"""PR-001 Motor claims frequency — Python redevelopment of pr001_claims_freq.R.

Poisson GLM, log link, offset log(exposure); rating factors veh_body, veh_age, agecat, area, gender
(all treated as categorical, first level alphabetical as R's factor() does).
QUIRK/FINDING: 'gender' is a rating factor (prohibited for UK/EU insurance pricing since 2012).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

FACTORS = ["veh_body", "veh_age", "agecat", "area", "gender"]


class PR001FrequencyGLM:
    def __init__(self):
        self.levels: dict[str, list[str]] = {}
        self.params: pd.Series | None = None

    def _design(self, d: pd.DataFrame) -> pd.DataFrame:
        X = pd.DataFrame(index=d.index)
        for f in FACTORS:
            v = d[f].astype(str)
            for lv in self.levels[f][1:]:  # treatment coding, first level = reference
                X[f"{f}{lv}"] = (v == lv).astype(float)
        return sm.add_constant(X, has_constant="add")

    def fit(self, d: pd.DataFrame) -> "PR001FrequencyGLM":
        d = d[d["exposure"] > 0]
        self.levels = {f: sorted(d[f].astype(str).unique()) for f in FACTORS}
        X = self._design(d)
        res = sm.GLM(d["numclaims"].to_numpy(float), X, family=sm.families.Poisson(),
                     offset=np.log(d["exposure"].to_numpy(float))).fit(tol=1e-12, maxiter=100)
        self.params = pd.Series(res.params, index=X.columns)
        return self

    @property
    def coef(self) -> pd.Series:
        c = self.params.copy()
        c.index = ["(Intercept)" if i == "const" else i for i in c.index]
        return c

    def predict_frequency(self, d: pd.DataFrame) -> np.ndarray:
        """Expected claims per unit exposure (= exp(linear predictor), the offset removed)."""
        return np.exp(self._design(d).to_numpy() @ self.params.to_numpy())

    def score(self, d: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({"id": d["id"].to_numpy(), "score": self.predict_frequency(d)})
