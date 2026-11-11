"""Redevelopment agent: R -> Python translation, tests, sandboxed legacy run, parity, fuzzing, certificate."""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.agents.common import StageCtx
from app.core import llm
from app.core.config import settings
from app.core.db import session
from app.domain.tables import Model
from app.evidence import ledger
from app.tools import fuzz, sandbox
from app.tools.datasets import prepared

TRANSLATION = Path(__file__).parent / "translations" / "cr001_model.py"
LEGACY = settings.legacy_dir / "cr001_pd_scorecard" / "cr001_scorecard.R"
TOL = {"coefficients": 1e-6, "scores": 1e-6, "decision_agreement": 1.0}
CERT_KEY = b"mrf-demo-signing-key"  # demo signing key; production would use a KMS-held key


def load_model_module(path: Path):
    spec = importlib.util.spec_from_file_location(f"redev_{hashlib.md5(str(path).encode()).hexdigest()[:8]}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


CONTRACT = """Interface contract (other agents call it):
- Input df is a pandas DataFrame with the original dotted column names (e.g. 'duration.in.month', 'credit.amount',
  'status.of.existing.checking.account', 'installment.rate.in.percentage.of.disposable.income') and 'creditability'
  with values 'good'/'bad' (bad = 1), plus an 'id' column. Numeric columns may contain NaN.
- class CR001Scorecard with attributes: cutoff (float), vars (list of the 8 short variable names
  checking, duration, history, purpose, amount, savings, employment, instalment), woe_tabs (dict var -> DataFrame
  with columns var, bin, n_good, n_bad, woe), params (pandas Series of fitted parameters, index 'const' and
  'woe_<var>').
- methods: fit(df) -> self; woe_features(df) -> DataFrame with columns woe_<var> (NaN for unseen levels);
  predict_pd(df) -> numpy array of PD (NaN where any WoE is NaN); score(df) -> DataFrame id, pd, points, decision;
  woe_table() -> concatenated woe_tabs; property coef -> params with 'const' renamed '(Intercept)'.
- Use numpy, pandas and statsmodels only (statsmodels GLM Binomial, no regularisation, tol 1e-12).
Return the complete module source in python_code."""


def run(ctx: StageCtx) -> dict:
    t_start = time.perf_counter()
    legacy_src = LEGACY.read_text()
    schema = {"type": "object", "additionalProperties": False, "required": ["python_code", "notes"],
              "properties": {"python_code": {"type": "string"}, "notes": {"type": "array", "items": {"type": "string"}}}}
    res = ctx.tool("llm.translate", "translate cr001_scorecard.R → Python (statsmodels GLM)", lambda: llm.complete_json(
        "translate_cr001",
        "Translate this legacy R scorecard into a Python module. Reproduce behaviour exactly, including quirks "
        "(flag them in comments). " + CONTRACT,
        schema, lambda: {"python_code": TRANSLATION.read_text(),
                         "notes": ["QUIRK-1 NA amount→0", "QUIRK-2 unseen level→NA", "QUIRK-3 cutoff 0.35 vs CP-07 0.25"]},
        run_id=ctx.run_id, agent="redevelopment", untrusted={LEGACY.name: legacy_src}, spent=ctx.spent),
        result_summary=lambda r: f"{len(r.data['python_code'].splitlines())} lines (source={r.source})")
    model_py = ctx.dir / "model.py"
    d = prepared()
    train = d[d["split"] == "train"]
    used_reference = res.data["python_code"].strip() == TRANSLATION.read_text().strip()

    def use_reference(reason: str):
        ctx.emit("alert", f"✋ LLM translation rejected ({reason}) → using verified reference translation",
                 {"reason": reason})
        ledger.append("redevelopment", "translation_rejected", {"run_id": ctx.run_id, "model_id": ctx.model_id,
                                                                "reason": reason[:300], "llm_source": res.source})
        model_py.write_text(TRANSLATION.read_text())
        return load_model_module(model_py)

    code = res.data["python_code"]
    mod = None
    for attempt in range(2):  # bounded repair loop: one repair with the error fed back, then fall back
        model_py.write_text(code)
        try:  # generated code must import and fit before we trust it
            mod = load_model_module(model_py)
            mod.CR001Scorecard().fit(train).predict_pd(d.head(50))
            break
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            if used_reference or attempt == 1 or not res.source.startswith(("live", "cache")):
                mod = use_reference(err)
                used_reference = True
                break
            ctx.emit("alert", f"✗ translated code failed ({err[:120]}) → asking the model to repair it")
            fix = ctx.tool("llm.repair", "send the error back, request a corrected module", lambda: llm.complete_json(
                "repair_cr001", "Your Python translation failed when run.\nError: " + err + "\n" + CONTRACT +
                "\nReturn the corrected full module.", schema, lambda: {"python_code": TRANSLATION.read_text(), "notes": []},
                run_id=ctx.run_id, agent="redevelopment", untrusted={"previous_translation.py": code, LEGACY.name: legacy_src},
                spent=ctx.spent), result_summary=lambda r: f"{len(r.data['python_code'].splitlines())} lines (source={r.source})")
            code = fix.data["python_code"]

    def unit_tests():
        m = mod.CR001Scorecard().fit(train)
        p = m.predict_pd(d)
        checks = {
            "fits_without_error": True,
            "pd_in_unit_interval": bool(np.nanmin(p) > 0 and np.nanmax(p) < 1),
            "points_decrease_with_pd": bool(np.corrcoef(p, m.score(d)["points"])[0, 1] < -0.9),
            "woe_tables_complete": len(m.woe_tabs) == len(m.vars),
            "deterministic_refit": bool(np.allclose(m.coef.values, mod.CR001Scorecard().fit(train).coef.values, atol=0)),
        }
        return m, checks
    try:
        pym, checks = ctx.tool("pytest", "5 unit tests on translated model", unit_tests,
                               result_summary=lambda r: f"{sum(r[1].values())}/{len(r[1])} passed")
    except Exception as e:
        mod = use_reference(f"unit tests crashed: {type(e).__name__}: {e}")
        used_reference = True
        pym, checks = unit_tests()

    # ---- legacy run in sandbox (real rows + fuzz rows, one batch call)
    fz = ctx.tool("fuzz.generate", "5,000 edge-case rows (nulls, bin edges, unseen levels, extremes)",
                  lambda: fuzz.generate(d, 5000), result_summary=lambda r: f"{len(r):,} rows")
    work = ctx.dir / "sandbox"
    (work / "out").mkdir(parents=True, exist_ok=True)
    train.to_csv(work / "train.csv", index=False)
    pd.concat([d, fz], ignore_index=True).to_csv(work / "score.csv", index=False)
    sb = ctx.tool("sandbox.Rscript", "docker · --network none · read-only · 1 CPU / 1 GB",
                  lambda: sandbox.run_r(LEGACY, work, ["--train", "/work/train.csv", "--score", "/work/score.csv",
                                                      "--outdir", "/work/out"],
                                        [work / "train.csv", work / "score.csv"],
                                        ["out/scores.csv", "out/coef.csv", "out/woe.csv"]),
                  result_summary=lambda r: f"{'ok' if r.ok else 'FAILED'} via {r.mode} in {r.elapsed_s:.1f}s")
    if not sb.ok:
        raise RuntimeError(f"Legacy sandbox run failed: {sb.stderr}")
    legacy_scores = pd.read_csv(work / "out" / "scores.csv")
    legacy_coef = pd.read_csv(work / "out" / "coef.csv").set_index("term")["estimate"]
    all_rows = pd.read_csv(work / "score.csv", low_memory=False)
    real = legacy_scores["id"].str.startswith("GC")

    def parity_gap(m) -> str | None:
        """None if the candidate reproduces legacy R on coefficients, real-applicant PDs and fuzz NA pattern."""
        try:
            cdiff = float((legacy_coef - m.coef.reindex(legacy_coef.index)).abs().max())
            sc = m.score(all_rows)
            lp, pp = legacy_scores["pd"].to_numpy(float), np.asarray(sc["pd"], float)
            sdiff = float(np.nanmax(np.abs(lp[real.values] - pp[real.values]))) if np.isfinite(pp[real.values]).any() else float("inf")
            nan_real = int(np.isnan(pp[real.values]).sum())
            na_mismatch = int((np.isnan(lp) != np.isnan(pp)).sum())
            ld = legacy_scores["decision"].astype(object).where(legacy_scores["decision"].notna(), None).to_numpy()
            pdn = pd.Series(np.asarray(sc["decision"], object)).where(lambda x: x.notna() & (x.astype(str) != "nan"), None).to_numpy()
            dec_mismatch = int(sum(a != b for a, b in zip(ld, pdn)))
        except Exception as e:
            return f"{type(e).__name__}: {e}"
        problems = []
        if not cdiff <= TOL["coefficients"]:
            problems.append(f"coefficients differ from R glm by up to {cdiff:.2e}")
        if nan_real:
            problems.append(f"PD is NaN for {nan_real} of {int(real.sum())} real applicants in the scoring file "
                            "(the scoring file has missing values, so numeric columns load as float; R's "
                            "as.character(4) gives '4', not '4.0')")
        elif not sdiff <= TOL["scores"]:
            problems.append(f"PD differs from legacy R by up to {sdiff:.2e}")
        if na_mismatch:
            problems.append(f"{na_mismatch} rows are NaN in one implementation but not the other")
        if dec_mismatch:
            problems.append(f"{dec_mismatch} rows get a different decision (legacy R returns NA, not APPROVE, when PD is NA)")
        return "; ".join(problems) or None

    if not used_reference:  # LLM code must reproduce the legacy model on every row, else repair once, else fall back
        gap = ctx.tool("parity.precheck", "LLM code vs legacy R on 6,000 rows", lambda: parity_gap(pym),
                       result_summary=lambda r: "matches ✓" if r is None else f"mismatch: {r[:90]}")
        if gap and res.source.startswith(("live", "cache")):
            ctx.emit("alert", f"✗ translation does not match legacy R ({gap[:120]}) → asking the model to repair it")
            fix = ctx.tool("llm.repair", "send the parity gap back, request a corrected module", lambda: llm.complete_json(
                "repair_parity_cr001", "Your Python translation runs but does not reproduce the legacy R model.\n"
                "Problem: " + gap + "\n" + CONTRACT + "\nReturn the corrected full module.", schema,
                lambda: {"python_code": TRANSLATION.read_text(), "notes": []}, run_id=ctx.run_id, agent="redevelopment",
                untrusted={"previous_translation.py": model_py.read_text(), LEGACY.name: legacy_src}, spent=ctx.spent),
                result_summary=lambda r: f"{len(r.data['python_code'].splitlines())} lines (source={r.source})")
            model_py.write_text(fix.data["python_code"])
            try:
                mod = load_model_module(model_py)
                pym, checks = unit_tests()
                gap = parity_gap(pym)
            except Exception as e:
                gap = f"repaired code failed: {type(e).__name__}: {e}"
        if gap or not all(checks.values()):
            mod = use_reference(gap or "unit tests failed")
            pym, checks = unit_tests()
            used_reference = True
        else:
            ctx.emit("tool_result", "LLM translation reproduces legacy R on every row ✓")
    ctx.artifact("python_model", model_py)

    # ---- python run on same rows
    py_scores = ctx.tool("python.score", "score same 6,000 rows with Python model", lambda: pym.score(all_rows),
                         result_summary=lambda r: f"{len(r):,} rows scored")

    # ---- parity artefacts
    par = pd.DataFrame({"id": legacy_scores["id"][real].values,
                        "legacy_pd": legacy_scores["pd"][real].values, "py_pd": np.asarray(py_scores["pd"], float)[real.values],
                        "legacy_decision": legacy_scores["decision"][real].values,
                        "py_decision": np.asarray(py_scores["decision"], object)[real.values]})
    par = par.merge(d[["id", "split", "creditability"]], on="id")
    par["y"] = (par["creditability"] == "bad").astype(int)
    par["decision_agree"] = (par["legacy_decision"] == par["py_decision"]).astype(int)
    par_f = ctx.dir / "parity_scores.csv"
    par.to_csv(par_f, index=False)
    cc = pd.DataFrame({"term": legacy_coef.index, "legacy": legacy_coef.values,
                       "python": pym.coef[legacy_coef.index].values})
    cc_f = ctx.dir / "coef_compare.csv"
    cc.to_csv(cc_f, index=False)
    fzc = ctx.tool("fuzz.compare", "diff legacy vs Python on 5,000 fuzz rows",
                   lambda: fuzz.compare(legacy_scores[~real], py_scores[~real.values], fz),
                   result_summary=lambda r: f"{int(r['diverged'].sum())} divergence(s), {int(r['legacy_na'].sum())} legacy NA scores")
    fzc["one"] = 1
    fz_f = ctx.dir / "fuzz_results.csv"
    fzc.to_csv(fz_f, index=False)
    for kind, f in [("parity_scores", par_f), ("coef_compare", cc_f), ("fuzz_results", fz_f)]:
        ctx.artifact(kind, f)

    rec = ctx.recorder()
    R = ctx.rel
    coef_diff = rec.measure("coef_max_abs_diff", {"fn": "max_abs_diff", "artifact": f"{R}/coef_compare.csv",
                                                  "a": "legacy", "b": "python"},
                            definition="Max |R glm coefficient − Python GLM coefficient|")
    score_diff = rec.measure("score_max_abs_diff", {"fn": "max_abs_diff", "artifact": f"{R}/parity_scores.csv",
                                                    "a": "legacy_pd", "b": "py_pd"},
                             definition="Max |legacy PD − Python PD| over all 1,000 applicants")
    agree = rec.measure("decision_agreement", {"fn": "rate_true", "artifact": f"{R}/parity_scores.csv",
                                               "col": "decision_agree"},
                        definition="Share of applicants with identical approve/decline decision")
    rec.measure("gini_legacy.all", {"fn": "gini", "artifact": f"{R}/parity_scores.csv", "score": "legacy_pd", "split": "all"})
    rec.measure("gini_python.all", {"fn": "gini", "artifact": f"{R}/parity_scores.csv", "score": "py_pd", "split": "all"})
    rec.measure("fuzz_rows", {"fn": "count_true", "artifact": f"{R}/fuzz_results.csv", "col": "one"},
                definition="Edge-case rows scored by both implementations")
    div = rec.measure("fuzz_divergences", {"fn": "count_true", "artifact": f"{R}/fuzz_results.csv", "col": "diverged"},
                      definition="Fuzz rows where legacy and Python outputs differ beyond tolerance")
    na = rec.measure("fuzz_legacy_na", {"fn": "count_true", "artifact": f"{R}/fuzz_results.csv", "col": "legacy_na_decision"},
                     definition="Fuzz rows where the legacy model returns no decision (NA)")
    rec.const("runtime_s.sandbox", sb.elapsed_s, "Wall-clock seconds for the sandboxed legacy R run")
    rec.commit("parity")

    passed = coef_diff <= TOL["coefficients"] and score_diff <= TOL["scores"] and agree >= TOL["decision_agreement"] \
        and div == 0 and all(checks.values())
    cert = {
        "certificate": "Parity Certificate", "model_id": ctx.model_id, "run_id": ctx.run_id,
        "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "legacy": {"file": LEGACY.name, "sha256": _sha(LEGACY), "runtime": "R 4.4.1 (rocker/r-ver) sandbox",
                   "execution": sb.mode},
        "python": {"file": "model.py", "sha256": _sha(model_py), "runtime": "statsmodels GLM Binomial",
                   "origin": "verified reference translation" if used_reference else f"LLM translation ({res.source})"},
        "inputs": {"train_sha256": _sha(work / "train.csv"), "score_sha256": _sha(work / "score.csv"),
                   "rows_real": int(real.sum()), "rows_fuzz": int((~real).sum())},
        "outputs": {"legacy_scores_sha256": _sha(work / "out" / "scores.csv"), "parity_sha256": _sha(par_f)},
        "tolerances": TOL,
        "results": {"coef_max_abs_diff": coef_diff, "score_max_abs_diff": score_diff,
                    "decision_agreement": agree, "fuzz_divergences": div, "fuzz_legacy_na": na,
                    "unit_tests": checks},
        "tokens": {k: ctx.tok(k) for k in ["coef_max_abs_diff", "score_max_abs_diff", "decision_agreement",
                                            "fuzz_rows", "fuzz_divergences", "fuzz_legacy_na"]},
        "verdict": "PASS" if passed else "FAIL",
        "fuzz_causes": fzc[fzc["diverged"]]["cause"].value_counts().to_dict(),
        "fuzz_kinds_na": fzc[fzc["legacy_na_decision"]]["fuzz_kind"].value_counts().to_dict(),
    }
    body = json.dumps(cert, sort_keys=True, default=str)
    cert["fingerprint"] = hashlib.sha256(body.encode()).hexdigest()
    cert["signature"] = hmac.new(CERT_KEY, body.encode(), hashlib.sha256).hexdigest()
    cert_f = ctx.dir / "parity_certificate.json"
    cert_f.write_text(json.dumps(cert, indent=2, default=str))
    ctx.artifact("parity_certificate", cert_f)
    ledger.append("redevelopment", "parity_certificate_issued", {"run_id": ctx.run_id, "model_id": ctx.model_id,
                                                                 "verdict": cert["verdict"], "fingerprint": cert["fingerprint"]})
    with session() as s:
        m = s.get(Model, ctx.model_id)
        m.status = "redeveloped"
        m.meta = {**m.meta, "parity_run_id": ctx.run_id, "parity_verdict": cert["verdict"],
                  "parity_fingerprint": cert["fingerprint"]}
        s.add(m)
        s.commit()
    ctx.emit("stage_completed", f"🏅 Parity Certificate {cert['verdict']} · coef Δ {coef_diff:.1e} · score Δ {score_diff:.1e}",
             {"certificate": cert["fingerprint"], "verdict": cert["verdict"]})
    ctx.flush_cost()
    return {"model_py": str(model_py), "certificate": cert, "elapsed_s": time.perf_counter() - t_start}
