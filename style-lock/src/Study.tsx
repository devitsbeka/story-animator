import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Bone, Cam, Layer, LayerAsset, CamKey, M, Plane, Pose, bodyStep, camAt, mixPose, mul, S, simulate, solveRig, springStep, svgM, T } from "./engine";
import rig from "./assets/rig.json";
import room from "./assets/room.json";
import desk from "./assets/desk.json";
import lamp from "./assets/lamp.json";
import ball from "./assets/ball.json";
import head from "./assets/head.json";
import handL from "./assets/handL.json";
import handR from "./assets/handR.json";
import armL from "./assets/armL.json";
import armR from "./assets/armR.json";
import torso from "./assets/torso.json";
import browL from "./assets/browL.json";
import browR from "./assets/browR.json";
import eyeL from "./assets/eyeL.json";
import eyeR from "./assets/eyeR.json";
import mouth from "./assets/mouth.json";

const A = (x: unknown) => x as LayerAsset;
const PV = rig.pivots as unknown as Record<string, [number, number]>;

// ---------- the hero's skeleton ----------
export const BONES: Record<string, Bone> = {
  torso: { parent: null, pivot: PV.torso },
  head: { parent: "torso", pivot: PV.head },
  armL: { parent: "torso", pivot: PV.armL },
  handL: { parent: "armL", pivot: PV.handL },
  armR: { parent: "torso", pivot: PV.armR },
  handR: { parent: "armR", pivot: PV.handR },
};

export type Face = { blink: number; worry: number; mouth: "dot" | "smile" | "frown"; lookX: number; lookY: number };

// ---------- the hero, drawn from a solved pose ----------
export const Hero: React.FC<{ pose: Pose; face: Face }> = ({ pose, face }) => {
  const W = solveRig(BONES, pose);
  const g = (m: M, children: React.ReactNode) => <g transform={svgM(m)}>{children}</g>;
  const [ex, ey, erx, ery, ea] = rig.headEllipse;
  const eyeXf = (cx: number, cy: number): M =>
    mul(T(cx + face.lookX * 6, cy + face.lookY * 5), mul(S(1, Math.max(0.06, 1 - face.blink)), T(-cx, -cy)));
  const browXf = (side: -1 | 1): M => {
    // worry lifts the inner ends: rotate each brow about its outer end
    const [ox, oy] = side < 0 ? [378, 312] : [598, 312];
    const r = side * -face.worry * 6;
    const c = Math.cos((r * Math.PI) / 180), s = Math.sin((r * Math.PI) / 180);
    return mul(T(ox, oy - face.worry * 4), mul([c, s, -s, c, 0, 0], T(-ox, -oy)));
  };
  return (
    <g>
      {g(W.torso, <>
        <polygon points={rig.torsoHull.map((p) => p.join(",")).join(" ")} fill={rig.redColor} />
        <Layer a={A(torso)} id="torso" />
      </>)}
      {g(W.armL, <Layer a={A(armL)} id="armL" />)}
      {g(W.armR, <Layer a={A(armR)} id="armR" />)}
      {g(W.head, <>
        <ellipse cx={ex} cy={ey} rx={erx - 3} ry={ery - 3} transform={`rotate(${ea} ${ex} ${ey})`} fill={rig.headColor} stroke={rig.inkColor} strokeWidth={6} />
        <Layer a={A(head)} id="head" />
        <g transform={svgM(browXf(-1))}><Layer a={A(browL)} id="browL" /></g>
        <g transform={svgM(browXf(1))}><Layer a={A(browR)} id="browR" /></g>
        <g transform={svgM(eyeXf(424, 351))}><Layer a={A(eyeL)} id="eyeL" /></g>
        <g transform={svgM(eyeXf(550, 351))}><Layer a={A(eyeR)} id="eyeR" /></g>
        {face.mouth === "dot" && <Layer a={A(mouth)} id="mouth" />}
        {face.mouth === "smile" && <path d="M 462,380 Q 477,394 492,380" fill="none" stroke={rig.inkColor} strokeWidth={4.5} strokeLinecap="round" />}
        {face.mouth === "frown" && <path d="M 464,390 Q 477,380 490,390" fill="none" stroke={rig.inkColor} strokeWidth={4.5} strokeLinecap="round" />}
      </>)}
      {g(W.handL, <Layer a={A(handL)} id="handL" />)}
      {g(W.handR, <Layer a={A(handR)} id="handR" />)}
    </g>
  );
};

// ---------- the room, as depth planes ----------
export const Z = { room: 260, hero: 0, desk: -40, lamp: -90 };

const Glow: React.FC<{ f: number }> = ({ f }) => {
  const k = 0.9 + 0.06 * Math.sin(f * 0.37) + 0.04 * Math.sin(f * 1.13);
  return (
    <g style={{ mixBlendMode: "screen" }} opacity={0.3 * k}>
      <radialGradient id="lampGlow"><stop offset="0" stopColor="#ffd98a" stopOpacity="0.9" /><stop offset="0.4" stopColor="#ffb257" stopOpacity="0.25" /><stop offset="1" stopColor="#ff9030" stopOpacity="0" /></radialGradient>
      <circle cx={200} cy={212} r={170} fill="url(#lampGlow)" /><circle cx={196} cy={206} r={55} fill="url(#lampGlow)" />
    </g>
  );
};

// ---------- acting for the style-lock demo ----------
const REST: Pose = {};
const SIGH_IN: Pose = { torso: { sy: 1.025, dy: -4 }, head: { rot: -2, dy: -6 }, armL: { rot: -1.5 }, armR: { rot: 1.5 } };
const SIGH_OUT: Pose = { torso: { sy: 0.985, dy: 3 }, head: { rot: 3.5, dy: 5 }, armL: { rot: 1.2 }, armR: { rot: -1.2 } };
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const seg = (f: number, a: number, b: number) => ease(Math.max(0, Math.min(1, (f - a) / (b - a))));

const keyPose = (f: number): Pose => {
  if (f < 50) return mixPose(REST, SIGH_IN, seg(f, 20, 50));
  if (f < 90) return mixPose(SIGH_IN, SIGH_OUT, seg(f, 50, 90));
  return mixPose(SIGH_OUT, REST, seg(f, 110, 150));
};

// Physics on top of the keyed acting: the head lags behind the torso on a soft spring,
// and breathing runs continuously. Driven by simulate(), so it's deterministic.
type HeroSim = { hr: { x: number; v: number }; hy: { x: number; v: number } };
const heroSecondary = (f: number) =>
  simulate<HeroSim>("hero-secondary", f, () => ({ hr: { x: 0, v: 0 }, hy: { x: 0, v: 0 } }), (s, t, dt) => {
    const k = keyPose(t * 30);
    return { hr: springStep(s.hr, k.head?.rot ?? 0, dt, 1.4, 0.35), hy: springStep(s.hy, k.head?.dy ?? 0, dt, 1.8, 0.4) };
  });

const blinkAt = (f: number, frames: number[]) => {
  for (const b of frames) { const d = f - b; if (d >= 0 && d < 7) return d < 3 ? d / 3 : 1 - (d - 3) / 4; }
  return 0;
};

// The paper ball: dropped from above, bounces on the desk, rolls to rest.
const DESK_TOP = rig.ball.cy + rig.ball.r - 2;
const ballSim = (f: number) =>
  simulate("ball", f, () => ({ x: 150, y: DESK_TOP - rig.ball.r - 70, vx: 360, vy: -150, a: 0, w: 0, r: rig.ball.r }), (b, t, dt) =>
    t * 30 < 18 ? b : bodyStep(b, dt, () => DESK_TOP + 0 * t, { e: 0.42, mu: 0.1 }));

export const StudyScene: React.FC<{ f: number; vw: number; vh: number; cam: Cam; still?: boolean }> = ({ f, vw, vh, cam, still }) => {
  const k = still ? REST : keyPose(f);
  const sec = still ? null : heroSecondary(f);
  const breathe = still ? 0 : Math.sin(f * 0.09);
  const pose: Pose = {
    ...k,
    torso: { ...(k.torso ?? {}), sy: (k.torso?.sy ?? 1) + 0.008 * breathe },
    head: { ...(k.head ?? {}), rot: sec ? sec.hr.x : 0, dy: (sec ? sec.hy.x : 0) - 2 * breathe },
  };
  const face: Face = { blink: still ? 0 : blinkAt(f, [36, 96, 140]), worry: still ? 0 : 0.6 * seg(f, 40, 80), mouth: "dot", lookX: 0, lookY: still ? 0 : -0.6 * seg(f, 30, 60) + 0.6 * seg(f, 100, 130) };
  const b = still ? { x: rig.ball.cx, y: rig.ball.cy, a: 0 } : ballSim(f);
  const shadowK = still ? 1 : Math.max(0.15, 1 - (DESK_TOP - rig.ball.r - b.y) / 500);
  return (
    <svg width={vw} height={vh} viewBox={`0 0 ${vw} ${vh}`}>
      <rect width={vw} height={vh} fill="#2a160a" />
      <Plane cam={cam} z={Z.room} vw={vw} vh={vh}><Layer a={A(room)} id="room" /></Plane>
      <Plane cam={cam} z={Z.hero} vw={vw} vh={vh}><Hero pose={pose} face={face} /></Plane>
      <Plane cam={cam} z={Z.desk} vw={vw} vh={vh}>
        <Layer a={A(desk)} id="desk" />
        {!still && <ellipse cx={b.x} cy={DESK_TOP - 4} rx={44 * shadowK} ry={9 * shadowK} fill="#5a2c0c" opacity={0.35 * shadowK} />}
        <g transform={svgM(mul(T(b.x, b.y), mul([Math.cos((b.a * Math.PI) / 180), Math.sin((b.a * Math.PI) / 180), -Math.sin((b.a * Math.PI) / 180), Math.cos((b.a * Math.PI) / 180), 0, 0], T(-rig.ball.cx, -rig.ball.cy))))}>
          <Layer a={A(ball)} id="ball" />
        </g>
      </Plane>
      <Plane cam={cam} z={Z.lamp} vw={vw} vh={vh}><Layer a={A(lamp)} id="lamp" /><Glow f={f} /></Plane>
    </svg>
  );
};

// 1:1 still at rest: should line up with the reference.
export const StudySquare: React.FC = () => <StudyScene f={0} vw={1024} vh={1024} cam={{ x: 512, y: 512, zoom: 1, dolly: 0, roll: 0 }} still />;

// 9:16 motion test: slow push-in with parallax, a sigh, blinks, a paper ball dropping in.
const CAM916: CamKey[] = [
  [0, 512, 500, 2.0, 0, 0],
  [150, 505, 430, 2.0, 260, 0],
];
export const Study916: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill>
      <StudyScene f={f} vw={1080} vh={1920} cam={camAt(f, CAM916)} />
    </AbsoluteFill>
  );
};


