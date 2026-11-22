"""Face sheet for the series hero (hero_v4 = Blender Studio Jay re-dressed) through cloudrig_adapter.

  blender -b --factory-startup -P cloud/blender/test/face_sheet_hero.py -- --out DIR [--mode sheet|channels|shots]
      [--res 540x960] [--samples 32] [--only 0,3,5] [--channels "lidUp=0.3,pupil=-1;browIn=1"] [--threads 2]

sheet    : every face.EMOTIONS pose (FACE_POSES, as CloudRigPuppet.face_at layers them: resting lids, lid follow)
           + blink + 4 gaze directions, 3/4 close-up, eyes converged on the camera (look = 'camera').
channels : ad-hoc channel dicts (';' separated items, ',' separated ch=value) for calibration.
shots    : the real face_spec + perf of episode shots (--shots A03:140,B12:800 ...) baked through
           CloudRigPuppet.bake() and rendered from the sheet camera (a face-only view of the performance).
Writes <out>/<mode>_<nn>_<label>.png and <out>/<mode>_sheet.png (ImageMagick montage).
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
ap.add_argument("--mode", default="sheet")
ap.add_argument("--out", required=True)
ap.add_argument("--res", default="540x960")
ap.add_argument("--samples", type=int, default=32)
ap.add_argument("--threads", type=int, default=2)
ap.add_argument("--blend", default="/home/user/story-animator/library_store/characters/hero_v4/hero_v4.blend")
ap.add_argument("--only", default=None)
ap.add_argument("--channels", default="")
ap.add_argument("--shots", default="A03:131,A03:145,B12:795,B12:825,C20:1340,C20:1352,C28:2015")
ap.add_argument("--spec", default=os.path.join(REPO, "episodes", "sentinel", "episode_v5.json"))
ap.add_argument("--angle", type=float, default=18.0, help="camera azimuth off his nose, degrees (+ = his left)")
ap.add_argument("--tile", default="6x")
ap.add_argument("--view", default="episode", help="shots mode: episode (along the shot camera) | face (in front of his face)")
ap.add_argument("--follow", action="store_true", help="shots mode: re-aim the camera at the eyes every frame")
ap.add_argument("--extend", type=int, default=0, help="shots mode: keep baking N frames past the shot end (holds)")
ap.add_argument("--fps", type=float, default=0, help="shots mode: also write <out>/clip.mp4 at this frame rate")
ap.add_argument("--look", default="", help="shots mode: face look target when the shot has none (e.g. camera)")
args = ap.parse_args(argv)
os.makedirs(args.out, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
coll, arm, objs = cra.append_character(args.blend, "CH-jay", "RIG-jay")
holder = bpy.data.objects.new("holder", None)
sc.collection.objects.link(holder)
arm.parent = holder
cra.prefer_mesh_hair(coll)
cra.set_character_options(arm, {"Glasses": 0})
pup = cra.CloudRigPuppet(arm, holder)
pup.debug_eyes = bool(os.environ.get("FACE_DEBUG"))

# ---------------- stage: soft portrait light, dark blue backdrop
w = bpy.data.worlds.new("w")
sc.world = w
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.035, 0.045, 0.07, 1)
aim = bpy.data.objects.new("aim", None)
sc.collection.objects.link(aim)
eyes = pup.eyecen.bone.head_local.copy() if pup.eyecen else Vector((0, -0.05, pup.LM["eyes"]))
fz = eyes.z - 0.03
aim.location = (0, eyes.y + 0.02, fz)


def light(n, loc, e, size=1.0, col=(1, 1, 1), shadow=True):
    d = bpy.data.lights.new(n, "AREA")
    d.energy, d.size, d.color = e, size, col
    d.use_shadow = shadow
    o = bpy.data.objects.new(n, d)
    sc.collection.objects.link(o)
    o.location = loc
    c = o.constraints.new("TRACK_TO")
    c.target, c.track_axis, c.up_axis = aim, "TRACK_NEGATIVE_Z", "UP_Y"
    return o


cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.lens = 65
cam.data.sensor_fit = "VERTICAL"
cam.data.sensor_height = 24.0
cam.data.dof.use_dof = True
cam.data.dof.aperture_fstop = 4.0
a = math.radians(args.angle)
dist = 1.2
cam.location = (aim.location.x + math.sin(a) * dist, aim.location.y - math.cos(a) * dist, fz - 0.02)
c = cam.constraints.new("TRACK_TO")
c.target, c.track_axis, c.up_axis = aim, "TRACK_NEGATIVE_Z", "UP_Y"
cam.data.dof.focus_distance = dist - 0.05
light("key", (0.75, -1.0, fz + 0.75), 55, 0.9, (1.0, 0.93, 0.85))
light("fill", (-1.0, -0.9, fz + 0.1), 16, 1.6, (0.75, 0.85, 1.0))
light("rim", (-0.6, 0.9, fz + 0.6), 55, 0.5, (0.7, 0.8, 1.0))
light("under", (0.1, -0.9, fz - 0.45), 6, 0.8, (1.0, 0.85, 0.75))     # bounce under the cap brim
light("catch", (cam.location.x + 0.05, cam.location.y + 0.1, fz + 0.12), 4, 0.15, (1, 1, 1), shadow=False)

rx, ry = (int(v) for v in args.res.split("x"))
sc.render.resolution_x, sc.render.resolution_y = rx, ry
sc.render.engine = "CYCLES"
sc.cycles.samples = args.samples
sc.cycles.device = "CPU"
sc.cycles.use_denoising = True
sc.render.threads_mode = "FIXED"
sc.render.threads = args.threads
sc.view_settings.view_transform = "AgX"
sc.view_settings.look = "AgX - Medium High Contrast"
bpy.context.view_layer.update()
pup.camera_fn = lambda f: cam.matrix_world.translation.copy()

stand = acting.pose_at(0, {"stance": [[-100, "stand"]], "breath": 0})


def static_items():
    items = []
    for emo in face.EMOTIONS:
        items.append((emo, {"emotion": [[-100, emo, 1.0]]}))
    items.append(("blink", {"emotion": [[-100, "neutral"]], "blinkNow": 1.0}))
    for lab, g in (("gaze_left", (22, 0)), ("gaze_right", (-22, 0)), ("gaze_up", (0, 15)), ("gaze_down", (0, -16))):
        items.append((lab, {"emotion": [[-100, "neutral"]], "gazeOffset": g}))
    return items


def channel_items():
    out = []
    for i, it in enumerate(s for s in args.channels.split(";") if s.strip()):
        ch = {}
        for kv in it.split(","):
            k, v = kv.split("=")
            k = k.strip()
            names = [k] if (k in cra.CHANNELS) else [k + ".L", k + ".R"]
            for n in names:
                ch[n] = float(v)
        out.append((it.replace("=", "").replace(",", "_")[:40], ch))
    return out


def static_render(items, raw=False):
    frames = []
    pup._prev_eul = {}
    for i, (label, spec) in enumerate(items):
        f = i * 2 + 1
        if raw:
            ch, gaze = spec, {"point": pup.look_point(f, "camera")}
        else:
            ch, gaze = pup.static_face(spec, f)
        pup.apply(stand, ch, gaze)
        for pb in pup._controls():
            pb.keyframe_insert("location", frame=f)
            pb.keyframe_insert("rotation_euler", frame=f)
            pb.keyframe_insert("scale", frame=f)
        frames.append((f, label))
    return frames


def render(f, n, label, paths):
    sc.frame_set(f)
    p = os.path.join(args.out, f"{args.mode}_{n:02d}_{label}.png")
    sc.render.filepath = p
    bpy.ops.render.render(write_still=True)
    paths.append((p, label))
    print("WROTE", p, flush=True)


def shots_render(paths):
    """bake each shot's real perf + face (same frame numbers as the episode) and render the asked frames."""
    spec = json.load(open(args.spec))
    by_id = {s["id"]: s for s in spec["shots"]}
    order = []
    for it in args.shots.split(","):
        sid, fr = it.split(":")
        order.append((sid, int(fr)))
    n = 0
    T = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    hh = cra.natural_height(arm)
    for sid in dict.fromkeys(s for s, _ in order):
        sh = by_id[sid]
        a = next(x for x in sh["actors"] if x.get("asset") == "hero_v4")
        fs = a.get("face") or {}
        if args.look and "look" not in fs:
            fs = dict(fs, look=args.look)
        # the episode camera in this actor's armature space (yacht-space keys, linear between keys: a sheet approximation)
        M = (T @ Matrix.Translation(Vector(a["local"])) @ Matrix.Rotation(a.get("rotY", 0), 4, "Y") @ T.transposed()
             @ Matrix.Scale(float(a.get("height", 1.8)) / hh, 4))
        Mi = M.inverted()
        keys = sorted(sh["camera"]["keys"], key=lambda k: k["f"])

        def cam_arm(f, keys=keys, Mi=Mi):
            k0 = keys[0]
            k1 = keys[-1]
            for i in range(len(keys) - 1):
                if keys[i]["f"] <= f <= keys[i + 1]["f"]:
                    k0, k1 = keys[i], keys[i + 1]
                    break
            u = 0 if k1["f"] == k0["f"] else max(0, min(1, (f - k0["f"]) / (k1["f"] - k0["f"])))
            c = [k0["cam"][j] + (k1["cam"][j] - k0["cam"][j]) * u for j in range(3)]
            return Mi @ Vector((c[0], -c[2], c[1]))
        pup.camera_fn = cam_arm
        pup.bake(a.get("perf"), fs, sh["from"] - 1, sh["to"] + 1 + args.extend)
        cam.constraints.clear()
        placed = False
        for s2, fr in order:
            if s2 != sid:
                continue
            if only is None or n in only:
                sc.frame_set(fr)
                if not placed or args.follow:
                    # camera fixed for the shot (head motion stays visible), placed at the first rendered frame
                    E = pup.eyecen.head.copy() if pup.eyecen else Vector((0, 0, pup.LM["eyes"]))
                    if args.view == "face":
                        hd = pup.headdef
                        fwd = (hd.matrix.to_quaternion() @ hd.bone.matrix_local.to_quaternion().inverted()) @ Vector((0, -1, 0))
                        fwd.z = 0
                        d = (Matrix.Rotation(math.radians(args.angle), 3, "Z") @ fwd.normalized()).normalized()
                    else:
                        d = (cam_arm(fr) - E).normalized()
                    aim.location = E + Vector((0, 0, -0.035))
                    cam.location = aim.location + d * dist
                    cam.rotation_mode = "QUATERNION"
                    cam.rotation_quaternion = (aim.location - cam.location).to_track_quat("-Z", "Y")
                    placed = True
                render(fr, n, f"{sid}_{fr}", paths)
            n += 1


only = set(int(x) for x in args.only.split(",")) if args.only else None
paths = []
if args.mode == "shots":
    shots_render(paths)
else:
    frames = static_render(static_items()) if args.mode == "sheet" else static_render(channel_items(), raw=True)
    for n, (f, label) in enumerate(frames):
        if only is None or n in only:
            render(f, n, label, paths)
if paths:
    sheet = os.path.join(args.out, f"{args.mode}_sheet.png")
    cmd = ["montage"]
    for p, lab in paths:
        cmd += ["-label", lab, p]
    cmd += ["-tile", args.tile, "-geometry", "270x480+3+3", "-pointsize", "16", "-background", "#181818", "-fill", "#eee", sheet]
    subprocess.run(cmd, check=False)
    print("SHEET", sheet)
    if args.mode == "shots" and args.fps:
        lst = os.path.join(args.out, "clip.txt")
        with open(lst, "w") as fh:
            for p, lab in paths:
                fh.write(f"file '{p}'\nduration {1.0 / args.fps:.4f}\n")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-vf", "fps=30,format=yuv420p",
                        "-c:v", "libx264", "-crf", "20", os.path.join(args.out, "clip.mp4")], check=False)
