"""The standard legacy export bundle — the one contract between any R model and the platform.

An agent-written epilogue must leave in /work/out:
  frame.csv       one row per scored record: the raw inputs as the model saw them (plus the outcome if known),
                  with `.row` = 1..n
  scores.csv      `.row`, `score` (numeric model output) and optionally `decision`
  coef.csv        optional: `term`, `estimate` (parametric models)
  train_rows.csv  optional: `.row` of the frame rows the model was fitted on (omit if fitted on all rows / not fitted)

validate() is deterministic and its messages are written for the agent that has to fix the epilogue.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

BUNDLE_FILES = ("frame.csv", "scores.csv", "coef.csv", "train_rows.csv")
SPEC_TEXT = __doc__.split("An agent-written epilogue must leave in /work/out:")[1].split("validate()")[0].strip()


@dataclass
class Bundle:
    frame: pd.DataFrame
    scores: pd.DataFrame
    coef: pd.Series | None
    train_rows: np.ndarray | None

    @property
    def n(self) -> int:
        return len(self.frame)

    def summary(self) -> dict:
        return {"rows": self.n, "columns": [c for c in self.frame.columns if c != ".row"][:60],
                "scored": int(self.scores["score"].notna().sum()), "has_decision": "decision" in self.scores,
                "coefficients": 0 if self.coef is None else len(self.coef),
                "train_rows": None if self.train_rows is None else len(self.train_rows)}


def _read(p: Path) -> pd.DataFrame:
    return pd.read_csv(p, low_memory=False, keep_default_na=True)


def validate(out: Path | str) -> list[str]:
    out = Path(out)
    errs: list[str] = []
    if not (out / "frame.csv").exists():
        errs.append("frame.csv was not written to /work/out")
    if not (out / "scores.csv").exists():
        errs.append("scores.csv was not written to /work/out")
    if errs:
        return errs
    f, s = _read(out / "frame.csv"), _read(out / "scores.csv")
    if ".row" not in f.columns:
        errs.append("frame.csv needs a `.row` column (1..n) — write.csv with row.names = FALSE and add .row explicitly")
    elif not (f[".row"].is_unique and f[".row"].min() == 1 and f[".row"].max() == len(f)):
        errs.append("frame.csv `.row` must be exactly 1..n with no gaps or duplicates")
    for col in (".row", "score"):
        if col not in s.columns:
            errs.append(f"scores.csv needs a `{col}` column (found: {', '.join(map(str, s.columns[:8]))})")
    if errs:
        return errs
    if not pd.api.types.is_numeric_dtype(s["score"]):
        errs.append("scores.csv `score` must be numeric (the model's raw output, e.g. a probability or rate)")
    if not set(s[".row"]).issubset(set(f[".row"])):
        errs.append("scores.csv has `.row` values that are not in frame.csv")
    if s["score"].notna().sum() == 0:
        errs.append("every score is missing")
    if len(f.columns) < 3:
        errs.append("frame.csv should contain the model's raw input columns, not just ids")
    if (out / "coef.csv").exists():
        c = _read(out / "coef.csv")
        if not {"term", "estimate"} <= set(c.columns):
            errs.append("coef.csv needs columns `term` and `estimate`")
    if (out / "train_rows.csv").exists():
        t = _read(out / "train_rows.csv")
        if ".row" not in t.columns:
            errs.append("train_rows.csv needs a `.row` column")
        elif not set(t[".row"]).issubset(set(f[".row"])):
            errs.append("train_rows.csv refers to rows that are not in frame.csv")
    return errs


def load(out: Path | str) -> Bundle:
    out = Path(out)
    f = _read(out / "frame.csv").sort_values(".row").reset_index(drop=True)
    s = _read(out / "scores.csv")
    s = f[[".row"]].merge(s, on=".row", how="left")  # align scores to frame order
    coef = None
    if (out / "coef.csv").exists():
        c = _read(out / "coef.csv")
        coef = c.set_index("term")["estimate"].astype(float)
    tr = None
    if (out / "train_rows.csv").exists():
        tr = np.sort(_read(out / "train_rows.csv")[".row"].to_numpy(int))
    return Bundle(f, s, coef, tr)


def store(out: Path, dest: Path) -> Path:
    """Keep the bundle with the run that produced it (serving and validation read it from there)."""
    dest.mkdir(parents=True, exist_ok=True)
    for name in BUNDLE_FILES:
        if (out / name).exists():
            shutil.copy(out / name, dest / name)
    return dest
