"""Evidence: reports, every number's provenance + Reproduce, findings, parity certificates, ledger, controls."""
from __future__ import annotations

import json

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import select

from app import repositories as repo
from app.api.common import iso, not_found, row_json, run_json
from app.core.config import settings
from app.core.db import session
from app.core.events import bus
from app.domain.tables import Control, Finding, LedgerEntry, Metric, Report, Run
from app.evidence import ledger, metric_store, tokens
from app.tools import controls
from app.tools import metrics as M

router = APIRouter(prefix="/api", tags=["evidence"])


def _find_report(report_id: str) -> Report:
    with session() as s:
        r = s.get(Report, report_id)
        if not r:  # a model id → its latest report
            r = s.exec(select(Report).where(Report.model_id == report_id).order_by(Report.created_at.desc())).first()
    if not r:
        raise not_found("report")
    return r


@router.get("/reports")
def list_reports(model_id: str | None = None):
    with session() as s:
        q = select(Report).order_by(Report.created_at.desc())
        if model_id:
            q = q.where(Report.model_id == model_id)
        return [{"id": r.id, "model_id": r.model_id, "version": r.version, "run_id": r.run_id, "title": r.title,
                 "checker_ok": r.checker.get("ok"), "tokens": r.checker.get("token_count"), "created_at": iso(r.created_at)}
                for r in s.exec(q).all()]


@router.get("/reports/{report_id}")
def get_report(report_id: str):
    r = _find_report(report_id)
    md, toks = tokens.resolve(r.markdown)
    with session() as s:
        versions = s.exec(select(Report).where(Report.model_id == r.model_id).order_by(Report.version)).all()
        run = s.get(Run, r.run_id)
    checks = settings.runs_dir / r.run_id / "validate" / "checks.json"
    return {"report": row_json(r), "markdown": md, "tokens": toks,
            "versions": [{"id": v.id, "version": v.version, "run_id": v.run_id} for v in versions],
            "run": run_json(run) if run else None,
            "checks": json.loads(checks.read_text()) if checks.exists() else None}


@router.get("/reports/{report_id}/diff")
def report_diff(report_id: str, against: str | None = None):
    r = _find_report(report_id)
    with session() as s:
        run = s.get(Run, r.run_id)
        base_id = against or (run.parent_run_id if run else None)
        if not base_id:
            prev = s.exec(select(Report).where(Report.model_id == r.model_id, Report.version < r.version)
                          .order_by(Report.version.desc())).first()
            base_id = prev.run_id if prev else None
    if not base_id:
        return {"base_run_id": None, "rows": []}
    checks = settings.runs_dir / r.run_id / "validate" / "checks.json"
    names = [c["metric_name"] for c in json.loads(checks.read_text())["results"]] if checks.exists() else []
    rows = []
    for n in names:
        a, b = metric_store.get(base_id, n), metric_store.get(r.run_id, n)
        if a and b:
            rows.append({"metric": n, "before": a.value, "after": b.value, "delta": b.value - a.value,
                         "before_display": tokens.fmt(n, a.value), "after_display": tokens.fmt(n, b.value),
                         "before_token": metric_store.token(base_id, n), "after_token": metric_store.token(r.run_id, n)})
    rows.sort(key=lambda x: -abs(x["delta"]))
    with session() as s:
        ta = {f.title for f in s.exec(select(Finding).where(Finding.run_id == base_id)).all()}
        fb = s.exec(select(Finding).where(Finding.run_id == r.run_id)).all()
    return {"base_run_id": base_id, "run_id": r.run_id, "rows": rows[:20], "new_findings": [f.model_dump() for f in fb if f.title not in ta]}


def _chart(m: Metric) -> dict | None:
    rcp = m.recipe
    try:
        if not rcp.get("artifact"):
            return None
        df = metric_store.load_artifact(rcp["artifact"])
        if rcp.get("fn") in ("gini", "auc", "ks"):
            d = metric_store._split(df, rcp)
            return {"kind": "roc", "points": M.roc_points(d[rcp.get("target", "y")], d[rcp.get("score", "score")])}
        if rcp.get("fn") in ("calibration_ratio", "max_decile_gap", "brier"):
            d = metric_store._split(df, rcp)
            g = M.calibration_deciles(d[rcp.get("target", "y")], d[rcp.get("score", "score")])
            return {"kind": "calibration", "points": g.round(4).to_dict("records")}
        if rcp.get("fn") == "psi":
            base, comp = df[df["split"] == rcp["base"]][rcp["col"]], df[df["split"] == rcp["comp"]][rcp["col"]]
            if rcp.get("categorical"):
                b = base.astype(str).value_counts(normalize=True)
                c = comp.astype(str).value_counts(normalize=True)
                keys = sorted(set(b.index) | set(c.index))[:20]
                return {"kind": "dist", "points": [{"bin": k[:18], "base": float(b.get(k, 0)), "comp": float(c.get(k, 0))} for k in keys]}
            edges = np.unique(np.quantile(base.dropna().astype(float), np.linspace(0, 1, 11)))
            edges[0], edges[-1] = -np.inf, np.inf
            bh = np.histogram(base.dropna().astype(float), edges)[0] / max(base.notna().sum(), 1)
            ch = np.histogram(comp.dropna().astype(float), edges)[0] / max(comp.notna().sum(), 1)
            return {"kind": "dist", "points": [{"bin": f"D{i + 1}", "base": float(a), "comp": float(b)} for i, (a, b) in enumerate(zip(bh, ch))]}
        if rcp.get("fn") in ("di_ratio", "dp_diff", "group_mean_ratio") and rcp.get("group"):
            d = metric_store._split(df, rcp)
            col = rcp.get("col") or rcp.get("approve", "approve")
            g = d.groupby(d[rcp["group"]].astype(str))[col].mean()
            return {"kind": "groups", "points": [{"group": k, "value": round(float(v), 4)} for k, v in g.items()]}
    except Exception:
        return None
    return None


@router.get("/evidence/{token}")
def evidence(token: str):
    try:
        run_id, name = tokens.parse(token)
    except ValueError:
        raise HTTPException(400, "bad token")
    m = metric_store.get(run_id, name)
    if not m:
        raise not_found("metric")
    with session() as s:
        run = s.get(Run, run_id)
        led = s.get(LedgerEntry, m.ledger_seq) if m.ledger_seq else None
    return {"token": token, "name": name, "value": m.value, "display": tokens.fmt(name, m.value), "definition": m.definition,
            "split": m.split, "slice": m.slice, "recipe": {k: v for k, v in m.recipe.items() if k != "features"},
            "run": run_json(run) if run else None, "code_hash": m.code_hash, "data_hash": m.data_hash,
            "artifact": m.recipe.get("artifact"), "source": metric_store.source_of(m.recipe["fn"]),
            "ledger": {"seq": led.seq, "entry_hash": led.entry_hash, "action": led.action} if led else None,
            "created_at": iso(m.created_at), "chart": _chart(m)}


@router.post("/evidence/{token}/reproduce")
def reproduce(token: str):
    run_id, name = tokens.parse(token)
    m = metric_store.get(run_id, name)
    if not m:
        raise not_found("metric")
    res = metric_store.reproduce(m)
    ledger.append("human", "metric_reproduced", {"run_id": run_id, "metric": name, "match": res.get("match")})
    return res


# ------------------------------------------------------------------ findings
class FindingUpdate(BaseModel):
    status: str  # open | accepted | remediated | dismissed
    comment: str = ""
    by: str = "Model Risk Officer"


@router.get("/findings")
def findings(model_id: str | None = None, severity: str | None = None, status: str | None = None):
    with session() as s:
        q = select(Finding).order_by(Finding.id.desc())
        for col, v in (("model_id", model_id), ("severity", severity), ("status", status)):
            if v:
                q = q.where(getattr(Finding, col) == v)
        return [f.model_dump() for f in s.exec(q).all()]


@router.patch("/findings/{finding_id}")
def update_finding(finding_id: int, u: FindingUpdate):
    if u.status not in ("open", "accepted", "remediated", "dismissed"):
        raise HTTPException(400, "bad status")
    with session() as s:
        f = s.get(Finding, finding_id)
        if not f:
            raise not_found("finding")
        f.status = u.status
        f.evidence = {**(f.evidence or {}), "status_comment": u.comment, "status_by": u.by}
        s.add(f)
        s.commit()
        s.refresh(f)
    ledger.append("human", "finding_status", {"finding_id": finding_id, "model_id": f.model_id, "status": u.status, "by": u.by})
    return f.model_dump()


# ------------------------------------------------------------------ parity certificate
@router.get("/models/{model_id}/parity")
def parity(model_id: str):
    m = repo.models.get(model_id)
    if not m:
        raise not_found("model")
    pr = (m.meta or {}).get("parity_run_id")
    if not pr:
        raise HTTPException(404, f"{model_id} has no parity certificate yet")
    d = settings.runs_dir / pr
    cert = json.loads((d / "parity_certificate.json").read_text())
    names = ("score_max_abs_diff", "coef_max_abs_diff", "decision_agreement", "rows_compared", "rows_scored", "legacy_runtime_s")
    toks = {n: metric_store.token(pr, n) for n in names if metric_store.get(pr, n)}
    sample = None
    if (d / "parity" / "parity_scores.csv").exists():
        import pandas as pd
        ps = pd.read_csv(d / "parity" / "parity_scores.csv")
        diff = (ps["legacy_score"] - ps["py_score"]).abs()
        hist = []
        if (diff > 0).any():
            counts, edges = np.histogram(np.log10(diff[diff > 0]), bins=12)
            hist = [{"lo": float(edges[i]), "hi": float(edges[i + 1]), "n": int(counts[i])} for i in range(len(counts))]
        sample = {"scatter": ps.sample(min(400, len(ps)), random_state=1)[["legacy_score", "py_score"]].round(6).to_dict("records"),
                  "hist": hist, "exact": int((diff == 0).sum()), "rows": int(len(ps)),
                  "max": float(diff.max()) if len(diff) else 0}
    coef = None
    if (d / "parity" / "parity_coef.csv").exists():
        import pandas as pd
        coef = pd.read_csv(d / "parity" / "parity_coef.csv").to_dict("records")
    code = (d / "model.py").read_text() if (d / "model.py").exists() else None
    epi = (d / "epilogue.R").read_text() if (d / "epilogue.R").exists() else None
    return {"certificate": cert, "tokens": toks, "sample": sample, "coef": coef, "python": code, "epilogue": epi}


# ------------------------------------------------------------------ ledger + controls
@router.get("/ledger")
def get_ledger(limit: int = Query(400, le=5000), model_id: str | None = None):
    es = ledger.entries()
    if model_id:
        es = [e for e in es if (e.payload or {}).get("model_id") == model_id]
    return {"total": len(es), "entries": [e.model_dump() for e in es[-limit:]]}


@router.post("/ledger/verify")
def verify_ledger():
    v = ledger.verify()
    bus.publish("info", f"⛓ Ledger verify: {'intact' if v['ok'] else 'BROKEN at #' + str(v['broken_at'])}", agent="governance", payload=v)
    return v


@router.post("/ledger/_tamper")
def tamper(seq: int | None = None):
    if not settings.allow_tamper_demo:
        raise HTTPException(403, "tamper demo disabled")
    r = ledger.tamper(seq)
    bus.publish("alert", f"☠ Demo: ledger entry #{r.get('seq')} silently edited in the database", agent="attacker", payload=r)
    return r


@router.get("/controls/coverage")
def coverage():
    with session() as s:
        ctl = s.exec(select(Control).order_by(Control.ref)).all()
    ms = repo.models.list()
    return {"controls": [c.model_dump() for c in ctl], "models": [m.id for m in ms],
            "matrix": {m.id: {r["ref"]: r for r in controls.evaluate(m.id)} for m in ms},
            "disclaimer": "Controls are this team's interpretation of PRA SS1/23 principles, not legal advice."}
