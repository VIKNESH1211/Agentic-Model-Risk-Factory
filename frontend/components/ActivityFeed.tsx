"use client";
import clsx from "clsx";
import { AnimatePresence, motion } from "framer-motion";
import { useFactory } from "@/lib/store";
import { AGENT_COLOR } from "./ui";

const ICON: Record<string, string> = {
  tool_call: "›", tool_result: "✓", finding: "⚑", gate_requested: "⏸", gate_decided: "✔", alert: "⚠", security: "🛡",
  ledger_append: "⛓", metric: "∑", stage_started: "▶", stage_completed: "■", run_started: "◉", run_completed: "◎",
  benchmark: "◆", monitor: "≈", info: "·", agent_step: "◇", traffic: "⇄", promotion: "⇪",
};

export function ActivityFeed({ filter, height = 380, hideTypes = ["metric", "ledger_append"] }: {
  filter?: (e: any) => boolean; height?: number; hideTypes?: string[];
}) {
  const events = useFactory((s) => s.events);
  const list = events.filter((e) => !hideTypes.includes(e.type) && (!filter || filter(e))).slice(-80).reverse();
  return (
    <div className="overflow-y-auto scroll-thin pr-1" style={{ height }} role="log" aria-label="Live agent activity">
      {list.length === 0 && <div className="text-muted text-sm py-8 text-center">Waiting for agent activity…</div>}
      <AnimatePresence initial={false}>
        {list.map((e) => (
          <motion.div key={e.id} layout initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}
            className={clsx("grid grid-cols-[64px_18px_1fr] gap-2 py-1.5 text-[14px] border-b border-white/[.03]",
              e.type === "alert" && "text-fail", e.type === "security" && "text-fail", e.type === "finding" && "text-warn")}>
            <span className="mono text-[12px] text-faint pt-0.5">{new Date(e.ts).toLocaleTimeString([], { hour12: false })}</span>
            <span className={clsx("text-center", e.type === "tool_call" && "text-agent")}>{ICON[e.type] ?? "·"}</span>
            <span className="min-w-0">
              {e.agent && <span className={clsx("font-semibold mr-1.5", AGENT_COLOR[e.agent] || "text-muted")}>{e.agent}</span>}
              {e.model_id && <span className="mono text-[12px] text-muted mr-1.5">{e.model_id}</span>}
              <span className={clsx(e.type === "tool_result" && "text-muted")}>{e.summary}</span>
            </span>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
