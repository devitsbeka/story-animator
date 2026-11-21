"""Final-video measurements with ffprobe/ffmpeg (no Python media deps).

One video pass (scaled to 270x480): blackdetect, freezedetect and the scene-change score.
One audio pass: silencedetect + ebur128 (integrated, short-term, true peak).
"""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess

import numpy as np

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


def available():
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _run(cmd, timeout=900):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed ({p.returncode}): {p.stderr[-800:]}")
    return p


def probe(path):
    p = _run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    d = json.loads(p.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    out = {"duration": float(d["format"].get("duration", 0)), "has_audio": a is not None}
    if v:
        num, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/1").split("/")
        out.update(width=int(v["width"]), height=int(v["height"]), fps=float(num) / float(den or 1),
                   nb_frames=int(v["nb_frames"]) if v.get("nb_frames", "").isdigit() else None, vcodec=v.get("codec_name"))
    if a:
        out.update(acodec=a.get("codec_name"), sample_rate=int(a.get("sample_rate", 0)), channels=a.get("channels"))
    return out


_F = r"(-?[\d.]+|-?inf|nan)"


def video_pass(path, scene_th=0.3, black_pix=0.10, black_min=0.1, freeze_noise=0.001, freeze_min=0.5, threads=2):
    # branch a: black/freeze/scene cuts; branch b: mpdecimate counts frames that differ from the
    # previous one (effective animation rate: a plate held for 3 frames shows as 10 fps)
    fc = (f"[0:v]scale=270:480,split[a][b];[a]blackdetect=d={black_min}:pix_th={black_pix},freezedetect=n={freeze_noise}:d={freeze_min},"
          f"select='gt(scene\\,{scene_th})',showinfo@cuts[o1];[b]mpdecimate,showinfo@uniq[o2]")
    p = _run([FFMPEG, "-hide_banner", "-nostats", "-threads", str(threads), "-i", path, "-filter_complex", fc,
              "-map", "[o1]", "-f", "null", "-", "-map", "[o2]", "-f", "null", "-"])
    err = p.stderr
    black = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)]
    fs = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", err)]
    fe = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", err)]
    freezes = [(s, fe[i] if i < len(fe) else None) for i, s in enumerate(fs)]
    cuts = [float(x) for x in re.findall(r"\[showinfo@cuts @[^\]]*\].*?pts_time:([\d.]+)", err)]
    unique = len(re.findall(r"\[showinfo@uniq @[^\]]*\].*?pts_time:", err))
    return {"black": black, "freeze": freezes, "cuts": cuts, "unique_frames": unique}


def audio_pass(path, sil_db=-40, sil_min=0.3):
    af = f"silencedetect=n={sil_db}dB:d={sil_min},ebur128=peak=true"
    p = _run([FFMPEG, "-hide_banner", "-nostats", "-i", path, "-vn", "-af", af, "-f", "null", "-"])
    err = p.stderr
    ss = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", err)]
    se = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    silences = [(s, se[i] if i < len(se) else None) for i, s in enumerate(ss)]
    st = [(float(t), float(m), float(s)) for t, m, s in re.findall(r"t:\s*([\d.]+)\s+TARGET:.*?M:\s*" + _F + r"\s+S:\s*" + _F, err)]
    summ = err[err.rfind("Summary:"):] if "Summary:" in err else ""
    I = re.search(r"I:\s+" + _F + r" LUFS", summ)
    LRA = re.search(r"LRA:\s+" + _F + r" LU", summ)
    TP = re.search(r"Peak:\s+" + _F + r" dBFS", summ)
    f = lambda m: float(m.group(1)) if m else None  # noqa: E731
    return {"integrated": f(I), "lra": f(LRA), "true_peak": f(TP), "short_term": st, "silences": silences}


def frame_at(path, t, w=270, h=480):
    """One decoded frame at time t (s) as float RGB array in [0,1]."""
    from PIL import Image
    p = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, t):.3f}", "-i", path, "-frames:v", "1",
                        "-vf", f"scale={w}:{h}", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, timeout=120)
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError(f"frame extract failed at {t}s: {p.stderr[-300:]!r}")
    return np.asarray(Image.open(io.BytesIO(p.stdout)).convert("RGB"), dtype=np.float32) / 255.0


def ssim(a, b):
    """Global-window SSIM on luma (Wang et al. constants), arrays in [0,1]."""
    ya = a[..., :3] @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    yb = b[..., :3] @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    # 8x8 block statistics
    H, W = (ya.shape[0] // 8) * 8, (ya.shape[1] // 8) * 8
    A = ya[:H, :W].reshape(H // 8, 8, W // 8, 8)
    B = yb[:H, :W].reshape(H // 8, 8, W // 8, 8)
    ma, mb = A.mean((1, 3)), B.mean((1, 3))
    va, vb = A.var((1, 3)), B.var((1, 3))
    cov = ((A - ma[:, None, :, None]) * (B - mb[:, None, :, None])).mean((1, 3))
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    s = ((2 * ma * mb + c1) * (2 * cov + c2)) / ((ma ** 2 + mb ** 2 + c1) * (va + vb + c2))
    return float(s.mean())
