"""World kits: schema, library provenance, deterministic layout, librarian mapping, stage-4 staging on kit marks."""
import copy
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from factory.director import checks, compile as comp, librarian, schemas  # noqa: E402
from factory.worlds import kits, layout, match  # noqa: E402

STARTERS = ["jungle_clearing", "desert_canyon", "snow_mountain_ridge", "abandoned_city_street"]


@pytest.fixture(scope="module")
def all_kits():
    return kits.all_kits()


# ---------------------------------------------------------------- schema + validation
def test_starter_kits_exist_and_validate(all_kits):
    assert set(STARTERS) <= set(all_kits)
    for k, kit in all_kits.items():
        assert kits.validate(kit) == [], k


def test_starter_kits_cover_the_brief(all_kits):
    j, d, s, c = (all_kits[k] for k in STARTERS)
    assert j["sky"]["time_of_day"] == "night" and {"ph:island_tree_01", "ph:fern_02", "ph:rock_moss_set_01"} <= {a for L in j["scatter"] for a in L["assets"]}
    assert d["sky"]["time_of_day"] == "day" and d["terrain"]["type"] == "canyon" and "ph:namaqualand_cliff_02" in {a for L in d["scatter"] for a in L["assets"]}
    assert s["terrain"]["type"] == "ridge" and s["terrain"]["material"]["texture"] == "ph:snow_02"
    assert any(p["builder"] == "proc:building" for p in c["pieces"]) and any(o.startswith("acg:") for p in c["pieces"] for o in (p.get("opts") or {}).get("facades", []))
    for kit in (j, d, s, c):  # every library asset is sourced with provenance (catalog entry with sha256 files)
        cat = kits._catalog()
        for cid, _ in kits.library_ids(kit):
            assert cat[cid]["licence"] == "CC0-1.0" and all(len(f["sha256"]) == 64 for f in cat[cid]["files"]), cid


def test_validation_catches_bad_kits(all_kits):
    kit = copy.deepcopy(all_kits["jungle_clearing"])
    kit["scatter"][0]["assets"].append("ph:not_in_library")
    kit["lighting"]["preset"] = "disco"
    kit["pieces"][0]["builder"] = "proc:spaceship"
    kit["marks"]["CENTER"]["at"] = [500, 0]
    kit["marks"]["FIRESIDE"]["target"] = "nothing"
    kit["ambience"].append({"id": "el:sfx_nope"})
    errs = "\n".join(kits.validate(kit))
    for frag in ("ph:not_in_library", "disco", "proc:spaceship", "CENTER is outside", "'nothing' is not a piece", "el:sfx_nope"):
        assert frag in errs, frag
    bad = copy.deepcopy(all_kits["desert_canyon"])
    bad["marks"]["oops"] = bad["marks"].pop("SHADE")
    assert any(e.startswith("schema") for e in kits.validate(bad))


# ---------------------------------------------------------------- determinism
@pytest.mark.parametrize("kid", STARTERS)
def test_layout_is_deterministic(all_kits, kid):
    kit = all_kits[kid]
    a, b = layout.layout(kit), layout.layout(copy.deepcopy(kit))
    assert a == b and a["hash"] == b["hash"] == layout.plan_hash(a)
    c = layout.layout(kit, seed=kit["seed"] + 1)
    assert c["hash"] != a["hash"]
    if kit["scatter"]:
        assert [i["pos"] for i in c["instances"]] != [i["pos"] for i in a["instances"]]
    assert a["marks"] == c["marks"] or kit["terrain"].get("amp")  # marks only move with the terrain noise


def test_layout_hash_pinned(all_kits):
    """Golden values: a change here means every set built from these kits changes (re-render, re-approve)."""
    got = {k: layout.layout(all_kits[k])["hash"][:12] for k in STARTERS}
    golden_path = os.path.join(os.path.dirname(__file__), "layout_hashes.json")
    with open(golden_path) as fh:
        assert got == json.load(fh)


def test_noise_is_platform_independent():
    """Integer hashing + sha256 seeds: pinned values hold on any CPython / Blender Python build."""
    assert layout.vnoise(0.0, 0.0, 0) == layout._ihash(0, 0, 0)
    assert layout.vnoise(3.7, -1.2, 5) == pytest.approx(0.21483615748144125, abs=1e-12)
    assert layout.fbm(12.3, -4.5, 7, 4) == pytest.approx(-0.13486053506959123, abs=1e-12)
    assert layout.seed_int("a", 1) == 0x773232ABE9343F0E


def test_scatter_respects_rules(all_kits):
    kit = all_kits["jungle_clearing"]
    plan = layout.layout(kit, with_grid=False)
    by = {}
    for i in plan["instances"]:
        by.setdefault(i["layer"], []).append(i)
    assert set(by) == {"canopy", "understorey", "rocks", "deadwood"}
    for i in plan["instances"]:
        L = next(l for l in kit["scatter"] if l["id"] == i["layer"])
        x, _, z = i["pos"]
        assert layout.in_region(kit, L["region"], x, z) and L["height"][0] <= i["height"] <= L["height"][1]
        for m in plan["marks"].values():   # nothing grows on a mark
            assert (x - m["local"][0]) ** 2 + (z - m["local"][2]) ** 2 >= L.get("avoid_marks", 2.5) ** 2 - 1e-9
    # density ~ requested (jittered grid, minus keep-outs)
    can = next(l for l in kit["scatter"] if l["id"] == "canopy")
    expect = layout.region_area(kit, can["region"]) * can["density"] / 100
    assert 0.6 * expect <= len(by["canopy"]) <= 1.1 * expect
    snow = all_kits["snow_mountain_ridge"]
    sp = layout.layout(snow, with_grid=False)
    firs = [i for i in sp["instances"] if i["layer"] == "firs"]
    assert firs and all(i["pos"][1] + 0.4 <= -45 + 1e-6 for i in firs)  # only below the tree line


def test_marks_stand_on_the_ground(all_kits):
    for k in STARTERS:
        kit = all_kits[k]
        for name, m in layout.marks(kit).items():
            x, y, z = m["local"]
            assert abs(y - layout.height(kit, x, z) - kit["marks"][name].get("y", 0.0)) < 1e-3
            assert layout.slope_deg(kit, x, z) < 25, (k, name)  # standable


def test_terrain_shapes():
    canyon = kits.load("desert_canyon")
    assert layout.height(canyon, 30, 0) - layout.height(canyon, 0, 0) > 30          # walls tower over the floor
    ridge = kits.load("snow_mountain_ridge")
    assert layout.height(ridge, 0, 0) - layout.height(ridge, 60, 0) > 35             # falls away from the crest
    street = kits.load("abandoned_city_street")
    assert abs(layout.height(street, 7.0, 3) - 0.16) < 1e-6 and layout.height(street, 0, 0) == pytest.approx(0.04)


def test_camera_check(all_kits):
    kit = all_kits["abandoned_city_street"]
    plan = layout.layout(kit, with_grid=False)
    assert layout.camera_check(kit, plan, [0.5, 1.8, -8]) == []
    assert any("inside set piece wreck_a" in p for p in layout.camera_check(kit, plan, [2.6, 1.0, 6.2]))
    assert any("zone band" in p for p in layout.camera_check(kit, plan, [-14, 2, 0]))          # street level inside a building lot
    assert any("inside set piece buildings_left" in p for p in layout.camera_check(kit, plan, [-14, 2, 0]))
    assert any("outside every camera-safe zone" in p for p in layout.camera_check(kits.load("jungle_clearing"), layout.layout(kits.load("jungle_clearing"), with_grid=False), [30, 2, 30]))
    assert any("below" in p for p in layout.camera_check(kit, plan, [0, -1, 0]))


# ---------------------------------------------------------------- librarian
def _bd(el, tod="night"):
    return {"id": "t", "scenes": [{"id": "S01", "title": "x", "location": el["id"], "time_of_day": tod, "weather": "clear", "line_ids": ["L01"],
                                   "picture": "x", "elements": [el["id"]]}], "elements": [el]}


@pytest.mark.parametrize("terms,name,kit", [
    (["rainforest", "clearing"], "Camp in the rainforest", "jungle_clearing"),
    (["gorge", "desert"], "A dry gorge", "desert_canyon"),
    (["summit ridge", "snow"], "The final ridge", "snow_mountain_ridge"),
    (["downtown street", "ruins"], "Ruined downtown", "abandoned_city_street"),
])
def test_librarian_maps_locations_to_kits(terms, name, kit):
    el = {"id": "loc", "kind": "location", "name": name, "must_do": ["frame the hero"], "search_terms": terms}
    man, _ = librarian.resolve(_bd(el))
    e = man["entries"][0]
    assert (e["decision"], e["catalog_id"], e["render_key"], e["status"]) == ("REUSE", f"kit:{kit}", f"set:{kit}", "ready")
    assert checks.check_manifest(man, _bd(el), librarian.load_catalog()).ok


def test_librarian_proposes_a_new_kit_from_the_library():
    el = {"id": "pine_forest_camp", "kind": "location", "name": "Pine forest camp", "must_do": ["hide the hero among firs"],
          "search_terms": ["pine forest", "fir", "boulder"]}
    man, _ = librarian.resolve(_bd(el, "dusk"))
    e = man["entries"][0]
    assert e["decision"] == "BUILD" and e["recipe"] == "kit:pine_forest_camp" and e["status"] == "to_build"
    p = e["kit_proposal"]
    assert p["errors"] == [], p["errors"]
    k = p["kit"]
    assert "ph:fir_tree_01" in {a for L in k["scatter"] for a in L["assets"]} and k["sky"]["time_of_day"] == "dusk"
    assert k["lighting"]["preset"] == "golden_hour" and kits.validate(k) == []
    assert checks.check_manifest(man, _bd(el, "dusk"), librarian.load_catalog()).ok


def test_sentinel_locations_still_resolve_internally(breakdown_sentinel):
    man, _ = librarian.resolve(breakdown_sentinel)
    by = {e["element"]: e for e in man["entries"]}
    assert by["open_sea"]["catalog_id"] == "int:ocean_fft" and by["north_sentinel"]["catalog_id"] == "int:island_sentinel"


@pytest.fixture
def breakdown_sentinel():
    with open(os.path.join(ROOT, "factory", "director", "fixtures", "sentinel", "breakdown.1.json")) as fh:
        return json.load(fh)


# ---------------------------------------------------------------- stage 4 on kit marks
def _plan(kit_id, mark, extra=None):
    s = {"id": "K01", "title": "t", "from": 0, "to": 75, "scene": "S01", "line_ids": ["L01"], "size": "MS", "set": kit_id,
         "camera": {"preset": "orbit_arc", "motivation": "character_attention", "rig": "orbit", "mark": mark, "az": [-30, -20], "dist": [4, 3.5],
                    "height": [0.2, 0.2], "fov": [35, 32], "ease": "move"},
         "yacht": {"state": "absent"}, "island": None, "hero": {"mark": mark, "stance": "stand", "poses": [{"pose": "look_up", "from": 10, "to": 60}]}}
    s.update(extra or {})
    return {"id": "t", "audio_offset_frames": 3, "world": {"moonDir": [0, 1, 0], "seaState": 0, "dawn": 0, "island": None},
            "action_line": "x", "shots": [s], "overrides": []}


def test_compile_stages_hero_on_kit_marks():
    kit = kits.load("desert_canyon")
    plan = _plan("desert_canyon", "SHADE")
    story = {"id": "t", "title": "t", "narration": [{"id": "L01", "t0": 0.1, "t1": 2.0, "text": "Shade is water."}]}
    ep = comp.compile_episode(plan, story, {"entries": [{"render_key": "characters/hero", "catalog_id": "int:hero", "element": "hero"}]}, ROOT)
    sh = ep["shots"][0]
    mk = layout.marks(kit)["SHADE"]
    a = sh["actors"][0]
    assert a["space"] == "set" and a["local"] == mk["local"] and a["rotY"] == round(mk["rotY"], 5)
    assert sh["set"]["kit"] == "desert_canyon" and sh["set"]["seed"] == kit["seed"] and sh["lighting"]["preset"] == "midday"
    assert sh["camera"]["space"] == "world" and "yacht" not in sh and sh["island"] is None
    look = sh["camera"]["keys"][0]["look"]
    assert abs(look[0] - mk["local"][0]) < 1e-3 and abs(look[2] - mk["local"][2]) < 1e-3   # the camera orbits the kit mark
    assert schemas.validate("episode", ep) == []
    assert checks.check_episode(ep).ok


def test_shotplan_checks_use_kit_marks(story_bd_man):
    story, bd, man = story_bd_man
    r = checks.check_shotplan(_plan("jungle_clearing", "FIRESIDE"), story, bd, man)
    names = {i["rule"] for i in r.blocking}
    assert not any(n.startswith(("V-mark", "V-orbit", "V-set")) for n in names), names
    r = checks.check_shotplan(_plan("jungle_clearing", "HELM"), story, bd, man)        # a yacht mark is not on this set
    names = {i["rule"] for i in r.blocking}
    assert {"V-mark.K01", "V-orbit.K01"} <= names
    r = checks.check_shotplan(_plan("jungle_clearing", "FIRESIDE", {"yacht": {"state": "afloat_lit"}}), story, bd, man)
    assert "V-set-world.K01" in {i["rule"] for i in r.blocking}
    r = checks.check_shotplan(_plan("atlantis", "CENTER"), story, bd, man)
    assert "V-set.K01" in {i["rule"] for i in r.blocking}
    bad_cam = _plan("abandoned_city_street", "LAMP_POST")
    bad_cam["shots"][0]["camera"].update(az=[-30, -15], dist=[4.4, 3.8])    # swings the camera into the red wreck
    r = checks.check_shotplan(bad_cam, story, bd, man)
    assert any(i["rule"] == "K-camera-safe.K01" and "wreck_a" in i["msg"] for i in r.issues)


@pytest.fixture
def story_bd_man():
    story = {"id": "t", "format": "short", "title": "t", "duration_s": 2.5, "narration": [{"id": "L01", "t0": 0.1, "t1": 2.0, "text": "Hold on."}]}
    el = {"id": "loc", "kind": "location", "name": "Jungle clearing", "must_do": ["x"], "search_terms": ["jungle clearing"]}
    bd = _bd(el)
    bd["scenes"][0]["line_ids"] = ["L01"]
    man, _ = librarian.resolve(bd)
    return story, bd, man


def test_proof_episodes_compile_to_the_render_contract():
    for k in STARTERS:
        p = os.path.join(ROOT, "episodes", "world_kits", k, "episode.json")
        with open(p) as fh:
            ep = json.load(fh)
        assert checks.check_episode(ep).ok, k
        assert len(ep["shots"]) == 3 and all(s["set"]["kit"] == k and s["actors"][0]["asset"] == "hero" and s["actors"][0]["perf"]["poses"] for s in ep["shots"])


def test_renderer_vocabulary_matches_set_assembly():
    assert {"building", "car_wreck", "campfire", "cairn"} <= kits.proc_builders()
