import React from "react";
import { P, add, ellipse, ik2, lerpP, mulv, norm, perp, qcurve, rot, sub, superellipse, tube } from "./geom";
import { Brush, Line, Shape, Union } from "./render";
import { INK, MAT, Material, WEIGHT } from "./theme";
import { SANS } from "./type";

// ============================================================================
// THE HERO: anatomically grounded cartoon rig.
//
// References (technique only, no art copied):
//  - Skeleton-driven illustration (bones + bound parts): google pose-animator, Apache-2.0.
//  - 2-bone IK with explicit bend direction: DragonBones runtime, MIT.
//  - Hand gestures as per-finger curl (none/half/full) + direction: andypotato/fingerpose, MIT.
//  - Facial expressions as FACS action units (AU1, 2, 4, 5, 6, 7, 12, 15, 18, 26).
//
// Proportions (in head radii, R = 190 at s = 1): upper arm 0.6R, forearm 0.62R, hand length
// ~0.78R, palm width ~0.44R. Finger segments follow real phalanx ratios (≈ 0.45 / 0.32 / 0.23).
// ============================================================================

export type HandPose = "cheek" | "flat" | "fist" | "point" | "open" | "wave" | "grip" | "rim" | "shh" | "relaxed";
export type Brows = "worry" | "neutral" | "happy" | "angry" | "surprised";
export type Mouth = "dot" | "smile" | "grin" | "frown" | "o" | "flat";

// FACS-style controls, 0..1
export type AU = {
  innerUp?: number; // AU1  inner brow raiser
  outerUp?: number; // AU2  outer brow raiser
  browDown?: number; // AU4  brow lowerer
  lidUp?: number; // AU5  upper lid raiser (eyes go big)
  lidTight?: number; // AU7  lid tightener
  cheekUp?: number; // AU6  cheek raiser (smiling eyes)
  smile?: number; // AU12 lip corner puller
  frown?: number; // AU15 lip corner depressor
  jaw?: number; // AU26 jaw drop
  pucker?: number; // AU18 lip pucker
  squeeze?: number; // eyes squeezed shut (sneeze, wince)
  sweat?: number; // cartoon sweat drop
};

export const EXPR: Record<string, AU> = {
  neutral: {},
  worried: { innerUp: 0.8, browDown: 0.25, frown: 0.25 },
  scared: { innerUp: 1, outerUp: 0.6, browDown: 0.2, lidUp: 0.8, jaw: 0.35, frown: 0.2, sweat: 1 },
  surprised: { innerUp: 0.8, outerUp: 0.9, lidUp: 1, jaw: 0.55 },
  shout: { browDown: 0.8, lidTight: 0.3, jaw: 1, smile: 0.15 },
  determined: { browDown: 0.7, lidTight: 0.35, frown: 0.1 },
  happy: { cheekUp: 0.7, smile: 1, outerUp: 0.2 },
  grin: { cheekUp: 0.9, smile: 1, jaw: 0.45 },
  sneeze: { squeeze: 1, browDown: 0.5, jaw: 0.5, pucker: 0.1 },
  hush: { innerUp: 0.5, pucker: 0.8, lidTight: 0.2 },
  sad: { innerUp: 1, frown: 0.8, lidTight: 0.2 },
};

// legacy names → AU (so older scene code keeps working)
const BROW_AU: Record<Brows, AU> = { worry: { innerUp: 0.8, browDown: 0.25 }, neutral: {}, happy: { outerUp: 0.3, cheekUp: 0.4 }, angry: { browDown: 0.9, lidTight: 0.3 }, surprised: { innerUp: 0.8, outerUp: 0.9, lidUp: 1 } };
const MOUTH_AU: Record<Mouth, AU> = { dot: {}, smile: { smile: 0.9, cheekUp: 0.3 }, grin: { smile: 1, jaw: 0.5, cheekUp: 0.6 }, frown: { frown: 0.9 }, o: { jaw: 0.45, pucker: 0.6 }, flat: { frown: 0.15 } };

export type HeroPose = {
  x: number; y: number; s?: number;
  lean?: number; breathe?: number;
  headTilt?: number; headDrop?: number;
  handL: P; handR: P;
  elbowL?: P; elbowR?: P;
  handPoseL?: HandPose; handPoseR?: HandPose;
  handAngleL?: number; handAngleR?: number;
  handAbsL?: number; handAbsR?: number; // absolute hand angle (deg, 0 = fingers up): for gestures like shh or pointing
  expr?: keyof typeof EXPR | AU;
  brows?: Brows; mouth?: Mouth; // legacy
  blink?: number; look?: P; faceX?: number; blush?: number;
  sweater?: Material;
  outfit?: Outfit;
};

// Wardrobe: the rig is the same; outfits are swappable layers.
export type Outfit = { top?: "sweater" | "hoodie"; cap?: boolean; wordmark?: string; topMat?: Material; capMat?: Material };
export const STREET: Outfit = { top: "hoodie", cap: true, wordmark: "PALENCIAGA" };

const S = MAT.skin;
const R = 190;
const BODY = {
  headR: [193, 178] as P, headE: 2.15,
  neck: [0, -196] as P, headC: [-4, -362] as P,
  shoulderL: [-122, -150] as P, shoulderR: [122, -150] as P,
  upper: 0.6 * R, fore: 0.62 * R,
  armW: 0.4 * R,
};
export const HERO_BODY = BODY;

// ---------------------------------------------------------------------------
// HAND: palm + four 3-segment fingers + 2-segment thumb, posed by curl (fingerpose model)
// Local frame: wrist at (0,0), fingers toward -y, thumb side toward +x.
// ---------------------------------------------------------------------------
type Fin = { curl: number; spread: number };
type Gesture = { view: "front" | "side"; t: Fin; f: [Fin, Fin, Fin, Fin]; thumb?: boolean };
const G = (view: "front" | "side", t: [number, number], f: [number, number][], thumb = true): Gesture => ({ view, t: { curl: t[0], spread: t[1] }, f: f.map(([curl, spread]) => ({ curl, spread })) as [Fin, Fin, Fin, Fin], thumb });
const GESTURES: Record<HandPose, Gesture> = {
  //            thumb[curl,spread]  index      middle    ring       pinky
  cheek: G("front", [0.3, 10], [[0.12, 6], [0.1, 0], [0.12, -6], [0.18, -12]], false),
  relaxed: G("front", [0.3, 20], [[0.35, 5], [0.4, 0], [0.45, -5], [0.5, -10]]),
  open: G("front", [0, 40], [[0, 14], [0, 2], [0, -10], [0, -22]]),
  wave: G("front", [0, 44], [[0, 16], [0, 3], [0, -11], [0, -25]]),
  flat: G("front", [0.2, 18], [[0, 3], [0, 0], [0, -3], [0, -6]]),
  fist: G("front", [0.9, 30], [[1, 2], [1, 0], [1, -2], [1, -4]]),
  point: G("front", [0.8, 30], [[0, 4], [1, 0], [1, -2], [1, -4]]),
  shh: G("front", [0.8, 30], [[0, 0], [1, 0], [1, -2], [1, -4]]),
  grip: G("side", [0.6, 60], [[0.8, 0], [0.85, 0], [0.9, 0], [0.95, 0]]),
  rim: G("side", [0.4, 50], [[0.55, 0], [0.6, 0], [0.62, 0], [0.65, 0]]),
};
const FINGERS = [
  { base: [21, -74] as P, len: 52, w: 23 }, // index (thumb side)
  { base: [6, -79] as P, len: 58, w: 24 },
  { base: [-10, -77] as P, len: 54, w: 23 },
  { base: [-24, -69] as P, len: 42, w: 21 }, // pinky
];
const SEG = [0.45, 0.32, 0.23];
const FLEX = [65, 95, 60]; // MCP / PIP / DIP flexion at full curl (degrees)

export const Hand: React.FC<{ wrist: P; dir: P; pose: HandPose; side: -1 | 1; s?: number; extra?: number; abs?: number; seed?: number }> = ({ wrist, dir, pose, side, s = 1, extra = 0, abs, seed = 1 }) => {
  const g = GESTURES[pose] ?? GESTURES.relaxed;
  const ang = abs !== undefined ? abs : (Math.atan2(dir[1], dir[0]) * 180) / Math.PI + 90 + extra;
  const hs = s;
  const W = (p: P): P => add(wrist, rot([p[0] * side * hs, p[1] * hs], ang));
  const parts: P[][] = [];
  const inner: P[][] = [];
  // palm: a soft trapezoid, wider at the knuckles, with a fleshy heel on the thumb side
  const palm: P[] = [[-26, -2], [-34, -30], [-34, -62], [-24, -78], [0, -84], [24, -80], [36, -60], [40, -34], [30, -10], [14, 0]];
  const fingerChains: P[][] = [];
  g.f.forEach((fs, i) => {
    const F = FINGERS[i];
    const pts: P[] = [F.base];
    let a = fs.spread, p = F.base;
    SEG.forEach((sg, k) => {
      if (g.view === "front") {
        // fingers curl toward the viewer: foreshorten instead of bending in plane
        const bend = (fs.curl * FLEX.slice(0, k + 1).reduce((x, y) => x + y, 0) * Math.PI) / 180;
        const vis = Math.cos(Math.min(Math.PI / 2, bend));
        p = add(p, rot([0, -F.len * sg * Math.max(0.12, vis)], a));
      } else {
        a += fs.curl * FLEX[k];
        p = add(p, rot([0, -F.len * sg], a));
      }
      pts.push(p);
    });
    fingerChains.push(pts);
    const wd = F.w * (g.view === "side" ? 0.95 : 1);
    parts.push(tube(pts.map(W), (t) => (wd - t * 4) * hs));
    if (g.view === "front" && fs.curl > 0.6) inner.push([add(F.base, [-wd * 0.32, -6]), add(F.base, [wd * 0.32, -6])].map(W));
  });
  if (g.view === "front") {
    for (let i = 0; i < 3; i++) {
      const a = fingerChains[i], b = fingerChains[i + 1];
      const tip = lerpP(a[3], b[3], 0.5);
      const base = lerpP(a[0], b[0], 0.5);
      if (Math.hypot(tip[0] - base[0], tip[1] - base[1]) > 14) inner.push([add(base, [0, -4]), lerpP(base, tip, 0.85)].map(W));
    }
  } else {
    fingerChains.slice(1).forEach((ch, i) => inner.push([lerpP(ch[1], ch[2], 0.2), ch[2], ch[3]].map((q) => W(add(q, [-4 * (i + 1), 2])))));
  }
  if (g.thumb) {
    const base: P = [32, -26];
    const a = 70 - g.t.spread + g.t.curl * 110; // curl swings it across the palm
    const p1 = add(base, rot([0, -26], a)), p2 = add(p1, rot([0, -22], a + g.t.curl * 45));
    parts.push(tube([base, p1, p2].map(W), (t) => (25 - t * 5) * hs));
    if (g.t.curl > 0.5) inner.push([lerpP(base, p1, 0.4), p1].map(W));
  }
  if (g.view === "front" && g.f[1].curl < 0.5) inner.push(qcurve([-22, -40], [0, -50], [22, -44], 6).map(W));
  return <Union parts={[palm.map(W), ...parts]} mat={S} seed={seed} ink={WEIGHT.hero - 1} inner={inner} innerW={WEIGHT.inner - 0.4} shade={0.1} lit={0} />;
};

// ---------------------------------------------------------------------------
// ARM: shoulder cap + upper arm + forearm sleeve (one silhouette), ribbed cuff
// ---------------------------------------------------------------------------
const Sleeve: React.FC<{ shoulder: P; elbow: P; wrist: P; s: number; mat: Material; seed: number }> = ({ shoulder, elbow, wrist, s, mat, seed }) => {
  const w = BODY.armW * s;
  const foreDir = norm(sub(wrist, elbow));
  const cuffStart = sub(wrist, mulv(foreDir, 34 * s));
  const upper = tube([shoulder, lerpP(shoulder, elbow, 0.5), elbow], (t) => w * (1.08 - t * 0.12));
  const fore = tube([elbow, lerpP(elbow, cuffStart, 0.5), cuffStart], (t) => w * (0.96 - t * 0.1));
  const cap = ellipse(shoulder[0], shoulder[1], w * 0.6, w * 0.55, 20);
  const n = perp(foreDir);
  const cw = (w * 0.86) / 2;
  const cuffEnd = sub(wrist, mulv(foreDir, -2 * s));
  const cuff: P[] = [add(cuffStart, mulv(n, cw)), add(cuffEnd, mulv(n, cw * 0.95)), add(cuffEnd, mulv(n, -cw * 0.95)), add(cuffStart, mulv(n, -cw))];
  const ribs: P[][] = Array.from({ length: 7 }, (_, i) => {
    const t = ((i + 1) / 8) * 2 - 1;
    return [add(cuffStart, mulv(n, cw * t)), add(cuffEnd, mulv(n, cw * t * 0.95))];
  });
  const upDir = norm(sub(elbow, shoulder));
  const bendSide = Math.sign(upDir[0] * foreDir[1] - upDir[1] * foreDir[0]) || 1;
  const inside = add(elbow, mulv(perp(upDir), -bendSide * w * 0.28));
  return (
    <g>
      <Union parts={[cap, upper, fore]} mat={mat} seed={seed} shade={0.14} lit={0.07} ink={WEIGHT.hero}>
        <Brush pts={[add(inside, mulv(foreDir, 6)), add(inside, mulv(foreDir, 30))]} w={4 * s + 1.5} color={mat.line} taper={0.9} />
        <Brush pts={[add(inside, mulv(upDir, -8)), add(inside, mulv(upDir, -30))]} w={3 * s + 1.2} color={mat.line} taper={0.9} opacity={0.8} />
      </Union>
      <Shape pts={cuff} mat={mat} round={0.25} wob={0.3} shade={0.12} lit={0.05} ink={WEIGHT.hero - 1.5} seed={seed + 5}>
        {ribs.map((r, i) => <Line key={i} pts={r} w={1.8} color={mat.line} wob={0.1} />)}
      </Shape>
    </g>
  );
};

// pick the IK solution whose elbow points outward and down: elbows never fold inward
const elbowFor = (shoulder: P, wrist: P, l1: number, l2: number, side: -1 | 1, cx: number): P => {
  const a = ik2(shoulder, wrist, l1, l2, 1), b = ik2(shoulder, wrist, l1, l2, -1);
  const score = (e: P) => (e[0] - cx) * side + e[1] * 0.35;
  return score(a) > score(b) ? a : b;
};

// ---------------------------------------------------------------------------
// FACE (FACS-driven)
// ---------------------------------------------------------------------------
const mix = (a: AU, b: AU): AU => {
  const o: AU = { ...a };
  (Object.keys(b) as (keyof AU)[]).forEach((k) => { o[k] = Math.min(1, (o[k] ?? 0) + (b[k] ?? 0)); });
  return o;
};
const faceAU = (p: HeroPose): AU => {
  if (p.expr) return typeof p.expr === "string" ? EXPR[p.expr] ?? {} : p.expr;
  return mix(BROW_AU[p.brows ?? "neutral"], MOUTH_AU[p.mouth ?? "dot"]);
};

const Face: React.FC<{ c: P; s: number; tilt: number; p: HeroPose }> = ({ c, s, tilt, p }) => {
  const au = faceAU(p);
  const v = (k: keyof AU) => au[k] ?? 0;
  const fx = (p.faceX ?? -27) * s;
  const lk = p.look ?? [0, 0];
  const F = (q: P): P => add(c, rot([q[0] * s + fx, q[1] * s], tilt));
  const blink = Math.max(p.blink ?? 0, v("squeeze"));
  const EY = 62;
  const poly = (pts: P[]) => "M" + pts.map((q) => q.join(",")).join("L") + "Z";
  const eyes = [-1, 1].map((side) => {
    const cx = side * 63 + lk[0] * 8, cy = EY + lk[1] * 6;
    const rx = 18 * (1 + v("lidUp") * 0.12), ry = 27 * (1 + v("lidUp") * 0.18);
    const close = Math.min(1, blink + v("lidTight") * 0.32 + v("browDown") * 0.12);
    const raise = v("cheekUp") * 0.38;
    if (close > 0.86 || v("squeeze") > 0.5) {
      const sq = v("squeeze") > 0.5;
      const pts = sq ? [F([cx - 18, cy - 6]), F([cx + side * 4, cy + 4]), F([cx + 18, cy - 6])] : qcurve(F([cx - 18, cy]), F([cx, cy + 9]), F([cx + 18, cy]), 8);
      return <Brush key={side} pts={pts} w={6.5 * s} taper={0.5} />;
    }
    const eye = ellipse(cx, cy, rx, ry, 32).map(F);
    const lidY = cy - ry + 2 * ry * close;
    const lowY = cy + ry - 2 * ry * raise;
    const cl = F([cx - 6, cy - ry * 0.45]);
    return (
      <g key={side}>
        <Shape pts={eye} mat={{ base: INK, shade: INK, lit: INK, line: INK }} ink={0} shade={0} lit={0} wob={0.2}>
          <circle cx={cl[0]} cy={cl[1]} r={3.2 * s} fill="#ffffff" opacity={0.9} />
          {close > 0.02 && <path d={poly([F([cx - 40, cy - 60]), F([cx + 40, cy - 60]), F([cx + 40, lidY]), F([cx - 40, lidY])])} fill={S.base} />}
          {raise > 0.02 && <path d={poly([F([cx - 40, cy + 60]), F([cx + 40, cy + 60]), ...qcurve(F([cx + 40, lowY + 6]), F([cx, lowY - 6]), F([cx - 40, lowY + 6]), 6)])} fill={S.base} />}
        </Shape>
        {close > 0.05 && <Brush pts={qcurve(F([cx - rx - 2, lidY + 2]), F([cx, lidY - 3]), F([cx + rx + 2, lidY + 2]), 8)} w={5 * s} taper={0.5} />}
      </g>
    );
  });
  const brows = [-1, 1].map((side) => {
    const ex = side * 63;
    const inn: P = [ex - side * 36 + side * 6 * v("browDown"), 16 - 18 * v("innerUp") + 16 * v("browDown")];
    const mid: P = [ex, -6 * v("innerUp") - 10 * v("outerUp") + 6 * v("browDown")];
    const out: P = [ex + side * 34, 18 - 16 * v("outerUp") + 2 * v("browDown") + 6 * v("innerUp")];
    return <Brush key={side} pts={qcurve(F(inn), F(mid), F(out), 12)} w={8.5 * s} taper={0.7} />;
  });
  const mx = -2, my = 106;
  const open = v("jaw") * 72;
  const cw = 16 + 12 * v("smile") - 9 * v("pucker") + 12 * v("jaw");
  const cy = -11 * v("smile") + 10 * v("frown");
  let mouth: React.ReactNode;
  if (open < 4 && v("smile") < 0.15 && v("frown") < 0.15 && v("pucker") < 0.3) {
    const d = F([mx, my]);
    mouth = <circle cx={d[0]} cy={d[1]} r={3.6 * s} fill={INK} />;
  } else if (open < 4) {
    if (v("pucker") >= 0.3) mouth = <Shape pts={ellipse(mx, my, 7, 8, 16).map(F)} mat={{ base: "#6a2016", shade: "#6a2016", lit: "#6a2016", line: INK }} ink={4 * s} shade={0} lit={0} />;
    else mouth = <Brush pts={qcurve(F([mx - cw, my + cy]), F([mx, my - cy * 0.6 + 4 * v("smile")]), F([mx + cw, my + cy]), 10)} w={6.2 * s} taper={0.6} />;
  } else {
    const top = qcurve([mx - cw, my + cy], [mx, my - 6 - 2 * v("smile")], [mx + cw, my + cy], 10);
    const bot = qcurve([mx + cw, my + cy], [mx, my + open + 4 - 6 * v("frown")], [mx - cw, my + cy], 10);
    const shape = [...top, ...bot.slice(1)].map(F);
    const tg = F([mx, my + open * 0.8]);
    mouth = (
      <Shape pts={shape} mat={{ base: "#5a1a12", shade: "#5a1a12", lit: "#5a1a12", line: INK }} ink={4.6 * s} shade={0} lit={0} round={0.7} wob={0.2}>
        <ellipse cx={tg[0]} cy={tg[1]} rx={cw * 0.7 * s} ry={open * 0.35 * s} fill="#d9605a" />
        {(v("smile") > 0.3 || v("jaw") > 0.6) && <path d={poly([F([mx - cw, my - 20]), F([mx + cw, my - 20]), F([mx + cw, my + cy + 6]), F([mx - cw, my + cy + 6])])} fill="#fffaf0" />}
      </Shape>
    );
  }
  const blush = Math.min(1, (p.blush ?? 0) + v("cheekUp") * 0.6);
  const fr1 = F([-26, 98]), fr2 = F([-34, 106]);
  return (
    <g>
      {blush > 0 && [-112, 98].map((x) => { const q = F([x, 112]); return <ellipse key={x} cx={q[0]} cy={q[1]} rx={24 * s} ry={12 * s} fill="#f4a08a" opacity={0.4 * blush} />; })}
      {brows}
      {eyes}
      {mouth}
      <circle cx={fr1[0]} cy={fr1[1]} r={1.8 * s} fill={S.line} />
      <circle cx={fr2[0]} cy={fr2[1]} r={1.4 * s} fill={S.line} />
      {v("sweat") > 0 && <Shape pts={[F([150, -40]), F([162, -6]), F([150, 4]), F([138, -6])]} mat={{ base: "#bfe3ff", shade: "#8cc6f2", lit: "#ffffff", line: "#5a9ad0" }} ink={3.2 * s} round={0.9} shade={0.2} lit={0.2} seed={77} />}
    </g>
  );
};

// ---------------------------------------------------------------------------
// THE WHOLE CHARACTER
// ---------------------------------------------------------------------------
export const Hero: React.FC<{ p: HeroPose; seed?: number }> = ({ p, seed = 1 }) => {
  const s = p.s ?? 1;
  const root: P = [p.x, p.y];
  const lean = p.lean ?? 0;
  const br = p.breathe ?? 0;
  const Rr = (q: P): P => add(root, rot([q[0] * s, q[1] * s * (1 + br * 0.012)], lean));
  const o = p.outfit ?? { top: "sweater" };
  const hoodie = o.top === "hoodie";
  const top = o.topMat ?? (hoodie ? MAT.hoodie : p.sweater ?? MAT.sweater);
  // hoodies sit boxy and oversized, with dropped shoulders
  const torsoPts: P[] = hoodie
    ? [[-168, 44], [-176, -60], [-172, -122], [-150, -164], [-100, -192], [-46, -202], [46, -202], [100, -192], [150, -164], [172, -122], [176, -60], [168, 44]]
    : [[-142, 40], [-150, -60], [-148, -118], [-126, -158], [-80, -184], [-40, -196], [40, -196], [80, -184], [126, -158], [148, -118], [150, -60], [142, 40]];
  const torso = torsoPts.map((q) => Rr(q));
  const neck = Rr(BODY.neck);
  const tilt = (p.headTilt ?? 0) + lean;
  const hc = add(Rr(BODY.headC), [0, (p.headDrop ?? 0) * s]);
  const headC = rot(hc, p.headTilt ?? 0, neck);
  const H = (q: P): P => add(headC, rot([q[0] * s, q[1] * s], tilt));
  const head = superellipse(0, 0, BODY.headR[0] * s, BODY.headR[1] * s, BODY.headE, 64).map((q) => add(headC, rot(q, tilt)));
  const neckShape = ellipse(neck[0], neck[1] - 6 * s, 44 * s, 26 * s, 20);
  const collarTop = qcurve(Rr([-66, -200]), Rr([0, -180]), Rr([66, -200]), 10);
  const collarBot = qcurve(Rr([-66, -180]), Rr([0, -160]), Rr([66, -180]), 10);
  const collar = tube(qcurve(Rr([-66, -190]), Rr([0, -170]), Rr([66, -190]), 12), () => 20 * s);
  const shOff = hoodie ? 18 : 0;
  const shL = Rr([BODY.shoulderL[0] - shOff, BODY.shoulderL[1] + shOff]), shR = Rr([BODY.shoulderR[0] + shOff, BODY.shoulderR[1] + shOff]);
  const elL = p.elbowL ?? elbowFor(shL, p.handL, BODY.upper * s, BODY.fore * s, -1, root[0]);
  const elR = p.elbowR ?? elbowFor(shR, p.handR, BODY.upper * s, BODY.fore * s, 1, root[0]);
  // hood: a heavy bunched hood behind the neck that peeks out round the head
  const hood = [[-150, -150], [-196, -214], [-176, -286], [-96, -318], [96, -318], [176, -286], [196, -214], [150, -150]].map((q) => Rr(q as P));
  const hoodFront = tube(qcurve(Rr([-112, -196]), Rr([0, -160]), Rr([112, -196]), 14), (t) => (30 + 10 * Math.sin(Math.PI * t)) * s);
  const cord = (x: number, sw: number): P[] => [Rr([x, -178]), Rr([x + sw * 4, -140 + Math.sin((p.breathe ?? 0) + x) * 2]), Rr([x + sw * 2, -104])];
  return (
    <g>
      {hoodie && <Shape pts={hood} mat={top} seed={seed + 4} ink={WEIGHT.hero} round={0.9} shade={0.2} lit={0.08} />}
      <Shape pts={torso} mat={top} seed={seed} ink={WEIGHT.hero} shade={0.1} lit={0.06} litOpacity={0.6}>
        {hoodie ? (
          <g>
            {/* kangaroo pocket */}
            <Brush pts={[Rr([-118, 40]), Rr([-96, -46]), Rr([96, -46]), Rr([118, 40])]} w={4 * s} color={top.line} taper={0.2} />
            <Brush pts={[Rr([-96, -46]), Rr([-84, 8])]} w={3 * s} color={top.lit} taper={0.5} opacity={0.5} />
            <Brush pts={[Rr([96, -46]), Rr([84, 8])]} w={3 * s} color={top.lit} taper={0.5} opacity={0.5} />
            {/* fabric folds of a heavyweight drop-shoulder hoodie */}
            <Brush pts={[Rr([-150, -110]), Rr([-120, -86]), Rr([-112, -60])]} w={3.4 * s} color={top.line} taper={0.9} />
            <Brush pts={[Rr([150, -110]), Rr([122, -84])]} w={3.4 * s} color={top.line} taper={0.9} />
            {o.wordmark && (
              <text x={0} y={0} transform={`translate(${Rr([0, -96])[0]},${Rr([0, -96])[1]}) rotate(${lean}) scale(${s})`} textAnchor="middle" fontFamily={SANS} fontWeight={700} fontSize={28} letterSpacing="0.02em" fill="#f4f1ea">{o.wordmark}</text>
            )}
          </g>
        ) : (
          <g>
            <Brush pts={[Rr([-70, -110]), Rr([-30, -96]), Rr([8, -104])]} w={3.5 * s} color={top.line} taper={0.9} opacity={0.6} />
            <Brush pts={[Rr([60, -40]), Rr([84, -20])]} w={3 * s} color={top.line} taper={0.9} opacity={0.5} />
          </g>
        )}
      </Shape>
      <Shape pts={neckShape} mat={S} seed={seed + 3} ink={WEIGHT.inner} shade={0.3} lit={0} />
      {hoodie ? (
        <g>
          <Shape pts={hoodFront} mat={top} seed={seed + 1} ink={WEIGHT.inner} shade={0.25} lit={0.12} />
          {[-28, 28].map((x, i) => (
            <g key={i}>
              <Brush pts={cord(x, i ? 1 : -1)} w={6.5 * s} color="#e9e6df" taper={0.1} />
              <Shape pts={rrectPts(Rr([x + (i ? 1 : -1) * 2, -104]), 8 * s, 20 * s)} mat={MAT.metal2} ink={2.4 * s} round={0.4} shade={0.2} lit={0.3} seed={seed + 50 + i} />
            </g>
          ))}
        </g>
      ) : (
        <Shape pts={collar} mat={top} seed={seed + 1} ink={WEIGHT.inner} shade={0.2} lit={0.1}>
          {collarTop.map((a, i) => <Line key={i} pts={[a, collarBot[i]]} w={1.6} color={top.line} wob={0.1} />)}
        </Shape>
      )}
      <ellipse cx={neck[0]} cy={neck[1] - 2 * s} rx={90 * s} ry={14 * s} fill="#140805" opacity={0.25} />
      <Shape pts={head} mat={S} seed={seed + 2} ink={WEIGHT.hero + 0.5} shade={0.045} lit={0.04} wob={0.3} />
      {o.cap && <Cap H={H} s={s} faceX={p.faceX ?? -27} mat={o.capMat ?? MAT.capBlack} seed={seed + 60} />}
      <Face c={headC} s={s} tilt={tilt} p={p} />
      <Sleeve shoulder={shL} elbow={elL} wrist={p.handL} s={s} mat={top} seed={seed + 10} />
      <Sleeve shoulder={shR} elbow={elR} wrist={p.handR} s={s} mat={top} seed={seed + 20} />
      <Hand wrist={p.handL} dir={norm(sub(p.handL, elL))} pose={p.handPoseL ?? "relaxed"} side={1} s={s} extra={p.handAngleL ?? 0} abs={p.handAbsL} seed={seed + 30} />
      <Hand wrist={p.handR} dir={norm(sub(p.handR, elR))} pose={p.handPoseR ?? "relaxed"} side={-1} s={s} extra={p.handAngleR ?? 0} abs={p.handAbsR} seed={seed + 40} />
    </g>
  );
};

const rrectPts = (c: P, w: number, h: number): P[] => [[c[0] - w / 2, c[1] - h / 2], [c[0] + w / 2, c[1] - h / 2], [c[0] + w / 2, c[1] + h / 2], [c[0] - w / 2, c[1] + h / 2]];

// Baseball cap, front view: a structured six-panel crown that SITS ON the skull (flat-ish top,
// firm front panels), a wide curved bill with stitch rows, a soft cast shadow on the forehead,
// a small embroidered emblem. Follows head tilt and face turn.
const Cap: React.FC<{ H: (q: P) => P; s: number; faceX: number; mat: Material; seed: number }> = ({ H, s, faceX, mat, seed }) => {
  const fx = faceX * 0.85;
  // crown: firm front panels, flatter top than the skull, set slightly back
  const crown: P[] = [[-182, -70], ...qcurve([-186, -150], [-120, -214], [-10 + fx * 0.3, -218], 10), ...qcurve([110 + fx * 0.3, -216], [186, -152], [182, -70], 10).slice(1)];
  // bill: projects toward camera; seen from slightly above, so it's a wide crescent
  const billTop = qcurve([-196 + fx, -74], [fx, -92], [196 + fx, -74], 14);
  const billBot = qcurve([218 + fx, -58], [fx, -12], [-218 + fx, -58], 14);
  const bill: P[] = [...billTop, ...billBot];
  const stitches = [0.3, 0.55, 0.8].map((k) => qcurve([-196 - 22 * k + fx, -74 + 16 * k], [fx, -92 + 80 * k], [196 + 22 * k + fx, -74 + 16 * k], 14));
  const seams: P[][] = [-0.62, 0.62].map((k) => qcurve([fx * 0.3 + k * 10, -214], [k * 110 + fx * 0.5, -168], [k * 150 + fx * 0.8, -76], 10));
  const front = qcurve([fx * 0.3, -216], [fx * 0.6, -150], [fx * 0.9, -82], 8);
  const emb = (q: P): P => H([q[0] + fx * 0.75, q[1] - 140]);
  return (
    <g>
      {/* cast shadow of the bill on the forehead */}
      <path d={"M" + qcurve([-170 + fx, -60], [fx, 30], [170 + fx, -60], 14).map((q) => H(q).join(",")).join("L") + "Z"} fill="#7a5a40" opacity={0.28} />
      <Shape pts={crown.map(H)} mat={mat} seed={seed} ink={WEIGHT.hero} round={0.6} shade={0.14} lit={0.12} litOpacity={0.6}>
        {seams.map((sm, i) => <Line key={i} pts={sm.map(H)} w={2.4 * s + 0.6} color={mat.lit} opacity={0.55} />)}
        <Line pts={front.map(H)} w={2.4 * s + 0.6} color={mat.lit} opacity={0.55} />
        {/* embroidered emblem: a small wave mark, thread-white */}
        <Brush pts={[emb([-30, 6]), emb([-14, -10]), emb([0, 4]), emb([14, -10]), emb([30, 6])]} w={7 * s} color="#f4f1ea" taper={0.2} />
        <Brush pts={[emb([-30, 22]), emb([-14, 6]), emb([0, 20]), emb([14, 6]), emb([30, 22])]} w={5 * s} color="#f4f1ea" taper={0.2} opacity={0.85} />
      </Shape>
      <Shape pts={ellipse(fx * 0.3 - 10, -218, 13, 7, 12).map(H)} mat={mat} ink={3 * s} shade={0} lit={0.25} seed={seed + 3} />
      <Shape pts={bill.map(H)} mat={mat} seed={seed + 1} ink={WEIGHT.hero} round={0.7} shade={0.3} lit={0.2} litOpacity={0.7}>
        {stitches.map((st, i) => <Line key={i} pts={st.map(H)} w={1.8 * s + 0.4} color={mat.lit} opacity={0.6} />)}
      </Shape>
    </g>
  );
};

// A point on the head (in head-local units), for constraints like hands on cheeks.
export const headAnchor = (p: HeroPose, local: P): P => {
  const s = p.s ?? 1;
  const root: P = [p.x, p.y];
  const lean = p.lean ?? 0;
  const Rr = (q: P): P => add(root, rot([q[0] * s, q[1] * s], lean));
  const neck = Rr(BODY.neck);
  const hc = add(Rr(BODY.headC), [0, (p.headDrop ?? 0) * s]);
  const headC = rot(hc, p.headTilt ?? 0, neck);
  return add(headC, rot([local[0] * s, local[1] * s], (p.headTilt ?? 0) + lean));
};
