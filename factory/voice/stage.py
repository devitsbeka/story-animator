"""Stage 5a, voice: story.json narration -> narration.mp3 + narration.words.json ([{w,s,e}] seconds).

    synthesize(story_json, out_dir, voice=None, model=None, backend=None, takes="auto")
        -> {"audio", "words", "lines", "report"}

Steps: chunk the narration (one request per chunk, <= max_chars, split at chapters for docuseries)
-> per chunk, 1 or 2 takes (2 only when cheap) from the backend, cached by a hash of the request
-> word timings (character alignment, else transcript, else syllables over speech regions); word ends stop where
   the sound stops (align.trim_ends_to_speech, per take and on the joined stem)
-> pick the take by pacing fit (format band), no clipping, alignment coverage
-> concatenate chunks -> tempo correction if the whole is still outside the band
-> loudness normalisation (two-pass loudnorm to -16 LUFS, TP -1.5 dBTP)
-> reserved narration gaps measured and topped up (gaps.enforce, canon CAN-N2c)
-> pace retake (retake.pace_retake, canon CAN-N4f-pace, lesson L030): every block between gaps brought into the
   per-block band by local tempo, pause tightening or a re-voice of that block alone; gaps re-measured
-> words, lines, report (narration.voice.json: takes, tempo, pace_retake with every attempt and its cost).
"""
import hashlib
import json
import os
import shutil

from . import align, audio, pacing
from .backends import BackendError, ImportBackend, PlaceholderBackend, RestBackend, Take
from .text import chunk_prompt, model_reads_tags, script_words

HERE = os.path.dirname(os.path.abspath(__file__))
VOICES = os.path.join(HERE, "voices.json")
CACHE_VERSION = 1
CHUNK_GAP_S = 0.35
TRIM_DB, TRIM_MIN_S = -45.0, 0.15   # silence that ends a word (align.trim_ends_to_speech)


# ---------------------------------------------------------------- config
def load_voices(path=VOICES):
    with open(path) as fh:
        return json.load(fh)


def resolve_voice(style, fmt, voice=None, voices=None):
    """voice: None (from voices.json), a voice_id string, or a dict with voice_id."""
    voices = voices or load_voices()
    styles = voices.get("styles", {})
    base = (styles.get(style) or {}).get(fmt) or (styles.get("_default") or {}).get(fmt) \
        or (styles.get("_default") or {}).get("short")
    base = dict(base or {})
    if isinstance(voice, dict):
        base.update(voice)
    elif voice:
        if voice != base.get("voice_id"):
            base = {"voice_id": voice, "name": None, "native_wps": None}
    if not base.get("voice_id"):
        raise ValueError(f"no voice for style={style!r} format={fmt!r}")
    base.setdefault("model", voices.get("default_model", "eleven_v4"))
    return base


def _load_story(story_json):
    if isinstance(story_json, dict):
        return story_json, None
    with open(story_json) as fh:
        return json.load(fh), os.path.abspath(story_json)


def chunk_lines(lines, model_id, max_chars=2500, gap_after=()):
    """Group consecutive lines into requests of at most max_chars; a new chapter starts a new chunk, and so does the
    line after a reserved narration gap (canon CAN-N2c: the gap is made by the join, not hoped for from the model)."""
    chunks, cur = [], []
    for ln in lines:
        trial = cur + [ln]
        new_chapter = cur and ln.get("chapter") is not None and ln.get("chapter") != cur[-1].get("chapter")
        after_gap = cur and cur[-1]["id"] in gap_after
        if cur and (new_chapter or after_gap or len(chunk_prompt(trial, model_id)) > max_chars):
            chunks.append(cur)
            cur = [ln]
        else:
            cur = trial
    if cur:
        chunks.append(cur)
    return chunks


# ---------------------------------------------------------------- cache
def cache_key(backend_name, text, voice_id, model_id, speed, seed, context=None):
    d = {"v": CACHE_VERSION, "b": backend_name, "t": text, "voice": voice_id, "model": model_id, "speed": speed,
         "seed": seed}
    if context:  # pace retakes send previous/next text; plain chunk keys stay what they always were
        d["ctx"] = context
    payload = json.dumps(d, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def default_cache_dir():
    return os.environ.get("VOICE_CACHE_DIR", os.path.expanduser("~/.cache/story_animator/voice"))


def _cached_tts(backend, cache_dir, text, voice_id, model_id, speed, seed, chunk, take, work, context=None):
    """context: optional {"previous_text", "next_text"} sent with the request (pace retakes)."""
    ctx = {k: v for k, v in (context or {}).items() if v}
    if not getattr(backend, "cacheable", False) or not cache_dir:
        out = os.path.join(work, f"c{chunk:03d}_t{take}.mp3" if not ctx else f"r{chunk:03d}_t{take}_s{seed}.mp3")
        return backend.tts(text, voice_id, model_id, out, speed=speed, seed=seed, chunk=chunk, take=take, **ctx), False
    key = cache_key(backend.name, text, voice_id, model_id, speed, seed, ctx or None)
    mp3, meta = os.path.join(cache_dir, key + ".mp3"), os.path.join(cache_dir, key + ".json")
    if os.path.exists(mp3) and os.path.exists(meta):
        with open(meta) as fh:
            d = json.load(fh)
        toks = [tuple(t) for t in d["tokens"]] if d.get("tokens") else None
        return Take(mp3, toks, d.get("source"), d.get("meta")), True
    os.makedirs(cache_dir, exist_ok=True)
    tmp = mp3 + ".part.mp3"
    tk = backend.tts(text, voice_id, model_id, tmp, speed=speed, seed=seed, chunk=chunk, take=take, **ctx)
    os.replace(tmp, mp3)
    tk.audio = mp3
    with open(meta + ".part", "w") as fh:
        json.dump({"tokens": tk.tokens, "source": tk.source, "meta": tk.meta, "text": text}, fh)
    os.replace(meta + ".part", meta)
    return tk, False


# ---------------------------------------------------------------- takes
def score_take(wps, fmt, clipped, coverage):
    """Lower is better: pacing distance to the band (per w/s), clipping, unaligned words."""
    return round(10.0 * pacing.band_distance(wps, fmt) + (5.0 if clipped else 0.0)
                 + 5.0 * (1.0 - coverage) + 0.1 * abs(wps - pacing.centre(fmt)), 4)


def n_takes_for(takes, backend, total_chars, chunk):
    if isinstance(backend, ImportBackend):
        return backend.n_takes(chunk) if takes == "auto" else min(int(takes), backend.n_takes(chunk))
    if takes == "auto":
        return 2 if total_chars <= getattr(backend, "cheap_chars", 0) else 1
    return max(1, int(takes))


def words_for_take(tk, words, backend, transcribe_fallback, trim=True):
    """Timed script words of one take. trim: word ends stop where the take's sound stops (L030: character alignment
    lets a final '.' or ',' run through the pause after it), so pacing, gaps and the pace retake measure real speech;
    stats["trimmed"] / stats["trimmed_s"] record it."""
    dur = audio.duration(tk.audio)
    regions = align.speech_regions(audio.silences(tk.audio), dur)
    tokens, source = tk.tokens, tk.source
    if not tokens and transcribe_fallback:
        tokens = backend.transcribe(tk.audio)
        source = "transcript" if tokens else None
    stats = {}
    timed = align.align_to_script(words, tokens, dur, regions, stats)
    if trim:
        timed, stats["trimmed"], stats["trimmed_s"] = align.trim_ends_to_speech(
            timed, audio.silences(tk.audio, TRIM_DB, TRIM_MIN_S) + [(dur, float("inf"))])  # nothing sounds past EOF
    source = source or "proportional_syllables"
    cov = (stats["matched"] + stats["mapped"]) / max(1, stats["words"])
    return timed, source, cov, stats, dur


def voice_usd_of(chars):
    from factory.run.costs import voice_usd
    return voice_usd(chars)


# ---------------------------------------------------------------- main
def synthesize(story_json, out_dir, voice=None, model=None, backend=None, takes="auto", cache_dir=None,
               fmt=None, normalize=True, tempo_fix=True, max_chars=2500, transcribe_fallback=True,
               basename="narration", target_lufs=audio.VOICE_LUFS, target_tp=audio.VOICE_TP, log=None,
               pace_retake=True, trim_word_ends=True, retake_max_lines=None, retake_max_takes=None, retake_ceiling_usd="stage"):
    log = log or (lambda *a: None)
    story, story_path = _load_story(story_json)
    fmt = fmt or story.get("format", "short")
    vc = resolve_voice(story.get("style"), fmt, voice)
    model_id = model or vc.get("model")
    if backend is None:
        backend = RestBackend()
    cache_dir = default_cache_dir() if cache_dir is None else cache_dir
    lines = story["narration"]
    gap_after = {g["after_line"] for g in story.get("narration_gaps") or []}  # canon: one block per run between gaps
    chunks = chunk_lines(lines, model_id, max_chars, gap_after)
    total_chars = sum(len(chunk_prompt(c, model_id)) for c in chunks)
    speed = pacing.speed_for(vc.get("native_wps"), fmt) if getattr(backend, "supports_speed", False) else None
    os.makedirs(out_dir, exist_ok=True)
    work = os.path.join(out_dir, f".{basename}_work")
    os.makedirs(work, exist_ok=True)

    picked, take_log = [], []
    for ci, chunk in enumerate(chunks):
        text = chunk_prompt(chunk, model_id)
        words = [w for ln in chunk for w in script_words(ln["text"])]
        n = n_takes_for(takes, backend, total_chars, ci)
        best = None
        for k in range(n):
            tk, hit = _cached_tts(backend, cache_dir, text, vc["voice_id"], model_id, speed, k + 1, ci, k, work)
            timed, source, cov, stats, dur = words_for_take(tk, words, backend, transcribe_fallback, trim_word_ends)
            clip = audio.clipping(tk.audio)
            w = pacing.wps(timed)
            sc = score_take(w, fmt, clip["clipped_samples"] > 0, cov)
            row = {"chunk": ci, "take": k, "audio": tk.audio, "cache_hit": hit, "duration_s": round(dur, 3),
                   "wps": round(w, 3), "timing_source": source, "alignment": stats, "coverage": round(cov, 3),
                   **clip, "score": sc, "meta": tk.meta}
            take_log.append(row)
            log(f"chunk {ci} take {k}: {w:.2f} w/s, {source}, cov {cov:.2f}, clip {clip['clipped_samples']}, score {sc}")
            if best is None or sc < best[0]:
                best = (sc, tk, timed, row)
        best[3]["picked"] = True
        picked.append(best)

    # concatenate chunks
    raw = os.path.join(work, "raw.wav")
    if len(picked) == 1:
        audio._run([audio.FFMPEG, "-v", "error", "-y", "-i", picked[0][1].audio, "-ac", "1", "-ar", str(audio.SR),
                    "-c:a", "pcm_s16le", raw])
        offsets = [0.0]
    else:
        from .gaps import boundary_pads  # canon: declared gaps get exactly the silence they still need
        pads = boundary_pads(chunks, [p[2] for p in picked], [audio.duration(p[1].audio) for p in picked], story)
        offsets = audio.concat([p[1].audio for p in picked], raw, gap_s=pads)
    words = []
    for off, p in zip(offsets, picked):
        words += align.shift(p[2], off)
    stem_trim = (0, 0.0)
    if trim_word_ends:  # L030: the joined stem shows the silence after each take's last word (the pads follow it)
        words, n_tr, s_tr = align.trim_ends_to_speech(words, audio.silences(raw, TRIM_DB, TRIM_MIN_S))
        stem_trim = (n_tr, s_tr)

    measured = pacing.wps(words)
    tempo = pacing.tempo_correction(measured, fmt) if tempo_fix else 1.0
    out_audio = os.path.join(out_dir, basename + ".mp3")
    if normalize:
        loud = audio.normalize(raw, out_audio, target_lufs, target_tp, tempo=tempo)
    else:
        if abs(tempo - 1.0) > 1e-4:
            audio._run([audio.FFMPEG, "-v", "error", "-y", "-i", raw, "-af", f"atempo={tempo}",
                        "-c:a", "libmp3lame", "-b:a", "128k", out_audio])
        else:
            audio._run([audio.FFMPEG, "-v", "error", "-y", "-i", raw, "-c:a", "libmp3lame", "-b:a", "128k", out_audio])
        loud = audio.loudness(out_audio)
    if abs(tempo - 1.0) > 1e-4:
        words = align.scale(words, tempo)
    final_clip = audio.clipping(out_audio)
    trim = None
    if trim_word_ends:  # L030: a word ends where its sound ends (measured per take, words_for_take)
        al = [p[3]["alignment"] for p in picked]
        trim = {"take_words": sum(a.get("trimmed", 0) for a in al),
                "take_seconds": round(sum(a.get("trimmed_s", 0) for a in al), 3),
                "stem_words": stem_trim[0], "stem_seconds": stem_trim[1], "noise_db": TRIM_DB, "min_silence_s": TRIM_MIN_S}

    words_path = os.path.join(out_dir, basename + ".words.json")
    lines_path = os.path.join(out_dir, basename + ".lines.json")
    report_path = os.path.join(out_dir, basename + ".voice.json")
    gaps_path = os.path.join(out_dir, basename + ".gaps.json")
    with open(words_path, "w") as fh:
        json.dump(words, fh, indent=0)
    gaps_rep = None
    if story.get("narration_gaps"):  # canon CAN-N2c: measure the gaps in the voiced words, top up short ones
        from .gaps import enforce
        gaps_rep = enforce(story, out_audio, words_path, gaps_path, log=log)
        with open(words_path) as fh:
            words = json.load(fh)
    pace_rep = None
    if pace_retake:  # canon CAN-N4f-pace: every block in the per-block band (tempo, else re-voice that block alone)
        from .retake import pace_retake as _pace_retake
        from factory.run.costs import voice_usd
        words, pace_rep = _pace_retake(
            story, out_audio, words, backend, vc["voice_id"], model_id, fmt=fmt, speed=speed, global_tempo=tempo,
            cache_dir=cache_dir, work=os.path.join(work, "pace"), spent_usd=voice_usd(total_chars),
            ceiling_usd=retake_ceiling_usd, max_lines=retake_max_lines, max_takes=retake_max_takes,
            transcribe_fallback=transcribe_fallback, target_lufs=target_lufs, target_tp=target_tp, log=log,
            trim_word_ends=trim_word_ends)
        if any(f.get("applied") for f in pace_rep["fixes"]):
            with open(words_path, "w") as fh:
                json.dump(words, fh, indent=0)
            loud = pace_rep.get("loudness_after") or audio.loudness(out_audio)
            final_clip = audio.clipping(out_audio)
            if story.get("narration_gaps"):  # re-measure: the splice keeps every gap, the report proves it
                from .gaps import enforce
                gaps_rep = enforce(story, out_audio, words_path, gaps_path, log=log)
                with open(words_path) as fh:
                    words = json.load(fh)
    line_rows, i = [], 0
    for ln in lines:
        n = len(script_words(ln["text"]))
        seg = words[i:i + n]
        i += n
        if seg:
            line_rows.append({"id": ln["id"], "t0": seg[0]["s"], "t1": seg[-1]["e"], "words": n,
                              "wps": round(pacing.wps(seg), 3)})
    with open(lines_path, "w") as fh:
        json.dump(line_rows, fh, indent=1)
    final_wps = pacing.wps(words)
    lo, hi = pacing.target(fmt)
    report = {
        "story": story_path or story.get("id"), "format": fmt, "backend": backend.name,
        "voice": {k: vc.get(k) for k in ("voice_id", "name", "native_wps")}, "model_id": model_id,
        "speed_requested": speed, "tags_sent": model_reads_tags(model_id),
        "chunks": len(chunks), "chars": total_chars,
        "takes": take_log, "tempo_correction": tempo,
        "pacing": {"wps": round(final_wps, 3), "target": [lo, hi], "in_band": pacing.in_band(final_wps, fmt),
                   "pre_correction_wps": round(measured, 3)},
        "loudness": {"I": loud["I"], "TP": loud["TP"], "target_I": target_lufs if normalize else None,
                     "target_TP": target_tp if normalize else None},
        "clipping": final_clip,
        "timing_sources": sorted({p[3]["timing_source"] for p in picked}),
        "gaps": None if gaps_rep is None else {"ok": gaps_rep["ok"], "inserts": len(gaps_rep["inserts"])},
        "word_end_trim": trim,
        "pace_retake": pace_rep,
        "usd": {"voice": voice_usd_of(total_chars), "retakes": (pace_rep or {}).get("usd", 0.0)},
        "outputs": {"audio": out_audio, "words": words_path, "lines": lines_path},
    }
    with open(report_path, "w") as fh:
        json.dump(report, fh, indent=1)
    shutil.rmtree(work, ignore_errors=True)
    return {"audio": out_audio, "words": words_path, "lines": lines_path, "report": report_path}


# ---------------------------------------------------------------- MCP route
def mcp_plan(story_json, voice=None, model=None, max_chars=2500, fmt=None):
    """The exact ElevenLabs MCP calls an agent makes for this story (one take per chunk)."""
    story, _ = _load_story(story_json)
    fmt = fmt or story.get("format", "short")
    vc = resolve_voice(story.get("style"), fmt, voice)
    model_id = model or vc.get("model")
    calls = []
    for ci, chunk in enumerate(chunk_lines(story["narration"], model_id, max_chars)):
        calls.append({
            "chunk": ci, "lines": [l["id"] for l in chunk],
            "creative_generate_speech": {"prompt": chunk_prompt(chunk, model_id), "model_id": model_id,
                                         "voice_id": vc["voice_id"], "generations_count": 1},
            "then": ["creative_get_flow_run_status(flow_id, session_ids) until all_completed; "
                     "curl the media[].url to chunk_%03d.mp3" % ci,
                     "creative_add_flow_asset_node(modality=audio, generation_id) -> node_id; "
                     "creative_transcribe_audio(model_id=eleven_scribe_v1, connect_from=[node_id]) (0 credits); "
                     "poll; curl transcripts[].words_download_url to chunk_%03d.words.json" % ci],
        })
    return {"voice": vc, "model_id": model_id, "format": fmt, "target_wps": list(pacing.target(fmt)),
            "calls": calls,
            "import": "python -m factory.voice import --story <story.json> --out <dir> "
                      "--take chunk_000.mp3:chunk_000.words.json [--take ...]"}


def backend_for(name):
    if name == "rest":
        return RestBackend()
    if name == "offline":
        return PlaceholderBackend()
    raise BackendError(f"unknown backend {name}")
