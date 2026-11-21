// STYLE TOKENS. The one place the look is defined. Every prop and character pulls from here,
// which is what keeps episodes consistent. Values were sampled from the style reference.

export type Material = {
  base: string; // main fill
  shade: string; // cel shadow, side away from the key light
  lit: string; // highlight, side facing the key light
  line: string; // interior detail lines (folds, grain, page edges): never the ink colour
};

export const INK = "#140805";

export const WEIGHT = {
  hero: 7, // character silhouette
  outline: 5, // props
  small: 3.6, // small props (pencils, notes)
  inner: 3.6, // interior ink (fingers, collar)
  detail: 2, // detail lines in the material's line colour
  fine: 1.4,
};

const m = (base: string, shade: string, lit: string, line: string): Material => ({ base, shade, lit, line });

export const MAT = {
  skin: m("#fdf0d7", "#ead2ac", "#fffaf0", "#d9bf98"),
  sweater: m("#c1301e", "#902517", "#df462c", "#7a1c10"),
  paper: m("#fbeed6", "#efd4a8", "#fffaf0", "#b8977a"),
  paperOld: m("#f3dfbd", "#ddbf92", "#fbeed6", "#b0896c"),
  wall: m("#eccb98", "#d9ae7c", "#f8dfb4", "#b98b62"),
  woodLight: m("#e49950", "#c98145", "#f5b45c", "#ab6536"),
  wood: m("#ab6536", "#90512d", "#c98145", "#713a22"),
  woodDark: m("#713a22", "#4f2a1b", "#90512d", "#3f1d10"),
  chair: m("#5a2f1d", "#3f1d10", "#7a4127", "#2c140a"),
  ceramic: m("#f6ead6", "#d9c3a4", "#fffaf0", "#b8a184"),
  coffee: m("#4a2214", "#2f140b", "#6b3820", "#2a1108"),
  metal: m("#5a5250", "#3e3836", "#827976", "#2e2826"),
  bulb: m("#fff6d6", "#ffe6a8", "#ffffff", "#f0d590"),
  green: m("#8fae7a", "#6e8163", "#acc796", "#56684d"),
  lilac: m("#c9c1df", "#a79fc0", "#e2dcf2", "#8a83a6"),
  mustard: m("#e3b24a", "#c48f2c", "#f3cb6a", "#9a6c1c"),
  cream: m("#f1e2c2", "#d8c29b", "#fbf1dc", "#b49a74"),
  note: m("#f5b45c", "#e09445", "#fcc879", "#c27a30"),
  phone: m("#3b3533", "#262120", "#5b5350", "#1c1817"),
  screen: m("#4f4744", "#3a3331", "#6c625e", "#2c2624"),
  leaf: m("#6f9a5b", "#4f7640", "#8fbb74", "#3f5f33"),
  pot: m("#c8653c", "#9c4a2a", "#e07c52", "#7a3820"),
  sky: m("#2b3566", "#1d2550", "#3d4a85", "#151b3d"),
  moon: m("#fff4cf", "#f1dca0", "#ffffff", "#e6cf8c"),
  glass: m("#3a4472", "#2a335c", "#55609a", "#1e2546"),
};

export type LightRig = {
  key: { x: number; y: number; color: string; reach: number; strength: number }; // the main light (lamp, window, sun)
  ambient: string; // overall colour grade (multiplied)
  ambientStrength: number;
  vignette: number;
  grain: number;
};

export const LIGHTS: Record<string, LightRig> = {
  // warm desk lamp at night, the reference look
  lampNight: { key: { x: 205, y: 215, color: "#ffcf7a", reach: 620, strength: 0.55 }, ambient: "#f3a35a", ambientStrength: 0.08, vignette: 0.45, grain: 0 },
  // cool moonlit room with a warm accent
  moonNight: { key: { x: 760, y: 260, color: "#bcd0ff", reach: 700, strength: 0.4 }, ambient: "#6a78b8", ambientStrength: 0.22, vignette: 0.5, grain: 0.07 },
  // soft morning daylight
  morning: { key: { x: 900, y: 120, color: "#fff1c8", reach: 900, strength: 0.35 }, ambient: "#f7c98a", ambientStrength: 0.08, vignette: 0.25, grain: 0.06 },
};
