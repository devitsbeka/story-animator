"""Narration text handling: performance tags, prompt building, script words, syllables.

story.json narration lines carry a delivery tag (``tag: "excited"``) and may also carry inline
ElevenLabs v3/v4 audio tags inside the text (``"... [whispers] don't move."``).  Tags are directions,
never words: they are sent to tag-aware models and stripped from the script words that the
word-timing file lists.
"""
import re

TAG_RE = re.compile(r"\[[^\[\]]{1,60}\]")
# models that read inline [tags] as delivery directions; older models would read them aloud
TAG_MODELS = ("eleven_v3", "eleven_v4")


def model_reads_tags(model_id):
    return any(str(model_id or "").startswith(m) for m in TAG_MODELS)


def strip_tags(text):
    return re.sub(r"\s{2,}", " ", TAG_RE.sub(" ", text)).strip()


def line_prompt(line, model_id):
    """One narration line as sent to the TTS model."""
    text = line["text"].strip()
    tag = (line.get("tag") or "").strip().strip("[]")
    if not model_reads_tags(model_id):
        return strip_tags(text)
    if tag and not text.startswith("["):
        return f"[{tag}] {text}"
    return text


def chunk_prompt(lines, model_id):
    """Lines joined one per paragraph (the delivery reads each as its own breath group)."""
    return "\n\n".join(line_prompt(l, model_id) for l in lines)


def script_words(text):
    """Words as they appear in the words file: whitespace tokens with [tags] removed.  Punctuation stays
    attached (``yacht...``, ``DIED.``); bare punctuation tokens such as ``...`` or ``-`` are dropped."""
    out = []
    for tok in strip_tags(text).split():
        if norm(tok):
            out.append(tok)
    return out


def norm(word):
    """Comparison form: lower case, letters/digits/apostrophes only."""
    return re.sub(r"[^a-z0-9']", "", word.lower().replace("’", "'")).strip("'")


_VOWELS = "aeiouy"


def syllables(word):
    """Heuristic English syllable count (>= 1 for any word with a letter or digit)."""
    w = norm(word)
    if not w:
        return 0
    if w.isdigit():
        # numbers are read out: about 1.5 syllables per digit is a fair duration proxy
        return max(1, round(len(w) * 1.5))
    w = w.replace("'", "")
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and n > 1:
        n -= 1
    if w.endswith("ed") and len(w) > 3 and w[-3] not in "td" and n > 1:
        n -= 1
    return max(1, n)
