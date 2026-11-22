"""Pace retake (factory/voice/retake.py, canon CAN-N4f-pace, lesson L030). Offline: the placeholder TTS with per-line
native pace stands in for ElevenLabs (no network, no credits).

Scenarios reproduce the waterspout v2 defect class: one block slow by a little (tempo alone fixes it), one block
rushed far past the band (only a re-voice fixes it), several bad blocks (the cap), a tiny cost ceiling, and blocks
both slow and rushed in one run, always with reserved narration gaps around them."""
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from factory.canon import checks as canon  # noqa: E402
from factory.voice import audio, gaps, pacing, retake, stage  # noqa: E402
from factory.voice.backends import ImportBackend, PlaceholderBackend  # noqa: E402

TEXTS = ["The storm builds slowly over the dark water.", "You sail alone tonight, far south of Bermuda.",
         "Your radio is dead and nobody hears you.", "But your heading now puts you in its path.",
         "Salt stings your eyes and only seconds remain."]
SLOW, RUSHED = "south of Bermuda", "puts you in"


def story(n=4, gap_len=0.8):
    lines = [{"id": f"L{i + 1:02d}", "tag": "tense", "text": t} for i, t in enumerate(TEXTS[:n])]
    gp = [{"id": f"G{i + 1:02d}", "after_line": f"L{i + 1:02d}", "len_s": gap_len, "purpose": "key_sfx",
           "filled_by": "room_tone"} for i in range(n - 1)]
    return {"id": "pace", "format": "short", "style": "pixar_night_survival", "narration": lines, "narration_gaps": gp}


def run(tmp_path, line_wps, s=None, **kw):
    out = tmp_path / "o"
    be = PlaceholderBackend(wps=2.8, line_wps=line_wps)  # the in-band blocks sit mid-band (~3.1 w/s after speed + tempo)
    res = stage.synthesize(s or story(), str(out), backend=be, cache_dir="", **kw)
    with open(res["report"]) as fh:
        rep = json.load(fh)
    with open(res["words"]) as fh:
        words = json.load(fh)
    return res, rep, words, be


def canon_pace(s, words, voice):
    c = canon.Ctx(story=s, words=words, voice=voice)
    c.line_words()
    R = canon.Results()
    canon.check_N_audio(c, R)
    return R.r["CAN-N4f-pace"]


def fix_for(rep, line):
    return next(f for f in rep["pace_retake"]["fixes"] if line in f["lines"])


# ------------------------------------------------------------------ measurement is the canon's
def test_block_pace_matches_canon_blocks():
    s = story()
    words = [{"w": w, "s": i * 0.4, "e": i * 0.4 + 0.3} for i, w in
             enumerate(x for ln in s["narration"] for x in ln["text"].split())]
    rows = pacing.block_pace(s["narration"], s["narration_gaps"], words)
    assert [r["lines"] for r in rows] == [["L01"], ["L02"], ["L03"], ["L04"]]
    assert all(r["measured"] for r in rows)
    assert rows[0]["wps"] == pytest.approx(8 / (7 * 0.4 + 0.3), abs=1e-3)
    # a block shorter than 6 words is never judged (same as the gate)
    short = [{"id": "A", "text": "Run now."}, {"id": "B", "text": "one two three four five six seven"}]
    r2 = pacing.block_pace(short, [{"after_line": "A"}], [{"w": "x", "s": i, "e": i + 0.1} for i in range(9)])
    assert [r["measured"] for r in r2] == [False, True]


def test_in_band_run_changes_nothing(tmp_path):
    _, rep, _, be = run(tmp_path, {})
    pr = rep["pace_retake"]
    assert pr["ok"] and pr["fixes"] == [] and pr["usd"] == 0.0
    assert all(c["previous_text"] is None for c in be.calls)


# ------------------------------------------------------------------ tempo only
def test_tempo_only_fixes_a_slightly_slow_block(tmp_path):
    s = story()
    # no global tempo here, so the local atempo has the whole 0.9-1.1 room
    res, rep, words, be = run(tmp_path, {SLOW: 2.05}, s, tempo_fix=False)
    assert rep["tempo_correction"] == 1.0
    fx = fix_for(rep, "L02")
    assert fx["before_wps"] < 2.2
    assert fx["method"] == "tempo" and fx["applied"] and fx["takes"] == []
    assert 0.9 <= fx["tempo_total"] <= 1.1  # global x local tempo stays in voice_speed
    assert 2.2 <= fx["after_wps"] <= 3.3
    assert rep["pace_retake"]["usd"] == 0.0 and not any(c["previous_text"] or c["next_text"] for c in be.calls)
    assert canon_pace(s, words, rep)["status"] == "PASS"


def test_global_tempo_counts_toward_the_local_limit(tmp_path):
    """The same slow block under a 1.08 global tempo: 1.08 x local may not pass 1.1, so tempo cannot reach the band
    and the block is re-voiced instead (waterspout v2 L02 / L10)."""
    s = story()
    res, rep, words, _ = run(tmp_path, {SLOW: 1.85}, s)
    assert rep["tempo_correction"] > 1.05
    fx = fix_for(rep, "L02")
    assert fx["tempo_try"]["tempo_total"] <= 1.1 + 1e-6 and not fx["tempo_try"]["reaches"]
    assert fx["method"] == "retake" and fx["in_band"]
    assert canon_pace(s, words, rep)["status"] == "PASS"


# ------------------------------------------------------------------ re-voice
def test_retake_needed_for_a_rushed_block(tmp_path):
    s = story()
    res, rep, words, be = run(tmp_path, {RUSHED: 3.9}, s)
    fx = fix_for(rep, "L04")
    assert fx["before_wps"] > 3.3
    assert fx["tempo_try"]["reaches"] is False and fx["method"] == "retake" and fx["applied"]
    picked = [t for t in fx["takes"] if t.get("picked")]
    assert len(picked) == 1 and picked[0]["in_band"]
    assert all(0.9 <= t["speed"] <= 1.1 and 0.9 <= t["tempo"] <= 1.1 for t in fx["takes"])
    assert all(t["seed"] != 1 for t in fx["takes"])  # a new seed, never the original take's
    # the block alone was re-voiced, with its neighbours as context
    rc = [c for c in be.calls if c["previous_text"] or c["next_text"]]
    assert rc and all(RUSHED in c["text"] and TEXTS[0] not in c["text"] for c in rc)
    assert rc[0]["previous_text"] == TEXTS[2] and rc[0]["next_text"] is None
    # cost is booked in the report
    assert rep["pace_retake"]["usd"] > 0 and rep["usd"]["retakes"] == rep["pace_retake"]["usd"]
    assert rep["pace_retake"]["chars"] == sum(t["chars"] for t in fx["takes"] if not t["cache_hit"])
    # loudness of the spliced stem stays on target
    assert abs(rep["loudness"]["I"] - audio.VOICE_LUFS) <= 1.0
    assert canon_pace(s, words, rep)["status"] == "PASS"
    # the words still land on the audio: the speech after the last word is silence, and the stem ends after it
    assert audio.duration(res["audio"]) >= words[-1]["e"]
    assert abs(audio.silences(res["audio"])[-1][0] - words[-1]["e"]) < 0.08


def test_slow_and_rushed_in_one_run_keep_every_gap(tmp_path):
    s = story(5)
    res, rep, words, _ = run(tmp_path, {SLOW: 1.9, RUSHED: 3.9}, s)
    pr = rep["pace_retake"]
    assert pr["ok"], pr["after"]
    fixed = {tuple(f["lines"]): f["method"] for f in pr["fixes"] if f["applied"]}
    assert {("L02",), ("L04",)} <= set(fixed) and all(m == "tempo" for k, m in fixed.items() if k not in {("L02",), ("L04",)})
    # gaps: none shrank, every one still meets its planned length (gaps.py measure == canon CAN-N2c)
    with open(res["words"].replace(".words.json", ".gaps.json")) as fh:
        grep = json.load(fh)
    assert grep["ok"] and grep["inserts"] == []
    for g in gaps.measure(s, words):
        assert g["ok"], g
    assert canon_pace(s, words, rep)["status"] == "PASS"


def test_gap_lengths_identical_before_and_after_splice(tmp_path):
    s = story()
    # same narration voiced twice: once with the retake off, once on; every gap must measure the same
    _, rep_off, w_off, _ = run(tmp_path / "a", {RUSHED: 3.9, SLOW: 1.9}, s, pace_retake=False)
    _, rep_on, w_on, _ = run(tmp_path / "b", {RUSHED: 3.9, SLOW: 1.9}, s)
    m_off = {g["id"]: g["measured_s"] for g in gaps.measure(s, w_off)}
    m_on = {g["id"]: g["measured_s"] for g in gaps.measure(s, w_on)}
    for k in m_off:
        assert abs(m_on[k] - m_off[k]) <= 0.02, (k, m_off[k], m_on[k])
    # untouched block L01 sits exactly where it was
    assert w_on[:8] == w_off[:8]
    assert canon_pace(s, w_off, rep_off)["status"] == "FAIL"
    assert canon_pace(s, w_on, rep_on)["status"] == "PASS"


# ------------------------------------------------------------------ caps and ceiling
def test_retake_cap_lines_and_takes(tmp_path):
    s = story(5)
    fast = {t.split()[-2]: 4.6 for t in TEXTS}  # every block rushed far past what speed + tempo can fix
    res, rep, words, be = run(tmp_path, fast, s, retake_max_lines=3, retake_max_takes=2)
    pr = rep["pace_retake"]
    revoiced = [f for f in pr["fixes"] if f["method"] == "retake"]
    capped = [f for f in pr["fixes"] if "cap" in (f.get("reason") or "")]
    assert len(revoiced) == 3 and len(capped) == 2
    assert all(len(f["takes"]) <= 2 for f in pr["fixes"])
    assert len([c for c in be.calls if c["previous_text"] or c["next_text"]]) <= 6
    assert pr["cap"] == {"lines": 3, "takes": 2}
    assert not pr["ok"]  # honest: the gate will still fail, the report says why
    assert canon_pace(s, words, rep)["status"] == "FAIL"


def test_cost_ceiling_is_never_exceeded(tmp_path):
    s = story()
    full = stage.voice_usd_of(sum(len(stage.chunk_prompt([ln], "eleven_v4")) for ln in s["narration"]))
    ceiling = full + 0.016  # room for exactly one ~50-char take at $0.30 / 1k chars
    res, rep, words, be = run(tmp_path, {RUSHED: 4.6, SLOW: 1.5}, s, retake_ceiling_usd=ceiling)
    pr = rep["pace_retake"]
    assert pr["spent_before_usd"] + pr["usd"] <= ceiling + 1e-9
    skipped = [t for f in pr["fixes"] for t in f["takes"] if "skipped" in t]
    assert skipped and all("ceiling" in t["skipped"] for t in skipped)


def test_import_backend_never_revoices(tmp_path):
    s = story()
    words = [{"w": w, "s": i * 0.2, "e": i * 0.2 + 0.15} for i, w in
             enumerate(x for ln in s["narration"] for x in ln["text"].split())]
    src = tmp_path / "n.mp3"
    retake._write(audio.decode_mono(PlaceholderBackend().tts(" ".join(TEXTS[:4]), "v", "m", str(tmp_path / "p.mp3")).audio),
                  str(src))
    w2, rep = retake.pace_retake(s, str(src), words, ImportBackend([]), "v", "eleven_v4", work=str(tmp_path / "w"))
    assert all(f["method"] in ("none", "tempo") for f in rep["fixes"])
    assert all(f["takes"] == [] for f in rep["fixes"])


def test_canon_flags_a_retake_outside_voice_speed():
    s = story()
    words = [{"w": w, "s": i * 0.36, "e": i * 0.36 + 0.3} for i, w in
             enumerate(x for ln in s["narration"] for x in ln["text"].split())]
    ok = canon_pace(s, words, {"speed_requested": 1.0, "tempo_correction": 1.0})
    assert ok["status"] == "PASS"
    bad = {"speed_requested": 1.0, "tempo_correction": 1.0,
           "pace_retake": {"fixes": [{"lines": ["L02"], "applied": True, "speed": 0.8, "tempo_total": 1.0}]}}
    assert canon_pace(s, words, bad)["status"] == "FAIL"


# ------------------------------------------------------------------ stress: the defect class across paces
@pytest.mark.parametrize("native", [1.6, 1.9, 2.05, 3.6, 3.9, 4.2])
def test_stress_one_block_off_pace(tmp_path, native):
    """One block per run voiced at a native pace across the slow / rushed range (waterspout v2 saw 2.10 and 4.29 w/s
    after the global tempo). Every case ends in band, or the report names why not; gaps never shrink; speed and
    every tempo stay in voice_speed."""
    s = story()
    res, rep, words, _ = run(tmp_path, {RUSHED if native > 3 else SLOW: native}, s)
    pr = rep["pace_retake"]
    for f in pr["fixes"]:
        assert 0.9 - 1e-6 <= (f.get("tempo_total") or 1.0) <= 1.1 + 1e-6
        assert 0.9 - 1e-6 <= (f.get("speed") or 1.0) <= 1.1 + 1e-6 or f["method"] == "tempo"
        assert f["applied"] or f.get("reason")
    for g in gaps.measure(s, words):
        assert g["ok"], g
    assert pr["ok"] == (canon_pace(s, words, rep)["status"] == "PASS")
    if 1.9 <= native <= 3.9:
        assert pr["ok"], pr["fixes"]


# ------------------------------------------------------------------ word ends and internal pauses
def test_word_ends_stop_where_the_sound_stops():
    # char alignment stretched "gap." over the 0.44 s of silence after it (waterspout v2 L10)
    from factory.voice import align
    words = [{"w": "closes", "s": 0.0, "e": 0.37}, {"w": "the", "s": 0.44, "e": 0.52}, {"w": "gap.", "s": 0.59, "e": 1.55}]
    out, n, sec = align.trim_ends_to_speech(words, [(1.11, 1.70)])
    assert n == 1 and out[-1]["e"] == pytest.approx(1.15) and sec == pytest.approx(0.40, abs=0.01)
    assert [w["s"] for w in out] == [w["s"] for w in words]          # starts never move
    # a word that sounds to its end, or a silence that ends before the word does, is left alone
    same, n2, _ = align.trim_ends_to_speech(words, [(0.38, 0.43), (1.20, 1.30)])
    assert n2 == 0 and same == words


def test_slow_block_fixed_by_tightening_a_long_internal_pause(tmp_path):
    """'Earlier. You sail alone, ...' read with a long beat after 'Earlier.' under a 1.08 global tempo: tempo may not
    pass 1.1 in total, so the over-long pause is tightened (never below 0.25 s) instead of paying for a re-voice."""
    lines = [{"id": "L01", "tag": "tense", "text": TEXTS[0]},
             {"id": "L02", "tag": "serious", "text": "Earlier. You sail alone, south of Bermuda tonight."},
             {"id": "L03", "tag": "tense", "text": TEXTS[2]}]
    s = {"id": "pace", "format": "short", "style": "pixar_night_survival", "narration": lines,
         "narration_gaps": [{"id": "G01", "after_line": "L01", "len_s": 0.8, "purpose": "key_sfx", "filled_by": "room_tone"},
                            {"id": "G02", "after_line": "L02", "len_s": 0.8, "purpose": "key_sfx", "filled_by": "room_tone"}]}
    be = PlaceholderBackend(line_wps={"Earlier.": 2.4}, stop_pause=0.75)
    res = stage.synthesize(s, str(tmp_path / "o"), backend=be, cache_dir="")
    with open(res["report"]) as fh:
        rep = json.load(fh)
    with open(res["words"]) as fh:
        words = json.load(fh)
    fx = fix_for(rep, "L02")
    assert fx["before_wps"] < 2.2 and fx["method"] == "tempo+pauses" and fx["applied"], fx
    assert 0 < fx["tighten_s"] <= retake.TIGHTEN_MAX_S and fx["takes"] == []
    assert 0.9 <= fx["tempo_total"] <= 1.1
    # the pause after 'Earlier.' is still a real beat
    i = next(k for k, w in enumerate(words) if w["w"] == "Earlier.")
    sil = [b - a for a, b in audio.silences(res["audio"], -45, 0.1) if words[i]["s"] <= a and b <= words[i + 1]["s"] + 0.05]
    assert sil and min(sil) >= retake.PAUSE_KEEP_S - 0.06, sil
    assert canon_pace(s, words, rep)["status"] == "PASS"
    for g in gaps.measure(s, words):
        assert g["ok"], g
