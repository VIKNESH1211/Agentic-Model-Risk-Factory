"""Parity: does a Python translation reproduce the legacy R model exactly? (runs out of process)"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

WORKER = Path(__file__).with_name("parity_worker.py")
TIMEOUT_S = 300


def check(model_py: Path, bundle_dir: Path, out_dir: Path) -> dict:
    """Run the worker; returns {ok, problems, score_max_abs_diff, coef_max_abs_diff, decision_agreement, rows…}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "parity.json").unlink(missing_ok=True)
    try:
        r = subprocess.run([sys.executable, "-I", str(WORKER), str(model_py), str(bundle_dir), str(out_dir)],
                           capture_output=True, text=True, timeout=TIMEOUT_S, cwd=str(out_dir))
    except subprocess.TimeoutExpired:
        return {"ok": False, "problems": [f"translation did not finish within {TIMEOUT_S}s"]}
    f = out_dir / "parity.json"
    if not f.exists():
        return {"ok": False, "problems": [f"parity worker crashed: {(r.stderr or r.stdout)[-400:]}"]}
    return json.loads(f.read_text())


CONTRACT = """class LegacyModel:
    def fit(self, frame: pandas.DataFrame, train_rows: numpy.ndarray | None = None) -> "LegacyModel":
        # frame = frame.csv exactly as exported (all rows, incl. `.row`); train_rows = 1-based `.row` values the
        # legacy code fitted on, or None if it fitted on every row (or does not fit anything). Return self.
    def score(self, frame: pandas.DataFrame) -> pandas.DataFrame:
        # one output row per input row, same order; column `score` (float, identical to the legacy score) and,
        # if the legacy code makes a decision, column `decision` (same labels as legacy). Must work on ONE row.
    @property
    def coef(self) -> pandas.Series | None:
        # fitted coefficients named exactly like R's coef() (e.g. '(Intercept)', 'veh_bodyCONVT'), else None"""
