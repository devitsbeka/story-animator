import React, { useLayoutEffect, useRef } from "react";
import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
// MIT © 2026 Meng To: threejs-scene-fx/3d-ultra-realistic-water (see vendor/ocean/LICENSE)
// @ts-expect-error untyped vendored module
import { createWaves, bakeOceanDetail, createOcean } from "../vendor/ocean/ocean.mjs";
import { YachtRig, buildYacht, yachtPose } from "./yacht3d";
import { ActorInstance, ActorState, instantiate, poseActor } from "./actors";
import { IslandRig, buildIsland } from "./island3d";

// ============================================================================
// OCEAN 3D: a real Three.js sea (Gerstner spectrum shaded per pixel, Fresnel sky
// reflection, HDR moon glitter → bloom, lace foam, aerial haze) under a night sky.
// Pure function of props: the wave phases are rebuilt from `time` every frame.
// Helpers below give the SAME camera and wave heights to the 2D (SVG) layer, so drawn
// boats and characters sit on the real water at the right scale.
// ============================================================================

export type V3 = [number, number, number];
export type SeaShot = {
  time: number;
  cam: V3; look: V3; fov?: number; roll?: number; // degrees
  moonDir?: V3; // direction to the moon (also the glitter path)
  seaState?: number; // 1 = the reference sea, 1.6 = rough, 2.2 = storm
  dawn?: number;
  yacht?: YachtState;
  actors?: ActorState[];
  island?: { x: number; z: number; rotY?: number; scale?: number; fires?: number[] };
};
export type YachtState = { x: number; z: number; heading: number; lights?: number; hatch?: number; pitch?: number; roll?: number; heave?: number; sink?: number };

/** The yacht's world matrix at this moment (buoyancy + scripted extras). */
export const yachtMatrix = (s: SeaShot): THREE.Matrix4 => {
  const y = s.yacht!;
  const pose = yachtPose(s.time, y.x, y.z, y.heading, s.seaState ?? 1.6);
  const m = new THREE.Matrix4();
  const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(-(pose.pitch + (y.pitch ?? 0)), y.heading, pose.roll + (y.roll ?? 0), "YXZ"));
  m.compose(new THREE.Vector3(y.x, pose.y + (y.heave ?? 0) - (y.sink ?? 0), y.z), q, new THREE.Vector3(1, 1, 1));
  return m;
};
/** A point on the yacht (local metres) in world space. */
export const yachtWorld = (s: SeaShot, local: V3): V3 => {
  const v = new THREE.Vector3(...local).applyMatrix4(yachtMatrix(s));
  return [v.x, v.y, v.z];
};

const W_DIR = 1.22;
const mkWaves = () => createWaves({ direction: W_DIR });
const wavesCache = new Map<string, ReturnType<typeof mkWaves>>();
const wavesAt = (time: number, seaState: number) => {
  const key = "w";
  let w = wavesCache.get(key);
  if (!w) { w = mkWaves(); wavesCache.set(key, w); }
  w.time = 0; w.update(time); w.setSeaState(seaState);
  return w;
};
export const seaHeight = (time: number, x: number, z: number, seaState = 1.6): number => wavesAt(time, seaState).height(x, z);

export const makeCamera = (s: SeaShot, w: number, h: number) => {
  const cam = new THREE.PerspectiveCamera(s.fov ?? 38, w / h, 0.5, 20000);
  cam.position.set(...s.cam);
  const fwd = new THREE.Vector3(...s.look).sub(cam.position).normalize();
  const up = new THREE.Vector3(0, 1, 0).applyAxisAngle(fwd, -((s.roll ?? 0) * Math.PI) / 180);
  cam.up.copy(up);
  cam.lookAt(...s.look);
  cam.updateMatrixWorld(true);
  cam.updateProjectionMatrix();
  return cam;
};
/** World point → screen px (and depth). */
export const project = (s: SeaShot, w: number, h: number, p: V3): [number, number, number] => {
  const cam = makeCamera(s, w, h);
  const v = new THREE.Vector3(...p).project(cam);
  return [(v.x * 0.5 + 0.5) * w, (-v.y * 0.5 + 0.5) * h, v.z];
};

// ---------- night sky (shared by the sky dome, the reflection cube and the ocean's haze) ----------
const SKY_GLSL = /* glsl */ `
uniform vec3 uMoonDir; uniform float uDawn; uniform float uSkyTime;
float sh21(vec2 p){ p = fract(p * vec2(233.34, 851.73)); p += dot(p, p + 23.45); return fract(p.x * p.y); }
float sn2(vec2 p){ vec2 i = floor(p), f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(sh21(i), sh21(i + vec2(1,0)), u.x), mix(sh21(i + vec2(0,1)), sh21(i + vec2(1,1)), u.x), u.y); }
float sfbm(vec2 p){ float a = 0.5, s = 0.0; for (int i = 0; i < 6; i++){ s += a * sn2(p); p = mat2(1.6, 1.2, -1.2, 1.6) * p + 3.1; a *= 0.5; } return s; }
vec3 hazeColor(vec3 d){
  vec3 night = vec3(0.012, 0.02, 0.045), dawn = vec3(0.55, 0.28, 0.22);
  float m = max(dot(normalize(vec3(d.x, 0.0, d.z) + 1e-4), normalize(vec3(uMoonDir.x, 0.0, uMoonDir.z))), 0.0);
  // faint airglow band + moon-side brightening along the horizon
  return mix(night, dawn, uDawn) + vec3(0.02, 0.028, 0.05) * pow(m, 8.0) * (1.0 - uDawn);
}
vec3 skyColor(vec3 d, bool withMoonDisc){
  float e = clamp(d.y, 0.0, 1.0);
  vec3 top = mix(vec3(0.0008, 0.0016, 0.006), vec3(0.05, 0.08, 0.22), uDawn);
  vec3 col = mix(hazeColor(d), top, pow(e, 0.38));
  float m = max(dot(d, uMoonDir), 0.0);
  // moon: tight glow + 22° halo ring + wide scatter
  col += vec3(0.16, 0.19, 0.28) * pow(m, 220.0) * 1.2 + vec3(0.04, 0.05, 0.08) * pow(m, 18.0);
  float ang = degrees(acos(clamp(m, -1.0, 1.0)));
  col += vec3(0.03, 0.035, 0.05) * exp(-pow((ang - 22.0) / 1.6, 2.0)) * (1.0 - uDawn);
  // milky way: a tilted, mottled band
  vec3 bandN = normalize(vec3(0.55, 0.35, -0.75));
  float band = exp(-pow(dot(d, bandN) / 0.16, 2.0));
  float dust = sfbm(vec2(atan(d.z, d.x) * 6.0, d.y * 9.0));
  col += vec3(0.018, 0.02, 0.03) * band * smoothstep(0.35, 0.8, dust) * smoothstep(0.05, 0.35, e) * (1.0 - uDawn);
  // stars: three magnitudes, slight colour, twinkle
  for (int L = 0; L < 3; L++) {
    float sc = L == 0 ? 160.0 : (L == 1 ? 320.0 : 640.0);
    vec2 sg = vec2(atan(d.z, d.x) * sc, d.y * sc * 1.9);
    vec2 id = floor(sg); float st = sh21(id + float(L) * 17.0);
    float thr = L == 0 ? 0.9975 : (L == 1 ? 0.995 : 0.99 - band * 0.02);
    vec2 o2 = vec2(sh21(id + 3.1), sh21(id + 8.7)) - 0.5;
    float dd = length(fract(sg) - 0.5 - o2 * 0.6);
    float star = step(thr, st) * smoothstep(0.32, 0.0, dd) * (0.65 + 0.35 * sin(uSkyTime * (2.0 + st * 3.0) + st * 60.0));
    vec3 tint = mix(vec3(0.75, 0.82, 1.0), vec3(1.0, 0.88, 0.74), sh21(id + 5.5));
    col += tint * star * (L == 0 ? 1.6 : (L == 1 ? 0.7 : 0.3)) * smoothstep(0.02, 0.18, e) * (1.0 - uDawn);
  }
  if (withMoonDisc) {
    float r = 0.026;
    float a = acos(clamp(m, -1.0, 1.0));
    if (a < r * 1.05) {
      vec3 tX = normalize(cross(uMoonDir, vec3(0, 1, 0))), tY = cross(tX, uMoonDir);
      vec2 uvm = vec2(dot(d, tX), dot(d, tY)) / r;
      float maria = sfbm(uvm * 1.6 + 7.0);
      vec3 mc = vec3(1.9, 1.86, 1.72) * mix(1.0, 0.62, smoothstep(0.48, 0.66, maria));
      mc *= 0.82 + 0.18 * sqrt(max(0.0, 1.0 - dot(uvm, uvm))); // limb darkening
      col = mix(col, mc, smoothstep(r, r * 0.94, a));
    }
  }
  // clouds: layered fbm banks drifting, lit from the moon (silver lining, dark bellies)
  vec2 cp = d.xz / max(d.y + 0.08, 0.04) * 0.55 + vec2(uSkyTime * 0.01, uSkyTime * 0.003);
  float cl = sfbm(cp);
  float cov = smoothstep(0.5, 0.78, cl) * smoothstep(0.0, 0.12, d.y);
  float thick = smoothstep(0.5, 0.95, cl);
  float lit = pow(m, 6.0) * (1.0 - thick) * 1.4 + pow(m, 40.0) * 2.0 * smoothstep(0.82, 0.55, cl);
  vec3 cloud = mix(vec3(0.004, 0.006, 0.014), vec3(0.008, 0.011, 0.024), e) + vec3(0.12, 0.13, 0.17) * lit;
  cloud = mix(cloud, mix(vec3(0.3, 0.2, 0.22), vec3(0.85, 0.55, 0.45), lit), uDawn);
  return mix(col, cloud, cov * 0.95);
}
vec3 oceanHaze(vec3 d){ return hazeColor(d); }
`;

type GL = {
  renderer: THREE.WebGLRenderer; scene: THREE.Scene; skyScene: THREE.Scene; composer: EffectComposer; bloom: UnrealBloomPass;
  cubeRT: THREE.WebGLCubeRenderTarget; cubeCam: THREE.CubeCamera; ocean: ReturnType<typeof createOcean>; skyU: Record<string, THREE.IUniform>;
  renderPass: RenderPass; yacht: YachtRig; moon: THREE.DirectionalLight; actors: Map<string, ActorInstance>; island: IslandRig | null; islandScale: number;
};

export const Ocean3D: React.FC<{ shot: SeaShot; w: number; h: number; front?: [number, number][]; children?: React.ReactNode; debug?: string }> = ({ shot, w, h, front, children, debug }) => {
  const ref = useRef<HTMLCanvasElement>(null);
  const fref = useRef<HTMLCanvasElement>(null);
  const gl = useRef<GL | null>(null);
  useLayoutEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    if (!gl.current) {
      const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true, powerPreference: "high-performance" });
      renderer.setPixelRatio(1);
      renderer.debug.checkShaderErrors = true;
      renderer.setSize(w, h, false);
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 0.95;
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      const skyU: Record<string, THREE.IUniform> = { uMoonDir: { value: new THREE.Vector3(0.3, 0.25, 0.9).normalize() }, uDawn: { value: 0 }, uSkyTime: { value: 0 } };
      const skyMat = (disc: boolean) => new THREE.ShaderMaterial({
        uniforms: skyU, side: THREE.BackSide, depthWrite: false,
        vertexShader: "varying vec3 vD; void main(){ vD = normalize((modelMatrix * vec4(position, 0.0)).xyz); vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0); gl_Position = p.xyww; }",
        fragmentShader: SKY_GLSL + `varying vec3 vD; void main(){ gl_FragColor = vec4(skyColor(normalize(vD), ${disc ? "true" : "false"}), 1.0); }`,
      });
      const scene = new THREE.Scene();
      const dome = new THREE.Mesh(new THREE.SphereGeometry(10000, 48, 24), skyMat(true));
      dome.frustumCulled = false;
      dome.renderOrder = 10;
      if (debug !== "nodome") scene.add(dome);
      const skyScene = new THREE.Scene();
      skyScene.add(new THREE.Mesh(new THREE.SphereGeometry(100, 32, 16), skyMat(false)));
      const cubeRT = new THREE.WebGLCubeRenderTarget(128, { type: THREE.HalfFloatType, generateMipmaps: true, minFilter: THREE.LinearMipmapLinearFilter });
      const cubeCam = new THREE.CubeCamera(0.1, 1000, cubeRT);
      const waves = wavesAt(0, 1.6);
      const ocean = createOcean(THREE, {
        waves, detailTexture: bakeOceanDetail(THREE, renderer), skyCube: cubeRT.texture,
        hazeGLSL: SKY_GLSL, hazeUniforms: skyU,
        sunColor: new THREE.Vector3(0.2, 0.23, 0.3),
        ambient: new THREE.Vector3(0.07, 0.09, 0.16),
        deepColor: new THREE.Vector3(0.004, 0.011, 0.024),
        scatterColor: new THREE.Vector3(0.012, 0.07, 0.1),
        foamColor: new THREE.Vector3(0.55, 0.6, 0.7),
        fogDensity: 1.6e-4,
      });
      if (debug === "plane") { const pl = new THREE.Mesh(new THREE.PlaneGeometry(200, 200).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: 0xff0000 })); scene.add(pl); } else scene.add(ocean.mesh);
      const yacht = buildYacht(cubeRT.texture);
      scene.add(yacht.group);
      const moon = new THREE.DirectionalLight(0xc8d6ff, 2.6);
      scene.add(moon, moon.target);
      scene.add(new THREE.HemisphereLight(0x3a4a80, 0x0a0e18, 0.8));
      const fill = new THREE.DirectionalLight(0x9fb2e8, 0.0); fill.name = "fill"; scene.add(fill, fill.target);
      const composer = new EffectComposer(renderer, new THREE.WebGLRenderTarget(w, h, { type: THREE.HalfFloatType, samples: 4 }));
      const renderPass = new RenderPass(scene, new THREE.PerspectiveCamera());
      composer.addPass(renderPass);
      const bloom = new UnrealBloomPass(new THREE.Vector2(w / 2, h / 2), 0.32, 0.35, 1.6);
      composer.addPass(bloom);
      composer.addPass(new OutputPass());
      gl.current = { renderer, scene, skyScene, composer, bloom, cubeRT, cubeCam, ocean, skyU, renderPass, yacht, moon, actors: new Map(), island: null, islandScale: 0 };
    }
    const g = gl.current;
    const seaState = shot.seaState ?? 1.6;
    const waves = wavesAt(shot.time, seaState);
    g.skyU.uSkyTime.value = shot.time;
    g.skyU.uDawn.value = shot.dawn ?? 0;
    (g.skyU.uMoonDir.value as THREE.Vector3).set(...(shot.moonDir ?? [0.3, 0.25, 0.9])).normalize();
    g.ocean.uniforms.uSunDir.value.copy(g.skyU.uMoonDir.value);
    if (shot.yacht) {
      g.yacht.group.visible = true;
      g.yacht.group.matrixAutoUpdate = false;
      g.yacht.group.matrix.copy(yachtMatrix(shot));
      g.yacht.group.updateMatrixWorld(true);
      g.yacht.setLights(shot.yacht.lights ?? 0);
      g.yacht.hatch.rotation.x = -(shot.yacht.hatch ?? 0) * 1.9;
      const md = g.skyU.uMoonDir.value as THREE.Vector3;
      g.moon.position.set(shot.yacht.x + md.x * 50, md.y * 50, shot.yacht.z + md.z * 50);
      g.moon.target.position.set(shot.yacht.x, 0, shot.yacht.z);
      g.moon.target.updateMatrixWorld();
      const fill = g.scene.getObjectByName("fill") as THREE.DirectionalLight;
      fill.intensity = 1.8; fill.position.set(shot.cam[0], shot.cam[1] + 6, shot.cam[2]); fill.target.position.set(shot.yacht.x, 1.5, shot.yacht.z); fill.target.updateMatrixWorld();
    } else g.yacht.group.visible = false;
    if (shot.island) {
      const sc = shot.island.scale ?? 1;
      if (!g.island || g.islandScale !== sc) {
        if (g.island) g.scene.remove(g.island.group);
        g.island = buildIsland(g.cubeRT.texture, { scale: sc }); g.islandScale = sc; g.scene.add(g.island.group);
      }
      g.island.group.visible = true;
      g.island.group.position.set(shot.island.x, 0, shot.island.z);
      g.island.group.rotation.y = shot.island.rotY ?? 0;
      g.island.setFires(shot.island.fires ?? [], shot.time);
    } else if (g.island) g.island.group.visible = false;
    (shot.actors ?? []).forEach((a, i) => {
      const key = `${a.asset}#${i}`;
      let inst = g.actors.get(key);
      if (!inst) { const made = instantiate(a.asset); if (!made) return; inst = made; g.actors.set(key, inst); g.scene.add(inst.root); }
      inst.root.visible = true;
      poseActor(inst, a);
    });
    const cam = makeCamera(shot, w, h);
    g.cubeCam.update(g.renderer, g.skyScene);
    void waves;
    g.ocean.update({ time: shot.time, camera: cam });
    g.renderPass.camera = cam;
    if (debug === "nobloom" || debug === "nodome" || debug === "plane") g.renderer.render(g.scene, cam); else g.composer.render();
    if (debug === "diag") {
      g.renderer.render(g.scene, cam);
      const progs = (g.renderer.info.programs ?? []) as unknown as { name: string; diagnostics?: { runnable: boolean; programLog: string; vertexShader: { log: string }; fragmentShader: { log: string } } }[];
      const bad = progs.filter((p) => p.diagnostics && !p.diagnostics.runnable);
      if (bad.length) throw new Error("SHADER: " + bad.map((p) => p.name + " | " + p.diagnostics!.programLog + " | VS " + p.diagnostics!.vertexShader.log.slice(0, 600) + " | FS " + p.diagnostics!.fragmentShader.log.slice(0, 1200)).join("\n"));
      throw new Error("DIAG OK programs=" + progs.map((p) => p.name).join(","));
    }
    const fc = fref.current;
    if (fc) { const c2 = fc.getContext("2d"); if (c2) { c2.clearRect(0, 0, w, h); c2.drawImage(canvas, 0, 0); } }
  });
  const clip = front && front.length > 2 ? `polygon(${front.map(([x, y]) => `${x.toFixed(1)}px ${y.toFixed(1)}px`).join(",")})` : undefined;
  return (
    <>
      <canvas ref={ref} width={w} height={h} style={{ position: "absolute", inset: 0, width: w, height: h }} />
      {children}
      {clip && <canvas ref={fref} width={w} height={h} style={{ position: "absolute", inset: 0, width: w, height: h, clipPath: clip }} />}
    </>
  );
};
