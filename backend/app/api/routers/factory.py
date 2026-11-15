"""The factory floor: pipeline board, runs, gates (single + bulk), settings, agent traces, live events, overview."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import func, select

from app import repositories as repo
from app.api.common import iso, not_found, row_json, run_json


def _finite(o):
    from app.main import _finite as f
    return f(o)
from app.core.config import settings
from app.core.db import session
from app.core.events import bus
from app.domain.tables import AgentStep, Artifact, Finding, Gate, LLMCall, Run
from app.evidence import ledger
from app.orchestrator import pipeline, services

router = APIRouter(prefix="/api", tags=["factory"])


class RunRequest(BaseModel):
    model_ids: list[str] | None = None
    auto_approve: bool = False


class Decision(BaseModel):
    decision: str
    comment: str = ""
    decided_by: str = "Model Risk Officer"


class BulkDecision(Decision):
    gate_ids: list[int]


class SettingReq(BaseModel):
    value: bool | float | str | None


@router.post("/runs")
def start_runs(req: RunRequest):
    return {"runs": [run_json(r) for r in pipeline.start_portfolio(req.model_ids, req.auto_approve)]}


@router.post("/models/{model_id}/start")
def start_model(model_id: str):
    if not repo.models.get(model_id):
        raise not_found("model")
    runs = pipeline.start_portfolio([model_id], False)
    if not runs:
        raise HTTPException(409, f"{model_id} already has an active run")
    return {"runs": [run_json(r) for r in runs]}


@router.get("/runs")
def list_runs(model_id: str | None = None, limit: int = 100):
    with session() as s:
        q = select(Run).order_by(Run.started_at.desc()).limit(limit)
        if model_id:
            q = q.where(Run.model_id == model_id)
        return [run_json(r) for r in s.exec(q).all()]


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    with session() as s:
        r = s.get(Run, run_id)
        if not r:
            raise not_found("run")
        arts = s.exec(select(Artifact).where(Artifact.run_id == run_id)).all()
        gates = s.exec(select(Gate).where(Gate.run_id == run_id)).all()
    return {"run": run_json(r), "artifacts": [row_json(a) for a in arts], "gates": [row_json(g) for g in gates]}


@router.get("/pipeline")
def pipeline_board():
    """One card per model: lifecycle stage, status, pending gate, agent recommendation, knowledge versions."""
    with session() as s:
        gates = {g.model_id: g for g in s.exec(select(Gate).where(Gate.status == "pending")).all()}
        runs = s.exec(select(Run).order_by(Run.started_at.desc())).all()
    latest: dict = {}
    for r in runs:
        latest.setdefault((r.model_id, r.kind), r)
    from app.engine.traffic import sim
    cards = []
    for m in repo.models.list():
        meta = m.meta or {}
        lc = meta.get("lifecycle", {})
        g = gates.get(m.id)
        run, reval = latest.get((m.id, "factory")), latest.get((m.id, "revalidation"))
        sp = repo.specs.current(m.id)
        stage = lc.get("stage", "onboarded")
        cards.append({
            "id": m.id, "name": m.name, "tier": m.tier, "type": m.type, "status": m.status, "owner": m.owner,
            "stage": stage, "station": pipeline.STATION.get(stage, "discover"), "state": lc.get("status", "idle"),
            "next": lc.get("next"), "recommendation": lc.get("recommendation"),
            "gate": {"id": g.id, "title": g.title, "stage": g.stage, "context": g.context} if g else None,
            "run": run_json(run) if run else None, "revalidation": run_json(reval) if reval else None,
            "strategy": meta.get("strategy") or (sp.body.get("strategy") if sp else None), "deployable": meta.get("deployable"),
            "deployed": m.id in sim.models, "parity": meta.get("parity_verdict"), "error": lc.get("error"),
            "spec_version": sp.version if sp else None, "task": sp.body.get("task") if sp else None})
    return {"cards": cards, "auto_promote": pipeline.get_setting("auto_promote", False)}


@router.get("/gates")
def list_gates(status: str | None = None, model_id: str | None = None):
    with session() as s:
        q = select(Gate).order_by(Gate.requested_at.desc())
        if status:
            q = q.where(Gate.status == status)
        if model_id:
            q = q.where(Gate.model_id == model_id)
        return [row_json(g) for g in s.exec(q).all()]


def _check(decision: str):
    if decision not in ("approved", "rejected", "changes_requested"):
        raise HTTPException(400, "decision must be approved | rejected | changes_requested")


@router.post("/gates/{gate_id}/decision")
def gate_decision(gate_id: int, d: Decision):
    _check(d.decision)
    with session() as s:
        if not s.get(Gate, gate_id):
            raise not_found("gate")
    try:
        return row_json(pipeline.decide(gate_id, d.decision, d.decided_by, d.comment))
    except pipeline.GateBlocked as e:
        raise HTTPException(409, str(e))


@router.post("/gates/bulk-decision")
def bulk_decision(d: BulkDecision):
    _check(d.decision)
    try:
        return {"results": pipeline.decide_many(d.gate_ids, d.decision, d.decided_by, d.comment)}
    except pipeline.GateBlocked as e:
        raise HTTPException(409, str(e))


@router.get("/settings")
def get_settings():
    return {"auto_promote": pipeline.get_setting("auto_promote", False),
            "llm": {"provider": settings.llm_provider, "model": settings.llm_model, "fast_model": settings.llm_fast_model,
                    "mode": settings.llm_mode}, "demo_pace": settings.demo_pace}


@router.post("/settings/{key}")
def put_setting(key: str, req: SettingReq):
    if key not in ("auto_promote",):
        raise HTTPException(400, "unknown setting")
    pipeline.set_setting(key, req.value)
    ledger.append("human", "setting_changed", {"key": key, "value": req.value})
    if key == "auto_promote" and req.value:  # apply to gates already waiting where the agent recommends promote
        with session() as s:
            pend = s.exec(select(Gate).where(Gate.status == "pending")).all()
        ok = [g.id for g in pend if ((g.context or {}).get("agent") or {}).get("recommendation", "promote") == "promote"]
        if ok:
            pipeline.decide_many(ok, "approved", "auto-promote (agent recommendation)", "Auto-promote switched on.")
    return {"ok": True}


# ------------------------------------------------------------------ agent traces
@router.get("/agents/runs")
def agent_runs(model_id: str | None = None):
    with session() as s:
        q = select(Run).order_by(Run.started_at.desc()).limit(80)
        if model_id:
            q = q.where(Run.model_id == model_id)
        runs = s.exec(q).all()
        counts = dict(s.exec(select(AgentStep.run_id, func.count()).group_by(AgentStep.run_id)).all())
        costs = dict(s.exec(select(LLMCall.run_id, func.sum(LLMCall.cost)).group_by(LLMCall.run_id)).all())
        calls = dict(s.exec(select(LLMCall.run_id, func.count()).group_by(LLMCall.run_id)).all())
    return [{**run_json(r), "steps": counts.get(r.id, 0), "llm_cost": round(costs.get(r.id) or 0, 5), "llm_calls": calls.get(r.id, 0)}
            for r in runs]


@router.get("/agents/steps")
def agent_steps(run_id: str, after: int = 0):
    with session() as s:
        rows = s.exec(select(AgentStep).where(AgentStep.run_id == run_id, AgentStep.id > after).order_by(AgentStep.id).limit(1000)).all()
    return [{**r.model_dump(), "ts": iso(r.ts)} for r in rows]


@router.get("/agents/llm-calls")
def llm_calls(run_id: str):
    with session() as s:
        rows = s.exec(select(LLMCall).where(LLMCall.run_id == run_id).order_by(LLMCall.id)).all()
    return [row_json(r) for r in rows]


# ------------------------------------------------------------------ live events (SSE)
async def _sse(request: Request, run_id: str | None, replay: int):
    q = bus.subscribe()
    try:
        for e in ([e for e in bus.recent(replay) if not run_id or e["run_id"] == run_id] if replay else []):
            yield f"id: {e['id']}\nevent: message\ndata: {json.dumps(_finite(e))}\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                e = await asyncio.wait_for(q.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if run_id and e["run_id"] != run_id:
                continue
            yield f"id: {e['id']}\nevent: message\ndata: {json.dumps(_finite(e))}\n\n"
    finally:
        bus.unsubscribe(q)


@router.get("/events")
async def events(request: Request, replay: int = 150):
    return StreamingResponse(_sse(request, None, replay), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/events/recent")
def recent_events(n: int = 200):
    return bus.recent(n)


@router.get("/overview")
def overview():
    from app.engine.traffic import sim
    with session() as s:
        runs = s.exec(select(Run).order_by(Run.started_at)).all()
        gates_open = s.exec(select(func.count()).select_from(Gate).where(Gate.status == "pending")).one()
        cost = s.exec(select(func.sum(LLMCall.cost))).one() or 0.0
        n_calls = s.exec(select(func.count()).select_from(LLMCall)).one()
        n_find = s.exec(select(func.count()).select_from(Finding)).one()
        n_high = s.exec(select(func.count()).select_from(Finding).where(Finding.severity == "high")).one()
        n_steps = s.exec(select(func.count()).select_from(AgentStep)).one()
    models = repo.models.list()
    factory = [r for r in runs if r.kind == "factory"]
    clock = None
    if factory:
        t0 = min(r.started_at for r in factory)
        ends = [r.ended_at for r in factory if r.ended_at]
        active = any(r.status in ("running", "queued", "waiting_gate") for r in factory)
        t1 = datetime.now(timezone.utc) if active or not ends else max(ends).replace(tzinfo=timezone.utc)
        clock = {"started_at": iso(t0), "elapsed_s": (t1 - t0.replace(tzinfo=timezone.utc)).total_seconds(), "active": active}
    verdicts = [(m.meta or {}).get("parity_verdict") for m in models]
    return {"models": len(models), "clock": clock, "autopilot": services.autopilot_state(),
            "kpis": {"models_total": len(models), "models_validated": sum(1 for m in models if (m.meta or {}).get("validated_run_id")),
                     "parity_pass": sum(v == "PASS" for v in verdicts), "rehosted": sum(v == "REHOSTED" for v in verdicts),
                     "live": len(sim.models), "gates_open": gates_open, "findings": n_find, "findings_high": n_high,
                     "agent_steps": n_steps, "llm_cost_usd": round(cost, 4), "llm_calls": n_calls,
                     "runs_active": sum(r.status in ("running", "queued") for r in runs),
                     "llm": f"{settings.llm_provider}:{settings.llm_model}"}}
