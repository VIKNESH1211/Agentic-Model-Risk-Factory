"use client";
import clsx from "clsx";
import { animate, motion, useMotionValue, useTransform } from "framer-motion";
import { AlertTriangle, CheckCircle2, CircleDashed, Info, Loader2, PauseCircle, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

export function Panel({ title, right, className, children, pad = true }: {
  title?: React.ReactNode; right?: React.ReactNode; className?: string; children: React.ReactNode; pad?: boolean;
}) {
  return (
    <section className={clsx("panel", className)}>
      {(title || right) && (
        <header className="flex items-center justify-between gap-3 px-5 pt-4 pb-2">
          <div className="panel-title">{title}</div>
          <div>{right}</div>
        </header>
      )}
      <div className={clsx(pad && "px-5 pb-5", !title && pad && "pt-5")}>{children}</div>
    </section>
  );
}

const SEV: Record<string, { c: string; icon: any; label: string }> = {
  high: { c: "text-fail border-fail/40 bg-fail/10", icon: XCircle, label: "High" },
  medium: { c: "text-warn border-warn/40 bg-warn/10", icon: AlertTriangle, label: "Medium" },
  low: { c: "text-info border-info/40 bg-info/10", icon: Info, label: "Low" },
  info: { c: "text-muted border-line bg-white/5", icon: Info, label: "Info" },
  pass: { c: "text-pass border-pass/40 bg-pass/10", icon: CheckCircle2, label: "Pass" },
  PASS: { c: "text-pass border-pass/40 bg-pass/10", icon: CheckCircle2, label: "PASS" },
  green: { c: "text-pass border-pass/40 bg-pass/10", icon: CheckCircle2, label: "Green" },
  completed: { c: "text-pass border-pass/40 bg-pass/10", icon: CheckCircle2, label: "Completed" },
  approved: { c: "text-pass border-pass/40 bg-pass/10", icon: CheckCircle2, label: "Approved" },
  warn: { c: "text-warn border-warn/40 bg-warn/10", icon: AlertTriangle, label: "Warn" },
  amber: { c: "text-warn border-warn/40 bg-warn/10", icon: AlertTriangle, label: "Amber" },
  waiting_gate: { c: "text-warn border-warn/40 bg-warn/10", icon: PauseCircle, label: "Awaiting approval" },
  pending: { c: "text-warn border-warn/40 bg-warn/10", icon: PauseCircle, label: "Pending" },
  changes_requested: { c: "text-warn border-warn/40 bg-warn/10", icon: AlertTriangle, label: "Changes requested" },
  fail: { c: "text-fail border-fail/40 bg-fail/10", icon: XCircle, label: "Fail" },
  FAIL: { c: "text-fail border-fail/40 bg-fail/10", icon: XCircle, label: "FAIL" },
  red: { c: "text-fail border-fail/40 bg-fail/10", icon: XCircle, label: "Red" },
  failed: { c: "text-fail border-fail/40 bg-fail/10", icon: XCircle, label: "Failed" },
  rejected: { c: "text-fail border-fail/40 bg-fail/10", icon: XCircle, label: "Rejected" },
  running: { c: "text-agent border-agent/40 bg-agent/10", icon: Loader2, label: "Running" },
  queued: { c: "text-muted border-line bg-white/5", icon: CircleDashed, label: "Queued" },
  "n/a": { c: "text-faint border-line bg-white/[.02]", icon: CircleDashed, label: "n/a" },
};

export function Badge({ kind, label, className }: { kind: string; label?: string; className?: string }) {
  const s = SEV[kind] || SEV.info;
  const Icon = s.icon;
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-semibold", s.c, className)}>
      <Icon size={13} className={kind === "running" ? "animate-spin" : ""} aria-hidden />
      {label ?? s.label}
    </span>
  );
}

export function CountUp({ value, decimals = 0, prefix = "", suffix = "", className }: {
  value: number; decimals?: number; prefix?: string; suffix?: string; className?: string;
}) {
  const mv = useMotionValue(0);
  const txt = useTransform(mv, (v) => `${prefix}${v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}${suffix}`);
  useEffect(() => {
    const c = animate(mv, value, { duration: 1.1, ease: "easeOut" });
    return () => c.stop();
  }, [value, mv]);
  return <motion.span className={clsx("num", className)}>{txt}</motion.span>;
}

export function Kpi({ label, children, sub, tone }: { label: string; children: React.ReactNode; sub?: React.ReactNode; tone?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="text-xs uppercase tracking-[.14em] text-muted font-semibold">{label}</div>
      <div className={clsx("text-3xl font-bold num", tone)}>{children}</div>
      {sub && <div className="text-sm text-muted">{sub}</div>}
    </div>
  );
}

export function Hash({ v, n = 10 }: { v?: string; n?: number }) {
  if (!v) return <span className="text-faint">—</span>;
  return <span className="mono text-[13px] text-agent/90" title={v}>{v.slice(0, n)}…{v.slice(-4)}</span>;
}

export function Empty({ title, children, action }: { title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center text-center gap-3 py-16 px-6">
      <CircleDashed className="text-faint" size={36} aria-hidden />
      <div className="text-lg font-semibold">{title}</div>
      {children && <div className="text-muted max-w-xl">{children}</div>}
      {action}
    </div>
  );
}

export function Tag({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "agent" | "teal" | "warn" }) {
  const c = { muted: "text-muted border-line", agent: "text-agent border-agent/40", teal: "text-teal border-teal/40", warn: "text-warn border-warn/40" }[tone];
  return <span className={clsx("inline-flex rounded border px-1.5 py-px text-[11px] font-semibold uppercase tracking-wider", c)}>{children}</span>;
}

export function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

export function fmtClock(s: number) {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = Math.floor(s % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}`;
}

export const AGENT_COLOR: Record<string, string> = {
  discovery: "text-info", documentation: "text-teal", redevelopment: "text-agent", validator: "text-pass",
  redteam: "text-fail", report: "text-warn", monitor: "text-info", guardrail: "text-fail", orchestrator: "text-muted",
  benchmark: "text-agent", autopilot: "text-teal", governance: "text-teal", attacker: "text-fail", human: "text-text",
};
