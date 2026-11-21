import React from "react";

// ============================================================================
// ENGINE: 2D rig (bone hierarchy), deterministic physics, 2.5D camera.
// Everything is a pure function of the frame number, so any frame renders the
// same on any machine and Remotion can render frames in parallel.
// ============================================================================

// ---------- 2D affine matrices ----------

export type M = [number, number, number, number, number, number]; // a b c d e f (SVG order)
export const I: M = [1, 0, 0, 1, 0, 0];
export const mul = (m: M, n: M): M => [
  m[0] * n[0] + m[2] * n[1],
  m[1] * n[0] + m[3] * n[1],
  m[0] * n[2] + m[2] * n[3],
  m[1] * n[2] + m[3] * n[3],
  m[0] * n[4] + m[2] * n[5] + m[4],
  m[1] * n[4] + m[3] * n[5] + m[5],
];
export const T = (x: number, y: number): M => [1, 0, 0, 1, x, y];
export const R = (deg: number): M => {
  const r = (deg * Math.PI) / 180, c = Math.cos(r), s = Math.sin(r);
  return [c, s, -s, c, 0, 0];
};
export const S = (x: number, y = x): M => [x, 0, 0, y, 0, 0];
export const apply = (m: M, x: number, y: number): [number, number] => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
export const svgM = (m: M) => `matrix(${m.map((v) => +v.toFixed(5)).join(" ")})`;

// ---------- rig ----------
// Parts are traced in their rest pose in world coordinates, so a bone only needs a
// parent and a pivot. A pose sets each bone's rotation / offset / scale about its pivot.

export type Bone = { parent: string | null; pivot: [number, number] };
export type BoneXf = { rot?: number; dx?: number; dy?: number; sx?: number; sy?: number };
export type Pose = Record<string, BoneXf>;

export const solveRig = (bones: Record<string, Bone>, pose: Pose): Record<string, M> => {
  const out: Record<string, M> = {};
  const solve = (id: string): M => {
    if (out[id]) return out[id];
    const b = bones[id];
    const p = pose[id] ?? {};
    const [px, py] = b.pivot;
    // local = T(pivot + offset) · R · S · T(-pivot)
    const local = mul(mul(mul(T(px + (p.dx ?? 0), py + (p.dy ?? 0)), R(p.rot ?? 0)), S(p.sx ?? 1, p.sy ?? 1)), T(-px, -py));
    out[id] = b.parent ? mul(solve(b.parent), local) : local;
    return out[id];
  };
  Object.keys(bones).forEach(solve);
  return out;
};

// Blend two poses (for keyframed acting). Missing values fall back to the rest pose.
export const mixPose = (a: Pose, b: Pose, t: number): Pose => {
  const ids = new Set([...Object.keys(a), ...Object.keys(b)]);
  const r: Pose = {};
  const L = (x = 0, y = 0) => x + (y - x) * t;
  ids.forEach((id) => {
    const p = a[id] ?? {}, q = b[id] ?? {};
    r[id] = { rot: L(p.rot, q.rot), dx: L(p.dx, q.dx), dy: L(p.dy, q.dy), sx: L(p.sx ?? 1, q.sx ?? 1), sy: L(p.sy ?? 1, q.sy ?? 1) };
  });
  return r;
};

// ---------- deterministic physics ----------
// simulate() steps a state from frame 0 to the requested frame at a fixed substep and
// caches every frame, so frame N always gives the same answer, in any render order.

const simCache = new Map<string, unknown[]>();
export function simulate<St>(key: string, frame: number, init: () => St, step: (s: St, t: number, dt: number) => St, fps = 30, substeps = 8): St {
  let arr = simCache.get(key) as St[] | undefined;
  if (!arr) { arr = [init()]; simCache.set(key, arr); }
  const dt = 1 / fps / substeps;
  while (arr.length <= frame) {
    let s = arr[arr.length - 1];
    const f0 = arr.length - 1;
    for (let k = 0; k < substeps; k++) s = step(s, (f0 + k / substeps) / fps, dt);
    arr.push(s);
  }
  return arr[Math.max(0, frame)];
}

// Damped spring toward a moving target: x'' = k(target - x) - c x'.
// freq in Hz, damping ratio zeta (1 = critical, <1 = overshoot / wobble).
export type Spring = { x: number; v: number };
export const springStep = (s: Spring, target: number, dt: number, freq = 2, zeta = 0.5): Spring => {
  const w = 2 * Math.PI * freq;
  const a = w * w * (target - s.x) - 2 * zeta * w * s.v;
  const v = s.v + a * dt;
  return { x: s.x + v * dt, v };
};

// A rigid circle body (paper ball, coin, fruit...) with gravity, a floor line, restitution,
// rolling friction and spin. Units: world px and seconds.
export type Body = { x: number; y: number; vx: number; vy: number; a: number; w: number; r: number; asleep?: boolean };
export const bodyStep = (b: Body, dt: number, floorY: (x: number) => number, opts: { g?: number; e?: number; mu?: number; air?: number } = {}): Body => {
  if (b.asleep) return b;
  const { g = 2600, e = 0.38, mu = 0.12, air = 0.02 } = opts;
  let { x, y, vx, vy, a, w } = b;
  vy += g * dt;
  vx *= 1 - air * dt; vy *= 1 - air * dt;
  x += vx * dt; y += vy * dt;
  const fy = floorY(x) - b.r;
  if (y > fy) {
    y = fy;
    if (vy > 0) vy = -vy * e;
    if (Math.abs(vy) < 40) vy = 0;
    // contact: Coulomb-style deceleration, and the body rolls without slipping (spin = v / r)
    const decel = mu * g * dt;
    vx = Math.abs(vx) <= decel ? 0 : vx - Math.sign(vx) * decel;
    w = (vx / b.r) * (180 / Math.PI);
  }
  a += w * dt;
  const asleep = y >= fy - 0.01 && Math.abs(vx) < 2 && vy === 0;
  return { ...b, x, y, vx: asleep ? 0 : vx, vy, a, w: asleep ? 0 : w, asleep };
};

// ---------- 2.5D camera ----------
// A pinhole camera over layered depth planes. The subject plane is z = 0. Positive z is
// farther away (slower parallax), negative z is nearer (faster). At rest (dolly 0, zoom 1)
// every plane maps 1:1 to the reference image.

export type Cam = { x: number; y: number; zoom: number; dolly: number; roll: number };
export const FOCAL = 1200;
export const camMatrix = (cam: Cam, z: number, vw: number, vh: number, worldCx = 512, worldCy = 512): M => {
  // Each plane is pre-scaled by (FOCAL + z) / FOCAL so that at rest all planes line up with the
  // reference exactly; dollying in then makes near planes grow faster than far ones.
  const dist = FOCAL - cam.dolly + z;
  const s = (cam.zoom * (FOCAL + z)) / Math.max(50, dist);
  // plane-space point that sits at the screen centre (parallax: farther planes shift less)
  const k = FOCAL / Math.max(50, FOCAL + z);
  const cx = worldCx + (cam.x - worldCx) * k;
  const cy = worldCy + (cam.y - worldCy) * k;
  return mul(mul(mul(T(vw / 2, vh / 2), R(cam.roll)), S(s)), T(-cx, -cy));
};

export const Plane: React.FC<{ cam: Cam; z: number; vw: number; vh: number; wc?: [number, number]; children: React.ReactNode }> = ({ cam, z, vw, vh, wc = [512, 512], children }) => (
  <g transform={svgM(camMatrix(cam, z, vw, vh, wc[0], wc[1]))}>{children}</g>
);

// Camera keyframes [frame, x, y, zoom, dolly, roll], eased in/out.
export type CamKey = [number, number, number, number, number, number];
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
export const camAt = (f: number, keys: CamKey[]): Cam => {
  let i = 0;
  while (i < keys.length - 2 && f >= keys[i + 1][0]) i++;
  const a = keys[i], b = keys[Math.min(i + 1, keys.length - 1)];
  const t = b[0] === a[0] ? 1 : ease(Math.max(0, Math.min(1, (f - a[0]) / (b[0] - a[0]))));
  const L = (j: number) => a[j] + (b[j] - a[j]) * t;
  return { x: L(1), y: L(2), zoom: L(3), dolly: L(4), roll: L(5) };
};
