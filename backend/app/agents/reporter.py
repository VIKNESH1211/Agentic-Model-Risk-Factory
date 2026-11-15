"""Report writer: assembles the validation report from the run's evidence; the LLM only drafts the executive summary.

Every number in the report is a {{m:run:metric}} token (resolved and clickable in the UI). The unsourced-number
checker rejects a summary with a raw number and the writer redrafts once; failing that, a rule-based summary is used.
"""
from __future__ import annotations

import json

from sqlmodel import select

from app import repositories as repo
from app.agents.common import StageCtx
from app.agents.runtime import Agent, Tool, ToolError, run as run_agent
from app.core import llm
from app.core.db import save, session
from app.domain.tables import Finding, Report, Run
from app.evidence import ledger, metric_store, tokens
from app.services import plans, prompts, specs

CATEGORY_ORDER = ["implementation", "performance", "calibration", "stability", "fairness", "data_quality", "policy"]
STATUS_ICON = {"pass": "✅ pass", "amber": "🟠 amber", "red": "🔴 red", "info": "ℹ️ info", "error": "⚠️ error"}


def _T(run_id: str, name: str) -> str:
    return "{{" + metric_store.token(run_id, name) + "}}"


def _threshold(run_id: str, r: dict) -> str:
    th, name = r.get("threshold"), r["metric_name"]
    if not th:
        return "—"
    parts = [f"{lvl} {th['op']} {_T(run_id, f'threshold.{name}.{lvl}')}" for lvl in ("amber", "red")
             if th.get(lvl) is not None and metric_store.get(run_id, f"threshold.{name}.{lvl}")]
    return " · ".join(parts) or "—"


def _findings(ctx: StageCtx) -> list[Finding]:
    """This run's findings; a re-validation also carries the code findings from the model's documentation."""
    doc_run = (repo.models.get(ctx.model_id).meta or {}).get("doc_run_id")
    with session() as sess:
        own = list(sess.exec(select(Finding).where(Finding.run_id == ctx.run_id)).all())
        if ctx.run.kind == "revalidation" and doc_run:
            own += [f for f in sess.exec(select(Finding).where(Finding.run_id == doc_run)).all()
                    if f.detector.startswith(("policy:", "llm_review"))]
    return own


def build(ctx: StageCtx, *, summary: str | None = None) -> Report:
    s = specs.current(ctx.model_id)
    m = repo.models.get(ctx.model_id)
    meta = m.meta or {}
    run_id = ctx.run_id
    checks = json.loads((ctx.dir / "validate" / "checks.json").read_text())
    results, summ, skipped = checks["results"], checks["summary"], checks.get("skipped", [])
    with session() as sess:
        run = sess.get(Run, run_id)
    all_f = _findings(ctx)
    rec = ctx.recorder()
    rec.const("findings.total", len(all_f), "Findings in this report")
    rec.const("findings.high", sum(f.severity == "high" for f in all_f), "High-severity findings")
    rec.const("findings.medium", sum(f.severity == "medium" for f in all_f), "Medium-severity findings")
    for k in ("pass", "amber", "red"):
        rec.const(f"checks.{k}", summ["counts"].get(k, 0), f"Plan checks with status {k}")
    rec.commit("report")
    pr = meta.get("parity_run_id")
    reval = ctx.run.kind == "revalidation"
    lines = [f"# Independent validation report — {ctx.model_id} {s.name}", "",
             f"**Overall rating: {summ['rating']}** · checks: {_T(run_id, 'checks.pass')} pass · {_T(run_id, 'checks.amber')} amber · "
             f"{_T(run_id, 'checks.red')} red · findings: {_T(run_id, 'findings.total')} ({_T(run_id, 'findings.high')} high)", ""]
    if reval:
        lines += [f"> Automatic re-validation on recent live traffic ({ctx.run.options.get('batch_label', 'live alert')}), "
                  f"compared with the baseline validation `{ctx.run.parent_run_id}`.", ""]
    lines += ["## Executive summary", "", summary or "_Pending._", "",
              "## Model and scope", "",
              f"| | |\n|---|---|\n| Model | `{ctx.model_id}` {s.name} |\n| Type / task | {s.model_type or '—'} · `{s.task}` |\n"
              f"| Tier | Tier {s.tier} — {s.tier_rationale or '—'} |\n| Owner | {s.owner or 'Not documented'} |\n"
              f"| Specification | `v{repo.specs.current(ctx.model_id).version}` · validation plan `v{checks.get('plan_version', '') or plans.current_row(ctx.model_id, 'validation').version}` |\n"
              f"| Decision rule | {s.decision.kind}{(' — adverse `' + s.decision.adverse_label + '` when score ' + s.decision.op + ' the coded cut-off') if s.decision.adverse_label else ''} |", ""]
    lines += ["## Implementation", ""]
    if meta.get("parity_verdict") == "PASS" and pr:
        bits = [f"maximum score difference {_T(pr, 'score_max_abs_diff')} over {_T(pr, 'rows_compared')} rows"]
        if metric_store.get(pr, "coef_max_abs_diff"):
            bits.append(f"coefficients within {_T(pr, 'coef_max_abs_diff')}")
        if metric_store.get(pr, "decision_agreement"):
            bits.append(f"decision agreement {_T(pr, 'decision_agreement')}")
        lines += [f"The legacy R code was run unmodified in a no-network sandbox and rebuilt in Python with **exact parity**: "
                  + ", ".join(bits) + f". Certificate run `{pr}`.", ""]
    else:
        lines += ["The model is **rehosted**: its legacy R outputs are validated as-is (no Python re-implementation).", ""]
    lines += ["## Results by category", ""]
    for cat in CATEGORY_ORDER:
        rows = [r for r in results if r["category"] == cat]
        if not rows:
            continue
        lines += [f"### {cat.replace('_', ' ').title()}", "", "| Check | Result | Limits | Status |", "|---|---|---|---|"]
        for r in rows:
            val = _T(run_id, r["metric_name"]) if r["value"] is not None else "n/a"
            lines.append(f"| {r['title']} | {val} | {_threshold(run_id, r)} | {STATUS_ICON.get(r['status'], r['status'])} |")
        lines.append("")
    if skipped:
        lines += ["Checks in the plan that could not run on this data: " + "; ".join(f"`{x['check']}`" for x in skipped), ""]
    lines += ["## Findings", ""]
    if all_f:
        lines += ["| Code | Severity | Finding | Source |", "|---|---|---|---|"]
        for f in sorted(all_f, key=lambda f: ({"high": 0, "medium": 1, "low": 2}.get(f.severity, 3), f.code)):
            lines.append(f"| `{f.code}` | {f.severity} | {f.title} | `{f.detector or 'validator'}` |")
    else:
        lines.append("No findings.")
    inv = (run.state.get("validate") or {}).get("investigations") or []
    lines += ["", "## Investigations by the validator agent", "",
              ("The agent chose to run: " + ", ".join(f"`{i}`" for i in dict.fromkeys(inv)) + ". Their measurements are in the evidence "
               "store and cited by the findings above.") if inv else "No additional investigation was needed beyond the plan.", ""]
    lines += ["## Limitations and notes", "", "- The `oot` sample is a SIMULATED out-of-time split (the data carries no dates).",
              "- Checks, thresholds and investigations follow the approved, versioned validation plan."]
    if s.notes:
        lines += ["", "Notes recorded in the model specification (quoted):", ""] + [f"> {n}  " for n in s.notes[:8]]
    md = "\n".join(lines)
    rid = f"rep_{run_id}"
    with session() as sess:
        old = sess.get(Report, rid)
        version = old.version if old else (len(sess.exec(select(Report).where(Report.model_id == ctx.model_id)).all()) + 1)
        if old:
            sess.delete(old)
            sess.commit()
    rep = save(Report(id=rid, run_id=run_id, model_id=ctx.model_id, version=version, title=f"Validation report — {ctx.model_id}",
                      markdown=md, checker=tokens.check(md), status="draft"))
    ledger.append("report", "report_drafted", {"run_id": run_id, "model_id": ctx.model_id, "report_id": rid,
                                               "checker_ok": rep.checker["ok"], "tokens": rep.checker["token_count"]})
    return rep


SUMMARY_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["summary"], "properties": {"summary": {"type": "string"}}}


def _rule_summary(ctx: StageCtx, checks: dict) -> str:
    rid = ctx.run_id
    bad = [r for r in checks["results"] if r["status"] in ("red", "amber")]
    s = (f"Independent validation of `{ctx.model_id}` concludes **{checks['summary']['rating']}**. "
         f"{_T(rid, 'checks.pass')} plan checks pass, {_T(rid, 'checks.amber')} are amber and {_T(rid, 'checks.red')} red.")
    if bad:
        s += " Main concerns: " + "; ".join(f"{r['title'].lower()} ({_T(rid, r['metric_name'])}, {r['status']})" for r in bad[:3]) + "."
    return s + f" The validator recorded {_T(rid, 'findings.total')} findings ({_T(rid, 'findings.high')} high)."


def t_write(ctx: StageCtx, args: dict) -> dict:
    if not (ctx.dir / "validate" / "checks.json").exists():
        raise ToolError("no validation results in this run")
    rep = build(ctx)  # records the summary metrics the LLM may cite
    checks = json.loads((ctx.dir / "validate" / "checks.json").read_text())
    rid = ctx.run_id
    res = [{"token": "{{" + metric_store.token(rid, r["metric_name"]) + "}}", "title": r["title"], "status": r["status"]}
           for r in checks["results"] if r["value"] is not None]
    fl = [{"code": f.code, "severity": f.severity, "title": f.title} for f in _findings(ctx)]
    extra = {"counts": {k: "{{" + metric_store.token(rid, f"checks.{k}") + "}}" for k in ("pass", "amber", "red")},
             "findings_total": "{{" + metric_store.token(rid, "findings.total") + "}}"}
    summary, attempts = None, 0
    for attempts in (1, 2):
        r = llm.complete_json(f"report_summary_try{attempts}", prompts.render(
            "report_summary", model_id=ctx.model_id, name=specs.current(ctx.model_id).name, rating=checks["summary"]["rating"],
            results=json.dumps(res[:40]), findings=json.dumps(fl[:12]),
            context=("Re-validation on recent live traffic. " if ctx.run.kind == "revalidation" else "") + "Count tokens: " + json.dumps(extra)),
            SUMMARY_SCHEMA, lambda: {"summary": ""}, run_id=rid, agent="report", spent=ctx.spent)
        chk = tokens.check(r.data.get("summary", ""))
        if r.data.get("summary") and chk["ok"]:
            summary = r.data["summary"]
            break
        ctx.step("observation", f"Summary draft {attempts} rejected by the unsourced-number checker "
                                f"({len(chk['violations'])} raw number(s), {len(chk['unknown_tokens'])} unknown token(s))",
                 {"violations": chk["violations"][:5]})
    source = "llm" if summary else "rule-based"
    rep = build(ctx, summary=summary or _rule_summary(ctx, checks))
    ctx.state.update(report_id=rep.id, checker=rep.checker)
    return {"report_id": rep.id, "checker_ok": rep.checker["ok"], "tokens": rep.checker["token_count"],
            "violations": len(rep.checker["violations"]), "summary_source": source, "drafts": attempts}


AGENT = Agent(
    name="report", stage="report",
    goal="Write the validation report: every number must be a traceable token; the summary must pass the unsourced-number checker.",
    tools=[Tool("write_report", "Assemble the report from the evidence and draft the executive summary (tokens only)", t_write,
                summary=lambda r: f"{r['report_id']} · {r['tokens']} traceable numbers · {r['violations']} unsourced · summary {r['summary_source']}",
                observe=lambda r: r)],
    mandatory=["write_report"], fallback=lambda ctx: None if ctx.state.get("ok", {}).get("write_report") else {"tool": "write_report", "args": {}},
    guard=lambda ctx: [] if (ctx.state.get("checker") or {}).get("ok", True) else ["the report contains unsourced numbers"], max_steps=4)


def run(ctx: StageCtx) -> dict:
    c = run_agent(ctx, AGENT)
    return {"conclusion": c, "report_id": ctx.state.get("report_id"), "checker_ok": (ctx.state.get("checker") or {}).get("ok")}
