#!/usr/bin/env python3
"""
Shot-language validator for episode.json (PIXAR_RECIPE section 3 C-rules + ENGAGEMENT_RECIPE pacing).

    python3 factory/direction/shot_validator.py episodes/sentinel/episode_v3.json [--out report.json] [--strict]

Everything is computed from the spec itself, with the renderer's own camera maths (camgeo.rig_at, the yacht
transforms, vertical fov): the subject point is projected through the camera on every 3rd frame.

Subject of a shot: direction.subject.track (written by camera_presets) if present, else the first actor's chest
(the hero), else the camera's look point. Shot size = frame height at the subject's depth, normalised to a
1.8 m human (camgeo.SIZE_BOUNDS). Location / sequence: direction.location / direction.sequence if present,
else derived from the yacht state (afloat 'sea' / aground 'reef') and the island placement.

Rules evaluated (status pass | fail | warn | skip):
  C1 CU+ECU <= 25 %            C2 no run > 3 CU-or-tighter        C3 establishing EWS/WS within first 2 shots of a location
  C4 re-establish after <= 6 tighter shots / time jumps            C5 180-degree side per sequence (vs hero facing)
  C7 hero eyes y in [0.30, 0.45] on MCU/CU                         C8 motivated + eased moves
  C9 durations (median 2.0-3.5 s, none < 18 f unless insert, none > 6 s unless long_take)
  C11 eye-trace across cuts <= 0.15 for >= 80 % of cuts            C14 hero CU lens within +-10 mm per sequence
  H1 subject centred |x - 0.5| < 0.08 (POV / insert exempt)       DIST shot-size distribution targets (3.2)
  P1 ASL by section + overall  P6 preset repetition  P7 camera always moving (no static >= 0.8 s)
  COL camera under water / inside the hull    OCC hero hidden behind the hull (ray test)
  CTX story-first framing (island / fires on screen)   LENS lens language (non-CU shots mostly 18-60 mm)
  C6 C10 C12 C13 need gaze / audio / rendered pixels -> skip (reported).
  Craft canon (factory/canon): CAN-C1 a wide holding hero + boat + island/tree line before any coverage per location;
  CAN-C2 hero CUs only on the sequence's reserved_close_up; CAN-H1 impacts: subject escapes 2-12 f, catch-up 2-10 f late.
"""
import argparse
import json
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import camgeo as G  # noqa: E402

TIGHT = {"CU", "ECU"}
FACE_VIS_MAX = 80.0      # polish_camera: deg between the lens and the face normal beyond which the face does not read
FACE_ABOVE_MAX = 40.0    # deg the lens may sit above a lowered face's normal before the cap brim hides it
COL_CLEAR = 0.15        # polish_camera: minimum air (m) between the lens and any yacht surface
WIDE = {"WS", "EWS"}
CENTRE_TOL = 0.08


# ------------------------------------------------------------------ per-shot analysis
def hero_actor(shot):
    acts = shot.get("actors") or []
    return next((a for a in acts if a.get("asset", "").startswith("hero")), acts[0] if acts else None)


def actor_point(shot, a, f, h_frac):
    h = a.get("height", 1.8)
    loc = a["local"]
    return G.YachtFrame(shot.get("yacht"), f).body_to_world([loc[0], loc[1] + h * h_frac, loc[2]])


# >>> polish_camera: the hero's real landmarks (factory/direction/hero_profile_*.json, measured from the rig)
GENERIC_FRAC = {"eye": 1.64 / 1.8, "chest": 1.3 / 1.8, "top": 1.0, "brow": 1.68 / 1.8, "chin": 1.5 / 1.8, "waist": 1.0 / 1.8}


def actor_landmark(shot, a, f, name):
    """world point of a hero landmark: measured performance track > profile stance/rest > generic 1.8 m human."""
    prof = G.hero_profile(a.get("asset"))
    h = a.get("height", 1.8)
    loc = a["local"]
    if prof is not None:
        st = ((a.get("perf") or {}).get("stance") or [[0, None]])[0][1]
        q = prof.local(name, h, shot.get("id"), f, st)
        if q is not None:
            q = G.rot_yv(a.get("rotY", 0.0), q)
            return G.YachtFrame(shot.get("yacht"), f).body_to_world([loc[0] + q[0], loc[1] + q[1], loc[2] + q[2]])
    return actor_point(shot, a, f, GENERIC_FRAC[name])
# <<< polish_camera


def track_at(track, f):
    ks = track
    if f <= ks[0][0]:
        return ks[0][1]
    if f >= ks[-1][0]:
        return ks[-1][1]
    for (a, pa), (b, pb) in zip(ks, ks[1:]):
        if a <= f <= b:
            return G.vlerp(pa, pb, (f - a) / max(1e-9, b - a))
    return ks[-1][1]


# fire positions in island_sentinel.glb (island-local metres at scale 1; measured with Blender from the GLB)
FIRE_LOCAL = [(-1009.4, 5.8, 4172.8), (175.7, 5.8, 4164.2), (-418.7, 5.8, 3243.2), (1331.1, 5.8, 4112.3), (2352.9, 5.8, 3891.4), (3761.8, 5.8, 2296.3)]
COAST = None


def load_coast(root):
    global COAST
    for rel in ("assets/props/island_sentinel_geo.json", "studio/src/data/sentinel_geo.json"):
        p = os.path.join(root, rel)
        if os.path.exists(p):
            COAST = json.load(open(p)).get("coast")
            return


def island_anchors(isl):
    """World points that locate the story: coast (every 6th vertex, 3 m up) and the six fires."""
    if not isl:
        return [], []
    S = isl.get("scale", 1.0)
    out, fires = [], []
    for x, y in (COAST or [])[::6]:
        q = G.rot_yv(isl.get("rotY", 0), [x * 1000 * S, 3.0, y * 1000 * S])
        out.append([q[0] + isl["x"], q[1], q[2] + isl["z"]])
    for fx, fy, fz in FIRE_LOCAL:
        q = G.rot_yv(isl.get("rotY", 0), [fx * S, fy * S + 2.0, fz * S])
        fires.append([q[0] + isl["x"], q[1], q[2] + isl["z"]])
    return out, fires


def in_hull(b):
    """Coarse solid of the yacht (body coords, from yacht.glb's bbox and the deck marks): the hull up to the
    sheer / coaming (~1.9 m), minus the cockpit well the hero stands in (floor 1.42 m)."""
    if not (abs(b[0]) < 2.1 and -7.8 < b[2] < 6.8 and -0.9 < b[1] < 1.9):
        return False
    in_well = abs(b[0]) < 1.3 and -6.4 < b[2] < -2.6 and b[1] > 1.42
    return not in_well


def location_of(shot):
    d = shot.get("direction") or {}
    if d.get("location"):
        return d["location"]
    y = shot.get("yacht")
    isl = shot.get("island") or {}
    state = "none"
    if y:
        sink = max(G.keyed(y.get("sink"), shot["from"]), G.keyed(y.get("sink"), shot["to"]))
        state = "reef" if sink > 0.05 else "sea"
    return f"{state}@isl({isl.get('x')},{isl.get('z')},{isl.get('scale')})"


def sequence_of(shot):
    d = shot.get("direction") or {}
    return d.get("sequence") or shot.get("scene") or location_of(shot)


def analyse_shot(ep, shot):
    W, H = ep.get("width", 1080), ep.get("height", 1920)
    aspect = W / H
    d = shot.get("direction") or {}
    f0, f1 = shot["from"], shot["to"] - 1
    frames = list(range(f0, f1 + 1, 3))
    if frames[-1] != f1:
        frames.append(f1)
    a = hero_actor(shot)
    trk = (d.get("subject") or {}).get("track")
    if trk:
        subj_kind = d["subject"].get("kind", "subject")
        subj_h = d["subject"].get("height", 1.8)
        if subj_kind == "object" and subj_h < 1.0:
            subj_h = 1.8          # props / inserts: size by absolute frame height (an insert is an ECU/CU)
        subj = lambda f: track_at(trk, f)
    elif a is not None:
        subj_kind, subj_h = "hero", a.get("height", 1.8)
        subj = lambda f: actor_landmark(shot, a, f, "chest")
    else:
        subj_kind, subj_h = "look", 1.8
        subj = lambda f: G.camera_world(shot, f, jitter=False)[1]
    centre_from = d.get("centre_from", f0)
    exempt = bool(d.get("pov") or d.get("insert"))
    # craft canon CAN-H1: an impact_handheld reaction window lets the subject escape the frame on purpose
    cex = [tuple(w) for w in d.get("centre_exempt") or []]

    def in_cex(f):
        return any(w0 <= f <= w1 for w0, w1 in cex)
    samples = []
    for f in frames:
        cam, look, fov, roll = G.camera_world(shot, f, jitter=True)
        S = subj(f)
        sx, sy, depth = G.project(cam, look, roll, fov, aspect, S)
        fh = G.frame_height_at(max(depth, 1e-3), fov)
        rec = {"f": f, "sx": sx, "sy": sy, "depth": depth, "fov": fov, "frame_h": fh, "cam": cam,
               "size": G.classify_size(fh, subj_h) if depth > 0 else "behind"}
        if a is not None:
            E = actor_landmark(shot, a, f, "eye")
            ex, ey, ed = G.project(cam, look, roll, fov, aspect, E)
            rec["eye"] = (ex, ey)
            Hc = actor_landmark(shot, a, f, "chest")
            hx, hy, hd = G.project(cam, look, roll, fov, aspect, Hc)
            rec["hero"] = (hx, hy, hd)
            rec["hero_fh"] = G.frame_height_at(max(hd, 1e-3), fov)
            rec["face"] = {n: G.project(cam, look, roll, fov, aspect, actor_landmark(shot, a, f, n))[:2] for n in ("top", "brow", "chin")}
            rec["eye_p"] = E
        samples.append(rec)

    # shot size: median frame height over the shot (a profiled hero: by his real head / torso proportions)
    fhs = sorted(s["frame_h"] for s in samples if s["depth"] > 0) or [0.0]
    prof = G.hero_profile(a.get("asset")) if a is not None else None
    if prof is not None and subj_kind == "hero":
        for s_ in samples:
            if s_["depth"] > 0:
                s_["size"] = prof.classify(s_["frame_h"], subj_h)
        size = prof.classify(fhs[len(fhs) // 2], subj_h)
    else:
        size = G.classify_size(fhs[len(fhs) // 2], subj_h)
    lens = statistics.median(G.vfov_to_lens(s["fov"], aspect) for s in samples)
    dxs = [abs(s["sx"] - 0.5) for s in samples if s["sx"] is not None and s["f"] >= centre_from and not in_cex(s["f"])]
    behind = [s["f"] for s in samples if s["sx"] is None and not in_cex(s["f"])]
    offscreen = [s["f"] for s in samples if s["sx"] is not None and not (0 <= s["sx"] <= 1 and 0 <= s["sy"] <= 1) and not in_cex(s["f"])]

    # motion (keys only: no drift / handheld noise)
    m_frames = []
    prev = None
    for f in range(f0, f1 + 1):
        cam, look, fov, _ = G.camera_world(shot, f, jitter=False)
        fwd = G.unit(G.sub(look, cam))
        dist = max(0.5, G.norm(G.sub(subj(f), cam)))
        if prev is not None:
            pc, pf, pv = prev
            ang = math.acos(max(-1.0, min(1.0, G.dot(fwd, pf))))
            zm = abs(math.log(math.tan(math.radians(fov) / 2) / math.tan(math.radians(pv) / 2)))
            m_frames.append(G.norm(G.sub(cam, pc)) / dist + ang + zm)
        prev = (cam, fwd, fov)
    fps = ep.get("fps", 30)
    win = int(round(0.8 * fps))
    static_at = None
    for i in range(0, max(0, len(m_frames) - win + 1)):
        if sum(m_frames[i:i + win]) < 0.004:
            static_at = f0 + i
            break
    rate = sum(m_frames) / max(1e-6, (f1 - f0) / fps)

    # collisions (polish_camera: against the real yacht geometry when the proxy exists, every frame)
    col = []
    yacht = shot.get("yacht")
    P = G.yacht_proxy() if yacht else None
    col_frames = [{"f": f, "cam": G.camera_world(shot, f, jitter=True)[0]} for f in range(f0, f1 + 1)] if P else samples
    for s in col_frames:
        if s["cam"][1] < 0.25:
            col.append((s["f"], "under water"))
        elif yacht:
            b = G.YachtFrame(yacht, s["f"]).world_to_body(s["cam"])
            if P is not None:
                dd = P.sdf(b)
                if dd < 0:
                    col.append((s["f"], f"inside yacht geometry ({dd:+.2f} m)"))
                elif dd < COL_CLEAR:
                    col.append((s["f"], f"lens {dd:.2f} m from a surface"))
            elif abs(b[0]) < 2.0 and -7.5 < b[2] < 6.5 and b[1] < 1.25:
                col.append((s["f"], "inside hull"))

    # hull occlusion: the camera -> hero chest ray passing through the hull below deck (transom, topsides)
    occ = []
    if a is not None and yacht and P is not None:
        if not d.get("ots"):
            for s in samples:                     # camera -> face sight line through the real geometry
                yf = G.YachtFrame(yacht, s["f"])
                cb, eb = yf.world_to_body(s["cam"]), yf.world_to_body(s["eye_p"])
                L = G.norm(G.sub(eb, cb))
                ex_, ey_ = s.get("eye") or (None, None)
                if L > 0.3 and ex_ is not None and 0 <= ex_ <= 1 and 0 <= ey_ <= 1:
                    if P.blocked(cb, G.add(cb, G.mul(G.sub(eb, cb), (L - 0.18) / L)), 0.0) is not None:
                        occ.append(s["f"])
    elif a is not None and yacht:
        for s in samples[::2]:
            yf = G.YachtFrame(yacht, s["f"])
            Hc = actor_point(shot, a, s["f"], 1.3 / 1.8)
            for i in range(1, 20):
                b = yf.world_to_body(G.vlerp(s["cam"], Hc, i / 20))
                if in_hull(b):
                    occ.append(s["f"])
                    break

    # 180: camera side relative to hero facing, at the first and last sample
    side = None
    if a is not None and yacht:
        yaw = yacht["heading"] + a.get("rotY", 0.0)
        Fv = G.yaw_dir(yaw)

        def side_at(s):
            Hc = actor_point(shot, a, s["f"], 1.3 / 1.8)
            C = G.sub(s["cam"], Hc)
            C = [C[0], 0, C[2]]
            n = G.norm(C)
            if n < 1e-6:
                return 0, 0.0
            cosang = G.dot(G.unit(C), Fv)
            ang = math.degrees(math.acos(max(-1, min(1, cosang))))
            crs = Fv[2] * C[0] - Fv[0] * C[2]          # >0: camera on the hero's left
            if ang < 15 or ang > 165:
                return 0, ang
            return (1 if crs > 0 else -1), ang
        s0, a0 = side_at(samples[0])
        s1, a1 = side_at(samples[-1])
        side = {"start": s0, "end": s1, "az_start": round(a0, 1), "az_end": round(a1, 1), "facing": yaw}

    # face crop (polish_camera): on hero shots framed MS or tighter, brow..chin inside, cap top inside (headroom)
    crop = []
    if a is not None and subj_kind == "hero" and not exempt and not d.get("ots"):
        for s in samples:
            fc = s.get("face")
            if not fc or s.get("size") not in ("ECU", "CU", "MCU", "MS") or s["f"] < centre_from or in_cex(s["f"]):
                continue
            u = (s["f"] - f0) / max(1, f1 - f0)       # a tilt frames the hands on purpose until it reaches the face
            if (d.get("preset") == "tilt_up" and u < 0.7) or (d.get("preset") == "tilt_down" and u > 0.3):
                continue
            (tx, ty), (bx, by), (cx, cy) = fc["top"], fc["brow"], fc["chin"]
            if None in (tx, bx, cx):
                crop.append((s["f"], "face behind camera"))
            elif s["size"] != "ECU" and ty < -0.005:
                crop.append((s["f"], f"cap cropped (top {ty:.2f})"))
            elif not (0.2 <= bx <= 0.8) and s["size"] in ("CU", "MCU"):
                crop.append((s["f"], f"face off-centre (x {bx:.2f})"))
            elif by < 0.0 or cy > 1.0 or not (0 <= bx <= 1):
                crop.append((s["f"], f"face cropped (brow {by:.2f}, chin {cy:.2f})"))
    key = shot.get("keyFrame", (f0 + f1) // 2)
    ks = min(samples, key=lambda s: abs(s["f"] - key))
    # face visibility at the key frame (polish_camera): face normal = body facing squared to the brow..chin axis
    # (so a look-down pitches it); the angle to the lens, and how far the lens sits above that normal (a cap brim
    # hides a lowered face seen from above: v6's first A02 render)
    face_vis = None
    if a is not None and subj_kind == "hero" and yacht and ks.get("eye_p"):
        br, ch = actor_landmark(shot, a, ks["f"], "brow"), actor_landmark(shot, a, ks["f"], "chin")
        u = G.unit(G.sub(br, ch))
        fh = G.yaw_dir(yacht["heading"] + a.get("rotY", 0.0))
        n_ = G.unit(G.sub(fh, G.mul(u, G.dot(fh, u))))
        tc = G.unit(G.sub(ks["cam"], ks["eye_p"]))
        face_vis = {"angle": round(math.degrees(math.acos(max(-1.0, min(1.0, G.dot(n_, tc))))), 1),
                    "above_normal": round(math.degrees(math.asin(max(-1.0, min(1.0, tc[1]))) - math.asin(max(-1.0, min(1.0, n_[1])))), 1)}
    # story anchors on screen at the key frame (no occlusion test): island coast, fires, the yacht
    isl = shot["island"] if "island" in shot else (ep.get("world") or {}).get("island")
    coast, fires = island_anchors(isl)
    cam, look, fov, roll = G.camera_world(shot, ks["f"], jitter=False)

    def on(p):
        x_, y_, d_ = G.project(cam, look, roll, fov, aspect, p)
        return x_ is not None and 0.02 <= x_ <= 0.98 and 0.02 <= y_ <= 0.98
    lit = [i for i, v in enumerate(G.keyed_vec_any(shot.get("fires"), ks["f"])) if v > 0.05]
    anchors = {"island": sum(on(p) for p in coast), "fires": sum(on(fires[i]) for i in lit) if fires else 0,
               "yacht": bool(yacht) and on(G.YachtFrame(yacht, ks["f"]).body_to_world([0, 2.0, 0]))}
    # >>> craft canon CAN-C1: frames whose composition holds the geography (hero + boat + island/tree line/fires)
    geo = []
    for s_ in samples:
        cam_, look_, fov_, roll_ = G.camera_world(shot, s_["f"], jitter=False)

        def on_(p, m=0.02):
            x_, y_, _ = G.project(cam_, look_, roll_, fov_, aspect, p)
            return x_ is not None and m <= x_ <= 1 - m and m <= y_ <= 1 - m
        hero_on = a is not None and on_(actor_landmark(shot, a, s_["f"], "chest"), 0.0)
        boat_on = bool(yacht) and on_(G.YachtFrame(yacht, s_["f"]).body_to_world([0, 2.0, 0]))
        land_on = sum(on_(p) for p in coast) + (sum(on_(p) for p in fires) if fires else 0)
        if hero_on and boat_on and land_on and s_.get("size") in WIDE:
            geo.append(s_["f"])
    # >>> craft canon CAN-H1: measured operator reaction around an impact (per frame, as rendered)
    impact = None
    ih = d.get("impact_handheld")
    imp_f = (ih or {}).get("impact", d.get("impact"))
    if imp_f is not None and a is not None:
        dx = []
        for f in range(int(imp_f) - 2, min(f1, int(imp_f) + 40) + 1):
            cam_, look_, fov_, roll_ = G.camera_world(shot, f, jitter=True)
            x_, y_, _ = G.project(cam_, look_, roll_, fov_, aspect, actor_landmark(shot, a, f, "chest"))
            dx.append((f, 9.0 if x_ is None else abs(x_ - 0.5)))
        post = [(f, v) for f, v in dx if f >= imp_f]
        esc = sum(1 for f, v in post if v > 0.5)
        peak_i = max(range(len(post)), key=lambda i: post[i][1]) if post else 0
        # catch-up start: walk back from the frame the subject re-enters the frame along the monotonic fall of
        # the offset (the operator's correction); the jolt hold before it can wobble with the boat
        start = None
        back_in = next((i for i in range(peak_i, len(post)) if post[i][1] <= 0.5), None)
        if back_in is not None and post[peak_i][1] > 0.5:
            i = back_in
            while i > 0 and post[i - 1][1] >= post[i][1] + 0.01:
                i -= 1
            start = post[i][0]
        recentred = next((f for f, v in post[peak_i:] if v < CENTRE_TOL), None)
        impact = {"impact": imp_f, "escape_frames": esc, "lag_frames": None if start is None else start - imp_f,
                  "recentred_at": recentred, "declared": ih}
    return {
        "id": shot["id"], "title": shot.get("title", ""), "from": shot["from"], "to": shot["to"],
        "geo_frames": geo, "impact": impact, "face_vis": face_vis, "impact_declared": bool(d.get("impact") is not None or ih),
        "reserved_cu": bool(d.get("reserved_close_up")), "shakes_px": max([x.get("px", 0) for x in shot["camera"].get("shakes") or []] or [0]),
        "frames": shot["to"] - shot["from"], "dur_s": round((shot["to"] - shot["from"]) / fps, 3),
        "space": shot["camera"].get("space", "world"), "subject": subj_kind, "subject_h": subj_h,
        "size": size, "size_start": samples[0]["size"], "size_end": samples[-1]["size"],
        "frame_h": round(fhs[len(fhs) // 2], 3), "lens_mm": round(lens, 1),
        "max_dx": round(max(dxs), 4) if dxs else None, "key_sx": None if ks["sx"] is None else round(ks["sx"], 4),
        "key_sy": None if ks["sy"] is None else round(ks["sy"], 4),
        "behind": behind, "offscreen": offscreen,
        "eye_y_key": round(ks["eye"][1], 3) if ks.get("eye") and ks["eye"][1] is not None else None,
        "hero_sx_key": round(ks["hero"][0], 3) if ks.get("hero") and ks["hero"][0] is not None else None,
        "hero_size_key": G.classify_size(ks["hero_fh"], 1.8) if ks.get("hero") and ks["hero"][2] > 0 else None,
        "first_sx": samples[0]["sx"], "last_sx": samples[-1]["sx"],
        "motion_rate": round(rate, 4), "static_at": static_at, "collisions": col[:5], "occluded": occ, "side": side,
        "face_crop": crop[:4],
        "key_top_y": round(ks["face"]["top"][1], 3) if ks.get("face") and ks["face"]["top"][1] is not None else None,
        "key_chin_y": round(ks["face"]["chin"][1], 3) if ks.get("face") and ks["face"]["chin"][1] is not None else None,
        "has_hero": a is not None, "anchors": anchors, "fires_lit": bool(lit), "preset": d.get("preset"), "motivation": d.get("motivation"),
        "pov": bool(d.get("pov")), "insert": bool(d.get("insert")), "ots": bool(d.get("ots")), "exempt": exempt,
        "line_cross": d.get("line_cross"), "long_take": bool(d.get("long_take")), "time_jump": bool(d.get("time_jump")),
        "location": location_of(shot), "sequence": sequence_of(shot),
        "key_spacing": max((b["f"] - a_["f"]) for a_, b in zip(shot["camera"]["keys"], shot["camera"]["keys"][1:])) if len(shot["camera"]["keys"]) > 1 else 0,
        "key_eases": sorted({k.get("ease", "move") for k in shot["camera"]["keys"][1:]}),
    }


# ------------------------------------------------------------------ rules
def rule(rid, name, status, detail, shots=()):
    return {"id": rid, "name": name, "status": status, "detail": detail, "shots": list(shots)}


SECTIONS = [  # name, start(D), end(D), ASL range (s), target
    ("HOOK", lambda D: 0.0, lambda D: 3.0, (0.6, 2.0), (1.0, 1.5)),
    ("CONTEXT", lambda D: 3.0, lambda D: 0.15 * D, (1.2, 3.5), (2.0, 2.5)),
    ("ESCALATION1", lambda D: 0.15 * D, lambda D: 0.40 * D, (1.0, 3.0), (1.8, 2.2)),
    ("MIDPOINT", lambda D: 0.40 * D, lambda D: 0.50 * D, (0.0, 5.0), (2.5, 4.0)),
    ("ESCALATION2", lambda D: 0.50 * D, lambda D: 0.80 * D, (0.8, 3.0), (1.5, 2.0)),
    ("PAYOFF", lambda D: 0.80 * D, lambda D: 0.95 * D, (0.0, 4.5), (2.5, 3.5)),
    ("STING", lambda D: 0.95 * D, lambda D: D + 1e-6, (0.6, 3.5), (1.0, 2.0)),
]


def validate(ep):
    shots = sorted(ep["shots"], key=lambda s: s["from"])
    A = [analyse_shot(ep, s) for s in shots]
    fps = ep.get("fps", 30)
    n = len(A)
    R = []

    # C1
    cu = [x["id"] for x in A if x["size"] in TIGHT]
    R.append(rule("C1", "CU+ECU <= 25% of shots", "pass" if len(cu) <= 0.25 * n else "fail",
                  f"{len(cu)}/{n} = {100 * len(cu) / max(1, n):.0f}% CU-or-tighter", cu))
    # C2
    runs, run = [], []
    for x in A + [None]:
        if x is not None and x["size"] in TIGHT:
            run.append(x["id"])
        else:
            if len(run) > 3:
                runs.append(list(run))
            run = []
    R.append(rule("C2", "no run of > 3 consecutive CU-or-tighter", "fail" if runs else "pass",
                  f"runs: {runs}" if runs else "longest run ok", [i for r in runs for i in r]))
    # C3
    seen, bad, det = {}, [], []
    for i, x in enumerate(A):
        seen.setdefault(x["location"], []).append(i)
    for loc, idx in seen.items():
        first = idx[:2]
        ok = any(A[i]["size"] in WIDE for i in first)
        det.append(f"{loc}: first shots {[A[i]['id'] + ':' + A[i]['size'] for i in first]}")
        if not ok:
            bad.append(A[idx[0]]["id"])
    R.append(rule("C3", "establishing EWS/WS within the first 2 shots of each location", "fail" if bad else "pass", "; ".join(det), bad))
    # C4
    bad, run = [], []
    for x in A:
        if x["time_jump"] and x["size"] not in WIDE:
            bad.append(x["id"])
        if x["size"] in WIDE:
            run = []
        else:
            run.append(x["id"])
            if len(run) == 7:
                bad.extend(run)
            elif len(run) > 7:
                bad.append(x["id"])
    R.append(rule("C4", "re-establish (WS/EWS) after <= 6 tighter shots and on time jumps", "fail" if bad else "pass",
                  f"over-long tight runs / unestablished time jumps: {bad}" if bad else "ok", bad))
    # C5
    bad, det = [], []
    seqs = {}
    for x in A:
        if x["side"] is not None:
            seqs.setdefault(x["sequence"], []).append(x)
    for seq, xs in seqs.items():
        cur_side, cur_face = 0, None
        for x in xs:
            s = x["side"]
            if cur_face is not None and abs(math.atan2(math.sin(s["facing"] - cur_face), math.cos(s["facing"] - cur_face))) > math.radians(60):
                cur_side = 0          # hero turned: the line resets (cut on a turn)
            cur_face = s["facing"]
            st = s["start"]
            if st != 0 and cur_side != 0 and st != cur_side and not x["line_cross"]:
                bad.append(x["id"])
                det.append(f"{x['id']} crosses the line in '{seq}' (side {st:+d} vs {cur_side:+d})")
            if s["end"] != 0:
                cur_side = s["end"]
            elif st != 0:
                cur_side = st
    R.append(rule("C5", "180-degree rule: camera side vs hero facing per sequence", "fail" if bad else "pass",
                  "; ".join(det) if det else "consistent", bad))
    R.append(rule("C6", "look/POV gaze pairs", "skip", "needs gaze annotations (actors.lookAt) and POV pairs"))
    # C7
    bad, det = [], []
    for x in A:
        if x["has_hero"] and x["subject"] == "hero" and x["size"] in ("MCU", "CU") and x["eye_y_key"] is not None:
            if not (0.30 <= x["eye_y_key"] <= 0.45):
                bad.append(x["id"])
                det.append(f"{x['id']} eye y {x['eye_y_key']:.2f}")
    R.append(rule("C7", "hero eyes y in [0.30, 0.45] on MCU/CU", "fail" if bad else "pass", "; ".join(det) if det else "ok", bad))
    # C8
    nomot = [x["id"] for x in A if not x["motivation"]]
    uneased = [x["id"] for x in A if x["key_spacing"] > 4 and x["key_eases"] == ["linear"]]
    R.append(rule("C8", "every move motivated + eased", "fail" if (nomot or uneased) else "pass",
                  f"no motivation: {nomot}; linear un-sampled keys: {uneased}", nomot + uneased))
    # C9
    durs = [x["dur_s"] for x in A]
    med = statistics.median(durs)
    short = [x["id"] for x in A if x["frames"] < (8 if x["insert"] else 18)]
    long_ = [x["id"] for x in A if x["dur_s"] > 6.0 and not x["long_take"]]
    st = "pass" if (2.0 <= med <= 3.5 and not short and not long_) else "fail"
    R.append(rule("C9", "durations: median 2.0-3.5 s, none < 18 f (insert >= 8 f), none > 6 s",
                  st, f"median {med:.2f} s; too short {short}; too long {long_}", short + long_))
    R.append(rule("C10", "J-cut into each threat reveal", "skip", "audio edit: checked on the cut list / sound.json"))
    # C11
    deltas, bad = [], []
    for a_, b in zip(A, A[1:]):
        if a_["last_sx"] is None or b["first_sx"] is None:
            continue
        dlt = abs(a_["last_sx"] - b["first_sx"])
        deltas.append(dlt)
        if dlt > 0.15:
            bad.append(f"{a_['id']}>{b['id']}")
    frac = 1 - len(bad) / max(1, len(deltas))
    R.append(rule("C11", "eye-trace delta <= 0.15 for >= 80% of cuts", "pass" if frac >= 0.8 else "fail",
                  f"{100 * frac:.0f}% of {len(deltas)} cuts within 0.15", bad))
    R.append(rule("C12", "intensity graph vs visual contrast", "skip", "needs rendered frames (QC on plates)"))
    R.append(rule("C13", ">= 3 depth planes on WS/MS", "skip", "needs scene occupancy / rendered depth (QC on plates)"))
    # C14
    bad, det = [], []
    for seq in {x["sequence"] for x in A}:
        cus = [x for x in A if x["sequence"] == seq and x["has_hero"] and x["subject"] == "hero" and x["size"] in TIGHT]
        if len(cus) >= 2:
            lo, hi = min(x["lens_mm"] for x in cus), max(x["lens_mm"] for x in cus)
            if hi - lo > 20:
                bad += [x["id"] for x in cus]
                det.append(f"{seq}: CU lenses {lo:.0f}-{hi:.0f} mm")
    R.append(rule("C14", "hero CU lens within +-10 mm per sequence", "fail" if bad else "pass", "; ".join(det) if det else "ok", bad))
    # H1 centring
    bad, det = [], []
    for x in A:
        if x["exempt"]:
            continue
        if x["behind"] or x["max_dx"] is None or x["max_dx"] >= CENTRE_TOL:
            bad.append(x["id"])
            det.append(f"{x['id']} max|dx| {x['max_dx']}" + (f" (subject behind camera at {x['behind'][:3]})" if x["behind"] else ""))
    R.append(rule("H1", "subject dead centre: |x - 0.5| < 0.08 on every sampled frame (POV/insert exempt)",
                  "fail" if bad else "pass", "; ".join(det) if det else "all centred", bad))
    # distribution
    obj = [x for x in A if not (x["ots"] or x["pov"])]      # OTS / POV are their own category (PIXAR 3.1)
    m = max(1, len(obj))
    wide = sum(1 for x in obj if x["size"] in WIDE) / m
    mid = sum(1 for x in obj if x["size"] in ("MS", "MCU")) / m
    ok = 0.25 <= wide <= 0.40 and 0.35 <= mid <= 0.50
    R.append(rule("DIST", "size mix: EWS+WS 25-40%, MS/MCU 35-50%, CU+ECU <= 25%", "pass" if ok else "warn",
                  f"EWS+WS {100 * wide:.0f}%, MS/MCU {100 * mid:.0f}% of {len(obj)} objective shots; OTS/POV {n - len(obj)}; CU+ECU {100 * len(cu) / max(1, n):.0f}%"))
    # P1 ASL by section
    D = max(x["to"] for x in A) / fps
    det, st = [], "pass"
    for name, s0, s1, rng, tgt in SECTIONS:
        xs = [x for x in A if s0(D) <= (x["from"] + x["to"]) / 2 / fps < s1(D)]
        if not xs:
            continue
        asl = sum(x["dur_s"] for x in xs) / len(xs)
        flag = "" if rng[0] <= asl <= rng[1] else " OUT"
        if flag:
            st = "warn"
        det.append(f"{name} {len(xs)} shots ASL {asl:.2f}s (range {rng[0]}-{rng[1]}, target {tgt[0]}-{tgt[1]}){flag}")
    overall = D / max(1, n)
    if not (1.8 <= overall <= 2.6):
        st = "warn"
    lo, hi = math.floor(D / 2.6), math.ceil(D / 1.8)
    det.append(f"overall ASL {overall:.2f}s over {D:.1f}s (1.8-2.6); {n} shots (bounds {lo}-{hi})")
    R.append(rule("P1", "average shot length by section (ENGAGEMENT 4 P-1)", st, "; ".join(det)))
    # P6
    pres = [x["preset"] for x in A]
    if any(pres):
        rep = [f"{a_['id']}>{b['id']}" for a_, b in zip(A, A[1:]) if a_["preset"] and a_["preset"] == b["preset"]]
        counts = {}
        for p in pres:
            if p:
                counts[p] = counts.get(p, 0) + 1
        over = {p: c for p, c in counts.items() if c > 0.25 * n}
        R.append(rule("P6", "no preset twice in a row; no preset on > 25% of shots", "fail" if (rep or over) else "pass",
                      f"repeats {rep}; overused {over}; mix {counts}", rep))
    else:
        R.append(rule("P6", "no preset twice in a row; no preset on > 25% of shots", "skip", "shots carry no direction.preset"))
    # P7
    stat = [f"{x['id']}@{x['static_at']}" for x in A if x["static_at"] is not None]
    slow = [f"{x['id']}({x['motion_rate']:.3f}/s)" for x in A if x["motion_rate"] < 0.02]
    R.append(rule("P7", "camera always moving: no static hold >= 0.8 s; >= 2%/s frame change",
                  "fail" if stat else ("warn" if slow else "pass"), f"static: {stat}; slow: {slow}", [s.split("@")[0] for s in stat]))
    # collisions
    col = [f"{x['id']}:{x['collisions'][0][1]}@{x['collisions'][0][0]}" for x in A if x["collisions"]]
    R.append(rule("COL", "camera not under water / inside the yacht (walls, consoles, cabin: real-geometry proxy)", "fail" if col else "pass",
                  "; ".join(col) if col else "ok", [c.split(":")[0] for c in col]))
    # >>> polish_camera: face framing + set references
    fc = [f"{x['id']}@{x['face_crop'][0][0]}: {x['face_crop'][0][1]}" for x in A if x.get("face_crop")]
    R.append(rule("FACE", "hero face never cropped on MS-and-tighter (brow..chin inside, cap inside = headroom)",
                  "fail" if fc else "pass", "; ".join(fc) if fc else "ok", [c.split("@")[0] for c in fc]))
    fv = [x for x in A if x.get("face_vis") and x["size"] in ("MCU", "CU", "ECU") and not (x["ots"] or x["insert"] or x["pov"])
          and x["preset"] != "tilt_down" and (x["face_vis"]["angle"] > FACE_VIS_MAX or x["face_vis"]["above_normal"] > FACE_ABOVE_MAX)]
    R.append(rule("FACEVIS", f"face readable on MCU-and-tighter: lens within {FACE_VIS_MAX:.0f} deg of the face normal, "
                  f"<= {FACE_ABOVE_MAX:.0f} deg above it (cap brim)", "warn" if fv else "pass",
                  "; ".join(f"{x['id']} angle {x['face_vis']['angle']} above {x['face_vis']['above_normal']}" for x in fv) if fv else "ok",
                  [x["id"] for x in fv]))
    kits = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "worlds", "kits")
    badset = [s_["id"] for s_ in shots if isinstance(s_.get("set"), str) and not os.path.exists(os.path.join(kits, s_["set"] + ".json"))]
    R.append(rule("SET", "every shot 'set' names a world kit (the renderer exits on an unknown kit)", "fail" if badset else "pass",
                  f"unknown kits on {badset}" if badset else "ok", badset))
    # <<< polish_camera
    # story context: hero shots must also show where we are (island / fires), not just a man against black water
    hs = [x for x in A if x["has_hero"]]
    ctx = [x for x in hs if x["anchors"]["island"] or x["anchors"]["fires"]]
    frac = len(ctx) / max(1, len(hs))
    nofire = [x["id"] for x in A if x["fires_lit"] and not x["anchors"]["fires"]]
    R.append(rule("CTX", "story-first framing: >= 50% of hero shots show the island/fires; lit fires seen in >= 1/3 of fire shots",
                  "pass" if frac >= 0.5 and len(nofire) <= 2 / 3 * max(1, sum(1 for x in A if x["fires_lit"])) else "fail",
                  f"{len(ctx)}/{len(hs)} hero shots show island/fires; fires lit but never in frame: {nofire}",
                  [x["id"] for x in hs if x not in ctx]))
    # lens language (PIXAR 3.5): calm/neutral clusters 35-50, extremes for contrast; telephoto everywhere hides the world
    tele = [x["id"] for x in A if x["lens_mm"] > 60 and not x["insert"] and x["size"] not in TIGHT]
    R.append(rule("LENS", "lens language: non-CU shots mostly 18-60 mm (<= 30% longer)", "pass" if len(tele) <= 0.3 * n else "warn",
                  f"{len(tele)}/{n} non-CU shots on > 60 mm equivalent", tele))
    occl = [f"{x['id']}@{x['occluded'][0]}" for x in A if x.get("occluded")]
    R.append(rule("OCC", "hero not hidden behind the hull (camera->chest ray clear of the hull below deck)", "fail" if occl else "pass",
                  "; ".join(occl) if occl else "ok", [o.split("@")[0] for o in occl]))
    # subject visible
    vis = [x["id"] for x in A if (x["behind"] or x["offscreen"]) and not x["exempt"]]
    R.append(rule("VIS", "subject in front of the camera and inside the frame", "fail" if vis else "pass",
                  f"not visible on some frames: {vis}" if vis else "ok", vis))

    R.extend(canon_rules(ep, A))
    counts = {k: sum(1 for r in R if r["status"] == k) for k in ("pass", "fail", "warn", "skip")}
    evald = counts["pass"] + counts["fail"] + counts["warn"]
    score = round(100 * (counts["pass"] + 0.5 * counts["warn"]) / max(1, evald), 1)
    shots_out = []
    for x in A:
        y = {k: v for k, v in x.items() if k not in ("first_sx", "last_sx", "key_eases")}
        shots_out.append(y)
    return {"episode": ep.get("id"), "shots_n": n, "duration_s": round(D, 2), "summary": counts | {"score": score},
            "rules": R, "shots": shots_out}


# >>> craft canon camera rules (factory/canon/SOURCES.md: UW two-shot coverage; Greengrass)
IMPACT_SHAKE_PX = 12     # a camera shake this strong marks an impact even if the director did not declare one
ESCAPE_RANGE = (2, 12)   # frames the subject may be out of frame on an impact
LAG_RANGE = (2, 10)      # frames before the operator starts to catch up ("a few frames late")


def canon_rules(ep, A):
    R = []
    # CAN-C1: per location, a wide holding hero + boat + island/tree line/fires comes before any hero coverage
    bad, det = [], []
    locs = {}
    for i, x in enumerate(A):
        locs.setdefault(x["location"], []).append(i)
    for loc, idx in locs.items():
        cov = [i for i in idx if A[i]["has_hero"] and A[i]["subject"] == "hero" and (A[i]["size"] not in WIDE or A[i]["ots"])]
        if not cov:
            continue
        first = cov[0]
        est = [i for i in idx if i <= first and A[i]["geo_frames"] and (A[i]["size"] in WIDE or i < first)]
        if est:
            det.append(f"{loc}: {A[est[0]]['id']} establishes (geo frames {A[est[0]]['geo_frames'][0]}..{A[est[0]]['geo_frames'][-1]}) before {A[first]['id']}")
        else:
            bad.append(A[first]["id"])
            det.append(f"{loc}: coverage starts at {A[first]['id']} with no wide holding hero + boat + island first")
    R.append(rule("CAN-C1", "wide establishes geography (hero + boat + threat/tree line in one composition) before coverage",
                  "fail" if bad else "pass", "; ".join(det), bad))
    # CAN-C2: hero close-ups only on the reserved decisive beat of their sequence
    reserved = dict(((ep.get("canon") or {}).get("reserved_close_up") or {}))
    shot_of = {x["id"]: x for x in A}
    bad, det = [], []
    for x in A:
        if x["reserved_cu"]:
            sq = x["sequence"]
            if reserved.get(sq) not in (None, x["id"]):
                bad.append(x["id"])
                det.append(f"{sq}: two reserved close-ups ({reserved[sq]}, {x['id']})")
            reserved.setdefault(sq, x["id"])
    for sq, sid in reserved.items():
        if sid not in shot_of:
            bad.append(sid)
            det.append(f"{sq}: reserved close-up names unknown shot {sid}")
    for x in A:
        tight = x["size"] in TIGHT or x["size_end"] in TIGHT
        if not (tight and x["has_hero"] and x["subject"] == "hero" and not x["insert"]):
            continue
        if reserved.get(x["sequence"]) == x["id"]:
            det.append(f"{x['id']} reserved CU of {x['sequence']}")
        else:
            bad.append(x["id"])
            det.append(f"{x['id']} casual CU ({x['size']}->{x['size_end']}) in {x['sequence']} (reserved: {reserved.get(x['sequence'])})")
    R.append(rule("CAN-C2", "close-up reserved for the decisive reaction beat (director marks reserved_close_up)",
                  "fail" if bad else "pass", "; ".join(det) if det else "no hero close-ups", bad))
    # CAN-H1: impacts are covered by reactive handheld: subject escapes, camera catches up late
    bad, det = [], []
    for x in A:
        if not (x["impact_declared"] or x["shakes_px"] >= IMPACT_SHAKE_PX):
            continue
        m = x["impact"]
        if not m:
            bad.append(x["id"])
            det.append(f"{x['id']}: impact shot (shake {x['shakes_px']} px) without impact_handheld (locked-off impact)")
            continue
        e, l_, dec = m["escape_frames"], m["lag_frames"], m.get("declared") or {}
        why = []
        if not ESCAPE_RANGE[0] <= e <= ESCAPE_RANGE[1]:
            why.append(f"escape {e} f not in {ESCAPE_RANGE}")
        if l_ is None or not LAG_RANGE[0] <= l_ <= LAG_RANGE[1]:
            why.append(f"catch-up lag {l_} f not in {LAG_RANGE}")
        if m["recentred_at"] is None or m["recentred_at"] > x["to"] - 1:
            why.append("never re-centred")
        if dec and (abs(dec.get("escape_frames", e) - e) > 1 or (l_ is not None and abs(dec.get("lag_frames", l_) - l_) > 1)):
            why.append(f"measured escape/lag {e}/{l_} vs declared {dec.get('escape_frames')}/{dec.get('lag_frames')}")
        if why:
            bad.append(x["id"])
        det.append(f"{x['id']}@{m['impact']}: escape {e} f, lag {l_} f, re-centred @{m['recentred_at']}" + (f" FAIL: {', '.join(why)}" if why else ""))
    R.append(rule("CAN-H1", "impact handheld: subject briefly escapes frame, camera catches up a few frames late",
                  "fail" if bad else "pass", "; ".join(det) if det else "no impact shots", bad))
    return R
# <<< craft canon camera rules


def human(report):
    out = []
    s = report["summary"]
    out.append(f"Shot validator: {report['episode']}  {report['shots_n']} shots, {report['duration_s']} s  "
               f"pass {s['pass']} / fail {s['fail']} / warn {s['warn']} / skip {s['skip']}  score {s['score']}")
    out.append(f"{'id':5} {'dur':>5} {'size':5} {'lens':>5} {'|dx|':>6} {'eyeY':>5} {'side':>5} {'mot/s':>6} preset")
    for x in report["shots"]:
        sd = x["side"]
        side = "" if not sd else f"{sd['start']:+d}{sd['end']:+d}"
        out.append(f"{x['id']:5} {x['dur_s']:5.2f} {x['size']:5} {x['lens_mm']:5.0f} "
                   f"{('%.3f' % x['max_dx']) if x['max_dx'] is not None else '  -  ':>6} "
                   f"{('%.2f' % x['eye_y_key']) if x['eye_y_key'] is not None else '':>5} {side:>5} {x['motion_rate']:6.3f} "
                   f"{x['preset'] or '-'}{' POV' if x['pov'] else ''}{' INSERT' if x['insert'] else ''}{' OTS' if x['ots'] else ''}")
    out.append("")
    for r in report["rules"]:
        out.append(f"[{r['status'].upper():4}] {r['id']:4} {r['name']}: {r['detail']}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("episode")
    ap.add_argument("--out", help="write the JSON report here")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any rule fails")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    ep = json.load(open(args.episode))
    root = os.path.dirname(os.path.abspath(args.episode))
    while root != "/" and not os.path.isdir(os.path.join(root, "factory")):
        root = os.path.dirname(root)
    load_coast(root)
    rep = validate(ep)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        json.dump(rep, open(args.out, "w"), indent=1)
    if not args.quiet:
        print(human(rep))
    if args.strict and rep["summary"]["fail"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
