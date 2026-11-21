import React from "react";
import { P, add, ellipse, lerpP, qcurve, rng, rot, rr, rrect, tube } from "./geom";
import { Contact, Line, Shape } from "./render";
import { INK, Material, WEIGHT } from "./theme";

// ============================================================================
// SEA KIT: night sky, ocean, island, yacht, smoke, fire, ships, rescue gear.
// Same renderer and ink as every other kit part, so episodes stay one hand.
// ============================================================================

const m = (base: string, shade: string, lit: string, line: string): Material => ({ base, shade, lit, line });
export const SM = {
  hull: m("#eef1f6", "#b9c3d8", "#ffffff", "#9aa6c2"),
  stripe: m("#2c4a8a", "#1d3366", "#3f62ad", "#16264d"),
  bottom: m("#b8393a", "#8c2628", "#d65252", "#6a1a1c"),
  deck: m("#c79a62", "#9f7444", "#e0b57c", "#7d5530"),
  glass: m("#1d2748", "#121a35", "#33416e", "#0c1226"),
  glassLit: m("#ffd98a", "#f3b45a", "#fff1c4", "#d08f35"),
  jungle: m("#122019", "#0b1510", "#28443a", "#07100b"),
  jungle2: m("#1a2d24", "#0f1c16", "#36584a", "#0b140f"),
  palm: m("#16261e", "#0c160f", "#2f4a3e", "#07100b"),
  sand: m("#5d6276", "#454a5d", "#7d8399", "#3a3e50"),
  rock: m("#2a3046", "#1b2032", "#40486a", "#121625"),
  smoke: m("#3b3d48", "#26272f", "#5c5f6e", "#1c1d24"),
  ship: m("#3b4a63", "#26324a", "#56688a", "#1a2335"),
  shipRust: m("#8a4a2e", "#6a321c", "#a86040", "#4a2212"),
  cgWhite: m("#f1f3f7", "#c3cad8", "#ffffff", "#9aa6c2"),
  cgRed: m("#d8432f", "#a92f20", "#ef6a4f", "#7a1f14"),
  beacon: m("#ffb21e", "#d98a0c", "#ffd36a", "#a3640a"),
  radio: m("#2b2f38", "#1b1e25", "#464c5a", "#121419"),
  lcd: m("#a8e07a", "#86c25c", "#c9f5a3", "#4f7a33"),
  germ: m("#7fd36b", "#58ad48", "#a7ee92", "#3f7e33"),
  orange: m("#ff8a2a", "#e06a10", "#ffb15e", "#b04f0a"),
  heli: m("#e8ecf2", "#b8c1d2", "#ffffff", "#8e9ab3"),
};

const place = (pts: P[], x: number, y: number, r = 0, s = 1): P[] => pts.map((p) => add(rot([p[0] * s, p[1] * s], r), [x, y]));
const lerpC = (a: string, b: string, t: number) => {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16)), pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return "#" + pa.map((v, i) => Math.round(v + (pb[i] - v) * t).toString(16).padStart(2, "0")).join("");
};

// ---------- sky ----------
export const Sky: React.FC<{ x0: number; y0: number; w: number; h: number; horizon: number; moon?: P; moonR?: number; f: number; dawn?: number; seed?: number }> = ({ x0, y0, w, h, horizon, moon, moonR = 70, f, dawn = 0, seed = 1 }) => {
  const g = rng(`sky${seed}`);
  const stars = Array.from({ length: 140 }, () => [rr(g, x0, x0 + w), rr(g, y0, horizon - 30), rr(g, 0.9, 2.6), rr(g, 0, 6.28)]);
  const top = lerpC("#060a1f", "#2a3a78", dawn), mid = lerpC("#141c45", "#c0708a", dawn), hor = lerpC("#2b3a74", "#ffb27a", dawn);
  return (
    <g>
      <defs>
        <linearGradient id={`skyG${seed}`} gradientUnits="userSpaceOnUse" x1="0" y1={y0} x2="0" y2={horizon}>
          <stop offset="0" stopColor={top} /><stop offset="0.65" stopColor={mid} /><stop offset="1" stopColor={hor} />
        </linearGradient>
        <radialGradient id={`moonGlow${seed}`}><stop offset="0" stopColor="#dfe8ff" stopOpacity="0.55" /><stop offset="0.3" stopColor="#b9c8ff" stopOpacity="0.18" /><stop offset="1" stopColor="#b9c8ff" stopOpacity="0" /></radialGradient>
      </defs>
      <rect x={x0} y={y0} width={w} height={horizon - y0 + 4} fill={`url(#skyG${seed})`} />
      {stars.map(([sx, sy, r, ph], i) => <circle key={i} cx={sx} cy={sy} r={r} fill="#fff6dc" opacity={(0.35 + 0.45 * (0.5 + 0.5 * Math.sin(f * 0.06 + ph))) * (1 - dawn)} />)}
      {moon && (
        <g opacity={1 - dawn * 0.8}>
          <circle cx={moon[0]} cy={moon[1]} r={moonR * 5} fill={`url(#moonGlow${seed})`} />
          <Shape pts={ellipse(moon[0], moon[1], moonR, moonR, 40)} mat={m("#fff6d8", "#eedca8", "#ffffff", "#d9c48a")} ink={0} shade={0.18} lit={0} lightFrom={[moon[0] - 200, moon[1] - 150]} seed={seed}>
            {[[-22, -10, 14], [18, 16, 10], [8, -28, 7], [-10, 26, 8]].map(([cx, cy, r], i) => <circle key={i} cx={moon[0] + cx} cy={moon[1] + cy} r={r} fill="#e9d6a0" opacity={0.6} />)}
          </Shape>
        </g>
      )}
      {/* low cloud bands lit from the moon */}
      {[0, 1, 2].map((i) => {
        const cy = y0 + (horizon - y0) * (0.35 + i * 0.17), cx = x0 + ((f * (0.25 + i * 0.1) + i * 400) % (w + 600)) - 300;
        const pts: P[] = [[cx - 160, cy], ...qcurve([cx - 120, cy - 30], [cx - 40, cy - 50], [cx + 20, cy - 26], 6), ...qcurve([cx + 60, cy - 46], [cx + 140, cy - 30], [cx + 170, cy], 6)];
        return <Shape key={i} pts={pts} mat={m(lerpC("#1c2654", "#e7a487", dawn), lerpC("#141c42", "#c98673", dawn), lerpC("#36427a", "#ffd3a8", dawn), "#0f1533")} ink={0} shade={0.12} lit={0.18} litOpacity={0.6} seed={seed + i} />;
      })}
    </g>
  );
};

// ---------- sea ----------
export const Sea: React.FC<{ x0: number; w: number; horizon: number; bottom: number; f: number; glitterX?: number; dawn?: number; seed?: number; rows?: number }> = ({ x0, w, horizon, bottom, f, glitterX, dawn = 0, seed = 1, rows = 26 }) => {
  const g = rng(`sea${seed}`);
  const deep = lerpC("#0b1230", "#2c3a6e", dawn), far = lerpC("#1f2b5c", "#9a7a9a", dawn);
  const lines: React.ReactNode[] = [];
  for (let i = 0; i < rows; i++) {
    const t = (i + 1) / rows; // 0 near horizon → 1 near camera
    const y = horizon + (bottom - horizon) * Math.pow(t, 1.8);
    const n = Math.round(3 + t * 6);
    for (let k = 0; k < n; k++) {
      const len = 30 + t * 140 + rr(g, -10, 20);
      const sx = x0 + ((rr(g, 0, w) + f * (0.4 + t * 1.4) * (i % 2 ? 1 : -1)) % w + w) % w;
      const amp = 2 + t * 7;
      const pts: P[] = [[sx, y], [sx + len * 0.5, y - amp], [sx + len, y]];
      lines.push(<Line key={`${i}-${k}`} pts={pts} w={1 + t * 3} color={lerpC("#3a4c8c", "#e8c8b8", dawn)} opacity={0.25 + t * 0.35} wob={0} />);
    }
  }
  const glit: React.ReactNode[] = [];
  if (glitterX !== undefined) {
    for (let i = 0; i < 60; i++) {
      const t = rr(g, 0, 1);
      const y = horizon + 6 + (bottom - horizon) * Math.pow(t, 1.6);
      const spread = 10 + t * 120;
      const x = glitterX + rr(g, -spread, spread);
      const L = 6 + t * 40;
      const tw = 0.5 + 0.5 * Math.sin(f * 0.25 + i * 2.1);
      glit.push(<rect key={i} x={x - L / 2} y={y} width={L} height={1.5 + t * 3} rx={2} fill="#fff4d4" opacity={tw * (0.4 + 0.5 * (1 - t))} />);
    }
  }
  return (
    <g>
      <defs>
        <linearGradient id={`seaG${seed}`} gradientUnits="userSpaceOnUse" x1="0" y1={horizon} x2="0" y2={bottom}>
          <stop offset="0" stopColor={far} /><stop offset="0.35" stopColor={lerpC("#16204a", "#5d5a86", dawn)} /><stop offset="1" stopColor={deep} />
        </linearGradient>
      </defs>
      <rect x={x0} y={horizon} width={w} height={bottom - horizon} fill={`url(#seaG${seed})`} />
      <Line pts={[[x0, horizon], [x0 + w, horizon]]} w={2.5} color={lerpC("#5468aa", "#ffd0a0", dawn)} opacity={0.8} wob={0} />
      {lines}
      {glit}
    </g>
  );
};

// A strip of water with a wavy top edge, drawn in front of a hull to sink it in the sea.
export const Waterline: React.FC<{ x0: number; x1: number; y: number; depth: number; f: number; amp?: number; dawn?: number; seed?: number; foam?: boolean }> = ({ x0, x1, y, depth, f, amp = 8, dawn = 0, seed = 1, foam = true }) => {
  const pts: P[] = [];
  for (let x = x0; x <= x1; x += 16) pts.push([x, y + Math.sin(x * 0.02 + f * 0.12 + seed) * amp + Math.sin(x * 0.047 - f * 0.08) * amp * 0.4]);
  const body: P[] = [...pts, [x1, y + depth], [x0, y + depth]];
  return (
    <g>
      <Shape pts={body} mat={m(lerpC("#16214a", "#4f5a8c", dawn), "#0c1330", lerpC("#2f3f80", "#a88fb0", dawn), "#4a5ea8")} ink={0} round={0.5} wob={0} shade={0} lit={0.06} litOpacity={0.5} seed={seed} />
      {foam && <Line pts={pts} w={4} color="#cfd9ff" opacity={0.75} wob={0} />}
      {foam && <Line pts={pts.map(([x, yy]) => [x, yy + 10] as P)} w={2} color="#8fa2e6" opacity={0.45} wob={0} />}
    </g>
  );
};

// ---------- island ----------
export type Fire = { x: number; y: number; on: number; s?: number };
export const Island: React.FC<{ cx: number; base: number; w: number; h: number; f: number; seed?: number; fires?: Fire[]; dawn?: number; reef?: boolean }> = ({ cx, base, w, h, f, seed = 1, fires = [], dawn = 0, reef = true }) => {
  const g = rng(`isl${seed}`);
  const x0 = cx - w / 2;
  // canopy: a scalloped ridge of tree crowns, tallest near the middle
  const canopy = (layer: number): P[] => {
    const pts: P[] = [[x0 - 40, base]];
    let x = x0;
    while (x < x0 + w) {
      const t = (x - x0) / w;
      const prof = Math.pow(Math.sin(Math.PI * Math.min(1, Math.max(0, t))), 0.7);
      const r = rr(g, 24, 46) * (1 - layer * 0.15);
      const top = base - (h * (0.25 + 0.75 * prof)) * (1 - layer * 0.35) - rr(g, 0, 26);
      for (let k = 0; k <= 6; k++) {
        const a = Math.PI + (k / 6) * Math.PI;
        pts.push([x + r + Math.cos(a) * r, top + Math.sin(a) * r * 0.85]);
      }
      x += r * rr(g, 1.4, 1.8);
    }
    pts.push([x0 + w + 40, base]);
    return pts;
  };
  const palms = Array.from({ length: 6 }, (_, i) => {
    const px = x0 + w * (0.12 + i * 0.15) + rr(g, -20, 20);
    const ph = h * rr(g, 0.55, 0.95);
    return { px, ph, lean: rr(g, -14, 14), seed: i };
  });
  const sway = (i: number) => Math.sin(f * 0.04 + i) * 3;
  return (
    <g>
      {/* back ridge */}
      <Shape pts={canopy(0)} mat={SM.jungle} ink={WEIGHT.outline} round={0.7} shade={0} lit={0.04} litOpacity={0.6} seed={seed} wob={0.4} />
      {palms.map((p, i) => {
        const top: P = [p.px + p.lean + sway(i), base - p.ph];
        const trunk = tube(qcurve([p.px, base - 10], [p.px + p.lean * 0.2, base - p.ph * 0.6], top, 10), (t) => 14 - t * 6);
        const fronds = [0, 1, 2, 3, 4, 5].map((k) => {
          const a = -170 + k * 34 + sway(i) * 2;
          const tip = add(top, rot([90, 0], a));
          const mid = add(lerpP(top, tip, 0.5), rot([0, 16], a));
          return [top, mid, tip, add(lerpP(top, tip, 0.55), rot([0, -4], a))] as P[];
        });
        return (
          <g key={i}>
            <Shape pts={trunk} mat={SM.palm} ink={WEIGHT.small} round={0.5} shade={0} lit={0.15} seed={seed + 10 + i} />
            {fronds.map((fr, k) => <Shape key={k} pts={fr} mat={SM.palm} ink={WEIGHT.small} round={0.9} shade={0} lit={0.12} seed={seed + 30 + i * 6 + k} />)}
          </g>
        );
      })}
      {/* fires: warm light among the trees (the islanders are never shown) */}
      {fires.map((fi, i) => fi.on > 0 && (
        <g key={i}>
          <circle cx={fi.x} cy={fi.y} r={70 * (fi.s ?? 1) * fi.on} fill="#ff9a3c" opacity={0.18 * fi.on} />
          <Flame x={fi.x} y={fi.y} s={(fi.s ?? 1) * fi.on} f={f} seed={i} />
        </g>
      ))}
      {/* front canopy layer, lower and darker */}
      <Shape pts={canopy(1)} mat={SM.jungle2} ink={WEIGHT.outline} round={0.7} shade={0} lit={0.05} litOpacity={0.6} seed={seed + 2} wob={0.4} />
      {/* beach */}
      <Shape pts={[[x0 - 60, base + 2], ...qcurve([x0 + w * 0.3, base - 12], [x0 + w * 0.7, base - 8], [x0 + w + 60, base + 2], 12), [x0 + w + 80, base + 26], [x0 - 80, base + 26]]} mat={m(lerpC("#5d6276", "#d8b48e", dawn), "#454a5d", "#8a90a6", "#3a3e50")} ink={WEIGHT.small} round={0.6} shade={0} lit={0.1} seed={seed + 3} />
      {reef && [0, 1, 2].map((k) => {
        const yy = base + 40 + k * 22;
        const pts: P[] = Array.from({ length: 30 }, (_, i) => [x0 - 80 + (i * (w + 160)) / 29, yy + Math.sin(i * 0.9 + f * 0.1 + k) * 4]);
        return <Line key={k} pts={pts} w={4 - k} color="#dfe7ff" opacity={(0.7 - k * 0.2) * (0.6 + 0.4 * Math.sin(f * 0.07 + k * 2))} wob={0} />;
      })}
    </g>
  );
};

export const Flame: React.FC<{ x: number; y: number; s?: number; f: number; seed?: number }> = ({ x, y, s = 1, f, seed = 0 }) => {
  const k = 1 + 0.12 * Math.sin(f * 0.6 + seed * 3) + 0.08 * Math.sin(f * 1.7 + seed);
  const sway = Math.sin(f * 0.35 + seed) * 4 * s;
  const shape = (sc: number): P[] => [[x - 12 * s * sc, y], ...qcurve([x - 14 * s * sc, y - 18 * s * sc * k], [x + sway * sc, y - 34 * s * sc * k], [x + sway * sc, y - 40 * s * sc * k], 6), ...qcurve([x + 14 * s * sc, y - 18 * s * sc * k], [x + 12 * s * sc, y], [x + 12 * s * sc, y], 4)];
  return (
    <g>
      <Shape pts={shape(1)} mat={SM.orange} ink={1.8} inkColor="#6a2a08" round={0.9} shade={0} lit={0} seed={seed} />
      <Shape pts={shape(0.6).map(([px, py]) => [px, py] as P)} mat={m("#ffd35a", "#ffd35a", "#ffd35a", "#ffd35a")} ink={0} round={0.9} shade={0} lit={0} seed={seed + 1} />
    </g>
  );
};

// ---------- yacht ----------
// Side view, bow to the right, origin at the waterline centre. `lights` 0..1, `hatch` 0..1 open.
export const yachtPoint = (x: number, y: number, s: number, r: number, local: P): P => add(rot([local[0] * s, local[1] * s], r), [x, y]);
export const Yacht: React.FC<{ x: number; y: number; s?: number; r?: number; f: number; lights?: number; hatch?: number; seed?: number; children?: React.ReactNode; anchorUp?: boolean }> = ({ x, y, s = 1, r = 0, f, lights = 1, hatch = 0, seed = 1, children }) => {
  const Pt = (pts: P[]) => place(pts, x, y, r, s);
  const hull = Pt([[-270, -54], [-60, -62], [140, -74], [250, -88], [300, -100], [276, -44], [220, 18], [-230, 30], [-268, 8]]);
  const bottom = Pt([[-262, 4], [222, 14], [206, 36], [-226, 40]]);
  const stripe = Pt([[-266, -24], [240, -40], [232, -26], [-262, -8]]);
  const cabin = Pt([[-176, -60], [-158, -152], [64, -158], [168, -66]]);
  const roof = Pt(rrect(-182, -178, 252, 26, 8));
  const wins = [[-138, -128, 54], [-62, -130, 54], [14, -132, 56]].map(([wx, wy, ww]) => Pt([[wx, wy], [wx + ww, wy - 2], [wx + ww + 6, wy + 26], [wx + 4, wy + 28]]));
  const windshield = Pt([[72, -150], [132, -112], [118, -100], [70, -132]]);
  const mast = Pt([[-36, -176], [-30, -290]]);
  const hatchHinge: P = [-40, -178];
  const hatchLid = Pt([...[[0, 0], [80, 0], [80, -10], [0, -10]].map((p) => add(rot(p as P, -112 * hatch), hatchHinge))]);
  const rail: P[] = Pt([[-262, -82], [-60, -90], [150, -104], [292, -120]]);
  const posts = [-240, -170, -100, -30, 40, 110, 180, 250].map((px) => {
    const t = (px + 262) / 554;
    const top = lerpP([-262, -82], [292, -120], t), bot = lerpP([-262, -54], [292, -96], t);
    return Pt([top, bot]);
  });
  const flick = lights;
  const lit = flick > 0.5;
  return (
    <g>
      <Shape pts={bottom} mat={SM.bottom} ink={WEIGHT.outline} round={0.4} shade={0.1} lit={0} seed={seed} />
      <Shape pts={hull} mat={SM.hull} ink={WEIGHT.hero} round={0.35} shade={0.12} lit={0.08} seed={seed + 1}>
        <Line pts={Pt([[-262, -38], [250, -60]])} w={2} color={SM.hull.line} opacity={0.7} />
      </Shape>
      <Shape pts={stripe} mat={SM.stripe} ink={WEIGHT.small} round={0.2} shade={0} lit={0.15} seed={seed + 2} />
      <Shape pts={cabin} mat={SM.hull} ink={WEIGHT.hero} round={0.3} shade={0.1} lit={0.08} seed={seed + 3} />
      {wins.map((wp, i) => <Shape key={i} pts={wp} mat={lit ? SM.glassLit : SM.glass} ink={WEIGHT.small} round={0.5} shade={lit ? 0 : 0.2} lit={lit ? 0 : 0.2} seed={seed + 4 + i} />)}
      <Shape pts={windshield} mat={SM.glass} ink={WEIGHT.small} round={0.3} shade={0} lit={0.3} seed={seed + 8} />
      <Shape pts={roof} mat={SM.hull} ink={WEIGHT.outline} round={0.5} shade={0.15} lit={0.1} seed={seed + 9} />
      <Shape pts={tube(mast, () => 9 * s)} mat={SM.hull} ink={WEIGHT.small} round={0.3} shade={0.2} lit={0.2} seed={seed + 10} />
      <Shape pts={tube(Pt([[-76, -262], [14, -262]]), () => 7 * s)} mat={SM.hull} ink={WEIGHT.small} round={0.3} shade={0.2} lit={0.2} seed={seed + 11} />
      {/* life ring */}
      <Shape pts={Pt(ellipse(118, -110, 20, 20, 24))} mat={SM.orange} ink={WEIGHT.small} shade={0.15} lit={0.1} seed={seed + 12} />
      <Shape pts={Pt(ellipse(118, -110, 9, 9, 16))} mat={SM.hull} ink={WEIGHT.small} shade={0} lit={0} seed={seed + 13} />
      {/* fenders */}
      {[-140, 20].map((fx, i) => <Shape key={i} pts={Pt(rrect(fx, -62, 18, 40, 9))} mat={SM.stripe} ink={WEIGHT.small} round={0.6} shade={0.15} lit={0.2} seed={seed + 14 + i} />)}
      {/* rail */}
      <Line pts={rail} w={4 * s} color={INK} />
      {posts.map((p, i) => <Line key={i} pts={p} w={3 * s} color={INK} />)}
      {/* hatch: frame, the lid swings open; children (the hero) emerge through it */}
      <Shape pts={Pt(rrect(-44, -186, 88, 12, 3))} mat={SM.stripe} ink={WEIGHT.small} round={0.3} shade={0} lit={0.1} seed={seed + 16} />
      {children}
      <Shape pts={hatchLid} mat={SM.hull} ink={WEIGHT.small} round={0.3} shade={0.2} lit={0.1} seed={seed + 17} />
      {/* nav lights (their glow is drawn in the emissive pass, see YachtGlow) */}
      <circle cx={Pt([[262, -96]])[0][0]} cy={Pt([[262, -96]])[0][1]} r={7 * s} fill={lit ? "#5dff8a" : "#1d3a28"} stroke={INK} strokeWidth={2} />
      <circle cx={Pt([[-30, -292]])[0][0]} cy={Pt([[-30, -292]])[0][1]} r={7 * s} fill={lit ? "#ffffff" : "#3a3f50"} stroke={INK} strokeWidth={2} />
      <circle cx={Pt([[-262, -86]])[0][0]} cy={Pt([[-262, -86]])[0][1]} r={6 * s} fill={lit ? "#fff2c8" : "#3a3f50"} stroke={INK} strokeWidth={2} />
    </g>
  );
};

// Emissive pass for the yacht: window glow, nav-light halos, light spill on the water.
export const YachtGlow: React.FC<{ x: number; y: number; s?: number; r?: number; lights: number }> = ({ x, y, s = 1, r = 0, lights }) => {
  if (lights <= 0.02) return null;
  const Q = (p: P) => yachtPoint(x, y, s, r, p);
  const c = Q([-40, -116]), g = Q([262, -96]), w = Q([-30, -292]), st = Q([-262, -86]);
  return (
    <g opacity={lights}>
      <defs>
        <radialGradient id="ywarm"><stop offset="0" stopColor="#ffc86a" stopOpacity="0.55" /><stop offset="1" stopColor="#ffc86a" stopOpacity="0" /></radialGradient>
        <radialGradient id="ygreen"><stop offset="0" stopColor="#6dff9a" stopOpacity="0.7" /><stop offset="1" stopColor="#6dff9a" stopOpacity="0" /></radialGradient>
        <radialGradient id="ywhite"><stop offset="0" stopColor="#ffffff" stopOpacity="0.8" /><stop offset="1" stopColor="#ffffff" stopOpacity="0" /></radialGradient>
      </defs>
      <ellipse cx={c[0]} cy={c[1]} rx={230 * s} ry={110 * s} fill="url(#ywarm)" />
      <circle cx={g[0]} cy={g[1]} r={46 * s} fill="url(#ygreen)" />
      <circle cx={w[0]} cy={w[1]} r={52 * s} fill="url(#ywhite)" />
      <circle cx={st[0]} cy={st[1]} r={40 * s} fill="url(#ywhite)" />
      {/* warm reflection streak on the water below the cabin */}
      <ellipse cx={c[0]} cy={y + 70 * s} rx={150 * s} ry={16 * s} fill="#ffc86a" opacity={0.25} />
    </g>
  );
};

// ---------- smoke (analytic particles: deterministic, no state) ----------
export type Puff = { t0: number; x: number; y: number; vx: number; vy: number; r0: number; life: number; seed: number };
export const makePuffs = (bursts: { at: number; n: number; x: number; y: number; power?: number }[]): Puff[] => {
  const out: Puff[] = [];
  bursts.forEach((b, bi) => {
    const g = rng(`puff${bi}`);
    for (let i = 0; i < b.n; i++) out.push({ t0: b.at + i * 1.5, x: b.x, y: b.y, vx: -rr(g, 30, 90) * (b.power ?? 1), vy: -rr(g, 50, 110) * (b.power ?? 1), r0: rr(g, 10, 20) * (b.power ?? 1), life: rr(g, 45, 80), seed: bi * 10 + i });
  });
  return out;
};
export const Smoke: React.FC<{ puffs: Puff[]; f: number }> = ({ puffs, f }) => (
  <g>
    {puffs.map((p, i) => {
      const a = (f - p.t0) / 30;
      if (a < 0 || f - p.t0 > p.life) return null;
      const k = (f - p.t0) / p.life;
      const x = p.x + p.vx * a - 20 * a * a, y = p.y + p.vy * a - 12 * a * a;
      const r = p.r0 + 46 * Math.sqrt(a);
      const o = (1 - k) * Math.min(1, k * 8);
      const g = rng(`pf${p.seed}`);
      const blob: P[] = Array.from({ length: 9 }, (_, j) => {
        const ang = (j / 9) * Math.PI * 2;
        const rr2 = r * rr(g, 0.82, 1.08);
        return [x + Math.cos(ang) * rr2, y + Math.sin(ang) * rr2 * 0.9] as P;
      });
      return <g key={i} opacity={o}><Shape pts={blob} mat={SM.smoke} ink={2.4} inkColor="#14151b" round={1} shade={0.18} lit={0.12} seed={p.seed} /></g>;
    })}
  </g>
);

// ---------- rescue gear and ships ----------
export const Radio: React.FC<{ x: number; y: number; s?: number; r?: number; f: number; tx?: number }> = ({ x, y, s = 1, r = 0, f, tx = 0 }) => {
  const Pt = (pts: P[]) => place(pts, x, y, r, s);
  return (
    <g>
      <Shape pts={Pt(rrect(-14, -150, 12, 60, 5))} mat={SM.radio} ink={WEIGHT.small} round={0.5} shade={0.2} lit={0.2} seed={70} />
      <Shape pts={Pt(rrect(-44, -100, 88, 190, 18))} mat={SM.radio} ink={WEIGHT.outline} round={0.6} shade={0.16} lit={0.18} seed={71}>
        {[0, 1, 2, 3].map((i) => <Line key={i} pts={Pt([[-26, 40 + i * 12], [26, 40 + i * 12]])} w={3} color="#0e1014" opacity={0.8} />)}
      </Shape>
      <Shape pts={Pt(rrect(-32, -84, 64, 44, 6))} mat={SM.lcd} ink={WEIGHT.small} round={0.4} shade={0} lit={0.2} seed={72} />
      <text x={0} y={0} transform={`translate(${Pt([[0, -54]])[0].join(",")}) rotate(${r}) scale(${s})`} textAnchor="middle" fontFamily="monospace" fontWeight={700} fontSize={26} fill="#1e3a12">CH 16</text>
      <Shape pts={Pt(rrect(-30, -26, 60, 22, 8))} mat={tx > 0.5 ? SM.cgRed : SM.ship} ink={WEIGHT.small} round={0.6} shade={0.1} lit={0.2} seed={73} />
    </g>
  );
};

export const Beacon: React.FC<{ x: number; y: number; s?: number; f: number; on?: number }> = ({ x, y, s = 1, f, on = 1 }) => {
  const strobe = on > 0 && f % 24 < 4;
  return (
    <g>
      <Contact x={x} y={y + 2} w={90 * s} opacity={0.35} />
      <Shape pts={place(rrect(-34, -150, 68, 150, 16), x, y, 0, s)} mat={SM.beacon} ink={WEIGHT.outline} round={0.6} shade={0.18} lit={0.15} seed={80}>
        <Line pts={place([[-34, -60], [34, -60]], x, y, 0, s)} w={6} color={SM.beacon.line} />
      </Shape>
      <Shape pts={place(ellipse(0, -164, 26, 26, 20), x, y, 0, s)} mat={strobe ? m("#ffffff", "#e8f0ff", "#fff", "#cfd8f0") : m("#dfe6f4", "#b8c2d8", "#fff", "#9aa6c2")} ink={WEIGHT.small} shade={0.1} lit={0.2} seed={81} />
    </g>
  );
};

export const CoastGuardShip: React.FC<{ x: number; y: number; s?: number; f: number }> = ({ x, y, s = 1, f }) => {
  const bob = Math.sin(f * 0.08) * 4;
  const Pt = (pts: P[]) => place(pts, x, y + bob, Math.sin(f * 0.05) * 1.2, s);
  return (
    <g>
      <Shape pts={Pt([[-200, -40], [190, -50], [240, -70], [210, 20], [-190, 24]])} mat={SM.cgWhite} ink={WEIGHT.outline} round={0.3} shade={0.12} lit={0.08} seed={90}>
        <Shape pts={Pt([[60, -46], [110, -48], [40, 22], [-10, 22]])} mat={SM.cgRed} ink={0} round={0} shade={0} lit={0} seed={91} />
      </Shape>
      <Shape pts={Pt([[-120, -40], [-110, -110], [60, -116], [90, -44]])} mat={SM.cgWhite} ink={WEIGHT.outline} round={0.3} shade={0.12} lit={0.08} seed={92} />
      {[-90, -40, 10].map((wx, i) => <Shape key={i} pts={Pt(rrect(wx, -98, 34, 20, 4))} mat={SM.glassLit} ink={WEIGHT.small} round={0.4} shade={0} lit={0} seed={93 + i} />)}
      <Shape pts={tube(Pt([[-30, -114], [-26, -180]]), () => 8 * s)} mat={SM.cgWhite} ink={WEIGHT.small} round={0.3} shade={0.2} lit={0.2} seed={96} />
    </g>
  );
};

export const Helicopter: React.FC<{ x: number; y: number; s?: number; f: number; rope?: number; tilt?: number }> = ({ x, y, s = 1, f, rope = 0, tilt = -6 }) => {
  const Pt = (pts: P[]) => place(pts, x, y, tilt, s);
  const blade = Math.cos(f * 1.3);
  return (
    <g>
      {rope > 0 && <Line pts={[Pt([[0, 30]])[0], [x, y + rope]]} w={3 * s} color={INK} />}
      <Shape pts={tube(Pt([[40, -6], [200, -16]]), (t) => (22 - t * 12) * s)} mat={SM.cgRed} ink={WEIGHT.outline} round={0.4} shade={0.15} lit={0.1} seed={100} />
      <Shape pts={Pt(ellipse(-10, 0, 90, 52, 30))} mat={SM.heli} ink={WEIGHT.outline} shade={0.14} lit={0.1} seed={101} />
      <Shape pts={Pt([[-80, -10], [-20, -36], [-20, 4], [-78, 10]])} mat={SM.glass} ink={WEIGHT.small} round={0.6} shade={0} lit={0.3} seed={102} />
      <Shape pts={Pt(rrect(20, -18, 60, 20, 6))} mat={SM.cgRed} ink={WEIGHT.small} round={0.5} shade={0} lit={0.1} seed={103} />
      <Line pts={Pt([[-70, 58], [60, 58]])} w={6 * s} color={INK} />
      <Line pts={Pt([[-40, 44], [-46, 58]])} w={4 * s} color={INK} />
      <Line pts={Pt([[30, 44], [36, 58]])} w={4 * s} color={INK} />
      <Line pts={Pt([[-10, -52], [-10, -66]])} w={6 * s} color={INK} />
      <Line pts={Pt([[-10 - 150 * blade, -66], [-10 + 150 * blade, -66]])} w={6 * s} color={INK} />
      <ellipse cx={Pt([[-10, -66]])[0][0]} cy={Pt([[-10, -66]])[0][1]} rx={150 * s} ry={10 * s} fill="#ffffff" opacity={0.12} />
      <Line pts={Pt([[200, -40], [200, 8]].map(([px, py]) => [px, py] as P))} w={4 * s} color={INK} opacity={0.6 + 0.4 * Math.sin(f * 1.7)} />
    </g>
  );
};

// MV Primrose-style bulk freighter (generic, not a replica), aground and listing.
export const CargoShip: React.FC<{ x: number; y: number; s?: number; r?: number; f: number; portholes?: number; seed?: number }> = ({ x, y, s = 1, r = -4, f, portholes = 1, seed = 1 }) => {
  const Pt = (pts: P[]) => place(pts, x, y, r, s);
  return (
    <g>
      <Shape pts={Pt([[-520, -120], [400, -120], [520, -170], [470, 40], [-500, 50]])} mat={SM.ship} ink={WEIGHT.hero} round={0.2} shade={0.1} lit={0.08} seed={seed}>
        <Shape pts={Pt([[-500, 10], [480, 0], [470, 40], [-500, 50]])} mat={SM.shipRust} ink={0} round={0} shade={0} lit={0} seed={seed + 1} />
        {Array.from({ length: 7 }, (_, i) => <Line key={i} pts={Pt([[-420 + i * 120, -110], [-418 + i * 120, 30]])} w={2} color={SM.ship.line} opacity={0.6} />)}
      </Shape>
      {/* cargo hatches */}
      {[-300, -120, 60, 240].map((hx, i) => <Shape key={i} pts={Pt(rrect(hx, -150, 140, 32, 4))} mat={SM.shipRust} ink={WEIGHT.small} round={0.2} shade={0.1} lit={0.1} seed={seed + 2 + i} />)}
      {/* superstructure at the stern */}
      <Shape pts={Pt([[-500, -120], [-490, -330], [-330, -330], [-320, -120]])} mat={SM.cgWhite} ink={WEIGHT.outline} round={0.15} shade={0.12} lit={0.06} seed={seed + 8} />
      {Array.from({ length: 4 }, (_, row) => Array.from({ length: 4 }, (_, c) => {
        const on = portholes > (row * 4 + c) / 16;
        return <Shape key={`${row}-${c}`} pts={Pt(ellipse(-470 + c * 40, -290 + row * 44, 11, 11, 16))} mat={on ? SM.glassLit : SM.glass} ink={2.4} shade={0} lit={0} seed={seed + 20 + row * 4 + c} />;
      }))}
      <Shape pts={Pt([[-450, -330], [-440, -420], [-380, -420], [-370, -330]])} mat={SM.cgRed} ink={WEIGHT.outline} round={0.2} shade={0.15} lit={0.1} seed={seed + 40} />
      <Shape pts={tube(Pt([[300, -170], [300, -360]]), () => 12 * s)} mat={SM.ship} ink={WEIGHT.small} round={0.2} shade={0.2} lit={0.2} seed={seed + 41} />
      <Line pts={Pt([[300, -340], [100, -130]])} w={3 * s} color={INK} />
      <Line pts={Pt([[300, -340], [460, -150]])} w={3 * s} color={INK} />
    </g>
  );
};

// Cute germ (for the "immunity" beat): a blob with nubs and a face.
export const Germ: React.FC<{ x: number; y: number; r?: number; f: number; seed?: number }> = ({ x, y, r = 30, f, seed = 1 }) => {
  const g = rng(`germ${seed}`);
  const n = 9;
  const body: P[] = Array.from({ length: n * 2 }, (_, i) => {
    const a = (i / (n * 2)) * Math.PI * 2 + f * 0.03;
    const k = i % 2 === 0 ? 1.18 : 0.92 + 0.05 * Math.sin(f * 0.2 + i);
    return [x + Math.cos(a) * r * k, y + Math.sin(a) * r * k];
  });
  const e = r * 0.22;
  return (
    <g>
      <Shape pts={body} mat={SM.germ} ink={WEIGHT.small} round={0.9} shade={0.2} lit={0.15} seed={seed} />
      <circle cx={x - e * 1.4} cy={y - e * 0.4} r={e * 0.7} fill={INK} />
      <circle cx={x + e * 1.4} cy={y - e * 0.4} r={e * 0.7} fill={INK} />
      <path d={`M ${x - e},${y + e * 1.2} Q ${x},${y + e * 2.2 + rr(g, 0, 2)} ${x + e},${y + e * 1.2}`} stroke={INK} strokeWidth={3} fill="none" strokeLinecap="round" />
    </g>
  );
};
