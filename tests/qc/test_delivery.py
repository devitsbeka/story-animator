"""L006 regression: the delivery profile check fails on the original defect (no faststart, long GOP) and
factory/deliver.py produces compliant final + mobile copies or refuses."""
import os
import subprocess

import pytest

from factory import deliver
from factory.qc import delivery, video

pytestmark = pytest.mark.skipif(not video.available(), reason="ffmpeg/ffprobe not installed")


def _src(path, extra=(), size="360x640", d=3):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=30:d={d}",
                    "-f", "lavfi", "-i", f"sine=f=330:d={d}", "-c:v", "libx264", "-preset", "ultrafast", *extra,
                    "-c:a", "aac", "-shortest", str(path)], check=True)
    return str(path)


def _by(rules):
    return {r["id"].split(".")[0]: r for r in rules}


def test_atoms_and_faststart(tmp_path):
    slow = _src(tmp_path / "slow.mp4")                                   # default mux: mdat before moov
    fast = _src(tmp_path / "fast.mp4", ["-movflags", "+faststart"])
    assert [t for t, _, _ in delivery.top_level_atoms(slow)][:1] == ["ftyp"]
    assert not delivery.moov_before_mdat(slow)
    assert delivery.moov_before_mdat(fast)


def test_original_defect_fails(tmp_path):
    # the L006 file: no faststart, one keyframe for the whole clip, yuv444 high-4:4:4 profile
    bad = _src(tmp_path / "bad.mp4", ["-g", "300", "-pix_fmt", "yuv444p"])
    ok, rules, m = delivery.check_file(bad, "final")
    r = _by(rules)
    assert not ok
    assert r["TQ-DELIVERY-FASTSTART"]["status"] == "fail"
    assert r["TQ-DELIVERY-GOP"]["status"] == "fail" and m["max_gop_s"] > 2.5
    assert r["TQ-DELIVERY-PIXFMT"]["status"] == "fail"
    assert r["TQ-DELIVERY-PROFILE"]["status"] == "fail"


def test_bitrate_cap(tmp_path):
    hot = _src(tmp_path / "hot.mp4", ["-b:v", "4000k", "-minrate", "4000k", "-maxrate", "4000k", "-bufsize", "1000k", "-x264-params", "nal-hrd=cbr"], d=2)
    m = delivery.measure(hot)
    rules = delivery.delivery_rules(m, dict(delivery.MOBILE, max_kbps=1000, max_peak_kbps=1500))
    assert _by(rules)["TQ-DELIVERY-BITRATE"]["status"] == "fail"


def test_deliver_produces_compliant_copies(tmp_path):
    src = _src(tmp_path / "master.mp4", ["-g", "300"], size="540x960", d=3)
    rep = deliver.deliver(src, str(tmp_path / "out"), log=lambda *a: None)
    assert rep["ok"], rep
    fin, mob = rep["outputs"]["final"], rep["outputs"]["mobile"]
    assert fin["measured"]["profile"] == "High" and fin["measured"]["moov_before_mdat"] and fin["measured"]["max_gop_s"] <= 1.04
    assert (fin["measured"]["width"], fin["measured"]["height"]) == (540, 960)
    assert mob["measured"]["height"] <= 1280 and mob["measured"]["has_audio"]
    assert os.path.isfile(os.path.join(tmp_path, "out", "delivery.json"))
    assert deliver.main([src, "--out-dir", str(tmp_path / "out"), "--check-only"]) == 0


def test_deliver_refuses_and_removes(tmp_path, monkeypatch):
    src = _src(tmp_path / "master.mp4", d=2)
    # sabotage the encoder: drop faststart and the GOP settings -> the check must refuse the outputs
    real = deliver.encode_cmd

    def broken(s, d, fps, enc, mobile=False):
        cmd = real(s, d, fps, enc, mobile)
        i = cmd.index("-movflags")
        del cmd[i:i + 2]
        return cmd
    monkeypatch.setattr(deliver, "encode_cmd", broken)
    with pytest.raises(deliver.DeliveryRefused):
        deliver.deliver_or_raise(src, str(tmp_path / "out"), log=lambda *a: None)
    assert not os.path.exists(tmp_path / "out" / "episode.mp4")
    assert deliver.main([src, "--out-dir", str(tmp_path / "out2")]) == 1
