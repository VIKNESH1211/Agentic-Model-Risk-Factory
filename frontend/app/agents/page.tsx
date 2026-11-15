"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { AgentTrace } from "@/components/AgentTrace";
import { Badge, Empty, PageHeader, Panel, Tag, ago, inputCls } from "@/components/ui";
import { get, STAGE_LABEL } from "@/lib/api";

function Console() {
  const sp = useSearchParams();
  const router = useRouter();
  const runs = useQuery({ queryKey: ["agent-runs"], queryFn: () => get<any[]>("/api/agents/runs"), refetchInterval: 3000 });
  const [model, setModel] = useState("all");
  const [status, setStatus] = useState("all");
  const list = (runs.data || []).filter((r) => (model === "all" || r.model_id === model) && (status === "all" || r.status === status));
  const sel = sp.get("run") || list[0]?.id;
  const run = (runs.data || []).find((r) => r.id === sel);
  const models = useMemo(() => Array.from(new Set((runs.data || []).map((r) => r.model_id))).sort(), [runs.data]);
  return (
    <div className="space-y-5 max-w-[1800px] mx-auto">
      <PageHeader title="Agent console"
        sub="Every run as a structured log: the agent's goal, each thought, every tool call with its exact arguments and result, errors it recovered from, findings, and its recommendation. Click a line to expand it." />
      {runs.isSuccess && !runs.data.length ? (
        <Panel><Empty title="No agent runs yet" action={<Link href="/" className="btn btn-primary">Go to the factory floor</Link>}>Start a model; its agents' work appears here live.</Empty></Panel>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-[330px_1fr] gap-5">
          <div className="space-y-3">
            <div className="flex gap-2">
              <select className={clsx(inputCls, "!py-1.5 text-sm")} value={model} onChange={(e) => setModel(e.target.value)}><option value="all">All models</option>{models.map((m) => <option key={m}>{m}</option>)}</select>
              <select className={clsx(inputCls, "!py-1.5 text-sm")} value={status} onChange={(e) => setStatus(e.target.value)}>{["all", "running", "waiting_gate", "completed", "failed", "rejected"].map((s) => <option key={s}>{s}</option>)}</select>
            </div>
            <div className="space-y-1.5 max-h-[calc(100vh-260px)] overflow-y-auto scroll-thin pr-1">
              {list.map((r) => (
                <button key={r.id} onClick={() => router.replace(`/agents?run=${r.id}`)}
                  className={clsx("w-full text-left rounded-xl border px-3 py-2.5 transition", r.id === sel ? "border-teal/60 bg-teal/[.06]" : "border-line hover:bg-slate-900/[.03]",
                    r.status === "running" && "agent-scan")}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="mono font-bold text-[14px]">{r.model_id}</span><Badge kind={r.status} />
                  </div>
                  <div className="text-xs text-muted mt-1 flex items-center gap-1.5 flex-wrap">
                    <span className="mono">{r.id}</span> · <Tag tone={r.kind === "revalidation" ? "warn" : "muted"}>{r.kind}</Tag> · {STAGE_LABEL[r.stage] || r.stage}
                  </div>
                  <div className="text-[11.5px] text-faint mt-0.5">{r.steps} steps · {r.llm_calls} LLM calls · ${r.llm_cost.toFixed(4)} · {ago(r.started_at)}</div>
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-3 min-w-0">
            {run && (
              <div className="flex items-center gap-3 flex-wrap">
                <Link href={`/models/${run.model_id}`} className="mono text-lg font-bold hover:text-teal">{run.model_id}</Link>
                <span className="mono text-muted">{run.id}</span><Badge kind={run.status} />
                <div className="flex items-center gap-1 flex-wrap">
                  {(run.state?.timeline || []).map((t: any, i: number) => (
                    <span key={i} className={clsx("rounded-md border px-2 py-0.5 text-[11.5px]", t.end ? "border-teal/40 text-teal" : "border-agent text-agent")}>
                      {STAGE_LABEL[t.stage] || t.stage}{t.end ? ` · ${Math.round((+new Date(t.end) - +new Date(t.start)) / 1000)}s` : " …"}
                    </span>
                  ))}
                </div>
                {Object.entries(run.state?.conclusions || {}).slice(-1).map(([st, c]: any) => (
                  <span key={st} className={clsx("text-sm font-semibold", c.recommendation === "promote" ? "text-pass" : "text-warn")}>last recommendation: {c.recommendation?.toUpperCase()}</span>
                ))}
              </div>
            )}
            {sel ? <AgentTrace runId={sel} live={run && ["running", "queued"].includes(run.status)} height="calc(100vh - 230px)" /> : null}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<div className="text-muted">Loading…</div>}><Console /></Suspense>;
}
