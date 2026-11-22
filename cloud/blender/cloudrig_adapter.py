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
        MSTR-Mouth (side) -> an authored FACE CHANNEL layer; ARKit-52 units are poses over channels
        (ARKIT_UNITS), emotions are face.EMOTIONS mixes of those units (FACE_POSES), blended additively.
  eyes  MSTR-TGT-Eyes is re-placed every frame in front of the head from face.gaze_at() (head-relative
        yaw/pitch with saccades + micro-saccades); upper lids follow gaze pitch; blinks from blink_at().
  mouth face.viseme_track() -> VISEME_POSES over jaw + lip channels.

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
FACE_CTRL = {
    "lidUp":    ("ACT-Eyelid_Upper.{S}", "loc", 1, -0.025, 1, (-0.025, 0.01)),   # 1 = upper lid fully down
    "lidLo":    ("ACT-Eyelid_Lower.{S}", "loc", 1, 0.015, 1, (-0.015, 0.015)),   # 1 = lower lid fully up
    "lidTilt":  ("ACT-Eyelid_Upper.{S}", "rot", 2, 32.0, -1, (-45, 45)),         # + = outer corner down (sad)
    "eyeWide":  ("MSTR-EyeRing_Upper.{S}", "dpos", 2, 0.007, 1, (-0.012, 0.012)),  # + = upper ring up
    "browUp":   ("MSTR-Eyebrow.{S}", "loc", 1, 0.012, 1, (-0.015, 0.02)),
    "browIn":   ("MSTR-Eyebrow.{S}", "rot", 2, 16.0, -1, (-35, 35)),            # + = inner end up / outer down
    "browSq":   ("MSTR-Eyebrow.{S}", "loc", 0, 0.006, -1, (-0.012, 0.012)),      # + = towards the nose
    "cornerUp": ("ACT-MouthCorner.{S}", "loc", 0, 0.03, -1, (-0.03, 0.03)),      # + = smile, - = frown
    "cornerWide": ("ACT-MouthCorner.{S}", "loc", 1, -0.035, 1, (-0.05, 0.02)),  # + = wide, - = squash
    "pucker":   ("CTR-LipCorner.{S}", "loc", 1, 0.008, 1, (-0.01, 0.012)),       # + = corner in
    "cheek":    ("CTR-CheekPuff.{S}", "loc", 1, 0.008, 1, (-0.01, 0.012)),       # + = cheek raised
    "sneer":    ("Nostril.{S}", "loc", 1, 0.004, 1, (-0.006, 0.006)),            # + = nostril up
    "jaw":      ("Jaw", "loc", 2, 0.045, 1, (-0.008, 0.05)),                     # + = open
    "jawFwd":   ("Jaw", "loc", 1, 0.006, 1, (-0.01, 0.01)),
    "upLip":    ("MSTR-Lip_Upper", "loc", 1, -0.004, 1, (-0.008, 0.006)),        # + = upper lip up
    "loLip":    ("MSTR-Lip_Lower", "loc", 1, -0.004, 1, (-0.008, 0.006)),        # + = lower lip down
    "rollUp":   ("ACT-Lip_Upper_Roll", "rot", 0, 30.0, 1, (-60, 60)),            # + = roll in (press)
    "rollLo":   ("ACT-Lip_Lower_Roll", "rot", 0, 30.0, 1, (-60, 60)),
    "mouthSide": ("MSTR-Mouth", "dpos", 0, 0.010, 1, (-0.02, 0.02)),             # + = towards his left
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


# The FACE POSE LIBRARY: one channel pose per emotion (ARKit mix from face.EMOTIONS + stylisation).
FACE_POSES = {name: _add(channels_from_arkit(w), EMOTION_EXTRA.get(name, {})) for name, w in face.EMOTIONS.items()}

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
        # <<< hands/contact
        self._set_ik_mode()
        for pb in self._controls():
            pb.rotation_mode = "XYZ" if pb.rotation_mode == "QUATERNION" else pb.rotation_mode
        self._measure()
        self._prev_eul = {}
        # Jay's flat cartoon eyeballs lose the pupil past ~15 deg of yaw: eye rotation = gaze * gain
        self.gaze_gain = (0.55, 0.75)

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
        out += [v[0] for v in self.facectl.values()]
        for s in SIDES:
            out += self.fingers.get(s, [])
            if self.toes.get(s) is not None:
                out.append(self.toes[s])
        return list(dict.fromkeys(out))

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
        for s in SIDES:
            tb = self.toes.get(s)
            self.rest_ball[s] = h(tb) if tb is not None else self.rest_foot[s] + Vector((0, -0.1, -0.05))
            hp, an = h(self.thigh[s]), self.rest_foot[s]
            kn = h(self.shin[s]) if self.shin.get(s) else (hp + an) * 0.5 + Vector((0, -0.01, 0))
            self.leg_l[s] = ((kn - hp).length, (an - kn).length)
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
            v = fwd_of[s] + Vector((0, 0, 0.6))
            if dd.length > 1e-4:
                dn = dd.normalized()
                v = v - dn * v.dot(dn)
            if v.length < 1e-4:
                v = Vector((0, -1, 0))
            kp = (hip + ft) * 0.5 + v.normalized() * max(0.25, dd.length)
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
        # 3. eyes: target in front of the (posed) head
        if self.eyetgt is not None and gaze is not None:
            yaw, pitch = gaze[0] * self.gaze_gain[0], gaze[1] * self.gaze_gain[1]
            dvec = Quaternion((0, 0, 1), math.radians(yaw)) @ Quaternion((1, 0, 0), math.radians(-pitch)) @ Vector((0, -1, 0))
            cen = self.eyecen.matrix @ (self.eyecen.bone.matrix_local.inverted() @ self.eyecen.bone.head_local) if self.eyecen else head_c
            tgt = cen + hq @ (dvec * self.eye_dist)
            self._set_pose_matrix(self.eyetgt, Matrix.Translation(tgt) @ self._rest3(self.eyetgt).to_4x4())
        # 4. face channels
        self.apply_face(face_ch or {})
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
    def _knee_est(self, s, hip, ankle, fwd):
        """analytic 2-bone knee position (thigh/shin rest lengths, knee toward fwd + up)."""
        L1, L2 = self.leg_l[s]
        dv = ankle - hip
        dl = min(max(dv.length, 1e-4), (L1 + L2) * 0.9999)
        dn = dv.normalized() if dv.length > 1e-6 else Vector((0, 0, -1))
        a = (L1 * L1 - L2 * L2 + dl * dl) / (2 * dl)
        h = math.sqrt(max(0.0, L1 * L1 - a * a))
        pv = fwd + Vector((0, 0, 0.6))
        pv = pv - dn * pv.dot(dn)
        if pv.length < 1e-5:
            pv = Vector((0, -1, 0))
        return hip + dn * a + pv.normalized() * h

    def _plant_foot(self, s, ft, pose):
        """(IK-MSTR-Foot pose matrix, toe forward dir) for an ankle target ft: foot flat on the deck (no roll, the
        ankle never below its rest height), yawed with the hips + FOOT_TOE_OUT, and rolled up onto the ball (heel
        up, toes kept flat by self._toe_m) by however much the shin leans forward past ANKLE_DF_MAX."""
        R0 = self._rest3(self.foot[s])
        yaw = math.radians(pose["hipsRot"][1] * FOOT_YAW_FOLLOW + (FOOT_TOE_OUT if s == "L" else -FOOT_TOE_OUT))
        Qy = Quaternion(Vector((0, 0, 1)), yaw)
        ft = ft.copy()
        ft.z = max(ft.z, self.rest_foot[s].z)
        ball_off = self.rest_ball[s] - self.rest_foot[s]
        ball = ft + Qy @ ball_off
        fwd = Qy @ Vector((ball_off.x, ball_off.y, 0)).normalized()
        lat = fwd.cross(Vector((0, 0, 1))).normalized()       # foot's right side
        hip = self.thigh[s].head.copy()
        lift, ankle = 0.0, ft
        for _ in range(4):
            K = self._knee_est(s, hip, ankle, fwd)
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
            if kind == "dpos":
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
            else:
                pb.location = val

    # ---------------------------------------------------------------- face timeline
    def face_at(self, f, face_spec, perf, events, extra_blinks):
        fs = face_spec or {}
        seed = fs.get("seed", perf.get("seed", 1) if perf else 1)
        w = face.emotion_at(f, fs.get("emotion") or [], fs.get("blend", 10))
        ch = channels_from_arkit(w)
        # emotion stylisation, weighted by the active emotion amounts
        if fs.get("emotion"):
            # recompute the extra layer with the same cross-fade as emotion_at
            cur = {}
            for k in fs["emotion"]:
                if f < k[0]:
                    break
                amt = k[2] if len(k) > 2 else 1.0
                tgt = {n: v * amt for n, v in EMOTION_EXTRA.get(k[1], {}).items()}
                t = face._smooth((f - k[0]) / max(1, fs.get("blend", 10)))
                names = set(cur) | set(tgt)
                cur = {n: cur.get(n, 0) + (tgt.get(n, 0) - cur.get(n, 0)) * t for n in names}
            _add(ch, cur)
        # resting lid height (0 = wide awake .. 1 = closed)
        relax = fs.get("lids", 0.12)
        for s in SIDES:
            ch[f"lidUp.{s}"] = ch.get(f"lidUp.{s}", 0.0) + relax
        # speech
        if events:
            vis = face.visemes_at(f, events, fs.get("speech", 1.0))
            for vn, vw in vis.items():
                _add(ch, VISEME_POSES.get(vn, {}), vw)
        # gaze + lids follow the eye pitch
        gaze = face.gaze_at(f, fs.get("gaze") or [], seed)
        lid_follow(ch, gaze[1])
        # blinks close fully (whatever the lids were doing), lower lid meets it a little
        b = face.blink_at(f, seed, extra_blinks)
        if fs.get("noBlink"):
            b = 0.0
        for s in SIDES:
            u = min(1.0, max(-0.4, ch.get(f"lidUp.{s}", 0.0)))
            ch[f"lidUp.{s}"] = u + (1.0 - u) * b
            ch[f"lidLo.{s}"] = ch.get(f"lidLo.{s}", 0.0) * (1 - b) + 0.22 * b
            ch[f"eyeWide.{s}"] = ch.get(f"eyeWide.{s}", 0.0) * (1 - b)
        return ch, gaze

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
            if v.get("verb") in ("flinch", "sneeze", "shake_head"):
                extra.append(v["at"])
        ctr = self._controls()
        keyed = {}
        self._prev_eul = {}
        for f in range(int(f0), int(f1) + 1, step):
            ch, gaze = self.face_at(f, fs, perf, events, extra)
            self.apply(acting.pose_at(f, perf), ch, gaze)
            for pb in ctr:
                pb.keyframe_insert("location", frame=f)
                pb.keyframe_insert("rotation_euler", frame=f)
        for pb in ctr:
            keyed[pb.name] = ["location", "rotation_euler"]
        return keyed


def lid_follow(ch, pitch):
    """upper lids ride the eye pitch: down-gaze lowers them, up-gaze lifts the eye ring; lower lids drop a
    touch on down-gaze. Modifies + returns ch."""
    for s in SIDES:
        ch[f"lidUp.{s}"] = ch.get(f"lidUp.{s}", 0.0) - pitch * 0.014
        if pitch > 0:
            ch[f"eyeWide.{s}"] = ch.get(f"eyeWide.{s}", 0.0) + pitch * 0.03
        else:
            ch[f"lidLo.{s}"] = ch.get(f"lidLo.{s}", 0.0) + pitch * 0.01
    return ch


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
