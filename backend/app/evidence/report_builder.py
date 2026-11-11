"""Validation report builder. Every number is a {{m:...}} token resolved from the metric store."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlmodel import func, select

from app.agents.common import StageCtx
from app.core import llm
from app.core.db import save, session
from app.domain.tables import Finding, Model, Report
from app.evidence import ledger, metric_store, tokens

SEV_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def rating(findings: list[Finding]) -> str:
    sev = {f.severity for f in findings}
    if "high" in sev:
        return "Requires remediation before continued use"
    if "medium" in sev:
        return "Fit for use with conditions"
    return "Fit for use"


def _t(run_id: str, name: str) -> str:
    return "{{" + metric_store.token(run_id, name) + "}}"


def build(ctx: StageCtx, *, parity_run_id: str | None, revalidation_of: str | None = None,
          drift_label: str | None = None) -> Report:
    rid = ctx.run_id
    with session() as s:
        model = s.get(Model, ctx.model_id)
        findings = sorted(s.exec(select(Finding).where(Finding.run_id == rid)).all(),
                          key=lambda f: (SEV_ORDER.get(f.severity, 9), f.code))
        version = s.exec(select(func.count()).select_from(Report).where(Report.model_id == ctx.model_id)).one() + 1
    rec = ctx.recorder()
    for sev in ("high", "medium", "low"):
        rec.const(f"findings.{sev}", sum(f.severity == sev for f in findings), f"Number of {sev}-severity findings")
    rec.const("findings.total", len(findings), "Number of findings")
    rec.commit("report counts")
    T = lambda n: _t(rid, n)  # noqa: E731
    P = (lambda n: _t(parity_run_id, n)) if parity_run_id else None
    verdict = rating(findings)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # --- executive summary (LLM drafts with tokens only; checker enforces it)
    avail = {n: metric_store.token(rid, n) for n in
             ["gini.test", "gini.oot", "ks.oot", "calibration_ratio.holdout", "psi.score.oot", "di_ratio.age_band",
              "findings.high", "findings.medium", "findings.total", "el_gap.holdout"]}
    if P:
        avail.update({n: metric_store.token(parity_run_id, n) for n in ["score_max_abs_diff", "fuzz_rows", "fuzz_legacy_na"]})
    top = [{"code": f.code, "severity": f.severity, "title": f.title} for f in findings[:5]]

    def offline_summary():
        parts = [f"Independent validation of {model.id} ({model.name}) concludes: **{verdict}**."]
        if revalidation_of:
            parts.append(f"This is an automatic re-validation triggered by a drift alert (`{drift_label}`); "
                         f"the comparison sample is the drifted batch.")
        parts.append(f"Out-of-time Gini is {T('gini.oot')} against {T('gini.test')} on the test sample, "
                     f"with KS of {T('ks.oot')}.")
        if P:
            parts.append(f"The Python redevelopment reproduces the legacy R model to within {P('score_max_abs_diff')} on every "
                         f"applicant; differential fuzzing on {P('fuzz_rows')} edge cases found {P('fuzz_legacy_na')} inputs "
                         f"where the legacy code returns no decision.")
        parts.append(f"The validator raised {T('findings.total')} findings ({T('findings.high')} high, "
                     f"{T('findings.medium')} medium). Most material: "
                     + "; ".join(f"{f['code']} {f['title'].lower()}" for f in top[:3]) + ".")
        return {"summary": " ".join(parts)}

    schema = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"],
              "additionalProperties": False}
    # Facts: each token with its actual value and the verdict from the fixed thresholds, so the drafter
    # cannot mis-describe what a number means (the checker only stops raw numbers, not wrong adjectives).
    from app.tools.validation_core import THRESHOLDS as TH
    v = lambda n: metric_store.value(rid, n)  # noqa: E731
    g_te, g_oot, psi_v, cr, di = v("gini.test"), v("gini.oot"), v("psi.score.oot"), v("calibration_ratio.holdout"), v("di_ratio.age_band")
    verdicts = {
        "gini.oot": "out-of-time Gini is " + ("HIGHER than (no deterioration vs) the test sample" if g_oot >= g_te else "LOWER than the test sample"),
        "psi.score.oot": "score population is " + ("STABLE (below amber threshold)" if psi_v <= TH["psi_amber"] else
                                                   "SHIFTED (amber)" if psi_v <= TH["psi_red"] else "SHIFTED (red breach)"),
        "calibration_ratio.holdout": "calibration is " + ("WITHIN tolerance" if TH["calibration_ratio_low"] <= cr <= TH["calibration_ratio_high"] else "OUTSIDE tolerance"),
        "di_ratio.age_band": "age-band approval ratio is " + ("BELOW the four-fifths rule" if di < TH["di_ratio"] else "above the four-fifths rule"),
        "el_gap.holdout": "expected-loss gap in GBP; negative means the model over-predicts risk (conservative)",
    }
    facts = {n: {"token": "{{" + t + "}}", "value": round(metric_store.value(*t.split(":")[1:]), 6), **({"meaning": verdicts[n]} if n in verdicts else {})}
             for n, t in avail.items()}
    prompt = ("Write a 4-6 sentence executive summary for an independent model validation report.\n"
              "Rules: (1) write NO digits at all; (2) refer to a number only by copying its token exactly as given, "
              "including the double curly braces; (3) describe each metric ONLY as its 'meaning' says - do not infer "
              "drift, degradation or improvement beyond that; (4) state the overall rating verbatim.\n"
              "Facts: " + json.dumps(facts) + f"\nOverall rating: {verdict}\nTop findings: " + json.dumps(top)
              + ("\nContext: automatic re-validation on a drifted batch." if revalidation_of else ""))
    summary, check, attempts = None, None, 0
    while attempts < 2:
        attempts += 1
        r = ctx.tool("llm.draft", "executive summary (tokens only, no raw numbers)", lambda: llm.complete_json(
            f"exec_summary_try{attempts}", prompt, schema, offline_summary, run_id=rid, agent="report", spent=ctx.spent),
            result_summary=lambda r: f"source={r.source}")
        check = tokens.check(r.data["summary"])
        if check["ok"]:
            summary = r.data["summary"]
            break
        why = ", ".join(x for x in [f"{len(check['violations'])} raw number(s)" if check["violations"] else "",
                                     f"{len(check['unknown_tokens'])} unknown token(s)" if check["unknown_tokens"] else ""] if x)
        ctx.emit("alert", f"✋ unsourced-number checker rejected draft ({why}) – regenerating",
                 {"violations": check["violations"][:5], "unknown_tokens": check["unknown_tokens"][:5]})
    if summary is None:
        summary = offline_summary()["summary"]

    perf_rows = "\n".join(
        f"| {lbl} | {T(f'gini.{sp}')} | " + (T(f"ks.{sp}") if sp in ("test", "oot") else "—") + " |"
        for lbl, sp in [("Train", "train"), ("Test", "test"), ("Out-of-time (simulated)", "oot")])
    fair_rows = "\n".join(f"| {g} | {T(f'di_ratio.{k}')} | {T(f'dp_diff.{k}')} | {T(f'eo_diff.{k}')} |"
                          for g, k in [("Sex", "sex"), ("Age band", "age_band")])
    find_rows = "\n".join(f"| {f.code} | {f.severity.upper()} | {f.title} | `{f.detector}` |" for f in findings)
    csi = sorted([m for m in metric_store.for_run(rid) if m.name.startswith("csi.")], key=lambda m: -m.value)[:3]
    csi_txt = ", ".join(f"`{m.name.split('.')[1].replace('woe_', '')}` {T(m.name)}" for m in csi)

    parity = ""
    if P:
        parity = f"""
## 3. Implementation parity (legacy R → Python)

The legacy script was executed unmodified in a network-isolated sandbox and compared with the Python
redevelopment on the same rows. Maximum coefficient difference: {P('coef_max_abs_diff')}. Maximum PD difference:
{P('score_max_abs_diff')}. Decision agreement: {P('decision_agreement')}. Differential fuzzing over {P('fuzz_rows')}
edge-case inputs found {P('fuzz_divergences')} divergences between implementations, and {P('fuzz_legacy_na')} inputs where
the legacy model returns no decision. See the Parity Certificate.
"""
    reval = ""
    if revalidation_of:
        reval = f"\n> **Re-validation** triggered automatically by drift alert on batch `{drift_label}`. " \
                f"Baseline report run: `{revalidation_of}`. Stability and performance below compare the development " \
                f"sample with the drifted batch (simulated).\n"
    md = f"""# Independent Validation Report — {model.id} {model.name}

**Run** `{rid}` · **Date** `{date}` · **Tier** {model.tier} · **Validator** independent agent (separate session; inputs: code, data, docs only)
{reval}
## 1. Executive summary

{summary}

**Overall rating: {verdict}**

## 2. Scope and approach

Conceptual soundness, implementation parity, discriminatory power, calibration, stability, fairness, challenger
benchmarking and adversarial (red-team) testing, mapped to the independent-validation principle of SS1/23. Pass/fail decisions use fixed,
deterministic thresholds; the language model only drafts prose and every figure is a traceable token.
{parity}
## 4. Discriminatory power

| Sample | Gini | KS |
|---|---|---|
{perf_rows}

Area under the ROC curve on the test sample is {T('auc.test')}. Gradient-boosting challenger Gini on the hold-out is
{T('gini.challenger.holdout')} against {T('gini.champion.holdout')} for the champion (bootstrap interval for the uplift
{T('gini_diff_ci_low')} to {T('gini_diff_ci_high')}; {T('decision_flips.challenger')} applicants would receive a different decision).

## 5. Calibration

Mean predicted PD over observed default rate on the hold-out: {T('calibration_ratio.holdout')} (tolerance
{T('threshold.calibration_ratio_low')} to {T('threshold.calibration_ratio_high')}). Worst decile gap: {T('max_decile_gap.holdout')}.
Observed default rate {T('bad_rate.holdout')}; Brier score {T('brier.holdout')}.

## 6. Stability

Score PSI against the development sample: {T('psi.score.oot')} (red threshold {T('threshold.psi_red')}).
Largest characteristic shifts: {csi_txt}.

## 7. Fairness and proxy discrimination

| Group | Disparate impact ratio | Approval-rate gap | Equal-opportunity gap |
|---|---|---|---|
{fair_rows}

Proxy test — model inputs predicting whether an applicant is under twenty-five: cross-validated AUC {T('proxy_auc.age')} (threshold {T('threshold.proxy_auc')}).
Four-fifths reference: {T('threshold.di_ratio')}.

## 8. Findings

| ID | Severity | Finding | Detector |
|---|---|---|---|
{find_rows}

## 9. Business impact

Annual expected-loss gap implied by hold-out calibration: {T('el_gap.holdout')} GBP, using labelled assumptions —
LGD {T('assumption.lgd')}, average exposure {T('assumption.avg_ead_gbp')} GBP, volume {T('assumption.annual_applications')}
applications per year. Hold-out approval rate at the coded cutoff {T('cutoff')}: {T('approval_rate.holdout')}.

## 10. Limitations

Public German credit data stands in for bank data. It has no dates, so out-of-time and drift samples are
**simulated** and labelled as such. Fairness attributes are derived from the dataset's combined status/sex field.
Thresholds are this team's interpretation of SS1/23 expectations, not legal advice.
"""
    check = tokens.check(md)
    ctx.emit("tool_result" if check["ok"] else "alert",
             f"unsourced-number check: {'✓ clean' if check['ok'] else '✗ ' + str(len(check['violations'])) + ' violation(s)'} · "
             f"{check['token_count']} traceable numbers", {"check": check})
    with session() as s_:  # a redraft (after "request changes") replaces the earlier draft of this run
        prev = s_.get(Report, f"rep_{rid}")
        if prev:
            s_.delete(prev)
            s_.commit()
            version -= 1
    rep = save(Report(id=f"rep_{rid}", run_id=rid, model_id=ctx.model_id, version=version,
                      title=f"{model.id} validation report v{version}", markdown=md,
                      status="draft", checker=check))
    ledger.append("report", "report_drafted", {"run_id": rid, "model_id": ctx.model_id, "report_id": rep.id,
                                               "version": version, "rating": verdict,
                                               "sha256": __import__("hashlib").sha256(md.encode()).hexdigest()})
    return rep
