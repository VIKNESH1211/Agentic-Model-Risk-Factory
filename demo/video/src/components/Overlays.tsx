import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { T, glass } from "../theme";

/** Floating glass card that slides in on the right of the frame. */
const Card: React.FC<{ children: React.ReactNode; delay?: number; frames: number; w?: number; top?: number; side?: "right" | "left" }> = ({ children, delay = 10, frames, w = 470, top = 190, side = "right" }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: f - delay, fps, config: { damping: 18, mass: 0.7 } });
  const out = interpolate(f, [frames - 14, frames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", [side]: 58, top, width: w, ...glass, padding: "26px 28px", opacity: s * out,
      transform: `translateX(${(1 - s) * (side === "right" ? 60 : -60)}px)`, fontFamily: T.font, color: T.ink }}>
      {children}
    </div>
  );
};
const H: React.FC<{ children: React.ReactNode; c?: string }> = ({ children, c = T.tealSoft }) => (
  <div style={{ fontSize: 15, fontWeight: 800, letterSpacing: 3, color: c, marginBottom: 16 }}>{children}</div>
);
const useStep = (n: number, every: number, delay = 16) => {
  const f = useCurrentFrame();
  return Math.max(-1, Math.floor((f - delay) / every)) % (n + 1);
};

// ---------------------------------------------------------------- agent loop + guardrails
const LOOP = [["PLAN", "goal, tools, mandatory steps", T.tealSoft], ["THINK", "reason about evidence so far", T.muted], ["CALL", "invoke a real tool", T.violetSoft],
  ["RESULT", "deterministic output", T.blue], ["DECIDE", "recommend promote / hold", T.green]] as const;
export const AgentLoop: React.FC<{ frames: number }> = ({ frames }) => {
  const step = useStep(LOOP.length, 22);
  return (
    <Card frames={frames} side="left">
      <H>HOW AN AGENT WORKS</H>
      {LOOP.map(([k, d, c], i) => (
        <div key={k} style={{ display: "flex", alignItems: "center", gap: 14, padding: "9px 12px", borderRadius: 10, marginBottom: 6,
          background: step >= i ? "rgba(139,92,246,.12)" : "transparent", border: `1px solid ${step === i ? c : "transparent"}`, transition: "none" }}>
          <span style={{ fontFamily: T.mono, fontSize: 17, fontWeight: 800, color: c, width: 84 }}>{k}</span>
          <span style={{ fontSize: 19, color: step >= i ? T.ink : T.faint }}>{d}</span>
        </div>
      ))}
      <div style={{ height: 1, background: T.line, margin: "16px 0" }} />
      <H c={T.amber}>GUARDRAILS</H>
      {["Can't finish until mandatory tools succeed", "Step budget → deterministic fallback", "Hard blockers force HOLD"].map((g) => (
        <div key={g} style={{ fontSize: 18, color: "#cbd5e1", marginBottom: 8 }}>▸ {g}</div>
      ))}
    </Card>
  );
};

// ---------------------------------------------------------------- R sandbox
const FLAGS = ["--network none", "--read-only", "--cpus 2", "--memory 2g", "--pids-limit 256", "--security-opt no-new-privileges"];
export const Sandbox: React.FC<{ frames: number }> = ({ frames }) => {
  const f = useCurrentFrame();
  return (
    <Card frames={frames} w={520} side="left">
      <H>ATTACHED R SANDBOX</H>
      <div style={{ border: `2px dashed ${T.teal}`, borderRadius: 14, padding: 18, position: "relative" }}>
        <div style={{ fontFamily: T.mono, fontSize: 17, color: T.muted }}>docker run</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "10px 0 16px" }}>
          {FLAGS.map((fl, i) => {
            const o = interpolate(f, [16 + i * 7, 24 + i * 7], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
            return <span key={fl} style={{ opacity: o, fontFamily: T.mono, fontSize: 16, color: T.tealSoft, background: "rgba(20,184,166,.12)", borderRadius: 8, padding: "5px 9px" }}>{fl}</span>;
          })}
        </div>
        <div style={{ background: "rgba(245,158,11,.1)", border: `1px solid ${T.amber}`, borderRadius: 10, padding: "12px 14px", fontFamily: T.mono, fontSize: 17, color: "#fcd34d" }}>
          cr001_scorecard.R <span style={{ color: T.muted }}>· unmodified</span>
        </div>
        <div style={{ position: "absolute", right: -14, top: -14, background: T.bg0, border: `2px solid ${T.red}`, borderRadius: 20, padding: "4px 10px", fontSize: 14, color: T.red, fontWeight: 700 }}>no network</div>
      </div>
      <div style={{ fontSize: 18, color: T.muted, marginTop: 16, lineHeight: 1.45 }}>Outputs are exported as a standard bundle and become the reference every later step is checked against.</div>
    </Card>
  );
};

// ---------------------------------------------------------------- R → Python parity flow
const FLOW = ["Legacy R run (sandbox)", "R export epilogue → bundle", "Python translation (LLM draft)", "Out-of-process parity: every row", "Certificate + fingerprint"];
export const ParityFlow: React.FC<{ frames: number }> = ({ frames }) => {
  const step = useStep(FLOW.length, 26);
  return (
    <Card frames={frames} w={500} side="left">
      <H>R → PYTHON, PROVEN</H>
      {FLOW.map((s, i) => (
        <React.Fragment key={s}>
          <div style={{ padding: "11px 14px", borderRadius: 10, fontSize: 19, background: step >= i ? (i === 4 ? "rgba(34,197,94,.14)" : "rgba(20,184,166,.10)") : "rgba(148,163,184,.06)",
            border: `1px solid ${step >= i ? (i === 4 ? T.green : T.teal) : T.line}`, color: step >= i ? T.ink : T.faint }}>{s}</div>
          {i < FLOW.length - 1 && <div style={{ textAlign: "center", color: T.faint, fontSize: 16, lineHeight: "20px" }}>↓</div>}
        </React.Fragment>
      ))}
      <div style={{ marginTop: 14, fontSize: 17, color: T.amber }}>↺ on a parity gap, the exact rows and values go back to the agent</div>
    </Card>
  );
};

// ---------------------------------------------------------------- translate vs rehost
export const TwoPaths: React.FC<{ frames: number }> = ({ frames }) => {
  const lane = (title: string, steps: string[], c: string, d: number) => (
    <div style={{ marginBottom: 20 }}>
      <div style={{ fontFamily: T.mono, fontSize: 19, fontWeight: 800, color: c, marginBottom: 10 }}>{title}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        {steps.map((s, i) => <Pill key={s} text={s} c={c} d={d + i * 8} last={i === steps.length - 1} />)}
      </div>
    </div>
  );
  return (
    <Card frames={frames} w={560}>
      <H>TWO GOVERNED PATHS</H>
      {lane("CR-001 · GLM scorecard", ["translate", "parity PASS", "deployable", "monitored"], T.teal, 14)}
      {lane("CR-002 · ranger forest", ["rehost", "validated in R", "not deployed"], T.violet, 40)}
      <div style={{ fontSize: 17, color: T.muted, lineHeight: 1.45 }}>The intake agent chooses the strategy from what the probe finds; the reviewer approves it at the gate.</div>
    </Card>
  );
};
const Pill: React.FC<{ text: string; c: string; d: number; last?: boolean }> = ({ text, c, d, last }) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [d, d + 8], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <span style={{ opacity: o, fontSize: 18, padding: "7px 12px", borderRadius: 9, border: `1px solid ${c}`, color: last ? "#fff" : T.ink, background: last ? c : "transparent" }}>{text}</span>;
};

// ---------------------------------------------------------------- agent-chosen KPIs → dashboard
export const PlanToPanels: React.FC<{ frames: number }> = ({ frames }) => {
  // CR-001's approved plan (v2), as drafted by the documentation agent
  const kpis = ["score_psi > 0.25 · red · revalidate", "worst_csi > 0.25 · red · revalidate", "drifted_features > 2", "missing_input_rate > 5%", "out_of_range_rate > 5%", "unseen_category_rate > 2%"];
  return (
    <Card frames={frames} w={520}>
      <H>AGENT-DESIGNED MONITORING</H>
      {kpis.map((k, i) => <Row key={k} text={k} d={14 + i * 8} />)}
      <div style={{ fontSize: 17, color: T.muted, marginTop: 14, lineHeight: 1.45 }}>Linted against the KPI catalogue (known KPI, correct alert direction) before a person approves. These become the live dashboard and alert rules.</div>
    </Card>
  );
};
const Row: React.FC<{ text: string; d: number }> = ({ text, d }) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [d, d + 8], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <div style={{ opacity: o, transform: `translateX(${(1 - o) * 16}px)`, fontFamily: T.mono, fontSize: 17, color: T.ink, padding: "8px 12px", borderLeft: `3px solid ${T.violet}`, background: "rgba(139,92,246,.08)", borderRadius: 6, marginBottom: 7 }}>{text}</div>;
};

// ---------------------------------------------------------------- gate decisions
export const GateBadges: React.FC<{ frames: number }> = ({ frames }) => (
  <Card frames={frames} w={440} delay={20}>
    <H c={T.amber}>EVERY GATE, A PERSON DECIDES</H>
    {[["✓ Approve", T.green, "promote to the next stage"], ["↺ Send back", T.amber, "agent re-runs with your comment"], ["✕ Reject", T.red, "stop the lifecycle"]].map(([k, c, d]) => (
      <div key={k} style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12 }}>
        <span style={{ fontWeight: 800, fontSize: 21, color: c, width: 150 }}>{k}</span><span style={{ fontSize: 18, color: "#cbd5e1" }}>{d}</span>
      </div>
    ))}
    <div style={{ fontSize: 17, color: T.muted, marginTop: 6 }}>Incomplete stages are blocked from approval.</div>
  </Card>
);

// ---------------------------------------------------------------- ledger chain
export const Ledger: React.FC<{ frames: number }> = ({ frames }) => {
  const f = useCurrentFrame();
  const broken = f > frames * 0.55;
  return (
    <Card frames={frames} w={440} side="left" top={560}>
      <H>HASH-CHAINED LEDGER</H>
      {[0, 1, 2, 3].map((i) => {
        const bad = broken && i === 2;
        return (
          <div key={i}>
            <div style={{ fontFamily: T.mono, fontSize: 16, padding: "10px 12px", borderRadius: 8, border: `1px solid ${bad ? T.red : T.line}`, background: bad ? "rgba(244,63,94,.12)" : "rgba(148,163,184,.05)", color: bad ? "#fda4af" : T.muted }}>
              #{1840 + i} hash {["9f2c…e1", "41ab…07", bad ? "≠ recomputed" : "c77d…3a", "08e5…b9"][i]}
            </div>
            {i < 3 && <div style={{ textAlign: "center", color: broken && i >= 1 && i <= 2 ? T.red : T.faint, lineHeight: "18px" }}>⛓</div>}
          </div>
        );
      })}
    </Card>
  );
};

// ---------------------------------------------------------------- lifecycle strip over the floor: what each stage does
const STAGES = [["Discover", "Intake agent · runs the legacy R", T.tealSoft], ["Document", "Docs, validation & monitoring plans", T.blue],
  ["Redevelop", "R → Python, parity-certified", T.violetSoft], ["Validate", "Checks, challengers, report", T.green], ["Monitor", "Live KPIs, alerts, re-validation", T.amber]] as const;
export const Stages: React.FC<{ frames: number }> = ({ frames }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const out = interpolate(f, [frames - 14, frames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", left: 230, right: 230, bottom: 112, display: "flex", gap: 10, opacity: out }}>
      {STAGES.map(([k, d, c], i) => {
        const s = spring({ frame: f - 20 - i * 9, fps, config: { damping: 16, mass: 0.6 } });
        return (
          <React.Fragment key={k}>
            <div style={{ ...glass, flex: 1, borderRadius: 14, padding: "14px 16px", opacity: s, transform: `translateY(${(1 - s) * 30}px)`, borderTop: `3px solid ${c}`, fontFamily: T.font }}>
              <div style={{ fontSize: 22, fontWeight: 800, color: c }}>{i + 1} · {k}</div>
              <div style={{ fontSize: 16, color: "#cbd5e1", marginTop: 4 }}>{d}</div>
            </div>
            {i < STAGES.length - 1 && <div style={{ alignSelf: "center", opacity: s, width: 26, height: 26, borderRadius: 13, border: `2px solid ${T.amber}`, background: T.bg1, display: "grid", placeItems: "center", color: T.amber, fontSize: 13, fontWeight: 900, flexShrink: 0 }}>‖</div>}
          </React.Fragment>
        );
      })}
    </div>
  );
};

// ---------------------------------------------------------------- responsible AI checklist
export const Rai: React.FC<{ frames: number }> = ({ frames }) => {
  const step = useStep(5, 26, 10);
  const items = [["Fairness", "disparate-impact checks in every validation"], ["SS1/23 controls", "scored from evidence, per model"],
    ["Prompt injection", "agents tested against hostile files"], ["Guardrails", "mandatory tools, step budgets, forced HOLD"], ["Tamper-evident", "every step and decision hash-chained"]];
  return (
    <Card frames={frames} side="right" w={500} top={200}>
      <H>RESPONSIBLE AI, BUILT IN</H>
      {items.map(([k, d], i) => (
        <div key={k} style={{ display: "flex", gap: 14, alignItems: "flex-start", marginBottom: 14, opacity: step >= i ? 1 : 0.25 }}>
          <span style={{ width: 28, height: 28, borderRadius: 14, flexShrink: 0, background: "rgba(20,184,166,.15)", border: `2px solid ${T.teal}`, display: "grid", placeItems: "center", color: T.tealSoft, fontSize: 15, fontWeight: 900 }}>✓</span>
          <div><div style={{ fontSize: 21, fontWeight: 700 }}>{k}</div><div style={{ fontSize: 17, color: T.muted }}>{d}</div></div>
        </div>
      ))}
    </Card>
  );
};
