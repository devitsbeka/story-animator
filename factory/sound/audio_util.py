"""ffmpeg/numpy helpers for the sound stage: decode, write, EBU R128 measurement, envelope analysis."""
import os, re, subprocess
import numpy as np

SR = 48000
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=kw.pop("text", True), **kw)
    if r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(map(str, cmd))[:400]}\n{r.stderr[-2000:]}")
    return r


def decode(path, sr=SR, ch=2):
    """Decode any audio file to float32 array of shape (n, ch)."""
    r = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-ac", str(ch), "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"decode failed {path}: {r.stderr.decode()[-500:]}")
    return np.frombuffer(r.stdout, np.float32).reshape(-1, ch).copy()


def write_wav(path, x, sr=SR):
    """Write float32 (n, ch) to a 32-bit float WAV (no clipping in intermediate stems)."""
    x = np.ascontiguousarray(np.asarray(x, np.float32))
    if x.ndim == 1:
        x = x[:, None]
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    p = subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", str(x.shape[1]), "-i", "-",
                        "-c:a", "pcm_f32le", path], input=x.tobytes(), capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode()[-800:])
    return path


_NUM = r"(-?(?:inf|\d+(?:\.\d+)?))"


def ebur128(path, pre_filter=None):
    """Measure with ffmpeg's ebur128 filter (BS.1770-4, true peak on).
    Returns {I, LRA, TP, S: [(t, short_term)], M_max}. pre_filter is prepended (e.g. an aselect)."""
    af = (pre_filter + "," if pre_filter else "") + "ebur128=peak=true:framelog=info"
    r = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", path, "-af", af, "-f", "null", "-"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-1500:])
    err = r.stderr
    S, M = [], []
    for m in re.finditer(r"t:\s*" + _NUM + r"\s+TARGET:.*?M:\s*" + _NUM + r"\s+S:\s*" + _NUM, err):
        t, mm, ss = (float(v) for v in m.groups())
        S.append((t, ss))
        M.append(mm)
    summ = err[err.rfind("Summary:"):]
    def grab(pat):
        m = re.search(pat, summ, re.S)
        return float(m.group(1)) if m else float("nan")
    return {
        "I": grab(r"Integrated loudness:.*?I:\s*" + _NUM),
        "LRA": grab(r"Loudness range:.*?LRA:\s*" + _NUM),
        "TP": grab(r"True peak:.*?Peak:\s*" + _NUM),
        "S": S,
        "M_max": max(M) if M else float("-inf"),
        "raw_summary": summ.strip(),
    }


def silences(path, noise_db=-40.0, min_d=0.3, pre_filter=None):
    """ffmpeg silencedetect -> list of (start, end) seconds."""
    af = (pre_filter + "," if pre_filter else "") + f"silencedetect=n={noise_db}dB:d={min_d}"
    r = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", path, "-af", af, "-f", "null", "-"],
                       capture_output=True, text=True)
    starts = [float(v) for v in re.findall(r"silence_start:\s*(-?\d+(?:\.\d+)?)", r.stderr)]
    ends = [float(v) for v in re.findall(r"silence_end:\s*(-?\d+(?:\.\d+)?)", r.stderr)]
    return list(zip(starts, ends + [float("nan")] * (len(starts) - len(ends))))


def envelope_db(x, sr=SR, win=0.01):
    mono = x.mean(axis=1) if x.ndim == 2 else x
    hop = max(1, int(sr * win))
    n = len(mono) // hop
    if n == 0:
        return np.array([-120.0])
    e = np.sqrt((mono[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    return 20 * np.log10(e)


def analyse(x, sr=SR):
    """Timing landmarks of a one-shot: onset (first 10 ms window within 24 dB of max), peak, active end."""
    env = envelope_db(x, sr)
    mx = env.max()
    win = 0.01
    above = np.nonzero(env > mx - 24)[0]
    act = np.nonzero(env > mx - 40)[0]
    peak_i = int(np.argmax(env))
    return {
        "dur": len(x) / sr,
        "onset": float(above[0] * win) if len(above) else 0.0,
        "peak": float(peak_i * win + win / 2),
        "end": float((act[-1] + 1) * win) if len(act) else len(x) / sr,
        "peak_db": float(20 * np.log10(np.abs(x).max() + 1e-12)),
    }
