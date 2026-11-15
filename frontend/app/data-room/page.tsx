"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Database, Upload } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";
import { Empty, Field, PageHeader, Panel, Tag, ago, inputCls } from "@/components/ui";
import { get, upload } from "@/lib/api";
import { toast } from "@/lib/store";

export default function DataRoom() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["data-room"], queryFn: () => get<any[]>("/api/data-room") });
  const [sel, setSel] = useState<string | null>(null);
  const a = useQuery({ queryKey: ["asset", sel], queryFn: () => get(`/api/data-room/${encodeURIComponent(sel!)}`), enabled: !!sel });
  const [meta, setMeta] = useState({ description: "", provenance: "" });
  const ref = useRef<HTMLInputElement>(null);
  const up = useMutation({ mutationFn: (f: File) => upload("/api/data-room", [f], meta, "file"),
    onSuccess: (r: any) => { qc.invalidateQueries({ queryKey: ["data-room"] }); setSel(r.name); toast({ kind: "success", text: `${r.name} v${r.version} uploaded (${r.rows.toLocaleString()} rows)` }); },
    onError: (e: any) => toast({ kind: "error", text: e.message }) });
  return (
    <div className="space-y-5 max-w-[1600px] mx-auto">
      <PageHeader title="Data room" sub="The shared drive legacy scripts read from (mounted at //shared/riskdata in the sandbox; files referenced by relative path are copied into the working directory). Uploading a file with an existing name adds a new version — earlier versions stay for lineage."
        actions={<>
          <input ref={ref} type="file" className="hidden" onChange={(e) => e.target.files?.[0] && up.mutate(e.target.files[0])} />
          <button className="btn btn-primary" onClick={() => ref.current?.click()} disabled={up.isPending}><Upload size={16} /> Upload file</button>
        </>} />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-3xl">
        <Field label="Description for the next upload"><input className={inputCls} value={meta.description} onChange={(e) => setMeta({ ...meta, description: e.target.value })} /></Field>
        <Field label="Provenance" hint='e.g. "real · UCI", "synthetic", "produced by CR-001"'><input className={inputCls} value={meta.provenance} onChange={(e) => setMeta({ ...meta, provenance: e.target.value })} /></Field>
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_1.2fr] gap-5">
        <Panel pad={false} title="Files">
          {q.isSuccess && !q.data.length ? <Empty title="The data room is empty">Upload the CSVs your legacy scripts read.</Empty> : (
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs uppercase tracking-wider text-muted"><th className="px-4 py-2">File</th><th>Rows</th><th>Columns</th><th>Version</th><th>Used by</th><th className="pr-4">Provenance</th></tr></thead>
              <tbody>{(q.data || []).map((f) => (
                <tr key={f.name} onClick={() => setSel(f.name)} className={clsx("border-t border-line/50 cursor-pointer hover:bg-slate-900/[.02]", sel === f.name && "bg-teal/[.06]")}>
                  <td className="px-4 py-2.5"><span className="flex items-center gap-2"><Database size={14} className="text-info" /><span className="mono">{f.name}</span></span></td>
                  <td className="num">{f.rows?.toLocaleString()}</td><td className="num">{f.profile?.columns?.length ?? 0}</td><td><Tag>v{f.version}{f.versions > 1 ? ` of ${f.versions}` : ""}</Tag></td>
                  <td>{f.used_by.map((m: string) => <Link key={m} href={`/models/${m}`} className="mono text-teal mr-1.5" onClick={(e) => e.stopPropagation()}>{m}</Link>)}</td>
                  <td className="pr-4 text-xs text-muted max-w-[240px] truncate" title={f.provenance}>{f.provenance}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Panel>
        <Panel title={sel ? <span className="mono normal-case tracking-normal text-sm text-text">{sel}</span> : "Preview"}>
          {!sel ? <div className="text-muted text-sm">Select a file to see its profile and first rows.</div> : !a.data ? <div className="text-muted">Loading…</div> : (
            <div className="space-y-4">
              <div className="text-sm text-muted">{a.data.description} · {a.data.size?.toLocaleString()} bytes · sha256 <span className="mono">{a.data.sha256?.slice(0, 12)}…</span> · uploaded {ago(a.data.created_at)}</div>
              <div className="overflow-x-auto scroll-thin rounded-lg border border-line">
                <table className="text-xs mono">
                  <thead><tr className="text-left text-muted">{(a.data.preview?.columns || []).map((c: string) => <th key={c} className="px-2 py-1.5 whitespace-nowrap">{c}</th>)}</tr></thead>
                  <tbody>{(a.data.preview?.data || []).slice(0, 12).map((r: any[], i: number) => <tr key={i} className="border-t border-line/40">{r.map((v, j) => <td key={j} className="px-2 py-1 whitespace-nowrap text-slate-700">{String(v ?? "NA")}</td>)}</tr>)}</tbody>
                </table>
              </div>
              <div>
                <div className="panel-title mb-2">Column profile</div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1 text-xs max-h-[300px] overflow-y-auto scroll-thin">
                  {(a.data.profile?.columns || []).map((c: any) => (
                    <div key={c.name} className="flex items-center gap-2 border-b border-line/30 py-1">
                      <span className="mono flex-1 truncate">{c.name}</span><span className="text-faint">{c.dtype}</span>
                      <span className={c.missing ? "text-warn" : "text-faint"}>{c.missing} NA</span><span className="text-faint">{c.unique} uniq</span>
                    </div>
                  ))}
                </div>
              </div>
              {a.data.versions?.length > 1 && <div className="text-xs text-muted">Versions: {a.data.versions.map((v: any) => `v${v.version} (${v.rows} rows, ${ago(v.created_at)})`).join(" · ")}</div>}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
