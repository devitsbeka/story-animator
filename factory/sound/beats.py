"""Beat / tempo / accent analysis for music stems (numpy only; audio decoded with ffmpeg by audio_util.decode).

onset_envelope   log-magnitude spectral flux (half-wave rectified), one value per hop, normalised to [0, 1]
estimate_tempo   autocorrelation of the onset envelope, weighted by a log-normal prior around the nominal BPM
beat_grid        constant-tempo beat phase by comb search, each beat refined to the local onset peak
downbeats        which of the 4 beat phases carries the strongest accumulated onset energy (bar accent)
analyse_file     all of the above for one file -> plain dict (cacheable as JSON)

Generated and library tracks are close to constant tempo, so a phase-locked grid with local refinement is more
robust here than a full dynamic-programming beat tracker.
"""
import numpy as np

HOP = 512
NFFT = 2048
ONSET_LAG = 0.83


def onset_envelope(x, sr, hop=HOP, nfft=NFFT):
    """Spectral-flux onset strength. x: (n,) or (n, ch) float. Returns (env, frame_rate)."""
    mono = x.mean(axis=1) if x.ndim == 2 else np.asarray(x, np.float64)
    if len(mono) < nfft:
        mono = np.pad(mono, (0, nfft - len(mono)))
    n = 1 + (len(mono) - nfft) // hop
    idx = np.arange(nfft)[None, :] + hop * np.arange(n)[:, None]
    frames = mono[idx] * np.hanning(nfft)[None, :]
    mag = np.abs(np.fft.rfft(frames, axis=1))
    logm = np.log1p(1000.0 * mag)
    flux = np.maximum(0.0, np.diff(logm, axis=0, prepend=logm[:1])).sum(axis=1)
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")        # remove slow loudness trend
    flux = np.maximum(flux, 0.0)
    if flux.max() > 0:
        flux /= flux.max()
    # with log compression the flux of frame f (start f*hop) peaks when a transient is ONSET_LAG of the window
    # length into the frame (calibrated on synthetic clicks: 35 ms at nfft 2048, 14 ms at 1024); resample so that
    # env[k] is the onset strength at time k*hop/sr
    t_flux = (np.arange(n) * hop + ONSET_LAG * nfft) / sr
    env = np.interp(np.arange(n) * hop / sr, t_flux, flux, left=0.0, right=0.0)
    return env, sr / hop


def estimate_tempo(env, frame_rate, prior_bpm=None, bpm_range=(60.0, 190.0), prior_width=0.35):
    """Tempo in BPM from the autocorrelation of the onset envelope. prior_bpm biases octave choice."""
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    lags = np.arange(len(ac))
    lo = int(np.floor(60.0 * frame_rate / bpm_range[1]))
    hi = min(len(ac) - 1, int(np.ceil(60.0 * frame_rate / bpm_range[0])))
    if hi <= lo + 1:
        return float(prior_bpm or 120.0)
    cand = lags[lo:hi + 1]
    score = ac[lo:hi + 1].copy()
    # harmonic support: a true beat period also correlates at 2x and 4x the lag
    for mult in (2, 4):
        j = np.clip(cand * mult, 0, len(ac) - 1)
        score = score + 0.5 * ac[j] / mult
    if prior_bpm:
        bpm = 60.0 * frame_rate / cand
        score = score * np.exp(-0.5 * (np.log2(bpm / prior_bpm) / prior_width) ** 2)
    k = int(np.argmax(score))
    lag = float(cand[k])
    if 0 < k < len(score) - 1:                                       # parabolic interpolation
        a, b, c = score[k - 1], score[k], score[k + 1]
        d = a - 2 * b + c
        if d != 0:
            lag += 0.5 * (a - c) / d
    return 60.0 * frame_rate / lag


def _interp(env, frame_rate, t):
    return np.interp(np.asarray(t) * frame_rate, np.arange(len(env)), env, left=0.0, right=0.0)


def beat_grid(env, frame_rate, bpm, refine=0.08):
    """Beat times (s) on a constant-tempo grid whose phase maximises onset strength, each beat then moved to the
    strongest onset within +-refine*period (keeps the grid where the audio has no clear transient)."""
    period = 60.0 / bpm
    dur = len(env) / frame_rate
    phases = np.linspace(0, period, 96, endpoint=False)
    best, best_p = -1.0, 0.0
    for p in phases:
        s = _interp(env, frame_rate, np.arange(p, dur, period)).sum()
        if s > best:
            best, best_p = s, p
    grid = np.arange(best_p, dur, period)
    w = refine * period
    out = []
    for t in grid:
        a, b = int(max(0, (t - w) * frame_rate)), int(min(len(env), (t + w) * frame_rate + 1))
        seg = env[a:b]
        if len(seg) and seg.max() > 0.15 * env.max():
            out.append((a + int(np.argmax(seg))) / frame_rate)
        else:
            out.append(float(t))
    return np.array(out)


def beat_energy(x, sr, beats, win=0.08, lowpass_hz=200.0):
    """Per beat: power (dB) of the `win` seconds after it, full band and low band (kick / bass weight)."""
    mono = x.mean(axis=1) if x.ndim == 2 else np.asarray(x)
    w = int(win * sr)
    k = max(1, int(sr / lowpass_hz / 2))
    low = np.convolve(mono, np.ones(k) / k, mode="same")            # crude low-pass (box filter)
    full_db, low_db = [], []
    for t in beats:
        a = int(t * sr)
        seg, sl = mono[a:a + w], low[a:a + w]
        full_db.append(10 * np.log10(np.mean(seg.astype(np.float64) ** 2) + 1e-12) if len(seg) else -120.0)
        low_db.append(10 * np.log10(np.mean(sl.astype(np.float64) ** 2) + 1e-12) if len(sl) else -120.0)
    return np.array(full_db), np.array(low_db)


def downbeats(beats, env, frame_rate, meter=4, x=None, sr=None):
    """Index offset (0..meter-1) of the downbeat in `beats`, and the downbeat times. Uses the onset accent and,
    when the audio is given, the (low-band weighted) loudness right after each beat: bar accents in music are
    louder / heavier, which a compressed onset envelope underrates."""
    if len(beats) < meter:
        return 0, np.asarray(beats[:1])
    s = _interp(env, frame_rate, beats)
    if x is not None:
        full, low = beat_energy(x, sr, beats)
        z = lambda v: (v - v.mean()) / (v.std() + 1e-9)               # noqa: E731
        s = z(s) + z(full) + z(low)
    acc = [s[k::meter].mean() for k in range(meter)]
    k = int(np.argmax(acc))
    return k, np.asarray(beats[k::meter])


def accent(env, frame_rate, t, tol=0.035):
    """Onset strength at time(s) t: max of the envelope within +-tol seconds (tolerates a frame of jitter)."""
    t = np.atleast_1d(np.asarray(t, float))
    r = max(1, int(round(tol * frame_rate)))
    pad = np.concatenate([np.zeros(r), env, np.zeros(r)])
    win = np.lib.stride_tricks.sliding_window_view(pad, 2 * r + 1).max(axis=1)
    return _interp(win, frame_rate, t)


def loudness_curve(x, sr, win=1.0, hop=0.25):
    """Short RMS loudness (dBFS) every `hop` seconds over `win`-second windows: used to energy-match sections."""
    mono = x.mean(axis=1) if x.ndim == 2 else x
    w, h = int(win * sr), int(hop * sr)
    n = max(1, 1 + (len(mono) - w) // h)
    out = np.empty(n)
    for i in range(n):
        seg = mono[i * h:i * h + w]
        out[i] = 10 * np.log10(np.mean(seg.astype(np.float64) ** 2) + 1e-12)
    return out, 1.0 / hop


def analyse(x, sr, prior_bpm=None, meter=4):
    env, fr = onset_envelope(x, sr)
    bpm = estimate_tempo(env, fr, prior_bpm)
    beats = beat_grid(env, fr, bpm)
    k, dbs = downbeats(beats, env, fr, meter, x=x, sr=sr)
    # tempo stability: spread of inter-beat intervals relative to the period
    ibi = np.diff(beats)
    stab = float(np.std(ibi) / (60.0 / bpm)) if len(ibi) > 2 else 1.0
    loud, lr = loudness_curve(x, sr)
    return {"bpm": float(bpm), "beats": beats, "downbeat_phase": k, "downbeats": dbs, "env": env, "env_rate": fr,
            "ibi_jitter": stab, "loud": loud, "loud_rate": lr, "dur": len(x) / sr}
