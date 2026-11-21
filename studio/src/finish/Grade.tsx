// House grade for Blender plates: subtle filmic contrast (S-curve with a lifted toe and a soft
// shoulder, shadows a touch cool), halation on highlights (thresholded, blurred, warm red-orange,
// screened back), vignette and per-frame grain. SVG filters run in Chromium's software path
// (works with --gl=swangle; no WebGL needed).
import React from "react";
import { AbsoluteFill } from "remotion";

// coolShadows: 1 = house blue lift in the shadows, 0 = neutral (style system: factory/styles <style>.grade)
export type GradeOpts = { contrast: number; vignette: number; grain: number; halation: number; coolShadows?: number };
export const DEFAULT_GRADE: GradeOpts = { contrast: 0.35, vignette: 0.42, grain: 0.07, halation: 0.45, coolShadows: 1 };
const HI_TABLE = "0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0.12 0.45 1"; // 20 steps: zero below luma 0.85

// filmic tone curve sampled into an feComponentTransfer table
function curve(k: number, lift: number, gain: number, n = 17): string {
  const out: string[] = [];
  for (let i = 0; i < n; i++) {
    const x = i / (n - 1);
    const s = x * x * (3 - 2 * x); // S around mid grey
    let y = x + k * (s - x);
    y = lift + (gain - lift) * y; // toe lift / shoulder roll-off
    out.push(Math.max(0, Math.min(1, y)).toFixed(4));
  }
  return out.join(" ");
}

export const GradeDefs: React.FC<{ id: string; opts: GradeOpts; scale: number }> = ({ id, opts, scale }) => {
  const k = opts.contrast;
  const halo = opts.halation;
  const cool = opts.coolShadows ?? 1;
  const liftB = 0.016 + (0.03 - 0.016) * cool; // blue toe lift: 0.03 house, 0.016 (= green) neutral
  return (
    <svg width={0} height={0} style={{ position: "absolute" }}>
      <defs>
        <filter id={id} x="0" y="0" width="100%" height="100%" colorInterpolationFilters="sRGB">
          <feComponentTransfer in="SourceGraphic" result="tone">
            <feFuncR type="table" tableValues={curve(k, 0.012, 0.985)} />
            <feFuncG type="table" tableValues={curve(k, 0.016, 0.98)} />
            <feFuncB type="table" tableValues={curve(k * (1 - 0.15 * cool), liftB, 0.975)} />
          </feComponentTransfer>
          {/* halation: luminance -> keep only highlights -> wide blur -> warm tint */}
          <feColorMatrix in="tone" type="matrix" result="lum"
            values={`0.30 0.59 0.11 0 0  0.30 0.59 0.11 0 0  0.30 0.59 0.11 0 0  0 0 0 1 0`} />
          {/* only true highlights (lamps, moon glints, specular) bloom: luma > ~0.85, ramping to 1 */}
          <feComponentTransfer in="lum" result="hi">
            <feFuncR type="table" tableValues={HI_TABLE} />
            <feFuncG type="table" tableValues={HI_TABLE} />
            <feFuncB type="table" tableValues={HI_TABLE} />
          </feComponentTransfer>
          <feGaussianBlur in="hi" stdDeviation={14 * scale} result="blur" />
          <feColorMatrix in="blur" type="matrix" result="halo"
            values={`${halo} 0 0 0 0  0 ${halo * 0.42} 0 0 0  0 0 ${halo * 0.22} 0 0  0 0 0 1 0`} />
          <feBlend in="tone" in2="halo" mode="screen" />
        </filter>
      </defs>
    </svg>
  );
};

export const Vignette: React.FC<{ amount: number }> = ({ amount }) => (
  <AbsoluteFill style={{
    background: `radial-gradient(ellipse 78% 62% at 50% 46%, rgba(0,0,0,0) 52%, rgba(0,0,0,${amount * 0.55}) 82%, rgba(0,0,0,${amount}) 100%)`,
    pointerEvents: "none",
  }} />
);

// grain: fresh fractal noise every frame (seed = frame), grey, overlaid at low opacity
export const Grain: React.FC<{ frame: number; amount: number; width: number; height: number }> = ({ frame, amount, width, height }) => {
  const id = `grain-${frame}`;
  return (
    <svg width={width} height={height} style={{ position: "absolute", inset: 0, mixBlendMode: "overlay", opacity: amount * 4, pointerEvents: "none" }}>
      <filter id={id} x="0" y="0" width="100%" height="100%">
        <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves={2} seed={frame % 997} stitchTiles="stitch" />
        <feColorMatrix type="matrix" values="0.33 0.33 0.33 0 0  0.33 0.33 0.33 0 0  0.33 0.33 0.33 0 0  0 0 0 0 1" />
      </filter>
      <rect width="100%" height="100%" filter={`url(#${id})`} />
    </svg>
  );
};
