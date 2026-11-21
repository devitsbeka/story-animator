"""
PROPS_VEHICLES: big code-built (bpy) hero props and sets for the Primrose 1981 sequence, reusable.

  primrose      1980s bulk carrier 'PRIMROSE' (~150 m): rusty dark hull, red boot-top, white aft
                superstructure with a hollow bridge (glass with rain), cranes over 6 hatches, portholes,
                windows, deck floods, nav lights, hull name text.
  helicopter    1980s rescue helicopter (generic Sea King-like, unbranded): spinning main + tail rotor
                (keyed rotation, motion-blur friendly, optional translucent rotor disc), blinking beacon,
                nose searchlight, starboard door with a winch cable and a hanging survivor.
  coastguard    generic patrol vessel (~48 m): white hull, bow stripes, 'COAST GUARD' text, searchlight
                with a fake volumetric beam, radar.
  cargo_hold    interior set: steel walls, ribs, hopper slopes, ladder, cargo sacks, hatch slit of daylight,
                a swinging lamp, stylized low-detail crew silhouettes.
  beach_torches carried torches (flames + flicker lights, slow bob). Never people.
  rotor_wash    spinning spray disc for under the helicopter.

Builders: BUILDERS[name](root_name, **opts) -> root empty. Units metres, Blender Z up, the bow / nose
points along Blender -Y (= spec +z), so rotY in the spec behaves like the yacht heading.

Animation is data on the objects (custom properties) and is keyed by post_place(root, p, f0, f1, fps),
which render_episode.build_props calls after the prop is placed:
  spin_rps + spin_axis      constant rotation (rotors, radar)
  swing_deg + swing_period  pendulum (hanging lamp)
  blink_period              anti-collision beacon (light on 3 frames per period)
  flicker                   flames: light energy + flame scale
  bob                       slow vertical drift (carried torches)
  winch_cable / winch_load  cable length from p['winch'] keys [[f, metres], ...]
  search                    yaw (deg) from p['search'] keys
and per-prop spec fields: p['path'] [[f, [x, y, z]], ...] world (spec) positions, p['yaw'] [[f, deg]],
p['tilt'] [pitch_deg, roll_deg] (aground list), p['rock'] {'amp': deg, 'period': s}.
"""
import math
import random

import bpy
import bmesh
from mathutils import Matrix, Vector, Quaternion


# ======================================================================================= materials
def _principled(m):
    return m.node_tree.nodes["Principled BSDF"]


def mat(name, color, rough=0.5, metal=0.0, emit=None, strength=0.0, alpha=None):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = _principled(m)
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = strength
    if alpha is not None:
        b.inputs["Alpha"].default_value = alpha
    return m


def paint(name, base, rust=(0.23, 0.085, 0.03), amount=0.35, streak=True, rough=0.72, metal=0.15, scale=0.35):
    """Weathered paint: base colour broken by rust patches and (optionally) vertical rust streaks."""
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    N, Lk = nt.nodes, nt.links
    b = _principled(m)
    tc = N.new("ShaderNodeTexCoord")
    # vertical streaks: noise stretched along Z
    mp = N.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (scale * 4, scale * 4, scale * 0.25) if streak else (scale, scale, scale)
    Lk.new(tc.outputs["Object"], mp.inputs["Vector"])
    n1 = N.new("ShaderNodeTexNoise")
    n1.inputs["Scale"].default_value = 3.0
    n1.inputs["Detail"].default_value = 6.0
    Lk.new(mp.outputs["Vector"], n1.inputs["Vector"])
    # big patches
    n2 = N.new("ShaderNodeTexNoise")
    n2.inputs["Scale"].default_value = scale * 0.6
    n2.inputs["Detail"].default_value = 3.0
    Lk.new(tc.outputs["Object"], n2.inputs["Vector"])
    mul = N.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    Lk.new(n1.outputs["Fac"], mul.inputs[0])
    Lk.new(n2.outputs["Fac"], mul.inputs[1])
    rr = N.new("ShaderNodeMapRange")
    rr.inputs["From Min"].default_value = 0.34 - 0.12 * amount
    rr.inputs["From Max"].default_value = 0.42 - 0.12 * amount
    Lk.new(mul.outputs[0], rr.inputs["Value"])
    mix = N.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    Lk.new(rr.outputs[0], mix.inputs[0])
    mix.inputs[6].default_value = (*base, 1)
    mix.inputs[7].default_value = (*rust, 1)
    Lk.new(mix.outputs[2], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    bump = N.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.15
    Lk.new(n1.outputs["Fac"], bump.inputs["Height"])
    Lk.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


def ghost(name, color, alpha=0.2, strength=0.0):
    """Translucent sheet (rotor disc, light beam, spray): Transparent mixed with Emission or diffuse."""
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    N, Lk = nt.nodes, nt.links
    N.clear()
    out = N.new("ShaderNodeOutputMaterial")
    tr = N.new("ShaderNodeBsdfTransparent")
    if strength > 0:
        sh = N.new("ShaderNodeEmission")
        sh.inputs["Color"].default_value = (*color, 1)
        sh.inputs["Strength"].default_value = strength
    else:
        sh = N.new("ShaderNodeBsdfDiffuse")
        sh.inputs["Color"].default_value = (*color, 1)
    mx = N.new("ShaderNodeMixShader")
    mx.inputs[0].default_value = alpha
    Lk.new(tr.outputs[0], mx.inputs[1])
    Lk.new(sh.outputs[0], mx.inputs[2])
    Lk.new(mx.outputs[0], out.inputs["Surface"])
    try:
        m.blend_method = "BLEND"
    except (AttributeError, TypeError):
        pass
    return m


def spray(name="rotor_spray"):
    """Noisy translucent white for the rotor wash disc."""
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    N, Lk = m.node_tree.nodes, m.node_tree.links
    N.clear()
    out = N.new("ShaderNodeOutputMaterial")
    tc = N.new("ShaderNodeTexCoord")
    nz = N.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 0.35
    nz.inputs["Detail"].default_value = 8.0
    Lk.new(tc.outputs["Object"], nz.inputs["Vector"])
    gr = N.new("ShaderNodeTexGradient")
    gr.gradient_type = "SPHERICAL"
    mpg = N.new("ShaderNodeMapping")
    mpg.inputs["Scale"].default_value = (1 / 15, 1 / 15, 1 / 15)
    Lk.new(tc.outputs["Object"], mpg.inputs["Vector"])
    Lk.new(mpg.outputs["Vector"], gr.inputs["Vector"])
    rr = N.new("ShaderNodeMapRange")
    rr.inputs["From Min"].default_value = 0.5
    rr.inputs["From Max"].default_value = 0.75
    Lk.new(nz.outputs["Fac"], rr.inputs["Value"])
    mul = N.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    Lk.new(rr.outputs[0], mul.inputs[0])
    Lk.new(gr.outputs["Fac"], mul.inputs[1])
    mul2 = N.new("ShaderNodeMath")
    mul2.operation = "MULTIPLY"
    mul2.inputs[1].default_value = 0.7
    Lk.new(mul.outputs[0], mul2.inputs[0])
    tr = N.new("ShaderNodeBsdfTransparent")
    df = N.new("ShaderNodeBsdfDiffuse")
    df.inputs["Color"].default_value = (0.85, 0.88, 0.9, 1)
    mx = N.new("ShaderNodeMixShader")
    Lk.new(mul2.outputs[0], mx.inputs[0])
    Lk.new(tr.outputs[0], mx.inputs[1])
    Lk.new(df.outputs[0], mx.inputs[2])
    Lk.new(mx.outputs[0], out.inputs["Surface"])
    return m


def glass_rain(name="bridge_glass_rain"):
    """Window glass with static droplets and running rivulets (mapping keyed by the storm module if wanted)."""
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    N, Lk = m.node_tree.nodes, m.node_tree.links
    N.clear()
    out = N.new("ShaderNodeOutputMaterial")
    tc = N.new("ShaderNodeTexCoord")
    # droplets
    vo = N.new("ShaderNodeTexVoronoi")
    vo.inputs["Scale"].default_value = 28.0
    Lk.new(tc.outputs["Object"], vo.inputs["Vector"])
    dr = N.new("ShaderNodeMapRange")
    dr.inputs["From Min"].default_value = 0.0
    dr.inputs["From Max"].default_value = 0.28
    dr.inputs["To Min"].default_value = 1.0
    dr.inputs["To Max"].default_value = 0.0
    Lk.new(vo.outputs["Distance"], dr.inputs["Value"])
    # rivulets: voronoi stretched along Z, scrolled by a keyable mapping (node name 'rivulet_map')
    mp = N.new("ShaderNodeMapping")
    mp.name = "rivulet_map"
    mp.inputs["Scale"].default_value = (9.0, 9.0, 0.8)
    Lk.new(tc.outputs["Object"], mp.inputs["Vector"])
    vr = N.new("ShaderNodeTexVoronoi")
    vr.inputs["Scale"].default_value = 2.0
    Lk.new(mp.outputs["Vector"], vr.inputs["Vector"])
    rv = N.new("ShaderNodeMapRange")
    rv.inputs["From Min"].default_value = 0.0
    rv.inputs["From Max"].default_value = 0.08
    rv.inputs["To Min"].default_value = 1.0
    rv.inputs["To Max"].default_value = 0.0
    Lk.new(vr.outputs["Distance"], rv.inputs["Value"])
    h = N.new("ShaderNodeMath")
    h.operation = "MAXIMUM"
    Lk.new(dr.outputs[0], h.inputs[0])
    Lk.new(rv.outputs[0], h.inputs[1])
    bump = N.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.6
    bump.inputs["Distance"].default_value = 0.02
    Lk.new(h.outputs[0], bump.inputs["Height"])
    gl = N.new("ShaderNodeBsdfGlass")
    gl.inputs["Color"].default_value = (0.82, 0.86, 0.88, 1)
    gl.inputs["Roughness"].default_value = 0.04
    gl.inputs["IOR"].default_value = 1.2
    Lk.new(bump.outputs["Normal"], gl.inputs["Normal"])
    # mostly see-through: thin pane, keep the straight-through ray (no refraction offset in a 2 cm pane)
    tr = N.new("ShaderNodeBsdfTransparent")
    tr.inputs["Color"].default_value = (0.86, 0.9, 0.92, 1)
    mx = N.new("ShaderNodeMixShader")
    mx.inputs[0].default_value = 0.35
    Lk.new(tr.outputs[0], mx.inputs[1])
    Lk.new(gl.outputs[0], mx.inputs[2])
    Lk.new(mx.outputs[0], out.inputs["Surface"])
    return m


# ======================================================================================= mesh kit
class Kit:
    """Collects primitives into one bmesh per material; done() makes one object per material."""

    def __init__(self, name, parent):
        self.name, self.parent = name, parent
        self.bms = {}

    def bm(self, m):
        if m.name not in self.bms:
            self.bms[m.name] = (m, bmesh.new())
        return self.bms[m.name][1]

    @staticmethod
    def _M(c, rot=None, scale=(1, 1, 1)):
        R = Matrix.Identity(4)
        if rot is not None:
            if isinstance(rot, Matrix):
                R = rot.to_4x4()
            else:
                from mathutils import Euler
                R = Euler(rot, "XYZ").to_matrix().to_4x4()
        S = Matrix.Diagonal((*scale, 1.0))
        return Matrix.Translation(Vector(c)) @ R @ S

    def box(self, m, c, s, rot=None):
        bmesh.ops.create_cube(self.bm(m), size=1.0, matrix=self._M(c, rot, s))

    def cyl(self, m, c, r, depth, axis="Z", segs=16, r2=None, rot=None):
        R = {"Z": Matrix.Identity(3), "X": Matrix.Rotation(math.pi / 2, 3, "Y"), "Y": Matrix.Rotation(math.pi / 2, 3, "X")}[axis]
        if rot is not None:
            from mathutils import Euler
            R = Euler(rot, "XYZ").to_matrix() @ R
        bmesh.ops.create_cone(self.bm(m), cap_ends=True, cap_tris=False, segments=segs, radius1=r,
                              radius2=r if r2 is None else r2, depth=depth, matrix=self._M(c, R))

    def sph(self, m, c, r, scale=(1, 1, 1), segs=14, rot=None):
        bmesh.ops.create_uvsphere(self.bm(m), u_segments=segs, v_segments=max(6, segs // 2), radius=r,
                                  matrix=self._M(c, rot, scale))

    def beam(self, m, p0, p1, w, h=None, round_=False, segs=8):
        p0, p1 = Vector(p0), Vector(p1)
        d = p1 - p0
        L = d.length
        if L < 1e-6:
            return
        q = Vector((0, 0, 1)).rotation_difference(d.normalized())
        mid = (p0 + p1) / 2
        if round_:
            bmesh.ops.create_cone(self.bm(m), cap_ends=True, cap_tris=False, segments=segs, radius1=w, radius2=w,
                                  depth=L, matrix=Matrix.Translation(mid) @ q.to_matrix().to_4x4())
        else:
            self.box(m, mid, (w, h or w, L), rot=q.to_matrix())

    def raw(self, m, verts, faces):
        b = self.bm(m)
        vs = [b.verts.new(v) for v in verts]
        for f in faces:
            try:
                b.faces.new([vs[i] for i in f])
            except ValueError:
                pass

    def done(self, smooth_angle=None, bevel=0.0):
        objs = []
        for key, (m, b) in self.bms.items():
            me = bpy.data.meshes.new(f"{self.name}_{key}")
            b.to_mesh(me)
            b.free()
            me.materials.append(m)
            if smooth_angle is not None:
                for p in me.polygons:
                    p.use_smooth = True
                try:
                    me.set_sharp_from_angle(angle=math.radians(smooth_angle))
                except AttributeError:
                    pass
            o = bpy.data.objects.new(f"{self.name}_{key}", me)
            bpy.context.scene.collection.objects.link(o)
            o.parent = self.parent
            if bevel > 0:
                bv = o.modifiers.new("bevel", "BEVEL")
                bv.width, bv.segments, bv.limit_method = bevel, 1, "ANGLE"
            objs.append(o)
        self.bms = {}
        return objs


def empty(name, parent=None, loc=(0, 0, 0)):
    e = bpy.data.objects.new(name, None)
    e.empty_display_size = 0.5
    bpy.context.scene.collection.objects.link(e)
    e.parent = parent
    e.location = loc
    return e


def light(name, kind, loc, color, energy, parent, radius=0.1, rot=None, spot=None):
    ld = bpy.data.lights.new(name, kind)
    ld.color, ld.energy = color, energy
    if kind in ("POINT", "SPOT"):
        ld.shadow_soft_size = radius
    if kind == "SPOT" and spot:
        ld.spot_size = math.radians(spot[0])
        ld.spot_blend = spot[1]
    o = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(o)
    o.parent = parent
    o.location = loc
    if rot is not None:
        o.rotation_euler = rot
    return o


def text(name, body, size, loc, m, parent, rot, extrude=0.02):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.size = size
    cu.extrude = extrude
    cu.align_x, cu.align_y = "CENTER", "CENTER"
    o = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(o)
    o.location, o.rotation_euler = loc, rot
    o.data.materials.append(m)
    o.parent = parent
    return o


# ======================================================================================= hull loft
def hull_loft(kit, m_side, m_bottom, m_deck, L, prof, stations=44, boot=0.4):
    """Closed ship hull. prof(t) -> (hb_top, hb_bottom, keel_z, deck_z, bilge_r) for t in [0 stern, 1 bow].
    Blender local: bow toward -Y, waterline z=0. Faces below `boot` get the bottom (antifouling) material."""
    rings = []
    for i in range(stations + 1):
        t = i / stations
        hbT, hbB, keel, deck, rb = prof(t)
        rb = max(0.05, min(rb, hbB * 0.8, (deck - keel) * 0.45))
        y = -(-L / 2 + t * L)
        stb = [(hbT, deck), ((hbT + hbB) / 2, (deck + keel + rb) / 2), (hbB, keel + rb)]
        cx, cz = hbB - rb, keel + rb
        for k in range(1, 5):
            a = -math.pi / 2 * k / 4
            stb.append((cx + rb * math.cos(a), cz + rb * math.sin(a)))
        ring = stb + [(0.0, keel)] + [(-x, z) for x, z in reversed(stb)] + [(0.0, deck + 0.25)]
        rings.append([(x, y, z) for x, z in ring])
    n = len(rings[0])
    deck_segs = {n - 2, n - 1}
    for m_ in (m_side, m_bottom, m_deck):
        kit.bm(m_)
    verts = {}
    for key in (m_side.name, m_bottom.name, m_deck.name):
        verts[key] = {}

    def vid(m_, i, k):
        b = kit.bm(m_)
        d = verts[m_.name]
        if (i, k) not in d:
            d[(i, k)] = b.verts.new(rings[i][k])
        return d[(i, k)]

    for i in range(stations):
        for k in range(n):
            k2 = (k + 1) % n
            pts = [rings[i][k], rings[i + 1][k], rings[i + 1][k2], rings[i][k2]]
            zc = sum(p[2] for p in pts) / 4
            m_ = m_deck if k in deck_segs else (m_bottom if zc < boot else m_side)
            try:
                kit.bm(m_).faces.new([vid(m_, i, k), vid(m_, i + 1, k), vid(m_, i + 1, k2), vid(m_, i, k2)])
            except ValueError:
                pass
    for i in (0, stations):
        try:
            kit.bm(m_side).faces.new([vid(m_side, i, k) for k in range(n)])
        except ValueError:
            pass
    for m_ in (m_side, m_bottom, m_deck):
        b = kit.bm(m_)
        bmesh.ops.remove_doubles(b, verts=b.verts, dist=1e-4)
        bmesh.ops.recalc_face_normals(b, faces=b.faces)


def _smooth01(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


# ======================================================================================= PRIMROSE
PR_L, PR_B = 150.0, 23.0


def primrose_profile(t):
    B2 = PR_B / 2
    bow = _smooth01((t - 0.74) / 0.26)
    stern = _smooth01((0.1 - t) / 0.1)
    hb = B2 * (1 - bow ** 1.6 * 0.985) * (1 - 0.12 * stern)
    hbT = hb * (1 + 0.06 * bow) if t < 0.995 else 0.3
    hbB = max(0.25, hb * (1 - 0.55 * bow) * (1 - 0.35 * stern))
    keel = -7.5 + 5.5 * _smooth01((t - 0.93) / 0.07) ** 2 + 4.0 * stern ** 1.5
    deck = 6.5 + 3.2 * _smooth01((t - 0.55) / 0.45) ** 2 + 1.0 * stern
    rb = 2.2 + 3.5 * bow + 2.5 * stern
    return hbT, hbB, keel, deck, rb


def primrose_deck(s):
    """deck height at longitudinal s (m, + toward the bow)."""
    return primrose_profile((s + PR_L / 2) / PR_L)[3]


def primrose_halfbeam(s):
    return primrose_profile((s + PR_L / 2) / PR_L)[0]


# bridge interior (spec-local: x starboard, y up, z toward the bow) for POV cameras
PRIMROSE_BRIDGE = {"floor": 18.7, "front": -55.5, "back": -64.0, "eye": [0.0, 20.35, -57.0]}


def primrose(name="primrose", lights=True, seed=3, name_text="PRIMROSE", **_):
    rnd = random.Random(seed)
    root = empty(name)
    P = lambda x, s, z: (x, -s, z)  # ship coords (x stbd, s fore, z up) -> Blender local
    hullm = paint("pr_hull", (0.045, 0.04, 0.038), rust=(0.26, 0.09, 0.03), amount=0.55)
    bottom = paint("pr_antifoul", (0.24, 0.035, 0.025), rust=(0.12, 0.05, 0.03), amount=0.4, streak=False)
    deckm = paint("pr_deck", (0.17, 0.07, 0.045), rust=(0.08, 0.05, 0.03), amount=0.5, streak=False, rough=0.85)
    white = paint("pr_white", (0.62, 0.6, 0.55), rust=(0.3, 0.17, 0.08), amount=0.25, rough=0.6)
    grey = paint("pr_grey", (0.2, 0.21, 0.2), rust=(0.22, 0.09, 0.04), amount=0.45)
    ochre = paint("pr_crane", (0.55, 0.36, 0.06), rust=(0.2, 0.08, 0.03), amount=0.4)
    black = mat("pr_black", (0.015, 0.015, 0.015), 0.5)
    winlit = mat("pr_window_lit", (0.2, 0.15, 0.08), 0.2, emit=(1.0, 0.68, 0.36), strength=4.0 if lights else 0.0)
    windark = mat("pr_window_dark", (0.01, 0.012, 0.015), 0.08, 0.0)
    glass = glass_rain()
    namem = mat("pr_name_paint", (0.75, 0.74, 0.7), 0.6)
    steel = mat("pr_steel", (0.18, 0.18, 0.17), 0.45, 0.8)

    k = Kit(name, root)
    hull_loft(k, hullm, bottom, deckm, PR_L, primrose_profile, stations=48)

    # --- hatches (6) and cranes between them
    hatch_c = [-36.0 + i * 16.5 for i in range(6)]
    for i, sc in enumerate(hatch_c):
        dz = primrose_deck(sc)
        k.box(grey, P(0, sc, dz + 0.6), (14.5, 12.5, 1.2))
        k.box(deckm if i % 2 else grey, P(0, sc, dz + 1.55), (14.0, 12.0, 0.7))
        for j in range(4):
            k.box(grey, P(0, sc - 4.5 + j * 3.0, dz + 2.0), (14.2, 0.35, 0.25))
    for ci, sc in enumerate((hatch_c[0] + 8.25, hatch_c[2] + 8.25, hatch_c[4] + 8.25)):
        dz = primrose_deck(sc)
        k.cyl(ochre, P(0, sc, dz + 3.5), 1.4, 7.0, segs=20)
        k.box(ochre, P(0, sc, dz + 8.5), (4.0, 4.4, 3.0))
        k.box(windark, P(0, sc - 2.25 if ci % 2 == 0 else sc + 2.25, dz + 9.0), (2.6, 0.1, 1.0))
        # jib: two converging chords + braces, elevated 24 deg, alternately fore / aft, slewed to port
        sgn = 1 if ci % 2 == 0 else -1
        root_p = Vector(P(0, sc + sgn * 1.8, dz + 8.0))
        slew = math.radians(18 + 7 * ci)
        el = math.radians(24 + 4 * ci)
        Ljib = 24.0
        dirv = Vector((-math.sin(slew) * math.cos(el), -sgn * math.cos(slew) * math.cos(el), math.sin(el)))
        tip = root_p + dirv * Ljib
        side = dirv.cross(Vector((0, 0, 1))).normalized()
        for sd in (-0.7, 0.7):
            k.beam(ochre, root_p + side * sd, tip + side * 0.12 * (1 if sd > 0 else -1), 0.32)
        for j in range(1, 8):
            u = j / 8
            a = root_p.lerp(tip, u)
            w = 0.7 * (1 - u) + 0.12 * u
            k.beam(ochre, a + side * w, a - side * w, 0.12)
            if j < 7:
                b2 = root_p.lerp(tip, (j + 1) / 8)
                k.beam(ochre, a + side * w, b2 - side * (0.7 * (1 - (j + 1) / 8) + 0.12 * (j + 1) / 8), 0.08)
        hook_z = max(dz + 3.0, tip.z - 11.0)
        k.beam(steel, tip, Vector((tip.x, tip.y, hook_z)), 0.04, round_=True)
        k.box(ochre, (tip.x, tip.y, hook_z - 0.4), (0.7, 0.5, 0.9))

    # --- deck rails (top rail + posts), both sides
    prev = None
    for i in range(4, 46):
        t = i / 48
        s = -PR_L / 2 + t * PR_L
        hbT, _, _, dz, _ = primrose_profile(t)
        cur = [(sx * (hbT - 0.15), s, dz + 1.1) for sx in (-1, 1)]
        if prev:
            for a, b in zip(prev, cur):
                k.beam(steel, P(*a), P(*b), 0.06)
        for a in cur:
            if i % 2 == 0:
                k.beam(steel, P(a[0], a[1], a[2] - 1.1), P(*a), 0.05)
        prev = cur

    # --- forecastle: bulwark, foremast, windlass, hawse pipes
    for sx in (-1, 1):
        for s0, s1 in ((60.0, 68.0), (68.0, 73.0)):
            a = (sx * (primrose_halfbeam(s0) - 0.1), s0, primrose_deck(s0) + 0.7)
            b = (sx * (primrose_halfbeam(s1) - 0.1), s1, primrose_deck(s1) + 0.7)
            k.beam(hullm, P(*a), P(*b), 0.2, 1.4)
        k.cyl(black, P(sx * (primrose_halfbeam(66) + 0.02), 66, 5.4), 0.7, 0.3, axis="X")
        k.box(grey, P(sx * 2.0, 64, primrose_deck(64) + 0.6), (2.0, 2.4, 1.2))
    fz = primrose_deck(62)
    k.cyl(white, P(0, 62, fz + 6.0), 0.3, 12.0, segs=12)
    k.beam(white, P(-3, 62, fz + 9.5), P(3, 62, fz + 9.5), 0.15)

    # --- aft superstructure: 4 accommodation tiers + hollow bridge
    tiers = [(-71.0, -49.0, 10.5, 7.5), (-70.0, -50.5, 10.0, 10.3), (-69.0, -52.0, 9.5, 13.1), (-68.0, -53.0, 9.0, 15.9)]
    for ti, (s0, s1, hw, z0) in enumerate(tiers):
        z1 = z0 + 2.8
        k.box(white, P(0, (s0 + s1) / 2, (z0 + z1) / 2), (hw * 2, s1 - s0, 2.8))
        k.box(grey, P(0, (s0 + s1) / 2, z1 + 0.05), (hw * 2 + 0.5, s1 - s0 + 0.5, 0.12))
        # front windows (facing the bow) and side portholes; ~45% lit
        nwin = int(hw * 2 / 2.2)
        for j in range(nwin):
            x = -hw + 1.1 + j * (hw * 2 - 2.2) / max(1, nwin - 1)
            mw = winlit if rnd.random() < 0.45 else windark
            k.box(mw, P(x, s1 + 0.03, z0 + 1.55), (1.1, 0.08, 0.9))
        for sx in (-1, 1):
            for j in range(int((s1 - s0) / 2.4)):
                s = s0 + 1.5 + j * 2.4
                mw = winlit if rnd.random() < 0.4 else windark
                k.cyl(mw, P(sx * (hw + 0.03), s, z0 + 1.55), 0.3, 0.08, axis="X", segs=14)
                k.cyl(steel, P(sx * (hw + 0.01), s, z0 + 1.55), 0.38, 0.05, axis="X", segs=14)
    # bridge: floor 18.7, room x +-8, s -64..-55.5, height 2.9; wings to +-11.6
    BZ, BF, BB, HW = 18.7, -55.5, -64.0, 8.0
    zt = BZ + 2.9
    k.box(grey, P(0, (BF + BB) / 2, BZ - 0.1), (HW * 2 + 7.2, BF - BB, 0.2))           # floor + wings slab
    k.box(white, P(0, (BF + BB) / 2 - 0.2, zt + 0.15), (HW * 2 + 0.6, BF - BB + 1.4, 0.3))  # roof with visor
    k.box(white, P(0, BB + 0.15, (BZ + zt) / 2), (HW * 2, 0.3, 2.9))                    # back wall
    # front wall with 5 windows
    k.box(white, P(0, BF, BZ + 0.575), (HW * 2, 0.3, 1.15))
    k.box(white, P(0, BF, zt - 0.3), (HW * 2, 0.3, 0.6))
    nwin, x0, x1, mull = 5, -7.2, 7.2, 0.25   # odd: a pane (not a mullion) on the centreline for POV shots
    pw = (x1 - x0 - (nwin - 1) * mull) / nwin
    for sx in (-1, 1):
        k.box(white, P(sx * (HW - 0.4), BF, BZ + 1.725), (0.8, 0.3, 1.15))
    for j in range(nwin):
        xc = x0 + pw / 2 + j * (pw + mull)
        k.box(glass, P(xc, BF + 0.02, BZ + 1.725), (pw, 0.02, 1.15))
        if j < nwin - 1:
            k.box(white, P(xc + pw / 2 + mull / 2, BF, BZ + 1.725), (mull, 0.3, 1.15))
    # side walls with one window each
    for sx in (-1, 1):
        x = sx * (HW - 0.15)
        k.box(white, P(x, (BB + (BF - 3.0)) / 2, (BZ + zt) / 2), (0.3, (BF - 3.0) - BB, 2.9))
        k.box(white, P(x, BF - 0.75, (BZ + zt) / 2), (0.3, 1.5, 2.9))
        k.box(white, P(x, BF - 2.25, BZ + 0.575), (0.3, 1.5, 1.15))
        k.box(white, P(x, BF - 2.25, zt - 0.3), (0.3, 1.5, 0.6))
        k.box(glass, P(x, BF - 2.25, BZ + 1.725), (0.02, 1.5, 1.15))
        # wing bulwark + nav light box
        k.box(white, P(sx * 11.55, BF - 1.3, BZ + 0.55), (0.12, 2.6, 1.1))
        k.box(white, P(sx * (HW + 1.8), BF - 0.1, BZ + 0.55), (3.6, 0.12, 1.1))
    # interior: console + dim gauges + wheel
    k.box(grey, P(0, BF - 0.75, BZ + 0.5), (12.0, 0.8, 1.0))
    gauge = mat("pr_gauge", (0.02, 0.06, 0.03), 0.3, emit=(0.3, 1.0, 0.45), strength=1.5 if lights else 0.0)
    for j in range(10):
        k.cyl(gauge, P(-5.4 + j * 1.2, BF - 1.12, BZ + 0.85), 0.07, 0.02, axis="Y", segs=10)
    k.cyl(steel, P(-2.6, BF - 1.6, BZ + 0.6), 0.06, 1.2, segs=8)
    k.cyl(black, P(-2.6, BF - 1.62, BZ + 1.25), 0.38, 0.05, axis="Y", segs=24)
    # funnel + mast + radar
    k.cyl(white, P(0, -67.0, 22.5), 2.4, 7.6, segs=24, rot=None)
    k.cyl(black, P(0, -67.0, 26.8), 2.45, 1.4, segs=24)
    k.cyl(grey, P(0, -60.0, 25.2), 0.22, 7.0, segs=10)
    k.beam(grey, P(-2.5, -60.0, 26.5), P(2.5, -60.0, 26.5), 0.12)
    # stern: name + port of registry
    k.done(smooth_angle=35, bevel=0.04)

    # radar scanner (spins)
    rad = empty(name + "_radar", root, P(0, -60.0, 28.9))
    rad["spin_rps"], rad["spin_axis"] = 0.4, 2
    kr = Kit(name + "_radar", rad)
    kr.box(grey, (0, 0, 0), (3.2, 0.25, 0.3))
    kr.done()

    # hull name on both sides (midbody, toward the bow) and on the stern
    for sx in (-1, 1):
        s = 50.0
        x = sx * (primrose_halfbeam(s) + 0.05)
        text(f"{name}_name_{'s' if sx > 0 else 'p'}", name_text, 3.2, P(x, s, 3.4), namem, root,
             (math.pi / 2, 0, math.pi / 2 if sx > 0 else -math.pi / 2))
    text(f"{name}_name_stern", name_text, 1.6, P(0, -PR_L / 2 - 0.05, 5.2), namem, root, (math.pi / 2, 0, 0))

    # lights: deck floods (sodium, from the superstructure front, aimed at the foredeck), nav, masthead
    if lights:
        for sx in (-6.0, 0.0, 6.0):
            light(f"{name}_flood{int(sx)}", "SPOT", P(sx, -52.6, 17.0), (1.0, 0.68, 0.38), 9.0e4, root, 0.4,
                  rot=(math.radians(62), 0, 0), spot=(70, 0.6))
        light(f"{name}_nav_port", "POINT", P(-11.6, BF - 0.3, BZ + 1.3), (1.0, 0.08, 0.05), 400, root, 0.1)
        light(f"{name}_nav_stbd", "POINT", P(11.6, BF - 0.3, BZ + 1.3), (0.1, 1.0, 0.3), 400, root, 0.1)
        light(f"{name}_mast", "POINT", P(0, 62, fz + 12.3), (1.0, 0.95, 0.85), 900, root, 0.15)
        light(f"{name}_aft", "POINT", P(0, -60.0, 29.3), (1.0, 0.95, 0.85), 600, root, 0.15)
        light(f"{name}_bridge_red", "POINT", P(0, -59.0, BZ + 2.5), (1.0, 0.15, 0.08), 60, root, 0.3)
    bulbs = mat("pr_bulb", (1, 1, 1), 0.3, emit=(1.0, 0.9, 0.75), strength=25.0 if lights else 0.0)
    kb = Kit(name + "_bulbs", root)
    kb.sph(bulbs, P(0, 62, fz + 12.3), 0.25)
    kb.sph(bulbs, P(0, -60.0, 29.3), 0.25)
    kb.done()
    return root


# ======================================================================================= crew figures
POSES = {
    # joints in figure-local metres; facing -Y; z up
    "stand": dict(pelvis=(0, 0, 0.95), chest=(0, 0, 1.38), head=(0, 0, 1.66), sh=(0.2, 0, 1.42), el=(0.25, 0.02, 1.13),
                  ha=(0.26, -0.03, 0.86), hip=(0.1, 0, 0.92), kn=(0.11, -0.02, 0.5), ft=(0.12, 0, 0.06)),
    "stand_crossed": dict(pelvis=(0, 0, 0.95), chest=(0, 0, 1.38), head=(0, -0.02, 1.64), sh=(0.2, 0, 1.42), el=(0.25, -0.12, 1.12),
                          ha=(-0.1, -0.2, 1.22), hip=(0.1, 0, 0.92), kn=(0.11, -0.02, 0.5), ft=(0.14, 0, 0.06)),
    "sit": dict(pelvis=(0, 0.05, 0.16), chest=(0, 0.16, 0.6), head=(0, 0.17, 0.88), sh=(0.2, 0.14, 0.62), el=(0.27, -0.12, 0.44),
                ha=(0.1, -0.3, 0.52), hip=(0.1, 0.03, 0.15), kn=(0.13, -0.32, 0.5), ft=(0.14, -0.5, 0.06)),
    "sit_head_down": dict(pelvis=(0, 0.05, 0.16), chest=(0, 0.1, 0.58), head=(0, -0.04, 0.78), sh=(0.2, 0.1, 0.6), el=(0.26, -0.14, 0.42),
                          ha=(0.08, -0.3, 0.55), hip=(0.1, 0.03, 0.15), kn=(0.13, -0.32, 0.5), ft=(0.14, -0.5, 0.06)),
    "sit_bench": dict(pelvis=(0, 0.05, 0.5), chest=(0, 0.1, 0.94), head=(0, 0.06, 1.2), sh=(0.2, 0.1, 0.97), el=(0.24, -0.15, 0.78),
                      ha=(0.12, -0.32, 0.6), hip=(0.1, 0.02, 0.48), kn=(0.12, -0.42, 0.5), ft=(0.13, -0.45, 0.06)),
    "lie": dict(pelvis=(0, 0, 0.16), chest=(0, 0.46, 0.18), head=(0, 0.74, 0.22), sh=(0.21, 0.42, 0.18), el=(0.27, 0.16, 0.14),
                ha=(0.2, -0.06, 0.18), hip=(0.1, -0.03, 0.15), kn=(0.12, -0.46, 0.22), ft=(0.13, -0.88, 0.12)),
    "hang": dict(pelvis=(0, 0, -1.02), chest=(0, 0, -0.6), head=(0, -0.03, -0.36), sh=(0.2, 0, -0.56), el=(0.16, -0.06, -0.26),
                 ha=(0.04, -0.02, -0.02), hip=(0.1, 0, -1.04), kn=(0.11, -0.12, -1.45), ft=(0.1, -0.02, -1.86)),
}


def crew_figure(name, parent, pose="stand", loc=(0, 0, 0), yaw=0.0, cloth=None, vest=False):
    """Stylized low-detail silhouette (mannequin): capsule torso, sphere head, tube limbs. Never the islanders."""
    J = POSES[pose]
    root = empty(name, parent, loc)
    root.rotation_euler = (0, 0, yaw)
    cl = cloth or mat("crew_cloth", (0.05, 0.06, 0.09), 0.85)
    skin = mat("crew_skin", (0.32, 0.22, 0.16), 0.7)
    k = Kit(name, root)
    V = lambda p, sx=1: Vector((p[0] * sx, p[1], p[2]))
    k.beam(cl, V(J["pelvis"]), V(J["chest"]), 0.17, round_=True, segs=12)
    k.sph(cl, V(J["chest"]), 0.19, scale=(1.15, 0.75, 0.75))
    k.sph(cl, V(J["pelvis"]), 0.17, scale=(1.05, 0.8, 0.7))
    if vest:
        k.sph(mat("crew_vest", (0.8, 0.28, 0.04), 0.7), V(J["chest"]) + Vector((0, 0, -0.08)), 0.21, scale=(1.05, 0.85, 0.85))
    k.beam(skin, V(J["chest"]), V(J["head"]), 0.05, round_=True)
    k.sph(skin, V(J["head"]), 0.115, scale=(0.9, 1.0, 1.1))
    for sx in (-1, 1):
        k.beam(cl, V(J["sh"], sx), V(J["el"], sx), 0.055, round_=True)
        k.beam(cl, V(J["el"], sx), V(J["ha"], sx), 0.05, round_=True)
        k.sph(skin, V(J["ha"], sx), 0.05)
        k.beam(cl, V(J["hip"], sx), V(J["kn"], sx), 0.075, round_=True)
        k.beam(cl, V(J["kn"], sx), V(J["ft"], sx), 0.065, round_=True)
        k.sph(cl, V(J["kn"], sx), 0.075)
        k.box(mat("crew_boot", (0.02, 0.02, 0.02), 0.6), V(J["ft"], sx) + Vector((0, -0.06, 0)), (0.11, 0.26, 0.1))
    k.done(smooth_angle=60)
    return root


# ======================================================================================= helicopter
def heli_profile(t):
    """fuselage section at t (0 nose -> 1 tail): half width, bottom z, top z"""
    nose = _smooth01(t / 0.2)
    hw = 0.25 + 0.75 * math.sqrt(nose) if t < 0.62 else 1.0 - 0.8 * _smooth01((t - 0.62) / 0.38)
    bot = 0.35 * (1 - _smooth01(t / 0.1)) + 1.75 * _smooth01((t - 0.6) / 0.4) ** 1.2
    top = (1.15 + 1.2 * math.sqrt(nose)) if t < 0.62 else 2.35 + 0.1 * _smooth01((t - 0.62) / 0.38)
    return hw, bot, top


def helicopter(name="helicopter", rotor_disc=True, lights=True, winch=True, survivor=True, **_):
    root = empty(name)
    body = paint("heli_body", (0.28, 0.31, 0.34), rust=(0.12, 0.12, 0.12), amount=0.15, streak=False, rough=0.5, metal=0.2)
    band = mat("heli_dayglo", (0.85, 0.22, 0.04), 0.5)
    dark = mat("heli_glass", (0.01, 0.015, 0.02), 0.05)
    blk = mat("heli_black", (0.02, 0.02, 0.02), 0.5, 0.3)
    k = Kit(name, root)
    # fuselage: superellipse loft, nose toward -Y; s = +8.5 (nose) .. -8.5 (tail)
    NS, NP = 34, 22
    rings = []
    for i in range(NS + 1):
        t = i / NS
        hw, bot, top = heli_profile(t)
        cz, hh = (bot + top) / 2, (top - bot) / 2
        e = 2.0 / (2.8 if t < 0.62 else 2.2)
        y = -(8.5 - 17.0 * t)
        ring = []
        for j in range(NP):
            a = 2 * math.pi * j / NP
            c, s = math.cos(a), math.sin(a)
            ring.append((hw * math.copysign(abs(c) ** e, c), y, cz + hh * math.copysign(abs(s) ** e, s)))
        rings.append((t, ring))
    for i in range(NS):
        t0 = rings[i][0]
        mm = band if (t0 < 0.1 or 0.82 < t0 < 0.9) else body
        for j in range(NP):
            j2 = (j + 1) % NP
            k.raw(mm, [rings[i][1][j], rings[i + 1][1][j], rings[i + 1][1][j2], rings[i][1][j2]], [(0, 1, 2, 3)])
    k.raw(band, rings[0][1], [tuple(range(NP))])
    k.raw(body, rings[-1][1], [tuple(reversed(range(NP)))])
    for mm in (band, body):
        b = k.bm(mm)
        bmesh.ops.remove_doubles(b, verts=b.verts, dist=1e-4)
        bmesh.ops.recalc_face_normals(b, faces=b.faces)
    P = lambda x, s, z: (x, -s, z)
    k.sph(dark, P(0, 6.6, 1.95), 1.0, scale=(0.95, 1.25, 0.62), segs=18)        # windscreen
    for sx in (-1, 1):
        for j in range(4):
            k.box(dark, P(sx * 1.0, -1.6 + j * 1.25, 1.75), (0.06, 0.6, 0.5))      # cabin windows
        k.sph(body, P(sx * 1.6, -0.4, 0.55), 1.0, scale=(0.5, 1.9, 0.45))        # sponsons
        k.cyl(blk, P(sx * 1.75, -0.6, 0.2), 0.33, 0.22, axis="X")                # wheels
    k.box(blk, P(1.02, 2.4, 1.2), (0.06, 1.9, 1.5))                              # open starboard door (dark)
    k.sph(body, P(0, 1.2, 2.45), 1.0, scale=(0.95, 2.8, 0.62))                    # engine cowling
    k.cyl(blk, P(0, 1.0, 3.2), 0.22, 0.8, segs=10)                               # rotor mast
    k.sph(blk, P(0, 1.0, 3.6), 0.38)                                            # hub
    # tail fin (swept) + tail plane
    k.beam(body, P(0, -7.2, 2.2), P(0, -8.4, 4.5), 0.16, 1.2)
    k.box(band, P(0, -7.6, 3.0), (0.18, 1.0, 0.5))
    k.box(body, P(-0.9, -7.9, 3.9), (1.8, 0.7, 0.08))
    # winch arm above the door
    if winch:
        k.beam(blk, P(0.9, 2.4, 2.65), P(1.95, 2.4, 2.65), 0.12)
        k.cyl(blk, P(1.95, 2.4, 2.55), 0.16, 0.3, axis="Y")
    k.done(smooth_angle=50)

    # main rotor (5 blades) + disc
    mr = empty(name + "_rotor_main", root, P(0, 1.0, 3.65))
    mr["spin_rps"], mr["spin_axis"] = 3.4, 2
    km = Kit(name + "_rotor_main", mr)
    for b in range(5):
        a = 2 * math.pi * b / 5
        c = Vector((math.cos(a), math.sin(a), 0)) * 5.0
        km.box(blk, (c.x, c.y, -0.05), (9.4, 0.55, 0.07), rot=(0.06, 0, a))
    if rotor_disc:
        km.cyl(ghost("heli_rotor_disc", (0.08, 0.08, 0.08), alpha=0.18), (0, 0, -0.05), 9.8, 0.02, segs=48)
    km.done()
    # tail rotor (4 blades) on the port side of the fin
    tr = empty(name + "_rotor_tail", root, P(-0.3, -8.1, 3.8))
    tr["spin_rps"], tr["spin_axis"] = 6.0, 0
    kt = Kit(name + "_rotor_tail", tr)
    for b in range(4):
        a = 2 * math.pi * b / 4
        kt.box(blk, (0, math.cos(a) * 0.75, math.sin(a) * 0.75), (0.04, 0.25, 1.5), rot=(a, 0, 0))
    if rotor_disc:
        kt.cyl(ghost("heli_rotor_disc", (0.08, 0.08, 0.08), alpha=0.18), (0, 0, 0), 1.55, 0.02, axis="X", segs=24)
    kt.done()

    if lights:
        bc = light(name + "_beacon", "POINT", P(0, -3.0, 2.75), (1.0, 0.05, 0.03), 120, root, 0.05)
        bc["blink_period"] = 30
        light(name + "_search", "SPOT", P(0, 7.2, 0.4), (1.0, 0.95, 0.85), 2.5e4, root, 0.08,
              rot=(math.radians(25), 0, 0), spot=(22, 0.3))
    if winch:
        wn = empty(name + "_winch", root, P(1.95, 2.4, 2.45))
        cab = empty(name + "_winch_cable", wn)
        cab["winch_cable"] = 1
        kc = Kit(name + "_cable", cab)
        kc.cyl(mat("heli_cable", (0.6, 0.6, 0.6), 0.4, 0.8), (0, 0, -0.5), 0.02, 1.0, segs=6)   # unit length, scaled in z
        kc.done()
        cab.scale = (1, 1, 8.0)
        if survivor:
            load = empty(name + "_winch_load", wn, (0, 0, -8.0))
            load["winch_load"] = 1
            crew_figure(name + "_survivor", load, "hang", cloth=mat("crew_cloth", (0.05, 0.06, 0.09), 0.85), vest=True)
            kh = Kit(name + "_strop", load)
            kh.cyl(band, (0, 0, -0.55), 0.24, 0.12, segs=14)
            kh.done()
    return root


# ======================================================================================= coast guard patrol vessel
CG_L, CG_B = 48.0, 8.4


def cg_profile(t):
    B2 = CG_B / 2
    bow = _smooth01((t - 0.55) / 0.45)
    stern = _smooth01((0.05 - t) / 0.05)
    hb = B2 * (1 - bow ** 1.5 * 0.98) * (1 - 0.05 * stern)
    hbT = hb * (1 + 0.1 * bow) if t < 0.995 else 0.12
    hbB = max(0.1, hb * (1 - 0.65 * bow) * 0.92)
    keel = -2.5 + 2.2 * _smooth01((t - 0.85) / 0.15) ** 2 + 1.2 * stern
    deck = 2.4 + 1.6 * _smooth01((t - 0.5) / 0.5) ** 2
    rb = 0.9 + 0.8 * bow
    return hbT, hbB, keel, deck, rb


def coastguard(name="coastguard", lights=True, beam=True, text_body="COAST GUARD", **_):
    root = empty(name)
    P = lambda x, s, z: (x, -s, z)
    hull = paint("cg_hull", (0.72, 0.72, 0.7), rust=(0.3, 0.2, 0.12), amount=0.12, rough=0.45)
    bottom = paint("cg_antifoul", (0.22, 0.04, 0.03), amount=0.2, streak=False)
    deck = paint("cg_deck", (0.3, 0.31, 0.3), amount=0.1, streak=False, rough=0.8)
    sup = paint("cg_super", (0.75, 0.75, 0.73), rust=(0.3, 0.25, 0.2), amount=0.1, rough=0.45)
    orange = mat("cg_orange", (0.85, 0.3, 0.04), 0.45)
    blue = mat("cg_blue", (0.03, 0.1, 0.38), 0.45)
    dark = mat("cg_glass", (0.01, 0.012, 0.015), 0.06)
    grey = mat("cg_grey", (0.25, 0.26, 0.26), 0.5, 0.4)
    k = Kit(name, root)
    hull_loft(k, hull, bottom, deck, CG_L, cg_profile, stations=40, boot=0.25)
    prof = lambda s: cg_profile((s + CG_L / 2) / CG_L)
    # superstructure + bridge with a wrap-around dark window band
    k.box(sup, P(0, 0, 3.9), (6.2, 14.0, 2.6))
    k.box(sup, P(0, 4.0, 6.3), (5.6, 6.0, 2.2))
    k.box(dark, P(0, 7.02, 6.5), (5.2, 0.06, 0.9))
    for sx in (-1, 1):
        k.box(dark, P(sx * 2.82, 4.6, 6.5), (0.06, 4.0, 0.9))
        for j in range(5):
            k.cyl(dark, P(sx * 3.12, -5.0 + j * 2.4, 3.9), 0.22, 0.06, axis="X", segs=12)
    k.box(sup, P(0, 4.0, 7.5), (5.9, 6.4, 0.2))
    k.cyl(grey, P(0, 2.5, 10.5), 0.14, 6.0, segs=10)                  # mast
    k.beam(grey, P(-2.0, 2.5, 11.8), P(2.0, 2.5, 11.8), 0.1)
    k.box(sup, P(0, -9.0, 3.6), (1.6, 2.2, 2.4))                       # funnel
    k.box(grey, P(0, -9.0, 4.85), (1.7, 2.3, 0.3))
    # foredeck gun mount (generic)
    gz = prof(13.0)[3]
    k.cyl(grey, P(0, 13.0, gz + 0.5), 0.7, 1.0, segs=16)
    k.beam(grey, P(0, 13.4, gz + 0.8), P(0, 15.6, gz + 1.0), 0.06, round_=True)
    # bow stripes (both sides): wide orange + thin blue, raked
    for sx in (-1, 1):
        for off, w, m_ in ((0.0, 1.0, orange), (0.85, 0.35, blue)):
            s0 = 9.5 + off
            hb0, hb1 = prof(s0)[0], prof(s0 + 1.6)[0]
            a = Vector(P(sx * (hb0 + 0.04), s0, 0.3))
            b = Vector(P(sx * (hb1 + 0.04), s0 + 1.6, prof(s0 + 1.6)[3] - 0.15))
            k.beam(m_, a, b, 0.03, w)
        # rails
        prev = None
        for i in range(3, 38):
            t = i / 40
            hbT, _, _, dz, _ = cg_profile(t)
            cur = Vector(P(sx * (hbT - 0.1), -CG_L / 2 + t * CG_L, dz + 0.9))
            if prev is not None:
                k.beam(grey, prev, cur, 0.04)
            if i % 2 == 0:
                k.beam(grey, cur - Vector((0, 0, 0.9)), cur, 0.03)
            prev = cur
    k.done(smooth_angle=35, bevel=0.02)
    rad = empty(name + "_radar", root, P(0, 2.5, 13.6))
    rad["spin_rps"], rad["spin_axis"] = 0.5, 2
    kr = Kit(name + "_radar", rad)
    kr.box(grey, (0, 0, 0), (2.2, 0.18, 0.22))
    kr.done()
    lettering = mat("cg_letter", (0.02, 0.06, 0.28), 0.5)
    for sx in (-1, 1):
        x = sx * (prof(-2.0)[0] + 0.04)
        text(f"{name}_text_{'s' if sx > 0 else 'p'}", text_body, 0.9, P(x, -2.0, 1.55), lettering, root,
             (math.pi / 2, 0, math.pi / 2 if sx > 0 else -math.pi / 2), extrude=0.01)
    # searchlight on the bridge roof (yaw keyable via p['search'])
    sl = empty(name + "_searchlight", root, P(0, 6.2, 8.0))
    sl["search"] = 1
    ks = Kit(name + "_searchlight", sl)
    ks.cyl(grey, (0, 0, 0), 0.32, 0.55, axis="Y", segs=16)
    ks.cyl(mat("cg_lens", (1, 1, 1), 0.2, emit=(1.0, 0.96, 0.88), strength=40.0 if lights else 0.0), (0, -0.29, 0), 0.27, 0.03, axis="Y", segs=16)
    if beam and lights:
        # fake volumetric beam: a long faint emissive cone along -Y (forward of the lamp)
        ks.cyl(ghost("cg_beam", (0.9, 0.92, 1.0), alpha=0.1, strength=1.5), (0, -60.0, 0), 0.3, 120.0, axis="Y", r2=9.0, segs=24)
    ks.done()
    if lights:
        light(name + "_search_spot", "SPOT", (0, -0.35, 0), (1.0, 0.96, 0.88), 3.0e5, sl, 0.1,
              rot=(math.radians(90), 0, 0), spot=(9, 0.25))
        light(name + "_mast", "POINT", P(0, 2.5, 13.9), (1.0, 0.95, 0.85), 300, root, 0.1)
        light(name + "_nav_p", "POINT", P(-2.9, 5.0, 7.0), (1.0, 0.08, 0.05), 120, root, 0.05)
        light(name + "_nav_s", "POINT", P(2.9, 5.0, 7.0), (0.1, 1.0, 0.3), 120, root, 0.05)
        for j in range(4):
            light(f"{name}_port{j}", "POINT", P(0, -5.0 + j * 3.0, 4.1), (1.0, 0.75, 0.45), 40, root, 0.3)
    return root


# ======================================================================================= cargo hold interior
HOLD = {"w": 18.0, "l": 24.0, "h": 11.0}


def cargo_hold(name="cargo_hold", lamp=True, crew=True, slit=True, seed=11, **_):
    """Closed steel hold. Origin = floor centre; +Y aft/-Y forward. Interior lit by a swinging lamp
    (pivot empty tagged swing_*) and a thin daylight slit between the hatch covers."""
    rnd = random.Random(seed)
    W, Lh, H = HOLD["w"], HOLD["l"], HOLD["h"]
    root = empty(name)
    wall = paint("hold_wall", (0.16, 0.19, 0.17), rust=(0.24, 0.1, 0.04), amount=0.6, rough=0.75, scale=0.6)
    floor = paint("hold_floor", (0.09, 0.08, 0.07), rust=(0.17, 0.08, 0.04), amount=0.6, streak=False, rough=0.9, scale=0.8)
    rib = paint("hold_rib", (0.14, 0.16, 0.14), rust=(0.26, 0.1, 0.04), amount=0.65, rough=0.7, scale=0.9)
    sack = paint("hold_sack", (0.32, 0.25, 0.16), rust=(0.22, 0.17, 0.1), amount=0.5, streak=False, rough=0.95, scale=3.0, metal=0.0)
    wood = paint("hold_crate", (0.28, 0.18, 0.1), rust=(0.18, 0.12, 0.07), amount=0.5, rough=0.85, metal=0.0, scale=2.0)
    steel = mat("hold_steel", (0.2, 0.2, 0.2), 0.4, 0.9)
    k = Kit(name, root)
    t = 0.3
    k.box(floor, (0, 0, -t / 2), (W + 2 * t, Lh + 2 * t, t))
    for sx in (-1, 1):
        k.box(wall, (sx * (W / 2 + t / 2), 0, H / 2), (t, Lh + 2 * t, H))
        k.box(wall, (0, sx * (Lh / 2 + t / 2), H / 2), (W, t, H))
        # hopper slopes in the lower corners
        k.box(wall, (sx * (W / 2 - 1.3), 0, 1.0), (0.25, Lh, 3.3), rot=(0, sx * math.radians(-50), 0))
        # side ribs + stringers
        for j in range(int(Lh / 1.6) + 1):
            y = -Lh / 2 + 0.4 + j * 1.6
            k.box(rib, (sx * (W / 2 - 0.2), y, H / 2 + 1.2), (0.4, 0.22, H - 2.4))
        for z in (4.5, 7.8):
            k.box(rib, (sx * (W / 2 - 0.3), 0, z), (0.6, Lh, 0.18))
        for j in range(int(W / 1.8) + 1):
            x = -W / 2 + 0.6 + j * 1.8
            k.box(rib, (x, sx * (Lh / 2 - 0.2), H / 2), (0.22, 0.4, H))
    # ceiling = two hatch-cover undersides with a slit along X at y = -2
    gap_y, gap = -2.0, 0.22 if slit else 0.0
    yA0, yA1 = -Lh / 2, gap_y - gap / 2
    yB0, yB1 = gap_y + gap / 2, Lh / 2
    for y0, y1 in ((yA0, yA1), (yB0, yB1)):
        k.box(wall, (0, (y0 + y1) / 2, H + t / 2), (W + 2 * t, y1 - y0, t))
    for j in range(int(W / 3.0) + 1):
        x = -W / 2 + 1.5 + j * 3.0
        for y0, y1 in ((yA0, yA1), (yB0, yB1)):
            k.box(rib, (x, (y0 + y1) / 2, H - 0.25), (0.25, y1 - y0, 0.5))
    if slit:
        k.box(mat("hold_daylight", (0.6, 0.7, 0.8), 0.5, emit=(0.75, 0.85, 1.0), strength=2.5), (0, gap_y, H + t + 0.05), (W, gap + 0.4, 0.05))
        k.box(wall, (0, gap_y, H + t + 0.3), (W + 2 * t, gap + 1.0, 0.4))
    # ladder on the aft wall
    for sx in (-0.25, 0.25):
        k.box(steel, (W / 2 - 3.0 + sx, Lh / 2 - 0.35, H / 2), (0.06, 0.06, H))
    for j in range(int(H / 0.32)):
        k.box(steel, (W / 2 - 3.0, Lh / 2 - 0.35, 0.3 + j * 0.32), (0.5, 0.04, 0.04))
    # cargo: heaped sacks along the walls + some crates
    for j in range(46):
        side = rnd.choice((-1, 1))
        x = side * (W / 2 - rnd.uniform(1.5, 4.5))
        y = rnd.uniform(-Lh / 2 + 1, Lh / 2 - 1)
        z = rnd.uniform(0.2, 1.1)
        k.sph(sack, (x, y, z), 0.5, scale=(1.4, 0.9, 0.55), segs=10, rot=(0, 0, rnd.uniform(0, math.pi)))
    for (x, y, s) in ((-2.5, 6.5, 1.1), (-1.2, 7.2, 0.9), (3.0, -7.5, 1.2), (4.2, -6.6, 0.8), (1.0, 4.6, 0.7)):
        k.box(wood, (x, y, s / 2), (s, s, s), rot=(0, 0, rnd.uniform(-0.3, 0.3)))
    k.done(smooth_angle=40, bevel=0.02)

    if lamp:
        piv = empty(name + "_lamp_pivot", root, (0.5, 1.0, H - 0.2))
        piv["swing_deg"], piv["swing_period"], piv["swing_axis"] = 11.0, 3.4, 0
        kl = Kit(name + "_lamp", piv)
        kl.cyl(steel, (0, 0, -3.0), 0.015, 6.0, segs=6)
        kl.cyl(mat("hold_shade", (0.12, 0.14, 0.1), 0.5, 0.6), (0, 0, -6.15), 0.08, 0.35, r2=0.38, segs=20)
        kl.sph(mat("hold_bulb", (1, 1, 1), 0.2, emit=(1.0, 0.72, 0.38), strength=60.0), (0, 0, -6.32), 0.08)
        kl.done()
        light(name + "_lamp_light", "POINT", (0, 0, -6.4), (1.0, 0.7, 0.38), 420, piv, 0.06)
    if crew:
        cloth = [mat("crew_cloth", (0.05, 0.06, 0.09), 0.85), mat("crew_cloth_b", (0.11, 0.09, 0.07), 0.85),
                 mat("crew_cloth_c", (0.07, 0.1, 0.12), 0.85)]
        # (pose, x, y, yaw, vest): backs to the walls, around the lamp pool
        # grouped around the lamp pool (aft of centre), readable from a camera at the forward end looking aft
        spots = [("sit", -2.4, 3.2, 0.3, False), ("sit_head_down", -1.3, 3.7, 0.1, True),
                 ("lie", 2.7, 2.2, math.pi * 0.6, False), ("sit_bench", -1.2, 6.6, math.pi, True),
                 ("stand_crossed", 1.9, 4.9, -0.4, False), ("sit", 3.4, 5.8, -0.5, False),
                 ("sit", -W / 2 + 2.7, -1.0, -math.pi / 2, False)]
        for i, (pose, x, y, yaw, vest) in enumerate(spots):
            crew_figure(f"{name}_crew{i}", root, pose, (x, y, 0.0), yaw, cloth[i % 3], vest)
    return root


# ======================================================================================= small FX props
def beach_torches(name="beach_torches", count=7, spread=40.0, seed=5, **_):
    """Torches carried along a beach (local X = along the shore). Flames flicker, torches bob. No people."""
    rnd = random.Random(seed)
    root = empty(name)
    stick = mat("torch_stick", (0.12, 0.07, 0.04), 0.8)
    flame = mat("torch_flame", (1.0, 0.5, 0.15), 0.5, emit=(1.0, 0.48, 0.12), strength=35.0)
    for i in range(count):
        x = -spread / 2 + spread * (i + rnd.uniform(-0.3, 0.3)) / max(1, count - 1)
        y = rnd.uniform(-4, 4)
        z = rnd.uniform(1.2, 1.7)
        t = empty(f"{name}_{i}", root, (x, y, z))
        t["bob"] = rnd.uniform(0, 6.28)
        kk = Kit(f"{name}_{i}", t)
        kk.cyl(stick, (0, 0, -0.55), 0.03, 1.2, segs=6, rot=(rnd.uniform(-0.2, 0.2), rnd.uniform(-0.2, 0.2), 0))
        kk.done()
        fo = empty(f"{name}_{i}_flame", t, (0, 0, 0.12))
        fo["flicker"] = rnd.uniform(0, 6.28)
        kf = Kit(f"{name}_{i}_flame", fo)
        kf.cyl(flame, (0, 0, 0.2), 0.13, 0.5, r2=0.01, segs=10)
        kf.sph(flame, (0, 0, 0.02), 0.13)
        kf.done()
        lo = light(f"{name}_{i}_light", "POINT", (0, 0, 0.35), (1.0, 0.5, 0.17), 1500, t, 0.2)
        lo["flicker"] = fo["flicker"]
    return root


def rotor_wash(name="rotor_wash", radius=15.0, **_):
    root = empty(name)
    root["spin_rps"], root["spin_axis"] = -0.25, 2
    k = Kit(name, root)
    k.cyl(spray(), (0, 0, 0.3), radius, 0.02, segs=48)
    k.cyl(spray(), (0, 0, 1.2), radius * 0.8, 0.02, segs=48)
    k.done()
    return root


BUILDERS = {
    "primrose": primrose, "helicopter": helicopter, "coastguard": coastguard, "cargo_hold": cargo_hold,
    "beach_torches": beach_torches, "rotor_wash": rotor_wash,
}


# ======================================================================================= animation
def _kv(v, f, default=0.0):
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    ks = sorted(v, key=lambda k: k[0])
    if f <= ks[0][0]:
        return ks[0][1]
    if f >= ks[-1][0]:
        return ks[-1][1]
    for (a, va), (b, vb) in zip(ks, ks[1:]):
        if a <= f <= b:
            u = 0 if b == a else (f - a) / (b - a)
            if isinstance(va, (list, tuple)):
                return [x + (y - x) * u for x, y in zip(va, vb)]
            return va + (vb - va) * u
    return ks[-1][1]


def post_place(root, p, f0, f1, fps=30):
    """Key the animation of a placed vehicle prop for frames f0..f1 (inclusive)."""
    objs = [root] + list(root.children_recursive)
    # --- root motion: path / yaw / tilt / rock (spec world coords -> Blender)
    if any(p.get(k_) is not None for k_ in ("path", "yaw", "tilt", "rock")):
        base = root.matrix_basis.copy()
        loc0, _, sc0 = base.decompose()
        tilt = p.get("tilt") or (0.0, 0.0)
        rock = p.get("rock") or {}
        root.rotation_mode = "QUATERNION"
        prev = None
        for f in range(f0, f1 + 1):
            if p.get("path"):
                x, y, z = _kv(p["path"], f)
                loc = Vector((x, -z, y))
            else:
                loc = loc0
            yaw = p.get("rotY", 0.0) + math.radians(_kv(p.get("yaw"), f, 0.0))
            ph = 2 * math.pi * f / (fps * float(rock.get("period", 7.0)))
            pitch = math.radians(tilt[0] + float(rock.get("amp", 0.0)) * 0.4 * math.sin(ph + 1.3))
            roll = math.radians(tilt[1] + float(rock.get("amp", 0.0)) * math.sin(ph))
            q = (Matrix.Rotation(yaw, 4, "Z") @ Matrix.Rotation(pitch, 4, "X") @ Matrix.Rotation(roll, 4, "Y")).to_quaternion()
            if prev is not None and prev.dot(q) < 0:
                q.negate()
            prev = q
            root.location, root.rotation_quaternion, root.scale = loc, q, sc0
            root.keyframe_insert("location", frame=f)
            root.keyframe_insert("rotation_quaternion", frame=f)
    for o in objs:
        if "spin_rps" in o:
            ax = int(o.get("spin_axis", 2))
            o.rotation_mode = "XYZ"
            base = o.rotation_euler[ax]
            for f in (f0, f1):
                o.rotation_euler[ax] = base + 2 * math.pi * float(o["spin_rps"]) * f / fps
                o.keyframe_insert("rotation_euler", index=ax, frame=f)
            fc = o.animation_data.action.fcurves.find("rotation_euler", index=ax)
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"  # constant rpm (render_episode also linearizes everything)
        if "swing_deg" in o:
            ax = int(o.get("swing_axis", 0))
            for f in range(f0, f1 + 1):
                ph = 2 * math.pi * f / (fps * float(o["swing_period"]))
                o.rotation_euler[ax] = math.radians(o["swing_deg"]) * math.sin(ph)
                o.rotation_euler[(ax + 1) % 3] = math.radians(o["swing_deg"]) * 0.25 * math.sin(ph * 0.5 + 0.7)
                o.keyframe_insert("rotation_euler", frame=f)
        if "bob" in o:
            z0 = o.location.z
            for f in range(f0, f1 + 1):
                o.location.z = z0 + 0.06 * math.sin(f / fps * 2.1 + o["bob"])
                o.keyframe_insert("location", index=2, frame=f)
        if "flicker" in o:
            ph = float(o["flicker"])
            if o.type == "LIGHT":
                e0 = o.data.energy
                for f in range(f0, f1 + 1):
                    t = f / fps
                    o.data.energy = e0 * (0.75 + 0.25 * math.sin(t * 17 + ph) * math.sin(t * 6.1 + 2 * ph))
                    o.data.keyframe_insert("energy", frame=f)
            else:
                for f in range(f0, f1 + 1):
                    t = f / fps
                    s = 0.85 + 0.15 * math.sin(t * 15 + ph)
                    o.scale = (s, s, s * (0.9 + 0.2 * math.sin(t * 11 + ph)))
                    o.keyframe_insert("scale", frame=f)
        if "blink_period" in o and o.type == "LIGHT":
            e0 = o.data.energy
            per = int(o["blink_period"])
            for f in range(f0, f1 + 1):
                o.data.energy = e0 if (f % per) < 3 else 0.0
                o.data.keyframe_insert("energy", frame=f)
        if "winch_cable" in o or "winch_load" in o:
            if p.get("winch") is not None:
                for f in range(f0, f1 + 1):
                    L = max(0.3, float(_kv(p["winch"], f)))
                    if "winch_cable" in o:
                        o.scale = (1, 1, L)
                        o.keyframe_insert("scale", frame=f)
                    else:
                        o.location = (0, 0, -L)
                        o.keyframe_insert("location", frame=f)
        if "search" in o and p.get("search") is not None:
            o.rotation_mode = "XYZ"
            for f in range(f0, f1 + 1):
                o.rotation_euler[2] = math.radians(float(_kv(p["search"], f)))
                o.keyframe_insert("rotation_euler", index=2, frame=f)
