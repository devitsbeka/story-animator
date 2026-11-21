"""Framing QC: project the subject through the episode.json camera and test the house rules.

The camera model is a numpy port of `cloud/blender/render_episode.py` (`rig_at`, `look_matrix3`,
yacht-space cameras): three.js convention, Y up, the camera looks down -Z, vertical FOV.
Buoyancy heave/pitch/roll is simulated by the renderer from the ocean and is not available
here, so the yacht pose uses only the keyed `pitch`/`roll`/`sink` (error ~0.1-0.3 m).

Rules (PIXAR_RECIPE house rules + checklist C7, ENGAGEMENT C-1):
- H1        hero eyes x in 0.5 +- 0.08 of frame width
- C7.eye_y  eyes y in [0.30, 0.45] from top, enforced on close shots (hero >= 60% of frame height)
- H2        eyes outside the top 12% and bottom 20%
- C-1.face  (CAPTIONS) hero face box inside the ENGAGEMENT safe rect in >= 90% of hero frames
Shots without a hero, or whose camera aims more than 1 m from the hero's eyes (inserts:
radio, beacon, switch), centre the camera's look target instead; that only tests the jitter.
"""
from __future__ import annotations

import math

import numpy as np

from .common import FAIL, PASS, SAFE_RECT, CANVAS, check, rnd, rule, skip

# ---- port of render_episode.py ---------------------------------------------------------------


def keyed(v, f, default=0.0):
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    ks = sorted(v, key=lambda k: k[0])
    if f <= ks[0][0]:
        return float(ks[0][1])
    if f >= ks[-1][0]:
        return float(ks[-1][1])
    for (f0, v0), (f1, v1) in zip(ks, ks[1:]):
        if f0 <= f <= f1:
            return float(v0) if f1 == f0 else v0 + (v1 - v0) * (f - f0) / (f1 - f0)
    return float(ks[-1][1])


def _bez(x1, y1, x2, y2):
    def f(x):
        t = x
        for _ in range(8):
            cx = 3 * x1 * t * (1 - t) ** 2 + 3 * x2 * t * t * (1 - t) + t ** 3 - x
            dx = 3 * x1 * (1 - t) ** 2 + 6 * (x2 - x1) * t * (1 - t) + 3 * (1 - x2) * t * t
            if abs(dx) < 1e-6:
                break
            t = min(1.0, max(0.0, t - cx / dx))
        return 3 * y1 * t * (1 - t) ** 2 + 3 * y2 * t * t * (1 - t) + t ** 3
    return f


EASE = {
    "arrive": _bez(0.16, 1, 0.3, 1), "move": _bez(0.65, 0, 0.35, 1), "exit": _bez(0.7, 0, 0.84, 0),
    "anticipate": _bez(0.5, -0.32, 0.25, 1), "overshoot": _bez(0.34, 1.45, 0.64, 1),
    "crashIn": lambda t: t * t * t, "linear": lambda t: t,
}


def rig_at(f, keys, handheld=0.2, shakes=(), drift=0.25):
    keys = sorted(keys, key=lambda k: k["f"])
    i = 0
    while i < len(keys) - 2 and f >= keys[i + 1]["f"]:
        i += 1
    a, b = keys[i], keys[min(i + 1, len(keys) - 1)]
    u = 1.0 if b["f"] == a["f"] else max(0.0, min(1.0, (f - a["f"]) / (b["f"] - a["f"])))
    e = EASE.get(b.get("ease") or "move", EASE["move"])(u)
    cam = [a["cam"][j] + (b["cam"][j] - a["cam"][j]) * e for j in range(3)]
    look = [a["look"][j] + (b["look"][j] - a["look"][j]) * e for j in range(3)]
    fov = math.exp(math.log(a["fov"]) + (math.log(b["fov"]) - math.log(a["fov"])) * e)
    roll = (a.get("roll", 0) or 0) + ((b.get("roll", 0) or 0) - (a.get("roll", 0) or 0)) * e
    dr = drift
    cam = [cam[0] + math.sin(f * 0.011) * dr, cam[1] + math.sin(f * 0.017 + 1) * dr * 0.5, cam[2] + math.sin(f * 0.009 + 2) * dr]
    k = math.dist(look, cam) * 0.0175
    jx = handheld * (math.sin(f * 0.31) + 0.6 * math.sin(f * 0.83 + 1.7))
    jy = handheld * (math.sin(f * 0.47 + 0.9) + 0.5 * math.sin(f * 1.13 + 3.1))
    for s in shakes or ():
        t = f - s["at"]
        if t < 0 or t > s["tau"] * 6:
            continue
        amp = s["px"] * math.exp(-t / s["tau"]) * (fov / 1080)
        jx += amp * math.sin(t * 2.3)
        jy += amp * math.cos(t * 2.9)
        roll += amp * 0.25 * math.sin(t * 1.7)
    look = [look[0] + jx * k, look[1] + jy * k, look[2]]
    return np.array(cam), np.array(look), fov, roll


def _rot(axis, a):
    c, s = math.cos(a), math.sin(a)
    if axis == "X":
        m = [[1, 0, 0], [0, c, -s], [0, s, c]]
    elif axis == "Y":
        m = [[c, 0, s], [0, 1, 0], [-s, 0, c]]
    else:
        m = [[c, -s, 0], [s, c, 0], [0, 0, 1]]
    M = np.eye(4)
    M[:3, :3] = m
    return M


def _trans(v):
    M = np.eye(4)
    M[:3, 3] = v
    return M


def _app(M, p):
    return (M @ np.append(np.asarray(p, float), 1.0))[:3]


def yacht_matrix(y, f):
    """Yacht object matrix without the ocean buoyancy term (see module doc)."""
    return (_trans((y["x"], -keyed(y.get("sink"), f), y["z"])) @ _rot("Y", y["heading"])
            @ _rot("X", -keyed(y.get("pitch"), f)) @ _rot("Z", keyed(y.get("roll"), f)))


def camera_basis(cam, look, roll_deg):
    fwd = look - cam
    fwd = fwd / np.linalg.norm(fwd)
    up = np.array([0.0, 1.0, 0.0])
    a = -math.radians(roll_deg)  # Rodrigues rotation of up about fwd (as mathutils in the renderer)
    up = up * math.cos(a) + np.cross(fwd, up) * math.sin(a) + fwd * np.dot(fwd, up) * (1 - math.cos(a))
    z = -fwd
    x = np.cross(up, z)
    if np.linalg.norm(x) < 1e-6:
        x = np.array([1.0, 0, 0])
    x = x / np.linalg.norm(x)
    yv = np.cross(z, x)
    return x, yv, z


def camera_at(shot, f):
    """World-space camera position, look point, vertical fov (deg) and roll for frame f."""
    ck = shot["camera"]
    cam, look, fov, roll = rig_at(f, ck["keys"], keyed(ck.get("handheld"), f, 0.2), ck.get("shakes") or (), ck.get("drift", 0.25))
    y = shot.get("yacht")
    if ck.get("space", "world") == "yacht" and y:
        cm = _trans((y["x"], 0.0, y["z"])) @ _rot("Y", y["heading"])
        cam, look = _app(cm, cam), _app(yacht_matrix(y, f), look)
    return cam, look, fov, roll


def project(p, cam, look, fov, roll, aspect):
    """-> (x, y) in [0,1] from the top-left, depth (m, >0 in front) or None behind the camera."""
    x, yv, z = camera_basis(cam, look, roll)
    d = np.asarray(p, float) - cam
    zc = float(np.dot(d, z))
    if zc >= -1e-6:
        return None
    t = math.tan(math.radians(fov) / 2)
    u = float(np.dot(d, x)) / (-zc) / (t * aspect)
    v = float(np.dot(d, yv)) / (-zc) / t
    return (u + 1) / 2, (1 - v) / 2, -zc


# eye height / actor height per stance; 0.90 standing was calibrated on rendered plates
# (B12 f815 close-up, C21 f1450 seated: projected vs. visible eyes within ~0.02 of frame height)
DEFAULT_EYE = 0.90
STANCE_EYE = {"sit_deck": 0.50, "down": 0.3, "crouch": 0.6, "kneel": 0.62}


def _stance(perf, f):
    name = "stand"
    for k, s in sorted((perf or {}).get("stance") or [], key=lambda k: k[0]):
        if f >= k:
            name = s
    return name


def hero_points(shot, f):
    """World-space eye point and feet point of the first actor in the shot (yacht space)."""
    acts = shot.get("actors") or []
    y = shot.get("yacht")
    if not acts or not y:
        return None
    a = acts[0]
    h = float(a.get("height", 1.8))
    eye_k = STANCE_EYE.get(_stance(a.get("perf"), f), DEFAULT_EYE)
    loc = np.asarray(a["local"], float)
    ym = yacht_matrix(y, f)
    return _app(ym, loc + [0, h * eye_k, 0]), _app(ym, loc), h


def shot_frames(shot, step=3):
    fr = list(range(shot["from"], shot["to"], step))
    return fr or [shot["from"]]


def analyse_shot(shot, w, h, step=3):
    """Per-frame subject projections for a shot."""
    aspect = w / h
    rows = []
    for f in shot_frames(shot, step):
        cam, look, fov, roll = camera_at(shot, f)
        hp = hero_points(shot, f)
        kind, eye, frac, face_r = "look-target", None, None, None
        if hp is not None:
            eye_w, feet_w, hh = hp
            if np.linalg.norm(look - eye_w) <= 1.0:
                kind = "hero"
                pe = project(eye_w, cam, look, fov, roll, aspect)
                pf = project(feet_w, cam, look, fov, roll, aspect)
                if pe is not None:
                    eye = pe[:2]
                    frac = abs(pf[1] - pe[1]) / DEFAULT_EYE if pf is not None else None
                    # face box half-size: a 0.25 m head at the eye depth, in frame-height units
                    face_r = 0.125 / (pe[2] * math.tan(math.radians(fov) / 2)) / 2
            else:
                kind = "insert"
        if kind != "hero":
            p = project(look, cam, look, fov, roll, aspect)
            eye = p[:2] if p else None
        rows.append({"f": f, "kind": kind, "eye": eye, "hero_frac": frac, "face_r": face_r})
    return rows


def framing_checks(ep, step=3):
    """-> (rules, per-shot detail)."""
    w, h = ep.width, ep.height
    sx0, sy0, sx1, sy1 = SAFE_RECT[0] / CANVAS[0], SAFE_RECT[1] / CANVAS[1], SAFE_RECT[2] / CANVAS[0], SAFE_RECT[3] / CANVAS[1]
    per_shot, face_ok, face_n = [], 0, 0
    h1_pass = h2_pass = eyey_pass = n_hero_shots = n_close = 0
    for s in ep.shots:
        if "camera" not in s:
            continue
        rows = analyse_shot(s, w, h, step)
        kinds = [r["kind"] for r in rows]
        kind = max(set(kinds), key=kinds.count)
        vis = [r for r in rows if r["eye"] is not None and r["kind"] == kind]
        if not vis:
            per_shot.append({"shot": s["id"], "kind": kind, "status": FAIL, "why": "subject behind the camera"})
            if kind == "hero":
                n_hero_shots += 1
            continue
        xs = np.array([r["eye"][0] for r in vis])
        ys = np.array([r["eye"][1] for r in vis])
        h1 = float(np.mean(np.abs(xs - 0.5) <= 0.08))
        h2 = float(np.mean((ys >= 0.12) & (ys <= 0.80)))
        fracs = [r["hero_frac"] for r in vis if r["hero_frac"] is not None]
        close = bool(fracs) and float(np.median(fracs)) >= 0.6
        eyey = float(np.mean((ys >= 0.30) & (ys <= 0.45))) if close else None
        ok = h1 >= 0.9 and h2 >= 0.9 and (eyey is None or eyey >= 0.9)
        d = {"shot": s["id"], "kind": kind, "frames": len(vis), "eye_x_mean": rnd(xs.mean()), "eye_x_maxdev": rnd(np.abs(xs - 0.5).max()),
             "eye_y_mean": rnd(ys.mean()), "H1_share": rnd(h1), "H2_share": rnd(h2), "close": close, "C7_eye_y_share": rnd(eyey),
             "status": PASS if ok else FAIL}
        if kind == "hero":
            n_hero_shots += 1
            h1_pass += h1 >= 0.9
            h2_pass += h2 >= 0.9
            if close:
                n_close += 1
                eyey_pass += eyey >= 0.9
            for r in vis:
                fx, fy, fr = r["eye"][0], r["eye"][1], r["face_r"] or 0.0
                face_n += 1
                face_ok += (fx - fr * h / w >= sx0 and fx + fr * h / w <= sx1 and fy - fr >= sy0 and fy + fr <= sy1)
        per_shot.append(d)
    rules = []
    if n_hero_shots == 0:
        rules.append(skip("H1", "FRAMING", "no hero shots with a camera"))
    else:
        rules.append(check("H1", "FRAMING", h1_pass == n_hero_shots, f"{h1_pass}/{n_hero_shots} hero shots", "every hero shot: eyes x in 0.5+-0.08 for >=90% of frames",
                           [d["shot"] for d in per_shot if d["kind"] == "hero" and (d.get("H1_share") or 0) < 0.9]))
        rules.append(check("H2", "FRAMING", h2_pass == n_hero_shots, f"{h2_pass}/{n_hero_shots} hero shots", "eyes y in [0.12, 0.80] for >=90% of frames",
                           [d["shot"] for d in per_shot if d["kind"] == "hero" and (d.get("H2_share") or 0) < 0.9]))
        if n_close:
            rules.append(check("C7.eye_y", "FRAMING", eyey_pass == n_close, f"{eyey_pass}/{n_close} close shots", "close shots: eyes y in [0.30, 0.45]",
                               [d["shot"] for d in per_shot if d.get("close") and (d.get("C7_eye_y_share") or 0) < 0.9]))
        else:
            rules.append(skip("C7.eye_y", "FRAMING", "no close (MCU/CU) hero shots"))
        share = face_ok / face_n if face_n else 0.0
        rules.append(check("C-1.face", "CAPTIONS", share >= 0.9, rnd(share), ">= 0.90 of sampled hero frames with the face box inside the safe rect"))
    others = [d for d in per_shot if d["kind"] != "hero"]
    if others:
        bad = [d["shot"] for d in others if d["status"] != PASS]
        rules.append(rule("H1.subject", "FRAMING", PASS if not bad else FAIL, f"{len(others) - len(bad)}/{len(others)} non-hero shots",
                          "look target (insert/establishing subject) centred", {"failed": bad, "note": "non-hero shots centre the camera look target; this only tests rig jitter"}))
    return rules, per_shot


def overlay(png_in, png_out, shot, f, w, h):
    """Draw the projected subject point and the H1 band on a rendered plate (visual cross-check)."""
    from PIL import Image, ImageDraw
    rows = analyse_shot({**shot, "from": f, "to": f + 1}, w, h, 1)
    im = Image.open(png_in).convert("RGB")
    W, H = im.size
    dr = ImageDraw.Draw(im)
    for xx in (0.42, 0.58):
        dr.line([(xx * W, 0), (xx * W, H)], fill=(255, 210, 0), width=1)
    sx0, sy0, sx1, sy1 = (SAFE_RECT[0] / CANVAS[0] * W, SAFE_RECT[1] / CANVAS[1] * H, SAFE_RECT[2] / CANVAS[0] * W, SAFE_RECT[3] / CANVAS[1] * H)
    dr.rectangle([sx0, sy0, sx1, sy1], outline=(0, 200, 255), width=1)
    r = rows[0]
    if r["eye"] is not None:
        ex, ey = r["eye"][0] * W, r["eye"][1] * H
        dr.ellipse([ex - 4, ey - 4, ex + 4, ey + 4], outline=(255, 0, 0), width=2)
    im.save(png_out)
    return r
