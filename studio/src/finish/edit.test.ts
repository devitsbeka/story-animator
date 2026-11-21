// Edit logic checks (no test runner needed):
//   cd studio && node_modules/.bin/esbuild src/finish/edit.test.ts --bundle --platform=node --outfile=/tmp/finish/edit.test.js && node /tmp/finish/edit.test.js
import { buildCuts, layersAt, plateFor } from "./edit";
import { FinishShot, StepSpan } from "./types";

const assert = (c: boolean, m: string) => { if (!c) throw new Error("FAIL: " + m); };
const shots: FinishShot[] = [
  { id: "A03", from: 118, to: 158 }, { id: "A04", from: 158, to: 241 },
  { id: "B10", from: 241, to: 300 }, { id: "C13", from: 300, to: 400 },
];
const steps: StepSpan[] = [{ n: 1, label: "STEP 1", title: "MAYDAY", from: 299, to: 400, total: 1 }];
const manifest = { A03: { frames: [153, 154, 155, 156, 157] }, A04: { frames: [158, 160, 162] } };

const onset160 = [{ from: 160, to: 170, words: [{ t: "x", from: 160 }], emph: null, tone: "accent" as const }];
assert(buildCuts(shots, steps, onset160, manifest)[0].at === 158, "no snap without rendered handles");
const withHandles = { ...manifest, A03: { frames: [153, 154, 155, 156, 157, 158, 159] } };
const cuts = buildCuts(shots, steps, onset160, withHandles);
assert(cuts.map((c) => c.type).join() === "cut,whip,push", "auto transitions: " + cuts.map((c) => c.type));
assert(cuts[0].at === 160, "cut snaps to a word onset within 3 frames: " + cuts[0].at);
assert(plateFor(shots[0], 120, manifest) === 153, "before first plate -> first plate");
assert(plateFor(shots[0], 155, manifest) === 155, "exact plate");
assert(plateFor(shots[0], 170, manifest) === 157, "past shot end -> last plate of the shot");
assert(plateFor(shots[0], 159, withHandles) === 159, "rendered handle frame used");
assert(plateFor(shots[1], 161, manifest) === 160, "hold nearest earlier plate");
assert(plateFor(shots[2], 250, manifest) === null, "no plates -> slate");
assert(layersAt(159, shots, cuts, manifest, 1080)[0].shot.id === "A03", "before snapped cut: outgoing");
assert(layersAt(160, shots, cuts, manifest, 1080)[0].shot.id === "A04", "at snapped cut: incoming");
const w1 = layersAt(238, shots, cuts, manifest, 1080), w2 = layersAt(242, shots, cuts, manifest, 1080);
assert(w1.length === 2 && w1[0].shot.id === "A04" && w1[0].tx < 0 && w1[0].streak > 0, "whip out moves left with smear");
assert(w2[1].shot.id === "B10" && w2[1].tx > 0 && w2[1].tx < 1080, "whip in arrives from the right");
assert(Math.abs(w2[1].tx - w2[0].tx - 1080) < 1e-6, "whip strip is contiguous (frame always full)");
const p = layersAt(300, shots, cuts, manifest, 1080);
assert(p.length === 2 && p[0].scale > 1 && p[1].opacity > 0 && p[1].opacity < 1, "push overlaps both shots");
assert(layersAt(320, shots, cuts, manifest, 1080).length === 1, "single layer between transitions");
// re-cut shots (factory/shorts): plates of another shot, from another time, optionally punched in
const recut: FinishShot[] = [
  { id: "S00", from: 0, to: 30, plate: "D013", src: 1500, transition: "cut" },
  { id: "S01", from: 30, to: 90, plate: "D013", src: 1440, zoom: 1.15, transition: "cut" },
];
const recutManifest = { D013: { frames: [1440, 1441, 1500, 1501, 1529] } };
assert(plateFor(recut[0], 0, recutManifest) === 1500, "re-cut reads the source plate at `src`");
assert(plateFor(recut[0], 1, recutManifest) === 1501, "re-cut advances with the edit");
assert(plateFor(recut[0], 29, recutManifest) === 1529, "re-cut maps the whole shot");
assert(plateFor(recut[1], 31, recutManifest) === 1441, "second re-cut of the same plate dir from an earlier time");
const rc = buildCuts(recut, [], [], recutManifest);
assert(rc[0].type === "cut", "explicit cut between re-cut shots");
const rl = layersAt(40, recut, rc, recutManifest, 1080);
assert(rl.length === 1 && rl[0].shot.id === "S01" && rl[0].scale === 1.15, "punch-in zoom carried on the layer");
console.log("edit.test OK:", cuts.map((c) => `${c.out.id}->${c.in.id}@${c.at}:${c.type}`).join(" "));
