from __future__ import annotations

import itertools
import math
from copy import deepcopy

import numpy as np
import pandas as pd
from scipy.stats import norm

METRIC_COLUMNS = [
    "generalized_cost_jpy",
    "product_cost_jpy",
    "unmet_demand_cost_jpy",
    "purchase_event_cost_jpy",
    "packaging_cost_jpy",
    "storage_cost_jpy",
    "freshness_cost_jpy",
    "handling_cost_jpy",
    "adaptation_cost_jpy",
    "physical_discard_kg",
    "purchases",
    "openings",
    "packaging_mass_kg",
    "storage_kg_days",
    "mean_age_at_consumption_days",
    "freshness_penalty_jpy",
    "adaptation_events",
    "purchased_kg",
    "ending_inventory_kg",
    "consumed_kg",
    "demanded_kg",
    "unmet_demand_kg",
    "opening_demand_backlog_kg",
    "service_level_fraction",
]


def zero_discard_balance_holds(
    initial_inventory_kg: float,
    purchased_kg: float,
    consumed_kg: float,
    ending_inventory_kg: float,
    non_discard_removals_kg: float = 0.0,
    tolerance: float = 1e-9,
) -> bool:
    quantities = [
        initial_inventory_kg,
        purchased_kg,
        consumed_kg,
        ending_inventory_kg,
        non_discard_removals_kg,
    ]
    if any(quantity < 0.0 for quantity in quantities):
        raise ValueError("Inventory-flow quantities must be nonnegative")
    balance = (
        initial_inventory_kg
        + purchased_kg
        - consumed_kg
        - ending_inventory_kg
        - non_discard_removals_kg
    )
    return math.isclose(balance, 0.0, rel_tol=0.0, abs_tol=tolerance)


def terminal_residual_distribution(
    package_kg: float,
    usage_g: list[float],
    probabilities: list[float],
    replications: int,
    seed: int,
) -> dict[str, float]:
    rng = np.random.default_rng(seed)
    package_g = package_kg * 1000.0
    residuals = np.empty(replications)
    for replication in range(replications):
        residual = package_g
        while True:
            planned = float(rng.choice(usage_g, p=probabilities))
            if planned > residual + 1e-9:
                break
            residual -= planned
        residuals[replication] = residual
    return {
        "package_kg": package_kg,
        "mean_terminal_residual_g": float(residuals.mean()),
        "median_terminal_residual_g": float(np.median(residuals)),
        "p95_terminal_residual_g": float(np.quantile(residuals, 0.95)),
        "zero_residual_probability": float(np.mean(residuals < 1e-9)),
    }


def packaging_mass_kg(package_kg: float, costs: dict) -> float:
    grams = costs["packaging_fixed_g"] + (
        costs["packaging_surface_g_per_kg_two_thirds"] * package_kg ** (2.0 / 3.0)
    )
    return grams / 1000.0


def lattice_diagnostics(package_kg: float, usage_g: list[float]) -> dict[str, float | bool]:
    package_g = int(round(package_kg * 1000.0))
    integer_usage = [int(round(value)) for value in usage_g]
    lattice_g = math.gcd(*integer_usage)
    return {
        "package_kg": package_kg,
        "package_g": package_g,
        "usage_lattice_g": lattice_g,
        "package_mod_lattice_g": package_g % lattice_g,
        "lattice_compatible": package_g % lattice_g == 0,
    }


def manufacturing_safety_margin(
    target_g: float,
    process_sigma_g: float,
    maximum_underfill_probability: float,
) -> dict[str, float]:
    safety_margin_g = float(
        norm.ppf(1.0 - maximum_underfill_probability) * process_sigma_g
    )
    return {
        "target_g": target_g,
        "process_sigma_g": process_sigma_g,
        "maximum_underfill_probability": maximum_underfill_probability,
        "safety_margin_g": safety_margin_g,
        "mean_fill_g": target_g + safety_margin_g,
        "expected_giveaway_fraction": safety_margin_g / target_g,
    }


def apply_regime(config: dict, regime: dict) -> dict:
    scenario = deepcopy(config)
    costs = scenario["costs"]
    for key, default in (
        ("spoilage_hazard_multiplier", 1.0),
        ("sku_complexity_multiplier", 1.0),
        ("packaging_cost_multiplier", 1.0),
        ("purchase_event_cost_multiplier", 1.0),
        ("adaptation_cost_multiplier", 1.0),
        ("handling_cost_multiplier", 1.0),
    ):
        scenario[key] = float(regime.get(key, default))
    scenario["usage_distribution"] = regime.get(
        "usage_distribution",
        "lognormal" if regime.get("continuous_usage", False) else "discrete",
    )
    scenario["adaptation_probability_override"] = regime.get("adaptation_probability")
    scenario["adaptation_min_ratio_override"] = regime.get("adaptation_min_ratio")
    scenario["regime_name"] = regime["name"]
    costs["sku_complexity_jpy_per_household_year"] *= scenario[
        "sku_complexity_multiplier"
    ]
    return scenario


def _usage_draw(
    rng: np.random.Generator,
    household: dict,
    distribution: str,
) -> float:
    values = np.asarray(household["usage_g"], dtype=float)
    probabilities = np.asarray(household["usage_probability"], dtype=float)
    if distribution == "discrete":
        return float(rng.choice(values, p=probabilities))
    mean = float(np.sum(values * probabilities))
    variance = float(np.sum(probabilities * (values - mean) ** 2))
    if variance <= 1e-12:
        return mean
    if distribution == "gamma":
        shape = mean * mean / variance
        scale = variance / mean
        return float(rng.gamma(shape=shape, scale=scale))
    if distribution != "lognormal":
        raise ValueError(f"Unknown usage distribution: {distribution}")
    cv_squared = variance / max(mean * mean, 1e-12)
    sigma_squared = math.log1p(cv_squared)
    sigma = math.sqrt(sigma_squared)
    mu = math.log(mean) - sigma_squared / 2.0
    return float(rng.lognormal(mu, sigma))


def _consume_fifo(
    lots: list[dict],
    amount_g: float,
    day: float,
    freshness_threshold_days: float,
) -> tuple[float, float, float]:
    remaining = amount_g
    age_mass = 0.0
    excess_age_mass = 0.0
    consumed = 0.0
    while remaining > 1e-9 and lots:
        lot = lots[0]
        take = min(remaining, lot["quantity_g"])
        age = day - lot["purchase_day"]
        age_mass += take * age
        excess_age_mass += take * max(0.0, age - freshness_threshold_days)
        consumed += take
        lot["quantity_g"] -= take
        remaining -= take
        if lot["quantity_g"] <= 1e-9:
            lots.pop(0)
    return consumed, age_mass, excess_age_mass


def _advance_lots(
    lots: list[dict],
    day: float,
    threshold_days: float,
    hazard: float,
) -> tuple[float, float]:
    discarded = 0.0
    storage_g_days = 0.0
    retained = []
    for lot in lots:
        start_day = lot["last_check_day"]
        threshold_day = lot["purchase_day"] + threshold_days
        pre_decay_days = max(0.0, min(day, threshold_day) - start_day)
        decay_days = max(0.0, day - max(start_day, threshold_day))
        quantity_g = lot["quantity_g"]
        storage_g_days += quantity_g * pre_decay_days
        if hazard > 0.0:
            decay_factor = math.exp(-hazard * decay_days)
            storage_g_days += quantity_g * (1.0 - decay_factor) / hazard
        else:
            decay_factor = 1.0
            storage_g_days += quantity_g * decay_days
        remaining_g = quantity_g * decay_factor
        loss = quantity_g - remaining_g
        lot["quantity_g"] = remaining_g
        lot["last_check_day"] = day
        discarded += loss
        if lot["quantity_g"] > 1e-9:
            retained.append(lot)
    lots[:] = retained
    return discarded, storage_g_days


def _simulate_one(
    package_kg: float,
    household: dict,
    scenario: dict,
    rng: np.random.Generator,
) -> dict[str, float]:
    years = float(scenario["project"]["horizon_years"])
    burn_in_years = float(scenario["project"].get("burn_in_years", 0.0))
    days_per_year = float(scenario["project"]["days_per_year"])
    burn_in_days = burn_in_years * days_per_year
    horizon_days = (years + burn_in_years) * days_per_year
    costs = scenario["costs"]
    mean_usage = float(
        np.dot(household["usage_g"], household["usage_probability"])
    )
    annual_events = household["annual_consumption_kg"] * 1000.0 / mean_usage
    mean_interval = days_per_year / annual_events
    adaptation_probability = (
        scenario["adaptation_probability_override"]
        if scenario["adaptation_probability_override"] is not None
        else household["adaptation_probability"]
    )
    adaptation_min_ratio = (
        scenario["adaptation_min_ratio_override"]
        if scenario["adaptation_min_ratio_override"] is not None
        else household["adaptation_min_ratio"]
    )
    package_g = package_kg * 1000.0
    pack_mass = packaging_mass_kg(package_kg, costs)
    hazard = (
        costs["spoilage_hazard_per_day_after_threshold"]
        * scenario["spoilage_hazard_multiplier"]
    )
    lots: list[dict] = []
    day = 0.0
    prior_day = 0.0
    purchases = 0
    purchased_g = 0.0
    discarded_g = 0.0
    consumed_g = 0.0
    age_mass = 0.0
    storage_kg_days = 0.0
    adaptation_events = 0
    freshness_penalty = 0.0
    demanded_g = 0.0
    demand_backlog_g = 0.0
    opening_backlog_g = 0.0
    measurement_started = False

    while True:
        interval = float(rng.gamma(shape=4.0, scale=mean_interval / 4.0))
        next_day = day + interval
        if next_day >= horizon_days:
            if day < burn_in_days <= horizon_days:
                _advance_lots(
                    lots,
                    burn_in_days,
                    household["freshness_threshold_days"],
                    hazard,
                )
            event_discarded_g, event_storage_g_days = _advance_lots(
                lots,
                horizon_days,
                household["freshness_threshold_days"],
                hazard,
            )
            if horizon_days >= burn_in_days:
                discarded_g += event_discarded_g
                storage_kg_days += event_storage_g_days / 1000.0
            break
        day = next_day
        measured = day >= burn_in_days
        if measured and not measurement_started:
            opening_backlog_g = demand_backlog_g
            measurement_started = True
        if prior_day < burn_in_days <= day:
            _advance_lots(
                lots,
                burn_in_days,
                household["freshness_threshold_days"],
                hazard,
            )
        prior_day = day
        event_discarded_g, event_storage_g_days = _advance_lots(
            lots,
            day,
            household["freshness_threshold_days"],
            hazard,
        )
        if measured:
            discarded_g += event_discarded_g
            storage_kg_days += event_storage_g_days / 1000.0
        base_planned_g = _usage_draw(
            rng,
            household,
            scenario["usage_distribution"],
        )
        if measured:
            demanded_g += base_planned_g
        planned_g = base_planned_g + demand_backlog_g
        inventory_g = sum(lot["quantity_g"] for lot in lots)
        adaptation_draw = rng.random()
        adapted = (
            0.0 < inventory_g < planned_g
            and inventory_g >= adaptation_min_ratio * planned_g
            and adaptation_draw < adaptation_probability
        )
        if adapted:
            demand_backlog_g = planned_g - inventory_g
            planned_g = inventory_g
            if measured:
                adaptation_events += 1
        else:
            demand_backlog_g = 0.0
            while inventory_g + 1e-9 < planned_g:
                lots.append(
                    {
                        "quantity_g": package_g,
                        "purchase_day": day,
                        "last_check_day": day,
                    }
                )
                if measured:
                    purchases += 1
                    purchased_g += package_g
                inventory_g += package_g
        consumed, event_age_mass, excess_age_mass = _consume_fifo(
            lots,
            planned_g,
            day,
            household["freshness_threshold_days"],
        )
        if measured:
            consumed_g += consumed
            age_mass += event_age_mass
            freshness_penalty += (
                excess_age_mass
                / 1000.0
                * costs["freshness_jpy_per_kg_day"]
            )

    ending_inventory_g = sum(lot["quantity_g"] for lot in lots)
    price_discount = costs["size_discount_fraction_per_log_kg"] * math.log(
        package_kg / scenario["rice"]["reference_package_kg"]
    )
    effective_price = scenario["rice"]["value_jpy_per_kg"] * max(
        0.75, 1.0 - price_discount
    )
    packaging_kg = purchases * pack_mass
    handling_excess = max(0.0, package_kg - household["handling_threshold_kg"])
    product_throughput_kg = (consumed_g + discarded_g) / 1000.0
    unmet_demand_kg = demand_backlog_g / 1000.0
    service_demand_g = demanded_g + opening_backlog_g
    product_cost = product_throughput_kg * effective_price
    unmet_demand_cost = unmet_demand_kg * costs["unmet_demand_jpy_per_kg"]
    purchase_event_cost = (
        purchases
        * costs["purchase_event_jpy"]
        * scenario["purchase_event_cost_multiplier"]
    )
    packaging_cost = (
        packaging_kg
        * costs["packaging_material_jpy_per_kg"]
        * scenario["packaging_cost_multiplier"]
    )
    storage_cost = storage_kg_days * costs["storage_jpy_per_kg_day"]
    handling_cost = (
        purchases
        * handling_excess**2
        * costs["handling_jpy_per_purchase_kg_squared"]
        * scenario["handling_cost_multiplier"]
    )
    adaptation_cost = (
        adaptation_events
        * costs["adaptation_jpy_per_event"]
        * scenario["adaptation_cost_multiplier"]
    )
    total_cost = (
        product_cost
        + unmet_demand_cost
        + purchase_event_cost
        + packaging_cost
        + storage_cost
        + freshness_penalty
        + handling_cost
        + adaptation_cost
    )
    scale = 1.0 / years
    return {
        "generalized_cost_jpy": total_cost * scale,
        "product_cost_jpy": product_cost * scale,
        "unmet_demand_cost_jpy": unmet_demand_cost * scale,
        "purchase_event_cost_jpy": purchase_event_cost * scale,
        "packaging_cost_jpy": packaging_cost * scale,
        "storage_cost_jpy": storage_cost * scale,
        "freshness_cost_jpy": freshness_penalty * scale,
        "handling_cost_jpy": handling_cost * scale,
        "adaptation_cost_jpy": adaptation_cost * scale,
        "physical_discard_kg": discarded_g / 1000.0 * scale,
        "purchases": purchases * scale,
        "openings": purchases * scale,
        "packaging_mass_kg": packaging_kg * scale,
        "storage_kg_days": storage_kg_days * scale,
        "mean_age_at_consumption_days": age_mass / max(consumed_g, 1e-12),
        "freshness_penalty_jpy": freshness_penalty * scale,
        "adaptation_events": adaptation_events * scale,
        "purchased_kg": purchased_g / 1000.0 * scale,
        "ending_inventory_kg": ending_inventory_g / 1000.0,
        "consumed_kg": consumed_g / 1000.0 * scale,
        "demanded_kg": demanded_g / 1000.0 * scale,
        "unmet_demand_kg": unmet_demand_kg * scale,
        "opening_demand_backlog_kg": opening_backlog_g / 1000.0 * scale,
        "service_level_fraction": (
            consumed_g / service_demand_g if service_demand_g > 1e-12 else 1.0
        ),
    }


def simulate_package_replications(
    package_kg: float,
    household: dict,
    scenario: dict,
    seed: int,
) -> pd.DataFrame:
    rows = []
    seed_sequence = np.random.SeedSequence(seed)
    for replication, child_seed in enumerate(
        seed_sequence.spawn(int(scenario["project"]["replications"]))
    ):
        row = _simulate_one(
            package_kg,
            household,
            scenario,
            np.random.default_rng(child_seed),
        )
        row["replication"] = replication
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_simulation(
    frame: pd.DataFrame,
    package_kg: float,
    household: dict,
    scenario: dict,
) -> dict[str, float | str]:
    result: dict[str, float | str] = {
        "regime": scenario["regime_name"],
        "household": household["name"],
        "package_kg": package_kg,
        "scenario_weight": household["scenario_weight"],
    }
    for column in METRIC_COLUMNS:
        mean = float(frame[column].mean())
        standard_error = float(frame[column].std(ddof=1) / math.sqrt(len(frame)))
        confidence = float(scenario["project"].get("confidence_level", 0.95))
        critical_value = float(norm.ppf(0.5 + confidence / 2.0))
        result[column] = mean
        result[f"{column}_se"] = standard_error
        result[f"{column}_ci_low"] = max(
            0.0, mean - critical_value * standard_error
        )
        result[f"{column}_ci_high"] = mean + critical_value * standard_error
    return result


def simulate_package(
    package_kg: float,
    household: dict,
    scenario: dict,
    seed: int,
) -> dict[str, float | str]:
    frame = simulate_package_replications(package_kg, household, scenario, seed)
    return summarize_simulation(frame, package_kg, household, scenario)


def evaluate_portfolios(
    size_results: pd.DataFrame,
    candidate_sizes: list[float],
    household_weights: dict[str, float],
    complexity_cost: float,
    max_skus: int = 3,
) -> pd.DataFrame:
    rows = []
    indexed = size_results.set_index(["household", "package_kg"])
    households = sorted(household_weights)
    for sku_count in range(1, max_skus + 1):
        for portfolio in itertools.combinations(candidate_sizes, sku_count):
            consumer_cost = 0.0
            chosen_sizes = {}
            physical_discard = 0.0
            packaging_mass = 0.0
            for household in households:
                alternatives = [
                    (
                        float(indexed.loc[(household, size), "generalized_cost_jpy"]),
                        size,
                    )
                    for size in portfolio
                ]
                cost, chosen = min(alternatives)
                weight = household_weights[household]
                consumer_cost += weight * cost
                physical_discard += weight * float(
                    indexed.loc[(household, chosen), "physical_discard_kg"]
                )
                packaging_mass += weight * float(
                    indexed.loc[(household, chosen), "packaging_mass_kg"]
                )
                chosen_sizes[household] = chosen
            complexity = max(0, sku_count - 1) * complexity_cost
            rows.append(
                {
                    "sku_count": sku_count,
                    "portfolio": "|".join(f"{size:g}" for size in portfolio),
                    "system_cost_jpy": consumer_cost + complexity,
                    "consumer_cost_jpy": consumer_cost,
                    "complexity_cost_jpy": complexity,
                    "physical_discard_kg": physical_discard,
                    "packaging_mass_kg": packaging_mass,
                    "household_choices": ";".join(
                        f"{household}:{chosen_sizes[household]:g}"
                        for household in households
                    ),
                }
            )
    result = pd.DataFrame(rows)
    minimum = result["system_cost_jpy"].min()
    result["regret_jpy"] = result["system_cost_jpy"] - minimum
    return result.sort_values(["sku_count", "system_cost_jpy"]).reset_index(drop=True)


def sku_inclusion_thresholds(
    size_results: pd.DataFrame,
    candidate_sizes: list[float],
    household_weights: dict[str, float],
    max_skus: int = 3,
) -> pd.DataFrame:
    portfolios = evaluate_portfolios(
        size_results,
        candidate_sizes,
        household_weights,
        complexity_cost=0.0,
        max_skus=max_skus,
    )
    best = (
        portfolios.sort_values(["sku_count", "consumer_cost_jpy"])
        .groupby("sku_count", as_index=False)
        .first()
        .set_index("sku_count")
    )
    rows = []
    for sku_count in range(1, max_skus):
        current = best.loc[sku_count]
        expanded = best.loc[sku_count + 1]
        current_sizes = set(str(current["portfolio"]).split("|"))
        expanded_sizes = set(str(expanded["portfolio"]).split("|"))
        rows.append(
            {
                "from_sku_count": sku_count,
                "to_sku_count": sku_count + 1,
                "best_from_portfolio": current["portfolio"],
                "best_to_portfolio": expanded["portfolio"],
                "from_consumer_cost_jpy": current["consumer_cost_jpy"],
                "to_consumer_cost_jpy": expanded["consumer_cost_jpy"],
                "marginal_variety_value_jpy": (
                    current["consumer_cost_jpy"]
                    - expanded["consumer_cost_jpy"]
                ),
                "break_even_complexity_jpy_per_added_sku": (
                    current["consumer_cost_jpy"]
                    - expanded["consumer_cost_jpy"]
                ),
                "globally_optimal_portfolios_nested": current_sizes.issubset(
                    expanded_sizes
                ),
            }
        )
    return pd.DataFrame(rows)
