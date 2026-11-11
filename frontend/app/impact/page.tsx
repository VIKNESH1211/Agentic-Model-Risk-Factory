"use client";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { CountUp, Panel, Tag } from "@/components/ui";
import { get, post } from "@/lib/api";

const SLIDERS = [
  { k: "models_per_year", label: "Models validated per year", min: 5, max: 200, step: 5, fmt: (v: number) => `${v}` },
  { k: "manual_weeks_per_validation", label: "Manual effort per validation", min: 2, max: 20, step: 1, fmt: (v: number) => `${v} weeks` },
  { k: "validator_cost_per_week_gbp", label: "Loaded validator cost per week", min: 1000, max: 6000, step: 250, fmt: (v: number) => `£${v.toLocaleString()}` },
  { k: "human_review_hours_per_model", label: "Human review kept per model", min: 4, max: 80, step: 2, fmt: (v: number) => `${v} h` },
];

export default function Impact() {
  const defaults = useQuery({ queryKey: ["roi-defaults"], queryFn: () => get("/api/roi/defaults") });
  const [inputs, setInputs] = useState<Record<string, number>>({});
  const [debounced, setDebounced] = useState(inputs);
  useEffect(() => { const t = setTimeout(() => setDebounced(inputs), 200); return () => clearTimeout(t); }, [inputs]);
  const roi = useQuery({ queryKey: ["roi", debounced], queryFn: () => post("/api/roi", { inputs: debounced }), placeholderData: (p) => p });
  const r = roi.data;
  const val = (k: string) => inputs[k] ?? defaults.data?.[k]?.value ?? 0;

  return (
    <div className="space-y-5 max-w-[1500px] mx-auto">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Business Impact</h1>
        <p className="text-muted mt-1">Measured run time and LLM cost from this factory, combined with assumptions you can change. Every input says where it came from.</p>
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-[420px_1fr] gap-5">
        <Panel title="Assumptions">
          <div className="space-y-6">
            {SLIDERS.map((s) => (
              <div key={s.k}>
                <div className="flex justify-between items-baseline">
                  <label htmlFor={s.k} className="text-[15px]">{s.label}</label>
                  <span className="mono font-bold">{s.fmt(val(s.k))}</span>
                </div>
                <input id={s.k} type="range" min={s.min} max={s.max} step={s.step} value={val(s.k)} className="w-full accent-[#2dd4bf] mt-2"
                  onChange={(e) => setInputs({ ...inputs, [s.k]: +e.target.value })} />
                <div className="mt-1"><Tag tone={inputs[s.k] !== undefined ? "teal" : "muted"}>{inputs[s.k] !== undefined ? "user" : defaults.data?.[s.k]?.source ?? "assumed"}</Tag></div>
              </div>
            ))}
            {r && (
              <div className="border-t border-line pt-4 space-y-2 text-sm">
                <div className="flex justify-between"><span>Factory run time (CR-001)</span><span className="mono">{r.measured.factory_runtime_s.value}s <Tag tone="teal">{r.measured.factory_runtime_s.source}</Tag></span></div>
                <div className="flex justify-between"><span>LLM spend</span><span className="mono">${r.measured.llm_cost_usd.value} <Tag tone="teal">measured</Tag></span></div>
                {r.measured_run_id && <div className="text-xs text-faint">from run <span className="mono">{r.measured_run_id}</span></div>}
              </div>
            )}
          </div>
        </Panel>
        <div className="space-y-5">
          {r && (
            <>
              <div className="grid md:grid-cols-3 gap-5">
                <Panel title="Hours released / year"><div className="text-5xl font-bold text-teal"><CountUp value={r.annual.hours_saved} /></div><div className="text-muted mt-1">≈ <CountUp value={r.annual.fte_released} decimals={1} /> FTE</div></Panel>
                <Panel title="Cost avoided / year"><div className="text-5xl font-bold text-pass"><CountUp value={r.annual.cost_saved_gbp} prefix="£" /></div><div className="text-muted mt-1">before platform & run costs <Tag tone="warn">illustrative</Tag></div></Panel>
                <Panel title="Machine-time compression"><div className="text-5xl font-bold text-agent"><CountUp value={r.compression_x} />×</div><div className="text-muted mt-1 text-sm">{r.compression_note}</div></Panel>
              </div>
              <Panel title="Per model">
                <div className="grid grid-cols-2 gap-8">
                  {[["Manual", r.per_model.manual_hours, r.per_model.manual_cost_gbp, "text-muted"], ["Factory + human review", r.per_model.factory_hours, r.per_model.factory_cost_gbp, "text-teal"]].map(([l, h, c, tone]: any) => (
                    <div key={l}>
                      <div className="text-sm text-muted">{l}</div>
                      <div className={`text-4xl font-bold mt-1 ${tone}`}><CountUp value={h} decimals={h < 100 ? 1 : 0} /> h</div>
                      <div className="text-lg mt-1">£<CountUp value={c} /></div>
                      <div className="h-3 rounded-full bg-white/5 mt-3 overflow-hidden"><div className={`h-full ${tone === "text-teal" ? "bg-teal" : "bg-muted"}`} style={{ width: `${Math.max(2, (100 * h) / r.per_model.manual_hours)}%`, transition: "width .8s" }} /></div>
                    </div>
                  ))}
                </div>
              </Panel>
              <Panel title="Who benefits">
                <ul className="grid md:grid-cols-2 gap-3 text-[15px]">
                  <li><b>Model Risk / 2nd line</b> — validators review evidence instead of rebuilding it; every number is reproducible.</li>
                  <li><b>Model owners</b> — legacy R/SAS migrated to tested Python with a parity certificate.</li>
                  <li><b>Audit / regulators</b> — tamper-evident trail mapped to SS1/23 controls.</li>
                  <li><b>Customers</b> — faster detection of drift and unfair outcomes in live decisions.</li>
                </ul>
              </Panel>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
