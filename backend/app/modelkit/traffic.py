"""Simulated live traffic for deployed models, with real scoring, measured latency and delayed outcomes.

Requests are sampled from each model's hold-out population, optionally pushed through a drift scenario
that ramps gradually, and scored one at a time by the certified Python endpoint (latency is measured, not
invented). Outcomes (default / claim / fraud label) "mature" OUTCOME_DELAY seconds later — standing in
for a 12-month performance window. Every WINDOW seconds the KPIs are closed into a persisted window,
alert rules are evaluated, and a red breach triggers automatic re-validation on recent traffic.
"""
from __future__ import annotations

import math
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlmodel import delete, select

from app.core.config import settings
from app.core.db import save, session
from app.core.events import bus
from app.domain.tables import Model, MonitorAlert, MonitorWindow, Run
from app.evidence import ledger
from app.modelkit import registry as R
from app.modelkit import serving
from app.tools import metrics as M

WINDOW = 10.0          # seconds per KPI window
OUTCOME_DELAY = 40.0   # seconds until an outcome is known (stands in for ~12 months)
TICK = 0.5
RULES = {  # rule: (kpi, comparator, threshold, consecutive windows, severity)
    "score_psi_red": ("psi", ">", 0.25, 3, "red"),
    "score_psi_amber": ("psi", ">", 0.10, 3, "amber"),
    "input_csi_red": ("worst_csi", ">", 0.25, 3, "red"),
    "latency_p95": ("latency_p95_ms", ">", 150.0, 3, "amber"),
    "no_decision": ("no_decision_rate", ">", 0.02, 2, "amber"),
    "ae_low": ("ae_ratio", "<", 0.80, 3, "red"),
    "ae_high": ("ae_ratio", ">", 1.25, 3, "red"),
}
DEFAULT_RPM = {"CR-001": 300, "CR-003": 180, "PR-001": 240, "FR-001": 480}
MIN_PSI_N = 200  # rolling requests needed before PSI/CSI is computed (avoids small-sample false alarms)


def _now():
    return datetime.now(timezone.utc)


class ModelTraffic:
    def __init__(self, model_id: str, cfg: dict):
        self.model_id = model_id
        self.a = R.get(model_id)
        self.ep = serving.get(model_id)
        self.pool = self.a.traffic_pool().reset_index(drop=True)
        self.rng = np.random.default_rng(abs(hash(model_id)) % 2**32)
        self.cfg = {"enabled": True, "rpm": DEFAULT_RPM.get(model_id, 120), "scenario": None, "severity": 0.0,
                    "ramp_s": 60, "ramp_from": 0.0, "ramp_start": time.time(), **cfg}
        base = self.pool.sample(min(800, len(self.pool)), random_state=1)
        self.base_rows = base
        self.base_scores = self.ep.predict(base)["score"].to_numpy(float)
        self.feats = [f for f in self.a.spec.features if f in base.columns]
        self.reqs: deque = deque(maxlen=6000)        # every request (for tail + rolling stats)
        self.rows: deque = deque(maxlen=600)          # recent full rows (for re-validation)
        self.streak: dict[str, int] = {}
        self.active: dict[str, str] = {}
        self.window_start = time.time()
        self.total = 0
        self.last_reval = 0.0

    # ---------------------------------------------------------------- drift ramp
    def severity(self) -> float:
        c = self.cfg
        if not c.get("scenario"):
            return 0.0
        f = min(1.0, (time.time() - c["ramp_start"]) / max(c["ramp_s"], 1))
        return c["ramp_from"] + (c["severity"] - c["ramp_from"]) * f

    # ---------------------------------------------------------------- one tick
    def tick(self):
        if not self.cfg.get("enabled"):
            return
        t = time.time()
        wave = 1 + 0.35 * math.sin(2 * math.pi * t / 120)  # a compressed "daily" cycle
        n = self.rng.poisson(self.cfg["rpm"] / 60 * TICK * wave)
        if n == 0:
            return
        rows = self.pool.iloc[self.rng.integers(0, len(self.pool), n)].reset_index(drop=True)
        sev = self.severity()
        if self.cfg.get("scenario") and sev > 0:
            rows = self.a.drift(rows, self.cfg["scenario"], sev, self.rng)
        for i in range(n):
            row = rows.iloc[[i]]
            t0 = time.perf_counter()
            err = False
            try:
                out = self.ep.predict(row)
                score = float(out["score"].iloc[0]) if pd.notna(out["score"].iloc[0]) else float("nan")
                dec = out["decision"].iloc[0]
            except Exception:
                err, score, dec = True, float("nan"), None
            lat = (time.perf_counter() - t0) * 1000
            self.total += 1
            rid = f"{self.model_id[:2]}-{self.total:07d}"
            r = {"ts": t, "req": rid, "row_id": row["id"].iloc[0], "latency_ms": round(lat, 2), "score": score,
                 "decision": None if dec is None else str(dec), "error": err, "matures": t + OUTCOME_DELAY,
                 "outcome": self._outcome(row), "exposure": float(row["exposure"].iloc[0]) if "exposure" in row else 1.0,
                 "sev": round(sev, 3), "feats": {f: (row[f].iloc[0].item() if hasattr(row[f].iloc[0], "item") else row[f].iloc[0])
                                                 for f in self.feats}}
            self.reqs.append(r)
            full = row.iloc[0].to_dict()
            if self.model_id == "CR-003" and "upstream_pd" in out:
                full["pd"] = float(out["upstream_pd"].iloc[0])
                full["decision"] = "DECLINE" if full["pd"] > 0.35 else "APPROVE"
            self.rows.append(full)
        if t - self.window_start >= WINDOW:
            self.close_window()

    def _outcome(self, row):
        tgt = self.a.spec.target
        if self.model_id in ("CR-001", "CR-003"):
            return int(row["creditability"].iloc[0] == "bad")
        if tgt and tgt in row:
            return float(row[tgt].iloc[0])
        return None

    # ---------------------------------------------------------------- KPIs
    def close_window(self):
        t = time.time()
        w = [r for r in self.reqs if r["ts"] >= self.window_start]
        self.window_start = t
        if not w:
            return
        lat = np.array([r["latency_ms"] for r in w])
        sc = np.array([r["score"] for r in w], float)
        k: dict = {"requests": len(w), "rpm": round(len(w) * 60 / WINDOW, 1),
                   "latency_p50_ms": round(float(np.percentile(lat, 50)), 2), "latency_p95_ms": round(float(np.percentile(lat, 95)), 2),
                   "error_rate": round(float(np.mean([r["error"] for r in w])), 4),
                   "no_decision_rate": round(float(np.mean(np.isnan(sc))), 4),
                   "mean_score": round(float(np.nanmean(sc)), 5) if np.isfinite(sc).any() else None,
                   "severity": w[-1]["sev"], "scenario": self.cfg.get("scenario"), "total": self.total}
        decs = [r["decision"] for r in w]
        kind = self.a.spec.decision_kind
        if kind == "approve":
            k["decision_rate"] = round(float(np.mean([d == "APPROVE" for d in decs])), 4)
        elif kind == "alert":
            k["decision_rate"] = round(float(np.mean([d == "ALERT" for d in decs])), 4)
        elif kind == "limit":
            k["decision_rate"] = round(float(np.mean([d == "LIMIT" for d in decs])), 4)
            k["cap_share"] = round(float(np.mean(sc[np.isfinite(sc)] >= 15000)) if np.isfinite(sc).any() else 0, 4)
        recent = list(self.reqs)[-400:]
        rs = np.array([r["score"] for r in recent], float)
        rs = rs[np.isfinite(rs)]
        k["psi_n"] = len(rs)
        if len(rs) >= MIN_PSI_N:
            k["psi"] = round(M.psi(self.base_scores[np.isfinite(self.base_scores)], rs), 4)
            worst, wv = None, 0.0
            for f in self.feats:
                cur = pd.Series([r["feats"].get(f) for r in recent])
                ref = self.base_rows[f]
                cat = not pd.api.types.is_numeric_dtype(ref) or ref.nunique() <= 12
                v = M.psi_categorical(ref.astype(str), cur.astype(str)) if cat else M.psi(ref.astype(float), cur.astype(float))
                if v > wv:
                    worst, wv = f, v
            k["worst_csi"], k["worst_csi_feature"] = round(wv, 4), worst
        mat = [r for r in self.reqs if r["matures"] <= t and r["outcome"] is not None and np.isfinite(r["score"])]
        mat = mat[-(1500 if self.model_id == "FR-001" else 500):]
        k["matured"] = len(mat)
        if len(mat) >= 100 and self.a.spec.task in ("binary", "frequency"):
            y = np.array([r["outcome"] for r in mat], float)
            p = np.array([r["score"] for r in mat], float)
            ex = np.array([r["exposure"] for r in mat], float)
            if self.a.spec.task == "frequency":
                k["realized_rate"] = round(float(y.sum() / ex.sum()), 5)
                k["predicted_rate"] = round(float((p * ex).sum() / ex.sum()), 5)
                k["ae_ratio"] = round(float(y.sum() / max((p * ex).sum(), 1e-9)), 4)
            else:
                k["realized_rate"] = round(float(y.mean()), 5)
                k["predicted_rate"] = round(float(p.mean()), 5)
                if y.sum() >= 5 and (len(y) - y.sum()) >= 5:
                    k["realized_gini"] = round(M.gini(y, p), 4)
                if self.model_id == "FR-001" and y.sum() >= 3:
                    k["realized_recall"] = round(float(((p > 0.5) & (y == 1)).sum() / y.sum()), 4)
                if self.model_id != "FR-001":
                    k["ae_ratio"] = round(float(y.mean() / max(p.mean(), 1e-9)), 4)
        status = self.evaluate(k)
        save(MonitorWindow(model_id=self.model_id, kpis=k, status=status))
        bus.publish("traffic", f"{self.model_id} · {k['requests']} req · p95 {k['latency_p95_ms']}ms · PSI {k.get('psi', '—')} → {status}",
                    model_id=self.model_id, stage="monitor", agent="monitor", payload={"kpis": k, "status": status})

    def evaluate(self, k: dict) -> str:
        worst = "green"
        for name, (kpi, op, thr, need, sev) in RULES.items():
            v = k.get(kpi)
            if kpi == "ae_ratio" and k.get("matured", 0) < 200:
                v = None
            hit = v is not None and ((v > thr) if op == ">" else (v < thr))
            self.streak[name] = self.streak.get(name, 0) + 1 if hit else 0
            if self.streak[name] >= need:
                worst = "red" if sev == "red" or worst == "red" else "amber"
                if name not in self.active:
                    self.active[name] = sev
                    self.raise_alert(name, kpi, v, thr, sev)
            elif not hit and name in self.active:
                del self.active[name]
                bus.publish("monitor", f"✓ {self.model_id}: {name} back within threshold", model_id=self.model_id,
                            stage="monitor", agent="monitor")
            elif hit and worst == "green" and RULES[name][4] == "red":
                worst = "amber"  # an early red-rule breach shows as a warning before it confirms
        return worst

    def raise_alert(self, rule, kpi, v, thr, sev):
        msg = f"{kpi} = {v:.3f} breached {thr} for {RULES[rule][3]} consecutive windows"
        action = ""
        reval = None
        if sev == "red" and time.time() - self.last_reval > 120:
            reval = trigger_revalidation(self.model_id, rule, list(self.rows))
            self.last_reval = time.time()
            action = "automatic re-validation started" if reval else ""
        al = save(MonitorAlert(model_id=self.model_id, rule=rule, severity=sev, message=msg, value=float(v or 0),
                               action=action, revalidation_run_id=reval))
        ledger.append("monitor", "monitor_alert", {"model_id": self.model_id, "rule": rule, "severity": sev, "value": v,
                                                   "alert_id": al.id, "revalidation_run_id": reval})
        bus.publish("alert", f"{'🚨' if sev == 'red' else '⚠'} {self.model_id}: {msg}" + (f" → {action}" if action else ""),
                    model_id=self.model_id, stage="monitor", agent="monitor", payload={"alert_id": al.id, "rule": rule})


def trigger_revalidation(model_id: str, rule: str, rows: list[dict]) -> str | None:
    from app.orchestrator import pipeline
    with session() as s:
        m = s.get(Model, model_id)
        busy = s.exec(select(Run).where(Run.model_id == model_id, Run.kind == "revalidation",
                                        Run.status.in_(["queued", "running"]))).first()
    if busy or not (m.meta or {}).get("validated_run_id") or len(rows) < 150:
        return None
    out = settings.var_dir / "monitor" / model_id
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"recent_{int(time.time())}.csv"
    pd.DataFrame(rows[-400:]).to_csv(f, index=False)
    r = pipeline.create_run(model_id, kind="revalidation", auto_approve=False, parent=m.meta["validated_run_id"],
                            extra={"recent_file": str(f), "batch_label": f"live traffic · {rule}"})
    pipeline.start(r.id)
    return r.id


# ==================================================================== simulator loop
class Simulator:
    def __init__(self):
        self.models: dict[str, ModelTraffic] = {}
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.stop_flag = False

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_flag = False
        self.thread = threading.Thread(target=self._loop, name="traffic", daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stop_flag:
            t0 = time.time()
            with self.lock:
                items = list(self.models.values())
            for mt in items:
                try:
                    mt.tick()
                except Exception:
                    traceback.print_exc()
            time.sleep(max(0.05, TICK - (time.time() - t0)))

    def deploy(self, model_id: str) -> dict:
        with session() as s:
            m = s.get(Model, model_id)
            cfg = (m.meta or {}).get("traffic", {})
        mt = ModelTraffic(model_id, cfg)
        with self.lock:
            self.models[model_id] = mt
        self.persist(model_id)
        self.start()
        return mt.cfg

    def persist(self, model_id: str):
        mt = self.models.get(model_id)
        if not mt:
            return
        with session() as s:
            m = s.get(Model, model_id)
            m.meta = {**(m.meta or {}), "deployed": True, "traffic": mt.cfg}
            s.add(m)
            s.commit()

    def restore(self):
        """On startup: every model that was deployed comes back with its saved traffic settings."""
        with session() as s:
            ids = [m.id for m in s.exec(select(Model)).all() if (m.meta or {}).get("deployed")]
        for mid in ids:
            try:
                self.deploy(mid)
            except Exception:
                traceback.print_exc()

    def set_scenario(self, model_id: str, scenario: str | None, severity: float, ramp_s: int):
        mt = self.models[model_id]
        cur = mt.severity()
        mt.cfg.update({"scenario": scenario or mt.cfg.get("scenario"), "severity": severity if scenario else 0.0,
                       "ramp_from": cur, "ramp_start": time.time(), "ramp_s": ramp_s})
        if not scenario:  # heal: ramp back to zero, then clear
            mt.cfg["severity"] = 0.0
        self.persist(model_id)
        ledger.append("human", "traffic_scenario", {"model_id": model_id, "scenario": mt.cfg["scenario"], "severity": mt.cfg["severity"],
                                                    "ramp_s": ramp_s})

    def set(self, model_id: str, **kw):
        self.models[model_id].cfg.update(kw)
        self.persist(model_id)

    def state(self, model_id: str, tail: int = 25) -> dict:
        mt = self.models.get(model_id)
        if not mt:
            return {"deployed": False}
        reqs = list(mt.reqs)[-tail:][::-1]
        return {"deployed": True, "cfg": mt.cfg, "severity_now": round(mt.severity(), 3), "total": mt.total,
                "active_alerts": mt.active, "rules": {k: {"kpi": v[0], "op": v[1], "threshold": v[2], "windows": v[3], "severity": v[4]}
                                                      for k, v in RULES.items()},
                "tail": [{k: v for k, v in r.items() if k != "feats"} | {"inputs": r["feats"]} for r in reqs],
                "scenarios": mt.a.scenarios, "window_s": WINDOW, "outcome_delay_s": OUTCOME_DELAY,
                "decision_kind": mt.a.spec.decision_kind, "version": mt.ep.version}

    def reset(self):
        with self.lock:
            self.models.clear()


sim = Simulator()


def windows(model_id: str, n: int = 90) -> list[dict]:
    with session() as s:
        rows = s.exec(select(MonitorWindow).where(MonitorWindow.model_id == model_id).order_by(MonitorWindow.id.desc()).limit(n)).all()
    return [{"ts": w.ts.replace(tzinfo=timezone.utc).isoformat() if w.ts.tzinfo is None else w.ts.isoformat(), "status": w.status, **w.kpis}
            for w in rows][::-1]


def prune(keep_hours: float = 6.0):
    with session() as s:
        s.exec(delete(MonitorWindow).where(MonitorWindow.ts < _now() - timedelta(hours=keep_hours)))
        s.commit()
