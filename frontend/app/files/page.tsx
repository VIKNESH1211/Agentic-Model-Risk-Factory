"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ChevronDown, ChevronRight, File, FileCode2, FileSpreadsheet, Folder } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Empty, Hash, Panel, Tag } from "@/components/ui";
import { get } from "@/lib/api";

const ROOTS = [
  { id: "legacy", label: "Legacy code", note: "The bank's R models exactly as found — the factory never edits them." },
  { id: "data_room", label: "Data room", note: "Files the legacy scripts expect under //shared/riskdata (mounted into the sandbox)." },
  { id: "runs", label: "Run artifacts", note: "Everything each run produced: Python translation, sandbox exports, parity files, validation evidence." },
];

function icon(n: string, dir: boolean) {
  if (dir) return Folder;
  if (/\.(R|py)$/.test(n)) return FileCode2;
  if (/\.(csv)$/.test(n)) return FileSpreadsheet;
  return File;
}

function Tree({ nodes, root, sel, onSel, owners, depth = 0 }: any) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  return (
    <ul>
      {nodes.map((n: any) => {
        const I = icon(n.name, n.dir);
        const isOpen = open[n.path] ?? (depth === 0 && root === "legacy");
        return (
          <li key={n.path}>
            <button onClick={() => (n.dir ? setOpen({ ...open, [n.path]: !isOpen }) : onSel(n.path))}
              className={clsx("w-full flex items-center gap-1.5 py-1 pr-2 text-left text-[14px] rounded hover:bg-white/[.04]", sel === n.path && "bg-teal/10 text-teal")}
              style={{ paddingLeft: 8 + depth * 14 }}>
              {n.dir ? (isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />) : <span className="w-[13px]" />}
              <I size={14} className={n.dir ? "text-warn" : "text-muted"} />
              <span className="truncate flex-1">{n.name}</span>
              {owners?.[n.name] && <span className="mono text-[11px] text-agent">{owners[n.name]}</span>}
              {!n.dir && <span className="text-[11px] text-faint">{n.size > 1e6 ? `${(n.size / 1e6).toFixed(1)}MB` : n.size > 1e3 ? `${(n.size / 1e3).toFixed(0)}KB` : `${n.size}B`}</span>}
            </button>
            {n.dir && isOpen && <Tree nodes={n.children || []} root={root} sel={sel} onSel={onSel} depth={depth + 1} />}
          </li>
        );
      })}
    </ul>
  );
}

function Csv({ text }: { text: string }) {
  const rows = text.split("\n").slice(0, 60).map((l) => l.split(",").map((c) => c.replace(/^"|"$/g, "")));
  return (
    <div className="overflow-auto scroll-thin max-h-[620px] border border-line rounded-lg">
      <table className="text-[12.5px] mono">
        <thead className="sticky top-0 bg-panel-2"><tr>{rows[0]?.map((h, i) => <th key={i} className="px-2 py-1.5 text-left text-muted whitespace-nowrap border-b border-line">{h}</th>)}</tr></thead>
        <tbody>{rows.slice(1).map((r, i) => <tr key={i} className="border-b border-line/40">{r.map((c, j) => <td key={j} className="px-2 py-1 whitespace-nowrap">{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function Code({ text, parse }: { text: string; parse?: any }) {
  const smell = new Map<number, string>((parse?.smells || []).map((s: any) => [s.line, s.kind]));
  const inj = new Set<number>((parse?.injection || []).map((s: any) => s.line));
  return (
    <div className="mono text-[13px] leading-[1.7] bg-black/30 rounded-lg border border-line overflow-auto scroll-thin max-h-[620px]">
      {text.split("\n").map((l, i) => {
        const n = i + 1;
        return (
          <div key={i} className={clsx("flex", inj.has(n) && "bg-fail/15", smell.has(n) && !inj.has(n) && "bg-warn/10")}>
            <span className="w-12 shrink-0 text-right pr-3 text-faint select-none">{n}</span>
            <span className={clsx("whitespace-pre pr-4 flex-1", l.trim().startsWith("#") ? "text-muted" : "text-[#d7dcff]")}>{l || " "}</span>
            {inj.has(n) && <span className="px-2 text-fail font-sans text-xs font-bold whitespace-nowrap">prompt injection</span>}
            {smell.has(n) && !inj.has(n) && <span className="px-2 text-warn font-sans text-xs whitespace-nowrap">{smell.get(n)?.replace(/_/g, " ")}</span>}
          </div>
        );
      })}
    </div>
  );
}

function Files() {
  const sp = useSearchParams();
  const router = useRouter();
  const root = sp.get("root") || "legacy";
  const path = sp.get("path") || "";
  const tree = useQuery({ queryKey: ["tree", root], queryFn: () => get(`/api/files/tree?root=${root}`) });
  const file = useQuery({ queryKey: ["file", root, path], queryFn: () => get(`/api/files/read?root=${root}&path=${encodeURIComponent(path)}`), enabled: !!path });
  const f = file.data;
  const go = (r: string, p = "") => router.push(`/files?root=${r}${p ? `&path=${encodeURIComponent(p)}` : ""}`);
  return (
    <div className="space-y-4 max-w-[1700px] mx-auto">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Models Folder</h1>
        <p className="text-muted mt-1">{ROOTS.find((r) => r.id === root)?.note}</p>
      </div>
      <div className="flex gap-1.5">
        {ROOTS.map((r) => <button key={r.id} onClick={() => go(r.id)} className={clsx("rounded-lg border px-3 py-1.5 text-sm font-semibold", r.id === root ? "border-teal bg-teal/10 text-teal" : "border-line text-muted hover:text-text")}>{r.label}</button>)}
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-[360px_1fr] gap-5">
        <Panel title="Files" pad={false}>
          <div className="px-2 pb-3 max-h-[calc(100vh-260px)] overflow-y-auto scroll-thin">
            {tree.data?.tree?.length ? <Tree nodes={tree.data.tree} root={root} sel={path} onSel={(p: string) => go(root, p)} owners={root === "legacy" ? tree.data.owners : undefined} /> : <div className="p-4 text-muted text-sm">{root === "runs" ? "No runs yet." : "Empty."}</div>}
          </div>
        </Panel>
        <Panel title={f ? <span className="mono normal-case tracking-normal text-text">{f.path}</span> : "Viewer"}
          right={f && <div className="flex items-center gap-3 text-xs text-muted"><span>{f.lines ?? "—"} lines</span><span>{(f.size / 1024).toFixed(1)} KB</span><span>sha256 <Hash v={f.sha256} /></span></div>}>
          {!path ? <Empty title="Pick a file">{root === "legacy" ? "Each folder is one model; the agent that discovered it labels it with its ID." : "Choose a file on the left."}</Empty> : !f ? <div className="text-muted">Loading…</div> : f.binary ? <Empty title="Binary file">{f.path} · not previewable</Empty> : (
            <div className="space-y-3">
              {f.parse && (
                <div className="flex flex-wrap gap-2 text-sm">
                  <Tag tone="agent">{f.parse.id}</Tag>
                  {f.parse.methods.map((m: string) => <Tag key={m} tone="teal">{m}</Tag>)}
                  {f.parse.libraries.map((m: string) => <Tag key={m}>library({m})</Tag>)}
                  {f.parse.smells.length > 0 && <Tag tone="warn">{f.parse.smells.length} code smells</Tag>}
                  {f.parse.injection.length > 0 && <span className="rounded border border-fail/50 text-fail px-1.5 text-[11px] font-bold uppercase">injection attempt</span>}
                  {f.parse.reads.length > 0 && <span className="text-muted">reads: <span className="mono text-xs">{f.parse.reads.join(", ")}</span></span>}
                </div>
              )}
              {f.kind === "csv" ? <Csv text={f.text} /> : f.kind === "json" ? <pre className="mono text-[12.5px] bg-black/30 border border-line rounded-lg p-3 overflow-auto max-h-[620px] scroll-thin">{(() => { try { return JSON.stringify(JSON.parse(f.text), null, 2); } catch { return f.text; } })()}</pre> : <Code text={f.text} parse={f.parse} />}
              {f.truncated && <div className="text-xs text-faint">Showing the first lines only.</div>}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}

export default function FilesPage() {
  return <Suspense><Files /></Suspense>;
}
