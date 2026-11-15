/**
 * README screenshots of the running product → docs/screenshots/*.png (raw, 2× scale; resized afterwards).
 *   npx tsx capture/screens.ts        (needs `make demo` state with a finished CR-001 lifecycle)
 */
import { chromium, type Page } from "playwright";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const WEB = "http://localhost:3210";
const API = "http://localhost:8100";
const OUT = join(import.meta.dirname, "..", "..", "..", "docs", "screenshots");
mkdirSync(OUT, { recursive: true });
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const api = async (p: string) => (await fetch(API + p)).json();

const factoryRun = (await api("/api/runs?model_id=CR-001")).find((r: any) => r.kind === "factory").id;

const shots: [string, string, ((p: Page) => Promise<void>)?][] = [
  ["01-factory-floor", "/"],
  ["02-approvals", "/approvals"],
  ["03-agent-console", `/agents?run=${factoryRun}`, async (p) => {
    await p.getByRole("button", { name: "follow" }).click().catch(() => {});
    const box = p.locator("div.flex-1.overflow-y-auto").first();
    const row = box.locator("button").filter({ hasText: "probe_legacy" }).filter({ hasText: "RESULT" }).first();
    await row.scrollIntoViewIfNeeded().catch(() => {});
    await row.click().catch(() => {});
    await sleep(800);
    await box.evaluate((el) => { el.scrollTop = Math.max(0, el.scrollTop - 260); });
  }],
  ["04-model-workbench", "/models/CR-001"],
  ["05-monitoring-plan-editor", "/models/CR-001?tab=monitoring"],
  ["06-parity-certificate", "/models/CR-001?tab=parity"],
  ["07-blast-radius", "/models", async (p) => { await p.click('.react-flow__node[data-id="CR-001"]').catch(() => {}); }],
  ["08-live-monitoring", "/monitoring?model=CR-001"],
  ["09-validation-report", "/reports/rep_run_6e5c7f"],
  ["10-governance", "/governance"],
];

const browser = await chromium.launch({ channel: "chrome", headless: true });
for (const [name, path, act] of shots) {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 2 });
  const p = await ctx.newPage();
  await p.goto(WEB + path, { waitUntil: "load" }).catch(() => {});
  await sleep(3500);
  if (act) { await act(p); await sleep(1500); }
  await p.mouse.move(1599, 999);
  await p.screenshot({ path: join(OUT, `${name}.png`) });
  console.log("✓", name);
  await ctx.close();
}
await browser.close();
