"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { motion } from "framer-motion";
import { Link2, ShieldAlert, ShieldCheck, Skull } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Badge, Panel, Tag } from "@/components/ui";
import { get, post } from "@/lib/api";

const CELL: Record<string, string> = { pass: "bg-pass/20 text-pass border-pass/40", warn: "bg-warn/15 text-warn border-warn/40", fail: "bg-fail/20 text-fail border-fail/40", "n/a": "bg-white/[.02] text-faint border-line" };
const SYM: Record<string, string> = { pass: "✓", warn: "!", fail: "✗", "n/a": "–" };

function Gov() {
  const qc = useQueryClient();
  const sp = useSearchParams();
  const focus = Number(sp.get("seq") || 0);
  const cov = useQuery({ queryKey: ["coverage"], queryFn: () => get("/api/controls/coverage") });
  const led = useQuery({ queryKey: ["ledger"], queryFn: () => get("/api/ledger?limit=400") });
  const [verify, setVerify] = useState<any>(null);
  const ver = useMutation({ mutationFn: () => post("/api/ledger/verify"), onSuccess: (v) => { setVerify(v); qc.invalidateQueries({ queryKey: ["coverage"] }); } });
  const tam = useMutation({ mutationFn: () => post("/api/ledger/_tamper"), onSuccess: () => { setVerify(null); qc.invalidateQueries({ queryKey: ["ledger"] }); } });
  const [sel, setSel] = useState<any>(null);
  const strip = useRef<HTMLDivElement>(null);
  const entries: any[] = led.data?.entries || [];
  const broken = verify && !verify.ok ? verify.broken_at : null;

  useEffect(() => {
    const target = broken || focus;
    if (target && strip.current) {
      const el = strip.current.querySelector(`[data-seq="${target}"]`) as HTMLElement | null;
      el?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
      if (focus && !sel) setSel(entries.find((e) => e.seq === focus));
    } else if (strip.current) strip.current.scrollLeft = strip.current.scrollWidth;
  }, [broken, focus, entries.length]); // eslint-disable-line

  return (
    <div className="space-y-5 max-w-[1600px] mx-auto">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Controls & Audit Ledger</h1>
        <p className="text-muted mt-1">SS1/23 principles as executable controls, and a hash-chained record of every agent action, metric batch, finding and human decision.</p>
      </div>

      <Panel title="SS1/23 control coverage" right={<span className="text-xs text-muted">{cov.data?.disclaimer}</span>}>
        {cov.data && (
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full text-sm border-separate border-spacing-1">
              <thead>
                <tr><th className="text-left text-xs text-muted font-semibold">Control</th>{cov.data.models.map((m: string) => <th key={m} className="mono text-xs text-muted">{m}</th>)}</tr>
              </thead>
              <tbody>
                {cov.data.controls.map((c: any) => (
                  <tr key={c.ref}>
                    <td className="pr-4 py-1"><span className="mono text-muted mr-2">{c.ref}</span>{c.title}<div className="text-xs text-faint">{c.principle}</div></td>
                    {cov.data.models.map((m: string) => {
                      const r = cov.data.matrix[m][c.ref];
                      return <td key={m} className={clsx("text-center rounded-md border font-bold w-[84px]", CELL[r.status])} title={JSON.stringify(r.evidence)}>{SYM[r.status]} <span className="text-[11px] font-semibold">{r.status}</span></td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title={<>Hash-chained ledger · {led.data?.total ?? 0} entries</>} right={
        <div className="flex gap-2">
          <button className="btn btn-primary" onClick={() => ver.mutate()} disabled={ver.isPending}><ShieldCheck size={16} /> Verify chain</button>
          <button className="btn btn-danger" onClick={() => tam.mutate()} disabled={tam.isPending} title="Demo only: edits one stored entry without fixing the hashes"><Skull size={16} /> Tamper (demo)</button>
        </div>}>
        {verify && (
          <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
            className={clsx("mb-4 rounded-lg border px-4 py-3 flex items-center gap-3 text-[15px]", verify.ok ? "border-pass/50 bg-pass/10 text-pass" : "border-fail/60 bg-fail/10 text-fail glow-fail")}>
            {verify.ok ? <ShieldCheck /> : <ShieldAlert />}
            {verify.ok ? <>Chain intact — {verify.checked} entries recomputed, head <span className="mono">{verify.head.slice(0, 16)}…</span></>
              : <>Chain BROKEN at entry #{verify.broken_at}: {verify.reason}. Every later block is now untrusted.</>}
          </motion.div>
        )}
        <div ref={strip} className="flex items-center gap-0 overflow-x-auto scroll-thin pb-3">
          {entries.map((e, i) => {
            const bad = broken && e.seq >= broken;
            const first = broken === e.seq;
            return (
              <div key={e.seq} className="flex items-center" data-seq={e.seq}>
                {i > 0 && <Link2 size={14} className={clsx("mx-0.5 shrink-0", bad ? "text-fail" : "text-faint")} />}
                <motion.button onClick={() => setSel(e)} animate={first ? { x: [0, -5, 5, -3, 3, 0] } : {}} transition={{ duration: 0.5 }}
                  className={clsx("shrink-0 w-[132px] rounded-lg border px-2.5 py-2 text-left transition",
                    bad ? "border-fail/70 bg-fail/15" : "border-line bg-white/[.03] hover:border-teal/50",
                    first && "glow-fail", (sel?.seq === e.seq || focus === e.seq) && !bad && "border-teal glow-teal")}>
                  <div className="flex justify-between text-[11px]"><span className="mono font-bold">#{e.seq}</span><span className="text-faint">{e.actor.slice(0, 10)}</span></div>
                  <div className="text-[12px] truncate mt-0.5">{e.action.replace(/_/g, " ")}</div>
                  <div className={clsx("mono text-[10px] mt-1", bad ? "text-fail" : "text-agent/80")}>{e.entry_hash.slice(0, 12)}</div>
                </motion.button>
              </div>
            );
          })}
        </div>
        {sel && (
          <div className="mt-4 grid md:grid-cols-2 gap-4 text-sm">
            <div className="space-y-1">
              <div className="font-semibold text-base">#{sel.seq} {sel.action} <Tag>{sel.actor}</Tag></div>
              <div><span className="text-muted">time</span> {new Date(sel.ts * 1000).toLocaleString()}</div>
              <div className="break-all"><span className="text-muted">prev_hash</span> <span className="mono text-xs">{sel.prev_hash}</span></div>
              <div className="break-all"><span className="text-muted">entry_hash</span> <span className="mono text-xs text-agent">{sel.entry_hash}</span></div>
              <div className="break-all"><span className="text-muted">payload_hash</span> <span className="mono text-xs">{sel.payload_hash}</span></div>
              {broken === sel.seq && <Badge kind="fail" label="payload no longer matches its hash" />}
            </div>
            <pre className="mono text-[12px] bg-black/30 border border-line rounded-lg p-3 overflow-auto max-h-[240px] scroll-thin">{JSON.stringify(sel.payload, null, 2)}</pre>
          </div>
        )}
        <p className="text-xs text-faint mt-3">entry_hash = sha256(prev_hash + {"{ts, actor, action, payload_hash}"}). Editing any stored payload or entry breaks every hash after it. Reset the demo to restore a clean chain.</p>
      </Panel>
    </div>
  );
}

export default function Governance() {
  return <Suspense><Gov /></Suspense>;
}
