from pathlib import Path

import pandas as pd
import pytest

from pcum.distribution import is_public_distribution


def write_provenance(root: Path) -> None:
    provenance = root / "provenance"
    provenance.mkdir()
    pd.DataFrame(
        [
            {"source_id": "public", "local_path": "data/raw/public.json"},
            {"source_id": "restricted_a", "local_path": "data/raw/a.html"},
            {"source_id": "restricted_b", "local_path": "data/raw/b.html"},
        ]
    ).to_csv(provenance / "acquisition_ledger.csv", index=False)
    pd.DataFrame(
        [
            {
                "source_id": "public",
                "public_archive_status": "redistributable_metadata",
            },
            {
                "source_id": "restricted_a",
                "public_archive_status": "private_research_only",
            },
            {
                "source_id": "restricted_b",
                "public_archive_status": "exclude_unless_permission_verified",
            },
        ]
    ).to_csv(provenance / "redistribution_policy.csv", index=False)


def test_distribution_mode_detects_complete_and_public_source_sets(
    tmp_path: Path,
) -> None:
    write_provenance(tmp_path)
    assert is_public_distribution(tmp_path)

    raw = tmp_path / "data/raw"
    raw.mkdir(parents=True)
    (raw / "a.html").write_text("a")
    (raw / "b.html").write_text("b")
    assert not is_public_distribution(tmp_path)


def test_distribution_mode_rejects_partial_restricted_source_set(
    tmp_path: Path,
) -> None:
    write_provenance(tmp_path)
    raw = tmp_path / "data/raw"
    raw.mkdir(parents=True)
    (raw / "a.html").write_text("a")

    with pytest.raises(ValueError, match="Restricted source snapshot set is incomplete"):
        is_public_distribution(tmp_path)
