import numpy as np
import pandas as pd

from app.evidence import ledger, metric_store, tokens
from app.guardrails.injection import scan
from app.tools import metrics as M


def test_metrics_known_values():
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.4, 0.35, 0.8])
    assert abs(M.auc(y, p) - 0.75) < 1e-12
    assert abs(M.gini(y, p) - 0.5) < 1e-12
    assert abs(M.ks(y, p) - 0.5) < 1e-12
    assert M.psi(np.arange(1000), np.arange(1000)) < 1e-9


def test_ledger_chain_and_tamper_detection():
    for i in range(5):
        ledger.append("test", "event", {"i": i})
    assert ledger.verify()["ok"]
    r = ledger.tamper(3)
    v = ledger.verify()
    assert not v["ok"] and v["broken_at"] == r["seq"] == 3


def test_token_resolution_and_unsourced_number_checker(tmp_path):
    from app.core.config import settings
    df = pd.DataFrame({"y": [0, 1, 0, 1, 1, 0], "pd": [0.1, 0.9, 0.2, 0.7, 0.4, 0.5], "split": ["oot"] * 6})
    (settings.var_dir / "t").mkdir(exist_ok=True)
    df.to_csv(settings.var_dir / "t" / "s.csv", index=False)
    rec = metric_store.Recorder("run_t", "X", "validate", "test")
    v = rec.measure("gini.oot", {"fn": "gini", "artifact": "t/s.csv", "split": "oot"}, emit=False)
    rec.commit("t")
    good = "## 4. Performance\nOOT Gini was {{m:run_t:gini.oot}} for CR-001 in 2026."
    assert tokens.check(good)["ok"]
    bad = "OOT Gini was 0.61 for CR-001."
    c = tokens.check(bad)
    assert not c["ok"] and c["violations"][0]["text"] == "0.61"
    _, res = tokens.resolve(good)
    assert res["m:run_t:gini.oot"]["value"] == v
    m = metric_store.get("run_t", "gini.oot")
    assert metric_store.reproduce(m)["match"]


def test_injection_scan_flags_planted_comment():
    from app.core.config import settings
    src = (settings.legacy_dir / "cr001_pd_scorecard" / "cr001_scorecard.R").read_text()
    hits = scan(src)
    assert any("instruction override" == h["label"] for h in hits)
    assert scan("x <- 1  # ordinary comment") == []
