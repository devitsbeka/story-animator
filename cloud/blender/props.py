"""
PROPS: story props built in code (bpy), reusable across episodes.
Each builder returns a root object whose origin is the natural grip / mount point.
Units: metres, Blender Z-up. Props are low-poly-but-bevelled hero objects with real materials.
"""
import math
import bpy
from mathutils import Vector


def _mat(name, color, rough=0.5, metal=0.0, emit=None, strength=0.0):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = strength
    return m


def _link(o, coll=None):
    (coll or bpy.context.scene.collection).objects.link(o)
    return o


def _cube(name, size, loc, mat, parent, bevel=0.004):
    bpy.ops.mesh.primitive_cube_add(size=1)
    o = bpy.context.object
    o.name = name
    o.scale = size
    o.location = loc
    bpy.ops.object.transform_apply(scale=True)
    if bevel:
        m = o.modifiers.new("bevel", "BEVEL")
        m.width, m.segments = bevel, 2
    o.data.materials.append(mat)
    o.parent = parent
    for p in o.data.polygons:
        p.use_smooth = True
    return o


def _cyl(name, r, depth, loc, mat, parent, rot=(0, 0, 0), verts=24):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=depth, vertices=verts, location=loc, rotation=rot)
    o = bpy.context.object
    o.name = name
    o.data.materials.append(mat)
    o.parent = parent
    for p in o.data.polygons:
        p.use_smooth = True
    return o


def _root(name):
    e = bpy.data.objects.new(name, None)
    e.empty_display_size = 0.05
    return _link(e)


def _text(name, body, size, loc, mat, parent, rot=(math.pi / 2, 0, 0)):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.size = size
    cu.align_x, cu.align_y = "CENTER", "CENTER"
    o = bpy.data.objects.new(name, cu)
    _link(o)
    o.location, o.rotation_euler = loc, rot
    o.data.materials.append(mat)
    o.parent = parent
    return o


# ------------------------------------------------------------------ hand props (origin = palm grip)
def vhf_handset(name="radio"):
    """Handheld marine VHF: black body, rubber antenna, glowing LCD reading 16. Long axis = +Z."""
    r = _root(name)
    body = _mat("radio_body", (0.03, 0.03, 0.035), 0.55)
    rub = _mat("radio_rubber", (0.015, 0.015, 0.015), 0.9)
    lcd = _mat("radio_lcd", (0.1, 0.3, 0.35), 0.3, emit=(0.35, 0.95, 1.0), strength=6)
    txt = _mat("radio_txt", (0.0, 0.0, 0.0), 0.5, emit=(0.02, 0.05, 0.06), strength=0.5)
    _cube(name + "_body", (0.06, 0.035, 0.14), (0, 0, 0.03), body, r, 0.008)
    _cyl(name + "_ant", 0.007, 0.11, (0.018, 0, 0.155), rub, r)
    _cube(name + "_knob", (0.014, 0.014, 0.012), (-0.015, 0, 0.106), rub, r, 0.003)
    _cube(name + "_lcd", (0.046, 0.003, 0.03), (0, -0.0185, 0.07), lcd, r, 0.001)
    _text(name + "_ch", "16", 0.022, (0, -0.0205, 0.07), txt, r)
    _cube(name + "_ptt", (0.004, 0.018, 0.035), (0.032, 0, 0.04), rub, r, 0.002)
    return r


def epirb(name="beacon"):
    """Emergency beacon: yellow body, clear dome with a strobe (keyable 'strobe' light). Long axis = +Z."""
    r = _root(name)
    yel = _mat("epirb_yellow", (0.95, 0.62, 0.02), 0.45)
    blk = _mat("epirb_black", (0.02, 0.02, 0.02), 0.7)
    dome = _mat("epirb_dome", (0.9, 0.95, 1.0), 0.1, emit=(1, 1, 1), strength=0.0)
    _cyl(name + "_body", 0.035, 0.17, (0, 0, 0.03), yel, r)
    _cyl(name + "_band", 0.037, 0.03, (0, 0, -0.02), blk, r)
    _cyl(name + "_ant", 0.005, 0.12, (0, 0, 0.17), blk, r)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.03, location=(0, 0, 0.12))
    d = bpy.context.object
    d.name = name + "_dome"
    d.data.materials.append(dome)
    d.parent = r
    ld = bpy.data.lights.new(name + "_strobe", "POINT")
    ld.energy, ld.color, ld.shadow_soft_size = 0.0, (0.9, 0.95, 1.0), 0.02
    lo = _link(bpy.data.objects.new(name + "_strobe", ld))
    lo.location, lo.parent = (0, 0, 0.13), r
    return r


def phone(name="phone"):
    r = _root(name)
    _cube(name + "_body", (0.072, 0.008, 0.15), (0, 0, 0.02), _mat("phone_body", (0.02, 0.02, 0.025), 0.3, 0.6), r, 0.006)
    _cube(name + "_screen", (0.066, 0.001, 0.142), (0, -0.0045, 0.02), _mat("phone_screen", (0.05, 0.05, 0.06), 0.15, emit=(0.6, 0.75, 1.0), strength=2.5), r, 0)
    return r


def trash_bag(name="bag"):
    r = _root(name)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.16, segments=24, ring_count=16, location=(0, 0, -0.16))
    o = bpy.context.object
    o.name = name + "_sack"
    o.scale = (1.0, 0.9, 1.15)
    disp = o.modifiers.new("lumps", "DISPLACE")
    t = bpy.data.textures.new(name + "_tex", "CLOUDS")
    t.noise_scale = 0.12
    disp.texture, disp.strength = t, 0.05
    o.data.materials.append(_mat("bag_black", (0.01, 0.01, 0.012), 0.35))
    o.parent = r
    for p in o.data.polygons:
        p.use_smooth = True
    _cyl(name + "_knot", 0.025, 0.05, (0, 0, 0.0), _mat("bag_black", (0, 0, 0)), r)
    return r


# ------------------------------------------------------------------ boat fittings (origin = deck mount)
def helm_console(name="helm"):
    """Cockpit helm station (polish_yacht): moulded gelcoat console with a raised black dash pod, three chrome-bezel
    gauges + a multifunction display (emissive 'helm_gauge*', keyed by the prop's light keys), twin throttles,
    compass, tinted acrylic screen and a three-spoke stainless wheel facing aft (-Y local = toward the helmsman).
    The wheel rim keeps its original place/size (hand targets depend on it); the top stays at 0.95 m (lamp mount)."""
    import bmesh
    r = _root(name)
    gel = _mat("helm_gel", (0.80, 0.81, 0.79), 0.22)
    gel.node_tree.nodes["Principled BSDF"].inputs["Coat Weight"].default_value = 0.4
    dash = _mat("helm_dash", (0.012, 0.013, 0.015), 0.28)
    dash.node_tree.nodes["Principled BSDF"].inputs["Coat Weight"].default_value = 0.6
    steel = _mat("helm_steel", (0.75, 0.76, 0.78), 0.18, 1.0)
    rubber = _mat("helm_rubber", (0.02, 0.02, 0.022), 0.6)
    gauge = _mat("helm_gauge", (0.05, 0.08, 0.1), 0.3, emit=(0.25, 0.7, 1.0), strength=0.0)
    screen = _mat("helm_gauge_screen", (0.01, 0.015, 0.02), 0.08, emit=(0.15, 0.45, 0.8), strength=0.0)
    acrylic = _mat("helm_screen", (0.01, 0.012, 0.014), 0.04)
    acrylic.node_tree.nodes["Principled BSDF"].inputs["Coat Weight"].default_value = 1.0

    def wn(o):
        m = o.modifiers.new("wn", "WEIGHTED_NORMAL")
        m.keep_sharp = True
        return o

    body = wn(_cube(name + "_box", (0.9, 0.5, 0.95), (0, 0, 0.475), gel, r, 0.045))
    body.modifiers["bevel"].segments = 4
    _cube(name + "_toekick", (0.8, 0.06, 0.09), (0, -0.23, 0.045), rubber, r, 0.01)
    # dash pod: a wedge across the top, sloping toward the helmsman
    me = bpy.data.meshes.new(name + "_dash")
    bm = bmesh.new()
    prof = [(-0.24, 0.95), (-0.20, 0.99), (0.10, 1.13), (0.20, 1.13), (0.22, 0.95)]
    rows = []
    for x in (-0.40, 0.18):
        rows.append([bm.verts.new((x, y, z)) for y, z in prof])
    for j in range(len(prof) - 1):
        bm.faces.new([rows[0][j], rows[0][j + 1], rows[1][j + 1], rows[1][j]])
    bm.faces.new(list(reversed(rows[0])))
    bm.faces.new(rows[1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    d = _link(bpy.data.objects.new(name + "_dash", me))
    d.data.materials.append(dash)
    d.parent = r
    bv = d.modifiers.new("bevel", "BEVEL")
    bv.width, bv.segments = 0.012, 2
    # instruments on the slope (slope from (-0.20, 0.99) to (0.10, 1.13): ~25 deg)
    ang = math.atan2(1.13 - 0.99, 0.30)
    def on_slope(u):
        return lerp2((-0.20, 0.99), (0.10, 1.13), u)
    for i, x in enumerate((-0.31, -0.18)):
        y, z = on_slope(0.55)
        _cyl(f"{name}_gauge{i}", 0.045, 0.012, (x, y, z + 0.006), gauge, r, rot=(ang, 0, 0))
        bpy.ops.mesh.primitive_torus_add(major_radius=0.05, minor_radius=0.007, location=(x, y - 0.002, z + 0.012), rotation=(ang, 0, 0))
        t = bpy.context.object
        t.name, t.parent = f"{name}_bezel{i}", r
        t.data.materials.append(steel)
    y, z = on_slope(0.5)
    scr = _cube(name + "_mfd", (0.20, 0.14, 0.01), (0.03, y, z + 0.006), screen, r, 0.004)
    scr.rotation_euler = (ang, 0, 0)
    # compass binnacle
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.055, location=(-0.10, 0.15, 1.14), segments=16, ring_count=8)
    c = bpy.context.object
    c.name, c.parent, c.scale = name + "_compass", r, (1, 1, 0.6)
    c.data.materials.append(acrylic)
    _cyl(name + "_compass_base", 0.06, 0.02, (-0.10, 0.15, 1.13), dash, r)
    # throttle quadrant (helmsman's right) with twin levers + knobs
    _cube(name + "_throttle_base", (0.16, 0.20, 0.07), (0.31, -0.05, 0.985), dash, r, 0.02)
    for i, x in enumerate((0.27, 0.35)):
        _cyl(f"{name}_throttle{i}", 0.008, 0.16, (x, -0.08, 1.07), steel, r, rot=(math.radians(-25), 0, 0), verts=10)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.022, location=(x, -0.115, 1.14), segments=12, ring_count=6)
        k = bpy.context.object
        k.name, k.parent = f"{name}_throttle_knob{i}", r
        k.data.materials.append(rubber)
    # tinted acrylic screen on the forward edge
    _cube(name + "_screen", (0.80, 0.008, 0.20), (-0.02, 0.23, 1.10), acrylic, r, 0.006).rotation_euler = (math.radians(-18), 0, 0)
    # wheel: rim torus + hub + three spokes, axis pointing aft-up (unchanged placement)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.2, minor_radius=0.014, location=(0, -0.33, 1.08), rotation=(math.radians(60), 0, 0))
    w = bpy.context.object
    w.name = name + "_wheel"
    w.data.materials.append(steel)
    w.parent = r
    for p in w.data.polygons:
        p.use_smooth = True
    _cyl(name + "_hub", 0.035, 0.06, (0, -0.31, 1.07), steel, r, rot=(math.radians(60), 0, 0))
    _cyl(name + "_shaft", 0.02, 0.14, (0, -0.25, 1.035), steel, r, rot=(math.radians(60), 0, 0), verts=12)
    from mathutils import Matrix as _Mx
    rw = _Mx.Rotation(math.radians(60), 3, "X")
    ctr = Vector((0, -0.33, 1.08))
    for k in range(3):
        a = math.radians(90 + 120 * k)
        dirv = rw @ Vector((math.cos(a), math.sin(a), 0))
        mid = ctr + dirv * 0.105
        o = _cyl(f"{name}_spoke{k}", 0.008, 0.17, mid, steel, r, verts=8)
        o.rotation_mode = "QUATERNION"
        o.rotation_quaternion = dirv.to_track_quat("Z", "Y")
    return r


def lerp2(a, b, u):
    return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)


def switch_panel(name="switches"):
    """Breaker / switch panel on a bulkhead: 4 toggles + LEDs (keyable 'leds' emission)."""
    r = _root(name)
    _cube(name + "_plate", (0.28, 0.02, 0.18), (0, 0, 0), _mat("panel_plate", (0.05, 0.05, 0.055), 0.4, 0.3), r, 0.004)
    led = _mat("panel_led", (0.1, 0.02, 0.02), 0.3, emit=(1.0, 0.25, 0.1), strength=0.0)
    for i in range(4):
        x = -0.09 + i * 0.06
        _cube(f"{name}_tog{i}", (0.012, 0.03, 0.03), (x, -0.02, -0.01), _mat("panel_tog", (0.8, 0.8, 0.8), 0.3, 0.8), r, 0.002)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.006, location=(x, -0.012, 0.05))
        o = bpy.context.object
        o.name = f"{name}_led{i}"
        o.data.materials.append(led)
        o.parent = r
    return r


def anchor_lamp(name="lamp"):
    """Small deck lamp (warm), keyable via its 'bulb' light energy."""
    r = _root(name)
    _cyl(name + "_base", 0.05, 0.04, (0, 0, 0.02), _mat("lamp_metal", (0.6, 0.55, 0.45), 0.3, 1.0), r)
    _cyl(name + "_glass", 0.04, 0.1, (0, 0, 0.09), _mat("lamp_glass", (1.0, 0.8, 0.5), 0.1, emit=(1.0, 0.7, 0.35), strength=8.0), r)
    ld = bpy.data.lights.new(name + "_bulb", "POINT")
    ld.energy, ld.color, ld.shadow_soft_size = 60.0, (1.0, 0.72, 0.4), 0.05
    lo = _link(bpy.data.objects.new(name + "_bulb", ld))
    lo.location, lo.parent = (0, 0, 0.1), r
    return r


BUILDERS = {
    "radio": vhf_handset, "beacon": epirb, "phone": phone, "bag": trash_bag,
    "helm": helm_console, "switches": switch_panel, "lamp": anchor_lamp,
}
