"""
render_episode.py - build an episode shot in Blender (bpy, 4.2 LTS) from episode.json and
render a frame range as PNG plates (no captions).

  blender -b -P cloud/blender/render_episode.py -- --spec episodes/<id>/episode.json \
          --start N --end M --out episodes/<id>/plates/ [--quality preview|final] [--engine EEVEE|CYCLES]

Also runs under the `bpy` pip module:  python render_episode.py --spec ... (same flags).

Frames are ABSOLUTE film frames at 30 fps; --end is INCLUSIVE. A range may span several shots;
each shot is built from scratch (deterministic) and its frames are written to
<out>/<shotId>/<frame:04d>.png plus <out>/<shotId>/_render_<start>_<end>.json (a small manifest).

Coordinates: the spec uses three.js / glTF axes (Y up, metres; yacht-local +z bow, +x starboard).
Blender is Z up. A spec point (x, y, z) maps to Blender (x, -z, y) - the same mapping the glTF
importer applies, so imported GLBs line up with no extra rotation.
"""
import argparse
import ctypes
import json
import math
import os
import sys
import time

import bpy
import bmesh
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

LOG_PREFIX = "[render_episode]"
WARNINGS = []


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import acting  # noqa: E402
import props as propkit  # noqa: E402
import lighting  # noqa: E402  (sequence lighting + night world: cloud/blender/lighting.py)
# >>> yachtsea: yacht PBR materials + night-sea look (cloud/blender/materials.py, oceanfx.py)
import materials as yachtmats  # noqa: E402
import oceanfx  # noqa: E402
# <<< yachtsea
# --- props2 hook: vehicles / sets (Primrose 1981) and storm weather + archival grade
import props_vehicles as vehicles  # noqa: E402
import storm  # noqa: E402
# --- end props2 hook


def log(*a):
    print(LOG_PREFIX, *a, flush=True)


def warn(msg):
    WARNINGS.append(msg)
    log("WARNING:", msg)


# ----------------------------------------------------------------------------------------------
# args / paths
# ----------------------------------------------------------------------------------------------
def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    p = argparse.ArgumentParser(description="Render episode plates with Blender")
    p.add_argument("--spec", required=True, help="path to episode.json")
    p.add_argument("--start", type=int, required=True, help="first absolute film frame")
    p.add_argument("--end", type=int, required=True, help="last absolute film frame (inclusive)")
    p.add_argument("--out", required=True, help="plates dir (episodes/<id>/plates/); <shot>/####.png is written inside")
    p.add_argument("--quality", choices=["preview", "final"], default="preview")
    p.add_argument("--engine", choices=["EEVEE", "CYCLES"], default="EEVEE")
    p.add_argument("--root", default=os.environ.get("STORAGE_ROOT"),
                   help="storage root that asset keys are relative to (default: $STORAGE_ROOT or auto-detect from the spec path)")
    p.add_argument("--res", default=None, help="override resolution WxH, e.g. 270x480")
    p.add_argument("--samples", type=int, default=None, help="override render samples")
    p.add_argument("--threads", type=int, default=0, help="CPU threads (0 = auto)")
    p.add_argument("--exposure", type=float, default=None, help="override view exposure (stops)")
    p.add_argument("--ocean-res", type=int, default=None, help="Ocean modifier resolution (default 10; same for preview and final so the waves match)")
    p.add_argument("--haze", type=float, default=0.0, help="volumetric haze density (0 = off)")
    p.add_argument("--lighting", default=None, help="override the lighting preset for every shot (lighting.PRESETS name, or 'legacy')")
    p.add_argument("--no-motion-blur", action="store_true")
    p.add_argument("--skip-existing", action="store_true", help="do not re-render plates that already exist")
    p.add_argument("--save-blend", default=None, help="also save the built scene of each shot to this .blend path prefix")
    p.add_argument("--strict-engine", action="store_true", help="fail instead of falling back from EEVEE to Cycles when no GPU/EGL")
    # >>> docuseries hook: dual-frame shots carry cameras {main (16:9), vertical (9:16)}
    p.add_argument("--camera", choices=["main", "vertical"], default="main",
                   help="which camera of dual-frame shots to render; 'vertical' renders only shots with cameras.vertical, "
                        "at the episode's vertical size (1080x1920), into <out>_vertical when --out ends in /plates")
    # <<< docuseries
    return p.parse_args(argv)


def find_root(spec_path):
    d = os.path.dirname(os.path.abspath(spec_path))
    for _ in range(6):
        if os.path.isdir(os.path.join(d, "assets")) or os.path.isdir(os.path.join(d, "studio", "public", "assets")):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(spec_path))))


ROOT = "."


def resolve(key):
    """Storage key -> local path (or None). Dev fallback: the Remotion studio's public dir."""
    if not key:
        return None
    if os.path.isabs(key) and os.path.exists(key):
        return key
    for base in (ROOT, os.path.join(ROOT, "studio", "public")):
        p = os.path.join(base, key)
        if os.path.exists(p):
            return p
    return None


# ----------------------------------------------------------------------------------------------
# math: spec (three.js, Y up) <-> Blender (Z up)
# ----------------------------------------------------------------------------------------------
T = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
TI = T.transposed()


def b3(v):
    """spec point -> Blender Vector"""
    return Vector((v[0], -v[2], v[1]))


def obj_mat(m3):
    """spec-space object matrix -> Blender object matrix (for glTF-imported / converted geometry)."""
    return T @ m3 @ TI


def rot_y(a):
    return Matrix.Rotation(a, 4, "Y")


def trans(v):
    return Matrix.Translation(Vector(v))


def lerp(a, b, t):
    return a + (b - a) * t


def keyed(v, f, default=0.0):
    """scalarOrKeys: number, or [[f, v], ...] linear between keys, hold outside."""
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


def keyed_vec(ks, f, n):
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


# ---- camera eases (same as studio/src/kit/camrig.ts) ----
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


EASE = {
    "arrive": bez(0.16, 1, 0.3, 1),
    "move": bez(0.65, 0, 0.35, 1),
    "exit": bez(0.7, 0, 0.84, 0),
    "anticipate": bez(0.5, -0.32, 0.25, 1),
    "overshoot": bez(0.34, 1.45, 0.64, 1),
    "crashIn": lambda t: t * t * t,
    "linear": lambda t: t,
}


def rig_at(f, keys, handheld=0.2, shakes=(), drift=0.25):
    """Port of camrig.ts rigAt: returns cam, look (spec space of the keys), fov (deg), roll (deg)."""
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


def look_matrix3(cam, look, roll_deg):
    """three.js camera world matrix (looks down -Z, +Y up) with roll, like ocean3d.makeCamera."""
    c, l = Vector(cam), Vector(look)
    fwd = (l - c).normalized()
    up = Vector((0, 1, 0))
    up.rotate(Matrix.Rotation(-math.radians(roll_deg), 3, fwd))
    z = -fwd
    x = up.cross(z)
    if x.length < 1e-6:
        x = Vector((1, 0, 0))
    x.normalize()
    y = z.cross(x)
    m = Matrix.Identity(4)
    for r in range(3):
        m[r][0], m[r][1], m[r][2], m[r][3] = x[r], y[r], z[r], c[r]
    return m


# ----------------------------------------------------------------------------------------------
# node helpers
# ----------------------------------------------------------------------------------------------
class NB:
    def __init__(self, tree):
        self.t = tree
        self.n = tree.nodes
        self.l = tree.links

    def node(self, typ, inputs=None, **props):
        nd = self.n.new(typ)
        for k, v in props.items():
            setattr(nd, k, v)
        for k, v in (inputs or {}).items():
            sock = nd.inputs[k]
            if isinstance(v, bpy.types.NodeSocket):
                self.l.new(v, sock)
            else:
                sock.default_value = v
        return nd

    def math(self, op, a, b=None, clamp=False):
        nd = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, bpy.types.NodeSocket):
                self.l.new(v, nd.inputs[i])
            else:
                nd.inputs[i].default_value = v
        return nd.outputs[0]

    def vmath(self, op, a, b=None):
        nd = self.node("ShaderNodeVectorMath", operation=op)
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, bpy.types.NodeSocket):
                self.l.new(v, nd.inputs[i])
            else:
                nd.inputs[i].default_value = v
        out = nd.outputs["Value"] if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else nd.outputs["Vector"]
        return out

    def mix(self, a, b, fac):
        nd = self.node("ShaderNodeMix", data_type="RGBA")
        for sock, v in ((nd.inputs[0], fac), (nd.inputs[6], a), (nd.inputs[7], b)):
            if isinstance(v, bpy.types.NodeSocket):
                self.l.new(v, sock)
            else:
                sock.default_value = v
        return nd.outputs[2]

    def link(self, a, b):
        self.l.new(a, b)


def rgba(c, a=1.0):
    return (c[0], c[1], c[2], a)


def emission_mat(name, color, strength):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nb = NB(m.node_tree)
    nb.n.clear()
    out = nb.node("ShaderNodeOutputMaterial")
    em = nb.node("ShaderNodeEmission", {"Color": rgba(color), "Strength": strength})
    nb.link(em.outputs[0], out.inputs[0])
    return m, em


def principled_mat(name, color, rough=0.5, metal=0.0, emit=None, emit_strength=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = rgba(color)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if emit is not None:
        bsdf.inputs["Emission Color"].default_value = rgba(emit)
        bsdf.inputs["Emission Strength"].default_value = emit_strength
    return m


# ----------------------------------------------------------------------------------------------
# scene pieces
# ----------------------------------------------------------------------------------------------
def link_obj(ob, coll=None):
    (coll or bpy.context.scene.collection).objects.link(ob)
    return ob


def new_empty(name, parent=None):
    e = bpy.data.objects.new(name, None)
    link_obj(e)
    if parent is not None:
        e.parent = parent
    return e


def mesh_obj(name, verts, faces, mat=None, parent=None, smooth=False):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.update()
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    link_obj(ob)
    if mat:
        me.materials.append(mat)
    if parent is not None:
        ob.parent = parent
    return ob


def box(name, center3, size3, mat, parent=None):
    """axis-aligned box in SPEC (three) local coords, converted to Blender."""
    cx, cy, cz = center3
    sx, sy, sz = (s / 2 for s in size3)
    vs = [b3((cx + dx * sx, cy + dy * sy, cz + dz * sz)) for dx in (-1, 1) for dy in (-1, 1) for dz in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return mesh_obj(name, vs, faces, mat, parent)


def sphere(name, center3, r, mat, parent=None):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=r)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    link_obj(ob)
    me.materials.append(mat)
    ob.location = b3(center3)
    if parent is not None:
        ob.parent = parent
    return ob


def point_light(name, loc3, color, watts, radius=0.05, parent=None):
    ld = bpy.data.lights.new(name, "POINT")
    ld.color = color
    ld.energy = watts
    ld.shadow_soft_size = radius
    ob = bpy.data.objects.new(name, ld)
    link_obj(ob)
    ob.location = b3(loc3)
    if parent is not None:
        ob.parent = parent
    return ob


def key_value(idblock, path, frames_values, index=-1, interp="LINEAR"):
    """insert keyframes [(f, v)] on idblock.path; LINEAR interpolation."""
    for f, v in frames_values:
        if index >= 0:
            getattr(idblock, path)[index] = v
        else:
            setattr(idblock, path, v)
        idblock.keyframe_insert(path, index=index, frame=f)
    # interpolation is fixed for every keyed curve by linearize_all() once the shot is built


def linearize_all():
    """All scripted keys are per-frame samples or ramps: LINEAR everywhere (motion blur subframes)."""
    ids = list(bpy.data.objects) + list(bpy.data.lights) + list(bpy.data.cameras)
    ids += [m.node_tree for m in bpy.data.materials if m.node_tree] + [w.node_tree for w in bpy.data.worlds if w.node_tree]
    for idb in ids:
        ad = getattr(idb, "animation_data", None)
        if ad and ad.action:
            for fc in ad.action.fcurves:
                for kp in fc.keyframe_points:
                    kp.interpolation = "LINEAR"
                fc.extrapolation = "LINEAR" if fc.data_path.endswith("time") else "CONSTANT"


def set_linear(idblock):
    ad = getattr(idblock, "animation_data", None)
    if ad and ad.action:
        for fc in ad.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"


# ---------------- world: night sky, stars, clouds, moon disc, dawn ----------------
def build_world(env, fps, frames, haze=0.0):
    moon3 = Vector(env["moonDir"]).normalized()
    moon = b3(moon3).normalized()
    dawn = float(env.get("dawn", 0) or 0)
    w = bpy.data.worlds.new("NightSky")
    bpy.context.scene.world = w
    w.use_nodes = True
    nb = NB(w.node_tree)
    nb.n.clear()
    out = nb.node("ShaderNodeOutputWorld")
    tc = nb.node("ShaderNodeTexCoord")
    d = nb.vmath("NORMALIZE", tc.outputs["Generated"])
    sep = nb.node("ShaderNodeSeparateXYZ", {"Vector": d})
    elev = nb.math("MAXIMUM", sep.outputs["Z"], 0.0)
    # horizon haze (moon side brighter) -> zenith
    night_h, dawn_h = (0.012, 0.02, 0.045), (0.55, 0.28, 0.22)
    night_t, dawn_t = (0.0008, 0.0016, 0.006), (0.05, 0.08, 0.22)
    haze_c = tuple(lerp(a, b, dawn) for a, b in zip(night_h, dawn_h))
    top_c = tuple(lerp(a, b, dawn) for a, b in zip(night_t, dawn_t))
    flat = nb.vmath("MULTIPLY", d, (1, 1, 0))
    flatn = nb.vmath("NORMALIZE", flat)
    mflat = nb.math("MAXIMUM", nb.vmath("DOT_PRODUCT", flatn, Vector((moon.x, moon.y, 0)).normalized()), 0.0)
    moonside = nb.math("POWER", mflat, 8.0)
    haze_s = nb.mix(rgba(haze_c), rgba(tuple(c + g * (1 - dawn) for c, g in zip(haze_c, (0.02, 0.028, 0.05)))), moonside)
    ge = nb.math("POWER", elev, 0.38)
    sky = nb.mix(haze_s, rgba(top_c), ge)
    # moon glow + halo
    md = nb.math("MAXIMUM", nb.vmath("DOT_PRODUCT", d, moon), 0.0)
    glow = nb.math("ADD", nb.math("MULTIPLY", nb.math("POWER", md, 220.0), 1.2), nb.math("MULTIPLY", nb.math("POWER", md, 18.0), 0.3))
    glow_c = nb.node("ShaderNodeMix", data_type="RGBA", blend_type="ADD")
    nb.link(glow, glow_c.inputs[0])
    nb.link(sky, glow_c.inputs[6])
    glow_c.inputs[7].default_value = (0.16, 0.19, 0.28, 1)
    sky = glow_c.outputs[2]
    # stars: voronoi cells on the direction, random threshold, faded near the horizon and at dawn
    if dawn < 0.98:
        for scale, thr, gain in ((180.0, 0.985, 6.0), (420.0, 0.97, 2.5)):
            vor = nb.node("ShaderNodeTexVoronoi", {"Vector": d, "Scale": scale, "Randomness": 0.9}, voronoi_dimensions="3D", feature="F1")
            pt = nb.math("LESS_THAN", vor.outputs["Distance"], 0.08)
            rnd = nb.node("ShaderNodeSeparateColor", {"Color": vor.outputs["Color"]})
            on = nb.math("GREATER_THAN", rnd.outputs[0], thr)
            star = nb.math("MULTIPLY", nb.math("MULTIPLY", pt, on), gain * (1 - dawn))
            hor = nb.node("ShaderNodeMapRange", {"Value": sep.outputs["Z"], "From Min": 0.02, "From Max": 0.2})
            star = nb.math("MULTIPLY", star, hor.outputs[0])
            add = nb.node("ShaderNodeMix", data_type="RGBA", blend_type="ADD")
            nb.link(star, add.inputs[0])
            nb.link(sky, add.inputs[6])
            add.inputs[7].default_value = (0.8, 0.86, 1.0, 1)
            sky = add.outputs[2]
    # moon disc (angular radius 0.026 rad), limb-darkened, mottled
    r = 0.026
    disc = nb.node("ShaderNodeMapRange", {"Value": md, "From Min": math.cos(r), "From Max": math.cos(r * 0.92)})
    mott = nb.node("ShaderNodeTexNoise", {"Vector": d, "Scale": 220.0, "Detail": 3.0})
    mc = nb.node("ShaderNodeMapRange", {"Value": mott.outputs["Fac"], "From Min": 0.45, "From Max": 0.65, "To Min": 1.0, "To Max": 0.65})
    moon_col = nb.math("MULTIPLY", mc.outputs[0], 40.0)
    mcol = nb.node("ShaderNodeCombineColor")
    nb.link(nb.math("MULTIPLY", moon_col, 1.0), mcol.inputs[0])
    nb.link(nb.math("MULTIPLY", moon_col, 0.98), mcol.inputs[1])
    nb.link(nb.math("MULTIPLY", moon_col, 0.9), mcol.inputs[2])
    sky = nb.mix(sky, mcol.outputs[0], disc.outputs[0])
    # clouds: fbm banks projected on a dome, drifting with time (W), lit from the moon
    zc = nb.math("ADD", sep.outputs["Z"], 0.08)
    zc = nb.math("MAXIMUM", zc, 0.04)
    proj = nb.vmath("DIVIDE", d, nb.node("ShaderNodeCombineXYZ", {"X": zc, "Y": zc, "Z": 1.0}).outputs[0])
    proj = nb.vmath("MULTIPLY", proj, (0.55, 0.55, 0.0))
    cn = nb.node("ShaderNodeTexNoise", {"Vector": proj, "Scale": 1.6, "Detail": 6.0, "Roughness": 0.55}, noise_dimensions="4D")
    t0, t1 = frames[0], frames[-1]
    key_value(cn.inputs["W"], "default_value", [(t0, t0 / fps * 0.01), (t1 + 1, (t1 + 1) / fps * 0.01)])
    cov = nb.node("ShaderNodeMapRange", {"Value": cn.outputs["Fac"], "From Min": 0.5, "From Max": 0.68})
    above = nb.node("ShaderNodeMapRange", {"Value": sep.outputs["Z"], "From Min": 0.0, "From Max": 0.12})
    covm = nb.math("MULTIPLY", nb.math("MULTIPLY", cov.outputs[0], above.outputs[0]), 0.95)
    lit = nb.math("ADD", nb.math("MULTIPLY", nb.math("POWER", md, 6.0), 1.4), nb.math("MULTIPLY", nb.math("POWER", md, 40.0), 2.0))
    cloud_dark = tuple(lerp(a, b, dawn) for a, b in zip((0.004, 0.006, 0.014), (0.3, 0.2, 0.22)))
    cloud_lit = tuple(lerp(a, b, dawn) for a, b in zip((0.12, 0.13, 0.17), (0.85, 0.55, 0.45)))
    cloud = nb.mix(rgba(cloud_dark), rgba(cloud_lit), nb.math("MINIMUM", lit, 1.0))
    sky = nb.mix(sky, cloud, covm)
    bg = nb.node("ShaderNodeBackground", {"Color": sky, "Strength": 1.0})
    nb.link(bg.outputs[0], out.inputs["Surface"])
    if haze > 0:
        vol = nb.node("ShaderNodeVolumePrincipled", {"Density": haze, "Color": rgba((0.5, 0.55, 0.7))})
        nb.link(vol.outputs[0], out.inputs["Volume"])
    # >>> lighting hook: sequence key + HDRI env (lighting.py); legacy suns below only for preset 'legacy'
    if lighting.active():
        return lighting.build_world_rig(w, bg, out)
    # <<< lighting hook
    # moonlight
    sd = bpy.data.lights.new("Moon", "SUN")
    sd.color = tuple(lerp(a, b, dawn) for a, b in zip((0.62, 0.72, 1.0), (1.0, 0.75, 0.6)))
    sd.energy = lerp(1.1, 2.5, dawn)
    sd.angle = 2 * r
    sun = bpy.data.objects.new("Moon", sd)
    link_obj(sun)
    sun.rotation_mode = "QUATERNION"
    sun.rotation_quaternion = (-moon).to_track_quat("-Z", "Y")
    # sky fill (the hemisphere light of the three.js stack)
    fd = bpy.data.lights.new("SkyFill", "SUN")
    fd.color = (0.35, 0.45, 0.8)
    fd.energy = 0.12 + 0.5 * dawn
    fd.angle = math.radians(90)
    fill = bpy.data.objects.new("SkyFill", fd)
    link_obj(fill)
    fill.rotation_euler = (0, 0, 0)
    return sun


# ---------------- ocean: Ocean modifier tiles + flat horizon frame ----------------
OCEAN_TILE = 60  # metres per FFT tile


def ocean_params(mod, sea_state, res):
    mod.geometry_mode = "GENERATE"
    mod.resolution = res
    mod.viewport_resolution = min(res, 6)
    mod.spatial_size = OCEAN_TILE
    mod.spectrum = "JONSWAP" if sea_state >= 1.2 else "PHILLIPS"
    mod.wind_velocity = 10.0
    mod.wave_scale = 0.5 * sea_state
    mod.wave_scale_min = 0.01
    mod.choppiness = min(1.6, 0.6 + 0.35 * sea_state)
    mod.wave_alignment = 0.35
    mod.wave_direction = 1.22
    mod.damping = 0.5
    mod.depth = 200.0
    mod.random_seed = 7
    mod.use_normals = True
    mod.use_foam = True
    mod.foam_layer_name = "foam"
    mod.foam_coverage = 0.25 + 0.15 * sea_state


def water_material(name, has_foam=True):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nb = NB(m.node_tree)
    nb.n.clear()
    out = nb.node("ShaderNodeOutputMaterial")
    tc = nb.node("ShaderNodeTexCoord")
    # micro ripples break the moon glitter into sparkles
    rip = nb.node("ShaderNodeTexNoise", {"Vector": tc.outputs["Object"], "Scale": 1.3, "Detail": 8.0, "Roughness": 0.6})
    bump = nb.node("ShaderNodeBump", {"Strength": 0.25, "Distance": 0.1, "Height": rip.outputs["Fac"]})
    water = nb.node("ShaderNodeBsdfPrincipled", {
        "Base Color": rgba((0.003, 0.008, 0.016)), "Roughness": 0.035, "IOR": 1.333, "Normal": bump.outputs[0],
        "Subsurface Weight": 0.0,
    })
    shader = water.outputs[0]
    if has_foam:
        att = nb.node("ShaderNodeAttribute", attribute_name="foam", attribute_type="GEOMETRY")
        ramp = nb.node("ShaderNodeMapRange", {"Value": att.outputs["Fac"], "From Min": 0.35, "From Max": 0.95})
        lace = nb.node("ShaderNodeTexNoise", {"Vector": tc.outputs["Object"], "Scale": 0.9, "Detail": 4.0})
        lacem = nb.node("ShaderNodeMapRange", {"Value": lace.outputs["Fac"], "From Min": 0.4, "From Max": 0.6})
        fac = nb.math("MULTIPLY", ramp.outputs[0], lacem.outputs[0])
        foam = nb.node("ShaderNodeBsdfPrincipled", {"Base Color": rgba((0.55, 0.6, 0.7)), "Roughness": 0.9})
        mx = nb.node("ShaderNodeMixShader")
        nb.link(nb.math("MULTIPLY", fac, 0.85), mx.inputs[0])
        nb.link(shader, mx.inputs[1])
        nb.link(foam.outputs[0], mx.inputs[2])
        shader = mx.outputs[0]
    nb.link(shader, out.inputs["Surface"])
    return m


def build_ocean(center3, sea_state, res, frames, fps, repeat):
    """Returns (ocean object, probe object). The probe is a 3x3 copy (not rendered) used for buoyancy."""
    L = OCEAN_TILE
    # snap so the wave pattern is fixed in world space wherever the boat is
    cx = round(center3[0] / L) * L
    cz = round(center3[2] / L) * L
    mat = oceanfx.water_material("Water")  # yachtsea hook (was water_material("Water"))
    objs = []
    for name, rep in (("Ocean", repeat), ("OceanProbe", 3)):
        me = bpy.data.meshes.new(name)
        ob = bpy.data.objects.new(name, me)
        link_obj(ob)
        mod = ob.modifiers.new("ocean", "OCEAN")
        ocean_params(mod, sea_state, res)
        oceanfx.tune_modifier(mod, sea_state)  # yachtsea hook
        mod.repeat_x = rep
        mod.repeat_y = rep
        # GENERATE grid spans [-L/2, L/2 + (rep-1)L]; shift so it is centred on (cx, cz)
        half = (rep - 1) / 2 * L
        ob.location = Vector((cx - half, -cz - half, 0))
        me.materials.append(mat)
        objs.append(ob)
    ocean, probe = objs
    probe.hide_render = True
    probe.hide_viewport = False
    f0, f1 = frames[0] - 2, frames[-1] + 2
    mod = ocean.modifiers["ocean"]
    key_value(mod, "time", [(f0, f0 / fps), (f1, f1 / fps)])
    oceanfx.add_whitecap_layer(ocean, sea_state, frames, fps)  # yachtsea hook
    # horizon: a flat frame of water around the tiles out to 30 km
    ext = repeat * L / 2 - 1.0
    R = 30000.0
    c = Vector((cx, -cz, 0.0))
    vs = [c + Vector(v) for v in ((-R, -R, 0), (R, -R, 0), (R, R, 0), (-R, R, 0), (-ext, -ext, 0), (ext, -ext, 0), (ext, ext, 0), (-ext, ext, 0))]
    faces = [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    hm = oceanfx.water_material("WaterFar", has_foam=False)  # yachtsea hook
    horizon = mesh_obj("OceanHorizon", vs, faces, hm)
    oceanfx.key_time(frames, fps)  # yachtsea hook: shader clock
    return ocean, probe, (cx, cz)


class Buoyancy:
    """Sea height at world (x, z) [spec coords] and time t, sampled from the probe ocean."""

    def __init__(self, probe, tile_center):
        self.probe = probe
        self.mod = probe.modifiers["ocean"]
        self.cx, self.cz = tile_center
        self.cache = {}

    def _bvh(self, t):
        key = round(t, 5)
        if key in self.cache:
            return self.cache[key]
        self.mod.time = t
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        ev = self.probe.evaluated_get(dg)
        me = ev.to_mesh()
        verts = [v.co.copy() for v in me.vertices]
        polys = [tuple(p.vertices) for p in me.polygons]
        ev.to_mesh_clear()
        bvh = BVHTree.FromPolygons(verts, polys)
        if len(self.cache) > 400:
            self.cache.clear()
        self.cache[key] = bvh
        return bvh

    def height(self, t, x, z):
        L = OCEAN_TILE
        bvh = self._bvh(t)
        # wrap into the central tile of the 3x3 probe (probe-local coords; centre tile spans [L/2, 3L/2]... )
        bx, by = x - self.cx, -z + self.cz  # blender xy relative to the tile centre
        bx = ((bx + L / 2) % L) - L / 2
        by = ((by + L / 2) % L) - L / 2
        # probe object local origin is at tile-centre - L (it was shifted by -half = -L)
        lx, ly = bx + L, by + L
        hit = bvh.ray_cast(Vector((lx, ly, 50.0)), Vector((0, 0, -1)), 200.0)
        if hit[0] is None:
            return 0.0
        return hit[0].z

    def pose(self, t, x, z, heading):
        """port of yacht3d.yachtPose: heave y, pitch, roll (radians)"""
        fx, fz = math.sin(heading), math.cos(heading)
        sx, sz = fz, -fx

        def H(tt, f, s):
            return self.height(tt, x + fx * f + sx * s, z + fz * f + sz * s)
        y = pitch = roll = wsum = 0.0
        for k in range(6):
            tt = t - k * 0.12
            w = math.exp(-k * 0.45)
            bow, stn, prt, stb, mid = H(tt, 5, 0), H(tt, -5, 0), H(tt, 0, -2), H(tt, 0, 2), H(tt, 0, 0)
            y += w * (mid * 2 + bow + stn + prt + stb) / 6
            pitch += w * math.atan2(bow - stn, 10) * 0.85
            roll += w * math.atan2(prt - stb, 4) * 0.5
            wsum += w
        return y / wsum - 0.05, pitch / wsum, roll / wsum


# ---------------- yacht ----------------
LOA = 14.0
Z0 = -LOA / 2


def beam_at(t):
    b = 2.15
    bow = ((t - 0.62) / 0.38) ** 1.7 if t > 0.62 else 0
    stern = 0.94 + 0.06 * (t / 0.06) if t < 0.06 else 1
    return b * stern * (1 - bow * 0.985)


def sheer_at(t):
    return 1.35 + 0.55 * t ** 2.2


def keel_at(t):
    return -0.95 + 0.25 * t ** 3 + ((t - 0.9) * 6.5 if t > 0.9 else 0)


def deadrise(t):
    return 0.32 + 0.45 * t


def build_placeholder_yacht(root):
    """A 14 m motor yacht from the same hull lines as studio/src/kit/yacht3d.ts (simplified)."""
    white = principled_mat("YachtGelcoat", (0.85, 0.86, 0.88), 0.35)
    navy = principled_mat("YachtBoot", (0.04, 0.07, 0.16), 0.4)
    teak = principled_mat("YachtTeak", (0.3, 0.2, 0.12), 0.7)
    glass = principled_mat("YachtGlass", (0.02, 0.025, 0.03), 0.08, emit=(1.0, 0.72, 0.4), emit_strength=3.0)
    steel = principled_mat("YachtSteel", (0.7, 0.72, 0.75), 0.25, metal=1.0)
    NST, NSEC = 36, 10
    verts, faces = [], []
    rows = []
    for i in range(NST + 1):
        t = i / NST
        hb, top, keel = beam_at(t), sheer_at(t), keel_at(t)
        chine = keel + (top - keel) * 0.32
        row = []
        for side in (-1, 1):
            pts = []
            for j in range(NSEC + 1):
                u = j / NSEC
                if u < 0.45:
                    s = u / 0.45
                    x = hb * 0.92 * s
                    y = keel + (chine - keel) * (s * (1 - deadrise(t)) + deadrise(t) * s * s)
                else:
                    s = (u - 0.45) / 0.55
                    x = hb * (0.92 + 0.08 * math.sin(s * math.pi * 0.5)) + 0.04 * math.sin(s * math.pi)
                    y = chine + (top - chine) * s
                pts.append((side * x, y, Z0 + t * LOA))
            row.append(pts)
        # one ring: port sheer -> keel -> starboard sheer
        ring = list(reversed(row[0])) + row[1][1:]
        rows.append(len(verts))
        verts.extend(ring)
    n = 2 * NSEC + 1
    for i in range(NST):
        a, b = rows[i], rows[i + 1]
        for j in range(n - 1):
            faces.append((a + j, a + j + 1, b + j + 1, b + j))
    # transom + deck caps
    faces.append(tuple(rows[0] + j for j in range(n)))
    deck = [rows[i] for i in range(NST + 1)] + [rows[i] + n - 1 for i in range(NST, -1, -1)]
    faces.append(tuple(deck))
    hull = mesh_obj("yacht_hull", [b3(v) for v in verts], faces, white, root, smooth=True)
    hull.data.materials.append(navy)
    for p in hull.data.polygons:  # boot stripe / antifouling below the waterline
        if p.center.z < 0.12 and len(p.vertices) == 4:
            p.material_index = 1
    box("yacht_cabin", (0, 2.3, -1.2), (3.3, 1.0, 5.6), white, root)
    box("yacht_windows", (0, 2.45, -1.0), (3.36, 0.45, 5.2), glass, root)
    box("yacht_flybridge", (0, 3.0, -2.2), (3.0, 0.35, 4.6), white, root)
    box("yacht_cockpit", (0, 1.38, -5.4), (3.8, 0.08, 2.6), teak, root)
    box("yacht_platform", (0, 0.45, Z0 - 0.42), (4.0, 0.12, 0.9), teak, root)
    box("yacht_mast", (0, 4.6, -1.9), (0.08, 2.6, 0.08), steel, root)
    # foredeck hatch on a hinge
    hz = Z0 + 0.78 * LOA - 0.35
    pivot = new_empty("hatch_pivot", root)
    pivot.location = b3((0, sheer_at(0.78) + 0.05, hz))
    lid = box("hatch_lid", (0, 0, 0.35), (0.7, 0.06, 0.7), white, pivot)
    # nav + cabin lights (GLB convention: lights-on values; multiplied by yacht.lights)
    lights = []
    for nm, pos, col in (("nav_port", (-1.62, 2.3, 2.6), (1, 0.16, 0.1)), ("nav_stbd", (1.62, 2.3, 2.6), (0.1, 1, 0.35)),
                         ("nav_mast", (0, 6.32, -1.9), (1, 1, 1)), ("nav_stern", (0, 1.5, Z0 - 0.02), (1, 1, 1))):
        m, _ = emission_mat(nm + "_mat", col, 25.0)
        sphere(nm, pos, 0.07, m, root)
        lights.append(point_light(nm + "_light", pos, col, 3.0, 0.05, root))
    lights.append(point_light("cabin_light", (0, 2.4, -0.5), (1.0, 0.72, 0.4), 60.0, 0.3, root))
    return pivot


def collect_light_targets(objs):
    """lights and emissive materials under the yacht, with their lights-on base values."""
    lights, emits = [], []
    seen = set()
    for ob in objs:
        if ob.type == "LIGHT":
            lights.append((ob.data, ob.data.energy))
        for slot in getattr(ob, "material_slots", []):
            m = slot.material
            if not m or m.name in seen or not m.use_nodes:
                continue
            seen.add(m.name)
            for nd in m.node_tree.nodes:
                if nd.type == "BSDF_PRINCIPLED" and nd.inputs["Emission Strength"].default_value > 0 and any(c > 0 for c in nd.inputs["Emission Color"].default_value[:3]):
                    emits.append((nd.inputs["Emission Strength"], nd.inputs["Emission Strength"].default_value))
                elif nd.type == "EMISSION":
                    emits.append((nd.inputs["Strength"], nd.inputs["Strength"].default_value))
    return lights, emits


def import_glb(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    # importer bone-shape helpers are not linked to the scene; drop them
    for o in list(new):
        if not o.users_collection:
            bpy.data.objects.remove(o)
            new.remove(o)
    return new


def roots_of(objs):
    s = set(objs)
    return [o for o in objs if o.parent not in s]


# ---------------- island ----------------
def coast_from_geo():
    for p in (os.path.join(ROOT, "assets", "props", "island_sentinel_geo.json"),
              os.path.join(ROOT, "studio", "src", "data", "sentinel_geo.json")):
        if os.path.exists(p):
            with open(p) as fh:
                d = json.load(fh)
            if d.get("coast"):
                return d["coast"]
    return None


def build_placeholder_island(scale):
    """Terrain from the OSM coastline (km) if available, else a disc; domed rings to a ridge."""
    coast = coast_from_geo()
    S = scale * 1000.0
    if coast:
        pts = [(x * S, y * S) for x, y in coast]  # x east, y south == spec +z
        if len(pts) > 160:
            step = len(pts) / 160.0
            pts = [pts[int(i * step)] for i in range(160)]
    else:
        warn("island: no GLB and no coastline data; using a disc")
        pts = [(math.cos(a) * 3500 * scale, math.sin(a) * 3500 * scale) for a in (i / 96 * 2 * math.pi for i in range(96))]
    cxm = sum(p[0] for p in pts) / len(pts)
    czm = sum(p[1] for p in pts) / len(pts)
    hs = max(scale, 0.05) ** 0.5
    rings = ((1.03, -1.5), (1.0, 0.6), (0.975, 2.5), (0.95, 9 * hs), (0.85, 30 * hs), (0.65, 55 * hs), (0.4, 70 * hs), (0.15, 78 * hs))
    verts, faces = [], []
    n = len(pts)
    for k, (s, h) in enumerate(rings):
        for (x, z) in pts:
            verts.append(b3((cxm + (x - cxm) * s, h, czm + (z - czm) * s)))
    for k in range(len(rings) - 1):
        for i in range(n):
            a, b = k * n + i, k * n + (i + 1) % n
            faces.append((a, b, b + n, a + n))
    verts.append(b3((cxm, 82 * hs, czm)))
    top = len(verts) - 1
    last = (len(rings) - 1) * n
    for i in range(n):
        faces.append((last + i, last + (i + 1) % n, top))
    m = bpy.data.materials.new("IslandGround")
    m.use_nodes = True
    nb = NB(m.node_tree)
    bsdf = nb.n.get("Principled BSDF")
    geo = nb.node("ShaderNodeNewGeometry")
    sep = nb.node("ShaderNodeSeparateXYZ", {"Vector": geo.outputs["Position"]})
    beach = nb.node("ShaderNodeMapRange", {"Value": sep.outputs["Z"], "From Min": 1.5, "From Max": 4.0})
    noise = nb.node("ShaderNodeTexNoise", {"Vector": geo.outputs["Position"], "Scale": 0.04, "Detail": 6.0})
    forest = nb.mix(rgba((0.012, 0.03, 0.015)), rgba((0.03, 0.05, 0.025)), noise.outputs["Fac"])
    col = nb.mix(rgba((0.35, 0.33, 0.27)), forest, beach.outputs[0])
    nb.link(col, bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.95
    bump = nb.node("ShaderNodeBump", {"Strength": 0.6, "Height": noise.outputs["Fac"], "Distance": 3.0})
    nb.link(bump.outputs[0], bsdf.inputs["Normal"])
    ob = mesh_obj("island_placeholder", verts, faces, m, smooth=True)
    # fires along the tree line (indices like island3d.ts)
    fire_pos = []
    for i in range(6):
        x, z = pts[int((0.08 + i * 0.045) * n) % n]
        fire_pos.append((cxm + (x - cxm) * 0.94, 4.0, czm + (z - czm) * 0.94))
    return ob, fire_pos



LIB_STORE = os.environ.get("LIBRARY_STORE") or None


def lib_path(rel):
    base = LIB_STORE or os.path.join(ROOT, "library_store")
    p = os.path.join(base, rel)
    return p if os.path.exists(p) else None


def lib_collection(asset_id, rel):
    """Import a library glTF once into a hidden collection for instancing; returns (collection, height_m)."""
    name = "LIB_" + asset_id
    if name in bpy.data.collections:
        c = bpy.data.collections[name]
        return c, c.get("height", 1.0)
    path = lib_path(rel)
    if not path:
        warn(f"library asset {asset_id} missing ({rel})")
        return None, 0
    objs = import_glb(path)
    c = bpy.data.collections.new(name)
    for o in objs:
        for uc in list(o.users_collection):
            uc.objects.unlink(o)
        c.objects.link(o)
    bpy.context.view_layer.update()
    zs = [(o.matrix_world @ Vector(v)).z for o in objs if o.type == "MESH" for v in o.bound_box]
    h = (max(zs) - min(zs)) if zs else 1.0
    c["height"] = h
    return c, h


def _inst(coll, parent, loc_spec, yaw, scale, name):
    e = bpy.data.objects.new(name, None)
    e.instance_type, e.instance_collection = "COLLECTION", coll
    link_obj(e)
    e.parent = parent
    e.matrix_basis = obj_mat(trans(loc_spec) @ rot_y(yaw)) @ Matrix.Scale(scale, 4)
    return e


def dress_island(root, isl, objs):
    """Replace stand-in vegetation with real CC0 library assets (Poly Haven): rows of tropical trees behind the
    beach, shrubs/ferns at the treeline, coast rocks along the waterline. Deterministic (seeded by index)."""
    for o in objs:
        if o.name.startswith("palm_"):
            o.hide_render = True
    try:
        geo = json.load(open(os.path.join(ROOT, "studio/src/data/sentinel_geo.json")))
    except Exception as e:
        warn(f"no coastline for dressing: {e}")
        return
    S = isl.get("scale", 1) * 1000.0
    coast = [(x * S, y * S) for x, y in geo["coast"]]
    trees = [lib_collection(f"island_tree_0{i}", f"polyhaven/island_tree_0{i}/island_tree_0{i}_1k.gltf") for i in (1, 2, 3)]
    trees = [t for t in trees if t[0]]
    rocks = [lib_collection(n, f"polyhaven/{n}/{n}_1k.gltf") for n in ("coast_rocks_01", "coast_rocks_03", "coast_land_rocks_02")]
    rocks = [r for r in rocks if r[0]]
    under = [lib_collection(n, f"polyhaven/{n}/{n}_1k.gltf") for n in ("shrub_01", "fern_02")]
    under = [u for u in under if u[0]]
    if not trees:
        return
    hsh = lambda n: (math.sin(n * 127.1 + 311.7) * 43758.5453) % 1.0
    # resample the coast at even spacing
    def walk(step):
        pts = []
        acc = 0.0
        for i in range(len(coast)):
            a, b = coast[i], coast[(i + 1) % len(coast)]
            seg = math.hypot(b[0] - a[0], b[1] - a[1])
            t = (step - acc) / seg if seg else 1
            while t <= 1.0:
                pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
                t += step / seg
            acc = (acc + seg) % step
        return pts
    n = 0
    for row, (shrink, step, base_h) in enumerate(((0.982, 7.0, 3.0), (0.968, 9.0, 3.6), (0.95, 12.0, 4.5), (0.92, 16.0, 6.0))):
        for j, (x, y) in enumerate(walk(step)):
            k = n * 1.37 + row * 91.1
            jit = (hsh(k) - 0.5) * step * 0.6
            px, py = x * shrink + jit * 0.3, y * shrink + jit * 0.3
            coll, h = trees[int(hsh(k + 3) * len(trees)) % len(trees)]
            target_h = 13.0 + hsh(k + 5) * 9.0 + row * 2.0
            _inst(coll, root, (px, base_h, py), hsh(k + 7) * 6.283, target_h / max(0.1, h), f"tree_{n}")
            n += 1
            if under and row < 2 and hsh(k + 11) < 0.6:
                uc, uh = under[int(hsh(k + 13) * len(under)) % len(under)]
                _inst(uc, root, (x * (shrink + 0.004), base_h, y * (shrink + 0.004)), hsh(k + 17) * 6.283, (1.6 + hsh(k + 19) * 1.4) / max(0.1, uh), f"under_{n}")
    if rocks:
        for j, (x, y) in enumerate(walk(22.0)):
            k = j * 2.71 + 500
            if hsh(k) < 0.45:
                continue
            rc, rh = rocks[int(hsh(k + 1) * len(rocks)) % len(rocks)]
            _inst(rc, root, (x * 1.004, 0.0, y * 1.004), hsh(k + 2) * 6.283, (1.6 + hsh(k + 3) * 2.5) / max(0.1, rh), f"rock_{j}")
    log(f"island dressed: {n} trees + understorey + rocks from the library")


def build_island(isl, frames, fires_keys, fps):
    if not isl:
        return
    key = isl.get("asset")
    path = None
    props = SPEC["assets"].get("props", {})
    if key in props:
        path = resolve(props[key])
    elif key and key.endswith(".glb"):
        path = resolve(key)
    root = new_empty("IslandRoot")
    root.matrix_world = obj_mat(trans((isl["x"], 0, isl["z"])) @ rot_y(isl.get("rotY", 0)))
    fire_lights, fire_meshes = [None] * 6, [None] * 6
    if path:
        objs = import_glb(path)
        sub = new_empty("IslandScale", root)
        sub.scale = (isl.get("scale", 1),) * 3
        for o in roots_of(objs):
            o.parent = sub
        for o in objs:
            for i in range(6):
                if o.name.startswith(f"fire_light_{i}") and o.type == "LIGHT":
                    fire_lights[i] = o
                elif o.name.startswith(f"fire_{i}") and o.type == "MESH":
                    fire_meshes[i] = o
        dress_island(root, isl, objs)
    else:
        warn(f"island asset '{key}' not found; building a placeholder")
        ob, fpos = build_placeholder_island(isl.get("scale", 1))
        ob.parent = root
        fm, _ = emission_mat("Flame", (1.0, 0.55, 0.2), 30.0)
        for i, p in enumerate(fpos):
            fire_lights[i] = point_light(f"fire_light_{i}", (p[0], p[1] + 3, p[2]), (1.0, 0.54, 0.19), 0.0, 1.0, root)
            cone = sphere(f"fire_{i}", (p[0], p[1] + 1.8, p[2]), 1.2, fm, root)
            fire_meshes[i] = cone
    # fire flicker keys (pure function of the frame)
    base = {}
    for i, lo in enumerate(fire_lights):
        if lo is not None:
            base[i] = lo.data.energy if lo.data.energy > 0 else 2.0e5
    for f in range(frames[0] - 1, frames[-1] + 2):
        vals = keyed_vec(fires_keys, f, 6) if fires_keys else [0.0] * 6
        t = f / fps
        for i in range(6):
            fl = 0.75 + 0.25 * math.sin(t * 13.0 + i * 1.7) * math.sin(t * 7.3 + i * 2.9)
            v = max(0.0, vals[i]) * fl
            lo = fire_lights[i]
            if lo is not None:
                lo.data.energy = base[i] * v
                lo.data.keyframe_insert("energy", frame=f)
            fm = fire_meshes[i]
            if fm is not None:
                s = max(0.001, v)
                fm.scale = (s * 5.0, s * 5.0, s * 5.0 * (0.6 + 0.4 * fl))  # readable at 150-300 m (camera review: fires were sub-pixel)
                fm.keyframe_insert("scale", frame=f)
                fm.hide_render = v < 0.02
                fm.keyframe_insert("hide_render", frame=f)
    for lo in fire_lights:
        if lo is not None:
            set_linear(lo.data)


# ---------------- characters ----------------
ACTION_CACHE = {}


def norm_bone(n):
    n = n.lower().split(":")[-1].replace("mixamorig", "")
    return "".join(ch for ch in n if ch.isalnum())


def load_motion(clip):
    if clip in ACTION_CACHE:
        return ACTION_CACHE[clip]
    key = SPEC["assets"]["motions"].get(clip, f"assets/motions/{clip}.glb")
    path = resolve(key)
    if not path:
        warn(f"motion '{clip}' not found ({key}); track skipped")
        ACTION_CACHE[clip] = None
        return None
    acts_before = set(bpy.data.actions)
    objs = import_glb(path)
    acts = [a for a in bpy.data.actions if a not in acts_before]
    act = None
    for o in objs:
        if o.type == "ARMATURE" and o.animation_data and o.animation_data.action:
            act = o.animation_data.action
    if act is None and acts:
        act = max(acts, key=lambda a: len(a.fcurves))
    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)
    if act is None:
        warn(f"motion '{clip}' has no action")
    else:
        act.name = "motion_" + clip
        act.use_fake_user = True
    ACTION_CACHE[clip] = act
    return act


def retarget(action, arm):
    """Return an action whose bone paths match `arm` by (normalised) bone name."""
    names = {b.name for b in arm.data.bones}
    lookup = {norm_bone(n): n for n in names}
    missing = 0
    ok = True
    for fc in action.fcurves:
        if fc.data_path.startswith('pose.bones["'):
            bn = fc.data_path.split('"')[1]
            if bn not in names:
                ok = False
                break
    if ok:
        return action
    new = action.copy()
    new.name = action.name + "_rt_" + arm.name
    for fc in list(new.fcurves):
        if not fc.data_path.startswith('pose.bones["'):
            continue
        bn = fc.data_path.split('"')[1]
        if bn in names:
            continue
        tgt = lookup.get(norm_bone(bn))
        if tgt:
            fc.data_path = fc.data_path.replace(f'"{bn}"', f'"{tgt}"', 1)
        else:
            new.fcurves.remove(fc)
            missing += 1
    if missing:
        warn(f"retarget {action.name} -> {arm.name}: dropped {missing} curves with no matching bone")
    return new


def axis_toward(bone, direction):
    """bone-local axis (as Damped Track enum) that best points along `direction` (armature space) in rest pose."""
    m = bone.matrix_local.to_3x3()
    best, name = -2, "TRACK_Y"
    for i, ax in enumerate("XYZ"):
        d = m.col[i].normalized().dot(direction)
        if d > best:
            best, name = d, f"TRACK_{ax}"
        if -d > best:
            best, name = -d, f"TRACK_NEGATIVE_{ax}"
    return name


ACTORS = {}


def build_actor(idx, a, yacht_root, camera, shot, fps):
    key = SPEC["assets"]["characters"].get(a["asset"], f"assets/characters/{a['asset']}/{a['asset']}.glb")
    path = resolve(key)
    holder = new_empty(f"actor_{idx}_{a['asset']}", yacht_root)
    holder.matrix_parent_inverse = Matrix.Identity(4)
    if not path:
        warn(f"character '{a['asset']}' not found ({key}); using a capsule stand-in")
        m = principled_mat("standin", (0.5, 0.3, 0.2), 0.8)
        box(f"standin_{idx}", (0, 0.9, 0), (0.45, 1.8, 0.3), m, holder)
        holder.matrix_basis = obj_mat(trans(a["local"]) @ rot_y(a.get("rotY", 0)))
        return
    objs = import_glb(path)
    arm = next((o for o in objs if o.type == "ARMATURE"), None)
    for o in roots_of(objs):
        o.parent = holder
    for o in objs:
        if o.type == "MESH":
            for slot in o.material_slots:  # generated PBR comes out glossy: fabric and skin are matte
                m = slot.material
                if m and m.use_nodes:
                    for nd in m.node_tree.nodes:
                        if nd.type == "BSDF_PRINCIPLED":
                            for l in list(nd.inputs["Metallic"].links) + list(nd.inputs["Roughness"].links):
                                m.node_tree.links.remove(l)
                            nd.inputs["Metallic"].default_value = 0.0
                            nd.inputs["Roughness"].default_value = max(nd.inputs["Roughness"].default_value, 0.78)
    # height from the skeleton (head_end -> toes), scale to a.height (default 1.8 m like the 3D kit)
    sc = 1.0
    if arm:
        bpy.context.view_layer.update()
        top = max((arm.matrix_world @ b.head_local).z for b in arm.data.bones) if arm.data.bones else 1.8
        feet = [(arm.matrix_world @ b.head_local).z for b in arm.data.bones if "toe" in b.name.lower() or "foot" in b.name.lower()]
        hts = [(arm.matrix_world @ b.head_local).z for b in arm.data.bones if "head_end" in b.name.lower() or "headtop" in b.name.lower()]
        if hts:
            top = max(hts)
        bottom = min(feet) if feet else 0.0
        h = (top - bottom) * 1.04 if top > bottom else 1.8
        sc = float(a.get("height", 1.8)) / h
    perf = a.get("perf")
    pup = None
    if arm and perf:
        if arm.animation_data:
            arm.animation_data.action = None
        bpy.context.view_layer.update()
        pup = acting.Puppet(arm, holder)
    holder.matrix_basis = obj_mat(trans(a["local"]) @ rot_y(a.get("rotY", 0))) @ Matrix.Scale(sc, 4)
    if not arm:
        warn(f"character '{a['asset']}' has no armature; tracks ignored")
        return None
    if pup is not None:
        pup.bake(perf, shot["from"] - 1, shot["to"] + 1)
        # >>> lighting hook: sequence rig hero lights (world-direction face fill, rim cheat, eye light)
        if lighting.active():
            lighting.build_hero_rig(idx, holder, arm, a, camera, shot)
            ACTORS[a.get("name", "hero")] = arm
            return arm
        # <<< lighting hook (legacy rig below)
        # GAFFER 'moonlight portrait' preset: cool soft key front-left-high, strong rim behind, faint warm bounce.
        # Parented to the hero so his face always reads against the night sea, whatever the camera does.
        aimt = bpy.data.objects.new(f"aim_{idx}", None)
        link_obj(aimt)
        aimt.parent = holder
        aimt.location = (0, 0, 1.35)
        rig = a.get("lightRig", {})
        for nm, loc, energy, size, col in (
            ("key", (0.9, -1.7, 2.3), rig.get("key", 30.0), 1.6, (0.72, 0.82, 1.0)),
            ("rim", (-0.9, 1.5, 2.1), rig.get("rim", 110.0), 0.8, (0.62, 0.74, 1.0)),
            ("bounce", (0.0, -1.2, 0.3), rig.get("bounce", 3.0), 2.0, (0.55, 0.62, 0.8)),
        ):
            ld = bpy.data.lights.new(f"hero_{nm}_{idx}", "AREA")
            ld.energy, ld.size, ld.color = energy, size, col
            lo = bpy.data.objects.new(f"hero_{nm}_{idx}", ld)
            link_obj(lo)
            lo.parent = holder
            lo.location = loc
            c = lo.constraints.new("TRACK_TO")
            c.target, c.track_axis, c.up_axis = aimt, "TRACK_NEGATIVE_Z", "UP_Y"
        ACTORS[a.get("name", "hero")] = arm
        return arm
    if arm.animation_data:
        arm.animation_data.action = None
    else:
        arm.animation_data_create()
    ad = arm.animation_data
    ad.action = None
    shot_end = shot["to"] + 2
    for ti, tr in enumerate(a["tracks"]):
        act = load_motion(tr["clip"])
        if act is None:
            continue
        act = retarget(act, arm)
        nt = ad.nla_tracks.new()
        nt.name = f"{ti}_{tr['clip']}"
        f0 = tr["from"]
        st = nt.strips.new(tr["clip"], int(math.floor(f0)), act)
        a0, a1 = act.frame_range
        st.action_frame_start, st.action_frame_end = a0, a1
        off = float(tr.get("offset", 0) or 0)
        if off:
            st.action_frame_start = a0 + off
        speed = float(tr.get("speed", 1) or 1)
        st.scale = 1.0 / speed
        length = (st.action_frame_end - st.action_frame_start) / speed
        if tr.get("loop", True) is not False and length > 0:
            st.repeat = max(1.0, math.ceil((shot_end - f0) / length) + 1)
        st.blend_type = "REPLACE"
        st.extrapolation = "HOLD_FORWARD" if ti > 0 else "HOLD"
        fade = tr.get("fade", 8 if ti > 0 else 0)
        st.use_auto_blend = False
        st.blend_in = min(float(fade or 0), max(0.0, st.frame_end - st.frame_start - 1))
    # head aim
    look = a.get("lookAt")
    if look is not None:
        if look == "camera":
            target = camera
        else:
            target = new_empty(f"look_{idx}", yacht_root)
            target.location = b3(look)
        head = next((b for b in arm.pose.bones if norm_bone(b.name) == "head"), None)
        neck = next((b for b in arm.pose.bones if norm_bone(b.name) == "neck"), None)
        fwd = Vector((0, -1, 0))  # glTF +z (character front) in Blender armature space
        for pb, share in ((neck, 0.35), (head, 0.6)):
            if pb is None:
                continue
            c = pb.constraints.new("DAMPED_TRACK")
            c.target = target
            c.track_axis = axis_toward(pb.bone, fwd)
            lw = a.get("lookWeight", 0.8)
            if isinstance(lw, (int, float)):
                c.influence = float(lw) * share
            else:
                for f in range(shot["from"] - 1, shot["to"] + 1):
                    c.influence = keyed(lw, f, 0.8) * share
                    c.keyframe_insert("influence", frame=f)


# ---------------- render settings ----------------

BONE_OF = {"handR": "RightHand", "handL": "LeftHand", "head": "Head", "chest": "Spine"}


def _hide_keys(root, show_keys, f0, f1):
    objs = [root] + list(root.children_recursive)
    for f in range(f0, f1 + 1):
        vis = keyed(show_keys, f, 1.0) > 0.5
        for o in objs:
            o.hide_render = not vis
            o.hide_viewport = not vis
            o.keyframe_insert("hide_render", frame=f)


def build_props(shot, yacht_root, frames):
    """shot.props: [{prop, attach: 'yacht'|'handR'|'handL'|'world', local, rot (deg xyz) | rotY, scale, show: keys,
    strobe: f_on, light: keys (0..1 lamp/gauge/led intensity)}]"""
    f0, f1 = frames[0] - 1, frames[-1] + 1
    for i, p in enumerate(shot.get("props") or []):
        b = propkit.BUILDERS.get(p["prop"])
        vb = vehicles.BUILDERS.get(p["prop"])  # props2 hook: vehicle / set builders take opts
        if not b and not vb:
            warn(f"unknown prop {p['prop']}")
            continue
        root = b(f"{p['prop']}_{i}") if b else vb(f"{p['prop']}_{i}", **(p.get("opts") or {}))
        att = p.get("attach", "yacht")
        if att in BONE_OF:
            arm = ACTORS.get(p.get("actor", "hero"))
            if arm is None:
                warn(f"prop {p['prop']}: no actor to attach to")
                continue
            root.parent = arm
            root.parent_type = "BONE"
            root.parent_bone = next((bn.name for bn in arm.data.bones if bn.name.lower() == BONE_OF[att].lower()), BONE_OF[att])
            root.matrix_parent_inverse = Matrix.Identity(4)
            s_arm = arm.matrix_world.to_scale()[0] or 1.0
            root.location = Vector(p.get("local", (0, 0, 0))) / s_arm
            r = p.get("rot", (0, 0, 0))
            root.rotation_euler = tuple(math.radians(x) for x in r)
            root.scale = (p.get("scale", 1.0) / s_arm,) * 3
        else:
            if att == "yacht" and yacht_root is not None:
                root.parent = yacht_root
            root.matrix_basis = obj_mat(trans(p.get("local", (0, 0, 0))) @ rot_y(p.get("rotY", 0.0))) @ Matrix.Scale(p.get("scale", 1.0), 4)
        if p.get("show") is not None:
            _hide_keys(root, p["show"], f0, f1)
        kids = list(root.children_recursive)
        if p.get("strobe") is not None:
            for o in kids:
                if o.type == "LIGHT":
                    for f in range(f0, f1 + 1):
                        on = f >= p["strobe"] and ((f - p["strobe"]) % 24) < 2
                        o.data.energy = 40.0 if on else 0.0
                        o.data.keyframe_insert("energy", frame=f)
                for slot in getattr(o, "material_slots", []):
                    m = slot.material
                    if m and m.name.startswith("epirb_dome"):
                        m = m.copy(); slot.material = m
                        nd = m.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"]
                        for f in range(f0, f1 + 1):
                            on = f >= p["strobe"] and ((f - p["strobe"]) % 24) < 2
                            nd.default_value = 60.0 if on else 0.0
                            nd.keyframe_insert("default_value", frame=f)
        if p.get("light") is not None:
            for o in kids:
                if o.type == "LIGHT":
                    base = o.data.energy
                    for f in range(f0, f1 + 1):
                        o.data.energy = base * keyed(p["light"], f, 1.0)
                        o.data.keyframe_insert("energy", frame=f)
                for slot in getattr(o, "material_slots", []):
                    m = slot.material
                    if m and m.node_tree and m.node_tree.nodes.get("Principled BSDF"):
                        es = m.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"]
                        if es.default_value > 0 or m.name.startswith(("helm_gauge", "panel_led")):
                            base = es.default_value or 5.0
                            m = m.copy(); slot.material = m
                            es = m.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"]
                            for f in range(f0, f1 + 1):
                                es.default_value = base * keyed(p["light"], f, 1.0)
                                es.keyframe_insert("default_value", frame=f)
        if vb:  # props2 hook: rotors, path/yaw/tilt/rock, lamp swing, winch, flicker
            vehicles.post_place(root, p, f0, f1, SPEC.get("fps", 30))


def egl_available():
    for lib in ("libEGL.so.1", "libEGL.so"):
        try:
            ctypes.CDLL(lib)
            return True
        except OSError:
            pass
    return sys.platform in ("darwin", "win32")


def setup_cycles_device(scene):
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except KeyError:
        return "CPU"
    for typ in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
        try:
            prefs.compute_device_type = typ
            prefs.get_devices()
        except Exception:
            continue
        devs = [d for d in prefs.devices if d.type == typ]
        if devs:
            for d in prefs.devices:
                d.use = d.type == typ
            scene.cycles.device = "GPU"
            return typ
    scene.cycles.device = "CPU"
    return "CPU"


def setup_render(args, spec):
    sc = bpy.context.scene
    engine = args.engine
    if engine == "EEVEE" and bpy.app.background and not egl_available():
        if args.strict_engine:
            raise SystemExit("EEVEE needs a GPU/EGL context and none is available (use --engine CYCLES)")
        warn("EEVEE requested but no EGL/GPU context here; falling back to Cycles")
        engine = "CYCLES"
    W, H = spec.get("width", 1080), spec.get("height", 1920)
    if args.res:
        W, H = (int(x) for x in args.res.lower().split("x"))
    elif args.quality == "preview":
        W, H = W // 2, H // 2
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
    sc.render.fps = spec.get("fps", 30)
    sc.render.fps_base = 1.0
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.image_settings.color_depth = "8"
    sc.render.image_settings.compression = 15
    sc.render.film_transparent = False
    sc.render.use_motion_blur = not args.no_motion_blur
    sc.render.motion_blur_shutter = 0.5
    if args.threads:
        sc.render.threads_mode = "FIXED"
        sc.render.threads = args.threads
    device = "GPU"
    if engine == "CYCLES":
        sc.render.engine = "CYCLES"
        device = setup_cycles_device(sc)
        sc.cycles.samples = args.samples or (128 if args.quality == "final" else 16)
        sc.cycles.use_adaptive_sampling = True
        sc.cycles.adaptive_threshold = 0.02
        sc.cycles.use_denoising = True
        try:
            sc.cycles.denoiser = "OPTIX" if device == "OPTIX" else "OPENIMAGEDENOISE"
        except TypeError:
            pass
        sc.cycles.seed = 0
        sc.cycles.use_animated_seed = True  # deterministic per frame
        sc.cycles.max_bounces = 6 if args.quality == "final" else 3
        sc.cycles.glossy_bounces = 3 if args.quality == "final" else 2
        sc.cycles.transmission_bounces = 4
        sc.cycles.volume_bounces = 0
        sc.cycles.caustics_reflective = False
        sc.cycles.caustics_refractive = False
        sc.cycles.blur_glossy = 1.0
        sc.cycles.sample_clamp_indirect = 10.0
        sc.render.use_persistent_data = True
    else:
        sc.render.engine = "BLENDER_EEVEE_NEXT"
        ee = sc.eevee
        ee.taa_render_samples = args.samples or (64 if args.quality == "final" else 16)
        for attr, val in (("use_raytracing", args.quality == "final"), ("use_shadows", True), ("use_gtao", True),
                          ("shadow_ray_count", 1), ("volumetric_tile_size", "8")):
            try:
                setattr(ee, attr, val)
            except (AttributeError, TypeError):
                pass
    # colour: AgX, punchy-ish night grade
    sty = (spec.get("style") or {}).get("look") or {}  # style system hook (factory/styles): view look + exposure
    vs = sc.view_settings
    try:
        vs.view_transform = sty.get("view_transform", "AgX")
    except TypeError:
        vs.view_transform = "Filmic"
    for look in (sty.get("look", "AgX - Medium High Contrast"), "AgX - Medium High Contrast", "AgX - Base Contrast", "None"):
        try:
            vs.look = look
            break
        except TypeError:
            continue
    vs.exposure = args.exposure if args.exposure is not None else float(sty.get("exposure", 1.0))
    sc.display_settings.display_device = "sRGB"
    # bloom via compositor glare (EEVEE Next has no built-in bloom; same look in Cycles)
    sc.use_nodes = True
    nt = sc.node_tree
    nt.nodes.clear()
    rl = nt.nodes.new("CompositorNodeRLayers")
    gl = nt.nodes.new("CompositorNodeGlare")
    gl.glare_type = "FOG_GLOW"
    gl.quality = "MEDIUM" if args.quality == "final" else "LOW"
    gl.mix = -0.75
    gl.threshold = 0.8
    gl.size = 8 if args.quality == "final" else 7
    comp = nt.nodes.new("CompositorNodeComposite")
    nt.links.new(rl.outputs["Image"], gl.inputs["Image"])
    nt.links.new(gl.outputs["Image"], comp.inputs["Image"])
    return engine, device


# ----------------------------------------------------------------------------------------------
# build one shot
# ----------------------------------------------------------------------------------------------
SPEC = {}


def build_shot(shot, frames, args):
    spec = SPEC
    fps = spec.get("fps", 30)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ACTION_CACHE.clear()
    sc = bpy.context.scene
    sc.render.fps = fps  # before any glTF import, so clip seconds -> frames at 30 fps
    sc.frame_start, sc.frame_end = frames[0], frames[-1]
    engine, device = setup_render(args, spec)
    env = dict(spec["world"])
    env.update(shot.get("env") or {})
    sea = float(env.get("seaState", 1.6))
    lighting.begin_shot(spec, shot, args.lighting)  # lighting hook
    build_world(env, fps, frames, args.haze)

    y = shot.get("yacht")
    centre = (y["x"], 0, y["z"]) if y else (0, 0, 0)
    cam_space = shot["camera"].get("space", "world")
    # tile coverage: more tiles when the camera is far from the boat
    cdist = 0.0
    for k in shot["camera"]["keys"]:
        c = k["cam"] if cam_space == "yacht" else (k["cam"][0] - centre[0], k["cam"][1], k["cam"][2] - centre[2])
        cdist = max(cdist, math.hypot(c[0], c[2]))
    repeat = 9 if cdist < 150 else 13
    ocean_res = args.ocean_res or 10
    ocean, probe, tile_c = build_ocean(centre, sea, ocean_res, frames, fps, repeat)
    buoy = Buoyancy(probe, tile_c)

    # island
    isl = shot["island"] if "island" in shot else env.get("island")
    build_island(isl, frames, shot.get("fires"), fps)
    # >>> yachtsea hook: reef breaking-wave surf in the water shaders
    surf = oceanfx.add_reef_surf()
    if surf:
        log(f"reef surf: {surf}")
    # <<< yachtsea

    # camera object
    camd = bpy.data.cameras.new("Cam")
    camd.sensor_fit = "VERTICAL"
    camd.sensor_height = 24.0
    camd.clip_start = 0.1
    camd.clip_end = 40000.0
    cam = bpy.data.objects.new("Cam", camd)
    link_obj(cam)
    sc.camera = cam
    cam.rotation_mode = "QUATERNION"

    # yacht
    yacht_root = None
    if y:
        yacht_root = new_empty("YachtRoot")
        yacht_root.rotation_mode = "QUATERNION"
        ypath = resolve(spec["assets"].get("props", {}).get("yacht", "assets/props/yacht.glb"))
        hatch = None
        if ypath:
            objs = import_glb(ypath)
            for o in roots_of(objs):
                o.parent = yacht_root
            hatch = next((o for o in objs if o.name.startswith("hatch_pivot")), None)
            yobjs = objs
            # >>> yachtsea hook: PBR yacht materials (before collect_light_targets) + hull/water foam
            done = yachtmats.apply_yacht_materials(objs, store=LIB_STORE or os.path.join(ROOT, "library_store"))
            log(f"yacht materials: {len(done)} restyled; hull foam: {oceanfx.add_hull_foam(yacht_root, objs)}")
            # <<< yachtsea
        else:
            warn("yacht.glb not found; building the code yacht as a placeholder")
            hatch = build_placeholder_yacht(yacht_root)
            yobjs = [o for o in bpy.data.objects if o.parent is yacht_root or (o.parent and o.parent.parent is yacht_root)]
        lights, emits = collect_light_targets(yobjs)
        for ld, base in lights:
            for f in range(frames[0] - 1, frames[-1] + 2):
                ld.energy = base * keyed(y.get("lights"), f, 0.0)
                ld.keyframe_insert("energy", frame=f)
            set_linear(ld)
        for sock, base in emits:
            for f in range(frames[0] - 1, frames[-1] + 2):
                sock.default_value = base * keyed(y.get("lights"), f, 0.0)
                sock.keyframe_insert("default_value", frame=f)
        if hatch is not None:
            hatch.rotation_mode = "XYZ"
            for f in range(frames[0] - 1, frames[-1] + 2):
                hatch.rotation_euler[0] = -keyed(y.get("hatch"), f, 0.0) * 1.9
                hatch.keyframe_insert("rotation_euler", index=0, frame=f)

    ACTORS.clear()
    # actors (parented to the yacht)
    for i, a in enumerate(shot.get("actors") or []):
        if yacht_root is None:
            warn("actor without a yacht in this shot; skipped")
            continue
        build_actor(i, a, yacht_root, cam, shot, fps)

    build_props(shot, yacht_root, frames)

    # per-frame: buoyancy -> yacht matrix; camera rig
    ck = shot["camera"]
    prev_q = {}
    t_b = time.time()
    for f in range(frames[0] - 1, frames[-1] + 2):
        t = f / fps
        ym3 = Matrix.Identity(4)
        heave = 0.0
        if y:
            hy, pitch, roll = buoy.pose(t, y["x"], y["z"], y["heading"])
            heave = hy
            eul_pitch = -(pitch + keyed(y.get("pitch"), f))
            eul_roll = roll + keyed(y.get("roll"), f)
            ym3 = trans((y["x"], hy - keyed(y.get("sink"), f), y["z"])) @ rot_y(y["heading"]) @ Matrix.Rotation(eul_pitch, 4, "X") @ Matrix.Rotation(eul_roll, 4, "Z")
            mb = obj_mat(ym3)
            loc, q, _ = mb.decompose()
            if "y" in prev_q and prev_q["y"].dot(q) < 0:
                q.negate()
            prev_q["y"] = q
            yacht_root.location = loc
            yacht_root.rotation_quaternion = q
            yacht_root.keyframe_insert("location", frame=f)
            yacht_root.keyframe_insert("rotation_quaternion", frame=f)
        camp, lookp, fov, rollc = rig_at(f, ck["keys"], keyed(ck.get("handheld"), f, 0.2), ck.get("shakes") or (), ck.get("drift", 0.25))
        if cam_space == "yacht" and y:
            cm = trans((y["x"], heave * 0.85, y["z"])) @ rot_y(y["heading"])
            camw = (cm @ Vector(camp).to_4d()).to_3d()
            lookw = (ym3 @ Vector(lookp).to_4d()).to_3d()
        else:
            camw, lookw = Vector(camp), Vector(lookp)
        m3 = look_matrix3(camw, lookw, rollc)
        mb = T @ m3
        loc, q, _ = mb.decompose()
        if "c" in prev_q and prev_q["c"].dot(q) < 0:
            q.negate()
        prev_q["c"] = q
        cam.location = loc
        cam.rotation_quaternion = q
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_quaternion", frame=f)
        camd.lens = (camd.sensor_height / 2) / math.tan(math.radians(fov) / 2)
        camd.keyframe_insert("lens", frame=f)
    # operator fill: a cool key from the camera side so faces read against the moon (ocean3d.tsx 'fill')
    k0 = ck["keys"][0]
    if cam_space == "yacht" and y:
        cm0 = trans((y["x"], 0, y["z"])) @ rot_y(y["heading"])
        c0 = (cm0 @ Vector(k0["cam"]).to_4d()).to_3d()
        l0 = (cm0 @ Vector(k0["look"]).to_4d()).to_3d()
    else:
        c0, l0 = Vector(k0["cam"]), Vector(k0["look"])
    c0 = c0 + Vector((0, 6, 0))
    fdir = b3(l0 - c0).normalized()
    fl = bpy.data.lights.new("CamFill", "SUN")
    fl.color = (0.62, 0.7, 0.91)
    fl.energy = 0.7
    fl.angle = math.radians(10)
    flo = bpy.data.objects.new("CamFill", fl)
    link_obj(flo)
    flo.rotation_mode = "QUATERNION"
    flo.rotation_quaternion = fdir.to_track_quat("-Z", "Y")
    storm.apply(shot, env, frames, cam, fps, log)  # props2 hook: rain, lightning, overcast, sepia grade
    if lighting.active():  # lighting hook: drops CamFill, warms practicals, haze, exposure offset
        lighting.finalize_shot(sc, shot, b3(centre))
    linearize_all()
    log(f"shot {shot['id']}: buoyancy + camera keyed in {time.time() - t_b:.1f}s ({len(buoy.cache)} ocean evals)")
    # the probe is only for buoyancy: take it out of the render
    bpy.data.objects.remove(probe, do_unlink=True)
    return engine, device


def shots_for_range(spec, start, end):
    out = []
    for s in spec["shots"]:
        fr = [f for f in range(max(start, s["from"]), min(end, s["to"] - 1) + 1)]
        if fr:
            out.append((s, fr))
    return out


# >>> docuseries hook: pick cameras.main / cameras.vertical per shot (factory/director/docuseries.py derives the
# vertical camera from the 16:9 one: same positions, re-aimed at the subject, tighter fov)
def select_camera(spec, work, args):
    if args.camera == "main":
        return [({**s, "camera": s["cameras"]["main"]} if s.get("cameras") else s, fr) for s, fr in work]
    vert = spec.get("vertical") or {"width": 1080, "height": 1920}
    spec["width"], spec["height"] = int(vert["width"]), int(vert["height"])
    if os.path.basename(os.path.normpath(args.out)) == "plates":
        args.out = os.path.normpath(args.out) + "_vertical"
    out = []
    for s, fr in work:
        if (s.get("cameras") or {}).get("vertical"):
            out.append(({**s, "camera": s["cameras"]["vertical"]}, fr))
        else:
            log(f"shot {s['id']}: no vertical camera (not a short_candidate shot); skipped")
    log(f"camera=vertical: {len(out)} shot(s) at {spec['width']}x{spec['height']} -> {args.out}")
    return out
# <<< docuseries


def main():
    global ROOT, SPEC
    args = parse_args()
    with open(args.spec) as fh:
        SPEC = json.load(fh)
    ROOT = os.path.abspath(args.root) if args.root else find_root(args.spec)
    log(f"spec={args.spec} root={ROOT} frames={args.start}..{args.end} quality={args.quality} engine={args.engine} blender={bpy.app.version_string}")
    if args.start > args.end:
        raise SystemExit("--start must be <= --end")
    work = shots_for_range(SPEC, args.start, args.end)
    work = select_camera(SPEC, work, args)  # docuseries hook
    if not work:
        raise SystemExit(f"no shot covers frames {args.start}..{args.end}" + (" with a vertical camera" if args.camera == "vertical" else ""))
    t_all = time.time()
    rendered = 0
    for shot, frames in work:
        odir = os.path.join(args.out, shot["id"])
        os.makedirs(odir, exist_ok=True)
        todo = [f for f in frames if not (args.skip_existing and os.path.exists(os.path.join(odir, f"{f:04d}.png")))]
        if not todo:
            log(f"shot {shot['id']}: all {len(frames)} plates exist, skipping")
            continue
        WARNINGS.clear()
        t0 = time.time()
        engine, device = build_shot(shot, frames, args)
        log(f"shot {shot['id']}: built in {time.time() - t0:.1f}s; engine={engine} device={device}")
        if args.save_blend:
            bpy.ops.wm.save_as_mainfile(filepath=f"{args.save_blend}_{shot['id']}.blend", copy=True)
        sc = bpy.context.scene
        times = {}
        for f in todo:
            t1 = time.time()
            sc.frame_set(f)
            sc.render.filepath = os.path.join(odir, f"{f:04d}.png")
            bpy.ops.render.render(write_still=True)
            times[f] = round(time.time() - t1, 2)
            rendered += 1
            log(f"shot {shot['id']} frame {f}: {times[f]}s")
        man = {
            "shot": shot["id"], "frames": [todo[0], todo[-1]], "engine": engine, "device": device,
            "quality": args.quality, "resolution": [sc.render.resolution_x, sc.render.resolution_y], "camera": args.camera,
            "samples": sc.cycles.samples if engine == "CYCLES" else sc.eevee.taa_render_samples,
            "blender": bpy.app.version_string, "secondsPerFrame": times, "warnings": list(WARNINGS),
            "lighting": lighting.report(),
        }
        with open(os.path.join(odir, f"_render_{todo[0]}_{todo[-1]}.json"), "w") as fh:
            json.dump(man, fh, indent=1)
    log(f"done: {rendered} frames in {time.time() - t_all:.1f}s")


if __name__ == "__main__":
    main()
