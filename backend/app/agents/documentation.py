"""Documentation & planning agent: documents the model from evidence, reviews its code, and proposes the
validation plan (metrics + thresholds) and the monitoring plan (KPIs, alerts, dashboard, drift scenarios)
that are specific to THIS model. Plans are linted against the metric catalog before they are saved.
"""
from __future__ import annotations

import json

from app import repositories as repo
from app.agents.common import StageCtx
from app.agents.intake import model_probe
from app.agents.runtime import Agent, Tool, ToolError, run as run_agent
from app.core import llm
from app.domain.schemas import ModelSpec, MonitoringPlan, ValidationPlan
from app.engine import catalog, defaults
from app.services import onboarding, plans, policy, prompts, specs

SECTIONS = ["purpose", "scope_and_use", "data", "methodology", "variables", "implementation", "assumptions_limitations",
            "performance_and_monitoring", "governance", "gaps"]


def frame_estimate(model_id: str, spec: ModelSpec) -> list[str]:
    """Columns of the data frame the model most likely scores (from the sandbox probe), before the export exists."""
    frames = model_probe(model_id).get("frames", {})
    want = set(spec.features) | ({spec.target} if spec.target else set())
    best = max(frames.items(), key=lambda kv: len(want & {c["column"] for c in kv[1]}), default=(None, []))[1]
    cols = [c["column"] for c in best]
    return cols + [c for c in ([spec.target] if spec.target else []) if c not in cols]


def _spec(ctx: StageCtx) -> ModelSpec:
    if "spec" not in ctx.state:
        ctx.state["spec"] = specs.current(ctx.model_id)
    return ctx.state["spec"]


def _spec_brief(s: ModelSpec) -> str:
    return json.dumps({k: v for k, v in s.model_dump().items() if k not in ("harness",)}, default=str)[:3500]


# ------------------------------------------------------------------ tools
def t_policies(ctx: StageCtx, args: dict) -> list[dict]:
    name, text = onboarding.script_text(ctx.model_id, _spec(ctx).entry_script)
    hits = policy.run(text, name)
    for h in hits:
        ctx.finding(h["severity"], h["category"], h["title"], h["description"], detector=f"policy:{h['code']}",
                    evidence={"file": name, "line": h["line"], "code": h["text"]})
    ctx.state["policy"] = hits
    return hits


REVIEW_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["findings"],
                 "properties": {"findings": {"type": "array", "items": {"type": "object"}}}}


def t_review(ctx: StageCtx, args: dict) -> dict:
    s = _spec(ctx)
    name, text = onboarding.script_text(ctx.model_id, s.entry_script)
    lines = text.splitlines()
    r = llm.complete_json("code_review", prompts.render("code_review", spec=_spec_brief(s), focus=args.get("focus") or "general",
                          policy=json.dumps([h["title"] for h in ctx.state.get("policy", [])])),
                          REVIEW_SCHEMA, lambda: {"findings": []}, run_id=ctx.run_id, agent="documentation",
                          untrusted={name: "\n".join(f"{i:>4}| {l}" for i, l in enumerate(lines, 1))}, spent=ctx.spent)
    kept, dropped = [], 0
    for f in r.data.get("findings", [])[:8]:
        try:
            ln = int(f.get("line") or 0)
        except (TypeError, ValueError):
            ln = 0
        code = lines[ln - 1].strip() if 0 < ln <= len(lines) else ""
        if not code:  # every LLM finding must point at a real line, or it is dropped
            dropped += 1
            continue
        sev = f.get("severity") if f.get("severity") in ("high", "medium", "low") else "medium"
        ctx.finding(sev, str(f.get("category") or "methodology")[:30], str(f.get("title") or "Code issue")[:160],
                    str(f.get("detail") or "")[:1200], detector="llm_review", evidence={"file": name, "line": ln, "code": code})
        kept.append(f.get("title"))
    ctx.state["review"] = kept
    return {"findings": kept, "dropped_unverifiable": dropped, "source": r.source}


def _lineage(model_id: str, s: ModelSpec) -> dict:
    """Read from the dependency graph, so hand edits on the Models page reach the documentation too."""
    from app.tools import graph_build
    g = graph_build.build()
    mine = {m.asset for m in s.inputs}
    if model_id not in g:
        return {"reads": sorted(mine), "upstream": [], "downstream": [], "shares_data_with": []}
    feeds_in = [(u, d) for u, _, d in g.in_edges(model_id, data=True) if d.get("kind") == "feeds"]
    downstream = sorted(v for _, v, d in g.out_edges(model_id, data=True) if d.get("kind") == "feeds")
    shares = sorted({u for u, _, d in g.in_edges(model_id, data=True) if d.get("kind") == "shares_data"}
                    | {v for _, v, d in g.out_edges(model_id, data=True) if d.get("kind") == "shares_data"})
    return {"reads": sorted(mine), "upstream": [{"model_id": u, "via_asset": d.get("via", ""), "origin": d.get("origin")} for u, d in feeds_in],
            "downstream": downstream, "shares_data_with": shares}


DOC_SCHEMA = {"type": "object", "additionalProperties": False, "required": SECTIONS,
              "properties": {k: {"type": "string"} for k in SECTIONS}}


def t_doc(ctx: StageCtx, args: dict) -> dict:
    s = _spec(ctx)
    m = repo.models.get(ctx.model_id)
    parse = (m.meta or {}).get("parse", {})
    lineage = _lineage(ctx.model_id, s)
    r = llm.complete_json("doc_draft", prompts.render(
        "doc_draft", model_id=ctx.model_id, spec=_spec_brief(s), parse=json.dumps(parse, default=str)[:1500],
        lineage=json.dumps(lineage), policy=json.dumps([h["title"] for h in ctx.state.get("policy", [])]),
        review=json.dumps(ctx.state.get("review", []))) + (f"\nAgent instructions: {args['instructions']}" if args.get("instructions") else ""),
        DOC_SCHEMA, lambda: {k: "" for k in SECTIONS}, run_id=ctx.run_id, agent="documentation", spent=ctx.spent)
    sections = r.data
    if not any(sections.values()):
        raise ToolError(f"documentation not drafted ({r.source}); a language model is required")
    gaps = [g.strip(" -•") for g in sections.get("gaps", "").split("\n") if g.strip(" -•")]
    doc = {"model_id": ctx.model_id, "sections": sections, "lineage": lineage, "gaps": gaps, "llm_source": r.source,
           "spec_version": repo.specs.current(ctx.model_id).version,
           "completeness": round(sum(1 for k in SECTIONS if sections.get(k) and "not documented" not in sections[k].lower()) / len(SECTIONS), 2)}
    f = ctx.dir / "model_doc.json"
    f.write_text(json.dumps(doc, indent=2))
    ctx.artifact("model_doc", f)
    repo.models.update(ctx.model_id, meta={**(m.meta or {}), "doc_run_id": ctx.run_id, "doc_gaps": len(gaps)})
    ctx.state["doc"] = doc
    return {"sections": len([v for v in sections.values() if v]), "gaps": gaps[:8], "completeness": doc["completeness"]}


PLAN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["plan", "summary"],
               "properties": {"plan": {"type": "object"}, "summary": {"type": "string"}}}


def _context(ctx: StageCtx) -> str:
    doc = ctx.state.get("doc") or {}
    return json.dumps({"gaps": doc.get("gaps", [])[:8], "policy": [h["title"] for h in ctx.state.get("policy", [])],
                       "review": ctx.state.get("review", [])})[:2500]


def t_vplan(ctx: StageCtx, args: dict) -> dict:
    s = _spec(ctx)
    cols = catalog.scored_columns(s, frame_estimate(ctx.model_id, s))
    base = defaults.validation_plan(s)
    prev = ctx.state.get("vplan_errors")
    previous = ("Your previous plan was rejected:\n- " + "\n- ".join(prev)) if prev else \
        f"Baseline plan (improve it for this model): {json.dumps(base.model_dump())[:2500]}"
    r = llm.complete_json("validation_plan", prompts.render(
        "validation_plan", model_id=ctx.model_id, spec=_spec_brief(s), columns=", ".join(sorted(cols)), context=_context(ctx),
        catalog=json.dumps(catalog.describe(s.task)), previous=previous + (f"\nAgent instructions: {args['instructions']}" if args.get("instructions") else ""),
        schema=json.dumps(ValidationPlan.model_json_schema())[:5000]),
        PLAN_SCHEMA, lambda: {"plan": base.model_dump(), "summary": "Baseline plan (LLM unavailable)."},
        run_id=ctx.run_id, agent="planner", spent=ctx.spent)
    try:
        plan = plans.parse("validation", r.data.get("plan") or {})
    except plans.PlanError as e:
        ctx.state["vplan_errors"] = [str(e)]
        return {"ok": False, "error": f"plan does not match the schema: {e}"}
    good, errs = catalog.valid_checks(plan, s, cols)
    n = ctx.state["vplan_attempts"] = ctx.state.get("vplan_attempts", 0) + 1
    author, note = "agent:planner", r.data.get("summary", "")[:800]
    if errs and len(good) >= 6:  # salvage: keep the valid checks, report what was dropped
        plan = plan.model_copy(update={"checks": good})
        note = f"{note} (dropped {len(errs)} invalid check(s): {'; '.join(errs[:3])})"
    elif errs and n >= 2:  # still wrong after a retry: the deterministic baseline, plus whatever was valid
        base_ids = {c.id for c in base.checks}
        plan = base.model_copy(update={"checks": base.checks + [c for c in good if c.id not in base_ids]})
        author, note = "system:baseline", f"Baseline plan for a {s.task} model (the planner's drafts failed the linter: {'; '.join(errs[:3])})"
    elif errs:
        ctx.state["vplan_errors"] = errs
        return {"ok": False, "error": "plan rejected by the linter: " + "; ".join(errs[:10])}
    row = plans.save_draft(ctx.model_id, "validation", plan.model_dump(), author, note=note)
    ctx.state["vplan_errors"] = []
    by = {}
    for c in plan.checks:
        by[c.category] = by.get(c.category, 0) + 1
    return {"ok": True, "version": row.version, "checks": len(plan.checks), "by_category": by,
            "investigations": plan.investigations, "summary": r.data.get("summary", "")[:300], "source": r.source}


def t_mplan(ctx: StageCtx, args: dict) -> dict:
    s = _spec(ctx)
    cols = frame_estimate(ctx.model_id, s)
    frames = model_probe(ctx.model_id).get("frames", {})
    numeric = [c["column"] for cols_ in frames.values() for c in cols_ if c["column"] in s.features
               and c["class"] in ("numeric", "integer") and c["unique"] > 15]
    base = defaults.monitoring_plan(s, list(dict.fromkeys(numeric)))
    prev = ctx.state.get("mplan_errors")
    previous = ("Your previous plan was rejected:\n- " + "\n- ".join(prev)) if prev else \
        f"Baseline plan (improve it for this model): {json.dumps(base.model_dump())[:2000]}"
    r = llm.complete_json("monitoring_plan", prompts.render(
        "monitoring_plan", model_id=ctx.model_id, spec=_spec_brief(s), columns=", ".join(cols), kpis=json.dumps(catalog.KPI_CATALOG),
        context=_context(ctx), previous=previous + (f"\nAgent instructions: {args['instructions']}" if args.get("instructions") else ""),
        schema=json.dumps(MonitoringPlan.model_json_schema())[:5000]),
        PLAN_SCHEMA, lambda: {"plan": base.model_dump(), "summary": "Baseline plan (LLM unavailable)."},
        run_id=ctx.run_id, agent="planner", spent=ctx.spent)
    try:
        plan = plans.parse("monitoring", r.data.get("plan") or {})
    except plans.PlanError as e:
        ctx.state["mplan_errors"] = [str(e)]
        return {"ok": False, "error": f"plan does not match the schema: {e}"}
    errs = catalog.lint_monitoring(plan, set(cols))
    n = ctx.state["mplan_attempts"] = ctx.state.get("mplan_attempts", 0) + 1
    author, note = "agent:planner", r.data.get("summary", "")[:800]
    if errs and n >= 3:  # the deterministic baseline always passes its own linter
        plan, author = base, "system:baseline"
        note = f"Baseline monitoring plan (the planner's drafts failed the linter: {'; '.join(errs[:3])})"
    elif errs:
        ctx.state["mplan_errors"] = errs
        return {"ok": False, "error": "plan rejected by the linter: " + "; ".join(errs[:10])}
    row = plans.save_draft(ctx.model_id, "monitoring", plan.model_dump(), author, note=note)
    ctx.state["mplan_errors"] = []
    return {"ok": True, "version": row.version, "rules": len(plan.rules), "panels": [p.title for p in plan.panels],
            "scenarios": [sc.title for sc in plan.scenarios], "rpm": plan.rpm, "source": r.source}


TOOLS = [
    Tool("get_spec", "The approved model specification", lambda ctx, a: _spec_brief(_spec(ctx)), summary=lambda r: "spec loaded",
         observe=lambda r: r),
    Tool("check_policies", "Apply the policy library (deterministic code rules) to the script; hits become findings", t_policies,
         summary=lambda r: f"{len(r)} policy hit(s): " + ", ".join(h["code"] for h in r),
         observe=lambda r: [{k: h[k] for k in ("code", "title", "severity", "line", "text")} for h in r]),
    Tool("review_code", "LLM code review as an independent validator; findings must cite a real line", t_review,
         {"focus": "what to look at, e.g. methodology, data handling, fairness"},
         summary=lambda r: f"{len(r['findings'])} finding(s), {r['dropped_unverifiable']} unverifiable dropped", observe=lambda r: r),
    Tool("lineage", "Which data and models this one depends on or feeds", lambda ctx, a: _lineage(ctx.model_id, _spec(ctx)),
         summary=lambda r: f"reads {len(r['reads'])}, downstream {r['downstream']}", observe=lambda r: r),
    Tool("draft_documentation", "Write the model documentation (SR 11-7 / SS1/23 structure) from the evidence", t_doc,
         {"instructions": "optional emphasis"}, summary=lambda r: f"{r['sections']} sections, {len(r['gaps'])} gap(s), completeness {r['completeness']}",
         observe=lambda r: r),
    Tool("draft_validation_plan", "Propose the model-specific validation plan (catalog metrics + thresholds); linted then saved", t_vplan,
         {"instructions": "what the plan must cover or fix"},
         summary=lambda r: f"validation plan v{r['version']}: {r['checks']} checks {r['by_category']}" if r.get("ok") else r.get("error", "")[:200],
         observe=lambda r: r),
    Tool("draft_monitoring_plan", "Propose KPIs, alert rules, dashboard panels and drift scenarios for this model; linted then saved", t_mplan,
         {"instructions": "what the plan must cover or fix"},
         summary=lambda r: f"monitoring plan v{r['version']}: {r['rules']} rules, {len(r['panels'])} panels, {len(r['scenarios'])} scenarios"
         if r.get("ok") else r.get("error", "")[:200], observe=lambda r: r),
]

ORDER = ["check_policies", "review_code", "draft_documentation", "draft_validation_plan", "draft_monitoring_plan"]


def _fallback(ctx: StageCtx) -> dict | None:
    ok = ctx.state.get("ok", {})
    nxt = next((t for t in ORDER if not ok.get(t)), None)
    return {"tool": nxt, "args": {}} if nxt else None


def _facts(ctx: StageCtx) -> dict:
    s = _spec(ctx)
    return {"model": ctx.model_id, "name": s.name, "task": s.task, "tier": s.tier, "strategy": s.strategy,
            "groups": [g.name for g in s.groups], "decision": s.decision.kind, "notes": s.notes[:5],
            "doc_gaps": (ctx.state.get("doc") or {}).get("gaps", [])[:5]}


AGENT = Agent(
    name="documentation", stage="document",
    goal="Document the model from evidence (policy rules, an independent code review, lineage), then propose the "
         "validation plan and the monitoring plan that fit THIS model's task, tier, decision rule and risks.",
    tools=TOOLS, mandatory=["check_policies", "draft_documentation", "draft_validation_plan", "draft_monitoring_plan"],
    facts=_facts, fallback=_fallback, max_steps=12)


def run(ctx: StageCtx) -> dict:
    c = run_agent(ctx, AGENT)
    doc = ctx.state.get("doc") or {}
    return {"conclusion": c, "gaps": doc.get("gaps", []), "completeness": doc.get("completeness")}
