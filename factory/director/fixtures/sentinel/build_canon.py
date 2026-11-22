"""Build the canon-compliant Sentinel fixture attempts from the legacy recorded ones.

    python3 factory/director/fixtures/sentinel/build_canon.py      # writes develop.3.json + direct.2.json

develop.2.json / direct.1.json are the recorded pre-canon responses (they still pass the legacy checklists and the
compiled-episode = episode_v2 test). The director's retry loop now also enforces the film-craft canon
(factory/canon/checks.py), so the offline chain replays them, gets canon feedback, and is answered by the attempts
built here: the same film re-directed by the canon worked examples (factory/canon/VISUAL_CANON.md 8.1 and
STORY_SOUND_CANON.md worked example 1):

  * reserved narration gaps (CAN-N2b): the planned pauses are widened (one insert per gap, frames re-timed), the narration
    rewritten where a sentence ran over 14 words (CAN-N4f), and a 2.9 s reaction gap holds the ONE reserved close-up:
    "he hears drums inland and stays aboard" (CAN-C2, S06 of the worked example);
  * threats planted for the audience first (reef: A07, fires: A08) with a knowledge timeline (CAN-S1/S2);
  * sequences with discovery maps, the reef action order A07 > A09 > B10 > B11 and reactive impact handheld on B10
    (CAN-E1/H1/L1), turn-then-change on the reserved CU, pose onsets out of the 10-frame bookends (CAN-P1);
  * a look-dev test (boat + stern deck lamp + water, CAN-T1).
The rewritten script no longer matches the recorded Sentinel take, so the offline voice stage uses the stub narration
(factory/run/voice.py only reuses a reference take that voices exactly this script).
"""
import copy
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FPS, OFF = 30, 15

TEXT = {  # CAN-N4f: no sentence over 14 words; CAN-N4e: no value judgement without evidence
    "L01": "Alone on a yacht, at night. And your engine just DIED.",
    "L03": "And the current drags you toward one island. The ONE place on Earth you can't touch.",
    "L05": "The people here have refused contact with outsiders for thousands of years. And they defend that. Hard.",
    "L12": "In 1981, a cargo ship called the Primrose ran aground right here. The crew saw armed islanders "
           "on the beach. So they stayed inside their steel hull for days. Until helicopters lifted every one of them out.",
    "L15": "On North Sentinel, the only way to survive is to never be there.",
}
# id, after_line, wanted length (s), purpose, filled_by, desc, insert time (audio s; default the pause midpoint)
GAPS = [
    ("G1", "L01", 0.80, "key_sfx", "FX:engine sputters and dies", "the engine coughs twice and stops", None),
    ("G2", "L02", 0.90, "key_sfx", "FX:a wave slaps the dead hull", "the silence of a dead boat: one wave on the hull", None),
    ("G3", "L04", 1.00, "reaction", "room_tone", "the fires light in the trees while nobody speaks", None),
    ("G4", "L06", 1.10, "key_sfx", "FX:hull grinds on the coral", "the hull grinds and settles on the reef", None),
    ("GR", "L08", 2.88, "reaction", "room_tone", "drums inland under the surf: the reserved close-up (he decides to stay)", 35.70),
    ("G5", "L09", 1.00, "reaction", "room_tone", "he lowers the phone", None),
    ("G6", "L11", 1.00, "key_sfx", "FX:thunder rolls over the reef", "the 1981 storm arrives before the words", None),
    ("G7", "L12", 0.60, "breath", "room_tone", "breath before step four", None),
    ("G8", "L14", 1.00, "reaction", "room_tone", "the tide lifts him; score and sea drop out before the thesis (P-5)", None),
    ("G9", "L15", 0.80, "breath", "room_tone", "tail room before the end card", None),
]
POSE_EDITS = {  # CAN-P1c: no onset/release in the first or last 10 frames (original frames, before re-timing)
    ("A04", "press_ahead"): {"from": 168, "to": 241}, ("A05", "hold_rail"): {"from": 251},
    ("A05", "look_right"): {"to": 330}, ("A09", "rail_ahead"): {"from": 570},
    ("C15", "beacon_pull"): {"from": 950, "to": 966}, ("C15", "beacon_raise"): {"from": 970},
    ("C17", "rail_ahead"): {"from": 1096}, ("C18", "phone_up"): {"from": 1180},
    ("C28", "shush"): {"from": 2005}, ("C29", "tie_bag"): {"from": 2040},
}
MATCH_ACTION = {"A06", "C14", "C16"}       # the pose continues across the cut from the previous shot
EXTRA_CU = {
    "A04": "the hand on the dead switch and the moonlit face are one image: the power is gone (no decision here)",
    "B12": "direct address: he looks into the lens to ask the step question (series format), not a reaction beat",
    "C27": "the instruction is the image: his face goes dark with the last lamp",
    "C28": "finger to lips: the gesture is step four itself",
}
ESTABLISHES = {"A01": ["hero", "vessel", "open_sea"], "A07": ["vessel", "island", "reef"],
               "B10": ["hero", "vessel", "threat"], "D23": ["vessel", "island", "beach"]}
REVEAL = {  # line -> (key word, reveal shot)
    "L01": ("DIED.", "A03"), "L02": ("power.", "A04"), "L03": ("island.", "A06"), "L04": ("Island!", "A07"),
    "L05": ("contact", "A08"), "L06": ("crunch.", "B10"), "L07": ("do?", "B12"), "L08": ("radio,", "C13"),
    "L09": ("ashore.", "C17"), "L10": ("germs.", "C19"), "L11": ("boat.", "C21"), "L12": ("Primrose", "D23"),
    "L13": ("lights.", "C27"), "L14": ("tide", "E30"), "L15": ("survive", "E32"),
}
PURPOSE = {
    "L01": ("setup", "the engine failure and that you are alone: the picture only shows a calm, lit yacht"),
    "L02": ("clarify", "the boat has no power at all, not just a dead engine"),
    "L03": ("context", "the current, and that this island is forbidden"),
    "L04": ("authenticity", "the real name of the island"),
    "L05": ("context", "who lives there and that they refuse contact"),
    "L06": ("momentum", "you are stuck: the hull will not come off"),
    "L07": ("bridge", "turns the situation into steps"),
    "L08": ("step", "the radio channel, the beacon, and that the Coast Guard patrols here"),
    "L09": ("step", "the rule not to land and the temptations to refuse"),
    "L10": ("context", "why: their immunity, which no picture can show"),
    "L11": ("step", "stay aboard, and that it has happened before"),
    "L12": ("authenticity", "the 1981 Primrose precedent: the crew stayed and lived"),
    "L13": ("step", "dark, quiet, no trace"),
    "L14": ("step", "how to leave when the tide lifts you"),
    "L15": ("resolution", "the thesis: the only safe choice is never to go"),
}
SEQS = [  # id, shots, tension, action, reserved CU, discoveries [(detail, shot, frame offset into shot, source, kind)]
    ("SQ1", ["A01", "A02", "A03", "A04"], "plateau", False, None,
     [("the cabin lights die", "A04", 62, "practical:cabin_lamp", "practical_pool")]),
    ("SQ2", ["A05", "A06", "A07"], "mounting", False, None,
     [("the reef breakers ahead of the drift", "A07", 25, "moon", "glint")]),
    ("SQ3", ["A08", "A09", "B10", "B11"], "mounting", True, None,
     [("fires lighting in the trees", "A08", 40, "fire", "practical_pool"),
      ("the hull pinned on the coral", "B11", 45, "moon", "reflection")]),
    ("SQ4", ["B12", "C13", "C14", "C15", "C16"], "plateau", False, None,
     [("the EPIRB strobe", "C15", 50, "practical:epirb_strobe", "glint")]),
    ("SQ5", ["R16", "C17", "C18"], "plateau", False, {"beat": "B3", "shot": "R16", "reason": "decision: he hears drums inland and stays aboard"},
     [("the fires inland from the bow", "C17", 60, "fire", "practical_pool")]),
    ("SQ6", ["C19", "C20", "C21", "C22"], "plateau", False, None,
     [("the protected-zone ring on the water", "C19", 50, "moon", "rim")]),
    ("SQ7", ["D23", "D24", "D25", "D26"], "plateau", False, None,
     [("torches on the Primrose beach", "D24", 30, "fire", "practical_pool")]),
    ("SQ8", ["C27", "C28", "C29"], "release", False, None,
     [("the last lamp goes out", "C27", 47, "practical:deck_lamp", "practical_pool")]),
    ("SQ9", ["E30", "E31", "E32", "E33"], "release", False, None,
     [("water rising up the hull", "E30", 34, "moon", "reflection")]),
]
# knowledge timeline in ORIGINAL audio seconds (re-timed below)
KT = [
    ("B1", 0.0, 4.48, "shared", [], [], "character", "Can he get the engine back?", None, False),
    ("B2", 4.48, 7.54, "shared", [], [], "nobody", "Where will a dead boat drift tonight?", None, False),
    ("B3", 7.54, 12.97, "mystery", [], [], "nobody", "Where will the current carry him?", None, False),
    ("B3", 12.97, 14.67, "dramatic_irony", ["T_reef"], [], "nobody", "Will he see the reef before he hits it?", "A07", False),
    ("B3", 14.67, 20.70, "dramatic_irony", ["T_reef", "T_fires"], [], "nobody", "Will he notice the fires in the trees?", "A08", False),
    ("B3", 20.70, 22.64, "dramatic_irony", ["T_reef", "T_fires"], ["T_fires"], "character", "Can he back away before the reef stops him?", None, False),
    ("B3", 22.64, 25.72, "shared", ["T_reef", "T_fires"], ["T_reef", "T_fires"], "character", "Will the hull hold on the coral?", None, False),
    ("B3", 25.72, 35.24, "shared", ["T_reef", "T_fires"], ["T_reef", "T_fires"], "character", "Will anyone hear the Mayday in time?", None, False),
    ("B3", 35.24, 35.72, "shared", ["T_reef", "T_fires"], ["T_reef", "T_fires"], "character", "Will he go ashore where the fires burn?", None, True),
    ("B4", 35.72, 40.70, "shared", ["T_reef", "T_fires"], ["T_reef", "T_fires"], "character", "Can he stay unseen until help comes?", None, False),
    ("B5", 40.70, 49.88, "shared", ["T_reef", "T_fires"], ["T_reef", "T_fires"], "character", "Will his germs reach them?", None, False),
    ("B5", 49.88, 56.00, "shared", ["T_reef", "T_fires"], ["T_reef", "T_fires"], "character", "How long can a crew wait in a steel hull?", None, False),
    ("B5", 56.00, 63.46, "shared", ["T_reef", "T_fires"], ["T_reef", "T_fires"], "character", "Will the helicopters come before the islanders do?", None, False),
    ("B5", 63.46, 68.70, "shared", ["T_reef", "T_fires"], ["T_reef", "T_fires"], "character", "Can he stay dark and quiet all night?", None, False),
    ("B6", 68.70, 72.84, "relief", ["T_reef", "T_fires"], ["T_reef", "T_fires"], "character", "Will the tide lift him off in time?", None, False),
    ("B7", 72.84, None, "relief", ["T_reef", "T_fires"], ["T_reef", "T_fires"], "character", "Would you ever go back?", None, False),
]


def load(n):
    with open(os.path.join(HERE, n)) as fh:
        return json.load(fh)


def words(text):
    import re
    return [w for w in re.sub(r"\[[^\]]*\]", " ", text).split() if re.search(r"\w", w)]


def stub_timing(ln):
    """Same as factory/run/voice.stub_timings for one line (the offline voice)."""
    import re
    ws = words(ln["text"])
    weights = [max(1, len(re.sub(r"\W", "", w))) + 1.5 for w in ws]
    span, tot, c, out = ln["t1"] - ln["t0"], sum(weights), ln["t0"], []
    for w, wt in zip(ws, weights):
        d = span * wt / tot
        out.append({"w": w, "s": round(c, 3), "e": round(c + d * 0.88, 3)})
        c += d
    return out


def main():
    story, plan = load("develop.2.json"), load("direct.1.json")
    lines = story["narration"]
    lmap = {ln["id"]: ln for ln in lines}
    ids = [ln["id"] for ln in lines]
    # ---- inserts (seconds and frames kept exactly equal: n frames = n/30 s)
    inserts, gaps = [], []
    for gid, after, want, purpose, fill, desc, at in GAPS:
        ln = lmap[after]
        i = ids.index(after)
        nxt = lmap[ids[i + 1]] if i + 1 < len(ids) else None
        natural = (nxt["t0"] - ln["t1"]) if nxt else 0.0
        n = max(0, math.ceil((want - natural) * FPS - 1e-9)) if nxt else 0
        t_k = at if at is not None else (ln["t1"] + (nxt["t0"] if nxt else ln["t1"])) / 2
        if n:
            inserts.append((t_k, n))
        gaps.append({"id": gid, "after_line": after, "len_s": round(natural + n / FPS - 0.004, 2) if nxt else want,
                     "purpose": purpose, "filled_by": fill, "desc": desc, "_t": ln["t1"]})

    def st(t):
        return round(t + sum(n / FPS for tk, n in inserts if tk < t - 1e-9), 3)

    def sf(f):
        return int(f + sum(n for tk, n in inserts if OFF + round(FPS * tk) < f))

    # ---- story
    s = copy.deepcopy(story)
    D = round(story["duration_s"] + sum(n for _, n in inserts) / FPS, 2)
    s["duration_s"] = D
    for ln in s["narration"]:
        ln["text"] = TEXT.get(ln["id"], ln["text"])
        ln["t0"], ln["t1"] = st(ln["t0"]), st(ln["t1"])
        ln["purpose"], ln["adds"] = PURPOSE[ln["id"]]
    s["hook"]["text_overlay"]["end"] = min(s["hook"]["text_overlay"]["end"], 3.0)
    nl = {ln["id"]: ln for ln in s["narration"]}
    for g in gaps:
        g.pop("_t")
        g["start_s"] = nl[g["after_line"]]["t1"]
    s["narration_gaps"] = gaps
    # beats: each beat closes at the next beat's first line (its gap belongs to the beat it ends)
    firsts = {}
    for ln in s["narration"]:
        firsts.setdefault(ln["beat"], ln["t0"])
    for k, b in enumerate(s["beats"]):
        b["t0"] = 0.0 if k == 0 else firsts[b["id"]]
    for a, b in zip(s["beats"], s["beats"][1:]):
        a["t1"] = b["t0"]
    s["beats"][-1]["t1"] = D
    for lp in s["open_loops"]:
        lp["opened_t"], lp["closed_t"] = st(lp["opened_t"]), st(lp["closed_t"])
    s["narrator"] = {"person": "second", "persona": "a calm survival instructor who has read the incident reports",
                     "authority": "the Primrose 1981 record and the Indian Coast Guard guidance; speaks to you as the sailor",
                     "knowledge_scope": "omniscient", "voice_id": "467tX2b9Bky3cD6jXpNa",
                     "direction": "warm, low, unhurried; stop talking in the gaps and let the sound carry them"}
    s["threats"] = [
        {"id": "T_reef", "desc": "the reef line the current is carrying him onto", "planted_shot": "A07", "planted_t": st(12.97),
         "noticed_shot": "B10", "noticed_at": st(22.64), "peak_t": st(22.64), "outcome": "survived_with_cost",
         "keywords": ["reef", "coral"]},
        {"id": "T_fires", "desc": "fires lighting in the trees: the islanders are awake", "planted_shot": "A08", "planted_t": st(14.67),
         "noticed_shot": "A09", "noticed_at": st(20.70), "peak_t": st(35.50), "outcome": "averted",
         "keywords": ["fires", "islanders", "torches"]},
    ]
    kt = []
    for beat, t0, t1, mode, A, C, who, q, tps, dec in KT:
        r = {"beat": beat, "t0": st(t0), "t1": D if t1 is None else st(t1), "mode": mode, "audience_knows": A,
             "character_knows": C, "withheld_from_audience": [], "who_can_act": who, "audience_question": q,
             "threat_planted_shot": tps}
        if dec:
            r["decision"] = True
        kt.append(r)
    kt[0]["t0"] = 0.0
    s["knowledge_timeline"] = kt
    # ---- shot plan
    p = copy.deepcopy(plan)
    for sh in p["shots"]:
        h = sh.get("hero") or {}
        for q in h.get("poses", []):
            q.update(POSE_EDITS.get((sh["id"], q["pose"]), {}))
    for sh in p["shots"]:
        sh["from"], sh["to"] = sf(sh["from"]), sf(sh["to"])
        if "key_frame" in sh:
            sh["key_frame"] = min(sh["to"] - 1, max(sh["from"], sf(sh["key_frame"])))
        h = sh.get("hero") or {}
        for q in h.get("poses", []):
            q["from"], q["to"] = sf(q["from"]), sf(q["to"])
        for v in h.get("verbs", []):
            v["at"] = sf(v["at"])
        h["stance_changes"] = [[sf(f), x] for f, x in h.get("stance_changes", [])] if h.get("stance_changes") else h.get("stance_changes")
        if h and h.get("stance_changes") is None:
            h.pop("stance_changes", None)
        if sh.get("fires"):
            sh["fires"] = [[sf(f), v] for f, v in sh["fires"]]
        y = sh["yacht"]
        if "hit_frame" in y:
            y["hit_frame"] = sf(y["hit_frame"])
        if y.get("lights"):
            y["lights"] = [[sf(f), v] for f, v in y["lights"]]
        for pr in sh.get("props", []):
            for k in ("light", "show"):
                if pr.get(k):
                    pr[k] = [[sf(f), v] for f, v in pr[k]]
            if "strobe" in pr:
                pr["strobe"] = sf(pr["strobe"])
        cam = sh["camera"]
        for k in cam.get("shakes", []):
            k["at"] = sf(k["at"])
        if cam.get("handheld", 0) > 0.12:
            cam["handheld"] = 0.1                       # CAN-H1e: no decorative baseline shake
        for q in h.get("poses", []):
            q["why"] = f"{sh['title']}: {', '.join(sh['line_ids']) or 'picture'} motivates the {q['pose'].replace('_', ' ')}"
        for v in h.get("verbs", []):
            v["why"] = f"{sh['title']}: the {v['verb'].replace('_', ' ')} answers the beat"
        if sh["id"] in MATCH_ACTION:
            sh["match_action"] = True
        if sh["id"] in EXTRA_CU:
            sh["extra_cu_reason"] = EXTRA_CU[sh["id"]]
        if sh["id"] in ESTABLISHES:
            sh["establishes"] = ESTABLISHES[sh["id"]]
    sm = {sh["id"]: sh for sh in p["shots"]}
    sm["C19"]["camera"].update(dist=[7.5, 6.5], height=[0.4, 0.6])   # a real WS (it was framed MS: 7 tight shots in a row, C4)
    sm["A03"]["camera"]["motivation"] = "tension_push"   # the engine dying is not a physical hit (no impact layer)
    b10 = sm["B10"]
    b10["impact_handheld"] = {"impact_frame": b10["yacht"]["hit_frame"], "escape_frames": 4, "lag_frames": 5,
                              "recover_frames": 12, "amplitude_deg": 6.0}
    # ---- the reserved close-up R16: the first 60 frames of the reaction-gap insert in front of C17
    c17 = sm["C17"]
    fr = c17["from"]
    c17["from"] = fr + 60
    c17["key_frame"] = c17["from"] + 40
    for q in c17["hero"].get("poses", []):
        q["from"] += 60
    for v in c17["hero"].get("verbs", []):
        v["at"] += 60
    c17["fires"] = [[c17["from"], c17["fires"][0][1]]]
    b12 = sm["B12"]
    r16 = {"id": "R16", "title": "He hears drums inland: stays aboard", "from": fr, "to": fr + 60, "key_frame": fr + 40,
           "scene": "S07", "line_ids": [], "size": "CU",
           "camera": {"preset": "push_in", "motivation": "character_attention", "rig": "orbit", "mark": "BOW", "az": [10, 2],
                      "dist": list(b12["camera"]["dist"]), "height": list(b12["camera"]["height"]), "fov": [28, 25], "ease": "arrive",
                      "target": "face", "handheld": 0.06},
           "yacht": {"state": "aground"}, "island": "near", "fires": [[fr, c17["fires"][0][1]]],
           "hero": {"mark": "BOW", "stance": "stand",
                    "poses": [{"pose": "look_left", "from": fr + 12, "to": fr + 60, "in": 12, "out": 10, "ease": "smooth",
                               "why": "a drum inland: he turns toward the trees"}],
                    "verbs": [], "breath": 1.4, "seed": 9, "emotion": "curious"},
           "turn_then_change": [{"turn": {"from": fr + 12, "to": fr + 24, "deg": 70}, "settle_frames": 8,
                                 "change": {"from": fr + 32, "to": fr + 44}, "emotion_from": "curious", "emotion_to": "resolve",
                                 "mode": "post_turn"}]}
    p["shots"].insert([sh["id"] for sh in p["shots"]].index("C17"), r16)
    sm = {sh["id"]: sh for sh in p["shots"]}
    seqs = []
    for sid, shots, tension, action, rc, disc in SEQS:
        q = {"id": sid, "beats": sorted({nl[i]["beat"] for x in shots for i in sm[x]["line_ids"]}), "shots": shots,
             "tension": tension, "action": action, "reserved_close_up": rc,
             "discovery_map": [{"detail": d, "shot": sh, "frame": sm[sh]["from"] + off,
                                "light_reveal": {"source": src, "kind": kind}, "subordinate": ["the forest stays dark"]}
                               for d, sh, off, src, kind in disc],
             "action_order": None}
        if action:
            q["action_order"] = {"obstacle_audience": "A07", "obstacle_character": "A09", "impact": "B10", "cost_revealed": "B11"}
        seqs.append(q)
    p["sequences"] = seqs
    p["lookdev_test"] = {"view": "hull", "elements": ["boat", "one_practical", "water"], "practical": "stern deck lamp",
                         "lighting_preset": "moonlight_practical_mix", "water_material": "oceanfx_night", "hull_material": "yacht_v2"}
    # ---- reveal order per line, from the offline (stub) word timings and the re-timed cut
    for ln in s["narration"]:
        kw, shot = REVEAL[ln["id"]]
        ws = stub_timing(ln)
        k = next(i for i, w in enumerate(ws) if w["w"] == kw)
        kf = (ws[k]["s"] * FPS) + OFF                           # key word, film frames
        sh = sm[shot]
        rf = int(round(kf))
        if sh["from"] <= rf - 15 < sh["to"]:
            rf, order = rf - 15, "after"                        # the picture shows it 0.5 s before the word names it
        elif sh["from"] <= rf + 15 < sh["to"]:
            rf, order = rf + 15, "before"                       # the word primes, the picture pays off 0.5 s later
        else:
            sh = next(x for x in p["shots"] if x["from"] <= rf < x["to"])
            order = "on"
        ln["reveal_order"] = {"key_word_idx": k, "reveal_shot": sh["id"], "reveal_frame": rf, "order": order}
    # ---- three-column script: a row per line + a sound-only row per gap
    bd = load("breakdown.1.json")
    pic = {i: sc["picture"] for sc in bd["scenes"] for i in sc["line_ids"]}
    fx = {"L06": "FX: coral crunch @lead", "L08": "FX: VHF squelch, EPIRB beeps", "L12": "FX: storm rain, helicopter",
          "L13": "FX: switch click", "L14": "MUSIC: tide theme"}
    rows = []
    for ln in s["narration"]:
        rows.append({"row_id": f"R{ln['id']}", "beat": ln["beat"], "t0": ln["t0"], "t1": ln["t1"], "picture": pic[ln["id"]],
                     "narration": ln["text"], "sound": "AMB: night swell, sea wind; " + fx.get(ln["id"], "FX: none"),
                     "line_ids": [ln["id"]], "gap_id": None})
        for g in gaps:
            if g["after_line"] == ln["id"]:
                t1 = round(min(g["start_s"] + g["len_s"], D), 3)
                rows.append({"row_id": f"R{g['id']}", "beat": ln["beat"], "t0": g["start_s"], "t1": t1,
                             "picture": g["desc"], "narration": "",
                             "sound": f"AMB: night swell, sea wind; {g['filled_by'] if g['filled_by'].startswith('FX:') else 'AMB: room tone'} @gap:{g['id']}",
                             "line_ids": [], "gap_id": g["id"]})
    s["script_columns"] = rows
    # legacy checklist overrides the canon re-timing costs (logged, honest)
    extra = [
        {"rule": "N-1", "reason": "Canon CAN-N2: the reserved narration gaps (7.6 s in total) lower the words/s over the span; "
                                  "the lines themselves still play at 2.6-3.0 w/s."},
        {"rule": "N-1-budget", "reason": "Canon CAN-N2f thins the narration so it does not lead the picture: fewer words than "
                                         "2.83 x D by design, the gaps carry key sounds and the reserved close-up."},
        {"rule": "H-7", "reason": "The hook keeps the recorded rhythm; its first sentence is 6 words."},
        {"rule": "R-beats-window", "reason": "Beats close on the next beat's first line so each gap stays in the beat it ends (canon CAN-N1)."},
        {"rule": "N-2", "reason": "Canon CAN-N4f caps sentences at 14 words; the staccato fragments stay."},
    ]
    have = {o["rule"] for o in s["overrides"]}
    s["overrides"] += [o for o in extra if o["rule"] not in have]
    p["overrides"] += [{"rule": "C9", "reason": "The reserved close-up and the gap-widened shots move the median; no shot is under 18 f or over 6 s."}]
    with open(os.path.join(HERE, "develop.3.json"), "w") as fh:
        json.dump(s, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    with open(os.path.join(HERE, "direct.2.json"), "w") as fh:
        json.dump(p, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"develop.3.json: D {D} s, {len(gaps)} gaps, {len(inserts)} inserts ({sum(n for _, n in inserts)} f); "
          f"direct.2.json: {len(p['shots'])} shots, {len(seqs)} sequences, ends {p['shots'][-1]['to']}")


if __name__ == "__main__":
    main()
