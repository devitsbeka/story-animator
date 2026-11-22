"""Delivery (lesson L006): master mp4 -> final + mobile copies that pass the delivery profile, or refuse.

    python -m factory.deliver episodes/<id>/final/episode.mp4 [--out-dir episodes/<id>/final/delivery] [--name episode]

Writes <out>/<name>.mp4 (H.264 High, yuv420p, +faststart, keyframe every 1 s, capped VBV bitrate, AAC 48 kHz) and
<out>/<name>_mobile.mp4 (<= 720x1280, lower cap), checks both with factory.qc.delivery, writes <out>/delivery.json,
and exits 1 (removing the failed outputs) if either fails. `--check-only` verifies existing files without encoding.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from factory.qc import delivery, video

FINAL_ENC = {"maxrate_k": 10000, "bufsize_k": 10000, "crf": 18, "audio_k": 192, "max_h": 1920}
MOBILE_ENC = {"maxrate_k": 3000, "bufsize_k": 3000, "crf": 23, "audio_k": 128, "max_h": 1280}


def encode_cmd(src, dst, fps, enc, mobile=False):
    # keep the aspect, never upscale, even dimensions
    scale = f"scale=-2:'min({enc['max_h']},ih)'" if mobile else "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    g = max(1, int(round(fps)))
    return [video.FFMPEG, "-hide_banner", "-v", "error", "-y", "-i", src, "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", f"{scale},format=yuv420p", "-c:v", "libx264", "-profile:v", "high", "-preset", "medium",
            "-crf", str(enc["crf"]), "-maxrate", f"{enc['maxrate_k']}k", "-bufsize", f"{enc['bufsize_k']}k",
            "-g", str(g), "-keyint_min", str(g), "-sc_threshold", "0", "-force_key_frames", "expr:gte(t,n_forced*1)",
            "-c:a", "aac", "-b:a", f"{enc['audio_k']}k", "-ar", "48000", "-movflags", "+faststart", dst]


def deliver(src, out_dir=None, name="episode", check_only=False, log=print):
    if not os.path.isfile(src):
        raise FileNotFoundError(src)
    out_dir = out_dir or os.path.join(os.path.dirname(os.path.abspath(src)), "delivery")
    os.makedirs(out_dir, exist_ok=True)
    fps = video.probe(src).get("fps") or 30.0
    outs = {"final": os.path.join(out_dir, f"{name}.mp4"), "mobile": os.path.join(out_dir, f"{name}_mobile.mp4")}
    if not check_only:
        for kind, enc in (("final", FINAL_ENC), ("mobile", MOBILE_ENC)):
            log(f"[deliver] encoding {kind}: {outs[kind]}")
            subprocess.run(encode_cmd(src, outs[kind], fps, enc, mobile=kind == "mobile"), check=True)
    report = {"source": src, "outputs": {}, "ok": True}
    for kind, path in outs.items():
        if not os.path.isfile(path):
            report["outputs"][kind] = {"path": path, "ok": False, "error": "missing"}
            report["ok"] = False
            continue
        ok, rules, m = delivery.check_file(path, kind)
        report["outputs"][kind] = {"path": path, "ok": ok, "measured": m,
                                   "failed": [{"id": r["id"], "measured": r["measured"], "expected": r["expected"]} for r in rules if r["status"] != "pass"]}
        report["ok"] &= ok
    with open(os.path.join(out_dir, "delivery.json"), "w") as fh:
        json.dump(report, fh, indent=1, default=str)
    if not report["ok"] and not check_only:
        for kind, o in report["outputs"].items():
            if not o["ok"] and os.path.isfile(o["path"]):
                os.remove(o["path"])          # never leave a non-compliant deliverable behind
    return report


class DeliveryRefused(RuntimeError):
    pass


def deliver_or_raise(src, out_dir=None, name="episode", log=print):
    rep = deliver(src, out_dir, name, log=log)
    if not rep["ok"]:
        bad = {k: o.get("failed") or o.get("error") for k, o in rep["outputs"].items() if not o["ok"]}
        raise DeliveryRefused(f"delivery refused: {json.dumps(bad, default=str)[:600]}")
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m factory.deliver", description=__doc__.split("\n")[0])
    ap.add_argument("src")
    ap.add_argument("--out-dir")
    ap.add_argument("--name", default="episode")
    ap.add_argument("--check-only", action="store_true", help="verify existing <out>/<name>.mp4 and _mobile.mp4 only")
    a = ap.parse_args(argv)
    rep = deliver(a.src, a.out_dir, a.name, a.check_only)
    for kind, o in rep["outputs"].items():
        m = o.get("measured") or {}
        print(f"{'PASS' if o['ok'] else 'FAIL'} {kind:6} {o['path']}  {m.get('profile')} {m.get('pix_fmt')} faststart={m.get('moov_before_mdat')} "
              f"gop={m.get('max_gop_s')}s {m.get('video_kbps')} kbps (peak {m.get('peak_kbps')})")
        for f in o.get("failed") or []:
            print(f"     {f['id']}: measured {f['measured']} expected {f['expected']}")
    print("DELIVERY " + ("OK" if rep["ok"] else "REFUSED"))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
