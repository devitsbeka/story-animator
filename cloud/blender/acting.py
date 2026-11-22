"""
ACTING: code-driven character performance in Blender (no generated clips).

The hero is puppeteered via a control rig built on the Meshy skeleton:
  - 2-bone IK for both arms (hand targets + elbow poles) and both legs (ankle targets + knee poles)
  - hips translation/rotation, a 3-bone spine bend, neck/head rotation, head look-at
Performance is data: a base STANCE plus timed POSE overlays and procedural VERBS
(shake_head, nod, sneeze, fall, breathe_hard, flinch...). Every channel is a pure
function of the frame, baked to keyframes, so a shot renders identically on any worker.

Character-local space (metres, as imported): +X = hero's LEFT, -Y = hero's FRONT, +Z = up,
origin between the feet. Angles in degrees: pitch + = lean forward, yaw + = turn to hero's left,
roll + = tilt toward hero's left.
"""
import math
import bpy
from mathutils import Matrix, Quaternion, Vector, Euler

# ---------------------------------------------------------------- easing
def _bez(x1, y1, x2, y2):
    def f(x):
        x = min(1.0, max(0.0, x))
        t = x
        for _ in range(10):
            cx = 3 * x1 * t * (1 - t) ** 2 + 3 * x2 * t * t * (1 - t) + t ** 3 - x
            d = 3 * x1 * (1 - t) ** 2 + 6 * (x2 - x1) * t * (1 - t) + 3 * (1 - x2) * t * t
            if abs(d) < 1e-6:
                break
            t = min(1.0, max(0.0, t - cx / d))
        return 3 * y1 * t * (1 - t) ** 2 + 3 * y2 * t * t * (1 - t) + t ** 3
    return f

EASE = {
    "smooth": _bez(0.45, 0, 0.25, 1),       # default: quick-in, soft settle
    "snap": _bez(0.2, 0.9, 0.3, 1),         # fast reaction
    "anticipate": _bez(0.5, -0.3, 0.25, 1), # small wind-up, then go
    "overshoot": _bez(0.3, 1.4, 0.6, 1),    # past the mark, settle back
    "heavy": _bez(0.7, 0, 0.3, 1),          # slow start, weight
    "linear": lambda t: min(1.0, max(0.0, t)),
}

def lerp(a, b, t):
    return a + (b - a) * t

def vlerp(a, b, t):
    return [lerp(x, y, t) for x, y in zip(a, b)]

# ---------------------------------------------------------------- the pose model
CHANNELS = ("hips", "hipsRot", "chest", "head", "handL", "handR", "handRotL", "handRotR", "footL", "footR", "poleL", "poleR",
            # >>> hands/contact channels (polish_hands_pose)
            "handShapeL", "handShapeR", "anchorL", "anchorR", "anchorHips", "palmL", "palmR", "fingL", "fingR")
# Dict channels blend as weight maps (a missing key = weight 0):
#   handShapeL/R  {shape: w} over hand_poses.SHAPES (a string = that shape at 1.0) -> finger poses (CloudRig hero)
#   anchorL/R     {anchor: w}: put the hand's contact point ON a named anchor (helm wheel rim, rail, knee, mouth,
#                 bench...) instead of the free hand target, by that weight; anchors come from the shot
#                 (contact.py: props, rails, marks) or from the body itself (knee_L/R, mouth, seat_L/R)
#   anchorHips    {anchor: w}: seat the pelvis on an anchor (bench seat / deck) - absolute, for Jay's real proportions
# Vector channels palmL/R + fingL/R: the direction the palm faces / the fingers point (char space); their LENGTH is
# the blend weight against the default (hand continuing the forearm), so [0,0,0] = no orientation authored.
DICT_CHANNELS = ("handShapeL", "handShapeR", "anchorL", "anchorR", "anchorHips")
# <<< hands/contact channels

# relaxed standing (measured from the hero rig: shoulders ~1.32 m, hips 0.93 m, ankles 0.16 m)
STANCES = {
    "stand": {
        "hips": [0, 0, 0], "hipsRot": [0, 0, 0], "chest": [2, 0, 0], "head": [0, 0, 0],
        "handL": [0.235, -0.03, 0.86], "handR": [-0.235, -0.03, 0.86],
        "handRotL": [0, 0, 0], "handRotR": [0, 0, 0],
        "footL": [0.13, -0.05, 0.16], "footR": [-0.13, -0.03, 0.16],
        "poleL": [0.45, 0.45, 1.05], "poleR": [-0.45, 0.45, 1.05],
        "handShapeL": "relaxed", "handShapeR": "relaxed", "anchorL": {}, "anchorR": {}, "anchorHips": {},
        "palmL": [-1, 0.25, 0], "palmR": [1, 0.25, 0], "fingL": [0, 0, 0], "fingR": [0, 0, 0],   # palms to the thighs, thumbs forward
    },
    # feet wider, knees soft, centre of mass low: riding a moving deck
    "brace": {
        "hips": [0, 0.02, -0.06], "hipsRot": [4, 0, 0], "chest": [6, 0, 0], "head": [-4, 0, 0],
        "handL": [0.30, -0.12, 0.92], "handR": [-0.30, -0.12, 0.92],
        "footL": [0.22, -0.02, 0.16], "footR": [-0.22, 0.02, 0.16],
        "handShapeL": {"relaxed": 0.7, "brace_spread": 0.3}, "handShapeR": {"relaxed": 0.7, "brace_spread": 0.3},
        "palmL": [-0.75, 0.1, -0.65], "palmR": [0.75, 0.1, -0.65],
    },
    # both hands on a wheel in front of him at waist height (on the rim at 10 and 2 when the shot has a helm prop)
    "helm": {
        "hips": [0, 0.0, -0.02], "chest": [5, 0, 0],
        "handL": [0.17, -0.30, 1.06], "handR": [-0.17, -0.30, 1.06],
        "poleL": [0.6, 0.1, 0.9], "poleR": [-0.6, 0.1, 0.9],
        "handShapeL": "grip_cylinder", "handShapeR": "grip_cylinder", "anchorL": {"helm_L": 1}, "anchorR": {"helm_R": 1},
    },
    # sitting on the deck, back against the cabin, knees up, hands on knees (legacy; prefer sit_deck_relaxed / sit_bench)
    "sit_deck": {
        "hips": [0, 0.10, -0.70], "hipsRot": [-6, 0, 0], "chest": [10, 0, 0], "head": [-4, 0, 0],
        "footL": [0.17, -0.34, 0.09], "footR": [-0.17, -0.32, 0.09],
        "handL": [0.20, -0.36, 0.50], "handR": [-0.20, -0.36, 0.50],
        "poleL": [0.5, 0.2, 0.6], "poleR": [-0.5, 0.2, 0.6],
        "anchorL": {"knee_L": 1}, "anchorR": {"knee_R": 1}, "anchorHips": {"floor": 1},
        "palmL": [0, 0, -1], "palmR": [0, 0, -1], "fingL": [0.1, -1, -0.5], "fingR": [-0.1, -1, -0.5],
    },
    # >>> sitting stances (polish_hands_pose). Hips go ON the seat anchor (marks.py 'bench_seat' = the yacht_v2 aft
    # cockpit bench, seat 0.45 m above the sole) - the actor's mark (SITMARK) is where his feet are, the seat ~0.5 m behind.
    # Back upright / slightly forward (whole torso pitched +6, chest +8 more), feet planted, forearms on the knees.
    "sit_bench": {
        "hips": [0, 0.50, -0.36], "hipsRot": [9, 0, 0], "chest": [12, 0, 0], "head": [-12, 0, 0],
        "footL": [0.15, -0.04, 0.16], "footR": [-0.14, -0.01, 0.16],
        "handL": [0.17, -0.22, 0.62], "handR": [-0.17, -0.20, 0.62],
        "poleL": [0.6, 0.3, 0.5], "poleR": [-0.6, 0.3, 0.5],
        "anchorL": {"knee_L": 1}, "anchorR": {"knee_R": 1}, "anchorHips": {"bench_seat": 1},
        "palmL": [0, 0, -1], "palmR": [0, 0, -1], "fingL": [0.15, -1, -0.7], "fingR": [-0.15, -1, -0.7],
    },
    # on the deck, legs bent, back upright (leans only on a padded surface when the shot gives one: anchor 'backrest')
    "sit_deck_relaxed": {
        "hips": [0, 0.32, -0.74], "hipsRot": [4, 0, 0], "chest": [6, 0, 0], "head": [-6, 0, 0],
        "footL": [0.17, -0.18, 0.16], "footR": [-0.16, -0.14, 0.16],
        "handL": [0.20, -0.20, 0.42], "handR": [-0.20, -0.18, 0.42],
        "poleL": [0.6, 0.2, 0.4], "poleR": [-0.6, 0.2, 0.4],
        "anchorL": {"knee_L": 1}, "anchorR": {"knee_R": 1}, "anchorHips": {"floor": 1},
        "palmL": [0, 0, -1], "palmR": [0, 0, -1], "fingL": [0.15, -1, -0.7], "fingR": [-0.15, -1, -0.7],
    },
    # <<< sitting stances
    # thrown onto hands and knees by an impact
    "down": {
        "hips": [0, 0.15, -0.55], "hipsRot": [55, 0, 6], "chest": [25, 0, 0], "head": [-35, 0, 0],
        "footL": [0.14, 0.45, 0.08], "footR": [-0.16, 0.42, 0.08],
        "handL": [0.25, -0.45, 0.06], "handR": [-0.25, -0.42, 0.06],
        "poleL": [0.3, -0.6, 0.3], "poleR": [-0.3, -0.6, 0.3],
        "handShapeL": "brace_spread", "handShapeR": "brace_spread",
        "palmL": [0, 0, -1], "palmR": [0, 0, -1], "fingL": [0.2, -1, 0], "fingR": [-0.2, -1, 0],
    },
}

# hand-target key poses (overlay only the channels they name)
POSES = {
    "radio_mouth":   {"handR": [-0.07, -0.17, 1.42], "handRotR": [0, 0, 0], "poleR": [-0.32, 0.05, 0.75], "head": [6, -6, 0], "chest": [8, -6, 0]},
    "radio_shout":   {"handR": [-0.06, -0.18, 1.43], "handRotR": [0, 0, 0], "poleR": [-0.32, 0.05, 0.75], "head": [-8, -4, 0], "chest": [-4, -6, 0], "handL": [0.30, -0.25, 1.05]},
    "radio_wait":    {"handR": [-0.14, -0.22, 1.22], "handRotR": [0, 0, 0], "poleR": [-0.32, 0.05, 0.75], "head": [4, 8, 0]},
    "press_ahead":   {"handR": [-0.10, -0.38, 1.20], "poleR": [-0.6, 0.1, 1.2], "chest": [12, 0, 0], "head": [14, 0, 0]},
    "beacon_pull":   {"handR": [-0.10, -0.36, 0.95], "handL": [0.08, -0.34, 0.92], "chest": [22, 0, 0], "head": [20, 0, 0], "hips": [0, 0.04, -0.08]},
    "beacon_raise":  {"handR": [-0.12, -0.12, 1.68], "handL": [0.30, -0.10, 1.00], "head": [-18, -4, 0], "chest": [-6, 0, 0]},
    "shush":         {"handR": [-0.02, -0.19, 1.45], "handRotR": [0, 0, 0], "poleR": [-0.32, 0.05, 0.75], "head": [4, 0, 0]},
    "cover_mouth":   {"handR": [-0.03, -0.18, 1.44], "handRotR": [0, 0, 0], "poleR": [-0.32, 0.05, 0.75]},
    "phone_up":      {"handR": [-0.06, -0.30, 1.36], "handL": [0.06, -0.30, 1.36], "poleR": [-0.32, 0.05, 0.75], "poleL": [0.32, 0.05, 0.75], "head": [4, 0, 0]},
    "wave":          {"handR": [-0.33, -0.08, 1.55], "poleR": [-0.7, 0.2, 1.1], "head": [0, 0, 0]},
    "point_ahead":   {"handR": [-0.16, -0.40, 1.38], "poleR": [-0.7, 0.2, 1.2]},
    "hold_rail":     {"handL": [0.38, -0.08, 1.02], "handR": [-0.38, -0.08, 1.02], "poleL": [0.7, 0.4, 1.1], "poleR": [-0.7, 0.4, 1.1]},
    "rail_ahead":    {"handL": [0.20, -0.34, 1.02], "handR": [-0.20, -0.34, 1.02], "chest": [10, 0, 0]},
    "tie_bag":       {"handR": [-0.06, -0.36, 0.95], "handL": [0.06, -0.36, 0.95], "chest": [24, 0, 0], "head": [26, 0, 0], "hips": [0, 0.05, -0.12]},
    "hands_up":      {"handR": [-0.30, -0.12, 1.72], "handL": [0.30, -0.12, 1.72], "head": [-10, 0, 0]},
    "hands_face":    {"handR": [-0.07, -0.19, 1.45], "handL": [0.07, -0.19, 1.45], "chest": [10, 0, 0], "poleR": [-0.32, 0.05, 0.75], "poleL": [0.32, 0.05, 0.75]},
    "look_left":     {"head": [0, 35, 0], "chest": [0, 12, 0]},
    "look_right":    {"head": [0, -35, 0], "chest": [0, -12, 0]},
    "look_back":     {"head": [0, 55, 0], "chest": [0, 30, 0], "hipsRot": [0, 15, 0]},
    "look_down":     {"head": [30, 0, 0], "chest": [8, 0, 0]},
    "look_up":       {"head": [-28, 0, 0], "chest": [-6, 0, 0]},
    "lean_in":       {"chest": [14, 0, 0], "head": [-6, 0, 0], "hips": [0, -0.03, -0.02]},
    "recoil":        {"chest": [-12, 0, 0], "head": [-10, 0, 0], "hips": [0, 0.06, 0]},
}

# >>> hand shapes / palm orientation / anchors for every pose (polish_hands_pose). Merged into POSES so a pose
# carries its hands with it; a pose that does not name a hand leaves that hand's channels to the stance.
_RADIO = {"handShapeR": "grip_flat", "palmR": [0.1, 1, 0.35], "fingR": [0.25, -0.35, 1]}   # phone-style hold, palm to the face
_HANDS = {
    "radio_mouth":  dict(_RADIO, anchorR={"mouth_radio": 1}),
    "radio_shout":  dict(_RADIO, anchorR={"mouth_radio": 1}, handShapeL="brace_spread"),
    "radio_wait":   dict(_RADIO),
    "press_ahead":  {"handShapeR": "press", "palmR": [0.25, 0, -1], "fingR": [0, -1, -0.15], "anchorR": {"switch_R": 1}},
    "beacon_pull":  {"handShapeR": "grip_flat", "handShapeL": "grip_cylinder",
                     "palmR": [0.6, 0, -0.8], "fingR": [0, -1, 0], "palmL": [-0.6, 0, -0.8], "fingL": [0, -1, 0]},
    "beacon_raise": {"handShapeR": "grip_flat", "palmR": [0.9, 0.2, 0], "fingR": [0.15, -0.1, 1],
                     "handR": [-0.16, -0.10, 1.72], "poleR": [-0.8, 0.0, 1.3],
                     "handShapeL": {"relaxed": 0.5, "brace_spread": 0.5}},
    "shush":        {"handShapeR": "shush", "anchorR": {"mouth": 1}, "palmR": [1, 0.15, 0], "fingR": [0, 0, 1]},
    "cover_mouth":  {"handShapeR": "relaxed", "anchorR": {"mouth_palm": 1}, "palmR": [0, 1, 0], "fingR": [1, 0, 0.35]},
    "phone_up":     {"handShapeR": "grip_flat", "palmR": [0.15, 1, 0.45], "fingR": [0.1, -0.4, 1],
                     "handR": [-0.09, -0.40, 1.17], "poleR": [-0.5, 0.1, 0.8], "head": [16, -4, 0], "chest": [6, 0, 0],
                     "handL": [0.22, -0.06, 0.90], "poleL": [0.45, 0.45, 1.05], "handShapeL": "relaxed"},
    "wave":         {"handShapeR": "open_palm_wave", "palmR": [0.1, -1, 0], "fingR": [-0.15, 0, 1]},
    "point_ahead":  {"handShapeR": "point", "palmR": [0.7, 0, -0.7], "fingR": [0, -1, 0]},
    "hold_rail":    {"handShapeL": "grip_cylinder", "handShapeR": "grip_cylinder", "anchorL": {"rail_L": 1}, "anchorR": {"rail_R": 1}},
    "rail_ahead":   {"handShapeL": "grip_cylinder", "handShapeR": "grip_cylinder", "anchorL": {"rail_L": 1}, "anchorR": {"rail_R": 1}},
    "tie_bag":      {"handShapeL": "grip_cylinder", "handShapeR": "grip_cylinder", "anchorL": {"bag_L": 1}, "anchorR": {"bag_R": 1},
                     "palmR": [0.6, 0, -0.8], "fingR": [0, -1, 0], "palmL": [-0.6, 0, -0.8], "fingL": [0, -1, 0]},
    "hands_up":     {"handShapeL": "open_palm_wave", "handShapeR": "open_palm_wave",
                     "palmL": [-0.1, -1, 0], "fingL": [0.15, 0, 1], "palmR": [0.1, -1, 0], "fingR": [-0.15, 0, 1]},
    "hands_face":   {"handShapeL": "relaxed", "handShapeR": "relaxed",
                     "palmL": [-0.3, 1, 0], "fingL": [0, 0, 1], "palmR": [0.3, 1, 0], "fingR": [0, 0, 1]},
}
for _p, _h in _HANDS.items():
    POSES[_p].update(_h)
# <<< hand shapes


def _ch(stance, name):
    v = STANCES.get(stance, {}).get(name)
    if v is None:
        v = STANCES["stand"][name]
    return _copy(v)


def _copy(v):
    if isinstance(v, str):
        return {v: 1.0}
    if isinstance(v, dict):
        return dict(v)
    return list(v)


def mix(a, b, t):
    """blend two channel values: lists lerp, weight maps (dict channels) cross-fade key by key."""
    if isinstance(a, (dict, str)) or isinstance(b, (dict, str)):
        a, b = _copy(a), _copy(b)
        return {k: a.get(k, 0.0) + (b.get(k, 0.0) - a.get(k, 0.0)) * t for k in set(a) | set(b)}
    return vlerp(a, b, t)


def _env(f, a, b, fin, fout, ease):
    """weight envelope of an overlay active from a..b with fade in/out"""
    if f <= a or f >= b + fout:
        return 0.0
    if f < a + fin:
        return EASE[ease]((f - a) / max(1, fin))
    if f <= b:
        return 1.0
    return 1.0 - EASE["smooth"]((f - b) / max(1, fout))


def _noise(f, seed, freq):
    return math.sin(f * freq + seed) * 0.6 + math.sin(f * freq * 2.31 + seed * 1.7) * 0.4


def pose_at(f, perf):
    """Pure function: the full pose at frame f for a performance spec.

    perf = {
      "stance": [[f, "stand"], [f, "brace"], ...]   # base stance keys (blended over 'blend' frames)
      "blend": 14,
      "poses": [{"pose": "radio_mouth", "from": 840, "to": 900, "in": 8, "out": 10, "ease": "overshoot"}],
      "verbs": [{"verb": "shake_head", "at": 1120, "dur": 30}, ...],
      "breath": 1.0,   # breathing amplitude (2.0 = out of breath)
      "seed": 3
    }
    """
    seed = perf.get("seed", 1)
    keys = perf.get("stance") or [[-10000, "stand"]]
    blend = perf.get("blend", 14)
    # base stance with blends between stance changes
    cur = keys[0][1]
    pose = {c: _ch(cur, c) for c in CHANNELS}
    for (kf, name) in keys[1:]:
        if f >= kf:
            t = EASE[perf.get("stanceEase", "heavy")]((f - kf) / max(1, blend))
            nxt = {c: _ch(name, c) for c in CHANNELS}
            pose = {c: mix(pose[c], nxt[c], t) for c in CHANNELS}
    # timed pose overlays, in order (later wins while active)
    for p in perf.get("poses", []):
        d = POSES[p["pose"]] if isinstance(p.get("pose"), str) else p["pose"]
        w = _env(f, p["from"], p["to"], p.get("in", 8), p.get("out", 10), p.get("ease", "smooth"))
        if w <= 0:
            continue
        d = dict(d)
        for s in "LR":   # a pose that moves a hand frees it from the stance's anchor / palm orientation
            if "hand" + s in d:
                d.setdefault("anchor" + s, {})
                d.setdefault("palm" + s, [-1, 0.15, 0] if s == "L" else [1, 0.15, 0])   # neutral forearm: palm in
                d.setdefault("fing" + s, [0, 0, 0])
            if "anchor" + s in d and "hand" + s not in d and "handShape" + s not in d:
                d.setdefault("handShape" + s, "relaxed")
        for c, v in d.items():
            if c in pose:
                pose[c] = mix(pose[c], v, w)
    # per-shot hand overrides: [{"hand": "R", "shape": ..., "anchor": {...}, "from", "to", "in", "out"}]
    for h in perf.get("hands", []):
        w = _env(f, h.get("from", -10 ** 6), h.get("to", 10 ** 6), h.get("in", 6), h.get("out", 6), h.get("ease", "smooth"))
        if w <= 0:
            continue
        s = h.get("hand", "R")
        for key, ch in (("shape", "handShape"), ("anchor", "anchor"), ("palm", "palm"), ("fing", "fing")):
            if key in h:
                pose[ch + s] = mix(pose[ch + s], h[key], w)
    # procedural verbs (additive)
    for v in perf.get("verbs", []):
        _verb(f, v, pose)
    # breathing + micro-motion so he is never a statue
    br = perf.get("breath", 1.0)
    ph = f / 30.0 * 2 * math.pi * (0.28 * (1 + 0.6 * (br - 1)))
    pose["chest"][0] += -1.2 * br * math.sin(ph)
    pose["hips"][2] += 0.004 * br * math.sin(ph)
    for h in ("handL", "handR"):
        pose[h][2] += 0.005 * br * math.sin(ph + 0.6)
    pose["head"][0] += 1.0 * _noise(f, seed, 0.031)
    pose["head"][1] += 1.6 * _noise(f, seed + 4, 0.023)
    pose["hips"][0] += 0.008 * _noise(f, seed + 9, 0.017)   # slow weight shift
    pose["hipsRot"][2] += 1.2 * _noise(f, seed + 9, 0.017)
    return pose


def _verb(f, v, pose):
    at, dur = v["at"], v.get("dur", 24)
    u = (f - at) / max(1, dur)
    if u < 0 or u > 1.0:
        return
    k = v.get("amount", 1.0)
    env = math.sin(math.pi * u)  # 0 -> 1 -> 0
    name = v["verb"]
    if name == "shake_head":   # 3 decaying swings
        pose["head"][1] += k * 22 * math.sin(u * 2 * math.pi * 3) * (1 - u)
    elif name == "nod":
        pose["head"][0] += k * 14 * math.sin(u * 2 * math.pi * 2) * (1 - u)
    elif name == "flinch":     # startle: snap back + shoulders up, decays
        s = math.exp(-u * 5) * (1 - math.exp(-u * 40))
        pose["chest"][0] -= k * 16 * s
        pose["head"][0] -= k * 14 * s
        pose["hips"][1] += k * 0.05 * s
        for h, sx in (("handL", 1), ("handR", -1)):
            pose[h][0] += sx * 0.10 * k * s
            pose[h][2] += 0.22 * k * s
            pose[h][1] -= 0.10 * k * s
    elif name == "sneeze":     # in-in-in ... CHOO (forward jerk at 70%)
        if u < 0.7:
            q = u / 0.7
            pose["chest"][0] -= k * 10 * q * q
            pose["head"][0] -= k * 18 * q * q
        else:
            q = (u - 0.7) / 0.3
            s = math.exp(-q * 6)
            pose["chest"][0] += k * 26 * s - k * 10 * (1 - q)
            pose["head"][0] += k * 34 * s - k * 18 * (1 - q)
            pose["hips"][1] += k * 0.05 * s
    elif name == "press":      # small push forward of the right hand (pressing a button/switch)
        pose["handR"][1] -= k * 0.035 * env
    elif name == "press_twice":
        pose["handR"][1] -= k * 0.035 * abs(math.sin(u * 2 * math.pi))
    elif name == "shout":      # whole body drives into the word
        s = math.sin(math.pi * min(1, u * 2)) if u < 0.5 else math.exp(-(u - 0.5) * 6)
        pose["chest"][0] += k * 8 * s
        pose["head"][0] -= k * 10 * s
        pose["hips"][2] -= k * 0.02 * s
    elif name == "breathe_hard":
        ph = (f - at) / 30.0 * 2 * math.pi * 0.9
        pose["chest"][0] += k * 3.5 * math.sin(ph)
        pose["head"][0] += k * 2.0 * math.sin(ph + 0.4)
        pose["handL"][2] += k * 0.012 * math.sin(ph)
        pose["handR"][2] += k * 0.012 * math.sin(ph)
    elif name == "step_back":  # two steps backwards, hips follow
        d = k * 0.35
        t1 = EASE["smooth"](min(1, u * 2))
        t2 = EASE["smooth"](max(0, u * 2 - 1))
        lift1 = math.sin(math.pi * min(1, u * 2)) * 0.07
        lift2 = math.sin(math.pi * max(0, min(1, u * 2 - 1))) * 0.07
        pose["footR"][1] += d * t1
        pose["footR"][2] += lift1
        pose["footL"][1] += d * t2
        pose["footL"][2] += lift2
        pose["hips"][1] += d * EASE["smooth"](u)
        pose["hipsRot"][2] += 4 * (lift1 - lift2) / 0.07
    elif name == "lurch":      # thrown sideways by the deck (amount sign = direction)
        s = math.exp(-u * 4) * math.sin(u * math.pi * 3)
        pose["hips"][0] += k * 0.10 * s
        pose["hipsRot"][2] += k * 8 * s
        pose["chest"][2] -= k * 10 * s
        pose["head"][2] -= k * 8 * s


# ---------------------------------------------------------------- rig + bake
def _find(arm, *names):
    low = {b.name.lower(): b for b in arm.pose.bones}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None



def fix_bone_lengths(arm):
    """Meshy exports bones with tails ~35 m away and unconnected joints, which makes 2-bone IK
    degenerate (limbs only aim, never bend). Re-tail each limb bone onto its child's head."""
    chains = [("LeftArm", "LeftForeArm"), ("LeftForeArm", "LeftHand"), ("RightArm", "RightForeArm"), ("RightForeArm", "RightHand"),
              ("LeftUpLeg", "LeftLeg"), ("LeftLeg", "LeftFoot"), ("RightUpLeg", "RightLeg"), ("RightLeg", "RightFoot"),
              ("LeftFoot", "LeftToeBase"), ("RightFoot", "RightToeBase"), ("LeftShoulder", "LeftArm"), ("RightShoulder", "RightArm"),
              ("Hips", "Spine02"), ("Spine02", "Spine01"), ("Spine01", "Spine"), ("Spine", "neck"), ("neck", "Head"), ("Head", "head_end")]
    prev = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    low = {b.name.lower(): b for b in eb}
    for a, c in chains:
        A, C = low.get(a.lower()), low.get(c.lower())
        if A and C and (C.head - A.head).length > 1e-4:
            A.tail = C.head.copy()
    for end, ref in (("LeftHand", "LeftForeArm"), ("RightHand", "RightForeArm"), ("LeftToeBase", "LeftFoot"), ("RightToeBase", "RightFoot"), ("head_end", "Head")):
        E, R = low.get(end.lower()), low.get(ref.lower())
        if E and R:
            d = (E.head - R.head).normalized()
            E.tail = E.head + d * (R.length * 0.35)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.objects.active = prev

class Puppet:
    """Control rig on an imported Meshy armature. Call before the holder transform is applied
    (char-local == the imported world space)."""

    def __init__(self, arm, holder):
        self.arm, self.holder = arm, holder
        fix_bone_lengths(arm)
        bpy.context.view_layer.update()
        self.A = holder.matrix_world.inverted() @ arm.matrix_world  # char-local <- armature space (0.01 scale + axis fix)
        self.Ainv = self.A.inverted()
        self.Rq = self.A.to_quaternion()
        self.s = self.A.to_scale()[0]
        b = lambda *n: _find(arm, *n)
        self.hips, self.spines = b("Hips"), [b("Spine02"), b("Spine01"), b("Spine")]
        self.neck, self.head = b("neck"), b("Head")
        self.fore = {"L": b("LeftForeArm"), "R": b("RightForeArm")}
        self.hand = {"L": b("LeftHand"), "R": b("RightHand")}
        self.leg = {"L": b("LeftLeg"), "R": b("RightLeg")}
        for pb in arm.pose.bones:
            pb.rotation_mode = "QUATERNION"
        self.ctl = {}
        for key in ("handL", "handR", "footL", "footR", "poleL", "poleR"):
            e = bpy.data.objects.new(f"ctl_{key}_{arm.name}", None)
            e.empty_display_size = 0.05
            for c in holder.users_collection:
                c.objects.link(e)
            e.parent = holder
            self.ctl[key] = e
        for s in "LR":
            c = self.fore[s].constraints.new("IK")
            c.target, c.pole_target = self.ctl["hand" + s], self.ctl["pole" + s]
            c.chain_count, c.pole_angle = 2, math.radians(-90)
            c = self.leg[s].constraints.new("IK")
            c.target, c.pole_target = self.ctl["foot" + s], self.ctl["poleK" + s] if ("poleK" + s) in self.ctl else None
            c.chain_count = 2
        # knee poles: in front of the knees
        for s, x in (("L", 0.13), ("R", -0.13)):
            e = bpy.data.objects.new(f"ctl_knee{s}_{arm.name}", None)
            for c in holder.users_collection:
                c.objects.link(e)
            e.parent = holder
            e.location = (x, -1.0, 0.5)
            self.ctl["knee" + s] = e
            ik = [c for c in self.leg[s].constraints if c.type == "IK"][0]
            ik.pole_target, ik.pole_angle = e, math.radians(-90)
        self.base_hips = self.hips.bone.head_local.copy() if self.hips else Vector()

    def _rot(self, pb, pitch, yaw, roll):
        """apply a char-space rotation (deg) to a pose bone relative to its rest orientation."""
        qc = Euler((math.radians(-pitch), math.radians(roll), math.radians(yaw)), "YXZ").to_quaternion()
        qa = self.Rq.inverted() @ qc @ self.Rq                    # armature space
        bm = pb.bone.matrix_local.to_quaternion()
        pb.rotation_quaternion = bm.inverted() @ qa @ bm

    def apply(self, pose):
        P = pose
        if self.hips:
            d = Vector(P["hips"])
            da = (self.Rq.inverted() @ d) / self.s                 # armature-space units
            self.hips.location = self.hips.bone.matrix_local.to_3x3().inverted() @ da
            self._rot(self.hips, *P["hipsRot"])
        ch = P["chest"]
        for sp in self.spines:
            if sp:
                self._rot(sp, ch[0] / 3, ch[1] / 3, ch[2] / 3)
        hd = P["head"]
        if self.neck:
            self._rot(self.neck, hd[0] * 0.4, hd[1] * 0.4, hd[2] * 0.4)
        if self.head:
            self._rot(self.head, hd[0] * 0.6, hd[1] * 0.6, hd[2] * 0.6)
        for s in "LR":
            self.ctl["hand" + s].location = P["hand" + s]
            self.ctl["pole" + s].location = P["pole" + s]
            self.ctl["foot" + s].location = P["foot" + s]
            # knee pole: perpendicular to hip->ankle, biased to front+up, so knees bend correctly
            # when standing (knees forward) and sitting (knees up) without a degenerate plane
            hip = Vector(((0.085 if s == "L" else -0.09) + P["hips"][0], P["hips"][1], 0.849 + P["hips"][2]))
            ank = Vector(P["foot" + s])
            d = ank - hip
            v = Vector((0, -1, 1))
            if d.length > 1e-4:
                dn = d.normalized()
                v = v - dn * v.dot(dn)
            if v.length < 1e-4:
                v = Vector((0, -1, 0))
            self.ctl["knee" + s].location = (hip + ank) * 0.5 + v.normalized() * 0.8
            hr = P["handRot" + s]
            if self.hand[s]:
                self._rot(self.hand[s], *hr)

    def bake(self, perf, f0, f1, step=1):
        if not hasattr(self, "lids"):
            body = next((m for m in self.arm.children if m.type == "MESH" and len(m.data.vertices) > 1000), None)
            self.lids = add_eyelids(self.arm, body) if body else []
        bake_lids(self.lids, perf, f0, f1)
        for f in range(int(f0), int(f1) + 1, step):
            self.apply(pose_at(f, perf))
            for pb in [self.hips, *self.spines, self.neck, self.head, self.hand["L"], self.hand["R"]]:
                if pb:
                    pb.keyframe_insert("rotation_quaternion", frame=f)
            if self.hips:
                self.hips.keyframe_insert("location", frame=f)
            for e in self.ctl.values():
                e.keyframe_insert("location", frame=f)


# ---------------------------------------------------------------- face: cartoon eyelids
# The generated hero has its eyes painted on a sparse face, so the face can't deform. Instead each eye gets a
# real eyelid: a small skin-coloured patch hugging the face (shrinkwrap), with a dark lash line at its edge,
# hanging from the top of the eye and riding the Head bone. Its height = how closed the eye is.

def _eye_centres(me):
    import numpy as np
    mat = me.data.materials[0]
    img = next((n.image for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.outputs[0].links
                and n.outputs[0].links[0].to_socket.name == "Base Color"), None)
    if img is None:
        return None, None
    W, H = img.size
    px = np.empty(W * H * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(H, W, 4)
    uv = me.data.uv_layers.active.data
    zs = [v.co.z for v in me.data.vertices]
    hz = min(zs) + (max(zs) - min(zs)) * 0.80
    seen, pts, cols = set(), {"L": [], "R": []}, {}
    for li, lp in enumerate(me.data.loops):
        vi = lp.vertex_index
        if vi in seen:
            continue
        seen.add(vi)
        co = me.data.vertices[vi].co
        u, v = uv[li].uv
        c = px[min(H - 1, int(v * H)), min(W - 1, int(u * W)), :3]
        cols[vi] = c
        if co.z < hz:
            continue
        if c.mean() > 0.75 and (c.max() - c.min()) < 0.12:
            pts["L" if co.x > 0 else "R"].append(co.copy())
    out = {s_: sum(p, Vector()) / len(p) for s_, p in pts.items() if len(p) >= 6}
    if len(out) != 2:
        return None, None
    # skin tone: median colour of vertices just below the eyes (cheek)
    span = abs(out["L"].x - out["R"].x)
    cheek = []
    for vi, c in cols.items():
        co = me.data.vertices[vi].co
        for e in out.values():
            d = co - e
            if abs(d.x) < span * 0.3 and -span * 0.75 < d.z < -span * 0.35 and d.y < span * 0.2:
                cheek.append(c)
    skin = tuple(float(x) for x in np.median(np.array(cheek), axis=0)) if cheek else (0.75, 0.55, 0.42)
    return out, skin


def add_eyelids(arm, me):
    """Build the two eyelids; returns their objects (origin at the top of the eye; scale.z = closure)."""
    eyes, skin = _eye_centres(me)
    if not eyes:
        return []
    head = next((b for b in arm.pose.bones if b.name.lower() == "head"), None)
    mw = me.matrix_world
    span_w = (mw @ eyes["L"] - mw @ eyes["R"]).length
    ew, eh = span_w * 0.62, span_w * 0.50          # lid patch size (world)
    skin_m = bpy.data.materials.new("eyelid_skin")
    skin_m.use_nodes = True
    bs = skin_m.node_tree.nodes["Principled BSDF"]
    bs.inputs["Base Color"].default_value = (*[c * 0.92 for c in skin], 1)
    bs.inputs["Roughness"].default_value = 0.6
    bs.inputs["Subsurface Weight"].default_value = 0.15
    lash_m = bpy.data.materials.new("eyelid_lash")
    lash_m.use_nodes = True
    lash_m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.03, 0.018, 0.012, 1)
    lash_m.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.7
    lids = []
    for side, c in eyes.items():
        cw = mw @ c
        bpy.ops.mesh.primitive_grid_add(x_subdivisions=12, y_subdivisions=10, size=1)
        o = bpy.context.object
        o.name = f"eyelid_{side}_{arm.name}"
        # grid in XY -> stand it up facing -Y, origin at its TOP edge
        for v in o.data.vertices:
            x, y = v.co.x, v.co.y
            v.co = Vector((x * ew, 0.0, (y - 0.5) * eh))
        o.data.materials.append(skin_m)
        o.data.materials.append(lash_m)
        for poly in o.data.polygons:   # bottom row = lash line
            if poly.center.z < -eh * 0.88:
                poly.material_index = 1
            poly.use_smooth = True
        top = cw + Vector((0, -0.03, eh * 0.52))
        o.location = top
        sw = o.modifiers.new("hug", "SHRINKWRAP")
        sw.target, sw.wrap_method, sw.wrap_mode, sw.offset = me, "NEAREST_SURFACEPOINT", "OUTSIDE_SURFACE", 0.0012
        if head:
            bpy.context.view_layer.update()
            mwo = o.matrix_world.copy()
            o.parent, o.parent_type, o.parent_bone = arm, "BONE", head.name
            bpy.context.view_layer.update()
            o.matrix_world = mwo
        o.scale.z = 0.001
        lids.append(o)
    return lids


def bake_lids(lids, perf, f0, f1):
    if not lids:
        return
    relax = perf.get("lids", 0.38)             # 0 = wide open (the raw 'crazy' stare), 1 = closed
    seed = perf.get("seed", 1)
    period = 96 + (seed * 37) % 50             # a blink every ~3-5 s
    base_sz = [o.scale.z for o in lids]
    for f in range(int(f0), int(f1) + 1):
        lid = relax
        for p in perf.get("poses", []):
            if p.get("pose") in ("recoil",) and p["from"] <= f <= p["to"]:
                lid = 0.12                      # surprise: eyes open wide
            if p.get("pose") in ("look_down", "tie_bag", "beacon_pull") and p["from"] <= f <= p["to"]:
                lid = max(lid, 0.6)
        for v in perf.get("verbs", []):
            if v["verb"] == "sneeze" and v["at"] + v.get("dur", 24) * 0.6 <= f <= v["at"] + v.get("dur", 24):
                lid = 1.0
        ph = (f + seed * 11) % period
        if ph < 2:
            lid = 1.0
        elif ph < 4:
            lid = max(lid, 0.7)
        for o in lids:
            o.scale.z = max(0.001, lid)
            o.keyframe_insert("scale", index=2, frame=f)
