"""L012 regression: no silent render failures. A missing plate fails the local render stage, a Python exception in
render_episode.py exits non-zero (--python-exit-code), and a previs keyframe that did not render fails previs."""
import json
import os

import pytest

from conftest import FAKE_BLENDER, IDEA, ROOT
from factory.run import render
from factory.run.pipeline import Options, Pipeline

SENTINEL = os.path.join(ROOT, "episodes", "sentinel", "episode_v4.json")


def test_blender_cmd_exits_nonzero_on_python_errors():
    job = {"frameStart": 1, "frameEnd": 2, "quality": "preview", "engine": "EEVEE"}
    cmd = render.blender_cmd(job, "/s.json", "/p", "blender")
    i = cmd.index("--python-exit-code")
    assert cmd[i + 1] == "1" and i < cmd.index("-P")


def test_missing_plate_is_reported(tmp_path, monkeypatch):
    spec = json.load(open(SENTINEL))
    spec["shots"] = spec["shots"][:1]
    sp = tmp_path / "ep.json"
    sp.write_text(json.dumps(spec))
    skip = spec["shots"][0]["from"] + 3
    monkeypatch.setenv("FAKE_SKIP", str(skip))
    res = render.render_local(spec, str(sp), str(tmp_path / "plates"), "preview", blender=FAKE_BLENDER, log=lambda m: None)
    assert res["missingCount"] == 1 and res["missing"] == [f"{spec['shots'][0]['id']}/{skip:04d}"]


def test_pipeline_render_stage_fails_on_missing_plate(tmp_path, monkeypatch):
    o = Options(idea=IDEA, offline=True, stubs=frozenset({"previs", "finish", "mix"}), auto_approve=True,
                episodes_dir=str(tmp_path / "eps"), blender=FAKE_BLENDER, regress="warn")
    monkeypatch.setenv("FAKE_SKIP", "5")
    doc = Pipeline(o, "miss", log=lambda m: None).run()
    assert doc["status"] == "failed" and doc["stages"]["render"]["status"] == "failed"
    assert "plates missing" in doc["stages"]["render"]["error"] and doc["stages"]["finish"]["status"] == "pending"


def test_previs_fails_when_a_keyframe_is_missing(tmp_path, monkeypatch):
    from factory.run import previs
    real = previs.render_keys

    def lossy(spec, *a, **kw):
        info = real(spec, *a, **kw)
        info["missing"] = [spec["shots"][0]["id"]]
        return info
    monkeypatch.setattr(previs, "render_keys", lossy)
    o = Options(idea=IDEA, offline=True, stubs=frozenset({"previs", "render", "finish", "mix"}), auto_approve=True,
                episodes_dir=str(tmp_path / "eps"), regress="warn")
    doc = Pipeline(o, "pv", log=lambda m: None).run()
    assert doc["stages"]["previs"]["status"] == "failed" and "did not render" in doc["stages"]["previs"]["error"]
