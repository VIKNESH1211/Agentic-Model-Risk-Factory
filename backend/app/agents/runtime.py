"""The agent runtime: one tool-use loop for every stage.

    observe → LLM chooses {call tool | finish} → executor validates and runs the tool → observation → …

Guardrails (deterministic, not negotiable by the model):
  · only the stage's tools, with their declared arguments
  · a finish is refused until every mandatory tool has SUCCEEDED (the refusal is fed back as an observation)
  · step budget; on exhaustion the outstanding mandatory tools run with deterministic defaults
  · hard blockers (agent.guard) force a HOLD recommendation whatever the model says
  · every step (thought, call, arguments, result, error, decision) is persisted to agent_steps and the event bus
If the LLM is unavailable, `agent.fallback` picks the next action deterministically, so a stage never stalls.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from app.agents.common import StageCtx
from app.core import llm
from app.services import prompts

STEP_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["thought", "action"],
    "properties": {"thought": {"type": "string"}, "action": {"type": "string", "enum": ["call", "finish"]},
                   "tool": {"type": "string"}, "args": {"type": "object"}, "summary": {"type": "string"},
                   "recommendation": {"type": "string", "enum": ["promote", "hold"]},
                   "reasons": {"type": "array", "items": {"type": "string"}}},
}


class ToolError(Exception):
    """A tool failed in a way the agent can act on (message is written for the agent)."""


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[[StageCtx, dict], Any]
    args: dict[str, str] = field(default_factory=dict)  # arg → description (incl. type)
    summary: Callable[[Any], str] = lambda r: "done"
    observe: Callable[[Any], Any] | None = None  # what the model sees (default: the summary)


@dataclass
class Agent:
    name: str
    stage: str
    goal: str
    tools: list[Tool]
    mandatory: list[str]
    facts: Callable[[StageCtx], dict] = lambda ctx: {}
    fallback: Callable[[StageCtx], dict | None] = lambda ctx: None  # {"tool", "args"} or None = finish
    guard: Callable[[StageCtx], list[str]] = lambda ctx: []        # hard blockers → HOLD
    max_steps: int = 14
    max_failures: int = 4  # consecutive failures of one tool before the agent stops for a human

    def tool(self, name: str) -> Tool | None:
        return next((t for t in self.tools if t.name == name), None)


def _compact(v: Any, n: int = 700) -> str:
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    return s if len(s) <= n else s[:n] + " …(truncated)"


def _tools_text(agent: Agent) -> str:
    lines = []
    for t in agent.tools:
        args = ", ".join(f"{k}: {v}" for k, v in t.args.items()) or "no arguments"
        lines.append(f"- {t.name}({args}) — {t.description}{'  [mandatory]' if t.name in agent.mandatory else ''}")
    return "\n".join(lines)


def _history_text(hist: list[dict]) -> str:
    if not hist:
        return "(none yet)"
    out = []
    for h in hist[-10:]:
        out.append(f"{h['n']}. {h['tool']}({_compact(h.get('args', {}), 200)}) → {'OK' if h['ok'] else 'FAILED'}: {_compact(h['obs'])}")
    return "\n".join(out)


def _facts(ctx: StageCtx, agent: Agent) -> dict:
    f = dict(agent.facts(ctx))
    fb = (ctx.run.state or {}).get("feedback", {}).get(agent.stage)
    if fb:  # the reviewer sent this stage back: their comment is the top priority
        f = {"HUMAN_REVIEWER_FEEDBACK (address this first)": fb, **f}
    return f


def run(ctx: StageCtx, agent: Agent) -> dict:
    """Run the loop; returns the conclusion {summary, recommendation, reasons, source, steps}."""
    ctx.state.setdefault("ok", {})
    hist: list[dict] = []
    ctx.step("plan", f"Goal: {agent.goal}", {"tools": [t.name for t in agent.tools], "mandatory": agent.mandatory,
                                             "max_steps": agent.max_steps})
    ctx.emit("agent_step", f"{agent.name} agent started: {agent.goal[:120]}")
    finish: dict | None = None
    fails: dict[str, int] = {}
    for n in range(1, agent.max_steps + 1):
        outstanding = [t for t in agent.mandatory if not ctx.state["ok"].get(t)]
        fb = agent.fallback(ctx)
        def fallback(fb=fb, outstanding=outstanding):
            if fb:
                return {"thought": "Deterministic policy: next required step.", "action": "call", **fb}
            return {"thought": "All required steps are done.", "action": "finish", "summary": "; ".join(ctx.observations[-5:]) or "Done.",
                    "recommendation": "promote", "reasons": ["Required steps completed"]}
        prompt = prompts.render("agent_step", agent=agent.name, model_id=ctx.model_id, goal=agent.goal,
                                facts=_compact(_facts(ctx, agent), 2500), tools=_tools_text(agent),
                                mandatory=", ".join(agent.mandatory) or "none", outstanding=", ".join(outstanding) or "none",
                                history=_history_text(hist), step=str(n), max_steps=str(agent.max_steps))
        r = llm.complete_json(f"{agent.stage}_step", prompt, STEP_SCHEMA, fallback, run_id=ctx.run_id, agent=agent.name,
                              spent=ctx.spent)
        d = r.data
        if d.get("thought"):
            ctx.think(d["thought"][:600])
        if d.get("action") == "finish":
            if outstanding:
                obs = f"Cannot finish yet: mandatory step(s) not completed successfully: {', '.join(outstanding)}."
                hist.append({"n": n, "tool": "finish", "args": {}, "ok": False, "obs": obs})
                ctx.step("observation", obs)
                continue
            finish = {**d, "source": r.source}
            break
        tool = agent.tool(d.get("tool") or "")
        args = d.get("args") or {}
        if tool is None:
            obs = f"Unknown tool '{d.get('tool')}'. Choose one of: {', '.join(t.name for t in agent.tools)}."
            hist.append({"n": n, "tool": str(d.get("tool")), "args": args, "ok": False, "obs": obs})
            ctx.step("observation", obs)
            continue
        unknown = [k for k in args if k not in tool.args]
        if unknown:
            args = {k: v for k, v in args.items() if k in tool.args}
        try:
            res = ctx.tool(tool.name, (d.get("thought") or tool.description)[:140], lambda: tool.fn(ctx, args),
                           result_summary=tool.summary, args=args)
            ok = not (isinstance(res, dict) and res.get("ok") is False)
            obs = tool.observe(res) if tool.observe else tool.summary(res)
            if isinstance(res, dict) and res.get("ok") is False:
                obs = res.get("error") or obs
        except ToolError as e:
            ok, obs = False, str(e)
        except Exception as e:  # a bug or an unexpected input: the agent sees it and can route around it
            ok, obs = False, f"{type(e).__name__}: {str(e)[:400]}"
        if ok:
            ctx.state["ok"][tool.name] = True
            fails.pop(tool.name, None)
        else:
            fails[tool.name] = fails.get(tool.name, 0) + 1
        hist.append({"n": n, "tool": tool.name, "args": args, "ok": ok, "obs": obs})
        if fails.get(tool.name, 0) >= agent.max_failures:
            ctx.step("observation", f"{tool.name} failed {fails[tool.name]} times in a row — stopping for a human.")
            break

    # The model is stuck or out of budget: the deterministic policy takes over for a few steps (it knows the
    # safe route, e.g. an uploaded reference implementation), still through the same tools and guardrails.
    if [t for t in agent.mandatory if not ctx.state["ok"].get(t)]:
        ctx.step("observation", "Handing over to the deterministic policy to complete the required steps.")
        policy_fails: dict[str, int] = {}
        for _ in range(8):
            fb = agent.fallback(ctx)
            if not fb or policy_fails.get(fb["tool"], 0) >= 2:
                break
            t = agent.tool(fb["tool"])
            try:
                res = ctx.tool(t.name, "deterministic policy", lambda: t.fn(ctx, fb.get("args") or {}),
                               result_summary=t.summary, args=fb.get("args") or {})
                ok = not (isinstance(res, dict) and res.get("ok") is False)
            except Exception as e:
                ok = False
                ctx.step("error", f"{t.name}: {str(e)[:300]}")
            if ok:
                ctx.state["ok"][t.name] = True
            else:
                policy_fails[t.name] = policy_fails.get(t.name, 0) + 1
            if not [m for m in agent.mandatory if not ctx.state["ok"].get(m)]:
                finish = None  # the policy finished the job; the conclusion is rule-based below
                break

    outstanding = [t for t in agent.mandatory if not ctx.state["ok"].get(t)]
    blockers = list(agent.guard(ctx)) + [f"required step not completed: {t}" for t in outstanding]
    done = not [t for t in agent.mandatory if not ctx.state["ok"].get(t)]
    c = finish or {"summary": "; ".join(ctx.observations[-4:]) or "Stopped.",
                   "recommendation": "promote" if done else "hold",
                   "reasons": ["All required steps completed"] if done else ["The agent stopped before finishing"],
                   "source": "runtime"}
    c = {"summary": c.get("summary") or "", "recommendation": c.get("recommendation") or "promote",
         "reasons": list(c.get("reasons") or []), "source": c.get("source", "")}
    if blockers:
        c["recommendation"] = "hold"
        c["reasons"] = blockers + [r for r in c["reasons"] if r not in blockers]
    c["steps"] = len(hist)
    c["incomplete"] = outstanding
    ctx.step("decision", f"Recommendation: {c['recommendation'].upper()} — {c['summary'][:200]}", c)
    ctx.flush_cost()
    return c
