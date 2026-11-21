import { SeaShot, V3 } from "./ocean3d";

// ============================================================================
// CAMERA RIG for 3D shots. Rules from motion-tools-and-skills (MIT/Apache):
//  - eases: arrive (0.16,1,0.3,1), move (0.65,0,0.35,1), exit (0.7,0,0.84,0),
//    anticipate (0.5,-0.32,0.25,1), overshoot (0.34,1.45,0.64,1)  [video-shotcraft Polish.tsx]
//  - zoom (fov) interpolated in log space; never zoom in then straight back out  [howseen §2]
//  - crash zoom: 6-frame ease-in, hard stop + shake 14px·e^(−t/1.8f)  [shotcraft crash-zoom-punch]
//  - handheld: amp·(sin(f·.31)+.6·sin(f·.83+1.7))  [shotcraft helpers/shake.ts]
//  - never frozen: drift continues through holds  [howseen §0]
// ============================================================================

const bez = (x1: number, y1: number, x2: number, y2: number) => (x: number) => {
  // solve x(t) = x by Newton, return y(t)
  let t = x;
  for (let i = 0; i < 8; i++) {
    const cx = 3 * x1 * t * (1 - t) ** 2 + 3 * x2 * t * t * (1 - t) + t ** 3 - x;
    const dx = 3 * x1 * (1 - t) ** 2 + 6 * (x2 - x1) * t * (1 - t) + 3 * (1 - x2) * t * t;
    if (Math.abs(dx) < 1e-6) break;
    t = Math.min(1, Math.max(0, t - cx / dx));
  }
  return 3 * y1 * t * (1 - t) ** 2 + 3 * y2 * t * t * (1 - t) + t ** 3;
};
export const EASE = {
  arrive: bez(0.16, 1, 0.3, 1),
  move: bez(0.65, 0, 0.35, 1),
  exit: bez(0.7, 0, 0.84, 0),
  anticipate: bez(0.5, -0.32, 0.25, 1),
  overshoot: bez(0.34, 1.45, 0.64, 1),
  crashIn: (t: number) => t * t * t,
  linear: (t: number) => t,
};
export type EaseName = keyof typeof EASE;

export type CamKey3 = { f: number; cam: V3; look: V3; fov: number; roll?: number; ease?: EaseName };
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const lerp3 = (a: V3, b: V3, t: number): V3 => [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];

export type Shake = { at: number; px: number; tau: number }; // impact shakes
export const rigAt = (f: number, keys: CamKey3[], opt: { handheld?: number; shakes?: Shake[]; drift?: number } = {}): Pick<SeaShot, "cam" | "look" | "fov" | "roll"> => {
  let i = 0;
  while (i < keys.length - 2 && f >= keys[i + 1].f) i++;
  const a = keys[i], b = keys[Math.min(i + 1, keys.length - 1)];
  const u = b.f === a.f ? 1 : Math.max(0, Math.min(1, (f - a.f) / (b.f - a.f)));
  const e = EASE[b.ease ?? "move"](u);
  let cam = lerp3(a.cam, b.cam, e), look = lerp3(a.look, b.look, e);
  const fov = Math.exp(lerp(Math.log(a.fov), Math.log(b.fov), e));
  let roll = lerp(a.roll ?? 0, b.roll ?? 0, e);
  // continuous drift so holds never freeze
  const dr = opt.drift ?? 0.25;
  cam = [cam[0] + Math.sin(f * 0.011) * dr, cam[1] + Math.sin(f * 0.017 + 1) * dr * 0.5, cam[2] + Math.sin(f * 0.009 + 2) * dr];
  // handheld (angular, in degrees of look offset → metres at the look distance)
  const hh = opt.handheld ?? 0;
  const dist = Math.hypot(look[0] - cam[0], look[1] - cam[1], look[2] - cam[2]);
  const k = dist * 0.0175; // ~1° → metres at the subject
  let jx = hh * (Math.sin(f * 0.31) + 0.6 * Math.sin(f * 0.83 + 1.7));
  let jy = hh * (Math.sin(f * 0.47 + 0.9) + 0.5 * Math.sin(f * 1.13 + 3.1));
  // impact shakes: amplitude in screen px (1080 wide ≈ fov) → degrees
  (opt.shakes ?? []).forEach((s) => {
    const t = f - s.at;
    if (t < 0 || t > s.tau * 6) return;
    const amp = s.px * Math.exp(-t / s.tau) * (fov / 1080);
    jx += amp * Math.sin(t * 2.3);
    jy += amp * Math.cos(t * 2.9);
    roll += amp * 0.25 * Math.sin(t * 1.7);
  });
  look = [look[0] + jx * k, look[1] + jy * k, look[2]];
  return { cam, look, fov, roll };
};
