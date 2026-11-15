"""Live endpoints: each certified Python translation, fitted on its own legacy export bundle.

Generic for every model: the parity run directory holds model.py (the certified code) and bundle/
(frame, train rows). Nothing here knows which model it is serving.
"""
from __future__ import annotations

import importlib.util
import threading

import pandas as pd

from app import repositories as repo
from app.core.config import settings
from app.domain.schemas import ModelSpec
from app.engine import bundle as B
from app.engine.scoring import adverse

_cache: dict[str, "Endpoint"] = {}
_lock = threading.RLock()


def load_module(path):
    spec = importlib.util.spec_from_file_location(f"mrf_model_{abs(hash(str(path)))}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Endpoint:
    def __init__(self, model_id: str, run_id: str, spec: ModelSpec):
        self.model_id, self.version, self.spec = model_id, run_id, spec
        d = settings.runs_dir / run_id
        self.bundle = B.load(d / "bundle")
        self.m = load_module(d / "model.py").LegacyModel().fit(self.bundle.frame.copy(), self.bundle.train_rows)

    def predict(self, rows: pd.DataFrame) -> pd.DataFrame:
        out = self.m.score(rows.copy())
        score = pd.to_numeric(out["score"], errors="coerce").to_numpy()
        res = pd.DataFrame({"score": score}, index=rows.index)
        res["decision"] = out["decision"].to_numpy() if "decision" in out else None
        res["flag"] = adverse(res["score"], res["decision"] if "decision" in out else None, self.spec).to_numpy()
        return res


def certified_run(model_id: str) -> str | None:
    m = repo.models.get(model_id)
    meta = (m.meta or {}) if m else {}
    return meta.get("parity_run_id") if meta.get("parity_verdict") == "PASS" else None


def get(model_id: str) -> Endpoint | None:
    run_id = certified_run(model_id)
    if not run_id:
        return None
    with _lock:
        ep = _cache.get(model_id)
        if ep is None or ep.version != run_id:
            from app.services import specs
            ep = _cache[model_id] = Endpoint(model_id, run_id, specs.current(model_id))
        return ep


def invalidate(model_id: str | None = None) -> None:
    with _lock:
        if model_id:
            _cache.pop(model_id, None)
        else:
            _cache.clear()
