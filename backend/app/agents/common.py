"""Stage context shared by every agent: a persisted step-by-step trace, events, findings, artifacts, ledger."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from sqlmodel import func, select

from app.core import logging as mlog
from app.core.config import settings
from app.core.db import save, session
from app.core.events import bus
from app.domain.tables import AgentStep, Artifact, Finding, Run
from app.evidence import ledger
from app.evidence.metric_store import Recorder, token


log = mlog.get("agent")
ICONS = {"plan": "◆", "thought": "…", "tool_call": "→", "tool_result": "←", "observation": "•", "decision": "■", "error": "✗"}


def _preview(obj: Any, n: int = 600) -> Any:
    try:
        if isinstance(obj, pd.DataFrame):
            return {"type": "table", "rows": len(obj), "columns": list(obj.columns)[:12],
                    "head": json.loads(obj.head(3).to_json(orient="records", default_handler=str))}
        if isinstance(obj, (dict, list)):
            s = json.dumps(obj, default=str)
            return json.loads(s) if len(s) <= n else s[:n] + "…"
        if hasattr(obj, "__dict__") and not isinstance(obj, type):
            d = {k: v for k, v in vars(obj).items() if isinstance(v, (str, int, float, bool))}
            return d or type(obj).__name__
        s = str(obj)
        return s if len(s) <= n else s[:n] + "…"
    except Exception:
        return type(obj).__name__


class StageCtx:
    def __init__(self, run: Run, stage: str, agent: str):
        self.run, self.stage, self.agent = run, stage, agent
        self.run_id, self.model_id = run.id, run.model_id
        self.dir = settings.runs_dir / run.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.rel = f"runs/{run.id}"
        self.spent = {"cost": run.llm_cost, "tokens": run.tokens}
        self.observations: list[str] = []
        self.state: dict = {}  # shared by the tools of one stage

    # -------------------------------------------------------------- trace
    def step(self, kind: str, title: str, content: dict | None = None, duration_ms: int | None = None) -> AgentStep:
        (log.warning if kind == "error" else log.info)(
            "%s %-8s %-13s %s", ICONS.get(kind, "·"), self.model_id, self.agent, title[:200],
            extra={"run_id": self.run_id, "model_id": self.model_id, "agent": self.agent, "stage": self.stage, "kind": kind})
        st = save(AgentStep(run_id=self.run_id, model_id=self.model_id, stage=self.stage, agent=self.agent, kind=kind,
                            title=title[:300], content=json.loads(json.dumps(content or {}, default=str)), duration_ms=duration_ms))
        bus.publish("agent_step", f"[{kind}] {title}"[:220], run_id=self.run_id, model_id=self.model_id, stage=self.stage,
                    agent=self.agent, payload={"step_id": st.id, "kind": kind})
        return st

    def think(self, text: str) -> None:
        self.step("thought", text)

    def emit(self, type: str, summary: str, payload: dict | None = None) -> None:
        bus.publish(type, summary, run_id=self.run_id, model_id=self.model_id, stage=self.stage,
                    agent=self.agent, payload=payload)

    def pace(self, k: float = 1.0) -> None:
        if settings.demo_pace > 0:
            time.sleep(settings.demo_pace * k)

    def tool(self, name: str, summary: str, fn: Callable[[], Any], *, result_summary: Callable[[Any], str] | None = None,
             payload: dict | None = None, args: dict | None = None) -> Any:
        self.step("tool_call", f"{name} · {summary}", {"tool": name, "args": args or payload or {}})
        self.emit("tool_call", f"{name} · {summary}", {"tool": name, **(payload or {})})
        self.pace(0.6)
        t0 = time.perf_counter()
        try:
            out = fn()
        except Exception as e:
            ms = round((time.perf_counter() - t0) * 1000)
            self.step("error", f"{name} raised {type(e).__name__}", {"tool": name, "error": str(e)[:800]}, ms)
            raise
        ms = round((time.perf_counter() - t0) * 1000)
        rs = result_summary(out) if result_summary else "done"
        self.step("tool_result", f"{name} → {rs}", {"tool": name, "result": _preview(out)}, ms)
        self.observations.append(f"{name}: {rs}")
        self.emit("tool_result", f"{name} → {rs}", {"tool": name, "elapsed_ms": ms})
        self.pace(0.4)
        return out

    # -------------------------------------------------------------- records
    def recorder(self) -> Recorder:
        return Recorder(self.run_id, self.model_id, self.stage, self.agent)

    def tok(self, name: str) -> str:
        return token(self.run_id, name)

    def artifact(self, kind: str, path: Path) -> Artifact:
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        a = save(Artifact(run_id=self.run_id, kind=kind, path=str(path.relative_to(settings.var_dir)), sha256=sha))
        ledger.append(self.agent, "artifact_stored", {"run_id": self.run_id, "model_id": self.model_id,
                                                      "kind": kind, "path": a.path, "sha256": sha})
        return a

    def finding(self, severity: str, category: str, title: str, detail: str, *, detector: str = "",
                evidence: dict | None = None, impact: dict | None = None) -> Finding:
        with session() as s:
            n = s.exec(select(func.count()).select_from(Finding).where(Finding.run_id == self.run_id)).one()
        code = f"F-{n + 1:02d}"
        f = save(Finding(code=code, model_id=self.model_id, run_id=self.run_id, severity=severity,
                         category=category, title=title, detail=detail, detector=detector,
                         evidence=evidence or {}, impact=impact or {}))
        ledger.append(self.agent, "finding_recorded", {"run_id": self.run_id, "model_id": self.model_id,
                                                       "code": code, "severity": severity, "title": title,
                                                       "detector": detector})
        self.step("observation", f"Finding {code} ({severity}): {title}", {"detail": detail, "detector": detector,
                                                                           "evidence": evidence or {}})
        self.observations.append(f"finding {code} {severity}: {title}")
        self.emit("finding", f"{'⚠' if severity in ('high', 'medium') else 'ℹ'} {code} {title}",
                  {"code": code, "severity": severity, "category": category, "finding_id": f.id})
        self.pace(0.5)
        return f

    def flush_cost(self) -> None:
        with session() as s:
            r = s.get(Run, self.run_id)
            r.llm_cost, r.tokens = self.spent.get("cost", 0.0), int(self.spent.get("tokens", 0))
            s.add(r)
            s.commit()
