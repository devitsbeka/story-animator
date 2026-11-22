"""
Cinematic camera presets as pure functions (no Blender), producing episode.json camera tracks.

The 36 presets of atlas/ATLAS_CINEMA_AGENT_KIT/03_CATALOGS/camera_presets.yaml, written in the house style:
  - the shot's SUBJECT is always dead centre horizontally (|x - 0.5| ~ 0), except where the preset is a
    POV / insert or a whip pan between two subjects (the direction meta says so);
  - the camera always moves (continuous, eased, motivated motion);
  - keys every 3 frames with ease 'linear' between them, so the renderer reproduces the eased path exactly;
  - fov is VERTICAL degrees; lenses are chosen as 35 mm full-frame equivalents per emotion (PIXAR_RECIPE 3.5),
    converted for the 9:16 frame on the diagonal (see camgeo.lens_to_vfov);
  - camera height follows PIXAR_RECIPE 3.6 (eye level neutral, low = resolve/power, high = vulnerable).

Every preset returns {"camera": {...episode camera...}, "direction": {...meta...}}:
  camera.space is 'yacht' when the subject rides the yacht (the camera then heaves with the boat like an
  operator on deck) and 'world' otherwise. All design maths is done in world space; the yacht export inverts
  the renderer's transforms (heading-only for the camera, full keyed pitch/roll/sink for the look), so far-away
  world targets (the island) stay exactly where they were designed even when the boat is tilted on the reef.
  direction = {preset, motivation, emotion, size [start, end], lens_mm [start, end], subject {kind, track},
               pov, insert, centre_from, handheld, ...} for the shot validator.

Usage:
    import camera_presets as CP
    hero = CP.hero_subject(yacht, local=[0, 1.9, 4.7], rotY=0)
    c = CP.dolly_in(560, 668, hero, size=("MS", "MCU"), emotion="fear")
    shot["camera"], shot["direction"] = c["camera"], c["direction"]
"""
import math

try:
    from . import camgeo as G
except ImportError:  # run as a script / imported with factory/direction on sys.path
    import camgeo as G

ASPECT = 9 / 16
STEP = 3

# ------------------------------------------------------------------ lens / height language (PIXAR_RECIPE 3.5, 3.6)
LENS_BY_EMOTION = {
    "isolation": 20, "panic": 20, "vast": 21, "disorientation": 21,
    "establishing": 24, "environment": 24, "action": 28, "energy": 28, "scale": 24,
    "neutral": 35, "with_him": 35, "calm": 35, "procedure": 35,
    "honest": 50, "vo": 50, "decision": 50, "dialogue": 50, "worry": 50,
    "fear": 65, "intimate": 75, "emotion": 75, "realization": 85, "shock": 85,
    "threat": 110, "voyeur": 120, "watched": 120,
}
LENS_BY_SIZE = {"EWS": 24, "WS": 28, "MS": 35, "MCU": 50, "CU": 75, "ECU": 85}
ANGLE_EL = {"eye": 3.0, "low": -14.0, "high": 28.0, "bird": 75.0, "top": 88.0}

# hero anchor heights (m) for a 1.8 m character, scaled by the actor height
AIM_H = {"feet": 0.1, "knees": 0.5, "sit": 0.78, "hands": 1.15, "chest": 1.3, "face": 1.55, "eye": 1.64, "head_top": 1.8}


def pick_lens(emotion=None, size=None, default=35):
    if emotion in LENS_BY_EMOTION:
        return LENS_BY_EMOTION[emotion]
    if size in LENS_BY_SIZE:
        return LENS_BY_SIZE[size]
    return default


def frame_h_of(size, subj_h=1.8):
    """Size name (EWS..ECU) or explicit metres -> frame height at the subject (m)."""
    if isinstance(size, (int, float)):
        return float(size)
    return G.SIZE_FRAME_H[size] * subj_h / 1.8


def pair(v):
    if isinstance(v, (list, tuple)) and len(v) == 2 and not isinstance(v[0], (list, tuple)):
        return tuple(v)
    return (v, v)


# ------------------------------------------------------------------ subjects
class Subject:
    """What the shot is about. point(f, aim) -> world point; facing(f) -> world yaw (rotY convention)."""

    def __init__(self, point_fn, facing_fn=None, height=1.8, kind="hero", yacht=None, floor=0.6, name=None, profile=None):
        self._p = point_fn
        self._yaw = facing_fn or (lambda f: 0.0)
        self.height = height
        self.kind = kind
        self.yacht = yacht
        self.floor = floor          # minimum world camera height (water / deck clearance)
        self.name = name or kind
        self.profile = profile      # >>> polish_camera: camgeo.HeroProfile (real head size / eye height) or None

    def frame_h(self, size):
        """size name or metres -> frame height at the subject; a profiled hero uses his measured landmarks."""
        if self.profile is not None and isinstance(size, str):
            return self.profile.frame_h(size, self.height)
        return frame_h_of(size, self.height)

    def classify(self, frame_h):
        if self.profile is not None:
            return self.profile.classify(frame_h, self.height)
        return G.classify_size(frame_h, self.height)

    def point(self, f, aim=None):
        return self._p(f, aim)

    def facing(self, f):
        return self._yaw(f)


PROFILE_AIMS = {"eye": "eye", "brow": "brow", "chin": "chin", "head_top": "top", "top": "top", "chest": "chest", "waist": "waist"}


def hero_subject(yacht, local, rotY, height=1.8, name="hero", stance=None, profile=None, shot_id=None, acting_stance=None):
    """A character standing on the yacht (feet at `local`, facing rotY in yacht space).
    profile (camgeo.HeroProfile): aim points come from the rig's measured landmarks; with shot_id they follow the
    measured performance of that shot (head lowered by a brace / look-down / lean), else acting_stance's pose."""
    def pt(f, aim):
        aim = aim or "chest"
        if aim == "chest" and stance == "sit":
            aim = "sit"
        if profile is not None and isinstance(aim, str) and (aim in PROFILE_AIMS or aim in ("face", "sit")):
            if aim == "face":
                a, b = profile.local("brow", height, shot_id, f, acting_stance), profile.local("chin", height, shot_id, f, acting_stance)
                q = G.vlerp(a, b, 0.5)
            else:
                q = profile.local(PROFILE_AIMS.get(aim, "chest"), height, shot_id, f, acting_stance)
            q = G.rot_yv(rotY, q)
            return G.YachtFrame(yacht, f).body_to_world([local[0] + q[0], local[1] + q[1], local[2] + q[2]])
        h = AIM_H[aim] * height / 1.8 if isinstance(aim, str) else float(aim)
        return G.YachtFrame(yacht, f).body_to_world([local[0], local[1] + h, local[2]])

    def yaw(f):
        return (yacht["heading"] if yacht else 0.0) + rotY

    return Subject(pt, yaw, height, "hero", yacht, floor=0.6, name=name, profile=profile)


def object_subject(yacht, local, size=0.3, facing=0.0, name="object"):
    """A prop / detail riding the yacht (yacht-local point)."""
    def pt(f, aim):
        off = 0.0 if aim in (None, "chest", "centre") else (float(aim) if not isinstance(aim, str) else 0.0)
        return G.YachtFrame(yacht, f).body_to_world([local[0], local[1] + off, local[2]])
    return Subject(pt, lambda f: (yacht["heading"] if yacht else 0.0) + facing, size, "object", yacht, floor=0.6, name=name)


def world_subject(point, facing=0.0, height=1.8, kind="place", yacht=None, name=None, floor=0.6):
    """A fixed world point (island beach, fire, reef, the yacht as seen from afar)."""
    p = list(point)
    pfn = point if callable(point) else (lambda f, aim: list(p))
    return Subject(pfn, lambda f: facing, height, kind, yacht, floor=floor, name=name or kind)


def moving_subject(track, facing=0.0, height=1.8, kind="place", yacht=None, name=None):
    """A world point that moves: track = [[f, [x,y,z]], ...] (linear, hold outside)."""
    ks = sorted(track, key=lambda k: k[0])

    def pt(f, aim):
        if f <= ks[0][0]:
            return list(ks[0][1])
        if f >= ks[-1][0]:
            return list(ks[-1][1])
        for (a, pa), (b, pb) in zip(ks, ks[1:]):
            if a <= f <= b:
                return G.vlerp(pa, pb, (f - a) / max(1e-9, b - a))
        return list(ks[-1][1])
    return Subject(pt, lambda f: facing, height, kind, yacht, name=name or kind)


# ------------------------------------------------------------------ core samplers
def _frames(f0, f1):
    f = f0
    while True:
        yield f
        if f >= f1:
            break
        f = min(f1, f + STEP)


def _lerp_log(a, b, t):
    return math.exp(G.lerp(math.log(a), math.log(b), t))


def _finish(name, keys_world, subj_track, subj, *, motivation, emotion, sizes, lenses, space=None,
            handheld=0.12, drift=0.05, extra=None, aspect=ASPECT):
    """World keys -> episode camera (yacht or world space) + direction meta."""
    yacht = subj.yacht if subj is not None else None
    if space is None:
        space = "yacht" if yacht else "world"
    col = None
    if COLLIDE and yacht:                       # polish_camera: never inside walls / consoles, face never occluded
        keys_world, col = avoid_collisions(keys_world, subj_track, yacht, aspect)
    keys = []
    for k in keys_world:
        cam, look = k["cam"], k["look"]
        if space == "yacht" and yacht:
            yf = G.YachtFrame(yacht, k["f"])
            cam, look = yf.world_to_cam(cam), yf.world_to_body(look)
        kk = {"f": k["f"], "cam": [round(x, 4) for x in cam], "look": [round(x, 4) for x in look],
              "fov": round(k["fov"], 3), "ease": "linear"}
        if k.get("roll"):
            kk["roll"] = round(k["roll"], 3)
        keys.append(kk)
    d = {"preset": name, "motivation": motivation, "emotion": emotion,
         "size": list(sizes), "lens_mm": [round(lenses[0], 1), round(lenses[1], 1)],
         "subject": {"kind": subj.kind if subj else "look", "name": subj.name if subj else "look",
                     "height": subj.height if subj else 1.8,
                     "track": [[f, [round(x, 3) for x in p]] for f, p in subj_track]},
         "pov": False, "insert": False, "handheld": handheld}
    if col:
        d["collision_fix"] = col
    if extra:
        d.update(extra)
    return {"camera": {"space": space, "keys": keys, "handheld": handheld, "drift": drift}, "direction": d}


# >>> polish_camera: collision avoidance against the yacht proxy (camgeo.YachtProxy, exported from the real geometry)
COLLIDE = True
CLEARANCE = 0.22        # metres of air around the lens (near clip + no wall filling the frame edge)
LOS_MARGIN = 0.03       # the camera -> subject sight line keeps this far from any surface


def _rot_between(a, b, v):
    """rotate v by the rotation taking unit a to unit b (Rodrigues)."""
    ax = G.cross(a, b)
    s_ = G.norm(ax)
    c = max(-1.0, min(1.0, G.dot(a, b)))
    if s_ < 1e-9:
        return list(v)
    k = G.mul(ax, 1 / s_)
    ang = math.atan2(s_, c)
    return G.add(G.add(G.mul(v, math.cos(ang)), G.mul(G.cross(k, v), math.sin(ang))), G.mul(k, G.dot(k, v) * (1 - math.cos(ang))))


def _cam_ok(P, yf, cam, S):
    b = yf.world_to_body(cam)
    if P.sdf(b) < CLEARANCE:
        return False
    sb = yf.world_to_body(S)
    L = G.norm(G.sub(sb, b))
    if L < 0.3:
        return True
    end = G.add(b, G.mul(G.sub(sb, b), (L - 0.18) / L))     # stop short of the subject itself
    return P.blocked(b, end, LOS_MARGIN) is None


def avoid_collisions(keys_world, track, yacht, aspect=ASPECT, proxy=None):
    """Move every key whose lens is inside / against the yacht (or whose sight line to the subject crosses it)
    to the nearest clear spot: slide along the camera->subject line and/or rise, the slide smoothed over
    neighbouring keys (no pops), the fov widened to keep the frame height at the subject, and the look turned
    with the camera so the subject keeps its screen position. Returns (keys, report or None)."""
    P = proxy or G.yacht_proxy()
    if P is None or not keys_world:
        return keys_world, None
    tr = {f: p for f, p in track}
    sol = []
    bad = 0
    for k in keys_world:
        S = tr.get(k["f"], k["look"])
        yf = G.YachtFrame(yacht, k["f"])
        cam = k["cam"]
        if _cam_ok(P, yf, cam, S):
            sol.append((0.0, 0.0))
            continue
        bad += 1
        best = None
        D = G.norm(G.sub(S, cam))
        for dz in (0.0, 0.15, 0.3, 0.45, 0.6, 0.8, 1.0, 1.3, 1.6, 2.0):
            for i in range(0, 18):
                t = i * 0.05
                if D * (1 - t) < 0.45:
                    break
                c = G.add(G.add(cam, G.mul(G.sub(S, cam), t)), [0, dz, 0])
                if _cam_ok(P, yf, c, S):
                    cost = t * D + 0.8 * dz
                    if best is None or cost < best[0]:
                        best = (cost, t, dz)
                    break
        sol.append((best[1], best[2]) if best else (0.0, 0.0))
    if not bad:
        return keys_world, None
    n = len(sol)
    W = 4
    mx = [tuple(max(sol[j][c] for j in range(max(0, i - W), min(n, i + W + 1))) for c in (0, 1)) for i in range(n)]
    sm = [tuple(sum(mx[j][c] for j in range(max(0, i - W), min(n, i + W + 1))) / (min(n, i + W + 1) - max(0, i - W)) for c in (0, 1)) for i in range(n)]
    out, worst, fails = [], [0.0, 0.0], []
    for k, (t, dz), raw in zip(keys_world, sm, sol):
        S = tr.get(k["f"], k["look"])
        yf = G.YachtFrame(yacht, k["f"])
        cam = k["cam"]

        def moved(tt, zz):
            return G.add(G.add(cam, G.mul(G.sub(S, cam), tt)), [0, zz, 0])
        c = moved(t, dz)
        if not _cam_ok(P, yf, c, S):
            c = moved(*raw)
            t, dz = raw
            if not _cam_ok(P, yf, c, S):
                fails.append(k["f"])
        if t == 0 and dz == 0:
            out.append(k)
            continue
        worst = [max(worst[0], t * G.norm(G.sub(S, cam))), max(worst[1], dz)]
        d0, d1 = G.norm(G.sub(S, cam)), G.norm(G.sub(S, c))
        fh = G.frame_height_at(d0, k["fov"])
        fov = max(k["fov"], min(100.0, math.degrees(2 * math.atan(fh / (2 * max(0.05, d1))))))
        look = G.add(c, _rot_between(G.unit(G.sub(S, cam)), G.unit(G.sub(S, c)), G.sub(k["look"], cam)))
        kk = dict(k)
        kk.update({"cam": c, "look": look, "fov": fov})
        out.append(kk)
    rep = {"keys_moved": sum(1 for t, z in sm if t or z), "max_slide_m": round(worst[0], 3), "max_rise_m": round(worst[1], 3)}
    if fails:
        rep["unresolved_frames"] = fails[:8]
    return out, rep
# <<< polish_camera


def _clear(cam, floor):
    if cam[1] < floor:
        cam = [cam[0], floor, cam[2]]
    return cam


def _orbit(name, f0, f1, subj, *, az=(0, 0), el=(3, 3), size=("MS", "MS"), dist=None, lens=None, emotion="neutral",
           ease="move", aim=None, motivation="follow_subject", lag=0, headroom=True, extra=None, handheld=0.12,
           roll=(0, 0), aspect=ASPECT, space=None, keep_size=None):
    """Spherical rig around the subject: az (deg from the subject's facing; 0 = in front of his face, +90 = his
    left... i.e. +az swings counter-clockwise seen from above), el (deg above the aim point), size or dist."""
    az, el, size, roll = pair(az), pair(el), pair(size), pair(roll)
    s0 = size[0]
    lens = pair(lens if lens is not None else pick_lens(emotion, s0 if isinstance(s0, str) else None))
    fh = (subj.frame_h(size[0]), subj.frame_h(size[1]))
    eye_max = 1.3 * subj.profile.frame_h("MS", subj.height) if subj.profile is not None else 1.1 * subj.height / 1.8
    keys, track = [], []
    for f in _frames(f0, f1):
        u = (f - f0) / max(1, f1 - f0)
        e = G.EASE[ease](u)
        mm = _lerp_log(lens[0], lens[1], e)
        vfov = G.lens_to_vfov(mm, aspect)
        fhe = _lerp_log(fh[0], fh[1], e)
        if keep_size is not None:          # dolly zoom: keep the frame height at the subject constant
            fhe = keep_size
        D = G.lerp(dist[0], dist[1], e) if dist else G.distance_for(fhe, vfov)
        a = math.radians(G.lerp(az[0], az[1], e))
        elv = math.radians(G.lerp(el[0], el[1], e))
        cur_aim = aim or ("eye" if subj.kind == "hero" and fhe <= eye_max else None)
        S = subj.point(f, cur_aim)
        S_cam = subj.point(max(f0, f - lag), cur_aim) if lag else S
        yaw = subj.facing(f) + a
        cam = [S_cam[0] + D * math.cos(elv) * math.sin(yaw), S_cam[1] + D * math.sin(elv), S_cam[2] + D * math.cos(elv) * math.cos(yaw)]
        cam = _clear(cam, subj.floor)
        look = list(S)
        if headroom and subj.kind == "hero" and cur_aim == "eye":
            if subj.profile is not None:     # polish_camera: eyes exactly on the eye line (0.38 from the top)
                look = _place_y(cam, S, vfov, G.EYE_LINE)
            else:
                look[1] -= 0.10 * G.frame_height_at(G.norm(G.sub(S, cam)), vfov)   # eyes at ~0.40 from the top
        keys.append({"f": f, "cam": cam, "look": look, "fov": vfov, "roll": G.lerp(roll[0], roll[1], e)})
        track.append((f, S))
    sizes = [s if isinstance(s, str) else subj.classify(s) for s in size]
    return _finish(name, keys, track, subj, motivation=motivation, emotion=emotion, sizes=sizes, lenses=lens,
                   handheld=handheld, extra=extra, aspect=aspect, space=space)


def _line(name, f0, f1, subj, cam_a, cam_b, *, lens=35, emotion="neutral", ease="move", aim=None,
          motivation="follow_subject", look_a=None, look_b=None, track_look=False, extra=None, handheld=0.1,
          aspect=ASPECT, space=None, path=None, aims=None):
    """Camera along a straight line (or Catmull-Rom `path` of world points), look locked on the subject
    (or interpolated look_a -> look_b, in which case the look IS the subject track; or, with aims=(from, to),
    interpolated between two of the subject's aim points evaluated every frame, so a tilt follows a moving head)."""
    lens = pair(lens)
    keys, track = [], []
    for f in _frames(f0, f1):
        u = (f - f0) / max(1, f1 - f0)
        e = G.EASE[ease](u)
        cam = catmull(path, e) if path else G.vlerp(cam_a, cam_b, e)
        cam = _clear(cam, subj.floor)
        if aims is not None:
            look = G.vlerp(subj.point(f, aims[0]), subj.point(f, aims[1]), e)
            S = look
        elif look_a is not None:
            look = G.vlerp(look_a, look_b, e)
            S = look
        else:
            S = subj.point(f, aim)
            look = S
        mm = _lerp_log(lens[0], lens[1], e)
        keys.append({"f": f, "cam": cam, "look": look, "fov": G.lens_to_vfov(mm, aspect)})
        track.append((f, S))
    fh0 = G.frame_height_at(G.norm(G.sub(track[0][1], keys[0]["cam"])), keys[0]["fov"])
    fh1 = G.frame_height_at(G.norm(G.sub(track[-1][1], keys[-1]["cam"])), keys[-1]["fov"])
    sizes = [subj.classify(fh0), subj.classify(fh1)]
    return _finish(name, keys, track, subj, motivation=motivation, emotion=emotion, sizes=sizes, lenses=lens,
                   handheld=handheld, extra=extra, aspect=aspect, space=space)


def catmull(pts, t):
    """Uniform Catmull-Rom through world control points, t in [0, 1]."""
    n = len(pts)
    if n == 1:
        return list(pts[0])
    if n == 2:
        return G.vlerp(pts[0], pts[1], t)
    seg = min(n - 2, int(t * (n - 1)))
    lt = t * (n - 1) - seg
    p0 = pts[max(0, seg - 1)]; p1 = pts[seg]; p2 = pts[seg + 1]; p3 = pts[min(n - 1, seg + 2)]
    out = []
    for a, b, c, d in zip(p0, p1, p2, p3):
        out.append(0.5 * ((2 * b) + (-a + c) * lt + (2 * a - 5 * b + 4 * c - d) * lt * lt + (-a + 3 * b - 3 * c + d) * lt ** 3))
    return out


def _place_y(cam, T, vfov, ty):
    """Look point that puts T at screen y = ty (0 top .. 1 bottom) and x = 0.5: pitch the view down/up."""
    if abs(ty - 0.5) < 1e-6:
        return list(T)
    d = G.sub(T, cam)
    dist = G.norm(d)
    yaw = math.atan2(d[0], d[2])
    pitch = math.atan2(d[1], math.hypot(d[0], d[2]))
    pitch -= math.atan((0.5 - ty) * 2 * math.tan(math.radians(vfov) / 2))
    return G.add(cam, [dist * math.cos(pitch) * math.sin(yaw), dist * math.sin(pitch), dist * math.cos(pitch) * math.cos(yaw)])


def _sph(S, yaw, D, el_deg):
    elv = math.radians(el_deg)
    return [S[0] + D * math.cos(elv) * math.sin(yaw), S[1] + D * math.sin(elv), S[2] + D * math.cos(elv) * math.cos(yaw)]


def _setup(subj, f, az, el, size, lens, aim=None, aspect=ASPECT):
    """Static camera placement: returns (cam, S, vfov, D, right_vector)."""
    vfov = G.lens_to_vfov(lens, aspect)
    D = G.distance_for(subj.frame_h(size), vfov)
    S = subj.point(f, aim)
    yaw = subj.facing(f) + math.radians(az)
    cam = _sph(S, yaw, D, el)
    x, _, _ = G.basis(cam, S, 0)
    return cam, S, vfov, D, x


# =================================================================== the 36 presets
# Common keyword args: size (name or metres of frame height), lens (mm, 35mm-FF equivalent), emotion, ease,
# az (deg around the subject from his facing), angle ('eye' | 'low' | 'high' | 'bird') or el (deg), aim.

def dolly_in(f0, f1, subj, size=("MS", "MCU"), az=0, angle="eye", el=None, emotion="tension", lens=None, ease="move", aim=None, **kw):
    """Push in along the view axis: growing realization / tension."""
    e = el if el is not None else ANGLE_EL[angle]
    return _orbit("dolly_in", f0, f1, subj, az=az, el=e, size=size, lens=lens, emotion=emotion, ease=ease, aim=aim, motivation="tension_push", **kw)


def dolly_out(f0, f1, subj, size=("MCU", "WS"), az=0, angle="eye", el=None, emotion="isolation", lens=None, ease="move", aim=None, **kw):
    """Pull back along the view axis: isolation / reveal of scale."""
    e = el if el is not None else ANGLE_EL[angle]
    return _orbit("dolly_out", f0, f1, subj, az=az, el=e, size=size, lens=lens, emotion=emotion, ease=ease, aim=aim, motivation="reveal", **kw)


def _truck(name, sign, f0, f1, subj, size="MS", az=30, angle="eye", el=None, amount=None, emotion="neutral", lens=None, ease="move", aim=None, **kw):
    e = el if el is not None else ANGLE_EL[angle]
    lens = lens or pick_lens(emotion, size if isinstance(size, str) else None)
    cam, S, vfov, D, x = _setup(subj, f0, az, e, size, lens, aim)
    amt = amount if amount is not None else 0.35 * D
    a = G.add(cam, G.mul(x, -sign * amt / 2))
    b = G.add(cam, G.mul(x, sign * amt / 2))
    return _line(name, f0, f1, subj, a, b, lens=lens, emotion=emotion, ease=ease, aim=aim, motivation="follow_subject", **kw)


def truck_left(f0, f1, subj, **kw):
    """Lateral move to camera-left, pan compensating so the subject stays centred (parallax on the background)."""
    return _truck("truck_left", -1, f0, f1, subj, **kw)


def truck_right(f0, f1, subj, **kw):
    """Lateral move to camera-right, subject held centred."""
    return _truck("truck_right", 1, f0, f1, subj, **kw)


def _pedestal(name, sign, f0, f1, subj, size="MS", az=20, angle="eye", el=None, amount=None, emotion="neutral", lens=None, ease="move", aim=None, **kw):
    e = el if el is not None else ANGLE_EL[angle]
    lens = lens or pick_lens(emotion, size if isinstance(size, str) else None)
    cam, S, vfov, D, x = _setup(subj, f0, az, e, size, lens, aim)
    amt = amount if amount is not None else 0.3 * D
    a = G.add(cam, [0, -sign * amt / 2, 0])
    b = G.add(cam, [0, sign * amt / 2, 0])
    return _line(name, f0, f1, subj, a, b, lens=lens, emotion=emotion, ease=ease, aim=aim, motivation="character_attention", **kw)


def pedestal_up(f0, f1, subj, **kw):
    """Camera rises vertically, tilting to hold the subject (resolve building)."""
    return _pedestal("pedestal_up", 1, f0, f1, subj, **kw)


def pedestal_down(f0, f1, subj, **kw):
    """Camera sinks vertically, holding the subject (weight, dread)."""
    return _pedestal("pedestal_down", -1, f0, f1, subj, **kw)


def crane_rise(f0, f1, subj, size=("MS", "WS"), az=(20, 30), el=(4, 32), emotion="vulnerable", lens=None, ease="move", aim=None, **kw):
    """Boom up and back: the hero gets small, the world gets big."""
    return _orbit("crane_rise", f0, f1, subj, az=az, el=el, size=size, lens=lens or pick_lens(emotion, "WS"), emotion=emotion, ease=ease, aim=aim, motivation="reveal", **kw)


def crane_descend(f0, f1, subj, size=("EWS", "WS"), az=(30, 20), el=(40, 6), emotion="arrival", lens=None, ease="arrive", aim=None, **kw):
    """Boom down from high into the subject's world: arrival, focus."""
    return _orbit("crane_descend", f0, f1, subj, az=az, el=el, size=size, lens=lens or 28, emotion=emotion, ease=ease, aim=aim, motivation="follow_subject", **kw)


def orbit_cw(f0, f1, subj, size="MS", az=(30, -10), angle="eye", el=None, emotion="neutral", lens=None, ease="move", aim=None, **kw):
    """Orbit clockwise seen from above (azimuth decreasing)."""
    e = el if el is not None else ANGLE_EL[angle]
    a = pair(az)
    if a[1] > a[0]:
        a = (a[1], a[0])
    return _orbit("orbit_cw", f0, f1, subj, az=a, el=e, size=size, lens=lens, emotion=emotion, ease=ease, aim=aim, motivation="character_attention", **kw)


def orbit_ccw(f0, f1, subj, size="MS", az=(-10, 30), angle="eye", el=None, emotion="neutral", lens=None, ease="move", aim=None, **kw):
    """Orbit counter-clockwise seen from above (azimuth increasing)."""
    e = el if el is not None else ANGLE_EL[angle]
    a = pair(az)
    if a[1] < a[0]:
        a = (a[1], a[0])
    return _orbit("orbit_ccw", f0, f1, subj, az=a, el=e, size=size, lens=lens, emotion=emotion, ease=ease, aim=aim, motivation="character_attention", **kw)


def arc_track(f0, f1, subj, size=("MS", "MCU"), az=(40, 15), angle="eye", el=None, emotion="worry", lens=None, ease="move", aim=None, **kw):
    """Partial arc with a gentle push: attention closing in on the hero."""
    e = el if el is not None else ANGLE_EL[angle]
    return _orbit("arc_track", f0, f1, subj, az=az, el=e, size=size, lens=lens, emotion=emotion, ease=ease, aim=aim, motivation="character_attention", **kw)


def follow_tracking(f0, f1, subj, size="MS", az=150, angle="eye", el=None, emotion="action", lens=None, lag=6, creep=0.08, ease="linear", aim=None, **kw):
    """Follow a (moving) subject from a fixed relative offset with a little lag, creeping in by `creep`."""
    e = el if el is not None else ANGLE_EL[angle]
    s = pair(size)
    s = (frame_h_of(s[0], subj.height), frame_h_of(s[1], subj.height) * (1 - creep))
    return _orbit("follow_tracking", f0, f1, subj, az=az, el=e, size=s, lens=lens or pick_lens(emotion, "MS"), emotion=emotion, ease=ease, aim=aim, lag=lag, motivation="follow_subject", **kw)


def over_shoulder(f0, f1, hero, target, shoulder="right", back=(1.9, 1.5), above=(0.45, 0.4), side=0.32, lens=(32, 36), emotion="threat",
                  ease="move", aspect=ASPECT, target_y=0.5, **kw):
    """Behind the hero's shoulder looking at what he looks at. The TARGET is the subject and sits dead centre;
    the camera sits on the target->hero line (offset `side` m to one shoulder), so in 9:16 the hero's head and
    shoulder fill the lower frame and the target sits on the centre line above/behind it."""
    lens = pair(lens)
    keys, track = [], []
    sgn = 1 if shoulder == "right" else -1
    for f in _frames(f0, f1):
        u = (f - f0) / max(1, f1 - f0)
        e = G.EASE[ease](u)
        H = hero.point(f, "eye")
        T = target.point(f, None)
        dirp = G.unit([T[0] - H[0], 0, T[2] - H[2]])
        right = [-dirp[2], 0, dirp[0]]          # hero's right hand side when facing the target (y up)
        b, h = G.lerp(back[0], back[1], e), G.lerp(above[0], above[1], e)
        cam = [H[0] - dirp[0] * b + right[0] * side * sgn, H[1] + h, H[2] - dirp[2] * b + right[2] * side * sgn]
        cam = _clear(cam, hero.floor)
        mm = _lerp_log(lens[0], lens[1], e)
        vfov = G.lens_to_vfov(mm, aspect)
        look = _place_y(cam, T, vfov, target_y)
        keys.append({"f": f, "cam": cam, "look": look, "fov": vfov})
        track.append((f, T))
    extra = {"ots": True, "foreground": hero.name}
    tgt = Subject(target._p, target._yaw, target.height, target.kind, hero.yacht, name=target.name)
    return _finish("over_shoulder", keys, track, tgt, motivation="character_attention", emotion=emotion,
                   sizes=["OTS", "OTS"], lenses=lens, extra=extra, handheld=kw.get("handheld", 0.1), aspect=aspect)


def pov(f0, f1, hero, target, push=0.12, lens=(50, 58), emotion="threat", ease="move", aspect=ASPECT, **kw):
    """Through the hero's eyes at the target, a slow subjective push (lens tightens by `push`)."""
    lens = pair(lens)
    keys, track = [], []
    for f in _frames(f0, f1):
        u = (f - f0) / max(1, f1 - f0)
        e = G.EASE[ease](u)
        H = hero.point(f, "eye")
        T = target.point(f, None)
        d = G.unit(G.sub(T, H))
        cam = G.add(H, G.mul(d, 0.12 + push * e))
        mm = _lerp_log(lens[0], lens[1], e)
        keys.append({"f": f, "cam": cam, "look": T, "fov": G.lens_to_vfov(mm, aspect)})
        track.append((f, T))
    tgt = Subject(target._p, target._yaw, target.height, target.kind, hero.yacht, name=target.name)
    return _finish("pov", keys, track, tgt, motivation="character_attention", emotion=emotion, sizes=["POV", "POV"],
                   lenses=lens, extra={"pov": True, "pov_of": hero.name}, handheld=kw.get("handheld", 0.18), aspect=aspect)


def low_reveal(f0, f1, subj, size=("MCU", "MS"), az=(15, 25), el=(-18, -8), emotion="decision", lens=None, ease="move", aim=None, **kw):
    """Low angle rising slightly while pulling back: the hero's resolve (first low angle = turning point)."""
    return _orbit("low_reveal", f0, f1, subj, az=az, el=el, size=size, lens=lens or 28, emotion=emotion, ease=ease, aim=aim, motivation="reveal", **kw)


def high_reveal(f0, f1, subj, target, back=(2.2, 5.0), above=(0.3, 6.0), side=0.0, lens=(30, 26), emotion="vulnerable", ease="move",
                aspect=ASPECT, reveal_at=0.55, target_y=0.5, **kw):
    """Behind the subject on the subject->target line, rising high: the look travels from the subject to the
    target. Both lie in the camera's vertical centre plane, so both stay horizontally centred all the way;
    target_y lifts the revealed target toward the upper third so the subject keeps the lower frame."""
    lens = pair(lens)
    keys, track = [], []
    for f in _frames(f0, f1):
        u = (f - f0) / max(1, f1 - f0)
        e = G.EASE[ease](u)
        S = subj.point(f, None)
        T = target.point(f, None)
        dirp = G.unit([T[0] - S[0], 0, T[2] - S[2]])
        b, h = G.lerp(back[0], back[1], e), G.lerp(above[0], above[1], e)
        cam = _clear([S[0] - dirp[0] * b + dirp[2] * side, S[1] + h, S[2] - dirp[2] * b - dirp[0] * side], subj.floor)
        w = G.EASE["move"](min(1.0, e / max(1e-6, reveal_at)))
        mm = _lerp_log(lens[0], lens[1], e)
        vfov = G.lens_to_vfov(mm, aspect)
        aimpt = G.vlerp(S, T, w)
        # ease the revealed target up to target_y so the subject stays in the lower frame (still x-centred)
        look = _place_y(cam, aimpt, vfov, G.lerp(0.5, target_y, w))
        keys.append({"f": f, "cam": cam, "look": look, "fov": vfov})
        track.append((f, aimpt))
    return _finish("high_reveal", keys, track, subj, motivation="reveal", emotion=emotion, sizes=["MS", "EWS"], lenses=lens,
                   extra={"reveal_target": target.name}, handheld=kw.get("handheld", 0.06), aspect=aspect)


def establishing(f0, f1, subj, frame_h=None, az=(-4, 4), el=(10, 8), push=0.12, emotion="establishing", lens=None, ease="move", aim=None, **kw):
    """EWS of a location: high-ish, wide lens, slow push and a few degrees of orbit."""
    fh = frame_h or max(40.0, subj.height * 2.5)
    return _orbit("establishing", f0, f1, subj, az=az, el=el, size=(fh, fh * (1 - push)), lens=lens or pick_lens(emotion, "EWS"),
                  emotion=emotion, ease=ease, aim=aim, motivation="reveal", headroom=False, handheld=kw.pop("handheld", 0.05), **kw)


def extreme_closeup(f0, f1, subj, size=("ECU", 0.22), az=(10, 5), angle="eye", el=None, emotion="realization", lens=None, ease="move", aim=None, insert=None, **kw):
    """ECU on eyes / hands / a prop detail with a slow push (an insert when the subject is an object)."""
    e = el if el is not None else ANGLE_EL[angle]
    ins = insert if insert is not None else (subj.kind == "object")
    return _orbit("extreme_closeup", f0, f1, subj, az=az, el=e, size=size, lens=lens or 85, emotion=emotion, ease=ease, aim=aim,
                  motivation="tension_push", extra={"insert": ins}, handheld=kw.pop("handheld", 0.05), **kw)


def push_reveal(f0, f1, fg, target, back=(3.0, 0.6), above=(0.5, 1.1), side=0.55, lens=(30, 34), emotion="threat", ease="move", aspect=ASPECT, **kw):
    """Push forward past a foreground subject (the hero) toward the target, which is held dead centre."""
    lens = pair(lens)
    keys, track = [], []
    for f in _frames(f0, f1):
        u = (f - f0) / max(1, f1 - f0)
        e = G.EASE[ease](u)
        S = fg.point(f, "eye")
        T = target.point(f, None)
        dirp = G.unit([T[0] - S[0], 0, T[2] - S[2]])
        b, h = G.lerp(back[0], back[1], e), G.lerp(above[0], above[1], e)
        cam = _clear([S[0] - dirp[0] * b + dirp[2] * side, S[1] + h, S[2] - dirp[2] * b - dirp[0] * side], fg.floor)
        mm = _lerp_log(lens[0], lens[1], e)
        keys.append({"f": f, "cam": cam, "look": T, "fov": G.lens_to_vfov(mm, aspect)})
        track.append((f, T))
    tgt = Subject(target._p, target._yaw, target.height, target.kind, fg.yacht, name=target.name)
    return _finish("push_reveal", keys, track, tgt, motivation="reveal", emotion=emotion, sizes=["OTS", "WS"], lenses=lens,
                   extra={"foreground": fg.name}, handheld=kw.get("handheld", 0.08), aspect=aspect)


def pullback_reveal(f0, f1, subj, size=("MCU", "EWS"), az=(0, 25), el=(4, 35), emotion="isolation", lens=(40, 24), ease="move", aim=None, **kw):
    """Start tight on the subject, pull far back and up: isolation, scale."""
    return _orbit("pullback_reveal", f0, f1, subj, az=az, el=el, size=size, lens=lens, emotion=emotion, ease=ease, aim=aim, motivation="reveal", **kw)


def whip_pan(f0, f1, subj_from, subj_to, whip=8, size="MCU", az=25, angle="eye", el=None, lens=None, emotion="shock", aspect=ASPECT, **kw):
    """Camera placed for subj_to; the look whips from subj_from to subj_to in `whip` frames (keyed every frame
    there, direction slerped), then settles with a slow push. Centring applies from f0 + whip (direction.centre_from)."""
    e = el if el is not None else ANGLE_EL[angle]
    lens = lens or pick_lens(emotion, size if isinstance(size, str) else None)
    cam0, S, vfov, D, x = _setup(subj_to, f0, az, e, size, lens)
    keys, track = [], []
    fw = f0 + whip
    frames = sorted(set(_frames(f0, f1)) | set(range(f0, min(fw, f1) + 1)))   # every frame through the whip
    for f in frames:
        A, B = subj_from.point(f, None), subj_to.point(f, "eye" if subj_to.kind == "hero" else None)
        if subj_to.kind == "hero" and subj_to.profile is not None:   # eyes on the eye line (0.38 from the top)
            B = _place_y(cam0, B, vfov, G.EYE_LINE)
        elif subj_to.kind == "hero":   # eyes at ~0.40 from the top
            B = [B[0], B[1] - 0.10 * G.frame_height_at(G.norm(G.sub(B, cam0)), vfov), B[2]]
        if f < fw:
            w = G.EASE["crashIn"]((f - f0) / whip) if f > f0 else 0.0
            # slerp the view DIRECTION (a point lerp between a far and a near target swings through the camera)
            da, db = G.unit(G.sub(A, cam0)), G.unit(G.sub(B, cam0))
            om = math.acos(max(-1.0, min(1.0, G.dot(da, db))))
            if om < 1e-4:
                dv = db
            else:
                dv = G.add(G.mul(da, math.sin((1 - w) * om) / math.sin(om)), G.mul(db, math.sin(w * om) / math.sin(om)))
            look = G.add(cam0, G.mul(dv, G.norm(G.sub(B, cam0))))
            push = 0.0
        else:
            look = B
            push = G.EASE["arrive"]((f - fw) / max(1, f1 - fw)) * 0.12
        cam = G.add(cam0, G.mul(G.sub(B, cam0), push))
        keys.append({"f": f, "cam": cam, "look": look, "fov": vfov})
        track.append((f, subj_to.point(f, "eye" if subj_to.kind == "hero" else None)))
    return _finish("whip_pan", keys, track, subj_to, motivation="character_attention", emotion=emotion, sizes=[size, size],
                   lenses=(lens, lens), extra={"centre_from": fw, "whip_from": subj_from.name}, handheld=kw.get("handheld", 0.15), aspect=aspect)


def _tilt(name, f0, f1, subj, aim_from, aim_to, size="MS", az=15, angle="eye", el=None, lens=None, emotion="neutral", ease="move", creep=0.06, aspect=ASPECT, **kw):
    e = el if el is not None else ANGLE_EL[angle]
    lens = lens or pick_lens(emotion, size if isinstance(size, str) else None)
    cam0, _, vfov, D, _ = _setup(subj, f0, az, e, size, lens, aim_to)
    A, B = subj.point(f0, aim_from), subj.point(f0, aim_to)
    cam1 = G.add(cam0, G.mul(G.sub(B, cam0), creep))
    # polish_camera: the tilt follows the performance (A04: he leans 0.25 m into the switch panel while it tilts)
    return _line(name, f0, f1, subj, cam0, cam1, lens=lens, emotion=emotion, ease=ease, look_a=A, look_b=B, aims=(aim_from, aim_to),
                 motivation="character_attention", aspect=aspect, **kw)


def tilt_up(f0, f1, subj, aim_from="hands", aim_to="face", **kw):
    """Fixed-ish camera tilting up the subject (hands -> face): from action to emotion."""
    return _tilt("tilt_up", f0, f1, subj, aim_from, aim_to, **kw)


def tilt_down(f0, f1, subj, aim_from="face", aim_to="hands", **kw):
    """Tilt down the subject (face -> hands / object): from thought to action."""
    return _tilt("tilt_down", f0, f1, subj, aim_from, aim_to, **kw)


def _pan(name, f0, f1, subj, look_from, look_to, cam=None, lens=35, emotion="neutral", ease="move", creep=0.04, aspect=ASPECT, **kw):
    """Camera (nearly) fixed at `cam`, the look sweeps look_from -> look_to; the look is the subject track."""
    if cam is None:
        mid = G.vlerp(look_from, look_to, 0.5)
        yaw = subj.facing(f0)
        cam = _sph(mid, yaw, max(6.0, 1.2 * G.norm(G.sub(look_to, look_from))), 6)
    cam1 = G.add(cam, G.mul(G.sub(look_to, cam), creep))
    return _line(name, f0, f1, subj, cam, cam1, lens=lens, emotion=emotion, ease=ease, look_a=look_from, look_b=look_to,
                 motivation="follow_subject", aspect=aspect, **kw)


def pan_left(f0, f1, subj, look_from, look_to, **kw):
    """Pan following attention toward screen-left (look_from -> look_to, world points)."""
    return _pan("pan_left", f0, f1, subj, look_from, look_to, **kw)


def pan_right(f0, f1, subj, look_from, look_to, **kw):
    """Pan following attention toward screen-right."""
    return _pan("pan_right", f0, f1, subj, look_from, look_to, **kw)


def handheld_subtle(f0, f1, subj, size="MS", az=(20, 12), angle="eye", el=None, emotion="worry", lens=None, ease="move", aim=None, **kw):
    """Operator on deck: a small drift around the hero with gentle handheld noise."""
    e = el if el is not None else ANGLE_EL[angle]
    s = frame_h_of(size, subj.height)
    return _orbit("handheld_subtle", f0, f1, subj, az=az, el=e, size=(s, s * 0.94), lens=lens, emotion=emotion, ease=ease, aim=aim,
                  motivation="character_attention", handheld=kw.pop("handheld", 0.25), **kw)


def handheld_documentary(f0, f1, subj, size="MS", az=(35, 20), angle="eye", el=None, emotion="panic", lens=None, ease="linear", aim=None, **kw):
    """Reactive, documentary handheld for panic beats (noise amplitude at the recipe's 0.3 deg ceiling)."""
    e = el if el is not None else ANGLE_EL[angle]
    s = frame_h_of(size, subj.height)
    return _orbit("handheld_documentary", f0, f1, subj, az=az, el=e, size=(s, s * 0.9), lens=lens or 28, emotion=emotion, ease=ease, aim=aim,
                  motivation="tension_push", handheld=kw.pop("handheld", 0.3), **kw)


def stabilized_tracking(f0, f1, subj, size="WS", az=(95, 80), angle="eye", el=None, emotion="action", lens=None, ease="linear", aim=None, **kw):
    """Gimbal-smooth side track alongside the subject (profile, low noise)."""
    e = el if el is not None else ANGLE_EL[angle]
    return _orbit("stabilized_tracking", f0, f1, subj, az=az, el=e, size=size, lens=lens, emotion=emotion, ease=ease, aim=aim,
                  motivation="follow_subject", handheld=kw.pop("handheld", 0.03), **kw)


def tripod(f0, f1, subj, size="MS", az=10, angle="eye", el=None, emotion="calm", lens=None, creep=0.04, ease="linear", aim=None, **kw):
    """'Locked-off' composition that still breathes: a barely perceptible push (house rule: never static)."""
    e = el if el is not None else ANGLE_EL[angle]
    s = frame_h_of(size, subj.height)
    secs = max(1.0, (f1 - f0) / 30.0)
    return _orbit("tripod", f0, f1, subj, az=az, el=e, size=(s, s * (1 - creep * secs)), lens=lens, emotion=emotion, ease=ease, aim=aim,
                  motivation="character_attention", handheld=kw.pop("handheld", 0.0), **kw)


def dolly_zoom(f0, f1, subj, size="MCU", lens=(28, 70), az=0, angle="eye", el=None, emotion="realization", ease="move", aim=None, **kw):
    """Vertigo: dolly while zooming so the subject keeps its size and the background swells / shrinks."""
    e = el if el is not None else ANGLE_EL[angle]
    fh = frame_h_of(size, subj.height)
    return _orbit("dolly_zoom", f0, f1, subj, az=az, el=e, size=(fh, fh), lens=lens, emotion=emotion, ease=ease, aim=aim,
                  motivation="tension_push", keep_size=fh, **kw)


def rack_focus(f0, f1, subj, focus_from=None, size="MCU", az=20, angle="eye", el=None, emotion="realization", lens=None, ease="move", aim=None, **kw):
    """Slow push holding the subject; direction.focus records the focus pull from `focus_from` (a world point,
    e.g. a foreground prop) to the subject. (The renderer has no DOF keys yet; the meta is for when it does.)"""
    e = el if el is not None else ANGLE_EL[angle]
    s = frame_h_of(size, subj.height)
    out = _orbit("rack_focus", f0, f1, subj, az=az, el=e, size=(s, s * 0.92), lens=lens, emotion=emotion, ease=ease, aim=aim,
                 motivation="character_attention", **kw)
    fd = [[f, round(G.EASE["move"]((f - f0) / max(1, f1 - f0)), 3)] for f, _ in out["direction"]["subject"]["track"]]
    out["direction"]["focus"] = {"from": focus_from, "to": "subject", "blend": fd}
    return out


def parallax_reveal(f0, f1, subj, size="WS", az=60, angle="eye", el=None, amount=None, emotion="threat", lens=None, ease="move", aim=None, **kw):
    """A long lateral truck past foreground (rigging, rail, foliage) with the subject locked centre: depth layers slide."""
    e = el if el is not None else ANGLE_EL[angle]
    lens = lens or pick_lens(emotion, size if isinstance(size, str) else None)
    cam, S, vfov, D, x = _setup(subj, f0, az, e, size, lens, aim)
    amt = amount if amount is not None else 0.8 * D
    out = _line("parallax_reveal", f0, f1, subj, G.add(cam, G.mul(x, -amt / 2)), G.add(cam, G.mul(x, amt / 2)), lens=lens,
                emotion=emotion, ease=ease, aim=aim, motivation="reveal", **kw)
    return out


def orbit_track(f0, f1, subj, size="MS", az=(-30, 40), angle="eye", el=None, emotion="energy", lens=None, ease="move", aim=None, lag=3, **kw):
    """Orbit around a subject that is itself moving (the offset is re-based on the subject every frame)."""
    e = el if el is not None else ANGLE_EL[angle]
    return _orbit("orbit_track", f0, f1, subj, az=az, el=e, size=size, lens=lens, emotion=emotion, ease=ease, aim=aim, lag=lag,
                  motivation="follow_subject", **kw)


def product_turntable(f0, f1, subj, size=0.6, az=(-60, 60), el=15, lens=50, emotion="procedure", aim=None, **kw):
    """Constant-speed orbit around an object (insert / hero prop)."""
    return _orbit("product_turntable", f0, f1, subj, az=az, el=el, size=size, lens=lens, emotion=emotion, ease="linear", aim=aim,
                  motivation="follow_subject", extra={"insert": True}, headroom=False, handheld=kw.pop("handheld", 0.0), **kw)


def architecture_walkthrough(f0, f1, subj, path, lens=24, emotion="environment", ease="move", aim=None, **kw):
    """Camera glides through world control points (Catmull-Rom) at walking height, framing the subject."""
    return _line("architecture_walkthrough", f0, f1, subj, path[0], path[-1], lens=lens, emotion=emotion, ease=ease, aim=aim,
                 motivation="follow_subject", path=[list(p) for p in path], **kw)


def aerial_flyover(f0, f1, subj, altitude=(60, 45), dist=(240, 160), az=(-25, 10), lens=24, emotion="scale", ease="move", aim=None, aspect=ASPECT, **kw):
    """Drone pass high over the location, looking down at the subject (yacht, island, reef)."""
    alt, dst, az = pair(altitude), pair(dist), pair(az)
    keys, track = [], []
    for f in _frames(f0, f1):
        u = (f - f0) / max(1, f1 - f0)
        e = G.EASE[ease](u)
        S = subj.point(f, aim)
        yaw = subj.facing(f) + math.radians(G.lerp(az[0], az[1], e))
        d = G.lerp(dst[0], dst[1], e)
        cam = [S[0] + d * math.sin(yaw), S[1] + G.lerp(alt[0], alt[1], e), S[2] + d * math.cos(yaw)]
        keys.append({"f": f, "cam": cam, "look": S, "fov": G.lens_to_vfov(lens, aspect)})
        track.append((f, S))
    return _finish("aerial_flyover", keys, track, subj, motivation="reveal", emotion=emotion, sizes=["EWS", "EWS"], lenses=(lens, lens),
                   handheld=kw.get("handheld", 0.04), aspect=aspect)


PRESETS = {
    "dolly_in": dolly_in, "dolly_out": dolly_out, "truck_left": truck_left, "truck_right": truck_right,
    "pedestal_up": pedestal_up, "pedestal_down": pedestal_down, "crane_rise": crane_rise, "crane_descend": crane_descend,
    "orbit_cw": orbit_cw, "orbit_ccw": orbit_ccw, "arc_track": arc_track, "follow_tracking": follow_tracking,
    "over_shoulder": over_shoulder, "pov": pov, "low_reveal": low_reveal, "high_reveal": high_reveal,
    "establishing": establishing, "extreme_closeup": extreme_closeup, "push_reveal": push_reveal,
    "pullback_reveal": pullback_reveal, "whip_pan": whip_pan, "tilt_up": tilt_up, "tilt_down": tilt_down,
    "pan_left": pan_left, "pan_right": pan_right, "handheld_subtle": handheld_subtle,
    "handheld_documentary": handheld_documentary, "stabilized_tracking": stabilized_tracking, "tripod": tripod,
    "dolly_zoom": dolly_zoom, "rack_focus": rack_focus, "parallax_reveal": parallax_reveal, "orbit_track": orbit_track,
    "product_turntable": product_turntable, "architecture_walkthrough": architecture_walkthrough, "aerial_flyover": aerial_flyover,
}
# presets that take a second subject (target) positionally
TWO_SUBJECT = {"over_shoulder", "pov", "high_reveal", "push_reveal", "whip_pan"}
