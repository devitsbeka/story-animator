"""Numeric checks for cloud/blender/cloudrig_adapter.py on jay.blend (no rendering).

  blender -b --factory-startup -P cloud/blender/test/cloudrig_adapter_test.py [-- --blend path/to/jay.blend]

Bakes the 12 acting test poses + a face track through CloudRigPuppet.bake() and asserts that
  * the solved wrists land on the (clamped) hand targets, feet on their targets (IK really drives the rig),
  * hands stay out of the head volume and inside arm reach,
  * eyes aim along the requested head-relative gaze, lids close fully on a blink and the jaw opens on a viseme,
  * the face channels move the DEF face bones in the authored direction (smile up, brows up, jaw down).
Prints PASS/FAIL lines and exits non-zero on failure.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import acting  # noqa: E402
import cloudrig_adapter as cra  # noqa: E402
import face  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
BLEND = argv[argv.index("--blend") + 1] if "--blend" in argv else "/home/user/story-animator/library_store/characters/jay.blend"
FAILS = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{info}]" if info else ""))
    if not ok:
        FAILS.append(name)


bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
coll, arm, objs = cra.append_character(BLEND, "CH-jay", "RIG-jay")
check("append CH-jay -> RIG-jay", arm is not None and len(arm.pose.bones) > 1000, f"{len(objs)} objects")
pup = cra.CloudRigPuppet(arm)
print("MEASURE", pup.describe())
check("natural height ~1.26 m", 1.2 < cra.natural_height(arm) < 1.32, f"{cra.natural_height(arm):.3f}")
P = arm.pose.bones
for pb in P:
    if pb.name.startswith("PRP-UpperArm") or pb.name.startswith("PRP-Thigh"):
        ik = [k for k in pb.keys() if k.startswith("ik_") and (k.endswith("_arm") or k.endswith("_leg")) and "stretch" not in k and "parents" not in k and "pole" not in k]
        check(f"{pb.name} in IK", all(pb[k] == 1.0 for k in ik), str({k: pb[k] for k in ik}))

tests = [("stand", None), ("helm", None), ("brace", None), ("stand", "radio_shout"), ("stand", "shush"), ("stand", "phone_up"),
         ("stand", "wave"), ("stand", "hands_face"), ("stand", "look_back"), ("sit_deck", None), ("down", None), ("stand", "point_ahead")]
perf = {"stance": [], "poses": [], "blend": 1, "seed": 2}
for i, (st, ps) in enumerate(tests):
    perf["stance"].append([i * 10, st])
    if ps:
        perf["poses"].append({"pose": ps, "from": i * 10, "to": i * 10 + 9, "in": 1, "out": 1})
perf["stance"][0][0] = -100
fs = {"gaze": [[0, 0, 0], [20, 25, 0], [40, 0, -20]], "blinks": [55], "emotion": [[0, "neutral"], [60, "shock"]],
      "words": [{"w": "aa", "s": 75 / 30, "e": 79 / 30}], "seed": 3}
keyed = pup.bake(perf, fs, 0, len(tests) * 10)
check("bake keyed controls", len(keyed) >= 30, f"{len(keyed)} controls")
act = arm.animation_data.action
check("action has fcurves", act is not None and len(act.fcurves) > 100, f"{len(act.fcurves) if act else 0} fcurves")


def head_info():
    hd = P["DEF-Head"]
    hq = hd.matrix.to_quaternion() @ hd.bone.matrix_local.to_quaternion().inverted()
    hc = hd.matrix @ (hd.bone.matrix_local.inverted() @ pup.head_c)
    return hq, hc


for i, (st, ps) in enumerate(tests):
    f = i * 10 + 8
    sc.frame_set(f)
    pose = acting.pose_at(f, perf)
    hq, hc = head_info()
    for s in "LR":
        tgt = P[f"IK-MSTR-Wrist.{s}"].head
        wr = P[f"DEF-Wrist.{s}"].head if f"DEF-Wrist.{s}" in P else P[f"ORG-Wrist.{s}"].head
        err = (wr - tgt).length
        sh = P[f"IK-UpperArm.{s}"].head
        reach = (tgt - sh).length
        d = hq.inverted() @ (wr - hc)
        e = (d.x / pup.head_r.x) ** 2 + (d.y / pup.head_r.y) ** 2 + (d.z / pup.head_r.z) ** 2
        check(f"{st}{'+' + ps if ps else ''} wrist.{s} on target", err < 0.012, f"err {err * 100:.1f} cm, reach {reach:.3f}/{pup.arm_len[s]:.3f}")
        check(f"{st}{'+' + ps if ps else ''} wrist.{s} outside head", e >= 0.98, f"ellipsoid {e:.2f}")
        ft = P[f"IK-MSTR-Foot.{s}"].head
        fd = P[f"DEF-Foot.{s}"].head
        check(f"{st}{'+' + ps if ps else ''} foot.{s} on target", (ft - fd).length < 0.012, f"{(ft - fd).length * 100:.1f} cm")
    if st == "sit_deck":
        check("sit_deck hips low", P["MSTR-Spine_Torso"].head.z < pup.LM["hips"] - 0.25, f"torso z {P['MSTR-Spine_Torso'].head.z:.3f}")
    if ps == "look_back":
        hq, _ = head_info()
        fwd = hq @ Vector((0, -1, 0))
        yaw = math.degrees(math.atan2(fwd.x, -fwd.y))
        check("look_back turns head to his left", yaw > 30, f"head yaw {yaw:.0f} deg")

# gaze: eye bones aim along the head-relative gaze
for f, want in ((30, (25, 0)), (48, (0, -20))):
    sc.frame_set(f)
    hq, _ = head_info()
    eye = P["DEF-Eye.L"]
    d = hq.inverted() @ (eye.tail - eye.head).normalized()
    rest = (eye.bone.tail_local - eye.bone.head_local).normalized()
    yaw = math.degrees(math.atan2(d.x, -d.y)) - math.degrees(math.atan2(rest.x, -rest.y))
    pitch = math.degrees(math.asin(max(-1, min(1, d.z)))) - math.degrees(math.asin(max(-1, min(1, rest.z))))
    g = face.gaze_at(f, fs["gaze"], 3)
    g = (g[0] * pup.gaze_gain[0], g[1] * pup.gaze_gain[1])
    check(f"gaze f{f} yaw", abs(yaw - g[0]) < 6, f"eye yaw {yaw:.1f} vs {g[0]:.1f}")
    check(f"gaze f{f} pitch", abs(pitch - g[1]) < 6, f"eye pitch {pitch:.1f} vs {g[1]:.1f}")

# blink at 55 (+2 frames = fully closed) -> upper lid control at its closed limit
sc.frame_set(57)
v = P["ACT-Eyelid_Upper.L"].location.y
check("blink closes the upper lid", v <= -0.024, f"lid loc.y {v:.4f}")
sc.frame_set(50)
v2 = P["ACT-Eyelid_Upper.L"].location.y
check("open between blinks", v2 > -0.012, f"lid loc.y {v2:.4f}")
# viseme 'aa' around 77 -> jaw open
sc.frame_set(77)
check("viseme opens the jaw", P["Jaw"].location.z > 0.015, f"jaw z {P['Jaw'].location.z:.4f}")

# face channel directions on the DEF bones (rest pose body)
stand = acting.pose_at(0, {"stance": [[-100, "stand"]], "breath": 0})


def def_z(names, ch):
    pup.apply(stand, ch, (0, 0))
    bpy.context.view_layer.update()
    return {n: P[n].head.copy() for n in names}


base = def_z(["DEF-Lip_Corner.L", "DEF-Lip_Corner.R", "DEF-Eyebrow3.L", "DEF-Eyebrow3.R", "DEF-Jaw"], {})
sm = def_z(["DEF-Lip_Corner.L", "DEF-Lip_Corner.R"], cra.FACE_POSES["content"])
check("smile lifts both corners", all(sm[n].z - base[n].z > 0.004 for n in sm), str({n: round(sm[n].z - base[n].z, 4) for n in sm}))
fr = def_z(["DEF-Lip_Corner.L", "DEF-Lip_Corner.R"], {"cornerUp.L": -1, "cornerUp.R": -1})
check("frown drops both corners", all(fr[n].z - base[n].z < -0.004 for n in fr), str({n: round(fr[n].z - base[n].z, 4) for n in fr}))
br = def_z(["DEF-Eyebrow3.L", "DEF-Eyebrow3.R"], {"browUp.L": 1, "browUp.R": 1})
check("brows up", all(br[n].z - base[n].z > 0.006 for n in br), str({n: round(br[n].z - base[n].z, 4) for n in br}))
jw = def_z(["DEF-Jaw"], {"jaw": 1})
check("jaw opens down", jw["DEF-Jaw"].z - base["DEF-Jaw"].z < -0.02, f"{jw['DEF-Jaw'].z - base['DEF-Jaw'].z:.4f}")
wd = def_z(["DEF-Lip_Corner.L", "DEF-Lip_Corner.R"], {"cornerWide.L": 1, "cornerWide.R": 1})
check("wide moves corners outward", wd["DEF-Lip_Corner.L"].x - base["DEF-Lip_Corner.L"].x > 0.004 and wd["DEF-Lip_Corner.R"].x - base["DEF-Lip_Corner.R"].x < -0.004)

print(f"RESULT {'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failures", FAILS)
sys.exit(1 if FAILS else 0)
