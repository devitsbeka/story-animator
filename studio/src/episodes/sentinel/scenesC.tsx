import React from "react";
import { CamKey } from "../../kit/engine";
import { P, add, ellipse } from "../../kit/geom";
import { Shape } from "../../kit/render";
import { Island, Sea, Sky, Waterline, Yacht, YachtGlow, yachtPoint } from "../../kit/sea";
import { CUE, DURATION } from "./cues";
import { HatchHero, NIGHT, SceneView, boatMotion, camera, heroPt, lin, seg } from "./harness";
import type { SceneProps } from "./scenesA";

// ---------------------------------------------------------------------------
// S09 · step four: kill the lights · shh · leave nothing behind
// ---------------------------------------------------------------------------
const S9_CAM: CamKey[] = [
  [1918, 560, 960, 1, 520, 0],
  [CUE.killLights, 548, 960, 1, 620, 0],
  [CUE.quiet + 6, 540, 940, 1, 760, 0],
  [2080, 520, 1000, 1, 460, 0],
];
export const S9: React.FC<SceneProps> = ({ f, push }) => {
  const s = 1.2, bx = 540;
  const mo = boatMotion(f, [], 0.3);
  const by = 1300 + mo.y;
  const r = -6 + mo.r * 0.3;
  const lights = 1 - lin(f, CUE.killLights, CUE.killLights + 2);
  const dark = seg(f, CUE.killLights, CUE.killLights + 8);
  const head = yachtPoint(bx, by, s, r, [0, -184]);
  const hs = 0.4 * s;
  const shh = f >= CUE.quiet - 8 && f < CUE.nothingBehind - 6;
  const reach = f >= CUE.killLights - 16 && f < CUE.killLights + 6;
  const bag = seg(f, CUE.nothingBehind - 10, CUE.nothingBehind + 2) * (1 - seg(f, CUE.nothingBehind + 14, CUE.nothingBehind + 30));
  const bagDown = seg(f, CUE.nothingBehind + 10, CUE.nothingBehind + 30);
  const switchPt = yachtPoint(bx, by, s, r, [110, -196]);
  const bagHand: P = heroPt(bx, by, s, r, 0.4, [-210, -150 + bagDown * 230]);
  const shhWrist: P = heroPt(bx, by, s, r, 0.4, [-30, -104]);
  const cam = camera(f, S9_CAM, push);
  return (
    <SceneView cam={cam} light={NIGHT(760, 520, 0.22 - 0.08 * dark)}
      layers={[
        { z: 1800, node: <Sky x0={-1300} y0={-1400} w={3700} h={3000} horizon={1060} moon={[840, 740]} moonR={46} f={f} seed={12} /> },
        { z: 700, node: <Island cx={560} base={1060} w={2200} h={460} f={f} seed={9} fires={[{ x: 300, y: 1000, on: 0.9, s: 1.1 }, { x: 760, y: 990, on: 0.9, s: 1.1 }]} /> },
        { z: 300, node: <Sea x0={-1300} w={3700} horizon={1110} bottom={2900} f={f} glitterX={840} seed={15} /> },
        { z: 0, node: (
          <g>
            <Yacht x={bx} y={by} s={s} r={r} f={f} lights={lights} hatch={1}>
              <HatchHero bx={bx} by={by} bs={s} br={r} emerge={1} s={0.4} arms="custom"
                pose={{
                  handL: bag > 0 ? bagHand : yachtPoint(bx, by, s, r, [-52, -192]), handPoseL: bag > 0 ? "grip" : "fist", handAbsL: 0,
                  handR: shh ? shhWrist : reach ? switchPt : yachtPoint(bx, by, s, r, [52, -192]), handPoseR: shh ? "shh" : "fist", handAbsR: shh ? -6 : 0,
                  expr: shh ? "hush" : "determined", look: shh ? [0, 0] : [0.5, 0.3],
                  blink: f > CUE.killLights + 2 && f < CUE.killLights + 7 ? 1 : 0,
                }} />
              {/* the light switch on the cabin roof */}
              <Shape pts={ellipse(switchPt[0], switchPt[1] + 6, 16, 10, 16)} mat={{ base: lights > 0.5 ? "#ffd98a" : "#3a3f50", shade: "#2a2e3a", lit: "#fff1c4", line: "#121419" }} ink={3} shade={0} lit={0} seed={70} />
              {bag > 0 && (
                <g transform={`translate(${bagHand[0]},${bagHand[1] + 50}) scale(${bag})`}>
                  <Shape pts={[[-40, -40], [-14, -56], [14, -56], [40, -40], [48, 30], [0, 52], [-48, 30]]} mat={{ base: "#2b2f38", shade: "#1b1e25", lit: "#464c5a", line: "#121419" }} ink={4} round={0.8} shade={0.15} lit={0.15} seed={71} />
                  <path d="M -12,-56 Q 0,-76 12,-56" stroke="#121419" strokeWidth={6} fill="none" />
                </g>
              )}
            </Yacht>
            <Waterline x0={-1300} x1={2400} y={by + 22} depth={60} f={f} />
            <Sea x0={-1300} w={3700} horizon={by + 64} bottom={2900} f={f} edge={false} rows={10} tint={0.25} seed={16} />
            {/* the night closes in when the lights go off */}
            <rect x={-1300} y={-1400} width={3700} height={4400} fill="#03050f" opacity={0.28 * dark} />
          </g>
        ) },
      ]}
      fx={[{ z: 0, node: <YachtGlow x={bx} y={by} s={s} r={r} lights={lights} /> }]}
    />
  );
};

// ---------------------------------------------------------------------------
// S10 · the tide lifts the boat · drift out past the reef · get gone
// ---------------------------------------------------------------------------
const S10_CAM: CamKey[] = [
  [2060, 560, 1080, 1, 340, 0],
  [CUE.drift, 520, 1060, 1, 120, 0],
  [CUE.gone + 10, 260, 1100, 1, -60, 0],
  [2206, 180, 1000, 1, -120, 0],
];
export const S10: React.FC<SceneProps> = ({ f, push }) => {
  const s = 1.1;
  const rise = seg(f, CUE.tide - 6, CUE.drift);
  const out = seg(f, CUE.drift - 4, 2196);
  const zoom = lin(f, CUE.gone - 8, 2200);
  const bx = 560 - out * 380 - zoom * zoom * 300;
  const mo = boatMotion(f, [], 0.4 + 0.6 * rise);
  const wl = 1300 - rise * 40;
  const by = wl + mo.y - 6 * (1 - rise);
  const r = -6 * (1 - rise) + mo.r * (0.3 + 0.7 * rise) + 3 * zoom;
  const cam = camera(f, S10_CAM, push);
  const wake = Array.from({ length: 8 }, (_, i) => {
    const stern = yachtPoint(bx, by, s, r, [-270, 10]);
    const len = (60 + i * 50) * (out + zoom);
    return <path key={i} d={`M ${stern[0] + 300 * 0},${stern[1] + i * 3} q ${len * 0.5 + 300},${-10 + (i % 2) * 20} ${len + 400},${i * 4}`} stroke="#cfd9ff" strokeWidth={6 - i * 0.6} fill="none" opacity={0.5 * (out + zoom) * (1 - i / 9)} strokeLinecap="round" transform={`translate(${200 + i * 30},0)`} />;
  });
  return (
    <SceneView cam={cam} light={NIGHT(760, 480)}
      layers={[
        { z: 1800, node: <Sky x0={-1500} y0={-1400} w={3900} h={3000} horizon={1060} moon={[840, 740]} moonR={46} f={f} dawn={0.15 * out} seed={13} /> },
        { z: 700, node: <Island cx={620} base={1060} w={2200} h={460} f={f} seed={9} fires={[{ x: 360, y: 1000, on: 0.8, s: 1.1 }, { x: 820, y: 990, on: 0.8, s: 1.1 }]} /> },
        { z: 300, node: <Sea x0={-1500} w={3900} horizon={1110} bottom={2900} f={f} glitterX={840} seed={17} /> },
        { z: 0, node: (
          <g>
            <Yacht x={bx} y={by} s={s} r={r} f={f} lights={0} hatch={1}>
              <HatchHero bx={bx} by={by} bs={s} br={r} emerge={1} s={0.32} arms={f > CUE.gone - 10 ? "up" : "rim"}
                pose={{ expr: f > CUE.gone - 10 ? "grin" : "surprised", look: [-0.6, 0] }} />
            </Yacht>
            {wake}
            <Waterline x0={-1500} x1={2400} y={wl + 22} depth={60} f={f} />
            <Sea x0={-1500} w={3900} horizon={wl + 64} bottom={2900} f={f} edge={false} rows={10} tint={0.25} seed={18} />
            {/* speed lines when it really goes */}
            {zoom > 0 && Array.from({ length: 6 }, (_, i) => <line key={i} x1={bx + 380 + i * 40} y1={by - 260 + i * 60} x2={bx + 680 + i * 60} y2={by - 260 + i * 60} stroke="#e8eeff" strokeWidth={5} opacity={0.5 * zoom} strokeLinecap="round" />)}
          </g>
        ) },
      ]}
    />
  );
};

// ---------------------------------------------------------------------------
// S11 · dawn · the island small and dead centre · the closing line
// ---------------------------------------------------------------------------
const S11_CAM: CamKey[] = [
  [2186, 540, 1000, 1, -100, 0],
  [CUE.never, 540, 980, 1, 120, 0],
  [DURATION, 540, 960, 1, 240, 0],
];
export const S11: React.FC<SceneProps> = ({ f, push }) => {
  const dawn = 0.55 + 0.3 * seg(f, 2196, DURATION);
  const cam = camera(f, S11_CAM, push);
  const sunY = 1060 - 70 * seg(f, 2196, DURATION);
  return (
    <SceneView cam={cam} light={{ ...NIGHT(540, sunY, 0.3), ambient: "#c07a7a", ambientStrength: 0.06 }}
      layers={[
        { z: 2200, node: (
          <g>
            <Sky x0={-1500} y0={-1400} w={3900} h={3000} horizon={1070} f={f} dawn={dawn} seed={14} />
            <circle cx={540} cy={sunY} r={70} fill="#ffe2a8" opacity={0.95} />
            <circle cx={540} cy={sunY} r={220} fill="#ffcf8a" opacity={0.18} />
          </g>
        ) },
        { z: 1200, node: <Island cx={540} base={1072} w={560} h={150} f={f} seed={21} dawn={dawn} reef={false} /> },
        { z: 300, node: <Sea x0={-1500} w={3900} horizon={1072} bottom={2900} f={f} glitterX={840} dawn={dawn} seed={19} /> },
        { z: 0, node: (
          <g transform={`translate(${880 + (f - 2196) * 0.25},${1180}) scale(0.16)`}>
            <Yacht x={0} y={0} s={1} r={0} f={f} lights={0} />
          </g>
        ) },
      ]}
    />
  );
};

export const _u = [add];
