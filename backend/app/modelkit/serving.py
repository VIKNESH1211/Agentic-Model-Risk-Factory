"""Live endpoints: the redeveloped Python models, loaded from the run that certified them.

predict(rows) -> DataFrame[score, decision] for one or many requests. CR-003 calls CR-001's endpoint
for each applicant's PD and decision, exactly as the legacy batch job consumed CR-001's file.
"""
from __future__ import annotations

import threading

import numpy as np
import pandas as pd

from app.core.config import settings
from app.core.db import session
from app.domain.tables import Model
from app.modelkit import data as D
from app.modelkit import registry as R

_cache: dict[str, "Endpoint"] = {}
_lock = threading.RLock()  # re-entrant: CR-003 builds CR-001 inside get()


def _load_module(path):
    from app.agents.redevelopment import load_model_module
    return load_model_module(path)


class Endpoint:
    def __init__(self, model_id: str, run_id: str):
        self.model_id, self.version = model_id, run_id
        a = R.get(model_id)
        mod = _load_module(settings.runs_dir / run_id / "model.py")
        work = settings.runs_dir / run_id / "sandbox"
        if model_id == "CR-001":
            from app.tools.datasets import prepared
            d = prepared()
            self.m = mod.CR001Scorecard().fit(d[d["split"] == "train"])
        elif model_id == "PR-001":
            self.m = mod.PR001FrequencyGLM().fit(R._pr_frame())
        elif model_id == "FR-001":
            idx = pd.read_csv(work / "out" / "train_idx.csv")["row"].to_numpy()
            self.m = mod.FR001FraudGLM().fit(R._fr_frame(idx), idx)
        elif model_id == "CR-003":
            self.m = mod.CR003LimitStrategy()
            self.upstream = get("CR-001")
        else:
            raise ValueError(f"{model_id} is not deployable ({a.strategy})")

    def predict(self, rows: pd.DataFrame) -> pd.DataFrame:
        mid = self.model_id
        if mid == "CR-001":
            p = self.m.predict_pd(rows)
            dec = np.where(np.isnan(p), None, np.where(p > self.m.cutoff, "DECLINE", "APPROVE"))
            return pd.DataFrame({"score": p, "decision": dec}, index=rows.index)
        if mid == "PR-001":
            return pd.DataFrame({"score": self.m.predict_frequency(rows), "decision": "QUOTED"}, index=rows.index)
        if mid == "FR-001":
            s = self.m.score(rows)
            return pd.DataFrame({"score": s["score"].to_numpy(), "decision": s["decision"].to_numpy()}, index=rows.index)
        if mid == "CR-003":
            up = self.upstream.predict(rows) if self.upstream else None
            if up is None:  # CR-001 not deployed: use its legacy batch scores
                sc = pd.read_csv(D.ROOM / "cr001_scores.csv").set_index("id").reindex(rows["id"])
                up = pd.DataFrame({"score": sc["pd"].to_numpy(), "decision": sc["decision"].to_numpy()}, index=rows.index)
            sc = pd.DataFrame({"id": rows["id"].to_numpy(), "pd": up["score"].to_numpy(), "decision": up["decision"].to_numpy()})
            ok = sc["pd"].notna().to_numpy()
            lim = np.full(len(rows), np.nan)
            if ok.any():
                out = self.m.score(rows[["id", "income"]].iloc[ok], sc[ok]).set_index("id")
                lim[ok] = out.reindex(rows["id"].to_numpy()[ok])["score"].to_numpy()
            return pd.DataFrame({"score": lim, "decision": np.where(np.isnan(lim), None, np.where(lim > 0, "LIMIT", "NO_LIMIT")),
                                 "upstream_pd": up["score"].to_numpy()}, index=rows.index)
        raise ValueError(mid)


def get(model_id: str) -> Endpoint | None:
    """The endpoint for a model's certified run, or None if it has not been redeveloped yet."""
    with session() as s:
        m = s.get(Model, model_id)
    run_id = (m.meta or {}).get("parity_run_id") if m else None
    a = R.get(model_id)
    if not run_id or not a or a.strategy == "rehost" or not (settings.runs_dir / run_id / "model.py").exists():
        return None
    with _lock:
        ep = _cache.get(model_id)
        if ep is None or ep.version != run_id:
            ep = Endpoint(model_id, run_id)
            _cache[model_id] = ep
        return ep


def clear() -> None:
    with _lock:
        _cache.clear()
