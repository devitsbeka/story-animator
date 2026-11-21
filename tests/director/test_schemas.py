import json
import os

from conftest import ROOT, load
from factory.director import schemas
from factory.director.recipes import all_checklists, stage_recipe_text


def test_schemas_are_valid_draft_2020_12():
    for n in schemas.NAMES:
        schemas.load(n)          # check_schema raises on an invalid schema
    schemas.render_contract()


def test_fixtures_validate_against_their_schemas():
    assert schemas.validate("story", load("develop.2.json")) == []
    assert schemas.validate("breakdown", load("breakdown.1.json")) == []
    assert schemas.validate("shotplan", load("direct.1.json")) == []


def test_hand_built_sentinel_v2_satisfies_the_render_contract():
    # the existing renderer input (built by build_v2.py) is the compatibility target
    with open(os.path.join(ROOT, "episodes", "sentinel", "episode_v2.json")) as fh:
        assert schemas.validate("episode", json.load(fh)) == []


def test_schema_errors_are_reported():
    s = load("develop.2.json")
    s["hook"]["format"] = "TEASER"
    del s["spine"]
    errs = schemas.validate("story", s)
    assert any("hook/format" in e for e in errs) and any("spine" in e for e in errs)


def test_api_schema_strips_constraints_but_keeps_structure():
    for n in ("story", "breakdown", "shotplan"):
        txt = json.dumps(schemas.api_schema(n))
        for kw in ('"minimum"', '"pattern"', '"minItems"', '"prefixItems"', '"$schema"'):
            assert kw not in txt, (n, kw)
        assert '"additionalProperties": false' in txt and '"required"' in txt
    # property *names* that look like keywords survive (story.hook.text_overlay.start etc.)
    assert "format" in schemas.api_schema("story")["properties"]


def test_recipes_are_embedded_verbatim():
    dev = stage_recipe_text("develop")
    assert "**Checklist: Hook**" in dev and "**CHECKLIST §2**" in dev and "Story spine" in dev
    direct = stage_recipe_text("direct")
    assert "**Checklist: Pacing**" in direct and "**CHECKLIST §3**" in direct
    assert all_checklists().count("- [ ]") > 60
