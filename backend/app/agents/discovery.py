"""Discovery agent: walks the legacy estate, builds the inventory, tiers models, finds lineage."""
from __future__ import annotations

from pathlib import Path

from sqlmodel import delete, select

from app.agents.common import StageCtx
from app.core import llm
from app.core.config import settings
from app.core.db import session
from app.domain.tables import Model, ModelEdge
from app.evidence import ledger
from app.tools.parsers import r_parser

TYPE_RULES = [("challenger", "Challenger / benchmark"), ("limit", "Credit strategy"),
              ("claims", "Pricing – frequency GLM"), ("fraud", "Financial crime – fraud"), ("pd", "Credit risk – PD")]


def _type(p: dict) -> str:
    txt = (p["name"] + " " + " ".join(p["header"])).lower()
    return next((t for k, t in TYPE_RULES if k in txt), "Other")


def _tier(p: dict, mtype: str) -> tuple[str, str]:
    """Deterministic tiering rule (materiality x customer impact x complexity)."""
    if "Challenger" in mtype:
        return "C", "Not used for live decisions; benchmark only."
    if "PD" in mtype or "Pricing" in mtype:
        return "A", "Directly drives customer-level credit or pricing decisions at scale."
    return "B", "Supports decisions or depends on a Tier A model; material but indirect customer impact."


def scan_files() -> list[Path]:
    return sorted(p for p in settings.legacy_dir.glob("*/*.R") if p.parent.name != "sandbox")


def scan_portfolio() -> list[dict]:
    """Register every legacy model and its lineage edges. Idempotent."""
    parsed = [r_parser.parse(p) for p in scan_files()]
    with session() as s:
        for p in parsed:
            mtype = _type(p)
            tier, why = _tier(p, mtype)
            m = s.get(Model, p["id"]) or Model(id=p["id"], name=p["name"], type=mtype, language="R")
            m.name, m.type, m.owner, m.tier, m.code_hash = p["name"], mtype, p["owner"], tier, p["code_hash"]
            m.tier_rationale = m.tier_rationale or why
            m.purpose = m.purpose or next((h for h in p["header"][1:] if "owner" not in h.lower()), "")
            m.status = m.status if m.status not in ("", "registered") else "discovered"
            m.meta = {**(m.meta or {}), "path": str(Path(p["path"]).relative_to(settings.root)),
                      "libraries": p["libraries"], "methods": p["methods"], "reads": p["reads"],
                      "writes": p["writes"], "loc": p["loc"], "smells": len(p["smells"]),
                      "injection_flags": len(p["injection"]),
                      "hero": p["id"] == "CR-001"}
            s.add(m)
        s.exec(delete(ModelEdge))
        ids = {p["id"] for p in parsed}
        for p in parsed:
            for f in p["reads"]:
                base = Path(f).name.lower()
                for other in ids - {p["id"]}:
                    if other.replace("-", "").lower() in base:
                        s.add(ModelEdge(src_id=other, dst_id=p["id"], kind="feeds"))
            if "challenger" in " ".join(p["header"]).lower():
                tgt = next((o for o in ids - {p["id"]} if o in " ".join(p["header"])), None)
                if tgt:
                    s.add(ModelEdge(src_id=p["id"], dst_id=tgt, kind="challenger_of"))
        # shared input data: same CSV referenced by two models (excluding other models' outputs)
        import re as _re
        refs = {p["id"]: {Path(x).name.lower() for x in _re.findall(r'"([^"]+\.csv)"', p["source"])} for p in parsed}
        for i, a in enumerate(parsed):
            for b in parsed[i + 1:]:
                common = {f for f in refs[a["id"]] & refs[b["id"]]
                          if not any(o.replace("-", "").lower() in f for o in ids)}
                if common:
                    s.add(ModelEdge(src_id=a["id"], dst_id=b["id"], kind="shares_data"))
        s.commit()
    ledger.append("discovery", "portfolio_scanned", {"models": sorted(ids),
                                                     "files": [str(Path(p["path"]).name) for p in parsed]})
    return parsed


def run(ctx: StageCtx) -> dict:
    path = next(p for p in scan_files() if r_parser.parse(p)["id"] == ctx.model_id)
    p = ctx.tool("file_walker", f"scan {path.parent.name}/", lambda: r_parser.parse(path),
                 result_summary=lambda r: f"{r['loc']} lines of R, {len(r['libraries'])} libraries")
    ctx.tool("r_parser", "extract methods, inputs, outputs", lambda: p,
             result_summary=lambda r: f"{', '.join(r['methods']) or 'script'}; reads {len(r['reads'])} file(s)")
    smells = ctx.tool("code_smell_scan", "hardcoded paths, magic numbers, stale TODOs", lambda: p["smells"],
                      result_summary=lambda r: f"{len(r)} smell(s)")
    inj = ctx.tool("injection_guard", "pre-scan untrusted source for instructions", lambda: p["injection"],
                   result_summary=lambda r: f"{len(r)} flagged line(s)" if r else "clean")
    if inj:
        ledger.append("guardrail", "injection_flagged", {"run_id": ctx.run_id, "model_id": ctx.model_id,
                                                         "lines": [h["line"] for h in inj], "labels": [h["label"] for h in inj]})
        ctx.emit("security", f"🛡 prompt-injection attempt flagged in {path.name} (line {inj[0]['line']}) – treated as data",
                 {"hits": inj})
    with session() as s:
        m = s.get(Model, ctx.model_id)
    schema = {"type": "object", "properties": {"tier_rationale": {"type": "string"}, "purpose": {"type": "string"}},
              "required": ["tier_rationale", "purpose"], "additionalProperties": False}
    res = ctx.tool("llm.classify", "draft tier rationale (tier itself is rule-based)", lambda: llm.complete_json(
        "tier_rationale",
        f"Model {m.id} '{m.name}' of type {m.type} was assigned Tier {m.tier} by the deterministic rule "
        f"(materiality x customer impact). Write a two-sentence rationale and a one-line purpose statement. "
        f"Methods: {p['methods']}. Inputs: {p['reads']}. Outputs: {p['writes']}.",
        schema, lambda: {"tier_rationale": f"{m.tier_rationale} Methods: {', '.join(p['methods']) or 'scripted rules'}.",
                         "purpose": m.purpose},
        run_id=ctx.run_id, agent="discovery", untrusted={path.name: p["source"]}, spent=ctx.spent),
        result_summary=lambda r: f"source={r.source}")
    with session() as s:
        m = s.get(Model, ctx.model_id)
        m.tier_rationale = res.data["tier_rationale"]
        m.purpose = res.data.get("purpose") or m.purpose
        m.meta = {**m.meta, "smell_list": smells, "injection_hits": inj}
        s.add(m)
        s.commit()
    ctx.emit("info", f"{ctx.model_id} registered · Tier {m.tier} · {m.type}", {"tier": m.tier})
    return {"parsed": {k: v for k, v in p.items() if k != "source"}, "tier": m.tier}
