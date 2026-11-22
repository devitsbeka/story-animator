"""
CLOUDRIG ADAPTER: drive a Blender Studio CloudRig human (Jay from Sprite Fright, and by name pattern
Phil / Rex) from our code-driven performance (acting.pose_at) and face (face.py) engines.

Asset: library_store/characters/jay.blend -- Blender Studio, "Sprite Fright" (CC-BY 4.0,
(c) Blender Foundation, studio.blender.org). Rig 'RIG-jay' in collection 'CH-jay'.

What it drives (all keyed on the rig's own animator controls, never on DEF bones):
  body  MSTR-Spine_Torso (hips loc + rot), MSTR-Spine_Chest (chest), FK-Neck / FK-Head (head),
        IK-MSTR-Wrist.L/R (hand position + orientation) and IK-POLE-Arm.L/R (elbows),
        IK-MSTR-Foot.L/R (feet) and IK-POLE-Leg.L/R (knees). Arms + legs + spine forced to IK,
        IK stretch off (arms never rubber-band past their length).
  face  the CloudRig face controls whose LOCAL transforms drive the rig's Action constraints:
        ACT-Eyelid_Upper/Lower (close + tilt), MSTR-EyeRing_Upper (wide), MSTR-Eyebrow (up/down,
        inner tilt, squeeze), ACT-MouthCorner (up/down, wide/squash), CTR-LipCorner (pucker),
        Jaw (open / forward), MSTR-Lip_Upper / MSTR-Lip_Lower, ACT-Lip_*_Roll, CTR-CheekPuff, Nostril,
        MSTR-Mouth (side), Eyebrow1/5 (inner / outer brow ends), CTR-Eye scale (pupil dot), LTC-Eye_Lattice scale
        (eye height) -> an authored FACE CHANNEL layer. FACE_POSES = one hand-posed channel pose per face.EMOTIONS
        name (asymmetric, calibrated on the rig's Sprite Fright pose assets), cross-faded by emotion_channels();
        ARKit-52 units over channels (ARKIT_UNITS) remain for other callers / emotions without a pose.
  eyes  MSTR-TGT-Eyes aims at a real point: face_spec "look" ('camera' via pup.camera_fn, an object name, a world
        [x,y,z], or keys [[f, target]]), else a fixation point held ahead while the head moves a little (VOR) that
        pops (1-frame saccade, led into the turn) when the head moves on. face.gaze_at keys + thought darts (on
        emotion changes) + micro-saccades are offsets on top. TGT-Eye.L/R are pulled in for real convergence, the
        nasal-turning eye is cheated (Jay's flat eye hides a nasal dot), visual angles are clamped (eye_limit).
        Upper lids ride the reached eye pitch; blinks from blink_at(): before thought changes, on head turns, withheld
        while staring in shock/fear/panic (thought_blinks).
  mouth face.viseme_track() -> VISEME_POSES over jaw + lip channels.
  life  (lesson L018) face_life(): continuous brow / lid / mouth-corner micro-drift (L/R out of phase) + nostril,
        cheek and jaw breath on every hold; transitions overlap (OVERLAP: brows lead, lids +1, cheeks +2, mouth +4 f)
        with brow/lid anticipation; eyes dart ~4 f before a thought change; conversational saccades every 0.5-2 s.
  timing (canon CAN-P1, turn-then-change) bake() re-times emotion keys off head turns: head_turns() lists the
        turn windows, settle_frame() gives the first frame a change may start (TURN_SETTLE f after the turn), and
        turn_then_change() applies it to a face_spec ('turnSettle', 'turnThenChange': false). sync_sneeze() lands
        the 'sneeze' face on the body's CHOO. Check a spec without Blender: cloud/blender/test/can_p1_check.py.

Proportions: acting.py speaks metres for a 1.8 m hero (shoulders 1.32, hips 0.93, ankles 0.16).
Jay is a 1.26 m stylised kid with a huge head and short arms; positions are re-mapped through his
MEASURED landmarks (ankle, hip joint, torso pivot, shoulder, mouth, eyes, head top): heights by a
piecewise-linear landmark warp, horizontal offsets by his shoulder-height ratio, hips/feet relative to
rest by his leg-length ratio. Hand targets are then kept outside his head + torso volumes and inside
his arm reach.

Space: everything is computed in ARMATURE space (rig rest: +X = his left, -Y = front, +Z up, feet at 0).
The holder (render_episode) scales/places the armature, exactly like the GLB actors.
"""
import math

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

import acting
import face
import hand_poses  # polish_hands_pose: finger shapes + contact points

# >>> hands/contact: wrist limits (radians). Free hands: the fingers stay within WRIST_BEND of the forearm line;
# hands on a contact anchor (helm rim, rail...) may bend a little more; a hand with no finger direction gets a
# relaxed flex of RELAX_FLEX (tan) toward the palm, like a real resting wrist.
WRIST_BEND = math.radians(22.0)
WRIST_BEND_GRIP = math.radians(32.0)
RELAX_FLEX = 0.14
ANCHOR_ELBOW_STEER = 0.3
# feet: ankle dorsiflexion limit (shin forward lean before the heel must come up), max heel roll, toe-out, and how
# much the feet turn with a hips yaw
ANKLE_DF_MAX = math.radians(30.0)
# plantarflexion limit for a planted flat foot (shin->foot angle closing vs rest; pose QC FOOT-ANKLE allows 25) and
# how far the leg may turn out (hip external rotation: knee + toes out together) to keep the ankle inside it. Jay's
# stylised legs (thigh = shin = 1.75 x ankle height) cannot raise the knee over a flat foot when the pelvis sits on
# the floor: the shin reclines >= 45 deg, so a flat foot pointing forward would be a broken, pointed ankle.
ANKLE_PF_MAX = math.radians(16.0)
TURN_OUT_MAX = math.radians(60.0)
FOOT_SPLAY_FOLLOW = 0.6      # the foot turns out this fraction of the knee's splay (feet follow the knees)
HEEL_LIFT_MAX = math.radians(70.0)
FOOT_TOE_OUT = 7.0
FOOT_YAW_FOLLOW = 0.35
# <<< hands/contact

# ---------------------------------------------------------------- acting.py reference body (metres)
ACT_LM = {"ankle": 0.16, "hipjoint": 0.849, "hips": 0.93, "shoulder": 1.32, "mouth": 1.42, "eyes": 1.55, "top": 1.75}
ACT_SHOULDER_X = 0.16
ACT_HIP_X = 0.087
ACT_STAND = acting.STANCES["stand"]

SIDES = ("L", "R")


def _side_of(key):
    return key[-1]


# ---------------------------------------------------------------- FACE CHANNELS (authored for CloudRig faces)
# channel: (bone pattern, kind, axis, amount per unit, mirror-sign for .R, (lo, hi) clamp of the raw value)
#   kind 'loc' / 'rot' = the bone's LOCAL channel (the one its Action-constraint drivers read; rot in degrees)
#   kind 'dpos' = a translation in armature space (x mirrored for .R), converted through the rest matrix
#   kind 'scl' = a LOCAL scale offset (axis = per-axis weights; scale = 1 + v * unit * w), clamp on the offset
# Calibrated on hero_v4 (Jay) against the rig's own Sprite Fright pose assets (Jay_face_smile / _worried / _panic /
# _cool in the .blend): their raw control values set units + clamps, so ~1.0 is what the Sprite Fright animators used.
FACE_CTRL = {
    "lidUp":    ("ACT-Eyelid_Upper.{S}", "loc", 1, -0.025, 1, (-0.025, 0.01)),   # 1 = upper lid fully down
    "lidLo":    ("ACT-Eyelid_Lower.{S}", "loc", 1, 0.015, 1, (-0.015, 0.015)),   # 1 = lower lid fully up
    "lidTilt":  ("ACT-Eyelid_Upper.{S}", "rot", 2, 32.0, -1, (-45, 45)),         # + = outer corner down (sad)
    "eyeWide":  ("MSTR-EyeRing_Upper.{S}", "dpos", 2, 0.007, 1, (-0.012, 0.012)),  # + = upper ring up
    "browUp":   ("MSTR-Eyebrow.{S}", "loc", 1, 0.012, 1, (-0.015, 0.02)),
    "browIn":   ("MSTR-Eyebrow.{S}", "rot", 2, 16.0, -1, (-35, 35)),            # + = inner end up / outer down
    "browSq":   ("MSTR-Eyebrow.{S}", "loc", 0, 0.006, -1, (-0.012, 0.012)),      # + = towards the nose
    "browInUp": ("Eyebrow1.{S}", "loc", 1, -0.012, 1, (-0.018, 0.01)),         # + = inner brow end up (SF worried ~1.1)
    "browInRot": ("Eyebrow1.{S}", "rot", 2, -22.0, -1, (-35, 35)),             # + = inner end twist (keeps the arch smooth)
    "browOutUp": ("Eyebrow5.{S}", "loc", 1, -0.006, 1, (-0.012, 0.012)),       # + = outer brow end up
    "cornerUp": ("ACT-MouthCorner.{S}", "loc", 0, 0.03, -1, (-0.035, 0.035)),    # + = smile, - = frown
    "cornerWide": ("ACT-MouthCorner.{S}", "loc", 1, -0.035, 1, (-0.05, 0.025)),  # + = wide, - = squash
    "pucker":   ("CTR-LipCorner.{S}", "loc", 1, 0.008, 1, (-0.012, 0.012)),      # + = corner in
    "cheek":    ("CTR-CheekPuff.{S}", "loc", 1, 0.008, 1, (-0.01, 0.012)),       # + = cheek raised
    "sneer":    ("Nostril.{S}", "loc", 1, 0.004, 1, (-0.006, 0.006)),            # + = nostril up
    "jaw":      ("Jaw", "loc", 2, 0.045, 1, (-0.008, 0.05)),                     # + = open
    "jawFwd":   ("Jaw", "loc", 1, 0.006, 1, (-0.01, 0.01)),
    "upLip":    ("MSTR-Lip_Upper", "loc", 1, -0.004, 1, (-0.01, 0.008)),         # + = upper lip up
    "loLip":    ("MSTR-Lip_Lower", "loc", 1, -0.004, 1, (-0.016, 0.008)),        # + = lower lip down
    "rollUp":   ("ACT-Lip_Upper_Roll", "rot", 0, 30.0, 1, (-60, 60)),            # + = roll in (press)
    "rollLo":   ("ACT-Lip_Lower_Roll", "rot", 0, 30.0, 1, (-60, 60)),
    "mouthSide": ("MSTR-Mouth", "dpos", 0, 0.010, 1, (-0.02, 0.02)),             # + = towards his left
    "pupil":    ("CTR-Eye.{S}", "scl", (1, 0, 1), 0.3, 1, (-0.6, 0.35)),         # + = bigger pupil dot (SF panic ~ -1.8)
    "eyeBig":   ("LTC-Eye_Lattice.{S}", "scl", (0.25, 0.25, 1.0), 0.4, 1, (-0.3, 0.7)),  # + = taller eye (SF panic ~1.7)
}

CHANNELS = []
for _c, _spec in FACE_CTRL.items():
    if "{S}" in _spec[0]:
        CHANNELS += [f"{_c}.L", f"{_c}.R"]
    else:
        CHANNELS.append(_c)


def _both(d, **kw):
    """helper: same channel values on both sides"""
    out = dict(d)
    for k, v in kw.items():
        out[k + ".L"] = out.get(k + ".L", 0) + v
        out[k + ".R"] = out.get(k + ".R", 0) + v
    return out


def _one(s, **kw):
    return {f"{k}.{s}": v for k, v in kw.items()}


# ARKit-52 units authored as channel poses (weight 1.0). Sided units are written once per side.
ARKIT_UNITS = {}
for _s, _n in (("L", "Left"), ("R", "Right")):
    ARKIT_UNITS.update({
        f"eyeBlink{_n}":      _one(_s, lidUp=1.0, lidLo=0.25),
        f"eyeSquint{_n}":     _one(_s, lidLo=0.75, lidUp=0.18, cheek=0.35),
        f"eyeWide{_n}":       _one(_s, eyeWide=0.8, lidLo=-0.9, browUp=0.2),
        f"eyeLookDown{_n}":   _one(_s, lidUp=0.25),
        f"browDown{_n}":      _one(_s, browUp=-0.9, browSq=0.8, browIn=-0.35, lidUp=0.12),
        f"browOuterUp{_n}":   _one(_s, browUp=0.8, browIn=-0.55),
        f"mouthSmile{_n}":    _one(_s, cornerUp=1.0, cornerWide=0.35, cheek=0.6, lidLo=0.2),
        f"mouthFrown{_n}":    _one(_s, cornerUp=-1.0, cornerWide=0.1),
        f"mouthStretch{_n}":  _one(_s, cornerWide=1.0, cornerUp=-0.3),
        f"mouthPress{_n}":    _one(_s, cornerWide=0.15, pucker=-0.2),
        f"mouthDimple{_n}":   _one(_s, cornerWide=0.3, pucker=-0.3),
        f"mouthUpperUp{_n}":  _one(_s, sneer=0.35, cheek=0.15),
        f"mouthLowerDown{_n}": _one(_s, cornerWide=0.1),
        f"noseSneer{_n}":     _one(_s, sneer=1.0, cheek=0.45, browUp=-0.25, browSq=0.3, lidLo=0.2),
        f"cheekSquint{_n}":   _one(_s, cheek=1.0, lidLo=0.35),
    })
    # mouthUpperUp/LowerDown also move the centre lip masters, shared half by each side
    ARKIT_UNITS[f"mouthUpperUp{_n}"]["upLip"] = 0.5
    ARKIT_UNITS[f"mouthLowerDown{_n}"]["loLip"] = 0.5
    ARKIT_UNITS[f"mouthPress{_n}"]["rollUp"] = 0.25
    ARKIT_UNITS[f"mouthPress{_n}"]["rollLo"] = 0.25
ARKIT_UNITS.update({
    "browInnerUp":  _both({}, browIn=1.0, browUp=0.35, browSq=0.25),
    "jawOpen":      {"jaw": 1.0},
    "jawForward":   {"jawFwd": 1.0},
    "jawLeft":      {"mouthSide": 0.4},
    "jawRight":     {"mouthSide": -0.4},
    "mouthLeft":    {"mouthSide": 1.0},
    "mouthRight":   {"mouthSide": -1.0},
    "mouthClose":   {"jaw": -0.2},
    "mouthFunnel":  _both({"jaw": 0.12, "rollUp": -0.6, "rollLo": -0.6}, cornerWide=-0.7, pucker=0.5),
    "mouthPucker":  _both({"rollUp": -0.4, "rollLo": -0.4}, cornerWide=-0.6, pucker=1.0),
    "mouthRollUpper": {"rollUp": 1.0},
    "mouthRollLower": {"rollLo": 1.0},
    "mouthShrugUpper": {"upLip": 0.4},
    "mouthShrugLower": {"loLip": -0.6, "jaw": -0.1},
    "cheekPuff":    _both({}, cheek=0.6, pucker=0.3),
})

# Per-emotion stylisation on top of the ARKit mix (CloudRig faces read better a little pushed)
EMOTION_EXTRA = {
    "calm":       _both({}, lidUp=0.12),
    "concern":    _both({}, lidTilt=0.4),
    "worried":    _both({}, lidTilt=0.8),
    "fear":       _both({}, eyeWide=0.4),
    "shock":      _both({"jaw": 0.15}, eyeWide=0.6),
    "panic":      _both({}, lidTilt=0.5, eyeWide=0.3),
    "pain":       _both({}, lidTilt=-0.3),
    "determined": _both({}, lidTilt=-0.6, lidUp=0.15),
    "shout":      _both({}, lidTilt=-0.4),
    "hopeful":    _both({}, lidTilt=0.4),
    "relief":     _both({}, lidTilt=0.3),
    "secret":     _both({}, lidUp=0.2),
    "wince":      _both({}, lidTilt=-0.3),
}


def channels_from_arkit(weights):
    out = {}
    for unit, w in (weights or {}).items():
        for ch, v in ARKIT_UNITS.get(unit, {}).items():
            out[ch] = out.get(ch, 0.0) + v * w
    return out


def _add(a, b, k=1.0):
    for ch, v in b.items():
        a[ch] = a.get(ch, 0.0) + v * k
    return a


# Legacy pose library (ARKit mix from face.EMOTIONS + stylisation), kept for reference / non-Jay CloudRig faces.
FACE_POSES_ARKIT = {name: _add(channels_from_arkit(w), EMOTION_EXTRA.get(name, {})) for name, w in face.EMOTIONS.items()}

# Resting upper lid (0 = wide open .. 1 = shut): the lid line just covers the top of the iris (no 'crazy stare').
REST_LIDS = 0.3
# Resting pupil dot size (channel units): a touch bigger than the rig default reads softer / more appealing.
REST_PUPIL = 0.3


def _pose(asym=0.1, lead="L", L=None, R=None, **kw):
    """author one expression: kw = channel values on both sides (centre channels as-is); `asym` makes the lead
    side that much stronger and the other weaker (5-15% keeps a face alive); L / R = one-sided additions."""
    out = {}
    for k, v in kw.items():
        if k in FACE_CTRL and "{S}" in FACE_CTRL[k][0]:
            for s in SIDES:
                out[f"{k}.{s}"] = v * (1 + asym if s == lead else 1 - asym)
        else:
            out[k] = v
    for s, extra in (("L", L), ("R", R)):
        for k, v in (extra or {}).items():
            out[f"{k}.{s}"] = out.get(f"{k}.{s}", 0.0) + v
    return out


# The FACE POSE LIBRARY, hand-posed on Jay's controls (every face.EMOTIONS key). Read with the rig's Sprite Fright
# pose assets as reference (smile: corners up+wide with the cheeks; worried: inner brow ends up, lower lip rolled out,
# small pupils; panic: tall eyes, tiny pupils, wide frown). Values are channel units (see FACE_CTRL); the resting lid
# REST_LIDS is added on top at run time, so lidUp here is relative to it.
FACE_POSES = {
    "neutral":    _pose(0.0, cheek=0.05, upLip=0.15, loLip=0.25, pucker=-0.1, L={"cornerUp": 0.18}, R={"cornerUp": 0.06}),  # resting lopsided half-smile
    "calm":       _pose(0.1, cornerUp=0.3, cornerWide=0.12, cheek=0.3, lidLo=0.28, lidUp=-0.02, browIn=0.1),
    "content":    _pose(0.12, cornerUp=0.75, cornerWide=0.45, cheek=0.8, lidLo=0.5, lidUp=-0.08, browUp=0.15, browInUp=0.15,
                        pupil=0.2, loLip=0.2),
    "concern":    _pose(0.1, browInUp=0.6, browInRot=0.4, browIn=0.35, browSq=0.4, browUp=-0.1, lidTilt=0.3, lidLo=0.15,
                        cornerUp=-0.25, cornerWide=-0.15, pucker=0.1, rollLo=-0.3),
    "worried":    _pose(0.12, browInUp=1.1, browInRot=0.9, browIn=0.6, browSq=0.35, browUp=-0.2, browOutUp=-0.3, lidTilt=0.7,
                        lidUp=-0.05, lidLo=0.1, cornerUp=-0.35, cornerWide=-0.4, rollLo=-1.5, jaw=0.15, pupil=-0.5),
    "fear":       _pose(0.08, browUp=1.0, browIn=0.7, browInUp=0.8, browSq=0.3, eyeWide=0.9, eyeBig=0.5, lidUp=-0.35,
                        lidLo=-0.4, cornerWide=0.9, cornerUp=-0.45, jaw=0.3, loLip=0.8, pupil=-1.2),
    "shock":      _pose(0.06, browUp=1.3, browIn=0.3, browOutUp=0.5, eyeWide=1.2, eyeBig=0.9, lidUp=-0.4, lidLo=-0.6,
                        jaw=0.45, cornerWide=-0.8, pucker=0.45, rollUp=-0.3, rollLo=-0.3, pupil=-1.0),
    "panic":      _pose(0.0, browUp=1.05, browIn=1.0, browInUp=0.2, eyeBig=1.6, lidUp=-0.35, rollLo=-2.0, jaw=1.1,
                        pupil=-1.8, L={"cornerUp": -0.5, "cornerWide": 1.25}, R={"cornerUp": -0.93, "cornerWide": 1.4}),
    "pain":       _pose(0.15, browSq=1.0, browUp=-0.6, browInUp=0.7, browIn=0.4, lidUp=0.45, lidLo=0.8, cheek=0.8, sneer=0.8,
                        cornerWide=0.9, cornerUp=-0.3, upLip=0.8, jaw=0.2, lidTilt=-0.2),
    "determined": _pose(0.12, browUp=-0.75, browSq=0.9, browIn=-0.6, browInUp=-0.4, browOutUp=0.2, lidUp=-0.06, lidLo=0.5,
                        lidTilt=-0.25, cornerUp=-0.12, cornerWide=0.05, rollUp=0.7, rollLo=0.55, jawFwd=0.5, pupil=0.0, mouthSide=0.35,
                        cheek=0.2, L={"cornerUp": -0.3, "cornerWide": 0.35, "cheek": 0.25}, R={"cornerUp": 0.12}),
    "shout":      _pose(0.1, browUp=-0.7, browSq=1.0, browIn=-0.8, browInUp=-0.4, lidLo=0.5, lidUp=0.05, jaw=1.0, cornerWide=1.0, cornerUp=-0.1,
                        upLip=1.5, loLip=1.0, sneer=0.6, cheek=0.4),
    "hopeful":    _pose(0.1, browInUp=0.6, browIn=0.4, browUp=0.35, cornerUp=0.35, cornerWide=0.1, cheek=0.3, lidUp=-0.12,
                        pupil=0.25, lidLo=0.15),
    "relief":     _pose(0.1, browInUp=0.5, browIn=0.3, browUp=0.1, lidUp=0.3, lidLo=0.3, cornerUp=0.5, cornerWide=0.3, cheek=0.4,
                        jaw=0.12, loLip=0.3),
    "sneeze_build": _pose(0.15, browInUp=1.2, browUp=0.6, browIn=0.6, lidUp=0.35, lidLo=0.45, cheek=0.7, sneer=1.0, upLip=1.5,
                          jaw=0.45, cornerWide=0.3),
    "sneeze":     _pose(0.1, lidUp=1.0, lidLo=0.7, browUp=-0.9, browSq=1.0, browIn=-0.3, cheek=1.0, sneer=1.0, upLip=1.0,
                        jaw=0.65, cornerWide=0.7, cornerUp=-0.2),
    "secret":     _pose(0.05, pucker=1.0, cornerWide=-0.8, rollUp=-0.5, rollLo=-0.5, jaw=0.05, browInUp=0.3, lidUp=0.2,
                        lidLo=0.3, mouthSide=0.3, cornerUp=0.15, L={"browUp": 1.0, "browOutUp": 0.6}, R={"browUp": -0.3}),
    # wince: knitted brows pulled down, one eye squeezed (lead side), grimace = upper lip up off the teeth, one corner
    # yanked back + down, mouth pulled to that side (not a flat pressed line)
    "wince":      _pose(0.2, browSq=1.2, browUp=-0.75, browInUp=0.55, browIn=0.3, lidUp=0.4, lidLo=0.7, cheek=0.8, sneer=0.7,
                        cornerWide=0.8, cornerUp=-0.25, mouthSide=-0.5, upLip=0.9, loLip=0.4, jaw=0.08,
                        R={"cornerUp": -0.25, "cornerWide": 0.3, "cheek": 0.3}),
}
for _n in face.EMOTIONS:                     # any emotion added to face.py later still gets a (legacy) pose
    FACE_POSES.setdefault(_n, FACE_POSES_ARKIT[_n])

# face.VIS viseme keys -> channel poses (jaw + lips); co-articulated weights come from face.visemes_at
VISEME_POSES = {
    "aa_02":          _both({"jaw": 0.62, "loLip": 0.3}, cornerWide=0.15),
    "ey_eh_uh_04":    _both({"jaw": 0.36, "upLip": 0.2}, cornerWide=0.45),
    "y_iy_ih_ix_06":  _both({"jaw": 0.16, "upLip": 0.25}, cornerWide=0.75, cornerUp=0.1),
    "ow_08":          _both({"jaw": 0.42, "rollUp": -0.5, "rollLo": -0.5}, cornerWide=-0.65, pucker=0.6),
    "w_uw_07":        _both({"jaw": 0.14, "rollUp": -0.6, "rollLo": -0.6}, cornerWide=-0.6, pucker=1.0),
    "p_b_m_21":       _both({"jaw": -0.25, "rollUp": 0.35, "rollLo": 0.35}, cornerWide=0.05),
    "f_v_18":         _both({"jaw": 0.08, "loLip": -0.8, "rollLo": 0.7, "upLip": 0.2}, cornerWide=0.2),
    "d_t_n_19":       _both({"jaw": 0.22, "upLip": 0.2}, cornerWide=0.3),
    "l_14":           _both({"jaw": 0.32}, cornerWide=0.2),
    "r_13":           _both({"jaw": 0.2, "rollUp": -0.2}, cornerWide=-0.3, pucker=0.3),
    "s_z_15":         _both({"jaw": 0.07, "upLip": 0.3, "loLip": 0.3}, cornerWide=0.55),
    "k_g_ng_20":      _both({"jaw": 0.26}, cornerWide=0.3),
    "h_12":           _both({"jaw": 0.38}, cornerWide=0.1),
    "sh_ch_jh_zh_16": _both({"jaw": 0.16, "rollUp": -0.4, "rollLo": -0.4, "upLip": 0.3}, cornerWide=-0.45, pucker=0.5),
}


# ---------------------------------------------------------------- small math
def _q_char(pitch, yaw, roll):
    """acting.py convention, armature space: pitch + = lean forward (about +X: top goes to -Y),
    yaw + = turn to his left (about +Z), roll + = tilt to his left (about +Y: top goes to +X)."""
    return (Quaternion((0, 0, 1), math.radians(yaw)) @ Quaternion((1, 0, 0), math.radians(pitch))
            @ Quaternion((0, 1, 0), math.radians(roll)))


def _warp(points, z):
    """piecewise-linear map through (src, dst) landmark pairs, linear extrapolation at both ends."""
    if z <= points[0][0]:
        (a0, b0), (a1, b1) = points[0], points[1]
    elif z >= points[-1][0]:
        (a0, b0), (a1, b1) = points[-2], points[-1]
    else:
        for i in range(len(points) - 1):
            if points[i][0] <= z <= points[i + 1][0]:
                (a0, b0), (a1, b1) = points[i], points[i + 1]
                break
    t = (z - a0) / max(1e-9, a1 - a0)
    return b0 + (b1 - b0) * t


# ---------------------------------------------------------------- the puppet
class CloudRigPuppet:
    """Puppet-compatible driver for a CloudRig human. Usage (render_episode / tests):
         pup = CloudRigPuppet(arm)
         keyed = pup.bake(perf, face_spec, f0, f1)       # or pup.bake(perf, f0, f1) like acting.Puppet
    face_spec (optional) = {"emotion": [[f, "name", amt?], ...], "gaze": [[f, yaw, pitch], ...],
        "words": [{"w","s","e"}, ...], "wordsOffset": frames, "blinks": [f, ...], "lids": 0..1 relax,
        "seed": n, "blend": frames, "speech": strength}
    """

    def __init__(self, arm, holder=None):
        self.arm, self.holder = arm, holder
        P = arm.pose.bones
        self.P = P

        def need(n):
            if n not in P:
                raise KeyError(f"CloudRig control '{n}' missing in {arm.name}")
            return P[n]

        def opt(n):
            return P.get(n)

        self.torso, self.chest = need("MSTR-Spine_Torso"), need("MSTR-Spine_Chest")
        self.neck, self.head = opt("FK-Neck"), need("FK-Head")
        self.wrist = {s: need(f"IK-MSTR-Wrist.{s}") for s in SIDES}
        self.apole = {s: need(f"IK-POLE-Arm.{s}") for s in SIDES}
        self.foot = {s: need(f"IK-MSTR-Foot.{s}") for s in SIDES}
        self.lpole = {s: need(f"IK-POLE-Leg.{s}") for s in SIDES}
        self.upper = {s: need(f"IK-UpperArm.{s}") for s in SIDES}
        self.fore = {s: need(f"IK-Forearm.{s}") for s in SIDES}
        self.thigh = {s: need(f"ROOT-Thigh.{s}") for s in SIDES}
        self.eyetgt = opt("MSTR-TGT-Eyes")
        self.eyecen = opt("CEN-Eyes")
        self.headdef = opt("DEF-Head") or self.head
        self.facectl = {}
        for ch in CHANNELS:
            base, s = (ch[:-2], ch[-1]) if ch[-2:] in (".L", ".R") else (ch, None)
            spec = FACE_CTRL[base]
            bn = spec[0].replace("{S}", s or "")
            if bn in P:
                self.facectl[ch] = (P[bn], spec, s)
        # >>> hands/contact (polish_hands_pose): FK finger controls, leg bones for knee anchors, anchor sources
        self.fingers = {s: [P[n] for n in hand_poses.bone_names(s) if n in P] for s in SIDES}
        self.shin = {s: P.get(f"IK-Shin.{s}") or P.get(f"FK-Shin.{s}") for s in SIDES}
        self.mouth = P.get("MSTR-Mouth")
        self.anchors = {}          # name -> (p, n, d, kind) in armature space (static: props, rails, marks)
        self.rail_snap = None      # callable(world point) -> (world point, world tangent) | None
        self._dirw = {"L": 0.0, "R": 0.0}   # per-frame: how strongly the finger direction is authored
        self.toes = {s: P.get(f"IK-Toes.{s}") for s in SIDES}
        self._toe_m = {}
        self.foot_lift = {"L": 0.0, "R": 0.0}
        self.knee_splay = {"L": 0.0, "R": 0.0}   # per frame: hip external rotation chosen by _plant_foot
        self._knee_fwd = {}
        # <<< hands/contact
        self._set_ik_mode()
        for pb in self._controls():
            pb.rotation_mode = "XYZ" if pb.rotation_mode == "QUATERNION" else pb.rotation_mode
        self._measure()
        self._prev_eul = {}
        # Jay's flat cartoon eyeballs lose the pupil past ~15 deg of yaw: eye rotation = gaze * gain
        self.gaze_gain = (0.55, 0.75)
        # EYE CRAFT. The eyes aim at a real point (the camera, an object, or a held fixation point ahead) instead of a
        # head-locked direction: TGT-Eye.L/R are pulled in towards the master target so the two eyes converge on it
        # (vergence 1 = both eye targets on the point; the rig's rest spreads them 13 cm = parallel/wall-eyed).
        self.eyetgt_lr = {s: opt(f"TGT-Eye.{s}") for s in SIDES}
        self.vergence = 1.0                  # 1 = geometric convergence for the target distance, 0 = parallel
        self.ipd = 0.06                      # pupil-dot separation (armature m) used for the convergence angle
        self._eye_dist_real = 1.6
        self._eye_yaw = 0.0
        self.nasal_gain = 0.45
        self.debug_eyes = False
        self.eye_limit = (28.0, 14.0)        # max VISUAL eye-in-head yaw / pitch (deg) before the dot slides off
        self.eye_gain = (0.55, 0.5)          # visual angle -> rig angle (the dot on the flat eye reads ~2x the bone turn)
        self.camera_fn = None                # f -> world-space camera position (set by the shot builder / sheets)
        self.fix_hold = 9.0                  # deg: head motion inside this keeps the fixation (VOR), beyond = saccade
        self._fix = self._fix_frame = self._last_head_pt = None
        self._eye_pitch = 0.0

    # ---------------------------------------------------------------- setup
    def _set_ik_mode(self):
        """arms, legs, spine in IK; no IK stretch; poles in world (root) space; head hinge off."""
        for pb in self.P:
            if not pb.name.startswith("PRP-"):
                continue
            for k in list(pb.keys()):
                if k.startswith("ik_") and (k.endswith("_arm") or k.endswith("_leg")) and not k.startswith(("ik_stretch", "ik_parents", "ik_pole")):
                    pb[k] = 1.0
                elif k.startswith("ik_stretch"):
                    pb[k] = 0.0 if not k.endswith("spine") else pb[k]
                elif k.startswith("ik_parents") or k.startswith("ik_pole_follow"):
                    pb[k] = 0
                elif k == "ik_spine":
                    pb[k] = 1.0
        self.arm.update_tag()

    def _controls(self):
        out = [self.torso, self.chest, self.head, *self.wrist.values(), *self.apole.values(), *self.foot.values(), *self.lpole.values()]
        if self.neck:
            out.append(self.neck)
        if self.eyetgt:
            out.append(self.eyetgt)
        out += [b for b in (getattr(self, "eyetgt_lr", None) or {}).values() if b is not None]
        out += [v[0] for v in self.facectl.values()]
        for s in SIDES:
            out += self.fingers.get(s, [])
            if self.toes.get(s) is not None:
                out.append(self.toes[s])
        return list(dict.fromkeys(out))

    def life_controls(self):
        """the controls face-life QC watches (body, head, eyes, face): every keyed control except the finger FK
        chains and toe pivots, which are held shapes. Watching ~30 static finger bones as well diluted the mean
        per-channel motion about 2x and failed FACE-LIFE on a face that moves as much as before (merge of the
        hands/feet polish, which added them to _controls())."""
        held = set()
        for s in SIDES:
            held.update(pb.name for pb in self.fingers.get(s, []))
            if self.toes.get(s) is not None:
                held.add(self.toes[s].name)
        return [pb for pb in self._controls() if pb.name not in held]

    def _measure(self):
        """rest landmarks in armature space -> the proportion map."""
        arm = self.arm
        h = lambda pb: pb.bone.head_local.copy()
        self.rest_foot = {s: h(self.foot[s]) for s in SIDES}
        ankle = sum(p.z for p in self.rest_foot.values()) / 2
        hipj = sum(h(self.thigh[s]).z for s in SIDES) / 2
        torso = h(self.torso).z
        self.rest_sh = {s: h(self.upper[s]) for s in SIDES}
        sh = sum(p.z for p in self.rest_sh.values()) / 2
        self.arm_len = {s: self.upper[s].bone.length + self.fore[s].bone.length for s in SIDES}
        mouth = h(self.P["MSTR-Mouth"]).z if "MSTR-Mouth" in self.P else sh + 0.45 * (sh - hipj)
        eyes = h(self.eyecen).z if self.eyecen else mouth + 0.12
        # head volume from the head mesh (rest, armature space)
        inv = arm.matrix_world.inverted()
        head_me = None
        top = eyes + 0.15
        for o in arm.children_recursive:
            if o.type == "MESH" and o.name.lower().endswith("_head") and not o.hide_render:
                head_me = o
        bb_min, bb_max = Vector((-0.08, -0.08, mouth - 0.06)), Vector((0.08, 0.08, eyes + 0.15))
        if head_me is not None:
            M = inv @ head_me.matrix_world
            cs = [M @ Vector(c) for c in head_me.bound_box]
            bb_min = Vector((min(c.x for c in cs), min(c.y for c in cs), min(c.z for c in cs)))
            bb_max = Vector((max(c.x for c in cs), max(c.y for c in cs), max(c.z for c in cs)))
            top = bb_max.z
        self.head_c = (bb_min + bb_max) * 0.5
        self.head_r = (bb_max - bb_min) * 0.5
        # torso half-widths from the deforming meshes between hips and armpits
        xs, ys = [], []
        for o in arm.children_recursive:
            if o.type != "MESH" or o.hide_render or o == head_me or len(o.data.vertices) < 200:
                continue
            if not any(m.type == "ARMATURE" for m in o.modifiers):
                continue
            M = inv @ o.matrix_world
            for v in o.data.vertices:
                p = M @ v.co
                if torso <= p.z <= sh - 0.04 and abs(p.x) < 0.25:
                    xs.append(abs(p.x))
                    ys.append(p.y)
        self.torso_rx = max(xs) if xs else 0.1
        self.torso_y = (min(ys), max(ys)) if ys else (-0.07, 0.07)
        self.LM = {"ankle": ankle, "hipjoint": hipj, "hips": torso, "shoulder": sh, "mouth": mouth, "eyes": eyes, "top": top}
        keys = ["ankle", "hipjoint", "hips", "shoulder", "mouth", "eyes", "top"]
        self.zwarp = [(0.0, 0.0)] + [(ACT_LM[k], self.LM[k]) for k in keys]
        self.k_xy = (sh - ankle) / (ACT_LM["shoulder"] - ACT_LM["ankle"])
        self.k_leg = (hipj - ankle) / (ACT_LM["hipjoint"] - ACT_LM["ankle"])
        self.height = top
        self.rest_torso = h(self.torso)
        self.eye_dist = (h(self.eyetgt) - h(self.eyecen)).length if (self.eyetgt and self.eyecen) else 0.7
        # >>> hands/contact: thigh thickness (seat height of the pelvis), rest hand frame
        knee = h(self.shin["L"]).z if self.shin.get("L") else hipj - 0.45 * (hipj - ankle)
        # feet: ball of the foot (toe pivot) and leg segment lengths for the planted-foot solve
        self.rest_ball = {}
        self.leg_l = {}
        self.rest_ankle = {}
        for s in SIDES:
            tb = self.toes.get(s)
            self.rest_ball[s] = h(tb) if tb is not None else self.rest_foot[s] + Vector((0, -0.1, -0.05))
            hp, an = h(self.thigh[s]), self.rest_foot[s]
            kn = h(self.shin[s]) if self.shin.get(s) else (hp + an) * 0.5 + Vector((0, -0.01, 0))
            self.leg_l[s] = ((kn - hp).length, (an - kn).length)
            # rest shin->foot angle (what pose QC's FOOT-ANKLE measures against): knee->ankle vs ankle->ball
            self.rest_ankle[s] = (an - kn).angle(self.rest_ball[s] - an, math.pi / 2)
        zt = knee + 0.55 * (hipj - knee)
        ty = []
        for o in arm.children_recursive:
            if o.type != "MESH" or o.hide_render or o == head_me or len(o.data.vertices) < 200:
                continue
            if not any(m.type == "ARMATURE" for m in o.modifiers):
                continue
            M = inv @ o.matrix_world
            for v in o.data.vertices:
                p = M @ v.co
                if abs(p.z - zt) < 0.012 and 0.0 < p.x < 0.2:
                    ty.append(p.y)
        self.thigh_r = (max(ty) - min(ty)) * 0.5 if ty else 0.05
        # pelvis pivot above the seat surface when sitting with level thighs
        self.seat_h = (torso - hipj) + self.thigh_r * 0.95
        self.knee_z = knee
        self.hand_rest = {}
        for s in SIDES:
            w = self.wrist[s].bone
            F = (w.tail_local - w.head_local).normalized()
            N = Vector((0, 0, -1))
            N = (N - F * N.dot(F)).normalized()
            T = Vector((0, -1, 0))
            self.hand_rest[s] = (F, N, T)
        # <<< hands/contact

    def describe(self):
        return {"landmarks": {k: round(v, 4) for k, v in self.LM.items()}, "k_xy": round(self.k_xy, 4), "k_leg": round(self.k_leg, 4),
                "arm_len": {s: round(v, 4) for s, v in self.arm_len.items()}, "head_c": tuple(round(x, 4) for x in self.head_c),
                "head_r": tuple(round(x, 4) for x in self.head_r), "torso_rx": round(self.torso_rx, 4),
                "torso_y": tuple(round(x, 4) for x in self.torso_y), "thigh_r": round(self.thigh_r, 4),
                "seat_h": round(self.seat_h, 4), "fingers": {s: len(v) for s, v in self.fingers.items()}}

    # ---------------------------------------------------------------- mapping
    def map_point(self, p):
        """acting char-space point (1.8 m hero) -> Jay armature space (landmark warp)."""
        return Vector((p[0] * self.k_xy, p[1] * self.k_xy, _warp(self.zwarp, p[2])))

    def _clear_hand(self, t, s, sh_pose, head_c, head_q, spine_a, spine_b):
        """keep a hand target out of the head + torso and inside the arm's reach."""
        t = t.copy()
        # torso: elliptic cylinder around the (posed) spine line, half a hand of margin
        if spine_a.z <= t.z <= spine_b.z + 0.02:
            u = (t.z - spine_a.z) / max(1e-6, spine_b.z - spine_a.z)
            c = spine_a.lerp(spine_b, min(1.0, max(0.0, u)))
            rx, ry0, ry1 = self.torso_rx + 0.03, self.torso_y[0] - 0.03, self.torso_y[1] + 0.03
            dx, dy = t.x - c.x, t.y - c.y
            ry = -ry0 if dy < 0 else ry1
            e = (dx / rx) ** 2 + (dy / ry) ** 2
            if e < 1.0:
                k = 1.0 / math.sqrt(max(e, 1e-6))
                if e < 1e-4:
                    dx, dy, k = (rx if s == "L" else -rx), 0.0, 1.0
                t.x, t.y = c.x + dx * k, c.y + dy * k
        # head: ellipsoid (rotates with the head), margin for the hand's thickness; reach; head again
        r = Vector((self.head_r.x + 0.025, self.head_r.y + 0.03, self.head_r.z + 0.02))

        def out_of_head(t):
            d = head_q.inverted() @ (t - head_c)
            e = (d.x / r.x) ** 2 + (d.y / r.y) ** 2 + (d.z / r.z) ** 2
            if e >= 1.0:
                return t
            if d.length < 1e-4:
                d = Vector((0, -1, 0))
            return head_c + head_q @ (d * (1.0 / math.sqrt(max(e, 1e-6))))

        t = out_of_head(t)
        v = t - sh_pose
        L = self.arm_len[s] * 0.985
        if v.length > L:
            t = out_of_head(sh_pose + v.normalized() * L)
        return t

    # ---------------------------------------------------------------- bone helpers
    def _set_pose_matrix(self, pb, M):
        """set a control so its POSE-space matrix becomes M (parents/constraints of its parents honoured)."""
        L = self.arm.convert_space(pose_bone=pb, matrix=M, from_space="POSE", to_space="LOCAL")
        loc, rot, _ = L.decompose()
        pb.location = loc
        prev = self._prev_eul.get(pb.name)
        e = rot.to_euler(pb.rotation_mode, prev) if prev is not None else rot.to_euler(pb.rotation_mode)
        pb.rotation_euler = e
        self._prev_eul[pb.name] = e.copy()

    def _rest3(self, pb):
        return pb.bone.matrix_local.to_3x3()

    def _set_rot_char(self, pb, q):
        """rotation q (armature axes) about the bone's own pivot, relative to its rest orientation."""
        R = self._rest3(pb).to_quaternion()
        b = R.inverted() @ q @ R
        prev = self._prev_eul.get(pb.name)
        e = b.to_euler(pb.rotation_mode, prev) if prev is not None else b.to_euler(pb.rotation_mode)
        pb.rotation_euler = e
        self._prev_eul[pb.name] = e.copy()

    def _pose_head(self, pb):
        return pb.head.copy()

    # ---------------------------------------------------------------- per-frame application
    def apply(self, pose, face_ch=None, gaze=None):
        """pose: acting.pose_at() dict. face_ch: {channel: value}. gaze: (yaw, pitch) head-relative degrees."""
        arm = self.arm
        # 1. torso / chest / neck / head
        d = Vector(pose["hips"]) * self.k_leg
        # >>> hands/contact: seat the pelvis on an anchor (bench / deck) for Jay's real proportions
        hw, hp = self._anchor_mix(pose.get("anchorHips"), d=d)
        if hw > 0:
            d = d.lerp(hp + Vector((0, 0, self.seat_h)) - self.rest_torso, hw)
        # <<< hands/contact
        q_h = _q_char(*pose["hipsRot"])
        R0 = self._rest3(self.torso).to_4x4()
        self._set_pose_matrix(self.torso, Matrix.Translation(self.rest_torso + d) @ q_h.to_matrix().to_4x4() @ R0)
        self._set_rot_char(self.chest, _q_char(*pose["chest"]))
        hd = pose["head"]
        if self.neck:
            self._set_rot_char(self.neck, _q_char(hd[0] * 0.4, hd[1] * 0.4, hd[2] * 0.4))
            self._set_rot_char(self.head, _q_char(hd[0] * 0.6, hd[1] * 0.6, hd[2] * 0.6))
        else:
            self._set_rot_char(self.head, _q_char(*hd))
        # provisional limb targets so pass-1 has sane IK
        for s in SIDES:
            self.wrist[s].location = (0, 0, 0)
        # feet + knees first (knee anchors for the hands need the legs solved)
        bpy.context.view_layer.update()
        fwd_of = {}
        for s in SIDES:
            # feet: relative to rest, leg-length ratio; planted flat (never under the deck), toes a little out,
            # heel rolling up over the ball only when the shin leans past the ankle's dorsiflexion limit
            fa = Vector(pose["foot" + s]) - Vector(ACT_STAND["foot" + s])
            ft = self.rest_foot[s] + fa * self.k_leg
            M_f, fwd_of[s] = self._plant_foot(s, ft, pose)
            self._set_pose_matrix(self.foot[s], M_f)
        bpy.context.view_layer.update()
        for s in SIDES:
            if self.toes.get(s) is not None and s in self._toe_m:
                self._set_pose_matrix(self.toes[s], self._toe_m[s])
        bpy.context.view_layer.update()
        for s in SIDES:
            ft = self.foot[s].matrix.to_translation()
            # knee pole: perpendicular to hip->ankle, biased toward where the toes point + up (knee over the toes)
            hip = self.thigh[s].head.copy()
            dd = ft - hip
            v = self._knee_dir(s, hip, ft, self._knee_fwd.get(s, fwd_of[s]))
            kp = (hip + ft) * 0.5 + v * max(0.25, dd.length)
            self._set_pose_matrix(self.lpole[s], Matrix.Translation(kp) @ self._rest3(self.lpole[s]).to_4x4())
        bpy.context.view_layer.update()
        # 2. limb targets from the posed body
        hq = (self.headdef.matrix.to_quaternion() @ self.headdef.bone.matrix_local.to_quaternion().inverted())
        head_c = self.headdef.matrix @ (self.headdef.bone.matrix_local.inverted() @ self.head_c)
        self._hq = hq
        spine_a = self.torso.head.copy()
        spine_b = Vector((0, 0, 0))
        n = 0
        for s in SIDES:
            spine_b += self.upper[s].head
            n += 1
        spine_b /= n
        hand_t = {}
        for s in SIDES:
            sh_pose = self.upper[s].head.copy()
            t = self.map_point(pose["hand" + s])
            t = self._clear_hand(t, s, sh_pose, head_c, hq, spine_a, spine_b)
            # >>> hands/contact: anchored hands (provisional orientation: forearm ~ shoulder->target)
            t_free = t.copy()
            hand_t[s] = t_free
            t, q_t = self._hand_target(pose, s, t_free, sh_pose, None)
            # <<< hands/contact
            # elbow pole: the acting pole direction, re-anchored between Jay's shoulder and wrist
            sh_act = Vector((ACT_SHOULDER_X if s == "L" else -ACT_SHOULDER_X, 0.0, ACT_LM["shoulder"]))
            hand_act = Vector(pose["hand" + s])
            pd = Vector(pose["pole" + s]) - (sh_act + hand_act) * 0.5
            ax = (t - sh_pose)
            if ax.length > 1e-5:
                an = ax.normalized()
                pd = pd - an * pd.dot(an)
            if pd.length < 1e-4:
                pd = Vector((1 if s == "L" else -1, 0.6, -0.3))
            # >>> hands/contact: the rig's wrist only bends so far off the forearm, so an authored finger direction
            # is delivered by the ARM: put the elbow where the forearm points along the fingers (elbow ~ wrist - F*L)
            wd = self._dirw.get(s, 0.0)
            if wd > 1e-3 and ax.length > 1e-5:
                F_t = q_t @ self.hand_rest[s][0]
                e_star = t - F_t * self.fore[s].bone.length
                pd2 = e_star - (sh_pose + t) * 0.5
                pd2 = pd2 - an * pd2.dot(an)
                if pd2.length > 1e-4:
                    pd = pd.normalized().lerp(pd2.normalized(), wd)
                    if pd.length < 1e-4:
                        pd = pd2
            # <<< hands/contact
            pole = (sh_pose + t) * 0.5 + pd.normalized() * (self.arm_len[s] * 0.9)
            Rw = self._rest3(self.wrist[s]).to_4x4()
            self._set_pose_matrix(self.wrist[s], Matrix.Translation(t) @ Rw)
            self._set_pose_matrix(self.apole[s], Matrix.Translation(pole) @ self._rest3(self.apole[s]).to_4x4())
        # 3. eyes: a real fixation point (look target / held point ahead), converged, clamped to the eye's range
        if self.eyetgt is not None and gaze is not None:
            cen = self.eyecen.matrix @ (self.eyecen.bone.matrix_local.inverted() @ self.eyecen.bone.head_local) if self.eyecen else head_c
            tgt = self._eye_target(gaze, cen, hq)
            self._set_pose_matrix(self.eyetgt, Matrix.Translation(tgt) @ self._rest3(self.eyetgt).to_4x4())
            # vergence: the rig's rest spreads the two eye targets (13 cm at 0.71 m = its 'parallel' look). Pull them
            # in by the real convergence angle for the target distance so both pupils meet on the point.
            k = min(0.6, self.vergence * self.eye_gain[0] * self.eye_dist * (self.ipd * 0.5) / max(0.25, self._eye_dist_real) /
                    max(1e-4, abs(self.eyetgt_lr["L"].bone.head_local.x - self.eyetgt.bone.head_local.x))) if self.eyetgt_lr.get("L") else 0.0
            # nasal cheat: an eye turning towards the nose slides its dot behind the flattened eye shape (reads as a
            # missing pupil on the far eye of a 3/4), so the nasal-turning eye rotates only `nasal_gain` as far.
            ylat = self.eye_dist * math.tan(math.radians(self._eye_yaw * self.eye_gain[0])) * (1.0 - self.nasal_gain)
            for s, b in self.eyetgt_lr.items():
                if b is not None:
                    off = b.bone.head_local - self.eyetgt.bone.head_local
                    d = -off * k
                    if (s == "R" and self._eye_yaw > 0) or (s == "L" and self._eye_yaw < 0):
                        d = d + Vector((-ylat, 0.0, 0.0))
                    b.location = self._rest3(b).inverted() @ d
        # 4. face channels (lids follow the eye pitch actually reached, then the blink closes over them)
        face_ch = face_ch or {}
        if "_blink" in face_ch:
            face_ch = compose_lids(dict(face_ch), self._eye_pitch if gaze is not None else 0.0)
        self.apply_face(face_ch)
        # >>> hands/contact: finger shapes
        for s in SIDES:
            if self.fingers.get(s):
                eul = hand_poses.finger_euler(pose.get("handShape" + s), s)
                for pb in self.fingers[s]:
                    e = eul.get(pb.name)
                    if e is not None:
                        pb.location = (0, 0, 0)
                        pb.rotation_euler = e
        # <<< hands/contact
        bpy.context.view_layer.update()
        # 5. hand orientation: rest hand rotated onto the solved forearm, then the acting handRot, then the authored
        #    palm orientation / the anchor's grip orientation (hands/contact); anchored wrists re-placed for it
        for s in SIDES:
            fo = self.fore[s]
            d_now = (fo.tail - fo.head)
            d_rest = (fo.bone.tail_local - fo.bone.head_local)
            if d_now.length < 1e-6:
                continue
            q_align = d_rest.normalized().rotation_difference(d_now.normalized())
            q = _q_char(*pose["handRot" + s]) @ q_align
            t, q = self._hand_target(pose, s, hand_t[s], self.upper[s].head.copy(), q)
            if t is None:
                t = self.wrist[s].matrix.to_translation()
            M = Matrix.Translation(t) @ q.to_matrix().to_4x4() @ self._rest3(self.wrist[s]).to_4x4()
            self._set_pose_matrix(self.wrist[s], M)

    # ---------------------------------------------------------------- feet (polish_hands_pose)
    def _knee_est(self, s, hip, ankle, fwd, splay=None):
        """analytic 2-bone knee position (thigh/shin rest lengths, knee toward fwd + up)."""
        L1, L2 = self.leg_l[s]
        dv = ankle - hip
        dl = min(max(dv.length, 1e-4), (L1 + L2) * 0.9999)
        dn = dv.normalized() if dv.length > 1e-6 else Vector((0, 0, -1))
        a = (L1 * L1 - L2 * L2 + dl * dl) / (2 * dl)
        h = math.sqrt(max(0.0, L1 * L1 - a * a))
        return hip + dn * a + self._knee_dir(s, hip, ankle, fwd, splay) * h

    def _knee_dir(self, s, hip, ankle, fwd, splay=None):
        """unit knee direction, perpendicular to hip->ankle: toward where the toes point + up, then turned OUT about
        the hip->ankle axis by `splay` rad (hip external rotation; default: the splay _plant_foot chose)."""
        dv = ankle - hip
        dn = dv.normalized() if dv.length > 1e-6 else Vector((0, 0, -1))
        pv = fwd + Vector((0, 0, 0.6))
        pv = pv - dn * pv.dot(dn)
        if pv.length < 1e-5:
            pv = Vector((0, -1, 0))
        e1 = pv.normalized()
        splay = self.knee_splay.get(s, 0.0) if splay is None else splay
        if splay <= 1e-6:
            return e1
        out = Vector((1.0 if s == "L" else -1.0, 0.0, 0.0))
        q = Quaternion(dn, splay)
        if (q @ e1).dot(out) < (q.inverted() @ e1).dot(out):
            q = q.inverted()
        return (q @ e1).normalized()

    def _plant_foot(self, s, ft, pose):
        """(IK-MSTR-Foot pose matrix, toe forward dir) for an ankle target ft: foot flat on the deck (no roll, the
        ankle never below its rest height), yawed with the hips + FOOT_TOE_OUT, and rolled up onto the ball (heel
        up, toes kept flat by self._toe_m) by however much the shin leans forward past ANKLE_DF_MAX."""
        R0 = self._rest3(self.foot[s])
        yaw0 = math.radians(pose["hipsRot"][1] * FOOT_YAW_FOLLOW + (FOOT_TOE_OUT if s == "L" else -FOOT_TOE_OUT))
        ft = ft.copy()
        ft.z = max(ft.z, self.rest_foot[s].z)
        ball_off = self.rest_ball[s] - self.rest_foot[s]
        hip = self.thigh[s].head.copy()
        # a flat foot under a reclined shin (seated on the deck) plantarflexes: open the leg out (hip external
        # rotation: the knee falls out about the hip->ankle line and the foot turns out with it) until the
        # shin->foot angle is back inside ANKLE_PF_MAX of rest; at most TURN_OUT_MAX. Standing / bent-over-the-toes
        # legs never need it (dev >= -ANKLE_PF_MAX at splay 0), so they keep their pose exactly.
        out_sign = 1.0 if s == "L" else -1.0
        Qy0 = Quaternion(Vector((0, 0, 1)), yaw0)
        fwd0 = Qy0 @ Vector((ball_off.x, ball_off.y, 0)).normalized()
        splay = 0.0
        while True:
            Qy = Quaternion(Vector((0, 0, 1)), yaw0 + out_sign * splay * FOOT_SPLAY_FOLLOW)
            fwd = Qy @ Vector((ball_off.x, ball_off.y, 0)).normalized()
            K = self._knee_est(s, hip, ft, fwd0, splay)
            dev = (ft - K).angle(Qy @ ball_off, 0.0) - self.rest_ankle.get(s, 0.0)
            if dev >= -ANKLE_PF_MAX or splay >= TURN_OUT_MAX - 1e-6:
                break
            splay = min(TURN_OUT_MAX, splay + math.radians(2.5))
        self.knee_splay[s] = splay
        self._knee_fwd[s] = fwd0
        ball = ft + Qy @ ball_off
        lat = fwd.cross(Vector((0, 0, 1))).normalized()       # foot's right side
        lift, ankle = 0.0, ft
        for _ in range(4):
            K = self._knee_est(s, hip, ankle, fwd0)
            u = (K - ankle)
            lean = math.atan2(u.dot(fwd), max(1e-5, u.z)) if u.z > 0 else math.pi / 2
            want = max(0.0, min(HEEL_LIFT_MAX, lean - ANKLE_DF_MAX))
            if abs(want - lift) < 1e-3:
                break
            lift = want
            ankle = ball + Quaternion(lat, -lift) @ (ft - ball)    # heel UP over the ball
        Ql = Quaternion(lat, -lift)
        M = Matrix.Translation(ankle) @ (Ql @ Qy).to_matrix().to_4x4() @ R0.to_4x4()
        # toes stay flat on the deck (bend at the ball): their pose = yaw only, pivot at the ball
        if self.toes.get(s) is not None:
            self._toe_m[s] = Matrix.Translation(ball) @ Qy.to_matrix().to_4x4() @ self._rest3(self.toes[s]).to_4x4()
        self.foot_lift[s] = lift
        return M, fwd

    # ---------------------------------------------------------------- hands/contact (polish_hands_pose)
    def set_anchors(self, anchors_world=None, rail_snap=None):
        """anchors_world: {name: {"p": world Vector, "n": palm normal (world, optional), "d": finger dir (optional),
        "kind": 'grip' | 'palm' | 'flat' | 'tip' (optional)}} -> stored in armature space. rail_snap: callable
        (world point) -> (world point, world tangent) | None, for the rail_L / rail_R anchors."""
        bpy.context.view_layer.update()
        Mi = self.arm.matrix_world.inverted()
        R = Mi.to_quaternion()
        self.anchors = {}
        for name, a in (anchors_world or {}).items():
            p = Mi @ Vector(a["p"])
            nn = (R @ Vector(a["n"])).normalized() if a.get("n") is not None else None
            dd = (R @ Vector(a["d"])).normalized() if a.get("d") is not None else None
            self.anchors[name] = (p, nn, dd, a.get("kind"))
        self.rail_snap = rail_snap

    def _anchor(self, name, s=None, t_free=None, d=None):
        """(p, n, d, kind) in armature space for a static or body anchor, or None when it does not exist here."""
        if name in self.anchors:
            return self.anchors[name]
        hq = getattr(self, "_hq", Quaternion())
        if name in ("knee_L", "knee_R"):
            sh = self.shin.get(name[-1])
            if sh is None:
                return None
            # on top of the knee cap, a touch forward: the palm rests there
            p = sh.head + Vector((0, -0.25 * self.thigh_r, self.thigh_r * 1.15))
            return (p, None, None, "palm")
        if name.startswith("mouth") and self.mouth is not None:
            m = self.mouth.head.copy()
            off = {"mouth": Vector((0, -0.016, -0.004)), "mouth_palm": Vector((0, -0.03, 0.0)),
                   "mouth_radio": Vector((0.0, -0.065, -0.058))}.get(name)
            if off is None:
                return None
            kind = {"mouth": "tip", "mouth_palm": "palm", "mouth_radio": "flat"}[name]
            return (m + hq @ off, None, None, kind)
        if name in ("seat_L", "seat_R") and "bench_seat" in self.anchors:
            p = self.anchors["bench_seat"][0] + Vector((0.16 if name[-1] == "L" else -0.16, 0.03, 0.0))
            return (p, Vector((0, 0, -1)), Vector((0.3 if name[-1] == "L" else -0.3, -1, 0)).normalized(), "palm")
        if name == "floor" and d is not None:
            p = self.rest_torso + d
            return (Vector((p.x, p.y, 0.0)), None, None, None)
        if name in ("rail_L", "rail_R") and self.rail_snap is not None and t_free is not None:
            Mw = self.arm.matrix_world
            hit = self.rail_snap(Mw @ t_free)
            if hit is None:
                return None
            Mi = Mw.inverted()
            p = Mi @ Vector(hit[0])
            tan = (Mi.to_quaternion() @ Vector(hit[1])).normalized()
            out = p - self.upper[name[-1]].head
            out.z = 0
            out = out - tan * out.dot(tan)
            dd = out.normalized() if out.length > 1e-5 else Vector((0, -1, 0))
            return (p, Vector((0, 0, -1)), dd, "grip")
        return None

    def _anchor_mix(self, weights, s=None, t_free=None, d=None):
        """weighted anchor blend -> (weight, point) (weight 0 when none of the named anchors exist)."""
        W, P = 0.0, Vector((0, 0, 0))
        for name, w in (weights or {}).items():
            if w <= 1e-4:
                continue
            a = self._anchor(name, s, t_free, d)
            if a is None:
                continue
            W += w
            P += a[0] * w
        if W <= 1e-6:
            return 0.0, None
        return min(1.0, W), P / W

    def _orient(self, s, n, dvec):
        """rotation (armature space) taking the rest hand onto palm normal n / finger direction dvec."""
        F0, N0, T0 = self.hand_rest[s]
        n = n.normalized()
        dvec = dvec - n * dvec.dot(n)
        if dvec.length < 1e-5:
            dvec = F0 - n * F0.dot(n)
        dvec = dvec.normalized()
        Rt = Matrix((dvec, n, dvec.cross(n))).transposed()
        Rr = Matrix((F0, N0, F0.cross(N0))).transposed()
        return (Rt @ Rr.transposed()).to_quaternion()

    def _wrist_orient(self, s, q_base, n, dvec, max_bend):
        """hand rotation that never breaks the wrist: the fingers continue the forearm (q_base @ F0), bent at most
        max_bend (radians) toward an authored finger direction dvec (None = straight, with a natural ~8 deg relaxed
        flex toward the palm); the palm normal is the target n made perpendicular to the fingers, i.e. the forearm
        TWISTS the palm to face its target instead of the hand folding at the wrist."""
        F0, N0, T0 = self.hand_rest[s]
        Fa = (q_base @ F0).normalized()
        n = Vector(n).normalized()
        if dvec is None or Vector(dvec).length < 1e-5:
            nn = n - Fa * n.dot(Fa)
            Fd = (Fa + nn.normalized() * RELAX_FLEX).normalized() if nn.length > 1e-4 else Fa
        else:
            Fd = Vector(dvec).normalized()
            ang = Fa.angle(Fd, 0.0)
            if ang > max_bend:
                ax = Fa.cross(Fd)
                Fd = (Quaternion(ax.normalized(), max_bend) @ Fa) if ax.length > 1e-6 else Fa
        nn = n - Fd * n.dot(Fd)
        if nn.length < 0.25:          # target along the fingers: keep the forearm's own twist
            nb = q_base @ N0
            nn = nb - Fd * nb.dot(Fd)
        return self._orient(s, nn.normalized(), Fd)

    def _hand_target(self, pose, s, t_free, sh_pose, q_base):
        """(wrist target, hand rotation) for one hand: free target blended toward the anchored contact, rotation
        blended toward the authored palm / anchor orientation. q_base None = provisional (forearm ~ shoulder->target)."""
        F0, N0, T0 = self.hand_rest[s]
        if q_base is None:
            fo = self.fore[s]
            d_rest = (fo.bone.tail_local - fo.bone.head_local).normalized()
            v = t_free - sh_pose
            q_base = d_rest.rotation_difference(v.normalized()) if v.length > 1e-5 else Quaternion()
        q = q_base
        # authored palm orientation (length = weight): wrist = forearm direction + a twist that turns the palm
        # toward the target, plus at most WRIST_BEND of flex/deviation toward an authored finger direction
        pv, fv = Vector(pose.get("palm" + s) or (0, 0, 0)), Vector(pose.get("fing" + s) or (0, 0, 0))
        wp = min(1.0, pv.length)
        if wp > 1e-3:
            q = q.slerp(self._wrist_orient(s, q_base, pv, fv if fv.length > 1e-4 else None, WRIST_BEND), wp)
        # how strongly the finger direction is authored (steers the elbow so the forearm can deliver it)
        self._dirw[s] = min(wp, min(1.0, fv.length)) if fv.length > 1e-4 else 0.0
        # anchors
        W, P, Wn, Nn, Dn, kinds = 0.0, Vector((0, 0, 0)), 0.0, Vector((0, 0, 0)), Vector((0, 0, 0)), {}
        for name, w in (pose.get("anchor" + s) or {}).items():
            if w <= 1e-4:
                continue
            a = self._anchor(name, s, t_free)
            if a is None:
                continue
            W += w
            P += a[0] * w
            if a[1] is not None:
                Wn += w
                Nn += a[1] * w
                Dn += (a[2] if a[2] is not None else q @ F0) * w
            if a[3]:
                kinds[a[3]] = kinds.get(a[3], 0.0) + w
        if W <= 1e-6:
            return t_free, q
        P /= W
        W = min(1.0, W)
        if Wn > 1e-6 and Nn.length > 1e-5:
            q = q.slerp(self._wrist_orient(s, q_base, Nn, Dn, WRIST_BEND_GRIP), min(1.0, Wn))
            self._dirw[s] = max(self._dirw[s], ANCHOR_ELBOW_STEER * min(1.0, Wn))   # elbows stay low on grips
        kind = max(kinds.items(), key=lambda kv: kv[1])[0] if kinds else None
        c = hand_poses.contact_point(pose.get("handShape" + s), kind)
        c_rest = F0 * c[0] + N0 * c[1] + T0 * c[2]
        t_anchor = P - q @ c_rest
        # never past the arm's reach (IK stretch is off): pull the wrist in along the shoulder line
        v = t_anchor - sh_pose
        L = self.arm_len[s] * 0.995
        if v.length > L:
            t_anchor = sh_pose + v.normalized() * L
        return t_free.lerp(t_anchor, W), q

    def apply_face(self, ch):
        # reset all face controls, then accumulate (several channels share a bone)
        acc = {}
        for name, (pb, spec, s) in self.facectl.items():
            _, kind, axis, unit, msign, (lo, hi) = spec
            key = (pb.name, kind if kind != "dpos" else "loc")
            acc.setdefault(key, [pb, [0.0, 0.0, 0.0], [], kind])
            v = ch.get(name, 0.0)
            if not v:
                continue
            sign = msign if s == "R" else 1
            if kind == "scl":
                for i in range(3):
                    acc[key][1][i] += v * unit * axis[i]
                acc[key][2].append((None, lo, hi))
            elif kind == "dpos":
                dv = Vector((0, 0, 0))
                dv[axis] = v * unit * (-1 if (s == "R" and axis == 0) else 1) if s else v * unit
                local = self._rest3(pb).inverted() @ dv
                for i in range(3):
                    acc[key][1][i] += local[i]
                acc[key][2].append((None, lo, hi))
            else:
                acc[key][1][axis] += v * unit * sign
                acc[key][2].append((axis, lo, hi))
        for (bn, kind), (pb, val, lims, _k) in acc.items():
            for axis, lo, hi in lims:
                if axis is None:
                    for i in range(3):
                        val[i] = min(hi, max(lo, val[i]))
                else:
                    val[axis] = min(hi, max(lo, val[axis]))
            if kind == "rot":
                pb.rotation_euler = [math.radians(x) for x in val]
            elif kind == "scl":
                pb.scale = [1.0 + x for x in val]
            else:
                pb.location = val

    # ---------------------------------------------------------------- face timeline
    def face_at(self, f, face_spec, perf, events, extra_blinks, quiet=()):
        """channels + gaze for frame f. The returned ch carries '_blink' (0..1); apply() then lets the lids follow
        the real eye pitch and closes them over whatever they are doing (see compose_lids)."""
        fs = face_spec or {}
        seed = fs.get("seed", perf.get("seed", 1) if perf else 1)
        ch = emotion_channels(f, fs.get("emotion") or [], fs.get("blend", 10))
        _add(ch, face_life(f, seed, fs.get("life", 1.0)))
        # resting lid height (0 = wide awake .. 1 = closed): the upper lid just covers the top of the iris
        relax = fs.get("lids", REST_LIDS)
        for s in SIDES:
            ch[f"lidUp.{s}"] = ch.get(f"lidUp.{s}", 0.0) + relax
            ch[f"pupil.{s}"] = ch.get(f"pupil.{s}", 0.0) + fs.get("pupil", REST_PUPIL)
        # speech
        if events:
            vis = face.visemes_at(f, events, fs.get("speech", 1.0))
            for vn, vw in vis.items():
                _add(ch, VISEME_POSES.get(vn, {}), vw)
        # gaze: base direction (keys) + thought darts + micro-saccades, aimed at the look target when there is one
        base = face.gaze_at(f, fs.get("gaze") or [], seed, micro=False)
        micro = face.gaze_at(f, [], seed)
        dart = _dart_at(f, fs, seed)
        cur_emo = next((k[1] for k in reversed(fs.get("emotion") or []) if f >= k[0]), None)
        scan = (0.0, 0.0) if cur_emo in STARE else _scan_at(f, seed)
        gaze = {"yaw": base[0] + dart[0] + scan[0] + micro[0] * 0.5, "pitch": base[1] + dart[1] + scan[1] + micro[1] * 0.5,
                "point": self.look_point(f, _look_at(f, fs.get("look")))}
        # blinks close fully (whatever the lids were doing), lower lid meets it a little
        b = face.blink_at(f, seed, extra_blinks, quiet=quiet)
        if fs.get("noBlink"):
            b = 0.0
        ch["_blink"] = b
        return ch, gaze

    def look_point(self, f, target):
        """look target -> armature-space point, or None (= hold a fixation point ahead of the head).
        target: 'camera' (self.camera_fn), an object name, or a world-space [x, y, z]."""
        if target in (None, "ahead", ""):
            return None
        w = None
        if target == "camera":
            if self.camera_fn is None:
                cam = bpy.context.scene.camera
                w = cam.matrix_world.translation.copy() if cam else None
            else:
                w = Vector(self.camera_fn(f))
        elif isinstance(target, str):
            ob = bpy.data.objects.get(target)
            w = ob.matrix_world.translation.copy() if ob else None
        elif isinstance(target, (list, tuple, Vector)) and len(target) == 3:
            w = Vector(target)
        if w is None:
            return None
        return self.arm.matrix_world.inverted() @ w

    def _eye_target(self, gaze, cen, hq):
        """gaze (dict from face_at, or a legacy (yaw, pitch) head-relative tuple) -> armature-space eye target.
        Without a look point the eyes hold a fixation point ~1.6 m ahead while the head moves inside fix_hold (VOR),
        then pop to the new point (a 1-frame saccade, led a few frames into the head move)."""
        if not isinstance(gaze, dict):
            gaze = {"yaw": gaze[0] * self.gaze_gain[0], "pitch": gaze[1] * self.gaze_gain[1], "point": None, "legacy": True}
        hqi = hq.inverted()
        dist = max(0.3, self.eye_dist)

        def ang(d):
            d = hqi @ d
            return math.degrees(math.atan2(d.x, -d.y)), math.degrees(math.atan2(d.z, math.hypot(d.x, d.y)))

        def vec(yaw, pitch):
            return Quaternion((0, 0, 1), math.radians(yaw)) @ Quaternion((1, 0, 0), math.radians(-pitch)) @ Vector((0, -1, 0))

        point = gaze.get("point")
        if point is not None:
            d = point - cen
            by, bp = ang(d)
            if abs(by) > self.eye_limit[0] * 1.7 or abs(bp) > self.eye_limit[1] * 1.9:
                point = None                      # target behind / far off-axis: the head is not facing it
            else:
                dist = max(0.3, d.length)
        if point is None:
            if gaze.get("legacy"):
                by, bp = 0.0, 0.0
            else:
                head_pt = cen + hq @ (vec(0, 0) * 1.6)
                if self._fix is None or self._fix_frame is None:
                    self._fix = head_pt
                else:
                    a = (self._fix - cen).angle(head_pt - cen, 0.0)
                    if math.degrees(a) > self.fix_hold:
                        lead = head_pt + (head_pt - self._last_head_pt) * 3.0 if self._last_head_pt is not None else head_pt
                        self._fix = lead
                self._last_head_pt = head_pt
                self._fix_frame = True
                by, bp = ang(self._fix - cen)
                dist = 1.6
        yaw = max(-self.eye_limit[0], min(self.eye_limit[0], by + gaze.get("yaw", 0.0)))
        pitch = max(-self.eye_limit[1], min(self.eye_limit[1], bp + gaze.get("pitch", 0.0)))
        self._eye_pitch, self._eye_yaw = pitch, yaw
        self._eye_dist_real = dist
        if gaze.get("legacy"):
            return cen + hq @ (vec(yaw, pitch) * self.eye_dist)
        # visual angle -> rig angle: the pupil dot rides a lattice-flattened eye on a deep pivot, so it reads ~2x the
        # bone rotation; the master target stays at the rig's own distance (its rest spread is calibrated there)
        if self.debug_eyes:
            print(f"EYES want yaw {by:.1f} pitch {bp:.1f} -> {yaw:.1f} {pitch:.1f} point {point is not None}")
        return cen + hq @ (vec(yaw * self.eye_gain[0], pitch * self.eye_gain[1]) * self.eye_dist)

    def static_face(self, spec, f=0):
        """one held expression for sheets/tests: spec = {"emotion": [[f, name, amt]], "blinkNow": 0..1,
        "gazeOffset": (yaw, pitch), "look": target (default 'camera'), "lids": rest}. -> (ch, gaze)"""
        ch = emotion_channels(f, spec.get("emotion") or [], 1)
        for s in SIDES:
            ch[f"lidUp.{s}"] = ch.get(f"lidUp.{s}", 0.0) + spec.get("lids", REST_LIDS)
            ch[f"pupil.{s}"] = ch.get(f"pupil.{s}", 0.0) + spec.get("pupil", REST_PUPIL)
        ch["_blink"] = spec.get("blinkNow", 0.0)
        g = spec.get("gazeOffset", (0.0, 0.0))
        return ch, {"yaw": g[0], "pitch": g[1], "point": self.look_point(f, spec.get("look", "camera"))}

    # ---------------------------------------------------------------- bake
    def bake(self, perf, *args, face=None, step=1):
        """bake(perf, f0, f1)  |  bake(perf, face_spec, f0, f1)  -> {bone name: [keyed data paths]}"""
        if len(args) == 3:
            face_spec, f0, f1 = args
        elif len(args) == 2:
            f0, f1 = args
            face_spec = face
        else:
            raise TypeError("bake(perf, [face], f0, f1)")
        perf = perf or {"stance": [[-10000, "stand"]]}
        fs = face_spec or {}
        arm = self.arm
        if arm.animation_data is None:
            arm.animation_data_create()
        arm.animation_data.action = bpy.data.actions.new(f"{arm.name}_perf")
        events = face_mod_viseme(fs)
        extra = list(fs.get("blinks") or [])
        gk = fs.get("gaze") or []
        for i in range(1, len(gk)):           # blink-on-saccade for big gaze shifts
            if abs(gk[i][1] - gk[i - 1][1]) + abs(gk[i][2] - gk[i - 1][2]) > 20:
                extra.append(gk[i][0])
        for v in (perf.get("verbs") or []):  # flinch / sneeze punctuation
            if v.get("verb") in ("flinch", "shake_head"):
                extra.append(v["at"])
        fs = turn_then_change(sync_sneeze(fs, perf), perf, f0, f1)
        ev_blinks, quiet = thought_blinks(fs, perf, f0, f1)
        extra += ev_blinks
        ctr = self._controls()
        scl = {v[0].name for v in self.facectl.values() if v[1][1] == "scl"}
        keyed = {}
        self._prev_eul = {}
        self._fix = self._fix_frame = self._last_head_pt = None
        bpy.context.view_layer.update()          # holder placement -> arm.matrix_world (look targets are world space)
        for f in range(int(f0), int(f1) + 1, step):
            ch, gaze = self.face_at(f, fs, perf, events, extra, quiet)
            self.apply(acting.pose_at(f, perf), ch, gaze)
            for pb in ctr:
                pb.keyframe_insert("location", frame=f)
                pb.keyframe_insert("rotation_euler", frame=f)
                if pb.name in scl:
                    pb.keyframe_insert("scale", frame=f)
        for pb in ctr:
            keyed[pb.name] = ["location", "rotation_euler"] + (["scale"] if pb.name in scl else [])
        return keyed


def lid_follow(ch, pitch):
    """upper lids ride the eye pitch: down-gaze lowers them, up-gaze lifts the eye ring; lower lids drop a
    touch on down-gaze. Modifies + returns ch."""
    for s in SIDES:
        # up-gaze lifts the lid only about as far as the iris rises, so the lid line still covers the iris top
        # (measured on B12 close-ups: the old 0.014 / 0.03 gains bared the sclera above the iris = 'crazy stare')
        ch[f"lidUp.{s}"] = ch.get(f"lidUp.{s}", 0.0) - pitch * (0.014 if pitch < 0 else 0.006)
        if pitch > 0:
            ch[f"eyeWide.{s}"] = ch.get(f"eyeWide.{s}", 0.0) + pitch * 0.008
        else:
            ch[f"lidLo.{s}"] = ch.get(f"lidLo.{s}", 0.0) + pitch * 0.01
    return ch


def compose_lids(ch, eye_pitch):
    """lids ride the real eye pitch, then the blink ('_blink' 0..1) closes over whatever they were doing."""
    b = ch.pop("_blink", 0.0)
    lid_follow(ch, eye_pitch)
    for s in SIDES:
        u = min(1.0, max(-0.4, ch.get(f"lidUp.{s}", 0.0)))
        ch[f"lidUp.{s}"] = u + (1.0 - u) * b
        ch[f"lidLo.{s}"] = ch.get(f"lidLo.{s}", 0.0) * (1 - b) + 0.22 * b
        ch[f"eyeWide.{s}"] = ch.get(f"eyeWide.{s}", 0.0) * (1 - b)
        ch[f"eyeBig.{s}"] = ch.get(f"eyeBig.{s}", 0.0) * (1 - b)
    return ch


def _emotion_pose(k):
    amt = k[2] if len(k) > 2 else 1.0
    pose = FACE_POSES.get(k[1])
    if pose is None:
        pose = channels_from_arkit(face.EMOTIONS.get(k[1], {}))
    return {n: v * amt for n, v in pose.items()}


def _crossfade(f, keys, blend):
    cur = {}
    for i, k in enumerate(keys or []):
        if f < k[0]:
            break
        tgt = _emotion_pose(k)
        # the first key is the state the shot opens in (mid-performance), not a fade-in from a blank face
        t = 1.0 if i == 0 else face._smooth((f - k[0]) / max(1, blend))
        names = set(cur) | set(tgt)
        cur = {n: cur.get(n, 0) + (tgt.get(n, 0) - cur.get(n, 0)) * t for n in names}
    return cur


# OVERLAP: brows lead an expression change, lids follow 1 frame later, cheeks/nose 2, the mouth 3-4 frames later
OVERLAP = (("brow", 0), ("lid", 1), ("eyeWide", 1), ("eyeBig", 1), ("pupil", 2), ("cheek", 2), ("sneer", 2))
MOUTH_LAG = 4


def _lag(ch):
    base = ch.split(".")[0]
    for pre, d in OVERLAP:
        if base.startswith(pre):
            return d
    return MOUTH_LAG


def emotion_channels(f, keys, blend=10, overlap=True):
    """face.emotion_at's eased cross-fade over the FACE_POSES library, with OVERLAP (each feature group crosses at
    its own lag) and ANTICIPATION (brows + lids dip ~20% against the coming change over the 5 frames before it)."""
    if not overlap or not keys:
        return _crossfade(f, keys, blend)
    by_lag = {}
    out = {}
    names = set()
    for k in keys:
        names |= set(_emotion_pose(k))
    for n in names:
        d = _lag(n)
        if d not in by_lag:
            fd = max(f - d, keys[0][0]) if f >= keys[0][0] else f - d   # lag only delays changes, not the opening state
            by_lag[d] = _crossfade(fd, keys, blend)
        out[n] = by_lag[d].get(n, 0.0)
    for i, k in enumerate(keys):
        u = f - (k[0] - 5)
        if i == 0 or u < 0 or u > 6:
            continue
        bump = math.sin(math.pi * u / 6.0)
        prev, tgt = _crossfade(k[0] - 1, keys, blend), _emotion_pose(k)
        for n in tgt.keys() | prev.keys():
            if n.startswith(("brow", "lid", "eyeWide")):
                out[n] = out.get(n, 0.0) - 0.2 * (tgt.get(n, 0.0) - prev.get(n, 0.0)) * bump
    return out


def _wave(f, seed, period, salt):
    """smooth deterministic noise in -1..1 (two incommensurate sines with hashed phases)."""
    p1 = face._hash(seed * 1.7 + salt) * 6.283
    p2 = face._hash(seed * 2.9 + salt * 3.1) * 6.283
    return 0.65 * math.sin(f * 6.283 / period + p1) + 0.35 * math.sin(f * 6.283 / (period * 0.61) + p2)


def face_life(f, seed=1, amount=1.0):
    """LIFE layer: the face is never a held mask. Brow micro-drift, lid tension, mouth-corner shifts (L/R apart),
    nostril + cheek + jaw breathing (~3.3 s cycle). Small channel offsets, pure function of the frame."""
    if amount <= 0:
        return {}
    ch = {}
    breath = 0.5 + 0.5 * math.sin(f * 6.283 / 100.0 + face._hash(seed) * 6.283)
    for i, s in enumerate(SIDES):
        # amplitudes in channel units, sized on 540x960 close-ups: ~1.5-2 mm of brow / corner travel = visible life,
        # well under any expression change. L/R use different phases so the face never moves as a mirrored mask.
        ch[f"browUp.{s}"] = 0.13 * _wave(f, seed, 83, 1 + i * 0.3) + 0.05 * _wave(f, seed, 37, 7 + i)
        ch[f"browInUp.{s}"] = 0.10 * _wave(f, seed, 97, 29 + i * 0.4)
        ch[f"browIn.{s}"] = 0.07 * _wave(f, seed, 61, 3)
        ch[f"lidLo.{s}"] = 0.08 * _wave(f, seed, 71, 11 + i * 0.2)
        ch[f"lidUp.{s}"] = 0.04 * _wave(f, seed, 53, 13)
        ch[f"cornerUp.{s}"] = 0.10 * _wave(f, seed, 67, 17 + i * 5)
        ch[f"cornerWide.{s}"] = 0.07 * _wave(f, seed, 91, 19 + i * 3)
        ch[f"sneer.{s}"] = 0.18 * breath
        ch[f"cheek.{s}"] = 0.07 * breath
    ch["jaw"] = 0.02 * breath
    ch["loLip"] = 0.06 * _wave(f, seed, 79, 31)
    ch["mouthSide"] = 0.08 * _wave(f, seed, 113, 23)
    return {k: v * amount for k, v in ch.items()}


def _scan_at(f, seed):
    """conversational saccades: a new fixation spot every 0.5-2 s (15-60 f), 1-3 deg off the target (e.g. between
    the viewer's two eyes / across the object). Step function: the eyes pop."""
    t, i, cur = -60, 0, (0.0, 0.0)
    while True:
        h = face._hash(i * 2.13 + seed * 0.71)
        nxt = t + int(15 + 45 * h)
        if nxt > f:
            break
        t = nxt
        i += 1
        a, b = face._hash(i * 5.3 + seed), face._hash(i * 7.9 + seed * 1.3)
        cur = ((a - 0.5) * 5.0, (b - 0.5) * 2.4)
    return cur


STARE = ("shock", "fear", "panic")            # no darts, spontaneous blinks withheld for ~2 s after the onset
EYES_SHUT = ("sneeze", "sneeze_build")


def _look_at(f, look):
    """face_spec 'look': a target, or keys [[frame, target], ...] (target 'camera' | object name | [x,y,z] | 'ahead')."""
    if isinstance(look, list) and look and isinstance(look[0], list) and len(look[0]) == 2 and not isinstance(look[0][0], float):
        cur = None
        for kf, tgt in look:
            if f >= kf:
                cur = tgt
        return cur
    return look


def _dart_at(f, fs, seed):
    """thought darts: on every emotion change (and fs['darts'] frames) the eyes flick 2-3 small saccades
    (3-5 deg, 6-8 frames apart) and settle back - the 'deciding' beat. Step function = the eyes pop."""
    starts = [k[0] - 4 for i, k in enumerate(fs.get("emotion") or []) if i > 0 and k[1] not in STARE + EYES_SHUT]  # eyes lead
    starts += list(fs.get("darts") or [])
    y = p = 0.0
    for i, s0 in enumerate(starts):
        d = f - s0
        if d < 1 or d > 22:
            continue
        h = face._hash(s0 * 0.37 + seed * 3.1)
        sx = 1 if h > 0.5 else -1
        if d < 8:
            y, p = sx * (3.0 + 2.0 * h), 1.2
        elif d < 15:
            y, p = -sx * (2.5 + 1.5 * h), -0.6
        else:
            y, p = sx * 0.8, 0.0
    return y, p


def _head_track(perf, f0, f1):
    def ang(f):
        p = acting.pose_at(f, perf)
        return (p["hipsRot"][1] + p["chest"][1] + p["head"][1], p["hipsRot"][0] + p["chest"][0] + p["head"][0])
    return {f: ang(f) for f in range(int(f0) - 2, int(f1) + 40)}


# ---- canon CAN-P1 timing helpers (Animation Mentor: expression changes get lost in movement) ---------------------
TURN_SPEED = 1.2          # deg/frame of head yaw (+0.6 x pitch) above which the head counts as turning
TURN_SETTLE = 3           # frames the head rests after a turn before the new expression starts to land


def head_turns(perf, f0, f1, speed=TURN_SPEED, min_len=3):
    """[(start, end)] frame windows where the head (hips + chest + head yaw/pitch of acting.pose_at) is turning.
    Use it in the director / acting pass to see where an expression change must NOT be keyed."""
    if not perf:
        return []
    tr = _head_track(perf, f0, f1)
    out, s0 = [], None
    for f in range(int(f0) - 1, int(f1) + 38):
        a, b = tr.get(f - 1), tr.get(f + 1)
        mv = a is not None and b is not None and (abs(b[0] - a[0]) + 0.6 * abs(b[1] - a[1])) / 2.0 > speed
        if mv and s0 is None:
            s0 = f
        elif not mv and s0 is not None:
            if f - s0 >= min_len:
                out.append((s0, f - 1))
            s0 = None
    if s0 is not None:
        out.append((s0, int(f1) + 37))
    return out


def settle_frame(perf, f, f0=None, f1=None, settle=TURN_SETTLE, ramp=10, turns=None, max_delay=20):
    """first frame >= f where an expression change of `ramp` frames can start without overlapping a head turn:
    inside a turn -> `settle` frames after it ends; a turn starting during the ramp -> also after that turn.
    Never drifts more than `max_delay` frames: past that it takes the stillest head frame within reach.
    e.g. face key [settle_frame(perf, 812), "determined"] in a shot builder."""
    turns = head_turns(perf, f - 40 if f0 is None else f0, f + 80 if f1 is None else f1) if turns is None else turns
    f = want = int(f)
    for _ in range(8):
        hit = next(((s, e) for s, e in turns if s - 1 <= f + ramp * 0.6 and e + settle > f), None)
        if hit is None or hit[0] - 1 > f + ramp * 0.6:
            break
        f = hit[1] + settle
    if f - want > max_delay:
        # a long move (head shake, run of small turns) would drift the beat away. If the change can be COMPLETE just
        # before the move starts (<= 10 frames earlier), land it there: the thought shows, then he moves. Otherwise
        # take the frame whose cross-fade window has the stillest head.
        first = next(((s0, e) for s0, e in turns if s0 - 1 <= want + ramp * 0.6 and e + settle > want), None)
        early = first[0] - 2 - int(math.ceil(ramp * 0.6)) if first else None
        if early is not None and 0 <= want - early <= 10:
            return early
        win = int(math.ceil(ramp * 0.6))
        tr = _head_track(perf, want - 2, want + max_delay + win + 2)

        def spd(g):
            return sum(abs(tr[h + 1][0] - tr[h - 1][0]) + 0.6 * abs(tr[h + 1][1] - tr[h - 1][1]) for h in range(g, g + win + 1))
        f = min(range(want, want + max_delay + 1), key=lambda g: (round(spd(g), 1), g))
    return f


def turn_then_change(fs, perf, f0, f1, speed=TURN_SPEED, settle=None):
    """canon CAN-P1 (Animation Mentor): an expression change never lands during a head turn - he turns, settles,
    then the thought reaches the face. Emotion keys that fall in (or whose cross-fade would run into) a head turn
    wait until `settle` frames (face_spec 'turnSettle', default TURN_SETTLE) after it ends. Startle reactions (STARE)
    and eyes-shut beats stay on their frame (the reaction IS the move). Opt out: face_spec 'turnThenChange': false.
    Returns a new face_spec (keys stay ordered; a delayed key never jumps past the next one)."""
    keys = fs.get("emotion") or []
    if not perf or len(keys) < 2 or fs.get("turnThenChange") is False:
        return fs
    settle = fs.get("turnSettle", TURN_SETTLE) if settle is None else settle
    turns = head_turns(perf, f0, f1, speed)
    if not turns:
        return fs
    ramp = fs.get("blend", 10)
    out = []
    for i, k in enumerate(keys):
        k = list(k)
        if i > 0 and k[1] not in STARE + EYES_SHUT:
            nf = settle_frame(perf, k[0], f0, f1, settle, ramp, turns)
            if i + 1 < len(keys):
                nf = min(nf, int(keys[i + 1][0]) - 2)
            k[0] = max(int(out[-1][0]) + 2, nf)       # may move earlier (completed before a long move), never past the previous key
        out.append(k)
    return dict(fs, emotion=out)


def sync_sneeze(fs, perf):
    """the 'sneeze' face lands with the body's CHOO (acting verb 'sneeze' jerks forward at 70% of its dur): the face
    key starts 6 frames before it so the squeeze peaks on the jerk; a 'sneeze_build' key before it stays."""
    keys = fs.get("emotion") or []
    v = next((v for v in (perf or {}).get("verbs") or [] if v.get("verb") == "sneeze"), None)
    if v is None or not any(k[1] == "sneeze" for k in keys):
        return fs
    choo = int(v["at"] + v.get("dur", 24) * 0.7)
    out = [list(k) for k in keys]
    for i, k in enumerate(out):
        if k[1] == "sneeze":
            k[0] = choo - 6
            for k2 in out[i + 1:]:                 # keep the following keys after it
                k2[0] = max(k2[0], k[0] + 8)
    return dict(fs, emotion=out)


def thought_blinks(fs, perf, f0, f1):
    """(extra blink frames, quiet ranges): a blink just before each thought change (a 'blink take' into shock),
    blinks on head turns (eyes + lids lead the turn), and no spontaneous blinks while staring in shock/fear."""
    out, quiet = [], []
    keys = fs.get("emotion") or []
    for i, k in enumerate(keys):
        if k[1] in EYES_SHUT:
            continue
        if i > 0 or k[0] > f0 + 4:
            out.append(k[0] - 1)
        if k[1] in STARE:
            quiet.append((k[0] + 4, k[0] + 64))
    last = -100
    if perf:
        def ang(f):
            p = acting.pose_at(f, perf)
            return (p["hipsRot"][1] + p["chest"][1] + p["head"][1], p["hipsRot"][0] + p["chest"][0] + p["head"][0])
        prev = [ang(f) for f in range(int(f0), int(f1) + 6)]
        for i in range(len(prev) - 4):
            dy = abs(prev[i + 4][0] - prev[i][0]) + 0.6 * abs(prev[i + 4][1] - prev[i][1])
            if dy > 7.0 and (i + f0) - last > 18:
                last = i + f0
                out.append(last + 1)
    return out, quiet


def face_mod_viseme(fs):
    words = fs.get("words") or []
    return face.viseme_track(words, fs.get("fps", 30), fs.get("wordsOffset", 0)) if words else []


def bake(arm, perf, face_spec, f0, f1):
    """module-level convenience: build a puppet on `arm` and bake; returns (puppet, keyed controls)."""
    pup = CloudRigPuppet(arm)
    return pup, pup.bake(perf, face_spec, f0, f1)


# ---------------------------------------------------------------- loading a CloudRig .blend
def append_character(path, collection="CH-jay", rig="RIG-jay", link_to=None):
    """Append the character collection from a CloudRig .blend; returns (collection, armature, objects).
    Rig widgets/helpers keep their hidden flags. Name clashes (two Jays) are handled by Blender's suffixes."""
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        if collection not in src.collections:
            raise KeyError(f"{collection} not in {path}")
        dst.collections = [collection]
    coll = dst.collections[0]
    (link_to or bpy.context.scene.collection).children.link(coll)
    objs = list(coll.all_objects)
    arm = next((o for o in objs if o.type == "ARMATURE" and o.name.split(".")[0] == rig), None)
    if arm is None:
        arm = next((o for o in objs if o.type == "ARMATURE" and o.name.startswith("RIG")), None)
    return coll, arm, objs


def prefer_mesh_hair(coll):
    """Blender Studio particle hair is re-attached to the head by a startup script (rigged_particle_hair.py)
    that never runs in a --factory-startup render, so the particle groom stays at rest and floats off when the
    body moves. Render the rigged mesh hair (armature-deformed) instead. Returns the objects switched on."""
    on = []
    for c in [coll, *coll.children_recursive]:
        n = c.name.lower()
        if "hair" in n and "particles" in n:
            c.hide_render = True
            c.hide_viewport = True
        elif "hair" in n and n.split(".")[-1] == "mesh" or n.endswith("hair.mesh"):
            c.hide_render = False
            c.hide_viewport = False
            for o in c.objects:
                o.hide_render = False
                o.hide_viewport = False
                on.append(o.name)
    return on


def set_character_options(arm, options):
    """CloudRig character toggles live as custom props on the 'Properties_Character_*' bone
    (Jay: Glasses, Chain, Hairstyle, Hair Particles, Quality). Unknown keys are ignored."""
    pb = next((b for b in arm.pose.bones if b.name.startswith("Properties_Character")), None)
    done = {}
    if pb is None:
        return done
    for k, v in (options or {}).items():
        if k in pb.keys():
            pb[k] = type(pb[k])(v) if isinstance(pb[k], (int, float)) else v
            done[k] = pb[k]
    arm.update_tag()
    return done


def natural_height(arm):
    """top of the visible meshes above the feet (rest), armature units."""
    bpy.context.view_layer.update()
    inv = arm.matrix_world.inverted()
    zs = []
    for o in arm.children_recursive:
        if o.type == "MESH" and not o.hide_render and o.visible_get():
            M = inv @ o.matrix_world
            zs += [(M @ Vector(c)).z for c in o.bound_box]
    return (max(zs) - min(0.0, min(zs))) if zs else 1.26


BONE_ALIAS = {"handR": "ORG-Wrist.R", "handL": "ORG-Wrist.L", "head": "DEF-Head", "chest": "DEF-Chest"}


def hand_prop_basis(arm, bone_name, p, s_arm=1.0):
    """matrix_basis for a prop spec `p` parented to a CloudRig hand bone (BONE_ALIAS, rest axes at the bone tail):
    known props sit in the palm by hand_poses.PROP_GRIPS unless the spec asks for its raw local/rot with
    "grip": "raw". None = use the spec's raw local/rot. The ONE placement both render_episode.py and pose QC use
    (pose QC placing the raw DEF-Wrist offsets on ORG-Wrist measured a phone the renderer never shows)."""
    if p.get("grip", "auto") != "auto" or p.get("attach") not in ("handR", "handL"):
        return None
    bone = arm.data.bones.get(bone_name)
    g = hand_poses.prop_grip(p.get("prop"), p["attach"][-1], bone.length) if bone else None
    if not g:
        return None
    Mg = Matrix((g[1][0], g[1][1], g[1][2])).transposed().to_4x4()
    Mg.translation = Vector(g[0])
    return Mg @ Matrix.Scale(p.get("scale", 1.0) / s_arm, 4)
