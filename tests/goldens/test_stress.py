"""Scenario stress suite: generated coverage, camera planning, lesson regression cases, known-failure gate logic."""
import json
import os
import shutil
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "factory", "direction"))
import shot_checks as SC  # noqa: E402
from factory.goldens import manifest as M  # noqa: E402
from factory.goldens.stress import generator as SG, run as SR  # noqa: E402


def test_committed_spec_is_current_and_deterministic():
    assert SG.is_current(), "run: python -m factory.goldens.stress.generator"
    assert json.dumps(SG.build(), sort_keys=True) == json.dumps(SG.build(), sort_keys=True)


def test_coverage_axes():
    meta = SG.build()["stress"]["scenarios"]
    assert len(meta) >= 20
    by_kit = {k: [m for m in meta if m["kit"] == k] for k in SG.KITS}
    assert all(len(v) >= 4 for v in by_kit.values()), {k: len(v) for k, v in by_kit.items()}
    assert {m["emotion"] for m in meta} >= set(SG.EMOTIONS)
    assert {m["size"] for m in meta} == {"wide", "medium", "close"}
    stances = {m["stance"] for m in meta}
    assert {"stand", "brace", "helm", "sit_deck", "sit_log", "sit_rock", "sit_bench", "kneel", "crouch", "walk"} <= stances
    hands = {m["hands"] for m in meta}
    assert {"relaxed", "wheel", "radio", "phone", "beacon", "rail", "point", "wave", "shush", "reach", "rope"} <= hands
    assert all(m["vocab_missing"] for m in meta if m["stance"] in SG.VOCAB_FALLBACK)


def test_every_scenario_is_framed_and_collision_free():
    spec = json.load(open(SG.SPEC_PATH))
    res = SC.check_episode(spec)
    assert res["ok"], res["failing"]
    assert {s["id"] for s in spec["shots"]} == {m["id"] for m in spec["stress"]["scenarios"]}


def test_stress_goldens_registered():
    g = M.load()["goldens"]
    st = [k for k in g if k.startswith("stress_")]
    assert len(st) == len(SG.build()["stress"]["scenarios"])
    x = g[st[0]]
    assert x["res"] == "360x640" and x["lib"] == "curated" and M.STRESS_SPEC in x["globs"]
    assert set(M.affected(["cloud/blender/acting.py"])) >= set(st)


def test_case_selectors_cover_every_kit():
    e = SG.expand_case({"lesson": "LX", "stance": "sit*", "tag": "sit"})
    assert len(e) == len(SG.KITS)
    assert {x["id"] for x in e if x["reused"]} >= {"y_sit_deck", "j_sit_log", "d_sit_rock_sneeze", "s_sit_bench"}
    new = [x for x in e if not x["reused"]]
    assert new and new[0]["row"][1] == "abandoned_city_street" and new[0]["row"][3] == "sit_deck"
    e2 = SG.expand_case({"lesson": "LY", "hands": ["radio*", "phone"], "size": "close"})
    assert any(x["id"] == "y_radio_shout" for x in e2)


def test_lesson_add_attaches_regression_cases(tmp_path):
    import factory.lessons as L
    from factory.lessons import cases
    led = tmp_path / "lessons.yaml"
    shutil.copyfile(L.LEDGER, led)
    lid = L.add_lesson("Fingers splay when he waves", "no hand shapes", "hands curl", "direct", path=str(led))
    ids = cases.attach(lid, None, "Fingers splay when he waves; hands curl", path=str(led))
    assert len(ids) == len(SG.KITS) and L.get(lid, str(led))["regression_cases"] == ids
    assert json.load(open(tmp_path / "stress_cases.json"))["cases"][-1]["tag"] == "hands"
    assert cases.derive("He leans back when sitting")[0] == "sit" and cases.derive("close-ups crop the face")[0] in ("face", "frame")
    assert cases.parse_case("stance=sit*,hands=radio|phone") == {"stance": "sit*", "hands": ["radio", "phone"]}


def test_repo_lessons_have_regression_cases():
    import factory.lessons as L
    d = {x["id"]: x for x in L.load_lessons()}
    for lid in ("L009", "L010", "L011", "L012", "L017", "L018", "L019", "L020"):
        assert len(d[lid].get("regression_cases") or []) == len(SG.KITS), lid
    ids = {m["id"] for m in json.load(open(SG.SPEC_PATH))["stress"]["scenarios"]}
    assert all(c in ids for lid in ("L009", "L020") for c in d[lid]["regression_cases"])


def test_run_known_failures_logic(tmp_path, monkeypatch):
    spec = json.load(open(SG.SPEC_PATH))
    ids = [m["id"] for m in spec["stress"]["scenarios"]][:3]

    def fake_pose(spec_path, only, out_json, log):
        return {i: [{"rule": "POSE-FINGERS.R", "status": "fail" if i != ids[2] else "pass", "measured": 4.7}] for i in only}
    known = tmp_path / "known.json"
    known.write_text(json.dumps({"failures": {ids[0]: {"POSE-FINGERS.R": "L010"}, ids[2]: {"POSE-FINGERS.R": "L010"}}}))
    monkeypatch.setattr(SR, "KNOWN", str(known))
    monkeypatch.setattr(SR, "load_known", lambda path=str(known): json.load(open(path)))
    monkeypatch.setenv("FACTORY_GOLDENS_STORE", str(tmp_path / "store"))
    rep = SR.run(ids, render=False, pose=True, pose_fn=fake_pose, log=lambda m: None)
    assert (ids[1], "POSE-FINGERS.R") in rep["regressions"]            # not known -> FAIL
    assert (ids[0], "POSE-FINGERS.R") in rep["known_failures_hit"]
    assert (ids[2], "POSE-FINGERS.R") in rep["fixed"] and not rep["ok"]
    doc = SR.update_known(rep, "test", path=str(known))
    assert doc["failures"][ids[1]] == {"POSE-FINGERS.R": "L017"} and ids[2] not in doc["failures"]
    assert "STRESS FAIL" in SR.summary_text(rep)


def test_vision_rubric_with_fake_client(tmp_path):
    from factory.goldens import metrics, vision
    import numpy as np
    png = tmp_path / "f.png"
    metrics.save(np.full((32, 18, 3), 0.5), str(png))

    class Fake:
        messages = None

        def __init__(self):
            self.messages = self

        def create(self, **kw):
            items = [{"id": i, "pass": i != "HANDS-1", "note": "x"} for i in vision.RUBRIC]

            class R:
                content = [type("B", (), {"type": "text", "text": json.dumps({"items": items})})()]
            return R()
    r = vision.rubric(str(png), {"kit": "k", "stance": "s", "hands": "h", "size": "close", "emotion": "fear"}, client=Fake())
    assert r["HANDS-1"]["status"] == "fail" and r["FACE-2"]["status"] == "pass"
