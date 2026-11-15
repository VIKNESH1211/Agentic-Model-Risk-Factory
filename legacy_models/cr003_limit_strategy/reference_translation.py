"""CR-003 Credit limit strategy — reference Python translation of cr003_limits.R (generic LegacyModel contract).

Rules, nothing is fitted: limit = min(round(income × multiplier(PD band), -2), 15000); 0 when CR-001 declined.
PD bands use R cut() semantics: right-closed (0,0.05], (0.05,0.10], (0.10,0.20], (0.20,0.35], (0.35,1].
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BREAKS = [0, 0.05, 0.10, 0.20, 0.35, 1]
MULT = {"A": 0.30, "B": 0.25, "C": 0.15, "D": 0.08, "E": 0.0}
CAP = 15_000


class LegacyModel:
    coef = None

    def fit(self, frame: pd.DataFrame, train_rows=None) -> "LegacyModel":
        return self

    def score(self, frame: pd.DataFrame) -> pd.DataFrame:
        band = pd.cut(pd.to_numeric(frame["pd"], errors="coerce"), BREAKS, labels=list(MULT), right=True).astype(object)
        raw = frame["income"].to_numpy(float) * band.map(MULT).astype(float).to_numpy()
        limit = np.minimum(np.round(raw, -2), CAP)
        limit = np.where(frame["decision"].astype(str).to_numpy() == "DECLINE", 0.0, limit)
        return pd.DataFrame({"score": limit}, index=frame.index)
