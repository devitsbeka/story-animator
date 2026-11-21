// Finish: the Remotion finishing pass over Blender plates. Data driven (any episode):
//   props = {episodeJson, platesDir, manifest, audio, captions, steps, range?}
// written by factory/finish/make_plates_manifest.py --stage into public/finish/<id>/props.json.
// Pass them inline with --props=<file>, or set {propsFile: "finish/<id>/props.json"} and
// calculateMetadata loads it (inline props win).
//
// Per frame: plate image sequence of the shot on screen (editorial cut / push / whip from edit.ts)
// -> house grade (filmic curve + halation) -> vignette -> grain -> STEP tracker -> captions; audio
// from the episode's mix or narration, placed at its offset.
import React from "react";
import { AbsoluteFill, Audio, CalculateMetadataFunction, Img, Sequence, staticFile, useCurrentFrame } from "remotion";
import { Captions, CAPTION_FONT } from "./Captions";
import { buildCuts, Layer, layersAt, plateId } from "./edit";
import { DEFAULT_GRADE, GradeDefs, Grain, Vignette } from "./Grade";
import { StepTracker } from "./StepTracker";
import { FinishEpisode, FinishProps } from "./types";

const EMPTY_EP: FinishEpisode = { id: "empty", fps: 30, width: 1080, height: 1920, durationFrames: 30, shots: [] };
const pad4 = (n: number) => String(n).padStart(4, "0");

const PlateLayer: React.FC<{ layer: Layer; platesDir: string; w: number; h: number }> = ({ layer, platesDir, w, h }) => {
  const { shot, plateFrame, opacity, scale, tx, streak, blur } = layer;
  const base: React.CSSProperties = { position: "absolute", inset: 0, width: w, height: h, objectFit: "cover" };
  if (plateFrame === null) {
    // shot not rendered yet: a dark slate keeps the edit timeable
    return (
      <AbsoluteFill style={{ opacity, transform: `translateX(${tx}px) scale(${scale})`, background: "linear-gradient(#0a1226, #03050c)", alignItems: "center", justifyContent: "center" }}>
        <div style={{ fontFamily: CAPTION_FONT, fontWeight: 800, fontSize: 56, color: "rgba(255,255,255,0.35)", textAlign: "center" }}>
          {shot.id}<br /><span style={{ fontSize: 34 }}>{shot.title ?? ""} · no plate</span>
        </div>
      </AbsoluteFill>
    );
  }
  const src = staticFile(`${platesDir}/${plateId(shot)}/${pad4(plateFrame)}.png`);
  // whip smear: a few copies spread along the motion, averaged (directional blur without WebGL)
  const n = streak > 4 ? Math.min(13, 5 + Math.round(streak / 40)) : 1;
  const copies = Array.from({ length: n }, (_, i) => (n === 1 ? 0 : (i / (n - 1) - 0.5) * streak));
  return (
    <AbsoluteFill style={{ opacity, transform: `translateX(${tx}px) scale(${scale})`, transformOrigin: "50% 46%", filter: blur > 0.3 ? `blur(${blur}px)` : undefined }}>
      {copies.map((dx, i) => (
        <Img key={i} src={src} style={{ ...base, transform: `translateX(${dx}px)`, opacity: i === 0 ? 1 : 1 / (i + 1) }} />
      ))}
    </AbsoluteFill>
  );
};

// hook title (ENGAGEMENT H-5 / C-6): the short's hook line in the hook band (y 330-500 of 1920), from frame 0
const HookTitle: React.FC<{ text: string; t: number; w: number; h: number }> = ({ text, t, w, h }) => {
  const k = h / 1920;
  const size = Math.min(64, 1500 / Math.max(10, text.length)) * k;
  return (
    <div style={{ position: "absolute", left: 0.06 * w, width: 0.88 * w, top: 330 * k, height: 170 * k, display: "flex",
      alignItems: "center", justifyContent: "center", textAlign: "center", opacity: Math.min(1, (t + 1) / 3) }}>
      <span style={{ fontFamily: CAPTION_FONT, fontWeight: 900, fontSize: size, lineHeight: 1.08, color: "#FFFFFF", textTransform: "uppercase",
        WebkitTextStroke: `${Math.round(size * 0.14)}px #000`, paintOrder: "stroke fill", textShadow: "0 6px 0 rgba(0,0,0,0.5)" }}>{text}</span>
    </div>
  );
};

export const Finish: React.FC<FinishProps> = (props) => {
  const ep = props.episodeJson ?? EMPTY_EP;
  const w = ep.width, h = ep.height;
  const range = props.range ?? { from: 0, to: ep.durationFrames };
  const f = useCurrentFrame() + range.from; // absolute film frame
  const captions = props.captions ?? [];
  const steps = props.steps ?? [];
  const manifest = props.manifest ?? {};
  const platesDir = props.platesDir ?? `finish/${ep.id}/plates`;
  const grade = { ...DEFAULT_GRADE, ...(props.grade ?? {}) };
  const cuts = React.useMemo(() => buildCuts(ep.shots, steps, captions, manifest), [ep, steps, captions, manifest]);
  const layers = layersAt(f, ep.shots, cuts, manifest, w);
  const audioAt = (ep.audio?.offsetFrames ?? 0) - range.from;
  const fadeIn = range.from === 0 ? Math.max(0, 1 - f / 8) : 0;
  const fadeOut = range.to >= ep.durationFrames ? Math.max(0, (f - (ep.durationFrames - 20)) / 20) : 0;
  return (
    <AbsoluteFill style={{ backgroundColor: "#03050c", overflow: "hidden" }}>
      <GradeDefs id="finish-grade" opts={grade} scale={1} />
      <AbsoluteFill style={{ filter: "url(#finish-grade)" }}>
        {layers.map((l, i) => <PlateLayer key={`${l.shot.id}-${i}`} layer={l} platesDir={platesDir} w={w} h={h} />)}
      </AbsoluteFill>
      <Vignette amount={grade.vignette} />
      <Grain frame={f} amount={grade.grain} width={w} height={h} />
      <StepTracker f={f} steps={steps} />
      {props.title && f >= props.title.from && f < props.title.to && <HookTitle text={props.title.text} t={f - props.title.from} w={w} h={h} />}
      <Captions f={f} pages={captions} w={w} h={h} />
      <AbsoluteFill style={{ backgroundColor: "#000", opacity: Math.max(fadeIn, fadeOut), pointerEvents: "none" }} />
      {props.audio && (
        audioAt >= 0
          ? <Sequence from={audioAt} layout="none"><Audio src={staticFile(props.audio)} /></Sequence>
          : <Audio src={staticFile(props.audio)} trimBefore={-audioAt} />
      )}
    </AbsoluteFill>
  );
};

// 16:9 docuseries master (FinishLandscape): the same pass; the canvas comes from episodeJson.width/height
// (1920x1080 from factory/director for format docuseries), falling back to 1920x1080 when nothing is staged.
const EMPTY_LANDSCAPE: FinishEpisode = { ...EMPTY_EP, width: 1920, height: 1080 };

async function finishMetadata(props: FinishProps, fallback: FinishEpisode) {
  let merged: FinishProps = props;
  if (props.propsFile) {
    try {
      const res = await fetch(staticFile(props.propsFile));
      if (res.ok) merged = { ...(await res.json()), ...props };
    } catch {
      // no staged props yet: render the empty episode
    }
  }
  const ep = merged.episodeJson ?? fallback;
  merged = { ...merged, episodeJson: ep };
  const range = merged.range ?? { from: 0, to: ep.durationFrames };
  return {
    durationInFrames: Math.max(1, range.to - range.from),
    fps: ep.fps, width: ep.width, height: ep.height,
    props: merged,
  };
}

export const calculateFinishMetadata: CalculateMetadataFunction<FinishProps> = async ({ props }) => finishMetadata(props, EMPTY_EP);
export const calculateFinishLandscapeMetadata: CalculateMetadataFunction<FinishProps> = async ({ props }) => finishMetadata(props, EMPTY_LANDSCAPE);
export const FINISH_LANDSCAPE_DEFAULT_PROPS: FinishProps = { propsFile: "finish/minidoc/props.json" };

export const FINISH_DEFAULT_PROPS: FinishProps = { propsFile: "finish/sentinel/props.json" };
