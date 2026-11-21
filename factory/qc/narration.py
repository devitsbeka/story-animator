"""Transcript checks from Stage 5 word timings (ENGAGEMENT sections 1, 2 and 3)."""
from __future__ import annotations

import os

from .common import (BANNED_BODY, BANNED_OPENERS, END_SIGNAL, REHOOK, SUPERLATIVES, TENSION, THREAT,
                     check, is_number_token, norm_token, rnd, skip)


def sentences(words):
    """Split the word list on terminal punctuation -> list of lists of Word."""
    out, cur = [], []
    for w in words:
        cur.append(w)
        if w.text.rstrip("\"')”").endswith((".", "!", "?")):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _text(ws):
    return " ".join(norm_token(w.text) for w in ws)


def _phrase_times(words, phrases):
    """Start times of each phrase occurrence (token sequence match)."""
    toks = [norm_token(w.text) for w in words]
    hits = []
    for ph in phrases:
        p = ph.split()
        for i in range(len(toks) - len(p) + 1):
            if toks[i:i + len(p)] == p:
                hits.append((words[i].start, ph))
    return sorted(hits)


def narration_checks(ep):
    W = ep.words
    D = ep.duration
    if not W:
        why = "no word timings (audio.wordsJson)"
        return [skip(i, s, why) for i, s in (("H-1.first_word", "HOOK"), ("N-1.wps", "NARRATION"), ("R-5", "RETENTION"))]
    out = []
    hook = [w for w in W if w.start < 3.0]
    toks = [norm_token(w.text) for w in W]
    n = len(W)
    span = W[-1].end - W[0].start

    # ---- HOOK -------------------------------------------------------------------------------
    out.append(check("H-1.first_word", "HOOK", W[0].start <= 0.30, rnd(W[0].start), "<= 0.30 s"))
    ht = [norm_token(w.text) for w in hook]
    has_you = any(t in ("you", "your", "you're", "youre") for t in ht)
    has_stake = any(is_number_token(t) or t in THREAT for t in ht)
    out.append(check("H-1.proposition", "HOOK", has_you and has_stake, " ".join(w.text for w in hook),
                     "by 3.0 s: you/your AND a number or threat word", {"you": has_you, "number_or_threat": has_stake}))
    sents = sentences(W)
    hook_s = [s for s in sents if s[0].start < 3.0]
    hw = sum(len(s) for s in hook_s)
    first_len = len(hook_s[0]) if hook_s else 0
    out.append(check("H-7", "HOOK", bool(hook_s) and len(hook_s) <= 2 and hw <= 18 and first_len <= 8,
                     {"sentences": len(hook_s), "words": hw, "first_sentence_words": first_len},
                     "<= 2 sentences, <= 18 words, first sentence <= 8 words"))
    opener = _text(hook)
    bad_open = [b for b in BANNED_OPENERS if (" " + opener + " ").find(" " + b + " ") >= 0]
    out.append(check("H-1.banned_opener", "HOOK", not bad_open, bad_open, "no banned opener in the first 3 s"))

    # ---- NARRATION --------------------------------------------------------------------------
    wps = n / span if span > 0 else 0
    out.append(check("N-1.wps", "NARRATION", 2.8 <= wps <= 3.1, rnd(wps, 2), "2.8-3.1 words/s overall"))
    hook_wps = len(hook) / max(1e-6, min(3.0, hook[-1].end) - hook[0].start) if hook else 0
    out.append(check("N-1.hook_wps", "NARRATION", hook_wps <= 3.3, rnd(hook_wps, 2), "hook <= 3.3 words/s"))
    pay = [w for w in W if 0.80 * D <= w.start < 0.95 * D]
    if len(pay) >= 3:
        pw = len(pay) / max(1e-6, pay[-1].end - pay[0].start)
        out.append(check("N-1.payoff_wps", "NARRATION", 2.3 <= pw <= 2.6, rnd(pw, 2), "payoff 2.3-2.6 words/s"))
    lo, hi = 2.65 * D, 3.0 * D  # ENGAGEMENT N-1 budget: 60 s ~ 160-180 words, 120 s ~ 320-360
    out.append(check("N-1.word_budget", "NARRATION", lo * 0.9 <= n <= hi * 1.1, n, f"{rnd(lo * 0.9, 0)}-{rnd(hi * 1.1, 0)} words for {rnd(D, 1)} s"))
    lens = [len(s) for s in sents]
    mean = sum(lens) / len(lens)
    short = sum(1 for x in lens if x <= 5) / len(lens)
    out.append(check("N-2.sentence_length", "NARRATION", 6 <= mean <= 10 and max(lens) <= 16 and short >= 0.30,
                     {"mean": rnd(mean, 2), "max": max(lens), "share_le5": rnd(short, 2)}, "mean 6-10, max <= 16, >= 30% <= 5 words"))
    you = sum(1 for t in toks if t in ("you", "your", "you're", "youre", "yourself"))
    out.append(check("N-3.second_person", "NARRATION", you / n >= 1 / 15, {"count": you, "per_word": rnd(you / n)}, ">= 1 per 15 words"))
    nums = [w for w in W if is_number_token(w.text)]
    voiced = max(span, 1e-6)
    out.append(check("N-4.density", "NARRATION", len(nums) / voiced * 10 >= 1, {"numbers": [w.text for w in nums], "per_10s": rnd(len(nums) / voiced * 10, 2)},
                     ">= 1 concrete number per 10 s", hard=False))
    story = os.path.join(ep.ep_dir, "story.json")
    if os.path.isfile(story):
        import json
        with open(story) as fh:
            facts = json.load(fh).get("facts") or []
        srcd = [f for f in facts if f.get("source_url")]
        out.append(check("N-4.sourced", "NARRATION", bool(facts) and len(srcd) == len(facts), f"{len(srcd)}/{len(facts)} facts sourced",
                         "every fact in story.json has a source_url (HTTP check not run offline)"))
    else:
        out.append(skip("N-4.sourced", "NARRATION", "no story.json facts[] to verify numbers against"))
    ten = sum(1 for t in toks if t in TENSION)
    out.append(check("N-5.tension", "NARRATION", ten / n >= 1 / 20, {"count": ten, "per_word": rnd(ten / n)}, ">= 1 tension word per 20 words"))
    sup = len(SUPERLATIVES.findall(" ".join(w.text for w in W)))
    out.append(check("N-5.superlatives", "NARRATION", sup <= 3 * max(1.0, D / 60), sup, f"<= {rnd(3 * max(1.0, D / 60), 1)} superlatives"))
    banned = _phrase_times(W, BANNED_BODY)
    out.append(check("N-10.banned", "NARRATION", not banned, [f"{rnd(t, 2)}s '{p}'" for t, p in banned], "no filler, hedging or CTA"))

    # ---- RETENTION --------------------------------------------------------------------------
    ends = [(t, p) for t, p in _phrase_times(W, END_SIGNAL) if t < D - 1.5]
    out.append(check("R-5", "RETENTION", not ends, [f"{rnd(t, 2)}s '{p}'" for t, p in ends], "no end-signal phrase before D-1.5 s"))
    rh = [t for t, _ in _phrase_times(W, REHOOK)]
    gaps = [b - a for a, b in zip([0.0] + rh, rh + [D])]
    need = int(D // 12)
    out.append(check("R-2.rehooks", "RETENTION", len(rh) >= need and rh and rh[0] <= 12 and max(gaps) <= 12,
                     {"count": len(rh), "first_s": rnd(rh[0] if rh else None, 2), "max_gap_s": rnd(max(gaps), 2)},
                     f">= {need} re-hook tokens, first <= 12 s, max gap <= 12 s (narration side only)"))
    return out
