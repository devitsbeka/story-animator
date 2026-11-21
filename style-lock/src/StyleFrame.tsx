import React from "react";
import { useCurrentFrame } from "remotion";
import { blink, rnd, wobble } from "./kit/helpers";

// STYLE LOCK: a code-drawn match of the reference image (ref/reference.jpg).
// World is 1024 × 1024. Everything is SVG: thick dark-brown ink outlines, flat warm fills with one
// soft shade tone, a warm lamp at top-left, a sunlight patch on the wall, and paper grain on top.

export const INK = "#2b1a10";
export const PAL = {
  wallHi: "#f3dcb4",
  wall: "#e2c193",
  wallLo: "#c99b66",
  woodHi: "#b9763e",
  wood: "#94582b",
  woodLo: "#5e3519",
  woodDk: "#3e2211",
  head: "#fbf7ee",
  headLo: "#e8dfcf",
  red: "#c8331f",
  redLo: "#93220f",
  redHi: "#de4a31",
  paper: "#f5ecda",
  paperLo: "#dccbab",
  lampShade: "#4a4644",
  lampShadeLo: "#2f2c2b",
  bulb: "#fff4cf",
  note: "#f0b46a",
  noteLo: "#d99a50",
  green: "#5e8f69",
  coffee: "#4a2816",
};

const ink = (w = 5) => ({ stroke: INK, strokeWidth: w, strokeLinejoin: "round" as const, strokeLinecap: "round" as const });

export const StyleDefs: React.FC = () => (
  <defs>
    <linearGradient id="wallG" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stopColor={PAL.wall} />
      <stop offset="0.55" stopColor={PAL.wallHi} />
      <stop offset="1" stopColor={PAL.wallLo} />
    </linearGradient>
    <linearGradient id="deskG" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stopColor="#d59a5c" />
      <stop offset="1" stopColor="#b5733a" />
    </linearGradient>
    <radialGradient id="headG" cx="0.38" cy="0.32" r="0.75">
      <stop offset="0.55" stopColor={PAL.head} />
      <stop offset="1" stopColor={PAL.headLo} />
    </radialGradient>
    <radialGradient id="lampLight" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stopColor="#ffe9b0" stopOpacity="0.85" />
      <stop offset="0.35" stopColor="#ffc56e" stopOpacity="0.32" />
      <stop offset="1" stopColor="#ff9a3a" stopOpacity="0" />
    </radialGradient>
    <radialGradient id="roomVig" cx="0.42" cy="0.4" r="0.8">
      <stop offset="0.5" stopColor="#3a1d08" stopOpacity="0" />
      <stop offset="1" stopColor="#2a1204" stopOpacity="0.55" />
    </radialGradient>
    <filter id="grain" x="0" y="0" width="100%" height="100%">
      <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="7" />
      <feColorMatrix type="matrix" values="0 0 0 0 0.35  0 0 0 0 0.22  0 0 0 0 0.1  0 0 0 0.9 0" />
    </filter>
  </defs>
);

// ---------- props ----------

const Book: React.FC<{ x: number; y: number; w: number; h: number; c: string; page?: boolean; tilt?: number }> = ({ x, y, w, h, c, page = true, tilt = 0 }) => (
  <g transform={`translate(${x} ${y}) rotate(${tilt})`}>
    <rect x={0} y={0} width={w} height={h} rx={3} fill={c} {...ink(3.5)} />
    {page && <rect x={w * 0.05} y={h * 0.28} width={w * 0.9} height={h * 0.44} fill={PAL.paper} opacity={0.9} />}
    {page && <line x1={w * 0.05} y1={h * 0.5} x2={w * 0.95} y2={h * 0.5} stroke={PAL.paperLo} strokeWidth={1.5} />}
  </g>
);

const BOOK_COLS = ["#e9e0cc", "#d9b25c", "#c9c1e0", "#efe6d2", "#d3a24a", "#e7d9b8", "#b8b1cf", "#f0e8d6"];

const Stack: React.FC<{ x: number; y: number; n: number; w: number; h: number; seed: string }> = ({ x, y, n, w, h, seed }) => (
  <g>
    {Array.from({ length: n }, (_, k) => {
      const dx = (rnd(`${seed}dx${k}`) - 0.5) * 18;
      const dw = (rnd(`${seed}dw${k}`) - 0.5) * 22;
      const c = BOOK_COLS[Math.floor(rnd(`${seed}c${k}`) * BOOK_COLS.length)];
      return <Book key={k} x={x + dx} y={y - (k + 1) * h} w={w + dw} h={h} c={c} />;
    })}
  </g>
);

const Spines: React.FC<{ x: number; y: number; n: number; seed: string; maxH: number }> = ({ x, y, n, seed, maxH }) => {
  let cx = x;
  const cols = ["#6b4a33", "#8a6a4a", "#a98a64", "#4d3a2c", "#c4a477", "#7c5b3c", "#e3cfa8"];
  return (
    <g>
      {Array.from({ length: n }, (_, k) => {
        const w = 16 + rnd(`${seed}w${k}`) * 14;
        const h = maxH * (0.7 + rnd(`${seed}h${k}`) * 0.3);
        const el = <rect key={k} x={cx} y={y - h} width={w} height={h} rx={2} fill={cols[Math.floor(rnd(`${seed}c${k}`) * cols.length)]} {...ink(3)} />;
        cx += w + 1;
        return el;
      })}
    </g>
  );
};

const Crumple: React.FC<{ x: number; y: number; s?: number }> = ({ x, y, s = 1 }) => (
  <g transform={`translate(${x} ${y}) scale(${s})`}>
    <path d="M -42,8 C -48,-14 -30,-34 -8,-32 C 6,-44 32,-36 38,-18 C 52,-6 46,20 28,26 C 14,40 -14,38 -26,28 C -42,26 -48,18 -42,8 Z" fill="#f4efe4" {...ink(3.5)} />
    <path d="M -24,-8 L -6,2 L -14,18 M 4,-22 L 10,-4 L 26,0 M -2,6 L 14,14" fill="none" stroke="#b9ac98" strokeWidth={2.5} strokeLinecap="round" />
    <path d="M 10,22 C 22,18 32,10 34,-2" fill="none" stroke="#d6cbb8" strokeWidth={6} opacity={0.8} />
  </g>
);

const Pencil: React.FC<{ x: number; y: number; len: number; rot: number; c?: string }> = ({ x, y, len, rot, c = "#e3b23c" }) => (
  <g transform={`translate(${x} ${y}) rotate(${rot})`}>
    <rect x={0} y={-7} width={len} height={14} rx={3} fill={c} {...ink(3)} />
    <rect x={len * 0.62} y={-7} width={len * 0.12} height={14} fill="#3a3a3a" />
    <path d={`M ${len},-7 L ${len + 22},0 L ${len},7 Z`} fill="#f1d9b0" {...ink(3)} />
    <path d={`M ${len + 14},-2.5 L ${len + 22},0 L ${len + 14},2.5 Z`} fill={INK} />
  </g>
);

const Lines: React.FC<{ x: number; y: number; w: number; n: number; gap: number; c?: string; sw?: number }> = ({ x, y, w, n, gap, c = "#b9a88a", sw = 2 }) => (
  <g>
    {Array.from({ length: n }, (_, k) => (
      <line key={k} x1={x} y1={y + k * gap} x2={x + w * (k === n - 1 ? 0.6 : 0.95 - (k % 3) * 0.05)} y2={y + k * gap} stroke={c} strokeWidth={sw} strokeLinecap="round" />
    ))}
  </g>
);

// ---------- the character ----------

// The hero: a big white round head, worried brows, solid black oval eyes, tiny mouth,
// red ribbed sweater, white cartoon hands cupping the cheeks, elbows on the desk.
export const Hero: React.FC<{ f: number; mood?: "worried" | "neutral" | "happy" }> = ({ f, mood = "worried" }) => {
  const breathe = Math.sin(f * 0.07);
  const sway = wobble(f, 3, 0.4) * 1.0;
  const o = blink(f, 11);
  const browLift = mood === "worried" ? 1 : 0;
  const lift = breathe * 3; // head and hands rise slightly on the in-breath
  return (
    <g>
      {/* torso between the arms */}
      <path d="M 380,650 L 420,505 C 460,482 590,482 630,505 L 670,650 Z" fill={PAL.red} {...ink(6)} />
      <path d="M 420,520 C 470,505 560,505 610,520" fill="none" stroke={PAL.redLo} strokeWidth={10} opacity={0.6} />
      <Hatch x={430} y={512} n={9} len={22} gap={18} />
      {/* arms */}
      <Arm side={-1} lift={lift} />
      <Arm side={1} lift={lift} />
      {/* head */}
      <g transform={`translate(0 ${-lift}) rotate(${sway} 512 470)`}>
        <ellipse cx={522} cy={300} rx={194} ry={178} fill="url(#headG)" {...ink(7)} />
        {/* brows */}
        <path d={`M 384,${326 - browLift * 2} Q 416,${316 - browLift * 8} 452,${304 - browLift * 6}`} fill="none" {...ink(6)} />
        <path d={`M 528,${304 - browLift * 6} Q 566,${314 - browLift * 8} 600,${326 - browLift * 2}`} fill="none" {...ink(6)} />
        {/* eyes */}
        {[428, 552].map((ex, i) => (
          <g key={i} transform={`translate(${ex} 356) scale(1 ${Math.max(0.08, o)})`}>
            <ellipse rx={18} ry={26} fill={INK} />
          </g>
        ))}
        {/* mouth + freckle dots */}
        {mood === "happy" ? (
          <path d="M 468,400 Q 484,414 500,400" fill="none" {...ink(5)} />
        ) : (
          <ellipse cx={484} cy={398} rx={3.5} ry={3} fill={INK} />
        )}
        <circle cx={464} cy={394} r={1.8} fill="#9b8e7e" />
        {/* worry ticks above the head */}
        <path d="M 352,104 L 380,118 M 300,182 L 324,170" fill="none" {...ink(4)} />
        <path d="M 640,88 L 664,74" fill="none" stroke="#fff6e4" strokeWidth={4} strokeLinecap="round" />
      </g>
      {/* hands on cheeks */}
      <g transform={`translate(0 ${-lift}) rotate(${sway * 0.6} 512 470)`}>
        <Hand x={350} y={428} flip={false} />
        <Hand x={690} y={428} flip />
      </g>
    </g>
  );
};

const Hatch: React.FC<{ x: number; y: number; n: number; len: number; gap: number; c?: string }> = ({ x, y, n, len, gap, c = PAL.redLo }) => (
  <g opacity={0.7}>
    {Array.from({ length: n }, (_, k) => (
      <line key={k} x1={x + k * gap} y1={y} x2={x + k * gap - len * 0.4} y2={y + len} stroke={c} strokeWidth={2.5} strokeLinecap="round" />
    ))}
  </g>
);

// One forearm as a tilted tube: wrist (with ribbed cuff) at the cheek, elbow resting on the desk.
const Arm: React.FC<{ side: -1 | 1; lift: number }> = ({ side, lift }) => {
  const wx = side < 0 ? 392 : 652;
  const wy = 478 - lift;
  const rot = side < 0 ? 24 : -24;
  return (
    <g transform={`translate(${wx} ${wy}) rotate(${rot})`}>
      <path d="M -60,10 L 60,10 C 66,80 70,140 64,190 C 60,215 -60,215 -64,190 C -70,140 -66,80 -60,10 Z" fill={PAL.red} {...ink(6)} />
      <path d={`M ${side < 0 ? 44 : -44},40 C ${side < 0 ? 52 : -52},100 ${side < 0 ? 52 : -52},150 ${side < 0 ? 46 : -46},195`} fill="none" stroke={PAL.redLo} strokeWidth={16} opacity={0.55} strokeLinecap="round" />
      <path d={`M ${side < 0 ? -40 : 40},50 C ${side < 0 ? -46 : 46},100 ${side < 0 ? -46 : 46},140 ${side < 0 ? -40 : 40},180`} fill="none" stroke={PAL.redHi} strokeWidth={8} opacity={0.5} strokeLinecap="round" />
      <path d="M -58,-30 L 58,-30 L 60,18 L -60,18 Z" fill={PAL.red} {...ink(5)} />
      {Array.from({ length: 9 }, (_, k) => (
        <line key={k} x1={-48 + k * 12} y1={-26} x2={-48 + k * 12} y2={14} stroke={PAL.redLo} strokeWidth={2.5} />
      ))}
    </g>
  );
};

const Hand: React.FC<{ x: number; y: number; flip: boolean }> = ({ x, y, flip }) => (
  <g transform={`translate(${x} ${y}) scale(${flip ? -1.02 : 1.02} 1.02) rotate(14)`}>
    <path
      d="M -46,58 C -58,30 -56,-6 -44,-30 C -38,-46 -24,-46 -22,-30 C -22,-52 -6,-58 2,-44 C 8,-60 26,-58 26,-40 C 34,-52 50,-44 46,-26 C 44,-6 40,18 40,36 C 40,56 26,70 4,72 C -20,74 -40,70 -46,58 Z"
      fill={PAL.head}
      {...ink(6)}
    />
    <path d="M -22,-30 C -21,-12 -20,0 -18,10 M 2,-44 C 2,-24 1,-10 1,4 M 26,-40 C 25,-22 23,-8 22,6" fill="none" {...ink(4)} />
    <path d="M 40,0 C 30,20 30,40 34,52" fill="none" stroke={PAL.headLo} strokeWidth={10} opacity={0.9} strokeLinecap="round" />
  </g>
);

// ---------- the room ----------

export const Room: React.FC<{ f: number }> = ({ f }) => {
  const flick = 1 + 0.03 * Math.sin(f * 0.5) + 0.02 * Math.sin(f * 1.3);
  return (
    <g>
      {/* wall */}
      <rect x={-200} y={-200} width={1500} height={1100} fill="url(#wallG)" />
      {/* sunlight patch */}
      <path d="M 420,-10 L 880,-10 L 880,300 L 600,420 L 470,420 Z" fill="#fff1d4" opacity={0.45} />
      <path d="M 880,-10 L 880,300 L 600,420" fill="none" stroke="#d3a774" strokeWidth={10} opacity={0.35} />
      {/* faint wall marks */}
      <path d="M 352,90 L 378,104 M 380,52 L 396,74 M 690,92 Q 712,74 735,96 Q 752,82 760,98" fill="none" stroke="#c59a68" strokeWidth={4} strokeLinecap="round" opacity={0.7} />

      {/* left shelf */}
      <rect x={-60} y={-40} width={250} height={700} fill={PAL.wood} {...ink(6)} />
      <rect x={-40} y={-20} width={210} height={660} fill={PAL.woodLo} />
      <rect x={-50} y={110} width={235} height={20} fill={PAL.woodHi} {...ink(4)} />
      <rect x={-50} y={300} width={235} height={20} fill={PAL.woodHi} {...ink(4)} />
      <Stack x={-20} y={110} n={5} w={130} h={22} seed="ls1" />
      <Spines x={-30} y={300} n={4} seed="lsp" maxH={140} />

      {/* right shelf */}
      <rect x={900} y={-40} width={200} height={700} fill={PAL.wood} {...ink(6)} />
      <rect x={918} y={-20} width={180} height={660} fill={PAL.woodLo} />
      <rect x={890} y={150} width={200} height={18} fill={PAL.woodHi} {...ink(4)} />
      <rect x={890} y={450} width={200} height={18} fill={PAL.woodHi} {...ink(4)} />
      <Stack x={960} y={150} n={5} w={110} h={20} seed="rs1" />
      <Spines x={925} y={450} n={5} seed="rsp" maxH={210} />
      {/* leaning tall books between shelf and wall */}
      <Spines x={860} y={460} n={2} seed="lean" maxH={190} />

      {/* wall papers and notes */}
      <g transform="rotate(-1 840 110)">
        <rect x={782} y={40} width={112} height={135} fill={PAL.paper} {...ink(3.5)} />
        <Lines x={798} y={70} w={80} n={6} gap={15} />
      </g>
      <rect x={750} y={262} width={80} height={86} fill={PAL.note} {...ink(3)} />
      <path d="M 815,262 L 830,262 L 830,280 Z" fill={PAL.noteLo} />
      <rect x={780} y={198} width={22} height={24} fill="#f5d9a8" {...ink(2.5)} />
      <rect x={885} y={210} width={20} height={22} fill="#f5d9a8" {...ink(2.5)} />

      {/* chair back */}
      <path d="M 690,640 L 700,420 C 702,385 725,372 760,372 L 860,376 C 892,378 905,400 902,430 L 890,640 Z" fill={PAL.wood} {...ink(6)} />
      <path d="M 712,640 L 722,430 C 724,404 740,394 765,394 L 850,397 C 875,398 882,415 880,440 L 870,640 Z" fill={PAL.woodLo} opacity={0.55} />

      {/* lamp glow on wall */}
      <circle cx={210} cy={230} r={360 * flick} fill="url(#lampLight)" style={{ mixBlendMode: "screen" }} />
    </g>
  );
};

export const Lamp: React.FC<{ f: number }> = ({ f }) => {
  const flick = 0.92 + 0.08 * Math.sin(f * 0.45) * Math.sin(f * 0.13);
  return (
    <g>
      {/* arm */}
      <path d="M -40,260 L 95,150" stroke={INK} strokeWidth={22} strokeLinecap="round" />
      <path d="M -40,260 L 95,150" stroke="#5a5552" strokeWidth={13} strokeLinecap="round" />
      <path d="M 70,60 L 130,128" stroke={INK} strokeWidth={18} strokeLinecap="round" />
      <path d="M 70,60 L 130,128" stroke="#5a5552" strokeWidth={10} strokeLinecap="round" />
      <circle cx={100} cy={148} r={18} fill="#6a6461" {...ink(5)} />
      {/* shade */}
      <g transform="translate(190 160) rotate(-32)">
        <path d="M -48,-62 L 48,-62 L 92,58 L -92,58 Z" fill={PAL.lampShade} {...ink(6)} />
        <path d="M 10,-62 L 48,-62 L 92,58 L 46,58 Z" fill={PAL.lampShadeLo} opacity={0.6} />
        <path d="M -40,-52 L -10,-52 L -44,48 L -80,48 Z" fill="#7c7672" opacity={0.35} />
        <ellipse cx={0} cy={58} rx={92} ry={22} fill={PAL.bulb} opacity={flick} {...ink(5)} />
        <ellipse cx={0} cy={56} rx={42} ry={14} fill="#fff" opacity={0.9 * flick} />
      </g>
      <circle cx={232} cy={235} r={110} fill="url(#lampLight)" opacity={flick} style={{ mixBlendMode: "screen" }} />
    </g>
  );
};

export const Desk: React.FC<{ f: number }> = ({ f }) => {
  const steam = (k: number) => Math.sin(f * 0.06 + k) * 6;
  return (
    <g>
      {/* desk top and front */}
      <path d="M -60,640 L 1100,620 L 1100,935 L -60,935 Z" fill="url(#deskG)" {...ink(6)} />
      <path d="M -60,640 L 1100,620" fill="none" stroke="#d79b5e" strokeWidth={6} opacity={0.6} transform="translate(0 6)" />
      {/* grain */}
      {[700, 760, 830, 890].map((y, k) => (
        <path key={k} d={`M -40,${y} C 200,${y - 8 + k * 2} 500,${y + 6} 1080,${y - 6}`} fill="none" stroke={PAL.wood} strokeWidth={2.5} opacity={0.45} />
      ))}
      <rect x={-60} y={935} width={1160} height={40} fill={PAL.woodLo} {...ink(6)} />
      <rect x={-60} y={975} width={1160} height={120} fill={PAL.woodDk} {...ink(6)} />
      <rect x={20} y={975} width={240} height={70} fill="#4a2a15" {...ink(4)} />
      <rect x={300} y={975} width={250} height={70} fill="#4a2a15" {...ink(4)} />
      <rect x={810} y={975} width={240} height={70} fill="#4a2a15" {...ink(4)} />

      {/* cast shadows */}
      <ellipse cx={180} cy={760} rx={110} ry={18} fill="#6b3712" opacity={0.35} />
      <ellipse cx={980} cy={705} rx={120} ry={14} fill="#6b3712" opacity={0.3} />
      <ellipse cx={270} cy={836} rx={52} ry={10} fill="#6b3712" opacity={0.35} />
      {/* left book stack */}
      <Stack x={-30} y={720} n={14} w={230} h={26} seed="dl" />
      {/* right book stack */}
      <Stack x={930} y={705} n={8} w={150} h={24} seed="dr" />

      {/* mug */}
      <g transform="translate(170 680)">
        <path d="M 52,-40 C 100,-44 100,30 50,24" fill="none" {...ink(18)} />
        <path d="M 52,-40 C 100,-44 100,30 50,24" fill="none" stroke={PAL.paper} strokeWidth={9} />
        <path d="M -72,-60 L 66,-60 L 58,70 C 56,86 -60,86 -64,70 Z" fill={PAL.paper} {...ink(6)} />
        <path d="M 30,-55 L 62,-55 L 54,68 C 50,78 30,80 20,80 Z" fill={PAL.paperLo} opacity={0.6} />
        <ellipse cx={-3} cy={-60} rx={69} ry={18} fill={PAL.paper} {...ink(5)} />
        <ellipse cx={-3} cy={-58} rx={58} ry={12} fill={PAL.coffee} />
        {[0, 1].map((k) => (
          <path key={k} d={`M ${-20 + k * 30},-86 C ${-30 + k * 30 + steam(k)},-110 ${-10 + k * 30 - steam(k)},-130 ${-20 + k * 30},-155`} fill="none" stroke="#fff4e0" strokeWidth={5} strokeLinecap="round" opacity={0.35} />
        ))}
      </g>

      {/* open book: pages bow up from the spine, page edges stacked underneath */}
      <g>
        <ellipse cx={510} cy={770} rx={300} ry={24} fill="#6b3712" opacity={0.35} />
        <path d="M 210,762 C 330,778 440,778 512,770 C 590,778 700,778 800,764 L 806,786 C 700,800 590,800 512,792 C 440,800 330,800 206,786 Z" fill={PAL.woodLo} {...ink(5)} />
        {[0, 1, 2].map((k) => (
          <path key={k} d={`M ${214 + k * 4},${756 + k * 8} C 330,${770 + k * 8} 440,${770 + k * 8} 512,${762 + k * 8} C 590,${770 + k * 8} 700,${770 + k * 8} ${796 - k * 4},${758 + k * 8}`} fill={PAL.paper} {...ink(3)} />
        ))}
        <path d="M 240,676 C 320,646 430,648 508,676 L 512,762 C 440,770 330,770 214,756 Z" fill={PAL.paper} {...ink(5)} />
        <path d="M 508,676 C 590,648 700,646 770,676 L 796,758 C 700,770 590,770 512,762 Z" fill={PAL.paper} {...ink(5)} />
        <path d="M 508,676 L 512,762" fill="none" {...ink(4)} />
        <path d="M 470,670 C 490,680 500,700 505,750 L 512,762 L 508,676 Z" fill={PAL.paperLo} opacity={0.8} />
        <path d="M 548,670 C 528,680 518,700 515,750 L 512,762 L 508,676 Z" fill={PAL.paperLo} opacity={0.6} />
        {Array.from({ length: 6 }, (_, k) => (
          <g key={k}>
            <path d={`M ${262 - k * 4},${682 + k * 12} C 330,${662 + k * 12} 420,${662 + k * 12} 480,${686 + k * 12}`} fill="none" stroke="#b7a88d" strokeWidth={2.2} />
            <path d={`M 540,${686 + k * 12} C 600,${662 + k * 12} 690,${662 + k * 12} ${758 + k * 4},${684 + k * 12}`} fill="none" stroke="#b7a88d" strokeWidth={2.2} />
          </g>
        ))}
      </g>

      {/* loose papers */}
      <g transform="rotate(2 560 800)">
        <path d="M 350,780 L 700,770 L 720,850 L 360,860 Z" fill={PAL.paper} {...ink(4)} />
        <Lines x={380} y={795} w={300} n={4} gap={14} />
      </g>
      <path d="M 640,770 L 820,760 L 830,800 L 650,810 Z" fill="#f2e9d6" {...ink(3.5)} />
      <path d="M 370,820 L 470,812 L 474,856 L 372,862 Z" fill={PAL.note} {...ink(3)} />
      <path d="M 830,650 L 905,644 L 910,690 L 834,694 Z" fill="#f3d6b2" {...ink(3)} />

      {/* pens */}
      <Pencil x={700} y={752} len={120} rot={-38} c="#cfa64a" />
      <Pencil x={806} y={750} len={110} rot={-16} c="#3b3b3b" />
      <Pencil x={650} y={865} len={130} rot={-20} c="#e3b23c" />

      {/* green books + phone */}
      <g>
        <path d="M 800,760 L 1010,735 L 1030,800 L 810,830 Z" fill={PAL.green} {...ink(5)} />
        <path d="M 810,830 L 1030,800 L 1032,830 L 812,862 Z" fill={PAL.paper} {...ink(4)} />
        <path d="M 812,862 L 1032,830 L 1034,860 L 814,892 Z" fill="#c9c1e0" {...ink(4)} />
      </g>
      <g transform="rotate(-12 820 860)">
        <rect x={745} y={835} width={160} height={50} rx={10} fill="#3a3533" {...ink(5)} />
        <rect x={755} y={842} width={140} height={36} rx={6} fill="#57504c" />
      </g>

      {/* crumpled paper */}
      <Crumple x={270} y={808} s={1.15} />
      <Crumple x={850} y={612} s={1.05} />
    </g>
  );
};

// ---------- the full reference shot ----------

export const StyleShot: React.FC<{ f: number }> = ({ f }) => (
  <g>
    <Room f={f} />
    <Hero f={f} />
    <Desk f={f} />
    <Lamp f={f} />
    <rect x={-200} y={-200} width={1500} height={1500} fill="#ffa040" opacity={0.13} style={{ mixBlendMode: "multiply" }} />
    <rect x={-200} y={-200} width={1500} height={1500} fill="url(#roomVig)" />
  </g>
);

export const Grain: React.FC<{ w: number; h: number }> = ({ w, h }) => (
  <rect width={w} height={h} filter="url(#grain)" opacity={0.12} style={{ mixBlendMode: "multiply" }} />
);

export const StyleSquare: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <svg width={1024} height={1024} viewBox="0 0 1024 1024">
      <StyleDefs />
      <StyleShot f={f} />
      <Grain w={1024} h={1024} />
    </svg>
  );
};

export const StyleVertical: React.FC = () => {
  const f = useCurrentFrame();
  // 9:16 framing of the same world: 1080 × 1920, scaled so the room fills the height.
  const s = 1920 / 1100;
  const cx = 512;
  return (
    <svg width={1080} height={1920} viewBox="0 0 1080 1920">
      <StyleDefs />
      <rect width={1080} height={1920} fill={PAL.wall} />
      <g transform={`translate(${540 - cx * s} ${-60}) scale(${s})`}>
        <StyleShot f={f} />
      </g>
      <Grain w={1080} h={1920} />
    </svg>
  );
};
