"""Style system tests: styles as data (factory/styles) and the consumers that read the stamp.

Run: python3 -m pytest -q tests/styles          (UPDATE_SNAPSHOTS=1 rewrites tests/styles/snapshots/*.json)
"""
import copy
import json
import os
import sys

import jsonschema
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "factory", "direction"))
sys.path.insert(0, os.path.join(ROOT, "factory", "sound"))
sys.path.insert(0, os.path.join(ROOT, "factory", "finish"))

from factory import styles  # noqa: E402
from factory.styles import (StyleError, apply_style_to_episode, check_episode, list_styles, load_style,  # noqa: E402
                            resolved_style, retime_episode, validate_style)

EP_V4 = os.path.join(ROOT, "episodes", "sentinel", "episode_v4.json")
WORDS = os.path.join(ROOT, "episodes", "sentinel", "audio", "narration.words.json")
STYLES = ["documentary_naturalistic", "pixar_night_survival"]
SNAP = os.path.join(HERE, "snapshots")


@pytest.fixture(scope="module")
def ep4():
    with open(EP_V4) as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def styled(ep4):
    return {sid: apply_style_to_episode(ep4, sid) for sid in STYLES}


@pytest.fixture(scope="module")
def words():
    with open(WORDS) as fh:
        return json.load(fh)


# ------------------------------------------------------------------ the styles themselves
def test_both_styles_listed_and_valid():
    assert set(STYLES) <= set(list_styles())
    for sid in STYLES:
        with open(os.path.join(ROOT, "factory", "styles", f"{sid}.json")) as fh:
            assert validate_style(json.load(fh)) == []
        s = load_style(sid)
        assert s["id"] == sid and validate_style({k: v for k, v in s.items()}) == []


def test_styles_contrast():
    p, d = load_style("pixar_night_survival"), load_style("documentary_naturalistic")
    assert (p["frame"]["fps"], d["frame"]["fps"]) == (30, 24)
    assert d["narration"]["wps"] == [2.4, 2.7] and p["narration"]["wps"] == [2.8, 3.1]
    assert d["captions"]["mode"] == "lower_third" and d["captions"]["font"]["family"] == "SourceSerif4"
    assert p["captions"]["mode"] == "kinetic" and p["captions"]["font"]["family"] == "Inter"
    assert d["camera"]["handheld"]["default"] < p["camera"]["handheld"]["default"]  # softer motion
    assert "whip" not in d["transitions"]["vocabulary"] and "whip_pan" in d["camera"]["avoid"]
    assert d["grade"]["contrast"] < p["grade"]["contrast"] and d["grade"]["halation"] < p["grade"]["halation"]
    assert p["materials"]["outline"] == d["materials"]["outline"] == "none"
    assert p["look"]["view_transform"] == "AgX"


def test_house_style_matches_pre_style_defaults():
    """pixar_night_survival must reproduce what the consumers hard-coded before styles were data."""
    L = styles.lighting_module()
    from camera_presets import LENS_BY_EMOTION, LENS_BY_SIZE
    import designer
    p = load_style("pixar_night_survival")
    assert p["lighting"]["default_preset"] == L.DEFAULT_PRESET
    assert p["lens"]["by_emotion"] == LENS_BY_EMOTION and p["lens"]["by_size"] == LENS_BY_SIZE
    assert p["grade"] == {"contrast": 0.35, "vignette": 0.42, "grain": 0.07, "halation": 0.45, "coolShadows": 1.0}  # Grade.tsx DEFAULT_GRADE
    m = designer.HOUSE_MUSIC
    assert (p["music"]["bpm"], p["music"]["key"]) == (m["bpm"], m["key"])
    assert p["music"]["sfx_density"]["max_transients"] == m["sfx_density"]["max_transients"]
    tsx = open(os.path.join(ROOT, "studio", "src", "finish", "Captions.tsx")).read()
    sf = p["captions"]["safe"]
    assert f"SAFE = {{ x0: {sf['x0']}, x1: {sf['x1']}, y0: {sf['y0']}, y1: {sf['y1']} }}" in tsx
    for tone, hexv in p["captions"]["tones"].items():
        assert f'{tone}: "{hexv}"' in tsx


@pytest.mark.parametrize("mutate, needle", [
    (lambda s: s["lighting"]["time_of_day"]["night"].update(preset="no_such_preset"), "not a lighting.py preset"),
    (lambda s: s["lighting"]["time_of_day"]["night"].update(bogus_param=1.0), "not a lighting.py preset parameter"),
    (lambda s: s["camera"]["vocabulary"].append("crash_zoom"), "not in factory/direction/camera_presets.py"),
    (lambda s: s["music"].update(bpm=200), "outside bpm_range"),
    (lambda s: s["transitions"].update(default="whip", vocabulary=["cut"]), "transitions.default"),
    (lambda s: s["captions"]["safe"].update(x1=2000), "inside the 1080x1920 canvas"),
    (lambda s: s["frame"].update(fps=60), "schema /frame/fps"),
    (lambda s: s.pop("grade"), "'grade' is a required property"),
])
def test_invalid_styles_are_rejected(mutate, needle, tmp_path):
    with open(os.path.join(ROOT, "factory", "styles", "pixar_night_survival.json")) as fh:
        s = json.load(fh)
    mutate(s)
    errs = validate_style(s)
    assert any(needle in e for e in errs), errs
    p = tmp_path / "bad_style.json"
    p.write_text(json.dumps(s))
    with pytest.raises(StyleError):
        load_style(str(p))


def test_unknown_style_id():
    with pytest.raises(StyleError, match="unknown style"):
        load_style("nope")


@pytest.mark.parametrize("sid", STYLES)
def test_resolved_style_snapshot(sid):
    got = resolved_style(sid)
    path = os.path.join(SNAP, f"{sid}.resolved.json")
    if os.environ.get("UPDATE_SNAPSHOTS"):
        os.makedirs(SNAP, exist_ok=True)
        with open(path, "w") as fh:
            json.dump(got, fh, indent=1, sort_keys=True)
            fh.write("\n")
    with open(path) as fh:
        assert got == json.load(fh), f"resolved style changed; review and rerun with UPDATE_SNAPSHOTS=1 ({path})"


# ------------------------------------------------------------------ applying to episode_v4
@pytest.mark.parametrize("sid", STYLES)
def test_apply_produces_valid_episode(sid, ep4, styled):
    before = copy.deepcopy(ep4)
    out = styled[sid]
    assert ep4 == before, "apply_style_to_episode must not modify its input"
    s = load_style(sid)
    errs, warns = check_episode(out)
    assert errs == [] and warns == []
    assert out["fps"] == s["frame"]["fps"] and out["style"]["id"] == sid
    assert out["source"]["style"] == f"factory/styles/{sid}.json@v1"
    # every sequence got a preset from the style's time-of-day table; the storm flashback (D) is a storm
    seqs = out["world"]["lighting"]["sequences"]
    assert seqs["D"]["preset"] == s["lighting"]["time_of_day"]["storm"]["preset"]
    assert seqs["D"]["lightning_per_s"] == 0.0  # scripted lightning in env.weather: no doubled flashes
    assert seqs["A"]["preset"] == s["lighting"]["time_of_day"]["night"]["preset"]
    # idempotent: re-applying the same style changes nothing (handheld is scaled relative to the last stamp)
    assert apply_style_to_episode(out, sid) == out


@pytest.mark.parametrize("sid", STYLES)
def test_schema_errors_not_increased(sid, ep4, styled):
    """cloud/spec/episode.schema.json is behind the v4 extensions (direction, perf, props...); the style stamp must
    not add any new schema error on top of those."""
    with open(os.path.join(ROOT, "cloud", "spec", "episode.schema.json")) as fh:
        V = jsonschema.Draft202012Validator(json.load(fh))

    def errs(e):
        out = set()
        for x in V.iter_errors(e):
            p = [str(k) for k in x.path]
            if p[:1] == ["shots"]:
                p = ["shots", "*"] + p[2:]
            out.add(("/".join(p), x.validator))
        return out
    assert errs(styled[sid]) - errs(ep4) == set()


def test_lighting_hook_matches_world_lighting(styled):
    """lighting.py picks the same preset from episode.style alone as from the stamped world.lighting."""
    L = styles.lighting_module()
    for sid, ep in styled.items():
        bare = copy.deepcopy(ep)
        bare["world"].pop("lighting")
        for shot in ep["shots"]:
            a, b = L.resolve(ep, shot), L.resolve(bare, shot)
            assert (a["preset"], a["fill_ratio"], a["lightning_per_s"]) == (b["preset"], b["fill_ratio"], b["lightning_per_s"]), shot["id"]
        rows, problems = L.check_sequences(ep)
        assert problems == []
    # no style and no world.lighting: the legacy default is untouched
    plain = copy.deepcopy(styled["pixar_night_survival"])
    plain.pop("style")
    plain["world"].pop("lighting")
    assert all(L.resolve(plain, s)["preset"] == L.DEFAULT_PRESET for s in plain["shots"])


def test_explicit_episode_lighting_wins(ep4):
    ep = copy.deepcopy(ep4)
    ep["world"]["lighting"] = {"sequences": {"D": {"preset": "rim_silhouette"}}, "exposure_ev": 0.1}
    out = apply_style_to_episode(ep, "pixar_night_survival")
    assert out["world"]["lighting"]["sequences"]["D"] == {"preset": "rim_silhouette"}
    assert out["world"]["lighting"]["exposure_ev"] == 0.1
    forced = apply_style_to_episode(ep, "pixar_night_survival", override_lighting=True)
    assert forced["world"]["lighting"]["sequences"]["D"]["preset"] == "storm_night"


def test_pixar_on_v4_only_adds_the_stamp(ep4, styled):
    out = styled["pixar_night_survival"]
    assert out["shots"] == ep4["shots"] and out["captions"] == ep4["captions"] and out["fps"] == 30
    assert set(out) - set(ep4) == {"style"}


def test_docu_softens_handheld(ep4, styled):
    out = styled["documentary_naturalistic"]
    k = load_style("documentary_naturalistic")["camera"]["handheld"]["default"] / styles.HOUSE_HANDHELD
    for a, b in zip(ep4["shots"], out["shots"]):
        if isinstance(a["camera"].get("handheld"), (int, float)):
            assert b["camera"]["handheld"] == pytest.approx(a["camera"]["handheld"] * k, abs=1e-4)
    with pytest.raises(StyleError):
        apply_style_to_episode(ep4, "documentary_naturalistic", retime=False)


# ------------------------------------------------------------------ retime (30 -> 24 fps)
def test_retime_keeps_time_in_seconds(ep4, styled):
    out = styled["documentary_naturalistic"]
    assert out["fps"] == 24 and out["source"]["retimed"]["from_fps"] == 30
    assert abs(out["durationFrames"] / 24 - ep4["durationFrames"] / 30) <= 1 / 24
    assert abs(out["audio"]["offsetFrames"] / 24 - ep4["audio"]["offsetFrames"] / 30) <= 1 / 24
    prev = 0
    for a, b in zip(ep4["shots"], out["shots"]):
        assert b["from"] == prev and b["to"] > b["from"]
        prev = b["to"]
        assert abs(b["from"] / 24 - a["from"] / 30) <= 0.5 / 24 + 1e-9
        kf = [k["f"] for k in b["camera"]["keys"]]
        assert kf == sorted(set(kf)), b["id"]
        assert b["from"] <= b["keyFrame"] < b["to"]
        for p in b.get("props") or []:
            for key, v in p.items():
                if isinstance(v, list) and v and isinstance(v[0], list):
                    assert [x[0] for x in v] == sorted(x[0] for x in v)
        for a0, act in zip(a.get("actors") or [], b.get("actors") or []):
            if a0["perf"]["stance"][0][0] == -10000:
                assert act["perf"]["stance"][0][0] == -10000  # 'before the start' sentinel kept
    assert prev == out["durationFrames"]
    for a, b in zip(ep4["captions"], out["captions"]):
        assert abs(b["from"] / 24 - a["from"] / 30) <= 0.5 / 24 + 1e-9 and b["to"] > b["from"]
    # lightning frames in the storm flashback follow the retime
    a = next(s for s in ep4["shots"] if (s.get("env") or {}).get("weather", {}).get("lightning"))
    b = next(s for s in out["shots"] if s["id"] == a["id"])
    assert b["env"]["weather"]["lightning"] == [int(f * 0.8 + 0.5) for f in a["env"]["weather"]["lightning"]]


def test_retime_noop_and_steps():
    ep = {"fps": 30, "durationFrames": 60, "shots": [{"id": "X", "from": 0, "to": 60, "camera": {"keys": [{"f": 0}, {"f": 1}, {"f": 2}]},
                                                     "props": [{"show": [[0, 0], [30, 0], [31, 1]]}]}], "captions": []}
    assert retime_episode(ep, 30) == ep
    out = retime_episode(ep, 24)
    assert [k["f"] for k in out["shots"][0]["camera"]["keys"]] == [0, 1, 2]
    assert [k[0] for k in out["shots"][0]["props"][0]["show"]] == [0, 24, 25]  # a step stays a step


# ------------------------------------------------------------------ validator + QC still pass (no regressions)
@pytest.fixture(scope="module")
def validator():
    import shot_validator as V
    V.load_coast(ROOT)
    return V


@pytest.mark.parametrize("sid", STYLES)
def test_shot_validator_unchanged(sid, ep4, styled, validator):
    base = {r["id"]: r["status"] for r in validator.validate(ep4)["rules"]}
    got = {r["id"]: r["status"] for r in validator.validate(styled[sid])["rules"]}
    assert got == base


@pytest.mark.parametrize("sid", STYLES)
def test_qc_unchanged(sid, ep4, styled, tmp_path, monkeypatch):
    from factory.qc.report import run
    monkeypatch.chdir(ROOT)
    quiet = lambda *a, **k: None  # noqa: E731
    base = run(spec=EP_V4, out_dir=str(tmp_path / "qc_base"), run_vision=False, log=quiet)
    p = tmp_path / f"{sid}.json"
    p.write_text(json.dumps(styled[sid]))
    rep = run(spec=str(p), out_dir=str(tmp_path / "qc_style"), run_vision=False, log=quiet)
    assert {r["id"]: r["status"] for r in rep["rules"]} == {r["id"]: r["status"] for r in base["rules"]}
    assert rep["decision"] == base["decision"]


# ------------------------------------------------------------------ consumers
def test_sound_designer_reads_music_palette(ep4, styled, words):
    import designer
    base = designer.design(ep4, words)
    house = designer.design(styled["pixar_night_survival"], words)
    assert [(c["type"], c["sfx"], c["at"]) for c in house["cues"]] == [(c["type"], c["sfx"], c["at"]) for c in base["cues"]]
    assert (house["music"]["bpm"], house["music"]["key"]) == (110, "D minor")
    docu = designer.design(styled["documentary_naturalistic"], words)
    d = load_style("documentary_naturalistic")["music"]
    assert (docu["music"]["bpm"], docu["music"]["key"], docu["music"]["style"]) == (d["bpm"], d["key"], "documentary_naturalistic")
    assert not [c for c in docu["cues"] if c["type"] in ("whoosh", "ui")]
    assert max(s["energy"] for s in docu["music"]["sections"]) <= d["energy_max"]
    win = int(round(d["sfx_density"]["window_s"] * 24))
    tr = sorted(c["at"] for c in docu["cues"] if c["transient"])
    assert all(sum(1 for t in tr if a <= t < a + win) <= d["sfx_density"]["max_transients"] for a in tr)


def test_music_transposes_to_style_key():
    import music
    main, dark = music.key_progressions("A minor")
    assert [r for r, _ in main] == [r - 5 for r, _ in music.PROG]
    assert music.key_progressions("D minor") == (music.PROG, music.DARK)
    assert music.key_progressions("D major")[0] == music.MAJOR
    import numpy as np
    out = music.render([{"from": 0, "to": 24, "energy": 2, "mood": "tense"}], 24, 24, bpm=72, key="A minor")
    assert out.shape == (48000, 2) and np.isfinite(out).all() and np.abs(out).max() > 0


def test_finish_props_from_episode(styled, tmp_path):
    import make_plates_manifest as mpm
    for sid, ep in styled.items():
        epp = tmp_path / f"{sid}" / "episode.json"
        epp.parent.mkdir()
        ep = {**ep, "audio": {**ep["audio"], "narration": os.path.join(ROOT, ep["audio"]["narration"]),
                              "wordsJson": os.path.join(ROOT, ep["audio"]["wordsJson"])}}
        epp.write_text(json.dumps(ep))
        plates = tmp_path / f"{sid}" / "plates"
        plates.mkdir()
        pub = tmp_path / f"{sid}" / "public"
        assert mpm.main(["--episode", str(epp), "--plates", str(plates), "--stage", "--public", str(pub)]) == 0
        props = json.loads((pub / "finish" / "sentinel" / "props.json").read_text())
        s = load_style(sid)
        assert props["grade"] == s["grade"]
        assert props["transitions"] == s["transitions"]["vocabulary"]
        cs = props["captionStyle"]
        assert cs["mode"] == s["captions"]["mode"] and cs["font"] == s["captions"]["font"]["family"]
        assert cs["safe"] == s["captions"]["safe"] and cs["tones"] == s["captions"]["tones"]
        n_words = max(len(p["words"]) for p in props["captions"])
        assert n_words <= s["captions"]["paging"]["max_words"]
        if sid == "documentary_naturalistic":
            assert n_words > 3  # lower thirds carry longer phrases than kinetic captions


def test_caption_paging_default_unchanged(words):
    from captions import build_pages
    assert build_pages(words, 30, 15) == build_pages(words, 30, 15, paging={"max_words": 3, "max_chars_3": 14, "max_page_s": 1.2})


def test_director_prompt_has_style_section():
    from factory.director import prompts
    p = prompts.system_blocks("direct", "pixar_night_survival")[0]["text"]
    assert "STYLE `pixar_night_survival`" in p and "moonlight_practical_mix" in p and "POSES:" in p
    d = prompts.system_blocks("develop", "documentary_naturalistic")[0]["text"]
    assert "STYLE `documentary_naturalistic`" in d and "2.4-2.7 words/s" in d and "24 fps" in d
    assert "STYLE `pixar_night_survival`" in prompts.system_blocks("develop")[0]["text"]  # default


def test_render_episode_reads_style_look():
    src = open(os.path.join(ROOT, "cloud", "blender", "render_episode.py")).read()
    assert '(spec.get("style") or {}).get("look")' in src and 'sty.get("exposure", 1.0)' in src


def test_cli_apply_and_check(tmp_path):
    from factory.styles.__main__ import main
    out = tmp_path / "ep.json"
    assert main(["apply", "--episode", EP_V4, "--style", "documentary_naturalistic", "--out", str(out)]) == 0
    assert main(["check", str(out)]) == 0
    assert json.loads(out.read_text())["fps"] == 24
