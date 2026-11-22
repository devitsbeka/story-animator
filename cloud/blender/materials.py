"""
materials.py - PBR look-dev for the hero yacht (bpy, Blender 4.2).

apply_yacht_materials(objs) restyles the materials of an imported yacht.glb IN PLACE, matched by material
name (falling back to object name) prefix:

  gelcoat_hull   white gelcoat hull: glossy coat, roughness/wear variation, waterline scum, navy boot stripe,
                 dark antifouling below the waterline (object space; the hull has no UVs)
  gelcoat_*      superstructure gelcoat: same white, coat + subtle wear, no stripe
  teak*          teak deck from the CC0 Poly Haven texture brown_planks_05 (library_store), re-tinted honey
                 teak, ~5.5 cm planks running fore-aft; procedural planks if the texture is missing
  steel*         brushed 316 stainless: anisotropic, streaky roughness
  glass*         real tinted thin-pane glass (reflection IOR 1.5 + tinted transmission), NEVER emissive (L019);
                 lit windows glow from the lit interior behind them (yacht_v2 builds a salon with real lights)
  upholstery_*   dark marine fabric with sheen and a fine weave bump
  fender*        navy PVC fender: semi-gloss coat, light grime
  nav_*          lens look only (coat); emission untouched

The Principled BSDF node of every material is KEPT (only its inputs are re-driven), so render_episode's
collect_light_targets() still finds and keys the emissive sockets (nav lights, interior lamp fixtures).
Everything is deterministic and CPU-cheap (one 2k texture set, a few procedural noises).
"""
import os
import re

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))


def _store():
    return os.environ.get("LIBRARY_STORE") or os.path.join(REPO, "library_store")


def lib_file(rel, store=None):
    p = os.path.join(store or _store(), rel)
    return p if os.path.exists(p) else None


# ---------------------------------------------------------------------------------------------
# tiny node-building helper (self-contained so this module does not depend on render_episode)
# ---------------------------------------------------------------------------------------------
class Nodes:
    def __init__(self, mat):
        self.mat = mat
        self.t = mat.node_tree
        self.n = self.t.nodes
        self.l = self.t.links

    def node(self, typ, inputs=None, **props):
        nd = self.n.new(typ)
        for k, v in props.items():
            setattr(nd, k, v)
        for k, v in (inputs or {}).items():
            self.set(nd.inputs[k], v)
        return nd

    def set(self, sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            for lk in list(sock.links):
                self.l.remove(lk)
            self.l.new(v, sock)
        else:
            sock.default_value = v

    def math(self, op, a, b=None, clamp=False):
        nd = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b)):
            if v is not None:
                self.set(nd.inputs[i], v)
        return nd.outputs[0]

    def vmath(self, op, a, b=None):
        nd = self.node("ShaderNodeVectorMath", operation=op)
        for i, v in enumerate((a, b)):
            if v is not None:
                self.set(nd.inputs[i], v)
        return nd.outputs["Value"] if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else nd.outputs["Vector"]

    def maprange(self, v, a, b, c=0.0, d=1.0, interp="LINEAR", clamp=True):
        nd = self.node("ShaderNodeMapRange", interpolation_type=interp, clamp=clamp)
        self.set(nd.inputs["Value"], v)
        nd.inputs["From Min"].default_value = a
        nd.inputs["From Max"].default_value = b
        nd.inputs["To Min"].default_value = c
        nd.inputs["To Max"].default_value = d
        return nd.outputs["Result"]

    def mixc(self, a, b, fac, blend="MIX"):
        nd = self.node("ShaderNodeMix", data_type="RGBA", blend_type=blend, clamp_result=True)
        for sock, v in ((nd.inputs[0], fac), (nd.inputs[6], a), (nd.inputs[7], b)):
            self.set(sock, v)
        return nd.outputs[2]

    def noise(self, vec, scale, detail=2.0, rough=0.5, dims="3D", w=None):
        nd = self.node("ShaderNodeTexNoise", noise_dimensions=dims)
        self.set(nd.inputs["Vector"], vec)
        nd.inputs["Scale"].default_value = scale
        nd.inputs["Detail"].default_value = detail
        nd.inputs["Roughness"].default_value = rough
        if w is not None:
            self.set(nd.inputs["W"], w)
        return nd

    def stretch(self, vec, sx, sy, sz):
        return self.vmath("MULTIPLY", vec, (sx, sy, sz))


def rgba(c, a=1.0):
    return (c[0], c[1], c[2], a)


def _principled(mat):
    """Keep the material's Principled node (and its emission sockets); drop everything else."""
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    for n in list(nt.nodes):
        if n != bsdf and n != out:  # bpy wrappers: compare by pointer, never with `is`
            nt.nodes.remove(n)
    if bsdf is None:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    if out is None:
        out = nt.nodes.new("ShaderNodeOutputMaterial")
    for lk in list(nt.links):
        nt.links.remove(lk)
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    return bsdf


def _set_inputs(bsdf, **kw):
    names = {
        "base": "Base Color", "rough": "Roughness", "metal": "Metallic", "ior": "IOR", "spec": "Specular IOR Level",
        "coat": "Coat Weight", "coat_rough": "Coat Roughness", "sheen": "Sheen Weight", "sheen_rough": "Sheen Roughness",
        "sheen_tint": "Sheen Tint", "aniso": "Anisotropic", "aniso_rot": "Anisotropic Rotation",
        "transmission": "Transmission Weight", "alpha": "Alpha",
    }
    for k, v in kw.items():
        sock = bsdf.inputs[names[k]]
        if isinstance(v, tuple) and len(v) == 3:
            v = rgba(v)
        sock.default_value = v


# ---------------------------------------------------------------------------------------------
# material builders (each restyles `mat` in place and returns it)
# ---------------------------------------------------------------------------------------------
GELCOAT = (0.55, 0.55, 0.53)     # polish_light: warm off-white, exposure-safe (was 0.80: clipped under the moon)
BOOT_NAVY = (0.006, 0.012, 0.045)
ANTIFOUL = (0.012, 0.016, 0.03)


def gelcoat(mat, hull=False, waterline_z=None):
    b = _principled(mat)
    N = Nodes(mat)
    tc = N.node("ShaderNodeTexCoord")
    obj = tc.outputs["Object"]
    # large soft roughness variation (polish / wear) + fine speckle
    n1 = N.noise(obj, 0.9, 3.0, 0.55)
    n2 = N.noise(obj, 18.0, 2.0, 0.5)
    rough = N.math("ADD", N.maprange(n1.outputs["Fac"], 0.35, 0.65, 0.24, 0.42), N.maprange(n2.outputs["Fac"], 0.3, 0.7, -0.03, 0.04))  # polish_light: satin base under the coat
    # vertical grime streaks (rain/salt runs) - noise stretched along z
    streak = N.noise(N.stretch(obj, 6.0, 6.0, 0.35), 2.2, 4.0, 0.6)
    grime = N.maprange(streak.outputs["Fac"], 0.55, 0.8, 0.0, 0.10)
    col = N.mixc(rgba(GELCOAT), rgba((0.55, 0.53, 0.47)), grime)
    if hull and waterline_z is not None:
        sep = N.node("ShaderNodeSeparateXYZ", {"Vector": obj})
        z = sep.outputs["Z"]
        # a wobbly waterline so the stripe edges are not ruler-straight
        wob = N.maprange(N.noise(obj, 3.0, 2.0).outputs["Fac"], 0.3, 0.7, -0.012, 0.012)
        zz = N.math("ADD", N.math("SUBTRACT", z, waterline_z), wob)
        boot_lo, boot_hi = 0.06, 0.20
        below = N.math("LESS_THAN", zz, 0.0)
        boot = N.math("MULTIPLY", N.math("GREATER_THAN", zz, boot_lo), N.math("LESS_THAN", zz, boot_hi))
        # brownish scum line just above the boot stripe, fading upward
        scum = N.math("MULTIPLY", N.maprange(zz, boot_hi + 0.25, boot_hi, 0.0, 0.35), N.maprange(streak.outputs["Fac"], 0.3, 0.7, 0.4, 1.0))
        col = N.mixc(col, rgba((0.33, 0.30, 0.2)), scum)
        col = N.mixc(col, rgba(BOOT_NAVY), boot)
        col = N.mixc(col, rgba(ANTIFOUL), below)
        # antifouling is matte, boot stripe glossy like the gelcoat
        rough = N.math("ADD", rough, N.math("MULTIPLY", below, 0.45))
    N.set(b.inputs["Base Color"], col)
    N.set(b.inputs["Roughness"], rough)
    bump = N.node("ShaderNodeBump", {"Strength": 0.04, "Distance": 0.002, "Height": n2.outputs["Fac"]})
    N.set(b.inputs["Normal"], bump.outputs[0])
    _set_inputs(b, metal=0.0, ior=1.5, spec=0.5, coat=0.22, coat_rough=0.2)  # polish_light: soft moon glint, no hot spot
    return mat


def teak(mat, store=None, plank_m=0.055):
    """brown_planks_05 tile is 1 m with ~9 planks (11 cm); scale so planks are `plank_m` wide, running along
    the object's local Y (the yacht's length: glTF +z bow maps to Blender -Y)."""
    b = _principled(mat)
    N = Nodes(mat)
    tc = N.node("ShaderNodeTexCoord")
    obj = tc.outputs["Object"]
    sep = N.node("ShaderNodeSeparateXYZ", {"Vector": obj})
    tile = plank_m * 9.0
    # u along the planks (object Y), v across (object X); a tiny Z term so plank sides do not smear
    uv = N.node("ShaderNodeCombineXYZ")
    N.set(uv.inputs["X"], N.math("DIVIDE", sep.outputs["Y"], tile * 1.6))
    N.set(uv.inputs["Y"], N.math("DIVIDE", N.math("ADD", sep.outputs["X"], N.math("MULTIPLY", sep.outputs["Z"], 0.3)), tile))
    base = "polyhaven/brown_planks_05/brown_planks_05_{}_2k.jpg"
    diff, nor, rgh = (lib_file(base.format(k), store) for k in ("diff", "nor_gl", "rough"))
    if diff:
        def img(path, noncolor):
            im = bpy.data.images.load(path, check_existing=True)
            if noncolor:
                im.colorspace_settings.name = "Non-Color"
            return N.node("ShaderNodeTexImage", {"Vector": uv.outputs[0]}, image=im, interpolation="Linear")
        d = img(diff, False)
        # grey weathered planks -> oiled teak: keep the texture's luminance detail, tint honey-brown
        bw = N.node("ShaderNodeRGBToBW", {"Color": d.outputs["Color"]})
        tint = N.node("ShaderNodeValToRGB", {"Fac": N.maprange(bw.outputs["Val"], 0.08, 0.62)})
        cr = tint.color_ramp
        cr.elements[0].color = rgba((0.012, 0.005, 0.002))   # caulk / gaps
        cr.elements[1].color = rgba((0.36, 0.17, 0.065))     # light grain
        e = cr.elements.new(0.45)
        e.color = rgba((0.17, 0.07, 0.025))                  # oiled teak body
        col = tint.outputs["Color"]
        N.set(b.inputs["Base Color"], col)
        if rgh:
            r = img(rgh, True)
            N.set(b.inputs["Roughness"], N.maprange(r.outputs["Color"], 0.0, 1.0, 0.45, 0.85))
        else:
            b.inputs["Roughness"].default_value = 0.65
        if nor:
            nm = N.node("ShaderNodeNormalMap", {"Color": img(nor, True).outputs["Color"], "Strength": 0.8})
            N.set(b.inputs["Normal"], nm.outputs[0])
        mat["yachtsea_teak"] = "brown_planks_05"
    else:
        # procedural fallback: planks from a wave texture + black caulk lines
        wave = N.node("ShaderNodeTexWave", {"Vector": uv.outputs[0], "Scale": 9.0, "Distortion": 0.0},
                      wave_type="BANDS", bands_direction="Y", wave_profile="SAW")
        caulk = N.maprange(wave.outputs["Fac"], 0.0, 0.06, 1.0, 0.0)
        grain = N.noise(N.stretch(uv.outputs[0], 1.0, 40.0, 1.0), 6.0, 6.0)
        wood = N.mixc(rgba((0.18, 0.075, 0.025)), rgba((0.32, 0.15, 0.055)), grain.outputs["Fac"])
        N.set(b.inputs["Base Color"], N.mixc(wood, rgba((0.01, 0.008, 0.006)), caulk))
        N.set(b.inputs["Roughness"], N.maprange(caulk, 0.0, 1.0, 0.6, 0.9))
        mat["yachtsea_teak"] = "procedural"
    _set_inputs(b, metal=0.0, spec=0.4, coat=0.0)
    return mat


def steel(mat):
    b = _principled(mat)
    N = Nodes(mat)
    tc = N.node("ShaderNodeTexCoord")
    obj = tc.outputs["Object"]
    brush = N.noise(N.stretch(obj, 220.0, 220.0, 2.0), 1.0, 4.0, 0.6)
    smudge = N.noise(obj, 4.0, 2.0)
    rough = N.math("ADD", N.maprange(brush.outputs["Fac"], 0.3, 0.7, 0.14, 0.26), N.maprange(smudge.outputs["Fac"], 0.5, 0.75, 0.0, 0.1))
    N.set(b.inputs["Roughness"], rough)
    col = N.mixc(rgba((0.72, 0.73, 0.75)), rgba((0.6, 0.6, 0.6)), N.maprange(smudge.outputs["Fac"], 0.4, 0.7))
    N.set(b.inputs["Base Color"], col)
    _set_inputs(b, metal=1.0, aniso=0.55, aniso_rot=0.0, coat=0.0)
    return mat


def glass(mat):
    """Real tinted glazing (lesson L019): never an emissive panel. A thin pane = dielectric reflection (Principled,
    IOR 1.5, near-mirror, so the sky and moon reflect) + tinted transmission (Transparent BSDF weighted by 1 - Fresnel),
    so lit windows glow only because the interior behind them is lit by real lights, and those lights spill out through
    the tint. The transmission does not cost diffuse/glossy bounces (render_episode runs max_bounces 3 in preview).
    Tint: the material's custom property 'tint' (yacht_v2 sets dark bronze / grey per pane), else smoked bronze."""
    b = _principled(mat)
    N = Nodes(mat)
    tint = tuple(mat.get("tint", (0.30, 0.26, 0.21)))[:3]
    _set_inputs(b, base=(0.0, 0.0, 0.0), metal=0.0, ior=1.5, spec=1.0, coat=0.0, transmission=0.0)
    b.inputs["Emission Strength"].default_value = 0.0
    b.inputs["Emission Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    tc = N.node("ShaderNodeTexCoord")
    # faint water spots / wiping marks: roughness 0.01..0.05, never milky
    spots = N.noise(tc.outputs["Object"], 9.0, 3.0, 0.6)
    N.set(b.inputs["Roughness"], N.maprange(spots.outputs["Fac"], 0.5, 0.8, 0.008, 0.05))
    fr = N.node("ShaderNodeFresnel", {"IOR": 1.5})
    trans = N.node("ShaderNodeBsdfTransparent")
    N.set(trans.inputs["Color"], N.mixc(rgba(tint), rgba((0.0, 0.0, 0.0)), fr.outputs["Fac"]))
    add = N.node("ShaderNodeAddShader")
    N.set(add.inputs[0], b.outputs[0])
    N.set(add.inputs[1], trans.outputs[0])
    out = next(n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL")
    N.set(out.inputs["Surface"], add.outputs[0])
    for attr, val in (("surface_render_method", "BLENDED"), ("use_transparent_shadow", True), ("blend_method", "BLEND")):
        try:
            setattr(mat, attr, val)
        except (AttributeError, TypeError):
            pass
    return mat


def upholstery(mat):
    b = _principled(mat)
    N = Nodes(mat)
    tc = N.node("ShaderNodeTexCoord")
    obj = tc.outputs["Object"]
    weave = N.node("ShaderNodeTexWave", {"Vector": obj, "Scale": 140.0, "Distortion": 1.5, "Detail": 1.0}, wave_type="RINGS")
    patina = N.noise(obj, 3.0, 3.0)
    N.set(b.inputs["Base Color"], N.mixc(rgba((0.010, 0.013, 0.022)), rgba((0.022, 0.026, 0.036)), N.maprange(patina.outputs["Fac"], 0.35, 0.7)))
    bump = N.node("ShaderNodeBump", {"Strength": 0.15, "Distance": 0.002, "Height": weave.outputs["Fac"]})
    N.set(b.inputs["Normal"], bump.outputs[0])
    _set_inputs(b, rough=0.72, metal=0.0, sheen=0.45, sheen_rough=0.4, sheen_tint=(0.55, 0.6, 0.75), coat=0.0, spec=0.35)
    return mat


def fender(mat):
    b = _principled(mat)
    N = Nodes(mat)
    tc = N.node("ShaderNodeTexCoord")
    dirt = N.noise(tc.outputs["Object"], 6.0, 3.0)
    N.set(b.inputs["Base Color"], N.mixc(rgba((0.010, 0.035, 0.20)), rgba((0.03, 0.04, 0.07)), N.maprange(dirt.outputs["Fac"], 0.55, 0.8, 0.0, 0.5)))
    N.set(b.inputs["Roughness"], N.maprange(dirt.outputs["Fac"], 0.3, 0.8, 0.3, 0.55))
    _set_inputs(b, metal=0.0, coat=0.5, coat_rough=0.15, spec=0.5)
    return mat


def nav_lens(mat):
    b = _principled(mat) if mat.use_nodes else None
    if b is not None:
        # keep base/emission as authored; make the unlit lens read as glass
        _set_inputs(b, rough=0.2, coat=1.0, coat_rough=0.03)
    return mat


# ---------------------------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------------------------
RULES = [  # (prefix, kind) - first match wins; matched against material name, then object name
    ("gelcoat_hull", "hull"),
    ("gelcoat", "gelcoat"),
    ("teak", "teak"),
    ("steel", "steel"),
    ("glass_cabin", "glass"),
    ("glass", "glass"),
    ("upholstery", "upholstery"),
    ("fender", "fender"),
    ("nav_", "nav"),
]


def _kind(name):
    base = re.sub(r"\.\d{3}$", "", name or "")
    for pre, kind in RULES:
        if base.startswith(pre):
            return kind
    return None


def _root_space_matrix(ob):
    m = ob.matrix_world.copy()
    p = ob.parent
    while p is not None and p.parent is not None:
        p = p.parent
    if p is not None:
        m = p.matrix_world.inverted() @ m
    return m


def apply_yacht_materials(objs, store=None, waterline=0.05):
    """Restyle the yacht's materials in place. `objs` are the imported yacht objects. `waterline` is the
    static waterline height in yacht-root space (render_episode floats the root at sea height - 0.05, so the
    sea surface sits ~0.05 m above the root origin). Returns {material name: kind} of what was restyled."""
    bpy.context.view_layer.update()
    done = {}
    for ob in objs:
        if ob.type != "MESH":
            continue
        for slot in ob.material_slots:
            m = slot.material
            if m is None or m.name in done:
                continue
            kind = _kind(m.name) or _kind(ob.name)
            if kind is None:
                continue
            if kind == "hull":
                # waterline in the hull's object space (Object texture coordinates are pre-transform)
                from mathutils import Vector
                local = _root_space_matrix(ob).inverted() @ Vector((0.0, 0.0, waterline))
                gelcoat(m, hull=True, waterline_z=local.z)
            elif kind == "gelcoat":
                gelcoat(m)
            elif kind == "teak":
                teak(m, store)
            elif kind == "steel":
                steel(m)
            elif kind == "glass":
                glass(m)
            elif kind == "upholstery":
                upholstery(m)
            elif kind == "fender":
                fender(m)
            elif kind == "nav":
                nav_lens(m)
            done[m.name] = kind
    return done


# >>> polish_light: hero (Blender Studio Jay / hero_v4) look-dev, applied after the character is appended.
# Edits material/node-group INPUTS only (no topology changes to the studio shaders), so it is safe to re-run.
CLOTH_FLOOR = (0.02, 0.02, 0.022)  # black cotton ~2% albedo, not 1% (1% crushes to a hole at night)


def _lift_black(mat, floor=CLOTH_FLOOR, sheen=0.4, sheen_rough=0.32, sheen_tint=(0.75, 0.82, 1.0)):
    """Black fabric: lift the albedo floor (LIGHTEN keeps prints / white stripes), cotton sheen so folds and the
    silhouette catch the moon/rim (separation from the night sea)."""
    nt = mat.node_tree
    b = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if b is None or mat.get("polish_light_cloth"):
        return False
    base = b.inputs["Base Color"]
    if base.is_linked:
        src = base.links[0].from_socket
        lt = nt.nodes.new("ShaderNodeMix")
        lt.data_type, lt.blend_type = "RGBA", "LIGHTEN"
        lt.inputs[0].default_value = 1.0
        nt.links.new(src, lt.inputs[6])
        lt.inputs[7].default_value = rgba(floor)
        nt.links.new(lt.outputs[2], base)
    else:
        c = base.default_value
        base.default_value = (max(c[0], floor[0]), max(c[1], floor[1]), max(c[2], floor[2]), 1.0)
    sw = b.inputs["Sheen Weight"]
    if sw.is_linked:  # hoodie: print drives sheen off; keep the link, raise the cloth branch via its Mix input A
        mx = sw.links[0].from_node
        if mx.type == "MIX" and not mx.inputs[2].is_linked:
            mx.inputs[2].default_value = max(mx.inputs[2].default_value, sheen)
    else:
        sw.default_value = max(sw.default_value, sheen)
    b.inputs["Sheen Roughness"].default_value = sheen_rough
    b.inputs["Sheen Tint"].default_value = rgba(sheen_tint)
    mat["polish_light_cloth"] = 1
    return True


def _skin(groups):
    """SH-skin: softer, less saturated scatter (red 2 cm, green/blue wider) so the moon-lit face reads as skin, not
    red wax; a faint specular so the key/eye light models the cheeks without blowing them."""
    ng = groups.get("SH-skin")
    if ng is None or ng.get("polish_light"):
        return False
    cx = next((n for n in ng.nodes if n.type == "COMBXYZ"), None)
    if cx is not None:
        for k, v in zip("XYZ", (1.0, 0.42, 0.26)):
            if not cx.inputs[k].is_linked:
                cx.inputs[k].default_value = v
    vm = next((n for n in ng.nodes if n.type == "VECT_MATH" and n.operation == "SCALE"), None)
    if vm is not None and not vm.inputs["Scale"].is_linked:
        vm.inputs["Scale"].default_value = 0.016
    b = next((n for n in ng.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if b is not None:
        b.inputs["Coat Weight"].default_value = 0.08  # thin oily layer: a soft broad highlight, no hot spot
        b.inputs["Coat Roughness"].default_value = 0.38
    ng["polish_light"] = 1
    return True


def _cornea(mat):
    """Eyes: a clear coat (cornea) so the eye light gives a crisp catchlight; the sclera stays matte under it."""
    b = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if mat.use_nodes else None
    if b is None:
        return False
    b.inputs["Coat Weight"].default_value = 1.0
    b.inputs["Coat Roughness"].default_value = 0.02
    b.inputs["Coat IOR"].default_value = 1.376
    return True


def apply_hero_materials(objs):
    """Look-dev pass for an appended hero_v4 / Jay character. Returns {material: kind}."""
    done = {}
    mats = {}
    for ob in objs:
        for slot in getattr(ob, "material_slots", []):
            if slot.material is not None:
                mats[slot.material.name] = slot.material
    for name, m in mats.items():
        base = re.sub(r"\.\d{3}$", "", name)
        if not m.use_nodes:
            continue
        if base in ("hero.hoodie_black", "hero.hoodie_rib", "hero.hoodie_seam", "hero.joggers_black"):
            if _lift_black(m):
                done[name] = "cloth_black"
        elif base in ("hero.cap_black", "hero.cap_underbrim"):
            if _lift_black(m, floor=(0.024, 0.024, 0.027), sheen=0.3):
                done[name] = "cap"
        elif base in ("jay.eyes", "jay.eyes_pupils"):
            if _cornea(m):
                done[name] = "cornea"
    if _skin(bpy.data.node_groups):
        done["SH-skin"] = "skin"
    return done
# <<< polish_light
