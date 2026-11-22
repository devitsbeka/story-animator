"""Render one golden recipe to a PNG (a horizontal strip of its views), deterministically on the CPU.

kinds
  hero       cloud/blender/test/golden_hero.py --mode turnaround|pose|face (neutral stage, production rig adapter)
  synthetic  a spec built here (yacht_turnaround: the yacht alone, island off, 4 camera azimuths) -> render_episode.py
  episode    frames of a pinned episode spec -> render_episode.py (one process per frame)

All renders: Cycles CPU, fixed samples, seed 0, --threads 2, no motion blur, recipe resolution (360x640), and a
library view `curated` (characters + the HDRIs/teak the renderer looks up; no island trees: deterministic, low
memory) or `full` (the whole library_store, for world kits whose scatter assets are the point).
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
import time

from . import manifest as M
from . import metrics

BLENDER = os.environ.get("BLENDER", "/opt/blender/blender-4.2.3-linux-x64/blender")
CURATED = ["characters", "ambientcg", "polyhaven/brown_planks_05", "polyhaven/kloppenheim_02_puresky", "polyhaven/moonlit_golf",
           "polyhaven/qwantani_night"]


def library_view(kind, root=M.ROOT):
    """Directory to use as LIBRARY_STORE for a render: the full store, or a symlink farm with the curated subset."""
    lib = M.find_library_store(root)
    if kind == "full":
        return lib
    d = os.path.join(M.store_dir(root), "lib_curated")
    for rel in CURATED:
        src, dst = os.path.join(lib, rel), os.path.join(d, rel)
        if os.path.exists(src) and not os.path.lexists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.symlink(src, dst)
    os.makedirs(d, exist_ok=True)
    return d


def yacht_turnaround_spec(root=M.ROOT):
    base = json.load(open(os.path.join(root, "episodes", "sentinel", "episode_v5.json")))
    keys = []
    for f, az in enumerate((35, 125, 215, 305)):
        import math
        a = math.radians(az)
        keys.append({"f": f, "cam": [round(17.0 * math.sin(a), 4), 5.5, round(17.0 * math.cos(a), 4)], "look": [0.0, 1.8, 0.0],
                     "fov": 42.0, "ease": "linear"})
    shot = {"id": "YT", "title": "yacht turnaround (golden)", "from": 0, "to": 4, "keyFrame": 1,
            "yacht": {"x": 0.0, "z": 0.0, "heading": 0.0, "lights": [[0, 1]]}, "island": None,
            "camera": {"space": "yacht", "handheld": 0.0, "drift": 0.0, "keys": keys},
            "direction": {"preset": "golden", "motivation": "golden"}}
    world = dict(base["world"], island=None)
    return {"$schema": base.get("$schema"), "version": 1, "id": "golden_yacht_turnaround", "title": "golden", "fps": 30,
            "width": 1080, "height": 1920, "durationFrames": 4, "audio": base.get("audio", {}), "world": world,
            "assets": {"characters": {}, "motions": {}, "props": dict(base["assets"].get("props", {}))},
            "shots": [shot], "captions": []}


def _abs_characters(spec, lib):
    """Pin blend characters to absolute library paths (the render may run from a worktree without library_store/)."""
    for k, v in (spec.get("assets", {}).get("characters") or {}).items():
        if isinstance(v, dict) and v.get("file", "").startswith("library_store/"):
            p = os.path.join(lib, v["file"][len("library_store/"):])
            if os.path.exists(p):
                v["file"] = p
    return spec


def _run(cmd, env, log_path, timeout):
    with open(log_path, "a") as fh:
        fh.write("$ " + " ".join(cmd) + "\n")
        fh.flush()
        try:
            return subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            return -9


def render_episode_frames(spec, frames, g, work, root, env, log_path):
    sp = os.path.join(work, "spec.json")
    with open(sp, "w") as fh:
        json.dump(spec, fh)
    plates = os.path.join(work, "plates")
    out = []
    for f in frames:
        cmd = [BLENDER, "-b", "--python-exit-code", "1", "--factory-startup", "-P", os.path.join(root, "cloud", "blender", "render_episode.py"),
               "--", "--spec", sp, "--root", root, "--start", str(f), "--end", str(f), "--out", plates, "--engine", g["engine"],
               "--res", g["res"], "--samples", str(g["samples"]), "--threads", str(g["threads"]), "--no-motion-blur"]
        rc = _run(cmd, env, log_path, g["timeout_s"])
        hits = glob.glob(os.path.join(plates, "*", f"{f:04d}.png"))
        if rc != 0 or not hits:
            raise RuntimeError(f"golden {g['id']}: frame {f} failed (rc={rc}); log {log_path}")
        out.append(hits[0])
    return out


def render_golden(gid, out_png, root=M.ROOT, log=print):
    m = M.load(root)
    g = m["goldens"][gid]
    lib = library_view(g.get("lib", "curated"), root)
    env = dict(os.environ, LIBRARY_STORE=lib)
    work = tempfile.mkdtemp(prefix=f"golden_{gid}_", dir=os.environ.get("FACTORY_GOLDENS_TMP"))
    log_path = os.path.splitext(out_png)[0] + ".log"
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    open(log_path, "w").close()
    t0 = time.time()
    try:
        if g["kind"] == "hero":
            blend = os.path.join(M.find_library_store(root), "characters", "hero_v4", "hero_v4.blend")
            cmd = [BLENDER, "-b", "--python-exit-code", "1", "--factory-startup", "-P", os.path.join(root, "cloud", "blender", "test", "golden_hero.py"),
                   "--", "--mode", g["mode"], "--out", work, "--blend", blend, "--res", g["res"], "--samples", str(g["samples"]),
                   "--threads", str(g["threads"])]
            rc = _run(cmd, env, log_path, g["timeout_s"])
            views = sorted(glob.glob(os.path.join(work, f"{g['mode']}_*.png")))
            if rc != 0 or not views:
                raise RuntimeError(f"golden {gid}: hero render failed (rc={rc}); log {log_path}")
        elif g["kind"] == "synthetic":
            spec = {"yacht_turnaround": yacht_turnaround_spec}[g["builder"]](root)
            views = render_episode_frames(spec, list(range(spec["durationFrames"])), g, work, root, env, log_path)
        elif g["kind"] == "episode":
            spec = _abs_characters(json.load(open(os.path.join(root, g["spec"]))), M.find_library_store(root))
            views = render_episode_frames(spec, g["frames"], g, work, root, env, log_path)
        else:
            raise ValueError(f"unknown golden kind {g['kind']}")
        strip = metrics.tile_strip([metrics.load(v) for v in views])
        metrics.save(strip, out_png)
        log(f"[goldens] {gid}: {len(views)} view(s) in {time.time() - t0:.0f}s -> {out_png}")
        return {"id": gid, "png": out_png, "views": len(views), "seconds": round(time.time() - t0, 1), "log": log_path}
    finally:
        shutil.rmtree(work, ignore_errors=True)
