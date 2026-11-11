"""Validation report for the non-scorecard estate: sections appear only for metrics this model has."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlmodel import func, select

from app.agents.common import StageCtx
from app.core import llm
from app.core.db import save, session
from app.domain.tables import Finding, Model, Report
from app.evidence import ledger, metric_store, tokens
from app.evidence.report_builder import SEV_ORDER, rating
from app.modelkit import registry as R

LABELS = {
    "gini.train": "Gini — train", "gini.test": "Gini — test", "gini.oot": "Gini — out-of-time (simulated)",
    "ks.oot": "KS — out-of-time", "auc.holdout": "AUC — hold-out", "brier.holdout": "Brier score — hold-out",
    "calibration_ratio.holdout": "Predicted ÷ observed — hold-out", "bad_rate.holdout": "Observed outcome rate — hold-out",
    "approval_rate.holdout": "Approval rate at coded cutoff", "recall_at.holdout": "Recall at coded threshold",
    "precision_at.holdout": "Precision at coded threshold", "avg_precision.holdout": "Average precision (PR-AUC)",
    "alert_rate.holdout": "Alert rate", "ae_ratio.holdout": "Actual ÷ expected claims — hold-out",
    "dev_explained.holdout": "Poisson deviance explained — hold-out", "decline_zero_share": "Declines with zero limit",
    "max_limit": "Largest limit granted", "cap_share": "Share of limits at the cap", "limit_ratio_monotone": "Limit falls as risk rises (yes/no flag)",
    "approval_rate.all": "Share granted a limit", "upstream_high_findings": "Open high findings on CR-001 (upstream)",
    "gini.champion.holdout": "Champion Gini — hold-out", "gini.challenger.holdout": "Challenger Gini — hold-out",
}


def build(ctx: StageCtx, a: R.Adapter, *, parity_run_id: str | None, revalidation_of: str | None = None,
          drift_label: str | None = None) -> Report:
    rid = ctx.run_id
    with session() as s:
        model = s.get(Model, a.id)
        findings = sorted(s.exec(select(Finding).where(Finding.run_id == rid)).all(), key=lambda f: (SEV_ORDER.get(f.severity, 9), f.code))
        version = s.exec(select(func.count()).select_from(Report).where(Report.model_id == a.id)).one() + 1
    rec = ctx.recorder()
    for sev in ("high", "medium", "low"):
        rec.const(f"findings.{sev}", sum(f.severity == sev for f in findings), f"Number of {sev}-severity findings")
    rec.const("findings.total", len(findings), "Number of findings")
    rec.commit("report counts")
    have = {m.name: m for m in metric_store.for_run(rid)}
    T = lambda n: "{{" + metric_store.token(rid, n) + "}}"  # noqa: E731
    P = (lambda n: "{{" + metric_store.token(parity_run_id, n) + "}}") if parity_run_id else None
    pm = {m.name for m in metric_store.for_run(parity_run_id)} if parity_run_id else set()
    verdict = rating(findings)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    top = [{"code": f.code, "severity": f.severity, "title": f.title} for f in findings[:5]]

    facts = {n: {"token": T(n), "value": round(have[n].value, 6), "meaning": LABELS.get(n, have[n].definition)}
             for n in list(LABELS) + ["findings.high", "findings.medium", "findings.total"] if n in have}
    if P:
        facts.update({f"parity.{n}": {"token": P(n), "meaning": "parity vs legacy: " + n} for n in pm if n in
                      ("score_max_abs_diff", "coef_max_abs_diff", "rows_compared", "rows_scored")})

    def offline():
        parts = [f"Independent validation of {a.id} ({model.name}) concludes: **{verdict}**."]
        if revalidation_of:
            parts.append(f"Automatic re-validation after a live-traffic drift alert (`{drift_label}`).")
        perf = [n for n in ("gini.oot", "auc.holdout", "ae_ratio.holdout", "recall_at.holdout", "decline_zero_share") if n in have]
        if perf:
            parts.append("Key measures: " + "; ".join(f"{LABELS[n].lower()} {T(n)}" for n in perf) + ".")
        parts.append(f"The validator raised {T('findings.total')} findings ({T('findings.high')} high, {T('findings.medium')} medium)"
                     + (": " + "; ".join(f"{f['code']} {f['title'].lower()}" for f in top[:3]) if top else "") + ".")
        return {"summary": " ".join(parts)}
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"], "additionalProperties": False}
    prompt = ("Write a 4-6 sentence executive summary for an independent model validation report.\n"
              "Rules: (1) write NO digits; (2) refer to numbers only by copying a token exactly, braces included; "
              "(3) describe each metric only as its 'meaning' says; (4) state the overall rating verbatim.\n"
              f"Model: {a.id} {model.name} ({model.type}). Facts: {json.dumps(facts)}\nOverall rating: {verdict}\n"
              f"Top findings: {json.dumps(top)}" + ("\nContext: automatic re-validation on recent live traffic." if revalidation_of else ""))
    summary = None
    for attempt in (1, 2):
        r = ctx.tool("llm.draft", "executive summary (tokens only)", lambda: llm.complete_json(
            f"exec_summary_{a.id}_try{attempt}", prompt, schema, offline, run_id=rid, agent="report", spent=ctx.spent),
            result_summary=lambda r: f"source={r.source}")
        chk = ctx.tool("token_checker", "reject unsourced numbers / unknown tokens", lambda: tokens.check(r.data["summary"]),
                       result_summary=lambda c: "clean ✓" if c["ok"] else f"rejected: {len(c['violations'])} raw, {len(c['unknown_tokens'])} unknown")
        if chk["ok"]:
            summary = r.data["summary"]
            break
    summary = summary or offline()["summary"]

    def table(names, head="Measure"):
        rows = [f"| {LABELS.get(n, n)} | {T(n)} |" for n in names if n in have]
        return (f"| {head} | Value |\n|---|---|\n" + "\n".join(rows)) if rows else ""

    perf = table(["gini.train", "gini.test", "gini.oot", "ks.oot", "auc.holdout", "avg_precision.holdout", "recall_at.holdout",
                  "precision_at.holdout", "alert_rate.holdout", "dev_explained.holdout", "gini.champion.holdout", "gini.challenger.holdout"])
    calib = table(["calibration_ratio.holdout", "bad_rate.holdout", "brier.holdout", "approval_rate.holdout", "ae_ratio.holdout"])
    seg = sorted([n for n in have if n.startswith("ae_ratio.") and "=" in n], key=lambda n: -abs(have[n].value - 1))[:6]
    seg_t = ("| Segment | Actual ÷ expected |\n|---|---|\n" + "\n".join(f"| `{n.split('.', 1)[1]}` | {T(n)} |" for n in seg)) if seg else ""
    rules = table(["decline_zero_share", "max_limit", "cap_share", "limit_ratio_monotone", "approval_rate.all", "upstream_high_findings"], "Policy check")
    csi = sorted([n for n in have if n.startswith("csi.")], key=lambda n: -have[n].value)[:4]
    psi = next((n for n in have if n.startswith("psi.score.")), None)
    fair = [n for n in have if n.split(".")[0] in ("di_ratio", "dp_diff", "price_ratio", "limit_ratio") and "." in n]
    fair_t = ("| Measure | Group | Value |\n|---|---|---|\n" + "\n".join(f"| {n.split('.')[0].replace('_', ' ')} | {n.split('.', 1)[1].replace('_', ' ')} | {T(n)} |"
                                                                  for n in sorted(fair))) if fair else ""
    find_rows = "\n".join(f"| {f.code} | {f.severity.upper()} | {f.title} | `{f.detector}` |" for f in findings)

    impl = ""
    if P and "rows_scored" in pm:
        impl = (f"\n## 3. Implementation\n\nThe legacy model was **rehosted**: its unmodified R code ran in the network-isolated sandbox and "
                f"scored {P('rows_scored')} rows. A random forest cannot be reproduced exactly outside its original library, so no "
                "translation was attempted; the legacy outputs themselves were validated.\n")
    elif P:
        impl = (f"\n## 3. Implementation parity (legacy R → Python)\n\nThe unmodified legacy script ran in the sandbox and the Python "
                f"redevelopment scored the same {P('rows_compared')} rows. Largest output difference: {P('score_max_abs_diff')}"
                + (f"; largest coefficient difference: {P('coef_max_abs_diff')}" if "coef_max_abs_diff" in pm else "") + ".\n")
    lim = {"FR-001": "The fraud data is a **synthetic stand-in** with the public ULB schema; the real dataset needs a manual download.",
           "CR-003": "Applicant incomes are **synthetic** (seeded); PDs and decisions are the real outputs of legacy CR-001.",
           "PR-001": "Policy dates are not in the data, so hold-out and out-of-time samples are **simulated** random splits.",
           "CR-002": "The challenger was trained on all rows; every performance figure is in-sample."}.get(a.id, "")
    reval = f"\n> **Re-validation** on recent live traffic after drift alert `{drift_label}` · baseline run `{revalidation_of}`.\n" if revalidation_of else ""
    md = f"""# Independent Validation Report — {a.id} {model.name}

**Run** `{rid}` · **Date** `{date}` · **Tier** {model.tier} · **Validator** independent agent (inputs: code, data, docs only)
{reval}
## 1. Executive summary

{summary}

**Overall rating: {verdict}**

## 2. Scope and approach

{model.type}. Checks: {'discrimination, calibration, stability, fairness, data quality' if a.spec.task == 'binary' else 'segment experience (actual vs expected), deviance, stability, rating-factor fairness' if a.spec.task == 'frequency' else 'policy rules, upstream dependency, stability, fairness of limits'}, plus a rule-based review of the legacy code. Pass/fail uses fixed thresholds; the language model only drafts prose.
{impl}
## 4. {'Performance' if a.spec.task != 'rules' else 'Policy checks'}

{perf or rules}

{('## 5. Calibration and experience' + chr(10) + chr(10) + calib + (chr(10) + chr(10) + seg_t if seg_t else '')) if (calib or seg_t) else ''}

## 6. Stability

{('Score PSI against the development sample: ' + T(psi) + '. Largest input shifts: ' + ', '.join(f'`{n.split(".")[1]}` {T(n)}' for n in csi) + '.') if psi else 'No comparison sample.'}

{('## 7. Fairness' + chr(10) + chr(10) + fair_t) if fair_t else ''}

## 8. Findings

| ID | Severity | Finding | Detector |
|---|---|---|---|
{find_rows}

## 9. Limitations

{lim} Thresholds are this team's interpretation of SS1/23 expectations, not legal advice.
"""
    check = tokens.check(md)
    ctx.step("observation", f"Report checker: {'clean' if check['ok'] else 'violations'} · {check['token_count']} traceable numbers", check)
    with session() as s_:  # a redraft (after "request changes") replaces the earlier draft of this run
        prev = s_.get(Report, f"rep_{rid}")
        if prev:
            s_.delete(prev)
            s_.commit()
            version -= 1
    rep = save(Report(id=f"rep_{rid}", run_id=rid, model_id=a.id, version=version, title=f"{a.id} validation report v{version}",
                      markdown=md, status="draft", checker=check))
    ledger.append("report", "report_drafted", {"run_id": rid, "model_id": a.id, "report_id": rep.id, "version": version,
                                               "rating": verdict, "sha256": hashlib.sha256(md.encode()).hexdigest()})
    return rep
