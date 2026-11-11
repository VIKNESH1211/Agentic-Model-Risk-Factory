"""Independent Validator agent.

Independence: it receives only the Python code, the data and the legacy source. It re-fits the model
itself and never reads the Redevelopment agent's conclusions (only the stored parity metrics, which are
deterministic tool outputs). Pass/fail comes from validation_core thresholds.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.agents.common import StageCtx
from app.agents.redevelopment import load_model_module
from app.core.config import settings
from app.core.db import session
from app.domain.tables import Model
from app.evidence import metric_store
from app.tools import challenger, impact
from app.tools import validation_core as V
from app.tools.parsers import r_parser

SMELL_FINDINGS = {
    "comment_code_mismatch": ("high", "governance", "Decision cutoff contradicts documented credit policy",
                              "Code declines when PD > 0.35, but the comment cites policy CP-07 at 0.25. No approval record "
                              "exists for the change; decisions may not reflect approved risk appetite."),
    "na_imputed_zero": ("medium", "data_handling", "Missing credit amount silently imputed as zero",
                        "Missing loan amounts fall into the lowest-risk amount bin, understating PD for incomplete applications."),
    "hardcoded_path": ("low", "implementation", "Hardcoded analyst file paths",
                       "Inputs default to a personal laptop path; production data lineage is uncontrolled."),
}


def run(ctx: StageCtx, *, model_py: Path, data: pd.DataFrame, comp_split: str = "oot",
        factory_findings: bool = True, label: str = "validation") -> dict:
    mod = load_model_module(model_py)
    rec = ctx.recorder()
    model = ctx.tool("refit", "independent re-fit of Python model on training split",
                     lambda: mod.CR001Scorecard().fit(data[data["split"] == "train"]),
                     result_summary=lambda m: f"{len(m.coef)} coefficients")
    ch = ctx.tool("challenger.fit", "gradient-boosting challenger on same inputs", lambda: challenger.fit_predict(data),
                  result_summary=lambda r: "fitted")
    vctx = ctx.tool("build_scored", "score all splits, write evidence artifacts",
                    lambda: V.build_context(model, data, f"{ctx.rel}/validate", challenger_pd=ch),
                    result_summary=lambda r: "scored.csv · coef.csv · woe.csv")
    for k in ("scored", "coef", "woe"):
        ctx.artifact(f"validation_{k}", settings.var_dir / vctx[k])

    measure = lambda n, r: rec.measure(n, r)  # noqa: E731
    dets = ctx.tool("detectors", "performance · leakage · soundness · proxy · stability · binning · calibration · "
                    "integrity · fairness", lambda: V.run_detectors(vctx, measure, ctx.tok, comp_split=comp_split),
                    result_summary=lambda r: f"{len(r)} detector(s) fired")
    S = vctx["scored"]
    hold = "test|oot" if comp_split == "oot" else comp_split

    def chal():
        rec.measure("gini.challenger.holdout", {"fn": "gini", "artifact": S, "split": hold, "score": "challenger_pd"})
        rec.measure("gini.champion.holdout", {"fn": "gini", "artifact": S, "split": hold})
        lo = rec.measure("gini_diff_ci_low", {"fn": "gini_diff_ci", "artifact": S, "split": hold, "a": "challenger_pd",
                                              "b": "pd", "q": 2.5, "seed": 7, "n_boot": 300},
                         definition="2.5th percentile of bootstrap Gini(challenger) − Gini(champion), 300 resamples, seed 7")
        hi = rec.measure("gini_diff_ci_high", {"fn": "gini_diff_ci", "artifact": S, "split": hold, "a": "challenger_pd",
                                               "b": "pd", "q": 97.5, "seed": 7, "n_boot": 300},
                         definition="97.5th percentile of bootstrap Gini(challenger) − Gini(champion), 300 resamples, seed 7")
        rec.measure("decision_flips.challenger", {"fn": "decision_flips", "artifact": S, "split": hold,
                                                  "a": "challenger_pd", "b": "pd", "cutoff": model.cutoff})
        return lo, hi
    lo, hi = ctx.tool("challenger.compare", "bootstrap CI on Gini difference + decision flips", chal,
                      result_summary=lambda r: f"ΔGini CI [{r[0]:+.3f}, {r[1]:+.3f}]")

    def imp():
        rec.measure("el_gap.holdout", impact.el_gap_recipe(S, hold))
        rec.measure("approval_rate.holdout", {"fn": "approval_rate", "artifact": S, "split": hold, "cutoff": model.cutoff})
        for k, v in impact.ASSUMPTIONS.items():
            rec.const(f"assumption.{k}", v["value"], f"Assumption: {v['unit']} — {v['source']}")
        for k in ("psi_red", "calibration_ratio_low", "calibration_ratio_high", "di_ratio", "proxy_auc"):
            rec.const(f"threshold.{k}", V.THRESHOLDS[k], f"Validation threshold ({k}), fixed policy setting")
        rec.const("cutoff", model.cutoff, "Decision cutoff in code (PD above this is declined)")
    ctx.tool("impact", "translate findings into £ and customers (labelled assumptions)", imp,
             result_summary=lambda r: "expected-loss gap computed")
    rec.commit(label)

    findings = []
    for det in dets:
        imp_ = {"el_gap_token": ctx.tok("el_gap.holdout")} if det.category == "calibration_shift" else {}
        findings.append(ctx.finding(det.severity, det.category, det.title, det.detail, detector=det.detector,
                                    evidence={"tokens": det.tokens}, impact=imp_))
    if lo > 0:
        findings.append(ctx.finding("medium", "challenger", "Challenger materially outperforms champion",
                                    "Bootstrap confidence interval for the Gini uplift excludes zero.", detector="challenger",
                                    evidence={"tokens": [ctx.tok("gini_diff_ci_low"), ctx.tok("gini_diff_ci_high")]}))

    if factory_findings:
        with session() as s:
            m = s.get(Model, ctx.model_id)
        p = r_parser.parse(settings.root / m.meta["path"])
        seen = set()
        for sm in p["smells"]:
            if sm["kind"] in SMELL_FINDINGS and sm["kind"] not in seen:
                seen.add(sm["kind"])
                sev, cat, title, detail = SMELL_FINDINGS[sm["kind"]]
                findings.append(ctx.finding(sev, cat, title, detail, detector="code_review",
                                            evidence={"file": Path(p["path"]).name, "line": sm["line"], "code": sm["text"]}))
        if metric_store.value(ctx.run_id, "fuzz_legacy_na", 0) > 0:
            findings.append(ctx.finding("high", "robustness", "Legacy model returns no decision for some inputs",
                                        "Differential fuzzing found inputs (unseen categories, missing values) where the legacy "
                                        "R code produces an NA score and NA decision — such applications fall through.",
                                        detector="differential_fuzz",
                                        evidence={"tokens": [ctx.tok("fuzz_legacy_na"), ctx.tok("fuzz_rows")]}))
        if p["injection"]:
            h = p["injection"][0]
            findings.append(ctx.finding("high", "security", "Prompt-injection text planted in model source",
                                        "A comment instructs AI reviewers to report zero findings. It was treated as data, "
                                        "ignored, logged to the ledger and escalated.", detector="injection_guard",
                                        evidence={"file": Path(p["path"]).name, "line": h["line"], "code": h["text"]}))
    ctx.flush_cost()
    return {"findings": [f.id for f in findings], "context": vctx, "model": model}
