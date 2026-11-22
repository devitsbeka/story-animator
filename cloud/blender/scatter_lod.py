"""
scatter_lod.py - camera-aware level of detail for scattered library instances (island trees, understorey,
coast rocks) in render_episode.py.

Per shot, for every planned instance, it measures the largest size the instance reaches on screen over the
shot's frames and the closest it gets to the camera. It samples the shot's camera rig at a stride over the
WHOLE shot, not only the rendered chunk, so every farm chunk of a shot picks the same LOD and nothing pops
between chunks. Then each instance gets one of these tiers:

  cull  - outside the view frustum (plus a margin) on every sampled frame: not created at all
  far   - at most FAR_PX on screen: decimated proxy (6% of the faces) + 256 px textures
  mid   - up to HERO_PX: decimated proxy (18% of the faces) + 512 px textures
  full  - hero zone (in view closer than HERO_DIST metres, or bigger than the frame): the original 1k asset
          (re-saved as a .blend, because appending that is ~10x faster than importing the 60 MB glTF)

Screen sizes are measured at the episode's output resolution (1080x1920), not the preview size, so preview and
final renders choose the same tiers. Proxies are baked once per asset into <LIBRARY_STORE>/lod/<asset>/
(lod.json + <asset>_{full,mid,far}.blend + downsized textures). They are baked on demand the first time
they are needed, or ahead of time with:

  blender -b -P cloud/blender/scatter_lod.py -- --bake [--store /path/library_store] [--force]

A tier's collection is loaded only when some instance uses it: a shot whose trees are all far never loads the
full-detail trees. ISLAND_LOD=0 in the environment turns the LOD off (every instance at full, as before).

The planning math (camera samples, projection, tier choice) is pure Python and covered by
tests/blender/test_scatter_lod.py; only the bake and realize steps need bpy.
"""
import json
import math
import os
import sys
import time

# ----------------------------------------------------------------------------------------------
# config
# ----------------------------------------------------------------------------------------------
HERO_PX = 2400.0     # bigger than this (larger than the 1920 px frame) -> full mesh, 1k textures
FAR_PX = 160.0       # at most this -> far proxy
HERO_DIST = 40.0     # metres: full when in view closer than this (the hero zone around the camera)
MARGIN = 0.2         # frustum margin, as a fraction of the half-extent of the view
MAX_SAMPLES = 48     # camera samples per shot (stride over the shot's frames; first and last always in)
TIERS = ("full", "mid", "far")
BAKE = {             # tier -> (decimate ratio, texture size; None = keep the 1k source textures)
    "full": (1.0, None),   # the glTF as is, saved as .blend: appending it is ~10x faster than the glTF import
    "mid": (0.18, 512),
    "far": (0.06, 256),
}
BAKE_VERSION = 10

# assets a bake run prepares (asset id -> glTF path inside the library store); render_episode.dress_island uses these
ISLAND_ASSETS = {n: f"polyhaven/{n}/{n}_1k.gltf" for n in (
    "island_tree_01", "island_tree_02", "island_tree_03", "shrub_01", "fern_02",
    "coast_rocks_01", "coast_rocks_03", "coast_land_rocks_02")}


def enabled():
    return os.environ.get("ISLAND_LOD", "1").strip().lower() not in ("0", "off", "false", "no")


# ----------------------------------------------------------------------------------------------
# pure math (no bpy / mathutils): vectors are 3-tuples in Blender world space (Z up)
# ----------------------------------------------------------------------------------------------
def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def frame_samples(f0, f1, max_samples=MAX_SAMPLES):
    """Frames f0..f1 (inclusive) at an even stride, at most max_samples, first and last always included."""
    if f1 < f0:
        f0, f1 = f1, f0
    n = f1 - f0 + 1
    if n <= max_samples:
        return list(range(f0, f1 + 1))
    step = (n - 1) / float(max_samples - 1)
    out = sorted({f0 + int(round(i * step)) for i in range(max_samples)} | {f0, f1})
    return out


def camera_sample(matrix_rows, lens_mm, sensor_h_mm, aspect):
    """A camera sample from a 4x4 world matrix (rows) of a Blender camera (looks down local -Z, up local +Y),
    its focal length, the sensor height (sensor_fit VERTICAL) and the image aspect (width / height)."""
    m = matrix_rows
    pos = (m[0][3], m[1][3], m[2][3])
    right = (m[0][0], m[1][0], m[2][0])
    up = (m[0][1], m[1][1], m[2][1])
    fwd = (-m[0][2], -m[1][2], -m[2][2])
    tv = (sensor_h_mm / 2.0) / max(1e-6, lens_mm)
    return {"pos": pos, "right": right, "up": up, "fwd": fwd, "tan_v": tv, "tan_h": tv * aspect}


def project(sample, center, radius, height_px=1920.0, margin=MARGIN, extent=None):
    """-> (inside, size_px, dist): is a sphere (center, radius) inside the view frustum grown by `margin`, the
    on-screen size in pixels (of an image `height_px` tall) of the object's largest dimension `extent` (default:
    the sphere's diameter), and its distance to the camera."""
    d = _sub(center, sample["pos"])
    dist = math.sqrt(_dot(d, d))
    z = _dot(d, sample["fwd"])
    if z < -radius:
        return False, 0.0, dist
    x = _dot(d, sample["right"])
    y = _dot(d, sample["up"])
    zc = max(z, 1e-3)
    # sphere vs frustum side planes (half-angles grown by the margin); exact enough for culling purposes
    th = sample["tan_h"] * (1.0 + margin)
    tv = sample["tan_v"] * (1.0 + margin)
    ch = 1.0 / math.sqrt(1.0 + th * th)   # cos of the half-angle: plane distance factor
    cv = 1.0 / math.sqrt(1.0 + tv * tv)
    inside = (abs(x) - th * z) * ch <= radius and (abs(y) - tv * z) * cv <= radius
    if dist <= radius:
        return True, float(height_px) * 10.0, dist  # camera inside the bounds: as big as it gets
    ext = 2.0 * radius if extent is None else extent
    size = ext / (2.0 * zc * sample["tan_v"]) * height_px if z > 0 else 0.0
    return inside, size, dist


def classify(inside_any, max_px, min_dist, hero_px=HERO_PX, far_px=FAR_PX, hero_dist=HERO_DIST):
    """Tier for one instance from its whole-shot stats; None = cull."""
    if not inside_any:
        return None
    if min_dist < hero_dist or max_px > hero_px:
        return "full"
    if max_px > far_px:
        return "mid"
    return "far"


def plan_stats(spheres, samples, height_px=1920.0, margin=MARGIN):
    """spheres: [(center, radius[, extent])] -> [(inside_any, max_px, min_dist)] over all camera samples. inside_any
    uses the frustum grown by `margin` (what may cast shadows/reflections into view); max_px and min_dist only count
    frames where the object is really in view, so an edge-of-frame object stays cheap (numpy when
    available: ~4000 instances x ~100 samples is a few ms instead of tens of seconds)."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - Blender and the test env both ship numpy
        np = None
    if np is None or not spheres or not samples:
        out = []
        for sp in spheres:
            c, r = sp[0], sp[1]
            inside_any, mpx, mdist = False, 0.0, float("inf")
            for s in samples:
                ins, px, dist = project(s, c, r, height_px, margin, sp[2] if len(sp) > 2 else None)
                if ins:
                    inside_any = True
                    if project(s, c, r, height_px, 0.0)[0]:
                        mpx = max(mpx, px)
                        mdist = min(mdist, dist)
            out.append((inside_any, mpx, mdist))
        return out
    C = np.array([sp[0] for sp in spheres], dtype=float)                       # (N, 3)
    R = np.array([sp[1] for sp in spheres], dtype=float)[:, None]              # (N, 1) cull radius
    E = np.array([sp[2] if len(sp) > 2 else 2 * sp[1] for sp in spheres], dtype=float)[:, None]  # extent
    P = np.array([s["pos"] for s in samples], dtype=float)        # (S, 3)
    F = np.array([s["fwd"] for s in samples], dtype=float)
    X = np.array([s["right"] for s in samples], dtype=float)
    U = np.array([s["up"] for s in samples], dtype=float)
    TV = np.array([s["tan_v"] for s in samples], dtype=float)[None, :]
    TH = np.array([s["tan_h"] for s in samples], dtype=float)[None, :]
    D = C[:, None, :] - P[None, :, :]                             # (N, S, 3)
    dist = np.sqrt((D * D).sum(-1))
    z = (D * F[None]).sum(-1)
    x = (D * X[None]).sum(-1)
    y = (D * U[None]).sum(-1)
    th, tv = TH * (1.0 + margin), TV * (1.0 + margin)
    def inside_at(th, tv):
        ch, cv = 1.0 / np.sqrt(1.0 + th * th), 1.0 / np.sqrt(1.0 + tv * tv)
        return ((z >= -R) & ((np.abs(x) - th * z) * ch <= R) & ((np.abs(y) - tv * z) * cv <= R)) | (dist <= R)
    inside = inside_at(th, tv)
    strict = inside_at(TH, TV)
    size = np.where(z > 0, E / (2.0 * np.maximum(z, 1e-3) * TV) * height_px, 0.0)
    size = np.where(dist <= R, height_px * 10.0, size)
    mpx = np.where(strict, size, 0.0).max(1)
    mdist = np.where(strict, dist, np.inf).min(1)
    return list(zip(inside.any(1).tolist(), mpx.tolist(), mdist.tolist()))


def plan_tiers(spheres, samples, height_px=1920.0, margin=MARGIN, **kw):
    """spheres: [(center, radius[, extent])] -> list of tiers (None = cull), one per sphere, over all camera samples."""
    return [classify(i, px, d, **kw) for i, px, d in plan_stats(spheres, samples, height_px, margin)]


def bounding_radius(meta, scale):
    """Conservative radius (metres) of a sphere centred on the instance origin that holds the scaled asset."""
    lo, hi = meta["bbox_min"], meta["bbox_max"]
    corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    return scale * max(math.sqrt(_dot(c, c)) for c in corners)


def summarize(tiers):
    out = {"cull": 0, "full": 0, "mid": 0, "far": 0}
    for t in tiers:
        out[t or "cull"] += 1
    return out


# ----------------------------------------------------------------------------------------------
# library store paths
# ----------------------------------------------------------------------------------------------
def lod_dir(store, asset_id):
    return os.path.join(store, "lod", asset_id)


def load_meta(store, asset_id):
    p = os.path.join(lod_dir(store, asset_id), "lod.json")
    try:
        with open(p) as fh:
            m = json.load(fh)
        if m.get("version") != BAKE_VERSION:
            return None
        for t in m.get("tiers", {}):
            if not os.path.exists(os.path.join(lod_dir(store, asset_id), m["tiers"][t]["blend"])):
                return None
        return m
    except (OSError, ValueError):
        return None


# ----------------------------------------------------------------------------------------------
# bpy part: bake proxies, plan per shot, realize instances
# ----------------------------------------------------------------------------------------------
def _bpy():
    import bpy  # noqa: WPS433 (only inside Blender)
    return bpy


def _import_gltf(path):
    bpy = _bpy()
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    return [o for o in bpy.data.objects if o not in before]


def _bbox(objs):
    from mathutils import Vector
    pts = [(o.matrix_world @ Vector(v)) for o in objs if o.type == "MESH" for v in o.bound_box]
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    return lo, hi


def _material_images(objs):
    seen = {}
    for o in objs:
        for slot in getattr(o, "material_slots", []):
            m = slot.material
            if not m or not m.use_nodes:
                continue
            for n in m.node_tree.nodes:
                im = getattr(n, "image", None)
                if n.type == "TEX_IMAGE" and im is not None:
                    seen.setdefault(im.name, im)
    return list(seen.values())


def _has_alpha(im):
    """True if the image carries real transparency (the glTF importer packs diffuse+alpha pairs as one RGBA image)."""
    if im.channels < 4 or not im.has_data and not im.size[0]:
        return False
    try:
        import numpy as np
        px = np.empty(im.size[0] * im.size[1] * im.channels, dtype=np.float32)
        im.pixels.foreach_get(px)
        return bool(px[3::im.channels].min() < 0.995)
    except Exception:
        return "alpha" in im.name


def _rebase_images(objs, size, tex_dir, tag):
    """Point every image the objects' materials use at a file instead of the copy the glTF importer packs into the
    .blend (a packed 1k image would load at 1k whatever its file says). size None: keep the source file; else write
    a copy scaled to <= size px into tex_dir and use that."""
    bpy = _bpy()
    ims = _material_images(objs)
    for im in ims:
        if size is None:
            if (im.packed_file is not None and im.filepath and os.path.exists(bpy.path.abspath(im.filepath))
                    and not _has_alpha(im)):
                im.unpack(method="REMOVE")
            continue
        os.makedirs(tex_dir, exist_ok=True)
        w, h = im.size[:]
        if max(w, h) > size:
            k = size / float(max(w, h))
            im.scale(max(1, int(w * k)), max(1, int(h * k)))
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in im.name.split(".0")[0])
        alpha = _has_alpha(im)
        ext = ".png" if alpha or os.path.splitext(im.filepath)[1].lower() == ".png" else ".jpg"
        out = os.path.join(tex_dir, f"{safe}_{tag}{ext}")
        im.filepath_raw = out
        im.file_format = "PNG" if out.endswith(".png") else "JPEG"
        if alpha:
            im.alpha_mode = "STRAIGHT"
        im.save()
        if im.packed_file is not None:
            im.unpack(method="REMOVE")
        im.filepath = out
        im.source = "FILE"
        im.reload()
    return len(ims)


def bake_asset(store, asset_id, rel, log=print, force=False):
    """Bake the mid/far proxies of one library asset into <store>/lod/<asset>/. Returns the meta dict.
    Imports the full glTF once, then decimates and downsizes step by step (mid, then far from mid)."""
    bpy = _bpy()
    if not force:
        m = load_meta(store, asset_id)
        if m:
            return m
    src = os.path.join(store, rel)
    if not os.path.exists(src):
        return None
    t0 = time.time()
    out_dir = lod_dir(store, asset_id)
    os.makedirs(out_dir, exist_ok=True)
    meta = {"version": BAKE_VERSION, "asset": asset_id, "source": rel, "tiers": {}}
    before = {k: set(getattr(bpy.data, k)) for k in ("meshes", "materials", "images", "textures", "node_groups")}
    objs = _import_gltf(src)
    bpy.context.view_layer.update()
    lo, hi = _bbox(objs)
    meta["bbox_min"], meta["bbox_max"] = lo, hi
    meta["height"] = (hi[2] - lo[2]) or 1.0
    meshes = [o for o in objs if o.type == "MESH"]
    faces0 = sum(len(o.data.polygons) for o in meshes)
    meta["faces_full"] = faces0
    coll = bpy.data.collections.new(f"_lodbake_{asset_id}")
    for o in objs:
        for uc in list(o.users_collection):
            uc.objects.unlink(o)
        coll.objects.link(o)
    bpy.context.scene.collection.children.link(coll)  # the depsgraph only evaluates modifiers of linked objects
    done_ratio = 1.0
    for tier, (ratio, tex) in sorted(BAKE.items(), key=lambda kv: -kv[1][0]):
        for o in meshes if ratio < done_ratio else []:
            mod = o.modifiers.new("lod", "DECIMATE")
            mod.decimate_type = "COLLAPSE"
            mod.ratio = min(1.0, ratio / done_ratio)
            mod.use_collapse_triangulate = True
            dg = bpy.context.evaluated_depsgraph_get()
            me = bpy.data.meshes.new_from_object(o.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
            old = o.data
            o.modifiers.remove(mod)
            o.data = me
            me.name = f"{old.name}_{tier}"
            if old.users == 0:
                bpy.data.meshes.remove(old)
        done_ratio = ratio
        n_img = _rebase_images(objs, tex, os.path.join(out_dir, f"tex{tex}"), f"{tex}")
        coll.name = f"LOD_{asset_id}_{tier}"
        faces = sum(len(o.data.polygons) for o in meshes)
        blend = f"{asset_id}_{tier}.blend"
        bpy.data.libraries.write(os.path.join(out_dir, blend), {coll}, path_remap="RELATIVE_ALL", compress=True)
        meta["tiers"][tier] = {"blend": blend, "collection": coll.name, "faces": faces, "ratio": ratio,
                               "texture_px": tex, "images": n_img}
    # clean the bake data out of this session (the caller may be building a shot)
    bpy.context.scene.collection.children.unlink(coll)
    for o in objs:
        me = o.data if o.type == "MESH" else None
        bpy.data.objects.remove(o, do_unlink=True)
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)
    bpy.data.collections.remove(coll)
    for k, old in before.items():  # only what the bake import created (no global purge: the shot is mid-build)
        bag = getattr(bpy.data, k)
        for idb in [x for x in bag if x not in old and x.users == 0]:
            bag.remove(idb)
    meta["baked_s"] = round(time.time() - t0, 1)
    with open(os.path.join(out_dir, "lod.json"), "w") as fh:
        json.dump(meta, fh, indent=1)
    log(f"[scatter_lod] baked {asset_id}: {meta['faces_full']} faces -> " +
        ", ".join(f"{t} {v['faces']} @{v['texture_px'] or 'source '}px" for t, v in meta["tiers"].items()) + f" in {meta['baked_s']}s")
    return meta


def _fcurves(idblock):
    ad = getattr(idblock, "animation_data", None)
    return list(ad.action.fcurves) if ad and ad.action else []


def camera_keyed_frames(cam):
    """Frames the camera object (or its lens) carries keys on."""
    fr = set()
    for fc in _fcurves(cam) + _fcurves(cam.data):
        fr.update(int(round(k.co[0])) for k in fc.keyframe_points)
    return sorted(fr)


def camera_matrix_at(cam, f):
    """(world Matrix, lens mm) of an unparented camera at frame f, straight from its fcurves (no frame_set)."""
    from mathutils import Matrix, Quaternion, Vector
    loc, quat = list(cam.location), list(cam.rotation_quaternion)
    for fc in _fcurves(cam):
        if fc.data_path == "location":
            loc[fc.array_index] = fc.evaluate(f)
        elif fc.data_path == "rotation_quaternion":
            quat[fc.array_index] = fc.evaluate(f)
    lens = cam.data.lens
    for fc in _fcurves(cam.data):
        if fc.data_path == "lens":
            lens = fc.evaluate(f)
    q = Quaternion(quat)
    q.normalize()
    return Matrix.Translation(Vector(loc)) @ q.to_matrix().to_4x4(), lens


def _append_collection(path, name):
    bpy = _bpy()
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.collections = [c for c in src.collections if c == name]
    return dst.collections[0] if dst.collections else None


class Planner:
    """Collects the instances dress_island wants (begin/add) and creates them per shot (realize)."""

    def __init__(self):
        self.items = []
        self.metas = {}
        self.report = {}

    def begin(self, store):
        self.items = []
        self.store = store
        self.report = {}

    def add(self, asset_id, rel, parent, matrix_basis_unscaled, target_h, name):
        """Plan one instance: its parent, its unit-scale local matrix (Blender), its height in metres and name."""
        self.items.append((asset_id, rel, parent, matrix_basis_unscaled, target_h, name))

    # -- per-asset data ----------------------------------------------------------------------
    def meta(self, asset_id, rel, log):
        if asset_id not in self.metas:
            m = load_meta(self.store, asset_id)
            if m is None and os.path.exists(os.path.join(self.store, rel)):
                if os.access(self.store, os.W_OK):
                    log(f"[scatter_lod] baking LOD proxies for {asset_id} (once; cached in {lod_dir(self.store, asset_id)})")
                    m = bake_asset(self.store, asset_id, rel, log=log)
                else:
                    log(f"[scatter_lod] {self.store} is read-only and {asset_id} has no baked LOD: full detail only")
            self.metas[asset_id] = m
        return self.metas[asset_id]

    def collection(self, asset_id, rel, tier, full_loader, log):
        bpy = _bpy()
        name = f"LOD_{asset_id}_{tier}"
        if name in bpy.data.collections:
            return bpy.data.collections[name]
        m = self.metas.get(asset_id)
        info = (m or {}).get("tiers", {}).get(tier)
        if not info:
            return full_loader(asset_id, rel)[0]
        c = _append_collection(os.path.join(lod_dir(self.store, asset_id), info["blend"]), info["collection"])
        if c is None:
            log(f"[scatter_lod] {asset_id} {tier} proxy failed to load; using full")
            return full_loader(asset_id, rel)[0]
        return c

    # -- per shot ------------------------------------------------------------------------------
    def realize(self, cam, frames, out_size, full_loader, log=print, cam_at=None):
        """Create the planned instances for one shot.
        cam: the keyed camera object (sensor_fit VERTICAL); frames: all of the shot's frames; out_size: (width,
        height) of the episode output; full_loader(asset_id, rel) -> (collection, height) imports the full-detail
        asset (render_episode.lib_collection); cam_at(f) -> (Blender 4x4 Matrix, vertical fov deg) covers the shot's
        frames the camera object is not keyed on (render chunks key only their own frames)."""
        bpy = _bpy()
        from mathutils import Matrix
        t0 = time.time()
        if not self.items:
            return {}
        use_lod = enabled()
        w, h = out_size
        aspect = w / float(h)
        sensor_h = cam.data.sensor_height
        samples = []
        keyed = camera_keyed_frames(cam)
        for f in frame_samples(min(keyed), max(keyed)) if keyed else []:
            mb, lens = camera_matrix_at(cam, f)
            samples.append(camera_sample([list(r) for r in mb], lens, sensor_h, aspect))
        if cam_at is not None:
            for f in frame_samples(min(frames), max(frames)):
                mb, fov = cam_at(f)
                lens = (sensor_h / 2.0) / math.tan(math.radians(fov) / 2.0)
                samples.append(camera_sample([list(r) for r in mb], lens, sensor_h, aspect))
        if not samples:
            use_lod = False
        # world spheres
        spheres, scales = [], []
        for asset_id, rel, parent, mbu, target_h, name in self.items:
            m = self.meta(asset_id, rel, log) if use_lod else None
            hgt = (m or {}).get("height") or full_loader(asset_id, rel)[1] or 1.0
            s = target_h / max(0.1, hgt)
            scales.append(s)
            wm = parent.matrix_world @ mbu
            c = tuple(wm.translation)
            r = bounding_radius(m, s) if m else target_h * 1.5
            ext = s * max(hi - lo for lo, hi in zip(m["bbox_min"], m["bbox_max"])) if m else 2 * r
            spheres.append((c, r, ext))
        if use_lod:
            tiers = plan_tiers(spheres, samples, height_px=float(h))
            # an asset without a bake can only be drawn full
            tiers = [t if (t is None or t == "full" or self.metas.get(it[0])) else "full" for t, it in zip(tiers, self.items)]
        else:
            tiers = ["full"] * len(self.items)
        t_plan = time.time() - t0
        made = 0
        for (asset_id, rel, parent, mbu, target_h, name), tier, s in zip(self.items, tiers, scales):
            if tier is None:
                continue
            coll = self.collection(asset_id, rel, tier, full_loader, log)
            if coll is None:
                continue
            e = bpy.data.objects.new(name, None)
            e.instance_type, e.instance_collection = "COLLECTION", coll
            bpy.context.scene.collection.objects.link(e)
            e.parent = parent
            e.matrix_basis = mbu @ Matrix.Scale(s, 4)
            e["lod"] = tier
            made += 1
        rep = {"enabled": use_lod, "instances": len(self.items), "created": made, "tiers": summarize(tiers),
               "samples": len(samples), "plan_s": round(t_plan, 2), "realize_s": round(time.time() - t0, 2)}
        by_asset = {}
        for it, t in zip(self.items, tiers):
            by_asset.setdefault(it[0], summarize([]))[t or "cull"] += 1
        rep["by_asset"] = by_asset
        self.report = rep
        self.items = []
        log(f"[scatter_lod] {rep['created']}/{rep['instances']} instances (tiers {rep['tiers']}) from {rep['samples']} camera samples; plan {rep['plan_s']}s, total {rep['realize_s']}s; by asset {by_asset}")
        return rep


PLANNER = Planner()


# ----------------------------------------------------------------------------------------------
# CLI: bake every island asset ahead of time
# ----------------------------------------------------------------------------------------------
def _main():
    import argparse
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(description="bake LOD proxies for the island library assets")
    p.add_argument("--bake", action="store_true")
    p.add_argument("--store", default=os.environ.get("LIBRARY_STORE") or os.path.join(os.getcwd(), "library_store"))
    p.add_argument("--force", action="store_true")
    p.add_argument("--only", nargs="*", default=None)
    a = p.parse_args(argv)
    if not a.bake:
        p.print_help()
        return
    bpy = _bpy()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for asset_id, rel in ISLAND_ASSETS.items():
        if a.only and asset_id not in a.only:
            continue
        if not os.path.exists(os.path.join(a.store, rel)):
            print(f"[scatter_lod] skip {asset_id}: {rel} not in {a.store}")
            continue
        bake_asset(a.store, asset_id, rel, force=a.force)


if __name__ == "__main__":
    _main()
