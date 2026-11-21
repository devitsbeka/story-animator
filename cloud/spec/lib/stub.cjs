// Universal stand-in for modules the exporter must not execute (React, Remotion, WebGL/DOM-bound
// kit files). Every property is a callable no-op that returns another stub, so module top levels
// that merely define components or read constants evaluate fine. Anything that *needs* a real value
// from a stubbed module will produce a stub, which the adapters never put into the spec.
const handler = {
  get(_t, k) {
    if (k === "__esModule") return true;
    if (k === "then" || k === Symbol.toPrimitive || k === Symbol.iterator) return undefined;
    if (k === "toString" || k === "valueOf") return () => "[stub]";
    return stub;
  },
  apply() { return stub; },
  construct() { return stub; },
};
const stub = new Proxy(function stub() {}, handler);
module.exports = stub;
