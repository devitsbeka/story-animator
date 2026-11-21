import React from "react";
import { CamKey } from "../../kit/engine";
import { P, add, rng, rr } from "../../kit/geom";
import { Line, Shape } from "../../kit/render";
import { Beacon, CargoShip, CoastGuardShip, Germ, Helicopter, Island, Radio, Sea, Sky, Waterline, Yacht, yachtPoint } from "../../kit/sea";
import { INK } from "../../kit/theme";
import { SANS, SERIF } from "../../kit/type";
import { CUE } from "./cues";
import { HatchHero, NIGHT, SceneView, boatMotion, camera, heroPt, lin, pop, seg } from "./harness";
import type { SceneProps } from "./scenesA";

// Rings of radio signal rising from a point (P04 grammar: thin cobalt line, timed to speech)
const Rings: React.FC<{ x: number; y: number; f: number; from: number; to: number; every?: number; maxR?: number }> = ({ x, y, f, from, to, every = 12, maxR = 900 }) => {
  const out: React.ReactNode[] = [];
  for (let s = from; s < to; s += every) {
    const a = (f - s) / 50;
    if (a < 0 || a > 1) continue;
    const r = 40 + a * maxR;
    out.push(<path key={s} d={`M ${x - r * 0.8},${y - r * 0.35} Q ${x},${y - r * 0.95} ${x + r * 0.8},${y - r * 0.35}`} fill="none" stroke="#7da2ff" strokeWidth={6 * (1 - a) + 2} opacity={1 - a} strokeLinecap="round" />);
  }
  return <g>{out}</g>;
};

// ---------------------------------------------------------------------------
// S05 · MAYDAY · close on the hero with the radio → pull back to the rescue
// ---------------------------------------------------------------------------
const S5_CAM: CamKey[] = [
  [820, 556, 930, 1, 600, 0],
  [CUE.mayday, 556, 940, 1, 660, 0],
  [CUE.radio + 30, 570, 980, 1, 480, 0],
  [CUE.beacon, 570, 1020, 1, 260, 0],
  [CUE.coastGuard + 40, 540, 960, 1, -40, 0],
  [1095, 540, 1000, 1, -120, 0],
];
export const S5: React.FC<SceneProps> = ({ f, push }) => {
  const s = 1.2, bx = 540;
  const mo = boatMotion(f, [], 0.6);
  const by = 1300 + mo.y;
  const r = -5 + mo.r * 0.5;
  const head = yachtPoint(bx, by, s, r, [0, -184]);
  const hs = 0.4 * s;
  const shout = f >= CUE.mayday - 2 && f < CUE.mayday + 14;
  const talk = f > CUE.radio - 6 && f < CUE.beacon + 10 && Math.sin(f * 0.9) > 0;
  const radioHand: P = add(heroPt(bx, by, s, r, 0.4, [168, -206]), [0, Math.sin(f * 0.4) * 2]);
  const beaconOn = pop(f, CUE.beacon - 4, 10);
  const cam = camera(f, S5_CAM, push);
  const cg = pop(f, CUE.coastGuard - 6, 14);
  return (
    <SceneView cam={cam} light={NIGHT(760, 520)}
      layers={[
        { z: 1800, node: <Sky x0={-1300} y0={-1400} w={3700} h={3000} horizon={1080} moon={[840, 780]} moonR={46} f={f} seed={6} /> },
        { z: 900, node: (
          <g>
            {cg > 0 && <g opacity={Math.min(1, cg)}><CoastGuardShip x={880} y={1074} s={0.45 * cg} f={f} /></g>}
            {cg > 0 && <g opacity={Math.min(1, cg)}><Helicopter x={250 + (f - CUE.coastGuard) * 1.2} y={640} s={0.42 * cg} f={f} /></g>}
          </g>
        ) },
        { z: 300, node: <Sea x0={-1300} w={3700} horizon={1080} bottom={2900} f={f} glitterX={840} seed={7} /> },
        { z: 0, node: (
          <g>
            <Rings x={radioHand[0]} y={radioHand[1] - 80} f={f} from={CUE.mayday} to={CUE.coastGuard + 30} />
            <Yacht x={bx} y={by} s={s} r={r} f={f} lights={0} hatch={1}>
              <HatchHero bx={bx} by={by} bs={s} br={r} emerge={1} s={0.4} arms="custom"
                pose={{ handR: radioHand, handL: yachtPoint(bx, by, s, r, [-52, -192]), handPoseR: "grip", handPoseL: "fist", handAbsR: -12,
                  expr: shout ? "shout" : talk ? { browDown: 0.5, jaw: 0.45, lidTight: 0.2 } : f < CUE.mayday ? "surprised" : "determined", look: [0.6, -0.3], faceX: -10 }} />
              <Radio x={radioHand[0] + 4} y={radioHand[1] - 34 * hs} s={0.36} r={-10} f={f} tx={shout || talk ? 1 : 0} />
            </Yacht>
            {beaconOn > 0 && <Beacon x={yachtPoint(bx, by, s, r, [120, -180])[0]} y={yachtPoint(bx, by, s, r, [120, -180])[1]} s={0.5 * beaconOn} f={f} />}
            <Waterline x0={-1300} x1={2400} y={by + 22} depth={60} f={f} />
            <Sea x0={-1300} w={3700} horizon={by + 64} bottom={2900} f={f} edge={false} rows={10} tint={0.25} seed={8} />
          </g>
        ) },
      ]}
      fx={[
        { z: 0, node: beaconOn > 0 && f % 24 < 4 ? <circle cx={yachtPoint(bx, by, s, r, [120, -262])[0]} cy={yachtPoint(bx, by, s, r, [120, -262])[1]} r={180} fill="#dfe8ff" opacity={0.5} /> : null },
        { z: 0, node: (shout || talk) ? <circle cx={radioHand[0]} cy={radioHand[1] - 40} r={60} fill="#a8e07a" opacity={0.18} /> : null },
      ]}
    />
  );
};

// ---------------------------------------------------------------------------
// S06 · step two: do NOT go ashore · footprints blocked · germs stopped
// ---------------------------------------------------------------------------
const S6_CAM: CamKey[] = [
  [1075, 540, 1200, 1.15, 0, 0],
  [CUE.ashore, 560, 900, 1.05, 0, 0],
  [CUE.photo + 10, 520, 1180, 1.25, 120, 0],
  [CUE.germs, 540, 1220, 1.25, 160, 0],
  [CUE.deadly + 6, 560, 860, 1.1, 60, 0],
  [1398, 540, 760, 1.1, 120, 0],
];
const BARRIER_Y = 820;
export const S6: React.FC<SceneProps> = ({ f, push }) => {
  const s = 0.95, bx = 540;
  const mo = boatMotion(f, [], 0.3);
  const by = 1380 + mo.y;
  const r = -6 + mo.r * 0.3;
  const cam = camera(f, S6_CAM, push);
  const steps = Array.from({ length: 10 }, (_, i) => {
    const t = i / 9;
    const x = 600 + Math.sin(t * 3) * 60 + (i % 2 ? 18 : -18), y = 1200 - t * 640;
    const vis = lin(f, CUE.step2 - 4 + i * 3, CUE.step2 + i * 3);
    const cut = y < BARRIER_Y + 30 ? 1 - lin(f, CUE.ashore - 20, CUE.ashore - 10) : 1;
    return { x, y, o: vis * cut };
  });
  const barrier = seg(f, CUE.ashore - 22, CUE.ashore - 6);
  const wave = f >= CUE.sayHi - 6 && f < CUE.sayHi + 14;
  const photo = f >= CUE.photo - 6 && f < CUE.sayHi - 8;
  const sneeze = f >= CUE.germs - 8 && f < CUE.germs + 6;
  const head = yachtPoint(bx, by, s, r, [0, -184]);
  const hs = 0.34 * s;
  const mouth: P = heroPt(bx, by, s, r, 0.34, [-33, -218]);
  const germs = Array.from({ length: 7 }, (_, i) => {
    const g = rng(`gm${i}`);
    const t0 = CUE.germs - 2 + i * 2;
    const a = Math.max(0, (f - t0) / 30);
    if (f < t0) return null;
    const tx = rr(g, 380, 720), ty = BARRIER_Y + 70 + rr(g, -10, 30);
    const k = Math.min(1, a / 1.3);
    const ee = 1 - Math.pow(1 - k, 3);
    const bounce = Math.max(0, a - 1.3);
    const x = mouth[0] + (tx - mouth[0]) * ee + Math.sin(f * 0.2 + i) * 6;
    const y = mouth[1] + (ty - mouth[1]) * ee + Math.sin(bounce * 10) * 10 * Math.exp(-bounce * 3);
    return { x, y, r: rr(g, 20, 30), i };
  }).filter(Boolean) as { x: number; y: number; r: number; i: number }[];
  const danger = seg(f, CUE.deadly - 4, CUE.deadly + 6);
  return (
    <SceneView cam={cam} light={NIGHT(640, 300)}
      layers={[
        { z: 1600, node: <Sky x0={-1300} y0={-1400} w={3700} h={3000} horizon={520} moon={[840, 460]} moonR={42} f={f} seed={8} /> },
        { z: 200, node: (
          <g>
            <Island cx={600} base={640} w={2400} h={360} f={f} seed={11} fires={[{ x: 420, y: 600, on: 0.9, s: 1.2 }, { x: 820, y: 590, on: 0.9, s: 1.2 }]} />
          </g>
        ) },
        { z: 100, node: <Sea x0={-1300} w={3700} horizon={760} bottom={2900} f={f} glitterX={840} seed={9} /> },
        { z: 0, node: (
          <g>
            {steps.length > 1 && <path d={"M" + steps.filter((st) => st.o > 0).map((st) => `${st.x},${st.y}`).join("L")} fill="none" stroke="#dfe6ff" strokeWidth={7} strokeDasharray="4 18" strokeLinecap="round" opacity={0.85} />}
            {steps.map((st, i) => i === steps.length - 1 && st.o > 0 && <path key={i} d={`M ${st.x - 18},${st.y + 14} L ${st.x},${st.y - 8} L ${st.x + 18},${st.y + 14}`} fill="none" stroke="#dfe6ff" strokeWidth={7} strokeLinecap="round" strokeLinejoin="round" opacity={st.o} />)}
            {f >= CUE.ashore - 8 && <g transform={`translate(${steps[6].x},${BARRIER_Y - 26})`} opacity={lin(f, CUE.ashore - 8, CUE.ashore)}><circle r={38} fill="#ff6b57" stroke="#140805" strokeWidth={5} /><path d="M -16,-16 L 16,16 M 16,-16 L -16,16" stroke="#fff" strokeWidth={8} strokeLinecap="round" /></g>}
            {/* the barrier: one cobalt line across the path, then a protective arc */}
            <path d={`M ${-200},${BARRIER_Y} Q ${540},${BARRIER_Y - 60} ${1280},${BARRIER_Y}`} fill="none" stroke={danger > 0 ? "#ff6b57" : "#5b8bff"} strokeWidth={12} strokeLinecap="round" strokeDasharray="2400" strokeDashoffset={2400 * (1 - barrier)} />
            <Yacht x={bx} y={by} s={s} r={r} f={f} lights={0} hatch={1}>
              <HatchHero bx={bx} by={by} bs={s} br={r} emerge={1} s={0.34} arms={wave || photo ? "custom" : "rim"}
                pose={{
                  ...(wave ? { handR: add(heroPt(bx, by, s, r, 0.34, [200, -330]), [Math.sin(f * 0.9) * 8, 0]), handPoseR: "wave" as const, handAbsR: 12 + Math.sin(f * 0.9) * 14, handL: yachtPoint(bx, by, s, r, [-52, -192]), handPoseL: "fist" as const } : {}),
                  ...(photo ? { handR: heroPt(bx, by, s, r, 0.34, [190, -300]), handPoseR: "grip" as const, handAbsR: 0, handL: yachtPoint(bx, by, s, r, [-52, -192]), handPoseL: "fist" as const } : {}),
                  expr: sneeze ? "sneeze" : wave ? "happy" : f > CUE.deadly - 6 ? "scared" : "worried",
                  blink: sneeze ? 1 : 0, look: [0.2, -0.8], headTilt: sneeze ? 10 * Math.sin(((f - CUE.germs + 8) / 14) * Math.PI) : 0,
                }} />
              {photo && (
                <g>
                  <Shape pts={[[0, 0], [52, 0], [52, 92], [0, 92]].map((p) => add(add(heroPt(bx, by, s, r, 0.34, [190, -300]), [-26, -118]), p as P))} mat={{ base: "#3b3533", shade: "#262120", lit: "#5b5350", line: "#1c1817" }} ink={4} round={0.4} seed={60} shade={0.1} lit={0.1} />
                </g>
              )}
            </Yacht>
            <Waterline x0={-1300} x1={2400} y={by + 20} depth={60} f={f} />
            <Sea x0={-1300} w={3700} horizon={by + 60} bottom={2900} f={f} edge={false} rows={10} tint={0.25} seed={10} />
            {germs.map((gm) => <g key={gm.i} style={{ filter: danger > 0 ? `hue-rotate(${-100 * danger}deg) saturate(${1 + danger})` : undefined }}><Germ x={gm.x} y={gm.y} r={gm.r} f={f} seed={gm.i} /></g>)}
            {/* "photo" and "say hi" get struck through, in the same cobalt as the barrier */}
            {f >= CUE.photo + 4 && f < CUE.sayHi - 8 && <Line pts={[heroPt(bx, by, s, r, 0.34, [110, -430]), heroPt(bx, by, s, r, 0.34, [280, -200])]} w={10} color="#5b8bff" wob={0} />}
            {f >= CUE.sayHi + 8 && f < CUE.immunity - 8 && <Line pts={[heroPt(bx, by, s, r, 0.34, [120, -460]), heroPt(bx, by, s, r, 0.34, [300, -230])]} w={10} color="#5b8bff" wob={0} />}
          </g>
        ) },
      ]}
      fx={[{ z: 0, node: photo && f >= CUE.photo - 2 && f < CUE.photo + 3 ? <circle cx={heroPt(bx, by, s, r, 0.34, [190, -360])[0]} cy={heroPt(bx, by, s, r, 0.34, [190, -360])[1]} r={240} fill="#ffffff" opacity={0.7} /> : null }]}
    />
  );
};

// ---------------------------------------------------------------------------
// S07 · step three: stay with your boat · hug the mast · tilt up to the sky
// ---------------------------------------------------------------------------
const S7_CAM: CamKey[] = [
  [1378, 420, 1080, 1, 280, -1],
  [CUE.before - 20, 660, 1040, 1, 380, 1.2],
  [1530, 600, 520, 1, 300, 0],
];
export const S7: React.FC<SceneProps> = ({ f, push }) => {
  const s = 1.2, bx = 540;
  const mo = boatMotion(f, [], 0.3);
  const by = 1300 + mo.y;
  const r = -6 + mo.r * 0.3;
  const hug = seg(f, CUE.stayBoat - 14, CUE.stayBoat);
  const mast = (y: number) => yachtPoint(bx, by, s, r, [-33, y]);
  const rim = (x: number) => yachtPoint(bx, by, s, r, [x, -192]);
  const lerp = (a: P, b: P, t: number): P => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  const cam = camera(f, S7_CAM, push);
  return (
    <SceneView cam={cam} light={NIGHT(700, 500)}
      layers={[
        { z: 1800, node: <Sky x0={-1300} y0={-1400} w={3700} h={3000} horizon={1060} moon={[840, 760]} moonR={48} f={f} seed={9} /> },
        { z: 700, node: <Island cx={560} base={1060} w={2200} h={460} f={f} seed={9} fires={[{ x: 300, y: 1000, on: 0.8, s: 1.1 }, { x: 760, y: 990, on: 0.8, s: 1.1 }]} /> },
        { z: 300, node: <Sea x0={-1300} w={3700} horizon={1110} bottom={2900} f={f} glitterX={840} seed={11} /> },
        { z: 0, node: (
          <g>
            <Yacht x={bx} y={by} s={s} r={r} f={f} lights={0} hatch={1}>
              <HatchHero bx={bx} by={by} bs={s} br={r} emerge={1} s={0.36} arms="custom"
                pose={{ handL: lerp(rim(-46), mast(-236), hug), handR: lerp(rim(46), mast(-214), hug), handPoseL: hug > 0.5 ? "flat" : "fist", handPoseR: hug > 0.5 ? "flat" : "fist", handAngleL: hug > 0.5 ? 70 : 160, handAngleR: hug > 0.5 ? -110 : -160,
                  expr: f > CUE.before - 30 ? { browDown: 0.5, smile: 0.7, cheekUp: 0.3 } : "determined", look: [-0.4, -0.2], headTilt: -8 * hug }} />
            </Yacht>
            <Waterline x0={-1300} x1={2400} y={by + 22} depth={60} f={f} />
            <Sea x0={-1300} w={3700} horizon={by + 64} bottom={2900} f={f} edge={false} rows={10} tint={0.25} seed={12} />
          </g>
        ) },
      ]}
    />
  );
};

// ---------------------------------------------------------------------------
// S08 · 1981 · the Primrose aground · stayed inside · days pass · helicopters
// ---------------------------------------------------------------------------
const S8_CAM: CamKey[] = [
  [1510, 300, 1000, 1, 600, 0],
  [CUE.y1981 + 20, 340, 1020, 1, 520, 0],
  [CUE.aground, 560, 1060, 1, -60, 0],
  [CUE.steel, 420, 1040, 1, 160, 0],
  [CUE.helicopters, 480, 940, 1, 0, 0],
  [CUE.everySingle + 30, 360, 860, 1, 160, 0],
  [1938, 380, 700, 1, 300, 0],
];
export const S8: React.FC<SceneProps> = ({ f, push }) => {
  // time-lapse: three quick day/night cycles while they "waited for days"
  const tl = lin(f, CUE.stayed + 40, CUE.helicopters - 4);
  const dawn = tl > 0 && tl < 1 ? 0.5 - 0.5 * Math.cos(tl * Math.PI * 6) : 0;
  const cam = camera(f, S8_CAM, push);
  const shipX = 560, shipY = 1200, ss = 0.82;
  const port = seg(f, CUE.stayed - 4, CUE.steel + 10);
  const heliIn = seg(f, CUE.helicopters - 10, CUE.helicopters + 24);
  const deck: P = [shipX - 410 * ss, shipY - 330 * ss];
  const hx = 1400 + (deck[0] - 1400) * heliIn, hy = 260 + (deck[1] - 360 - 260) * heliIn;
  const rope = f > CUE.helicopters + 20 ? Math.min(330, (f - CUE.helicopters - 20) * 22) : 0;
  const crew = Array.from({ length: 5 }, (_, i) => {
    const t0 = CUE.everySingle - 18 + i * 9;
    const a = lin(f, t0, t0 + 16);
    return { a, i };
  });
  const fireFlare = 1 + 0.6 * seg(f, CUE.armed - 4, CUE.armed + 6);
  return (
    <SceneView cam={cam} light={NIGHT(760, 420)}
      layers={[
        { z: 1800, node: <Sky x0={-1300} y0={-1400} w={3700} h={3000} horizon={1020} moon={[840, 680]} moonR={46} f={f} dawn={dawn} seed={10} /> },
        { z: 600, node: <Island cx={560} base={1020} w={2300} h={420} f={f} seed={13} dawn={dawn} fires={[180, 420, 640, 880].map((x, i) => ({ x, y: 990 - (i % 2) * 14, on: (0.7 + 0.1 * i) * fireFlare * (1 - dawn * 0.7), s: 1.2 }))} /> },
        { z: 300, node: <Sea x0={-1300} w={3700} horizon={1070} bottom={2900} f={f} glitterX={840} seed={13} dawn={dawn} /> },
        { z: 0, node: (
          <g>
            <CargoShip x={shipX} y={shipY} s={ss} r={-4} f={f} portholes={port} />
            <text transform={`translate(${shipX + 260 * ss},${shipY - 70 * ss}) rotate(-4)`} fontFamily={SERIF} fontStyle="italic" fontWeight={800} fontSize={58} fill="#f1f3f7" opacity={lin(f, CUE.primrose - 6, CUE.primrose + 4)} textAnchor="middle">PRIMROSE</text>
            <Waterline x0={-1300} x1={2400} y={shipY + 10} depth={60} f={f} amp={6} dawn={dawn} />
            <Sea x0={-1300} w={3700} horizon={shipY + 50} bottom={2900} f={f} edge={false} rows={10} tint={0.25} seed={14} dawn={dawn} />
            {heliIn > 0 && (
              <g>
                {crew.map((c) => {
                  if (rope <= 0) return null;
                  const y = deck[1] - c.a * (deck[1] - (hy + 40));
                  if (c.a >= 1) return null;
                  return <g key={c.i}><circle cx={hx} cy={y - 16} r={14} fill="#fdf0d7" stroke={INK} strokeWidth={3} /><rect x={hx - 11} y={y - 2} width={22} height={24} rx={8} fill="#c1301e" stroke={INK} strokeWidth={3} /></g>;
                })}
                <Helicopter x={hx} y={hy} s={0.62} f={f} rope={rope} tilt={-6 * (1 - heliIn) - 2} />
                {heliIn > 0.6 && <Helicopter x={hx + 620 - (f - CUE.helicopters) * 0.8} y={hy - 190} s={0.38} f={f + 7} tilt={-4} />}
              </g>
            )}
          </g>
        ) },
      ]}
      fx={[{ z: 0, node: port > 0 ? <circle cx={shipX - 410 * ss} cy={shipY - 240 * ss} r={130 * port} fill="#ffc86a" opacity={0.25 * port} /> : null }]}
    />
  );
};

export const _unused = [SANS, rng, rr];
