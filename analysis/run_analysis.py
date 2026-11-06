from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.stats import norm

from pcum.model import (
    apply_regime,
    evaluate_portfolios,
    lattice_diagnostics,
    manufacturing_safety_margin,
    simulate_package_replications,
    sku_inclusion_thresholds,
    summarize_simulation,
    terminal_residual_distribution,
)

ROOT = Path(__file__).resolve().parents[1]


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config/default.yaml").read_text())


def run_terminal_residual(config: dict) -> pd.DataFrame:
    rows = []
    for household_index, household in enumerate(config["households"]):
        for size_index, package_kg in enumerate(config["rice"]["candidate_package_kg"]):
            result = terminal_residual_distribution(
                package_kg=package_kg,
                usage_g=household["usage_g"],
                probabilities=household["usage_probability"],
                replications=20000,
                seed=config["project"]["seed"] + household_index * 100 + size_index,
            )
            result["household"] = household["name"]
            rows.append(result)
    frame = pd.DataFrame(rows)
    frame.to_csv(ROOT / "output/terminal_residual.csv", index=False)
    return frame


def run_lattice_diagnostics(config: dict) -> pd.DataFrame:
    rows = []
    for household in config["households"]:
        for package_kg in config["rice"]["candidate_package_kg"]:
            row = lattice_diagnostics(package_kg, household["usage_g"])
            row["household"] = household["name"]
            rows.append(row)
    frame = pd.DataFrame(rows)
    frame.to_csv(ROOT / "output/lattice_diagnostics.csv", index=False)
    return frame


def run_inventory_models(config: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    jobs = []
    for regime in config["regimes"]:
        scenario = apply_regime(config, regime)
        for household_index, household in enumerate(config["households"]):
            for package_kg in config["rice"]["candidate_package_kg"]:
                seed = config["project"]["seed"] + household_index * 100
                jobs.append(
                    {
                        "package_kg": package_kg,
                        "household": household,
                        "scenario": scenario,
                        "seed": seed,
                    }
                )
    workers = int(config["project"].get("workers", 1))
    if workers == 1:
        job_results = [run_simulation_job(job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            job_results = list(executor.map(run_simulation_job, jobs))
    frame = pd.DataFrame([result["summary"] for result in job_results])
    replication_frame = pd.concat(
        [pd.DataFrame(result["replications"]) for result in job_results],
        ignore_index=True,
    )
    frame.to_csv(ROOT / "output/size_household_metrics.csv", index=False)
    replication_frame.to_csv(
        ROOT / "output/simulation_replications.csv.gz",
        index=False,
        compression="gzip",
    )
    return frame, replication_frame


def run_simulation_job(job: dict) -> dict:
    replications = simulate_package_replications(**job)
    summary = summarize_simulation(
        replications,
        job["package_kg"],
        job["household"],
        job["scenario"],
    )
    replications.insert(0, "scenario_weight", job["household"]["scenario_weight"])
    replications.insert(0, "package_kg", job["package_kg"])
    replications.insert(0, "household", job["household"]["name"])
    replications.insert(0, "regime", job["scenario"]["regime_name"])
    return {"summary": summary, "replications": replications.to_dict("records")}


def evaluate_portfolio_replications(
    point_results: pd.DataFrame,
    replication_results: pd.DataFrame,
    household_weights: dict[str, float],
    complexity_cost: float,
) -> pd.DataFrame:
    rows = []
    for portfolio_row in point_results.itertuples(index=False):
        choices = {
            item.split(":", maxsplit=1)[0]: float(item.split(":", maxsplit=1)[1])
            for item in portfolio_row.household_choices.split(";")
        }
        selected = []
        for household, package_kg in choices.items():
            subset = replication_results[
                (replication_results["household"] == household)
                & (replication_results["package_kg"] == package_kg)
            ].copy()
            weight = household_weights[household]
            subset["weighted_cost"] = subset["generalized_cost_jpy"] * weight
            subset["weighted_discard"] = subset["physical_discard_kg"] * weight
            subset["weighted_packaging"] = subset["packaging_mass_kg"] * weight
            selected.append(
                subset[
                    [
                        "replication",
                        "weighted_cost",
                        "weighted_discard",
                        "weighted_packaging",
                    ]
                ]
            )
        combined = pd.concat(selected).groupby("replication", as_index=False).sum()
        combined["system_cost_jpy"] = (
            combined["weighted_cost"]
            + max(0, portfolio_row.sku_count - 1) * complexity_cost
        )
        combined["regime"] = replication_results["regime"].iloc[0]
        combined["sku_count"] = portfolio_row.sku_count
        combined["portfolio"] = portfolio_row.portfolio
        combined.rename(
            columns={
                "weighted_discard": "physical_discard_kg",
                "weighted_packaging": "packaging_mass_kg",
            },
            inplace=True,
        )
        rows.append(
            combined[
                [
                    "regime",
                    "replication",
                    "sku_count",
                    "portfolio",
                    "system_cost_jpy",
                    "physical_discard_kg",
                    "packaging_mass_kg",
                ]
            ]
        )
    return pd.concat(rows, ignore_index=True)


def portfolio_uncertainty(
    point_results: pd.DataFrame,
    replication_results: pd.DataFrame,
    confidence: float,
) -> pd.DataFrame:
    critical_value = float(norm.ppf(0.5 + confidence / 2.0))
    rows = []
    for sku_count, point_group in point_results.groupby("sku_count"):
        point_group = point_group.sort_values("system_cost_jpy")
        best_portfolio = point_group.iloc[0]["portfolio"]
        best_replications = replication_results[
            (replication_results["sku_count"] == sku_count)
            & (replication_results["portfolio"] == best_portfolio)
        ].set_index("replication")["system_cost_jpy"]
        replication_group = replication_results[
            replication_results["sku_count"] == sku_count
        ]
        winners = replication_group.loc[
            replication_group.groupby("replication")["system_cost_jpy"].idxmin(),
            "portfolio",
        ].value_counts(normalize=True)
        for point_row in point_group.itertuples(index=False):
            samples = replication_group[
                replication_group["portfolio"] == point_row.portfolio
            ].set_index("replication")["system_cost_jpy"]
            delta = samples - best_replications
            delta_mean = float(delta.mean())
            delta_se = float(delta.std(ddof=1) / np.sqrt(len(delta)))
            rows.append(
                {
                    "regime": replication_results["regime"].iloc[0],
                    "sku_count": sku_count,
                    "portfolio": point_row.portfolio,
                    "system_cost_jpy": point_row.system_cost_jpy,
                    "system_cost_jpy_se": float(
                        samples.std(ddof=1) / np.sqrt(len(samples))
                    ),
                    "delta_vs_group_min_jpy": delta_mean,
                    "delta_vs_group_min_se": delta_se,
                    "delta_vs_group_min_ci_low": delta_mean
                    - critical_value * delta_se,
                    "delta_vs_group_min_ci_high": delta_mean
                    + critical_value * delta_se,
                    "equivalent_to_group_min": (
                        delta_mean - critical_value * delta_se <= 0.0
                    ),
                    "probability_lowest_cost_within_sku_count": float(
                        winners.get(point_row.portfolio, 0.0)
                    ),
                    "confidence_level": confidence,
                }
            )
    return pd.DataFrame(rows)


def portfolio_contrasts(
    point_results: pd.DataFrame,
    replication_results: pd.DataFrame,
    confidence: float,
) -> pd.DataFrame:
    critical_value = float(norm.ppf(0.5 + confidence / 2.0))
    selected = {
        sku_count: group.sort_values("system_cost_jpy")["portfolio"].tolist()
        for sku_count, group in point_results.groupby("sku_count")
    }
    comparisons = [
        ("best_1_minus_best_2", selected[1][0], selected[2][0]),
        ("best_1_minus_best_3", selected[1][0], selected[3][0]),
        ("best_2_minus_best_3", selected[2][0], selected[3][0]),
        ("runner_up_minus_best_1", selected[1][1], selected[1][0]),
        ("runner_up_minus_best_2", selected[2][1], selected[2][0]),
        ("runner_up_minus_best_3", selected[3][1], selected[3][0]),
    ]
    rows = []
    for name, minuend, subtrahend in comparisons:
        left = replication_results[
            replication_results["portfolio"] == minuend
        ].set_index("replication")["system_cost_jpy"]
        right = replication_results[
            replication_results["portfolio"] == subtrahend
        ].set_index("replication")["system_cost_jpy"]
        difference = left - right
        mean = float(difference.mean())
        standard_error = float(difference.std(ddof=1) / np.sqrt(len(difference)))
        rows.append(
            {
                "regime": replication_results["regime"].iloc[0],
                "contrast": name,
                "minuend_portfolio": minuend,
                "subtrahend_portfolio": subtrahend,
                "mean_difference_jpy": mean,
                "standard_error_jpy": standard_error,
                "ci_low_jpy": mean - critical_value * standard_error,
                "ci_high_jpy": mean + critical_value * standard_error,
                "probability_positive": float((difference > 0.0).mean()),
                "confidence_level": confidence,
            }
        )
    return pd.DataFrame(rows)


def run_portfolios(
    config: dict,
    size_results: pd.DataFrame,
    replication_results: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    replication_rows = []
    uncertainty_rows = []
    contrast_rows = []
    weights = {
        household["name"]: household["scenario_weight"]
        for household in config["households"]
    }
    market_portfolio = "|".join(
        f"{size:g}" for size in config["rice"]["benchmark_market_portfolio_kg"]
    )
    for regime in config["regimes"]:
        scenario = apply_regime(config, regime)
        subset = size_results[size_results["regime"] == regime["name"]]
        evaluated = evaluate_portfolios(
            size_results=subset,
            candidate_sizes=config["rice"]["candidate_package_kg"],
            household_weights=weights,
            complexity_cost=scenario["costs"][
                "sku_complexity_jpy_per_household_year"
            ],
        )
        evaluated["regime"] = regime["name"]
        evaluated["is_current_market"] = evaluated["portfolio"] == market_portfolio
        regime_replications = replication_results[
            replication_results["regime"] == regime["name"]
        ]
        evaluated_replications = evaluate_portfolio_replications(
            evaluated,
            regime_replications,
            weights,
            scenario["costs"]["sku_complexity_jpy_per_household_year"],
        )
        uncertainty = portfolio_uncertainty(
            evaluated,
            evaluated_replications,
            float(config["project"]["confidence_level"]),
        )
        contrasts = portfolio_contrasts(
            evaluated,
            evaluated_replications,
            float(config["project"]["confidence_level"]),
        )
        evaluated = evaluated.merge(
            uncertainty.drop(columns=["system_cost_jpy"]),
            on=["regime", "sku_count", "portfolio"],
            how="left",
        )
        rows.append(evaluated)
        replication_rows.append(evaluated_replications)
        uncertainty_rows.append(uncertainty)
        contrast_rows.append(contrasts)
    frame = pd.concat(rows, ignore_index=True)
    frame.to_csv(ROOT / "output/portfolio_results.csv", index=False)
    pd.concat(replication_rows, ignore_index=True).to_csv(
        ROOT / "output/portfolio_replications.csv.gz",
        index=False,
        compression="gzip",
    )
    pd.concat(uncertainty_rows, ignore_index=True).to_csv(
        ROOT / "output/portfolio_uncertainty.csv", index=False
    )
    pd.concat(contrast_rows, ignore_index=True).to_csv(
        ROOT / "output/portfolio_contrasts.csv", index=False
    )

    regret_wide = frame.pivot(
        index=["sku_count", "portfolio"], columns="regime", values="regret_jpy"
    )
    robust = regret_wide.reset_index()
    robust["maximum_regret_jpy"] = regret_wide.max(axis=1).to_numpy()
    robust["mean_regret_jpy"] = regret_wide.mean(axis=1).to_numpy()
    robust.sort_values(
        ["maximum_regret_jpy", "mean_regret_jpy"]
    ).to_csv(ROOT / "output/robust_portfolios.csv", index=False)
    return frame


def run_sku_thresholds(
    config: dict,
    size_results: pd.DataFrame,
) -> pd.DataFrame:
    weights = {
        household["name"]: household["scenario_weight"]
        for household in config["households"]
    }
    rows = []
    for regime in [item["name"] for item in config["regimes"]]:
        subset = size_results[size_results["regime"] == regime]
        thresholds = sku_inclusion_thresholds(
            subset,
            config["rice"]["candidate_package_kg"],
            weights,
        )
        thresholds.insert(0, "regime", regime)
        rows.append(thresholds)
    frame = pd.concat(rows, ignore_index=True)
    frame.to_csv(ROOT / "output/sku_inclusion_thresholds.csv", index=False)
    return frame


def run_manufacturing() -> pd.DataFrame:
    rows = []
    for target_g in [1800, 2000, 5000]:
        for sigma_g in [1, 2, 5, 10, 20]:
            rows.append(manufacturing_safety_margin(target_g, sigma_g, 0.001))
    frame = pd.DataFrame(rows)
    frame.to_csv(ROOT / "output/manufacturing_precision.csv", index=False)
    return frame


def build_summaries(
    config: dict,
    size_results: pd.DataFrame,
    portfolio_results: pd.DataFrame,
) -> None:
    baseline = size_results[size_results["regime"] == "baseline"].copy()
    baseline["cost_regret_jpy"] = baseline["generalized_cost_jpy"] - baseline.groupby(
        "household"
    )["generalized_cost_jpy"].transform("min")
    baseline.to_csv(ROOT / "output/baseline_size_comparison.csv", index=False)

    rows = []
    current = "|".join(
        f"{size:g}" for size in config["rice"]["benchmark_market_portfolio_kg"]
    )
    for regime in [item["name"] for item in config["regimes"]]:
        subset = portfolio_results[portfolio_results["regime"] == regime]
        for sku_count in [1, 2, 3]:
            best = subset[subset["sku_count"] == sku_count].iloc[0]
            rows.append(
                {
                    "regime": regime,
                    "comparison": f"minimum_point_estimate_{sku_count}_sku",
                    "portfolio": best["portfolio"],
                    "system_cost_jpy": best["system_cost_jpy"],
                    "physical_discard_kg": best["physical_discard_kg"],
                    "packaging_mass_kg": best["packaging_mass_kg"],
                    "regret_jpy": best["regret_jpy"],
                }
            )
        current_row = subset[subset["portfolio"] == current].iloc[0]
        rows.append(
            {
                "regime": regime,
                "comparison": "benchmark_market_portfolio",
                "portfolio": current,
                "system_cost_jpy": current_row["system_cost_jpy"],
                "physical_discard_kg": current_row["physical_discard_kg"],
                "packaging_mass_kg": current_row["packaging_mass_kg"],
                "regret_jpy": current_row["regret_jpy"],
            }
        )
    pd.DataFrame(rows).to_csv(
        ROOT / "output/boundary_sensitivity_summary.csv", index=False
    )


def build_convergence_diagnostics(config: dict, size_results: pd.DataFrame) -> None:
    relative_threshold = float(config["project"]["relative_mcse_threshold"])
    absolute_thresholds = config["project"]["absolute_mcse_threshold"]
    rows = []
    for metric in [
        "generalized_cost_jpy",
        "physical_discard_kg",
        "packaging_mass_kg",
        "mean_age_at_consumption_days",
    ]:
        means = size_results[metric].abs()
        standard_errors = size_results[f"{metric}_se"]
        relative_mcse = standard_errors / means.replace(0.0, np.nan)
        exact_zero = (means == 0.0) & (standard_errors == 0.0)
        absolute_threshold = float(absolute_thresholds[metric])
        converged = (
            (relative_mcse <= relative_threshold)
            | (standard_errors <= absolute_threshold)
            | exact_zero
        )
        for index in size_results.index:
            rows.append(
                {
                    "regime": size_results.at[index, "regime"],
                    "household": size_results.at[index, "household"],
                    "package_kg": size_results.at[index, "package_kg"],
                    "metric": metric,
                    "mean": size_results.at[index, metric],
                    "mcse": size_results.at[index, f"{metric}_se"],
                    "relative_mcse": relative_mcse.at[index],
                    "relative_threshold": relative_threshold,
                    "absolute_threshold": absolute_threshold,
                    "converged": bool(converged.at[index]),
                }
            )
    pd.DataFrame(rows).to_csv(
        ROOT / "output/convergence_diagnostics.csv", index=False
    )


def build_manuscript_values(
    config: dict,
    terminal: pd.DataFrame,
    size_results: pd.DataFrame,
    portfolios: pd.DataFrame,
    manufacturing: pd.DataFrame,
) -> None:
    baseline = size_results[size_results["regime"] == "baseline"]
    no_spoilage = size_results[size_results["regime"] == "full_carry_no_spoilage"]
    best_single = portfolios[
        (portfolios["regime"] == "baseline") & (portfolios["sku_count"] == 1)
    ].iloc[0]
    best_two = portfolios[
        (portfolios["regime"] == "baseline") & (portfolios["sku_count"] == 2)
    ].iloc[0]
    best_three = portfolios[
        (portfolios["regime"] == "baseline") & (portfolios["sku_count"] == 3)
    ].iloc[0]
    current_name = "|".join(
        f"{size:g}" for size in config["rice"]["benchmark_market_portfolio_kg"]
    )
    current = portfolios[
        (portfolios["regime"] == "baseline")
        & (portfolios["portfolio"] == current_name)
    ].iloc[0]
    values = [
        {
            "value_id": "max_terminal_residual_g",
            "value": terminal["mean_terminal_residual_g"].max(),
            "unit": "g",
            "analysis_source": "output/terminal_residual.csv",
            "input_source": "config/default.yaml",
            "code_source": "src/pcum/model.py:terminal_residual_distribution",
            "manuscript_location": "Results 3.1",
        },
        {
            "value_id": "no_spoilage_max_discard_kg",
            "value": no_spoilage["physical_discard_kg"].max(),
            "unit": "kg/household-year",
            "analysis_source": "output/size_household_metrics.csv",
            "input_source": "config/default.yaml",
            "code_source": "src/pcum/model.py:simulate_package",
            "manuscript_location": "Results 3.2",
        },
        {
            "value_id": "baseline_max_discard_kg",
            "value": baseline["physical_discard_kg"].max(),
            "unit": "kg/household-year",
            "analysis_source": "output/size_household_metrics.csv",
            "input_source": "config/default.yaml",
            "code_source": "src/pcum/model.py:simulate_package",
            "manuscript_location": "Results 3.2",
        },
        {
            "value_id": "best_single_portfolio",
            "value": best_single["portfolio"],
            "unit": "kg package",
            "analysis_source": "output/portfolio_results.csv",
            "input_source": "config/default.yaml",
            "code_source": "src/pcum/model.py:evaluate_portfolios",
            "manuscript_location": "Results 3.3",
        },
        {
            "value_id": "best_two_portfolio",
            "value": best_two["portfolio"],
            "unit": "kg packages",
            "analysis_source": "output/portfolio_results.csv",
            "input_source": "config/default.yaml",
            "code_source": "src/pcum/model.py:evaluate_portfolios",
            "manuscript_location": "Results 3.3",
        },
        {
            "value_id": "best_three_portfolio",
            "value": best_three["portfolio"],
            "unit": "kg packages",
            "analysis_source": "output/portfolio_results.csv",
            "input_source": "config/default.yaml",
            "code_source": "src/pcum/model.py:evaluate_portfolios",
            "manuscript_location": "Results 3.3",
        },
        {
            "value_id": "two_vs_one_saving_jpy",
            "value": best_single["system_cost_jpy"] - best_two["system_cost_jpy"],
            "unit": "JPY/household-year",
            "analysis_source": "output/portfolio_results.csv",
            "input_source": "config/default.yaml",
            "code_source": "src/pcum/model.py:evaluate_portfolios",
            "manuscript_location": "Results 3.3",
        },
        {
            "value_id": "current_portfolio_regret_jpy",
            "value": current["regret_jpy"],
            "unit": "JPY/household-year",
            "analysis_source": "output/portfolio_results.csv",
            "input_source": "config/default.yaml",
            "code_source": "src/pcum/model.py:evaluate_portfolios",
            "manuscript_location": "Results 3.3",
        },
        {
            "value_id": "high_sigma_safety_margin_g",
            "value": manufacturing["safety_margin_g"].max(),
            "unit": "g",
            "analysis_source": "output/manufacturing_precision.csv",
            "input_source": "analysis/run_analysis.py",
            "code_source": "src/pcum/model.py:manufacturing_safety_margin",
            "manuscript_location": "Results 3.4",
        },
    ]
    pd.DataFrame(values).to_csv(ROOT / "manuscript_values.csv", index=False)


def main() -> None:
    for directory in ["output", "reports"]:
        (ROOT / directory).mkdir(parents=True, exist_ok=True)
    config = load_config()
    run_lattice_diagnostics(config)
    terminal = run_terminal_residual(config)
    size_results, replication_results = run_inventory_models(config)
    portfolios = run_portfolios(config, size_results, replication_results)
    run_sku_thresholds(config, size_results)
    manufacturing = run_manufacturing()
    build_summaries(config, size_results, portfolios)
    build_convergence_diagnostics(config, size_results)
    build_manuscript_values(
        config, terminal, size_results, portfolios, manufacturing
    )


if __name__ == "__main__":
    np.set_printoptions(suppress=True)
    main()
