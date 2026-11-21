"""Synthetic docuseries fixtures: a ~6-minute 'mini-doc' (scale model of the 15-25 min format) for offline tests.

  python factory/director/fixtures/minidoc/build.py                  # writes develop.1 / breakdown.1 / direct.1 here
  python factory/director/fixtures/minidoc/build.py --duration 1200  # the same structure at 20 minutes (to a dir)

CLEARLY SYNTHETIC: the narration cycles short per-chapter line pools; these are not recorded model responses. They
exist so the docuseries chain (story -> breakdown -> manifest -> shotplan -> episode with dual-frame shots -> shorts)
runs offline and fast. Everything is a deterministic function of (duration, chapters). The set is the Sentinel yacht
world (cloud/blender renders it), so element ids match factory/director/fixtures/sentinel and resolve to REUSE.
"""
import argparse
import copy
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SENTINEL_BD = os.path.join(HERE, "..", "sentinel", "breakdown.1.json")
FPS = 30
OFFSET = 6
WPS = 2.8          # delivery inside a line; with the 0.3 s gaps and act-break pauses the span lands at ~2.5-2.65 w/s
GAP = 0.3

HOOK = ("excited", "You are drifting onto the forbidden reef. In the dark.")
COLD = [
    ("serious", "The hull grinds on coral. Water slaps against the keel, louder every second."),
    ("whispers", "On the beach, torches move. Someone is watching you."),
    ("dramatic", "But this is not where the story starts. It starts before dusk."),
    ("serious", "You had one rule out here. Never come near this island."),
]
CHAPTERS = [
    ("The engine dies", "open_sea", "afloat_dark", [
        ("dramatic", "But the engine coughs once and stops. The silence is sudden and total."),
        ("serious", "You check the fuel. You check the battery. Nothing works."),
        ("storytelling", "The sea is calm around you, almost kind. That calm is the problem."),
        ("whispers", "No lights. No power. Only the moon on the water."),
        ("serious", "You try the radio before panic sets in. Static answers you."),
        ("dramatic", "But the current has already taken hold of the yacht."),
    ]),
    ("The current", "open_sea", "afloat_dark", [
        ("dramatic", "But the current does not drift. It pulls you toward the reef."),
        ("serious", "You brace at the rail and read the water. It is moving fast."),
        ("storytelling", "Sailors warned you about this stretch. They call it the wrong side."),
        ("whispers", "Ahead, a dark line of trees rises out of the sea."),
        ("serious", "You know that shape from the charts. You were told never to go near it."),
        ("dramatic", "But there is no anchor that can hold you here."),
    ]),
    ("The reef", "north_sentinel", "aground", [
        ("excited", "Then the keel hits the reef. The whole boat lurches sideways."),
        ("serious", "You are thrown against the helm. Your hands find the wheel."),
        ("whispers", "The hull holds. For now, the hull holds."),
        ("storytelling", "The tide is falling. Every minute, the coral rises around you."),
        ("serious", "You are stuck at the edge of an island nobody is allowed to visit."),
        ("dramatic", "But the reef is not the real danger tonight."),
    ]),
    ("The beach", "north_sentinel", "aground", [
        ("dramatic", "But then you see the fires on the beach."),
        ("whispers", "Shapes move between the trees. They are watching you."),
        ("serious", "The people here have lived alone for a very long time. They want it that way."),
        ("storytelling", "Every visitor before you was turned back. Some never left."),
        ("serious", "Your instinct says swim for help. That instinct is the mistake."),
        ("dramatic", "But staying aboard means waiting in the dark until dawn."),
    ]),
    ("The beacon", "north_sentinel", "aground", [
        ("dramatic", "But you have one thing left. The emergency beacon in the cabin."),
        ("excited", "You pull the tab and raise it over your head. The light starts to pulse."),
        ("whispers", "Now you wait. You do not shout. You do not wave at the beach."),
        ("serious", "The night crawls by you before the sky turns grey over the water."),
        ("storytelling", "Then a patrol boat appears on the horizon, slow and careful."),
    ]),
]
ANSWER = ("serious", "You survive because you never set foot on that beach.")
TEASE = ("whispers", "Next time: the sailors who did go ashore, and what they found.")
ELEMENTS = ["open_sea", "north_sentinel", "night_sky", "hdri_night", "yacht", "hero", "helm", "deck_lamp", "fires",
            "acting_rig", "face_engine", "camera_rig"]

# camera templates (house vocabulary), cycled so no preset repeats and none exceeds 1/8 of the cut
T = [
    dict(size="EWS", preset="crane_down", motivation="isolation", mark="HELM", stance="helm",
         cam=dict(rig="orbit", mark="HELM", az=[150, 160], dist=[42, 26], height=[30, 9], fov=[30, 30], ease="arrive")),
    dict(size="MS", preset="push_in", motivation="character_attention", mark="HELM", stance="helm", pose="look_down",
         cam=dict(rig="orbit", mark="HELM", az=[55, 40], dist=[3.4, 2.6], height=[0.6, 0.4], fov=[32, 30], ease="move")),
    dict(size="WS", preset="rise_overhead", motivation="reveal", mark="RAIL", stance="brace", pose="hold_rail",
         cam=dict(rig="orbit", mark="RAIL", az=[30, 60], dist=[4.0, 14.0], height=[0.6, 9.0], fov=[30, 34], ease="move")),
    dict(size="MCU", preset="orbit_arc", motivation="character_attention", mark="BOW", stance="stand", pose="look_up",
         cam=dict(rig="orbit", mark="BOW", az=[-20, -5], dist=[2.0, 1.7], height=[0.15, 0.1], fov=[30, 28], ease="move", target="face")),
    # world-space glide that frames the deck ahead of the hero: the 16:9 look is NOT the hero, so the derived 9:16
    # camera re-aims at him (the dual-frame case that matters)
    dict(size="WS", preset="lateral_glide", motivation="follow_subject", mark="HELM", stance="helm", pose="look_left",
         cam=dict(rig="path", space="world", cam=[{"frame": "world", "v": [-25, 7, -28]}, {"frame": "world", "v": [-20, 6.5, -32]}],
                  look=[{"frame": "world", "v": [4, 2.5, 4]}, {"frame": "world", "v": [4, 2.5, 4]}], fov=[30, 30], ease="move")),
    dict(size="CU", preset="slow_push", motivation="tension_push", mark="HELM", stance="helm", verb="breathe_hard",
         cam=dict(rig="orbit", mark="HELM", az=[20, 12], dist=[1.8, 1.4], height=[0.1, 0.05], fov=[30, 27], ease="move", target="face")),
    dict(size="MWS", preset="pull_back", motivation="isolation", mark="RAIL", stance="brace", pose="look_right",
         cam=dict(rig="orbit", mark="RAIL", az=[-60, -45], dist=[3.5, 6.0], height=[0.4, 1.2], fov=[30, 32], ease="move")),
    dict(size="MS", preset="arc_low", motivation="character_attention", mark="COCKPIT", stance="stand", pose="point_ahead",
         cam=dict(rig="orbit", mark="COCKPIT", az=[-70, -50], dist=[3.0, 2.6], height=[-0.2, -0.1], fov=[30, 30], ease="move")),
]
HOLD = dict(size="MCU", preset="suspense_hold", motivation="tension_push", mark="HELM", stance="helm",
            cam=dict(rig="orbit", mark="HELM", az=[35, 30], dist=[2.4, 2.1], height=[0.2, 0.15], fov=[28, 26], ease="move", target="face"))
WIDE = {"EWS", "WS"}


def nwords(text):
    return len([w for w in text.replace(":", " ").split() if any(c.isalnum() for c in w)])


def line_dur(text):
    return round(nwords(text) / WPS, 2)


# ------------------------------------------------------------------ story.json
def build_story(D=360.0, n_chapters=5, sid="minidoc"):
    if not 1 <= n_chapters <= len(CHAPTERS):
        raise ValueError(f"n_chapters must be 1-{len(CHAPTERS)}")
    chapters_src = CHAPTERS[:n_chapters]
    cold_t1 = float(round(min(90.0, max(20.0, 0.075 * D))))
    title_t1 = cold_t1 + 4.0
    ch_len = (D - title_t1) / n_chapters
    chapters = [{"id": f"CH{i + 1}", "title": src[0], "t0": round(title_t1 + i * ch_len, 2), "t1": round(title_t1 + (i + 1) * ch_len, 2)}
                for i, src in enumerate(chapters_src)]
    chapters[-1]["t1"] = D
    last = chapters[-1]
    climax_t0 = round(last["t0"] + 0.1 * (last["t1"] - last["t0"]), 2)
    tease_t0 = round(D - line_dur(TEASE[1]) - 0.6, 2)
    resolution_t0 = round(min(0.88 * D, tease_t0 - 8.0), 2)

    lines = []

    def add(tag, text, t0, **kw):
        ln = {"id": f"L{len(lines) + 1:03d}", "tag": tag, "text": text, "t0": round(t0, 2), "t1": round(t0 + line_dur(text), 2)}
        ln.update(kw)
        lines.append(ln)
        return ln["t1"] + GAP

    # cold open: hook at t=0, then the cold-open pool until the title
    t = add(*HOOK, 0.0, beat="B0")
    k = 0
    while t + line_dur(COLD[k % len(COLD)][1]) <= cold_t1:
        t = add(*COLD[k % len(COLD)], t, beat="B0", **({"rehook": True} if k == 2 else {}))
        k += 1
    # chapters: each opens on an act-break re-hook exactly at its start; lines never straddle a chapter boundary
    last_rh = 0.0
    answered = False
    for i, (c, src) in enumerate(zip(chapters, chapters_src)):
        pool = src[3]
        t = max(t, c["t0"])
        j = 0
        while True:
            tag, text = pool[j % len(pool)]
            is_last = i == n_chapters - 1
            if is_last and not answered and t >= 0.86 * D:
                tag, text = ANSWER
            if is_last and t + line_dur(text) > tease_t0 - GAP:
                break
            if not is_last and t + line_dur(text) > c["t1"]:
                break
            kw = {"beat": f"B{i + 2}", "chapter": c["id"]}
            if is_last:
                kw["beat"] = "B9" if t >= resolution_t0 else ("B8" if t >= climax_t0 else kw["beat"])
            if j == 0 or (text.startswith("But") and t - last_rh >= 100.0):
                kw["rehook"] = True
                last_rh = t
            if (tag, text) == ANSWER:
                answered = True
            t = add(tag, text, t, **kw)
            j += 1
    t = add(*TEASE, max(t, tease_t0), beat="B10", chapter=last["id"])
    answer = next(ln for ln in lines if ln["text"] == ANSWER[1])

    # short candidates: a self-contained 45-90 s run of lines inside each chapter, cut on line boundaries
    for c in chapters:
        cl = [ln for ln in lines if ln.get("chapter") == c["id"] and ln["beat"] not in ("B10",)]
        start = cl[1] if len(cl) > 2 else cl[0]
        span = min(75.0, c["t1"] - c["t0"] - 2.0)
        ends = [ln for ln in cl if ln["t1"] - start["t0"] <= span]
        end = ends[-1]
        if end["t1"] - start["t0"] < 45.0:
            start = cl[0]
            end = [ln for ln in cl if ln["t1"] - start["t0"] <= span][-1]
        src = next(s for s in chapters_src if s[0] == c["title"])
        c["spine"] = {"hook": src[3][0][1], "escalation": [src[3][1][1], src[3][3][1]], "payoff": src[3][-1][1]}
        c["short_candidate"] = {"id": f"SC{c['id'][2:]}", "in": start["t0"], "out": end["t1"],
                                "hook_line": f"Would you survive {c['title'].lower()} alone at night?",
                                "setup": src[3][1][1], "turn": src[3][0][1], "payoff": src[3][-1][1]}

    beats = [{"id": "B0", "name": "COLD_OPEN", "t0": 0.0, "t1": cold_t1, "link": None, "stakes": 7, "visual_scale": 8,
              "summary": "In medias res: the yacht on the reef, torches on the beach."},
             {"id": "B1", "name": "TITLE", "t0": cold_t1, "t1": title_t1, "link": "THEREFORE", "stakes": 6, "visual_scale": 6,
              "summary": "Title card over the dark island."}]
    for i, c in enumerate(chapters):
        beats.append({"id": f"B{i + 2}", "name": "CHAPTER", "t0": c["t0"], "t1": c["t1"], "link": "BUT" if i % 2 == 0 else "THEREFORE",
                      "stakes": round(5 + i * 0.8, 1), "visual_scale": 5 + i, "summary": c["title"], "chapter": c["id"]})
    beats += [{"id": "B8", "name": "CLIMAX", "t0": climax_t0, "t1": resolution_t0, "link": "BUT", "stakes": 9.5, "visual_scale": 9,
               "summary": "The beacon pulses while the beach watches.", "chapter": last["id"]},
              {"id": "B9", "name": "RESOLUTION", "t0": resolution_t0, "t1": tease_t0, "link": "THEREFORE", "stakes": 8, "visual_scale": 7,
               "summary": "A patrol boat at dawn; never going ashore is the answer.", "chapter": last["id"]},
              {"id": "B10", "name": "TEASE", "t0": tease_t0, "t1": D, "link": "BUT", "stakes": 7, "visual_scale": 6,
               "summary": "Tease of the next episode.", "chapter": last["id"]}]
    overrides = []
    if D < 900:
        overrides.append({"rule": "INTEGRITY.duration", "reason": "mini-doc test fixture: a 6-minute scale model of the 15-25 min docuseries format"})
    return {
        "id": sid, "format": "docuseries", "title": "The forbidden reef: one night off North Sentinel",
        "logline": "A solo sailor's yacht drifts onto the reef of the world's most isolated island at night and must survive without going ashore.",
        "essence": "Surviving the forbidden reef means never stepping onto the beach.", "style": "pixar_night_survival",
        "duration_s": D,
        "hero": {"name": "the sailor", "description": "A solo sailor on a small yacht", "flaw": "Alone, without power, and forbidden to go ashore."},
        "hook": {"format": "IMR", "line_ids": ["L001"], "text_overlay": {"text": "THE DARK REEF", "start": 0, "end": 2.5},
                 "visual": "The yacht heels on the reef at night; torches move on the beach behind the hero at the helm."},
        "core_question": {"text": "How do you survive the night without going ashore?", "answer_line": answer["id"]},
        "stakes": {"physical": "A grounded hull on a falling tide.", "legal_ethical": "Contact with the island is forbidden.",
                   "mortal": "The island's people turn every visitor back."},
        "time_pressure": False,
        "spine": {"once_upon_a_time": "A solo sailor crosses the Andaman Sea.", "every_day": "The yacht holds its course far from the island.",
                  "one_day": "The engine dies at dusk.", "because_of_that": ["Because of that, the current drags the yacht to the reef.",
                                                                              "Because of that, the sailor must wait aboard in the dark."],
                  "until_finally": "The beacon brings a patrol boat at dawn.", "ever_since": "The sailor gives the island a wide berth."},
        "beats": beats, "narration": lines, "steps": [], "facts": [],
        "suspense_devices": [{"type": "threat_reveal", "desc": "Torches on the beach in the cold open, before the story rewinds.", "beat": "B0"}],
        "attempts": [{"action": "Restart the engine.", "outcome": "fail"}, {"action": "Radio for help.", "outcome": "fail"},
                     {"action": "Raise the emergency beacon and wait aboard.", "outcome": "success"}],
        "resolution": {"hero_action": "The sailor raises the beacon and stays aboard until the patrol boat arrives.", "outcome": "Rescued at dawn."},
        "loop_back": {"method": "reverse_question", "desc": "Would you have stayed aboard?"},
        "open_loops": [{"id": "CQ", "desc": "How do you survive without going ashore?", "opened_t": 0.0, "closed_t": answer["t1"], "primary": True},
                       {"id": "OL1", "desc": "Who is watching from the beach?", "opened_t": 5.0, "closed_t": 30.0, "primary": False},
                       {"id": "OL2", "desc": "Will help come?", "opened_t": 0.4 * D, "closed_t": 0.4 * D + 20, "primary": False},
                       {"id": "OL3", "desc": "What happened to the sailors who went ashore?", "opened_t": answer["t0"], "closed_t": D, "primary": False}],
        "overrides": overrides,
        "cold_open": {"t0": 0.0, "t1": cold_t1},
        "tease_next": TEASE[1],
        "chapters": chapters,
    }


# ------------------------------------------------------------------ breakdown.json
def _location(story, ln):
    if not ln.get("chapter"):
        return "north_sentinel"
    idx = int(ln["chapter"][2:]) - 1
    return CHAPTERS[idx][1]


def build_breakdown(story):
    with open(SENTINEL_BD) as fh:
        sent = {e["id"]: e for e in json.load(fh)["elements"]}
    elements = [copy.deepcopy(sent[i]) for i in ELEMENTS]
    scenes, cur = [], None
    for ln in story["narration"]:
        loc, ch = _location(story, ln), ln.get("chapter")
        if cur is None or cur["location"] != loc or cur.get("chapter") != ch or len(cur["line_ids"]) >= 3:
            cur = {"id": f"S{len(scenes) + 1:02d}", "title": (ch or "Cold open") + f" / {loc}", "location": loc,
                   "time_of_day": "night", "weather": "clear", "line_ids": [], "picture": "", "elements": []}
            if ch:
                cur["chapter"] = ch
            scenes.append(cur)
        cur["line_ids"].append(ln["id"])
    for s in scenes:
        idx = int(s["chapter"][2:]) if s.get("chapter") else 0
        els = [s["location"], "night_sky", "hdri_night", "yacht", "hero", "helm", "deck_lamp", "acting_rig", "face_engine", "camera_rig"]
        if s["location"] == "north_sentinel" and (idx == 0 or idx >= 4):
            els.append("fires")
        s["elements"] = els
        s["picture"] = ("The yacht small on the moonlit sea, the hero on deck" if s["location"] == "open_sea"
                        else "The yacht on the reef below the dark island, the hero at the helm" + (", torches on the beach" if "fires" in els else ""))
    return {"id": story["id"], "scenes": scenes, "elements": elements}


# ------------------------------------------------------------------ shotplan.json
def _shot(i, tpl, f0, f1, scene, lines, ch, yacht, island, fires):
    c = copy.deepcopy(tpl["cam"])
    c.update(preset=tpl["preset"], motivation=tpl["motivation"])
    if c["rig"] == "orbit":
        c.setdefault("handheld", 0.15)
    hero = {"mark": tpl["mark"], "stance": tpl["stance"], "seed": 2}
    if tpl.get("pose"):
        hero["poses"] = [{"pose": tpl["pose"], "from": f0 + 4, "to": max(f0 + 12, f1 - 6), "in": 8, "out": 8}]
    if tpl.get("verb"):
        hero["verbs"] = [{"verb": tpl["verb"], "at": f0 + 8, "dur": min(36, f1 - f0 - 8)}]
    props = [{"prop": "helm", "attach": "yacht"}, {"prop": "lamp", "attach": "yacht", "light": [[0, 0.6]]}]
    s = {"id": f"D{i + 1:03d}", "title": f"{tpl['preset']} {tpl['size']}", "from": f0, "to": f1, "key_frame": (f0 + f1) // 2,
         "scene": scene, "line_ids": lines, "size": tpl["size"], "camera": c, "yacht": {"state": yacht}, "island": island,
         "hero": hero, "props": props}
    if tpl is HOLD:
        s["suspense_hold"] = True
    if ch:
        s["chapter"] = ch
    if fires:
        s["fires"] = [[f0, [1, 1, 1, 1, 0.9, 1]]]
    return s


def build_shotplan(story, bd):
    D = story["duration_s"]
    end = round(D * FPS)
    scene_of = {i: s for s in bd["scenes"] for i in s["line_ids"]}
    lines = story["narration"]
    starts = [0] + [OFFSET + round(ln["t0"] * FPS) for ln in lines[1:]] + [end]
    pieces = []          # (f0, f1, line, hold?)
    for k, ln in enumerate(lines):
        a, b = starts[k], starts[k + 1]
        if k % 3 == 2 and b - a >= 120:
            ch_first = ln.get("chapter") and not any(p[2].get("chapter") == ln["chapter"] and p[3] for p in pieces)
            cut = a + 45 if ch_first else a + (b - a) // 2
            pieces += [(a, cut, ln, bool(ch_first)), (cut, b, ln, False)]
        else:
            pieces.append((a, b, ln, False))
    shots, ti, prev_preset, seen_loc = [], 0, None, set()
    for i, (a, b, ln, hold) in enumerate(pieces):
        sc = scene_of[ln["id"]]
        loc = sc["location"]
        if hold:
            tpl = HOLD
        else:
            tpl = T[ti % len(T)]
            ti += 1
            if loc not in seen_loc and tpl["size"] not in WIDE:
                tpl = next(t for t in T if t["size"] in WIDE and t["preset"] != prev_preset)
        seen_loc.add(loc)
        if tpl["preset"] == prev_preset:
            tpl = T[ti % len(T)]
            ti += 1
        ch = ln.get("chapter")
        idx = int(ch[2:]) if ch else 0
        yacht = CHAPTERS[idx - 1][2] if ch else "aground"
        island = "near" if loc == "north_sentinel" else "far"
        shots.append(_shot(i, tpl, a, b, sc["id"], [ln["id"]], ch, yacht, island, "fires" in sc["elements"]))
        prev_preset = tpl["preset"]
    # (the 4 s title beat has no narration: it plays on the shot carrying the last cold-open line)
    for c in story["chapters"]:
        sc = c["short_candidate"]
        f0, f1 = OFFSET + round(sc["in"] * FPS), OFFSET + round(sc["out"] * FPS)
        for s in shots:
            if s["from"] < f1 and s["to"] > f0:
                s["short_candidate"] = sc["id"]
    return {"id": story["id"], "audio_offset_frames": OFFSET,
            "world": {"moonDir": [0.12, 0.3, 1], "seaState": 1.6, "dawn": 0, "island": "near"},
            "action_line": "bow-stern axis of the yacht; the island stays screen-left", "shots": shots, "overrides": []}


def build_all(D=360.0, n_chapters=5, sid="minidoc"):
    story = build_story(D, n_chapters, sid)
    bd = build_breakdown(story)
    return story, bd, build_shotplan(story, bd)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--duration", type=float, default=360.0)
    ap.add_argument("--chapters", type=int, default=5)
    ap.add_argument("--id", default="minidoc")
    ap.add_argument("--out", default=HERE)
    a = ap.parse_args(argv)
    story, bd, plan = build_all(a.duration, a.chapters, a.id)
    os.makedirs(a.out, exist_ok=True)
    for name, doc in (("develop.1.json", story), ("breakdown.1.json", bd), ("direct.1.json", plan)):
        with open(os.path.join(a.out, name), "w") as fh:
            json.dump(doc, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    with open(os.path.join(a.out, "polyhaven_search.json"), "w") as fh:
        fh.write("{}\n")
    print(f"{a.out}: {len(story['narration'])} lines, {len(bd['scenes'])} scenes, {len(plan['shots'])} shots, "
          f"{sum(1 for s in plan['shots'] if s.get('short_candidate'))} dual-frame shots, {math.ceil(a.duration)} s")


if __name__ == "__main__":
    main()
