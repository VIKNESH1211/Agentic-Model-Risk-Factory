"use client";
import { useQuery } from "@tanstack/react-query";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node } from "@xyflow/react";
import clsx from "clsx";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Badge, Empty, Panel, Tag } from "@/components/ui";
import { get } from "@/lib/api";

const TIER: Record<string, { c: string; ring: string }> = {
  A: { c: "#f04461", ring: "rgba(240,68,97,.55)" },
  B: { c: "#f5a524", ring: "rgba(245,165,36,.5)" },
  C: { c: "#60a5fa", ring: "rgba(96,165,250,.5)" },
};
const POS: Record<string, [number, number]> = {
  "CR-001": [320, 170], "CR-003": [680, 40], "CR-002": [680, 320], "PR-001": [0, 320], "FR-001": [0, 40],
};

function ModelNode({ data }: { data: any }) {
  const t = TIER[data.tier] || TIER.C;
  return (
    <div className={clsx("rounded-xl px-4 py-3 w-[230px] bg-panel-2 border transition-all", data.dim && "opacity-30")}
      style={{ borderColor: data.hot ? "#a78bfa" : t.ring, boxShadow: data.hot ? "0 0 0 2px #a78bfa, 0 0 30px rgba(167,139,250,.6)" : data.selected ? `0 0 26px ${t.ring}` : undefined }}>
      <Handle type="target" position={Position.Left} style={{ background: t.c }} />
      <div className="flex items-center justify-between">
        <span className="mono font-bold text-[15px]">{data.id}</span>
        <span className="text-[11px] font-black px-1.5 rounded" style={{ color: t.c, border: `1px solid ${t.ring}` }}>TIER {data.tier}</span>
      </div>
      <div className="text-[13px] text-muted mt-1 leading-snug">{data.name}</div>
      <div className="text-[11px] text-faint mt-1">{data.type}</div>
      {data.hot && <div className="text-[11px] mt-1 font-bold text-agent">IN BLAST RADIUS</div>}
      <Handle type="source" position={Position.Right} style={{ background: t.c }} />
    </div>
  );
}
const nodeTypes = { model: ModelNode };
const EDGE: Record<string, { c: string; label: string; dash?: string }> = {
  feeds: { c: "#2dd4bf", label: "feeds" },
  challenger_of: { c: "#a78bfa", label: "challenger of", dash: "6 4" },
  shares_data: { c: "#8f98b8", label: "shares data", dash: "2 4" },
};

export default function Inventory() {
  const models = useQuery({ queryKey: ["models"], queryFn: () => get<any[]>("/api/models") });
  const graph = useQuery({ queryKey: ["graph"], queryFn: () => get("/api/graph") });
  const [sel, setSel] = useState<string | null>("CR-001");
  const selNode = graph.data?.nodes.find((n: any) => n.id === sel);
  const radius: string[] = selNode?.blast_radius || [];

  const { nodes, edges } = useMemo(() => {
    if (!graph.data) return { nodes: [], edges: [] };
    const nodes: Node[] = graph.data.nodes.map((n: any, i: number) => ({
      id: n.id, type: "model", position: { x: (POS[n.id] || [i * 260, 420])[0], y: (POS[n.id] || [0, 420])[1] },
      data: { ...n, selected: n.id === sel, hot: radius.includes(n.id), dim: sel && n.id !== sel && !radius.includes(n.id) },
    }));
    const edges: Edge[] = graph.data.edges.map((e: any) => {
      const s = EDGE[e.kind] || EDGE.shares_data;
      const live = e.kind === "feeds" && (e.source === sel || radius.includes(e.source)) && radius.includes(e.target);
      return {
        id: `${e.source}-${e.target}`, source: e.source, target: e.target, label: s.label, animated: live,
        style: { stroke: live ? "#a78bfa" : s.c, strokeWidth: live ? 3 : 1.6, strokeDasharray: s.dash },
        labelStyle: { fill: "#8f98b8", fontSize: 11 }, labelBgStyle: { fill: "#0f1630" },
        markerEnd: { type: MarkerType.ArrowClosed, color: live ? "#a78bfa" : s.c },
      };
    });
    return { nodes, edges };
  }, [graph.data, sel, radius]);

  if (models.data && !models.data.length)
    return <Panel><Empty title="No models discovered yet" action={<Link className="btn btn-primary" href="/">Go to Mission Control →</Link>}>Start the factory: the Discovery agent walks the legacy folders and builds the inventory from code alone.</Empty></Panel>;

  return (
    <div className="space-y-5 max-w-[1600px] mx-auto">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Inventory & Dependency Graph</h1>
        <p className="text-muted mt-1">Built by the Discovery agent from the legacy code: tiers by rule, lineage from file I/O. Click a model to see its downstream blast radius.</p>
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-5">
        <Panel title="Dependency graph" pad={false}>
          <div className="h-[520px]">
            <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.2 }}
              onNodeClick={(_, n) => setSel(n.id === sel ? null : n.id)} onPaneClick={() => setSel(null)} proOptions={{ hideAttribution: true }}>
              <Background color="rgba(148,163,255,.12)" gap={22} />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
        </Panel>
        <Panel title="Blast radius">
          {selNode ? (
            <div className="space-y-4">
              <div>
                <div className="mono text-2xl font-bold">{selNode.id}</div>
                <div className="text-muted">{selNode.name}</div>
              </div>
              <div className="text-6xl font-bold num text-agent">{radius.length}</div>
              <div className="text-muted -mt-2">downstream model(s) consume its outputs</div>
              {radius.length > 0 && (
                <ul className="space-y-1">{radius.map((r) => <li key={r} className="mono text-agent">→ {r}</li>)}</ul>
              )}
              <p className="text-sm text-muted">A defect or drift in {selNode.id} propagates to every model in its blast radius; the Monitor agent re-validates upstream first.</p>
              <Link href={`/models/${selNode.id}`} className="btn">Open workbench →</Link>
            </div>
          ) : <div className="text-muted">Select a node.</div>}
          <div className="mt-6 space-y-1.5 text-sm">
            {Object.entries(EDGE).map(([k, v]) => (
              <div key={k} className="flex items-center gap-2"><span className="inline-block w-8 border-t-2" style={{ borderColor: v.c, borderStyle: v.dash ? "dashed" : "solid" }} /> {v.label}</div>
            ))}
          </div>
        </Panel>
      </div>
      <Panel title="Model inventory" pad={false}>
        <table className="w-full text-[15px]">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-muted border-b border-line">
              <th className="px-5 py-3">ID</th><th>Name</th><th>Type</th><th>Tier</th><th>Owner</th><th>Status</th><th>Findings</th><th className="pr-5">Flags</th>
            </tr>
          </thead>
          <tbody>
            {(models.data || []).map((m) => (
              <tr key={m.id} className="border-b border-line/60 hover:bg-white/[.02]">
                <td className="px-5 py-3 mono font-bold"><Link href={`/models/${m.id}`} className="hover:text-teal">{m.id}</Link></td>
                <td>{m.name}</td>
                <td className="text-muted">{m.type}</td>
                <td><span className="font-black" style={{ color: TIER[m.tier]?.c }}>{m.tier}</span> <span className="text-xs text-muted">{m.tier_rationale?.slice(0, 60)}{m.tier_rationale?.length > 60 ? "…" : ""}</span></td>
                <td className="text-muted text-sm">{m.owner}</td>
                <td><Badge kind={m.status === "monitored" ? "completed" : m.status === "documented" ? "info" : "queued"} label={m.status} /></td>
                <td className="num">{m.findings}</td>
                <td className="pr-5 space-x-1">
                  {m.meta?.smells ? <Tag tone="warn">{m.meta.smells} smells</Tag> : null}
                  {m.meta?.injection_flags ? <Tag tone="agent">injection</Tag> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
