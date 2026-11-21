"""Load an episode (episode.json + word timings) into one QC view.

The timeline is in seconds from frame 0 of the edit. Word timings from Stage 5 are relative
to the narration file, so `audio.offsetFrames` is added to them.
"""
from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass, field


@dataclass
class Word:
    text: str
    start: float  # seconds on the edit timeline
    end: float


@dataclass
class Episode:
    path: str  # the episode json
    root: str  # repo root used to resolve relative asset paths
    data: dict
    words: list = field(default_factory=list)

    @property
    def fps(self) -> float:
        return float(self.data.get("fps", 30))

    @property
    def width(self) -> int:
        return int(self.data.get("width", 1080))

    @property
    def height(self) -> int:
        return int(self.data.get("height", 1920))

    @property
    def frames(self) -> int:
        if "durationFrames" in self.data:
            return int(self.data["durationFrames"])
        return max((s["to"] for s in self.shots), default=0)

    @property
    def duration(self) -> float:
        return self.frames / self.fps

    @property
    def shots(self) -> list:
        return self.data.get("shots", [])

    @property
    def captions(self) -> list:
        return self.data.get("captions", [])

    @property
    def ep_dir(self) -> str:
        return os.path.dirname(os.path.abspath(self.path))


def _version_key(p):
    m = re.search(r"_v(\d+)\.json$", p)
    return int(m.group(1)) if m else 0


def find_spec(episode: str) -> str:
    """`episode` may be an episode json or an episode directory (newest episode_v<N>.json wins)."""
    if os.path.isfile(episode):
        return episode
    cands = glob.glob(os.path.join(episode, "episode_v*.json"))
    if cands:
        return max(cands, key=_version_key)
    p = os.path.join(episode, "episode.json")
    if os.path.isfile(p):
        return p
    raise FileNotFoundError(f"no episode json in {episode}")


def find_root(spec_path: str) -> str:
    d = os.path.dirname(os.path.abspath(spec_path))
    while True:
        if os.path.isdir(os.path.join(d, "episodes")) or os.path.isdir(os.path.join(d, ".git")):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            return os.getcwd()
        d = nd


def resolve(root: str, rel: str | None) -> str | None:
    if not rel:
        return None
    for base in (root, os.getcwd()):
        p = rel if os.path.isabs(rel) else os.path.join(base, rel)
        if os.path.exists(p):
            return p
    return None


def load_words(path: str, offset_s: float) -> list:
    with open(path) as fh:
        raw = json.load(fh)
    if isinstance(raw, dict):
        raw = raw.get("words", [])
    out = []
    for w in raw:
        if "s" in w:  # ElevenLabs alignment (seconds)
            out.append(Word(w["w"], w["s"] + offset_s, w["e"] + offset_s))
        elif "start_ms" in w:
            out.append(Word(w["text"], w["start_ms"] / 1000 + offset_s, w["end_ms"] / 1000 + offset_s))
        elif "start" in w:
            out.append(Word(w.get("word") or w.get("text") or w.get("w"), w["start"] + offset_s, w["end"] + offset_s))
    return sorted(out, key=lambda w: w.start)


def load(episode: str, spec: str | None = None) -> Episode:
    path = spec or find_spec(episode)
    with open(path) as fh:
        data = json.load(fh)
    root = find_root(path)
    ep = Episode(path=path, root=root, data=data)
    audio = data.get("audio") or {}
    wp = resolve(root, audio.get("wordsJson"))
    if wp:
        ep.words = load_words(wp, audio.get("offsetFrames", 0) / ep.fps)
    return ep


# ---- ENGAGEMENT 2.1 beat map, normalised to duration D --------------------------------------
# (house mapping of the table's windows to half-open intervals; MIDPOINT is centred on 0.45D)
def sections(D: float):
    return [
        ("HOOK", 0.0, min(3.0, D)),
        ("CONTEXT", 3.0, 0.15 * D),
        ("ESCALATION_1", 0.15 * D, 0.40 * D),
        ("MIDPOINT", 0.40 * D, 0.50 * D),
        ("ESCALATION_2", 0.50 * D, 0.80 * D),
        ("PAYOFF", 0.80 * D, 0.95 * D),
        ("STING", 0.95 * D, D),
    ]


def section_at(t: float, D: float) -> str:
    for name, a, b in sections(D):
        if a <= t < b:
            return name
    return "STING"
