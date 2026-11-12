from pathlib import Path

import pandas as pd


def is_public_distribution(root: Path) -> bool:
    if (root / "PUBLIC_DISTRIBUTION.txt").exists():
        return True

    ledger = pd.read_csv(root / "provenance/acquisition_ledger.csv")
    policy = pd.read_csv(root / "provenance/redistribution_policy.csv")
    restricted_ids = set(
        policy.loc[
            policy["public_archive_status"] != "redistributable_metadata",
            "source_id",
        ]
    )
    paths = [
        root / local_path
        for local_path in ledger.loc[
            ledger["source_id"].isin(restricted_ids), "local_path"
        ]
    ]
    present = [path.exists() for path in paths]
    if all(present):
        return False
    if not any(present):
        return True
    missing = [
        str(path.relative_to(root))
        for path, exists in zip(paths, present)
        if not exists
    ]
    raise ValueError(f"Restricted source snapshot set is incomplete: {missing}")
