/**
 * The film, shot by shot. `vo` is spoken in the voiced cut and shown as captions in the silent cut.
 * `clip` refers to a recording in public/clips (markers.json holds its timed events); `from`/`to` are marker
 * names or seconds into that clip. `overlay` names a motion-graphics layer drawn over the footage.
 * Every claim here is backed by code (see the plan's "facts" list) — keep it that way when editing.
 */
export type Cam = [t: number, scale: number, x: number, y: number]; // t in 0..1 of the shot; x,y = focus point 0..1
export type Shot = {
  id: string;
  vo: string;
  chapter?: string;
  clip?: string;
  from?: string | number;
  to?: string | number;
  cam?: Cam[];
  overlay?: "agentLoop" | "sandbox" | "parityFlow" | "twoPaths" | "planToPanels" | "gateBadges" | "ledger";
  callout?: { text: string; x: number; y: number; at?: number };
  graphic?: "open" | "problem" | "map" | "standsOut" | "recap" | "outro";
  minSec?: number;
  maxRate?: number; // allow a faster time-lapse for this shot (shown on screen)
};

const TRACE: Cam[] = [[0, 1, 0.5, 0.5], [0.18, 1.25, 0.64, 0.55], [0.85, 1.25, 0.64, 0.68], [1, 1.12, 0.62, 0.6]];
const PAGE: Cam[] = [[0, 1, 0.5, 0.5], [0.3, 1.18, 0.55, 0.45], [1, 1.1, 0.5, 0.55]];

export const SHOTS: Shot[] = [
  { id: "open", graphic: "open", minSec: 6,
    vo: "Model Risk Factory, by Zero Gradient. Legacy R models, rebuilt and governed by AI agents, with people in control." },
  { id: "problem", graphic: "problem",
    vo: "Banks carry large estates of legacy R models, often undocumented, and validation takes weeks of manual work, under SR 11-7 and SS1/23 expectations." },
  { id: "map", graphic: "map", chapter: "The lifecycle",
    vo: "One lifecycle for every model: six specialist agents, a human gate between every stage, and a hash-chained ledger underneath." },
  { id: "floor", clip: "s01_floor", from: "open", to: "end", cam: PAGE,
    callout: { text: "Reviewer starts CR-001 (scorecard) and CR-002 (random forest)", x: 0.33, y: 0.42, at: 0.35 },
    vo: "This is the factory floor. A reviewer starts two models: CR-001, a credit scorecard, and CR-002, a random-forest challenger." },

  { id: "intake", clip: "s02_intake", from: "open", to: "tool_probe_legacy", cam: TRACE, overlay: "agentLoop", chapter: "1 · Discover",
    vo: "This is the intake agent's trace. It plans, reasons and calls real tools: it parses the R script, reads the data room, and runs the legacy code unmodified." },
  { id: "sandbox", clip: "s02_intake", from: "tool_probe_legacy", to: "tool_draft_spec", overlay: "sandbox", minSec: 5,
    vo: "That run happens in an attached R sandbox: no network, a read-only file system, and hard CPU, memory and process limits." },
  { id: "so_sandbox", graphic: "standsOut", minSec: 4,
    vo: "The legacy code itself is the source of truth, and the agent cannot finish until that evidence exists." },

  { id: "gate1", clip: "s03_gate1_review", from: "open", to: "end", cam: PAGE, overlay: "gateBadges", chapter: "Human gate",
    vo: "Now the first human gate. The reviewer reads the drafted specification, checks it against the script, and approves, with a comment that goes to the ledger." },
  { id: "doc", clip: "s06_document", from: "open", to: "done", cam: TRACE, chapter: "2 · Document",
    vo: "The documentation agent applies the policy library, reviews the code independently, traces lineage, and drafts the documentation and both plans." },
  { id: "plans", clip: "s07_gate2_sendback", from: "monitoring_plan", to: "end", cam: PAGE, overlay: "planToPanels", chapter: "Human gate · send back",
    vo: "At the next gate, the reviewer reads the monitoring plan the agent designed: its own KPIs, thresholds and alert rules. And sends it back: add data-quality alerts." },
  { id: "redraft", clip: "s07b_doc_redraft", from: "open", to: "done", cam: [[0, 1, 0.5, 0.5], [0.2, 1.3, 0.5, 0.45], [1, 1.3, 0.5, 0.55]],
    vo: "The agent receives the comment as its top-priority instruction, and re-plans against it." },
  { id: "approve2", clip: "s07c_gate2_approve", from: "open", to: "end", cam: PAGE,
    vo: "The revised plan carries the data-quality alerts: missing inputs and out-of-range values above five percent. The reviewer approves, on the ledger." },
  { id: "so_gate", graphic: "standsOut", minSec: 4,
    vo: "Reviewers steer agents in plain language. Approve, send back, or reject, at every stage." },
  { id: "graph", clip: "s08_graph", from: "open", to: "end", cam: PAGE, chapter: "Dependency graph",
    callout: { text: "Blast radius: who consumes CR-001's outputs", x: 0.42, y: 0.35, at: 0.15 },
    vo: "Lineage becomes a dependency graph, with each model's blast radius. Reviewers can add a dependency the code doesn't show, and it's audited." },

  { id: "redevelop", clip: "s09_redevelop", from: "open", to: "done", cam: TRACE, overlay: "parityFlow", chapter: "3 · Redevelop · translate",
    vo: "Redevelopment. The agent writes an R export step, runs it in the sandbox, writes a Python translation, and tests it out of process against every row. Any gap goes back to the agent." },
  { id: "parity", clip: "s10_parity", from: "open", to: "end", cam: [[0, 1, 0.5, 0.5], [0.25, 1.06, 0.45, 0.4], [1, 1.03, 0.5, 0.5]],
    vo: "The result is a parity certificate. Scores and coefficients within one in a million, every decision identical, single-request scoring checked, and a fingerprint over the whole certificate." },
  { id: "gate3", clip: "s11_gate3_approvals", from: "open", to: "end", cam: PAGE,
    vo: "The reviewer approves it from the approvals queue." },
  { id: "guard", clip: "x_blocked_trace", from: "open", to: "end", cam: [[0, 1, 0.5, 0.5], [0.25, 1.3, 0.5, 0.5], [1, 1.3, 0.5, 0.6]], chapter: "Guardrails",
    vo: "And when an agent can't succeed, it says so. In an earlier run the sandbox rejected its export five times, so the agent stopped and recommended HOLD." },
  { id: "guard_gate", clip: "x_blocked_gate", from: "open", to: "end", cam: [[0, 1, 0.5, 0.5], [0.3, 1.35, 0.4, 0.3], [1, 1.35, 0.4, 0.3]],
    vo: "The gate itself refuses approval until the evidence exists." },
  { id: "so_parity", graphic: "standsOut", minSec: 4,
    vo: "Not 'the AI rewrote it'. Proven equivalent, row for row, or stopped for a person." },
  { id: "rehost", clip: "s12_rehost", from: "open", to: "end", cam: PAGE, overlay: "twoPaths", chapter: "3 · Redevelop · rehost",
    vo: "CR-002 takes a different path. It's a ranger random forest, which can't be reproduced exactly outside R. So it is rehosted: validated on its R outputs, never deployed as a translation." },
  { id: "so_rehost", graphic: "standsOut", minSec: 4,
    vo: "No fake parity. A governed path for what cannot be translated." },

  { id: "validate", clip: "s13_validate", from: "open", to: "done", cam: TRACE, chapter: "4 · Validate",
    vo: "The validator agent runs the approved plan, then investigates: weak segments, stress tests, a challenger model, and edge-case fuzzing." },
  { id: "report", clip: "s14_report", from: "open", to: "end", cam: PAGE,
    vo: "The validator is no rubber stamp: this report rates the model not fit for use. And every number is evidence, with its definition, hashes and code. Reproduce it live." },
  { id: "so_report", graphic: "standsOut", minSec: 3.5,
    vo: "The language model never writes a number." },

  { id: "deploy", clip: "s15_gate4_deploy", from: "open", to: "end", cam: PAGE, chapter: "5 · Monitor",
    vo: "Here the reviewer accepts those findings for a monitored deployment, on the record. The monitor agent stands up the endpoint and arms the rules it designed." },
  { id: "monitor", clip: "s16_monitor", from: "open", to: "pick_scenario", cam: [[0, 1, 0.5, 0.5], [0.5, 1.12, 0.5, 0.42], [1, 1, 0.5, 0.5]],
    vo: "Live monitoring: health, operations, data quality, drift, decisions and outcomes, all from the agent's plan." },
  { id: "drift", clip: "s16_monitor", from: "ramp", to: "end", maxRate: 5.5, cam: [[0, 1, 0.5, 0.5], [0.55, 1.12, 0.5, 0.3], [0.8, 1, 0.5, 0.5], [1, 1, 0.5, 0.5]],
    vo: "Now we push a population shift into live traffic. Rules move from normal, to pending, to firing." },
  { id: "diagnose", clip: "s17_diagnose", from: "open", to: "done", cam: TRACE,
    vo: "A red alert hands control back to the agents. The monitor agent diagnoses data quality, drift and score shift, and the validator re-runs the plan on live traffic." },
  { id: "accept", clip: "s18_accept", from: "open", to: "end", cam: PAGE,
    vo: "And a person closes the loop: accept the re-validation, with a comment, on the ledger." },
  { id: "so_monitor", graphic: "standsOut", minSec: 4,
    vo: "Monitoring designed by the agent, enforced automatically, signed off by a person." },

  { id: "gov", clip: "s19_governance", from: "open", to: "end", cam: PAGE, overlay: "ledger", chapter: "Governance",
    vo: "Finally, governance. The ledger is hash-chained. Verify it. Tamper with one stored entry, verify again, and the break is found at that exact entry." },
  { id: "recap", clip: "s20_floor_end", from: "open", to: "end", graphic: "recap",
    vo: "Two models: one translated, proven, deployed and monitored; one rehosted and closed. Reasoned by agents, decided by people." },
  { id: "outro", graphic: "outro", minSec: 5, vo: "Model Risk Factory. By Zero Gradient." },
];

/** "Why it stands out" card text, keyed by shot id. */
export const STANDS_OUT: Record<string, { title: string; points: string[] }> = {
  so_sandbox: { title: "Evidence before AI", points: ["Unmodified legacy R runs offline, read-only, resource-capped", "Agents can't finish until mandatory tools succeed"] },
  so_gate: { title: "Human in the loop, by design", points: ["Approve · send back with instructions · reject", "Blocked stages can't be approved", "Every decision signed into the ledger"] },
  so_parity: { title: "Proven, not assumed", points: ["Every row within 1e-6 · coefficients within 1e-6", "100% decision agreement · single-request scoring", "Fingerprinted certificate", "Repeated failure → HOLD, gate blocked"] },
  so_rehost: { title: "Honest about limits", points: ["Tree ensembles are rehosted, not faked", "Validated in R · never deployed as a translation"] },
  so_report: { title: "Traceable numbers", points: ["Every figure: definition, data + code hashes, function", "Reproduce any number live"] },
  so_monitor: { title: "Closed-loop monitoring", points: ["KPIs and alert rules chosen per model by the agent", "Red alert → agent diagnosis → re-validation", "A person signs off"] },
};

export const WORDS = SHOTS.reduce((n, s) => n + s.vo.split(/\s+/).length, 0);
export {};
