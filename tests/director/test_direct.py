import json
import os

import pytest

from director_helpers import ROOT, deep, rules
from factory.director import checks, compile as comp
from factory.director.staging import vocabulary


def _close(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        out = [f"{path}/{k}: missing" for k in set(a) ^ set(b)]
        for k in set(a) & set(b):
            out += _close(a[k], b[k], f"{path}/{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: len {len(a)} != {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in _close(x, y, f"{path}[{i}]")]
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return [] if abs(a - b) <= 1e-3 else [f"{path}: {a} != {b}"]
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def test_vocabulary_is_read_from_the_renderer():
    v = vocabulary()
    assert {"helm", "brace", "sit_deck"} <= set(v["stances"]) and "radio_shout" in v["poses"]
    assert {"sneeze", "shake_head", "lurch"} <= set(v["verbs"]) and {"radio", "beacon", "bag"} <= set(v["props"])


def test_shotplan_passes(plan, story, breakdown, manifest, words):
    rep = checks.check_shotplan(plan, story, breakdown, manifest, words)
    assert rep.ok, rep.blocking
    for r in ("C1", "C2", "C3", "C8", "C9", "P-1", "P-4", "P-6", "S8", "INTEGRITY.contiguous", "M-props-resolved"):
        assert r in rep.passed, r


def test_compiled_episode_reproduces_hand_built_sentinel_v2(plan, story, manifest):
    """The director's stage-4 output for the Sentinel fixture equals episodes/sentinel/episode_v2.json shot for shot
    (camera keys, yacht, island, actors/perf, props, fires, env). The only difference: A01 states the renderer's
    default handheld/drift explicitly (build_v2 dropped them when it replaced A01's camera)."""
    ep = comp.compile_episode(plan, story, manifest, os.path.join(ROOT, "episodes", "sentinel"))
    with open(os.path.join(ROOT, "episodes", "sentinel", "episode_v2.json")) as fh:
        v2 = json.load(fh)
    assert ep["$schema"] == v2["$schema"] and ep["durationFrames"] == v2["durationFrames"] and ep["world"] == v2["world"]
    assert ep["audio"] == v2["audio"]
    v2["shots"][0]["camera"].update(handheld=0.2, drift=0.25)
    diffs = [d for m, o in zip(ep["shots"], v2["shots"]) for d in _close(m, o, m["id"])]
    assert len(ep["shots"]) == 33 and diffs == []
    assert checks.check_episode(ep).ok


@pytest.mark.parametrize("mutate,rule", [
    (lambda p: p["shots"][3]["hero"]["poses"].append({"pose": "moonwalk", "from": 170, "to": 180}), "V-pose.A04"),
    (lambda p: p["shots"][3]["hero"]["verbs"].append({"verb": "dance", "at": 170}), "V-verb.A04"),
    (lambda p: p["shots"][12]["props"].append({"prop": "flare_gun", "attach": "handR"}), "V-prop.C13"),
    (lambda p: p["shots"][1].update(**{"from": 76}), "INTEGRITY.contiguous"),
    (lambda p: p["shots"][2]["camera"].update(mark="MAST"), "V-orbit.A03"),
    (lambda p: p["shots"][6]["camera"]["cam"][0].update(frame="yacht"), "V-path.A07"),
    (lambda p: p["shots"][1]["camera"].pop("motivation"), "SCHEMA"),
    (lambda p: p["shots"][14].update(line_ids=["L02"]), "D-line-shown.L02"),
    (lambda p: p["shots"][2]["camera"].update(preset="push_in"), "P-6"),
])
def test_shotplan_failures(plan, story, breakdown, manifest, mutate, rule):
    p = deep(plan)
    mutate(p)
    assert rule in rules(checks.check_shotplan(p, story, breakdown, manifest))


def test_cut_on_word_check_uses_word_timings(plan, story, breakdown, manifest, words):
    p = deep(plan)
    p["overrides"] = [o for o in p["overrides"] if o["rule"] != "P-3"]
    assert "P-3" in rules(checks.check_shotplan(p, story, breakdown, manifest, words))
    assert "P-3" not in rules(checks.check_shotplan(p, story, breakdown, manifest, None))   # skipped without words[]


def test_episode_contract_catches_static_camera(plan, story, manifest):
    ep = comp.compile_episode(plan, story, manifest, "/tmp")
    s = ep["shots"][5]
    k0 = s["camera"]["keys"][0]
    s["camera"]["keys"] = [dict(k0, f=s["from"]), dict(k0, f=s["to"])]
    s["camera"]["drift"] = 0
    assert "P-7.A06" in rules(checks.check_episode(ep))
