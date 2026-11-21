import React, { useLayoutEffect, useRef } from "react";
import * as THREE from "three";
import { useCurrentFrame } from "remotion";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { characterUrl, instantiate, motionUrl, poseActor, useAssets } from "../kit/actors";

export const HeroGLBTest: React.FC = () => {
  const f = useCurrentFrame();
  const ok = useAssets([characterUrl("hero"), motionUrl("panic_arms"), motionUrl("brace_loop")]);
  const ref = useRef<HTMLCanvasElement>(null);
  const info = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (!ok) return;
    const r = new THREE.WebGLRenderer({ canvas: ref.current!, antialias: true, preserveDrawingBuffer: true });
    r.setSize(1080, 1920, false); r.toneMapping = THREE.ACESFilmicToneMapping; r.outputColorSpace = THREE.SRGBColorSpace;
    const scene = new THREE.Scene(); scene.background = new THREE.Color(0x30343e);
    scene.environment = new THREE.PMREMGenerator(r).fromScene(new RoomEnvironment(), 0.04).texture;
    const inst = instantiate("hero")!;
    scene.add(inst.root);
    poseActor(inst, { asset: "hero", frame: f, scale: 1.8, matrix: new THREE.Matrix4(), tracks: [{ clip: "brace_loop", from: -100, loop: true }, { clip: "panic_arms", from: 20, loop: true }] });
    const box = new THREE.Box3().setFromObject(inst.root);
    info.current!.textContent = `h=${inst.height.toFixed(3)} box=${box.min.toArray().map((v) => v.toFixed(2))} → ${box.max.toArray().map((v) => v.toFixed(2))} bones=${Object.keys(inst.bones).join(",")}`;
    scene.add(new THREE.DirectionalLight(0xffffff, 2).translateX(2).translateY(3).translateZ(3));
    const cam = new THREE.PerspectiveCamera(30, 1080 / 1920, 0.05, 100); cam.position.set(0, 1.0, 5.2); cam.lookAt(0, 0.95, 0);
    r.render(scene, cam);
    return () => r.dispose();
  }, [ok, f]);
  return <div style={{ position: "relative", width: 1080, height: 1920 }}><canvas ref={ref} width={1080} height={1920} /><div ref={info} style={{ position: "absolute", top: 20, left: 20, color: "#fff", font: "24px monospace", width: 1040, wordBreak: "break-all" }} /></div>;
};
