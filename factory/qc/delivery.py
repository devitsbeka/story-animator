"""Delivery profile (lesson L006: a 43 MB file without faststart stalled after 11 s on a phone).

Every delivered mp4 must be: H.264 High profile, yuv420p, `moov` before `mdat` (+faststart, so playback starts
before the whole file arrives), a keyframe at least every 1 s (GOP <= fps frames), and a capped video bitrate.

    measure(path) -> {codec, profile, pix_fmt, fps, moov_before_mdat, atoms, max_gop_s, video_kbps, peak_kbps, ...}
    delivery_rules(m, profile=FINAL) -> QC rule dicts (section DELIVERY)

The atom order is read from the file itself (top-level MP4 boxes; no media library needed); keyframe times and
bitrate come from ffprobe packet data.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess

from . import video
from .common import check, rnd

# kbps caps on the video stream (average over the file / peak over any 1 s window)
FINAL = {"name": "final", "max_kbps": 12000, "max_peak_kbps": 20000, "max_gop_s": 1.0, "profiles": ("High",), "max_height": 1920}
MOBILE = {"name": "mobile", "max_kbps": 3500, "max_peak_kbps": 6000, "max_gop_s": 1.0, "profiles": ("High", "Main"), "max_height": 1280}
PROFILES = {"final": FINAL, "mobile": MOBILE}


def top_level_atoms(path, limit=64):
    """[(type, offset, size)] of the top-level MP4 boxes."""
    out = []
    size_total = os.path.getsize(path)
    with open(path, "rb") as fh:
        off = 0
        while off < size_total and len(out) < limit:
            fh.seek(off)
            hdr = fh.read(8)
            if len(hdr) < 8:
                break
            size, typ = struct.unpack(">I4s", hdr)
            if size == 1:
                size = struct.unpack(">Q", fh.read(8))[0]
            elif size == 0:
                size = size_total - off
            out.append((typ.decode("latin-1"), off, size))
            if size < 8:
                break
            off += size
    return out


def moov_before_mdat(path):
    types = [t for t, _, _ in top_level_atoms(path)]
    if "moov" not in types or "mdat" not in types:
        return False
    return types.index("moov") < types.index("mdat")


def _packets(path):
    p = subprocess.run([video.FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,dts_time,size,flags",
                        "-of", "json", path], capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe packets failed: {p.stderr[-400:]}")
    pk = json.loads(p.stdout).get("packets", [])
    rows = []
    for x in pk:
        t = x.get("pts_time", x.get("dts_time"))
        if t in (None, "N/A"):
            continue
        rows.append((float(t), int(x.get("size", 0)), "K" in x.get("flags", "")))
    rows.sort()
    return rows


def measure(path):
    p = subprocess.run([video.FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {p.stderr[-400:]}")
    d = json.loads(p.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), {})
    num, den = (v.get("avg_frame_rate") or "0/1").split("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    dur = float(d["format"].get("duration") or v.get("duration") or 0)
    pk = _packets(path)
    keys = [t for t, _, k in pk if k]
    t_end = pk[-1][0] + (1.0 / fps if fps else 0) if pk else dur
    bounds = keys + [t_end]
    gops = [b - a for a, b in zip(bounds, bounds[1:])]
    total_bits = sum(s for _, s, _ in pk) * 8
    peak = 0.0
    if pk:
        # sliding 1 s window over packet sizes
        j, acc = 0, 0
        for i, (t, s, _) in enumerate(pk):
            acc += s
            while pk[j][0] <= t - 1.0:
                acc -= pk[j][1]
                j += 1
            peak = max(peak, acc * 8 / 1000.0)
    return {"path": path, "bytes": os.path.getsize(path), "codec": v.get("codec_name"), "profile": v.get("profile"),
            "pix_fmt": v.get("pix_fmt"), "width": v.get("width"), "height": v.get("height"), "fps": rnd(fps, 3), "duration": rnd(dur, 3),
            "atoms": [t for t, _, _ in top_level_atoms(path)], "moov_before_mdat": moov_before_mdat(path),
            "keyframes": len(keys), "first_key": rnd(keys[0], 3) if keys else None, "max_gop_s": rnd(max(gops), 3) if gops else None,
            "video_kbps": rnd(total_bits / max(dur, 1e-6) / 1000.0, 1), "peak_kbps": rnd(peak, 1),
            "has_audio": any(s["codec_type"] == "audio" for s in d["streams"])}


def delivery_rules(m, profile=FINAL, section="DELIVERY"):
    pf = profile["name"]
    tol = 1.0 / m["fps"] + 1e-3 if m.get("fps") else 0.04
    out = [
        check(f"TQ-DELIVERY-CODEC.{pf}", section, m["codec"] == "h264", m["codec"], "H.264"),
        check(f"TQ-DELIVERY-PROFILE.{pf}", section, m["profile"] in profile["profiles"], m["profile"], " or ".join(profile["profiles"])),
        check(f"TQ-DELIVERY-PIXFMT.{pf}", section, m["pix_fmt"] == "yuv420p", m["pix_fmt"], "yuv420p"),
        check(f"TQ-DELIVERY-FASTSTART.{pf}", section, m["moov_before_mdat"], m["atoms"][:6], "moov before mdat (+faststart)"),
        check(f"TQ-DELIVERY-GOP.{pf}", section, m["max_gop_s"] is not None and m["max_gop_s"] <= profile["max_gop_s"] + tol and m["first_key"] == 0.0,
              {"max_gop_s": m["max_gop_s"], "keyframes": m["keyframes"], "first_key": m["first_key"]},
              f"keyframe at t=0 and at least every {profile['max_gop_s']} s"),
        check(f"TQ-DELIVERY-BITRATE.{pf}", section, (m["video_kbps"] or 0) <= profile["max_kbps"] and (m["peak_kbps"] or 0) <= profile["max_peak_kbps"],
              {"avg_kbps": m["video_kbps"], "peak_1s_kbps": m["peak_kbps"]}, f"avg <= {profile['max_kbps']} kbps, 1 s peak <= {profile['max_peak_kbps']} kbps"),
        check(f"TQ-DELIVERY-SIZE.{pf}", section, (m["height"] or 0) <= profile["max_height"], f"{m['width']}x{m['height']}", f"height <= {profile['max_height']}"),
    ]
    return out


def check_file(path, profile="final"):
    """-> (ok, rules, measurement)"""
    pf = PROFILES[profile] if isinstance(profile, str) else profile
    m = measure(path)
    rules = delivery_rules(m, pf)
    return all(r["status"] == "pass" for r in rules), rules, m
