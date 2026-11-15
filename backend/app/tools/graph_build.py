"""Model dependency graph + downstream blast radius, derived from the approved specs and the data room.

feeds        a spec declares the other model as upstream, or reads a data-room asset whose provenance names it
shares_data  two models read the same data-room asset

Every edge carries an `origin`: spec, data_room, or manual. A person can add or remove dependencies on the Models
page; those overrides live on the downstream model's meta["lineage"] = {"added": [...], "removed": [...]} and are
applied on top of the derived graph, so they survive spec re-approvals and data-room changes.
"""
from __future__ import annotations

import re

import networkx as nx

from app import repositories as repo

ID_RE = re.compile(r"\b([A-Z]{2,4}-\d{2,4})\b")


def build() -> nx.DiGraph:
    from app.services import specs
    g = nx.DiGraph()
    models = repo.models.list()
    ids = {m.id for m in models}
    reads: dict[str, set[str]] = {}
    for m in models:
        g.add_node(m.id, name=m.name, tier=m.tier, status=m.status, type=m.type)
        s = specs.current_or_none(m.id)
        if not s:
            continue
        reads[m.id] = {i.asset for i in s.inputs}
        for u in s.upstream:
            if u.model_id in ids and u.model_id != m.id:
                g.add_edge(u.model_id, m.id, kind="feeds", via=u.via_asset, origin="spec")
    producers = {}
    for a in repo.assets.list(is_current=True):
        hit = ID_RE.search(f"{a.provenance} {a.description}")
        if hit and hit.group(1) in ids:
            producers[a.name] = hit.group(1)
    for mid, assets in reads.items():
        for a in assets:
            p = producers.get(a)
            if p and p != mid and not g.has_edge(p, mid):
                g.add_edge(p, mid, kind="feeds", via=a, origin="data_room")
    ms = sorted(reads)
    for i, a in enumerate(ms):
        for b in ms[i + 1:]:
            shared = reads[a] & reads[b]
            if shared and not g.has_edge(a, b) and not g.has_edge(b, a):
                g.add_edge(a, b, kind="shares_data", via=sorted(shared)[0], origin="data_room")
    _apply_overrides(g, models)
    return g


def overrides(meta: dict | None) -> dict:
    lin = (meta or {}).get("lineage") or {}
    return {"added": list(lin.get("added") or []), "removed": list(lin.get("removed") or [])}


def _apply_overrides(g: nx.DiGraph, models) -> None:
    for m in models:
        o = overrides(m.meta)
        for r in o["removed"]:
            if g.has_edge(r["source"], m.id):
                g.remove_edge(r["source"], m.id)
        for a in o["added"]:
            if a["source"] in g and a["source"] != m.id:
                if g.has_edge(m.id, a["source"]) and g[m.id][a["source"]].get("kind") == "shares_data":
                    g.remove_edge(m.id, a["source"])  # the explicit dependency supersedes the inferred link
                g.add_edge(a["source"], m.id, kind="feeds", via=a.get("via") or "", origin="manual",
                           note=a.get("note", ""), by=a.get("by", ""), at=a.get("at", ""))


def removed_edges() -> list[dict]:
    return [{**r, "target": m.id} for m in repo.models.list() for r in overrides(m.meta)["removed"]]


def blast_radius(g: nx.DiGraph, model_id: str) -> list[str]:
    """Models that consume this model's outputs, directly or indirectly (feeds edges only)."""
    feeds = nx.DiGraph([(u, v) for u, v, d in g.edges(data=True) if d.get("kind") == "feeds"])
    feeds.add_nodes_from(g.nodes)
    return sorted(nx.descendants(feeds, model_id)) if model_id in feeds else []


def as_json() -> dict:
    g = build()
    return {"nodes": [{"id": n, **d, "blast_radius": blast_radius(g, n)} for n, d in g.nodes(data=True)],
            "edges": [{"source": u, "target": v, **d} for u, v, d in g.edges(data=True)],
            "removed": removed_edges()}
