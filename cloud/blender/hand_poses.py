"""
HAND POSES: finger shapes for the CloudRig hero (RIG-jay), authored as data.

The rig's hands are FK chains (bone collection 'FK Controls'): FK-Finger_<F>_Carpal / <F>1 / <F>2 / <F>3 for
Index / Middle / Ring / Pinky and FK-Finger_Thumb1..3, each side .L / .R. Measured on hero_v4 (T-pose rest: fingers
along +-X, palm facing -Z, thumb toward -Y = front):
  local +X rotation = CURL toward the palm on both sides (same sign L and R),
  local  Z rotation = SPREAD (sideways); mirrored between sides, so R uses -Z.
  The thumb's X folds it across the palm (opposition), its Z bends it down toward the palm (flexion).

A SHAPE is {finger: (carpal, k1, k2, k3, spread)} in degrees for the four fingers and
{"Thumb": (t1x, t1z, t2x, t3x)} for the thumb. Shapes blend linearly (weights from acting.pose_at's handShapeL/R
channels), so a pose->pose transition curls the fingers through the in-between.

Contact points (where a hand touches the thing it holds) are given in the CANONICAL HAND FRAME, rig (armature)
units, relative to the wrist pivot: (F along the fingers, N along the palm normal (+ = in front of the palm, where a
held thing is), T toward the thumb side). cloudrig_adapter uses them to put the right part of the hand on an anchor
(wheel rim, rail, lips...). Rest frame of hero_v4: F = +X (.L) / -X (.R), N = -Z, T = -Y.
"""
import math

FINGERS = ("Index", "Middle", "Ring", "Pinky")
# spread direction per finger: + fans away from the middle finger (index toward the thumb, pinky away from it)
FAN = {"Index": 1.0, "Middle": 0.25, "Ring": -0.45, "Pinky": -1.0}


def _f(i, m, r, p, thumb):
    return {"Index": i, "Middle": m, "Ring": r, "Pinky": p, "Thumb": thumb}


# (carpal, k1, k2, k3, spread) / thumb (t1x, t1z, t2x, t3x)
SHAPES = {
    # natural rest: each finger a little more curled than the one before it (index -> pinky cascade), thumb soft
    # (index least curled -> pinky most, fingers gently converging, never splayed; thumb soft beside the index)
    "relaxed": _f((2, 12, 24, 13, 0), (3, 17, 30, 15, -0.5), (4, 23, 35, 17, -1.5), (6, 29, 40, 19, -3), (20, 12, 16, 12)),
    "fist": _f((4, 80, 95, 55, 0), (5, 85, 95, 55, 0), (6, 88, 95, 55, 0), (8, 90, 95, 55, 0), (40, 30, 30, 35)),
    # wrapped round a tube ~ the size of a wheel rim / rail / radio body: big k1, softer k2/k3, thumb opposed
    "grip_cylinder": _f((3, 56, 52, 26, 0), (4, 60, 54, 26, 0), (5, 62, 56, 26, 0), (7, 66, 56, 26, 0), (44, 22, 18, 14)),
    # holding a flat slab (phone): fingers behind it, thumb on the front face
    "grip_flat": _f((2, 38, 40, 20, 1), (3, 42, 40, 20, 0), (4, 46, 40, 20, 0), (6, 50, 40, 22, 1), (30, 4, 8, 10)),
    # index straight forward, the rest a loose fist, thumb tucked on the middle finger
    "point": _f((0, 0, 2, 2, 3), (5, 78, 92, 50, 0), (6, 84, 92, 50, 0), (8, 88, 92, 50, 0), (58, 34, 26, 26)),
    # 'shh': index straight up at the lips, others curled, thumb holding them
    "shush": _f((0, 2, 4, 2, 2), (5, 76, 88, 48, 0), (6, 82, 88, 48, 0), (8, 86, 88, 48, 0), (58, 34, 26, 26)),
    # open hand facing out for a wave: fingers long, gently spread, slight natural curl so it never reads as a paddle
    "open_palm_wave": _f((0, 5, 8, 5, 6), (0, 6, 9, 5, 2), (1, 8, 11, 6, 4), (2, 11, 13, 7, 8), (-4, -4, 6, 5)),
    # bracing: fingers spread wide, a little hooked, thumb out
    "brace_spread": _f((1, 14, 20, 12, 5), (1, 16, 22, 13, 1), (2, 20, 25, 14, 3), (3, 24, 28, 16, 6), (8, 0, 12, 8)),
    # pressing a button: index extended (slightly bent), the rest curled
    "press": _f((0, 8, 10, 6, 2), (4, 64, 80, 44, 0), (5, 72, 82, 44, 0), (7, 78, 82, 44, 0), (54, 30, 24, 24)),
}

NAMES = tuple(SHAPES)

# which part of the hand meets an anchor for a given shape
CONTACT = {"grip_cylinder": "grip", "fist": "grip", "grip_flat": "flat", "point": "tip", "shush": "tip", "press": "tip"}
# canonical hand frame offsets (F, N, T) from the wrist pivot, rig units
# (hero_v4 rest: wrist pivot -> middle knuckle 0.093, -> index tip 0.160, palm ~0.03 thick)
CONTACT_OFFSET = {
    "palm": (0.050, 0.020, 0.0),
    "grip": (0.080, 0.036, 0.004),
    "flat": (0.062, 0.026, 0.0),
    "tip": (0.152, 0.004, 0.050),
}


def as_weights(v):
    """'fist' | {'fist': .6, 'relaxed': .4} | None -> normalised {name: w} (empty -> relaxed)."""
    if v is None:
        return {"relaxed": 1.0}
    if isinstance(v, str):
        return {v: 1.0} if v in SHAPES else {"relaxed": 1.0}
    w = {k: float(x) for k, x in v.items() if k in SHAPES and x > 1e-4}
    s = sum(w.values())
    if s <= 1e-6:
        return {"relaxed": 1.0}
    return {k: x / s for k, x in w.items()}


def dominant(weights):
    w = as_weights(weights)
    return max(w.items(), key=lambda kv: kv[1])[0]


def contact_point(weights, kind=None):
    """contact offset (F, N, T) for a shape mix, or for an explicit contact kind ('palm' | 'grip' | 'flat' | 'tip')."""
    if kind:
        return CONTACT_OFFSET[kind]
    w = as_weights(weights)
    out = [0.0, 0.0, 0.0]
    for k, x in w.items():
        o = CONTACT_OFFSET[CONTACT.get(k, "palm")]
        for i in range(3):
            out[i] += o[i] * x
    return tuple(out)


def finger_euler(weights, side):
    """{bone name: (x, y, z) radians} for every FK finger control of one hand."""
    w = as_weights(weights)
    zs = -1.0 if side == "R" else 1.0
    out = {}
    for fn in FINGERS:
        acc = [0.0] * 5
        for k, x in w.items():
            v = SHAPES[k][fn]
            for i in range(5):
                acc[i] += v[i] * x
        car, k1, k2, k3, spr = acc
        out[f"FK-Finger_{fn}_Carpal.{side}"] = (math.radians(car), 0.0, 0.0)
        out[f"FK-Finger_{fn}1.{side}"] = (math.radians(k1), 0.0, math.radians(spr * FAN[fn] * zs))
        out[f"FK-Finger_{fn}2.{side}"] = (math.radians(k2), 0.0, 0.0)
        out[f"FK-Finger_{fn}3.{side}"] = (math.radians(k3), 0.0, 0.0)
    acc = [0.0] * 4
    for k, x in w.items():
        for i in range(4):
            acc[i] += SHAPES[k]["Thumb"][i] * x
    t1x, t1z, t2x, t3x = acc
    out[f"FK-Finger_Thumb1.{side}"] = (math.radians(t1x), 0.0, math.radians(t1z * zs))
    out[f"FK-Finger_Thumb2.{side}"] = (math.radians(t2x), 0.0, 0.0)
    out[f"FK-Finger_Thumb3.{side}"] = (math.radians(t3x), 0.0, 0.0)
    return out


def bone_names(side):
    return list(finger_euler("relaxed", side).keys())


# ---------------------------------------------------------------- hand-held props on ORG-Wrist.<S> (BONE_ALIAS; DEF-Wrist only takes HALF the hand rotation)
# A prop parented to a bone sits at the bone's TAIL, in the bone's rest axes. ORG-Wrist = DEF-Wrist rest (hero_v4) bone axes in the
# canonical frame: Y = F on both sides; X = -N on .L (back of the hand) / +N on .R; Z = -T on both sides.
# PROP_GRIPS: 'loc' = the prop origin (its grip point, props.py) in the canonical frame (F, N, T) from the wrist
# pivot, rig units; 'axes' = which canonical axis the prop's +Z (long axis) and -Y (front face) point along;
# 'shape' = the hand shape that holds it.
BONE_AXIS = {"L": {"F": (0, 1, 0), "N": (-1, 0, 0), "T": (0, 0, -1)},
             "R": {"F": (0, 1, 0), "N": (1, 0, 0), "T": (0, 0, -1)}}
PROP_GRIPS = {
    # radio / beacon lie along the palm (antenna toward the fingertips), front face away from the palm: Jay's short
    # arms + the rig's wrist limit cannot hold a fist-gripped radio upright at the mouth, a phone-style hold can
    "radio": {"loc": (0.085, 0.034, 0.0), "axes": ("F", "N"), "shape": "grip_flat"},
    "beacon": {"loc": (0.090, 0.040, 0.0), "axes": ("F", "N"), "shape": "grip_flat"},
    # phone lying on the fingers/palm, top toward the fingertips, screen facing out of the palm
    "phone": {"loc": (0.075, 0.020, 0.0), "axes": ("F", "N"), "shape": "grip_flat"},
}


def _neg(v):
    return tuple(-x for x in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def prop_grip(prop, side, bone_length):
    """(location in bone-TAIL space, (prop X, Y, Z axes in bone axes)) for a hand-held prop, or None."""
    g = PROP_GRIPS.get(prop)
    if not g:
        return None
    ax = BONE_AXIS[side]
    f, n, t = g["loc"]
    loc = [ax["F"][i] * f + ax["N"][i] * n + ax["T"][i] * t for i in range(3)]
    loc[1] -= bone_length                      # bone space origin is the tail
    z = ax[g["axes"][0]]
    y = _neg(ax[g["axes"][1]])                 # the prop's -Y is its front
    x = _cross(y, z)
    return tuple(loc), (x, y, z)
