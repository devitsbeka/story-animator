#!/usr/bin/env python3
"""
Episode v5 = v4 (story-first cameras + Primrose set) with the series hero swapped to hero_v4 (Blender Studio's Jay
rig re-dressed: PALENCIAGA hoodie, cap, joggers), driven by cloud/blender/cloudrig_adapter.py.

- Every hero actor becomes the CloudRig 'blend' actor (library_store/characters/hero_v4/hero_v4.blend).
- Face performance per shot: an emotion arc that follows the story beat, eyes on the action, natural blinks.
  He only lip-syncs where he actually speaks on screen ("Mayday!" in C13) - the VO is the narrator, not him.
- Eye-line fix: Jay's eyes sit ~0.22 m lower than the old hero's at the same 1.8 m height, so camera keys that frame
  the hero (look target within 2.5 m of his mark) drop by that amount, keeping eyes where the v3 cameras put them.
"""
import json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(EP))
EYE_DROP = 0.22

HERO = {"kind": "blend", "file": "library_store/characters/hero_v4/hero_v4.blend", "collection": "CH-jay", "rig": "RIG-jay",
        "options": {"Glasses": 0},
        "credit": "Hero built from Jay (Sprite Fright) by Blender Studio, (c) Blender Foundation, CC-BY 4.0, studio.blender.org"}

# story beat -> emotion arc [(offset_frames_from_shot_start, emotion, intensity)]
ARC = {
    "A01a": [(0, "calm", 0.8)], "A01b": [(0, "content", 0.6)], "A02": [(0, "calm", 0.7), (25, "concern", 0.4)],
    "A03": [(0, "calm", 0.5), (10, "shock", 1.0)], "A04": [(0, "worried"), (30, "panic", 0.8)],
    "A05": [(0, "worried", 0.9)], "A06": [(0, "worried", 0.8)],
    "A09a": [(0, "concern"), (50, "fear", 0.8)], "A09b": [(0, "fear", 1.0)],
    "B10": [(0, "concern", 0.4), (20, "pain", 0.9)], "B11": [(0, "pain", 0.6), (25, "worried")],
    "B12": [(0, "worried"), (25, "determined", 0.6)],
    "C13": [(0, "determined"), (10, "shout", 1.0)], "C14": [(0, "determined", 0.8)], "C15": [(0, "determined", 0.9), (30, "hopeful", 0.7)],
    "C16": [(0, "hopeful", 0.8)], "C17": [(0, "concern", 0.8), (40, "determined", 0.7)], "C18": [(0, "wince", 0.5), (30, "determined", 0.6)],
    "C19": [(0, "concern", 0.8)], "C20": [(0, "sneeze_build", 1.0), (34, "sneeze", 1.0), (46, "wince", 0.6)],
    "C21": [(0, "concern", 0.6), (30, "relief", 0.8)], "C22": [(0, "relief", 0.6)],
    "C27": [(0, "determined", 0.8)], "C28": [(0, "secret", 1.0)], "C29": [(0, "calm", 0.7)],
    "E30": [(0, "hopeful", 0.7), (40, "relief", 0.8)], "E31": [(0, "relief", 0.9), (30, "content", 0.7)],
}


# >>> polish_face: where the eyes go (cloudrig_adapter face_spec 'look'); default = a held fixation point ahead.
# Direct-to-lens only for deliberate address: the decision (B12) and the shush to the audience (C28).
LOOK = {"B12": "camera", "C28": "camera"}
# <<< polish_face


def words_in(words, f0, f1, offset):
    return [w for w in words if f0 <= w["s"] * 30 + offset < f1]


# >>> polish_hands_pose: every hero that sits on the bench (stance 'sit_bench', after use_yacht_v2 moved the sit beat
# onto the yacht_v2 aft bench) gets the bench seat anchor (marks.py) so the pelvis lands ON the cushion.
def anchor_sit(ep):
    import sys
    sys.path.insert(0, HERE)
    import marks
    if not marks.SIT_ANCHORS:
        return 0
    n = 0
    for sh in ep["shots"]:
        for a in sh.get("actors") or []:
            perf = a.get("perf") or {}
            st = perf.get("stance")
            names = [k[1] for k in st] if isinstance(st, list) else [st]
            if "sit_bench" in names:
                perf.setdefault("anchors", {}).update(marks.SIT_ANCHORS)
                n += 1
    return n
# <<< polish_hands_pose


def main():
    ep = json.load(open(os.path.join(EP, "episode_v4.json")))
    words = json.load(open(os.path.join(EP, "audio", "narration.words.json")))
    offset = (ep.get("audio") or {}).get("offset", 15)
    ep["assets"].setdefault("characters", {})["hero_v4"] = HERO
    n_hero = n_cam = 0
    for sh in ep["shots"]:
        heroes = [a for a in sh.get("actors") or [] if a.get("asset") == "hero"]
        for a in heroes:
            a["asset"] = "hero_v4"
            a.pop("tracks", None)
            arc = ARC.get(sh["id"], [(0, "calm", 0.6)])
            face = {"emotion": [[sh["from"] + t[0], t[1], t[2] if len(t) > 2 else 1.0] for t in arc],
                    "seed": (a.get("perf") or {}).get("seed", 1)}
            if sh["id"] in LOOK:  # polish_face
                face["look"] = LOOK[sh["id"]]
            if sh["id"] == "C13":
                face["words"] = words_in(words, sh["from"], sh["to"], offset)
            a["face"] = face
            n_hero += 1
            # eye-line fix for cameras that frame him
            if sh["camera"].get("space") == "yacht":
                hx, hy, hz = a["local"]
                for k in sh["camera"]["keys"]:
                    lx, ly, lz = k["look"]
                    if math.hypot(lx - hx, lz - hz) < 2.5 and abs(ly - hy) < 2.2:
                        k["look"][1] = round(ly - EYE_DROP, 4)
                        k["cam"][1] = round(k["cam"][1] - EYE_DROP, 4)
                        n_cam += 1
    n_yacht = use_yacht_v2(ep)
    anchor_sit(ep)
    ep["source"] = {"builder": "episodes/sentinel/plan/build_v5.py", "base": "episode_v4.json"}
    out = os.path.join(EP, "episode_v5.json")
    json.dump(ep, open(out, "w"), indent=1)
    print(f"wrote {out}: {n_hero} hero actors -> hero_v4, {n_cam} camera keys re-aimed to Jay's eye line; yacht_v2 remaps: {n_yacht}")


# >>> polish_yacht: the procedural high-detail yacht (cloud/blender/yacht_v2.py) + its marks (cloud/blender/yacht_marks.py)
YACHT = os.environ.get("SENTINEL_YACHT", "proc:yacht_v2")  # 'assets/props/yacht.glb' = the old crude yacht


def use_yacht_v2(ep):
    """Point the episode at yacht_v2 and move actors on marks that changed (SITMARK: cabin wall -> aft bench). The
    shot's yacht-space camera keys and yacht-attached props are carried rigidly with the mark (yaw about it)."""
    import sys
    sys.path.insert(0, os.path.join(ROOT, "cloud", "blender"))
    import yacht_marks as YM
    ep["assets"].setdefault("props", {})["yacht"] = YACHT
    if not YACHT.startswith("proc:yacht_v2"):
        return 0
    n = 0
    for sh in ep["shots"]:
        for a in sh.get("actors") or []:
            if a.get("space", "yacht") != "yacht":
                continue
            r = YM.remap(a["local"], a.get("rotY", 0.0))
            if not r:
                continue
            name, new, rot, dyaw = r
            old = list(a["local"])
            dy = YM.CAM_DY_V2.get(name, 0.0)
            a["local"], a["rotY"] = new, rot
            swap = YM.STANCE_V2.get(name, {})
            perf = a.get("perf") or {}
            if isinstance(perf.get("stance"), list):
                perf["stance"] = [[f, swap.get(s, s)] for f, s in perf["stance"]]
            elif isinstance(perf.get("stance"), str):
                perf["stance"] = swap.get(perf["stance"], perf["stance"])
            if sh["camera"].get("space") == "yacht":
                for k in sh["camera"]["keys"]:
                    k["cam"] = YM.move_point(k["cam"], old, new, dyaw, dy, YM.CAM_SCALE_V2.get(name, 1.0))
                    k["look"] = YM.move_point(k["look"], old, new, dyaw, dy)
            for p in sh.get("props") or []:
                if p.get("attach", "yacht") == "yacht" and "local" in p:
                    p["local"] = YM.move_point(p["local"], old, new, dyaw)
                    p["rotY"] = p.get("rotY", 0.0) + dyaw
            n += 1
    return n
# <<< polish_yacht


if __name__ == "__main__":
    main()
