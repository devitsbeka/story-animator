#!/usr/bin/env python3
"""Collision proxies for the camera-inside-geometry check (lesson L012: A02 rendered brown and A04 black because the
camera sat inside the cabin).

Proxies are boxes in the spec convention (x right, y up, z forward; metres):
  * yacht  - read straight from the yacht glTF (no Blender): one box per solid part node (cabin, flybridge, glass,
             upholstery, fenders, small fittings) from the accessor bounds and node matrices, plus the HULL as a
             z-sliced solid (per 0.5 m slab: half-beam and keel from the hull vertices, up to the deck at 1.33 m).
             Thin shells that a camera may legitimately be inside the bounds of (rails, the deck plate) are skipped.
  * props  - factory/direction/proxies/props.json, exported in Blender by cloud/blender/test/export_prop_proxies.py.

    python3 factory/direction/mesh_proxy.py export [--glb assets/props/yacht.glb]   -> proxies/yacht.json
    python3 factory/direction/mesh_proxy.py check episodes/sentinel/episode_v5.json  -> per-shot hits
"""
import argparse
import json
import math
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import camgeo as G  # noqa: E402

PROXY_DIR = os.path.join(HERE, "proxies")
DECK_Y = 1.33               # top of the hull solid (deck plate underside)
MARGIN = 0.05               # camera near plane: closer than this to a solid face counts as inside
SOLID_PARTS = re.compile(r"^(gelcoat_white|glass_cabin|upholstery|fender|teak_2)")
SMALL_PART_M = 1.0          # other parts (steel posts, nav lights) only when every extent is below this
ENCLOSURES = {"cargo_hold", "rotor_wash", "beach_torches"}   # sets the camera is meant to be inside / non-solid FX
COARSE_M = 8.0              # prop boxes larger than this are merged material layers, not solids


# ------------------------------------------------------------------ glTF reading (no deps)
def read_glb(path):
    with open(path, "rb") as fh:
        b = fh.read()
    magic, _ver, _ln = struct.unpack("<III", b[:12])
    if magic != 0x46546C67:
        raise ValueError(f"{path}: not a GLB")
    off, js, binc = 12, None, b""
    while off < len(b):
        cl, ct = struct.unpack("<II", b[off:off + 8])
        chunk = b[off + 8:off + 8 + cl]
        if ct == 0x4E4F534A:
            js = json.loads(chunk)
        elif ct == 0x004E4942:
            binc = chunk
        off += 8 + cl
    return js, binc


def mat_mul(a, b):  # column-major 4x4 (glTF)
    return [sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4)) for c in range(4) for r in range(4)]


def node_matrix(n):
    if "matrix" in n:
        return list(n["matrix"])
    t = n.get("translation", [0, 0, 0])
    x, y, z, w = n.get("rotation", [0, 0, 0, 1])
    s = n.get("scale", [1, 1, 1])
    R = [1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w), 0,
         2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w), 0,
         2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y), 0, 0, 0, 0, 1]
    for c in range(3):
        for r in range(3):
            R[c * 4 + r] *= s[c]
    R[12:15] = t
    return R


def xform(M, p):
    return [M[0] * p[0] + M[4] * p[1] + M[8] * p[2] + M[12], M[1] * p[0] + M[5] * p[1] + M[9] * p[2] + M[13],
            M[2] * p[0] + M[6] * p[1] + M[10] * p[2] + M[14]]


def corners(lo, hi):
    return [[(lo, hi)[i][0], (lo, hi)[j][1], (lo, hi)[k][2]] for i in (0, 1) for j in (0, 1) for k in (0, 1)]


def positions(js, binc, acc_i):
    a = js["accessors"][acc_i]
    bv = js["bufferViews"][a["bufferView"]]
    start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride") or 12
    return [struct.unpack_from("<3f", binc, start + i * stride) for i in range(a["count"])]


def export_yacht(glb):
    js, binc = read_glb(glb)
    world = {}

    def walk(i, M):
        n = js["nodes"][i]
        W = mat_mul(M, node_matrix(n))
        world[i] = W
        for c in n.get("children", []):
            walk(c, W)
    I4 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    for r in js["scenes"][js.get("scene", 0)]["nodes"]:
        walk(r, I4)
    boxes, hull = [], None
    for i, n in enumerate(js["nodes"]):
        if n.get("mesh") is None:
            continue
        name = n.get("name", f"node{i}")
        W = world[i]
        lo, hi = [1e9] * 3, [-1e9] * 3
        for p in js["meshes"][n["mesh"]]["primitives"]:
            a = js["accessors"][p["attributes"]["POSITION"]]
            for c in corners(a["min"], a["max"]):
                q = xform(W, c)
                lo = [min(u, v) for u, v in zip(lo, q)]
                hi = [max(u, v) for u, v in zip(hi, q)]
        if name.startswith("gelcoat_hull"):
            pts = [xform(W, p) for pr in js["meshes"][n["mesh"]]["primitives"] for p in positions(js, binc, pr["attributes"]["POSITION"])]
            hull = hull_slabs(pts)
            continue
        ext = [h - l for l, h in zip(lo, hi)]
        if SOLID_PARTS.match(name) or max(ext) < SMALL_PART_M:
            box = {"part": name, "min": [round(x, 4) for x in lo], "max": [round(x, 4) for x in hi]}
            if max(ext) >= SMALL_PART_M:
                # tapered / rounded parts (cabin, flybridge): per-z-slab x and y ranges of the actual vertices
                tris = [[xform(W, p) for p in t] for pr in js["meshes"][n["mesh"]]["primitives"] for t in triangles(js, binc, pr)]
                box["slabs"] = part_slabs(tris)
            boxes.append(box)
    return {"schema": "factory.direction.proxies/1", "source": os.path.relpath(glb, ROOT), "frame": "yacht body (spec axes)",
            "deck_y": DECK_Y, "hull": hull, "boxes": boxes}


def hull_slabs(pts, dz=0.5):
    zs = [p[2] for p in pts]
    z0, z1 = math.floor(min(zs) / dz) * dz, math.ceil(max(zs) / dz) * dz
    out = []
    z = z0
    while z < z1 - 1e-9:
        sl = [p for p in pts if z - 1e-6 <= p[2] <= z + dz + 1e-6]
        if sl:
            # half-beam at deck level of the slab (widest point below the deck), keel = lowest vertex
            hw = max(abs(p[0]) for p in sl if p[1] <= DECK_Y + 0.6) if any(p[1] <= DECK_Y + 0.6 for p in sl) else 0.0
            out.append({"z": [round(z, 3), round(z + dz, 3)], "half_beam": round(hw, 4), "keel": round(min(p[1] for p in sl), 4)})
        z += dz
    return out


def triangles(js, binc, prim):
    pos = positions(js, binc, prim["attributes"]["POSITION"])
    if prim.get("indices") is None:
        idx = list(range(len(pos)))
    else:
        a = js["accessors"][prim["indices"]]
        bv = js["bufferViews"][a["bufferView"]]
        fmt = {5121: "B", 5123: "H", 5125: "I"}[a["componentType"]]
        start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        idx = list(struct.unpack_from(f"<{a['count']}{fmt}", binc, start))
    return [(pos[idx[i]], pos[idx[i + 1]], pos[idx[i + 2]]) for i in range(0, len(idx) - 2, 3)]


def _section_points(tris, z0, z1):
    """Vertices inside [z0, z1] plus every triangle-edge crossing of the planes z0 and z1 (exact cross-section bounds
    of a convex part, even where the mesh has no vertex inside the slab)."""
    out = []
    for t in tris:
        for p in t:
            if z0 <= p[2] <= z1:
                out.append(p)
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            for zc in (z0, z1):
                if (a[2] - zc) * (b[2] - zc) < 0:
                    u = (zc - a[2]) / (b[2] - a[2])
                    out.append((a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1]), zc))
    return out


def part_slabs(tris, dz=0.25):
    zs = [p[2] for t in tris for p in t]
    z0 = math.floor(min(zs) / dz) * dz
    out, z = [], z0
    while z < max(zs) - 1e-9:
        sl = _section_points(tris, z, z + dz)
        if sl:
            out.append({"z": [round(z, 3), round(z + dz, 3)], "x": [round(min(p[0] for p in sl), 4), round(max(p[0] for p in sl), 4)],
                        "y": [round(min(p[1] for p in sl), 4), round(max(p[1] for p in sl), 4)]})
        z += dz
    return out


# ------------------------------------------------------------------ loading + queries
_CACHE = {}


def load(name):
    if name not in _CACHE:
        p = os.path.join(PROXY_DIR, f"{name}.json")
        _CACHE[name] = json.load(open(p)) if os.path.exists(p) else None
    return _CACHE[name]


def inside_box(p, b, margin=MARGIN):
    if not all(b["min"][i] - margin < p[i] < b["max"][i] + margin for i in range(3)):
        return False
    if b.get("slabs"):
        for s in b["slabs"]:
            if s["z"][0] - margin <= p[2] < s["z"][1] + margin and s["x"][0] - margin < p[0] < s["x"][1] + margin \
                    and s["y"][0] - margin < p[1] < s["y"][1] + margin:
                return True
        return False
    return True


def in_hull_solid(b, hull, margin=MARGIN):
    for s in hull or []:
        if s["z"][0] <= b[2] < s["z"][1]:
            return abs(b[0]) < s["half_beam"] + margin and s["keel"] - margin < b[1] < DECK_Y + margin
    return False


def yacht_hits(body_p, proxies=None):
    px = proxies or load("yacht")
    if not px:
        return []
    hits = ["hull"] if in_hull_solid(body_p, px.get("hull")) else []
    return hits + [b["part"] for b in px["boxes"] if inside_box(body_p, b)]


def prop_boxes(p):
    """World/yacht-frame AABBs of one spec prop entry (attach yacht|world), from props.json."""
    lib = load("props") or {"props": {}}
    ent = lib["props"].get(p.get("prop"))
    if not ent or p.get("attach", "yacht") not in ("yacht", "world") or p.get("prop") in ENCLOSURES:
        return []
    loc, ry, s = p.get("local", [0, 0, 0]), p.get("rotY", 0.0), p.get("scale", 1.0)
    out = []
    for b in ent["boxes"]:
        if max(h - l for l, h in zip(b["min"], b["max"])) * s > COARSE_M:
            continue   # a merged multi-part mesh (a 150 m ship's paint layer): its bounds are not a solid
        cs = [G.rot_yv(ry, [c[0] * s, c[1] * s, c[2] * s]) for c in corners(b["min"], b["max"])]
        cs = [[c[0] + loc[0], c[1] + loc[1], c[2] + loc[2]] for c in cs]
        out.append({"part": f"{p['prop']}:{b['part']}", "min": [min(c[i] for c in cs) for i in range(3)],
                    "max": [max(c[i] for c in cs) for i in range(3)], "attach": p.get("attach", "yacht")})
    return out


def shot_hits(shot, step=3):
    """-> [(frame, [parts])] for sampled frames where the camera is inside a proxy (yacht or props)."""
    f0, f1 = shot["from"], shot["to"] - 1
    y = shot.get("yacht")
    pboxes = [b for p in shot.get("props") or [] for b in prop_boxes(p)]
    out = []
    for f in list(range(f0, f1 + 1, step)) + ([f1] if (f1 - f0) % step else []):
        cam = G.camera_world(shot, f, jitter=False)[0]
        hits = []
        body = G.YachtFrame(y, f).world_to_body(cam) if y else None
        if body is not None:
            hits += yacht_hits(body)
        for b in pboxes:
            p = body if b["attach"] == "yacht" else cam
            if p is not None and inside_box(p, b):
                hits.append(b["part"])
        if hits:
            out.append((f, hits))
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--glb", default=os.path.join(ROOT, "assets", "props", "yacht.glb"))
    e.add_argument("--out", default=os.path.join(PROXY_DIR, "yacht.json"))
    c = sub.add_parser("check")
    c.add_argument("episode")
    a = ap.parse_args()
    if a.cmd == "export":
        d = export_yacht(a.glb)
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        json.dump(d, open(a.out, "w"), indent=1)
        print(f"wrote {a.out}: {len(d['boxes'])} boxes, {len(d['hull'] or [])} hull slabs")
        return 0
    ep = json.load(open(a.episode))
    bad = 0
    for s in ep["shots"]:
        h = shot_hits(s)
        if h:
            bad += 1
            print(f"{s['id']}: camera inside {sorted({p for _, ps in h for p in ps})} on frames {[f for f, _ in h][:8]}")
    print(f"{bad} shot(s) with the camera inside geometry")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
