"""L009/L010 regression: the pose QC rules (pure Python) fail the original defects - seated lean-back hovering off
the seat (C21/C22 in v5: pitch -9 deg, gap 10-14 cm), flat fingers (4.7 deg mean flexion on every v5 shot) - and
pass a good pose. The Blender measurement on the real rig runs with RUN_BLENDER_POSEQC=1 (~1 min)."""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "cloud", "blender"))
import pose_rules as PR  # noqa: E402


def _m(**kw):
    m = {"shot": "S", "frame": 10, "stance": "stand", "seated": False, "seat_gap_m": None, "spine_pitch_deg": 4.0,
         "finger_curl_deg": {"L": 35.0, "R": 38.0}, "hand_shape": {"L": "relaxed", "R": "relaxed"}, "grips": [], "allow_lean_back": False}
    m.update(kw)
    return m


def _status(fs):
    return {f["rule"]: f["status"] for f in fs}


def test_good_pose_passes():
    fs = PR.evaluate(_m(grips=[{"prop": "radio", "hand": "R", "dist_m": 0.01}]))
    assert all(f["status"] == "pass" for f in fs) and PR.summarize(fs)["ok"]


def test_original_sit_defect_fails():
    # measured on v5 C21 by cloud/blender/test/pose_qc.py
    fs = PR.evaluate(_m(stance="sit_deck", seated=True, seat_gap_m=0.098, spine_pitch_deg=-8.9, finger_curl_deg={"L": 4.7, "R": 4.7}))
    st = _status(fs)
    assert st["POSE-SEAT"] == "fail" and st["POSE-SPINE"] == "fail"
    assert st["POSE-FINGERS.L"] == "fail" and st["POSE-FINGERS.R"] == "fail"
    assert PR.summarize(fs)["by_rule"] == {"POSE-SEAT": ["S"], "POSE-SPINE": ["S"], "POSE-FINGERS": ["S"]}


def test_seated_upright_on_seat_passes_and_story_lean_back_allowed():
    ok = PR.evaluate(_m(stance="sit_deck", seated=True, seat_gap_m=0.01, spine_pitch_deg=12.0))
    assert all(f["status"] == "pass" for f in ok)
    lean = PR.evaluate(_m(stance="sit_deck", seated=True, seat_gap_m=0.0, spine_pitch_deg=-15.0, allow_lean_back=True))
    assert _status(lean)["POSE-SPINE"] == "pass"
    sunk = PR.evaluate(_m(stance="sit_deck", seated=True, seat_gap_m=-0.06, spine_pitch_deg=10.0))
    assert _status(sunk)["POSE-SEAT"] == "fail"


def test_open_palm_exempts_fingers_and_grip_distance():
    fs = PR.evaluate(_m(finger_curl_deg={"L": 3.0, "R": 3.0}, hand_shape={"L": "open_palm", "R": "relaxed"}))
    st = _status(fs)
    assert st["POSE-FINGERS.L"] == "pass" and st["POSE-FINGERS.R"] == "fail"
    far = PR.evaluate(_m(grips=[{"prop": "radio", "hand": "R", "dist_m": 0.09}]))
    assert _status(far)["POSE-GRIP.R"] == "fail"


def test_down_stance_skips_spine():
    assert "POSE-SPINE" not in _status(PR.evaluate(_m(stance="down", spine_pitch_deg=70.0)))


@pytest.mark.skipif(not os.environ.get("RUN_BLENDER_POSEQC"), reason="set RUN_BLENDER_POSEQC=1 (Blender + library_store)")
def test_blender_pose_qc_on_v5(tmp_path):
    out = tmp_path / "pq.json"
    blender = os.environ.get("BLENDER", "/opt/blender/blender-4.2.3-linux-x64/blender")
    r = subprocess.run([blender, "-b", "--python-exit-code", "1", "--factory-startup", "-P", os.path.join(ROOT, "cloud", "blender", "test", "pose_qc.py"),
                        "--", "--spec", os.path.join(ROOT, "episodes", "sentinel", "episode_v5.json"), "--shots", "C21,C13", "--out", str(out)],
                       capture_output=True, text=True, timeout=1200)
    assert r.returncode == 0, r.stdout[-2000:]
    doc = json.loads(out.read_text())
    assert "C21" in doc["summary"]["by_rule"]["POSE-SPINE"] and "C21" in doc["summary"]["by_rule"]["POSE-SEAT"]
    grips = [g for m in doc["measurements"] if m["shot"] == "C13" for g in m["grips"]]
    assert grips and all(g["dist_m"] < 0.035 for g in grips)
