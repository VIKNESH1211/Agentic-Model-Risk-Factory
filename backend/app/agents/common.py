"""Shared agent plumbing: a persisted, step-by-step agent trace (plan → act → observe → conclude),
plus events, findings, artifacts and ledger entries."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from sqlmodel import func, select

from app.core import llm
from app.core.config import settings
from app.core.db import save, session
from app.core.events import bus
from app.domain.tables import AgentStep, Artifact, Finding, Run
from app.evidence import ledger
from app.evidence.metric_store import Recorder, token

# The tool menu each stage's agent plans from. "optional" tools are the agent's choice.
STAGE_TOOLS: dict[str, dict] = {
    "discover": {"goal": "Find the model in the legacy estate, understand what it does and how risky it is.",
                 "tools": {"file_walker": "list files and lines of code", "r_parser": "extract methods, inputs, outputs",
                           "code_smell_scan": "hardcoded paths, magic numbers, stale TODOs",
                           "injection_guard": "scan untrusted source for instructions aimed at AI",
                           "tiering_rule": "deterministic materiality x customer-impact tier",
                           "llm.classify": "draft the tier rationale"}, "optional": {}},
    "document": {"goal": "Produce structured model documentation and list documentation gaps.",
                 "tools": {"r_parser": "re-read the code", "lineage_builder": "trace inputs/outputs to other models",
                           "data_profiler": "profile model inputs", "llm.draft": "draft documentation sections"},
                 "optional": {}},
    "redevelop": {"goal": "Rebuild the model in Python and prove it behaves exactly like the legacy code.",
                  "tools": {"data_room": "assemble the files the legacy code expects", "llm.translate": "draft the Python translation",
                            "sandbox.Rscript": "run the unmodified legacy code with no network",
                            "parity.precheck": "compare the translation with legacy on every row",
                            "llm.repair": "feed a failure back for one repair", "parity.certify": "issue the certificate"},
                  "optional": {"fuzz": "differential fuzzing on thousands of edge cases (scorecards)"}},
    "validate": {"goal": "Independently validate the model with fixed thresholds and raise findings.",
                 "tools": {"refit": "independent re-fit from code + data", "detectors": "performance, calibration, stability, fairness, data quality",
                           "code_review": "rule-based review of the legacy source", "impact": "convert findings into GBP and customers"},
                 "optional": {"challenger": "fit a gradient-boosting challenger and compare",
                              "slice_search": "find segments where the model ranks badly",
                              "stress_test": "perturb inputs and count decision flips"}},
    "report": {"goal": "Write the validation report; every number must be a traceable token.",
               "tools": {"llm.draft": "executive summary in tokens only", "token_checker": "reject any unsourced number"},
               "optional": {}},
    "monitor_setup": {"goal": "Deploy the model behind the traffic simulator and arm drift and performance alerts.",
                      "tools": {"deploy": "load the validated Python model as a live endpoint",
                                "baseline": "freeze the score and input distributions to compare against",
                                "alert_rules": "arm PSI, CSI, latency, no-decision and A/E rules"}, "optional": {}},
}


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
        self.choices: dict = {}
        self.observations: list[str] = []

    # -------------------------------------------------------------- trace
    def step(self, kind: str, title: str, content: dict | None = None, duration_ms: int | None = None) -> AgentStep:
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

    # -------------------------------------------------------------- plan / conclude (LLM, with deterministic fallback)
    def plan(self, facts: dict | None = None) -> dict:
        menu = STAGE_TOOLS.get(self.stage, {"goal": self.stage, "tools": {}, "optional": {}})
        schema = {"type": "object", "additionalProperties": False, "required": ["steps", "optional", "rationale"],
                  "properties": {"steps": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                                      "required": ["tool", "why"],
                                                                      "properties": {"tool": {"type": "string"}, "why": {"type": "string"}}}},
                                 "optional": {"type": "array", "items": {"type": "string"}},
                                 "rationale": {"type": "string"}}}

        def fallback():
            return {"steps": [{"tool": t, "why": d} for t, d in menu["tools"].items()],
                    "optional": list(menu["optional"]), "rationale": "Standard procedure: run every check (offline planner)."}
        r = llm.complete_json(
            f"plan_{self.stage}",
            f"You are the {self.agent} agent in a model-risk factory. Goal: {menu['goal']}\nModel: {self.model_id}. "
            f"Facts: {json.dumps(facts or {}, default=str)}\nMandatory tools (use all, in a sensible order): {json.dumps(menu['tools'])}\n"
            f"Optional analyses (choose the ones worth running for THIS model, explain why): {json.dumps(menu['optional'])}\n"
            "Return steps (tool + one-line why), the optional analyses you choose, and a two-sentence rationale.",
            schema, fallback, run_id=self.run_id, agent=self.agent, spent=self.spent, fast=True)
        p = r.data
        p["optional"] = [o for o in p.get("optional", []) if o in menu["optional"]]
        p["source"] = r.source
        self.choices = {"optional": p["optional"]}
        self.step("plan", f"Plan: {menu['goal']}", {**p, "mandatory": list(menu["tools"]), "menu_optional": menu["optional"]})
        return p

    def conclude(self, extra: dict | None = None) -> dict:
        schema = {"type": "object", "additionalProperties": False, "required": ["summary", "recommendation", "reasons"],
                  "properties": {"summary": {"type": "string"}, "recommendation": {"type": "string", "enum": ["promote", "hold"]},
                                 "reasons": {"type": "array", "items": {"type": "string"}}}}
        with session() as s:
            highs = s.exec(select(func.count()).select_from(Finding).where(Finding.run_id == self.run_id,
                                                                          Finding.severity == "high")).one()

        def fallback():
            rec = "hold" if (self.stage in ("validate", "report") and highs) else "promote"
            return {"summary": "; ".join(self.observations[-6:]) or "Stage completed.", "recommendation": rec,
                    "reasons": [f"{highs} high-severity finding(s) open" if highs else "No blocking issue found"]}
        r = llm.complete_json(
            f"conclude_{self.stage}",
            f"You are the {self.agent} agent. Stage '{self.stage}' for model {self.model_id} is complete. "
            f"Tool observations: {json.dumps(self.observations[-14:])}\nHigh-severity findings open: {highs}\n"
            f"Extra facts: {json.dumps(extra or {}, default=str)}\n"
            "Summarise what you observed in two or three sentences, then recommend 'promote' (move to the next stage) or "
            "'hold' (a human should look first), with short reasons. Only use facts given here.",
            schema, fallback, run_id=self.run_id, agent=self.agent, spent=self.spent, fast=True)
        c = {**r.data, "source": r.source}
        self.step("decision", f"Recommendation: {c['recommendation'].upper()} — {c['summary'][:160]}", c)
        self.flush_cost()
        return c

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
