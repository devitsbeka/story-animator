"""The in-pipeline regress check runs the film-craft canon pass: a canon FAIL blocks, MANUAL rules are warnings."""
import json
import os
import shutil

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _ep(tmp_path):
    p = tmp_path / "run" / "episode.json"
    p.parent.mkdir()
    shutil.copy(os.path.join(ROOT, "episodes", "sentinel", "episode_v5.json"), p)
    return str(p)


def test_regress_runs_real_canon_pass(tmp_path):
    from factory.lessons import regress
    rep = regress.episode_regress(_ep(tmp_path), gate="previs", goldens=False)
    c = rep["canon"]
    assert c["rc"] in (0, 1) and os.path.exists(c["report"]) and c["report"].endswith(os.path.join("qc", "canon_previs.json"))
    assert set(c["fail"]) | set(c["manual"]) <= set(json.load(open(c["report"]))["rules"])
    assert any(w.startswith("CANON-MANUAL") for w in rep["warnings"]) == bool(c["manual"])


def test_canon_fail_blocks(tmp_path, monkeypatch):
    from factory.lessons import regress
    monkeypatch.setattr(regress, "canon_pass", lambda *a, **k: {"rc": 1, "fail": ["CAN-C1"], "manual": [], "details": {"CAN-C1": "no wide"}})
    rep = regress.episode_regress(_ep(tmp_path), gate="publish", goldens=False)
    assert not rep["ok"] and any(b.startswith("CANON:CAN-C1") for b in rep["blocking"])
    monkeypatch.setenv("FACTORY_CANON", "0")
    (tmp_path / "off").mkdir()
    assert "canon" not in regress.episode_regress(_ep(tmp_path / "off"), goldens=False)
