"""Executable craft canon: every automatable CAN-* sub-rule of VISUAL_CANON.md + STORY_SOUND_CANON.md.

    run_all(episode_json, plates=None, video=None, stage="plan") -> {RULE_ID: {"status", "detail", ...}}

RULE_ID is both the parent ids (CAN-S1 ... CAN-T1, what `python3 -m factory.canon pass` prints) and every sub-rule
(CAN-S1a, CAN-N2c, ...). A parent is FAIL if any of its sub-rules FAILs, PASS if at least one passed (WARN counts as a
pass with a note), MANUAL when nothing could be computed. Sub-rule statuses: PASS | FAIL | WARN | MANUAL.

Inputs are read from the episode dir next to episode.json: story.json, shotplan.json, sound.json,
audio/narration.words.json ([{w,s,e}], narration-audio seconds), audio/narration.voice.json, audio/narration.gaps.json.
Story times are narration-audio seconds; shot frames are film frames; film time = audio time + offset/fps.
Fields the director must output (schemas in factory/director/schemas) are listed in the film-craft-canon SKILL.md
"Data the director must output". A missing required canon field is a FAIL, not a skip: the pass must not go green
because the plan says nothing. Checks that need pixels (plates) or a reviewer stay MANUAL without them.

The same functions back the director's retry loop: story_rules(ctx) at stage 1 (develop) and plan_rules(ctx) at
stage 4 (direct) (factory/director/runner.py), so the canon is enforced while drafting, not only at the gate.
Thresholds: factory/canon/thresholds.yaml.
"""
import functools
import glob
import importlib.util
import json
import math
import os
import re
import statistics

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PARENTS = ["CAN-S1", "CAN-S2", "CAN-S3", "CAN-C1", "CAN-C2", "CAN-H1", "CAN-E1", "CAN-P1", "CAN-P2",
           "CAN-L1", "CAN-L2", "CAN-L3", "CAN-T1", "CAN-N1", "CAN-N2", "CAN-N3", "CAN-N4"]
CU_SIZES = {"CU", "ECU"}
WIDE_SIZES = {"EWS", "WS", "TOP"}
SIZE_ORDER = ["EWS", "WS", "MWS", "MS", "MCU", "CU", "ECU"]
TURN_POSE = re.compile(r"(look_|turn|glance)")
FUTURE_Q = re.compile(r"\b(will|can|how|before|in time|could|would)\b", re.I)
PAST_Q = re.compile(r"\b(who did|why did|what happened)\b", re.I)
PASSIVE = re.compile(r"\b(is|are|was|were|be|been|being)\s+(\w+ed|\w+en)\b", re.I)
PASSIVE_OK = {"open", "even", "often", "seven", "eleven", "heaven", "garden", "kitten", "ten", "hidden", "golden",
              "broken", "frozen", "chosen", "listen", "sudden", "wooden", "given", "driven"}
ADVERB_AFTER_RIGHT = {"down", "here", "there", "now", "behind", "at", "into", "past", "through", "over", "under", "beside",
                      "after", "before", "up", "away", "on", "in", "back", "across", "toward", "towards", "off"}
PRONOUNS = {"he", "she", "they", "him", "her", "them", "it"}
STOP = set("""a an the and or but so of to in on at by for with from as is are was were be been being it its it's this that
these those you your you're i we he she they him her them his their our my me us do does did not no nor than then there here
what when where who why how all any some just only very too can will would could should into over under out up down off
about again once more most such own same other each few both if because while until also yet still ever never one""".split())


# ------------------------------------------------------------------ config / io
@functools.lru_cache(maxsize=1)
def T():
    with open(os.path.join(HERE, "thresholds.yaml")) as fh:
        return yaml.safe_load(fh)


def _fmt_val(v, fmt):
    return v[fmt] if isinstance(v, dict) else v


def _read(p):
    if p and os.path.isfile(p):
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def _abs(p, base):
    if not p:
        return None
    if os.path.isabs(p):
        return p
    for b in (base, ROOT):
        q = os.path.join(b, p)
        if os.path.exists(q):
            return q
    return os.path.join(ROOT, p)


def script_words(text):
    try:
        from factory.voice.text import script_words as sw
        return sw(text)
    except Exception:  # pragma: no cover - voice package always present in this repo
        return [w for w in re.sub(r"\[[^\]]*\]", " ", text).split() if re.search(r"\w", w)]


def norm(w):
    return re.sub(r"[^a-z0-9']", "", w.lower())


def content_words(text):
    out = []
    for w in re.findall(r"[a-z0-9']+", text.lower()):
        if w in STOP or len(w) < 3:
            continue
        out.append(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


def merge_story_links(story, plan):
    """shotplan.story_links (stage 4) re-points story.json's planned shot references at the shots actually cut."""
    links = (plan or {}).get("story_links") or {}
    if not story or not links:
        return story
    st = json.loads(json.dumps(story))
    for ln in st.get("narration", []):
        if ln["id"] in (links.get("reveal_order") or {}):
            ln["reveal_order"] = dict(links["reveal_order"][ln["id"]])
        if ln["id"] in (links.get("evidence") or {}):
            ln["evidence"] = dict(links["evidence"][ln["id"]])
    for th in st.get("threats", []):
        th.update((links.get("threats") or {}).get(th.get("id"), {}))
    return st


class Ctx:
    """Everything the checks read, in one place. Built from files (from_episode) or from in-memory docs
    (director stages: story only, or story + shotplan + compiled episode)."""

    def __init__(self, story=None, plan=None, ep=None, sound=None, words=None, voice=None, gaps_report=None,
                 plates=None, video=None, ep_dir=None, stage="plan", lighting=None, breakdown=None):
        story = merge_story_links(story, plan)
        self.story, self.plan, self.ep, self.sound = story or {}, plan or {}, ep or {}, sound
        self.breakdown = breakdown or {}
        self.words, self.voice, self.gaps_report = words, voice, gaps_report
        self.plates, self.video, self.dir, self.stage = plates, video, ep_dir, stage
        self.lighting = lighting
        self.fps = (ep or {}).get("fps", T()["fps"])
        self.fmt = (story or {}).get("format") or (ep or {}).get("format") or "short"
        off = (plan or {}).get("audio_offset_frames")
        if off is None:
            off = ((ep or {}).get("audio") or {}).get("offsetFrames", 0)
        self.offset = int(off or 0)
        self.off_s = self.offset / self.fps
        shots = (plan or {}).get("shots") or (ep or {}).get("shots") or []
        self.shots = sorted(shots, key=lambda s: s["from"])
        self.smap = {s["id"]: s for s in self.shots}
        self.ep_shots = {s["id"]: s for s in (ep or {}).get("shots", [])}
        if (ep or {}).get("durationFrames"):
            self.D = ep["durationFrames"] / self.fps
        elif self.shots:
            self.D = self.shots[-1]["to"] / self.fps
        else:
            self.D = float((story or {}).get("duration_s") or 0)
        self.lines = (story or {}).get("narration") or []
        self.lmap = {ln["id"]: ln for ln in self.lines}
        self.beats = (story or {}).get("beats") or []
        self.bmap = {b["id"]: b for b in self.beats}
        self.kt = (story or {}).get("knowledge_timeline") or []
        self.threats = (story or {}).get("threats") or []
        self.gaps = (story or {}).get("narration_gaps") or []
        self._line_words = None

    # ---- words per line (measured if words.json, else planned: proportional inside t0..t1)
    def line_words(self):
        if self._line_words is not None:
            return self._line_words
        out, i = {}, 0
        measured = bool(self.words) and len(self.words) == sum(len(script_words(ln["text"])) for ln in self.lines)
        for ln in self.lines:
            sw = script_words(ln["text"])
            if measured:
                seg = [{"w": w["w"], "s": w["s"], "e": w["e"]} for w in self.words[i:i + len(sw)]]
                i += len(sw)
            else:
                wt = [max(1, len(norm(w))) + 1.5 for w in sw] or [1]
                span, tot, c = ln["t1"] - ln["t0"], sum(wt), ln["t0"]
                seg = []
                for w, x in zip(sw, wt):
                    d = span * x / tot
                    seg.append({"w": w, "s": round(c, 3), "e": round(c + 0.88 * d, 3)})
                    c += d
            out[ln["id"]] = seg
        self.measured = measured
        self._line_words = out
        return out

    def all_words(self):
        lw = self.line_words()
        return [w for ln in self.lines for w in lw.get(ln["id"], [])]

    def film(self, t_audio):
        return t_audio + self.off_s

    def sequences(self):
        seqs = (self.plan or {}).get("sequences")
        if seqs:
            return seqs
        return [{"id": "ALL", "shots": [s["id"] for s in self.shots], "_implicit": True}]

    def seq_of(self, shot_id):
        for q in self.sequences():
            if shot_id in q.get("shots", []):
                return q
        return None

    def kt_at(self, t):
        hit = [k for k in self.kt if k.get("t0", -1e9) <= t < k.get("t1", 1e9)]
        return hit[-1] if hit else None

    def hero(self, sid):
        s = self.smap.get(sid) or {}
        return s.get("hero")


# ------------------------------------------------------------------ results
class Results:
    def __init__(self):
        self.r = {}

    def add(self, rid, status, detail="", **kw):
        self.r[rid] = {"status": status, "detail": detail, **kw}

    def ok(self, rid, cond, fail_detail, pass_detail="ok", warn=False):
        self.add(rid, "PASS" if cond else ("WARN" if warn else "FAIL"), pass_detail if cond else fail_detail)

    def manual(self, rid, detail):
        self.add(rid, "MANUAL", detail)

    def missing(self, rid, what):
        self.add(rid, "FAIL", f"missing {what} (the director must output it; see film-craft-canon SKILL.md)")


def aggregate(res):
    out = dict(res.r)
    for p in PARENTS:
        subs = {k: v for k, v in res.r.items() if k.startswith(p) and k != p and re.match(re.escape(p) + r"[a-z]", k)}
        if not subs:
            out[p] = {"status": "MANUAL", "detail": "no automated sub-rule could run", "sub": {}}
            continue
        sts = [v["status"] for v in subs.values()]
        st = "FAIL" if "FAIL" in sts else ("PASS" if ("PASS" in sts or "WARN" in sts) else "MANUAL")
        bad = [f"{k}: {v['detail']}" for k, v in subs.items() if v["status"] in ("FAIL", "WARN")]
        n = {s: sts.count(s) for s in ("PASS", "FAIL", "WARN", "MANUAL") if sts.count(s)}
        out[p] = {"status": st, "detail": ("; ".join(bad)[:900] if bad else f"{n}"), "sub": {k: v["status"] for k, v in subs.items()}}
    return out


# ================================================================== STORY (CAN-S*)
def check_S(c, R):
    st, fmt = T()["story"], c.fmt
    s = c.story
    tids = {t.get("id") for t in c.threats}
    # S1a / S1b
    if not c.threats:
        R.missing("CAN-S1a", "story.threats[] (every danger shown to the audience before the character notices it)")
        R.missing("CAN-S1b", "story.threats[] + knowledge_timeline[]")
    else:
        lead_min = _fmt_val(st["threat_lead_s"], fmt)
        bad_a, bad_b = [], []
        for th in c.threats:
            need = ("id", "planted_shot", "planted_t", "noticed_at", "outcome")
            miss = [k for k in need if th.get(k) is None]
            if miss:
                bad_a.append(f"{th.get('id')}: missing {miss}")
                continue
            lead = th["noticed_at"] - th["planted_t"]
            if lead < lead_min:
                bad_a.append(f"{th['id']}: lead {lead:.2f} s < {lead_min} s")
            if c.shots:
                ps = c.smap.get(th["planted_shot"])
                if not ps:
                    bad_a.append(f"{th['id']}: planted_shot {th['planted_shot']} is not a shot")
                else:
                    f0 = c.offset + th["planted_t"] * c.fps
                    f1 = c.offset + th["noticed_at"] * c.fps
                    vis = max(0.0, min(ps["to"], f1) - max(ps["from"], f0)) / c.fps
                    if vis + 1e-6 < st["threat_visible_s"]:
                        bad_a.append(f"{th['id']}: on screen {vis:.2f} s in the audience-only window (< {st['threat_visible_s']} s)")
                    if ps.get("hero") and th["id"] not in (ps.get("gaze_away_from") or []):
                        bad_a.append(f"{th['id']}: planted shot {ps['id']} has the hero but no gaze_away_from [{th['id']}]")
            for k in c.kt:
                if k.get("t1", 0) > th["planted_t"] + 1e-6 and k.get("t0", 0) < th["noticed_at"] - 1e-6 \
                        and k.get("t0", 0) >= th["planted_t"] - 1e-6:
                    if th["id"] not in k.get("audience_knows", []) or th["id"] in k.get("character_knows", []):
                        bad_b.append(f"{k.get('beat')}@{k.get('t0')}: {th['id']} must be in audience_knows and not character_knows")
        R.ok("CAN-S1a", not bad_a, "; ".join(bad_a), f"{len(c.threats)} threat(s) planted ahead of notice")
        if not c.kt:
            R.missing("CAN-S1b", "story.knowledge_timeline[]")
        else:
            R.ok("CAN-S1b", not bad_b, "; ".join(bad_b[:6]))
    # S1c relief
    if c.threats:
        bad = []
        for th in c.threats:
            if th.get("outcome") not in ("escaped", "averted", "survived_with_cost"):
                bad.append(f"{th.get('id')}: outcome {th.get('outcome')!r}")
            peak = th.get("peak_t", th.get("noticed_at", 0))
            rel = [k for k in c.kt if k.get("mode") == "relief" and k.get("t0", -1) >= peak - 1e-6
                   and k.get("t1", 0) - k.get("t0", 0) >= st["relief_min_s"] - 1e-6]
            if not rel:
                bad.append(f"{th.get('id')}: no relief record >= {st['relief_min_s']} s after its peak ({peak})")
        R.ok("CAN-S1c", not bad, "; ".join(bad))
    # S1d surprise budget
    if c.kt:
        sur = [k for k in c.kt if k.get("mode") == "surprise"]
        allowed = max(1, math.floor(c.D / st["surprise_per_s"])) if c.D else 1
        climax = [k for k in sur if c.bmap.get(k.get("beat"), {}).get("name") in ("PAYOFF", "CLIMAX")]
        R.ok("CAN-S1d", len(sur) <= allowed and not climax,
             f"{len(sur)} surprise records (allowed {allowed}); on the climax: {[k.get('beat') for k in climax]}")
    # S2a per-record fields + every beat covered
    if not c.kt:
        for r in ("CAN-S2a", "CAN-S2b", "CAN-S2c", "CAN-S2d", "CAN-S2e", "CAN-S2f"):
            R.missing(r, "story.knowledge_timeline[] (who knows / who can act / audience question per beat)")
    else:
        need = ("beat", "mode", "audience_knows", "character_knows", "who_can_act", "audience_question")
        bad = [f"{k.get('beat')}: missing {[f for f in need if k.get(f) is None or k.get(f) == '']}" for k in c.kt
               if any(k.get(f) is None or k.get(f) == "" for f in need) or "threat_planted_shot" not in k]
        unc = [b["id"] for b in c.beats if not any(k.get("beat") == b["id"] for k in c.kt)]
        badw = [k.get("beat") for k in c.kt if not re.match(r"^(character|nobody|other:.+)$", str(k.get("who_can_act", "")))]
        R.ok("CAN-S2a", not bad and not unc and not badw,
             f"records missing fields {bad[:4]}; beats without a record {unc}; bad who_can_act {badw}")
        # S2b mode vs sets
        bad = []
        for k in c.kt:
            A = set(k.get("audience_knows", [])) & tids
            C = set(k.get("character_knows", [])) & tids
            m = k.get("mode")
            if m == "dramatic_irony" and not (A > C):
                bad.append(f"{k.get('beat')}@{k.get('t0')}: dramatic_irony needs audience_knows > character_knows on threats")
            if m == "shared" and A != C:
                bad.append(f"{k.get('beat')}@{k.get('t0')}: shared needs equal threat knowledge (A-C = {sorted(A - C)})")
            if m == "suppression" and not k.get("withheld_from_audience"):
                bad.append(f"{k.get('beat')}: suppression needs withheld_from_audience[]")
            if m not in ("shared", "dramatic_irony", "suppression", "mystery", "surprise", "relief"):
                bad.append(f"{k.get('beat')}: unknown mode {m!r}")
        R.ok("CAN-S2b", not bad, "; ".join(bad[:5]))
        # S2c question pivots on knowledge/agency change
        bad = []
        for a, b in zip(c.kt, c.kt[1:]):
            gained = (set(b.get("character_knows", [])) - set(a.get("character_knows", []))) & tids
            agency = a.get("who_can_act") != b.get("who_can_act")
            if gained or agency:
                q = b.get("audience_question", "")
                if q.strip().lower() == a.get("audience_question", "").strip().lower():
                    bad.append(f"{b.get('beat')}@{b.get('t0')}: knowledge/agency changed but the audience question did not")
                elif not FUTURE_Q.search(q) or PAST_Q.search(q):
                    bad.append(f"{b.get('beat')}: new question {q!r} is not about what happens next")
        R.ok("CAN-S2c", not bad, "; ".join(bad[:5]))
        # S2d keep the mind occupied
        gap_max = _fmt_val(st["question_change_max_gap_s"], c.fmt)
        times = [c.kt[0].get("t0", 0.0)]
        for a, b in zip(c.kt, c.kt[1:]):
            if a.get("audience_question") != b.get("audience_question") or a.get("mode") != b.get("mode"):
                times.append(b.get("t0", 0.0))
        end = max([k.get("t1", 0) for k in c.kt] + [float(s.get("duration_s") or 0)])
        gaps = [y - x for x, y in zip(times, times[1:] + [end])]
        R.ok("CAN-S2d", max(gaps) <= gap_max + 1e-6, f"audience question/mode unchanged for {max(gaps):.1f} s (> {gap_max} s)",
             f"longest unchanged stretch {max(gaps):.1f} s")
        # S2e disclosure in pieces
        bad, prev = [], set()
        for k in c.kt:
            new = set(k.get("audience_knows", [])) - prev
            if len(new) > st["max_new_audience_items"]:
                bad.append(f"{k.get('beat')}@{k.get('t0')}: {len(new)} new items {sorted(new)}")
            prev |= set(k.get("audience_knows", []))
        R.ok("CAN-S2e", not bad, "; ".join(bad[:4]))
        modes = [k.get("mode") for k in c.kt]
        if c.fmt == "short":
            R.ok("CAN-S2f", "dramatic_irony" in modes and len(set(modes)) >= 2, f"modes {sorted(set(modes))}: need >= 1 dramatic_irony and >= 2 modes")
        else:
            R.ok("CAN-S2f", len(set(modes)) >= 2, f"modes {sorted(set(modes))}: need >= 2 modes")
    # S3 ticking clock
    tc = s.get("ticking_clock")
    if not tc:
        if s.get("time_pressure"):
            R.missing("CAN-S3a", "story.ticking_clock (time_pressure is true)")
        else:
            R.add("CAN-S3a", "PASS", "no time pressure declared: no clock required")
    else:
        rd = tc.get("readings") or []
        D = float(s.get("duration_s") or c.D or 1)
        first_ok = bool(rd) and rd[0]["t"] <= st["clock_first_reading_frac"] * D
        kind_ok = tc.get("kind") in ("diegetic_prop", "environment", "badge") and bool((tc.get("deadline") or "").strip())
        R.ok("CAN-S3a", first_ok and kind_ok,
             f"clock needs kind in diegetic_prop|environment|badge (got {tc.get('kind')!r}), a deadline, and a first reading <= "
             f"{st['clock_first_reading_frac']:.0%} of runtime (first {rd[0]['t'] if rd else None})")
        mono = all(a["severity"] < b["severity"] for a, b in zip(rd, rd[1:]))
        mx = max([b["t"] - a["t"] for a, b in zip(rd, rd[1:])] + [0])
        lim = _fmt_val(st["clock_reshow_max_s"], c.fmt)
        R.ok("CAN-S3b", len(rd) >= 2 and mono and mx <= lim, f"readings must worsen strictly and re-show every <= {lim} s "
             f"(monotonic {mono}, largest interval {mx:.1f} s)")
    # S3c attempts cost visible time
    known = min([th.get("planted_t", 1e9) for th in c.threats] or [1e9])
    att = [a for a in s.get("attempts", []) if a.get("t0") is None or a.get("t0", 0) >= known]
    if not s.get("attempts"):
        R.add("CAN-S3c", "PASS", "no attempts declared")
    elif not tc:
        R.add("CAN-S3c", "PASS", "no ticking clock: attempts cost no clock time")
    else:
        bad = []
        for a in att:
            if a.get("t0") is None or a.get("t1") is None or not a.get("clock_before") or not a.get("clock_after"):
                bad.append(f"{a.get('action', '?')[:30]}: needs t0/t1 and clock_before/clock_after")
            elif a["clock_before"] == a["clock_after"] or a["t1"] - a["t0"] < st["attempt_min_s"]:
                bad.append(f"{a['action'][:30]}: clock unchanged or < {st['attempt_min_s']} s on screen")
        R.ok("CAN-S3c", not bad, "; ".join(bad[:4]))


def check_S_plan(c, R):
    """S3d/S3e need the cut (impact shots)."""
    st = T()["story"]
    hits = []
    for q in c.sequences():
        imp = (q.get("action_order") or {}).get("impact")
        if imp and imp in c.smap:
            ih = c.smap[imp].get("impact_handheld") or {}
            hits.append((ih.get("impact_frame", c.smap[imp]["from"]), imp))
    for s in c.shots:
        ih = s.get("impact_handheld")
        if ih and not any(h[1] == s["id"] for h in hits):
            hits.append((ih.get("impact_frame", s["from"]), s["id"]))
    hits.sort()
    if not hits:
        R.manual("CAN-S3d", "no impact shots declared")
        R.manual("CAN-S3e", "no impact shots declared")
        return
    sp = [(b[0] - a[0]) / c.fps for a, b in zip(hits, hits[1:])]
    R.ok("CAN-S3d", all(x >= st["hits_min_spacing_s"] for x in sp), f"impacts {hits} spaced {sp} s (< {st['hits_min_spacing_s']} s)")
    known = min([th.get("planted_t", 1e9) for th in c.threats] or [None] if c.threats else [None])
    if known is None or known >= 1e9:
        R.missing("CAN-S3e", "threats[].planted_t (anticipation start)")
        return
    bad = []
    for f, sid in hits:
        s = c.smap[sid]
        dur = (s["to"] - s["from"]) / c.fps
        ant = f / c.fps - c.film(known)
        if ant < st["anticipation_ratio"] * dur:
            bad.append(f"{sid}: anticipation {ant:.1f} s < {st['anticipation_ratio']}x impact {dur:.1f} s")
    R.ok("CAN-S3e", not bad, "; ".join(bad))


# ================================================================== NARRATION (CAN-N*)
def _beat_of_t(c, t):
    for b in c.beats:
        if b["t0"] - 1e-6 <= t < b["t1"]:
            return b
    return c.beats[-1] if c.beats else None


def _gap_boundary(c, g):
    """(prev_word, next_word) around a gap declared after_line, in audio seconds (measured or planned)."""
    lw = c.line_words()
    ids = [ln["id"] for ln in c.lines]
    if g.get("after_line") not in lw or not lw[g["after_line"]]:
        return None, None
    i = ids.index(g["after_line"])
    prev = lw[g["after_line"]][-1]
    nxt = next((lw[j][0] for j in ids[i + 1:] if lw.get(j)), None)
    return prev, nxt


def check_N_story(c, R):
    nt = T()["narration"]
    s = c.story
    # N1 three columns
    rows = s.get("script_columns") or []
    if not rows:
        for r in ("CAN-N1a", "CAN-N1b", "CAN-N1d"):
            R.missing(r, "story.script_columns[] (PICTURE | NARRATION | SOUND rows)")
    else:
        bad = []
        for r in rows:
            b = c.bmap.get(r.get("beat"))
            if not (r.get("picture") or "").strip() or not (r.get("sound") or "").strip():
                bad.append(f"{r.get('row_id')}: empty picture/sound")
            if not (r.get("t0", 0) < r.get("t1", 0)):
                bad.append(f"{r.get('row_id')}: t0 >= t1")
            if b and not (b["t0"] - 0.05 <= r["t0"] and r["t1"] <= b["t1"] + 0.05):
                bad.append(f"{r.get('row_id')}: {r['t0']}-{r['t1']} outside beat {b['id']} {b['t0']}-{b['t1']}")
            if not b:
                bad.append(f"{r.get('row_id')}: unknown beat {r.get('beat')}")
        R.ok("CAN-N1a", not bad, "; ".join(bad[:6]), f"{len(rows)} rows")
        groups = {}
        key = "chapter" if c.fmt == "docuseries" else "id"
        for b in c.beats:
            groups.setdefault(b.get(key) or b["id"], []).append(b["id"])
        bad = []
        for g, bids in groups.items():
            ok = any(r.get("beat") in bids and not (r.get("narration") or "").strip()
                     and r["t1"] - r["t0"] >= nt["sound_only_row_min_s"] - 1e-6 for r in rows)
            if not ok:
                bad.append(g)
        R.ok("CAN-N1b", not bad, f"sequences without a sound-only row >= {nt['sound_only_row_min_s']} s: {bad}")
        amb = [r.get("row_id") for r in rows if "AMB:" not in (r.get("sound") or "")]
        R.ok("CAN-N1c", not amb, f"rows whose sound column names no AMB: bed: {amb[:8]}") if c.sound is None else None
        seen = {}
        for r in rows:
            for i in r.get("line_ids") or []:
                seen.setdefault(i, []).append(r)
        bad = [i for i in c.lmap if len(seen.get(i, [])) != 1]
        bad += [f"{i} outside {r['row_id']}" for i, rs in seen.items() for r in rs if i in c.lmap
                and not (r["t0"] - 0.05 <= c.lmap[i]["t0"] and c.lmap[i]["t1"] <= r["t1"] + 0.05)]
        R.ok("CAN-N1d", not bad, f"lines not in exactly one row / outside their row: {bad[:8]}")
    # N2b reserved gaps
    gm = nt["gap_min_s"]
    if not c.gaps:
        R.missing("CAN-N2b", "story.narration_gaps[] (breath / key_sfx / reaction gaps)")
    else:
        bad = []
        for g in c.gaps:
            p = g.get("purpose")
            if p not in gm:
                bad.append(f"{g.get('id')}: purpose {p!r}")
                continue
            if g.get("len_s", 0) + 1e-6 < gm[p]:
                bad.append(f"{g['id']}: {p} gap {g.get('len_s')} s < {gm[p]} s")
            if g.get("after_line") not in c.lmap:
                bad.append(f"{g['id']}: after_line {g.get('after_line')} unknown")
            if not g.get("filled_by"):
                bad.append(f"{g['id']}: filled_by missing")
            if c.sound and p == "key_sfx":
                cue = next((q for q in c.sound.get("cues", []) if q.get("id") == g.get("filled_by") or q.get("gap") == g["id"]), None)
                if cue and cue.get("dur") and g["len_s"] + 1e-6 < max(gm["key_sfx"], cue["dur"] + nt["key_sfx_margin_s"]):
                    bad.append(f"{g['id']}: key_sfx gap {g['len_s']} s < cue {cue['dur']} s + {nt['key_sfx_margin_s']}")
        # every beat with narration needs a gap >= 0.6 s; every suspense beat a reaction/key_sfx gap
        by_beat = {}
        for g in c.gaps:
            ln = c.lmap.get(g.get("after_line"))
            if ln:
                by_beat.setdefault(ln["beat"], []).append(g)
        voiced_beats = {ln["beat"] for ln in c.lines}
        # the last line of a beat may hand its gap to the next beat's opening: count gaps that start inside the beat
        for b in c.beats:
            if b["id"] not in voiced_beats:
                continue
            gs = by_beat.get(b["id"], []) + [g for g in c.gaps if b["t0"] <= g.get("start_s", -1) < b["t1"]]
            if not any(g.get("len_s", 0) >= nt["beat_gap_min_s"] - 1e-6 for g in gs):
                bad.append(f"beat {b['id']}: no gap >= {nt['beat_gap_min_s']} s")
            modes = {k.get("mode") for k in c.kt if k.get("beat") == b["id"]}
            if modes & {"dramatic_irony", "shared"} and not any(g.get("purpose") in ("reaction", "key_sfx") for g in gs):
                bad.append(f"suspense beat {b['id']}: no reaction/key_sfx gap")
        R.ok("CAN-N2b", not bad, "; ".join(bad[:8]), f"{len(c.gaps)} gaps")
    # N2f planned coverage (story level) -- the measured share is in check_N_audio
    D = float(s.get("duration_s") or c.D or 0)
    if D and c.lines:
        cov = sum(ln["t1"] - ln["t0"] for ln in c.lines) / D
        lim = _fmt_val(nt["planned_coverage_max"], c.fmt)
        R.ok("CAN-N2f-plan", cov <= lim + 1e-6, f"planned line spans cover {cov:.0%} of {D:.0f} s (> {lim:.0%}): narration leads the picture",
             f"planned line spans {cov:.0%} of runtime")
    # N4a narrator
    nr = s.get("narrator")
    if not nr:
        R.missing("CAN-N4a", "story.narrator {person, persona, authority, knowledge_scope, voice_id}")
    else:
        miss = [k for k in ("person", "persona", "authority", "knowledge_scope") if not nr.get(k)]
        okp = nr.get("person") in ("first", "second", "third_omniscient") and nr.get("knowledge_scope") in ("character", "omniscient")
        R.ok("CAN-N4a", not miss and okp, f"narrator missing {miss} or bad person/knowledge_scope ({nr.get('person')}, {nr.get('knowledge_scope')})")
        # N4b knowledge scope
        if nr.get("knowledge_scope") == "character":
            kw = {th["id"]: [k.lower() for k in th.get("keywords", [])] for th in c.threats if th.get("keywords")}
            if not kw:
                R.manual("CAN-N4b", "narrator scope is character: threats[].keywords needed to check lines against character_knows")
            else:
                bad = []
                for ln in c.lines:
                    k = c.kt_at(ln["t0"])
                    txt = " ".join(norm(w) for w in script_words(ln["text"]))
                    for tid, kws in kw.items():
                        if any(re.search(rf"\b{re.escape(x)}\b", txt) for x in kws) and k and tid not in k.get("character_knows", []):
                            bad.append(f"{ln['id']} names {tid} before the character knows it")
                R.ok("CAN-N4b", not bad, "; ".join(bad[:5]))
        else:
            R.add("CAN-N4b", "PASS", "omniscient narrator (timing governed by N3b)")
    # N4c purpose / adds / redundancy
    purposes = {"setup", "context", "authenticity", "momentum", "inner_state", "clarify", "bridge", "resolution", "step"}
    bad = [ln["id"] for ln in c.lines if ln.get("purpose") not in purposes or not (ln.get("adds") or "").strip()]
    red = _redundant_lines(c)
    det = []
    if bad:
        det.append(f"lines without a Rabiger purpose + adds (cut them or say what they add): {bad[:10]}")
    if red:
        det.append("lines that describe the picture/sound: " + "; ".join(f"{i} ({o:.0%} overlap)" for i, o in red[:6]))
    R.ok("CAN-N4c", not bad and not red, " | ".join(det))
    judge = llm_judge_redundancy(c)
    if judge is not None:
        R.ok("CAN-N4c-judge", not judge["flagged"], f"LLM judge: duplicates picture/sound: {judge['flagged']}",
             f"LLM judge ({judge['model']}): no duplicate lines")
    # N4d restating a key sound
    bad = []
    ids = [ln["id"] for ln in c.lines]
    for g in c.gaps:
        if g.get("purpose") != "key_sfx" or g.get("after_line") not in ids:
            continue
        i = ids.index(g["after_line"])
        if i + 1 < len(ids):
            nxt = c.lmap[ids[i + 1]]
            sw = [norm(w) for w in script_words(nxt["text"])]
            first = " ".join(sw[:3])
            restate = len(sw) <= 3 or re.match(r"^(nothing|silence|no catch|dead|it fails|click)", first)
            if restate:
                bad.append(f"{nxt['id']} {nxt['text'][:40]!r} restates the key sound of gap {g['id']}")
    R.ok("CAN-N4d", not bad, "; ".join(bad))
    # N4f style lint
    bad = []
    for ln in c.lines:
        for snt in re.split(r"(?<=[.!?])\s+", re.sub(r"\[[^\]]*\]", "", ln["text"])):
            n = len(script_words(snt))
            if n > nt["sentence_words_max"]:
                bad.append(f"{ln['id']}: {n}-word sentence")
            m = PASSIVE.search(snt)
            if m and m.group(2).lower() not in PASSIVE_OK:
                bad.append(f"{ln['id']}: passive '{m.group(0)}'")
    R.ok("CAN-N4f", not bad, "; ".join(bad[:8]))


def _redundant_lines(c):
    """Content-word overlap between a line and what the picture/sound already carries: the breakdown scene's
    `picture` (what is evident on screen while the line plays), the carrying shots' `establishes`, and the line's
    script row picture/sound text. Shot titles are not used (they quote the narration). Lines with purpose
    step/context/authenticity are only flagged when the overlap is near-total (instructions name what they show)."""
    lim = T()["narration"]["redundancy_overlap_max"]
    rows = c.story.get("script_columns") or []
    out = []
    for ln in c.lines:
        lw = set(content_words(ln["text"]))
        if len(lw) < 3:
            continue
        vis = []
        for s in c.shots:
            if ln["id"] in (s.get("line_ids") or []):
                vis += list(s.get("establishes") or [])
        for sc in (c.breakdown or {}).get("scenes", []):
            if ln["id"] in (sc.get("line_ids") or []) and len(sc.get("line_ids") or []) <= 2:
                vis.append(sc.get("picture", ""))
        for r in rows:
            if ln["id"] in (r.get("line_ids") or []):
                vis += [r.get("picture", ""), re.sub(r"\b(AMB|FX|MUSIC):", " ", r.get("sound", ""))]
        vw = set(content_words(" ".join(vis)))
        if not vw:
            continue
        ov = len(lw & vw) / len(lw)
        thr = 0.8 if ln.get("purpose") in ("step", "context", "authenticity") else lim
        if ov > thr:
            out.append((ln["id"], ov))
    return out


def llm_judge_redundancy(c):
    """Optional LLM judge for CAN-N4c (Rabiger p.450 'complement, don't duplicate'), behind ANTHROPIC_API_KEY and
    CANON_LLM_JUDGE=1 (never in tests / offline). Returns {"model", "flagged": [line ids]} or None."""
    if os.environ.get("CANON_LLM_JUDGE") != "1" or not os.environ.get("ANTHROPIC_API_KEY") or not c.lines:
        return None
    try:
        import anthropic
        model = os.environ.get("CANON_JUDGE_MODEL", "claude-sonnet-5-5")
        pics = {ln["id"]: [sc.get("picture", "") for sc in (c.breakdown or {}).get("scenes", []) if ln["id"] in (sc.get("line_ids") or [])]
                for ln in c.lines}
        rows = {i: r.get("picture", "") + " | " + r.get("sound", "") for r in c.story.get("script_columns") or [] for i in r.get("line_ids") or []}
        payload = [{"id": ln["id"], "line": ln["text"], "picture": pics.get(ln["id"]), "row": rows.get(ln["id"])} for ln in c.lines]
        msg = anthropic.Anthropic().messages.create(
            model=model, max_tokens=800,
            system="You are a documentary editor applying Rabiger: narration must add to the image, never describe what is "
                   "already evident in the picture or say what a featured sound already said. Reply with JSON only: "
                   "{\"flagged\": [line ids that only describe the picture/sound]}.",
            messages=[{"role": "user", "content": json.dumps(payload)}])
        txt = "".join(b.text for b in msg.content if b.type == "text")
        d = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
        return {"model": model, "flagged": [i for i in d.get("flagged", []) if i in c.lmap]}
    except Exception as e:  # noqa: BLE001 - the judge is advisory; a failure is reported, never a pass
        return {"model": "error", "flagged": [], "error": str(e)[:200]}


def _reaction_windows(c):
    """Film-second windows where no word may play (CAN-N3e / N4h)."""
    out = []
    plan_seqs = c.sequences()
    for q in plan_seqs:
        rc = q.get("reserved_close_up") or {}
        s = c.smap.get(rc.get("shot"))
        if s:
            out.append((s["from"] / c.fps, s["to"] / c.fps, f"reserved_close_up {s['id']}"))
    for s in c.shots:
        for w in s.get("reaction_windows") or []:
            out.append((w["from"] / c.fps, w["to"] / c.fps, f"{w.get('kind')} {s['id']}"))
        for t in s.get("turn_then_change") or []:
            tr, ch = t.get("turn") or {}, t.get("change") or {}
            if tr.get("to") is not None and ch.get("to") is not None and t.get("mode") != "pre_turn":
                out.append((tr["to"] / c.fps, ch["to"] / c.fps, f"turn_then_change settle {s['id']}"))
    for g in c.gaps:
        if g.get("purpose") == "reaction":
            prev, nxt = _gap_boundary(c, g)
            pad = T()["narration"]["reaction_pad_s"]
            if prev and nxt and nxt["s"] - prev["e"] > 2 * pad + 0.05:
                out.append((c.film(prev["e"]) + pad + 0.01, c.film(nxt["s"]) - pad - 0.01, f"reaction gap {g['id']}"))
    for sil in (c.sound or {}).get("silences", []):
        out.append((sil["from"] / c.fps, sil["to"] / c.fps, f"silence: {sil.get('reason', '')[:30]}"))
    return out


def check_N_plan(c, R):
    """N3a/b/c/d/e, N4e, N4h: need the cut (and words when voiced)."""
    nt = T()["narration"]
    lw = c.line_words()
    src = "measured words" if getattr(c, "measured", False) else "planned line timing"
    # N3a operative word on the cut
    cw = [s for s in c.shots if s.get("cut_word")]
    if not cw:
        R.manual("CAN-N3a", "no shot declares cut_word {line, word_idx}")
    else:
        bad = []
        lo, hi = nt["cut_word_window_s"]
        for s in cw:
            ln = s["cut_word"].get("line")
            i = s["cut_word"].get("word_idx", 0)
            ws = lw.get(ln) or []
            if not (0 <= i < len(ws)):
                bad.append(f"{s['id']}: cut_word {ln}[{i}] does not exist")
                continue
            d = s["from"] / c.fps - c.film(ws[i]["s"])
            if not (lo - 1e-6 <= d <= hi + 1e-6):
                bad.append(f"{s['id']}: cut {d:+.2f} s from '{ws[i]['w']}' (window {lo}..{hi})")
        R.ok("CAN-N3a", not bad, "; ".join(bad[:6]) + f" [{src}]", f"{len(cw)} operative-word cuts in window [{src}]")
    # N3b reveal order
    miss = [ln["id"] for ln in c.lines if not ln.get("reveal_order")]
    if miss:
        R.missing("CAN-N3b", f"narration[].reveal_order on {miss[:12]}")
    else:
        bad = []
        for ln in c.lines:
            ro = ln["reveal_order"]
            ws = lw.get(ln["id"]) or []
            i = ro.get("key_word_idx", 0)
            if not (0 <= i < len(ws)):
                bad.append(f"{ln['id']}: key_word_idx {i} out of range")
                continue
            if c.shots and ro.get("reveal_shot") not in c.smap:
                bad.append(f"{ln['id']}: reveal_shot {ro.get('reveal_shot')} unknown")
                continue
            if c.shots:
                rs = c.smap[ro["reveal_shot"]]
                if not (rs["from"] <= ro.get("reveal_frame", -1) < rs["to"]):
                    bad.append(f"{ln['id']}: reveal_frame {ro.get('reveal_frame')} outside {rs['id']} {rs['from']}-{rs['to']}")
                    continue
            if not c.shots:
                continue
            kt_ = c.film(ws[i]["s"])
            rt = ro["reveal_frame"] / c.fps
            o = ro.get("order")
            if o == "before":
                lo, hi = nt["reveal_before_s"]
                ok = lo - 1e-6 <= rt - kt_ <= hi + 1e-6
            elif o == "after":
                lo, hi = nt["reveal_after_s"]
                ok = lo - 1e-6 <= kt_ - rt <= hi + 1e-6
            elif o == "on":
                ok = abs(kt_ - rt) <= nt["reveal_on_s"] + 1e-6
            else:
                ok = False
            if not ok:
                bad.append(f"{ln['id']} '{ws[i]['w']}' {o}: word {kt_:.2f} s vs reveal {rt:.2f} s")
        R.ok("CAN-N3b", not bad, "; ".join(bad[:8]) + f" [{src}]", f"all {len(c.lines)} lines honour their reveal order [{src}]")
    # N3c perception order
    bad = []
    dm = {}
    for q in c.sequences():
        for e in q.get("discovery_map") or []:
            dm.setdefault(e.get("shot"), []).append(e)
    for ln in c.lines:
        po = ln.get("perception_order") or []
        if len(po) < 2:
            continue
        txt = ln["text"].lower()
        pos = [txt.find(x.lower()) for x in po]
        if any(p < 0 for p in pos) or pos != sorted(pos):
            bad.append(f"{ln['id']}: perception_order {po} does not match the mention order")
    R.ok("CAN-N3c", not bad, "; ".join(bad[:5]), "perception order consistent (or <2 visible things named)")
    # N3d first word on a new image
    if c.shots:
        bad = []
        words = [(c.film(w["s"]), w["w"]) for w in c.all_words()]
        for prev, s in zip(c.shots, c.shots[1:]):
            t = s["from"] / c.fps
            fw = next((w for ws, w in words if t - 0.05 <= ws < s["to"] / c.fps), None)
            if fw and norm(fw) in PRONOUNS and not s.get("hero") and not prev.get("hero") and norm(fw) in ("he", "she", "him", "her"):
                bad.append(f"{s['id']}: first word {fw!r} on an image without its referent")
        R.ok("CAN-N3d", not bad, "; ".join(bad[:5]))
    # N3e / N4h no talking over reactions
    wins = _reaction_windows(c)
    pad = nt["reaction_pad_s"]
    words = [(c.film(w["s"]), c.film(w["e"]), w["w"]) for w in c.all_words()]
    bad = []
    for a, b, why in wins:
        hit = [w for s_, e_, w in words if s_ < b + pad and e_ > a - pad]
        if hit:
            bad.append(f"{why} ({a:.2f}-{b:.2f} s): words {hit[:4]}")
    if not wins:
        R.missing("CAN-N3e", "reaction windows (reserved_close_up / turn_then_change / reaction gaps)")
    else:
        R.ok("CAN-N3e", not bad, "; ".join(bad[:6]) + f" [{src}]", f"{len(wins)} reaction windows clear [{src}]")
    # N2a sound-led lines (needs sound.json cues)
    sl = [ln for ln in c.lines if ln.get("sound_lead")]
    if not sl:
        R.manual("CAN-N2a", "no line declares sound_lead (sound before words): review where it serves the beat")
    elif c.sound is None:
        R.manual("CAN-N2a", f"{len(sl)} sound-led lines; sound.json not designed yet")
    else:
        bad = []
        lo, hi = nt["sound_lead_s"]
        for ln in sl:
            cue = next((q for q in c.sound.get("cues", []) if q.get("lead_line") == ln["id"] or q.get("id") == ln["sound_lead"].get("cue")), None)
            ws = lw.get(ln["id"]) or []
            if not cue or not ws:
                bad.append(f"{ln['id']}: no sound.json cue leads it")
                continue
            lead = c.film(ws[0]["s"]) - cue["at"] / c.fps
            if not (lo - 1e-6 <= lead <= hi + 1e-6):
                bad.append(f"{ln['id']}: lead {lead:.2f} s outside {lo}-{hi}")
        R.ok("CAN-N2a", not bad, "; ".join(bad))
    # N4e value judgements only after the evidence
    toks = set(T()["narration"]["judgement_tokens"])
    bad = []
    for ln in c.lines:
        ws = lw.get(ln["id"]) or []
        for k, w in enumerate(ws):
            if norm(w["w"]) not in toks:
                continue
            nxt = norm(ws[k + 1]["w"]) if k + 1 < len(ws) else ""
            if norm(w["w"]) == "right" and nxt in ADVERB_AFTER_RIGHT:
                continue  # "right down your wake": a direction, not a judgement
            ev = ln.get("evidence") or {}
            if not ev.get("frame"):
                bad.append(f"{ln['id']} '{w['w']}': judgement with no evidence {{shot, frame}}")
            elif c.film(w["s"]) + 1e-6 < ev["frame"] / c.fps:
                bad.append(f"{ln['id']} '{w['w']}' at {c.film(w['s']):.2f} s before its evidence at {ev['frame'] / c.fps:.2f} s")
    R.ok("CAN-N4e", not bad, "; ".join(bad[:5]))


def check_N_audio(c, R):
    """N1c, N2c, N2d, N2e, N2f (measured), N4f pace/speed, N4g: need words.json and/or sound.json."""
    nt = T()["narration"]
    lw = c.line_words()
    measured = getattr(c, "measured", False)
    # N2c gaps survive voicing
    if not c.words:
        R.manual("CAN-N2c", "no narration.words.json yet (gaps are measured after TTS)")
    elif not measured:
        R.add("CAN-N2c", "FAIL", f"words.json has {len(c.words)} words but the script has "
                                 f"{sum(len(script_words(l['text'])) for l in c.lines)}: re-voice")
    elif c.gaps:
        bad = []
        for g in c.gaps:
            prev, nxt = _gap_boundary(c, g)
            if not prev or not nxt:
                continue
            real = nxt["s"] - prev["e"]
            if real + 1e-6 < g["len_s"] - nt["gap_tolerance_s"]:
                bad.append(f"{g['id']}: measured {real:.2f} s < planned {g['len_s']} s")
        R.ok("CAN-N2c", not bad, "; ".join(bad[:8]), f"{len(c.gaps)} gaps measured in the voiced words")
    else:
        R.missing("CAN-N2c", "story.narration_gaps[]")
    # N2d gaps are filled ; N1c ambience coverage ; N2e no dead air
    if c.sound is None:
        R.manual("CAN-N2d", "sound.json not designed yet")
        if "CAN-N1c" not in R.r:
            R.manual("CAN-N1c", "sound.json not designed yet")
        R.manual("CAN-N2e", "sound.json not designed yet")
    else:
        snd = c.sound
        fps = snd.get("fps", c.fps)
        bad = []
        for g in c.gaps:
            prev, nxt = _gap_boundary(c, g)
            if not prev or not nxt:
                continue
            a, b = c.film(prev["e"]), c.film(nxt["s"])
            fb = g.get("filled_by")
            if fb == "music":
                cov = sum(max(0.0, min(b, m["to"] / fps) - max(a, m["from"] / fps)) for m in (snd.get("music") or {}).get("sections", [])
                          if m.get("energy", 1) > 0)
                if cov < (b - a) - 0.05:
                    bad.append(f"{g['id']}: no music section under the swell")
                continue
            if fb == "room_tone" or (fb or "").startswith("bed_"):
                beds = [x for x in snd.get("beds", []) if x["from"] / fps <= a and x["to"] / fps >= b
                        and (fb == "room_tone" or x["id"] == fb)]
                if not beds:
                    bad.append(f"{g['id']}: no bed covers the gap")
                continue
            cue = next((q for q in snd.get("cues", []) if q.get("gap") == g["id"] or q.get("id") == fb), None)
            if not cue:
                bad.append(f"{g['id']}: filled_by {fb} has no sound.json cue")
                continue
            on = cue["at"] / fps
            if not (a - 1e-6 <= on <= a + g["len_s"] - nt["gap_fill_onset_tail_s"] + 1e-6) or on > b:
                bad.append(f"{g['id']}: cue onset {on:.2f} s outside the gap {a:.2f}-{b:.2f}")
            end = on + float(cue.get("dur") or 0.5)
            if end > b + nt["gap_fill_overlap_s"]:
                bad.append(f"{g['id']}: cue tail runs {end - b:.2f} s into the next word (not -12 dB by it)")
        R.ok("CAN-N2d", not bad, "; ".join(bad[:6]), "every gap filled" if c.gaps else "no gaps declared")
        D = snd.get("durationFrames", int(c.D * fps))
        sil = snd.get("silences", [])
        cover = [0] * max(1, D)
        for bd in snd.get("beds", []):
            if bd.get("bus", "ambience") == "ambience":
                for f in range(max(0, bd["from"]), min(D, bd["to"])):
                    cover[f] = 1
        for sl in sil:
            for f in range(max(0, sl["from"]), min(D, sl["to"])):
                cover[f] = 1
        hole = sum(1 for x in cover if not x)
        R.ok("CAN-N1c", hole <= nt["bed_tolerance_frames"], f"{hole} frames without an ambience bed or declared silence")
        lim_n = _fmt_val(nt["silences_max"], c.fmt)
        badsl = [s_ for s_ in sil if (s_["to"] - s_["from"]) / fps > nt["silence_max_s"] or not s_.get("reason")]
        R.ok("CAN-N2e", hole <= nt["bed_tolerance_frames"] and len(sil) <= lim_n and not badsl,
             f"dead air {hole} f; {len(sil)} silences (max {lim_n}); too long / no reason: {badsl[:2]}")
    # N2f measured speech share
    if c.words and measured:
        ws = c.all_words()
        sp = sum(w["e"] - w["s"] for w in ws)
        share = sp / max(1e-6, c.D)
        win, mx = nt["speech_window_s"], 0.0
        t = 0.0
        while t + win <= c.D + 1e-6:
            a, b = t, t + win
            occ = sum(max(0.0, min(b, c.film(w["e"])) - max(a, c.film(w["s"]))) for w in ws)
            mx = max(mx, occ / win)
            t += 1.0
        R.ok("CAN-N2f", share <= nt["speech_share_max"] + 1e-6 and mx <= nt["speech_window_max"] + 1e-6,
             f"voiced speech {share:.0%} of runtime (max {nt['speech_share_max']:.0%}), densest 20 s window {mx:.0%} (max {nt['speech_window_max']:.0%})",
             f"voiced speech {share:.0%}, densest 20 s window {mx:.0%}")
    elif not c.words:
        R.manual("CAN-N2f", "no words.json yet (planned coverage is CAN-N2f-plan)")
    # N4f pace per block + voice speed
    if c.words and measured:
        bad = []
        lo, hi = nt["wps"]
        blocks, cur = [], []
        gap_after = {g["after_line"] for g in c.gaps}
        for ln in c.lines:
            cur.append(ln["id"])
            if ln["id"] in gap_after:
                blocks.append(cur)
                cur = []
        if cur:
            blocks.append(cur)
        for bl in blocks:
            ws = [w for i in bl for w in lw.get(i, [])]
            if len(ws) < 6:
                continue
            span = ws[-1]["e"] - ws[0]["s"]
            wps = len(ws) / max(1e-6, span)
            if not (lo - 1e-6 <= wps <= hi + 1e-6):
                bad.append(f"block {bl[0]}-{bl[-1]}: {wps:.2f} w/s")
        v = c.voice or {}
        sp = v.get("speed_requested") or 1.0
        tc = v.get("tempo_correction") or 1.0
        vlo, vhi = nt["voice_speed"]
        if not (vlo <= sp <= vhi) or not (vlo <= tc <= vhi):
            bad.append(f"voice speed {sp} / tempo {tc} outside {vlo}-{vhi}")
        R.ok("CAN-N4f-pace", not bad, "; ".join(bad[:6]))
    # N4g tryout record
    if c.story.get("animatic_tryout"):
        R.add("CAN-N4g", "PASS", f"tryout {c.story['animatic_tryout'].get('date')}")
    else:
        R.manual("CAN-N4g", "no animatic_tryout record yet (scratch VO against the animatic, then re-run N2c/N3)")


# ================================================================== VISUAL (C, E, H, P, L, T)
def _validator():
    p = os.path.join(ROOT, "factory", "direction", "shot_validator.py")
    spec = importlib.util.spec_from_file_location("canon_shot_validator", p)
    m = importlib.util.module_from_spec(spec)
    import sys
    sys.path.insert(0, os.path.dirname(p))
    spec.loader.exec_module(m)
    return m


def _lighting():
    p = os.path.join(ROOT, "cloud", "blender", "lighting.py")
    spec = importlib.util.spec_from_file_location("canon_lighting", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def hero_face_cu(s):
    return s.get("size") in CU_SIZES and bool(s.get("hero")) and not s.get("insert") and s.get("size") != "POV"


def check_C(c, R, vrep=None):
    vt = T()["visual"]
    if vrep:
        by = {r["id"]: r for r in vrep["rules"]}
        c3, c4 = by.get("C3", {}), by.get("C4", {})
        R.ok("CAN-C1a", c3.get("status") != "fail" and c4.get("status") != "fail",
             f"shot_validator C3 {c3.get('status')}: {c3.get('detail', '')[:200]}; C4 {c4.get('status')}: {c4.get('detail', '')[:200]}",
             "shot_validator C3/C4 pass")
        c5 = by.get("C5", {})
        R.ok("CAN-C1c", c5.get("status") != "fail", f"shot_validator C5 (advisory): {c5.get('detail', '')[:300]}", "C5 pass", warn=True)
        c1, c2 = by.get("C1", {}), by.get("C2", {})
        R.ok("CAN-C2a-episode", c1.get("status") != "fail" and c2.get("status") != "fail",
             f"C1 {c1.get('detail')}; C2 {c2.get('detail')}", "CU+ECU <= 25%, no run > 3")
    # C1b establishes: per location (breakdown scene.location; else per sequence) one of the first 3 shots is an
    # establishing WS/EWS that declares what it holds together; every establishing shot is wide, >= 36 f, and lists
    # the hero when he is in it
    est = [s for s in c.shots if s.get("establishes")]
    if not est:
        R.missing("CAN-C1b", "shots[].establishes [hero, vessel, threat] on the establishing wides")
    else:
        bad = []
        loc = {sc["id"]: sc.get("location") for sc in (c.breakdown or {}).get("scenes", [])}
        groups = {}
        if loc:
            for s in c.shots:
                groups.setdefault(loc.get(s.get("scene"), s.get("scene")), []).append(s)
        else:
            for q in c.sequences():
                groups[q.get("id")] = [c.smap[i] for i in q.get("shots", []) if i in c.smap]
        for g, sh in groups.items():
            if sh and not any(s.get("establishes") for s in sh[:3]):
                bad.append(f"{g}: no establishing shot in its first 3 shots")
        for s in est:
            if s.get("size") not in WIDE_SIZES:
                bad.append(f"{s['id']}: establishes on a {s.get('size')} (needs WS/EWS)")
            if s["to"] - s["from"] < vt["establish_min_frames"]:
                bad.append(f"{s['id']}: establishing shot {s['to'] - s['from']} f < {vt['establish_min_frames']} f")
            if s.get("hero") and "hero" not in s["establishes"]:
                bad.append(f"{s['id']}: the hero is in the establishing shot but not in establishes")
        R.ok("CAN-C1b", not bad, "; ".join(bad[:6]), f"{len(est)} establishing shots")
    # C2a/b/c reserved close-up
    seqs = [q for q in c.sequences() if not q.get("_implicit")]
    if not seqs:
        for r in ("CAN-C2a", "CAN-C2b", "CAN-C2c"):
            R.missing(r, "shotplan.sequences[] with reserved_close_up")
        return
    bad_a, bad_b, bad_c = [], [], []
    for q in seqs:
        rc = q.get("reserved_close_up")
        cus = [i for i in q.get("shots", []) if i in c.smap and hero_face_cu(c.smap[i])]
        extra = [i for i in cus if not rc or i != rc.get("shot")]
        extra = [i for i in extra if not c.smap[i].get("extra_cu_reason")]
        if rc and rc.get("shot") not in c.smap:
            bad_a.append(f"{q['id']}: reserved_close_up.shot {rc.get('shot')} unknown")
            continue
        if extra:
            bad_a.append(f"{q['id']}: casual hero-face CUs {extra} (only the reserved CU, or declare extra_cu_reason)")
        if not rc:
            continue
        s = c.smap[rc["shot"]]
        if not hero_face_cu(s):
            bad_a.append(f"{q['id']}: reserved CU {s['id']} is {s.get('size')} (needs a hero-face CU/ECU)")
        mid_a = (s["from"] + s["to"]) / 2 / c.fps - c.off_s
        k = c.kt_at(mid_a) or next((k for k in c.kt if k.get("beat") == rc.get("beat")), None)
        idx = c.kt.index(k) if k in c.kt else -1
        prev = c.kt[idx - 1] if idx > 0 else None
        changed = bool(k) and (k.get("decision") or (prev and (set(k.get("character_knows", [])) != set(prev.get("character_knows", []))
                                                               or k.get("who_can_act") != prev.get("who_can_act"))))
        if c.kt and not changed and not str(rc.get("reason", "")).lower().startswith("decision"):
            bad_b.append(f"{q['id']}: reserved CU beat {rc.get('beat')} changes neither character_knows nor who_can_act (and is not a decision)")
        dur = s["to"] - s["from"]
        tt = (s.get("turn_then_change") or [{}])[0]
        need = max(vt["reserved_cu_min_frames"], vt["read_frames"] * 2 + int(tt.get("settle_frames", 0))
                   + int(((tt.get("change") or {}).get("to", 0) - (tt.get("change") or {}).get("from", 0))))
        if not (need <= dur <= vt["reserved_cu_max_s"] * c.fps):
            bad_c.append(f"{s['id']}: {dur} f (need {need}..{int(vt['reserved_cu_max_s'] * c.fps)} f)")
    if not any(q.get("reserved_close_up") for q in seqs):
        bad_a.append("no sequence reserves a close-up for the decisive reaction")
    R.ok("CAN-C2a", not bad_a, "; ".join(bad_a[:6]))
    if not c.kt:
        R.missing("CAN-C2b", "story.knowledge_timeline[]")
    else:
        R.ok("CAN-C2b", not bad_b, "; ".join(bad_b[:4]))
    R.ok("CAN-C2c", not bad_c, "; ".join(bad_c[:4]))


def check_E(c, R):
    vt = T()["visual"]
    seqs = [q for q in c.sequences() if not q.get("_implicit")]
    act = [q for q in seqs if q.get("action")]
    order = {s["id"]: i for i, s in enumerate(c.shots)}
    if not seqs:
        for r in ("CAN-E1a", "CAN-E1g"):
            R.missing(r, "shotplan.sequences[] (action flags, action_order, tension)")
    elif not act:
        R.add("CAN-E1a", "PASS", "no sequence tagged action")
    bad_a, bad_b, bad_c, bad_d, bad_e, bad_h, warn_f = [], [], [], [], [], [], []
    for q in act:
        ao = q.get("action_order") or {}
        keys = ["obstacle_audience", "obstacle_character", "impact", "cost_revealed"]
        miss = [k for k in keys if ao.get(k) not in c.smap]
        if miss:
            bad_a.append(f"{q['id']}: action_order missing/unknown {miss}")
            continue
        ix = [order[ao[k]] for k in keys]
        strict = all(a < b for a, b in zip(ix, ix[1:]))
        shared_ok = ix[1] == ix[2] and c.smap[ao["impact"]].get("long_take") and ix[0] < ix[1] < ix[3]
        if not (strict or shared_ok):
            bad_a.append(f"{q['id']}: steps not in strictly increasing shots {dict(zip(keys, [ao[k] for k in keys]))}")
        oa, oc = c.smap[ao["obstacle_audience"]], c.smap[ao["obstacle_character"]]
        fa = ao.get("obstacle_audience_frame", oa["from"])
        fc = ao.get("obstacle_character_frame", oc["from"])
        if fc - fa < vt["audience_lead_frames"]:
            bad_b.append(f"{q['id']}: audience lead {fc - fa} f < {vt['audience_lead_frames']} f")
        if oa.get("hero") and not oa.get("gaze_away_from"):
            bad_b.append(f"{q['id']}: {oa['id']} shows the hero but declares no gaze_away_from (he must not see it yet)")
        k = order[oc["id"]]
        nxt = c.shots[k + 1] if k + 1 < len(c.shots) else None
        pov_ok = nxt is not None and (nxt.get("size") == "POV" or nxt.get("insert") or "threat" in (nxt.get("establishes") or [])
                                      or any(e.get("shot") == nxt["id"] for e in q.get("discovery_map") or []))
        react = c.shots[k + 2] if k + 2 < len(c.shots) else None
        react_ok = react is not None and react.get("hero") and react["to"] - react["from"] >= vt["reaction_min_frames"]
        if not pov_ok or not react_ok:
            bad_c.append(f"{q['id']}: {oc['id']} must be followed by a POV/reveal of the obstacle, then a reaction >= {vt['reaction_min_frames']} f")
        cr = c.smap[ao["cost_revealed"]]
        if cr["to"] - cr["from"] < vt["cost_min_frames"]:
            bad_d.append(f"{q['id']}: cost shot {cr['id']} {cr['to'] - cr['from']} f < {vt['cost_min_frames']} f")
        if not any(e.get("shot") == cr["id"] for e in q.get("discovery_map") or []):
            bad_d.append(f"{q['id']}: cost shot {cr['id']} has no discovery_map entry (light must reveal the cost)")
        sh = [c.smap[i] for i in q.get("shots", []) if i in c.smap]
        bad_e += [f"{s['id']} {s['to'] - s['from']} f" for s in sh if s["to"] - s["from"] < vt["action_min_frames"] and not s.get("insert")]
        ki = order[ao["impact"]]
        after = c.shots[ki + 1: ki + 1 + vt["reestablish_after_impact"]]
        if after and not any(s.get("size") in WIDE_SIZES for s in after) and len(c.shots) - ki - 1 > vt["reestablish_after_impact"]:
            bad_e.append(f"{q['id']}: no wide within {vt['reestablish_after_impact']} shots after the impact")
        for a, b in zip(sh, sh[1:]):
            ca, cb = a.get("camera", {}), b.get("camera", {})
            size_diff = a.get("size") != b.get("size")
            az_diff = ca.get("rig") == cb.get("rig") == "orbit" and ca.get("az") and cb.get("az") and \
                abs(ca["az"][-1] - cb["az"][0]) >= vt["new_angle_az_deg"]
            other = a.get("scene") != b.get("scene") or (ca.get("rig") != cb.get("rig")) or ca.get("mark") != cb.get("mark")
            if not (size_diff or az_diff or other):
                bad_h.append(f"{a['id']}>{b['id']}")
        cl = [(s["to"] - s["from"]) for s in sh if s.get("size") in ("CU", "MCU", "ECU")]
        ld = [(s["to"] - s["from"]) for s in sh if s.get("size") in WIDE_SIZES]
        if cl and ld and statistics.median(cl) >= statistics.median(ld):
            warn_f.append(f"{q['id']}: median close {statistics.median(cl)} f >= median wide {statistics.median(ld)} f")
    if act:
        R.ok("CAN-E1a", not bad_a, "; ".join(bad_a))
        R.ok("CAN-E1b", not bad_b, "; ".join(bad_b))
        R.ok("CAN-E1c", not bad_c, "; ".join(bad_c))
        R.ok("CAN-E1d", not bad_d, "; ".join(bad_d))
        R.ok("CAN-E1e", not bad_e, f"action shots too short / no re-establish: {bad_e[:6]}")
        R.ok("CAN-E1f", not warn_f, "; ".join(warn_f), warn=True)
        R.ok("CAN-E1h", not bad_h, f"action cuts without a new angle (size class or >= 30 deg az): {bad_h[:6]}")
    # E1g tension
    if seqs:
        bad = []
        for q in seqs:
            t = q.get("tension")
            if t not in ("mounting", "plateau", "release"):
                bad.append(f"{q['id']}: tension {t!r}")
                continue
            sh = [c.smap[i] for i in q.get("shots", []) if i in c.smap]
            if t == "mounting" and len(sh) >= 3:
                n = len(sh) // 3
                first = statistics.mean(s["to"] - s["from"] for s in sh[:n])
                last = statistics.mean(s["to"] - s["from"] for s in sh[-n:])
                if last > T()["visual"]["mounting_asl_ratio"] * first + 1e-6:
                    bad.append(f"{q['id']}: mounting but last-third ASL {last:.0f} f > 0.8 x first {first:.0f} f")
        R.ok("CAN-E1g", not bad, "; ".join(bad[:5]))
    # E1i compressed time needs a cutaway
    tc = [s for s in c.shots if s.get("time_cut")]
    if not tc:
        R.add("CAN-E1i", "PASS", "no time_cut shots")
    else:
        bad = []
        for s in tc:
            k = order[s["id"]]
            p = c.shots[k - 1] if k else None
            if not p or not (p.get("cutaway") or p.get("size") == "POV" or p.get("insert") or p.get("reaction_windows")
                             or p.get("turn_then_change")):
                bad.append(f"{s['id']}: time cut without a reaction/parallel cutaway before it")
        R.ok("CAN-E1i", not bad, "; ".join(bad))


def _impact_window(ih):
    f = ih.get("impact_frame", 0)
    return f, f + ih.get("escape_frames", 0) + ih.get("lag_frames", 0) + ih.get("recover_frames", 0)


def check_H(c, R, vrep=None):
    vt = T()["visual"]
    imp_ids = {q["action_order"]["impact"] for q in c.sequences() if (q.get("action_order") or {}).get("impact")}
    imp_ids |= {s["id"] for s in c.shots if (s.get("camera") or {}).get("motivation") == "impact"}
    bad = [i for i in sorted(imp_ids) if i in c.smap and not c.smap[i].get("impact_handheld")]
    R.ok("CAN-H1a", not bad, f"impact shots without impact_handheld: {bad}",
         f"{len(imp_ids)} impact shot(s) declare reactive handheld" if imp_ids else "no impact shots")
    ihs = [(s, s["impact_handheld"]) for s in c.shots if s.get("impact_handheld")]
    bb, bc = [], []
    for s, ih in ihs:
        e, l, r = ih.get("escape_frames"), ih.get("lag_frames"), ih.get("recover_frames")
        f = ih.get("impact_frame")
        if f is None or not (s["from"] <= f < s["to"]):
            bb.append(f"{s['id']}: impact_frame {f} outside the shot")
        if e is None or not (vt["escape_frames"][0] <= e <= vt["escape_frames"][1]):
            bb.append(f"{s['id']}: escape_frames {e} not in {vt['escape_frames']}")
        if l is None or not (vt["lag_frames"][0] <= l <= vt["lag_frames"][1]):
            bc.append(f"{s['id']}: lag_frames {l} not in {vt['lag_frames']}")
        if r is None or r > vt["recover_frames_max"]:
            bc.append(f"{s['id']}: recover_frames {r} > {vt['recover_frames_max']}")
        es = c.ep_shots.get(s["id"])
        if c.ep and es is not None and not es.get("impact_handheld"):
            bc.append(f"{s['id']}: compiled camera carries no impact layer")
    if ihs:
        R.ok("CAN-H1b", not bb, "; ".join(bb))
        R.ok("CAN-H1c", not bc, "; ".join(bc))
    # H1d / H1e on the compiled camera
    if c.ep and ihs:
        try:
            import sys
            sys.path.insert(0, os.path.join(ROOT, "factory", "direction"))
            import camgeo as G
            bad = []
            for s, ih in ihs:
                es = c.ep_shots.get(s["id"])
                if not es:
                    continue
                f = ih["impact_frame"]
                fr = list(range(max(es["from"], f - 2), min(es["to"] - 1, f + ih.get("lag_frames", 4)) + 1))
                angs = []
                for a, b in zip(fr, fr[1:]):
                    ca, la, _, _ = G.camera_world(es, a, jitter=False)
                    cb, lb, _, _ = G.camera_world(es, b, jitter=False)
                    u, v = G.unit(G.sub(la, ca)), G.unit(G.sub(lb, cb))
                    angs.append(math.degrees(math.acos(max(-1.0, min(1.0, G.dot(u, v))))) * c.fps)
                if not angs or max(angs) < vt["impact_min_deg_s"]:
                    bad.append(f"{s['id']}: camera {max(angs or [0]):.1f} deg/s around the impact (locked-off)")
            R.ok("CAN-H1d", not bad, "; ".join(bad))
        except Exception as e:  # noqa: BLE001
            R.manual("CAN-H1d", f"camera maths unavailable ({e})")
    if c.ep:
        bad = []
        for es in c.ep.get("shots", []):
            hh = es["camera"].get("handheld", 0.2)
            if isinstance(hh, list):
                hh = max(v for _, v in hh)
            lim = vt["handheld_pov_max"] if (c.smap.get(es["id"], {}).get("size") == "POV") else vt["handheld_baseline_max"]
            if hh > lim + 1e-9:
                bad.append(f"{es['id']} {hh}")
        R.ok("CAN-H1e", not bad, f"constant decorative shake above baseline {vt['handheld_baseline_max']} (POV {vt['handheld_pov_max']}): {bad[:8]}")
    if vrep is not None:
        ex = [x["id"] for x in vrep.get("shots", []) if x.get("impact_exempt")]
        R.ok("CAN-H1f", not ihs or bool(ex) or not c.ep, "shot_validator did not receive the impact windows",
             f"shot_validator exempts H1/C11 inside impact windows ({ex})" if ex else "no impact windows to exempt")
    rcs = {(q.get("reserved_close_up") or {}).get("shot") for q in c.sequences()}
    clash = [s["id"] for s, _ in ihs if s["id"] in rcs]
    R.ok("CAN-H1g", not clash, f"impact handheld on the reserved CU: {clash}")


def _turn_windows(s, vt):
    """Declared turn windows + head-turn poses (look_*/turn*) as [from, from+in] windows."""
    out = []
    for t in s.get("turn_then_change") or []:
        tr = t.get("turn") or {}
        if tr.get("from") is not None and tr.get("to") is not None:
            out.append((tr["from"], tr["to"], "declared turn"))
    for p in (s.get("hero") or {}).get("poses", []):
        if TURN_POSE.search(p["pose"]):
            out.append((p["from"], p["from"] + int(p.get("in", 8)), p["pose"]))
    return out


def _face_keys(c, s):
    """Emotion keys [[f, name]] and blinks for a shot: the compiled perf.face if there is one, else derived from the plan."""
    es = c.ep_shots.get(s["id"]) or {}
    for a in es.get("actors") or []:
        face = (a.get("perf") or {}).get("face") or a.get("face")
        if face:
            return face.get("emotion") or [], face.get("blinks") or [], face.get("blend", T()["visual"]["emotion_blend_frames"])
    try:
        from factory.director.compile import schedule_face
        face = schedule_face(s)
        if face:
            return face.get("emotion") or [], face.get("blinks") or [], face.get("blend", 10)
    except Exception:  # noqa: BLE001
        pass
    return [], [], T()["visual"]["emotion_blend_frames"]


def check_P(c, R):
    vt = T()["visual"]
    bk = vt["bookend_frames"]
    hero_shots = [s for s in c.shots if s.get("hero")]
    # P1a / P1b / P1d / P1e
    ttc = [(s, t) for s in c.shots for t in s.get("turn_then_change") or []]
    bad_a, bad_b, bad_d, bad_e = [], [], [], []
    for s in hero_shots:
        emo, blinks, blend = _face_keys(c, s)
        wins = _turn_windows(s, vt)
        for k in emo:
            f = k[0]
            if f <= s["from"]:
                continue  # the shot's opening emotion (held from before the cut)
            for a, b, why in wins:
                if f < b and f + blend > a:
                    bad_a.append(f"{s['id']}: emotion '{k[1]}' at {f} (+{blend} f blend) inside {why} {a}-{b}")
    for s, t in ttc:
        tr, ch = t.get("turn") or {}, t.get("change") or {}
        if None in (tr.get("from"), tr.get("to"), ch.get("from"), ch.get("to")):
            bad_b.append(f"{s['id']}: turn_then_change needs turn{{from,to}} and change{{from,to}}")
            continue
        if t.get("mode") == "pre_turn":
            if ch["to"] > tr["from"] - vt["pre_turn_frames"]:
                bad_b.append(f"{s['id']}: pre_turn change must end >= {vt['pre_turn_frames']} f before the turn")
        else:
            st = int(t.get("settle_frames", ch["from"] - tr["to"]))
            if st < vt["settle_frames_min"] or abs((ch["from"] - tr["to"]) - st) > 1:
                bad_b.append(f"{s['id']}: settle {ch['from'] - tr['to']} f (declared {st}; need >= {vt['settle_frames_min']})")
        emo, blinks, _ = _face_keys(c, s)
        lo, hi = vt["blink_window"]
        if t.get("no_blink"):
            if (t.get("no_blink_frames") or 0) > vt["no_blink_max_frames"]:
                bad_d.append(f"{s['id']}: noBlink hold > {vt['no_blink_max_frames']} f")
        elif not any(ch["from"] + lo <= b <= ch["from"] + hi for b in blinks):
            bad_d.append(f"{s['id']}: no thought blink in [{ch['from'] + lo}, {ch['from'] + hi}]")
        deg = abs(tr.get("deg") or 0)
        if deg >= vt["fast_turn_deg"] and tr["to"] - tr["from"] <= vt["fast_turn_frames"]:
            mid0 = tr["from"] + 0.5 * (tr["to"] - tr["from"])
            if not any(mid0 - 2 <= b <= tr["to"] for b in blinks):
                bad_e.append(f"{s['id']}: fast {deg} deg turn in {tr['to'] - tr['from']} f without a blink at 50-100 %")
    R.ok("CAN-P1a", not bad_a, "; ".join(bad_a[:6]))
    if ttc:
        R.ok("CAN-P1b", not bad_b, "; ".join(bad_b[:6]))
        R.ok("CAN-P1d", not bad_d, "; ".join(bad_d[:6]))
        R.ok("CAN-P1e", not bad_e, "; ".join(bad_e[:6]), "fast turns carry a blink" if bad_e == [] else "")
    else:
        R.missing("CAN-P1b", "shots[].turn_then_change (at least for the reserved close-up)")
    # P1c bookends
    bad = []
    for s in hero_shots:
        if s.get("match_action"):
            continue
        h = s["hero"]
        a0, a1 = s["from"], s["from"] + bk
        z0, z1 = s["to"] - bk, s["to"]
        evs = [(f, f"stance {st}") for f, st in h.get("stance_changes", [])]
        for p in h.get("poses", []):
            if p["from"] >= s["from"]:
                evs.append((p["from"], f"pose {p['pose']} onset"))
            if p["to"] < s["to"]:
                evs.append((p["to"], f"pose {p['pose']} release"))
        emo, _, _ = _face_keys(c, s)
        evs += [(k[0], f"emotion {k[1]}") for k in emo if k[0] > s["from"]]
        for f, why in evs:
            if a0 <= f < a1 or z0 < f <= z1 - 1:
                bad.append(f"{s['id']}: {why} at {f} ({f - s['from']} f in / {s['to'] - f} f out)")
    R.ok("CAN-P1c", not bad, "; ".join(bad[:8]) + (f" (+{len(bad) - 8} more)" if len(bad) > 8 else ""),
         f"no pose/stance/emotion change in the first/last {bk} f of {len(hero_shots)} hero shots")
    R.manual("CAN-P1f", "bounce-apex timing needs the baked head track (acting bake)")
    rcs = [(q.get("reserved_close_up") or {}).get("shot") for q in c.sequences() if q.get("reserved_close_up")]
    if rcs:
        nolog = [i for i in rcs if i in c.smap and not c.smap[i].get("turn_then_change")]
        R.ok("CAN-P1g", not nolog, f"reserved CU(s) {nolog} log no turn_then_change (the sound-off test needs one)",
             "reserved CU logs turn_then_change; sound-off review stays manual")
    # P2c every verb/pose has a reason
    bad = []
    for s in hero_shots:
        for v in s["hero"].get("verbs", []) + s["hero"].get("poses", []):
            if not (v.get("why") or "").strip():
                bad.append(f"{s['id']}:{v.get('verb') or v.get('pose')}")
    R.ok("CAN-P2c", not bad, f"moves without a why (beat or stimulus): {bad[:10]}" + (f" (+{len(bad) - 10})" if len(bad) > 10 else ""))
    R.manual("CAN-P2a", "blink cadence (CV >= 0.35) needs the baked face track")
    R.manual("CAN-P2b", "eyes-lead-head needs gaze keys (cloudrig_adapter face_at)")
    R.manual("CAN-P2d", "hands: lessons L010/L017 checks on renders")


def check_L(c, R):
    vt = T()["visual"]
    seqs = [q for q in c.sequences() if not q.get("_implicit")]
    dm = [(q, e) for q in seqs for e in q.get("discovery_map") or []]
    if not seqs or not dm:
        R.missing("CAN-L1a", "sequences[].discovery_map[] {detail, shot, frame, light_reveal{source, kind}}")
    else:
        bad = []
        no = [q["id"] for q in seqs if not q.get("discovery_map")]
        if no:
            bad.append(f"sequences without a discovery: {no}")
        kinds = {"reflection", "rim", "practical_pool", "lightning", "silhouette", "glint"}
        for q, e in dm:
            s = c.smap.get(e.get("shot"))
            lr = e.get("light_reveal") or {}
            src = str(lr.get("source", ""))
            if not s:
                bad.append(f"{e.get('detail')}: shot {e.get('shot')} unknown")
                continue
            f = e.get("frame")
            if f is None or not (s["from"] + vt["discovery_min_into_shot"] <= f < s["to"]):
                bad.append(f"{e.get('detail')}: frame {f} must be >= {vt['discovery_min_into_shot']} f into {s['id']} ({s['from']}-{s['to']})")
            if src.split(":")[0] not in vt["light_sources"] or lr.get("kind") not in kinds:
                bad.append(f"{e.get('detail')}: light_reveal {lr} (source in {vt['light_sources']}, kind in {sorted(kinds)})")
        R.ok("CAN-L1a", not bad, "; ".join(bad[:6]), f"{len(dm)} discoveries")
        # L1e the revealed thing is the only salient mover
        bad = []
        lo, hi = vt["reveal_quiet_window"]
        for q, e in dm:
            s = c.smap.get(e.get("shot"))
            f = e.get("frame")
            if not s or f is None:
                continue
            h = s.get("hero") or {}
            ons = [p["from"] for p in h.get("poses", [])] + [v["at"] for v in h.get("verbs", [])] + [x[0] for x in h.get("stance_changes", [])]
            ons = [o for o in ons if f + lo <= o <= f + hi]
            cuts = [x for x in c.shots if f + lo <= x["from"] <= f + hi and x["id"] != s["id"]
                    and (x.get("camera") or {}).get("preset") not in vt["reveal_presets"]]
            if ons or cuts:
                bad.append(f"{e.get('detail')} @{f}: hero onsets {ons} / cuts {[x['id'] for x in cuts]} in [{f + lo}, {f + hi}]")
        R.ok("CAN-L1e", not bad, "; ".join(bad[:4]), warn=True)
    # L1f audience-first exception (gaze away in obstacle_audience) -- gaze keys are not in the plan yet
    R.manual("CAN-L1f", "eyeline to the discovery needs gaze keys; audience-first gaze_away_from is checked in CAN-S1a/E1b")
    if c.plates:
        _plates_L1d(c, R)
    else:
        for r in ("CAN-L1b", "CAN-L1c", "CAN-L1d"):
            R.manual(r, "needs plates (--plates)")
    # L2 from lighting.py
    if c.lighting is not None:
        rows, probs = c.lighting
        l2 = [p for p in probs if p.startswith(("L2", "L8"))]
        R.ok("CAN-L2a", not l2, "; ".join(l2[:5]), f"key holds across cuts ({len(rows)} shots)")
        lit = [r for r in rows if r.get("key_fill") is not None and (r.get("dawn") or 0) < 0.5]   # night shots only
        lowf = [r["shot"] for r in lit if r["key_fill"] < 4.0]
        if lit:
            R.ok("CAN-L2d", not lowf, f"key:fill < 4:1 on {lowf[:6]}", "key:fill >= 4:1 (azimuth vs camera needs plates)")
        l5 = [p for p in probs if p.startswith("L5")]
        if lit:
            R.ok("CAN-L2g", not l5, "; ".join(l5[:4]), "key/practical hue separation >= 120 deg")
        else:
            R.manual("CAN-L2g", "legacy lighting (no preset)")
    else:
        R.manual("CAN-L2a", "lighting continuity check unavailable")
    for r in ("CAN-L2b", "CAN-L2c", "CAN-L2e", "CAN-L2f"):
        R.manual(r, "needs plates / the Blender light rig")
    for r in ("CAN-L3a", "CAN-L3b", "CAN-L3c", "CAN-L3d", "CAN-L3e", "CAN-L3f", "CAN-L3g"):
        R.manual(r, "needs plates with depth/masks")


def _luma(path):
    try:
        import numpy as np
        from PIL import Image
        a = np.asarray(Image.open(path).convert("RGB"), dtype="float32") / 255.0
        return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]
    except Exception:  # noqa: BLE001
        return None


def _plates_L1d(c, R):
    vt = T()["visual"]
    bad, n = [], 0
    for s in c.shots:
        fs = sorted(glob.glob(os.path.join(c.plates, s["id"], "*.png")))
        if not fs:
            continue
        y = _luma(fs[len(fs) // 2])
        if y is None:
            continue
        n += 1
        lit, hot, blk = float((y > 0.5).mean()), float((y >= 0.75).mean()), float((y <= 0.04).mean())
        lo, hi = vt["night_well_lit"]
        if not (lo <= lit <= hi) or hot < vt["night_hot_frac"] or blk < vt["night_black_frac"]:
            bad.append(f"{s['id']}: lit {lit:.1%} hot {hot:.2%} blacks {blk:.0%}")
    if n:
        R.ok("CAN-L1d", not bad, "; ".join(bad[:6]), f"{n} plates low-key")
    else:
        R.manual("CAN-L1d", "no PNG plates found")
    R.manual("CAN-L1b", "needs detail masks (cryptomatte)")
    R.manual("CAN-L1c", "needs detail masks (cryptomatte)")


def lookdev_hash(ep):
    """Hash of what the look-dev test locks: lighting preset + params, water + hull materials (CAN-T1a)."""
    import hashlib
    w = (ep or {}).get("world") or {}
    st = (ep or {}).get("style") or {}
    payload = {"lighting": w.get("lighting") or st.get("lighting"), "seaState": w.get("seaState"), "moonDir": w.get("moonDir"),
               "materials": (st.get("materials") or {}), "yacht": ((ep or {}).get("assets") or {}).get("props", {}).get("yacht")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def check_T(c, R):
    lt = (c.plan or {}).get("lookdev_test") or (c.ep or {}).get("lookdev_test")
    vt = T()["visual"]
    if not lt:
        R.missing("CAN-T1a", "shotplan.lookdev_test {view, elements [boat, one_practical, water], lighting_preset, ...}")
        return
    els = set(lt.get("elements") or [])
    yacht = any((s.get("yacht") or {}).get("state", "absent") != "absent" for s in c.shots)
    need = {"boat", "one_practical", "water"} if yacht else {"one_practical"}
    R.ok("CAN-T1b", need <= els and not (els & {"actors", "fx", "spray", "rain", "funnel"}),
         f"look-dev elements {sorted(els)} must be {sorted(need)} only (no actors/FX)")
    fx = [s["id"] for s in c.shots if (s.get("placeholder") or "") or any(k in json.dumps(s.get("env") or {}) for k in ("storm", "spray"))]
    cur = lookdev_hash(c.ep) if c.ep else None
    if not lt.get("approved_at"):
        if c.stage == "render":
            R.add("CAN-T1a", "FAIL", "look-dev test not approved: FX / weather / acting renders are refused")
        else:
            R.add("CAN-T1a", "PASS", f"look-dev test planned ({lt.get('view')}); approval required before render")
    else:
        ok = not cur or lt.get("hash") in (None, cur)
        R.ok("CAN-T1a", ok, f"look-dev hash {lt.get('hash')} != current lighting/material hash {cur}: re-test",
             f"approved by {lt.get('approved_by')} at {lt.get('approved_at')}")
    png = _abs(lt.get("frame_png"), c.dir or ROOT) if lt.get("frame_png") else None
    if png and os.path.isfile(png):
        y = _luma(png)
        if y is not None:
            clip = float((y >= 0.995).mean())
            water = y[int(0.6 * y.shape[0]):]
            ok = clip <= vt["lookdev_clip_max"] and float(water.mean()) >= vt["lookdev_water_min"]
            R.ok("CAN-T1c", ok, f"look-dev frame: clipped {clip:.2%}, water mean {float(water.mean()):.3f}")
    else:
        R.manual("CAN-T1c", "look-dev frame not rendered yet")
    if lt.get("approved_at"):
        R.ok("CAN-T1d", bool(lt.get("locks")), "approved look-dev test records no locks {practical_kelvin, key_color, lut}")
    else:
        R.manual("CAN-T1d", "locks are recorded at approval")
    R.manual("CAN-T1e", "night colour cues / open shadows need plates")


# ================================================================== entry points
def story_rules(story, words=None):
    """Stage 1 (develop): the rules computable from story.json alone."""
    c = Ctx(story=story, words=words)
    R = Results()
    check_S(c, R)
    check_N_story(c, R)
    return R.r


def plan_rules(story, plan, ep=None, words=None, breakdown=None):
    """Stage 4 (direct): story + shotplan (+ compiled episode) rules, before voice/sound/plates exist."""
    c = Ctx(story=story, plan=plan, ep=ep, words=words, breakdown=breakdown)
    R = Results()
    check_S_plan(c, R)
    check_N_plan(c, R)
    check_C(c, R)
    check_E(c, R)
    check_H(c, R)
    check_P(c, R)
    L = Results()
    check_L(c, L)
    R.r.update({k: v for k, v in L.r.items() if k in ("CAN-L1a", "CAN-L1e")})
    check_T(c, R)
    return R.r


def load_ctx(episode_json, plates=None, video=None, stage="plan"):
    ep = _read(episode_json) or {}
    d = os.path.dirname(os.path.abspath(episode_json))
    story = _read(os.path.join(d, "story.json"))
    plan = _read(os.path.join(d, "shotplan.json"))
    sound = _read(os.path.join(d, "sound.json"))
    wpath = None
    for cand in (os.path.join(d, "audio", "narration.words.json"), _abs((ep.get("audio") or {}).get("wordsJson"), d)):
        if cand and os.path.isfile(cand):
            wpath = cand
            break
    words = _read(wpath)
    voice = _read(os.path.join(os.path.dirname(wpath), "narration.voice.json")) if wpath else None
    gaps = _read(os.path.join(os.path.dirname(wpath), "narration.gaps.json")) if wpath else None
    try:
        lighting = _lighting().check_sequences(ep)
    except Exception:  # noqa: BLE001
        lighting = None
    return Ctx(story=story, plan=plan, ep=ep, sound=sound, words=words, voice=voice, gaps_report=gaps, plates=plates,
               video=video, ep_dir=d, stage=stage, lighting=lighting, breakdown=_read(os.path.join(d, "breakdown.json")))


def run_all(episode_json, plates=None, video=None, stage="plan"):
    """All canon rules for an episode -> {RULE_ID: {status, detail}} (parents + sub-rules)."""
    c = load_ctx(episode_json, plates, video, stage)
    R = Results()
    vrep = None
    if c.ep.get("shots"):
        try:
            V = _validator()
            V.load_coast(ROOT)
            vrep = V.validate(c.ep)
        except Exception as e:  # noqa: BLE001
            R.add("CAN-C1a", "MANUAL", f"shot_validator unavailable ({type(e).__name__}: {e})")
    if not c.story:
        R.missing("CAN-S2a", "story.json next to the episode")
    check_S(c, R)
    if c.shots:
        check_S_plan(c, R)
    check_N_story(c, R)
    if c.shots:
        check_N_plan(c, R)
    check_N_audio(c, R)
    check_C(c, R, vrep)
    check_E(c, R)
    check_H(c, R, vrep)
    # polish_camera: the shot validator's own camera-maths verdicts on CAN-C1/C2/H1 are reported as sub-rules '<id>v'.
    # They are advisory here (WARN): the shot validator already blocks them in its own gate step (no new failures vs
    # base), and the canon's semantic sub-rules above stay the blocking verdict, so one defect is not blocked twice.
    for r in (vrep or {}).get("rules", []):
        if r.get("id") in ("CAN-C1", "CAN-C2", "CAN-H1"):
            R.add(r["id"] + "v", "PASS" if r["status"] == "pass" else "WARN", f"shot_validator: {r.get('detail', '')}")
    check_P(c, R)
    check_L(c, R)
    check_T(c, R)
    out = aggregate(R)
    out["_meta"] = {"words": "measured" if getattr(c, "measured", False) else ("absent" if not c.words else "mismatch"),
                    "sound": c.sound is not None, "shotplan": bool(c.plan), "story": bool(c.story), "stage": stage}
    return out


def failing(results, prefix="CAN-"):
    return {k: v for k, v in results.items() if k.startswith(prefix) and isinstance(v, dict) and v.get("status") == "FAIL"}
