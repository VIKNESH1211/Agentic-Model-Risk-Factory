"""Explainability for WoE logistic scorecards: global importance + per-applicant reason codes."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.tools import metrics as M


def global_importance(model, data: pd.DataFrame) -> list[dict]:
    tr = data[data["split"] == "train"]
    X = model.woe_features(tr)
    y = (tr["creditability"] == "bad").astype(int)
    out = []
    for c in X.columns:
        coef = float(model.params[c])
        sd = float(np.nanstd(X[c]))
        a = M.auc(y, X[c])
        out.append({"feature": c.replace("woe_", ""), "coefficient": round(coef, 4),
                    "std_contribution": round(coef * sd, 4), "univariate_auc": round(max(a, 1 - a), 4)})
    tot = sum(abs(r["std_contribution"]) for r in out) or 1
    for r in out:
        r["share"] = round(abs(r["std_contribution"]) / tot, 4)
    return sorted(out, key=lambda r: -r["share"])


def reason_codes(model, row: pd.DataFrame, top: int = 3) -> list[dict]:
    """Variables pushing this applicant's PD up the most vs. an average applicant (WoE 0)."""
    X = model.woe_features(row).iloc[0]
    contrib = {c.replace("woe_", ""): float(model.params[c] * X[c]) for c in X.index if not np.isnan(X[c])}
    return [{"feature": k, "log_odds_contribution": round(v, 4)}
            for k, v in sorted(contrib.items(), key=lambda kv: -kv[1])[:top]]
