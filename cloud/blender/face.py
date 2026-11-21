"""
FACE: the expression + eye engine (ARKit-52 face units on an MPFB/MakeHuman head).

Layers, all pure functions of the frame, baked to shape-key / bone keyframes:
  1. EMOTION   : timed emotion presets (FACS-style ARKit mixes) with eased cross-fades
  2. EYES      : gaze targets with saccades (fast 2-3 frame jumps), micro-saccades, vergence,
                 upper-lid tracking (lids follow eye pitch), asymmetric natural blinks
                 (2 frames close, 4-5 frames open), blink-on-saccade for big gaze shifts
  3. SPEECH    : viseme track from word timings (grapheme -> Microsoft viseme groups) with
                 co-articulation smoothing, jaw driven by the voice envelope
  4. LIFE      : breathing in the nostrils/jaw, brow micro-motion, never a frozen face
Animation principles: holds are never dead (micro-motion), changes are eased with anticipation, the eyes
lead the head (gaze arrives ~4 frames before the head turn), blinks punctuate thought changes.
"""
import math

# ---------------------------------------------------------------- emotion library (ARKit weights 0..1)
EMOTIONS = {
    "neutral":    {},
    "calm":       {"mouthSmileLeft": 0.12, "mouthSmileRight": 0.12, "eyeSquintLeft": 0.1, "eyeSquintRight": 0.1},
    "content":    {"mouthSmileLeft": 0.35, "mouthSmileRight": 0.32, "cheekSquintLeft": 0.2, "cheekSquintRight": 0.2, "eyeSquintLeft": 0.2, "eyeSquintRight": 0.2},
    "concern":    {"browInnerUp": 0.45, "browDownLeft": 0.15, "browDownRight": 0.15, "mouthPressLeft": 0.25, "mouthPressRight": 0.25, "mouthFrownLeft": 0.15, "mouthFrownRight": 0.15},
    "worried":    {"browInnerUp": 0.75, "mouthStretchLeft": 0.2, "mouthStretchRight": 0.2, "mouthFrownLeft": 0.3, "mouthFrownRight": 0.3, "eyeWideLeft": 0.15, "eyeWideRight": 0.15},
    "fear":       {"browInnerUp": 0.9, "browOuterUpLeft": 0.5, "browOuterUpRight": 0.5, "eyeWideLeft": 0.55, "eyeWideRight": 0.55, "mouthStretchLeft": 0.45, "mouthStretchRight": 0.45, "jawOpen": 0.18, "mouthLowerDownLeft": 0.2, "mouthLowerDownRight": 0.2},
    "shock":      {"browInnerUp": 0.8, "browOuterUpLeft": 0.85, "browOuterUpRight": 0.85, "eyeWideLeft": 0.8, "eyeWideRight": 0.8, "jawOpen": 0.4, "mouthFunnel": 0.2},
    "panic":      {"browInnerUp": 1.0, "browOuterUpLeft": 0.6, "browOuterUpRight": 0.6, "eyeWideLeft": 0.6, "eyeWideRight": 0.6, "mouthStretchLeft": 0.6, "mouthStretchRight": 0.6, "jawOpen": 0.3, "noseSneerLeft": 0.15, "noseSneerRight": 0.15},
    "pain":       {"browDownLeft": 0.6, "browDownRight": 0.6, "browInnerUp": 0.4, "eyeSquintLeft": 0.7, "eyeSquintRight": 0.7, "eyeBlinkLeft": 0.35, "eyeBlinkRight": 0.35, "mouthStretchLeft": 0.5, "mouthStretchRight": 0.5, "noseSneerLeft": 0.4, "noseSneerRight": 0.4, "jawOpen": 0.12},
    "determined": {"browDownLeft": 0.55, "browDownRight": 0.55, "eyeSquintLeft": 0.3, "eyeSquintRight": 0.3, "mouthPressLeft": 0.35, "mouthPressRight": 0.35, "jawForward": 0.15},
    "shout":      {"browDownLeft": 0.45, "browDownRight": 0.45, "browInnerUp": 0.3, "eyeSquintLeft": 0.25, "eyeSquintRight": 0.25, "jawOpen": 0.7, "mouthStretchLeft": 0.4, "mouthStretchRight": 0.4, "mouthUpperUpLeft": 0.4, "mouthUpperUpRight": 0.4, "noseSneerLeft": 0.25, "noseSneerRight": 0.25},
    "hopeful":    {"browInnerUp": 0.4, "mouthSmileLeft": 0.15, "mouthSmileRight": 0.12, "eyeWideLeft": 0.1, "eyeWideRight": 0.1},
    "relief":     {"browInnerUp": 0.3, "mouthSmileLeft": 0.3, "mouthSmileRight": 0.3, "eyeSquintLeft": 0.25, "eyeSquintRight": 0.25, "jawOpen": 0.06, "eyeBlinkLeft": 0.15, "eyeBlinkRight": 0.15},
    "sneeze_build": {"browInnerUp": 0.6, "eyeSquintLeft": 0.6, "eyeSquintRight": 0.6, "eyeBlinkLeft": 0.45, "eyeBlinkRight": 0.45, "noseSneerLeft": 0.7, "noseSneerRight": 0.7, "mouthUpperUpLeft": 0.5, "mouthUpperUpRight": 0.5, "jawOpen": 0.25},
    "sneeze":     {"browDownLeft": 0.8, "browDownRight": 0.8, "eyeBlinkLeft": 1.0, "eyeBlinkRight": 1.0, "noseSneerLeft": 0.9, "noseSneerRight": 0.9, "jawOpen": 0.5, "mouthFunnel": 0.3},
    "secret":     {"mouthPucker": 0.55, "mouthFunnel": 0.15, "browInnerUp": 0.3, "eyeSquintLeft": 0.15, "eyeSquintRight": 0.15},
    "wince":      {"browDownLeft": 0.4, "browDownRight": 0.4, "eyeSquintLeft": 0.5, "eyeSquintRight": 0.5, "mouthPressLeft": 0.4, "mouthPressRight": 0.4, "mouthLeft": 0.2},
}


def _smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def emotion_at(f, keys, blend=10):
    """keys: [[frame, 'emotion', intensity?], ...] -> ARKit weight dict, eased cross-fades."""
    if not keys:
        return {}
    cur = {}
    prev = {}
    for i, k in enumerate(keys):
        kf, name = k[0], k[1]
        amt = k[2] if len(k) > 2 else 1.0
        tgt = {n: v * amt for n, v in EMOTIONS.get(name, {}).items()}
        if f < kf:
            break
        t = _smooth((f - kf) / max(1, blend))
        names = set(cur) | set(tgt)
        cur = {n: cur.get(n, 0) + (tgt.get(n, 0) - cur.get(n, 0)) * t for n in names}
    return cur


# ---------------------------------------------------------------- gaze: saccades + blinks
def _hash(n):
    s = math.sin(n * 127.1 + 311.7) * 43758.5453
    return s - math.floor(s)


def gaze_at(f, gaze_keys, seed=1):
    """gaze_keys: [[frame, yaw_deg, pitch_deg]] in head space (+yaw = his left, +pitch = up).
    Returns (yaw, pitch) with saccadic arrival (3 frames) and micro-saccades on holds."""
    yaw, pitch = 0.0, 0.0
    if gaze_keys:
        yaw, pitch = gaze_keys[0][1], gaze_keys[0][2]
        for i in range(1, len(gaze_keys)):
            kf, ky, kp = gaze_keys[i]
            if f >= kf:
                t = min(1.0, (f - kf) / 3.0)          # saccade: ~100 ms
                t = 1 - (1 - t) ** 3
                yaw = yaw + (ky - yaw) * t
                pitch = pitch + (kp - pitch) * t
    # micro-saccades: tiny jumps every 12-30 frames (never a dead stare)
    seg = int((f + seed * 7) / 18)
    jy = (_hash(seg * 3.1 + seed) - 0.5) * 1.6
    jp = (_hash(seg * 5.7 + seed) - 0.5) * 1.0
    return yaw + jy, pitch + jp


def blink_at(f, seed=1, extra=()):
    """Natural blink curve: 0 open .. 1 closed. Close in 2 frames, hold 1, open over 5 (ease-out)."""
    def curve(d):
        if d < 0 or d > 8:
            return 0.0
        if d < 2:
            return (d + 1) / 3.0
        if d < 3:
            return 1.0
        return max(0.0, 1.0 - ((d - 3) / 5.0) ** 0.7)
    v = 0.0
    # spontaneous blinks every 2.5-5.5 s, jittered per blink
    t = -40
    i = 0
    while t < f + 10:
        t += int(75 + _hash(i * 1.37 + seed) * 90)
        v = max(v, curve(f - t))
        i += 1
    for e in extra:                                    # punctuation blinks (thought changes, big saccades)
        v = max(v, curve(f - e))
    return min(1.0, v)


# ---------------------------------------------------------------- speech: words -> visemes
VIS = {  # grapheme groups -> MPFB Microsoft viseme shape keys
    "a": "aa_02", "e": "ey_eh_uh_04", "i": "y_iy_ih_ix_06", "o": "ow_08", "u": "w_uw_07",
    "m": "p_b_m_21", "b": "p_b_m_21", "p": "p_b_m_21", "f": "f_v_18", "v": "f_v_18",
    "t": "d_t_n_19", "d": "d_t_n_19", "n": "d_t_n_19", "l": "l_14", "r": "r_13",
    "s": "s_z_15", "z": "s_z_15", "c": "k_g_ng_20", "k": "k_g_ng_20", "g": "k_g_ng_20", "q": "k_g_ng_20",
    "h": "h_12", "w": "w_uw_07", "y": "y_iy_ih_ix_06", "j": "sh_ch_jh_zh_16", "x": "k_g_ng_20",
}


def viseme_track(words, fps=30, offset=0):
    """words: [{'w','s','e'}] seconds -> list of (frame, viseme, weight) samples (co-articulated)."""
    events = []
    for w in words:
        txt = "".join(ch for ch in w["w"].lower() if ch.isalpha())
        if not txt:
            continue
        f0, f1 = w["s"] * fps + offset, w["e"] * fps + offset
        groups = []
        for ch in txt:
            v = VIS.get(ch)
            if v and (not groups or groups[-1] != v):
                groups.append(v)
        n = max(1, len(groups))
        for i, v in enumerate(groups):
            events.append((f0 + (f1 - f0) * (i + 0.5) / n, v, (f1 - f0) / n))
    return events


def visemes_at(f, events, strength=1.0):
    out = {}
    for c, v, d in events:
        r = max(2.0, d * 0.9)
        x = abs(f - c) / r
        if x < 1.5:
            w = math.exp(-x * x * 2.2) * strength
            out[v] = max(out.get(v, 0), w)
    return out
