"""The data room: the files the legacy scripts expect under //shared/riskdata, plus analysis frames.

Real public data: germancredit (CR-001, CR-002, CR-003 applicants), dataCar (PR-001).
Synthetic, seeded and labelled as such: applicant income (CR-003) and card transactions (FR-001,
same schema as the Kaggle ULB dataset, which needs a manual download and cannot ship in the repo).
"""
from __future__ import annotations

import shutil
import threading

import numpy as np
import pandas as pd

from app.core.config import settings
from app.tools import sandbox
from app.tools.datasets import prepared

ROOM = settings.var_dir / "data_room"
RAW = settings.data_dir / "raw"
_lock = threading.Lock()


def _split(n: int, seed: int) -> np.ndarray:
    u = np.random.default_rng(seed).random(n)
    return np.where(u < 0.6, "train", np.where(u < 0.8, "test", "oot"))


# ------------------------------------------------------------------ synthetic sources
def applicant_income() -> pd.DataFrame:
    """SYNTHETIC annual income for the German-credit applicants (seeded): grows with age and job grade."""
    d = prepared()
    rng = np.random.default_rng(31)
    job_bonus = d["job"].map(lambda j: 1.35 if "management" in j else 1.1 if "skilled" in j else 0.85).to_numpy()
    base = (14_000 + 520 * d["age.in.years"].clip(19, 70).to_numpy()) * job_bonus
    income = np.round(base * np.exp(rng.normal(0, 0.28, len(d))), -2).astype(int)
    return pd.DataFrame({"id": d["id"], "income": income})


def creditcard(n: int = 20_000, fraud_rate: float = 0.006) -> pd.DataFrame:
    """SYNTHETIC card transactions with the Kaggle ULB schema (Time, V1..V28, Amount, Class)."""
    rng = np.random.default_rng(2013)
    y = (rng.random(n) < fraud_rate).astype(int)
    V = rng.normal(0, 1, (n, 28))
    shift = {0: -1.1, 2: -1.4, 3: 1.3, 9: -1.6, 11: -1.5, 13: -1.9, 16: -1.3}  # V1,V3,V4,V10,V12,V14,V17
    for j, s in shift.items():
        V[y == 1, j] += s + rng.normal(0, 0.6, (y == 1).sum())
    amount = np.round(np.exp(rng.normal(3.6, 1.2, n)) * np.where(y == 1, 1.6, 1.0), 2)
    df = pd.DataFrame(V, columns=[f"V{i}" for i in range(1, 29)])
    df.insert(0, "Time", np.sort(rng.uniform(0, 172_800, n)).round(0))
    df["Amount"] = amount
    df["Class"] = y
    return df


def datacar() -> pd.DataFrame:
    p = RAW / "dataCar.csv"
    if not p.exists():
        import subprocess
        out = subprocess.run(["docker", "run", "--rm", "--entrypoint", "cat", settings.sandbox_image, "/opt/data/dataCar.csv"],
                             capture_output=True, text=True, timeout=120)
        if out.returncode != 0 or not out.stdout:
            raise RuntimeError("dataCar.csv missing: run `make sandbox` to export it from the R image")
        p.write_text(out.stdout)
    return pd.read_csv(p)


# ------------------------------------------------------------------ the data room
def build_room(force: bool = False) -> dict:
    """Create //shared/riskdata contents. CR-001's scores come from actually running the legacy CR-001 code."""
    with _lock:
        ROOM.mkdir(parents=True, exist_ok=True)
        made = {}
        if force or not (ROOM / "german_final_v3.csv").exists():
            shutil.copy(RAW / "germancredit.csv", ROOM / "german_final_v3.csv")
            made["german_final_v3.csv"] = "real (scorecard::germancredit)"
        if force or not (ROOM / "applications_today.csv").exists():
            applicant_income().to_csv(ROOM / "applications_today.csv", index=False)
            made["applications_today.csv"] = "synthetic income"
        if force or not (ROOM / "creditcard.csv").exists():
            creditcard().to_csv(ROOM / "creditcard.csv", index=False)
            made["creditcard.csv"] = "synthetic (ULB schema)"
        if force or not (ROOM / "cr001_scores.csv").exists():
            work = settings.var_dir / "data_room_build"
            (work / "out").mkdir(parents=True, exist_ok=True)
            d = prepared()
            d[d["split"] == "train"].to_csv(work / "train.csv", index=False)
            d.to_csv(work / "score.csv", index=False)
            script = settings.legacy_dir / "cr001_pd_scorecard" / "cr001_scorecard.R"
            r = sandbox.run_r(script, work, ["--train", "/work/train.csv", "--score", "/work/score.csv", "--outdir", "/work/out"],
                              [work / "train.csv", work / "score.csv"], ["out/scores.csv", "out/coef.csv", "out/woe.csv"])
            if not r.ok:
                raise RuntimeError(f"could not produce cr001_scores.csv: {r.stderr}")
            shutil.copy(work / "out" / "scores.csv", ROOM / "cr001_scores.csv")
            made["cr001_scores.csv"] = f"legacy CR-001 output ({r.mode})"
        return made


def room_files() -> list[dict]:
    build_room()
    labels = {"german_final_v3.csv": "real · German credit (UCI / scorecard pkg)",
              "applications_today.csv": "synthetic · applicant income",
              "creditcard.csv": "synthetic · ULB card-fraud schema",
              "cr001_scores.csv": "produced by legacy CR-001 in the sandbox"}
    return [{"name": p.name, "size": p.stat().st_size, "label": labels.get(p.name, "")} for p in sorted(ROOM.glob("*.csv"))]
