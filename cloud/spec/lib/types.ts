// TypeScript mirror of episode.schema.json (keep in sync; the schema is the source of truth).
import type * as THREE from "three";
export type V3 = [number, number, number];
export type ScalarOrKeys = number | [number, number][];
export type Ease = "arrive" | "move" | "exit" | "anticipate" | "overshoot" | "crashIn" | "linear";
export type CamKey = { f: number; cam: V3; look: V3; fov: number; roll?: number; ease?: Ease };
export type Island = { asset: string; x: number; z: number; rotY: number; scale: number };
export type Track = { clip: string; from: number; loop?: boolean; fade?: number; speed?: number; offset?: number };
export type Actor = { asset: string; space: "yacht"; local: V3; rotY: number; height?: number; tracks: Track[]; lookAt?: "camera" | V3; lookWeight?: ScalarOrKeys };
export type Shot = {
  id: string; from: number; to: number; title?: string; scene?: string; keyFrame?: number;
  camera: { space: "yacht" | "world"; keys: CamKey[]; handheld?: ScalarOrKeys; drift?: number; shakes?: { at: number; px: number; tau: number }[] };
  yacht?: { x: number; z: number; heading: number; lights: [number, number][]; hatch?: ScalarOrKeys; pitch?: ScalarOrKeys; roll?: ScalarOrKeys; sink?: ScalarOrKeys };
  actors?: Actor[];
  fires?: [number, number[]][];
  island?: Island | null;
  env?: { moonDir?: V3; seaState?: number; dawn?: number };
};
export type Caption = { from: number; to: number; small?: string; big: string; at?: "top" | "low" | "mid"; tone?: "warm" | "blue" | "red" };
export type Episode = {
  $schema?: string; version?: number; source?: Record<string, unknown>;
  id: string; title: string; fps: 30; width: 1080; height: 1920; durationFrames: number;
  audio: { narration: string; wordsJson: string; mix?: string; offsetFrames?: number };
  world: { moonDir: V3; seaState: number; dawn: number; island: Island | null };
  assets: { characters: Record<string, string>; motions: Record<string, string>; props: Record<string, string> };
  shots: Shot[];
  captions: Caption[];
};
export type PropDef = { key: string; file: string; build: () => THREE.Object3D };
export type Adapter = { id: string; episode: () => Episode; props: PropDef[] };
