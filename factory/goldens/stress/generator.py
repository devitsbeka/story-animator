"""Scenario stress suite: synthetic one-shot scenarios generated in code (not picked from an episode).

The base suite crosses the axes that break - stance x hand use x world kit x shot size x emotion - with seeded
variety (camera azimuth/height jitter, actor yaw jitter, seed). Lesson regression cases (cases.json, written by
`python -m factory.lessons add`) expand one defect selector into one scenario per world kit, so a defect class is
covered in every world, not only where it was first seen.

All scenarios are compiled into ONE episode spec (stress_episode.json, deterministic; 60 frames per scenario) that
render_episode.py, pose_qc.py and the shot checks all consume.

    python -m factory.goldens.stress.generator [--check]     (re)write stress_episode.json / verify it is current
"""
from __future__ import annotations

import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SPEC_PATH = os.path.join(HERE, "stress_episode.json")
CASES_PATH = os.path.join(HERE, "cases.json")
SEED = 20261122
FRAMES = 60                      # 2 s per scenario (face-life is measured over the whole clip)
KITS = ("sea_yacht", "jungle_clearing", "desert_canyon", "snow_mountain_ridge", "abandoned_city_street")
SIZES = {"wide": (6.5, 40.0, 0.55), "medium": (2.6, 34.0, 0.72), "close": (1.7, 30.0, 0.82)}   # dist m, fov, look-at height / body height
EMOTIONS = ("neutral", "fear", "shout", "relief", "determined", "sneeze")
YACHT_MARKS = {"HELM": ([0.55, 1.42, -4.3], 0.0), "COCKPIT": ([0.0, 1.42, -4.6], 0.0), "SITMARK": ([-0.55, 1.42, -3.7], math.pi),
               "RAIL": ([1.45, 1.42, -4.8], math.pi / 2), "BOW": ([0.0, 1.9, 4.7], 0.0), "AFTFACE": ([0.0, 1.42, -4.7], math.pi)}
# hand use -> (pose, prop, hand shape intent). Grip props attach to handR exactly as episodes do.
HANDS = {
    "relaxed": (None, None, "relaxed"), "wheel": (None, "helm", "grip"), "radio": ("radio_shout", "radio", "grip"),
    "radio_mouth": ("radio_mouth", "radio", "grip"), "phone": ("phone_up", "phone", "grip"), "beacon": ("beacon_raise", "beacon", "grip"),
    "rail": ("hold_rail", None, "grip"), "point": ("point_ahead", None, "point"), "wave": ("wave", None, "open_palm"),
    "shush": ("shush", None, "point"), "reach": ("press_ahead", None, "reach"), "cover_mouth": ("cover_mouth", None, "relaxed"),
    "hands_up": ("hands_up", None, "open_palm"), "rope": (None, None, "grip"),
}
PROP_GRIP = {"radio": {"local": [0.0, -0.03, 0.0], "rot": [-90, 0, 0]}, "phone": {"local": [0.0, -0.02, 0.0], "rot": [-90, 0, 0]},
             "beacon": {"local": [0.0, -0.03, 0.0], "rot": [-90, 0, 0]}}
# stances the renderer does not have yet: the scenario uses the fallback and records the gap (VOCAB rule fails)
VOCAB_FALLBACK = {"kneel": "down", "crouch": "down", "walk": "stand", "sit_bench": "sit_deck", "sit_rock": "sit_deck", "sit_log": "sit_deck"}

# The base suite: (id, kit, mark, stance, hands, size, emotion). 22 scenarios, >= 4 per world.
BASE = [
    ("y_helm_wheel", "sea_yacht", "HELM", "helm", "wheel", "medium", "determined"),
    ("y_radio_shout", "sea_yacht", "COCKPIT", "brace", "radio", "close", "shout"),
    ("y_sit_deck", "sea_yacht", "SITMARK", "sit_deck", "relaxed", "medium", "neutral"),
    ("y_rail_fear", "sea_yacht", "RAIL", "brace", "rail", "wide", "fear"),
    ("y_bow_point", "sea_yacht", "BOW", "stand", "point", "wide", "determined"),
    ("j_sit_log", "jungle_clearing", "LOG_SIT", "sit_log", "relaxed", "medium", "relief"),
    ("j_shush_close", "jungle_clearing", "FIRESIDE", "stand", "shush", "close", "fear"),
    ("j_phone", "jungle_clearing", "CENTER", "stand", "phone", "medium", "neutral"),
    ("j_kneel", "jungle_clearing", "BOULDER", "kneel", "relaxed", "medium", "fear"),
    ("j_walk", "jungle_clearing", "TRAIL_EDGE", "walk", "relaxed", "wide", "neutral"),
    ("d_wave", "desert_canyon", "CANYON_FLOOR", "stand", "wave", "wide", "relief"),
    ("d_sit_rock_sneeze", "desert_canyon", "SHADE", "sit_rock", "relaxed", "close", "sneeze"),
    ("d_reach", "desert_canyon", "DEAD_TREE", "stand", "reach", "medium", "determined"),
    ("d_rope", "desert_canyon", "WALK_IN", "brace", "rope", "medium", "determined"),
    ("s_brace_wide", "snow_mountain_ridge", "CREST", "brace", "relaxed", "wide", "fear"),
    ("s_sit_bench", "snow_mountain_ridge", "SHELTER", "sit_bench", "relaxed", "medium", "sneeze"),
    ("s_beacon", "snow_mountain_ridge", "LOOKOUT", "stand", "beacon", "medium", "relief"),
    ("s_crouch_close", "snow_mountain_ridge", "CLIMB_UP", "crouch", "relaxed", "close", "determined"),
    ("c_radio_mouth", "abandoned_city_street", "STREET_CENTER", "stand", "radio_mouth", "close", "neutral"),
    ("c_cover_fear", "abandoned_city_street", "CAR_COVER", "brace", "cover_mouth", "close", "fear"),
    ("c_hands_up", "abandoned_city_street", "LAMP_POST", "stand", "hands_up", "wide", "shout"),
    ("c_doorway_sneeze", "abandoned_city_street", "DOORWAY", "stand", "relaxed", "medium", "sneeze"),
]


def kit_marks(kit):
    if kit == "sea_yacht":
        return {k: {"local": v[0], "rotY": v[1], "kind": "sit" if k == "SITMARK" else "stand"} for k, v in YACHT_MARKS.items()}
    sys.path.insert(0, ROOT)
    from factory.worlds import kits, layout
    return layout.marks(kits.load(kit))


def load_cases(path=CASES_PATH):
    if not os.path.exists(path):
        return {"schema": "factory.goldens.stress.cases/1", "cases": []}
    with open(path) as fh:
        return json.load(fh)


def pick_mark(kit, stance, hands):
    mk = kit_marks(kit)
    want = "sit" if stance.startswith("sit") else ("walk" if stance == "walk" else ("interact" if hands not in ("relaxed",) else "stand"))
    for kind in (want, "interact", "stand"):
        for n, m in mk.items():
            if m.get("kind") == kind:
                return n
    return next(iter(mk))


def _sel_match(sel, v):
    """selector value: None (any), a glob ('sit*'), or a list of alternatives"""
    import fnmatch
    if sel is None:
        return True
    return any(fnmatch.fnmatch(v, s) for s in (sel if isinstance(sel, list) else [sel]))


def _first(sel, default):
    if sel is None:
        return default
    s = sel[0] if isinstance(sel, list) else sel
    s = s.replace("*", "")
    if s in HANDS or s in VOCAB_FALLBACK or s in SIZES or s in EMOTIONS or s in ("stand", "brace", "helm", "down", "sit_deck"):
        return s
    return {"sit": "sit_deck", "radio": "radio"}.get(s.rstrip("_"), default)


def expand_case(case, base_ids=None):
    """A lesson case selector {stance?, hands?, size?, emotion?} -> one scenario per kit (reusing a matching base
    scenario in that kit when there is one)."""
    out = []
    for kit in KITS:
        hit = next((b for b in BASE if b[1] == kit and all(_sel_match(case.get(k), v) for k, v in
                                                          (("stance", b[3]), ("hands", b[4]), ("size", b[5]), ("emotion", b[6])))), None)
        if hit:
            out.append({"id": hit[0], "reused": True})
            continue
        st = _first(case.get("stance"), "stand")
        hands = _first(case.get("hands"), "relaxed")
        sid = f"{case['lesson'].lower()}_{kit.split('_')[0]}_{case.get('tag', 'case')}"
        out.append({"id": sid, "reused": False, "row": (sid, kit, pick_mark(kit, st, hands), st, hands, _first(case.get("size"), "medium"),
                                                        _first(case.get("emotion"), "neutral"))})
    return out


def scenarios(cases=None):
    rows = list(BASE)
    lesson_of = {}
    for c in (cases or load_cases())["cases"]:
        for e in expand_case(c, {b[0] for b in BASE}):
            lesson_of.setdefault(e["id"], []).append(c["lesson"])
            if not e["reused"] and all(r[0] != e["id"] for r in rows):
                rows.append(e["row"])
    return rows, lesson_of


def _rot(a, v):
    c, s = math.cos(a), math.sin(a)
    return [c * v[0] + s * v[2], v[1], -s * v[0] + c * v[2]]


def _sc():
    d = os.path.join(ROOT, "factory", "direction")
    if d not in sys.path:
        sys.path.insert(0, d)
    import shot_checks
    return shot_checks


def build(cases=None):
    global SC
    SC = _sc()
    base = json.load(open(os.path.join(ROOT, "episodes", "sentinel", "episode_v5.json")))
    rows, lesson_of = scenarios(cases)
    rng = random.Random(SEED)
    shots, meta = [], []
    for i, (sid, kit, mark, stance, hands, size, emo) in enumerate(rows):
        f0 = i * FRAMES
        f1 = f0 + FRAMES
        key = f0 + 40
        mk = kit_marks(kit)[mark]
        loc = list(mk["local"])
        yaw = mk.get("rotY", 0.0) + rng.uniform(-0.15, 0.15)
        st = VOCAB_FALLBACK.get(stance, stance)
        pose, prop, shape = HANDS[hands]
        perf = {"stance": [[-10000, st]], "poses": [], "verbs": [], "breath": 1.0, "seed": 1 + i, "blend": 8,
                "hands": [[-10000, "relaxed", shape]]}
        if pose:
            perf["poses"].append({"pose": pose, "from": f0 + 4, "to": f1, "in": 8, "out": 1, "ease": "smooth"})
        dist, fov, ty = SIZES[size]
        actor = {"asset": "hero_v4", "space": "yacht" if kit == "sea_yacht" else "set", "local": [round(x, 4) for x in loc],
                 "rotY": round(yaw, 4), "height": 1.8, "perf": perf, "face": {"emotion": [[f0, emo, 1.0]], "seed": 1 + i}}
        shot = {"id": sid, "title": f"stress {kit} {stance} {hands} {size} {emo}", "from": f0, "to": f1, "keyFrame": key,
                "actors": [actor], "camera": {"space": "yacht" if kit == "sea_yacht" else "world", "handheld": 0.0, "drift": 0.0, "keys": []},
                "direction": {"preset": "stress", "motivation": "stress", "size": [size.upper(), size.upper()],
                              "subject": {"kind": "hero", "name": "hero", "height": 1.8}}}
        if kit == "sea_yacht":
            shot["yacht"] = {"x": 0.0, "z": 0.0, "heading": 0.0, "lights": [[0, 1]]}
        # aim from the rig's head landmarks (the same metrics the per-shot checks use): close = eyes in the upper band,
        # medium = chest, wide = mid-body; then pick the first seeded azimuth whose camera is collision-free and frames
        # the head (yacht cabins / set pieces block some sides)
        hp = SC.head_points(shot, actor, key)
        if size == "close":
            frame_h = 2 * dist * math.tan(math.radians(fov) / 2)
            tgt = [hp["eyes"][0], hp["eyes"][1] - 0.12 * frame_h, hp["eyes"][2]]
        elif size == "medium":
            tgt = hp["chest"]
        else:
            tgt = [loc[0], (loc[1] + hp["top"][1]) / 2, loc[2]]
        lift = rng.uniform(0.05, 0.3)
        cands = [yaw + rng.uniform(-0.9, 0.9)] + [yaw + d for d in (0.6, -0.6, 1.2, -1.2, 1.8, -1.8, math.pi)]

        def keys_for(az):
            def cam_at(d):
                off = _rot(az, [0.0, 0.0, d])
                return [round(tgt[0] + off[0], 4), round(tgt[1] + lift * (d / 6.5 + 0.3), 4), round(tgt[2] + off[2], 4)]
            look = [round(x, 4) for x in tgt]
            return [{"f": f0, "cam": cam_at(dist * 1.06), "look": look, "fov": fov, "ease": "linear"},
                    {"f": f1 - 1, "cam": cam_at(dist), "look": look, "fov": fov, "ease": "move"}]
        for az in cands:
            shot["camera"]["keys"] = keys_for(az)
            if not any(f["status"] == "fail" and f["rule"] in ("COLLIDE", "FRAME-CROP", "VIS") for f in SC.check_shot({"width": 1080, "height": 1920}, shot)):
                break
        if kit == "sea_yacht":
            shot["island"] = None
        else:
            shot["set"] = {"kit": kit, "seed": 11}
            shot["island"] = None
        props = []
        if hands == "wheel" and kit == "sea_yacht":
            props.append({"prop": "helm", "attach": "yacht", "local": [0.55, 1.42, -3.72], "rotY": math.pi})
        if prop in PROP_GRIP:
            props.append({"prop": prop, "attach": "handR", **PROP_GRIP[prop]})
        if props:
            shot["props"] = props
            for az in cands:                  # props can block too: re-check with them
                if not any(f["status"] == "fail" and f["rule"] in ("COLLIDE", "FRAME-CROP", "VIS") for f in SC.check_shot({"width": 1080, "height": 1920}, shot)):
                    break
                shot["camera"]["keys"] = keys_for(az)
        missing = [x for x in (stance if stance in VOCAB_FALLBACK else None, "rope" if hands == "rope" else None,
                               "wheel_prop" if hands == "wheel" and kit != "sea_yacht" else None) if x]
        shots.append(shot)
        meta.append({"id": sid, "kit": kit, "mark": mark, "stance": stance, "render_stance": st, "hands": hands, "hand_shape": shape,
                     "size": size, "emotion": emo, "vocab_missing": missing, "lessons": lesson_of.get(sid, []), "keyFrame": key})
    spec = {"version": 1, "id": "stress_suite", "title": "Scenario stress suite (generated)", "fps": 30, "width": 1080, "height": 1920,
            "durationFrames": len(shots) * FRAMES, "audio": {}, "world": dict(base["world"], island=None),
            "assets": {"characters": {"hero_v4": base["assets"]["characters"]["hero_v4"]}, "motions": {}, "props": dict(base["assets"]["props"])},
            "shots": shots, "captions": [], "stress": {"seed": SEED, "generator": "factory/goldens/stress/generator.py", "scenarios": meta}}
    return spec


def write(path=SPEC_PATH):
    spec = build()
    with open(path, "w") as fh:
        json.dump(spec, fh, indent=1)
        fh.write("\n")
    return spec


def is_current(path=SPEC_PATH):
    if not os.path.exists(path):
        return False
    with open(path) as fh:
        return json.load(fh) == json.loads(json.dumps(build()))


if __name__ == "__main__":
    if "--check" in sys.argv:
        ok = is_current()
        print("stress_episode.json " + ("current" if ok else "STALE: run python -m factory.goldens.stress.generator"))
        sys.exit(0 if ok else 1)
    s = write()
    print(f"wrote {SPEC_PATH}: {len(s['shots'])} scenarios")
