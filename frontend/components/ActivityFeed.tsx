"use client";
import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useFactory } from "@/lib/store";
import { AGENT_COLOR, AGENT_LABEL } from "./ui";

/** Live, log-style feed of factory events (SSE). */
const TYPE: Record<string, { tag: string; c: string }> = {
  tool_call: { tag: "CALL", c: "text-agent" }, tool_result: { tag: "RESULT", c: "text-info" }, finding: { tag: "FINDING", c: "text-warn" },
  gate_requested: { tag: "GATE", c: "text-warn" }, gate_decided: { tag: "DECIDED", c: "text-muted" }, promotion: { tag: "PROMOTED", c: "text-pass" },
  alert: { tag: "ALERT", c: "text-fail" }, security: { tag: "SECURITY", c: "text-fail" }, stage_started: { tag: "STAGE", c: "text-teal" },
  stage_completed: { tag: "DONE", c: "text-pass" }, run_started: { tag: "RUN", c: "text-teal" }, run_completed: { tag: "RUN", c: "text-pass" },
  agent_step: { tag: "STEP", c: "text-muted" }, traffic: { tag: "TRAFFIC", c: "text-info" }, monitor: { tag: "MONITOR", c: "text-info" },
  info: { tag: "INFO", c: "text-muted" }, metric: { tag: "METRIC", c: "text-muted" },
};

export function ActivityFeed({ filter, height = 380, hideTypes = ["metric", "ledger_append", "agent_step"] }: {
  filter?: (e: any) => boolean; height?: number; hideTypes?: string[];
}) {
  const events = useFactory((s) => s.events);
  const list = events.filter((e) => !hideTypes.includes(e.type) && (!filter || filter(e))).slice(-120).reverse();
  return (
    <div className="overflow-y-auto scroll-thin pr-1 rounded-lg bg-[#fbfcfe] border border-line" style={{ height }} role="log" aria-label="Live agent activity">
      {list.length === 0 && <div className="text-muted text-sm py-10 text-center">Waiting for activity…</div>}
      <AnimatePresence initial={false}>
        {list.map((e) => {
          const t = TYPE[e.type] || { tag: e.type.toUpperCase(), c: "text-muted" };
          const href = e.run_id ? `/agents?run=${e.run_id}` : undefined;
          return (
            <motion.div key={e.id} initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
              className={clsx("grid grid-cols-[62px_70px_1fr] gap-2 px-2.5 py-[5px] text-[13px] border-b border-slate-900/[.03]",
                (e.type === "alert" || e.type === "security") && "bg-fail/[.06]")}>
              <span className="mono text-[11.5px] text-faint pt-px">{new Date(e.ts).toLocaleTimeString([], { hour12: false })}</span>
              <span className={clsx("mono text-[11px] font-bold pt-px", t.c)}>{t.tag}</span>
              <span className="min-w-0 leading-snug">
                {e.model_id && <Link href={`/models/${e.model_id}`} className="mono text-[12px] text-teal mr-1.5 hover:underline">{e.model_id}</Link>}
                {e.agent && <span className={clsx("font-semibold mr-1.5", AGENT_COLOR[e.agent] || "text-muted")}>{AGENT_LABEL[e.agent] || e.agent}</span>}
                {href ? <Link href={href} className="text-slate-700 hover:text-text">{e.summary}</Link> : <span className="text-slate-700">{e.summary}</span>}
              </span>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
