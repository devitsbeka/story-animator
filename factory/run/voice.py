"""Stage 5a voice: story.json narration -> audio/narration.* + audio/narration.words.json ([{w, s, e}] seconds).

Order of preference:
  1. factory.voice.synthesize(story_json, out_dir) -> {"audio": path, "words": path}  (built by the voice workstream;
     ElevenLabs behind ELEVENLABS_API_KEY). Never called with --offline (no spend in tests).
  2. offline + a reference narration in the repo for the same story id (episodes/<story.id>/audio/narration.mp3 +
     narration.words.json, e.g. Sentinel) -> copied, so the offline chain uses the real recorded VO.
  3. stub: a speech-like placeholder WAV (band-limited noise bursts per word) with word timings laid out inside each
     narration line's [t0, t1] proportionally to word length. Loud enough for the mixer's EBU R128 maths.
"""
import importlib
import json
import math
import os
import re
import shutil
import wave

import numpy as np

from factory.director.paths import ROOT

SR = 48000


def _words(text):
    return [w for w in re.sub(r"\[[^\]]*\]", " ", text).split() if re.search(r"\w", w)]


def stub_timings(story):
    out = []
    lines = story.get("narration") or []
    t = 0.0
    for ln in lines:
        ws = _words(ln.get("text", ""))
        if not ws:
            continue
        t0 = float(ln.get("t0", t))
        t1 = float(ln.get("t1", t0 + len(ws) / 2.9))
        if t1 <= t0:
            t1 = t0 + len(ws) / 2.9
        weights = [max(1, len(re.sub(r"\W", "", w))) + 1.5 for w in ws]
        span, tot, c = t1 - t0, sum(weights), t0
        for w, wt in zip(ws, weights):
            d = span * wt / tot
            out.append({"w": w, "s": round(c, 3), "e": round(c + d * 0.88, 3)})
            c += d
        t = t1
    return out


def write_stub_wav(words, path, seed=11):
    total = (words[-1]["e"] if words else 1.0) + 0.6
    n = int(total * SR)
    rng = np.random.default_rng(seed)
    sig = np.zeros(n, dtype=np.float32)
    for w in words:
        a, b = int(w["s"] * SR), min(n, int(w["e"] * SR))
        if b <= a:
            continue
        m = b - a
        noise = rng.standard_normal(m).astype(np.float32)
        # crude "voice": box-filtered (low-passed) noise + a pitched component, Hann envelope
        lp = np.convolve(noise, np.ones(16, dtype=np.float32) / 16, mode="same")
        tt = np.arange(m) / SR
        tone = 0.5 * np.sin(2 * math.pi * 140 * tt) + 0.25 * np.sin(2 * math.pi * 280 * tt)
        env = np.hanning(m).astype(np.float32)
        sig[a:b] += (0.6 * lp * 4 + 0.4 * tone) * env * 0.35
    sig = np.clip(sig, -0.95, 0.95)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes((sig * 32767).astype("<i2").tobytes())
    return path


def _load_voice_module():
    try:
        return importlib.import_module("factory.voice")
    except ImportError:
        return None


def synthesize(story_path, ep_dir, offline=False, mode="auto", log=print):
    """-> {"audio", "words", "provider", "chars", "usd"}. mode: auto | stub | module."""
    story = json.load(open(story_path, encoding="utf-8"))
    audio_dir = os.path.join(ep_dir, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    chars = sum(len(re.sub(r"\[[^\]]*\]", "", ln.get("text", ""))) for ln in story.get("narration") or [])
    mod = None if (offline or mode == "stub") else _load_voice_module()
    if mode == "module" and mod is None and not offline:
        raise RuntimeError("--voice module requested but factory.voice is not importable")
    if mod is not None and hasattr(mod, "synthesize"):
        try:
            res = mod.synthesize(story_path, audio_dir)
        except (TypeError, AttributeError, KeyError):
            res = mod.synthesize(story, audio_dir)   # implementations that take the parsed story dict
        from . import costs
        return {"audio": os.path.abspath(res["audio"]), "words": os.path.abspath(res["words"]), "provider": "factory.voice",
                "chars": chars, "usd": costs.voice_usd(chars)}
    if mode == "auto" and mod is None and not offline:
        log("[voice] factory.voice not available: using the stub narration")
    ref = os.path.join(ROOT, "episodes", str(story.get("id", "")), "audio")
    if offline and mode != "stub" and os.path.isfile(os.path.join(ref, "narration.mp3")) \
            and os.path.isfile(os.path.join(ref, "narration.words.json")):
        a, w = os.path.join(audio_dir, "narration.mp3"), os.path.join(audio_dir, "narration.words.json")
        if os.path.abspath(ref) != os.path.abspath(audio_dir):
            shutil.copy2(os.path.join(ref, "narration.mp3"), a)
            shutil.copy2(os.path.join(ref, "narration.words.json"), w)
        return {"audio": os.path.abspath(a), "words": os.path.abspath(w), "provider": f"reference:episodes/{story['id']}",
                "chars": chars, "usd": 0.0}
    words = stub_timings(story)
    a = write_stub_wav(words, os.path.join(audio_dir, "narration.wav"))
    w = os.path.join(audio_dir, "narration.words.json")
    with open(w, "w") as fh:
        json.dump(words, fh)
    return {"audio": os.path.abspath(a), "words": os.path.abspath(w), "provider": "stub", "chars": chars, "usd": 0.0}
