"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Connection, type Edge, type Node } from "@xyflow/react";
import clsx from "clsx";
import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowRight, Check, PackagePlus, Pencil, Plus, Trash2, Undo2 } from "lucide-react";
import { Badge, Empty, PageHeader, Panel, Tag, ago, inputCls } from "@/components/ui";
import { del, get, post, STAGE_LABEL } from "@/lib/api";
import { toast } from "@/lib/store";

const TIER: Record<string, { c: string; ring: string }> = {
  A: { c: "#dc2626", ring: "rgba(240,68,97,.55)" },
  B: { c: "#d97706", ring: "rgba(245,165,36,.5)" },
  C: { c: "#2563eb", ring: "rgba(96,165,250,.5)" },
};
/** Generic layout: column = longest chain of "feeds" edges into the node, rows stacked within a column. */
function layout(nodes: any[], edges: any[]): Record<string, [number, number]> {
  const depth: Record<string, number> = Object.fromEntries(nodes.map((n) => [n.id, 0]));
  for (let k = 0; k < nodes.length; k++)
    for (const e of edges) if (e.kind === "feeds") depth[e.target] = Math.max(depth[e.target], depth[e.source] + 1);
  const rows: Record<number, number> = {};
  const pos: Record<string, [number, number]> = {};
  for (const n of [...nodes].sort((a, b) => a.id.localeCompare(b.id))) {
    const c = depth[n.id];
    rows[c] = (rows[c] || 0) + 1;
    pos[n.id] = [c * 330, (rows[c] - 1) * 150];
  }
  return pos;
}

function ModelNode({ data }: { data: any }) {
  const t = TIER[data.tier] || TIER.C;
  return (
    <div className={clsx("rounded-xl px-4 py-3 w-[230px] bg-panel-2 border transition-all", data.dim && "opacity-30")}
      style={{ borderColor: data.hot ? "#7c3aed" : t.ring, boxShadow: data.hot ? "0 0 0 2px #7c3aed, 0 0 30px rgba(167,139,250,.6)" : data.selected ? `0 0 26px ${t.ring}` : undefined }}>
      <Handle type="target" position={Position.Left} style={{ background: t.c, ...(data.edit && HANDLE_EDIT) }} />
      <div className="flex items-center justify-between">
        <span className="mono font-bold text-[15px]">{data.id}</span>
        <span className="text-[11px] font-black px-1.5 rounded" style={{ color: t.c, border: `1px solid ${t.ring}` }}>TIER {data.tier}</span>
      </div>
      <div className="text-[13px] text-muted mt-1 leading-snug">{data.name}</div>
      <div className="text-[11px] text-faint mt-1">{data.type}</div>
      {data.hot && <div className="text-[11px] mt-1 font-bold text-agent">IN BLAST RADIUS</div>}
      <Handle type="source" position={Position.Right} style={{ background: t.c, ...(data.edit && HANDLE_EDIT) }} />
    </div>
  );
}
const HANDLE_EDIT = { width: 12, height: 12, border: "2px solid #fff", boxShadow: "0 0 0 1px rgba(15,23,42,.25)" };
const nodeTypes = { model: ModelNode };
const EDGE: Record<string, { c: string; label: string; dash?: string }> = {
  feeds: { c: "#0d9488", label: "feeds" },
  manual: { c: "#2563eb", label: "feeds (added by hand)" },
  challenger_of: { c: "#7c3aed", label: "challenger of", dash: "6 4" },
  shares_data: { c: "#64748b", label: "shares data", dash: "2 4" },
};

const ORIGIN_LABEL: Record<string, string> = { spec: "declared in the spec", data_room: "inferred from the data room", manual: "added by hand" };
const edgeKey = (s: string, t: string) => `${s}->${t}`;

export default function Inventory() {
  const qc = useQueryClient();
  const models = useQuery({ queryKey: ["models"], queryFn: () => get<any[]>("/api/models") });
  const graph = useQuery({ queryKey: ["graph"], queryFn: () => get("/api/graph") });
  const assets = useQuery({ queryKey: ["data-room"], queryFn: () => get<any[]>("/api/data-room") });
  const [sel, setSel] = useState<string | null>(null);
  const [edit, setEdit] = useState(false);
  const [selEdge, setSelEdge] = useState<string | null>(null);
  const [form, setForm] = useState({ source: "", target: "", via: "", note: "" });
  const [flash, setFlash] = useState(false);
  const selNode = graph.data?.nodes.find((n: any) => n.id === sel);
  const radius: string[] = selNode?.blast_radius || [];
  const edgeData = graph.data?.edges.find((e: any) => edgeKey(e.source, e.target) === selEdge);
  const ids: string[] = (graph.data?.nodes || []).map((n: any) => n.id).sort();

  const done = (msg: string) => (g: any) => { qc.setQueryData(["graph"], g); qc.invalidateQueries(); toast({ kind: "success", text: msg }); };
  const fail = (e: any) => toast({ kind: "error", text: e.message });
  const add = useMutation({ mutationFn: () => post("/api/graph/edges", form),
    onSuccess: (g) => { done(`${form.source} now feeds ${form.target}`)(g); setSelEdge(edgeKey(form.source, form.target)); setForm({ source: "", target: "", via: "", note: "" }); }, onError: fail });
  const remove = useMutation({ mutationFn: (e: any) => del(`/api/graph/edges?source=${encodeURIComponent(e.source)}&target=${encodeURIComponent(e.target)}`),
    onSuccess: (g, e: any) => { done(`Removed ${e.source} → ${e.target}`)(g); setSelEdge(null); }, onError: fail });
  const restore = useMutation({ mutationFn: (r: any) => post("/api/graph/edges", { source: r.source, target: r.target, restore: true }),
    onSuccess: (g, r: any) => done(`Restored ${r.source} → ${r.target}`)(g), onError: fail });

  const onConnect = (c: Connection) => {
    if (!c.source || !c.target) return;
    setForm((f) => ({ ...f, source: c.source!, target: c.target! }));
    setFlash(true); setTimeout(() => setFlash(false), 900);
  };
  const toggleEdit = () => { setEdit((v) => !v); setSel(null); setSelEdge(null); setForm({ source: "", target: "", via: "", note: "" }); };

  const { nodes, edges } = useMemo(() => {
    if (!graph.data) return { nodes: [], edges: [] };
    const POS = layout(graph.data.nodes, graph.data.edges);
    const nodes: Node[] = graph.data.nodes.map((n: any) => ({
      id: n.id, type: "model", position: { x: POS[n.id][0], y: POS[n.id][1] },
      data: { ...n, edit, selected: n.id === sel, hot: radius.includes(n.id), dim: sel && n.id !== sel && !radius.includes(n.id) },
    }));
    const edges: Edge[] = graph.data.edges.map((e: any) => {
      const s = e.origin === "manual" ? EDGE.manual : EDGE[e.kind] || EDGE.shares_data;
      const live = e.kind === "feeds" && (e.source === sel || radius.includes(e.source)) && radius.includes(e.target);
      const picked = edgeKey(e.source, e.target) === selEdge;
      const c = picked ? "#0f172a" : live ? "#7c3aed" : s.c;
      return {
        id: edgeKey(e.source, e.target), source: e.source, target: e.target, animated: live,
        label: `${e.kind === "feeds" ? "feeds" : s.label}${e.via ? ` · ${e.via}` : ""}${e.origin === "manual" ? " · manual" : ""}`,
        style: { stroke: c, strokeWidth: picked || live ? 3 : 1.6, strokeDasharray: s.dash, cursor: edit ? "pointer" : undefined },
        labelStyle: { fill: picked ? "#0f172a" : "#64748b", fontSize: 11, fontWeight: picked ? 600 : 400 }, labelBgStyle: { fill: "#ffffff" },
        markerEnd: { type: MarkerType.ArrowClosed, color: c }, interactionWidth: 18,
      };
    });
    return { nodes, edges };
  }, [graph.data, sel, radius, selEdge, edit]);

  if (models.data && !models.data.length)
    return <Panel><Empty title="No models onboarded yet" action={<Link className="btn btn-primary" href="/onboard">Onboard a model →</Link>}>Upload a legacy R script; the intake agent works out what it is.</Empty></Panel>;

  const removed: any[] = graph.data?.removed || [];
  const busy = add.isPending || remove.isPending || restore.isPending;

  return (
    <div className="space-y-5 max-w-[1600px] mx-auto">
      <PageHeader title="Models" sub="Every onboarded model, its approved specification and lineage. The graph is derived from the specs (declared upstream models, data-room files they share or produce) — you can correct it by hand. Click a node to see its downstream blast radius."
        actions={<Link href="/onboard" className="btn btn-primary"><PackagePlus size={16} /> Onboard a model</Link>} />
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-5">
        <Panel title="Dependency graph" pad={false} className={clsx(edit && "ring-2 ring-teal/40")}
          right={<button className={clsx("btn !py-1 text-xs", edit && "btn-primary")} onClick={toggleEdit}>{edit ? <><Check size={14} /> Done editing</> : <><Pencil size={14} /> Edit dependencies</>}</button>}>
          {edit && <div className="px-5 pb-2 text-xs text-muted">Drag from a model&apos;s <b>right</b> dot to another model&apos;s <b>left</b> dot to add a dependency. Click an arrow to select it for removal.</div>}
          <div className="h-[520px]">
            <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.2 }}
              nodesConnectable={edit} onConnect={onConnect} connectionLineStyle={{ stroke: "#2563eb", strokeWidth: 2, strokeDasharray: "5 4" }}
              onNodeClick={(_, n) => { if (!edit) setSel(n.id === sel ? null : n.id); }}
              onEdgeClick={(_, e) => { if (edit) setSelEdge(e.id === selEdge ? null : e.id); }}
              onPaneClick={() => { setSel(null); setSelEdge(null); }} proOptions={{ hideAttribution: true }}>
              <Background color="rgba(15,23,42,.10)" gap={22} />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
        </Panel>
        {edit ? (
          <div className="space-y-5">
            <Panel title="Add a dependency" className={clsx("transition-shadow", flash && "glow-teal")}>
              <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
                <div className="grid grid-cols-[1fr_auto_1fr] items-end gap-2">
                  <label className="text-xs text-muted">Upstream
                    <select required className={clsx(inputCls, "mt-1 mono !py-1.5")} value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })}>
                      <option value="">—</option>{ids.map((i) => <option key={i} disabled={i === form.target}>{i}</option>)}
                    </select>
                  </label>
                  <ArrowRight size={16} className="text-muted mb-2.5" />
                  <label className="text-xs text-muted">Downstream
                    <select required className={clsx(inputCls, "mt-1 mono !py-1.5")} value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })}>
                      <option value="">—</option>{ids.map((i) => <option key={i} disabled={i === form.source}>{i}</option>)}
                    </select>
                  </label>
                </div>
                <label className="block text-xs text-muted">Via data asset <span className="text-faint">(optional)</span>
                  <input list="dep-assets" className={clsx(inputCls, "mt-1 !py-1.5")} placeholder="e.g. pd_scores.csv" value={form.via} onChange={(e) => setForm({ ...form, via: e.target.value })} />
                  <datalist id="dep-assets">{(assets.data || []).map((a: any) => <option key={a.name} value={a.name} />)}</datalist>
                </label>
                <label className="block text-xs text-muted">Reason <span className="text-faint">(logged to the ledger)</span>
                  <input className={clsx(inputCls, "mt-1 !py-1.5")} placeholder="Why does this dependency exist?" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
                </label>
                <button type="submit" className="btn btn-primary w-full justify-center" disabled={busy || !form.source || !form.target}><Plus size={15} /> Add dependency</button>
              </form>
            </Panel>
            <Panel title="Selected dependency">
              {edgeData ? (
                <div className="space-y-3 text-sm">
                  <div className="flex items-center gap-2 mono text-lg font-bold">{edgeData.source} <ArrowRight size={16} className="text-muted" /> {edgeData.target}</div>
                  <ul className="space-y-1">
                    <li><span className="text-muted">Kind:</span> {EDGE[edgeData.kind]?.label || edgeData.kind}</li>
                    <li><span className="text-muted">Source:</span> {ORIGIN_LABEL[edgeData.origin] || edgeData.origin}</li>
                    {edgeData.via && <li><span className="text-muted">Via:</span> <span className="mono">{edgeData.via}</span></li>}
                    {edgeData.note && <li><span className="text-muted">Reason:</span> {edgeData.note}</li>}
                    {edgeData.by && <li className="text-xs text-faint">{edgeData.by} · {ago(edgeData.at)}</li>}
                  </ul>
                  <p className="text-xs text-muted">{edgeData.origin === "manual" ? "Removing a hand-added dependency deletes it." : "This link was derived automatically. Removing it hides it from the graph and blast radius; you can restore it below."}</p>
                  <button className="btn btn-danger w-full justify-center" disabled={busy} onClick={() => remove.mutate(edgeData)}><Trash2 size={15} /> Remove dependency</button>
                </div>
              ) : <div className="text-sm text-muted">Click an arrow in the graph to select it.</div>}
            </Panel>
            {removed.length > 0 && (
              <Panel title={`Removed links · ${removed.length}`}>
                <ul className="space-y-2">{removed.map((r) => (
                  <li key={edgeKey(r.source, r.target)} className="flex items-center justify-between gap-2 text-sm">
                    <div className="min-w-0"><div className="mono">{r.source} → {r.target}</div><div className="text-xs text-faint truncate">{EDGE[r.kind]?.label || r.kind}{r.via ? ` · ${r.via}` : ""} · {ORIGIN_LABEL[r.origin] || r.origin}</div></div>
                    <button className="btn !py-1 !px-2 text-xs shrink-0" disabled={busy} onClick={() => restore.mutate(r)}><Undo2 size={13} /> Restore</button>
                  </li>
                ))}</ul>
              </Panel>
            )}
          </div>
        ) : (
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
              <p className="text-sm text-muted">A defect or drift in {selNode.id} propagates to every model in its blast radius.</p>
              <Link href={`/models/${selNode.id}`} className="btn">Open workspace →</Link>
            </div>
          ) : <div className="text-muted">Select a node.</div>}
          <div className="mt-6 space-y-1.5 text-sm">
            {Object.entries(EDGE).map(([k, v]) => (
              <div key={k} className="flex items-center gap-2"><span className="inline-block w-8 border-t-2" style={{ borderColor: v.c, borderStyle: v.dash ? "dashed" : "solid" }} /> {v.label}</div>
            ))}
          </div>
        </Panel>
        )}
      </div>
      <Panel title="Inventory" pad={false}>
        <table className="w-full text-[14.5px]">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-muted border-b border-line">
              <th className="px-5 py-3">ID</th><th>Name · type</th><th>Tier</th><th>Spec</th><th>Validation plan</th><th>Lifecycle</th><th>Implementation</th><th>Findings</th><th className="pr-5">Files</th>
            </tr>
          </thead>
          <tbody>
            {(models.data || []).map((m) => {
              const lc = m.meta?.lifecycle || {};
              return (
                <tr key={m.id} className="border-b border-line/60 hover:bg-slate-900/[.02] align-top">
                  <td className="px-5 py-3 mono font-bold"><Link href={`/models/${m.id}`} className="hover:text-teal">{m.id}</Link></td>
                  <td className="py-3"><div>{m.name}</div><div className="text-xs text-muted">{m.type || m.description?.slice(0, 70)}</div></td>
                  <td className="py-3"><span className="font-black" style={{ color: TIER[m.tier]?.c }}>{m.tier || "—"}</span></td>
                  <td className="py-3">{m.spec ? <Tag tone={m.spec.status === "approved" ? "teal" : "warn"}>v{m.spec.version} {m.spec.status}</Tag> : <span className="text-faint">—</span>}</td>
                  <td className="py-3">{m.validation_plan ? <Tag tone={m.validation_plan.status === "approved" ? "teal" : "warn"}>v{m.validation_plan.version} {m.validation_plan.status}</Tag> : <span className="text-faint">—</span>}</td>
                  <td className="py-3 text-sm">{STAGE_LABEL[lc.stage] || lc.stage || "onboarded"} <span className="text-muted">· {lc.status || "idle"}</span></td>
                  <td className="py-3">{m.meta?.parity_verdict ? <Badge kind={m.meta.parity_verdict === "PASS" ? "PASS" : "warn"} label={m.meta.parity_verdict} /> : <span className="text-faint">—</span>}</td>
                  <td className="py-3 num">{m.findings}</td>
                  <td className="py-3 pr-5 text-xs mono text-muted">{m.files.join(", ")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
