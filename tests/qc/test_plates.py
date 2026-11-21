import json
import os

import numpy as np
from PIL import Image

from factory.qc import plates
from helpers import hero_shot, make_episode


def _png(path, rgb, size=(27, 48)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    a = np.zeros((size[1], size[0], 3), np.uint8)
    a[:] = rgb
    a[0, 0] = (255, 255, 255)  # a highlight so normal frames are not "black"
    Image.fromarray(a).save(path)


def _manifest(d, f0, f1, res=(27, 48), warnings=()):
    with open(os.path.join(d, f"_render_{f0}_{f1}.json"), "w") as fh:
        json.dump({"frames": [f0, f1], "resolution": list(res), "warnings": list(warnings)}, fh)


def _by(rules):
    return {r["id"]: r for r in rules}


def test_clean_plates_pass(tmp_path):
    d = tmp_path / "S1"
    for f in range(0, 4):
        _png(str(d / f"{f:04d}.png"), (40, 50, 60))
    _manifest(str(d), 0, 3)
    ep = make_episode([hero_shot("S1", 0, 4)])
    rules, per = plates.plate_checks(str(tmp_path), ep)
    by = _by(rules)
    for rid in ("TQ-PLATE-DECODE", "TQ-PLATE-BLACK", "TQ-PLATE-OVEREXPOSED", "TQ-PLATE-MISSING-TEX", "TQ-PLATE-RES",
                "TQ-PLATE-FLICKER", "TQ-PLATE-MANIFEST", "TQ-PLATE-COUNT"):
        assert by[rid]["status"] == "pass", (rid, by[rid])
    assert len(per) == 4


def test_defects_are_caught(tmp_path):
    d = tmp_path / "S1"
    _png(str(d / "0000.png"), (40, 50, 60))
    _png(str(d / "0001.png"), (120, 130, 140))  # flicker jump
    a = np.zeros((48, 27, 3), np.uint8)
    Image.fromarray(a).save(str(d / "0002.png"))  # fully black
    _png(str(d / "0003.png"), (255, 0, 255))  # missing texture
    _png(str(d / "0004.png"), (255, 255, 255))  # blown out
    _png(str(d / "0005.png"), (40, 50, 60), size=(30, 48))  # wrong size
    (d / "0006.png").write_bytes(b"not a png")
    _manifest(str(d), 0, 7, warnings=["character 'hero' not found"])  # frame 7 missing
    ep = make_episode([hero_shot("S1", 0, 10)])
    by = _by(plates.plate_checks(str(tmp_path), ep)[0])
    assert by["TQ-PLATE-FLICKER"]["status"] == "fail"
    assert by["TQ-PLATE-BLACK"]["status"] == "fail"
    assert by["TQ-PLATE-MISSING-TEX"]["status"] == "fail"
    assert by["TQ-PLATE-OVEREXPOSED"]["status"] == "fail"
    assert by["TQ-PLATE-RES"]["status"] == "fail"
    assert by["TQ-PLATE-DECODE"]["status"] == "fail"
    assert by["TQ-PLATE-MANIFEST"]["status"] == "fail"
    assert by["TQ-PLATE-COUNT"]["status"] == "fail"
    assert by["TQ-PLATE-RENDER-WARNINGS"]["status"] == "warn"


def test_keyed_light_change_is_not_flicker(tmp_path):
    d = tmp_path / "S1"
    _png(str(d / "0000.png"), (120, 130, 140))
    _png(str(d / "0001.png"), (20, 25, 30))
    s = hero_shot("S1", 0, 2)
    s["yacht"]["lights"] = [[0, 1], [1, 0]]
    by = _by(plates.plate_checks(str(tmp_path), make_episode([s]), partial=True)[0])
    assert by["TQ-PLATE-FLICKER"]["status"] == "pass"


def test_partial_coverage_is_warning(tmp_path):
    _png(str(tmp_path / "S1" / "0000.png"), (40, 50, 60))
    ep = make_episode([hero_shot("S1", 0, 30)])
    by = _by(plates.plate_checks(str(tmp_path), ep, partial=True)[0])
    assert by["TQ-PLATE-COUNT"]["status"] == "warn"
    by = _by(plates.plate_checks(str(tmp_path), ep)[0])
    assert by["TQ-PLATE-COUNT"]["status"] == "fail"
