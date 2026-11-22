"""tools/merge_gate.py helpers (the full gate is exercised by running tools/merge_gate.sh on a branch)."""
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import merge_gate as MG  # noqa: E402


def test_test_dirs_cover_every_area():
    dirs = MG.test_dirs(ROOT)
    assert {"tests/lessons", "tests/goldens", "tests/direction", "tests/run", "tests/qc"} <= set(dirs)
    assert "factory/direction/test_direction.py" in dirs


def test_validator_pairs_and_current_episode(tmp_path):
    assert MG.current_episode(ROOT).endswith("episode_v5.json")
    pairs, ep = MG.validator_fails(ROOT, dict(os.environ), str(tmp_path / "v.json"))
    assert ep.endswith("episode_v5.json") and ("PROXY", "A04") in pairs     # known L012 defect in v5
    assert json.load(open(tmp_path / "v.json"))["shots_n"] == 35


def test_shell_wrapper_syntax():
    assert subprocess.run(["bash", "-n", os.path.join(ROOT, "tools", "merge_gate.sh")]).returncode == 0
    r = subprocess.run(["bash", os.path.join(ROOT, "tools", "merge_gate.sh")], capture_output=True, text=True)
    assert r.returncode == 2 and "usage" in r.stderr


def test_canon_pass_step(tmp_path):
    fails, err = MG.canon_fails(ROOT, dict(os.environ), str(tmp_path / "c.json"))
    assert err is None and isinstance(fails, set)
    rules = json.load(open(tmp_path / "c.json"))["rules"]
    assert {"CAN-C1", "CAN-P2"} <= set(rules) and fails == {k for k, r in rules.items() if r["status"] == "FAIL"}
    # a side without factory/canon (an old base) reports "did not run" instead of crashing
    (tmp_path / "episodes" / "sentinel").mkdir(parents=True)
    (tmp_path / "episodes" / "sentinel" / "episode_v1.json").write_text("{}")
    assert MG.canon_fails(str(tmp_path), dict(os.environ), str(tmp_path / "x.json"))[0] is None
