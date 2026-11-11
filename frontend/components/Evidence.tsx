"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, FlaskConical, Link2, RotateCw, X, XCircle } from "lucide-react";
import Link from "next/link";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { get, post, type TokenInfo } from "@/lib/api";
import { useFactory } from "@/lib/store";
import { Hash, Tag } from "./ui";

/** A number in a report. Click to open the evidence drawer. */
export function Ev({ token, info, fallback }: { token: string; info?: TokenInfo; fallback?: string }) {
  const open = useFactory((s) => s.openEvidence);
  const q = useQuery({ queryKey: ["ev-mini", token], queryFn: () => get(`/api/evidence/${token}`), enabled: !info, staleTime: 60_000 });
  const display = info?.display ?? q.data?.display ?? fallback ?? "…";
  const ok = info ? info.ok : !q.isError;
  return (
    <button type="button" className={ok ? "pill" : "pill pill-missing"} onClick={() => open(token)} title={info?.definition || q.data?.definition || "Show evidence"}
      aria-label={`Evidence for ${display}`}>
      {display}
    </button>
  );
}

const tooltipStyle = { background: "#121a33", border: "1px solid rgba(148,163,255,.25)", borderRadius: 8, color: "#e6e9f5" };

function Chart({ chart }: { chart: any }) {
  if (!chart) return null;
  if (chart.kind === "roc")
    return (
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={chart.points} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid stroke="rgba(148,163,255,.08)" />
          <XAxis dataKey="fpr" type="number" domain={[0, 1]} tick={{ fill: "#8f98b8", fontSize: 11 }} />
          <YAxis domain={[0, 1]} tick={{ fill: "#8f98b8", fontSize: 11 }} />
          <Tooltip contentStyle={tooltipStyle} />
          <Area type="monotone" dataKey="tpr" stroke="#2dd4bf" fill="rgba(45,212,191,.18)" strokeWidth={2} name="TPR" />
        </AreaChart>
      </ResponsiveContainer>
    );
  if (chart.kind === "calibration")
    return (
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={chart.points} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid stroke="rgba(148,163,255,.08)" />
          <XAxis dataKey="decile" tick={{ fill: "#8f98b8", fontSize: 11 }} />
          <YAxis tick={{ fill: "#8f98b8", fontSize: 11 }} />
          <Tooltip contentStyle={tooltipStyle} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line dataKey="predicted" stroke="#a78bfa" strokeWidth={2} dot={false} />
          <Line dataKey="observed" stroke="#2dd4bf" strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    );
  if (chart.kind === "dist")
    return (
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={chart.points} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid stroke="rgba(148,163,255,.08)" />
          <XAxis dataKey="bin" tick={{ fill: "#8f98b8", fontSize: 10 }} />
          <YAxis tick={{ fill: "#8f98b8", fontSize: 11 }} />
          <Tooltip contentStyle={tooltipStyle} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="base" fill="#60a5fa" name="development" />
          <Bar dataKey="comp" fill="#f5a524" name="comparison" />
        </BarChart>
      </ResponsiveContainer>
    );
  return null;
}

export function EvidenceDrawer() {
  const token = useFactory((s) => s.evidenceToken);
  const close = useFactory((s) => s.openEvidence);
  const q = useQuery({ queryKey: ["evidence", token], queryFn: () => get(`/api/evidence/${token}`), enabled: !!token });
  const rep = useMutation({ mutationFn: () => post(`/api/evidence/${token}/reproduce`) });
  const d = q.data;
  return (
    <AnimatePresence>
      {token && (
        <>
          <motion.div className="fixed inset-0 z-40 bg-black/50" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={() => { close(null); rep.reset(); }} />
          <motion.aside role="dialog" aria-label="Evidence" className="fixed right-0 top-0 z-50 h-full w-full max-w-[560px] overflow-y-auto scroll-thin border-l border-line-strong bg-ink-2 p-6"
            initial={{ x: 600 }} animate={{ x: 0 }} exit={{ x: 600 }} transition={{ type: "spring", damping: 30, stiffness: 260 }}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="panel-title flex items-center gap-2"><FlaskConical size={14} /> Evidence</div>
                <div className="mono text-sm text-muted mt-1 break-all">{token}</div>
              </div>
              <button className="btn !p-2" onClick={() => { close(null); rep.reset(); }} aria-label="Close"><X size={18} /></button>
            </div>
            {q.isLoading && <div className="mt-8 text-muted">Loading…</div>}
            {q.isError && <div className="mt-8 text-fail">Metric not found in the metric store.</div>}
            {d && (
              <div className="mt-5 space-y-5">
                <div className="flex items-end justify-between gap-4">
                  <div>
                    <div className="text-muted text-sm">{d.name}</div>
                    <div className="text-5xl font-bold num mono text-teal">{d.display}</div>
                  </div>
                  <AnimatePresence mode="wait">
                    {rep.data && (
                      <motion.div key="r" initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
                        className={`flex items-center gap-2 rounded-lg border px-3 py-2 font-semibold ${rep.data.match === false ? "border-fail/50 text-fail bg-fail/10" : "border-pass/50 text-pass bg-pass/10"}`}>
                        {rep.data.match === false ? <XCircle size={18} /> : <CheckCircle2 size={18} />}
                        {rep.data.match === null ? "Measured value" : rep.data.match ? "Reproduced" : "Mismatch"}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
                <dl className="grid grid-cols-[120px_1fr] gap-y-2 text-sm">
                  <dt className="text-muted">Definition</dt><dd>{d.definition}</dd>
                  {d.split && <><dt className="text-muted">Sample</dt><dd>{d.split}{d.slice ? ` · ${d.slice}` : ""}</dd></>}
                  <dt className="text-muted">Run</dt><dd className="mono">{d.run?.id} · {d.run?.kind} · stage {d.run?.stage}</dd>
                  <dt className="text-muted">Code hash</dt><dd><Hash v={d.code_hash} n={14} /></dd>
                  <dt className="text-muted">Data hash</dt><dd><Hash v={d.data_hash} n={14} /></dd>
                  <dt className="text-muted">Artifact</dt><dd className="mono text-xs break-all text-muted">{d.artifact || "—"}</dd>
                  <dt className="text-muted">Ledger</dt>
                  <dd>{d.ledger ? <Link href={`/governance?seq=${d.ledger.seq}`} className="text-teal hover:underline inline-flex items-center gap-1"><Link2 size={13} />#{d.ledger.seq} {d.ledger.action}</Link> : "—"}</dd>
                </dl>
                <Chart chart={d.chart} />
                <div>
                  <div className="panel-title mb-2">Function that computed it</div>
                  <pre className="mono text-[12.5px] leading-relaxed bg-black/30 border border-line rounded-lg p-3 overflow-x-auto scroll-thin text-[#cbd3ff]">{d.source}</pre>
                </div>
                <div>
                  <div className="panel-title mb-2">Recipe <Tag tone="agent">stored</Tag></div>
                  <pre className="mono text-[12px] bg-black/30 border border-line rounded-lg p-3 overflow-x-auto scroll-thin text-muted">{JSON.stringify(d.recipe, null, 2)}</pre>
                </div>
                <div className="flex items-center gap-3 pt-1">
                  <button className="btn btn-primary" onClick={() => rep.mutate()} disabled={rep.isPending}>
                    <RotateCw size={16} className={rep.isPending ? "animate-spin" : ""} /> Reproduce
                  </button>
                  {rep.data && rep.data.match !== null && (
                    <div className="text-sm text-muted">
                      recomputed <span className="mono text-text">{Number(rep.data.recomputed).toPrecision(8)}</span> · Δ <span className="mono">{rep.data.abs_diff}</span> ·
                      data {rep.data.data_hash_match ? "✓" : "✗"} · code {rep.data.code_hash_match ? "✓" : "✗"} · {rep.data.elapsed_ms} ms
                    </div>
                  )}
                  {rep.data?.note && <div className="text-sm text-muted">{rep.data.note}</div>}
                </div>
              </div>
            )}
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
