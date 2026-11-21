import React from "react";
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadPlayfair } from "@remotion/google-fonts/PlayfairDisplay";

// ============================================================================
// TYPOGRAPHY (premium-minimal-video-editor P01 + P06).
// Inter for context words, Playfair Display Italic for the anchor. One anchor per
// phrase, ≤5 words, reveal ≤250 ms, safe margins 6% horizontal and 8% vertical.
// ============================================================================

const inter = loadInter("normal", { weights: ["500", "700"], subsets: ["latin"] });
const play = loadPlayfair("italic", { weights: ["600", "800"], subsets: ["latin"] });
export const SANS = inter.fontFamily;
export const SERIF = play.fontFamily;

export const TYPE = {
  paper: "#F6F3EB",
  muted: "rgba(246,243,235,0.78)",
  blue: "#5B8BFF", // cobalt #386AD9, lifted for contrast on night scenes
  cobalt: "#386AD9",
  red: "#FF6B57",
};

const ease = (t: number) => 1 - Math.pow(1 - Math.max(0, Math.min(1, t)), 3);

export type CaptionProps = {
  f: number; from: number; to: number;
  small?: string; big: string;
  at?: "top" | "low" | "mid";
  tone?: "warm" | "blue" | "red";
  w: number; h: number;
};

export const Caption: React.FC<CaptionProps> = ({ f, from, to, small, big, at = "top", tone = "warm", w, h }) => {
  if (f < from - 1 || f > to + 1) return null;
  const inT = ease((f - from) / 7); // ~230 ms reveal
  const outT = ease((to - f) / 6);
  const o = Math.min(inT, outT);
  const y = (1 - inT) * 26;
  const settle = (1 - inT) * 0.06;
  const top = at === "top" ? h * 0.115 : at === "mid" ? h * 0.42 : h * 0.66;
  const len = big.length;
  const bigSize = len <= 6 ? 150 : len <= 10 ? 118 : len <= 16 ? 96 : 80;
  const color = tone === "blue" ? TYPE.blue : tone === "red" ? TYPE.red : TYPE.paper;
  return (
    <div style={{ position: "absolute", left: w * 0.06, right: w * 0.06, top, display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", opacity: o, transform: `translateY(${y}px)` }}>
      {small && (
        <div style={{ fontFamily: SANS, fontWeight: 700, fontSize: 40, letterSpacing: `${0.14 + settle}em`, textTransform: "uppercase", color: TYPE.muted, textShadow: "0 2px 18px rgba(4,6,20,0.85), 0 0 4px rgba(4,6,20,0.6)", marginBottom: 6 }}>
          {small}
        </div>
      )}
      <div style={{ fontFamily: SERIF, fontStyle: "italic", fontWeight: 800, fontSize: bigSize, lineHeight: 1.02, letterSpacing: `${-0.02 + settle}em`, color, textShadow: "0 4px 30px rgba(4,6,20,0.9), 0 0 6px rgba(4,6,20,0.7)" }}>
        {big}
      </div>
    </div>
  );
};

// P06: oversized quote marks framing a final line
export const QuoteMarks: React.FC<{ f: number; from: number; w: number; h: number }> = ({ f, from, w, h }) => {
  const t = ease((f - from) / 12);
  return (
    <>
      <div style={{ position: "absolute", left: w * 0.08, top: h * 0.33, fontFamily: SERIF, fontStyle: "italic", fontSize: 300, color: TYPE.cobalt, opacity: 0.9 * t, transform: `translateY(${(1 - t) * 30}px)`, lineHeight: 1 }}>“</div>
      <div style={{ position: "absolute", right: w * 0.08, top: h * 0.53, fontFamily: SERIF, fontStyle: "italic", fontSize: 300, color: TYPE.cobalt, opacity: 0.9 * t, transform: `translateY(${(1 - t) * -30}px)`, lineHeight: 1 }}>”</div>
    </>
  );
};
