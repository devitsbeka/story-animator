"""Build a world kit set twice from scratch (no render) and print a digest of the result; identical digests = the
assembler is deterministic for (kit, seed). Used by tests/worlds/test_set_assembly_blender.py.

  blender -b -P cloud/blender/test/set_assembly_determinism.py -- <kit> [seed]
"""
import hashlib
import json
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import set_assembly as SA  # noqa: E402
import lighting  # noqa: E402


def lib_loader(asset_id, rel):
    """Stand-in for render_episode.lib_collection: a 1 m cube collection per asset (no glTF import needed)."""
    name = "LIB_" + asset_id
    if name in bpy.data.collections:
        return bpy.data.collections[name], 1.0
    c = bpy.data.collections.new(name)
    me = bpy.data.meshes.new(name)
    me.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)], [], [(0, 1, 2), (0, 1, 3)])
    c.objects.link(bpy.data.objects.new(name, me))
    return c, 1.0


def build(kit_id, seed):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    kit = SA.load_kit(kit_id)
    shot = SA.shot_with_kit({"id": "T01", "from": 0, "to": 10, "camera": {"keys": []}}, kit)
    lighting.begin_shot({"world": {"moonDir": kit["sky"]["key_dir"], "dawn": 0}}, shot, "legacy")  # no HDRI loads

    def night(env):
        w = bpy.data.worlds.new("w")
        bpy.context.scene.world = w
        return None
    sb = SA.build_set(kit, seed, list(range(0, 10)), 30, night, lib_loader, dict(shot["env"]))
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    bpy.context.scene.collection.objects.link(cam)
    SA.scatter_lod = None  # simple instancing path (LOD planner tiers depend on the camera, not on the kit)
    SA.realize_scatter(sb, cam, list(range(0, 10)), (1080, 1920))
    bpy.context.view_layer.update()
    h = hashlib.sha256()
    rows = []
    for ob in sorted(bpy.data.objects, key=lambda o: o.name):
        mw = [round(x, 4) for r in ob.matrix_world for x in r]
        row = [ob.name, ob.type, mw, ob.instance_collection.name if ob.instance_collection else ""]
        if ob.type == "MESH":
            row.append(len(ob.data.vertices))
            row.append([round(c, 4) for v in list(ob.data.vertices)[:: max(1, len(ob.data.vertices) // 50)] for c in v.co])
        rows.append(row)
    h.update(json.dumps(rows).encode())
    return {"objects": len(rows), "instances": sum(1 for r in rows if r[3]), "meshes": sum(1 for r in rows if r[1] == "MESH"),
            "lights": sum(1 for r in rows if r[1] == "LIGHT"), "digest": h.hexdigest(), "plan_hash": sb.plan["hash"]}


argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
kit_id = argv[0] if argv else "abandoned_city_street"
seed = int(argv[1]) if len(argv) > 1 else None
a, b = build(kit_id, seed), build(kit_id, seed)
c = build(kit_id, (SA.load_kit(kit_id).get("seed", 0) + 1) if seed is None else seed + 1)
print("DETERMINISM " + json.dumps({"a": a, "b": b, "other_seed": c}))
