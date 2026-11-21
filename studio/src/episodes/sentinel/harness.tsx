import React from "react";
import { Cam, CamKey, Plane, apply, camAt, camMatrix, svgM } from "../../kit/engine";
import { OceanGL } from "../../kit/oceanGL";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Hero, HeroPose, STREET } from "../../kit/character";
import { P, add, rot } from "../../kit/geom";
import { Stage } from "../../kit/render";
import { LightRig, envAt } from "../../kit/theme";
import { yachtPoint } from "../../kit/sea";

export const W = 1080, H = 1920;
export const WC: [number, number] = [540, 960];

export const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
export const eout = (t: number) => 1 - Math.pow(1 - t, 3);
export const seg = (f: number, a: number, b: number) => ease(Math.max(0, Math.min(1, (f - a) / (b - a))));
export const lin = (f: number, a: number, b: number) => Math.max(0, Math.min(1, (f - a) / (b - a)));
export const pop = (f: number, a: number, d = 10) => {
  // overshoot pop 0 → 1.08 → 1
  const t = Math.max(0, Math.min(1, (f - a) / d));
  const c1 = 1.9, c3 = c1 + 1;
  return t >= 1 ? 1 : t <= 0 ? 0 : 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
};
// decaying shake after an impact at frame a
export const shake = (f: number, a: number, amp = 18, dur = 22) => {
  const t = f - a;
  if (t < 0 || t > dur) return [0, 0, 0];
  const k = (1 - t / dur) ** 2;
  return [Math.sin(t * 2.3) * amp * k, Math.cos(t * 2.9) * amp * 0.7 * k, Math.sin(t * 1.7) * 1.4 * k];
};

export const NIGHT = (kx: number, ky: number, strength = 0.22): LightRig => ({
  key: { x: kx, y: ky, color: "#c4d4ff", reach: 1500, strength },
  ambient: "#4f5fa6", ambientStrength: 0.12, vignette: 0.55, grain: 0,
});

// The camera never stops: keyframes + a slow handheld drift + optional impact shake.
export const camera = (f: number, keys: CamKey[], push = 1, sh: number[] = [0, 0, 0]): Cam => {
  const c = camAt(f, keys);
  return {
    x: c.x + Math.sin(f * 0.013) * 9 + Math.sin(f * 0.031 + 1) * 4 + sh[0],
    y: c.y + Math.sin(f * 0.017 + 2) * 7 + sh[1],
    zoom: c.zoom * push,
    dolly: c.dolly,
    roll: c.roll + Math.sin(f * 0.011) * 0.35 + sh[2],
  };
};

export type Layer = { z: number; node: React.ReactNode };
// GPU sea + sky: horizon and moon given in WORLD coords on their planes, projected by the same camera
export type GLSea = { horizon: number; z: number; moon: [number, number]; moonZ: number; moonR?: number; dawn?: number; chop?: number; heave?: number; splash?: number; wet?: number; front?: { z: number; pts: P[] } };
export const SceneView: React.FC<{ cam: Cam; light: LightRig; layers: Layer[]; fx?: Layer[]; bg?: string; sea?: GLSea }> = ({ cam, light, layers, fx = [], bg = "#060a1f", sea }) => {
  const f = useCurrentFrame();
  const stage = (
    <Stage light={sea ? { ...light, key: { ...light.key, color: envAt(sea.dawn ?? 0).moon } } : light} screenGrade={!sea} w={W} h={H} world={{ w: 2400, h: 3200 }} worldOrigin={[-600, -600]} viewTransform={svgM(camMatrix(cam, 0, W, H, WC[0], WC[1]))}
      fx={fx.map((l, i) => <Plane key={i} cam={cam} z={l.z} vw={W} vh={H} wc={WC}>{l.node}</Plane>)}>
      {!sea && <rect width={W} height={H} fill={bg} />}
      {layers.map((l, i) => <Plane key={i} cam={cam} z={l.z} vw={W} vh={H} wc={WC}>{l.node}</Plane>)}
    </Stage>
  );
  if (!sea) return stage;
  const camNoRoll = { ...cam, roll: 0 };
  const hor = apply(camMatrix(camNoRoll, sea.z, W, H, WC[0], WC[1]), WC[0], sea.horizon);
  const mo = apply(camMatrix(camNoRoll, sea.moonZ, W, H, WC[0], WC[1]), sea.moon[0], sea.moon[1]);
  const sMoon = camMatrix(camNoRoll, sea.moonZ, W, H, WC[0], WC[1])[0];
  const frontPts = sea.front ? sea.front.pts.map((q) => { const v = apply(camMatrix(cam, sea.front!.z, W, H, WC[0], WC[1]), q[0], q[1]); return [v[0], v[1]] as [number, number]; }) : undefined;
  return (
    <AbsoluteFill>
      <OceanGL w={W} h={H} t={f / 30} horizon={hor[1]} camX={cam.x - WC[0]} zoom={cam.zoom * (1 + cam.dolly / 1200)} moon={[mo[0], mo[1]]} moonR={(sea.moonR ?? 56) * sMoon} dawn={sea.dawn ?? 0} chop={sea.chop ?? 1} roll={cam.roll}
        heave={sea.heave ?? 0} splash={sea.splash ?? -1} wet={sea.wet ?? 0} front={frontPts}>
        <AbsoluteFill>{stage}</AbsoluteFill>
      </OceanGL>
      {/* ONE grade over both renderers: palette tint (multiply) + soft vignette */}
      <AbsoluteFill style={{ backgroundColor: envAt(sea.dawn ?? 0).grade, mixBlendMode: "multiply", opacity: light.ambientStrength }} />
      <AbsoluteFill style={{ background: `radial-gradient(ellipse 75% 60% at 50% 46%, rgba(0,0,0,0) 55%, ${envAt(sea.dawn ?? 0).ink}cc 100%)`, opacity: light.vignette * 1.3 }} />
    </AbsoluteFill>
  );
};

// The hero standing in the yacht's hatch, clipped at the hatch rim so he climbs out of it.
let clipN = 0;
export const HatchHero: React.FC<{ bx: number; by: number; bs: number; br: number; emerge: number; s?: number; pose?: Partial<HeroPose>; arms?: "rim" | "up" | "shrug" | "custom" }> = ({ bx, by, bs, br, emerge, s = 0.27, pose = {}, arms = "rim" }) => {
  if (emerge <= 0.001) return null;
  const Q = (p: P) => yachtPoint(bx, by, bs, br, p);
  const rim = Q([0, -184]);
  const hs = s * bs;
  const root = add(rim, rot([0, (1 - emerge) * 330 * hs + 40 * hs], br));
  const id = `hatch${++clipN}`;
  const clip = [[-400, -2000], [400, -2000], [400, -184], [-400, -184]].map((p) => Q(p as P));
  const handsRim: [P, P] = [Q([-52, -192]), Q([52, -192])];
  // targets kept inside the arm's reach (upper + forearm ≈ 232 × s)
  const up: [P, P] = [add(root, rot([-196 * hs, -350 * hs], br)), add(root, rot([196 * hs, -350 * hs], br))];
  const shrug: [P, P] = [add(root, rot([-250 * hs, -120 * hs], br)), add(root, rot([250 * hs, -120 * hs], br))];
  const hands = arms === "up" ? up : arms === "shrug" ? shrug : handsRim;
  const p: HeroPose = {
    x: root[0], y: root[1], s: hs, lean: br,
    handL: hands[0], handR: hands[1],
    handPoseL: arms === "rim" ? "fist" : "open", handPoseR: arms === "rim" ? "fist" : "open",
    handAbsL: arms === "rim" || arms === "up" ? (arms === "up" ? -10 : 0) : undefined, handAbsR: arms === "rim" || arms === "up" ? (arms === "up" ? 10 : 0) : undefined,
    handAngleL: arms === "shrug" ? -70 : 0, handAngleR: arms === "shrug" ? 70 : 0,
    outfit: STREET,
    brows: "worry", mouth: "o", ...pose,
  };
  if (arms === "custom") {
    p.handPoseL = pose.handPoseL ?? "fist"; p.handPoseR = pose.handPoseR ?? "fist";
    p.handAngleL = pose.handAngleL ?? 0; p.handAngleR = pose.handAngleR ?? 0;
    p.handAbsL = pose.handAbsL ?? (p.handPoseL === "fist" ? 0 : undefined); p.handAbsR = pose.handAbsR ?? (p.handPoseR === "fist" ? 0 : undefined);
  }
  return (
    <g>
      <defs><clipPath id={id}><path d={"M" + clip.map((q) => q.join(",")).join("L") + "Z"} /></clipPath></defs>
      <g clipPath={`url(#${id})`}><Hero p={p} /></g>
    </g>
  );
};

// Boat motion: wave bob plus decaying jolts at impact frames. Pure function of f (no state).
export type Kick = { at: number; pitch: number; heave: number };
export const boatMotion = (f: number, kicks: Kick[] = [], calm = 1) => {
  let r = Math.sin(f * 0.05 + 1) * 1.6 * calm + Math.sin(f * 0.13) * 0.4 * calm;
  let y = Math.sin(f * 0.06) * 7 * calm + Math.sin(f * 0.11 + 2) * 3 * calm;
  kicks.forEach((k) => {
    const t = f - k.at;
    if (t < 0) return;
    const env = Math.exp(-t / 9);
    r += k.pitch * env * Math.cos(t * 0.55);
    y += k.heave * env * Math.sin(t * 0.7);
  });
  return { r, y };
};
// on/off flicker driven by a seed (for failing lights)
export const flicker = (f: number, a: number, b: number, seed = 1) => {
  if (f < a) return 1;
  if (f >= b) return 0;
  const h = Math.sin((Math.floor(f / 2) + seed) * 12.9898) * 43758.5453;
  return h - Math.floor(h) > 0.45 + 0.4 * ((f - a) / (b - a)) ? 1 : 0;
};

// Points on the hatch hero, in hero units (× s × boat scale) measured from the hatch rim.
// Head centre ≈ (-4, -322), mouth ≈ (-33, -218), right cheek ≈ (110, -250), shoulders ≈ (±140, -92).
export const heroPt = (bx: number, by: number, bs: number, br: number, s: number, local: P): P => {
  const rim = yachtPoint(bx, by, bs, br, [0, -184]);
  return add(rim, rot([local[0] * s * bs, local[1] * s * bs], br));
};
