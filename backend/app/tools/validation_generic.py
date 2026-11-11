"""Deterministic validation for non-scorecard models (binary classifiers, claim-frequency GLMs, decision rules).

Same principle as validation_core: every number goes through measure(name, recipe) into the metric
store, and fixed thresholds decide what becomes a finding.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from app.core.config import settings
from app.modelkit.registry import Spec
from app.tools.validation_core import THRESHOLDS as TH, Detection

GEN = {"recall_min": 0.60, "ae_low": 0.80, "ae_high": 1.25, "segment_min_exposure": 300.0, "limit_cap": 15000.0}


def build_scored(frame: pd.DataFrame, scores: pd.DataFrame, spec: Spec, rel_dir: str) -> str:
    """Join scores onto the analysis frame and write the evidence artifact. Returns its relative path."""
    sc = scores[["id", "score"] + (["decision"] if "decision" in scores else [])]
    keep = [c for c in frame.columns if c == "id" or c not in sc.columns]  # model outputs win over stale columns
    d = frame[keep].merge(sc, on="id", how="inner")
    if "decision" not in d and "decision" in frame:
        d = d.merge(frame[["id", "decision"]], on="id", how="left")
    if spec.decision_kind == "approve":
        d["approve"] = (d["score"] <= spec.cutoff).astype(int)
    if spec.decision_kind == "alert":
        d["flag"] = (d["score"] > spec.cutoff).astype(int)
    if spec.decision_kind == "limit":
        d["approve"] = (d["score"] > 0).astype(int)
        d["ratio"] = d["score"] / d["income"].clip(lower=1)
        from app.modelkit.translations.cr003_model import BREAKS, BANDS
        d["band"] = pd.cut(d["pd"], BREAKS, labels=BANDS, right=True).astype(str)
    if spec.task == "frequency":
        d["occurred"] = (d[spec.target] > 0).astype(int)
    feats = [f for f in spec.features if f in d.columns]
    d["missing_any"] = d[feats].isna().any(axis=1).astype(int) if feats else 0
    out = settings.var_dir / rel_dir
    out.mkdir(parents=True, exist_ok=True)
    d.to_csv(out / "scored.csv", index=False)
    return f"{rel_dir}/scored.csv"


def run(spec: Spec, S: str, measure: Callable[[str, dict], float], tok: Callable[[str], str], *,
        comp_split: str = "oot", holdout: str = "test|oot", upstream_high: int = 0) -> list[Detection]:
    d = pd.read_csv(settings.var_dir / S, low_memory=False)
    splits = set(d["split"].unique())
    out: list[Detection] = []
    tgt = spec.target

    # ---------------------------------------------------------------- discrimination
    if spec.task in ("binary", "frequency"):
        ycol = tgt if spec.task == "binary" else "occurred"
        for sp in ("train", "test", "oot"):
            if sp in splits:
                measure(f"gini.{sp}", {"fn": "gini", "artifact": S, "split": sp, "target": ycol, "score": "score"})
        measure("ks.oot", {"fn": "ks", "artifact": S, "split": comp_split, "target": ycol, "score": "score"})
        measure("auc.holdout", {"fn": "auc", "artifact": S, "split": holdout, "target": ycol, "score": "score"})
        if not spec.trained_on_all and {"train", "test"} <= splits:
            gtr = measure("gini.train", {"fn": "gini", "artifact": S, "split": "train", "target": ycol, "score": "score"})
            gte = measure("gini.test", {"fn": "gini", "artifact": S, "split": "test", "target": ycol, "score": "score"})
            if gtr - gte > TH["gini_gap_train_test"]:
                out.append(Detection("performance_gap", "leakage", "high", "Train/test performance gap suggests overfitting",
                                     "Gini falls sharply from training to test.", [tok("gini.train"), tok("gini.test")]))

    # ---------------------------------------------------------------- binary specifics
    if spec.task == "binary":
        measure("bad_rate.holdout", {"fn": "bad_rate", "artifact": S, "split": holdout, "target": tgt})
        measure("brier.holdout", {"fn": "brier", "artifact": S, "split": holdout, "target": tgt, "score": "score"})
        cr = measure("calibration_ratio.holdout", {"fn": "calibration_ratio", "artifact": S, "split": holdout, "target": tgt, "score": "score"})
        if spec.decision_kind == "approve":
            measure("approval_rate.holdout", {"fn": "approval_rate", "artifact": S, "split": holdout, "cutoff": spec.cutoff, "score": "score"})
            if not (TH["calibration_ratio_low"] <= cr <= TH["calibration_ratio_high"]):
                out.append(Detection("calibration", "calibration_shift", "medium", "Predicted PDs mis-calibrated",
                                     "Mean predicted PD is outside tolerance of the observed default rate.", [tok("calibration_ratio.holdout")]))
        if spec.decision_kind == "alert":
            rc = measure("recall_at.holdout", {"fn": "recall_at", "artifact": S, "split": holdout, "target": tgt, "score": "score", "cutoff": spec.cutoff})
            measure("precision_at.holdout", {"fn": "precision_at", "artifact": S, "split": holdout, "target": tgt, "score": "score", "cutoff": spec.cutoff})
            measure("avg_precision.holdout", {"fn": "avg_precision", "artifact": S, "split": holdout, "target": tgt, "score": "score"})
            measure("alert_rate.holdout", {"fn": "rate_true", "artifact": S, "split": holdout, "col": "flag"})
            measure("threshold.recall_min", {"fn": "const", "value": GEN["recall_min"]})
            if rc < GEN["recall_min"]:
                out.append(Detection("recall", "performance", "high", "Most fraud is not alerted at the coded threshold",
                                     "Recall at the coded alert threshold is below the minimum; precision-recall shows a better operating point.",
                                     [tok("recall_at.holdout"), tok("precision_at.holdout"), tok("avg_precision.holdout")]))
        # leakage: one numeric input that alone separates the classes
        for f in spec.features:
            if f in d and pd.api.types.is_numeric_dtype(d[f]):
                v = measure(f"univariate_auc.{f}", {"fn": "auc_abs", "artifact": S, "split": "all", "target": tgt, "score": f})
                limit = 0.97 if spec.decision_kind == "alert" else TH["single_feature_auc"]  # rare-event detectors have strong single signals
                if v > limit:
                    out.append(Detection("importance_anomaly", "leakage", "high", f"Single input `{f}` separates outcomes almost perfectly",
                                         "Check for target leakage.", [tok(f"univariate_auc.{f}")]))

    # ---------------------------------------------------------------- frequency specifics
    if spec.task == "frequency":
        e = spec.exposure
        measure("ae_ratio.holdout", {"fn": "ae_ratio", "artifact": S, "split": holdout, "target": tgt, "score": "score", "exposure": e})
        measure("dev_explained.holdout", {"fn": "poisson_dev_explained", "artifact": S, "split": holdout, "target": tgt, "score": "score", "exposure": e})
        worst = (None, 1.0)
        for f in ("agecat", "area", "veh_body"):
            for v, expo in d[d["split"].isin(holdout.split("|"))].groupby(d[f].astype(str))[e].sum().items():
                if expo < GEN["segment_min_exposure"]:
                    continue
                name = f"ae_ratio.{f}={v}"
                a = measure(name, {"fn": "ae_ratio", "artifact": S, "split": holdout, "slice": f"{f}={v}", "target": tgt,
                                   "score": "score", "exposure": e})
                if abs(np.log(a)) > abs(np.log(worst[1])):
                    worst = (name, a)
        if worst[0] and not (GEN["ae_low"] <= worst[1] <= GEN["ae_high"]):
            out.append(Detection("segment_ae", "calibration_shift", "medium", "A rating segment is mis-priced",
                                 "Actual claims differ materially from expected in at least one rating segment.", [tok(worst[0])]))
        for g in spec.groups:
            measure(f"price_ratio.{g}", {"fn": "group_mean_ratio", "artifact": S, "split": "all", "group": g, "col": "score"})

    # ---------------------------------------------------------------- decision rules (limit strategy)
    if spec.task == "rules":
        dz = measure("decline_zero_share", {"fn": "share_eq", "artifact": S, "split": "all", "col": "score", "value": 0, "where": "decision=DECLINE"})
        mx = measure("max_limit", {"fn": "col_max", "artifact": S, "split": "all", "col": "score"})
        mono = measure("limit_ratio_monotone", {"fn": "monotone_by", "artifact": S, "split": "all", "col": "ratio", "by": "band"})
        measure("cap_share", {"fn": "share_eq", "artifact": S, "split": "all", "col": "score", "value": GEN["limit_cap"]})
        measure("approval_rate.all", {"fn": "rate_true", "artifact": S, "split": "all", "col": "approve"})
        measure("upstream_high_findings", {"fn": "const", "value": upstream_high})
        if dz < 1:
            out.append(Detection("policy_decline", "policy", "high", "Declined applicants receive a credit limit",
                                 "Some DECLINE decisions carry a non-zero limit.", [tok("decline_zero_share")]))
        if mx > GEN["limit_cap"]:
            out.append(Detection("policy_cap", "policy", "high", "Limit cap breached", "A limit exceeds the cap.", [tok("max_limit")]))
        if mono < 1:
            out.append(Detection("policy_monotone", "policy", "medium", "Limits do not fall as risk rises",
                                 "Average limit-to-income ratio is not monotone across PD bands.", [tok("limit_ratio_monotone")]))
        for g in spec.groups:
            measure(f"limit_ratio.{g}", {"fn": "group_mean_ratio", "artifact": S, "split": "all", "group": g, "col": "score"})

    # ---------------------------------------------------------------- stability (all)
    if comp_split in splits and "train" in splits:
        ps = measure(f"psi.score.{comp_split}", {"fn": "psi", "artifact": S, "col": "score", "base": "train", "comp": comp_split})
        wn, wv = None, 0.0
        for f in spec.features:
            if f not in d:
                continue
            cat = not pd.api.types.is_numeric_dtype(d[f]) or d[f].nunique() <= 12
            v = measure(f"csi.{f}.{comp_split}", {"fn": "psi", "artifact": S, "col": f, "base": "train", "comp": comp_split, "categorical": cat})
            if v > wv:
                wn, wv = f, v
        if ps > TH["psi_amber"] or wv > TH["psi_red"]:
            out.append(Detection("psi_csi", "covariate_drift", "high" if max(ps, wv) > TH["psi_red"] else "medium",
                                 f"Population shift detected ({wn or 'score'})", "Score PSI or an input's CSI exceeds threshold.",
                                 [tok(f"psi.score.{comp_split}")] + ([tok(f"csi.{wn}.{comp_split}")] if wn else [])))

    # ---------------------------------------------------------------- fairness on decisions
    if "approve" in d:
        for g in spec.groups:
            if g in d:
                di = measure(f"di_ratio.{g}", {"fn": "di_ratio", "artifact": S, "split": "all", "group": g})
                measure(f"dp_diff.{g}", {"fn": "dp_diff", "artifact": S, "split": "all", "group": g})
                if di < TH["di_ratio"]:
                    out.append(Detection("fairness_di", "fairness", "medium", f"Approval-rate disparity by {g.replace('_', ' ')}",
                                         "Disparate impact ratio is below the four-fifths rule of thumb.", [tok(f"di_ratio.{g}")],
                                         counts_for_benchmark=False))

    mr = measure("missing_rate.holdout", {"fn": "rate_true", "artifact": S, "split": holdout, "col": "missing_any"})
    if mr > TH["missing_rate"]:
        out.append(Detection("data_quality", "missing_spike", "medium", "Spike in missing input values",
                             "Share of rows with a missing model input exceeds tolerance.", [tok("missing_rate.holdout")]))
    return out
