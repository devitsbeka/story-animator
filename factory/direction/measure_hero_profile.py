"""
Measure the hero's real framing landmarks from the rig (Blender script) -> factory/direction/hero_profile_<id>.json

    blender -b --factory-startup -P factory/direction/measure_hero_profile.py -- \
        --blend /path/library_store/characters/hero_v4/hero_v4.blend --spec episodes/sentinel/episode_v5.json \
        --asset hero_v4 --out factory/direction/hero_profile_jay.json

What it records (spec space: +y up, +z = the way the actor faces at rotY 0, metres at the actor's spec height):
  rest      landmark heights as fractions of the total height (cap top = 1.0): eye, brow, chin, mouth, shoulder,
            chest, waist, hips, head_top (skull without cap) + head height / width. These are what the camera
            presets and the shot validator use for every 'hero' subject (camgeo.HeroProfile).
  stances   per acting stance (stand / helm / brace / down / sit_deck): actor-local positions of the landmarks.
  shots     per hero shot of --spec (every 6th frame + the key frame): actor-local landmark positions of the actual
            performance (acting.pose_at -> cloudrig_adapter.apply), so a crouch, a lean or a look-down is framed
            where the head really is, not where a standing 1.8 m man's head would be.
Head landmarks ride DEF-Head rigidly (chin/brow/top measured on the rest mesh, then carried by the posed head bone).
"""
import argparse
import json
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "cloud", "blender"))
import acting  # noqa: E402
import cloudrig_adapter as CA  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--blend", required=True)
ap.add_argument("--spec", default=None)
ap.add_argument("--asset", default="hero_v4")
ap.add_argument("--height", type=float, default=1.8)
ap.add_argument("--out", required=True)
ap.add_argument("--step", type=int, default=6)
args = ap.parse_args(argv)

coll, arm, objs = CA.append_character(args.blend, "CH-jay", "RIG-jay")
CA.set_character_options(arm, {"Glasses": 0})
CA.prefer_mesh_hair(coll)
bpy.context.view_layer.update()
NAT = CA.natural_height(arm)
S = args.height / NAT
pup = CA.CloudRigPuppet(arm, None)
LM = pup.LM
inv = arm.matrix_world.inverted()


def mesh(suffix):
    return next((o for o in arm.children_recursive if o.type == "MESH" and o.name.lower().endswith(suffix) and not o.hide_render), None)


def verts(o):
    M = inv @ o.matrix_world
    return [M @ v.co for v in o.data.vertices]


head_v = verts(mesh("_head"))
front = min(v.y for v in head_v)                     # nose tip (Jay faces -Y)
mid = [v for v in head_v if abs(v.x) < 0.02]
# Jay has no chin bulge (the jaw slopes straight into the neck), so the visual chin is put just under the lower
# teeth: the front-most midline head vertex 12 mm below the bottom of the lower teeth.
teeth = mesh("_teeth_btm")
chin_z = (min(v.z for v in verts(teeth)) - 0.012) if teeth else min(v.z for v in mid if v.y < front + 0.06)
chin = min((v for v in mid if abs(v.z - chin_z) < 0.006), key=lambda v: v.y)
skull_top = max(head_v, key=lambda v: v.z)
cap = mesh("_cap")
top = max(verts(cap), key=lambda v: v.z) if cap else skull_top
eye_m = [mesh("_eye.l"), mesh("_eye.r")]
eye = sum((sum(verts(o), Vector()) / len(o.data.vertices) for o in eye_m if o), Vector()) / max(1, sum(1 for o in eye_m if o))
brows = mesh("_eyebrows")
brow = (sum(verts(brows), Vector()) / len(brows.data.vertices)) if brows else eye + Vector((0, 0, 0.03))
head_w = 2 * max(abs(v.x) for v in head_v)

hb = pup.headdef
H_rest = hb.bone.matrix_local.copy()
H_rest_inv = H_rest.inverted()
REL = {k: H_rest_inv @ p for k, p in (("eye", eye), ("brow", brow), ("chin", chin), ("top", top), ("skull", skull_top))}
chest_b = arm.pose.bones.get("DEF-Chest") or pup.chest
hips_b = arm.pose.bones.get("DEF-Hips") or pup.torso


def to_spec(p):
    return [round(S * p.x, 4), round(S * p.z, 4), round(-S * p.y, 4)]


def landmarks():
    bpy.context.view_layer.update()
    Hm = hb.matrix
    out = {k: to_spec(Hm @ v) for k, v in REL.items()}
    out["chest"] = to_spec(chest_b.matrix @ Vector((0, chest_b.bone.length * 0.5, 0)))
    out["waist"] = to_spec(hips_b.matrix.translation)
    return out


rest = {
    "eye": eye.z / NAT, "brow": brow.z / NAT, "chin": chin.z / NAT, "mouth": LM["mouth"] / NAT, "head_top": skull_top.z / NAT,
    "top": top.z / NAT, "shoulder": LM["shoulder"] / NAT, "hips": LM["hips"] / NAT,
    "chest": (LM["hips"] + 0.6 * (LM["shoulder"] - LM["hips"])) / NAT, "waist": (LM["hips"] + 0.12 * (LM["shoulder"] - LM["hips"])) / NAT,
    "head_h": (top.z - chin.z) / NAT, "face_h": (brow.z - chin.z) / NAT, "head_w": head_w / NAT, "eye_fwd": -eye.y / NAT,
}
rest = {k: round(v, 4) for k, v in rest.items()}
prof = {"rig": os.path.basename(args.blend), "asset": args.asset, "height": args.height, "natural_height": round(NAT, 4),
        "rest": rest, "stances": {}, "shots": {}}


def pose(perf, f):
    pup._prev_eul = {}
    ch, gaze = pup.face_at(f, {}, perf, [], [])
    pup.apply(acting.pose_at(f, perf), ch, gaze)


for st in ("stand", "helm", "brace", "down", "sit_deck"):
    pose({"stance": [[-10000, st]], "breath": 0.0}, 100)
    prof["stances"][st] = landmarks()

if args.spec:
    spec = json.load(open(args.spec))
    for sh in spec["shots"]:
        for a in sh.get("actors") or []:
            if a.get("asset") != args.asset:
                continue
            perf = a.get("perf") or {"stance": [[-10000, "stand"]]}
            fr = sorted(set(list(range(sh["from"], sh["to"] + 1, args.step)) + [sh["to"], sh.get("keyFrame", sh["from"])]))
            trk = []
            for f in fr:
                pose(perf, f)
                trk.append([f, landmarks()])
            prof["shots"][sh["id"]] = trk
            break
        print("measured", sh["id"], flush=True)

json.dump(prof, open(args.out, "w"), indent=1)
print("PROFILE", json.dumps(rest), "stand eye", prof["stances"]["stand"]["eye"])
