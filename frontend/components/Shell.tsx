"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Command } from "cmdk";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity, BadgeCheck, Bot, BrainCircuit, ChevronLeft, ChevronRight, ClipboardCheck, Factory, FileText, FolderTree, Gauge, Layers, Network,
  PoundSterling, RotateCcw, ShieldCheck, Sparkles, StickyNote, Target, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import { useFactory } from "@/lib/store";
import { useEventStream } from "@/lib/useEventStream";
import { EvidenceDrawer } from "./Evidence";

const NAV = [
  { href: "/", label: "Pipeline", icon: Factory },
  { href: "/agents", label: "Agent Console", icon: BrainCircuit },
  { href: "/files", label: "Models Folder", icon: FolderTree },
  { href: "/inventory", label: "Inventory & Graph", icon: Network },
  { href: "/models/CR-001", label: "Model Workbench", icon: Layers },
  { href: "/models/CR-001/parity", label: "Parity Certificate", icon: BadgeCheck },
  { href: "/reports/CR-001", label: "Validation Report", icon: FileText },
  { href: "/scorecard", label: "Validator Scorecard", icon: Target },
  { href: "/monitoring", label: "Live Monitoring", icon: Activity },
  { href: "/governance", label: "Controls & Ledger", icon: ShieldCheck },
  { href: "/responsible-ai", label: "Responsible AI", icon: Sparkles },
  { href: "/impact", label: "Business Impact", icon: PoundSterling },
  { href: "/approvals", label: "Approvals", icon: ClipboardCheck },
];

export const BEATS = [
  { route: "/", title: "The pipeline", note: "Five legacy R models. Discovery runs on all of them; each agent recommends promote or hold. Tick several cards and promote them together — the human decides, in bulk." },
  { route: "/files", title: "The legacy estate", note: "The real models folder: untouched R scripts, the data room they expect at //shared/riskdata, and every artifact each run produced." },
  { route: "/agents", title: "Agents at work", note: "Every stage is plan → tool calls → observations → recommendation. Open a tool call to see its exact arguments and result." },
  { route: "/models/CR-001/parity", title: "Parity, model by model", note: "Each legacy model ran unmodified in a no-network sandbox. Python matches to 1e-10 or better; the forest (CR-002) is rehosted, not translated." },
  { route: "/reports/CR-001", title: "Every number is evidence", note: "The LLM writes tokens, never numbers. Click any figure → definition, hashes, code → Reproduce recomputes live." },
  { route: "/scorecard", title: "Validate the validator", note: "10 planted defects plus 2 clean controls: what is caught, what is missed, zero false alarms." },
  { route: "/monitoring", title: "Live traffic", note: "Deployed models score simulated requests with measured latency. Ramp a drift scenario: PSI/CSI climb, three bad windows raise an alert, re-validation runs by itself." },
  { route: "/governance", title: "Tamper-evident audit", note: "SS1/23 controls as code. Verify the chain, tamper with a finding, verify again." },
  { route: "/responsible-ai", title: "Responsible AI", note: "Fairness and proxy tests for the model; injection defence and the factory card for the AI itself." },
];

function DemoBar() {
  const router = useRouter();
  const path = usePathname();
  const qc = useQueryClient();
  const [notes, setNotes] = useState(false);
  const [follow, setFollow] = useState(true);
  const events = useFactory((s) => s.events);
  const clear = useFactory((s) => s.clear);
  const idx = Math.max(0, BEATS.findIndex((b) => b.route === path));
  const reset = useMutation({ mutationFn: () => post("/api/demo/reset"), onSuccess: () => { clear(); qc.invalidateQueries(); router.push("/"); } });
  const auto = useMutation({ mutationFn: () => post("/api/demo/autopilot") });
  const state = useQuery({ queryKey: ["demo-state"], queryFn: () => get("/api/demo/state"), refetchInterval: 4000 });
  const running = state.data?.running;

  // follow autopilot beats
  const last = events.filter((e) => e.agent === "autopilot" && e.payload?.route).at(-1);
  useEffect(() => {
    if (follow && last && Date.now() - new Date(last.ts).getTime() < 6000) router.push(last.payload.route);
  }, [last?.id]); // eslint-disable-line

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (/^[1-9]$/.test(e.key) && BEATS[+e.key - 1]) router.push(BEATS[+e.key - 1].route);
      if (e.key === "ArrowRight" && e.shiftKey) router.push(BEATS[Math.min(BEATS.length - 1, idx + 1)].route);
      if (e.key === "ArrowLeft" && e.shiftKey) router.push(BEATS[Math.max(0, idx - 1)].route);
      if (e.key === "n") setNotes((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [idx, router]);

  return (
    <div className="relative flex items-center gap-2">
      <div className="hidden lg:flex items-center gap-1 rounded-xl border border-line bg-white/[.03] p-1">
        <button className="btn !p-1.5 !border-0" onClick={() => router.push(BEATS[Math.max(0, idx - 1)].route)} aria-label="Previous beat"><ChevronLeft size={16} /></button>
        {BEATS.map((b, i) => (
          <button key={b.route} onClick={() => router.push(b.route)} title={`${i + 1}. ${b.title}`}
            className={clsx("h-7 w-7 rounded-lg text-xs font-bold transition", i === idx ? "bg-teal text-ink" : "text-muted hover:bg-white/10")}>{i + 1}</button>
        ))}
        <button className="btn !p-1.5 !border-0" onClick={() => router.push(BEATS[Math.min(BEATS.length - 1, idx + 1)].route)} aria-label="Next beat"><ChevronRight size={16} /></button>
      </div>
      <button className={clsx("btn !py-1.5", notes && "glow-teal")} onClick={() => setNotes((v) => !v)} title="Presenter notes (n)"><StickyNote size={15} /> Notes</button>
      <button className={clsx("btn !py-1.5", running && "glow-agent")} onClick={() => auto.mutate()} disabled={running} title="Run the whole demo hands-free">
        <Bot size={15} /> {running ? `Autopilot · beat ${state.data?.beat}` : "Autopilot"}
      </button>
      <button className="btn !py-1.5" onClick={() => { if (confirmReset()) reset.mutate(); }} title="Reset demo"><RotateCcw size={15} /> Reset</button>
      <AnimatePresence>
        {notes && (
          <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}
            className="absolute right-0 top-11 z-40 w-[420px] panel p-4">
            <div className="flex items-center justify-between">
              <div className="panel-title">Beat {idx + 1} · {BEATS[idx].title}</div>
              <button onClick={() => setNotes(false)} aria-label="Close notes"><X size={16} /></button>
            </div>
            <p className="mt-2 text-[15px] leading-relaxed">{BEATS[idx].note}</p>
            <label className="mt-3 flex items-center gap-2 text-sm text-muted">
              <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> Follow autopilot between pages
            </label>
            <div className="mt-2 text-xs text-faint">Keys: 1–9 jump · Shift+←/→ step · n notes · ⌘K command palette</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// Reset is destructive for the demo state; a small inline confirm avoids blocking browser dialogs.
let armed = 0;
function confirmReset() {
  const now = Date.now();
  if (now - armed < 2500) return true;
  armed = now;
  useFactory.setState((s) => ({ toasts: [...s.toasts, { id: `reset${now}`, kind: "info", text: "Press Reset again within 2s to clear the demo." }] }));
  return false;
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
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);
  const go = (h: string) => { setOpen(false); router.push(h); };
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60] bg-black/60 flex items-start justify-center pt-[12vh]" onClick={() => setOpen(false)}>
      <Command className="panel w-[600px] overflow-hidden" onClick={(e) => e.stopPropagation()} label="Command palette">
        <Command.Input autoFocus placeholder="Jump to a screen, model or action…" className="w-full bg-transparent px-5 py-4 text-lg outline-none border-b border-line" />
        <Command.List className="max-h-[50vh] overflow-y-auto scroll-thin p-2">
          <Command.Empty className="p-4 text-muted">No results</Command.Empty>
          <Command.Group heading="Screens" className="text-xs text-muted px-2">
            {NAV.map((n) => (
              <Command.Item key={n.href} onSelect={() => go(n.href)} className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-base text-text cursor-pointer data-[selected=true]:bg-white/10">
                <n.icon size={17} /> {n.label}
              </Command.Item>
            ))}
          </Command.Group>
          <Command.Group heading="Models" className="text-xs text-muted px-2 mt-2">
            {(models.data || []).map((m) => (
              <Command.Item key={m.id} onSelect={() => go(`/models/${m.id}`)} className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-base text-text cursor-pointer data-[selected=true]:bg-white/10">
                <Layers size={17} /> {m.id} · {m.name}
              </Command.Item>
            ))}
          </Command.Group>
          <Command.Group heading="Actions" className="text-xs text-muted px-2 mt-2">
            <Command.Item onSelect={() => { post("/api/runs", { auto_approve: false }); go("/"); }} className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-base text-text cursor-pointer data-[selected=true]:bg-white/10"><Factory size={17} /> Start factory (human gates)</Command.Item>
            <Command.Item onSelect={() => { post("/api/benchmarks/run"); go("/scorecard"); }} className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-base text-text cursor-pointer data-[selected=true]:bg-white/10"><Target size={17} /> Run seeded-defect benchmark</Command.Item>
            <Command.Item onSelect={() => { post("/api/ledger/verify"); go("/governance"); }} className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-base text-text cursor-pointer data-[selected=true]:bg-white/10"><ShieldCheck size={17} /> Verify ledger</Command.Item>
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
  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 w-[420px]" aria-live="polite">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div key={t.id} layout initial={{ opacity: 0, x: 60 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 60 }}
            className={clsx("panel px-4 py-3 flex items-start gap-3", t.kind === "alert" && "glow-fail", t.kind === "security" && "glow-fail", t.kind === "gate" && "glow-teal")}>
            <div className="flex-1 text-[15px]">
              {t.href ? <Link href={t.href} className="hover:underline">{t.text}</Link> : t.text}
            </div>
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
  const gates = useQuery({ queryKey: ["gates-pending"], queryFn: () => get<any[]>("/api/gates?status=pending"), refetchInterval: 8000 });
  const health = useQuery({ queryKey: ["health"], queryFn: () => get("/api/health"), refetchInterval: 15000 });
  return (
    <div className="flex min-h-screen">
      <aside className="w-[244px] shrink-0 border-r border-line bg-ink-2/70 backdrop-blur sticky top-0 h-screen flex flex-col">
        <Link href="/" className="flex items-center gap-2.5 px-5 h-16 border-b border-line">
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-teal to-agent grid place-items-center text-ink font-black">◉</div>
          <div className="leading-tight">
            <div className="font-extrabold tracking-wide text-[15px]">MODEL RISK</div>
            <div className="text-[11px] tracking-[.3em] text-muted">FACTORY</div>
          </div>
        </Link>
        <nav className="flex-1 overflow-y-auto scroll-thin p-3 space-y-0.5" aria-label="Main">
          {NAV.map((n) => {
            const active = n.href === "/" ? path === "/" : path === n.href || (n.href !== "/models/CR-001" && path.startsWith(n.href)) || (n.href === "/models/CR-001" && path.startsWith("/models/") && !path.endsWith("/parity"));
            return (
              <Link key={n.href} href={n.href}
                className={clsx("flex items-center gap-3 rounded-lg px-3 py-2.5 text-[15px] transition", active ? "bg-white/[.08] text-text font-semibold" : "text-muted hover:text-text hover:bg-white/[.04]")}>
                <n.icon size={18} className={active ? "text-teal" : ""} aria-hidden />
                <span className="flex-1">{n.label}</span>
                {n.href === "/approvals" && !!gates.data?.length && (
                  <span className="rounded-full bg-warn text-ink text-xs font-bold px-2">{gates.data.length}</span>
                )}
              </Link>
            );
          })}
        </nav>
        <div className="p-4 border-t border-line text-xs text-muted space-y-1">
          <div className="flex justify-between gap-2"><span>LLM</span><span className={`mono text-right ${health.data?.llm_error ? "text-warn" : "text-text"}`} title={health.data?.llm_error || ""}>{health.data?.llm ?? "…"}</span></div>
          {health.data?.llm_error && <div className="text-warn text-[11px] leading-snug">{health.data.llm_error}</div>}
          <div className="flex justify-between"><span>R sandbox</span><span className={health.data?.sandbox_docker ? "text-pass" : "text-warn"}>{health.data ? (health.data.sandbox_docker ? "docker" : "reference") : "…"}</span></div>
          <div className="flex justify-between"><span>Ledger</span><span className={health.data?.ledger === false ? "text-fail" : "text-pass"}>{health.data ? (health.data.ledger ? "intact" : "BROKEN") : "…"}</span></div>
        </div>
      </aside>
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="sticky top-0 z-30 h-16 border-b border-line bg-ink/80 backdrop-blur flex items-center gap-4 px-6">
          <DemoBar />
          <div className="flex-1" />
          <button className="btn !py-1.5 text-muted" onClick={() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }))}>
            <Gauge size={15} /> ⌘K
          </button>
          <div className={clsx("flex items-center gap-2 text-sm font-bold tracking-widest", connected ? "text-pass" : "text-fail")}>
            <span className={clsx("h-2.5 w-2.5 rounded-full", connected ? "bg-pass live-dot" : "bg-fail")} /> {connected ? "LIVE" : "OFFLINE"}
          </div>
        </header>
        <main className="flex-1 p-6 min-w-0">{children}</main>
      </div>
      <EvidenceDrawer />
      <Palette />
      <Toasts />
    </div>
  );
}
