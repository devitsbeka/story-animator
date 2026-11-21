import subprocess

import pytest

from factory.qc import video, video_rules
from helpers import hero_shot, make_episode

pytestmark = pytest.mark.skipif(not video.available(), reason="ffmpeg/ffprobe not installed")


def _by(rules):
    return {r["id"]: r for r in rules}


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    """3 s 1080x1920@30: 1 s black, 1 s still red, 1 s moving test pattern; a quiet sine tone
    with 1.2 s of silence in the middle."""
    p = str(tmp_path_factory.mktemp("v") / "clip.mp4")
    vf = ("color=c=black:s=1080x1920:r=30:d=1[a];color=c=red:s=1080x1920:r=30:d=1[b];"
          "testsrc2=s=1080x1920:r=30:d=1[c];[a][b][c]concat=n=3:v=1:a=0[v]")
    af = "sine=f=440:d=0.9,volume=0.5[s1];anullsrc=r=48000:cl=mono:d=1.2[z];sine=f=440:d=0.9,volume=0.5[s2];[s1][z][s2]concat=n=3:v=0:a=1[aud]"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-filter_complex", vf + ";" + af, "-map", "[v]", "-map", "[aud]",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", p], check=True)
    return p


def test_probe(clip):
    pr = video.probe(clip)
    assert (pr["width"], pr["height"]) == (1080, 1920)
    assert abs(pr["fps"] - 30) < 0.01 and abs(pr["duration"] - 3.0) < 0.1 and pr["has_audio"]


def test_measure_and_rules(clip):
    m = video_rules.measure(clip)
    assert m["video"]["black"] and m["video"]["black"][0][0] == 0.0  # black first second
    assert m["video"]["freeze"]  # the still red second (and the black one) are freezes > 0.5 s
    assert any(0.9 <= c <= 1.1 for c in m["video"]["cuts_merged"])  # black -> red cut
    a = m["audio"]
    assert a["integrated"] is not None and a["integrated"] < -20  # quiet tone
    assert any(0.8 <= s <= 1.0 and e and e - s > 1.0 for s, e in a["silences"])
    ep = make_episode([hero_shot("A", 0, 30), hero_shot("B", 30, 60), hero_shot("C", 60, 90)])
    by = _by(video_rules.video_rules(m, ep) + video_rules.detected_cut_rules(m, ep))
    assert by["TQ-VIDEO-RES"]["status"] == "pass"
    assert by["TQ-VIDEO-FPS"]["status"] == "pass"
    assert by["TQ-VIDEO-DURATION"]["status"] == "pass"
    assert by["TQ-VIDEO-BLACK"]["status"] == "fail"
    assert by["P-7.freeze"]["status"] == "fail"
    assert by["S-1.integrated"]["status"] == "fail" and by["S-1.integrated"]["hard"]
    assert by["S-6.no_gaps"]["status"] == "fail"
    assert by["TQ-VIDEO-EDIT-MATCH"]["status"] == "pass"  # cuts at 1 s and 2 s match the shots
    # two of the three seconds are still: ~1 + 1 + 30 distinct frames in 3 s
    assert 25 <= m["video"]["unique_frames"] <= 40
    assert by["TQ-VIDEO-EFFECTIVE-FPS"]["status"] == "fail"


def test_ssim_identity():
    import numpy as np
    a = np.random.default_rng(0).random((64, 64, 3)).astype("float32")
    assert video.ssim(a, a) > 0.999
    assert video.ssim(a, 1 - a) < 0.2


def test_merge_cuts():
    assert video_rules.merge_cuts([0.1, 0.2, 4.4, 4.5, 8.0]) == [0.1, 4.4, 8.0]
