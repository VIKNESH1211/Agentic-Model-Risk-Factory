"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Field, PageHeader, Panel, Tabs, Tag, ago, inputCls } from "@/components/ui";
import { del, get, post, put } from "@/lib/api";
import { toast } from "@/lib/store";

function Prompts() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["prompts"], queryFn: () => get<any[]>("/api/library/prompts") });
  const [key, setKey] = useState<string | null>(null);
  const cur = (q.data || []).find((p) => p.key === key) || q.data?.[0];
  const [txt, setTxt] = useState("");
  useEffect(() => { if (cur) setTxt(cur.text); }, [cur?.key, cur?.version]); // eslint-disable-line
  const vers = useQuery({ queryKey: ["prompt-v", cur?.key], queryFn: () => get<any[]>(`/api/library/prompts/${cur.key}/versions`), enabled: !!cur });
  const save = useMutation({ mutationFn: () => put(`/api/library/prompts/${cur.key}`, { text: txt, author: "Model Risk Officer" }),
    onSuccess: (r: any) => { qc.invalidateQueries({ queryKey: ["prompts"] }); qc.invalidateQueries({ queryKey: ["prompt-v"] }); toast({ kind: "success", text: `${cur.key} v${r.version} is now active` }); },
    onError: (e: any) => toast({ kind: "error", text: e.message }) });
  const reset = useMutation({ mutationFn: () => post(`/api/library/prompts/${cur.key}/reset`), onSuccess: () => { qc.invalidateQueries(); toast({ kind: "success", text: "Reset to the shipped default" }); } });
  if (!cur) return <div className="text-muted">Loading…</div>;
  return (
    <div className="grid grid-cols-1 xl:grid-cols-[300px_1fr] gap-5">
      <div className="space-y-1.5">
        {(q.data || []).map((p) => (
          <button key={p.key} onClick={() => setKey(p.key)} className={clsx("w-full text-left rounded-lg border px-3 py-2", cur.key === p.key ? "border-teal/60 bg-teal/[.06]" : "border-line hover:bg-slate-900/[.03]")}>
            <div className="flex justify-between items-center"><span className="mono text-[13px] font-semibold">{p.key}</span><span className="flex gap-1"><Tag>v{p.version}</Tag>{!p.is_default && <Tag tone="warn">edited</Tag>}</span></div>
            <div className="text-xs text-muted mt-0.5">{p.description}</div>
          </button>
        ))}
      </div>
      <div className="space-y-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="mono font-bold">{cur.key}</span><span className="text-sm text-muted">v{cur.version} by {cur.author} · {ago(cur.updated_at)}</span>
          <div className="flex-1" />
          <button className="btn !py-1.5 text-sm" disabled={cur.is_default || reset.isPending} onClick={() => reset.mutate()}><RotateCcw size={15} /> Reset to default</button>
          <button className="btn btn-primary !py-1.5 text-sm" disabled={txt === cur.text || save.isPending} onClick={() => save.mutate()}><Save size={15} /> Save as v{cur.version + 1}</button>
        </div>
        <div className="text-xs text-muted">Placeholders the agent fills in (must stay): {cur.variables.map((v: string) => <code key={v} className="mono text-teal mr-1.5">{`{{${v}}}`}</code>)} · Editing a prompt changes agent behaviour immediately (and misses the LLM cache).</div>
        <textarea className={clsx(inputCls, "mono text-[12.5px] leading-relaxed min-h-[560px]")} value={txt} onChange={(e) => setTxt(e.target.value)} spellCheck={false} />
        <div className="text-xs text-muted">History: {(vers.data || []).map((v) => `v${v.version} (${v.author}, ${ago(v.created_at)})`).join(" · ")}</div>
      </div>
    </div>
  );
}

function Policies() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["policies"], queryFn: () => get<any[]>("/api/library/policies") });
  const [edit, setEdit] = useState<any>(null);
  const save = useMutation({ mutationFn: (p: any) => put(`/api/library/policies/${p.code}`, p), onSuccess: () => { qc.invalidateQueries({ queryKey: ["policies"] }); setEdit(null); toast({ kind: "success", text: "Policy check saved" }); },
    onError: (e: any) => toast({ kind: "error", text: e.message }) });
  const remove = useMutation({ mutationFn: (code: string) => del(`/api/library/policies/${code}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["policies"] }) });
  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center"><p className="text-sm text-muted max-w-3xl">Deterministic code-review rules run on every legacy script by the documentation agent. Hits become findings with the exact line. Model-specific issues come from the agent's own code review on top.</p>
        <button className="btn" onClick={() => setEdit({ code: `PC-${String((q.data?.length || 0) + 1).padStart(2, "0")}`, title: "", category: "governance", severity: "medium", kind: "regex", pattern: "", description: "", enabled: true, _new: true })}><Plus size={15} /> New rule</button></div>
      {edit && (
        <Panel title={edit._new ? "New policy check" : `Edit ${edit.code}`}>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <Field label="Code"><input className={clsx(inputCls, "mono")} value={edit.code} disabled={!edit._new} onChange={(e) => setEdit({ ...edit, code: e.target.value })} /></Field>
            <Field label="Title" className="md:col-span-3"><input className={inputCls} value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} /></Field>
            <Field label="Category"><input className={inputCls} value={edit.category} onChange={(e) => setEdit({ ...edit, category: e.target.value })} /></Field>
            <Field label="Severity"><select className={inputCls} value={edit.severity} onChange={(e) => setEdit({ ...edit, severity: e.target.value })}>{["high", "medium", "low", "info"].map((x) => <option key={x}>{x}</option>)}</select></Field>
            <Field label="Kind"><select className={inputCls} value={edit.kind} onChange={(e) => setEdit({ ...edit, kind: e.target.value })}>{["regex", "injection", "comment_code"].map((x) => <option key={x}>{x}</option>)}</select></Field>
            <Field label="Enabled"><input type="checkbox" className="accent-[#0d9488] h-5 w-5" checked={edit.enabled} onChange={(e) => setEdit({ ...edit, enabled: e.target.checked })} /></Field>
            {edit.kind === "regex" && <Field label="Pattern (regex, case-insensitive)" className="md:col-span-4"><input className={clsx(inputCls, "mono")} value={edit.pattern} onChange={(e) => setEdit({ ...edit, pattern: e.target.value })} /></Field>}
            <Field label="Why it matters" className="md:col-span-4"><textarea className={inputCls} value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
          </div>
          <div className="flex justify-end gap-2 mt-3"><button className="btn" onClick={() => setEdit(null)}>Cancel</button><button className="btn btn-primary" onClick={() => { const { _new, ...p } = edit; save.mutate(p); }}><Save size={15} /> Save</button></div>
        </Panel>
      )}
      <Panel pad={false}>
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wider text-muted"><th className="px-4 py-2">Code</th><th>Rule</th><th>Severity</th><th>Kind</th><th>Pattern</th><th>On</th><th className="pr-4" /></tr></thead>
          <tbody>{(q.data || []).map((p) => (
            <tr key={p.code} className="border-t border-line/50 align-top">
              <td className="px-4 py-2 mono">{p.code}</td><td className="py-2 pr-3"><div className="font-medium">{p.title}</div><div className="text-xs text-muted">{p.description}</div></td>
              <td className="py-2"><Badge kind={p.severity} /></td><td className="py-2"><Tag>{p.kind}</Tag></td>
              <td className="py-2 mono text-[11px] text-muted max-w-[260px] break-all">{p.pattern || "—"}</td>
              <td className="py-2">{p.enabled ? <span className="text-pass">●</span> : <span className="text-faint">○</span>}</td>
              <td className="py-2 pr-4 whitespace-nowrap"><button className="text-teal text-xs mr-3" onClick={() => setEdit(p)}>edit</button><button onClick={() => remove.mutate(p.code)} aria-label="delete"><Trash2 size={14} className="text-muted hover:text-fail" /></button></td>
            </tr>
          ))}</tbody>
        </table>
      </Panel>
    </div>
  );
}

function Catalog() {
  const q = useQuery({ queryKey: ["metric-catalog"], queryFn: () => get("/api/library/metrics") });
  if (!q.data) return <div className="text-muted">Loading…</div>;
  return (
    <div className="grid grid-cols-1 xl:grid-cols-[1fr_420px] gap-5">
      <Panel pad={false} title="Metric catalog — the only functions a validation plan can use">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wider text-muted"><th className="px-4 py-2">Metric</th><th>Definition</th><th>Better</th><th>Parameters</th><th className="pr-4">Tasks</th></tr></thead>
          <tbody>{q.data.metrics.map((m: any) => (
            <tr key={m.fn} className="border-t border-line/50 align-top">
              <td className="px-4 py-2 mono text-teal">{m.fn}</td><td className="py-2 pr-3">{m.description}{m.note && <div className="text-xs text-muted">{m.note}</div>}</td>
              <td className="py-2">{m.better ? <Tag tone={m.better === "higher" ? "teal" : "warn"}>{m.better}</Tag> : <span className="text-faint">—</span>}</td>
              <td className="py-2 mono text-[11px] text-muted">{Object.keys(m.params).map((p) => m.required.includes(p) ? `${p}*` : p).join(", ")}</td>
              <td className="py-2 pr-4 text-xs text-muted">{m.tasks.join(", ")}</td>
            </tr>
          ))}</tbody>
        </table>
      </Panel>
      <div className="space-y-5">
        <Panel title="Live KPIs (monitoring plans)"><ul className="space-y-1.5 text-sm">{Object.entries(q.data.kpis).map(([k, v]: any) => <li key={k}><span className="mono text-teal">{k}</span> <span className="text-muted">— {v}</span></li>)}</ul></Panel>
        <Panel title="Standard scored-frame columns"><div className="mono text-sm text-muted">{q.data.standard_columns.join(", ")}</div></Panel>
      </div>
    </div>
  );
}

export default function LibraryPage() {
  const [tab, setTab] = useState<"prompts" | "policies" | "catalog">("prompts");
  return (
    <div className="space-y-5 max-w-[1700px] mx-auto">
      <PageHeader title="Library" sub="Platform knowledge that is the same for every model — versioned and editable here, never hard-coded: the prompts every agent sends, the policy rules every script is checked against, and the metric catalog plans are built from." />
      <Tabs tabs={[{ id: "prompts", label: "Prompt templates" }, { id: "policies", label: "Policy checks" }, { id: "catalog", label: "Metric & KPI catalog" }]} value={tab} onChange={setTab} />
      {tab === "prompts" && <Prompts />}
      {tab === "policies" && <Policies />}
      {tab === "catalog" && <Catalog />}
    </div>
  );
}
