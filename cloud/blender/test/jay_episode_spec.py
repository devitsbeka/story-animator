"""Make a copy of an episode spec with the hero swapped to the CloudRig Jay rig (render_episode 'blend' actor kind).

  python3 cloud/blender/test/jay_episode_spec.py [--src episodes/sentinel/episode_v4.json] [--out /tmp/rigadapter/episode_jay.json]

Adds per-shot face tracks (emotion / gaze / a test line of words for visemes) to a few shots so the
face engine is exercised; every other shot keeps only its body perf (face defaults: blinks + micro-saccades).
Render e.g.:
  LIBRARY_STORE=/tmp/empty_lib blender -b --factory-startup -P cloud/blender/render_episode.py -- \
     --spec /tmp/rigadapter/episode_jay.json --root . --start 815 --end 815 --out /tmp/rigadapter/plates \
     --engine CYCLES --res 360x540 --samples 16 --threads 2
"""
import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))

JAY = {"kind": "blend", "file": "library_store/characters/jay.blend", "collection": "CH-jay", "rig": "RIG-jay",
       "options": {"Glasses": 0},
       "credit": "Jay (Sprite Fright) by Blender Studio, (c) Blender Foundation, CC-BY 4.0, studio.blender.org"}

FACES = {
    "B12": {"emotion": [[786, "worried"], [806, "fear", 0.9]], "gaze": [[786, 12, -4], [800, -10, 2], [818, 4, -6]], "seed": 7},
    "C21": {"emotion": [[1389, "concern", 0.6], [1420, "relief"]], "gaze": [[1389, 0, -8], [1425, -6, 4]], "seed": 12,
            "words": [{"w": "stay", "s": 47.6, "e": 47.95}, {"w": "with", "s": 47.95, "e": 48.15},
                      {"w": "the", "s": 48.15, "e": 48.3}, {"w": "boat", "s": 48.3, "e": 48.75}]},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(REPO, "episodes", "sentinel", "episode_v4.json"))
    ap.add_argument("--out", default="/tmp/rigadapter/episode_jay.json")
    ap.add_argument("--jay", default=None, help="jay.blend path written into the spec (default: first library_store copy found)")
    a = ap.parse_args()
    s = json.load(open(a.src))
    jay = dict(JAY)
    cands = [a.jay, os.path.join(REPO, JAY["file"]), os.path.join(os.environ.get("LIBRARY_STORE_SRC", ""), "characters", "jay.blend"),
             "/home/user/story-animator/library_store/characters/jay.blend"]
    jay["file"] = next((c for c in cands if c and os.path.isfile(c)), JAY["file"])
    s["assets"]["characters"]["jay"] = jay
    n = 0
    for sh in s["shots"]:
        for act in sh.get("actors") or []:
            if act.get("asset") == "hero":
                act["asset"] = "jay"
                act.pop("tracks", None)
                if sh["id"] in FACES:
                    act["face"] = FACES[sh["id"]]
                n += 1
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(s, open(a.out, "w"), indent=1)
    print(f"wrote {a.out}: {n} hero actors -> jay")


if __name__ == "__main__":
    main()
