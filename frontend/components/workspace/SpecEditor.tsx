"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Braces, Check, Plus, Save, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { get, post, put } from "@/lib/api";
import { toast } from "@/lib/store";
import { Field, Modal, Panel, Tag, inputCls } from "../ui";
import { DiffList, Versions } from "./Versions";

function Chips({ value, onChange, suggestions, placeholder }: { value: string[]; onChange: (v: string[]) => void; suggestions?: string[]; placeholder?: string }) {
  const [txt, setTxt] = useState("");
  const addOne = (v: string) => { v = v.trim(); if (v && !value.includes(v)) onChange([...value, v]); setTxt(""); };
  return (
    <div className={clsx(inputCls, "flex flex-wrap gap-1.5 !py-1.5")}>
      {value.map((v) => (
        <span key={v} className="inline-flex items-center gap-1 rounded-md bg-slate-900/[.07] px-2 py-0.5 text-[13px] mono">
          {v}<button onClick={() => onChange(value.filter((x) => x !== v))} aria-label={`remove ${v}`}><X size={12} className="text-muted" /></button>
        </span>
      ))}
      <input list={placeholder} value={txt} onChange={(e) => setTxt(e.target.value)} placeholder={placeholder}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addOne(txt); } }}
        onBlur={() => txt && addOne(txt)} className="bg-transparent outline-none flex-1 min-w-[120px] text-[14px]" />
      {suggestions && <datalist id={placeholder}>{suggestions.map((s) => <option key={s} value={s} />)}</datalist>}
    </div>
  );
}

export function SpecEditor({ modelId }: { modelId: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["spec", modelId], queryFn: () => get(`/api/models/${modelId}/spec`) });
  const room = useQuery({ queryKey: ["data-room"], queryFn: () => get<any[]>("/api/data-room") });
  const [picked, setPicked] = useState<any>(null);
  const [body, setBody] = useState<any>(null);
  const [raw, setRaw] = useState(false);
  const [rawTxt, setRawTxt] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [diff, setDiff] = useState<any>(null);
  const row = picked || q.data?.current;
  useEffect(() => { if (row) { setBody(structuredClone(row.body)); setRawTxt(JSON.stringify(row.body, null, 2)); setErrors([]); } }, [row?.id]); // eslint-disable-line
  const cols = useMemo(() => {
    const frames = q.data?.probe?.frames || {};
    return Array.from(new Set(Object.values(frames).flatMap((c: any) => c.map((x: any) => x.column)))) as string[];
  }, [q.data]);
  const dirty = row && body && JSON.stringify(body) !== JSON.stringify(row.body);
  const save = useMutation({
    mutationFn: () => put(`/api/models/${modelId}/spec`, { body: raw ? JSON.parse(rawTxt) : body, note: "edited in the workspace" }),
    onSuccess: (r: any) => { setPicked(null); setErrors([]); qc.invalidateQueries({ queryKey: ["spec", modelId] }); toast({ kind: "success", text: `Spec v${r.version} saved as a draft` }); },
    onError: (e: any) => { setErrors(e.detail?.lint || [e.message]); toast({ kind: "error", text: "The linter rejected the spec" }); },
  });
  const approve = useMutation({ mutationFn: () => post(`/api/models/${modelId}/spec/approve`, { by: "Model Risk Officer" }),
    onSuccess: (r: any) => { qc.invalidateQueries(); toast({ kind: "success", text: `Spec v${r.version} approved` }); } });
  const showDiff = async (a: number, b: number) => setDiff(await get(`/api/models/${modelId}/spec/diff?a=${a}&b=${b}`));
  if (q.isLoading) return <div className="text-muted">Loading…</div>;
  if (!q.data?.current) return <Panel><div className="text-muted py-10 text-center">No specification yet — start the model; the intake agent drafts one.</div></Panel>;
  const set = (k: string, v: any) => setBody((b: any) => ({ ...b, [k]: v }));
  const setD = (k: string, v: any) => setBody((b: any) => ({ ...b, decision: { ...b.decision, [k]: v } }));
  const b = body || {};
  const isLatest = row?.version === q.data.versions[0]?.version;
  return (
    <div className="grid grid-cols-1 xl:grid-cols-[1fr_260px] gap-5">
      <div className="space-y-4">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm text-muted">Viewing <b className="text-text mono">v{row.version}</b> · {row.status}</span>
          {row.note && <span className="text-xs rounded-md bg-agent/10 border border-agent/30 text-agent px-2 py-1 max-w-[640px] truncate" title={row.note}>🤖 {row.note}</span>}
          <div className="flex-1" />
          <button className={clsx("btn !py-1.5 text-sm", raw && "glow-teal")} onClick={() => { if (!raw) setRawTxt(JSON.stringify(body, null, 2)); else { try { setBody(JSON.parse(rawTxt)); } catch {} } setRaw(!raw); }}><Braces size={15} /> JSON</button>
          <button className="btn !py-1.5 text-sm" disabled={!(dirty || raw) || save.isPending} onClick={() => save.mutate()}><Save size={15} /> Save as v{q.data.versions[0].version + 1}</button>
          {isLatest && row.status !== "approved" && <button className="btn btn-primary !py-1.5 text-sm" disabled={!!dirty || approve.isPending} onClick={() => approve.mutate()}><Check size={15} /> Approve v{row.version}</button>}
        </div>
        {errors.length > 0 && <div className="rounded-lg border border-fail/50 bg-fail/[.07] p-3 text-sm"><b className="text-fail">Linter:</b><ul className="list-disc ml-5 mt-1">{errors.map((e) => <li key={e}>{e}</li>)}</ul></div>}
        {raw ? <textarea className={clsx(inputCls, "mono text-[12.5px] min-h-[640px]")} value={rawTxt} onChange={(e) => setRawTxt(e.target.value)} spellCheck={false} /> : (
          <>
            <Panel title="Identity & risk">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Field label="Name"><input className={inputCls} value={b.name || ""} onChange={(e) => set("name", e.target.value)} /></Field>
                <Field label="Type"><input className={inputCls} value={b.model_type || ""} onChange={(e) => set("model_type", e.target.value)} /></Field>
                <Field label="Owner"><input className={inputCls} value={b.owner || ""} onChange={(e) => set("owner", e.target.value)} /></Field>
                <Field className="md:col-span-3" label="Purpose"><textarea className={clsx(inputCls, "min-h-[60px]")} value={b.purpose || ""} onChange={(e) => set("purpose", e.target.value)} /></Field>
                <Field label="Tier"><select className={inputCls} value={b.tier} onChange={(e) => set("tier", e.target.value)}>{["A", "B", "C"].map((t) => <option key={t}>{t}</option>)}</select></Field>
                <Field className="md:col-span-2" label="Tier rationale"><input className={inputCls} value={b.tier_rationale || ""} onChange={(e) => set("tier_rationale", e.target.value)} /></Field>
              </div>
            </Panel>
            <Panel title="How it runs">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Field label="Entry script"><input className={clsx(inputCls, "mono")} value={b.entry_script || ""} onChange={(e) => set("entry_script", e.target.value)} /></Field>
                <Field className="md:col-span-2" label="Command-line arguments" hint="What the batch job passes"><Chips value={b.harness?.args || []} onChange={(v) => set("harness", { ...b.harness, args: v })} placeholder="args" /></Field>
              </div>
              <div className="mt-4">
                <div className="text-xs font-semibold uppercase tracking-[.1em] text-muted mb-1.5">Inputs · file the script reads → data-room asset</div>
                <div className="space-y-1.5">
                  {(b.inputs || []).map((m: any, i: number) => (
                    <div key={i} className="flex items-center gap-2">
                      <input className={clsx(inputCls, "mono !py-1.5")} value={m.ref} onChange={(e) => set("inputs", b.inputs.map((x: any, j: number) => j === i ? { ...x, ref: e.target.value } : x))} />
                      <span className="text-muted">→</span>
                      <select className={clsx(inputCls, "mono !py-1.5")} value={m.asset} onChange={(e) => set("inputs", b.inputs.map((x: any, j: number) => j === i ? { ...x, asset: e.target.value } : x))}>
                        {[m.asset, ...(room.data || []).map((a) => a.name)].filter((v, k, a) => a.indexOf(v) === k).map((a) => <option key={a}>{a}</option>)}
                      </select>
                      <button onClick={() => set("inputs", b.inputs.filter((_: any, j: number) => j !== i))} aria-label="remove input"><Trash2 size={15} className="text-muted" /></button>
                    </div>
                  ))}
                  <button className="btn !py-1 text-xs" onClick={() => set("inputs", [...(b.inputs || []), { ref: "", asset: room.data?.[0]?.name || "" }])}><Plus size={13} /> input</button>
                </div>
              </div>
            </Panel>
            <Panel title="What it models">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <Field label="Task"><select className={inputCls} value={b.task} onChange={(e) => set("task", e.target.value)}>{["binary", "frequency", "regression", "rules"].map((t) => <option key={t}>{t}</option>)}</select></Field>
                <Field label="Strategy" hint="translate = exact Python rebuild"><select className={inputCls} value={b.strategy} onChange={(e) => set("strategy", e.target.value)}>{["translate", "rehost"].map((t) => <option key={t}>{t}</option>)}</select></Field>
                <Field label="Target"><input list="cols" className={clsx(inputCls, "mono")} value={b.target || ""} onChange={(e) => set("target", e.target.value || null)} /></Field>
                <Field label="Exposure"><input list="cols" className={clsx(inputCls, "mono")} value={b.exposure || ""} onChange={(e) => set("exposure", e.target.value || null)} /></Field>
                <Field className="md:col-span-4" label={`Features (${(b.features || []).length})`} hint="Raw inputs, before any binning or transformation"><Chips value={b.features || []} onChange={(v) => set("features", v)} suggestions={cols} placeholder="cols" /></Field>
              </div>
              <datalist id="cols">{cols.map((c) => <option key={c} value={c} />)}</datalist>
            </Panel>
            <Panel title="Decision rule">
              <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                <Field label="Kind"><select className={inputCls} value={b.decision?.kind} onChange={(e) => setD("kind", e.target.value)}>{["approve", "alert", "price", "limit", "none"].map((t) => <option key={t}>{t}</option>)}</select></Field>
                <Field label="Adverse when score"><select className={inputCls} value={b.decision?.op} onChange={(e) => setD("op", e.target.value)}>{[">", ">=", "<", "<="].map((t) => <option key={t}>{t}</option>)}</select></Field>
                <Field label="Cut-off"><input type="number" step="any" className={clsx(inputCls, "mono")} value={b.decision?.cutoff ?? ""} onChange={(e) => setD("cutoff", e.target.value === "" ? null : Number(e.target.value))} /></Field>
                <Field label="Adverse label"><input className={clsx(inputCls, "mono")} value={b.decision?.adverse_label || ""} onChange={(e) => setD("adverse_label", e.target.value)} /></Field>
                <Field label="Favourable label"><input className={clsx(inputCls, "mono")} value={b.decision?.favourable_label || ""} onChange={(e) => setD("favourable_label", e.target.value)} /></Field>
              </div>
            </Panel>
            <Panel title="Fairness & segment groups">
              <div className="space-y-2">
                {(b.groups || []).map((g: any, i: number) => (
                  <div key={i} className="grid grid-cols-[1fr_1fr_2fr_auto] gap-2 items-center">
                    <input className={clsx(inputCls, "mono !py-1.5")} value={g.name} onChange={(e) => set("groups", b.groups.map((x: any, j: number) => j === i ? { ...x, name: e.target.value } : x))} placeholder="group name" />
                    <input list="cols" className={clsx(inputCls, "mono !py-1.5")} value={g.column} onChange={(e) => set("groups", b.groups.map((x: any, j: number) => j === i ? { ...x, column: e.target.value } : x))} placeholder="source column" />
                    <span className="text-xs text-muted mono truncate" title={JSON.stringify(g.bins ? { bins: g.bins, labels: g.labels } : g.regex_map)}>
                      {g.bins ? `bins ${JSON.stringify(g.bins)} → ${JSON.stringify(g.labels)}` : g.regex_map ? `regex ${JSON.stringify(g.regex_map)}` : "values as-is"}
                    </span>
                    <button onClick={() => set("groups", b.groups.filter((_: any, j: number) => j !== i))} aria-label="remove group"><Trash2 size={15} className="text-muted" /></button>
                  </div>
                ))}
                <div className="text-xs text-faint">Bins and regex maps can be edited in JSON mode.</div>
              </div>
            </Panel>
            <Panel title="Lineage, deployment & notes">
              <div className="flex items-center gap-4 flex-wrap">
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-[#0d9488]" checked={!!b.deployable} onChange={(e) => set("deployable", e.target.checked)} /> Deployable (used for live decisions)</label>
                {(b.upstream || []).map((u: any) => <Tag key={u.model_id}>upstream {u.model_id} via {u.via_asset}</Tag>)}
              </div>
              <ul className="mt-3 space-y-1 text-sm text-slate-700 list-disc ml-5">{(b.notes || []).map((n: string, i: number) => <li key={i}>{n}</li>)}</ul>
            </Panel>
          </>
        )}
      </div>
      <div className="space-y-4">
        <Panel title="Versions"><Versions versions={q.data.versions} current={row.version} onPick={setPicked} onDiff={showDiff} /></Panel>
        {cols.length > 0 && (
          <Panel title="Probed data frames">
            <div className="space-y-2 text-xs">
              {Object.entries(q.data.probe?.frames || {}).map(([f, cs]: any) => (
                <details key={f}><summary className="cursor-pointer mono">{f} <span className="text-faint">({cs.length} cols)</span></summary>
                  <div className="mt-1 mono text-faint leading-relaxed">{cs.map((c: any) => c.column).join(", ")}</div></details>
              ))}
            </div>
          </Panel>
        )}
      </div>
      <Modal open={!!diff} onClose={() => setDiff(null)} title={diff ? `Spec v${diff.a} → v${diff.b}` : ""} wide>{diff && <DiffList changes={diff.changes} />}</Modal>
    </div>
  );
}
