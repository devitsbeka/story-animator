// Bundle-time transforms for the sentinel adapter: expose values that s1_3d.tsx keeps private
// (module consts and literals inside the S1_3D component body) as extra named exports.
import { grabExpr, grabGroup } from "../lib/extract.mjs";

export const transforms = [
  {
    filter: /studio\/src\/episodes\/sentinel\/s1_3d\.tsx$/,
    transform(src) {
      const body = src.indexOf("export const S1_3D");
      if (body < 0) throw new Error("s1_3d.tsx: S1_3D component not found");
      const place = src.indexOf("const place", body);
      const lookAt = src.indexOf("lookAt:", place);
      const x = {
        handheld: grabExpr(src, /handheld:\s*/, body),
        shakes: grabGroup(src, /shakes:/, body),
        kick: grabExpr(src, /const kick\s*=\s*/, body),
        seaState: grabExpr(src, /seaState:\s*/, body),
        island: grabGroup(src, /island:/, body),
        heroLocal: grabGroup(src, /makeTranslation/, place),
        heroRotY: grabGroup(src, /makeRotationY/, place),
        heroScale: grabExpr(src, /scale:\s*/, place),
        tracks: grabGroup(src, /tracks:/, place),
        lookWeight: grabExpr(src, /weight:\s*/, lookAt),
      };
      return src + `
;export const __S1 = {
  handheld: (f) => (${x.handheld}),
  shakes: ${x.shakes},
  kick: (f) => (${x.kick}),
  seaState: ${x.seaState},
  island: ${x.island},
  heroLocal: [${x.heroLocal.slice(1, -1)}],
  heroRotY: ${x.heroRotY},
  heroScale: ${x.heroScale},
  tracks: ${x.tracks},
  lookWeight: (f) => (${x.lookWeight}),
};
export { KEYS as __S1_KEYS, CLIPS as __S1_CLIPS, YACHT as __S1_YACHT, MOON as __S1_MOON, flick as __S1_flick };
`;
    },
  },
];

// studio/src files the adapter really executes; every other studio module (React components,
// WebGL/DOM-bound kit files) is replaced by lib/stub.cjs at bundle time.
export const real = [
  /studio\/src\/episodes\/sentinel\/(cues\.ts|beats3d\.tsx|s1_3d\.tsx)$/,
  /studio\/src\/kit\/(camrig|yacht3d|island3d)\.ts$/,
  /studio\/src\/data\/.*\.json$/,
];
