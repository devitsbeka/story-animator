import React, { useLayoutEffect, useRef } from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { HeroPose3, V3, buildHero3D } from "../kit/hero3d";
import { SANS } from "../kit/type";

type View = { label: string; cam: V3; look: V3; fov: number; pose: HeroPose3; rotY?: number };
const Studio: React.FC<{ v: View; w: number; h: number }> = ({ v, w, h }) => {
  const ref = useRef<HTMLCanvasElement>(null);
  useLayoutEffect(() => {
    const r = new THREE.WebGLRenderer({ canvas: ref.current!, antialias: true, preserveDrawingBuffer: true });
    r.setSize(w, h, false); r.toneMapping = THREE.ACESFilmicToneMapping; r.outputColorSpace = THREE.SRGBColorSpace;
    r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFSoftShadowMap;
    const scene = new THREE.Scene(); scene.background = new THREE.Color(0x2a2d36);
    const env = new THREE.PMREMGenerator(r).fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environment = env;
    const hero = buildHero3D(env);
    hero.group.rotation.y = v.rotY ?? 0;
    scene.add(hero.group);
    hero.setPose(v.pose);
    const key = new THREE.DirectionalLight(0xfff1e0, 2.4); key.position.set(2, 3, 3); key.castShadow = true; key.shadow.mapSize.set(1024, 1024); scene.add(key);
    const rim = new THREE.DirectionalLight(0x9fb8ff, 2.0); rim.position.set(-2, 2.5, -3); scene.add(rim);
    scene.add(new THREE.HemisphereLight(0x8090b0, 0x202020, 0.5));
    const floor = new THREE.Mesh(new THREE.CircleGeometry(1.2, 48), new THREE.MeshStandardMaterial({ color: 0x3a3e4a, roughness: 0.9 }));
    floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
    const cam = new THREE.PerspectiveCamera(v.fov, w / h, 0.05, 50); cam.position.set(...v.cam); cam.lookAt(...v.look);
    r.render(scene, cam);
    return () => r.dispose();
  }, [v, w, h]);
  return <canvas ref={ref} width={w} height={h} style={{ width: w, height: h, display: "block" }} />;
};

const idle: HeroPose3 = { armL: { shoulder: [0.04, 0, -0.14], elbow: 0.25, gesture: "relaxed" }, armR: { shoulder: [0.04, 0, 0.14], elbow: 0.25, gesture: "relaxed" }, expr: "neutral" };
const full = (label: string, rotY: number): View => ({ label, cam: [0, 1.05, 4.6], look: [0, 0.92, 0], fov: 28, pose: idle, rotY });
const face = (label: string, expr: HeroPose3["expr"], extra: Partial<HeroPose3> = {}): View => ({ label, cam: [0.15, 1.7, 0.95], look: [0, 1.66, 0], fov: 24, pose: { ...idle, expr, ...extra } });
const VIEWS: View[] = [
  full("front", 0), full("three-quarter", -0.7), full("side", -Math.PI / 2), full("back", Math.PI),
  face("scared", "scared"), face("shout", "shout"), face("determined", "determined", { look: [0.4, 0] }), face("grin", "grin"),
];
export const Hero3DSheet: React.FC = () => (
  <div style={{ width: 1920, height: 1080, background: "#1d2028", display: "grid", gridTemplateColumns: "repeat(4, 480px)", gridTemplateRows: "repeat(2, 540px)" }}>
    {VIEWS.map((v, i) => (
      <div key={i} style={{ position: "relative" }}>
        <Studio v={v} w={480} h={540} />
        <div style={{ position: "absolute", bottom: 12, left: 0, right: 0, textAlign: "center", fontFamily: SANS, fontWeight: 700, fontSize: 20, color: "#c9cedd", letterSpacing: "0.1em", textTransform: "uppercase" }}>{v.label}</div>
      </div>
    ))}
  </div>
);
