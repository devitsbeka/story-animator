#!/usr/bin/env node
// Validate an episode.json against episode.schema.json (ajv, draft 2020-12) plus semantic checks
// the schema cannot express (frame ranges, references, sorted keys, files present).
// Usage: node validate.mjs <episode.json> [--root <storage root>] [--assets-root <dir for assets/…>]
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../..");

export const validateEpisode = (ep, { root = REPO, assetsRoot = join(REPO, "studio/public/assets"), checkFiles = true } = {}) => {
  const schema = JSON.parse(readFileSync(join(HERE, "episode.schema.json"), "utf8"));
  const ajv = new Ajv2020({ allErrors: true, strict: true, strictTuples: false });
  const ok = ajv.validate(schema, ep);
  const errors = ok ? [] : ajv.errors.map((e) => `schema ${e.instancePath || "/"} ${e.message}${e.params?.additionalProperty ? ` (${e.params.additionalProperty})` : ""}`);
  const warnings = [];
  if (!ok) return { ok: false, errors, warnings };
  const E = (m) => errors.push(m), W = (m) => warnings.push(m);
  const sorted = (arr, at) => arr.every((k, i) => i === 0 || at(arr[i - 1]) <= at(k));
  // shots: inside the film, sorted, contiguous coverage
  let prevTo = 0;
  ep.shots.forEach((s, i) => {
    const tag = `shot ${s.id}`;
    if (s.from >= s.to) E(`${tag}: from ${s.from} >= to ${s.to}`);
    if (s.from < 0 || s.to > ep.durationFrames) E(`${tag}: [${s.from},${s.to}) outside 0..${ep.durationFrames}`);
    if (s.from !== prevTo) (s.from < prevTo ? E : W)(`${tag}: starts at ${s.from}, previous shot ended at ${prevTo} (${s.from < prevTo ? "overlap" : "gap"})`);
    prevTo = s.to;
    if (s.keyFrame !== undefined && (s.keyFrame < s.from || s.keyFrame >= s.to)) W(`${tag}: keyFrame ${s.keyFrame} outside the shot`);
    if (!sorted(s.camera.keys, (k) => k.f)) E(`${tag}: camera keys not sorted by f`);
    const kf = s.camera.keys.map((k) => k.f);
    if (kf[0] > s.from || kf[kf.length - 1] < s.from) W(`${tag}: first camera key at ${kf[0]} (shot starts ${s.from})`);
    for (const [name, v] of Object.entries({ handheld: s.camera.handheld, ...(s.yacht ?? {}) }))
      if (Array.isArray(v) && !sorted(v, (k) => k[0])) E(`${tag}: ${name} keys not sorted`);
    if (s.fires && !sorted(s.fires, (k) => k[0])) E(`${tag}: fires keys not sorted`);
    for (const a of s.actors ?? []) {
      if (!ep.assets.characters[a.asset]) E(`${tag}: actor asset '${a.asset}' not in assets.characters`);
      for (const t of a.tracks) if (!ep.assets.motions[t.clip]) E(`${tag}: clip '${t.clip}' not in assets.motions`);
    }
    if (s.actors?.length && !s.yacht) E(`${tag}: yacht-space actor but no yacht in shot`);
    if (s.camera.space === "yacht" && !s.yacht) E(`${tag}: yacht-space camera but no yacht in shot`);
    const isl = s.island === undefined ? ep.world.island : s.island;
    if (isl && !ep.assets.props[isl.asset] && !isl.asset.endsWith(".glb")) E(`${tag}: island asset '${isl.asset}' not in assets.props`);
    if (s.fires && !isl) W(`${tag}: fires set but no island`);
  });
  if (prevTo !== ep.durationFrames) W(`shots end at ${prevTo}, film is ${ep.durationFrames} frames`);
  ep.captions.forEach((c, i) => {
    if (c.from >= c.to) E(`caption ${i}: from >= to`);
    if (c.to > ep.durationFrames) E(`caption ${i}: ends after the film`);
  });
  if (!sorted(ep.captions, (c) => c.from)) W("captions not sorted by from");
  if (checkFiles) {
    const where = (key) => (key.startsWith("assets/") ? join(assetsRoot, key.slice(7)) : join(root, key));
    const files = [ep.audio.narration, ep.audio.wordsJson, ep.audio.mix, ...Object.values(ep.assets.characters), ...Object.values(ep.assets.motions), ...Object.values(ep.assets.props)].filter(Boolean);
    for (const k of files) if (!existsSync(where(k))) E(`missing file for '${k}' (looked at ${where(k)})`);
  }
  return { ok: errors.length === 0, errors, warnings };
};

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const opt = (n) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : undefined; };
  const file = args.find((a, i) => !a.startsWith("--") && !(i > 0 && args[i - 1].startsWith("--")));
  if (!file) { console.error("usage: node validate.mjs <episode.json> [--root DIR] [--assets-root DIR] [--no-files]"); process.exit(2); }
  const r = validateEpisode(JSON.parse(readFileSync(file, "utf8")), { root: opt("--root") ?? REPO, assetsRoot: opt("--assets-root") ?? join(REPO, "studio/public/assets"), checkFiles: !args.includes("--no-files") });
  r.warnings.forEach((w) => console.log("warn:", w));
  r.errors.forEach((e) => console.log("ERROR:", e));
  console.log(r.ok ? `OK ${file}` : `INVALID ${file} (${r.errors.length} errors)`);
  process.exit(r.ok ? 0 : 1);
}
