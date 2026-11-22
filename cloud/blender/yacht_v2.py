"""
yacht_v2.py - the factory's own high-detail hero yacht, built procedurally in bpy (Blender 4.2). No external assets.

A ~14 m flybridge motor yacht that holds up in close shots: lofted hard-chine hull with a proper sheer, raked stem,
spray rails and flared topsides; swim platform + boarding ladder; aft cockpit with a U-shaped upholstered dinette
around a teak table; cabin with raked tinted windows in frames, glass aft door, raked windscreen; flybridge with
helm console, bench and coaming; hardtop on a radar arch with radar dome and mast; stainless bow pulpit, rails and
stanchions; cleats, fairleads, anchor in a bow roller + windlass + chain; foredeck hatches; nav lights; fenders;
life ring; teak decks (cap rails, cockpit sole, side decks, foredeck).

  build(root) -> {"objs": [...], "hatch": hatch_pivot, "marks": MARKS}
      Everything is parented to `root` (render_episode's YachtRoot, Blender axes), with object transforms at identity
      so cloud/blender/materials.py's object-space shaders (teak planks fore-aft, hull waterline) line up.

Naming follows the yacht.glb contract so the existing pipeline keeps working unchanged:
  materials  gelcoat_hull (hull: boot stripe/antifouling + oceanfx hull foam finds object 'gelcoat_hull'),
             gelcoat_*, teak*, steel*, glass_cabin* (emissive cabin glow, keyed by yacht.lights), upholstery_*,
             fender*, nav_* (emissive; keyed by yacht.lights) -> restyled by materials.apply_yacht_materials()
  objects    hatch_pivot (foredeck hatch hinge; render_episode keys its X rotation from yacht.hatch),
             anchor_* empties (bow, cockpit, hatch, stern, exhaust) as in yacht.glb
  lights     point lights under the root (keyed by yacht.lights like the GLB's)

Coordinates: geometry is authored in SPEC space (three.js: x starboard, y up, z bow, metres, origin at the yacht root
whose static waterline is y = 0.05) and converted to Blender (x, -z, y) - the same mapping render_episode uses.

MARKS: the episode attachment points (spec, yacht-local) that this layout is designed around. HELM / SWITCH / RAIL /
COCKPIT / BOW are unchanged from yacht.glb (sole 1.42 m, cabin aft wall z = -3.33, helm console against it), so
every existing shot keeps working. SITMARK moves from the cabin wall to the aft dinette bench (the hero sits ON the
bench, facing forward) - episodes/sentinel/plan/build_v5.py remaps it (camera keys follow) when the yacht is v2.

Standalone preview (4 angles, studio night light):
  blender -b --factory-startup -P cloud/blender/yacht_v2.py -- --preview /tmp/yacht_v2 [--glb old.glb]
"""
import math
import os
import sys

import bpy
import bmesh
from mathutils import Matrix, Vector

# ---------------------------------------------------------------------------------------------
# layout constants (spec space, metres)
# ---------------------------------------------------------------------------------------------
LOA = 14.0
Z_TR = -7.0           # transom
Z_STEM = 7.0          # stem head
SOLE = 1.42           # cockpit sole (kept from yacht.glb so every episode mark still stands on deck)
Z_AFTWALL = -3.33     # cabin aft bulkhead (switch panel / helm console mount)
Z_CABFRONT = 3.15     # cabin front (base of the windscreen brow)
Z_COCK_AFT = -6.88    # inside face of the transom bulwark
ROOF = 3.40           # cabin roof / flybridge sole underside
FLY = 3.52            # flybridge sole
SIDEDECK = 1.72       # side-deck height along the cabin
WL = 0.05             # static waterline in root space
BWK = 0.10            # bulwark / cap-rail thickness
SEAT = 0.45           # bench seat height above the sole

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from yacht_marks import MARKS_V2 as MARKS  # noqa: E402  (single source of the episode marks)

COLL = []  # objects made by the current build()


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
def B(p):
    return Vector((p[0], -p[2], p[1]))


def smoothstep(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def mat(name, color, rough=0.5, metal=0.0, emit=None, strength=0.0, coat=0.0):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    b.inputs["Coat Weight"].default_value = coat
    if emit is not None:
        b.inputs["Emission Color"].default_value = (*emit, 1.0)
        b.inputs["Emission Strength"].default_value = strength
    return m


class M:
    """the yacht's materials (created lazily so the module imports without bpy data)"""
    @staticmethod
    def init():
        M.hull = mat("gelcoat_hull", (0.85, 0.86, 0.88), 0.3)
        M.gel = mat("gelcoat_white", (0.85, 0.86, 0.88), 0.3)
        M.nonskid = mat("gelcoat_nonskid", (0.80, 0.80, 0.78), 0.55)
        M.teak = mat("teak", (0.3, 0.2, 0.12), 0.7)
        M.steel = mat("steel", (0.7, 0.72, 0.75), 0.2, 1.0)
        M.glass = mat("glass_cabin", (0.02, 0.025, 0.03), 0.05, emit=(1.0, 0.72, 0.4), strength=0.9)
        M.hullglass = mat("glass_cabin_hull", (0.02, 0.025, 0.03), 0.05, emit=(1.0, 0.70, 0.38), strength=0.5)
        M.screen = mat("glass_screen", (0.02, 0.025, 0.03), 0.05)
        M.uph = mat("upholstery_dark", (0.02, 0.025, 0.035), 0.7)
        M.fender = mat("fender", (0.01, 0.035, 0.2), 0.4)
        M.stripe = mat("trim_stripe_navy", (0.008, 0.016, 0.06), 0.25, coat=0.6)
        M.trim = mat("trim_black", (0.012, 0.012, 0.014), 0.25, coat=0.5)
        M.rubber = mat("trim_rubber", (0.02, 0.02, 0.022), 0.7)
        M.red = mat("nav_port_red", (0.5, 0.02, 0.02), 0.2, emit=(1.0, 0.08, 0.05), strength=25.0)
        M.green = mat("nav_stbd_green", (0.02, 0.4, 0.08), 0.2, emit=(0.05, 1.0, 0.3), strength=25.0)
        M.white = mat("nav_white", (0.8, 0.8, 0.8), 0.2, emit=(1.0, 0.97, 0.9), strength=25.0)
        M.ring_o = mat("lifering_orange", (0.8, 0.12, 0.02), 0.45, coat=0.3)
        M.ring_w = mat("lifering_white", (0.8, 0.8, 0.78), 0.45, coat=0.3)
        M.rope = mat("rope_white", (0.55, 0.53, 0.48), 0.85)
        M.chain = mat("steel_chain", (0.5, 0.5, 0.52), 0.35, 1.0)
        M.radar = mat("gelcoat_radar", (0.86, 0.87, 0.88), 0.25)


def obj_from_bm(name, bm, mats, smooth=True, sharp=None, parent=None, weighted=False, facing=None):
    """facing: spec-space direction single-sided sheets must face (recalc cannot orient an open sheet reliably)"""
    me = bpy.data.meshes.new(name)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    if facing is not None:
        fv = B(facing)
        bm.normal_update()
        flip = [f for f in bm.faces if f.normal.dot(fv) < 0]
        if flip:
            bmesh.ops.reverse_faces(bm, faces=flip)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    if smooth:
        me.shade_smooth()
        if sharp is not None:
            me.set_sharp_from_angle(angle=math.radians(sharp))
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    if parent is not None:
        ob.parent = parent
    if weighted:
        mod = ob.modifiers.new("wn", "WEIGHTED_NORMAL")
        mod.keep_sharp = True
    COLL.append(ob)
    return ob


def mesh(name, verts, faces, mats, parent, smooth=True, sharp=35, mat_idx=None, weighted=False, facing=None):
    """verts in SPEC space"""
    bm = bmesh.new()
    vs = [bm.verts.new(B(v)) for v in verts]
    for i, f in enumerate(faces):
        try:
            fc = bm.faces.new([vs[k] for k in f])
            if mat_idx:
                fc.material_index = mat_idx[i]
        except ValueError:
            pass
    return obj_from_bm(name, bm, mats if isinstance(mats, (list, tuple)) else [mats], smooth, sharp, parent, weighted, facing)


def loft(name, rings, mats, parent, closed=False, cap0=False, cap1=False, smooth=True, sharp=35, face_mat=None, facing=None):
    """rings: list of point lists (same length, spec space). face_mat(i, j) -> material index."""
    n = len(rings[0])
    verts = [p for r in rings for p in r]
    faces, idx = [], []
    for i in range(len(rings) - 1):
        a, b = i * n, (i + 1) * n
        for j in range(n if closed else n - 1):
            j1 = (j + 1) % n
            faces.append((a + j, a + j1, b + j1, b + j))
            idx.append(face_mat(i, j) if face_mat else 0)
    if cap0:
        faces.append(tuple(range(n - 1, -1, -1)))
        idx.append(0)
    if cap1:
        last = (len(rings) - 1) * n
        faces.append(tuple(last + j for j in range(n)))
        idx.append(0)
    return mesh(name, verts, faces, mats, parent, smooth, sharp, idx, facing=facing)


def rbox(name, c, s, mats, parent, r=0.02, seg=3, rot=None):
    """rounded box (spec centre/size); rot = (axis 'X'|'Y'|'Z' in spec, degrees) about the centre."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector((s[0], s[2], s[1])), verts=bm.verts)
    if r > 0:
        rr = min(r, min(s) * 0.49)
        bmesh.ops.bevel(bm, geom=bm.edges[:] + bm.verts[:], offset=rr, segments=seg, affect="EDGES", profile=0.5)
    if rot:
        ax = {"X": "X", "Y": "Z", "Z": "Y"}[rot[0]]
        ang = math.radians(rot[1]) * (-1 if rot[0] == "Z" else 1)
        bmesh.ops.rotate(bm, verts=bm.verts, cent=Vector(), matrix=Matrix.Rotation(ang, 3, ax))
    bmesh.ops.translate(bm, vec=B(c), verts=bm.verts)
    return obj_from_bm(name, bm, mats if isinstance(mats, (list, tuple)) else [mats], True, 40, parent, weighted=r > 0)


def tube(name, pts, r, mats, parent, sides=10, closed=False, caps=True):
    """tube along a spec-space polyline (parallel-transport frames)."""
    P = [Vector(p) for p in pts]
    n = len(P)
    T = []
    for i in range(n):
        if closed:
            d = P[(i + 1) % n] - P[i - 1]
        else:
            d = P[min(i + 1, n - 1)] - P[max(i - 1, 0)]
        T.append(d.normalized())
    up = Vector((0, 1, 0)) if abs(T[0].y) < 0.9 else Vector((1, 0, 0))
    N0 = T[0].cross(up).normalized()
    frames = []
    Nc = N0
    for i in range(n):
        if i > 0:
            Nc = (Nc - T[i] * Nc.dot(T[i])).normalized()
        frames.append((Nc, T[i].cross(Nc).normalized()))
    rings = []
    for i in range(n):
        Nn, Bn = frames[i]
        rr = r[i] if isinstance(r, (list, tuple)) else r
        rings.append([P[i] + (Nn * math.cos(2 * math.pi * k / sides) + Bn * math.sin(2 * math.pi * k / sides)) * rr for k in range(sides)])
    if closed:
        rings.append(rings[0])
    return loft(name, rings, mats, parent, closed=True, cap0=caps and not closed, cap1=caps and not closed, sharp=None)


def cyl(name, c, r, h, mats, parent, axis="Y", seg=20, r2=None):
    """cylinder along a spec axis, centred at c"""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r, radius2=r if r2 is None else r2, depth=h)
    # bmesh cone is along Blender Z = spec Y
    if axis == "X":
        bmesh.ops.rotate(bm, verts=bm.verts, cent=Vector(), matrix=Matrix.Rotation(math.pi / 2, 3, "Y"))
    elif axis == "Z":
        bmesh.ops.rotate(bm, verts=bm.verts, cent=Vector(), matrix=Matrix.Rotation(math.pi / 2, 3, "X"))
    elif isinstance(axis, Matrix):
        bmesh.ops.rotate(bm, verts=bm.verts, cent=Vector(), matrix=axis)
    bmesh.ops.translate(bm, vec=B(c), verts=bm.verts)
    return obj_from_bm(name, bm, mats if isinstance(mats, (list, tuple)) else [mats], True, 40, parent)


def sphere(name, c, r, mats, parent, scale=(1, 1, 1), seg=16):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=max(6, seg // 2), radius=r)
    bmesh.ops.scale(bm, vec=Vector((scale[0], scale[2], scale[1])), verts=bm.verts)
    bmesh.ops.translate(bm, vec=B(c), verts=bm.verts)
    return obj_from_bm(name, bm, mats if isinstance(mats, (list, tuple)) else [mats], True, None, parent)


def torus(name, c, R, r, mats, parent, normal="Z", segs=32, sides=10, mat_fn=None):
    """torus in spec space; normal axis X|Y|Z (spec). mat_fn(i) -> material index of segment i."""
    ring = []
    for i in range(segs):
        a = 2 * math.pi * i / segs
        row = []
        for k in range(sides):
            b = 2 * math.pi * k / sides
            rad = R + r * math.cos(b)
            p = [rad * math.cos(a), rad * math.sin(a), r * math.sin(b)]   # local: ring in XY, normal Z
            if normal == "Y":
                p = [p[0], p[2], p[1]]
            elif normal == "X":
                p = [p[2], p[1], p[0]]
            row.append((c[0] + p[0], c[1] + p[1], c[2] + p[2]))
        ring.append(row)
    ring.append(ring[0])
    return loft(name, ring, mats, parent, closed=True, sharp=None, face_mat=(lambda i, j: mat_fn(i)) if mat_fn else None)


# ---------------------------------------------------------------------------------------------
# hull lines
# ---------------------------------------------------------------------------------------------
def tz(z):
    return (z - Z_TR) / LOA


def half_beam(z):
    """sheer half-beam"""
    t = tz(z)
    bow = ((t - 0.60) / 0.40) ** 1.65 if t > 0.60 else 0.0
    stern = 0.955 + 0.045 * smoothstep(0.0, 0.12, t)
    return 2.15 * stern * max(0.0, 1.0 - bow * 0.995)


def sheer(z):
    # sweeping sheer + a raised aft bulwark round the cockpit (~0.8 m above the sole at the transom)
    return 1.80 + 0.00595 * (z + 1.5) ** 2 + 0.26 * smoothstep(-2.6, -5.2, z)


def keel(z):
    t = tz(z)
    return -0.72 + 0.10 * t * t + max(0.0, t - 0.68) ** 2 * 8.0


def deck_y(z):
    """deck height outboard of the cabin / on the foredeck (cockpit is SOLE)"""
    if z <= Z_AFTWALL:
        return SOLE
    if z < Z_CABFRONT:
        return SIDEDECK + 0.035 * smoothstep(0.0, Z_CABFRONT, z)
    return SIDEDECK + 0.035 + 0.07 * (z - Z_CABFRONT) * (1 + 0.15 * (z - Z_CABFRONT))


NSTA = 72


def hull_section(z):
    """starboard half section (spec points) keel -> sheer at station z. Returns (pts, chine_index)."""
    t = tz(z)
    b = max(half_beam(z), 0.004)
    s = sheer(z)
    k = keel(z)
    beta = math.radians(13 + 32 * t ** 2.2)
    cx = b * (0.90 - 0.30 * smoothstep(0.55, 1.0, t))
    cy = k + cx * math.tan(beta) + 0.55 * smoothstep(0.75, 1.0, t) ** 1.5
    cy = min(cy, s - 0.25 * max(b, 0.05))
    pts = []
    # bottom keel -> chine with two spray rails (small outward steps that face down)
    nb = 12
    rails = (4, 8)
    for i in range(nb + 1):
        u = i / nb
        x = cx * u
        y = k + (cy - k) * (u * 0.85 + 0.15 * u * u)
        pts.append([x, y])
        if i in rails:
            pts.append([x + 0.028 * min(1.0, b / 0.6), y + 0.004])
    chine_i = len(pts) - 1
    # chine flat (reverse chine lip)
    pts.append([cx + 0.06 * min(1.0, b / 0.5), cy + 0.012])
    # topsides chine -> sheer with flare
    x0, y0 = pts[-1]
    nt = 12
    for i in range(1, nt + 1):
        u = i / nt
        x = x0 + (b - x0) * (1 - (1 - u) ** 1.7)
        y = y0 + (s - y0) * u
        pts.append([x, y])
    # stem rake: lower points pulled aft near the bow
    f = smoothstep(0.80, 1.0, t) ** 1.4
    out = []
    for x, y in pts:
        h = min(1.0, max(0.0, (s - y) / max(s - k, 0.01)))
        out.append((x, y, z - 1.05 * f * h ** 1.25))
    return out, chine_i


def hull_x(z, y):
    """outer hull half-width at station z, height y (topsides)"""
    pts, _ = hull_section(z)
    for a, b in zip(pts, pts[1:]):
        if a[1] <= y <= b[1]:
            u = (y - a[1]) / max(b[1] - a[1], 1e-6)
            return lerp(a[0], b[0], u)
    return pts[-1][0]


def stations(z0, z1, n):
    return [lerp(z0, z1, i / n) for i in range(n + 1)]


# ---------------------------------------------------------------------------------------------
# parts
# ---------------------------------------------------------------------------------------------
def build_hull(root):
    zs = stations(Z_TR, Z_STEM, NSTA)
    rings = []
    for z in zs:
        half, _ = hull_section(z)
        port = [(-x, y, zz) for (x, y, zz) in reversed(half)]
        rings.append(port + list(half[1:]))
    hull = loft("gelcoat_hull", rings, [M.hull], root, sharp=28)
    # transom: a flat fan (own object so the hull stays one clean loft for oceanfx's footprint)
    tr = rings[0]
    cen = (0.0, sum(p[1] for p in tr) / len(tr), Z_TR)
    mesh("gelcoat_hull_transom", [cen] + tr, [(0, i + 1, i + 2) for i in range(len(tr) - 1)] + [(0, len(tr), 1)], [M.hull], root, smooth=False, facing=(0, 0, -1))
    # rub rail just below the sheer (stainless-capped rubber)
    pts = [(half_beam(z) + 0.035, sheer(z) - 0.11, z) for z in stations(Z_TR + 0.02, Z_STEM - 0.35, 48)]
    tube("trim_rubrail_s", pts, 0.035, [M.rubber], root, sides=8)
    tube("trim_rubrail_p", [(-x, y, z) for x, y, z in pts], 0.035, [M.rubber], root, sides=8)
    tube("steel_rubrail_s", [(x + 0.03, y, z) for x, y, z in pts], 0.012, [M.steel], root, sides=6)
    tube("steel_rubrail_p", [(-x - 0.03, y, z) for x, y, z in pts], 0.012, [M.steel], root, sides=6)
    # navy cove stripe below the rub rail
    zs3 = stations(Z_TR + 0.01, 6.2, 60)
    for side in (1, -1):
        rows = []
        for z in zs3:
            y0, y1 = sheer(z) - 0.30, sheer(z) - 0.22
            rows.append([(side * (hull_x(z, y0) + 0.004), y0, z), (side * (hull_x(z, y1) + 0.004), y1, z)])
        loft(f"trim_stripe_{'s' if side > 0 else 'p'}", rows, [M.stripe], root, sharp=None, facing=(side, 0, 0))
    # long hull windows (owner's cabin) - dark glass with a warm glow, proud of the topsides
    for side in (1, -1):
        zs2 = stations(-1.7, 2.3, 16)
        top = [(side * (hull_x(z, 1.30 + 0.06 * smoothstep(-1.7, 2.3, z)) + 0.008), 1.30 + 0.06 * smoothstep(-1.7, 2.3, z), z) for z in zs2]
        bot = [(side * (hull_x(z, 1.06 + 0.10 * smoothstep(-1.7, 2.3, z)) + 0.008), 1.06 + 0.10 * smoothstep(-1.7, 2.3, z), z) for z in zs2]
        # taper both ends (lozenge)
        for k_, dz in ((0, 0.08), (-1, -0.08)):
            m_ = ((bot[k_][0] + top[k_][0]) / 2, (bot[k_][1] + top[k_][1]) / 2, bot[k_][2] + dz)
            bot[k_] = top[k_] = m_
        loft(f"glass_cabin_hull_{'s' if side > 0 else 'p'}", [[b_, t_] for b_, t_ in zip(bot, top)], [M.hullglass], root, facing=(side, 0, 0))
        frame = bot[:-1] + list(reversed(top))[:-1]
        tube(f"trim_hullwin_{'s' if side > 0 else 'p'}", [(x + side * 0.006, y, z) for x, y, z in frame], 0.012, [M.steel], root, sides=6, closed=True)
    # transom: swim platform + ladder
    rbox("teak_swim_platform", (0, 0.45, Z_TR - 0.46), (4.0, 0.12, 0.9), [M.teak], root, r=0.03)
    rbox("gelcoat_platform_lip", (0, 0.37, Z_TR - 0.46), (4.04, 0.06, 0.94), [M.gel], root, r=0.025)
    for x in (0.95, 1.25):
        tube(f"steel_ladder_{x}", [(x, 0.52, Z_TR - 0.86), (x, 0.40, Z_TR - 0.95), (x, -0.55, Z_TR - 1.02)], 0.014, [M.steel], root, sides=8)
    for y in (0.1, -0.2, -0.5):
        cyl(f"steel_ladder_rung_{y}", (1.10, y, Z_TR - 0.99), 0.016, 0.32, [M.steel], root, axis="X", seg=10)
    # transom steps up to the cockpit (port & starboard quarters)
    for side in (1, -1):
        for i, (y, dz) in enumerate(((0.80, 0.0), (1.15, 0.0))):
            rbox(f"teak_transom_step_{side}_{i}", (side * 1.55, y, Z_TR - 0.13 + 0.0 * dz), (0.7, 0.06, 0.26), [M.teak], root, r=0.015)
    # stern light + exhaust outlets
    sphere("nav_white_stern", (0, sheer(Z_TR) - 0.15, Z_TR - 0.02), 0.04, [M.white], root, scale=(1.4, 1, 0.6))
    for side in (1, -1):
        cyl(f"steel_exhaust_{side}", (side * 1.35, 0.55, Z_TR - 0.01), 0.07, 0.04, [M.steel], root, axis="Z")
    return hull


def build_decks(root):
    # cockpit sole
    zs = stations(Z_COCK_AFT, Z_AFTWALL, 10)
    rings = [[(-(half_beam(z) - BWK), SOLE, z), (half_beam(z) - BWK, SOLE, z)] for z in zs]
    loft("teak_cockpit_sole", rings, [M.teak], root, sharp=None, facing=(0, 1, 0))
    # bulwarks: inner faces + teak cap rail (cockpit, side decks, foredeck), one loft per side
    zs = stations(Z_COCK_AFT, Z_STEM - 0.25, 64)
    for side in (1, -1):
        rings = []
        for z in zs:
            b, s = half_beam(z), sheer(z)
            d = deck_y(z)
            w = BWK if b > 0.3 else b * 0.33
            rings.append([(side * (b + 0.004), s - 0.03, z), (side * (b - 0.01), s + 0.025, z), (side * (b - w + 0.01), s + 0.025, z),
                          (side * (b - w), s - 0.03, z), (side * (b - w), d, z)])
        loft(f"gelcoat_bulwark_{side}", [r[2:] for r in rings], [M.gel], root, sharp=30)
        loft(f"teak_caprail_{side}", [r[:4] for r in rings], [M.teak], root, sharp=30)
    # transom bulwark (inside) + cap
    xs = half_beam(Z_COCK_AFT) - BWK
    rbox("gelcoat_transom_bulwark", (0, (SOLE + sheer(Z_TR)) / 2, Z_COCK_AFT - 0.06), (2 * xs + 0.02, sheer(Z_TR) - SOLE, 0.12), [M.gel], root, r=0.01)
    rbox("teak_transom_cap", (0, sheer(Z_TR) + 0.015, Z_TR + 0.06), (2 * half_beam(Z_TR) - 0.02, 0.05, 0.2), [M.teak], root, r=0.012)
    # side decks along the cabin (teak) and foredeck (teak with gelcoat margin)
    for side in (1, -1):
        rings = []
        for z in stations(Z_AFTWALL, Z_CABFRONT, 24):
            rings.append([(side * cabin_hw(z, deck_y(z)), deck_y(z), z), (side * (half_beam(z) - BWK), deck_y(z), z)])
        loft(f"teak_sidedeck_{side}", rings, [M.teak], root, sharp=None, facing=(0, 1, 0))
        # riser: cockpit sole -> side deck step at the aft wall, with a teak tread
        x0, x1 = cabin_hw(Z_AFTWALL, SIDEDECK), half_beam(Z_AFTWALL) - BWK
        mesh(f"gelcoat_riser_{side}", [(side * x0, SOLE, Z_AFTWALL), (side * x1, SOLE, Z_AFTWALL), (side * x1, SIDEDECK, Z_AFTWALL), (side * x0, SIDEDECK, Z_AFTWALL)],
             [(0, 1, 2, 3)], [M.gel], root, facing=(0, 0, -1))
        rbox(f"teak_step_{side}", (side * (x0 + x1) / 2, SOLE + 0.15, Z_AFTWALL - 0.16), (x1 - x0 - 0.04, 0.05, 0.3), [M.teak], root, r=0.012)
        rbox(f"gelcoat_step_{side}", (side * (x0 + x1) / 2, SOLE + 0.06, Z_AFTWALL - 0.16), (x1 - x0 - 0.04, 0.12, 0.28), [M.gel], root, r=0.01)
    zs = stations(Z_CABFRONT - 0.05, Z_STEM - 0.25, 24)
    rings = []
    for z in zs:
        hw = max(half_beam(z) - BWK, 0.01)
        d = deck_y(z)
        rings.append([(x * hw, d + 0.03 * (1 - x * x), z) for x in (-1, -0.5, 0, 0.5, 1)])
    loft("teak_foredeck", rings, [M.teak], root, sharp=None, facing=(0, 1, 0))


def cabin_hw(z, y=None):
    """cabin side wall half-width at station z (and height y: 6 deg tumblehome)"""
    hw = min(1.58, half_beam(z) - 0.50)
    if y is not None:
        hw -= max(0.0, y - SIDEDECK) * 0.10
    return hw


def roof_y(z):
    if z <= 1.30:
        return ROOF
    return lerp(ROOF, 2.18, smoothstep(1.30, Z_CABFRONT, z) ** 0.85)


def build_cabin(root):
    zs = stations(Z_AFTWALL, Z_CABFRONT, 30)
    rings = []
    for z in zs:
        base = deck_y(z)
        r = roof_y(z)
        ring = [(-cabin_hw(z, base), base, z), (-cabin_hw(z, r - 0.06), r - 0.06, z), (-cabin_hw(z, r) + 0.06, r, z),
                (cabin_hw(z, r) - 0.06, r, z), (cabin_hw(z, r - 0.06), r - 0.06, z), (cabin_hw(z, base), base, z)]
        rings.append(ring)

    def fm(i, j):  # raked windscreen faces on the roof slope
        z = lerp(zs[i], zs[i + 1], 0.5)
        return 1 if (z > 1.45 and z < Z_CABFRONT - 0.18 and j in (1, 2, 3)) else 0
    cab = loft("gelcoat_cabin", rings, [M.gel, M.screen], root, sharp=30, face_mat=fm)
    # aft bulkhead from the cockpit sole to the roof, full width of the cabin
    hw0 = cabin_hw(Z_AFTWALL, SOLE)
    mesh("gelcoat_aftwall", [(-hw0, SOLE, Z_AFTWALL), (hw0, SOLE, Z_AFTWALL), (cabin_hw(Z_AFTWALL, ROOF - 0.06), ROOF - 0.06, Z_AFTWALL),
                             (cabin_hw(Z_AFTWALL, ROOF) - 0.06, ROOF, Z_AFTWALL), (-cabin_hw(Z_AFTWALL, ROOF) + 0.06, ROOF, Z_AFTWALL),
                             (-cabin_hw(Z_AFTWALL, ROOF - 0.06), ROOF - 0.06, Z_AFTWALL)], [(0, 1, 2, 3, 4, 5)], [M.gel], root, facing=(0, 0, -1))
    # front brow (vertical face below the windscreen)
    zf = Z_CABFRONT
    d = deck_y(zf)
    hwb, hwt = cabin_hw(zf, d), cabin_hw(zf, roof_y(zf))
    mesh("gelcoat_cabin_brow", [(-hwb, d, zf), (hwb, d, zf), (hwt - 0.06, roof_y(zf), zf), (-hwt + 0.06, roof_y(zf), zf)], [(0, 1, 2, 3)], [M.gel], root, facing=(0, 0, 1))
    # windscreen frame + mullions
    zw0, zw1 = 1.45, Z_CABFRONT - 0.18
    for side in (1, -1):
        edge = [(side * (cabin_hw(z, roof_y(z)) - 0.05), roof_y(z) + 0.012, z) for z in stations(zw0, zw1, 8)]
        tube(f"trim_screen_edge_{side}", edge, 0.025, [M.trim], root, sides=6)
        mz = lerp(zw0, zw1, 0.5)
        tube(f"trim_screen_mullion_{side}", [(side * 0.55, roof_y(z) + 0.014, z) for z in stations(zw0, zw1, 6)], 0.02, [M.trim], root, sides=6)
    tube("trim_screen_bottom", [(x, roof_y(zw1) + 0.014, zw1) for x in [i / 10 * 2 * (cabin_hw(zw1, roof_y(zw1)) - 0.05) - (cabin_hw(zw1, roof_y(zw1)) - 0.05) for i in range(11)]], 0.025, [M.trim], root, sides=6)
    tube("trim_screen_top", [(x, ROOF + 0.014, zw0) for x in [i / 10 * 2 * (cabin_hw(zw0, ROOF) - 0.05) - (cabin_hw(zw0, ROOF) - 0.05) for i in range(11)]], 0.025, [M.trim], root, sides=6)
    # raked side windows: long dark panes proud of the walls, raked aft end, black frames
    for side in (1, -1):
        s_ = "s" if side > 0 else "p"
        yb, yt = 2.10, 2.98
        za_b, za_t = -3.00, -2.55   # aft end raked forward going up
        zf_b, zf_t = 1.25, 1.10     # front end
        grid = []
        for v in (0.0, 1.0):
            y = lerp(yb, yt, v)
            z0, z1 = lerp(za_b, za_t, v), lerp(zf_b, zf_t, v)
            grid.append([(side * (cabin_hw(z, y) + 0.012), y, z) for z in stations(z0, z1, 18)])
        rows = [[grid[0][i], grid[1][i]] for i in range(len(grid[0]))]
        loft(f"glass_cabin_side_{s_}", rows, [M.glass], root, sharp=None, facing=(side, 0, 0))
        frame = grid[0] + list(reversed(grid[1]))
        tube(f"trim_sidewin_{s_}", [(x + side * 0.004, y, z) for x, y, z in frame], 0.022, [M.trim], root, sides=6, closed=True)
        # two mullions
        for zm in (-1.30, 0.10):
            tube(f"trim_sidewin_mullion_{s_}_{zm}", [(side * (cabin_hw(zm, y) + 0.018), y, zm) for y in (yb, yt)], 0.016, [M.trim], root, sides=6)
        # nav sidelights on the cabin sides forward
        zn = 2.55
        yn = 2.25
        xn = cabin_hw(zn, yn) + 0.03
        rbox(f"gelcoat_navbox_{s_}", (side * xn, yn, zn), (0.06, 0.12, 0.22), [M.gel], root, r=0.015)
        rbox(f"{'nav_stbd_green' if side > 0 else 'nav_port_red'}_lens", (side * (xn + 0.035), yn, zn + 0.03), (0.02, 0.07, 0.12),
             [M.green if side > 0 else M.red], root, r=0.008)
    # aft wall: glass sliding door + windows in frames (cockpit side), the switch-panel pier stays solid
    za = Z_AFTWALL - 0.012
    def pane(name, x0, x1, y0, y1, m=M.glass):
        mesh(name, [(x0, y0, za), (x1, y0, za), (x1, y1, za), (x0, y1, za)], [(0, 1, 2, 3)], [m], root, smooth=False, facing=(0, 0, -1))
        tube("trim_" + name, [(x0, y0, za - 0.004), (x1, y0, za - 0.004), (x1, y1, za - 0.004), (x0, y1, za - 0.004)], 0.02, [M.trim], root, sides=6, closed=True)
    pane("glass_cabin_door", -0.60, 0.04, SOLE + 0.06, 3.25)
    pane("glass_cabin_aft_p", -1.50, -0.70, 2.86, 3.25)
    pane("glass_cabin_aft_s", 0.14, 1.48, 2.48, 3.25)
    tube("steel_door_handle", [(0.0, 2.15, za - 0.03), (0.0, 2.55, za - 0.03)], 0.012, [M.steel], root, sides=8)
    # cabin-top grab rails
    for side in (1, -1):
        pts = [(side * (cabin_hw(z, ROOF) - 0.12), ROOF + 0.07, z) for z in stations(-2.6, 0.9, 10)]
        tube(f"steel_grabrail_{side}", pts, 0.013, [M.steel], root, sides=8)
        for z in (-2.6, -0.85, 0.9):
            cyl(f"steel_grabpost_{side}_{z}", (side * (cabin_hw(z, ROOF) - 0.12), ROOF + 0.035, z), 0.011, 0.07, [M.steel], root, seg=8)
    return cab


def build_flybridge(root):
    zb0, zb1 = -3.90, 1.30
    # flybridge sole slab (overhangs the aft wall over the helm)
    rbox("gelcoat_fly_sole", (0, (ROOF + FLY) / 2, (zb0 + zb1) / 2), (2 * cabin_hw(-1, ROOF) + 0.10, FLY - ROOF + 0.02, zb1 - zb0), [M.gel], root, r=0.05)
    hw = cabin_hw(-1, ROOF) + 0.03
    ytop = FLY + 0.50
    # coaming: low moulded wall all round, rounded corners
    pts = []
    for i in range(9):
        a = math.pi / 2 * i / 8
        pts.append((hw - 0.25 + 0.25 * math.cos(a), zb1 - 0.25 + 0.25 * math.sin(a)))
    pts = [(hw, zb0 + 0.25)] + list(reversed([(x, z) for x, z in pts]))
    outline = [(hw - 0.25 + 0.25 * math.cos(-math.pi / 2 * i / 8), zb0 + 0.25 + 0.25 * math.sin(-math.pi / 2 * i / 8)) for i in range(8, -1, -1)]
    outline = [(x, z) for x, z in reversed(outline)]
    right = [(hw - 0.25 + 0.25 * math.cos(a), zb0 + 0.25 + 0.25 * math.sin(a)) for a in [-math.pi / 2 + math.pi / 2 * i / 8 for i in range(9)]]
    right += [(hw - 0.25 + 0.25 * math.cos(a), zb1 - 0.25 + 0.25 * math.sin(a)) for a in [math.pi / 2 * i / 8 for i in range(9)]]
    loop = right + [(-x, z) for x, z in reversed(right)]
    rings = []
    for x, z in loop:
        rings.append([(x * 0.985, FLY, z), (x, FLY + 0.02, z), (x, ytop, z), (x * 0.96, ytop + 0.03, z), (x * 0.94, ytop, z), (x * 0.94, FLY, z)])
    rings.append(rings[0])
    loft("gelcoat_fly_coaming", rings, [M.gel], root, sharp=30)
    # flybridge windscreen (small tinted screen on the front coaming)
    zf = zb1 - 0.02
    ws = [[(x, ytop + 0.02, zf - 0.04), (x * 0.97, ytop + 0.28, zf - 0.20)] for x in [lerp(-hw + 0.3, hw - 0.3, i / 10) for i in range(11)]]
    loft("glass_screen_fly", ws, [M.screen], root, sharp=None, facing=(0, 0.5, 1))
    tube("trim_fly_screen", [w[1] for w in ws], 0.014, [M.trim], root, sides=6)
    # flybridge helm console + seat + wheel + bench
    rbox("gelcoat_fly_console", (0.55, FLY + 0.42, 0.62), (0.95, 0.84, 0.55), [M.gel], root, r=0.08)
    rbox("trim_fly_dash", (0.55, FLY + 0.82, 0.48), (0.86, 0.04, 0.32), [M.trim], root, r=0.015, rot=("X", -30))
    torus("steel_fly_wheel", (0.55, FLY + 0.86, 0.28), 0.18, 0.012, [M.steel], root, normal="Z", segs=24, sides=6)
    rbox("upholstery_fly_helmseat", (0.55, FLY + 0.52, -0.35), (0.95, 0.16, 0.5), [M.uph], root, r=0.06)
    rbox("upholstery_fly_helmback", (0.55, FLY + 0.85, -0.58), (0.95, 0.5, 0.12), [M.uph], root, r=0.05)
    rbox("gelcoat_fly_seatbase", (0.55, FLY + 0.22, -0.35), (0.9, 0.44, 0.45), [M.gel], root, r=0.04)
    # aft L-bench on the flybridge
    rbox("gelcoat_fly_benchbase", (0.0, FLY + 0.2, -3.45), (2.6, 0.4, 0.5), [M.gel], root, r=0.04)
    rbox("upholstery_fly_bench", (0.0, FLY + 0.47, -3.45), (2.6, 0.14, 0.5), [M.uph], root, r=0.06)
    rbox("upholstery_fly_benchback", (0.0, FLY + 0.60, -3.70), (2.6, 0.36, 0.10), [M.uph], root, r=0.04, rot=("X", 10))
    # radar arch: two raked moulded legs + crossbeam, carries the hardtop
    za = -2.15
    for side in (1, -1):
        leg = [(side * (hw - 0.12), FLY + 0.0, za - 0.25), (side * (hw - 0.14), FLY + 0.45, za - 0.12), (side * (hw - 0.17), 4.25, za + 0.05)]
        rings = []
        for x, y, z in leg:
            rings.append([(x - 0.09, y, z - 0.22), (x + 0.09, y, z - 0.22), (x + 0.09, y, z + 0.22), (x - 0.09, y, z + 0.22)])
        loft(f"gelcoat_arch_leg_{side}", rings, [M.gel], root, closed=True, sharp=50)
    # hardtop: thin rounded slab, aft edge over the flybridge bench, front strut tubes
    ht0, ht1 = -3.75, 0.55
    rbox("gelcoat_hardtop", (0, 4.36, (ht0 + ht1) / 2), (2 * hw + 0.12, 0.13, ht1 - ht0), [M.gel], root, r=0.06)
    rbox("trim_hardtop_edge", (0, 4.30, (ht0 + ht1) / 2), (2 * hw + 0.13, 0.03, ht1 - ht0 + 0.01), [M.trim], root, r=0.012)
    for side in (1, -1):
        tube(f"steel_hardtop_strut_{side}", [(side * (hw - 0.15), ytop + 0.02, 1.05), (side * (hw - 0.18), 4.29, 0.45)], 0.025, [M.steel], root, sides=10)
    # radar dome, mast + masthead light, antennae
    cyl("gelcoat_radar_base", (0, 4.47, -1.0), 0.18, 0.08, [M.radar], root, seg=24)
    sphere("gelcoat_radar_dome", (0, 4.56, -1.0), 0.30, [M.radar], root, scale=(1, 0.42, 1), seg=24)
    tube("steel_mast", [(0, 4.42, -1.9), (0, 5.75, -1.95)], 0.035, [M.steel], root, sides=10)
    tube("steel_mast_yard", [(-0.45, 5.35, -1.94), (0.45, 5.35, -1.94)], 0.018, [M.steel], root, sides=8)
    sphere("nav_white_mast", (0, 5.80, -1.95), 0.05, [M.white], root, scale=(1, 1.4, 1), seg=12)
    for side in (1, -1):
        tube(f"trim_antenna_{side}", [(side * (hw - 0.2), 4.43, -2.6), (side * (hw - 0.2), 5.55, -2.75)], 0.012, [M.trim], root, sides=6)
    # ladder from the cockpit to the flybridge (port aft, stainless)
    # (starboard, outboard of the helm console, clear of the SWITCH / HELM / RAIL marks)
    for x in (1.22, 1.56):
        tube(f"steel_flyladder_{x}", [(x, SOLE + 0.01, -4.42), (x, FLY + 0.02, -3.93), (x, FLY + 0.62, -3.80)], 0.016, [M.steel], root, sides=8)
    for i in range(1, 6):
        u = i / 6
        y = lerp(SOLE, FLY, u)
        z = lerp(-4.42, -3.93, u)
        rbox(f"teak_flyladder_step_{i}", (1.39, y, z), (0.32, 0.03, 0.11), [M.teak], root, r=0.008)
    # life ring on the flybridge aft coaming face (starboard)
    torus("lifering", (-1.05, FLY + 0.20, zb0 - 0.06), 0.27, 0.06, [M.ring_o, M.ring_w], root, normal="Z", segs=32, sides=12,
          mat_fn=lambda i: 1 if (i // 4) % 2 else 0)
    return hw


def build_cockpit(root):
    """U-shaped dinette at the transom: aft bench + port/starboard arms, teak table, cushions; free sole forward."""
    xa = half_beam(Z_COCK_AFT) - BWK      # inner bulwark at the transom
    zf_arm = -5.45
    sz0 = Z_COCK_AFT
    seat = SOLE + SEAT
    # moulded bases (gelcoat), with a toe-kick recess
    rbox("gelcoat_bench_aft", (0, SOLE + (SEAT - 0.10) / 2 + 0.0, sz0 + 0.27), (2 * xa, SEAT - 0.10, 0.54), [M.gel], root, r=0.03)
    for side in (1, -1):
        rbox(f"gelcoat_bench_arm_{side}", (side * (xa - 0.25), SOLE + (SEAT - 0.10) / 2, (sz0 + 0.54 + zf_arm) / 2), (0.50, SEAT - 0.10, zf_arm - sz0 - 0.54), [M.gel], root, r=0.03)
    # seat cushions + back cushions
    rbox("upholstery_seat_aft", (0, seat - 0.05, sz0 + 0.30), (2 * xa - 0.04, 0.12, 0.50), [M.uph], root, r=0.05)
    bt = sheer(Z_TR) - 0.02 - seat  # back cushion height: top just under the cap rail
    rbox("upholstery_back_aft", (0, seat + 0.02 + bt / 2, sz0 + 0.07), (2 * xa - 0.10, bt, 0.13), [M.uph], root, r=0.05, rot=("X", 8))
    for side in (1, -1):
        rbox(f"upholstery_seat_arm_{side}", (side * (xa - 0.26), seat - 0.05, (sz0 + 0.56 + zf_arm) / 2), (0.48, 0.12, zf_arm - sz0 - 0.58), [M.uph], root, r=0.05)
        bta = sheer(zf_arm) - 0.03 - seat
        rbox(f"upholstery_back_arm_{side}", (side * (xa - 0.04), seat + 0.02 + bta / 2, (sz0 + 0.20 + zf_arm) / 2), (0.12, bta, zf_arm - sz0 - 0.24), [M.uph], root, r=0.05)
    # piping lines between cushions (dark seams)
    for x in (-0.65, 0.65):
        rbox(f"trim_seam_{x}", (x, seat + 0.008, sz0 + 0.30), (0.01, 0.01, 0.48), [M.trim], root, r=0.0)
    # teak table on a stainless pedestal, rounded corners, fiddle edge
    tz_ = -5.90
    rbox("teak_table", (0.38, SOLE + 0.72, tz_), (0.90, 0.04, 0.62), [M.teak], root, r=0.02)
    rbox("trim_table_edge", (0.38, SOLE + 0.70, tz_), (0.92, 0.03, 0.64), [M.trim], root, r=0.015)
    cyl("steel_table_post", (0.38, SOLE + 0.36, tz_), 0.045, 0.70, [M.steel], root, seg=16)
    cyl("steel_table_foot", (0.38, SOLE + 0.012, tz_), 0.20, 0.025, [M.steel], root, seg=24)
    # hatch outlines in the sole (lazarette) + drains
    for x0, x1, z0, z1 in ((-0.55, 0.55, -5.20, -4.70),):
        tube("trim_lazarette", [(x0, SOLE + 0.003, z0), (x1, SOLE + 0.003, z0), (x1, SOLE + 0.003, z1), (x0, SOLE + 0.003, z1)], 0.006, [M.trim], root, sides=4, closed=True)
        cyl("steel_lazarette_ring", (0, SOLE + 0.005, z1 - 0.06), 0.03, 0.006, [M.steel], root, seg=12)
    # cockpit cleats / courtesy lights in the bulwarks
    for side in (1, -1):
        for z in (-6.2, -5.0, -3.9):
            x = side * (half_beam(z) - BWK - 0.003)
            rbox(f"nav_white_courtesy_{side}_{z}", (x, SOLE + 0.18, z), (0.01, 0.04, 0.08), [M.white], root, r=0.004)


def cleat(name, c, along="Z", root=None, L=0.26):
    x, y, z = c
    if along == "Z":
        horn = [(x, y + 0.055, z - L / 2), (x, y + 0.075, z - L / 4), (x, y + 0.075, z + L / 4), (x, y + 0.055, z + L / 2)]
        bases = [(x, y, z - L / 6), (x, y, z + L / 6)]
    else:
        horn = [(x - L / 2, y + 0.055, z), (x - L / 4, y + 0.075, z), (x + L / 4, y + 0.075, z), (x + L / 2, y + 0.055, z)]
        bases = [(x - L / 6, y, z), (x + L / 6, y, z)]
    tube(name + "_horn", horn, [0.012, 0.018, 0.018, 0.012], [M.steel], root, sides=8)
    for i, b_ in enumerate(bases):
        tube(f"{name}_foot{i}", [b_, (b_[0], b_[1] + 0.07, b_[2])], [0.022, 0.016], [M.steel], root, sides=8)


def build_rails(root):
    """stanchions + top rail + mid rail along the side decks to a bow pulpit; cockpit rail on the bulwark cap."""
    z0, z1 = Z_AFTWALL - 0.05, Z_STEM - 0.50
    zs = stations(z0, z1, 9)
    for side in (1, -1):
        top, mid = [], []
        for i, z in enumerate(zs):
            b = half_beam(z) - BWK * 0.5
            s = sheer(z) + 0.025
            d = deck_y(z)
            yt = d + 0.90
            x = side * max(b - 0.02, 0.12)
            tube(f"steel_stanchion_{side}_{i}", [(x, s, z), (x * 0.995, yt, z)], 0.014, [M.steel], root, sides=8)
            cyl(f"steel_stanchion_base_{side}_{i}", (x, s + 0.012, z), 0.03, 0.025, [M.steel], root, seg=12)
            top.append((x * 0.995, yt, z))
            mid.append((x, lerp(s, yt, 0.5), z))
        # pulpit: top rail curves round the bow
        zt = Z_STEM - 0.18
        tip_y = deck_y(zt) + 0.86
        top += [(side * 0.30, tip_y, zt - 0.10), (side * 0.0001, tip_y, zt)]
        tube(f"steel_toprail_{side}", top, 0.016, [M.steel], root, sides=10)
        tube(f"steel_midrail_{side}", mid, 0.010, [M.steel], root, sides=8)
        # pulpit legs
        tube(f"steel_pulpit_leg_{side}", [(side * 0.30, sheer(zt - 0.1) + 0.02, zt - 0.10), (side * 0.30, tip_y, zt - 0.10)], 0.016, [M.steel], root, sides=8)
    # cockpit rail on the bulwark cap (aft), 1.0 m above the sole
    for side in (1, -1):
        zs2 = stations(Z_COCK_AFT + 0.1, Z_AFTWALL - 0.05, 4)
        top = []
        for i, z in enumerate(zs2):
            x = side * (half_beam(z) - BWK * 0.5)
            s = sheer(z) + 0.025
            tube(f"steel_cockstanchion_{side}_{i}", [(x, s, z), (x, SOLE + 1.0, z)], 0.014, [M.steel], root, sides=8)
            top.append((x, SOLE + 1.0, z))
        tube(f"steel_cockrail_{side}", top, 0.016, [M.steel], root, sides=10)
    tube("steel_transom_rail", [(-(half_beam(Z_TR) - 0.06), SOLE + 1.0, Z_COCK_AFT + 0.1), (-(half_beam(Z_TR) - 0.12), SOLE + 1.0, Z_TR + 0.06),
                                (half_beam(Z_TR) - 0.12, SOLE + 1.0, Z_TR + 0.06), (half_beam(Z_TR) - 0.06, SOLE + 1.0, Z_COCK_AFT + 0.1)], 0.016, [M.steel], root, sides=10)
    for x in (-1.2, 0.0, 1.2):
        tube(f"steel_transom_stanchion_{x}", [(x, sheer(Z_TR) + 0.04, Z_TR + 0.06), (x, SOLE + 1.0, Z_TR + 0.06)], 0.014, [M.steel], root, sides=8)
    # cleats (stern quarters, midships, bow) + fairleads at the bow
    for side in (1, -1):
        cleat(f"steel_cleat_stern_{side}", (side * (half_beam(-6.5) - BWK * 0.5), sheer(-6.5) + 0.025, -6.5), "Z", root)
        cleat(f"steel_cleat_mid_{side}", (side * (half_beam(-0.5) - BWK * 0.5), sheer(-0.5) + 0.025, -0.5), "Z", root)
        zb = 5.45
        cleat(f"steel_cleat_bow_{side}", (side * (half_beam(zb) - 0.35), deck_y(zb) + 0.02, zb), "Z", root, L=0.30)
        zfl = 5.85
        xf = side * (half_beam(zfl) - BWK * 0.5)
        tube(f"steel_fairlead_{side}", [(xf - side * 0.03, sheer(zfl) + 0.02, zfl - 0.09), (xf, sheer(zfl) + 0.07, zfl - 0.04),
                                         (xf, sheer(zfl) + 0.07, zfl + 0.04), (xf - side * 0.03, sheer(zfl) + 0.02, zfl + 0.09)], 0.016, [M.steel], root, sides=8)


def build_foredeck(root):
    """anchor + bow roller + windlass + chain, hatches (hatch_pivot = the keyed one), sunpad, fenders."""
    zs_ = Z_STEM - 0.25
    dy = deck_y(zs_)
    # bow roller: stainless channel projecting past the stem
    rbox("steel_bowroller", (0, sheer(Z_STEM) + 0.02, Z_STEM + 0.05), (0.16, 0.08, 0.75), [M.steel], root, r=0.02)
    cyl("trim_roller", (0, sheer(Z_STEM) + 0.06, Z_STEM + 0.38), 0.045, 0.10, [M.rubber], root, axis="X", seg=14)
    # anchor (plough/delta) hanging in the roller
    ax, ay, az = 0.0, sheer(Z_STEM) - 0.05, Z_STEM + 0.42
    tube("steel_anchor_shank", [(ax, sheer(Z_STEM) + 0.08, Z_STEM - 0.05), (ax, ay + 0.06, az - 0.02), (ax, ay - 0.30, az + 0.08)], [0.02, 0.022, 0.026], [M.steel], root, sides=8)
    mesh("steel_anchor_fluke", [(ax, ay - 0.30, az + 0.10), (ax - 0.22, ay - 0.42, az - 0.02), (ax, ay - 0.62, az - 0.10), (ax + 0.22, ay - 0.42, az - 0.02),
                                (ax, ay - 0.40, az - 0.03)], [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)], [M.steel], root, smooth=False)
    # windlass: drum + cap, foot switch pads
    zw = Z_STEM - 1.05
    yw = deck_y(zw)
    rbox("gelcoat_windlass_base", (0, yw + 0.04, zw), (0.30, 0.08, 0.36), [M.gel], root, r=0.03)
    cyl("steel_windlass_drum", (0, yw + 0.16, zw), 0.10, 0.18, [M.steel], root, seg=20, r2=0.08)
    cyl("steel_windlass_cap", (0, yw + 0.27, zw), 0.06, 0.04, [M.steel], root, seg=16)
    for x in (-0.28, 0.28):
        cyl(f"trim_footswitch_{x}", (x, yw + 0.012, zw - 0.25), 0.045, 0.02, [M.rubber], root, seg=12)
    # chain from the windlass to the roller (links as a twisted tube)
    pts = [(0, yw + 0.14, zw + 0.08), (0, sheer(Z_STEM) + 0.05, Z_STEM - 0.25), (0, sheer(Z_STEM) + 0.07, Z_STEM + 0.1)]
    tube("steel_chain", pts, 0.018, [M.chain], root, sides=6)
    # hatches: forward (keyed) on a hinge at its aft edge; second smaller hatch further aft
    hz = 3.57
    hy = deck_y(hz + 0.35) + 0.035
    pivot = bpy.data.objects.new("hatch_pivot", None)
    bpy.context.scene.collection.objects.link(pivot)
    pivot.parent = root
    pivot.location = B((0, hy, hz))
    COLL.append(pivot)
    rbox("gelcoat_hatch_frame", (0, hy - 0.025, hz + 0.35), (0.80, 0.06, 0.80), [M.gel], root, r=0.03)
    # lid built at the origin, then parented to the pivot with a local offset (Blender -Y = spec +z)
    lid = rbox("glass_screen_hatch_lid", (0, 0.015, 0.35), (0.72, 0.03, 0.72), [M.screen], pivot, r=0.025)
    lidf = rbox("trim_hatch_lidframe", (0, 0.0, 0.35), (0.74, 0.02, 0.74), [M.trim], pivot, r=0.02)
    # fenders hanging over the side from the rails
    fenders = []
    for side in (1, -1):
        for z in (-1.2, 1.6):
            x = side * (half_beam(z) + 0.16)
            yb = sheer(z) - 0.95
            f = cyl(f"fender_{side}_{z}", (x, yb, z), 0.11, 0.62, [M.fender], root, seg=18)
            for dy_ in (0.33, -0.33):
                cyl(f"fender_cap_{side}_{z}_{dy_}", (x, yb + dy_, z), 0.07, 0.06, [M.fender], root, seg=14, r2=0.04 if dy_ > 0 else 0.07)
            tube(f"rope_fender_{side}_{z}", [(x, yb + 0.36, z), (x * 0.985, sheer(z) - 0.1, z), (side * (half_beam(z) - BWK * 0.5), sheer(z) + 0.45, z)], 0.007, [M.rope], root, sides=5)
            fenders.append(f)
    return pivot


def build_lights(root):
    lights = []

    def pl(name, p, col, w, r=0.05):
        ld = bpy.data.lights.new(name, "POINT")
        ld.color, ld.energy, ld.shadow_soft_size = col, w, r
        ob = bpy.data.objects.new(name, ld)
        bpy.context.scene.collection.objects.link(ob)
        ob.parent = root
        ob.location = B(p)
        COLL.append(ob)
        lights.append(ob)

    xn = cabin_hw(2.55, 2.25) + 0.09
    pl("nav_port_light", (-xn, 2.25, 2.58), (1, 0.16, 0.1), 3.0)
    pl("nav_stbd_light", (xn, 2.25, 2.58), (0.1, 1, 0.35), 3.0)
    pl("nav_mast_light", (0, 5.80, -1.95), (1, 1, 1), 3.0)
    pl("nav_stern_light", (0, sheer(Z_TR) - 0.15, Z_TR - 0.08), (1, 1, 1), 3.0)
    pl("cabin_light", (0, 2.6, -0.5), (1.0, 0.72, 0.4), 60.0, 0.3)
    # warm downlight in the flybridge overhang above the helm (spot, pointing down)
    ld = bpy.data.lights.new("cockpit_light", "SPOT")
    ld.color, ld.energy, ld.shadow_soft_size = (1.0, 0.78, 0.5), 18.0, 0.04
    ld.spot_size, ld.spot_blend = math.radians(95), 0.8
    ob = bpy.data.objects.new("cockpit_light", ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = root
    ob.location = B((0.0, ROOF - 0.02, -3.70))
    COLL.append(ob)
    lights.append(ob)
    return lights


def anchors(root):
    for nm, p in (("anchor_bow", (0, 1.9, 7.0)), ("anchor_cockpit", (0, 1.55, -5.6)), ("anchor_exhaust", (1.35, 0.55, -7.05)),
                  ("anchor_hatch", (0, 1.67, 3.92)), ("anchor_stern", (0, 1.4, -7.0))):
        e = bpy.data.objects.new(nm, None)
        bpy.context.scene.collection.objects.link(e)
        e.parent = root
        e.location = B(p)
        COLL.append(e)


# ---------------------------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------------------------
def build(root):
    """Build the yacht under `root`. Returns {"objs", "hatch", "marks"}."""
    COLL.clear()
    M.init()
    build_hull(root)
    build_decks(root)
    build_cabin(root)
    build_flybridge(root)
    build_cockpit(root)
    build_rails(root)
    hatch = build_foredeck(root)
    build_lights(root)
    anchors(root)
    objs = [o for o in COLL if o is not None]
    return {"objs": objs, "hatch": hatch, "marks": MARKS}


def _preview(out_dir, glb=None, res=(960, 540), samples=32, views=None, night=False, lights=1.0, suffix=""):
    """4-angle preview at night-ish studio light (no sea), Cycles CPU. night=True: moonlight only (for the
    glazing / interior close-ups); lights scales every yacht light + emissive like render_episode's yacht.lights."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import materials as yachtmats
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    root = bpy.data.objects.new("YachtRoot", None)
    sc.collection.objects.link(root)
    if glb:
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=glb)
        objs = [o for o in bpy.data.objects if o not in before]
        for o in objs:
            if o.parent is None:
                o.parent = root
    else:
        objs = build(root)["objs"]
    yachtmats.apply_yacht_materials(objs)
    # the cockpit props every episode shot carries (helm console against the aft wall, switch panel on it)
    import props as propkit
    for nm, mk in (("helm", "HELM_CONSOLE"), ("switches", "SWITCH_PANEL")):
        pr = propkit.BUILDERS[nm](nm)
        pr.parent = root
        x, y, z = MARKS[mk]["local"]
        pr.location = B((x, y, z))
        pr.rotation_euler = (0, 0, MARKS[mk]["rotY"])
    # yacht lights keyed to `lights` (same targets as render_episode.collect_light_targets)
    for ob in [o for o in bpy.data.objects if o.parent is not None]:
        if ob.type == "LIGHT" and not ob.name.startswith(("helm", "switches")):
            ob.data.energy *= lights
    for m in bpy.data.materials:
        if not m.use_nodes:
            continue
        for nd in m.node_tree.nodes:
            if nd.type == "BSDF_PRINCIPLED" and nd.inputs["Emission Strength"].default_value > 0:
                nd.inputs["Emission Strength"].default_value *= lights
            elif nd.type == "EMISSION":
                nd.inputs["Strength"].default_value *= lights
    # water plane at the waterline
    bpy.ops.mesh.primitive_plane_add(size=200, location=(0, 0, WL))
    w = bpy.context.object
    wm = bpy.data.materials.new("water")
    wm.use_nodes = True
    bw = wm.node_tree.nodes["Principled BSDF"]
    bw.inputs["Base Color"].default_value = (0.004, 0.012, 0.02, 1)
    bw.inputs["Roughness"].default_value = 0.08
    w.data.materials.append(wm)
    # light: moon key + cool fill + warm rim
    suns = (("key", (55, 0, 35), 3.0, (0.75, 0.82, 1.0)), ("rim", (60, 0, 200), 2.0, (1.0, 0.85, 0.7)))
    if night:  # a low moon behind the camera side + faint sky
        suns = (("moon", (62, 0, 150), 0.35, (0.70, 0.80, 1.0)),)
    for nm, rot, e, col in suns:
        ld = bpy.data.lights.new(nm, "SUN")
        ld.energy, ld.color, ld.angle = e, col, math.radians(3)
        ob = bpy.data.objects.new(nm, ld)
        sc.collection.objects.link(ob)
        ob.rotation_euler = tuple(math.radians(a) for a in rot)
    sc.world = bpy.data.worlds.new("w")
    sc.world.use_nodes = True
    sc.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.006, 0.010, 0.022, 1) if night else (0.02, 0.03, 0.06, 1)
    sc.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0
    sc.render.engine = "CYCLES"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.threads_mode = "FIXED"
    sc.render.threads = 2
    sc.view_settings.view_transform = "AgX"
    camd = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", camd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    VIEWS = {  # spec-space camera, look, lens
        "three_quarter_bow": ((9.5, 4.2, 11.0), (0, 1.8, 0.8), 35),
        "profile_port": ((-20.0, 2.6, 0.0), (0, 2.0, 0.0), 40),
        "stern_cockpit": ((2.6, 3.6, -11.5), (0, 2.0, -4.6), 30),
        "deck_close": ((-2.2, 2.9, -7.4), (0.3, 2.0, -4.2), 24),
        # glazing / door detail crops
        "salon_door": ((-1.6, 2.35, -6.0), (-0.1, 2.45, -3.33), 32),
        "side_windows": ((4.6, 2.7, -4.0), (1.5, 2.55, -0.9), 32),
    }
    os.makedirs(out_dir, exist_ok=True)
    for nm, (c, l, lens) in VIEWS.items():
        if views and nm not in views:
            continue
        cam.location = B(c)
        d = B(l) - B(c)
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        camd.lens = lens
        sc.render.filepath = os.path.join(out_dir, nm + suffix + ".png")
        bpy.ops.render.render(write_still=True)
        print("[yacht_v2] wrote", sc.render.filepath, flush=True)


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", required=True)
    ap.add_argument("--glb", default=None)
    ap.add_argument("--samples", type=int, default=32)
    ap.add_argument("--res", default="960x540")
    ap.add_argument("--views", default=None)
    ap.add_argument("--night", action="store_true")
    ap.add_argument("--lights", type=float, default=1.0)
    ap.add_argument("--suffix", default="")
    a = ap.parse_args(argv)
    _preview(a.preview, a.glb, tuple(int(v) for v in a.res.split("x")), a.samples, a.views.split(",") if a.views else None,
             a.night, a.lights, a.suffix)
