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
