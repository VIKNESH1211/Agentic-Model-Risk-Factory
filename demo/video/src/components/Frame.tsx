import React from "react";
import { AbsoluteFill, OffthreadVideo, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig, Easing } from "remotion";
import type { Cam } from "../../vo/script";
import type { Timed } from "../timeline";
import { T } from "../theme";

export const Backdrop: React.FC<{ hue?: number }> = ({ hue = 0 }) => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: `radial-gradient(1200px 700px at ${30 + Math.sin((f + hue) / 90) * 6}% 18%, rgba(20,184,166,.16), transparent 60%), radial-gradient(1000px 700px at ${78 + Math.cos((f + hue) / 110) * 5}% 85%, rgba(139,92,246,.18), transparent 60%), ${T.bg0}` }}>
      <AbsoluteFill style={{ backgroundImage: "linear-gradient(rgba(148,163,184,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,.05) 1px, transparent 1px)", backgroundSize: "64px 64px", maskImage: "radial-gradient(ellipse at center, black 30%, transparent 80%)" }} />
    </AbsoluteFill>
  );
};

/** Interpolate camera keyframes (t = 0..1 of the shot) with eased transitions. */
function camAt(cam: Cam[] | undefined, p: number): { s: number; x: number; y: number } {
  if (!cam?.length) return { s: 1, x: 0.5, y: 0.5 };
  if (p <= cam[0][0]) return { s: cam[0][1], x: cam[0][2], y: cam[0][3] };
  for (let i = 0; i < cam.length - 1; i++) {
    const [t0, s0, x0, y0] = cam[i], [t1, s1, x1, y1] = cam[i + 1];
    if (p <= t1) {
      const k = Easing.inOut(Easing.cubic)((p - t0) / Math.max(1e-6, t1 - t0));
      return { s: s0 + (s1 - s0) * k, x: x0 + (x1 - x0) * k, y: y0 + (y1 - y0) * k };
    }
  }
  const l = cam[cam.length - 1];
  return { s: l[1], x: l[2], y: l[3] };
}

const FW = 1500, FH = Math.round((1500 * 9) / 16) + 40; // window incl. title bar

/** The product, framed as a macOS window, with camera moves inside it. */
export const ClipShot: React.FC<{ shot: Timed; children?: React.ReactNode; dim?: number }> = ({ shot, children, dim = 0 }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame: f, fps, config: { damping: 200 }, durationInFrames: 18 });
  const p = f / Math.max(1, shot.frames - 1);
  const c = camAt(shot.cam, p);
  const vw = FW, vh = FH - 40;
  const tx = (0.5 - c.x) * vw * c.s, ty = (0.5 - c.y) * vh * c.s;
  // keep the zoomed video covering the window
  const maxX = ((c.s - 1) * vw) / 2, maxY = ((c.s - 1) * vh) / 2;
  const cx = Math.max(-maxX, Math.min(maxX, tx)), cy = Math.max(-maxY, Math.min(maxY, ty));
  const path = { s01_floor: "/", s02_intake: "/agents", s04_intake_redraft: "/agents", s06_document: "/agents", s09_redevelop: "/agents",
    s13_validate: "/agents", s17_diagnose: "/agents", s03_gate1_sendback: "/models/CR-001", s05_gate1_approve: "/models/CR-001",
    s07_gate2_plans: "/models/CR-001", s08_graph: "/models", s10_parity: "/models/CR-001 · parity", s11_gate3_approvals: "/approvals",
    s12_rehost: "/models/CR-002", s14_report: "/reports", s15_gate4_deploy: "/models/CR-001", s16_monitor: "/monitoring",
    s18_accept: "/approvals", s19_governance: "/governance", s20_floor_end: "/", s03_gate1_review: "/models/CR-001",
    s07_gate2_sendback: "/models/CR-001", s07b_doc_redraft: "/agents", s07c_gate2_approve: "/models/CR-001 · monitoring plan",
    x_blocked_trace: "/agents", x_blocked_gate: "/models/CR-001",
    v_floor_start: "/", v_floor_docs: "/", v_floor_plans: "/", v_floor_end: "/", v_approvals: "/approvals", v_workbench: "/models/CR-001",
    v_parity: "/models/CR-001 · parity", v_rehost: "/models/CR-002", v_graph: "/models", v_kpi_edit: "/models/CR-001 · monitoring plan",
    v_monitor: "/monitoring", v_governance: "/governance", v_trace_intake: "/agents", v_trace_document: "/agents",
    v_trace_redevelop: "/agents", v_trace_validate: "/agents", v_trace_diagnose: "/agents" }[shot.clip || ""] || "/";
  return (
    <AbsoluteFill>
      <Backdrop hue={shot.start} />
      {shot.chapter && <Chapter text={shot.chapter} />}
      <div style={{ position: "absolute", left: (1920 - FW) / 2, top: 84 + (1 - enter) * 40, width: FW, height: FH, opacity: enter,
        borderRadius: 16, overflow: "hidden", boxShadow: "0 50px 120px rgba(0,0,0,.6), 0 0 0 1px rgba(148,163,184,.25)", background: "#fff" }}>
        <div style={{ height: 40, background: "linear-gradient(#f6f7f9,#eceef2)", display: "flex", alignItems: "center", padding: "0 16px", gap: 8, borderBottom: "1px solid #dfe3ea" }}>
          {["#ff5f57", "#febc2e", "#28c840"].map((c) => <span key={c} style={{ width: 13, height: 13, borderRadius: 7, background: c }} />)}
          <div style={{ marginLeft: 18, flex: 1, maxWidth: 560, height: 26, borderRadius: 8, background: "#fff", border: "1px solid #dfe3ea", display: "flex", alignItems: "center", padding: "0 12px",
            fontFamily: T.font, fontSize: 14, color: "#475569" }}>🔒&nbsp; Model Risk Factory&nbsp;<span style={{ color: "#94a3b8" }}>{path}</span></div>
        </div>
        <div style={{ position: "relative", width: vw, height: vh, overflow: "hidden", background: "#f8fafc" }}>
          {shot.src ? (
            <div style={{ position: "absolute", inset: 0, transform: `translate(${cx}px, ${cy}px) scale(${c.s})`, transformOrigin: "50% 50%" }}>
              <OffthreadVideo src={staticFile(shot.src.file)} startFrom={Math.round(shot.src.fromSec * fps)} playbackRate={shot.src.rate} muted
                style={{ width: vw, height: vh, objectFit: "cover" }} />
            </div>
          ) : <Missing name={shot.clip} />}
          {dim > 0 && <AbsoluteFill style={{ background: `rgba(7,11,22,${dim})` }} />}
        </div>
      </div>
      {shot.src && (shot.src.speed ?? shot.src.rate) > 1.9 && <SpeedTag rate={shot.src.speed ?? shot.src.rate} />}
      {children}
    </AbsoluteFill>
  );
};

const Missing: React.FC<{ name?: string }> = ({ name }) => (
  <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", fontFamily: T.font, color: "#64748b", fontSize: 28 }}>footage pending: {name}</AbsoluteFill>
);

export const Chapter: React.FC<{ text: string }> = ({ text }) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", left: 210, top: 30, display: "flex", alignItems: "center", gap: 14, opacity: o, transform: `translateX(${(1 - o) * -20}px)` }}>
      <span style={{ width: 10, height: 10, borderRadius: 5, background: T.grad }} />
      <span style={{ fontFamily: T.font, fontSize: 24, fontWeight: 600, letterSpacing: 0.4, color: T.ink }}>{text}</span>
    </div>
  );
};

const SpeedTag: React.FC<{ rate: number }> = ({ rate }) => (
  <div style={{ position: "absolute", right: 210, top: 36, fontFamily: T.mono, fontSize: 17, color: T.muted, display: "flex", alignItems: "center", gap: 8 }}>
    <span style={{ width: 8, height: 8, borderRadius: 4, background: T.red }} /> TIME-LAPSE · {rate >= 9.5 ? Math.round(rate) : rate.toFixed(1)}×
  </div>
);

/** Pointer + label anchored to a point in the footage (0..1 of the window). */
export const Callout: React.FC<{ text: string; x: number; y: number; at: number; frames: number }> = ({ text, x, y, at, frames }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t0 = Math.round(at * frames);
  const s = spring({ frame: f - t0, fps, config: { damping: 16, mass: 0.6 } });
  const t1 = Math.min(frames, t0 + Math.round(frames * 0.38));
  const out = interpolate(f, [t1 - 10, t1], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  if (f < t0) return null;
  const px = (1920 - FW) / 2 + x * FW, py = 84 + 40 + y * (FH - 40);
  return (
    <div style={{ position: "absolute", left: px, top: py, opacity: out }}>
      <span style={{ position: "absolute", left: -11, top: -11, width: 22, height: 22, borderRadius: 11, border: `3px solid ${T.teal}`, transform: `scale(${s})`, boxShadow: `0 0 0 ${8 * s}px rgba(20,184,166,.18)` }} />
      <div style={{ position: "absolute", left: 26, top: -24, whiteSpace: "nowrap", transform: `translateX(${(1 - s) * 20}px)`, opacity: s,
        background: "#0b1222", color: T.ink, fontFamily: T.font, fontSize: 22, fontWeight: 600, padding: "10px 16px", borderRadius: 12,
        border: `1px solid ${T.teal}`, boxShadow: "0 18px 40px rgba(0,0,0,.4)" }}>{text}</div>
    </div>
  );
};

/** "Why it matters" pill, top-right of the window. */
export const Badge: React.FC<{ text: string; frames: number }> = ({ text, frames }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: f - 16, fps, config: { damping: 15, mass: 0.6 } });
  const out = interpolate(f, [frames - 12, frames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", right: 250, top: 150, opacity: s * out, transform: `scale(${0.85 + s * 0.15})`, transformOrigin: "right center",
      background: "linear-gradient(135deg, rgba(20,184,166,.95), rgba(139,92,246,.95))", color: "#fff", fontFamily: T.font, fontSize: 24, fontWeight: 800,
      padding: "12px 22px", borderRadius: 999, boxShadow: "0 18px 50px rgba(0,0,0,.45)", letterSpacing: 0.3 }}>✦ {text}</div>
  );
};
