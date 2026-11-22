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


def words_in(words, f0, f1, offset):
    return [w for w in words if f0 <= w["s"] * 30 + offset < f1]


# >>> polish_hands_pose: the sit beat (C21 sits down, C22 stays seated) moves from the deck against the white cabin
# wall onto the cockpit bench (marks.py), facing the bow, stance 'sit_bench' with the pelvis anchored on the seat.
# The cameras are mirrored through the plane half-way between the old and new seat (z' = z_old + z_new - z) and
# lifted by the extra seat height, so each shot keeps its framing / move (orbit, crane) around the new position.
SIT_SHOTS = ("C21", "C22")
OLD_SIT_Z = -3.7        # v4 'SITMARK' (deck, back to the cabin)
SIT_LIFT = 0.35         # bench seat 0.41 m above the deck, minus what the deck sit already raised the look by


def restage_sit(ep):
    import sys
    sys.path.insert(0, HERE)
    import marks
    new_z = marks.SIT_ANCHORS["bench_seat"]["p"][2]
    for sh in ep["shots"]:
        if sh["id"] not in SIT_SHOTS:
            continue
        for a in sh.get("actors") or []:
            if a.get("asset") != "hero_v4":
                continue
            a["local"] = list(marks.SIT_MARK["local"])
            a["rotY"] = marks.SIT_MARK["rotY"]
            perf = a.setdefault("perf", {})
            perf["stance"] = [[k[0], "sit_bench" if k[1] == "sit_deck" else k[1]] for k in perf.get("stance", [])]
            perf["anchors"] = dict(marks.SIT_ANCHORS)
        keys = sh["camera"]["keys"]
        f0, f1 = keys[0]["f"], keys[-1]["f"]
        for k in keys:
            for key in ("cam", "look"):
                x, y, z = k[key]
                k[key] = [x, round(y + SIT_LIFT, 4), round(OLD_SIT_Z + new_z - z, 4)]
        # the mirrored C21 orbit / C22 crane start too close for Jay's big head: re-author the near part.
        # C21 = a slow orbit in front of him, between the cabin's aft wall (z -3.33) and the bench, clear of the helm;
        # C22 starts there and keeps its crane to the extreme wide.
        sx, sz = marks.SIT_X, new_z
        if sh["id"] == "C21":
            a_, b_ = [sx - 0.45, 2.95, -3.42], [sx + 0.2, 2.9, -3.42]
            for k in keys:
                u = (k["f"] - f0) / max(1, f1 - f0)
                e = u * u * (3 - 2 * u)
                k["cam"] = [round(a_[i] + (b_[i] - a_[i]) * e, 4) for i in range(3)]
                k["fov"] = 64.0
                s = min(1.0, max(0.0, (k["f"] - 1400) / 20.0))     # stands, then sits at 1405
                s = s * s * (3 - 2 * s)
                k["look"] = [sx, round(2.78 + (2.45 - 2.78) * s, 4), round(sz + 0.35 - 0.25 * s, 4)]
        elif sh["id"] == "C22":
            start = [sx + 0.2, 2.9, -3.42]
            c0 = list(keys[0]["cam"])
            for k in keys:
                u = (k["f"] - f0) / max(1, f1 - f0)
                w = (1 - u) ** 2
                k["cam"] = [round(k["cam"][i] + (start[i] - c0[i]) * w, 4) for i in range(3)]
                k["look"] = [sx, 2.45, round(sz + 0.1, 4)]
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
    restage_sit(ep)
    ep["source"] = {"builder": "episodes/sentinel/plan/build_v5.py", "base": "episode_v4.json"}
    out = os.path.join(EP, "episode_v5.json")
    json.dump(ep, open(out, "w"), indent=1)
    print(f"wrote {out}: {n_hero} hero actors -> hero_v4, {n_cam} camera keys re-aimed to Jay's eye line")


if __name__ == "__main__":
    main()
