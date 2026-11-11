"""Deterministic validation detectors shared by the Validator agent and the seeded-defect benchmark.

Pass/fail is decided here, by metrics and fixed thresholds. LLMs never decide pass/fail.
Every detector reads numbers through `measure(name, recipe)`, so in a real run each number
lands in the metric store (with a token) and can be reproduced later.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from app.core.config import settings
from app.tools.datasets import RAW_FEATURES

THRESHOLDS = {
    "gini_gap_train_test": 0.15,
    "single_feature_auc": 0.85,
    "coef_min": -0.05,
    "proxy_auc": 0.70,
    "psi_red": 0.25,
    "psi_amber": 0.10,
    "csi_amber": 0.25,
    "min_bin_share": 0.03,
    "calibration_ratio_low": 0.80,
    "calibration_ratio_high": 1.25,
    "max_decile_gap": 0.20,
    "dup_rate": 0.01,
    "missing_rate": 0.05,
    "di_ratio": 0.80,
}
NUMERIC_BINNED = ["duration", "amount"]

Measure = Callable[[str, dict], float]


@dataclass
class Detection:
    detector: str
    category: str  # defect category this detector covers
    severity: str
    title: str
    detail: str
    tokens: list[str] = field(default_factory=list)
    counts_for_benchmark: bool = True


# ------------------------------------------------------------------ context
def build_context(model, data: pd.DataFrame, rel_dir: str, *, challenger_pd: np.ndarray | None = None) -> dict:
    """Write scored.csv / coef.csv / woe.csv under var/<rel_dir>. Returns artifact relative paths."""
    out = settings.var_dir / rel_dir
    out.mkdir(parents=True, exist_ok=True)
    pdv = model.predict_pd(data)
    X = model.woe_features(data)
    keep = ["id", "split", "sex", "age_band", "age.in.years"] + RAW_FEATURES
    scored = data[keep].copy()
    scored["y"] = (data["creditability"] == "bad").astype(int).values
    scored["pd"] = pdv
    scored["approve"] = (pdv <= model.cutoff).astype(int)
    scored["is_under25"] = (data["age_band"] == "under25").astype(int).values
    scored["legacy_na_score"] = np.isnan(pdv).astype(int)
    for c in X.columns:
        scored[c] = X[c].values
    scored["missing_any"] = data[RAW_FEATURES].isna().any(axis=1).astype(int).values
    key = data[RAW_FEATURES + ["creditability"]].apply(lambda s: s.map(str)).agg("|".join, axis=1)
    train_keys = set(key[data["split"] == "train"])
    scored["dup_of_train"] = ((data["split"] != "train") & key.isin(train_keys)).astype(int).values
    if challenger_pd is not None:
        scored["challenger_pd"] = challenger_pd
    scored.to_csv(out / "scored.csv", index=False)

    coef = model.coef.rename("estimate").reset_index().rename(columns={"index": "term"})
    coef["is_feature"] = coef["term"] != "(Intercept)"
    coef.to_csv(out / "coef.csv", index=False)

    woe = model.woe_table()
    totals = woe.groupby("var")[["n_good", "n_bad"]].transform("sum").sum(axis=1)
    woe["share"] = (woe["n_good"] + woe["n_bad"]) / totals
    woe.to_csv(out / "woe.csv", index=False)
    return {"scored": f"{rel_dir}/scored.csv", "coef": f"{rel_dir}/coef.csv", "woe": f"{rel_dir}/woe.csv",
            "woe_cols": list(X.columns)}


# ------------------------------------------------------------------ detectors
def run_detectors(ctx: dict, measure: Measure, tok: Callable[[str], str], *, holdout: str = "test|oot",
                  comp_split: str = "oot", include_fairness: bool = True) -> list[Detection]:
    S, C, W = ctx["scored"], ctx["coef"], ctx["woe"]
    T = THRESHOLDS
    out: list[Detection] = []

    # 1. leakage / overfitting
    g_tr = measure("gini.train", {"fn": "gini", "artifact": S, "split": "train"})
    g_te = measure("gini.test", {"fn": "gini", "artifact": S, "split": "test"})
    measure("gini.oot", {"fn": "gini", "artifact": S, "split": "oot"})
    measure("auc.test", {"fn": "auc", "artifact": S, "split": "test"})
    measure("ks.test", {"fn": "ks", "artifact": S, "split": "test"})
    measure("ks.oot", {"fn": "ks", "artifact": S, "split": "oot"})
    if g_tr - g_te > T["gini_gap_train_test"]:
        out.append(Detection("performance_gap", "leakage", "high", "Train/test performance gap suggests overfitting or leakage",
                             "Training Gini {gt} vs. test Gini {ge}.", [tok("gini.train"), tok("gini.test")]))
    dom = []
    for c in ctx["woe_cols"]:
        v = measure(f"univariate_auc.{c}", {"fn": "auc_abs", "artifact": S, "split": "train", "score": c})
        if v > T["single_feature_auc"]:
            dom.append(c)
    if dom:
        out.append(Detection("importance_anomaly", "leakage", "high", f"Single feature dominates prediction ({dom[0]})",
                             f"Univariate AUC of {dom[0]} is {{v}}, implausibly high for one application variable.",
                             [tok(f"univariate_auc.{dom[0]}")]))

    # 2. conceptual soundness: WoE = ln(%bad/%good) so every coefficient should be positive
    cmin = measure("coef_min", {"fn": "col_min", "artifact": C, "col": "estimate", "slice": "is_feature=True"})
    if cmin < T["coef_min"]:
        coef = pd.read_csv(settings.var_dir / C)
        bad = coef[coef["is_feature"]].sort_values("estimate").iloc[0]["term"]
        out.append(Detection("coefficient_sign", "sign_flip", "high", f"Counter-intuitive coefficient sign on {bad}",
                             "A WoE-encoded coefficient is negative, so the variable moves risk the wrong way.",
                             [tok("coef_min")]))

    # 3. proxy discrimination (age)
    pa = measure("proxy_auc.age", {"fn": "proxy_auc", "artifact": S, "split": "train",
                                   "features": ctx["woe_cols"], "protected": "is_under25"})
    if pa > T["proxy_auc"]:
        out.append(Detection("proxy_detection", "age_proxy", "high", "Model features act as a proxy for applicant age",
                             "Model inputs predict under-25 status with high accuracy.", [tok("proxy_auc.age")]))

    # 4. stability (PSI on score, CSI on each WoE feature)
    ps = measure(f"psi.score.{comp_split}", {"fn": "psi", "artifact": S, "col": "pd", "base": "train", "comp": comp_split})
    worst, worst_v = None, 0.0
    for c in ctx["woe_cols"]:
        v = measure(f"csi.{c}.{comp_split}", {"fn": "psi", "artifact": S, "col": c, "base": "train",
                                               "comp": comp_split, "categorical": True})
        if v > worst_v:
            worst, worst_v = c, v
    if ps > T["psi_amber"] or worst_v > T["csi_amber"]:
        sev = "high" if (ps > T["psi_red"] or worst_v > T["psi_red"]) else "medium"
        out.append(Detection("psi_csi", "covariate_drift", sev, f"Population shift detected ({worst or 'score'})",
                             "Score PSI and worst feature CSI vs. development sample exceed thresholds.",
                             [tok(f"psi.score.{comp_split}")] + ([tok(f"csi.{worst}.{comp_split}")] if worst else [])))

    # 5. binning stability
    for v in NUMERIC_BINNED:
        sh = measure(f"min_bin_share.{v}", {"fn": "col_min", "artifact": W, "col": "share", "slice": f"var={v}"})
        if sh < T["min_bin_share"]:
            out.append(Detection("bin_stability", "unstable_binning", "medium", f"Unstable binning on {v}",
                                 "At least one bin holds too few applicants for a stable WoE estimate.",
                                 [tok(f"min_bin_share.{v}")]))
            break

    # 6. calibration
    cr = measure("calibration_ratio.holdout", {"fn": "calibration_ratio", "artifact": S, "split": holdout})
    dg = measure("max_decile_gap.holdout", {"fn": "max_decile_gap", "artifact": S, "split": holdout})
    measure("brier.holdout", {"fn": "brier", "artifact": S, "split": holdout})
    measure("bad_rate.holdout", {"fn": "bad_rate", "artifact": S, "split": holdout})
    if not (T["calibration_ratio_low"] <= cr <= T["calibration_ratio_high"]) or dg > T["max_decile_gap"]:
        out.append(Detection("calibration", "calibration_shift", "high" if abs(cr - 1) > 0.4 else "medium",
                             "Predicted PDs are mis-calibrated against observed default rates",
                             "Aggregate predicted/observed ratio and worst decile gap breach tolerance.",
                             [tok("calibration_ratio.holdout"), tok("max_decile_gap.holdout")]))

    # 7. data integrity
    du = measure("dup_rate.holdout", {"fn": "rate_true", "artifact": S, "split": holdout, "col": "dup_of_train"})
    if du > T["dup_rate"]:
        out.append(Detection("data_integrity", "train_test_overlap", "high", "Hold-out sample contaminated with training rows",
                             "Identical applicant records appear in both training and hold-out samples.",
                             [tok("dup_rate.holdout")]))

    # 8. data quality
    mr = measure("missing_rate.holdout", {"fn": "rate_true", "artifact": S, "split": holdout, "col": "missing_any"})
    if mr > T["missing_rate"]:
        out.append(Detection("data_quality", "missing_spike", "medium", "Spike in missing input values",
                             "Share of applications with a missing model input exceeds tolerance; legacy code "
                             "silently imputes missing credit amount as zero.", [tok("missing_rate.holdout")]))

    # 9. fairness (a property of the model, not a planted defect)
    if include_fairness:
        for grp in ("sex", "age_band"):
            di = measure(f"di_ratio.{grp}", {"fn": "di_ratio", "artifact": S, "split": "all", "group": grp})
            measure(f"dp_diff.{grp}", {"fn": "dp_diff", "artifact": S, "split": "all", "group": grp})
            measure(f"eo_diff.{grp}", {"fn": "eo_diff", "artifact": S, "split": "all", "group": grp})
            if di < T["di_ratio"]:
                out.append(Detection("fairness_di", "fairness", "medium",
                                     f"Approval-rate disparity by {'sex' if grp == 'sex' else 'age band'}",
                                     "Disparate impact ratio is below the four-fifths rule of thumb.",
                                     [tok(f"di_ratio.{grp}"), tok(f"dp_diff.{grp}")], counts_for_benchmark=False))
    return out
