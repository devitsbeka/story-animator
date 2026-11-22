"""L031 regression: the stress generator's hand-shape intent list (perf.hands = [[frame, shapeL, shapeR]], read by pose
QC) must never override the hand shapes a stance or pose authors (the merge made phone_up's grip_flat a fist and
hands_up's open palms relaxed). Dict entries ({"L": shape} or [{"hand", "shape", ...}]) still drive the hands.
acting.pose_at is pure maths; bpy / mathutils are stubbed so this runs without Blender."""
import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _acting():
    sys.modules.setdefault("bpy", types.ModuleType("bpy"))
    if "mathutils" not in sys.modules:
        m = types.ModuleType("mathutils")
        for n in ("Vector", "Matrix", "Quaternion", "Euler"):
            setattr(m, n, object)
        sys.modules["mathutils"] = m
    sys.path.insert(0, os.path.join(ROOT, "cloud", "blender"))
    import acting
    return acting


def _top(shape):
    return max(shape.items(), key=lambda kv: kv[1])[0] if isinstance(shape, dict) else shape


def _perf(pose, hands):
    return {"stance": [[-10000, "stand"]], "poses": [{"pose": pose, "from": 0, "to": 100, "in": 1, "out": 1}] if pose else [],
            "hands": hands}


def test_intent_list_does_not_override_pose_shapes():
    A = _acting()
    p = A.pose_at(50, _perf("phone_up", [[-10000, "relaxed", "grip"]]))
    assert _top(p["handShapeR"]) == "grip_flat"
    p = A.pose_at(50, _perf("hands_up", [[-10000, "relaxed", "open_palm"]]))
    assert _top(p["handShapeL"]) == "open_palm_wave" and _top(p["handShapeR"]) == "open_palm_wave"


def test_dict_hand_overrides_still_apply():
    A = _acting()
    assert _top(A.pose_at(50, _perf(None, {"R": "grip"}))["handShapeR"]) == "grip"
    assert _top(A.pose_at(50, _perf(None, [{"hand": "L", "shape": "point"}]))["handShapeL"]) == "point"
