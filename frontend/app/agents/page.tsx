"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertTriangle, Brain, CheckCircle2, ChevronDown, ChevronRight, Lightbulb, ListChecks, Search, Wrench, XCircle } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { Badge, Empty, Panel, Tag } from "@/components/ui";
import { get } from "@/lib/api";

const KIND: Record<string, { icon: any; tone: string; label: string }> = {
  plan: { icon: ListChecks, tone: "text-agent", label: "Plan" },
  thought: { icon: Brain, tone: "text-agent", label: "Thought" },
  tool_call: { icon: Wrench, tone: "text-info", label: "Tool call" },
  tool_result: { icon: CheckCircle2, tone: "text-teal", label: "Result" },
  observation: { icon: Search, tone: "text-warn", label: "Observation" },
  decision: { icon: Lightbulb, tone: "text-pass", label: "Recommendation" },
  error: { icon: XCircle, tone: "text-fail", label: "Error" },
};
const STAGE_NAME: Record<string, string> = { discover: "Discover", document: "Document", redevelop: "Redevelop", validate: "Validate", report: "Report", monitor_setup: "Deploy & monitor" };

function Json({ v }: { v: any }) {
  return <pre className="mono text-[12px] leading-relaxed bg-black/30 border border-line rounded-md p-2.5 overflow-x-auto scroll-thin max-h-[320px] text-[#cbd3ff]">{typeof v === "string" ? v : JSON.stringify(v, null, 2)}</pre>;
}

function Step({ s, pair }: { s: any; pair?: any }) {
  const [open, setOpen] = useState(s.kind === "plan" || s.kind === "decision" || s.kind === "error");
  const k = KIND[s.kind] || KIND.thought;
  const Icon = k.icon;
  const c = s.content || {};
  if (s.kind === "tool_result") return null;  // rendered with its call
  const body = (() => {
    if (s.kind === "plan") return (
      <div className="space-y-2 text-[14px]">
        <ol className="list-decimal ml-5 space-y-0.5">{(c.steps || []).map((x: any, i: number) => <li key={i}><span className="mono text-info">{x.tool}</span> <span className="text-muted">— {x.why}</span></li>)}</ol>
        {Object.keys(c.menu_optional || {}).length > 0 && (
          <div className="flex flex-wrap gap-2 items-center"><span className="text-muted text-sm">Optional analyses:</span>
            {Object.keys(c.menu_optional).map((o) => <span key={o} className={clsx("rounded border px-2 py-0.5 text-xs font-semibold", (c.optional || []).includes(o) ? "border-pass/50 text-pass bg-pass/10" : "border-line text-faint line-through")}>{o}</span>)}
          </div>)}
        {c.rationale && <div className="text-muted text-sm italic">“{c.rationale}”</div>}
        <div className="text-xs text-faint">planner: {c.source}</div>
      </div>);
    if (s.kind === "decision") return (
      <div className="space-y-1.5 text-[14px]">
        <div>{c.summary}</div>
        <ul className="list-disc ml-5 text-muted">{(c.reasons || []).map((r: string) => <li key={r}>{r}</li>)}</ul>
        <div className="text-xs text-faint">reviewer: {c.source}</div>
      </div>);
    if (s.kind === "tool_call") return (
      <div className="grid md:grid-cols-2 gap-2">
        <div><div className="text-xs text-muted mb-1">arguments</div><Json v={c.args} /></div>
        <div><div className="text-xs text-muted mb-1">result {pair?.duration_ms != null && <span className="mono">· {pair.duration_ms} ms</span>}</div><Json v={pair?.content?.result ?? "…running"} /></div>
      </div>);
    return <Json v={c} />;
  })();
  return (
    <div className={clsx("relative pl-8 pb-3", s.kind === "decision" && "pt-1")}>
      <span className={clsx("absolute left-0 top-0.5 grid place-items-center h-6 w-6 rounded-full border border-line bg-ink-2", k.tone)}><Icon size={13} /></span>
      <button onClick={() => setOpen((o) => !o)} className="flex items-start gap-2 text-left w-full group">
        <span className={clsx("text-[11px] font-bold uppercase tracking-wider mt-0.5 w-[92px] shrink-0", k.tone)}>{k.label}</span>
        <span className={clsx("flex-1 text-[14.5px]", s.kind === "decision" && "font-semibold")}>
          {s.kind === "tool_call" && pair ? pair.title : s.title}
        </span>
        <span className="mono text-[11px] text-faint shrink-0">{new Date(s.ts).toLocaleTimeString([], { hour12: false })}</span>
        {open ? <ChevronDown size={15} className="text-muted" /> : <ChevronRight size={15} className="text-muted" />}
      </button>
      {open && <div className="mt-2 ml-[100px]">{body}</div>}
    </div>
  );
}

function Console() {
  const sp = useSearchParams();
  const router = useRouter();
  const runs = useQuery({ queryKey: ["agent-runs"], queryFn: () => get<any[]>("/api/agents/runs"), refetchInterval: 4000 });
  const [filter, setFilter] = useState("");
  const runId = sp.get("run") || runs.data?.[0]?.id;
  const steps = useQuery({ queryKey: ["agent-steps", runId], queryFn: () => get<any[]>(`/api/agents/steps?run_id=${runId}`), enabled: !!runId, refetchInterval: 1500 });
  const run = runs.data?.find((r) => r.id === runId);
  const grouped = useMemo(() => {
    const g: { stage: string; agent: string; items: any[] }[] = [];
    for (const s of steps.data || []) {
      const last = g.at(-1);
      if (!last || last.stage !== s.stage || (s.kind === "plan" && last.items.length)) g.push({ stage: s.stage, agent: s.agent, items: [s] });
      else last.items.push(s);
    }
    return g;
  }, [steps.data]);
  const results = useMemo(() => {
    const m: Record<number, any> = {};
    const all = steps.data || [];
    all.forEach((s, i) => { if (s.kind === "tool_call") { const r = all.slice(i + 1).find((x) => x.kind === "tool_result" && x.content?.tool === s.content?.tool); if (r) m[s.id] = r; } });
    return m;
  }, [steps.data]);
  useEffect(() => { if (!sp.get("run") && runs.data?.[0]) router.replace(`/agents?run=${runs.data[0].id}`); }, [runs.data]); // eslint-disable-line

  const list = (runs.data || []).filter((r) => !filter || r.model_id.toLowerCase().includes(filter.toLowerCase()) || r.kind.includes(filter));
  return (
    <div className="grid grid-cols-1 xl:grid-cols-[340px_1fr] gap-5 max-w-[1700px] mx-auto">
      <Panel title="Runs" pad={false}>
        <div className="px-4 pb-2"><input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by model or kind…" className="w-full rounded-md border border-line bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-teal" /></div>
        <div className="max-h-[calc(100vh-220px)] overflow-y-auto scroll-thin">
          {list.map((r) => (
            <button key={r.id} onClick={() => router.push(`/agents?run=${r.id}`)}
              className={clsx("w-full text-left px-4 py-2.5 border-t border-line/60 hover:bg-white/[.03]", r.id === runId && "bg-teal/[.08] border-l-2 border-l-teal")}>
              <div className="flex items-center justify-between"><span className="mono font-bold">{r.model_id}</span><Badge kind={r.status} /></div>
              <div className="text-xs text-muted mt-0.5"><span className="mono">{r.id}</span> · {r.kind} · {r.stage} · {r.steps} steps</div>
            </button>
          ))}
          {!list.length && <div className="p-6 text-muted text-sm">No runs yet.</div>}
        </div>
      </Panel>
      <Panel title={run ? <>Agent trace · <span className="mono normal-case">{run.model_id}</span> · {run.kind}</> : "Agent trace"}
        right={run && <span className="text-xs text-muted">plan → act → observe → recommend · every step is stored</span>}>
        {!runId ? <Empty title="No agent activity yet">Start the factory from the Pipeline page.</Empty> : (
          <div className="space-y-5">
            {grouped.map((g, gi) => (
              <section key={gi} className="rounded-xl border border-line p-4">
                <div className="flex items-center gap-2 mb-3">
                  <span className="font-bold tracking-[.14em] uppercase text-[13px]">{STAGE_NAME[g.stage] || g.stage}</span>
                  <Tag tone="agent">{g.agent} agent</Tag>
                  <span className="text-xs text-faint">{g.items.filter((x) => x.kind === "tool_call").length} tool calls</span>
                </div>
                <div className="border-l border-line/80 ml-3 pl-0">
                  {g.items.map((s) => <Step key={s.id} s={s} pair={results[s.id]} />)}
                </div>
              </section>
            ))}
            {run?.status === "running" && <div className="flex items-center gap-2 text-agent text-sm"><span className="h-2 w-2 rounded-full bg-agent live-dot" /> agent working…</div>}
            {run?.status === "waiting_gate" && <div className="flex items-center gap-2 text-warn text-sm"><AlertTriangle size={15} /> paused at a promotion gate — decide on the Pipeline or Approvals page.</div>}
          </div>
        )}
      </Panel>
    </div>
  );
}

export default function AgentsPage() {
  return <Suspense><Console /></Suspense>;
}
