"""Verification sheets for cloud/blender/cloudrig_adapter.py on the Blender Studio Jay rig.

  blender -b --factory-startup -P cloud/blender/test/cloudrig_sheets.py -- --mode body|face|channels \
      --out /tmp/<you>/sheets [--samples 16] [--blend library_store/characters/jay.blend]

body     : the 12 acting poses (stand, helm, brace, radio_shout, shush, phone_up, wave, hands_face, look_back,
           sit_deck, down, point_ahead) baked through CloudRigPuppet.bake(), full body 360x540, 3/4 front view.
face     : 16 emotions + blink + 4 gaze directions + 3 visemes as head close-ups (FACE_POSES / VISEME_POSES).
channels : every face channel at +1 / -1 (calibration of signs and ranges).
Each frame is written as <out>/<mode>_<nn>_<label>.png and a contact sheet <out>/<mode>_sheet.png (ImageMagick).
"""
import argparse
import json
import math
import os
import subprocess
import sys

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import acting  # noqa: E402
import cloudrig_adapter as cra  # noqa: E402
import face  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--mode", default="body")
ap.add_argument("--out", default="/tmp/rigadapter/sheets")
ap.add_argument("--samples", type=int, default=16)
ap.add_argument("--blend", default=os.path.join("/home/user/story-animator", "library_store", "characters", "jay.blend"))
ap.add_argument("--only", default=None, help="comma list of indices to render")
ap.add_argument("--focus", default="face", help="face | mouth | eyes (close-up framing for face/channels)")
ap.add_argument("--res", default=None, help="WxH override for body / hands frames (e.g. 540x960)")
ap.add_argument("--lens", type=float, default=42.0, help="body mode lens (mm)")
ap.add_argument("--closeup", action="store_true", help="body mode: hands-only close-up per pose")
ap.add_argument("--legacy", action="store_true", help="body mode: the pre-polish 12 poses (sit_deck, no props)")
args = ap.parse_args(argv)
os.makedirs(args.out, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
coll, arm, objs = cra.append_character(args.blend, "CH-jay", "RIG-jay")
holder = bpy.data.objects.new("holder", None)
sc.collection.objects.link(holder)
arm.parent = holder
print("MESH HAIR", cra.prefer_mesh_hair(coll))
print("OPTIONS", cra.set_character_options(arm, {"Glasses": 0}))
pup = cra.CloudRigPuppet(arm, holder)
print("MEASURE", json.dumps(pup.describe()))

# ---------------- stage
bpy.ops.mesh.primitive_plane_add(size=20)
fl = bpy.context.object
m = bpy.data.materials.new("floor")
m.use_nodes = True
m.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (0.22, 0.2, 0.18, 1)
fl.data.materials.append(m)
w = bpy.data.worlds.new("w")
sc.world = w
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.06, 0.07, 0.09, 1)
w.node_tree.nodes["Background"].inputs[1].default_value = 1.0
aim = bpy.data.objects.new("aim", None)
sc.collection.objects.link(aim)


def light(n, loc, e, size=1.0, col=(1, 1, 1)):
    d = bpy.data.lights.new(n, "AREA")
    d.energy, d.size, d.color = e, size, col
    o = bpy.data.objects.new(n, d)
    sc.collection.objects.link(o)
    o.location = loc
    c = o.constraints.new("TRACK_TO")
    c.target, c.track_axis, c.up_axis = aim, "TRACK_NEGATIVE_Z", "UP_Y"
    return o


cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
c = cam.constraints.new("TRACK_TO")
c.target, c.track_axis, c.up_axis = aim, "TRACK_NEGATIVE_Z", "UP_Y"
sc.render.engine = "CYCLES"
sc.cycles.samples = args.samples
sc.cycles.device = "CPU"
sc.cycles.use_denoising = True
sc.render.threads_mode = "FIXED"
sc.render.threads = 2
sc.render.film_transparent = False
sc.view_settings.view_transform = "AgX" if "AgX" in [i.identifier for i in sc.view_settings.bl_rna.properties["view_transform"].enum_items] else "Filmic"

stand = acting.pose_at(0, {"stance": [[-100, "stand"]], "breath": 0})


def _res(default):
    if args.res:
        w_, h_ = (int(x) for x in args.res.lower().split("x"))
        return w_, h_
    return default


def _show_only(objs, frames_on, f_all):
    """keyframe hide_render so these objects only appear on frames_on."""
    for o in objs:
        for f in f_all:
            o.hide_render = f not in frames_on
            o.keyframe_insert("hide_render", frame=f)


def body_props(tests):
    """helm (for 'helm'), radio / phone in the right hand, the cockpit bench (for the sit test) - at episode scale
    relative to Jay (episodes scale him to 1.8 m; here the holder is unscaled, so props shrink by 1/k)."""
    import contact
    import hand_poses
    import props as propkit
    sys.path.insert(0, os.path.join(REPO, "episodes", "sentinel", "plan"))
    import marks as MK
    k = 1.8 / cra.natural_height(arm)
    f_all = list(range(-1, len(tests) * 10 + 2))
    anchors = {}
    for i, (st, ps) in enumerate(tests):
        on = set(range(i * 10, i * 10 + 10))
        if st == "helm":
            r = propkit.helm_console("helm")
            r.scale = (1 / k,) * 3
            r.rotation_euler = (0, 0, math.pi)
            r.location = (0, -0.58 / k, 0)
            bpy.context.view_layer.update()
            anchors.update(contact.helm_anchors(r.matrix_world, (1, 0, 0)))
            _show_only([r, *r.children_recursive], on, f_all)
        if st.startswith("sit_bench"):
            bpy.ops.mesh.primitive_cube_add(size=1)
            b = bpy.context.object
            b.name = "bench"
            # yacht_v2 aft bench (marks.py BENCH): the actor mark (feet) is `fe` in front of the seat front
            fe = MK.SITMARK["local"][2] - MK.BENCH["front_z"]
            sh_ = MK.BENCH["seat_y"] - MK.SITMARK["local"][1]
            dp = MK.BENCH["depth"]
            b.scale = (2.4 / k, dp / k, sh_ / k)
            b.location = (0, (fe + dp / 2) / k, sh_ / 2 / k)
            mb = bpy.data.materials.new("bench")
            mb.use_nodes = True
            mb.node_tree.nodes["Principled BSDF"].inputs[0].default_value = (0.05, 0.07, 0.1, 1)
            b.data.materials.append(mb)
            anchors["bench_seat"] = {"p": Vector((0, (fe + MK.SEAT_SETBACK) / k, sh_ / k))}
            _show_only([b], on, f_all)
        for prop, pose in (("radio", "radio_shout"), ("phone", "phone_up")):
            if ps == pose:
                r = getattr(propkit, {"radio": "vhf_handset", "phone": "phone"}[prop])(prop)
                bone = arm.data.bones["ORG-Wrist.R"]
                loc, axes = hand_poses.prop_grip(prop, "R", bone.length)
                r.parent, r.parent_type, r.parent_bone = arm, "BONE", "ORG-Wrist.R"
                r.matrix_parent_inverse = Matrix.Identity(4)
                M = Matrix((axes[0], axes[1], axes[2])).transposed().to_4x4()
                M.translation = Vector(loc)
                r.matrix_basis = M @ Matrix.Scale(1 / k, 4)
                _show_only([r, *r.children_recursive], on, f_all)
    pup.set_anchors(anchors)
    return k


def body_mode():
    tests = [("stand", None), ("helm", None), ("brace", None), ("stand", "radio_shout"), ("stand", "shush"), ("stand", "phone_up"),
             ("stand", "wave"), ("stand", "hands_face"), ("stand", "look_back"), ("sit_bench", None), ("down", None), ("stand", "point_ahead")]
    if args.legacy:
        tests[9] = ("sit_deck", None)
    else:
        body_props(tests)
    perf = {"stance": [], "poses": [], "blend": 1, "seed": 2}
    for i, (st, ps) in enumerate(tests):
        perf["stance"].append([i * 10, st])
        if ps:
            perf["poses"].append({"pose": ps, "from": i * 10, "to": i * 10 + 9, "in": 1, "out": 1})
    perf["stance"][0][0] = -100
    fs = {"emotion": [[0, "calm"], [30, "shout"], [40, "secret"], [50, "neutral"], [70, "hopeful"], [80, "worried"], [90, "calm"], [100, "pain"], [110, "determined"]],
          "blend": 2, "noBlink": True}
    keyed = pup.bake(perf, fs, 0, len(tests) * 10)
    print("KEYED", len(keyed), sorted(keyed)[:8])
    cam.location = (-1.25, -2.7, 0.95)
    cam.data.lens = args.lens
    aim.location = (0, 0, 0.58)
    light("key", (-1.8, -2.4, 2.4), 260, 1.5, (1, 0.96, 0.9))
    light("rim", (1.6, 1.8, 1.9), 220, 1.0, (0.8, 0.88, 1))
    light("fill", (2.0, -1.8, 0.9), 60, 2.5)
    sc.render.resolution_x, sc.render.resolution_y = _res((360, 540))
    frames = [(i * 10 + 8, f"{st}{'+' + ps if ps else ''}") for i, (st, ps) in enumerate(tests)]
    if args.closeup:
        # hands-only close-ups: camera on the two wrists of each pose (front-left 3/4, a little above)
        out = []
        for f, label in frames:
            sc.frame_set(f)
            bpy.context.view_layer.update()
            wl = arm.matrix_world @ arm.pose.bones["DEF-Wrist.L"].tail
            wr = arm.matrix_world @ arm.pose.bones["DEF-Wrist.R"].tail
            r_only = any(k in label for k in ("radio", "shush", "phone", "wave", "point"))
            mid = wr if r_only else (wl + wr) * 0.5
            dist = 0.34 if r_only else (wl - wr).length * 0.9 + 0.22
            dv = Vector((-0.45, -1.0, 0.25)).normalized()
            out.append((f, label, tuple(mid + dv * dist), tuple(mid)))
        cam.data.lens = 50
        return out
    return frames


def hands_mode():
    """every hand_poses shape on both hands, raised in front of the chest: palm view + back view per shape."""
    import hand_poses
    shapes = list(hand_poses.SHAPES)
    perf = {"stance": [[-100, "stand"]], "poses": [], "blend": 1, "seed": 2, "breath": 0}
    for i, s in enumerate(shapes):
        perf["poses"].append({"pose": {"handR": [-0.20, -0.34, 1.22], "handL": [0.20, -0.34, 1.22],
                                       "poleR": [-0.6, 0.2, 0.9], "poleL": [0.6, 0.2, 0.9],
                                       "handShapeR": s, "handShapeL": s,
                                       "palmR": [0.35, -1, 0], "fingR": [0, 0, 1], "palmL": [0, 0.2, -1], "fingL": [-0.2, -1, 0]},
                              "from": i * 10, "to": i * 10 + 9, "in": 1, "out": 1})
    pup.bake(perf, {"emotion": [[0, "calm"]], "noBlink": True}, 0, len(shapes) * 10)
    bpy.context.view_layer.update()
    c = (pup.upper["L"].head + pup.upper["R"].head) * 0.5
    aim.location = (0, c.y - 0.20, c.z + 0.0)
    cam.data.lens = 60
    light("key", (-1.2, -1.8, 1.8), 120, 1.0, (1, 0.96, 0.9))
    light("rim", (1.0, 1.2, 1.4), 80, 0.8, (0.8, 0.88, 1))
    light("fill", (1.2, -1.4, 0.6), 40, 1.5)
    sc.render.resolution_x, sc.render.resolution_y = _res((360, 360))
    frames = []
    for i, s in enumerate(shapes):
        frames.append((i * 10 + 8, s, (-0.10, c.y - 0.95, c.z + 0.05)))
    return frames


def face_mode(items):
    cam.data.lens = 85
    sc.render.resolution_x, sc.render.resolution_y = 300, 300
    frames = []
    pup._prev_eul = {}
    for i, (label, ch, gaze) in enumerate(items):
        f = i * 2 + 1
        pup.apply(stand, ch, gaze)
        for pb in pup._controls():
            pb.keyframe_insert("location", frame=f)
            pb.keyframe_insert("rotation_euler", frame=f)
        frames.append((f, label))
    bpy.context.view_layer.update()
    eyes = pup.eyecen.head if pup.eyecen else Vector((0, 0, 1.0))
    z = {"face": (eyes.z + pup.LM["mouth"]) * 0.5, "mouth": pup.LM["mouth"], "eyes": eyes.z}[args.focus]
    dist = {"face": 0.8, "mouth": 0.45, "eyes": 0.45}[args.focus]
    aim.location = (0, -0.04, z)
    cam.location = (-0.12 * dist, -dist, z + 0.06 * dist)
    light("key", (-0.9, -1.4, 1.6), 110, 0.8, (1, 0.96, 0.9))
    light("rim", (0.9, 1.0, 1.4), 90, 0.6, (0.8, 0.88, 1))
    light("fill", (1.0, -1.2, 0.8), 30, 1.5)
    light("front", (0.0, -1.0, eyes.z - 0.25), 18, 0.6)   # under the hat brim
    return frames


def face_items():
    items = []
    for emo in ("neutral", "calm", "concern", "worried", "fear", "shock", "panic", "pain", "determined", "shout",
                "hopeful", "relief", "sneeze_build", "sneeze", "secret", "wince"):
        ch = dict(cra.FACE_POSES[emo])
        for s in "LR":
            ch[f"lidUp.{s}"] = ch.get(f"lidUp.{s}", 0) + 0.12
        items.append((emo, ch, (0, 0)))
    items.append(("blink", {"lidUp.L": 1.0, "lidUp.R": 1.0, "lidLo.L": 0.22, "lidLo.R": 0.22}, (0, 0)))
    for lab, g in (("gaze_left", (25, 0)), ("gaze_right", (-25, 0)), ("gaze_up", (0, 18)), ("gaze_down", (0, -20))):
        ch = cra.lid_follow({"lidUp.L": 0.12, "lidUp.R": 0.12}, g[1])   # same rule as CloudRigPuppet.face_at
        items.append((lab, ch, g))
    for v in ("aa_02", "w_uw_07", "p_b_m_21"):
        ch = dict(cra.VISEME_POSES[v])
        for s in "LR":
            ch[f"lidUp.{s}"] = ch.get(f"lidUp.{s}", 0) + 0.12
        items.append(("vis_" + v, ch, (0, 0)))
    return items


def channel_items():
    items = [("rest", {}, (0, 0))]
    for chn in cra.FACE_CTRL:
        side = chn + ".L" if (chn + ".L") in cra.CHANNELS else chn
        both = [chn + ".L", chn + ".R"] if (chn + ".L") in cra.CHANNELS else [chn]
        for v in (1.0, -1.0):
            items.append((f"{chn}{'+' if v > 0 else '-'}", {c: v for c in both}, (0, 0)))
    return items


if args.mode == "body":
    frames = body_mode()
elif args.mode == "hands":
    frames = hands_mode()
elif args.mode == "face":
    frames = face_mode(face_items())
else:
    frames = face_mode(channel_items())
only = set(int(x) for x in args.only.split(",")) if args.only else None
paths = []
for n, fr in enumerate(frames):
    f, label = fr[0], fr[1]
    if only is not None and n not in only:
        continue
    if len(fr) > 2:
        cam.location = fr[2]
    if len(fr) > 3:
        aim.location = fr[3]
    sc.frame_set(f)
    p = os.path.join(args.out, f"{args.mode}_{n:02d}_{label}.png")
    sc.render.filepath = p
    bpy.ops.render.render(write_still=True)
    paths.append((p, label))
    print("WROTE", p)
if paths and only is None:
    sheet = os.path.join(args.out, f"{args.mode}_sheet.png")
    cmd = ["montage"]
    for p, lab in paths:
        cmd += ["-label", lab, p]
    cmd += ["-tile", "6x" if args.mode in ("body", "hands") else "8x", "-geometry", "+2+2", "-pointsize", "12", "-background", "#222", "-fill", "#ddd", sheet]
    subprocess.run(cmd, check=False)
    print("SHEET", sheet)
