"""Golden-frame renders of the hero rig (factory/goldens): turnaround, pose sheet, face sheet on a neutral stage.

  blender -b --factory-startup -P cloud/blender/test/golden_hero.py -- --mode turnaround|pose|face --out <dir> \
      [--blend library_store/characters/hero_v4/hero_v4.blend] [--res 360x640] [--samples 8] [--threads 2]

Deterministic: Cycles CPU, fixed seed, fixed sample count, no adaptive sampling, OIDN denoise, fixed lights/cameras.
Writes <out>/<mode>_<nn>_<label>.png (one per view) and prints WROTE lines; factory/goldens tiles them into a strip.
Driven through the production adapter (cloudrig_adapter.CloudRigPuppet), so rig/acting/face changes show up here.
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import cloudrig_adapter as cra  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--mode", required=True, choices=["turnaround", "pose", "face"])
ap.add_argument("--out", required=True)
ap.add_argument("--blend", default=os.path.join(os.environ.get("LIBRARY_STORE") or os.path.join(REPO, "library_store"),
                                                "characters", "hero_v4", "hero_v4.blend"))
ap.add_argument("--collection", default="CH-jay")
ap.add_argument("--rig", default="RIG-jay")
ap.add_argument("--res", default="360x640")
ap.add_argument("--samples", type=int, default=8)
ap.add_argument("--threads", type=int, default=2)
args = ap.parse_args(argv)
os.makedirs(args.out, exist_ok=True)

POSES = [("stand", None), ("helm", None), ("brace", None), ("sit_deck", None), ("stand", "radio_shout"), ("stand", "point_ahead")]
EMOTIONS = ["neutral", "calm", "worried", "fear", "determined", "shout"]
TURN = [0, 90, 180, 270]

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
coll, arm, objs = cra.append_character(args.blend, args.collection, args.rig)
holder = bpy.data.objects.new("holder", None)
sc.collection.objects.link(holder)
arm.parent = holder
cra.prefer_mesh_hair(coll)
cra.set_character_options(arm, {"Glasses": 0})
pup = cra.CloudRigPuppet(arm, holder)

# stage: floor, dim world, 3 area lights aimed at an empty
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
W, H = (int(v) for v in args.res.lower().split("x"))
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = args.samples
sc.cycles.use_adaptive_sampling = False
sc.cycles.seed = 0
sc.cycles.use_animated_seed = False
sc.cycles.use_denoising = True
try:
    sc.cycles.denoiser = "OPENIMAGEDENOISE"
except TypeError:
    pass
sc.render.threads_mode = "FIXED"
sc.render.threads = args.threads
sc.render.use_motion_blur = False
sc.render.image_settings.file_format = "PNG"
sc.view_settings.view_transform = "AgX" if "AgX" in [i.identifier for i in sc.view_settings.bl_rna.properties["view_transform"].enum_items] else "Filmic"


def body_lights():
    light("key", (-1.8, -2.4, 2.4), 260, 1.5, (1, 0.96, 0.9))
    light("rim", (1.6, 1.8, 1.9), 220, 1.0, (0.8, 0.88, 1))
    light("fill", (2.0, -1.8, 0.9), 60, 2.5)


frames = []
if args.mode == "turnaround":
    pup.bake({"stance": [[-100, "stand"]], "poses": [], "blend": 1, "seed": 2, "breath": 0},
             {"emotion": [[0, "neutral"]], "noBlink": True}, 0, 4)
    body_lights()
    aim.location = (0, 0, 0.62)
    cam.data.lens = 50
    for i, az in enumerate(TURN):
        a = math.radians(az)
        frames.append((2, f"az{az:03d}", Vector((3.2 * math.sin(a), -3.2 * math.cos(a), 0.85))))
elif args.mode == "pose":
    perf = {"stance": [], "poses": [], "blend": 1, "seed": 2, "breath": 0}
    for i, (st, ps) in enumerate(POSES):
        perf["stance"].append([i * 10, st])
        if ps:
            perf["poses"].append({"pose": ps, "from": i * 10, "to": i * 10 + 9, "in": 1, "out": 1})
    perf["stance"][0][0] = -100
    pup.bake(perf, {"emotion": [[0, "calm"]], "noBlink": True}, 0, len(POSES) * 10)
    body_lights()
    aim.location = (0, 0, 0.58)
    cam.data.lens = 42
    for i, (st, ps) in enumerate(POSES):
        frames.append((i * 10 + 8, f"{st}{'+' + ps if ps else ''}", Vector((-1.25, -2.7, 0.95))))
else:
    stand = cra.acting.pose_at(0, {"stance": [[-100, "stand"]], "breath": 0}) if hasattr(cra, "acting") else None
    if stand is None:
        import acting
        stand = acting.pose_at(0, {"stance": [[-100, "stand"]], "breath": 0})
    pup._prev_eul = {}
    for i, emo in enumerate(EMOTIONS):
        f = i * 2 + 1
        pup.apply(stand, dict(cra.FACE_POSES[emo]), (0, 0))
        for pb in pup._controls():
            pb.keyframe_insert("location", frame=f)
            pb.keyframe_insert("rotation_euler", frame=f)
        frames.append((f, emo, None))
    bpy.context.view_layer.update()
    eyes = pup.eyecen.head if pup.eyecen else Vector((0, 0, 1.0))
    z = (eyes.z + pup.LM["mouth"]) * 0.5
    aim.location = (0, -0.04, z)
    cam.data.lens = 85
    light("key", (-0.9, -1.4, 1.6), 110, 0.8, (1, 0.96, 0.9))
    light("rim", (0.9, 1.0, 1.4), 90, 0.6, (0.8, 0.88, 1))
    light("fill", (1.0, -1.2, 0.8), 30, 1.5)
    light("front", (0.0, -1.0, eyes.z - 0.25), 18, 0.6)
    frames = [(f, lab, Vector((-0.1, -1.0, z + 0.05))) for f, lab, _ in frames]

for n, (f, label, cpos) in enumerate(frames):
    sc.frame_set(f)
    cam.location = cpos
    bpy.context.view_layer.update()
    p = os.path.join(args.out, f"{args.mode}_{n:02d}_{label}.png")
    sc.render.filepath = p
    bpy.ops.render.render(write_still=True)
    print("WROTE", p)
