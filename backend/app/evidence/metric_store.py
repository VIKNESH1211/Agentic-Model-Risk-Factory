"""The metric store: the ONLY source of numbers in reports.

Every metric is produced from a *recipe* (function name + stored data artifact + arguments).
Because the recipe and the data artifact are stored, any number can be recomputed later
("Reproduce") and compared with the stored value.
"""
from __future__ import annotations

import hashlib
import inspect
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from sqlmodel import select

from app.core.config import settings
from app.core.db import session
from app.core.events import bus
from app.domain.tables import Metric
from app.evidence import ledger
from app.tools import fairness as F
from app.tools import metrics as M


# ---------------------------------------------------------------- data access
@lru_cache(maxsize=64)
def _load(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_csv(path)


def load_artifact(rel: str) -> pd.DataFrame:
    p = settings.var_dir / rel
    return _load(str(p), p.stat().st_mtime)


def file_sha256(rel_or_path: str | Path) -> str:
    p = Path(rel_or_path)
    if not p.is_absolute():
        p = settings.var_dir / p
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _split(df: pd.DataFrame, r: dict) -> pd.DataFrame:
    if r.get("split") and r["split"] != "all" and "split" in df.columns:
        df = df[df["split"].isin(r["split"].split("|"))]
    if r.get("slice"):
        col, val = r["slice"].split("=", 1)
        df = df[df[col].astype(str) == val]
    return df


# ---------------------------------------------------------------- recipes
def _perf(fn: Callable) -> Callable:
    def run(df, r):
        d = _split(df, r)
        return fn(d[r.get("target", "y")], d[r.get("score", "pd")])
    run.__wrapped_fn__ = fn
    return run


def _psi(df, r):
    base = df[df["split"] == r["base"]][r["col"]]
    comp = df[df["split"] == r["comp"]][r["col"]]
    if r.get("categorical"):
        return M.psi_categorical(base, comp)
    return M.psi(base, comp)
_psi.__wrapped_fn__ = M.psi


def _fair(kind):
    def run(df, r):
        d = _split(df, r)
        approve = d[r.get("approve", "approve")].astype(float).values
        g = d[r["group"]].astype(str).values
        if kind == "dp":
            return F.demographic_parity_diff(approve, g)
        if kind == "di":
            return F.disparate_impact_ratio(approve, g)
        return F.equal_opportunity_diff(approve, d[r.get("target", "y")].values, g)
    run.__wrapped_fn__ = {"dp": F.demographic_parity_diff, "di": F.disparate_impact_ratio,
                          "eo": F.equal_opportunity_diff}[kind]
    return run


def _proxy(df, r):
    d = _split(df, r)
    return F.proxy_auc(d[r["features"]], d[r["protected"]].values)
_proxy.__wrapped_fn__ = F.proxy_auc


def _max_abs_diff(df, r):
    a = df[r["a"]].astype(float)
    b = df[r["b"]].astype(float)
    m = a.notna() & b.notna()
    return float((a[m] - b[m]).abs().max()) if m.any() else 0.0


def _count_true(df, r):
    d = _split(df, r)
    return float(d[r["col"]].astype(bool).sum())


def _rate_true(df, r):
    d = _split(df, r)
    return float(d[r["col"]].astype(bool).mean())


def _nunique_where(df, r):
    return float(len(df))


def _approval(df, r):
    d = _split(df, r)
    return M.approval_rate(d[r.get("score", "pd")], r["cutoff"])
_approval.__wrapped_fn__ = M.approval_rate


def _bad_rate(df, r):
    return M.bad_rate(_split(df, r)[r.get("target", "y")])
_bad_rate.__wrapped_fn__ = M.bad_rate


def _gini_diff_ci(df, r):
    """Bootstrap percentile of Gini(challenger) - Gini(champion), fixed seed for reproducibility."""
    d = _split(df, r)
    rng = np.random.default_rng(r.get("seed", 7))
    y, a, b = d["y"].values, d[r["a"]].values, d[r["b"]].values
    diffs = []
    for _ in range(r.get("n_boot", 300)):
        i = rng.integers(0, len(y), len(y))
        if len(np.unique(y[i])) < 2:
            continue
        diffs.append(M.gini(y[i], a[i]) - M.gini(y[i], b[i]))
    return float(np.percentile(diffs, r["q"]))


def _decision_flips(df, r):
    d = _split(df, r)
    return float(((d[r["a"]] <= r["cutoff"]) != (d[r["b"]] <= r["cutoff"])).sum())


def _auc_abs(df, r):
    d = _split(df, r)
    a = M.auc(d[r.get("target", "y")], d[r["score"]])
    return max(a, 1 - a)
_auc_abs.__wrapped_fn__ = M.auc


def _col_agg(agg):
    def run(df, r):
        s = _split(df, r)[r["col"]].astype(float)
        return float({"min": s.min, "max": s.max, "mean": s.mean, "sum": s.sum}[agg]())
    return run


def _el_gap(df, r):
    """Annual expected-loss gap (GBP) = (observed default rate - mean predicted PD) x LGD x EAD x applications."""
    d = _split(df, r)
    return float((d[r.get("target", "y")].mean() - d[r.get("score", "pd")].mean()) * r["lgd"] * r["ead"] * r["volume"])


def _scaled_rate(df, r):
    """Share of rows where condition holds x annual application volume."""
    d = _split(df, r)
    return float(d[r["col"]].astype(bool).mean() * r["volume"])


def _ae_ratio(df, r):
    """Actual / expected: observed outcomes over predicted (frequency x exposure, or mean PD)."""
    d = _split(df, r)
    exp_ = (d[r.get("score", "score")] * d[r["exposure"]]).sum() if r.get("exposure") else d[r.get("score", "score")].sum()
    return float(d[r["target"]].sum() / max(exp_, 1e-12))


def _poisson_dev_explained(df, r):
    """1 - deviance(model) / deviance(intercept-only), Poisson, with exposure."""
    d = _split(df, r)
    y, mu = d[r["target"]].to_numpy(float), (d[r["score"]] * d[r["exposure"]]).to_numpy(float)
    mu0 = d[r["exposure"]].to_numpy(float) * y.sum() / d[r["exposure"]].sum()
    def dev(m):
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.where(y > 0, y * np.log(y / m), 0.0)
        return 2 * np.sum(t - (y - m))
    return float(1 - dev(mu) / dev(mu0))


def _recall_at(df, r):
    d = _split(df, r)
    y, p = d[r["target"]].to_numpy(), d[r.get("score", "score")].to_numpy()
    return float(((p > r["cutoff"]) & (y == 1)).sum() / max((y == 1).sum(), 1))


def _precision_at(df, r):
    d = _split(df, r)
    y, p = d[r["target"]].to_numpy(), d[r.get("score", "score")].to_numpy()
    return float(((p > r["cutoff"]) & (y == 1)).sum() / max((p > r["cutoff"]).sum(), 1))


def _avg_precision(df, r):
    from sklearn.metrics import average_precision_score
    d = _split(df, r)
    return float(average_precision_score(d[r["target"]], d[r.get("score", "score")]))


def _group_mean_ratio(df, r):
    """Lowest group mean of a column divided by the highest group mean."""
    d = _split(df, r)
    g = d.groupby(d[r["group"]].astype(str))[r["col"]].mean()
    return float(g.min() / max(g.max(), 1e-12))


def _monotone_by(df, r):
    """1 if the mean of `col` never increases across the ordered groups of `by`, else 0."""
    d = _split(df, r)
    g = d.groupby(d[r["by"]].astype(str))[r["col"]].mean().sort_index()
    return float(all(np.diff(g.to_numpy()) <= 1e-9))


def _share_eq(df, r):
    d = _split(df, r)
    if r.get("where"):
        c, v = r["where"].split("=", 1)
        d = d[d[c].astype(str) == v]
    return float((d[r["col"]] == r["value"]).mean()) if len(d) else 1.0


def _const(df, r):
    return float(r["value"])


RECIPES: dict[str, tuple[Callable, str]] = {
    "auc": (_perf(M.auc), "Area under ROC curve"),
    "gini": (_perf(M.gini), "Gini = 2·AUC − 1"),
    "ks": (_perf(M.ks), "Kolmogorov–Smirnov statistic (max TPR − FPR)"),
    "brier": (_perf(M.brier), "Brier score: mean squared error of PD"),
    "calibration_ratio": (_perf(M.calibration_ratio), "Mean predicted PD ÷ observed default rate"),
    "max_decile_gap": (_perf(M.max_decile_calibration_gap), "Max |predicted − observed| default rate across score deciles"),
    "psi": (_psi, "Population Stability Index (base vs. comparison)"),
    "dp_diff": (_fair("dp"), "Demographic parity difference in approval rate"),
    "di_ratio": (_fair("di"), "Disparate impact ratio (lowest ÷ highest group approval rate)"),
    "eo_diff": (_fair("eo"), "Equal opportunity difference (approval-rate gap among non-defaulters)"),
    "proxy_auc": (_proxy, "5-fold CV AUC of predicting the protected attribute from model features"),
    "max_abs_diff": (_max_abs_diff, "Maximum absolute difference between two columns"),
    "count_true": (_count_true, "Count of rows where condition holds"),
    "rate_true": (_rate_true, "Share of rows where condition holds"),
    "approval_rate": (_approval, "Share of applicants with PD at or below cutoff"),
    "bad_rate": (_bad_rate, "Observed default rate"),
    "gini_diff_ci": (_gini_diff_ci, "Bootstrap percentile of Gini difference (seeded)"),
    "decision_flips": (_decision_flips, "Applicants whose approve/decline decision differs between two models"),
    "auc_abs": (_auc_abs, "Univariate AUC of a single feature (max of AUC, 1−AUC)"),
    "col_min": (_col_agg("min"), "Minimum of a stored column"),
    "col_max": (_col_agg("max"), "Maximum of a stored column"),
    "col_mean": (_col_agg("mean"), "Mean of a stored column"),
    "el_gap": (_el_gap, "Annual expected-loss gap: (observed − predicted default rate) × LGD × EAD × volume"),
    "scaled_rate": (_scaled_rate, "Share of applicants affected × annual application volume"),
    "ae_ratio": (_ae_ratio, "Actual ÷ expected outcomes (1.0 = predictions match experience)"),
    "poisson_dev_explained": (_poisson_dev_explained, "Share of Poisson deviance explained vs an intercept-only model"),
    "recall_at": (_recall_at, "Share of true positives flagged at the coded threshold (recall)"),
    "precision_at": (_precision_at, "Share of flags that are true positives at the coded threshold (precision)"),
    "avg_precision": (_avg_precision, "Average precision (area under the precision-recall curve)"),
    "group_mean_ratio": (_group_mean_ratio, "Lowest group mean ÷ highest group mean"),
    "monotone_by": (_monotone_by, "1 if the column falls (never rises) across ordered groups, else 0"),
    "share_eq": (_share_eq, "Share of rows where a column equals a value"),
    "const": (_const, "Measured value recorded at run time (not recomputable from data)"),
}


def _code_hash(fn_name: str) -> tuple[str, str]:
    fn, _ = RECIPES[fn_name]
    target = getattr(fn, "__wrapped_fn__", fn)
    try:
        src = inspect.getsource(target)
    except (OSError, TypeError):
        src = fn_name
    return hashlib.sha256(src.encode()).hexdigest(), src


def compute(recipe: dict) -> float:
    fn, _ = RECIPES[recipe["fn"]]
    df = load_artifact(recipe["artifact"]) if recipe.get("artifact") else pd.DataFrame()
    return float(fn(df, recipe))


# ---------------------------------------------------------------- store API
class Recorder:
    """Batch-records metrics for one run/stage; writes one ledger entry per batch."""

    def __init__(self, run_id: str, model_id: str, stage: str, agent: str):
        self.run_id, self.model_id, self.stage, self.agent = run_id, model_id, stage, agent
        self.rows: list[Metric] = []

    def measure(self, name: str, recipe: dict, *, definition: str | None = None,
                split: str = "", slice_: str = "", emit: bool = True) -> float:
        value = compute(recipe)
        code_hash, _ = _code_hash(recipe["fn"])
        data_hash = file_sha256(recipe["artifact"]) if recipe.get("artifact") else ""
        m = Metric(run_id=self.run_id, name=name, value=value, split=split or recipe.get("split", ""),
                   slice=slice_ or recipe.get("slice", ""), definition=definition or RECIPES[recipe["fn"]][1],
                   recipe=recipe, code_hash=code_hash, data_hash=data_hash)
        with session() as s:
            # replace any earlier value of the same metric in the same run
            for old in s.exec(select(Metric).where(Metric.run_id == self.run_id, Metric.name == name)).all():
                s.delete(old)
            s.add(m)
            s.commit()
            s.refresh(m)
        self.rows = [r for r in self.rows if r.name != name] + [m]  # a re-measure replaces the earlier row
        if emit:
            bus.publish("metric", f"{name} = {value:.4g}", run_id=self.run_id, model_id=self.model_id,
                        stage=self.stage, agent=self.agent, payload={"metric": name, "value": value,
                                                                     "token": token(self.run_id, name)})
        return value

    def const(self, name: str, value: float, definition: str) -> float:
        return self.measure(name, {"fn": "const", "value": float(value)}, definition=definition, emit=False)

    def commit(self, label: str) -> None:
        if not self.rows:
            return
        digest = hashlib.sha256("|".join(f"{m.name}={m.value!r}" for m in self.rows).encode()).hexdigest()
        e = ledger.append(self.agent, "metrics_recorded", {
            "run_id": self.run_id, "model_id": self.model_id, "stage": self.stage, "label": label,
            "count": len(self.rows), "metrics_digest": digest,
            "metrics": {m.name: m.value for m in self.rows}})
        with session() as s:
            for m in self.rows:
                m.ledger_seq = e.seq
                s.add(m)
            s.commit()
        self.rows = []


def token(run_id: str, name: str) -> str:
    return f"m:{run_id}:{name}"


def get(run_id: str, name: str) -> Metric | None:
    with session() as s:
        return s.exec(select(Metric).where(Metric.run_id == run_id, Metric.name == name)).first()


def for_run(run_id: str) -> list[Metric]:
    with session() as s:
        return list(s.exec(select(Metric).where(Metric.run_id == run_id)).all())


def value(run_id: str, name: str, default: float = float("nan")) -> float:
    m = get(run_id, name)
    return m.value if m else default


def reproduce(m: Metric) -> dict[str, Any]:
    if m.recipe.get("fn") == "const":
        return {"reproduced": None, "stored": m.value, "recomputed": None, "match": None,
                "note": "Measured at run time (wall-clock / cost); not recomputable from data."}
    t0 = time.perf_counter()
    current_data_hash = file_sha256(m.recipe["artifact"]) if m.recipe.get("artifact") else ""
    _load.cache_clear()
    v = compute(m.recipe)
    code_hash, _ = _code_hash(m.recipe["fn"])
    match = bool(np.isclose(v, m.value, rtol=0, atol=1e-12))
    return {
        "stored": m.value, "recomputed": v, "abs_diff": abs(v - m.value), "match": match,
        "data_hash_match": current_data_hash == m.data_hash, "code_hash_match": code_hash == m.code_hash,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def source_of(fn_name: str) -> str:
    return _code_hash(fn_name)[1]
