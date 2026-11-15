"use client";
import clsx from "clsx";
import { Badge, ago } from "../ui";

/** Version rail shared by the spec and plan editors. */
export function Versions({ versions, current, onPick, onDiff }: { versions: any[]; current?: number; onPick: (v: any) => void; onDiff?: (a: number, b: number) => void }) {
  return (
    <div className="space-y-1.5">
      {versions.map((v, i) => (
        <div key={v.id} className={clsx("rounded-lg border px-3 py-2 cursor-pointer transition", current === v.version ? "border-teal/60 bg-teal/[.06]" : "border-line hover:bg-slate-900/[.03]")}
          onClick={() => onPick(v)}>
          <div className="flex items-center justify-between gap-2">
            <span className="mono font-bold text-sm">v{v.version}</span>
            <Badge kind={v.status === "approved" ? "approved" : v.status === "draft" ? "pending" : "n/a"} label={v.status} />
          </div>
          <div className="text-xs text-muted mt-0.5 truncate">{(v.author || "").replace("agent:", "🤖 ").replace("human:", "👤 ")} · {ago(v.created_at)}</div>
          {v.approved_by && <div className="text-[11px] text-pass">approved by {v.approved_by}</div>}
          {onDiff && i < versions.length - 1 && (
            <button className="text-[11px] text-teal hover:underline mt-0.5" onClick={(e) => { e.stopPropagation(); onDiff(versions[i + 1].version, v.version); }}>
              diff vs v{versions[i + 1].version}
            </button>
          )}
        </div>
      ))}
      {!versions.length && <div className="text-sm text-muted">No versions yet.</div>}
    </div>
  );
}

export function DiffList({ changes }: { changes: { field: string; before: any; after: any }[] }) {
  if (!changes.length) return <div className="text-muted text-sm">No differences.</div>;
  return (
    <table className="w-full text-sm">
      <thead><tr className="text-left text-xs uppercase text-muted"><th className="py-1.5">Field</th><th>Before</th><th>After</th></tr></thead>
      <tbody>{changes.map((c) => (
        <tr key={c.field} className="border-t border-line/60 align-top">
          <td className="py-1.5 pr-3 mono text-xs text-muted">{c.field}</td>
          <td className="pr-3 mono text-xs text-fail whitespace-pre-wrap break-all">{JSON.stringify(c.before)}</td>
          <td className="mono text-xs text-teal whitespace-pre-wrap break-all">{JSON.stringify(c.after)}</td>
        </tr>
      ))}</tbody>
    </table>
  );
}
