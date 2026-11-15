/** Timed narration script for a human voice-over: drop recordings into public/vo/<id>.wav (same ids). */
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { buildTimeline } from "../src/timeline";
const tc = (f: number) => { const s = f / 30; return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`; };
const { shots, total } = buildTimeline();
const lines = ["# Model Risk Factory: narration script", "",
  `Total ${tc(total)}. Record each line as public/vo/<id>.wav (44.1 kHz), then \`npm run render:voice\`; shot lengths follow the audio.`, "",
  "| Time | Id | On screen | Line |", "|---|---|---|---|",
  ...shots.map((s) => `| ${tc(s.start)} | \`${s.id}\` | ${s.chapter ? `**${s.chapter}** · ` : ""}${s.clip || s.graphic || ""} | ${s.vo} |`)];
writeFileSync(join(import.meta.dirname, "..", "out", "vo-script.md"), lines.join("\n") + "\n");
console.log("wrote out/vo-script.md", tc(total));
