"""
oceanfx.py - night-sea look for render_episode's Ocean-modifier sea (bpy, Blender 4.2). Particle-free and
CPU-cheap: everything is in the water shader.

  water_material(name, has_foam)   wet, glossy night water: animated two-scale micro ripples, wind-slick
                                   roughness variation, teal crest translucency (subsurface / absorption
                                   colour where waves are thin), crest-biased whitecaps from an Ocean-
                                   modifier foam layer ("whitecaps") broken into organic lace, and an open
                                   foam input (FOAM_SUM) that the extras below plug into.
  add_whitecap_layer(ocean, ...)   adds the DISPLACE-mode PHILLIPS Ocean modifier (< 2 cm displacement)
                                   whose foam layer drives the whitecaps (see its docstring for why).
  add_hull_foam(root, objs)        foam ring + bright contact line + lapping pulses where the hull meets the
                                   water: a signed-distance mask to the hull's measured waterline footprint,
                                   evaluated in the yacht root's space (so it follows heave/heading).
  add_reef_surf(island_objs)       breaking-wave surf along the island's reef ring: the reef centre line is
                                   taken from the island GLB's reef_foam mesh, baked once into a signed
                                   distance image (metres, + seaward), and the water shaders draw a breaker
                                   line, incoming foam sets and lagoon foam residue from it. The thin
                                   reef_foam ribbon (which z-fights the waves) is hidden.
  key_time(frames, fps)            keys the shared shader clock (seconds) linearly over the shot.
  tune_modifier(mod, sea_state)    keeps the main modifier's own foam layer on (unused by the shader).

All patterns are pure functions of world position and the frame, so frames render deterministically.
"""
import math

import bpy
from mathutils import Vector

from materials import Nodes, rgba

TIME_NODE = "SEAFX_TIME"
FOAM_SUM = "SEAFX_FOAM_SUM"
WATER_MATS = ("Water", "WaterFar")
INFO = {}  # what was applied (for logs / tests)


# ---------------------------------------------------------------------------------------------
# water
# ---------------------------------------------------------------------------------------------
WHITECAP_LAYER = "whitecaps"


def tune_modifier(mod, sea_state):
    mod.use_foam = True
    mod.foam_layer_name = "foam"


def add_whitecap_layer(ocean, sea_state, frames, fps):
    """Whitecaps from an Ocean-modifier foam layer.

    Measured in Blender 4.2: with the JONSWAP spectrum the main sea uses, the modifier's foam layer is flat
    (all vertices 0.392-0.407 at coverage 0.67 - the Jacobian spread is below the 8-bit layer precision), so
    it cannot drive whitecaps. A second Ocean modifier in DISPLACE mode with the PHILLIPS spectrum gives a
    well-spread foam layer whose distribution does not depend on wave_scale; at wave_scale 0.02 its
    displacement is < 2 cm, so the hero sea shape (and the buoyancy probe that matches it) is unchanged."""
    main = ocean.modifiers.get("ocean")
    m = ocean.modifiers.new("whitecaps", "OCEAN")
    m.geometry_mode = "DISPLACE"
    m.resolution = main.resolution if main else 10
    m.viewport_resolution = min(m.resolution, 6)
    m.spatial_size = main.spatial_size if main else 60
    m.spectrum = "PHILLIPS"
    m.wave_scale = 0.02
    m.choppiness = 2.0
    m.wind_velocity = main.wind_velocity if main else 10.0
    m.wave_alignment = main.wave_alignment if main else 0.35
    m.wave_direction = main.wave_direction if main else 1.22
    m.damping = 0.5
    m.random_seed = (main.random_seed if main else 7)
    m.use_normals = False
    m.use_foam = True
    m.foam_layer_name = WHITECAP_LAYER
    # fraction of sea surface in whitecap cores grows with the sea state (~4% at 1.0, ~10% at 2.0)
    m.foam_coverage = max(0.15, min(0.6, 0.12 + 0.12 * sea_state))
    f0, f1 = frames[0] - 2, frames[-1] + 2
    for f in (f0, f1):
        m.time = f / fps
        m.keyframe_insert("time", frame=f)
    ad = ocean.animation_data
    if ad and ad.action:
        for fc in ad.action.fcurves:
            if "whitecaps" in fc.data_path:
                for kp in fc.keyframe_points:
                    kp.interpolation = "LINEAR"
    INFO["whitecaps"] = {"coverage": round(m.foam_coverage, 3)}
    return m


def water_material(name, has_foam=True):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    N = Nodes(m)
    N.n.clear()
    out = N.node("ShaderNodeOutputMaterial")
    geo = N.node("ShaderNodeNewGeometry")
    pos = geo.outputs["Position"]
    clock = N.node("ShaderNodeValue", name=TIME_NODE, label="time (s)")
    t = clock.outputs[0]
    # micro ripples (two scales, slowly evolving) break the moon path into glitter
    r1 = N.noise(pos, 0.9, 6.0, 0.55, dims="4D", w=N.math("MULTIPLY", t, 0.22))
    r2 = N.noise(pos, 5.5, 3.0, 0.5, dims="4D", w=N.math("MULTIPLY", t, 0.8))
    h = N.math("ADD", r1.outputs["Fac"], N.math("MULTIPLY", r2.outputs["Fac"], 0.3))
    bump = N.node("ShaderNodeBump", {"Strength": 0.22, "Distance": 0.1, "Height": h})
    # wind slicks: large patches of calmer (glossier) water
    slick = N.noise(pos, 0.035, 2.0, 0.5)
    rough = N.maprange(slick.outputs["Fac"], 0.35, 0.7, 0.018, 0.075)
    water = N.node("ShaderNodeBsdfPrincipled", {
        "Base Color": rgba((0.0035, 0.009, 0.014)), "Roughness": rough, "IOR": 1.333,
        "Specular IOR Level": 0.5, "Normal": bump.outputs[0],
    })
    shader = water.outputs[0]
    # crest translucency: where the wave is high and thin, moonlight scatters through teal water
    sep = N.node("ShaderNodeSeparateXYZ", {"Vector": pos})
    crest = N.maprange(sep.outputs["Z"], 0.1, 0.9, 0.0, 1.0, interp="SMOOTHSTEP")
    trans_col = N.mixc((0, 0, 0, 1), rgba((0.010, 0.060, 0.052)), crest)
    trans = N.node("ShaderNodeBsdfTranslucent", {"Color": trans_col, "Normal": bump.outputs[0]})
    add = N.node("ShaderNodeAddShader")
    N.set(add.inputs[0], shader)
    N.set(add.inputs[1], trans.outputs[0])
    shader = add.outputs[0]

    # foam accumulator: whitecaps + (later) hull foam + reef surf
    fsum = N.node("ShaderNodeMath", name=FOAM_SUM, label="foam sum", operation="ADD", use_clamp=True)
    fsum.inputs[0].default_value = 0.0
    fsum.inputs[1].default_value = 0.0
    if has_foam:
        att = N.node("ShaderNodeAttribute", attribute_name=WHITECAP_LAYER, attribute_type="GEOMETRY")
        f = att.outputs["Fac"]
        drift = N.vmath("ADD", pos, N.node("ShaderNodeCombineXYZ", {"X": N.math("MULTIPLY", t, 0.35), "Y": N.math("MULTIPLY", t, 0.12)}).outputs[0])
        lace = foam_lace(N, drift, 1.4, N.maprange(f, 0.3, 0.9))
        breakup = N.maprange(N.noise(drift, 0.6, 3.0, 0.6).outputs["Fac"], 0.38, 0.62)
        # whitecaps sit on the crests: bias by wave height so caps do not appear in troughs
        hbias = N.maprange(sep.outputs["Z"], -0.3, 0.4, 0.35, 1.0)
        core = N.math("MULTIPLY", N.math("MULTIPLY", N.maprange(f, 0.55, 0.95, 0.0, 1.0, interp="SMOOTHSTEP"), breakup), hbias)
        veins = N.math("MULTIPLY", N.math("MULTIPLY", N.maprange(f, 0.3, 0.6), lace), hbias)
        caps = N.math("MAXIMUM", core, N.math("MULTIPLY", veins, 0.75))
        N.set(fsum.inputs[0], caps)
    foam_bump = N.node("ShaderNodeBump", {"Strength": 0.35, "Distance": 0.05, "Height": r2.outputs["Fac"]})
    foam = N.node("ShaderNodeBsdfPrincipled", {
        "Base Color": rgba((0.62, 0.67, 0.74)), "Roughness": 0.55, "Specular IOR Level": 0.35,
        "Normal": foam_bump.outputs[0],
    })
    mx = N.node("ShaderNodeMixShader")
    N.set(mx.inputs[0], N.math("MULTIPLY", fsum.outputs[0], 0.95))
    N.set(mx.inputs[1], shader)
    N.set(mx.inputs[2], foam.outputs[0])
    N.set(out.inputs["Surface"], mx.outputs[0])
    m["seafx"] = 1
    return m


def foam_lace(N, vec, scale, density):
    """Organic foam pattern (warped fractal noise, thresholded): 0..1. `density` (float or socket, 0..1)
    lowers the threshold so denser foam merges into sheets and sparse foam breaks into streaks/islands."""
    nz = N.node("ShaderNodeTexNoise", {"Vector": vec, "Scale": scale, "Detail": 8.0, "Roughness": 0.62, "Distortion": 0.9})
    thr = N.math("SUBTRACT", 0.66, N.math("MULTIPLY", density, 0.3))
    return N.math("DIVIDE", N.math("SUBTRACT", nz.outputs["Fac"], thr), 0.1, clamp=True)


def add_foam(mat, socket_fn):
    """Add a foam contribution: socket_fn(N, pos, t) -> float socket in [0, 1]."""
    if mat is None or not mat.use_nodes or FOAM_SUM not in mat.node_tree.nodes:
        return False
    N = Nodes(mat)
    fsum = N.n[FOAM_SUM]
    pos = next(n for n in N.n if n.type == "NEW_GEOMETRY").outputs["Position"]
    t = N.n[TIME_NODE].outputs[0]
    contrib = socket_fn(N, pos, t)
    add = N.node("ShaderNodeMath", operation="ADD", use_clamp=True)
    prev = fsum.inputs[1].links[0].from_socket if fsum.inputs[1].is_linked else None
    if prev is not None:
        N.set(add.inputs[0], prev)
    else:
        add.inputs[0].default_value = 0.0
    N.set(add.inputs[1], contrib)
    N.set(fsum.inputs[1], add.outputs[0])
    return True


def key_time(frames, fps):
    f0, f1 = frames[0] - 2, frames[-1] + 2
    for m in bpy.data.materials:
        if not m.use_nodes or TIME_NODE not in m.node_tree.nodes:
            continue
        sock = m.node_tree.nodes[TIME_NODE].outputs[0]
        for f in (f0, f1):
            sock.default_value = f / fps
            sock.keyframe_insert("default_value", frame=f)
        ad = m.node_tree.animation_data
        if ad and ad.action:
            for fc in ad.action.fcurves:
                for kp in fc.keyframe_points:
                    kp.interpolation = "LINEAR"


# ---------------------------------------------------------------------------------------------
# hull foam
# ---------------------------------------------------------------------------------------------
def _root_space(ob, root):
    return root.matrix_world.inverted() @ ob.matrix_world


def hull_footprint(hull, root, waterline=0.05, band=0.35, bins=28):
    """Half-beam profile of the hull near/below the waterline, in yacht-root space (Blender axes)."""
    bpy.context.view_layer.update()
    M = _root_space(hull, root)
    pts = [M @ v.co for v in hull.data.vertices]
    sel = [p for p in pts if p.z < waterline + band]
    if len(sel) < 8:
        sel = pts
    xs = [p.x for p in sel]
    xc = 0.5 * (min(xs) + max(xs))
    y0 = min(p.y for p in sel)
    y1 = max(p.y for p in sel)
    prof = [0.0] * bins
    for p in sel:
        i = min(bins - 1, int((p.y - y0) / max(1e-6, y1 - y0) * bins))
        prof[i] = max(prof[i], abs(p.x - xc))
    # fill gaps
    for i in range(bins):
        if prof[i] == 0.0:
            nb = [prof[j] for j in (i - 1, i + 1) if 0 <= j < bins and prof[j] > 0]
            prof[i] = sum(nb) / len(nb) if nb else 0.1
    return xc, y0, y1, prof


def add_hull_foam(root, objs, waterline=0.05):
    hull = next((o for o in objs if o.type == "MESH" and o.name.startswith("gelcoat_hull")), None)
    if hull is None:
        meshes = [o for o in objs if o.type == "MESH"]
        if not meshes:
            return None
        hull = max(meshes, key=lambda o: o.dimensions.x * o.dimensions.y)
    xc, y0, y1, prof = hull_footprint(hull, root, waterline)
    bmax = max(prof)
    L = y1 - y0

    def build(N, pos, t):
        tc = N.node("ShaderNodeTexCoord", object=root)
        sep = N.node("ShaderNodeSeparateXYZ", {"Vector": tc.outputs["Object"]})
        X = N.math("ABSOLUTE", N.math("SUBTRACT", sep.outputs["X"], xc))
        Y = sep.outputs["Y"]
        tt = N.math("DIVIDE", N.math("SUBTRACT", Y, y0), L, clamp=True)
        fc = N.node("ShaderNodeFloatCurve", {"Value": tt})
        cv = fc.mapping.curves[0]
        n = len(prof)
        pts_xy = [((i + 0.5) / n, prof[i] / bmax) for i in range(n)]
        pts_xy = [(0.0, prof[0] / bmax)] + pts_xy + [(1.0, prof[-1] / bmax * 0.5)]
        while len(cv.points) < len(pts_xy):
            cv.points.new(0.5, 0.5)
        for p, (a, b) in zip(cv.points, pts_xy):
            p.location = (a, b)
            p.handle_type = "VECTOR"
        fc.mapping.update()
        r = N.math("MULTIPLY", fc.outputs["Value"], bmax)
        yc = N.math("MINIMUM", N.math("MAXIMUM", Y, y0), y1)
        dx = N.math("SUBTRACT", X, r)
        dy = N.math("ABSOLUTE", N.math("SUBTRACT", Y, yc))
        dxp = N.math("MAXIMUM", dx, 0.0)
        d = N.math("ADD", N.math("SQRT", N.math("ADD", N.math("MULTIPLY", dxp, dxp), N.math("MULTIPLY", dy, dy))), N.math("MINIMUM", dx, 0.0))
        # ring width breathes along the hull and in time
        wn = N.noise(pos, 0.45, 2.0, 0.5, dims="4D", w=N.math("MULTIPLY", t, 0.5))
        width = N.maprange(wn.outputs["Fac"], 0.3, 0.7, 0.7, 2.4)
        ring = N.math("SUBTRACT", 1.0, N.math("DIVIDE", N.math("MAXIMUM", d, 0.0), width, clamp=True))
        ring = N.math("POWER", ring, 1.6)
        contact = N.maprange(d, 0.35, -0.05, 0.0, 1.0, interp="SMOOTHSTEP")
        lap = N.maprange(N.math("SINE", N.math("SUBTRACT", N.math("MULTIPLY", d, 5.0), N.math("MULTIPLY", t, 2.6))), 0.35, 1.0)
        drift = N.vmath("ADD", pos, N.node("ShaderNodeCombineXYZ", {"Z": N.math("MULTIPLY", t, 0.4)}).outputs[0])
        lace = foam_lace(N, drift, 1.8, ring)
        body = N.math("MULTIPLY", ring, N.math("ADD", lace, N.math("MULTIPLY", lap, 0.3)))
        return N.math("MAXIMUM", contact, body, clamp=True)

    ok = add_foam(bpy.data.materials.get("Water"), build)
    INFO["hull_foam"] = {"hull": hull.name, "length": round(L, 2), "beam": round(2 * bmax, 2), "applied": ok}
    return INFO["hull_foam"]


# ---------------------------------------------------------------------------------------------
# reef surf
# ---------------------------------------------------------------------------------------------
def reef_centreline(reef, bins=720):
    """Centre line of the reef tube, world XY, in angular order around the ring centroid (CCW)."""
    bpy.context.view_layer.update()
    M = reef.matrix_world
    pts = [(M @ v.co) for v in reef.data.vertices]
    cx = sum(p.x for p in pts) / len(pts)
    cy = sum(p.y for p in pts) / len(pts)
    acc = [[0.0, 0.0, 0] for _ in range(bins)]
    for p in pts:
        a = math.atan2(p.y - cy, p.x - cx)
        i = int((a + math.pi) / (2 * math.pi) * bins) % bins
        acc[i][0] += p.x
        acc[i][1] += p.y
        acc[i][2] += 1
    line = [(sx / n, sy / n) for sx, sy, n in acc if n]
    return (cx, cy), line


def bake_reef_sdf(centre, line, max_px=1024, margin=180.0, clamp_m=170.0):
    import numpy as np
    P = np.array(line, dtype=np.float64)
    x0, y0 = P[:, 0].min() - margin, P[:, 1].min() - margin
    x1, y1 = P[:, 0].max() + margin, P[:, 1].max() + margin
    cell = max(x1 - x0, y1 - y0) / max_px
    W = int(math.ceil((x1 - x0) / cell))
    H = int(math.ceil((y1 - y0) / cell))
    gx = x0 + (np.arange(W) + 0.5) * cell
    gy = y0 + (np.arange(H) + 0.5) * cell
    dist = np.full((H, W), clamp_m, dtype=np.float64)
    n = len(P)
    for i in range(n):
        a, b = P[i], P[(i + 1) % n]
        lo = np.minimum(a, b) - clamp_m
        hi = np.maximum(a, b) + clamp_m
        i0, i1 = max(0, int((lo[0] - x0) / cell)), min(W, int((hi[0] - x0) / cell) + 1)
        j0, j1 = max(0, int((lo[1] - y0) / cell)), min(H, int((hi[1] - y0) / cell) + 1)
        if i0 >= i1 or j0 >= j1:
            continue
        X, Y = np.meshgrid(gx[i0:i1], gy[j0:j1])
        ab = b - a
        l2 = max(1e-9, ab @ ab)
        t = np.clip(((X - a[0]) * ab[0] + (Y - a[1]) * ab[1]) / l2, 0.0, 1.0)
        d = np.hypot(X - (a[0] + t * ab[0]), Y - (a[1] + t * ab[1]))
        sub = dist[j0:j1, i0:i1]
        np.minimum(sub, d, out=sub)
    # sign: outside the ring (seaward) is +; radial test against the ring radius at that bearing
    cx, cy = centre
    ang = np.arctan2(P[:, 1] - cy, P[:, 0] - cx)
    rad = np.hypot(P[:, 0] - cx, P[:, 1] - cy)
    order = np.argsort(ang)
    ang, rad = ang[order], rad[order]
    ang = np.concatenate([ang[-1:] - 2 * np.pi, ang, ang[:1] + 2 * np.pi])
    rad = np.concatenate([rad[-1:], rad, rad[:1]])
    X, Y = np.meshgrid(gx, gy)
    R = np.interp(np.arctan2(Y - cy, X - cx), ang, rad)
    sign = np.where(np.hypot(X - cx, Y - cy) >= R, 1.0, -1.0)
    sdf = (dist * sign).astype(np.float32)
    img = bpy.data.images.get("SEAFX_reef_sdf")
    if img is not None:
        bpy.data.images.remove(img)
    img = bpy.data.images.new("SEAFX_reef_sdf", W, H, alpha=False, float_buffer=True)
    img.colorspace_settings.name = "Non-Color"
    px = np.zeros((H, W, 4), dtype=np.float32)
    px[..., 0] = sdf
    px[..., 3] = 1.0
    img.pixels.foreach_set(px.ravel())
    img.pack()
    return img, (x0, y0, W * cell, H * cell), cell


def add_reef_surf(objs=None):
    pool = objs if objs is not None else bpy.data.objects
    reef = next((o for o in pool if o.type == "MESH" and o.name.startswith("reef_foam")), None)
    if reef is None:
        return None
    centre, line = reef_centreline(reef)
    if len(line) < 16:
        return None
    img, (x0, y0, w, h), cell = bake_reef_sdf(centre, line)
    reef.hide_render = True  # the shader surf replaces the flat ribbon

    def build(N, pos, t):
        sep = N.node("ShaderNodeSeparateXYZ", {"Vector": pos})
        uv = N.node("ShaderNodeCombineXYZ")
        N.set(uv.inputs["X"], N.math("DIVIDE", N.math("SUBTRACT", sep.outputs["X"], x0), w))
        N.set(uv.inputs["Y"], N.math("DIVIDE", N.math("SUBTRACT", sep.outputs["Y"], y0), h))
        tex = N.node("ShaderNodeTexImage", {"Vector": uv.outputs[0]}, image=img, interpolation="Linear", extension="EXTEND")
        s = N.node("ShaderNodeSeparateColor", {"Color": tex.outputs["Color"]}).outputs[0]  # signed metres, + seaward
        big = N.noise(pos, 0.012, 2.0, 0.5)
        strength = N.maprange(big.outputs["Fac"], 0.3, 0.65, 0.45, 1.0)
        jitter = N.maprange(N.noise(pos, 0.08, 2.0).outputs["Fac"], 0.0, 1.0, -4.0, 4.0)
        sj = N.math("ADD", s, jitter)
        drift = N.vmath("ADD", pos, N.node("ShaderNodeCombineXYZ", {"X": N.math("MULTIPLY", t, 0.6)}).outputs[0])
        lace = foam_lace(N, drift, 0.35, 0.35)
        # breaker line: solid whitewater just seaward of the reef crest
        breaker = N.math("MULTIPLY", N.maprange(sj, -2.0, 1.5, 0.0, 1.0, interp="SMOOTHSTEP"), N.maprange(sj, 5.0, 11.0, 1.0, 0.0, interp="SMOOTHSTEP"))
        # incoming sets: foam lines travelling toward the reef, fading with distance offshore
        phase = N.math("ADD", N.math("MULTIPLY", sj, 0.32), N.math("MULTIPLY", t, 1.5))
        sets = N.math("MULTIPLY", N.maprange(N.math("SINE", phase), 0.72, 1.0, 0.0, 1.0, interp="SMOOTHSTEP"), N.maprange(sj, 45.0, 8.0))
        sets = N.math("MULTIPLY", sets, lace)
        # lagoon side: residue that thins out toward the island
        residue = N.math("MULTIPLY", N.maprange(sj, -45.0, -1.0, 0.0, 1.0), foam_lace(N, drift, 0.5, N.maprange(sj, -45.0, -1.0, 0.0, 0.6)))
        surf = N.math("MAXIMUM", N.math("MULTIPLY", breaker, N.math("ADD", 0.55, N.math("MULTIPLY", lace, 0.45))), N.math("MAXIMUM", N.math("MULTIPLY", sets, 0.8), N.math("MULTIPLY", residue, 0.45)))
        return N.math("MULTIPLY", surf, strength, clamp=True)

    applied = [nm for nm in WATER_MATS if add_foam(bpy.data.materials.get(nm), build)]
    INFO["reef_surf"] = {"reef": reef.name, "line_pts": len(line), "sdf_px": [img.size[0], img.size[1]], "cell_m": round(cell, 2),
                         "bbox": [round(x0, 1), round(y0, 1), round(w, 1), round(h, 1)], "materials": applied}
    return INFO["reef_surf"]
