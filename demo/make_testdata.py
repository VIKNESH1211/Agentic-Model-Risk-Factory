"""Materialise the test estate's shared drive (legacy_models/_data_room) from the raw public data.

Run once (`make testdata`). After this, the platform knows nothing about these models: they are onboarded
through the public API like any other upload (`make seed`).

Files written (what the legacy scripts expect on //shared/riskdata, plus CR-001's batch extracts):
  german_final_v3.csv      real · German credit (UCI / scorecard pkg), as the analysts saved it
  german_train.csv         real · CR-001 development extract (60% of applicants, with ids)
  german_applications.csv  real · CR-001 scoring batch (all applicants, with ids)
  applications_today.csv   synthetic · applicant income for the same ids (seeded)
  creditcard.csv           synthetic · card transactions in the Kaggle ULB schema (seeded)
  cr001_scores.csv         produced by the unmodified legacy CR-001 script (copied from its last sandbox run)
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "legacy_models" / "_data_room"


def german() -> pd.DataFrame:
    d = pd.read_csv(RAW / "germancredit.csv")
    d.insert(0, "id", [f"GC{i:04d}" for i in range(1, len(d) + 1)])
    return d


def train_mask(n: int, seed: int = 7) -> np.ndarray:
    return np.random.default_rng(seed).random(n) < 0.6


def applicant_income(d: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(31)
    job_bonus = d["job"].map(lambda j: 1.35 if "management" in j else 1.1 if "skilled" in j else 0.85).to_numpy()
    base = (14_000 + 520 * d["age.in.years"].clip(19, 70).to_numpy()) * job_bonus
    income = np.round(base * np.exp(rng.normal(0, 0.28, len(d))), -2).astype(int)
    return pd.DataFrame({"id": d["id"], "income": income})


def creditcard(n: int = 20_000, fraud_rate: float = 0.006) -> pd.DataFrame:
    rng = np.random.default_rng(2013)
    y = (rng.random(n) < fraud_rate).astype(int)
    V = rng.normal(0, 1, (n, 28))
    for j, s in {0: -1.1, 2: -1.4, 3: 1.3, 9: -1.6, 11: -1.5, 13: -1.9, 16: -1.3}.items():
        V[y == 1, j] += s + rng.normal(0, 0.6, (y == 1).sum())
    amount = np.round(np.exp(rng.normal(3.6, 1.2, n)) * np.where(y == 1, 1.6, 1.0), 2)
    df = pd.DataFrame(V, columns=[f"V{i}" for i in range(1, 29)])
    df.insert(0, "Time", np.sort(rng.uniform(0, 172_800, n)).round(0))
    df["Amount"], df["Class"] = amount, y
    return df


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy(RAW / "germancredit.csv", OUT / "german_final_v3.csv")
    g = german()
    g[train_mask(len(g))].to_csv(OUT / "german_train.csv", index=False)
    g.to_csv(OUT / "german_applications.csv", index=False)
    applicant_income(g).to_csv(OUT / "applications_today.csv", index=False)
    creditcard().to_csv(OUT / "creditcard.csv", index=False)
    prev = ROOT / "var" / "data_room" / "cr001_scores.csv"
    if not prev.exists():
        sys.exit("cr001_scores.csv not found: run the legacy CR-001 script once (v2 data room) or onboard CR-001 first")
    shutil.copy(prev, OUT / "cr001_scores.csv")
    for p in sorted(OUT.glob("*.csv")):
        print(f"{p.name:28s} {p.stat().st_size:>10,} bytes")


if __name__ == "__main__":
    main()
