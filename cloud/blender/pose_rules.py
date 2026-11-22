"""Pose QC rules (lessons L009 seated lean-back on a blank box, L010 splayed fingers / hands not on props).

Pure Python (no bpy): cloud/blender/test/pose_qc.py measures the baked rig in Blender and calls evaluate() on one
measurement per (shot, frame):

  {"shot", "frame", "stance", "seated": bool, "seat_gap_m": float|None, "spine_pitch_deg": float,
   "finger_curl_deg": {"L": deg, "R": deg}, "hand_shape": {"L": str, "R": str}, "grips": [{"prop", "hand", "dist_m"}],
   "allow_lean_back": bool}

Rules (ids):
  POSE-SEAT    seated: lowest pelvis/buttock skin point within SEAT_TOL of the seat surface under it (no hover, no sinking)
  POSE-SPINE   pelvis->neck pitch inside the stance's range (+ = forward); seated poses upright or forward unless the
               shot allows a lean-back (actor.perf.allow_lean_back)
  POSE-FINGERS mean flexion of index..pinky >= CURL_MIN unless that hand's shape is open_palm (never flat-splayed)
  POSE-GRIP    a prop held in a hand: palm-centre to prop surface <= GRIP_TOL (+ palm half-thickness)
"""

SEAT_TOL = 0.03
CURL_MIN = 20.0
GRIP_TOL = 0.02
PALM_HALF = 0.015
WRIST_MAX = 65.0            # deg between forearm and hand axes
PALM_MAX = 75.0             # deg between the palm normal and the direction to the held prop
FROZEN_MAX_S = 0.5          # longest run with (almost) no face/eye/head motion
FACE_MOTION_MIN = 0.002     # mean per-frame change of the face controls (blinks, saccades, breath, emotion)
# allowed pelvis->neck pitch (deg, + forward) by stance family
SPINE_RANGE = {"stand": (-10.0, 25.0), "helm": (-8.0, 25.0), "brace": (-8.0, 35.0), "sit": (-5.0, 40.0)}
SKIP_SPINE = {"down"}          # thrown onto hands and knees: intentional extreme
OPEN_SHAPES = {"open_palm", "open", "splay_intent"}


def stance_family(stance):
    s = (stance or "stand").lower()
    if s.startswith("sit"):
        return "sit"
    return s if s in SPINE_RANGE or s in SKIP_SPINE else "stand"


def evaluate(m):
    out = []
    fam = stance_family(m.get("stance"))
    ctx = {"shot": m.get("shot"), "frame": m.get("frame"), "stance": m.get("stance")}

    def add(rid, ok, measured, expected, severity="fail"):
        out.append(dict(ctx, rule=rid, status="pass" if ok else severity, measured=measured, expected=expected))
    if m.get("seated") or fam == "sit":
        g = m.get("seat_gap_m")
        add("POSE-SEAT", g is not None and abs(g) <= SEAT_TOL, None if g is None else round(g, 4),
            f"|pelvis skin - seat| <= {SEAT_TOL} m")
    if fam not in SKIP_SPINE and m.get("spine_pitch_deg") is not None:
        lo, hi = SPINE_RANGE[fam]
        if m.get("allow_lean_back"):
            lo = min(lo, -30.0)
        p = m["spine_pitch_deg"]
        add("POSE-SPINE", lo <= p <= hi, round(p, 1), f"{lo}..{hi} deg (+ = forward) for {fam}")
    for side in ("L", "R"):
        c = (m.get("finger_curl_deg") or {}).get(side)
        shape = (m.get("hand_shape") or {}).get(side) or "unset"
        if c is None:
            continue
        if shape in OPEN_SHAPES:
            add(f"POSE-FINGERS.{side}", True, round(c, 1), f"open hand shape '{shape}': curl not required")
        else:
            add(f"POSE-FINGERS.{side}", c >= CURL_MIN, round(c, 1), f"mean finger flexion >= {CURL_MIN} deg (shape {shape})")
    for side, b in (m.get("wrist_bend_deg") or {}).items():
        if b is not None:
            add(f"POSE-WRIST.{side}", b <= WRIST_MAX, round(b, 1), f"forearm->hand bend <= {WRIST_MAX} deg (no broken wrists)")
    for g in m.get("grips") or []:
        if g.get("palm_angle_deg") is not None:
            add(f"POSE-PALM.{g.get('hand')}", g["palm_angle_deg"] <= PALM_MAX, round(g["palm_angle_deg"], 1),
                f"palm normal within {PALM_MAX} deg of the held {g.get('prop')} (palm faces the object)")
    fl = m.get("face_life")
    if fl:
        add("FACE-LIFE", fl["frozen_max_s"] <= FROZEN_MAX_S and fl["motion"] >= FACE_MOTION_MIN,
            {"frozen_max_s": round(fl["frozen_max_s"], 2), "motion": round(fl["motion"], 4)},
            f"no frozen face > {FROZEN_MAX_S} s over the clip; face motion >= {FACE_MOTION_MIN}")
    for g in m.get("grips") or []:
        d = g.get("dist_m")
        add(f"POSE-GRIP.{g.get('hand')}", d is not None and d <= GRIP_TOL + PALM_HALF, None if d is None else round(d, 4),
            f"palm centre -> {g.get('prop')} surface <= {GRIP_TOL + PALM_HALF} m")
    return out


def summarize(findings):
    fails = [f for f in findings if f["status"] == "fail"]
    by = {}
    for f in fails:
        by.setdefault(f["rule"].split(".")[0], []).append(f["shot"])
    return {"checked": len(findings), "failed": len(fails), "ok": not fails,
            "by_rule": {k: sorted(set(v)) for k, v in by.items()}}
