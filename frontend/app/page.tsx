"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AnimatePresence, LayoutGroup, motion } from "framer-motion";
import { ArrowRight, Check, CheckSquare, Play, RotateCcw, Square, ThumbsDown, ThumbsUp, X } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { ActivityFeed } from "@/components/ActivityFeed";
import { CountUp, fmtClock, Panel, Tag, useNow } from "@/components/ui";
import { get, post, STATION_LABEL, STATIONS } from "@/lib/api";
import { useFactory } from "@/lib/store";

const TIER_C: Record<string, string> = { A: "text-fail border-fail/40", B: "text-warn border-warn/40", C: "text-info border-info/40" };
const STAGE_ORDER = ["discover", "document", "redevelop", "validate", "monitor"];

function StageDots({ station, state }: { station: string; state: string }) {
  const i = STAGE_ORDER.indexOf(station);
  return (
    <div className="flex items-center gap-1" aria-label={`stage ${i + 1} of 5`}>
      {STAGE_ORDER.map((s, k) => (
        <span key={s} className={clsx("h-1.5 w-5 rounded-full", k < i || (k === i && state === "done") ? "bg-teal" : k === i ? (state === "running" ? "bg-agent live-dot" : state === "failed" || state === "rejected" ? "bg-fail" : "bg-warn") : "bg-white/10")} />
      ))}
    </div>
  );
}

function Card({ c, selected, toggle, live }: { c: any; selected: boolean; toggle: () => void; live?: { summary: string } }) {
  const qc = useQueryClient();
  const decide = useMutation({ mutationFn: (decision: string) => post(`/api/gates/${c.gate.id}/decision`, { decision, comment: "", decided_by: "Model Risk Officer" }), onSuccess: () => qc.invalidateQueries() });
  const awaiting = c.state === "awaiting" && c.gate;
  const agent = c.gate?.context?.agent;
  const rec = c.recommendation || agent?.recommendation;
  return (
    <motion.div layout layoutId={`card-${c.id}`} transition={{ type: "spring", stiffness: 140, damping: 20 }}
      className={clsx("rounded-xl border bg-panel-2/90 p-3", c.state === "running" ? "border-agent/60 glow-agent" : awaiting ? (selected ? "border-teal glow-teal" : "border-warn/50") : c.state === "failed" ? "border-fail/60" : "border-line")}>
      <div className="flex items-start gap-2">
        {awaiting ? (
          <button onClick={toggle} aria-label={`select ${c.id}`} className="mt-0.5 text-teal">{selected ? <CheckSquare size={18} /> : <Square size={18} className="text-muted" />}</button>
        ) : <span className="w-[18px]" />}
        <Link href={`/models/${c.id}`} className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className="mono font-bold">{c.id}</span>
            <span className={clsx("rounded border px-1.5 text-[11px] font-bold", TIER_C[c.tier])}>TIER {c.tier}</span>
          </div>
          <div className="text-sm text-muted truncate">{c.name}</div>
        </Link>
      </div>
      <div className="mt-2"><StageDots station={c.station} state={c.state} /></div>
      <div className={clsx("mt-2 text-[13px] rounded-md px-2 py-1.5", c.state === "running" ? "agent-scan text-agent" : "bg-white/[.03] text-muted")}>
        {c.state === "running" && <>⟳ {live?.summary?.replace(/^\[[a-z_]+\]\s*/, "").slice(0, 90) ?? c.stage}</>}
        {awaiting && <>⏸ waiting for you: <b className="text-text">{c.gate.title}</b></>}
        {c.state === "done" && (c.deployed ? <>● live · serving traffic</> : <>✓ complete{c.strategy === "rehost" ? " (rehosted, not deployable)" : ""}</>)}
        {c.state === "failed" && <span className="text-fail">✗ failed at {c.stage}: {c.error?.slice(0, 80)}</span>}
        {c.state === "rejected" && <span className="text-fail">✗ rejected at {c.stage}</span>}
        {c.state === "new" && <>not started</>}
      </div>
      {awaiting && agent && (
        <div className="mt-2 text-[12.5px]">
          <span className={clsx("font-bold", rec === "promote" ? "text-pass" : "text-warn")}>Agent recommends {rec?.toUpperCase()}</span>
          <div className="text-muted line-clamp-2" title={agent.summary}>{(agent.reasons || []).join(" · ") || agent.summary}</div>
        </div>
      )}
      {awaiting && (
        <div className="mt-2 flex gap-1.5">
          <button className="btn !py-1 !px-2 text-xs" onClick={() => decide.mutate("approved")} disabled={decide.isPending}><Check size={13} /> Promote</button>
          <button className="btn !py-1 !px-2 text-xs" onClick={() => decide.mutate("changes_requested")} disabled={decide.isPending} title="Re-run the previous stage"><RotateCcw size={13} /></button>
          <button className="btn btn-danger !py-1 !px-2 text-xs" onClick={() => decide.mutate("rejected")} disabled={decide.isPending} title="Stop this model"><X size={13} /></button>
          {c.run && <Link className="btn !py-1 !px-2 text-xs ml-auto" href={`/agents?run=${c.run.id}`}>Trace</Link>}
        </div>
      )}
      {!awaiting && c.run && c.state !== "new" && <Link className="mt-2 inline-block text-xs text-teal hover:underline" href={`/agents?run=${c.run.id}`}>View agent trace →</Link>}
    </motion.div>
  );
}

export default function Pipeline() {
  const qc = useQueryClient();
  const board = useQuery({ queryKey: ["pipeline"], queryFn: () => get("/api/pipeline"), refetchInterval: 2500 });
  const ov = useQuery({ queryKey: ["overview"], queryFn: () => get("/api/overview"), refetchInterval: 4000 });
  const traffic = useQuery({ queryKey: ["traffic"], queryFn: () => get<any[]>("/api/traffic"), refetchInterval: 3000 });
  const active = useFactory((s) => s.activeAgents);
  const now = useNow(500);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [comment, setComment] = useState("");
  const start = useMutation({ mutationFn: () => post("/api/runs", { auto_approve: false }), onSuccess: () => qc.invalidateQueries() });
  const auto = useMutation({ mutationFn: (v: boolean) => post("/api/settings/auto_promote", { value: v }), onSuccess: () => qc.invalidateQueries() });
  const bulk = useMutation({
    mutationFn: (decision: string) => post("/api/gates/bulk-decision", { gate_ids: cards.filter((c) => sel.has(c.id) && c.gate).map((c) => c.gate.id), decision, comment, decided_by: "Model Risk Officer" }),
    onSuccess: () => { setSel(new Set()); setComment(""); qc.invalidateQueries(); },
  });
  const cards: any[] = board.data?.cards || [];
  const awaiting = cards.filter((c) => c.state === "awaiting" && c.gate);
  const selectedNow = [...sel].filter((id) => awaiting.some((c) => c.id === id));
  const toggle = (id: string) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const clock = ov.data?.clock;
  const elapsed = clock ? (clock.active ? (now - new Date(clock.started_at).getTime()) / 1000 : clock.elapsed_s) : 0;
  const live = traffic.data || [];
  const rpm = live.reduce((a, m) => a + (m.latest?.rpm || 0), 0);
  const alerts = live.reduce((a, m) => a + Object.keys(m.active_alerts || {}).length, 0);
  const nextOf = useMemo(() => Object.fromEntries(awaiting.map((c) => [c.id, c.gate.title])), [awaiting]);

  return (
    <div className="space-y-5 max-w-[1700px] mx-auto pb-24">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Pipeline</h1>
          <p className="text-muted mt-1">Agents do the work stage by stage; <b className="text-text">you decide</b> which models move on — one at a time or many together.</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <label className="flex items-center gap-2 text-sm cursor-pointer select-none" title="When on, gates where the agent recommends PROMOTE pass automatically; HOLD still waits for a human">
            <input type="checkbox" className="accent-[#2dd4bf] h-4 w-4" checked={!!board.data?.auto_promote} onChange={(e) => auto.mutate(e.target.checked)} />
            Auto-promote when the agent recommends it
          </label>
          <button className="btn btn-primary" disabled={start.isPending} onClick={() => start.mutate()}><Play size={16} /> {cards.length ? "Start remaining models" : "Discover the legacy estate"}</button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        {[
          ["Models", cards.length, ""],
          ["Waiting for you", awaiting.length, awaiting.length ? "text-warn" : ""],
          ["Agents working", cards.filter((c) => c.state === "running").length, "text-agent"],
          ["Deployed", cards.filter((c) => c.deployed).length, "text-pass"],
          ["Live requests / min", Math.round(rpm), "text-teal"],
          ["Open monitoring alerts", alerts, alerts ? "text-fail" : ""],
        ].map(([l, v, tone]: any) => (
          <div key={l} className="panel px-4 py-3">
            <div className="text-[11px] uppercase tracking-[.14em] text-muted font-semibold">{l}</div>
            <div className={clsx("text-3xl font-bold num mt-1", tone)}><CountUp value={Number(v)} /></div>
          </div>
        ))}
      </div>

      <Panel title={<>Factory floor {clock && <span className="ml-3 mono normal-case tracking-normal text-agent">{fmtClock(elapsed)}</span>}</>}
        right={awaiting.length > 0 && (
          <div className="flex gap-2 text-xs">
            <button className="btn !py-1 !px-2" onClick={() => setSel(new Set(awaiting.map((c) => c.id)))}>Select all waiting</button>
            <button className="btn !py-1 !px-2" onClick={() => setSel(new Set(awaiting.filter((c) => (c.recommendation || c.gate?.context?.agent?.recommendation) === "promote").map((c) => c.id)))}>Select agent-recommended</button>
          </div>)}>
        {!cards.length ? (
          <div className="py-14 text-center">
            <div className="text-xl font-semibold">No models yet.</div>
            <p className="text-muted mt-2">Press <b>Discover the legacy estate</b>: the Discovery agent walks <Link className="text-teal" href="/files">the models folder</Link> and registers every model it finds.</p>
          </div>
        ) : (
          <LayoutGroup>
            <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
              {STATIONS.map((st, i) => {
                const here = cards.filter((c) => c.station === st);
                const hot = here.some((c) => c.state === "running");
                return (
                  <div key={st} className={clsx("rounded-xl border p-3 min-h-[300px] relative", hot ? "border-agent/40 bg-agent/[.05]" : "border-line bg-white/[.015]")}>
                    <div className="flex items-center justify-between mb-3">
                      <div className="font-bold tracking-[.18em] text-[13px] uppercase">{STATION_LABEL[st]}</div>
                      <div className="text-xs text-muted">{here.length}</div>
                    </div>
                    {i < 4 && <ArrowRight size={18} className="absolute -right-[15px] top-4 text-faint z-10 hidden md:block" aria-hidden />}
                    <div className="space-y-2.5">
                      {here.map((c) => <Card key={c.id} c={c} selected={sel.has(c.id)} toggle={() => toggle(c.id)} live={active[c.id]} />)}
                    </div>
                  </div>
                );
              })}
            </div>
          </LayoutGroup>
        )}
      </Panel>

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_460px] gap-5">
        <Panel title="Live agent activity" right={<Link href="/agents" className="text-xs text-teal hover:underline">Open agent console →</Link>}>
          <ActivityFeed height={380} hideTypes={["metric", "ledger_append", "traffic"]} />
        </Panel>
        <Panel title="Live traffic" right={<Link href="/monitoring" className="text-xs text-teal hover:underline">Monitoring →</Link>}>
          {!live.length ? <div className="text-muted text-sm py-8 text-center">Nothing deployed yet. Promote a validated model to Monitor.</div> : (
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-muted uppercase"><th className="py-1">Model</th><th>req/min</th><th>p95 ms</th><th>PSI</th><th>Status</th></tr></thead>
              <tbody>{live.map((m) => (
                <tr key={m.model_id} className="border-t border-line/60">
                  <td className="py-2"><Link className="mono font-bold hover:text-teal" href={`/monitoring?model=${m.model_id}`}>{m.model_id}</Link>{m.cfg?.scenario && <Tag tone="warn">{m.cfg.scenario}</Tag>}</td>
                  <td className="mono">{m.latest?.rpm ?? "—"}</td>
                  <td className="mono">{m.latest?.latency_p95_ms ?? "—"}</td>
                  <td className="mono">{m.latest?.psi ?? "…"}</td>
                  <td><span className={clsx("inline-flex items-center gap-1.5 text-xs font-bold", m.latest?.status === "red" ? "text-fail" : m.latest?.status === "amber" ? "text-warn" : "text-pass")}><span className={clsx("h-2 w-2 rounded-full", m.latest?.status === "red" ? "bg-fail live-dot" : m.latest?.status === "amber" ? "bg-warn" : "bg-pass")} />{m.latest?.status ?? "starting"}</span></td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Panel>
      </div>

      <AnimatePresence>
        {selectedNow.length > 0 && (
          <motion.div initial={{ y: 80, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 80, opacity: 0 }}
            className="fixed bottom-5 left-1/2 -translate-x-1/2 z-40 panel glow-teal px-5 py-3 flex items-center gap-3 flex-wrap max-w-[min(1100px,92vw)]">
            <div className="font-semibold">{selectedNow.length} selected</div>
            <div className="text-xs text-muted max-w-[320px] truncate">{selectedNow.map((id) => `${id} → ${nextOf[id]?.replace("Promote to ", "")}`).join(" · ")}</div>
            <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment for the ledger…" className="rounded-md border border-line bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-teal w-[220px]" />
            <button className="btn btn-primary !py-1.5" onClick={() => bulk.mutate("approved")} disabled={bulk.isPending}><ThumbsUp size={15} /> Promote selected</button>
            <button className="btn !py-1.5" onClick={() => bulk.mutate("changes_requested")} disabled={bulk.isPending}><RotateCcw size={15} /> Request changes</button>
            <button className="btn btn-danger !py-1.5" onClick={() => bulk.mutate("rejected")} disabled={bulk.isPending}><ThumbsDown size={15} /> Reject</button>
            <button className="btn !py-1.5 !px-2" onClick={() => setSel(new Set())} aria-label="Clear selection"><X size={15} /></button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
