// Geometry for the kit: points, smooth paths, hand-drawn wobble, primitive shapes.
// Everything is deterministic: randomness always comes from a string/number seed.

export type P = [number, number];

// ---------- seeded randomness ----------
const hashStr = (s: string) => {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
};
export const rng = (seed: string | number) => {
  let a = typeof seed === "number" ? seed >>> 0 : hashStr(seed);
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
};
export const rr = (r: () => number, a: number, b: number) => a + (b - a) * r();

// smooth 1D value noise, for wobble that varies along a line
export const noise1 = (x: number, seed = 0) => {
  const i = Math.floor(x), f = x - i;
  const h = (n: number) => {
    const s = Math.sin((n + seed * 131.7) * 127.1) * 43758.5453;
    return s - Math.floor(s);
  };
  const u = f * f * (3 - 2 * f);
  return (h(i) * (1 - u) + h(i + 1) * u) * 2 - 1;
};

// ---------- vectors ----------
export const add = (a: P, b: P): P => [a[0] + b[0], a[1] + b[1]];
export const sub = (a: P, b: P): P => [a[0] - b[0], a[1] - b[1]];
export const mulv = (a: P, k: number): P => [a[0] * k, a[1] * k];
export const len = (a: P) => Math.hypot(a[0], a[1]);
export const norm = (a: P): P => { const l = len(a) || 1; return [a[0] / l, a[1] / l]; };
export const perp = (a: P): P => [-a[1], a[0]];
export const lerpP = (a: P, b: P, t: number): P => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
export const rot = (p: P, deg: number, c: P = [0, 0]): P => {
  const r = (deg * Math.PI) / 180, s = Math.sin(r), k = Math.cos(r);
  const x = p[0] - c[0], y = p[1] - c[1];
  return [c[0] + x * k - y * s, c[1] + x * s + y * k];
};
export const centroid = (pts: P[]): P => {
  let x = 0, y = 0;
  pts.forEach((p) => { x += p[0]; y += p[1]; });
  return [x / pts.length, y / pts.length];
};
export const bbox = (pts: P[]) => {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  pts.forEach(([x, y]) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); });
  return { x0, y0, x1, y1, w: x1 - x0, h: y1 - y0, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 };
};

// ---------- paths ----------
const f = (n: number) => +n.toFixed(2);

// Catmull-Rom through points → cubic Béziers. tension 0 = sharp corners, 1 = round.
export const smooth = (pts: P[], closed = true, tension = 1): string => {
  const n = pts.length;
  if (n < 2) return "";
  const at = (i: number) => (closed ? pts[(i + n) % n] : pts[Math.max(0, Math.min(n - 1, i))]);
  let d = `M${f(pts[0][0])},${f(pts[0][1])}`;
  const segs = closed ? n : n - 1;
  for (let i = 0; i < segs; i++) {
    const p0 = at(i - 1), p1 = at(i), p2 = at(i + 1), p3 = at(i + 2);
    const k = tension / 6;
    const c1: P = [p1[0] + (p2[0] - p0[0]) * k, p1[1] + (p2[1] - p0[1]) * k];
    const c2: P = [p2[0] - (p3[0] - p1[0]) * k, p2[1] - (p3[1] - p1[1]) * k];
    d += `C${f(c1[0])},${f(c1[1])} ${f(c2[0])},${f(c2[1])} ${f(p2[0])},${f(p2[1])}`;
  }
  return closed ? d + "Z" : d;
};
export const poly = (pts: P[], closed = true) => "M" + pts.map((p) => `${f(p[0])},${f(p[1])}`).join("L") + (closed ? "Z" : "");

// Hand-drawn feel: nudge points along their normals by smooth noise. amp in px.
export const wobble = (pts: P[], seed: number, amp = 0.8, freq = 0.35): P[] =>
  pts.map((p, i) => [p[0] + noise1(i * freq, seed) * amp, p[1] + noise1(i * freq + 50, seed) * amp]);

// Resample a polyline/polygon to roughly even spacing (so wobble is even).
export const resample = (pts: P[], step: number, closed = true): P[] => {
  const out: P[] = [];
  const n = pts.length;
  const segs = closed ? n : n - 1;
  for (let i = 0; i < segs; i++) {
    const a = pts[i], b = pts[(i + 1) % n];
    const L = len(sub(b, a));
    const k = Math.max(1, Math.round(L / step));
    for (let j = 0; j < k; j++) out.push(lerpP(a, b, j / k));
  }
  if (!closed) out.push(pts[n - 1]);
  return out;
};

// ---------- primitive shapes (as point lists, so everything can wobble / be shaded alike) ----------
export const ellipse = (cx: number, cy: number, rx: number, ry: number, n = 48, start = 0): P[] =>
  Array.from({ length: n }, (_, i) => {
    const a = start + (i / n) * Math.PI * 2;
    return [cx + Math.cos(a) * rx, cy + Math.sin(a) * ry] as P;
  });

// superellipse: e = 2 ellipse, larger = boxier. Good for heads, cushions, stones.
export const superellipse = (cx: number, cy: number, rx: number, ry: number, e = 2.4, n = 56): P[] =>
  Array.from({ length: n }, (_, i) => {
    const a = (i / n) * Math.PI * 2, c = Math.cos(a), s = Math.sin(a);
    return [cx + Math.sign(c) * Math.pow(Math.abs(c), 2 / e) * rx, cy + Math.sign(s) * Math.pow(Math.abs(s), 2 / e) * ry] as P;
  });

// rounded rectangle as points (corner radius r, k points per corner)
export const rrect = (x: number, y: number, w: number, h: number, r = 6, k = 5): P[] => {
  r = Math.min(r, w / 2, h / 2);
  const corners: [number, number, number][] = [[x + w - r, y + r, -90], [x + w - r, y + h - r, 0], [x + r, y + h - r, 90], [x + r, y + r, 180]];
  const out: P[] = [];
  corners.forEach(([cx, cy, a0]) => {
    for (let i = 0; i <= k; i++) {
      const a = ((a0 + (i / k) * 90) * Math.PI) / 180;
      out.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]);
    }
  });
  return out;
};

// quad (4 corners, e.g. a desk top in perspective) with slightly rounded corners
export const quad = (a: P, b: P, c: P, d: P, r = 4): P[] => {
  const pts = [a, b, c, d];
  const out: P[] = [];
  pts.forEach((p, i) => {
    const prev = pts[(i + 3) % 4], next = pts[(i + 1) % 4];
    out.push(add(p, mulv(norm(sub(prev, p)), r)));
    out.push(p);
    out.push(add(p, mulv(norm(sub(next, p)), r)));
  });
  return out;
};

// A tube along a polyline with a width profile (limbs, sleeves, lamp arms, cables).
export const tube = (spine: P[], widths: number[] | ((t: number) => number)): P[] => {
  const n = spine.length;
  const w = (i: number) => (typeof widths === "function" ? widths(i / (n - 1)) : widths[Math.min(i, widths.length - 1)]);
  const left: P[] = [], right: P[] = [];
  for (let i = 0; i < n; i++) {
    const a = spine[Math.max(0, i - 1)], b = spine[Math.min(n - 1, i + 1)];
    const nrm = perp(norm(sub(b, a)));
    left.push(add(spine[i], mulv(nrm, w(i) / 2)));
    right.push(add(spine[i], mulv(nrm, -w(i) / 2)));
  }
  // round caps
  const capPts = (c: P, dir: P, r: number): P[] =>
    Array.from({ length: 7 }, (_, k) => {
      const ang = Math.atan2(dir[1], dir[0]) - Math.PI / 2 + (k / 6) * Math.PI;
      return [c[0] + Math.cos(ang) * r, c[1] + Math.sin(ang) * r] as P;
    });
  const endDir = norm(sub(spine[n - 1], spine[n - 2]));
  const startDir = norm(sub(spine[0], spine[1]));
  return [...left, ...capPts(spine[n - 1], endDir, w(n - 1) / 2).slice(1, -1), ...right.reverse(), ...capPts(spine[0], startDir, w(0) / 2).slice(1, -1)];
};

// Quadratic Bézier sampled as points (for bendy spines)
export const qcurve = (a: P, c: P, b: P, n = 12): P[] =>
  Array.from({ length: n + 1 }, (_, i) => {
    const t = i / n, u = 1 - t;
    return [u * u * a[0] + 2 * u * t * c[0] + t * t * b[0], u * u * a[1] + 2 * u * t * c[1] + t * t * b[1]] as P;
  });

// 2-bone IK: given root, target, and bone lengths, return the joint. bend = +1/-1 picks the side.
export const ik2 = (root: P, target: P, l1: number, l2: number, bend: 1 | -1 = 1): P => {
  const d = sub(target, root);
  const dist = Math.min(len(d), l1 + l2 - 0.001);
  const a = Math.acos(Math.max(-1, Math.min(1, (l1 * l1 + dist * dist - l2 * l2) / (2 * l1 * dist))));
  const base = Math.atan2(d[1], d[0]) + bend * a;
  return [root[0] + Math.cos(base) * l1, root[1] + Math.sin(base) * l1];
};
