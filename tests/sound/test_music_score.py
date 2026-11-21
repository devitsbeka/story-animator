"""Tests for the real-music score path: beat analysis, stem planning / stitching, licensed-library adapters.

Synthetic click-track stems (no network, no library files) except the last class, which runs on the generated
Sentinel stems when $LIBRARY_STORE has them and is skipped otherwise.
Run: python3 -m pytest tests/sound -q
"""
import json, os, sys

import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SOUND = os.path.join(ROOT, "factory", "sound")
sys.path.insert(0, SOUND)
sys.path.insert(0, os.path.join(ROOT, "factory", "library", "sources"))

import beats as B  # noqa: E402
import score as S  # noqa: E402
import music_library as ML  # noqa: E402

SR = 48000


def click_track(bpm=110.0, dur=20.0, first=0.25, accent_every=4, bed_db=-30.0, seed=0, sr=SR):
    """Stereo test stem: decaying noise clicks on a beat grid (downbeats 2x louder) over a quiet sine bed."""
    rng = np.random.default_rng(seed)
    n = int(dur * sr)
    t = np.arange(n) / sr
    x = (10 ** (bed_db / 20)) * np.sin(2 * np.pi * 147 * t)
    period = 60.0 / bpm
    L = int(0.05 * sr)
    burst = rng.standard_normal(L) * np.exp(-np.arange(L) / (0.008 * sr))
    times = np.arange(first, dur - 0.06, period)
    for k, bt in enumerate(times):
        i = int(round(bt * sr))
        amp = 0.8 if k % accent_every == 0 else 0.35
        x[i:i + L] += amp * burst[:n - i]
    return np.stack([x, x], axis=1).astype(np.float32), times


# ------------------------------------------------------------------------------------------------- beats
class TestBeats:
    def test_tempo_blind_and_with_prior(self):
        x, _ = click_track(bpm=110)
        env, fr = B.onset_envelope(x, SR)
        assert abs(B.estimate_tempo(env, fr) - 110) < 0.6
        assert abs(B.estimate_tempo(env, fr, prior_bpm=110) - 110) < 0.6

    def test_prior_resolves_octave(self):
        x, _ = click_track(bpm=90)
        env, fr = B.onset_envelope(x, SR)
        assert abs(B.estimate_tempo(env, fr, prior_bpm=90) - 90) < 0.6

    def test_beat_grid_matches_clicks(self):
        x, times = click_track(bpm=110, first=0.31)
        a = B.analyse(x, SR, prior_bpm=110)
        err = [np.min(np.abs(a["beats"] - t)) for t in times[1:-1]]
        assert np.median(err) < 0.012 and max(err) < 0.03
        assert a["ibi_jitter"] < 0.05

    def test_downbeats_follow_accent(self):
        x, times = click_track(bpm=120, first=0.2)
        a = B.analyse(x, SR, prior_bpm=120)
        # accented clicks are times[0::4]
        for t in a["downbeats"][:-1]:
            assert np.min(np.abs(times[0::4] - t)) < 0.02

    def test_accent_is_high_on_click_low_between(self):
        x, times = click_track(bpm=110)
        env, fr = B.onset_envelope(x, SR)
        on = B.accent(env, fr, times[4:8]).mean()
        off = B.accent(env, fr, times[4:8] + 0.27).mean()
        assert on > 0.3 and off < 0.1


# ------------------------------------------------------------------------------------------------- planning
@pytest.fixture(scope="module")
def stems():
    tens, _ = click_track(bpm=110, dur=30, first=0.4, seed=1)
    dark, _ = click_track(bpm=110, dur=12, first=0.1, bed_db=-36, seed=2)
    res, _ = click_track(bpm=110, dur=8, first=0.05, bed_db=-24, seed=3)
    return {"tension": S.Stem("tension", tens, SR, "tension", 110),
            "dark": S.Stem("dark", dark, SR, "dark", 110),
            "resolve": S.Stem("resolve", res, SR, "resolve", 110)}


FPS = 30
SECTIONS = [
    {"id": "a", "from": 0, "to": 140, "energy": 4, "hit": True, "mood": "tense"},
    {"id": "b", "from": 140, "to": 307, "energy": 3, "hit": False, "mood": "tense"},
    {"id": "c", "from": 307, "to": 461, "energy": 4, "hit": True, "mood": "tense"},
    {"id": "d", "from": 461, "to": 600, "energy": 3, "hit": True, "mood": "dark"},
    {"id": "e", "from": 600, "to": 615, "energy": 0, "mood": "tense"},
    {"id": "f", "from": 615, "to": 700, "energy": 5, "hit": True, "mood": "resolve"},
]
CUES = [{"id": "i0", "type": "impact", "at": 0}, {"id": "w1", "type": "whoosh", "at": 211},
        {"id": "i2", "type": "impact", "at": 307}, {"id": "w3", "type": "whoosh", "at": 383},
        {"id": "i4", "type": "impact", "at": 461}, {"id": "i5", "type": "impact", "at": 615}]


class TestPlan:
    def test_roles_follow_mood(self, stems):
        pl = S.plan(SECTIONS, FPS, stems, CUES)
        by = {p["section"]: p["stem"] for p in pl}
        assert by["a"] == "tension" and by["d"] == "dark" and by["f"] == "resolve" and by["e"] is None

    def test_hit_sections_start_on_a_beat(self, stems):
        pl = S.plan(SECTIONS, FPS, stems, CUES)
        for p in pl:
            sec = next(s for s in SECTIONS if s["id"] == p["section"])
            if sec.get("hit") and p["stem"]:
                assert np.min(np.abs(stems[p["stem"]].beats - p["src_start"])) < 1e-3

    def test_non_hit_continues_seamlessly(self, stems):
        pl = S.plan(SECTIONS, FPS, stems, CUES)
        a, b = pl[0], pl[1]
        assert b["splice"] is False
        assert abs(b["src_start"] - (a["src_start"] + a["dst_end"] - a["dst_start"])) < 1e-6
        assert len(S.segments(pl)) == len(pl) - 1        # a+b merged

    def test_impacts_land_on_beats_better_than_naive(self, stems):
        pl = S.plan(SECTIONS, FPS, stems, CUES)
        naive = S.plan(SECTIONS, FPS, stems, CUES, naive=True)
        got = S.summarise(S.alignment(pl, stems, CUES, FPS))
        base = S.summarise(S.alignment(naive, stems, CUES, FPS))
        assert got["impact"]["on_beat_frac"] == 1.0
        assert got["mean_accent"] > base["mean_accent"]

    def test_energy_ladder_trims(self, stems):
        pl = S.plan(SECTIONS, FPS, stems, CUES)
        for p in pl:
            if p["stem"]:
                assert abs(p["gain_db"]) <= S.MAX_TRIM_DB

    def test_split_on_whooshes(self):
        secs = S.split_on_whooshes(SECTIONS, CUES, FPS, min_len_s=2.0)
        ids = [s["id"] for s in secs]
        assert "b@211" in ids and "c@383" in ids
        sub = next(s for s in secs if s["id"] == "b@211")
        assert sub["from"] == 211 and sub["to"] == 307 and sub["soft_hit"] and not sub["hit"]
        # contiguous cover of the timeline, same total
        assert [s["from"] for s in secs[1:]] == [s["to"] for s in secs[:-1]]
        # too short a remainder: no split
        assert S.split_on_whooshes(SECTIONS, CUES, FPS, min_len_s=10.0) == SECTIONS


# ------------------------------------------------------------------------------------------------- render
class TestRender:
    def render(self, stems):
        pl = S.plan(SECTIONS, FPS, stems, CUES)
        total = SECTIONS[-1]["to"] / FPS
        return pl, S.render(pl, stems, total), total

    def test_length_and_silence(self, stems):
        pl, x, total = self.render(stems)
        assert x.shape == (int(round(total * SR)), 2)
        a, b = int(600 / FPS * SR), int(615 / FPS * SR)
        assert np.abs(x[a + 10:b - 10]).max() == 0.0

    def test_hit_downbeat_at_full_level(self, stems):
        # crossfade ends on the boundary: just after a hit boundary the output is the incoming stem alone
        pl, x, _ = self.render(stems)
        p = next(p for p in pl if p["section"] == "c")
        st = stems[p["stem"]]
        d0, s0 = int(round(p["dst_start"] * SR)), int(round(p["src_start"] * SR))
        seg = x[d0 + 5:d0 + 2000]
        ref = st.x[s0 + 5:s0 + 2000] * 10 ** (p["gain_db"] / 20)
        np.testing.assert_allclose(seg, ref, atol=1e-5)

    def test_preroll_crossfade_before_boundary(self, stems):
        pl, x, _ = self.render(stems)
        p = next(p for p in pl if p["section"] == "c")
        d0 = int(round(p["dst_start"] * SR))
        xn = int(S.XFADE_S * SR)
        pre = x[d0 - xn:d0]
        assert np.sqrt((pre ** 2).mean()) > 1e-4          # something is playing in the crossfade, no hole

    def test_equal_power_crossfade_no_dip(self):
        rng = np.random.default_rng(5)
        n1 = rng.standard_normal((SR * 6, 2)).astype(np.float32) * 0.1
        n2 = rng.standard_normal((SR * 6, 2)).astype(np.float32) * 0.1
        sa, sb = S.Stem("a", n1, SR, "tension", 110), S.Stem("b", n2, SR, "dark", 110)
        pl = [{"section": "x", "stem": "a", "dst_start": 0.0, "dst_end": 2.0, "src_start": 1.0, "gain_db": 0.0, "splice": True},
              {"section": "y", "stem": "b", "dst_start": 2.0, "dst_end": 4.0, "src_start": 1.0, "gain_db": 0.0, "splice": True}]
        x = S.render(pl, {"a": sa, "b": sb}, 4.0)
        xn = int(S.XFADE_S * SR)
        mid = x[2 * SR - xn:2 * SR]
        ref = x[SR:SR + 4 * xn]
        dip = 10 * np.log10((mid ** 2).mean() / (ref ** 2).mean())
        assert -1.5 < dip < 1.5

    def test_hard_stop_at_end(self, stems):
        pl, x, _ = self.render(stems)
        tail = x[-int(0.1 * SR):-200]
        assert np.sqrt((tail ** 2).mean()) > 1e-3          # still playing in the last 100 ms
        assert np.abs(x[-1]).max() < 1e-3                  # 2 ms de-click only

    def test_extend_with_loops(self, stems):
        st = stems["dark"]
        y = S.extend_with_loops(st, 30.0)
        assert len(y) / SR >= 30.0
        # loops are bar-aligned: the loop period is a whole number of bars
        bar = 4 * 60.0 / st.bpm
        a, b = st.downbeats[1], st.downbeats[st.downbeats < st.usable_end - 0.1][-1]
        assert abs(((b - a) / bar) - round((b - a) / bar)) < 0.05

    def test_long_section_loops_instead_of_failing(self, stems):
        secs = [{"id": "long", "from": 0, "to": 30 * 20, "energy": 3, "hit": True, "mood": "dark"}]
        pl = S.plan(secs, FPS, stems, [])
        x = S.render(pl, stems, 20.0)
        assert np.sqrt((x[-SR:-SR // 2] ** 2).mean()) > 1e-3


class TestApply:
    def test_apply_switches_engine(self):
        snd = json.load(open(os.path.join(ROOT, "episodes", "sentinel", "sound.json")))
        out = S.apply(snd)
        assert out["music"]["engine"] == "stems" and out["music"]["manifest"].endswith("music_manifest.json")
        assert out["music"]["sections"] == snd["music"]["sections"]
        assert snd["music"]["engine"] == "procedural"      # input untouched

    def test_manifest_fields(self):
        m = S.manifest()
        roles = {e["role"] for e in m["stems"].values()}
        assert {"tension", "dark", "resolve"} <= roles
        for e in m["stems"].values():
            for k in ("file", "generation", "node", "session", "prompt", "bpm"):
                assert e.get(k), k


# ------------------------------------------------------------------------------------------------- library
class TestLibrary:
    def rec(self, tmp_path, **kw):
        f = tmp_path / "dl.mp3"
        if not f.exists():
            f.write_bytes(b"not really audio")
        r = {"source_id": "123", "title": "Dark Tension", "author": "Someone", "url": "https://example.org/t/123",
             "licence": "Pixabay Content License", "retrieved": "2026-11-21", "file": str(f), "bpm": 110,
             "mood": ["tense"], "tags": ["cinematic"]}
        r.update(kw)
        return r

    def test_pixabay_policy(self, tmp_path):
        src = ML.PixabayMusicSource(manifest={"tracks": []})
        ok, attr = src.licence_policy(self.rec(tmp_path))
        assert ok and "Someone" in attr
        with pytest.raises(ML.LicenceError):
            src.licence_policy(self.rec(tmp_path, content_id=True))
        with pytest.raises(ML.LicenceError):
            src.licence_policy(self.rec(tmp_path, licence="All rights reserved"))

    @pytest.mark.parametrize("lic,ok", [("CC0", True), ("CC BY 4.0", True), ("CC BY-SA 4.0", True),
                                        ("CC BY-NC 4.0", False), ("CC BY-ND 4.0", False), ("CC BY-NC-SA 3.0", False)])
    def test_fma_policy(self, tmp_path, lic, ok):
        src = ML.FMASource(manifest={"tracks": []})
        r = self.rec(tmp_path, licence=lic)
        if ok:
            good, attr = src.licence_policy(r)
            assert good and ((attr is None) == (lic == "CC0"))
        else:
            with pytest.raises(ML.LicenceError):
                src.licence_policy(r)

    def test_missing_provenance_rejected(self, tmp_path):
        src = ML.PixabayMusicSource(manifest={"tracks": [self.rec(tmp_path, url="")]})
        assert src.search() == []

    def test_intake_registers_with_provenance(self, tmp_path, monkeypatch):
        import common
        cat = tmp_path / "catalog.json"
        monkeypatch.setattr(common, "CATALOG", str(cat))
        x, _ = click_track(dur=6)
        wav = tmp_path / "track.wav"
        from audio_util import write_wav
        write_wav(str(wav), x)
        man = {"tracks": [self.rec(tmp_path, file=str(wav)), self.rec(tmp_path, source_id="9", licence="CC BY-NC 4.0")]}
        src = ML.FMASource(manifest={"tracks": [dict(man["tracks"][1])]}, store=str(tmp_path / "store"))
        done, rej = src.intake(analyse=False)
        assert not done and rej and "non-commercial" in rej[0]["reason"]
        src = ML.PixabayMusicSource(manifest={"tracks": [man["tracks"][0]]}, store=str(tmp_path / "store"))
        done, rej = src.intake(analyse=True)
        assert len(done) == 1 and not rej
        e = json.load(open(cat))["assets"]["pixabay:music_123"]
        assert e["kind"] == "music" and e["files"][0]["sha256"] and e["url"].startswith("https://")
        assert e["provenance"]["retrieved"] == "2026-11-21" and e["provenance"]["attribution"]
        assert abs(e["music"]["bpm_measured"] - 110) < 1.0
        assert os.path.exists(tmp_path / "store" / e["files"][0]["path"])
        found = ML.CatalogSource().search(mood="tense", bpm=55)           # half-time matches
        assert [t.id for t in found] == ["pixabay:music_123"]
        assert ML.CatalogSource().search(bpm=140) == []

    def test_catalog_has_score_stems(self):
        ts = ML.CatalogSource().search()
        ids = {t.id for t in ts}
        assert {"el:music_tension_build", "el:music_flashback_dark", "el:music_payoff_resolve"} <= ids
        t = next(t for t in ts if t.id == "el:music_tension_build")
        assert t.role == "tension" and "tense" in t.mood and t.sha256 and abs(t.bpm - 110) < 1


# ------------------------------------------------------------------------------------------------- real stems
STORE = os.environ.get("LIBRARY_STORE", os.path.join(ROOT, "library_store"))
HAVE = all(os.path.exists(os.path.join(STORE, e["file"])) for e in S.manifest()["stems"].values())


@pytest.mark.skipif(not HAVE, reason="generated stems not in $LIBRARY_STORE")
class TestSentinelStems:
    def test_render_music_on_sentinel(self):
        snd = S.apply(json.load(open(os.path.join(ROOT, "episodes", "sentinel", "sound.json"))))
        x, rep = S.render_music(snd["music"], snd["fps"], snd["durationFrames"], snd["cues"], store=STORE)
        assert x.shape[0] == int(round(snd["durationFrames"] / snd["fps"] * SR))
        for k, st in rep["stems"].items():
            assert abs(st["bpm"] - 110) < 1.0, k
        assert rep["alignment"]["impact"]["on_beat_frac"] >= 0.8
        assert rep["alignment"]["on_beat_frac"] > rep["alignment_naive"]["on_beat_frac"]
