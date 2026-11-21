"""World-kit registry: load, list and validate kits (factory/worlds/kits/<id>.json).

validate(kit) = JSON schema (kit.schema.json) + semantic checks:
  * every library id a kit uses (scatter assets, lib: pieces, ground textures) is in factory/library/catalog.json
    with files (sourced, sha256-hashed, licensed) - nothing unlicensed, nothing missing
  * proc:/prop: builders exist (cloud/blender/set_assembly.py PROC / props.py BUILDERS, read by AST, no bpy)
  * the lighting preset exists in cloud/blender/lighting.py PRESETS
  * marks and camera zones are inside the extent; no mark stands inside a piece footprint; every
    interaction target names a piece; ambience beds are catalog sounds or explicitly to_generate
"""
import ast
import functools
import json
import os

from jsonschema import Draft202012Validator

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
KITS_DIR = os.path.join(HERE, "kits")
SCHEMA = os.path.join(HERE, "kit.schema.json")
CATALOG = os.path.join(ROOT, "factory", "library", "catalog.json")
SET_ASSEMBLY_PY = os.path.join(ROOT, "cloud", "blender", "set_assembly.py")
PROPS_PY = os.path.join(ROOT, "cloud", "blender", "props.py")
LIGHTING_PY = os.path.join(ROOT, "cloud", "blender", "lighting.py")
OK_LICENCES = {"CC0-1.0", "proprietary (ours)"}


@functools.lru_cache(maxsize=1)
def schema():
    with open(SCHEMA) as fh:
        s = json.load(fh)
    Draft202012Validator.check_schema(s)
    return s


def kit_ids():
    return sorted(f[:-5] for f in os.listdir(KITS_DIR) if f.endswith(".json"))


def load(kit_id):
    with open(os.path.join(KITS_DIR, f"{kit_id}.json")) as fh:
        return json.load(fh)


def all_kits():
    return {k: load(k) for k in kit_ids()}


def _catalog():
    with open(CATALOG) as fh:
        return json.load(fh).get("assets", {})


def _dict_keys(path, name):
    with open(path) as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            if isinstance(node.value, ast.Dict):
                return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    return set()


@functools.lru_cache(maxsize=1)
def proc_builders():
    return _dict_keys(SET_ASSEMBLY_PY, "PROC") if os.path.exists(SET_ASSEMBLY_PY) else set()


@functools.lru_cache(maxsize=1)
def prop_builders():
    return _dict_keys(PROPS_PY, "BUILDERS")


@functools.lru_cache(maxsize=1)
def lighting_presets():
    return _dict_keys(LIGHTING_PY, "PRESETS")


def library_ids(kit):
    """Every catalog id the kit needs: (id, role)."""
    out = []
    t = kit.get("terrain", {})
    for key in ("material", "walk_material"):
        m = t.get(key) or {}
        if m.get("texture"):
            out.append((m["texture"], f"terrain.{key}"))
        if (m.get("steep") or {}).get("texture"):
            out.append((m["steep"]["texture"], f"terrain.{key}.steep"))
    bm = (t.get("backdrop") or {}).get("material") or {}
    if bm.get("texture"):
        out.append((bm["texture"], "terrain.backdrop"))
    for L in kit.get("scatter", []):
        out += [(a, f"scatter.{L['id']}") for a in L["assets"]]
    for p in kit.get("pieces", []):
        if p["builder"].startswith("lib:"):
            out.append((p["builder"][4:], f"pieces.{p['id']}"))
        for k in ("facade", "facades", "texture"):
            v = (p.get("opts") or {}).get(k)
            for tid in ([v] if isinstance(v, str) else v or []):
                out.append((tid, f"pieces.{p['id']}.opts.{k}"))
    return out


def validate(kit, catalog=None):
    """[] when the kit is valid, else human-readable problems."""
    errs = [f"schema {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message[:200]}"
            for e in sorted(Draft202012Validator(schema()).iter_errors(kit), key=lambda e: list(e.absolute_path))]
    if errs:
        return errs
    if kit.get("legacy"):
        return []
    cat = catalog if catalog is not None else _catalog()
    for cid, role in library_ids(kit):
        a = cat.get(cid)
        if a is None:
            errs.append(f"{role}: {cid} is not in the library catalog (fetch it with factory/library/sources/*)")
            continue
        if a.get("licence") not in OK_LICENCES:
            errs.append(f"{role}: {cid} licence {a.get('licence')!r} not allowed")
        if cid.split(":")[0] in ("ph", "acg") and not a.get("files"):
            errs.append(f"{role}: {cid} has no fetched files")
    for p in kit.get("pieces", []):
        b = p["builder"]
        if b.startswith("proc:") and proc_builders() and b[5:] not in proc_builders():
            errs.append(f"pieces.{p['id']}: unknown procedural builder {b} (set_assembly.PROC: {sorted(proc_builders())})")
        if b.startswith("prop:") and b[5:] not in prop_builders():
            errs.append(f"pieces.{p['id']}: unknown prop builder {b}")
    if kit["lighting"]["preset"] not in lighting_presets():
        errs.append(f"lighting.preset {kit['lighting']['preset']!r} is not a lighting.py preset")
    from . import layout as lay
    hx, hz = kit["extent"]["half"]
    pids = {p["id"] for p in kit.get("pieces", [])}
    plan = lay.layout(kit, with_grid=False)
    for name, m in plan["marks"].items():
        x, _, z = m["local"]
        if abs(x) > hx or abs(z) > hz:
            errs.append(f"mark {name} is outside the extent")
        for pc in plan["pieces"]:
            if kit["marks"][name]["kind"] != "sit" and pc.get("footprint") and ((x - pc["pos"][0]) ** 2 + (z - pc["pos"][2]) ** 2) ** 0.5 < pc["footprint"] * 0.6:
                errs.append(f"mark {name} stands inside piece {pc['id']}")
        t = kit["marks"][name].get("target")
        if t and t not in pids:
            errs.append(f"mark {name}: interaction target {t!r} is not a piece")
        if not any(lay.in_region(kit, cz["region"], x + 3 * dx, z + 3 * dz) for cz in kit["camera_zones"]
                   for dx, dz in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))):
            errs.append(f"mark {name}: no camera-safe zone within 3 m (it cannot be covered)")
    sounds = {k for k, v in cat.items() if v.get("kind") == "sfx"}
    for a in kit["ambience"]:
        if a.get("status") != "to_generate" and a["id"] not in sounds:
            errs.append(f"ambience {a['id']}: not a catalog sound (mark it status to_generate with a prompt)")
        if a.get("status") == "to_generate" and not a.get("prompt"):
            errs.append(f"ambience {a['id']}: to_generate needs a prompt")
    if not plan["instances"] and kit.get("scatter"):
        errs.append("scatter layers produced no instances (check regions/density/avoid rules)")
    return errs


def kit_marks(kit_id, seed=None):
    from . import layout as lay
    return lay.marks(load(kit_id), seed)


def sky_env(kit):
    """episode.json env for a kit: moonDir (= key direction) and dawn."""
    s = kit["sky"]
    return {"moonDir": list(s["key_dir"]), "dawn": float(s.get("dawn", 0.0))}
