// SENTINEL · cue table. The ONE place frame numbers live.
// Narration: episodes/sentinel/audio/narration.mp3 (take A, 77.76 s), starts at frame 15.
// A word at t seconds sits at frame 15 + round(t × 30). Visuals lead their word by 2–6 frames.

export const FPS = 30;
export const OFFSET = 15;
export const DURATION = 2416; // last word ends f2341, plus a 2.5 s tail

// Named beats (frame of the word they land on)
export const CUE = {
  yacht: 39, engine: 109, died: 135, noLights: 160, nothing: 214,
  current: 249, dragging: 268, island: 315, touch: 384,
  sentinel: 406,
  people: 463, contact: 510, thousands: 563, defend: 618, hard: 638,
  crunch: 694, reef: 737, stuck: 760, actuallyDo: 802,
  step1: 835, mayday: 863, radio: 902, ch16: 928, beacon: 990, coastGuard: 1024,
  step2: 1087, ashore: 1146, photo: 1184, sayHi: 1212, immunity: 1267, germs: 1293, cold: 1333, deadly: 1357,
  step3: 1390, stayBoat: 1421, before: 1501,
  y1981: 1528, primrose: 1592, aground: 1617, armed: 1676, stayed: 1736, steel: 1763, days: 1809, helicopters: 1840, everySingle: 1871,
  step4: 1931, killLights: 1963, quiet: 2005, nothingBehind: 2035,
  tide: 2087, drift: 2124, gone: 2177,
  because: 2200, never: 2306, end: 2341,
};

// Scenes (one continuous camera; transitions are push-throughs, never static cuts)
export type SceneId = "yacht" | "chart" | "shore" | "reef" | "radio" | "ashore" | "stay" | "primrose" | "quiet" | "tide" | "outro";
export const SCENES: { id: SceneId; from: number; to: number }[] = [
  { id: "yacht", from: 0, to: 238 },
  { id: "chart", from: 238, to: 452 },
  { id: "shore", from: 452, to: 668 },
  { id: "reef", from: 668, to: 830 },
  { id: "radio", from: 830, to: 1085 },
  { id: "ashore", from: 1085, to: 1388 },
  { id: "stay", from: 1388, to: 1520 },
  { id: "primrose", from: 1520, to: 1928 },
  { id: "quiet", from: 1928, to: 2070 },
  { id: "tide", from: 2070, to: 2196 },
  { id: "outro", from: 2196, to: DURATION },
];
export const XFADE = 10; // frames of push-through overlap between scenes

// Designed captions (P01): [from, to, small (sans), big (serif italic anchor), position]
// ≤5 words per phrase, one anchor. Verbatim captions go to the SRT, not here.
export type Cap = { from: number; to: number; small?: string; big: string; at?: "top" | "low" | "mid"; tone?: "warm" | "blue" | "red" };
export const CAPS: Cap[] = [
  { from: 18, to: 100, small: "alone on a", big: "yacht", at: "top" },
  { from: 103, to: 157, small: "your engine just", big: "died.", at: "top", tone: "red" },
  { from: 158, to: 236, small: "no lights · no power", big: "nothing.", at: "top" },
  { from: 245, to: 330, small: "the current is", big: "dragging you", at: "top" },
  { from: 332, to: 402, small: "the one island you're", big: "not allowed", at: "top", tone: "red" },
  { from: 404, to: 455, small: "island", big: "North Sentinel", at: "mid", tone: "blue" },
  { from: 494, to: 602, small: "no contact for", big: "thousands of years", at: "top" },
  { from: 606, to: 668, small: "and they defend that", big: "hard.", at: "top" },
  { from: 690, to: 735, big: "CRUNCH.", at: "top", tone: "red" },
  { from: 736, to: 784, small: "you hit the reef", big: "stuck.", at: "top" },
  { from: 786, to: 832, small: "so what do you", big: "actually do?", at: "top" },
  { from: 834, to: 870, small: "step one", big: "MAYDAY", at: "top", tone: "red" },
  { from: 900, to: 988, small: "radio · channel", big: "16", at: "top", tone: "blue" },
  { from: 989, to: 1084, small: "fire your", big: "emergency beacon", at: "top" },
  { from: 1087, to: 1166, small: "step two", big: "do NOT go ashore", at: "top", tone: "red" },
  { from: 1167, to: 1232, small: "not for a photo", big: "not to say hi", at: "top" },
  { from: 1236, to: 1310, small: "almost no", big: "immunity", at: "top" },
  { from: 1312, to: 1388, small: "a common cold could be", big: "deadly", at: "top", tone: "red" },
  { from: 1390, to: 1462, small: "step three", big: "stay with your boat", at: "top" },
  { from: 1462, to: 1520, small: "this has actually", big: "happened before", at: "top" },
  { from: 1524, to: 1590, small: "in", big: "1981", at: "top", tone: "blue" },
  { from: 1590, to: 1660, small: "a cargo ship called the", big: "Primrose", at: "top" },
  { from: 1662, to: 1730, small: "armed islanders", big: "on the beach", at: "top" },
  { from: 1732, to: 1836, small: "they stayed inside and waited", big: "for days", at: "top" },
  { from: 1838, to: 1926, small: "helicopters lifted", big: "every single one", at: "top", tone: "blue" },
  { from: 1930, to: 1990, small: "step four", big: "kill the lights", at: "top" },
  { from: 1993, to: 2026, big: "stay quiet.", at: "top" },
  { from: 2028, to: 2070, small: "leave", big: "nothing behind", at: "top" },
  { from: 2076, to: 2122, small: "if the tide", big: "lifts your boat", at: "top" },
  { from: 2122, to: 2196, small: "drift past the reef and", big: "get gone!", at: "top", tone: "blue" },
  { from: 2244, to: 2300, small: "the smartest way to survive", big: "is…", at: "mid" },
  { from: 2302, to: 2416, small: "to", big: "never be there at all.", at: "mid" },
];
