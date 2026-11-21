import React from "react";
import { P, add, ellipse, lerpP, qcurve, quad, rng, rot, rr, rrect, tube } from "./geom";
import { Contact, Line, Shape } from "./render";
import { INK, MAT, Material, WEIGHT } from "./theme";

// ============================================================================
// PROPS. Every prop is parametric (numbers and a seed in, drawing out) and
// built only from Shape / Line, so it inherits the house style automatically.
// Coordinates are world pixels; `x, y` is the prop's anchor (usually bottom-centre).
// ============================================================================

const place = (pts: P[], x: number, y: number, r = 0, s = 1): P[] => pts.map((p) => add(rot([p[0] * s, p[1] * s], r), [x, y]));

// ---------- room ----------

export const Wall: React.FC<{ w: number; h: number; mat?: Material; patch?: P[]; patchOpacity?: number; shadows?: P[][]; marks?: number; seed?: number }> = ({ w, h, mat = MAT.wall, patch, patchOpacity = 0.75, shadows = [], marks = 6, seed = 1 }) => {
  const r = rng(`wall${seed}`);
  return (
    <g>
      <defs>
        <linearGradient id="wallG" x1="0" y1="0" x2="0.3" y2="1">
          <stop offset="0" stopColor={mat.lit} />
          <stop offset="0.6" stopColor={mat.base} />
          <stop offset="1" stopColor={mat.shade} />
        </linearGradient>
      </defs>
      <rect x={-w} y={-h} width={w * 3} height={h * 3} fill="url(#wallG)" />
      <filter id="softEdge" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="6" /></filter>
      {patch && <path d={"M" + patch.map((p) => p.join(",")).join("L") + "Z"} fill="#fff4d6" opacity={patchOpacity} filter="url(#softEdge)" />}
      {shadows.map((sh, i) => <path key={i} d={"M" + sh.map((p) => p.join(",")).join("L") + "Z"} fill={mat.shade} opacity={0.75} filter="url(#softEdge)" style={{ mixBlendMode: "multiply" }} />)}
      {/* a few hand marks so the wall is a painted surface, not a fill */}
      {Array.from({ length: marks }, (_, i) => {
        const x = rr(r, 0, w), y = rr(r, 0, h * 0.6), l = rr(r, 10, 26), a = rr(r, -30, 30);
        return <Line key={i} pts={[[x, y], rot([x + l, y], a, [x, y])]} w={2.2} color={mat.line} opacity={0.6} seed={i} />;
      })}
    </g>
  );
};

export const PinnedPaper: React.FC<{ x: number; y: number; w: number; h: number; r?: number; lines?: number; seed?: number; mat?: Material }> = ({ x, y, w, h, r = 0, lines = 6, seed = 1, mat = MAT.paper }) => {
  const pts = place(rrect(-w / 2, -h / 2, w, h, 2), x, y, r);
  return (
    <Shape pts={pts} mat={mat} ink={WEIGHT.small} inkColor={mat.line} seed={seed} shade={0.05} lit={0}>
      {Array.from({ length: lines }, (_, i) => {
        const yy = -h / 2 + h * 0.22 + (i * h * 0.65) / lines;
        const ww = w * (i === lines - 1 ? 0.45 : 0.72 - (i % 3) * 0.06);
        return <Line key={i} pts={place([[-w * 0.36, yy], [-w * 0.36 + ww, yy]], x, y, r)} w={2} color={mat.line} seed={seed * 10 + i} />;
      })}
    </Shape>
  );
};

export const StickyNote: React.FC<{ x: number; y: number; s?: number; r?: number; mat?: Material; seed?: number; ink?: number }> = ({ x, y, s = 70, r = 0, mat = MAT.note, seed = 1, ink = WEIGHT.small }) => (
  <Shape pts={place(rrect(-s / 2, -s / 2, s, s * 0.95, 2), x, y, r)} mat={mat} ink={ink} inkColor={mat.line} seed={seed} shade={0.1} lit={0.06} round={0.6} />
);

// ---------- furniture ----------

// Desk: top surface as a perspective quad, a front edge, and a dark underside with drawers.
export const Desk: React.FC<{ top: [P, P, P, P]; thick?: number; under?: number; mat?: Material; seed?: number; grain?: number }> = ({ top, thick = 46, under = 140, mat = MAT.woodLight, seed = 1, grain = 7 }) => {
  const [a, b, c, d] = top; // back-left, back-right, front-right, front-left
  const front: P[] = [d, c, add(c, [0, thick]), add(d, [0, thick])];
  const below: P[] = [add(d, [0, thick]), add(c, [0, thick]), add(c, [0, thick + under]), add(d, [0, thick + under])];
  const r = rng(`desk${seed}`);
  return (
    <g>
      <Shape pts={below} mat={MAT.woodDark} round={0} wob={0.3} shade={0} lit={0} seed={seed + 2} />
      {[0.03, 0.36, 0.69].map((t, i) => {
        const x0 = lerpP(add(d, [0, thick]), add(c, [0, thick]), t + 0.01), x1 = lerpP(add(d, [0, thick]), add(c, [0, thick]), t + 0.3);
        return <Shape key={i} pts={[add(x0, [0, 14]), add(x1, [0, 14]), add(x1, [0, 92]), add(x0, [0, 92])]} mat={MAT.chair} round={0} wob={0.3} shade={0.08} lit={0} ink={WEIGHT.small} seed={seed + 10 + i} />;
      })}
      <Shape pts={front} mat={MAT.wood} round={0} wob={0.4} shade={0} lit={0.12} seed={seed + 1} />
      <Shape pts={quad(a, b, c, d, 6)} mat={mat} round={0.5} wob={0.5} shade={0} lit={0} seed={seed} ink={WEIGHT.outline}>
        {/* wood grain running along the desk */}
        {Array.from({ length: grain }, (_, i) => {
          const t = (i + 0.5) / grain + rr(r, -0.03, 0.03);
          const p0 = lerpP(a, d, t), p1 = lerpP(b, c, t);
          const mid = lerpP(p0, p1, rr(r, 0.3, 0.7));
          return <Line key={i} pts={qcurve(p0, add(mid, [0, rr(r, -8, 8)]), p1, 16)} w={1.6} color={mat.line} opacity={0.35} seed={seed * 7 + i} />;
        })}
        {/* the lit front lip */}
        <Line pts={[add(d, [0, -5]), add(c, [0, -5])]} w={5} color={mat.lit} opacity={0.6} wob={0.3} />
      </Shape>
    </g>
  );
};

export const ChairBack: React.FC<{ x: number; y: number; w: number; h: number; seed?: number }> = ({ x, y, w, h, seed = 1 }) => {
  const outer = place([[-w / 2, h], ...qcurve([-w / 2, h * 0.25], [-w / 2, -h * 0.02], [-w * 0.1, -h * 0.02], 8), ...qcurve([w * 0.1, -h * 0.02], [w / 2, -h * 0.02], [w / 2, h * 0.25], 8), [w / 2, h]], x, y);
  const inner = place([[-w * 0.4, h], ...qcurve([-w * 0.4, h * 0.3], [-w * 0.4, h * 0.08], [-w * 0.08, h * 0.08], 8), ...qcurve([w * 0.08, h * 0.08], [w * 0.4, h * 0.08], [w * 0.4, h * 0.3], 8), [w * 0.4, h]], x, y);
  return (
    <g>
      <Shape pts={outer} mat={MAT.wood} seed={seed} round={0.8} shade={0.05} lit={0.12} litOpacity={0.8} />
      <Shape pts={inner} mat={MAT.chair} seed={seed + 1} round={0.8} ink={0} shade={0.12} lit={0.04} />
    </g>
  );
};

// Bookcase: frame, shelves, and seeded contents (rows of spines, small stacks, jars).
export const Bookcase: React.FC<{ x: number; y: number; w: number; h: number; rows: number[]; seed?: number }> = ({ x, y, w, h, rows, seed = 1 }) => {
  const r = rng(`case${seed}`);
  const boards = rows.map((t) => y + t * h);
  return (
    <g>
      <Shape pts={rrect(x, y, w, h, 3)} mat={MAT.wood} round={0} wob={0.4} shade={0} lit={0} seed={seed} />
      <Shape pts={rrect(x + 14, y + 10, w - 28, h - 20, 2)} mat={MAT.woodDark} round={0} wob={0.3} shade={0.04} lit={0} ink={WEIGHT.small} seed={seed + 1} />
      {boards.map((by, i) => {
        const prev = i === 0 ? y + 10 : boards[i - 1] + 16;
        const room = by - prev;
        // books standing on the board
        let cx = x + 18;
        const spines: React.ReactNode[] = [];
        let k = 0;
        while (cx < x + w - 40) {
          if (r() < 0.22) {
            // a lying stack instead
            const sw = rr(r, 46, 70), n = 2 + Math.floor(r() * 3);
            for (let j = 0; j < n; j++) spines.push(<Book key={`s${k++}`} x={cx + sw / 2 + rr(r, -3, 3)} y={by - j * 15} w={sw} h={15} seed={seed * 100 + i * 10 + j} />);
            cx += sw + 6;
          } else {
            const bw = rr(r, 14, 24), bh = room * rr(r, 0.62, 0.92);
            const mats = [MAT.cream, MAT.paperOld, MAT.wood, MAT.woodLight, MAT.lilac, MAT.chair];
            spines.push(
              <Shape key={`b${k++}`} pts={rrect(cx, by - bh, bw, bh, 2)} mat={mats[Math.floor(r() * mats.length)]} round={0} wob={0.3} shade={0.12} lit={0.05} ink={WEIGHT.small} seed={seed * 50 + k}>
                <Line pts={[[cx + 3, by - bh * 0.78], [cx + bw - 3, by - bh * 0.78]]} w={1.5} color={INK} opacity={0.35} />
              </Shape>,
            );
            cx += bw + 1;
          }
        }
        return (
          <g key={i}>
            {spines}
            <Shape pts={rrect(x + 4, by, w - 8, 16, 2)} mat={MAT.woodLight} round={0} wob={0.3} shade={0.2} lit={0.1} ink={WEIGHT.small} seed={seed + 20 + i} />
          </g>
        );
      })}
    </g>
  );
};

// ---------- books & paper ----------

// A closed book lying flat, seen from the front: cover, page block, cover.
export const Book: React.FC<{ x: number; y: number; w: number; h: number; r?: number; mat?: Material; seed?: number; tab?: boolean }> = ({ x, y, w, h, r = 0, mat, seed = 1, tab = false }) => {
  const g = rng(`book${seed}`);
  const mats = [MAT.lilac, MAT.mustard, MAT.cream, MAT.paperOld, MAT.lilac, MAT.wood, MAT.green, MAT.mustard];
  const cover = mat ?? mats[Math.floor(g() * mats.length)];
  const body = place(rrect(-w / 2, -h, w, h, 3), x, y, r);
  const pages = place(rrect(-w / 2 + 5, -h * 0.74, w - 8, h * 0.5, 1.5), x, y, r);
  const lines = Math.max(1, Math.floor(h / 7));
  return (
    <g>
      <Shape pts={body} mat={cover} round={0.4} wob={0.4} shade={0.08} lit={0.05} ink={WEIGHT.small} seed={seed} />
      <Shape pts={pages} mat={MAT.paperOld} round={0.3} wob={0.3} shade={0.25} lit={0} ink={1.8} inkColor={INK} seed={seed + 1}>
        {Array.from({ length: lines }, (_, i) => {
          const yy = -h * 0.74 + ((i + 1) * h * 0.5) / (lines + 1);
          return <Line key={i} pts={place([[-w / 2 + 6, yy], [w / 2 - 4, yy]], x, y, r)} w={1.1} color={MAT.paper.line} opacity={0.7} seed={seed * 3 + i} />;
        })}
      </Shape>
      {tab && <Shape pts={place(rrect(w * 0.1, -h * 0.7, 26, h * 0.5, 1), x, y, r)} mat={MAT.note} ink={1.6} inkColor={MAT.note.line} shade={0} lit={0} round={0} seed={seed + 5} />}
    </g>
  );
};

export const BookStack: React.FC<{ x: number; y: number; n: number; w: number; seed?: number; lean?: number; tabs?: number }> = ({ x, y, n, w, seed = 1, lean = 0, tabs = 0.25 }) => {
  const r = rng(`stack${seed}`);
  let yy = y;
  const books: React.ReactNode[] = [];
  for (let i = 0; i < n; i++) {
    const h = rr(r, 20, 34), bw = w * rr(r, 0.8, 1.06), dx = rr(r, -16, 16) + lean * i;
    books.push(<Book key={i} x={x + dx} y={yy} w={bw} h={h} r={rr(r, -2.2, 2.2)} seed={seed * 100 + i} tab={r() < tabs} />);
    yy -= h - 1;
  }
  return <g><Contact x={x} y={y + 2} w={w * 1.15} opacity={0.35} />{books}</g>;
};

// An open book lying on a desk, seen from the front and above: pages bow up from the spine,
// layered page edges underneath, the cover peeking out below. (cx, cy) = bottom of the spine.
export const OpenBook: React.FC<{ cx: number; cy: number; w: number; d?: number; r?: number; seed?: number; lines?: number }> = ({ cx, cy, w, d = 112, r = 0, seed = 1, lines = 7 }) => {
  const hw = w / 2;
  const P2 = (pts: P[]) => place(pts, cx, cy, r);
  const spineTop: P = [-6, -d + 8];
  // left page: outer-top corner, bowed top edge up to the spine, spine, bowed bottom edge
  const left = P2([...qcurve([-hw + 26, -d + 20], [-hw * 0.45, -d - 26], spineTop, 10), ...qcurve([0, -6], [-hw * 0.5, 8], [-hw - 4, -10], 10)]);
  const right = P2([...qcurve(spineTop, [hw * 0.45, -d - 26], [hw - 18, -d + 16], 10), ...qcurve([hw + 10, -12], [hw * 0.5, 8], [0, -6], 10)]);
  const block = P2([[-hw - 6, -14], ...qcurve([-hw * 0.5, 6], [0, -4], [0, -4], 2).slice(1), ...qcurve([hw * 0.5, 6], [hw + 12, -14], [hw + 12, -14], 2).slice(0, 1), [hw + 12, -14], [hw + 16, 12], ...qcurve([hw * 0.5, 30], [0, 22], [0, 22], 2).slice(0, 1), [0, 22], [-hw * 0.5, 30], [-hw - 10, 10]]);
  const cover = P2([[-hw - 12, 6], [-hw * 0.5, 28], [0, 20], [hw * 0.5, 28], [hw + 18, 6], [hw + 20, 20], [hw * 0.5, 40], [0, 32], [-hw * 0.5, 40], [-hw - 14, 20]]);
  const textLine = (s: number, i: number) => {
    const t = (i + 1) / (lines + 1);
    const y0 = -d + 14 + t * (d - 26);
    const bow = (1 - t) * 18;
    const xs = s < 0 ? [-hw * 0.86 + t * 6, -hw * 0.08] : [hw * 0.08, hw * 0.84 - t * 4];
    return P2(qcurve([xs[0], y0 + (s < 0 ? bow * 0.2 : -bow * 0.1)], [(xs[0] + xs[1]) / 2, y0 - bow], [xs[1], y0 + (s < 0 ? -bow * 0.1 : bow * 0.2)], 10));
  };
  return (
    <g>
      <Contact x={cx} y={cy + 30} w={w * 1.15} h={22} opacity={0.4} />
      <Shape pts={cover} mat={MAT.wood} round={0.5} shade={0.12} lit={0.05} seed={seed} />
      <Shape pts={block} mat={MAT.paper} round={0.5} shade={0.2} lit={0} seed={seed + 1}>
        {[-6, 0, 6, 12, 18].map((k, i) => <Line key={i} pts={P2([[-hw - 6, k - 4], [-hw * 0.5, k + 14], [0, k + 6], [hw * 0.5, k + 14], [hw + 12, k - 4]])} w={1.3} color={MAT.paper.line} opacity={0.7} seed={seed + i} />)}
      </Shape>
      {[left, right].map((pg, si) => (
        <Shape key={si} pts={pg} mat={MAT.paper} round={0.6} shade={0.05} lit={0.05} seed={seed + 2 + si}>
          {Array.from({ length: lines }, (_, i) => <Line key={i} pts={textLine(si === 0 ? -1 : 1, i)} w={1.8} color={MAT.paper.line} opacity={0.75} seed={seed * 9 + i + si * 20} />)}
          {/* gutter shading into the spine */}
          <Line pts={P2([[0, -d + 14], [0, -10]])} w={30} color={MAT.paper.shade} opacity={0.55} wob={0} />
        </Shape>
      ))}
      <Line pts={P2([spineTop, [0, -6]])} w={WEIGHT.small} color={INK} />
    </g>
  );
};

export const PaperSheet: React.FC<{ x: number; y: number; w: number; h: number; r?: number; skew?: number; lines?: number; seed?: number; mat?: Material }> = ({ x, y, w, h, r = 0, skew = 0.12, lines = 5, seed = 1, mat = MAT.paper }) => {
  // a sheet lying on the desk: a parallelogram for perspective
  const k = w * skew;
  const pts = place([[-w / 2 + k, -h / 2], [w / 2 + k, -h / 2], [w / 2 - k, h / 2], [-w / 2 - k, h / 2]], x, y, r);
  return (
    <Shape pts={pts} mat={mat} round={0.15} wob={0.6} shade={0.05} lit={0.03} ink={WEIGHT.small} seed={seed}>
      {Array.from({ length: lines }, (_, i) => {
        const t = (i + 1) / (lines + 1);
        const yy = -h / 2 + h * t, sx = -k + 2 * k * (1 - t);
        return <Line key={i} pts={place([[-w * 0.38 + sx, yy], [w * (i === lines - 1 ? 0.05 : 0.36) + sx, yy]], x, y, r)} w={1.8} color={mat.line} opacity={0.8} seed={seed * 5 + i} />;
      })}
    </Shape>
  );
};

// ---------- desk things ----------

export const Mug: React.FC<{ x: number; y: number; h?: number; seed?: number; steam?: number; f?: number }> = ({ x, y, h = 130, seed = 1, steam = 0, f = 0 }) => {
  const w = h * 0.98;
  const body = place([[-w / 2, -h + 14], [w / 2, -h + 14], [w / 2 - 6, -12], [w / 2 - 18, 0], [-w / 2 + 18, 0], [-w / 2 + 6, -12]], x, y);
  const rim = ellipse(x, y - h + 14, w / 2, 16, 40);
  const coffee = ellipse(x, y - h + 17, w / 2 - 9, 10, 36);
  const handle = tube(qcurve([x + w / 2 - 6, y - h + 38], [x + w / 2 + 52, y - h * 0.55], [x + w / 2 - 6, y - 32], 14), () => 15);
  return (
    <g>
      <Contact x={x} y={y + 2} w={w * 1.3} opacity={0.4} />
      <Shape pts={handle} mat={MAT.ceramic} seed={seed + 3} shade={0.1} lit={0} />
      <Shape pts={body} mat={MAT.ceramic} seed={seed} round={0.7} shade={0.16} lit={0.1} />
      <Shape pts={rim} mat={MAT.ceramic} seed={seed + 1} shade={0} lit={0} ink={WEIGHT.outline} />
      <Shape pts={coffee} mat={MAT.coffee} seed={seed + 2} shade={0.2} lit={0} ink={0} />
      {steam > 0 && [0, 1].map((k) => {
        const sx = x - 14 + k * 26;
        const pts: P[] = Array.from({ length: 8 }, (_, i) => [sx + Math.sin(f * 0.07 + i * 0.9 + k * 2) * 7, y - h - 6 - i * 13]);
        return <Line key={k} pts={pts} w={5} color="#fff6e6" opacity={0.3 * steam} wob={0} />;
      })}
    </g>
  );
};

// Crumpled paper ball: a notched blob with crease lines. Seeded, so every ball is different.
export const PaperBall: React.FC<{ x: number; y: number; r?: number; a?: number; seed?: number }> = ({ x, y, r: R = 44, a = 0, seed = 1 }) => {
  const g = rng(`ball${seed}`);
  const n = 13;
  const outline: P[] = [];
  for (let i = 0; i < n; i++) {
    const ang = (i / n) * Math.PI * 2;
    const k = i % 2 === 0 ? rr(g, 0.92, 1.05) : rr(g, 0.8, 0.9);
    outline.push([Math.cos(ang) * R * k, Math.sin(ang) * R * k * 0.88]);
  }
  const pts = place(outline, x, y, a);
  const creases: P[][] = Array.from({ length: 5 }, (_, i) => {
    const a0 = rr(g, 0, Math.PI * 2), a1 = a0 + rr(g, 1.2, 2.4);
    const mid: P = [rr(g, -R * 0.25, R * 0.25), rr(g, -R * 0.2, R * 0.2)];
    return place([[Math.cos(a0) * R * 0.8, Math.sin(a0) * R * 0.7], mid, [Math.cos(a1) * R * 0.55, Math.sin(a1) * R * 0.5]], x, y, a);
  });
  return (
    <Shape pts={pts} mat={MAT.paper} seed={seed} round={0.55} wob={0.8} shade={0.2} lit={0.1} ink={WEIGHT.small + 0.6}>
      {creases.map((c, i) => <Line key={i} pts={c} w={1.8} color={MAT.paper.line} round={0.2} seed={seed + i} />)}
    </Shape>
  );
};

export const Pencil: React.FC<{ x: number; y: number; len?: number; a?: number; mat?: Material; seed?: number }> = ({ x, y, len = 130, a = 0, mat = MAT.mustard, seed = 1 }) => {
  const P2 = (pts: P[]) => place(pts, x, y, a);
  return (
    <g>
      <Shape pts={P2(rrect(0, -6.5, len, 13, 3))} mat={mat} seed={seed} round={0.3} shade={0.25} lit={0.15} ink={WEIGHT.small} />
      <Shape pts={P2(rrect(len * 0.08, -6.5, len * 0.1, 13, 1))} mat={MAT.metal} seed={seed + 1} round={0} shade={0} lit={0.2} ink={2} />
      <Shape pts={P2([[len, -6.5], [len + 22, 0], [len, 6.5]])} mat={MAT.cream} seed={seed + 2} round={0} shade={0} lit={0} ink={WEIGHT.small} />
      <Shape pts={P2([[len + 15, -2.2], [len + 22, 0], [len + 15, 2.2]])} mat={MAT.phone} round={0} shade={0} lit={0} ink={0} />
    </g>
  );
};

export const Phone: React.FC<{ x: number; y: number; w?: number; a?: number; seed?: number }> = ({ x, y, w = 150, a = -10, seed = 1 }) => (
  <g>
    <Contact x={x} y={y + 22} w={w * 1.1} opacity={0.3} />
    <Shape pts={place(rrect(-w / 2, -24, w, 48, 10), x, y, a)} mat={MAT.phone} seed={seed} round={0.6} shade={0.1} lit={0.15} />
    <Shape pts={place(rrect(-w / 2 + 10, -16, w - 20, 32, 6), x, y, a)} mat={MAT.screen} seed={seed + 1} round={0.6} shade={0} lit={0.25} ink={0} />
  </g>
);

// Desk lamp: a cone shade on an articulated arm. The shade is drawn in its own frame
// (x along the cone's axis, from the narrow top to the opening). `O` is the centre of the
// opening, which is where the scene's key light should sit.
export const DeskLamp: React.FC<{ O: P; axis?: number; L?: number; r0?: number; r1?: number; joint?: P; anchor?: P; on?: number; seed?: number }> = ({
  O, axis = 62, L = 150, r0 = 38, r1 = 80, joint, anchor = [-40, 250], on = 1, seed = 1,
}) => {
  const top = add(O, rot([-L, 0], axis));
  const F = (p: P): P => add(top, rot(p, axis)); // shade frame: (0,0) = top centre
  const shade = [[-6, -r0 + 6], [6, -r0], [L * 0.5, -(r0 + r1) / 2 - 2], [L, -r1], [L, r1], [L * 0.5, (r0 + r1) / 2 + 2], [6, r0], [-6, r0 - 6]].map((p) => F(p as P));
  const opening = ellipse(L, 0, 22, r1, 40).map(F);
  const inner = ellipse(L + 2, 0, 14, r1 - 14, 32).map(F);
  const cap = rrect(-24, -r0 * 0.7, 26, r0 * 1.4, 8).map(F);
  const rod = tube([F([-20, 0]), F([-62, -8])], () => 18);
  const knob = ellipse(-66, -8, 15, 15, 18).map(F);
  const j = joint ?? F([L * 0.18, -r0 - 30]);
  return (
    <g>
      <Shape pts={tube([anchor, j], () => 20)} mat={MAT.metal} round={0.3} shade={0.25} lit={0.22} seed={seed} />
      <Shape pts={ellipse(j[0], j[1], 19, 19, 20)} mat={MAT.metal} shade={0.25} lit={0.25} seed={seed + 1} />
      <Shape pts={tube([j, F([L * 0.2, -r0 + 4])], () => 16)} mat={MAT.metal} round={0.3} shade={0.2} lit={0.2} seed={seed + 6} />
      <Shape pts={rod} mat={MAT.metal} round={0.3} shade={0.2} lit={0.25} seed={seed + 2} />
      <Shape pts={knob} mat={MAT.metal} shade={0.25} lit={0.3} seed={seed + 3} />
      <Shape pts={cap} mat={MAT.metal} round={0.6} shade={0.2} lit={0.25} seed={seed + 4} />
      <Shape pts={shade} mat={MAT.metal} round={0.25} shade={0.16} lit={0.18} litOpacity={0.7} seed={seed + 5} ink={WEIGHT.outline + 1} lightFrom={F([-200, -300])}>
        {/* a long soft highlight down the shade */}
        <Line pts={[F([16, -r0 + 12]), F([L - 14, -r1 + 18])]} w={10} color={MAT.metal.lit} opacity={0.45} />
      </Shape>
      <Shape pts={opening} mat={on > 0 ? MAT.bulb : MAT.cream} shade={0} lit={0} seed={seed + 7} ink={WEIGHT.outline} />
      {on > 0 && <Shape pts={inner} mat={{ base: "#ffffff", shade: "#fff", lit: "#fff", line: "#fff" }} ink={0} shade={0} lit={0} seed={seed + 8} />}
    </g>
  );
};

// ---------- other rooms (so episodes aren't all the same desk) ----------

export const Window: React.FC<{ x: number; y: number; w: number; h: number; night?: boolean; f?: number; seed?: number }> = ({ x, y, w, h, night = true, f = 0, seed = 1 }) => {
  const g = rng(`win${seed}`);
  const stars = Array.from({ length: 26 }, () => [rr(g, x + 20, x + w - 20), rr(g, y + 20, y + h * 0.7), rr(g, 1.2, 2.6), rr(g, 0, 6)]);
  return (
    <g>
      <Shape pts={rrect(x - 22, y - 22, w + 44, h + 44, 6)} mat={MAT.cream} round={0.3} shade={0.04} lit={0.05} seed={seed} />
      <Shape pts={rrect(x, y, w, h, 3)} mat={night ? MAT.sky : MAT.paper} round={0.2} shade={0} lit={0} seed={seed + 1} ink={WEIGHT.small}>
        {night && stars.map(([sx, sy, r, ph], i) => <circle key={i} cx={sx} cy={sy} r={r} fill="#fff6d8" opacity={0.5 + 0.4 * Math.sin(f * 0.08 + ph)} />)}
        {night && <Shape pts={ellipse(x + w * 0.7, y + h * 0.28, 34, 34, 32)} mat={MAT.moon} shade={0.25} lit={0} ink={0} lightFrom={[x + w, y]} seed={seed + 2} />}
        {/* distant rooftops */}
        <Shape pts={[[x - 10, y + h + 10], [x - 10, y + h * 0.78], [x + w * 0.2, y + h * 0.78], [x + w * 0.2, y + h * 0.7], [x + w * 0.45, y + h * 0.7], [x + w * 0.45, y + h * 0.82], [x + w * 0.7, y + h * 0.82], [x + w * 0.7, y + h * 0.66], [x + w + 10, y + h * 0.66], [x + w + 10, y + h + 10]]} mat={MAT.glass} round={0} wob={0.3} shade={0} lit={0} ink={0} seed={seed + 3} />
      </Shape>
      <Line pts={[[x + w / 2, y], [x + w / 2, y + h]]} w={14} color={MAT.cream.base} wob={0.2} />
      <Line pts={[[x, y + h / 2], [x + w, y + h / 2]]} w={14} color={MAT.cream.base} wob={0.2} />
      <Line pts={[[x + w / 2, y], [x + w / 2, y + h]]} w={14} color="none" />
      <Shape pts={rrect(x - 36, y + h + 14, w + 72, 22, 4)} mat={MAT.cream} round={0.3} shade={0.15} lit={0.1} seed={seed + 4} />
    </g>
  );
};

export const Plant: React.FC<{ x: number; y: number; s?: number; seed?: number; f?: number }> = ({ x, y, s = 1, seed = 1, f = 0 }) => {
  const g = rng(`plant${seed}`);
  const leaves = Array.from({ length: 7 }, (_, i) => {
    const a = -90 + rr(g, -60, 60) + Math.sin(f * 0.05 + i) * 2;
    const L = rr(g, 70, 120) * s;
    const base: P = [x + rr(g, -10, 10) * s, y - 70 * s];
    const tip = add(base, rot([L, 0], a));
    const mid = lerpP(base, tip, 0.5);
    const n = rot([0, L * 0.22], a);
    return [base, add(mid, n), tip, add(mid, [-n[0], -n[1]])] as P[];
  });
  const pot = [[x - 46 * s, y - 76 * s], [x + 46 * s, y - 76 * s], [x + 36 * s, y], [x - 36 * s, y]] as P[];
  return (
    <g>
      <Contact x={x} y={y + 2} w={100 * s} opacity={0.35} />
      {leaves.map((l, i) => <Shape key={i} pts={l} mat={MAT.leaf} round={1} shade={0.18} lit={0.1} seed={seed * 10 + i} ink={WEIGHT.small} over={<Line pts={[l[0], l[2]]} w={1.6} color={MAT.leaf.line} opacity={0.8} />} />)}
      <Shape pts={pot} mat={MAT.pot} round={0.25} shade={0.18} lit={0.1} seed={seed} />
      <Shape pts={rrect(x - 52 * s, y - 86 * s, 104 * s, 20 * s, 5)} mat={MAT.pot} round={0.5} shade={0.1} lit={0.15} seed={seed + 1} />
    </g>
  );
};

export const Frame: React.FC<{ x: number; y: number; w: number; h: number; seed?: number; art?: "hills" | "sun" }> = ({ x, y, w, h, seed = 1, art = "hills" }) => (
  <g>
    <Shape pts={rrect(x, y, w, h, 3)} mat={MAT.wood} round={0.2} shade={0.06} lit={0.08} seed={seed} />
    <Shape pts={rrect(x + 12, y + 12, w - 24, h - 24, 2)} mat={MAT.paper} round={0.2} shade={0} lit={0} ink={WEIGHT.small} seed={seed + 1}>
      {art === "hills" && <Shape pts={[[x, y + h], [x, y + h * 0.65], [x + w * 0.35, y + h * 0.5], [x + w * 0.7, y + h * 0.66], [x + w, y + h * 0.55], [x + w, y + h]]} mat={MAT.leaf} round={1} shade={0} lit={0} ink={0} seed={seed + 2} />}
      <Shape pts={ellipse(x + w * 0.68, y + h * 0.34, w * 0.1, w * 0.1, 20)} mat={MAT.note} shade={0} lit={0} ink={0} seed={seed + 3} />
    </Shape>
  </g>
);
