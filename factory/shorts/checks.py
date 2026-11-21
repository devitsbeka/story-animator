"""Shorts checklist on a derived short (structure of the edit; factory.qc then scores the episode/video).

ARCHITECTURE "Deriving shorts from long-form" + ENGAGEMENT_RECIPE sections 1, 2 (R-7), 4 (P-1, P-2) and 5 (C-2).
"""
from factory.director.report import Report

FPS = 30


def check_short(res, long_ep):
    e, qep, pages = res["edit"], res["episode"], res["pages"]
    rep = Report("shorts")
    shots = e["shots"]
    D = e["durationFrames"] / FPS
    hook = e["hook"]
    hd = (hook["dst1"] - hook["dst0"]) / FPS
    rep.hard("SH-hook", hook["dst0"] == 0 and 1.0 <= hd <= 3.0, f"the short opens on a new 1-3 s cold-open hook (got {hd:.2f} s at {hook['dst0']})")
    rep.check("SH-hook-source", hook["source"] in ("recut", "vo_pickup"), f"hook source {hook['source']!r}")
    rep.check("SH-duration", 45.0 <= D <= 120.0, f"short runs {D:.1f} s (45-120 s)")
    durs = [(s["to"] - s["from"]) / FPS for s in shots]
    asl = D / len(shots)
    rep.check("SH-P-1", 1.8 <= asl <= 2.6, f"ASL {asl:.2f} s outside the shorts range 1.8-2.6 s ({len(shots)} shots)")
    rep.check("SH-P-2", max(durs) <= 3.0, f"a visual change (cut or punch-in) at least every 3 s: longest shot {max(durs):.2f} s")
    rep.hard("SH-contiguous", shots[0]["from"] == 0 and all(a["to"] == b["from"] for a, b in zip(shots, shots[1:])), "shots are contiguous from frame 0")
    by_id = {s["id"]: s for s in long_ep["shots"]}
    not_vert = sorted({s["plate"] for s in shots if not (by_id.get(s["plate"], {}).get("cameras") or {}).get("vertical")})
    rep.hard("SH-vertical", not not_vert, f"every shot is a re-framed 9:16 plate (cameras.vertical), never a crop: {not_vert}")
    tail = e["segments"][-1]
    rep.hard("SH-loop", tail["kind"] == "tail" and tail["src0"] == e["segments"][0]["src0"] and tail["dst1"] == e["durationFrames"],
             "the short ends on the hook's opening frames (R-7 frame_match loop)")
    rep.check("SH-C-2", all(1 <= len(p["words"]) <= 3 for p in pages), "caption pages hold 1-3 words")
    rep.hard("SH-size", (qep["width"], qep["height"]) == (1080, 1920), "shorts are 1080x1920")
    cams_ok = all(s["camera"]["keys"][0]["f"] <= s["from"] and s["camera"]["keys"][-1]["f"] >= s["to"] - 1 for s in qep["shots"])
    rep.hard("SH-camera-span", cams_ok, "re-timed vertical camera keys span every shot of the short")
    return rep
