import durations from "../vo/durations.json";
import markersJson from "../public/clips/markers.json";
import cutsJson from "../public/cuts/manifest.json";
import { SHOTS, type Shot } from "../vo/script";

export const FPS = 30;
const PAD = 0.45; // a natural breath after each line

type Markers = Record<string, { duration: number; marks: Record<string, number> }>;
const markers = markersJson as Markers;

export type Timed = Shot & {
  frames: number;
  voSec: number;
  start: number; // first frame in the film
  src?: { file: string; fromSec: number; rate: number; speed?: number }; // footage window (speed = real speed-up when pre-cut)
};


function markSec(clip: string, m: string | number | undefined, fallback: number): number {
  if (typeof m === "number") return m;
  const c = markers[clip];
  if (!c || !m) return fallback;
  const [, name, sign, off] = m.match(/^([a-z0-9_]+)(?:([+-])([\d.]+))?$/i) || [];
  const base = name === "end" ? c.duration : name === "open" ? (c.marks.open ?? 0) : c.marks[name];
  if (base == null) return fallback;
  return base + (sign ? (sign === "+" ? 1 : -1) * parseFloat(off) : 0);
}

export function buildTimeline(raw = false): { shots: Timed[]; total: number } {
  let start = 0;
  const shots = SHOTS.map((s) => {
    const voSec = (durations as any).shots[s.id] ?? 3;
    const sec = Math.max(voSec + PAD, s.minSec ?? 0);
    const frames = Math.ceil(sec * FPS);
    let src: Timed["src"];
    if (s.clip && markers[s.clip]) {
      const dur = markers[s.clip].duration;
      let a = Math.max(0, markSec(s.clip, s.from, 0));
      let b = Math.min(dur, markSec(s.clip, s.to, dur));
      if (b - a < 0.5) { a = 0; b = dur; }
      // play near real speed; if the window is still longer than the shot, keep its start or its end
      const cap = s.maxRate ?? 1.5;
      const rate = Math.min(cap, Math.max(1, (b - a) / sec));
      const fromSec = s.anchor === "end" ? Math.max(a, b - sec * rate) : a;
      src = { file: `clips/${s.clip}.mp4`, fromSec, rate };
      const key = `${src.file}@${fromSec.toFixed(3)}x${rate.toFixed(4)}/${frames}`;
      if (!raw && (cutsJson as Record<string, string>)[s.id] === key) src = { file: `cuts/${s.id}.mp4`, fromSec: 0, rate: 1, speed: rate };
    }
    const t: Timed = { ...s, frames, voSec, start, src };
    start += frames;
    return t;
  });
  return { shots, total: start };
}
