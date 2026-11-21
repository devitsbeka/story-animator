"""
QC for the hero_v4 asset: turnaround sheet (front, 3/4, side, back) + 4 extreme-pose checks (arms raised,
crouch, twist, reach forward) posed by keying the CloudRig IK/FK controls of RIG-jay, plus numeric checks
(cap follows head rigidly, face rig still deforms the head, glasses/chain gone, no broken drivers).

Usage:
  blender -b -y <hero_v4.blend> --python factory/characters/check_hero_v4.py -- \
      [--out assets/characters/hero_v4] [--tmp /tmp/wardrobe/qc] [--samples 24] [--only turn|poses|numeric]
Renders: 360x540 per view, Cycles, 2 threads; sheets are composited with numpy.
"""
import argparse
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="assets/characters/hero_v4")
ap.add_argument("--tmp", default="/tmp/wardrobe/qc")
ap.add_argument("--samples", type=int, default=24)
ap.add_argument("--only", default="all")
args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
os.makedirs(args.out, exist_ok=True)
os.makedirs(args.tmp, exist_ok=True)

D = bpy.data
sc = bpy.context.scene
rig = D.objects["RIG-jay"]
P = rig.pose.bones
RESULT = {}


def log(*a):
    print("[qc]", *a, flush=True)


# ---------------------------------------------------------------------------------------------- posing helpers
def reset_pose():
    # drop keys from the previous check pose, otherwise animation re-evaluation at render time restores them
    if rig.animation_data and rig.animation_data.action:
        act = rig.animation_data.action
        rig.animation_data.action = None
        if act.users == 0:
            D.actions.remove(act)
    for pb in P:
        pb.location = (0, 0, 0); pb.rotation_quaternion = (1, 0, 0, 0); pb.rotation_euler = (0, 0, 0)
        pb.scale = (1, 1, 1)
    for side, s in (("L", "left"), ("R", "right")):  # make sure limbs are in IK (CloudRig switch props)
        P["PRP-UpperArm." + side]["ik_%s_arm" % s] = 1.0
        P["PRP-Thigh." + side]["ik_%s_leg" % s] = 1.0
    bpy.context.view_layer.update()


def place(name, loc=None, rot=None, key=True, frame=1):
    """Put a control at an armature-space location and/or apply an extra armature-space rotation (Euler deg),
    then key its local channels (what an animator keys)."""
    pb = P[name]
    m = pb.matrix.copy()
    t = m.to_translation() if loc is None else Vector(loc)
    r3 = m.to_3x3().normalized()
    if rot is not None:
        r3 = Euler([math.radians(a) for a in rot], "XYZ").to_matrix() @ r3
    pb.matrix = Matrix.Translation(t) @ r3.to_4x4()
    bpy.context.view_layer.update()
    if key:
        pb.keyframe_insert("location", frame=frame)
        pb.keyframe_insert("rotation_quaternion" if pb.rotation_mode == "QUATERNION" else "rotation_euler", frame=frame)


def head_of(name):
    return rig.data.bones[name].head_local.copy()


SH = {s: head_of("IK-UpperArm." + s) for s in "LR"}
ARM = (head_of("IK-MSTR-Wrist.L") - SH["L"]).length
FOOT = {s: head_of("IK-MSTR-Foot." + s) for s in "LR"}


def arm_dir(side, elev_deg, fwd=0.0, reach=0.96):
    """Wrist target from the shoulder: elevation from horizontal (+up), forward swing (deg, toward -Y)."""
    sx = 1 if side == "L" else -1
    e, f = math.radians(elev_deg), math.radians(fwd)
    d = Vector((sx * math.cos(e) * math.cos(f), -math.cos(e) * math.sin(f), math.sin(e)))
    return SH[side] + d * ARM * reach, d


def wrist_to(side, elev, fwd=0.0, reach=0.96, offset=(0, 0, 0)):
    loc, d = arm_dir(side, elev, fwd, reach)
    sx = 1 if side == "L" else -1
    # rotate the hand so it continues the arm line (rest hand points along +-X)
    rot = Vector((sx, 0, 0)).rotation_difference(d).to_euler("XYZ")
    place("IK-MSTR-Wrist." + side, loc + Vector(offset), [math.degrees(a) for a in rot])


POSES = {}


def pose_apose():
    wrist_to("L", -58); wrist_to("R", -58)


def pose_arms_up():
    place("MSTR-Spine_Chest", rot=(-6, 0, 0))
    wrist_to("L", 72, fwd=8); wrist_to("R", 72, fwd=8)


def pose_crouch():
    place("MSTR-Spine_Torso", loc=head_of("MSTR-Spine_Torso") + Vector((0, 0.07, -0.20)), rot=(28, 0, 0))
    place("MSTR-Spine_Chest", rot=(12, 0, 0))
    for s, sx in (("L", 1), ("R", -1)):
        place("IK-MSTR-Foot." + s, FOOT[s] + Vector((sx * 0.035, 0.0, 0.0)), (0, 0, -sx * 12))
        place("IK-POLE-Leg." + s, head_of("IK-POLE-Leg." + s) + Vector((sx * 0.12, 0, 0.05)))
    bpy.context.view_layer.update()
    for s, sx in (("L", 1), ("R", -1)):
        place("IK-MSTR-Wrist." + s, Vector((sx * 0.11, -0.20, 0.30)), (70, 0, -sx * 70))


def pose_twist():
    place("MSTR-Spine_Hips", rot=(0, 0, -15))
    place("MSTR-Spine_Chest", rot=(0, 0, 40))
    place("FK-Neck", rot=(0, 0, 15))
    bpy.context.view_layer.update()
    place("IK-MSTR-Wrist.L", Vector((0.06, -0.24, 0.52)), (0, 0, -100))
    place("IK-MSTR-Wrist.R", Vector((-0.20, 0.17, 0.46)), (0, 40, 50))
    for s, sx in (("L", 1), ("R", -1)):
        place("IK-MSTR-Foot." + s, FOOT[s] + Vector((sx * 0.03, -sx * 0.02, 0)))


def pose_reach():
    place("MSTR-Spine_Torso", loc=head_of("MSTR-Spine_Torso") + Vector((0, 0.03, -0.02)), rot=(24, 0, 0))
    place("MSTR-Spine_Chest", rot=(10, 0, 0))
    bpy.context.view_layer.update()
    for s, sx in (("L", 1), ("R", -1)):
        place("IK-MSTR-Wrist." + s, Vector((sx * 0.075, -0.33, 0.60)), (0, 0, -sx * 90))
    place("IK-MSTR-Foot.R", FOOT["R"] + Vector((0, 0.09, 0)))


# ------------------------------------------------------------------------------------------------- staging
def setup_stage():
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = args.samples
    sc.cycles.use_denoising = True
    sc.render.threads_mode = "FIXED"; sc.render.threads = 2
    sc.render.resolution_x = 360; sc.render.resolution_y = 540; sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "AgX"; sc.view_settings.look = "AgX - Medium High Contrast"
    w = sc.world or D.worlds.new("QC"); sc.world = w; w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.42, 0.45, 0.50, 1); bg.inputs[1].default_value = 0.35
    floor = D.objects.get("QC_floor")
    if not floor:
        bpy.ops.mesh.primitive_plane_add(size=8, location=(0, 0, 0))
        floor = bpy.context.active_object; floor.name = "QC_floor"
        m = D.materials.new("QC_floor"); m.use_nodes = True
        m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.22, 0.23, 0.25, 1)
        m.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
        floor.data.materials.append(m)

    def light(name, kind, loc, energy, size, color=(1, 1, 1)):
        o = D.objects.get(name)
        if not o:
            o = D.objects.new(name, D.lights.new(name, kind)); sc.collection.objects.link(o)
        o.data.energy = energy; o.data.color = color
        if kind == "AREA":
            o.data.size = size
        o.location = loc
        d = Vector((0, 0, 0.7)) - Vector(loc)
        o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        return o
    light("QC_key", "AREA", (-1.6, -2.0, 2.2), 150, 1.6, (1.0, 0.95, 0.88))
    light("QC_fill", "AREA", (2.0, -1.6, 1.2), 40, 2.0, (0.85, 0.9, 1.0))
    light("QC_rim", "AREA", (0.6, 2.2, 1.9), 260, 1.2, (0.9, 0.95, 1.0))
    light("QC_rim2", "AREA", (-1.8, 1.6, 1.4), 140, 1.0, (1.0, 0.95, 0.9))
    cam = D.objects.get("QC_cam")
    if not cam:
        cam = D.objects.new("QC_cam", D.cameras.new("QC_cam")); sc.collection.objects.link(cam)
    cam.data.lens = 50
    sc.camera = cam
    return cam


def aim(cam, yaw_deg, target=(0, 0, 0.64), dist=2.05, height=0.80, lens=50):
    a = math.radians(yaw_deg)
    cam.data.lens = lens
    cam.location = Vector((dist * math.sin(a), -dist * math.cos(a), height))
    cam.rotation_euler = (Vector(target) - cam.location).to_track_quat("-Z", "Y").to_euler()


def render(path):
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    log("rendered", path)
    return path


def sheet(paths, out, cols):
    imgs = []
    for p in paths:
        im = D.images.load(p, check_existing=False)
        w, h = im.size
        a = np.array(im.pixels[:], dtype=np.float32).reshape(h, w, 4)
        imgs.append(a); D.images.remove(im)
    h, w = imgs[0].shape[:2]
    rows = (len(imgs) + cols - 1) // cols
    gap = 6
    canvas = np.ones(((h + gap) * rows - gap, (w + gap) * cols - gap, 4), dtype=np.float32) * 0.08
    canvas[..., 3] = 1
    for i, a in enumerate(imgs):
        r, c = divmod(i, cols)
        # image rows are bottom-up in Blender: put row 0 at the top of the sheet
        y0 = (rows - 1 - r) * (h + gap)
        canvas[y0:y0 + h, c * (w + gap):c * (w + gap) + w] = a
    H, W = canvas.shape[:2]
    out_img = D.images.new("sheet", W, H, alpha=True)
    out_img.pixels.foreach_set(canvas.ravel())
    out_img.filepath_raw = out; out_img.file_format = "PNG"; out_img.save()
    D.images.remove(out_img)
    log("sheet", out)
    return out


# ------------------------------------------------------------------------------------------------- numeric
def eval_verts(name):
    dg = bpy.context.evaluated_depsgraph_get()
    o = D.objects[name].evaluated_get(dg)
    m = o.to_mesh()
    vs = np.array([tuple(o.matrix_world @ v.co) for v in m.vertices])
    o.to_mesh_clear()
    return vs


def numeric():
    out = {}
    out["removed_objects_absent"] = {n: n not in D.objects for n in ("GEO-jay_shades", "GEO-jay_chain", "GEO-jay_hat")}
    out["props"] = {k: P["Properties_Character_Jay"][k] for k in ("Glasses", "Chain")}
    bad = 0
    for idb in list(D.objects) + list(D.shape_keys) + list(D.materials) + list(D.armatures):
        ad = getattr(idb, "animation_data", None)
        if ad:
            for d in ad.drivers:
                if not d.is_valid:
                    bad += 1
    out["invalid_drivers_after_eval"] = bad
    # cap follows the head rigidly
    reset_pose()
    cap0 = eval_verts("GEO-hero_cap"); h0 = eval_verts("GEO-jay_head")
    place("FK-Head", rot=(18, 0, 35), key=False); place("FK-Neck", rot=(0, 10, 0), key=False)
    cap1 = eval_verts("GEO-hero_cap"); h1 = eval_verts("GEO-jay_head")
    # rigid fit (Kabsch) of the skull top (head verts above the brows), then predict the cap with it
    top = h0[:, 2] > 1.06
    A, B = h0[top], h1[top]
    ca, cb = A.mean(0), B.mean(0)
    U, _S, Vt = np.linalg.svd((A - ca).T @ (B - cb))
    R = Vt.T @ np.diag([1, 1, np.sign(np.linalg.det(Vt.T @ U.T))]) @ U.T
    pred = (R @ (cap0 - ca).T).T + cb
    out["cap_follow_head_max_err_mm"] = float(np.abs(pred - cap1).max() * 1000)
    out["cap_moved_mm"] = float(np.abs(cap1 - cap0).max() * 1000)
    # face rig still drives the head (eyelid + jaw controls)
    reset_pose()
    h0 = eval_verts("GEO-jay_head")
    for n, d in (("MSTR-EyeRing_Upper.L", (0, 0, -0.008)), ("MSTR-Mouth_Lower", (0, 0, -0.01))):
        if n in P:
            place(n, head_of(n) + Vector(d), key=False)
    h1 = eval_verts("GEO-jay_head")
    out["face_rig_head_max_disp_mm"] = float(np.linalg.norm(h1 - h0, axis=1).max() * 1000)
    reset_pose()
    return out


# ------------------------------------------------------------------------------------------------- main
cam = setup_stage()
renders = {}
if args.only in ("all", "numeric"):
    RESULT["numeric"] = numeric()
    log("NUMERIC", json.dumps(RESULT["numeric"]))
if args.only in ("all", "turn"):
    reset_pose(); pose_apose()
    paths = []
    for name, yaw in (("front", 0), ("three_quarter", 35), ("side", 90), ("back", 180)):
        aim(cam, yaw)
        paths.append(render(os.path.join(args.tmp, "turn_%s.png" % name)))
    RESULT["turnaround"] = sheet(paths, os.path.join(args.out, "turnaround.png"), 4)
if args.only in ("all", "poses"):
    paths = []
    for name, fn, yaw in (("arms_raised", pose_arms_up, 25), ("crouch", pose_crouch, 55), ("twist", pose_twist, 15),
                          ("reach_forward", pose_reach, 65)):
        reset_pose(); fn()
        aim(cam, yaw)
        paths.append(render(os.path.join(args.tmp, "pose_%s.png" % name)))
    RESULT["poses"] = sheet(paths, os.path.join(args.out, "pose_checks.png"), 4)
if args.only in ("all", "face"):
    reset_pose(); pose_apose()
    paths = []
    for yaw in (0, 40, 120, 180):
        aim(cam, yaw, target=(0, -0.01, 1.0), dist=1.0, height=1.05, lens=60)
        paths.append(render(os.path.join(args.tmp, "head_%d.png" % yaw)))
    RESULT["head"] = sheet(paths, os.path.join(args.out, "head_closeups.png"), 4)
log("RESULT", json.dumps(RESULT))
with open(os.path.join(args.tmp, "qc_result.json"), "w") as f:
    json.dump(RESULT, f, indent=1)
