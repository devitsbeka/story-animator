import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Cam, CamKey, Plane, bodyStep, camAt, camMatrix, simulate, springStep, svgM } from "../kit/engine";
import { Hero, HeroPose, headAnchor } from "../kit/character";
import { Bookcase, BookStack, ChairBack, Desk, DeskLamp, Mug, OpenBook, PaperBall, PaperSheet, Pencil, Phone, PinnedPaper, StickyNote, Wall, Book } from "../kit/props";
import { Stage } from "../kit/render";
import { LIGHTS, MAT } from "../kit/theme";

// ============================================================================
// SCENE: late-night study. Built entirely from kit parts, with no images.
// World is 1024 × 1024 (the style reference's framing). Depth planes:
// room z=260, hero z=0, desk z=-40, lamp z=-90.
// ============================================================================

export const Z = { room: 260, hero: 0, desk: -40, lamp: -90 };

const LAMP = { O: [205, 212] as [number, number], axis: 62, L: 150, r0: 36, r1: 80, anchor: [-40, 262] as [number, number] };

const Room: React.FC<{ f: number }> = ({ f }) => (
  <g>
    <Wall w={1024} h={1024} patch={[[392, -40], [905, -40], [905, 150], [700, 330], [560, 520], [392, 520]]} shadows={[[[905, 150], [905, 700], [740, 700], [700, 330]]]} seed={2} />
    <Bookcase x={-40} y={-30} w={238} h={700} rows={[0.2, 0.48, 0.78]} seed={3} />
    <Bookcase x={905} y={60} w={200} h={620} rows={[0.2, 0.62]} seed={4} />
    {/* tall books leaning against the right case */}
    {[0, 1, 2].map((i) => <Book key={i} x={865 + i * 18} y={445} w={210 - i * 30} h={16} r={-90} seed={40 + i} />)}
    <PinnedPaper x={835} y={108} w={112} h={135} r={-1} seed={5} />
    <StickyNote x={790} y={305} s={76} seed={6} />
    <StickyNote x={770} y={210} s={24} mat={MAT.cream} seed={7} />
    <StickyNote x={890} y={218} s={22} mat={MAT.cream} seed={8} />
    <ChairBack x={790} y={378} w={205} h={300} seed={9} />
  </g>
);

const DeskTop: React.FC<{ f: number; ball: { x: number; y: number; a: number } }> = ({ f, ball }) => (
  <g>
    <Desk top={[[-80, 624], [1110, 612], [1110, 935], [-80, 940]]} thick={44} under={160} seed={11} />
    <BookStack x={92} y={712} n={13} w={230} seed={12} />
    <BookStack x={995} y={706} n={8} w={160} seed={13} lean={-1} />
    <Mug x={168} y={752} h={140} seed={14} steam={1} f={f} />
    <PaperSheet x={80} y={790} w={210} h={120} r={-6} seed={15} />
    <OpenBook cx={510} cy={752} w={560} d={118} seed={16} />
    <PaperSheet x={560} y={810} w={330} h={92} r={2} skew={0.18} seed={17} />
    <PaperSheet x={735} y={790} w={170} h={60} r={-3} seed={18} lines={3} />
    <StickyNote x={418} y={838} s={88} r={-2} mat={MAT.note} seed={19} />
    <Pencil x={700} y={765} len={120} a={-36} seed={20} />
    <Pencil x={800} y={745} len={100} a={-14} mat={MAT.phone} seed={21} />
    <Pencil x={650} y={868} len={130} a={-20} seed={22} />
    <g>
      <Book x={930} y={880} w={240} h={30} r={-8} mat={MAT.lilac} seed={23} />
      <Book x={925} y={850} w={230} h={28} r={-7} mat={MAT.cream} seed={24} />
      <Book x={920} y={822} w={220} h={30} r={-7} mat={MAT.green} seed={25} />
    </g>
    <Phone x={815} y={856} seed={26} />
    <PaperBall x={848} y={612} r={42} seed={27} a={10} />
    <PaperBall x={ball.x} y={ball.y} r={44} a={ball.a} seed={28} />
  </g>
);

// ---------- acting (data, so it can be generated per episode) ----------
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const seg = (f: number, a: number, b: number) => ease(Math.max(0, Math.min(1, (f - a) / (b - a))));

const posture = (f: number) => {
  // a sigh: rise 20→50, sink 50→90, settle 110→150
  const rise = seg(f, 20, 50) - seg(f, 50, 90) * 1.6 + seg(f, 110, 150) * 0.6;
  return { headDrop: -rise * 8, headTilt: rise * -2 };
};

const heroPose = (f: number, still: boolean): HeroPose => {
  // springy head: lags behind the keyed posture (physics, deterministic)
  const sp = still ? null : simulate("hero-head", f, () => ({ d: { x: 0, v: 0 }, r: { x: 0, v: 0 } }), (s, tt, dt) => {
    const k = posture(tt * 30);
    return { d: springStep(s.d, k.headDrop, dt, 1.6, 0.4), r: springStep(s.r, k.headTilt, dt, 1.3, 0.35) };
  });
  const base: HeroPose = {
    x: 520, y: 650, s: 1,
    breathe: still ? 0 : Math.sin(f * 0.09),
    headDrop: sp ? sp.d.x : 0,
    headTilt: sp ? sp.r.x : 0,
    handL: [0, 0], handR: [0, 0],
    elbowL: [318, 628], elbowR: [724, 630],
    handPoseL: "cheek", handPoseR: "cheek", handAngleL: -12, handAngleR: 22,
    brows: "worry", mouth: "dot",
    blink: still ? 0 : blink(f, [36, 96, 140]),
    look: still ? [0, 0] : [0, -0.5 * seg(f, 30, 60) + 0.5 * seg(f, 100, 130)],
  };
  // hands cup the cheeks, so they follow the head
  base.handL = headAnchor(base, [-158, 196]);
  base.handR = headAnchor(base, [136, 196]);
  return base;
};

const blink = (f: number, at: number[]) => {
  for (const b of at) { const d = f - b; if (d >= 0 && d < 7) return d < 3 ? d / 3 : 1 - (d - 3) / 4; }
  return 0;
};

const DESK_Y = 838;
const ballAt = (f: number) =>
  simulate("study-ball", f, () => ({ x: 120, y: DESK_Y - 44 - 70, vx: 360, vy: -150, a: 0, w: 0, r: 44 }), (b, t, dt) => (t * 30 < 18 ? b : bodyStep(b, dt, () => DESK_Y, { e: 0.42, mu: 0.1 })));

export const StudyScene: React.FC<{ f: number; vw: number; vh: number; cam: Cam; still?: boolean }> = ({ f, vw, vh, cam, still = false }) => {
  const light = LIGHTS.lampNight;
  const flick = still ? 1 : 0.94 + 0.04 * Math.sin(f * 0.37) + 0.02 * Math.sin(f * 1.13);
  const b = still ? { x: 270, y: DESK_Y - 44, a: 0 } : ballAt(f);
  return (
    <Stage light={light} w={vw} h={vh} world={{ w: 1024, h: 1024 }} flicker={flick} viewTransform={svgM(camMatrix(cam, Z.hero, vw, vh))}>
      <rect width={vw} height={vh} fill="#3a1d0c" />
      <Plane cam={cam} z={Z.room} vw={vw} vh={vh}><Room f={f} /></Plane>
      <Plane cam={cam} z={Z.hero} vw={vw} vh={vh}><Hero p={heroPose(f, still)} /></Plane>
      <Plane cam={cam} z={Z.desk} vw={vw} vh={vh}><DeskTop f={f} ball={b} /></Plane>
      <Plane cam={cam} z={Z.lamp} vw={vw} vh={vh}><DeskLamp {...LAMP} /></Plane>
    </Stage>
  );
};

export const StudySquare: React.FC = () => <StudyScene f={0} vw={1024} vh={1024} cam={{ x: 512, y: 512, zoom: 1, dolly: 0, roll: 0 }} still />;

const CAM916: CamKey[] = [
  [0, 512, 500, 2.0, 0, 0],
  [150, 505, 430, 2.0, 260, 0],
];
export const Study916: React.FC = () => {
  const f = useCurrentFrame();
  return <AbsoluteFill><StudyScene f={f} vw={1080} vh={1920} cam={camAt(f, CAM916)} /></AbsoluteFill>;
};

