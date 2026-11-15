import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { T } from "../theme";

/**
 * Words appear in step with the narration (uniform pacing over the line's spoken duration).
 * voiced: a compact lower-third line.  silent: large two-line kinetic captions.
 */
export const Captions: React.FC<{ text: string; voSec: number; mode: "voiced" | "silent"; overGraphic?: boolean }> = ({ text, voSec, mode, overGraphic }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const words = text.split(/\s+/);
  const t = f / fps;
  const per = voSec / words.length;
  const shown = Math.min(words.length, Math.floor(t / per) + 1);
  // show the current chunk of ~14 words (voiced) / ~11 (silent) so lines never overflow
  const chunk = mode === "voiced" ? 14 : 11;
  const ci = Math.floor((shown - 1) / chunk);
  const seg = words.slice(ci * chunk, ci * chunk + chunk);
  const fade = interpolate(f, [0, 6], [0, 1], { extrapolateRight: "clamp" });
  if (mode === "voiced") {
    return (
      <div style={{ position: "absolute", left: 0, right: 0, bottom: overGraphic ? 46 : 22, display: "flex", justifyContent: "center", opacity: fade }}>
        <div style={{ maxWidth: 1500, fontFamily: T.font, fontSize: 30, lineHeight: 1.35, color: T.ink, textAlign: "center",
          background: "rgba(7,11,22,.72)", padding: "10px 22px", borderRadius: 12 }}>
          {seg.map((w, i) => <span key={i} style={{ opacity: ci * chunk + i < shown ? 1 : 0.28 }}>{w} </span>)}
        </div>
      </div>
    );
  }
  return (
    <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: overGraphic ? 220 : 250, display: "flex", alignItems: "flex-end", justifyContent: "center",
      paddingBottom: 34, background: overGraphic ? "none" : "linear-gradient(transparent, rgba(7,11,22,.92) 55%)", opacity: fade }}>
      <div style={{ maxWidth: 1560, fontFamily: T.font, fontSize: 46, fontWeight: 700, lineHeight: 1.25, color: "#fff", textAlign: "center", letterSpacing: -0.4 }}>
        {seg.map((w, i) => {
          const k = ci * chunk + i;
          const o = k < shown ? 1 : 0;
          return <span key={i} style={{ opacity: o, display: "inline-block", transform: `translateY(${o ? 0 : 10}px)`, marginRight: 13,
            color: /^(agent|agents|human|reviewer|parity|rehost|rehosted|ledger|sandbox|proven|evidence|person|people)/i.test(w) ? T.tealSoft : "#fff" }}>{w}</span>;
        })}
      </div>
    </div>
  );
};
