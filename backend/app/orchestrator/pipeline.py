"""Factory orchestrator: per-model stage plans with a human promotion gate between every stage.

  intake ─▶[approve spec]▶ document+plan ─▶[approve doc & plans]▶ redevelop ─▶[approve certificate]▶
  validate → report ─▶[approve validation · deploy]▶ monitor (live traffic)
  live red alert ─▶ re-validation run: diagnose → validate → report ─▶[accept]

Approving a gate also approves what the stage produced (spec, plans) — that approved version is what later stages
use. "Request changes" re-runs the previous stage and hands the reviewer's comment to its agent. State lives in the
DB (runs.state checkpoint: next stage, timeline, conclusions), so a restart resumes every run where it stopped.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlmodel import select

from app import repositories as repo
from app.agents import documentation, intake, monitor, redevelopment, reporter, validator
from app.agents.common import StageCtx
from app.core.config import settings
from app.core.db import save, session
from app.core.events import bus
from app.domain.tables import AppSetting, Gate, Run
from app.evidence import ledger, metric_store
from app.services import plans, specs

log = logging.getLogger("mrf.pipeline")

FULL = ["discover", "gate_document", "document", "gate_redevelop", "redevelop", "gate_validate", "validate", "report",
        "gate_deploy", "monitor_setup"]
NO_DEPLOY = FULL[:8] + ["gate_deploy"]
REVAL = ["diagnose", "validate", "report", "gate_accept"]
STATION = {"queued": "discover", "discover": "discover", "gate_document": "discover", "document": "document",
           "gate_redevelop": "document", "redevelop": "redevelop", "gate_validate": "redevelop", "validate": "validate",
           "report": "validate", "gate_deploy": "validate", "monitor_setup": "monitor", "diagnose": "monitor",
           "gate_accept": "validate"}
AGENT = {"discover": "intake", "document": "documentation", "redevelop": "redevelopment", "validate": "validator",
         "report": "report", "monitor_setup": "monitor", "diagnose": "monitor"}
GATE_TITLES = {"gate_document": "Approve spec · promote to Document",
               "gate_redevelop": "Approve documentation & plans · promote to Redevelop",
               "gate_validate": "Approve parity certificate · promote to Validate",
               "gate_deploy": "Approve validation · deploy to Monitor",
               "gate_accept": "Accept re-validation"}
NEXT_OF_GATE = {"gate_document": "document", "gate_redevelop": "redevelop", "gate_validate": "validate",
                "gate_deploy": "monitor", "gate_accept": "monitor"}

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="factory")
_lock = threading.Lock()
GEN = {"n": 0, "active": 0}  # a reset bumps the generation; stale workers stop at the next stage boundary


class Stale(Exception):
    pass


class GateBlocked(ValueError):
    pass


class Retry(Exception):
    """A gate sent the run back: continue from the checkpoint it set."""


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
def _deployable(model_id: str) -> bool:
    m = repo.models.get(model_id)
    meta = (m.meta or {}) if m else {}
    if "deployable" in meta:
        return bool(meta["deployable"])
    s = specs.current_or_none(model_id)
    return bool(s.deployable) if s else True


def stages_for(run: Run) -> list[str]:
    if run.options.get("stages"):
        return run.options["stages"]
    if run.kind == "revalidation":
        return REVAL
    return FULL if _deployable(run.model_id) else NO_DEPLOY


def create_run(model_id: str, *, kind: str = "factory", auto_approve: bool = False, parent: str | None = None,
               extra: dict | None = None) -> Run:
    rid = "run_" + uuid.uuid4().hex[:6]
    r = Run(id=rid, model_id=model_id, kind=kind, parent_run_id=parent, status="queued", stage="queued",
            options={"auto_approve": auto_approve, **(extra or {})}, state={"next": 0, "timeline": [], "conclusions": {}})
    save(r)
    ledger.append("orchestrator", "run_created", {"run_id": rid, "model_id": model_id, "kind": kind, "parent": parent})
    log.info("run created %s model=%s kind=%s", rid, model_id, kind)
    return r


def start(run_id: str, delay: float = 0.0) -> None:
    _pool.submit(_advance_safe, run_id, delay)


def start_portfolio(model_ids: list[str] | None, auto_approve: bool) -> list[Run]:
    with session() as s:
        active = {r.model_id for r in s.exec(select(Run).where(Run.kind == "factory",
                                                               Run.status.in_(["queued", "running", "waiting_gate"]))).all()}
    ids = [i for i in (model_ids or [m.id for m in repo.models.list()]) if i not in active]
    runs = [create_run(i, auto_approve=auto_approve) for i in ids]
    if runs:
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
        log.error("run %s failed: %s\n%s", run_id, e, traceback.format_exc())
        r = _update(run_id, status="failed", ended_at=datetime.now(timezone.utc), state_error=f"{type(e).__name__}: {e}")
        bus.publish("alert", f"✗ {r.model_id} {r.stage} failed: {e}", run_id=run_id, model_id=r.model_id, stage=r.stage)
        ledger.append("orchestrator", "run_failed", {"run_id": run_id, "model_id": r.model_id, "error": str(e)[:300]})
        _set_model(r.model_id, lifecycle={"stage": r.stage, "status": "failed", "run_id": run_id, "error": str(e)[:300]})
    finally:
        GEN["active"] -= 1


def _set_model(model_id: str, **meta) -> None:
    m = repo.models.get(model_id)
    if m:
        repo.models.update(model_id, meta={**(m.meta or {}), **meta})


STAGE_FNS = {"discover": intake.run, "document": documentation.run, "redevelop": redevelopment.run,
             "validate": validator.run, "report": reporter.run, "monitor_setup": monitor.setup, "diagnose": monitor.diagnose}


def _advance(run_id: str, gen: int = 0) -> None:
    with session() as s:
        run = s.get(Run, run_id)
    if run is None:
        return
    if run.status == "queued":
        run = _update(run_id, status="running", started_at=datetime.now(timezone.utc))
        bus.publish("run_started", f"{run.model_id} entered the factory ({run.kind})", run_id=run_id, model_id=run.model_id,
                    payload={"stages": stages_for(run), "kind": run.kind})
    i = run.state.get("next", 0)
    while i < len(stages_for(run)):
        if gen != GEN["n"]:
            raise Stale()
        stage = stages_for(run)[i]
        run = _update(run_id, stage=stage, status="running")
        if run.kind == "factory":
            _set_model(run.model_id, lifecycle={"stage": stage, "status": "running", "run_id": run_id})
        if stage.startswith("gate_"):
            try:
                if not _gate(run, stage):
                    return
            except Retry:
                with session() as sess:
                    run = sess.get(Run, run_id)
                i = run.state.get("next", 0)
                continue
            i += 1
            run = _update(run_id, state_next=i)
            continue
        tl = list(run.state.get("timeline", []))
        tl.append({"stage": stage, "station": STATION[stage], "start": _now()})
        run = _update(run_id, state_timeline=tl)
        agent = AGENT.get(stage, "orchestrator")
        bus.publish("stage_started", f"{run.model_id} → {stage}", run_id=run_id, model_id=run.model_id, stage=stage,
                    agent=agent, payload={"station": STATION[stage]})
        ledger.append(agent, "stage_started", {"run_id": run_id, "model_id": run.model_id, "stage": stage})
        log.info("stage start %s %s %s", run.model_id, run_id, stage)
        ctx = StageCtx(run, stage, agent)
        result = STAGE_FNS[stage](ctx) or {}
        conclusion = result.pop("conclusion", {"summary": "", "recommendation": "promote", "reasons": []})
        with session() as s:
            run = s.get(Run, run_id)
        tl = list(run.state.get("timeline", []))
        tl[-1]["end"] = _now()
        concl = {**run.state.get("conclusions", {}), stage: conclusion}
        run = _update(run_id, state_timeline=tl, state_conclusions=concl, **{f"state_{stage}": _summary(result)})
        bus.publish("stage_completed", f"{run.model_id} ✓ {stage} · agent recommends {conclusion['recommendation'].upper()}",
                    run_id=run_id, model_id=run.model_id, stage=stage, agent=agent, payload={"station": STATION[stage]})
        ledger.append(agent, "stage_completed", {"run_id": run_id, "model_id": run.model_id, "stage": stage,
                                                 "recommendation": conclusion["recommendation"]})
        log.info("stage done %s %s %s → %s", run.model_id, run_id, stage, conclusion["recommendation"])
        i += 1
        run = _update(run_id, state_next=i)
    _complete(run_id)


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
        _set_model(run.model_id, lifecycle={"stage": stages_for(run)[-1], "status": "done", "run_id": run_id})
    bus.publish("run_completed", f"{run.model_id} completed ({run.kind}) in {rt:.0f}s", run_id=run_id, model_id=run.model_id,
                payload={"runtime_s": rt, "kind": run.kind})
    ledger.append("orchestrator", "run_completed", {"run_id": run_id, "model_id": run.model_id, "runtime_s": round(rt, 2)})


def _summary(result) -> dict:
    if not isinstance(result, dict):
        return {}
    return {k: v for k, v in result.items() if isinstance(v, (str, int, float, bool, list, dict)) and k != "model"}


# ------------------------------------------------------------------ gates
def _gate_context(run: Run, stage: str) -> dict:
    stages = stages_for(run)
    prev = stages[stages.index(stage) - 1] if stages.index(stage) > 0 else None
    concl = run.state.get("conclusions", {}).get(prev) if prev else None
    ctx: dict = {"completed": prev, "next": NEXT_OF_GATE.get(stage), "agent": concl}
    m = repo.models.get(run.model_id)
    meta = m.meta or {}
    if stage == "gate_document":
        row = repo.specs.latest(run.model_id)
        if row:
            sp = specs.parse(row.body)
            ctx.update(summary=f"{sp.model_type or sp.task} · Tier {sp.tier} · strategy {sp.strategy}. {sp.tier_rationale}",
                       spec_version=row.version, review=row.note, link=f"/models/{run.model_id}?tab=spec")
    elif stage == "gate_redevelop":
        doc = run.state.get("document", {})
        vp, mp = repo.plans.latest(run.model_id, "validation"), repo.plans.latest(run.model_id, "monitoring")
        ctx.update(summary=f"Documentation drafted · validation plan v{vp.version if vp else '—'} "
                           f"({len(vp.body.get('checks', [])) if vp else 0} checks) · monitoring plan v{mp.version if mp else '—'}",
                   gaps=doc.get("gaps", [])[:6], link=f"/models/{run.model_id}?tab=validation")
    elif stage == "gate_validate":
        pr = meta.get("parity_run_id")
        ctx.update(summary=f"Implementation: {meta.get('parity_verdict', '—')}", link=f"/models/{run.model_id}?tab=parity")
        if pr:
            ctx["tokens"] = {n: metric_store.token(pr, n) for n in ("score_max_abs_diff", "coef_max_abs_diff", "decision_agreement",
                                                                   "rows_compared") if metric_store.get(pr, n)}
    elif stage in ("gate_deploy", "gate_accept"):
        v = run.state.get("validate", {})
        ctx.update(summary=f"{v.get('rating', 'Validation report drafted')}", report_id=f"rep_{run.id}",
                   tokens={n: metric_store.token(run.id, n) for n in ("checks.pass", "checks.amber", "checks.red", "findings.high",
                                                                      "findings.total") if metric_store.get(run.id, n)},
                   link=f"/reports/rep_{run.id}")
        if stage == "gate_deploy" and not _deployable(run.model_id):
            ctx["summary"] += " · not deployable (rehosted / not used live): approving closes the run"
    fb = run.state.get("feedback", {})
    if fb:
        ctx["feedback"] = fb
    blocked = _blockers(run, stage, prev, concl)
    if blocked:
        ctx["blocked"] = blocked
    return ctx


def _blockers(run: Run, stage: str, prev: str | None, concl: dict | None) -> list[str]:
    """Hard reasons a gate cannot be approved: the stage did not produce what the next stage needs."""
    out = [f"required step not completed: {t}" for t in ((concl or {}).get("incomplete") or [])]
    meta = (repo.models.get(run.model_id).meta or {})
    if stage == "gate_document" and not repo.specs.latest(run.model_id):
        out.append("no specification was drafted")
    if stage == "gate_redevelop":
        for k in ("validation", "monitoring"):
            if not repo.plans.latest(run.model_id, k):
                out.append(f"no {k} plan was drafted")
    if stage == "gate_validate" and meta.get("parity_run_id") != run.id:
        out.append("no parity certificate was issued in this run")
    if stage in ("gate_deploy", "gate_accept"):
        from app.domain.tables import Report
        with session() as s:
            rep = s.get(Report, f"rep_{run.id}")
        if rep is None:
            out.append("no validation report was written")
    return list(dict.fromkeys(out))


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
    blocked = (g.context or {}).get("blocked")
    auto = (run.options.get("auto_approve") and run.kind == "factory") or (get_setting("auto_promote", False) and rec == "promote")
    if blocked and auto:  # a delegate never approves an incomplete stage: send it back once, then stop
        tries = (run.state.get("auto_retries") or {}).get(stage, 0)
        if tries < 1:
            _update(run.id, state_auto_retries={**(run.state.get("auto_retries") or {}), stage: tries + 1})
            decide(g.id, "changes_requested", "auto-delegate", "Stage incomplete: " + "; ".join(blocked), resume=False)
            with session() as sess:  # like a human send-back: the gate is asked again after the re-run
                sess.delete(sess.get(Gate, g.id))
                sess.commit()
            prev_i = max(0, stages_for(run).index(stage) - 1)
            fb = {**run.state.get("feedback", {}), stages_for(run)[prev_i]: "Previous attempt was incomplete: " + "; ".join(blocked)}
            _update(run.id, state_next=prev_i, state_feedback=fb)
            raise Retry()
        _update(run.id, status="failed", ended_at=datetime.now(timezone.utc), state_error="blocked: " + "; ".join(blocked))
        _set_model(run.model_id, lifecycle={"stage": stage, "status": "failed", "run_id": run.id, "error": "blocked: " + "; ".join(blocked)})
        bus.publish("alert", f"✗ {run.model_id}: stopped at {GATE_TITLES[stage]} — " + "; ".join(blocked), run_id=run.id, model_id=run.model_id)
        return False
    if blocked:
        pass  # wait for a human: they can only send it back or reject (see decide)
    elif run.options.get("auto_approve") and run.kind == "factory":  # demo delegate: approves every gate, holds included
        time.sleep(settings.demo_pace * 2)
        decide(g.id, "approved", "autopilot (demo delegate)", f"Agent said {rec}; demo delegate approves.", resume=False)
        return True
    elif get_setting("auto_promote", False) and rec == "promote":
        time.sleep(settings.demo_pace * 2)
        decide(g.id, "approved", "auto-promote (agent recommendation)", "Agent recommended promote; auto-promote is on.", resume=False)
        return True
    _update(run.id, status="waiting_gate")
    if run.kind == "factory":
        _set_model(run.model_id, lifecycle={"stage": stage, "status": "awaiting", "run_id": run.id, "gate_id": g.id,
                                            "next": NEXT_OF_GATE.get(stage), "recommendation": rec})
    return False


def _on_approved(g: Gate, by: str) -> None:
    """What approving a gate commits: the spec, the plans, the validation."""
    if g.stage == "gate_document":
        specs.approve(g.model_id, by)
    elif g.stage == "gate_redevelop":
        plans.approve(g.model_id, "validation", by)
        plans.approve(g.model_id, "monitoring", by)
    elif g.stage == "gate_deploy":
        _set_model(g.model_id, validated_run_id=g.run_id, status="validated")


def decide(gate_id: int, decision: str, by: str, comment: str, resume: bool = True) -> Gate:
    with session() as s:
        g = s.get(Gate, gate_id)
        if g.status != "pending":
            return g
        if decision == "approved" and (g.context or {}).get("blocked"):
            raise GateBlocked("cannot approve: " + "; ".join(g.context["blocked"]) + " — send it back to the agent or reject")
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
    log.info("gate %s %s %s by %s", g.id, g.stage, decision, by)
    if decision == "approved":
        _on_approved(g, by)
    if not resume:
        return g
    with session() as s:
        run = s.get(Run, g.run_id)
    if decision == "approved":
        _update(run.id, status="running")
        start(run.id)
    elif decision == "changes_requested":
        stages = stages_for(run)
        prev = max(0, stages.index(g.stage) - 1)
        fb = {**run.state.get("feedback", {}), stages[prev]: comment or "The reviewer requested changes."}
        with session() as s:
            s.delete(s.get(Gate, g.id))
            s.commit()
        _update(run.id, state_next=prev, state_feedback=fb, status="running")
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
        try:
            g = decide(gid, decision, by, comment)
            out.append({"gate_id": gid, "model_id": g.model_id, "status": g.status})
        except GateBlocked as e:  # an incomplete stage is skipped, not approved; the rest still go through
            out.append({"gate_id": gid, "status": "blocked", "error": str(e)})
    ledger.append("human", "bulk_decision", {"gates": gate_ids, "decision": decision, "by": by, "count": len(gate_ids)})
    return out


def recover_interrupted() -> None:
    """On startup: runs that were mid-stage when the process stopped restart from their last checkpoint."""
    with session() as s:
        for r in s.exec(select(Run).where(Run.status.in_(["running", "queued"]))).all():
            start(r.id)
