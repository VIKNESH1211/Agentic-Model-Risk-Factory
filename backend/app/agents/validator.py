"""Validator agent: independent validation driven by the APPROVED validation plan, then investigation.

Mandatory: build the scored frame (re-scored through the certified implementation, or the legacy outputs if
rehosted) and execute every plan check (status from the plan's thresholds, never the LLM). Then the agent decides
which investigations the evidence calls for — slice search, stress test, challenger, fuzzing, baseline comparison —
and may raise findings, but only citing metrics this run actually produced.
"""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

from app import repositories as repo
from app.agents.common import StageCtx
from app.agents.runtime import Agent, Tool, ToolError, run as run_agent
from app.core.config import settings
from app.domain.schemas import ModelSpec
from app.engine import bundle as B
from app.engine import catalog, scoring, serving
from app.engine import validation as V
from app.evidence import metric_store
from app.services import plans, specs

MIN_SEGMENT = 80


def _spec(ctx: StageCtx) -> ModelSpec:
    if "spec" not in ctx.state:
        ctx.state["spec"] = specs.current(ctx.model_id)
    return ctx.state["spec"]


def _meta(model_id: str) -> dict:
    return repo.models.get(model_id).meta or {}


def _scored(ctx: StageCtx) -> pd.DataFrame:
    if "scored_rel" not in ctx.state:
        raise ToolError("build_scored must run first")
    return metric_store.load_artifact(ctx.state["scored_rel"])


def _y(s: ModelSpec) -> str | None:
    return None if not s.target else (s.target if s.task == "binary" else "occurred")


# ------------------------------------------------------------------ tools
def t_build_scored(ctx: StageCtx, args: dict) -> dict:
    s = _spec(ctx)
    meta = _meta(ctx.model_id)
    pr = meta.get("parity_run_id")
    if not pr:
        raise ToolError("the model has no parity certificate — redevelopment must certify it first")
    b = B.load(settings.runs_dir / pr / "bundle")
    frame = b.frame.copy()
    recent = ctx.run.options.get("recent_file")
    if recent:  # re-validation: recent live traffic replaces the comparison sample
        base = scoring.build(frame, b.scores["score"], b.scores.get("decision"), s, b.train_rows)
        keep = frame[base["split"].isin(["train", "test"]).to_numpy()].copy()
        keep["split"] = base.loc[base["split"].isin(["train", "test"]), "split"].to_numpy()
        live = pd.read_csv(recent, low_memory=False)
        live = live[[c for c in frame.columns if c in live.columns]].copy()
        live["split"] = "oot"
        frame = pd.concat([keep, live], ignore_index=True)
        ctx.think(f"Re-validation: comparison sample replaced by {len(live)} recent live requests (outcomes matured).")
    if meta.get("parity_verdict") == "PASS":
        ep = serving.get(ctx.model_id)
        out = ep.predict(frame)
        score, decision, how = out["score"], (out["decision"] if out["decision"].notna().any() else None), "certified Python implementation"
    else:
        if recent:
            raise ToolError("a rehosted model cannot be re-scored on live traffic (no Python implementation)")
        score, decision, how = b.scores["score"], b.scores.get("decision"), "legacy R outputs (rehosted)"
    d = scoring.build(frame, score, decision, s, b.train_rows)
    out_dir = ctx.dir / "validate"
    out_dir.mkdir(parents=True, exist_ok=True)
    d.to_csv(out_dir / "scored.csv", index=False)
    rel = f"{ctx.rel}/validate/scored.csv"
    ctx.artifact("validation_scored", out_dir / "scored.csv")
    ctx.state.update(scored_rel=rel, scored_cols=list(d.columns), scored_how=how)
    return {"rows": len(d), "splits": d["split"].value_counts().to_dict(), "scored_by": how,
            "adverse_rate": round(float(d["flag"].mean()), 4), "columns": len(d.columns),
            "split_note": scoring.SPLIT_NOTE if b.train_rows is not None else "Model fitted on every row: test/oot are in-sample (simulated)."}


def t_run_plan(ctx: StageCtx, args: dict) -> dict:
    s = _spec(ctx)
    plan = plans.current(ctx.model_id, "validation")
    if plan is None:
        raise ToolError("no validation plan — the documentation stage must draft one")
    d = _scored(ctx)
    cols = set(d.columns)
    runnable, skipped = [], []
    for c in plan.checks:  # lint each check against the REAL scored frame; skip (and report) what cannot run
        errs = catalog.lint_validation(plan.model_copy(update={"checks": [c]}), s, cols)
        (skipped.append({"check": c.id, "why": errs[0]}) if errs else runnable.append(c))
    rec = ctx.recorder()
    results = V.execute(plan.model_copy(update={"checks": runnable}), s, ctx.state["scored_rel"], d, rec)
    for r in results:  # thresholds become evidence too (the report may not print raw numbers)
        if r.threshold:
            for lvl in ("amber", "red"):
                if r.threshold.get(lvl) is not None:
                    rec.const(f"threshold.{r.metric_name}.{lvl}", r.threshold[lvl], f"{lvl.title()} threshold for {r.title} (approved plan)")
    rec.commit("validation plan")
    for r in results:
        sev = V.finding_severity(r)
        if sev:
            ctx.finding(sev, r.category, f"{r.title}: {r.status.upper()}",
                        f"{r.title} breached its {r.status} threshold in the approved validation plan.",
                        detector=f"plan:{r.check_id}", evidence={"tokens": [r.token], "check": r.check_id})
    summ = V.summarise(results)
    ctx.state.update(results=[r.to_dict() for r in results], plan_summary=summ, skipped=skipped,
                     plan_version=plans.current_row(ctx.model_id, "validation").version)
    (ctx.dir / "validate" / "checks.json").write_text(json.dumps({"results": ctx.state["results"], "skipped": skipped,
                                                                   "summary": summ}, indent=2, default=str))
    ctx.artifact("validation_checks", ctx.dir / "validate" / "checks.json")
    weak = [{"check": r.metric_name, "status": r.status, "value": None if r.value is None else round(r.value, 4)}
            for r in results if r.status in ("red", "amber", "error")]
    return {"rating": summ["rating"], "counts": summ["counts"], "not_passing": weak[:12], "skipped": skipped[:6]}


def _segments(d: pd.DataFrame, s: ModelSpec) -> list[str]:
    cand = [g.name for g in s.groups] + [f for f in s.features if f in d and d[f].nunique() <= 15]
    return [c for c in dict.fromkeys(cand) if c in d]


def t_slices(ctx: StageCtx, args: dict) -> dict:
    s = _spec(ctx)
    d = _scored(ctx)
    y = _y(s)
    if not y or y not in d:
        raise ToolError("slice search needs an outcome column")
    cols = [c for c in (args.get("columns") or _segments(d, s)) if c in d]
    rec = ctx.recorder()
    overall = rec.measure("investigate.gini.all", {"fn": "gini", "artifact": ctx.state["scored_rel"], "split": "all",
                                                   "target": y, "score": "score"}, definition="Gini on all rows (slice baseline)")
    res = []
    for c in cols:
        for v, n in d[c].astype(str).value_counts().items():
            sub = d[d[c].astype(str) == v]
            if n < MIN_SEGMENT or sub[y].nunique() < 2:
                continue
            name = catalog.safe_name(f"investigate.gini.{c[:14]}={v[:20]}")
            g = rec.measure(name, {"fn": "gini", "artifact": ctx.state["scored_rel"], "split": "all", "slice": f"{c}={v}",
                                   "target": y, "score": "score"}, definition=f"Gini where {c} = {v}", emit=False)
            res.append({"segment": f"{c}={v}", "rows": int(n), "gini": round(g, 4), "token": ctx.tok(name)})
    rec.commit("slice search")
    res.sort(key=lambda r: r["gini"])
    ctx.state.setdefault("investigations", []).append("slice_search")
    for r in res:
        r["vs_overall"] = round(r["gini"] - overall, 4)
    weak = [r for r in res if r["gini"] < overall - 0.15]
    return {"overall_gini": round(overall, 4), "overall_token": ctx.tok("investigate.gini.all"), "segments": len(res),
            "verdict": f"{len(weak)} segment(s) rank materially worse (> 0.15 Gini below overall)" if weak else
                       "no segment ranks materially worse than overall", "worst": res[:5]}


def t_stress(ctx: StageCtx, args: dict) -> dict:
    s = _spec(ctx)
    ep = serving.get(ctx.model_id)
    if ep is None:
        raise ToolError("stress tests need the certified Python implementation (the model is rehosted)")
    frame = ep.bundle.frame
    num = [f for f in s.features if f in frame and pd.api.types.is_numeric_dtype(frame[f]) and frame[f].nunique() > 10]
    col = args.get("column") or (num[0] if num else None)
    if col not in frame:
        raise ToolError(f"choose a numeric input column: {num}")
    factor = float(args.get("factor") or 1.2)
    st = frame.copy()
    st[col] = st[col].astype(float) * factor
    base, new = ep.predict(frame), ep.predict(st)
    flips = int((base["flag"].to_numpy() != new["flag"].to_numpy()).sum())
    rel = float(np.nanmean(np.abs(new["score"] - base["score"]) / np.maximum(np.abs(base["score"]), 1e-9)))
    rec = ctx.recorder()
    tag = catalog.safe_name(f"investigate.stress.{col}.x{factor:g}")
    rec.const(f"{tag}.decision_flips", flips, f"Decisions that flip when {col} is multiplied by {factor:g} for every row")
    rec.const(f"{tag}.mean_rel_change", rel, f"Mean relative change in the model output when {col} × {factor:g}")
    rec.commit("stress test")
    ctx.state.setdefault("investigations", []).append("stress_test")
    return {"column": col, "factor": factor, "decision_flips": flips, "mean_rel_change": round(rel, 4),
            "tokens": [ctx.tok(f"{tag}.decision_flips"), ctx.tok(f"{tag}.mean_rel_change")]}


def t_challenger(ctx: StageCtx, args: dict) -> dict:
    s = _spec(ctx)
    d = _scored(ctx)
    y = _y(s)
    if s.task not in ("binary", "frequency") or not y or y not in d:
        raise ToolError("a challenger needs a binary or frequency outcome")
    from sklearn.ensemble import HistGradientBoostingClassifier
    feats = [f for f in s.features if f in d]
    X = pd.get_dummies(d[feats], dummy_na=True).astype(float)
    tr = (d["split"] == "train").to_numpy()
    if tr.sum() < 50:
        raise ToolError("not enough training rows for a challenger")
    clf = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, random_state=42)
    clf.fit(X[tr], d.loc[tr, y])
    c = d[["split", y, "score"]].copy()
    c["challenger"] = clf.predict_proba(X)[:, 1]
    c.to_csv(ctx.dir / "validate" / "challenger.csv", index=False)
    rel = f"{ctx.rel}/validate/challenger.csv"
    rec = ctx.recorder()
    g1 = rec.measure("investigate.gini.challenger", {"fn": "gini", "artifact": rel, "split": "test|oot", "target": y, "score": "challenger"},
                     definition="Gini of a gradient-boosting challenger on the hold-out")
    g0 = rec.measure("investigate.gini.champion", {"fn": "gini", "artifact": rel, "split": "test|oot", "target": y, "score": "score"},
                     definition="Gini of the model on the same hold-out")
    rec.commit("challenger")
    ctx.state.setdefault("investigations", []).append("challenger")
    verdict = (f"the MODEL ranks better than the challenger by {g0 - g1:.3f} Gini — no concern" if g0 >= g1 else
               f"the CHALLENGER ranks better than the model by {g1 - g0:.3f} Gini" + (" — material (> 0.05)" if g1 - g0 > 0.05 else " — small"))
    return {"verdict": verdict, "champion_gini": round(g0, 4), "challenger_gini": round(g1, 4), "uplift": round(g1 - g0, 4),
            "tokens": [ctx.tok("investigate.gini.champion"), ctx.tok("investigate.gini.challenger")]}


def t_fuzz(ctx: StageCtx, args: dict) -> dict:
    """Edge cases derived from each input's own type: extremes, zero, negatives, missing, unseen categories."""
    s = _spec(ctx)
    ep = serving.get(ctx.model_id)
    if ep is None:
        raise ToolError("fuzzing needs the certified Python implementation (the model is rehosted)")
    frame = ep.bundle.frame
    n = int(args.get("n") or 2000)
    rng = np.random.default_rng(20261111)
    rows = frame.sample(n, replace=True, random_state=7).reset_index(drop=True)
    feats = [f for f in s.features if f in rows]
    kinds = []
    for i in range(n):
        f = feats[rng.integers(len(feats))]
        col = frame[f]
        if pd.api.types.is_numeric_dtype(col):
            lo, hi = float(col.min()), float(col.max())
            k = rng.choice(["min", "max", "zero", "negative", "huge", "missing"])
            val = {"min": lo, "max": hi, "zero": 0.0, "negative": -abs(hi) - 1, "huge": hi * 10 + 1, "missing": np.nan}[k]
            rows[f] = rows[f].astype(float)
        else:
            k = rng.choice(["unseen", "missing"])
            val = "__unseen__" if k == "unseen" else np.nan
            rows[f] = rows[f].astype(object)
        rows.at[i, f] = val
        kinds.append(f"{f}:{k}")
    errors, missing = 0, 0
    try:
        out = ep.predict(rows)
        sc = out["score"].to_numpy(float)
        missing = int(np.isnan(sc).sum())
    except Exception:  # batch failed: score one by one to count
        for i in range(n):
            try:
                v = float(ep.predict(rows.iloc[[i]])["score"].iloc[0])
                missing += int(np.isnan(v))
            except Exception:
                errors += 1
    rec = ctx.recorder()
    rec.const("investigate.fuzz.rows", n, "Edge-case rows generated from the inputs' own types")
    rec.const("investigate.fuzz.no_decision", missing, "Edge-case rows for which the model returns no score / decision")
    rec.const("investigate.fuzz.errors", errors, "Edge-case rows for which the implementation raised an error")
    rec.commit("fuzz")
    worst = pd.Series([k for k, v in zip(kinds, np.isnan(sc) if not errors else [False] * n) if v]).value_counts().head(5).to_dict() if not errors else {}
    ctx.state.setdefault("investigations", []).append("fuzz")
    return {"rows": n, "no_decision": missing, "errors": errors, "most_affected": worst,
            "tokens": [ctx.tok("investigate.fuzz.no_decision"), ctx.tok("investigate.fuzz.errors")]}


def t_compare(ctx: StageCtx, args: dict) -> dict:
    parent = ctx.run.parent_run_id or _meta(ctx.model_id).get("validated_run_id")
    if not parent or parent == ctx.run_id:
        raise ToolError("no earlier validation run to compare with")
    rows = []
    for r in ctx.state.get("results", []):
        a = metric_store.get(parent, r["metric_name"])
        if a and r["value"] is not None:
            rows.append({"metric": r["metric_name"], "before": round(a.value, 4), "now": round(r["value"], 4),
                         "status_now": r["status"]})
    rows.sort(key=lambda x: -abs(x["now"] - x["before"]))
    ctx.state.setdefault("investigations", []).append("compare_to_baseline")
    return {"baseline_run": parent, "changed_most": rows[:8]}


def t_finding(ctx: StageCtx, args: dict) -> dict:
    toks = [t.strip("{}") for t in (args.get("tokens") or [])]
    valid = [t for t in toks if t.startswith(f"m:{ctx.run_id}:") and metric_store.get(ctx.run_id, t.split(":", 2)[2])]
    if not valid:
        raise ToolError(f"a finding must cite at least one metric token produced in THIS run (m:{ctx.run_id}:<name>)")
    sev = args.get("severity") if args.get("severity") in ("high", "medium", "low") else "medium"
    f = ctx.finding(sev, str(args.get("category") or "performance")[:30], str(args.get("title") or "Investigation finding")[:160],
                    str(args.get("detail") or "")[:1200], detector="validator_investigation", evidence={"tokens": valid})
    return {"code": f.code, "severity": sev}


TOOLS = [
    Tool("build_scored", "Score the legacy export frame through the certified implementation and build the evidence artifact",
         t_build_scored, summary=lambda r: f"{r['rows']:,} rows scored by {r['scored_by']} · splits {r['splits']}", observe=lambda r: r),
    Tool("run_plan", "Execute every check of the APPROVED validation plan; red/amber become findings", t_run_plan,
         summary=lambda r: f"{r['rating']} · {r['counts']}", observe=lambda r: r),
    Tool("slice_search", "Gini in every segment (groups + low-cardinality inputs) to find where the model ranks badly",
         t_slices, {"columns": "optional list of columns to segment by"},
         summary=lambda r: f"{r['segments']} segments; worst {r['worst'][0]['segment']} Gini {r['worst'][0]['gini']}" if r["worst"] else "no segments",
         observe=lambda r: r),
    Tool("stress_test", "Multiply one numeric input by a factor for every row and count decision flips", t_stress,
         {"column": "numeric input column", "factor": "e.g. 1.2"},
         summary=lambda r: f"{r['column']} ×{r['factor']}: {r['decision_flips']} decision flips", observe=lambda r: r),
    Tool("challenger", "Fit a gradient-boosting challenger on the same inputs and compare hold-out Gini", t_challenger,
         summary=lambda r: r["verdict"], observe=lambda r: r),
    Tool("fuzz", "Score edge cases built from each input's type (extremes, missing, unseen categories); count no-decisions and errors",
         t_fuzz, {"n": "rows to generate (default 2000)"},
         summary=lambda r: f"{r['rows']} edge cases: {r['no_decision']} no-decision, {r['errors']} errors", observe=lambda r: r),
    Tool("compare_to_baseline", "Compare this run's check values with the previous validation", t_compare,
         summary=lambda r: f"vs {r['baseline_run']}: {len(r['changed_most'])} metrics compared", observe=lambda r: r),
    Tool("raise_finding", "Record a finding from an investigation; must cite metric tokens from this run", t_finding,
         {"severity": "high|medium|low", "category": "e.g. performance, fairness, robustness", "title": "short title",
          "detail": "what and why it matters", "tokens": "list of metric tokens m:<run>:<name> from this run"},
         summary=lambda r: f"finding {r['code']} ({r['severity']})", observe=lambda r: r),
]


def _fallback(ctx: StageCtx) -> dict | None:
    ok = ctx.state.get("ok", {})
    for t in ("build_scored", "run_plan"):
        if not ok.get(t):
            return {"tool": t, "args": {}}
    if ctx.run.kind == "revalidation" and not ok.get("compare_to_baseline"):
        return {"tool": "compare_to_baseline", "args": {}}
    return None


def _facts(ctx: StageCtx) -> dict:
    s = _spec(ctx)
    plan = plans.current(ctx.model_id, "validation")
    return {"model": ctx.model_id, "task": s.task, "tier": s.tier, "strategy": _meta(ctx.model_id).get("parity_verdict"),
            "run_kind": ctx.run.kind, "plan_checks": len(plan.checks) if plan else 0,
            "plan_suggests": plan.investigations if plan else [], "plan_result": ctx.state.get("plan_summary"),
            "investigations_done": ctx.state.get("investigations", [])}


def _guard(ctx: StageCtx) -> list[str]:
    c = (ctx.state.get("plan_summary") or {}).get("counts", {})
    return [f"{c['red']} check(s) breached their red threshold"] if c.get("red") else []


AGENT = Agent(
    name="validator", stage="validate",
    goal="Independently validate the model: execute the approved plan, then investigate whatever the results call for "
         "(weak segments, sensitivity, a challenger, edge cases, change vs the last validation) and raise evidence-backed findings.",
    tools=TOOLS, mandatory=["build_scored", "run_plan"], facts=_facts, fallback=_fallback, guard=_guard, max_steps=12)


def run(ctx: StageCtx) -> dict:
    c = run_agent(ctx, AGENT)
    return {"conclusion": c, "rating": (ctx.state.get("plan_summary") or {}).get("rating"),
            "counts": (ctx.state.get("plan_summary") or {}).get("counts"), "investigations": ctx.state.get("investigations", [])}
