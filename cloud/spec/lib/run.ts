// Runtime entry (bundled together with one adapter by cli.mjs). Kept free of Node-only imports at
// module top level except fs/path, so the same bundle runs in a cloud worker.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { exportGLB, glbStats } from "./props";
import type { Adapter } from "./types";

export const runSpec = (adapter: Adapter, outFile: string, source: Record<string, unknown>) => {
  const ep = adapter.episode();
  const doc = { $schema: "../../cloud/spec/episode.schema.json", ...ep, source: { ...source, exportedAt: new Date().toISOString() } };
  mkdirSync(dirname(outFile), { recursive: true });
  writeFileSync(outFile, JSON.stringify(doc, null, 2) + "\n");
  return doc;
};

export const runProps = async (adapter: Adapter, assetsRoot: string, opts: { instanced?: boolean; only?: string[] } = {}) => {
  const out: Record<string, unknown> = {};
  for (const p of adapter.props) {
    if (opts.only && !opts.only.includes(p.key)) continue;
    const t0 = Date.now();
    const buf = await exportGLB(p.build(), { instanced: opts.instanced });
    const file = join(assetsRoot, p.file.replace(/^assets\//, ""));
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, Buffer.from(buf));
    out[p.key] = { file, ms: Date.now() - t0, ...glbStats(buf) };
  }
  return out;
};
