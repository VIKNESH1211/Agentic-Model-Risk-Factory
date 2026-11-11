"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Ev } from "@/components/Evidence";
import { FindingRow } from "@/components/FindingRow";
import { ModelPicker } from "@/components/ModelPicker";
import { Badge, Empty, Hash, Panel, Tag } from "@/components/ui";
import { get } from "@/lib/api";

const TABS = ["Document", "Redevelop", "Validate", "Monitor", "Findings", "Source"] as const;
const SECTION_LABEL: Record<string, string> = {
  purpose: "Purpose & use", data: "Data", methodology: "Methodology", variables: "Variables", implementation: "Implementation",
  assumptions_limitations: "Assumptions & limitations", monitoring: "Monitoring", gaps: "Documentation gaps",
};

function Source({ src, doc }: { src: string; doc: any }) {
  const smell = new Map<number, string>((doc?.smells || []).map((s: any) => [s.line, s.kind]));
  const inj = new Set<number>((doc?.injection || []).map((s: any) => s.line));
  return (
    <div className="mono text-[13px] leading-[1.7] bg-black/30 rounded-lg border border-line overflow-x-auto scroll-thin max-h-[640px]">
      {src.split("\n").map((l, i) => {
        const n = i + 1;
        return (
          <div key={i} className={clsx("flex", inj.has(n) && "bg-fail/15", smell.has(n) && !inj.has(n) && "bg-warn/10")}>
            <span className="w-12 shrink-0 text-right pr-3 text-faint select-none">{n}</span>
            <span className={clsx("whitespace-pre pr-4 flex-1", l.trim().startsWith("#") ? "text-muted" : "text-[#d7dcff]")}>{l || " "}</span>
            {inj.has(n) && <span className="px-2 text-fail font-sans text-xs font-bold">🛡 injection</span>}
            {smell.has(n) && !inj.has(n) && <span className="px-2 text-warn font-sans text-xs">{smell.get(n)?.replace(/_/g, " ")}</span>}
          </div>
        );
      })}
    </div>
  );
}

export default function Workbench() {
  const { id } = useParams<{ id: string }>();
  const [tab, setTab] = useState<(typeof TABS)[number]>("Document");
  const q = useQuery({ queryKey: ["model", id], queryFn: () => get(`/api/models/${id}`) });
  const mon = useQuery({ queryKey: ["monitor", id], queryFn: () => get(`/api/monitor/${id}`), enabled: tab === "Monitor" });
  if (q.isError) return <Panel><Empty title={`${id} not in inventory yet`} action={<Link className="btn btn-primary" href="/">Start the factory →</Link>} /></Panel>;
  const d = q.data;
  if (!d) return <div className="text-muted">Loading…</div>;
  const m = d.model, doc = d.doc;
  const parityRun = m.meta?.parity_run_id;
  const tk = (n: string) => `m:${parityRun}:${n}`;
  return (
    <div className="space-y-5 max-w-[1500px] mx-auto">
      <ModelPicker current={m.id} hrefFor={(x) => `/models/${x}`} />
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-3xl font-bold mono">{m.id}</h1>
            <span className="text-2xl font-semibold">{m.name}</span>
            <Badge kind={m.status === "monitored" ? "completed" : "info"} label={m.status} />
          </div>
          <p className="text-muted mt-1">{m.type} · Tier <b className="text-text">{m.tier}</b> · Owner {m.owner || "—"} · {m.meta?.loc} lines of {m.language} · code <Hash v={m.code_hash} /></p>
        </div>
        <div className="flex gap-2">
          {parityRun && <Link href={`/models/${m.id}/parity`} className="btn">Parity certificate</Link>}
          {d.reports.length > 0 && <Link href={`/reports/${m.id}`} className="btn btn-primary">Validation report v{d.reports.at(-1).version}</Link>}
        </div>
      </div>
      <div className="flex gap-1 border-b border-line" role="tablist">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={clsx("px-4 py-2.5 text-[15px] font-semibold border-b-2 -mb-px transition", tab === t ? "border-teal text-text" : "border-transparent text-muted hover:text-text")}>
            {t}{t === "Findings" && d.findings.length ? <span className="ml-1.5 text-xs text-warn">{d.findings.length}</span> : null}
          </button>
        ))}
      </div>

      {tab === "Document" && (doc ? (
        <div className="grid grid-cols-1 xl:grid-cols-[1fr_400px] gap-5">
          <Panel title={<>ModelDoc <Tag tone="agent">drafted · {doc.llm_source}</Tag></>}>
            <div className="space-y-5">
              {Object.entries(doc.sections).map(([k, v]: any) => (
                <div key={k}>
                  <div className="font-semibold text-[#cfd6ff]">{SECTION_LABEL[k] || k}</div>
                  <p className="text-[15px] leading-relaxed text-[#d6daea] mt-1">{v}</p>
                </div>
              ))}
              {doc.variables?.length > 0 && (
                <div>
                  <div className="font-semibold text-[#cfd6ff] mb-2">Variable dictionary</div>
                  <table className="w-full text-sm">
                    <thead><tr className="text-left text-muted text-xs uppercase"><th className="py-1">Variable</th><th>Source column</th><th>Type</th><th>Missing</th><th>Description</th></tr></thead>
                    <tbody>{doc.variables.map((v: any) => (
                      <tr key={v.name} className="border-t border-line/60"><td className="py-1.5 mono">{v.name}</td><td className="mono text-xs text-muted">{v.source_column}</td><td>{v.type}</td><td className="num">{v.missing_pct}%</td><td className="text-muted">{v.description}</td></tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
            </div>
          </Panel>
          <div className="space-y-5">
            <Panel title="Documentation gaps">
              <ul className="space-y-2">{doc.gaps.map((g: string) => <li key={g} className="flex gap-2 text-[15px]"><span className="text-warn">▲</span>{g}</li>)}</ul>
            </Panel>
            <Panel title="Lineage">
              <div className="text-sm space-y-2">
                <div><span className="text-muted">Upstream:</span> {d.upstream.length ? d.upstream.map((u: string) => <Link key={u} className="mono text-teal mr-2" href={`/models/${u}`}>{u}</Link>) : "—"}</div>
                <div><span className="text-muted">Blast radius:</span> {d.blast_radius.length ? d.blast_radius.map((u: string) => <Link key={u} className="mono text-agent mr-2" href={`/models/${u}`}>{u}</Link>) : "—"}</div>
                <div><span className="text-muted">Reads:</span> {(doc.lineage.reads || []).map((r: string) => <div key={r} className="mono text-xs">{r}</div>)}</div>
                <div><span className="text-muted">Writes:</span> {(doc.lineage.writes || []).map((r: string) => <div key={r} className="mono text-xs">{r}</div>)}</div>
              </div>
            </Panel>
          </div>
        </div>
      ) : <Panel><Empty title="Not documented yet">The Documentation agent runs after Discovery.</Empty></Panel>)}

      {tab === "Redevelop" && (parityRun ? (
        <Panel title="R → Python redevelopment">
          <div className="grid md:grid-cols-3 gap-6 text-[15px]">
            <div><div className="text-muted text-sm">Max coefficient difference</div><div className="text-2xl mt-1"><Ev token={tk("coef_max_abs_diff")} /></div></div>
            <div><div className="text-muted text-sm">Max PD difference</div><div className="text-2xl mt-1"><Ev token={tk("score_max_abs_diff")} /></div></div>
            <div><div className="text-muted text-sm">Fuzz divergences</div><div className="text-2xl mt-1"><Ev token={tk("fuzz_divergences")} /> of <Ev token={tk("fuzz_rows")} /></div></div>
          </div>
          <p className="text-muted mt-5">Faithful translation first (quirks reproduced and flagged), proven by parity; fixes come after, as tracked findings. <Link href={`/models/${m.id}/parity`} className="text-teal hover:underline">Open the Parity Certificate →</Link></p>
        </Panel>
      ) : <Panel><Empty title="Redevelopment not run yet">Promote this model to Redevelop on the pipeline.</Empty></Panel>)}

      {tab === "Validate" && (
        <Panel title="Validation runs">
          {d.reports.length ? d.reports.map((r: any) => (
            <div key={r.id} className="flex items-center justify-between border-b border-line/60 py-3">
              <div><span className="font-semibold">Report v{r.version}</span> <span className="mono text-sm text-muted ml-2">{r.run_id}</span></div>
              <Link href={`/reports/${r.id}`} className="btn">Open →</Link>
            </div>
          )) : <Empty title="No validation report yet" />}
        </Panel>
      )}

      {tab === "Monitor" && (
        <Panel title="Monitoring batches" right={<Link href="/monitoring" className="text-teal text-sm hover:underline">Drift lab →</Link>}>
          {mon.data?.batches?.length ? mon.data.batches.map((b: any) => (
            <div key={b.id} className="flex items-center justify-between border-b border-line/60 py-2.5">
              <span>{b.label}</span><span className="mono">PSI {b.psi.toFixed(3)}</span><Badge kind={b.status} />
            </div>
          )) : <Empty title="No monitoring yet" />}
        </Panel>
      )}

      {tab === "Findings" && (
        <Panel title={`Findings (${d.findings.length})`}>
          {d.findings.length ? d.findings.map((f: any) => <FindingRow key={f.id} f={f} />) : <Empty title="No findings" />}
        </Panel>
      )}

      {tab === "Source" && (
        <Panel title={<>Legacy source · {m.meta?.path} <Tag tone="warn">untrusted · read as data</Tag></>}>
          <Source src={d.source} doc={doc} />
        </Panel>
      )}
    </div>
  );
}
