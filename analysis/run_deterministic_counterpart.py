"""Gate 3 (SMPT): deterministic mean-trajectory counterpart ablation.

Evaluates the household x package-size grid and the SKU portfolio problem
under a fully deterministic model (constant interval, constant usage, no
adaptive consumption), then measures the decision regret incurred when the
deterministically chosen portfolios are re-evaluated under the canonical
stochastic results (baseline regime).

Outputs:
    output/deterministic_size_household_metrics.csv
    output/deterministic_portfolio_results.csv
    output/deterministic_sku_inclusion_thresholds.csv
    output/deterministic_counterpart_comparison.csv
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from pcum.model import (
    apply_regime,
    evaluate_portfolios,
    simulate_package_deterministic,
    sku_inclusion_thresholds,
)

ROOT = Path(__file__).resolve().parents[1]


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config/default.yaml").read_text())


def main() -> None:
    config = load_config()
    regime = next(r for r in config["regimes"] if r["name"] == "baseline")
    scenario = apply_regime(config, regime)
    weights = {
        household["name"]: household["scenario_weight"]
        for household in config["households"]
    }
    candidate_sizes = config["rice"]["candidate_package_kg"]
    complexity_cost = scenario["costs"]["sku_complexity_jpy_per_household_year"]

    rows = []
    for household in config["households"]:
        for package_kg in candidate_sizes:
            rows.append(
                simulate_package_deterministic(
                    package_kg, household, scenario
                )
            )
    det_metrics = pd.DataFrame(rows)
    det_metrics.to_csv(
        ROOT / "output/deterministic_size_household_metrics.csv", index=False
    )

    det_portfolios = evaluate_portfolios(
        size_results=det_metrics,
        candidate_sizes=candidate_sizes,
        household_weights=weights,
        complexity_cost=complexity_cost,
    )
    det_portfolios.to_csv(
        ROOT / "output/deterministic_portfolio_results.csv", index=False
    )

    det_thresholds = sku_inclusion_thresholds(
        size_results=det_metrics,
        candidate_sizes=candidate_sizes,
        household_weights=weights,
    )
    det_thresholds.to_csv(
        ROOT / "output/deterministic_sku_inclusion_thresholds.csv", index=False
    )

    stoch = pd.read_csv(ROOT / "output/portfolio_results.csv")
    stoch = stoch[stoch["regime"] == "baseline"]

    comparison_rows = []
    for sku_count in (1, 2, 3):
        det_pick = det_portfolios[
            det_portfolios["sku_count"] == sku_count
        ].nsmallest(1, "system_cost_jpy").iloc[0]
        stoch_best = stoch[stoch["sku_count"] == sku_count].nsmallest(
            1, "system_cost_jpy"
        ).iloc[0]
        det_pick_in_stoch = stoch[
            (stoch["sku_count"] == sku_count)
            & (stoch["portfolio"] == det_pick["portfolio"])
        ]
        if det_pick_in_stoch.empty:
            stochastic_cost = float("nan")
            regret = float("nan")
        else:
            stochastic_cost = float(
                det_pick_in_stoch.iloc[0]["system_cost_jpy"]
            )
            regret = stochastic_cost - float(stoch_best["system_cost_jpy"])
        comparison_rows.append(
            {
                "sku_count": sku_count,
                "deterministic_optimal_portfolio": det_pick["portfolio"],
                "stochastic_optimal_portfolio": stoch_best["portfolio"],
                "identities_match": det_pick["portfolio"]
                == stoch_best["portfolio"],
                "deterministic_pick_cost_under_stochastic_jpy": stochastic_cost,
                "stochastic_optimum_cost_jpy": float(
                    stoch_best["system_cost_jpy"]
                ),
                "decision_regret_jpy": regret,
            }
        )
    comparison = pd.DataFrame(comparison_rows)
    comparison.to_csv(
        ROOT / "output/deterministic_counterpart_comparison.csv", index=False
    )

    dense_sizes = sorted(
        set(config["sensitivity"]["dense_candidate_package_kg"])
    )
    dense_rows = []
    for household in config["households"]:
        for package_kg in dense_sizes:
            dense_rows.append(
                simulate_package_deterministic(
                    package_kg, household, scenario
                )
            )
    det_dense_metrics = pd.DataFrame(dense_rows)
    det_dense_metrics.to_csv(
        ROOT / "output/deterministic_dense_size_household_metrics.csv",
        index=False,
    )
    det_dense_portfolios = evaluate_portfolios(
        size_results=det_dense_metrics,
        candidate_sizes=dense_sizes,
        household_weights=weights,
        complexity_cost=complexity_cost,
    )
    det_dense_portfolios.to_csv(
        ROOT / "output/deterministic_dense_portfolio_results.csv", index=False
    )

    stoch_dense = pd.read_csv(
        ROOT / "output/dense_grid_portfolio_results.csv"
    )
    dense_comparison_rows = []
    for sku_count in (1, 2, 3):
        det_pick = det_dense_portfolios[
            det_dense_portfolios["sku_count"] == sku_count
        ].nsmallest(1, "system_cost_jpy").iloc[0]
        stoch_best = stoch_dense[
            stoch_dense["sku_count"] == sku_count
        ].nsmallest(1, "system_cost_jpy").iloc[0]
        det_pick_in_stoch = stoch_dense[
            (stoch_dense["sku_count"] == sku_count)
            & (stoch_dense["portfolio"] == det_pick["portfolio"])
        ]
        if det_pick_in_stoch.empty:
            stochastic_cost = float("nan")
            regret = float("nan")
        else:
            stochastic_cost = float(
                det_pick_in_stoch.iloc[0]["system_cost_jpy"]
            )
            regret = stochastic_cost - float(stoch_best["system_cost_jpy"])
        dense_comparison_rows.append(
            {
                "sku_count": sku_count,
                "deterministic_optimal_portfolio": det_pick["portfolio"],
                "stochastic_optimal_portfolio": stoch_best["portfolio"],
                "identities_match": det_pick["portfolio"]
                == stoch_best["portfolio"],
                "deterministic_pick_cost_under_stochastic_jpy": stochastic_cost,
                "stochastic_optimum_cost_jpy": float(
                    stoch_best["system_cost_jpy"]
                ),
                "decision_regret_jpy": regret,
            }
        )
    dense_comparison = pd.DataFrame(dense_comparison_rows)
    dense_comparison.to_csv(
        ROOT / "output/deterministic_dense_comparison.csv", index=False
    )

    update_manuscript_values(
        det_metrics, comparison, dense_comparison
    )

    print(comparison.to_string(index=False))
    print(dense_comparison.to_string(index=False))


def update_manuscript_values(
    det_metrics: pd.DataFrame,
    comparison: pd.DataFrame,
    dense_comparison: pd.DataFrame,
) -> None:
    baseline = pd.read_csv(ROOT / "output/size_household_metrics.csv")
    baseline = baseline[baseline["regime"] == "baseline"]
    merged = det_metrics.merge(
        baseline[
            [
                "household",
                "package_kg",
                "generalized_cost_jpy",
                "storage_kg_days",
                "mean_age_at_consumption_days",
            ]
        ],
        on=["household", "package_kg"],
        suffixes=("_det", "_stoch"),
    )
    cost_delta = (
        merged["generalized_cost_jpy_det"]
        - merged["generalized_cost_jpy_stoch"]
    )
    cost_rel = (
        cost_delta.abs()
        / merged["generalized_cost_jpy_stoch"].abs().clip(lower=1e-9)
    )
    storage_rel = (
        (merged["storage_kg_days_det"] - merged["storage_kg_days_stoch"]).abs()
        / merged["storage_kg_days_stoch"].abs().clip(lower=1e-9)
    )
    age_rel = (
        (
            merged["mean_age_at_consumption_days_det"]
            - merged["mean_age_at_consumption_days_stoch"]
        ).abs()
        / merged["mean_age_at_consumption_days_stoch"].abs().clip(lower=1e-9)
    )
    det_rows = [
        {
            "value_id": "det_cost_deviation_mean_jpy",
            "value": float(cost_delta.mean()),
            "unit": "JPY/household-year (deterministic minus stochastic)",
            "analysis_source": "output/deterministic_size_household_metrics.csv",
            "input_source": "output/size_household_metrics.csv",
            "code_source": "src/pcum/model.py:simulate_package_deterministic",
            "manuscript_location": "Results (deterministic ablation)",
        },
        {
            "value_id": "det_cost_max_relative_deviation",
            "value": float(cost_rel.max()),
            "unit": "relative deviation",
            "analysis_source": "output/deterministic_size_household_metrics.csv",
            "input_source": "output/size_household_metrics.csv",
            "code_source": "src/pcum/model.py:simulate_package_deterministic",
            "manuscript_location": "Results (deterministic ablation)",
        },
        {
            "value_id": "det_storage_max_relative_deviation",
            "value": float(storage_rel.max()),
            "unit": "relative deviation",
            "analysis_source": "output/deterministic_size_household_metrics.csv",
            "input_source": "output/size_household_metrics.csv",
            "code_source": "src/pcum/model.py:simulate_package_deterministic",
            "manuscript_location": "Results (deterministic ablation)",
        },
        {
            "value_id": "det_age_max_relative_deviation",
            "value": float(age_rel.max()),
            "unit": "relative deviation",
            "analysis_source": "output/deterministic_size_household_metrics.csv",
            "input_source": "output/size_household_metrics.csv",
            "code_source": "src/pcum/model.py:simulate_package_deterministic",
            "manuscript_location": "Results (deterministic ablation)",
        },
        {
            "value_id": "det_decision_regret_max_jpy",
            "value": float(comparison["decision_regret_jpy"].max()),
            "unit": "JPY/household-year",
            "analysis_source": "output/deterministic_counterpart_comparison.csv",
            "input_source": "output/portfolio_results.csv",
            "code_source": (
                "analysis/run_deterministic_counterpart.py"
            ),
            "manuscript_location": "Results (deterministic ablation)",
        },
        {
            "value_id": "det_portfolio_identities_match",
            "value": bool(comparison["identities_match"].all()),
            "unit": "boolean (all SKU counts)",
            "analysis_source": "output/deterministic_counterpart_comparison.csv",
            "input_source": "output/portfolio_results.csv",
            "code_source": (
                "analysis/run_deterministic_counterpart.py"
            ),
            "manuscript_location": "Results (deterministic ablation)",
        },
        {
            "value_id": "det_dense_max_regret_jpy",
            "value": float(
                dense_comparison["decision_regret_jpy"].max()
            ),
            "unit": "JPY/household-year",
            "analysis_source": "output/deterministic_dense_comparison.csv",
            "input_source": "output/dense_grid_portfolio_results.csv",
            "code_source": (
                "analysis/run_deterministic_counterpart.py"
            ),
            "manuscript_location": "Results (deterministic ablation)",
        },
        {
            "value_id": "det_dense_identity_match_count",
            "value": int(dense_comparison["identities_match"].sum()),
            "unit": "of 3 SKU counts",
            "analysis_source": "output/deterministic_dense_comparison.csv",
            "input_source": "output/dense_grid_portfolio_results.csv",
            "code_source": (
                "analysis/run_deterministic_counterpart.py"
            ),
            "manuscript_location": "Results (deterministic ablation)",
        },
    ]
    values = pd.read_csv(ROOT / "manuscript_values.csv")
    new_ids = {row["value_id"] for row in det_rows}
    values = values[~values["value_id"].isin(new_ids)]
    values = pd.concat(
        [values, pd.DataFrame(det_rows)], ignore_index=True
    )
    values.to_csv(ROOT / "manuscript_values.csv", index=False)


if __name__ == "__main__":
    main()
