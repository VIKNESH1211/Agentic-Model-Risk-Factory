from __future__ import annotations

import json
import warnings
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api
from app.core.config import settings
from app.core.db import init_db
from app.orchestrator import pipeline
from app.tools import controls

warnings.filterwarnings("ignore", category=RuntimeWarning)

import faulthandler  # noqa: E402
import signal  # noqa: E402

_dump = open(settings.var_dir / "stacks.log", "a")
faulthandler.register(signal.SIGUSR1, file=_dump, all_threads=True)  # `kill -USR1 <pid>` → var/stacks.log


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    controls.seed()
    pipeline.recover_interrupted()
    from app.modelkit.traffic import sim
    sim.restore()  # deployed models come back with their saved traffic settings
    yield


app = FastAPI(title="Model Risk Factory API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(api)


def export_openapi() -> None:
    (settings.root / "contracts" / "openapi.json").write_text(json.dumps(app.openapi(), indent=2))


if __name__ == "__main__":
    export_openapi()
