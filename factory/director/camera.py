"""Camera helpers for stage 4 (copied from episodes/sentinel/plan/build_v2.py so the director's output is
numerically identical to the hand-built Sentinel v2 episode; factory/direction/camera_presets.py does not
exist in this branch).

orbit(): orbit/push around a hero mark in yacht-local metres. path(): straight eased move between two
camera positions / look points. Both sample keys every 3 frames with ease 'linear' between samples, so
Blender reproduces the eased curve exactly.
"""
import math


def bez(x1, y1, x2, y2):
    def f(x):
        x = min(1.0, max(0.0, x)); t = x
        for _ in range(10):
            cx = 3*x1*t*(1-t)**2 + 3*x2*t*t*(1-t) + t**3 - x
            d = 3*x1*(1-t)**2 + 6*(x2-x1)*t*(1-t) + 3*(1-x2)*t*t
            if abs(d) < 1e-6:
                break
            t = min(1.0, max(0.0, t - cx/d))
        return 3*y1*t*(1-t)**2 + 3*y2*t*t*(1-t) + t**3
    return f


EASE = {"move": bez(.65, 0, .35, 1), "arrive": bez(.16, 1, .3, 1), "exit": bez(.7, 0, .84, 0), "linear": lambda t: t,
        "crash": lambda t: t ** 3}
TARGETS = {"chest": 1.30, "face": 1.55, "hands": 1.15, "feet": 0.4, "sit": 0.75}
STEP = 3


def L(a, b, t):
    return a + (b - a) * t


def r3(v):
    return [round(x, 4) for x in v]


def orbit(mark, f0, f1, az, d, h, fov, ease="move", target="chest", aim=(0, 0, 0)):
    """az = degrees around the hero (0 = in front of his face), d = distance (m), h = camera height above
    the target, fov = vertical degrees; each is [start, end]. mark = {"local": [x, y, z], "rotY": rad}."""
    lx, ly, lz = mark["local"]
    ty = TARGETS[target] if isinstance(target, str) else target
    T = [lx + aim[0], ly + ty + aim[1], lz + aim[2]]
    keys = []
    f = f0
    while True:
        u = (f - f0) / max(1, f1 - f0); e = EASE[ease](u)
        a = math.radians(L(az[0], az[1], e)) + mark["rotY"]
        dd, hh = L(d[0], d[1], e), L(h[0], h[1], e)
        fv = math.exp(L(math.log(fov[0]), math.log(fov[1]), e))
        cam = [T[0] + math.sin(a) * dd, T[1] + hh, T[2] + math.cos(a) * dd]
        keys.append({"f": f, "cam": r3(cam), "look": r3(T), "fov": round(fv, 3), "ease": "linear"})
        if f >= f1:
            break
        f = min(f1, f + STEP)
    return {"space": "yacht", "keys": keys}


def path(f0, f1, cams, looks, fovs, ease="move", space="world"):
    keys = []
    f = f0
    while True:
        u = (f - f0) / max(1, f1 - f0); e = EASE[ease](u)
        keys.append({"f": f, "cam": r3([L(a, b, e) for a, b in zip(*cams)]), "look": r3([L(a, b, e) for a, b in zip(*looks)]),
                     "fov": round(math.exp(L(math.log(fovs[0]), math.log(fovs[1]), e)), 3), "ease": "linear"})
        if f >= f1:
            break
        f = min(f1, f + STEP)
    return {"space": space, "keys": keys}
