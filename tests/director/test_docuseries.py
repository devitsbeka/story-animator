"""Docuseries end to end in factory/director: the synthetic 6-minute mini-doc fixtures (scale model of 20 min),
structure checks, 150-400 shot density, dual-frame staging (cameras.main + cameras.vertical) and the renderer's
--camera selection."""
import ast
import copy
import functools
import json
import math
import os
import subprocess
import sys

import pytest

from director_helpers import ROOT, rules
from factory.director import checks, compile as comp, docuseries as doc, librarian
from factory.director.llm import FixtureClient
from factory.director.runner import Runner

MINI = os.path.join(ROOT, "factory", "director", "fixtures", "minidoc")
sys.path.insert(0, MINI)
import build as minidoc  # noqa: E402

IDEA = "A solo sailor drifts onto North Sentinel's reef at night: a docuseries episode"


def _ph():
    return librarian.PolyHavenSearch(os.path.join(MINI, "polyhaven_search.json"))


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    out = tmp_path_factory.mktemp("minidoc")
    run = Runner(str(out), FixtureClient(MINI), IDEA, "docuseries", ph=_ph(), log=lambda *a: None)
    res = run.run()
    return run, res, out


@pytest.fixture
def mini():
    return copy.deepcopy(minidoc.build_all(360.0))


def _man(bd):
    return librarian.resolve(bd, ph=_ph())[0]


# ------------------------------------------------------------------ fixtures + full chain
def test_committed_fixtures_are_the_generator_output():
    story, bd, plan = minidoc.build_all(360.0)
    for name, doc_ in (("develop.1.json", story), ("breakdown.1.json", bd), ("direct.1.json", plan)):
        with open(os.path.join(MINI, name)) as fh:
            assert json.load(fh) == json.loads(json.dumps(doc_)), f"{name} is stale: run factory/director/fixtures/minidoc/build.py"


def test_minidoc_chain_offline(chain):
    run, res, out = chain
    assert all(r.ok for r in run.reports.values()), {k: r.blocking for k, r in run.reports.items()}
    story, ep = res["story"], res["episode"]
    assert story["format"] == "docuseries" and len(story["chapters"]) == 5 and story["duration_s"] == 360.0
    assert (ep["width"], ep["height"]) == (1920, 1080) and ep["format"] == "docuseries" and ep["vertical"] == {"width": 1080, "height": 1920}
    lo, hi = doc.shot_count_range(360.0)
    assert lo <= len(ep["shots"]) <= hi
    assert [s["id"] for s in ep["shorts"]] == ["SC1", "SC2", "SC3", "SC4", "SC5"]
    for sh in ep["shorts"]:
        assert sh["shots"] and 45 * 30 <= sh["to"] - sh["from"] <= 90 * 30
        for sid in sh["shots"]:
            s = next(x for x in ep["shots"] if x["id"] == sid)
            assert s["short_candidate"] == sh["id"] and s["cameras"]["main"] == s["camera"]
            assert [k["cam"] for k in s["cameras"]["vertical"]["keys"]] == [k["cam"] for k in s["camera"]["keys"]]
    passed = set(run.reports["develop"].passed) | set(run.reports["direct"].passed)
    for r in ("DOC-title-beat", "DOC-arc", "DOC-act-breaks", "DOC-short-cut.CH1", "DOC-shot-count", "DOC-short-staged.SC3",
              "DOC-centre-band.D013", "DOC-vertical.D013", "E-size", "N-1", "R-2"):
        assert r in passed, r
    assert "INTEGRITY.duration" in run.reports["develop"].to_dict()["overridden"]      # 6 min < 15 min: logged override
    with open(out / "episode.json") as fh:
        assert json.load(fh)["shorts"][0]["hook_line"].startswith("Would you survive")


def test_twenty_minute_scale():
    """Same generator at 1200 s: 150-400 shots, re-hooks <= 180 s apart, every stage passes."""
    story, bd, plan = minidoc.build_all(1200.0)
    assert checks.check_story(story).ok
    assert checks.check_breakdown(bd, story).ok
    man = _man(bd)
    rep = checks.check_shotplan(plan, story, bd, man)
    assert rep.ok, rep.blocking
    assert 150 <= len(plan["shots"]) <= 400 and story["chapters"][0]["short_candidate"]["out"] - story["chapters"][0]["short_candidate"]["in"] <= 90
    rh = [ln["t0"] for ln in story["narration"] if ln.get("rehook")]
    assert max(b - a for a, b in zip(rh, rh[1:])) <= 180
    ep = comp.compile_episode(plan, story, man, "episodes/x")
    assert checks.check_episode(ep).ok


def test_cli_docuseries_offline(tmp_path):
    out = tmp_path / "cli"
    r = subprocess.run([sys.executable, "-m", "factory.director", "run", "--idea", IDEA, "--format", "docuseries", "--out", str(out), "--offline"],
                       cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK: develop pass, breakdown pass, library pass, direct pass" in r.stdout
    v = subprocess.run([sys.executable, "-m", "factory.director", "validate", "--dir", str(out)], cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert v.returncode == 0 and "episode    PASS" in v.stdout, v.stdout


# ------------------------------------------------------------------ story / breakdown / shotplan structure
def _first(story, name):
    return next(b for b in story["beats"] if b["name"] == name)


@pytest.mark.parametrize("mutate,rule", [
    (lambda s: s["beats"].remove(_first(s, "TITLE")), "DOC-title-beat"),
    (lambda s: s["beats"].remove(_first(s, "CLIMAX")), "DOC-arc"),
    (lambda s: _first(s, "CLIMAX").update(t0=10.0), "DOC-arc"),
    (lambda s: [ln.pop("rehook", None) for ln in s["narration"] if ln.get("chapter") == "CH3"], "DOC-act-breaks"),
    (lambda s: s["chapters"][0]["short_candidate"].update(**{"in": s["chapters"][0]["short_candidate"]["in"] + 2.0}), "DOC-short-cut.CH1"),
    (lambda s: s["chapters"][1]["short_candidate"].update(hook_line="word " * 20), "DOC-short-cut.CH2"),
])
def test_story_structure_failures(mini, mutate, rule):
    story = mini[0]
    mutate(story)
    assert rule in rules(checks.check_story(story))


def test_breakdown_scenes_stay_inside_chapters(mini):
    story, bd, _ = mini
    sc = next(s for s in bd["scenes"] if s.get("chapter") == "CH2")
    sc["chapter"] = "CH3"
    assert "DOC-scene-chapter" in rules(checks.check_breakdown(bd, story))
    sc["chapter"] = "CH2"
    other = next(s for s in bd["scenes"] if s.get("chapter") == "CH4")
    sc["line_ids"].append(other["line_ids"][0])          # a scene straddling two chapters
    assert "DOC-scene-chapter" in rules(checks.check_breakdown(bd, story))


def test_shotplan_short_staging_failures(mini):
    story, bd, plan = mini
    man = _man(bd)
    assert checks.check_shotplan(plan, story, bd, man).ok
    p = copy.deepcopy(plan)
    tagged = [s for s in p["shots"] if s.get("short_candidate") == "SC1"]
    tagged[3].pop("short_candidate")
    assert "DOC-short-staged.SC1" in rules(checks.check_shotplan(p, story, bd, man))
    p = copy.deepcopy(plan)
    p["shots"][0]["short_candidate"] = "SC4"                # tagged far outside SC4's in/out
    assert "DOC-short-staged.SC4" in rules(checks.check_shotplan(p, story, bd, man))
    p = copy.deepcopy(plan)
    p["shots"][0]["short_candidate"] = "SC9"
    assert "DOC-short-ref" in rules(checks.check_shotplan(p, story, bd, man))
    p = copy.deepcopy(plan)
    tagged = next(s for s in p["shots"] if s.get("short_candidate") == "SC2")
    tagged["hero"] = None
    assert "DOC-short-subject.SC2" in rules(checks.check_shotplan(p, story, bd, man))


def test_shot_density_rule():
    assert doc.shot_count_range(1200) == (150, 400)
    assert doc.shot_count_range(360) == (45, 120)
    story, bd, plan = minidoc.build_all(360.0)
    p = copy.deepcopy(plan)
    # merge pairs of shots: half the cut, still contiguous and valid, but too few shots for 6 minutes
    merged = []
    for a, b in zip(p["shots"][0::2], p["shots"][1::2]):
        a = dict(a, to=b["to"], line_ids=list(dict.fromkeys(a["line_ids"] + b["line_ids"])))
        merged.append(a)
    merged[-1]["to"] = p["shots"][-1]["to"]
    p["shots"] = [s for s in merged if not s.get("suspense_hold")][:40]
    p["shots"][-1]["to"] = plan["shots"][-1]["to"]
    for a, b in zip(p["shots"], p["shots"][1:]):
        a["to"] = b["from"]
    assert "DOC-shot-count" in {i["rule"] for i in checks.check_shotplan(p, story, bd, _man(bd)).issues}


# ------------------------------------------------------------------ dual-frame staging (vertical camera)
@functools.lru_cache(maxsize=1)
def _compiled_once():
    story, bd, plan = minidoc.build_all(360.0)
    return comp.compile_episode(plan, story, _man(bd), "episodes/x")


def _compiled():
    return copy.deepcopy(_compiled_once())


def test_vertical_camera_reaims_world_glide():
    ep = _compiled()
    s = next(x for x in ep["shots"] if x.get("short_candidate") and x["title"].startswith("lateral_glide"))
    m, v = s["cameras"]["main"], s["cameras"]["vertical"]
    assert [k["cam"] for k in m["keys"]] == [k["cam"] for k in v["keys"]]                  # same position
    assert all(abs(b["fov"] - a["fov"] * doc.DEFAULT_TIGHTEN) < 1e-3 for a, b in zip(m["keys"], v["keys"]))   # tightened
    assert math.dist(m["keys"][0]["look"], v["keys"][0]["look"]) > 5.0                      # re-aimed (16:9 looks at the deck ahead)
    r = doc.dual_frame_report(s)
    assert 0.05 < r["main"] <= doc.CENTRE_BAND and r["vertical"] <= 0.01 and not r["behind"]
    # rendered check (cloud/blender, frame 1528, 270x480 vs 480x270): hero at x ~0.52 in 9:16, ~0.44 in 16:9
    f = (s["from"] + s["to"]) // 2
    vx, _ = doc.project_subject(s, m, v, f, 9 / 16)
    mx, _ = doc.project_subject(s, m, m, f, 16 / 9)
    assert abs(vx - 0.5) < 0.01 and 0.3 < mx < 0.45


def test_vertical_camera_keeps_hero_aim_on_wide_orbits_and_adds_headroom_on_close_ones():
    ep = _compiled()
    wide = next(x for x in ep["shots"] if x.get("short_candidate") and x["title"] == "crane_down EWS")
    assert [k["look"] for k in wide["cameras"]["vertical"]["keys"]] == [k["look"] for k in wide["camera"]["keys"]]
    close = next(x for x in ep["shots"] if x.get("short_candidate") and x["title"] == "slow_push CU")
    v = close["cameras"]["vertical"]
    f = close["from"] + 6
    from factory.direction import camgeo
    c, look, fov, roll = camgeo.camera_world({**close, "camera": v}, f, jitter=False)
    ex, ey, _ = camgeo.project(c, look, roll, fov, 9 / 16, doc.eye_world(close, f))
    assert abs(ex - 0.5) < 0.02 and abs(ey - doc.EYE_Y) < 0.03                              # eyes centred, at 38% height


def test_episode_dual_frame_failures():
    ep = _compiled()
    assert checks.check_episode(ep).ok
    bad = copy.deepcopy(ep)
    s = next(x for x in bad["shots"] if x.get("short_candidate"))
    s["cameras"]["vertical"]["keys"][0]["cam"] = [0, 99, 0]
    assert f"DOC-vertical.{s['id']}" in rules(checks.check_episode(bad))
    bad = copy.deepcopy(ep)
    s = next(x for x in bad["shots"] if x.get("short_candidate") and x["title"].startswith("lateral_glide"))
    s["cameras"]["vertical"] = copy.deepcopy(s["camera"])          # a crop-style vertical: same aim as 16:9
    s["cameras"]["vertical"]["keys"] = [dict(k, fov=k["fov"] * 0.85) for k in s["camera"]["keys"]]
    rep = checks.check_episode(bad)
    assert f"DOC-centre-band.{s['id']}" in rules(rep)
    assert checks.check_episode(bad, [{"rule": f"DOC-centre-band.{s['id']}", "reason": "deliberate off-centre insert"}]).ok
    bad = copy.deepcopy(ep)
    bad["width"], bad["height"] = 1080, 1920
    assert "E-size" in rules(checks.check_episode(bad))


def test_short_episodes_unchanged(plan, story, manifest):
    ep = comp.compile_episode(plan, story, manifest, "episodes/sentinel")
    assert (ep["width"], ep["height"]) == (1080, 1920) and "shorts" not in ep and "format" not in ep
    assert checks.check_episode(ep).ok


# ------------------------------------------------------------------ renderer --camera (pure part, no bpy)
def _select_camera():
    src = open(os.path.join(ROOT, "cloud", "blender", "render_episode.py")).read()
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "select_camera")
    ns = {"os": os, "log": lambda *a: None}
    exec(compile(ast.Module([fn], []), "render_episode.select_camera", "exec"), ns)
    return ns["select_camera"]


def test_render_select_camera():
    sel = _select_camera()
    ep = _compiled()
    work = [(s, list(range(s["from"], s["to"]))) for s in ep["shots"][:20]]

    class A:
        camera, out = "main", "/x/episodes/minidoc/plates"
    a = A()
    main = sel(dict(ep), work, a)
    assert len(main) == 20 and all(s["camera"] == (s.get("cameras") or {}).get("main", s["camera"]) for s, _ in main)
    a.camera = "vertical"
    spec = dict(ep)
    vert = sel(spec, work, a)
    assert (spec["width"], spec["height"]) == (1080, 1920) and a.out == "/x/episodes/minidoc/plates_vertical"
    assert vert and all(s["camera"] is s["cameras"]["vertical"] for s, _ in vert)
    assert len(vert) == sum(1 for s, _ in work if s.get("cameras"))
