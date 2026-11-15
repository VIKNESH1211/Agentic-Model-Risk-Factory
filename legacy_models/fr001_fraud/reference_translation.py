"""FR-001 Card fraud detector — reference Python translation of fr001_fraud.R (generic LegacyModel contract).

Logistic GLM on V1, V3, V4, V10, V12, V14, V17 and log1p(Amount), fitted on the rows R's sample() chose
(train_rows, exported by the platform because R's RNG cannot be reproduced). score = fraud probability;
the alert decision (p > 0.5, untuned for a <1% base rate) is applied by the platform from the spec.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

FEATURES = ["V1", "V3", "V4", "V10", "V12", "V14", "V17", "logamt"]


class LegacyModel:
    def _X(self, d: pd.DataFrame) -> pd.DataFrame:
        X = d[[f for f in FEATURES if f != "logamt"]].astype(float).copy()
        X["logamt"] = np.log1p(d["Amount"].astype(float))
        return sm.add_constant(X[FEATURES], has_constant="add")

    def fit(self, frame: pd.DataFrame, train_rows=None) -> "LegacyModel":
        d = frame if train_rows is None else frame[frame[".row"].isin(train_rows)]
        X = self._X(d)
        res = sm.GLM(d["Class"].to_numpy(float), X, family=sm.families.Binomial()).fit(tol=1e-12, maxiter=100)
        self.params = pd.Series(np.asarray(res.params), index=X.columns)
        return self

    @property
    def coef(self) -> pd.Series:
        return self.params.rename(index={"const": "(Intercept)"})

    def score(self, frame: pd.DataFrame) -> pd.DataFrame:
        p = 1 / (1 + np.exp(-(self._X(frame).to_numpy() @ self.params.to_numpy())))
        return pd.DataFrame({"score": p}, index=frame.index)
