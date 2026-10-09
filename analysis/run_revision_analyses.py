from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from pcum.model import (
    apply_regime,
    evaluate_portfolios,
    simulate_package_replications,
    sku_inclusion_thresholds,
    summarize_simulation,
)

ROOT = Path(__file__).resolve().parents[1]

COST_COMPONENTS = [
    "product_cost_jpy",
    "unmet_demand_cost_jpy",
    "purchase_event_cost_jpy",
    "packaging_cost_jpy",
    "storage_cost_jpy",
    "freshness_cost_jpy",
    "handling_cost_jpy",
    "adaptation_cost_jpy",
]

COMPARISON_METRICS = [
    "generalized_cost_jpy",
    "physical_discard_kg",
    "purchases",
    "packaging_mass_kg",
    "storage_kg_days",
    "mean_age_at_consumption_days",
    *COST_COMPONENTS,
]


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config/default.yaml").read_text())


def run_point_job(job: dict) -> dict:
    replications = simulate_package_replications(**job)
    return summarize_simulation(
        replications,
        job["package_kg"],
        job["household"],
        job["scenario"],
    )


def simulate_point_grid(
    config: dict,
    scenarios: list[tuple[dict, list[dict]]],
    package_sizes: list[float],
    seed_offset: int,
) -> pd.DataFrame:
    jobs = []
    for scenario_index, (scenario, households) in enumerate(scenarios):
        for household_index, household in enumerate(households):
            seed = (
                int(config["project"]["seed"])
                + seed_offset
                + scenario_index * 10000
                + household_index * 100
            )
            for package_kg in package_sizes:
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
        rows = [run_point_job(job) for job in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            rows = list(executor.map(run_point_job, jobs))
    return pd.DataFrame(rows)


def sensitivity_scenario(
    config: dict,
    name: str,
    **regime_updates: float | str,
) -> dict:
    regime = {"name": name, **regime_updates}
    scenario = apply_regime(config, regime)
    scenario["project"]["replications"] = int(config["sensitivity"]["replications"])
    return scenario


def household_weights(config: dict) -> dict[str, float]:
    return {
        household["name"]: household["scenario_weight"]
        for household in config["households"]
    }


def build_parameter_evidence_audit(config: dict) -> None:
    rows = [
        {
            "parameter": "natural consumption quantum",
            "configured_value": f"{config['rice']['natural_quantum_g']:g}",
            "unit": "g uncooked rice",
            "evidence_class": "empirically anchored",
            "source_id": "maff_rice_go_mass",
            "model_role": "reference lattice unit",
            "limitation": "A mass convention, not an event-probability estimate.",
        },
        {
            "parameter": "annual consumption",
            "configured_value": "32.0–213.6",
            "unit": "kg/scenario-year",
            "evidence_class": "empirically anchored",
            "source_id": "maff_rice_consumption_per_capita",
            "model_role": "scenario event-rate calibration",
            "limitation": (
                "53.4 kg/person-year anchors scenarios; class values are not "
                "estimated household-segment means."
            ),
        },
        {
            "parameter": "household composition weights",
            "configured_value": "0.15475–0.1905",
            "unit": "scenario weight",
            "evidence_class": "scenario assumption",
            "source_id": "statistics_japan_2025",
            "model_role": "design-scenario aggregation",
            "limitation": (
                "Only the one-person share is empirically anchored; the six "
                "weights are not fitted population weights."
            ),
        },
        {
            "parameter": "freshness threshold",
            "configured_value": "30",
            "unit": "days",
            "evidence_class": "empirically anchored",
            "source_id": "maff_rice_storage",
            "model_role": "start of aging and spoilage exposure",
            "limitation": (
                "Storage guidance anchors a scenario threshold, not a measured "
                "discard boundary."
            ),
        },
        {
            "parameter": "usage-event size probabilities",
            "configured_value": "six discrete distributions",
            "unit": "probability",
            "evidence_class": "unidentified",
            "source_id": "none",
            "model_role": "lattice demand process",
            "limitation": "No household diary or scanner data were fitted.",
        },
        {
            "parameter": "event interarrival distribution",
            "configured_value": "Gamma shape 4",
            "unit": "distribution",
            "evidence_class": "scenario assumption",
            "source_id": "none",
            "model_role": "stochastic timing",
            "limitation": "Mean is calibrated; shape is not empirically estimated.",
        },
        {
            "parameter": "adaptation behavior",
            "configured_value": "probability 0.30–0.55; ratio 0.70–0.75",
            "unit": "probability and fraction",
            "evidence_class": "unidentified",
            "source_id": "none",
            "model_role": "final-batch adjustment and backlog",
            "limitation": "Behavioral response is a transparent scenario input.",
        },
        {
            "parameter": "spoilage hazard",
            "configured_value": (
                f"{config['costs']['spoilage_hazard_per_day_after_threshold']:g}"
            ),
            "unit": "per day after threshold",
            "evidence_class": "unidentified",
            "source_id": "none",
            "model_role": "inventory exit",
            "limitation": "No rice-household hazard was estimated.",
        },
        {
            "parameter": "purchase-event cost",
            "configured_value": f"{config['costs']['purchase_event_jpy']:g}",
            "unit": "JPY/event",
            "evidence_class": "scenario assumption",
            "source_id": "none",
            "model_role": "shopping and ordering burden",
            "limitation": "Break-even analysis varies this coefficient.",
        },
        {
            "parameter": "packaging mass function",
            "configured_value": "8 + 9 P^(2/3)",
            "unit": "g/package",
            "evidence_class": "scenario assumption",
            "source_id": "none",
            "model_role": "package-material intensity",
            "limitation": "No manufacturer bill of materials was available.",
        },
        {
            "parameter": "packaging material cost",
            "configured_value": (
                f"{config['costs']['packaging_material_jpy_per_kg']:g}"
            ),
            "unit": "JPY/kg packaging",
            "evidence_class": "unidentified",
            "source_id": "none",
            "model_role": "packaging cost",
            "limitation": "No procurement data were available.",
        },
        {
            "parameter": "storage cost",
            "configured_value": f"{config['costs']['storage_jpy_per_kg_day']:g}",
            "unit": "JPY/kg-day",
            "evidence_class": "unidentified",
            "source_id": "none",
            "model_role": "inventory carrying cost",
            "limitation": "No household shadow-price estimate was available.",
        },
        {
            "parameter": "freshness cost",
            "configured_value": (
                f"{config['costs']['freshness_jpy_per_kg_day']:g}"
            ),
            "unit": "JPY/kg-day beyond threshold",
            "evidence_class": "unidentified",
            "source_id": "none",
            "model_role": "quality loss",
            "limitation": "No willingness-to-pay estimate was available.",
        },
        {
            "parameter": "handling cost",
            "configured_value": (
                f"{config['costs']['handling_jpy_per_purchase_kg_squared']:g}"
            ),
            "unit": "JPY/purchase-kg²",
            "evidence_class": "unidentified",
            "source_id": "none",
            "model_role": "large-package inconvenience",
            "limitation": "No ergonomics or labor-cost estimate was available.",
        },
        {
            "parameter": "size discount",
            "configured_value": (
                f"{config['costs']['size_discount_fraction_per_log_kg']:g}"
            ),
            "unit": "fraction per log kg",
            "evidence_class": "scenario assumption",
            "source_id": "none",
            "model_role": "price–size relationship",
            "limitation": "No retail price panel was fitted.",
        },
        {
            "parameter": "unmet-demand penalty",
            "configured_value": (
                f"{config['costs']['unmet_demand_jpy_per_kg']:g}"
            ),
            "unit": "JPY/kg",
            "evidence_class": "scenario assumption",
            "source_id": "none",
            "model_role": "service-loss penalty",
            "limitation": "No revealed or stated preference estimate was available.",
        },
        {
            "parameter": "SKU complexity",
            "configured_value": (
                f"{config['costs']['sku_complexity_jpy_per_household_year']:g}"
            ),
            "unit": "JPY/household-year/additional SKU",
            "evidence_class": "unidentified",
            "source_id": "none",
            "model_role": "assortment and production complexity",
            "limitation": (
                "No producer cost allocation was available; analytical "
                "break-even thresholds replace an empirical point claim."
            ),
        },
    ]
    frame = pd.DataFrame(rows)
    frame.to_csv(ROOT / "tables/parameter_evidence_table.csv", index=False)
    counts = frame["evidence_class"].value_counts().sort_index()
    report = [
        "# Parameter evidence audit",
        "",
        "The classification distinguishes empirical estimation from calibration",
        "anchors and transparent scenario inputs. No unidentified parameter is",
        "presented as an estimate.",
        "",
        "## Classification counts",
        "",
    ]
    report.extend(
        f"- {evidence_class}: {count}"
        for evidence_class, count in counts.items()
    )
    report.extend(
        [
            "",
            "## Consequence for interpretation",
            "",
            "The zero-discard proposition and SKU-inclusion inequality are",
            "structural. Numerical package optima, discard quantities, monetary",
            "costs, and phase boundaries are scenario-dependent because key",
            "behavioral and producer-cost coefficients are unidentified.",
            "",
            "The annual-consumption, household-composition, natural-quantum, and",
            "freshness inputs use public anchors, but the model does not claim",
            "that the six scenario weights or event probabilities estimate the",
            "Japanese household population. The dense sensitivity analyses show",
            "how decisions change when the most consequential unidentified",
            "parameters vary.",
            "",
            "The machine-readable audit is `tables/parameter_evidence_table.csv`.",
        ]
    )
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports/PARAMETER_EVIDENCE_AUDIT.md").write_text(
        "\n".join(report) + "\n"
    )


def weighted_size_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (regime, package_kg), group in frame.groupby(["regime", "package_kg"]):
        row: dict[str, float | str] = {
            "regime": regime,
            "package_kg": package_kg,
        }
        for metric in COMPARISON_METRICS:
            row[metric] = float(
                (group[metric] * group["scenario_weight"]).sum()
            )
        rows.append(row)
    return pd.DataFrame(rows)


def run_negative_controls(config: dict, size_results: pd.DataFrame) -> None:
    weighted = weighted_size_metrics(size_results)
    baseline = weighted[weighted["regime"] == "baseline"].set_index("package_kg")
    rows = []
    for control in [
        "no_discrete_consumption_quantum",
        "randomized_non_lattice_usage",
    ]:
        comparison = weighted[weighted["regime"] == control].set_index("package_kg")
        for package_kg in baseline.index:
            for metric in COMPARISON_METRICS:
                discrete = float(baseline.loc[package_kg, metric])
                continuous = float(comparison.loc[package_kg, metric])
                rows.append(
                    {
                        "control": control,
                        "package_kg": package_kg,
                        "metric": metric,
                        "discrete_value": discrete,
                        "continuous_value": continuous,
                        "discrete_minus_continuous": discrete - continuous,
                        "relative_difference_fraction": (
                            (discrete - continuous) / abs(continuous)
                            if abs(continuous) > 1e-12
                            else np.nan
                        ),
                    }
                )
    pd.DataFrame(rows).to_csv(
        ROOT / "output/negative_control_comparison.csv",
        index=False,
    )

    pathway_rows = []
    for regime in [
        "baseline",
        "no_discrete_consumption_quantum",
        "randomized_non_lattice_usage",
        "full_carry_no_spoilage",
        "continuous_no_spoilage",
    ]:
        regime_frame = weighted[weighted["regime"] == regime]
        best_package = float(
            regime_frame.loc[
                regime_frame["generalized_cost_jpy"].idxmin(),
                "package_kg",
            ]
        )
        for basis, package_kg in [
            ("regime_specific_best_single", best_package),
            ("baseline_best_single", 9.0),
        ]:
            selected = regime_frame[regime_frame["package_kg"] == package_kg].iloc[0]
            row = {
                "regime": regime,
                "comparison_basis": basis,
                "package_kg": package_kg,
            }
            for metric in COMPARISON_METRICS:
                row[metric] = selected[metric]
            pathway_rows.append(row)
    pd.DataFrame(pathway_rows).to_csv(
        ROOT / "output/mechanism_pathway_comparison.csv",
        index=False,
    )

    factorial_regimes = {
        (1, 1): "baseline",
        (0, 1): "no_discrete_consumption_quantum",
        (1, 0): "full_carry_no_spoilage",
        (0, 0): "continuous_no_spoilage",
    }
    factorial_rows = []
    indexed = weighted.set_index(["regime", "package_kg"])
    for package_kg in config["rice"]["candidate_package_kg"]:
        for metric in COMPARISON_METRICS:
            y11 = float(indexed.loc[(factorial_regimes[(1, 1)], package_kg), metric])
            y01 = float(indexed.loc[(factorial_regimes[(0, 1)], package_kg), metric])
            y10 = float(indexed.loc[(factorial_regimes[(1, 0)], package_kg), metric])
            y00 = float(indexed.loc[(factorial_regimes[(0, 0)], package_kg), metric])
            factorial_rows.append(
                {
                    "package_kg": package_kg,
                    "metric": metric,
                    "continuous_no_spoilage": y00,
                    "lattice_main_at_no_spoilage": y10 - y00,
                    "spoilage_main_under_continuous": y01 - y00,
                    "lattice_spoilage_interaction": y11 - y10 - y01 + y00,
                    "discrete_with_spoilage": y11,
                }
            )
    pd.DataFrame(factorial_rows).to_csv(
        ROOT / "output/lattice_factorial_decomposition.csv",
        index=False,
    )


def adjusted_purchase_cost(
    frame: pd.DataFrame,
    multiplier: float,
) -> pd.DataFrame:
    adjusted = frame.copy()
    adjusted["generalized_cost_jpy"] = (
        adjusted["generalized_cost_jpy"]
        - adjusted["purchase_event_cost_jpy"]
        + adjusted["purchase_event_cost_jpy"] * multiplier
    )
    adjusted["purchase_event_cost_jpy"] *= multiplier
    return adjusted


def run_dense_phase_map(config: dict) -> None:
    hazard_levels = config["sensitivity"]["spoilage_hazard_multipliers"]
    scenarios = []
    for hazard in hazard_levels:
        name = f"spoilage_intensity_{hazard:g}"
        scenario = sensitivity_scenario(
            config,
            name,
            spoilage_hazard_multiplier=float(hazard),
        )
        scenarios.append((scenario, deepcopy(config["households"])))
    size_frame = simulate_point_grid(
        config,
        scenarios,
        config["rice"]["candidate_package_kg"],
        seed_offset=2000000,
    )
    hazard_lookup = {
        f"spoilage_intensity_{hazard:g}": hazard for hazard in hazard_levels
    }
    size_frame.insert(
        0,
        "spoilage_hazard_multiplier",
        size_frame["regime"].map(hazard_lookup),
    )
    size_frame.to_csv(
        ROOT / "output/spoilage_intensity_size_metrics.csv",
        index=False,
    )

    weights = household_weights(config)
    phase_rows = []
    threshold_rows = []
    for hazard in hazard_levels:
        regime = f"spoilage_intensity_{hazard:g}"
        hazard_frame = size_frame[size_frame["regime"] == regime]
        for purchase_multiplier in config["sensitivity"][
            "purchase_event_cost_multipliers"
        ]:
            adjusted = adjusted_purchase_cost(hazard_frame, purchase_multiplier)
            zero_complexity = evaluate_portfolios(
                adjusted,
                config["rice"]["candidate_package_kg"],
                weights,
                complexity_cost=0.0,
            )
            thresholds = sku_inclusion_thresholds(
                adjusted,
                config["rice"]["candidate_package_kg"],
                weights,
            )
            for threshold in thresholds.itertuples(index=False):
                threshold_rows.append(
                    {
                        "spoilage_hazard_multiplier": hazard,
                        "purchase_event_cost_multiplier": purchase_multiplier,
                        **threshold._asdict(),
                    }
                )
            for complexity in config["sensitivity"][
                "sku_complexity_jpy_per_household_year"
            ]:
                portfolios = zero_complexity.copy()
                portfolios["system_cost_jpy"] = (
                    portfolios["consumer_cost_jpy"]
                    + (portfolios["sku_count"] - 1) * complexity
                )
                minimum = float(portfolios["system_cost_jpy"].min())
                best = portfolios.loc[portfolios["system_cost_jpy"].idxmin()]
                benchmark = portfolios[
                    portfolios["portfolio"] == "2|5|10"
                ].iloc[0]
                phase_rows.append(
                    {
                        "spoilage_hazard_multiplier": hazard,
                        "purchase_event_cost_multiplier": purchase_multiplier,
                        "sku_complexity_jpy_per_household_year": complexity,
                        "optimal_sku_count": int(best["sku_count"]),
                        "optimal_portfolio": best["portfolio"],
                        "system_cost_jpy": best["system_cost_jpy"],
                        "consumer_cost_jpy": best["consumer_cost_jpy"],
                        "physical_discard_kg": best["physical_discard_kg"],
                        "packaging_mass_kg": best["packaging_mass_kg"],
                        "benchmark_portfolio": "2|5|10",
                        "benchmark_regret_jpy": (
                            benchmark["consumer_cost_jpy"]
                            + 2 * complexity
                            - minimum
                        ),
                    }
                )
    pd.DataFrame(phase_rows).to_csv(
        ROOT / "output/sku_phase_map.csv",
        index=False,
    )
    pd.DataFrame(threshold_rows).to_csv(
        ROOT / "output/sku_phase_threshold_curves.csv",
        index=False,
    )


def run_consumption_sensitivity(config: dict) -> None:
    multipliers = config["sensitivity"]["annual_consumption_multipliers"]
    scenarios = []
    for multiplier in multipliers:
        households = deepcopy(config["households"])
        for household in households:
            household["annual_consumption_kg"] *= float(multiplier)
        scenario = sensitivity_scenario(
            config,
            f"annual_consumption_{multiplier:.2f}",
        )
        scenarios.append((scenario, households))
    size_frame = simulate_point_grid(
        config,
        scenarios,
        config["rice"]["candidate_package_kg"],
        seed_offset=3000000,
    )
    multiplier_lookup = {
        f"annual_consumption_{multiplier:.2f}": multiplier
        for multiplier in multipliers
    }
    size_frame.insert(
        0,
        "annual_consumption_multiplier",
        size_frame["regime"].map(multiplier_lookup),
    )
    size_frame.to_csv(
        ROOT / "output/continuous_consumption_size_metrics.csv",
        index=False,
    )

    weights = household_weights(config)
    complexity = float(config["costs"]["sku_complexity_jpy_per_household_year"])
    portfolio_frames = []
    summary_rows = []
    weighted_anchor = sum(
        household["scenario_weight"] * household["annual_consumption_kg"]
        for household in config["households"]
    )
    for multiplier in multipliers:
        regime = f"annual_consumption_{multiplier:.2f}"
        subset = size_frame[size_frame["regime"] == regime]
        portfolios = evaluate_portfolios(
            subset,
            config["rice"]["candidate_package_kg"],
            weights,
            complexity_cost=complexity,
        )
        portfolios.insert(0, "annual_consumption_multiplier", multiplier)
        portfolio_frames.append(portfolios)
        best_by_count = (
            portfolios.sort_values(["sku_count", "system_cost_jpy"])
            .groupby("sku_count")
            .first()
        )
        best = portfolios.loc[portfolios["system_cost_jpy"].idxmin()]
        benchmark = portfolios[portfolios["portfolio"] == "2|5|10"].iloc[0]
        thresholds = sku_inclusion_thresholds(
            subset,
            config["rice"]["candidate_package_kg"],
            weights,
        ).set_index("from_sku_count")
        summary_rows.append(
            {
                "annual_consumption_multiplier": multiplier,
                "weighted_annual_consumption_kg": weighted_anchor * multiplier,
                "minimum_scenario_annual_consumption_kg": (
                    min(
                        household["annual_consumption_kg"]
                        for household in config["households"]
                    )
                    * multiplier
                ),
                "maximum_scenario_annual_consumption_kg": (
                    max(
                        household["annual_consumption_kg"]
                        for household in config["households"]
                    )
                    * multiplier
                ),
                "best_one_sku_portfolio": best_by_count.loc[1, "portfolio"],
                "best_two_sku_portfolio": best_by_count.loc[2, "portfolio"],
                "best_three_sku_portfolio": best_by_count.loc[3, "portfolio"],
                "global_optimal_sku_count": int(best["sku_count"]),
                "global_optimal_portfolio": best["portfolio"],
                "global_system_cost_jpy": best["system_cost_jpy"],
                "global_physical_discard_kg": best["physical_discard_kg"],
                "global_packaging_mass_kg": best["packaging_mass_kg"],
                "benchmark_regret_jpy": (
                    benchmark["system_cost_jpy"] - best["system_cost_jpy"]
                ),
                "one_to_two_break_even_complexity_jpy": thresholds.loc[
                    1, "break_even_complexity_jpy_per_added_sku"
                ],
                "two_to_three_break_even_complexity_jpy": thresholds.loc[
                    2, "break_even_complexity_jpy_per_added_sku"
                ],
            }
        )
    pd.concat(portfolio_frames, ignore_index=True).to_csv(
        ROOT / "output/continuous_consumption_portfolios.csv",
        index=False,
    )
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(
        ROOT / "output/continuous_consumption_summary.csv",
        index=False,
    )

    transition_rows = []
    for column in [
        "best_one_sku_portfolio",
        "best_two_sku_portfolio",
        "best_three_sku_portfolio",
        "global_optimal_portfolio",
    ]:
        prior = None
        prior_multiplier = None
        for row in summary.to_dict("records"):
            current = row[column]
            if prior is not None and current != prior:
                transition_rows.append(
                    {
                        "outcome": column,
                        "lower_multiplier": prior_multiplier,
                        "upper_multiplier": row[
                            "annual_consumption_multiplier"
                        ],
                        "from_portfolio": prior,
                        "to_portfolio": current,
                    }
                )
            prior = current
            prior_multiplier = row["annual_consumption_multiplier"]
    pd.DataFrame(transition_rows).to_csv(
        ROOT / "output/consumption_transition_thresholds.csv",
        index=False,
    )


def run_candidate_grid_robustness(config: dict) -> None:
    dense_sizes = sorted(
        set(config["sensitivity"]["dense_candidate_package_kg"])
        | set(config["rice"]["candidate_package_kg"])
    )
    scenario = sensitivity_scenario(config, "dense_candidate_grid")
    size_frame = simulate_point_grid(
        config,
        [(scenario, deepcopy(config["households"]))],
        dense_sizes,
        seed_offset=4000000,
    )
    size_frame.to_csv(
        ROOT / "output/dense_grid_size_household_metrics.csv",
        index=False,
    )
    weights = household_weights(config)
    complexity = float(config["costs"]["sku_complexity_jpy_per_household_year"])
    portfolio_frames = []
    summary_rows = []
    for grid_name, candidate_sizes in [
        ("coarse", config["rice"]["candidate_package_kg"]),
        ("dense", dense_sizes),
    ]:
        subset = size_frame[size_frame["package_kg"].isin(candidate_sizes)]
        portfolios = evaluate_portfolios(
            subset,
            candidate_sizes,
            weights,
            complexity_cost=complexity,
        )
        portfolios.insert(0, "candidate_grid", grid_name)
        portfolio_frames.append(portfolios)
        for sku_count in [1, 2, 3]:
            best = portfolios[
                portfolios["sku_count"] == sku_count
            ].sort_values("system_cost_jpy").iloc[0]
            summary_rows.append(
                {
                    "candidate_grid": grid_name,
                    "candidate_count": len(candidate_sizes),
                    "sku_count": sku_count,
                    "best_portfolio": best["portfolio"],
                    "system_cost_jpy": best["system_cost_jpy"],
                    "consumer_cost_jpy": best["consumer_cost_jpy"],
                    "physical_discard_kg": best["physical_discard_kg"],
                    "packaging_mass_kg": best["packaging_mass_kg"],
                }
            )
    pd.concat(portfolio_frames, ignore_index=True).to_csv(
        ROOT / "output/dense_grid_portfolio_results.csv",
        index=False,
    )
    pd.DataFrame(summary_rows).to_csv(
        ROOT / "output/candidate_grid_robustness.csv",
        index=False,
    )


def update_manuscript_values() -> None:
    values = pd.read_csv(ROOT / "manuscript_values.csv")
    thresholds = pd.read_csv(
        ROOT / "output/sku_inclusion_thresholds.csv"
    ).set_index(["regime", "from_sku_count"])
    phase = pd.read_csv(ROOT / "output/sku_phase_map.csv")
    phase_shares = phase["optimal_sku_count"].value_counts(normalize=True)
    modal_portfolio_share = phase["optimal_portfolio"].value_counts(
        normalize=True
    ).iloc[0]
    contrasts = pd.read_csv(ROOT / "output/portfolio_contrasts.csv").set_index(
        ["regime", "contrast"]
    )
    robust = pd.read_csv(ROOT / "output/robust_portfolios.csv")
    minimax = robust.loc[robust["maximum_regret_jpy"].idxmin()]
    consumption = pd.read_csv(
        ROOT / "output/continuous_consumption_summary.csv"
    ).set_index("annual_consumption_multiplier")
    grid = pd.read_csv(ROOT / "output/candidate_grid_robustness.csv").set_index(
        ["candidate_grid", "sku_count"]
    )
    revision_rows = [
        {
            "value_id": "one_to_two_sku_threshold_jpy",
            "value": thresholds.loc[
                ("baseline", 1),
                "break_even_complexity_jpy_per_added_sku",
            ],
            "unit": "JPY/household-year per added SKU",
            "analysis_source": "output/sku_inclusion_thresholds.csv",
            "input_source": "output/size_household_metrics.csv",
            "code_source": "src/pcum/model.py:sku_inclusion_thresholds",
            "manuscript_location": "Results 3.6",
        },
        {
            "value_id": "two_to_three_sku_threshold_jpy",
            "value": thresholds.loc[
                ("baseline", 2),
                "break_even_complexity_jpy_per_added_sku",
            ],
            "unit": "JPY/household-year per added SKU",
            "analysis_source": "output/sku_inclusion_thresholds.csv",
            "input_source": "output/size_household_metrics.csv",
            "code_source": "src/pcum/model.py:sku_inclusion_thresholds",
            "manuscript_location": "Results 3.6",
        },
        {
            "value_id": "phase_one_sku_share",
            "value": phase_shares.get(1, 0.0),
            "unit": "fraction of phase-map cells",
            "analysis_source": "output/sku_phase_map.csv",
            "input_source": "config/default.yaml",
            "code_source": "analysis/run_revision_analyses.py:run_dense_phase_map",
            "manuscript_location": "Results 3.7",
        },
        {
            "value_id": "phase_two_sku_share",
            "value": phase_shares.get(2, 0.0),
            "unit": "fraction of phase-map cells",
            "analysis_source": "output/sku_phase_map.csv",
            "input_source": "config/default.yaml",
            "code_source": "analysis/run_revision_analyses.py:run_dense_phase_map",
            "manuscript_location": "Results 3.7",
        },
        {
            "value_id": "phase_three_sku_share",
            "value": phase_shares.get(3, 0.0),
            "unit": "fraction of phase-map cells",
            "analysis_source": "output/sku_phase_map.csv",
            "input_source": "config/default.yaml",
            "code_source": "analysis/run_revision_analyses.py:run_dense_phase_map",
            "manuscript_location": "Results 3.7",
        },
        {
            "value_id": "phase_modal_portfolio_share",
            "value": modal_portfolio_share,
            "unit": "fraction of phase-map cells",
            "analysis_source": "output/sku_phase_map.csv",
            "input_source": "config/default.yaml",
            "code_source": "analysis/run_revision_analyses.py:run_dense_phase_map",
            "manuscript_location": "Results 3.7",
        },
        {
            "value_id": "two_vs_one_ci_low_jpy",
            "value": contrasts.loc[
                ("baseline", "best_1_minus_best_2"),
                "ci_low_jpy",
            ],
            "unit": "JPY/household-year",
            "analysis_source": "output/portfolio_contrasts.csv",
            "input_source": "output/portfolio_replications.csv.gz",
            "code_source": "analysis/run_analysis.py:portfolio_contrasts",
            "manuscript_location": "Results 3.5",
        },
        {
            "value_id": "two_vs_one_ci_high_jpy",
            "value": contrasts.loc[
                ("baseline", "best_1_minus_best_2"),
                "ci_high_jpy",
            ],
            "unit": "JPY/household-year",
            "analysis_source": "output/portfolio_contrasts.csv",
            "input_source": "output/portfolio_replications.csv.gz",
            "code_source": "analysis/run_analysis.py:portfolio_contrasts",
            "manuscript_location": "Results 3.5",
        },
        {
            "value_id": "minimax_portfolio",
            "value": minimax["portfolio"],
            "unit": "kg packages",
            "analysis_source": "output/robust_portfolios.csv",
            "input_source": "output/portfolio_results.csv",
            "code_source": "analysis/run_analysis.py:run_portfolios",
            "manuscript_location": "Results 3.9",
        },
        {
            "value_id": "minimax_max_regret_jpy",
            "value": minimax["maximum_regret_jpy"],
            "unit": "JPY/household-year",
            "analysis_source": "output/robust_portfolios.csv",
            "input_source": "output/portfolio_results.csv",
            "code_source": "analysis/run_analysis.py:run_portfolios",
            "manuscript_location": "Results 3.9",
        },
        {
            "value_id": "low_consumption_best_single",
            "value": consumption.loc[0.5, "best_one_sku_portfolio"],
            "unit": "kg package",
            "analysis_source": "output/continuous_consumption_summary.csv",
            "input_source": "config/default.yaml",
            "code_source": (
                "analysis/run_revision_analyses.py:"
                "run_consumption_sensitivity"
            ),
            "manuscript_location": "Results 3.4",
        },
        {
            "value_id": "high_consumption_best_single",
            "value": consumption.loc[1.5, "best_one_sku_portfolio"],
            "unit": "kg package",
            "analysis_source": "output/continuous_consumption_summary.csv",
            "input_source": "config/default.yaml",
            "code_source": (
                "analysis/run_revision_analyses.py:"
                "run_consumption_sensitivity"
            ),
            "manuscript_location": "Results 3.4",
        },
        {
            "value_id": "dense_grid_best_single",
            "value": grid.loc[("dense", 1), "best_portfolio"],
            "unit": "kg package",
            "analysis_source": "output/candidate_grid_robustness.csv",
            "input_source": "config/default.yaml",
            "code_source": (
                "analysis/run_revision_analyses.py:"
                "run_candidate_grid_robustness"
            ),
            "manuscript_location": "Results 3.8",
        },
        {
            "value_id": "dense_grid_best_two",
            "value": grid.loc[("dense", 2), "best_portfolio"],
            "unit": "kg packages",
            "analysis_source": "output/candidate_grid_robustness.csv",
            "input_source": "config/default.yaml",
            "code_source": (
                "analysis/run_revision_analyses.py:"
                "run_candidate_grid_robustness"
            ),
            "manuscript_location": "Results 3.8",
        },
        {
            "value_id": "dense_grid_best_three",
            "value": grid.loc[("dense", 3), "best_portfolio"],
            "unit": "kg packages",
            "analysis_source": "output/candidate_grid_robustness.csv",
            "input_source": "config/default.yaml",
            "code_source": (
                "analysis/run_revision_analyses.py:"
                "run_candidate_grid_robustness"
            ),
            "manuscript_location": "Results 3.8",
        },
    ]
    values = values[
        ~values["value_id"].isin(row["value_id"] for row in revision_rows)
    ]
    pd.concat([values, pd.DataFrame(revision_rows)], ignore_index=True).to_csv(
        ROOT / "manuscript_values.csv",
        index=False,
    )


def main() -> None:
    config = load_config()
    build_parameter_evidence_audit(config)
    size_results = pd.read_csv(ROOT / "output/size_household_metrics.csv")
    run_negative_controls(config, size_results)
    run_dense_phase_map(config)
    run_consumption_sensitivity(config)
    run_candidate_grid_robustness(config)
    update_manuscript_values()


if __name__ == "__main__":
    main()
