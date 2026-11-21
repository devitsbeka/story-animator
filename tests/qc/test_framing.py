import math

import numpy as np

from factory.qc import framing
from helpers import hero_shot, make_episode


def test_project_centre_and_offsets():
    cam, look = np.array([0.0, 0.0, 10.0]), np.array([0.0, 0.0, 0.0])
    x, y, d = framing.project(look, cam, look, 30.0, 0.0, 9 / 16)
    assert abs(x - 0.5) < 1e-9 and abs(y - 0.5) < 1e-9 and abs(d - 10) < 1e-9
    # a point at the top edge of a 30 deg vertical fov
    top = np.array([0.0, 10 * math.tan(math.radians(15)), 0.0])
    x, y, _ = framing.project(top, cam, look, 30.0, 0.0, 9 / 16)
    assert abs(y) < 1e-9 and abs(x - 0.5) < 1e-9
    # +x world is screen right; behind the camera -> None
    xr, _, _ = framing.project(np.array([1.0, 0, 0]), cam, look, 30.0, 0.0, 9 / 16)
    assert xr > 0.5
    assert framing.project(np.array([0, 0, 20.0]), cam, look, 30.0, 0.0, 9 / 16) is None


def test_roll_rotates_screen():
    cam, look = np.array([0.0, 0.0, 10.0]), np.zeros(3)
    p = np.array([0.0, 1.0, 0.0])
    x0, _, _ = framing.project(p, cam, look, 30, 0.0, 9 / 16)
    x1, _, _ = framing.project(p, cam, look, 30, 20.0, 9 / 16)
    assert abs(x0 - 0.5) < 1e-9 and abs(x1 - 0.5) > 0.01


def test_rig_matches_keys_without_jitter():
    keys = [{"f": 0, "cam": [0, 0, 10], "look": [0, 0, 0], "fov": 30, "ease": "linear"},
            {"f": 10, "cam": [0, 0, 20], "look": [0, 0, 0], "fov": 60, "ease": "linear"}]
    cam, look, fov, roll = framing.rig_at(5, keys, handheld=0.0, drift=0.0)
    assert np.allclose(cam, [0, 0, 15]) and np.allclose(look, [0, 0, 0])
    assert abs(fov - math.sqrt(30 * 60)) < 1e-6  # log-space fov blend like the renderer


def test_yacht_space_heading_moves_camera():
    s = hero_shot()
    s["yacht"]["heading"] = math.pi / 2
    cam, look, _, _ = framing.camera_at(s, 0)
    # local +z rotated by +90 deg about Y lands on world +x
    assert cam[0] > 5.9 and abs(cam[2]) < 1e-6


def test_centred_hero_passes():
    ep = make_episode([hero_shot()])
    rules, per = framing.framing_checks(ep)
    by = {r["id"]: r for r in rules}
    assert per[0]["kind"] == "hero"
    assert by["H1"]["status"] == "pass" and by["H2"]["status"] == "pass"


def test_off_centre_hero_fails_h1():
    # aim the camera 0.9 m to the side of the eyes: still a hero shot, but the face is off-centre
    eye = [0.0, 1.0 + 1.8 * 0.90, 0.0]
    s = hero_shot(look=[0.9, eye[1], 0.0], cam=(0.9, eye[1], 3.0))
    rules, per = framing.framing_checks(make_episode([s]))
    by = {r["id"]: r for r in rules}
    assert by["H1"]["status"] == "fail", per
    assert by["H1"]["detail"] == ["S1"]


def test_insert_shot_uses_look_target():
    s = hero_shot(look=[3.0, 1.0, 0.0], cam=(3.0, 2.0, 2.0))
    rules, per = framing.framing_checks(make_episode([s]))
    assert per[0]["kind"] == "insert"
    assert any(r["id"] == "H1.subject" and r["status"] == "pass" for r in rules)
