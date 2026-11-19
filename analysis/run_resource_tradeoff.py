"""Conditional dry-rice/primary-packaging comparison at matched consumption."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import PercentFormatter
from run_analysis import load_config
from scipy.stats import t

from pcum.model import apply_regime, simulate_package_replications

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "phase_a"


def packaging_break_even(large_intensity, small_intensity, small_exit):
    """Large-pack exit share at packaging parity, with zero net stock change."""
    return 1 - (large_intensity / small_intensity) * (1 - small_exit)


def buy_size(options, handling_threshold):
    """Illustrative assignment for a household with a given handling threshold."""
    return max((size for size in options if size <= handling_threshold), default=min(options))


def load_study_inputs(config):
    retail = pd.read_csv(EVIDENCE / "RICE_RETAIL_PACKAGE_OPTIONS.csv")
    observed = set(retail.loc[retail["bag_count"] == 1, "primary_bag_kg"])
    sizes = tuple(sorted(map(float, config["rice"]["benchmark_market_portfolio_kg"])))
    if not set(sizes).issubset(observed):
        raise ValueError("The comparison requires listings for each individual bag size.")
    bags = pd.read_csv(EVIDENCE / "PACKAGING_MASS_EVIDENCE.csv")
    proxy = bags.loc[bags["package_family"] == "heiko_clear"].dropna(subset=["listed_g_per_bag"])
    masses = proxy.groupby("rice_capacity_kg")["listed_g_per_bag"].agg(["min", "max"]) / 1000
    if set(sizes) - set(masses.index) or (masses.loc[list(sizes), "min"] <= 0).any():
        raise ValueError("Every comparison size needs a positive catalog proxy.")
    return sizes, {size: tuple(masses.loc[size]) for size in sizes}


def paired_ci(values, confidence):
    margin = t.ppf((1 + confidence) / 2, len(values) - 1) * values.sem()
    return values.mean() - margin, values.mean() + margin


def assert_control(frame, years):
    """Opening inventory is known to be zero; closing inventory is a stock."""
    np.testing.assert_allclose(frame["physical_discard_kg"], 0, atol=0, rtol=0)
    np.testing.assert_allclose(frame["consumed_kg"], frame["demanded_kg"], atol=1e-9, rtol=0)
    residual = (
        frame["purchased_kg"]
        - frame["consumed_kg"]
        - frame["physical_discard_kg"]
        - frame["ending_inventory_kg"] / years
    )
    np.testing.assert_allclose(residual, 0, atol=1e-9, rtol=0)


def contrast(reference, alternative, sizes, masses, confidence):
    large, small = sizes
    np.testing.assert_allclose(
        reference["consumed_kg"], alternative["consumed_kg"], atol=1e-9, rtol=0
    )
    large_low, large_high = masses[large]
    small_low, small_high = masses[small]
    large_count = reference["purchases"]
    small_count = alternative["purchases"]
    exits = alternative["physical_discard_kg"] - reference["physical_discard_kg"]
    exit_low, exit_high = paired_ci(exits, confidence)
    same_size = large == small
    # Unchanged alternatives share the same (unknown) unit mass even at the endpoints.
    delta_low = small_count * small_low - large_count * large_high if not same_size else exits
    delta_high = small_count * small_high - large_count * large_low if not same_size else exits
    ci_low, _ = paired_ci(delta_low, confidence)
    _, ci_high = paired_ci(delta_high, confidence)
    values = {
        "ref_package_kg": large,
        "alt_package_kg": small,
        "ref_primary_proxy_kg_per_household_year_low": (large_count * large_low).mean(),
        "ref_primary_proxy_kg_per_household_year_high": (large_count * large_high).mean(),
        "alt_primary_proxy_kg_per_household_year_low": (small_count * small_low).mean(),
        "alt_primary_proxy_kg_per_household_year_high": (small_count * small_high).mean(),
        "delta_primary_proxy_kg_per_household_year_low": delta_low.mean(),
        "delta_primary_proxy_kg_per_household_year_high": delta_high.mean(),
        "delta_primary_proxy_paired_mc_ci_low": ci_low,
        "delta_primary_proxy_paired_mc_ci_high": ci_high,
        "delta_exit_kg_per_household_year": exits.mean(),
        "delta_exit_paired_mc_ci_low": exit_low,
        "delta_exit_paired_mc_ci_high": exit_high,
        "retail_primary_kg_per_household_year": None,
        "paired_confidence_level": confidence,
    }
    for prefix, frame in [("ref", reference), ("alt", alternative)]:
        for metric in [
            "consumed_kg",
            "purchased_kg",
            "physical_discard_kg",
            "ending_inventory_kg",
            "purchases",
        ]:
            values[f"{prefix}_{metric}"] = frame[metric].mean()
    values["observed_market_pareto"] = "unidentified"
    if same_size:
        values["conditional_control_pareto"] = "same_assignment"
        return values
    if ci_low > 0:
        values["conditional_control_pareto"] = "reference_lower_proxy_packaging_same_exit"
    elif ci_high < 0:
        values["conditional_control_pareto"] = "alternative_lower_proxy_packaging_same_exit"
    else:
        values["conditional_control_pareto"] = "proxy_packaging_order_unresolved_at_mc_precision"
    ratio_low = (large_low / large) / (small_high / small)
    ratio_high = (large_high / large) / (small_low / small)
    q_low = packaging_break_even(ratio_high, 1, 0)
    q_high = packaging_break_even(ratio_low, 1, 0)
    large_count_ratio = large_count.mean() / small_count.mean()
    consumed = reference["consumed_kg"].mean()
    values.update(
        control_mass_ratio_alt_over_ref_at_packaging_parity=large_count_ratio,
        control_alt_g_at_packaging_parity_low=large_count_ratio * large_low * 1000,
        control_alt_g_at_packaging_parity_high=large_count_ratio * large_high * 1000,
        steady_intensity_ratio_ref_over_alt_low=ratio_low,
        steady_intensity_ratio_ref_over_alt_high=ratio_high,
        steady_ref_exit_fraction_at_packaging_parity_given_alt_zero_low=q_low,
        steady_ref_exit_fraction_at_packaging_parity_given_alt_zero_high=q_high,
        steady_ref_exit_kg_per_household_year_given_alt_zero_low=consumed * q_low / (1 - q_low),
        steady_ref_exit_kg_per_household_year_given_alt_zero_high=consumed * q_high / (1 - q_high),
    )
    return values


def run(config, sizes, masses):
    portfolios = (sizes[-1:], sizes[1:], sizes)
    control = next(r for r in config["regimes"] if r["name"] == "full_carry_no_spoilage")
    scenario = apply_regime(config, dict(control, adaptation_probability=0.0))
    scenario["project"]["burn_in_years"] = 0
    confidence = scenario["project"]["confidence_level"]
    years = scenario["project"]["horizon_years"]
    rows = []
    for index, household in enumerate(config["households"]):
        assigned = [buy_size(p, household["handling_threshold_kg"]) for p in portfolios]
        seed = config["project"]["seed"] + index * 100
        frames = {}
        for size in sorted(set(assigned)):
            frame = simulate_package_replications(size, household, scenario, seed)
            assert_control(frame, years)
            frames[size] = frame
        for a, b in [(0, 1), (0, 2), (1, 2)]:
            large, small = assigned[a], assigned[b]
            row = dict(
                household=household["name"],
                ref_offered_kg="|".join(f"{size:g}" for size in portfolios[a]),
                alt_offered_kg="|".join(f"{size:g}" for size in portfolios[b]),
                regime="zero_exit_same_service_no_adaptation_empty_start",
                horizon_years=years,
                replications=len(frames[large]),
                annual_target_consumption_kg=household["annual_consumption_kg"],
                opening_stock_kg=0,
                empirical_exit_overlap="no_capacity_specific_exit_bound",
            )
            row.update(contrast(frames[large], frames[small], (large, small), masses, confidence))
            rows.append(row)
    return pd.DataFrame(rows)


def plot_resource_quantities(frame, masses, target):
    example = frame[frame["household"] == "single_low"]
    consumed = example["ref_consumed_kg"].iloc[0]
    largest_exit = example["steady_ref_exit_kg_per_household_year_given_alt_zero_high"].max()
    rice_exit = np.linspace(0, largest_exit, 300)
    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    fig.subplots_adjust(left=0.13, right=0.98, top=0.91, bottom=0.23)
    for (size, (low, high)), color in zip(
        sorted(masses.items()), ["#156884", "#a64100", "#67548b"], strict=True
    ):
        pack_low = (consumed + rice_exit) * low / size
        pack_high = (consumed + rice_exit) * high / size
        ax.plot(rice_exit, (pack_low + pack_high) / 2, label=f"{size:g} kg bag", color=color)
        ax.fill_between(rice_exit, pack_low, pack_high, color=color, alpha=0.2)
    ax.set(
        xlabel="Dry rice leaving as waste (kg per household-year)",
        ylabel="Primary packaging (kg per household-year)",
        title="Conditional resource quantities at fixed consumption",
    )
    ax.grid(alpha=0.2)
    ax.legend(loc="upper left", frameon=False)
    fig.text(
        0.5,
        0.055,
        f"Illustrative low-demand single-person household, consumption {consumed:.2f} kg/year.\n"
        "Zero net stock change. Shading spans HEIKO specification values.",
        ha="center",
        fontsize=9,
    )
    fig.savefig(target, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_exit_parity(frame, target):
    changes = frame[frame["ref_package_kg"] > frame["alt_package_kg"]]
    pairs = changes.drop_duplicates(["ref_package_kg", "alt_package_kg"]).sort_values(
        ["ref_package_kg", "alt_package_kg"]
    )
    limit = min(1, pairs["steady_ref_exit_fraction_at_packaging_parity_given_alt_zero_high"].max())
    x = np.linspace(0, limit, 300)
    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    fig.subplots_adjust(left=0.13, right=0.98, top=0.91, bottom=0.23)
    for row, color in zip(pairs.itertuples(), ["#156884", "#a64100", "#67548b"], strict=True):
        low = packaging_break_even(row.steady_intensity_ratio_ref_over_alt_high, 1, x)
        high = packaging_break_even(row.steady_intensity_ratio_ref_over_alt_low, 1, x)
        label = f"{row.ref_package_kg:g} → {row.alt_package_kg:g} kg packaging parity"
        ax.plot(x, (low + high) / 2, label=label, color=color)
        ax.fill_between(x, low, high, color=color, alpha=0.2)
    ax.plot(x, x, "--", color="#444444", label="Rice exit parity")
    ax.set(
        xlim=(0, limit),
        ylim=(0, 1.12 * (limit + limit * (1 - limit))),
        xlabel="Smaller pack exit (% of purchased dry rice)",
        ylabel="Larger pack exit (% of purchased dry rice)",
        title="Conditional break-even under HEIKO bag specifications",
    )
    ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.grid(alpha=0.2)
    ax.legend(loc="upper left", frameon=False)
    fig.text(
        0.5,
        0.055,
        "Shown range illustrates the thresholds. Shading spans catalog values.\n"
        "Equal consumption and zero net stock change. Exit data by pack size unavailable.",
        ha="center",
        fontsize=9,
    )
    fig.savefig(target, dpi=180, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=EVIDENCE)
    args = parser.parse_args()
    figdir = args.output_dir / "RESOURCE_TRADEOFF_FIGURES"
    figdir.mkdir(parents=True, exist_ok=True)
    config = load_config()
    sizes, masses = load_study_inputs(config)
    results = run(config, sizes, masses)
    results.to_csv(
        args.output_dir / "RESOURCE_TRADEOFF_RESULTS.csv", index=False, float_format="%.10g"
    )
    plot_resource_quantities(results, masses, figdir / "resource_quantities.png")
    plot_exit_parity(results, figdir / "exit_share_parity.png")
