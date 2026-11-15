/** Narration: one WAV per shot with macOS `say`, then measure durations → vo/durations.json. */
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { SHOTS, WORDS } from "./script";

const VOICE = process.env.VO_VOICE || "Samantha";
const RATE = process.env.VO_RATE || "182";
const dir = join(import.meta.dirname, "..", "public", "vo");
const tools = join(import.meta.dirname, "..", "node_modules", "@remotion", "compositor-darwin-arm64");
mkdirSync(dir, { recursive: true });
const out: Record<string, number> = {};
for (const s of SHOTS) {
  const f = join(dir, `${s.id}.wav`);
  // light SSML-free pacing: commas already give pauses; "SR 11-7" reads better spelled out
  const text = s.vo.replace(/SR 11-7/g, "S R eleven seven").replace(/SS1\/23/g, "S S one twenty-three").replace(/CR-00(\d)/g, "C R zero zero $1");
  execFileSync("say", ["-v", VOICE, "-r", RATE, "--data-format=LEI16@44100", "-o", f, text]);
  const d = execFileSync(join(tools, "ffprobe"), ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f], { cwd: tools }).toString().trim();
  out[s.id] = Math.round(parseFloat(d) * 100) / 100;
}
writeFileSync(join(import.meta.dirname, "durations.json"), JSON.stringify({ voice: VOICE, rate: RATE, shots: out }, null, 2));
const total = Object.values(out).reduce((a, b) => a + b, 0);
console.log(`${SHOTS.length} shots · ${WORDS} words · narration ${total.toFixed(1)}s with ${VOICE} @ ${RATE} wpm`);
