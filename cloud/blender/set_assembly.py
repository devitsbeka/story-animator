"""
set_assembly.py - build any world kit (factory/worlds/kits/<id>.json) as a Blender set, deterministically.

render_episode.py calls it for a shot that carries "set": {"kit": "<id>", "seed": N} (or world.set); shots without
one keep the yacht/island path. The plan (terrain heights, scatter instances, pieces, marks, practicals) comes from
factory/worlds/layout.py - the same pure-python code the director uses for staging - so the hero's feet, the marks
and every rock agree between stage 4 and the renderer. Same kit + seed -> same set (plan hash logged).

  sky        night_procedural (render_episode.build_world: stars, moon, clouds) | day_physical (Nishita sky, sun =
             the lighting key) | overcast; then lighting.build_world_rig adds the key light + HDRI env
  terrain    grid mesh from the layout heights, PBR ground from catalog textures (Poly Haven / ambientCG) with a slope
             blend (canyon walls, rock through snow) and a sidewalk layer for streets; distant backdrop ring
  scatter    library glTFs instanced per layer; through scatter_lod.PLANNER (camera-aware LOD) when that module is
             present, else simple collection instancing
  pieces     lib:<catalog id> (true-size model scaled to a height) | proc:<PROC builder> | prop:<props.py builder>
  lights     set practicals (lamps, fire) with optional deterministic flicker

Spec axes (Y up) map to Blender as (x, y, z) -> (x, -z, y); a spec yaw about +y is a Blender rotation about +z.
"""
import json
import math
import os
import random
import sys

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from factory.worlds import layout as L  # noqa: E402  (pure python, no jsonschema)
import lighting  # noqa: E402

try:  # camera-aware LOD for scattered instances (built by another agent; optional)
    import scatter_lod  # noqa: E402
except ImportError:
    scatter_lod = None

KITS_DIR = os.path.join(REPO, "factory", "worlds", "kits")
CATALOG_PATH = os.path.join(REPO, "factory", "library", "catalog.json")
_CAT = {}


def log(*a):
    print("[set_assembly]", *a, flush=True)


# ----------------------------------------------------------------------------------------------
# kit / catalog access
# ----------------------------------------------------------------------------------------------
def kit_ref(spec, shot):
    """{"kit", "seed"?} for a set shot, else None (yacht/island path)."""
    ref = shot.get("set")
    if ref is None:
        ref = (spec.get("world") or {}).get("set")
    if not ref:
        return None
    if isinstance(ref, str):
        ref = {"kit": ref}
    try:
        if load_kit(ref["kit"]).get("legacy"):
            return None  # the sea/yacht kit IS the legacy path
    except FileNotFoundError:
        raise SystemExit(f"unknown world kit {ref['kit']!r} (no {KITS_DIR}/{ref['kit']}.json)")
    return ref


def load_kit(kit_id):
    with open(os.path.join(KITS_DIR, f"{kit_id}.json")) as fh:
        return json.load(fh)


def catalog():
    if not _CAT:
        with open(CATALOG_PATH) as fh:
            _CAT.update(json.load(fh).get("assets", {}))
    return _CAT


def store():
    return os.environ.get("LIBRARY_STORE") or os.path.join(REPO, "library_store")


def lib_file(cid, *roles):
    a = catalog().get(cid)
    if not a:
        return None
    for f in a.get("files", []):
        if f.get("role") in roles:
            p = os.path.join(store(), f["path"])
            if os.path.exists(p):
                return p
    return None


def gltf_rel(cid):
    a = catalog().get(cid) or {}
    return next((f["path"] for f in a.get("files", []) if f.get("role") == "gltf"), None)


def shot_with_kit(shot, kit):
    """Shot copy with the kit defaults the lighting module reads: lighting preset (+ overrides) and env.moonDir/dawn
    from the kit sky (an explicit shot value always wins)."""
    s = dict(shot)
    lt = {"preset": kit["lighting"]["preset"], **(kit["lighting"].get("overrides") or {})}
    lt.update(shot.get("lighting") or {})
    s["lighting"] = lt
    env = {"moonDir": list(kit["sky"]["key_dir"]), "dawn": float(kit["sky"].get("dawn", 0.0))}
    env.update(shot.get("env") or {})
    s["env"] = env
    return s


# ----------------------------------------------------------------------------------------------
# small bpy helpers
# ----------------------------------------------------------------------------------------------
def b3(v):
    return Vector((v[0], -v[2], v[1]))


def place_matrix(pos, yaw=0.0, scale=1.0, tilt=(0.0, 0.0)):
    m = Matrix.Translation(b3(pos)) @ Matrix.Rotation(yaw, 4, "Z")
    if tilt and (tilt[0] or tilt[1]):
        m = m @ Matrix.Rotation(math.radians(tilt[0]), 4, "X") @ Matrix.Rotation(math.radians(tilt[1]), 4, "Y")
    return m @ Matrix.Scale(scale, 4)


def link(ob, parent=None):
    bpy.context.scene.collection.objects.link(ob)
    if parent is not None:
        ob.parent = parent
    return ob


def empty(name, parent=None):
    e = bpy.data.objects.new(name, None)
    return link(e, parent)


def mesh(name, verts, faces, mat=None, parent=None, smooth=False):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.update()
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    if mat is not None:
        me.materials.append(mat)
    return link(bpy.data.objects.new(name, me), parent)


def box_verts(x0, x1, y0, y1, z0, z1):
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return v, f


def box(name, x0, x1, y0, y1, z0, z1, mat, parent=None):
    v, f = box_verts(x0, x1, y0, y1, z0, z1)
    return mesh(name, v, f, mat, parent)


def cyl(name, r, h, mat, parent=None, n=16, r_top=None):
    r_top = r if r_top is None else r_top
    v = [(math.cos(2 * math.pi * i / n) * r, math.sin(2 * math.pi * i / n) * r, 0) for i in range(n)]
    v += [(math.cos(2 * math.pi * i / n) * r_top, math.sin(2 * math.pi * i / n) * r_top, h) for i in range(n)]
    f = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)] + [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
    return mesh(name, v, f, mat, parent, smooth=True)


def blob(name, r, mat, parent=None, squash=(1, 1, 1), seed=0, rough=0.18, seg=10):
    """Lumpy low-poly stone: a UV sphere with seeded radial noise."""
    rng = random.Random(seed)
    verts, faces = [], []
    rings = seg // 2
    for j in range(rings + 1):
        th = math.pi * j / rings
        for i in range(seg):
            ph = 2 * math.pi * i / seg
            k = 1 + (rng.random() * 2 - 1) * rough if 0 < j < rings else 1
            verts.append((math.sin(th) * math.cos(ph) * r * squash[0] * k, math.sin(th) * math.sin(ph) * r * squash[1] * k, math.cos(th) * r * squash[2] * k))
    for j in range(rings):
        for i in range(seg):
            a, b = j * seg + i, j * seg + (i + 1) % seg
            faces.append((a, b, b + seg, a + seg))
    return mesh(name, verts, faces, mat, parent, smooth=True)


def principled(name, color, rough=0.6, metal=0.0, emit=None, strength=0.0):
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


class NT:
    """Tiny node-tree builder."""

    def __init__(self, mat):
        self.t = mat.node_tree
        self.n, self.l = self.t.nodes, self.t.links

    def node(self, typ, inputs=None, **props):
        nd = self.n.new(typ)
        for k, v in props.items():
            setattr(nd, k, v)
        for k, v in (inputs or {}).items():
            if hasattr(v, "is_output") or hasattr(v, "links"):
                self.l.new(v, nd.inputs[k])
            else:
                nd.inputs[k].default_value = v
        return nd

    def math(self, op, a, b=0.0):
        nd = self.n.new("ShaderNodeMath")
        nd.operation = op
        for i, v in enumerate((a, b)):
            if hasattr(v, "is_output"):
                self.l.new(v, nd.inputs[i])
            else:
                nd.inputs[i].default_value = v
        return nd.outputs[0]

    def mix(self, fac, a, b, kind="RGBA"):
        nd = self.n.new("ShaderNodeMix")
        nd.data_type = kind
        idx = {"RGBA": (6, 7, 2), "FLOAT": (2, 3, 0), "VECTOR": (4, 5, 1)}[kind]
        for sock, v in ((nd.inputs[0], fac), (nd.inputs[idx[0]], a), (nd.inputs[idx[1]], b)):
            if hasattr(v, "is_output"):
                self.l.new(v, sock)
            elif kind == "RGBA" and isinstance(v, (tuple, list)) and len(v) == 3:
                sock.default_value = (*v, 1.0)
            else:
                sock.default_value = v
        return nd.outputs[idx[2]]


_IMG = {}


def image(path, noncolor=False):
    key = (path, noncolor)
    if key not in _IMG:
        img = bpy.data.images.load(path, check_existing=True)
        if noncolor:
            img.colorspace_settings.name = "Non-Color"
        _IMG[key] = img
    return _IMG[key]


def tex_layer(nt, spec, vec, box_blend=0.3):
    """One PBR texture set sampled at vec (already scaled to tiles). Returns (color, rough, normal_color|None)."""
    cid = spec.get("texture")
    fallback = tuple(spec.get("color", (0.4, 0.4, 0.4)))
    tint = tuple(spec.get("tint", (1, 1, 1)))
    cpath = lib_file(cid, "Diffuse", "Color") if cid else None
    npath = lib_file(cid, "nor_gl", "NormalGL") if cid else None
    rpath = lib_file(cid, "Rough", "Roughness") if cid else None

    def sample(path, noncolor):
        t = nt.node("ShaderNodeTexImage", {"Vector": vec}, projection="BOX", projection_blend=box_blend)
        t.image = image(path, noncolor)
        return t

    if cpath:
        col = sample(cpath, False).outputs["Color"]
    else:
        if cid:
            log(f"WARNING: texture {cid} files missing in {store()}; flat colour stand-in")
        nz = nt.node("ShaderNodeTexNoise", {"Vector": vec, "Scale": 3.0, "Detail": 6.0})
        col = nt.mix(nz.outputs["Fac"], tuple(c * 0.75 for c in fallback), tuple(min(1, c * 1.2) for c in fallback))
    if tint != (1, 1, 1):
        col = _mul(nt, col, tint)
    rough = sample(rpath, True).outputs["Color"] if rpath else spec.get("roughness", 0.85)
    nrm = sample(npath, True).outputs["Color"] if npath else None
    return col, rough, nrm


def _mul(nt, col, tint):
    nd = nt.n.new("ShaderNodeMix")
    nd.data_type, nd.blend_type = "RGBA", "MULTIPLY"
    nd.inputs[0].default_value = 1.0
    nt.l.new(col, nd.inputs[6])
    nd.inputs[7].default_value = (*tint, 1)
    return nd.outputs[2]


def _mul_sock(nt, a, b):
    nd = nt.n.new("ShaderNodeMix")
    nd.data_type, nd.blend_type = "RGBA", "MULTIPLY"
    nd.inputs[0].default_value = 1.0
    nt.l.new(a, nd.inputs[6])
    nt.l.new(b, nd.inputs[7])
    return nd.outputs[2]


def ground_material(name, mat_spec, walk_spec=None, road_half=None, steep_box=0.35):
    """World-space PBR ground: base layer, optional slope-blended steep layer, optional sidewalk layer (|x| > road_half)."""
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = NT(m)
    bsdf = nt.n["Principled BSDF"]
    tc = nt.node("ShaderNodeTexCoord")
    obj = tc.outputs["Object"]

    def scaled(tile):
        return nt.node("ShaderNodeMapping", {"Vector": obj, "Scale": (1 / tile, 1 / tile, 1 / tile)}).outputs[0]

    col, rough, nrm = tex_layer(nt, mat_spec, scaled(mat_spec.get("tile_m", 4.0)), steep_box)
    # large-scale breakup so tiling never reads
    big = nt.node("ShaderNodeTexNoise", {"Vector": obj, "Scale": 0.02, "Detail": 3.0})
    var = nt.node("ShaderNodeMapRange", {"Value": big.outputs["Fac"], "From Min": 0.3, "From Max": 0.7, "To Min": 0.78, "To Max": 1.12})
    vmix = nt.n.new("ShaderNodeMix")
    vmix.data_type, vmix.blend_type = "RGBA", "MULTIPLY"
    vmix.inputs[0].default_value = 1.0
    nt.l.new(col, vmix.inputs[6])
    comb = nt.node("ShaderNodeCombineColor")
    for i in range(3):
        nt.l.new(var.outputs[0], comb.inputs[i])
    nt.l.new(comb.outputs[0], vmix.inputs[7])
    col = vmix.outputs[2]
    st = mat_spec.get("steep")
    if st:
        geo = nt.node("ShaderNodeNewGeometry")
        sep = nt.node("ShaderNodeSeparateXYZ", {"Vector": geo.outputs["Normal"]})
        jitter = nt.node("ShaderNodeTexNoise", {"Vector": obj, "Scale": 0.15, "Detail": 4.0})
        nzj = nt.math("ADD", sep.outputs["Z"], nt.math("MULTIPLY", nt.math("SUBTRACT", jitter.outputs["Fac"], 0.5), 0.12))
        fac = nt.node("ShaderNodeMapRange", {"Value": nzj, "From Min": math.cos(math.radians(st["from_deg"])),
                                             "From Max": math.cos(math.radians(st["to_deg"]))}).outputs[0]
        c2, r2, n2 = tex_layer(nt, st, scaled(st.get("tile_m", 6.0)), steep_box)
        if st.get("strata"):  # sedimentary bands across steep faces (period in metres, wobbled by noise)
            sep_o = nt.node("ShaderNodeSeparateXYZ", {"Vector": obj})
            wob = nt.node("ShaderNodeTexNoise", {"Vector": obj, "Scale": 0.05, "Detail": 3.0})
            ph = nt.math("ADD", sep_o.outputs["Z"], nt.math("MULTIPLY", wob.outputs["Fac"], st["strata"] * 1.5))
            band = nt.math("SINE", nt.math("MULTIPLY", ph, 2 * math.pi / st["strata"]))
            g = nt.node("ShaderNodeMapRange", {"Value": band, "From Min": -1.0, "From Max": 1.0, "To Min": 0.72, "To Max": 1.12}).outputs[0]
            comb = nt.node("ShaderNodeCombineColor")
            for i in range(3):
                nt.l.new(g, comb.inputs[i])
            c2 = _mul_sock(nt, c2, comb.outputs[0])
        col = nt.mix(fac, col, c2)
        rough = nt.mix(fac, rough, r2, "FLOAT") if not (isinstance(rough, float) and isinstance(r2, float)) else rough
        if nrm is not None and n2 is not None:
            nrm = nt.mix(fac, nrm, n2)
    if walk_spec and road_half:
        sx = nt.node("ShaderNodeSeparateXYZ", {"Vector": obj})
        fac = nt.math("GREATER_THAN", nt.math("ABSOLUTE", sx.outputs["X"]), road_half)
        c2, r2, n2 = tex_layer(nt, walk_spec, scaled(walk_spec.get("tile_m", 2.5)), 0.2)
        col = nt.mix(fac, col, c2)
        if not isinstance(rough, float) or not isinstance(r2, float):
            rough = nt.mix(fac, rough, r2, "FLOAT")
        if nrm is not None and n2 is not None:
            nrm = nt.mix(fac, nrm, n2)
    nt.l.new(col, bsdf.inputs["Base Color"])
    if isinstance(rough, float):
        bsdf.inputs["Roughness"].default_value = rough
    else:
        nt.l.new(rough, bsdf.inputs["Roughness"])
    if nrm is not None:
        nm = nt.node("ShaderNodeNormalMap", {"Color": nrm, "Strength": 0.8})
        nt.l.new(nm.outputs[0], bsdf.inputs["Normal"])
    sp = mat_spec.get("sparkle", 0.0)
    if sp:  # snow glints: sparse tiny cells with a high specular level
        vor = nt.node("ShaderNodeTexVoronoi", {"Vector": obj, "Scale": 90.0})
        g = nt.math("GREATER_THAN", nt.node("ShaderNodeSeparateColor", {"Color": vor.outputs["Color"]}).outputs[0], 0.985)
        nt.l.new(nt.math("ADD", 0.5, nt.math("MULTIPLY", g, 6.0 * sp)), bsdf.inputs["Specular IOR Level"])
    return m


# ----------------------------------------------------------------------------------------------
# sky
# ----------------------------------------------------------------------------------------------
def build_sky(kit, env, frames, fps, night_world):
    """Night: render_episode.build_world (procedural stars/moon/clouds + lighting rig). Day/overcast: a Nishita or
    gradient sky whose sun sits where the lighting key is, then lighting.build_world_rig. Returns the key light."""
    sky = kit["sky"]
    if sky["type"] == "night_procedural":
        return night_world(env)
    w = bpy.data.worlds.new(f"Sky_{kit['id']}")
    bpy.context.scene.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    if lighting.active():
        d = lighting._key_dir_blender(lighting.STATE["cfg"])
    else:
        d = b3(env.get("moonDir", sky["key_dir"])).normalized()
    elev = math.asin(max(-1.0, min(1.0, d.z)))
    if sky["type"] == "day_physical":
        st = nt.nodes.new("ShaderNodeTexSky")
        st.sky_type = "NISHITA"
        st.sun_elevation = max(elev, math.radians(0.5))
        # Nishita: sun_rotation is the azimuth measured from +Y toward -X? measured empirically: dir = (sin r, cos r)
        st.sun_rotation = math.atan2(d.x, d.y) % (2 * math.pi)
        st.air_density = sky.get("air", 1.0)
        st.dust_density = sky.get("dust", 1.0)
        st.sun_disc = True
        st.sun_intensity = 0.4
        nt.links.new(st.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = sky.get("strength", 0.4)
    else:  # overcast: soft grey gradient
        tc = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        nt.links.new(tc.outputs["Generated"], sep.inputs[0])
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = (0.32, 0.34, 0.36, 1)
        ramp.color_ramp.elements[1].color = (0.6, 0.62, 0.66, 1)
        nt.links.new(sep.outputs["Z"], ramp.inputs[0])
        nt.links.new(ramp.outputs[0], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = sky.get("strength", 1.0)
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    if lighting.active():
        return lighting.build_world_rig(w, bg, out)
    sd = bpy.data.lights.new("Sun", "SUN")
    sd.energy = 4.0 if sky["type"] == "day_physical" else 1.5
    sun = link(bpy.data.objects.new("Sun", sd))
    sun.rotation_mode = "QUATERNION"
    sun.rotation_quaternion = (-d).to_track_quat("-Z", "Y")
    return sun


# ----------------------------------------------------------------------------------------------
# terrain
# ----------------------------------------------------------------------------------------------
def build_terrain(kit, plan, root):
    t = kit["terrain"]
    if t["type"] == "none":
        return None
    g = plan["ground"]
    nx, nz = g["nx"], g["nz"]
    sx, sz = g["size"]
    verts, faces = [], []
    for iz in range(nz + 1):
        z = -sz / 2 + sz * iz / nz
        for ix in range(nx + 1):
            verts.append(b3((-sx / 2 + sx * ix / nx, g["heights"][iz][ix], z)))
    W = nx + 1
    for iz in range(nz):
        for ix in range(nx):
            a = iz * W + ix
            faces.append((a, a + W, a + W + 1, a + 1))  # counter-clockwise from above: normals point up (+Z)
    rh = None
    if t["type"] == "street":
        rh = t.get("params", {}).get("road_half", 5.0)
    mat = ground_material(f"ground_{kit['id']}", t.get("material") or {}, t.get("walk_material"), rh)
    ob = mesh(f"terrain_{kit['id']}", verts, faces, mat, root, smooth=True)
    if t["type"] == "street":  # crisp curbs: the grid is too coarse for a 16 cm step, add curb boxes
        p = t.get("params", {})
        ch, rh, ww = p.get("curb_h", 0.15), p.get("road_half", 5.0), p.get("walk_w", 3.0)
        cm = principled("curb_concrete", (0.36, 0.35, 0.33), 0.85)
        for s in (-1, 1):
            x0, x1 = sorted((s * rh, s * (rh + 0.25)))
            box(f"curb_{s}", x0, x1, -sz / 2, sz / 2, -0.2, ch + 0.005, cm, root)
            xa, xb = sorted((s * (rh + 0.25), s * (rh + ww + 6)))
            box(f"walk_{s}", xa, xb, -sz / 2, sz / 2, -0.2, ch, mat, root)
    return ob


def build_backdrop(kit, plan, root):
    ring = plan.get("backdrop") or []
    if not ring:
        return None
    b = kit["terrain"]["backdrop"]
    base = min(min(r) for r in plan["ground"]["heights"]) - 5.0
    verts, faces = [], []
    n = len(ring)
    for a, r0, r1, hpk in ring:
        ca, sa = math.cos(a), math.sin(a)
        for rr, hh in ((r0, base), ((r0 * 0.4 + r1 * 0.6), base + hpk), (r1, base + hpk * 0.35)):
            verts.append(b3((ca * rr, hh, sa * rr)))
    for i in range(n):
        j = (i + 1) % n
        for k in range(2):
            faces.append((i * 3 + k, j * 3 + k, j * 3 + k + 1, i * 3 + k + 1))
    m = bpy.data.materials.new(f"backdrop_{kit['id']}")
    m.use_nodes = True
    nt = NT(m)
    bsdf = nt.n["Principled BSDF"]
    geo = nt.node("ShaderNodeNewGeometry")
    sep = nt.node("ShaderNodeSeparateXYZ", {"Vector": geo.outputs["Position"]})
    hmax = b.get("height", [200, 800])[1]
    rock = tuple((b.get("material") or {}).get("color", (0.36, 0.3, 0.26) if kit["sky"]["time_of_day"] == "day" else (0.2, 0.2, 0.22)))
    nz = nt.node("ShaderNodeTexNoise", {"Vector": geo.outputs["Position"], "Scale": 0.004, "Detail": 8.0})
    col = nt.mix(nz.outputs["Fac"], tuple(c * 0.7 for c in rock), rock)
    if b.get("snowline") is not None:
        sl = base + hmax * b["snowline"]
        fac = nt.node("ShaderNodeMapRange", {"Value": nt.math("ADD", sep.outputs["Z"], nt.math("MULTIPLY", nz.outputs["Fac"], 120.0)),
                                             "From Min": sl, "From Max": sl + 40}).outputs[0]
        col = nt.mix(fac, col, (0.85, 0.88, 0.94))
    nt.l.new(col, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.9
    hz = b.get("haze", 0.0)
    if hz:  # aerial perspective: distant ranges dissolve into the sky colour, most at their feet
        tod = kit["sky"]["time_of_day"]
        hc = tuple(b.get("haze_color") or {"day": (0.55, 0.65, 0.82), "dawn": (0.8, 0.62, 0.55), "dusk": (0.78, 0.6, 0.55)}.get(tod, (0.02, 0.025, 0.045)))
        em = nt.node("ShaderNodeEmission", {"Color": (*hc, 1.0), "Strength": 1.0})
        hn = nt.node("ShaderNodeMapRange", {"Value": sep.outputs["Z"], "From Min": base, "From Max": base + hmax, "To Min": hz, "To Max": hz * 0.55}).outputs[0]
        ms = nt.node("ShaderNodeMixShader", {"Fac": hn})
        nt.l.new(bsdf.outputs[0], ms.inputs[1])
        nt.l.new(em.outputs[0], ms.inputs[2])
        out = next(n for n in nt.n if n.type == "OUTPUT_MATERIAL")
        nt.l.new(ms.outputs[0], out.inputs["Surface"])
    ob = mesh(f"backdrop_{kit['id']}", verts, faces, m, root, smooth=True)
    ob.visible_shadow = False  # distant ranges must never eclipse a low sun on the set
    return ob


# ----------------------------------------------------------------------------------------------
# procedural set pieces (PROC registry: kit pieces name them as proc:<key>)
# ----------------------------------------------------------------------------------------------
def _kelvin(k):
    return tuple(lighting.kelvin_rgb(k))


def _flicker_keys(ld, frames, amp, seed):
    base = ld.energy
    fps = float(bpy.context.scene.render.fps or 30)
    ph = (seed % 997) / 997.0 * 6.283
    for f in range(frames[0] - 1, frames[-1] + 2):
        t = f / fps
        n = math.sin(t * 2 * math.pi * 7.3 + ph) * 0.5 + math.sin(t * 2 * math.pi * 11.9 + 1.1 + ph) * 0.3 + math.sin(t * 2 * math.pi * 2.9 + ph) * 0.2
        if amp > 0.5 and math.sin(t * 2 * math.pi * 0.7 + ph) > 0.93:  # a failing lamp drops out
            n = -1.6
        ld.energy = max(0.0, base * (1.0 + amp * n))
        ld.keyframe_insert("energy", frame=f)
    if ld.animation_data and ld.animation_data.action:
        for fc in ld.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"


def practical(name, loc_b, color, watts, radius=0.1, parent=None, motivation="practical"):
    ld = bpy.data.lights.new(name, "POINT")
    ld.color, ld.energy, ld.shadow_soft_size = color, watts, radius
    ob = link(bpy.data.objects.new(name, ld), parent)
    ob.location = loc_b
    ob["motivation"] = motivation
    return ob


def proc_campfire(name, pc, ctx):
    o = pc.get("opts") or {}
    rng = random.Random(pc["seed"])
    root = empty(name)
    stone = principled("fire_stone", (0.16, 0.15, 0.14), 0.9)
    for i in range(9):
        a = 2 * math.pi * i / 9 + rng.uniform(-0.12, 0.12)
        s = blob(f"{name}_stone{i}", rng.uniform(0.11, 0.16), stone, root, (1.2, 1.0, 0.7), seed=pc["seed"] + i)
        s.location = (math.cos(a) * 0.48, math.sin(a) * 0.48, 0.05)
    wood = principled("fire_log", (0.06, 0.035, 0.02), 0.85)
    char = principled("fire_char", (0.02, 0.015, 0.012), 0.95, emit=(1.0, 0.25, 0.05), strength=1.5)
    for i in range(4):
        lg = cyl(f"{name}_log{i}", 0.05, 0.75, wood if i % 2 else char, root, n=8)
        a = i * math.pi / 2 + 0.4
        lg.location = (math.cos(a) * 0.3, math.sin(a) * 0.3, 0.04)
        lg.rotation_euler = (0, math.radians(-62), a)
    fl = principled("fire_flame", (0, 0, 0), 1.0, emit=(1.0, 0.42, 0.08), strength=14.0)
    for i in range(3):
        c = cyl(f"{name}_flame{i}", rng.uniform(0.09, 0.14), rng.uniform(0.35, 0.6), fl, root, n=8, r_top=0.0)
        c.location = (rng.uniform(-0.07, 0.07), rng.uniform(-0.07, 0.07), 0.05)
        c.visible_shadow = False
    k = o.get("kelvin", 1900)
    lt = practical(f"{name}_light", (0, 0, 0.45), _kelvin(k), o.get("watts", 250), 0.18, root, "practical:fire")
    lt.data.use_shadow = True
    if o.get("flicker", 0.3) > 0:
        _flicker_keys(lt.data, ctx["frames"], o.get("flicker", 0.3), pc["seed"])
    return root


def proc_cairn(name, pc, ctx):
    o = pc.get("opts") or {}
    rng = random.Random(pc["seed"])
    root = empty(name)
    m = principled("cairn_stone", (0.25, 0.24, 0.23), 0.85)
    z, r = 0.0, 0.32
    hgt = o.get("height", 1.2)
    i = 0
    while z < hgt and i < 12:
        h = r * 0.7
        s = blob(f"{name}_{i}", r, m, root, (1.0, rng.uniform(0.8, 1.0), 0.55), seed=pc["seed"] + i)
        s.location = (rng.uniform(-0.03, 0.03), rng.uniform(-0.03, 0.03), z + h * 0.5)
        s.rotation_euler = (0, 0, rng.uniform(0, 6.28))
        z += h * 0.85
        r *= 0.86
        i += 1
    return root


def facade_material(fid, broken, concrete=None):
    name = f"facade_{fid}_{int(broken * 100)}"
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = NT(m)
    bsdf = nt.n["Principled BSDF"]
    tc = nt.node("ShaderNodeTexCoord")
    obj = tc.outputs["Object"]
    vec = nt.node("ShaderNodeMapping", {"Vector": obj, "Scale": (1 / 25.6, 1 / 25.6, 1 / 25.6)}).outputs[0]
    col, rough, nrm = tex_layer(nt, {"texture": fid, "color": (0.3, 0.33, 0.35)}, vec, 0.05)
    # grime: dirt streaks down the facade + per-building tone (Object Info random)
    oi = nt.node("ShaderNodeObjectInfo")
    st = nt.node("ShaderNodeTexNoise", {"Vector": nt.node("ShaderNodeMapping", {"Vector": obj, "Scale": (0.6, 0.6, 0.05)}).outputs[0],
                                         "Scale": 3.0, "Detail": 5.0})
    dirt = nt.node("ShaderNodeMapRange", {"Value": st.outputs["Fac"], "From Min": 0.35, "From Max": 0.75, "To Min": 0.35, "To Max": 1.0})
    tone = nt.node("ShaderNodeMapRange", {"Value": oi.outputs["Random"], "To Min": 0.55, "To Max": 1.0})
    g = nt.math("MULTIPLY", dirt.outputs[0], tone.outputs[0])
    comb = nt.node("ShaderNodeCombineColor")
    for i in range(3):
        nt.l.new(g, comb.inputs[i])
    mm = nt.n.new("ShaderNodeMix")
    mm.data_type, mm.blend_type = "RGBA", "MULTIPLY"
    mm.inputs[0].default_value = 1.0
    nt.l.new(col, mm.inputs[6])
    nt.l.new(comb.outputs[0], mm.inputs[7])
    col = mm.outputs[2]
    if broken > 0:  # broken / boarded windows: random window cells (3.2 m grid) go black
        cell = nt.node("ShaderNodeMapping", {"Vector": obj, "Scale": (1 / 3.2, 1 / 3.2, 1 / 3.2)}).outputs[0]
        vor = nt.node("ShaderNodeTexVoronoi", {"Vector": cell, "Scale": 1.0, "Randomness": 0.0})
        rnd = nt.node("ShaderNodeSeparateColor", {"Color": vor.outputs["Color"]}).outputs[0]
        hole = nt.math("LESS_THAN", nt.math("FRACT", nt.math("ADD", rnd, oi.outputs["Random"])), broken)
        col = nt.mix(hole, col, (0.01, 0.01, 0.012))
    nt.l.new(col, bsdf.inputs["Base Color"])
    if isinstance(rough, float):
        bsdf.inputs["Roughness"].default_value = rough
    else:
        nt.l.new(rough, bsdf.inputs["Roughness"])
    if nrm is not None:
        nt.l.new(nt.node("ShaderNodeNormalMap", {"Color": nrm, "Strength": 0.6}).outputs[0], bsdf.inputs["Normal"])
    return m


def proc_building(name, pc, ctx):
    """Blockout building: facade faces local -Y (= spec +z, so rotY points it at the street). Concrete ground floor
    with a dark door recess, PBR facade above, parapet, a few lit windows."""
    o = pc.get("opts") or {}
    rng = random.Random(pc["seed"])
    w, d = o.get("width", 12.0), o.get("depth", 12.0)
    fl = o.get("floors", [3, 6])
    floors = rng.randint(fl[0], fl[1]) if isinstance(fl, list) else int(fl)
    fh = o.get("floor_h", 3.2)
    gf = fh * 1.3
    H = gf + (floors - 1) * fh
    root = empty(name)
    facs = o.get("facades") or ([o["facade"]] if o.get("facade") else [])
    fid = facs[rng.randrange(len(facs))] if facs else None
    fac_m = facade_material(fid, o.get("broken", 0.3)) if fid else principled("facade_plain", (0.3, 0.3, 0.32), 0.8)
    gnd_m = ground_material("building_ground_floor", {"texture": o.get("texture"), "tile_m": 3.0, "color": (0.35, 0.34, 0.32), "tint": (0.8, 0.8, 0.8)})
    inset = 0.25 * rng.random()
    ob = box(f"{name}_upper", -w / 2 + 0.05, w / 2 - 0.05, -d / 2 + inset, d / 2, gf, H, fac_m, root)
    box(f"{name}_ground", -w / 2, w / 2, -d / 2, d / 2, 0, gf, gnd_m, root)
    par = principled("parapet", (0.2, 0.2, 0.2), 0.9)
    box(f"{name}_parapet", -w / 2, w / 2, -d / 2 + inset - 0.05, d / 2, H, H + 0.6, par, root)
    box(f"{name}_slab", -w / 2 - 0.1, w / 2 + 0.1, -d / 2 - 0.12, d / 2, gf - 0.18, gf, par, root)
    dark = principled("door_dark", (0.008, 0.008, 0.009), 0.9)
    dx = rng.uniform(-w / 4, w / 4)
    box(f"{name}_door", dx - 0.8, dx + 0.8, -d / 2 - 0.01, -d / 2 + 0.25, 0, 2.5, dark, root)
    for i in range(int(w // 4.5)):  # shop windows, boarded or black
        x = -w / 2 + 1.5 + i * 4.5
        if abs(x - dx) < 1.6:
            continue
        mat = dark if rng.random() < 0.6 else principled("boards", (0.12, 0.08, 0.05), 0.9)
        box(f"{name}_shop{i}", x, x + 2.6, -d / 2 - 0.02, -d / 2 + 0.05, 0.8, gf - 0.6, mat, root)
    lit = principled("window_lit", (0.05, 0.04, 0.03), 0.5, emit=(1.0, 0.62, 0.3), strength=4.0)
    cols = max(1, int(w // 3.2))
    nlit = sum(1 for _ in range(floors * cols) if rng.random() < o.get("lit_windows", 0.02))
    for k in range(nlit):
        f, c = rng.randint(1, floors - 1) if floors > 1 else 0, rng.randrange(cols)
        x0 = -w / 2 + (c + 0.15) * (w / cols)
        z0 = gf + (f - 1) * fh + 0.7
        box(f"{name}_lit{k}", x0, x0 + 0.7 * (w / cols), -d / 2 + inset - 0.03, -d / 2 + inset - 0.01, z0, z0 + fh * 0.55, lit, root)
    root["height_m"] = H
    return root


def proc_car_wreck(name, pc, ctx):
    o = pc.get("opts") or {}
    rng = random.Random(pc["seed"])
    root = empty(name)
    paint = bpy.data.materials.new(f"{name}_paint")
    paint.use_nodes = True
    nt = NT(paint)
    bsdf = nt.n["Principled BSDF"]
    tc = nt.node("ShaderNodeTexCoord")
    nz = nt.node("ShaderNodeTexNoise", {"Vector": tc.outputs["Object"], "Scale": 2.2, "Detail": 8.0})
    rust = nt.node("ShaderNodeMapRange", {"Value": nz.outputs["Fac"], "From Min": 0.5, "From Max": 0.62}).outputs[0]
    nt.l.new(nt.mix(rust, tuple(o.get("color", (0.3, 0.05, 0.04))), (0.16, 0.07, 0.03)), bsdf.inputs["Base Color"])
    nt.l.new(nt.mix(rust, 0.45, 0.95, "FLOAT"), bsdf.inputs["Roughness"])
    nt.l.new(nt.mix(rust, 0.35, 0.0, "FLOAT"), bsdf.inputs["Metallic"])
    glass = principled("wreck_glass", (0.01, 0.012, 0.014), 0.15)
    tyre = principled("wreck_tyre", (0.02, 0.02, 0.02), 0.9)
    L_, W_, h0 = 4.3, 1.78, 0.32
    body = box(f"{name}_body", -W_ / 2, W_ / 2, -L_ / 2, L_ / 2, h0, h0 + 0.68, paint, root)
    # cabin: a tapered prism (glass sides) with a roof
    zc0, zc1 = h0 + 0.68, h0 + 1.22
    yb0, yb1, yt0, yt1 = -1.15, 0.95, -0.7, 0.45
    v = [(-W_ / 2 + 0.06, yb0, zc0), (W_ / 2 - 0.06, yb0, zc0), (W_ / 2 - 0.06, yb1, zc0), (-W_ / 2 + 0.06, yb1, zc0),
         (-W_ / 2 + 0.16, yt0, zc1), (W_ / 2 - 0.16, yt0, zc1), (W_ / 2 - 0.16, yt1, zc1), (-W_ / 2 + 0.16, yt1, zc1)]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    mesh(f"{name}_cabin", v, f, glass, root)
    box(f"{name}_roof", -W_ / 2 + 0.14, W_ / 2 - 0.14, yt0 - 0.02, yt1 + 0.02, zc1, zc1 + 0.06, paint, root)
    for i, (sx, sy) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1))):
        if rng.random() < 0.25:
            continue  # stripped wheel
        t = cyl(f"{name}_wheel{i}", 0.33, 0.24, tyre, root, n=14)
        t.rotation_euler = (0, math.radians(90), 0)
        t.location = (sx * (W_ / 2 - 0.1), sy * 1.35, 0.33 - (0.12 if rng.random() < 0.4 else 0))  # some flat
    # slumped: sinks on one side
    root.rotation_euler = (math.radians(rng.uniform(-3, 3)), math.radians(rng.uniform(-4, 4)), 0)
    return root


PROC = {
    "building": proc_building,
    "car_wreck": proc_car_wreck,
    "campfire": proc_campfire,
    "cairn": proc_cairn,
}


# ----------------------------------------------------------------------------------------------
# library instancing (+ optional camera-aware LOD)
# ----------------------------------------------------------------------------------------------
def lib_key(cid):
    return cid.split(":", 1)[1]


def instance(coll, parent, mb, name):
    e = bpy.data.objects.new(name, None)
    e.instance_type, e.instance_collection = "COLLECTION", coll
    link(e, parent)
    e.matrix_basis = mb
    return e


class SetBuild:
    def __init__(self, kit, plan, root):
        self.kit, self.plan, self.root = kit, plan, root
        self.report = {"kit": kit["id"], "seed": plan["seed"], "plan_hash": plan["hash"], "pieces": 0, "instances": 0, "missing": []}


def build_set(kit, seed, frames, fps, night_world, lib_collection, env):
    """World + terrain + backdrop + pieces + practicals. Scatter is realized after the camera is keyed
    (realize_scatter) so the LOD planner can see the shot's camera."""
    plan = L.layout(kit, seed)
    log(f"kit {kit['id']} seed {plan['seed']}: {L.summary(plan)}")
    root = empty(f"SET_{kit['id']}")
    sb = SetBuild(kit, plan, root)
    sb.key = build_sky(kit, env, frames, fps, night_world)
    build_terrain(kit, plan, root)
    build_backdrop(kit, plan, root)
    ctx = {"frames": frames, "fps": fps}
    for pc in plan["pieces"]:
        b = pc["builder"]
        pos, yaw = pc["pos"], pc.get("rotY", 0.0)
        if b.startswith("lib:"):
            cid = b[4:]
            rel = gltf_rel(cid)
            coll, h = lib_collection(lib_key(cid), rel) if rel else (None, 0)
            if coll is None:
                sb.report["missing"].append(cid)
                continue
            s = (pc["height_m"] / max(0.05, h)) if pc.get("height_m") else pc.get("scale_f", 1.0)
            instance(coll, root, place_matrix(pos, yaw, s), f"piece_{pc['id']}")
        elif b.startswith("proc:"):
            ob = PROC[b[5:]](f"piece_{pc['id']}", pc, ctx)
            ob.parent = root
            ob.matrix_basis = place_matrix(pos, yaw, pc.get("scale_f", 1.0)) @ ob.matrix_basis
        elif b.startswith("prop:"):
            import props as propkit
            ob = propkit.BUILDERS[b[5:]](f"piece_{pc['id']}")
            ob.parent = root
            ob.matrix_basis = place_matrix(pos, yaw, pc.get("scale_f", 1.0))
        sb.report["pieces"] += 1
    for lt in plan["lights"]:
        col = tuple(lt["color"]) if lt.get("color") else _kelvin(lt.get("kelvin", 2800))
        ob = practical(f"practical_{lt['id']}", b3(lt["pos"]), col, lt["watts"], lt.get("radius", 0.1), root, f"practical:{lt['id']}")
        if lt.get("flicker"):
            _flicker_keys(ob.data, frames, lt["flicker"], L.seed_int(kit["id"], lt["id"]) % 100000)
    sb.lib_collection = lib_collection
    return sb


def realize_scatter(sb, cam, frames, out_size, cam_at=None):
    plan = sb.plan
    insts = plan["instances"]
    if not insts:
        return {}
    lc = sb.lib_collection
    if scatter_lod is not None and hasattr(scatter_lod, "PLANNER"):
        P = scatter_lod.PLANNER
        P.begin(store())
        for k, it in enumerate(insts):
            rel = gltf_rel(it["asset"])
            if not rel:
                sb.report["missing"].append(it["asset"])
                continue
            mbu = place_matrix(it["pos"], it["yaw"], 1.0, it.get("tilt"))
            P.add(lib_key(it["asset"]), rel, sb.root, mbu, it["height"], f"sc_{it['layer']}_{k}")
        rep = P.realize(cam, frames, out_size, lc, log=log, cam_at=cam_at)
        sb.report["instances"] = rep.get("created", 0)
        sb.report["lod"] = {k: v for k, v in rep.items() if k != "by_asset"}
        return rep
    made = 0
    for k, it in enumerate(insts):
        rel = gltf_rel(it["asset"])
        coll, h = lc(lib_key(it["asset"]), rel) if rel else (None, 0)
        if coll is None:
            if it["asset"] not in sb.report["missing"]:
                sb.report["missing"].append(it["asset"])
            continue
        instance(coll, sb.root, place_matrix(it["pos"], it["yaw"], it["height"] / max(0.05, h), it.get("tilt")), f"sc_{it['layer']}_{k}")
        made += 1
    sb.report["instances"] = made
    log(f"scatter: {made}/{len(insts)} instances (simple instancing; scatter_lod not present)")
    return {"created": made}
