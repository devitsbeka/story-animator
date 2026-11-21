// SENTINEL adapter: reads the code-driven episode (cue table, 3D beats, the richer S01 opening)
// and emits the renderer-neutral episode spec + the list of code-built props to export as GLB.
import * as THREE from "three";
import { CAPS, CUE, DURATION, FPS, OFFSET, SCENES } from "../../../studio/src/episodes/sentinel/cues";
import { BEATS, BeatSpec } from "../../../studio/src/episodes/sentinel/beats3d";
// @ts-ignore: extra exports are injected at bundle time by sentinel.inject.mjs
import { __S1, __S1_KEYS, __S1_MOON, __S1_YACHT, __S1_flick } from "../../../studio/src/episodes/sentinel/s1_3d";
import { buildYacht } from "../../../studio/src/kit/yacht3d";
import { buildIsland } from "../../../studio/src/kit/island3d";
import { collapse, round3, rnd, sampledKeys, stepKeys } from "../lib/keys";
import type { Adapter, Episode, Shot, V3 } from "../lib/types";

const ID = "sentinel";
const flipX = (v: V3): V3 => [-v[0], v[1], v[2]]; // beat specs use +x = hero side; BeatView flips before the yacht transform

// defaults BeatView applies when a beat leaves a field out
const BEAT_DEFAULTS = { moon: [0.12, 0.3, 1] as V3, seaState: 1.6, dawn: 0, handheld: 0.2, heroHeight: 1.8, lookWeight: 0.8 };
const YACHT0 = { x: 0, z: 0, heading: Math.PI / 2 };
const ISL_NEAR = BEATS[1].island!; // the island placement most beats share → world default

const islandOf = (i: { x: number; z: number; rotY?: number; scale?: number }) => ({ asset: "island", x: i.x, z: i.z, rotY: i.rotY ?? 0, scale: i.scale ?? 1 });
const sameIsland = (a?: BeatSpec["island"], b?: BeatSpec["island"]) => !!a && !!b && a.x === b.x && a.z === b.z && (a.rotY ?? 0) === (b.rotY ?? 0) && (a.scale ?? 1) === (b.scale ?? 1);
const sceneAt = (f: number) => SCENES.find((s) => f >= s.from && f < s.to)?.id;

// ---------- the 10 storyboard beats (S02..S11) ----------
const beatShot = (b: BeatSpec): Shot => {
  const rel = (f: number) => b.from + f; // beat-local frames (keys at f:0, tracks from -300…) → absolute
  const shot: Shot = {
    id: b.id, title: b.title, scene: sceneAt(b.from), from: b.from, to: b.to, keyFrame: b.keyFrame,
    camera: {
      space: "yacht",
      keys: b.cam.map((k) => ({ f: rel(k.f), cam: flipX(k.cam), look: flipX(k.look), fov: k.fov, ...(k.roll !== undefined && { roll: k.roll }), ...(k.ease && { ease: k.ease }) })),
      handheld: b.handheld ?? BEAT_DEFAULTS.handheld,
      drift: 0.25,
    },
  };
  if (b.yacht) {
    const y = b.yacht;
    shot.yacht = {
      ...YACHT0, lights: [[b.from, y.lights ?? 0]],
      ...(y.hatch !== undefined && { hatch: y.hatch }), ...(y.pitch !== undefined && { pitch: y.pitch }),
      ...(y.roll !== undefined && { roll: y.roll }), ...(y.sink !== undefined && { sink: y.sink }),
    };
  }
  if (b.hero) {
    const h = b.hero;
    shot.actors = [{
      asset: "hero", space: "yacht", local: h.local, rotY: rnd(h.rotY, 6), height: BEAT_DEFAULTS.heroHeight,
      tracks: h.tracks.map((t) => ({ clip: t.clip, from: rel(t.from), ...(t.loop !== undefined && { loop: t.loop }), ...(t.fade !== undefined && { fade: t.fade }), ...(t.speed !== undefined && { speed: t.speed }), ...(t.offset !== undefined && { offset: t.offset }) })),
      ...(h.look && { lookAt: h.look === "camera" ? "camera" : h.look, lookWeight: BEAT_DEFAULTS.lookWeight }),
    }];
  }
  if (b.island?.fires?.length) shot.fires = [[b.from, [0, 1, 2, 3, 4, 5].map((i) => b.island!.fires![i] ?? 0)]];
  if (b.island && !sameIsland(b.island, ISL_NEAR)) shot.island = islandOf(b.island);
  if (!b.island) shot.island = null;
  const env: Shot["env"] = {};
  if (b.moon) env.moonDir = b.moon;
  if (b.dawn !== undefined) env.dawn = b.dawn;
  const ss = b.seaState ?? b.yacht?.seaState;
  if (ss !== undefined) env.seaState = ss;
  if (Object.keys(env).length) shot.env = env;
  return shot;
};

// ---------- S01: the richer opening from s1_3d.tsx (world-space camera, flicker, kicks, crash zoom) ----------
const openingShot = (): Shot => {
  const sc = SCENES[0];
  const beat = BEATS[0];
  const kick = (f: number) => __S1.kick(f) as number;
  return {
    id: beat.id, title: beat.title, scene: sc.id, from: sc.from, to: sc.to, keyFrame: beat.keyFrame,
    camera: {
      space: "world",
      keys: (__S1_KEYS as typeof beat.cam).map((k) => ({ f: k.f, cam: k.cam, look: k.look, fov: k.fov, ...(k.roll !== undefined && { roll: k.roll }), ...(k.ease && { ease: k.ease }) })),
      handheld: collapse(stepKeys((f) => __S1.handheld(f), sc.from, sc.to)),
      drift: 0.25,
      shakes: __S1.shakes,
    },
    yacht: {
      x: __S1_YACHT.x, z: __S1_YACHT.z, heading: rnd(__S1_YACHT.heading, 6),
      lights: stepKeys((f) => __S1_flick(f), sc.from, sc.to),
      pitch: collapse(sampledKeys(kick, sc.from, sc.to)),
      roll: collapse(sampledKeys((f) => kick(f) * 0.6, sc.from, sc.to)),
    },
    actors: [{
      asset: "hero", space: "yacht", local: round3(__S1.heroLocal), rotY: rnd(__S1.heroRotY, 6), height: __S1.heroScale,
      tracks: __S1.tracks,
      lookAt: "camera",
      lookWeight: collapse(sampledKeys((f) => __S1.lookWeight(f), sc.from, sc.to)),
    }],
    island: islandOf(__S1.island),
    env: { seaState: __S1.seaState, moonDir: __S1_MOON },
  };
};

export const episode = (): Episode => ({
  version: 1,
  id: ID,
  title: "North Sentinel: what to do if your engine dies",
  fps: FPS as 30, width: 1080, height: 1920, durationFrames: DURATION,
  audio: { narration: `episodes/${ID}/audio/narration.mp3`, wordsJson: `episodes/${ID}/audio/narration.words.json`, offsetFrames: OFFSET },
  world: { moonDir: BEAT_DEFAULTS.moon, seaState: BEAT_DEFAULTS.seaState, dawn: BEAT_DEFAULTS.dawn, island: islandOf(ISL_NEAR) },
  assets: {
    characters: { hero: "assets/characters/hero/hero.glb" },
    motions: Object.fromEntries(["brace_loop", "startle", "panic_arms"].map((m) => [m, `assets/motions/${m}.glb`])),
    props: { yacht: "assets/props/yacht.glb", island: "assets/props/island_sentinel.glb" },
  },
  shots: [openingShot(), ...BEATS.slice(1).map(beatShot)],
  captions: CAPS.map((c) => ({ from: c.from, to: c.to, ...(c.small && { small: c.small }), big: c.big, ...(c.at && { at: c.at }), ...(c.tone && { tone: c.tone }) })),
});

// ---------- code-built props → GLB ----------
const nameByMaterial = (root: THREE.Object3D, rules: [(m: any) => boolean, string][]) => {
  root.traverse((o: any) => {
    if (!o.isMesh) return;
    const m = o.material;
    const hit = rules.find(([test]) => test(m));
    if (hit && !m.name) m.name = hit[1];
  });
};

const yachtProp = (): THREE.Object3D => {
  const rig = buildYacht(null);
  rig.setLights(1); // GLB carries the lights-ON values; spec yacht.lights multiplies them
  const g = rig.group;
  g.name = "yacht";
  rig.hatch.name = "hatch_pivot";
  const hex = (m: any) => (m.color ? m.color.getHex() : -1);
  nameByMaterial(g, [
    [(m) => m.isMeshPhysicalMaterial && m.vertexColors, "gelcoat_hull"],
    [(m) => m.isMeshPhysicalMaterial && m.emissive && m.emissive.r > 0.9 && m.emissive.g > 0.6 && m.emissive.g < 0.7, "glass_cabin"],
    [(m) => m.isMeshPhysicalMaterial && hex(m) === 0xeceef2, "gelcoat_white"],
    [(m) => hex(m) === 0x8a5a32, "teak"],
    [(m) => m.metalness === 1, "steel"],
    [(m) => hex(m) === 0x1c2027, "upholstery_dark"],
    [(m) => hex(m) === 0x1e3a8a, "fender"],
    [(m) => hex(m) === 0xff2a1a, "nav_port_red"],
    [(m) => hex(m) === 0x18ff5a, "nav_stbd_green"],
    [(m) => hex(m) === 0xffffff && m.emissiveIntensity > 0, "nav_white"],
  ]);
  let n = 0;
  g.traverse((o: any) => {
    if (o.isPointLight) o.name = "cabin_light";
    else if (o.isMesh && !o.name) o.name = `${o.material?.name || "part"}_${n++}`;
  });
  // anchors as empties so Blender can find cockpit / exhaust / bow etc.
  Object.entries(rig.anchors).forEach(([k, v]) => { const e = new THREE.Object3D(); e.name = `anchor_${k}`; e.position.copy(v); g.add(e); });
  return g;
};

const islandProp = (): THREE.Object3D => {
  const rig = buildIsland(null, { scale: 1 });
  const g = rig.group;
  g.name = "island_sentinel";
  // fires at full, no flicker (v = 1, fl = 1): spec `fires` multiplies them; the renderer adds flicker.
  // island3d: light = v*900*fl, flame scale (1, .6+.4fl, 1)*v, flame colour (1.6fl, .75fl, .25) HDR.
  // glTF base colours must be <= 1, so the HDR flame becomes an emissive with emissive_strength 1.6.
  rig.fires.forEach((l, i) => { l.name = `fire_light_${i}`; l.intensity = 900; });
  rig.fireMeshes.forEach((m, i) => {
    m.name = `fire_${i}`; m.visible = true; m.scale.set(1, 1, 1);
    const hdr = new THREE.Color(1.6, 0.75, 0.25), k = Math.max(hdr.r, hdr.g, hdr.b);
    m.material = new THREE.MeshStandardMaterial({ name: `flame_${i}`, color: 0x000000, roughness: 1, emissive: hdr.multiplyScalar(1 / k), emissiveIntensity: k });
  });
  let n = 0;
  g.traverse((o: any) => {
    if (o.isInstancedMesh) { o.name = "canopy"; o.material.name = "canopy"; }
    else if (o.isMesh && !o.name) {
      const m = o.material;
      const hex = m.color?.getHex();
      m.name ||= hex === 0x8c8470 ? "sand" : hex === 0x1b2a1d ? "ground" : hex === 0x15201a ? "palm" : hex === 0xcfd8f0 ? "reef_foam" : "island_part";
      o.name = `${m.name}_${n++}`;
    }
  });
  return g;
};

export const adapter: Adapter = {
  id: ID,
  episode,
  props: [
    { key: "yacht", file: "assets/props/yacht.glb", build: yachtProp },
    { key: "island", file: "assets/props/island_sentinel.glb", build: islandProp },
  ],
};
// keep CUE referenced so the cue table is part of the bundle's provenance
export const cueCount = Object.keys(CUE).length;
