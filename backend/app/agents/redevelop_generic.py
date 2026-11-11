"""Redevelopment agent for the non-scorecard estate (translate with exact parity, or rehost)."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.agents.common import StageCtx
from app.agents.redevelopment import CERT_KEY, load_model_module
from app.core import llm
from app.core.db import session
from app.domain.tables import Model
from app.evidence import ledger
from app.modelkit import registry as R
from app.tools import sandbox

TOL = {"coefficients": 1e-6, "scores": 1e-6, "decision_agreement": 1.0}


def _sha(p) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _set_meta(model_id: str, **kw) -> None:
    with session() as s:
        m = s.get(Model, model_id)
        m.meta = {**(m.meta or {}), **kw}
        if "status" in kw:
            m.status = kw["status"]
        s.add(m)
        s.commit()


def run(ctx: StageCtx, a: R.Adapter) -> dict:
    work = ctx.dir / "sandbox"
    room = ctx.tool("data_room", "assemble //shared/riskdata for the legacy code", lambda: R.prepare_work(a, work),
                    result_summary=lambda r: f"{len(list(r.glob('*.csv')))} files mounted at /shared/riskdata",
                    args={"files": [p.name for p in sorted(R.D.ROOM.glob('*.csv'))]})
    legacy_src = (a.dir / a.script).read_text()
    inputs = [room / p.name for p in sorted(room.glob("*.csv"))] + [work / f for f in a.extra_work_files]
    sb = ctx.tool("sandbox.Rscript", f"source {a.script} unmodified + export epilogue · --network none",
                  lambda: sandbox.run_instrumented(a.dir, a.script, a.epilogue, work, room, inputs, a.outputs),
                  result_summary=lambda r: f"{'ok' if r.ok else 'FAILED'} via {r.mode} in {r.elapsed_s:.1f}s",
                  args={"image": "mrf-rsandbox", "network": "none", "mounts": ["/model:ro", "/harness:ro", "/work", "/shared/riskdata"],
                        "script": a.script, "epilogue": a.epilogue})
    if not sb.ok:
        raise RuntimeError(f"legacy run failed: {sb.stderr[-400:]}")
    ctx.step("observation", "Legacy console output", {"stdout": sb.stdout[-2500:]})
    legacy = a.legacy_scores(work, room)
    rec = ctx.recorder()
    rec.const("runtime_s.sandbox", sb.elapsed_s, "Wall-clock seconds for the sandboxed legacy run")

    # ------------------------------------------------------------------ rehost (no translation possible)
    if a.strategy == "rehost":
        f = ctx.dir / "legacy_scores.csv"
        legacy["one"] = 1
        legacy.to_csv(f, index=False)
        ctx.artifact("legacy_scores", f)
        rec.measure("rows_scored", {"fn": "count_true", "artifact": f"{ctx.rel}/legacy_scores.csv", "col": "one"},
                    definition="Rows scored by the rehosted legacy model")
        rec.commit("rehost")
        cert = {"certificate": "Rehost Record", "model_id": a.id, "run_id": ctx.run_id, "verdict": "REHOSTED",
                "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "legacy": {"file": a.script, "sha256": _sha(a.dir / a.script), "runtime": "R 4.4.1 + ranger 0.18 sandbox",
                           "execution": sb.mode},
                "python": {"file": "—", "sha256": "", "runtime": "not translated",
                           "origin": "random forests cannot be reproduced exactly outside ranger; validated as-is"},
                "inputs": {"rows_real": len(legacy), "rows_fuzz": 0, "train_sha256": "", "score_sha256": ""},
                "tolerances": {}, "results": {"rows_scored": len(legacy)}, "tokens": {"rows_scored": ctx.tok("rows_scored")}}
        cert["fingerprint"] = hashlib.sha256(json.dumps(cert, sort_keys=True, default=str).encode()).hexdigest()
        cert["signature"] = hmac.new(CERT_KEY, cert["fingerprint"].encode(), hashlib.sha256).hexdigest()
        (ctx.dir / "parity_certificate.json").write_text(json.dumps(cert, indent=2))
        ctx.artifact("rehost_record", ctx.dir / "parity_certificate.json")
        _set_meta(a.id, parity_run_id=ctx.run_id, parity_verdict="REHOSTED", parity_fingerprint=cert["fingerprint"],
                  status="redeveloped")
        ctx.emit("stage_completed", f"Rehosted {a.id}: {len(legacy)} rows scored by the legacy model")
        return {"certificate": cert}

    # ------------------------------------------------------------------ translate
    ref = a.reference.read_text()
    schema = {"type": "object", "additionalProperties": False, "required": ["python_code", "notes"],
              "properties": {"python_code": {"type": "string"}, "notes": {"type": "array", "items": {"type": "string"}}}}
    res = ctx.tool("llm.translate", f"translate {a.script} → Python", lambda: llm.complete_json(
        f"translate_{a.id}", "Translate this legacy R model into a Python module. Reproduce behaviour exactly, quirks "
        "included (flag them in comments). " + a.contract + "\nReturn the complete module in python_code.",
        schema, lambda: {"python_code": ref, "notes": []}, run_id=ctx.run_id, agent="redevelopment",
        untrusted={a.script: legacy_src}, spent=ctx.spent),
        result_summary=lambda r: f"{len(r.data['python_code'].splitlines())} lines (source={r.source})")
    model_py = ctx.dir / "model.py"
    legacy_coef = a.legacy_coef(work)
    lg = legacy.set_index("id")

    def compare(mod):
        m, sc, coef = a.python_fit_score(mod, work, room)
        j = lg.join(sc.set_index("id"), rsuffix="_py", how="inner")
        problems = []
        if len(j) < len(lg):
            problems.append(f"only {len(j)} of {len(lg)} rows scored")
        sdiff = float(np.nanmax(np.abs(j["score"] - j["score_py"]))) if len(j) else float("inf")
        if not sdiff <= TOL["scores"]:
            problems.append(f"scores differ from legacy by up to {sdiff:.2e}")
        if np.isnan(j["score_py"]).sum() != np.isnan(j["score"]).sum():
            problems.append("missing-score pattern differs from legacy")
        cdiff = None
        if legacy_coef is not None and coef is not None:
            common = legacy_coef.index.intersection(coef.index)
            cdiff = float((legacy_coef[common] - coef[common]).abs().max()) if len(common) else float("inf")
            if len(common) < len(legacy_coef):
                problems.append(f"{len(legacy_coef) - len(common)} legacy coefficients missing in Python")
            if not cdiff <= TOL["coefficients"]:
                problems.append(f"coefficients differ by up to {cdiff:.2e}")
        if "decision" in j and "decision_py" in j and (j["decision"].astype(str) != j["decision_py"].astype(str)).any():
            problems.append("approve/alert decisions differ on some rows")
        return m, sc, coef, j, ("; ".join(problems) or None)

    def attempt(code: str):
        model_py.write_text(code)
        try:
            return compare(load_model_module(model_py))
        except Exception as e:
            return None, None, None, None, f"{type(e).__name__}: {str(e)[:300]}"

    origin = f"LLM translation ({res.source})"
    used_ref = res.data["python_code"].strip() == ref.strip()
    m, sc, coef, j, gap = ctx.tool("parity.precheck", "candidate vs legacy on every row", lambda: attempt(res.data["python_code"]),
                                   result_summary=lambda r: "matches ✓" if r[4] is None else f"mismatch: {r[4][:100]}")
    if gap and not used_ref and res.source.startswith(("live", "cache")):
        ctx.emit("alert", f"✗ translation does not match legacy ({gap[:110]}) → asking the model to repair it")
        fix = ctx.tool("llm.repair", "send the parity gap back for one repair", lambda: llm.complete_json(
            f"repair_{a.id}", "Your Python translation does not reproduce the legacy R model.\nProblem: " + gap + "\n" + a.contract
            + "\nReturn the corrected full module.", schema, lambda: {"python_code": ref, "notes": []}, run_id=ctx.run_id,
            agent="redevelopment", untrusted={"previous_translation.py": model_py.read_text(), a.script: legacy_src}, spent=ctx.spent),
            result_summary=lambda r: f"{len(r.data['python_code'].splitlines())} lines (source={r.source})")
        m, sc, coef, j, gap = ctx.tool("parity.precheck", "repaired candidate vs legacy", lambda: attempt(fix.data["python_code"]),
                                       result_summary=lambda r: "matches ✓" if r[4] is None else f"mismatch: {r[4][:100]}")
        origin = f"LLM translation, repaired once ({fix.source})"
    if gap:
        ctx.emit("alert", f"✋ LLM translation rejected ({gap[:120]}) → using verified reference translation")
        ledger.append("redevelopment", "translation_rejected", {"run_id": ctx.run_id, "model_id": a.id, "reason": gap[:300]})
        ctx.think(f"Rejected the generated code: {gap}. Falling back to the verified reference translation.")
        m, sc, coef, j, gap = attempt(ref)
        origin = "verified reference translation"
        if gap:
            raise RuntimeError(f"reference translation failed parity: {gap}")
    elif used_ref:
        origin = "verified reference translation (offline drafter)"
    ctx.artifact("python_model", model_py)

    # ------------------------------------------------------------------ parity artefacts + certificate
    par = pd.DataFrame({"id": j.index, "legacy_pd": j["score"].to_numpy(), "py_pd": j["score_py"].to_numpy()})
    if "decision" in j and "decision_py" in j:
        par["legacy_decision"], par["py_decision"] = j["decision"].to_numpy(), j["decision_py"].to_numpy()
        par["decision_agree"] = (par["legacy_decision"].astype(str) == par["py_decision"].astype(str)).astype(int)
    par["one"] = 1
    par.to_csv(ctx.dir / "parity_scores.csv", index=False)
    sc.to_csv(ctx.dir / "python_scores.csv", index=False)
    ctx.artifact("parity_scores", ctx.dir / "parity_scores.csv")
    Rr = ctx.rel
    sdiff = rec.measure("score_max_abs_diff", {"fn": "max_abs_diff", "artifact": f"{Rr}/parity_scores.csv", "a": "legacy_pd", "b": "py_pd"},
                        definition="Max |legacy output − Python output| over every row")
    rec.measure("rows_compared", {"fn": "count_true", "artifact": f"{Rr}/parity_scores.csv", "col": "one"}, definition="Rows compared")
    toks = {"score_max_abs_diff": ctx.tok("score_max_abs_diff"), "rows_compared": ctx.tok("rows_compared")}
    cdiff, agree = 0.0, 1.0
    if legacy_coef is not None and coef is not None:
        common = legacy_coef.index.intersection(coef.index)
        pd.DataFrame({"term": common, "legacy": legacy_coef[common].to_numpy(), "python": coef[common].to_numpy()}).to_csv(
            ctx.dir / "coef_compare.csv", index=False)
        cdiff = rec.measure("coef_max_abs_diff", {"fn": "max_abs_diff", "artifact": f"{Rr}/coef_compare.csv", "a": "legacy", "b": "python"},
                            definition="Max |R coefficient − Python coefficient|")
        toks["coef_max_abs_diff"] = ctx.tok("coef_max_abs_diff")
    if "decision_agree" in par:
        agree = rec.measure("decision_agreement", {"fn": "rate_true", "artifact": f"{Rr}/parity_scores.csv", "col": "decision_agree"},
                            definition="Share of rows with identical decisions")
        toks["decision_agreement"] = ctx.tok("decision_agreement")
    rec.commit("parity")
    passed = sdiff <= TOL["scores"] and cdiff <= TOL["coefficients"] and agree >= 1.0
    cert = {"certificate": "Parity Certificate", "model_id": a.id, "run_id": ctx.run_id,
            "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "legacy": {"file": a.script, "sha256": _sha(a.dir / a.script), "runtime": "R 4.4.1 sandbox (harness, unmodified source)",
                       "execution": sb.mode},
            "python": {"file": "model.py", "sha256": _sha(model_py), "runtime": "Python / statsmodels", "origin": origin},
            "inputs": {"rows_real": int(len(par)), "rows_fuzz": 0, "train_sha256": "",
                       "score_sha256": hashlib.sha256("".join(_sha(p) for p in inputs).encode()).hexdigest()},
            "tolerances": TOL, "results": {"score_max_abs_diff": sdiff, "coef_max_abs_diff": cdiff, "decision_agreement": agree},
            "tokens": toks, "verdict": "PASS" if passed else "FAIL"}
    cert["fingerprint"] = hashlib.sha256(json.dumps(cert, sort_keys=True, default=str).encode()).hexdigest()
    cert["signature"] = hmac.new(CERT_KEY, cert["fingerprint"].encode(), hashlib.sha256).hexdigest()
    (ctx.dir / "parity_certificate.json").write_text(json.dumps(cert, indent=2, default=str))
    ctx.artifact("parity_certificate", ctx.dir / "parity_certificate.json")
    ledger.append("redevelopment", "parity_certificate_issued", {"run_id": ctx.run_id, "model_id": a.id,
                                                                 "verdict": cert["verdict"], "fingerprint": cert["fingerprint"]})
    _set_meta(a.id, parity_run_id=ctx.run_id, parity_verdict=cert["verdict"], parity_fingerprint=cert["fingerprint"],
              status="redeveloped")
    ctx.emit("stage_completed", f"🏅 Parity {cert['verdict']} · output Δ {sdiff:.1e} · {origin}")
    ctx.flush_cost()
    return {"certificate": cert}
