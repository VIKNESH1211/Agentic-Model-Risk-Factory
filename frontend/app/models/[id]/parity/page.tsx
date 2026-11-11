"use client";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { Ev } from "@/components/Evidence";
import { ModelPicker } from "@/components/ModelPicker";
import { Empty, Hash, Panel, Tag } from "@/components/ui";
import { get } from "@/lib/api";

const tt = { background: "#121a33", border: "1px solid rgba(148,163,255,.25)", borderRadius: 8, color: "#e6e9f5" };
const LABEL: Record<string, [string, string]> = {
  coef_max_abs_diff: ["Max coefficient Δ", "R vs Python"],
  score_max_abs_diff: ["Max output Δ", "every row"],
  decision_agreement: ["Decision agreement", "required 100%"],
  fuzz_rows: ["Fuzz cases", "nulls · bin edges · unseen levels"],
  fuzz_divergences: ["Fuzz divergences", "legacy vs Python"],
  fuzz_legacy_na: ["Legacy returns no decision", "found by fuzzing"],
  rows_compared: ["Rows compared", "legacy vs Python"],
  rows_scored: ["Rows scored", "by the rehosted legacy code"],
};

function Stamp({ verdict, fp }: { verdict: string; fp: string }) {
  const c = verdict === "PASS" ? "#22c55e" : verdict === "REHOSTED" ? "#60a5fa" : "#f04461";
  return (
    <motion.div key={fp} initial={{ scale: 2.6, rotate: -28, opacity: 0 }} animate={{ scale: 1, rotate: -12, opacity: 1 }}
      transition={{ type: "spring", stiffness: 210, damping: 13, delay: 0.2 }}
      className="grid place-items-center w-[230px] h-[230px] rounded-full" style={{ border: `5px double ${c}`, color: c, boxShadow: `0 0 50px ${c}55 inset` }}>
      <div className="text-center">
        <div className="text-[11px] tracking-[.35em] font-bold">{verdict === "REHOSTED" ? "REHOST" : "PARITY"}</div>
        <div className={verdict === "REHOSTED" ? "text-3xl font-black my-1" : "text-5xl font-black tracking-wider my-1"}>{verdict}</div>
        <div className="text-[11px] tracking-[.3em] font-bold">{verdict === "REHOSTED" ? "RECORDED" : "CERTIFIED"}</div>
        <div className="mono text-[10px] mt-2 opacity-80">{fp.slice(0, 16)}</div>
      </div>
    </motion.div>
  );
}

export default function Parity() {
  const { id } = useParams<{ id: string }>();
  const q = useQuery({ queryKey: ["parity", id], queryFn: () => get(`/api/models/${id}/parity`), retry: false });
  const header = (
    <div className="flex items-end justify-between flex-wrap gap-3">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Parity Certificate · <span className="mono">{id}</span></h1>
        <p className="text-muted mt-1">The unmodified legacy R code ran in a network-isolated sandbox; the Python redevelopment scored the identical rows.</p>
      </div>
      <ModelPicker current={id} hrefFor={(m) => `/models/${m}/parity`} />
    </div>
  );
  if (q.isError) return <div className="space-y-5 max-w-[1500px] mx-auto">{header}<Panel><Empty title="No certificate yet" action={<Link className="btn btn-primary" href="/">Open the pipeline →</Link>}>Promote {id} to <b>Redevelop</b>; the agent issues the certificate after comparing legacy and Python on every row.</Empty></Panel></div>;
  const d = q.data;
  if (!d) return <div className="text-muted">Loading…</div>;
  const c = d.certificate;
  const keys = Object.keys(d.tokens || {});
  return (
    <div className="space-y-5 max-w-[1500px] mx-auto">
      {header}
      <Panel pad={false}>
        <div className="grid grid-cols-1 lg:grid-cols-[300px_1fr]">
          <div className="grid place-items-center p-8 border-r border-line"><Stamp verdict={c.verdict} fp={c.fingerprint} /></div>
          <div className="p-6 space-y-5">
            <div className="grid grid-cols-2 xl:grid-cols-3 gap-6">
              {keys.map((k) => (
                <div key={k}>
                  <div className="text-sm text-muted">{LABEL[k]?.[0] ?? k}</div>
                  <div className="text-3xl mt-1"><Ev token={d.tokens[k].token} info={d.tokens[k]} /></div>
                  <div className="text-xs text-faint mt-1">{LABEL[k]?.[1]}</div>
                </div>
              ))}
            </div>
            <div className="grid md:grid-cols-2 gap-4 text-sm border-t border-line pt-4">
              <div className="space-y-1">
                <div><span className="text-muted">Legacy</span> <span className="mono">{c.legacy.file}</span> · {c.legacy.runtime} · via <Tag tone={c.legacy.execution === "docker" ? "teal" : "warn"}>{c.legacy.execution}</Tag></div>
                <div><span className="text-muted">sha256</span> <Hash v={c.legacy.sha256} n={20} /></div>
                <div><span className="text-muted">Python</span> <span className="mono">{c.python.file}</span> · {c.python.runtime}</div>
                {c.python.origin && <div><span className="text-muted">Origin</span> {c.python.origin}</div>}
                {c.python.sha256 && <div><span className="text-muted">sha256</span> <Hash v={c.python.sha256} n={20} /></div>}
              </div>
              <div className="space-y-1">
                {c.inputs?.score_sha256 && <div><span className="text-muted">Inputs</span> <Hash v={c.inputs.score_sha256} n={20} /> · {c.inputs.rows_real} rows{c.inputs.rows_fuzz ? ` + ${c.inputs.rows_fuzz} fuzz` : ""}</div>}
                <div><span className="text-muted">Fingerprint</span> <Hash v={c.fingerprint} n={20} /></div>
                <div><span className="text-muted">Signature</span> <Hash v={c.signature} n={20} /> <span className="text-xs text-faint">HMAC-SHA256 (demo key)</span></div>
                {d.exports && <div><span className="text-muted">Sandbox exports</span> <span className="mono text-xs">{d.exports.join(", ")}</span> · <Link className="text-teal hover:underline" href={`/files?root=runs&path=${d.run_id}/sandbox/out/${d.exports[0]}`}>browse</Link></div>}
              </div>
            </div>
          </div>
        </div>
      </Panel>

      {d.scatter.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
          <Panel title="Legacy output vs Python output (500 rows)" right={<Tag tone="teal">on the 45° line</Tag>}>
            <ResponsiveContainer width="100%" height={330}>
              <ScatterChart margin={{ top: 10, right: 20, bottom: 10, left: 0 }}>
                <CartesianGrid stroke="rgba(148,163,255,.08)" />
                <XAxis type="number" dataKey="legacy" name="Legacy (R)" tick={{ fill: "#8f98b8" }} />
                <YAxis type="number" dataKey="python" name="Python" tick={{ fill: "#8f98b8" }} />
                <Tooltip contentStyle={tt} />
                <ReferenceLine segment={[{ x: Math.min(...d.scatter.map((p: any) => p.legacy)), y: Math.min(...d.scatter.map((p: any) => p.legacy)) }, { x: Math.max(...d.scatter.map((p: any) => p.legacy)), y: Math.max(...d.scatter.map((p: any) => p.legacy)) }]} stroke="#a78bfa" strokeDasharray="4 4" />
                <Scatter data={d.scatter} fill="#2dd4bf" fillOpacity={0.65} />
              </ScatterChart>
            </ResponsiveContainer>
          </Panel>
          <Panel title="Residual |legacy − Python| on every row" right={<Tag tone="agent">floating-point noise</Tag>}>
            <ResponsiveContainer width="100%" height={330}>
              <BarChart data={d.residual_hist} margin={{ top: 10, right: 20, bottom: 10, left: 0 }}>
                <CartesianGrid stroke="rgba(148,163,255,.08)" /><XAxis dataKey="bin" tick={{ fill: "#8f98b8", fontSize: 11 }} /><YAxis tick={{ fill: "#8f98b8" }} />
                <Tooltip contentStyle={tt} /><Bar dataKey="count" fill="#a78bfa" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Panel>
        </div>
      )}
      {c.verdict === "REHOSTED" && (
        <Panel title="Why rehost, not translate">
          <p className="text-[15px] leading-relaxed">CR-002 is a random forest built with <span className="mono">ranger</span>. Tree-growing depends on the library's own random-number stream and split rules, so no Python library reproduces it row-for-row. The factory therefore runs the legacy code itself in the sandbox, captures its outputs through an instrumented epilogue, and validates those outputs directly. A Python challenger can be <i>re-developed</i> later as a new model with its own validation.</p>
        </Panel>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        {d.fuzz_by_kind.length > 0 && (
          <Panel title="Differential fuzzing by case type">
            <table className="w-full text-[15px]">
              <thead><tr className="text-left text-xs uppercase tracking-wider text-muted"><th className="py-2">Case type</th><th>Rows</th><th>Divergences</th><th>Legacy NA decision</th></tr></thead>
              <tbody>{d.fuzz_by_kind.map((r: any) => (
                <tr key={r.fuzz_kind} className="border-t border-line/60"><td className="py-2.5">{r.fuzz_kind.replace(/_/g, " ")}</td><td className="num">{r.rows.toLocaleString()}</td>
                  <td className={r.diverged ? "text-fail num" : "text-pass num"}>{r.diverged}</td><td className={r.legacy_na ? "text-warn num font-semibold" : "num text-muted"}>{r.legacy_na}</td></tr>
              ))}</tbody>
            </table>
          </Panel>
        )}
        {d.coefficients.length > 0 && (
          <Panel title={`Coefficients (R vs Python) · ${d.coefficients.length} terms`}>
            <div className="max-h-[420px] overflow-auto scroll-thin">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-panel-2"><tr className="text-left text-xs uppercase tracking-wider text-muted"><th className="py-2">Term</th><th>R</th><th>Python</th><th>|Δ|</th></tr></thead>
                <tbody>{d.coefficients.map((r: any) => (
                  <tr key={r.term} className="border-t border-line/60 mono"><td className="py-1.5">{r.term}</td><td>{r.legacy.toFixed(9)}</td><td>{r.python.toFixed(9)}</td><td className="text-pass">{r.abs_diff.toExponential(1)}</td></tr>
                ))}</tbody>
              </table>
            </div>
          </Panel>
        )}
      </div>
    </div>
  );
}
