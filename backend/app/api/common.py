"""Shared helpers for the API routers."""
from __future__ import annotations

from datetime import timezone

from fastapi import HTTPException

from app.domain.tables import Run


def iso(dt):
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def run_json(r: Run) -> dict:
    from app.orchestrator import pipeline
    d = r.model_dump()
    d["started_at"], d["ended_at"] = iso(r.started_at), iso(r.ended_at)
    d["station"] = pipeline.STATION.get(r.stage, r.stage)
    d["stages"] = pipeline.stages_for(r)
    return d


def row_json(r) -> dict:
    d = r.model_dump()
    for k in ("created_at", "approved_at", "requested_at", "decided_at", "ts"):
        if k in d:
            d[k] = iso(getattr(r, k))
    return d


def not_found(what: str) -> HTTPException:
    return HTTPException(404, f"{what} not found")
