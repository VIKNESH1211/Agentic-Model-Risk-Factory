"""Deterministic baseline plans, derived only from a spec's task, columns and groups (no model knowledge).

Used when the language model is unavailable, and shown to the planner as the floor it should improve on.
"""
from __future__ import annotations

from app.domain.schemas import (AlertRule, Check, ModelSpec, MonitoringPlan, Panel, Scenario, Threshold, Transform,
                                ValidationPlan)


def validation_plan(spec: ModelSpec) -> ValidationPlan:
    c: list[Check] = []
    T = Threshold
    if spec.task in ("binary", "frequency") and spec.target:
        y = spec.target if spec.task == "binary" else "occurred"
        for sp in ("test", "oot"):
            c.append(Check(id=f"performance.gini_{sp}", title=f"Discrimination (Gini) on {sp}", category="performance",
                           metric="gini", params={"target": y, "score": "score", "split": sp},
                           threshold=T(op="<", amber=0.40 if spec.task == "binary" else 0.15, red=0.25 if spec.task == "binary" else 0.05),
                           severity="high", rationale="A model that cannot rank risk is unfit for decisions."))
    if spec.task == "binary" and spec.target:
        c.append(Check(id="calibration.ratio_holdout", title="Calibration (predicted ÷ observed)", category="calibration",
                       metric="calibration_ratio", params={"target": spec.target, "score": "score", "split": "test|oot"},
                       threshold=T(op=">", amber=1.2, red=1.5), severity="medium"))
        c.append(Check(id="calibration.ratio_low", title="Calibration — under-prediction", category="calibration",
                       metric="calibration_ratio", params={"target": spec.target, "score": "score", "split": "test|oot"},
                       threshold=T(op="<", amber=0.8, red=0.6), severity="medium"))
    if spec.task == "frequency" and spec.target:
        c.append(Check(id="calibration.ae_holdout", title="Actual vs expected claims", category="calibration", metric="ae_ratio",
                       params={"target": spec.target, "score": "score", "exposure": spec.exposure, "split": "test|oot"}
                       if spec.exposure else {"target": spec.target, "score": "score", "split": "test|oot"},
                       threshold=T(op=">", amber=1.15, red=1.3), severity="medium"))
    c.append(Check(id="stability.score_psi", title="Score stability train → oot (PSI)", category="stability", metric="psi",
                   params={"col": "score", "base": "train", "comp": "oot"}, threshold=T(op=">", amber=0.10, red=0.25), severity="medium"))
    if spec.features:
        c.append(Check(id="stability.csi", title="Input stability train → oot (CSI)", category="stability", metric="psi",
                       params={"base": "train", "comp": "oot"}, expand="features", threshold=T(op=">", amber=0.10, red=0.25),
                       severity="low"))
    if spec.groups and spec.decision.kind in ("approve", "alert", "limit"):
        c.append(Check(id="fairness.di_ratio", title="Favourable-outcome parity across groups (disparate impact)",
                       category="fairness", metric="di_ratio", params={"split": "all"}, expand="groups",
                       threshold=T(op="<", amber=0.8, red=0.6), severity="medium"))
    if spec.groups and spec.decision.kind == "price":
        c.append(Check(id="fairness.price_ratio", title="Price parity across groups", category="fairness", metric="group_mean_ratio",
                       params={"col": "score", "split": "all"}, expand="groups", threshold=T(op="<", amber=0.8, red=0.6), severity="medium"))
    c.append(Check(id="data_quality.missing", title="Rows with a missing model input", category="data_quality", metric="rate_true",
                   params={"col": "missing_any", "split": "test|oot"}, threshold=T(op=">", amber=0.02, red=0.10), severity="medium"))
    if spec.decision.kind in ("approve", "alert", "limit"):
        c.append(Check(id="policy.adverse_rate", title="Share of adverse decisions", category="policy", metric="rate_true",
                       params={"col": "flag", "split": "all"}, threshold=None, severity="low",
                       rationale="Context for the decision rule; no pass/fail."))
    return ValidationPlan(checks=c, investigations=["slice_search", "stress_test"] + (["challenger"] if spec.task == "binary" else []),
                          rationale="Baseline plan derived from the task, decision rule and groups in the specification.")


def monitoring_plan(spec: ModelSpec, numeric: list[str] | None = None) -> MonitoringPlan:
    R = AlertRule
    rules = [
        # stability
        R(id="score_psi_amber", kpi="score_psi", op=">", threshold=0.10, windows=3, severity="amber",
          rationale="Score distribution moving away from the validation baseline"),
        R(id="score_psi_red", kpi="score_psi", op=">", threshold=0.25, windows=3, severity="red", action="revalidate",
          rationale="Significant population shift: the validation evidence no longer describes live traffic"),
        R(id="input_csi_red", kpi="worst_csi", op=">", threshold=0.25, windows=3, severity="red", action="revalidate",
          rationale="At least one input has shifted significantly"),
        R(id="drift_breadth", kpi="drifted_features", op=">", threshold=2, windows=3, severity="amber",
          rationale="Several inputs drifting together usually means a population or pipeline change"),
        # data quality
        R(id="missing_inputs", kpi="missing_input_rate", op=">", threshold=0.05, windows=2, severity="amber",
          rationale="Upstream feed is dropping values"),
        R(id="out_of_range", kpi="out_of_range_rate", op=">", threshold=0.05, windows=2, severity="amber",
          rationale="Inputs outside anything the model saw in development: extrapolation risk"),
        R(id="unseen_categories", kpi="unseen_category_rate", op=">", threshold=0.02, windows=2, severity="amber",
          rationale="New category codes the model has no estimate for"),
        # operations
        R(id="errors", kpi="error_rate", op=">", threshold=0.01, windows=2, severity="amber"),
        R(id="availability", kpi="availability", op="<", threshold=0.95, windows=2, severity="red",
          rationale="More than 5% of requests failing"),
        R(id="no_decision", kpi="no_decision_rate", op=">", threshold=0.02, windows=2, severity="amber"),
        R(id="latency", kpi="latency_p95_ms", op=">", threshold=150, windows=3, severity="amber"),
        R(id="latency_tail", kpi="latency_p99_ms", op=">", threshold=400, windows=3, severity="amber"),
        # decisions
        R(id="adverse_shift", kpi="adverse_rate_shift", op=">", threshold=0.10, windows=3, severity="amber",
          rationale="Adverse decisions 10 points above the baseline rate"),
    ]
    panels = [Panel(id="volume", title="Volume & latency", kind="area", kpis=["rpm", "latency_p95_ms", "latency_p99_ms"]),
              Panel(id="stability", title="Stability (PSI / CSI)", kpis=["score_psi", "worst_csi", "mean_csi"]),
              Panel(id="data_quality", title="Input data quality", kind="bar", kpis=["missing_input_rate", "out_of_range_rate", "unseen_category_rate"]),
              Panel(id="quality", title="Errors & no-decision", kind="bar", kpis=["error_rate", "no_decision_rate"]),
              Panel(id="decisions", title="Mean score & adverse rate", kpis=["mean_score", "adverse_rate"])]
    if spec.task in ("binary", "frequency") and spec.target:
        rules += [R(id="ae_high", kpi="ae_ratio", op=">", threshold=1.25, windows=3, severity="red", action="revalidate",
                    rationale="More adverse outcomes than the model predicts"),
                  R(id="ae_low", kpi="ae_ratio", op="<", threshold=0.8, windows=3, severity="red", action="revalidate",
                    rationale="Fewer adverse outcomes than predicted: the model is over-conservative")]
        panels.append(Panel(id="outcomes", title="Actual vs expected", kpis=["realized_rate", "predicted_rate", "ae_ratio"]))
        if spec.task == "binary":
            rules.append(R(id="gini_drop", kpi="realized_gini", op="<", threshold=0.2, windows=3, severity="amber",
                           rationale="Rank-ordering power on matured outcomes has weakened"))
            panels.append(Panel(id="discrimination", title="Discrimination on matured outcomes", kpis=["realized_gini", "realized_ks"]))
    scen = []
    if numeric:
        scen.append(Scenario(id="inflation", title=f"{numeric[0]} inflates", description=f"{numeric[0]} rises across the book",
                             transforms=[Transform(op="scale", column=numeric[0], value=1.0)]))
    if spec.target and spec.task == "binary":
        scen.append(Scenario(id="deterioration", title="Outcomes deteriorate", description="More adverse outcomes than predicted",
                             transforms=[Transform(op="flip_target", column=spec.target, value=1, fraction=0.25)]))
    return MonitoringPlan(kpis=sorted({k for p in panels for k in p.kpis}), rules=rules, panels=panels, scenarios=scen, rpm=240,
                          rationale="Baseline plan: standard stability, operational and outcome rules for the task.")
