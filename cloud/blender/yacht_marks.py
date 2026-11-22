"""
yacht_marks.py - episode attachment points on the hero yacht (pure data, no bpy; importable by episode builders).

Spec space, yacht-local (three.js axes: x starboard, y up, z bow; metres). rotY 0 = facing the bow.

MARKS_V1  the crude yacht.glb layout (what episodes v2..v5 were authored against)
MARKS_V2  cloud/blender/yacht_v2.py. Same cockpit sole (1.42) / cabin aft wall (z -3.33) / helm console, so HELM,
          SWITCH, RAIL, COCKPIT and BOW are unchanged; SITMARK moves from the cabin wall onto the aft dinette bench
          (sit facing forward, feet planted ahead of the seat front). BENCH describes the seat for sit stances.

remap(mark_v1_local, rotY) -> (name, new_local, new_rotY, dyaw) for a v1 mark position (None if not a mark).
"""
import math

SOLE = 1.42

MARKS_V1 = {
    "HELM": {"local": [0.55, SOLE, -4.30], "rotY": 0.0},
    "SWITCH": {"local": [-0.85, SOLE, -3.78], "rotY": 0.0},
    "RAIL": {"local": [1.45, SOLE, -4.80], "rotY": math.pi / 2},
    "BOW": {"local": [0.0, 1.90, 4.70], "rotY": 0.0},
    "COCKPIT": {"local": [0.0, SOLE, -4.60], "rotY": 0.0},
    "SITMARK": {"local": [-0.55, SOLE, -3.70], "rotY": math.pi},
}

MARKS_V2 = dict(MARKS_V1)
MARKS_V2.update({
    # on the aft dinette bench, facing forward; the actor origin is the feet, the pelvis sits ~0.50 m behind it
    "SITMARK": {"local": [-0.95, SOLE, -5.95], "rotY": 0.0},
    "BENCH": {"seat_y": SOLE + 0.45, "front_z": -6.30, "depth": 0.48, "x": [-1.30, 1.30]},
    "SWITCH_PANEL": {"local": [-0.85, 2.62, -3.35], "rotY": math.pi},
    "HELM_CONSOLE": {"local": [0.55, SOLE, -3.72], "rotY": math.pi},
})

# stance swaps when a shot moves to the v2 layout (sitting on the bench instead of the deck against the wall)
STANCE_V2 = {"SITMARK": {"sit_deck": "sit_bench"}}
# camera carry for those shots: the pelvis is on a 0.45 m seat, not the deck (head ~0.4 m higher), and the
# eye-level view needs a little more distance than the old top-down one to keep the cap in frame
CAM_DY_V2 = {"SITMARK": 0.40}
CAM_SCALE_V2 = {"SITMARK": 1.25}


def remap(local, rotY, tol=0.06):
    for name, m in MARKS_V1.items():
        if all(abs(a - b) < tol for a, b in zip(local, m["local"])) and abs(((rotY - m["rotY"]) + math.pi) % (2 * math.pi) - math.pi) < 0.05:
            n = MARKS_V2[name]
            if n["local"] == m["local"] and n["rotY"] == m["rotY"]:
                return None
            return name, list(n["local"]), n["rotY"], n["rotY"] - m["rotY"]
    return None


def move_point(p, old_local, new_local, dyaw, dy=0.0, scale=1.0):
    """rigidly carry a yacht-space point from the old mark frame to the new one (yaw about the mark), + dy;
    `scale` stretches the horizontal offset from the mark (camera distance)"""
    x, y, z = (p[0] - old_local[0]) * scale, p[1], (p[2] - old_local[2]) * scale
    c, s = math.cos(dyaw), math.sin(dyaw)
    # three.js rotation about +Y: x' = x c + z s, z' = -x s + z c
    xr, zr = x * c + z * s, -x * s + z * c
    return [round(new_local[0] + xr, 4), round(y + (new_local[1] - old_local[1]) + dy, 4), round(new_local[2] + zr, 4)]
