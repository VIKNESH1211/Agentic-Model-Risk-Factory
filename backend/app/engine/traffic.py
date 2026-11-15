"""Simulated live traffic for every deployed model, driven by its approved monitoring plan.

Requests are sampled from the model's hold-out rows (legacy export), pushed through the plan's drift scenario
(declarative transforms, ramped in gradually) and scored one at a time by the certified endpoint (latency is
measured). Outcomes "mature" OUTCOME_DELAY seconds later (standing in for the real performance window). Every
WINDOW seconds the KPIs are closed into a persisted window and the plan's alert rules are evaluated; a red rule
with action "revalidate" starts an automatic re-validation run (diagnose → validate → report → human).
Nothing here knows which model it is serving.
"""
from __future__ import annotations

import math
import operator
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlmodel import delete, select

from app import repositories as repo
from app.core.config import settings
from app.core.db import save, session
from app.core.events import bus
from app.domain.schemas import AlertRule, ModelSpec, MonitoringPlan, Scenario
from app.domain.tables import MonitorAlert, MonitorWindow, Run
from app.engine import scoring, serving
from app.evidence import ledger
from app.tools import metrics as M

WINDOW = 10.0
OUTCOME_DELAY = 40.0
TICK = 0.5
MIN_PSI_N = 200
OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}
# KPIs measured on matured outcomes: too noisy to alert on until enough requests have matured
OUTCOME_KPIS = {"ae_ratio", "realized_gini", "realized_ks", "realized_recall", "realized_precision", "brier"}


def _now():
    return datetime.now(timezone.utc)


def apply_scenario(rows: pd.DataFrame, sc: Scenario, sev: float, rng: np.random.Generator, spec: ModelSpec) -> pd.DataFrame:
    r = rows.copy()
    for t in sc.transforms:
        if t.column not in r.columns:
            continue
        hit = rng.random(len(r)) < min(1.0, t.fraction * sev)
        if t.op in ("scale", "shift"):
            v = pd.to_numeric(r[t.column], errors="coerce").astype(float)
            amt = float(t.value) * sev
            r[t.column] = np.where(hit, v * (1 + amt) if t.op == "scale" else v + amt, v)
        elif t.op == "set_category":
            r[t.column] = r[t.column].astype(object)
            r.loc[hit, t.column] = t.value
        elif t.op == "null_rate":
            r[t.column] = r[t.column].astype(object)
            r.loc[hit, t.column] = np.nan
        elif t.op == "flip_target" and spec.target == t.column:
            col = r[t.column]
            if pd.api.types.is_numeric_dtype(col):
                r.loc[hit, t.column] = 1
            else:  # text outcome (good/bad…): set the adverse level
                levels = [str(x) for x in col.dropna().unique()]
                bad = next((v for v in levels if v.lower() in ("bad", "1", "yes", "default", "fraud", "true")), levels[0] if levels else 1)
                r.loc[hit, t.column] = bad
    return r


class ModelTraffic:
    def __init__(self, model_id: str, cfg: dict):
        from app.services import plans, specs
        self.model_id = model_id
        self.spec: ModelSpec = specs.current(model_id)
        self.plan: MonitoringPlan = plans.current(model_id, "monitoring") or MonitoringPlan()
        self.ep = serving.get(model_id)
        if self.ep is None:
            raise RuntimeError(f"{model_id} has no certified Python endpoint")
        b = self.ep.bundle
        sp = scoring.splits(b.n, b.frame[".row"].to_numpy(), b.train_rows)
        hold = b.frame[sp != "train"] if (sp != "train").sum() >= 50 else b.frame
        self.pool = hold.reset_index(drop=True)
        self.rng = np.random.default_rng(abs(hash(model_id)) % 2**32)
        self.cfg = {"enabled": True, "rpm": self.plan.rpm or 240, "scenario": None, "severity": 0.0, "ramp_s": 60,
                    "ramp_from": 0.0, "ramp_start": time.time(), **cfg}
        base = self.pool.sample(min(800, len(self.pool)), random_state=1)
        self.base_rows = base
        bp = self.ep.predict(base)
        self.base_scores = bp["score"].to_numpy(float)
        self.base_adverse = float(pd.to_numeric(bp["flag"], errors="coerce").fillna(0).mean()) if "flag" in bp else 0.0
        self.feats = [f for f in self.spec.features if f in base.columns]
        # baseline profile of every input: numeric range, or the set of known categories
        self.cat_feats, self.ranges, self.levels = set(), {}, {}
        for f in self.feats:
            col = self.pool[f]
            if not pd.api.types.is_numeric_dtype(col) or col.nunique() <= 12:
                self.cat_feats.add(f)
                self.levels[f] = set(col.dropna().astype(str))
            else:
                v = col.astype(float)
                self.ranges[f] = (float(v.min()), float(v.max()), float(v.mean()), float(v.std() or 1.0))
        self.base_missing = {f: float(self.pool[f].isna().mean()) for f in self.feats}
        self.reqs: deque = deque(maxlen=6000)
        self.rows: deque = deque(maxlen=600)
        self.streak: dict[str, int] = {}
        self.active: dict[str, str] = {}
        self.window_start = time.time()
        self.total = 0
        self.last_reval = 0.0

    # ------------------------------------------------------------ drift ramp
    def scenario(self) -> Scenario | None:
        return next((s for s in self.plan.scenarios if s.id == self.cfg.get("scenario")), None)

    def severity(self) -> float:
        if not self.cfg.get("scenario"):
            return 0.0
        f = min(1.0, (time.time() - self.cfg["ramp_start"]) / max(self.cfg["ramp_s"], 1))
        return self.cfg["ramp_from"] + (self.cfg["severity"] - self.cfg["ramp_from"]) * f

    def _outcome(self, row: pd.DataFrame):
        t = self.spec.target
        if not t or t not in row:
            return None
        v = row[t].iloc[0]
        if isinstance(v, str):
            return 1.0 if v.lower() in ("bad", "1", "yes", "default", "fraud", "true") else 0.0
        return None if pd.isna(v) else float(v)

    # ------------------------------------------------------------ one tick
    def tick(self):
        if not self.cfg.get("enabled"):
            return
        t = time.time()
        wave = 1 + 0.35 * math.sin(2 * math.pi * t / 120)  # a compressed "daily" cycle
        n = self.rng.poisson(self.cfg["rpm"] / 60 * TICK * wave)
        if n:
            rows = self.pool.iloc[self.rng.integers(0, len(self.pool), n)].reset_index(drop=True)
            sev, sc = self.severity(), self.scenario()
            if sc and sev > 0:
                rows = apply_scenario(rows, sc, sev, self.rng, self.spec)
            for i in range(n):
                row = rows.iloc[[i]]
                t0 = time.perf_counter()
                err = False
                try:
                    out = self.ep.predict(row)
                    score = float(out["score"].iloc[0]) if pd.notna(out["score"].iloc[0]) else float("nan")
                    flag = int(out["flag"].iloc[0])
                except Exception:
                    err, score, flag = True, float("nan"), 0
                lat = (time.perf_counter() - t0) * 1000
                self.total += 1
                self.reqs.append({"ts": t, "req": f"{self.model_id[:3]}-{self.total:07d}", "latency_ms": round(lat, 2), "score": score,
                                  "flag": flag, "error": err, "matures": t + OUTCOME_DELAY, "outcome": self._outcome(row),
                                  "exposure": float(row[self.spec.exposure].iloc[0]) if self.spec.exposure and self.spec.exposure in row else 1.0,
                                  "sev": round(sev, 3),
                                  "feats": {f: (row[f].iloc[0].item() if hasattr(row[f].iloc[0], "item") else row[f].iloc[0]) for f in self.feats}})
                self.rows.append(row.iloc[0].to_dict())
        if t - self.window_start >= WINDOW:
            self.close_window()

    # ------------------------------------------------------------ KPIs
    def close_window(self):
        t = time.time()
        w = [r for r in self.reqs if r["ts"] >= self.window_start]
        self.window_start = t
        if not w:
            return
        lat = np.array([r["latency_ms"] for r in w])
        sc = np.array([r["score"] for r in w], float)
        fin = sc[np.isfinite(sc)]
        err = float(np.mean([r["error"] for r in w]))
        adverse = float(np.mean([r["flag"] for r in w]))
        k: dict = {
            # operations
            "requests": len(w), "rpm": round(len(w) * 60 / WINDOW, 1),
            "latency_p50_ms": round(float(np.percentile(lat, 50)), 2), "latency_p95_ms": round(float(np.percentile(lat, 95)), 2),
            "latency_p99_ms": round(float(np.percentile(lat, 99)), 2), "latency_max_ms": round(float(lat.max()), 2),
            "error_rate": round(err, 4), "availability": round(1 - err, 4),
            "no_decision_rate": round(float(np.mean(np.isnan(sc))), 4),
            # decisions & score shape
            "mean_score": round(float(fin.mean()), 5) if len(fin) else None,
            "score_p50": round(float(np.median(fin)), 5) if len(fin) else None,
            "score_std": round(float(fin.std()), 5) if len(fin) > 1 else None,
            "adverse_rate": round(adverse, 4), "adverse_rate_shift": round(adverse - self.base_adverse, 4),
            "severity": w[-1]["sev"], "scenario": self.cfg.get("scenario"), "total": self.total}
        k.update(self._data_quality(w))
        recent = list(self.reqs)[-400:]
        rs = np.array([r["score"] for r in recent], float)
        rs = rs[np.isfinite(rs)]
        k["psi_n"] = len(rs)
        if len(rs) >= MIN_PSI_N:
            base = self.base_scores[np.isfinite(self.base_scores)]
            k["score_psi"] = round(M.psi(base, rs), 4)
            k["score_ks"] = round(M.ks_two_sample(base, rs), 4)
            csi = self.feature_csi(recent)
            if csi:
                worst = max(csi, key=csi.get)
                k["worst_csi"], k["worst_csi_feature"] = csi[worst], worst
                k["mean_csi"] = round(float(np.mean(list(csi.values()))), 4)
                k["drifted_features"] = int(sum(v > 0.1 for v in csi.values()))
                k["csi"] = csi
        mat = [r for r in self.reqs if r["matures"] <= t and r["outcome"] is not None and np.isfinite(r["score"])][-1500:]
        k["matured"] = len(mat)
        if len(mat) >= 100 and self.spec.task in ("binary", "frequency"):
            y = np.array([r["outcome"] for r in mat], float)
            p = np.array([r["score"] for r in mat], float)
            ex = np.array([r["exposure"] for r in mat], float)
            if self.spec.task == "frequency":
                k["realized_rate"] = round(float(y.sum() / ex.sum()), 5)
                k["predicted_rate"] = round(float((p * ex).sum() / ex.sum()), 5)
                k["ae_ratio"] = round(float(y.sum() / max((p * ex).sum(), 1e-9)), 4)
            else:
                k["realized_rate"], k["predicted_rate"] = round(float(y.mean()), 5), round(float(p.mean()), 5)
                k["ae_ratio"] = round(float(y.mean() / max(p.mean(), 1e-9)), 4)
                if y.sum() >= 5 and (len(y) - y.sum()) >= 5:
                    k["realized_gini"] = round(M.gini(y, p), 4)
                    k["realized_ks"] = round(M.ks(y, p), 4)
                if 0 <= p.min() and p.max() <= 1:
                    k["brier"] = round(M.brier(y, p), 5)
                fl = np.array([r["flag"] for r in mat])
                if self.spec.decision.kind == "alert" and y.sum() >= 3:
                    k["realized_recall"] = round(float(((fl == 1) & (y == 1)).sum() / y.sum()), 4)
                if self.spec.decision.kind == "alert" and fl.sum() >= 3:
                    k["realized_precision"] = round(float(((fl == 1) & (y == 1)).sum() / fl.sum()), 4)
        status = self.evaluate(k)
        k["health_score"] = self.health()
        save(MonitorWindow(model_id=self.model_id, kpis=k, status=status))
        bus.publish("traffic", f"{self.model_id} · {k['requests']} req · p95 {k['latency_p95_ms']}ms · PSI {k.get('score_psi', '—')} → {status}",
                    model_id=self.model_id, stage="monitor", agent="monitor", payload={"kpis": k, "status": status})

    def _data_quality(self, w: list[dict]) -> dict:
        """Input health of the requests in this window: missing values, numbers outside the baseline range,
        categories never seen in the baseline."""
        miss = oor = unseen = n_num = n_cat = n_all = 0
        for r in w:
            for f, v in r["feats"].items():
                n_all += 1
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    miss += 1
                    continue
                if f in self.ranges:
                    n_num += 1
                    lo, hi = self.ranges[f][:2]
                    try:
                        oor += not (lo <= float(v) <= hi)
                    except (TypeError, ValueError):
                        oor += 1
                elif f in self.levels:
                    n_cat += 1
                    unseen += str(v) not in self.levels[f]
        return {"missing_input_rate": round(miss / n_all, 4) if n_all else 0.0,
                "out_of_range_rate": round(oor / n_num, 4) if n_num else 0.0,
                "unseen_category_rate": round(unseen / n_cat, 4) if n_cat else 0.0}

    def feature_csi(self, recent: list[dict]) -> dict[str, float]:
        out = {}
        for f in self.feats:
            cur = pd.Series([r["feats"].get(f) for r in recent])
            ref = self.base_rows[f]
            v = M.psi_categorical(ref.astype(str), cur.astype(str)) if f in self.cat_feats else \
                M.psi(ref.astype(float), pd.to_numeric(cur, errors="coerce").astype(float))
            out[f] = round(float(v), 4)
        return out

    def health(self) -> int:
        """0–100: starts at 100, loses points for every firing or breaching rule (red weighs more)."""
        h = 100
        for rule in self.plan.rules:
            if rule.id in self.active:
                h -= 35 if self.active[rule.id] == "red" else 15
            elif self.streak.get(rule.id):
                h -= 5
        return max(0, h)

    def profile(self) -> dict:
        """Live vs baseline: score histogram and a per-input drift / data-quality table (for the dashboard)."""
        recent = list(self.reqs)[-400:]
        rs = np.array([r["score"] for r in recent], float)
        rs = rs[np.isfinite(rs)]
        base = self.base_scores[np.isfinite(self.base_scores)]
        hist = []
        if len(rs) >= 20 and len(base):
            edges = np.unique(np.quantile(base, np.linspace(0, 1, 13)))
            if len(edges) >= 3:
                inner = edges.copy()
                inner[0], inner[-1] = -np.inf, np.inf
                bh = np.histogram(base, inner)[0] / len(base)
                lh = np.histogram(rs, inner)[0] / len(rs)
                hist = [{"bin": f"{edges[i]:.3g}", "lo": float(edges[i]), "hi": float(edges[i + 1]),
                         "baseline": round(float(bh[i]), 4), "live": round(float(lh[i]), 4)} for i in range(len(bh))]
        csi = self.feature_csi(recent) if len(recent) >= 50 else {}
        feats = []
        for f in self.feats:
            vals = [r["feats"].get(f) for r in recent]
            s = pd.Series(vals, dtype=object)
            miss = float(s.isna().mean()) if len(s) else 0.0
            row = {"feature": f, "kind": "categorical" if f in self.cat_feats else "numeric", "csi": csi.get(f),
                   "missing": round(miss, 4), "base_missing": round(self.base_missing.get(f, 0.0), 4)}
            if f in self.ranges:
                lo, hi, mu, sd = self.ranges[f]
                num = pd.to_numeric(s, errors="coerce").dropna()
                row.update({"base_mean": round(mu, 4), "live_mean": round(float(num.mean()), 4) if len(num) else None,
                            "shift_sd": round(float((num.mean() - mu) / sd), 3) if len(num) else None,
                            "out_of_range": round(float(((num < lo) | (num > hi)).mean()), 4) if len(num) else 0.0})
            else:
                known = self.levels.get(f, set())
                live = s.dropna().astype(str)
                row.update({"levels": len(known), "unseen": round(float((~live.isin(known)).mean()), 4) if len(live) else 0.0,
                            "top": live.value_counts().index[0] if len(live) else None})
            feats.append(row)
        feats.sort(key=lambda r: -(r["csi"] or 0))
        return {"score_hist": hist, "features": feats, "base_adverse_rate": round(self.base_adverse, 4)}

    def evaluate(self, k: dict) -> str:
        worst = "green"
        for rule in self.plan.rules:
            v = k.get(rule.kpi)
            if rule.kpi in OUTCOME_KPIS and k.get("matured", 0) < 200:
                v = None
            hit = v is not None and OPS[rule.op](v, rule.threshold)
            self.streak[rule.id] = self.streak.get(rule.id, 0) + 1 if hit else 0
            if self.streak[rule.id] >= rule.windows:
                worst = "red" if rule.severity == "red" or worst == "red" else "amber"
                if rule.id not in self.active:
                    self.active[rule.id] = rule.severity
                    self.raise_alert(rule, v)
            elif not hit and rule.id in self.active:
                del self.active[rule.id]
                bus.publish("monitor", f"✓ {self.model_id}: {rule.id} back within threshold", model_id=self.model_id,
                            stage="monitor", agent="monitor")
            elif hit and worst == "green":
                worst = "amber"  # an unconfirmed breach shows as a warning first
        return worst

    def raise_alert(self, rule: AlertRule, v):
        msg = f"{rule.kpi} = {v:.4g} {rule.op} {rule.threshold:g} for {rule.windows} consecutive windows"
        action, reval = "", None
        if rule.severity == "red" and rule.action == "revalidate" and time.time() - self.last_reval > 120:
            reval = trigger_revalidation(self.model_id, rule, list(self.rows))
            self.last_reval = time.time()
            action = "automatic re-validation started" if reval else ""
        al = save(MonitorAlert(model_id=self.model_id, rule=rule.id, severity=rule.severity, message=msg, value=float(v or 0),
                               action=action, revalidation_run_id=reval))
        ledger.append("monitor", "monitor_alert", {"model_id": self.model_id, "rule": rule.id, "severity": rule.severity,
                                                   "value": v, "alert_id": al.id, "revalidation_run_id": reval})
        bus.publish("alert", f"{'🚨' if rule.severity == 'red' else '⚠'} {self.model_id}: {msg}" + (f" → {action}" if action else ""),
                    model_id=self.model_id, stage="monitor", agent="monitor", payload={"alert_id": al.id, "rule": rule.id})


def trigger_revalidation(model_id: str, rule: AlertRule, rows: list[dict]) -> str | None:
    from app.orchestrator import pipeline
    m = repo.models.get(model_id)
    with session() as s:
        busy = s.exec(select(Run).where(Run.model_id == model_id, Run.kind == "revalidation",
                                        Run.status.in_(["queued", "running"]))).first()
    if busy or not (m.meta or {}).get("validated_run_id") or len(rows) < 150:
        return None
    out = settings.var_dir / "monitor" / model_id
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"recent_{int(time.time())}.csv"
    pd.DataFrame(rows[-400:]).to_csv(f, index=False)
    r = pipeline.create_run(model_id, kind="revalidation", parent=m.meta["validated_run_id"],
                            extra={"recent_file": str(f), "batch_label": f"live traffic · {rule.id}", "alert_rule": rule.model_dump()})
    pipeline.start(r.id)
    return r.id


class Simulator:
    def __init__(self):
        self.models: dict[str, ModelTraffic] = {}
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, name="traffic", daemon=True)
        self.thread.start()

    def _loop(self):
        while True:
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
        m = repo.models.get(model_id)
        mt = ModelTraffic(model_id, (m.meta or {}).get("traffic", {}))
        with self.lock:
            self.models[model_id] = mt
        self.persist(model_id)
        self.start()
        return mt.cfg

    def undeploy(self, model_id: str) -> None:
        with self.lock:
            self.models.pop(model_id, None)
        m = repo.models.get(model_id)
        if m:
            repo.models.update(model_id, meta={**(m.meta or {}), "deployed": False})

    def reload_plan(self, model_id: str) -> None:
        if model_id in self.models:
            self.deploy(model_id)

    def persist(self, model_id: str):
        mt = self.models.get(model_id)
        m = repo.models.get(model_id)
        if mt and m:
            repo.models.update(model_id, meta={**(m.meta or {}), "deployed": True, "traffic": mt.cfg})

    def restore(self):
        for m in repo.models.list():
            if (m.meta or {}).get("deployed"):
                try:
                    self.deploy(m.id)
                except Exception:
                    traceback.print_exc()

    def set_scenario(self, model_id: str, scenario: str | None, severity: float, ramp_s: int):
        mt = self.models[model_id]
        cur = mt.severity()
        mt.cfg.update({"scenario": scenario or mt.cfg.get("scenario"), "severity": severity if scenario else 0.0,
                       "ramp_from": cur, "ramp_start": time.time(), "ramp_s": ramp_s})
        self.persist(model_id)
        ledger.append("human", "traffic_scenario", {"model_id": model_id, "scenario": mt.cfg["scenario"], "severity": mt.cfg["severity"]})

    def set(self, model_id: str, **kw):
        self.models[model_id].cfg.update(kw)
        self.persist(model_id)

    def state(self, model_id: str, tail: int = 25) -> dict:
        mt = self.models.get(model_id)
        if not mt:
            return {"deployed": False}
        reqs = list(mt.reqs)[-tail:][::-1]
        return {"deployed": True, "cfg": mt.cfg, "severity_now": round(mt.severity(), 3), "total": mt.total, "active_alerts": mt.active,
                "plan": mt.plan.model_dump(), "tail": [{k: v for k, v in r.items() if k != "feats"} | {"inputs": r["feats"]} for r in reqs],
                "window_s": WINDOW, "outcome_delay_s": OUTCOME_DELAY, "decision_kind": mt.spec.decision.kind, "version": mt.ep.version,
                "task": mt.spec.task, "health": mt.health(), "streaks": {k: v for k, v in mt.streak.items() if v},
                **mt.profile()}

    def reset(self):
        with self.lock:
            self.models.clear()


sim = Simulator()


def windows(model_id: str, n: int = 90) -> list[dict]:
    with session() as s:
        rows = s.exec(select(MonitorWindow).where(MonitorWindow.model_id == model_id).order_by(MonitorWindow.id.desc()).limit(n)).all()
    return [{"ts": (w.ts if w.ts.tzinfo else w.ts.replace(tzinfo=timezone.utc)).isoformat(), "status": w.status, **w.kpis} for w in rows][::-1]


def prune(keep_hours: float = 6.0):
    with session() as s:
        s.exec(delete(MonitorWindow).where(MonitorWindow.ts < _now() - timedelta(hours=keep_hours)))
        s.commit()
