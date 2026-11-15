"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowDownToLine, ChevronRight, Copy, Search } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { get, STAGE_LABEL } from "@/lib/api";
import { toast } from "@/lib/store";
import { AGENT_COLOR, AGENT_LABEL, JsonView } from "./ui";

/** Structured, terminal-style log of one run: every plan, thought, tool call (with arguments), result, error,
 *  finding and decision, grouped by stage. Polls incrementally while the run is live. */
const KIND: Record<string, { icon: string; label: string; c: string }> = {
  plan: { icon: "◆", label: "PLAN", c: "text-teal" },
  thought: { icon: "…", label: "THINK", c: "text-muted" },
  tool_call: { icon: "→", label: "CALL", c: "text-agent" },
  tool_result: { icon: "←", label: "RESULT", c: "text-info" },
  observation: { icon: "•", label: "OBSERVE", c: "text-warn" },
  decision: { icon: "■", label: "DECIDE", c: "text-pass" },
  error: { icon: "✗", label: "ERROR", c: "text-fail" },
};
const FILTERS = [
  { id: "all", label: "All" }, { id: "tools", label: "Tools", kinds: ["tool_call", "tool_result"] },
  { id: "thoughts", label: "Reasoning", kinds: ["plan", "thought", "decision"] }, { id: "findings", label: "Findings & observations", kinds: ["observation"] },
  { id: "errors", label: "Errors", kinds: ["error"] },
] as const;

function time(ts: string) {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
}

function Row({ s, open, toggle }: { s: any; open: boolean; toggle: () => void }) {
  const k = KIND[s.kind] || { icon: "·", label: s.kind.toUpperCase(), c: "text-muted" };
  const hasBody = s.content && Object.keys(s.content).length > 0 && s.kind !== "thought";
  const isDecision = s.kind === "decision";
  const rec = s.content?.recommendation;
  return (
    <div className={clsx("group border-l-2 pl-2", s.kind === "error" ? "border-fail/70 bg-fail/[.04]" : isDecision ? "border-pass/60 bg-pass/[.04]" :
      s.kind === "tool_call" ? "border-agent/40" : "border-transparent")}>
      <button onClick={hasBody ? toggle : undefined} className={clsx("w-full text-left grid grid-cols-[86px_74px_118px_1fr_auto] gap-2 items-baseline py-[3px] mono text-[12.5px]",
        hasBody && "cursor-pointer hover:bg-slate-900/[.03]")}>
        <span className="text-faint">{time(s.ts)}</span>
        <span className={clsx("font-bold", k.c)}>{k.icon} {k.label}</span>
        <span className={clsx("truncate", AGENT_COLOR[s.agent] || "text-muted")}>{AGENT_LABEL[s.agent] || s.agent}</span>
        <span className={clsx("min-w-0 font-sans text-[13.5px]", s.kind === "thought" ? "italic text-slate-500" : "text-text",
          isDecision && (rec === "hold" ? "text-warn font-semibold" : "text-pass font-semibold"))}>
          {hasBody && <ChevronRight size={12} className={clsx("inline mr-1 transition text-faint", open && "rotate-90")} />}
          {s.title}
        </span>
        <span className="text-faint text-[11px] pr-2">{s.duration_ms != null ? `${s.duration_ms}ms` : ""}</span>
      </button>
      {open && hasBody && (
        <div className="ml-[290px] mr-2 mb-2 space-y-2">
          {isDecision && s.content?.reasons?.length > 0 && (
            <ul className="text-[13px] list-disc ml-5 text-muted">{s.content.reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul>
          )}
          {s.content?.args && Object.keys(s.content.args).length > 0 && <div><div className="text-[11px] uppercase tracking-widest text-faint mb-1">arguments</div><JsonView value={s.content.args} /></div>}
          {s.content?.result !== undefined && <div><div className="text-[11px] uppercase tracking-widest text-faint mb-1">result</div><JsonView value={s.content.result} className="max-h-80 overflow-auto scroll-thin" /></div>}
          {s.content?.error && <JsonView value={s.content.error} className="text-fail" />}
          {!s.content?.args && s.content?.result === undefined && !s.content?.error && <JsonView value={s.content} className="max-h-80 overflow-auto scroll-thin" />}
        </div>
      )}
    </div>
  );
}

export function AgentTrace({ runId, live, height = 640 }: { runId: string; live?: boolean; height?: number | string }) {
  const [steps, setSteps] = useState<any[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [q, setQ] = useState("");
  const [follow, setFollow] = useState(true);
  const [open, setOpen] = useState<Set<number>>(new Set());
  const box = useRef<HTMLDivElement>(null);
  const last = steps.at(-1)?.id || 0;
  useEffect(() => { setSteps([]); setOpen(new Set()); }, [runId]);
  useQuery({
    queryKey: ["steps", runId, last], refetchInterval: live ? 1500 : false,
    queryFn: async () => {
      const fresh = await get<any[]>(`/api/agents/steps?run_id=${runId}&after=${last}`);
      if (fresh.length) setSteps((s) => [...s, ...fresh.filter((f) => !s.some((x) => x.id === f.id))]);
      return fresh.length;
    },
  });
  const calls = useQuery({ queryKey: ["llm-calls", runId, steps.length], queryFn: () => get<any[]>(`/api/agents/llm-calls?run_id=${runId}`) });
  const kinds = (FILTERS.find((f) => f.id === filter) as any)?.kinds as string[] | undefined;
  const shown = useMemo(() => steps.filter((s) => (!kinds || kinds.includes(s.kind)) &&
    (!q || `${s.title} ${JSON.stringify(s.content)}`.toLowerCase().includes(q.toLowerCase()))), [steps, kinds, q]);
  useEffect(() => { if (follow && box.current) box.current.scrollTop = box.current.scrollHeight; }, [shown.length, follow]);
  const n = (k: string) => steps.filter((s) => s.kind === k).length;
  const cost = (calls.data || []).reduce((a, c) => a + (c.cost || 0), 0);
  const copy = () => {
    navigator.clipboard?.writeText(steps.map((s) => `${time(s.ts)}  ${(KIND[s.kind]?.label || s.kind).padEnd(7)}  ${(s.agent || "").padEnd(14)} ${s.title}`).join("\n"));
    toast({ kind: "success", text: `Copied ${steps.length} log lines` });
  };
  let lastStage = "";
  return (
    <div className="flex flex-col rounded-xl border border-line bg-[#fbfcfe] overflow-hidden" style={{ height }}>
      <div className="flex items-center gap-2 flex-wrap px-3 py-2 border-b border-line bg-slate-900/[.02]">
        <div className="flex items-center gap-1 rounded-lg bg-slate-50 p-0.5">
          {FILTERS.map((f) => (
            <button key={f.id} onClick={() => setFilter(f.id)}
              className={clsx("px-2.5 py-1 rounded-md text-[12.5px] font-medium", filter === f.id ? "bg-slate-900/[.06] text-text" : "text-muted hover:text-text")}>
              {f.label}{f.id === "errors" && n("error") > 0 && <span className="ml-1 text-fail">{n("error")}</span>}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5 rounded-lg border border-line bg-slate-50 px-2 py-1 text-sm">
          <Search size={13} className="text-faint" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="filter log…" className="bg-transparent outline-none w-40 text-[13px]" />
        </div>
        <div className="flex-1" />
        <span className="mono text-[11.5px] text-muted">{steps.length} steps · {n("tool_call")} tool calls · {(calls.data || []).length} LLM calls · ${cost.toFixed(4)}</span>
        <button onClick={() => setFollow((v) => !v)} className={clsx("btn !py-1 !px-2 text-xs", follow && "glow-teal")} title="Follow the newest step"><ArrowDownToLine size={13} /> follow</button>
        <button onClick={copy} className="btn !py-1 !px-2 text-xs" title="Copy as text"><Copy size={13} /></button>
      </div>
      <div ref={box} className="flex-1 overflow-y-auto scroll-thin px-2 py-1" onWheel={() => follow && box.current && box.current.scrollTop + box.current.clientHeight < box.current.scrollHeight - 40 && setFollow(false)}>
        {!steps.length && <div className="text-center text-muted py-16 text-sm">{live ? "Waiting for the agent's first step…" : "No steps recorded for this run."}</div>}
        {shown.map((s) => {
          const header = s.stage !== lastStage;
          lastStage = s.stage;
          return (
            <Fragment key={s.id}>
              {header && (
                <div className="sticky top-0 z-10 -mx-2 px-3 py-1.5 mt-1 bg-slate-100/95 backdrop-blur border-y border-line text-[11px] uppercase tracking-[.18em] text-muted font-semibold flex items-center gap-2">
                  <span className="text-teal">▸</span> {STAGE_LABEL[s.stage] || s.stage}
                </div>
              )}
              <Row s={s} open={open.has(s.id)} toggle={() => setOpen((o) => { const x = new Set(o); x.has(s.id) ? x.delete(s.id) : x.add(s.id); return x; })} />
            </Fragment>
          );
        })}
        {live && steps.length > 0 && <div className="mono text-[12px] text-agent py-2 pl-2 live-dot">▍ agent working…</div>}
      </div>
    </div>
  );
}
