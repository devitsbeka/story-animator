import React from "react";
import { Hero, HeroPose, HandPose, AU, EXPR, STREET, headAnchor } from "../kit/character";
import { P, add } from "../kit/geom";
import { Stage } from "../kit/render";
import { LIGHTS } from "../kit/theme";
import { SANS } from "../kit/type";

// Model sheet: anatomy, hands and expressions in one view (the rig QA page).
type Cell = { label: string; expr: keyof typeof EXPR | AU; l: P | "cheekL"; r: P | "cheekR"; hl: HandPose; hr: HandPose; al?: number; ar?: number; tilt?: number; look?: P };
const CELLS: Cell[] = [
  { label: "neutral · relaxed", expr: "neutral", l: [-170, 80], r: [170, 80], hl: "relaxed", hr: "relaxed" },
  { label: "scared · arms up", expr: "scared", l: [-230, -480], r: [230, -480], hl: "open", hr: "open" },
  { label: "worried · shrug", expr: "worried", l: [-270, -120], r: [270, -120], hl: "open", hr: "open", al: -70, ar: 70 },
  { label: "shout · radio grip", expr: "shout", l: [-170, 80], r: [150, -270], hl: "relaxed", hr: "grip", ar: -10 },
  { label: "hush · shh", expr: "hush", l: [-170, 80], r: [-40, -150], hl: "relaxed", hr: "shh" },
  { label: "happy · wave", expr: "happy", l: [-170, 80], r: [250, -460], hl: "relaxed", hr: "wave" },
  { label: "worried · hands on cheeks", expr: "worried", l: "cheekL", r: "cheekR", hl: "cheek", hr: "cheek", al: -12, ar: 22 },
  { label: "sneeze · fists", expr: "sneeze", l: [-100, -110], r: [100, -110], hl: "fist", hr: "fist", tilt: 10 },
];
export const HeroSheet: React.FC = () => {
  const cw = 480, ch = 540;
  return (
    <div style={{ width: 1920, height: 1080, background: "#f3e2c2", position: "relative" }}>
      <Stage light={LIGHTS.lampNight} w={1920} h={1080} world={{ w: 1920, h: 1080 }} post={false}>
        <rect width={1920} height={1080} fill="#f3e2c2" />
        {CELLS.map((c, i) => {
          const ox = (i % 4) * cw + cw / 2, oy = Math.floor(i / 4) * ch + ch - 40;
          const s = 0.62;
          const base: HeroPose = { x: ox, y: oy, s, outfit: STREET, handL: [0, 0], handR: [0, 0], expr: c.expr, headTilt: c.tilt ?? 0, handPoseL: c.hl, handPoseR: c.hr, handAngleL: c.al, handAngleR: c.ar, look: c.look, handAbsR: c.hr === "shh" ? -4 : undefined };
          base.handL = c.l === "cheekL" ? headAnchor(base, [-146, 196]) : add([ox, oy], [(c.l as P)[0] * s, (c.l as P)[1] * s]);
          base.handR = c.r === "cheekR" ? headAnchor(base, [126, 196]) : add([ox, oy], [(c.r as P)[0] * s, (c.r as P)[1] * s]);
          if (c.l === "cheekL") { base.elbowL = [ox - 130 * s, oy - 10 * s]; base.elbowR = [ox + 130 * s, oy - 10 * s]; }
          return <g key={i}><Hero p={base} /><text x={ox} y={oy + 30} textAnchor="middle" fontFamily={SANS} fontSize={22} fontWeight={700} fill="#5a3a20">{c.label}</text></g>;
        })}
      </Stage>
    </div>
  );
};
