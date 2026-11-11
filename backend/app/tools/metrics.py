"""Deterministic model-performance metrics. Pure functions: arrays in, numbers out."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, roc_curve


def _clean(y, p):
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    m = ~(np.isnan(y) | np.isnan(p))
    return y[m], p[m]


def auc(y, p) -> float:
    """Area under the ROC curve (probability a random bad outranks a random good)."""
    y, p = _clean(y, p)
    return float(roc_auc_score(y, p))


def gini(y, p) -> float:
    """Gini coefficient = 2 * AUC - 1."""
    return 2.0 * auc(y, p) - 1.0


def ks(y, p) -> float:
    """Kolmogorov-Smirnov: max distance between bad and good cumulative score distributions."""
    y, p = _clean(y, p)
    fpr, tpr, _ = roc_curve(y, p)
    return float(np.max(tpr - fpr))


def brier(y, p) -> float:
    """Mean squared error between predicted PD and outcome."""
    y, p = _clean(y, p)
    return float(np.mean((p - y) ** 2))


def calibration_ratio(y, p) -> float:
    """Mean predicted PD divided by observed default rate (1.0 = perfectly calibrated in aggregate)."""
    y, p = _clean(y, p)
    return float(np.mean(p) / max(np.mean(y), 1e-9))


def calibration_deciles(y, p, n: int = 10) -> pd.DataFrame:
    y, p = _clean(y, p)
    df = pd.DataFrame({"y": y, "p": p})
    df["decile"] = pd.qcut(df["p"].rank(method="first"), n, labels=False) + 1
    g = df.groupby("decile").agg(predicted=("p", "mean"), observed=("y", "mean"), n=("y", "size")).reset_index()
    return g


def max_decile_calibration_gap(y, p, n: int = 10) -> float:
    """Largest absolute gap between mean predicted and observed default rate across score deciles."""
    g = calibration_deciles(y, p, n)
    return float((g["predicted"] - g["observed"]).abs().max())


def approval_rate(p, cutoff: float) -> float:
    p = np.asarray(p, dtype=float)
    p = p[~np.isnan(p)]
    return float(np.mean(p <= cutoff))


def bad_rate(y) -> float:
    y = np.asarray(y, dtype=float)
    return float(np.nanmean(y))


def psi(expected, actual, bins: int = 10) -> float:
    """Population Stability Index of `actual` vs `expected` on expected-quantile bins."""
    e = np.asarray(expected, dtype=float)
    a = np.asarray(actual, dtype=float)
    e, a = e[~np.isnan(e)], a[~np.isnan(a)]
    edges = np.unique(np.quantile(e, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:  # near-constant (e.g. WoE with few levels): fall back to value buckets
        return psi_categorical(e, a)
    edges[0], edges[-1] = -np.inf, np.inf
    ep = np.histogram(e, edges)[0] / len(e)
    ap = np.histogram(a, edges)[0] / len(a)
    return _psi_from_props(ep, ap)


def psi_categorical(expected, actual) -> float:
    """PSI over discrete values (categorical features / WoE buckets), +0.5 count smoothing per category
    so rare categories missing from a small sample do not dominate."""
    e = pd.Series(np.asarray(expected)).astype(str).value_counts()
    a = pd.Series(np.asarray(actual)).astype(str).value_counts()
    keys = sorted(set(e.index) | set(a.index))
    ec = np.array([e.get(k, 0.0) for k in keys]) + 0.5
    ac = np.array([a.get(k, 0.0) for k in keys]) + 0.5
    return _psi_from_props(ec / ec.sum(), ac / ac.sum())


def _psi_from_props(ep, ap) -> float:
    ep = np.clip(ep, 1e-4, None)
    ap = np.clip(ap, 1e-4, None)
    return float(np.sum((ap - ep) * np.log(ap / ep)))


def roc_points(y, p, n: int = 40) -> list[dict]:
    y, p = _clean(y, p)
    fpr, tpr, _ = roc_curve(y, p)
    idx = np.unique(np.linspace(0, len(fpr) - 1, min(n, len(fpr))).astype(int))
    return [{"fpr": round(float(fpr[i]), 4), "tpr": round(float(tpr[i]), 4)} for i in idx]
