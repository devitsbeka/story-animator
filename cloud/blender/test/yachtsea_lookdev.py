"""
yachtsea_lookdev.py - quick look-dev stills of the yacht materials + night sea, through the real
render_episode build path (hooks included), with the island's tree dressing and actors skipped so a
frame builds in seconds on a CPU.

  blender -b --factory-startup -P cloud/blender/test/yachtsea_lookdev.py -- \
      --out /tmp/yachtsea/ld --views hull,deck,reef --res 270x480 --samples 12 --threads 2 [--dress]

Views (yacht-space cameras unless noted): hull (low 3/4 at the waterline), deck (high over the cockpit),
reef (world camera behind the boat, looking across it at the reef breaker line ~25 m away), wide (A01-like aerial). Writes <out>/<view>.png.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import render_episode as R  # noqa: E402

VIEWS = {
    "hull": {"space": "yacht", "cam": [7.5, 1.6, 9.0], "look": [0.0, 0.8, 0.5], "fov": 38.0},
    "deck": {"space": "yacht", "cam": [3.2, 7.5, -9.5], "look": [0.0, 1.4, -3.0], "fov": 36.0},
    "reef": {"space": "world", "cam": [-18.0, 16.0, 22.0], "look": [22.0, 0.0, -14.0], "fov": 45.0},
    "wide": {"space": "yacht", "cam": [21.55, 32.72, -40.67], "look": [0.55, 2.72, -4.3], "fov": 30.0},
}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--views", default="hull,deck,reef")
    ap.add_argument("--frame", type=int, default=760)
    ap.add_argument("--res", default="270x480")
    ap.add_argument("--samples", type=int, default=12)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--dress", action="store_true", help="keep the island tree dressing (slow)")
    ap.add_argument("--base-shot", default="B11")
    a = ap.parse_args(argv)
    root = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
    spec_path = os.path.join(root, "episodes/sentinel/episode_v2.json")
    spec = json.load(open(spec_path))
    base = next(s for s in spec["shots"] if s["id"] == a.base_shot)
    shots = []
    f = a.frame
    for i, v in enumerate(a.views.split(",")):
        cfg = VIEWS[v]
        s = json.loads(json.dumps(base))
        s.update({"id": f"LD_{v}", "from": f + i * 10, "to": f + i * 10 + 1, "actors": [], "props": []})
        s["camera"] = {"space": cfg["space"], "keys": [{"f": f + i * 10, "cam": cfg["cam"], "look": cfg["look"], "fov": cfg["fov"], "ease": "linear"}]}
        shots.append(s)
    spec["shots"] = shots
    tmp = os.path.join(a.out, "_lookdev_spec.json")
    os.makedirs(a.out, exist_ok=True)
    # keep asset keys resolvable: write the spec next to the real one's root via --root
    json.dump(spec, open(tmp, "w"))
    if not a.dress:
        R.dress_island = lambda *x, **k: R.log("lookdev: island dressing skipped")
    sys.argv = ["blender", "--", "--spec", tmp, "--root", root, "--start", str(f), "--end", str(f + 10 * len(shots)),
                "--out", a.out, "--engine", "CYCLES", "--res", a.res, "--samples", str(a.samples),
                "--threads", str(a.threads), "--no-motion-blur"]
    R.main()


main()
