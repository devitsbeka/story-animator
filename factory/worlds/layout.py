"""Pure-python half of the set assembler: everything about a world kit that can be decided without bpy.

  height(kit, x, z, seed)      ground height (m) at set-local (x, z): shaped terrain + fbm noise + clearings
  layout(kit, seed)            the deterministic build plan: ground grid, scatter instances, pieces, marks on the
                               ground, practical lights, plus a sha256 of the plan (same kit + seed -> same hash)
  camera_check(kit, plan, p)   is a camera position inside a camera-safe zone, above the ground, clear of geometry?

Axes: three.js / glTF (Y up, metres), the same as episode.json. cloud/blender/set_assembly.py imports this module
(it adds the repo root to sys.path), so Blender and the director agree on every height, mark and instance.
Randomness is integer hashing + random.Random seeded from sha256 - identical across Python builds and platforms.
"""
import hashlib
import json
import math
import random

DEFAULT_AVOID_MARKS = 2.5
MAX_INSTANCES = 4000


# ----------------------------------------------------------------------------------------------
# deterministic noise
# ----------------------------------------------------------------------------------------------
def _ihash(ix, iz, seed):
    n = (ix * 374761393 + iz * 668265263 + seed * 1442695041) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFFFF) / float(0xFFFFFF)


def _smooth(t):
    return t * t * (3 - 2 * t)


def vnoise(x, z, seed=0):
    """Value noise in [0, 1], C1-smooth."""
    ix, iz = math.floor(x), math.floor(z)
    fx, fz = _smooth(x - ix), _smooth(z - iz)
    a, b = _ihash(ix, iz, seed), _ihash(ix + 1, iz, seed)
    c, d = _ihash(ix, iz + 1, seed), _ihash(ix + 1, iz + 1, seed)
    return (a + (b - a) * fx) * (1 - fz) + (c + (d - c) * fx) * fz


def fbm(x, z, seed=0, octaves=4, lac=2.03, gain=0.5):
    """Fractal noise in about [-1, 1]."""
    s, amp, norm = 0.0, 1.0, 0.0
    for o in range(octaves):
        s += amp * (vnoise(x, z, seed + o * 101) * 2 - 1)
        norm += amp
        amp *= gain
        x, z = x * lac + 17.3, z * lac - 9.1
    return s / norm


def smoothstep(e0, e1, x):
    if e1 == e0:
        return 1.0 if x >= e1 else 0.0
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return _smooth(t)


def seed_int(*parts):
    return int.from_bytes(hashlib.sha256("/".join(str(p) for p in parts).encode()).digest()[:8], "big")


def kit_seed(kit, seed=None):
    return int(kit.get("seed", 0) if seed is None else seed)


# ----------------------------------------------------------------------------------------------
# terrain
# ----------------------------------------------------------------------------------------------
def centerline(kit, z):
    """x of the set's main axis at z (canyon meander; 0 for every other terrain)."""
    t = kit["terrain"]
    if t["type"] != "canyon":
        return 0.0
    p = t.get("params", {})
    A, L = p.get("meander_amp", 0.0), p.get("meander_len", 100.0)
    return A * math.sin(2 * math.pi * z / L) if A else 0.0


def shape_height(kit, x, z):
    t = kit["terrain"]
    p = t.get("params", {})
    typ = t["type"]
    if typ in ("plane", "noise", "none"):
        return 0.0
    if typ == "canyon":
        d = abs(x - centerline(kit, z))
        fh, ww, wh = p.get("floor_half", 8.0), p.get("wall_w", 12.0), p.get("wall_h", 30.0)
        u = smoothstep(fh, fh + ww, d)
        terr = p.get("terraces", 0)
        if terr:  # stepped sandstone ledges
            k = u * terr
            u = (math.floor(k) + _smooth(k - math.floor(k)) ** 3) / terr
        # eroded faces: extra, finer relief only on the walls (buttresses, gullies), none on the floor
        wr = p.get("wall_rough", 0.0)
        rough = wr * smoothstep(fh, fh + ww * 0.5, d) * fbm(x * 0.11, z * 0.07, 4241, 4) if wr else 0.0
        # walls keep rising slowly past the rim so the camera never sees over them
        return wh * u + rough + max(0.0, d - fh - ww) * p.get("rim_slope", 0.15)
    if typ == "ridge":
        # crest along z at x = crest(z); falls off to both sides; a saddle (flat spot) near the origin
        cx = p.get("crest_amp", 0.0) * math.sin(2 * math.pi * z / p.get("crest_len", 300.0))
        d = abs(x - cx)
        slope = p.get("slope", 0.6)
        crest_w = p.get("crest_w", 2.5)
        fall = 0.0 if d < crest_w else (d - crest_w) * slope + (d - crest_w) ** 2 * p.get("curve", 0.002)
        rise = p.get("rise", 0.04) * abs(z)  # the ridge climbs away from the saddle in both directions
        return rise - fall
    if typ == "street":
        rh, ww, ch = p.get("road_half", 5.0), p.get("walk_w", 3.0), p.get("curb_h", 0.15)
        ax = abs(x)
        if ax <= rh:
            return 0.04 * (1 - (ax / rh) ** 2)  # cambered road: crown at the centre (+4 cm)
        return ch
    raise ValueError(f"unknown terrain type {typ}")


def _noise_mask(kit, x, z):
    """Where noise applies at full strength: streets keep the road and walks flat."""
    t = kit["terrain"]
    if t["type"] == "street":
        p = t.get("params", {})
        return smoothstep(p.get("road_half", 5.0) + p.get("walk_w", 3.0) + 2.0, p.get("road_half", 5.0) + p.get("walk_w", 3.0) + 12.0, abs(x))
    if t["type"] == "canyon":  # a calmer floor, rougher walls
        p = t.get("params", {})
        d = abs(x - centerline(kit, z))
        return 0.35 + 0.65 * smoothstep(p.get("floor_half", 8.0), p.get("floor_half", 8.0) + p.get("wall_w", 12.0), d)
    return 1.0


def height(kit, x, z, seed=None):
    t = kit["terrain"]
    if t["type"] == "none":
        return float(t.get("base_y", 0.0))
    s = kit_seed(kit, seed)
    h = t.get("base_y", 0.0) + shape_height(kit, x, z)
    amp = t.get("amp", 0.0)
    if amp:
        h += amp * _noise_mask(kit, x, z) * fbm(x * t.get("freq", 0.02), z * t.get("freq", 0.02), s % 100003, t.get("octaves", 4))
    for c in t.get("clearings", []):
        cx, cz = c["at"]
        d = math.hypot(x - cx, z - cz)
        blend = c.get("blend", c["r"])
        w = 1.0 - smoothstep(c["r"], c["r"] + blend, d)
        if w > 0:
            if "y" in c:
                y0 = c["y"]
            else:
                y0 = t.get("base_y", 0.0) + shape_height(kit, cx, cz)
            # keep a hint of the micro relief inside the clearing so it does not read as a table top
            micro = 0.06 * fbm(x * 0.4, z * 0.4, s % 7919 + 5, 2)
            h = h * (1 - w) + (y0 + micro) * w
    return h


def slope_deg(kit, x, z, seed=None, e=0.5):
    dx = (height(kit, x + e, z, seed) - height(kit, x - e, z, seed)) / (2 * e)
    dz = (height(kit, x, z + e, seed) - height(kit, x, z - e, seed)) / (2 * e)
    return math.degrees(math.atan(math.hypot(dx, dz)))


def ground_size(kit):
    t = kit["terrain"]
    hx, hz = kit["extent"]["half"]
    return t.get("size", [2 * hx, 2 * hz])


def ground_grid(kit, seed=None):
    """(nx, nz, sx, sz, heights row-major [iz][ix]) for the ground mesh."""
    sx, sz = ground_size(kit)
    res = kit["terrain"].get("res", 96)
    if sx >= sz:
        nx, nz = res, max(4, round(res * sz / sx))
    else:
        nz, nx = res, max(4, round(res * sx / sz))
    hs = []
    for iz in range(nz + 1):
        z = -sz / 2 + sz * iz / nz
        hs.append([round(height(kit, -sx / 2 + sx * ix / nx, z, seed), 4) for ix in range(nx + 1)])
    return {"nx": nx, "nz": nz, "size": [sx, sz], "heights": hs}


def backdrop_ring(kit, seed=None, n=96):
    """Distant peaks/dunes as a ring: [(angle, r_inner, r_outer, peak_h)] (pure data for the assembler)."""
    b = kit["terrain"].get("backdrop")
    if not b or b["type"] == "none":
        return []
    s = kit_seed(kit, seed)
    r0, r1 = b.get("r", [1500.0, 3000.0])
    h0, h1 = b.get("height", [200.0, 800.0])
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n
        u = 0.5 + 0.5 * fbm(math.cos(a) * 2.2, math.sin(a) * 2.2, s % 104729 + 77, 4)
        ridge = (1 - abs(fbm(math.cos(a) * 5.0, math.sin(a) * 5.0, s % 104729 + 91, 3))) ** 2
        out.append([round(a, 5), r0, r1, round(h0 + (h1 - h0) * (0.55 * u + 0.45 * ridge), 2)])
    return out


# ----------------------------------------------------------------------------------------------
# regions
# ----------------------------------------------------------------------------------------------
def region_bbox(kit, reg):
    hx, hz = kit["extent"]["half"]
    sh = reg["shape"]
    if sh == "all":
        return -hx, hx, -hz, hz
    c = reg.get("center", [0.0, 0.0])
    if sh == "rect":
        w, d = reg["size"]
        return c[0] - w / 2, c[0] + w / 2, c[1] - d / 2, c[1] + d / 2
    if sh in ("disc", "ring"):
        r = reg["r"] if isinstance(reg["r"], (int, float)) else reg["r"][1]
        return c[0] - r, c[0] + r, c[1] - r, c[1] + r
    if sh == "band":
        r1 = reg["r"][1] if isinstance(reg["r"], list) else reg["r"]
        z0, z1 = reg.get("z_range", [-hz, hz])
        A = kit["terrain"].get("params", {}).get("meander_amp", 0.0) if kit["terrain"]["type"] == "canyon" else 0.0
        return -r1 - A, r1 + A, z0, z1
    raise ValueError(sh)


def in_region(kit, reg, x, z):
    hx, hz = kit["extent"]["half"]
    if abs(x) > hx or abs(z) > hz:
        return False
    sh = reg["shape"]
    if sh == "all":
        return True
    c = reg.get("center", [0.0, 0.0])
    if sh == "rect":
        w, d = reg["size"]
        return abs(x - c[0]) <= w / 2 and abs(z - c[1]) <= d / 2
    if sh == "disc":
        return math.hypot(x - c[0], z - c[1]) <= reg["r"]
    if sh == "ring":
        r0, r1 = reg["r"]
        return r0 <= math.hypot(x - c[0], z - c[1]) <= r1
    if sh == "band":
        r0, r1 = reg["r"] if isinstance(reg["r"], list) else (0.0, reg["r"])
        z0, z1 = reg.get("z_range", [-hz, hz])
        if not (z0 <= z <= z1):
            return False
        dx = x - centerline(kit, z)
        side = reg.get("side", "both")
        if (side == "left" and dx > 0) or (side == "right" and dx < 0):
            return False
        return r0 <= abs(dx) <= r1
    raise ValueError(sh)


def region_area(kit, reg, n=48):
    """Monte-Carlo-free area estimate on a fixed n x n lattice of the bbox (deterministic)."""
    x0, x1, z0, z1 = region_bbox(kit, reg)
    inside = sum(in_region(kit, reg, x0 + (x1 - x0) * (i + 0.5) / n, z0 + (z1 - z0) * (j + 0.5) / n) for i in range(n) for j in range(n))
    return (x1 - x0) * (z1 - z0) * inside / (n * n)


# ----------------------------------------------------------------------------------------------
# pieces, marks, lights
# ----------------------------------------------------------------------------------------------
def _rng(kit, seed, *tag):
    return random.Random(seed_int(kit["id"], kit_seed(kit, seed), *tag))


def _pick_range(rng, v, default=1.0):
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    return rng.uniform(v[0], v[1])


def _place(kit, at, y_off, seed):
    if len(at) == 3:
        return [float(at[0]), float(at[1]), float(at[2])]
    x, z = at
    return [float(x), round(height(kit, x, z, seed) + (y_off or 0.0), 4), float(z)]


def expand_pieces(kit, seed=None):
    """pieces with 'repeat' expanded into concrete, seeded copies; every piece gets a resolved position."""
    out = []
    for pc in kit.get("pieces", []):
        rng = _rng(kit, seed, "piece", pc["id"])
        rep = pc.get("repeat")
        if not rep:
            q = dict(pc)
            q["pos"] = _place(kit, pc.get("at", [0, 0]), pc.get("y"), seed)
            q["height_m"] = _pick_range(rng, pc.get("height"), None) if pc.get("height") is not None else None
            q["scale_f"] = _pick_range(rng, pc.get("scale"), 1.0)
            q["seed"] = rng.randrange(1 << 30)
            out.append(q)
            continue
        base = pc.get("at", [0, 0])
        v = rep["from"]
        i = 0
        while v <= rep["to"] + 1e-9:
            if rng.random() >= rep.get("skip", 0.0):
                j = rng.uniform(-1, 1) * rep.get("jitter", 0.0)
                if rep["axis"] == "z":
                    at = [base[0], v + j]
                else:
                    at = [v + j, base[1]]
                q = {k: val for k, val in pc.items() if k != "repeat"}
                q["id"] = f"{pc['id']}_{i:02d}"
                q["pos"] = _place(kit, at, pc.get("y"), seed)
                q["height_m"] = _pick_range(rng, pc.get("height"), None) if pc.get("height") is not None else None
                q["scale_f"] = _pick_range(rng, pc.get("scale"), 1.0)
                q["seed"] = rng.randrange(1 << 30)
                out.append(q)
            i += 1
            v += rep["step"]
    return out


def marks(kit, seed=None):
    """{NAME: {local [x, y, z] on the ground, rotY, kind, desc, ...}} - the staging.MARKS format."""
    if kit.get("legacy") == "yacht_island":
        from factory.director.staging import MARKS
        return {k: dict(v, kind="stand") for k, v in MARKS.items()}
    out = {}
    for name, m in kit["marks"].items():
        d = {k: v for k, v in m.items() if k not in ("at", "y")}
        d["local"] = _place(kit, m["at"], m.get("y"), seed)
        out[name] = d
    return out


def lights(kit, seed=None):
    out = []
    for L in kit.get("lights", []):
        q = dict(L)
        q["pos"] = _place(kit, L["at"], L.get("y", 0.0), seed)
        out.append(q)
    return out


# ----------------------------------------------------------------------------------------------
# scatter
# ----------------------------------------------------------------------------------------------
def _blocked(kit, layer, x, z, mk, pieces):
    r_m = layer.get("avoid_marks", DEFAULT_AVOID_MARKS)
    if r_m and any(math.hypot(x - m["local"][0], z - m["local"][2]) < r_m for m in mk.values()):
        return True
    for pc in pieces:
        fp = pc.get("footprint", 0.0)
        if fp and math.hypot(x - pc["pos"][0], z - pc["pos"][2]) < fp:
            return True
    if layer.get("avoid_zones", True):
        # a camera zone keeps scatter out only where the scatter would reach into its height band
        for cz in kit.get("camera_zones", []):
            if cz["y"][0] < layer["height"][1] and in_region(kit, cz["region"], x, z):
                return True
    return any(in_region(kit, ex, x, z) for ex in layer.get("exclude", []))


def scatter_layer(kit, layer, seed, mk, pieces):
    rng = _rng(kit, seed, "scatter", layer["id"])
    x0, x1, z0, z1 = region_bbox(kit, layer["region"])
    cell = math.sqrt(100.0 / layer["density"])
    nx, nz = max(1, int(math.ceil((x1 - x0) / cell))), max(1, int(math.ceil((z1 - z0) / cell)))
    assets = layer["assets"]
    weights = layer.get("weights") or [1.0] * len(assets)
    cum, acc = [], 0.0
    for w in weights:
        acc += w
        cum.append(acc)
    cl = layer.get("cluster")
    s = kit_seed(kit, seed)
    out = []
    cap = min(layer.get("max_count", MAX_INSTANCES), MAX_INSTANCES)
    for iz in range(nz):
        for ix in range(nx):
            # every cell draws the same number of randoms, so a rejection never shifts later cells
            jx, jz, ra, ryaw, rh, rt1, rt2 = (rng.random() for _ in range(7))
            if len(out) >= cap:
                continue
            x = x0 + (ix + jx) * cell
            z = z0 + (iz + jz) * cell
            if not in_region(kit, layer["region"], x, z) or _blocked(kit, layer, x, z, mk, pieces):
                continue
            if cl and vnoise(x * cl["freq"], z * cl["freq"], seed_int(layer["id"], s) % 65521) < cl["threshold"]:
                continue
            y = height(kit, x, z, seed)
            yr = layer.get("y_range")
            if yr and not (yr[0] <= y <= yr[1]):
                continue
            if "slope_max_deg" in layer or "slope_min_deg" in layer:
                sl = slope_deg(kit, x, z, seed)
                if sl > layer.get("slope_max_deg", 90) or sl < layer.get("slope_min_deg", 0):
                    continue
            k = next(i for i, c in enumerate(cum) if ra * acc <= c)
            yaw = ryaw * 2 * math.pi if layer.get("yaw", "random") == "random" else float(layer["yaw"])
            h0, h1 = layer["height"]
            tilt = layer.get("tilt_deg", 0.0)
            out.append({"layer": layer["id"], "asset": assets[k], "pos": [round(x, 4), round(y - layer.get("sink", 0.0), 4), round(z, 4)],
                        "yaw": round(yaw, 5), "height": round(h0 + (h1 - h0) * rh, 4),
                        "tilt": [round((rt1 * 2 - 1) * tilt, 3), round((rt2 * 2 - 1) * tilt, 3)]})
    return out


# ----------------------------------------------------------------------------------------------
# the plan
# ----------------------------------------------------------------------------------------------
def layout(kit, seed=None, with_grid=True):
    """The complete deterministic build plan for (kit, seed)."""
    s = kit_seed(kit, seed)
    if kit.get("legacy") == "yacht_island":
        plan = {"kit": kit["id"], "seed": s, "legacy": kit["legacy"], "marks": marks(kit, s)}
        plan["hash"] = plan_hash(plan)
        return plan
    mk = marks(kit, s)
    pcs = expand_pieces(kit, s)
    inst = []
    for layer in kit.get("scatter", []):
        inst += scatter_layer(kit, layer, s, mk, pcs)
    plan = {"kit": kit["id"], "version": kit["version"], "seed": s, "marks": mk, "pieces": pcs, "instances": inst,
            "lights": lights(kit, s), "backdrop": backdrop_ring(kit, s)}
    if with_grid:
        plan["ground"] = ground_grid(kit, s)
    plan["hash"] = plan_hash(plan)
    return plan


def plan_hash(plan):
    body = {k: v for k, v in plan.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def summary(plan):
    by = {}
    for i in plan.get("instances", []):
        by[i["layer"]] = by.get(i["layer"], 0) + 1
    return {"kit": plan["kit"], "seed": plan["seed"], "instances": len(plan.get("instances", [])), "by_layer": by,
            "pieces": len(plan.get("pieces", [])), "marks": sorted(plan["marks"]), "hash": plan["hash"][:12]}


# ----------------------------------------------------------------------------------------------
# camera safety
# ----------------------------------------------------------------------------------------------
def camera_check(kit, plan, p, clearance=0.6):
    """Problems (list of strings, [] = ok) for a camera at set-local p = [x, y, z]."""
    if kit.get("legacy"):
        return []
    x, y, z = p
    s = plan["seed"]
    probs = []
    zones = [cz for cz in kit["camera_zones"] if in_region(kit, cz["region"], x, z)]
    g = height(kit, x, z, s)
    if not zones:
        probs.append(f"camera at ({x:.1f}, {z:.1f}) is outside every camera-safe zone {[c['id'] for c in kit['camera_zones']]}")
    elif not any(cz["y"][0] <= y - g <= cz["y"][1] for cz in zones):
        probs.append(f"camera {y - g:.2f} m above the ground at ({x:.1f}, {z:.1f}); zone band {[c['y'] for c in zones]}")
    if y - g < 0.25:
        probs.append(f"camera below/at the ground ({y - g:.2f} m)")
    for pc in plan["pieces"]:
        fp = pc.get("footprint", 0.0)
        if fp and math.hypot(x - pc["pos"][0], z - pc["pos"][2]) < fp * 0.8 and y < pc["pos"][1] + (pc.get("height_m") or 3.0):
            probs.append(f"camera inside set piece {pc['id']}")
    for i in plan["instances"]:
        r = max(0.3, i["height"] * 0.18)
        if math.hypot(x - i["pos"][0], z - i["pos"][2]) < r + clearance * 0.5 and y < i["pos"][1] + i["height"]:
            probs.append(f"camera inside scatter {i['layer']}:{i['asset']}")
            break
    return probs
