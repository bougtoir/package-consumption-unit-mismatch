from __future__ import annotations

import pandas as pd

from analysis.build_tables import weighted_replication_standard_errors


def test_weighted_standard_error_preserves_replication_covariance() -> None:
    frame = pd.DataFrame(
        [
            {
                "package_kg": 1.0,
                "replication": replication,
                "scenario_weight": 0.5,
                "generalized_cost_jpy": value,
            }
            for replication, value in [(0, 0.0), (1, 2.0)]
            for _household in ["a", "b"]
        ]
    )
    standard_errors = weighted_replication_standard_errors(
        frame,
        "generalized_cost_jpy",
    )
    assert standard_errors.loc[1.0] == 1.0
