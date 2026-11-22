"""Export collision proxies (per-part axis-aligned boxes) of every code-built prop / vehicle to JSON, for the
camera-inside-geometry check in factory/direction/mesh_proxy.py (lesson L012). No rendering.

  blender -b --factory-startup -P cloud/blender/test/export_prop_proxies.py -- [--out factory/direction/proxies/props.json]

Boxes are in the prop root's local frame in the renderer's spec convention (x right, y up, z forward: three.js /
glTF axes, the same frame as `props[].local`), so a box transforms with the prop's local/rotY/scale.
Parts smaller than 5 cm on every axis are skipped (they cannot swallow a camera).
"""
import json
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import props as propkit  # noqa: E402
import props_vehicles as vehicles  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(REPO, "factory", "direction", "proxies", "props.json")


def bl_to_spec(v):
    return (v.x, v.z, -v.y)


def boxes_of(root):
    bpy.context.view_layer.update()
    inv = root.matrix_world.inverted()
    dg = bpy.context.evaluated_depsgraph_get()
    out = []
    for o in root.children_recursive:
        if o.type not in ("MESH", "CURVE", "FONT"):
            continue
        ev = o.evaluated_get(dg)
        try:
            me = ev.to_mesh()
        except RuntimeError:
            continue
        if me is None or not me.vertices:
            ev.to_mesh_clear()
            continue
        M = inv @ o.matrix_world
        pts = [bl_to_spec(M @ v.co) for v in me.vertices]
        ev.to_mesh_clear()
        lo = [min(p[i] for p in pts) for i in range(3)]
        hi = [max(p[i] for p in pts) for i in range(3)]
        if max(h - l for l, h in zip(lo, hi)) < 0.05:
            continue
        out.append({"part": o.name, "min": [round(x, 4) for x in lo], "max": [round(x, 4) for x in hi]})
    return out


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    res = {"schema": "factory.direction.proxies/1", "frame": "prop-local, spec axes (x right, y up, z forward)",
           "blender": bpy.app.version_string, "props": {}}
    for name, b in sorted(propkit.BUILDERS.items()):
        root = b(f"{name}_proxy")
        res["props"][name] = {"source": f"cloud/blender/props.py:{b.__name__}", "boxes": boxes_of(root)}
    for name, b in sorted(vehicles.BUILDERS.items()):
        if name in res["props"]:
            continue
        root = b(f"{name}_proxy")
        res["props"][name] = {"source": f"cloud/blender/props_vehicles.py:{b.__name__}", "boxes": boxes_of(root)}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(res, fh, indent=1)
    print("PROXIES", OUT, {k: len(v["boxes"]) for k, v in res["props"].items()})


main()
