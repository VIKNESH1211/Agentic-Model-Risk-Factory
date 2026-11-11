"""Fairness metrics and proxy detection (deterministic)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_predict
from sklearn.metrics import roc_auc_score


def _rates(decision_approve: np.ndarray, group: np.ndarray):
    out = {}
    for g in pd.unique(group):
        m = group == g
        out[g] = float(np.mean(decision_approve[m])) if m.any() else np.nan
    return out


def demographic_parity_diff(approve, group) -> float:
    """Largest gap in approval rate between groups."""
    r = _rates(np.asarray(approve, float), np.asarray(group))
    v = [x for x in r.values() if not np.isnan(x)]
    return float(max(v) - min(v))


def disparate_impact_ratio(approve, group) -> float:
    """Lowest group approval rate divided by highest (four-fifths rule flags < 0.8)."""
    r = _rates(np.asarray(approve, float), np.asarray(group))
    v = [x for x in r.values() if not np.isnan(x)]
    return float(min(v) / max(max(v), 1e-9))


def equal_opportunity_diff(approve, y, group) -> float:
    """Largest gap in approval rate among applicants who did NOT default (true goods)."""
    approve, y, group = np.asarray(approve, float), np.asarray(y, float), np.asarray(group)
    m = y == 0
    r = _rates(approve[m], group[m])
    v = [x for x in r.values() if not np.isnan(x)]
    return float(max(v) - min(v))


def proxy_auc(X: pd.DataFrame, protected: np.ndarray, seed: int = 0) -> float:
    """How well model features predict the protected attribute (5-fold CV AUC). ~0.5 = no proxy."""
    Xn = pd.get_dummies(X, drop_first=True).astype(float).fillna(0.0)
    yb = np.asarray(protected).astype(int)
    if len(np.unique(yb)) < 2:
        return 0.5
    clf = LogisticRegression(max_iter=2000)
    p = cross_val_predict(clf, Xn, yb, cv=5, method="predict_proba")[:, 1]
    return float(roc_auc_score(yb, p))


def max_feature_corr(X: pd.DataFrame, target: np.ndarray) -> tuple[str, float]:
    """Feature with the highest absolute Spearman correlation to `target`."""
    t = pd.Series(np.asarray(target, float))
    best, val = "", 0.0
    for c in X.columns:
        s = pd.to_numeric(X[c], errors="coerce")
        if s.notna().sum() < 10 or s.nunique() < 2:
            continue
        r = abs(s.reset_index(drop=True).corr(t, method="spearman"))
        if r > val:
            best, val = c, float(r)
    return best, val
