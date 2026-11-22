"""Glazing / door asset gate (lesson L019: windows were flat milky emissive panels).

  blender -b --factory-startup -P cloud/blender/test/glazing_check.py -- [--out glazing.json] [--strict]

Builds the hero yacht exactly as render_episode does (cloud/blender/yacht_v2.py + materials.apply_yacht_materials)
and scans every object or material whose name says glass / window / glazing / windscreen / door pane:
  GLAZE-EMIT   no emission on glass (lit windows glow from interior lights behind the glass, never from the pane)
  GLAZE-TRANS  glass transmits or is reflective-dark: transmission > 0.5, or roughness <= 0.15 (reflects the world)
Writes JSON {findings, summary}; --strict exits 1 on any failure.
"""
import argparse
import json
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
BL = os.path.dirname(HERE)
sys.path.insert(0, BL)

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--out", default=None)
ap.add_argument("--strict", action="store_true")
args = ap.parse_args(argv)
GLASSY = ("glass", "window", "glazing", "windscreen", "pane")


def is_glass(obj_name, mat_name):
    """the material says glass, or the object does and is not a frame/trim/gasket around the glass"""
    if any(k in mat_name.lower() for k in GLASSY):
        return True
    o = obj_name.lower()
    return any(k in o for k in GLASSY) and not o.startswith(("trim_", "frame_", "gasket_", "seal_"))


def bsdf_values(mat):
    if not mat or not mat.use_nodes:
        return None
    out = {"emission": 0.0, "transmission": 0.0, "roughness": None}
    for n in mat.node_tree.nodes:
        if n.type == "BSDF_PRINCIPLED":
            es = n.inputs.get("Emission Strength")
            ec = n.inputs.get("Emission Color")
            col = max(ec.default_value[:3]) if ec is not None else 1.0
            out["emission"] = max(out["emission"], (es.default_value if es is not None else 0.0) * col)
            tw = n.inputs.get("Transmission Weight") or n.inputs.get("Transmission")
            out["transmission"] = max(out["transmission"], tw.default_value if tw is not None else 0.0)
            r = n.inputs.get("Roughness")
            out["roughness"] = r.default_value if r is not None else None
        elif n.type == "EMISSION":
            s = n.inputs.get("Strength")
            out["emission"] = max(out["emission"], s.default_value if s is not None else 1.0)
    return out


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    import materials as yachtmats
    import yacht_v2
    root = bpy.data.objects.new("YachtRoot", None)
    bpy.context.scene.collection.objects.link(root)
    built = yacht_v2.build(root)
    objs = built["objs"]
    repo = os.path.dirname(os.path.dirname(BL))
    try:
        yachtmats.apply_yacht_materials(objs, store=os.environ.get("LIBRARY_STORE") or os.path.join(repo, "library_store"))
    except Exception as e:  # noqa: BLE001 - restyling is optional; the procedural materials are then what renders
        print(f"GLAZING materials restyle skipped: {e}")
    findings = []
    for o in objs:
        if o.type != "MESH":
            continue
        for slot in o.material_slots:
            m = slot.material
            if m is None or not is_glass(o.name, m.name):
                continue
            v = bsdf_values(m)
            if v is None:
                continue
            ctx = {"object": o.name, "material": m.name}
            findings.append(dict(ctx, rule="GLAZE-EMIT", status="pass" if v["emission"] <= 1e-3 else "fail",
                                 measured=round(v["emission"], 3), expected="no emission on glass"))
            ok_t = v["transmission"] > 0.5 or (v["roughness"] is not None and v["roughness"] <= 0.15)
            findings.append(dict(ctx, rule="GLAZE-TRANS", status="pass" if ok_t else "fail",
                                 measured={"transmission": round(v["transmission"], 2), "roughness": v["roughness"]},
                                 expected="transmission > 0.5 or roughness <= 0.15"))
    fails = [f for f in findings if f["status"] == "fail"]
    summ = {"checked": len(findings), "failed": len(fails), "ok": bool(findings) and not fails,
            "by_rule": {r: sorted({f["object"] for f in fails if f["rule"] == r}) for r in {f["rule"] for f in fails}}}
    if not findings:
        summ["note"] = "no glass-named objects found (naming contract broken?)"
    out = args.out or "/tmp/glazing_check.json"
    with open(out, "w") as fh:
        json.dump({"schema": "factory.glazing_check/1", "findings": fails, "summary": summ}, fh, indent=1, default=str)
    print("GLAZING SUMMARY", json.dumps(summ)[:600], "->", out)
    if args.strict and not summ["ok"]:
        sys.exit(1)


main()
