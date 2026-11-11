"""Documentation agent: produces a structured ModelDoc from code, data and lineage."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.agents.common import StageCtx
from app.core import llm
from app.core.config import settings
from app.core.db import session
from app.domain.tables import Model, ModelEdge
from app.tools.parsers import r_parser

SECTIONS = ["purpose", "data", "methodology", "variables", "implementation", "assumptions_limitations",
            "monitoring", "gaps"]

CR001_VARIABLES = [
    ("checking", "status.of.existing.checking.account", "categorical", "Checking-account balance band"),
    ("duration", "duration.in.month", "numeric → 4 bins", "Loan term; bins <12, 12–24, 24–36, 36+ months"),
    ("history", "credit.history", "categorical", "Repayment history"),
    ("purpose", "purpose", "categorical", "Loan purpose"),
    ("amount", "credit.amount", "numeric → 4 bins", "Loan amount; missing silently set to 0 (quirk)"),
    ("savings", "savings.account.and.bonds", "categorical", "Savings band"),
    ("employment", "present.employment.since", "categorical", "Employment tenure band"),
    ("instalment", "installment.rate.in.percentage.of.disposable.income", "ordinal 1–4", "Instalment as % of income"),
]


def run(ctx: StageCtx) -> dict:
    with session() as s:
        m = s.get(Model, ctx.model_id)
        ups = [e.src_id for e in s.exec(__import__("sqlmodel").select(ModelEdge).where(ModelEdge.dst_id == m.id)).all()]
        downs = [e.dst_id for e in s.exec(__import__("sqlmodel").select(ModelEdge).where(ModelEdge.src_id == m.id)).all()]
    path = settings.root / m.meta["path"]
    p = ctx.tool("r_parser", f"re-read {path.name}", lambda: r_parser.parse(path),
                 result_summary=lambda r: f"{len(r['smells'])} smells, {len(r['injection'])} injection flag(s)")
    lineage = ctx.tool("lineage_builder", "trace inputs/outputs to other models",
                       lambda: {"upstream": ups, "downstream": downs, "reads": p["reads"], "writes": p["writes"]},
                       result_summary=lambda r: f"{len(r['upstream'])} upstream, {len(r['downstream'])} downstream")
    variables = []
    if m.id == "CR-001":
        raw = pd.read_csv(settings.data_dir / "raw" / "germancredit.csv")
        def profile():
            out = []
            for short, col, kind, desc in CR001_VARIABLES:
                s = raw[col]
                out.append({"name": short, "source_column": col, "type": kind, "description": desc,
                            "missing_pct": round(float(s.isna().mean()) * 100, 2), "distinct": int(s.nunique())})
            return out
        variables = ctx.tool("data_profiler", "profile 8 model inputs on germancredit (n=1,000)", profile,
                             result_summary=lambda r: f"{len(r)} variables profiled")
    gaps = []
    kinds = {s["kind"] for s in p["smells"]}
    if "comment_code_mismatch" in kinds:
        gaps.append("Decision cutoff in code contradicts the policy cited in comments; no approved cutoff record.")
    if "na_imputed_zero" in kinds:
        gaps.append("Missing-value treatment is undocumented and silently imputes zero.")
    if "hardcoded_path" in kinds:
        gaps.append("Hardcoded file paths: production data source is not documented or controlled.")
    if "stale_todo" in kinds:
        gaps.append("Outstanding TODOs indicate recalibration / rebinning was never completed.")
    gaps.append("No ongoing-monitoring plan or thresholds documented.")
    if not variables:
        gaps.append("Development and validation data not available in repository; validation deferred.")

    facts = {"id": m.id, "name": m.name, "type": m.type, "tier": m.tier, "owner": m.owner, "methods": p["methods"],
             "libraries": p["libraries"], "lineage": lineage, "gaps": gaps}
    schema = {"type": "object", "additionalProperties": False, "required": SECTIONS,
              "properties": {k: {"type": "string"} for k in SECTIONS}}

    def offline():
        return {
            "purpose": f"{m.name} ({m.id}) — {m.purpose or m.type}. Owner: {m.owner or 'unassigned'}. Tier {m.tier}: {m.tier_rationale}",
            "data": ("Development data: " + (", ".join(Path(r).name for r in p["reads"]) or "not specified")
                     + ". " + ("German credit sample (public, n=1,000; out-of-time split simulated)." if m.id == "CR-001" else "")),
            "methodology": ", ".join(p["methods"]) or "Scripted business rules.",
            "variables": "See variable dictionary." if variables else "Not derivable without data.",
            "implementation": f"Legacy R script ({p['loc']} lines); libraries: {', '.join(p['libraries']) or 'base R only'}. "
                              f"Outputs: {', '.join(Path(w).name for w in p['writes']) or 'console only'}.",
            "assumptions_limitations": "Bins frozen since 2016; no out-of-time evidence in legacy pack; "
                                       "cutoff hardcoded in code." if m.id == "CR-001" else "Not documented by model owner.",
            "monitoring": "None documented in legacy pack.",
            "gaps": " ".join(gaps),
        }
    res = ctx.tool("llm.draft", "draft ModelDoc sections from parsed facts", lambda: llm.complete_json(
        "model_doc", "Draft concise model documentation sections from these verified facts. Do not add numbers "
                     "that are not in the facts.\n" + json.dumps(facts), schema, offline,
        run_id=ctx.run_id, agent="documentation", untrusted={path.name: p["source"]}, spent=ctx.spent),
        result_summary=lambda r: f"{len(r.data)} sections (source={r.source})")
    doc = {"model_id": m.id, "sections": res.data, "variables": variables, "lineage": lineage, "gaps": gaps,
           "smells": p["smells"], "injection": p["injection"], "llm_source": res.source,
           "completeness": round(sum(1 for k in SECTIONS if res.data.get(k)) / len(SECTIONS), 2)}
    f = ctx.dir / "model_doc.json"
    f.write_text(json.dumps(doc, indent=2))
    ctx.artifact("model_doc", f)
    with session() as s:
        mm = s.get(Model, m.id)
        mm.meta = {**mm.meta, "doc_run_id": ctx.run_id, "doc_gaps": len(gaps)}
        mm.status = "documented"
        s.add(mm)
        s.commit()
    ctx.emit("stage_completed", f"ModelDoc ready · {len(gaps)} gap(s) · {len(variables)} variables", {"gaps": gaps})
    return {"doc_path": str(f), "gaps": gaps}
