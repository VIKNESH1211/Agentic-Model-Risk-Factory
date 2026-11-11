"""Factory orchestrator: per-model stage plans with a human promotion gate between every stage.

discover ─▶[promote]▶ document ─▶[promote]▶ redevelop ─▶[promote]▶ validate+report ─▶[promote]▶ monitor (live traffic)
                                                         live alert ──▶ revalidation run: validate → report → [accept]

State lives in the DB (runs.state = checkpoint: next stage index, timeline, agent conclusions; gates; models.meta),
so a restart resumes every run exactly where it stopped. Gates can be decided one by one or in bulk; with the
global "auto-promote" setting on, the agents' own recommendations are applied (hold → still waits for a human).
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd
from sqlmodel import select

from app.agents import discovery, documentation, monitor, redevelop_generic, redevelopment, redteam, validate_generic, validator
from app.agents.common import StageCtx
from app.core.config import settings
from app.core.db import save, session
from app.core.events import bus
from app.domain.tables import AppSetting, Gate, Model, Run
from app.evidence import ledger, metric_store, report_builder, report_generic
from app.modelkit import registry as R
from app.tools.datasets import prepared

FULL = ["discover", "gate_document", "document", "gate_redevelop", "redevelop", "gate_validate", "validate", "report",
        "gate_deploy", "monitor_setup"]
NO_DEPLOY = FULL[:8]
REVAL = ["validate", "report", "gate_accept"]
STATION = {"discover": "discover", "gate_document": "discover", "document": "document", "gate_redevelop": "document",
           "redevelop": "redevelop", "gate_validate": "redevelop", "validate": "validate", "report": "validate",
           "gate_deploy": "validate", "monitor_setup": "monitor", "gate_accept": "validate", "queued": "discover"}
AGENT = {"discover": "discovery", "document": "documentation", "redevelop": "redevelopment", "validate": "validator",
         "report": "report", "monitor_setup": "monitor"}
GATE_TITLES = {"gate_document": "Promote to Document", "gate_redevelop": "Promote to Redevelop",
               "gate_validate": "Promote to Validate", "gate_deploy": "Promote to Monitor (deploy)",
               "gate_accept": "Accept re-validation report"}
NEXT_OF_GATE = {"gate_document": "document", "gate_redevelop": "redevelop", "gate_validate": "validate",
                "gate_deploy": "monitor", "gate_accept": "monitor"}

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="factory")
_lock = threading.Lock()
GEN = {"n": 0, "active": 0}  # a reset bumps the generation; stale workers stop at the next stage boundary


class Stale(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# ------------------------------------------------------------------ settings (persisted)
def get_setting(key: str, default=None):
    with session() as s:
        row = s.get(AppSetting, key)
    return row.value.get("v", default) if row else default


def set_setting(key: str, value) -> None:
    with session() as s:
        row = s.get(AppSetting, key) or AppSetting(key=key)
        row.value = {"v": value}
        s.add(row)
        s.commit()
    bus.publish("info", f"Setting {key} = {value}", agent="system")


# ------------------------------------------------------------------ runs
def stages_for(run: Run) -> list[str]:
    if run.options.get("stages"):
        return run.options["stages"]
    if run.kind == "revalidation":
        return REVAL
    a = R.get(run.model_id)
    return FULL if (a and a.deployable) else NO_DEPLOY


def create_run(model_id: str, *, kind: str = "factory", auto_approve: bool = False, parent: str | None = None,
               extra: dict | None = None) -> Run:
    rid = "run_" + uuid.uuid4().hex[:6]
    r = Run(id=rid, model_id=model_id, kind=kind, parent_run_id=parent, status="queued", stage="queued",
            options={"auto_approve": auto_approve, **(extra or {})}, state={"next": 0, "timeline": [], "conclusions": {}})
    save(r)
    ledger.append("orchestrator", "run_created", {"run_id": rid, "model_id": model_id, "kind": kind, "parent": parent})
    return r


def start(run_id: str, delay: float = 0.0) -> None:
    _pool.submit(_advance_safe, run_id, delay)


def start_portfolio(model_ids: list[str] | None, auto_approve: bool) -> list[Run]:
    discovery.scan_portfolio()
    with session() as s:
        ids = model_ids or [m.id for m in s.exec(select(Model)).all()]
        active = {r.model_id for r in s.exec(select(Run).where(Run.kind == "factory",
                                                               Run.status.in_(["queued", "running", "waiting_gate"]))).all()}
    ids = [i for i in sorted(ids, key=lambda i: (i != "CR-001", i)) if i not in active]
    runs = [create_run(i, auto_approve=auto_approve) for i in ids]
    bus.publish("run_started", f"Factory started for {len(runs)} model(s)", payload={"runs": [r.id for r in runs]})
    for k, r in enumerate(runs):
        start(r.id, delay=k * 0.8)
    return runs


def _update(run_id: str, **kw) -> Run:
    with _lock, session() as s:
        r = s.get(Run, run_id)
        st = dict(r.state)
        for k, v in kw.items():
            if k.startswith("state_"):
                st[k[6:]] = v
            else:
                setattr(r, k, v)
        r.state = st
        s.add(r)
        s.commit()
        s.refresh(r)
        return r


def _advance_safe(run_id: str, delay: float) -> None:
    gen = GEN["n"]
    if delay:
        time.sleep(delay)
    if gen != GEN["n"]:
        return
    GEN["active"] += 1
    try:
        _advance(run_id, gen)
    except Stale:
        return
    except Exception as e:
        if gen != GEN["n"]:
            return
        traceback.print_exc()
        r = _update(run_id, status="failed", ended_at=datetime.now(timezone.utc), state_error=f"{type(e).__name__}: {e}")
        bus.publish("alert", f"✗ {r.model_id} {r.stage} failed: {e}", run_id=run_id, model_id=r.model_id, stage=r.stage)
        ledger.append("orchestrator", "run_failed", {"run_id": run_id, "model_id": r.model_id, "error": str(e)[:300]})
        _set_model(r.model_id, lifecycle={"stage": r.stage, "status": "failed", "run_id": run_id, "error": str(e)[:300]})
    finally:
        GEN["active"] -= 1


def _set_model(model_id: str, **meta) -> None:
    with session() as s:
        m = s.get(Model, model_id)
        if m:
            m.meta = {**(m.meta or {}), **meta}
            s.add(m)
            s.commit()


def _advance(run_id: str, gen: int = 0) -> None:
    with session() as s:
        run = s.get(Run, run_id)
    if run is None:
        return
    stages = stages_for(run)
    if run.status == "queued":
        run = _update(run_id, status="running", started_at=datetime.now(timezone.utc))
        bus.publish("run_started", f"{run.model_id} entered the factory ({run.kind})", run_id=run_id, model_id=run.model_id,
                    payload={"stages": stages, "kind": run.kind})
    i = run.state.get("next", 0)
    while i < len(stages):
        if gen != GEN["n"]:
            raise Stale()
        stage = stages[i]
        run = _update(run_id, stage=stage, status="running")
        if run.kind == "factory":
            _set_model(run.model_id, lifecycle={"stage": stage, "status": "running", "run_id": run_id})
        if stage.startswith("gate_"):
            if not _gate(run, stage):
                return
            i += 1
            _update(run_id, state_next=i)
            continue
        tl = list(run.state.get("timeline", []))
        tl.append({"stage": stage, "station": STATION[stage], "start": _now()})
        _update(run_id, state_timeline=tl)
        bus.publish("stage_started", f"{run.model_id} → {stage}", run_id=run_id, model_id=run.model_id, stage=stage,
                    agent=AGENT.get(stage, ""), payload={"station": STATION[stage]})
        ledger.append(AGENT.get(stage, "orchestrator"), "stage_started", {"run_id": run_id, "model_id": run.model_id, "stage": stage})
        ctx = StageCtx(run, stage, AGENT.get(stage, "orchestrator"))
        ctx.plan(_facts(run))
        result = STAGE_FNS[stage](ctx, run)
        conclusion = ctx.conclude(_summary(result))
        with session() as s:
            run = s.get(Run, run_id)
        tl = list(run.state.get("timeline", []))
        tl[-1]["end"] = _now()
        concl = {**run.state.get("conclusions", {}), stage: conclusion}
        _update(run_id, state_timeline=tl, state_conclusions=concl, **{f"state_{stage}": _summary(result)})
        bus.publish("stage_completed", f"{run.model_id} ✓ {stage} · agent recommends {conclusion['recommendation'].upper()}",
                    run_id=run_id, model_id=run.model_id, stage=stage, agent=AGENT.get(stage, ""), payload={"station": STATION[stage]})
        ledger.append(AGENT.get(stage, "orchestrator"), "stage_completed", {"run_id": run_id, "model_id": run.model_id,
                                                                            "stage": stage, "recommendation": conclusion["recommendation"]})
        i += 1
        _update(run_id, state_next=i)
    _complete(run_id)


def _facts(run: Run) -> dict:
    a = R.get(run.model_id)
    with session() as s:
        m = s.get(Model, run.model_id)
    return {"model": run.model_id, "name": m.name if m else "", "type": m.type if m else "", "tier": m.tier if m else "",
            "strategy": a.strategy if a else "", "task": a.spec.task if a else "", "run_kind": run.kind,
            "deployable": a.deployable if a else False}


def _complete(run_id: str) -> None:
    with session() as s:
        run = s.get(Run, run_id)
    ended = datetime.now(timezone.utc)
    started = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=timezone.utc)
    rt = (ended - started).total_seconds()
    run = _update(run_id, status="completed", ended_at=ended, state_runtime_s=rt)
    metric_store.Recorder(run_id, run.model_id, "complete", "orchestrator").const(
        "runtime_s.factory", rt, "Measured wall-clock seconds for this run (includes time waiting at human gates)")
    if run.kind == "factory":
        last = stages_for(run)[-1]
        _set_model(run.model_id, lifecycle={"stage": last, "status": "done", "run_id": run_id})
    bus.publish("run_completed", f"{run.model_id} completed ({run.kind}) in {rt:.0f}s", run_id=run_id, model_id=run.model_id,
                payload={"runtime_s": rt, "kind": run.kind})
    ledger.append("orchestrator", "run_completed", {"run_id": run_id, "model_id": run.model_id, "runtime_s": round(rt, 2)})


def _summary(result) -> dict:
    if not isinstance(result, dict):
        return {}
    return {k: v for k, v in result.items() if isinstance(v, (str, int, float, bool, list)) and k != "model"}


# ------------------------------------------------------------------ gates
def _gate_context(run: Run, stage: str) -> dict:
    stages = stages_for(run)
    prev = stages[stages.index(stage) - 1] if stages.index(stage) > 0 else None
    concl = run.state.get("conclusions", {}).get(prev) if prev else None
    ctx = {"completed": prev, "next": NEXT_OF_GATE.get(stage), "agent": concl}
    with session() as s:
        m = s.get(Model, run.model_id)
    if stage == "gate_document":
        ctx["summary"] = f"Discovered: {m.type}, Tier {m.tier}. {m.tier_rationale}"
    elif stage == "gate_redevelop":
        ctx["summary"] = "ModelDoc drafted from code and data."
        ctx["gaps"] = run.state.get("document", {}).get("gaps", [])
    elif stage == "gate_validate":
        pr = (m.meta or {}).get("parity_run_id")
        ctx["summary"] = f"Implementation: {(m.meta or {}).get('parity_verdict', '—')}."
        if pr:
            ctx["tokens"] = {n: metric_store.token(pr, n) for n in ("score_max_abs_diff", "coef_max_abs_diff", "decision_agreement",
                                                                   "fuzz_divergences", "rows_scored") if metric_store.get(pr, n)}
    elif stage in ("gate_deploy", "gate_accept"):
        ctx["summary"] = "Validation report drafted."
        ctx["report_id"] = f"rep_{run.id}"
        ctx["tokens"] = {n: metric_store.token(run.id, n) for n in ("findings.high", "findings.medium", "findings.total")
                         if metric_store.get(run.id, n)}
    return ctx


def _gate(run: Run, stage: str) -> bool:
    with session() as s:
        g = s.exec(select(Gate).where(Gate.run_id == run.id, Gate.stage == stage)).first()
    if g and g.status == "approved":
        return True
    if not g:
        g = save(Gate(run_id=run.id, model_id=run.model_id, stage=stage, title=GATE_TITLES[stage], context=_gate_context(run, stage)))
        ledger.append("orchestrator", "gate_requested", {"run_id": run.id, "model_id": run.model_id, "gate_id": g.id, "stage": stage})
        bus.publish("gate_requested", f"⏸ {run.model_id}: {GATE_TITLES[stage]}", run_id=run.id, model_id=run.model_id,
                    stage=stage, payload={"gate_id": g.id, "station": STATION[stage]})
    rec = ((g.context or {}).get("agent") or {}).get("recommendation", "promote")
    if run.options.get("auto_approve") and run.kind == "factory":  # demo delegate: approves every gate, holds included
        time.sleep(settings.demo_pace * 2)
        decide(g.id, "approved", "autopilot (demo delegate)", f"Agent said {rec}; demo delegate approves.", resume=False)
        return True
    if get_setting("auto_promote", False) and rec == "promote":
        time.sleep(settings.demo_pace * 2)
        decide(g.id, "approved", "auto-promote (agent recommendation)", "Agent recommended promote; auto-promote is on.", resume=False)
        return True
    _update(run.id, status="waiting_gate")
    if run.kind == "factory":
        _set_model(run.model_id, lifecycle={"stage": stage, "status": "awaiting", "run_id": run.id, "gate_id": g.id,
                                            "next": NEXT_OF_GATE.get(stage), "recommendation": rec})
    return False


def decide(gate_id: int, decision: str, by: str, comment: str, resume: bool = True) -> Gate:
    with session() as s:
        g = s.get(Gate, gate_id)
        if g.status != "pending":
            return g
        g.status = decision
        g.decision, g.decided_by, g.comment = decision, by, comment
        g.decided_at = datetime.now(timezone.utc)
        s.add(g)
        s.commit()
        s.refresh(g)
    ledger.append("human" if not by.startswith("auto") else "orchestrator", "gate_decided",
                  {"run_id": g.run_id, "model_id": g.model_id, "gate_id": g.id, "stage": g.stage, "decision": decision,
                   "by": by, "comment": comment})
    bus.publish("promotion" if decision == "approved" else "gate_decided",
                f"{'✓' if decision == 'approved' else '✗'} {g.model_id}: {g.title} — {decision} by {by}",
                run_id=g.run_id, model_id=g.model_id, stage=g.stage, payload={"gate_id": g.id, "decision": decision})
    if resume:
        with session() as s:
            run = s.get(Run, g.run_id)
        if decision == "approved":
            _update(run.id, status="running")
            start(run.id)
        elif decision == "changes_requested":
            stages = stages_for(run)
            prev = max(0, stages.index(g.stage) - 1)
            with session() as s:
                s.delete(s.get(Gate, g.id))
                s.commit()
            _update(run.id, state_next=prev, status="running")
            start(run.id)
        else:
            _update(run.id, status="rejected", ended_at=datetime.now(timezone.utc))
            if run.kind == "factory":
                _set_model(run.model_id, lifecycle={"stage": g.stage, "status": "rejected", "run_id": run.id})
            bus.publish("run_completed", f"{run.model_id} stopped at {g.stage} (rejected)", run_id=run.id, model_id=run.model_id)
    return g


def decide_many(gate_ids: list[int], decision: str, by: str, comment: str) -> list[dict]:
    out = []
    for gid in gate_ids:
        g = decide(gid, decision, by, comment)
        out.append({"gate_id": gid, "model_id": g.model_id, "status": g.status})
    ledger.append("human", "bulk_decision", {"gates": gate_ids, "decision": decision, "by": by, "count": len(gate_ids)})
    return out


# ------------------------------------------------------------------ stage functions
def _discover(ctx, run):
    return discovery.run(ctx)


def _document(ctx, run):
    return documentation.run(ctx)


def _redevelop(ctx, run):
    a = R.get(run.model_id)
    if a.strategy == "scorecard":
        return redevelopment.run(ctx)
    return redevelop_generic.run(ctx, a)


def _recent_rows(run: Run) -> pd.DataFrame | None:
    f = run.options.get("recent_file")
    return pd.read_csv(f, low_memory=False) if f else None


def _validate(ctx, run):
    a = R.get(run.model_id)
    with session() as s:
        m = s.get(Model, run.model_id)
    parity_run = (m.meta or {}).get("parity_run_id")
    if a.strategy == "scorecard":
        model_py = settings.runs_dir / parity_run / "model.py"
        if run.kind == "revalidation":
            rows = _recent_rows(run)
            rows["split"] = "oot"
            base = prepared()
            data = pd.concat([base[base["split"].isin(["train", "test"])], rows[[c for c in base.columns if c in rows]]], ignore_index=True)
            ctx.think(f"Re-validating on {len(rows)} recent live requests (outcomes matured in the simulator).")
            res = validator.run(ctx, model_py=model_py, data=data, factory_findings=False, label="revalidation")
            return {"findings": res["findings"]}
        data = prepared()
        res = validator.run(ctx, model_py=model_py, data=data)
        if set(ctx.choices.get("optional", [])) & {"slice_search", "stress_test"}:
            ctx2 = StageCtx(run, "validate", "redteam")
            ctx2.choices = ctx.choices
            ctx2.think("Red-team engaged for the analyses the validator chose: " + ", ".join(ctx.choices["optional"]))
            redteam.run(ctx2, model=res["model"], data=data, vctx=res["context"])
        return {"findings": res["findings"]}
    res = validate_generic.run(ctx, a, recent=_recent_rows(run) if run.kind == "revalidation" else None,
                               factory_findings=run.kind != "revalidation",
                               label="revalidation" if run.kind == "revalidation" else "validation")
    return res


def _report(ctx, run):
    a = R.get(run.model_id)
    with session() as s:
        m = s.get(Model, run.model_id)
    parity_run = (m.meta or {}).get("parity_run_id")
    reval = run.parent_run_id if run.kind == "revalidation" else None
    if a.strategy == "scorecard":
        rep = report_builder.build(ctx, parity_run_id=parity_run, revalidation_of=reval, drift_label=run.options.get("batch_label"))
    else:
        rep = report_generic.build(ctx, a, parity_run_id=parity_run, revalidation_of=reval, drift_label=run.options.get("batch_label"))
    if run.kind == "factory":
        _set_model(run.model_id, validated_run_id=run.id, status="validated")
    return {"report_id": rep.id, "checker_ok": rep.checker.get("ok"), "tokens": rep.checker.get("token_count")}


def _monitor_setup(ctx, run):
    from app.modelkit.traffic import sim
    if run.model_id == "CR-001":
        monitor.setup(ctx)
    cfg = ctx.tool("deploy", f"load the certified Python {run.model_id} as a live endpoint and start traffic",
                   lambda: sim.deploy(run.model_id), result_summary=lambda c: f"live · {c['rpm']} requests/min",
                   args={"endpoint": f"/score/{run.model_id}", "window_s": 10, "outcome_delay_s": 40})
    ctx.tool("alert_rules", "arm PSI, CSI, latency, no-decision and actual-vs-expected rules",
             lambda: __import__("app.modelkit.traffic", fromlist=["RULES"]).RULES, result_summary=lambda r: f"{len(r)} rules armed")
    _set_model(run.model_id, status="monitored")
    ledger.append("monitor", "model_deployed", {"run_id": run.id, "model_id": run.model_id, "rpm": cfg["rpm"]})
    return {"deployed": True, "rpm": cfg["rpm"]}


STAGE_FNS = {"discover": _discover, "document": _document, "redevelop": _redevelop, "validate": _validate,
             "report": _report, "monitor_setup": _monitor_setup}


def recover_interrupted() -> None:
    """On startup: runs that were mid-stage when the process stopped restart from their last checkpoint."""
    with session() as s:
        for r in s.exec(select(Run).where(Run.status.in_(["running", "queued"]))).all():
            start(r.id)


# kept for the legacy CR-001 drift button
def inject_drift(model_id: str, severity: float, feature_set: str, auto_approve: bool = True) -> dict:
    from app.modelkit.traffic import sim
    if model_id in sim.models:
        sim.set_scenario(model_id, feature_set, severity, 30)
        return {"batch": {"psi": 0, "status": "ramping"}, "revalidation_run_id": None, "mode": "live traffic"}
    b = monitor.inject(model_id, severity, feature_set)
    return {"batch": b.model_dump(), "revalidation_run_id": None}
