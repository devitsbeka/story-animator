#!/usr/bin/env python3
"""
Build the Primrose 1981 set (shots D23-D26 of plan/shotlist.md) as a JSON fragment of 4 shots, in the
same schema as episode_v2.json shots plus a 'set': 'primrose' marker.

  python3 episodes/sentinel/plan/build_primrose.py                      # -> plan/primrose_shots.json
  python3 episodes/sentinel/plan/build_primrose.py --splice episodes/sentinel/episode_v2.json --out /tmp/x.json
        # full episode with D23-D26 replaced (render_episode.py can render it directly)
  --library-previews   also emit LIB_* turntable-ish shots (frames 5000+) of the coast guard vessel, helicopter
                       and Primrose in daylight for catalog thumbnails

Props are code-built in cloud/blender/props_vehicles.py and placed in WORLD space (attach 'world').
Weather / grade are env fields read by cloud/blender/storm.py (env.weather, env.grade).
World axes are the spec's (three.js): Y up, metres; rotY 0 = bow along +z.
"""
import argparse
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(EP))
GEO = json.load(open(os.path.join(ROOT, "studio/src/data/sentinel_geo.json")))

# ------------------------------------------------------------------ easing (same curves as build_v2 / renderer)
def bez(x1, y1, x2, y2):
    def f(x):
        x = min(1.0, max(0.0, x)); t = x
        for _ in range(10):
            cx = 3*x1*t*(1-t)**2 + 3*x2*t*t*(1-t) + t**3 - x
            d = 3*x1*(1-t)**2 + 6*(x2-x1)*t*(1-t) + 3*(1-x2)*t*t
            if abs(d) < 1e-6: break
            t = min(1.0, max(0.0, t - cx/d))
        return 3*y1*t*(1-t)**2 + 3*y2*t*t*(1-t) + t**3
    return f
EASE = {"move": bez(.65, 0, .35, 1), "arrive": bez(.16, 1, .3, 1), "exit": bez(.7, 0, .84, 0), "linear": lambda t: t}
L = lambda a, b, t: a + (b - a) * t
r3 = lambda v: [round(x, 4) for x in v]

# ------------------------------------------------------------------ world staging (same island as build_v2)
ISL_NEAR = {"asset": "island", "x": -300, "z": 900, "rotY": 0.6, "scale": 0.2}
FIRES = [1, 1, 1, 1, 0.9, 1]


def rot_y(a, x, z):
    return x * math.cos(a) + z * math.sin(a), -x * math.sin(a) + z * math.cos(a)


def coast_world(isl):
    S = isl["scale"] * 1000
    out = []
    for x, y in GEO["coast"]:
        wx, wz = rot_y(isl["rotY"], x * S, y * S)
        out.append((wx + isl["x"], wz + isl["z"]))
    return out


SHORE = min(coast_world(ISL_NEAR), key=lambda p: p[0] ** 2 + p[1] ** 2)      # the reef beach our yacht hits
_n = math.hypot(*SHORE)
OUT = (-SHORE[0] / _n, -SHORE[1] / _n)                                         # seaward
HEAD = (-OUT[0], -OUT[1])                                                      # bow toward the beach
SHIP_YAW = math.atan2(HEAD[0], HEAD[1])
SHIP_POS = [SHORE[0] + OUT[0] * 140.0, 0.0, SHORE[1] + OUT[1] * 140.0]       # bow ~65 m off the beach
SHIP_TILT = [-1.2, 4.5]                                                        # pitch (neg = bow up), roll (deg)
STBD = (math.cos(SHIP_YAW), -math.sin(SHIP_YAW))                               # ship's starboard in world xz


def ship_to_world(local, pos=SHIP_POS, yaw=SHIP_YAW, tilt=SHIP_TILT):
    """ship-local spec point (x stbd, y up, z fore) -> world, using exactly the rotation post_place keys:
    Blender Rz(yaw) @ Rx(pitch) @ Ry(roll) on Blender-local (x, -z, y)."""
    bx, by, bz = local[0], -local[2], local[1]
    p, r = math.radians(tilt[0]), math.radians(tilt[1])
    # Ry(roll)
    bx, bz = bx * math.cos(r) + bz * math.sin(r), -bx * math.sin(r) + bz * math.cos(r)
    # Rx(pitch)
    by, bz = by * math.cos(p) - bz * math.sin(p), by * math.sin(p) + bz * math.cos(p)
    # Rz(yaw)
    bx, by = bx * math.cos(yaw) - by * math.sin(yaw), bx * math.sin(yaw) + by * math.cos(yaw)
    bx, by, bz = bx + pos[0], by - pos[2], bz + pos[1]
    return [bx, bz, -by]


def world_dir(az_deg):
    """horizontal unit vector at azimuth az from the ship's bow (+90 = starboard)."""
    a = math.radians(az_deg)
    return (HEAD[0] * math.cos(a) + STBD[0] * math.sin(a), HEAD[1] * math.cos(a) + STBD[1] * math.sin(a))


def sample(f0, f1, fn, ease="move", space="world"):
    keys, f = [], f0
    while True:
        u = EASE[ease]((f - f0) / max(1, f1 - f0))
        cam, look, fov = fn(u)
        keys.append({"f": f, "cam": r3(cam), "look": r3(look), "fov": round(fov, 3), "ease": "linear"})
        if f >= f1:
            break
        f = min(f1, f + 3)
    return {"space": space, "keys": keys}


def lfov(a, b, u):
    return math.exp(L(math.log(a), math.log(b), u))


# ------------------------------------------------------------------ the set
SHIP = {"prop": "primrose", "attach": "world", "local": r3(SHIP_POS), "rotY": round(SHIP_YAW, 5), "tilt": SHIP_TILT}
STORM = {"seaState": 3.2, "weather": {"rain": 1.0, "wind": 14, "overcast": 0.9, "moonScale": 0.7}, "grade": {"look": "sepia", "amount": 0.85}}
DAY = {"dawn": 1.0, "moonDir": [0.35, 1.0, 0.45], "seaState": 2.0, "weather": {"overcast": 0.45}, "grade": {"look": "sepia", "amount": 0.85}}
HOLD_POS = [0.0, 3.0, -2600.0]       # the hold is a closed interior set, placed away from the ship


def env_with(base, **kw):
    e = json.loads(json.dumps(base))
    for k, v in kw.items():
        if isinstance(v, dict) and isinstance(e.get(k), dict):
            e[k].update(v)
        else:
            e[k] = v
    return e


def shot(sid, title, f0, f1, camera, props, env, island=ISL_NEAR, fires=None, key=None, handheld=0.12, drift=0.1, extra=None):
    camera["handheld"], camera["drift"] = handheld, drift
    s = {"id": sid, "title": title, "set": "primrose", "from": f0, "to": f1, "keyFrame": key or (f0 + f1) // 2,
         "camera": camera, "island": island, "props": props, "env": env}
    if fires:
        s["fires"] = fires
    if extra:
        s.update(extra)
    return s


def build():
    shots = []
    # D23 1523-1650 "In 1981, a cargo ship called the Primrose ran aground right here."
    #   EWS slow pull-back to reveal scale: storm, rain, lightning; ship dead centre, island behind its bow.
    # stern-quarter: the 150 m hull foreshortens into the 9:16 frame, superstructure nearest, island past the bow
    tgt = [SHIP_POS[0] - HEAD[0] * 22 + STBD[0] * 6, 10.0, SHIP_POS[2] - HEAD[1] * 22 + STBD[1] * 6]
    def d23(u):
        dx, dz = world_dir(L(150, 157, u))
        d, h = L(185, 300, u), L(24, 52, u)
        return [tgt[0] + dx * d, tgt[1] + h, tgt[2] + dz * d], tgt, lfov(36, 33, u)
    shots.append(shot("D23", "Primrose 1981", 1523, 1650, sample(1523, 1650, d23, "move"),
                      [SHIP | {"rock": {"amp": 0.5, "period": 8.0}}],
                      env_with(STORM, weather={"lightning": [1541, 1590, 1632], "lightningDir": [0.3, 0.7, -0.6]}),
                      key=1600, extra={"overlays": [{"type": "label", "text": "PRIMROSE · 1981", "from": 1535, "to": 1650}]}))

    # D24 1650-1760 "The crew saw armed islanders on the beach..." POV from the bridge window, slow push;
    #   only torches and shadows on the beach (never people), rain on the glass, lightning.
    beach = [SHORE[0] + HEAD[0] * 14, 2.2, SHORE[1] + HEAD[1] * 14]
    tang = (-OUT[1], OUT[0])
    torch_yaw = math.atan2(-tang[1], tang[0])
    def d24(u):
        eye = ship_to_world([L(0.25, 0.0, u), L(20.45, 20.4, u), L(-58.6, -57.6, u)])
        return eye, [beach[0], L(3.0, 2.6, u), beach[2]], lfov(40, 31, u)
    torches = {"prop": "beach_torches", "attach": "world", "local": r3([SHORE[0] + HEAD[0] * 10, 1.6, SHORE[1] + HEAD[1] * 10]),
               "rotY": round(torch_yaw, 5), "opts": {"count": 9, "spread": 55.0}}
    shots.append(shot("D24", "Armed islanders", 1650, 1760, sample(1650, 1760, d24, "move"),
                      [SHIP, torches],
                      env_with(STORM, weather={"lightning": [1688, 1741], "lightningDir": [-0.2, 0.8, 0.6], "rain": 0.6}),
                      fires=[[1650, FIRES]], key=1705, handheld=0.06, drift=0.03))

    # D25 1760-1840 "...so they stayed inside their steel hull and waited for days..." interior MS, slow drift;
    #   swinging lamp, crew silhouettes; DAY 1 -> 7 counter is a Remotion overlay.
    def hold_w(p):
        return [HOLD_POS[0] + p[0], HOLD_POS[1] + p[1], HOLD_POS[2] + p[2]]
    def d25(u):
        # from the forward end, looking aft at the lamp pool; crew against both walls
        return hold_w([L(2.6, 1.7, u), L(2.4, 2.7, u), L(10.0, 8.6, u)]), hold_w([L(-0.6, -0.2, u), L(2.2, 2.4, u), L(-1.0, -0.4, u)]), lfov(50, 45, u)
    shots.append(shot("D25", "Waited for days", 1760, 1840, sample(1760, 1840, d25, "linear"),
                      [{"prop": "cargo_hold", "attach": "world", "local": HOLD_POS, "rotY": 0.0}],
                      {"seaState": 1.0, "grade": {"look": "sepia", "amount": 0.85}},
                      island=None, key=1800, handheld=0.05, drift=0.04,
                      extra={"overlays": [{"type": "day_counter", "from": 1768, "to": 1836, "days": [1, 7]}]}))

    # D26 1840-1931 "...until helicopters lifted every single one of them out." daylight WS, crane-up with the
    #   helicopter hovering over the foredeck, winching a survivor up; rotor wash on the hatches.
    hover0 = ship_to_world([3.0, 30.0, 18.0])
    hover1 = ship_to_world([3.0, 36.0, 18.0])
    deck = ship_to_world([3.0, 8.8, 18.0])
    heli = {"prop": "helicopter", "attach": "world", "local": r3(hover0), "rotY": round(SHIP_YAW + math.radians(-8), 5),
            "path": [[1840, r3(hover0)], [1931, r3(hover1)]], "yaw": [[1840, 0], [1931, 4]], "tilt": [2.0, -1.5],
            "winch": [[1840, 19.5], [1850, 19.5], [1925, 7.0]], "opts": {"lights": True}}
    wash = {"prop": "rotor_wash", "attach": "world", "local": r3(deck), "rotY": 0.0}
    def d26(u):
        hp = [L(a, b, u) for a, b in zip(hover0, hover1)]
        tg = [hp[0], hp[1] - L(7.0, 5.0, u), hp[2]]
        dx, dz = world_dir(L(70, 80, u))
        d, h = L(78, 66, u), L(-8.0, 3.0, u)
        return [tg[0] + dx * d, tg[1] + h, tg[2] + dz * d], tg, lfov(34, 32, u)
    shots.append(shot("D26", "Helicopters", 1840, 1931, sample(1840, 1931, d26, "move"),
                      [SHIP | {"opts": {"lights": False}}, heli, wash], DAY, key=1885))
    return shots


def library_previews():
    """Daylight preview shots of each vehicle (not part of the cut; frames 5000+)."""
    out = []
    def orbit(f0, f1, tg, az, d, h, fov):
        def fn(u):
            a = math.radians(L(az[0], az[1], u))
            return [tg[0] + math.sin(a) * d, tg[1] + h, tg[2] + math.cos(a) * d], tg, fov
        return sample(f0, f1, fn, "linear")
    cg = {"prop": "coastguard", "attach": "world", "local": [0, 0, 0], "rotY": 0.0, "search": [[5000, -20], [5030, 20]]}
    out.append(shot("LIB_coastguard", "Library: coast guard patrol vessel", 5000, 5030, orbit(5000, 5030, [0, 3, 0], (55, 65), 70, 14, 30),
                    [cg], {"moonDir": [0.12, 0.3, 1], "seaState": 1.4}, island=None, key=5015, handheld=0.0, drift=0.0))
    out.append(shot("LIB_helicopter", "Library: rescue helicopter", 5100, 5130, orbit(5100, 5130, [0, 19, 0], (60, 70), 40, 4, 34),
                    [{"prop": "helicopter", "attach": "world", "local": [0, 18, 0], "rotY": 0.0, "winch": [[5100, 6.0]]}],
                    {"dawn": 1.0, "moonDir": [0.35, 1.0, 0.45], "seaState": 1.4}, island=None, key=5115, handheld=0.0, drift=0.0))
    out.append(shot("LIB_primrose", "Library: Primrose bulk carrier", 5200, 5230, orbit(5200, 5230, [0, 10, -10], (125, 135), 330, 70, 30),
                    [{"prop": "primrose", "attach": "world", "local": [0, 0, 0], "rotY": 0.0, "opts": {"lights": False}}],
                    {"dawn": 1.0, "moonDir": [0.35, 1.0, 0.45], "seaState": 1.4}, island=None, key=5215, handheld=0.0, drift=0.0))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--out", default=None, help="output path (fragment by default, full episode with --splice)")
    ap.add_argument("--splice", default=None, help="episode.json whose D23-D26 are replaced; writes a full episode")
    ap.add_argument("--library-previews", action="store_true")
    a = ap.parse_args()
    shots = build()
    if a.library_previews:
        shots += library_previews()
    if a.splice:
        ep = json.load(open(a.splice))
        byid = {s["id"]: s for s in shots}
        ep["shots"] = [byid.pop(s["id"], s) for s in ep["shots"]] + list(byid.values())
        ep.setdefault("source", {})["primrose"] = "episodes/sentinel/plan/build_primrose.py"
        out = a.out or a.splice
        json.dump(ep, open(out, "w"), indent=1)
    else:
        out = a.out or os.path.join(HERE, "primrose_shots.json")
        json.dump({"set": "primrose", "builder": "episodes/sentinel/plan/build_primrose.py",
                   "shotlist": "episodes/sentinel/plan/shotlist.md", "shots": shots}, open(out, "w"), indent=1)
    print(f"wrote {out}: {len(shots)} primrose shots; ship at {r3(SHIP_POS)} yaw {math.degrees(SHIP_YAW):.1f} deg, "
          f"bow {math.hypot(SHIP_POS[0] + HEAD[0] * 75 - SHORE[0], SHIP_POS[2] + HEAD[1] * 75 - SHORE[1]):.0f} m off the beach")


if __name__ == "__main__":
    main()
