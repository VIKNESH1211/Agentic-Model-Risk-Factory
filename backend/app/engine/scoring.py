"""Build the scored frame every validation check reads (one CSV artifact per run, hashed into evidence).

scored = legacy export frame + standard columns:
  score, decision, flag (1 = adverse: decline / alert / no limit), approve (1 - flag), split, occurred, missing_any
  + one column per derived group (spec.groups)
"""
from __future__ import annotations

import operator
import re

import numpy as np
import pandas as pd

from app.domain.schemas import GroupDef, ModelSpec

OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}
SPLIT_NOTE = ("Rows the legacy code trained on are `train`; the remaining rows are split 50/50 into `test` and a "
              "SIMULATED out-of-time sample `oot` (seeded), because the data carries no dates.")


def derive_group(df: pd.DataFrame, g: GroupDef) -> pd.Series:
    src = df[g.column]
    if g.bins:
        labels = g.labels or [f"<{g.bins[0]}"] + [f"≥{b}" for b in g.bins]
        edges = [-np.inf, *g.bins, np.inf]
        return pd.cut(pd.to_numeric(src, errors="coerce"), edges, labels=labels, right=False).astype(str)
    if g.regex_map:
        def lab(v):
            for pat, label in g.regex_map.items():
                if re.search(pat, str(v)):
                    return label
            return "other"
        return src.map(lab)
    return src.astype(str)


def with_groups(df: pd.DataFrame, spec: ModelSpec) -> pd.DataFrame:
    df = df.copy()
    for g in spec.groups:
        if g.column in df.columns:
            df[g.name] = derive_group(df, g)
    return df


def adverse(score: pd.Series, decision: pd.Series | None, spec: ModelSpec) -> pd.Series:
    """1 when the decision is adverse. Uses the coded decision label if present, else the spec's rule."""
    d = spec.decision
    has = decision is not None and decision.notna().any() and (decision.astype(str).str.strip() != "").any()
    if has and d.adverse_label:
        return (decision.astype(str) == d.adverse_label).astype(int)
    if d.cutoff is not None and d.kind != "none":
        s = pd.to_numeric(score, errors="coerce")
        return (OPS[d.op](s, d.cutoff) & s.notna()).astype(int)
    return pd.Series(0, index=score.index)


def splits(n: int, rows: np.ndarray, train_rows: np.ndarray | None, seed: int = 7) -> np.ndarray:
    u = np.random.default_rng(seed).random(n)
    if train_rows is None:  # fitted on everything: hold-out is simulated and in-sample (flagged by validation)
        return np.where(u < 0.6, "train", np.where(u < 0.8, "test", "oot"))
    is_train = np.isin(rows, train_rows)
    return np.where(is_train, "train", np.where(u < 0.5, "test", "oot"))


def build(frame: pd.DataFrame, score: pd.Series, decision: pd.Series | None, spec: ModelSpec,
          train_rows: np.ndarray | None) -> pd.DataFrame:
    d = with_groups(frame.reset_index(drop=True), spec)
    d["score"] = pd.to_numeric(pd.Series(score).reset_index(drop=True), errors="coerce")
    if decision is not None:
        d["decision"] = pd.Series(decision).reset_index(drop=True).astype(object)
    elif "decision" not in d:
        d["decision"] = ""
    d["flag"] = adverse(d["score"], d["decision"] if decision is not None else None, spec)
    d["approve"] = 1 - d["flag"]
    if "split" not in d:
        d["split"] = splits(len(d), d[".row"].to_numpy() if ".row" in d else np.arange(1, len(d) + 1), train_rows)
    if spec.target and spec.target in d:
        d[spec.target] = pd.to_numeric(d[spec.target], errors="coerce") if not _is_binary_label(d[spec.target]) else _binary(d[spec.target])
        d["occurred"] = (d[spec.target].fillna(0) > 0).astype(int)
    feats = [f for f in spec.features if f in d.columns]
    d["missing_any"] = d[feats].isna().any(axis=1).astype(int) if feats else 0
    return d


def _is_binary_label(s: pd.Series) -> bool:
    return not pd.api.types.is_numeric_dtype(s) and s.dropna().nunique() == 2


def _binary(s: pd.Series) -> pd.Series:
    """Text outcomes (good/bad, yes/no…) → 1 for the adverse level."""
    levels = [str(v).lower() for v in s.dropna().unique()]
    bad = next((v for v in levels if v in ("bad", "1", "yes", "default", "fraud", "true", "y")), sorted(levels)[0])
    return (s.astype(str).str.lower() == bad).astype(int)
