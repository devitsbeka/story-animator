import React from "react";
import * as THREE from "three";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Ocean3D, SeaShot, V3, yachtMatrix } from "../../kit/ocean3d";
import { CamKey3, EASE, rigAt } from "../../kit/camrig";
import { Track, characterUrl, motionUrl, useAssets } from "../../kit/actors";
import { Caption } from "../../kit/type";
import { CAPS } from "./cues";
import { W, H } from "./harness";

// ============================================================================
// BEATS AS DATA. Each beat is a spec rendered by one component on the shared 3D stack
// (ocean, sky, yacht, island, hero). The storyboard renders a keyframe per beat; the film
// renders every frame. Camera keys are in YACHT-LOCAL metres (+z bow, +x starboard) so a beat
// stays framed on the boat wherever the boat is.
// ============================================================================

export type BeatSpec = {
  id: string; title: string; from: number; to: number; keyFrame: number;
  cam: CamKey3[]; // yacht-local
  yacht?: { lights?: number; hatch?: number; pitch?: number; roll?: number; sink?: number; seaState?: number };
  island?: { x: number; z: number; rotY?: number; scale?: number; fires?: number[] };
  moon?: V3; dawn?: number; seaState?: number;
  hero?: { local: V3; rotY: number; tracks: Track[]; look?: "camera" | V3 } | null;
  handheld?: number;
  move?: { a: [number, number]; d: [number, number]; h: [number, number]; fov: [number, number]; ease?: "move" | "arrive" | "exit" };
  shakes?: { at: number; px: number; tau: number }[];
};

const toWorld = (m: THREE.Matrix4, v: V3): V3 => { const p = new THREE.Vector3(...v).applyMatrix4(m); return [p.x, p.y, p.z]; };

export const BeatView: React.FC<{ spec: BeatSpec; f: number; captions?: boolean; fovScale?: number }> = ({ spec, f, captions = true, fovScale = 1 }) => {
  const clips = Array.from(new Set((spec.hero?.tracks ?? []).map((t) => t.clip)));
  const ok = useAssets(spec.hero ? [characterUrl("hero"), ...clips.map(motionUrl)] : []);
  const base: SeaShot = {
    time: f / 30, cam: [0, 3, -20], look: [0, 2, 0], fov: 30,
    moonDir: spec.moon ?? [0.12, 0.3, 1], seaState: spec.seaState ?? 1.6, dawn: spec.dawn ?? 0,
    yacht: { x: 0, z: 0, heading: Math.PI / 2, ...spec.yacht },
    island: spec.island,
  };
  const ym = yachtMatrix(base);
  const heading = base.yacht!.heading;
  const ypos = new THREE.Vector3().setFromMatrixPosition(ym);
  // camera frame: follows the yacht's position/heading and 85% of its heave, but not its roll (a human operator)
  const camFrame = new THREE.Matrix4().makeTranslation(base.yacht!.x, ypos.y * 0.85, base.yacht!.z).multiply(new THREE.Matrix4().makeRotationY(heading));
  let camW: V3, lookW: V3, fov: number, roll = 0;
  const u = Math.max(0, Math.min(1, (f - spec.from) / Math.max(1, spec.to - spec.from)));
  if (spec.move && spec.hero) {
    // GOLDEN RULE: the hero's chest is the look target → he is always dead centre
    const e = EASE[spec.move.ease ?? "move"](u);
    const L = (r: [number, number]) => r[0] + (r[1] - r[0]) * e;
    const ang = (L(spec.move.a) * Math.PI) / 180, d = L(spec.move.d), h = L(spec.move.h);
    const chest: V3 = [spec.hero.local[0], spec.hero.local[1] + 1.3, spec.hero.local[2]];
    const camL: V3 = [chest[0] + Math.cos(ang) * d, chest[1] + h, chest[2] + Math.sin(ang) * d];
    camW = toWorld(camFrame, camL);
    lookW = toWorld(ym, chest);
    fov = Math.exp(Math.log(spec.move.fov[0]) + (Math.log(spec.move.fov[1]) - Math.log(spec.move.fov[0])) * e);
    // handheld + impact shakes on top
    const r2 = rigAt(f, [{ f: 0, cam: camW, look: lookW, fov }], { handheld: spec.handheld ?? 0.2, shakes: spec.shakes, drift: 0.06 });
    camW = r2.cam!; lookW = r2.look!; fov = r2.fov!; roll = r2.roll ?? 0;
  } else {
    const rig = rigAt(f, spec.cam, { handheld: spec.handheld ?? 0.2 });
    camW = toWorld(camFrame, rig.cam!); lookW = toWorld(ym, rig.look!); fov = rig.fov!; roll = rig.roll ?? 0;
  }
  const shot: SeaShot = { ...base, cam: camW, look: lookW, fov: fov / fovScale, roll };
  if (spec.hero && ok) {
    const place = new THREE.Matrix4().makeTranslation(...spec.hero.local).multiply(new THREE.Matrix4().makeRotationY(spec.hero.rotY));
    shot.actors = [{
      asset: "hero", frame: f, scale: 1.8, matrix: ym.clone().multiply(place), tracks: spec.hero.tracks,
      lookAt: spec.hero.look ? { target: new THREE.Vector3(...(spec.hero.look === "camera" ? camW : toWorld(ym, spec.hero.look))), weight: 0.8 } : undefined,
    }];
  }
  return (
    <AbsoluteFill style={{ background: "#03050f" }}>
      <Ocean3D w={W} h={H} shot={shot} />
      {captions && CAPS.map((c, i) => <Caption key={i} f={f} {...c} w={W} h={H} />)}
    </AbsoluteFill>
  );
};

// ---------- the 11 beats (hero dead centre in every one) ----------
const deck: V3 = [0.2, 1.42, -4.7]; // yacht-local (+x starboard); the hero faces +x
const FACE = Math.PI / 2 - 0.2;
const idle: Track[] = [{ clip: "brace_loop", from: -300, loop: true }];
const panic = (at: number): Track[] => [{ clip: "brace_loop", from: -300, loop: true }, { clip: "panic_arms", from: at, loop: true, fade: 8 }];
const startle = (at: number): Track[] => [{ clip: "brace_loop", from: -300, loop: true }, { clip: "startle", from: at, loop: false, fade: 3 }, { clip: "brace_loop", from: at + 70, loop: true, fade: 12, offset: 1 }];
const ISL_NEAR = { x: -300, z: 900, rotY: 0.6, scale: 0.2 };
const FIRES6 = [1, 1, 1, 1, 0.9, 1];
const aground = { lights: 0, pitch: -0.1, roll: 0.16, sink: 0.25 };
const HERO = (tracks: Track[]) => ({ local: deck, rotY: FACE, tracks, look: "camera" as const });
export const BEATS: BeatSpec[] = [
  { id: "S01", title: "Alone. Engine dies.", from: 0, to: 238, keyFrame: 170, cam: [], yacht: { lights: 0 }, island: { x: -900, z: 2600, rotY: 0.6, scale: 0.35 },
    hero: HERO(panic(150)), move: { a: [8, 2], d: [9, 7], h: [0.4, 0.3], fov: [26, 24] } },
  { id: "S02", title: "Drifting to the island", from: 238, to: 452, keyFrame: 400, cam: [], yacht: { lights: 0 }, island: { ...ISL_NEAR },
    hero: HERO(idle), move: { a: [20, 60], d: [18, 70], h: [8, 45], fov: [34, 40], ease: "exit" }, handheld: 0.08 },
  { id: "S03", title: "Firelight in the trees", from: 452, to: 668, keyFrame: 640, cam: [], yacht: { lights: 0 }, island: { ...ISL_NEAR, fires: FIRES6 },
    hero: HERO(idle), move: { a: [-10, 10], d: [7, 5], h: [0.9, 0.6], fov: [30, 25] } },
  { id: "S04", title: "CRUNCH on the reef", from: 668, to: 830, keyFrame: 705, cam: [], yacht: aground, island: { ...ISL_NEAR, fires: FIRES6 },
    hero: HERO(startle(694)), move: { a: [-35, -15], d: [8, 5], h: [1.2, 0.4], fov: [30, 26], ease: "arrive" }, shakes: [{ at: 694, px: 9, tau: 1.8 }] },
  { id: "S05", title: "Step 1 · MAYDAY on CH 16", from: 830, to: 1085, keyFrame: 900, cam: [], yacht: aground, island: ISL_NEAR,
    hero: HERO(panic(840)), move: { a: [15, 5], d: [4.2, 2.8], h: [0.1, 0.0], fov: [28, 26] } },
  { id: "S06", title: "Step 2 · do NOT go ashore", from: 1085, to: 1388, keyFrame: 1180, cam: [], yacht: aground, island: { ...ISL_NEAR, fires: FIRES6 },
    hero: HERO(idle), move: { a: [170, 190], d: [5, 4], h: [0.8, 0.6], fov: [32, 30] } },
  { id: "S07", title: "Step 3 · stay with the boat", from: 1388, to: 1520, keyFrame: 1460, cam: [], yacht: aground, island: ISL_NEAR,
    hero: HERO(idle), move: { a: [40, 85], d: [6, 6], h: [1.5, 2.5], fov: [28, 28] } },
  { id: "S08", title: "1981 · the Primrose", from: 1520, to: 1928, keyFrame: 1640, cam: [], yacht: aground, island: { ...ISL_NEAR, fires: FIRES6 },
    hero: HERO(idle), move: { a: [0, 25], d: [12, 26], h: [3, 12], fov: [30, 32], ease: "move" }, handheld: 0.1 },
  { id: "S09", title: "Step 4 · kill the lights", from: 1928, to: 2070, keyFrame: 1990, cam: [], yacht: aground, island: ISL_NEAR,
    hero: HERO(idle), move: { a: [5, 0], d: [3.4, 2.4], h: [0.1, 0.0], fov: [26, 24] } },
  { id: "S10", title: "Tide lifts · get gone", from: 2070, to: 2196, keyFrame: 2170, cam: [], yacht: { lights: 0 }, island: ISL_NEAR,
    hero: HERO(panic(2160)), move: { a: [-10, -40], d: [6, 22], h: [0.8, 8], fov: [28, 32], ease: "exit" } },
  { id: "S11", title: "Never be there at all", from: 2196, to: 2416, keyFrame: 2370, cam: [], dawn: 0.75, moon: [0.1, 0.06, 1], yacht: { lights: 0 }, island: ISL_NEAR,
    hero: HERO(idle), move: { a: [10, 25], d: [24, 48], h: [6, 18], fov: [30, 30] }, handheld: 0.06 },
];

/** Storyboard frame: one beat's keyframe (frame index selects the beat). */
export const BoardFrame: React.FC = () => {
  const i = useCurrentFrame();
  const b = BEATS[Math.min(BEATS.length - 1, i)];
  return <BeatView spec={b} f={b.keyFrame} />;
};
