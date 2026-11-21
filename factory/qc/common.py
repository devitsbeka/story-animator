"""Shared QC primitives: rule results, sections, the house safe rectangle and lexicons.

Every check returns a list of rule dicts made by `rule()`. A rule ID is the recipe ID it
enforces (ENGAGEMENT_RECIPE `H-`, `R-`, `N-`, `P-`, `C-`, `S-`; PIXAR_RECIPE `H1`, `C7`, ...)
plus an optional `.suffix` for the sub-assertion, or a `TQ-` ID for technical checks that
the recipes imply but do not number (plates and the final mp4).
"""
from __future__ import annotations

import re

PASS, FAIL, WARN, SKIP = "pass", "fail", "warn", "skip"

# ENGAGEMENT section 8.2 weights. TECH and FRAMING are gates reported next to the score.
SECTION_WEIGHTS = {"HOOK": 30, "RETENTION": 20, "NARRATION": 15, "PACING": 15, "CAPTIONS": 10, "SOUND": 10}
GATE_SECTIONS = ("TECH", "FRAMING")
# ENGAGEMENT 8.2: HARD rules (any fail -> back to Stage 1/4).
HARD_PREFIXES = ("H-1", "H-3", "H-4", "R-5", "N-4.sourced", "C-1", "S-1")

# ENGAGEMENT 5.1 house safe rectangle on 1080x1920 (scaled for other sizes).
SAFE_RECT = (65, 290, 888, 1248)  # x0, y0, x1, y1
CAPTION_BAND = (1000, 1240)
HOOK_BAND = (300, 520)
CANVAS = (1080, 1920)

# ENGAGEMENT Appendix B (+ section 3 / 1 lists).
THREAT = {"drown", "sink", "freeze", "shark", "fire", "storm", "wave", "cliff", "venom", "hypothermia",
          "dehydration", "avalanche", "rip", "lightning", "dark", "died", "die", "dead", "deadly", "reef",
          "crash", "crunch", "stuck", "aground", "kill", "killed"}
TENSION = {"but", "suddenly", "except", "only", "last", "never", "mistake", "wrong", "seconds", "before",
           "until", "worse", "catch", "problem", "almost", "instead", "deadly"}
END_SIGNAL = ("in conclusion", "finally", "that's it", "to sum up", "thanks for watching", "so remember", "in summary")
BANNED_OPENERS = ("hey", "hi guys", "welcome", "in this video", "today we", "let me tell you", "have you ever wondered")
BANNED_BODY = ("basically", "actually", "so yeah", "kind of", "maybe", "like and subscribe", "subscribe")
REHOOK = ("but", "except", "then", "suddenly", "the problem is", "here's the catch", "worse")
NUMBER_WORDS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
                "twenty", "thirty", "forty", "fifty", "hundred", "hundreds", "thousand", "thousands", "million",
                "first", "second", "third", "fourth", "fifth", "half", "dozen"}
SUPERLATIVES = re.compile(r"\b(\w+est|most|best|worst|biggest|smartest)\b", re.I)


def rule(rid, section, status, measured=None, expected=None, detail=None, hard=None, source="auto", **extra):
    """One rule result. `hard` defaults to the ENGAGEMENT 8.2 HARD list."""
    if hard is None:
        hard = any(rid == p or rid.startswith(p + ".") for p in HARD_PREFIXES)
    r = {"id": rid, "section": section, "status": status, "hard": bool(hard), "measured": measured,
         "expected": expected, "detail": detail, "source": source}
    r.update(extra)
    return r


def check(rid, section, ok, measured=None, expected=None, detail=None, **kw):
    return rule(rid, section, PASS if ok else FAIL, measured, expected, detail, **kw)


def skip(rid, section, why, **kw):
    return rule(rid, section, SKIP, detail=why, **kw)


def norm_token(w: str) -> str:
    return re.sub(r"[^a-z0-9']", "", w.lower().replace("’", "'"))


def is_number_token(w: str) -> bool:
    t = norm_token(w)
    return bool(re.search(r"\d", t)) or t in NUMBER_WORDS


def scale_rect(rect, w, h):
    sx, sy = w / CANVAS[0], h / CANVAS[1]
    return (rect[0] * sx, rect[1] * sy, rect[2] * sx, rect[3] * sy)


def rnd(x, n=3):
    if x is None:
        return None
    if isinstance(x, (list, tuple)):
        return [rnd(v, n) for v in x]
    try:
        return round(float(x), n)
    except (TypeError, ValueError):
        return x
