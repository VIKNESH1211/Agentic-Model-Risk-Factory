"""Model knowledge as data: specifications and validation / monitoring plans (versioned CRUD + approve + diff)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import repositories as repo
from app.agents.documentation import frame_estimate
from app.agents.intake import model_probe, probe_columns
from app.api.common import not_found, row_json
from app.domain.schemas import ModelSpec, MonitoringPlan, ValidationPlan
from app.engine import catalog
from app.services import plans, specs

router = APIRouter(prefix="/api/models/{model_id}", tags=["knowledge"])


class Draft(BaseModel):
    body: dict
    note: str = ""
    author: str = "Model Risk Officer"


class Approve(BaseModel):
    by: str = "Model Risk Officer"


def _model(model_id: str):
    m = repo.models.get(model_id)
    if not m:
        raise not_found("model")
    return m


def _diff(a: dict, b: dict, prefix: str = "") -> list[dict]:
    out = []
    for k in sorted(set(a) | set(b)):
        p = f"{prefix}{k}"
        va, vb = a.get(k), b.get(k)
        if isinstance(va, dict) and isinstance(vb, dict):
            out += _diff(va, vb, p + ".")
        elif va != vb:
            out.append({"field": p, "before": va, "after": vb})
    return out


# ------------------------------------------------------------------ specs
@router.get("/spec")
def get_spec(model_id: str):
    _model(model_id)
    rows = repo.specs.versions(model_id)
    cur = repo.specs.current(model_id)
    return {"current": row_json(cur) if cur else None, "versions": [row_json(r) for r in rows],
            "schema": ModelSpec.model_json_schema(), "probe": model_probe(model_id)}


@router.put("/spec")
def put_spec(model_id: str, d: Draft):
    _model(model_id)
    try:
        sp = specs.parse(d.body)
    except specs.SpecError as e:
        raise HTTPException(422, str(e))
    probe = model_probe(model_id)
    errs = specs.lint(model_id, sp, probe_columns(probe) if probe else None, probe.get("objects") if probe else None)
    if errs:
        raise HTTPException(422, {"lint": errs})
    return row_json(specs.save_draft(model_id, sp, f"human:{d.author}", d.note))


@router.post("/spec/approve")
def approve_spec(model_id: str, a: Approve):
    _model(model_id)
    row = specs.approve(model_id, a.by)
    if not row:
        raise HTTPException(409, "no spec to approve")
    return row_json(row)


@router.get("/spec/diff")
def spec_diff(model_id: str, a: int, b: int):
    va = next((r for r in repo.specs.versions(model_id) if r.version == a), None)
    vb = next((r for r in repo.specs.versions(model_id) if r.version == b), None)
    if not va or not vb:
        raise not_found("spec version")
    return {"a": a, "b": b, "changes": _diff(va.body, vb.body)}


@router.get("/contract")
def get_contract(model_id: str):
    cur = repo.specs.current(model_id)
    if not cur:
        raise not_found("spec")
    return {"version": cur.version, "status": cur.status, "contract": cur.contract,
            "epilogue": ((repo.models.get(model_id).meta or {}).get("export_epilogue") or {}).get("code")}


# ------------------------------------------------------------------ plans
@router.get("/plans/{kind}")
def get_plan(model_id: str, kind: str):
    if kind not in plans.KINDS:
        raise HTTPException(400, "kind must be validation or monitoring")
    _model(model_id)
    cur = repo.plans.current(model_id, kind)
    sp = specs.current_or_none(model_id)
    cols = sorted(catalog.scored_columns(sp, frame_estimate(model_id, sp))) if sp else []
    return {"current": row_json(cur) if cur else None, "versions": [row_json(r) for r in repo.plans.versions(model_id, kind)],
            "schema": plans.KINDS[kind].model_json_schema(), "columns": cols,
            "catalog": catalog.describe() if kind == "validation" else catalog.KPI_CATALOG}


@router.put("/plans/{kind}")
def put_plan(model_id: str, kind: str, d: Draft):
    if kind not in plans.KINDS:
        raise HTTPException(400, "kind must be validation or monitoring")
    _model(model_id)
    try:
        plan = plans.parse(kind, d.body)
    except plans.PlanError as e:
        raise HTTPException(422, str(e))
    sp = specs.current_or_none(model_id)
    if sp:
        errs = (catalog.lint_validation(plan, sp, catalog.scored_columns(sp, frame_estimate(model_id, sp))) if kind == "validation"
                else catalog.lint_monitoring(plan, set(frame_estimate(model_id, sp))))
        if errs:
            raise HTTPException(422, {"lint": errs})
    row = plans.save_draft(model_id, kind, plan.model_dump(), f"human:{d.author}", d.note)
    if kind == "monitoring":
        from app.engine.traffic import sim
        if model_id in sim.models and row.status == "approved":
            sim.reload_plan(model_id)
    return row_json(row)


@router.post("/plans/{kind}/approve")
def approve_plan(model_id: str, kind: str, a: Approve):
    _model(model_id)
    row = plans.approve(model_id, kind, a.by)
    if not row:
        raise HTTPException(409, "no plan to approve")
    if kind == "monitoring":
        from app.engine.traffic import sim
        sim.reload_plan(model_id)  # live dashboards and alert rules follow the newly approved plan
    return row_json(row)


@router.get("/plans/{kind}/diff")
def plan_diff(model_id: str, kind: str, a: int, b: int):
    va = next((r for r in repo.plans.versions(model_id, kind) if r.version == a), None)
    vb = next((r for r in repo.plans.versions(model_id, kind) if r.version == b), None)
    if not va or not vb:
        raise not_found("plan version")
    key = "checks" if kind == "validation" else "rules"
    ia = {c["id"]: c for c in va.body.get(key, [])}
    ib = {c["id"]: c for c in vb.body.get(key, [])}
    return {"a": a, "b": b, "added": sorted(set(ib) - set(ia)), "removed": sorted(set(ia) - set(ib)),
            "changed": [{"id": k, "changes": _diff(ia[k], ib[k])} for k in sorted(set(ia) & set(ib)) if ia[k] != ib[k]]}
