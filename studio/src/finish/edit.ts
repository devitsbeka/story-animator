// Editorial logic for Finish: which plate(s) are on screen at a film frame and how they move.
// Pure functions (no React) so the edit can be reasoned about and tested on its own.
import { CaptionPage, FinishShot, PlatesManifest, StepSpan, Transition } from "./types";

export const TRANSITION_HALF: Record<Transition, number> = { cut: 0, push: 5, whip: 4 };
const SNAP = 3; // a cut may move up to 3 frames to land on a word onset (cuts on VO), only onto rendered handle frames

export type Cut = { at: number; type: Transition; out: FinishShot; in: FinishShot };
export type Layer = {
  shot: FinishShot;
  plateFrame: number | null; // null = no plate rendered for this shot yet (slate)
  opacity: number;
  scale: number;
  tx: number; // px, canvas space
  streak: number; // px of horizontal motion smear (whip)
  blur: number; // px gaussian blur (push)
};

const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const easeIn = (t: number) => clamp01(t) ** 3;
const easeOut = (t: number) => 1 - (1 - clamp01(t)) ** 3;
const smooth = (t: number) => { const x = clamp01(t); return x * x * (3 - 2 * x); };
const easeInOut = (t: number) => { const x = clamp01(t); return x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2; };

// Automatic transition rule (house style: mostly cuts on the VO, an occasional push or whip):
//   a STEP starting at the cut -> push (zoom through); a new sequence letter (A..->B..) -> whip; else cut.
export function autoTransition(prev: FinishShot, next: FinishShot, steps: StepSpan[]): Transition {
  if (next.transition) return next.transition;
  if (steps.some((s) => Math.abs(s.from - next.from) <= 6)) return "push";
  if (prev.id[0] !== next.id[0]) return "whip";
  return "cut";
}

const covers = (m: PlatesManifest, id: string, a: number, b: number) => {
  const fr = new Set(m[id]?.frames ?? []);
  for (let k = a; k < b; k++) if (!fr.has(k)) return false;
  return true;
};

export function buildCuts(shots: FinishShot[], steps: StepSpan[], captions: CaptionPage[], manifest: PlatesManifest = {}): Cut[] {
  const onsets = captions.flatMap((p) => p.words.map((w) => w.from)).sort((a, b) => a - b);
  const cuts: Cut[] = [];
  for (let i = 1; i < shots.length; i++) {
    const out = shots[i - 1], inn = shots[i];
    let at = inn.from;
    let best = SNAP + 1;
    for (const o of onsets) {
      const d = Math.abs(o - inn.from);
      if (d === 0) { at = o; break; }
      if (d >= best || o <= out.from + 4 || o >= inn.to - 4) continue;
      // moving the cut shows the outgoing shot past its end (or the incoming before its start): only
      // when those handle frames were rendered, otherwise the picture would freeze
      const ok = o > inn.from ? covers(manifest, out.id, inn.from, o) : covers(manifest, inn.id, o, inn.from);
      if (ok) { best = d; at = o; }
    }
    cuts.push({ at, type: autoTransition(out, inn, steps), out, in: inn });
  }
  return cuts;
}

// nearest rendered plate at or before film frame f, else the shot's first plate (handles outside
// [from, to) are used when they were rendered; otherwise the edge plate holds)
export function plateFor(shot: FinishShot, f: number, manifest: PlatesManifest): number | null {
  const fr = manifest[shot.id]?.frames;
  if (!fr || fr.length === 0) return null;
  const want = f;
  let lo = 0, hi = fr.length - 1, ans = -1;
  while (lo <= hi) {
    const m = (lo + hi) >> 1;
    if (fr[m] <= want) { ans = m; lo = m + 1; } else hi = m - 1;
  }
  return ans >= 0 ? fr[ans] : fr[0];
}

export function layersAt(f: number, shots: FinishShot[], cuts: Cut[], manifest: PlatesManifest, width: number): Layer[] {
  if (shots.length === 0) return [];
  const plain = (s: FinishShot): Layer => ({ shot: s, plateFrame: plateFor(s, f, manifest), opacity: 1, scale: 1, tx: 0, streak: 0, blur: 0 });
  for (const c of cuts) {
    const h = TRANSITION_HALF[c.type];
    if (h === 0 || f < c.at - h || f >= c.at + h) continue;
    const p = (f - (c.at - h) + 0.5) / (2 * h); // 0..1 across the transition
    const a = plain(c.out), b = plain(c.in);
    if (c.type === "push") {
      // push through: outgoing accelerates forward and blurs, incoming lands from slightly close;
      // the hand-over is concentrated in the middle of the window so it reads as a push, not a dissolve
      a.scale = 1 + 0.3 * easeIn(p);
      a.blur = 10 * easeIn(p);
      b.scale = 1.14 - 0.14 * easeOut(p);
      b.blur = 8 * (1 - easeOut(p));
      b.opacity = smooth((p - 0.3) / 0.4);
      return [a, b];
    }
    // whip: both shots on one strip, panned right-to-left so the frame is always full; motion smear
    // proportional to the strip's speed (easeInOut derivative peaks at 1.5 / window)
    const e = easeInOut(p);
    const speed = width * (1 - Math.abs(2 * p - 1)) * 3 / (2 * h); // px per frame, 0 at the ends
    a.tx = -width * e;
    b.tx = width * (1 - e);
    a.streak = b.streak = speed * 0.8;
    return [a, b];
  }
  // between cuts: the shot whose [cut-in, cut-out) holds f
  let idx = 0;
  for (let i = 0; i < cuts.length; i++) if (f >= cuts[i].at) idx = i + 1;
  return [plain(shots[idx])];
}
