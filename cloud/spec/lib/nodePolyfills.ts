// Minimal browser APIs three.js' GLTFExporter needs under Node (Blob is native in Node >= 18).
class NodeFileReader {
  result: ArrayBuffer | string | null = null;
  onloadend: (() => void) | null = null;
  onload: (() => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  private done(r: ArrayBuffer | string) { this.result = r; this.onload?.(); this.onloadend?.(); }
  readAsArrayBuffer(b: Blob) { b.arrayBuffer().then((r) => this.done(r), (e) => this.onerror?.(e)); }
  readAsDataURL(b: Blob) {
    b.arrayBuffer().then((r) => this.done(`data:${b.type || "application/octet-stream"};base64,${Buffer.from(r).toString("base64")}`), (e) => this.onerror?.(e));
  }
}
const g = globalThis as any;
if (typeof g.FileReader === "undefined") g.FileReader = NodeFileReader;
if (typeof g.self === "undefined") g.self = g;
export {};
