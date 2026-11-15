"""Monitor agent: deploys a validated model behind live (simulated) traffic with ITS monitoring plan, and — when a
red alert starts a re-validation — diagnoses what changed before the validator re-runs the plan."""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
from sqlmodel import select

from app import repositories as repo
from app.agents.common import StageCtx
from app.agents.runtime import Agent, Tool, ToolError, run as run_agent
from app.core import llm
from app.core.db import session
from app.domain.tables import MonitorAlert
from app.engine import serving, traffic
from app.evidence import ledger
from app.services import plans, prompts
from app.tools import metrics as M


def _set_meta(model_id: str, **kw) -> None:
    m = repo.models.get(model_id)
    repo.models.update(model_id, meta={**(m.meta or {}), **kw})


# ------------------------------------------------------------------ setup tools
def t_smoke(ctx: StageCtx, args: dict) -> dict:
    ep = serving.get(ctx.model_id)
    if ep is None:
        raise ToolError("no certified Python endpoint: rehosted models cannot be deployed")
    rows = ep.bundle.frame.sample(min(25, ep.bundle.n), random_state=3)
    lat = []
    for i in range(len(rows)):
        t0 = time.perf_counter()
        ep.predict(rows.iloc[[i]])
        lat.append((time.perf_counter() - t0) * 1000)
    return {"requests": len(rows), "p50_ms": round(float(np.percentile(lat, 50)), 2), "p95_ms": round(float(np.percentile(lat, 95)), 2)}


def t_deploy(ctx: StageCtx, args: dict) -> dict:
    if plans.current(ctx.model_id, "monitoring") is None:
        raise ToolError("no monitoring plan — the documentation stage must draft one")
    cfg = traffic.sim.deploy(ctx.model_id)
    if args.get("rpm"):
        traffic.sim.set(ctx.model_id, rpm=float(args["rpm"]))
    _set_meta(ctx.model_id, status="monitored")
    ledger.append("monitor", "model_deployed", {"run_id": ctx.run_id, "model_id": ctx.model_id, "rpm": cfg["rpm"],
                                                "plan_version": plans.current_row(ctx.model_id, "monitoring").version})
    return {"endpoint": f"/score/{ctx.model_id}", "rpm": traffic.sim.models[ctx.model_id].cfg["rpm"], "window_s": traffic.WINDOW}


def t_rules(ctx: StageCtx, args: dict) -> dict:
    mt = traffic.sim.models.get(ctx.model_id)
    if mt is None:
        raise ToolError("deploy first")
    return {"rules": [f"{r.id}: {r.kpi} {r.op} {r.threshold} ×{r.windows} → {r.severity}/{r.action}" for r in mt.plan.rules],
            "panels": [p.title for p in mt.plan.panels], "scenarios": [s.title for s in mt.plan.scenarios]}


SETUP = Agent(
    name="monitor", stage="monitor_setup",
    goal="Deploy the certified model as a live endpoint with its approved monitoring plan: smoke-test it, start traffic, arm the alert rules.",
    tools=[Tool("smoke_test", "Score 25 rows one at a time through the endpoint and measure latency", t_smoke,
                summary=lambda r: f"{r['requests']} requests · p95 {r['p95_ms']} ms", observe=lambda r: r),
           Tool("deploy", "Start live traffic with the plan's request rate", t_deploy, {"rpm": "optional override of requests per minute"},
                summary=lambda r: f"live at {r['endpoint']} · {r['rpm']} req/min", observe=lambda r: r),
           Tool("arm_rules", "Confirm the alert rules, dashboard and drift scenarios now active", t_rules,
                summary=lambda r: f"{len(r['rules'])} rules armed · {len(r['panels'])} panels", observe=lambda r: r)],
    mandatory=["deploy", "arm_rules"],
    fallback=lambda ctx: next(({"tool": t, "args": {}} for t in ("smoke_test", "deploy", "arm_rules") if not ctx.state.get("ok", {}).get(t)), None),
    max_steps=6)


# ------------------------------------------------------------------ diagnosis tools (re-validation runs)
def _recent(ctx: StageCtx) -> pd.DataFrame:
    f = ctx.run.options.get("recent_file")
    if not f:
        raise ToolError("this run has no live traffic sample")
    return pd.read_csv(f, low_memory=False)


def t_alert(ctx: StageCtx, args: dict) -> dict:
    with session() as s:
        al = s.exec(select(MonitorAlert).where(MonitorAlert.revalidation_run_id == ctx.run_id)).first()
    return {"rule": ctx.run.options.get("alert_rule"), "message": al.message if al else ctx.run.options.get("batch_label"),
            "scenario_in_simulator": (traffic.sim.models.get(ctx.model_id).cfg if ctx.model_id in traffic.sim.models else {})}


def t_windows(ctx: StageCtx, args: dict) -> list[dict]:
    keep = ["ts", "status", "health_score", "requests", "latency_p95_ms", "latency_p99_ms", "error_rate", "no_decision_rate",
            "missing_input_rate", "out_of_range_rate", "unseen_category_rate",
            "score_psi", "score_ks", "worst_csi", "worst_csi_feature", "mean_csi", "drifted_features",
            "adverse_rate", "adverse_rate_shift", "mean_score", "ae_ratio", "realized_gini", "realized_ks", "brier"]
    return [{k: w.get(k) for k in keep if w.get(k) is not None} for w in traffic.windows(ctx.model_id, int(args.get("n") or 12))]


def t_drift(ctx: StageCtx, args: dict) -> list[dict]:
    from app.services import specs
    s = specs.current(ctx.model_id)
    ep = serving.get(ctx.model_id)
    base = ep.bundle.frame
    cur = _recent(ctx)
    out = []
    for f in s.features:
        if f not in base or f not in cur:
            continue
        cat = not pd.api.types.is_numeric_dtype(base[f]) or base[f].nunique() <= 12
        v = M.psi_categorical(base[f].astype(str), cur[f].astype(str)) if cat else \
            M.psi(base[f].astype(float), pd.to_numeric(cur[f], errors="coerce").astype(float))
        shift = None if cat else round(float(pd.to_numeric(cur[f], errors="coerce").mean() / max(abs(base[f].astype(float).mean()), 1e-9) - 1), 3)
        out.append({"column": f, "psi": round(v, 4), "mean_shift": shift})
    out.sort(key=lambda r: -r["psi"])
    ctx.state["drift"] = out
    return out[:10]


def t_quality(ctx: StageCtx, args: dict) -> list[dict]:
    """Per input: missing rate, values outside the baseline range, categories the baseline never saw."""
    from app.services import specs
    s = specs.current(ctx.model_id)
    base = serving.get(ctx.model_id).bundle.frame
    cur = _recent(ctx)
    out = []
    for f in s.features:
        if f not in base or f not in cur:
            continue
        row = {"column": f, "missing_live": round(float(cur[f].isna().mean()), 4), "missing_base": round(float(base[f].isna().mean()), 4)}
        cat = not pd.api.types.is_numeric_dtype(base[f]) or base[f].nunique() <= 12
        if cat:
            known = set(base[f].dropna().astype(str))
            live = cur[f].dropna().astype(str)
            new = sorted(set(live) - known)
            row.update({"unseen_rate": round(float((~live.isin(known)).mean()), 4) if len(live) else 0.0, "new_codes": new[:5]})
        else:
            b = base[f].astype(float)
            v = pd.to_numeric(cur[f], errors="coerce").dropna()
            row["out_of_range_rate"] = round(float(((v < b.min()) | (v > b.max())).mean()), 4) if len(v) else 0.0
        row["issue"] = bool(row["missing_live"] - row["missing_base"] > 0.03 or row.get("unseen_rate", 0) > 0.02
                            or row.get("out_of_range_rate", 0) > 0.05)
        out.append(row)
    out.sort(key=lambda r: (not r["issue"], -(r["missing_live"] - r["missing_base"])))
    ctx.state["quality"] = out
    return out[:10]


def t_score_shift(ctx: StageCtx, args: dict) -> dict:
    """Re-score the recent live sample and compare the score distribution and adverse rate with the baseline."""
    ep = serving.get(ctx.model_id)
    base = ep.predict(ep.bundle.frame.sample(min(1500, ep.bundle.n), random_state=7))
    live = ep.predict(_recent(ctx))
    bs, ls = base["score"].astype(float).dropna(), live["score"].astype(float).dropna()
    q = [0.1, 0.25, 0.5, 0.75, 0.9]
    out = {"quantiles": {f"p{int(x * 100)}": {"baseline": round(float(bs.quantile(x)), 5), "live": round(float(ls.quantile(x)), 5)} for x in q},
           "ks": round(M.ks_two_sample(bs, ls), 4), "psi": round(M.psi(bs, ls), 4),
           "adverse_rate": {"baseline": round(float(base["flag"].mean()), 4), "live": round(float(live["flag"].mean()), 4)} if "flag" in base else None,
           "unscored_live": round(float(live["score"].isna().mean()), 4)}
    ctx.state["score_shift"] = out
    return out


def _fallback_diagnosis(drift: list[dict], quality: list[dict], shift: dict, windows: list[dict]) -> dict:
    """Rule-based diagnosis when no LLM is available: look at each aspect in turn."""
    last = windows[-1] if windows else {}
    bad_q = [q["column"] for q in quality if q.get("issue")]
    ae = last.get("ae_ratio")
    top = drift[0] if drift else None
    reasons = []
    if bad_q:
        reasons.append(f"Data-quality issue on {', '.join(bad_q[:3])} (missing values, new codes or out-of-range inputs)")
        return {"diagnosis": f"The input feed changed: {', '.join(bad_q[:3])} no longer look like the development data.",
                "likely_cause": "data issue", "action": "rollback", "reasons": reasons + ["Fix the upstream feed before trusting new scores"]}
    if (last.get("error_rate") or 0) > 0.01 or (last.get("latency_p95_ms") or 0) > 150:
        return {"diagnosis": "Serving is degraded (errors or latency); the model itself may be fine.", "likely_cause": "operational",
                "action": "accept", "reasons": [f"error rate {last.get('error_rate')}, p95 {last.get('latency_p95_ms')} ms"]}
    if top and top["psi"] > 0.1:
        reasons.append(f"Largest input shift: {top['column']} (PSI {top['psi']})")
        if shift:
            reasons.append(f"Score KS vs baseline {shift.get('ks')}")
        if ae is not None and not 0.8 <= ae <= 1.25:
            reasons.append(f"A/E {ae} outside 0.8–1.25")
        return {"diagnosis": f"The population has shifted, led by {top['column']}; the validation evidence may no longer apply.",
                "likely_cause": "population shift", "action": "revalidate", "reasons": reasons}
    if ae is not None and not 0.8 <= ae <= 1.25:
        return {"diagnosis": f"Inputs are stable but realised outcomes differ from predictions (A/E {ae}).",
                "likely_cause": "calibration drift", "action": "recalibrate", "reasons": [f"A/E {ae}", "No material input drift"]}
    if last.get("realized_gini") is not None and last["realized_gini"] < 0.2:
        return {"diagnosis": "Rank ordering on matured outcomes has weakened.", "likely_cause": "performance deterioration",
                "action": "retrain", "reasons": [f"realised Gini {last['realized_gini']}"]}
    return {"diagnosis": "No single clear cause; re-validate on recent traffic.", "likely_cause": "performance deterioration",
            "action": "revalidate", "reasons": ["Red alert on live traffic"]}


DIAG_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["diagnosis", "likely_cause", "action", "reasons"],
               "properties": {"diagnosis": {"type": "string"}, "likely_cause": {"type": "string"},
                              "action": {"type": "string", "enum": ["revalidate", "recalibrate", "retrain", "rollback", "accept"]},
                              "reasons": {"type": "array", "items": {"type": "string"}}}}


def t_diagnose(ctx: StageCtx, args: dict) -> dict:
    alert = t_alert(ctx, {})
    drift = ctx.state.get("drift") or t_drift(ctx, {})
    quality = ctx.state.get("quality") or t_quality(ctx, {})
    shift = ctx.state.get("score_shift") or t_score_shift(ctx, {})
    wins = t_windows(ctx, {"n": 10})
    r = llm.complete_json("diagnose", prompts.render(
        "diagnose", model_id=ctx.model_id, alert=json.dumps(alert, default=str)[:800], windows=json.dumps(wins, default=str)[:3500],
        drift=json.dumps(drift[:8]), quality=json.dumps(quality[:8], default=str)[:1500], score_shift=json.dumps(shift, default=str)[:800],
        scenario=json.dumps(alert.get("scenario_in_simulator", {}), default=str)[:400]),
        DIAG_SCHEMA, lambda: _fallback_diagnosis(drift, quality, shift, wins),
        run_id=ctx.run_id, agent="monitor", spent=ctx.spent)
    d = r.data
    with session() as s:
        al = s.exec(select(MonitorAlert).where(MonitorAlert.revalidation_run_id == ctx.run_id)).first()
        if al:
            al.action = f"{al.action} · diagnosis: {d['action']}"
            s.add(al)
            s.commit()
    (ctx.dir / "diagnosis.json").write_text(json.dumps({**d, "drift": drift[:10], "quality": quality[:10], "score_shift": shift,
                                                        "alert": alert}, indent=2, default=str))
    ctx.artifact("diagnosis", ctx.dir / "diagnosis.json")
    ledger.append("monitor", "alert_diagnosed", {"run_id": ctx.run_id, "model_id": ctx.model_id, "action": d["action"],
                                                 "cause": d["likely_cause"]})
    ctx.state["diagnosis"] = d
    return d


DIAGNOSE = Agent(
    name="monitor", stage="diagnose",
    goal="A red live alert started this re-validation. Work out what changed, aspect by aspect — operations (errors, "
         "latency), input data quality, input drift, score distribution, outcomes (A/E, Gini) — and recommend an action "
         "before the validator re-runs the plan on recent traffic.",
    tools=[Tool("alert_context", "The alert that fired and the simulator's current settings", t_alert, summary=lambda r: str(r.get("message"))[:160],
                observe=lambda r: r),
           Tool("kpi_history", "Recent KPI windows", t_windows, {"n": "number of windows (default 12)"},
                summary=lambda r: f"{len(r)} windows", observe=lambda r: r),
           Tool("input_drift", "PSI of every input between the validation baseline and recent live requests", t_drift,
                summary=lambda r: f"largest shift: {r[0]['column']} PSI {r[0]['psi']}" if r else "no inputs", observe=lambda r: r),
           Tool("data_quality", "Per input: missing values, out-of-range numbers and unseen category codes, live vs baseline", t_quality,
                summary=lambda r: (f"{sum(x['issue'] for x in r)} input(s) with data issues" + (f": {r[0]['column']}" if r and r[0]["issue"] else "")),
                observe=lambda r: r),
           Tool("score_shift", "Compare live vs baseline score quantiles, KS, PSI and adverse-decision rate", t_score_shift,
                summary=lambda r: f"score KS {r['ks']} · PSI {r['psi']}", observe=lambda r: r),
           Tool("diagnose", "Write the diagnosis and recommended action", t_diagnose,
                summary=lambda r: f"{r['likely_cause']} → {r['action']}", observe=lambda r: r)],
    mandatory=["diagnose"],
    fallback=lambda ctx: next(({"tool": t, "args": {}} for t in ("kpi_history", "input_drift", "data_quality", "score_shift", "diagnose")
                               if not ctx.state.get("ok", {}).get(t)), None),
    max_steps=9)


def setup(ctx: StageCtx) -> dict:
    c = run_agent(ctx, SETUP)
    return {"conclusion": c, "deployed": ctx.model_id in traffic.sim.models}


def diagnose(ctx: StageCtx) -> dict:
    c = run_agent(ctx, DIAGNOSE)
    d = ctx.state.get("diagnosis") or {}
    return {"conclusion": c, "action": d.get("action"), "likely_cause": d.get("likely_cause")}
