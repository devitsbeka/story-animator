"""
Build the series hero on the MPFB / MakeHuman base: production face topology, real eyeballs, brows, lashes,
teeth, tongue, ARKit-52 face units + Microsoft visemes as shape keys, game-engine/mixamo-compatible rig.
Usage: blender -b -P build_hero_mh.py -- --out assets/characters/hero_v3/hero_v3.blend [--style pixar]
"""
import bpy, sys, os, argparse, importlib
a = argparse.ArgumentParser()
a.add_argument("--out", default="/tmp/hero_v3.blend")
a.add_argument("--style", default="pixar")
args = a.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

mp = importlib.import_module("bl_ext.user_default.mpfb")
from bl_ext.user_default.mpfb.services.humanservice import HumanService
from bl_ext.user_default.mpfb.services.faceservice import FaceService
from bl_ext.user_default.mpfb.services.locationservice import LocationService
from bl_ext.user_default.mpfb.services.targetservice import TargetService

bpy.ops.wm.read_factory_settings(use_empty=True)
macro = {"gender": 1.0, "age": 0.42, "muscle": 0.5, "weight": 0.45, "proportions": 0.5, "height": 0.5, "cupsize": 0.5, "firmness": 0.5,
         "race": {"african": 0.15, "asian": 0.15, "caucasian": 0.7}}
basemesh = HumanService.create_human(macro_detail_dict=macro, scale=0.1)
print("BASEMESH", basemesh.name, len(basemesh.data.vertices))

# --- STYLE: stylised 'Pixar' proportions via MakeHuman targets (bigger head/eyes, softer features)
STYLE_TARGETS = {
    "pixar": {
        "head/head-scale-vert-incr": 0.35, "head/head-scale-horiz-incr": 0.25, "head/head-scale-depth-incr": 0.2,
        "eyes/r-eye-scale-incr": 0.45, "eyes/l-eye-scale-incr": 0.45,
        "nose/nose-scale-horiz-decr": 0.2, "chin/chin-prominent-decr": 0.2, "neck/neck-scale-horiz-decr": 0.15,
    },
}
loaded = []
for t, v in STYLE_TARGETS.get(args.style, {}).items():
    try:
        TargetService.load_target(basemesh, LocationService.get_mpfb_data("targets") + "/" + t + ".target.gz", weight=v, name=t.split("/")[-1])
        loaded.append(t)
    except Exception as e:
        print("STYLE target skipped", t, e)
print("STYLE", loaded)

data = LocationService.get_user_data
def asset(*p):
    for base in (LocationService.get_user_data(""), LocationService.get_mpfb_data("")):
        f = os.path.join(base, *p)
        if os.path.exists(f):
            return f
    return None

for kind, rel in (("Eyes", ("eyes", "high-poly", "high-poly.mhclo")), ("Eyebrows", ("eyebrows", "eyebrow001", "eyebrow001.mhclo")),
                  ("Eyelashes", ("eyelashes", "eyelashes01", "eyelashes01.mhclo")), ("Teeth", ("teeth", "teeth_base", "teeth_base.mhclo")),
                  ("Tongue", ("tongue", "tongue01", "tongue01.mhclo"))):
    f = asset(*rel)
    if not f:
        d = asset(rel[0])
        print("MISSING", rel, os.listdir(d) if d else None)
        continue
    o = HumanService.add_mhclo_asset(f, basemesh, asset_type=kind, subdiv_levels=0, material_type="MAKESKIN")
    print("ADDED", kind, o.name if o else None)

skin = asset("skins", "young_caucasian_male", "young_caucasian_male.mhmat")
if skin:
    HumanService.set_character_skin(skin, basemesh, skin_type="ENHANCED_SSS")
FaceService.load_targets(basemesh, load_microsoft_visemes=True, load_arkit_faceunits=True)
print("SHAPEKEYS", len(basemesh.data.shape_keys.key_blocks) if basemesh.data.shape_keys else 0)
HumanService.add_builtin_rig(basemesh, "mixamo", import_weights=True)
try:
    FaceService.interpolate_targets(basemesh)
except Exception as e:
    print("interpolate failed", e)
os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.out))
print("SAVED", args.out, [o.name for o in bpy.data.objects])
