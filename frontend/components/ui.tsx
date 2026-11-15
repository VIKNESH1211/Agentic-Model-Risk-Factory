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
  info: { c: "text-muted border-line bg-slate-900/[.04]", icon: Info, label: "Info" },
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
  queued: { c: "text-muted border-line bg-slate-900/[.04]", icon: CircleDashed, label: "Queued" },
  "n/a": { c: "text-faint border-line bg-slate-900/[.02]", icon: CircleDashed, label: "n/a" },
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
  intake: "text-info", discovery: "text-info", documentation: "text-teal", planner: "text-teal", redevelopment: "text-agent", validator: "text-pass",
  redteam: "text-fail", report: "text-warn", monitor: "text-info", guardrail: "text-fail", orchestrator: "text-muted",
  benchmark: "text-agent", autopilot: "text-teal", governance: "text-teal", attacker: "text-fail", human: "text-text",
};

// ====================================================================== v3 building blocks
export function PageHeader({ title, sub, actions, crumbs }: { title: React.ReactNode; sub?: React.ReactNode; actions?: React.ReactNode; crumbs?: { href?: string; label: string }[] }) {
  return (
    <div className="flex items-end justify-between gap-4 flex-wrap">
      <div className="min-w-0">
        {crumbs && (
          <div className="flex items-center gap-1.5 text-xs text-muted mb-1">
            {crumbs.map((c, i) => (
              <span key={i} className="flex items-center gap-1.5">
                {i > 0 && <span className="text-faint">/</span>}
                {c.href ? <a href={c.href} className="hover:text-text">{c.label}</a> : <span className="text-text">{c.label}</span>}
              </span>
            ))}
          </div>
        )}
        <h1 className="text-[28px] font-bold tracking-tight leading-tight">{title}</h1>
        {sub && <p className="text-muted mt-1 max-w-3xl">{sub}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange, className }: {
  tabs: { id: T; label: React.ReactNode; badge?: React.ReactNode }[]; value: T; onChange: (v: T) => void; className?: string;
}) {
  return (
    <div role="tablist" className={clsx("flex items-center gap-1 border-b border-line overflow-x-auto scroll-thin", className)}>
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={clsx("relative px-3.5 py-2.5 text-[14.5px] font-medium whitespace-nowrap transition flex items-center gap-2",
            value === t.id ? "text-text" : "text-muted hover:text-text")}>
          {t.label}{t.badge}
          {value === t.id && <motion.span layoutId="tab-underline" className="absolute left-2 right-2 -bottom-px h-[2px] rounded bg-teal" />}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, hint, children, className }: { label: string; hint?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <label className={clsx("flex flex-col gap-1.5", className)}>
      <span className="text-xs font-semibold uppercase tracking-[.1em] text-muted">{label}</span>
      {children}
      {hint && <span className="text-xs text-faint">{hint}</span>}
    </label>
  );
}

export const inputCls = "w-full rounded-lg border border-line bg-slate-50 px-3 py-2 text-[14.5px] outline-none focus:border-teal focus:ring-2 focus:ring-teal/20 transition placeholder:text-faint";

export function CodeBlock({ code, lang, maxH = 520, lineNo = true, highlight }: { code: string; lang?: string; maxH?: number; lineNo?: boolean; highlight?: number[] }) {
  const lines = (code || "").split("\n");
  const hl = new Set(highlight || []);
  return (
    <div className="rounded-xl border border-line bg-[#fbfcfe] overflow-auto scroll-thin" style={{ maxHeight: maxH }}>
      {lang && <div className="sticky top-0 z-10 flex justify-between px-3 py-1.5 text-[11px] uppercase tracking-widest text-faint border-b border-line bg-[#fbfcfe]">
        <span>{lang}</span>
        <button className="hover:text-text" onClick={() => navigator.clipboard?.writeText(code)}>copy</button>
      </div>}
      <pre className="mono text-[12.5px] leading-[1.65] py-2">
        {lines.map((l, i) => (
          <div key={i} className={clsx("flex px-3", hl.has(i + 1) && "bg-warn/10 border-l-2 border-warn")}>
            {lineNo && <span className="select-none w-10 shrink-0 text-right pr-3 text-faint">{i + 1}</span>}
            <span className="whitespace-pre text-slate-700">{l || " "}</span>
          </div>
        ))}
      </pre>
    </div>
  );
}

export function JsonView({ value, className }: { value: any; className?: string }) {
  const txt = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return <pre className={clsx("mono text-[12px] leading-relaxed whitespace-pre-wrap break-words rounded-lg bg-slate-50 border border-line p-3 text-slate-700", className)}>{txt}</pre>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("rounded-lg bg-slate-900/[.05] animate-pulse", className)} />;
}

export function Stat({ label, value, sub, tone, icon: Icon }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: string; icon?: any }) {
  return (
    <div className="panel px-4 py-3.5 flex items-start gap-3">
      {Icon && <div className={clsx("mt-0.5 rounded-lg p-2 bg-slate-900/[.04]", tone || "text-teal")}><Icon size={18} /></div>}
      <div className="min-w-0">
        <div className="text-[11px] uppercase tracking-[.14em] text-muted font-semibold">{label}</div>
        <div className={clsx("text-2xl font-bold num leading-tight mt-0.5", tone)}>{value}</div>
        {sub && <div className="text-xs text-muted mt-0.5 truncate">{sub}</div>}
      </div>
    </div>
  );
}

export function Dot({ tone = "muted", pulse }: { tone?: "pass" | "warn" | "fail" | "agent" | "muted" | "teal" | "info"; pulse?: boolean }) {
  const c = { pass: "bg-pass", warn: "bg-warn", fail: "bg-fail", agent: "bg-agent", muted: "bg-faint", teal: "bg-teal", info: "bg-info" }[tone];
  return <span className={clsx("inline-block h-2 w-2 rounded-full shrink-0", c, pulse && "live-dot")} />;
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="mono text-[11px] rounded border border-line-strong bg-slate-900/[.04] px-1.5 py-px text-muted">{children}</kbd>;
}

export function ago(ts?: string | null) {
  if (!ts) return "—";
  const s = (Date.now() - new Date(ts).getTime()) / 1000;
  if (s < 60) return `${Math.max(0, Math.round(s))}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return new Date(ts).toLocaleDateString();
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: React.ReactNode; children: React.ReactNode; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[70] bg-slate-900/40 backdrop-blur-[2px] flex items-start justify-center pt-[8vh] px-4" onClick={onClose}>
      <motion.div initial={{ opacity: 0, y: 10, scale: .98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
        className={clsx("panel w-full max-h-[84vh] flex flex-col", wide ? "max-w-5xl" : "max-w-2xl")} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-line">
          <div className="font-semibold">{title}</div>
          <button onClick={onClose} className="text-muted hover:text-text" aria-label="Close">✕</button>
        </div>
        <div className="overflow-y-auto scroll-thin p-5">{children}</div>
      </motion.div>
    </div>
  );
}

export const AGENT_LABEL: Record<string, string> = {
  intake: "Intake", documentation: "Documentation", planner: "Planner", redevelopment: "Redevelopment", validator: "Validator",
  report: "Report writer", monitor: "Monitor", orchestrator: "Orchestrator", guardrail: "Guardrail", human: "Human", system: "System",
  autopilot: "Autopilot", governance: "Governance", attacker: "Attacker",
};
