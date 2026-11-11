"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Check, CheckSquare, MessageSquareWarning, Square, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Ev } from "@/components/Evidence";
import { Badge, Empty, Panel } from "@/components/ui";
import { get, post } from "@/lib/api";

function GateCard({ g, selected, toggle }: { g: any; selected: boolean; toggle: () => void }) {
  const qc = useQueryClient();
  const [comment, setComment] = useState("");
  const decide = useMutation({
    mutationFn: (decision: string) => post(`/api/gates/${g.id}/decision`, { decision, comment, decided_by: "Model Risk Officer" }),
    onSuccess: () => qc.invalidateQueries(),
  });
  const ctx = g.context || {};
  const ag = ctx.agent;
  return (
    <Panel className={clsx(selected && "glow-teal")}>
      <div className="flex items-start gap-3">
        <button onClick={toggle} aria-label={`select gate ${g.id}`} className="mt-1 text-teal">{selected ? <CheckSquare size={20} /> : <Square size={20} className="text-muted" />}</button>
        <div className="flex-1">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-xl font-semibold">{g.title}</div>
              <div className="text-muted mt-0.5"><Link className="mono text-teal" href={`/models/${g.model_id}`}>{g.model_id}</Link> · run <Link className="mono hover:text-teal" href={`/agents?run=${g.run_id}`}>{g.run_id}</Link> · {new Date(g.requested_at).toLocaleTimeString()}</div>
            </div>
            <Badge kind="pending" />
          </div>
          {ag && (
            <div className={clsx("mt-3 rounded-lg border px-3 py-2 text-[14.5px]", ag.recommendation === "promote" ? "border-pass/40 bg-pass/[.05]" : "border-warn/40 bg-warn/[.06]")}>
              <div className={clsx("font-bold", ag.recommendation === "promote" ? "text-pass" : "text-warn")}>Agent recommends {ag.recommendation?.toUpperCase()}</div>
              <div className="mt-0.5">{ag.summary}</div>
              {ag.reasons?.length > 0 && <ul className="list-disc ml-5 text-muted mt-1">{ag.reasons.map((r: string) => <li key={r}>{r}</li>)}</ul>}
            </div>
          )}
          <div className="mt-3 space-y-2 text-[15px]">
            {ctx.summary && <div>{ctx.summary}</div>}
            {ctx.gaps?.length > 0 && <ul className="space-y-1">{ctx.gaps.map((x: string) => <li key={x} className="text-warn">▲ {x}</li>)}</ul>}
            {ctx.tokens && Object.keys(ctx.tokens).length > 0 && (
              <div className="flex flex-wrap gap-x-5 gap-y-2">{Object.entries(ctx.tokens).map(([k, t]: any) => <div key={k} className="text-sm"><span className="text-muted">{k.replace(/_/g, " ")}</span> <Ev token={t} /></div>)}</div>
            )}
            <div className="flex gap-4 text-sm">
              {ctx.report_id && <Link className="text-teal hover:underline" href={`/reports/${ctx.report_id}`}>Review the report →</Link>}
              {g.stage === "gate_validate" && <Link className="text-teal hover:underline" href={`/models/${g.model_id}/parity`}>Review the parity certificate →</Link>}
              <Link className="text-teal hover:underline" href={`/agents?run=${g.run_id}`}>Read the agent trace →</Link>
            </div>
          </div>
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment (logged to the ledger)…"
            className="mt-3 w-full rounded-lg border border-line bg-black/20 p-3 text-[15px] outline-none focus:border-teal" rows={2} />
          <div className="mt-2 flex gap-2">
            <button className="btn btn-primary" onClick={() => decide.mutate("approved")} disabled={decide.isPending}><Check size={16} /> Approve</button>
            <button className="btn" onClick={() => decide.mutate("changes_requested")} disabled={decide.isPending}><MessageSquareWarning size={16} /> Request changes</button>
            <button className="btn btn-danger" onClick={() => decide.mutate("rejected")} disabled={decide.isPending}><X size={16} /> Reject</button>
          </div>
        </div>
      </div>
    </Panel>
  );
}

export default function Approvals() {
  const qc = useQueryClient();
  const gates = useQuery({ queryKey: ["gates"], queryFn: () => get<any[]>("/api/gates"), refetchInterval: 3000 });
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [comment, setComment] = useState("");
  const pending = (gates.data || []).filter((g) => g.status === "pending");
  const done = (gates.data || []).filter((g) => g.status !== "pending");
  const chosen = pending.filter((g) => sel.has(g.id)).map((g) => g.id);
  const bulk = useMutation({ mutationFn: (decision: string) => post("/api/gates/bulk-decision", { gate_ids: chosen, decision, comment, decided_by: "Model Risk Officer" }),
    onSuccess: () => { setSel(new Set()); setComment(""); qc.invalidateQueries(); } });
  const toggle = (id: number) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  return (
    <div className="space-y-5 max-w-[1200px] mx-auto">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Approvals</h1>
        <p className="text-muted mt-1">Every stage ends at a gate. Each agent recommends promote or hold; you decide, one by one or in bulk. Every decision and comment goes to the hash-chained ledger.</p>
      </div>
      {pending.length > 0 && (
        <div className="panel px-4 py-3 flex items-center gap-3 flex-wrap sticky top-20 z-20">
          <button className="btn !py-1.5" onClick={() => setSel(new Set(pending.map((g) => g.id)))}>Select all ({pending.length})</button>
          <button className="btn !py-1.5" onClick={() => setSel(new Set(pending.filter((g) => g.context?.agent?.recommendation === "promote").map((g) => g.id)))}>Select agent-recommended</button>
          <span className="text-sm text-muted">{chosen.length} selected</span>
          <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment for all selected…" className="rounded-md border border-line bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-teal flex-1 min-w-[180px]" />
          <button className="btn btn-primary !py-1.5" disabled={!chosen.length || bulk.isPending} onClick={() => bulk.mutate("approved")}><Check size={15} /> Approve selected</button>
          <button className="btn !py-1.5" disabled={!chosen.length || bulk.isPending} onClick={() => bulk.mutate("changes_requested")}>Request changes</button>
          <button className="btn btn-danger !py-1.5" disabled={!chosen.length || bulk.isPending} onClick={() => bulk.mutate("rejected")}>Reject</button>
        </div>
      )}
      {pending.length ? pending.map((g) => <GateCard key={g.id} g={g} selected={sel.has(g.id)} toggle={() => toggle(g.id)} />) : (
        <Panel><Empty title="Nothing waiting for you">Start the factory from the Pipeline page; each finished stage parks its model here until you promote it.</Empty></Panel>
      )}
      {done.length > 0 && (
        <Panel title="Decision history" pad={false}>
          <table className="w-full text-[15px]">
            <tbody>{done.map((g) => (
              <tr key={g.id} className="border-t border-line/60">
                <td className="px-5 py-2.5 mono">{g.model_id}</td><td>{g.title}</td><td><Badge kind={g.status} /></td>
                <td className="text-muted text-sm">{g.decided_by}</td><td className="text-muted text-sm pr-5">{g.comment}</td>
              </tr>
            ))}</tbody>
          </table>
        </Panel>
      )}
    </div>
  );
}
