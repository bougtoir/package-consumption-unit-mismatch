from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]


def build_calibration() -> None:
    config = yaml.safe_load((ROOT / "config/default.yaml").read_text())
    rows = [
        {
            "parameter": "natural_quantum_g",
            "value": config["rice"]["natural_quantum_g"],
            "unit": "g uncooked rice",
            "source_type": "empirical anchor",
            "source_id": "maff_rice_go_mass",
            "interpretation": "Mass convention for one go; not a household-demand distribution",
        },
        {
            "parameter": "freshness_threshold_days",
            "value": 30,
            "unit": "days",
            "source_type": "scenario anchor",
            "source_id": "maff_rice_storage",
            "interpretation": "Quality guide after milling; not direct evidence of discard",
        },
        {
            "parameter": "national_annual_rice_supply_kg_per_person",
            "value": 53.4,
            "unit": "kg/person-year",
            "source_type": "empirical anchor",
            "source_id": "maff_rice_consumption_per_capita",
            "interpretation": "National supply-consumption anchor; not an event distribution",
        },
        {
            "parameter": "one_person_household_share",
            "value": 0.381,
            "unit": "fraction of private households",
            "source_type": "empirical anchor",
            "source_id": "statistics_japan_2025",
            "interpretation": "2020 census aggregate used only to structure scenario weights",
        },
    ]
    for parameter, value in config["costs"].items():
        rows.append(
            {
                "parameter": parameter,
                "value": value,
                "unit": "scenario-specific",
                "source_type": "transparent scenario assumption",
                "source_id": "none",
                "interpretation": "Not presented as observed empirical data",
            }
        )
    pd.DataFrame(rows).to_csv(ROOT / "data/processed/calibration.csv", index=False)


def build_cross_product_classification() -> None:
    rows = [
        {
            "product": "uncooked rice",
            "illustrative_hypothesis": "mismatch may create adaptation or aging costs",
            "natural_quantum": "approximately 150 g per go",
            "package_evidence": "2 kg, 5 kg, and 10 kg manufacturer lineup",
            "mechanism": "carry-over is easy; age and storage may create cost",
            "evidence_status": (
                "quantum and package examples verified; household behavior, discard, "
                "and package shares not estimated"
            ),
        },
        {
            "product": "dry pasta example",
            "illustrative_hypothesis": "stable carry-over may make mismatch low-cost",
            "natural_quantum": "serving quantum not empirically fixed here",
            "package_evidence": "300 g manufacturer page",
            "mechanism": "stable and divisible; residual normally carries over",
            "evidence_status": "single package verified; consumption quantum unverified",
        },
        {
            "product": "granulated sugar",
            "illustrative_hypothesis": "continuous use weakens the lattice mechanism",
            "natural_quantum": "continuous/divisible",
            "package_evidence": "not used as empirical calibration",
            "mechanism": "negative control for lattice mechanism",
            "evidence_status": "conceptual negative control",
        },
        {
            "product": "single-dose medicine",
            "illustrative_hypothesis": "count-based packaging may match prescribed use",
            "natural_quantum": "dose count",
            "package_evidence": "not used as empirical calibration",
            "mechanism": "count-based package can match prescribed course",
            "evidence_status": "conceptual comparator only",
        },
    ]
    pd.DataFrame(rows).to_csv(
        ROOT / "data/processed/cross_product_classification.csv", index=False
    )


def main() -> None:
    (ROOT / "data/processed").mkdir(parents=True, exist_ok=True)
    build_calibration()
    build_cross_product_classification()


if __name__ == "__main__":
    main()
