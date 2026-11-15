"""Validation and monitoring plans: agent-drafted, linted against the catalog, human-approved, versioned."""
from __future__ import annotations

from pydantic import ValidationError

from app import repositories as repo
from app.core.events import bus
from app.domain.schemas import MonitoringPlan, ValidationPlan
from app.domain.tables import PlanVersion
from app.evidence import ledger

KINDS = {"validation": ValidationPlan, "monitoring": MonitoringPlan}


class PlanError(ValueError):
    pass


def parse(kind: str, body: dict):
    try:
        return KINDS[kind].model_validate(body)
    except ValidationError as e:
        raise PlanError("; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:8])) from e


def current(model_id: str, kind: str):
    row = repo.plans.current(model_id, kind)
    return KINDS[kind].model_validate(row.body) if row else None


def current_row(model_id: str, kind: str) -> PlanVersion | None:
    return repo.plans.current(model_id, kind)


def save_draft(model_id: str, kind: str, body: dict, author: str, note: str = "") -> PlanVersion:
    plan = parse(kind, body)
    row = repo.plans.add_version(model_id, plan.model_dump(), author, note, kind=kind)
    ledger.append(author.split(":")[0] if ":" in author else "human", f"{kind}_plan_drafted",
                  {"model_id": model_id, "version": row.version, "author": author})
    bus.publish("info", f"{model_id}: {kind} plan v{row.version} drafted by {author}", model_id=model_id)
    return row


def approve(model_id: str, kind: str, by: str) -> PlanVersion | None:
    row = repo.plans.latest(model_id, kind)
    if row is None or row.status == "approved":
        return row
    row = repo.plans.approve(row.id, by)
    ledger.append("human", f"{kind}_plan_approved", {"model_id": model_id, "version": row.version, "by": by})
    return row
