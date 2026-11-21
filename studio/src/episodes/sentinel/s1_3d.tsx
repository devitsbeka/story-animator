import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Ocean3D, SeaShot, V3, project, yachtWorld } from "../../kit/ocean3d";
import { CamKey3, EASE, rigAt } from "../../kit/camrig";
import { Hero, STREET } from "../../kit/character";
import { Smoke, makePuffs } from "../../kit/sea";
import { CUE } from "./cues";
import { W, H, NIGHT } from "./harness";
import { LightCtx } from "../../kit/render";

// ---------------------------------------------------------------------------
// S01 (3D) · alone on a yacht at night, storm sea · engine sputters and DIES · hero pops out
// Camera: low wide over the swell → arrive on the yacht → 6-frame CRASH ZOOM on "died" with a
// hard stop + decaying shake → slow creep while he panics → crane up into the chart.
// ---------------------------------------------------------------------------
const YACHT = { x: 0, z: 0, heading: Math.PI / 2 };
const MOON: V3 = [0.12, 0.3, 1];
const KEYS: CamKey3[] = [
  { f: 0, cam: [-9, 2.0, -44], look: [0, 1.8, 0], fov: 34 },
  { f: 104, cam: [-3, 2.6, -25], look: [0, 2.1, 0], fov: 30, ease: "arrive" },
  { f: CUE.died - 6, cam: [-2.6, 2.7, -24], look: [0, 2.3, 0], fov: 29, ease: "move" },
  { f: CUE.died, cam: [-3.4, 2.8, -23.4], look: [-3.2, 2.9, -1.6], fov: 17, ease: "crashIn" },
  { f: 228, cam: [-3.9, 3.0, -21.6], look: [-4.0, 3.0, -1.7], fov: 15.5, ease: "arrive" },
  { f: 252, cam: [0, 26, -12], look: [0, 0, 4], fov: 40, ease: "exit" },
];

const flick = (f: number) => {
  if (f < CUE.engine - 4) return 1;
  if (f >= CUE.died) return 0;
  const h = Math.sin((Math.floor(f / 2) + 3) * 12.9898) * 43758.5453;
  return h - Math.floor(h) > 0.4 + 0.5 * ((f - CUE.engine) / (CUE.died - CUE.engine)) ? 1 : 0.15;
};

export const S1_3D: React.FC<{ f: number; push: number }> = ({ f, push }) => {
  const t = f / 30;
  const rig = rigAt(f, KEYS, {
    handheld: 0.18 + 0.25 * (f > CUE.engine - 4 ? 1 : 0),
    shakes: [{ at: CUE.died, px: 14, tau: 1.8 }, { at: CUE.engine, px: 5, tau: 2.2 }, { at: CUE.engine + 9, px: 5, tau: 2.2 }, { at: CUE.engine + 18, px: 6, tau: 2.2 }],
  });
  const kick = [CUE.engine, CUE.engine + 9, CUE.engine + 18, CUE.died].reduce((acc, at, i) => {
    const d = f - at;
    return d < 0 ? acc : acc + (i === 3 ? 0.07 : 0.035) * Math.exp(-d / 8) * Math.sin(d * 0.6);
  }, 0);
  const shot: SeaShot = {
    time: t, ...rig, fov: rig.fov! / push,
    moonDir: MOON, seaState: 1.75,
    yacht: { ...YACHT, lights: flick(f), pitch: kick, roll: kick * 0.6 },
  };
  // project helpers
  const P = (local: V3) => project(shot, W, H, yachtWorld(shot, local));
  // hero: a 1.8 m person standing on the starboard side deck aft of the cabin, waist at the rail
  const waistL: V3 = [1.75, 2.25, -4.1];
  const waist = P(waistL);
  const headTopW = yachtWorld(shot, [1.75, 3.2, -4.1]);
  const headTop = project(shot, W, H, headTopW);
  const hs = Math.hypot(headTop[0] - waist[0], headTop[1] - waist[1]) / 540; // hero units → px
  const pop = f < CUE.noLights - 16 ? 0 : EASE.overshoot(Math.min(1, (f - (CUE.noLights - 16)) / 14));
  const dip = f > CUE.noLights - 22 && f < CUE.noLights - 16 ? Math.sin(((f - (CUE.noLights - 22)) / 6) * Math.PI) * 0.06 : 0;
  const rise = (1 - pop + dip) * 600 * hs;
  const lean = Math.atan2(headTop[0] - waist[0], -(headTop[1] - waist[1])) * 57.3;
  const panic = f >= CUE.noLights - 4;
  const g1 = P([2.2, 1.55, -6.6]), g2 = P([2.2, 1.6, -1.4]);
  const clip = `polygon(${[[-2000, -4000], [3000, -4000], [3000, g2[1] + (g2[1] - g1[1]) / (g2[0] - g1[0]) * (3000 - g2[0])], [-2000, g1[1] + (g2[1] - g1[1]) / (g2[0] - g1[0]) * (-2000 - g1[0])]].map(([x, y]) => `${x}px ${y}px`).join(",")})`;
  const hands = panic
    ? { handL: [waist[0] - 230 * hs, waist[1] - 400 * hs + rise] as [number, number], handR: [waist[0] + 230 * hs, waist[1] - 400 * hs + rise] as [number, number] }
    : { handL: [waist[0] - 170 * hs, waist[1] - 10 * hs + rise] as [number, number], handR: [waist[0] + 170 * hs, waist[1] - 10 * hs + rise] as [number, number] };
  // smoke from the real exhaust point
  const ex = P([1.4, 0.7, -7.05]);
  const puffs = makePuffs([
    { at: CUE.engine, n: 3, x: ex[0], y: ex[1], power: hs * 6 },
    { at: CUE.engine + 9, n: 3, x: ex[0], y: ex[1], power: hs * 6 },
    { at: CUE.engine + 18, n: 4, x: ex[0], y: ex[1], power: hs * 6 },
    { at: CUE.died, n: 8, x: ex[0], y: ex[1], power: hs * 9 },
  ]);
  const cw = yachtWorld(shot, [0, 0, 0]);
  const moonScr = project(shot, W, H, [cw[0] + MOON[0] * 800, MOON[1] * 800, cw[2] + MOON[2] * 800]);
  return (
    <AbsoluteFill>
      <LightCtx.Provider value={NIGHT(moonScr[0], moonScr[1], 0.25)}>
      <Ocean3D w={W} h={H} shot={shot}>
        <svg width={W} height={H} style={{ position: "absolute", inset: 0 }}>
          <Smoke puffs={puffs} f={f} />
        </svg>
        <svg width={W} height={H} style={{ position: "absolute", inset: 0, clipPath: clip }}>
          {pop > 0 && (
            <Hero p={{
              x: waist[0], y: waist[1] + rise, s: hs, lean, outfit: STREET,
              ...hands, handPoseL: "open", handPoseR: "open",
              handAbsL: panic ? -12 + Math.sin(f * 0.9) * 8 : undefined, handAbsR: panic ? 12 - Math.sin(f * 0.9) * 8 : undefined,
              expr: panic ? "scared" : "surprised",
              blink: f > CUE.nothing + 2 && f < CUE.nothing + 7 ? 1 : 0,
              look: [0.15, -0.1], headTilt: panic ? Math.sin(f * 0.25) * 5 : 0,
            }} />
          )}
        </svg>
      </Ocean3D>
      </LightCtx.Provider>
    </AbsoluteFill>
  );
};

export const S1Test: React.FC = () => <S1_3D f={useCurrentFrame()} push={1} />;
