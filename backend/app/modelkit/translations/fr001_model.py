"""FR-001 Card fraud detector — Python redevelopment of fr001_fraud.R.

Logistic GLM on V1, V3, V4, V10, V12, V14, V17 and log1p(Amount); alert when p > 0.5.
R's sample() split cannot be reproduced in Python, so fit() takes the training rows exported from R.
FINDING: the 0.5 threshold is untuned for a <1% base rate.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

FEATURES = ["V1", "V3", "V4", "V10", "V12", "V14", "V17", "logamt"]
THRESHOLD = 0.5


class FR001FraudGLM:
    def _X(self, d: pd.DataFrame) -> pd.DataFrame:
        X = d[[f for f in FEATURES if f != "logamt"]].astype(float).copy()
        X["logamt"] = np.log1p(d["Amount"].astype(float))
        return sm.add_constant(X[FEATURES], has_constant="add")

    def fit(self, d: pd.DataFrame, train_rows: np.ndarray) -> "FR001FraudGLM":
        tr = d.iloc[np.asarray(train_rows) - 1]  # R rows are 1-based
        res = sm.GLM(tr["Class"].to_numpy(float), self._X(tr), family=sm.families.Binomial()).fit(tol=1e-12, maxiter=100)
        self.params = pd.Series(res.params, index=self._X(tr).columns)
        return self

    @property
    def coef(self) -> pd.Series:
        c = self.params.copy()
        c.index = ["(Intercept)" if i == "const" else i for i in c.index]
        return c

    def predict_proba(self, d: pd.DataFrame) -> np.ndarray:
        return 1 / (1 + np.exp(-(self._X(d).to_numpy() @ self.params.to_numpy())))

    def score(self, d: pd.DataFrame) -> pd.DataFrame:
        p = self.predict_proba(d)
        return pd.DataFrame({"id": d["id"].to_numpy(), "score": p, "decision": np.where(p > THRESHOLD, "ALERT", "PASS")})
