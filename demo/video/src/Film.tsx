import React from "react";
import { AbsoluteFill, Audio, Sequence, getStaticFiles, interpolate, staticFile, useCurrentFrame } from "remotion";
import { Captions } from "./components/Captions";
import { Badge, Callout, ClipShot } from "./components/Frame";
import { Impact, Innovation, Outro, Title } from "./components/Graphics";
import { AgentLoop, GateBadges, Ledger, ParityFlow, PlanToPanels, Rai, Sandbox, Stages, TwoPaths } from "./components/Overlays";
import { buildTimeline, type Timed } from "./timeline";

const OVERLAY: Record<string, React.FC<{ frames: number }>> = {
  agentLoop: AgentLoop, sandbox: Sandbox, parityFlow: ParityFlow, twoPaths: TwoPaths, planToPanels: PlanToPanels, gateBadges: GateBadges, ledger: Ledger, stages: Stages, rai: Rai,
};

const ShotView: React.FC<{ s: Timed; mode: "voiced" | "silent" }> = ({ s, mode }) => {
  const f = useCurrentFrame();
  const fadeIn = interpolate(f, [0, 8], [0, 1], { extrapolateRight: "clamp" });
  const Ov = s.overlay ? OVERLAY[s.overlay] : null;
  let body: React.ReactNode;
  if (s.graphic === "title") body = <Title shot={s} />;
  else if (s.graphic === "innovation") body = <Innovation />;
  else if (s.graphic === "impact") body = <Impact />;
  else if (s.graphic === "outro") body = <Outro />;
  else body = (
    <ClipShot shot={s} dim={Ov ? 0.12 : 0}>
      {s.callout && <Callout text={s.callout.text} x={s.callout.x} y={s.callout.y} at={s.callout.at ?? 0.2} frames={s.frames} />}
      {Ov && <Ov frames={s.frames} />}
      {s.badge && <Badge text={s.badge} frames={s.frames} />}
    </ClipShot>
  );
  return (
    <AbsoluteFill style={{ opacity: fadeIn }}>
      {body}
      {s.graphic !== "outro" && s.graphic !== "title" &&
        <Captions text={s.vo} voSec={s.voSec} mode={mode} overGraphic={!!s.graphic} />}
    </AbsoluteFill>
  );
};

export const Film: React.FC<{ mode: "voiced" | "silent" }> = ({ mode }) => {
  const { shots, total } = buildTimeline();
  const music = getStaticFiles().find((f) => f.name === "music.mp3");
  return (
    <AbsoluteFill style={{ background: "#070b16" }}>
      {shots.map((s) => (
        <Sequence key={s.id} from={s.start} durationInFrames={s.frames}>
          <ShotView s={s} mode={mode} />
          {mode === "voiced" && <Audio src={staticFile(`vo/${s.id}.wav`)} />}
        </Sequence>
      ))}
      {music && <Audio src={staticFile("music.mp3")} volume={(f) => (mode === "voiced" ? 0.12 : 0.5) * interpolate(f, [0, 30, total - 60, total], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })} />}
    </AbsoluteFill>
  );
};
