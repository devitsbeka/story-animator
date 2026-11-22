"""TTS backends.  Each one turns a prompt into an audio file plus (optionally) timed tokens.

- RestBackend:        direct ElevenLabs REST for headless factory runs (env ELEVENLABS_API_KEY).
                      POST /v1/text-to-speech/{voice}/with-timestamps -> mp3 + character alignment;
                      POST /v1/speech-to-text (Scribe) is the transcription fallback.
- ImportBackend:      takes produced by an agent through the ElevenLabs MCP tools
                      (creative_generate_speech -> download; creative_transcribe_audio -> words.json).
                      ``python -m factory.voice plan`` prints the exact MCP calls.
- PlaceholderBackend: offline stand-in (tone bursts at a given pace, exact timings) so later stages
                      and tests run without credits.
"""
import base64
import json
import os
import subprocess

import numpy as np

from . import align
from .audio import SR, FFMPEG

API = os.environ.get("ELEVENLABS_API_BASE", "https://api.elevenlabs.io")
# if a model id is refused over REST, try these in order (MCP-only models may lag on REST)
MODEL_FALLBACKS = {"eleven_v4": ["eleven_v3"], "eleven_v3": ["eleven_multilingual_v2"]}


class Take:
    def __init__(self, audio, tokens=None, source=None, meta=None):
        self.audio = audio            # path to the audio file
        self.tokens = tokens          # [(token, s, e)] or None
        self.source = source          # "char_alignment" | "transcript" | "placeholder" | None
        self.meta = meta or {}

    def to_json(self):
        return {"audio": self.audio, "tokens": self.tokens, "source": self.source, "meta": self.meta}


class BackendError(RuntimeError):
    pass


class RestBackend:
    name = "elevenlabs_rest"
    cacheable = True
    supports_speed = True
    cheap_chars = 600   # two takes are generated only for narrations up to this many characters

    def __init__(self, api_key=None, base=API, session=None, output_format="mp3_44100_128", timeout=300):
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not self.api_key:
            raise BackendError("ELEVENLABS_API_KEY is not set (or use the MCP import route / --offline)")
        self.base = base.rstrip("/")
        self.output_format = output_format
        self.timeout = timeout
        if session is None:
            import requests
            session = requests.Session()
        self.s = session

    def _headers(self, json_body=True):
        h = {"xi-api-key": self.api_key, "Accept": "application/json"}
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def tts(self, text, voice_id, model_id, out_path, speed=None, seed=None, previous_text=None, next_text=None, **_):
        """previous_text / next_text: the neighbouring narration (not voiced, not billed) so a single re-voiced line
        keeps the prosody of its context (pace retake). A model that refuses the context gets the request without it
        (recorded as meta.context_dropped)."""
        body = {"text": text, "model_id": model_id}
        if speed and abs(speed - 1.0) > 1e-3:
            body["voice_settings"] = {"speed": speed}
        if seed is not None:
            body["seed"] = int(seed)
        if previous_text:
            body["previous_text"] = previous_text
        if next_text:
            body["next_text"] = next_text
        tried, context_dropped = [], False
        mids = [model_id] + MODEL_FALLBACKS.get(model_id, [])
        while mids:
            mid = mids[0]
            body["model_id"] = mid
            if mid not in tried:
                tried.append(mid)
            url = f"{self.base}/v1/text-to-speech/{voice_id}/with-timestamps?output_format={self.output_format}"
            r = self.s.post(url, headers=self._headers(), data=json.dumps(body), timeout=self.timeout)
            if r.status_code in (400, 422) and _context_refused(r) and ("previous_text" in body or "next_text" in body):
                body.pop("previous_text", None)
                body.pop("next_text", None)
                context_dropped = True
                continue
            mids.pop(0)
            if r.status_code == 200:
                d = r.json()
                os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
                with open(out_path, "wb") as fh:
                    fh.write(base64.b64decode(d["audio_base64"]))
                al = d.get("alignment") or d.get("normalized_alignment")
                toks = align.tokens_from_char_alignment(al) if al else None
                return Take(out_path, toks or None, "char_alignment" if toks else None,
                            {"model_id": mid, "voice_id": voice_id, "speed": speed, "seed": seed,
                             "request_id": r.headers.get("request-id"),
                             **({"context": bool(previous_text or next_text), "context_dropped": context_dropped}
                                if (previous_text or next_text) else {})})
            if r.status_code in (400, 404, 422) and _model_refused(r):
                continue
            raise BackendError(f"ElevenLabs TTS {r.status_code}: {r.text[:300]}")
        raise BackendError(f"ElevenLabs refused models {tried}")

    def transcribe(self, path):
        with open(path, "rb") as fh:
            r = self.s.post(f"{self.base}/v1/speech-to-text", headers=self._headers(json_body=False),
                            data={"model_id": "scribe_v1", "timestamps_granularity": "word", "tag_audio_events": "false"},
                            files={"file": (os.path.basename(path), fh, "audio/mpeg")}, timeout=self.timeout)
        if r.status_code != 200:
            return None
        return align.tokens_from_transcript(r.json()) or None


def _context_refused(r):
    t = (r.text or "").lower()
    return any(k in t for k in ("previous_text", "next_text", "request stitching", "previous_request_ids"))


def _model_refused(r):
    t = (r.text or "").lower()
    return "model" in t and any(k in t for k in ("not found", "invalid", "not supported", "does not exist", "unknown"))


class ImportBackend:
    """Takes generated through the ElevenLabs MCP tools.  ``chunks`` is a list (one per text chunk) of
    lists of takes: {"audio": path, "transcript": path-or-None, "meta": {...}}.  The transcript is the
    Scribe words.json (creative_transcribe_audio ``words_download_url``) or any [{text,start,end}] list."""
    name = "elevenlabs_mcp_import"
    cacheable = False
    supports_speed = False
    cheap_chars = 0

    def __init__(self, chunks):
        self.chunks = chunks

    def n_takes(self, chunk):
        return len(self.chunks[chunk])

    def tts(self, text, voice_id, model_id, out_path, chunk=0, take=0, **_):
        if chunk >= len(self.chunks) or take >= len(self.chunks[chunk]):
            raise BackendError(f"no imported take for chunk {chunk} take {take}")
        t = self.chunks[chunk][take]
        toks, src = None, None
        if t.get("transcript"):
            with open(t["transcript"]) as fh:
                toks = align.tokens_from_transcript(json.load(fh)) or None
            src = "transcript" if toks else None
        meta = dict(t.get("meta") or {})
        meta.setdefault("voice_id", voice_id)
        meta.setdefault("model_id", model_id)
        return Take(os.path.abspath(t["audio"]), toks, src, meta)

    def transcribe(self, path):
        return None


class PlaceholderBackend:
    """Offline: a soft tone burst per word at `wps` (syllable-weighted), with a pause after
    sentence punctuation.  Timings are exact, so it exercises everything downstream for free."""
    name = "placeholder"
    cacheable = True
    supports_speed = True
    cheap_chars = 10 ** 6

    def __init__(self, wps=2.95, peak=0.5, emit_tokens=True, line_wps=None, seed_spread=0.03, stop_pause=0.25):
        """line_wps: {text fragment: native w/s} overrides the pace of any request containing the fragment (tests:
        one slow or rushed line). seed_spread: pace change per seed step (seeds cycle 1, 2, 3)."""
        self.wps = wps
        self.peak = peak
        self.emit_tokens = emit_tokens
        self.line_wps = dict(line_wps or {})
        self.seed_spread = seed_spread
        self.stop_pause = stop_pause    # silence after . ! ? (tests: a long internal pause)
        self.calls = []

    def native_wps(self, text):
        for frag, v in self.line_wps.items():
            if frag in text:
                return v
        return self.wps

    def tts(self, text, voice_id, model_id, out_path, speed=None, seed=None, previous_text=None, next_text=None, **_):
        from .text import script_words, syllables
        words = script_words(text)
        self.calls.append({"text": text, "speed": speed, "seed": seed, "previous_text": previous_text,
                           "next_text": next_text})
        rate = self.native_wps(text) * (speed or 1.0) * (1.0 + self.seed_spread * (((seed or 1) - 1) % 3))
        mean_syl = np.mean([syllables(w) for w in words]) if words else 1.0
        t, toks, segs = 0.15, [], []
        for w in words:
            d = syllables(w) / mean_syl / rate * 0.85
            toks.append((w, t, t + d))
            segs.append((t, t + d))
            t += d + (0.06 / rate * 3)
            if w[-1:] in ".!?":
                t += self.stop_pause
            elif w[-1:] in ",;:" or w.endswith("..."):
                t += 0.12
        total = t + 0.2
        n = int(total * SR)
        x = np.zeros(n, np.float32)
        for k, (a, b) in enumerate(segs):
            i0, i1 = int(a * SR), int(b * SR)
            tt = np.arange(i1 - i0) / SR
            env = np.sin(np.pi * np.clip(tt / max(b - a, 1e-3), 0, 1)) ** 0.5
            x[i0:i1] = self.peak * env * np.sin(2 * np.pi * (180 + 20 * (k % 5)) * tt)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        p = subprocess.run(
            [FFMPEG, "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
             "-c:a", "libmp3lame", "-b:a", "128k", out_path], input=x.tobytes(), capture_output=True)
        if p.returncode != 0:
            raise BackendError(p.stderr.decode()[-500:])
        return Take(out_path, toks if self.emit_tokens else None, "placeholder" if self.emit_tokens else None,
                    {"voice_id": voice_id, "model_id": model_id, "speed": speed, "seed": seed,
                     **({"context": True} if (previous_text or next_text) else {})})

    def transcribe(self, path):
        return None
