"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowRight, Check, Copy, FileCode2, RotateCcw, Server, ShieldAlert, ShieldCheck, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { get, patch, post, STAGE_LABEL } from "@/lib/api";
import { toast } from "@/lib/store";
import { AgentTrace } from "../AgentTrace";
import { Ev } from "../Evidence";
import { Badge, CodeBlock, Dot, Empty, Panel, Skeleton, Tag, ago, inputCls } from "../ui";

const LIFECYCLE = ["discover", "gate_document", "document", "gate_redevelop", "redevelop", "gate_validate", "validate", "report", "gate_deploy", "monitor_setup"];

export function Overview({ d, setTab }: { d: any; setTab: (t: any) => void }) {
  const qc = useQueryClient();
  const m = d.model;
  const meta = m.meta || {};
  const lc = meta.lifecycle || {};
  const gate = useQuery({ queryKey: ["gates", m.id], queryFn: () => get<any[]>(`/api/gates?model_id=${m.id}&status=pending`), refetchInterval: 4000 });
  const g = gate.data?.[0];
  const [comment, setComment] = useState("");
  const decide = useMutation({ mutationFn: (decision: string) => post(`/api/gates/${g.id}/decision`, { decision, comment, decided_by: "Model Risk Officer" }),
    onSuccess: (_r, x) => { qc.invalidateQueries(); toast({ kind: "success", text: `${m.id}: ${x.replace("_", " ")}` }); setComment(""); },
    onError: (e: any) => toast({ kind: "error", text: e.message }) });
  const start = useMutation({ mutationFn: () => post(`/api/models/${m.id}/start`), onSuccess: () => qc.invalidateQueries(), onError: (e: any) => toast({ kind: "error", text: e.message }) });
  const deploy = useMutation({ mutationFn: () => post(`/api/traffic/${m.id}/deploy`), onSuccess: () => { qc.invalidateQueries(); toast({ kind: "success", text: `${m.id} is serving traffic again` }); },
    onError: (e: any) => toast({ kind: "error", text: e.message }) });
  const idx = LIFECYCLE.indexOf(lc.stage);
  const spec = d.spec?.body;
  const latestReport = d.reports.at(-1);
  return (
    <div className="grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-5">
      <div className="space-y-5">
        <Panel title="Lifecycle">
          <div className="flex items-center gap-1 overflow-x-auto scroll-thin pb-1">
            {LIFECYCLE.map((s, i) => {
              const done = idx > i || (idx === i && lc.status === "done");
              const cur = idx === i && lc.status !== "done";
              return (
                <div key={s} className="flex items-center gap-1 shrink-0">
                  <div className={clsx("rounded-lg border px-2.5 py-1.5 text-[12px] whitespace-nowrap", s.startsWith("gate") && "border-dashed",
                    done ? "border-teal/50 text-teal bg-teal/[.06]" : cur ? (lc.status === "running" ? "border-agent text-agent glow-agent" : lc.status === "awaiting" ? "border-warn text-warn" : "border-fail text-fail") : "border-line text-faint")}>
                    {s.startsWith("gate") ? "⏸ " : ""}{STAGE_LABEL[s]}
                  </div>
                  {i < LIFECYCLE.length - 1 && <ArrowRight size={12} className="text-faint" />}
                </div>
              );
            })}
          </div>
          {lc.status === "failed" && <div className="mt-3 text-sm text-fail">Failed: {lc.error}</div>}
          {(!lc.stage || lc.stage === "onboarded" || ["failed", "rejected"].includes(lc.status)) &&
            <button className="btn btn-primary mt-3" onClick={() => start.mutate()} disabled={start.isPending}>Start the factory for {m.id}</button>}
        </Panel>
        {g && (
          <Panel className="glow-teal" title={<span className="text-warn">⏸ Waiting for you · {g.title}</span>}>
            {g.context?.agent && (
              <div className={clsx("rounded-lg border px-3 py-2.5 text-[14px]", g.context.agent.recommendation === "promote" ? "border-pass/40 bg-pass/[.05]" : "border-warn/40 bg-warn/[.06]")}>
                <b className={g.context.agent.recommendation === "promote" ? "text-pass" : "text-warn"}>Agent recommends {g.context.agent.recommendation?.toUpperCase()}</b>
                <div className="mt-0.5">{g.context.agent.summary}</div>
                {g.context.agent.reasons?.length > 0 && <ul className="list-disc ml-5 text-muted mt-1 text-[13px]">{g.context.agent.reasons.map((r: string) => <li key={r}>{r}</li>)}</ul>}
              </div>
            )}
            {g.context?.blocked && <div className="mt-3 rounded-lg border border-fail/50 bg-fail/[.07] px-3 py-2 text-sm"><b className="text-fail">⛔ This stage is incomplete — it can't be approved.</b> {g.context.blocked.join("; ")}. Send it back (your comment goes to the agent) or reject.</div>}
            {g.context?.summary && <p className="mt-3 text-sm">{g.context.summary}</p>}
            {g.context?.tokens && <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1.5 text-sm">{Object.entries(g.context.tokens).map(([k, t]: any) => <span key={k}><span className="text-muted">{k.replace(/[._]/g, " ")}</span> <Ev token={t} /></span>)}</div>}
            <div className="mt-3 flex gap-3 text-sm">
              {g.stage === "gate_document" && <button className="text-teal hover:underline" onClick={() => setTab("spec")}>Review the spec →</button>}
              {g.stage === "gate_redevelop" && <><button className="text-teal hover:underline" onClick={() => setTab("validation")}>Validation plan →</button><button className="text-teal hover:underline" onClick={() => setTab("monitoring")}>Monitoring plan →</button><button className="text-teal hover:underline" onClick={() => setTab("docs")}>Documentation →</button></>}
              {g.stage === "gate_validate" && <button className="text-teal hover:underline" onClick={() => setTab("parity")}>Parity certificate →</button>}
              {g.context?.report_id && <Link className="text-teal hover:underline" href={`/reports/${g.context.report_id}`}>Validation report →</Link>}
            </div>
            <textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment — logged to the ledger; on 'Send back' the agent reads it" className={clsx(inputCls, "mt-3 min-h-[60px]")} />
            <div className="mt-2 flex gap-2">
              <button className="btn btn-primary" onClick={() => decide.mutate("approved")} disabled={decide.isPending || !!g.context?.blocked}><Check size={16} /> Approve</button>
              <button className="btn" onClick={() => decide.mutate("changes_requested")} disabled={decide.isPending}><RotateCcw size={16} /> Send back to the agent</button>
              <button className="btn btn-danger" onClick={() => decide.mutate("rejected")} disabled={decide.isPending}><X size={16} /> Reject</button>
            </div>
          </Panel>
        )}
        {spec && (
          <Panel title="Specification at a glance" right={<button className="text-xs text-teal hover:underline" onClick={() => setTab("spec")}>open spec v{d.spec.version}</button>}>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              {[["Task", spec.task], ["Strategy", spec.strategy], ["Target", spec.target || "—"], ["Decision", spec.decision?.kind + (spec.decision?.cutoff != null ? ` (${spec.decision.op} ${spec.decision.cutoff})` : "")],
                ["Features", spec.features?.length], ["Groups", (spec.groups || []).map((x: any) => x.name).join(", ") || "—"], ["Entry", spec.entry_script], ["Deployable", spec.deployable ? "yes" : "no"]].map(([k, v]) => (
                <div key={k as string}><div className="text-[11px] uppercase tracking-wider text-muted">{k}</div><div className="mono text-[13px] mt-0.5 break-words">{String(v)}</div></div>
              ))}
            </div>
            {spec.purpose && <p className="text-sm text-slate-700 mt-4">{spec.purpose}</p>}
          </Panel>
        )}
      </div>
      <div className="space-y-5">
        <Panel title="Status">
          <ul className="text-sm space-y-2">
            <li className="flex justify-between"><span className="text-muted">Lifecycle</span><span>{STAGE_LABEL[lc.stage] || lc.stage || "onboarded"} · {lc.status || "idle"}</span></li>
            <li className="flex justify-between"><span className="text-muted">Implementation</span><span>{meta.parity_verdict ? <Badge kind={meta.parity_verdict === "PASS" ? "PASS" : "warn"} label={meta.parity_verdict} /> : "—"}</span></li>
            <li className="flex justify-between"><span className="text-muted">Validated</span><span>{meta.validated_run_id ? <Link className="mono text-teal" href={`/reports/rep_${meta.validated_run_id}`}>{meta.validated_run_id}</Link> : "—"}</span></li>
            <li className="flex justify-between items-center"><span className="text-muted">Live</span><span>{meta.deployed ? <Link href={`/monitoring?model=${m.id}`} className="flex items-center gap-1.5 text-pass"><Dot tone="pass" pulse /> serving</Link>
              : meta.validated_run_id && meta.parity_verdict === "PASS" ? <button className="btn !py-1 !px-2 text-xs" onClick={() => deploy.mutate()} disabled={deploy.isPending}>Put back into service</button> : "—"}</span></li>
            <li className="flex justify-between"><span className="text-muted">Findings</span><span>{d.findings.length} ({d.findings.filter((f: any) => f.severity === "high").length} high)</span></li>
          </ul>
        </Panel>
        <Panel title="Lineage">
          <div className="text-sm space-y-2">
            <div><span className="text-muted">Upstream:</span> {d.upstream.length ? d.upstream.map((u: string) => <Link key={u} href={`/models/${u}`} className="mono text-teal mr-2">{u}</Link>) : "—"}</div>
            <div><span className="text-muted">Downstream:</span> {d.downstream.length ? d.downstream.map((u: string) => <Link key={u} href={`/models/${u}`} className="mono text-teal mr-2">{u}</Link>) : "—"}</div>
            <div><span className="text-muted">Blast radius:</span> {d.blast_radius.length ? d.blast_radius.join(", ") : "none"}</div>
          </div>
        </Panel>
        <Panel title="Reports">
          {d.reports.length ? d.reports.map((r: any) => (
            <Link key={r.id} href={`/reports/${r.id}`} className="flex items-center justify-between py-1.5 text-sm hover:text-teal">
              <span>v{r.version} · <span className="mono text-xs">{r.run_id}</span></span>{r.checker_ok ? <Badge kind="pass" label="traceable" /> : <Badge kind="warn" label="check" />}
            </Link>
          )) : <div className="text-sm text-muted">None yet.</div>}
          {latestReport && <Link href={`/reports/${latestReport.id}`} className="btn mt-2 w-full justify-center">Open latest report</Link>}
        </Panel>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- parity certificate
const sci = (v?: number | null) => (v == null || Number.isNaN(v) ? "—" : v === 0 ? "0" : v.toExponential(1));
const pct = (v?: number | null) => (v == null ? "—" : `${(v * 100).toFixed(v === 1 ? 0 : 2)}%`);
const chartTip = { background: "#ffffff", border: "1px solid rgba(15,23,42,.12)", borderRadius: 8, fontSize: 12 };
const axisTick = { fill: "#64748b", fontSize: 11 };

/** How far under the tolerance a difference sits, in plain words. */
function headroom(diff?: number | null, tol?: number) {
  if (diff == null || tol == null) return null;
  if (diff === 0) return "exact match";
  if (diff > tol) return `${(diff / tol).toFixed(1)}× over tolerance`;
  const orders = Math.floor(Math.log10(tol / diff));
  return orders >= 1 ? `${orders} order${orders > 1 ? "s" : ""} of magnitude under tolerance` : "within tolerance";
}

function ParityCheck({ label, ok, value, token, target, note }: {
  label: string; ok: boolean | null; value: string; token?: string; target: string; note?: string | null;
}) {
  return (
    <div className={clsx("panel px-4 py-3.5 border-l-[3px]", ok === null ? "border-l-line" : ok ? "border-l-pass" : "border-l-fail")}>
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] uppercase tracking-[.14em] text-muted font-semibold">{label}</div>
        {ok === null ? <Badge kind="n/a" /> : <Badge kind={ok ? "pass" : "fail"} />}
      </div>
      <div className="mt-1.5 text-xl font-bold num">{token ? <Ev token={token} fallback={value} /> : value}</div>
      <div className="text-xs text-muted mt-1">target {target}</div>
      {note && <div className={clsx("text-xs mt-0.5", ok === false ? "text-fail" : "text-pass")}>{note}</div>}
    </div>
  );
}

function CopyHash({ v }: { v: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" title="Copy full fingerprint" className="inline-flex items-center gap-1.5 mono text-[12.5px] text-agent/90 hover:text-agent"
      onClick={() => { navigator.clipboard?.writeText(v); setDone(true); setTimeout(() => setDone(false), 1500); }}>
      {v.slice(0, 16)}…{v.slice(-6)} {done ? <Check size={13} className="text-pass" /> : <Copy size={13} />}
    </button>
  );
}

export function ParityView({ modelId }: { modelId: string }) {
  const q = useQuery({ queryKey: ["parity", modelId], queryFn: () => get(`/api/models/${modelId}/parity`), retry: false });
  const [code, setCode] = useState<"python" | "epilogue">("python");
  if (q.isError) return <Panel><Empty title="No parity certificate yet">The redevelopment agent issues it after the legacy export and the Python translation match row for row.</Empty></Panel>;
  if (!q.data) return <div className="space-y-5"><Skeleton className="h-36" /><div className="grid grid-cols-2 xl:grid-cols-4 gap-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}</div><Skeleton className="h-80" /></div>;

  const d = q.data;
  const c = d.certificate;
  const p = c.parity || {};
  const tol = c.tolerances || { scores: 1e-6, coefficients: 1e-6 };
  const tok = d.tokens || {};
  const rehosted = c.verdict === "REHOSTED";
  const pass = c.verdict === "PASS";
  const rows = p.rows ?? c.bundle?.rows;
  const compared = p.rows_compared;

  const checks = [
    { label: "Scores", ok: p.score_max_abs_diff == null ? null : p.score_max_abs_diff <= tol.scores, value: sci(p.score_max_abs_diff),
      token: tok.score_max_abs_diff, target: `max |Δ| ≤ ${sci(tol.scores)}`, note: headroom(p.score_max_abs_diff, tol.scores) },
    { label: "Coefficients", ok: p.coef_max_abs_diff == null ? null : p.coef_max_abs_diff <= tol.coefficients, value: sci(p.coef_max_abs_diff),
      token: tok.coef_max_abs_diff, target: `max |Δ| ≤ ${sci(tol.coefficients)}`,
      note: p.coef_max_abs_diff == null ? "model exports no coefficients" : headroom(p.coef_max_abs_diff, tol.coefficients) },
    { label: "Decisions", ok: p.decision_agreement == null ? null : p.decision_agreement >= 1, value: pct(p.decision_agreement),
      token: tok.decision_agreement, target: "100% agreement", note: p.decision_agreement == null ? "model makes no decision" : p.decision_agreement >= 1 ? "every row agrees" : null },
    { label: "Coverage", ok: compared == null || !rows ? null : compared === rows, value: compared == null ? "—" : compared.toLocaleString(),
      token: tok.rows_compared, target: `all ${rows?.toLocaleString() ?? "—"} rows scored by both`,
      note: compared != null && rows ? (compared === rows ? "no row left out" : `${(rows - compared).toLocaleString()} rows not compared`) : null },
  ];

  const scatter = d.sample?.scatter || [];
  const lo = scatter.length ? Math.min(...scatter.map((r: any) => Math.min(r.legacy_score, r.py_score))) : 0;
  const hi = scatter.length ? Math.max(...scatter.map((r: any) => Math.max(r.legacy_score, r.py_score))) : 1;
  const tolExp = Math.log10(tol.scores);
  const hist = (Array.isArray(d.sample?.hist) ? d.sample.hist : []).filter((b: any) => typeof b === "object")
    .map((b: any) => ({ ...b, label: `1e${Math.round((b.lo + b.hi) / 2)}`, over: b.hi > tolExp }));
  const coef = (d.coef || []).map((r: any) => ({ ...r, diff: r.python != null && r.legacy != null ? Math.abs(r.legacy - r.python) : null }));

  return (
    <div className="space-y-5">
      {/* Certificate header */}
      <section className={clsx("panel p-5", pass && "glow-teal")}>
        <div className="flex items-start gap-5 flex-wrap">
          <div className={clsx("rounded-2xl p-3.5 shrink-0", pass ? "bg-pass/10 text-pass" : rehosted ? "bg-info/10 text-info" : "bg-warn/10 text-warn")}>
            {pass ? <ShieldCheck size={40} /> : rehosted ? <Server size={40} /> : <ShieldAlert size={40} />}
          </div>
          <div className="flex-1 min-w-[260px]">
            <div className="text-[11px] uppercase tracking-[.16em] text-muted font-semibold">Parity certificate · {c.model_id}</div>
            <div className={clsx("text-3xl font-black tracking-tight leading-tight mt-0.5", pass ? "text-pass" : rehosted ? "text-info" : "text-warn")}>{c.verdict}</div>
            <p className="text-[15px] mt-1.5 max-w-3xl">
              {pass ? <>The Python translation reproduces the legacy R model on {compared != null ? <b>{compared.toLocaleString()}</b> : "every"} row{compared === 1 ? "" : "s"}, within {sci(tol.scores)} on scores{p.coef_max_abs_diff != null && <> and {sci(tol.coefficients)} on coefficients</>}{p.decision_agreement != null && <>, with identical decisions</>}.</>
                : rehosted ? <>The legacy R code was rehosted as is rather than translated, so there is no row-by-row comparison. {c.reason}</>
                : <>The translation did not meet every tolerance. Review the checks below before approving.</>}
            </p>
          </div>
        </div>
        <dl className="mt-5 pt-4 border-t border-line grid grid-cols-2 md:grid-cols-4 gap-x-6 gap-y-3 text-sm">
          {([
            ["Implementation", c.implementation],
            ["Export", c.export || "—"],
            ["Legacy run", c.legacy_run || "—"],
            ["Strategy", c.strategy || "—"],
            ["Spec", `v${c.spec_version}`],
            ["Run", <span key="r" className="mono">{c.run_id}</span>],
            ["Drafts", `${c.attempts?.export ?? 0} export · ${c.attempts?.translation ?? 0} translation`],
            ["Fingerprint", c.fingerprint ? <CopyHash key="f" v={c.fingerprint} /> : "—"],
          ] as [string, React.ReactNode][]).map(([k, v]) => (
            <div key={k} className="min-w-0"><dt className="text-[11px] uppercase tracking-wider text-muted">{k}</dt><dd className="mt-0.5 break-words">{v}</dd></div>
          ))}
        </dl>
        {!rehosted && c.reason && <p className="mt-3 text-sm text-muted"><span className="font-medium text-text">Why this strategy:</span> {c.reason}</p>}
      </section>

      {/* Acceptance checks */}
      {rehosted ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <ParityCheck label="Rows scored by legacy" ok={null} value={c.bundle?.scored?.toLocaleString() ?? "—"} token={tok.rows_scored} target="rehosted — no comparison" />
          <ParityCheck label="Legacy runtime" ok={null} value="—" token={tok.legacy_runtime_s} target="measured in the R sandbox" />
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">{checks.map((x) => <ParityCheck key={x.label} {...x} />)}</div>
      )}

      {/* Evidence charts */}
      {!rehosted && d.sample && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
          <Panel title="Legacy R vs Python scores" right={<span className="text-xs text-muted">{scatter.length} of {d.sample.rows?.toLocaleString() ?? "—"} rows · dashed line = identical</span>}>
            <ResponsiveContainer width="100%" height={300}>
              <ScatterChart margin={{ top: 10, right: 12, bottom: 18, left: 4 }}>
                <CartesianGrid stroke="rgba(15,23,42,.07)" />
                <XAxis dataKey="legacy_score" name="Legacy R" type="number" domain={[lo, hi]} tick={axisTick} tickFormatter={(v) => +v.toFixed(3) + ""}
                  label={{ value: "legacy R score", position: "insideBottom", offset: -10, fill: "#64748b", fontSize: 11 }} />
                <YAxis dataKey="py_score" name="Python" type="number" domain={[lo, hi]} tick={axisTick} tickFormatter={(v) => +v.toFixed(3) + ""}
                  label={{ value: "Python score", angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 11 }} />
                <ReferenceLine segment={[{ x: lo, y: lo }, { x: hi, y: hi }]} stroke="#94a3b8" strokeDasharray="4 4" ifOverflow="extendDomain" />
                <Tooltip contentStyle={chartTip} formatter={(v: any) => (typeof v === "number" ? v.toFixed(6) : v)} cursor={{ strokeDasharray: "3 3" }} />
                <Scatter data={scatter} fill="#0d9488" fillOpacity={0.55} />
              </ScatterChart>
            </ResponsiveContainer>
          </Panel>
          <Panel title="How far apart are the scores?" right={<span className="text-xs text-muted">max |Δ| {sci(d.sample.max)} · tolerance {sci(tol.scores)}</span>}>
            {hist.length ? (
              <>
                <ResponsiveContainer width="100%" height={270}>
                  <BarChart data={hist} margin={{ top: 10, right: 12, bottom: 18, left: 4 }}>
                    <CartesianGrid stroke="rgba(15,23,42,.07)" vertical={false} />
                    <XAxis dataKey="label" tick={axisTick} label={{ value: "|legacy − Python| per row (log scale)", position: "insideBottom", offset: -10, fill: "#64748b", fontSize: 11 }} />
                    <YAxis tick={axisTick} allowDecimals={false} />
                    <Tooltip contentStyle={chartTip} formatter={(v: any) => [`${v} rows`, "count"]}
                      labelFormatter={(_l, pl: any) => { const b = pl?.[0]?.payload; return b ? `${sci(10 ** b.lo)} – ${sci(10 ** b.hi)}` : ""; }} />
                    <Bar dataKey="n" radius={[3, 3, 0, 0]}>{hist.map((b: any, i: number) => <Cell key={i} fill={b.over ? "#dc2626" : "#0d9488"} />)}</Bar>
                  </BarChart>
                </ResponsiveContainer>
                <p className="text-xs text-muted mt-1">
                  {d.sample.exact > 0 && <>{d.sample.exact.toLocaleString()} rows match exactly and aren't plotted. </>}
                  {hist.some((b: any) => b.over) ? <span className="text-fail">Red bars are over the {sci(tol.scores)} tolerance.</span> : <>Every row sits under the {sci(tol.scores)} tolerance — differences are floating-point noise.</>}
                </p>
              </>
            ) : <Empty title="Every row matches exactly">Legacy R and Python produced bit-identical scores on all {d.sample.rows?.toLocaleString()} rows.</Empty>}
          </Panel>
        </div>
      )}

      {!rehosted && coef.length > 0 && (
        <Panel title={`Coefficients · ${coef.length}`} pad={false} right={<span className="text-xs text-muted">tolerance {sci(tol.coefficients)}</span>}>
          <div className="max-h-[360px] overflow-auto scroll-thin">
            <table className="w-full text-[13px]">
              <thead className="sticky top-0 bg-panel z-10"><tr className="text-left text-[11px] uppercase tracking-wider text-muted">
                <th className="px-5 py-2">Term</th><th className="text-right">Legacy R</th><th className="text-right">Python</th><th className="text-right pr-5">|Δ|</th></tr></thead>
              <tbody className="mono">{coef.map((r: any) => {
                const bad = r.diff == null || r.diff > tol.coefficients;
                return (
                  <tr key={r.term} className="border-t border-line/50 hover:bg-slate-900/[.02]">
                    <td className="px-5 py-1.5 font-sans">{r.term}</td>
                    <td className="text-right tabular-nums">{r.legacy?.toFixed(8) ?? "—"}</td>
                    <td className="text-right tabular-nums">{r.python?.toFixed(8) ?? <span className="text-fail font-sans">missing</span>}</td>
                    <td className={clsx("text-right pr-5 tabular-nums", bad ? "text-fail font-semibold" : "text-pass")}>{sci(r.diff)}</td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
        </Panel>
      )}

      <Panel title="Certified code" right={
        <div role="tablist" className="inline-flex rounded-lg border border-line p-0.5 text-xs">
          {(["python", "epilogue"] as const).map((k) => (
            <button key={k} role="tab" aria-selected={code === k} onClick={() => setCode(k)}
              className={clsx("px-2.5 py-1 rounded-md transition", code === k ? "bg-teal/10 text-teal font-semibold" : "text-muted hover:text-text")}>
              {k === "python" ? "Python translation" : "R export epilogue"}
            </button>
          ))}
        </div>}>
        <p className="text-xs text-muted mb-2">{code === "python"
          ? "The exact model.py that passed the checks above. It is what serves traffic once the model is deployed."
          : "Appended to the legacy R script to export its scores, coefficients and training rows for the comparison."}</p>
        {code === "python" ? (d.python ? <CodeBlock code={d.python} lang="python" /> : <div className="text-muted text-sm">Rehosted — no Python implementation.</div>)
          : d.epilogue ? <CodeBlock code={d.epilogue} lang="r" /> : <div className="text-muted text-sm">No export epilogue recorded.</div>}
      </Panel>
    </div>
  );
}

export function DocView({ d }: { d: any }) {
  if (!d.doc) return <Panel><Empty title="No documentation yet">Drafted by the documentation agent after the spec is approved.</Empty></Panel>;
  const s = d.doc.sections || {};
  return (
    <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-5">
      <Panel title={`Model documentation · completeness ${Math.round((d.doc.completeness || 0) * 100)}%`}>
        <div className="space-y-5">
          {Object.entries(s).filter(([k]) => k !== "gaps").map(([k, v]: any) => (
            <section key={k}><h3 className="text-sm uppercase tracking-[.12em] text-muted font-semibold mb-1">{k.replace(/_/g, " ")}</h3><p className="text-[15px] leading-relaxed text-slate-700 whitespace-pre-wrap">{v || "Not documented."}</p></section>
          ))}
        </div>
      </Panel>
      <div className="space-y-5">
        <Panel title="Documentation gaps">{(d.doc.gaps || []).length ? <ul className="space-y-1.5 text-sm">{d.doc.gaps.map((g: string) => <li key={g} className="text-warn">▲ {g}</li>)}</ul> : <div className="text-sm text-muted">None listed.</div>}</Panel>
        <Panel title="Lineage"><pre className="mono text-xs text-muted whitespace-pre-wrap">{JSON.stringify(d.doc.lineage, null, 2)}</pre></Panel>
      </div>
    </div>
  );
}

export function FindingsView({ modelId }: { modelId: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["findings", modelId], queryFn: () => get<any[]>(`/api/findings?model_id=${modelId}`) });
  const [sev, setSev] = useState("all");
  const upd = useMutation({ mutationFn: ({ id, status }: any) => patch(`/api/findings/${id}`, { status }), onSuccess: () => qc.invalidateQueries({ queryKey: ["findings", modelId] }) });
  const list = (q.data || []).filter((f) => sev === "all" || f.severity === sev);
  return (
    <Panel pad={false} title={`Findings · ${q.data?.length ?? 0}`} right={<div className="flex gap-1">{["all", "high", "medium", "low"].map((s) => <button key={s} onClick={() => setSev(s)} className={clsx("btn !py-0.5 !px-2 text-xs", sev === s && "glow-teal")}>{s}</button>)}</div>}>
      <table className="w-full text-[13.5px]">
        <thead><tr className="text-left text-[11px] uppercase tracking-wider text-muted"><th className="px-4 py-2">Code</th><th>Severity</th><th>Finding</th><th>Source</th><th>Evidence</th><th className="pr-4">Status</th></tr></thead>
        <tbody>{list.map((f) => (
          <tr key={f.id} className="border-t border-line/50 align-top">
            <td className="px-4 py-2 mono text-xs">{f.code}<div className="text-faint">{f.run_id}</div></td>
            <td className="py-2"><Badge kind={f.severity} /></td>
            <td className="py-2 pr-3 max-w-[460px]"><div className="font-medium">{f.title}</div><div className="text-xs text-muted mt-0.5">{f.detail}</div></td>
            <td className="py-2"><Tag tone={f.detector?.startsWith("llm") || f.detector?.includes("investigation") ? "agent" : f.detector?.startsWith("policy") ? "warn" : "teal"}>{f.detector || "—"}</Tag></td>
            <td className="py-2 pr-3 text-xs">
              {f.evidence?.line && <div className="mono"><span className="text-muted">{f.evidence.file}:{f.evidence.line}</span><div className="text-agent truncate max-w-[260px]" title={f.evidence.code}>{f.evidence.code}</div></div>}
              {(f.evidence?.tokens || []).map((t: string) => <span key={t} className="mr-1"><Ev token={t} /></span>)}
            </td>
            <td className="py-2 pr-4"><select className={clsx(inputCls, "!py-1 !px-1.5 text-xs w-[118px]")} value={f.status} onChange={(e) => upd.mutate({ id: f.id, status: e.target.value })}>
              {["open", "accepted", "remediated", "dismissed"].map((s) => <option key={s}>{s}</option>)}</select></td>
          </tr>
        ))}</tbody>
      </table>
      {!list.length && <div className="text-muted text-sm text-center py-10">No findings.</div>}
    </Panel>
  );
}

export function RunsView({ d, initial }: { d: any; initial?: string }) {
  const [sel, setSel] = useState<string | undefined>(initial || d.runs[0]?.id);
  const run = d.runs.find((r: any) => r.id === sel);
  if (!d.runs.length) return <Panel><Empty title="No runs yet">Start the factory for this model.</Empty></Panel>;
  return (
    <div className="grid grid-cols-1 xl:grid-cols-[260px_1fr] gap-5">
      <div className="space-y-1.5">
        {d.runs.map((r: any) => (
          <button key={r.id} onClick={() => setSel(r.id)} className={clsx("w-full text-left rounded-lg border px-3 py-2", sel === r.id ? "border-teal/60 bg-teal/[.06]" : "border-line hover:bg-slate-900/[.03]")}>
            <div className="flex justify-between items-center"><span className="mono text-sm font-bold">{r.id}</span><Badge kind={r.status} /></div>
            <div className="text-xs text-muted mt-0.5">{r.kind} · {STAGE_LABEL[r.stage] || r.stage} · {ago(r.started_at)}</div>
          </button>
        ))}
      </div>
      {run && <AgentTrace runId={run.id} live={["running", "queued"].includes(run.status)} height={680} />}
    </div>
  );
}

export function FilesView({ modelId, files }: { modelId: string; files: any[] }) {
  const [sel, setSel] = useState<string | undefined>(files.find((f) => f.role === "script")?.name || files[0]?.name);
  const q = useQuery({ queryKey: ["mfile", modelId, sel], queryFn: () => get(`/api/models/${modelId}/files/${encodeURIComponent(sel!)}`), enabled: !!sel });
  const smells = (q.data?.parse?.smells || []).map((s: any) => s.line).concat((q.data?.parse?.injection || []).map((s: any) => s.line));
  return (
    <div className="grid grid-cols-1 xl:grid-cols-[240px_1fr_300px] gap-5">
      <div className="space-y-1.5">
        {files.map((f) => (
          <button key={f.name} onClick={() => setSel(f.name)} className={clsx("w-full text-left rounded-lg border px-3 py-2 flex items-center gap-2", sel === f.name ? "border-teal/60 bg-teal/[.06]" : "border-line hover:bg-slate-900/[.03]")}>
            <FileCode2 size={15} className="text-teal" /><span className="mono text-sm truncate flex-1">{f.name}</span><Tag>{f.role}</Tag>
          </button>
        ))}
      </div>
      <div>{q.data ? <CodeBlock code={q.data.text} lang={sel?.split(".").pop()} highlight={smells} maxH={720} /> : <div className="text-muted">Loading…</div>}</div>
      <div className="space-y-4">
        {q.data?.parse && (
          <Panel title="Static parse">
            <div className="text-sm space-y-2">
              <div><span className="text-muted">Methods:</span> {q.data.parse.methods.join(", ") || "—"}</div>
              <div><span className="text-muted">Libraries:</span> {q.data.parse.libraries.join(", ") || "base R"}</div>
              <div><span className="text-muted">Reads:</span> <span className="mono text-xs">{q.data.parse.reads.join(", ") || "—"}</span></div>
              <div><span className="text-muted">Writes:</span> <span className="mono text-xs">{q.data.parse.writes.join(", ") || "—"}</span></div>
              <div className="text-xs text-faint">sha256 {q.data.sha256?.slice(0, 16)}… · {q.data.lines} lines</div>
            </div>
          </Panel>
        )}
        {(q.data?.parse?.smells?.length > 0 || q.data?.parse?.injection?.length > 0) && (
          <Panel title="Flagged lines">
            <ul className="space-y-2 text-xs">
              {q.data.parse.injection.map((s: any) => <li key={`i${s.line}`} className="text-fail"><b>line {s.line}</b> · {s.label}: <span className="mono">{s.text}</span></li>)}
              {q.data.parse.smells.map((s: any, i: number) => <li key={i}><b className="text-warn">line {s.line}</b> · {s.kind.replace(/_/g, " ")}</li>)}
            </ul>
          </Panel>
        )}
      </div>
    </div>
  );
}
