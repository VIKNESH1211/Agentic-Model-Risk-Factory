"""Independent Validator for the non-scorecard estate."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
from sqlmodel import func, select

from app.agents.common import StageCtx
from app.core.config import settings
from app.core.db import session
from app.domain.tables import Finding, Model
from app.modelkit import registry as R
from app.modelkit import serving
from app.tools import impact
from app.tools import validation_generic as VG
from app.tools.validation_core import THRESHOLDS


def _scores(a: R.Adapter, frame: pd.DataFrame) -> pd.DataFrame:
    if a.strategy == "rehost":
        with session() as s:
            run_id = s.get(Model, a.id).meta["parity_run_id"]
        return pd.read_csv(settings.runs_dir / run_id / "legacy_scores.csv")[["id", "score"]]
    ep = serving.get(a.id)
    if ep is None:
        raise RuntimeError(f"{a.id} has no certified Python endpoint yet — promote it through Redevelop first")
    out = ep.predict(frame)
    return pd.DataFrame({"id": frame["id"].to_numpy(), "score": out["score"].to_numpy(), "decision": out["decision"].to_numpy()})


def run(ctx: StageCtx, a: R.Adapter, *, recent: pd.DataFrame | None = None, factory_findings: bool = True,
        label: str = "validation") -> dict:
    rec = ctx.recorder()
    frame = ctx.tool("load_data", "analysis frame for " + a.id, a.frame,
                     result_summary=lambda f: f"{len(f):,} rows · splits {dict(f['split'].value_counts())}")
    if recent is not None:  # re-validation: recent live traffic becomes the comparison sample
        recent = recent.copy()
        recent["split"] = "oot"
        frame = pd.concat([frame[frame["split"].isin(["train", "test"])], recent[[c for c in frame.columns if c in recent]]],
                          ignore_index=True)
        ctx.think(f"Comparison sample replaced by {len(recent)} recent live requests (simulated traffic, outcomes matured).")
    scores = ctx.tool("refit", "independent scoring through the certified implementation" if a.strategy != "rehost"
                      else "load the rehosted legacy scores", lambda: _scores(a, frame),
                      result_summary=lambda s: f"{s['score'].notna().sum():,} rows scored")
    S = ctx.tool("build_scored", "join scores to data, write the evidence artifact",
                 lambda: VG.build_scored(frame, scores, a.spec, f"{ctx.rel}/validate"), result_summary=lambda p: p)
    ctx.artifact("validation_scored", settings.var_dir / S)
    upstream_high = 0
    if a.id == "CR-003":
        with session() as s:
            upstream_high = s.exec(select(func.count()).select_from(Finding).where(
                Finding.model_id == "CR-001", Finding.severity == "high")).one()
    measure = lambda n, r: rec.measure(n, r)  # noqa: E731
    dets = ctx.tool("detectors", f"{a.spec.task} checks: performance · calibration · stability · fairness · data quality",
                    lambda: VG.run(a.spec, S, measure, ctx.tok, upstream_high=upstream_high),
                    result_summary=lambda r: f"{len(r)} detector(s) fired", args={"thresholds": THRESHOLDS | VG.GEN})
    opt = set(ctx.choices.get("optional", []))
    d = pd.read_csv(settings.var_dir / S, low_memory=False)

    if "challenger" in opt and a.spec.task == "binary" and a.spec.target in d:
        def chal():
            from sklearn.ensemble import HistGradientBoostingClassifier
            X = pd.get_dummies(d[[f for f in a.spec.features if f in d]], dummy_na=True).astype(float)
            tr = d["split"] == "train"
            if tr.sum() < 50:
                return None
            clf = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, random_state=42)
            clf.fit(X[tr], d.loc[tr, a.spec.target])
            c = d[["id", "split", a.spec.target, "score"]].copy()
            c["challenger"] = clf.predict_proba(X)[:, 1]
            c.to_csv(ctx.dir / "challenger.csv", index=False)
            g1 = rec.measure("gini.challenger.holdout", {"fn": "gini", "artifact": f"{ctx.rel}/challenger.csv", "split": "test|oot",
                                                         "target": a.spec.target, "score": "challenger"})
            g0 = rec.measure("gini.champion.holdout", {"fn": "gini", "artifact": f"{ctx.rel}/challenger.csv", "split": "test|oot",
                                                       "target": a.spec.target, "score": "score"})
            return g0, g1
        r = ctx.tool("challenger", "gradient-boosting challenger on the same inputs", chal,
                     result_summary=lambda r: "skipped (no training split)" if r is None else f"champion {r[0]:.3f} vs challenger {r[1]:.3f}")
        if r and r[1] - r[0] > 0.08:
            ctx.finding("medium", "challenger", "A simple challenger materially outperforms the model",
                        "Gradient boosting on the same inputs ranks risk better on the hold-out.", detector="challenger",
                        evidence={"tokens": [ctx.tok("gini.champion.holdout"), ctx.tok("gini.challenger.holdout")]})

    if "slice_search" in opt and a.spec.task in ("binary", "frequency"):
        ycol = a.spec.target if a.spec.task == "binary" else "occurred"
        def slices():
            res = []
            for f in dict.fromkeys(a.spec.groups + [x for x in a.spec.features if x in d and d[x].nunique() <= 15]):
                for v, n in d[f].astype(str).value_counts().items():
                    sub = d[d[f].astype(str) == v]
                    if n < 80 or sub[ycol].nunique() < 2:
                        continue
                    name = re.sub(r"[^A-Za-z0-9_.=-]+", "_", f"gini.slice.{f[:12]}={v[:20]}")
                    res.append((rec.measure(name, {"fn": "gini", "artifact": S, "split": "all", "slice": f"{f}={v}",
                                                   "target": ycol, "score": "score"}, emit=False), name, f, v))
            overall = rec.measure("gini.all", {"fn": "gini", "artifact": S, "split": "all", "target": ycol, "score": "score"})
            return sorted(res), overall
        res, overall = ctx.tool("slice_search", "Gini on every segment with ≥80 rows", slices,
                                result_summary=lambda r: f"{len(r[0])} slices, worst {r[0][0][0]:.3f} vs overall {r[1]:.3f}" if r[0] else "none")
        if res and res[0][0] < overall - 0.2:
            g, name, f, v = res[0]
            ctx.finding("medium", "segment_weakness", f"Weak ranking in segment {f} = `{v}`",
                        "The model separates outcomes much worse in this segment than overall.", detector="slice_search",
                        evidence={"tokens": [ctx.tok(name), ctx.tok("gini.all")]})

    if "stress_test" in opt and a.strategy != "rehost":
        num = [f for f in a.spec.features if f in frame and pd.api.types.is_numeric_dtype(frame[f]) and frame[f].nunique() > 15]
        if num:
            def stress():
                ep = serving.get(a.id)
                st = frame.copy()
                st[num[0]] = st[num[0]].astype(float) * 1.2
                base, new = ep.predict(frame), ep.predict(st)
                flips = int((base["decision"].astype(str).to_numpy() != new["decision"].astype(str).to_numpy()).sum())
                rel = float(np.nanmean(np.abs(new["score"].to_numpy() - base["score"].to_numpy()) / np.maximum(np.abs(base["score"].to_numpy()), 1e-9)))
                rec.const(f"stress.{num[0]}.decision_flips", flips, f"Decisions that flip when {num[0]} rises 20% for every row")
                rec.const(f"stress.{num[0]}.mean_rel_change", rel, f"Mean relative change in output when {num[0]} rises 20%")
                return flips, rel
            ctx.tool("stress_test", f"{num[0]} +20% for every row", stress,
                     result_summary=lambda r: f"{r[0]} decision flips, mean output change {r[1] * 100:.1f}%")

    def imp():
        if a.spec.decision_kind == "approve" and a.spec.target in d:
            rec.measure("el_gap.holdout", {**impact.el_gap_recipe(S, "test|oot"), "target": a.spec.target, "score": "score"})
        for k, v in impact.ASSUMPTIONS.items():
            rec.const(f"assumption.{k}", v["value"], f"Assumption: {v['unit']} — {v['source']}")
        for k in ("psi_red", "calibration_ratio_low", "calibration_ratio_high", "di_ratio"):
            rec.const(f"threshold.{k}", THRESHOLDS[k], f"Validation threshold ({k}), fixed policy setting")
        if a.spec.cutoff is not None:
            rec.const("cutoff", a.spec.cutoff, "Decision threshold in the legacy code")
    ctx.tool("impact", "assumptions, thresholds and £ impact (labelled)", imp, result_summary=lambda r: "recorded")
    rec.commit(label)

    for det in dets:
        ctx.finding(det.severity, det.category, det.title, det.detail, detector=det.detector, evidence={"tokens": det.tokens})
    if factory_findings:
        src = (a.dir / a.script).read_text().splitlines()
        def review():
            hits = []
            for sev, cat, title, detail, rx in a.code_findings:
                line = next((i + 1 for i, l in enumerate(src) if re.search(rx, l)), None)
                hits.append((sev, cat, title, detail, line))
            return hits
        hits = ctx.tool("code_review", f"rule-based review of {a.script}", review, result_summary=lambda h: f"{len(h)} issue(s)")
        for sev, cat, title, detail, line in hits:
            ctx.finding(sev, cat, title, detail, detector="code_review",
                        evidence={"file": a.script, "line": line, "code": src[line - 1].strip() if line else ""})
    ctx.flush_cost()
    return {"scored": S}
