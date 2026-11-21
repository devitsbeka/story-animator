"""Caption QC from caption layout data (no OCR).

Each caption page in episode.json is laid out with the same geometry as the Remotion
component `studio/src/kit/type.tsx` (`Caption`): a container inset 6% left/right, its top at
11.5% / 42% / 66% of the height for at="top"/"mid"/"low", a 40 px uppercase Inter context line
(+0.14em tracking, 6 px gap) over the anchor word in Playfair Display Italic 800 at
150/118/96/80 px by length, line-height 1.02, centred, wrapping inside the container.
Glyph widths are average-advance estimates (no font files are read), so boxes are +-10%.
A caption may carry an explicit `box: [x0, y0, x1, y1]` (px) from the finishing stage,
which then wins over the model.
"""
from __future__ import annotations

from .common import FAIL, HOOK_BAND, SAFE_RECT, check, norm_token, rnd, rule, skip

# average advance per character, in em (measured on typical Latin text for these faces)
SANS_UPPER_EM = 0.68 + 0.14  # Inter 700 uppercase + letter-spacing 0.14em
SERIF_ITALIC_EM = 0.50       # Playfair Display Italic 800
SMALL_PX, SMALL_GAP = 40, 6
LINE_H_SMALL = 1.2
TOP_FRAC = {"top": 0.115, "mid": 0.42, "low": 0.66}


def big_size(text):
    n = len(text)
    return 150 if n <= 6 else 118 if n <= 10 else 96 if n <= 16 else 80


def _wrap(text, px, em, maxw):
    """Greedy word wrap -> list of line widths."""
    space = 0.28 * px
    lines, cur = [], 0.0
    for wd in text.split():
        ww = len(wd) * em * px
        if cur and cur + space + ww > maxw:
            lines.append(cur)
            cur = ww
        else:
            cur = ww if not cur else cur + space + ww
    if cur or not lines:
        lines.append(cur)
    return lines


def layout(cap, w=1080, h=1920):
    """-> dict(box=(x0,y0,x1,y1), lines, big_px, cap_height_px)."""
    bp = big_size(cap.get("big", ""))
    if cap.get("box"):
        x0, y0, x1, y1 = cap["box"]
        return {"box": (x0, y0, x1, y1), "lines": None, "big_px": bp, "cap_height_px": 0.7 * bp, "source": "box"}
    left, right = w * 0.06, w * 0.94
    maxw = right - left
    top = h * TOP_FRAC.get(cap.get("at", "top"), 0.115)
    widths, y = [], top
    if cap.get("small"):
        sw = _wrap(cap["small"].upper(), SMALL_PX, SANS_UPPER_EM, maxw)
        widths += sw
        y += len(sw) * SMALL_PX * LINE_H_SMALL + SMALL_GAP
    bw = _wrap(cap.get("big", ""), bp, SERIF_ITALIC_EM, maxw)
    widths += bw
    y += len(bw) * bp * 1.02
    tw = min(max(widths), maxw)
    cx = (left + right) / 2
    return {"box": (cx - tw / 2, top, cx + tw / 2, y), "lines": len(bw), "big_px": bp, "cap_height_px": 0.7 * bp, "source": "model"}


def _inside(b, r):
    return b[0] >= r[0] and b[1] >= r[1] and b[2] <= r[2] and b[3] <= r[3]


def caption_checks(ep):
    caps = ep.captions
    fps = ep.fps
    if not caps:
        return [skip("C-1.captions", "CAPTIONS", "episode has no captions[] layout data")], []
    sx = ep.width / 1080
    sy = ep.height / 1920
    safe = (SAFE_RECT[0] * sx, SAFE_RECT[1] * sy, SAFE_RECT[2] * sx, SAFE_RECT[3] * sy)
    rows, out = [], []
    for c in caps:
        L = layout(c, ep.width, ep.height)
        text = " ".join(t for t in (c.get("small"), c.get("big")) if t)
        nw = len(text.replace("·", " ").split())
        rows.append({"from": c["from"], "to": c["to"], "text": text, "box": rnd(list(L["box"]), 1), "inside_safe": _inside(L["box"], safe),
                     "words": nw, "dur_s": rnd((c["to"] - c["from"]) / fps), "big_px": L["big_px"], "lines": L["lines"]})
    bad = [r for r in rows if not r["inside_safe"]]
    out.append(check("C-1.captions", "CAPTIONS", not bad, f"{len(rows) - len(bad)}/{len(rows)} pages inside", f"all caption boxes inside safe rect {safe}",
                     [{"from": r["from"], "text": r["text"], "box": r["box"]} for r in bad[:12]]))
    # >>> docuseries/shorts hook: a hook title ({"kind": "title"}) is checked by C-1 and C-6, not as a word page
    allcaps, allrows = caps, rows
    caps = [c for c in allcaps if c.get("kind") != "title"] or allcaps
    rows = [r for c, r in zip(allcaps, allrows) if c.get("kind") != "title"] or allrows
    # <<< hook title
    words = [r["words"] for r in rows]
    out.append(check("C-2.words_per_page", "CAPTIONS", max(words) <= 4 and sum(words) / len(words) <= 3,
                     {"max": max(words), "mean": rnd(sum(words) / len(words), 2)}, "max <= 4, mean <= 3"))
    ok_d = [0.25 <= r["dur_s"] <= 1.2 for r in rows]
    out.append(check("C-2.page_duration", "CAPTIONS", all(ok_d), f"{sum(ok_d)}/{len(rows)} in range", "every page 0.25-1.2 s",
                     {"min_s": min(r["dur_s"] for r in rows), "max_s": max(r["dur_s"] for r in rows)}))
    multi = [r for r in rows if (r["lines"] or 1) > 1]
    out.append(check("C-2.single_line", "CAPTIONS", not multi, f"{len(rows) - len(multi)}/{len(rows)} single-line anchors", "anchor on one line",
                     [r["text"] for r in multi]))
    ch = [0.7 * r["big_px"] for r in rows]
    okc = [70 <= v <= 95 for v in ch]
    out.append(check("C-3.cap_height", "CAPTIONS", sum(okc) / len(okc) >= 0.9, f"{sum(okc)}/{len(okc)} pages", "anchor cap-height 70-95 px (font ~100-136 px)",
                     {"min_px": rnd(min(ch), 1), "max_px": rnd(max(ch), 1)}))
    # C-5 sync: the page appears within +-2 frames of the start of one of its words
    if ep.words:
        diffs = []
        for c, r in zip(caps, rows):
            toks = {norm_token(t) for t in r["text"].split()} - {""}
            t0 = c["from"] / fps
            cands = [w.start for w in ep.words if norm_token(w.text) in toks and abs(w.start - t0) <= 2.0]
            if cands:
                diffs.append((c["from"] - min(cands, key=lambda s: abs(s - t0)) * fps))
        within = [abs(d) <= 2 for d in diffs]
        early = [d < -2 for d in diffs]
        share = sum(within) / len(within) if within else 0.0
        out.append(check("C-5.sync", "CAPTIONS", share >= 0.95 and not any(early), {"within_2f": rnd(share), "matched": len(diffs), "ahead_of_audio": sum(early)},
                         ">= 95% of pages within +-2 frames of their word; never > 2 frames ahead",
                         {"offsets_frames": [rnd(d, 1) for d in diffs]}))
    else:
        out.append(skip("C-5.sync", "CAPTIONS", "no word timings"))
    # C-6 hook title in the hook band over [0, >= 2 s], not overlapping the caption band
    hook = [(c, r) for c, r in zip(allcaps, allrows) if c["from"] <= 1 and c["to"] >= 2.0 * fps]
    if hook:
        c, r = hook[0]
        b = r["box"]
        ok = b[1] >= HOOK_BAND[0] * sy and b[3] <= HOOK_BAND[1] * sy
        out.append(check("C-6.hook_title", "CAPTIONS", ok, b, f"title box inside the hook band y {HOOK_BAND}"))
    else:
        first = allrows[0]
        out.append(rule("C-6.hook_title", "CAPTIONS", FAIL, f"first page {first['from']}-{first['to']} f", "a hook title visible from frame 0 to >= 2.0 s",
                        "no caption covers [0, 2.0 s]"))
    return out, allrows
