import json
import os

from factory.director import checks

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def test_reserved_gaps_do_not_count_as_slow_delivery():
    """L024: a short whose narration leaves canon gaps (CAN-N2) is paced on the time the narrator speaks."""
    p = os.path.join(ROOT, "episodes", "waterspout_v2", "_llm", "develop.3.json")
    if not os.path.exists(p):
        import pytest
        pytest.skip("waterspout_v2 attempt not present")
    s = json.load(open(p))
    rep = checks.check_story(s)
    assert "N-1" not in [i["rule"] for i in rep.blocking]
    s2 = dict(s, narration_gaps=[])
    rep2 = checks.check_story(s2)
    assert "N-1" in [i["rule"] for i in rep2.blocking]   # the same words without declared gaps would be too slow
