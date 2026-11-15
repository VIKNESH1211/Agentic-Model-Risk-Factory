"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Command } from "cmdk";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity, Bell, Bot, BrainCircuit, ChevronDown, ClipboardCheck, Cpu, Database, Factory, FileText, Layers, Library,
  PackagePlus, RotateCcw, Search, ShieldCheck, Sprout, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { get, post } from "@/lib/api";
import { toast, useFactory } from "@/lib/store";
import { useEventStream } from "@/lib/useEventStream";
import { EvidenceDrawer } from "./Evidence";
import { Dot, Kbd } from "./ui";

const NAV = [
  { group: "Factory", items: [
    { href: "/", label: "Pipeline", icon: Factory },
    { href: "/approvals", label: "Approvals", icon: ClipboardCheck, badge: "gates" },
    { href: "/agents", label: "Agent console", icon: BrainCircuit },
  ] },
  { group: "Estate", items: [
    { href: "/models", label: "Models", icon: Layers },
    { href: "/onboard", label: "Onboard a model", icon: PackagePlus },
    { href: "/data-room", label: "Data room", icon: Database },
  ] },
  { group: "Assurance", items: [
    { href: "/monitoring", label: "Live monitoring", icon: Activity, badge: "alerts" },
    { href: "/reports", label: "Validation reports", icon: FileText },
    { href: "/governance", label: "Governance & ledger", icon: ShieldCheck },
  ] },
  { group: "Platform", items: [{ href: "/library", label: "Library", icon: Library }] },
];
const ALL = NAV.flatMap((g) => g.items);

function isActive(path: string, href: string) {
  return href === "/" ? path === "/" : path === href || path.startsWith(href + "/") || (href === "/reports" && path.startsWith("/reports"));
}

function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: () => get("/api/health"), refetchInterval: 15000 });
}

function StatusChips() {
  const h = useHealth().data;
  const llm = h?.llm;
  return (
    <div className="hidden xl:flex items-center gap-2 text-[12.5px]">
      <span className={clsx("flex items-center gap-1.5 rounded-lg border px-2.5 py-1", llm?.live ? "border-line" : "border-warn/40 text-warn")}
        title={llm?.last_error || `${llm?.provider} · ${llm?.mode}`}>
        <Cpu size={13} /> <span className="mono">{llm ? `${llm.provider}:${llm.model}` : "…"}</span>
        <Dot tone={!llm ? "muted" : llm.last_error ? "warn" : llm.live ? "pass" : "warn"} />
      </span>
      <span className="flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1" title="Legacy R runs unmodified in a no-network Docker sandbox">
        R sandbox <Dot tone={h ? (h.sandbox_docker ? "pass" : "warn") : "muted"} />
      </span>
      <span className="flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1" title="Hash-chained audit ledger">
        Ledger <Dot tone={h ? (h.ledger ? "pass" : "fail") : "muted"} />
      </span>
    </div>
  );
}

function DemoMenu() {
  const qc = useQueryClient();
  const router = useRouter();
  const clear = useFactory((s) => s.clear);
  const [open, setOpen] = useState(false);
  const [armed, setArmed] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const state = useQuery({ queryKey: ["demo-state"], queryFn: () => get("/api/demo/state"), refetchInterval: 4000 });
  const done = (msg: string) => () => { qc.invalidateQueries(); toast({ kind: "success", text: msg }); setOpen(false); setArmed(null); };
  const auto = useMutation({ mutationFn: () => post("/api/demo/autopilot"), onSuccess: done("Autopilot started — the demo delegate approves each gate") });
  const seed = useMutation({ mutationFn: () => post("/api/demo/seed"), onSuccess: done("Test estate onboarded from legacy_models/") });
  const reset = useMutation({ mutationFn: (scope: string) => post("/api/demo/reset", { scope, seed: scope === "all" }),
    onSuccess: (_r, scope) => { clear(); done(scope === "all" ? "Factory reset: fresh database, test estate re-onboarded" : "Runs cleared; models, specs and plans kept")(); router.push("/"); } });
  useEffect(() => {
    const c = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && (setOpen(false), setArmed(null));
    window.addEventListener("mousedown", c);
    return () => window.removeEventListener("mousedown", c);
  }, []);
  const confirm = (key: string, fn: () => void) => (armed === key ? fn() : setArmed(key));
  const running = state.data?.running;
  return (
    <div className="relative" ref={ref}>
      <button className={clsx("btn !py-1.5", running && "glow-agent")} onClick={() => setOpen((v) => !v)}>
        <Bot size={15} /> {running ? `Autopilot · ${state.data?.text?.slice(0, 32) || "running"}…` : "Demo"} <ChevronDown size={14} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
            className="absolute right-0 top-11 z-50 w-[330px] panel p-1.5">
            {[
              { k: "auto", icon: Bot, t: "Run autopilot", d: "Whole factory hands-free: every gate auto-approved, then drift, alerts and governance", fn: () => auto.mutate(), dis: running },
              { k: "seed", icon: Sprout, t: "Onboard the test estate", d: "Upload the 5 test models and the data room through the normal onboarding path", fn: () => seed.mutate() },
              { k: "runs", icon: RotateCcw, t: "Clear runs", d: "Keep models, specs, plans, data and prompts; clear runs, evidence and monitoring", fn: () => confirm("runs", () => reset.mutate("runs")), danger: true },
              { k: "all", icon: RotateCcw, t: "Factory reset", d: "Wipe everything and re-onboard the test estate", fn: () => confirm("all", () => reset.mutate("all")), danger: true },
            ].map((o) => (
              <button key={o.k} disabled={o.dis} onClick={o.fn}
                className={clsx("w-full text-left flex gap-3 rounded-lg px-3 py-2.5 hover:bg-slate-900/[.06] disabled:opacity-40", armed === o.k && "bg-fail/15")}>
                <o.icon size={17} className={clsx("mt-0.5 shrink-0", o.danger ? "text-fail" : "text-teal")} />
                <span>
                  <span className="block text-[14px] font-semibold">{armed === o.k ? "Click again to confirm" : o.t}</span>
                  <span className="block text-xs text-muted leading-snug">{o.d}</span>
                </span>
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Palette() {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const models = useQuery({ queryKey: ["models"], queryFn: () => get<any[]>("/api/models"), enabled: open });
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen((v) => !v); }
      if (e.key === "Escape") setOpen(false);
    };
    const o = () => setOpen(true);
    window.addEventListener("keydown", k);
    window.addEventListener("open-palette", o);
    return () => { window.removeEventListener("keydown", k); window.removeEventListener("open-palette", o); };
  }, []);
  const go = (h: string) => { setOpen(false); router.push(h); };
  if (!open) return null;
  const item = "flex items-center gap-3 rounded-lg px-3 py-2.5 text-[15px] text-text cursor-pointer data-[selected=true]:bg-slate-900/[.06]";
  return (
    <div className="fixed inset-0 z-[60] bg-slate-900/40 flex items-start justify-center pt-[12vh] px-4" onClick={() => setOpen(false)}>
      <Command className="panel w-full max-w-[620px] overflow-hidden" onClick={(e) => e.stopPropagation()} label="Command palette">
        <div className="flex items-center gap-3 px-5 border-b border-line">
          <Search size={18} className="text-muted" />
          <Command.Input autoFocus placeholder="Search screens, models and actions…" className="w-full bg-transparent py-4 text-lg outline-none" />
        </div>
        <Command.List className="max-h-[52vh] overflow-y-auto scroll-thin p-2">
          <Command.Empty className="p-4 text-muted">No results</Command.Empty>
          <Command.Group heading="Models" className="text-xs text-muted px-2">
            {(models.data || []).map((m) => (
              <Command.Item key={m.id} value={`${m.id} ${m.name}`} onSelect={() => go(`/models/${m.id}`)} className={item}>
                <Layers size={17} /> <span className="mono">{m.id}</span> <span className="text-muted truncate">{m.name}</span>
              </Command.Item>
            ))}
          </Command.Group>
          <Command.Group heading="Screens" className="text-xs text-muted px-2 mt-2">
            {ALL.map((n) => <Command.Item key={n.href} onSelect={() => go(n.href)} className={item}><n.icon size={17} /> {n.label}</Command.Item>)}
          </Command.Group>
          <Command.Group heading="Actions" className="text-xs text-muted px-2 mt-2">
            <Command.Item onSelect={() => go("/onboard")} className={item}><PackagePlus size={17} /> Onboard a new R model</Command.Item>
            <Command.Item onSelect={() => { post("/api/runs", { auto_approve: false }); go("/"); }} className={item}><Factory size={17} /> Start the factory for every idle model</Command.Item>
            <Command.Item onSelect={() => { post("/api/ledger/verify"); go("/governance"); }} className={item}><ShieldCheck size={17} /> Verify the audit ledger</Command.Item>
          </Command.Group>
        </Command.List>
      </Command>
    </div>
  );
}

function Toasts() {
  const toasts = useFactory((s) => s.toasts);
  const dismiss = useFactory((s) => s.dismiss);
  useEffect(() => {
    if (!toasts.length) return;
    const t = setTimeout(() => dismiss(toasts[0].id), 7000);
    return () => clearTimeout(t);
  }, [toasts, dismiss]);
  const tone: Record<string, string> = { alert: "glow-fail", security: "glow-fail", error: "glow-fail", gate: "glow-teal", success: "glow-teal", info: "" };
  return (
    <div className="fixed bottom-5 right-5 z-[80] flex flex-col gap-2 w-[min(420px,calc(100vw-2.5rem))]" aria-live="polite">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div key={t.id} layout initial={{ opacity: 0, x: 60 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 60 }}
            className={clsx("panel px-4 py-3 flex items-start gap-3", tone[t.kind])}>
            <div className="flex-1 text-[14.5px] leading-snug">{t.href ? <Link href={t.href} className="hover:underline">{t.text}</Link> : t.text}</div>
            <button onClick={() => dismiss(t.id)} aria-label="Dismiss"><X size={15} className="text-muted" /></button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  useEventStream();
  const path = usePathname();
  const connected = useFactory((s) => s.connected);
  const gates = useQuery({ queryKey: ["gates-pending"], queryFn: () => get<any[]>("/api/gates?status=pending"), refetchInterval: 6000 });
  const traffic = useQuery({ queryKey: ["traffic"], queryFn: () => get<any[]>("/api/traffic"), refetchInterval: 5000 });
  const alerts = (traffic.data || []).reduce((a: number, m: any) => a + Object.keys(m.active_alerts || {}).length, 0);
  const badges: Record<string, number> = { gates: gates.data?.length || 0, alerts };
  return (
    <div className="flex min-h-screen">
      <aside className="w-[236px] shrink-0 border-r border-line bg-ink-2/70 backdrop-blur sticky top-0 h-screen hidden md:flex flex-col">
        <Link href="/" className="flex items-center gap-2.5 px-5 h-16 border-b border-line">
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-teal to-agent grid place-items-center text-ink font-black">◉</div>
          <div className="leading-[1.15]">
            <div className="font-extrabold tracking-wide text-[15px]">MODEL RISK</div>
            <div className="text-[11px] tracking-[.3em] text-muted">FACTORY · v3</div>
            <div className="text-[10.5px] font-semibold tracking-[.12em] text-teal mt-px">by ZERO GRADIENT</div>
          </div>
        </Link>
        <nav className="flex-1 overflow-y-auto scroll-thin px-3 py-2" aria-label="Main">
          {NAV.map((g) => (
            <div key={g.group} className="mt-3 first:mt-1">
              <div className="px-3 pb-1 text-[10.5px] uppercase tracking-[.2em] text-faint font-semibold">{g.group}</div>
              {g.items.map((n: any) => {
                const active = isActive(path, n.href);
                const b = n.badge ? badges[n.badge] : 0;
                return (
                  <Link key={n.href} href={n.href}
                    className={clsx("relative flex items-center gap-3 rounded-lg px-3 py-2 text-[14.5px] transition",
                      active ? "bg-slate-900/[.08] text-text font-semibold" : "text-muted hover:text-text hover:bg-slate-900/[.04]")}>
                    {active && <motion.span layoutId="nav-active" className="absolute left-0 top-2 bottom-2 w-[3px] rounded bg-teal" />}
                    <n.icon size={17} className={active ? "text-teal" : ""} aria-hidden />
                    <span className="flex-1">{n.label}</span>
                    {!!b && <span className={clsx("rounded-full text-ink text-[11px] font-bold px-1.5 min-w-[20px] text-center", n.badge === "alerts" ? "bg-fail" : "bg-warn")}>{b}</span>}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="p-4 border-t border-line text-[11px] text-faint leading-relaxed">
          Agents draft · tools compute · humans decide. Every number is evidence; every action is on the ledger.
          <div className="mt-2 pt-2 border-t border-line/60 font-semibold text-muted tracking-wide">Built by Team Zero Gradient</div>
        </div>
      </aside>
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="sticky top-0 z-30 h-16 border-b border-line bg-ink/80 backdrop-blur flex items-center gap-3 px-4 md:px-6">
          <button className="flex items-center gap-2 rounded-lg border border-line bg-slate-900/[.03] px-3 py-1.5 text-sm text-muted hover:text-text w-[min(340px,40vw)]"
            onClick={() => window.dispatchEvent(new Event("open-palette"))}>
            <Search size={15} /> <span className="flex-1 text-left">Search models, screens, actions</span> <Kbd>⌘K</Kbd>
          </button>
          <div className="flex-1" />
          <StatusChips />
          <Link href="/approvals" className="relative btn !py-1.5 !px-2.5" aria-label="Pending approvals">
            <Bell size={16} />
            {!!badges.gates && <span className="absolute -top-1.5 -right-1.5 rounded-full bg-warn text-ink text-[10px] font-bold px-1.5">{badges.gates}</span>}
          </Link>
          <DemoMenu />
          <div className={clsx("flex items-center gap-2 text-xs font-bold tracking-widest", connected ? "text-pass" : "text-fail")} title="Live event stream">
            <span className={clsx("h-2.5 w-2.5 rounded-full", connected ? "bg-pass live-dot" : "bg-fail")} /> {connected ? "LIVE" : "OFFLINE"}
          </div>
        </header>
        <main className="flex-1 p-4 md:p-6 min-w-0">{children}</main>
      </div>
      <EvidenceDrawer />
      <Palette />
      <Toasts />
    </div>
  );
}
