// Kinetic captions, ENGAGEMENT_RECIPE section 5 (C-1..C-5) on a 1080x1920 canvas:
//   safe rect x 65..888, caption band y 1000..1240; 1-3 words per page, one line <= 800 px;
//   cap-height 70-95 px in a heavy grotesk (Inter 900, cap-height 0.727 em -> 96..130 px type);
//   white fill, 10 px black stroke, 50% drop shadow; the emphasised word in yellow / red / green
//   with a scale pop to ~118% over 3 frames on its own onset.
import React from "react";
import { loadFont } from "@remotion/google-fonts/Inter";
import { CaptionPage, CaptionTone } from "./types";

const inter = loadFont("normal", { weights: ["800", "900"], subsets: ["latin"] });
export const CAPTION_FONT = inter.fontFamily;

export const SAFE = { x0: 65, x1: 888, y0: 290, y1: 1248 };
export const BAND = { y0: 1000, y1: 1240 };
const CAP_HEIGHT_EM = 0.727; // Inter
const MAX_LINE = 800;
const TONE: Record<CaptionTone, string> = { accent: "#FFD400", danger: "#FF3B30", good: "#34C759" };

// rough advance widths for Inter Black (em); good to ~5% for one-line fitting
function textWidthEm(s: string): number {
  let w = 0;
  for (const ch of s) {
    if (ch === " ") w += 0.26;
    else if (/[il.,'!|:;]/.test(ch)) w += 0.3;
    else if (/[mwMW]/.test(ch)) w += 0.92;
    else if (/[A-Z]/.test(ch)) w += 0.72;
    else if (/[0-9]/.test(ch)) w += 0.66;
    else w += 0.6;
  }
  return w;
}

// Canvas layouts: the 9:16 short (above) and the 16:9 docuseries master, where captions are a documentary
// lower third (safe x 10%..90%, baseline at 89% height, cap-height 40-52 px).
export type CaptionLayout = { x0: number; x1: number; baseline: number; maxLine: number; capMin: number; capMax: number };
export const LAYOUT_916: CaptionLayout = { x0: SAFE.x0, x1: SAFE.x1, baseline: 1180, maxLine: MAX_LINE, capMin: 72, capMax: 92 };
export function captionLayout(w = 1080, h = 1920): CaptionLayout {
  if (w <= h) return LAYOUT_916;
  return { x0: Math.round(0.1 * w), x1: Math.round(0.9 * w), baseline: Math.round(0.89 * h), maxLine: Math.round(0.7 * w),
    capMin: Math.round(40 * h / 1080), capMax: Math.round(52 * h / 1080) };
}

export function captionFontSize(text: string, emphScale = 1.18, lay: CaptionLayout = LAYOUT_916): number {
  const { capMax, capMin } = lay;
  const fit = lay.maxLine / (textWidthEm(text) * 1.04 + 0.06 * emphScale); // stroke + pop headroom
  return Math.max(capMin / CAP_HEIGHT_EM, Math.min(capMax / CAP_HEIGHT_EM, fit));
}

const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const backOut = (t: number) => { const c = 1.9, x = clamp01(t) - 1; return 1 + (c + 1) * x * x * x + c * x * x; };

export const Captions: React.FC<{ f: number; pages: CaptionPage[]; w?: number; h?: number }> = ({ f, pages, w: cw, h: ch }) => {
  const page = pages.find((p) => f >= p.from && f < p.to);
  if (!page) return null;
  const lay = captionLayout(cw, ch);
  const text = page.words.map((w) => w.t).join(" ");
  let size = captionFontSize(text, 1.18, lay);
  const widthPx = textWidthEm(text) * size;
  const fitScale = widthPx > lay.x1 - lay.x0 - 20 ? (lay.x1 - lay.x0 - 20) / widthPx : 1; // never leave the safe rect
  size *= fitScale;
  const t = f - page.from;
  const enter = backOut(t / 4);
  const opacity = clamp01((t + 1) / 2);
  const cx = (lay.x0 + lay.x1) / 2;
  const baseline = lay.baseline;
  return (
    <div style={{
      position: "absolute", left: lay.x0, width: lay.x1 - lay.x0, top: baseline - size * 0.98, height: size * 1.25,
      display: "flex", justifyContent: "center", alignItems: "flex-start", whiteSpace: "nowrap",
      transform: `scale(${0.82 + 0.18 * enter})`, transformOrigin: `${cx - lay.x0}px ${size * 0.6}px`, opacity,
    }}>
      {page.words.map((w, i) => {
        const em = page.emph === i;
        const on = f >= w.from;
        const dt = f - w.from;
        const pop = em && on ? (dt < 3 ? 1 + 0.18 * backOut(dt / 3) : 1.18 - 0.06 * clamp01((dt - 3) / 5)) : 1;
        return (
          <span key={i} style={{
            display: "inline-block", fontFamily: CAPTION_FONT, fontWeight: 900, fontSize: size, lineHeight: 1,
            letterSpacing: "-0.01em", marginLeft: i ? size * (em ? 0.38 : 0.28) : 0,
            marginRight: em && i < page.words.length - 1 ? size * 0.1 : 0,
            color: em && on ? TONE[page.tone] : "#FFFFFF",
            WebkitTextStroke: `${Math.round(size * 0.19)}px #000`, paintOrder: "stroke fill",
            textShadow: "0 7px 0 rgba(0,0,0,0.5), 0 10px 26px rgba(0,0,0,0.5)",
            transform: `scale(${pop})`, transformOrigin: "50% 70%",
          }}>{w.t}</span>
        );
      })}
    </div>
  );
};
