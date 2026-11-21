import React from "react";
import { P, add, ellipse, ik2, lerpP, mulv, norm, perp, qcurve, rot, sub, superellipse, tube } from "./geom";
import { Brush, Line, Shape, Union } from "./render";
import { INK, MAT, Material, WEIGHT } from "./theme";

// ============================================================================
// THE HERO: a parametric, rigged character in the house style.
// Body proportions are fixed (that's the character's identity across episodes);
// everything that acts is a parameter: posture, head tilt, arm targets, hand
// shapes, expression, look direction, blink.
// ============================================================================

export type HandPose = "cheek" | "flat" | "fist" | "point" | "open" | "wave";
export type Brows = "worry" | "neutral" | "happy" | "angry" | "surprised";
export type Mouth = "dot" | "smile" | "grin" | "frown" | "o" | "flat";

export type HeroPose = {
  x: number; y: number; // root: middle of the waist / where the body meets the desk
  s?: number; // scale
  lean?: number; // torso rotation (deg)
  breathe?: number; // -1..1
  headTilt?: number; // deg, about the neck
  headDrop?: number; // px, head sinks/rises
  handL: P; handR: P; // wrist targets (world)
  elbowL?: P; elbowR?: P; // pin elbows (e.g. resting on the desk); otherwise IK decides
  handPoseL?: HandPose; handPoseR?: HandPose;
  handAngleL?: number; handAngleR?: number; // extra wrist rotation
  brows?: Brows; mouth?: Mouth;
  blink?: number; // 0 open, 1 closed
  look?: P; // -1..1 eye direction
  faceX?: number; // face turned left/right (px offset of features)
  blush?: number;
  sweater?: Material;
};

const S = MAT.skin;

// Body proportions (at s = 1).
const BODY = {
  headR: [193, 178] as P,
  headE: 2.15,
  neck: [0, -195] as P, // from root
  headC: [-4, -362] as P, // head centre from root
  shoulderL: [-128, -138] as P,
  shoulderR: [128, -138] as P,
  upper: 150,
  fore: 175,
  armW: 104,
};

// ---------- hands ----------
// Drawn in the hand's own frame: wrist at (0,0), fingers pointing to -y, inner (thumb) side +x.
const fingersFor = (pose: HandPose): { base: P; ang: number; len: number; w: number }[] => {
  switch (pose) {
    case "cheek":
      return [
        { base: [-25, -48], ang: -10, len: 44, w: 27 },
        { base: [-8, -54], ang: -3, len: 52, w: 28 },
        { base: [9, -54], ang: 4, len: 50, w: 28 },
        { base: [25, -48], ang: 11, len: 40, w: 26 },
      ];
    case "open":
    case "wave":
      return [
        { base: [-28, -38], ang: -28, len: 52, w: 23 },
        { base: [-10, -46], ang: -9, len: 60, w: 24 },
        { base: [9, -46], ang: 9, len: 58, w: 24 },
        { base: [26, -38], ang: 26, len: 48, w: 22 },
      ];
    case "point":
      return [{ base: [-2, -46], ang: 0, len: 66, w: 24 }];
    case "flat":
      return [
        { base: [-24, -42], ang: -4, len: 50, w: 24 },
        { base: [-7, -46], ang: -1, len: 56, w: 24 },
        { base: [10, -46], ang: 2, len: 54, w: 24 },
        { base: [26, -42], ang: 5, len: 44, w: 22 },
      ];
    case "fist":
    default:
      return [];
  }
};

export const Hand: React.FC<{ wrist: P; dir: P; pose: HandPose; side: -1 | 1; s?: number; extra?: number; seed?: number }> = ({ wrist, dir, pose, side, s = 1, extra = 0, seed = 1 }) => {
  // hand frame: fingers along `dir`, rotated by `extra`; mirrored for the left hand
  const ang = (Math.atan2(dir[1], dir[0]) * 180) / Math.PI + 90 + extra;
  const hs = s * 1.06; // hands are drawn a touch big: it reads as cute and expressive
  const W = (p: P): P => add(wrist, rot([p[0] * side * hs, p[1] * hs], ang));
  const palm = ellipse(0, -32, 43, 44, 32).map(W);
  const fingers = fingersFor(pose).map((fg) => {
    const tip = add(fg.base, rot([0, -fg.len], fg.ang));
    const mid = lerpP(fg.base, tip, 0.5);
    const bend = rot([fg.ang * 0.12, 0], fg.ang);
    return tube([fg.base, add(mid, bend), tip].map(W), (t) => fg.w * (1 - t * 0.12) * hs);
  });
  const thumb = pose === "fist" || pose === "point" || pose === "open" || pose === "wave"
    ? [tube(([[34, -22], [50, -40], [54, -58]] as P[]).map(W), () => 22 * hs)]
    : [];
  const fist = pose === "fist" || pose === "point" ? [ellipse(0, -48, 44, 30, 24).map(W)] : [];
  // interior lines: the gaps between fingers (only where fingers touch)
  const inner: P[][] = fingersFor(pose).slice(0, -1).map((fg, i, arr) => {
    const nx = fingersFor(pose)[i + 1];
    const a = lerpP(fg.base, nx.base, 0.5);
    const tipA = add(fg.base, rot([0, -fg.len * 0.82], fg.ang)), tipB = add(nx.base, rot([0, -nx.len * 0.82], nx.ang));
    return [add(a, [0, -6]), lerpP(tipA, tipB, 0.5)].map(W);
  });
  if (pose === "fist" || pose === "point") inner.push(...[-16, 0, 16].map((x) => [[x, -62], [x, -40]].map((p) => W(p as P))));
  return <Union parts={[palm, ...fist, ...fingers, ...thumb]} mat={S} seed={seed} ink={WEIGHT.hero - 0.5} inner={inner} innerW={WEIGHT.inner} shade={0.1} lit={0} />;
};

// ---------- arm (sleeve) ----------
const Sleeve: React.FC<{ shoulder: P; elbow: P; wrist: P; s: number; mat: Material; seed: number; front?: boolean }> = ({ shoulder, elbow, wrist, s, mat, seed }) => {
  const w = BODY.armW * s;
  const upper = tube([shoulder, lerpP(shoulder, elbow, 0.5), elbow], () => w);
  const foreDir = norm(sub(wrist, elbow));
  const cuffStart = sub(wrist, mulv(foreDir, 46 * s));
  const fore = tube([elbow, lerpP(elbow, cuffStart, 0.5), cuffStart], (t) => w * (1.02 - t * 0.08));
  const cuffN = perp(foreDir);
  const cw = w * 0.93 / 2;
  const cuffEnd = sub(wrist, mulv(foreDir, 2 * s));
  const cuff: P[] = [add(cuffStart, mulv(cuffN, cw)), add(cuffEnd, mulv(cuffN, cw * 0.98)), add(cuffEnd, mulv(cuffN, -cw * 0.98)), add(cuffStart, mulv(cuffN, -cw))];
  const ribs: P[][] = Array.from({ length: 8 }, (_, i) => {
    const t = (i + 1) / 9 * 2 - 1;
    return [add(cuffStart, mulv(cuffN, cw * t)), add(cuffEnd, mulv(cuffN, cw * t))];
  });
  // a couple of folds where the sleeve bends at the elbow
  const elbowOut = add(elbow, mulv(perp(norm(sub(elbow, shoulder))), w * 0.25));
  return (
    <g>
      <Union parts={[upper, fore]} mat={mat} seed={seed} shade={0.14} lit={0.06} ink={WEIGHT.hero}>
        <Line pts={[add(elbowOut, mulv(foreDir, 30)), add(elbowOut, mulv(foreDir, 62))]} w={WEIGHT.detail + 0.6} color={mat.line} opacity={0.8} />
        <Line pts={[add(elbow, mulv(foreDir, 70)), add(add(elbow, mulv(foreDir, 110)), mulv(cuffN, 14))]} w={WEIGHT.detail} color={mat.line} opacity={0.6} />
      </Union>
      <Shape pts={cuff} mat={mat} round={0.25} wob={0.4} shade={0.12} lit={0.05} ink={WEIGHT.hero - 1} seed={seed + 5}>
        {ribs.map((r, i) => <Line key={i} pts={r} w={1.8} color={mat.line} wob={0.2} />)}
      </Shape>
    </g>
  );
};

// ---------- face ----------
const Face: React.FC<{ c: P; s: number; tilt: number; p: HeroPose }> = ({ c, s, tilt, p }) => {
  const fx = (p.faceX ?? -27) * s;
  const lk = p.look ?? [0, 0];
  const F = (q: P): P => add(c, rot([q[0] * s + fx, q[1] * s], tilt));
  const open = 1 - (p.blink ?? 0);
  const brows = p.brows ?? "worry";
  const eyeY = 62 + (brows === "surprised" ? -4 : 0);
  const eyes = [-63, 63].map((ex) => {
    const cx = ex + lk[0] * 8, cy = eyeY + lk[1] * 6;
    if (open < 0.15) return <Line key={ex} pts={qcurve(F([cx - 17, cy]), F([cx, cy + 8]), F([cx + 17, cy]), 8)} w={5.5 * s} />;
    const pts = ellipse(cx, cy, 18, 26 * open, 30).map(F);
    return <Shape key={ex} pts={pts} mat={{ base: INK, shade: INK, lit: INK, line: INK }} ink={0} shade={0} lit={0} wob={0.3} />;
  });
  // brows: [outer, mid, inner] per side, shaped by expression
  const B: Record<Brows, [P, P, P]> = {
    worry: [[-122, 26], [-94, 8], [-62, 2]],
    neutral: [[-122, 14], [-92, 6], [-60, 10]],
    happy: [[-122, 18], [-92, 2], [-60, 12]],
    angry: [[-124, 4], [-92, 14], [-58, 28]],
    surprised: [[-124, 0], [-92, -14], [-58, -4]],
  };
  const browL = B[brows];
  const browR = browL.map(([x, y]) => [-x, y] as P).reverse() as [P, P, P];
  const mouth = p.mouth ?? "dot";
  const mx = -2, my = 104;
  const M: Record<Mouth, React.ReactNode> = {
    dot: <circle cx={F([mx, my])[0]} cy={F([mx, my])[1]} r={3.6 * s} fill={INK} />,
    smile: <Brush pts={qcurve(F([mx - 16, my - 3]), F([mx, my + 10]), F([mx + 16, my - 3]), 10)} w={6 * s} />,
    grin: <Shape pts={[...qcurve([mx - 22, my - 4], [mx, my + 26], [mx + 22, my - 4], 10).map(F)]} mat={{ base: "#7a2a1a", shade: "#5a1a10", lit: "#a8432a", line: INK }} ink={4 * s} shade={0} lit={0} round={0.6} />,
    frown: <Brush pts={qcurve(F([mx - 14, my + 6]), F([mx, my - 5]), F([mx + 14, my + 6]), 10)} w={6 * s} />,
    o: <Shape pts={ellipse(mx, my + 2, 8, 11, 18).map(F)} mat={{ base: "#5a1a10", shade: "#5a1a10", lit: "#5a1a10", line: INK }} ink={4 * s} shade={0} lit={0} />,
    flat: <Line pts={[F([mx - 12, my]), F([mx + 12, my])]} w={4.5 * s} />,
  };
  return (
    <g>
      {(p.blush ?? 0) > 0 && [-110, 100].map((x) => <ellipse key={x} cx={F([x, 108])[0]} cy={F([x, 108])[1]} rx={26 * s} ry={13 * s} fill="#f4a08a" opacity={0.45 * (p.blush ?? 0)} />)}
      <Brush pts={qcurve(...(browL.map(F) as [P, P, P]), 12)} w={8 * s} />
      <Brush pts={qcurve(...(browR.map(F) as [P, P, P]), 12)} w={8 * s} />
      {eyes}
      {M[mouth]}
      {/* two freckle dots: part of the character's identity */}
      <circle cx={F([-22, 98])[0]} cy={F([-22, 98])[1]} r={1.8 * s} fill={S.line} />
      <circle cx={F([-30, 106])[0]} cy={F([-30, 106])[1]} r={1.4 * s} fill={S.line} />
    </g>
  );
};

// ---------- the whole character ----------
export const Hero: React.FC<{ p: HeroPose; seed?: number }> = ({ p, seed = 1 }) => {
  const s = p.s ?? 1;
  const root: P = [p.x, p.y];
  const lean = p.lean ?? 0;
  const br = p.breathe ?? 0;
  const R = (q: P): P => add(root, rot([q[0] * s, q[1] * s * (1 + br * 0.012)], lean));
  const sweater = p.sweater ?? MAT.sweater;
  // torso
  const torso: P[] = [[-150, 30], [-160, -70], [-140, -138], [-92, -180], [-40, -194], [40, -194], [92, -180], [140, -138], [160, -70], [150, 30]].map((q) => R(q as P));
  const collar = tube(qcurve(R([-62, -186]), R([0, -168]), R([62, -186]), 12), () => 20 * s);
  // head
  const neck = R(BODY.neck);
  const tilt = (p.headTilt ?? 0) + lean;
  const hc = add(R(BODY.headC), [0, (p.headDrop ?? 0) * s]);
  const headC = rot(hc, p.headTilt ?? 0, neck);
  const head = superellipse(0, 0, BODY.headR[0] * s, BODY.headR[1] * s, BODY.headE, 64).map((q) => add(headC, rot(q, tilt)));
  // arms
  const shL = R(BODY.shoulderL), shR = R(BODY.shoulderR);
  const elL = p.elbowL ?? ik2(shL, p.handL, BODY.upper * s, BODY.fore * s, -1);
  const elR = p.elbowR ?? ik2(shR, p.handR, BODY.upper * s, BODY.fore * s, 1);
  return (
    <g>
      <Shape pts={torso} mat={sweater} seed={seed} ink={WEIGHT.hero} shade={0.1} lit={0.04} hatch={0}>
        {/* soft fold under the chest */}
        <Line pts={[R([-70, -120]), R([-30, -100]), R([10, -108])]} w={WEIGHT.detail} color={sweater.line} opacity={0.5} />
      </Shape>
      <Shape pts={collar} mat={sweater} seed={seed + 1} ink={WEIGHT.inner} shade={0.2} lit={0.1}>
        {Array.from({ length: 11 }, (_, i) => {
          const t = i / 10;
          const a = qcurve(R([-62, -196]), R([0, -178]), R([62, -196]), 10)[Math.round(t * 10)];
          const b = qcurve(R([-62, -176]), R([0, -158]), R([62, -176]), 10)[Math.round(t * 10)];
          return <Line key={i} pts={[a, b]} w={1.6} color={sweater.line} wob={0.1} />;
        })}
      </Shape>
      <Shape pts={head} mat={S} seed={seed + 2} ink={WEIGHT.hero + 0.5} shade={0.045} lit={0.04} wob={0.3} />
      <Face c={headC} s={s} tilt={tilt} p={p} />
      <Sleeve shoulder={shL} elbow={elL} wrist={p.handL} s={s} mat={sweater} seed={seed + 10} />
      <Sleeve shoulder={shR} elbow={elR} wrist={p.handR} s={s} mat={sweater} seed={seed + 20} />
      <Hand wrist={p.handL} dir={norm(sub(p.handL, elL))} pose={p.handPoseL ?? "cheek"} side={1} s={s} extra={p.handAngleL ?? 0} seed={seed + 30} />
      <Hand wrist={p.handR} dir={norm(sub(p.handR, elR))} pose={p.handPoseR ?? "cheek"} side={-1} s={s} extra={p.handAngleR ?? 0} seed={seed + 40} />
    </g>
  );
};

// Helpers for poses that depend on the head (e.g. hands cupping the cheeks follow the head).
export const headAnchor = (p: HeroPose, local: P): P => {
  const s = p.s ?? 1;
  const root: P = [p.x, p.y];
  const lean = p.lean ?? 0;
  const R = (q: P): P => add(root, rot([q[0] * s, q[1] * s], lean));
  const neck = R(BODY.neck);
  const hc = add(R(BODY.headC), [0, (p.headDrop ?? 0) * s]);
  const headC = rot(hc, p.headTilt ?? 0, neck);
  return add(headC, rot([local[0] * s, local[1] * s], (p.headTilt ?? 0) + lean));
};
