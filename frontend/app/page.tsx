"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AnimatePresence, LayoutGroup, motion } from "framer-motion";
import {
  Activity, AlertTriangle, BadgeCheck, Check, CheckSquare, ClipboardCheck, DollarSign, Layers, PackagePlus, Play, RotateCcw,
  ShieldAlert, Sprout, Square, X,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { ActivityFeed } from "@/components/ActivityFeed";
import { Dot, Empty, PageHeader, Panel, Stat, Tag, fmtClock, inputCls, useNow } from "@/components/ui";
import { get, post, STAGE_LABEL } from "@/lib/api";
import { toast, useFactory } from "@/lib/store";

const COLUMNS = [
  { id: "onboarded", label: "Onboarded", hint: "uploaded, not started" },
  { id: "discover", label: "Intake", hint: "probe · spec" },
  { id: "document", label: "Document & plan", hint: "docs · review · plans" },
  { id: "redevelop", label: "Redevelop", hint: "export · translate · parity" },
  { id: "validate", label: "Validate", hint: "plan · investigate · report" },
  { id: "monitor", label: "Monitor", hint: "live traffic · alerts" },
];
const TIER_C: Record<string, string> = { A: "text-fail border-fail/40", B: "text-warn border-warn/40", C: "text-info border-info/40" };

function column(c: any) {
  if (c.run && ["queued"].includes(c.run.status)) return "discover";
  if (c.stage === "onboarded" || (!c.run && c.state === "idle")) return "onboarded";
  return c.station;
}

function Progress({ c }: { c: any }) {
  const order = COLUMNS.map((x) => x.id).slice(1);
  const i = order.indexOf(c.station);
  return (
    <div className="flex items-center gap-1" aria-label="progress">
      {order.map((s, k) => (
        <span key={s} className={clsx("h-1.5 flex-1 rounded-full",
          k < i || (k === i && c.state === "done") ? "bg-teal" : k === i ? (c.state === "running" ? "bg-agent live-dot" : ["failed", "rejected"].includes(c.state) ? "bg-fail" : c.state === "awaiting" ? "bg-warn" : "bg-slate-900/10") : "bg-slate-900/[.07]")} />
      ))}
    </div>
  );
}

function Card({ c, selected, toggle, live }: { c: any; selected: boolean; toggle: () => void; live?: { summary: string } }) {
  const qc = useQueryClient();
  const decide = useMutation({
    mutationFn: (decision: string) => post(`/api/gates/${c.gate.id}/decision`, { decision, comment: "", decided_by: "Model Risk Officer" }),
    onSuccess: (_r, d) => { qc.invalidateQueries(); toast({ kind: "success", text: `${c.id}: ${d === "approved" ? "promoted" : d.replace("_", " ")}` }); },
    onError: (e: any) => toast({ kind: "error", text: e.message }),
  });
  const start = useMutation({ mutationFn: () => post(`/api/models/${c.id}/start`), onSuccess: () => { qc.invalidateQueries(); toast({ kind: "info", text: `${c.id} entered the factory` }); },
    onError: (e: any) => toast({ kind: "error", text: e.message }) });
  const awaiting = c.state === "awaiting" && c.gate;
  const agent = c.gate?.context?.agent;
  const rec = c.recommendation || agent?.recommendation;
  const idle = column(c) === "onboarded";
  return (
    <motion.div layout layoutId={`card-${c.id}`} transition={{ type: "spring", stiffness: 160, damping: 22 }}
      className={clsx("rounded-xl border bg-panel-2/90 p-3 space-y-2", c.state === "running" ? "border-agent/60 glow-agent" :
        awaiting ? (selected ? "border-teal glow-teal" : "border-warn/50") : ["failed", "rejected"].includes(c.state) ? "border-fail/60" : "border-line")}>
      <div className="flex items-start gap-2">
        {awaiting ? <button onClick={toggle} aria-label={`select ${c.id}`} className="mt-0.5">{selected ? <CheckSquare size={17} className="text-teal" /> : <Square size={17} className="text-muted" />}</button>
          : <span className="w-[17px]" />}
        <Link href={`/models/${c.id}`} className="flex-1 min-w-0 group">
          <div className="flex items-center justify-between gap-2">
            <span className="mono font-bold group-hover:text-teal">{c.id}</span>
            {c.tier && <span className={clsx("rounded border px-1.5 text-[10.5px] font-bold", TIER_C[c.tier] || "text-muted border-line")}>TIER {c.tier}</span>}
          </div>
          <div className="text-[13px] text-muted truncate" title={c.name}>{c.name}</div>
        </Link>
      </div>
      {(c.task || c.strategy || c.parity) && (
        <div className="flex flex-wrap gap-1">
          {c.task && <Tag>{c.task}</Tag>}
          {c.strategy && <Tag tone={c.strategy === "rehost" ? "warn" : "agent"}>{c.strategy}</Tag>}
          {c.parity === "PASS" && <Tag tone="teal">parity ✓</Tag>}
          {c.deployed && <Tag tone="teal">live</Tag>}
        </div>
      )}
      {!idle && <Progress c={c} />}
      <div className={clsx("text-[12.5px] rounded-md px-2 py-1.5 leading-snug", c.state === "running" ? "agent-scan text-agent" : "bg-slate-900/[.03] text-muted")}>
        {idle && <>Uploaded · the intake agent hasn't looked at it yet</>}
        {c.run?.status === "queued" && <>⧗ queued — waiting for a free agent worker</>}
        {c.state === "running" && <>⟳ <b>{STAGE_LABEL[c.stage] || c.stage}</b> · {live?.summary?.replace(/^\[[a-z_]+\]\s*/, "").slice(0, 84) ?? "working"}</>}
        {awaiting && <>⏸ <b className="text-text">{c.gate.title}</b></>}
        {c.state === "done" && (c.deployed ? <><Dot tone="pass" pulse /> serving live traffic</> : <>✓ complete{c.parity === "REHOSTED" ? " · rehosted (not deployable)" : ""}</>)}
        {c.state === "failed" && <span className="text-fail">✗ failed at {STAGE_LABEL[c.stage] || c.stage}: {c.error?.slice(0, 90)}</span>}
        {c.state === "rejected" && <span className="text-fail">✗ stopped by a reviewer at {STAGE_LABEL[c.stage] || c.stage}</span>}
      </div>
      {awaiting && c.gate.context?.blocked && (
        <div className="text-[12px] rounded-md border border-fail/40 bg-fail/[.07] text-fail px-2 py-1.5 leading-snug">⛔ Can't approve: {c.gate.context.blocked.join("; ")}</div>
      )}
      {awaiting && agent && (
        <div className="text-[12.5px] leading-snug">
          <span className={clsx("font-bold", rec === "promote" ? "text-pass" : "text-warn")}>Agent: {rec?.toUpperCase()}</span>
          <div className="text-muted line-clamp-2" title={(agent.reasons || []).join(" · ")}>{(agent.reasons || []).join(" · ") || agent.summary}</div>
        </div>
      )}
      <div className="flex items-center gap-1.5 flex-wrap">
        {awaiting && <>
          <button className="btn btn-primary !py-1 !px-2 text-xs" onClick={() => decide.mutate("approved")} disabled={decide.isPending || !!c.gate.context?.blocked} title={c.gate.context?.blocked ? "Stage incomplete — send it back" : ""}><Check size={13} /> Approve</button>
          <button className="btn !py-1 !px-2 text-xs" onClick={() => decide.mutate("changes_requested")} disabled={decide.isPending} title="Send back: re-run the previous stage"><RotateCcw size={13} /></button>
          <button className="btn btn-danger !py-1 !px-2 text-xs" onClick={() => decide.mutate("rejected")} disabled={decide.isPending} title="Stop this model"><X size={13} /></button>
        </>}
        {idle && <button className="btn btn-primary !py-1 !px-2 text-xs" onClick={() => start.mutate()} disabled={start.isPending}><Play size={13} /> Start</button>}
        {["failed", "rejected"].includes(c.state) && <button className="btn !py-1 !px-2 text-xs" onClick={() => start.mutate()}><Play size={13} /> Restart</button>}
        <span className="ml-auto flex items-center gap-2 whitespace-nowrap">
          {c.gate?.context?.link && <Link className="text-xs text-teal hover:underline" href={c.gate.context.link}>review</Link>}
          {c.run && <Link className="text-xs text-muted hover:text-text" href={`/agents?run=${c.run.id}`}>trace</Link>}
        </span>
      </div>
    </motion.div>
  );
}

export default function Pipeline() {
  const qc = useQueryClient();
  const board = useQuery({ queryKey: ["pipeline"], queryFn: () => get("/api/pipeline"), refetchInterval: 2500 });
  const ov = useQuery({ queryKey: ["overview"], queryFn: () => get("/api/overview"), refetchInterval: 4000 });
  const active = useFactory((s) => s.activeAgents);
  const now = useNow(1000);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [comment, setComment] = useState("");
  const startAll = useMutation({ mutationFn: () => post("/api/runs", { auto_approve: false }), onSuccess: (r: any) => { qc.invalidateQueries(); toast({ kind: "info", text: `${r.runs.length} model(s) entered the factory` }); } });
  const seed = useMutation({ mutationFn: () => post("/api/demo/seed"), onSuccess: () => { qc.invalidateQueries(); toast({ kind: "success", text: "Test estate onboarded" }); } });
  const auto = useMutation({ mutationFn: (v: boolean) => post("/api/settings/auto_promote", { value: v }), onSuccess: () => qc.invalidateQueries() });
  const cards: any[] = board.data?.cards || [];
  const awaiting = cards.filter((c) => c.state === "awaiting" && c.gate);
  const chosen = awaiting.filter((c) => sel.has(c.id));
  const bulk = useMutation({
    mutationFn: (decision: string) => post("/api/gates/bulk-decision", { gate_ids: chosen.map((c) => c.gate.id), decision, comment, decided_by: "Model Risk Officer" }),
    onSuccess: (r: any, d) => {
      const blocked = r.results.filter((x: any) => x.status === "blocked");
      toast({ kind: blocked.length ? "error" : "success", text: `${r.results.length - blocked.length} model(s): ${d.replace("_", " ")}${blocked.length ? ` · ${blocked.length} blocked (stage incomplete — send back instead)` : ""}` });
      setSel(new Set()); setComment(""); qc.invalidateQueries();
    },
  });
  const toggle = (id: string) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const k = ov.data?.kpis || {};
  const clock = ov.data?.clock;
  const elapsed = clock ? (clock.active ? (now - new Date(clock.started_at).getTime()) / 1000 : clock.elapsed_s) : 0;
  const idle = cards.filter((c) => column(c) === "onboarded").length;

  return (
    <div className="space-y-5 max-w-[1800px] mx-auto pb-28">
      <PageHeader title="Factory floor"
        sub={<>Agents work each model stage by stage — intake, documentation & planning, redevelopment, validation, monitoring. <b className="text-text">You decide</b> what moves on, one model or many at once.</>}
        actions={<>
          <label className="flex items-center gap-2 text-sm cursor-pointer select-none mr-1" title="Gates where the agent recommends PROMOTE pass automatically; HOLD still waits for you">
            <input type="checkbox" className="accent-[#0d9488] h-4 w-4" checked={!!board.data?.auto_promote} onChange={(e) => auto.mutate(e.target.checked)} />
            Auto-promote on agent PROMOTE
          </label>
          <Link href="/onboard" className="btn"><PackagePlus size={16} /> Onboard model</Link>
          <button className="btn btn-primary" disabled={!idle || startAll.isPending} onClick={() => startAll.mutate()}><Play size={16} /> Start {idle || ""} idle model{idle === 1 ? "" : "s"}</button>
        </>} />

      <div className="grid grid-cols-2 md:grid-cols-4 2xl:grid-cols-8 gap-3">
        <Stat icon={Layers} label="Models" value={k.models_total ?? "—"} sub={`${k.runs_active ?? 0} run(s) active`} />
        <Stat icon={BadgeCheck} label="Validated" value={k.models_validated ?? "—"} sub="approved by a human" tone="text-pass" />
        <Stat icon={BadgeCheck} label="Parity PASS" value={k.parity_pass ?? "—"} sub={`${k.rehosted ?? 0} rehosted`} tone="text-teal" />
        <Stat icon={Activity} label="Live" value={k.live ?? "—"} sub="serving traffic" tone="text-info" />
        <Stat icon={ClipboardCheck} label="Awaiting you" value={k.gates_open ?? "—"} sub={<Link href="/approvals" className="hover:underline">open approvals</Link>} tone={k.gates_open ? "text-warn" : undefined} />
        <Stat icon={AlertTriangle} label="High findings" value={k.findings_high ?? "—"} sub={`${k.findings ?? 0} total`} tone={k.findings_high ? "text-fail" : undefined} />
        <Stat icon={ShieldAlert} label="Agent steps" value={k.agent_steps ?? "—"} sub="persisted trace" tone="text-agent" />
        <Stat icon={DollarSign} label="LLM spend" value={`$${(k.llm_cost_usd ?? 0).toFixed(3)}`} sub={`${k.llm_calls ?? 0} calls · ${clock ? fmtClock(elapsed) : "—"}`} />
      </div>

      {board.isSuccess && !cards.length ? (
        <Panel>
          <Empty title="No models in the factory yet" action={<div className="flex gap-2">
            <Link href="/onboard" className="btn btn-primary"><PackagePlus size={16} /> Onboard an R model</Link>
            <button className="btn" onClick={() => seed.mutate()} disabled={seed.isPending}><Sprout size={16} /> Onboard the 5-model test estate</button>
          </div>}>
            Upload any legacy R script with its data. The intake agent runs it in the sandbox, works out what it is and drafts a specification for you to approve.
          </Empty>
        </Panel>
      ) : (
        <LayoutGroup>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6 gap-3">
            {COLUMNS.map((col) => {
              const list = cards.filter((c) => column(c) === col.id);
              return (
                <div key={col.id} className="rounded-2xl border border-line bg-slate-900/[.015] p-2.5 min-h-[220px]">
                  <div className="flex items-center justify-between px-1.5 pb-2">
                    <div>
                      <div className="text-[13px] font-semibold">{col.label}</div>
                      <div className="text-[11px] text-faint">{col.hint}</div>
                    </div>
                    <span className="mono text-xs text-muted rounded-md bg-slate-900/[.05] px-1.5">{list.length}</span>
                  </div>
                  <div className="space-y-2.5">
                    <AnimatePresence>
                      {list.map((c) => <Card key={c.id} c={c} selected={sel.has(c.id)} toggle={() => toggle(c.id)} live={active[c.id]} />)}
                    </AnimatePresence>
                  </div>
                </div>
              );
            })}
          </div>
        </LayoutGroup>
      )}

      <Panel title="Live log" right={<Link href="/agents" className="text-xs text-teal hover:underline">open agent console →</Link>}>
        <ActivityFeed height={300} />
      </Panel>

      <AnimatePresence>
        {awaiting.length > 0 && (
          <motion.div initial={{ y: 80, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 80, opacity: 0 }}
            className="fixed bottom-5 left-1/2 -translate-x-1/2 md:ml-[118px] z-40 panel px-4 py-3 flex items-center gap-3 flex-wrap shadow-2xl max-w-[calc(100vw-2rem)]">
            <span className="text-sm"><b>{awaiting.length}</b> waiting · <b className="text-teal">{chosen.length}</b> selected</span>
            <button className="btn !py-1 text-xs" onClick={() => setSel(new Set(awaiting.map((c) => c.id)))}>Select all</button>
            <button className="btn !py-1 text-xs" onClick={() => setSel(new Set(awaiting.filter((c) => (c.recommendation || c.gate?.context?.agent?.recommendation) === "promote").map((c) => c.id)))}>Select agent-recommended</button>
            <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment (ledger; sent to the agent on 'changes')" className={clsx(inputCls, "!py-1.5 w-64 text-sm")} />
            <button className="btn btn-primary !py-1.5" disabled={!chosen.length || bulk.isPending} onClick={() => bulk.mutate("approved")}><Check size={15} /> Approve {chosen.length || ""}</button>
            <button className="btn !py-1.5" disabled={!chosen.length || bulk.isPending} onClick={() => bulk.mutate("changes_requested")}><RotateCcw size={15} /> Send back</button>
            <button className="btn btn-danger !py-1.5" disabled={!chosen.length || bulk.isPending} onClick={() => bulk.mutate("rejected")}><X size={15} /> Reject</button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
