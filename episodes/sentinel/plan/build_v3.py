#!/usr/bin/env python3
"""
Build episodes/sentinel/episode_v3.json: v2's acting and props, re-directed with factory/direction/camera_presets.

What changed vs v2 (driven by factory/direction/shot_validator.py on episode_v2.json):
  - Staging: the island is placed so its FIRE coast faces the yacht (v2 put the six fires 1-1.7 km away on the
    far side of the island: never in frame). The yacht grounds ~130 m off that beach; the bow points at it.
    One island for the whole film (no scale swap); in act 1 the yacht is 600 m further out and drifts in.
  - Lenses: v2 shot everything on ~65-100 mm equivalents (vfov 22-36 deg on 9:16), which hid the world behind
    the hero. v3 uses the PIXAR_RECIPE lens language: 24-35 mm for geography, 50 mm for VO beats, 75 mm only
    on the three emotional close-ups (A09b fear, B12 direct address, C28 shush).
  - Story-first framing: island / beach / fires behind or above the centred hero (high_reveal, over_shoulder,
    push_reveal), C17's OTS really frames the beach, the fires are seen lighting (A09a OTS).
  - Shot language: one camera side per sequence (camera on the hero's left), eyes at 0.40 on MCU/CU,
    a re-establishing wide on the return from the Primrose flashback, every camera move tagged with a
    preset + motivation (shot["direction"], ignored by the renderer).
  - Cut points are unchanged except two splits on the existing VO beats (A01 at 40, A09 at 628).
Frames are absolute film frames at 30 fps (audio offset included). Yacht-local: +z bow, +y up; hero rotY 0
faces the bow.
"""
import json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(EP))
sys.path.insert(0, os.path.join(ROOT, "factory", "direction"))
import camera_presets as CP  # noqa: E402
import camgeo as G           # noqa: E402

base = json.load(open(os.path.join(EP, "episode.json")))
GEO = json.load(open(os.path.join(ROOT, "studio/src/data/sentinel_geo.json")))
ASPECT = base.get("width", 1080) / base.get("height", 1920)
CP.ASPECT = ASPECT

# ------------------------------------------------------------------ staging: island with the fire coast toward us
ISL_ROT, ISL_SCALE = 0.6, 0.2
FIRE_LOCAL = [(-1009.4, 5.8, 4172.8), (175.7, 5.8, 4164.2), (-418.7, 5.8, 3243.2), (1331.1, 5.8, 4112.3), (2352.9, 5.8, 3891.4), (3761.8, 5.8, 2296.3)]
ANCHOR_LOCAL = (463.0, 4375.0)          # coast vertex nearest the fire cluster (island-local metres, scale 1)
_fc = [sum(p[0] for p in FIRE_LOCAL[:5]) / 5, sum(p[2] for p in FIRE_LOCAL[:5]) / 5]
_n = G.unit([ANCHOR_LOCAL[0] - _fc[0], 0, ANCHOR_LOCAL[1] - _fc[1]])   # outward (seaward) normal, local
OFFSHORE = 130.0                         # yacht distance off the beach when aground (m)
_y_local = [ANCHOR_LOCAL[0] * ISL_SCALE + _n[0] * OFFSHORE, 0, ANCHOR_LOCAL[1] * ISL_SCALE + _n[2] * OFFSHORE]
_y_rot = G.rot_yv(ISL_ROT, _y_local)
ISL = {"asset": "island", "x": round(-_y_rot[0], 3), "z": round(-_y_rot[2], 3), "rotY": ISL_ROT, "scale": ISL_SCALE}


def isl_world(lx, ly, lz):
    q = G.rot_yv(ISL_ROT, [lx * ISL_SCALE, ly, lz * ISL_SCALE])
    return [q[0] + ISL["x"], q[1], q[2] + ISL["z"]]


BEACH = isl_world(ANCHOR_LOCAL[0], 2.5, ANCHOR_LOCAL[1])
FIRES_W = [isl_world(x, y * ISL_SCALE + 2.0, z) for x, y, z in FIRE_LOCAL]
FIRE_C = [sum(p[i] for p in FIRES_W[:3]) / 3 for i in range(3)]   # the three fires that light during A09a
U = G.unit([BEACH[0], 0, BEACH[2]])      # approach direction (yacht -> beach)
HEADING = math.atan2(U[0], U[2])         # bow points at the beach
SEAWARD = HEADING + math.pi              # the beach's facing (toward the sea / us)
FIRES = [1, 1, 1, 1, 0.9, 1]

# ------------------------------------------------------------------ v2 acting / props helpers (unchanged)
HELM = {"local": [0.55, 1.42, -4.30], "rotY": 0.0}
SWITCH = {"local": [-0.85, 1.42, -3.78], "rotY": 0.0}
RAIL = {"local": [1.45, 1.42, -4.80], "rotY": math.pi / 2}
BOW = {"local": [0.0, 1.90, 4.70], "rotY": 0.0}
COCKPIT = {"local": [0.0, 1.42, -4.60], "rotY": 0.0}
SITMARK = {"local": [-0.55, 1.42, -3.70], "rotY": math.pi}
AFTFACE = {"local": [0.0, 1.42, -4.70], "rotY": math.pi}


def yacht_at(back, **kw):
    d = {"x": round(-U[0] * back, 3), "z": round(-U[2] * back, 3), "heading": HEADING, "lights": [[0, 0]]}
    d.update(kw)
    return d


AFLOAT_FAR_LIT = yacht_at(600, lights=[[0, 1]])
AFLOAT_FAR = yacht_at(600)
AFLOAT_NEAR = yacht_at(250)


def aground(f_hit=None):
    if f_hit is None:
        return yacht_at(0, pitch=-0.10, roll=0.14, sink=0.25)
    return yacht_at(0, pitch=[[f_hit - 1, 0], [f_hit + 2, -0.13], [f_hit + 10, -0.09], [f_hit + 20, -0.10]],
                    roll=[[f_hit - 1, 0], [f_hit + 3, 0.19], [f_hit + 12, 0.12], [f_hit + 24, 0.14]],
                    sink=[[f_hit - 1, 0], [f_hit + 2, 0.27], [f_hit + 14, 0.25]])


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


# ------------------------------------------------------------------ subjects
def H(yacht, mark, stance=None):
    return CP.hero_subject(yacht, mark["local"], mark["rotY"], stance=stance)


def place(p, facing=SEAWARD, height=30.0, name="place"):
    return CP.world_subject(p, facing=facing, height=height, kind="place", name=name)


def yacht_subj(yacht, name="yacht"):
    return CP.world_subject(G.YachtFrame(yacht, 0).body_to_world([0, 2.0, 0]), facing=yacht["heading"], height=12.0, kind="object", name=name)


def az_away(subj, target_w, f):
    """az (deg) that puts the camera on the far side of the subject from a world target (target behind subject)."""
    S = subj.point(f, None)
    yaw = math.atan2(S[0] - target_w[0], S[2] - target_w[2])
    d = math.degrees(yaw - subj.facing(f))
    return (d + 180) % 360 - 180


BEACH_S = place(BEACH, height=40.0, name="beach")
FIRE_S = place(FIRE_C, height=40.0, name="fires")

SHOTS = []


def shot(id, title, f0, f1, cam, *, yacht, location, sequence, actors=None, props=None, fires=None, env=None, shakes=None,
         key=None, handheld=None, drift=None, **meta):
    camera = dict(cam["camera"])
    if handheld is not None:
        camera["handheld"] = handheld
    if drift is not None:
        camera["drift"] = drift
    if shakes:
        camera["shakes"] = shakes
    d = dict(cam["direction"])
    d.update({"location": location, "sequence": sequence})
    d.update(meta)
    s = {"id": id, "title": title, "from": f0, "to": f1, "keyFrame": key or (f0 + f1) // 2, "camera": camera,
         "yacht": yacht, "island": ISL, "direction": d}
    if actors: s["actors"] = actors
    if props: s["props"] = props
    if fires: s["fires"] = fires
    if env: s["env"] = env
    SHOTS.append(s)


# =================================================================== ACT 1 (open sea, drifting in)
Y = AFLOAT_FAR_LIT
# 1a EWS: the lit yacht alone, the dark island far beyond it on the centre line
shot("A01a", "Alone on a yacht", 0, 40, CP.establishing(0, 40, yacht_subj(Y), frame_h=60, az=(176, 172), el=(12, 10), push=0.15, lens=24),
     yacht=Y, location="open_sea", sequence="A_sea", actors=hero(HELM, hp(0, "helm", seed=2)), props=helm_props(), key=30)
# 1b crane down onto him at the helm (WS, stern-left quarter)
shot("A01b", "Alone on a yacht (helm)", 40, 75, CP.crane_descend(40, 75, H(Y, HELM), size=(14.0, "MS"), az=(150, 140), el=(30, 10), lens=28),
     yacht=Y, location="open_sea", sequence="A_sea", actors=hero(HELM, hp(0, "helm", seed=2)), props=helm_props(), key=65)
# 2 MS push from the front-left quarter: relaxed at the wheel
shot("A02", "Middle of the night", 75, 118, CP.arc_track(75, 118, H(Y, HELM), size=("MS", "MS"), az=(50, 35), el=4, emotion="calm", lens=35),
     yacht=Y, location="open_sea", sequence="A_sea", actors=hero(HELM, hp(75, "helm", poses=[P("look_down", 92, 108, 10, 10)], seed=2)), props=helm_props(), key=100)
# 3 crash push: engine dies
LFL = [[118, 1], [128, 1], [130, 0.3], [133, 1], [140, 1], [142, 0.2], [146, 0.7], [150, 0.15], [158, 0.15]]
shot("A03", "Engine died", 118, 158, CP.dolly_in(118, 158, H(Y, HELM), size=("MS", "MCU"), az=(55, 50), el=2, emotion="shock", lens=50, ease="crashIn"),
     yacht={**AFLOAT_FAR, "lights": LFL}, location="open_sea", sequence="A_sea",
     actors=hero(HELM, hp(118, "helm", poses=[P("look_back", 132, 158, 6, 6, "snap")], verbs=[V("flinch", 128, 26)], seed=2)),
     props=helm_props([[118, 1], [140, 1], [142, 0.2], [146, 0.7], [150, 0]], [[118, 1], [140, 1], [142, 0], [146, 0.5], [149, 0]]),
     shakes=[{"at": 128, "px": 6, "tau": 1.4}], key=145)
# 4 no lights, no power: tilt up from the dead switch hand to his moonlit face (same side of the line)
Y = AFLOAT_FAR
shot("A04", "No lights no power", 158, 241, CP.tilt_up(158, 241, H(Y, SWITCH), aim_from="hands", aim_to="face", size="MCU", az=35, el=2, lens=50, emotion="worry"),
     yacht=Y, location="open_sea", sequence="A_sea",
     actors=hero(SWITCH, hp(158, "stand", poses=[P("press_ahead", 166, 232, 7, 8, "snap")], verbs=[V("press_twice", 178, 26), V("press", 206, 10), V("breathe_hard", 160, 80, 0.8)], breath=1.6, seed=3)),
     props=[{"prop": "switches", "attach": "yacht", "local": [-0.85, 2.62, -3.35], "rotY": math.pi, "light": [[0, 0]]}], key=232)
# 5 current dragging: rise behind him at the rail, the island appears ahead over his shoulder
Y = AFLOAT_NEAR
shot("A05", "Current dragging", 241, 330, CP.high_reveal(241, 330, H(Y, RAIL), BEACH_S, back=(2.6, 6.0), above=(0.5, 3.2), side=0.4, lens=(30, 24), reveal_at=0.7, target_y=0.36),
     yacht=Y, location="approach", sequence="A_sea",
     actors=hero(RAIL, hp(241, "brace", poses=[P("hold_rail", 241, 330, 1, 1), P("look_left", 252, 280, 10, 12), P("look_right", 288, 322, 10, 10)], seed=4)), key=310)
# 6 map view: boom to near top-down over the yacht and the island (map overlay in Remotion)
MID = G.vlerp(G.YachtFrame(Y, 0).body_to_world([0, 0, 0]), BEACH, 0.5)
MID[1] = 0.0
shot("A06", "Toward the one island", 330, 404, CP.crane_rise(330, 404, place(MID, facing=HEADING, height=1.8, name="map"), size=(260.0, 1100.0), az=(180, 180), el=(55, 86), lens=35, emotion="fate"),
     yacht=Y, location="approach", sequence="A_sea", actors=hero(RAIL, hp(330, "brace", poses=[P("hold_rail", 330, 404, 1, 1)], seed=4)), handheld=0.0, key=380, line_cross="neutral")
# 7 North Sentinel Island! low push over the water at the beach
shot("A07", "North Sentinel Island", 404, 455, CP.dolly_in(404, 455, BEACH_S, size=(220.0, 150.0), az=8, el=1.5, lens=28, emotion="establishing", ease="arrive"),
     yacht=Y, location="island_shore", sequence="A_island", handheld=0.08, key=440)
# 8 refused contact: low lateral glide along the beach, the tree line centred
shot("A08", "Refused contact", 455, 560, CP.truck_right(455, 560, BEACH_S, size=90.0, az=-5, el=1.0, amount=70.0, lens=35, ease="linear", emotion="threat"),
     yacht=Y, location="island_shore", sequence="A_island", handheld=0.06, key=520)
# 9a they defend that: over his shoulder at the bow, fires light one by one in the trees, centre frame
FK = [[560, [0, 0, 0, 0, 0, 0]], [598, [1, 0, 0, 0, 0, 0]], [612, [1, 1, 0, 0, 0, 0]], [628, [1, 1, 1, 0, 0, 0]], [645, FIRES]]
shot("A09a", "Defend it", 560, 628, CP.over_shoulder(560, 628, H(Y, BOW), FIRE_S, shoulder="left", back=(1.7, 1.4), above=(0.32, 0.28), side=0.16, lens=(45, 52), target_y=0.4),
     yacht=Y, location="approach", sequence="A_bow", fires=FK,
     actors=hero(BOW, hp(560, "stand", poses=[P("rail_ahead", 560, 630, 1, 14), P("recoil", 636, 668, 6, 8, "snap")], verbs=[V("step_back", 636, 30, 0.8), V("breathe_hard", 640, 40)], seed=5)), key=620)
# 9b ... HARD: reverse on him from the same side of the line as the OTS (his right), push to a fear CU (CU #1)
shot("A09b", "Hard", 628, 668, CP.dolly_in(628, 668, H(Y, BOW), size=("MCU", "CU"), az=(-25, -20), el=1, lens=75, emotion="fear"),
     yacht=Y, location="approach", sequence="A_bow", fires=FK,
     actors=hero(BOW, hp(560, "stand", poses=[P("rail_ahead", 560, 630, 1, 14), P("recoil", 636, 668, 6, 8, "snap")], verbs=[V("step_back", 636, 30, 0.8), V("breathe_hard", 640, 40)], seed=5)), key=655)

# =================================================================== ACT 2 (the reef)
HIT = 690
YH = aground(HIT)
CH = H(YH, COCKPIT)
# 10 CRUNCH: high off the stern quarter looking down on him knocked flat (a waterline camera hid him behind the hull: OCC), the hull slams, the beach and fires beyond him
shot("B10", "Crunch", 668, 723, CP.handheld_documentary(668, 723, CH, size=5.0, az=(az_away(CH, BEACH, 668) - 30, az_away(CH, BEACH, 668) - 20), el=26, lens=28, aim="knees"),
     yacht=YH, location="reef", sequence="B_reef", fires=[[668, FIRES]],
     actors=hero(COCKPIT, hp(668, stances=[[-10000, "stand"], [HIT, "down"]], verbs=[V("lurch", HIT, 24, 1.0)], seed=6)),
     shakes=[{"at": HIT, "px": 14, "tau": 2.2}], key=700)
YA = aground()
CA = H(YA, COCKPIT)
# 11 stuck: slow orbit, the tilted deck and the shore
shot("B11", "Stuck on the reef", 723, 786, CP.orbit_ccw(723, 786, CA, size=("MS", "MS"), az=(110, 140), el=8, lens=35, emotion="worry"),
     yacht=YA, location="reef", sequence="B_reef", fires=[[723, FIRES]],
     actors=hero(COCKPIT, hp(723, stances=[[-10000, "down"], [735, "brace"]], poses=[P("rail_ahead", 750, 786, 10, 8)], verbs=[V("breathe_hard", 723, 63)], breath=1.8, seed=6)), key=770)
# 12 "So what do you actually do?" straight into the lens (CU #2, the one direct address)
shot("B12", "What do you do", 786, 834, CP.dolly_in(786, 834, H(YA, AFTFACE), size=("MCU", "CU"), az=0, el=0, lens=75, emotion="intimate", ease="arrive"),
     yacht=YA, location="reef", sequence="B_reef", fires=[[786, FIRES]],
     actors=hero(AFTFACE, hp(786, "brace", verbs=[V("breathe_hard", 786, 48)], breath=1.8, seed=7)), key=815, line_cross="neutral")

# =================================================================== ACT 3 (the steps, on the reef)
RADIO_IN_HAND = {"prop": "radio", "attach": "handR", "local": [0.0, -0.03, 0.0], "rot": [-90, 0, 0]}
AF = H(YA, AFTFACE)
# 13 MAYDAY: whip from the fires to him shouting into the handset
shot("C13", "Mayday", 834, 877, CP.whip_pan(834, 877, FIRE_S, AF, whip=8, size="MCU", az=30, el=2, lens=50),
     yacht=YA, location="reef", sequence="C_steps", fires=[[834, FIRES]],
     actors=hero(AFTFACE, hp(834, "brace", poses=[P("radio_shout", 846, 877, 6, 6, "overshoot")], verbs=[V("shout", 862, 18)], breath=1.5, seed=8)),
     props=[RADIO_IN_HAND | {"show": [[0, 0], [845, 0], [846, 1]]}], key=868)
# 14 insert: CH 16 on the handset at his mouth
RADIO_PT = CP.object_subject(YA, [AFTFACE["local"][0] + 0.05, AFTFACE["local"][1] + 1.48, AFTFACE["local"][2] - 0.22], size=0.3, facing=math.pi, name="radio")
shot("C14", "Channel 16", 877, 940, CP.extreme_closeup(877, 940, RADIO_PT, size=(0.55, 0.42), az=(30, 22), el=8, lens=85),
     yacht=YA, location="reef", sequence="C_steps",
     actors=hero(AFTFACE, hp(877, "brace", poses=[P("radio_mouth", 870, 940, 1, 1)], seed=8)), props=[RADIO_IN_HAND], key=910)
# 15 beacon: low angle, resolve (first low angle = the turn to action)
BEACON_IN_HAND = {"prop": "beacon", "attach": "handR", "local": [0.0, -0.02, 0.0], "rot": [-90, 0, 0], "strobe": 962}
shot("C15", "Emergency beacon", 940, 1010, CP.low_reveal(940, 1010, AF, size=("MCU", "MS"), az=(25, 35), el=(-20, -10), lens=28),
     yacht=YA, location="reef", sequence="C_steps", fires=[[940, FIRES]],
     actors=hero(AFTFACE, hp(940, "brace", poses=[P("beacon_pull", 944, 962, 6, 8), P("beacon_raise", 966, 1010, 8, 8, "overshoot")], seed=9)),
     props=[BEACON_IN_HAND], key=985)
# 16 Coast Guard patrols: big pull-back and up, the strobe tiny on the reef, the island and fires around it
shot("C16", "Coast Guard patrols", 1010, 1086, CP.pullback_reveal(1010, 1086, AF, size=("MS", 40.0), az=(40, 30), el=(6, 35), lens=(35, 24)),
     yacht=YA, location="reef", sequence="C_steps", fires=[[1010, FIRES]],
     actors=hero(AFTFACE, hp(1010, "brace", poses=[P("beacon_raise", 1000, 1086, 1, 1)], seed=9)),
     props=[BEACON_IN_HAND | {"strobe": 1000}], key=1060)
# 17 Do NOT go ashore: over his shoulder at the bow, the beach dead centre (the v2 OTS showed only sea)
BH = H(YA, BOW)
shot("C17", "Do not go ashore", 1086, 1168, CP.over_shoulder(1086, 1168, BH, BEACH_S, shoulder="left", back=(1.7, 1.4), above=(0.32, 0.28), side=0.16, lens=(45, 52), emotion="threat", target_y=0.4),
     yacht=YA, location="reef", sequence="C_bow", fires=[[1086, FIRES]],
     actors=hero(BOW, hp(1086, "stand", poses=[P("rail_ahead", 1086, 1130, 1, 10)], verbs=[V("shake_head", 1128, 34)], seed=10)), key=1140)
# 18 not for a photo: frontal-left MS push (VO beat, 50 mm)
shot("C18", "Not for a photo", 1168, 1236, CP.dolly_in(1168, 1236, BH, size=("MS", "MCU"), az=(25, 18), el=3, lens=50, emotion="honest"),
     yacht=YA, location="reef", sequence="C_bow", fires=[[1168, FIRES]],
     actors=hero(BOW, hp(1168, "stand", poses=[P("phone_up", 1170, 1196, 8, 8), P("wave", 1210, 1226, 6, 10)], verbs=[V("shake_head", 1196, 18, 0.6)], seed=10)),
     props=[{"prop": "phone", "attach": "handR", "local": [0.0, -0.02, 0.0], "rot": [-90, 0, 0], "show": [[0, 0], [1169, 0], [1170, 1], [1204, 1], [1205, 0]]}], key=1185)
# 19 no immunity: wide arc round to behind his left shoulder, the island grows behind him
shot("C19", "No immunity", 1236, 1314, CP.arc_track(1236, 1314, BH, size=("WS", 3.0), az=(95, 140), el=10, lens=28, emotion="environment"),
     yacht=YA, location="reef", sequence="C_bow", fires=[[1236, FIRES]],
     actors=hero(BOW, hp(1236, "stand", poses=[P("cover_mouth", 1262, 1300, 10, 10)], seed=11)), key=1280)
# 20 a common cold: the sneeze, then the camera rises behind him and travels with the germs to the island
shot("C20", "Common cold", 1314, 1389, CP.high_reveal(1314, 1389, BH, BEACH_S, back=(1.8, 5.0), above=(0.4, 2.6), side=0.35, lens=(35, 26), reveal_at=0.8, target_y=0.36),
     yacht=YA, location="reef", sequence="C_bow", fires=[[1314, FIRES]],
     actors=hero(BOW, hp(1314, "stand", poses=[P("cover_mouth", 1350, 1372, 4, 10, "snap")], verbs=[V("sneeze", 1326, 40, 1.2)], seed=11)), key=1352)
# 21 stay with your boat: slow arc on him sitting against the cabin
SH = H(YA, SITMARK, stance="sit")
shot("C21", "Stay with your boat", 1389, 1461, CP.orbit_cw(1389, 1461, SH, size=("WS", "MS"), az=(45, 20), el=10, lens=35, emotion="calm"),
     yacht=YA, location="reef", sequence="C_sit", fires=[[1389, FIRES]],
     actors=hero(SITMARK, hp(1389, stances=[[-10000, "stand"], [1405, "sit_deck"]], seed=12)), key=1450)
# 22 this has happened before: crane up away from the yacht (transition to the archive grade)
shot("C22", "Happened before", 1461, 1523, CP.crane_rise(1461, 1523, SH, size=("MS", 30.0), az=(20, 35), el=(10, 50), lens=(35, 24), ease="exit"),
     yacht=YA, location="reef", sequence="C_sit", fires=[[1461, FIRES]],
     actors=hero(SITMARK, hp(1461, "sit_deck", seed=12)), handheld=0.04, key=1500)
# 23-26 Primrose 1981 (separate set pending, props2 workstream): placeholder framings on our reef
REEF_S = yacht_subj(YA, "reef")
shot("D23", "Primrose 1981 (set pending)", 1523, 1650, CP.aerial_flyover(1523, 1650, REEF_S, altitude=(70, 55), dist=(260, 190), az=(160, 190), lens=24),
     yacht=YA, location="primrose_1981", sequence="D_primrose", fires=[[1523, FIRES]], time_jump=True)
shot("D24", "Armed islanders (set pending)", 1650, 1760, CP.dolly_in(1650, 1760, BEACH_S, size=(70.0, 50.0), az=4, el=2, lens=110, emotion="watched"),
     yacht=YA, location="primrose_1981", sequence="D_primrose", fires=[[1650, FIRES]])
shot("D25", "Waited for days (set pending)", 1760, 1840, CP.orbit_ccw(1760, 1840, REEF_S, size=(45.0, 40.0), az=(150, 170), el=14, lens=28, emotion="calm"),
     yacht=YA, location="primrose_1981", sequence="D_primrose", fires=[[1760, FIRES]])
shot("D26", "Helicopters (set pending)", 1840, 1931, CP.crane_rise(1840, 1931, REEF_S, size=(40.0, 120.0), az=(200, 215), el=(8, 40), lens=24, emotion="scale"),
     yacht=YA, location="primrose_1981", sequence="D_primrose", fires=[[1840, FIRES]])
# 27 back on our yacht (time jump -> re-establish): crane down onto him killing the lamp
HH = H(YA, HELM)
shot("C27", "Kill the lights", 1931, 1995, CP.crane_descend(1931, 1995, HH, size=(22.0, 3.6), az=(70, 55), el=(35, 8), lens=28),
     yacht=YA, location="reef", sequence="C_helm", fires=[[1931, FIRES]],
     actors=hero(HELM, hp(1931, "stand", poses=[P("press_ahead", 1950, 1972, 8, 10, "snap")], verbs=[V("press", 1962, 10)], seed=13)),
     props=helm_props([[0, 1], [1965, 1], [1967, 0]]), key=1958, time_jump=True)
# 28 stay quiet: finger to lips (CU #3)
shot("C28", "Stay quiet", 1995, 2029, CP.dolly_in(1995, 2029, HH, size=("MCU", "CU"), az=(30, 25), el=1, lens=75, emotion="intimate", ease="arrive"),
     yacht=YA, location="reef", sequence="C_helm", fires=[[1995, FIRES]],
     actors=hero(HELM, hp(1995, "stand", poses=[P("shush", 1998, 2029, 6, 1, "overshoot")], seed=13)), props=helm_props([[0, 0]]), key=2015)
# 29 leave nothing behind: tilt down from his face to the knot
CK = H(YA, COCKPIT)
shot("C29", "Leave nothing", 2029, 2076, CP.tilt_down(2029, 2076, CK, aim_from="face", aim_to="hands", size="MS", az=35, el=12, lens=35, emotion="procedure"),
     yacht=YA, location="reef", sequence="C_helm", fires=[[2029, FIRES]],
     actors=hero(COCKPIT, hp(2029, "stand", poses=[P("tie_bag", 2032, 2076, 8, 1)], seed=14)),
     props=[{"prop": "bag", "attach": "yacht", "local": [0.0, 1.62, -4.18], "rotY": 0}], key=2055)

# =================================================================== ACT 4 (escape, dawn)
LIFT = yacht_at(0, pitch=[[2076, -0.10], [2140, 0.0]], roll=[[2076, 0.14], [2140, 0.0]], sink=[[2076, 0.25], [2140, -0.05]])
LC = H(LIFT, COCKPIT)
# 30 the tide lifts: from just above the transom off the stern quarter, rising as the boat levels
shot("E30", "Tide lifts", 2076, 2140, CP.pedestal_up(2076, 2140, LC, size=8.0, az=az_away(LC, BEACH, 2076) - 30, el=8, amount=1.5, lens=28, emotion="relief"),
     yacht=LIFT, location="reef", sequence="E_escape", fires=[[2076, FIRES]],
     actors=hero(COCKPIT, hp(2076, "brace", poses=[P("look_down", 2090, 2140, 10, 8)], seed=15)), key=2130)
# 31 drift out past the reef: aerial pull-back, first dawn
YO = yacht_at(150)
shot("E31", "Get gone", 2140, 2200, CP.pullback_reveal(2140, 2200, H(YO, HELM), size=("WS", 45.0), az=(150, 170), el=(12, 40), lens=(28, 24), ease="exit"),
     yacht=YO, location="open_sea_dawn", sequence="E_escape", env={"dawn": 0.35}, actors=hero(HELM, hp(2140, "helm", seed=16)), props=helm_props([[0, 0]]), key=2190)
# 32-33 dawn: the island small and centred, our yacht small below it on the centre line, leaving
# the yacht has left: 1.8 km off the beach on the approach line. The camera sits ~250 m behind it on the same
# line, inside the renderer's wave tiles (13 x 60 m around the yacht; beyond them the sea is a flat plane).
YD = {"x": round(-U[0] * 1700, 3), "z": round(-U[2] * 1700, 3), "heading": HEADING + math.pi, "lights": [[0, 0]]}
DAWN = {"dawn": 0.75, "moonDir": [0.1, 0.06, 1]}
shot("E32", "Smartest way to survive", 2200, 2340, CP.establishing(2200, 2340, BEACH_S, frame_h=2250.0, az=(-0.3, 0.3), el=(2.6, 2.5), push=0.1066, lens=(35, 38), emotion="calm", ease="linear"),
     yacht=YD, location="open_sea_dawn", sequence="E_dawn", env=DAWN, key=2270)
shot("E33", "Never be there at all", 2340, 2416, CP.dolly_out(2340, 2416, BEACH_S, size=(2010.0, 2250.0), az=(0.3, -0.3), el=2.5, lens=(38, 35), emotion="calm", ease="linear"),
     yacht=YD, location="open_sea_dawn", sequence="E_dawn", env=DAWN, key=2378)

ep = dict(base)
ep["version"] = base.get("version", 1)
ep["world"] = dict(base["world"], island=ISL)
ep["shots"] = SHOTS
ep["source"] = {"builder": "episodes/sentinel/plan/build_v3.py", "shotlist": "episodes/sentinel/plan/shotlist.md",
                "direction": "factory/direction/camera_presets.py", "validator": "factory/direction/shot_validator.py"}
out = os.path.join(EP, "episode_v3.json")
json.dump(ep, open(out, "w"), indent=1)
print(f"wrote {out}: {len(SHOTS)} shots; island at ({ISL['x']}, {ISL['z']}), beach {[round(v) for v in BEACH]}, "
      f"fire centroid {[round(v) for v in FIRE_C]} ({math.dist([0, 0, 0], FIRE_C):.0f} m), heading {math.degrees(HEADING):.1f} deg")
