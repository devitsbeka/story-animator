"""
captions.py - turn narration word timings into kinetic caption pages and STEP tracker spans
for the Remotion 'Finish' composition. Rules: factory/recipes/ENGAGEMENT_RECIPE.md section 5.

  C-2  1-3 words per page (2 preferred), one line, page duration 0.25-1.2 s
  C-4  at most 1 emphasised word per page, at most 35% of pages emphasised, numbers always
  C-5  a page starts on its first word's frame (never ahead of the audio)
  C-7  STEP badges persist for the whole step

Word json: [{"w": "You're", "s": 0.0, "e": 0.26}, ...] seconds from the start of the audio file,
which starts at film frame `offset`.
"""
import re

PUNCT_BREAK = re.compile(r"[.,!?;:—…]$")
NUM_WORDS = {
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
    "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
    "twenty", "thirty", "forty", "fifty", "hundred", "hundreds", "thousand", "thousands", "million",
    "millions", "first", "second", "third", "fourth",
}
STEP_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
            "nine": 9, "ten": 10, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9}
STOP = {"a", "an", "the", "to", "of", "and", "or", "in", "on", "is", "it", "you", "your", "that", "for",
        "at", "be", "with", "this", "so", "do", "not", "just", "are", "they", "if", "by"}

MAX_WORDS = 3
MAX_CHARS_3 = 14       # three words only when they are short (one line <= 800 px at ~100 px type)
MAX_PAGE_S = 1.2
MIN_PAGE_S = 0.25
GAP_BREAK_S = 0.30
TAIL_FRAMES = 6        # a page lingers this long after its last word if nothing follows
EMPH_MAX_SHARE = 0.35
LEAD_FRAMES = 6        # designed captions may lead the shot cut by a few frames


def norm(w):
    return re.sub(r"[^\w']", "", w.lower())


def display(w):
    """Keep ? and ! (they carry tone), drop commas/periods/quotes."""
    w = w.strip().strip('"“”')
    return re.sub(r"[.,;:]+$", "", w)


def is_number(w):
    n = norm(w)
    return bool(re.search(r"\d", n)) or n in NUM_WORDS


def frame(t, fps, offset):
    return int(offset + round(t * fps))


def _anchor_index(anchors):
    """anchors = episode 'captions' [{from,to,big,small?,tone?}] -> list of (from, to, {word}, tone)."""
    out = []
    for a in anchors or []:
        words = {norm(x) for x in str(a.get("big", "")).split()} - STOP - {""}
        if words:
            out.append((int(a["from"]), int(a["to"]), words, a.get("tone", "warm")))
    return out


def build_pages(words, fps=30, offset=0, anchors=None):
    """Return [{from, to, words:[{t, from}], emph: index|None, tone}] in film frames."""
    ws = [w for w in words if str(w.get("w", "")).strip()]
    groups, cur = [], []
    for i, w in enumerate(ws):
        if cur:
            prev = cur[-1]
            chars = sum(len(x["w"]) for x in cur) + len(w["w"])
            brk = (
                len(cur) >= MAX_WORDS
                or (len(cur) == 2 and chars > MAX_CHARS_3)
                or PUNCT_BREAK.search(prev["w"].strip()) is not None
                or (w["s"] - prev["e"]) > GAP_BREAK_S
                or (w["e"] - cur[0]["s"]) > MAX_PAGE_S
                or (is_number(w["w"]) and len(cur) >= 2)
            )
            if brk:
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)

    pages = []
    for gi, g in enumerate(groups):
        f0 = frame(g[0]["s"], fps, offset)
        end = frame(g[-1]["e"], fps, offset) + TAIL_FRAMES
        if gi + 1 < len(groups):
            end = min(end, frame(groups[gi + 1][0]["s"], fps, offset))
        end = max(end, f0 + int(round(MIN_PAGE_S * fps)))
        end = min(end, f0 + int(round(MAX_PAGE_S * fps)))
        pages.append({
            "from": f0, "to": end,
            "words": [{"t": display(w["w"]), "from": frame(w["s"], fps, offset)} for w in g],
            "emph": None, "tone": "accent",
        })
    # C-5: pages never overlap (a later page starting early would run ahead of the audio)
    for a, b in zip(pages, pages[1:]):
        a["to"] = min(a["to"], b["from"])

    _emphasise(pages, groups, _anchor_index(anchors))
    return pages


def _emphasise(pages, groups, anchors):
    cand = []  # (priority, page index, word index, tone)
    for pi, (pg, g) in enumerate(zip(pages, groups)):
        num = [wi for wi, w in enumerate(g) if is_number(w["w"])]
        if num:
            cand.append((0, pi, num[0], "accent"))
            continue
        for a0, a1, aw, tone in anchors:
            if pg["from"] > a1 or pg["to"] < a0 - 6:
                continue
            hit = [wi for wi, w in enumerate(g) if norm(w["w"]) in aw]
            if hit:
                t = {"red": "danger", "green": "good"}.get(tone, "accent")
                cand.append((1 if tone == "red" else 2, pi, hit[-1], t))
                break
    limit = int(EMPH_MAX_SHARE * len(pages))
    used = set()
    for prio, pi, wi, tone in sorted(cand, key=lambda c: (c[0], c[1])):
        if len(used) >= limit and prio > 0:
            continue
        if pi in used:
            continue
        pages[pi]["emph"], pages[pi]["tone"] = wi, tone
        used.add(pi)


def build_steps(words, shots, fps=30, offset=0, anchors=None):
    """STEP spans [{n, label, title, from, to, total}]. Source: episode captions whose `small`
    reads 'step <n>' (title = big), else the narration words 'step <n>'. A step lasts until the
    next one; the last ends where the shot sequence letter changes (e.g. C29 -> E30)."""
    found = []
    for a in anchors or []:
        m = re.match(r"\s*step\s+(\w+)", str(a.get("small", "")), re.I)
        if m and m.group(1).lower() in STEP_NUM:
            found.append((int(a["from"]), STEP_NUM[m.group(1).lower()], str(a.get("big", "")).strip()))
    if not found:
        for i, w in enumerate(words[:-1]):
            if norm(w["w"]) == "step" and norm(words[i + 1]["w"]) in STEP_NUM:
                found.append((frame(w["s"], fps, offset), STEP_NUM[norm(words[i + 1]["w"])], ""))
    found.sort()
    end_film = shots[-1]["to"] if shots else (found[-1][0] + 1 if found else 0)
    steps = []
    for i, (f0, n, title) in enumerate(found):
        if i + 1 < len(found):
            f1 = found[i + 1][0]
        else:
            f1 = end_film
            probe = f0 + LEAD_FRAMES  # captions lead their word; the step belongs to the shot it lands in
            here = next((s for s in shots if s["from"] <= probe < s["to"]), None)
            if here:
                for s in shots:
                    if s["from"] > f0 and s["id"][:1] != here["id"][:1]:
                        f1 = s["from"]
                        break
        steps.append({"n": n, "label": f"STEP {n}", "title": title, "from": f0, "to": f1, "total": len(found)})
    return steps
