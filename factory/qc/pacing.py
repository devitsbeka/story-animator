"""Pacing from the directed edit (episode.json shots, captions, camera events) and the words.

ENGAGEMENT section 4 (P-1, P-2, P-3), section 2 R-9 (dead air) and PIXAR checklist C9.
"""
from __future__ import annotations

from .common import check, rnd, skip
from .episode import sections

# ENGAGEMENT P-1 table: allowed range of the mean shot length per section (s)
ASL_RANGE = {"HOOK": (0.6, 2.0), "CONTEXT": (1.2, 3.5), "ESCALATION_1": (1.0, 3.0), "MIDPOINT": (0.0, 5.0),
             "ESCALATION_2": (0.8, 3.0), "PAYOFF": (0.0, 4.5), "STING": (1.0, 2.0)}


def shot_bounds(ep):
    return sorted({s["from"] for s in ep.shots} | {ep.frames})


def visual_events(ep):
    """Times (s) of visual changes the edit declares: cuts, caption pages, camera shakes,
    yacht light changes, fires/VFX keys, hero pose starts (P-2's list)."""
    fps = ep.fps
    ev = set()
    for s in ep.shots:
        ev.add(s["from"] / fps)
        for sh in (s.get("camera") or {}).get("shakes") or []:
            ev.add(sh["at"] / fps)
        y = s.get("yacht") or {}
        lk = y.get("lights")
        if isinstance(lk, list):
            prev = None
            for f, v in sorted(lk, key=lambda k: k[0]):
                if prev is not None and abs(v - prev) > 0.2 and s["from"] <= f < s["to"]:
                    ev.add(f / fps)
                prev = v
        for key in ("pitch", "roll", "sink"):
            if isinstance(y.get(key), list):
                ev.add(max(s["from"], min(k[0] for k in y[key])) / fps)
        for f, _ in s.get("fires") or []:
            ev.add(max(f, s["from"]) / fps)
        for a in s.get("actors") or []:
            for p in (a.get("perf") or {}).get("poses") or []:
                if s["from"] <= p["from"] < s["to"]:
                    ev.add(p["from"] / fps)
    for c in ep.captions:
        ev.add(c["from"] / fps)
    return sorted(t for t in ev if 0 <= t <= ep.duration)


def pacing_checks(ep):
    out = []
    fps, D = ep.fps, ep.duration
    shots = sorted(ep.shots, key=lambda s: s["from"])
    if not shots:
        return [skip("P-1.asl_overall", "PACING", "no shots")]
    durs = [(s["to"] - s["from"]) / fps for s in shots]
    asl = D / len(shots)
    out.append(check("P-1.asl_overall", "PACING", 1.8 <= asl <= 2.6, rnd(asl, 2), "overall ASL 1.8-2.6 s"))
    lo = 25 + (D - 60) * 21 / 60
    hi = 33 + (D - 60) * 27 / 60
    out.append(check("P-1.shot_count", "PACING", lo <= len(shots) <= hi, len(shots), f"{rnd(lo, 1)}-{rnd(hi, 1)} shots for {rnd(D, 1)} s"))
    per = {}
    for s, d in zip(shots, durs):
        mid = (s["from"] + s["to"]) / 2 / fps
        name = next((n for n, a, b in sections(D) if a <= mid < b), "STING")
        per.setdefault(name, []).append(d)
    bad = {}
    for name, a, b in sections(D):
        ds = per.get(name)
        if not ds:
            continue
        m = sum(ds) / len(ds)
        r0, r1 = ASL_RANGE[name]
        if not (r0 <= m <= r1):
            bad[name] = {"asl_s": rnd(m, 2), "range": [r0, r1], "shots": len(ds)}
    out.append(check("P-1.asl_sections", "PACING", not bad, {n: rnd(sum(v) / len(v), 2) for n, v in per.items()}, "per-section ASL inside the P-1 table", bad or None))
    ev = visual_events(ep)
    pts = [0.0] + ev + [D]
    gaps = [(b - a, a) for a, b in zip(pts, pts[1:])]
    g, at = max(gaps)
    out.append(check("P-2.visual_change_gap", "PACING", g <= 3.0, {"max_gap_s": rnd(g, 2), "at_s": rnd(at, 2), "events": len(ev)},
                     "a declared visual change at least every 3.0 s (cuts, captions, shakes, light/VFX keys, pose starts)"))
    if ep.words:
        starts = [w.start * fps for w in ep.words]
        cuts = [s["from"] for s in shots if s["from"] > 0]
        near = [min(abs(c - x) for x in starts) for c in cuts]
        share = sum(n <= 2 for n in near) / len(near) if near else 1.0
        out.append(check("P-3.cut_on_word", "PACING", share >= 0.8, {"share": rnd(share), "cuts": len(cuts)}, ">= 80% of cuts within +-2 frames of a word start",
                         {"off_by_frames": {s["id"]: rnd(n, 1) for s, n in zip(shots[1:], near) if n > 2}}))
    else:
        out.append(skip("P-3.cut_on_word", "PACING", "no word timings"))
    short = [s["id"] for s, d in zip(shots, durs) if d * fps < 18 and not s.get("insert")]
    long_ = [s["id"] for s, d in zip(shots, durs) if d > 6.0 and not s.get("long_take")]
    out.append(check("C9.shot_duration", "PACING", not short and not long_, {"min_s": rnd(min(durs), 2), "max_s": rnd(max(durs), 2)},
                     "PIXAR C9: no shot < 18 f (except inserts) or > 6 s (unless long_take)", {"too_short": short, "too_long": long_}))
    # R-9 dead air: no 3 s window with neither narration, a visual event nor an accent
    acts = sorted(ev + [w.start for w in ep.words] + [w.end for w in ep.words])
    pts = [0.0] + acts + [D]
    dead = [(rnd(a, 2), rnd(b, 2)) for a, b in zip(pts, pts[1:]) if b - a >= 3.0]
    out.append(check("R-9.dead_air", "RETENTION", not dead, dead, "no >= 3 s window without narration or a visual event"))
    return out
