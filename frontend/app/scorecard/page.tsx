"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { motion } from "framer-motion";
import { Play } from "lucide-react";
import { Empty, Panel, Tag } from "@/components/ui";
import { get, post } from "@/lib/api";
import { useFactory } from "@/lib/store";

export default function Scorecard() {
  const latest = useQuery({ queryKey: ["bench"], queryFn: () => get("/api/benchmarks/latest"), refetchInterval: 1500 });
  const run = useMutation({ mutationFn: () => post("/api/benchmarks/run") });
  const events = useFactory((s) => s.events);
  const start = [...events].reverse().find((e) => e.type === "benchmark" && e.payload?.phase === "start");
  const d = latest.data;
  const rows: any[] = d?.rows || [];
  const variants: any[] = start?.payload?.variants || rows.map((r) => ({ defect_type: r.defect_type, title: r.title, expected: r.expected_detector, subtle: r.detail?.subtle }));
  const byType = Object.fromEntries(rows.map((r) => [r.defect_type, r]));
  const s = d?.summary;
  const runningBatch = run.isPending || (start && start.payload.batch_id !== d?.batch_id) || (d && !d.complete && rows.length > 0);

  return (
    <div className="space-y-5 max-w-[1500px] mx-auto">
      <div className="flex items-end justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Validator Scorecard</h1>
          <p className="text-muted mt-1">Validate the validator: plant known defects in CR-001, run the same deterministic detectors, count what they catch — and what they wrongly flag on clean controls.</p>
        </div>
        <button className="btn btn-primary" onClick={() => run.mutate()} disabled={!!runningBatch}><Play size={16} /> {runningBatch ? "Running…" : "Run benchmark"}</button>
      </div>

      {s && d.complete && (
        <Panel pad={false}>
          <div className="grid md:grid-cols-3 divide-x divide-line">
            <div className="p-6"><div className="panel-title">Planted defects caught</div><div className="text-6xl font-bold num mt-2 text-pass">{s.caught}<span className="text-muted text-3xl">/{s.planted}</span></div></div>
            <div className="p-6"><div className="panel-title">False alarms on clean controls</div><div className={clsx("text-6xl font-bold num mt-2", s.false_alarms ? "text-fail" : "text-pass")}>{s.false_alarms}<span className="text-muted text-3xl">/{s.controls}</span></div></div>
            <div className="p-6"><div className="panel-title">Honest misses</div><div className="text-[15px] mt-3 text-muted">{s.planted - s.caught ? `${s.planted - s.caught} deliberately subtle variant(s) slip under fixed thresholds — shown, not hidden. Tightening thresholds would trade them for false alarms on a dataset this small.` : "None."}</div></div>
          </div>
        </Panel>
      )}

      {variants.length === 0 ? (
        <Panel><Empty title="No benchmark run yet" action={<button className="btn btn-primary" onClick={() => run.mutate()}><Play size={16} /> Run benchmark</button>}>
          Ten defects (leakage, sign flip, hidden age proxy, drift, unstable bins, calibration shift, train/test contamination, missing-value spike, plus two subtle variants) and two clean controls.
        </Empty></Panel>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-4" style={{ perspective: 1200 }}>
          {variants.map((v, i) => {
            const r = byType[v.defect_type];
            const clean = !v.expected;
            const good = r && (clean ? !r.false_alarm : r.detected);
            return (
              <motion.div key={v.defect_type} className="relative h-[170px]" style={{ transformStyle: "preserve-3d" }}
                animate={{ rotateY: r ? 180 : 0 }} transition={{ duration: 0.7, delay: r ? 0 : i * 0.02 }}>
                <div className="absolute inset-0 panel p-4 flex flex-col justify-between" style={{ backfaceVisibility: "hidden" }}>
                  <div className="flex gap-2">{clean ? <Tag tone="teal">clean control</Tag> : <Tag tone="warn">planted</Tag>}{v.subtle && <Tag>subtle</Tag>}</div>
                  <div className="font-semibold text-[15px]">{v.title}</div>
                  <div className="text-xs text-muted">{runningBatch ? "awaiting validator…" : "not yet run"}</div>
                </div>
                <div className={clsx("absolute inset-0 rounded-[14px] border p-4 flex flex-col justify-between", good ? "border-pass/50 bg-pass/[.07]" : "border-fail/50 bg-fail/[.08]")}
                  style={{ backfaceVisibility: "hidden", transform: "rotateY(180deg)" }}>
                  <div className="flex items-center justify-between">
                    <span className={clsx("text-lg font-black tracking-wider", good ? "text-pass" : "text-fail")}>
                      {clean ? (r?.false_alarm ? "FALSE ALARM" : "NO ALARM ✓") : r?.detected ? "CAUGHT ✓" : "MISSED ✗"}
                    </span>
                    {v.subtle && <Tag>subtle</Tag>}
                  </div>
                  <div className="font-semibold text-[15px]">{v.title}</div>
                  <div className="text-xs text-muted">
                    {clean ? (r?.false_alarm ? `fired: ${r.detector}` : "no detector fired") : r?.detected ? <>detector <span className="mono text-text">{r.detector}</span> · {r.severity}</> : `expected: ${v.expected}`}
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      )}
      {s?.thresholds && (
        <Panel title="Fixed detector thresholds (policy settings, not tuned per variant)">
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3 text-sm">
            {Object.entries(s.thresholds).map(([k, v]: any) => <div key={k}><div className="text-muted text-xs">{k.replace(/_/g, " ")}</div><div className="mono">{v}</div></div>)}
          </div>
        </Panel>
      )}
    </div>
  );
}
