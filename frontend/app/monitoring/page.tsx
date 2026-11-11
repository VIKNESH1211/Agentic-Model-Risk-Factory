"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Activity, HeartPulse, Pause, Play, Zap } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Area, Bar, CartesianGrid, ComposedChart, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Empty, Panel, Tag } from "@/components/ui";
import { get, post } from "@/lib/api";

const tt = { background: "#121a33", border: "1px solid rgba(148,163,255,.25)", borderRadius: 8, color: "#e6e9f5", fontSize: 12 };
const ax = { fill: "#8f98b8", fontSize: 11 };
const DEC_LABEL: Record<string, string> = { approve: "Approval rate", alert: "Alert rate", limit: "Share granted a limit", price: "Quotes priced" };

function tone(v: number | null | undefined, amber: number, red: number, reverse = false) {
  if (v == null) return "text-muted";
  const bad = reverse ? v < red : v > red, warn = reverse ? v < amber : v > amber;
  return bad ? "text-fail" : warn ? "text-warn" : "text-pass";
}

function Tile({ label, value, fmt, sub, data, k, color, cls }: any) {
  return (
    <div className="panel px-4 py-3">
      <div className="text-[11px] uppercase tracking-[.12em] text-muted font-semibold">{label}</div>
      <div className={clsx("text-2xl font-bold num mt-0.5", cls)}>{value == null ? "—" : fmt ? fmt(value) : value}</div>
      <div className="text-xs text-muted h-4 truncate">{sub}</div>
      <div className="h-9 -mx-1 mt-1">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}><Line dataKey={k} stroke={color} strokeWidth={1.6} dot={false} isAnimationActive={false} connectNulls /></LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function Monitor() {
  const sp = useSearchParams();
  const router = useRouter();
  const qc = useQueryClient();
  const all = useQuery({ queryKey: ["traffic"], queryFn: () => get<any[]>("/api/traffic"), refetchInterval: 3000 });
  const model = sp.get("model") || all.data?.[0]?.model_id;
  const st = useQuery({ queryKey: ["traffic-state", model], queryFn: () => get(`/api/traffic/${model}?n=120`), enabled: !!model, refetchInterval: 2000 });
  const [scen, setScen] = useState<string | null>(null);
  const [sev, setSev] = useState(0.7);
  const [ramp, setRamp] = useState(45);
  const act = useMutation({ mutationFn: (body: any) => post(`/api/traffic/${model}/scenario`, body), onSuccess: () => qc.invalidateQueries() });
  const rate = useMutation({ mutationFn: (body: any) => post(`/api/traffic/${model}/rate`, body), onSuccess: () => qc.invalidateQueries() });
  const accept = useMutation({ mutationFn: (gate: number) => post(`/api/gates/${gate}/decision`, { decision: "approved", comment: "Accepted from monitoring", decided_by: "Model Risk Officer" }), onSuccess: () => qc.invalidateQueries() });
  const gates = useQuery({ queryKey: ["gates-pending"], queryFn: () => get<any[]>("/api/gates?status=pending"), refetchInterval: 4000 });

  if (all.data && !all.data.length)
    return <Panel><Empty title="No model is serving traffic yet" action={<Link href="/" className="btn btn-primary">Go to the pipeline →</Link>}>Promote a validated model through the <b>Promote to Monitor (deploy)</b> gate. It starts receiving simulated live requests immediately.</Empty></Panel>;
  const d = st.data;
  if (!d) return <div className="text-muted">Loading…</div>;
  const w: any[] = (d.windows || []).map((x: any) => ({ ...x, t: new Date(x.ts).toLocaleTimeString([], { hour12: false, minute: "2-digit", second: "2-digit" }) }));
  const last = w.at(-1) || {};
  const scenarios: Record<string, string> = d.scenarios || {};
  const activeScen = d.cfg?.scenario;
  const binary = last.realized_gini != null || d.decision_kind === "approve" || d.decision_kind === "alert";
  const pendingAccept = (gates.data || []).filter((g) => g.model_id === model && g.stage === "gate_accept");

  return (
    <div className="space-y-4 max-w-[1700px] mx-auto">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Live Monitoring</h1>
          <p className="text-muted mt-1">Deployed models score <b>simulated</b> requests one by one (latency is measured). Outcomes mature after {d.outcome_delay_s}s, standing in for a 12-month performance window. KPIs close every {d.window_s}s.</p>
        </div>
        <div className="flex gap-1.5">
          {(all.data || []).map((m) => (
            <button key={m.model_id} onClick={() => router.push(`/monitoring?model=${m.model_id}`)}
              className={clsx("rounded-lg border px-3 py-1.5 text-sm font-semibold flex items-center gap-2", m.model_id === model ? "border-teal bg-teal/10 text-teal" : "border-line text-muted hover:text-text")}>
              <span className={clsx("h-2 w-2 rounded-full", m.latest?.status === "red" ? "bg-fail live-dot" : m.latest?.status === "amber" ? "bg-warn" : "bg-pass")} />
              <span className="mono">{m.model_id}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 2xl:grid-cols-8 gap-3">
        <Tile label="Requests / min" value={last.rpm} sub={`${d.total?.toLocaleString()} served · target ${d.cfg?.rpm}`} data={w} k="rpm" color="#2dd4bf" cls="text-teal" />
        <Tile label="Latency p95" value={last.latency_p95_ms} fmt={(v: number) => `${v} ms`} sub={`p50 ${last.latency_p50_ms ?? "—"} ms`} data={w} k="latency_p95_ms" color="#60a5fa" cls={tone(last.latency_p95_ms, 100, 150)} />
        <Tile label="No-decision rate" value={last.no_decision_rate} fmt={(v: number) => `${(v * 100).toFixed(1)}%`} sub={`errors ${((last.error_rate || 0) * 100).toFixed(1)}%`} data={w} k="no_decision_rate" color="#f5a524" cls={tone(last.no_decision_rate, 0.01, 0.02)} />
        <Tile label={DEC_LABEL[d.decision_kind] || "Decision rate"} value={last.decision_rate ?? last.mean_score} fmt={(v: number) => last.decision_rate != null ? `${(v * 100).toFixed(1)}%` : v.toFixed(3)} sub={last.decision_rate != null ? `mean score ${last.mean_score?.toFixed?.(3) ?? "—"}` : "mean predicted frequency"} data={w} k={last.decision_rate != null ? "decision_rate" : "mean_score"} color="#a78bfa" />
        <Tile label="Score PSI" value={last.psi} fmt={(v: number) => v.toFixed(3)} sub={last.psi == null ? `warming up (${last.psi_n ?? 0}/200 requests)` : "vs validation baseline"} data={w} k="psi" color="#f04461" cls={tone(last.psi, 0.1, 0.25)} />
        <Tile label="Worst input CSI" value={last.worst_csi} fmt={(v: number) => v.toFixed(3)} sub={last.worst_csi_feature || "—"} data={w} k="worst_csi" color="#f5a524" cls={tone(last.worst_csi, 0.15, 0.25)} />
        <Tile label="Actual ÷ expected" value={last.ae_ratio} fmt={(v: number) => v.toFixed(2)} sub={`${last.matured ?? 0} matured outcomes`} data={w} k="ae_ratio" color="#22c55e" cls={last.ae_ratio == null ? "" : last.ae_ratio < 0.8 || last.ae_ratio > 1.25 ? "text-fail" : "text-pass"} />
        <Tile label={model === "FR-001" ? "Realised recall" : "Realised Gini"} value={model === "FR-001" ? last.realized_recall : last.realized_gini} fmt={(v: number) => v.toFixed(3)} sub={binary ? `outcome rate ${last.realized_rate != null ? (last.realized_rate * 100).toFixed(2) + "%" : "—"}` : "n/a for this model"} data={w} k={model === "FR-001" ? "realized_recall" : "realized_gini"} color="#2dd4bf" />
      </div>

      <div className="grid grid-cols-1 2xl:grid-cols-[1fr_380px] gap-4">
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <Panel title="Traffic & latency">
            <ResponsiveContainer width="100%" height={210}>
              <ComposedChart data={w}><CartesianGrid stroke="rgba(148,163,255,.08)" /><XAxis dataKey="t" tick={ax} minTickGap={40} /><YAxis yAxisId="l" tick={ax} /><YAxis yAxisId="r" orientation="right" tick={ax} />
                <Tooltip contentStyle={tt} /><Bar yAxisId="l" dataKey="requests" fill="rgba(45,212,191,.35)" name="requests / window" isAnimationActive={false} />
                <Line yAxisId="r" dataKey="latency_p95_ms" stroke="#60a5fa" dot={false} strokeWidth={2} name="p95 ms" isAnimationActive={false} /></ComposedChart>
            </ResponsiveContainer>
          </Panel>
          <Panel title="Drift (PSI / worst CSI)">
            <ResponsiveContainer width="100%" height={210}>
              <LineChart data={w}><CartesianGrid stroke="rgba(148,163,255,.08)" /><XAxis dataKey="t" tick={ax} minTickGap={40} /><YAxis tick={ax} />
                <Tooltip contentStyle={tt} /><ReferenceLine y={0.25} stroke="#f04461" strokeDasharray="4 4" /><ReferenceLine y={0.1} stroke="#f5a524" strokeDasharray="4 4" />
                <Line dataKey="psi" stroke="#f04461" dot={false} strokeWidth={2} name="score PSI" isAnimationActive={false} connectNulls />
                <Line dataKey="worst_csi" stroke="#f5a524" dot={false} strokeWidth={1.6} name="worst CSI" isAnimationActive={false} connectNulls />
                <Line dataKey="severity" stroke="#a78bfa" dot={false} strokeDasharray="3 3" name="injected severity" isAnimationActive={false} /></LineChart>
            </ResponsiveContainer>
          </Panel>
          <Panel title="Outcomes: realised vs predicted">
            <ResponsiveContainer width="100%" height={210}>
              <LineChart data={w}><CartesianGrid stroke="rgba(148,163,255,.08)" /><XAxis dataKey="t" tick={ax} minTickGap={40} /><YAxis tick={ax} />
                <Tooltip contentStyle={tt} /><Line dataKey="realized_rate" stroke="#22c55e" dot={false} strokeWidth={2} name="realised" isAnimationActive={false} connectNulls />
                <Line dataKey="predicted_rate" stroke="#a78bfa" dot={false} strokeWidth={2} name="predicted" isAnimationActive={false} connectNulls /></LineChart>
            </ResponsiveContainer>
            <div className="text-xs text-muted">Matured outcomes only (rolling). {binary ? "Default / fraud rate." : "Claims per unit exposure."}</div>
          </Panel>
          <Panel title="Live request tail" className="xl:col-span-3" pad={false}>
            <div className="max-h-[300px] overflow-auto scroll-thin">
              <table className="w-full text-[13px]">
                <thead className="sticky top-0 bg-panel-2"><tr className="text-left text-xs text-muted uppercase"><th className="px-4 py-2">Request</th><th>Time</th><th>Latency</th><th>Score</th><th>Decision</th><th>Drift sev.</th><th className="pr-4">Inputs (sample)</th></tr></thead>
                <tbody>{(d.tail || []).map((r: any) => (
                  <tr key={r.req} className="border-t border-line/50">
                    <td className="px-4 py-1.5 mono">{r.req}</td>
                    <td className="mono text-muted">{new Date(r.ts * 1000).toLocaleTimeString([], { hour12: false })}</td>
                    <td className="mono">{r.latency_ms} ms</td>
                    <td className="mono">{Number.isFinite(r.score) ? (r.score > 100 ? r.score.toLocaleString() : r.score.toFixed(4)) : "NA"}</td>
                    <td><span className={clsx("text-xs font-bold", ["DECLINE", "ALERT", "NO_LIMIT"].includes(r.decision) ? "text-warn" : r.decision ? "text-pass" : "text-fail")}>{r.decision ?? "NO DECISION"}</span></td>
                    <td className="mono text-muted">{r.sev}</td>
                    <td className="pr-4 text-muted text-xs truncate max-w-[480px]">{Object.entries(r.inputs || {}).slice(0, 4).map(([k, v]) => `${k.split(".")[0]}=${typeof v === "number" ? Math.round((v as number) * 100) / 100 : String(v).slice(0, 14)}`).join(" · ")}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </Panel>
        </div>

        <div className="space-y-4">
          <Panel title="Drift scenario" right={<Tag tone="warn">simulated</Tag>}>
            <div className="space-y-3">
              <div className="grid gap-2">
                {Object.entries(scenarios).map(([k, v]) => (
                  <button key={k} onClick={() => setScen(k)} className={clsx("text-left rounded-lg border px-3 py-2", (scen ?? activeScen) === k ? "border-teal bg-teal/10" : "border-line hover:bg-white/5")}>
                    <div className="font-semibold text-sm">{k.replace(/_/g, " ")} {activeScen === k && <Tag tone="warn">active</Tag>}</div><div className="text-xs text-muted">{v}</div>
                  </button>
                ))}
              </div>
              <div><div className="flex justify-between text-sm"><span className="text-muted">Target severity</span><span className="mono font-bold">{sev.toFixed(2)}</span></div>
                <input type="range" min={0.05} max={1} step={0.05} value={sev} onChange={(e) => setSev(+e.target.value)} className="w-full accent-[#f04461]" aria-label="severity" /></div>
              <div><div className="flex justify-between text-sm"><span className="text-muted">Ramp over</span><span className="mono font-bold">{ramp}s</span></div>
                <input type="range" min={5} max={180} step={5} value={ramp} onChange={(e) => setRamp(+e.target.value)} className="w-full accent-[#a78bfa]" aria-label="ramp seconds" /></div>
              <div className="flex gap-2">
                <button className="btn btn-danger flex-1 justify-center" disabled={!(scen ?? activeScen) || act.isPending} onClick={() => act.mutate({ scenario: scen ?? activeScen, severity: sev, ramp_s: ramp })}><Zap size={15} /> Ramp in</button>
                <button className="btn flex-1 justify-center" disabled={act.isPending} onClick={() => act.mutate({ scenario: null, severity: 0, ramp_s: ramp })}><HeartPulse size={15} /> Heal</button>
              </div>
              <div className="text-sm text-muted">Current severity <span className="mono text-text">{d.severity_now}</span>{activeScen ? ` · ${activeScen.replace(/_/g, " ")}` : " · none"}</div>
            </div>
          </Panel>
          <Panel title="Traffic">
            <div className="flex justify-between text-sm"><span className="text-muted">Target requests / min</span><span className="mono font-bold">{d.cfg?.rpm}</span></div>
            <input type="range" min={30} max={900} step={30} defaultValue={d.cfg?.rpm} onMouseUp={(e: any) => rate.mutate({ rpm: +e.target.value })} onKeyUp={(e: any) => rate.mutate({ rpm: +e.target.value })} className="w-full accent-[#2dd4bf]" aria-label="requests per minute" />
            <button className="btn w-full justify-center mt-2" onClick={() => rate.mutate({ enabled: !d.cfg?.enabled })}>{d.cfg?.enabled ? <><Pause size={15} /> Pause traffic</> : <><Play size={15} /> Resume traffic</>}</button>
            <div className="text-xs text-faint mt-2">Serving version <span className="mono">{d.version}</span> (the certified run)</div>
          </Panel>
          <Panel title="Alert rules">
            <table className="w-full text-xs">
              <tbody>{Object.entries(d.rules || {}).map(([k, r]: any) => (
                <tr key={k} className="border-t border-line/50"><td className="py-1.5"><span className={clsx("font-semibold", d.active_alerts?.[k] ? (r.severity === "red" ? "text-fail" : "text-warn") : "")}>{k.replace(/_/g, " ")}</span></td>
                  <td className="mono text-muted">{r.kpi} {r.op} {r.threshold}</td><td className="text-muted">{r.windows}×</td><td>{d.active_alerts?.[k] ? <Badge kind={r.severity} /> : <span className="text-faint">ok</span>}</td></tr>
              ))}</tbody>
            </table>
            <div className="text-xs text-faint mt-2">A rule fires after N consecutive breached windows; a red rule starts re-validation on the latest live requests.</div>
          </Panel>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Panel title="Alerts" pad={false}>
          <div className="max-h-[260px] overflow-auto scroll-thin">
            {!d.alerts?.length ? <div className="p-5 text-muted text-sm">No alerts.</div> : d.alerts.map((a: any) => (
              <div key={a.id} className="px-5 py-2 border-t border-line/50 flex items-start gap-3 text-sm">
                <Badge kind={a.severity} /><div className="flex-1"><div className="font-semibold">{a.rule.replace(/_/g, " ")}</div><div className="text-muted">{a.message}{a.action && <> → <span className="text-agent">{a.action}</span></>}</div></div>
                <span className="mono text-xs text-faint">{new Date(a.ts).toLocaleTimeString([], { hour12: false })}</span>
              </div>))}
          </div>
        </Panel>
        <Panel title="Automatic re-validations" pad={false}>
          {!d.revalidations?.length ? <div className="p-5 text-muted text-sm">None yet. A red alert starts one on the latest live requests.</div> : d.revalidations.map((r: any) => {
            const g = pendingAccept.find((x) => x.run_id === r.id);
            return (
              <div key={r.id} className="px-5 py-2.5 border-t border-line/50 flex items-center gap-3 text-sm">
                <Activity size={15} className="text-agent" /><span className="mono">{r.id}</span><Badge kind={r.status} /><span className="text-muted">{r.stage}</span>
                <div className="ml-auto flex gap-2">
                  <Link href={`/agents?run=${r.id}`} className="btn !py-1 !px-2 text-xs">Trace</Link>
                  {(r.status === "completed" || r.status === "waiting_gate") && <Link href={`/reports/rep_${r.id}`} className="btn !py-1 !px-2 text-xs">Report + diff</Link>}
                  {g && <button className="btn btn-primary !py-1 !px-2 text-xs" onClick={() => accept.mutate(g.id)}>Accept</button>}
                </div>
              </div>);
          })}
        </Panel>
      </div>
    </div>
  );
}

export default function MonitoringPage() {
  return <Suspense><Monitor /></Suspense>;
}
