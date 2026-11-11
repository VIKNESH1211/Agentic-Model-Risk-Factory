"""CR-003 Credit limit strategy — Python redevelopment of cr003_limits.R.

limit = min(round(income x multiplier(PD band), -2), 15000); declined applicants get 0.
PD bands use R cut() semantics: right-closed intervals (0,0.05], (0.05,0.10], ... (0.35,1].
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BREAKS = [0, 0.05, 0.10, 0.20, 0.35, 1]
BANDS = ["A", "B", "C", "D", "E"]
MULT = {"A": 0.30, "B": 0.25, "C": 0.15, "D": 0.08, "E": 0.0}
CAP = 15_000


class CR003LimitStrategy:
    def band(self, pd_: pd.Series) -> pd.Series:
        return pd.cut(pd_, BREAKS, labels=BANDS, right=True).astype(object)

    def score(self, apps: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
        d = apps.merge(scores, on="id").sort_values("id").reset_index(drop=True)  # R merge() sorts by key
        b = self.band(d["pd"])
        raw = d["income"].to_numpy(float) * b.map(MULT).astype(float).to_numpy()
        limit = np.minimum(np.round(raw, -2), CAP)
        limit = np.where(d["decision"].to_numpy() == "DECLINE", 0.0, limit)
        return pd.DataFrame({"id": d["id"], "pd": d["pd"], "band": b, "score": limit})
