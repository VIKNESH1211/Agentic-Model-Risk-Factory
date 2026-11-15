/**
 * Natural narration with OpenAI text-to-speech (gpt-4o-mini-tts): one WAV per shot → public/vo, durations → vo/durations.json.
 * Uses the OpenAI key from the project's .env (OPENAI_API_KEY or LLM_API_KEY). Only the narration lines are sent.
 *   VO_VOICE=ash npx tsx vo/make-vo-openai.ts            (voices: alloy ash ballad coral echo fable nova onyx sage shimmer verse)
 *   npx tsx vo/make-vo-openai.ts --only intake           (regenerate one line)
 */
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { SHOTS } from "./script";

const root = join(import.meta.dirname, "..");
const envFile = join(root, "..", "..", ".env");
const env = Object.fromEntries(readFileSync(envFile, "utf8").split("\n").filter((l) => /^[A-Z_]+=/.test(l)).map((l) => [l.split("=")[0], l.slice(l.indexOf("=") + 1).trim()]));
const KEY = process.env.OPENAI_API_KEY || env.OPENAI_API_KEY || env.LLM_API_KEY;
if (!KEY?.startsWith("sk-")) throw new Error("no OpenAI key found in .env");

const MODEL = process.env.VO_MODEL || "gpt-4o-mini-tts";
const VOICE = process.env.VO_VOICE || "ash";
const INSTRUCTIONS = process.env.VO_STYLE ||
  "You are the narrator of a product walkthrough for senior model-risk and banking professionals. " +
  "Speak in a calm, confident, natural voice: clear and measured, warm but not salesy, like an experienced practitioner explaining their work. " +
  "Speak at a relaxed, natural conversational pace, never rushed, with genuine pauses at commas and full stops, like a person talking a colleague through their work. Sound warm and human.";

// pronunciation help for identifiers
const say = (t: string) => t
  .replace(/CR-00(\d)/g, "C-R zero zero $1")
  .replace(/SR 11-7/g, "S-R eleven-seven")
  .replace(/SS1\/23/g, "S-S one, twenty-three")
  .replace(/\bPSI\b/g, "P-S-I")
  .replace(/\bKPIs\b/g, "K-P-Is")
  .replace(/\bR\b(?= script| model| run|,| to)/g, "R");

const dir = join(root, "public", "vo");
const tools = join(root, "node_modules", "@remotion", "compositor-darwin-arm64");
mkdirSync(dir, { recursive: true });
const durFile = join(import.meta.dirname, "durations.json");
const prev = existsSync(durFile) ? JSON.parse(readFileSync(durFile, "utf8")) : { shots: {} };
const only = process.argv.includes("--only") ? process.argv[process.argv.indexOf("--only") + 1] : null;
const out: Record<string, number> = { ...prev.shots };

async function tts(text: string, file: string) {
  for (let attempt = 1; ; attempt++) {
    const r = await fetch("https://api.openai.com/v1/audio/speech", {
      method: "POST",
      headers: { Authorization: `Bearer ${KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: MODEL, voice: VOICE, input: text, instructions: INSTRUCTIONS, response_format: "wav" }),
    });
    if (r.ok) { writeFileSync(file, Buffer.from(await r.arrayBuffer())); return; }
    const msg = (await r.text()).slice(0, 300);
    if (attempt >= 3 || r.status < 500 && r.status !== 429) throw new Error(`TTS ${r.status}: ${msg}`);
    await new Promise((res) => setTimeout(res, 2000 * attempt));
  }
}

const todo = SHOTS.filter((s) => !only || s.id === only);
let i = 0;
async function worker() {
  while (i < todo.length) {
    const s = todo[i++];
    const f = join(dir, `${s.id}.wav`);
    await tts(say(s.vo), f);
    const d = execFileSync(join(tools, "ffprobe"), ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f], { cwd: tools }).toString().trim();
    out[s.id] = Math.round(parseFloat(d) * 100) / 100;
    process.stdout.write(".");
  }
}
await Promise.all([worker(), worker(), worker(), worker()]);
writeFileSync(durFile, JSON.stringify({ voice: `openai:${MODEL}:${VOICE}`, rate: "natural", shots: out }, null, 2));
const total = Object.values(out).reduce((a, b) => a + b, 0);
console.log(`\n${todo.length} line(s) · narration ${total.toFixed(1)}s · ${MODEL} / ${VOICE}`);
