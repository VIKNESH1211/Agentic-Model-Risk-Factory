"""Out-of-process parity check for an untrusted Python translation.

    python -I parity_worker.py <model.py> <bundle_dir> <out_dir>

Fits LegacyModel on the legacy frame, scores every row, compares with the legacy R export, re-scores a
few rows one at a time (live serving does that), and writes parity.json + parity_scores.csv.
Only numpy / pandas are imported here; the translation may import statsmodels etc. itself.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

TOL = {"scores": 1e-6, "coefficients": 1e-6}


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("candidate_model", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "LegacyModel"):
        raise AttributeError("the module must define class LegacyModel")
    return mod


def _read(p: Path) -> pd.DataFrame:
    return pd.read_csv(p, low_memory=False)


def main(model_py: str, bundle_dir: str, out_dir: str) -> dict:
    b, out = Path(bundle_dir), Path(out_dir)
    frame = _read(b / "frame.csv").sort_values(".row").reset_index(drop=True)
    legacy = frame[[".row"]].merge(_read(b / "scores.csv"), on=".row", how="left")
    train_rows = np.sort(_read(b / "train_rows.csv")[".row"].to_numpy(int)) if (b / "train_rows.csv").exists() else None
    legacy_coef = _read(b / "coef.csv").set_index("term")["estimate"].astype(float) if (b / "coef.csv").exists() else None

    mod = _load(Path(model_py))
    m = mod.LegacyModel().fit(frame.copy(), train_rows)
    if m is None:
        raise TypeError("fit() must return self")
    sc = m.score(frame.copy())
    if not isinstance(sc, pd.DataFrame) or "score" not in sc:
        raise TypeError("score() must return a DataFrame with a `score` column")
    if len(sc) != len(frame):
        raise ValueError(f"score() returned {len(sc)} rows for {len(frame)} input rows")
    py = pd.to_numeric(sc["score"], errors="coerce").to_numpy(float)
    lg = pd.to_numeric(legacy["score"], errors="coerce").to_numpy(float)

    problems: list[str] = []
    both = np.isfinite(py) & np.isfinite(lg)
    sdiff = float(np.max(np.abs(py[both] - lg[both]))) if both.any() else float("inf")
    if not sdiff <= TOL["scores"]:
        worst = int(np.nanargmax(np.where(both, np.abs(py - lg), -1)))
        problems.append(f"scores differ from legacy by up to {sdiff:.3g} (worst row .row={int(frame['.row'][worst])}: "
                        f"legacy {lg[worst]:.6g} vs python {py[worst]:.6g})")
    nan_mismatch = int((np.isnan(py) != np.isnan(lg)).sum())
    if nan_mismatch:
        problems.append(f"{nan_mismatch} rows are missing in one implementation but not the other")

    agree = None
    py_dec = sc["decision"].astype(str).to_numpy() if "decision" in sc else None
    if py_dec is not None and "decision" in legacy:
        lg_dec = legacy["decision"].astype(str).to_numpy()
        agree = float(np.mean(py_dec == lg_dec))
        if agree < 1.0:
            problems.append(f"decisions differ on {int((py_dec != lg_dec).sum())} rows")

    cdiff = None
    if legacy_coef is not None:
        coef = getattr(m, "coef", None)
        if coef is None:
            problems.append("legacy model has coefficients but LegacyModel.coef is None")
        else:
            coef = pd.Series(coef, dtype=float)
            common = legacy_coef.index.intersection(coef.index)
            missing = [t for t in legacy_coef.index if t not in coef.index]
            if missing:
                problems.append(f"coefficients missing or named differently: {missing[:6]} (python has {list(coef.index[:6])})")
            if len(common):
                cdiff = float((legacy_coef[common] - coef[common]).abs().max())
                if not cdiff <= TOL["coefficients"]:
                    problems.append(f"coefficients differ by up to {cdiff:.3g}" + (
                        " — the export has no train_rows.csv, so fit() used every frame row; if the legacy model was "
                        "fitted on a subset (a random split, or a separate training file whose ids appear in the frame), "
                        "the EXPORT must write train_rows.csv (redraft the epilogue)" if train_rows is None else
                        " — if the translation's fitting logic is right, the export's train_rows.csv may name the wrong "
                        f"rows ({len(train_rows)} rows, first {list(train_rows[:5])}): they must be FRAME .row values of the "
                        "records R fitted on (match by id), so redraft the epilogue"))

    # live serving scores one request at a time
    idx = list(range(min(5, len(frame))))
    single_fail = None
    try:
        one = np.array([float(pd.to_numeric(m.score(frame.iloc[[i]].copy())["score"], errors="coerce").iloc[0]) for i in idx])
        if not np.allclose(one, py[idx], rtol=0, atol=1e-9, equal_nan=True):
            single_fail = "single-request scores differ from batch scores"
    except Exception as e:
        single_fail = f"fails when scoring a single request ({type(e).__name__}: {str(e)[:160]})"
    if single_fail:
        problems.append(single_fail)

    out.mkdir(parents=True, exist_ok=True)
    ps = pd.DataFrame({".row": frame[".row"], "legacy_score": lg, "py_score": py, "one": 1,
                       "both_scored": both.astype(int)})
    if py_dec is not None and "decision" in legacy:
        ps["decision_agree"] = (py_dec == legacy["decision"].astype(str).to_numpy()).astype(int)
    ps.to_csv(out / "parity_scores.csv", index=False)
    if legacy_coef is not None and getattr(m, "coef", None) is not None:
        c = pd.DataFrame({"term": legacy_coef.index, "legacy": legacy_coef.values})
        c["python"] = c["term"].map(pd.Series(m.coef, dtype=float))
        c.to_csv(out / "parity_coef.csv", index=False)
    return {"ok": not problems, "problems": problems, "score_max_abs_diff": sdiff, "coef_max_abs_diff": cdiff,
            "decision_agreement": agree, "rows": int(len(frame)), "rows_compared": int(both.sum())}


if __name__ == "__main__":
    model_py, bundle_dir, out_dir = sys.argv[1:4]
    try:
        res = main(model_py, bundle_dir, out_dir)
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        mine = [f for f in tb if f.filename == str(Path(model_py))]
        where = f" at line {mine[-1].lineno} in {mine[-1].name}(): `{(mine[-1].line or '').strip()}`" if mine else \
            f" (raised in {tb[-1].name})" if tb else ""
        res = {"ok": False, "problems": [f"{type(e).__name__}{where}: {str(e)[:240]}"],
               "traceback": "".join(traceback.format_exception(e)[-6:])[-1500:]}
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "parity.json").write_text(json.dumps(res, default=float))
