// Finish composition inputs. Written by factory/finish/make_plates_manifest.py (props.json).

export type Transition = "cut" | "push" | "whip";

export type FinishShot = {
  id: string;
  from: number; // absolute film frame, inclusive
  to: number; // exclusive
  title?: string;
  transition?: Transition; // transition INTO this shot (overrides the automatic rule)
  // re-cuts (factory/shorts): a shot of a derived edit plays plates of another shot from another time
  plate?: string; // plates sub-dir to read (default: id)
  src?: number; // source film frame shown at `from` (default: from)
  zoom?: number; // static punch-in scale (>= 1.15 reads as a cut inside a held plate)
};

export type FinishEpisode = {
  id: string;
  title?: string;
  fps: number;
  width: number;
  height: number;
  durationFrames: number;
  audio?: { offsetFrames?: number };
  shots: FinishShot[];
};

export type CaptionTone = "accent" | "danger" | "good";
export type CaptionPage = {
  from: number; // film frame of the first word
  to: number; // exclusive
  words: { t: string; from: number }[];
  emph: number | null; // index of the emphasised word
  tone: CaptionTone;
};

export type StepSpan = { n: number; label: string; title: string; from: number; to: number; total: number };

// shotId -> absolute film frames that have a plate PNG (<platesDir>/<shot>/####.png)
export type PlatesManifest = Record<string, { frames: number[] }>;

export type FinishProps = {
  episodeJson?: FinishEpisode;
  platesDir?: string; // staticFile-relative
  manifest?: PlatesManifest;
  audio?: string | null; // staticFile-relative
  captions?: CaptionPage[];
  steps?: StepSpan[];
  range?: { from: number; to: number }; // film frames rendered [from, to)
  propsFile?: string; // staticFile-relative props.json; merged under explicit props by calculateMetadata
  grade?: { contrast?: number; vignette?: number; grain?: number; halation?: number };
  title?: { text: string; from: number; to: number }; // hook title in the hook band (derived shorts, factory/shorts)
};
