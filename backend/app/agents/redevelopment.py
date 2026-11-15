"""Redevelopment agent: export the legacy model's behaviour, rebuild it in Python, prove exact parity.

Loop the agent drives (each arrow is a tool call it decides on):
  draft_export (LLM writes an R epilogue) → run_export (sandbox + bundle validator) ─ fails → read error, redraft
  → [translate] draft_translation (LLM writes Python) → check_parity (out-of-process) ─ gap → redraft with the gap
      → optional use_reference_translation (if one was uploaded) → certify
  → [rehost]    certify the legacy outputs as-is (validated, not re-implemented)
certify refuses unless parity passed (translate) or the strategy is rehost. Numbers go to the metric store.
"""
from __future__ import annotations

import json
import shutil

import numpy as np
import pandas as pd

from app import repositories as repo
from app.agents.common import StageCtx
from app.agents.intake import model_probe, probe_text
from app.agents.runtime import Agent, Tool, ToolError, run as run_agent
from app.core import llm, storage
from app.core.config import settings
from app.domain.schemas import ModelSpec
from app.engine import bundle as B
from app.engine import harness, parity, serving
from app.evidence import ledger
from app.services import onboarding, prompts, specs

CODE_SCHEMA_R = {"type": "object", "additionalProperties": False, "required": ["r_code", "explanation"],
                 "properties": {"r_code": {"type": "string"}, "explanation": {"type": "string"}}}
CODE_SCHEMA_PY = {"type": "object", "additionalProperties": False, "required": ["python_code", "notes"],
                  "properties": {"python_code": {"type": "string"}, "notes": {"type": "array", "items": {"type": "string"}}}}


def clean_code(code: str) -> str:
    """LLMs sometimes return code with escaped newlines (one long line) or inside a markdown fence."""
    code = (code or "").strip()
    if code.count("\n") == 0 and "\\n" in code:
        code = code.encode().decode("unicode_escape")
    if code.startswith("```"):
        code = code.split("\n", 1)[1] if "\n" in code else ""
        code = code.rsplit("```", 1)[0]
    return code.strip() + "\n"


def _spec(ctx: StageCtx) -> ModelSpec:
    if "spec" not in ctx.state:
        ctx.state["spec"] = specs.current(ctx.model_id)
    return ctx.state["spec"]


def _meta(model_id: str) -> dict:
    return (repo.models.get(model_id).meta or {})


def _set_meta(model_id: str, **kw) -> None:
    repo.models.update(model_id, meta={**_meta(model_id), **kw})


def _strategy(ctx: StageCtx) -> str:
    return ctx.state.get("strategy") or _spec(ctx).strategy


# ------------------------------------------------------------------ export (R side)
def t_draft_export(ctx: StageCtx, args: dict) -> dict:
    s = _spec(ctx)
    pinned = s.harness.epilogue.strip()
    if pinned and not ctx.state.get("pinned_tried"):
        ctx.state.update(epilogue=pinned, pinned_tried=True, epilogue_source="pinned in the spec", export_tried=False)
        return {"source": "pinned in the spec", "lines": pinned.count("\n") + 1}
    last = _meta(ctx.model_id).get("export_epilogue")
    if last and not ctx.state.get("last_tried") and last.get("spec_version") == repo.specs.current(ctx.model_id).version:
        ctx.state.update(epilogue=last["code"], last_tried=True, epilogue_source="reused from the last certified export",
                         export_tried=False)
        return {"source": "reused from the last certified export", "lines": last["code"].count("\n") + 1}
    name, text = onboarding.script_text(ctx.model_id, s.entry_script)
    prev = ctx.state.get("export_error")
    previous = (f"Your previous epilogue failed:\n{prev}\nPrevious epilogue:\n{ctx.state.get('epilogue', '')}") if prev else ""
    r = llm.complete_json("epilogue_draft", prompts.render(
        "epilogue_draft", model_id=ctx.model_id, bundle_spec=B.SPEC_TEXT,
        spec=json.dumps({k: v for k, v in s.model_dump().items() if k not in ("harness", "notes")}, default=str)[:2500],
        probe=probe_text(model_probe(ctx.model_id)), instructions=args.get("instructions") or "none", previous=previous),
        CODE_SCHEMA_R, lambda: {"r_code": "", "explanation": ""}, run_id=ctx.run_id, agent="redevelopment",
        untrusted={name: text}, spent=ctx.spent)
    code = clean_code(r.data.get("r_code") or "").strip()
    if not code:
        raise ToolError(f"no epilogue drafted ({r.source}); a language model is required")
    n = ctx.state["export_drafts"] = ctx.state.get("export_drafts", 0) + 1
    (ctx.dir / f"epilogue_{n}.R").write_text(code)
    ctx.state.update(epilogue=code, epilogue_source=f"LLM draft {n} ({r.source})", export_tried=False)
    return {"source": f"LLM draft {n}", "lines": code.count("\n") + 1, "explanation": r.data.get("explanation", "")[:400]}


def t_run_export(ctx: StageCtx, args: dict) -> dict:
    code = ctx.state.get("epilogue")
    if not code:
        raise ToolError("no epilogue yet — call draft_export first")
    s = _spec(ctx)
    ctx.state["export_tried"] = True
    r = harness.run(ctx.model_id, s, ctx.dir / "sandbox", epilogue=code)
    if not r.ok:
        ctx.state["export_error"] = f"R error ({r.mode}):\n{r.error or r.stderr[-800:]}"
        return {"ok": False, "error": ctx.state["export_error"]}
    errs = B.validate(r.out_dir)
    if errs:
        ctx.state["export_error"] = "The export ran but the bundle is invalid:\n- " + "\n- ".join(errs)
        return {"ok": False, "error": ctx.state["export_error"]}
    dest = B.store(r.out_dir, ctx.dir / "bundle")
    b = B.load(dest)
    for name in B.BUNDLE_FILES:
        if (dest / name).exists():
            ctx.artifact(f"bundle_{name.split('.')[0]}", dest / name)
    (ctx.dir / "epilogue.R").write_text(code)
    ctx.artifact("export_epilogue", ctx.dir / "epilogue.R")
    ctx.state.update(bundle_dir=str(dest), export_error=None, legacy_mode=r.mode, legacy_elapsed=r.elapsed_s,
                     parity=None if ctx.state.get("candidate_path") else ctx.state.get("parity"))
    return {"ok": True, "mode": r.mode, "elapsed_s": round(r.elapsed_s, 2), **b.summary()}


def t_inspect(ctx: StageCtx, args: dict) -> dict:
    if not ctx.state.get("bundle_dir"):
        raise ToolError("no export yet — run_export must succeed first")
    b = B.load(ctx.state["bundle_dir"])
    f = b.frame
    return {"rows": b.n, "dtypes": {c: str(f[c].dtype) for c in list(f.columns)[:50]},
            "head": json.loads(f.head(3).to_json(orient="records")), "score": b.scores["score"].describe().round(6).to_dict(),
            "decisions": b.scores["decision"].value_counts().head(6).to_dict() if "decision" in b.scores else None,
            "coef": None if b.coef is None else b.coef.head(12).round(6).to_dict(),
            "train_rows": None if b.train_rows is None else len(b.train_rows)}


# ------------------------------------------------------------------ translation (Python side)
def _frame_text(b: B.Bundle) -> str:
    f = b.frame
    cols = [f"{c} ({f[c].dtype}; e.g. {', '.join(map(str, f[c].dropna().unique()[:3]))}; {int(f[c].isna().sum())} NA)" for c in f.columns]
    return (f"{b.n} rows; train_rows: {'all rows / not fitted' if b.train_rows is None else f'{len(b.train_rows)} rows'}\n"
            + "\n".join(cols[:60]))


def t_choose(ctx: StageCtx, args: dict) -> dict:
    st = args.get("strategy")
    if st not in ("translate", "rehost"):
        raise ToolError("strategy must be 'translate' or 'rehost'")
    ctx.state["strategy"] = st
    ctx.state["strategy_reason"] = args.get("reason", "")
    ctx.think(f"Strategy: {st} — {args.get('reason', '')}")
    return {"strategy": st}


def _require_translate(ctx: StageCtx) -> None:
    if _strategy(ctx) == "rehost":
        raise ToolError("the approved strategy is REHOST: do not translate — call certify to certify the legacy outputs as-is. "
                        "(Only if you have strong evidence the model can be reproduced exactly, call choose_strategy first; "
                        "a human must then confirm the change.)")


def t_draft_translation(ctx: StageCtx, args: dict) -> dict:
    _require_translate(ctx)
    if not ctx.state.get("bundle_dir"):
        raise ToolError("run_export must succeed first — the translation is checked against its output")
    s = _spec(ctx)
    b = B.load(ctx.state["bundle_dir"])
    name, text = onboarding.script_text(ctx.model_id, s.entry_script)
    gap = ctx.state.get("parity_problems")
    previous = ""
    if gap:
        previous = "Your previous translation failed the parity check:\n- " + "\n- ".join(gap)
        if gap == ctx.state.get("parity_problems_before"):
            previous += ("\nIMPORTANT: your last revision produced EXACTLY the same failure — the change did not touch the "
                         "cause. Rewrite the failing function from scratch with a different approach.")
        ln = next((int(x.split("at line ")[1].split()[0]) for x in gap if "at line " in x), None)
        if ln and ctx.state.get("candidate"):
            lines = ctx.state["candidate"].splitlines()
            ctx_lines = "\n".join(f"{i:>4}| {lines[i - 1]}" for i in range(max(1, ln - 6), min(len(lines), ln + 4) + 1))
            previous += f"\nCode around the failing line:\n{ctx_lines}"
        previous += ("\nREPAIR RULES (strict): you MUST return the COMPLETE corrected module; you MUST fix the root cause of "
                     "every problem listed above (not just silence the error); you MUST NOT change anything that already "
                     "matched; you MUST follow the R → Python equivalents above for the failing operation. If the same "
                     "approach failed before, use a DIFFERENT, simpler approach (e.g. a dict + Series.map lookup).")
    sc = b.scores.head(5).to_dict(orient="records")
    r = llm.complete_json("translation_draft", prompts.render(
        "translation_draft", model_id=ctx.model_id, contract=parity.CONTRACT,
        spec=json.dumps({k: v for k, v in s.model_dump().items() if k not in ("harness",)}, default=str)[:2500],
        frame=_frame_text(b), scores=json.dumps(sc, default=str), coef="none" if b.coef is None else json.dumps(b.coef.round(8).to_dict()),
        instructions=args.get("instructions") or "none", previous=previous),
        CODE_SCHEMA_PY, lambda: {"python_code": "", "notes": []}, run_id=ctx.run_id, agent="redevelopment",
        untrusted={name: text, "epilogue.R": ctx.state.get("epilogue", ""),
                   **({"previous_translation.py": ctx.state["candidate"]} if gap and ctx.state.get("candidate") else {})},
        spent=ctx.spent)
    code = clean_code(r.data.get("python_code") or "").strip()
    if not code:
        raise ToolError(f"no translation drafted ({r.source}); a language model is required")
    n = ctx.state["translation_drafts"] = ctx.state.get("translation_drafts", 0) + 1
    p = ctx.dir / f"candidate_{n}.py"
    p.write_text(code)
    ctx.state.update(candidate=code, candidate_path=str(p), candidate_source=f"LLM draft {n} ({r.source})", parity=None)
    return {"draft": n, "lines": code.count("\n") + 1, "notes": r.data.get("notes", [])[:6]}


def t_reference(ctx: StageCtx, args: dict) -> dict:
    ref = onboarding.files_of(ctx.model_id, "reference")
    if not ref:
        raise ToolError("no reference translation was uploaded with this model")
    code = storage.read_text(ref[0].sha256)
    p = ctx.dir / "candidate_reference.py"
    p.write_text(code)
    ctx.state.update(candidate=code, candidate_path=str(p), candidate_source=f"uploaded reference ({ref[0].name})", parity=None,
                     reference_used=True)
    return {"file": ref[0].name, "lines": code.count("\n") + 1}


def t_parity(ctx: StageCtx, args: dict) -> dict:
    _require_translate(ctx)
    if not ctx.state.get("candidate_path"):
        raise ToolError("no candidate translation — call draft_translation first")
    res = parity.check(ctx.state["candidate_path"], ctx.state["bundle_dir"], ctx.dir / "parity")
    ctx.state["parity"] = res
    ctx.state["parity_attempts"] = ctx.state.get("parity_attempts", 0) + 1
    if not res.get("ok"):
        ctx.state["parity_problems_before"] = ctx.state.get("parity_problems")
        ctx.state["parity_problems"] = res.get("problems", [])
        ledger.append("redevelopment", "parity_failed", {"run_id": ctx.run_id, "model_id": ctx.model_id,
                                                         "source": ctx.state.get("candidate_source"), "problems": res.get("problems", [])[:4]})
        return {"ok": False, "error": "parity failed: " + " | ".join(res.get("problems", []))[:900]}
    ctx.state["parity_problems"] = None
    return {"ok": True, **{k: res.get(k) for k in ("score_max_abs_diff", "coef_max_abs_diff", "decision_agreement", "rows_compared")}}


# ------------------------------------------------------------------ certificate
def t_certify(ctx: StageCtx, args: dict) -> dict:
    if not ctx.state.get("bundle_dir"):
        raise ToolError("cannot certify: no valid export bundle")
    s = _spec(ctx)
    st = _strategy(ctx)
    rec = ctx.recorder()
    rel = ctx.rel
    b = B.load(ctx.state["bundle_dir"])
    rec.const("legacy_runtime_s", ctx.state.get("legacy_elapsed", 0.0), "Measured seconds to run the legacy R code in the sandbox")
    if st == "rehost":
        verdict = "REHOSTED"
        rec.const("rows_scored", float(b.scores["score"].notna().sum()), "Rows the legacy code scored (rehosted, not re-implemented)")
    else:
        res = ctx.state.get("parity") or {}
        if not res.get("ok"):
            raise ToolError("cannot certify: the last parity check did not pass" + (f" ({'; '.join(res.get('problems', [])[:2])})" if res else ""))
        shutil.copy(ctx.state["candidate_path"], ctx.dir / "model.py")
        ctx.artifact("python_model", ctx.dir / "model.py")
        ctx.artifact("parity_scores", ctx.dir / "parity" / "parity_scores.csv")
        rec.measure("score_max_abs_diff", {"fn": "max_abs_diff", "artifact": f"{rel}/parity/parity_scores.csv", "a": "legacy_score", "b": "py_score"},
                    definition="Largest absolute difference between legacy R and Python scores over every row")
        rec.measure("rows_compared", {"fn": "count_true", "artifact": f"{rel}/parity/parity_scores.csv", "col": "both_scored"},
                    definition="Rows scored by both implementations")
        if "decision_agreement" in res and res["decision_agreement"] is not None:
            rec.measure("decision_agreement", {"fn": "rate_true", "artifact": f"{rel}/parity/parity_scores.csv", "col": "decision_agree"},
                        definition="Share of rows where legacy and Python decisions agree")
        if (ctx.dir / "parity" / "parity_coef.csv").exists():
            rec.measure("coef_max_abs_diff", {"fn": "max_abs_diff", "artifact": f"{rel}/parity/parity_coef.csv", "a": "legacy", "b": "python"},
                        definition="Largest absolute difference between legacy and Python coefficients")
        verdict = "PASS"
    rec.commit("parity")
    cert = {"model_id": ctx.model_id, "run_id": ctx.run_id, "verdict": verdict, "strategy": st,
            "spec_version": repo.specs.current(ctx.model_id).version, "implementation": ctx.state.get("candidate_source", "legacy R (rehosted)"),
            "export": ctx.state.get("epilogue_source"), "legacy_run": ctx.state.get("legacy_mode"),
            "bundle": b.summary(), "parity": {k: v for k, v in (ctx.state.get("parity") or {}).items() if k != "problems"},
            "tolerances": {"scores": 1e-6, "coefficients": 1e-6},
            "attempts": {"export": ctx.state.get("export_drafts", 0), "translation": ctx.state.get("translation_drafts", 0)},
            "reason": ctx.state.get("strategy_reason", "")}
    cert["fingerprint"] = __import__("hashlib").sha256(json.dumps(cert, sort_keys=True, default=str).encode()).hexdigest()
    (ctx.dir / "parity_certificate.json").write_text(json.dumps(cert, indent=2, default=str))
    ctx.artifact("parity_certificate", ctx.dir / "parity_certificate.json")
    ledger.append("redevelopment", "parity_certificate_issued", {"run_id": ctx.run_id, "model_id": ctx.model_id, "verdict": verdict,
                                                                 "fingerprint": cert["fingerprint"]})
    _set_meta(ctx.model_id, export_epilogue={"code": ctx.state["epilogue"], "run_id": ctx.run_id,
                                             "spec_version": repo.specs.current(ctx.model_id).version},
              parity_run_id=ctx.run_id, parity_verdict=verdict, parity_fingerprint=cert["fingerprint"],
              strategy=st, deployable=bool(s.deployable and verdict == "PASS"), status="redeveloped")
    serving.invalidate(ctx.model_id)
    ctx.state["certified"] = verdict
    return {"verdict": verdict, "fingerprint": cert["fingerprint"][:16]}


TOOLS = [
    Tool("draft_export", "Write (or reuse) the R epilogue that exports the standard bundle from the legacy run", t_draft_export,
         {"instructions": "what the epilogue must do or fix"}, summary=lambda r: f"epilogue: {r['source']}, {r['lines']} lines",
         observe=lambda r: r),
    Tool("run_export", "Run the unmodified legacy script + the epilogue in the sandbox, then validate the bundle", t_run_export,
         summary=lambda r: (f"bundle OK: {r['rows']} rows, {r['scored']} scored, decision={r['has_decision']}, "
                            f"coef={r['coefficients']}, train_rows={r['train_rows']} ({r['mode']})") if r.get("ok") else r["error"][:220],
         observe=lambda r: r),
    Tool("inspect_export", "Look at the exported frame, scores, decisions and coefficients", t_inspect,
         summary=lambda r: f"{r['rows']} rows, {len(r['dtypes'])} columns", observe=lambda r: r),
    Tool("choose_strategy", "Change the approved strategy (translate ⇄ rehost). Only when the model truly cannot be reproduced "
         "exactly (e.g. tree ensembles); a change always sends the model back to a human",
         t_choose, {"strategy": "translate | rehost", "reason": "why"}, summary=lambda r: r["strategy"], observe=lambda r: r),
    Tool("draft_translation", "Write the Python translation (LegacyModel) — after a failed parity check it is fed the exact gap",
         t_draft_translation, {"instructions": "what to get right or fix"},
         summary=lambda r: f"draft {r['draft']}: {r['lines']} lines", observe=lambda r: r),
    Tool("check_parity", "Run the candidate out-of-process against the legacy export: every row, coefficients, decisions, single-row scoring",
         t_parity, summary=lambda r: ("parity PASS · max score diff " + f"{r['score_max_abs_diff']:.2g}") if r.get("ok") else r["error"][:220],
         observe=lambda r: r),
    Tool("use_reference_translation", "Use the reference translation uploaded with the model (still must pass check_parity)",
         t_reference, summary=lambda r: f"reference {r['file']} loaded", observe=lambda r: r),
    Tool("certify", "Issue the parity certificate (refused unless parity passed, or the strategy is rehost)", t_certify,
         summary=lambda r: f"certificate {r['verdict']} · {r['fingerprint']}", observe=lambda r: r),
]


def _fallback(ctx: StageCtx) -> dict | None:
    ok = ctx.state.get("ok", {})
    if not ok.get("run_export"):
        if ctx.state.get("export_drafts", 0) + (1 if ctx.state.get("pinned_tried") else 0) >= 4 and ctx.state.get("export_tried"):
            return None
        if ctx.state.get("epilogue") and not ctx.state.get("export_tried"):
            return {"tool": "run_export", "args": {}}
        return {"tool": "draft_export", "args": {}}
    if ok.get("certify"):
        return None
    if _strategy(ctx) == "rehost":
        return {"tool": "certify", "args": {}}
    p = ctx.state.get("parity")
    if p and p.get("ok"):
        return {"tool": "certify", "args": {}}
    if ctx.state.get("candidate_path") and p is None:
        return {"tool": "check_parity", "args": {}}
    if ctx.state.get("translation_drafts", 0) >= 3:
        if onboarding.files_of(ctx.model_id, "reference") and not ctx.state.get("reference_used"):
            return {"tool": "use_reference_translation", "args": {}}
        return None
    return {"tool": "draft_translation", "args": {}}


def _facts(ctx: StageCtx) -> dict:
    s = _spec(ctx)
    p = ctx.state.get("parity") or {}
    return {"model": ctx.model_id, "task": s.task, "APPROVED_STRATEGY": _strategy(ctx),
            "what_to_do": "export, then certify (no translation)" if _strategy(ctx) == "rehost" else "export, translate, check parity, certify",
            "entry_script": s.entry_script,
            "reference_translation_uploaded": bool(onboarding.files_of(ctx.model_id, "reference")),
            "export_ok": bool(ctx.state.get("bundle_dir")), "export_error": (ctx.state.get("export_error") or "")[:600],
            "translation_drafts": ctx.state.get("translation_drafts", 0), "parity_ok": p.get("ok"),
            "parity_problems": (p.get("problems") or [])[:4], "certified": ctx.state.get("certified"),
            "hint": ("several translation drafts failed parity — consider use_reference_translation, or redraft the export "
                     "if the problem is in train_rows / the frame") if ctx.state.get("translation_drafts", 0) >= 3 else ""}


def _guard(ctx: StageCtx) -> list[str]:
    out = [] if ctx.state.get("certified") else ["no parity certificate issued"]
    if ctx.state.get("strategy") and ctx.state["strategy"] != _spec(ctx).strategy:
        out.append(f"the agent changed the approved strategy from {_spec(ctx).strategy} to {ctx.state['strategy']} "
                   f"({ctx.state.get('strategy_reason') or 'no reason given'}) — a human must confirm")
    return out


AGENT = Agent(
    name="redevelopment", stage="redevelop",
    goal="Export the legacy model's exact behaviour from the sandbox (standard bundle), then rebuild it in Python and prove "
         "exact parity — or, if the model cannot be reproduced exactly (e.g. random forests), rehost it — and certify.",
    tools=TOOLS, mandatory=["run_export", "certify"], facts=_facts, fallback=_fallback, guard=_guard, max_steps=18,
    max_failures=5)


def run(ctx: StageCtx) -> dict:
    c = run_agent(ctx, AGENT)
    return {"conclusion": c, "verdict": ctx.state.get("certified"), "implementation": ctx.state.get("candidate_source")}
