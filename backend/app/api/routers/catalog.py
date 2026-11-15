"""Model inventory, model files and the data room (onboarding = uploads)."""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import networkx as nx
import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import func, select

from app import repositories as repo
from app.evidence import ledger
from app.api.common import iso, not_found, row_json, run_json
from app.core import storage
from app.core.config import settings
from app.core.db import session
from app.domain.tables import Finding, Report, Run
from app.services import onboarding, specs
from app.tools import graph_build
from app.tools.parsers import r_parser

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/models")
def list_models():
    with session() as s:
        counts = dict(s.exec(select(Finding.model_id, func.count()).group_by(Finding.model_id)).all())
    g = graph_build.build()
    out = []
    for m in repo.models.list():
        sp, vp = repo.specs.current(m.id), repo.plans.current(m.id, "validation")
        out.append({**row_json(m), "findings": counts.get(m.id, 0), "blast_radius": graph_build.blast_radius(g, m.id),
                    "spec": {"version": sp.version, "status": sp.status} if sp else None,
                    "validation_plan": {"version": vp.version, "status": vp.status} if vp else None,
                    "files": [f.name for f in onboarding.files_of(m.id)]})
    return out


@router.post("/models", status_code=201)
async def onboard_model(files: list[UploadFile] = File(...), model_id: str = Form(""), name: str = Form(""),
                        owner: str = Form(""), description: str = Form(""), start: bool = Form(False)):
    """Upload a legacy model: one or more R scripts (+ optional reference .py, docs). The intake agent does the rest."""
    payload = [(f.filename, await f.read()) for f in files]
    try:
        m = onboarding.create_model(payload, model_id=model_id or None, name=name, owner=owner, description=description)
    except ValueError as e:
        raise HTTPException(400, str(e))
    run = None
    if start:
        from app.orchestrator import pipeline
        run = run_json(pipeline.start_portfolio([m.id], False)[0])
    return {"model": row_json(m), "run": run}


@router.get("/models/{model_id}")
def get_model(model_id: str):
    m = repo.models.get(model_id)
    if not m:
        raise not_found("model")
    with session() as s:
        runs = s.exec(select(Run).where(Run.model_id == model_id).order_by(Run.started_at.desc())).all()
        findings = s.exec(select(Finding).where(Finding.model_id == model_id).order_by(Finding.id)).all()
        reports = s.exec(select(Report).where(Report.model_id == model_id).order_by(Report.version)).all()
    doc = None
    if (m.meta or {}).get("doc_run_id"):
        f = settings.runs_dir / m.meta["doc_run_id"] / "model_doc.json"
        doc = json.loads(f.read_text()) if f.exists() else None
    g = graph_build.build()
    sp = repo.specs.current(model_id)
    return {"model": row_json(m), "runs": [run_json(r) for r in runs], "findings": [f.model_dump() for f in findings],
            "reports": [{"id": r.id, "version": r.version, "run_id": r.run_id, "status": r.status, "checker_ok": r.checker.get("ok")}
                        for r in reports],
            "doc": doc, "files": [row_json(f) for f in onboarding.files_of(model_id)],
            "spec": row_json(sp) if sp else None, "blast_radius": graph_build.blast_radius(g, model_id),
            "upstream": sorted(g.predecessors(model_id)) if model_id in g else [],
            "downstream": sorted(g.successors(model_id)) if model_id in g else []}


@router.delete("/models/{model_id}")
def delete_model(model_id: str):
    if not repo.models.get(model_id):
        raise not_found("model")
    from app.engine.traffic import sim
    sim.undeploy(model_id)
    onboarding.delete_model(model_id)
    return {"ok": True}


@router.post("/models/{model_id}/files")
async def add_model_file(model_id: str, file: UploadFile = File(...), role: str = Form("")):
    if not repo.models.get(model_id):
        raise not_found("model")
    f = onboarding.add_file(model_id, file.filename, await file.read(), role or None)
    return row_json(f)


@router.get("/models/{model_id}/files/{name}")
def read_model_file(model_id: str, name: str):
    f = repo.model_files.first(model_id=model_id, name=name)
    if not f:
        raise not_found("file")
    text = storage.read_text(f.sha256)
    out = {**row_json(f), "text": text, "lines": text.count("\n") + 1}
    if f.role == "script":
        p = r_parser.parse_text(text, f.name)
        out["parse"] = {k: p[k] for k in ("methods", "libraries", "reads", "writes", "smells", "injection", "loc")}
    return out


@router.get("/graph")
def graph():
    return graph_build.as_json()


class EdgeIn(BaseModel):
    source: str
    target: str
    via: str = ""
    note: str = ""
    by: str = "Model Risk Officer"
    restore: bool = False


def _save_lineage(model_id: str, o: dict) -> None:
    m = repo.models.get(model_id)
    repo.models.update(model_id, meta={**(m.meta or {}), "lineage": o})


@router.post("/graph/edges")
def add_edge(e: EdgeIn):
    """Declare that `source` feeds `target`, or (restore=true) bring back a derived edge that was removed."""
    if e.source == e.target:
        raise HTTPException(400, "a model can't depend on itself")
    for mid in (e.source, e.target):
        if not repo.models.get(mid):
            raise not_found(f"model {mid}")
    o = graph_build.overrides(repo.models.get(e.target).meta)
    removed = next((r for r in o["removed"] if r["source"] == e.source), None)
    if e.restore:
        if not removed:
            raise HTTPException(404, f"no removed dependency {e.source} → {e.target}")
        o["removed"].remove(removed)
        _save_lineage(e.target, o)
        ledger.append("human", "dependency_restored", {"model_id": e.target, "upstream": e.source, "by": e.by})
        return graph_build.as_json()
    g = graph_build.build()
    if g.has_edge(e.source, e.target) and g[e.source][e.target].get("kind") == "feeds":
        raise HTTPException(409, f"{e.source} already feeds {e.target}")
    feeds = nx.DiGraph([(u, v) for u, v, d in g.edges(data=True) if d.get("kind") == "feeds"])
    if e.target in feeds and e.source in feeds and nx.has_path(feeds, e.target, e.source):
        path = " → ".join(nx.shortest_path(feeds, e.target, e.source))
        raise HTTPException(409, f"that would create a cycle: {path} → {e.target}")
    if removed:
        o["removed"].remove(removed)
    o["added"] = [a for a in o["added"] if a["source"] != e.source] + [
        {"source": e.source, "via": e.via.strip(), "note": e.note.strip(), "by": e.by, "at": iso(datetime.now(timezone.utc))}]
    _save_lineage(e.target, o)
    ledger.append("human", "dependency_added", {"model_id": e.target, "upstream": e.source, "via": e.via, "note": e.note, "by": e.by})
    return graph_build.as_json()


@router.delete("/graph/edges")
def remove_edge(source: str, target: str, by: str = "Model Risk Officer", note: str = ""):
    """Remove a dependency. Manual edges are deleted; derived ones (spec / data room) are suppressed and can be restored."""
    tgt = repo.models.get(target)
    if not tgt:
        raise not_found(f"model {target}")
    g = graph_build.build()
    if not g.has_edge(source, target):
        raise HTTPException(404, f"no dependency {source} → {target}")
    d = g[source][target]
    o = graph_build.overrides(tgt.meta)
    o["added"] = [a for a in o["added"] if a["source"] != source]
    if d.get("origin") != "manual":
        o["removed"] = [r for r in o["removed"] if r["source"] != source] + [
            {"source": source, "kind": d.get("kind"), "via": d.get("via", ""), "origin": d.get("origin"), "note": note,
             "by": by, "at": iso(datetime.now(timezone.utc))}]
    _save_lineage(target, o)
    ledger.append("human", "dependency_removed", {"model_id": target, "upstream": source, "kind": d.get("kind"),
                                                  "origin": d.get("origin"), "note": note, "by": by})
    return graph_build.as_json()


# ------------------------------------------------------------------ data room
@router.get("/data-room")
def data_room():
    return [{**row_json(a), "versions": len(onboarding.asset_versions(a.name)),
             "used_by": [m.id for m in repo.models.list() if (sp := specs.current_or_none(m.id)) and a.name in {i.asset for i in sp.inputs}]}
            for a in repo.assets.list(is_current=True)]


@router.post("/data-room", status_code=201)
async def upload_asset(file: UploadFile = File(...), description: str = Form(""), provenance: str = Form("")):
    a = onboarding.upload_asset(file.filename, await file.read(), description=description, provenance=provenance)
    return row_json(a)


@router.get("/data-room/{name}")
def asset(name: str, rows: int = 25):
    a = repo.current_asset(name)
    if not a:
        raise not_found("asset")
    try:
        head = pd.read_csv(storage.path_of(a.sha256), nrows=rows, low_memory=False)
        preview = json.loads(head.to_json(orient="split"))
    except Exception:
        preview = None
    return {**row_json(a), "preview": preview, "versions": [row_json(v) for v in onboarding.asset_versions(name)]}
