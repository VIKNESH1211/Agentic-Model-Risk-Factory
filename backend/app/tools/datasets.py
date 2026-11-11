"""Dataset preparation. German credit has no dates, so the out-of-time split is SIMULATED."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.config import settings

RAW = settings.data_dir / "raw" / "germancredit.csv"
PREPARED = settings.data_dir / "synthetic" / "cr001_prepared.csv"
SPLIT_SEED = 7


def prepared() -> pd.DataFrame:
    if PREPARED.exists():
        return pd.read_csv(PREPARED)
    d = pd.read_csv(RAW)
    d.insert(0, "id", [f"GC{i:04d}" for i in range(1, len(d) + 1)])
    rng = np.random.default_rng(SPLIT_SEED)
    u = rng.random(len(d))
    d["split"] = np.where(u < 0.6, "train", np.where(u < 0.8, "test", "oot"))  # oot = simulated
    d["sex"] = np.where(d["personal.status.and.sex"].str.startswith("female"), "F", "M")
    d["age_band"] = np.where(d["age.in.years"] < 25, "under25", "25plus")
    PREPARED.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(PREPARED, index=False)
    return d


RAW_FEATURES = ["status.of.existing.checking.account", "duration.in.month", "credit.history", "purpose",
                "credit.amount", "savings.account.and.bonds", "present.employment.since",
                "installment.rate.in.percentage.of.disposable.income"]
