/**
 * Pre-cut each shot's footage window into a short constant-30fps clip with its speed baked in
 * (public/cuts/<shot>.mp4), using input-timestamp scaling (Remotion's bundled ffmpeg has no setpts/fps filters). Remotion then plays small files at 1× instead of seeking through long
 * variable-frame-rate recordings at fractional rates, which can hang the renderer.
 *   npx tsx vo/make-cuts.ts        (rerun after changing script windows or narration)
 */
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { buildTimeline, FPS } from "../src/timeline";

const root = join(import.meta.dirname, "..");
const tools = join(root, "node_modules", "@remotion", "compositor-darwin-arm64");
const out = join(root, "public", "cuts");
mkdirSync(out, { recursive: true });
const manifest: Record<string, string> = {};
const { shots } = buildTimeline(true);
for (const s of shots) {
  if (!s.src) continue;
  const len = s.frames / FPS + 0.5; // a little spare so the last frame never runs dry
  const file = `${s.id}.mp4`;
  execFileSync(join(tools, "ffmpeg"), [
    "-v", "error", "-y", "-itsscale", (1 / s.src.rate).toFixed(6), "-ss", s.src.fromSec.toFixed(3), "-i", join(root, "public", s.src.file),
    "-t", len.toFixed(3), "-an", "-r", String(FPS),
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-g", "15",
    join(out, file),
  ], { cwd: tools });
  manifest[s.id] = `${s.src.file}@${s.src.fromSec.toFixed(3)}x${s.src.rate.toFixed(4)}/${s.frames}`;
  process.stdout.write(".");
}
writeFileSync(join(out, "manifest.json"), JSON.stringify(manifest, null, 2));
console.log(`\n${Object.keys(manifest).length} cuts → public/cuts`);
