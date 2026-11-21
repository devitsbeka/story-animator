"""ffmpeg helpers for the voice stage: probe, decode, clipping, silences, loudness, tempo, concat."""
import json
import os
import re
import subprocess

import numpy as np

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
SR = 44100
_NUM = r"(-?(?:inf|\d+(?:\.\d+)?))"

# voice stem target before the mix (ENGAGEMENT_RECIPE S-2: dialogue about -16..-14 LUFS,
# true peak headroom for the master limiter)
VOICE_LUFS = -16.0
VOICE_TP = -1.5


def _run(cmd, binary=False):
    r = subprocess.run(cmd, capture_output=True, text=not binary)
    if r.returncode != 0:
        err = r.stderr if not binary else r.stderr.decode(errors="replace")
        raise RuntimeError(f"command failed: {' '.join(map(str, cmd))[:300]}\n{err[-1500:]}")
    return r


def duration(path):
    r = _run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json", path])
    return float(json.loads(r.stdout)["format"]["duration"])


def decode_mono(path, sr=SR):
    r = _run([FFMPEG, "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], binary=True)
    return np.frombuffer(r.stdout, np.float32)


def clipping(path, thresh=0.999):
    """Count of decoded samples at or above full scale, and the sample peak in dBFS."""
    x = decode_mono(path)
    if len(x) == 0:
        return {"clipped_samples": 0, "peak_dbfs": float("-inf")}
    pk = float(np.abs(x).max())
    return {"clipped_samples": int((np.abs(x) >= thresh).sum()),
            "peak_dbfs": round(20 * np.log10(pk + 1e-12), 2)}


def silences(path, noise_db=-40.0, min_d=0.12):
    r = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", path, "-af",
                        f"silencedetect=n={noise_db}dB:d={min_d}", "-f", "null", "-"], capture_output=True, text=True)
    starts = [float(v) for v in re.findall(r"silence_start:\s*(-?\d+(?:\.\d+)?)", r.stderr)]
    ends = [float(v) for v in re.findall(r"silence_end:\s*(-?\d+(?:\.\d+)?)", r.stderr)]
    return list(zip(starts, ends + [float("nan")] * (len(starts) - len(ends))))


def loudness(path):
    """EBU R128 integrated loudness and true peak via ffmpeg ebur128."""
    r = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", path, "-af", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True)
    summ = r.stderr[r.stderr.rfind("Summary:"):]

    def grab(pat):
        m = re.search(pat, summ, re.S)
        return float(m.group(1)) if m else float("nan")

    return {"I": grab(r"Integrated loudness:.*?I:\s*" + _NUM), "TP": grab(r"True peak:.*?Peak:\s*" + _NUM)}


def _encode_args(dst):
    if dst.endswith(".mp3"):
        return ["-c:a", "libmp3lame", "-b:a", "128k"]
    return ["-c:a", "pcm_s16le"]


def normalize(src, dst, target_i=VOICE_LUFS, target_tp=VOICE_TP, tempo=1.0):
    """Two-pass loudnorm (linear) to target_i / target_tp, optional atempo, mono 44.1 kHz.
    Returns the measured loudness of the result."""
    pre = f"atempo={tempo:.5f}," if abs(tempo - 1.0) > 1e-4 else ""
    r = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", src, "-af",
                        pre + f"loudnorm=I={target_i}:TP={target_tp}:LRA=11:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if m:
        st = json.loads(m.group(0))
        ln = (f"loudnorm=I={target_i}:TP={target_tp}:LRA=11:measured_I={st['input_i']}:"
              f"measured_TP={st['input_tp']}:measured_LRA={st['input_lra']}:measured_thresh={st['input_thresh']}:"
              f"offset={st['target_offset']}:linear=true")
    else:
        ln = f"loudnorm=I={target_i}:TP={target_tp}:LRA=11"
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    _run([FFMPEG, "-v", "error", "-y", "-i", src, "-af", pre + ln, "-ac", "1", "-ar", str(SR)]
         + _encode_args(dst) + [dst])
    out = loudness(dst)
    # loudnorm falls back to dynamic mode when linear gain would break the TP ceiling; a short file can
    # land a little low.  One corrective static gain keeps I on target without touching TP headroom.
    if out["I"] == out["I"] and abs(out["I"] - target_i) > 0.6:
        g = min(target_i - out["I"], target_tp - out["TP"]) if out["TP"] == out["TP"] else target_i - out["I"]
        if abs(g) > 0.3:
            tmp = dst + ".gain" + os.path.splitext(dst)[1]
            _run([FFMPEG, "-v", "error", "-y", "-i", dst, "-af", f"volume={g:.2f}dB"] + _encode_args(tmp) + [tmp])
            os.replace(tmp, dst)
            out = loudness(dst)
    return out


def concat(paths, dst, gap_s=0.0):
    """Concatenate takes (re-encode) with optional silence between them. Returns the start offset of each."""
    offsets, t = [], 0.0
    inputs, filt = [], []
    for i, p in enumerate(paths):
        offsets.append(t)
        t += duration(p) + (gap_s if i < len(paths) - 1 else 0.0)
        inputs += ["-i", p]
        pad = f",apad=pad_dur={gap_s}" if gap_s and i < len(paths) - 1 else ""
        filt.append(f"[{i}:a]aformat=sample_rates={SR}:channel_layouts=mono{pad}[a{i}]")
    filt.append("".join(f"[a{i}]" for i in range(len(paths))) + f"concat=n={len(paths)}:v=0:a=1[out]")
    _run([FFMPEG, "-v", "error", "-y"] + inputs + ["-filter_complex", ";".join(filt), "-map", "[out]"]
         + _encode_args(dst) + [dst])
    return offsets
