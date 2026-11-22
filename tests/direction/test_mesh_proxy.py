"""L012 regression: the camera-inside-geometry check (yacht glTF proxies + Blender-exported prop proxies) catches
the v3/v5 A02 (brown) and A04 (black) cameras inside the cabin, and passes cameras in the cockpit / outside."""
import json
import os

import mesh_proxy as MP
import shot_validator as SV

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_proxies_exported_and_fresh():
    y = MP.load("yacht")
    assert y and y["hull"] and any(b["part"].startswith("gelcoat_white_3") for b in y["boxes"])
    fresh = MP.export_yacht(os.path.join(ROOT, y["source"]))
    assert fresh["boxes"] == y["boxes"] and fresh["hull"] == y["hull"], "re-run: python3 factory/direction/mesh_proxy.py export"
    assert set(MP.load("props")["props"]) >= {"radio", "helm", "switches", "primrose", "cargo_hold"}


def test_points():
    assert MP.yacht_hits([0.0, 2.6, 0.0]) == ["gelcoat_white_3"] or "gelcoat_white_3" in MP.yacht_hits([0.0, 2.6, 0.0])  # in the cabin
    assert MP.yacht_hits([0.0, 0.5, 0.0]) == ["hull"]                    # below deck
    assert MP.yacht_hits([0.55, 2.5, -4.8]) == []                         # cockpit, head height
    assert MP.yacht_hits([3.5, 1.0, 0.0]) == []                           # outside the topsides
    assert MP.yacht_hits([1.2, 0.5, 6.6]) == []                           # beside the narrow bow (not the 2.2 m beam box)


def test_original_defect_shots_flagged():
    ep = json.load(open(os.path.join(ROOT, "episodes", "sentinel", "episode_v5.json")))
    shots = {s["id"]: s for s in ep["shots"]}
    assert MP.shot_hits(shots["A02"]) and MP.shot_hits(shots["A04"])
    for ok in ("A01a", "A01b", "B11", "C21", "D25"):                       # deck / orbit / interior-set cameras are fine
        assert not MP.shot_hits(shots[ok]), ok


def test_prop_proxy_transform():
    p = {"prop": "helm", "attach": "yacht", "local": [0.55, 1.42, -3.72], "rotY": 3.141592653589793}
    boxes = MP.prop_boxes(p)
    assert boxes and all(b["min"][1] >= 1.3 for b in boxes)
    c = [(b["min"][i] + b["max"][i]) / 2 for b in boxes[:1] for i in range(3)]
    assert any(MP.inside_box(c, b) for b in boxes)
    assert MP.prop_boxes({"prop": "cargo_hold", "attach": "world", "local": [0, 3, -2600]}) == []   # enclosure set


def test_validator_proxy_rule():
    ep = json.load(open(os.path.join(ROOT, "episodes", "sentinel", "episode_v5.json")))
    sub = dict(ep, shots=[s for s in ep["shots"] if s["id"] in ("A01a", "A04")])
    r = {x["id"]: x for x in SV.validate(sub)["rules"]}["PROXY"]
    assert r["status"] == "fail" and r["shots"] == ["A04"]
