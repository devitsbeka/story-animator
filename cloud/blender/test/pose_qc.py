"""Pose QC on an episode's shot list (lessons L009 / L010), in Blender, no rendering.

  blender -b --factory-startup -P cloud/blender/test/pose_qc.py -- [--spec episodes/sentinel/episode_v5.json] \
      [--shots A01a,C13] [--out /tmp/pose_qc.json] [--strict]

For every shot with a CloudRig hero (spec.assets.characters.<id>.kind == "blend"), the actor is placed on its mark in
yacht-local space and its performance baked through the production adapter (cloudrig_adapter.CloudRigPuppet, as
render_episode.py does); hand props are attached to the same bones. At the key frame (and the middle of each pose
window) it measures:
  seat gap      lowest pelvis/buttock skin vertex vs the top of the seat surface under it (yacht proxies from
                factory/direction/proxies/yacht.json, or the mark's floor) - seated stances only
  spine pitch   DEF-Spine head -> DEF-Neck head, degrees from vertical in the actor's facing plane (+ = forward)
  finger curl   mean flexion (carpal->1->2->3 bone angles) of index..pinky per hand
  grip distance palm centre (mean of the finger carpal bones) -> surface of each prop held in that hand
and evaluates cloud/blender/pose_rules.py. Writes JSON {measurements, findings, summary}; --strict exits 1 on failure.
"""
import argparse
import json
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
BL = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(BL))
sys.path.insert(0, BL)
import cloudrig_adapter as cra  # noqa: E402
import pose_rules  # noqa: E402
import props as propkit  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--spec", default=None)
ap.add_argument("--shots", default=None)
ap.add_argument("--out", default=None)
ap.add_argument("--strict", action="store_true")
ap.add_argument("--max-frames", type=int, default=3, help="frames measured per shot (key frame + pose windows)")
ap.add_argument("--full-clip", action="store_true", help="bake the whole shot and measure face-life (frozen face) over it")
args = ap.parse_args(argv)

if args.spec is None:
    import glob
    import re
    cands = glob.glob(os.path.join(REPO, "episodes", "sentinel", "episode_v*.json"))
    args.spec = max(cands, key=lambda p: int(re.search(r"_v(\d+)\.json$", p).group(1)))
SPEC = json.load(open(args.spec))
LIB = os.environ.get("LIBRARY_STORE") or os.path.join(REPO, "library_store")
FINGERS = ("Index", "Middle", "Ring", "Pinky")


def spec_v(v):            # Blender world -> spec axes (x right, y up, z forward)
    return Vector((v.x, v.z, -v.y))


def bl_mat(local, roty, scale=1.0):
    from mathutils import Matrix
    T = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    m3 = Matrix.Translation(Vector(local)) @ Matrix.Rotation(roty, 4, "Y")
    return T @ m3 @ T.inverted() @ Matrix.Scale(scale, 4)


def char_file(entry):
    f = entry.get("file", "")
    for p in (f, os.path.join(REPO, f), os.path.join(LIB, f.replace("library_store/", "", 1)),
              os.path.join(LIB, "characters", "hero_v4", os.path.basename(f))):
        if p and os.path.isfile(p):
            return p
    return None


def seat_surfaces():
    p = os.path.join(REPO, "factory", "direction", "proxies", "yacht.json")
    if not os.path.exists(p):
        return []
    return [b for b in json.load(open(p))["boxes"] if max(b["max"][i] - b["min"][i] for i in (0, 2)) > 0.3]


SEATS = seat_surfaces()


def seat_top_under(x, z, y_max, floor):
    tops = [b["max"][1] for b in SEATS if b["min"][0] <= x <= b["max"][0] and b["min"][2] <= z <= b["max"][2] and b["max"][1] <= y_max]
    return max(tops + [floor])


def keyed_step(keys, f, default=1.0):
    v = default
    for k in sorted(keys or [], key=lambda k: k[0]):
        if k[0] <= f:
            v = k[1]
    return v


def stance_at(perf, f):
    st = "stand"
    for k in sorted(perf.get("stance") or [], key=lambda k: k[0]):
        if k[0] <= f:
            st = k[1]
    return st


def hand_shapes(perf, f):
    shapes = {"L": "unset", "R": "unset"}
    h = perf.get("hands")
    if isinstance(h, dict):
        shapes.update({k: v for k, v in h.items() if k in shapes})
    elif isinstance(h, list):
        for k in sorted(h, key=lambda k: k[0]):
            if k[0] <= f:
                shapes = {"L": k[1], "R": k[2] if len(k) > 2 else k[1]}
    for p in perf.get("poses") or []:
        if p.get("from", 0) <= f <= p.get("to", -1) and p.get("hand_shape"):
            hs = p["hand_shape"]
            shapes.update(hs if isinstance(hs, dict) else {"L": hs, "R": hs})
    return shapes


def finger_curl(arm, side):
    pb = arm.pose.bones
    vals = []
    for fn in FINGERS:
        chain = [pb.get(f"DEF-Finger_{fn}_Carpal.{side}")] + [pb.get(f"DEF-Finger_{fn}{i}.{side}") for i in (1, 2, 3)]
        chain = [b for b in chain if b is not None]
        if len(chain) < 3:
            continue
        vs = [(b.tail - b.head).normalized() for b in chain]
        vals.append(sum(math.degrees(a.angle(b)) for a, b in zip(vs, vs[1:])))
    return sum(vals) / len(vals) if vals else None


def palm_centre(arm, side):
    pts = []
    for fn in FINGERS:
        b = arm.pose.bones.get(f"DEF-Finger_{fn}_Carpal.{side}")
        if b is not None:
            pts += [arm.matrix_world @ b.head, arm.matrix_world @ b.tail]
    return sum(pts, Vector()) / len(pts) if pts else None


def wrist_bend(arm, side):
    pb = arm.pose.bones
    fa = pb.get(f"DEF-Forearm2.{side}") or pb.get(f"DEF-Forearm1.{side}")
    mid = pb.get(f"DEF-Finger_Middle_Carpal.{side}")
    if fa is None or mid is None:
        return None
    return math.degrees((fa.tail - fa.head).angle(mid.tail - mid.head))


def palm_normal(arm, side):
    """Palm-side normal from the carpal fan (index/pinky across x middle along); orientation per side chosen so it
    points out of the palm for the rig's bone layout (left = mirrored)."""
    pb = arm.pose.bones
    i, p, m = (pb.get(f"DEF-Finger_{n}_Carpal.{side}") for n in ("Index", "Pinky", "Middle"))
    if None in (i, p, m):
        return None
    W = arm.matrix_world.to_3x3()
    across = W @ (i.tail - p.tail)
    along = W @ (m.tail - m.head)
    n = along.cross(across).normalized()
    return n if side == "R" else -n


def _rest_world3(arm, name):
    b = arm.data.bones.get(name)
    return None if b is None else arm.matrix_world.to_3x3().normalized() @ b.matrix_local.to_3x3()


def foot_metrics(arm, side, floor):
    """Planted-foot measurements (L017 class: feet must sit flat with a natural ankle).
    tilt   deg between the foot's posed and rest 'up' axes in world space (pitch + roll; yaw is free) -> flat sole
    gap    m, (posed ball height above the floor under it) - (rest ball height above the rest ground) -> contact
    ankle  deg, posed shin->foot angle minus the rest angle (+ = plantarflexion / toes down) -> natural ankle"""
    pb = arm.pose.bones
    foot, toes, shin = pb.get(f"DEF-Foot.{side}"), pb.get(f"DEF-Toes.{side}"), pb.get(f"DEF-Knee2.{side}")
    if foot is None or toes is None:
        return None
    W = arm.matrix_world
    rest = _rest_world3(arm, foot.name)
    posed = W.to_3x3().normalized() @ foot.matrix.to_3x3()
    up = Vector((0.0, 0.0, 1.0))
    r_up = (rest.inverted() @ up)
    tilt = math.degrees((posed @ r_up).angle(up))
    s_arm = W.to_scale()[2] or 1.0
    rb = arm.data.bones[toes.name].head_local
    rest_ball_h = (rb.z - min(arm.data.bones[toes.name].tail_local.z, rb.z, 0.0)) * s_arm
    ball = W @ toes.head
    ground = seat_top_under(ball.x, -ball.y, ball.z + 0.05, floor)
    gap = (ball.z - ground) - rest_ball_h
    ankle = None
    if shin is not None:
        rs, rf = arm.data.bones[shin.name], arm.data.bones[foot.name]
        a_rest = math.degrees((rs.tail_local - rs.head_local).angle(rf.tail_local - rf.head_local))
        a_pose = math.degrees((shin.tail - shin.head).angle(foot.tail - foot.head))
        ankle = a_pose - a_rest
    return {"tilt_deg": tilt, "gap_m": gap, "ankle_dev_deg": ankle}


def relaxed_palm_angle(arm, side):
    """deg between the palm normal and the horizontal direction from the palm to the body midline (relaxed hands hang
    with palms toward the thighs). None when the hand is not hanging at the side (above the pelvis)."""
    pb = arm.pose.bones
    pc, nrm, spine = palm_centre(arm, side), palm_normal(arm, side), pb.get("DEF-Spine")
    if pc is None or nrm is None or spine is None:
        return None
    pel = arm.matrix_world @ spine.head
    if pc.z > pel.z + 0.05:
        return None
    to_mid = Vector((pel.x - pc.x, pel.y - pc.y, 0.0))
    if to_mid.length < 1e-4:
        return None
    return math.degrees(nrm.angle(to_mid))


def surface_point(p, objs):
    best = None
    for o in objs:
        if o.type != "MESH":
            continue
        ok, loc, _n, _i = o.closest_point_on_mesh(o.matrix_world.inverted() @ p)
        if ok:
            w = o.matrix_world @ loc
            if best is None or (w - p).length < (best - p).length:
                best = w
    return best


def face_life(arm, pup, f0, f1, fps=30):
    bones = [pb for pb in pup._controls()] if hasattr(pup, "_controls") else []
    head = arm.pose.bones.get("DEF-Head")
    prev, deltas = None, []
    sc = bpy.context.scene
    for f in range(f0, f1):
        sc.frame_set(f)
        vec = []
        for pb in bones:
            vec += list(pb.location) + list(pb.rotation_euler)
        if head is not None:
            vec += list(head.matrix.to_quaternion())
        if prev is not None:
            deltas.append(sum(abs(a - b) for a, b in zip(vec, prev)) / max(1, len(vec)))
        prev = vec
    run = best = 0
    for d in deltas:
        run = run + 1 if d < 1e-5 else 0
        best = max(best, run)
    return {"frozen_max_s": best / fps, "motion": sum(deltas) / max(1, len(deltas)) * 100, "frames": len(deltas) + 1}


def surface_dist(p, objs):
    best = None
    for o in objs:
        if o.type != "MESH":
            continue
        inv = o.matrix_world.inverted()
        ok, loc, _n, _i = o.closest_point_on_mesh(inv @ p)
        if ok:
            d = (o.matrix_world @ loc - p).length
            best = d if best is None else min(best, d)
    return best


def pelvis_skin_y(arm, meshes, pelvis_w, radius):
    dg = bpy.context.evaluated_depsgraph_get()
    low = None
    for o in meshes:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        M = o.matrix_world
        for v in me.vertices:
            w = M @ v.co
            if (w.x - pelvis_w.x) ** 2 + (w.y - pelvis_w.y) ** 2 <= radius * radius and w.z < pelvis_w.z + 0.05:
                low = w.z if low is None else min(low, w.z)
        ev.to_mesh_clear()
    return low


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    chars = SPEC.get("assets", {}).get("characters", {})
    want = set(args.shots.split(",")) if args.shots else None
    rigs, measurements, findings = {}, [], []
    for shot in SPEC["shots"]:
        if want and shot["id"] not in want:
            continue
        for a in shot.get("actors") or []:
            entry = chars.get(a.get("asset"))
            if not isinstance(entry, dict) or entry.get("kind") != "blend":
                continue
            if a["asset"] not in rigs:
                path = char_file(entry)
                if not path:
                    print(f"POSEQC skip {a['asset']}: file not found")
                    rigs[a["asset"]] = None
                    continue
                coll, arm, objs = cra.append_character(path, entry.get("collection", "CH-jay"), entry.get("rig", "RIG-jay"))
                holder = bpy.data.objects.new(f"holder_{a['asset']}", None)
                sc.collection.objects.link(holder)
                for o in objs:
                    if o.parent is None:
                        o.parent = holder
                cra.set_character_options(arm, entry.get("options", {"Glasses": 0}))
                meshes = [o for o in objs if o.type == "MESH" and any(k in o.name for k in ("joggers", "pants", "body"))]
                rigs[a["asset"]] = (arm, holder, meshes)
            if rigs[a["asset"]] is None:
                continue
            arm, holder, meshes = rigs[a["asset"]]
            h = cra.natural_height(arm)
            scale = float(a.get("height") or entry.get("height") or h) / h
            holder.matrix_basis = bl_mat(a["local"], a.get("rotY", 0.0), scale)
            perf = a.get("perf") or {"stance": [[-10000, "stand"]]}
            key = int(shot.get("keyFrame", (shot["from"] + shot["to"]) // 2))
            frames = [key] + [int((p["from"] + p["to"]) // 2) for p in perf.get("poses") or []
                              if shot["from"] <= (p["from"] + p["to"]) // 2 < shot["to"]]
            frames = sorted(set(frames))[:args.max_frames]
            pup = cra.CloudRigPuppet(arm, holder)
            b0, b1 = (shot["from"] - 1, shot["to"] + 1) if args.full_clip else (min(frames) - 1, max(frames) + 1)
            pup.bake(perf, a.get("face") or perf.get("face") or {"seed": perf.get("seed", 1)}, b0, b1)
            fl = face_life(arm, pup, shot["from"], shot["to"]) if args.full_clip else None
            # hand props
            props = []
            for i, p in enumerate(shot.get("props") or []):
                att = p.get("attach")
                if att not in ("handR", "handL") or p.get("prop") not in propkit.BUILDERS:
                    continue
                root = propkit.BUILDERS[p["prop"]](f"qc_{p['prop']}_{i}")
                root.parent = arm
                root.parent_type = "BONE"
                root.parent_bone = cra.BONE_ALIAS.get(att, "DEF-Wrist." + att[-1])
                from mathutils import Matrix
                root.matrix_parent_inverse = Matrix.Identity(4)
                s_arm = arm.matrix_world.to_scale()[0] or 1.0
                root.location = Vector(p.get("local", (0, 0, 0))) / s_arm
                root.rotation_euler = tuple(math.radians(x) for x in p.get("rot", (0, 0, 0)))
                root.scale = (p.get("scale", 1.0) / s_arm,) * 3
                props.append((p, att[-1], root))
            for f in frames:
                sc.frame_set(f)
                bpy.context.view_layer.update()
                stance = stance_at(perf, f)
                pb = arm.pose.bones
                spine, neck = pb.get("DEF-Spine"), pb.get("DEF-Neck")
                pel_w = arm.matrix_world @ spine.head
                v = spec_v(arm.matrix_world @ neck.head) - spec_v(pel_w)
                r = a.get("rotY", 0.0)
                fwd = Vector((math.sin(r), 0.0, math.cos(r)))
                pitch = math.degrees(math.atan2(v.dot(fwd), v.y))
                seated = stance.startswith("sit")
                gap = None
                if seated:
                    ps = spec_v(pel_w)
                    skin = pelvis_skin_y(arm, meshes, pel_w, 0.12 * scale)
                    top = seat_top_under(ps.x, ps.z, ps.y + 0.05, a["local"][1])
                    gap = None if skin is None else skin - top
                grips = []
                for p, side, root in props:
                    if keyed_step(p.get("show"), f, 1.0) < 0.5:
                        continue
                    pc = palm_centre(arm, side)
                    objs_p = [root] + list(root.children_recursive)
                    d = surface_dist(pc, objs_p) if pc is not None else None
                    sp = surface_point(pc, objs_p) if pc is not None else None
                    nrm = palm_normal(arm, side)
                    ang = math.degrees(nrm.angle(sp - pc)) if (nrm is not None and sp is not None and (sp - pc).length > 1e-4) else None
                    grips.append({"prop": p["prop"], "hand": side, "dist_m": d, "palm_angle_deg": ang})
                m = {"shot": shot["id"], "frame": f, "stance": stance, "seated": seated, "seat_gap_m": gap,
                     "spine_pitch_deg": pitch, "finger_curl_deg": {"L": finger_curl(arm, "L"), "R": finger_curl(arm, "R")},
                     "hand_shape": hand_shapes(perf, f), "grips": grips, "allow_lean_back": bool(perf.get("allow_lean_back")),
                     "wrist_bend_deg": {"L": wrist_bend(arm, "L"), "R": wrist_bend(arm, "R")},
                     "face_life": fl if f == frames[0] else None,
                     "feet": {sd: foot_metrics(arm, sd, a["local"][1]) for sd in ("L", "R")},
                     "relaxed_palm_deg": {sd: relaxed_palm_angle(arm, sd) for sd in ("L", "R")}}
                fs = pose_rules.evaluate(m)
                measurements.append(m)
                findings += fs
                bad = [x["rule"] for x in fs if x["status"] == "fail"]
                print(f"POSEQC {shot['id']} f{f} {stance:9s} pitch {pitch:6.1f} curl L{m['finger_curl_deg']['L'] or 0:5.1f} "
                      f"R{m['finger_curl_deg']['R'] or 0:5.1f} gap {gap} grips {[(g['prop'], g['dist_m'] and round(g['dist_m'], 3)) for g in grips]} -> {bad or 'ok'}")
            for p, side, root in props:
                for o in [root] + list(root.children_recursive):
                    bpy.data.objects.remove(o, do_unlink=True)
            if arm.animation_data and arm.animation_data.action:
                arm.animation_data.action = None
    summ = pose_rules.summarize(findings)
    doc = {"schema": "factory.pose_qc/1", "spec": os.path.relpath(args.spec, REPO), "measurements": measurements,
           "findings": [f for f in findings if f["status"] != "pass"], "summary": summ}
    out = args.out or os.path.join("/tmp", "pose_qc.json")
    with open(out, "w") as fh:
        json.dump(doc, fh, indent=1, default=str)
    print("POSEQC SUMMARY", json.dumps(summ), "->", out)
    if args.strict and not summ["ok"]:
        sys.exit(1)


main()
