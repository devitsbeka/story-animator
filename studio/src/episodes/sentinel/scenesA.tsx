import React from "react";
import { CamKey } from "../../kit/engine";
import { P, add, ellipse, qcurve, rng, rot, rr } from "../../kit/geom";
import GEO from "../../data/sentinel_geo.json";
import { Line, Shape } from "../../kit/render";
import { FireGlow, HullWater, Island, Sea, Sky, Smoke, Waterline, Yacht, YachtGlow, makePuffs, yachtPoint } from "../../kit/sea";
import { SANS } from "../../kit/type";
import { CUE } from "./cues";
import { HatchHero, NIGHT, SceneView, boatMotion, camera, flicker, lin, seg, shake } from "./harness";

export type SceneProps = { f: number; push: number };

// ---------------------------------------------------------------------------
// S01 · alone on a yacht · engine dies · lights out · panic
// ---------------------------------------------------------------------------
const S1_KICKS = [CUE.engine, CUE.engine + 9, CUE.engine + 18, CUE.died].map((at, i) => ({ at, pitch: i === 3 ? -9 : 4, heave: i === 3 ? 22 : 9 }));
const S1_PUFFS = (bx: number, by: number, s: number) => {
  const ex = yachtPoint(bx, by, s, 0, [-276, -14]);
  return makePuffs([
    { at: CUE.engine, n: 3, x: ex[0], y: ex[1] },
    { at: CUE.engine + 9, n: 3, x: ex[0], y: ex[1] },
    { at: CUE.engine + 18, n: 4, x: ex[0], y: ex[1] },
    { at: CUE.died, n: 7, x: ex[0], y: ex[1], power: 1.6 },
  ]);
};
const S1_CAM: CamKey[] = [
  [0, 540, 1130, 1, -60, 0],
  [200, 540, 1160, 1, 300, 0],
  [252, 540, 700, 1, 230, 0], // crane up into the sky → chart
];
export const S1: React.FC<SceneProps> = ({ f, push }) => {
  const s = 1.15, bx = 540;
  const m0 = boatMotion(f, S1_KICKS, 1);
  // storm swell: big slow roll + heave on top of the kicks
  const mo = { r: m0.r * 1.8 + Math.sin(f * 0.045) * 6, y: m0.y * 1.6 + Math.sin(f * 0.05 + 1) * 26 };
  const by = 1236 + mo.y;
  const lights = Math.min(flicker(f, CUE.engine - 4, CUE.died + 4, 3), 1 - lin(f, CUE.died + 2, CUE.died + 6)) || (f > CUE.noLights - 4 && f < CUE.noLights + 2 ? 1 : 0);
  const emerge = seg(f, CUE.noLights - 14, CUE.noLights + 6);
  const panic = f >= CUE.noLights && f < CUE.nothing + 10;
  const sh = shake(f, CUE.died, 22, 24);
  const c0 = camera(f, S1_CAM, push, sh);
  // the camera rides the same swell, a beat behind the boat: extreme, never still
  const cam = { ...c0, roll: c0.roll + Math.sin(f * 0.045 - 0.6) * 4.5, y: c0.y + Math.sin(f * 0.05 + 0.4) * 34 };
  const front: P[] = Array.from({ length: 30 }, (_, i) => {
    const x = -900 + i * 100;
    return [x, by + 4 + Math.sin(x * 0.012 + f * 0.12) * 16] as P;
  });
  return (
    <SceneView cam={cam} light={NIGHT(700, 600)} sea={{ horizon: 1010, z: 300, moon: [820, 760], moonZ: 2200, moonR: 54, chop: 1.5, heave: Math.sin(f * 0.05 + 0.4) * 1.6, splash: f >= CUE.died ? (f - CUE.died) / 30 : -1, wet: 0.25, front: { z: 0, pts: [...front, [2000, 4000], [-900, 4000]] } }}
      layers={[
        { z: 1000, node: <Island cx={190} base={1012} w={420} h={110} f={f} seed={3} reef={false} /> },
        { z: 0, node: (
          <g>
            <Smoke puffs={S1_PUFFS(bx, by, s)} f={f} />
            <Yacht x={bx} y={by} s={s} r={mo.r} f={f} lights={lights} hatch={seg(f, CUE.noLights - 22, CUE.noLights - 10)}>
              <HatchHero bx={bx} by={by} bs={s} br={mo.r} emerge={emerge} s={0.3} arms={panic ? "up" : "rim"}
                pose={{ expr: panic ? "scared" : "surprised", blink: f > CUE.nothing + 2 && f < CUE.nothing + 7 ? 1 : 0, look: [0, -0.2] }} />
            </Yacht>
          </g>
        ) },
      ]}
      fx={[{ z: 0, node: <YachtGlow x={bx} y={by} s={s} r={mo.r} lights={lights} /> }]}
    />
  );
};

// ---------------------------------------------------------------------------
// S02 · chart from real geodata (OpenStreetMap coastline) · drift line · 5 nm zone to scale
// ---------------------------------------------------------------------------
const PXKM = 50; // map scale: 50 px per km
const ISL: P = [540, 900];
const K = (q: number[]): P => [ISL[0] + q[0] * PXKM, ISL[1] + q[1] * PXKM];
const COAST: P[] = (GEO.coast as number[][]).map(K);
const off = (km: number): P[] => (GEO.coast as number[][]).map(([x, y]) => { const d = Math.hypot(x, y) || 1; return K([x * (1 + km / d), y * (1 + km / d)]); });
const ZONE_KM = 5 * GEO.kmPerNm; // 9.26 km beyond the shore
const ZONE = off(ZONE_KM);
const REEF = off(0.7);
const DRIFT: P[] = qcurve(K([9.5, 12.5]), K([9.5, 4.5]), K([4.25, 1.6]), 60);
const along = (t: number): P => DRIFT[Math.max(0, Math.min(DRIFT.length - 1, Math.round(t * (DRIFT.length - 1))))];
const S2_CAM: CamKey[] = [
  [226, K([9.5, 12.5])[0], K([9.5, 12.5])[1], 2.3, 0, 0],
  [300, K([8, 8])[0], K([8, 8])[1], 1.2, 0, -2],
  [CUE.touch, 560, 930, 0.62, 0, 0],
  [CUE.sentinel + 12, 560, 1010, 1.4, 0, 0],
  [462, 600, 960, 2.8, 0, 0], // push through the treeline → shore
];
const latLabel = (lat: number) => `${Math.floor(lat)}°${String(Math.round((lat % 1) * 60)).padStart(2, "0")}′N`;
const lonLabel = (lon: number) => `${Math.floor(lon)}°${String(Math.round((lon % 1) * 60)).padStart(2, "0")}′E`;
export const S2: React.FC<SceneProps> = ({ f, push }) => {
  const cam = camera(f, S2_CAM, push);
  const draw = seg(f, CUE.dragging - 6, CUE.touch);
  const boatT = seg(f, CUE.current, CUE.touch + 10) * 0.985;
  const bp = along(boatT), bn = along(Math.min(1, boatT + 0.02));
  const ang = (Math.atan2(bn[1] - bp[1], bn[0] - bp[0]) * 180) / Math.PI;
  const zone = seg(f, CUE.island - 14, CUE.touch - 4);
  const shown = Math.max(2, Math.round(draw * DRIFT.length));
  const [lat0, lon0] = GEO.centre as number[];
  const kx = Math.cos((lat0 * Math.PI) / 180) * 111.32;
  // graticule every 2 arc-minutes
  const lats = Array.from({ length: 16 }, (_, i) => 11.4 + i / 30), lons = Array.from({ length: 16 }, (_, i) => 92.1 + i / 30);
  const yOf = (lat: number) => ISL[1] - (lat - lat0) * 110.57 * PXKM, xOf = (lon: number) => ISL[0] + (lon - lon0) * kx * PXKM;
  const zonePath = "M" + ZONE.map((q) => q.join(",")).join("L") + "Z";
  const pb = rot([0, -1], GEO.portBlairBearingDeg); // bearing → screen direction
  const pbAt: P = [ISL[0] + pb[0] * 760, ISL[1] + pb[1] * 760];
  return (
    <SceneView cam={cam} light={NIGHT(540, 300, 0.1)} bg="#0b1430"
      layers={[
        { z: 0, node: (
          <g>
            <rect x={-2400} y={-1800} width={5900} height={5600} fill="#0c1533" />
            {lats.map((la, i) => <g key={`la${i}`}><line x1={-2400} x2={3500} y1={yOf(la)} y2={yOf(la)} stroke="#17224b" strokeWidth={2} /><text x={-60} y={yOf(la) - 8} fontFamily={SANS} fontSize={22} fontWeight={500} fill="#3f5296" letterSpacing="0.1em">{latLabel(la)}</text></g>)}
            {lons.map((lo, i) => <g key={`lo${i}`}><line y1={-1800} y2={3800} x1={xOf(lo)} x2={xOf(lo)} stroke="#17224b" strokeWidth={2} /><text x={xOf(lo) + 8} y={1980} fontFamily={SANS} fontSize={22} fontWeight={500} fill="#3f5296" letterSpacing="0.1em">{lonLabel(lo)}</text></g>)}
            {[2.5, 5, 7.5].map((km, i) => <path key={i} d={"M" + off(km).map((q) => q.join(",")).join("L") + "Z"} fill="none" stroke="#1d2a5e" strokeWidth={2.5} />)}
            {/* 5 nm protected zone, to scale, filling in as it's named */}
            <path d={zonePath} fill="#386AD9" opacity={0.08 * zone} />
            <path d={zonePath} fill="none" stroke="#5b8bff" strokeWidth={7} strokeDasharray="26 18" opacity={zone} strokeDashoffset={-f * 1.2} />
            <text x={ISL[0]} y={ISL[1] - 9.26 * PXKM - 4.4 * PXKM - 26} fontFamily={SANS} fontWeight={700} fontSize={34} letterSpacing="0.16em" fill="#8fb0ff" textAnchor="middle" opacity={zone}>5 NM PROTECTED ZONE</text>
            {/* fringing reef + the real coastline */}
            <path d={"M" + REEF.map((q) => q.join(",")).join("L") + "Z"} fill="#162a52" stroke="#c9d6ff" strokeWidth={4} strokeDasharray="10 8" opacity={0.75} strokeDashoffset={-f * 0.6} />
            <Shape pts={COAST} mat={{ base: "#24432f", shade: "#183022", lit: "#36604a", line: "#0f1f16" }} ink={4} seed={6} shade={0.06} lit={0.08} lightFrom={[300, 300]} round={0} wob={0}>
              {Array.from({ length: 70 }, (_, i) => { const g = rng(`tree${i}`); return <circle key={i} cx={ISL[0] + rr(g, -190, 190)} cy={ISL[1] + rr(g, -220, 220)} r={rr(g, 12, 24)} fill="#2e5340" stroke="#12241a" strokeWidth={2} />; })}
            </Shape>
            <path d={"M" + COAST.map((q) => q.join(",")).join("L") + "Z"} fill="none" stroke="#b9b49e" strokeWidth={6} opacity={0.75} />
            {/* the Primrose wreck (approximate reported position) */}
            <g opacity={zone}>
              <path d={`M ${K(GEO.primroseApprox)[0] - 12},${K(GEO.primroseApprox)[1] - 12} l 24,24 m 0,-24 l -24,24`} stroke="#ff6b57" strokeWidth={5} strokeLinecap="round" />
              <text x={K(GEO.primroseApprox)[0] + 22} y={K(GEO.primroseApprox)[1] - 20} fontFamily={SANS} fontSize={22} fontWeight={700} fill="#ff8a78" textAnchor="start" letterSpacing="0.08em">PRIMROSE WRECK · 1981</text>
            </g>
            {/* Port Blair bearing */}
            <g opacity={zone}>
              <line x1={pbAt[0] - pb[0] * 80} y1={pbAt[1] - pb[1] * 80} x2={pbAt[0]} y2={pbAt[1]} stroke="#6f84c9" strokeWidth={4} />
              <path d={`M ${pbAt[0]},${pbAt[1]} l ${-pb[0] * 18 - pb[1] * 10},${-pb[1] * 18 + pb[0] * 10} l ${pb[1] * 20},${-pb[0] * 20} Z`} fill="#6f84c9" />
              <text x={pbAt[0] - 10} y={pbAt[1] - 22} fontFamily={SANS} fontSize={22} fontWeight={700} fill="#6f84c9" textAnchor="end" letterSpacing="0.08em">PORT BLAIR ~{GEO.portBlairKm} KM</text>
            </g>
            {/* north arrow + 2 km scale bar */}
            <g transform={`translate(${ISL[0] + 560},${ISL[1] - 720})`} opacity={0.85}>
              <path d="M 0,-44 L 14,10 L 0,0 L -14,10 Z" fill="#8fb0ff" /><text x={0} y={-54} textAnchor="middle" fontFamily={SANS} fontWeight={700} fontSize={24} fill="#8fb0ff">N</text>
            </g>
            <g transform={`translate(${ISL[0] - 620},${ISL[1] + 700})`} opacity={0.85}>
              <rect x={0} y={0} width={2 * PXKM} height={10} fill="#8fb0ff" /><rect x={2 * PXKM} y={0} width={2 * PXKM} height={10} fill="none" stroke="#8fb0ff" strokeWidth={2} />
              <text x={0} y={-12} fontFamily={SANS} fontSize={22} fontWeight={700} fill="#8fb0ff">0</text><text x={4 * PXKM} y={-12} fontFamily={SANS} fontSize={22} fontWeight={700} fill="#8fb0ff" textAnchor="middle">4 km</text>
            </g>
            <text x={ISL[0] + 620} y={ISL[1] + 1000} fontFamily={SANS} fontSize={18} fill="#3f5296" textAnchor="end">coastline © OpenStreetMap contributors (ODbL)</text>
            {/* drift line (P04/P05: one cobalt line that grows with the narration) */}
            <path d={"M" + DRIFT.slice(0, shown).map((q) => q.join(",")).join("L")} fill="none" stroke="#5b8bff" strokeWidth={9} strokeLinecap="round" strokeLinejoin="round" />
            <circle cx={DRIFT[0][0]} cy={DRIFT[0][1]} r={12} fill="#0c1533" stroke="#5b8bff" strokeWidth={6} />
            {f > CUE.touch && <circle cx={DRIFT[DRIFT.length - 1][0]} cy={DRIFT[DRIFT.length - 1][1]} r={18 + 30 * lin(f, CUE.touch, CUE.touch + 20)} fill="none" stroke="#ff6b57" strokeWidth={5} opacity={1 - lin(f, CUE.touch, CUE.touch + 20)} />}
            <g transform={`translate(${bp[0]},${bp[1]}) rotate(${ang + 90})`}>
              <ellipse cx={0} cy={18} rx={40} ry={10} fill="#5b8bff" opacity={0.25} />
              <Shape pts={[[0, -40], [16, -14], [16, 30], [-16, 30], [-16, -14]]} mat={{ base: "#eef1f6", shade: "#b9c3d8", lit: "#fff", line: "#9aa6c2" }} ink={4} seed={7} shade={0.1} lit={0.1} round={0.6} />
              <Shape pts={[[0, -16], [9, -2], [9, 16], [-9, 16], [-9, -2]]} mat={{ base: "#2c4a8a", shade: "#1d3366", lit: "#3f62ad", line: "#16264d" }} ink={3} seed={8} shade={0} lit={0} round={0.5} />
            </g>
          </g>
        ) },
      ]}
    />
  );
};

// ---------------------------------------------------------------------------
// S03 · the tree line at night · fires appear one by one · flare on "hard"
// ---------------------------------------------------------------------------
const FIRES = [
  { x: 380, y: 1080, at: CUE.people + 6 },
  { x: 720, y: 1060, at: CUE.contact },
  { x: 560, y: 1110, at: CUE.thousands - 6 },
  { x: 900, y: 1100, at: CUE.thousands + 20 },
  { x: 220, y: 1120, at: CUE.defend - 4 },
  { x: 1060, y: 1080, at: CUE.defend + 6 },
];
const S3_CAM: CamKey[] = [
  [440, 380, 1000, 1, 180, 0],
  [630, 700, 1040, 1, 300, 0],
  [680, 760, 1120, 1, 360, 0],
];
export const S3: React.FC<SceneProps> = ({ f, push }) => {
  const flare = 1 + 0.5 * seg(f, CUE.hard - 4, CUE.hard + 4) - 0.2 * seg(f, CUE.hard + 4, CUE.hard + 24);
  const fires = FIRES.map((fi) => ({ x: fi.x, y: fi.y, on: seg(f, fi.at - 3, fi.at + 8) * flare, s: 2.6 }));
  const cam = camera(f, S3_CAM, push, shake(f, CUE.hard, 6, 14));
  return (
    <SceneView cam={cam} light={NIGHT(660, 420, 0.2)}
      layers={[
        { z: 1800, node: <Sky x0={-1100} y0={-900} w={3300} h={2400} horizon={1230} moon={[840, 680]} moonR={56} f={f} seed={2} /> },
        { z: 300, node: <Island cx={560} base={1220} w={2600} h={560} f={f} seed={7} fires={fires} /> },
        { z: 200, node: <Sea x0={-1200} w={3400} horizon={1290} bottom={2800} f={f} glitterX={840} seed={3} /> },
        { z: -160, node: <Waterline x0={-1200} x1={2400} y={1780} depth={600} f={f} amp={14} seed={4} /> },
      ]}
      fx={[{ z: 300, node: <g>{fires.map((fi, i) => fi.on > 0 && <FireGlow key={i} x={fi.x} y={fi.y - 30} r={170 * Math.min(1.5, fi.on)} o={0.45 * Math.min(1, fi.on)} />)}</g> }]}
    />
  );
};

// ---------------------------------------------------------------------------
// S04 · CRUNCH on the reef · tilt · foam burst · the hero shrugs
// ---------------------------------------------------------------------------
const S4_CAM: CamKey[] = [
  [658, 470, 1060, 1, 120, 0],
  [700, 540, 1120, 1, 200, 0],
  [840, 560, 1080, 1, 330, 0],
];
export const S4: React.FC<SceneProps> = ({ f, push }) => {
  const s = 1.05;
  const glide = seg(f, 640, CUE.crunch);
  const bx = 260 + 280 * glide;
  const tilt = -7 * seg(f, CUE.crunch, CUE.crunch + 6);
  const mo = boatMotion(f, [{ at: CUE.crunch, pitch: -6, heave: 14 }], f < CUE.crunch ? 1 : 0.25);
  const by = 1250 + mo.y - 10 * seg(f, CUE.crunch, CUE.crunch + 6);
  const r = mo.r + tilt;
  const emerge = seg(f, CUE.reef - 8, CUE.stuck);
  const shrug = f >= CUE.actuallyDo - 10;
  const sh = shake(f, CUE.crunch, 26, 26);
  const cam = camera(f, S4_CAM, push, sh);
  const bow = yachtPoint(bx, by, s, r, [250, 20]);
  const g = rng("foam");
  const foam = Array.from({ length: 16 }, (_, i) => {
    const a = (f - CUE.crunch) / 30;
    if (a < 0 || a > 1.1) return null;
    const vx = rr(g, -260, 300), vy = rr(g, -520, -220);
    const x = bow[0] + vx * a, y = bow[1] + vy * a + 900 * a * a;
    const rad = rr(g, 6, 16) * (1 - a * 0.6);
    return <circle key={i} cx={x} cy={y} r={rad} fill="#e8eeff" stroke="#0b1230" strokeWidth={2} opacity={1 - a * 0.8} />;
  });
  const rocks: P[][] = [[bow[0] - 40, by + 40], [bow[0] + 90, by + 30], [bow[0] + 210, by + 48]].map(([x, y], i) => ellipse(x, y, 60 - i * 8, 26, 14).map((p) => add(p, [0, -6])));
  return (
    <SceneView cam={cam} light={NIGHT(680, 520)}
      layers={[
        { z: 1800, node: <Sky x0={-1100} y0={-900} w={3300} h={2400} horizon={1060} moon={[840, 780]} moonR={50} f={f} seed={4} /> },
        { z: 700, node: <Island cx={560} base={1060} w={2200} h={460} f={f} seed={9} fires={FIRES.map((fi) => ({ x: fi.x * 0.9 + 60, y: 1000 - (1100 - fi.y) * 0.5, on: 0.8, s: 1.1 }))} /> },
        { z: 300, node: <Sea x0={-1200} w={3400} horizon={1110} bottom={2800} f={f} glitterX={840} seed={5} /> },
        { z: 0, node: (
          <g>
            {rocks.map((rk, i) => <Shape key={i} pts={rk} mat={{ base: "#2a3046", shade: "#1b2032", lit: "#40486a", line: "#121625" }} ink={4} seed={30 + i} shade={0.2} lit={0.15} />)}
            <Yacht x={bx} y={by} s={s} r={r} f={f} lights={0} hatch={seg(f, CUE.reef - 14, CUE.reef - 4)}>
              <HatchHero bx={bx} by={by} bs={s} br={r} emerge={emerge} s={0.3} arms={shrug ? "shrug" : "rim"}
                pose={{ expr: shrug ? "worried" : "scared", look: shrug ? [0, 0] : [0.5, -0.4], blink: f > CUE.stuck + 20 && f < CUE.stuck + 25 ? 1 : 0 }} />
            </Yacht>
            <Waterline x0={-1200} x1={2400} y={by + 22} depth={60} f={f} />
            <Sea x0={-1200} w={3400} horizon={by + 64} bottom={2800} f={f} edge={false} rows={10} tint={0.25} seed={6} />
            {foam}
            {f >= CUE.crunch && f < CUE.crunch + 10 && <path d={`M ${bow[0] - 30},${bow[1] - 40} l 40,-60 l 10,50 l 50,-30 l -20,50 l 60,10`} fill="none" stroke="#fff6d8" strokeWidth={8} strokeLinejoin="round" opacity={1 - (f - CUE.crunch) / 10} />}
          </g>
        ) },
      ]}
    />
  );
};

export const _q = Line;
