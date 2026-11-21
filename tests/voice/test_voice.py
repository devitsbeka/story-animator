"""Voice stage tests (factory/voice).  No network, no credits: REST is exercised with a fake session,
the MCP route with the real 1-line take generated for this stage (tests/voice/fixtures/mcp_take)."""
import base64
import copy
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from factory.voice import align, audio, pacing, stage, text  # noqa: E402
from factory.voice.backends import (BackendError, ImportBackend, PlaceholderBackend,  # noqa: E402
                                    RestBackend, Take)

FX = os.path.join(os.path.dirname(__file__), "fixtures")
MCP = os.path.join(FX, "mcp_take")
SENTINEL_STORY = os.path.join(ROOT, "factory", "director", "fixtures", "sentinel", "develop.1.json")
SENTINEL_WORDS = os.path.join(ROOT, "episodes", "sentinel", "audio", "narration.words.json")


def tiny_story(fmt="short", lines=None):
    return {"id": "tiny", "format": fmt, "style": "pixar_night_survival", "narration": lines or [
        {"id": "L01", "beat": "B1", "tag": "excited", "text": "Your engine just DIED.", "t0": 0, "t1": 1.5},
        {"id": "L02", "beat": "B2", "tag": "whispers", "text": "No lights. [pause] No power.", "t0": 1.6, "t1": 3},
        {"id": "L03", "beat": "B3", "tag": "dramatic", "text": "So what do you do now?", "t0": 3.1, "t1": 5},
    ]}


# ------------------------------------------------------------------ text
def test_line_prompt_tags_by_model():
    ln = {"tag": "whispers", "text": "Don't [gasps] move."}
    assert text.line_prompt(ln, "eleven_v4") == "[whispers] Don't [gasps] move."
    assert text.line_prompt(ln, "eleven_multilingual_v2") == "Don't move."
    assert text.script_words("You're alone... [sighs] on a yacht, ... - in the night.") == \
        ["You're", "alone...", "on", "a", "yacht,", "in", "the", "night."]


def test_syllables():
    assert [text.syllables(w) for w in ["the", "engine", "island", "dragging", "died.", "beautiful", "112"]] \
        == [1, 2, 2, 2, 1, 3, 4]


def test_chunking_respects_limit_and_chapters():
    lines = [{"id": f"L{i:02d}", "tag": "calm", "text": "word " * 30, "chapter": "C1" if i < 6 else "C2"}
             for i in range(10)]
    chunks = stage.chunk_lines(lines, "eleven_v4", max_chars=400)
    assert all(len(text.chunk_prompt(c, "eleven_v4")) <= 400 for c in chunks)
    assert [l["id"] for c in chunks for l in c] == [l["id"] for l in lines]
    assert all(len({l["chapter"] for l in c}) == 1 for c in chunks)


# ------------------------------------------------------------------ alignment
def char_alignment(prompt, t0=0.1, cps=14.0):
    chars = list(prompt)
    st = [t0 + i / cps for i in range(len(chars))]
    return {"characters": chars, "character_start_times_seconds": st,
            "character_end_times_seconds": [s + 1 / cps for s in st]}


def test_char_alignment_drops_tags_and_splits_words():
    al = char_alignment("[excited] Your engine\n\n[whispers] died.")
    toks = align.tokens_from_char_alignment(al)
    assert [t[0] for t in toks] == ["Your", "engine", "died."]
    assert all(e > s for _, s, e in toks)
    assert toks[0][1] == pytest.approx(0.1 + 10 / 14.0)


def test_transcript_alignment_handles_tags_misspellings_and_drops():
    words = ["Your", "engine", "just", "DIED...", "so", "what", "do", "you", "do", "now?"]
    with open(os.path.join(MCP, "scribe_words.json")) as fh:
        tr = json.load(fh)
    toks = align.tokens_from_transcript(tr)
    assert toks[0][0] == "Your"  # the "[excited]" token Scribe echoed is dropped
    # misspell one word and drop another from the transcript
    toks2 = [list(t) for t in toks]
    toks2[1][0] = "enjin"
    del toks2[5]  # "what"
    stats = {}
    out = align.align_to_script(words, [tuple(t) for t in toks2], 3.47, None, stats)
    assert [x["w"] for x in out] == words
    assert out[1]["s"] == pytest.approx(0.4, abs=0.01)           # 1:1 mapped despite spelling
    assert out[4]["e"] <= out[5]["s"] <= out[6]["s"]                # interpolated between anchors
    assert stats["interpolated"] == 1 and stats["matched"] + stats["mapped"] == 9
    assert all(out[k]["s"] >= out[k - 1]["s"] for k in range(1, len(out)))


def test_proportional_stays_in_speech_regions():
    words = ["one", "two", "three", "four", "five", "six"]
    regions = [(0.2, 1.2), (2.0, 3.0)]
    out = align.proportional(words, 3.2, regions)
    for x in out:
        assert any(a - 0.011 <= x["s"] and x["e"] <= b + 0.011 for a, b in regions), x
    assert out[0]["s"] == pytest.approx(0.2) and out[-1]["e"] == pytest.approx(3.0)
    assert align.speech_regions([(0.0, 0.2), (1.2, 2.0), (3.0, float("nan"))], 3.2) == regions


# ------------------------------------------------------------------ pacing
def test_pacing_targets_speed_and_tempo():
    assert pacing.target("short") == (2.8, 3.1) and pacing.target("docuseries") == (2.4, 2.7)
    assert pacing.speed_for(None, "short") is None
    assert pacing.speed_for(2.86, "short") == pytest.approx(2.95 / 2.86, abs=1e-3)
    assert pacing.speed_for(4.0, "docuseries") == 0.85          # clamped
    assert pacing.tempo_correction(2.9, "short") == 1.0
    assert pacing.tempo_correction(3.3, "short") == pytest.approx(3.08 / 3.3, abs=1e-3)
    assert pacing.tempo_correction(1.5, "short") == 1.08         # clamped
    w = [{"w": "a", "s": 0.0, "e": 0.5}, {"w": "b", "s": 0.5, "e": 1.0}]
    assert pacing.wps(w) == 2.0


def test_voices_json_resolution():
    v = stage.resolve_voice("pixar_night_survival", "short")
    assert v["voice_id"] == "467tX2b9Bky3cD6jXpNa" and v["native_wps"] == 2.86
    d = stage.resolve_voice("unknown_style", "docuseries")
    assert d["voice_id"] == "VMCgCMbBs53ElBxVD4VB"
    o = stage.resolve_voice("pixar_night_survival", "short", voice="abc123")
    assert o["voice_id"] == "abc123" and o["native_wps"] is None


# ------------------------------------------------------------------ fake REST
class FakeResp:
    def __init__(self, code, payload=None, text_body=""):
        self.status_code = code
        self._p = payload
        self.text = text_body or (json.dumps(payload) if payload is not None else "")
        self.headers = {"request-id": "req-test"}

    def json(self):
        return self._p


class FakeSession:
    """Plays ElevenLabs: TTS with timestamps (real mp3 bytes from the placeholder synth + char alignment
    derived from the placeholder's exact word times), and Scribe."""

    def __init__(self, tmp, refuse_models=(), no_alignment=False, peaks=None):
        self.tmp = tmp
        self.calls = []
        self.refuse = set(refuse_models)
        self.no_alignment = no_alignment
        self.peaks = peaks or {}
        self.last_tokens = None

    def post(self, url, headers=None, data=None, files=None, timeout=None):
        assert headers["xi-api-key"] == "test-key"
        if url.endswith("/v1/speech-to-text"):
            self.calls.append(("stt", url, data))
            return FakeResp(200, {"words": [{"text": "[excited]", "type": "word", "start": 0, "end": 0.1}] +
                                  [{"text": t, "type": "word", "start": s, "end": e}
                                   for t, s, e in self.last_tokens]})
        body = json.loads(data)
        self.calls.append(("tts", url, body))
        if body["model_id"] in self.refuse:
            return FakeResp(400, text_body='{"detail":{"status":"model_not_found","message":"Model not found"}}')
        seed = body.get("seed", 1)
        ph = PlaceholderBackend(peak=self.peaks.get(seed, 0.5))
        p = os.path.join(self.tmp, f"fake_{len(self.calls)}.mp3")
        tk = ph.tts(body["text"], "v", body["model_id"], p, speed=body.get("voice_settings", {}).get("speed"), seed=seed)
        self.last_tokens = tk.tokens
        chars, st, en = [], [], []
        prev_end = 0.0
        for w, s, e in tk.tokens:
            if chars:
                chars.append(" "); st.append(prev_end); en.append(s)
            for i, c in enumerate(w):
                chars.append(c); st.append(s + (e - s) * i / len(w)); en.append(s + (e - s) * (i + 1) / len(w))
            prev_end = e
        with open(p, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
        payload = {"audio_base64": b64}
        if not self.no_alignment:
            payload["alignment"] = {"characters": chars, "character_start_times_seconds": st,
                                    "character_end_times_seconds": en}
        return FakeResp(200, payload)


def rest(tmp, **kw):
    return RestBackend(api_key="test-key", session=FakeSession(str(tmp), **kw))


def test_rest_requires_key(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(BackendError):
        RestBackend()


def test_rest_model_fallback_and_request(tmp_path):
    be = rest(tmp_path, refuse_models={"eleven_v4"})
    tk = be.tts("[excited] Your engine just DIED.", "VOICE", "eleven_v4", str(tmp_path / "a.mp3"), speed=1.03, seed=1)
    kinds = [(c[2]["model_id"]) for c in be.s.calls]
    assert kinds == ["eleven_v4", "eleven_v3"]
    url, body = be.s.calls[-1][1], be.s.calls[-1][2]
    assert "/v1/text-to-speech/VOICE/with-timestamps?output_format=mp3_44100_128" in url
    assert body["voice_settings"] == {"speed": 1.03} and body["seed"] == 1
    assert tk.source == "char_alignment" and tk.meta["model_id"] == "eleven_v3"
    assert [t[0] for t in tk.tokens] == ["Your", "engine", "just", "DIED."]


def test_synthesize_rest_two_takes_cache_and_outputs(tmp_path):
    be = rest(tmp_path)
    cache = tmp_path / "cache"
    res = stage.synthesize(tiny_story(), str(tmp_path / "out"), backend=be, cache_dir=str(cache))
    tts_calls = [c for c in be.s.calls if c[0] == "tts"]
    assert len(tts_calls) == 2                              # cheap -> 2 takes (seeds 1, 2)
    assert {c[2]["seed"] for c in tts_calls} == {1, 2}
    assert tts_calls[0][2]["text"].startswith("[excited] Your engine just DIED.\n\n[whispers] No lights.")
    with open(res["words"]) as fh:
        words = json.load(fh)
    assert [w["w"] for w in words] == ["Your", "engine", "just", "DIED.", "No", "lights.", "No", "power.",
                                       "So", "what", "do", "you", "do", "now?"]
    with open(SENTINEL_WORDS) as fh:
        ref = json.load(fh)
    assert all(set(w) == set(ref[0]) for w in words)        # same {w,s,e} format as Sentinel
    assert all(isinstance(w["s"], float) and w["e"] >= w["s"] for w in words)
    with open(res["report"]) as fh:
        rep = json.load(fh)
    assert rep["timing_sources"] == ["char_alignment"]
    assert sum(1 for t in rep["takes"] if t.get("picked")) == 1
    assert abs(rep["loudness"]["I"] - audio.VOICE_LUFS) <= 1.0 and rep["loudness"]["TP"] <= -1.0
    assert rep["pacing"]["in_band"]
    with open(res["lines"]) as fh:
        lines = json.load(fh)
    assert [l["id"] for l in lines] == ["L01", "L02", "L03"] and lines[0]["t1"] <= lines[1]["t0"]
    assert abs(audio.duration(res["audio"]) - words[-1]["e"]) < 0.6
    # second run: all from cache, no new requests
    n = len(be.s.calls)
    stage.synthesize(tiny_story(), str(tmp_path / "out2"), backend=be, cache_dir=str(cache))
    assert len(be.s.calls) == n
    # a text change misses the cache for that request only
    st = tiny_story()
    st["narration"][2]["text"] = "So what now?"
    stage.synthesize(st, str(tmp_path / "out3"), backend=be, cache_dir=str(cache), takes=1)
    assert len(be.s.calls) == n + 1


def test_one_take_when_not_cheap(tmp_path):
    be = rest(tmp_path)
    be.cheap_chars = 10
    stage.synthesize(tiny_story(), str(tmp_path / "out"), backend=be, cache_dir="")
    assert len([c for c in be.s.calls if c[0] == "tts"]) == 1


def test_take_selection_rejects_clipping(tmp_path):
    be = rest(tmp_path, peaks={1: 1.6, 2: 0.5})              # take with seed 1 clips
    res = stage.synthesize(tiny_story(), str(tmp_path / "out"), backend=be, cache_dir="", normalize=False)
    with open(res["report"]) as fh:
        rep = json.load(fh)
    t0, t1 = rep["takes"]
    assert t0["clipped_samples"] > 0 and t1["clipped_samples"] == 0
    assert t1.get("picked") and not t0.get("picked")


def test_transcription_fallback_when_no_timestamps(tmp_path):
    be = rest(tmp_path, no_alignment=True)
    res = stage.synthesize(tiny_story(), str(tmp_path / "out"), backend=be, cache_dir="", takes=1)
    assert any(c[0] == "stt" for c in be.s.calls)
    with open(res["report"]) as fh:
        rep = json.load(fh)
    assert rep["timing_sources"] == ["transcript"] and rep["takes"][0]["coverage"] == 1.0


def test_syllable_fallback_is_close_to_truth(tmp_path):
    story = tiny_story()
    truth = PlaceholderBackend(emit_tokens=True)
    blind = PlaceholderBackend(emit_tokens=False)
    a = stage.synthesize(story, str(tmp_path / "a"), backend=truth, cache_dir="", takes=1, tempo_fix=False)
    b = stage.synthesize(story, str(tmp_path / "b"), backend=blind, cache_dir="", takes=1, tempo_fix=False)
    with open(a["words"]) as fh:
        wa = json.load(fh)
    with open(b["words"]) as fh:
        wb = json.load(fh)
    with open(b["report"]) as fh:
        assert json.load(fh)["timing_sources"] == ["proportional_syllables"]
    err = sum(abs(x["s"] - y["s"]) for x, y in zip(wa, wb)) / len(wa)
    assert err < 0.15, err


def test_tempo_correction_rescales_words(tmp_path):
    fast = PlaceholderBackend(wps=4.5)
    res = stage.synthesize(tiny_story(), str(tmp_path / "o"), backend=fast, cache_dir="", takes=1)
    with open(res["report"]) as fh:
        rep = json.load(fh)
    assert rep["tempo_correction"] == pacing.TEMPO_RANGE[0]
    assert rep["pacing"]["wps"] < rep["pacing"]["pre_correction_wps"]
    with open(res["words"]) as fh:
        words = json.load(fh)
    # the stretched timings still land on the stretched audio: the final silence starts at the last word end
    last_sil = audio.silences(res["audio"])[-1][0]
    assert abs(last_sil - words[-1]["e"]) < 0.08


def test_docuseries_multi_chunk_concat(tmp_path):
    lines = [{"id": f"L{i:02d}", "beat": "B1", "tag": "calm", "chapter": f"C{i // 2}",
              "text": "The island waited in the dark for a long time.", "t0": 0, "t1": 1} for i in range(4)]
    story = tiny_story("docuseries", lines)
    res = stage.synthesize(story, str(tmp_path / "o"), backend=PlaceholderBackend(wps=2.5), cache_dir="", takes=1)
    with open(res["report"]) as fh:
        rep = json.load(fh)
    assert rep["chunks"] == 2 and rep["voice"]["voice_id"] == "VMCgCMbBs53ElBxVD4VB"
    assert rep["pacing"]["target"] == [2.4, 2.7]
    with open(res["words"]) as fh:
        words = json.load(fh)
    assert len(words) == 40
    assert words[20]["s"] > words[19]["e"] + stage.CHUNK_GAP_S - 0.05   # second chunk placed after the gap
    assert abs(audio.duration(res["audio"]) - words[-1]["e"]) < 0.6


# ------------------------------------------------------------------ MCP route (real take)
def test_mcp_plan_for_sentinel():
    plan = stage.mcp_plan(SENTINEL_STORY)
    call = plan["calls"][0]["creative_generate_speech"]
    assert call["voice_id"] == "467tX2b9Bky3cD6jXpNa" and call["model_id"] == "eleven_v4"
    assert call["generations_count"] == 1 and call["prompt"].startswith("[excited] You're alone")
    assert len(plan["calls"]) == 1


def test_mcp_import_real_take(tmp_path):
    be = ImportBackend([[{"audio": os.path.join(MCP, "take.mp3"),
                          "transcript": os.path.join(MCP, "scribe_words.json"),
                          "meta": {"generation_id": "nFTsLYpIkjuBsuZYCiTD"}}]])
    res = stage.synthesize(os.path.join(MCP, "story.json"), str(tmp_path), backend=be)
    with open(res["words"]) as fh:
        words = json.load(fh)
    assert [w["w"] for w in words] == ["Your", "engine", "just", "DIED...", "so", "what", "do", "you", "do", "now?"]
    with open(res["report"]) as fh:
        rep = json.load(fh)
    assert rep["timing_sources"] == ["transcript"] and rep["takes"][0]["coverage"] == 1.0
    assert rep["clipping"]["clipped_samples"] == 0
    assert abs(rep["loudness"]["I"] - audio.VOICE_LUFS) <= 1.0 and rep["loudness"]["TP"] <= -1.0
    assert rep["pacing"]["in_band"]
    # the long "DIED..." hold lands on the real pause: the next word starts after the detected silence
    sil = audio.silences(res["audio"])
    assert any(abs(a - words[3]["e"]) < 0.25 for a, _ in sil)


def test_mcp_import_without_transcript_uses_syllables(tmp_path):
    be = ImportBackend([[{"audio": os.path.join(MCP, "take.mp3")}]])
    res = stage.synthesize(os.path.join(MCP, "story.json"), str(tmp_path), backend=be, tempo_fix=False)
    with open(res["words"]) as fh:
        words = json.load(fh)
    with open(os.path.join(MCP, "scribe_words.json")) as fh:
        truth = align.tokens_from_transcript(json.load(fh))
    err = sum(abs(w["s"] - t[1]) for w, t in zip(words, truth)) / len(words)
    assert len(words) == 10 and err < 0.3, err
