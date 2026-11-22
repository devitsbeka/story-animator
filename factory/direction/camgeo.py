"""
Camera geometry shared by the presets and the shot validator (pure python, no Blender).

This mirrors cloud/blender/render_episode.py exactly where it matters:
  - spec space: +x east/starboard, +y up, +z south/bow-forward (yacht-local +z = bow);
  - rot_y(a): x' = x cos a + z sin a, z' = -x sin a + z cos a (Blender Matrix.Rotation(a, 'Y'));
  - yacht matrix   ym3 = T(x, heave - sink, z) . Ry(heading) . Rx(-pitch) . Rz(roll);
  - camera in 'yacht' space: cam follows T(x, 0.85 heave, z) . Ry(heading) only, look follows ym3;
  - rig_at(): eased interpolation between keys, positional drift, handheld jitter and shakes;
  - fov is VERTICAL degrees; the render uses sensor_fit VERTICAL, sensor_height 24 mm.

Heave and buoyancy pitch/roll are dynamic (ocean) and ignored here (treated as 0); the keyed
pitch/roll/sink of the yacht are honoured, which is what moves a hero by ~0.5 m on the reef.
"""
import math

# ------------------------------------------------------------------ eases (same as the renderer)
def bez(x1, y1, x2, y2):
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


def quintic(t):
    """5th-order smoothstep (catalog default_ease 'quintic_smooth'): zero velocity and acceleration at both ends."""
    t = min(1.0, max(0.0, t))
    return t * t * t * (t * (t * 6 - 15) + 10)


EASE = {
    "arrive": bez(0.16, 1, 0.3, 1),
    "move": bez(0.65, 0, 0.35, 1),
    "exit": bez(0.7, 0, 0.84, 0),
    "anticipate": bez(0.5, -0.32, 0.25, 1),
    "overshoot": bez(0.34, 1.45, 0.64, 1),
    "crashIn": lambda t: t * t * t,
    "linear": lambda t: t,
    "quintic_smooth": quintic,
}


def lerp(a, b, t):
    return a + (b - a) * t


def vlerp(a, b, t):
    return [lerp(x, y, t) for x, y in zip(a, b)]


def add(a, b):
    return [x + y for x, y in zip(a, b)]


def sub(a, b):
    return [x - y for x, y in zip(a, b)]


def mul(a, s):
    return [x * s for x in a]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    n = norm(a)
    return [x / n for x in a] if n > 1e-12 else [0.0, 0.0, 0.0]


def keyed(v, f, default=0.0):
    """scalarOrKeys: number or [[f, v], ...] linear between keys, hold outside (renderer semantics)."""
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
            return v0 if f1 == f0 else lerp(v0, v1, (f - f0) / (f1 - f0))
    return float(ks[-1][1])


def keyed_vec_any(ks, f, n=6):
    """[[f, [v...]], ...] linear between keys, hold outside; None -> zeros."""
    if not ks:
        return [0.0] * n
    ks = sorted(ks, key=lambda k: k[0])
    if f <= ks[0][0]:
        return list(ks[0][1])
    if f >= ks[-1][0]:
        return list(ks[-1][1])
    for (f0, v0), (f1, v1) in zip(ks, ks[1:]):
        if f0 <= f <= f1:
            t = 0 if f1 == f0 else (f - f0) / (f1 - f0)
            return [lerp(a, b, t) for a, b in zip(v0, v1)]
    return list(ks[-1][1])


# ------------------------------------------------------------------ rotations (spec space)
def rot_x(a, p):
    c, s = math.cos(a), math.sin(a)
    return [p[0], p[1] * c - p[2] * s, p[1] * s + p[2] * c]


def rot_yv(a, p):
    c, s = math.cos(a), math.sin(a)
    return [p[0] * c + p[2] * s, p[1], -p[0] * s + p[2] * c]


def rot_z(a, p):
    c, s = math.cos(a), math.sin(a)
    return [p[0] * c - p[1] * s, p[0] * s + p[1] * c, p[2]]


def yaw_dir(a):
    """Plan direction a yaw angle faces (rotY convention: 0 faces +z, pi/2 faces +x)."""
    return [math.sin(a), 0.0, math.cos(a)]


def yaw_of(v):
    return math.atan2(v[0], v[2])


# ------------------------------------------------------------------ yacht frame
class YachtFrame:
    """Static (keyed, no ocean) yacht transform at frame f. None yacht -> identity."""

    def __init__(self, yacht, f):
        self.y = yacht
        if not yacht:
            self.x = self.z = self.h = self.pitch = self.roll = self.sink = 0.0
            return
        self.x, self.z, self.h = float(yacht["x"]), float(yacht["z"]), float(yacht["heading"])
        self.pitch = keyed(yacht.get("pitch"), f)
        self.roll = keyed(yacht.get("roll"), f)
        self.sink = keyed(yacht.get("sink"), f)

    # full matrix (what the hero, props and a yacht-space look point ride on)
    def body_to_world(self, p):
        q = rot_z(self.roll, p)
        q = rot_x(-self.pitch, q)
        q = rot_yv(self.h, q)
        return [q[0] + self.x, q[1] - self.sink, q[2] + self.z]

    def world_to_body(self, w):
        q = [w[0] - self.x, w[1] + self.sink, w[2] - self.z]
        q = rot_yv(-self.h, q)
        q = rot_x(self.pitch, q)
        return rot_z(-self.roll, q)

    # heading-only matrix (what a yacht-space camera position rides on)
    def cam_to_world(self, p):
        q = rot_yv(self.h, p)
        return [q[0] + self.x, q[1], q[2] + self.z]

    def world_to_cam(self, w):
        return rot_yv(-self.h, [w[0] - self.x, w[1], w[2] - self.z])


# ------------------------------------------------------------------ the renderer's camera rig
def rig_at(f, keys, handheld=0.2, shakes=(), drift=0.25):
    """Exact port of render_episode.rig_at: cam, look (space of the keys), fov (deg), roll (deg)."""
    keys = sorted(keys, key=lambda k: k["f"])
    i = 0
    while i < len(keys) - 2 and f >= keys[i + 1]["f"]:
        i += 1
    a = keys[i]
    b = keys[min(i + 1, len(keys) - 1)]
    u = 1.0 if b["f"] == a["f"] else max(0.0, min(1.0, (f - a["f"]) / (b["f"] - a["f"])))
    e = EASE.get(b.get("ease") or "move", EASE["move"])(u)
    cam = [lerp(a["cam"][j], b["cam"][j], e) for j in range(3)]
    look = [lerp(a["look"][j], b["look"][j], e) for j in range(3)]
    fov = math.exp(lerp(math.log(a["fov"]), math.log(b["fov"]), e))
    roll = lerp(a.get("roll", 0) or 0, b.get("roll", 0) or 0, e)
    dr = drift
    cam = [cam[0] + math.sin(f * 0.011) * dr, cam[1] + math.sin(f * 0.017 + 1) * dr * 0.5, cam[2] + math.sin(f * 0.009 + 2) * dr]
    dist = math.dist(look, cam)
    k = dist * 0.0175
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
    return cam, look, fov, roll


def camera_world(shot, f, jitter=True):
    """World-space (cam, look, vfov, roll) of a shot's camera at frame f, as the renderer builds it."""
    ck = shot["camera"]
    if jitter:
        cam, look, fov, roll = rig_at(f, ck["keys"], keyed(ck.get("handheld"), f, 0.2), ck.get("shakes") or (), ck.get("drift", 0.25))
    else:
        cam, look, fov, roll = rig_at(f, ck["keys"], 0.0, (), 0.0)
    if ck.get("space", "world") == "yacht" and shot.get("yacht"):
        yf = YachtFrame(shot["yacht"], f)
        return yf.cam_to_world(cam), yf.body_to_world(look), fov, roll
    return cam, look, fov, roll


# ------------------------------------------------------------------ projection
def basis(cam, look, roll_deg=0.0):
    """Camera right / up / forward unit vectors (three.js lookAt with roll, like look_matrix3)."""
    fwd = unit(sub(look, cam))
    up = [0.0, 1.0, 0.0]
    if roll_deg:
        # Rodrigues: rotate up about fwd by -roll
        a = -math.radians(roll_deg)
        c, s = math.cos(a), math.sin(a)
        up = add(add(mul(up, c), mul(cross(fwd, up), s)), mul(fwd, dot(fwd, up) * (1 - c)))
    z = mul(fwd, -1)
    x = cross(up, z)
    if norm(x) < 1e-6:
        x = [1.0, 0.0, 0.0]
    x = unit(x)
    y = cross(z, x)
    return x, y, fwd


def project(cam, look, roll, vfov, aspect, p):
    """Point p -> (sx, sy, depth). sx: 0 left .. 1 right; sy: 0 top .. 1 bottom; aspect = width/height."""
    x, y, fwd = basis(cam, look, roll)
    d = sub(p, cam)
    depth = dot(d, fwd)
    if depth <= 1e-6:
        return None, None, depth
    tv = math.tan(math.radians(vfov) / 2)
    th = tv * aspect
    sx = 0.5 + 0.5 * dot(d, x) / (depth * th)
    sy = 0.5 - 0.5 * dot(d, y) / (depth * tv)
    return sx, sy, depth


# ------------------------------------------------------------------ lenses
# 35 mm full-frame EQUIVALENT focal length, matched on the diagonal (the usual "equivalent" definition),
# for the episode's frame aspect. 9:16 portrait: the vertical side is 16/sqrt(9^2+16^2) of the 43.27 mm diagonal.
FF_DIAG = math.hypot(36.0, 24.0)


def _vert_mm(aspect):
    """Vertical extent (mm) of a frame with the full-frame diagonal and aspect = width/height."""
    return FF_DIAG / math.sqrt(1.0 + aspect * aspect)


def lens_to_vfov(mm, aspect=9 / 16):
    return math.degrees(2 * math.atan(_vert_mm(aspect) / 2 / mm))


def vfov_to_lens(vfov, aspect=9 / 16):
    return _vert_mm(aspect) / 2 / math.tan(math.radians(vfov) / 2)


def frame_height_at(depth, vfov):
    """World metres covered by the frame's height at a given depth."""
    return 2 * depth * math.tan(math.radians(vfov) / 2)


def distance_for(frame_h, vfov):
    return frame_h / (2 * math.tan(math.radians(vfov) / 2))


# ------------------------------------------------------------------ shot sizes
# Frame height (m) at the subject for a 1.8 m human in 9:16, per PIXAR_RECIPE 3.1 (relative to frame height):
# EWS hero < 10% of frame height; WS head-to-toe ~ 50-80%; MS waist up; MCU chest up; CU head+shoulders; ECU detail.
SIZE_FRAME_H = {"ECU": 0.28, "CU": 0.6, "MCU": 1.0, "MS": 1.75, "WS": 3.2, "EWS": 30.0}
# classification boundaries (geometric-ish midpoints); frame height >= 18 m means hero < 10 % of the frame
SIZE_BOUNDS = [("ECU", 0.42), ("CU", 0.8), ("MCU", 1.3), ("MS", 2.4), ("WS", 18.0), ("EWS", float("inf"))]
SIZE_ORDER = ["ECU", "CU", "MCU", "MS", "WS", "EWS"]


def classify_size(frame_h, subject_h=1.8):
    """Shot size from the frame height at the subject, normalised to a 1.8 m human."""
    fh = frame_h * 1.8 / max(0.05, subject_h)
    for name, hi in SIZE_BOUNDS:
        if fh < hi:
            return name
    return "EWS"


def tighter(a, b):
    return SIZE_ORDER.index(a) < SIZE_ORDER.index(b)


# ------------------------------------------------------------------ >>> polish_camera: hero profile + yacht collision proxy
import base64 as _b64  # noqa: E402
import zlib as _zlib  # noqa: E402
import json as _json  # noqa: E402
import os as _os  # noqa: E402

_HERE = _os.path.dirname(_os.path.abspath(__file__))
EYE_LINE = 0.38          # eyes this far from the top of frame on MS and tighter (PIXAR_RECIPE 3.1, C7 band 0.30-0.45)


class HeroProfile:
    """The hero's real proportions, measured from the rig (factory/direction/measure_hero_profile.py).

    rest: fractions of the total height (cap top = 1): eye, brow, chin, top, shoulder, chest, waist, hips ...
    stances / shots: actor-local landmark points (spec space, actor at rotY 0, height = profile height) for each
    stance and, per shot id, a track [[f, {eye, brow, chin, top, chest, waist}], ...] of the real performance.
    """

    def __init__(self, data):
        self.d = data
        self.asset = data.get("asset")
        self.height = float(data.get("height", 1.8))
        self.rest = data["rest"]
        self.stances = data.get("stances", {})
        self.shots = data.get("shots", {})

    @classmethod
    def load(cls, path=None):
        path = path or _os.path.join(_HERE, "hero_profile_jay.json")
        with open(path) as fh:
            return cls(_json.load(fh))

    def local(self, name, h=1.8, shot_id=None, f=None, stance=None):
        """actor-local landmark (spec space, actor height h, facing +z at rotY 0), or None if unknown."""
        k = h / self.height
        trk = self.shots.get(shot_id) if shot_id else None
        if trk and f is not None and name in trk[0][1]:
            if f <= trk[0][0]:
                return mul(trk[0][1][name], k)
            if f >= trk[-1][0]:
                return mul(trk[-1][1][name], k)
            for (fa, la), (fb, lb) in zip(trk, trk[1:]):
                if fa <= f <= fb:
                    return mul(vlerp(la[name], lb[name], (f - fa) / max(1e-9, fb - fa)), k)
        if stance and stance in self.stances and name in self.stances[stance]:
            return mul(self.stances[stance][name], k)
        frac = self.rest.get(name)
        if frac is None:
            return None
        return [0.0, frac * h, 0.0]

    def frame_h(self, size, h=1.8, eye_line=EYE_LINE):
        """Frame height at the subject (m) for a shot size from the real landmarks, eyes at `eye_line` from the top:
        ECU eyes; CU forehead-to-chin with the cap inside (headroom); MCU to mid-chest; MS waist up."""
        if not isinstance(size, str):
            return float(size)
        r = self.rest
        eye, top, chin, chest, waist = (r[k] * h for k in ("eye", "top", "chin", "chest", "waist"))
        need_top = (top - eye + 0.012 * h) / eye_line                    # cap (+ a little air) inside the top edge
        if size == "ECU":
            return 1.1 * (eye - chin)
        if size == "CU":
            return max(need_top, (eye - chin + 0.03 * h) / (1 - eye_line))
        if size == "MCU":
            return max(need_top, (eye - (chest - 0.03 * h)) / (1 - eye_line))
        if size == "MS":
            return max(need_top, (eye - (waist - 0.03 * h)) / (1 - eye_line))
        return SIZE_FRAME_H[size] * h / 1.8

    def size_bounds(self, h=1.8):
        fh = {s: self.frame_h(s, h) for s in SIZE_ORDER}
        out = [(a, math.sqrt(fh[a] * fh[b]) if a != "WS" else 18.0 * h / 1.8) for a, b in zip(SIZE_ORDER, SIZE_ORDER[1:])]
        return out + [("EWS", float("inf"))]

    def classify(self, frame_h, h=1.8):
        for name, hi in self.size_bounds(h):
            if frame_h < hi:
                return name
        return "EWS"


_PROFILES = {}


def hero_profile(asset):
    """Measured profile for a character asset id (hero_v4 -> hero_profile_jay.json), None if not measured."""
    if asset not in _PROFILES:
        p = None
        for fn in sorted(_os.listdir(_HERE)):
            if fn.startswith("hero_profile_") and fn.endswith(".json"):
                hp = HeroProfile.load(_os.path.join(_HERE, fn))
                if hp.asset == asset:
                    p = hp
                    break
        _PROFILES[asset] = p
    return _PROFILES[asset]


class YachtProxy:
    """Signed-distance grid of the yacht + its mounted props (factory/direction/export_yacht_proxy.py), in yacht
    body coordinates. sdf(p): metres, < 0 inside a solid, capped at 1.27; blocked(a, b): line of sight."""

    def __init__(self, data):
        self.cell = float(data["cell"])
        self.o = data["origin"]
        self.n = data["dims"]
        raw = _zlib.decompress(_b64.b64decode(data["sdf_zb64"])) if "sdf_zb64" in data else _b64.b64decode(data["sdf_b64"])
        self.v = [b - 256 if b > 127 else b for b in raw]
        self.source = data.get("source")

    @classmethod
    def load(cls, path=None):
        with open(path or _os.path.join(_HERE, "yacht_proxy.json")) as fh:
            return cls(_json.load(fh))

    def _at(self, i, j, k):
        nx, ny, nz = self.n
        if not (0 <= i < nx and 0 <= j < ny and 0 <= k < nz):
            return 127
        return self.v[(i * ny + j) * nz + k]

    def sdf(self, p):
        g = [(p[a] - self.o[a]) / self.cell for a in range(3)]
        i, j, k = (int(math.floor(x)) for x in g)
        fx, fy, fz = g[0] - i, g[1] - j, g[2] - k
        acc = 0.0
        for di, wx in ((0, 1 - fx), (1, fx)):
            for dj, wy in ((0, 1 - fy), (1, fy)):
                for dk, wz in ((0, 1 - fz), (1, fz)):
                    w = wx * wy * wz
                    if w:
                        acc += w * self._at(i + di, j + dj, k + dk)
        return acc / 100.0

    def blocked(self, a, b, margin=0.0):
        """first fraction t of the segment a->b inside a solid (sdf < margin), else None (sphere-traced)."""
        L = norm(sub(b, a))
        if L < 1e-6:
            return None
        t, step = 0.0, self.cell * 0.4
        while t < L:
            d = self.sdf(add(a, mul(sub(b, a), t / L)))
            if d < margin:
                return t / L
            t += max(step, (d - margin) * 0.9)
        return None


_PROXY = {}


def yacht_proxy(path=None):
    key = path or "default"
    if key not in _PROXY:
        p = path or _os.path.join(_HERE, "yacht_proxy.json")
        _PROXY[key] = YachtProxy.load(p) if _os.path.exists(p) else None
    return _PROXY[key]
# <<< polish_camera
