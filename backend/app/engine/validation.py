"""Execute an approved validation plan: every check → metric store (reproducible) → status from its threshold.

Pass / amber / red is decided here by the plan's thresholds — never by a language model.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import pandas as pd

from app.domain.schemas import Check, ModelSpec, Threshold, ValidationPlan
from app.engine.catalog import CATALOG, expand
from app.engine.scoring import OPS
from app.evidence.metric_store import Recorder, token

DOWNGRADE = {"high": "medium", "medium": "low", "low": "low"}


@dataclass
class CheckResult:
    check_id: str
    metric_name: str
    title: str
    category: str
    metric: str
    value: float | None
    status: str  # pass | amber | red | info | error
    threshold: dict | None
    severity: str
    token: str
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def status_of(v: float | None, th: Threshold | None) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "error"
    if th is None:
        return "info"
    if th.red is not None and OPS[th.op](v, th.red):
        return "red"
    if th.amber is not None and OPS[th.op](v, th.amber):
        return "amber"
    return "pass"


def _categorical(df: pd.DataFrame, col: str) -> bool:
    return col in df and (not pd.api.types.is_numeric_dtype(df[col]) or df[col].nunique() <= 12)


def run_check(c: Check, spec: ModelSpec, scored_rel: str, scored: pd.DataFrame, rec: Recorder) -> list[CheckResult]:
    out = []
    cols = set(scored.columns)
    for name, params in expand(c, spec, cols):
        recipe = {"fn": c.metric, "artifact": scored_rel, **params}
        if c.metric == "psi" and "categorical" not in params:
            recipe["categorical"] = _categorical(scored, params.get("col", ""))
        title = c.title + (f" — `{params.get('col') or params.get('group')}`" if name != c.id else "")
        try:
            v = rec.measure(name, recipe, definition=f"{c.title}. {CATALOG[c.metric].description}", emit=False)
            err = ""
        except Exception as e:
            v, err = None, f"{type(e).__name__}: {e}"[:200]
        out.append(CheckResult(c.id, name, title, c.category, c.metric, v, status_of(v, c.threshold),
                               c.threshold.model_dump() if c.threshold else None, c.severity, token(rec.run_id, name), err))
    return out


def execute(plan: ValidationPlan, spec: ModelSpec, scored_rel: str, scored: pd.DataFrame, rec: Recorder) -> list[CheckResult]:
    results: list[CheckResult] = []
    for c in plan.checks:
        results.extend(run_check(c, spec, scored_rel, scored, rec))
    return results


def summarise(results: list[CheckResult]) -> dict:
    by = {s: sum(r.status == s for r in results) for s in ("pass", "amber", "red", "info", "error")}
    rating = "Not fit for use" if by["red"] else "Fit for use with conditions" if by["amber"] else "Fit for use"
    return {"counts": by, "rating": rating, "total": len(results)}


def finding_severity(r: CheckResult) -> str | None:
    if r.status == "red":
        return r.severity
    if r.status == "amber":
        return DOWNGRADE[r.severity]
    return None
