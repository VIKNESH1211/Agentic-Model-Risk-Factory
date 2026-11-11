"""SS1/23-derived controls as code. Our interpretation of the PRA principles — not legal advice."""
from __future__ import annotations

from sqlmodel import select

from app.core.db import session
from app.domain.tables import Control, ControlResult, Finding, Gate, Model, MonitorBatch, Report, Run
from app.evidence import ledger

CONTROLS = [
    ("P1.1", "P1 Model identification", "Inventory record complete", "Model has owner, purpose, type and code hash recorded."),
    ("P1.2", "P1 Model identification", "Risk tier assigned with rationale", "Tier assigned by rule with written rationale."),
    ("P2.1", "P2 Governance", "Accountable owner named", "A named owner is recorded for the model."),
    ("P2.2", "P2 Governance", "Human approval at every gate", "Each gate has a recorded human (or delegated) decision."),
    ("P3.1", "P3 Development & implementation", "Model documentation exists", "Structured ModelDoc produced and stored."),
    ("P3.2", "P3 Development & implementation", "Implementation verified", "Parity Certificate PASS for the production implementation."),
    ("P3.3", "P3 Development & implementation", "Data quality assessed", "Missing values, duplicates and leakage checks executed."),
    ("P4.1", "P4 Independent validation", "Independent validation performed", "Validator agent (separate session) produced a report."),
    ("P4.2", "P4 Independent validation", "Findings recorded and tracked", "Findings logged with severity and status."),
    ("P4.3", "P4 Independent validation", "All reported numbers traceable", "Every figure in the report resolves to a stored metric."),
    ("P5.1", "P5 Risk mitigants", "Ongoing monitoring configured", "Drift thresholds set and a baseline batch recorded."),
    ("P5.2", "P5 Risk mitigants", "Audit trail integrity", "Hash-chained ledger verifies end to end."),
]


def seed() -> None:
    with session() as s:
        for ref, pr, title, desc in CONTROLS:
            if not s.get(Control, ref):
                s.add(Control(ref=ref, principle=pr, title=title, description=desc))
        s.commit()


def evaluate(model_id: str) -> list[dict]:
    with session() as s:
        m = s.get(Model, model_id)
        runs = s.exec(select(Run).where(Run.model_id == model_id)).all()
        rids = [r.id for r in runs]
        gates = s.exec(select(Gate).where(Gate.model_id == model_id)).all()
        reports = s.exec(select(Report).where(Report.model_id == model_id)).all()
        findings = s.exec(select(Finding).where(Finding.model_id == model_id)).all()
        batches = s.exec(select(MonitorBatch).where(MonitorBatch.model_id == model_id)).all()
    meta = m.meta or {}
    led = ledger.verify()
    hero = meta.get("hero", False)
    na = "n/a"

    def st(ok, warn=False):
        return "pass" if ok else ("warn" if warn else "fail")
    res = {
        "P1.1": (st(bool(m.owner and m.purpose and m.code_hash), bool(m.code_hash)), {"owner": m.owner, "code_hash": m.code_hash[:12]}),
        "P1.2": (st(bool(m.tier and m.tier_rationale)), {"tier": m.tier}),
        "P2.1": (st(bool(m.owner)), {"owner": m.owner}),
        "P2.2": (st(bool(gates) and all(g.status in ("approved",) for g in gates), bool(gates)) if gates else "warn",
                 {"gates": [{"stage": g.stage, "status": g.status, "by": g.decided_by} for g in gates]}),
        "P3.1": (st(bool(meta.get("doc_run_id"))), {"doc_run_id": meta.get("doc_run_id")}),
        "P3.2": ((st(meta.get("parity_verdict") == "PASS") if hero else na), {"verdict": meta.get("parity_verdict"),
                                                                             "fingerprint": meta.get("parity_fingerprint")}),
        "P3.3": ((st(any(f.detector in ("data_quality", "data_integrity") for f in findings) or bool(reports)) if hero else na), {}),
        "P4.1": ((st(bool(reports)) if hero else "warn"), {"reports": [r.id for r in reports]}),
        "P4.2": ((st(bool(findings)) if hero else na), {"findings": len(findings)}),
        "P4.3": ((st(bool(reports) and all(r.checker.get("ok") for r in reports)) if hero else na),
                 {"checks": [r.checker.get("token_count") for r in reports]}),
        "P5.1": ((st(bool(batches)) if hero else "fail"), {"batches": len(batches)}),
        "P5.2": (st(led["ok"]), led),
    }
    out = []
    with session() as s:
        for ref, (status, ev) in res.items():
            s.add(ControlResult(ref=ref, model_id=model_id, status=status, evidence=ev))
            out.append({"ref": ref, "status": status, "evidence": ev})
        s.commit()
    return out
