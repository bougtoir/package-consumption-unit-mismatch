from __future__ import annotations

import math
from copy import deepcopy

import pandas as pd

from pcum.model import (
    _advance_lots,
    _consume_fifo,
    _simulate_one,
    apply_regime,
    evaluate_portfolios,
    lattice_diagnostics,
    manufacturing_safety_margin,
    simulate_package,
    sku_inclusion_thresholds,
    terminal_residual_distribution,
    zero_discard_balance_holds,
)


def test_lattice_diagnostics_identifies_exact_compatibility() -> None:
    exact = lattice_diagnostics(2.1, [150, 300, 450])
    mismatch = lattice_diagnostics(2.0, [150, 300, 450])
    assert exact["lattice_compatible"]
    assert exact["package_mod_lattice_g"] == 0
    assert not mismatch["lattice_compatible"]
    assert mismatch["package_mod_lattice_g"] == 50


def minimal_config() -> dict:
    return {
        "project": {
            "seed": 1,
            "horizon_years": 1,
            "burn_in_years": 0,
            "replications": 4,
            "days_per_year": 365.25,
        },
        "rice": {
            "value_jpy_per_kg": 850.0,
            "reference_package_kg": 2.0,
        },
        "costs": {
            "purchase_event_jpy": 120.0,
            "packaging_fixed_g": 8.0,
            "packaging_surface_g_per_kg_two_thirds": 9.0,
            "packaging_material_jpy_per_kg": 350.0,
            "storage_jpy_per_kg_day": 0.08,
            "freshness_jpy_per_kg_day": 0.60,
            "handling_jpy_per_purchase_kg_squared": 4.0,
            "adaptation_jpy_per_event": 10.0,
            "unmet_demand_jpy_per_kg": 1700.0,
            "size_discount_fraction_per_log_kg": 0.025,
            "spoilage_hazard_per_day_after_threshold": 0.003,
            "sku_complexity_jpy_per_household_year": 180.0,
        },
    }


def household() -> dict:
    return {
        "name": "test",
        "scenario_weight": 1.0,
        "annual_consumption_kg": 30.0,
        "usage_g": [150],
        "usage_probability": [1.0],
        "adaptation_probability": 0.0,
        "adaptation_min_ratio": 0.7,
        "freshness_threshold_days": 30.0,
        "handling_threshold_kg": 5.0,
    }


def test_terminal_residual_exact_multiple_is_zero() -> None:
    result = terminal_residual_distribution(2.1, [150], [1.0], 100, 1)
    assert result["mean_terminal_residual_g"] == 0.0
    assert result["zero_residual_probability"] == 1.0


def test_fresh_inventory_does_not_dilute_old_lot_freshness_exposure() -> None:
    lots = [
        {"quantity_g": 100.0, "purchase_day": 0.0},
        {"quantity_g": 200.0, "purchase_day": 60.0},
    ]
    consumed, age_mass, excess_age_mass = _consume_fifo(
        lots,
        amount_g=300.0,
        day=60.0,
        freshness_threshold_days=30.0,
    )
    assert consumed == 300.0
    assert age_mass == 6000.0
    assert excess_age_mass == 3000.0


def test_storage_exposure_integrates_spoilage_decay() -> None:
    lots = [
        {
            "quantity_g": 1000.0,
            "purchase_day": 0.0,
            "last_check_day": 0.0,
        }
    ]
    discarded_g, storage_g_days = _advance_lots(
        lots,
        day=40.0,
        threshold_days=30.0,
        hazard=0.1,
    )
    decay_loss = 1000.0 * (1.0 - math.exp(-1.0))
    expected_storage = 1000.0 * 30.0 + decay_loss / 0.1
    assert math.isclose(discarded_g, decay_loss)
    assert math.isclose(storage_g_days, expected_storage)
    assert math.isclose(lots[0]["quantity_g"], 1000.0 - decay_loss)


def test_full_carry_no_spoilage_has_no_discard() -> None:
    config = minimal_config()
    scenario = apply_regime(
        config, {"name": "no_spoilage", "spoilage_hazard_multiplier": 0.0}
    )
    result = simulate_package(2.0, household(), scenario, seed=1)
    assert result["physical_discard_kg"] == 0.0
    assert result["openings"] == result["purchases"]
    assert result["generalized_cost_jpy_ci_low"] <= result["generalized_cost_jpy"]
    assert result["generalized_cost_jpy_ci_high"] >= result["generalized_cost_jpy"]


def test_package_mismatch_can_end_as_inventory_without_discard() -> None:
    assert zero_discard_balance_holds(
        initial_inventory_kg=0.0,
        purchased_kg=2.0,
        consumed_kg=1.95,
        ending_inventory_kg=0.05,
    )
    assert not zero_discard_balance_holds(
        initial_inventory_kg=0.0,
        purchased_kg=2.0,
        consumed_kg=1.95,
        ending_inventory_kg=0.0,
    )
    assert not zero_discard_balance_holds(
        initial_inventory_kg=0.0,
        purchased_kg=1_000_000_000.0,
        consumed_kg=0.0,
        ending_inventory_kg=999_999_999.0,
    )


class BeyondHorizonRng:
    def gamma(self, shape: float, scale: float) -> float:
        return 10_000.0


def test_event_beyond_horizon_does_not_create_terminal_purchase() -> None:
    scenario = apply_regime(minimal_config(), {"name": "baseline"})
    result = _simulate_one(2.0, household(), scenario, BeyondHorizonRng())
    assert result["purchases"] == 0.0
    assert result["consumed_kg"] == 0.0
    assert result["demanded_kg"] == 0.0


def test_adaptation_carries_unmet_demand_forward() -> None:
    scenario = apply_regime(
        minimal_config(),
        {
            "name": "perfect_adaptation",
            "adaptation_probability": 1.0,
            "adaptation_min_ratio": 0.0,
        },
    )
    result = simulate_package(2.0, household(), scenario, seed=1)
    supplied = result["consumed_kg"] + result["unmet_demand_kg"]
    required = result["demanded_kg"] + result["opening_demand_backlog_kg"]
    assert abs(supplied - required) < 1e-9
    assert result["service_level_fraction"] > 0.99


def test_manufacturing_variance_increases_safety_margin() -> None:
    low = manufacturing_safety_margin(2000, 2, 0.001)
    high = manufacturing_safety_margin(2000, 10, 0.001)
    assert high["safety_margin_g"] > low["safety_margin_g"]
    assert high["expected_giveaway_fraction"] > low["expected_giveaway_fraction"]


def test_portfolio_complexity_can_reverse_variety_benefit() -> None:
    rows = []
    for household_name, weight, costs in [
        ("a", 0.5, {1.0: 100.0, 2.0: 200.0}),
        ("b", 0.5, {1.0: 200.0, 2.0: 100.0}),
    ]:
        for package_kg, cost in costs.items():
            rows.append(
                {
                    "household": household_name,
                    "package_kg": package_kg,
                    "generalized_cost_jpy": cost,
                    "physical_discard_kg": 0.0,
                    "packaging_mass_kg": 1.0,
                }
            )
    frame = pd.DataFrame(rows)
    no_charge = evaluate_portfolios(
        frame, [1.0, 2.0], {"a": 0.5, "b": 0.5}, complexity_cost=0
    )
    high_charge = evaluate_portfolios(
        deepcopy(frame), [1.0, 2.0], {"a": 0.5, "b": 0.5}, complexity_cost=100
    )
    assert no_charge.iloc[0]["sku_count"] == 1
    assert no_charge[no_charge["sku_count"] == 2].iloc[0]["system_cost_jpy"] == 100.0
    assert high_charge[high_charge["sku_count"] == 2].iloc[0]["system_cost_jpy"] == 200.0


def test_sku_break_even_thresholds_match_global_enumeration() -> None:
    rows = []
    costs_by_household = {
        "a": {1.0: 100.0, 2.0: 200.0, 3.0: 200.0},
        "b": {1.0: 200.0, 2.0: 100.0, 3.0: 200.0},
        "c": {1.0: 200.0, 2.0: 200.0, 3.0: 100.0},
    }
    for household_name, costs in costs_by_household.items():
        for package_kg, cost in costs.items():
            rows.append(
                {
                    "household": household_name,
                    "package_kg": package_kg,
                    "generalized_cost_jpy": cost,
                    "physical_discard_kg": 0.0,
                    "packaging_mass_kg": 1.0,
                }
            )
    frame = pd.DataFrame(rows)
    weights = {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}
    thresholds = sku_inclusion_thresholds(
        frame,
        [1.0, 2.0, 3.0],
        weights,
    )
    assert math.isclose(
        thresholds.iloc[0]["break_even_complexity_jpy_per_added_sku"],
        100.0 / 3.0,
    )
    assert math.isclose(
        thresholds.iloc[1]["break_even_complexity_jpy_per_added_sku"],
        100.0 / 3.0,
    )
    below = evaluate_portfolios(
        frame,
        [1.0, 2.0, 3.0],
        weights,
        complexity_cost=30.0,
    )
    above = evaluate_portfolios(
        frame,
        [1.0, 2.0, 3.0],
        weights,
        complexity_cost=40.0,
    )
    assert below.loc[below["system_cost_jpy"].idxmin(), "sku_count"] == 3
    assert above.loc[above["system_cost_jpy"].idxmin(), "sku_count"] == 1
