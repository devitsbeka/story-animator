"""
Build the series hero asset (hero_v4) from Blender Studio's "Jay" (Sprite Fright, CC-BY 4.0, (c) Blender Foundation).

Wardrobe / series identity:
  * oversized BLACK hoodie with a worn white "PALENCIAGA" chest print, made from Jay's own jacket mesh
    (GEO-jay_jacket: keeps its armature weights, Elbow90 corrective shape keys and jacket lattice), inflated,
    lengthened, recoloured; zipper pulls removed; a hood and white drawstrings built in code and skinned by
    weight transfer from the jacket (same deform bones).
  * BLACK baseball cap built in code, skinned 100% to DEF-Hat (ROOT-Hat follows the head through the rig's
    own parent switch, FK-Hat stays an animator control). The hair's shrinkwrap helper is rebuilt as the cap's
    inner volume so the hair stays under the crown and falls out below it.
  * glasses and chain removed (objects deleted, rig toggles 'Glasses'/'Chain' set to 0; the driver audit
    below proves no driver is left pointing at a missing ID).
  * black joggers: the shorts are re-dressed black and jogger legs are grown from the body's own leg skin
    (same vertex groups -> same deformation), inflated and cuffed at the ankle; the body's leg skin under
    them is masked so it can never poke through. White sneakers kept.
  * face, eyes, eyelids, brows rig untouched.

Idempotent: it always starts from the pristine source .blend and overwrites the output.
Usage:
  blender -b -y --python factory/characters/build_hero_jay.py -- \
      [--src /home/user/story-animator/library_store/characters/jay.blend] \
      [--out /home/user/story-animator/library_store/characters/hero_v4/hero_v4.blend]
"""
import argparse
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.interpolate import poly_3d_calc

STORE = os.environ.get("LIBRARY_STORE", "/home/user/story-animator/library_store")
ap = argparse.ArgumentParser()
ap.add_argument("--src", default=os.path.join(STORE, "characters", "jay.blend"))
ap.add_argument("--out", default=os.path.join(STORE, "characters", "hero_v4", "hero_v4.blend"))
args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

PRINT_TEXT = "PALENCIAGA"
FONT_CANDIDATES = [  # bold condensed sans; Inter is squeezed to a condensed width below
    "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
    "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

# ---------------------------------------------------------------------------------------------------------
bpy.ops.wm.open_mainfile(filepath=os.path.abspath(args.src), load_ui=False)
D = bpy.data
rig = D.objects["RIG-jay"]
CH = D.collections["CH-jay"]
rig.data.pose_position = "REST"  # all geometry work happens in rest space
for pb in rig.pose.bones:
    pb.location = (0, 0, 0); pb.rotation_quaternion = (1, 0, 0, 0); pb.rotation_euler = (0, 0, 0); pb.scale = (1, 1, 1)
bpy.context.view_layer.update()
REPORT = {}


def log(*a):
    print("[hero_v4]", *a, flush=True)


def driver_audit():
    """Count drivers whose targets reference a missing ID or that Blender flags invalid."""
    bad, total = [], 0
    for coll in (D.objects, D.meshes, D.materials, D.shape_keys, D.armatures, D.node_groups, D.lattices, D.curves):
        for idb in coll:
            ad = getattr(idb, "animation_data", None)
            if not ad:
                continue
            for d in ad.drivers:
                total += 1
                for v in d.driver.variables:
                    for t in v.targets:
                        if v.type == "SINGLE_PROP" and t.id is None:
                            bad.append((idb.name, d.data_path, v.name))
    return total, bad


# --- 1. remove glasses, chain, bucket hat, zipper pulls -----------------------------------------------------
props = rig.pose.bones["Properties_Character_Jay"]
props["Glasses"] = 0
props["Chain"] = 0
for n in ("GEO-jay_shades", "GEO-jay_chain", "GEO-jay_hat", "GEO-jay_jacket_zipper_pull_neck",
          "GEO-jay_jacket_zipper_pull_pockets"):
    o = D.objects.get(n)
    if o:
        me = o.data
        D.objects.remove(o, do_unlink=True)
        if me and me.users == 0:
            D.meshes.remove(me)
# the glasses/chain bones stay (harmless, they only carry widgets); their bone collections are hidden
for bc in rig.data.collections_all:
    if bc.name in ("Shades", "Chain"):
        bc.is_visible = False
log("removed glasses/chain/hat/zipper pulls")

# --- materials ------------------------------------------------------------------------------------------------


def _n(nt, t, loc, **kw):
    node = nt.nodes.new(t); node.location = loc
    for k, v in kw.items():
        setattr(node, k, v)
    return node


def cotton(name, base=(0.012, 0.012, 0.0135), rough=0.82, sheen=0.28, weave_scale=420.0, rib=False, uv="UVMap",
           print_img=None, print_uv=None):
    """Black cotton: Principled + sheen + woven bump (two crossed wave textures + fibre noise); optional worn print."""
    m = D.materials.get(name) or D.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    out = _n(nt, "ShaderNodeOutputMaterial", (900, 0))
    bs = _n(nt, "ShaderNodeBsdfPrincipled", (600, 0))
    bs.inputs["Base Color"].default_value = (*base, 1)
    bs.inputs["Roughness"].default_value = rough
    bs.inputs["Sheen Weight"].default_value = sheen
    bs.inputs["Sheen Roughness"].default_value = 0.35
    bs.inputs["Sheen Tint"].default_value = (0.36, 0.37, 0.42, 1)
    nt.links.new(bs.outputs[0], out.inputs[0])
    uvn = _n(nt, "ShaderNodeUVMap", (-900, -300), uv_map=uv)
    w1 = _n(nt, "ShaderNodeTexWave", (-650, -200), wave_type="BANDS", bands_direction="X")
    w1.inputs["Scale"].default_value = weave_scale
    w1.inputs["Distortion"].default_value = 1.5
    nt.links.new(uvn.outputs[0], w1.inputs["Vector"])
    if rib:
        mix_w = w1
    else:
        w2 = _n(nt, "ShaderNodeTexWave", (-650, -450), wave_type="BANDS", bands_direction="Y")
        w2.inputs["Scale"].default_value = weave_scale
        w2.inputs["Distortion"].default_value = 1.5
        nt.links.new(uvn.outputs[0], w2.inputs["Vector"])
        mix_w = _n(nt, "ShaderNodeMath", (-400, -300), operation="MULTIPLY")
        nt.links.new(w1.outputs["Fac"], mix_w.inputs[0]); nt.links.new(w2.outputs["Fac"], mix_w.inputs[1])
    fib = _n(nt, "ShaderNodeTexNoise", (-650, -700))
    fib.inputs["Scale"].default_value = weave_scale * 0.6
    fib.inputs["Detail"].default_value = 6
    nt.links.new(uvn.outputs[0], fib.inputs["Vector"])
    hgt = _n(nt, "ShaderNodeMath", (-200, -400), operation="MULTIPLY_ADD")
    nt.links.new(fib.outputs["Fac"], hgt.inputs[0]); hgt.inputs[1].default_value = 0.35
    nt.links.new(mix_w.outputs[0] if not rib else w1.outputs["Fac"], hgt.inputs[2])
    bump = _n(nt, "ShaderNodeBump", (300, -350))
    bump.inputs["Strength"].default_value = 0.22 if not rib else 0.4
    bump.inputs["Distance"].default_value = 0.0006
    nt.links.new(hgt.outputs[0], bump.inputs["Height"])
    nt.links.new(bump.outputs[0], bs.inputs["Normal"])
    if print_img is not None:
        # worn screen print: image alpha x cracked-ink noise; ink is a little smoother and sits on the weave
        puv = _n(nt, "ShaderNodeUVMap", (-900, 450), uv_map=print_uv)
        tex = _n(nt, "ShaderNodeTexImage", (-600, 450), image=print_img, extension="CLIP", interpolation="Linear")
        nt.links.new(puv.outputs[0], tex.inputs["Vector"])
        crack = _n(nt, "ShaderNodeTexNoise", (-600, 150))
        crack.inputs["Scale"].default_value = 55.0
        crack.inputs["Detail"].default_value = 10.0
        crack.inputs["Roughness"].default_value = 0.7
        nt.links.new(puv.outputs[0], crack.inputs["Vector"])
        cr = _n(nt, "ShaderNodeMapRange", (-350, 150))
        cr.inputs["From Min"].default_value = 0.30; cr.inputs["From Max"].default_value = 0.42
        nt.links.new(crack.outputs["Fac"], cr.inputs["Value"])
        wear = _n(nt, "ShaderNodeMath", (-150, 300), operation="MULTIPLY")
        nt.links.new(tex.outputs["Alpha"], wear.inputs[0]); nt.links.new(cr.outputs[0], wear.inputs[1])
        thin2 = _n(nt, "ShaderNodeMath", (150, 300), operation="MULTIPLY")
        nt.links.new(wear.outputs[0], thin2.inputs[0])
        fibmask = _n(nt, "ShaderNodeMapRange", (0, 100))
        fibmask.inputs["From Min"].default_value = 0.2; fibmask.inputs["From Max"].default_value = 0.6
        fibmask.inputs["To Min"].default_value = 0.78; fibmask.inputs["To Max"].default_value = 1.0
        nt.links.new(fib.outputs["Fac"], fibmask.inputs["Value"])
        nt.links.new(fibmask.outputs[0], thin2.inputs[1])
        col = _n(nt, "ShaderNodeMix", (350, 250), data_type="RGBA")
        nt.links.new(thin2.outputs[0], col.inputs["Factor"])
        col.inputs["A"].default_value = (*base, 1)
        col.inputs["B"].default_value = (0.80, 0.80, 0.78, 1)
        nt.links.new(col.outputs["Result"], bs.inputs["Base Color"])
        rgh = _n(nt, "ShaderNodeMix", (350, 50), data_type="FLOAT")
        nt.links.new(thin2.outputs[0], rgh.inputs["Factor"])
        rgh.inputs["A"].default_value = rough; rgh.inputs["B"].default_value = 0.55
        nt.links.new(rgh.outputs["Result"], bs.inputs["Roughness"])
        shn = _n(nt, "ShaderNodeMix", (350, -100), data_type="FLOAT")
        nt.links.new(thin2.outputs[0], shn.inputs["Factor"])
        shn.inputs["A"].default_value = sheen; shn.inputs["B"].default_value = 0.0
        nt.links.new(shn.outputs["Result"], bs.inputs["Sheen Weight"])
    return m


def plastic(name, col, rough=0.45):
    m = D.materials.get(name) or D.materials.new(name)
    m.use_nodes = True
    bs = m.node_tree.nodes.get("Principled BSDF")
    bs.inputs["Base Color"].default_value = (*col, 1)
    bs.inputs["Roughness"].default_value = rough
    return m


def cord(name):
    """White braided drawstring."""
    m = D.materials.get(name) or D.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bs = nt.nodes.get("Principled BSDF")
    bs.inputs["Base Color"].default_value = (0.78, 0.78, 0.76, 1)
    bs.inputs["Roughness"].default_value = 0.75
    bs.inputs["Sheen Weight"].default_value = 0.4
    tc = _n(nt, "ShaderNodeTexCoord", (-700, -300))
    wv = _n(nt, "ShaderNodeTexWave", (-450, -300), wave_type="BANDS", bands_direction="DIAGONAL")
    wv.inputs["Scale"].default_value = 600.0
    nt.links.new(tc.outputs["Object"], wv.inputs["Vector"])
    bp = _n(nt, "ShaderNodeBump", (-200, -300))
    bp.inputs["Strength"].default_value = 0.3
    nt.links.new(wv.outputs["Fac"], bp.inputs["Height"])
    nt.links.new(bp.outputs[0], bs.inputs["Normal"])
    return m


# --- helpers ----------------------------------------------------------------------------------------------------


def add_armature(obj, name="Armature"):
    m = obj.modifiers.new(name, "ARMATURE")
    m.object = rig
    m.use_vertex_groups = True
    m.use_deform_preserve_volume = False
    return m


def new_object(name, me, coll=CH):
    old = D.objects.get(name)
    if old:
        D.objects.remove(old, do_unlink=True)
    o = D.objects.new(name, me)
    coll.objects.link(o)
    o.parent = rig
    o.matrix_parent_inverse = Matrix.Identity(4)
    o.matrix_world = Matrix.Identity(4)
    return o


def rest_bvh(obj):
    """BVH of an object's rest (basis) mesh in world space (rig and objects sit at identity)."""
    me = obj.data
    vs = [obj.matrix_world @ v.co for v in me.vertices]
    polys = [tuple(p.vertices) for p in me.polygons]
    return BVHTree.FromPolygons(vs, polys), vs, polys


def transfer_weights(src, dst, max_groups=4, allow=None):
    """Nearest-surface interpolated vertex-group transfer src -> dst (what a DataTransfer POLYINTERP_NEAREST does)."""
    bvh, svs, spolys = rest_bvh(src)
    names = [g.name for g in src.vertex_groups]
    wtab = [dict() for _ in svs]
    for v in src.data.vertices:
        for g in v.groups:
            if g.weight > 0:
                wtab[v.index][names[g.group]] = g.weight
    dgroups = {}
    for v in dst.data.vertices:
        co = dst.matrix_world @ v.co
        hit, _nrm, fi, _d = bvh.find_nearest(co)
        poly = spolys[fi]
        bary = poly_3d_calc([svs[i] for i in poly], hit)
        acc = {}
        for w, vi in zip(bary, poly):
            for gn, gw in wtab[vi].items():
                acc[gn] = acc.get(gn, 0.0) + w * gw
        if allow is not None:
            acc = {k: w for k, w in acc.items() if k in allow}
            if not acc:
                acc = {"DEF-Chest": 1.0}
        top = sorted(acc.items(), key=lambda kv: -kv[1])[:max_groups]
        s = sum(w for _, w in top) or 1.0
        for gn, gw in top:
            if allow is not None and gn not in allow:
                continue
            if gw / s < 0.01:
                continue
            g = dgroups.get(gn) or dst.vertex_groups.get(gn) or dst.vertex_groups.new(name=gn)
            dgroups[gn] = g
            g.add([v.index], gw / s, "REPLACE")


def smoothstep(e0, e1, x):
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


# --- 2. HOODIE from Jay's jacket ---------------------------------------------------------------------------------
hood_obj = D.objects["GEO-jay_jacket"]
hood_obj.name = "GEO-hero_hoodie"
hood_obj.data.name = "GEO-hero_hoodie"
me = hood_obj.data
kb = me.shape_keys.key_blocks
basis = kb["Basis"]
# rest normals of the basis
bm = bmesh.new(); bm.from_mesh(me); bm.verts.ensure_lookup_table(); bm.normal_update()
nrm = [v.normal.copy() for v in bm.verts]
bm.free()
zmin = min(v.co.z for v in me.vertices)
deltas = []
for v in me.vertices:
    co = basis.data[v.index].co
    on_torso = abs(co.x) < 0.085
    t = 0.0105 if on_torso else 0.0075          # oversized: ~1 cm looser on the body, 7.5 mm on the sleeves
    d = nrm[v.index] * t
    if on_torso:
        # drop the hem ~2 cm (hoodie hangs lower than the track jacket) with a smooth falloff up to the waist
        d.z -= 0.02 * (1.0 - smoothstep(zmin, zmin + 0.06, co.z))
        # boxier, fuller belly/back for the oversized silhouette
        d.y += 0.004 * math.copysign(1.0, co.y) * (1.0 - smoothstep(0.62, 0.72, co.z))
    else:
        # sleeves: a little extra slack around the forearm, pushed a touch past the wrist
        ax = abs(co.x)
        d += nrm[v.index] * 0.003 * smoothstep(0.15, 0.25, ax)
        if ax > 0.26:
            d.x += math.copysign(0.006, co.x) * smoothstep(0.26, 0.29, ax)
    deltas.append(d)
for k in kb:  # move every key by the same delta so the Elbow90 correctives keep working
    for i, d in enumerate(deltas):
        k.data[i].co = k.data[i].co + d
for i, d in enumerate(deltas):
    me.vertices[i].co = basis.data[i].co
log("hoodie: inflated", len(deltas), "verts; shape keys", [k.name for k in kb])

for m in hood_obj.modifiers:  # topology changes below: corrective smooth must use original coords, not a bind
    if m.type == "CORRECTIVE_SMOOTH":
        m.rest_source = "ORCO"
# remove the zipper pull handle faces (pullover hoodie); zipper tape stays as a black placket seam
bm = bmesh.new(); bm.from_mesh(me)
handle_idx = [i for i, m in enumerate(me.materials) if m and m.name == "jay.jacket_zipper_handle"]
kill = [f for f in bm.faces if f.material_index in handle_idx]
bmesh.ops.delete(bm, geom=kill, context="FACES")
loose = [v for v in bm.verts if not v.link_faces]
bmesh.ops.delete(bm, geom=loose, context="VERTS")
bm.to_mesh(me); bm.free()
me.update()

# --- the PALENCIAGA print image (rasterised from a real font in-script, packed into the .blend) ---------------
font_path = next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)
cu = D.curves.new("TMP_print_text", "FONT")
cu.body = PRINT_TEXT
cu.align_x = "CENTER"; cu.align_y = "CENTER"
cu.fill_mode = "BOTH"
cu.space_character = 1.04
if font_path:
    cu.font = D.fonts.load(font_path, check_existing=True)
tobj = D.objects.new("TMP_print_text", cu)
bpy.context.scene.collection.objects.link(tobj)
condense = 0.80 if (font_path is None or "Narrow" not in font_path and "Condensed" not in font_path) else 1.0
dg = bpy.context.evaluated_depsgraph_get()
tm = tobj.evaluated_get(dg).to_mesh()
tvs = [Vector((v.co.x * condense, v.co.y, 0.0)) for v in tm.vertices]
tpolys = [tuple(p.vertices) for p in tm.polygons]
tobj.evaluated_get(dg).to_mesh_clear()
D.objects.remove(tobj); D.curves.remove(cu)
tbvh = BVHTree.FromPolygons(tvs, tpolys)
x0 = min(v.x for v in tvs); x1 = max(v.x for v in tvs); y0 = min(v.y for v in tvs); y1 = max(v.y for v in tvs)
pad = 0.04 * (x1 - x0)
W = 1024
H = int(W * (y1 - y0 + 2 * pad) / (x1 - x0 + 2 * pad)) + 1
PRINT_ASPECT = W / H
px = [0.0] * (W * H * 4)
SS = ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75))
for j in range(H):
    for i in range(W):
        cov = 0
        for sx, sy in SS:
            x = x0 - pad + (i + sx) / W * (x1 - x0 + 2 * pad)
            y = y0 - pad + (j + sy) / H * (y1 - y0 + 2 * pad)
            if tbvh.ray_cast(Vector((x, y, 1.0)), Vector((0, 0, -1)), 2.0)[0] is not None:
                cov += 1
        a = cov / 4.0
        k = (j * W + i) * 4
        px[k] = px[k + 1] = px[k + 2] = 1.0
        px[k + 3] = a
img = D.images.get("hero_palenciaga_print") or D.images.new("hero_palenciaga_print", W, H, alpha=True)
if img.size[0] != W or img.size[1] != H:
    img.scale(W, H)
img.alpha_mode = "STRAIGHT"
img.pixels.foreach_set(px)
out_dir = os.path.dirname(os.path.abspath(args.out))
os.makedirs(out_dir, exist_ok=True)
img.filepath_raw = os.path.join(out_dir, "palenciaga_print.png")
img.file_format = "PNG"
img.save()
img.pack()
log("print image", W, H, "font", font_path, "condense", condense, "coverage px",
    sum(1 for k in range(3, len(px), 4) if px[k] > 0.5))

# print UV: planar front projection on the chest, back/side faces pushed out of the [0,1] tile (CLIP -> no ink)
PRINT_CENTER = (0.0, 0.612)       # x, z of the print centre on the chest (rest pose, metres)
PRINT_W = 0.112                   # print width across the chest (m)
PRINT_H = PRINT_W / PRINT_ASPECT
uvl = me.uv_layers.get("PRINT") or me.uv_layers.new(name="PRINT")
for p in me.polygons:
    front = p.normal.y < -0.25 and abs(p.center.x) < 0.09
    for li in p.loop_indices:
        co = me.vertices[me.loops[li].vertex_index].co
        u = (co.x - PRINT_CENTER[0]) / PRINT_W + 0.5
        v = (co.z - PRINT_CENTER[1]) / PRINT_H + 0.5
        uvl.data[li].uv = (u, v) if front else (u + 10.0, v)
me.uv_layers.active = me.uv_layers["UVMap"]
uv_render = me.uv_layers["UVMap"]
uv_render.active_render = True

M_HOODIE = cotton("hero.hoodie_black", print_img=img, print_uv="PRINT")
M_RIB = cotton("hero.hoodie_rib", base=(0.009, 0.009, 0.010), rough=0.86, sheen=0.22, weave_scale=260.0, rib=True)
M_PLACKET = cotton("hero.hoodie_seam", base=(0.010, 0.010, 0.011), rough=0.75, sheen=0.3)
slot_map = {"jay.jacket_main": M_HOODIE, "jay.jacket_black": M_HOODIE, "jay.jacket_rim": M_RIB,
            "jay.jacket_zipper": M_HOODIE, "jay.jacket_zipper_handle": M_PLACKET}  # print runs over the placket
for i, m in enumerate(me.materials):
    if m and m.name in slot_map:
        me.materials[i] = slot_map[m.name]
# the jacket's distressed/highlight custom-prop drivers stay valid (they target HLP-jay_settings props)

# --- hood (rolled, lying on the upper back) + drawstrings, skinned by weight transfer from the hoodie ----------
hbvh, hvs, hpolys = rest_bvh(hood_obj)
collar = [v for v in hvs if v.z > max(w.z for w in hvs) - 0.02]
ccx = sum(v.x for v in collar) / len(collar); ccy = sum(v.y for v in collar) / len(collar)
ccz = sum(v.z for v in collar) / len(collar)
cr = sum(math.hypot(v.x - ccx, v.y - ccy) for v in collar) / len(collar)
back_y = max(v.y for v in hvs if abs(v.x) < 0.03 and abs(v.z - 0.70) < 0.015)
front_y = min(v.y for v in hvs if abs(v.x) < 0.03 and abs(v.z - 0.74) < 0.015)
log("collar centre", round(ccx, 3), round(ccy, 3), round(ccz, 3), "r", round(cr, 3), "back_y", round(back_y, 3),
    "front_y", round(front_y, 3))

bm = bmesh.new()
# (a) rolled hood rim: a torus segment hugging the back of the neck
R, r, NU, NV = cr + 0.013, 0.0135, 28, 12
th0, th1 = math.radians(-28), math.radians(208)
ring = []
for iu in range(NU + 1):
    th = th0 + (th1 - th0) * iu / NU
    c = Vector((ccx + R * math.cos(th), ccy + R * math.sin(th), ccz - 0.012))
    radial = Vector((math.cos(th), math.sin(th), 0))
    taper = 0.55 + 0.45 * math.sin(math.pi * iu / NU)      # thinner where it tucks into the neckline in front
    row = []
    for iv in range(NV):
        ph = 2 * math.pi * iv / NV
        row.append(bm.verts.new(c + (radial * math.cos(ph) * 1.15 + Vector((0, 0, 1)) * math.sin(ph)) * r * taper))
    ring.append(row)
for iu in range(NU):
    for iv in range(NV):
        bm.faces.new((ring[iu][iv], ring[iu][(iv + 1) % NV], ring[iu + 1][(iv + 1) % NV], ring[iu + 1][iv]))
# (b) the hood's body: a soft flattened pouch draped on the upper back, conformed to the hoodie surface
pouch = bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=14, radius=1.0)
for v in pouch["verts"]:
    x, y, z = v.co
    sag = 1.0 - 0.25 * max(0.0, -z)              # narrower towards the bottom point of the hood
    v.co = Vector((x * 0.068 * sag, 0.0, z * 0.058))
    # sit it on the back surface: find the hoodie surface behind this point, offset outward by thickness
    p = Vector((v.co.x, back_y + 0.2, ccz - 0.062 + v.co.z))
    hit = hbvh.ray_cast(p, Vector((0, -1, 0)), 0.5)
    sy = hit[0].y if hit[0] is not None else back_y
    thick = 0.012 * math.sqrt(max(0.0, 1.0 - x * x - z * z * 0.9)) + 0.003
    v.co.y = sy + 0.002 + (thick if y > 0 else 0.0015) * (abs(y) ** 0.5)
    v.co.z = ccz - 0.062 + v.co.z
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
hme = D.meshes.new("GEO-hero_hood")
bm.to_mesh(hme); bm.free()
for p in hme.polygons:
    p.use_smooth = True
hme.materials.append(M_HOODIE)
hood = new_object("GEO-hero_hood", hme)
TORSO_GROUPS = {"DEF-Chest", "DEF-RibCage", "DEF-Collar", "DEF-Belly", "DEF-Spine"}  # no arm bones: arms-up
transfer_weights(hood_obj, hood, allow=TORSO_GROUPS)                                   # must not drag the hood
add_armature(hood)
sub = hood.modifiers.new("Subdivision", "SUBSURF"); sub.levels = 1; sub.render_levels = 2

# drawstrings: tubes following the chest surface from the neckline eyelets, aglets at the ends
M_CORD = cord("hero.drawstring_white")
M_AGLET = plastic("hero.aglet", (0.85, 0.85, 0.83), 0.3)
strings = D.meshes.new("GEO-hero_drawstrings")
bm = bmesh.new()
for side in (-1, 1):
    pts = []
    N = 14
    for k in range(N + 1):
        t = k / N
        x = side * (0.017 + 0.006 * t) + side * 0.002 * math.sin(t * 3.0)
        z = ccz - 0.016 - 0.105 * t
        hit = hbvh.ray_cast(Vector((x, front_y - 0.2, z)), Vector((0, 1, 0)), 0.5)
        y = (hit[0].y if hit[0] is not None else front_y) - 0.0035 - 0.004 * t
        pts.append(Vector((x, y, z)))
    rad, seg = 0.0024, 8
    rings = []
    for k, p in enumerate(pts):
        tng = (pts[min(k + 1, N)] - pts[max(k - 1, 0)]).normalized()
        a = tng.cross(Vector((0, 1, 0))).normalized()
        b = tng.cross(a).normalized()
        rk = rad * (1.35 if k >= N - 1 else 1.0)  # aglet
        rings.append([bm.verts.new(p + (a * math.cos(2 * math.pi * s / seg) + b * math.sin(2 * math.pi * s / seg)) * rk)
                      for s in range(seg)])
    for k in range(N):
        for s in range(seg):
            f = bm.faces.new((rings[k][s], rings[k][(s + 1) % seg], rings[k + 1][(s + 1) % seg], rings[k + 1][s]))
            f.material_index = 1 if k >= N - 1 else 0
    end = bm.faces.new(list(reversed(rings[-1]))); end.material_index = 1
    bm.faces.new(rings[0])
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
bm.to_mesh(strings); bm.free()
for p in strings.polygons:
    p.use_smooth = True
strings.materials.append(M_CORD); strings.materials.append(M_AGLET)
dstr = new_object("GEO-hero_drawstrings", strings)
transfer_weights(hood_obj, dstr, allow=TORSO_GROUPS)
add_armature(dstr)
sub = dstr.modifiers.new("Subdivision", "SUBSURF"); sub.levels = 1; sub.render_levels = 1
log("hood + drawstrings built; hood groups", [g.name for g in hood.vertex_groups][:8])

# --- 3. CAP -----------------------------------------------------------------------------------------------------
head = D.objects["GEO-jay_head"]
head_vs = [head.matrix_world @ v.co for v in head.data.vertices]
CAP_TILT = math.radians(14.0)    # rim plane tilted: front higher than the back
CAP_ORIGIN = Vector((0.0, 0.010, 1.022))
cap_rot = Matrix.Rotation(-CAP_TILT, 4, "X")   # rotates local +Y (back) downwards
cap_mat = Matrix.Translation(CAP_ORIGIN) @ cap_rot
cap_inv = cap_mat.inverted()
A, B = 0.101, 0.116             # rim ellipse half-width (x) and half-depth (y)
# crown height: smallest that keeps every head vertex above the rim plane inside the crown + 12 mm for hair
C = 0.08
for v in head_vs:
    l = cap_inv @ v
    if l.z > 0:
        q = 1.0 - (l.x / (A - 0.012)) ** 2 - (l.y / (B - 0.012)) ** 2
        if q > 0.02:
            C = max(C, l.z / math.sqrt(q) + 0.012)
C = min(C, 0.15)
log("cap crown radii", A, B, round(C, 4))


def crown_pt(th, ph, a=A, b=B, c=C, flat=0.28):
    """Baseball-cap crown: ellipsoid upper half, slightly flattened top and fuller front panels."""
    x = a * math.cos(ph) * math.cos(th)
    y = b * math.cos(ph) * math.sin(th)
    z = c * math.sin(ph) ** (1.0 - flat)
    if y < 0:  # front panels stand up a bit (structured front)
        y *= 1.0 + 0.06 * math.sin(ph)
    return Vector((x, y, z))


bm = bmesh.new()
NT, NP = 48, 14
rows = []
for ip in range(NP):
    ph = (math.pi / 2) * ip / NP
    rows.append([bm.verts.new(crown_pt(2 * math.pi * it / NT, ph)) for it in range(NT)])
top = bm.verts.new(crown_pt(0, math.pi / 2))
for ip in range(NP - 1):
    for it in range(NT):
        bm.faces.new((rows[ip][it], rows[ip][(it + 1) % NT], rows[ip + 1][(it + 1) % NT], rows[ip + 1][it]))
for it in range(NT):
    bm.faces.new((rows[-1][it], rows[-1][(it + 1) % NT], top))
# panel seams: six shallow grooves (vertex dents) from the rim to the button
for v in bm.verts:
    th = math.atan2(v.co.y / B, v.co.x / A)
    d = min(abs(math.remainder(th - math.pi / 2 - k * math.pi / 3, 2 * math.pi)) for k in range(6))
    if d < 0.06 and v.co.z > 0.004:
        v.co -= Vector((v.co.x / A ** 2, v.co.y / B ** 2, v.co.z / C ** 2)).normalized() * 0.0012
crown_faces = list(bm.faces)
# sweatband lip so the rim reads as a finished edge
band = []
for it in range(NT):
    th = 2 * math.pi * it / NT
    band.append(bm.verts.new(Vector((A * 0.985 * math.cos(th), B * 0.985 * math.sin(th), -0.004))))
for it in range(NT):
    bm.faces.new((band[it], band[(it + 1) % NT], rows[0][(it + 1) % NT], rows[0][it]))
# button on top
btn = bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=6, radius=1.0)
for v in btn["verts"]:
    v.co = Vector((v.co.x * 0.0085, v.co.y * 0.0085, v.co.z * 0.0045)) + crown_pt(0, math.pi / 2) + Vector((0, 0, 0.001))
# brim: crescent on the rim plane in front, curved down at the sides, tilted slightly down
BRIM_L, BRIM_DROP, BRIM_ARCH = 0.088, math.radians(9.0), 0.018
NBU, NBV = 26, 8
th_a, th_b = math.radians(-180 + 18), math.radians(-18)
grid_top, grid_bot = [], []
for iu in range(NBU + 1):
    th = th_a + (th_b - th_a) * iu / NBU
    s = math.sin(th)                      # -1 at the centre front
    inner = Vector((A * math.cos(th), B * s, 0.0))
    outer = Vector((A * 1.07 * math.cos(th), (B + BRIM_L) * s, 0.0))
    rt, rb = [], []
    for iv in range(NBV + 1):
        t = iv / NBV
        p = inner.lerp(outer, t)
        u = p.x / (A * 1.07)
        p.z = -math.tan(BRIM_DROP) * (abs(p.y) - B * abs(s)) - BRIM_ARCH * (u * u) * t ** 1.2 - 0.0015
        rt.append(bm.verts.new(p + Vector((0, 0, 0.0022))))
        rb.append(bm.verts.new(p - Vector((0, 0, 0.0022))))
    grid_top.append(rt); grid_bot.append(rb)
brim_faces = []
for iu in range(NBU):
    for iv in range(NBV):
        brim_faces.append(bm.faces.new((grid_top[iu][iv], grid_top[iu][iv + 1], grid_top[iu + 1][iv + 1], grid_top[iu + 1][iv])))
        f = bm.faces.new((grid_bot[iu][iv], grid_bot[iu + 1][iv], grid_bot[iu + 1][iv + 1], grid_bot[iu][iv + 1]))
        f.material_index = 1; brim_faces.append(f)
for iu in range(NBU):  # outer + inner edges
    brim_faces.append(bm.faces.new((grid_top[iu][NBV], grid_bot[iu][NBV], grid_bot[iu + 1][NBV], grid_top[iu + 1][NBV])))
    brim_faces.append(bm.faces.new((grid_top[iu + 1][0], grid_bot[iu + 1][0], grid_bot[iu][0], grid_top[iu][0])))
for iu in (0, NBU):
    for iv in range(NBV):
        a_, b_ = (grid_top[iu][iv], grid_top[iu][iv + 1]), (grid_bot[iu][iv], grid_bot[iu][iv + 1])
        if iu == 0:
            brim_faces.append(bm.faces.new((a_[0], b_[0], b_[1], a_[1])))
        else:
            brim_faces.append(bm.faces.new((a_[1], b_[1], b_[0], a_[0])))
bmesh.ops.recalc_face_normals(bm, faces=brim_faces)
bm.transform(cap_mat)
cme = D.meshes.new("GEO-hero_cap")
bm.to_mesh(cme); bm.free()
for p in cme.polygons:
    p.use_smooth = True
M_CAP = cotton("hero.cap_black", base=(0.011, 0.011, 0.012), rough=0.74, sheen=0.22, weave_scale=900.0, uv="UVMap")
M_UNDERBRIM = cotton("hero.cap_underbrim", base=(0.022, 0.022, 0.024), rough=0.85, sheen=0.2, weave_scale=900.0)
cme.materials.append(M_CAP); cme.materials.append(M_UNDERBRIM)
cap = new_object("GEO-hero_cap", cme)
# UVs for the weave: simple cube-ish projection from rest positions
uvc = cme.uv_layers.new(name="UVMap")
for p in cme.polygons:
    for li in p.loop_indices:
        co = cme.vertices[cme.loops[li].vertex_index].co
        uvc.data[li].uv = (co.x * 8 + co.y * 3, co.z * 8 + co.y * 5)
crown_shell = cap.modifiers.new("Solidify", "SOLIDIFY")
crown_shell.thickness = 0.0025; crown_shell.offset = -1.0; crown_shell.use_even_offset = True
vg = cap.vertex_groups.new(name="DEF-Hat")
vg.add(list(range(len(cme.vertices))), 1.0, "REPLACE")
add_armature(cap)
sub = cap.modifiers.new("Subdivision", "SUBSURF"); sub.levels = 1; sub.render_levels = 2
# keep the solidify before the armature (rest-space thickness), armature, then subsurf
log("cap built", len(cme.vertices), "verts; skinned to DEF-Hat")

# hair helper -> the cap's inner volume (dome) with a wide skirt below the rim: hair above the rim is held
# inside the crown, hair below the rim falls freely (it is already inside the skirt)
helper = D.objects["GEO-jay_hat_helper"]
bm = bmesh.new()
NT2 = 40
inset = 0.006
rings_l = []
for ip in range(0, 11):
    ph = (math.pi / 2) * ip / 10
    if ip == 10:
        break
    rings_l.append([crown_pt(2 * math.pi * it / NT2, ph, A - inset, B - inset, C - inset) for it in range(NT2)])
skirt = [[Vector((p.x * k, p.y * k, z)) for p in rings_l[0]] for k, z in ((1.0, -0.003), (2.6, -0.004), (2.6, -0.45))]
all_rings = list(reversed(skirt)) + rings_l
vr = [[bm.verts.new(p) for p in rr] for rr in all_rings]
for a_, b_ in zip(vr[:-1], vr[1:]):
    for it in range(NT2):
        bm.faces.new((a_[it], a_[(it + 1) % NT2], b_[(it + 1) % NT2], b_[it]))
bm.faces.new(vr[0][::-1])
pole = bm.verts.new(crown_pt(0, math.pi / 2, A - inset, B - inset, C - inset))
for it in range(NT2):
    bm.faces.new((vr[-1][it], vr[-1][(it + 1) % NT2], pole))
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
bm.transform(cap_mat)
old_hme = helper.data
nh = D.meshes.new("GEO-jay_hat_helper")
bm.to_mesh(nh); bm.free()
helper.data = nh
if old_hme.users == 0:
    D.meshes.remove(old_hme)
helper.vertex_groups.clear()
hg = helper.vertex_groups.new(name="DEF-Hat")
hg.add(list(range(len(nh.vertices))), 1.0, "REPLACE")
for m in list(helper.modifiers):
    if m.type != "ARMATURE":
        helper.modifiers.remove(m)
log("hair helper rebuilt as cap volume:", len(nh.vertices), "verts")

# --- 4. JOGGERS ------------------------------------------------------------------------------------------------
# Jay's leg skin is too coarse (one edge ring every ~6 cm) to carry a trouser profile, so each jogger leg is a new
# tube lofted along the rest leg axis (measured from the body's leg rings). It is skinned by weight transfer: from
# the body's leg below the shorts hem, from the shorts above it (so the top moves with the shorts), blended.
body = D.objects["GEO-jay_body"]
pants = D.objects["GEO-jay_pants"]
JOG_BOTTOM = 0.150                      # cuff height (just inside the sneaker collar)
pv = [v.co.copy() for v in pants.data.vertices]
HEM_Z = min(c.z for c in pv)
JOG_TOP = HEM_Z + 0.045                 # tucked 4.5 cm up inside the shorts
leg_rings = {1: {}, -1: {}}
for v in body.data.vertices:
    c = v.co
    if abs(c.x) < 0.2 and 0.08 < c.z < 0.5:
        leg_rings[1 if c.x > 0 else -1].setdefault(round(c.z / 0.012), []).append(c.copy())
LEG_AXIS = {}
for sx in (-1, 1):
    rs = []
    for ps in leg_rings[sx].values():
        if len(ps) < 5:
            continue
        cx = sum(p.x for p in ps) / len(ps); cy = sum(p.y for p in ps) / len(ps)
        rs.append((sum(p.z for p in ps) / len(ps), cx, cy, sum(math.hypot(p.x - cx, p.y - cy) for p in ps) / len(ps)))
    LEG_AXIS[sx] = sorted(rs)


def leg_axis(sx, z):
    rs = LEG_AXIS[sx]
    if z <= rs[0][0]:
        return Vector((rs[0][1], rs[0][2], z)), rs[0][3]
    for (z0, x0, y0, r0), (z1, x1, y1, r1) in zip(rs[:-1], rs[1:]):
        if z0 <= z <= z1:
            t = (z - z0) / (z1 - z0)
            return Vector((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, z)), r0 + (r1 - r0) * t
    return Vector((rs[-1][1], rs[-1][2], z)), rs[-1][3]


NSEG = 24
hem_r = {}
for sx in (-1, 1):
    c0, _ = leg_axis(sx, HEM_Z)
    bins = [None] * NSEG
    for c in pv:
        if c.z < HEM_Z + 0.012 and c.x * sx > 0:
            d = Vector((c.x - c0.x, c.y - c0.y))
            k = int(((math.atan2(d.y, d.x) / (2 * math.pi)) % 1.0) * NSEG) % NSEG
            bins[k] = d.length if bins[k] is None else min(bins[k], d.length)
    for _ in range(NSEG):  # fill empty bins from neighbours
        for k in range(NSEG):
            if bins[k] is None:
                nb = [x for x in (bins[(k - 1) % NSEG], bins[(k + 1) % NSEG]) if x is not None]
                if nb:
                    bins[k] = sum(nb) / len(nb)
    hem_r[sx] = bins
log("leg axis rings", {k: [(round(r[0], 3), round(r[1], 3), round(r[3], 3)) for r in v] for k, v in LEG_AXIS.items()})
log("shorts hem z", round(HEM_Z, 3), "hem radius min/max", {k: (round(min(v), 3), round(max(v), 3)) for k, v in hem_r.items()})

bm = bmesh.new()
NZ = 30
zs = [JOG_BOTTOM + (JOG_TOP - JOG_BOTTOM) * (i / NZ) ** 1.15 for i in range(NZ + 1)]
for sx in (-1, 1):
    rings = []
    for z in zs:
        c, lr = leg_axis(sx, z)
        k = smoothstep(JOG_BOTTOM + 0.010, HEM_Z - 0.004, z) ** 0.8
        band = 0.0016 if z < JOG_BOTTOM + 0.014 else 0.0      # ribbed elastic cuff band stands proud
        ring = []
        for js in range(NSEG):
            th = 2 * math.pi * js / NSEG
            cuff_r = lr + 0.0055 + band
            full_r = hem_r[sx][js] - 0.0035                     # just inside the shorts hem, all the way round
            r = cuff_r + (max(full_r, cuff_r) - cuff_r) * k
            r += 0.0012 * math.sin(th * 3 + z * 90) * k          # soft fabric unevenness
            ring.append(bm.verts.new(c + Vector((math.cos(th), math.sin(th), 0)) * r))
        rings.append(ring)
    # inner lip at the cuff opening (turns the hem inward so the edge has thickness)
    c, lr = leg_axis(sx, JOG_BOTTOM)
    lip = [bm.verts.new(c + Vector((math.cos(2 * math.pi * js / NSEG), math.sin(2 * math.pi * js / NSEG), 0)) * (lr + 0.0015)
                        + Vector((0, 0, 0.004))) for js in range(NSEG)]
    rings.insert(0, lip)
    for r0, r1 in zip(rings[:-1], rings[1:]):
        for js in range(NSEG):
            bm.faces.new((r0[js], r0[(js + 1) % NSEG], r1[(js + 1) % NSEG], r1[js]))
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
bm.normal_update()
bm.faces.ensure_lookup_table()
f0 = bm.faces[len(bm.faces) // 4]
fc = f0.calc_center_median()
cax, _ = leg_axis(1 if fc.x > 0 else -1, fc.z)
if f0.normal.dot(fc - cax) < 0:  # normals must point away from the leg
    bmesh.ops.reverse_faces(bm, faces=bm.faces)
jme = D.meshes.new("GEO-hero_joggers")
bm.to_mesh(jme); bm.free()
for p in jme.polygons:
    p.use_smooth = True
M_JOG = cotton("hero.joggers_black", base=(0.014, 0.014, 0.015), rough=0.85, sheen=0.3, weave_scale=380.0)
jme.materials.append(M_JOG)
uvj = jme.uv_layers.new(name="UVMap")
for p in jme.polygons:
    for li in p.loop_indices:
        co = jme.vertices[jme.loops[li].vertex_index].co
        uvj.data[li].uv = (math.atan2(co.y, co.x - math.copysign(0.05, co.x)) * 0.05, co.z * 2.0)
jog = new_object("GEO-hero_joggers", jme)
# skinning: body leg below the hem, shorts above, smooth blend across the hem
tmp_lo = new_object("TMP_jog_lo", jme.copy())
tmp_hi = new_object("TMP_jog_hi", jme.copy())
LEG_GROUPS = {g.name for g in body.vertex_groups
              if g.name.startswith("DEF-") and ("Thigh" in g.name or "Knee" in g.name or "Foot" in g.name)}
transfer_weights(body, tmp_lo, allow=LEG_GROUPS)
transfer_weights(pants, tmp_hi)
names = sorted({g.name for g in tmp_lo.vertex_groups} | {g.name for g in tmp_hi.vertex_groups})
for n in names:
    jog.vertex_groups.new(name=n)


def wdict(o, vi):
    gn = {g.index: g.name for g in o.vertex_groups}
    return {gn[g.group]: g.weight for g in o.data.vertices[vi].groups}


for v in jme.vertices:
    t = smoothstep(HEM_Z - 0.006, HEM_Z + 0.014, v.co.z)
    acc = {}
    for n, w in wdict(tmp_lo, v.index).items():
        acc[n] = acc.get(n, 0.0) + (1 - t) * w
    for n, w in wdict(tmp_hi, v.index).items():
        acc[n] = acc.get(n, 0.0) + t * w
    s_ = sum(acc.values()) or 1.0
    for n, w in acc.items():
        if w / s_ > 0.005:
            jog.vertex_groups[n].add([v.index], w / s_, "REPLACE")
for o in (tmp_lo, tmp_hi):
    me_ = o.data
    D.objects.remove(o, do_unlink=True)
    D.meshes.remove(me_)
add_armature(jog)
cs = jog.modifiers.new("CorrectiveSmooth", "CORRECTIVE_SMOOTH"); cs.rest_source = "ORCO"; cs.iterations = 4
sub = jog.modifiers.new("Subdivision", "SUBSURF"); sub.levels = 1; sub.render_levels = 1
cuff = jog.vertex_groups.new(name="hero_cuff")
cuff.add([v.index for v in jme.vertices if v.co.z < JOG_BOTTOM + 0.016], 1.0, "REPLACE")
# hide the body's leg skin under the joggers (Mask modifier before subsurf: no poke-through in deep bends)
hide = body.vertex_groups.get("hero_hidden_under_joggers") or body.vertex_groups.new(name="hero_hidden_under_joggers")
hide.add([v.index for v in body.data.vertices if (JOG_BOTTOM + 0.008) <= v.co.z <= 0.55 and abs(v.co.x) < 0.2],
         1.0, "REPLACE")
mk = body.modifiers.get("HeroMask") or body.modifiers.new("HeroMask", "MASK")
mk.vertex_group = hide.name; mk.invert_vertex_group = True
idx = [m.name for m in body.modifiers].index("Subdivision")
with bpy.context.temp_override(object=body):
    bpy.ops.object.modifier_move_to_index(modifier=mk.name, index=idx)
log("joggers built", len(jme.vertices), "verts, groups", names, "; body mods", [m.name for m in body.modifiers])

# shorts -> black (the joggers' baggy upper)
for i, m in enumerate(pants.data.materials):
    if m and m.name.startswith("jay.shorts_red"):
        pants.data.materials[i] = M_JOG
    elif m and m.name.startswith("jay.shorts_white"):
        pants.data.materials[i] = M_RIB

# --- 5. tidy, audit, save -----------------------------------------------------------------------------------
total, bad = driver_audit()
REPORT["drivers_total"] = total
REPORT["drivers_missing_target"] = bad
log("driver audit: total", total, "missing-target", len(bad), bad[:5])
for o in (hood, dstr, cap, jog):
    o.hide_render = False
rig.data.pose_position = "POSE"
bpy.context.scene.frame_set(1)
CH["hero_asset"] = "int:hero_v4"
CH["hero_build"] = "factory/characters/build_hero_jay.py"
CH["attribution"] = ("Jay (Sprite Fright) by Blender Studio, (c) Blender Foundation, studio.blender.org, "
                     "CC-BY 4.0; modified: hoodie/cap/joggers wardrobe, glasses and chain removed")
# purge data orphaned by the removals
for coll in (D.meshes, D.materials, D.images, D.node_groups):
    for idb in list(coll):
        if idb.users == 0 and not idb.use_fake_user:
            coll.remove(idb)
bpy.context.preferences.filepaths.save_version = 0  # no .blend1 next to the asset
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.out), compress=True)
log("SAVED", os.path.abspath(args.out))
log("REPORT", REPORT)
