// Helpers that turn per-frame functions from the code pipeline into compact keyframe lists.
export type ScalarKeys = [number, number][];
const r = (v: number, d = 5) => Math.round(v * 10 ** d) / 10 ** d;

/** Piecewise-constant signal -> step keys (two keys on consecutive frames at each change). */
export const stepKeys = (fn: (f: number) => number, from: number, to: number, d = 5): ScalarKeys => {
  const out: ScalarKeys = [[from, r(fn(from), d)]];
  for (let f = from + 1; f < to; f++) {
    const prev = r(fn(f - 1), d), cur = r(fn(f), d);
    if (cur !== prev) { if (out[out.length - 1][0] !== f - 1) out.push([f - 1, prev]); out.push([f, cur]); }
  }
  if (out[out.length - 1][0] !== to - 1) out.push([to - 1, r(fn(to - 1), d)]);
  return out;
};

/** Continuous signal -> per-frame keys, dropping points that linear interpolation reproduces within eps. */
export const sampledKeys = (fn: (f: number) => number, from: number, to: number, eps = 1e-4, d = 5): ScalarKeys => {
  const all: ScalarKeys = [];
  for (let f = from; f < to; f++) all.push([f, r(fn(f), d)]);
  const out: ScalarKeys = [all[0]];
  for (let i = 1; i < all.length - 1; i++) {
    const a = out[out.length - 1], b = all[i + 1];
    const t = (all[i][0] - a[0]) / (b[0] - a[0]);
    if (Math.abs(a[1] + (b[1] - a[1]) * t - all[i][1]) > eps) out.push(all[i]);
  }
  if (all.length > 1) out.push(all[all.length - 1]);
  return out;
};

/** A key list that is constant collapses to a plain number. */
export const collapse = (k: ScalarKeys): number | ScalarKeys => (k.every(([, v]) => v === k[0][1]) ? k[0][1] : k);
export const round3 = (v: [number, number, number], d = 5): [number, number, number] => [r(v[0], d), r(v[1], d), r(v[2], d)];
export const rnd = r;
