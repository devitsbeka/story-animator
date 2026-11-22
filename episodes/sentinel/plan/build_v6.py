#!/usr/bin/env python3
"""
Episode v6 = v5 (hero_v4 Jay, face arcs, Primrose set) with every hero camera re-directed for Jay's REAL proportions
and checked against the REAL yacht geometry.

    python3 episodes/sentinel/plan/build_v6.py && python3 factory/direction/shot_validator.py episodes/sentinel/episode_v6.json

Why (v5 keyframe sheet): close-ups cropped his face, A02 rendered brown (lens inside the cabin side), A04 black (lens
inside the cabin), and D23-D26 never rendered.

  1. Proportions from the rig (factory/direction/hero_profile_jay.json, measured by measure_hero_profile.py): at 1.8 m
     (cap included) Jay's eyes are at 1.555 m (0.864), his chin at 1.25 m (0.695), cap top 1.80 m: a 0.55 m head
     (31 % of his height; an adult is ~13 %) on shoulders at 1.09 m. v5 re-aimed the v3 cameras by a guessed
     -0.22 m "eye drop" while the old validator still assumed eyes at 1.64 m; the real drop is only 0.085 m, so
     every tight shot looked ~0.13 m too low and the generic MCU/CU frame heights (1.0 / 0.6 m, made for a 0.24 m
     head) were far too tight for a 0.55 m head: cap and brow cut off. Now camera_presets frames a profiled hero
     with his measured landmarks (and, per shot, the measured performance: a brace / look-down / lean moves the
     head): CU = forehead-to-chin with the cap inside (0.75 m frame), MCU to mid-chest, MS waist up, eyes on the
     0.38 line.
  2. Collision: camera_presets.avoid_collisions moves any key whose lens is inside / within 0.22 m of the yacht or
     whose sight line to the subject crosses it (factory/direction/yacht_proxy.json: signed-distance grid exported
     from yacht.glb + the mounted props by export_yacht_proxy.py; the hollow cabin counts as solid). The worst
     shots are also re-staged by hand: A02 / A04 / C28 face the helm console and the cabin's aft wall 0.6-1.2 m in
     front of him, so their cameras come round to his left side instead of sitting in the cabin.
  3. D23-D26 carried "set": "primrose" (a marker from build_primrose.py) which the world-kits assembler later
     started to read as a kit id -> SystemExit "unknown world kit 'primrose'" before anything rendered. The marker
     moves to direction.set_marker (the primrose ship is a prop; nothing else read the field).
  4. Craft canon (factory/canon/SOURCES.md): CAN-H1 the reef impact B10 is impact_handheld (subject escapes the frame
     6 f, the operator catches up 5 f late); CAN-C2 hero close-ups only on each sequence's reserved_close_up (A09b,
     B12, C28; C14 drops to MCU); CAN-C1 checked by the validator (wide with hero + boat + island before coverage).
  5. yacht_v2 (proc): the collision proxy is exported from the procedural yacht; C21/C22 sit on the cockpit bench.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(EP))
sys.path.insert(0, os.path.join(ROOT, "factory", "direction"))
import camera_presets as CP  # noqa: E402
import camgeo as G  # noqa: E402

SRC = json.load(open(os.path.join(EP, "episode_v5.json")))
CP.ASPECT = SRC.get("width", 1080) / SRC.get("height", 1920)
PROF = G.hero_profile("hero_v4")
assert PROF is not None, "run factory/direction/measure_hero_profile.py first"
SHOT = {s["id"]: s for s in SRC["shots"]}

# ------------------------------------------------------------------ staging (as build_v3: the island's fire coast)
ISL = SRC["world"]["island"]
FIRE_LOCAL = [(-1009.4, 5.8, 4172.8), (175.7, 5.8, 4164.2), (-418.7, 5.8, 3243.2), (1331.1, 5.8, 4112.3), (2352.9, 5.8, 3891.4), (3761.8, 5.8, 2296.3)]
ANCHOR_LOCAL = (463.0, 4375.0)


def isl_world(lx, ly, lz):
    q = G.rot_yv(ISL["rotY"], [lx * ISL["scale"], ly, lz * ISL["scale"]])
    return [q[0] + ISL["x"], q[1], q[2] + ISL["z"]]


BEACH = isl_world(ANCHOR_LOCAL[0], 2.5, ANCHOR_LOCAL[1])
FIRES_W = [isl_world(x, y * ISL["scale"] + 2.0, z) for x, y, z in FIRE_LOCAL]
FIRE_C = [sum(p[i] for p in FIRES_W[:3]) / 3 for i in range(3)]
U = G.unit([BEACH[0], 0, BEACH[2]])
SEAWARD = math.atan2(U[0], U[2]) + math.pi
BEACH_S = CP.world_subject(BEACH, facing=SEAWARD, height=40.0, kind="place", name="beach")
FIRE_S = CP.world_subject(FIRE_C, facing=SEAWARD, height=40.0, kind="place", name="fires")


def H(sid, stance=None):
    """Jay in shot `sid` (mark, facing and yacht from v5), aimed by his measured performance in that shot."""
    sh = SHOT[sid]
    a = next(x for x in sh["actors"] if x["asset"] == "hero_v4")
    st0 = ((a.get("perf") or {}).get("stance") or [[0, "stand"]])[0][1]
    return CP.hero_subject(sh["yacht"], a["local"], a.get("rotY", 0.0), a.get("height", 1.8), stance=stance,
                           profile=PROF, shot_id=sid, acting_stance=st0)


def az_away(subj, target_w, f):
    S = subj.point(f, None)
    yaw = math.atan2(S[0] - target_w[0], S[2] - target_w[2])
    d = math.degrees(yaw - subj.facing(f))
    return (d + 180) % 360 - 180


def radio_pt():
    """C14: the handset at his mouth, from the measured performance (chin landmark) instead of a fixed guess."""
    return H("C14")


# ------------------------------------------------------------------ hero shots, re-directed (frames as v3/v5)
# (v3 call, changes for Jay noted). Sizes are now Jay-sized (camgeo.HeroProfile.frame_h).
CAMS = {
    "A01b": lambda: CP.crane_descend(40, 75, H("A01b"), size=(14.0, "MS"), az=(150, 140), el=(30, 10), lens=28),
    # A02: v3 az 50->35 put the lens inside the cabin side (brown frame). From his left over the cockpit coaming,
    # slightly LOW (el -4): the key frame is inside his look-down at the wheel, and from above eye level the cap
    # brim hid his whole face (first v6 render). MS -> MCU at 30 mm keeps the lens in the open cockpit.
    "A02": lambda: CP.arc_track(75, 118, H("A02"), size=("MS", "MCU"), az=(50, 40), el=-4, emotion="calm", lens=30),
    "A03": lambda: CP.dolly_in(118, 158, H("A03"), size=("MS", "MCU"), az=(62, 56), el=2, emotion="shock", lens=45, ease="crashIn"),
    # A04: he faces the switch panel on the cabin's aft wall 0.6 m away; v3 az 35 sat inside the cabin (black).
    # Profile from his left, tilting from the pressing hand up to his face.
    "A04": lambda: CP.tilt_up(158, 241, H("A04"), aim_from="hands", aim_to="face", size="MCU", az=78, el=2, lens=40, emotion="worry"),
    "A05": lambda: CP.high_reveal(241, 330, H("A05"), BEACH_S, back=(2.6, 6.0), above=(0.5, 3.2), side=0.4, lens=(30, 24), reveal_at=0.7, target_y=0.36),
    "A09a": lambda: CP.over_shoulder(560, 628, H("A09a"), FIRE_S, shoulder="left", back=(1.7, 1.4), above=(0.32, 0.28), side=0.16, lens=(45, 52), target_y=0.4),
    "A09b": lambda: CP.dolly_in(628, 668, H("A09b"), size=("MCU", "CU"), az=(-25, -20), el=1, lens=75, emotion="fear"),
    # B10 (CAN-H1, Greengrass): the reef hit at 690 throws the operator: Jay escapes frame-left for 6 frames and the
    # camera only starts to re-acquire him 5 frames after the crunch (catch-up with a small overshoot).
    "B10": lambda: CP.impact_handheld(668, 723, H("B10"), impact=IMPACT_B10, escape_frames=6, lag_frames=5, side=-1, size=4.2,
                                      az=(az_away(H("B10"), BEACH, 668) - 30, az_away(H("B10"), BEACH, 668) - 20), el=22, lens=28, aim="knees"),
    "B11": lambda: CP.orbit_ccw(723, 786, H("B11"), size=("MS", "MS"), az=(110, 140), el=8, lens=35, emotion="worry"),
    "B12": lambda: CP.dolly_in(786, 834, H("B12"), size=("MCU", "CU"), az=0, el=0, lens=75, emotion="intimate", ease="arrive"),
    "C13": lambda: CP.whip_pan(834, 877, FIRE_S, H("C13"), whip=8, size="MCU", az=30, el=2, lens=50),
    # C14: was an 85 mm insert of a fixed point 1.48 m up: on Jay that is his nose. Now a CU on the handset at his
    # mouth with his eyes in frame (the beat is the call, his face sells it).
    # C14 (CAN-C2): the call is procedure, not the scene's decisive reaction -> MCU on the handset at his mouth.
    "C14": lambda: CP.extreme_closeup(877, 940, radio_pt(), size=("MCU", "MCU"), az=(30, 22), el=4, lens=50, insert=False, emotion="procedure"),
    "C15": lambda: CP.low_reveal(940, 1010, H("C15"), size=("MCU", "MS"), az=(25, 35), el=(-20, -10), lens=28),
    "C16": lambda: CP.pullback_reveal(1010, 1086, H("C16"), size=("MS", 40.0), az=(40, 30), el=(6, 35), lens=(35, 24)),
    "C17": lambda: CP.over_shoulder(1086, 1168, H("C17"), BEACH_S, shoulder="left", back=(1.7, 1.4), above=(0.32, 0.28), side=0.16, lens=(45, 52), emotion="threat", target_y=0.4),
    "C18": lambda: CP.dolly_in(1168, 1236, H("C18"), size=("MS", "MCU"), az=(25, 18), el=3, lens=50, emotion="honest"),
    "C19": lambda: CP.arc_track(1236, 1314, H("C19"), size=("WS", 3.0), az=(95, 140), el=10, lens=28, emotion="environment"),
    "C20": lambda: CP.high_reveal(1314, 1389, H("C20"), BEACH_S, back=(1.8, 3.4), above=(0.4, 3.0), side=0.35, lens=(35, 24), reveal_at=0.8, target_y=0.36),
    "C21": lambda: CP.orbit_cw(1389, 1461, H("C21", "sit"), size=("WS", "MS"), az=(45, 20), el=10, lens=35, emotion="calm"),
    "C22": lambda: CP.crane_rise(1461, 1523, H("C22", "sit"), size=("MS", 30.0), az=(20, 35), el=(10, 50), lens=(35, 24), ease="exit"),
    "C27": lambda: CP.crane_descend(1931, 1995, H("C27"), size=(22.0, 3.6), az=(70, 55), el=(35, 8), lens=28),
    # C28: v3 az 30->25 at 75 mm put the lens in the cabin's aft wall. 3/4 from his left over the side deck.
    "C28": lambda: CP.dolly_in(1995, 2029, H("C28"), size=("MCU", "CU"), az=(64, 56), el=1, lens=65, emotion="intimate", ease="arrive"),
    "C29": lambda: CP.tilt_down(2029, 2076, H("C29"), aim_from="face", aim_to="hands", size="MS", az=35, el=12, lens=35, emotion="procedure"),
    "E30": lambda: CP.pedestal_up(2076, 2140, H("E30"), size=8.0, az=az_away(H("E30"), BEACH, 2076) - 30, el=8, amount=1.5, lens=28, emotion="relief"),
    "E31": lambda: CP.pullback_reveal(2140, 2200, H("E31"), size=("WS", 45.0), az=(150, 170), el=(12, 40), lens=(28, 24), ease="exit"),
}
KEEP_DIR = ("location", "sequence", "time_jump", "line_cross")
IMPACT_B10 = 690          # the reef crunch (yacht pitch/roll keys 689 -> 692, camera shake at 690)

# craft canon CAN-C2: one close-up per sequence, reserved for the reaction/decision the sequence builds toward
RESERVED_CU = {
    "A_bow": ("A09b", "sees_the_reef"),          # "Hard": the instant he sees the reef and the fires ahead
    "B_reef": ("B12", "decides_to_call"),        # "What do you do": worry turns to determination
    "C_helm": ("C28", "chooses_to_hide"),        # "Stay quiet": the decision to go dark and wait for the tide
}


def main():
    ep = json.loads(json.dumps(SRC))
    n_cam = n_fix = 0
    for sh in ep["shots"]:
        if sh["id"] in CAMS:
            c = CAMS[sh["id"]]()
            old_cam, old_dir = sh["camera"], sh.get("direction") or {}
            cam = dict(old_cam)
            cam["keys"], cam["space"] = c["camera"]["keys"], c["camera"]["space"]
            d = dict(c["direction"])
            d.update({k: old_dir[k] for k in KEEP_DIR if k in old_dir})
            sh["camera"], sh["direction"] = cam, d
            n_cam += 1
            n_fix += bool(d.get("collision_fix"))
        for seq, (sid, beat) in RESERVED_CU.items():
            if sh["id"] == sid:
                sh["direction"]["reserved_close_up"] = beat
        if sh.get("set") == "primrose":            # legacy marker, not a world kit (see docstring 3)
            sh.setdefault("direction", {})["set_marker"] = sh.pop("set")
            sh["direction"].setdefault("location", "primrose_1981")
            sh["direction"].setdefault("sequence", "D_primrose")
            sh["direction"].setdefault("motivation", "reveal")
    ep["canon"] = dict(ep.get("canon") or {}, reserved_close_up={seq: sid for seq, (sid, _) in RESERVED_CU.items()},
                       impact_handheld={"B10": {"impact": IMPACT_B10, "escape_frames": 6, "lag_frames": 5}})
    ep["source"] = {"builder": "episodes/sentinel/plan/build_v6.py", "base": "episode_v5.json",
                    "hero_profile": "factory/direction/hero_profile_jay.json", "collision_proxy": "factory/direction/yacht_proxy.json"}
    out = os.path.join(EP, "episode_v6.json")
    json.dump(ep, open(out, "w"), indent=1)
    print(f"wrote {out}: {n_cam} hero cameras re-directed for Jay's proportions, {n_fix} with keys moved out of the yacht")


if __name__ == "__main__":
    main()
