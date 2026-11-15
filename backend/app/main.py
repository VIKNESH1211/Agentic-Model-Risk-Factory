"""Model Risk Factory API (v3): generic, DB-driven, agentic model-risk platform for legacy R models."""
from __future__ import annotations

import faulthandler
import json
import math
import signal
import time
import uuid
import warnings
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core import logging as mlog

mlog.setup()

from app.api.routers import ROUTERS  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.db import init_db  # noqa: E402
from app.orchestrator import pipeline, services  # noqa: E402

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
log = mlog.get("api")
_dump = open(settings.var_dir / "stacks.log", "a")
faulthandler.register(signal.SIGUSR1, file=_dump, all_threads=True)  # `kill -USR1 <pid>` → var/stacks.log


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    services.seed_platform()
    pipeline.recover_interrupted()
    from app.engine.traffic import prune, sim
    sim.restore()  # deployed models come back with their saved traffic settings and approved plans
    prune()
    log.info("ready · llm %s:%s (%s) · sandbox image %s · data %s", settings.llm_provider, settings.llm_model, settings.llm_mode,
             settings.sandbox_image, settings.var_dir)
    yield


def _finite(o):
    """NaN / ±inf are legitimate results (e.g. a request with no score) but not valid JSON: send null."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_finite(v) for v in o]
    return o


class SafeJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(_finite(content), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


app = FastAPI(title="Model Risk Factory API", version="3.0.0", lifespan=lifespan, default_response_class=SafeJSONResponse,
              description="Onboard any legacy R model; agents document, rebuild, validate and monitor it under human gates.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def request_log(request: Request, call_next):
    rid = uuid.uuid4().hex[:8]
    t0 = time.perf_counter()
    try:
        resp = await call_next(request)
    except Exception:
        log.exception("%s %s → 500 (request %s)", request.method, request.url.path, rid)
        return JSONResponse({"error": "internal error", "request_id": rid}, status_code=500)
    ms = (time.perf_counter() - t0) * 1000
    path = request.url.path
    if path.startswith("/api") and path != "/api/events" and not (request.method == "GET" and resp.status_code < 400 and ms < 300):
        (log.warning if resp.status_code >= 400 else log.info)("%s %s → %s %.0fms", request.method, path, resp.status_code, ms,
                                                              extra={"path": path, "status": resp.status_code, "ms": round(ms)})
    resp.headers["X-Request-Id"] = rid
    return resp


for r in ROUTERS:
    app.include_router(r)


def export_openapi() -> None:
    (settings.root / "contracts" / "openapi.json").write_text(json.dumps(app.openapi(), indent=2))


if __name__ == "__main__":
    export_openapi()
