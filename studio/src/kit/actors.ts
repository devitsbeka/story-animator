import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import * as SkeletonUtils from "three/examples/jsm/utils/SkeletonUtils.js";
import { useEffect, useState } from "react";
import { continueRender, delayRender, staticFile } from "remotion";

// ============================================================================
// ACTORS: the reusable character system.
//  - assets/characters/<name>/<name>.glb  : the rigged character (made once, reused every episode)
//  - assets/motions/<clip>.glb             : motion clips on the same rig (a growing library)
// Episodes only say WHICH clip plays WHEN; everything is a pure function of the frame:
// clips are sampled with mixer.setTime(), blends are computed from frame numbers, and the
// code layer (IK reach, head aim) is applied on top, so contacts are frame-exact.
// ============================================================================

export type Track = { clip: string; from: number; speed?: number; loop?: boolean; fade?: number; offset?: number };
export type ActorState = {
  asset: string;
  frame: number; fps?: number;
  tracks: Track[]; // later tracks blend over earlier ones (crossfade over `fade` frames)
  matrix: THREE.Matrix4; // world placement
  scale?: number; // world height / model height
  reach?: { hand: "L" | "R"; target: THREE.Vector3; weight: number }[]; // IK overrides (world space)
  lookAt?: { target: THREE.Vector3; weight: number };
};

type Loaded = { scene: THREE.Object3D; clips: THREE.AnimationClip[] };
const cache = new Map<string, Promise<Loaded>>();
const ready = new Map<string, Loaded>();
const load = (url: string) => {
  if (!cache.has(url)) {
    cache.set(url, new Promise<Loaded>((res, rej) => {
      new GLTFLoader().load(url, (g) => { const l = { scene: g.scene, clips: g.animations }; ready.set(url, l); res(l); }, undefined, rej);
    }));
  }
  return cache.get(url)!;
};
export const characterUrl = (name: string) => staticFile(`assets/characters/${name}/${name}.glb`);
export const motionUrl = (clip: string) => staticFile(`assets/motions/${clip}.glb`);

/** Hook: blocks the frame until every listed asset is loaded, then re-renders with them ready. */
export const useAssets = (urls: string[]) => {
  const key = urls.join("|");
  const allReady = () => urls.every((u) => ready.has(u));
  const [ok, setOk] = useState(allReady);
  const [handle] = useState(() => (allReady() ? null : delayRender(`loading ${key}`, { timeoutInMilliseconds: 120000 })));
  useEffect(() => {
    if (ok) { if (handle !== null) continueRender(handle); return; }
    let live = true;
    Promise.all(urls.map(load)).then(() => { if (live) setOk(true); }).catch((e) => { console.error("asset load failed", e); if (handle !== null) continueRender(handle); });
    return () => { live = false; };
  }, [key, ok]); // eslint-disable-line react-hooks/exhaustive-deps
  return ok;
};

// ---------- a live instance of a character in a scene ----------
type Inst = { root: THREE.Object3D; mixer: THREE.AnimationMixer; actions: Map<string, THREE.AnimationAction>; bones: Record<string, THREE.Bone | undefined>; height: number };
const BONE_RX: Record<string, RegExp> = {
  armL: /left.?(up.?)?arm$|upperarm.?l|l.?upperarm/i, foreL: /left.?fore.?arm|lowerarm.?l|l.?forearm/i, handL: /left.?hand$|hand.?l$|l.?hand$/i,
  armR: /right.?(up.?)?arm$|upperarm.?r|r.?upperarm/i, foreR: /right.?fore.?arm|lowerarm.?r|r.?forearm/i, handR: /right.?hand$|hand.?r$|r.?hand$/i,
  head: /head$/i, neck: /neck/i, spine: /spine.?2$|chest/i,
};

export const instantiate = (asset: string): Inst | null => {
  const base = ready.get(characterUrl(asset));
  if (!base) return null;
  const root = SkeletonUtils.clone(base.scene);
  root.traverse((o) => {
    const m = o as THREE.Mesh;
    if (!m.isMesh) return;
    m.castShadow = true; m.receiveShadow = true; m.frustumCulled = false;
    // generated PBR comes out glossy: fabric and skin should be matte
    (Array.isArray(m.material) ? m.material : [m.material]).forEach((mat) => {
      const sm = mat as THREE.MeshStandardMaterial;
      if (sm.isMeshStandardMaterial) { sm.metalness = 0; sm.roughness = Math.max(sm.roughness, 0.78); sm.metalnessMap = null; sm.roughnessMap = null; sm.envMapIntensity = 0.5; sm.needsUpdate = true; }
    });
  });
  const bones: Inst["bones"] = {};
  root.traverse((o) => {
    if ((o as THREE.Bone).isBone) Object.entries(BONE_RX).forEach(([k, rx]) => { if (!bones[k] && rx.test(o.name)) bones[k] = o as THREE.Bone; });
  });
  // height from the skeleton (skinned bounding boxes are unreliable before the first pose)
  root.updateMatrixWorld(true);
  let top = -Infinity, bottom = Infinity;
  root.traverse((o) => {
    if (!(o as THREE.Bone).isBone) return;
    const y = o.getWorldPosition(new THREE.Vector3()).y;
    if (/head_?end|headtop/i.test(o.name)) top = Math.max(top, y);
    if (/toe|foot/i.test(o.name)) bottom = Math.min(bottom, y);
  });
  const height = isFinite(top) && isFinite(bottom) && top > bottom ? (top - bottom) * 1.04 : 1.8;
  return { root, mixer: new THREE.AnimationMixer(root), actions: new Map(), bones, height };
};

const clipFor = (name: string): THREE.AnimationClip | null => {
  const l = ready.get(motionUrl(name));
  return l?.clips[0] ?? null;
};

/** Pose an instance for this frame. */
export const poseActor = (inst: Inst, s: ActorState) => {
  const fps = s.fps ?? 30;
  // weights from crossfades (pure function of the frame)
  const active = s.tracks.filter((t) => s.frame >= t.from);
  const weights = active.map((t, i) => {
    const next = active[i + 1];
    const wIn = Math.min(1, (s.frame - t.from) / Math.max(1, t.fade ?? 8));
    const wOut = next ? 1 - Math.min(1, (s.frame - next.from) / Math.max(1, next.fade ?? 8)) : 1;
    return Math.max(0, i === 0 ? wOut : wIn * wOut);
  });
  inst.actions.forEach((a) => { a.enabled = false; });
  active.forEach((t, i) => {
    const clip = clipFor(t.clip);
    if (!clip || weights[i] <= 0) return;
    let a = inst.actions.get(t.clip);
    if (!a) { a = inst.mixer.clipAction(clip); inst.actions.set(t.clip, a); }
    a.enabled = true; a.play();
    const local = ((s.frame - t.from) / fps) * (t.speed ?? 1) + (t.offset ?? 0);
    a.time = t.loop === false ? Math.min(local, clip.duration - 1e-3) : ((local % clip.duration) + clip.duration) % clip.duration;
    a.setEffectiveWeight(weights[i]);
    a.paused = true;
  });
  inst.mixer.update(0);
  inst.root.matrixAutoUpdate = false;
  const sc = (s.scale ?? 1.8) / Math.max(0.01, inst.height);
  inst.root.matrix.copy(s.matrix).multiply(new THREE.Matrix4().makeScale(sc, sc, sc));
  inst.root.updateMatrixWorld(true);
  // ---- code layer: IK reach (2-bone, analytic) ----
  (s.reach ?? []).forEach((r) => {
    const up = inst.bones[`arm${r.hand}`], fo = inst.bones[`fore${r.hand}`], ha = inst.bones[`hand${r.hand}`];
    if (!up || !fo || !ha || r.weight <= 0) return;
    const S = up.getWorldPosition(new THREE.Vector3()), E0 = fo.getWorldPosition(new THREE.Vector3()), H0 = ha.getWorldPosition(new THREE.Vector3());
    const a = S.distanceTo(E0), b = E0.distanceTo(H0);
    const T = H0.clone().lerp(r.target, r.weight);
    const dir = T.clone().sub(S); const d = Math.min(dir.length(), a + b - 1e-4); dir.normalize();
    const cosA = (a * a + d * d - b * b) / (2 * a * d);
    const poleRef = E0.clone().sub(S); poleRef.sub(dir.clone().multiplyScalar(poleRef.dot(dir))).normalize();
    const E = S.clone().add(dir.clone().multiplyScalar(a * cosA)).add(poleRef.multiplyScalar(a * Math.sqrt(Math.max(0, 1 - cosA * cosA))));
    const rotateTo = (bone: THREE.Bone, childNow: THREE.Vector3, childWant: THREE.Vector3) => {
      const p = bone.getWorldPosition(new THREE.Vector3());
      const q = new THREE.Quaternion().setFromUnitVectors(childNow.clone().sub(p).normalize(), childWant.clone().sub(p).normalize());
      const wq = bone.getWorldQuaternion(new THREE.Quaternion());
      const pq = bone.parent!.getWorldQuaternion(new THREE.Quaternion());
      bone.quaternion.copy(pq.invert().multiply(q.multiply(wq)));
      bone.updateMatrixWorld(true);
    };
    rotateTo(up, E0, E);
    rotateTo(fo, fo.children.length ? ha.getWorldPosition(new THREE.Vector3()) : H0, S.clone().add(dir.multiplyScalar(d)));
  });
  // ---- code layer: head aim ----
  if (s.lookAt && inst.bones.head && s.lookAt.weight > 0) {
    const h = inst.bones.head;
    const p = h.getWorldPosition(new THREE.Vector3());
    const fwd = new THREE.Vector3(0, 0, 1).applyQuaternion(h.getWorldQuaternion(new THREE.Quaternion()));
    const want = s.lookAt.target.clone().sub(p).normalize();
    const q = new THREE.Quaternion().setFromUnitVectors(fwd, fwd.clone().lerp(want, s.lookAt.weight * 0.6).normalize());
    const wq = h.getWorldQuaternion(new THREE.Quaternion()), pq = h.parent!.getWorldQuaternion(new THREE.Quaternion());
    h.quaternion.copy(pq.invert().multiply(q.multiply(wq)));
    h.updateMatrixWorld(true);
  }
};
export type ActorInstance = Inst;
