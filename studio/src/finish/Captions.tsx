// Kinetic captions, ENGAGEMENT_RECIPE section 5 (C-1..C-5) on a 1080x1920 canvas:
//   safe rect x 65..888, caption band y 1000..1240; 1-3 words per page, one line <= 800 px;
//   cap-height 70-95 px in a heavy grotesk (Inter 900, cap-height 0.727 em -> 96..130 px type);
//   white fill, 10 px black stroke, 50% drop shadow; the emphasised word in yellow / red / green
//   with a scale pop to ~118% over 3 frames on its own onset.
import React from "react";
import { loadFont } from "@remotion/google-fonts/Inter";
import { loadFont as loadSerif } from "@remotion/google-fonts/SourceSerif4";
import { CaptionPage, CaptionStyle, CaptionTone } from "./types";

const inter = loadFont("normal", { weights: ["800", "900"], subsets: ["latin"] });
export const CAPTION_FONT = inter.fontFamily;
// style system (factory/styles): the serif is loaded only when a style asks for it
let serifFamily: string | null = null;
const fontFamily = (name: CaptionStyle["font"] | undefined): string => {
  if (name !== "SourceSerif4") return CAPTION_FONT;
  if (!serifFamily) serifFamily = loadSerif("normal", { weights: ["400", "600", "700"], subsets: ["latin"] }).fontFamily;
  return serifFamily;
};

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

export function captionFontSize(text: string, emphScale = 1.18): number {
  const capMax = 92, capMin = 72;
  const fit = MAX_LINE / (textWidthEm(text) * 1.04 + 0.06 * emphScale); // stroke + pop headroom
  return Math.max(capMin / CAP_HEIGHT_EM, Math.min(capMax / CAP_HEIGHT_EM, fit));
}

const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const backOut = (t: number) => { const c = 1.9, x = clamp01(t) - 1; return 1 + (c + 1) * x * x * x + c * x * x; };

export const Captions: React.FC<{ f: number; pages: CaptionPage[]; captionStyle?: CaptionStyle }> = ({ f, pages, captionStyle }) => {
  const page = pages.find((p) => f >= p.from && f < p.to);
  if (!page) return null;
  if (captionStyle?.mode === "lower_third") return <LowerThird f={f} page={page} cs={captionStyle} />;
  const cs = captionStyle;
  const tones = cs?.tones ?? TONE;
  const popMax = cs?.pop ?? 1.18;
  const text = page.words.map((w) => w.t).join(" ");
  let size = captionFontSize(text);
  const widthPx = textWidthEm(text) * size;
  const fitScale = widthPx > SAFE.x1 - SAFE.x0 - 20 ? (SAFE.x1 - SAFE.x0 - 20) / widthPx : 1; // never leave the safe rect
  size *= fitScale;
  const t = f - page.from;
  const enter = backOut(t / 4);
  const opacity = clamp01((t + 1) / 2);
  const cx = (SAFE.x0 + SAFE.x1) / 2;
  const baseline = 1180;
  return (
    <div style={{
      position: "absolute", left: SAFE.x0, width: SAFE.x1 - SAFE.x0, top: baseline - size * 0.98, height: size * 1.25,
      display: "flex", justifyContent: "center", alignItems: "flex-start", whiteSpace: "nowrap",
      transform: `scale(${0.82 + 0.18 * enter})`, transformOrigin: `${cx - SAFE.x0}px ${size * 0.6}px`, opacity,
    }}>
      {page.words.map((w, i) => {
        const em = page.emph === i;
        const on = f >= w.from;
        const dt = f - w.from;
        const pk = popMax - 1;
        const pop = em && on ? (dt < 3 ? 1 + pk * backOut(dt / 3) : popMax - pk / 3 * clamp01((dt - 3) / 5)) : 1;
        return (
          <span key={i} style={{
            display: "inline-block", fontFamily: fontFamily(cs?.font), fontWeight: cs?.weight ?? 900, fontSize: size, lineHeight: 1,
            letterSpacing: "-0.01em", marginLeft: i ? size * (em ? 0.38 : 0.28) : 0,
            marginRight: em && i < page.words.length - 1 ? size * 0.1 : 0,
            color: em && on ? tones[page.tone] : (cs?.fill ?? "#FFFFFF"),
            WebkitTextStroke: cs && !cs.stroke ? undefined : `${Math.round(size * (cs?.strokeEm ?? 0.19))}px ${cs?.stroke ?? "#000"}`, paintOrder: "stroke fill",
            textShadow: cs && !cs.shadow ? undefined : "0 7px 0 rgba(0,0,0,0.5), 0 10px 26px rgba(0,0,0,0.5)",
            transform: `scale(${pop})`, transformOrigin: "50% 70%",
          }}>{w.t}</span>
        );
      })}
    </div>
  );
};

// Lower third (documentary styles): one line of serif type on a soft plate, bottom-left of the safe rect, fading in
// and out; the emphasised word takes the accent tone without a scale pop.
const LowerThird: React.FC<{ f: number; page: CaptionPage; cs: CaptionStyle }> = ({ f, page, cs }) => {
  const [capMin, capMax] = cs.capHeight ?? [34, 44];
  const capEm = 0.66; // Source Serif 4 cap height
  const text = page.words.map((w) => w.t).join(" ");
  const maxW = cs.safe.x1 - cs.safe.x0 - 48;
  let size = capMax / capEm;
  const w = textWidthEm(text) * 0.92 * size;
  if (w > maxW) size = Math.max(capMin / capEm, size * maxW / w);
  const t = f - page.from, left = page.to - f;
  const opacity = clamp01(Math.min((t + 1) / 6, left / 6));
  const rise = (1 - clamp01((t + 1) / 8)) * 12;
  const bottom = 1920 - cs.band.y1;
  return (
    <div style={{
      position: "absolute", left: cs.safe.x0, maxWidth: cs.safe.x1 - cs.safe.x0, bottom, opacity,
      transform: `translateY(${rise}px)`, padding: `${size * 0.22}px ${size * 0.5}px ${size * 0.26}px ${size * 0.42}px`,
      background: cs.plate ?? undefined, borderLeft: `${Math.max(3, Math.round(size * 0.07))}px solid ${cs.tones.accent}`,
      whiteSpace: "nowrap",
    }}>
      {page.words.map((wd, i) => (
        <span key={i} style={{
          fontFamily: fontFamily(cs.font), fontWeight: cs.weight, fontStyle: cs.italic ? "italic" : "normal",
          fontSize: size, lineHeight: 1.15, letterSpacing: "0.005em", marginLeft: i ? size * 0.24 : 0,
          color: page.emph === i && f >= wd.from ? cs.tones[page.tone] : cs.fill,
          textShadow: cs.shadow ? "0 2px 10px rgba(0,0,0,0.55)" : undefined,
        }}>{wd.t}</span>
      ))}
    </div>
  );
};
