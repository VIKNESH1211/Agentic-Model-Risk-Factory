import { buildTimeline } from "../src/timeline";
const { shots, total } = buildTimeline();
for (const s of shots) console.log(s.id.padEnd(12), String(s.start).padStart(5), String(s.frames).padStart(4), s.src ? `${s.src.file} @${s.src.fromSec.toFixed(1)}s ×${s.src.rate.toFixed(2)}` : "");
console.log("total", total, "frames =", (total / 30).toFixed(1), "s");
