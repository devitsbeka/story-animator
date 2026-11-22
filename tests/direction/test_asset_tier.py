"""L008 regression: catalog tiers + 'camera < 10 m to an asset needs tier hero' (warn in previs, block in final)."""
import json
import os

import asset_tier as AT
import shot_validator as SV

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _shot(cam, sid="S1", props=None, actor="hero_v4"):
    keys = [{"f": f, "cam": list(cam), "look": [0.0, 2.0, 0.0], "fov": 40.0, "ease": "move"} for f in (0, 15, 29)]
    return {"id": sid, "from": 0, "to": 30, "yacht": {"x": 0.0, "z": 0.0, "heading": 0.0},
            "actors": [{"asset": actor, "space": "yacht", "local": [0.0, 1.42, -4.3], "height": 1.8}],
            "props": props or [], "camera": {"space": "yacht", "keys": keys}}


def _ep(*shots):
    return {"id": "t", "fps": 30, "width": 1080, "height": 1920, "durationFrames": 30, "shots": list(shots)}


def test_catalog_tiers_set():
    cat = AT.load_catalog()
    assert cat["int:yacht_14m"]["tier"] == "previs"
    assert cat["int:hero_v4"]["tier"] == "hero"
    for k in ("int:prop_radio", "int:prop_helm", "int:prop_lamp", "int:prop_beacon", "int:prop_phone", "int:prop_switches"):
        assert cat[k]["tier"] == "previs", k
    assert all(e.get("tier") in (None,) + AT.TIERS for e in cat.values())


def test_close_previs_yacht_warns_in_previs_and_fails_in_final():
    ep = _ep(_shot([3.0, 3.0, -8.0]))                     # camera on deck: the box yacht fills the frame (the L008 defect)
    prev = AT.tier_rule(ep, "previs")
    fin = AT.tier_rule(ep, "final")
    assert prev["status"] == "warn" and fin["status"] == "fail"
    refs = {f["ref"] for f in fin["findings"]}
    assert "yacht" in refs and "actor:hero_v4" not in refs     # the hero rig is tier hero


def test_far_camera_passes_and_placeholder_blocks_final():
    far = _shot([60.0, 30.0, -80.0], "FAR")
    assert AT.tier_rule(_ep(far), "final")["status"] == "pass"
    ph = _shot([60.0, 30.0, -80.0], "PH", actor="hero")          # old hero.glb: not in the library = placeholder
    fin = AT.tier_rule(_ep(ph), "final")
    assert fin["status"] == "fail" and fin["findings"][0]["tier"] == "placeholder"
    assert AT.tier_rule(_ep(ph), "previs")["status"] == "warn"


def test_upgrading_the_tier_clears_the_rule():
    cat = AT.load_catalog()
    cat = json.loads(json.dumps(cat))
    cat["int:yacht_14m"]["tier"] = "hero"
    cat["int:prop_helm"]["tier"] = "hero"
    ep = _ep(_shot([3.0, 3.0, -8.0], props=[{"prop": "helm", "attach": "yacht", "local": [0.55, 1.42, -3.72]}]))
    assert AT.tier_rule(ep, "final", catalog=cat)["status"] == "pass"


def test_validator_carries_tier_rule_with_mode():
    ep = _ep(_shot([3.0, 3.0, -8.0]))
    st = {r["id"]: r["status"] for r in SV.validate(ep)["rules"]}
    assert st["TIER"] == "warn"
    st = {r["id"]: r["status"] for r in SV.validate(ep, "final")["rules"]}
    assert st["TIER"] == "fail"
