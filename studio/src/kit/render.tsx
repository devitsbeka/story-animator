import React, { createContext, useContext } from "react";
import { P, bbox, centroid, len, norm, poly, resample, smooth, sub, tube as tubeOf, wobble } from "./geom";
import { INK, LightRig, Material, WEIGHT } from "./theme";

// ============================================================================
// The renderer every object goes through. One function decides how a shape is
// filled, shaded, lit and outlined, so a mug, a sleeve and a wall all read as
// the same hand.
// ============================================================================

export const LightCtx = createContext<LightRig | null>(null);
export const useLight = () => useContext(LightCtx)!;

// deterministic, url-safe ids (SVG masks/clips need unique ids)
let __id = 0;
export const resetIds = () => { __id = 0; };
const nid = (p: string) => `${p}${++__id}`;

export type ShapeProps = {
  pts: P[]; // closed outline in world coordinates
  mat: Material;
  seed?: number;
  ink?: number; // outline weight; 0 = no outline
  inkColor?: string;
  round?: number; // 0 = sharp polygon, 1 = smooth curve
  wob?: number; // wobble amplitude (px)
  shade?: number; // cel shadow depth as a fraction of size (0 = none)
  lit?: number; // highlight depth as a fraction of size
  litOpacity?: number;
  hatch?: number; // hatch-line spacing inside the shadow (0 = none)
  lightFrom?: P; // override light position (e.g. object lit by its own glow)
  children?: React.ReactNode; // details, clipped to the shape
  over?: React.ReactNode; // details drawn after the outline (not clipped)
};

export const Shape: React.FC<ShapeProps> = ({
  pts, mat, seed = 1, ink = WEIGHT.outline, inkColor = INK, round = 1, wob = 0.3, shade = 0.14, lit = 0.08, litOpacity = 0.55, hatch = 0, lightFrom, children, over,
}) => {
  const light = useLight();
  const step = Math.max(6, Math.min(18, Math.sqrt(polyArea(pts)) / 10));
  const w = wob > 0 ? wobble(resample(pts, step), seed, wob) : pts;
  const d = round > 0 ? smooth(w, true, round) : poly(w, true);
  const c = centroid(pts);
  const b = bbox(pts);
  const size = Math.max(b.w, b.h);
  const L = lightFrom ?? [light.key.x, light.key.y];
  const dir = norm(sub(L, c));
  const far = len(sub(L, c));
  const so = Math.max(2, Math.min(60, shade * size)); // shadow offset
  const lo = Math.max(1.5, Math.min(40, lit * size));
  const idS = nid("s"), idL = nid("l"), idC = nid("c");
  const big = { x: b.x0 - 200, y: b.y0 - 200, width: b.w + 400, height: b.h + 400 };
  // light gets weaker with distance: highlights fade, shadows deepen a touch
  const reach = Math.max(0, 1 - far / (light.key.reach * 1.6));
  return (
    <g>
      <defs>
        <clipPath id={idC}><path d={d} /></clipPath>
        {shade > 0 && (
          <mask id={idS} maskUnits="userSpaceOnUse" {...big}>
            <path d={d} fill="#fff" />
            <path d={d} fill="#000" transform={`translate(${dir[0] * so},${dir[1] * so})`} />
          </mask>
        )}
        {lit > 0 && (
          <mask id={idL} maskUnits="userSpaceOnUse" {...big}>
            <path d={d} fill="#fff" />
            <path d={d} fill="#000" transform={`translate(${-dir[0] * lo},${-dir[1] * lo})`} />
          </mask>
        )}
      </defs>
      <path d={d} fill={mat.base} />
      {shade > 0 && (
        <g mask={`url(#${idS})`}>
          <path d={d} fill={mat.shade} />
          {hatch > 0 && <Hatch b={b} spacing={hatch} color={mat.line} angle={-Math.atan2(dir[1], dir[0]) * 57.3 + 60} seed={seed} />}
        </g>
      )}
      {lit > 0 && <g mask={`url(#${idL})`}><path d={d} fill={mat.lit} opacity={litOpacity * (0.4 + 0.6 * reach)} /></g>}
      {children && <g clipPath={`url(#${idC})`}>{children}</g>}
      {ink > 0 && <path d={d} fill="none" stroke={inkColor} strokeWidth={ink} strokeLinejoin="round" strokeLinecap="round" />}
      {over}
    </g>
  );
};

// Several parts drawn as ONE shape: a single merged outline (strokes underneath, fills on top),
// shared cel shading, and interior lines only where we ask for them (e.g. between fingers).
export const Union: React.FC<{ parts: P[][]; mat: Material; seed?: number; ink?: number; round?: number; wob?: number; shade?: number; lit?: number; litOpacity?: number; inner?: P[][]; innerW?: number; children?: React.ReactNode }> = ({
  parts, mat, seed = 1, ink = WEIGHT.hero, round = 1, wob = 0.25, shade = 0.12, lit = 0.08, litOpacity = 0.5, inner = [], innerW = WEIGHT.inner, children,
}) => {
  const light = useLight();
  const ds = parts.map((pts, i) => {
    const step = Math.max(5, Math.min(14, Math.sqrt(polyArea(pts)) / 9));
    const w = wob > 0 ? wobble(resample(pts, step), seed + i * 7, wob) : pts;
    return round > 0 ? smooth(w, true, round) : poly(w, true);
  });
  const all = parts.flat();
  const b = bbox(all);
  const c = centroid(all);
  const dir = norm(sub([light.key.x, light.key.y], c));
  const size = Math.max(b.w, b.h);
  const so = Math.max(2, Math.min(50, shade * size)), lo = Math.max(1.5, Math.min(30, lit * size));
  const idS = nid("us"), idL = nid("ul"), idC = nid("uc");
  const big = { x: b.x0 - 200, y: b.y0 - 200, width: b.w + 400, height: b.h + 400 };
  return (
    <g>
      <defs>
        <clipPath id={idC}>{ds.map((d, i) => <path key={i} d={d} />)}</clipPath>
        <mask id={idS} maskUnits="userSpaceOnUse" {...big}>
          {ds.map((d, i) => <path key={i} d={d} fill="#fff" />)}
          {ds.map((d, i) => <path key={`k${i}`} d={d} fill="#000" transform={`translate(${dir[0] * so},${dir[1] * so})`} />)}
        </mask>
        <mask id={idL} maskUnits="userSpaceOnUse" {...big}>
          {ds.map((d, i) => <path key={i} d={d} fill="#fff" />)}
          {ds.map((d, i) => <path key={`k${i}`} d={d} fill="#000" transform={`translate(${-dir[0] * lo},${-dir[1] * lo})`} />)}
        </mask>
      </defs>
      {ink > 0 && ds.map((d, i) => <path key={`o${i}`} d={d} fill="none" stroke={INK} strokeWidth={ink * 2} strokeLinejoin="round" />)}
      {ds.map((d, i) => <path key={`f${i}`} d={d} fill={mat.base} />)}
      {shade > 0 && <g mask={`url(#${idS})`}><rect {...big} fill={mat.shade} /></g>}
      {lit > 0 && <g mask={`url(#${idL})`}><rect {...big} fill={mat.lit} opacity={litOpacity} /></g>}
      {children && <g clipPath={`url(#${idC})`}>{children}</g>}
      {inner.map((pts, i) => <Line key={`i${i}`} pts={pts} w={innerW} seed={seed + 40 + i} />)}
    </g>
  );
};

const polyArea = (pts: P[]) => {
  let a = 0;
  for (let i = 0; i < pts.length; i++) { const p = pts[i], q = pts[(i + 1) % pts.length]; a += p[0] * q[1] - q[0] * p[1]; }
  return Math.abs(a / 2);
};

// A drawn line (open stroke) with wobble and optional taper (drawn as two passes).
export const Line: React.FC<{ pts: P[]; w?: number; color?: string; seed?: number; wob?: number; round?: number; opacity?: number; cap?: "round" | "butt" }> = ({
  pts, w = WEIGHT.detail, color = INK, seed = 3, wob = 0.25, round = 1, opacity = 1, cap = "round",
}) => {
  const p = wob > 0 ? wobble(resample(pts, 8, false), seed, wob) : pts;
  return <path d={round > 0 ? smooth(p, false, round) : poly(p, false)} fill="none" stroke={color} strokeWidth={w} strokeLinecap={cap} strokeLinejoin="round" opacity={opacity} />;
};

// A brush stroke: a filled tube whose width swells in the middle and tapers at both ends.
// Used for brows, smiles, folds: anything that should look inked by hand, not plotted.
export const Brush: React.FC<{ pts: P[]; w: number; color?: string; taper?: number; opacity?: number }> = ({ pts, w, color = INK, taper = 0.75, opacity = 1 }) => {
  const sp = resample(pts, 4, false);
  const outline = tubeOf(sp, (t) => w * (1 - taper + taper * Math.sin(Math.PI * Math.min(1, Math.max(0, t)))));
  return <path d={smooth(outline, true, 0.6)} fill={color} opacity={opacity} />;
};

// Parallel hatch lines across a box (used inside shadow masks).
export const Hatch: React.FC<{ b: ReturnType<typeof bbox>; spacing: number; color: string; angle?: number; w?: number; seed?: number; opacity?: number }> = ({
  b, spacing, color, angle = 60, w = 1.6, seed = 1, opacity = 0.55,
}) => {
  const r = Math.hypot(b.w, b.h) / 2 + 10;
  const lines: React.ReactNode[] = [];
  for (let k = -r, i = 0; k <= r; k += spacing, i++) {
    const j = ((Math.sin(i * 12.9898 + seed) * 43758.5453) % 1) * spacing * 0.3;
    lines.push(<line key={i} x1={-r} y1={k + j} x2={r} y2={k + j * 0.5} stroke={color} strokeWidth={w} strokeLinecap="round" />);
  }
  return <g opacity={opacity} transform={`translate(${b.cx},${b.cy}) rotate(${angle})`}>{lines}</g>;
};

// Soft contact shadow under an object resting on a surface.
export const Contact: React.FC<{ x: number; y: number; w: number; h?: number; opacity?: number; color?: string }> = ({ x, y, w, h = w * 0.12, opacity = 0.3, color = "#5a2a0c" }) => {
  const id = nid("cs");
  return (
    <g>
      <defs><radialGradient id={id}><stop offset="0.3" stopColor={color} stopOpacity={opacity} /><stop offset="1" stopColor={color} stopOpacity={0} /></radialGradient></defs>
      <ellipse cx={x} cy={y} rx={w / 2} ry={h} fill={`url(#${id})`} />
    </g>
  );
};

// ---------- the stage: light rig, post (grade, glow, vignette, grain) ----------
export const Stage: React.FC<{ light: LightRig; w: number; h: number; world: { w: number; h: number }; flicker?: number; children: React.ReactNode; post?: boolean; viewTransform?: string; fx?: React.ReactNode; worldOrigin?: [number, number] }> = ({
  light, w, h, world, flicker = 1, children, post = true, viewTransform, fx, worldOrigin = [0, 0],
}) => {
  resetIds();
  const k = light.key;
  return (
    <LightCtx.Provider value={light}>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: "block" }}>
        <defs>
          <radialGradient id="keyGlow" gradientUnits="userSpaceOnUse" cx={k.x} cy={k.y} r={k.reach}>
            <stop offset="0" stopColor={k.color} stopOpacity={0.7 * k.strength * flicker} />
            <stop offset="0.25" stopColor={k.color} stopOpacity={0.16 * k.strength * flicker} />
            <stop offset="1" stopColor={k.color} stopOpacity={0} />
          </radialGradient>
          <radialGradient id="falloff" gradientUnits="userSpaceOnUse" cx={k.x} cy={k.y} r={k.reach * 1.9}>
            <stop offset="0.45" stopColor="#fff" />
            <stop offset="1" stopColor="#8a5530" />
          </radialGradient>
          <radialGradient id="vig" cx="0.5" cy="0.45" r="0.75">
            <stop offset="0.55" stopColor="#1a0a03" stopOpacity="0" />
            <stop offset="1" stopColor="#1a0a03" stopOpacity={light.vignette} />
          </radialGradient>
          <filter id="grain" x="0" y="0" width="100%" height="100%">
            <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed="4" />
            <feColorMatrix type="matrix" values="0 0 0 0 0.3  0 0 0 0 0.18  0 0 0 0 0.08  0 0 0 1.2 -0.35" />
          </filter>
        </defs>
        {/* children place themselves (each depth plane carries its own camera transform) */}
        {children}
        {post && (
          <g transform={viewTransform} style={{ pointerEvents: "none" }}>
            {/* light falloff: the room darkens away from the key light */}
            <rect x={worldOrigin[0] - world.w} y={worldOrigin[1] - world.h} width={world.w * 3} height={world.h * 3} fill="url(#falloff)" style={{ mixBlendMode: "multiply" }} opacity={0.45} />
            {/* key light bloom */}
            <rect x={worldOrigin[0] - world.w} y={worldOrigin[1] - world.h} width={world.w * 3} height={world.h * 3} fill="url(#keyGlow)" style={{ mixBlendMode: "screen" }} />
          </g>
        )}
        {post && (
          <g style={{ pointerEvents: "none" }}>
            <rect width={w} height={h} fill={light.ambient} opacity={light.ambientStrength} style={{ mixBlendMode: "multiply" }} />
            <rect width={w} height={h} fill="url(#vig)" />
            {light.grain > 0 && <rect width={w} height={h} filter="url(#grain)" opacity={light.grain * 4} style={{ mixBlendMode: "multiply" }} />}
          </g>
        )}
        {/* emissive light (lamps, fire, running lights): drawn after the grade so it really glows */}
        {fx && <g style={{ mixBlendMode: "screen" }}>{fx}</g>}
      </svg>
    </LightCtx.Provider>
  );
};
