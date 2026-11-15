"""The library: prompt templates (versioned, editable), the policy-check library, metric and KPI catalogs."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import repositories as repo
from app.api.common import not_found, row_json
from app.domain.tables import PolicyCheck
from app.engine import catalog
from app.evidence import ledger
from app.services import prompts

router = APIRouter(prefix="/api/library", tags=["library"])


class PromptEdit(BaseModel):
    text: str
    author: str = "Model Risk Officer"


class PolicyBody(BaseModel):
    title: str
    category: str
    severity: str
    kind: str = "regex"
    pattern: str = ""
    description: str = ""
    enabled: bool = True


@router.get("/prompts")
def list_prompts():
    return prompts.catalog()


@router.get("/prompts/{key}/versions")
def prompt_versions(key: str):
    rows = sorted(repo.prompts.list(key=key), key=lambda r: -r.version)
    if not rows:
        raise not_found("prompt")
    return [row_json(r) for r in rows]


@router.put("/prompts/{key}")
def edit_prompt(key: str, e: PromptEdit):
    try:
        return row_json(prompts.update(key, e.text, e.author))
    except (ValueError, KeyError) as ex:
        raise HTTPException(422, str(ex))


@router.post("/prompts/{key}/reset")
def reset_prompt(key: str):
    return row_json(prompts.reset(key, "Model Risk Officer"))


@router.get("/policies")
def list_policies():
    return [p.model_dump() for p in repo.policy_checks.list()]


@router.put("/policies/{code}")
def upsert_policy(code: str, b: PolicyBody):
    import re
    if b.kind == "regex":
        try:
            re.compile(b.pattern)
        except re.error as e:
            raise HTTPException(422, f"invalid regex: {e}")
    if repo.policy_checks.get(code):
        row = repo.policy_checks.update(code, **b.model_dump())
    else:
        row = repo.policy_checks.create(PolicyCheck(code=code, **b.model_dump()))
    ledger.append("human", "policy_check_saved", {"code": code, "enabled": b.enabled})
    return row.model_dump()


@router.delete("/policies/{code}")
def delete_policy(code: str):
    repo.policy_checks.delete(code)
    ledger.append("human", "policy_check_deleted", {"code": code})
    return {"ok": True}


@router.get("/metrics")
def metric_catalog():
    return {"metrics": catalog.describe(), "kpis": catalog.KPI_CATALOG, "standard_columns": catalog.STANDARD_COLUMNS}
