/**
 * Records the real product, end to end, as one WebM clip per scene + a markers.json of timed events.
 *
 *   CR-001  scorecard GLM   → translate → parity PASS → validated → deployed → drift → re-validation accepted
 *   CR-002  ranger forest   → REHOST (validated in R, not deployable) → stops after validation
 *
 * The script plays the reviewer: it opens each gate, reads, and approves / sends back with a comment.
 * Usage:  npx tsx capture/record.ts            (full run — RESETS the demo data first)
 *         npx tsx capture/record.ts --only s14_report   (re-record one scene against the current state)
 */
import { chromium, type Browser, type BrowserContext, type Page } from "playwright";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const WEB = "http://localhost:3210";
const API = "http://localhost:8100";
const OUT = join(import.meta.dirname, "..", "public", "clips");
const TMP = join(import.meta.dirname, "..", ".rec-tmp");
const W = 1920, H = 1080;
const REVIEWER = "Model Risk Officer";
// Remotion ships an ffmpeg with libx264; we encode Chrome's screencast frames with it (no extra downloads)
const FFMPEG = join(import.meta.dirname, "..", "node_modules", "@remotion", "compositor-darwin-arm64", "ffmpeg");

mkdirSync(OUT, { recursive: true });
const markersFile = join(OUT, "markers.json");
const markers: Record<string, { duration: number; marks: Record<string, number> }> =
  existsSync(markersFile) ? JSON.parse(readFileSync(markersFile, "utf8")) : {};
const log = (...a: any[]) => console.log(new Date().toLocaleTimeString(), ...a);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------------ API helpers
async function api<T = any>(path: string, method = "GET", body?: unknown): Promise<T> {
  const r = await fetch(API + path, { method, headers: { "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!r.ok) throw new Error(`${method} ${path} → ${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}
async function waitFor<T>(label: string, fn: () => Promise<T | null | undefined | false>, timeoutMs = 15 * 60_000, every = 2000): Promise<T> {
  const t0 = Date.now();
  for (;;) {
    try {
      const v = await fn();
      if (v) return v as T;
    } catch { /* transient */ }
    if (Date.now() - t0 > timeoutMs) throw new Error(`timed out waiting for: ${label}`);
    await sleep(every);
  }
}
const pendingGate = (model: string, stage?: string) =>
  api<any[]>(`/api/gates?status=pending&model_id=${model}`).then((gs) => gs.find((g) => !stage || g.stage === stage) || null);
const factoryRun = (model: string) => api<any[]>(`/api/runs?model_id=${model}`).then((rs) => rs.find((r) => r.kind === "factory") || null);
const latestRun = (model: string, kind: string) => api<any[]>(`/api/runs?model_id=${model}`).then((rs) => rs.find((r) => r.kind === kind) || null);
const model = (id: string) => api<any>(`/api/models/${id}`);

// ------------------------------------------------------------------ browser + scenes
let browser: Browser;
const CURSOR = `
(() => {
  const mk = () => {
    if (document.getElementById('__cur')) return;
    const c = document.createElement('div'); c.id = '__cur';
    c.style.cssText = 'position:fixed;left:-50px;top:-50px;width:22px;height:22px;z-index:2147483647;pointer-events:none;transition:transform .08s';
    c.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M3 2l7.5 19 2.6-7.4L21 11z" fill="#0f172a" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
    addEventListener('mousemove', (e) => { c.style.left = e.clientX - 3 + 'px'; c.style.top = e.clientY - 2 + 'px'; }, true);
    addEventListener('mousedown', (e) => {
      const r = document.createElement('div');
      r.style.cssText = 'position:fixed;z-index:2147483646;pointer-events:none;border-radius:50%;border:3px solid #14b8a6;width:16px;height:16px;left:' + (e.clientX - 8) + 'px;top:' + (e.clientY - 8) + 'px;transition:all .45s ease-out;opacity:.9';
      document.documentElement.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = 'scale(3.2)'; r.style.opacity = '0'; });
      setTimeout(() => r.remove(), 600); c.style.transform = 'scale(.85)';
    }, true);
    addEventListener('mouseup', () => { c.style.transform = 'scale(1)'; }, true);
  };
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', mk); else mk();
})();`;

class Scene {
  ctx!: BrowserContext;
  page!: Page;
  cdp: any;
  frames: { file: string; ts: number }[] = [];
  t0 = 0;
  marks: Record<string, number> = {};
  constructor(public name: string) {}
  async open(path: string) {
    rmSync(TMP, { recursive: true, force: true });
    mkdirSync(TMP, { recursive: true });
    this.ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
    await this.ctx.addInitScript(CURSOR);
    this.page = await this.ctx.newPage();
    this.cdp = await this.ctx.newCDPSession(this.page);
    this.cdp.on("Page.screencastFrame", async (f: any) => {
      const file = join(TMP, `f${String(this.frames.length).padStart(6, "0")}.jpg`);
      writeFileSync(file, Buffer.from(f.data, "base64"));
      this.frames.push({ file, ts: f.metadata.timestamp });
      await this.cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }).catch(() => {});
    });
    await this.cdp.send("Page.startScreencast", { format: "jpeg", quality: 90, maxWidth: W, maxHeight: H, everyNthFrame: 1 });
    this.t0 = Date.now();
    await this.page.goto(WEB + path, { waitUntil: "load" }).catch(() => {}); await sleep(1500);
    await this.page.mouse.move(W * 0.62, H * 0.55);
    this.mark("open");
    log(`▶ ${this.name}`);
    return this.page;
  }
  mark(label: string) { this.marks[label] = (Date.now() - this.t0) / 1000; }
  async goto(path: string, label?: string) {
    await this.page.goto(WEB + path, { waitUntil: "load" }).catch(() => {}); await sleep(1500);
    if (label) this.mark(label);
  }
  /** Glide the cursor to an element, then click it. */
  async click(selector: string | ReturnType<Page["locator"]>, label?: string) {
    const loc = typeof selector === "string" ? this.page.locator(selector).first() : selector.first();
    await loc.scrollIntoViewIfNeeded().catch(() => {});
    const b = await loc.boundingBox();
    if (b) await this.page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 28 });
    await sleep(250);
    if (label) this.mark(label);
    await loc.click();
  }
  async hover(selector: string, ms = 800) {
    const b = await this.page.locator(selector).first().boundingBox();
    if (b) await this.page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 30 });
    await sleep(ms);
  }
  async type(selector: string, text: string) {
    await this.click(selector);
    await this.page.keyboard.type(text, { delay: 38 });
  }
  /** Smooth page scroll by `px` over `ms`. */
  async scroll(px: number, ms = 1600, at?: [number, number]) {
    if (at) await this.page.mouse.move(at[0], at[1], { steps: 10 });
    const steps = Math.max(8, Math.round(ms / 40));
    for (let i = 0; i < steps; i++) { await this.page.mouse.wheel(0, px / steps); await sleep(ms / steps); }
  }
  async hold(ms: number) { await sleep(ms); }
  async close() {
    const end = Date.now();
    const dur = (end - this.t0) / 1000;
    await this.cdp.send("Page.stopScreencast").catch(() => {});
    await sleep(300);
    await this.ctx.close();
    // frames arrive only when the page repaints: hold each one until the next (constant 30 fps output)
    const fr = this.frames;
    if (!fr.length) throw new Error(`${this.name}: no frames captured`);
    const lines: string[] = [];
    for (let i = 0; i < fr.length; i++) {
      const from = i === 0 ? this.t0 / 1000 : fr[i].ts;
      const to = i + 1 < fr.length ? fr[i + 1].ts : end / 1000;
      lines.push(`file '${fr[i].file}'`, `duration ${Math.max(0.001, to - from).toFixed(4)}`);
    }
    lines.push(`file '${fr.at(-1)!.file}'`);
    writeFileSync(join(TMP, "list.txt"), lines.join("\n"));
    const dst = join(OUT, `${this.name}.mp4`);
    execFileSync(FFMPEG, ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", join(TMP, "list.txt"),
      "-vf", `scale=${W}:${H},format=yuv420p`, "-r", "30", "-fps_mode", "cfr",
      "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-movflags", "+faststart", dst], { cwd: join(FFMPEG, "..") });
    rmSync(TMP, { recursive: true, force: true });
    markers[this.name] = { duration: Math.round(dur * 10) / 10, marks: this.marks };
    writeFileSync(markersFile, JSON.stringify(markers, null, 2));
    log(`■ ${this.name} (${dur.toFixed(0)}s)`);
  }
}

const failed: string[] = [];
async function scene(name: string, fn: (s: Scene) => Promise<void>) {
  if (only && only !== name) return;
  const s = new Scene(name);
  try { await fn(s); } catch (e: any) { failed.push(name); log(`✗ ${name}: ${e.message?.slice(0, 300)}`); }
  finally { if (s.ctx) await s.close().catch((e) => log("close failed", e)); }
}

/** Safety net: if the on-screen click didn't land, record the same reviewer decision through the API. */
async function ensureDecided(modelId: string, stage: string, decision: string, comment: string, prevId?: number) {
  if (only) return;
  await sleep(1500);
  const g = await pendingGate(modelId, stage).catch(() => null);
  if (g && prevId !== undefined && g.id !== prevId) return;  // a fresh gate after a send-back: already handled
  if (g && !g.context?.blocked) {
    log(`  (api) ${modelId} ${stage} → ${decision}`);
    await api(`/api/gates/${g.id}/decision`, "POST", { decision, comment, decided_by: REVIEWER });
  }
}

/** Record a live agent trace until `until()` resolves (cap keeps clips sane). */
async function traceUntil(s: Scene, runId: string, until: () => Promise<any>, capMs = 12 * 60_000) {
  await s.open(`/agents?run=${runId}`);
  await waitFor(`${s.name} end`, until, capMs);
  s.mark("done");
  await s.hold(2500);
}

const gateBox = 'textarea[placeholder^="Comment"]';
async function reviewerDecides(s: Scene, decision: "Approve" | "Send back to the agent", comment: string) {
  await s.type(gateBox, comment);
  await s.hold(500);
  await s.click(s.page.getByRole("button", { name: decision }), decision === "Approve" ? "approve" : "sendback");
  await s.hold(2500);
}

// ------------------------------------------------------------------ CR-002 runs alongside; its gates are decided too
let cr002Stop = false;
async function cr002Reviewer() {
  const notes: Record<string, string> = {
    gate_document: "Spec reviewed: ranger forest, strategy rehost — agreed.",
    gate_redevelop: "Documentation and plans reviewed.",
    gate_validate: "Rehost accepted: validate the R outputs as-is.",
    gate_deploy: "Validation reviewed. Not deployable (rehosted challenger) — close the lifecycle.",
  };
  while (!cr002Stop) {
    const g = await pendingGate("CR-002").catch(() => null);
    if (g && !g.context?.blocked && notes[g.stage]) {
      await sleep(4000);
      await api(`/api/gates/${g.id}/decision`, "POST", { decision: "approved", comment: notes[g.stage], decided_by: REVIEWER }).catch(() => {});
      log(`  CR-002 ${g.stage} approved`);
    }
    await sleep(3000);
  }
}


/** Tour a completed agent trace: jump to a stage, scroll its reasoning, expand key tool calls. */
async function traceTour(s: Scene, runId: string, stage: string | null, filter: string | null, tools: string[]) {
  const p = await s.open(`/agents?run=${runId}`);
  await s.hold(1800);
  await s.click(p.getByRole("button", { name: "follow" }));          // stop auto-follow so we can read
  const box = p.locator("div.flex-1.overflow-y-auto").first();          // the trace log (not the run list)
  if (filter) {
    await s.type('input[placeholder="filter log…"]', filter);
    s.mark("filtered");
    await s.hold(1500);
  }
  if (stage) {
    await box.evaluate((el, st) => {
      const h = [...el.querySelectorAll("div.sticky")].find((d) => d.textContent?.trim().endsWith(st as string)) as HTMLElement | undefined;
      if (h) el.scrollTop = h.offsetTop - 4;
    }, stage);
    s.mark("stage");
    await s.hold(1800);
  }
  const bb = await box.boundingBox();
  const at: [number, number] = bb ? [bb.x + bb.width * 0.6, bb.y + bb.height * 0.5] : [960, 600];
  await s.scroll(420, 3200, at);
  for (const t of tools) {
    let row = box.locator("button").filter({ hasText: t }).filter({ hasText: "RESULT" }).first();
    if (!(await row.count())) row = box.locator("button").filter({ hasText: t }).first();
    if (!(await row.count())) { log(`  (no row for ${t})`); continue; }
    await s.click(row, `tool_${t}`);
    await s.hold(3200);
    await s.scroll(260, 1600, at);
  }
  s.mark("done");
  await s.hold(2000);
}

async function traceTours() {
  const r1 = (await factoryRun("CR-001")).id;
  const rv = (await latestRun("CR-001", "revalidation"))?.id;
  const tours: [string, string, string | null, string | null, string[]][] = [
    ["s02_intake", r1, "Intake", null, ["read_script", "probe_legacy", "draft_spec"]],
    ["s07b_doc_redraft", r1, null, "data-quality", ["draft_monitoring_plan"]],
    ["s06_document", r1, "Documentation & planning", null, ["review_code", "draft_monitoring_plan"]],
    ["s09_redevelop", r1, "Redevelopment", null, ["run_export", "draft_translation", "check_parity", "certify"]],
    ["s13_validate", r1, "Validation", null, ["slice_search", "challenger", "fuzz"]],
  ];
  if (rv) tours.push(["s17_diagnose", rv, "Alert diagnosis", null, ["data_quality", "score_shift", "diagnose"]]);
  for (const [name, run, stage, filter, tools] of tours) {
    if (only && only !== name) continue;
    const sc = new Scene(name);
    try { await traceTour(sc, run, stage, filter, tools); } catch (e: any) { failed.push(name); log(`✗ ${name}: ${e.message?.slice(0, 200)}`); }
    finally { if (sc.ctx) await sc.close().catch(() => {}); }
  }
}


/**
 * v3 film (3-minute cut): all five models start together; CR-003 / FR-001 / PR-001 stop at plan approval;
 * CR-001 is translated → parity → validated → deployed → drift → re-validation; CR-002 is rehosted.
 */
const btnIn = (p: Page, id: string, btn: string) =>
  p.locator("div").filter({ hasText: id }).filter({ has: p.getByRole("button", { name: btn, exact: true }) }).last().getByRole("button", { name: btn, exact: true });
async function approveApi(model: string, stage: string, comment: string) {
  const g = await waitFor(`${model} ${stage}`, () => pendingGate(model, stage), 20 * 60_000);
  if (g.context?.blocked) throw new Error(`${model} ${stage} blocked: ${JSON.stringify(g.context.blocked)}`);
  await api(`/api/gates/${g.id}/decision`, "POST", { decision: "approved", comment, decided_by: REVIEWER });
  log(`  ${model} ${stage} approved`);
}
const ALL = ["CR-001", "CR-002", "CR-003", "FR-001", "PR-001"];

async function v3() {
  log("resetting demo data and re-onboarding the 5-model estate");
  await api("/api/demo/reset", "POST", { scope: "all", seed: true });
  await api("/api/settings/auto_promote", "POST", { value: false }).catch(() => {});
  await sleep(3000);

  // 1 · floor: start the whole estate, watch five agents work at once, approve one gate from its card
  await scene("v_floor_start", async (s) => {
    const p = await s.open("/");
    await s.hold(3500);
    await s.click(p.getByRole("button", { name: /Start .*idle model/ }), "start_all");
    await waitFor("all specs drafted", async () => (await Promise.all(ALL.map((m) => pendingGate(m, "gate_document")))).every(Boolean), 8 * 60_000);
    s.mark("gates");
    await s.hold(2500);
    await s.hover("text=Agent: PROMOTE", 2200);
    await s.click(btnIn(p, "CR-003", "Approve"), "approve_card");
    await s.hold(4000);
  });
  await ensureDecided("CR-003", "gate_document", "approved", "Approved from the floor.");

  // 2 · approvals queue: review one gate properly, then approve the rest in bulk
  await scene("v_approvals", async (s) => {
    const p = await s.open("/approvals");
    await s.hold(3000);
    const c = p.locator("div").filter({ hasText: "CR-001" }).filter({ has: p.locator(gateBox) }).filter({ has: p.getByRole("button", { name: "Approve", exact: true }) }).last();
    await s.hover("text=Agent recommends", 2200); s.mark("read");
    await s.click(c.locator(gateBox), "comment");
    await p.keyboard.type("Spec checked against the script: GLM scorecard, translate, cut-off 0.35 and inputs correct.", { delay: 30 });
    await s.hold(500);
    await s.click(c.getByRole("button", { name: "Approve", exact: true }), "approve_one");
    await s.hold(2500);
    await s.click(p.getByRole("button", { name: /^Select all/ }), "select_all");
    await s.type('input[placeholder="Comment for all selected…"]', "Specs reviewed; agent recommendations accepted.");
    await s.click(p.getByRole("button", { name: /Approve selected/ }), "approve_bulk");
    await s.hold(3500);
  });
  for (const m of ALL) await ensureDecided(m, "gate_document", "approved", "Spec reviewed and approved.");

  // 3 · the floor while documentation runs for every model in parallel
  await scene("v_floor_docs", async (s) => {
    await s.open("/");
    await s.hold(9000);
  });
  await waitFor("all plans drafted", async () => (await Promise.all(ALL.map((m) => pendingGate(m, "gate_redevelop")))).every(Boolean), 12 * 60_000);
  await scene("v_floor_plans", async (s) => { await s.open("/"); await s.hold(6000); });

  // CR-001 and CR-002 continue; the other three wait at plan approval (shown on the floor)
  await approveApi("CR-001", "gate_redevelop", "Documentation, validation plan and monitoring plan approved.");
  await approveApi("CR-002", "gate_redevelop", "Documentation and plans approved.");
  await approveApi("CR-001", "gate_validate", "Parity certificate reviewed: every row, coefficient and decision within tolerance.");
  await approveApi("CR-002", "gate_validate", "Rehost accepted: validate the R outputs as-is.");
  await approveApi("CR-002", "gate_deploy", "Validated; not deployable (rehosted challenger). Lifecycle closed.");
  await approveApi("CR-001", "gate_deploy", "Red findings accepted for a monitored deployment; remediation tracked.");
  await waitFor("deployed", async () => (await model("CR-001")).model.meta?.deployed, 6 * 60_000);
  await waitFor("dashboard warm", async () => {
    const w = (await api<any>("/api/traffic/CR-001?n=1")).windows?.at(-1);
    return w && w.score_psi != null && w.ae_ratio != null;
  }, 8 * 60_000);

  // 4 · live monitoring: agent-designed KPIs, drift ramp → alert → automatic re-validation
  await scene("v_monitor", async (s) => {
    const p = await s.open("/monitoring?model=CR-001");
    await s.hold(5000);
    await s.scroll(1100, 3500, [1000, 600]); s.mark("rows");
    await s.hold(2000);
    await p.locator("section:has-text('Drift scenario')").first().scrollIntoViewIfNeeded();
    await s.hold(800);
    await s.click(p.locator("section:has-text('Drift scenario') button").first(), "pick_scenario");
    await p.locator('input[type="range"]').nth(0).fill("1");
    await p.locator('input[type="range"]').nth(1).fill("20");
    await s.click(p.getByRole("button", { name: "Ramp in" }), "ramp");
    await s.hold(1200);
    await p.mouse.wheel(0, -20000);
    s.mark("watch");
    await waitFor("red alert", async () => Object.values((await api<any>("/api/traffic/CR-001?n=1")).active_alerts || {}).includes("red"), 6 * 60_000);
    s.mark("red");
    await s.hold(5000);
    await waitFor("revalidation", () => latestRun("CR-001", "revalidation"), 3 * 60_000);
    await p.locator("text=Alerts & logs").first().scrollIntoViewIfNeeded();
    s.mark("alerts");
    await s.hold(6000);
  });
  await approveApi("CR-001", "gate_accept", "Drift diagnosed and re-validated on live traffic. Accepted; recalibration raised.");

  // 5 · governance
  await scene("v_governance", async (s) => {
    const p = await s.open("/governance");
    await s.hold(3000);
    await s.click(p.getByRole("button", { name: /Verify chain/ }), "verify1");
    await s.hold(3500);
    await s.click(p.getByRole("button", { name: /Tamper/ }), "tamper");
    await s.hold(2000);
    await s.click(p.getByRole("button", { name: /Verify chain/ }), "verify2");
    await s.hold(5000);
  });

  // 6 · product tours over the finished state
  await scene("v_floor_end", async (s) => { await s.open("/"); await s.hold(7000); });
  await scene("v_workbench", async (s) => {
    const p = await s.open("/models/CR-001");
    await s.hold(3000);
    const tabs: [string, number][] = [["Spec", 900], ["Contract", 600], ["Documentation", 900], ["Validation plan", 700], ["Monitoring plan", 900], ["Findings", 400], ["Runs & agent log", 0]];
    for (const [t, px] of tabs) {
      await s.click(p.getByRole("tab", { name: t }).first(), "tab_" + t.split(" ")[0].toLowerCase());
      await s.hold(2200);
      if (px) { await s.scroll(px, 2600, [960, 640]); await s.hold(1000); }
      await p.mouse.wheel(0, -6000); await s.hold(300);
    }
    await s.hold(1500);
  });
  await scene("v_parity", async (s) => {
    await s.open("/models/CR-001?tab=parity");
    await s.hold(4500);
    await s.scroll(520, 2800, [960, 600]); s.mark("charts");
    await s.hold(3000);
    await s.scroll(700, 2800, [960, 600]); s.mark("coef");
    await s.hold(2500);
  });
  await scene("v_rehost", async (s) => {
    await s.open("/models/CR-002?tab=parity");
    await s.hold(5000);
    await s.goto("/models/CR-002", "overview");
    await s.hold(3500);
  });
  await scene("v_graph", async (s) => {
    const p = await s.open("/models");
    await s.hold(2500);
    await s.click('.react-flow__node[data-id="CR-001"]', "select_cr001");
    await s.hold(4500);
    await s.click('.react-flow__node[data-id="CR-003"]', "select_cr003");
    await s.hold(2500);
    void p;
  });

  // 7 · agent trace tours (thinking, tool calls, retries)
  const r1 = (await factoryRun("CR-001")).id;
  const rv = (await latestRun("CR-001", "revalidation"))?.id;
  const tours: [string, string, string | null, string[]][] = [
    ["v_trace_intake", r1, "Intake", ["read_script", "probe_legacy", "draft_spec"]],
    ["v_trace_document", r1, "Documentation & planning", ["review_code", "draft_monitoring_plan"]],
    ["v_trace_redevelop", r1, "Redevelopment", ["inspect_export", "draft_translation", "check_parity", "certify"]],
    ["v_trace_validate", r1, "Validation", ["slice_search", "challenger", "fuzz"]],
  ];
  if (rv) tours.push(["v_trace_diagnose", rv, "Alert diagnosis", ["data_quality", "score_shift", "diagnose"]]);
  for (const [name, run, stage, tools] of tours) {
    const sc = new Scene(name);
    try { await traceTour(sc, run, stage, null, tools); } catch (e: any) { failed.push(name); log(`✗ ${name}: ${e.message?.slice(0, 200)}`); }
    finally { if (sc.ctx) await sc.close().catch(() => {}); }
  }

  // 8 · measured impact for the film (this run only)
  const runs = await api<any[]>("/api/runs?limit=100");
  const impact: any = { models_in_parallel: ALL.length, runs: {} };
  for (const r of runs) {
    const calls = await api<any[]>(`/api/agents/llm-calls?run_id=${r.id}`);
    const steps = await api<any[]>(`/api/agents/steps?run_id=${r.id}&after=0`);
    const certify = steps.find((x) => x.kind === "tool_result" && x.title.startsWith("certify"));
    impact.runs[r.id] = { model: r.model_id, kind: r.kind, status: r.status, stage: r.stage, started: r.started_at, ended: r.ended_at,
      llm_calls: calls.length, llm_cost: calls.reduce((a, c) => a + (c.cost || 0), 0), steps: steps.length,
      tool_calls: steps.filter((x) => x.kind === "tool_call").length, certified_at: certify?.ts };
  }
  writeFileSync(join(OUT, "..", "impact.json"), JSON.stringify(impact, null, 2));
  log("impact →", JSON.stringify(Object.values(impact.runs).map((r: any) => [r.model, r.kind, r.llm_calls, r.llm_cost.toFixed(4), r.steps])));
}

// ------------------------------------------------------------------ the film
const only = process.argv.includes("--only") ? process.argv[process.argv.indexOf("--only") + 1] : null;

async function main() {
  browser = await chromium.launch({ channel: "chrome", headless: true });
  if (process.argv.includes("--blocked")) {   // the guardrail moment: failed export → HOLD → blocked gate
    const run = (await factoryRun("CR-001")).id;
    await scene("x_blocked_trace", async (s) => {
      const p = await s.open(`/agents?run=${run}`);
      await s.hold(1500);
      await s.click(p.getByRole("button", { name: "follow" }));
      await s.click(p.getByRole("button", { name: /^Errors/ }), "errors");
      await s.hold(3500);
      await s.click(p.getByRole("button", { name: /^All$/ }));
      await s.type('input[placeholder="filter log…"]', "HOLD");
      s.mark("hold");
      await s.hold(3500);
    });
    await scene("x_blocked_gate", async (s) => {
      await s.open("/models/CR-001");
      await s.hold(2500);
      await s.hover('button:has-text("Approve")', 2500);
      s.mark("blocked");
      await s.hold(3000);
    });
    await browser.close();
    return;
  }
  if (process.argv.includes("--v3")) {
    cr002Stop = true;
    await v3();
    await browser.close();
    log("v3 done", failed.length ? `· scenes with problems: ${failed.join(", ")}` : "· all scenes clean");
    return;
  }
  if (process.argv.includes("--traces")) {   // re-record agent traces from the finished runs
    await traceTours();
    await browser.close();
    log("traces done", failed.length ? `· failed: ${failed.join(", ")}` : "");
    return;
  }

  if (!only) {
    log("resetting demo data and re-onboarding the 5-model estate");
    await api("/api/demo/reset", "POST", { scope: "all", seed: true });
    await api("/api/settings/auto_promote", "POST", { value: false }).catch(() => {});
    await sleep(2000);
    await sleep(3000);
  }

  // 01 — factory floor, reviewer starts the two models
  await scene("s01_floor", async (s) => {
    const p = await s.open("/");
    await s.hold(3500);
    const starts = p.locator('button:has-text("Start")').filter({ hasNotText: "idle" });
    await s.click(starts.nth(0), "start_cr001");
    await s.hold(1200);
    await s.click(p.locator('button:has-text("Start")').filter({ hasNotText: "idle" }).nth(0), "start_cr002");
    await s.hold(7000);
  });
  if (!only) {
    // make sure both are running even if the card order differed
    for (const m of ["CR-001", "CR-002"]) if (!(await factoryRun(m))) await api(`/api/models/${m}/start`, "POST").catch(() => {});
    cr002Reviewer();
  }
  const r1 = async () => (await waitFor("CR-001 run", () => factoryRun("CR-001"))).id as string;

  // 02 — intake agent, live trace (reads script, probes R in the sandbox, drafts the spec)
  await scene("s02_intake", async (s) => traceUntil(s, await r1(), () => pendingGate("CR-001", "gate_document")));

  // 03 — gate 1: reviewer reads the drafted spec (task, strategy, tier, inputs) and approves
  const G1 = "Spec reviewed against the script: GLM scorecard, translate strategy, cut-off and inputs correct. Approved.";
  await scene("s03_gate1_review", async (s) => {
    const p = await s.open("/models/CR-001");
    await s.hold(2500);
    await s.click(p.getByRole("button", { name: "Review the spec →" }), "open_spec");
    await s.hold(2500);
    await s.scroll(700, 2600, [960, 650]);
    await s.hold(1500);
    await s.click(p.getByRole("tab", { name: "Overview" }), "back_overview");
    await s.hold(1200);
    await reviewerDecides(s, "Approve", G1);
  });
  await ensureDecided("CR-001", "gate_document", "approved", G1);

  // 04 — documentation agent (policies, independent code review, lineage, documentation, both plans)
  await scene("s06_document", async (s) => traceUntil(s, await r1(), () => pendingGate("CR-001", "gate_redevelop")));

  // 05 — gate 2: reviewer reads the documentation and the agent's monitoring plan, and sends it back
  const g2 = only ? null : await pendingGate("CR-001", "gate_redevelop");
  const SENDBACK = "Monitoring plan: add data-quality alerts for missing inputs and out-of-range values. This feed has had null issues before.";
  await scene("s07_gate2_sendback", async (s) => {
    const p = await s.open("/models/CR-001?tab=docs");
    await s.hold(2500);
    await s.scroll(800, 2600, [800, 600]);
    await s.click(p.getByRole("tab", { name: "Monitoring plan" }), "monitoring_plan");
    await s.hold(3500);
    await s.scroll(600, 2400, [960, 650]);
    await s.hold(1500);
    await s.click(p.getByRole("tab", { name: "Overview" }), "back_overview");
    await s.hold(1200);
    await reviewerDecides(s, "Send back to the agent", SENDBACK);
  });
  if (g2) {
    const still = await pendingGate("CR-001", "gate_redevelop");
    if (still && still.id === g2.id) await api(`/api/gates/${g2.id}/decision`, "POST", { decision: "changes_requested", comment: SENDBACK, decided_by: REVIEWER });
  }

  // 06 — the documentation agent re-plans with the reviewer's comment as its top priority
  await scene("s07b_doc_redraft", async (s) => traceUntil(s, await r1(),
    async () => { const g = await pendingGate("CR-001", "gate_redevelop"); return g && g.id !== g2?.id ? g : null; }));

  // 07 — gate 2 again: the revised monitoring plan, approved
  const G2 = "Data-quality alerts added as requested. Documentation and plans approved.";
  await scene("s07c_gate2_approve", async (s) => {
    const p = await s.open("/models/CR-001?tab=monitoring");
    await s.hold(3000);
    await s.scroll(600, 2600, [960, 650]);
    await s.hold(2000);
    await s.click(p.getByRole("tab", { name: "Overview" }));
    await s.hold(1200);
    await reviewerDecides(s, "Approve", G2);
  });
  await ensureDecided("CR-001", "gate_redevelop", "approved", G2);

  // 08 — dependency graph: blast radius, then a reviewer declares a dependency by hand
  await scene("s08_graph", async (s) => {
    const p = await s.open("/models");
    await s.hold(2500);
    await s.click('.react-flow__node[data-id="CR-001"]', "select_cr001");
    await s.hold(3500);
    await s.click(p.getByRole("button", { name: "Edit dependencies" }), "edit");
    await s.hold(1500);
    await p.locator("form select").nth(0).selectOption("CR-002"); s.mark("pick_up");
    await s.hold(900);
    await p.locator("form select").nth(1).selectOption("CR-003");
    await s.hold(900);
    await s.type('input[placeholder="Why does this dependency exist?"]', "Challenger scores are used as an override signal in limit setting");
    await s.click(p.getByRole("button", { name: "Add dependency" }), "added");
    await s.hold(3500);
    await s.click(p.getByRole("button", { name: "Done editing" }));
    await s.hold(1500);
    await s.click('.react-flow__node[data-id="CR-002"]', "select_cr002");
    await s.hold(3000);
  });

  // 09 — redevelopment agent: R export epilogue, sandbox run, Python translation, parity, certificate
  await scene("s09_redevelop", async (s) => traceUntil(s, await r1(), () => pendingGate("CR-001", "gate_validate")));

  if (!only) {
    const g3 = await pendingGate("CR-001", "gate_validate");
    if (g3?.context?.blocked) throw new Error("CR-001 redevelopment is blocked: " + JSON.stringify(g3.context.blocked));
  }

  // 10 — the parity certificate
  await scene("s10_parity", async (s) => {
    await s.open("/models/CR-001?tab=parity");
    await s.hold(4500);
    await s.scroll(520, 2600, [960, 600]);
    await s.hold(2500);
    await s.scroll(700, 2600, [960, 600]);
    await s.hold(2500);
    await s.scroll(800, 2600, [960, 600]);
    await s.hold(2000);
  });

  // 11 — gate 3 from the approvals queue
  await scene("s11_gate3_approvals", async (s) => {
    const p = await s.open("/approvals");
    await s.hold(3500);
    const card = p.locator("div").filter({ hasText: "CR-001" }).filter({ has: p.locator(gateBox) }).filter({ has: p.getByRole("button", { name: "Approve", exact: true }) }).last();
    await s.click(card.locator(gateBox));
    await p.keyboard.type("Parity certificate reviewed: every row, coefficient and decision within tolerance.", { delay: 34 });
    await s.click(card.getByRole("button", { name: "Approve", exact: true }), "approve");
    await s.hold(3000);
  });
  await ensureDecided("CR-001", "gate_validate", "approved", "Parity certificate reviewed: every row, coefficient and decision within tolerance.");

  // 12 — CR-002: the rehost path
  await scene("s12_rehost", async (s) => {
    await waitFor("CR-002 certified", async () => (await model("CR-002")).model.meta?.parity_verdict, 25 * 60_000);
    const run = await factoryRun("CR-002");
    const p = await s.open(`/agents?run=${run.id}`);
    await s.hold(1500);
    const search = p.locator('input[placeholder="filter log…"]').first();
    if (await search.count()) { await s.click(search); await p.keyboard.type("rehost", { delay: 60 }); s.mark("search"); }
    await s.hold(4500);
    await s.goto("/models/CR-002?tab=parity", "parity");
    await s.hold(5000);
    await s.goto("/models/CR-002", "overview");
    await s.hold(4000);
  });

  // 13 — validator agent on CR-001
  await scene("s13_validate", async (s) => traceUntil(s, await r1(), () => pendingGate("CR-001", "gate_deploy")));

  // 14 — the report: every number is evidence
  await scene("s14_report", async (s) => {
    const reps = await api<any[]>("/api/reports").then((rs) => rs.filter((r) => r.model_id === "CR-001"));
    const rep = reps.at(-1);
    const p = await s.open(`/reports/${rep.id}`);
    await s.hold(3500);
    await s.scroll(600, 2400, [960, 600]);
    await s.hold(1200);
    await s.click(p.locator("button.pill").nth(2), "pill");
    await s.hold(3500);
    const rb = p.getByRole("button", { name: /Reproduce/ });
    if (await rb.count()) { await s.click(rb, "reproduce"); await s.hold(4500); }
    await p.keyboard.press("Escape");
    await s.hold(1500);
  });

  // 15 — gate 4: approve validation → deploy; monitor agent stands up the endpoint
  await scene("s15_gate4_deploy", async (s) => {
    await s.open("/models/CR-001");
    await s.hold(3000);
    await reviewerDecides(s, "Approve", "Validation accepted. Deploy to production monitoring.");
    await ensureDecided("CR-001", "gate_deploy", "approved", "Validation accepted. Deploy to production monitoring.");
    await waitFor("deployed", async () => (await model("CR-001")).model.meta?.deployed, 6 * 60_000);
    s.mark("deployed");
    await s.goto(`/agents?run=${await r1()}`, "monitor_trace");
    await s.hold(9000);
  });

  // let the dashboard fill (drift needs 200 scored requests, outcomes need maturity)
  if (!only || only === "s16_monitor") {
    await waitFor("dashboard warm", async () => {
      const w = (await api<any>("/api/traffic/CR-001?n=1")).windows?.at(-1);
      return w && w.score_psi != null && w.ae_ratio != null;
    }, 6 * 60_000);
  }

  // 16 — live monitoring + drift ramp until the red alert starts a re-validation
  await scene("s16_monitor", async (s) => {
    const p = await s.open("/monitoring?model=CR-001");
    await s.hold(6000);
    await s.scroll(1100, 3500, [1000, 600]); s.mark("rows");
    await s.hold(2500);
    await s.scroll(1400, 3500, [1000, 600]);
    await s.hold(2500);
    await p.locator('button:has-text("Drift scenario"), section:has-text("Drift scenario")').first().scrollIntoViewIfNeeded();
    await s.hold(800);
    const scen = p.locator("section:has-text('Drift scenario') button").first();
    await s.click(scen, "pick_scenario");
    await p.locator('input[type="range"]').nth(0).fill("1");
    await p.locator('input[type="range"]').nth(1).fill("20");
    await s.hold(800);
    await s.click(p.getByRole("button", { name: "Ramp in" }), "ramp");
    await s.hold(1500);
    await p.mouse.wheel(0, -20000);
    s.mark("watch");
    await waitFor("red alert", async () => {
      const st = await api<any>("/api/traffic/CR-001?n=1");
      return Object.values(st.active_alerts || {}).includes("red");
    }, 6 * 60_000);
    s.mark("red");
    await s.hold(6000);
    await waitFor("revalidation", () => latestRun("CR-001", "revalidation"), 3 * 60_000);
    await p.locator("text=Alerts & logs").first().scrollIntoViewIfNeeded();
    s.mark("alerts");
    await s.hold(7000);
  });

  // 17 — monitor agent diagnoses, validator re-runs the plan on live traffic
  await scene("s17_diagnose", async (s) => {
    const rv = await waitFor("reval run", () => latestRun("CR-001", "revalidation"));
    await traceUntil(s, rv.id, () => pendingGate("CR-001", "gate_accept"));
  });

  // 18 — the reviewer accepts the re-validation
  await scene("s18_accept", async (s) => {
    const g = await waitFor("accept gate", () => pendingGate("CR-001", "gate_accept"));
    const p = await s.open("/approvals");
    await s.hold(3500);
    const card = p.locator("div").filter({ hasText: "Accept re-validation" }).filter({ has: p.locator(gateBox) }).filter({ has: p.getByRole("button", { name: "Approve", exact: true }) }).last();
    await s.click(card.locator(gateBox));
    await p.keyboard.type("Drift diagnosed and re-validated on live traffic. Accepted; recalibration ticket raised.", { delay: 34 });
    await s.click(card.getByRole("button", { name: "Approve", exact: true }), "approve");
    await s.hold(3000);
    void g;
  });
  await ensureDecided("CR-001", "gate_accept", "approved", "Drift diagnosed and re-validated on live traffic. Accepted; recalibration ticket raised.");

  // 19 — governance: verify, tamper, verify
  await scene("s19_governance", async (s) => {
    const p = await s.open("/governance");
    await s.hold(3000);
    await s.click(p.getByRole("button", { name: /Verify chain/ }), "verify1");
    await s.hold(3500);
    await s.click(p.getByRole("button", { name: /Tamper/ }), "tamper");
    await s.hold(2000);
    await s.click(p.getByRole("button", { name: /Verify chain/ }), "verify2");
    await s.hold(5000);
  });

  // 20 — the floor at the end: CR-001 monitored, CR-002 closed as rehosted
  await scene("s20_floor_end", async (s) => {
    await s.open("/");
    await s.hold(7000);
  });

  cr002Stop = true;
  await browser.close();
  log("done →", OUT, failed.length ? `· scenes with UI fallbacks: ${failed.join(", ")}` : "· all scenes clean");
}

main().catch(async (e) => { console.error(e); cr002Stop = true; await browser?.close(); process.exit(1); });
