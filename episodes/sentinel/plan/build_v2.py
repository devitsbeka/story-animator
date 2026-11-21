#!/usr/bin/env python3
"""
Build episodes/sentinel/episode_v2.json from the v2 shot list (plan/shotlist.md).

Everything here is direction-as-code: staging (where the hero stands, what he faces), the camera
(orbits/pushes around a target in yacht-local metres, sampled every 3 frames so Blender reproduces the
eased path exactly), the acting (stance + timed poses + verbs on VO frames) and props (radio, beacon...).
Frames are absolute film frames at 30 fps (audio offset already included).
Yacht-local: +z bow, +x starboard, +y up. Hero rotY: 0 faces the bow.
"""
import json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(EP))
base = json.load(open(os.path.join(EP, "episode.json")))
GEO = json.load(open(os.path.join(ROOT, "studio/src/data/sentinel_geo.json")))

# ------------------------------------------------------------------ easing (same curves as the renderer)
def bez(x1, y1, x2, y2):
    def f(x):
        x = min(1.0, max(0.0, x)); t = x
        for _ in range(10):
            cx = 3*x1*t*(1-t)**2 + 3*x2*t*t*(1-t) + t**3 - x
            d = 3*x1*(1-t)**2 + 6*(x2-x1)*t*(1-t) + 3*(1-x2)*t*t
            if abs(d) < 1e-6: break
            t = min(1.0, max(0.0, t - cx/d))
        return 3*y1*t*(1-t)**2 + 3*y2*t*t*(1-t) + t**3
    return f
EASE = {"move": bez(.65, 0, .35, 1), "arrive": bez(.16, 1, .3, 1), "exit": bez(.7, 0, .84, 0), "linear": lambda t: t,
        "crash": lambda t: t ** 3}
L = lambda a, b, t: a + (b - a) * t
r3 = lambda v: [round(x, 4) for x in v]

# ------------------------------------------------------------------ world staging
HEADING = math.atan2(-300, 900)          # bow points at the island
ISL_FAR = {"asset": "island", "x": -900, "z": 2600, "rotY": 0.6, "scale": 0.35}
ISL_NEAR = {"asset": "island", "x": -300, "z": 900, "rotY": 0.6, "scale": 0.2}
FIRES = [1, 1, 1, 1, 0.9, 1]

def rot_y(a, x, z):
    return x * math.cos(a) + z * math.sin(a), -x * math.sin(a) + z * math.cos(a)

def coast_world(isl):
    S = isl["scale"] * 1000
    pts = []
    for x, y in GEO["coast"]:
        wx, wz = rot_y(isl["rotY"], x * S, y * S)
        pts.append((wx + isl["x"], wz + isl["z"]))
    return pts

def nearest_shore(isl, px=0.0, pz=0.0):
    return min(coast_world(isl), key=lambda p: (p[0] - px) ** 2 + (p[1] - pz) ** 2)

def to_world(local, x=0.0, z=0.0, h=HEADING):
    wx, wz = rot_y(h, local[0], local[2])
    return [wx + x, local[1], wz + z]

# hero marks on the yacht (yacht-local)
HELM = {"local": [0.55, 1.42, -4.30], "rotY": 0.0}
SWITCH = {"local": [-0.85, 1.42, -3.78], "rotY": 0.0}
RAIL = {"local": [1.45, 1.42, -4.80], "rotY": math.pi / 2}
BOW = {"local": [0.0, 1.90, 4.70], "rotY": 0.0}
COCKPIT = {"local": [0.0, 1.42, -4.60], "rotY": 0.0}
SITMARK = {"local": [-0.55, 1.42, -3.70], "rotY": math.pi}
AFTFACE = {"local": [0.0, 1.42, -4.70], "rotY": math.pi}   # facing aft (toward a camera at the stern)

# ------------------------------------------------------------------ camera helpers
def orbit(mark, f0, f1, az, d, h, fov, ease="move", target="chest", aim=(0, 0, 0)):
    """Orbit/push around the hero. az = degrees around him, 0 = in front of his face, +90 = his left.
    d = distance (m), h = camera height above the target, fov = vertical degrees. Each is [start, end]."""
    lx, ly, lz = mark["local"]
    ty = {"chest": 1.30, "face": 1.55, "hands": 1.15, "feet": 0.4, "sit": 0.75}[target] if isinstance(target, str) else target
    T = [lx + aim[0], ly + ty + aim[1], lz + aim[2]]
    keys = []
    f = f0
    while True:
        u = (f - f0) / max(1, f1 - f0); e = EASE[ease](u)
        a = math.radians(L(az[0], az[1], e)) + mark["rotY"]
        dd, hh = L(d[0], d[1], e), L(h[0], h[1], e)
        fv = math.exp(L(math.log(fov[0]), math.log(fov[1]), e))
        # hero front = (sin rotY, cos rotY); +az swings toward his left (+x when facing +z is his RIGHT... use -sin)
        cam = [T[0] + math.sin(a) * dd, T[1] + hh, T[2] + math.cos(a) * dd]
        keys.append({"f": f, "cam": r3(cam), "look": r3(T), "fov": round(fv, 3), "ease": "linear"})
        if f >= f1: break
        f = min(f1, f + 3)
    return {"space": "yacht", "keys": keys}

def path(f0, f1, cams, looks, fovs, ease="move", space="world"):
    """Straight move between two camera positions / look points (world or yacht space)."""
    keys = []
    f = f0
    while True:
        u = (f - f0) / max(1, f1 - f0); e = EASE[ease](u)
        keys.append({"f": f, "cam": r3([L(a, b, e) for a, b in zip(*cams)]), "look": r3([L(a, b, e) for a, b in zip(*looks)]),
                     "fov": round(math.exp(L(math.log(fovs[0]), math.log(fovs[1]), e)), 3), "ease": "linear"})
        if f >= f1: break
        f = min(f1, f + 3)
    return {"space": space, "keys": keys}

# ------------------------------------------------------------------ yacht states
AFLOAT_LIT = {"x": 0, "z": 0, "heading": HEADING, "lights": [[0, 1]]}
AFLOAT_DARK = {"x": 0, "z": 0, "heading": HEADING, "lights": [[0, 0]]}
def aground(f_hit=None):
    if f_hit is None:
        return {"x": 0, "z": 0, "heading": HEADING, "lights": [[0, 0]], "pitch": -0.10, "roll": 0.14, "sink": 0.25}
    return {"x": 0, "z": 0, "heading": HEADING, "lights": [[0, 0]],
            "pitch": [[f_hit - 1, 0], [f_hit + 2, -0.13], [f_hit + 10, -0.09], [f_hit + 20, -0.10]],
            "roll": [[f_hit - 1, 0], [f_hit + 3, 0.19], [f_hit + 12, 0.12], [f_hit + 24, 0.14]],
            "sink": [[f_hit - 1, 0], [f_hit + 2, 0.27], [f_hit + 14, 0.25]]}

def hero(mark, perf):
    return [{"asset": "hero", "space": "yacht", "local": mark["local"], "rotY": round(mark["rotY"], 5), "height": 1.8, "perf": perf, "tracks": [{"clip": "none", "from": 0}]}]

def hp(f0, stance="stand", poses=(), verbs=(), breath=1.0, seed=1, stances=None):
    st = stances or [[-10000, stance]]
    return {"stance": st, "poses": list(poses), "verbs": list(verbs), "breath": breath, "seed": seed, "blend": 12}

def P(pose, a, b, i=8, o=10, ease="smooth"):
    return {"pose": pose, "from": a, "to": b, "in": i, "out": o, "ease": ease}

def V(verb, at, dur=24, amount=1.0):
    return {"verb": verb, "at": at, "dur": dur, "amount": amount}

def helm_props(lamp_keys=None, gauges=None):
    p = [{"prop": "helm", "attach": "yacht", "local": [0.55, 1.42, -3.72], "rotY": math.pi}]
    if gauges is not None:
        p[0]["light"] = gauges
    p.append({"prop": "lamp", "attach": "yacht", "local": [0.95, 2.38, -3.72], "rotY": 0, "light": lamp_keys or [[0, 1]]})
    return p

SHOTS = []
def shot(id, title, f0, f1, camera, yacht=None, island=ISL_NEAR, actors=None, props=None, fires=None, env=None, shakes=None, handheld=0.15, drift=0.08, key=None):
    camera["handheld"] = handheld
    camera["drift"] = drift
    if shakes: camera["shakes"] = shakes
    s = {"id": id, "title": title, "from": f0, "to": f1, "keyFrame": key or (f0 + f1) // 2, "camera": camera,
         "yacht": yacht or AFLOAT_DARK, "island": island}
    if actors: s["actors"] = actors
    if props: s["props"] = props
    if fires: s["fires"] = fires
    if env: s["env"] = env
    SHOTS.append(s)

# =================================================================== ACT 1
# 1 EWS crane down: alone at sea
shot("A01", "Alone on a yacht", 0, 75,
     path(0, 75, ([0, 0, 0], [0, 0, 0]), ([0, 0, 0], [0, 0, 0]), (34, 30), "arrive", space="yacht") | {}, yacht=AFLOAT_LIT, island=ISL_FAR,
     actors=hero(HELM, hp(0, "helm", seed=2)), props=helm_props(), key=60)
SHOTS[-1]["camera"] = orbit(HELM, 0, 75, [150, 160], [42, 26], [30, 9], [30, 30], "arrive")
# 2 MS push in from the stern quarter at the helm
shot("A02", "Middle of the night", 75, 118, orbit(HELM, 75, 118, [200, 192], [3.6, 2.8], [0.5, 0.35], [32, 30], "move"),
     yacht=AFLOAT_LIT, island=ISL_FAR, actors=hero(HELM, hp(75, "helm", poses=[P("look_down", 92, 108, 10, 10)], seed=2)), props=helm_props(), key=100)
# 3 crash zoom: engine dies (startle, look back)
shot("A03", "Engine died", 118, 158, orbit(HELM, 118, 158, [-25, -20], [2.6, 1.3], [0.25, 0.2], [30, 22], "crash", target="face"),
     yacht={**AFLOAT_LIT, "lights": [[118, 1], [128, 1], [130, 0.3], [133, 1], [140, 1], [142, 0.2], [146, 0.7], [150, 0.15], [158, 0.15]]},
     island=ISL_FAR, actors=hero(HELM, hp(118, "helm", poses=[P("look_back", 132, 158, 6, 6, "snap")], verbs=[V("flinch", 128, 26)], seed=2)),
     props=helm_props([[118, 1], [140, 1], [142, 0.2], [146, 0.7], [150, 0]], [[118, 1], [140, 1], [142, 0], [146, 0.5], [149, 0]]),
     shakes=[{"at": 128, "px": 6, "tau": 1.4}], key=145)
# 4 No lights, no power: flips a dead switch twice, lit only by the moon
shot("A04", "No lights no power", 158, 241, orbit(SWITCH, 158, 241, [-35, -12], [1.7, 1.25], [0.1, 0.05], [28, 26], "move", target="face"),
     yacht=AFLOAT_DARK, island=ISL_FAR,
     actors=hero(SWITCH, hp(158, "stand", poses=[P("press_ahead", 166, 232, 7, 8, "snap")], verbs=[V("press_twice", 178, 26), V("press", 206, 10), V("breathe_hard", 160, 80, 0.8)], breath=1.6, seed=3)),
     props=[{"prop": "switches", "attach": "yacht", "local": [-0.85, 2.62, -3.35], "rotY": math.pi, "light": [[0, 0]]}], key=190)
# 5 current dragging: worried look-around at the rail, camera rises
shot("A05", "Current dragging", 241, 330, orbit(RAIL, 241, 330, [30, 60], [4.0, 14.0], [0.6, 9.0], [30, 34], "move"),
     yacht=AFLOAT_DARK, island=ISL_NEAR,
     actors=hero(RAIL, hp(241, "brace", poses=[P("hold_rail", 241, 330, 1, 1), P("look_left", 252, 280, 10, 12), P("look_right", 288, 322, 10, 10)], seed=4)), key=300)
# 6 overhead: rise to a map view toward the island (map overlay added in Remotion)
shot("A06", "Toward the one island", 330, 404,
     path(330, 404, ([0, 60, -40], [0, 520, 300]), ([0, 0, 0], [0, 0, 420]), (36, 46), "move", space="yacht"),
     yacht=AFLOAT_DARK, island=ISL_NEAR, actors=hero(RAIL, hp(330, "brace", poses=[P("hold_rail", 330, 404, 1, 1)], seed=4)), handheld=0.05, key=380)
# 7 North Sentinel Island! low push over the water toward the island
_s = nearest_shore(ISL_NEAR)
_dx, _dz = _s[0] - 0, _s[1] - 0
_n = math.hypot(_dx, _dz); _ux, _uz = _dx / _n, _dz / _n
shot("A07", "North Sentinel Island", 404, 455,
     path(404, 455, ([_s[0] - _ux * 260, 6, _s[1] - _uz * 260], [_s[0] - _ux * 170, 4, _s[1] - _uz * 170]),
          ([_s[0] + _ux * 300, 30, _s[1] + _uz * 300], [_s[0] + _ux * 300, 26, _s[1] + _uz * 300]), (38, 34), "arrive"),
     yacht=AFLOAT_DARK, island=ISL_NEAR, handheld=0.1, key=440)
# 8 refused contact: lateral glide low along the beach and tree line (no people)
_px, _pz = -_uz, _ux
shot("A08", "Refused contact", 455, 560,
     path(455, 560, ([_s[0] - _ux * 70 - _px * 40, 3.5, _s[1] - _uz * 70 - _pz * 40], [_s[0] - _ux * 70 + _px * 40, 3.5, _s[1] - _uz * 70 + _pz * 40]),
          ([_s[0] - _px * 20, 12, _s[1] - _pz * 20], [_s[0] + _px * 60, 12, _s[1] + _pz * 60]), (30, 30), "linear"),
     yacht=AFLOAT_DARK, island=ISL_NEAR, handheld=0.08, key=520)
# 9 they defend that. Hard: fires light one by one, reverse on the hero stepping back from the rail
shot("A09", "Defend it hard", 560, 668, orbit(BOW, 560, 668, [20, 8], [3.2, 1.8], [0.3, 0.15], [30, 26], "move", target="face"),
     yacht=AFLOAT_DARK, island=ISL_NEAR, fires=[[560, [0, 0, 0, 0, 0, 0]], [598, [1, 0, 0, 0, 0, 0]], [612, [1, 1, 0, 0, 0, 0]], [628, [1, 1, 1, 0, 0, 0]], [645, FIRES]],
     actors=hero(BOW, hp(560, "stand", poses=[P("rail_ahead", 560, 630, 1, 14), P("recoil", 636, 668, 6, 8, "snap")], verbs=[V("step_back", 636, 30, 0.8), V("breathe_hard", 640, 40)], seed=5)), key=650)

# =================================================================== ACT 2
# 10 CRUNCH: low waterline angle, the hull slams onto coral, he is knocked down
HIT = 690
shot("B10", "Crunch", 668, 723, orbit(COCKPIT, 668, 723, [60, 75], [9.0, 7.5], [-1.9, -1.6], [30, 28], "move", target="chest"),
     yacht=aground(HIT), island=ISL_NEAR, fires=[[668, FIRES]],
     actors=hero(COCKPIT, hp(668, stances=[[-10000, "stand"], [HIT, "down"]], verbs=[V("lurch", HIT, 24, 1.0)], seed=6)),
     shakes=[{"at": HIT, "px": 14, "tau": 2.2}], handheld=0.25, key=700)
# 11 You hit the reef. You're stuck: tilted boat, he gets up holding the rail
shot("B11", "Stuck on the reef", 723, 786, orbit(COCKPIT, 723, 786, [40, 15], [4.0, 3.2], [0.4, 0.3], [30, 28], "move"),
     yacht=aground(), island=ISL_NEAR, fires=[[723, FIRES]],
     actors=hero(COCKPIT, hp(723, stances=[[-10000, "down"], [735, "brace"]], poses=[P("rail_ahead", 750, 786, 10, 8)], verbs=[V("breathe_hard", 723, 63)], breath=1.8, seed=6)), key=770)
# 12 So what do you actually do? looks straight into the lens
shot("B12", "What do you do", 786, 834, orbit(AFTFACE, 786, 834, [0, 0], [1.6, 0.95], [0.05, 0.0], [30, 26], "arrive", target="face"),
     yacht=aground(), island=ISL_NEAR, fires=[[786, FIRES]],
     actors=hero(AFTFACE, hp(786, "brace", verbs=[V("breathe_hard", 786, 48)], breath=1.8, seed=7)), key=815)

# =================================================================== ACT 3
RADIO_IN_HAND = {"prop": "radio", "attach": "handR", "local": [0.0, -0.03, 0.0], "rot": [-90, 0, 0]}
# 13 Step one. MAYDAY!
shot("C13", "Mayday", 834, 877, orbit(AFTFACE, 834, 877, [-35, -25], [2.0, 1.2], [0.1, 0.05], [30, 26], "arrive", target="face"),
     yacht=aground(), island=ISL_NEAR, fires=[[834, FIRES]],
     actors=hero(AFTFACE, hp(834, "brace", poses=[P("radio_shout", 846, 877, 6, 6, "overshoot")], verbs=[V("shout", 862, 18)], breath=1.5, seed=8)),
     props=[RADIO_IN_HAND | {"show": [[0, 0], [845, 0], [846, 1]]}], key=868)
# 14 Insert: CH 16 on the radio display
shot("C14", "Channel 16", 877, 940, orbit(AFTFACE, 877, 940, [-10, -4], [0.55, 0.38], [0.0, 0.0], [24, 22], "move", target=1.48, aim=(-0.06, 0, 0.18)),
     yacht=aground(), island=ISL_NEAR,
     actors=hero(AFTFACE, hp(877, "brace", poses=[P("radio_mouth", 870, 940, 1, 1)], seed=8)),
     props=[RADIO_IN_HAND], handheld=0.06, key=910)
# 15 fire off your emergency beacon: pulls the tab, strobe starts
BEACON_IN_HAND = {"prop": "beacon", "attach": "handR", "local": [0.0, -0.02, 0.0], "rot": [-90, 0, 0], "strobe": 962}
shot("C15", "Emergency beacon", 940, 1010, orbit(AFTFACE, 940, 1010, [30, 20], [2.2, 1.7], [-0.5, -0.4], [30, 28], "move", target="chest"),
     yacht=aground(), island=ISL_NEAR, fires=[[940, FIRES]],
     actors=hero(AFTFACE, hp(940, "brace", poses=[P("beacon_pull", 944, 962, 6, 8), P("beacon_raise", 966, 1010, 8, 8, "overshoot")], seed=9)),
     props=[BEACON_IN_HAND], key=985)
# 16 Coast Guard patrols: big crane up and back, the beacon pulsing small in frame
shot("C16", "Coast Guard patrols", 1010, 1086, orbit(AFTFACE, 1010, 1086, [20, 40], [3.0, 40.0], [0.5, 22.0], [30, 36], "move"),
     yacht=aground(), island=ISL_NEAR, fires=[[1010, FIRES]],
     actors=hero(AFTFACE, hp(1010, "brace", poses=[P("beacon_raise", 1000, 1086, 1, 1)], seed=9)),
     props=[BEACON_IN_HAND | {"strobe": 1000}], handheld=0.08, key=1060)
# 17 Step two. Do NOT go ashore: over the shoulder at the bow toward the beach, head shake
shot("C17", "Do not go ashore", 1086, 1168, orbit(BOW, 1086, 1168, [170, 185], [2.4, 1.9], [0.35, 0.3], [32, 30], "move", target="face"),
     yacht=aground(), island=ISL_NEAR, fires=[[1086, FIRES]],
     actors=hero(BOW, hp(1086, "stand", poses=[P("rail_ahead", 1086, 1130, 1, 10)], verbs=[V("shake_head", 1128, 34)], seed=10)), key=1140)
# 18 Not for a photo, not to say hi: phone up then away; a wave that dies
shot("C18", "Not for a photo", 1168, 1236, orbit(BOW, 1168, 1236, [-20, -8], [2.2, 1.8], [0.15, 0.1], [30, 28], "move", target="chest"),
     yacht=aground(), island=ISL_NEAR, fires=[[1168, FIRES]],
     actors=hero(BOW, hp(1168, "stand", poses=[P("phone_up", 1170, 1196, 8, 8), P("wave", 1210, 1226, 6, 10)], verbs=[V("shake_head", 1196, 18, 0.6)], seed=10)),
     props=[{"prop": "phone", "attach": "handR", "local": [0.0, -0.02, 0.0], "rot": [-90, 0, 0], "show": [[0, 0], [1169, 0], [1170, 1], [1204, 1], [1205, 0]]}], key=1185)
# 19 no immunity to our germs: side track, hand over mouth
shot("C19", "No immunity", 1236, 1314, orbit(BOW, 1236, 1314, [80, 65], [3.4, 3.0], [0.2, 0.2], [30, 30], "linear", target="chest"),
     yacht=aground(), island=ISL_NEAR, fires=[[1236, FIRES]],
     actors=hero(BOW, hp(1236, "stand", poses=[P("cover_mouth", 1262, 1300, 10, 10)], seed=11)), key=1280)
# 20 a common cold could be deadly: the sneeze
shot("C20", "Common cold", 1314, 1389, orbit(BOW, 1314, 1389, [-15, -30], [1.8, 2.6], [0.1, 0.4], [28, 32], "move", target="face"),
     yacht=aground(), island=ISL_NEAR, fires=[[1314, FIRES]],
     actors=hero(BOW, hp(1314, "stand", poses=[P("cover_mouth", 1350, 1372, 4, 10, "snap")], verbs=[V("sneeze", 1326, 40, 1.2)], seed=11)), key=1352)
# 21 Step three. Stay with your boat: sits down against the cabin, holding on
shot("C21", "Stay with your boat", 1389, 1461, orbit(SITMARK, 1389, 1461, [20, 0], [3.0, 2.3], [0.6, 0.2], [30, 28], "move", target="sit"),
     yacht=aground(), island=ISL_NEAR, fires=[[1389, FIRES]],
     actors=hero(SITMARK, hp(1389, stances=[[-10000, "stand"], [1405, "sit_deck"]], seed=12)), key=1450)
# 22 this has happened before: crane up away from the yacht
shot("C22", "Happened before", 1461, 1523, orbit(SITMARK, 1461, 1523, [0, 30], [2.3, 30.0], [0.2, 24.0], [28, 36], "exit", target="sit"),
     yacht=aground(), island=ISL_NEAR, fires=[[1461, FIRES]],
     actors=hero(SITMARK, hp(1461, "sit_deck", seed=12)), handheld=0.06, key=1500)
# 23-26 Primrose 1981: separate set (cargo ship, storm, helicopter): placeholder framing on the island until the set is built
for sid, title, a, b in (("D23", "Primrose 1981", 1523, 1650), ("D24", "Armed islanders", 1650, 1760), ("D25", "Waited for days", 1760, 1840), ("D26", "Helicopters", 1840, 1931)):
    shot(sid, title + " (set pending)", a, b, path(a, b, ([_s[0] - _ux * 400, 40, _s[1] - _uz * 400], [_s[0] - _ux * 330, 30, _s[1] - _uz * 330]),
                                                  ([_s[0], 10, _s[1]], [_s[0], 10, _s[1]]), (34, 32), "move"),
         yacht=aground(), island=ISL_NEAR, fires=[[a, FIRES]], key=(a + b) // 2)
# 27 Step four. Kill the lights: switches off the deck lamp, frame goes dark
shot("C27", "Kill the lights", 1931, 1995, orbit(HELM, 1931, 1995, [-30, -15], [1.6, 1.2], [0.05, 0.0], [28, 26], "move", target="face"),
     yacht=aground(), island=ISL_NEAR, fires=[[1931, FIRES]],
     actors=hero(HELM, hp(1931, "stand", poses=[P("press_ahead", 1950, 1972, 8, 10, "snap")], verbs=[V("press", 1962, 10)], seed=13)),
     props=helm_props([[0, 1], [1965, 1], [1967, 0]]), key=1958)
# 28 Stay quiet: finger to lips
shot("C28", "Stay quiet", 1995, 2029, orbit(HELM, 1995, 2029, [-8, -2], [1.3, 0.95], [0.02, 0.0], [26, 24], "arrive", target="face"),
     yacht=aground(), island=ISL_NEAR, fires=[[1995, FIRES]],
     actors=hero(HELM, hp(1995, "stand", poses=[P("shush", 1998, 2029, 6, 1, "overshoot")], seed=13)), props=helm_props([[0, 0]]), key=2015)
# 29 Leave nothing behind: ties a trash bag
shot("C29", "Leave nothing", 2029, 2076, orbit(COCKPIT, 2029, 2076, [30, 15], [2.0, 1.6], [1.2, 1.4], [30, 28], "move", target="hands"),
     yacht=aground(), island=ISL_NEAR, fires=[[2029, FIRES]],
     actors=hero(COCKPIT, hp(2029, "stand", poses=[P("tie_bag", 2032, 2076, 8, 1)], seed=14)),
     props=[{"prop": "bag", "attach": "yacht", "local": [0.0, 1.62, -4.18], "rotY": 0}], key=2055)

# =================================================================== ACT 4
# 30 tide lifts your boat: low waterline, the boat levels
LIFT = {"x": 0, "z": 0, "heading": HEADING, "lights": [[0, 0]], "pitch": [[2076, -0.10], [2140, 0.0]], "roll": [[2076, 0.14], [2140, 0.0]], "sink": [[2076, 0.25], [2140, -0.05]]}
shot("E30", "Tide lifts", 2076, 2140, orbit(COCKPIT, 2076, 2140, [70, 80], [8.0, 7.0], [-1.7, -1.0], [30, 30], "move"),
     yacht=LIFT, island=ISL_NEAR, fires=[[2076, FIRES]], actors=hero(COCKPIT, hp(2076, "brace", poses=[P("look_down", 2090, 2140, 10, 8)], seed=15)), key=2130)
# 31 drift out past the reef and get gone: aerial pull-back, dawn starts
shot("E31", "Get gone", 2140, 2200, orbit(HELM, 2140, 2200, [160, 175], [6.0, 45.0], [2.0, 26.0], [32, 36], "exit"),
     yacht={**AFLOAT_DARK}, island=ISL_NEAR, env={"dawn": 0.35}, actors=hero(HELM, hp(2140, "helm", seed=16)), props=helm_props([[0, 0]]), key=2190)
# 32-33 never be there at all: dawn, the island small and centred, slow drift and hold
for sid, title, a, b in (("E32", "Smartest way to survive", 2200, 2340), ("E33", "Never be there at all", 2340, 2416)):
    shot(sid, title, a, b, path(a, b, ([ _s[0] - _ux * 2400, 60, _s[1] - _uz * 2400], [_s[0] - _ux * 2250, 55, _s[1] - _uz * 2250]),
                                  ([ISL_NEAR["x"], 20, ISL_NEAR["z"]], [ISL_NEAR["x"], 20, ISL_NEAR["z"]]), (24, 23), "linear"),
         yacht={"x": -_ux * 600, "z": -_uz * 600, "heading": HEADING + math.pi, "lights": [[0, 0]]}, island=ISL_NEAR,
         env={"dawn": 0.75, "moonDir": [0.1, 0.06, 1]}, handheld=0.04, key=(a + b) // 2)

ep = dict(base)
ep["version"] = base.get("version", 1)
ep["shots"] = SHOTS
ep["source"] = {"builder": "episodes/sentinel/plan/build_v2.py", "shotlist": "episodes/sentinel/plan/shotlist.md"}
out = os.path.join(EP, "episode_v2.json")
json.dump(ep, open(out, "w"), indent=1)
print(f"wrote {out}: {len(SHOTS)} shots")
