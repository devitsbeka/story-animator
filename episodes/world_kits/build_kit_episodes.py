"""Tiny 3-shot proof episodes, one per starter world kit: breakdown -> librarian (location -> kit) -> shot plan staged
on the kit's marks -> stage-4 compile -> episode.json (render contract checked). The hero placeholder is the existing
hero.glb actor with an acting performance.

  python3 episodes/world_kits/build_kit_episodes.py            # writes episodes/world_kits/<kit>/*.json
  blender -b -P cloud/blender/render_episode.py -- --spec episodes/world_kits/<kit>/episode.json --start K --end K ...
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from factory.director import checks, compile as comp, librarian  # noqa: E402
from factory.worlds import kits, layout  # noqa: E402

FPS = 30


def orbit(mark, az, dist, height, fov, target="chest", preset="orbit_arc", motivation="character_attention", ease="move"):
    return {"preset": preset, "motivation": motivation, "rig": "orbit", "mark": mark, "az": az, "dist": dist, "height": height,
            "target": target, "fov": fov, "ease": ease, "handheld": 0.1, "drift": 0.06}


def path(cam0, cam1, look0, look1, fov, preset="push_in", motivation="reveal", ease="move"):
    P = lambda v: {"frame": "set", "v": v}
    return {"preset": preset, "motivation": motivation, "rig": "path", "space": "world", "cam": [P(cam0), P(cam1)], "look": [P(look0), P(look1)],
            "fov": fov, "ease": ease, "handheld": 0.08, "drift": 0.05}


# per kit: location element, 3 narration lines, 3 shots (camera, hero mark/stance/acting); index of the keyframe shot
EPISODES = {
    "jungle_clearing": {
        "location": {"name": "Jungle clearing with a campfire", "search_terms": ["jungle clearing", "campfire", "rainforest"], "must_do": ["surround the hero with dark trees", "glow with firelight"]},
        "time": "night",
        "lines": ["Night falls fast under the canopy.", "Keep the fire small and close.", "Out here, the dark is listening."],
        "shots": [
            {"title": "Clearing reveal down the trail", "size": "WS", "camera": path([0.2, 2.4, -13.0], [0.1, 2.0, -9.0], [0.6, 1.2, 0.6], [0.5, 1.0, 0.8], [40, 34]),
             "hero": {"mark": "FIRESIDE", "stance": "stand", "poses": [{"pose": "look_down", "from": 20, "to": 70}], "verbs": []}},
            {"title": "By the fire", "size": "MS", "camera": orbit("FIRESIDE", [-62, -42], [3.6, 3.0], [0.15, 0.1], [36, 32]),
             "hero": {"mark": "FIRESIDE", "stance": "stand", "poses": [{"pose": "look_left", "from": 85, "to": 140}], "verbs": [{"verb": "breathe_hard", "at": 80, "dur": 60, "amount": 0.6}]}},
            {"title": "Listening", "size": "MCU", "camera": orbit("FIRESIDE", [-52, -42], [1.5, 1.3], [0.05, 0.05], [30, 28], target="face", preset="push_in", motivation="tension_push"),
             "hero": {"mark": "FIRESIDE", "stance": "stand", "poses": [{"pose": "look_back", "from": 165, "to": 222}], "verbs": [{"verb": "flinch", "at": 180, "dur": 14}]}},
        ],
        "key_shot": 1,
    },
    "desert_canyon": {
        "location": {"name": "Sandstone desert canyon", "search_terms": ["desert canyon", "gorge", "sandstone"], "must_do": ["box the hero in with towering walls", "bake in midday sun"]},
        "time": "day",
        "lines": ["The canyon walls trap the heat.", "Shade is the only water you can find.", "Move at dawn, rest at noon."],
        "shots": [
            {"title": "Walking into the canyon", "size": "WS", "camera": path([-5.0, 2.6, -15.0], [-4.0, 2.2, -11.0], [0.0, 1.3, 0.0], [0.0, 1.2, 1.0], [42, 36]),
             "hero": {"mark": "CANYON_FLOOR", "stance": "stand", "poses": [{"pose": "look_up", "from": 15, "to": 70}], "verbs": []}},
            {"title": "Heat", "size": "MS", "camera": orbit("CANYON_FLOOR", [-35, -20], [4.2, 3.6], [0.25, 0.15], [36, 32]),
             "hero": {"mark": "CANYON_FLOOR", "stance": "stand", "poses": [{"pose": "hands_face", "from": 85, "to": 140}], "verbs": [{"verb": "breathe_hard", "at": 80, "dur": 60}]}},
            {"title": "Into the shade", "size": "MCU", "camera": orbit("SHADE", [-20, -10], [1.6, 1.4], [0.05, 0.05], [30, 28], target="face", preset="push_in", motivation="tension_push"),
             "hero": {"mark": "SHADE", "stance": "stand", "poses": [{"pose": "look_down", "from": 160, "to": 222}], "verbs": [{"verb": "nod", "at": 190, "dur": 18}]}},
        ],
        "key_shot": 1,
    },
    "snow_mountain_ridge": {
        "location": {"name": "Snowy mountain ridge", "search_terms": ["mountain ridge", "snow", "summit"], "must_do": ["drop away on both sides", "glow in low sun"]},
        "time": "dusk",
        "lines": ["The ridge is a knife edge of snow.", "One step wrong and the mountain decides.", "The summit is closer than the dark."],
        "shots": [
            {"title": "On the knife edge", "size": "WS", "camera": path([7.5, 3.6, -9.0], [6.5, 3.0, -6.0], [0.0, 1.3, 0.0], [0.0, 1.2, 0.5], [42, 36]),
             "hero": {"mark": "CREST", "stance": "brace", "poses": [{"pose": "look_down", "from": 15, "to": 70}], "verbs": []}},
            {"title": "Toward the summit", "size": "MS", "camera": orbit("CREST", [-45, -30], [4.6, 4.0], [0.35, 0.25], [36, 32]),
             "hero": {"mark": "CREST", "stance": "brace", "poses": [{"pose": "point_ahead", "from": 88, "to": 140}], "verbs": [{"verb": "breathe_hard", "at": 80, "dur": 60}]}},
            {"title": "The view", "size": "MCU", "camera": orbit("LOOKOUT", [-30, -20], [1.6, 1.4], [0.05, 0.05], [30, 28], target="face", preset="push_in", motivation="tension_push"),
             "hero": {"mark": "LOOKOUT", "stance": "stand", "poses": [{"pose": "look_up", "from": 160, "to": 222}], "verbs": []}},
        ],
        "key_shot": 1,
    },
    "abandoned_city_street": {
        "location": {"name": "Abandoned city street", "search_terms": ["city street", "abandoned", "downtown"], "must_do": ["stretch away empty", "hum under one lit lamp"]},
        "time": "night",
        "lines": ["Every street looks the same after the end.", "Stay under the light and they see you.", "Stay in the dark and you see them."],
        "shots": [
            {"title": "Empty street", "size": "WS", "camera": path([0.8, 2.2, -12.0], [0.6, 1.9, -8.0], [0.0, 1.2, 0.0], [0.0, 1.1, 1.0], [42, 36]),
             "hero": {"mark": "STREET_CENTER", "stance": "stand", "poses": [{"pose": "look_left", "from": 15, "to": 70}], "verbs": []}},
            {"title": "Under the lamp", "size": "MS", "camera": orbit("LAMP_POST", [8, 22], [4.4, 3.8], [0.3, 0.2], [36, 32]),
             "hero": {"mark": "LAMP_POST", "stance": "stand", "poses": [{"pose": "look_right", "from": 85, "to": 140}], "verbs": [{"verb": "step_back", "at": 110, "dur": 20}]}},
            {"title": "Behind the wreck", "size": "MCU", "camera": orbit("CAR_COVER", [-25, -15], [1.6, 1.4], [0.05, 0.05], [30, 28], target="face", preset="push_in", motivation="tension_push"),
             "hero": {"mark": "CAR_COVER", "stance": "brace", "poses": [{"pose": "shush", "from": 160, "to": 222}], "verbs": []}},
        ],
        "key_shot": 1,
    },
}


def build(kit_id, spec, out_root):
    kit = kits.load(kit_id)
    eid = f"wk_{kit_id}"
    loc = {"id": f"{kit_id}_loc", "kind": "location", **spec["location"]}
    hero = {"id": "hero", "kind": "character", "name": "Hero", "must_do": ["act"], "search_terms": ["hero"]}
    lines = [{"id": f"L{i + 1:02d}", "t0": round(i * 2.5 + 0.1, 2), "t1": round(i * 2.5 + 2.3, 2), "text": t} for i, t in enumerate(spec["lines"])]
    bd = {"id": eid, "scenes": [{"id": "S01", "title": kit["name"], "location": loc["id"], "time_of_day": spec["time"], "weather": "clear",
                                 "line_ids": [l["id"] for l in lines], "picture": spec["location"]["must_do"][0], "elements": [loc["id"], "hero"]}],
          "elements": [loc, hero]}
    man, _ = librarian.resolve(bd)
    loc_e = next(e for e in man["entries"] if e["element"] == loc["id"])
    assert loc_e.get("render_key") == f"set:{kit_id}", (kit_id, loc_e)
    story = {"id": eid, "format": "short", "title": f"World kit proof: {kit['name']}", "duration_s": 7.5, "narration": lines}
    shots = []
    for i, s in enumerate(spec["shots"]):
        f0, f1 = i * 75, (i + 1) * 75
        sh = {"id": f"K{i + 1:02d}", "title": s["title"], "from": f0, "to": f1, "scene": "S01", "line_ids": [lines[i]["id"]], "size": s["size"],
              "camera": s["camera"], "yacht": {"state": "absent"}, "island": None, "set": kit_id}
        h = dict(s["hero"], seed=i + 1)
        h["poses"] = [dict(p, **{"from": p["from"] if p["from"] >= f0 else p["from"] + f0, "to": p["to"] if p["to"] > f0 else p["to"] + f0}) for p in h["poses"]]
        sh["hero"] = h
        shots.append(sh)
    plan = {"id": eid, "audio_offset_frames": 3, "world": {"moonDir": kit["sky"]["key_dir"], "seaState": 0, "dawn": 0, "island": None, "set": kit_id},
            "action_line": "hero faces +z; cameras stay on the hero's left (az < 0)", "shots": shots, "overrides": []}
    rep = checks.check_shotplan(plan, story, bd, man)
    staging = [i for i in rep.issues if i["rule"].split(".")[0] in ("V-orbit", "V-path", "V-mark", "V-stance", "V-pose", "V-verb", "V-set", "V-set-world", "K-camera-safe", "SCHEMA")]
    out = os.path.join(out_root, kit_id)
    ep = comp.compile_episode(plan, story, man, out)
    erep = checks.check_episode(ep)
    os.makedirs(out, exist_ok=True)
    for name, doc in (("breakdown.json", bd), ("manifest.json", man), ("story.json", story), ("shotplan.json", plan), ("episode.json", ep)):
        with open(os.path.join(out, name), "w") as fh:
            json.dump(doc, fh, indent=1)
            fh.write("\n")
    key = ep["shots"][spec["key_shot"]]
    plan_k = layout.layout(kit, with_grid=False)
    return {"kit": kit_id, "manifest_location": loc_e["decision"] + " " + loc_e["catalog_id"], "staging_issues": [f"{i['rule']}: {i['msg']}" for i in staging],
            "episode_contract_ok": erep.ok, "episode_blocking": [i["msg"] for i in erep.blocking][:5], "key_frame": key["keyFrame"], "key_shot": key["id"],
            "layout_hash": plan_k["hash"][:12], "spec": os.path.relpath(os.path.join(out, "episode.json"), ROOT)}


def main():
    res = [build(k, v, HERE) for k, v in EPISODES.items()]
    print(json.dumps(res, indent=1))
    return 0 if all(r["episode_contract_ok"] and not r["staging_issues"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
