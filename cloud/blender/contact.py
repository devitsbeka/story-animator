"""
CONTACT: where a character's hands (and seat) must actually touch the set, as named WORLD anchors for
cloudrig_adapter.CloudRigPuppet.set_anchors().

  helm_L / helm_R   the wheel rim of a props.helm_console at 10 and 2 o'clock, grip orientation (palm on the rim,
                    fingers wrapping forward round it) - from the helm's world matrix + props.HELM_WHEEL.
  rail_L / rail_R   snapped at bake time to the nearest point of the yacht's steel rails (BVH of the rail meshes),
                    from wherever the free hand target is (acting pose hold_rail / rail_ahead).
  <spec anchors>    actor.perf.anchors = {"bench_seat": {"p": [x, y, z], "space": "yacht"}, ...} in spec coords
                    (episodes/<id>/plan/marks.py writes them), e.g. the cockpit bench seat for sit_bench.

The anchors are evaluated once before the bake with the yacht at rest (actors and props are children of the yacht
root, so their relative placement is what matters).
"""
import math

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

# props.helm_console wheel (helm-local, Blender axes): centre, tilt about X, rim radius, tube radius
HELM_WHEEL = {"centre": (0.0, -0.33, 1.08), "tilt": 60.0, "radius": 0.2, "tube": 0.014}
GRIP_CLOCK = 58.0      # degrees from 12 o'clock: ~10 and 2


def helm_anchors(M_helm, left_world):
    """{'helm_L': {...}, 'helm_R': {...}} world anchors on the wheel rim of a helm placed at world matrix M_helm.
    left_world = the actor's left direction (world) to tell his left hand's side of the wheel from his right."""
    s = M_helm.to_scale()[0]
    R = M_helm.to_quaternion()
    c = M_helm @ Vector(HELM_WHEEL["centre"])
    t = math.radians(HELM_WHEEL["tilt"])
    a = (R @ Vector((0.0, -math.sin(t), math.cos(t)))).normalized()     # wheel axis (toward the helmsman, up)
    up = Vector((0, 0, 1))
    up = (up - a * up.dot(a)).normalized()
    side = a.cross(up).normalized()
    if side.dot(Vector(left_world)) < 0:
        side = -side
    out = {}
    for key, sgn in (("helm_L", 1.0), ("helm_R", -1.0)):
        ang = math.radians(GRIP_CLOCK)
        radial = (up * math.cos(ang) + side * (sgn * math.sin(ang))).normalized()
        p = c + radial * HELM_WHEEL["radius"] * s
        # car-wheel grip at 10 and 2: palm faces into the wheel (forward, a little toward the hub), the fingers
        # leave the palm outward/up over the rim and curl round it, the thumb lies on top along the rim toward 12.
        # The forearm can then come up from below with the elbow down (no chicken wing).
        n = (-a * 0.75 - radial * 0.35).normalized()
        d = (radial * 0.85 + up * 0.25 - a * 0.2).normalized()
        out[key] = {"p": p, "n": n, "d": d, "kind": "grip"}
    return out


def switch_anchors(M_panel):
    """props.switch_panel: the index fingertip on the third toggle's face (panel front = local -Y)."""
    R = M_panel.to_quaternion()
    fwd = (R @ Vector((0, 1, 0))).normalized()          # from the operator into the panel
    p = M_panel @ Vector((0.03, -0.036, -0.01))
    n = (Vector((0, 0, -1)) * 0.8 + fwd * 0.45).normalized()
    return {"switch_R": {"p": p, "n": n, "d": (fwd - Vector((0, 0, 0.25))).normalized(), "kind": "tip"}}


def bag_anchors(M_bag, left_world):
    """props.trash_bag: both hands on the knot at the top of the sack (origin), palms down, fingers forward."""
    s = M_bag.to_scale()[0]
    c = M_bag @ Vector((0, 0, 0.015))
    lw = Vector(left_world).normalized()
    fwd = lw.cross(Vector((0, 0, 1))).normalized()          # left x up = the actor's forward
    out = {}
    for key, sg in (("bag_L", 1.0), ("bag_R", -1.0)):
        out[key] = {"p": c + lw * (0.045 * s * sg), "n": Vector((-sg * lw.x * 0.5, -sg * lw.y * 0.5, -0.85)).normalized(),
                    "d": fwd, "kind": "grip"}
    return out


def spec_anchors(perf, yacht_root, b3):
    """actor.perf.anchors in spec coords -> world anchors (spec 'yacht' space through the yacht root)."""
    out = {}
    M = yacht_root.matrix_world if yacht_root is not None else Matrix.Identity(4)
    R = M.to_quaternion()
    for name, a in ((perf or {}).get("anchors") or {}).items():
        sp = a.get("space", "yacht")
        Mx = M if sp == "yacht" else Matrix.Identity(4)
        e = {"p": Mx @ b3(a["p"]), "kind": a.get("kind")}
        if a.get("n") is not None:
            e["n"] = (R if sp == "yacht" else Matrix.Identity(3).to_quaternion()) @ b3(a["n"])
        if a.get("d") is not None:
            e["d"] = (R if sp == "yacht" else Matrix.Identity(3).to_quaternion()) @ b3(a["d"])
        out[name] = e
    return out


def rail_snapper(objects, max_dist=0.45, tube=0.02):
    """BVH over the yacht's rail meshes (steel material, long and thin). Returns snap(world p) -> (centre, tangent)
    or None, or returns None when there are no rails."""
    verts, polys = [], []
    for o in objects:
        if o.type != "MESH" or not o.data.polygons:
            continue
        mats = " ".join((s.material.name.lower() if s.material else "") for s in o.material_slots)
        if "steel" not in mats and "rail" not in o.name.lower():
            continue
        bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
        ext = sorted(max(v[i] for v in bb) - min(v[i] for v in bb) for i in range(3))
        if ext[2] < 1.2:          # posts, stanchions, antenna: not a rail
            continue
        base = len(verts)
        verts += [o.matrix_world @ v.co for v in o.data.vertices]
        polys += [[base + i for i in p.vertices] for p in o.data.polygons]
    if not polys:
        return None
    bvh = BVHTree.FromPolygons(verts, polys)

    def snap(p):
        p = Vector(p)
        hit = bvh.find_nearest(p, max_dist)
        if hit[0] is None:
            return None
        loc, nrm = hit[0], hit[1]
        centre = loc - nrm * tube
        best, tan = 0.0, Vector((1, 0, 0))
        for e in (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0.707, 0.707, 0)), Vector((0.707, -0.707, 0))):
            h1, h2 = bvh.find_nearest(loc + e * 0.08, 0.3), bvh.find_nearest(loc - e * 0.08, 0.3)
            if h1[0] is None or h2[0] is None:
                continue
            v = h1[0] - h2[0]
            if v.length > best:
                best, tan = v.length, v.normalized()
        return centre, tan
    return snap


def actor_anchors(actor, shot, yacht_root, holder, b3, obj_mat, trans, rot_y, yacht_objects=None):
    """everything a CloudRig actor can touch in this shot -> (world anchors, rail snap callable | None)."""
    bpy.context.view_layer.update()
    anchors = {}
    left = (holder.matrix_world.to_quaternion() @ Vector((1, 0, 0))).normalized()
    for p in shot.get("props") or []:
        if p.get("prop") == "helm" and p.get("attach", "yacht") == "yacht":
            M = obj_mat(trans(p.get("local", (0, 0, 0))) @ rot_y(p.get("rotY", 0.0))) @ Matrix.Scale(p.get("scale", 1.0), 4)
            if yacht_root is not None:
                M = yacht_root.matrix_world @ M
            anchors.update(helm_anchors(M, left))
        if p.get("prop") in ("switches", "bag") and p.get("attach", "yacht") == "yacht":
            M = obj_mat(trans(p.get("local", (0, 0, 0))) @ rot_y(p.get("rotY", 0.0))) @ Matrix.Scale(p.get("scale", 1.0), 4)
            if yacht_root is not None:
                M = yacht_root.matrix_world @ M
            anchors.update(switch_anchors(M) if p["prop"] == "switches" else bag_anchors(M, left))
    anchors.update(spec_anchors(actor.get("perf"), yacht_root, b3))
    snap = rail_snapper(yacht_objects) if yacht_objects else None
    return anchors, snap
