"""Monitor agent: baseline, drift batches, alerts and the automatic re-validation trigger."""
from __future__ import annotations

from sqlmodel import select

from app.agents.common import StageCtx
from app.agents.redevelopment import load_model_module
from app.core.config import settings
from app.core.db import save, session
from app.core.events import bus
from app.domain.tables import Model, MonitorBatch
from app.evidence import ledger, metric_store
from app.tools import drift
from app.tools.datasets import prepared


def setup(ctx: StageCtx) -> dict:
    """Record thresholds and the validation-time baseline batch."""
    psi = metric_store.value(ctx.run_id, "psi.score.oot", 0.0)
    csi = {m.name.split(".")[1].replace("woe_", ""): round(m.value, 4)
           for m in metric_store.for_run(ctx.run_id) if m.name.startswith("csi.") and m.name.endswith(".oot")}
    b = ctx.tool("drift.baseline", "PSI/CSI thresholds amber 0.10 · red 0.25; baseline = out-of-time sample",
                 lambda: save(MonitorBatch(model_id=ctx.model_id, label="Baseline (OOT, simulated)", severity=0.0,
                                           feature_set="baseline", psi=psi, csi=csi,
                                           perf={"gini": metric_store.value(ctx.run_id, "gini.oot")},
                                           status=drift.status(psi, max(csi.values() or [0])))),
                 result_summary=lambda r: f"baseline status {r.status}")
    with session() as s:
        m = s.get(Model, ctx.model_id)
        m.status = "monitored"
        m.meta = {**m.meta, "validated_run_id": ctx.run_id, "monitoring": {"amber": drift.AMBER, "red": drift.RED}}
        s.add(m)
        s.commit()
    ledger.append("monitor", "monitoring_configured", {"run_id": ctx.run_id, "model_id": ctx.model_id,
                                                       "amber": drift.AMBER, "red": drift.RED})
    return {"baseline_batch": b.id}


def inject(model_id: str, severity: float, feature_set: str) -> MonitorBatch:
    with session() as s:
        m = s.get(Model, model_id)
    run_id = (m.meta or {}).get("validated_run_id")
    if not run_id:
        raise ValueError("Model has no validated run yet – run the factory first.")
    mod = load_model_module(settings.runs_dir / run_id / "model.py")
    d = prepared()
    model = mod.CR001Scorecard().fit(d[d["split"] == "train"])
    with session() as s:
        n = len(s.exec(select(MonitorBatch).where(MonitorBatch.model_id == model_id)).all())
    bus.publish("tool_call", f"drift.generate · {feature_set} shift, severity {severity:.2f} (simulated batch)",
                model_id=model_id, stage="monitor", agent="monitor")
    batch = drift.make_batch(d, severity, feature_set, seed=100 + n)
    res = drift.score_batch(model, d[d["split"] == "train"], batch)
    label = f"Batch {n} · {feature_set} · sev {severity:.2f}"
    out = settings.var_dir / "monitor" / model_id
    out.mkdir(parents=True, exist_ok=True)
    batch.to_csv(out / f"batch_{n}.csv", index=False)
    mb = save(MonitorBatch(model_id=model_id, label=label, severity=severity, feature_set=feature_set,
                           psi=res["psi"], csi=res["csi"], perf=res["perf"], status=res["status"]))
    ledger.append("monitor", "drift_batch_scored", {"model_id": model_id, "batch_id": mb.id, "psi": res["psi"],
                                                    "status": res["status"]})
    worst = max(res["csi"], key=res["csi"].get)
    bus.publish("monitor", f"PSI {res['psi']:.3f} · worst CSI {worst} {res['csi'][worst]:.3f} → {res['status'].upper()}",
                model_id=model_id, stage="monitor", agent="monitor",
                payload={"batch_id": mb.id, "psi": res["psi"], "csi": res["csi"], "status": res["status"]})
    if res["status"] == "red":
        bus.publish("alert", f"🚨 Drift alert on {model_id}: PSI/CSI breached red threshold – triggering re-validation",
                    model_id=model_id, stage="monitor", agent="monitor", payload={"batch_id": mb.id})
    return mb
