"""SIMULATED drift batches (the dataset has no dates) and drift scoring."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.tools import metrics as M

FEATURE_SETS = {
    "affordability": "credit amount up, duration longer (cost-of-living squeeze)",
    "checking": "more applicants with overdrawn checking accounts",
    "mixed": "all of the above plus outcome deterioration",
}
AMBER, RED = 0.10, 0.25   # PSI on score
CSI_AMBER = 0.15           # CSI on categorical WoE buckets is noisier on small batches


def make_batch(base: pd.DataFrame, severity: float, feature_set: str, seed: int = 99, n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(seed + int(severity * 100))
    pool = base[base["split"].isin(["test", "oot"])]
    b = pool.sample(n, replace=True, random_state=int(rng.integers(1e9))).reset_index(drop=True).copy()
    b = b.astype({"credit.amount": float, "duration.in.month": float})
    s = float(np.clip(severity, 0, 1))
    if feature_set in ("affordability", "mixed"):
        b["credit.amount"] = b["credit.amount"] * (1 + 1.5 * s)
        b["duration.in.month"] = b["duration.in.month"] + np.round(18 * s)
    if feature_set in ("checking", "mixed"):
        flip = rng.random(n) < 0.6 * s
        b.loc[flip, "status.of.existing.checking.account"] = "... < 0 DM"
    if feature_set == "mixed":  # simulated outcome deterioration
        worsen = (b["creditability"] == "good") & (rng.random(n) < 0.25 * s)
        b.loc[worsen, "creditability"] = "bad"
    b["id"] = [f"DR{int(severity * 100):03d}_{i:04d}" for i in range(n)]
    b["split"] = "drift"
    return b


def status(psi: float, worst_csi: float) -> str:
    if psi > RED or worst_csi > RED:
        return "red"
    return "amber" if (psi > AMBER or worst_csi > CSI_AMBER) else "green"


def score_batch(model, train: pd.DataFrame, batch: pd.DataFrame) -> dict:
    p_tr, p_b = model.predict_pd(train), model.predict_pd(batch)
    X_tr, X_b = model.woe_features(train), model.woe_features(batch)
    csi = {c.replace("woe_", ""): round(M.psi_categorical(X_tr[c].round(6), X_b[c].round(6)), 4) for c in X_tr.columns}
    y = (batch["creditability"] == "bad").astype(int)
    psi = M.psi(p_tr, p_b)
    worst = max(csi.values())
    return {"psi": round(psi, 4), "csi": csi, "status": status(psi, worst),
            "perf": {"gini": round(M.gini(y, p_b), 4), "bad_rate": round(float(y.mean()), 4),
                     "mean_pd": round(float(np.nanmean(p_b)), 4)}}
