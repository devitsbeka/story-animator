"""Synthetic docuseries story.json for validator tests (clearly synthetic: repeated lines, not a recorded response).
20 minutes, cold open + 5 chapters, each chapter with a 60 s short_candidate."""

POOL = [
    ("serious", "You wait in silence. The water keeps rising slowly around the steel hull.", False),
    ("dramatic", "But you hold on. Nobody leaves the ship until the storm fully breaks.", True),
    ("storytelling", "You hear the drums. The fires on the beach burn brighter every hour.", False),
    ("whispers", "The radio crackles again. Help is only days away from your position tonight.", False),
    ("serious", "You count the hours. Every one feels longer than the last one did.", False),
]


def make_docuseries(D=1200.0, n_chapters=5):
    cold = 80.0
    lines, t, k = [], 0.0, 1
    hook = "You are trapped on a sinking ship. Nobody is coming."
    lines.append({"id": "L001", "beat": "B0", "tag": "excited", "text": hook, "t0": 0.0, "t1": 3.6})
    t = 4.0
    ch_len = (D - cold) / n_chapters
    chapters, beats = [], [{"id": "B0", "name": "COLD_OPEN", "t0": 0.0, "t1": cold, "link": None, "stakes": 6, "visual_scale": 7,
                            "summary": "Cold open at the peak of danger."}]
    for c in range(n_chapters):
        c0, c1 = cold + c * ch_len, cold + (c + 1) * ch_len
        chapters.append({"id": f"CH{c + 1}", "title": f"Chapter {c + 1}", "t0": c0, "t1": c1,
                         "spine": {"hook": "A new danger appears.", "escalation": ["It gets worse.", "A choice must be made."], "payoff": "The choice pays off."},
                         "short_candidate": {"id": f"SC{c + 1}", "in": c0 + 20, "out": c0 + 80, "hook_line": "Would you stay on a sinking ship?",
                                             "setup": "The ship runs aground.", "turn": "Armed shapes on the beach.", "payoff": "They stay aboard and live."}})
        beats.append({"id": f"B{c + 1}", "name": "CHAPTER", "t0": c0, "t1": c1, "link": "BUT" if c % 2 == 0 else "THEREFORE",
                      "stakes": 6 + c * 0.5, "visual_scale": 6, "summary": f"Chapter {c + 1}", "chapter": f"CH{c + 1}"})
    while True:
        tag, text, rh = POOL[(k - 1) % len(POOL)]
        t0 = t
        t1 = t0 + 4.7
        if t1 > D - 4:
            break
        ch = next((c for c in chapters if c["t0"] <= t0 < c["t1"]), None)
        beat = "B0" if ch is None else f"B{chapters.index(ch) + 1}"
        k += 1
        ln = {"id": f"L{k:03d}", "beat": beat, "tag": tag, "text": text, "t0": round(t0, 2), "t1": round(t1, 2)}
        if rh:
            ln["rehook"] = True
        if ch:
            ln["chapter"] = ch["id"]
        lines.append(ln)
        t = t1 + 0.4
    answer = next(ln for ln in lines if ln["t0"] >= 0.9 * D)
    # candidates cut on narration line boundaries (DOC-short-cut)
    for c in chapters:
        sc = c["short_candidate"]
        sc["in"] = next(ln["t0"] for ln in lines if ln["t0"] >= sc["in"])
        sc["out"] = max(ln["t1"] for ln in lines if ln["t1"] <= sc["in"] + 60)
    # title after the cold open; climax -> resolution -> tease close the last chapter (DOC-title-beat, DOC-arc)
    beats.insert(1, {"id": "BT", "name": "TITLE", "t0": cold, "t1": cold + 4, "link": "THEREFORE", "stakes": 6, "visual_scale": 6,
                     "summary": "Title card."})
    beats += [{"id": "BC", "name": "CLIMAX", "t0": 0.8 * D, "t1": 0.9 * D, "link": "BUT", "stakes": 9, "visual_scale": 9, "summary": "Climax."},
              {"id": "BR", "name": "RESOLUTION", "t0": 0.9 * D, "t1": D - 10, "link": "THEREFORE", "stakes": 8, "visual_scale": 7, "summary": "Resolution."},
              {"id": "BX", "name": "TEASE", "t0": D - 10, "t1": D, "link": "BUT", "stakes": 7, "visual_scale": 6, "summary": "Tease."}]
    return {
        "id": "primrose", "format": "docuseries", "title": "Primrose: six days on the forbidden reef",
        "logline": "A cargo crew runs aground on the most isolated island on Earth and must survive without stepping ashore.",
        "essence": "Survival on the forbidden reef means never leaving the ship.", "style": "pixar_night_survival",
        "duration_s": D,
        "hero": {"name": "the captain", "description": "Captain of the Primrose", "flaw": "Cannot leave the ship and cannot call for help in the storm."},
        "hook": {"format": "IMR", "line_ids": ["L001"], "text_overlay": {"text": "SIX DAYS ON THE REEF", "start": 0, "end": 3.0},
                 "visual": "The ship heels on the reef in the storm; torches on the beach."},
        "core_question": {"text": "How does the crew survive without going ashore?", "answer_line": answer["id"]},
        "stakes": {"physical": "A broken hull in a storm.", "legal_ethical": "Contact is forbidden.", "mortal": "Armed islanders on the beach."},
        "time_pressure": False,
        "spine": {"once_upon_a_time": "A cargo ship crosses the Andaman Sea.", "every_day": "The crew trusts the route.",
                  "one_day": "A storm drives the ship onto the reef.", "because_of_that": ["Because of that, they are stranded.", "Because of that, they must wait aboard."],
                  "until_finally": "Helicopters lift them out.", "ever_since": "The reef is avoided."},
        "beats": beats, "narration": lines, "steps": [], "facts": [],
        "suspense_devices": [{"type": "threat_reveal", "desc": "Torches on the beach before the crew sees them.", "beat": "B1"}],
        "attempts": [{"action": "Radio for help in the storm.", "outcome": "fail"}, {"action": "Wait aboard.", "outcome": "success"}],
        "resolution": {"hero_action": "The captain keeps everyone aboard until the rescue.", "outcome": "Everyone survives."},
        "loop_back": {"method": "reverse_question", "desc": "Would you have stayed?"},
        "open_loops": [{"id": "CQ", "desc": "How do they survive?", "opened_t": 0.0, "closed_t": D - 2, "primary": True},
                       {"id": "OL1", "desc": "Who is on the beach?", "opened_t": 100, "closed_t": 120, "primary": False},
                       {"id": "OL2", "desc": "Will help come?", "opened_t": 300, "closed_t": 320, "primary": False}],
        "overrides": [],
        "cold_open": {"t0": 0.0, "t1": cold},
        "tease_next": "Next time: the man who tried to land.",
        "chapters": chapters,
    }
