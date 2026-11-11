"use client";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Ev } from "@/components/Evidence";
import { ModelPicker } from "@/components/ModelPicker";
import { Empty, Panel, Tag } from "@/components/ui";
import { get } from "@/lib/api";

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const q = useQuery({ queryKey: ["report", id], queryFn: () => get(`/api/reports/${id}`), retry: false });
  const diff = useQuery({ queryKey: ["report-diff", id], queryFn: () => get(`/api/reports/${id}/diff`), enabled: !!q.data });
  if (q.isError) return <div className="space-y-4 max-w-[1600px] mx-auto"><ModelPicker current={id} hrefFor={(m) => `/reports/${m}`} /><Panel><Empty title={`No validation report for ${id} yet`} action={<Link className="btn btn-primary" href="/">Open the pipeline →</Link>}>Promote the model to Validate; the report is drafted at the end of that stage.</Empty></Panel></div>;
  const d = q.data;
  if (!d) return <div className="text-muted">Loading…</div>;
  const toks = d.tokens as Record<string, any>;
  // tokens → markdown links the renderer turns into evidence pills
  const md = (d.markdown as string).replace(/\{\{(m:[^}]+)\}\}/g, (_: string, t: string) => `[${toks[t]?.display ?? "?"}](#ev:${encodeURIComponent(t)})`);
  const chk = d.report.checker;
  const isReval = d.run?.kind === "revalidation";

  return (
    <div className="space-y-4 max-w-[1600px] mx-auto">
    <ModelPicker current={d.report.model_id} hrefFor={(m) => `/reports/${m}`} />
    <div className="grid grid-cols-1 2xl:grid-cols-[1fr_400px] gap-5">
      <Panel pad={false}>
        <div className="flex items-center justify-between gap-3 px-8 pt-6 flex-wrap">
          <div className="flex items-center gap-2 flex-wrap">
            {d.versions.map((v: any) => (
              <Link key={v.id} href={`/reports/${v.id}`} className={`rounded-md px-2.5 py-1 text-sm font-semibold border ${v.id === d.report.id ? "border-teal text-teal bg-teal/10" : "border-line text-muted hover:text-text"}`}>v{v.version}</Link>
            ))}
            {isReval && <Tag tone="warn">auto re-validation</Tag>}
          </div>
          <div className={`flex items-center gap-2 text-sm font-semibold ${chk.ok ? "text-pass" : "text-fail"}`}>
            {chk.ok ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
            {chk.token_count} traceable numbers · {chk.violations.length} unsourced
          </div>
        </div>
        <article className="prose-report px-8 pb-10 pt-2">
          <ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={(u) => u}
            components={{
              a: ({ href, children }) => {
                if (href?.startsWith("#ev:")) {
                  const t = decodeURIComponent(href.slice(4));
                  return <Ev token={t} info={toks[t]} />;
                }
                return <a href={href} className="text-teal underline">{children}</a>;
              },
            }}>
            {md}
          </ReactMarkdown>
        </article>
      </Panel>
      <div className="space-y-5">
        <Panel title="How to read this report">
          <ul className="text-[15px] space-y-2 text-[#d6daea]">
            <li><span className="pill">0.612</span> Every figure is a pill: click it for the definition, run, data and code hashes, the function that computed it, and <b>Reproduce</b>.</li>
            <li>The language model drafted prose with tokens only; a checker rejects any raw number before the report is stored.</li>
            <li>Pass/fail comes from fixed thresholds, not the model.</li>
          </ul>
        </Panel>
        {diff.data?.rows?.length > 0 && (
          <Panel title={isReval ? "Change vs. baseline validation" : "Change vs. previous version"}>
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs uppercase text-muted"><th className="py-1.5">Metric</th><th>Before</th><th>After</th></tr></thead>
              <tbody>{diff.data.rows.map((r: any) => (
                <tr key={r.metric} className="border-t border-line/60">
                  <td className="py-2 mono text-xs">{r.metric}</td>
                  <td><Ev token={r.before_token} fallback={r.before_display} /></td>
                  <td><Ev token={r.after_token} fallback={r.after_display} /> <span className={r.delta > 0 ? "text-warn text-xs" : "text-info text-xs"}>{r.delta > 0 ? "▲" : r.delta < 0 ? "▼" : ""}</span></td>
                </tr>
              ))}</tbody>
            </table>
            {diff.data.new_findings?.length > 0 && (
              <div className="mt-3 text-sm"><div className="text-muted mb-1">New findings</div>{diff.data.new_findings.map((f: any) => <div key={f.id} className="text-warn">⚑ {f.code} {f.title}</div>)}</div>
            )}
          </Panel>
        )}
        <Panel title="Run">
          <div className="text-sm space-y-1">
            <div><span className="text-muted">Run</span> <span className="mono">{d.run?.id}</span> · {d.run?.kind}</div>
            <div><span className="text-muted">Status</span> {d.run?.status}</div>
            <div><span className="text-muted">Model</span> <Link className="mono text-teal" href={`/models/${d.report.model_id}`}>{d.report.model_id}</Link></div>
          </div>
        </Panel>
      </div>
    </div>
    </div>
  );
}
