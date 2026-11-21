// STEP tracker (ENGAGEMENT_RECIPE C-7): upper band y 300..520, left aligned at x >= 65, persists for
// the whole step. Badge "STEP n" + the step's title + one pip per step (done / current / to come).
import React from "react";
import { CAPTION_FONT } from "./Captions";
import { StepSpan } from "./types";

const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const easeOut = (t: number) => 1 - (1 - clamp01(t)) ** 3;

export const StepTracker: React.FC<{ f: number; steps: StepSpan[] }> = ({ f, steps }) => {
  const s = steps.find((x) => f >= x.from && f < x.to);
  if (!s) return null;
  const t = f - s.from;
  const tin = easeOut(t / 8);
  const tout = easeOut((s.to - f) / 6);
  const o = Math.min(tin, tout);
  const total = Math.max(s.total, steps.length);
  const title = s.title.length > 22 ? s.title.slice(0, 21) + "…" : s.title;
  const pulse = 1 + 0.12 * Math.max(0, 1 - Math.abs(t - 6) / 6);
  return (
    <div style={{ position: "absolute", left: 65, top: 318, maxWidth: 823 - 20, opacity: o, transform: `translateX(${(1 - tin) * -40}px)` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
        <div style={{
          fontFamily: CAPTION_FONT, fontWeight: 900, fontSize: 46, letterSpacing: "0.06em", color: "#111",
          background: "#FFD400", padding: "10px 22px 8px", borderRadius: 14, boxShadow: "0 6px 18px rgba(0,0,0,0.45)",
          transform: `scale(${pulse})`, transformOrigin: "0% 50%",
        }}>{s.label}</div>
        <div style={{ display: "flex", gap: 10 }}>
          {Array.from({ length: total }, (_, i) => {
            const n = i + 1, cur = n === s.n, done = n < s.n;
            return <div key={i} style={{
              width: cur ? 34 : 16, height: 16, borderRadius: 8,
              background: cur ? "#FFD400" : done ? "rgba(255,255,255,0.92)" : "rgba(255,255,255,0.28)",
              border: "2px solid rgba(0,0,0,0.55)",
            }} />;
          })}
        </div>
      </div>
      {title && (
        <div style={{
          marginTop: 14, fontFamily: CAPTION_FONT, fontWeight: 800, fontSize: 50, lineHeight: 1.05, color: "#fff",
          textTransform: "uppercase", letterSpacing: "0.01em", whiteSpace: "nowrap",
          WebkitTextStroke: "9px #000", paintOrder: "stroke fill", textShadow: "0 5px 14px rgba(0,0,0,0.55)",
        }}>{title}</div>
      )}
    </div>
  );
};
