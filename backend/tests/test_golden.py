"""Golden tests: parity on CR-001 and the seeded-defect benchmark stay at target."""
import warnings

import pandas as pd
import pytest

from app.agents.translations.cr001_model import CR001Scorecard
from app.core.config import settings
from app.evidence.metric_store import compute
from app.tools import defect_injector as D, sandbox, validation_core as V
from app.tools.datasets import prepared

warnings.filterwarnings("ignore")


def test_parity_cr001_within_tolerance(tmp_path):
    d = prepared()
    tr = d[d["split"] == "train"]
    (tmp_path / "out").mkdir()
    tr.to_csv(tmp_path / "train.csv", index=False)
    d.to_csv(tmp_path / "score.csv", index=False)
    script = settings.legacy_dir / "cr001_pd_scorecard" / "cr001_scorecard.R"
    r = sandbox.run_r(script, tmp_path, ["--train", "/work/train.csv", "--score", "/work/score.csv", "--outdir", "/work/out"],
                      [tmp_path / "train.csv", tmp_path / "score.csv"], ["out/scores.csv", "out/coef.csv", "out/woe.csv"])
    if not r.ok:
        pytest.skip("R sandbox unavailable and no reference output")
    m = CR001Scorecard().fit(tr)
    lc = pd.read_csv(tmp_path / "out" / "coef.csv").set_index("term")["estimate"]
    assert (lc - m.coef[lc.index]).abs().max() < 1e-6
    ls = pd.read_csv(tmp_path / "out" / "scores.csv")
    assert (ls["pd"].values - m.predict_pd(d)).__abs__().max() < 1e-6


def test_seeded_defect_benchmark_meets_target():
    caught = planted = false_alarms = 0
    for v in D.VARIANTS:
        model, d2 = v.build(D.data_for(v), 1)
        ctx = V.build_context(model, d2, f"golden/{v.defect_type}")
        cats = {x.category for x in V.run_detectors(ctx, lambda n, r: compute(r), lambda n: n, include_fairness=False)
                if x.counts_for_benchmark}
        if v.expected_category:
            planted += 1
            caught += v.expected_category in cats
        else:
            false_alarms += bool(cats)
    assert caught >= 8 and planted == 10
    assert false_alarms == 0
