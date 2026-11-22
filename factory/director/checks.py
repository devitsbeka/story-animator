"""Automatable checklists (factory/recipes/*.md) for stages 1-4.

Rule ids match the recipes: ENGAGEMENT H-/R-/N-/P-/C-/T-, PIXAR S/C/P. Each check_* returns a Report.
Only checks that can be computed from the artifact at that stage are here; checks that need audio,
renders or vision (frame-0 face detection, optical flow, loudness...) belong to stage 9 QC.
"""
import math
import re
import statistics

from . import docuseries as doc
from . import schemas, text as tx
from .report import Report
from .staging import MARKS, vocabulary

FPS = 30

SHORT_BEATS = ["HOOK", "CONTEXT", "ESCALATION_1", "MIDPOINT", "ESCALATION_2", "PAYOFF", "STING"]
# ENGAGEMENT 2.1 beat map: expected start as a function of D
BEAT_START = {"HOOK": lambda D: 0.0, "CONTEXT": lambda D: 3.0, "ESCALATION_1": lambda D: 0.15 * D,
              "MIDPOINT": lambda D: 0.45 * D, "ESCALATION_2": lambda D: 0.45 * D, "PAYOFF": lambda D: 0.80 * D,
              "STING": lambda D: D - 3.0}
FORMAT = {
    "short": {"wps": (2.8, 3.1), "duration": (60, 120), "asl": (1.8, 2.6), "rehook_gap": 12.0},
    "docuseries": {"wps": (2.4, 2.7), "duration": (900, 1500), "asl": (3.0, 6.0), "rehook_gap": 180.0},
}


# >>> world_kits: shots staged on a world kit use that kit's marks (factory/worlds)
def _kit_ids():
    from factory.worlds import kits
    return set(kits.kit_ids())


def shot_kit(s, plan):
    """The (non-legacy) world kit a shot plays on, or None for the yacht/island world."""
    from factory.worlds import kits
    k = s.get("set") or (plan.get("world") or {}).get("set")
    if not k or k not in _kit_ids():
        return None
    kit = kits.load(k)
    return None if kit.get("legacy") else kit


def shot_marks(s, plan):
    kit = shot_kit(s, plan)
    if kit is None:
        return MARKS
    from factory.worlds import layout
    return layout.marks(kit, s.get("set_seed"))
# <<< world_kits


def _line_map(story):
    return {ln["id"]: ln for ln in story["narration"]}


def _all_text(story):
    return " ".join(ln["text"] for ln in story["narration"])


# ============================================================ stage 1: story.json
def check_story(story):
    rep = Report("develop", story.get("overrides"))
    errs = schemas.validate("story", story)
    if errs:
        rep.schema_errors(errs)
        return rep
    fmt = story["format"]
    F = FORMAT[fmt]
    D = float(story["duration_s"])
    lines = story["narration"]
    lmap = _line_map(story)
    beats = story["beats"]
    bmap = {b["id"]: b for b in beats}
    full = _all_text(story)
    n_words = len(tx.words(full))

    # ---- integrity
    ids = [ln["id"] for ln in lines]
    rep.hard("INTEGRITY.line_ids", len(ids) == len(set(ids)), "narration ids must be unique")
    rep.hard("INTEGRITY.beat_refs", all(ln["beat"] in bmap for ln in lines),
             f"narration[].beat must reference beats[].id; bad: {[ln['id'] for ln in lines if ln['beat'] not in bmap]}")
    rep.hard("INTEGRITY.line_times", all(0 <= ln["t0"] < ln["t1"] <= D + 0.01 for ln in lines),
             "every line needs 0 <= t0 < t1 <= duration_s")
    rep.hard("INTEGRITY.line_order", all(a["t1"] <= b["t0"] + 1e-6 for a, b in zip(lines, lines[1:])),
             "narration lines must be in time order without overlap")
    rep.hard("INTEGRITY.hook_lines", all(i in lmap for i in story["hook"]["line_ids"]), "hook.line_ids must exist")
    rep.hard("INTEGRITY.cq_line", story["core_question"]["answer_line"] in lmap, "core_question.answer_line must exist")
    fact_ids = {f["id"] for f in story["facts"]}
    rep.hard("INTEGRITY.fact_refs", all(fid in fact_ids for ln in lines for fid in ln.get("facts", [])),
             "narration[].facts must reference facts[].id")
    rep.check("INTEGRITY.duration", F["duration"][0] <= D <= F["duration"][1],
              f"duration_s {D} outside the {fmt} range {F['duration']}")

    # ---- HOOK (ENGAGEMENT 1)
    hook = story["hook"]
    hook_lines = [lmap[i] for i in hook["line_ids"] if i in lmap]
    hook_text = " ".join(ln["text"] for ln in hook_lines)
    hw = tx.lower_words(hook_text)
    rep.hard("H-1", bool(hook_lines) and hook_lines[0]["t0"] <= 0.3 and lines[0]["id"] == hook_lines[0]["id"] and hook["visual"].strip(),
             "the hook must be the first narration line, start at t <= 0.3 s, and have a frame-0 visual")
    first_sent = tx.sentences(hook_text)[:1]
    rep.check("H-7", len(hw) <= 18 and (not first_sent or len(tx.words(first_sent[0])) <= 8),
              f"hook narration must be <= 18 words with a first sentence <= 8 words (has {len(hw)} words, first sentence "
              f"{len(tx.words(first_sent[0])) if first_sent else 0})")
    has_you = any(w in tx.YOU for w in hw)
    has_num_or_threat = bool(tx.numbers_in(hook_text)) or tx.count_lexicon(hook_text, tx.lex("threat"), stems=True) > 0
    rep.check("H-hook-keywords", has_you and has_num_or_threat,
              "hook narration must contain you/your AND (a number OR a threat-lexicon word)")
    ov = hook["text_overlay"]
    ow = tx.words(ov["text"])
    ov_kw = bool(tx.numbers_in(ov["text"])) or bool(re.search(r"\d", ov["text"])) or tx.count_lexicon(ov["text"], tx.lex("threat"), stems=True) > 0
    rep.check("H-5", 2 <= len(ow) <= 6 and ov["start"] == 0 and ov["end"] >= 2.0 and ov_kw,
              f"hook.text_overlay needs 2-6 words, start 0, end >= 2.0 and a number or threat noun (got {ov})")
    opener = " ".join(tx.lower_words(lines[0]["text"])[:6])
    rep.check("H-banned-openers", not any(tx.has_phrase(opener, p) for p in tx.lex("banned openers")),
              "banned opener in the first line")
    cq_line = lmap.get(story["core_question"]["answer_line"])
    if cq_line:
        rep.hard("H-6", cq_line["t0"] >= 0.5 * D, f"the core question is answered at {cq_line['t0']:.1f} s, before 0.5 D ({0.5 * D:.1f} s)")

    # ---- story spine (PIXAR 2.1)
    sp = story["spine"]
    rep.hard("S1", all(sp[k].strip() for k in ("once_upon_a_time", "every_day", "one_day", "until_finally", "ever_since"))
             and len(sp["because_of_that"]) >= 2, "spine needs all 8 slots with >= 2 'because of that' lines")
    rep.hard("S1-causal", not any(re.match(r"\s*and then\b", b, re.I) for b in sp["because_of_that"]),
             "a 'because of that' line reads as 'and then' (episodic, not causal)")
    rep.check("S-essence", len(tx.words(story["essence"])) <= 20, "essence must be <= 20 words (Coats #14/#22)")
    rep.check("S-flaw", bool(story["hero"]["flaw"].strip()), "hero needs a stated flaw or limitation (Coats #2/#6)")
    rep.check("S-attempts", len(story["attempts"]) >= 2 and any(a["outcome"] == "fail" for a in story["attempts"]),
              "hero must attempt >= 2 actions with at least one failure (Coats #1)")
    rep.hard("S7", bool(story["resolution"]["hero_action"].strip()), "resolution must be caused by a hero action (no deus ex machina)")
    if story["time_pressure"]:
        tc = story.get("ticking_clock")
        ok = bool(tc) and len(tc["readings"]) >= 3 and all(a["severity"] < b["severity"] for a, b in zip(tc["readings"], tc["readings"][1:]))
        rep.check("S5", ok, "time_pressure: ticking clock shown >= 3 times with monotonically worsening value")
    rep.check("S4", any(d["type"] in ("threat_reveal", "dramatic_irony") for d in story["suspense_devices"]),
              "use dramatic irony / a threat_reveal at least once")

    # ---- RETENTION (ENGAGEMENT 2)
    rep.hard("R-3", all(b["link"] in ("BUT", "THEREFORE") for b in beats[1:]), "every beat after the first links with BUT or THEREFORE")
    rep.hard("R-3-and-then", not tx.has_phrase(full, "and then"), "the transcript must not contain 'and then'")
    late = [ln for ln in lines if ln["t0"] < D - 1.5]
    bad_end = [p for p in tx.lex("end-signal") if any(tx.has_phrase(ln["text"], p) for ln in late)]
    rep.hard("R-5", not bad_end, f"end-signal phrases before D-1.5 s: {bad_end}")
    if fmt == "short":
        names = [b["name"] for b in beats]
        rep.hard("R-beats-order", names == SHORT_BEATS, f"beats must be exactly {SHORT_BEATS} in order (got {names})")
        if names == SHORT_BEATS:
            off = {b["name"]: round(b["t0"] - BEAT_START[b["name"]](D), 1) for b in beats if abs(b["t0"] - BEAT_START[b["name"]](D)) > 0.10 * D}
            rep.check("R-beats-window", not off, f"beat starts off the 2.1 beat map by more than 10% of D: {off}")
            core = [b["stakes"] for b in beats if b["name"] not in ("HOOK", "STING")]
            dips = [a - b for a, b in zip(core, core[1:]) if b < a]
            rep.check("R-4", len(dips) <= 1 and all(d <= 2 for d in dips), f"stakes must climb CONTEXT->PAYOFF (<= 1 dip of <= 2): {core}")
            mid = next(b for b in beats if b["name"] == "MIDPOINT")
            before = [b["visual_scale"] for b in beats if b["name"] in ("HOOK", "CONTEXT", "ESCALATION_1", "ESCALATION_2")]
            rep.check("R-2-midpoint", mid["visual_scale"] >= max(before) and 0.40 * D <= mid["t0"] <= 0.55 * D,
                      f"the midpoint ({mid['t0']:.1f} s) must sit at 0.40-0.55 D and have the highest visual_scale before the payoff")
        if cq_line:
            rep.check("R-6", 0.80 * D <= cq_line["t0"] <= 0.95 * D and D - cq_line["t1"] <= 4.0,
                      f"CQ answer at {cq_line['t0']:.1f} s must be in [0.80 D, 0.95 D] = [{0.8 * D:.1f}, {0.95 * D:.1f}] with <= 4 s after it")
    rh = [ln["t0"] for ln in lines if ln.get("rehook")]
    bad_rh = [ln["id"] for ln in lines if ln.get("rehook") and not (
        any(tx.has_phrase(ln["text"], t) for t in tx.REHOOK_TOKENS) or tx.count_lexicon(ln["text"], tx.lex("tension")) or "?" in ln["text"])]
    rep.check("R-2-tokens", not bad_rh, f"re-hook lines without a contrast/tension token or question: {bad_rh}")
    gaps = [b - a for a, b in zip([0.0] + rh, rh + [D])]
    need = math.floor(D / 12) if fmt == "short" else math.floor(D / 180)
    first_ok = bool(rh) and rh[0] <= F["rehook_gap"]
    rep.check("R-2", len(rh) >= need and first_ok and max(gaps[:-1] or [0]) <= F["rehook_gap"],
              f"re-hooks: need >= {need}, first <= {F['rehook_gap']:.0f} s, gaps <= {F['rehook_gap']:.0f} s (got times {[round(t, 1) for t in rh]})")
    loops = story["open_loops"]
    prim = [lp for lp in loops if lp["primary"]]
    rep.check("R-1", bool(prim) and len(loops) >= 3 and all(lp["closed_t"] <= D for lp in loops),
              "need 1 primary loop + >= 2 secondary loops, all closed by D")
    if loops:
        lo, hi = 3.0, D - 3.0
        t, covered = lo, True
        while t <= hi:
            if not any(lp["opened_t"] <= t < lp["closed_t"] for lp in loops):
                covered = False
                break
            t += 0.5
        rep.check("R-1-open", covered, f"no open loop at t = {t:.1f} s (one must be open for all t in [3, D-3])")
    rep.check("R-7", story["loop_back"]["method"] in ("text_join", "frame_match", "reverse_question") and story["loop_back"]["desc"].strip(),
              "declare the loop-back method")

    # ---- NARRATION (ENGAGEMENT 3)
    span = lines[-1]["t1"] - lines[0]["t0"]
    wps = n_words / span if span > 0 else 0
    lo, hi = F["wps"]
    rep.check("N-1", lo <= wps <= hi, f"words/s over the narration span is {wps:.2f}, target [{lo}, {hi}]")
    if fmt == "short":
        hook_wps = len(hw) / max(0.01, hook_lines[-1]["t1"] - hook_lines[0]["t0"]) if hook_lines else 0
        rep.check("N-1-hook", hook_wps <= 3.3, f"hook words/s {hook_wps:.2f} > 3.3")
        pay = [ln for ln in lines if bmap.get(ln["beat"], {}).get("name") in ("PAYOFF",)] or ([cq_line] if cq_line else [])
        if pay:
            pw = sum(len(tx.words(ln["text"])) for ln in pay) / max(0.01, sum(ln["t1"] - ln["t0"] for ln in pay))
            rep.check("N-1-payoff", 2.3 <= pw <= 2.6, f"payoff words/s {pw:.2f} outside [2.3, 2.6]")
        budget = 2.83 * D
        rep.check("N-1-budget", abs(n_words - budget) <= 0.10 * budget, f"{n_words} words vs budget {budget:.0f} (+-10%) for D = {D:.0f} s")
    sents = [len(tx.words(s)) for ln in lines for s in tx.sentences(ln["text"])]
    if sents:
        mean, mx = statistics.mean(sents), max(sents)
        short_share = sum(1 for n in sents if n <= 5) / len(sents)
        rep.check("N-2", 6 <= mean <= 10 and mx <= 16 and short_share >= 0.30,
                  f"sentences: mean {mean:.1f} (6-10), max {mx} (<= 16), share <= 5 words {short_share:.2f} (>= 0.30)")
    you = sum(1 for w in tx.lower_words(full) if w in tx.YOU)
    rep.check("N-3", you * 15 >= n_words, f"you/your density {you}/{n_words} words is below 1 per 15")
    # N-4 (HARD): every spoken number is backed by a sourced fact
    backed = {n.lower() for f in story["facts"] for n in f.get("numbers", [])}
    unbacked = sorted({n for ln in lines for n in tx.numbers_in(ln["text"]) if n not in backed})
    rep.hard("N-4", not unbacked, f"numbers spoken without a facts[].numbers entry (with source_url): {unbacked}")
    rep.hard("P5", all(f["source_url"].startswith("http") for f in story["facts"]), "every fact needs a source URL")
    if fmt == "short":
        nums_t = sorted(ln["t0"] for ln in lines if tx.numbers_in(ln["text"]))
        gaps = [b - a for a, b in zip([lines[0]["t0"]] + nums_t, nums_t + [lines[-1]["t1"]])]
        rep.check("N-4-density", bool(nums_t) and max(gaps) <= 10.0, f"need a concrete number every 10 s (largest gap {max(gaps):.1f} s)")
    tension = tx.count_lexicon(full, tx.lex("tension"))
    rep.check("N-5", tension * 20 >= n_words, f"tension-word density {tension}/{n_words} words is below 1 per 20")
    sup = tx.superlatives(full)
    rep.check("N-5-superlatives", len(sup) <= 3 * max(1, D / 60), f"too many superlatives: {sup}")
    steps = story["steps"]
    if steps or fmt == "short":
        ordinals = ["one", "two", "three", "four", "five"]
        ok = 3 <= len(steps) <= 5 and [s["n"] for s in steps] == list(range(1, len(steps) + 1))
        for s in steps:
            ln = lmap.get(s["line_id"])
            ok = ok and ln is not None and re.search(rf"\bstep {ordinals[s['n'] - 1]}\b", " ".join(tx.lower_words(" ".join(
                l2["text"] for l2 in lines if abs(l2["t0"] - ln["t0"]) < 6)))) is not None and len(tx.words(s["instruction"])) <= 14
        rep.check("N-6", ok, "need 3-5 numbered steps ('Step one...') each <= 14 words of instruction")
    ranked = sorted(story["facts"], key=lambda f: -f["surprise"])
    fact_t = {}
    for ln in lines:
        for fid in ln.get("facts", []):
            fact_t.setdefault(fid, ln["t0"])
    if fmt == "short" and ranked:
        t = [fact_t.get(f["id"]) for f in ranked[:3]]
        ok7 = t[0] is not None and 0.80 * D <= t[0] <= 0.95 * D
        if len(t) > 1:
            ok7 = ok7 and t[1] is not None and 0.40 * D <= t[1] <= 0.55 * D
        ok7 = ok7 and all(x is None or x >= 0.5 * D for x in t[:1]) and all(x is None or x >= 0.40 * D for x in t[1:])
        rep.check("N-7", ok7, f"surprise ranking {[f['id'] for f in ranked[:3]]} at {t} s: #1 must land in [0.80 D, 0.95 D], "
                              f"#2 at 0.40-0.55 D, none of the top 3 spent early")
    tags = [ln["tag"].lower() for ln in lines]
    rep.check("N-9", all(tags) and any(t in tx.LOW_ENERGY_TAGS for t, ln in zip(tags, lines) if cq_line is None or ln["t0"] < cq_line["t0"]),
              "every line needs a delivery tag and >= 1 low-energy tag (whisper) before the payoff")
    banned = [p for p in tx.FILLER + tx.HEDGES + tx.CTA if tx.has_phrase(full, p)]
    rep.check("N-10", not banned, f"banned filler/hedge/CTA phrases: {banned}")

    # ---- TITLE (ENGAGEMENT 7)
    title = story["title"]
    t_kw = bool(re.search(r"\d", title)) or bool(tx.numbers_in(title)) or tx.count_lexicon(title, tx.lex("threat"), stems=True) > 0
    if fmt == "short":
        rep.check("T-3", len(title) <= 60 and t_kw, f"title must be <= 60 chars with a number or threat noun: {title!r}")
        rep.check("T-5", title.lower() != ov["text"].lower() and ov["text"].lower() != hook_text.lower(),
                  "title, cover/hook text and hook line must not be identical strings")

    # ---- DOCUSERIES (ARCHITECTURE: formats)
    if fmt == "docuseries":
        _check_docuseries(story, rep, D)
    return rep


def _check_docuseries(story, rep, D):
    ch = story.get("chapters") or []
    rep.hard("DOC-chapters", 5 <= len(ch) <= 8, f"docuseries needs 5-8 chapters (got {len(ch)})")
    co = story.get("cold_open")
    rep.hard("DOC-cold-open", bool(co) and co["t0"] == 0 and co["t1"] - co["t0"] <= 90, "cold open must start at 0 and last <= 90 s")
    rep.hard("DOC-tease", bool((story.get("tease_next") or "").strip()), "end with a tease of the next episode")
    ordered = all(a["t1"] <= b["t0"] + 1e-6 for a, b in zip(ch, ch[1:]))
    rep.hard("DOC-chapter-order", ordered and all(c["t0"] < c["t1"] <= D for c in ch), "chapters must be ordered, non-overlapping, inside D")
    for c in ch:
        sp = c["spine"]
        rep.hard(f"DOC-spine.{c['id']}", bool(sp["hook"].strip() and sp["payoff"].strip() and sp["escalation"]),
                 f"chapter {c['id']} needs its own spine (hook, escalation, payoff)")
        sc = c["short_candidate"]
        if sc:
            dur = sc["out"] - sc["in"]
            rep.check(f"DOC-short.{c['id']}", 45 <= dur <= 90 and c["t0"] <= sc["in"] < sc["out"] <= c["t1"] and sc["hook_line"].strip()
                      and sc["setup"].strip() and sc["turn"].strip() and sc["payoff"].strip(),
                      f"short_candidate {sc['id']}: 45-90 s inside chapter {c['id']} with hook line, setup, turn and payoff (got {dur:.0f} s)")
    n_sc = sum(1 for c in ch if c["short_candidate"])
    rep.check("DOC-shorts-per-chapter", n_sc >= len(ch), f"every chapter should carry a short_candidate ({n_sc}/{len(ch)})")
    lines = story["narration"]
    lch = {c["id"] for c in ch}
    rep.hard("DOC-line-chapters", all(ln.get("chapter") in lch or (co and ln["t0"] < co["t1"]) for ln in lines),
             "every narration line outside the cold open must name its chapter")
    # >>> docuseries structure: cold open -> title -> chapters with act breaks -> climax -> resolution -> tease
    beats = story["beats"]
    names = [b["name"] for b in beats]
    title = next((b for b in beats if b["name"] == "TITLE"), None)
    rep.check("DOC-title-beat", bool(title) and bool(co) and abs(title["t0"] - co["t1"]) <= 3.0,
              f"a TITLE beat must follow the cold open (cold open ends {co and co['t1']}, title at {title and title['t0']})")
    arc = [next((b for b in beats if b["name"] == n), None) for n in ("CLIMAX", "RESOLUTION", "TEASE")]
    rep.check("DOC-arc", all(arc) and arc[0]["t0"] < arc[1]["t0"] < arc[2]["t0"] and arc[2]["t1"] >= D - 1.0
              and arc[0]["t0"] >= 0.6 * D, f"need CLIMAX (>= 0.6 D) -> RESOLUTION -> TEASE (ending at D) beats; got {names}")
    rh_t = [ln["t0"] for ln in lines if ln.get("rehook")]
    no_break = [c["id"] for c in ch[1:] if not any(c["t0"] - 1.0 <= t <= c["t0"] + 30.0 for t in rh_t)]
    rep.check("DOC-act-breaks", not no_break, f"every chapter after the first opens on an act-break re-hook (within 30 s): {no_break}")
    starts, ends = [ln["t0"] for ln in lines], [ln["t1"] for ln in lines]
    for c in ch:
        sc = c["short_candidate"]
        if not sc:
            continue
        on_line = any(abs(t - sc["in"]) <= 0.5 for t in starts) and any(abs(t - sc["out"]) <= 0.5 for t in ends)
        rep.check(f"DOC-short-cut.{c['id']}", on_line and len(tx.words(sc["hook_line"])) <= 14,
                  f"short_candidate {sc['id']}: in/out must sit on narration line boundaries (+-0.5 s) and the hook line be <= 14 words")
    # <<< docuseries structure


# ============================================================ stage 2: breakdown.json
def check_breakdown(bd, story):
    rep = Report("breakdown")
    errs = schemas.validate("breakdown", bd)
    if errs:
        rep.schema_errors(errs)
        return rep
    D = float(story["duration_s"])
    lmap = _line_map(story)
    emap = {e["id"]: e for e in bd["elements"]}
    rep.hard("INTEGRITY.element_ids", len(emap) == len(bd["elements"]), "element ids must be unique")
    covered = [i for s in bd["scenes"] for i in s["line_ids"]]
    missing = [i for i in lmap if i not in covered]
    rep.hard("B-every-line-has-picture", not missing, f"narration lines with no scene/picture: {missing}")
    rep.hard("INTEGRITY.scene_lines", all(i in lmap for i in covered), f"scene line_ids not in story: {[i for i in covered if i not in lmap]}")
    order = [lmap[i]["t0"] for s in bd["scenes"] for i in s["line_ids"] if i in lmap]
    rep.check("B-scene-order", order == sorted(order), "scenes should follow narration order")
    bad_refs = sorted({r for s in bd["scenes"] for r in s["elements"] + [s["location"]] if r not in emap})
    rep.hard("INTEGRITY.element_refs", not bad_refs, f"scenes reference unknown elements: {bad_refs}")
    rep.hard("B-location-kind", all(emap.get(s["location"], {}).get("kind") in ("location", "set") for s in bd["scenes"]),
             "scene.location must be an element of kind location/set")
    used = {r for s in bd["scenes"] for r in s["elements"] + [s["location"]]}
    unused = sorted(k for k, e in emap.items() if k not in used and e["kind"] != "system")
    rep.check("B-unused-elements", not unused, f"elements never used on screen: {unused}")
    # S6: anything that solves the climax is planted on screen before 40% of runtime
    first_t = {}
    for s in bd["scenes"]:
        t0 = min((lmap[i]["t0"] for i in s["line_ids"] if i in lmap), default=D)
        for r in s["elements"]:
            first_t[r] = min(first_t.get(r, D), t0)
    late = [e["id"] for e in bd["elements"] if e.get("solves_climax") and first_t.get(e["id"], D) > 0.40 * D]
    rep.hard("S6", not late, f"climax-solving elements first seen after 40% of runtime: {late}")
    rep.check("B-hero", any(e["kind"] == "character" for e in bd["elements"]), "no character element (the hero)")
    if story.get("format") == "docuseries":
        # >>> docuseries: scenes are cut inside chapters, so a chapter (and its short) can be rendered and re-cut alone
        bad = []
        for s in bd["scenes"]:
            chs = {lmap[i].get("chapter") for i in s["line_ids"] if i in lmap}
            if len(chs) > 1 or (chs and s.get("chapter") != next(iter(chs))):
                bad.append(s["id"])
        rep.hard("DOC-scene-chapter", not bad, f"docuseries scenes must name the one chapter their lines belong to: {bad}")
    return rep


# ============================================================ stage 3: manifest.json
OK_LICENCES = {"CC0-1.0", "CC-BY-4.0", "CC-BY-3.0", "proprietary (ours)"}


def check_manifest(man, bd, catalog):
    rep = Report("library")
    errs = schemas.validate("manifest", man)
    if errs:
        rep.schema_errors(errs)
        return rep
    by_el = {}
    for e in man["entries"]:
        by_el.setdefault(e["element"], []).append(e)
    missing = [el["id"] for el in bd["elements"] if el["id"] not in by_el]
    rep.hard("M-nothing-missing", not missing, f"breakdown elements without a manifest decision: {missing}")
    dup = [k for k, v in by_el.items() if len(v) > 1]
    rep.hard("M-one-decision", not dup, f"elements with more than one decision: {dup}")
    assets = catalog.get("assets", {})
    for e in man["entries"]:
        el = e["element"]
        rep.hard(f"M-licence.{el}", e["licence"] in OK_LICENCES, f"{el}: licence {e['licence']!r} is not on the allow-list {sorted(OK_LICENCES)}")
        if e["decision"] == "REUSE":
            rep.hard(f"M-reuse.{el}", e.get("catalog_id") in assets or e.get("catalog_id", "").startswith("int:")
                     or (e.get("catalog_id", "").startswith("kit:") and e["catalog_id"][4:] in _kit_ids()),  # world_kits
                     f"{el}: REUSE needs a catalog_id ({e.get('catalog_id')!r})")
        elif e["decision"] == "SOURCE":
            rep.hard(f"M-source.{el}", bool(e.get("provider") and e.get("asset_id") and e.get("url")),
                     f"{el}: SOURCE needs provider, asset_id and url")
            if e["status"] == "ready":
                rep.hard(f"M-hash.{el}", bool(e.get("files")), f"{el}: a ready SOURCE entry needs files with sha256")
            if e["licence"].startswith("CC-BY"):
                rep.hard(f"M-attrib.{el}", any(e.get("asset_id", "") in a for a in man["attributions"]), f"{el}: CC-BY needs an attribution line")
        else:
            rep.hard(f"M-build.{el}", bool(e.get("recipe")), f"{el}: BUILD needs a recipe id")
    return rep


# ============================================================ stage 4: shotplan.json (+ compiled episode.json)
CU_SIZES = {"CU", "ECU"}
WIDE_SIZES = {"EWS", "WS", "TOP"}


def _voiced_spans(story, words):
    """{line id: (s of its first word, e of its last)} from the recorded narration, or None when it does not match."""
    if not words:
        return None
    from factory.voice.text import script_words
    out, i = {}, 0
    if len(words) != sum(len(script_words(ln["text"])) for ln in story["narration"]):
        return None
    for ln in story["narration"]:
        n = len(script_words(ln["text"]))
        if n:
            out[ln["id"]] = (words[i]["s"], words[i + n - 1]["e"])
        i += n
    return out


def check_shotplan(plan, story, bd, man, words=None):
    rep = Report("direct", plan.get("overrides"))
    errs = schemas.validate("shotplan", plan)
    if errs:
        rep.schema_errors(errs)
        return rep
    fmt = story["format"]
    F = FORMAT[fmt]
    shots = plan["shots"]
    lmap = _line_map(story)
    smap = {s["id"]: s for s in bd["scenes"]}
    voc = vocabulary()
    off = plan["audio_offset_frames"]
    D = float(story["duration_s"])

    # ---- continuity of the cut
    rep.hard("INTEGRITY.shot_ids", len({s["id"] for s in shots}) == len(shots), "shot ids must be unique")
    rep.hard("INTEGRITY.contiguous", shots[0]["from"] == 0 and all(a["to"] == b["from"] for a, b in zip(shots, shots[1:]))
             and all(s["to"] > s["from"] for s in shots), "shots must start at frame 0 and be contiguous with no gaps/overlaps")
    end = shots[-1]["to"]
    voiced = _voiced_spans(story, words)  # canon: once the narration is recorded, sync against the measured timing
    if voiced:
        tail = max(e for _, e in voiced.values()) + 0.5
        rep.check("INTEGRITY.duration", end / FPS >= tail + off / FPS - 0.5 and end / FPS <= max(D, tail + off / FPS) + 6.0,
                  f"cut ends at {end / FPS:.2f} s; the voiced narration ends at {tail:.2f} s (+offset)")
    else:
        rep.check("INTEGRITY.duration", abs(end / FPS - D) <= 0.5, f"cut ends at {end / FPS:.2f} s but story.duration_s = {D}")
    rep.hard("INTEGRITY.scene_refs", all(s["scene"] in smap for s in shots), f"unknown scenes: {[s['id'] for s in shots if s['scene'] not in smap]}")
    rep.hard("INTEGRITY.line_refs", all(i in lmap for s in shots for i in s["line_ids"]), "shot line_ids must exist in story")
    # every narration line is on screen while it plays, and the shot carrying it is in a scene that pictures it
    for ln in story["narration"]:
        t0, t1 = voiced.get(ln["id"], (ln["t0"], ln["t1"])) if voiced else (ln["t0"], ln["t1"])
        f0, f1 = off + round(t0 * FPS), off + round(t1 * FPS)
        carriers = [s for s in shots if ln["id"] in s["line_ids"]]
        rep.hard(f"D-line-shown.{ln['id']}", bool(carriers) and all(ln["id"] in smap.get(s["scene"], {}).get("line_ids", []) for s in carriers),
                 f"{ln['id']} must be carried by >= 1 shot whose scene pictures it")
        if carriers:
            rep.check(f"D-line-sync.{ln['id']}", min(s["from"] for s in carriers) <= f0 + 15 and max(s["to"] for s in carriers) >= f1 - 15,
                      f"{ln['id']} plays {f0}-{f1} but its shots cover {min(s['from'] for s in carriers)}-{max(s['to'] for s in carriers)}")

    # ---- vocabulary / render contract
    used_props = set()
    for s in shots:
        cam = s["camera"]
        if (s.get("set") or plan["world"].get("set")) and not ({s.get("set"), plan["world"].get("set")} - {None}) <= _kit_ids():
            rep.hard(f"V-set.{s['id']}", False, f"{s['id']}: unknown world kit {s.get('set') or plan['world'].get('set')}; kits: {sorted(_kit_ids())}")
        kit = shot_kit(s, plan)
        marks = shot_marks(s, plan)
        if cam["rig"] == "orbit":
            rep.hard(f"V-orbit.{s['id']}", cam.get("mark") in marks and all(k in cam for k in ("az", "dist", "height")),
                     f"{s['id']}: orbit needs a known mark {sorted(marks)} and az/dist/height")
        else:
            ok = "cam" in cam and "look" in cam
            frames = {p["frame"] for p in cam.get("cam", []) + cam.get("look", [])}
            space = cam.get("space", "world")
            ok = ok and (frames <= {"yacht"} if space == "yacht" else "yacht" not in frames)
            ok = ok and ("set" not in frames or kit is not None)
            rep.hard(f"V-path.{s['id']}", ok, f"{s['id']}: path needs cam+look points whose frames match space={space}")
            if frames & {"shore", "island"}:
                rep.hard(f"V-island.{s['id']}", s["island"] is not None, f"{s['id']}: shore/island points need an island in the shot")
        h = s.get("hero")
        if h:
            names = [h["stance"]] + [c[1] for c in h.get("stance_changes", [])]
            rep.hard(f"V-stance.{s['id']}", all(n in voc["stances"] for n in names), f"{s['id']}: stances {names} not in {voc['stances']}")
            rep.hard(f"V-mark.{s['id']}", h["mark"] in marks, f"{s['id']}: unknown hero mark {h['mark']} (marks: {sorted(marks)})")
            bad_p = [p["pose"] for p in h.get("poses", []) if p["pose"] not in voc["poses"]]
            rep.hard(f"V-pose.{s['id']}", not bad_p, f"{s['id']}: unknown poses {bad_p}; use {voc['poses']}")
            bad_v = [v["verb"] for v in h.get("verbs", []) if v["verb"] not in voc["verbs"]]
            rep.hard(f"V-verb.{s['id']}", not bad_v, f"{s['id']}: unknown verbs {bad_v}; use {voc['verbs']}")
            rep.check(f"A-acting.{s['id']}", bool(h.get("poses") or h.get("verbs") or h.get("stance_changes")) or s["size"] in WIDE_SIZES
                      or s.get("suspense_hold") or s["camera"]["preset"] in ("rise_overhead", "crane_up", "pull_back"),
                      f"{s['id']}: the hero is on screen but has no motivated action (pose/verb/stance change)")
        if kit is not None:  # world_kits: the set replaces the yacht/island world
            rep.hard(f"V-set-world.{s['id']}", s["yacht"]["state"] == "absent" and s["island"] is None,
                     f"{s['id']}: a shot on world kit {kit['id']} must have yacht.state absent and island null")
            from . import compile as comp
            from factory.worlds import layout
            if cam["rig"] != "orbit" or cam.get("mark") in marks:
                plan_k = layout.layout(kit, s.get("set_seed"), with_grid=False)
                keys = comp.compile_camera(s, None, marks)["keys"]
                probs = sorted({p for k in (keys[0], keys[len(keys) // 2], keys[-1]) for p in layout.camera_check(kit, plan_k, k["cam"])})
                rep.check(f"K-camera-safe.{s['id']}", not probs, f"{s['id']}: " + "; ".join(probs[:3]))
        for p in s.get("props", []):
            used_props.add(p["prop"])
            rep.hard(f"V-prop.{s['id']}", p["prop"] in voc["props"], f"{s['id']}: prop {p['prop']!r} has no builder in cloud/blender/props.py")
    # props on screen must be resolved in the manifest
    man_ok = {e["render_key"][5:] for e in man["entries"] if e.get("render_key", "").startswith("prop:")}
    rep.hard("M-props-resolved", used_props <= man_ok, f"props used but not resolved (render_key prop:<name>) in manifest.json: {sorted(used_props - man_ok)}")
    rep.check("H-1-offset", off <= 9, f"audio_offset_frames {off} puts the first word after 0.3 s (H-1)")
    rep.hard("INTEGRITY.world_island", plan["world"]["island"] is None or plan["world"]["island"] in ("near", "far"), "world.island preset")

    # ---- shot language (PIXAR 3, ENGAGEMENT 4)
    n = len(shots)
    durs = [(s["to"] - s["from"]) / FPS for s in shots]
    asl = sum(durs) / n
    rep.check("P-1", F["asl"][0] <= asl <= F["asl"][1], f"average shot length {asl:.2f} s outside {F['asl']}")
    short = [s["id"] for s, d in zip(shots, durs) if d * FPS < (8 if s.get("insert") else 18)]
    long_ = [s["id"] for s, d in zip(shots, durs) if d > 6 and not s.get("long_take")]
    rep.check("C9", not short and not long_ and 2.0 <= statistics.median(durs) <= 3.5 if fmt == "short" else not short,
              f"shot durations: too short {short}, > 6 s without long_take {long_}, median {statistics.median(durs):.2f} s (2.0-3.5)")
    cu = [s for s in shots if s["size"] in CU_SIZES]
    rep.check("C1", len(cu) <= 0.25 * n, f"CU+ECU share {len(cu)}/{n} > 25%")
    run = best = 0
    for s in shots:
        run = run + 1 if s["size"] in CU_SIZES else 0
        best = max(best, run)
    rep.check("C2", best <= 3, f"{best} consecutive CU-or-tighter shots (max 3)")
    wide = sum(1 for s in shots if s["size"] in WIDE_SIZES)
    rep.check("C-distribution", 0.20 * n <= wide <= 0.45 * n, f"EWS+WS share {wide}/{n} outside ~25-40%")
    presets = [s["camera"]["preset"] for s in shots]
    rep.check("P-6", all(a != b for a, b in zip(presets, presets[1:])), "the same camera preset is used twice in a row")
    top = max(presets.count(p) for p in set(presets))
    rep.check("P-6-share", top <= 0.25 * n, f"one camera preset used for {top}/{n} shots (> 25%)")
    rep.hard("C8", all(s["camera"].get("motivation") for s in shots), "every camera move needs a motivation")
    # C3: each new location is established by an EWS/WS within its first 2 shots
    seen, idx = {}, {}
    for s in shots:
        loc = smap[s["scene"]]["location"]
        k = idx.setdefault(loc, 0)
        idx[loc] = k + 1
        if s["size"] in WIDE_SIZES and loc not in seen:
            seen[loc] = k
    late = {loc: k for loc, k in idx.items() if seen.get(loc, 99) > 1}
    rep.check("C3", not late, f"locations not established by an EWS/WS in their first 2 shots: {sorted(late)}")
    holds = [s for s in shots if s.get("suspense_hold")]
    rep.check("P-4", (1 <= len(holds) <= 2 if fmt == "short" else len(holds) >= 1)
              and all(1.0 <= (s["to"] - s["from"]) / FPS <= 2.0 for s in holds),
              f"need 1-2 suspense_hold shots of 1.0-2.0 s (got {[(s['id'], (s['to'] - s['from']) / FPS) for s in holds]})")
    # S8 / H-3 / H-8: the first shot has the hero and motion
    s0 = shots[0]
    rep.check("S8", bool(s0.get("hero")), "shot 0 must contain the hero (frame-0 cover)")
    # P-3: cuts on word boundaries (needs words[] from stage 5 or the recorded take)
    if words:
        starts = [off + round(w["s"] * FPS) for w in words]
        cuts = [s["from"] for s in shots[1:]]
        hit = sum(1 for c in cuts if any(abs(c - st) <= 2 for st in starts))
        rep.check("P-3", hit >= 0.8 * len(cuts), f"{hit}/{len(cuts)} cuts within +-2 frames of a word start (need >= 80%)")
    if fmt == "docuseries":
        _check_docuseries_plan(plan, story, rep, D)
    return rep


def _check_docuseries_plan(plan, story, rep, D):
    """ARCHITECTURE formats: 150-400 shots per 20 min, and every short_candidate beat staged for both frames."""
    shots = plan["shots"]
    lo, hi = doc.shot_count_range(D)
    rep.check("DOC-shot-count", lo <= len(shots) <= hi, f"{len(shots)} shots for {D:.0f} s; a docuseries cuts {lo}-{hi} (150-400 per 20 min)")
    cands = doc.candidates(story)
    ids = {c["id"] for c in cands}
    bad_ref = sorted({s["short_candidate"] for s in shots if s.get("short_candidate") and s["short_candidate"] not in ids})
    rep.hard("DOC-short-ref", not bad_ref, f"shots tagged with unknown short_candidate ids: {bad_ref}")
    off = plan["audio_offset_frames"]
    for sc in cands:
        f0, f1 = doc.candidate_frames(sc, off)
        cover = [s for s in shots if doc.overlaps(s, f0, f1)]
        untagged = [s["id"] for s in cover if s.get("short_candidate") != sc["id"]]
        stray = [s["id"] for s in shots if s.get("short_candidate") == sc["id"] and not doc.overlaps(s, f0, f1)]
        rep.hard(f"DOC-short-staged.{sc['id']}", bool(cover) and not untagged and not stray,
                 f"{sc['id']} ({f0}-{f1}): every shot overlapping it must be tagged short_candidate={sc['id']} and staged for 9:16 "
                 f"(untagged {untagged}, tagged outside {stray})")
        no_hero = [s["id"] for s in cover if not s.get("hero") and not (s.get("vertical") or {}).get("subject")]
        rep.check(f"DOC-short-subject.{sc['id']}", not no_hero,
                  f"{sc['id']}: dual-frame shots need the hero or an explicit vertical.subject to keep centred: {no_hero}")


def check_episode(ep, overrides=None):
    """Render contract: extended cloud/spec schema + motion in every shot (P-7) + renderer vocabulary."""
    rep = Report("episode", overrides)
    errs = schemas.validate("episode", ep)
    if errs:
        rep.schema_errors(errs)
        return rep
    voc = vocabulary()
    for s in ep["shots"]:
        k = s["camera"]["keys"]
        moved = any(abs(a - b) > 1e-3 for a, b in zip(k[0]["cam"] + k[0]["look"] + [k[0]["fov"]], k[-1]["cam"] + k[-1]["look"] + [k[-1]["fov"]]))
        rep.hard(f"P-7.{s['id']}", moved or s["camera"].get("drift", 0.25) > 0, f"{s['id']}: static camera")
        rep.hard(f"E-keys.{s['id']}", k[0]["f"] <= s["from"] and k[-1]["f"] >= s["to"] - 1, f"{s['id']}: camera keys must span the shot")
        for a in s.get("actors", []):
            rep.hard(f"E-asset.{s['id']}", a["asset"] in ep["assets"]["characters"], f"{s['id']}: actor asset {a['asset']} not in assets.characters")
            for _, st in a.get("perf", {}).get("stance", []):
                rep.hard(f"E-stance.{s['id']}", st in voc["stances"], f"{s['id']}: unknown stance {st}")
        for p in s.get("props", []):
            rep.hard(f"E-prop.{s['id']}", p["prop"] in voc["props"], f"{s['id']}: unknown prop {p['prop']}")
    rep.hard("E-duration", ep["shots"][-1]["to"] == ep["durationFrames"], "durationFrames must equal the last shot's end")
    fmt = ep.get("format", "short")
    rep.hard("E-size", (ep["width"], ep["height"]) == doc.frame_size(fmt), f"a {fmt} renders {doc.frame_size(fmt)}, got {ep['width']}x{ep['height']}")
    if fmt == "docuseries":
        _check_dual_frame(ep, rep)
    return rep


def _check_dual_frame(ep, rep):
    """The 9:16 camera of every short_candidate shot: present, same positions/timing as the 16:9 one, and the
    subject inside the centre band in both frames."""
    shorts = ep.get("shorts") or []
    rep.hard("DOC-shorts", bool(shorts) and all(s["shots"] for s in shorts), "ep.shorts must list every candidate with its shots")
    for s in ep["shots"]:
        if not s.get("short_candidate"):
            continue
        cams = s.get("cameras") or {}
        m, v = cams.get("main"), cams.get("vertical")
        same = bool(m and v) and len(m["keys"]) == len(v["keys"]) and all(
            a["f"] == b["f"] and a["cam"] == b["cam"] for a, b in zip(m["keys"], v["keys"]))
        rep.hard(f"DOC-vertical.{s['id']}", same and m == s["camera"],
                 f"{s['id']}: needs cameras.main (= camera) and a cameras.vertical with the same keyed positions")
        if not same:
            continue
        r = doc.dual_frame_report(s, ep["width"] / ep["height"])
        rep.check(f"DOC-centre-band.{s['id']}", not r["behind"] and r["main"] <= doc.CENTRE_BAND and r["vertical"] <= doc.VERTICAL_TOL,
                  f"{s['id']}: subject must hold the centre band in both frames: |x-0.5| 16:9 {r['main']} (<= {doc.CENTRE_BAND:.3f}), "
                  f"9:16 {r['vertical']} (<= {doc.VERTICAL_TOL}){' - subject behind the camera' if r['behind'] else ''}")



# >>> canon: the film-craft canon in the director's retry loop (factory/canon/checks.py; thresholds.yaml)
def schema_clean(rep):
    return not any(i["rule"] == "SCHEMA" for i in rep.issues)


def _canon_into(rep, results):
    for rid, r in sorted(results.items()):
        if not rid.startswith("CAN-") or r.get("status") not in ("PASS", "FAIL"):
            continue
        rep.hard(rid, r["status"] == "PASS", str(r.get("detail") or "")[:600])
    return rep


def canon_story(rep, story, words=None):
    """Stage 1: the canon rules computable from story.json (CAN-S*, N1, N2b, N2f-plan, N4a-f) block like HARD rules."""
    from factory.canon import checks as cc
    try:
        return _canon_into(rep, cc.story_rules(story, words))
    except Exception as e:  # noqa: BLE001 - a malformed canon field must block, not crash the stage
        rep.hard("CAN-ERROR", False, f"canon checks could not read the story: {type(e).__name__}: {e}")
        return rep


def canon_plan(rep, story, plan, ep=None, words=None, bd=None):
    """Stage 4: shotplan + compiled episode canon rules (C, E, H, P, L1a/e, T1, N3, N4e, S3d/e)."""
    from factory.canon import checks as cc
    try:
        return _canon_into(rep, cc.plan_rules(story, plan, ep, words, bd))
    except Exception as e:  # noqa: BLE001
        rep.hard("CAN-ERROR", False, f"canon checks could not read the shot plan: {type(e).__name__}: {e}")
        return rep
# <<< canon
