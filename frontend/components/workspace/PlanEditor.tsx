"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Braces, Check, Plus, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { get, post, put } from "@/lib/api";
import { toast } from "@/lib/store";
import { Field, Modal, Panel, Tag, inputCls } from "../ui";
import { Versions } from "./Versions";

const CAT_C: Record<string, string> = { performance: "text-teal", calibration: "text-info", stability: "text-agent", fairness: "text-warn",
  data_quality: "text-muted", policy: "text-fail", implementation: "text-pass" };
const num = (v: string) => (v === "" ? null : Number(v));

function usePlan(modelId: string, kind: string) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["plan", modelId, kind], queryFn: () => get(`/api/models/${modelId}/plans/${kind}`) });
  const [picked, setPicked] = useState<any>(null);
  const [body, setBody] = useState<any>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [diff, setDiff] = useState<any>(null);
  const row = picked || q.data?.current;
  useEffect(() => { if (row) { setBody(structuredClone(row.body)); setErrors([]); } }, [row?.id]); // eslint-disable-line
  const save = useMutation({ mutationFn: (b: any) => put(`/api/models/${modelId}/plans/${kind}`, { body: b, note: "edited in the workspace" }),
    onSuccess: (r: any) => { setPicked(null); setErrors([]); qc.invalidateQueries({ queryKey: ["plan", modelId, kind] }); toast({ kind: "success", text: `${kind} plan v${r.version} saved as a draft` }); },
    onError: (e: any) => { setErrors(e.detail?.lint || [e.message]); toast({ kind: "error", text: "The plan linter rejected the change" }); } });
  const approve = useMutation({ mutationFn: () => post(`/api/models/${modelId}/plans/${kind}/approve`, { by: "Model Risk Officer" }),
    onSuccess: (r: any) => { qc.invalidateQueries(); toast({ kind: "success", text: `${kind} plan v${r.version} approved` }); } });
  const showDiff = async (a: number, b: number) => setDiff(await get(`/api/models/${modelId}/plans/${kind}/diff?a=${a}&b=${b}`));
  return { q, row, body, setBody, errors, save, approve, setPicked, diff, setDiff, showDiff, dirty: row && body && JSON.stringify(row.body) !== JSON.stringify(body) };
}

function Toolbar({ p, label }: { p: ReturnType<typeof usePlan>; label: string }) {
  const latest = p.q.data.versions[0]?.version;
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-sm text-muted">{label} <b className="text-text mono">v{p.row.version}</b> · {p.row.status}</span>
      {p.row.note && <span className="text-xs rounded-md bg-agent/10 border border-agent/30 text-agent px-2 py-1 max-w-[560px] truncate" title={p.row.note}>🤖 {p.row.note}</span>}
      <div className="flex-1" />
      <button className="btn !py-1.5 text-sm" disabled={!p.dirty || p.save.isPending} onClick={() => p.save.mutate(p.body)}><Save size={15} /> Save as v{latest + 1}</button>
      {p.row.version === latest && p.row.status !== "approved" &&
        <button className="btn btn-primary !py-1.5 text-sm" disabled={!!p.dirty || p.approve.isPending} onClick={() => p.approve.mutate()}><Check size={15} /> Approve v{p.row.version}</button>}
    </div>
  );
}

function Errors({ errors }: { errors: string[] }) {
  if (!errors.length) return null;
  return <div className="rounded-lg border border-fail/50 bg-fail/[.07] p-3 text-sm"><b className="text-fail">Plan linter:</b><ul className="list-disc ml-5 mt-1">{errors.map((e) => <li key={e}>{e}</li>)}</ul></div>;
}

function AddCheck({ open, onClose, catalog, columns, onAdd }: { open: boolean; onClose: () => void; catalog: any[]; columns: string[]; onAdd: (c: any) => void }) {
  const [c, setC] = useState<any>({ id: "", title: "", category: "performance", metric: "gini", params: {}, severity: "medium", threshold: { op: "<", amber: null, red: null }, rationale: "" });
  const m = catalog.find((x) => x.fn === c.metric);
  const setP = (k: string, v: any) => setC({ ...c, params: { ...c.params, [k]: v } });
  return (
    <Modal open={open} onClose={onClose} title="Add a check from the metric catalog" wide>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Field label="Metric"><select className={inputCls} value={c.metric} onChange={(e) => { const mm = catalog.find((x) => x.fn === e.target.value); setC({ ...c, metric: e.target.value, params: {}, threshold: { ...c.threshold, op: mm?.better === "higher" ? "<" : ">" } }); }}>
          {catalog.map((x) => <option key={x.fn} value={x.fn}>{x.fn}</option>)}</select></Field>
        <Field label="Id"><input className={clsx(inputCls, "mono")} value={c.id} onChange={(e) => setC({ ...c, id: e.target.value })} placeholder="performance.gini_oot" /></Field>
        <Field label="Category"><select className={inputCls} value={c.category} onChange={(e) => setC({ ...c, category: e.target.value })}>{Object.keys(CAT_C).map((k) => <option key={k}>{k}</option>)}</select></Field>
        <Field className="md:col-span-3" label="Title"><input className={inputCls} value={c.title} onChange={(e) => setC({ ...c, title: e.target.value })} /></Field>
      </div>
      {m && <p className="text-sm text-muted mt-3">{m.description}{m.note ? ` — ${m.note}` : ""} · {m.better ? <b>{m.better} is better</b> : "two-sided"}</p>}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
        {m && Object.entries(m.params).map(([p, kind]: any) => (
          <Field key={p} label={`${p}${m.required.includes(p) ? " *" : ""}`}>
            {kind === "col" ? <select className={clsx(inputCls, "mono")} value={c.params[p] || ""} onChange={(e) => setP(p, e.target.value || undefined)}><option value="">—</option>{columns.map((x) => <option key={x}>{x}</option>)}</select>
              : kind === "split" ? <select className={inputCls} value={c.params[p] || ""} onChange={(e) => setP(p, e.target.value || undefined)}><option value="">—</option>{["train", "test", "oot", "all", "test|oot"].map((x) => <option key={x}>{x}</option>)}</select>
              : kind === "num" ? <input type="number" step="any" className={clsx(inputCls, "mono")} value={c.params[p] ?? ""} onChange={(e) => setP(p, num(e.target.value) ?? undefined)} />
              : kind === "bool" ? <input type="checkbox" checked={!!c.params[p]} onChange={(e) => setP(p, e.target.checked)} />
              : <input className={clsx(inputCls, "mono")} value={c.params[p] || ""} onChange={(e) => setP(p, e.target.value || undefined)} />}
          </Field>
        ))}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mt-3">
        <Field label="Breach when value"><select className={inputCls} value={c.threshold.op} onChange={(e) => setC({ ...c, threshold: { ...c.threshold, op: e.target.value } })}>{["<", "<=", ">", ">="].map((x) => <option key={x}>{x}</option>)}</select></Field>
        <Field label="Amber"><input type="number" step="any" className={clsx(inputCls, "mono")} value={c.threshold.amber ?? ""} onChange={(e) => setC({ ...c, threshold: { ...c.threshold, amber: num(e.target.value) } })} /></Field>
        <Field label="Red"><input type="number" step="any" className={clsx(inputCls, "mono")} value={c.threshold.red ?? ""} onChange={(e) => setC({ ...c, threshold: { ...c.threshold, red: num(e.target.value) } })} /></Field>
        <Field label="Severity"><select className={inputCls} value={c.severity} onChange={(e) => setC({ ...c, severity: e.target.value })}>{["high", "medium", "low"].map((x) => <option key={x}>{x}</option>)}</select></Field>
        <Field label="Expand"><select className={inputCls} value={c.expand || ""} onChange={(e) => setC({ ...c, expand: e.target.value || null })}><option value="">—</option><option value="features">per feature</option><option value="groups">per group</option></select></Field>
      </div>
      <div className="flex justify-end gap-2 mt-5">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" disabled={!c.id || !c.title} onClick={() => { onAdd({ ...c, threshold: c.threshold.amber == null && c.threshold.red == null ? null : c.threshold }); onClose(); }}><Plus size={15} /> Add check</button>
      </div>
    </Modal>
  );
}

export function ValidationPlanEditor({ modelId }: { modelId: string }) {
  const p = usePlan(modelId, "validation");
  const [adding, setAdding] = useState(false);
  if (p.q.isLoading) return <div className="text-muted">Loading…</div>;
  if (!p.q.data?.current || !p.body) return <Panel><div className="text-muted py-10 text-center">No validation plan yet — the documentation agent proposes one after the spec is approved.</div></Panel>;
  const checks: any[] = p.body.checks || [];
  const setCheck = (i: number, patch: any) => p.setBody({ ...p.body, checks: checks.map((c, j) => (j === i ? { ...c, ...patch } : c)) });
  const byCat = Object.entries(checks.reduce((a: any, c) => ({ ...a, [c.category]: (a[c.category] || 0) + 1 }), {}));
  return (
    <div className="grid grid-cols-1 xl:grid-cols-[1fr_250px] gap-5">
      <div className="space-y-4">
        <Toolbar p={p} label="Validation plan" />
        <Errors errors={p.errors} />
        <div className="flex flex-wrap gap-2 text-sm">{byCat.map(([k, n]: any) => <span key={k} className={clsx("rounded-md border border-line px-2 py-0.5", CAT_C[k])}>{k.replace("_", " ")} · {n}</span>)}</div>
        {p.body.rationale && <p className="text-sm text-muted">{p.body.rationale}</p>}
        <Panel pad={false}>
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full text-[13.5px]">
              <thead><tr className="text-left text-[11px] uppercase tracking-wider text-muted border-b border-line">
                <th className="px-4 py-2.5">Check</th><th>Metric · params</th><th>Breach</th><th>Amber</th><th>Red</th><th>Severity</th><th className="pr-3"></th></tr></thead>
              <tbody>
                {checks.map((c, i) => (
                  <tr key={c.id + i} className="border-t border-line/50 align-top hover:bg-slate-900/[.015]">
                    <td className="px-4 py-2.5 max-w-[320px]">
                      <div className="font-medium">{c.title}</div>
                      <div className="mono text-[11.5px] text-faint">{c.id} · <span className={CAT_C[c.category]}>{c.category}</span>{c.expand ? ` · per ${c.expand.replace(/s$/, "")}` : ""}</div>
                      {c.rationale && <div className="text-xs text-muted mt-0.5 line-clamp-2" title={c.rationale}>{c.rationale}</div>}
                    </td>
                    <td className="py-2.5 pr-3"><span className="mono text-teal">{c.metric}</span><div className="mono text-[11px] text-muted max-w-[260px] break-words">{Object.entries(c.params || {}).map(([k, v]) => `${k}=${v}`).join(" · ")}</div></td>
                    <td className="py-2"><select className={clsx(inputCls, "!py-1 !px-1.5 w-16 mono")} value={c.threshold?.op || ""} onChange={(e) => setCheck(i, { threshold: e.target.value ? { ...(c.threshold || {}), op: e.target.value } : null })}>
                      <option value="">info</option>{["<", "<=", ">", ">="].map((x) => <option key={x}>{x}</option>)}</select></td>
                    {(["amber", "red"] as const).map((lvl) => (
                      <td key={lvl} className="py-2"><input disabled={!c.threshold} type="number" step="any" className={clsx(inputCls, "!py-1 !px-1.5 w-[84px] mono", lvl === "red" ? "focus:border-fail" : "focus:border-warn")}
                        value={c.threshold?.[lvl] ?? ""} onChange={(e) => setCheck(i, { threshold: { ...c.threshold, [lvl]: num(e.target.value) } })} /></td>
                    ))}
                    <td className="py-2"><select className={clsx(inputCls, "!py-1 !px-1.5 w-[92px]")} value={c.severity} onChange={(e) => setCheck(i, { severity: e.target.value })}>{["high", "medium", "low"].map((x) => <option key={x}>{x}</option>)}</select></td>
                    <td className="py-2 pr-3"><button onClick={() => p.setBody({ ...p.body, checks: checks.filter((_, j) => j !== i) })} aria-label="remove check"><Trash2 size={15} className="text-muted hover:text-fail" /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-4 py-3 border-t border-line flex items-center gap-2 flex-wrap">
            <button className="btn !py-1.5 text-sm" onClick={() => setAdding(true)}><Plus size={15} /> Add check</button>
            <span className="text-xs text-muted ml-2">Investigations the agent may run:</span>
            {["challenger", "slice_search", "stress_test", "fuzz"].map((x) => {
              const on = (p.body.investigations || []).includes(x);
              return <button key={x} onClick={() => p.setBody({ ...p.body, investigations: on ? p.body.investigations.filter((y: string) => y !== x) : [...(p.body.investigations || []), x] })}
                className={clsx("rounded-md border px-2 py-0.5 text-xs mono", on ? "border-teal/60 text-teal bg-teal/10" : "border-line text-muted")}>{x}</button>;
            })}
          </div>
        </Panel>
      </div>
      <div className="space-y-4">
        <Panel title="Versions"><Versions versions={p.q.data.versions} current={p.row.version} onPick={p.setPicked} onDiff={p.showDiff} /></Panel>
        <Panel title="Scored-frame columns"><div className="mono text-[11.5px] text-muted leading-relaxed">{p.q.data.columns.join(", ")}</div></Panel>
      </div>
      <AddCheck open={adding} onClose={() => setAdding(false)} catalog={p.q.data.catalog} columns={p.q.data.columns}
        onAdd={(c) => p.setBody({ ...p.body, checks: [...checks, c] })} />
      <Modal open={!!p.diff} onClose={() => p.setDiff(null)} title={p.diff ? `Validation plan v${p.diff.a} → v${p.diff.b}` : ""} wide>
        {p.diff && <div className="space-y-3 text-sm">
          <div><b className="text-pass">Added:</b> {p.diff.added.join(", ") || "—"}</div><div><b className="text-fail">Removed:</b> {p.diff.removed.join(", ") || "—"}</div>
          {p.diff.changed.map((c: any) => <div key={c.id}><b className="mono">{c.id}</b><ul className="ml-5 list-disc">{c.changes.map((x: any) => <li key={x.field} className="mono text-xs">{x.field}: {JSON.stringify(x.before)} → {JSON.stringify(x.after)}</li>)}</ul></div>)}
        </div>}
      </Modal>
    </div>
  );
}

export function MonitoringPlanEditor({ modelId }: { modelId: string }) {
  const p = usePlan(modelId, "monitoring");
  if (p.q.isLoading) return <div className="text-muted">Loading…</div>;
  if (!p.q.data?.current || !p.body) return <Panel><div className="text-muted py-10 text-center">No monitoring plan yet — the documentation agent proposes one after the spec is approved.</div></Panel>;
  const kpis = Object.keys(p.q.data.catalog || {});
  const b = p.body;
  const setRule = (i: number, patch: any) => p.setBody({ ...b, rules: b.rules.map((r: any, j: number) => (j === i ? { ...r, ...patch } : r)) });
  const setPanel = (i: number, patch: any) => p.setBody({ ...b, panels: b.panels.map((r: any, j: number) => (j === i ? { ...r, ...patch } : r)) });
  return (
    <div className="grid grid-cols-1 xl:grid-cols-[1fr_250px] gap-5">
      <div className="space-y-4">
        <Toolbar p={p} label="Monitoring plan" />
        <Errors errors={p.errors} />
        <Panel title="Alert rules" right={<button className="btn !py-1 text-xs" onClick={() => p.setBody({ ...b, rules: [...b.rules, { id: `rule_${b.rules.length + 1}`, kpi: "score_psi", op: ">", threshold: 0.25, windows: 3, severity: "amber", action: "notify" }] })}><Plus size={13} /> rule</button>} pad={false}>
          <table className="w-full text-[13.5px]">
            <thead><tr className="text-left text-[11px] uppercase tracking-wider text-muted"><th className="px-4 py-2">Rule</th><th>KPI</th><th>Fires when</th><th>Threshold</th><th>Windows</th><th>Severity</th><th>Action</th><th /></tr></thead>
            <tbody>{b.rules.map((r: any, i: number) => (
              <tr key={i} className="border-t border-line/50">
                <td className="px-4 py-1.5"><input className={clsx(inputCls, "!py-1 mono text-xs")} value={r.id} onChange={(e) => setRule(i, { id: e.target.value })} /></td>
                <td><select className={clsx(inputCls, "!py-1 mono text-xs")} value={r.kpi} onChange={(e) => setRule(i, { kpi: e.target.value })}>{kpis.map((k) => <option key={k}>{k}</option>)}</select></td>
                <td><select className={clsx(inputCls, "!py-1 w-16 mono")} value={r.op} onChange={(e) => setRule(i, { op: e.target.value })}>{[">", ">=", "<", "<="].map((x) => <option key={x}>{x}</option>)}</select></td>
                <td><input type="number" step="any" className={clsx(inputCls, "!py-1 w-24 mono")} value={r.threshold} onChange={(e) => setRule(i, { threshold: Number(e.target.value) })} /></td>
                <td><input type="number" min={1} className={clsx(inputCls, "!py-1 w-16 mono")} value={r.windows} onChange={(e) => setRule(i, { windows: Number(e.target.value) })} /></td>
                <td><select className={clsx(inputCls, "!py-1")} value={r.severity} onChange={(e) => setRule(i, { severity: e.target.value })}><option>amber</option><option>red</option></select></td>
                <td><select className={clsx(inputCls, "!py-1")} value={r.action} onChange={(e) => setRule(i, { action: e.target.value })}><option>notify</option><option>revalidate</option></select></td>
                <td className="pr-3"><button onClick={() => p.setBody({ ...b, rules: b.rules.filter((_: any, j: number) => j !== i) })} aria-label="remove rule"><Trash2 size={15} className="text-muted hover:text-fail" /></button></td>
              </tr>
            ))}</tbody>
          </table>
        </Panel>
        <Panel title="Dashboard panels" right={<button className="btn !py-1 text-xs" onClick={() => p.setBody({ ...b, panels: [...b.panels, { id: `panel_${b.panels.length + 1}`, title: "New panel", kind: "line", kpis: ["score_psi"] }] })}><Plus size={13} /> panel</button>}>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {b.panels.map((pn: any, i: number) => (
              <div key={i} className="rounded-lg border border-line p-3 space-y-2">
                <div className="flex gap-2">
                  <input className={clsx(inputCls, "!py-1 text-sm")} value={pn.title} onChange={(e) => setPanel(i, { title: e.target.value })} />
                  <select className={clsx(inputCls, "!py-1 w-24")} value={pn.kind} onChange={(e) => setPanel(i, { kind: e.target.value })}>{["line", "area", "bar", "stat"].map((x) => <option key={x}>{x}</option>)}</select>
                  <button onClick={() => p.setBody({ ...b, panels: b.panels.filter((_: any, j: number) => j !== i) })} aria-label="remove panel"><Trash2 size={15} className="text-muted" /></button>
                </div>
                <div className="flex flex-wrap gap-1">{kpis.map((k) => {
                  const on = pn.kpis.includes(k);
                  return <button key={k} onClick={() => setPanel(i, { kpis: on ? pn.kpis.filter((x: string) => x !== k) : [...pn.kpis, k] })}
                    className={clsx("rounded border px-1.5 py-px text-[11px] mono", on ? "border-teal/60 text-teal bg-teal/10" : "border-line text-faint")}>{k}</button>;
                })}</div>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Drift scenarios (for the traffic simulator)">
          <div className="space-y-3">
            {b.scenarios.map((s: any, i: number) => (
              <div key={i} className="rounded-lg border border-line p-3">
                <div className="flex items-center gap-2"><b>{s.title}</b> <span className="mono text-xs text-faint">{s.id}</span>
                  <button className="ml-auto" onClick={() => p.setBody({ ...b, scenarios: b.scenarios.filter((_: any, j: number) => j !== i) })} aria-label="remove scenario"><Trash2 size={15} className="text-muted" /></button></div>
                {s.description && <div className="text-sm text-muted">{s.description}</div>}
                <div className="flex flex-wrap gap-1.5 mt-2">{s.transforms.map((t: any, j: number) => <Tag key={j} tone="agent">{t.op} {t.column} {String(t.value)} · {Math.round(t.fraction * 100)}%</Tag>)}</div>
              </div>
            ))}
          </div>
        </Panel>
        <div className="flex items-center gap-3 text-sm">
          <Field label="Requests per minute"><input type="number" className={clsx(inputCls, "w-32 mono")} value={b.rpm} onChange={(e) => p.setBody({ ...b, rpm: Number(e.target.value) })} /></Field>
        </div>
      </div>
      <div className="space-y-4">
        <Panel title="Versions"><Versions versions={p.q.data.versions} current={p.row.version} onPick={p.setPicked} /></Panel>
        <Panel title="KPI catalog"><ul className="space-y-1.5 text-xs">{Object.entries(p.q.data.catalog || {}).map(([k, d]: any) => <li key={k}><span className="mono text-teal">{k}</span> <span className="text-muted">{d}</span></li>)}</ul></Panel>
      </div>
    </div>
  );
}
