"""Differential fuzzing: edge-case rows generated once, scored in batch by both models."""
from __future__ import annotations

import numpy as np
import pandas as pd

NUMERIC_EDGES = {
    "duration.in.month": [0, 1, 11, 11.999, 12, 12.001, 23.999, 24, 35.999, 36, 72, 120, 1000, -5],
    "credit.amount": [0, 1, 1399, 1399.999, 1400, 1400.001, 3999.999, 4000, 7999.999, 8000, 20000, 1e7, -100],
    "installment.rate.in.percentage.of.disposable.income": [1, 2, 3, 4, 5, 0],
}
CATEGORICAL = ["status.of.existing.checking.account", "credit.history", "purpose",
               "savings.account.and.bonds", "present.employment.since"]
UNSEEN = "__unseen_category__"


def generate(base: pd.DataFrame, n: int = 5000, seed: int = 20261109) -> pd.DataFrame:
    """Mix of: edge values, nulls, unseen categories, and random recombinations of real rows."""
    rng = np.random.default_rng(seed)
    rows = base.sample(n, replace=True, random_state=seed).reset_index(drop=True).copy()
    rows = rows.astype({c: float for c in NUMERIC_EDGES}).astype({c: object for c in CATEGORICAL})
    kinds = rng.choice(["edge_numeric", "null", "unseen_category", "recombine", "extreme_combo"], size=n,
                       p=[0.35, 0.15, 0.1, 0.3, 0.1])
    num_cols = list(NUMERIC_EDGES)
    for i, k in enumerate(kinds):
        if k == "edge_numeric":
            c = num_cols[rng.integers(len(num_cols))]
            rows.at[i, c] = NUMERIC_EDGES[c][rng.integers(len(NUMERIC_EDGES[c]))]
        elif k == "null":
            c = (num_cols + CATEGORICAL)[rng.integers(len(num_cols) + len(CATEGORICAL))]
            rows.at[i, c] = np.nan
        elif k == "unseen_category":
            c = CATEGORICAL[rng.integers(len(CATEGORICAL))]
            rows.at[i, c] = UNSEEN
        elif k == "recombine":
            for c in num_cols + CATEGORICAL:
                rows.at[i, c] = base[c].iloc[rng.integers(len(base))]
        else:
            for c in num_cols:
                rows.at[i, c] = NUMERIC_EDGES[c][rng.integers(len(NUMERIC_EDGES[c]))]
    rows["fuzz_kind"] = kinds
    rows["id"] = [f"FZ{i:05d}" for i in range(n)]
    return rows


def compare(legacy: pd.DataFrame, py: pd.DataFrame, fuzz: pd.DataFrame, tol: float = 1e-6) -> pd.DataFrame:
    d = fuzz[["id", "fuzz_kind"]].merge(legacy.rename(columns={"pd": "legacy_pd", "points": "legacy_points",
                                                                 "decision": "legacy_decision"}), on="id")
    d = d.merge(py.rename(columns={"pd": "py_pd", "points": "py_points", "decision": "py_decision"}), on="id")
    lna, pna = d["legacy_pd"].isna(), d["py_pd"].isna()
    diff = (d["legacy_pd"] - d["py_pd"]).abs()
    cause = np.where(lna ^ pna, "NA handling",
             np.where(~lna & ~pna & (diff > tol), "optimiser / numeric",
             np.where(~lna & ~pna & (d["legacy_points"] != d["py_points"]), "rounding",
             np.where(~lna & ~pna & (d["legacy_decision"] != d["py_decision"]), "tie-break at cutoff", ""))))
    d["abs_diff"] = diff
    d["diverged"] = cause != ""
    d["cause"] = cause
    d["legacy_na"] = lna
    d["legacy_na_decision"] = d["legacy_decision"].isna()
    return d
