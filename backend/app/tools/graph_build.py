"""Model dependency graph + downstream blast radius."""
from __future__ import annotations

import networkx as nx
from sqlmodel import select

from app.core.db import session
from app.domain.tables import Model, ModelEdge


def build() -> nx.DiGraph:
    g = nx.DiGraph()
    with session() as s:
        for m in s.exec(select(Model)).all():
            g.add_node(m.id, name=m.name, tier=m.tier, status=m.status, type=m.type)
        prio = {"feeds": 0, "challenger_of": 1, "shares_data": 2}
        for e in sorted(s.exec(select(ModelEdge)).all(), key=lambda e: prio.get(e.kind, 9)):
            if not g.has_edge(e.src_id, e.dst_id):  # one edge per direction; strongest kind wins
                g.add_edge(e.src_id, e.dst_id, kind=e.kind)
    return g


def blast_radius(g: nx.DiGraph, model_id: str) -> list[str]:
    """Models that consume this model's outputs, directly or indirectly (feeds edges only)."""
    feeds = nx.DiGraph([(u, v) for u, v, d in g.edges(data=True) if d.get("kind") == "feeds"])
    feeds.add_nodes_from(g.nodes)
    return sorted(nx.descendants(feeds, model_id)) if model_id in feeds else []


def as_json() -> dict:
    g = build()
    return {
        "nodes": [{"id": n, **d, "blast_radius": blast_radius(g, n)} for n, d in g.nodes(data=True)],
        "edges": [{"source": u, "target": v, "kind": d["kind"]} for u, v, d in g.edges(data=True)],
    }
