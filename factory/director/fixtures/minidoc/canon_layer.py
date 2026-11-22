"""Film-craft canon layer for the synthetic mini-doc (factory/director/fixtures/minidoc/build.py).

Deterministic, like the rest of the fixture: given the built story / breakdown / shot plan it adds what the canon
(factory/canon/*.md) asks the director for, authored from the worked examples:
  * a narrator, a purpose + `adds` per line, reserved gaps after every line (breath / reaction / key sound), a
    three-column script, reveal order per line (CAN-N1..N4);
  * threats planted for the audience first (torches in the cold open, the reef line in chapter 2) and a knowledge
    timeline whose question pivots when the sailor learns them (CAN-S1/S2);
  * sequences with discovery maps, one reserved close-up (chapter 4: he sees the watchers and stays aboard) cut into a
    wordless reaction gap with turn-then-change, reactive impact handheld on the reef hit, establishing wides, baseline
    handheld <= 0.12 and poses out of the 10-frame bookends (CAN-C/H/P/L), and a look-dev test (CAN-T1).
"""
import copy
import re

FPS = 30
OFFSET = 6


def _words(text):
    return [w for w in re.sub(r"\[[^\]]*\]", " ", text).split() if re.search(r"\w", w)]


def _stub(ln):
    """factory/run/voice.stub_timings for one line (the offline voice)."""
    ws = _words(ln["text"])
    wt = [max(1, len(re.sub(r"\W", "", w))) + 1.5 for w in ws]
    span, tot, c, out = ln["t1"] - ln["t0"], sum(wt), ln["t0"], []
    for w, x in zip(ws, wt):
        d = span * x / tot
        out.append({"w": w, "s": c, "e": c + 0.88 * d})
        c += d
    return out


def _frame(t):
    return OFFSET + round(FPS * t)


KEY_SFX = (("keel hits", "FX:keel hits the reef"), ("engine coughs", "FX:engine coughs and stops"),
           ("Static answers", "FX:radio static"), ("light starts to pulse", "FX:beacon beep"))
PURPOSES = ["context", "momentum", "inner_state", "clarify", "bridge"]


def canonize(story, bd, plan):
    lines = story["narration"]
    ids = [ln["id"] for ln in lines]
    lmap = {ln["id"]: ln for ln in lines}
    shots = plan["shots"]
    D = story["duration_s"]
    scene_loc = {sc["id"]: sc["location"] for sc in bd["scenes"]}
    pic = {i: sc["picture"] for sc in bd["scenes"] for i in sc["line_ids"]}
    chapters = story["chapters"]

    def carrier(lid, last=True):
        cs = [s for s in shots if lid in s["line_ids"]]
        return cs[-1] if last else cs[0]

    def find(text):
        return next(ln for ln in lines if ln["text"].startswith(text))

    # ---------------- shots: handheld baseline, poses out of the bookends, a reason for every move
    for s in shots:
        cam = s["camera"]
        if cam.get("handheld", 0.12) > 0.12:
            cam["handheld"] = 0.1
        h = s.get("hero") or {}
        for q in h.get("poses", []):
            q["from"], q["to"] = s["from"] + 12, s["to"]
            q["why"] = f"{s['title']}: the line {', '.join(s['line_ids'])} moves him"
        for v in h.get("verbs", []):
            v["at"] = s["from"] + 14
            v["dur"] = max(8, min(v.get("dur", 24), s["to"] - s["from"] - 24))
            v["why"] = f"{s['title']}: fear under the line"
    # ---------------- the reserved close-up: a wordless reaction gap in chapter 4
    ch4 = chapters[3] if len(chapters) >= 4 else None
    rcu = None
    if ch4:
        c4 = [ln for ln in lines if ln.get("chapter") == ch4["id"]]
        lr = c4[1]
        nxt = lmap[ids[ids.index(lr["id"]) + 1]]
        cs = carrier(lr["id"])
        k = shots.index(cs)
        f0, f1 = _frame(lr["t1"] + 0.3), _frame(nxt["t0"]) - 6
        cs["to"] = f0
        shots[k + 1]["from"] = f1
        for q in (shots[k + 1].get("hero") or {}).get("poses", []):
            q["from"] = max(q["from"], f1 + 12)
        for q in (cs.get("hero") or {}).get("poses", []):
            q["to"] = f0
        tpl = next(x for x in shots if x["size"] == "CU")
        cam = copy.deepcopy(tpl["camera"])
        cam.update(preset="reserved_cu", motivation="character_attention", handheld=0.06)
        rcu = {"id": "R001", "title": "He sees the watchers: stays aboard", "from": f0, "to": f1, "key_frame": (f0 + f1) // 2,
               "scene": cs["scene"], "line_ids": [], "size": "CU", "camera": cam, "yacht": dict(cs["yacht"]), "island": cs["island"],
               "hero": {"mark": cam.get("mark", "HELM"), "stance": "helm", "seed": 5,
                        "poses": [{"pose": "look_left", "from": f0 + 12, "to": f1, "in": 12, "out": 8,
                                   "why": "a torch moves on the beach: he turns to it"}]},
               "props": copy.deepcopy(cs.get("props", [])), "chapter": ch4["id"],
               "turn_then_change": [{"turn": {"from": f0 + 12, "to": f0 + 24, "deg": 60}, "settle_frames": 8,
                                     "change": {"from": f0 + 32, "to": f0 + 44}, "emotion_from": "fear", "emotion_to": "resolve",
                                     "mode": "post_turn"}]}
        if cs.get("fires"):
            rcu["fires"] = [[f0, cs["fires"][0][1]]]
        sc = ch4["short_candidate"]
        if sc and _frame(sc["in"]) < f1 and _frame(sc["out"]) > f0:
            rcu["short_candidate"] = sc["id"]
        shots.insert(k + 1, rcu)
    for s in shots:
        if s["size"] in ("CU", "ECU") and s.get("hero") and s is not rcu:
            s["extra_cu_reason"] = "the breath and the face carry the line (no decision: that close-up is reserved for chapter 4)"
    # ---------------- establishing wides: the first wide of each location
    seen = set()
    for s in shots:
        loc = scene_loc.get(s["scene"])
        if loc not in seen and s["size"] in ("WS", "EWS"):
            s["establishes"] = ["hero", "vessel", "island"] if s.get("hero") else ["vessel", "island"]
            seen.add(loc)
    # ---------------- threats, impact handheld
    plant_f = find("On the beach, torches move.")
    notice_f = find("But then you see the fires")
    plant_r = find("Ahead, a dark line of trees")
    hit = find("Then the keel hits the reef.")
    ps_f, ps_r, hs = carrier(plant_f["id"], last=False), carrier(plant_r["id"], last=False), carrier(hit["id"], last=False)
    for s_, tid in ((ps_f, "T_fires"), (ps_r, "T_reef")):
        if s_.get("hero"):
            s_["gaze_away_from"] = [tid]
    hs["camera"]["motivation"] = "impact"
    hs["impact_handheld"] = {"impact_frame": max(hs["from"] + 12, _frame(hit["t0"] + 0.6)), "escape_frames": 4, "lag_frames": 5,
                             "recover_frames": 12, "amplitude_deg": 6.0}
    story["threats"] = [
        {"id": "T_fires", "desc": "torches on the beach: the islanders are watching", "planted_shot": ps_f["id"],
         "planted_t": plant_f["t0"], "noticed_shot": carrier(notice_f["id"], last=False)["id"], "noticed_at": notice_f["t0"],
         "peak_t": notice_f["t0"], "outcome": "averted", "keywords": ["torches", "fires"]},
        {"id": "T_reef", "desc": "the reef line the current carries him onto", "planted_shot": ps_r["id"], "planted_t": plant_r["t0"],
         "noticed_shot": hs["id"], "noticed_at": hit["t0"], "peak_t": hit["t0"], "outcome": "survived_with_cost", "keywords": ["reef"]},
    ]
    # ---------------- knowledge timeline
    cold_t1 = story["cold_open"]["t1"]
    bmap = {b["id"]: b for b in story["beats"]}
    b9 = next(ln for ln in lines if ln["beat"] == "B9")
    b10 = next(ln for ln in lines if ln["beat"] == "B10")
    climax0 = next(ln for ln in lines if ln["beat"] == "B8")["t0"]
    bmap["B8"].update(t0=climax0, t1=b9["t0"])
    bmap["B9"].update(t0=b9["t0"], t1=b10["t0"])
    bmap["B10"].update(t0=b10["t0"], t1=D)
    F, R_ = "T_fires", "T_reef"
    ch = {c["id"]: c for c in chapters}
    rec = [
        ("B0", 0.0, plant_f["t0"], "mystery", [], [], "character", "What is happening on this reef?"),
        ("B0", plant_f["t0"], cold_t1, "dramatic_irony", [F], [], "character", "Will he see who is watching from the beach?"),
        ("B1", cold_t1, ch["CH1"]["t0"], "dramatic_irony", [F], [], "character", "How will a calm evening end up here?"),
        ("B2", ch["CH1"]["t0"], ch["CH1"]["t1"], "dramatic_irony", [F], [], "character", "Can he restart the engine before dark?"),
        ("B3", ch["CH2"]["t0"], plant_r["t0"], "dramatic_irony", [F], [], "nobody", "Where will the current take him?"),
        ("B3", plant_r["t0"], ch["CH2"]["t1"], "dramatic_irony", [F, R_], [], "nobody", "Will he see the reef before he hits it?"),
        ("B4", ch["CH3"]["t0"], hit["t0"], "dramatic_irony", [F, R_], [], "nobody", "Can anything hold him off the reef?"),
        ("B4", hit["t0"], ch["CH3"]["t1"], "dramatic_irony", [F, R_], [R_], "character", "Will the hull hold on the falling tide?"),
        ("B5", ch["CH4"]["t0"], notice_f["t0"], "dramatic_irony", [F, R_], [R_], "character", "Will he see the fires before he swims?"),
        ("B5", notice_f["t0"], ch["CH4"]["t1"], "shared", [F, R_], [F, R_], "character", "Can he stay aboard until dawn?", True),
        ("B6", ch["CH5"]["t0"], climax0, "shared", [F, R_], [F, R_], "character", "Will the beacon bring help before the beach acts?"),
        ("B8", climax0, b9["t0"], "shared", [F, R_], [F, R_], "character", "Can he keep still while they watch?"),
        ("B9", b9["t0"], b10["t0"], "relief", [F, R_], [F, R_], "character", "Will he ever come back here?"),
        ("B10", b10["t0"], D, "mystery", [F, R_], [F, R_], "character", "What did the sailors who went ashore find?"),
    ]
    kt = []
    for r in rec:
        d = {"beat": r[0], "t0": round(r[1], 3), "t1": round(r[2], 3), "mode": r[3], "audience_knows": r[4], "character_knows": r[5],
             "withheld_from_audience": [], "who_can_act": r[6], "audience_question": r[7],
             "threat_planted_shot": {1: ps_f["id"], 5: ps_r["id"]}.get(len(kt))}
        if len(r) > 8 and r[8]:
            d["decision"] = True
        kt.append(d)
    # docuseries: the question or mode changes at least every 180 s (CAN-S2d) -- long chapters get a second question
    out = []
    for d in kt:
        n = max(1, int((d["t1"] - d["t0"]) // 150) + (1 if (d["t1"] - d["t0"]) % 150 > 1e-6 and d["t1"] - d["t0"] > 150 else 0))
        step = (d["t1"] - d["t0"]) / n
        for i in range(n):
            e = dict(d, t0=round(d["t0"] + i * step, 3), t1=round(d["t0"] + (i + 1) * step, 3))
            if i:
                e["audience_question"] = d["audience_question"].rstrip("?") + (", and how long can he wait?" if i % 2 else ", before dawn?")
                e["threat_planted_shot"] = None
                e.pop("decision", None)
            out.append(e)
    kt = out
    story["knowledge_timeline"] = kt
    # ---------------- narrator, purposes, gaps, reveal order, three columns
    story["narrator"] = {"person": "second", "persona": "a measured documentary narrator who has sailed these waters",
                         "authority": "the incident record of the island and the coast guard's guidance", "knowledge_scope": "omniscient",
                         "voice_id": "VMCgCMbBs53ElBxVD4VB", "direction": "documentary register; leave the gaps to the sea"}
    gaps = []
    for k, ln in enumerate(lines):
        ln["purpose"] = "setup" if k == 0 else ("resolution" if ln["beat"] in ("B9", "B10") else PURPOSES[k % len(PURPOSES)])
        ln["adds"] = "what the sailor knows, fears or decides: the picture shows only the boat and the night"
        nxt = lines[k + 1] if k + 1 < len(lines) else None
        real = (nxt["t0"] - ln["t1"]) if nxt else min(0.6, D - ln["t1"])
        fx = next((f for key, f in KEY_SFX if key in ln["text"]), None)
        purpose = "key_sfx" if fx else ("reaction" if nxt and (k % 3 == 2 or real >= 2.0) else "breath")
        gaps.append({"id": f"G{k + 1:03d}", "after_line": ln["id"], "start_s": ln["t1"], "len_s": round(real - 0.004, 2) if nxt else 0.6,
                     "purpose": purpose, "filled_by": fx or "room_tone",
                     "desc": "the sea and the boat carry the pause" if not fx else fx[3:]})
    story["narration_gaps"] = gaps
    by = {s["id"]: s for s in shots}
    for ln in lines:
        ws = _stub(ln)
        k = max(range(len(ws)), key=lambda i: len(re.sub(r"\W", "", ws[i]["w"])))
        kf = round(ws[k]["s"] * FPS) + OFFSET
        sh = next(s for s in shots if s["from"] <= kf < s["to"])
        if sh["from"] <= kf - 15:
            rf, order = kf - 15, "after"
        else:
            rf, order = kf, "on"
        ln["reveal_order"] = {"key_word_idx": k, "reveal_shot": sh["id"], "reveal_frame": rf, "order": order}
    rows = []
    for ln in lines:
        b = bmap[ln["beat"]]
        rows.append({"row_id": f"R{ln['id']}", "beat": ln["beat"], "t0": ln["t0"], "t1": ln["t1"], "picture": pic[ln["id"]],
                     "narration": ln["text"], "sound": "AMB: night sea, wind in the rigging; FX: hull creaks", "line_ids": [ln["id"]],
                     "gap_id": None})
        g = next(x for x in gaps if x["after_line"] == ln["id"])
        t1 = round(min(g["start_s"] + g["len_s"], b["t1"], D), 3)
        if t1 - g["start_s"] > 0.05:
            rows.append({"row_id": f"R{g['id']}", "beat": ln["beat"], "t0": g["start_s"], "t1": t1, "picture": g["desc"], "narration": "",
                         "sound": f"AMB: night sea; {g['filled_by'] if g['filled_by'].startswith('FX:') else 'AMB: room tone'} @gap:{g['id']}",
                         "line_ids": [], "gap_id": g["id"]})
    tb = bmap["B1"]
    rows.append({"row_id": "RTITLE", "beat": "B1", "t0": tb["t0"], "t1": tb["t1"], "picture": "Title card over the dark island",
                 "narration": "", "sound": "AMB: night sea; MUSIC: title sting", "line_ids": [], "gap_id": None})
    story["script_columns"] = sorted(rows, key=lambda r: (r["t0"], r["row_id"]))
    # ---------------- sequences + discovery maps + look-dev
    groups = [("SQ0", None, "plateau")] + [(f"SQ{c['id'][2:]}", c["id"], "release" if c is chapters[-1] else "plateau") for c in chapters]
    seqs = []
    for sid, cid, tension in groups:
        sh = [s for s in shots if s.get("chapter") == cid]
        if not sh:
            continue
        cand = next(s for s in sh if s["to"] - s["from"] >= 50 and s is not rcu)
        src = {None: ("fire", "practical_pool"), "CH4": ("fire", "practical_pool"), "CH5": ("practical:epirb_strobe", "glint"),
               "CH3": ("moon", "reflection")}.get(cid, ("moon", "glint"))
        seqs.append({"id": sid, "beats": sorted({lmap[i]["beat"] for s in sh for i in s["line_ids"]}), "shots": [s["id"] for s in sh],
                     "tension": tension, "action": False,
                     "reserved_close_up": {"beat": "B5", "shot": rcu["id"], "reason": "decision: he sees the watchers and stays aboard"}
                     if (rcu and cid == (ch4 or {}).get("id")) else None,
                     "discovery_map": [{"detail": "torches on the beach" if src[0] == "fire" else "the water around the hull",
                                        "shot": cand["id"], "frame": cand["from"] + 30, "light_reveal": {"source": src[0], "kind": src[1]},
                                        "subordinate": ["the tree line stays dark"]}],
                     "action_order": None})
    plan["sequences"] = seqs
    plan["lookdev_test"] = {"view": "deck", "elements": ["boat", "one_practical", "water"], "practical": "deck lamp",
                            "lighting_preset": "moonlight_practical_mix", "water_material": "oceanfx_night", "hull_material": "yacht_v2"}
    return story, bd, plan
