"""
Export a collision proxy of the yacht (+ the yacht-mounted props an episode uses) for the camera presets and the
shot validator (Blender script; the consumers are pure python: camgeo.YachtProxy).

    blender -b --factory-startup -P factory/direction/export_yacht_proxy.py -- \
        --spec episodes/sentinel/episode_v6.json --out factory/direction/yacht_proxy.json [--cell 0.1]

The proxy is a signed-distance grid in yacht BODY coordinates (spec space: +x starboard, +y up, +z bow), built from
the very geometry the renderer loads (studio/public/assets/props/yacht.glb imported the same way, and every prop
with attach 'yacht' built with cloud/blender/props.py at its spec local/rotY). Each cell stores the distance to
the nearest surface in centimetres, clamped to +-127, negative inside a solid (sign from the nearest face normal,
confirmed by a 3-axis ray-parity vote so thin/open shells do not flip); the hollow cabin interior (every one of
14 rays hits a wall within 12 m) also counts as solid. A camera with sdf < clearance sits inside
or against a wall/console: that is what rendered A02 brown (lens inside the helm/cabin trim) and A04 black (lens
inside the cabin).
"""
import argparse
import base64
import zlib
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "cloud", "blender"))
import props as propkit  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--spec", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--cell", type=float, default=0.1)
ap.add_argument("--yacht", default=None, help="yacht .glb (default: the spec's assets.props.yacht under studio/public)")
args = ap.parse_args(argv)

T = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))   # spec -> Blender (render_episode.T)
TI = T.transposed()

spec = json.load(open(args.spec))
rel = args.yacht or (spec.get("assets", {}).get("props", {}).get("yacht") or "assets/props/yacht.glb")
cands = [rel, os.path.join(REPO, rel), os.path.join(REPO, "studio", "public", rel)]
ypath = next(p for p in cands if os.path.isfile(p))
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
bpy.ops.import_scene.gltf(filepath=ypath)
seen = set()
for sh in spec["shots"]:
    if not sh.get("yacht"):
        continue
    for p in sh.get("props") or []:
        if p.get("attach", "yacht") != "yacht" or p["prop"] not in propkit.BUILDERS:
            continue
        key = (p["prop"], tuple(round(x, 3) for x in p.get("local", (0, 0, 0))), round(p.get("rotY", 0.0), 4))
        if key in seen:
            continue
        seen.add(key)
        r = propkit.BUILDERS[p["prop"]](f"proxy_{p['prop']}_{len(seen)}")
        r.matrix_basis = T @ Matrix.Translation(Vector(p.get("local", (0, 0, 0)))) @ Matrix.Rotation(p.get("rotY", 0.0), 4, "Y") @ TI
bpy.context.view_layer.update()

dg = bpy.context.evaluated_depsgraph_get()
verts, polys = [], []
for o in bpy.data.objects:
    if o.type != "MESH" or o.hide_render:
        continue
    oe = o.evaluated_get(dg)
    me = oe.to_mesh()
    M = TI @ o.matrix_world                       # -> spec body coordinates
    base = len(verts)
    verts += [tuple(M @ v.co) for v in me.vertices]
    polys += [tuple(base + i for i in p.vertices) for p in me.polygons]
    oe.to_mesh_clear()
bvh = BVHTree.FromPolygons(verts, polys, all_triangles=False, epsilon=0.0)
xs, ys, zs = zip(*verts)
pad = 1.0
lo = [math.floor((min(c) - pad) / args.cell) * args.cell for c in (xs, ys, zs)]
hi = [max(c) + pad for c in (xs, ys, zs)]
dims = [int(math.ceil((h - l) / args.cell)) + 1 for l, h in zip(lo, hi)]
print("proxy bbox", lo, hi, "dims", dims, "verts", len(verts), "polys", len(polys), flush=True)

AX = [Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))]


def parity_inside(p):
    """majority vote of +-axis ray parity (odd crossings = inside)."""
    votes = 0
    for d in AX:
        for s in (1, -1):
            n, q = 0, Vector(p)
            dd = d * s
            for _ in range(64):
                hit = bvh.ray_cast(q, dd, 60.0)
                if hit[0] is None:
                    break
                n += 1
                q = hit[0] + dd * 1e-4
            votes += n % 2
    return votes >= 4


DIRS = [Vector(v).normalized() for v in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1),
                                           (1, 1, 1), (1, 1, -1), (-1, 1, 1), (-1, 1, -1), (1, -1, 1), (1, -1, -1), (-1, -1, 1), (-1, -1, -1))]


def enclosed(p, reach=12.0):
    """inside a hollow room (the cabin): every one of 14 rays hits geometry within `reach` m. A lens there sees
    only the inside of the walls (A04 rendered black); the solid test alone calls that open air."""
    for d in DIRS:
        if bvh.ray_cast(p, d, reach)[0] is None:
            return False
    return True


data = bytearray()
CL = 1.27
for i in range(dims[0]):
    x = lo[0] + i * args.cell
    for j in range(dims[1]):
        y = lo[1] + j * args.cell
        for k in range(dims[2]):
            p = Vector((x, y, lo[2] + k * args.cell))
            loc, nrm, idx, dist = bvh.find_nearest(p, CL)
            if loc is None:
                d = CL
            else:
                inside = (p - loc).dot(nrm) < 0
                if inside and dist > 0.03:          # confirm (open shells: normals can lie)
                    inside = parity_inside(p)
                if not inside and enclosed(p):
                    inside = True                 # hollow interior: counts as solid for cameras / sight lines
                d = -dist if inside else dist
            data.append(int(max(-127, min(127, round(d * 100)))) & 0xFF)
out = {"source": os.path.relpath(ypath, REPO), "props": [list(k[:1]) + [list(k[1]), k[2]] for k in sorted(seen)],
       "space": "yacht body (spec): +x starboard, +y up, +z bow", "cell": args.cell, "origin": [round(v, 4) for v in lo],
       "dims": dims, "order": "x-major (i, j, k) -> (i * ny + j) * nz + k", "units": "cm, int8, clamped +-127, <0 inside; zlib-compressed",
       "sdf_zb64": base64.b64encode(zlib.compress(bytes(data), 9)).decode()}
json.dump(out, open(args.out, "w"))
print("PROXY", args.out, dims, len(data), flush=True)
