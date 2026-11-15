"""v3 platform tests: catalog linter, agent runtime guardrails, bundle + scoring, parity worker, knowledge CRUD, API."""
from __future__ import annotations

import io
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app import repositories as repo
from app.core.config import settings
from app.domain.schemas import Check, DecisionRule, GroupDef, ModelSpec, Threshold, ValidationPlan


# ------------------------------------------------------------------ catalog linter
def _spec(**kw) -> ModelSpec:
    return ModelSpec(entry_script="m.R", task="binary", target="y", features=["a", "b"],
                     groups=[GroupDef(name="age_band", column="age", bins=[25], labels=["u25", "25plus"])],
                     decision=DecisionRule(kind="approve", op=">", cutoff=0.4, adverse_label="DECLINE"), **kw)


def test_lint_rejects_unknown_metric_bad_column_and_wrong_direction():
    from app.engine import catalog
    s = _spec()
    cols = catalog.scored_columns(s, ["a", "b", "y", "age"])
    plan = ValidationPlan(checks=[
        Check(id="ok", title="Gini", category="performance", metric="gini", params={"target": "y", "score": "score", "split": "oot"},
              threshold=Threshold(op="<", amber=0.4, red=0.25)),
        Check(id="dir", title="AUC", category="performance", metric="auc", params={"target": "y", "score": "score"},
              threshold=Threshold(op=">", amber=0.75, red=0.7)),
        Check(id="col", title="PSI", category="stability", metric="psi", params={"col": "nope", "base": "train", "comp": "oot"}),
        Check(id="fn", title="?", category="performance", metric="magic", params={}),
    ])
    errs = " | ".join(catalog.lint_validation(plan, s, cols))
    assert "check ok" not in errs
    assert "check dir: higher auc is better" in errs
    assert "column 'nope'" in errs
    assert "unknown metric 'magic'" in errs


def test_default_plans_pass_their_own_linter():
    from app.engine import catalog, defaults
    s = _spec()
    cols = catalog.scored_columns(s, ["a", "b", "y", "age"])
    assert catalog.lint_validation(defaults.validation_plan(s), s, cols) == []
    assert catalog.lint_monitoring(defaults.monitoring_plan(s, ["a"]), {"a", "b", "y", "age"}) == []


# ------------------------------------------------------------------ bundle + scored frame
def _bundle(tmp: Path, n=300, seed=0, train=True) -> Path:
    rng = np.random.default_rng(seed)
    f = pd.DataFrame({".row": np.arange(1, n + 1), "a": rng.normal(size=n), "b": rng.choice(["x", "y", "z"], n),
                      "age": rng.integers(18, 70, n)})
    eta = 0.8 * f["a"] + (f["b"] == "x") * 0.5 - 0.4
    f["y"] = (rng.random(n) < 1 / (1 + np.exp(-eta))).astype(int)
    (tmp / "out").mkdir(parents=True, exist_ok=True)
    f.to_csv(tmp / "out" / "frame.csv", index=False)
    return tmp / "out"


def test_bundle_validator_messages_are_actionable(tmp_path):
    from app.engine import bundle as B
    out = _bundle(tmp_path)
    assert "scores.csv was not written" in " ".join(B.validate(out))
    pd.DataFrame({".row": [1, 2], "score": ["a", "b"]}).to_csv(out / "scores.csv", index=False)
    errs = " ".join(B.validate(out))
    assert "must be numeric" in errs


def test_scored_frame_groups_flags_and_splits(tmp_path):
    from app.engine import scoring
    out = _bundle(tmp_path)
    f = pd.read_csv(out / "frame.csv")
    d = scoring.build(f, pd.Series(np.linspace(0, 1, len(f))), None, _spec(), np.arange(1, 181))
    assert set(d["age_band"]) <= {"u25", "25plus"}
    assert (d["flag"] == (d["score"] > 0.4).astype(int)).all() and (d["approve"] == 1 - d["flag"]).all()
    assert (d.loc[d[".row"] <= 180, "split"] == "train").all() and set(d.loc[d[".row"] > 180, "split"]) <= {"test", "oot"}


# ------------------------------------------------------------------ parity worker (out of process)
GOOD = textwrap.dedent('''
    import numpy as np, pandas as pd
    import statsmodels.api as sm
    class LegacyModel:
        def _X(self, d):
            X = pd.DataFrame({"a": d["a"].astype(float), "bx": (d["b"].astype(str) == "x").astype(float)}, index=d.index)
            return sm.add_constant(X, has_constant="add")
        def fit(self, frame, train_rows=None):
            d = frame if train_rows is None else frame[frame[".row"].isin(train_rows)]
            self.r = sm.GLM(d["y"].astype(float), self._X(d), family=sm.families.Binomial()).fit(tol=1e-12)
            return self
        @property
        def coef(self):
            return None
        def score(self, frame):
            return pd.DataFrame({"score": np.asarray(self.r.predict(self._X(frame)))}, index=frame.index)
''')


def _legacy_scores(out: Path):
    import importlib.util
    p = out.parent / "good.py"
    p.write_text(GOOD)
    spec = importlib.util.spec_from_file_location("good", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    f = pd.read_csv(out / "frame.csv")
    m = mod.LegacyModel().fit(f, np.arange(1, 201))
    pd.DataFrame({".row": f[".row"], "score": m.score(f)["score"]}).to_csv(out / "scores.csv", index=False)
    pd.DataFrame({".row": np.arange(1, 201)}).to_csv(out / "train_rows.csv", index=False)
    return p


def test_parity_pass_fail_and_single_row(tmp_path):
    from app.engine import parity
    out = _bundle(tmp_path)
    good = _legacy_scores(out)
    r = parity.check(good, out, tmp_path / "p1")
    assert r["ok"], r
    bad = tmp_path / "bad.py"
    bad.write_text(GOOD.replace("0.0", "0.0").replace("frame[frame[\".row\"].isin(train_rows)]", "frame"))
    r = parity.check(bad, out, tmp_path / "p2")
    assert not r["ok"] and "scores differ" in r["problems"][0]
    single = tmp_path / "single.py"
    single.write_text(GOOD.replace('has_constant="add"', 'has_constant="skip"'))
    r = parity.check(single, out, tmp_path / "p3")
    assert not r["ok"] and any("single request" in p for p in r["problems"])


# ------------------------------------------------------------------ agent runtime guardrails
def test_runtime_refuses_early_finish_and_enforces_guard(monkeypatch):
    from app.agents import runtime
    from app.agents.common import StageCtx
    from app.core import llm
    from app.core.db import save
    from app.domain.tables import Run
    script = iter([
        {"thought": "done already", "action": "finish", "summary": "x", "recommendation": "promote", "reasons": []},
        {"thought": "use a tool that does not exist", "action": "call", "tool": "rm_rf", "args": {}},
        {"thought": "do it", "action": "call", "tool": "work", "args": {"n": 2}},
        {"thought": "finish", "action": "finish", "summary": "worked", "recommendation": "promote", "reasons": ["ok"]},
    ])
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: llm.LLMResult(next(script), "live"))
    calls = []
    ag = runtime.Agent(name="t", stage="validate", goal="g", mandatory=["work"],
                       tools=[runtime.Tool("work", "does work", lambda ctx, a: calls.append(a) or {"done": True}, {"n": "int"})],
                       guard=lambda ctx: ["a red check"])
    run = save(Run(id="run_rt", model_id="M", state={}))
    c = runtime.run(StageCtx(run, "validate", "t"), ag)
    assert calls == [{"n": 2}]
    assert c["recommendation"] == "hold" and c["reasons"][0] == "a red check" and c["incomplete"] == []


# ------------------------------------------------------------------ knowledge: specs, plans, prompts, policies
def _onboard(name="M-001"):
    from app.services import onboarding
    onboarding.upload_asset("d.csv", b"a,b\n1,2\n3,4\n")
    return onboarding.create_model([("m.R", b"# M-001 test model\nd <- read.csv('d.csv')\n")], model_id=name)


def test_spec_versioning_and_approval():
    from app.services import specs
    _onboard()
    body = _spec(inputs=[{"ref": "d.csv", "asset": "d.csv"}]).model_dump()
    v1 = specs.save_draft("M-001", body, "agent:intake")
    v2 = specs.save_draft("M-001", {**body, "tier": "A"}, "human:me")
    assert repo.specs.get(v1.id).status == "superseded" and v2.version == 2
    specs.approve("M-001", "me")
    assert repo.specs.approved("M-001").version == 2 and specs.current("M-001").tier == "A"
    assert "Python implementation" in repo.specs.get(v2.id).contract
    bad = specs.lint("M-001", ModelSpec(entry_script="nope.R", inputs=[{"ref": "x", "asset": "missing.csv"}]))
    assert any("nope.R" in e for e in bad) and any("missing.csv" in e for e in bad)


def test_prompt_edit_keeps_placeholders():
    from app.services import prompts
    with pytest.raises(ValueError):
        prompts.update("diagnose", "no placeholders at all", "me")
    t = prompts.text("diagnose") + "\nBe concise."
    row = prompts.update("diagnose", t, "me")
    assert row.version == 2 and prompts.text("diagnose").endswith("Be concise.")
    assert "{{m:" in prompts.render("system_guard")


def test_policy_library_flags_cr001_script():
    from app.services import policy
    src = (settings.legacy_dir / "cr001_pd_scorecard" / "cr001_scorecard.R").read_text()
    codes = {h["code"] for h in policy.run(src, "cr001_scorecard.R")}
    assert {"PC-01", "PC-03", "PC-08", "PC-09"} <= codes


# ------------------------------------------------------------------ API smoke
def test_api_onboarding_and_library():
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        r = c.post("/api/data-room", files={"file": ("d.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")})
        assert r.status_code == 201 and r.json()["rows"] == 1
        r = c.post("/api/models", files=[("files", ("x.R", io.BytesIO(b"# AB-123 demo\nx <- 1\n"), "text/plain"))],
                   data={"description": "demo"})
        assert r.status_code == 201 and r.json()["model"]["id"] == "AB-123"
        assert c.get("/api/models/AB-123").json()["files"][0]["name"] == "x.R"
        assert c.get("/api/models/AB-123/spec").json()["current"] is None
        assert len(c.get("/api/library/prompts").json()) >= 10
        assert any(m["fn"] == "gini" for m in c.get("/api/library/metrics").json()["metrics"])
        assert c.get("/api/pipeline").json()["cards"][0]["id"] == "AB-123"
        assert c.post("/api/models", files=[("files", ("readme.txt", io.BytesIO(b"hi"), "text/plain"))]).status_code == 400


def test_api_edit_dependencies():
    """Manual add / remove / restore of model dependencies on the graph, with cycle and duplicate guards."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import specs
    with TestClient(app) as c:
        for mid in ("AB-001", "AB-002", "AB-003"):
            assert c.post("/api/models", files=[("files", (f"{mid}.R", io.BytesIO(f"# {mid}\nx <- 1\n".encode()), "text/plain"))]).status_code == 201
        # a spec-declared edge AB-001 → AB-002
        specs.save_draft("AB-002", _spec(upstream=[{"model_id": "AB-001", "via_asset": "pd.csv"}]).model_dump(), "agent:intake")
        e = {(x["source"], x["target"]): x for x in c.get("/api/graph").json()["edges"]}
        assert e[("AB-001", "AB-002")]["origin"] == "spec"

        g = c.post("/api/graph/edges", json={"source": "AB-002", "target": "AB-003", "via": "limits.csv"}).json()
        e = {(x["source"], x["target"]): x for x in g["edges"]}
        assert e[("AB-002", "AB-003")]["origin"] == "manual" and e[("AB-002", "AB-003")]["via"] == "limits.csv"
        assert c.get("/api/models/AB-001").json()["blast_radius"] == ["AB-002", "AB-003"]

        assert c.post("/api/graph/edges", json={"source": "AB-003", "target": "AB-001"}).status_code == 409  # cycle
        assert c.post("/api/graph/edges", json={"source": "AB-001", "target": "AB-002"}).status_code == 409  # duplicate
        assert c.post("/api/graph/edges", json={"source": "AB-001", "target": "AB-001"}).status_code == 400

        # removing a derived edge suppresses it; restoring brings it back
        g = c.delete("/api/graph/edges", params={"source": "AB-001", "target": "AB-002"}).json()
        assert ("AB-001", "AB-002") not in {(x["source"], x["target"]) for x in g["edges"]}
        assert g["removed"][0]["source"] == "AB-001" and g["removed"][0]["origin"] == "spec"
        g = c.post("/api/graph/edges", json={"source": "AB-001", "target": "AB-002", "restore": True}).json()
        assert ("AB-001", "AB-002") in {(x["source"], x["target"]) for x in g["edges"]} and g["removed"] == []

        # removing a manual edge deletes it outright (nothing to restore)
        g = c.delete("/api/graph/edges", params={"source": "AB-002", "target": "AB-003"}).json()
        assert ("AB-002", "AB-003") not in {(x["source"], x["target"]) for x in g["edges"]} and g["removed"] == []
        acts = [x["action"] for x in c.get("/api/ledger").json()["entries"]]
        assert {"dependency_added", "dependency_removed", "dependency_restored"} <= set(acts)


# ------------------------------------------------------------------ live monitoring KPIs
def test_traffic_kpis_data_quality_and_diagnosis(monkeypatch):
    """The simulator computes operational, data-quality, drift, decision and outcome KPIs; a broken feed shows up."""
    from types import SimpleNamespace

    from app.agents import monitor
    from app.engine import defaults, serving, traffic
    from app.services import plans, specs

    rng = np.random.default_rng(0)
    n = 1200
    frame = pd.DataFrame({".row": np.arange(n), "a": rng.normal(50, 10, n), "c": rng.choice(["x", "y", "z"], n)})
    frame["y"] = (rng.random(n) < 1 / (1 + np.exp(-(frame["a"] - 55) / 5))).astype(int)

    class EP:
        version = "run_test"
        bundle = SimpleNamespace(n=n, frame=frame, train_rows=None)

        def predict(self, rows):
            a = pd.to_numeric(rows["a"], errors="coerce")
            p = 1 / (1 + np.exp(-(a - 55) / 5))
            return pd.DataFrame({"score": p, "flag": (p > 0.5).astype(int)})

    spec = ModelSpec(task="binary", target="y", features=["a", "c"], entry_script="m.R",
                     decision=DecisionRule(kind="alert", op=">", cutoff=0.5))
    monkeypatch.setattr(specs, "current", lambda mid: spec)
    monkeypatch.setattr(plans, "current", lambda mid, kind=None: defaults.monitoring_plan(spec, ["a"]))
    monkeypatch.setattr(serving, "get", lambda mid: EP())
    monkeypatch.setattr(traffic, "OUTCOME_DELAY", 0.0)

    mt = traffic.ModelTraffic("TT-001", {"rpm": 120_000})
    for _ in range(4):
        mt.tick()
    mt.close_window()
    k = traffic.windows("TT-001")[-1]
    for key in ("latency_p99_ms", "availability", "missing_input_rate", "out_of_range_rate", "unseen_category_rate",
                "score_psi", "score_ks", "mean_csi", "drifted_features", "adverse_rate_shift", "realized_gini",
                "realized_ks", "brier", "realized_precision", "health_score"):
        assert key in k, key
    assert k["missing_input_rate"] == 0 and k["unseen_category_rate"] == 0 and k["availability"] == 1
    assert k["health_score"] == 100 and set(k["csi"]) == {"a", "c"}

    # break the feed: nulls, out-of-range values, a new category code
    bad = mt.pool.copy()
    bad.loc[bad.index[::4], "a"] = np.nan
    bad.loc[bad.index[1::4], "a"] = 500.0
    bad.loc[bad.index[2::4], "c"] = "NEW"
    mt.pool = bad
    mt.reqs.clear()
    for _ in range(4):
        mt.tick()
    mt.close_window()
    k = traffic.windows("TT-001")[-1]
    assert k["missing_input_rate"] > 0.05 and k["out_of_range_rate"] > 0.1 and k["unseen_category_rate"] > 0.1
    assert k["worst_csi"] > 0.25 and k["drifted_features"] >= 1

    prof = mt.profile()
    assert prof["score_hist"] and {f["feature"] for f in prof["features"]} == {"a", "c"}
    assert next(f for f in prof["features"] if f["feature"] == "c")["unseen"] > 0.1

    d = monitor._fallback_diagnosis([{"column": "a", "psi": 0.6}], [{"column": "c", "issue": True}], {}, [k])
    assert d["likely_cause"] == "data issue"
    d = monitor._fallback_diagnosis([{"column": "a", "psi": 0.02}], [], {}, [{"ae_ratio": 1.6}])
    assert d["action"] == "recalibrate"
