"""Intake agent: works out what an uploaded R model is and how to run it, and drafts its specification.

Tools are deterministic (parse, data-room listing, sandbox probe, spec linter) except draft_spec, which asks the
LLM to write the spec from the evidence the agent gathered. The spec is only saved once it passes the linter.
"""
from __future__ import annotations

import json
from pathlib import PurePath

import pandas as pd

from app import repositories as repo
from app.agents.common import StageCtx
from app.agents.runtime import Agent, Tool, ToolError, run as run_agent
from app.core import llm
from app.domain.schemas import InputMap, ModelSpec
from app.engine import harness
from app.services import onboarding, prompts, specs
from app.tools.parsers import r_parser


# ------------------------------------------------------------------ shared helpers (used by later stages too)
def probe_summary(out_dir) -> dict:
    """Compact view of the sandbox probe: objects and data-frame columns."""
    objs = pd.read_csv(out_dir / "probe_objects.csv").fillna("")
    cols = pd.read_csv(out_dir / "probe_columns.csv").fillna("")
    frames = {}
    for name, g in cols.groupby("object", sort=False):
        frames[name] = [{"column": r["column"], "class": r["class"], "missing": int(r["missing"]), "unique": int(r["unique"]),
                         "example": str(r["example"])[:40]} for _, r in g.iterrows()]
    return {"objects": [{"name": r["name"], "class": r["class"], "detail": str(r["detail"])[:240]} for _, r in objs.iterrows()],
            "frames": frames}


def probe_text(probe: dict, max_cols: int = 40) -> str:
    lines = []
    for o in probe.get("objects", []):
        if o["class"] in ("function",) and len(probe["objects"]) > 30:
            continue
        lines.append(f"- {o['name']} <{o['class']}> {o['detail']}")
    for f, cols in probe.get("frames", {}).items():
        shown = ", ".join(f"{c['column']}({c['class']}{', ' + str(c['missing']) + ' NA' if c['missing'] else ''})" for c in cols[:max_cols])
        lines.append(f"  data frame {f}: {shown}{' …' if len(cols) > max_cols else ''}")
    return "\n".join(lines)


def probe_columns(probe: dict) -> set[str]:
    return {c["column"] for cols in probe.get("frames", {}).values() for c in cols}


def data_room_text(max_cols: int = 30) -> str:
    rows = []
    for a in repo.assets.list(is_current=True):
        cols = [c["name"] for c in a.profile.get("columns", [])]
        rows.append(f"- {a.name} ({a.rows:,} rows): {', '.join(cols[:max_cols])}{' …' if len(cols) > max_cols else ''}"
                    + (f"  [{a.provenance}]" if a.provenance else ""))
    return "\n".join(rows) or "(empty)"


def model_probe(model_id: str) -> dict:
    m = repo.models.get(model_id)
    return ((m.meta or {}).get("probe") or {}) if m else {}


def _set_meta(model_id: str, **kw) -> None:
    m = repo.models.get(model_id)
    repo.models.update(model_id, meta={**(m.meta or {}), **kw})


# ------------------------------------------------------------------ tools
def t_read_script(ctx: StageCtx, args: dict) -> dict:
    name, text = onboarding.script_text(ctx.model_id, args.get("file"))
    p = r_parser.parse_text(text, name)
    ctx.state["script"] = (name, text)
    ctx.state["parse"] = {k: p[k] for k in ("header", "reads", "writes", "libraries", "methods", "loc")}
    ctx.state["parse"]["injection"] = p["injection"]
    _set_meta(ctx.model_id, parse={**ctx.state["parse"], "smells": len(p["smells"]), "code_hash": p["code_hash"]},
              hero=False)
    return {"file": name, **ctx.state["parse"], "injection_flags": len(p["injection"])}


def t_list_data_room(ctx: StageCtx, args: dict) -> str:
    return data_room_text()


def _probe_spec(ctx: StageCtx, args: dict) -> ModelSpec:
    name = args.get("script") or (ctx.state.get("script") or onboarding.script_text(ctx.model_id))[0]
    raw_inputs = args.get("inputs") or []
    inputs = [InputMap(ref=i["ref"], asset=i["asset"]) for i in raw_inputs if isinstance(i, dict) and i.get("ref") and i.get("asset")]
    a = [str(x) for x in (args.get("args") or [])]
    return ModelSpec(entry_script=name, inputs=inputs, harness={"args": a})


def t_probe(ctx: StageCtx, args: dict) -> dict:
    spec = _probe_spec(ctx, args)
    bad = [m.asset for m in spec.inputs if repo.current_asset(m.asset) is None]
    if bad:
        raise ToolError(f"unknown data-room asset(s) {bad}; available: {[a.name for a in repo.assets.list(is_current=True)]}")
    r = harness.run(ctx.model_id, spec, ctx.dir / "probe")
    if not r.ok:
        raise ToolError(f"the legacy script failed in the sandbox ({r.mode}): {r.error or r.stderr[-600:]}\n"
                        "Fix the arguments or input mapping (files referenced by relative path are copied into the "
                        "working directory; //shared/riskdata/<asset> is always available).")
    probe = probe_summary(r.out_dir)
    probe.update({"args": spec.harness.args, "inputs": [m.model_dump() for m in spec.inputs], "mode": r.mode,
                  "stdout": r.stdout[-800:]})
    ctx.state["probe"] = probe
    _set_meta(ctx.model_id, probe=probe)
    return {"ok": True, "mode": r.mode, "elapsed_s": round(r.elapsed_s, 1), "objects": len(probe["objects"]),
            "data_frames": {k: len(v) for k, v in probe["frames"].items()}, "text": probe_text(probe)}


SPEC_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["spec", "notes_for_reviewer"],
               "properties": {"spec": {"type": "object"}, "notes_for_reviewer": {"type": "string"}}}


def t_draft_spec(ctx: StageCtx, args: dict) -> dict:
    probe = ctx.state.get("probe") or model_probe(ctx.model_id)
    if not probe:
        raise ToolError("probe the legacy script first so the spec can be based on the objects it creates")
    name, text = ctx.state.get("script") or onboarding.script_text(ctx.model_id)
    m = repo.models.get(ctx.model_id)
    prev = ctx.state.get("spec_errors")
    previous = (f"Your previous draft was rejected by the linter:\n- " + "\n- ".join(prev) +
                (f"\nAgent instructions: {args.get('instructions')}" if args.get("instructions") else "")) if prev else \
               (f"Agent instructions: {args.get('instructions')}" if args.get("instructions") else "")
    prompt = prompts.render(
        "intake_spec", description=m.description or "(nothing)",
        files=", ".join(f"{f.name} ({f.role})" for f in onboarding.files_of(ctx.model_id)),
        data_room=data_room_text(), parse=json.dumps(ctx.state.get("parse") or {}, default=str)[:1500],
        probe=probe_text(probe), args=json.dumps(probe.get("args", [])), previous=previous,
        schema=json.dumps(ModelSpec.model_json_schema())[:6000])
    r = llm.complete_json("intake_spec", prompt, SPEC_SCHEMA, lambda: {"spec": {}, "notes_for_reviewer": ""},
                          run_id=ctx.run_id, agent="intake", untrusted={name: text}, spent=ctx.spent)
    if not r.data.get("spec"):
        raise ToolError(f"no spec drafted ({r.source}); a language model is required for intake")
    try:
        spec = specs.parse(r.data["spec"])
    except specs.SpecError as e:
        ctx.state["spec_errors"] = [str(e)]
        raise ToolError(f"spec does not match the schema: {e}")
    if not spec.entry_script:
        spec.entry_script = name
    if not spec.harness.args and probe.get("args"):
        spec.harness.args = probe["args"]
    spec, fixes = specs.autofix(spec, text)
    for f in fixes:
        ctx.step("observation", f"Spec auto-fix: {f}")
    errs = specs.lint(ctx.model_id, spec, probe_columns(probe), probe.get("objects"))
    if errs:
        ctx.state["spec_errors"] = errs
        return {"ok": False, "error": "spec rejected by the linter: " + "; ".join(errs)}
    note = r.data.get("notes_for_reviewer", "")[:900] + (f" [auto-fixed: {'; '.join(fixes)}]" if fixes else "")
    row = specs.save_draft(ctx.model_id, spec, "agent:intake", note=note)
    ctx.state["spec_errors"] = []
    ctx.state["spec_version"] = row.version
    return {"ok": True, "version": row.version, "task": spec.task, "strategy": spec.strategy, "target": spec.target,
            "features": len(spec.features), "groups": [g.name for g in spec.groups], "tier": spec.tier,
            "decision": spec.decision.model_dump(), "notes": r.data.get("notes_for_reviewer", "")[:300]}


TOOLS = [
    Tool("read_script", "Static parse of the uploaded R script: header, files read/written, libraries, methods, injection flags",
         t_read_script, {"file": "optional script file name"},
         summary=lambda r: f"{r['file']}: {r['loc']} lines, reads {r['reads'] or 'no files'}, {r['injection_flags']} injection flag(s)",
         observe=lambda r: r),
    Tool("list_data_room", "Files on the shared drive (data room) with their columns", t_list_data_room,
         summary=lambda r: f"{r.count(chr(10)) + 1} asset(s)", observe=lambda r: r),
    Tool("probe_legacy", "Run the UNMODIFIED script in the no-network sandbox and list every object it leaves behind "
         "(data frames + columns, fitted models + formulas)", t_probe,
         {"args": "list of command-line arguments the batch job passes ([] if none)",
          "inputs": "list of {ref, asset}: each file the script reads, mapped to a data-room asset",
          "script": "optional entry script name"},
         summary=lambda r: f"{r['objects']} objects, data frames {r['data_frames']} ({r['mode']})", observe=lambda r: r["text"]),
    Tool("draft_spec", "Ask the LLM to write the model specification from the evidence gathered; it is linted and saved as a draft",
         t_draft_spec, {"instructions": "what to pay attention to or fix"},
         summary=lambda r: (f"spec v{r['version']} saved · {r['task']} · {r['strategy']} · target {r['target']} · tier {r['tier']}"
                            if r.get("ok") else r.get("error", "rejected")[:200]),
         observe=lambda r: r),
]


def _fallback(ctx: StageCtx) -> dict | None:
    ok = ctx.state.get("ok", {})
    if not ok.get("read_script"):
        return {"tool": "read_script", "args": {}}
    if not ok.get("probe_legacy"):
        reads = (ctx.state.get("parse") or {}).get("reads", [])
        names = {a.name for a in repo.assets.list(is_current=True)}
        return {"tool": "probe_legacy", "args": {"args": [], "inputs": [{"ref": r, "asset": PurePath(r).name} for r in reads
                                                                         if PurePath(r).name in names]}}
    if not ok.get("draft_spec"):
        return {"tool": "draft_spec", "args": {}}
    return None


def _facts(ctx: StageCtx) -> dict:
    m = repo.models.get(ctx.model_id)
    return {"model": ctx.model_id, "uploader_notes": m.description, "files": [f.name for f in onboarding.files_of(ctx.model_id)],
            "data_room": [a.name for a in repo.assets.list(is_current=True)],
            "probe_done": bool(ctx.state.get("probe")), "spec_errors": ctx.state.get("spec_errors", [])}


AGENT = Agent(
    name="intake", stage="discover",
    goal="Understand the uploaded legacy R model well enough to run it unmodified in the sandbox, then draft a "
         "specification (task, inputs, target, features, fairness groups, decision rule, tier, strategy) that passes the linter.",
    tools=TOOLS, mandatory=["read_script", "probe_legacy", "draft_spec"], facts=_facts, fallback=_fallback, max_steps=10)


def run(ctx: StageCtx) -> dict:
    c = run_agent(ctx, AGENT)
    row = repo.specs.latest(ctx.model_id)
    return {"conclusion": c, "spec_version": row.version if row else None,
            "summary": f"Spec v{row.version} drafted" if row else "No spec drafted"}
