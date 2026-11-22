import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "factory", "direction"))
import camera_fix  # noqa: E402
import shot_checks  # noqa: E402


def test_repair_fixes_cameras_inside_the_yacht_and_tight_close_ups():
    """L027: the waterspout v2 plan had 15 shots failing COLLIDE / FRAME-*; geometry alone fixes them."""
    p = os.path.join(ROOT, "episodes", "waterspout_v2", "episode.json")
    if not os.path.exists(p):
        import pytest
        pytest.skip("waterspout_v2 episode not present")
    ep = json.load(open(p))
    bad = sorted(shot_checks.check_episode(ep)["failing"])
    ep2 = copy.deepcopy(ep)
    fixed, still = camera_fix.repair_episode(ep2, bad)
    assert not still and set(fixed) == set(bad)
    assert not shot_checks.check_episode(ep2, shots=set(bad))["failing"]
    for sid, mv in fixed.items():    # never more than a 1 m rise; close-up framing is re-aimed, not re-angled
        assert mv.get("rise", 0) <= 1.0
