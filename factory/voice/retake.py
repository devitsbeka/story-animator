"""Pace retake (canon CAN-N4f-pace, lesson L030): after voicing, every narration block lands inside the canon
per-block pace band (thresholds.yaml narration.wps, 2.2-3.3 w/s), or the stage says why not.

A block is the run of lines between two reserved narration gaps, measured exactly as the canon gate measures it
(pacing.block_pace is the one function both use). For every block outside the band, in order:

  1. tempo: ffmpeg atempo on that block's speech span alone. The TOTAL tempo the block's audio ever gets (the stage's
     global correction x this local one) stays inside voice_speed (0.9-1.1). Word timings inside the span are
     rescaled; nothing outside it moves except by the span's change in length.
     A slow block that tempo cannot fix may also have its over-long INTERNAL pauses (>= PAUSE_MIN_S, inside the
     speech span, never a reserved gap) tightened to no less than PAUSE_KEEP_S, only by what the band still needs.
     Speech is never cut. Steps 1 cost nothing.
  2. retake: when tempo alone cannot reach the band, the block is re-voiced alone: ElevenLabs speed inside
     voice_speed (aimed at the band centre from the pace measured so far), a new seed, and previous_text / next_text
     from the neighbouring lines so the take keeps the prosody of its context. Up to `max_takes` takes; the take whose
     pace is in the band (after an optional in-band tempo touch) and closest to the centre wins. It is gain-matched
     to the speech it replaces (EBU R128 on the speech spans) and spliced at the block's boundaries with short
     equal-power crossfades inside the surrounding silence.

The silence before and after the block is kept sample for sample (its first word lands where the old first word was,
the following silence is untouched), so the reserved narration gaps (gaps.py) are intact; every later word shifts
by the block's change in length. At most `max_lines` blocks are re-voiced per run, and a take is never requested
when it would push the stage past its cost ceiling (factory/run/costs.py STAGE_CEILINGS_USD["voice"]).
Every attempt, its speed, seed, pace and cost go to the voice report (narration.voice.json "pace_retake").
"""
import os
import subprocess

import numpy as np

from . import align, audio, pacing
from .backends import BackendError, ImportBackend
from .text import chunk_prompt, script_words, strip_tags

MAX_LINES = 3          # blocks re-voiced per run
MAX_TAKES = 2          # takes per re-voiced block
MARGIN_WPS = 0.05      # aim this far inside the band edge
EDGE_S = 0.12          # silence kept around the speech span on each side (bounded by half the real silence)
XFADE_S = 0.012        # crossfade length at each splice point
TEMPO_GUARD_S = 0.03   # tempo span starts/ends this far outside the first/last word (no clipped consonants)
PRESENCE_AMP = 0.0004  # padding where a take has less silence than the cut needs (never digital silence)
PAUSE_MIN_S = 0.30     # an internal pause this long or longer may be tightened (slow blocks only) ...
PAUSE_KEEP_S = 0.25    # ... never below this (a breath still reads as a beat)
PAUSE_DB = -40.0       # silence threshold for internal pauses (stem is at -16 LUFS)
TIGHTEN_MAX_S = 0.6    # at most this much pause removed from one block


def _usd(chars):
    from factory.run.costs import voice_usd
    return voice_usd(chars)


def stage_ceiling_usd():
    from factory.run.costs import stage_ceilings
    return stage_ceilings().get("voice")


# ---------------------------------------------------------------- audio helpers (float mono @ audio.SR)
def _write(x, dst):
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    p = subprocess.run([audio.FFMPEG, "-v", "error", "-y", "-f", "f32le", "-ar", str(audio.SR), "-ac", "1", "-i", "-"]
                       + audio._encode_args(dst) + [dst], input=np.asarray(x, np.float32).tobytes(), capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode()[-800:])
    return dst


def _atempo(x, factor, work, tag):
    src, dst = os.path.join(work, f"{tag}_in.wav"), os.path.join(work, f"{tag}_out.wav")
    _write(x, src)
    audio._run([audio.FFMPEG, "-v", "error", "-y", "-i", src, "-af", f"atempo={factor:.5f}", "-ac", "1",
                "-ar", str(audio.SR), "-c:a", "pcm_s16le", dst])
    return audio.decode_mono(dst)


def _lufs(x, work, tag):
    p = _write(x, os.path.join(work, f"{tag}_lufs.wav"))
    i = audio.loudness(p)["I"]
    return i if i == i and i > -70 else None


def _presence(n, seed=0):
    return (np.random.default_rng(seed).standard_normal(max(0, n)) * PRESENCE_AMP).astype(np.float32)


def _idx(t):
    return int(round(t * audio.SR))


H = max(1, _idx(XFADE_S / 2))   # crossfade half-length in samples


def splice(base, A, B, seg_ext, h=None):
    """Replace base[A:B] (sample indices) with the core of seg_ext, which carries h extra samples on each side. Both
    joins are equal-power crossfades of 2h samples centred on the cut, so the core starts exactly at output index A
    and the output is len(base) - (B - A) + (len(seg_ext) - 2h) samples long."""
    h = H if h is None else h
    if A - h < 0 or B + h > len(base) or len(seg_ext) < 4 * h:
        raise ValueError("splice too close to the file edge")
    core_n = len(seg_ext) - 2 * h
    t = np.linspace(0.0, np.pi / 2, 2 * h, dtype=np.float32)
    fin, fout = np.sin(t), np.cos(t)
    head = base[A - h:A + h] * fout + seg_ext[:2 * h] * fin
    tail = seg_ext[core_n:core_n + 2 * h] * fout + base[B - h:B + h] * fin
    return np.concatenate([base[:A - h], head, seg_ext[2 * h:core_n], tail, base[B + h:]]).astype(np.float32)


def band_distance(w, band):
    return max(0.0, band[0] - w, w - band[1])


# ---------------------------------------------------------------- planning
def _bounds(words, i0, i1, dur):
    ws, we = words[i0]["s"], words[i1]["e"]
    prev_e = words[i0 - 1]["e"] if i0 > 0 else 0.0
    next_s = words[i1 + 1]["s"] if i1 + 1 < len(words) else dur
    lead = max(0.0, min(EDGE_S, 0.5 * (ws - prev_e)))
    tail = max(0.0, min(EDGE_S, 0.5 * (next_s - we)))
    return ws, we, lead, tail


def _goal(w, band):
    lo, hi = band
    return lo + MARGIN_WPS if w < lo else hi - MARGIN_WPS


def _in(w, band):
    return band[0] - 1e-6 <= w <= band[1] + 1e-6


def _tempo_for(w, band, prior, vband):
    """Local atempo factor for a block measured at w w/s whose audio already had `prior` tempo: aimed inside the band,
    limited so prior x factor stays in voice_speed. Returns (factor, reaches_band)."""
    if _in(w, band):
        return 1.0, True
    f = _goal(w, band) / w
    f = min(max(f, vband[0] / prior), vband[1] / prior)
    return round(f, 4), _in(w * f, band)


def _block_words_wps(ws):
    return len(ws) / max(1e-6, ws[-1]["e"] - ws[0]["s"]) if ws else 0.0


def _pauses(x, work, tag):
    """[(start, end)] seconds of silences inside x (the speech span) long enough to tighten."""
    p = _write(x, os.path.join(work, f"{tag}_sil.wav"))
    dur = len(x) / audio.SR
    out = []
    for a, b in audio.silences(p, noise_db=PAUSE_DB, min_d=PAUSE_MIN_S):
        b = dur if b != b else b
        if a > 0.0 and b < dur and b - a >= PAUSE_MIN_S:
            out.append((a, b))
    return out


def _cut_map(cuts):
    """Time map for removed intervals [(c0, c1)] (sorted, non-overlapping)."""
    def m(t):
        d = 0.0
        for c0, c1 in cuts:
            if t >= c1:
                d += c1 - c0
            elif t > c0:
                return c0 - d
        return t - d
    return m


def fix_span(x, words, band, prior, vband, work, tag, tighten=True):
    """Local pace correction of one block inside the array x (words timed in x's seconds):
      1. atempo on the speech span alone, the total tempo (prior x local) inside voice_speed;
      2. for a slow block that tempo cannot fix: tighten over-long INTERNAL pauses (silences >= PAUSE_MIN_S inside the
         span, never the reserved gaps around it) down to PAUSE_KEEP_S, only by what the band still needs, then the
         same atempo. Speech itself is never cut.
    Returns (x', words', info); info["reaches"] says whether the block is now in band (x, words unchanged if not)."""
    n = len(words)
    ws, we = words[0]["s"], words[-1]["e"]
    dur = len(x) / audio.SR
    g = max(0.0, min(TEMPO_GUARD_S, ws, dur - we))
    G0, G1 = _idx(ws - g), _idx(we + g)
    span = we - ws
    w = n / max(1e-6, span)
    f, ok = _tempo_for(w, band, prior, vband)
    info = {"wps_in": round(w, 3), "tempo": f, "tempo_total": round(prior * f, 4), "tighten_s": 0.0, "cuts": [],
            "wps": round(w * f, 3), "reaches": ok}
    cuts = []
    if not ok and tighten and w < band[0]:
        f_hi = vband[1] / prior
        P = x[G0:G1]
        cand = sorted(_pauses(P, work, tag), key=lambda p: -(p[1] - p[0]))
        avail = min(TIGHTEN_MAX_S, sum(max(0.0, (b - a) - PAUSE_KEEP_S) for a, b in cand))
        # seconds of pause to remove at the highest allowed tempo: aim inside the margin, else just inside the edge
        need = span - f_hi * n / _goal(w, band)
        if need > avail:
            need = span - f_hi * n / (band[0] + 0.01)
        if 0 < need <= avail + 1e-9:
            left = need + 0.005
            for a, b in cand:
                take = min(left, (b - a) - PAUSE_KEEP_S)
                if take <= 0.004:
                    continue
                mid = (a + b) / 2.0
                cuts.append((G0 / audio.SR + mid - take / 2, G0 / audio.SR + mid + take / 2))
                left -= take
                if left <= 0:
                    break
            cuts.sort()
            cut_s = sum(c1 - c0 for c0, c1 in cuts)
            span2 = span - cut_s
            f, ok = _tempo_for(n / span2, band, prior, vband)
            info.update(tighten_s=round(cut_s, 3), cuts=[[round(c0, 3), round(c1, 3)] for c0, c1 in cuts],
                        tempo=f, tempo_total=round(prior * f, 4), wps=round(n / span2 * f, 3), reaches=ok)
    if not ok:
        return x, words, info
    # build the new span: pause cuts (short crossfades inside the silence) then atempo
    P = x[G0:G1].copy()
    for c0, c1 in sorted(cuts, reverse=True):
        a, b = _idx(c0) - G0, _idx(c1) - G0
        h = min(_idx(0.004), a, len(P) - b)
        t = np.linspace(0.0, np.pi / 2, 2 * h, dtype=np.float32)
        mix = P[a - h:a + h] * np.cos(t) + P[b - h:b + h] * np.sin(t)
        P = np.concatenate([P[:a - h], mix, P[b + h:]])
    if abs(f - 1.0) > 1e-4:
        P = _atempo(P, f, work, tag)
    m = _cut_map([(c0, c1) for c0, c1 in cuts])
    t0 = G0 / audio.SR
    new = [{"w": q["w"], "s": t0 + (m(q["s"]) - t0) / f, "e": t0 + (m(q["e"]) - t0) / f} for q in words]
    info["wps"] = round(_block_words_wps(new), 3)
    info["reaches"] = _in(_block_words_wps(new), band)
    return np.concatenate([x[:G0], P, x[G1:]]).astype(np.float32), new, info


def _context(lines, ids):
    pos = [k for k, ln in enumerate(lines) if ln["id"] in ids]
    prev = strip_tags(lines[pos[0] - 1]["text"]) if pos and pos[0] > 0 else None
    nxt = strip_tags(lines[pos[-1] + 1]["text"]) if pos and pos[-1] + 1 < len(lines) else None
    return {"previous_text": prev, "next_text": nxt}


# ---------------------------------------------------------------- main
def pace_retake(story, audio_path, words, backend, voice_id, model_id, fmt=None, speed=None, global_tempo=1.0,
                cache_dir=None, work=None, spent_usd=0.0, ceiling_usd="stage", max_lines=MAX_LINES,
                max_takes=MAX_TAKES, transcribe_fallback=True, target_lufs=audio.VOICE_LUFS, target_tp=audio.VOICE_TP,
                log=None, trim_word_ends=True):
    """Bring every canon block into the pace band (see module doc). Rewrites audio_path in place when anything changed.
    words: the final [{w, s, e}] of audio_path. Returns (words, report)."""
    log = log or (lambda *a: None)
    max_lines = MAX_LINES if max_lines is None else int(max_lines)
    max_takes = MAX_TAKES if max_takes is None else int(max_takes)
    band, vband = pacing.canon_bands()
    lines, gaps = story["narration"], story.get("narration_gaps") or []
    ceiling = stage_ceiling_usd() if ceiling_usd == "stage" else ceiling_usd
    work = work or os.path.join(os.path.dirname(os.path.abspath(audio_path)), ".pace_work")
    os.makedirs(work, exist_ok=True)
    can_retake = not isinstance(backend, ImportBackend) and hasattr(backend, "tts")
    before = pacing.block_pace(lines, gaps, words, band)
    rep = {"band": list(band), "voice_speed": list(vband), "global_tempo": global_tempo, "speed_base": speed,
           "cap": {"lines": max_lines, "takes": max_takes}, "ceiling_usd": ceiling, "spent_before_usd": round(spent_usd, 4),
           "before": [_row(b) for b in before], "fixes": [], "chars": 0, "usd": 0.0}
    bad = [b for b in before if b["measured"] and not b["in_band"]]
    if not bad:
        rep["after"] = rep["before"]
        rep["ok"] = True
        return words, rep
    base = audio.decode_mono(audio_path)
    dur = len(base) / audio.SR
    ref_lufs_cache = {}
    # worst blocks get the retake budget first
    order = sorted(bad, key=lambda b: -abs(b["wps_exact"] - (band[0] + band[1]) / 2))
    retakes_left, edits = max_lines, []
    for b in order:
        fx = {"lines": b["lines"], "before_wps": b["wps"], "method": None, "applied": False, "takes": []}
        rep["fixes"].append(fx)
        ws, we, lead, tail = _bounds(words, b["i0"], b["i1"], dur)
        w = b["wps_exact"]
        f, ok = _tempo_for(w, band, global_tempo, vband)
        fx["tempo_try"] = {"factor": f, "tempo_total": round(global_tempo * f, 4), "wps": round(w * f, 3), "reaches": ok}
        A, B = _idx(ws - lead), _idx(we + tail)
        # local correction on the stem itself (free): tempo, and for a slow block tighter internal pauses
        R0 = (A - H) / audio.SR
        reg = base[A - H:B + H]
        rw = [{"w": q["w"], "s": q["s"] - R0, "e": q["e"] - R0} for q in words[b["i0"]:b["i1"] + 1]]
        seg, nw, info = fix_span(reg, rw, band, global_tempo, vband, work, f"l{b['i0']}")
        fx["local_try"] = info
        if info["reaches"]:
            new_ws = [{"w": q["w"], "s": q["s"] + R0, "e": q["e"] + R0} for q in nw]
            fx.update(method="tempo" if not info["cuts"] else "tempo+pauses", tempo=info["tempo"],
                      tempo_total=info["tempo_total"], tighten_s=info["tighten_s"], speed=speed)
            edits.append((b, A, B, seg, new_ws, fx))
            continue
        if not can_retake:
            fx["method"] = "none"
            fx["reason"] = f"tempo cannot reach the band within {vband} and {getattr(backend, 'name', '?')} cannot re-voice"
            continue
        if retakes_left <= 0:
            fx["method"] = "none"
            fx["reason"] = f"retake cap reached ({max_lines} blocks per run)"
            continue
        retakes_left -= 1
        best = _retake(b, story, words, backend, voice_id, model_id, speed, global_tempo, w, band, vband, cache_dir,
                       work, spent_usd, ceiling, max_takes, transcribe_fallback, rep, fx, log, trim=trim_word_ends)
        if best is None:
            fx["method"] = fx.get("method") or "none"
            continue
        tk_x, tk_words = best
        # gain-match the take's speech to the speech it replaces
        if b["i0"] not in ref_lufs_cache:
            ref_lufs_cache[b["i0"]] = _lufs(base[_idx(ws):_idx(we)], work, f"ref{b['i0']}")
        tws, twe = tk_words[0]["s"], tk_words[-1]["e"]
        li = _lufs(tk_x[_idx(tws):_idx(twe)], work, f"take{b['i0']}")
        gain_db = (ref_lufs_cache[b["i0"]] - li) if (li is not None and ref_lufs_cache[b["i0"]] is not None) else 0.0
        tk_x = tk_x * (10 ** (gain_db / 20.0))
        pk = float(np.abs(tk_x).max()) if len(tk_x) else 0.0
        lim = 10 ** (target_tp / 20.0)
        if pk > lim:
            tk_x = tk_x * (lim / pk)
            gain_db += 20 * np.log10(lim / pk)
        fx["gain_db"] = round(float(gain_db), 2)
        L, T = _idx(ws) - A, B - _idx(we)
        pad = L + T + 2 * H + _idx(0.05)
        padded = np.concatenate([_presence(pad, 1), tk_x, _presence(pad, 2)])
        S, E = pad + _idx(tws), pad + _idx(twe)
        seg = padded[S - L - H:E + T + H]
        new_ws = [{"w": x["w"], "s": ws + (x["s"] - tws), "e": ws + (x["e"] - tws)} for x in tk_words]
        edits.append((b, A, B, seg, new_ws, fx))
    if not edits:
        rep["after"] = rep["before"]
        rep["ok"] = False
        return words, rep
    # apply the last block first so earlier sample positions stay valid; then shift the words once, in order
    for b, A, B, seg, new_ws, fx in sorted(edits, key=lambda e: -e[1]):
        base = splice(base, A, B, seg)
    by_i0 = {e[0]["i0"]: e for e in edits}
    out, k, delta = [], 0, 0.0
    while k < len(words):
        e = by_i0.get(k)
        if e is None:
            out.append({"w": words[k]["w"], "s": words[k]["s"] + delta, "e": words[k]["e"] + delta})
            k += 1
            continue
        b, A, B, seg, new_ws, fx = e
        out += [{"w": x["w"], "s": x["s"] + delta, "e": x["e"] + delta} for x in new_ws]
        d = ((len(seg) - 2 * H) - (B - A)) / audio.SR
        delta += d
        fx["shift_s"] = round(d, 3)
        fx["applied"] = True
        k = b["i1"] + 1
    words_out = align._finish([[w0["w"], x["s"], x["e"]] for w0, x in zip(words, out)])
    tmp = os.path.join(work, "paced.wav")
    _write(base, tmp)
    loud = audio.normalize(tmp, audio_path, target_lufs, target_tp)
    rep["loudness_after"] = loud
    after = pacing.block_pace(lines, gaps, words_out, band)
    rep["after"] = [_row(x) for x in after]
    for fx in rep["fixes"]:
        a_row = next((x for x in after if x["lines"] == fx["lines"]), None)
        fx["after_wps"] = a_row["wps"] if a_row else None
        fx["in_band"] = bool(a_row and a_row["in_band"])
    rep["ok"] = all(x["in_band"] for x in after if x["measured"])
    rep["usd"] = round(rep["usd"], 4)
    log(f"[voice] pace retake: {sum(1 for f in rep['fixes'] if f['applied'])} blocks fixed, "
        f"{sum(len(f['takes']) for f in rep['fixes'])} takes, ${rep['usd']:.3f}, ok={rep['ok']}")
    return words_out, rep


def _row(b):
    return {"lines": b["lines"], "n": b["n"], "wps": b["wps"], "in_band": b["in_band"], "measured": b["measured"]}


def _retake(b, story, words, backend, voice_id, model_id, speed, global_tempo, w, band, vband, cache_dir, work,
            spent_usd, ceiling, max_takes, transcribe_fallback, rep, fx, log, trim=True):
    """Re-voice block b alone; returns (audio array of the chosen take, its timed words) or None."""
    from .stage import _cached_tts, words_for_take
    lines = [ln for ln in story["narration"] if ln["id"] in b["lines"]]
    text = chunk_prompt(lines, model_id)
    script = [x for ln in lines for x in script_words(ln["text"])]
    ctx = _context(story["narration"], b["lines"])
    centre = (band[0] + band[1]) / 2
    # pace the voice would have at speed 1.0, from what was measured (speed and tempo already applied)
    native = w / max(1e-6, (speed or 1.0) * global_tempo)
    fx["method"] = "retake"
    fx["context"] = {k: v for k, v in ctx.items() if v}
    cands = []
    for k in range(max_takes):
        sp = round(min(max(centre / native, vband[0]), vband[1]), 3)
        seed = 1000 + 17 * b["i0"] + k
        chars = len(text)
        cost = _usd(chars)
        if ceiling is not None and spent_usd + rep["usd"] + cost > ceiling + 1e-9:
            fx["takes"].append({"take": k, "skipped": f"cost ceiling ${ceiling:.2f} (spent ${spent_usd + rep['usd']:.3f})"})
            break
        try:
            tk, hit = _cached_tts(backend, cache_dir, text, voice_id, model_id, sp, seed, b["i0"], k, work, context=ctx)
        except BackendError as e:
            fx["takes"].append({"take": k, "speed": sp, "seed": seed, "error": str(e)[:300]})
            break
        if not hit:
            rep["chars"] += chars
            rep["usd"] += cost
        timed, source, cov, stats, dur = words_for_take(tk, script, backend, transcribe_fallback, trim)
        raw = _block_words_wps(timed)
        x = audio.decode_mono(tk.audio)
        x2, timed2, info = fix_span(x, timed, band, 1.0, vband, work, f"rt{b['i0']}_{k}")
        if info["reaches"]:
            x, timed, t, tighten = x2, timed2, info["tempo"], info["tighten_s"]
        else:  # best effort: the in-limit tempo towards the band (the pick below still prefers an in-band take)
            t, _ = _tempo_for(raw, band, 1.0, vband)
            tighten = 0.0
            if abs(t - 1.0) > 1e-4:
                x = _atempo(x, t, work, f"rt{b['i0']}_{k}")
                timed = align.scale(timed, t)
        fin = _block_words_wps(timed)
        row = {"take": k, "seed": seed, "speed": sp, "wps_raw": round(raw, 3), "tempo": t, "tighten_s": tighten,
               "wps": round(fin, 3),
               "in_band": _in(fin, band), "coverage": round(cov, 3), "timing_source": source, "chars": chars,
               "usd": 0.0 if hit else cost, "cache_hit": hit, "audio": tk.audio,
               "context_dropped": bool((tk.meta or {}).get("context_dropped"))}
        fx["takes"].append(row)
        log(f"[voice] pace retake {b['lines'][0]}-{b['lines'][-1]} take {k}: speed {sp} seed {seed} -> "
            f"{raw:.2f} w/s raw, tempo {t} -> {fin:.2f} w/s")
        score = (0 if row["in_band"] else 10 + pacing._clamp(abs(fin - centre), 0, 9)) + abs(fin - centre) \
            + 0.5 * abs(t - 1.0) + 5.0 * (1.0 - cov)
        cands.append((score, row, x, timed))
        if row["in_band"] and cov >= 0.95:
            break
        native = raw / sp   # learn from this take for the next one
    if not cands:
        return None
    score, row, x, timed = min(cands, key=lambda c: c[0])
    orig_dist = band_distance(w, band)
    if not row["in_band"] and band_distance(row["wps"], band) >= orig_dist:
        fx["reason"] = "no take closer to the band than the original"
        return None
    row["picked"] = True
    fx.update(speed=row["speed"], tempo=row["tempo"], tempo_total=row["tempo"], seed=row["seed"])
    return x, timed
