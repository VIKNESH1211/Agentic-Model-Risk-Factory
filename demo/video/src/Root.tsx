import React from "react";
import { Composition } from "remotion";
import { Film } from "./Film";
import { FPS, buildTimeline } from "./timeline";

export const Root: React.FC = () => {
  const { total } = buildTimeline();
  return (
    <>
      <Composition id="DemoVoice" component={Film} durationInFrames={total} fps={FPS} width={1920} height={1080} defaultProps={{ mode: "voiced" as const }} />
      <Composition id="DemoSilent" component={Film} durationInFrames={total} fps={FPS} width={1920} height={1080} defaultProps={{ mode: "silent" as const }} />
    </>
  );
};
