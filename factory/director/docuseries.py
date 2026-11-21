"""Docuseries format: frame sizes, structure rules and dual-frame (16:9 + 9:16) staging for short_candidate beats.

factory/ARCHITECTURE.md "Formats: shorts and long-form docuseries":
  - the master is 16:9 (1920x1080; 3840x2160 later), shorts are 9:16 (1080x1920);
  - each chapter carries one self-contained short_candidate (45-90 s) with in/out points and a hook line;
  - those beats are staged for both frames: the hero stays inside a centre band that holds in 16:9 and 9:16, and
    every shot of the beat records a second 9:16 camera next to the 16:9 one, so verticals are re-framed, not cropped.

The vertical camera is derived from the main one (vertical_camera): same positions and timing, the look re-aimed at
the subject (the hero's chest, or an explicit `vertical.subject`) and the fov tightened, so the subject sits at the
centre of the tall frame. Pure python; the projection model is factory/direction/camgeo.py (a port of the renderer).
"""
import math

from factory.direction import camgeo

FPS = 30
SIZE = {"short": (1080, 1920), "docuseries": (1920, 1080)}
VERTICAL = (1080, 1920)
# 150-400 shots for a 20-minute episode, as a density so a 6-minute mini-doc is held to the same rule
SHOTS_PER_MIN = (7.5, 20.0)
# a 9:16 frame of the same height covers (9/16)/(16/9) = 31.6% of a 16:9 frame's width: the hero's centre must stay
# inside that band in the master, so a vertical re-frame never has to swing far from the 16:9 composition
CENTRE_BAND = 0.5 * (9 / 16) / (16 / 9)          # half-width in frame-width units (0.158)
VERTICAL_TOL = 0.08                               # house H1: hero x within 0.5 +- 0.08 in the vertical frame
DEFAULT_TIGHTEN = 0.85                            # vertical fov = main fov x 0.85 (phones read a tighter frame)
CHEST = 1.30
REAIM_MIN_M = 1.0                                 # re-aim only when the main look is >= 1 m from the hero's chest
EYE_Y = 0.38                                      # 9:16 close framings: eyes at 38% of the frame height (C7: 0.30-0.45)
CLOSE_FRAME_H = 3.2                               # metres of frame height at the hero below which headroom applies
DEFAULT_EYE, STANCE_EYE = 0.90, {"sit_deck": 0.50, "down": 0.3, "crouch": 0.6, "kneel": 0.62}   # eye / actor height


def frame_size(fmt):
    return SIZE.get(fmt, SIZE["short"])


def shot_count_range(duration_s):
    lo, hi = SHOTS_PER_MIN
    return math.floor(lo * duration_s / 60.0), math.ceil(hi * duration_s / 60.0)


def candidates(story):
    """[{id, chapter, in, out, hook_line, setup, turn, payoff}] in story order (seconds, narration-audio time)."""
    out = []
    for c in story.get("chapters") or []:
        sc = c.get("short_candidate")
        if sc:
            out.append({**sc, "chapter": c["id"]})
    return out


def candidate_frames(sc, offset):
    """Film frames [f_in, f_out) of a candidate (the narration audio starts at film frame `offset`)."""
    return offset + round(sc["in"] * FPS), offset + round(sc["out"] * FPS)


def overlaps(shot, f0, f1):
    return shot["from"] < f1 and shot["to"] > f0


# ------------------------------------------------------------------ subject + vertical camera
def hero_subject(shot):
    """The hero's chest in yacht-local metres, or None."""
    a = next(iter(shot.get("actors") or []), None)
    if not a:
        return None
    lx, ly, lz = a["local"]
    return [lx, ly + CHEST, lz]


def subject_world(shot, f, vertical=None):
    """World-space subject point at frame f: vertical.subject ({frame: yacht|world, v}) if given, else the hero's
    chest on the (keyed) yacht, else the main camera's look target. Returns (point, kind)."""
    spec = (vertical or {}).get("subject")
    y = shot.get("yacht")
    if spec:
        if spec["frame"] == "yacht" and y:
            return camgeo.YachtFrame(y, f).body_to_world(spec["v"]), "explicit"
        return list(spec["v"]), "explicit"
    h = hero_subject(shot)
    if h is not None and y:
        return camgeo.YachtFrame(y, f).body_to_world(h), "hero"
    _, look, _, _ = camgeo.camera_world(shot, f, jitter=False)
    return look, "look"


def aim_world(shot, main, f, vertical=None):
    """World point the 9:16 camera keeps centred at frame f: the subject, except that when the 16:9 camera already
    aims at the hero (look within REAIM_MIN_M of his chest, e.g. a face close-up) its own look point is kept."""
    probe = {**shot, "camera": main}
    p, kind = subject_world(probe, f, vertical)
    if kind == "hero":
        _, look, _, _ = camgeo.camera_world(probe, f, jitter=False)
        if math.dist(look, p) < REAIM_MIN_M:
            return look, "look"
    return p, kind


def _to_cam_space(shot, cam_spec, f, p_world):
    """World point -> the space the camera keys are written in (yacht-space looks ride the full yacht matrix)."""
    if cam_spec.get("space", "world") == "yacht" and shot.get("yacht"):
        return camgeo.YachtFrame(shot["yacht"], f).world_to_body(p_world)
    return p_world


def vertical_camera(shot, main, vertical=None):
    """Derive the 9:16 camera of a shot from its compiled 16:9 camera: same positions, keys, handheld and shakes;
    the look re-aimed at the subject; the fov tightened (vertical.tighten, default 0.85). `shot` is the compiled
    episode shot (yacht, actors) carrying `main` as its camera."""
    v = vertical or {}
    tighten = float(v.get("tighten", DEFAULT_TIGHTEN))
    aim = v.get("aim") or (0.0, 0.0, 0.0)
    probe = {**shot, "camera": main}
    keys = []
    for k in main["keys"]:
        p, kind = aim_world(shot, main, k["f"], v)
        fov = k["fov"] * tighten
        if kind in ("hero", "look") and shot.get("actors") and shot.get("yacht"):
            p = _headroom(probe, k["f"], p, fov)
        look = _to_cam_space(probe, main, k["f"], p)
        look = [look[0] + aim[0], look[1] + aim[1], look[2] + aim[2]]
        keys.append({**k, "look": [round(x, 4) for x in look], "fov": round(fov, 3)})
    out = {kk: vv for kk, vv in main.items() if kk != "keys"}
    out["keys"] = keys
    return out


def eye_world(shot, f):
    """The hero's eye point in world metres at frame f (same eye model as factory/qc/framing.py)."""
    a = shot["actors"][0]
    stance = "stand"
    for fk, name in sorted((a.get("perf") or {}).get("stance") or [], key=lambda x: x[0]):
        if f >= fk:
            stance = name
    eye = float(a.get("height", 1.8)) * STANCE_EYE.get(stance, DEFAULT_EYE)
    lx, ly, lz = a["local"]
    return camgeo.YachtFrame(shot["yacht"], f).body_to_world([lx, ly + eye, lz])


def _headroom(probe, f, p, vfov):
    """9:16 headroom: on close framings (frame height at the hero <= CLOSE_FRAME_H) aim at the hero's eyes (on a
    rolling deck they sit off the chest's vertical) and tilt so they sit at EYE_Y of the frame height (PIXAR C7)."""
    e = eye_world(probe, f)
    c, _, _, _ = camgeo.camera_world(probe, f, jitter=False)
    fh = 2 * math.dist(c, e) * math.tan(math.radians(vfov) / 2)
    if fh > CLOSE_FRAME_H:
        return p
    return [e[0], e[1] - (0.5 - EYE_Y) * fh, e[2]]


# ------------------------------------------------------------------ dual-frame geometry checks
def project_subject(shot, main, cam, f, aspect, vertical=None, eyes=False):
    """(sx, sy) of the aim point (aim_world of the 16:9 camera `main`; the hero's eyes with eyes=True and a hero on
    deck) through `cam` at frame f (no jitter), or (None, None) when it is behind the camera."""
    p, kind = aim_world(shot, main, f, vertical)
    if eyes and kind in ("hero", "look") and shot.get("actors") and shot.get("yacht"):
        p = eye_world(shot, f)
    c, look, fov, roll = camgeo.camera_world({**shot, "camera": cam}, f, jitter=False)
    sx, sy, _ = camgeo.project(c, look, roll, fov, aspect, p)
    return sx, sy


def dual_frame_report(shot, main_aspect=16 / 9, step=6):
    """Worst-case subject offsets of a dual-frame shot: max |x - 0.5| in the 16:9 master and in the 9:16 vertical."""
    cams = shot.get("cameras") or {}
    main, vert = cams.get("main") or shot["camera"], cams.get("vertical")
    vspec = shot.get("vertical")
    worst_main = worst_vert = 0.0
    behind = False
    frames = list(range(shot["from"], shot["to"], step)) + [shot["to"] - 1]
    for f in frames:
        sx, _ = project_subject(shot, main, main, f, main_aspect, vspec)
        if sx is None:
            behind = True
            continue
        worst_main = max(worst_main, abs(sx - 0.5))
        if vert:
            vx, _ = project_subject(shot, main, vert, f, VERTICAL[0] / VERTICAL[1], vspec, eyes=True)
            if vx is None:
                behind = True
                continue
            worst_vert = max(worst_vert, abs(vx - 0.5))
    return {"main": round(worst_main, 4), "vertical": round(worst_vert, 4) if vert else None, "behind": behind}
