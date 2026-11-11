"""REST + SSE API (build_plan.md §4.2)."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import func, select

from app.agents.redevelopment import load_model_module
from app.core.config import settings
from app.core.db import session
from app.core.events import bus
from app.domain.tables import (Artifact, Control, Finding, Gate, LedgerEntry, LLMCall, Metric, Model, MonitorBatch,
                               Report, Run)
from app.evidence import ledger, metric_store, tokens
from app.orchestrator import pipeline, services
from app.tools import controls, drift, explain, graph_build, impact
from app.tools import metrics as M
from app.tools.datasets import prepared
from app.tools.validation_core import THRESHOLDS

api = APIRouter(prefix="/api")


def _iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _run_json(r: Run) -> dict:
    d = r.model_dump()
    d["started_at"], d["ended_at"] = _iso(r.started_at), _iso(r.ended_at)
    d["station"] = pipeline.STATION.get(r.stage, r.stage)
    d["stages"] = pipeline.stages_for(r)
    return d


# ------------------------------------------------------------------ inventory
@api.get("/models")
def list_models():
    with session() as s:
        ms = s.exec(select(Model)).all()
        counts = dict(s.exec(select(Finding.model_id, func.count()).group_by(Finding.model_id)).all())
    g = graph_build.build()
    return [{**m.model_dump(), "findings": counts.get(m.id, 0), "blast_radius": graph_build.blast_radius(g, m.id)}
            for m in sorted(ms, key=lambda m: m.id)]


@api.get("/models/{model_id}")
def get_model(model_id: str):
    with session() as s:
        m = s.get(Model, model_id)
        if not m:
            raise HTTPException(404, "model not found")
        runs = s.exec(select(Run).where(Run.model_id == model_id).order_by(Run.started_at.desc())).all()
        findings = s.exec(select(Finding).where(Finding.model_id == model_id).order_by(Finding.id)).all()
        reports = s.exec(select(Report).where(Report.model_id == model_id).order_by(Report.version)).all()
    doc = None
    if m.meta.get("doc_run_id"):
        f = settings.runs_dir / m.meta["doc_run_id"] / "model_doc.json"
        doc = json.loads(f.read_text()) if f.exists() else None
    src = (settings.root / m.meta["path"]).read_text() if m.meta.get("path") else ""
    g = graph_build.build()
    return {"model": m.model_dump(), "runs": [_run_json(r) for r in runs], "findings": [f.model_dump() for f in findings],
            "reports": [{"id": r.id, "version": r.version, "run_id": r.run_id, "status": r.status} for r in reports],
            "doc": doc, "source": src, "blast_radius": graph_build.blast_radius(g, model_id),
            "upstream": sorted(g.predecessors(model_id)) if model_id in g else []}


@api.get("/graph")
def graph():
    return graph_build.as_json()


# ------------------------------------------------------------------ runs + events
class RunRequest(BaseModel):
    model_ids: list[str] | None = None
    auto_approve: bool = False


@api.post("/runs")
def start_runs(req: RunRequest):
    runs = pipeline.start_portfolio(req.model_ids, req.auto_approve)
    return {"runs": [_run_json(r) for r in runs]}


@api.get("/runs")
def list_runs():
    with session() as s:
        return [_run_json(r) for r in s.exec(select(Run).order_by(Run.started_at.desc())).all()]


@api.get("/runs/{run_id}")
def get_run(run_id: str):
    with session() as s:
        r = s.get(Run, run_id)
        if not r:
            raise HTTPException(404)
        arts = s.exec(select(Artifact).where(Artifact.run_id == run_id)).all()
    return {"run": _run_json(r), "artifacts": [a.model_dump() for a in arts]}


async def _sse(request: Request, run_id: str | None, replay: int):
    q = bus.subscribe()
    try:
        backlog = [e for e in bus.recent(replay) if not run_id or e["run_id"] == run_id] if replay else []
        for e in backlog:
            yield f"id: {e['id']}\nevent: message\ndata: {json.dumps(e)}\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                e = await asyncio.wait_for(q.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if run_id and e["run_id"] != run_id:
                continue
            yield f"id: {e['id']}\nevent: message\ndata: {json.dumps(e)}\n\n"
    finally:
        bus.unsubscribe(q)


@api.get("/events")
async def events(request: Request, replay: int = 150):
    return StreamingResponse(_sse(request, None, replay), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@api.get("/runs/{run_id}/events")
async def run_events(request: Request, run_id: str, replay: int = 500):
    return StreamingResponse(_sse(request, run_id, replay), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@api.get("/events/recent")
def recent_events(n: int = 200):
    return bus.recent(n)


@api.get("/overview")
def overview():
    with session() as s:
        models = s.exec(select(Model)).all()
        runs = s.exec(select(Run).order_by(Run.started_at)).all()
        gates_open = s.exec(select(func.count()).select_from(Gate).where(Gate.status == "pending")).one()
        cost = s.exec(select(func.sum(LLMCall.cost))).one() or 0.0
        llm_calls = s.exec(select(func.count()).select_from(LLMCall)).one()
        n_find = s.exec(select(func.count()).select_from(Finding)).one()
    factory = [r for r in runs if r.kind == "factory"]
    latest = {}
    for r in runs:
        latest[(r.model_id, r.kind)] = r
    lanes = [_run_json(r) for (mid, kind), r in latest.items() if kind == "factory"]
    revals = [_run_json(r) for (mid, kind), r in latest.items() if kind == "revalidation"]
    clock = None
    if factory:
        t0 = min(r.started_at for r in factory)
        ends = [r.ended_at for r in factory if r.ended_at]
        active = any(r.status in ("running", "queued", "waiting_gate") for r in factory)
        t1 = datetime.now(timezone.utc) if active or not ends else max(ends).replace(tzinfo=timezone.utc)
        clock = {"started_at": _iso(t0), "elapsed_s": (t1 - t0.replace(tzinfo=timezone.utc)).total_seconds(),
                 "active": active}
    parity = [m.meta.get("parity_verdict") for m in models if m.meta.get("parity_verdict")]
    bench = services.latest_benchmark()["summary"]
    return {
        "models": len(models), "lanes": lanes, "revalidations": revals, "clock": clock,
        "baseline_weeks": impact.ROI_DEFAULTS["manual_weeks_per_validation"]["value"],
        "kpis": {"models_processed": sum(1 for r in lanes if r["status"] == "completed"), "models_total": len(models),
                 "parity_pass": (sum(p == "PASS" for p in parity), len(parity)), "gates_open": gates_open,
                 "defects_caught": (bench["caught"], bench["planted"]) if bench else None,
                 "false_alarms": (bench["false_alarms"], bench["controls"]) if bench else None,
                 "findings": n_find, "llm_cost_usd": round(cost, 4), "llm_calls": llm_calls,
                 "llm_mode": f"{settings.llm_provider}/{settings.llm_mode}"},
        "autopilot": services.autopilot_state(),
    }


# ------------------------------------------------------------------ gates
class Decision(BaseModel):
    decision: str  # approved | rejected | changes_requested
    comment: str = ""
    decided_by: str = "Model Risk Officer"


@api.get("/gates")
def list_gates(status: str | None = None):
    with session() as s:
        q = select(Gate).order_by(Gate.requested_at.desc())
        if status:
            q = q.where(Gate.status == status)
        return [{**g.model_dump(), "requested_at": _iso(g.requested_at), "decided_at": _iso(g.decided_at)}
                for g in s.exec(q).all()]


@api.post("/gates/{gate_id}/decision")
def gate_decision(gate_id: int, d: Decision):
    if d.decision not in ("approved", "rejected", "changes_requested"):
        raise HTTPException(400, "bad decision")
    return pipeline.decide(gate_id, d.decision, d.decided_by, d.comment).model_dump()


# ------------------------------------------------------------------ parity
@api.get("/models/{model_id}/parity")
def parity(model_id: str):
    with session() as s:
        m = s.get(Model, model_id)
    rid = (m.meta or {}).get("parity_run_id") if m else None
    if not rid:
        raise HTTPException(404, "no parity run yet")
    d = settings.runs_dir / rid
    cert = json.loads((d / "parity_certificate.json").read_text())
    out = {"run_id": rid, "certificate": cert, "scatter": [], "residual_hist": [], "fuzz_by_kind": [], "coefficients": [],
           "tokens": {k: {"token": v, **tokens.resolve("{{" + v + "}}")[1][v]} for k, v in cert.get("tokens", {}).items()}}
    if (d / "parity_scores.csv").exists():
        par = pd.read_csv(d / "parity_scores.csv")
        samp = par.sample(min(500, len(par)), random_state=1)
        res = (par["legacy_pd"] - par["py_pd"]).abs()
        lg = np.log10(res.clip(lower=1e-17))
        out["residual_hist"] = [{"bin": f"1e{e}", "count": int(((lg >= e) & (lg < e + 1)).sum())} for e in range(-17, -5)]
        out["residual_hist"][0]["bin"] = "≤1e-17 (exact)"
        out["scatter"] = [{"legacy": round(a, 6), "python": round(b, 6)} for a, b in zip(samp["legacy_pd"], samp["py_pd"])]
    elif (d / "legacy_scores.csv").exists():
        ls = pd.read_csv(d / "legacy_scores.csv")
        out["legacy_distribution"] = np.histogram(ls["score"].dropna(), bins=20)[0].tolist()
    if (d / "fuzz_results.csv").exists():
        fz = pd.read_csv(d / "fuzz_results.csv")
        out["fuzz_by_kind"] = fz.groupby("fuzz_kind").agg(rows=("id", "size"), diverged=("diverged", "sum"),
                                                          legacy_na=("legacy_na_decision", "sum")).reset_index().to_dict("records")
    if (d / "coef_compare.csv").exists():
        coef = pd.read_csv(d / "coef_compare.csv")
        coef["abs_diff"] = (coef["legacy"] - coef["python"]).abs()
        out["coefficients"] = coef.to_dict("records")
    if (d / "sandbox" / "out").exists():
        out["exports"] = sorted(p.name for p in (d / "sandbox" / "out").iterdir())
    return out


# ------------------------------------------------------------------ reports + evidence
def _find_report(report_id: str) -> Report:
    with session() as s:
        if report_id.startswith("rep_"):
            r = s.get(Report, report_id)
        else:
            r = s.exec(select(Report).where(Report.model_id == report_id).order_by(Report.version.desc())).first()
    if not r:
        raise HTTPException(404, "report not found")
    return r


@api.get("/reports")
def list_reports():
    with session() as s:
        return [{"id": r.id, "model_id": r.model_id, "version": r.version, "run_id": r.run_id, "title": r.title,
                 "checker_ok": r.checker.get("ok"), "created_at": _iso(r.created_at)}
                for r in s.exec(select(Report).order_by(Report.created_at.desc())).all()]


@api.get("/reports/{report_id}")
def get_report(report_id: str):
    r = _find_report(report_id)
    md, toks = tokens.resolve(r.markdown)
    with session() as s:
        versions = s.exec(select(Report).where(Report.model_id == r.model_id).order_by(Report.version)).all()
        run = s.get(Run, r.run_id)
    return {"report": {**r.model_dump(), "created_at": _iso(r.created_at)}, "markdown": md, "tokens": toks,
            "versions": [{"id": v.id, "version": v.version, "run_id": v.run_id} for v in versions],
            "run": _run_json(run) if run else None}


DIFF_METRICS = ["gini.oot", "ks.oot", "psi.score.oot", "calibration_ratio.holdout", "max_decile_gap.holdout",
                "bad_rate.holdout", "approval_rate.holdout", "el_gap.holdout", "di_ratio.age_band", "brier.holdout"]


@api.get("/reports/{report_id}/diff")
def report_diff(report_id: str, against: str | None = None):
    r = _find_report(report_id)
    with session() as s:
        run = s.get(Run, r.run_id)
        base_id = against or run.parent_run_id
        if not base_id:
            prev = s.exec(select(Report).where(Report.model_id == r.model_id, Report.version < r.version)
                          .order_by(Report.version.desc())).first()
            base_id = prev.run_id if prev else None
    if not base_id:
        return {"base_run_id": None, "rows": []}
    rows = []
    for n in DIFF_METRICS:
        a, b = metric_store.get(base_id, n), metric_store.get(r.run_id, n)
        if a and b:
            rows.append({"metric": n, "before": a.value, "after": b.value, "delta": b.value - a.value,
                         "before_display": tokens.fmt(n, a.value), "after_display": tokens.fmt(n, b.value),
                         "before_token": metric_store.token(base_id, n), "after_token": metric_store.token(r.run_id, n)})
    with session() as s:
        fa = s.exec(select(Finding).where(Finding.run_id == base_id)).all()
        fb = s.exec(select(Finding).where(Finding.run_id == r.run_id)).all()
    ta = {f.title for f in fa}
    return {"base_run_id": base_id, "run_id": r.run_id, "rows": rows,
            "new_findings": [f.model_dump() for f in fb if f.title not in ta]}


def _chart(m: Metric) -> dict | None:
    rcp = m.recipe
    try:
        if rcp.get("fn") in ("gini", "auc", "ks") and rcp.get("artifact"):
            df = metric_store.load_artifact(rcp["artifact"])
            d = metric_store._split(df, rcp)
            return {"kind": "roc", "points": M.roc_points(d[rcp.get("target", "y")], d[rcp.get("score", "pd")])}
        if rcp.get("fn") in ("calibration_ratio", "max_decile_gap", "brier"):
            d = metric_store._split(metric_store.load_artifact(rcp["artifact"]), rcp)
            g = M.calibration_deciles(d["y"], d[rcp.get("score", "pd")])
            return {"kind": "calibration", "points": g.round(4).to_dict("records")}
        if rcp.get("fn") == "psi":
            df = metric_store.load_artifact(rcp["artifact"])
            base, comp = df[df["split"] == rcp["base"]][rcp["col"]], df[df["split"] == rcp["comp"]][rcp["col"]]
            if rcp.get("categorical"):
                b = base.round(4).astype(str).value_counts(normalize=True)
                c = comp.round(4).astype(str).value_counts(normalize=True)
                keys = sorted(set(b.index) | set(c.index), key=lambda k: float(k) if k != "nan" else 99)
                return {"kind": "dist", "points": [{"bin": k, "base": float(b.get(k, 0)), "comp": float(c.get(k, 0))} for k in keys]}
            edges = np.unique(np.quantile(base.dropna(), np.linspace(0, 1, 11)))
            edges[0], edges[-1] = -np.inf, np.inf
            bh = np.histogram(base.dropna(), edges)[0] / base.notna().sum()
            ch = np.histogram(comp.dropna(), edges)[0] / comp.notna().sum()
            return {"kind": "dist", "points": [{"bin": f"D{i + 1}", "base": float(a), "comp": float(b)} for i, (a, b) in enumerate(zip(bh, ch))]}
    except Exception:
        return None
    return None


@api.get("/evidence/{token}")
def evidence(token: str):
    try:
        run_id, name = tokens.parse(token)
    except ValueError:
        raise HTTPException(400, "bad token")
    m = metric_store.get(run_id, name)
    if not m:
        raise HTTPException(404, "metric not found")
    with session() as s:
        run = s.get(Run, run_id)
        led = s.get(LedgerEntry, m.ledger_seq) if m.ledger_seq else None
    recipe = {k: v for k, v in m.recipe.items() if k != "features"}
    return {"token": token, "name": name, "value": m.value, "display": tokens.fmt(name, m.value),
            "definition": m.definition, "split": m.split, "slice": m.slice, "recipe": recipe,
            "run": _run_json(run) if run else None, "code_hash": m.code_hash, "data_hash": m.data_hash,
            "artifact": m.recipe.get("artifact"), "source": metric_store.source_of(m.recipe["fn"]),
            "ledger": {"seq": led.seq, "entry_hash": led.entry_hash, "action": led.action} if led else None,
            "created_at": _iso(m.created_at), "chart": _chart(m)}


@api.post("/evidence/{token}/reproduce")
def reproduce(token: str):
    try:
        run_id, name = tokens.parse(token)
    except ValueError:
        raise HTTPException(400, "bad token")
    m = metric_store.get(run_id, name)
    if not m:
        raise HTTPException(404)
    res = metric_store.reproduce(m)
    ledger.append("human", "metric_reproduced", {"run_id": run_id, "metric": name, "match": res.get("match")})
    return res


# ------------------------------------------------------------------ findings, controls
@api.get("/findings")
def findings(model_id: str | None = None):
    with session() as s:
        q = select(Finding).order_by(Finding.id)
        if model_id:
            q = q.where(Finding.model_id == model_id)
        return [f.model_dump() for f in s.exec(q).all()]


@api.get("/controls/coverage")
def coverage():
    with session() as s:
        ctl = s.exec(select(Control).order_by(Control.ref)).all()
        ms = s.exec(select(Model).order_by(Model.id)).all()
    matrix = {m.id: {r["ref"]: r for r in controls.evaluate(m.id)} for m in ms}
    return {"controls": [c.model_dump() for c in ctl], "models": [m.id for m in ms], "matrix": matrix,
            "disclaimer": "Controls are this team's interpretation of PRA SS1/23 principles, not legal advice."}


# ------------------------------------------------------------------ benchmark
@api.post("/benchmarks/run")
def bench_run():
    return {"batch_id": services.run_benchmark()}


@api.get("/benchmarks/latest")
def bench_latest():
    return services.latest_benchmark()


# ------------------------------------------------------------------ monitoring
class DriftReq(BaseModel):
    feature_set: str = "mixed"
    severity: float = 0.6
    auto_approve: bool = True


@api.get("/monitor/{model_id}")
def monitor_state(model_id: str):
    with session() as s:
        bs = s.exec(select(MonitorBatch).where(MonitorBatch.model_id == model_id).order_by(MonitorBatch.id)).all()
        revals = s.exec(select(Run).where(Run.model_id == model_id, Run.kind == "revalidation")
                        .order_by(Run.started_at.desc())).all()
    return {"batches": [{**b.model_dump(), "created_at": _iso(b.created_at)} for b in bs],
            "thresholds": {"amber": drift.AMBER, "red": drift.RED, "csi_amber": drift.CSI_AMBER}, "feature_sets": drift.FEATURE_SETS,
            "revalidations": [_run_json(r) for r in revals]}


@api.post("/monitor/{model_id}/inject-drift")
def inject_drift(model_id: str, req: DriftReq):
    if req.feature_set not in drift.FEATURE_SETS:
        raise HTTPException(400, "unknown feature set")
    try:
        return pipeline.inject_drift(model_id, req.severity, req.feature_set, req.auto_approve)
    except ValueError as e:
        raise HTTPException(409, str(e))


# ------------------------------------------------------------------ ledger
@api.get("/ledger")
def get_ledger(limit: int = Query(400, le=5000)):
    es = ledger.entries()
    return {"total": len(es), "entries": [e.model_dump() for e in es[-limit:]]}


@api.post("/ledger/verify")
def verify_ledger():
    v = ledger.verify()
    bus.publish("info", f"⛓ Ledger verify: {'intact' if v['ok'] else 'BROKEN at #' + str(v['broken_at'])}",
                agent="governance", payload=v)
    return v


@api.post("/ledger/_tamper")
def tamper(seq: int | None = None):
    if not settings.allow_tamper_demo:
        raise HTTPException(403, "tamper demo disabled")
    r = ledger.tamper(seq)
    bus.publish("alert", f"☠ Demo: ledger entry #{r.get('seq')} silently edited in the database", agent="attacker", payload=r)
    return r


# ------------------------------------------------------------------ security + RAI
@api.post("/security/injection-test")
def injection():
    return services.injection_test()


@api.get("/rai/{model_id}")
def rai(model_id: str):
    with session() as s:
        m = s.get(Model, model_id)
        calls = s.exec(select(LLMCall)).all()
    if not m:
        raise HTTPException(404)
    rid = m.meta.get("validated_run_id")
    fair, importance, proxy = [], [], None
    if rid:
        for grp in ("sex", "age_band"):
            fair.append({"group": grp, **{k: {"token": metric_store.token(rid, f"{k}.{grp}"),
                                              "value": metric_store.value(rid, f"{k}.{grp}")}
                                          for k in ("di_ratio", "dp_diff", "eo_diff")}})
        proxy = {"token": metric_store.token(rid, "proxy_auc.age"), "value": metric_store.value(rid, "proxy_auc.age")}
        mod = load_model_module(settings.runs_dir / rid / "model.py")
        d = prepared()
        mdl = mod.CR001Scorecard().fit(d[d["split"] == "train"])
        importance = explain.global_importance(mdl, d)
        sample = d[d["split"] == "oot"].iloc[[0, 5, 9]]
        reasons = [{"id": r["id"], "pd": float(mdl.predict_pd(sample.loc[[i]])[0]),
                    "reasons": explain.reason_codes(mdl, sample.loc[[i]])} for i, r in sample.iterrows()]
    else:
        reasons = []
    sources: dict[str, int] = {}
    for c in calls:
        sources[c.source.split(" ")[0]] = sources.get(c.source.split(" ")[0], 0) + 1
    factory_card = {
        "name": "Model Risk Factory", "purpose": "Accelerate model documentation, redevelopment and independent "
                                                "validation under human oversight.",
        "agents": ["Discovery", "Documentation", "Redevelopment", "Validator (independent session)", "Red-team", "Monitor"],
        "llm": {"provider": settings.llm_provider, "model": settings.llm_model, "mode": settings.llm_mode, "key_configured": bool(settings.groq_api_key if settings.llm_provider == "groq" else settings.llm_api_key),
                "calls": len(calls), "by_source": sources, "cost_usd": round(sum(c.cost for c in calls), 4)},
        "llm_role": "Drafts prose, translation and rationales. Never computes numbers or decides pass/fail.",
        "decisions": "Deterministic thresholds decide findings; humans approve every gate.",
        "guardrails": ["Untrusted files wrapped as data + injection pre-scan", "Sandboxed legacy execution (no network)",
                       "Unsourced-number checker on every report", "Per-run token and cost caps",
                       "Hash-chained audit ledger"],
        "limitations": ["Public German-credit data; OOT and drift are simulated",
                        "Offline drafter used when no LLM key is configured",
                        "Controls are an interpretation of SS1/23, not legal advice"],
    }
    model_card = {"id": m.id, "name": m.name, "tier": m.tier, "owner": m.owner, "type": m.type, "purpose": m.purpose,
                  "intended_use": "Application PD for unsecured personal loans; decline above coded cutoff.",
                  "not_for": "Pricing, collections, or populations outside the development sample.",
                  "status": m.status}
    return {"model_card": model_card, "factory_card": factory_card, "fairness": fair, "proxy": proxy,
            "importance": importance, "reason_codes": reasons, "injection_test": services.last_injection(),
            "thresholds": {"di_ratio": THRESHOLDS["di_ratio"], "proxy_auc": THRESHOLDS["proxy_auc"]}}


# ------------------------------------------------------------------ ROI
class RoiReq(BaseModel):
    inputs: dict[str, float] = {}


@api.post("/roi")
def roi(req: RoiReq):
    with session() as s:
        r = s.exec(select(Run).where(Run.model_id == "CR-001", Run.kind == "factory", Run.status == "completed")
                   .order_by(Run.started_at.desc())).first()
        cost = s.exec(select(func.sum(LLMCall.cost))).one() or 0.0
    measured = {"factory_runtime_s": round(r.state.get("runtime_s", 0), 1) if r else 240.0,
                "llm_cost_usd": round(cost, 4)}
    out = impact.roi(req.inputs, measured)
    out["measured_run_id"] = r.id if r else None
    if not r:
        out["measured"]["factory_runtime_s"]["source"] = "placeholder (no completed run yet)"
    return out


@api.get("/roi/defaults")
def roi_defaults():
    return impact.ROI_DEFAULTS


# ------------------------------------------------------------------ demo
@api.post("/demo/reset")
def demo_reset():
    return services.reset()


@api.post("/demo/autopilot")
def demo_autopilot():
    return services.autopilot()


@api.get("/demo/state")
def demo_state():
    return services.autopilot_state()


@api.get("/health")
def health():
    from app.tools.sandbox import docker_available
    live = settings.llm_provider in ("anthropic", "groq")
    llm_label = f"{settings.llm_provider}:{settings.llm_model}/{settings.llm_mode}" if live else f"offline/{settings.llm_mode}"
    key = settings.groq_api_key if settings.llm_provider == "groq" else settings.llm_api_key
    if live and not key:
        llm_label += " (no key → offline)"
    from app.core.llm import LAST_ERROR
    if LAST_ERROR:
        llm_label += " (provider error → offline)"
    return {"ok": True, "llm": llm_label, "llm_error": LAST_ERROR.get("message"), "sandbox_docker": docker_available(),
            "ledger": ledger.verify()["ok"]}


# ====================================================================== v2: pipeline, agents, files, traffic
from app.domain.tables import AgentStep, MonitorAlert  # noqa: E402
from app.modelkit import registry as MR  # noqa: E402
from app.modelkit.traffic import sim, windows as traffic_windows  # noqa: E402


@api.get("/pipeline")
def pipeline_board():
    """One card per model: lifecycle stage, status, pending gate, agent recommendation."""
    with session() as s:
        ms = s.exec(select(Model).order_by(Model.id)).all()
        gates = {g.model_id: g for g in s.exec(select(Gate).where(Gate.status == "pending")).all()}
        runs = s.exec(select(Run).order_by(Run.started_at.desc())).all()
    latest = {}
    for r in runs:
        latest.setdefault((r.model_id, r.kind), r)
    cards = []
    for m in ms:
        lc = (m.meta or {}).get("lifecycle", {})
        g = gates.get(m.id)
        run = latest.get((m.id, "factory"))
        reval = latest.get((m.id, "revalidation"))
        a = MR.get(m.id)
        cards.append({
            "id": m.id, "name": m.name, "tier": m.tier, "type": m.type, "status": m.status,
            "stage": lc.get("stage", "discover"), "station": pipeline.STATION.get(lc.get("stage", "discover"), "discover"),
            "state": lc.get("status", "new"), "next": lc.get("next"), "recommendation": lc.get("recommendation"),
            "gate": ({"id": g.id, "title": g.title, "stage": g.stage, "context": g.context} if g else None),
            "run": _run_json(run) if run else None, "revalidation": _run_json(reval) if reval else None,
            "strategy": a.strategy if a else None, "deployable": a.deployable if a else False,
            "deployed": bool((m.meta or {}).get("deployed")), "parity": (m.meta or {}).get("parity_verdict"),
            "error": lc.get("error")})
    return {"cards": cards, "auto_promote": pipeline.get_setting("auto_promote", False)}


class BulkDecision(BaseModel):
    gate_ids: list[int]
    decision: str
    comment: str = ""
    decided_by: str = "Model Risk Officer"


@api.post("/gates/bulk-decision")
def bulk_decision(d: BulkDecision):
    if d.decision not in ("approved", "rejected", "changes_requested"):
        raise HTTPException(400, "bad decision")
    return {"results": pipeline.decide_many(d.gate_ids, d.decision, d.decided_by, d.comment)}


class SettingReq(BaseModel):
    value: bool | float | str | None


@api.get("/settings")
def get_settings():
    return {"auto_promote": pipeline.get_setting("auto_promote", False),
            "llm": {"provider": settings.llm_provider, "model": settings.llm_model, "fast_model": settings.llm_fast_model,
                    "mode": settings.llm_mode}}


@api.post("/settings/{key}")
def put_setting(key: str, req: SettingReq):
    if key not in ("auto_promote",):
        raise HTTPException(400, "unknown setting")
    pipeline.set_setting(key, req.value)
    ledger.append("human", "setting_changed", {"key": key, "value": req.value})
    if key == "auto_promote" and req.value:  # apply to gates already waiting where the agent recommends promote
        with session() as s:
            pend = s.exec(select(Gate).where(Gate.status == "pending")).all()
        ok = [g.id for g in pend if ((g.context or {}).get("agent") or {}).get("recommendation", "promote") == "promote"]
        if ok:
            pipeline.decide_many(ok, "approved", "auto-promote (agent recommendation)", "Auto-promote switched on.")
    return {"ok": True}


@api.post("/models/{model_id}/start")
def start_model(model_id: str):
    runs = pipeline.start_portfolio([model_id], False)
    return {"runs": [_run_json(r) for r in runs]}


# ---------------------------------------------------------------- agent traces
@api.get("/agents/runs")
def agent_runs():
    with session() as s:
        runs = s.exec(select(Run).order_by(Run.started_at.desc()).limit(60)).all()
        counts = dict(s.exec(select(AgentStep.run_id, func.count()).group_by(AgentStep.run_id)).all())
    return [{**_run_json(r), "steps": counts.get(r.id, 0)} for r in runs]


@api.get("/agents/steps")
def agent_steps(run_id: str, after: int = 0):
    with session() as s:
        rows = s.exec(select(AgentStep).where(AgentStep.run_id == run_id, AgentStep.id > after).order_by(AgentStep.id).limit(800)).all()
    return [{**r.model_dump(), "ts": _iso(r.ts)} for r in rows]


# ---------------------------------------------------------------- models folder / artifact browser
ROOTS = {"legacy": settings.legacy_dir, "data_room": settings.var_dir / "data_room", "runs": settings.runs_dir}


def _safe(root: str, rel: str):
    base = ROOTS.get(root)
    if base is None:
        raise HTTPException(400, "unknown root")
    p = (base / rel).resolve()
    if not str(p).startswith(str(base.resolve())):
        raise HTTPException(400, "path outside root")
    return base, p


@api.get("/files/tree")
def files_tree(root: str = "legacy", depth: int = 4):
    base, _ = _safe(root, "")
    if root == "data_room":
        from app.modelkit.data import build_room
        build_room()

    def walk(p, d):
        items = []
        for c in sorted(p.iterdir(), key=lambda c: (c.is_file(), c.name)):
            if c.name.startswith(".") or c.name == "__pycache__":
                continue
            node = {"name": c.name, "path": str(c.relative_to(base)), "dir": c.is_dir()}
            if c.is_dir():
                node["children"] = walk(c, d - 1) if d > 0 else []
            else:
                node["size"] = c.stat().st_size
            items.append(node)
        return items
    owner = {a.folder: a.id for a in MR.ADAPTERS.values()}
    return {"root": root, "tree": walk(base, depth) if base.exists() else [], "owners": owner}


@api.get("/files/read")
def files_read(root: str, path: str, limit: int = 400):
    import hashlib as _h
    base, p = _safe(root, path)
    if not p.is_file():
        raise HTTPException(404)
    raw = p.read_bytes()
    info = {"path": path, "size": len(raw), "sha256": _h.sha256(raw).hexdigest(),
            "modified": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()}
    if p.suffix in (".rds", ".png", ".pkl") or b"\x00" in raw[:2000]:
        return {**info, "binary": True}
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    info.update({"lines": len(lines), "text": "\n".join(lines[:limit]), "truncated": len(lines) > limit, "kind": p.suffix.lstrip(".")})
    if p.suffix == ".R" and root == "legacy":
        from app.tools.parsers import r_parser
        r = r_parser.parse(p)
        info["parse"] = {k: r[k] for k in ("id", "name", "owner", "methods", "libraries", "reads", "writes", "smells", "injection", "loc")}
    return info


# ---------------------------------------------------------------- live traffic monitoring
class ScenarioReq(BaseModel):
    scenario: str | None = None
    severity: float = 0.6
    ramp_s: int = 60


class RateReq(BaseModel):
    rpm: float | None = None
    enabled: bool | None = None


@api.get("/traffic")
def traffic_overview():
    out = []
    for mid, mt in list(sim.models.items()):
        w = traffic_windows(mid, 1)
        out.append({"model_id": mid, "cfg": mt.cfg, "severity_now": round(mt.severity(), 3), "total": mt.total,
                    "latest": w[-1] if w else None, "active_alerts": mt.active})
    return out


@api.get("/traffic/{model_id}")
def traffic_state(model_id: str, n: int = 90):
    st = sim.state(model_id)
    with session() as s:
        alerts = s.exec(select(MonitorAlert).where(MonitorAlert.model_id == model_id).order_by(MonitorAlert.id.desc()).limit(40)).all()
        revals = s.exec(select(Run).where(Run.model_id == model_id, Run.kind == "revalidation").order_by(Run.started_at.desc()).limit(10)).all()
    return {**st, "windows": traffic_windows(model_id, n), "alerts": [{**a.model_dump(), "ts": _iso(a.ts)} for a in alerts],
            "revalidations": [_run_json(r) for r in revals]}


@api.post("/traffic/{model_id}/scenario")
def traffic_scenario(model_id: str, req: ScenarioReq):
    if model_id not in sim.models:
        raise HTTPException(409, "model is not deployed")
    if req.scenario and req.scenario not in sim.models[model_id].a.scenarios:
        raise HTTPException(400, "unknown scenario")
    sim.set_scenario(model_id, req.scenario, req.severity, req.ramp_s)
    bus.publish("traffic", f"{model_id}: scenario {req.scenario or 'heal'} → severity {req.severity if req.scenario else 0} over {req.ramp_s}s",
                model_id=model_id, agent="human")
    return sim.state(model_id)


@api.post("/traffic/{model_id}/rate")
def traffic_rate(model_id: str, req: RateReq):
    if model_id not in sim.models:
        raise HTTPException(409, "model is not deployed")
    sim.set(model_id, **{k: v for k, v in req.model_dump().items() if v is not None})
    return sim.state(model_id)
