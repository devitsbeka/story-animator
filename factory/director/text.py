"""Text metrics for the narration checklists, with lexicons read from ENGAGEMENT_RECIPE.md Appendix B
(so editing the recipe edits the validator)."""
import functools
import os
import re

from .paths import RECIPES

WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9']*")
NUMBER_WORDS = {"two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen",
                "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty",
                "sixty", "seventy", "eighty", "ninety", "hundred", "hundreds", "thousand", "thousands", "million", "millions",
                "half", "dozen", "dozens"}
ORDINAL_PREFIX = {"step"}          # "Step two" is an ordinal label, not a factual number
YOU = {"you", "your", "you're", "yours", "yourself", "you've", "you'll", "you'd"}
# R-2 re-hook contrast tokens (multi-word ones matched on the lower-cased line)
REHOOK_TOKENS = ["but", "except", "then", "suddenly", "the problem is", "here's the catch", "worse"]
FILLER = ["basically", "actually", "so yeah"]
HEDGES = ["kind of", "maybe"]
CTA = ["like and subscribe", "subscribe"]
LOW_ENERGY_TAGS = {"whisper", "whispers", "whispering", "quiet", "soft", "low", "hushed", "calm"}
SUPERLATIVE_RE = re.compile(r"\b(\w+est|most|best|worst|biggest|deadliest)\b", re.I)
_NOT_SUPERLATIVE = {"just", "west", "rest", "test", "est", "honest", "interest", "forest", "chest", "guest", "nest", "lest",
                    "invest", "request", "contest", "protest", "suggest", "digest", "arrest", "modest", "harvest", "almost"}


@functools.lru_cache(maxsize=1)
def lexicons():
    """{'threat': [...], 'tension': [...], 'end-signal ...': [...], 'banned openers': [...]} from Appendix B."""
    with open(os.path.join(RECIPES, "ENGAGEMENT_RECIPE.md"), encoding="utf-8") as fh:
        md = fh.read()
    app = md[md.index("## Appendix B"):]
    out = {}
    for m in re.finditer(r"^- \*\*([^:*]+?)(?: \([^)]*\))?:\*\*\s*(.+)$", app, re.M):
        key = m.group(1).strip().lower()
        val = re.sub(r"\([^)]*\)", "", m.group(2))
        out[key] = [w.strip().lower() for w in val.split(",") if w.strip()]
    return out


def lex(name):
    for k, v in lexicons().items():
        if k.startswith(name):
            return v
    raise KeyError(name)


def words(text):
    return WORD_RE.findall(text)


def lower_words(text):
    return [w.lower() for w in words(text)]


def sentences(text):
    """Split on . ! ? and ellipses; drops empty fragments."""
    return [s for s in (p.strip() for p in re.split(r"(?:\.\.\.|…|[.!?])+", text)) if words(s)]


def has_phrase(text, phrase):
    return re.search(r"(?<![A-Za-z'])" + re.escape(phrase) + r"(?![A-Za-z'])", text.lower()) is not None


def numbers_in(text):
    """Digits and number words, skipping ordinal step labels ('Step two') and the word 'one'."""
    toks = lower_words(text)
    out = []
    for i, w in enumerate(toks):
        prev = toks[i - 1] if i else ""
        if prev in ORDINAL_PREFIX:
            continue
        if re.fullmatch(r"\d[\d,.']*", w) or w in NUMBER_WORDS:
            out.append(w)
    return out


def count_lexicon(text, words_list, stems=False):
    """Occurrences of lexicon entries as whole words (stems=True also matches inflections: sink -> sinking)."""
    t = text.lower()
    tail = r"[a-z']*" if stems else r"(?![a-z'])"
    return sum(len(re.findall(r"(?<![a-z'])" + re.escape(w) + tail, t)) for w in words_list)


def superlatives(text):
    return [w for w in SUPERLATIVE_RE.findall(text) if w.lower() not in _NOT_SUPERLATIVE and len(w) > 4]
