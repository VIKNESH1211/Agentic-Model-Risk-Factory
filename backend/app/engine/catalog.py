"""Metric catalog + plan linter.

Agents compose validation plans ONLY from these deterministic functions (they live in
evidence/metric_store.RECIPES, so every result is reproducible). The linter rejects a plan that names an
unknown metric, misses a parameter, or points at a column the scored frame does not have.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain.schemas import Check, MonitoringPlan, ModelSpec, ValidationPlan
from app.evidence.metric_store import RECIPES

# param kinds: col (a column) · cols (list of columns) · split · num · str · bool
SPLIT = "split"


@dataclass(frozen=True)
class MetricDef:
    fn: str
    params: dict[str, str]
    required: tuple[str, ...]
    tasks: tuple[str, ...] = ("binary", "frequency", "regression", "rules")
    note: str = ""
    defaults: dict = field(default_factory=dict)
    better: str | None = None  # "higher" | "lower" | None (two-sided or context)

    @property
    def description(self) -> str:
        return RECIPES[self.fn][1]


_PERF = {"target": "col", "score": "col", "split": SPLIT, "slice": "str"}
_CATALOG: list[MetricDef] = [
    MetricDef("auc", _PERF, ("target", "score"), ("binary", "frequency"), "target must be 0/1 (use `occurred` for frequency)"),
    MetricDef("gini", _PERF, ("target", "score"), ("binary", "frequency"), "target must be 0/1 (use `occurred` for frequency)"),
    MetricDef("ks", _PERF, ("target", "score"), ("binary",)),
    MetricDef("brier", _PERF, ("target", "score"), ("binary",), "score must be a probability"),
    MetricDef("calibration_ratio", _PERF, ("target", "score"), ("binary",), "mean predicted ÷ observed rate; 1.0 = calibrated"),
    MetricDef("max_decile_gap", _PERF, ("target", "score"), ("binary",)),
    MetricDef("psi", {"col": "col", "base": SPLIT, "comp": SPLIT, "categorical": "bool"}, ("col", "base", "comp"),
              note="population stability of a column between two splits (score or any input)"),
    MetricDef("dp_diff", {"group": "col", "approve": "col", "split": SPLIT}, ("group",), note="approve defaults to `approve`"),
    MetricDef("di_ratio", {"group": "col", "approve": "col", "split": SPLIT}, ("group",), note="four-fifths rule: < 0.8 is a concern"),
    MetricDef("eo_diff", {"group": "col", "approve": "col", "target": "col", "split": SPLIT}, ("group", "target"), ("binary",)),
    MetricDef("proxy_auc", {"features": "cols", "protected": "col", "split": SPLIT}, ("features", "protected"),
              note="can the inputs predict a protected attribute? > 0.7 suggests proxies"),
    MetricDef("rate_true", {"col": "col", "split": SPLIT, "slice": "str"}, ("col",), note="share of rows where a 0/1 column is 1"),
    MetricDef("bad_rate", {"target": "col", "split": SPLIT}, ("target",), ("binary",)),
    MetricDef("auc_abs", {"target": "col", "score": "col", "split": SPLIT}, ("target", "score"), ("binary",),
              "single-feature AUC; > 0.9 hints at target leakage (set score to the feature)"),
    MetricDef("col_min", {"col": "col", "split": SPLIT}, ("col",)),
    MetricDef("col_max", {"col": "col", "split": SPLIT}, ("col",)),
    MetricDef("col_mean", {"col": "col", "split": SPLIT}, ("col",)),
    MetricDef("ae_ratio", {"target": "col", "score": "col", "exposure": "col", "split": SPLIT, "slice": "str"}, ("target", "score"),
              ("binary", "frequency"), "actual ÷ expected; 1.0 = predictions match experience"),
    MetricDef("poisson_dev_explained", {"target": "col", "score": "col", "exposure": "col", "split": SPLIT},
              ("target", "score", "exposure"), ("frequency",)),
    MetricDef("recall_at", {"target": "col", "score": "col", "cutoff": "num", "split": SPLIT}, ("target", "score", "cutoff"), ("binary",)),
    MetricDef("precision_at", {"target": "col", "score": "col", "cutoff": "num", "split": SPLIT}, ("target", "score", "cutoff"), ("binary",)),
    MetricDef("avg_precision", {"target": "col", "score": "col", "split": SPLIT}, ("target", "score"), ("binary",)),
    MetricDef("group_mean_ratio", {"group": "col", "col": "col", "split": SPLIT}, ("group", "col"),
              note="lowest group mean ÷ highest (e.g. price or limit parity across groups)"),
    MetricDef("monotone_by", {"col": "col", "by": "col", "split": SPLIT}, ("col", "by"), note="1 if col never rises across ordered groups of `by`"),
    MetricDef("share_eq", {"col": "col", "value": "num", "where": "str", "split": SPLIT}, ("col", "value"),
              note="share of rows where col == value (optionally where `col=value`)"),
]
HIGHER_IS_BETTER = {'auc', 'gini', 'ks', 'di_ratio', 'recall_at', 'precision_at', 'avg_precision', 'poisson_dev_explained', 'group_mean_ratio', 'monotone_by'}
LOWER_IS_BETTER = {'brier', 'max_decile_gap', 'psi', 'dp_diff', 'eo_diff', 'proxy_auc', 'auc_abs'}
CATALOG: dict[str, MetricDef] = {m.fn: MetricDef(**{**m.__dict__, "better": "higher" if m.fn in HIGHER_IS_BETTER else
                                                    "lower" if m.fn in LOWER_IS_BETTER else None}) for m in _CATALOG}

SPLITS = {"train", "test", "oot", "all", "test|oot", "train|test", "train|test|oot"}
STANDARD_COLUMNS = ["score", "decision", "flag", "approve", "split", "occurred", "missing_any"]

# live KPIs the traffic simulator computes for every deployed model
KPI_CATALOG: dict[str, str] = {
    # operations
    "requests": "Requests in the window", "rpm": "Requests per minute",
    "latency_p50_ms": "Median scoring latency (ms)", "latency_p95_ms": "95th percentile scoring latency (ms)",
    "latency_p99_ms": "99th percentile scoring latency (ms)", "latency_max_ms": "Slowest request in the window (ms)",
    "error_rate": "Share of requests that raised an error", "availability": "Share of requests served without error",
    "no_decision_rate": "Share of requests with no score",
    # data quality (inputs vs the validation baseline profile)
    "missing_input_rate": "Share of input values that are missing",
    "out_of_range_rate": "Share of numeric input values outside the baseline min–max range",
    "unseen_category_rate": "Share of categorical input values never seen in the baseline",
    # stability / drift
    "score_psi": "PSI of live scores vs the validation baseline", "score_ks": "Two-sample KS distance of live vs baseline scores",
    "worst_csi": "Largest input-column PSI vs baseline", "mean_csi": "Average input-column PSI vs baseline",
    "drifted_features": "Number of inputs with PSI above 0.10",
    # decisions & score shape
    "mean_score": "Mean model output", "score_p50": "Median model output", "score_std": "Spread (std dev) of model output",
    "adverse_rate": "Share of adverse decisions (decline / alert)",
    "adverse_rate_shift": "Adverse-decision rate minus the baseline rate (percentage points as a fraction)",
    # outcomes (matured requests)
    "realized_rate": "Observed outcome rate on matured requests", "predicted_rate": "Predicted outcome rate on the same requests",
    "ae_ratio": "Actual ÷ expected on matured requests", "realized_gini": "Gini on matured requests (binary)",
    "realized_ks": "KS separation on matured requests (binary)", "brier": "Brier score on matured requests (binary, lower is better)",
    "realized_recall": "Share of positives flagged on matured requests (binary with cut-off)",
    "realized_precision": "Share of flagged requests that were positive on matured requests (binary with cut-off)",
    # overall
    "health_score": "0–100 composite: 100 minus penalties for firing (red 35, amber 15) and breaching (5) rules",
}


def scored_columns(spec: ModelSpec, frame_columns: list[str]) -> set[str]:
    return set(frame_columns) | set(STANDARD_COLUMNS) | {g.name for g in spec.groups}


def describe(task: str | None = None) -> list[dict]:
    """Catalog as data, for prompts (optionally only the metrics that apply to a task) and the UI."""
    return [{"fn": m.fn, "description": m.description, "params": m.params, "required": list(m.required),
             "tasks": list(m.tasks), "better": m.better, "note": m.note} for m in CATALOG.values() if not task or task in m.tasks]


def valid_checks(plan: ValidationPlan, spec: ModelSpec, columns: set[str]) -> tuple[list, list[str]]:
    """Split a plan into the checks that pass the linter and the errors of the rest."""
    good, errs = [], []
    for c in plan.checks:
        e = lint_validation(plan.model_copy(update={"checks": [c]}), spec, columns)
        (errs.extend(e) if e else good.append(c))
    return good, errs


def safe_name(name: str) -> str:
    """Metric names become evidence tokens ({{m:run:name}}): keep them to [A-Za-z0-9_.-=]."""
    return re.sub(r"[^A-Za-z0-9_.\-=]+", "_", name).strip("_")


def expand(check: Check, spec: ModelSpec, columns: set[str]) -> list[tuple[str, dict]]:
    """(metric name, params) for each instance of a check."""
    if check.expand == "features":
        return [(safe_name(f"{check.id}.{f}"), {**check.params, "col": f}) for f in spec.features if f in columns]
    if check.expand == "groups":
        return [(safe_name(f"{check.id}.{g.name}"), {**check.params, "group": g.name}) for g in spec.groups]
    return [(safe_name(check.id), dict(check.params))]


def lint_validation(plan: ValidationPlan, spec: ModelSpec, columns: set[str]) -> list[str]:
    errs: list[str] = []
    seen: set[str] = set()
    for c in plan.checks:
        where = f"check {c.id}"
        if c.id in seen:
            errs.append(f"{where}: duplicate id")
        seen.add(c.id)
        m = CATALOG.get(c.metric)
        if m is None:
            errs.append(f"{where}: unknown metric '{c.metric}' (choose from {', '.join(CATALOG)})")
            continue
        if spec.task not in m.tasks:
            errs.append(f"{where}: {c.metric} does not apply to {spec.task} models")
        for name, params in expand(c, spec, columns):
            for p in m.required:
                if p not in params:
                    errs.append(f"{where}: missing parameter '{p}'")
            for p, v in params.items():
                kind = m.params.get(p)
                if kind is None:
                    errs.append(f"{where}: unknown parameter '{p}' for {c.metric}")
                elif kind == "col" and v not in columns:
                    errs.append(f"{where}: column '{v}' is not in the scored frame")
                elif kind == "cols" and (not isinstance(v, list) or any(x not in columns for x in v)):
                    errs.append(f"{where}: '{p}' must list scored-frame columns")
                elif kind == SPLIT and v not in SPLITS:
                    errs.append(f"{where}: split '{v}' must be one of {sorted(SPLITS)}")
                elif kind == "num" and not isinstance(v, (int, float)):
                    errs.append(f"{where}: '{p}' must be a number")
            if c.expand and not expand(c, spec, columns):
                errs.append(f"{where}: expands over {c.expand} but the spec has none")
            break  # params are identical across expansions except the expanded column
        th = c.threshold
        if th and th.amber is None and th.red is None:
            errs.append(f"{where}: threshold needs an amber or red limit")
        if th and m.better == "higher" and th.op not in ("<", "<="):
            errs.append(f"{where}: higher {c.metric} is better, so the breach op must be '<' (red when the value falls BELOW the limit)")
        if th and m.better == "lower" and th.op not in (">", ">="):
            errs.append(f"{where}: lower {c.metric} is better, so the breach op must be '>' (red when the value rises ABOVE the limit)")
        if th and th.amber is not None and th.red is not None:
            if th.op in ("<", "<=") and th.red > th.amber:
                errs.append(f"{where}: with op '<' the red limit must be at or below the amber limit")
            if th.op in (">", ">=") and th.red < th.amber:
                errs.append(f"{where}: with op '>' the red limit must be at or above the amber limit")
    if not plan.checks:
        errs.append("plan has no checks")
    return errs


KPI_HIGHER_IS_BETTER = {"realized_gini", "realized_ks", "realized_recall", "realized_precision", "availability", "health_score"}
KPI_LOWER_IS_BETTER = {"score_psi", "score_ks", "worst_csi", "mean_csi", "drifted_features", "error_rate", "no_decision_rate",
                       "latency_p50_ms", "latency_p95_ms", "latency_p99_ms", "latency_max_ms", "missing_input_rate",
                       "out_of_range_rate", "unseen_category_rate", "brier"}


def lint_monitoring(plan: MonitoringPlan, frame_columns: set[str] | None = None) -> list[str]:
    errs = []
    for r in plan.rules:
        if r.kpi in KPI_HIGHER_IS_BETTER and r.op not in ("<", "<="):
            errs.append(f"rule {r.id}: higher {r.kpi} is better, so it must fire when the value is '<' the threshold")
        if r.kpi in KPI_LOWER_IS_BETTER and r.op not in (">", ">="):
            errs.append(f"rule {r.id}: lower {r.kpi} is better, so it must fire when the value is '>' the threshold")
    for sc in plan.scenarios:
        for t in sc.transforms:
            if frame_columns is not None and t.column not in frame_columns:
                errs.append(f"scenario {sc.id}: column '{t.column}' is not in the model's input frame")
    for r in plan.rules:
        if r.kpi not in KPI_CATALOG:
            errs.append(f"rule {r.id}: unknown KPI '{r.kpi}' (choose from {', '.join(KPI_CATALOG)})")
    for p in plan.panels:
        for k in p.kpis:
            if k not in KPI_CATALOG:
                errs.append(f"panel {p.id}: unknown KPI '{k}'")
    for k in plan.kpis:
        if k not in KPI_CATALOG:
            errs.append(f"kpis: unknown KPI '{k}'")
    if not plan.panels:
        errs.append("plan has no dashboard panels")
    return errs
