"""Health, demo controls (reset, seed test estate, autopilot) and the prompt-injection self-test."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings
from app.core.llm import LAST_ERROR
from app.engine.harness import docker_available
from app.evidence import ledger
from app.orchestrator import services

router = APIRouter(prefix="/api", tags=["system"])


class ResetReq(BaseModel):
    scope: str = "runs"  # runs | all
    seed: bool = False


@router.get("/health")
def health():
    live = settings.llm_provider in ("openai", "anthropic", "groq")
    key = {"openai": settings.openai_api_key, "groq": settings.groq_api_key, "anthropic": settings.llm_api_key}.get(settings.llm_provider)
    return {"ok": True, "llm": {"provider": settings.llm_provider, "model": settings.llm_model, "fast_model": settings.llm_fast_model,
                                "mode": settings.llm_mode, "key": bool(key), "live": live and bool(key),
                                "last_error": LAST_ERROR.get("message")},
            "sandbox_docker": docker_available(), "ledger": ledger.verify()["ok"]}


@router.post("/demo/reset")
def reset(req: ResetReq | None = None):
    req = req or ResetReq()
    out = services.reset(req.scope)
    if req.seed:
        out["seeded"] = services.seed_test_estate()
    return out


@router.post("/demo/seed")
def seed():
    return services.seed_test_estate()


@router.post("/demo/autopilot")
def autopilot():
    return services.autopilot()


@router.get("/demo/state")
def demo_state():
    return services.autopilot_state()


@router.post("/security/injection-test")
def injection(model_id: str | None = None):
    return services.injection_test(model_id)


@router.get("/security/injection-test")
def last_injection():
    return services.last_injection()
