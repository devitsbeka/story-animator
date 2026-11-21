"""The Blender set assembler builds a kit identically twice (same kit + seed -> same objects, transforms, meshes) and
agrees with the pure-python plan hash. Needs Blender (BLENDER or /opt/blender/...); skipped when it is missing."""
import glob
import json
import os
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CANDIDATES = [os.environ.get("BLENDER", "")] + sorted(glob.glob("/opt/blender/blender-*/blender"))
BLENDER = next((b for b in CANDIDATES if b and os.path.exists(b)), None)


@pytest.mark.skipif(BLENDER is None, reason="Blender not installed")
@pytest.mark.parametrize("kit", ["abandoned_city_street", "jungle_clearing"])
def test_assembler_is_deterministic(kit, tmp_path):
    import sys
    sys.path.insert(0, ROOT)
    from factory.worlds import kits, layout
    env = dict(os.environ, LIBRARY_STORE=str(tmp_path))  # no textures/models needed: stand-in loaders + flat colours
    out = subprocess.run([BLENDER, "-b", "--factory-startup", "-noaudio", "-P", os.path.join(ROOT, "cloud", "blender", "test", "set_assembly_determinism.py"),
                          "--", kit], capture_output=True, text=True, timeout=600, env=env)
    line = next((l for l in out.stdout.splitlines() if l.startswith("DETERMINISM ")), None)
    assert line, out.stdout[-3000:] + out.stderr[-3000:]
    r = json.loads(line[len("DETERMINISM "):])
    a, b, c = r["a"], r["b"], r["other_seed"]
    assert a == b
    assert a["plan_hash"] == layout.layout(kits.load(kit))["hash"]       # Blender and the director share one plan
    assert c["digest"] != a["digest"] and c["plan_hash"] != a["plan_hash"]
    assert a["instances"] > 0 and a["meshes"] > 0
