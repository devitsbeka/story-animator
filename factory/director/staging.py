"""House staging vocabulary for stage 4: hero marks on the yacht, island placements, yacht states, prop
defaults, and the renderer's acting/prop vocabulary (read from cloud/blender/*.py by AST, never imported,
so no bpy is needed). Values mirror episodes/sentinel/plan/build_v2.py.

Yacht-local: +z bow, +x starboard, +y up (metres). Hero rotY: 0 faces the bow.
"""
import ast
import functools
import json
import math

from .paths import ACTING_PY, PROPS_PY, SENTINEL_GEO

HEADING = math.atan2(-300, 900)          # bow points at the island
ISLANDS = {
    "far": {"asset": "island", "x": -900, "z": 2600, "rotY": 0.6, "scale": 0.35},
    "near": {"asset": "island", "x": -300, "z": 900, "rotY": 0.6, "scale": 0.2},
}
ALL_FIRES = [1, 1, 1, 1, 0.9, 1]

MARKS = {
    "HELM": {"local": [0.55, 1.42, -4.30], "rotY": 0.0, "desc": "at the wheel, facing the bow"},
    "SWITCH": {"local": [-0.85, 1.42, -3.78], "rotY": 0.0, "desc": "at the switch panel, port side of the companionway"},
    "RAIL": {"local": [1.45, 1.42, -4.80], "rotY": math.pi / 2, "desc": "starboard rail, facing outboard"},
    "BOW": {"local": [0.0, 1.90, 4.70], "rotY": 0.0, "desc": "foredeck at the bow, facing forward (toward the island)"},
    "COCKPIT": {"local": [0.0, 1.42, -4.60], "rotY": 0.0, "desc": "cockpit centre, facing the bow"},
    "SITMARK": {"local": [-0.55, 1.42, -3.70], "rotY": math.pi, "desc": "sitting spot against the cabin, facing aft"},
    "AFTFACE": {"local": [0.0, 1.42, -4.70], "rotY": math.pi, "desc": "cockpit, facing aft (toward a stern camera)"},
}

# yacht-attached prop placements (build_v2 helm_props / switch panel / bag) and in-hand grips
PROP_DEFAULTS = {
    ("helm", "yacht"): {"local": [0.55, 1.42, -3.72], "rotY": math.pi},
    ("lamp", "yacht"): {"local": [0.95, 2.38, -3.72], "rotY": 0},
    ("switches", "yacht"): {"local": [-0.85, 2.62, -3.35], "rotY": math.pi},
    ("bag", "yacht"): {"local": [0.0, 1.62, -4.18], "rotY": 0},
    ("radio", "handR"): {"local": [0.0, -0.03, 0.0], "rot": [-90, 0, 0]},
    ("beacon", "handR"): {"local": [0.0, -0.02, 0.0], "rot": [-90, 0, 0]},
    ("phone", "handR"): {"local": [0.0, -0.02, 0.0], "rot": [-90, 0, 0]},
}


def rot_y(a, x, z):
    return x * math.cos(a) + z * math.sin(a), -x * math.sin(a) + z * math.cos(a)


@functools.lru_cache(maxsize=1)
def _geo():
    with open(SENTINEL_GEO) as fh:
        return json.load(fh)


def coast_world(isl):
    S = isl["scale"] * 1000
    pts = []
    for x, y in _geo()["coast"]:
        wx, wz = rot_y(isl["rotY"], x * S, y * S)
        pts.append((wx + isl["x"], wz + isl["z"]))
    return pts


def shore_frame(isl, px=0.0, pz=0.0):
    """Nearest shore point s to (px, pz), unit vector u from the yacht toward s, and p = left-perpendicular."""
    s = min(coast_world(isl), key=lambda p: (p[0] - px) ** 2 + (p[1] - pz) ** 2)
    n = math.hypot(s[0] - px, s[1] - pz)
    ux, uz = (s[0] - px) / n, (s[1] - pz) / n
    return s, (ux, uz), (-uz, ux)


def yacht_state(spec, shot_from):
    st = spec["state"]
    lights = spec.get("lights")
    if st == "afloat_lit":
        y = {"x": 0, "z": 0, "heading": HEADING, "lights": [[0, 1]]}
    elif st == "afloat_dark":
        y = {"x": 0, "z": 0, "heading": HEADING, "lights": [[0, 0]]}
    elif st == "aground":
        y = {"x": 0, "z": 0, "heading": HEADING, "lights": [[0, 0]], "pitch": -0.10, "roll": 0.14, "sink": 0.25}
    elif st == "aground_hit":
        h = spec["hit_frame"]
        y = {"x": 0, "z": 0, "heading": HEADING, "lights": [[0, 0]],
             "pitch": [[h - 1, 0], [h + 2, -0.13], [h + 10, -0.09], [h + 20, -0.10]],
             "roll": [[h - 1, 0], [h + 3, 0.19], [h + 12, 0.12], [h + 24, 0.14]],
             "sink": [[h - 1, 0], [h + 2, 0.27], [h + 14, 0.25]]}
    elif st == "tide_lift":
        f0, f1 = shot_from, spec.get("hit_frame", shot_from + 64)
        y = {"x": 0, "z": 0, "heading": HEADING, "lights": [[0, 0]], "pitch": [[f0, -0.10], [f1, 0.0]],
             "roll": [[f0, 0.14], [f1, 0.0]], "sink": [[f0, 0.25], [f1, -0.05]]}
    elif st == "leaving":
        ox, oz = spec["offset"]
        y = {"x": ox, "z": oz, "heading": HEADING + math.pi, "lights": [[0, 0]]}
    elif st == "absent":
        return None
    else:
        raise ValueError(f"unknown yacht state {st}")
    if lights is not None:
        y["lights"] = lights
    return y


# ------------------------------------------------------------------ renderer vocabulary (AST, no bpy)
def _dict_keys(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            if isinstance(node.value, ast.Dict):
                return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    raise KeyError(name)


@functools.lru_cache(maxsize=1)
def vocabulary():
    with open(ACTING_PY) as fh:
        acting = ast.parse(fh.read())
    with open(PROPS_PY) as fh:
        props = ast.parse(fh.read())
    verbs = set()
    for fn in ast.walk(acting):
        if isinstance(fn, ast.FunctionDef) and fn.name == "_verb":
            for node in ast.walk(fn):
                if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "name":
                    for c in node.comparators:
                        if isinstance(c, ast.Constant):
                            verbs.add(c.value)
                        elif isinstance(c, (ast.Tuple, ast.List, ast.Set)):
                            verbs |= {e.value for e in c.elts if isinstance(e, ast.Constant)}
    return {
        "stances": sorted(_dict_keys(acting, "STANCES")),
        "poses": sorted(_dict_keys(acting, "POSES")),
        "verbs": sorted(verbs),
        "props": sorted(_dict_keys(props, "BUILDERS")),
        "marks": sorted(MARKS),
    }
