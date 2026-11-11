"""CR-001 Retail PD Scorecard — Python redevelopment of legacy cr001_scorecard.R (v2.3).

Faithful translation: reproduces the legacy behaviour exactly, including known quirks,
so parity can be proven first. Quirks are flagged (QUIRK) and raised as findings rather
than silently "fixed".
  QUIRK-1  missing credit amount is set to 0 before binning (legacy line: x[is.na(x)] <- 0)
  QUIRK-2  a category not seen in training gets WoE = NA, so PD and decision are NA
  QUIRK-3  decision cutoff is 0.35 although the code comment cites policy CP-07 = 0.25
GLM: statsmodels Binomial GLM (no regularisation) to match R glm() IRLS.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

CUTOFF = 0.35  # QUIRK-3
VARS = ["checking", "duration", "history", "purpose", "amount", "savings", "employment", "instalment"]


def _r_as_character(s: pd.Series) -> pd.Series:
    """Mimic R as.character(): integers print without '.0'; NA stays NA."""
    def conv(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return np.nan
        if isinstance(v, (float, np.floating)) and float(v).is_integer():
            return str(int(v))
        return str(v)
    return s.map(conv).astype(object)


def _cut(x: pd.Series, breaks, labels) -> pd.Series:
    out = pd.cut(pd.to_numeric(x, errors="coerce"), bins=breaks, right=False, labels=labels)
    return out.astype(object).where(out.notna(), np.nan)


def bin_duration(x: pd.Series) -> pd.Series:
    return _cut(x, [-np.inf, 12, 24, 36, np.inf], ["lt12", "12-24", "24-36", "36+"])


def bin_amount(x: pd.Series) -> pd.Series:
    x = pd.to_numeric(x, errors="coerce").fillna(0)  # QUIRK-1
    return _cut(x, [-np.inf, 1400, 4000, 8000, np.inf], ["lt1400", "1400-4000", "4000-8000", "8000+"])


def make_bins(d: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "checking": _r_as_character(d["status.of.existing.checking.account"]),
        "duration": bin_duration(d["duration.in.month"]),
        "history": _r_as_character(d["credit.history"]),
        "purpose": _r_as_character(d["purpose"]),
        "amount": bin_amount(d["credit.amount"]),
        "savings": _r_as_character(d["savings.account.and.bonds"]),
        "employment": _r_as_character(d["present.employment.since"]),
        "instalment": _r_as_character(d["installment.rate.in.percentage.of.disposable.income"]),
    }, index=d.index)


class CR001Scorecard:
    vars = VARS

    def __init__(self, cutoff: float = CUTOFF):
        self.cutoff = cutoff
        self.woe_tabs: dict[str, pd.DataFrame] = {}
        self.result = None

    # ------------------------------------------------------------ fit
    def fit(self, d: pd.DataFrame) -> "CR001Scorecard":
        y = (d["creditability"] == "bad").astype(float).values
        b = self.make_bins(d)
        G, B = float((y == 0).sum()), float((y == 1).sum())
        for v in self.vars:
            rows = []
            for lv in sorted(b[v].dropna().unique()):
                m = (b[v] == lv).values
                ng, nb = float(((y == 0) & m).sum()), float(((y == 1) & m).sum())
                rows.append({"var": v, "bin": lv, "n_good": ng, "n_bad": nb,
                             "woe": float(np.log(((nb + 0.5) / B) / ((ng + 0.5) / G)))})
            self.woe_tabs[v] = pd.DataFrame(rows)
        X = self.woe_features(d)
        Xc = sm.add_constant(X, has_constant="add")
        self.result = sm.GLM(y, Xc, family=sm.families.Binomial()).fit(tol=1e-12, maxiter=100)
        self.params = pd.Series(self.result.params, index=Xc.columns).copy()
        return self

    def woe_features(self, d: pd.DataFrame) -> pd.DataFrame:
        b = self.make_bins(d)
        out = {}
        for v in self.vars:
            mp = dict(zip(self.woe_tabs[v]["bin"], self.woe_tabs[v]["woe"]))
            out[f"woe_{v}"] = b[v].map(lambda k: mp.get(k, np.nan) if isinstance(k, str) else np.nan).astype(float)  # QUIRK-2
        return pd.DataFrame(out, index=d.index)

    def make_bins(self, d: pd.DataFrame) -> pd.DataFrame:
        return make_bins(d)

    # ------------------------------------------------------------ predict
    @property
    def coef(self) -> pd.Series:
        c = self.params.copy()
        c.index = ["(Intercept)" if i == "const" else i for i in c.index]
        return c

    def predict_pd(self, d: pd.DataFrame) -> np.ndarray:
        X = self.woe_features(d)
        c = self.params
        eta = c["const"] + X.values @ c[X.columns].values
        return 1.0 / (1.0 + np.exp(-eta))

    def score(self, d: pd.DataFrame) -> pd.DataFrame:
        p = self.predict_pd(d)
        with np.errstate(divide="ignore", invalid="ignore"):
            points = np.round(600 + (50 / np.log(2)) * np.log((1 - p) / p))
        decision = np.where(np.isnan(p), None, np.where(p > self.cutoff, "DECLINE", "APPROVE"))
        return pd.DataFrame({"id": d["id"].values, "pd": p, "points": points, "decision": decision})

    def woe_table(self) -> pd.DataFrame:
        return pd.concat(self.woe_tabs.values(), ignore_index=True)
