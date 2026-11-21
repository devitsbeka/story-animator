import React from "react";
import * as THREE from "three";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Ocean3D, SeaShot, V3, yachtMatrix } from "../../kit/ocean3d";
import { CamKey3, rigAt } from "../../kit/camrig";
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
};

const toWorld = (m: THREE.Matrix4, v: V3): V3 => { const p = new THREE.Vector3(...v).applyMatrix4(m); return [p.x, p.y, p.z]; };

export const BeatView: React.FC<{ spec: BeatSpec; f: number }> = ({ spec, f }) => {
  const clips = Array.from(new Set((spec.hero?.tracks ?? []).map((t) => t.clip)));
  const ok = useAssets(spec.hero ? [characterUrl("hero"), ...clips.map(motionUrl)] : []);
  const base: SeaShot = {
    time: f / 30, cam: [0, 3, -20], look: [0, 2, 0], fov: 30,
    moonDir: spec.moon ?? [0.12, 0.3, 1], seaState: spec.seaState ?? 1.6, dawn: spec.dawn ?? 0,
    yacht: { x: 0, z: 0, heading: Math.PI / 2, ...spec.yacht },
    island: spec.island,
  };
  const ym = yachtMatrix(base);
  const rig = rigAt(f, spec.cam, { handheld: spec.handheld ?? 0.2 });
  // camera follows the boat's heave but not its full roll (a human operator)
  // beat specs use +x = the hero's side of the boat (starboard, facing camera)
  const flip = (v: V3): V3 => [-v[0], v[1], v[2]];
  const camW = toWorld(new THREE.Matrix4().makeTranslation(0, new THREE.Vector3().setFromMatrixPosition(ym).y * 0.6, 0).multiply(new THREE.Matrix4().makeRotationY(Math.PI / 2)), flip(rig.cam!));
  const lookW = toWorld(ym, flip(rig.look!));
  const shot: SeaShot = { ...base, cam: camW, look: lookW, fov: rig.fov, roll: rig.roll };
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
      {CAPS.map((c, i) => <Caption key={i} f={f} {...c} w={W} h={H} />)}
    </AbsoluteFill>
  );
};

// ---------- the 11 beats ----------
const deck: V3 = [0.2, 1.42, -4.7]; // yacht-local (+x starboard)
const idle: Track[] = [{ clip: "brace_loop", from: -300, loop: true }];
const panic: Track[] = [{ clip: "brace_loop", from: -300, loop: true }, { clip: "panic_arms", from: -60, loop: true }];
const ISL_NEAR = { x: -300, z: 900, rotY: 0.6, scale: 0.2 };
export const BEATS: BeatSpec[] = [
  { id: "S01", title: "Alone. Engine dies.", from: 0, to: 238, keyFrame: 160,
    cam: [{ f: 0, cam: [-25, 2.8, -4], look: [0, 2.4, -4.4], fov: 16 }], yacht: { lights: 0 }, island: { x: -900, z: 2600, rotY: 0.6, scale: 0.35 },
    hero: { local: deck, rotY: Math.PI / 2 - 0.25, tracks: panic, look: "camera" } },
  { id: "S02", title: "Drifting to the island", from: 238, to: 452, keyFrame: 400,
    cam: [{ f: 0, cam: [-60, 140, -40], look: [0, 0, 20], fov: 40 }], yacht: { lights: 0 }, island: ISL_NEAR, hero: null, handheld: 0.05 },
  { id: "S03", title: "Firelight in the trees", from: 452, to: 668, keyFrame: 600,
    cam: [{ f: 0, cam: [-8, 3.5, -10], look: [800, 30, 600], fov: 22 }], yacht: { lights: 0 }, island: { ...ISL_NEAR, fires: [1, 1, 1, 1, 0.8, 0.9] }, hero: null },
  { id: "S04", title: "CRUNCH on the reef", from: 668, to: 830, keyFrame: 700,
    cam: [{ f: 0, cam: [-18, 1.2, 6], look: [0, 1.4, 2], fov: 26, roll: -4 }], yacht: { lights: 0, pitch: -0.12, roll: 0.18, sink: 0.25 }, island: { ...ISL_NEAR, fires: [1, 1, 1, 1, 1, 1] },
    hero: { local: deck, rotY: Math.PI / 2, tracks: [{ clip: "startle", from: -10, loop: false }] } },
  { id: "S05", title: "Step 1 · MAYDAY on CH 16", from: 830, to: 1085, keyFrame: 880,
    cam: [{ f: 0, cam: [-4.5, 3.2, -5.2], look: [0.2, 3.0, -4.7], fov: 30 }], yacht: { lights: 0, roll: 0.12, sink: 0.25 }, island: ISL_NEAR,
    hero: { local: deck, rotY: Math.PI / 2 + 0.3, tracks: idle, look: "camera" } },
  { id: "S06", title: "Step 2 · do NOT go ashore", from: 1085, to: 1388, keyFrame: 1150,
    cam: [{ f: 0, cam: [-3, 3.4, -9], look: [400, 10, 900], fov: 34 }], yacht: { lights: 0, roll: 0.12, sink: 0.25 }, island: { ...ISL_NEAR, fires: [0.8, 0.8, 0.8, 0.8, 0.8, 0.8] },
    hero: { local: deck, rotY: -0.2, tracks: idle } },
  { id: "S07", title: "Step 3 · stay with the boat", from: 1388, to: 1520, keyFrame: 1430,
    cam: [{ f: 0, cam: [-14, 6, -10], look: [0, 2.5, -2], fov: 26 }], yacht: { lights: 0, roll: 0.12, sink: 0.25 }, island: ISL_NEAR,
    hero: { local: deck, rotY: Math.PI / 2, tracks: idle, look: "camera" } },
  { id: "S08", title: "1981 · the Primrose", from: 1520, to: 1928, keyFrame: 1600,
    cam: [{ f: 0, cam: [-40, 8, -60], look: [0, 4, 0], fov: 30 }], yacht: { lights: 0, roll: 0.12, sink: 0.25 }, island: { ...ISL_NEAR, fires: [1, 1, 1, 1, 1, 1] }, hero: null },
  { id: "S09", title: "Step 4 · kill the lights", from: 1928, to: 2070, keyFrame: 1975,
    cam: [{ f: 0, cam: [-4.2, 3.0, -5.0], look: [0.2, 3.1, -4.7], fov: 28 }], yacht: { lights: 0, roll: 0.12, sink: 0.25 }, island: ISL_NEAR,
    hero: { local: deck, rotY: Math.PI / 2, tracks: idle, look: "camera" } },
  { id: "S10", title: "Tide lifts · get gone", from: 2070, to: 2196, keyFrame: 2160,
    cam: [{ f: 0, cam: [-30, 9, -30], look: [0, 1.5, 4], fov: 30 }], yacht: { lights: 0 }, island: ISL_NEAR,
    hero: { local: deck, rotY: Math.PI / 2, tracks: panic } },
  { id: "S11", title: "Never be there at all", from: 2196, to: 2416, keyFrame: 2360,
    cam: [{ f: 0, cam: [-2000, 40, -2600], look: [-300, 20, 900], fov: 18 }], dawn: 0.75, moon: [0.1, 0.06, 1], yacht: { lights: 0 }, island: ISL_NEAR, hero: null, handheld: 0.05 },
];

/** Storyboard frame: one beat's keyframe (frame index selects the beat). */
export const BoardFrame: React.FC = () => {
  const i = useCurrentFrame();
  const b = BEATS[Math.min(BEATS.length - 1, i)];
  return <BeatView spec={b} f={b.keyFrame} />;
};
