from conftest import deep, rules
from factory.director import checks, librarian


def _by(man):
    return {e["element"]: e for e in man["entries"]}


def test_breakdown_fixture_passes(story, breakdown):
    rep = checks.check_breakdown(breakdown, story)
    assert rep.ok, rep.blocking


def test_every_line_needs_a_picture(story, breakdown):
    bd = deep(breakdown)
    bd["scenes"][1]["line_ids"] = []
    bd["scenes"] = [s for s in bd["scenes"] if s["line_ids"]] or bd["scenes"]
    rep = checks.check_breakdown(bd, story)
    assert "B-every-line-has-picture" in rules(rep)


def test_unknown_element_and_late_climax_prop(story, breakdown):
    bd = deep(breakdown)
    bd["scenes"][0]["elements"].append("ghost")
    for e in bd["elements"]:
        if e["id"] == "helicopter":
            e["solves_climax"] = True          # first seen in S10 at 0.62 D
    r = rules(checks.check_breakdown(bd, story))
    assert {"INTEGRITY.element_refs", "S6"} <= r


def test_sentinel_library_decisions(manifest, breakdown):
    by = _by(manifest)
    assert by["yacht"]["decision"] == "REUSE" and by["yacht"]["catalog_id"] == "int:yacht_14m" and by["yacht"]["render_key"] == "props/yacht"
    assert by["vhf_radio"]["render_key"] == "prop:radio"
    assert by["hero"]["catalog_id"] == "int:hero"                       # uncatalogued render asset (gap reported)
    assert by["trash_bag"] == {**by["trash_bag"], "decision": "BUILD", "recipe": "cloud/blender/props.py:trash_bag", "status": "ready"}
    assert by["island_trees"]["catalog_id"].startswith("ph:island_tree_") and all(len(f["sha256"]) == 64 for f in by["island_trees"]["files"])
    assert by["hdri_night"]["catalog_id"] == "ph:moonlit_golf"
    # Poly Haven 'coral' only returns a shell tagged coral: rejected, so the reef is a procedural BUILD
    assert by["coral_reef"]["decision"] == "BUILD" and by["coral_reef"]["recipe"] == "proc:coral_reef"
    assert by["helicopter"]["status"] == "to_build" and by["primrose_ship"]["status"] == "to_build"
    assert by["germ_cloud"]["recipe"] == "remotion:germ_cloud"
    assert {e["id"] for e in breakdown["elements"]} == set(by)


def test_source_path_from_polyhaven_search(tmp_path):
    cache = tmp_path / "ph.json"
    cache.write_text('{"model:barrel": [["wine_barrel_01", "Wine Barrel 01", 900], ["x", "Other", 1]]}')
    bd = {"id": "t", "scenes": [], "elements": [
        {"id": "barrel", "kind": "prop", "name": "Water barrel", "must_do": ["roll"], "search_terms": ["barrel"]},
        {"id": "anchor", "kind": "prop", "name": "Anchor", "must_do": ["drop"], "search_terms": ["anchor"]}]}
    ph = librarian.PolyHavenSearch(str(cache), mode="offline")
    man, _ = librarian.resolve(bd, ph=ph)
    by = _by(man)
    assert by["barrel"]["decision"] == "SOURCE" and by["barrel"]["licence"] == "CC0-1.0" and by["barrel"]["status"] == "to_fetch"
    assert by["barrel"]["url"] == "https://polyhaven.com/a/wine_barrel_01"
    assert by["anchor"]["decision"] == "BUILD"
    assert ph.misses == ["model:anchor"]            # offline cache miss is reported, never a network call
    assert any("Wine Barrel 01" in a for a in man["attributions"])


def test_manifest_gate(manifest, breakdown):
    cat = librarian.load_catalog()
    assert checks.check_manifest(manifest, breakdown, cat).ok
    bad = deep(manifest)
    bad["entries"][0]["licence"] = "CC-BY-NC-4.0"
    bad["entries"] = bad["entries"][:-1]
    r = rules(checks.check_manifest(bad, breakdown, cat))
    assert "M-nothing-missing" in r and any(x.startswith("M-licence.") for x in r)
