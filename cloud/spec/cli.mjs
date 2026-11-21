#!/usr/bin/env node
// spec-export CLI: bundle one episode adapter (with the studio code it reads) via esbuild, then
//   1) write episodes/<id>/episode.json and validate it against episode.schema.json
//   2) export the adapter's code-built props (yacht, island, …) to GLB.
//
// node cloud/spec/cli.mjs --episode sentinel [--out FILE] [--assets-root DIR] [--no-props] [--no-spec]
//                         [--only yacht,island] [--instanced] [--json]
import { existsSync, mkdirSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import * as esbuild from "esbuild";
import { validateEpisode } from "./validate.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../..");
const STUDIO_SRC = join(REPO, "studio/src");
const STUB = join(HERE, "lib/stub.cjs");

const argv = process.argv.slice(2);
const flag = (n) => argv.includes(n);
const opt = (n, d) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[i + 1] : d; };
const id = opt("--episode");
if (!id || flag("--help")) {
  console.log("usage: node cloud/spec/cli.mjs --episode <id> [--out FILE] [--assets-root DIR] [--no-props] [--no-spec] [--only k1,k2] [--instanced] [--json]");
  process.exit(id ? 0 : 2);
}
const adapterFile = join(HERE, "adapters", `${id}.ts`);
if (!existsSync(adapterFile)) { console.error(`no adapter for '${id}': expected ${relative(REPO, adapterFile)}`); process.exit(2); }
const injectFile = join(HERE, "adapters", `${id}.inject.mjs`);
const inject = existsSync(injectFile) ? await import(pathToFileURL(injectFile).href) : {};
const transforms = inject.transforms ?? [];
const real = inject.real ?? [];

const outFile = resolve(opt("--out", join(REPO, "episodes", id, "episode.json")));
const assetsRoot = resolve(opt("--assets-root", join(REPO, "studio/public/assets")));

// ---------- bundle ----------
const stubPlugin = {
  name: "studio-stubs",
  setup(build) {
    build.onResolve({ filter: /^(react|react-dom|remotion|@remotion\/[^/]+)(\/.*)?$/ }, () => ({ path: STUB }));
    // one copy of three for both the studio code and the exporter
    build.onResolve({ filter: /^three(\/.*)?$/ }, async (a) => {
      if (a.pluginData?.three) return undefined;
      return build.resolve(a.path, { resolveDir: HERE, kind: a.kind, pluginData: { three: true } });
    });
    build.onResolve({ filter: /^\./ }, async (a) => {
      if (a.pluginData?.inner || !a.importer.startsWith(STUDIO_SRC)) return undefined;
      const r = await build.resolve(a.path, { resolveDir: a.resolveDir, kind: a.kind, importer: a.importer, pluginData: { inner: true } });
      if (r.errors.length) return r;
      if (r.path.startsWith(STUDIO_SRC) && !real.some((re) => re.test(r.path))) return { path: STUB };
      return r;
    });
    if (transforms.length) build.onLoad({ filter: /\.(tsx?|jsx?)$/ }, async (a) => {
      const t = transforms.filter((x) => x.filter.test(a.path));
      if (!t.length) return undefined;
      let src = await readFile(a.path, "utf8");
      for (const x of t) src = x.transform(src);
      return { contents: src, loader: a.path.endsWith("x") ? "tsx" : "ts", resolveDir: dirname(a.path) };
    });
  },
};
const buildDir = join(HERE, ".build");
mkdirSync(buildDir, { recursive: true });
const bundle = join(buildDir, `${id}.mjs`);
await esbuild.build({
  stdin: {
    contents: `export { adapter } from ${JSON.stringify(adapterFile)};\nexport { runSpec, runProps } from ${JSON.stringify(join(HERE, "lib/run.ts"))};`,
    resolveDir: HERE, loader: "ts", sourcefile: "entry.ts",
  },
  bundle: true, platform: "node", format: "esm", target: "node20", outfile: bundle,
  plugins: [stubPlugin], logLevel: "warning", jsx: "transform", sourcemap: "inline",
  banner: { js: "import { createRequire as __cr } from 'node:module'; const require = __cr(import.meta.url);" },
});
const mod = await import(pathToFileURL(bundle).href + `?t=${Date.now()}`);
const { adapter, runSpec, runProps } = mod;

const report = { episode: id };
let failed = false;
if (!flag("--no-spec")) {
  const doc = runSpec(adapter, outFile, { exporter: "cloud/spec/cli.mjs", adapter: relative(REPO, adapterFile) });
  const v = validateEpisode(doc, { root: REPO, assetsRoot, checkFiles: false });
  report.spec = { file: relative(REPO, outFile), shots: doc.shots.length, captions: doc.captions.length, durationFrames: doc.durationFrames, valid: v.ok, errors: v.errors, warnings: v.warnings };
  failed ||= !v.ok;
}
if (!flag("--no-props")) {
  const only = opt("--only")?.split(",");
  report.props = await runProps(adapter, assetsRoot, { instanced: flag("--instanced"), only });
  for (const p of Object.values(report.props)) p.file = relative(REPO, p.file);
}
if (!flag("--no-spec")) {
  // second pass with file checks, now that the props exist
  const { readFileSync } = await import("node:fs");
  const v = validateEpisode(JSON.parse(readFileSync(outFile, "utf8")), { root: REPO, assetsRoot, checkFiles: true });
  report.spec.filesPresent = v.ok;
  if (!v.ok) { report.spec.errors = v.errors; failed = true; }
}
if (flag("--json")) console.log(JSON.stringify(report, null, 2));
else {
  if (report.spec) {
    console.log(`spec  ${report.spec.file}: ${report.spec.shots} shots, ${report.spec.captions} captions, ${report.spec.durationFrames} frames, ${report.spec.valid && report.spec.filesPresent ? "VALID" : "INVALID"}`);
    report.spec.warnings.forEach((w) => console.log("  warn:", w));
    report.spec.errors.forEach((e) => console.log("  ERROR:", e));
  }
  for (const [k, p] of Object.entries(report.props ?? {}))
    console.log(`prop  ${k} -> ${p.file}: ${(p.bytes / 1e6).toFixed(2)} MB, ${p.nodes} nodes, ${p.meshes} meshes, ${p.materials} materials, ${p.verts} verts, ${p.tris} tris, ${p.lights} lights, ext=[${p.extensionsUsed.join(",")}] (${p.ms} ms)`);
}
process.exit(failed ? 1 : 0);
