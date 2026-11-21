import React from "react";
import { Cam, CamKey, Plane, camAt, camMatrix, svgM } from "../../kit/engine";
import { Hero, HeroPose } from "../../kit/character";
import { P, add, rot } from "../../kit/geom";
import { Stage } from "../../kit/render";
import { LightRig } from "../../kit/theme";
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
export const SceneView: React.FC<{ cam: Cam; light: LightRig; layers: Layer[]; fx?: Layer[]; bg?: string }> = ({ cam, light, layers, fx = [], bg = "#060a1f" }) => (
  <Stage light={light} w={W} h={H} world={{ w: 2400, h: 3200 }} worldOrigin={[-600, -600]} viewTransform={svgM(camMatrix(cam, 0, W, H, WC[0], WC[1]))}
    fx={fx.map((l, i) => <Plane key={i} cam={cam} z={l.z} vw={W} vh={H} wc={WC}>{l.node}</Plane>)}>
    <rect width={W} height={H} fill={bg} />
    {layers.map((l, i) => <Plane key={i} cam={cam} z={l.z} vw={W} vh={H} wc={WC}>{l.node}</Plane>)}
  </Stage>
);

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
  const handsRim: [P, P] = [Q([-40, -190]), Q([40, -190])];
  const up: [P, P] = [add(root, rot([-230 * hs, -560 * hs], br)), add(root, rot([230 * hs, -560 * hs], br))];
  const shrug: [P, P] = [add(root, rot([-250 * hs, -150 * hs], br)), add(root, rot([250 * hs, -150 * hs], br))];
  const hands = arms === "up" ? up : arms === "shrug" ? shrug : handsRim;
  const p: HeroPose = {
    x: root[0], y: root[1], s: hs, lean: br,
    handL: hands[0], handR: hands[1],
    handPoseL: arms === "rim" ? "fist" : "open", handPoseR: arms === "rim" ? "fist" : "open",
    handAngleL: arms === "rim" ? 160 : 0, handAngleR: arms === "rim" ? -160 : 0,
    brows: "worry", mouth: "o", ...pose,
  };
  return (
    <g>
      <defs><clipPath id={id}><path d={"M" + clip.map((q) => q.join(",")).join("L") + "Z"} /></clipPath></defs>
      <g clipPath={`url(#${id})`}><Hero p={p} /></g>
    </g>
  );
};
