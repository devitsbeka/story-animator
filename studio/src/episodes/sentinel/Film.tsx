import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile, useCurrentFrame } from "remotion";
import { Caption, QuoteMarks, SANS } from "../../kit/type";
import { CAPS, CUE, DURATION, OFFSET, SCENES, SceneId, XFADE } from "./cues";
import { H, W, ease } from "./harness";
import { S1, S2, S3, S4, SceneProps } from "./scenesA";
import { S5, S6, S7, S8 } from "./scenesB";
import { S9, S10, S11 } from "./scenesC";

const MAP: Record<SceneId, React.FC<SceneProps>> = { yacht: S1, chart: S2, shore: S3, reef: S4, radio: S5, ashore: S6, stay: S7, primrose: S8, quiet: S9, tide: S10, outro: S11 };
const HALF = XFADE / 2;

// Step tracker: four dots, the current step filled. Only during the four steps.
const STEPS = [CUE.step1, CUE.step2, CUE.step3, CUE.step4];
const Steps: React.FC<{ f: number }> = ({ f }) => {
  if (f < CUE.step1 - 6 || f > CUE.tide - 4) return null;
  const cur = STEPS.reduce((a, s, i) => (f >= s - 4 ? i : a), 0);
  const o = Math.min(ease(Math.min(1, (f - CUE.step1 + 6) / 8)), ease(Math.min(1, (CUE.tide - 4 - f) / 8)));
  return (
    <div style={{ position: "absolute", top: H * 0.07, left: 0, right: 0, display: "flex", justifyContent: "center", alignItems: "center", gap: 18, opacity: o }}>
      {STEPS.map((s, i) => {
        const on = i === cur, done = i < cur;
        const k = on ? 1 + 0.25 * Math.max(0, 1 - (f - s + 4) / 8) : 1;
        return (
          <div key={i} style={{ width: 46 * k, height: 46 * k, borderRadius: 99, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: SANS, fontWeight: 700, fontSize: 22 * k,
            color: on ? "#0b1230" : "rgba(246,243,235,0.8)", background: on ? "#F6F3EB" : done ? "rgba(91,139,255,0.55)" : "rgba(10,14,40,0.55)", border: "2px solid rgba(246,243,235,0.7)", boxShadow: "0 2px 14px rgba(4,6,20,0.6)" }}>{i + 1}</div>
        );
      })}
    </div>
  );
};

export const SentinelFilm: React.FC = () => {
  const f = useCurrentFrame();
  const layers: React.ReactNode[] = [];
  SCENES.forEach((sc, i) => {
    const start = i === 0 ? 0 : sc.from - HALF, end = i === SCENES.length - 1 ? DURATION : sc.to + HALF;
    if (f < start || f >= end) return;
    const C = MAP[sc.id];
    // incoming: fades in over the overlap while already pushing forward; outgoing: accelerates in
    const tin = i === 0 ? 1 : Math.min(1, (f - start) / XFADE);
    const tout = i === SCENES.length - 1 ? 0 : Math.max(0, (f - (sc.to - HALF)) / XFADE);
    const push = (0.92 + 0.08 * ease(tin)) * (1 + 0.14 * tout * tout);
    layers.push(<AbsoluteFill key={sc.id} style={{ opacity: ease(tin) }}><C f={f} push={push} /></AbsoluteFill>);
  });
  const fadeOut = Math.max(0, (f - (DURATION - 20)) / 20);
  const fadeIn = Math.max(0, 1 - f / 8);
  return (
    <AbsoluteFill style={{ backgroundColor: "#03050f" }}>
      {layers}
      {CAPS.map((c, i) => <Caption key={i} f={f} {...c} w={W} h={H} />)}
      <Steps f={f} />
      {f >= CUE.never - 4 && <QuoteMarks f={f} from={CUE.never - 4} w={W} h={H} />}
      <AbsoluteFill style={{ backgroundColor: "#000", opacity: Math.max(fadeOut, fadeIn), pointerEvents: "none" }} />
      <Sequence from={OFFSET}><Audio src={staticFile(SOUND)} /></Sequence>
    </AbsoluteFill>
  );
};
// Picture lock uses the raw narration; after the mix this points at audio/mix_from0.wav with OFFSET 0.
export const SOUND = "audio/narration.mp3";
