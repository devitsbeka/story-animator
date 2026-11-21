"""Word timings: [{w, s, e}] seconds, the format of episodes/sentinel/audio/narration.words.json.

Three sources, best first:
  1. character alignment from ElevenLabs ``/with-timestamps`` (``tokens_from_char_alignment``),
  2. a transcript with per-word times (ElevenLabs Scribe via the MCP ``creative_transcribe_audio`` tool
     or the REST ``/v1/speech-to-text`` endpoint, or any whisper-style word list),
  3. proportional by syllables over the detected speech regions (no timing source at all).
Sources 1 and 2 both become "timed tokens" that are matched to the script words with a sequence
alignment, so tags read in the transcript, misspellings and dropped words never shift later words.
"""
import difflib

from .text import TAG_RE, norm, syllables

ROUND = 2  # decimals, as in the Sentinel words file


def tokens_from_char_alignment(alignment):
    """ElevenLabs alignment {characters, character_start_times_seconds, character_end_times_seconds}
    -> [(token, s, e)] split on whitespace; [tag] tokens are dropped."""
    chars = alignment.get("characters") or []
    st = alignment.get("character_start_times_seconds") or []
    en = alignment.get("character_end_times_seconds") or []
    out, cur, cs, ce = [], [], None, None
    depth = 0

    def flush():
        nonlocal cur, cs, ce
        if cur:
            out.append(("".join(cur), cs, ce))
        cur, cs, ce = [], None, None

    for c, s, e in zip(chars, st, en):
        if c == "[":
            flush()
            depth += 1
            continue
        if c == "]":
            depth = max(0, depth - 1)
            continue
        if depth or c.isspace():
            flush()
            continue
        if cs is None:
            cs = float(s)
        cur.append(c)
        ce = float(e)
    flush()
    return out


def tokens_from_transcript(words):
    """Scribe / whisper style word lists -> [(token, s, e)].  Accepts {text|word|w, start|s, end|e}
    and Scribe's {type: word|spacing|audio_event}; drops spacing, audio events and [tags]."""
    if isinstance(words, dict):
        words = words.get("words") or words.get("segments") or []
    out = []
    for w in words:
        if w.get("type") not in (None, "word"):
            continue
        t = w.get("text", w.get("word", w.get("w", "")))
        t = TAG_RE.sub("", str(t)).strip()
        if not norm(t):
            continue
        s = w.get("start", w.get("s"))
        e = w.get("end", w.get("e"))
        if s is None or e is None:
            continue
        out.append((t, float(s), float(e)))
    return out


def speech_regions(silences, duration):
    """Invert [(silence_start, silence_end)] into speech intervals inside [0, duration]."""
    regions, t = [], 0.0
    for a, b in sorted(silences):
        b = duration if b != b else b  # NaN end = silence to the end
        if a > t + 1e-3:
            regions.append((t, min(a, duration)))
        t = max(t, b)
    if duration > t + 1e-3:
        regions.append((t, duration))
    return [(a, b) for a, b in regions if b - a > 0.02] or [(0.0, duration)]


def _spread(words, t0, t1):
    """Place words over [t0, t1] proportionally to syllables."""
    if not words:
        return []
    t1 = max(t1, t0)
    weights = [max(1, syllables(w)) for w in words]
    tot = float(sum(weights))
    out, acc = [], 0.0
    for w, k in zip(words, weights):
        s = t0 + (t1 - t0) * acc / tot
        acc += k
        e = t0 + (t1 - t0) * acc / tot
        out.append([w, s, e])
    return out


def proportional(words, duration, regions=None):
    """No timing source: spread words by syllables over the speech regions (silences stay empty)."""
    regions = regions or [(0.0, duration)]
    total = sum(b - a for a, b in regions)
    weights = [max(1, syllables(w)) for w in words]
    tot = float(sum(weights)) or 1.0

    def to_real(x, prefer_next):
        acc = 0.0
        for i, (a, b) in enumerate(regions):
            L = b - a
            if x < acc + L - 1e-9 or (not prefer_next and x <= acc + L + 1e-9) or i == len(regions) - 1:
                return a + min(max(x - acc, 0.0), L)
            acc += L
        return regions[-1][1]

    out, acc = [], 0.0
    for w, k in zip(words, weights):
        xs = total * acc / tot
        acc += k
        xe = total * acc / tot
        s = to_real(xs, prefer_next=True)
        e = to_real(xe, prefer_next=False)
        if e < s:  # straddled a silence: keep the word inside the region where it starts
            e = next(b for a, b in regions if a - 1e-9 <= s <= b + 1e-9)
        out.append([w, s, e])
    return _finish(out)


def align_to_script(words, tokens, duration, regions=None, stats=None):
    """Match timed tokens to script words.  Equal-length replaced runs map 1:1 (spelling differences);
    other gaps are filled by syllables between the neighbouring anchors.
    stats (dict, optional) receives matched / mapped / interpolated word counts."""
    if stats is not None:
        stats.update(words=len(words), matched=0, mapped=0, interpolated=0)
    if not tokens:
        if stats is not None:
            stats["interpolated"] = len(words)
        return proportional(words, duration, regions)
    a = [norm(w) for w in words]
    b = [norm(t[0]) for t in tokens]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    timed = [None] * len(words)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if stats is not None:
            if op == "equal":
                stats["matched"] += i2 - i1
            elif op == "replace" and i2 - i1 == j2 - j1:
                stats["mapped"] += i2 - i1
            elif op != "insert":
                stats["interpolated"] += i2 - i1
        if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                _, s, e = tokens[j1 + k]
                timed[i1 + k] = [words[i1 + k], s, e]
        elif op == "replace":
            span = _spread(words[i1:i2], tokens[j1][1], tokens[j2 - 1][2])
            timed[i1:i2] = span
    # fill gaps (deleted script words) between anchors
    i = 0
    while i < len(words):
        if timed[i] is not None:
            i += 1
            continue
        j = i
        while j < len(words) and timed[j] is None:
            j += 1
        t0 = timed[i - 1][2] if i > 0 else (regions[0][0] if regions else 0.0)
        t1 = timed[j][1] if j < len(words) else (regions[-1][1] if regions else duration)
        if t1 - t0 < 0.05 * (j - i):  # no room: borrow from both neighbours
            t1 = t0 + 0.08 * (j - i)
        timed[i:j] = _spread(words[i:j], t0, t1)
        i = j
    return _finish(timed)


def _finish(timed):
    out, last = [], 0.0
    for w, s, e in timed:
        s = max(float(s), last)
        e = max(float(e), s + 0.01)
        out.append({"w": w, "s": round(s, ROUND), "e": round(e, ROUND)})
        last = s
    # enforce monotonic, non-overlapping starts after rounding
    for k in range(1, len(out)):
        if out[k]["s"] < out[k - 1]["s"]:
            out[k]["s"] = out[k - 1]["s"]
        if out[k]["e"] < out[k]["s"]:
            out[k]["e"] = out[k]["s"]
    return out


def shift(words, offset):
    return [{"w": x["w"], "s": round(x["s"] + offset, ROUND), "e": round(x["e"] + offset, ROUND)} for x in words]


def scale(words, factor):
    """Timings after a tempo change by `factor` (>1 = faster = shorter)."""
    return [{"w": x["w"], "s": round(x["s"] / factor, ROUND), "e": round(x["e"] / factor, ROUND)} for x in words]
