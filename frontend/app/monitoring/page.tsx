"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Activity, ChevronDown, ChevronRight, Clock, HeartPulse, Info, LayoutGrid, Pause, Play, Power, RefreshCw, Settings2, Star, Zap,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Empty, PageHeader, Panel } from "@/components/ui";
import { get, post } from "@/lib/api";
import { toast } from "@/lib/store";

// ------------------------------------------------------------------ Grafana dark theme
const G = {
  bg: "#111217", panel: "#181b1f", border: "#2a2d33", head: "#22252b", text: "#ccccdc", muted: "#8e8e9e", faint: "#5e6168",
  green: "#73bf69", yellow: "#fade2a", orange: "#ff9830", red: "#f2495c", blue: "#5794f2", purple: "#b877d9", cyan: "#8ab8ff", teal: "#4ec9b0",
};
const SERIES = [G.green, G.yellow, G.blue, G.orange, G.purple, G.cyan, G.red, G.teal];
const tip = { background: "#202226", border: `1px solid ${G.border}`, borderRadius: 4, color: G.text, fontSize: 12, padding: "6px 10px" };
const axis = { fill: G.muted, fontSize: 10.5 };

type Unit = "pct" | "ms" | "ratio" | "ratio4" | "short" | "count" | "x" | "score" | "pp" | "int";
const KPI: Record<string, [string, Unit, string]> = {
  requests: ["Requests", "short", "Requests in the window"],
  rpm: ["Requests / min", "short", "Throughput"],
  latency_p50_ms: ["p50", "ms", "Median scoring latency"],
  latency_p95_ms: ["p95", "ms", "95th percentile scoring latency"],
  latency_p99_ms: ["p99", "ms", "99th percentile scoring latency"],
  latency_max_ms: ["max", "ms", "Slowest request in the window"],
  error_rate: ["Error rate", "pct", "Share of requests that raised an error"],
  availability: ["Availability", "pct", "Share of requests served without error"],
  no_decision_rate: ["No decision", "pct", "Share of requests with no score"],
  missing_input_rate: ["Missing inputs", "pct", "Share of input values that are missing"],
  out_of_range_rate: ["Out of range", "pct", "Numeric inputs outside the baseline min–max"],
  unseen_category_rate: ["Unseen categories", "pct", "Category codes never seen in the baseline"],
  score_psi: ["Score PSI", "ratio", "PSI of live scores vs the validation baseline"],
  score_ks: ["Score KS", "ratio", "Two-sample KS distance, live vs baseline scores"],
  worst_csi: ["Worst CSI", "ratio", "Largest input-column PSI"],
  mean_csi: ["Mean CSI", "ratio", "Average input-column PSI"],
  drifted_features: ["Drifted inputs", "count", "Inputs with PSI above 0.10"],
  mean_score: ["Mean", "score", "Mean model output"],
  score_p50: ["Median", "score", "Median model output"],
  score_std: ["Std dev", "score", "Spread of model output"],
  adverse_rate: ["Adverse rate", "pct", "Share of adverse decisions"],
  adverse_rate_shift: ["Adverse shift", "pp", "Adverse rate minus the baseline rate"],
  realized_rate: ["Realised", "pct", "Observed outcome rate on matured requests"],
  predicted_rate: ["Predicted", "pct", "Predicted outcome rate on matured requests"],
  ae_ratio: ["A/E", "x", "Actual ÷ expected on matured requests"],
  realized_gini: ["Gini", "ratio", "Gini on matured outcomes"],
  realized_ks: ["KS", "ratio", "KS separation on matured outcomes"],
  brier: ["Brier", "ratio4", "Brier score on matured outcomes (lower is better)"],
  realized_recall: ["Recall", "pct", "Share of positives flagged"],
  realized_precision: ["Precision", "pct", "Share of flags that were positive"],
  health_score: ["Health", "int", "100 minus penalties for firing and breaching rules"],
};
const label = (k: string) => KPI[k]?.[0] || k.replace(/_/g, " ");
function fmt(k: string, v: any, unit?: Unit): string {
  if (v == null || Number.isNaN(v)) return "—";
  const u = unit || KPI[k]?.[1] || "ratio";
  switch (u) {
    case "pct": return `${(v * 100).toFixed(v >= 0.995 && v < 1 ? 2 : 1)}%`;
    case "pp": return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)} pp`;
    case "ms": return `${v >= 100 ? Math.round(v) : (+v).toFixed(1)} ms`;
    case "x": return `${(+v).toFixed(2)}×`;
    case "int": case "count": return `${Math.round(v)}`;
    case "short": return v >= 1000 ? `${(v / 1000).toFixed(1)}K` : `${Math.round(v * 10) / 10}`;
    case "ratio4": return (+v).toFixed(4);
    case "score": return Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : (+v).toFixed(3);
    default: return (+v).toFixed(3);
  }
}

/** Colour a value by the plan's alert rules for that KPI (Grafana-style thresholds). */
function tone(k: string, v: any, rules: any[], fallback = G.green): string {
  if (v == null) return G.muted;
  const hit = (r: any) => (r.op.startsWith(">") ? (r.op === ">" ? v > r.threshold : v >= r.threshold) : (r.op === "<" ? v < r.threshold : v <= r.threshold));
  const rs = rules.filter((r) => r.kpi === k);
  if (rs.some((r) => r.severity === "red" && hit(r))) return G.red;
  if (rs.some((r) => hit(r))) return G.orange;
  return rs.length ? G.green : fallback;
}
const csiTone = (v?: number | null) => (v == null ? G.muted : v > 0.25 ? G.red : v > 0.1 ? G.orange : G.green);

// ------------------------------------------------------------------ layout primitives
function GPanel({ title, desc, children, className, firing, right, noPad }: {
  title: React.ReactNode; desc?: string; children: React.ReactNode; className?: string; firing?: boolean; right?: React.ReactNode; noPad?: boolean;
}) {
  return (
    <section className={clsx("rounded-[3px] flex flex-col min-w-0", className)}
      style={{ background: G.panel, border: `1px solid ${firing ? "rgba(242,73,92,.6)" : G.border}`, boxShadow: firing ? "0 0 0 1px rgba(242,73,92,.25)" : undefined }}>
      <header className="flex items-center gap-1.5 h-8 px-2.5 shrink-0">
        {firing && <HeartPulse size={13} style={{ color: G.red }} className="animate-pulse" />}
        <span className="text-[13px] font-medium truncate" style={{ color: G.text }}>{title}</span>
        {desc && <span title={desc} className="cursor-help" style={{ color: G.faint }}><Info size={12} /></span>}
        <span className="flex-1" />
        {right}
      </header>
      <div className={clsx("flex-1 min-h-0", !noPad && "px-2.5 pb-2.5")}>{children}</div>
    </section>
  );
}

function Row({ id, title, count, children, open, toggle }: { id: string; title: string; count?: number; children: React.ReactNode; open: boolean; toggle: (id: string) => void }) {
  return (
    <div>
      <button onClick={() => toggle(id)} className="flex items-center gap-1.5 py-1.5 text-[14px] font-medium group" style={{ color: G.text }}>
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}{title}
        {!open && count != null && <span className="text-xs ml-1" style={{ color: G.muted }}>({count} panels)</span>}
      </button>
      {open && <div className="mt-1.5">{children}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ panels
function Spark({ data, k, color }: { data: any[]; k: string; color: string }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
        <defs><linearGradient id={`sp-${k}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity={0.35} /><stop offset="100%" stopColor={color} stopOpacity={0} /></linearGradient></defs>
        <YAxis hide domain={["dataMin", "dataMax"]} />
        <Area dataKey={k} stroke={color} strokeWidth={1.5} fill={`url(#sp-${k})`} dot={false} isAnimationActive={false} connectNulls />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function Stat({ k, w, rules, title, unit, colorFallback }: { k: string; w: any[]; rules: any[]; title?: string; unit?: Unit; colorFallback?: string }) {
  const v = [...w].reverse().find((x) => x[k] != null)?.[k];
  const c = tone(k, v, rules, colorFallback);
  return (
    <GPanel title={title || label(k)} desc={KPI[k]?.[2]} noPad firing={c === G.red}>
      <div className="relative h-[86px]">
        <div className="absolute inset-x-0 bottom-0 h-[46px] opacity-90"><Spark data={w} k={k} color={c} /></div>
        <div className="relative px-3 text-[30px] leading-[1.15] font-semibold tabular-nums" style={{ color: c }}>{fmt(k, v, unit)}</div>
      </div>
    </GPanel>
  );
}

function Gauge({ title, value, min = 0, max = 100, steps, unit = "", desc }: {
  title: string; value: number | null | undefined; min?: number; max?: number; steps: [number, string][]; unit?: string; desc?: string;
}) {
  const R = 52, cx = 70, cy = 66, sw = 11;
  const ang = (v: number) => Math.PI * (1 - (Math.min(max, Math.max(min, v)) - min) / (max - min));
  const pt = (a: number, r = R) => [cx + r * Math.cos(a), cy - r * Math.sin(a)];
  const arc = (a0: number, a1: number, r = R) => { const [x0, y0] = pt(a0, r), [x1, y1] = pt(a1, r); return `M${x0},${y0} A${r},${r} 0 0 1 ${x1},${y1}`; };
  const color = value == null ? G.muted : [...steps].reverse().find(([s]) => value >= s)?.[1] || steps[0][1];
  const bounds = steps.map(([s], i) => [Math.max(s, min), steps[i + 1]?.[0] ?? max] as [number, number]);
  return (
    <GPanel title={title} desc={desc}>
      <svg viewBox="0 0 140 84" className="w-full h-[86px]">
        {bounds.map(([a, b], i) => <path key={i} d={arc(ang(a), ang(b), R + 9)} stroke={steps[i][1]} strokeWidth={2.5} fill="none" opacity={0.9} />)}
        <path d={arc(Math.PI, 0)} stroke="#2c3036" strokeWidth={sw} fill="none" />
        {value != null && <path d={arc(Math.PI, ang(value))} stroke={color} strokeWidth={sw} fill="none" />}
        <text x={cx} y={cy - 4} textAnchor="middle" fontSize="22" fontWeight={600} fill={color}>{value == null ? "—" : `${Math.round(value * 10) / 10}${unit}`}</text>
      </svg>
    </GPanel>
  );
}

type S = { k: string; color?: string; dash?: string; name?: string };
function TimeSeries({ title, data, series, rules = [], unit, height = 190, kind = "line", annotations = [], band, hline, desc, firing, stacked }: {
  title: string; data: any[]; series: S[]; rules?: any[]; unit?: Unit; height?: number; kind?: "line" | "area" | "bar"; annotations?: string[];
  band?: [number, number]; hline?: { y: number; label: string; color?: string }; desc?: string; firing?: boolean; stacked?: boolean;
}) {
  const keys = series.map((s) => s.k);
  const lines = rules.filter((r) => keys.includes(r.kpi));
  const u = unit || KPI[keys[0]]?.[1];
  const stats = series.map((s) => {
    const v = data.map((d) => d[s.k]).filter((x) => x != null && Number.isFinite(x));
    return { ...s, last: v.at(-1), mean: v.length ? v.reduce((a, b) => a + b, 0) / v.length : null, max: v.length ? Math.max(...v) : null };
  });
  const C: any = kind === "bar" ? BarChart : kind === "area" ? AreaChart : LineChart;
  const marks = [...lines.map((r) => r.threshold), ...(band || []), ...(hline ? [hline.y] : [])];
  const domain: [any, any] = [
    (lo: number) => Math.min(Number.isFinite(lo) ? lo : 0, 0, ...marks),
    (hi: number) => {
      const top = Math.max(Number.isFinite(hi) ? hi : 0, ...marks.map((m) => m * 1.15));
      return top > 0 ? top : u === "pct" || u === "pp" ? 0.05 : 1;
    },
  ];
  return (
    <GPanel title={title} desc={desc} firing={firing}>
      <ResponsiveContainer width="100%" height={height}>
        <C data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }} barCategoryGap={1}>
          <defs>{series.map((s, i) => <linearGradient key={s.k} id={`g-${title}-${i}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={s.color || SERIES[i]} stopOpacity={0.3} /><stop offset="100%" stopColor={s.color || SERIES[i]} stopOpacity={0.02} /></linearGradient>)}</defs>
          <CartesianGrid stroke="rgba(204,204,220,.07)" vertical={false} />
          <XAxis dataKey="t" tick={axis} minTickGap={50} axisLine={{ stroke: G.border }} tickLine={false} />
          <YAxis tick={axis} width={56} axisLine={false} tickLine={false} tickFormatter={(v) => fmt(keys[0], v, u)} domain={domain} allowDataOverflow={false} />
          <Tooltip contentStyle={tip} labelStyle={{ color: G.muted, marginBottom: 2 }} cursor={{ stroke: G.faint }}
            formatter={(v: any, n: any, p: any) => [fmt(p.dataKey, v, u), n]} />
          {band && <ReferenceArea y1={band[0]} y2={band[1]} fill={G.green} fillOpacity={0.06} stroke="none" />}
          {lines.map((r) => <ReferenceLine key={r.id} y={r.threshold} stroke={r.severity === "red" ? G.red : G.orange} strokeDasharray="4 3" strokeOpacity={0.8}
            label={{ value: r.id, fill: r.severity === "red" ? G.red : G.orange, fontSize: 9.5, position: "insideTopRight" }} />)}
          {hline && <ReferenceLine y={hline.y} stroke={hline.color || G.muted} strokeDasharray="2 3" label={{ value: hline.label, fill: G.muted, fontSize: 10, position: "insideTopLeft" }} />}
          {annotations.map((t, i) => <ReferenceLine key={`an${i}`} x={t} stroke={G.red} strokeOpacity={0.55} strokeDasharray="2 2" />)}
          {series.map((s, i) => {
            const c = s.color || SERIES[i];
            const nm = s.name || label(s.k);
            return kind === "bar" ? <Bar key={s.k} dataKey={s.k} name={nm} fill={c} fillOpacity={0.75} isAnimationActive={false} stackId={stacked ? "s" : undefined} />
              : kind === "area" ? <Area key={s.k} dataKey={s.k} name={nm} stroke={c} strokeWidth={1.5} fill={`url(#g-${title}-${i})`} dot={false} isAnimationActive={false} connectNulls strokeDasharray={s.dash} />
              : <Line key={s.k} dataKey={s.k} name={nm} stroke={c} strokeWidth={1.5} dot={false} isAnimationActive={false} connectNulls strokeDasharray={s.dash} />;
          })}
        </C>
      </ResponsiveContainer>
      <table className="w-full mt-1 text-[11.5px] tabular-nums table-fixed whitespace-nowrap">
        <colgroup><col /><col className="w-[64px]" /><col className="w-[64px]" /><col className="w-[64px]" /></colgroup>
        <thead><tr style={{ color: G.muted }}><th className="text-left font-normal">Name</th><th className="text-right font-normal">Mean</th><th className="text-right font-normal">Max</th><th className="text-right font-normal">Last</th></tr></thead>
        <tbody>{stats.map((s, i) => (
          <tr key={s.k} style={{ color: G.text }}>
            <td className="truncate"><span className="inline-block w-3 h-[3px] rounded mr-1.5 align-middle" style={{ background: s.color || SERIES[i] }} />{s.name || label(s.k)}</td>
            <td className="text-right">{fmt(s.k, s.mean, u)}</td><td className="text-right">{fmt(s.k, s.max, u)}</td>
            <td className="text-right font-medium" style={{ color: tone(s.k, s.last, rules, G.text) }}>{fmt(s.k, s.last, u)}</td>
          </tr>
        ))}</tbody>
      </table>
    </GPanel>
  );
}

function BarGauge({ title, items, max, desc, unit = "ratio", colorOf }: {
  title: string; items: { name: string; value: number | null | undefined; sub?: string }[]; max?: number; desc?: string; unit?: Unit; colorOf: (v?: number | null) => string;
}) {
  const top = max ?? Math.max(0.3, ...items.map((i) => i.value || 0));
  return (
    <GPanel title={title} desc={desc}>
      <div className="space-y-1.5 overflow-y-auto scroll-thin max-h-[250px] pr-1">
        {items.length ? items.map((it) => {
          const c = colorOf(it.value);
          const pctW = Math.min(100, ((it.value || 0) / top) * 100);
          return (
            <div key={it.name} className="grid grid-cols-[110px_1fr_64px] items-center gap-2 text-[12px]">
              <span className="truncate mono" style={{ color: G.text }} title={it.sub}>{it.name}</span>
              <div className="h-[18px] rounded-[2px] relative overflow-hidden" style={{ background: "#22252b" }}>
                <div className="absolute inset-y-0 left-0" style={{ width: `${pctW}%`, background: `linear-gradient(90deg, ${c}55, ${c})` }} />
              </div>
              <span className="text-right tabular-nums font-medium" style={{ color: c }}>{fmt("", it.value, unit)}</span>
            </div>
          );
        }) : <div className="text-xs py-6 text-center" style={{ color: G.muted }}>Collecting requests…</div>}
      </div>
    </GPanel>
  );
}

// ------------------------------------------------------------------ page
const RANGES = [{ l: "Last 5 minutes", n: 30 }, { l: "Last 15 minutes", n: 90 }, { l: "Last 30 minutes", n: 180 }, { l: "Last 1 hour", n: 360 }];
const REFRESH = [{ l: "Off", ms: 0 }, { l: "2s", ms: 2000 }, { l: "5s", ms: 5000 }, { l: "10s", ms: 10000 }, { l: "30s", ms: 30000 }];

function useRows() {
  const [closed, setClosed] = useState<Set<string>>(new Set());
  useEffect(() => { try { const v = localStorage.getItem("mon-rows-closed"); if (v) setClosed(new Set(JSON.parse(v))); } catch {} }, []);
  const toggle = (id: string) => setClosed((c) => {
    const n = new Set(c); n.has(id) ? n.delete(id) : n.add(id);
    try { localStorage.setItem("mon-rows-closed", JSON.stringify([...n])); } catch {}
    return n;
  });
  return { open: (id: string) => !closed.has(id), toggle };
}

function Picker({ icon: Icon, value, options, onChange, ariaLabel }: { icon: any; value: string; options: { v: string; l: string }[]; onChange: (v: string) => void; ariaLabel: string }) {
  return (
    <label className="flex items-center gap-1.5 h-8 px-2 rounded-[3px] text-[12.5px] cursor-pointer" style={{ background: G.panel, border: `1px solid ${G.border}`, color: G.text }}>
      <Icon size={14} style={{ color: G.muted }} />
      <select aria-label={ariaLabel} value={value} onChange={(e) => onChange(e.target.value)} className="bg-transparent outline-none cursor-pointer" style={{ color: G.text }}>
        {options.map((o) => <option key={o.v} value={o.v} style={{ background: G.panel }}>{o.l}</option>)}
      </select>
    </label>
  );
}

function Monitor() {
  const sp = useSearchParams();
  const router = useRouter();
  const qc = useQueryClient();
  const rows = useRows();
  const [range, setRange] = useState(90);
  const [refresh, setRefresh] = useState(2000);
  const all = useQuery({ queryKey: ["traffic"], queryFn: () => get<any[]>("/api/traffic"), refetchInterval: refresh || false });
  const model = sp.get("model") || all.data?.[0]?.model_id;
  const st = useQuery({ queryKey: ["traffic-state", model, range], queryFn: () => get(`/api/traffic/${model}?n=${range}`), enabled: !!model, refetchInterval: refresh || false });
  const gates = useQuery({ queryKey: ["gates-accept"], queryFn: () => get<any[]>("/api/gates?status=pending"), refetchInterval: 4000 });
  const [scen, setScen] = useState<string | null>(null);
  const [sev, setSev] = useState(0.7);
  const [ramp, setRamp] = useState(45);
  const act = useMutation({ mutationFn: (b: any) => post(`/api/traffic/${model}/scenario`, b), onSuccess: (_r, b: any) => { qc.invalidateQueries(); toast({ kind: "info", text: b.scenario ? `${model}: ramping in '${b.scenario}'` : `${model}: healing` }); } });
  const rate = useMutation({ mutationFn: (b: any) => post(`/api/traffic/${model}/rate`, b), onSuccess: () => qc.invalidateQueries() });
  const off = useMutation({ mutationFn: () => post(`/api/traffic/${model}/undeploy`), onSuccess: () => { qc.invalidateQueries(); router.replace("/monitoring"); } });
  const accept = useMutation({ mutationFn: (gid: number) => post(`/api/gates/${gid}/decision`, { decision: "approved", comment: "Re-validation accepted", decided_by: "Model Risk Officer" }), onSuccess: () => qc.invalidateQueries() });

  const d = st.data;
  const w = useMemo(() => (d?.windows || []).map((x: any) => {
    const r: any = { ...x, t: new Date(x.ts).toLocaleTimeString([], { hour12: false }) };
    for (const [f, v] of Object.entries(x.csi || {})) r[`csi:${f}`] = v;
    return r;
  }), [d?.windows]);
  const annotations = useMemo(() => {
    if (!w.length) return [];
    return (d?.alerts || []).map((a: any) => w.find((x: any) => new Date(x.ts) >= new Date(a.ts))?.t).filter(Boolean).slice(0, 12);
  }, [d?.alerts, w]);

  if (all.isSuccess && !all.data.length)
    return <div className="space-y-5 max-w-[1700px] mx-auto"><PageHeader title="Live monitoring" /><Panel><Empty title="No model is serving traffic yet" action={<Link href="/" className="btn btn-primary">Go to the factory floor →</Link>}>Approve a model through <b>Approve validation · deploy to Monitor</b>. It starts scoring simulated requests immediately, with dashboards, alerts and drift scenarios from its own monitoring plan.</Empty></Panel></div>;

  const plan = d?.plan || { panels: [], rules: [], scenarios: [] };
  const rules: any[] = plan.rules;
  const active: Record<string, string> = d?.active_alerts || {};
  const streaks: Record<string, number> = d?.streaks || {};
  const activeScen = d?.cfg?.scenario;
  const pendingAccept = (gates.data || []).filter((g) => g.model_id === model && g.stage === "gate_accept");
  const last = w.at(-1) || {};
  const feats: any[] = d?.features || [];
  const topFeats = feats.slice(0, 6).map((f) => f.feature);
  const firingKpi = (ks: string[]) => rules.some((r) => ks.includes(r.kpi) && active[r.id]);
  const hasOutcomes = w.some((x: any) => x.ae_ratio != null || x.realized_rate != null);
  const isAlert = d?.decision_kind === "alert";
  const firing = Object.keys(active).length;

  return (
    <div className="-m-4 md:-m-6 min-h-[calc(100vh-4rem)] p-3 md:p-4 space-y-3" style={{ background: G.bg, color: G.text }}>
      {/* Top bar */}
      <div className="flex items-center gap-2 flex-wrap">
        <LayoutGrid size={18} style={{ color: G.muted }} />
        <div className="text-[15px] flex items-center gap-1.5 min-w-0">
          <span style={{ color: G.muted }}>Dashboards</span><span style={{ color: G.faint }}>/</span>
          <span style={{ color: G.muted }}>Model Risk</span><span style={{ color: G.faint }}>/</span>
          <span className="font-medium truncate">Live model monitoring</span>
          <Star size={14} style={{ color: G.faint }} />
        </div>
        <span className="flex-1" />
        <Picker icon={Clock} ariaLabel="Time range" value={String(range)} onChange={(v) => setRange(+v)} options={RANGES.map((r) => ({ v: String(r.n), l: r.l }))} />
        <button onClick={() => qc.invalidateQueries({ queryKey: ["traffic-state"] })} className="h-8 px-2 rounded-[3px] flex items-center" style={{ background: G.panel, border: `1px solid ${G.border}` }} aria-label="Refresh now">
          <RefreshCw size={14} className={clsx(st.isFetching && "animate-spin")} style={{ color: G.muted }} />
        </button>
        <Picker icon={Activity} ariaLabel="Auto refresh" value={String(refresh)} onChange={(v) => setRefresh(+v)} options={REFRESH.map((r) => ({ v: String(r.ms), l: r.l }))} />
        {model && <Link href={`/models/${model}?tab=monitoring`} className="h-8 px-2.5 rounded-[3px] flex items-center gap-1.5 text-[12.5px]" style={{ background: G.panel, border: `1px solid ${G.border}`, color: G.text }}><Settings2 size={14} /> Edit plan</Link>}
      </div>
      {/* Variables */}
      <div className="flex items-center gap-2 flex-wrap text-[12.5px]">
        <span className="h-8 px-2.5 flex items-center rounded-l-[3px]" style={{ background: G.head, border: `1px solid ${G.border}`, color: G.cyan }}>model</span>
        <select aria-label="Model" value={model || ""} onChange={(e) => router.replace(`/monitoring?model=${e.target.value}`)}
          className="h-8 -ml-2 px-2 rounded-r-[3px] outline-none mono" style={{ background: G.panel, border: `1px solid ${G.border}`, color: G.text }}>
          {(all.data || []).map((m) => <option key={m.model_id} value={m.model_id} style={{ background: G.panel }}>{m.model_id}</option>)}
        </select>
        {d?.deployed && <>
          <span className="px-2 h-6 flex items-center rounded-[3px]" style={{ background: "rgba(115,191,105,.12)", color: G.green }}>serving {d.version}</span>
          <span className="px-2 h-6 flex items-center rounded-[3px]" style={{ background: G.head, color: G.muted }}>{d.task}</span>
          {activeScen && <span className="px-2 h-6 flex items-center rounded-[3px]" style={{ background: "rgba(255,152,48,.14)", color: G.orange }}>scenario: {activeScen} · severity {d.severity_now}</span>}
          {firing > 0 && <span className="px-2 h-6 flex items-center gap-1 rounded-[3px]" style={{ background: "rgba(242,73,92,.15)", color: G.red }}><HeartPulse size={12} /> {firing} firing</span>}
          <span style={{ color: G.muted }}>{d.total?.toLocaleString()} requests · {d.window_s}s windows · outcomes mature after {d.outcome_delay_s}s</span>
        </>}
      </div>

      <Row id="fleet" title="Fleet" count={1} open={rows.open("fleet")} toggle={rows.toggle}>
        <GPanel title="Model status history" desc="One block per 10-second window: green ok, amber breaching, red alert firing">
          <div className="space-y-1.5">
            {(all.data || []).map((m) => (
              <button key={m.model_id} onClick={() => router.replace(`/monitoring?model=${m.model_id}`)}
                className={clsx("w-full grid grid-cols-[88px_1fr_56px] items-center gap-2 text-[12px] rounded-[2px] px-1 py-0.5", m.model_id === model && "ring-1")}
                style={{ ["--tw-ring-color" as any]: G.blue }}>
                <span className="mono text-left" style={{ color: G.text }}>{m.model_id}</span>
                <div className="flex h-5 gap-px">
                  {(m.statuses || []).map((s: string, i: number) => <div key={i} className="flex-1" style={{ background: s === "red" ? G.red : s === "amber" ? G.orange : G.green, opacity: 0.85 }} />)}
                  {!m.statuses?.length && <div className="flex-1 text-left" style={{ color: G.muted }}>warming up…</div>}
                </div>
                <span className="text-right tabular-nums font-semibold" style={{ color: m.health >= 85 ? G.green : m.health >= 60 ? G.orange : G.red }}>{m.health ?? "—"}</span>
              </button>
            ))}
          </div>
        </GPanel>
      </Row>

      {d?.deployed && <>
        <Row id="overview" title="Overview" count={8} open={rows.open("overview")} toggle={rows.toggle}>
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-2">
            <Gauge title="Health score" value={d.health} steps={[[0, G.red], [60, G.orange], [85, G.green]]} desc={KPI.health_score[2]} />
            <Stat k="availability" w={w} rules={rules} />
            <Stat k="rpm" w={w} rules={rules} colorFallback={G.blue} />
            <Stat k="latency_p95_ms" w={w} rules={rules} title="Latency p95" />
            <Stat k="score_psi" w={w} rules={rules} />
            <Stat k="missing_input_rate" w={w} rules={rules} />
            <Stat k="adverse_rate" w={w} rules={rules} colorFallback={G.blue} />
            {hasOutcomes
              ? <Gauge title="Actual / expected" value={last.ae_ratio ?? [...w].reverse().find((x: any) => x.ae_ratio != null)?.ae_ratio} min={0.5} max={1.5}
                  steps={[[0.5, G.red], [0.8, G.green], [1.25, G.red]]} unit="×" desc={KPI.ae_ratio[2]} />
              : <Stat k="drifted_features" w={w} rules={rules} />}
          </div>
        </Row>

        <Row id="ops" title="Operations" count={3} open={rows.open("ops")} toggle={rows.toggle}>
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-2">
            <TimeSeries title="Throughput" data={w} kind="area" series={[{ k: "rpm", color: G.blue }]} annotations={annotations} desc="Requests per minute in each window" />
            <TimeSeries title="Scoring latency" data={w} rules={rules} series={[{ k: "latency_p50_ms", color: G.green }, { k: "latency_p95_ms", color: G.yellow }, { k: "latency_p99_ms", color: G.orange }, { k: "latency_max_ms", color: G.red, dash: "3 3" }]}
              firing={firingKpi(["latency_p95_ms", "latency_p99_ms"])} annotations={annotations} />
            <TimeSeries title="Errors & no-decision" data={w} rules={rules} kind="bar" series={[{ k: "error_rate", color: G.red }, { k: "no_decision_rate", color: G.orange }]}
              firing={firingKpi(["error_rate", "no_decision_rate", "availability"])} />
          </div>
        </Row>

        <Row id="quality" title="Data quality" count={3} open={rows.open("quality")} toggle={rows.toggle}>
          <div className="grid grid-cols-1 xl:grid-cols-[1fr_1fr_1.2fr] gap-2">
            <TimeSeries title="Input data quality" data={w} rules={rules} series={[{ k: "missing_input_rate", color: G.purple }, { k: "out_of_range_rate", color: G.orange }, { k: "unseen_category_rate", color: G.cyan }]}
              firing={firingKpi(["missing_input_rate", "out_of_range_rate", "unseen_category_rate"])} annotations={annotations} desc="Inputs checked against the validation baseline profile" />
            <BarGauge title="Missing values by input (live)" desc="Share of recent requests with the input missing" unit="pct" max={Math.max(0.2, ...feats.map((f) => f.missing || 0))}
              items={[...feats].sort((a, b) => b.missing - a.missing).map((f) => ({ name: f.feature, value: f.missing, sub: `baseline ${fmt("", f.base_missing, "pct")}` }))}
              colorOf={(v) => (v == null ? G.muted : v > 0.1 ? G.red : v > 0.02 ? G.orange : G.green)} />
            <GPanel title="Input profile vs baseline" desc="Recent live requests compared with the validation baseline" noPad>
              <div className="overflow-auto scroll-thin max-h-[262px]">
                <table className="w-full text-[12px] tabular-nums whitespace-nowrap">
                  <thead className="sticky top-0" style={{ background: G.panel, color: G.cyan }}>
                    <tr className="text-left"><th className="px-2.5 py-1.5 font-medium">Input</th><th className="font-medium">Type</th><th className="text-right font-medium px-2">CSI</th><th className="text-right font-medium">Missing</th><th className="text-right font-medium pl-2">Shift · new</th><th className="text-right pr-2.5 font-medium">Live</th></tr>
                  </thead>
                  <tbody>{feats.map((f) => (
                    <tr key={f.feature} style={{ borderTop: `1px solid ${G.border}` }}>
                      <td className="px-2.5 py-1 mono truncate max-w-[200px]" title={f.feature}>{f.feature}</td>
                      <td style={{ color: G.muted }}>{f.kind === "numeric" ? "num" : "cat"}</td>
                      <td className="text-right px-2"><span className="px-1.5 rounded-[2px]" style={{ background: `${csiTone(f.csi)}26`, color: csiTone(f.csi) }}>{fmt("", f.csi)}</span></td>
                      <td className="text-right" style={{ color: f.missing - f.base_missing > 0.03 ? G.orange : G.text }}>{fmt("", f.missing, "pct")}</td>
                      <td className="text-right" style={{ color: (f.out_of_range ?? f.unseen ?? 0) > 0.02 ? G.orange : G.text }}>
                        {f.kind === "numeric" ? `${f.shift_sd == null ? "—" : `${f.shift_sd >= 0 ? "+" : ""}${f.shift_sd}σ`} · ${fmt("", f.out_of_range, "pct")} oor` : `${fmt("", f.unseen, "pct")} new`}
                      </td>
                      <td className="text-right pr-2.5 truncate max-w-[110px]" style={{ color: G.muted }}>{f.kind === "numeric" ? fmt("", f.live_mean, "score") : f.top ?? "—"}</td>
                    </tr>
                  ))}</tbody>
                </table>
                {!feats.length && <div className="text-xs py-6 text-center" style={{ color: G.muted }}>Collecting requests…</div>}
              </div>
            </GPanel>
          </div>
        </Row>

        <Row id="drift" title="Stability & drift" count={4} open={rows.open("drift")} toggle={rows.toggle}>
          <div className="grid grid-cols-1 xl:grid-cols-2 2xl:grid-cols-4 gap-2">
            <TimeSeries title="Score stability" data={w} rules={rules} series={[{ k: "score_psi", color: G.yellow }, { k: "score_ks", color: G.cyan }]}
              firing={firingKpi(["score_psi", "score_ks"])} annotations={annotations} desc="PSI and KS of live scores vs the validation baseline (needs 200 scored requests)" />
            <TimeSeries title="Input drift (CSI) by feature" data={w} rules={rules.filter((r) => r.kpi === "worst_csi").map((r) => ({ ...r, kpi: `csi:${topFeats[0]}` }))}
              series={topFeats.map((f, i) => ({ k: `csi:${f}`, name: f, color: SERIES[i] }))} unit="ratio"
              firing={firingKpi(["worst_csi", "mean_csi", "drifted_features"])} annotations={annotations} desc="Population stability of each input over time" />
            <BarGauge title="Current drift by input" desc="CSI now: green < 0.10 ≤ orange < 0.25 ≤ red" items={feats.map((f) => ({ name: f.feature, value: f.csi }))} colorOf={csiTone} />
            <GPanel title="Score distribution: live vs baseline" desc="Share of requests in each baseline score bucket">
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={d.score_hist || []} margin={{ top: 6, right: 4, bottom: 0, left: 0 }} barGap={0}>
                  <CartesianGrid stroke="rgba(204,204,220,.07)" vertical={false} />
                  <XAxis dataKey="bin" tick={axis} interval={1} axisLine={{ stroke: G.border }} tickLine={false} />
                  <YAxis tick={axis} width={40} axisLine={false} tickLine={false} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
                  <Tooltip contentStyle={tip} formatter={(v: any, n: any) => [`${(v * 100).toFixed(1)}%`, n]} cursor={{ fill: "rgba(204,204,220,.05)" }} />
                  <Bar dataKey="baseline" name="baseline" fill={G.blue} fillOpacity={0.45} isAnimationActive={false} />
                  <Bar dataKey="live" name="live" fill={G.orange} fillOpacity={0.85} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </GPanel>
          </div>
        </Row>

        <Row id="decisions" title="Decisions" count={2} open={rows.open("decisions")} toggle={rows.toggle}>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-2">
            <TimeSeries title="Score shape" data={w} series={[{ k: "mean_score", color: G.green }, { k: "score_p50", color: G.blue }, { k: "score_std", color: G.purple, dash: "4 3" }]} unit="score" annotations={annotations} />
            <TimeSeries title="Adverse decisions vs baseline" data={w} rules={rules} kind="area" series={[{ k: "adverse_rate", color: G.orange }]}
              hline={d.base_adverse_rate != null ? { y: d.base_adverse_rate, label: `baseline ${fmt("", d.base_adverse_rate, "pct")}` } : undefined}
              firing={firingKpi(["adverse_rate", "adverse_rate_shift"])} annotations={annotations} />
          </div>
        </Row>

        {hasOutcomes && (
          <Row id="outcomes" title="Outcomes (matured requests)" count={isAlert ? 4 : 3} open={rows.open("outcomes")} toggle={rows.toggle}>
            <div className={clsx("grid grid-cols-1 gap-2", isAlert ? "xl:grid-cols-2 2xl:grid-cols-4" : "xl:grid-cols-3")}>
              <TimeSeries title="Actual vs expected" data={w} series={[{ k: "realized_rate", color: G.red }, { k: "predicted_rate", color: G.blue, dash: "4 3" }]} unit="pct" annotations={annotations} />
              <TimeSeries title="A/E ratio" data={w} rules={rules} series={[{ k: "ae_ratio", color: G.yellow }]} band={[0.8, 1.25]} firing={firingKpi(["ae_ratio"])} annotations={annotations} desc="Green band: 0.8–1.25" />
              <TimeSeries title="Discrimination" data={w} rules={rules} series={[{ k: "realized_gini", color: G.green }, { k: "realized_ks", color: G.cyan }]} firing={firingKpi(["realized_gini", "realized_ks"])} desc="Rank ordering on matured outcomes" />
              {isAlert && <TimeSeries title="Alert quality" data={w} rules={rules} series={[{ k: "realized_recall", color: G.green }, { k: "realized_precision", color: G.purple }]} unit="pct" firing={firingKpi(["realized_recall", "realized_precision"])} />}
            </div>
          </Row>
        )}

        {plan.panels.length > 0 && (
          <Row id="plan" title="Monitoring plan panels" count={plan.panels.length} open={rows.open("plan")} toggle={rows.toggle}>
            <div className="grid grid-cols-1 xl:grid-cols-3 gap-2">
              {plan.panels.map((p: any) => p.kind === "stat"
                ? <div key={p.id} className="grid grid-cols-2 gap-2">{p.kpis.map((k: string) => <Stat key={k} k={k} w={w} rules={rules} />)}</div>
                : <TimeSeries key={p.id} title={p.title} data={w} rules={rules} kind={p.kind} series={p.kpis.map((k: string) => ({ k }))}
                    unit={new Set(p.kpis.map((k: string) => KPI[k]?.[1])).size === 1 ? undefined : "ratio"} firing={firingKpi(p.kpis)} annotations={annotations} />)}
            </div>
          </Row>
        )}

        <Row id="events" title="Alerts & logs" count={3} open={rows.open("events")} toggle={rows.toggle}>
          <div className="grid grid-cols-1 xl:grid-cols-[1fr_1.4fr] gap-2">
            <div className="space-y-2">
              <GPanel title="Alert rules" desc="From the approved monitoring plan · Normal / Pending (breaching) / Firing" noPad>
                <div className="max-h-[230px] overflow-auto scroll-thin">
                  <table className="w-full text-[12px]">
                    <tbody>{rules.map((r) => {
                      const state = active[r.id] ? "Firing" : streaks[r.id] ? "Pending" : "Normal";
                      const c = state === "Firing" ? (r.severity === "red" ? G.red : G.orange) : state === "Pending" ? G.yellow : G.green;
                      return (
                        <tr key={r.id} style={{ borderTop: `1px solid ${G.border}` }} title={r.rationale}>
                          <td className="px-2.5 py-1"><span className="inline-flex items-center gap-1.5 px-1.5 rounded-[2px] text-[11px] font-medium" style={{ background: `${c}22`, color: c }}>
                            <span className="w-1.5 h-1.5 rounded-full" style={{ background: c }} />{state}</span></td>
                          <td className="mono" style={{ color: G.text }}>{r.id}</td>
                          <td className="mono" style={{ color: G.muted }}>{r.kpi} {r.op} {r.threshold}</td>
                          <td style={{ color: G.muted }}>{streaks[r.id] ? `${streaks[r.id]}/${r.windows}` : `×${r.windows}`}</td>
                          <td className="pr-2.5 text-right" style={{ color: r.severity === "red" ? G.red : G.orange }}>{r.severity}{r.action === "revalidate" && <span style={{ color: G.purple }}> · reval</span>}</td>
                        </tr>);
                    })}</tbody>
                  </table>
                </div>
              </GPanel>
              <GPanel title="Alert history" noPad>
                <div className="max-h-[200px] overflow-auto scroll-thin">
                  {!d.alerts?.length ? <div className="px-2.5 py-4 text-xs" style={{ color: G.muted }}>No alerts.</div> : d.alerts.map((a: any) => (
                    <div key={a.id} className="px-2.5 py-1.5 flex items-start gap-2 text-[12px]" style={{ borderTop: `1px solid ${G.border}` }}>
                      <HeartPulse size={13} className="mt-0.5 shrink-0" style={{ color: a.severity === "red" ? G.red : G.orange }} />
                      <div className="flex-1 min-w-0"><span className="mono font-medium">{a.rule}</span> <span style={{ color: G.muted }}>{a.message}</span>
                        {a.action && <div style={{ color: G.purple }}>→ {a.action}</div>}</div>
                      <span className="mono text-[11px] shrink-0" style={{ color: G.faint }}>{new Date(a.ts).toLocaleTimeString([], { hour12: false })}</span>
                    </div>))}
                </div>
              </GPanel>
              <GPanel title="Automatic re-validations" noPad>
                {!d.revalidations?.length ? <div className="px-2.5 py-4 text-xs" style={{ color: G.muted }}>None yet. A red rule with action &quot;revalidate&quot; starts one: the monitor agent diagnoses operations, data quality, drift and outcomes, then the validator re-runs the plan on recent traffic.</div>
                  : d.revalidations.map((r: any) => {
                    const g = pendingAccept.find((x) => x.run_id === r.id);
                    return (
                      <div key={r.id} className="px-2.5 py-1.5 flex items-center gap-2 text-[12px]" style={{ borderTop: `1px solid ${G.border}` }}>
                        <Activity size={13} style={{ color: G.purple }} /><span className="mono">{r.id}</span>
                        <span style={{ color: r.status === "failed" ? G.red : r.status === "completed" ? G.green : G.yellow }}>{r.status}</span><span style={{ color: G.muted }}>{r.stage}</span>
                        <div className="ml-auto flex gap-1.5">
                          <Link href={`/agents?run=${r.id}`} className="px-2 py-0.5 rounded-[2px]" style={{ background: G.head, color: G.text }}>Agent log</Link>
                          {["completed", "waiting_gate"].includes(r.status) && <Link href={`/reports/rep_${r.id}`} className="px-2 py-0.5 rounded-[2px]" style={{ background: G.head, color: G.text }}>Report</Link>}
                          {g && <button className="px-2 py-0.5 rounded-[2px] font-medium" style={{ background: G.blue, color: "#fff" }} onClick={() => accept.mutate(g.id)}>Accept</button>}
                        </div>
                      </div>);
                  })}
              </GPanel>
            </div>
            <GPanel title="Request log" desc="Most recent scored requests (newest first)" noPad>
              <div className="max-h-[560px] overflow-auto scroll-thin mono text-[11.5px] leading-[1.7] py-1">
                {(d.tail || []).map((r: any) => {
                  const lvl = r.error ? "error" : r.flag ? "warn" : "info";
                  const c = lvl === "error" ? G.red : lvl === "warn" ? G.yellow : G.green;
                  return (
                    <div key={r.req} className="flex gap-2 px-2.5 hover:bg-white/[.03] whitespace-nowrap">
                      <span className="w-[3px] shrink-0 rounded" style={{ background: c }} />
                      <span style={{ color: G.faint }}>{new Date(r.ts * 1000).toLocaleTimeString([], { hour12: false })}</span>
                      <span style={{ color: c }} className="w-9">{lvl}</span>
                      <span style={{ color: G.cyan }}>req=</span><span>{r.req}</span>
                      <span style={{ color: G.cyan }}>latency=</span><span>{r.latency_ms}ms</span>
                      <span style={{ color: G.cyan }}>score=</span><span>{Number.isFinite(r.score) ? (Math.abs(r.score) > 100 ? Math.round(r.score) : r.score.toFixed(4)) : "NA"}</span>
                      <span style={{ color: G.cyan }}>adverse=</span><span>{r.flag ? "true" : "false"}</span>
                      {r.sev > 0 && <><span style={{ color: G.cyan }}>drift=</span><span style={{ color: G.orange }}>{r.sev}</span></>}
                      <span className="truncate" style={{ color: G.muted }}>{Object.entries(r.inputs || {}).slice(0, 5).map(([k, v]) => `${k}=${v == null ? "null" : typeof v === "number" ? Math.round((v as number) * 100) / 100 : String(v).slice(0, 14)}`).join(" ")}</span>
                    </div>
                  );
                })}
              </div>
            </GPanel>
          </div>
        </Row>

        <Row id="sim" title="Simulation controls" count={2} open={rows.open("sim")} toggle={rows.toggle}>
          <div className="grid grid-cols-1 xl:grid-cols-[2fr_1fr] gap-2">
            <GPanel title="Drift scenario" desc="Simulated: ramps a change into the live request stream">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {plan.scenarios.map((s: any) => (
                  <button key={s.id} onClick={() => setScen(s.id)} className="text-left rounded-[3px] px-2.5 py-2"
                    style={{ border: `1px solid ${(scen ?? activeScen) === s.id ? G.blue : G.border}`, background: (scen ?? activeScen) === s.id ? "rgba(87,148,242,.1)" : G.head }}>
                    <div className="text-[13px] font-medium">{s.title} {activeScen === s.id && <span style={{ color: G.orange }}>· active</span>}</div>
                    <div className="text-[11.5px]" style={{ color: G.muted }}>{s.description}</div>
                    <div className="mt-1 flex flex-wrap gap-1.5">{s.transforms.map((t: any, i: number) => <span key={i} className="mono text-[10.5px]" style={{ color: G.faint }}>{t.op}:{t.column}</span>)}</div>
                  </button>
                ))}
                {!plan.scenarios.length && <div className="text-xs" style={{ color: G.muted }}>The plan defines no scenarios.</div>}
              </div>
              <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-3 items-end mt-3 text-[12.5px]">
                <label><div className="flex justify-between" style={{ color: G.muted }}>Target severity<span className="mono" style={{ color: G.text }}>{sev.toFixed(2)}</span></div>
                  <input type="range" min={0.05} max={1} step={0.05} value={sev} onChange={(e) => setSev(+e.target.value)} className="w-full accent-[#f2495c]" /></label>
                <label><div className="flex justify-between" style={{ color: G.muted }}>Ramp over<span className="mono" style={{ color: G.text }}>{ramp}s</span></div>
                  <input type="range" min={5} max={180} step={5} value={ramp} onChange={(e) => setRamp(+e.target.value)} className="w-full accent-[#5794f2]" /></label>
                <div className="flex gap-2">
                  <button className="h-8 px-3 rounded-[3px] flex items-center gap-1.5 font-medium disabled:opacity-40" style={{ background: G.red, color: "#fff" }}
                    disabled={!(scen ?? activeScen) || act.isPending} onClick={() => act.mutate({ scenario: scen ?? activeScen, severity: sev, ramp_s: ramp })}><Zap size={14} /> Ramp in</button>
                  <button className="h-8 px-3 rounded-[3px] flex items-center gap-1.5" style={{ background: G.head, border: `1px solid ${G.border}` }}
                    disabled={act.isPending} onClick={() => act.mutate({ scenario: null, severity: 0, ramp_s: ramp })}><HeartPulse size={14} /> Heal</button>
                </div>
              </div>
              <div className="text-[12px] mt-2" style={{ color: G.muted }}>Severity now <span className="mono" style={{ color: G.text }}>{d.severity_now}</span></div>
            </GPanel>
            <GPanel title="Traffic">
              <div className="flex justify-between text-[12.5px]" style={{ color: G.muted }}>Requests / min<span className="mono font-semibold" style={{ color: G.text }}>{d.cfg?.rpm}</span></div>
              <input key={d.cfg?.rpm} type="range" min={30} max={900} step={30} defaultValue={d.cfg?.rpm} onMouseUp={(e: any) => rate.mutate({ rpm: +e.target.value })}
                onTouchEnd={(e: any) => rate.mutate({ rpm: +e.target.value })} className="w-full accent-[#73bf69]" aria-label="requests per minute" />
              <div className="flex gap-2 mt-3">
                <button className="flex-1 h-8 rounded-[3px] flex items-center justify-center gap-1.5 text-[12.5px]" style={{ background: G.head, border: `1px solid ${G.border}` }}
                  onClick={() => rate.mutate({ enabled: !d.cfg?.enabled })}>{d.cfg?.enabled ? <><Pause size={14} /> Pause</> : <><Play size={14} /> Resume</>}</button>
                <button className="flex-1 h-8 rounded-[3px] flex items-center justify-center gap-1.5 text-[12.5px]" style={{ background: "rgba(242,73,92,.15)", color: G.red, border: "1px solid rgba(242,73,92,.4)" }}
                  onClick={() => off.mutate()}><Power size={14} /> Take offline</button>
              </div>
            </GPanel>
          </div>
        </Row>
      </>}
      {model && !d?.deployed && st.isSuccess && <div className="text-sm py-10 text-center" style={{ color: G.muted }}>{model} is not serving traffic.</div>}
    </div>
  );
}

export default function MonitoringPage() {
  return <Suspense><Monitor /></Suspense>;
}
