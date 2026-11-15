"""CR-001 Retail PD Scorecard — reference Python translation of cr001_scorecard.R (generic LegacyModel contract).

Uploaded WITH the model as a known-good fallback; the platform uses it only if the agent's own translation fails
parity, and it must pass the same parity check. Quirks reproduced on purpose:
  QUIRK-1 missing credit amount → 0 before binning · QUIRK-2 unseen category → NA WoE → NA PD
  QUIRK-3 decision cut-off 0.35 although the comment cites policy CP-07 = 0.25
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

CUTOFF = 0.35
VARS = ["checking", "duration", "history", "purpose", "amount", "savings", "employment", "instalment"]


def _chr(s: pd.Series) -> pd.Series:  # R as.character(): 2.0 → "2", NA stays NA
    def conv(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return np.nan
        if isinstance(v, (float, np.floating)) and float(v).is_integer():
            return str(int(v))
        return str(v)
    return s.map(conv).astype(object)


def _cut(x, breaks, labels):
    out = pd.cut(pd.to_numeric(x, errors="coerce"), bins=breaks, right=False, labels=labels)
    return out.astype(object).where(out.notna(), np.nan)


def make_bins(d: pd.DataFrame) -> pd.DataFrame:
    amount = pd.to_numeric(d["credit.amount"], errors="coerce").fillna(0)  # QUIRK-1
    return pd.DataFrame({
        "checking": _chr(d["status.of.existing.checking.account"]),
        "duration": _cut(d["duration.in.month"], [-np.inf, 12, 24, 36, np.inf], ["lt12", "12-24", "24-36", "36+"]),
        "history": _chr(d["credit.history"]), "purpose": _chr(d["purpose"]),
        "amount": _cut(amount, [-np.inf, 1400, 4000, 8000, np.inf], ["lt1400", "1400-4000", "4000-8000", "8000+"]),
        "savings": _chr(d["savings.account.and.bonds"]), "employment": _chr(d["present.employment.since"]),
        "instalment": _chr(d["installment.rate.in.percentage.of.disposable.income"]),
    }, index=d.index)


class LegacyModel:
    def fit(self, frame: pd.DataFrame, train_rows=None) -> "LegacyModel":
        d = frame if train_rows is None else frame[frame[".row"].isin(train_rows)]
        y = (d["creditability"].astype(str) == "bad").astype(float).to_numpy()
        b = make_bins(d)
        G, B = float((y == 0).sum()), float((y == 1).sum())
        self.woe = {}
        for v in VARS:
            mp = {}
            for lv in sorted(b[v].dropna().unique()):
                m = (b[v] == lv).to_numpy()
                ng, nb = float(((y == 0) & m).sum()), float(((y == 1) & m).sum())
                mp[lv] = float(np.log(((nb + 0.5) / B) / ((ng + 0.5) / G)))
            self.woe[v] = mp
        X = sm.add_constant(self._woe(d), has_constant="add")
        res = sm.GLM(y, X, family=sm.families.Binomial()).fit(tol=1e-12, maxiter=100)
        self.params = pd.Series(np.asarray(res.params), index=X.columns)
        return self

    def _woe(self, d: pd.DataFrame) -> pd.DataFrame:
        b = make_bins(d)
        return pd.DataFrame({f"woe_{v}": b[v].map(lambda k, mp=self.woe[v]: mp.get(k, np.nan) if isinstance(k, str) else np.nan)
                            .astype(float) for v in VARS}, index=d.index)  # QUIRK-2

    @property
    def coef(self) -> pd.Series:
        return self.params.rename(index={"const": "(Intercept)"})

    def score(self, frame: pd.DataFrame) -> pd.DataFrame:
        X = self._woe(frame)
        p = 1 / (1 + np.exp(-(self.params["const"] + X.to_numpy() @ self.params[X.columns].to_numpy())))
        dec = np.where(np.isnan(p), None, np.where(p > CUTOFF, "DECLINE", "APPROVE"))  # QUIRK-3
        return pd.DataFrame({"score": p, "decision": dec}, index=frame.index)
