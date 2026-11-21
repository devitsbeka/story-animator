from factory.qc import captions
from factory.qc.episode import Word
from helpers import make_episode


def test_layout_matches_remotion_geometry():
    L = captions.layout({"from": 0, "to": 30, "small": "alone on a", "big": "yacht", "at": "top"})
    x0, y0, x1, y1 = L["box"]
    assert abs(y0 - 1920 * 0.115) < 1e-6  # top: 11.5% of the height, as in kit/type.tsx
    assert L["big_px"] == 150 and L["lines"] == 1
    assert abs((x0 + x1) / 2 - 540) < 1e-6  # centred
    low = captions.layout({"big": "North Sentinel", "at": "low"})
    assert abs(low["box"][1] - 1920 * 0.66) < 1e-6 and low["big_px"] == 96


def test_long_anchor_wraps():
    L = captions.layout({"big": "every single one of them out of the water today"})
    assert L["lines"] >= 2


def test_safe_rect_and_sync():
    words = [Word("stay", 1.0, 1.3), Word("quiet", 1.3, 1.7)]
    caps = [{"from": 30, "to": 50, "big": "stay quiet", "box": [200, 700, 800, 860]},  # inside, on its word
            {"from": 60, "to": 80, "big": "quiet", "at": "top"}]                     # top band is above y=290
    ep = make_episode(captions=caps, words=words, frames=120)
    rules, rows = captions.caption_checks(ep)
    by = {r["id"]: r for r in rules}
    assert rows[0]["inside_safe"] and not rows[1]["inside_safe"]
    assert by["C-1.captions"]["status"] == "fail" and by["C-1.captions"]["hard"]
    assert by["C-2.page_duration"]["status"] == "pass"  # 0.67 s pages
    # page 2 appears 0.7 s after "quiet" starts -> out of sync
    assert by["C-5.sync"]["status"] == "fail"
    caps[1] = {"from": 39, "to": 60, "big": "quiet", "box": [200, 700, 800, 860]}
    rules, _ = captions.caption_checks(make_episode(captions=caps, words=words, frames=120))
    by = {r["id"]: r for r in rules}
    assert by["C-1.captions"]["status"] == "pass" and by["C-5.sync"]["status"] == "pass"


def test_no_captions_skips():
    rules, _ = captions.caption_checks(make_episode())
    assert rules[0]["status"] == "skip"
