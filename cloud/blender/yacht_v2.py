"""
yacht_v2.py - the factory's own high-detail hero yacht, built procedurally in bpy (Blender 4.2). No external assets.

A ~14 m flybridge motor yacht that holds up in close shots: lofted hard-chine hull with a proper sheer, raked stem,
spray rails and flared topsides; swim platform + boarding ladder; aft cockpit with a U-shaped upholstered dinette
around a teak table; cabin with real glazing + a lit salon interior, sliding aft door, curved windscreen; flybridge with
helm console, bench and coaming; hardtop on a radar arch with radar dome and mast; stainless bow pulpit, rails and
stanchions; cleats, fairleads, anchor in a bow roller + windlass + chain; foredeck hatches; nav lights; fenders;
life ring; teak decks (cap rails, cockpit sole, side decks, foredeck).

  build(root) -> {"objs": [...], "hatch": hatch_pivot, "marks": MARKS}
      Everything is parented to `root` (render_episode's YachtRoot, Blender axes), with object transforms at identity
      so cloud/blender/materials.py's object-space shaders (teak planks fore-aft, hull waterline) line up.

Naming follows the yacht.glb contract so the existing pipeline keeps working unchanged:
  materials  gelcoat_hull (hull: boot stripe/antifouling + oceanfx hull foam finds object 'gelcoat_hull'),
             gelcoat_*, teak*, steel*, glass* (real tinted glass, never emissive - lesson L019, checked by
             audit_glazing at build), upholstery_*, fender*, nav_* (emissive; keyed by yacht.lights) -> restyled by
             materials.apply_yacht_materials(); interior_* / trim_* / lamp_* stay as authored (lamp_* fixtures emit and
             are keyed by yacht.lights)
  objects    hatch_pivot (foredeck hatch hinge; render_episode keys its X rotation from yacht.hatch),
             anchor_* empties (bow, cockpit, hatch, stern, exhaust) as in yacht.glb
  lights     point/spot lights under the root (keyed by yacht.lights like the GLB's): nav lights, cockpit downlight,
             salon downlights (cabin_downlight_*), cabin_light fill, cabin_lamp_light (table lamp)

Glazing + doors (lesson L019): every window is a real opening in the cabin skin (holed_sheet) with a black surround
band, thin anodised frame, EPDM gasket, rounded tinted pane, lined reveal and a lit salon behind it (build_interior:
teak sole, headliner with recessed downlights, sofa/table, galley, credenza + lamp, lower helm, blinds part-drawn on
some windows). Curved three-pane windscreen in black frit frames; aft sliding glass door (stainless jamb, framed leaf,
top/bottom tracks, threshold, pull handle + lock); hinged boarding gate in the port rail; flush flybridge hatch;
stainless-rimmed round hull portholes; smoked-acrylic foredeck hatch over a dark well.

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


def glassmat(name, tint):
    """glazing: dark authored base (GLB fallback), real look from materials.glass() via the 'tint' property"""
    m = mat(name, tuple(c * 0.08 for c in tint), 0.02)
    m["tint"] = list(tint)
    return m


def fabric(name, color, translucency):
    """diffuse fabric that glows through when lit from behind (blinds, lamp shades)"""
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = mat(name, color, 0.85)
    nt = m.node_tree
    b = nt.nodes.get("Principled BSDF")
    out = nt.nodes.get("Material Output")
    tr = nt.nodes.new("ShaderNodeBsdfTranslucent")
    tr.inputs["Color"].default_value = (*color, 1.0)
    mx = nt.nodes.new("ShaderNodeMixShader")
    mx.inputs[0].default_value = translucency
    nt.links.new(b.outputs[0], mx.inputs[1])
    nt.links.new(tr.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out.inputs["Surface"])
    # pleats: horizontal wave bump
    tc = nt.nodes.new("ShaderNodeTexCoord")
    wv = nt.nodes.new("ShaderNodeTexWave")
    wv.wave_type, wv.bands_direction = "BANDS", "Z"
    wv.inputs["Scale"].default_value = 10.0 if "blind" in name else 0.0
    nt.links.new(tc.outputs["Object"], wv.inputs["Vector"])
    bp = nt.nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = 0.35 if "blind" in name else 0.0
    nt.links.new(wv.outputs["Fac"], bp.inputs["Height"])
    nt.links.new(bp.outputs["Normal"], b.inputs["Normal"])
    nt.links.new(bp.outputs["Normal"], tr.inputs["Normal"])
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
        # glazing: real tinted glass, NEVER emissive (lesson L019); tint read by materials.glass()
        M.glass = glassmat("glass_cabin", (0.30, 0.25, 0.19))          # salon side + aft windows: dark bronze
        M.doorglass = glassmat("glass_cabin_door", (0.40, 0.37, 0.32))  # sliding door: lighter grey-bronze
        M.hullglass = glassmat("glass_cabin_hull", (0.24, 0.23, 0.22))  # hull portholes
        M.screen = glassmat("glass_screen", (0.34, 0.34, 0.32))         # windscreens: neutral grey
        M.hatchglass = glassmat("glass_screen_hatch", (0.16, 0.16, 0.16))  # smoked acrylic hatch lids
        M.frame = mat("trim_frame_black", (0.010, 0.010, 0.011), 0.32, coat=0.25)   # anodised window frames
        M.band = mat("trim_band_black", (0.006, 0.006, 0.007), 0.08, coat=1.0)      # black glazing surround
        M.gasket = mat("trim_gasket", (0.010, 0.010, 0.010), 0.8)                   # EPDM rubber
        # salon interior (unmatched by materials.RULES, so these stay as authored)
        M.lining = mat("interior_lining", (0.46, 0.41, 0.34), 0.75)
        M.headliner = mat("interior_headliner", (0.62, 0.58, 0.50), 0.6)
        M.wood = mat("interior_wood", (0.11, 0.06, 0.032), 0.4, coat=0.35)
        M.cabinet = mat("interior_cabinet", (0.55, 0.52, 0.46), 0.3, coat=0.5)
        M.counter = mat("interior_counter", (0.025, 0.025, 0.028), 0.18, coat=0.4)
        M.sofa = mat("interior_sofa", (0.40, 0.36, 0.29), 0.85)
        M.pillow = mat("interior_pillow", (0.035, 0.09, 0.10), 0.8)
        M.idark = mat("interior_dark", (0.008, 0.008, 0.009), 0.6)
        M.dash = mat("interior_dash", (0.014, 0.014, 0.016), 0.35, coat=0.4)
        M.blind = fabric("interior_blind", (0.55, 0.50, 0.42), 0.35)
        M.shade = fabric("interior_shade", (0.75, 0.68, 0.55), 0.6)
        M.curtain = mat("interior_porthole_curtain", (0.10, 0.09, 0.075), 0.9)
        # interior light fixtures: small emissive lenses ON the fixtures (keyed by yacht.lights), the light itself
        # comes from real lamps with inverse-square falloff (build_interior)
        M.lamp = mat("lamp_downlight", (0.8, 0.78, 0.72), 0.3, emit=(1.0, 0.80, 0.56), strength=14.0)
        M.display = mat("lamp_display", (0.02, 0.03, 0.04), 0.1, emit=(0.35, 0.62, 1.0), strength=1.2)
        M.led = mat("lamp_ledstrip", (0.8, 0.78, 0.72), 0.3, emit=(1.0, 0.76, 0.50), strength=5.0)
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
# glazing helpers: rounded panes, frames, gaskets and walls with real openings (lesson L019)
#   2D outlines live in a surface parameter plane (u, v); mapf(u, v, h) -> spec point, h = offset along the
#   surface's outward normal (glass sits at the opening, frames proud, linings/reveals inboard).
# ---------------------------------------------------------------------------------------------
def _area2(P):
    return sum(P[i][0] * P[(i + 1) % len(P)][1] - P[(i + 1) % len(P)][0] * P[i][1] for i in range(len(P)))


def ccw(P):
    return list(P) if _area2(P) > 0 else list(reversed(P))


def offset_poly(P, d):
    """convex CCW polygon offset outward by d (inward for d < 0); same vertex count"""
    n = len(P)
    lines = []
    for i in range(n):
        a, b = P[i], P[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        lines.append(((a[0] + dy / L * d, a[1] - dx / L * d), (dx / L, dy / L)))
    out = []
    for i in range(n):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        den = d1[0] * d2[1] - d1[1] * d2[0]
        t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / den
        out.append((p1[0] + t * d1[0], p1[1] + t * d1[1]))
    return out


def fillet(P, r, seg=6, edge_pts=0):
    """round every corner of a convex CCW polygon with radius r (seg+1 arc points per corner, edge_pts extra
    points on each straight run) - a fixed point count, so offset rings of one outline loft together"""
    n = len(P)
    arcs = []
    for i in range(n):
        p0, p1, p2 = Vector(P[i - 1]), Vector(P[i]), Vector(P[(i + 1) % n])
        a, b = (p1 - p0), (p2 - p1)
        la, lb = a.length, b.length
        a.normalize()
        b.normalize()
        phi = math.acos(max(-1.0, min(1.0, a.dot(b))))
        t = r * math.tan(phi / 2)
        tmax = 0.49 * min(la, lb)
        rr = r if t <= tmax else tmax / max(math.tan(phi / 2), 1e-6)
        t = min(t, tmax)
        t1 = p1 - a * t
        c = t1 + Vector((-a.y, a.x)) * rr
        a1 = math.atan2(t1.y - c.y, t1.x - c.x)
        arcs.append([(c.x + rr * math.cos(a1 + phi * k / seg), c.y + rr * math.sin(a1 + phi * k / seg)) for k in range(seg + 1)])
    out = []
    for i in range(n):
        out += arcs[i]
        e0, e1 = arcs[i][-1], arcs[(i + 1) % n][0]
        for k in range(1, edge_pts + 1):
            u = k / (edge_pts + 1)
            out.append((lerp(e0[0], e1[0], u), lerp(e0[1], e1[1], u)))
    return out


def ring2(base, d, r, seg=6, edge_pts=0):
    return fillet(offset_poly(base, d), max(r, 0.002), seg, edge_pts)


def pane(name, ring, mapf, h, mats, parent, facing, rings=1):
    """a glass (or blind) sheet filling a closed 2D outline; rings > 1 subdivides radially for curved surfaces"""
    cx = sum(p[0] for p in ring) / len(ring)
    cy = sum(p[1] for p in ring) / len(ring)
    n = len(ring)
    verts = [mapf(cx, cy, h)]
    for k in range(1, rings + 1):
        f = k / rings
        verts += [mapf(cx + (p[0] - cx) * f, cy + (p[1] - cy) * f, h) for p in ring]
    faces = [(0, 1 + j, 1 + (j + 1) % n) for j in range(n)]
    for k in range(rings - 1):
        a, b = 1 + k * n, 1 + (k + 1) * n
        faces += [(a + j, a + (j + 1) % n, b + (j + 1) % n, b + j) for j in range(n)]
    return mesh(name, verts, faces, mats, parent, smooth=rings > 1, sharp=None, facing=facing)


def frame_loft(name, base, profile, mapf, mats, parent, seg=6, edge_pts=0):
    """window/door frame: closed loft through offset rings; profile = [(d, h, r)] from the outer edge inward"""
    rings = [[mapf(u, v, h) for u, v in ring2(base, d, r, seg, edge_pts)] for d, h, r in profile]
    return loft(name, rings, mats, parent, closed=True, sharp=40)


def gasket(name, base, d, h, r, mapf, parent, seg=6, edge_pts=0, rad=0.0045):
    pts = [mapf(u, v, h) for u, v in ring2(base, d, r, seg, edge_pts)]
    return tube(name, pts, rad, [M.gasket], parent, sides=6, closed=True)


def holed_sheet(name, outer, holes, mapf, h, mats, parent, facing):
    """a planar sheet (wall, lining, surround) with real openings: outer outline + hole outlines in (u, v)"""
    from mathutils.geometry import tessellate_polygon
    loops = [list(outer)] + [list(hh) for hh in holes]
    pts = [p for lp in loops for p in lp]
    tris = tessellate_polygon([[Vector((u, v, 0.0)) for u, v in lp] for lp in loops])
    return mesh(name, [mapf(u, v, h) for u, v in pts], [tuple(t) for t in tris], mats, parent, smooth=False, facing=facing)


def reveal(name, ring, mapf, h0, h1, mats, parent):
    """the jamb of an opening: the hole outline swept from the outer skin (h0) to the lining (h1)"""
    return loft(name, [[mapf(u, v, h0) for u, v in ring], [mapf(u, v, h1) for u, v in ring]], mats, parent, closed=True, sharp=50)


def clip_below(P, vcut):
    """keep the part of polygon P (2D) with v >= vcut (a drawn blind hangs from the head of the opening)"""
    out = []
    n = len(P)
    for i in range(n):
        a, b = P[i], P[(i + 1) % n]
        ia, ib = a[1] >= vcut, b[1] >= vcut
        if ia:
            out.append(a)
        if ia != ib:
            t = (vcut - a[1]) / (b[1] - a[1])
            out.append((lerp(a[0], b[0], t), vcut))
    return out


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
    # hull portholes (cabins below): round tinted glass in a polished stainless rim + flange with clamp dogs,
    # a dark curtain behind the glass (the cabins are unlit at night)
    for side in (1, -1):
        for k, z in enumerate((-0.70, 0.10, 0.90)):
            porthole(f"{'s' if side > 0 else 'p'}_{k}", side, z, 1.17 + 0.01 * k, root)
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


def porthole(tag, side, z, y, root, R=0.085):
    """round porthole on the topsides at (z, y): flange + rolled rim (stainless), gasket, glass, curtain"""
    e = 0.01
    x = hull_x(z, y)
    P = Vector((side * x, y, z))
    Tz = Vector((side * (hull_x(z + e, y) - hull_x(z - e, y)) / (2 * e), 0.0, 1.0)).normalized()
    Ty = Vector((side * (hull_x(z, y + e) - hull_x(z, y - e)) / (2 * e), 1.0, 0.0)).normalized()
    N = Ty.cross(Tz).normalized()
    if N.x * side < 0:
        N = -N
    U = Tz
    V = N.cross(U).normalized()

    def at(r, a, h):
        q = P + (U * math.cos(a) + V * math.sin(a)) * r + N * h
        return (q.x, q.y, q.z)
    A = [2 * math.pi * i / 32 for i in range(32)]
    mesh(f"interior_porthole_curtain_{tag}", [at(0, 0, 0.003)] + [at(R + 0.004, a, 0.003) for a in A], [(0, 1 + i, 1 + (i + 1) % 32) for i in range(32)],
         [M.curtain], root, smooth=False, facing=tuple(N))
    loft(f"steel_porthole_flange_{tag}", [[at(R + 0.045, a, 0.002) for a in A], [at(R + 0.040, a, 0.010) for a in A], [at(R + 0.012, a, 0.016) for a in A],
                                          [at(R + 0.002, a, 0.012) for a in A], [at(R, a, 0.004) for a in A]], [M.steel], root, closed=True, sharp=None)
    tube(f"steel_porthole_rim_{tag}", [at(R + 0.020, a, 0.020) for a in A], 0.008, [M.steel], root, sides=8, closed=True)
    tube(f"trim_gasket_porthole_{tag}", [at(R - 0.002, a, 0.013) for a in A], 0.004, [M.gasket], root, sides=6, closed=True)
    mesh(f"glass_cabin_hull_{tag}", [at(0, 0, 0.011)] + [at(R + 0.002, a, 0.011) for a in A], [(0, 1 + i, 1 + (i + 1) % 32) for i in range(32)],
         [M.hullglass], root, smooth=False, facing=tuple(N))
    for i in range(3):   # clamp dogs
        a = math.pi / 2 + 2 * math.pi * i / 3
        q0, q1 = at(R + 0.032, a, 0.012), at(R + 0.032, a, 0.034)
        tube(f"steel_porthole_dog_{tag}_{i}", [q0, q1], 0.007, [M.steel], root, sides=8)


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


FLOOR = SOLE + 0.05   # salon sole = top of the door threshold
CEIL = 3.30           # salon headliner
LIN = 0.05            # side-wall build-up: outer skin -> interior lining
LIN_A = 0.06          # aft bulkhead build-up
NU = 13               # roof points across the cabin top
ROOF_U = [-1 + 2 * k / (NU - 1) for k in range(NU)]
CAB_ZS = stations(Z_AFTWALL, Z_CABFRONT, 30)
I_SPLIT, I_SCR1 = 22, 29          # side walls with openings: rings 0..22; windscreen opening: rings 22..29
Z_SPLIT = CAB_ZS[I_SPLIT]
# salon side windows (z, y): one raked band split into three rounded panes by black mullions
SIDE_GROUP = [(-3.00, 2.10), (1.25, 2.10), (1.10, 2.98), (-2.55, 2.98)]
SIDE_PANES = [[(-3.00, 2.10), (-1.335, 2.10), (-1.335, 2.98), (-2.55, 2.98)],
              [(-1.265, 2.10), (0.065, 2.10), (0.065, 2.98), (-1.265, 2.98)],
              [(0.135, 2.10), (1.25, 2.10), (1.10, 2.98), (0.135, 2.98)]]
SIDE_R = 0.07
# aft bulkhead openings (x, y): sliding door between the switch-panel pier and the helm console, two windows
DOOR = [(-0.62, FLOOR), (0.06, FLOOR), (0.06, 3.12), (-0.62, 3.12)]
DOOR_R = 0.03
AFT_WINS = {"p": ([(-1.30, 2.86), (-0.74, 2.86), (-0.74, 3.22), (-1.30, 3.22)], 0.05),
            "s": ([(0.16, 2.48), (1.28, 2.48), (1.28, 3.22), (0.16, 3.22)], 0.06)}
# drawn blinds: (window, fraction drawn from the head)
BLINDS = {("side", 1, 0): 0.58, ("side", -1, 1): 0.42, ("aft", "p"): 0.5}
# frame profile (d from the opening edge, h proud of the skin, corner radius = r + d): thin black anodised
WIN_PROFILE = [(0.016, 0.002), (0.013, 0.013), (-0.004, 0.015), (-0.012, 0.008)]


def crown(z):
    """windscreen / forward-roof camber"""
    return 0.075 * smoothstep(0.9, 1.7, z)


def roof_w(z):
    return cabin_hw(z, roof_y(z)) - 0.07


def roof_surf(u, z):
    return roof_y(z) + crown(z) * (1 - u * u)


def cabin_ring(z):
    """cabin section port base -> wall top -> rounded shoulder -> cambered roof -> starboard (21 points)"""
    base, r, W = deck_y(z), roof_y(z), roof_w(z)
    wt = r - 0.07
    hwt = cabin_hw(z, wt)
    half = [(cabin_hw(z, base), base, z), (hwt, wt, z)]
    for a in (30, 60):
        ar = math.radians(a)
        half.append((W + (hwt - W) * math.cos(ar), wt + 0.07 * math.sin(ar), z))
    roof = [(u * W, roof_surf(u, z), z) for u in ROOF_U]
    return [(-x, y, zz) for x, y, zz in half] + roof + list(reversed(half))


def map_side(side):
    return lambda z, y, h: (side * (cabin_hw(z, y) + h), y, z)


def map_aft(x, y, h):
    return (x, y, Z_AFTWALL - h)


W0_SCREEN = None


def map_screen(sc, z, h):
    u = sc / W0_SCREEN
    return (u * roof_w(z), roof_surf(u, z) + h, z)


def glazed_opening(name, base, r, mapf, facing, glass_mat, lin, root, band=True, blind=None):
    """one window: black surround band, thin frame, rubber gasket, tinted glass at the opening, lined reveal,
    optional blind drawn part-way from the head inside the glass. Returns the hole outline (for the wall)."""
    hole = ring2(base, 0.0, r)
    if band:
        holed_sheet(f"trim_band_{name}", ring2(base, 0.035, r + 0.035), [ring2(base, 0.010, r + 0.010)], mapf, 0.0015, [M.band], root, facing)
    frame_loft(f"trim_frame_{name}", base, [(d, h, r + d) for d, h in WIN_PROFILE], mapf, [M.frame], root)
    gasket(f"trim_gasket_{name}", base, -0.014, 0.004, r - 0.014, mapf, root)
    pane(f"{glass_mat.name}_{name}", hole, mapf, -0.004, [glass_mat], root, facing)
    reveal(f"interior_reveal_{name}", hole, mapf, 0.0, -lin, [M.lining], root)
    if blind:
        vs = [p[1] for p in base]
        vcut = max(vs) - blind * (max(vs) - min(vs))
        poly = clip_below(hole, vcut)
        pane(f"interior_blind_{name}", poly, mapf, -0.030, [M.blind], root, facing)
        us = [p[0] for p in poly if abs(p[1] - vcut) < 1e-6]
        if len(us) >= 2:
            tube(f"trim_blind_rail_{name}", [mapf(min(us) + 0.01, vcut, -0.030), mapf(max(us) - 0.01, vcut, -0.030)], 0.009, [M.frame], root, sides=8)
    return hole


def build_cabin(root):
    global W0_SCREEN
    zs = CAB_ZS
    rings = [cabin_ring(z) for z in zs]
    n = len(rings[0])
    verts = [p for rg in rings for p in rg]
    faces = []
    for i in range(len(rings) - 1):
        for j in range(n - 1):
            if i < I_SPLIT and j in (0, n - 2):
                continue            # side walls with window openings are built below
            if I_SPLIT <= i < I_SCR1 and 5 <= j <= 14:
                continue            # windscreen opening
            a, b = i * n, (i + 1) * n
            faces.append((a + j, a + j + 1, b + j + 1, b + j))
    cab = mesh("gelcoat_cabin", verts, faces, [M.gel], root, sharp=30)
    # front brow: the forward ring as one face
    mesh("gelcoat_cabin_brow", rings[-1], [tuple(range(n))], [M.gel], root, smooth=False, facing=(0, 0, 1))

    # ---- side walls: skin with real openings, black band + framed rounded panes, lining inside
    for side in (1, -1):
        s_ = "s" if side > 0 else "p"
        mp = map_side(side)
        outer = [(z, deck_y(z)) for z in zs[:I_SPLIT + 1]] + [(z, roof_y(z) - 0.07) for z in reversed(zs[:I_SPLIT + 1])]
        holes = []
        holed_sheet(f"trim_band_side_{s_}", ring2(ccw(SIDE_GROUP), 0.035, SIDE_R + 0.035),
                    [ring2(ccw(p), 0.010, SIDE_R + 0.010) for p in SIDE_PANES], mp, 0.0015, [M.band], root, (side, 0, 0))
        for k, pb in enumerate(SIDE_PANES):
            holes.append(glazed_opening(f"side_{s_}_{k}", ccw(pb), SIDE_R, mp, (side, 0, 0), M.glass, LIN, root,
                                        band=False, blind=BLINDS.get(("side", side, k))))
        holed_sheet(f"gelcoat_cabin_side_{s_}", outer, holes, mp, 0.0, [M.gel], root, (side, 0, 0))
        lin_outer = [(Z_AFTWALL + LIN_A, FLOOR - 0.02), (Z_SPLIT, FLOOR - 0.02), (Z_SPLIT, CEIL), (Z_AFTWALL + LIN_A, CEIL)]
        holed_sheet(f"interior_lining_side_{s_}", lin_outer, holes, mp, -LIN, [M.lining], root, (-side, 0, 0))
        # walnut sill under the windows, inside
        rbox(f"interior_wood_sill_{s_}", (side * (cabin_hw(-0.9, 2.06) - LIN - 0.03), 2.06, -0.9), (0.07, 0.03, 4.2), [M.wood], root, r=0.008)
        # nav sidelights on the cabin sides forward
        zn, yn = 2.55, 2.25
        xn = cabin_hw(zn, yn) + 0.03
        rbox(f"gelcoat_navbox_{s_}", (side * xn, yn, zn), (0.06, 0.12, 0.22), [M.gel], root, r=0.015)
        rbox(f"{'nav_stbd_green' if side > 0 else 'nav_port_red'}_lens", (side * (xn + 0.035), yn, zn + 0.03), (0.02, 0.07, 0.12),
             [M.green if side > 0 else M.red], root, r=0.008)

    # ---- curved windscreen: three cambered, raked panes in black frit frames over the roof opening
    W0_SCREEN = roof_w(2.2)
    zA, zB = zs[I_SPLIT], zs[I_SCR1]
    for k, (u0, u1) in enumerate(((-5 / 6, -1 / 3), (-1 / 3, 1 / 3), (1 / 3, 5 / 6))):
        base = [(u0 * W0_SCREEN, zA), (u1 * W0_SCREEN, zA), (u1 * W0_SCREEN, zB), (u0 * W0_SCREEN, zB)]
        frame_loft(f"trim_screen_frame_{k}", base, [(0.0, 0.002, 0.004), (-0.004, 0.016, 0.008), (-0.028, 0.018, 0.030), (-0.040, 0.009, 0.036)],
                   map_screen, [M.band], root, edge_pts=8)
        gasket(f"trim_gasket_screen_{k}", base, -0.041, 0.007, 0.036, map_screen, root, edge_pts=8)
        pane(f"glass_screen_{k}", ring2(base, -0.026, 0.030, 6, 8), map_screen, 0.006, [M.screen], root, (0, 1, 0.6), rings=6)
    # wiper parked along the bottom (forward) frame of the centre pane
    zw = zB - 0.07
    tube("trim_wiper_arm", [map_screen(sc, zw, 0.030) for sc in (0.30 * W0_SCREEN, 0.0, -0.28 * W0_SCREEN)], 0.007, [M.frame], root, sides=6)
    tube("trim_wiper_blade", [map_screen(sc, zw - 0.02, 0.022) for sc in (0.20 * W0_SCREEN, -0.29 * W0_SCREEN)], 0.006, [M.gasket], root, sides=6)
    cyl("steel_wiper_pivot", map_screen(0.30 * W0_SCREEN, zw, 0.015), 0.018, 0.03, [M.steel], root, seg=12)

    # ---- aft bulkhead: skin with the door and two windows, lining inside
    outer = [(x, y) for x, y, z in rings[0]]
    holes = [glazed_opening(f"aft_{s_}", ccw(b_), r_, map_aft, (0, 0, -1), M.glass, LIN_A, root, blind=BLINDS.get(("aft", s_)))
             for s_, (b_, r_) in AFT_WINS.items()]
    door_hole = ring2(ccw(DOOR), 0.0, DOOR_R)
    holes.append(door_hole)
    holed_sheet("gelcoat_aftwall", outer, holes, map_aft, 0.0, [M.gel], root, (0, 0, -1))
    hwl = cabin_hw(Z_AFTWALL, CEIL) - LIN
    holed_sheet("interior_lining_aft", [(-hwl, FLOOR - 0.02), (hwl, FLOOR - 0.02), (hwl, CEIL), (-hwl, CEIL)], holes, map_aft, -LIN_A,
                [M.lining], root, (0, 0, 1))
    build_salon_door(root, door_hole)
    # cabin-top grab rails
    for side in (1, -1):
        pts = [(side * (cabin_hw(z, ROOF) - 0.12), ROOF + 0.07, z) for z in stations(-2.6, 0.9, 10)]
        tube(f"steel_grabrail_{side}", pts, 0.013, [M.steel], root, sides=8)
        for z in (-2.6, -0.85, 0.9):
            cyl(f"steel_grabpost_{side}_{z}", (side * (cabin_hw(z, ROOF) - 0.12), ROOF + 0.035, z), 0.011, 0.07, [M.steel], root, seg=8)
    return cab


def build_salon_door(root, hole):
    """aft sliding glass door: stainless jamb frame + threshold, a framed glass leaf riding a bottom track under a top
    track (it slides to starboard, parking behind the helm console), vertical pull handle with lock, weather seals."""
    x0, x1 = DOOR[0][0], DOOR[1][0]
    y0, y1 = DOOR[0][1], DOOR[2][1]
    # fixed stainless jamb frame round the opening (its bottom run is the stainless threshold nosing)
    frame_loft("steel_door_jamb", ccw(DOOR), [(0.030, 0.002, DOOR_R + 0.03), (0.028, 0.022, DOOR_R + 0.028), (0.004, 0.024, DOOR_R + 0.004),
                                              (0.0, 0.004, DOOR_R)], map_aft, [M.steel], root)
    reveal("interior_reveal_door", hole, map_aft, 0.0, -LIN_A, [M.lining], root)
    # teak threshold through the bulkhead + rubber brush seals up both jambs
    rbox("teak_door_threshold", ((x0 + x1) / 2, FLOOR + 0.006, Z_AFTWALL + LIN_A / 2), (x1 - x0 - 0.01, 0.012, LIN_A + 0.01), [M.teak], root, r=0.004)
    for x in (x0 + 0.006, x1 - 0.006):
        rbox(f"trim_door_seal_{x:.2f}", (x, (y0 + y1) / 2, Z_AFTWALL - 0.026), (0.010, y1 - y0 - 0.06, 0.012), [M.gasket], root, r=0.003)
    # tracks: the leaf slides from the opening to x1 + 0.74 (behind the helm console, clear of it)
    xa, xb = x0 - 0.08, x1 + 0.80
    hz = 0.055                                    # leaf plane, aft of the bulkhead skin
    zl = Z_AFTWALL - hz
    rbox("trim_door_track_base", ((xa + xb) / 2, (SOLE + FLOOR) / 2 + 0.002, Z_AFTWALL - 0.045), (xb - xa, FLOOR - SOLE + 0.004, 0.09), [M.frame], root, r=0.006)
    for dz in (-0.014, 0.014):
        rbox(f"steel_door_track_bottom_{dz:+.3f}", ((xa + xb) / 2, FLOOR + 0.008, zl + dz), (xb - xa, 0.012, 0.006), [M.steel], root, r=0.002)
    rbox("steel_door_track_top", ((xa + xb) / 2, y1 + 0.075, Z_AFTWALL - 0.05), (xb - xa, 0.07, 0.085), [M.steel], root, r=0.01)
    rbox("trim_door_track_top_slot", ((xa + xb) / 2, y1 + 0.039, zl), (xb - xa - 0.01, 0.004, 0.022), [M.frame], root, r=0.0)
    for x in (xa + 0.04, xb - 0.04):
        cyl(f"steel_door_stop_{x:.2f}", (x, FLOOR + 0.03, zl), 0.012, 0.03, [M.gasket], root, seg=10)
    # the leaf: stainless stiles and rails (deeper bottom rail), glass in a rubber gasket
    lx0, lx1 = x0 - 0.035, x1 + 0.035
    ly0, ly1 = FLOOR + 0.016, y1 + 0.03
    st, rt, rb, dep = 0.05, 0.055, 0.10, 0.032
    rbox("steel_door_stile_lock", (lx0 + st / 2, (ly0 + ly1) / 2, zl), (st, ly1 - ly0, dep), [M.steel], root, r=0.006)
    rbox("steel_door_stile_meet", (lx1 - st / 2, (ly0 + ly1) / 2, zl), (st, ly1 - ly0, dep), [M.steel], root, r=0.006)
    rbox("steel_door_rail_top", ((lx0 + lx1) / 2, ly1 - rt / 2, zl), (lx1 - lx0 - 2 * st + 0.004, rt, dep), [M.steel], root, r=0.006)
    rbox("steel_door_rail_bottom", ((lx0 + lx1) / 2, ly0 + rb / 2, zl), (lx1 - lx0 - 2 * st + 0.004, rb, dep), [M.steel], root, r=0.006)
    leaf = ccw([(lx0 + st - 0.004, ly0 + rb - 0.004), (lx1 - st + 0.004, ly0 + rb - 0.004), (lx1 - st + 0.004, ly1 - rt + 0.004), (lx0 + st - 0.004, ly1 - rt + 0.004)])
    mp_leaf = lambda x, y, h: (x, y, zl - h)  # noqa: E731
    pane("glass_cabin_door", ring2(leaf, 0.0, 0.012), mp_leaf, 0.0, [M.doorglass], root, (0, 0, -1))
    for hh in (dep / 2 - 0.004, -dep / 2 + 0.004):
        gasket(f"trim_gasket_door_{'o' if hh > 0 else 'i'}", leaf, -0.004, hh, 0.010, mp_leaf, root, rad=0.005)
    # vertical pull handle on stand-offs (cockpit side), flush pull + lock cylinder
    hx = lx0 + st / 2
    zh = zl - dep / 2 - 0.055
    tube("steel_door_handle", [(hx, 2.02, zh), (hx, 2.62, zh)], 0.014, [M.steel], root, sides=12)
    for y in (2.08, 2.56):
        tube(f"steel_door_handle_post_{y}", [(hx, y, zl - dep / 2), (hx, y, zh)], 0.009, [M.steel], root, sides=8)
    cyl("steel_door_lock", (hx, 1.95, zl - dep / 2 - 0.004), 0.013, 0.012, [M.steel], root, axis="Z", seg=14)
    cyl("trim_door_lock_key", (hx, 1.95, zl - dep / 2 - 0.0105), 0.004, 0.002, [M.frame], root, axis="Z", seg=6)
    rbox("steel_door_pull_inner", (hx, 2.30, zl + dep / 2 + 0.006), (0.03, 0.22, 0.012), [M.steel], root, r=0.005)


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
    # flush access hatch in the flybridge sole (down to the salon): recessed gutter, non-skid lid in a stainless
    # rim with a gasket line, two hinges on the aft edge and a flush lift ring
    hx, hzc, hs = -0.62, -1.45, 0.62
    yt = FLY + 0.02
    hbase = ccw([(hx - hs / 2, hzc - hs / 2), (hx + hs / 2, hzc - hs / 2), (hx + hs / 2, hzc + hs / 2), (hx - hs / 2, hzc + hs / 2)])
    mp_f = lambda u, v, h: (u, yt + h, v)  # noqa: E731
    frame_loft("steel_fly_hatch_rim", hbase, [(0.035, 0.0, 0.085), (0.033, 0.006, 0.083), (0.012, 0.006, 0.062), (0.010, -0.010, 0.06)], mp_f, [M.steel], root)
    holed_sheet("trim_fly_hatch_gutter", ring2(hbase, 0.010, 0.06), [ring2(hbase, -0.004, 0.046)], mp_f, -0.004, [M.gasket], root, (0, 1, 0))
    pane("gelcoat_nonskid_fly_hatch_lid", ring2(hbase, -0.006, 0.044), mp_f, 0.002, [M.nonskid], root, (0, 1, 0))
    gasket("trim_gasket_fly_hatch", hbase, -0.004, 0.0, 0.046, mp_f, root, rad=0.003)
    for x in (hx - 0.18, hx + 0.18):
        rbox(f"steel_fly_hatch_hinge_{x:.2f}", (x, yt + 0.004, hzc - hs / 2 + 0.01), (0.08, 0.006, 0.05), [M.steel], root, r=0.002)
        cyl(f"steel_fly_hatch_knuckle_{x:.2f}", (x, yt + 0.006, hzc - hs / 2 - 0.004), 0.007, 0.08, [M.steel], root, axis="X", seg=10)
    cyl("trim_fly_hatch_cup", (hx, yt + 0.001, hzc + hs / 2 - 0.08), 0.045, 0.004, [M.gasket], root, seg=20)
    torus("steel_fly_hatch_ring", (hx, yt + 0.005, hzc + hs / 2 - 0.08), 0.032, 0.005, [M.steel], root, normal="Y", segs=20, sides=6)
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


GATE = 1   # port side-deck stanchion index the boarding gate hangs from (gate spans to GATE + 1)


def boarding_gate(root, hinge_top, latch_top, ys0, ys1):
    """hinged stainless gate in the side rail: heavier gate posts with base plates, two barrel hinges on the aft post,
    a tube frame (top, mid and bottom bars, latch-side upright, diagonal brace), a spring latch + keeper on the forward
    post and a rubber stop"""
    xh, yt, zh = hinge_top
    xl, _, zl = latch_top
    for tag, (x, z, ys) in (("hinge", (xh, zh, ys0)), ("latch", (xl, zl, ys1))):
        tube(f"steel_gatepost_{tag}", [(x, ys, z), (x, yt + 0.02, z)], 0.021, [M.steel], root, sides=12)
        cyl(f"steel_gatepost_cap_{tag}", (x, yt + 0.03, z), 0.024, 0.02, [M.steel], root, seg=14)
        rbox(f"steel_gatepost_plate_{tag}", (x, ys + 0.005, z), (0.07, 0.01, 0.10), [M.steel], root, r=0.004)
    gz0, gz1 = zh + 0.06, zl - 0.05           # gate frame clear of both posts
    gx = lambda z: lerp(xh, xl, (z - zh) / (zl - zh))  # noqa: E731
    yb = max(ys0, ys1) + 0.10
    ym = lerp(yb, yt, 0.5)
    tube("steel_gate_frame", [(gx(gz0), yb, gz0), (gx(gz1), yb, gz1), (gx(gz1), yt - 0.01, gz1), (gx(gz0), yt - 0.01, gz0), (gx(gz0), yb, gz0)],
         0.014, [M.steel], root, sides=10)
    tube("steel_gate_mid", [(gx(gz0), ym, gz0), (gx(gz1), ym, gz1)], 0.010, [M.steel], root, sides=8)
    tube("steel_gate_brace", [(gx(gz0), yb + 0.02, gz0 + 0.02), (gx(gz1), ym - 0.02, gz1 - 0.02)], 0.009, [M.steel], root, sides=8)
    for k, y in enumerate((yb + 0.08, yt - 0.10)):   # barrel hinges: knuckle on the post + strap to the frame
        cyl(f"steel_gate_hinge_{k}", (xh, y, zh), 0.029, 0.07, [M.steel], root, seg=14)
        tube(f"steel_gate_hinge_strap_{k}", [(xh, y, zh + 0.025), (gx(gz0), y, gz0)], 0.008, [M.steel], root, sides=8)
        cyl(f"steel_gate_hinge_pin_{k}", (xh, y + 0.042, zh), 0.008, 0.016, [M.steel], root, seg=8)
    yl = yt - 0.12                                # latch: keeper block on the post, spring bolt + thumb lever on the gate
    rbox("steel_gate_keeper", (xl, yl, zl - 0.03), (0.05, 0.07, 0.035), [M.steel], root, r=0.008)
    tube("steel_gate_bolt", [(gx(gz1), yl, gz1), (gx(gz1), yl, zl - 0.02)], 0.007, [M.steel], root, sides=8)
    rbox("steel_gate_latch_body", (gx(gz1), yl, gz1 - 0.01), (0.03, 0.06, 0.04), [M.steel], root, r=0.008)
    tube("steel_gate_latch_lever", [(gx(gz1), yl + 0.03, gz1 - 0.01), (gx(gz1), yl + 0.10, gz1 - 0.05)], 0.006, [M.steel], root, sides=6)
    cyl("trim_gate_stop", (xl, yb + 0.05, zl - 0.03), 0.014, 0.03, [M.rubber], root, axis="Z", seg=10)


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
        if side < 0:
            # boarding gate (port side deck) between stanchions GATE and GATE+1: the rails stop at the gate posts
            g = GATE
            tube(f"steel_toprail_{side}_aft", top[:g + 1], 0.016, [M.steel], root, sides=10)
            tube(f"steel_toprail_{side}", top[g + 1:], 0.016, [M.steel], root, sides=10)
            tube(f"steel_midrail_{side}_aft", mid[:g + 1], 0.010, [M.steel], root, sides=8)
            tube(f"steel_midrail_{side}", mid[g + 1:], 0.010, [M.steel], root, sides=8)
            boarding_gate(root, top[g], top[g + 1], sheer(zs[g]) + 0.025, sheer(zs[g + 1]) + 0.025)
        else:
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
    # the opening under the acrylic: a dark well (cabin below) inside an anodised coaming with a gasket
    rbox("interior_dark_hatch_well", (0, hy + 0.006, hz + 0.35), (0.62, 0.004, 0.62), [M.idark], root, r=0.0)
    hb = ccw([(-0.31, hz + 0.04), (0.31, hz + 0.04), (0.31, hz + 0.66), (-0.31, hz + 0.66)])
    mp_h = lambda u, v, h: (u, hy + 0.006 + h, v)  # noqa: E731
    frame_loft("trim_frame_hatch_coaming", hb, [(0.05, 0.0, 0.08), (0.05, 0.022, 0.08), (0.0, 0.022, 0.03), (0.0, 0.0, 0.03)], mp_h, [M.frame], root)
    # lid built at the origin, then parented to the pivot with a local offset (Blender -Y = spec +z):
    # smoked acrylic in a rounded anodised frame, gasket underneath, two stainless hinges at the aft edge
    lb = ccw([(-0.36, -0.01 + 0.0), (0.36, -0.01), (0.36, 0.71), (-0.36, 0.71)])
    mp_l = lambda u, v, h: (u, 0.020 + h, v)  # noqa: E731
    pane("glass_screen_hatch_lid", ring2(lb, -0.035, 0.05), mp_l, 0.004, [M.hatchglass], pivot, (0, 1, 0))
    lidf = frame_loft("trim_hatch_lidframe", lb, [(0.0, -0.014, 0.08), (0.0, 0.010, 0.08), (-0.005, 0.016, 0.075), (-0.040, 0.012, 0.045), (-0.040, -0.004, 0.045)],
                      mp_l, [M.frame], pivot)
    gasket("trim_gasket_hatch_lid", lb, -0.02, -0.016, 0.06, mp_l, pivot, rad=0.006)
    for x in (-0.22, 0.22):
        cyl(f"steel_hatch_hinge_{x}", (x, 0.012, -0.012), 0.014, 0.09, [M.steel], pivot, axis="X", seg=12)
        rbox(f"steel_hatch_hinge_leaf_{x}", (x, 0.026, 0.03), (0.07, 0.006, 0.07), [M.steel], pivot, r=0.003)
    rbox("steel_hatch_handle", (0, 0.036, 0.66), (0.12, 0.012, 0.025), [M.steel], pivot, r=0.006)
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


def lamp(name, kind, p, col, w, r, root, spot=None):
    """a real light (inverse-square falloff) under the root, keyed by yacht.lights like every yacht light"""
    ld = bpy.data.lights.new(name, kind)
    ld.color, ld.energy, ld.shadow_soft_size = col, w, r
    if spot:
        ld.spot_size, ld.spot_blend = math.radians(spot[0]), spot[1]
    ob = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = root
    ob.location = B(p)
    COLL.append(ob)
    return ob


WARM = (1.0, 0.76, 0.50)   # ~2700 K


def build_interior(root):
    """the salon behind the glass, so lit windows read as a lit room (L019): teak sole, cream headliner with
    recessed downlights (spot lights + small lens fixtures), port L-sofa + table, starboard galley with an LED
    toe-kick, credenza with a table lamp, lower helm (dash, two seats, companionway) under the windscreen.
    Every lamp and fixture is keyed by yacht.lights, so the salon goes dark when the engine dies."""
    z0 = Z_AFTWALL + LIN_A

    def hwi(z, y=2.0):
        return cabin_hw(z, y) - LIN

    # sole + headliner
    zs = stations(z0, 2.31, 12)
    loft("teak_salon_floor", [[(-hwi(z, FLOOR), FLOOR, z), (hwi(z, FLOOR), FLOOR, z)] for z in zs], [M.teak], root, sharp=None, facing=(0, 1, 0))
    loft("interior_headliner", [[(-hwi(z, CEIL), CEIL, z), (hwi(z, CEIL), CEIL, z)] for z in stations(z0, Z_SPLIT, 8)], [M.headliner], root,
         sharp=None, facing=(0, -1, 0))
    for side in (1, -1):
        zf = stations(Z_SPLIT, 2.31, 6)
        loft(f"interior_lining_fwd_{side}", [[(side * hwi(z, FLOOR - 0.02), FLOOR - 0.02, z), (side * hwi(z, 2.35), 2.35, z)] for z in zf], [M.lining], root,
             sharp=None, facing=(-side, 0, 0))
        # cove lip where the headliner meets the lining (walnut)
        rbox(f"interior_wood_cove_{side}", (side * (hwi(-0.9, CEIL) - 0.03), CEIL - 0.03, (z0 + Z_SPLIT) / 2), (0.06, 0.06, Z_SPLIT - z0), [M.wood], root, r=0.01)
    # recessed downlights: stainless bezel + warm lens + a real spot pointing down
    for i, (x, z) in enumerate(((-0.72, -2.55), (0.72, -2.55), (-0.72, -1.20), (0.72, -1.20), (-0.72, 0.20), (0.72, 0.20), (0.0, 0.95))):
        cyl(f"steel_downlight_bezel_{i}", (x, CEIL - 0.005, z), 0.045, 0.01, [M.steel], root, seg=20)
        cyl(f"lamp_downlight_{i}", (x, CEIL - 0.011, z), 0.031, 0.004, [M.lamp], root, seg=16)
        lamp(f"cabin_downlight_{i}", "SPOT", (x, CEIL - 0.03, z), WARM, 12.0, 0.025, root, spot=(120, 0.75))
    lamp("cabin_light", "POINT", (0.0, 2.95, -1.0), (1.0, 0.72, 0.42), 14.0, 0.3, root)   # soft bounce fill

    # port L-sofa + table
    F = FLOOR
    rbox("interior_wood_sofa_plinth", (-1.21, F + 0.17, -1.10), (0.58, 0.34, 3.20), [M.wood], root, r=0.02)
    rbox("interior_sofa_seat", (-1.20, F + 0.40, -1.10), (0.60, 0.13, 3.18), [M.sofa], root, r=0.05)
    rbox("interior_sofa_back", (-1.43, F + 0.69, -1.10), (0.15, 0.47, 3.18), [M.sofa], root, r=0.06)
    rbox("interior_wood_sofa_return", (-0.58, F + 0.17, 0.27), (0.68, 0.34, 0.52), [M.wood], root, r=0.02)
    rbox("interior_sofa_return_seat", (-0.58, F + 0.40, 0.25), (0.70, 0.13, 0.56), [M.sofa], root, r=0.05)
    rbox("interior_sofa_return_back", (-0.58, F + 0.69, 0.48), (0.70, 0.47, 0.15), [M.sofa], root, r=0.06)
    for k, (x, z) in enumerate(((-1.33, -2.35), (-1.33, -0.55), (-0.85, 0.36))):
        rbox(f"interior_pillow_{k}", (x, F + 0.63, z), (0.13 if k < 2 else 0.34, 0.34, 0.34 if k < 2 else 0.13), [M.pillow], root, r=0.06)
    rbox("interior_wood_table", (-0.52, F + 0.72, -1.10), (0.62, 0.035, 1.30), [M.wood], root, r=0.03)
    cyl("steel_salon_table_post", (-0.52, F + 0.36, -1.10), 0.045, 0.70, [M.steel], root, seg=14)
    cyl("steel_salon_table_foot", (-0.52, F + 0.01, -1.10), 0.22, 0.02, [M.steel], root, seg=20)

    # starboard galley (aft, along the windows)
    gx = hwi(-2.4) - 0.28
    rbox("interior_cabinet_galley", (gx, F + 0.44, -2.42), (0.56, 0.86, 1.62), [M.cabinet], root, r=0.012)
    rbox("interior_counter_galley", (gx - 0.02, F + 0.895, -2.42), (0.62, 0.04, 1.66), [M.counter], root, r=0.008)
    rbox("interior_dark_toekick", (gx - 0.275, F + 0.04, -2.42), (0.02, 0.08, 1.58), [M.idark], root, r=0.0)
    rbox("lamp_ledstrip_toekick", (gx - 0.29, F + 0.083, -2.42), (0.008, 0.006, 1.56), [M.led], root, r=0.0)
    rbox("lamp_ledstrip_counter", (gx - 0.315, F + 0.868, -2.42), (0.008, 0.006, 1.58), [M.led], root, r=0.0)
    for z in (-2.82, -2.02):
        rbox(f"interior_dark_galley_seam_{z}", (gx - 0.281, F + 0.46, z), (0.004, 0.78, 0.006), [M.idark], root, r=0.0)
    for z in (-3.0, -2.6, -2.2, -1.82):
        rbox(f"steel_galley_pull_{z}", (gx - 0.29, F + 0.80, z), (0.012, 0.012, 0.16), [M.steel], root, r=0.004)
    rbox("steel_galley_sink", (gx, F + 0.917, -2.0), (0.34, 0.006, 0.40), [M.steel], root, r=0.02)
    tube("steel_galley_tap", [(gx + 0.20, F + 0.915, -2.0), (gx + 0.20, F + 1.22, -2.0), (gx + 0.12, F + 1.25, -2.0), (gx + 0.06, F + 1.17, -2.0)], 0.012, [M.steel], root, sides=10)
    rbox("interior_dark_coffee", (gx + 0.06, F + 1.06, -2.95), (0.24, 0.28, 0.22), [M.idark], root, r=0.02)
    for k, z in enumerate((-2.75, -2.15)):
        cyl(f"interior_sofa_stool_{k}", (gx - 0.62, F + 0.70, z), 0.17, 0.06, [M.sofa], root, seg=20)
        cyl(f"steel_stool_post_{k}", (gx - 0.62, F + 0.35, z), 0.022, 0.66, [M.steel], root, seg=10)
        cyl(f"steel_stool_foot_{k}", (gx - 0.62, F + 0.01, z), 0.18, 0.02, [M.steel], root, seg=18)

    # starboard credenza + table lamp (a real practical)
    cx = hwi(-0.2) - 0.22
    rbox("interior_wood_credenza", (cx, F + 0.30, -0.25), (0.42, 0.60, 1.70), [M.wood], root, r=0.015)
    cyl("steel_lamp_base", (cx, F + 0.62, 0.30), 0.06, 0.03, [M.steel], root, seg=16)
    tube("steel_lamp_stem", [(cx, F + 0.62, 0.30), (cx, F + 0.95, 0.30)], 0.008, [M.steel], root, sides=8)
    cyl("interior_shade_lamp", (cx, F + 1.02, 0.30), 0.16, 0.22, [M.shade], root, seg=24, r2=0.11)
    lamp("cabin_lamp_light", "POINT", (cx, F + 1.00, 0.30), WARM, 6.0, 0.05, root)

    # lower helm under the windscreen: dash following the roof, two helm seats, wheel, companionway down
    rows = []
    for z in stations(2.30, 2.95, 6):
        w_, top = hwi(z) - 0.02, roof_y(z) - 0.10
        rows.append([(-w_, F, z), (-w_, top, z), (w_, top, z), (w_, F, z)])
    loft("interior_dash", rows, [M.dash], root, cap0=True, sharp=30)
    for sx in (-0.48, 0.48):
        rbox(f"lamp_display_{sx}", (sx, roof_y(2.36) - 0.13, 2.33), (0.34, 0.16, 0.01), [M.display], root, r=0.004, rot=("X", -35))
    torus("steel_lower_wheel", (0.48, roof_y(2.36) - 0.28, 2.24), 0.17, 0.012, [M.steel], root, normal="Z", segs=24, sides=6)
    for sx in (-0.50, 0.50):
        rbox(f"interior_sofa_helmseat_{sx}", (sx, F + 0.62, 1.72), (0.50, 0.14, 0.50), [M.sofa], root, r=0.05)
        rbox(f"interior_sofa_helmback_{sx}", (sx, F + 0.98, 1.48), (0.50, 0.58, 0.13), [M.sofa], root, r=0.05)
        cyl(f"steel_helmseat_post_{sx}", (sx, F + 0.28, 1.72), 0.05, 0.56, [M.steel], root, seg=12)
    rbox("interior_dark_companionway", (0.0, F + 0.003, 2.05), (0.62, 0.006, 0.40), [M.idark], root, r=0.0)


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
    build_interior(root)
    build_flybridge(root)
    build_cockpit(root)
    build_rails(root)
    hatch = build_foredeck(root)
    build_lights(root)
    anchors(root)
    objs = [o for o in COLL if o is not None]
    bad = audit_glazing(objs)
    if bad:
        raise ValueError(f"L019: emissive material on glass objects {bad[:6]} - glazing must be real glass lit from inside")
    return {"objs": objs, "hatch": hatch, "marks": MARKS}


def audit_glazing(objs):
    """lesson L019 check: names of glass-named meshes whose material emits (they must not)"""
    bad = []
    for ob in objs:
        if ob.type != "MESH" or not ob.name.startswith("glass"):
            continue
        for sl in ob.material_slots:
            m = sl.material
            if m is None or not m.use_nodes:
                continue
            for nd in m.node_tree.nodes:
                if (nd.type == "BSDF_PRINCIPLED" and nd.inputs["Emission Strength"].default_value > 0
                        and any(c > 0 for c in nd.inputs["Emission Color"].default_value[:3])) or nd.type == "EMISSION":
                    bad.append(ob.name)
    return bad


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
        ld.energy, ld.color, ld.angle = e, col, math.radians(0.6 if night else 3)
        ob = bpy.data.objects.new(nm, ld)
        sc.collection.objects.link(ob)
        ob.rotation_euler = tuple(math.radians(a) for a in rot)
    sc.world = bpy.data.worlds.new("w")
    sc.world.use_nodes = True
    sc.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.006, 0.010, 0.022, 1) if night else (0.02, 0.03, 0.06, 1)
    sc.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0
    if night:  # moonlit sky gradient (brighter at the horizon) so the glazing has something to reflect
        wn = sc.world.node_tree
        tc = wn.nodes.new("ShaderNodeTexCoord")
        sp = wn.nodes.new("ShaderNodeSeparateXYZ")
        mr = wn.nodes.new("ShaderNodeMapRange")
        mr.inputs["From Min"].default_value, mr.inputs["From Max"].default_value = -0.05, 0.55
        mx = wn.nodes.new("ShaderNodeMix")
        mx.data_type = "RGBA"
        mx.inputs[6].default_value = (0.030, 0.045, 0.080, 1)
        mx.inputs[7].default_value = (0.004, 0.007, 0.016, 1)
        wn.links.new(tc.outputs["Generated"], sp.inputs[0])
        wn.links.new(sp.outputs["Z"], mr.inputs["Value"])
        wn.links.new(mr.outputs["Result"], mx.inputs[0])
        wn.links.new(mx.outputs[2], wn.nodes["Background"].inputs["Color"])
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
        "gate_port": ((-3.7, 2.75, -3.1), (-2.05, 2.25, -1.75), 32),
        "fly_hatch": ((0.9, 4.22, -2.95), (-0.62, 3.55, -1.45), 30),
        "fore_hatch": ((2.4, 3.7, 1.9), (0.0, 2.0, 3.92), 35),
        "portholes": ((5.2, 1.5, 2.2), (2.1, 1.25, 0.1), 40),
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
