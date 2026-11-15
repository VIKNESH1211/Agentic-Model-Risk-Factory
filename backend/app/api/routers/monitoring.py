"""Live monitoring: deployed endpoints, plan-driven KPI windows, alerts, drift scenarios, traffic controls."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from app.api.common import iso, run_json
from app.core.db import session
from app.core.events import bus
from app.domain.tables import MonitorAlert, Run
from app.engine.traffic import sim, windows

router = APIRouter(prefix="/api/traffic", tags=["monitoring"])


class ScenarioReq(BaseModel):
    scenario: str | None = None
    severity: float = 0.6
    ramp_s: int = 60


class RateReq(BaseModel):
    rpm: float | None = None
    enabled: bool | None = None


def _live(model_id: str):
    if model_id not in sim.models:
        raise HTTPException(409, f"{model_id} is not deployed")
    return sim.models[model_id]


@router.get("")
def overview():
    out = []
    for mid, mt in list(sim.models.items()):
        w = windows(mid, 30)
        out.append({"model_id": mid, "name": mt.spec.name, "task": mt.spec.task, "cfg": mt.cfg, "severity_now": round(mt.severity(), 3),
                    "total": mt.total, "latest": w[-1] if w else None, "spark": [x.get("score_psi") for x in w],
                    "statuses": [x.get("status") for x in w], "health": mt.health(),
                    "active_alerts": mt.active, "panels": [p.model_dump() for p in mt.plan.panels][:2]})
    return out


@router.get("/{model_id}")
def state(model_id: str, n: int = 90):
    st = sim.state(model_id)
    with session() as s:
        alerts = s.exec(select(MonitorAlert).where(MonitorAlert.model_id == model_id).order_by(MonitorAlert.id.desc()).limit(40)).all()
        revals = s.exec(select(Run).where(Run.model_id == model_id, Run.kind == "revalidation").order_by(Run.started_at.desc()).limit(10)).all()
    return {**st, "windows": windows(model_id, n), "alerts": [{**a.model_dump(), "ts": iso(a.ts)} for a in alerts],
            "revalidations": [run_json(r) for r in revals]}


@router.post("/{model_id}/scenario")
def scenario(model_id: str, req: ScenarioReq):
    mt = _live(model_id)
    if req.scenario and req.scenario not in {s.id for s in mt.plan.scenarios}:
        raise HTTPException(400, f"unknown scenario (plan has: {[s.id for s in mt.plan.scenarios]})")
    sim.set_scenario(model_id, req.scenario, req.severity, req.ramp_s)
    bus.publish("traffic", f"{model_id}: scenario {req.scenario or 'heal'} → severity {req.severity if req.scenario else 0} over {req.ramp_s}s",
                model_id=model_id, agent="human")
    return sim.state(model_id)


@router.post("/{model_id}/rate")
def rate(model_id: str, req: RateReq):
    _live(model_id)
    sim.set(model_id, **{k: v for k, v in req.model_dump().items() if v is not None})
    return sim.state(model_id)


@router.post("/{model_id}/undeploy")
def undeploy(model_id: str):
    _live(model_id)
    sim.undeploy(model_id)
    bus.publish("traffic", f"{model_id} taken out of service", model_id=model_id, agent="human")
    return {"ok": True}


@router.post("/{model_id}/deploy")
def deploy(model_id: str):
    try:
        cfg = sim.deploy(model_id)
    except Exception as e:
        raise HTTPException(409, str(e))
    bus.publish("traffic", f"{model_id} back in service at {cfg['rpm']} req/min", model_id=model_id, agent="human")
    return sim.state(model_id)
