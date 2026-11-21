import json
import os
import types

import numpy as np
from PIL import Image

from conftest import ROOT, SENTINEL
from factory.qc import report, vision
from factory.qc.common import rule

RECIPES = os.path.join(ROOT, "factory", "recipes")


def test_prompt_quotes_recipes():
    prompt, items = vision.build_prompt(RECIPES, ["f0 0.0s", "A01 2.0s"])
    ids = [i["id"] for i in items]
    assert "H-3" in ids and "H1" in ids
    h3 = next(i for i in items if i["id"] == "H-3")
    assert "first frame" in h3["rule"].lower()  # pulled from ENGAGEMENT_RECIPE.md
    h1 = next(i for i in items if i["id"] == "H1")
    assert "centered" in h1["rule"].lower() or "center" in h1["rule"].lower()
    assert "A01 2.0s" in prompt and "JSON" in prompt


def _plates(tmp_path):
    d = tmp_path / "plates" / "S1"
    d.mkdir(parents=True)
    for f in range(3):
        Image.fromarray(np.full((48, 27, 3), 60 + f * 10, np.uint8)).save(d / f"{f:04d}.png")
    return str(tmp_path / "plates")


def test_review_skips_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rules, info = vision.review(str(tmp_path / "v"), RECIPES, plates_dir=_plates(tmp_path))
    assert info["status"] == "skipped" and os.path.isfile(info["contact_sheet"]) and os.path.isfile(info["prompt"])
    assert rules and all(r["status"] == "skip" for r in rules)


class FakeClient:
    """Stands in for anthropic.Anthropic(); records the request."""

    def __init__(self, payload):
        self.payload, self.calls = payload, []
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        block = types.SimpleNamespace(type="text", text=json.dumps(self.payload))
        return types.SimpleNamespace(stop_reason="end_turn", content=[block])


def test_review_maps_model_verdicts(tmp_path):
    payload = {"items": [{"id": "H-3", "pass": False, "confidence": 0.9, "failing_tiles": ["f0"], "note": "black first frame"},
                         {"id": "H1", "pass": True, "confidence": 0.8, "failing_tiles": [], "note": ""},
                         {"id": "BOGUS", "pass": True, "confidence": 1, "failing_tiles": [], "note": ""}], "summary": "ok"}
    fc = FakeClient(payload)
    rules, info = vision.review(str(tmp_path / "v"), RECIPES, plates_dir=_plates(tmp_path), client=fc)
    assert info["status"] == "ok"
    by = {r["id"]: r for r in rules}
    assert by["H-3.vision"]["status"] == "fail" and by["H-3.vision"]["hard"]
    assert by["H1.vision"]["status"] == "pass" and not by["H1.vision"]["hard"]
    assert "BOGUS.vision" not in by
    kw = fc.calls[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["messages"][0]["content"][0]["type"] == "image"
    assert kw["output_config"]["format"]["type"] == "json_schema"


def test_review_survives_api_error(tmp_path):
    class Boom(FakeClient):
        def _create(self, **kw):
            raise ConnectionError("network down")
    rules, info = vision.review(str(tmp_path / "v"), RECIPES, plates_dir=_plates(tmp_path), client=Boom({}))
    assert info["status"] == "error" and all(r["status"] == "skip" for r in rules)


def test_score_weights_and_gate():
    def rs(sec, n_pass, n_fail, hard=False):
        return [rule(f"{sec}-p{i}", sec, "pass", hard=False) for i in range(n_pass)] + \
               [rule(f"{sec}-f{i}", sec, "fail", hard=hard) for i in range(n_fail)]
    all_pass = sum((rs(s, 2, 0) for s in report.SECTION_WEIGHTS), [])
    s = report.score(all_pass)
    assert s["engagement_score"] == 100.0 and s["decision"] == "PUBLISH"
    # half of SOUND fails: 100 - 10 * 0.5 = 95, still publishable
    s = report.score(sum((rs(x, 2, 0) for x in report.SECTION_WEIGHTS if x != "SOUND"), []) + rs("SOUND", 1, 1))
    assert s["engagement_score"] == 95.0 and s["decision"] == "PUBLISH"
    # a hook miss blocks PUBLISH (Hook must be 100%)
    s = report.score(all_pass + rs("HOOK", 0, 1))
    assert s["decision"] == "AUTO_FIX"
    assert report.score(all_pass + rs("HOOK", 0, 1), iteration=2)["decision"] == "RETURN"
    # any HARD fail returns to stage 1/4
    s = report.score(all_pass + [rule("C-1.captions", "CAPTIONS", "fail")])
    assert s["hard_failures"] == ["C-1.captions"] and s["decision"] == "RETURN"
    # TECH failure blocks PUBLISH but is not scored
    s = report.score(all_pass + [rule("TQ-PLATE-BLACK", "TECH", "fail")])
    assert s["engagement_score"] == 100.0 and s["decision"] == "AUTO_FIX"
    # sections with nothing evaluated are left out and reported in coverage
    assert report.score(rs("TECH", 3, 0))["decision"] == "INCOMPLETE"
    s = report.score(rs("HOOK", 1, 0))
    assert s["coverage"] == 0.3 and s["engagement_score"] == 100.0


def test_cli_on_sentinel_episode(tmp_path, capsys):
    from factory.qc.__main__ import main
    rc = main(["run", "--episode", SENTINEL, "--out", str(tmp_path), "--no-vision"])
    assert rc == 0
    rep = json.load(open(tmp_path / "report.json"))
    assert rep["schema"] == "factory.qc.report/1"
    assert set(rep["sections"]) >= set(report.SECTION_WEIGHTS)
    assert 0 <= rep["engagement_score"] <= 100 and rep["decision"] in ("PUBLISH", "AUTO_FIX", "RETURN")
    ids = {r["id"] for r in rep["rules"]}
    assert {"H-1.first_word", "C-1.captions", "P-1.asl_overall", "H1", "N-1.wps"} <= ids
    for r in rep["rules"]:
        assert r["status"] in ("pass", "fail", "warn", "skip") and r["section"]
    assert "engagement_score" in capsys.readouterr().out
