"""PR-001 Motor claims frequency — reference Python translation of pr001_claims_freq.R (generic LegacyModel contract).

Poisson GLM, log link, offset log(exposure); veh_body, veh_age, agecat, area, gender categorical with the
alphabetically first level as reference (R factor()). score = expected claims per unit exposure.
FINDING reproduced, not fixed: gender is a rating factor.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

FACTORS = ["veh_body", "veh_age", "agecat", "area", "gender"]


def _lvl(s: pd.Series) -> pd.Series:
    return s.map(lambda v: str(int(v)) if isinstance(v, (float, np.floating)) and float(v).is_integer() else str(v))


class LegacyModel:
    def _design(self, d: pd.DataFrame) -> pd.DataFrame:
        X = pd.DataFrame(index=d.index)
        for f in FACTORS:
            v = _lvl(d[f])
            for lv in self.levels[f][1:]:
                X[f"{f}{lv}"] = (v == lv).astype(float)
        return sm.add_constant(X, has_constant="add")

    def fit(self, frame: pd.DataFrame, train_rows=None) -> "LegacyModel":
        d = frame if train_rows is None else frame[frame[".row"].isin(train_rows)]
        d = d[d["exposure"] > 0]
        self.levels = {f: sorted(_lvl(d[f]).unique()) for f in FACTORS}
        X = self._design(d)
        res = sm.GLM(d["numclaims"].to_numpy(float), X, family=sm.families.Poisson(),
                     offset=np.log(d["exposure"].to_numpy(float))).fit(tol=1e-12, maxiter=100)
        self.params = pd.Series(np.asarray(res.params), index=X.columns)
        return self

    @property
    def coef(self) -> pd.Series:
        return self.params.rename(index={"const": "(Intercept)"})

    def score(self, frame: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({"score": np.exp(self._design(frame).to_numpy() @ self.params.to_numpy())}, index=frame.index)
