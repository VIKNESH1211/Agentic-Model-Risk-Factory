/**
 * The 3-minute film, shot by shot (v3). `vo` is spoken in the voiced cut and shown as captions in the silent cut.
 * `clip` = a recording in public/clips (markers.json holds its timed events); `from`/`to` are marker names,
 * "marker+seconds" / "marker-seconds", or seconds. Footage plays near real speed: `maxRate` caps the speed-up and a
 * shot whose window is longer than its narration shows the end of that window (traces, gates) or its start.
 * Every claim is backed by the product or by numbers measured in the recorded run (public/impact.json).
 * The previous 4-minute cut is kept in script.v1-4min.ts.
 */
import impact from "../public/impact.json";

export type Cam = [t: number, scale: number, x: number, y: number]; // t in 0..1 of the shot; x,y = focus point 0..1
export type Shot = {
  id: string;
  vo: string;
  chapter?: string;
  clip?: string;
  from?: string | number;
  to?: string | number;
  anchor?: "start" | "end"; // which end of the window to keep when it is longer than the shot
  cam?: Cam[];
  overlay?: "agentLoop" | "sandbox" | "parityFlow" | "twoPaths" | "planToPanels" | "gateBadges" | "ledger" | "stages" | "rai";
  callout?: { text: string; x: number; y: number; at?: number };
  badge?: string; // compact "why it matters" badge over the footage
  graphic?: "title" | "innovation" | "impact" | "outro";
  minSec?: number;
  maxRate?: number;
};

const TRACE: Cam[] = [[0, 1, 0.5, 0.5], [0.2, 1.18, 0.62, 0.52], [0.85, 1.18, 0.62, 0.62], [1, 1.08, 0.6, 0.58]];
const PAGE: Cam[] = [[0, 1, 0.5, 0.5], [0.35, 1.12, 0.52, 0.45], [1, 1.05, 0.5, 0.5]];
const WIDE: Cam[] = [[0, 1, 0.5, 0.5], [1, 1.04, 0.5, 0.5]];

const m = impact as any;
export const IMPACT = {
  models: m.models_in_parallel ?? 5,
  minutes: m.cr001_to_certified_minutes ?? null,
  cost: m.total_llm_cost ?? null,
  steps: m.total_agent_steps ?? null,
  toolCalls: m.total_tool_calls ?? null,
  decisions: m.human_decisions ?? null,
};
const mins = IMPACT.minutes != null ? `about ${Math.max(1, Math.round(IMPACT.minutes))} minutes` : "minutes";
const cost = IMPACT.cost != null ? (IMPACT.cost < 0.1 ? "a few cents" : IMPACT.cost < 1 ? "less than a dollar" : `about ${Math.ceil(IMPACT.cost)} dollars`) : "a few dollars";

export const SHOTS: Shot[] = [
  { id: "title", graphic: "title", minSec: 3.6, vo: "Model Risk Factory, by Zero Gradient." },

  // ── the product, straight away
  { id: "floor", clip: "v_floor_start", from: "open", to: "start_all+9", anchor: "start", maxRate: 1.4, cam: WIDE, chapter: "Factory floor", overlay: "stages",
    vo: "This is the factory floor: five legacy R models, one governed lifecycle. One click, and five agent pipelines start working in parallel." },
  { id: "floor_gate", clip: "v_floor_start", from: "gates-3", to: "end", anchor: "end", maxRate: 1.3, chapter: "Human in the loop",
    cam: [[0, 1, 0.5, 0.5], [0.35, 1.3, 0.3, 0.5], [1, 1.3, 0.3, 0.5]],
    vo: "Every stage ends at a human gate. You can approve right from the floor," },
  { id: "approvals", clip: "v_approvals", from: "open", to: "end", anchor: "end", maxRate: 1.6, cam: PAGE, overlay: "gateBadges",
    vo: "or review it properly in the approvals queue, with the agent's reasoning and evidence. Approve one, or the rest in bulk." },

  // ── how the agents work
  { id: "intake", clip: "v_trace_intake", from: "tool_probe_legacy-4", to: "end", anchor: "end", maxRate: 2, cam: TRACE, overlay: "agentLoop", chapter: "Agents at work",
    vo: "Each agent plans, thinks, calls real tools, and checks the result. Intake runs the R script unmodified, in a sealed sandbox." },
  { id: "plans_floor", clip: "v_floor_plans", from: 0.6, to: "end", maxRate: 1.2, cam: WIDE, minSec: 5,
    vo: "Meanwhile, the rest of the estate moves through documentation and planning in parallel." },

  // ── model workbench: what each stage produced
  { id: "workbench", clip: "v_workbench", from: "tab_spec-1", to: "tab_monitoring+5", maxRate: 3, cam: PAGE, chapter: "Model workbench",
    vo: "Everything the agents produce lands in the model workbench: spec, contract, documentation, validation plan and monitoring plan, each versioned and approved." },
  { id: "kpis", clip: "v_trace_document", from: "stage-1", to: "tool_draft_monitoring_plan+9", anchor: "end", maxRate: 2, cam: TRACE, overlay: "planToPanels", badge: "KPIs designed by the agent",
    vo: "The documentation agent decides what to test and what to watch: the checks, KPIs, thresholds and alert rules for this model." },

  // ── redevelopment and proof
  { id: "redevelop", clip: "v_trace_redevelop", from: "tool_check_parity-5", to: "end", anchor: "end", maxRate: 2.2, cam: TRACE, overlay: "parityFlow", chapter: "R to Python",
    vo: "Redevelopment uses all of it: the spec, the contract, the R reference outputs. The agent writes the Python, and if parity fails, the gap goes back and it retries." },
  { id: "parity", clip: "v_parity", from: "open", to: "end", maxRate: 1.5, cam: [[0, 1, 0.5, 0.5], [0.3, 1.06, 0.45, 0.4], [1, 1.02, 0.5, 0.5]], badge: "Proven, not assumed",
    vo: "The result is a parity certificate. Every row within one in a million, every decision identical." },
  { id: "rehost", clip: "v_rehost", from: "open", to: "overview+6", maxRate: 1.6, cam: PAGE, overlay: "twoPaths",
    vo: "The random forest can't be matched exactly, so it's rehosted instead. No fake parity." },
  { id: "graph", clip: "v_graph", from: "open", to: "end", maxRate: 1.4, cam: PAGE, chapter: "Blast radius",
    callout: { text: "Everything downstream of CR-001", x: 0.4, y: 0.32, at: 0.35 },
    vo: "The dependency graph shows each model's blast radius: everything a defect would reach." },

  // ── monitoring
  { id: "kpi_edit", clip: "v_kpi_edit", from: "agent_note-1", to: "end", anchor: "end", maxRate: 2.4, cam: PAGE, chapter: "Live monitoring",
    vo: "Once deployed, the agent's plan becomes a live, Grafana-style dashboard. People can add panels, change KPIs, and approve a new version." },
  { id: "drift", clip: "v_monitor", from: "ramp-1", to: "red+3", anchor: "end", maxRate: 6, badge: "Reviewer-added stress scenario", cam: [[0, 1, 0.5, 0.5], [0.5, 1.1, 0.5, 0.32], [1, 1.04, 0.5, 0.4]],
    vo: "We push a population shift. Rules go from normal, to pending, to firing, and re-validation starts on its own." },
  { id: "diagnose", clip: "v_trace_diagnose", from: "open", to: "end", anchor: "end", maxRate: 2, cam: TRACE, badge: "Closed loop · human sign-off",
    vo: "The monitor agent diagnoses the drift, and a person signs off the re-validation." },

  // ── responsible AI and governance
  { id: "gov", clip: "v_governance", from: "open", to: "end", anchor: "end", maxRate: 2.6, cam: PAGE, overlay: "rai", chapter: "Responsible AI",
    vo: "Responsible AI is built in: fairness checks, SS1/23 controls, and prompt-injection tests. And every step is hash-chained, so tampering is caught." },

  // ── why it matters
  { id: "innovation", graphic: "innovation", minSec: 9.5,
    vo: "What's new: evidence-bound agents, translations proven row by row, agent-designed monitoring, and a person at every gate." },
  { id: "impact", graphic: "impact", minSec: 12,
    vo: `The impact: CR-001 went from legacy R to certified Python in ${mins}, reviews included, for ${cost} of model calls.` },
  { id: "outro", graphic: "outro", minSec: 3.5, vo: "Model Risk Factory." },
];

export const INNOVATION = [
  { k: "Evidence-bound agents", v: "Plan · think · call tools · decide, with mandatory steps and HOLD guardrails" },
  { k: "Proven translation", v: "Legacy R → Python certified row by row, or rehosted, never faked" },
  { k: "Numbers you can audit", v: "The LLM never writes a figure: every number links to code, data and a recompute" },
  { k: "Agent-designed monitoring", v: "KPIs and alert rules chosen per model, editable by people, alerts trigger re-validation" },
  { k: "Human in the loop", v: "A gate at every stage, decided from the floor or the queue, on a hash-chained ledger" },
];

export const WORDS = SHOTS.reduce((n, s) => n + s.vo.split(/\s+/).length, 0);
