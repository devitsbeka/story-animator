"""factory/shorts: derive vertical shorts from the mini-doc long-form (fixtures), shorts checklist, QC, audio cut,
VO-pickup hook path, Finish staging; plus the QC hooks the derived shorts rely on."""
import json
import os
import shutil
import subprocess
import sys
import types

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from factory.director import librarian  # noqa: E402
from factory.director.llm import FixtureClient  # noqa: E402
from factory.director.runner import Runner  # noqa: E402
from factory.shorts import checks, derive as dv, finish  # noqa: E402

MINI = os.path.join(ROOT, "factory", "director", "fixtures", "minidoc")
FPS = 30
HAS_FFMPEG = shutil.which("ffmpeg") is not None


@pytest.fixture(scope="module")
def epdir(tmp_path_factory):
    out = tmp_path_factory.mktemp("ep")
    Runner(str(out), FixtureClient(MINI), "mini-doc", "docuseries",
           ph=librarian.PolyHavenSearch(os.path.join(MINI, "polyhaven_search.json")), log=lambda *a: None).run()
    return str(out)


@pytest.fixture(scope="module")
def derived(epdir, tmp_path_factory):
    out = str(tmp_path_factory.mktemp("shorts"))
    ctx, results = dv.derive(epdir, out_root=out, voice="off")
    return ctx, results


def test_every_candidate_becomes_a_short(derived):
    ctx, results = derived
    assert sorted(r["edit"]["candidate"] for r in results) == ["SC1", "SC2", "SC3", "SC4", "SC5"]
    scores = [r["edit"]["score"] for r in results]
    assert scores == sorted(scores, reverse=True)                       # ranked by intensity
    for r in results:
        for f in ("edit.json", "episode.json", "words.json", "props.json"):
            assert os.path.exists(os.path.join(r["dir"], f)), f


def test_shorts_checklist_passes(derived):
    ctx, results = derived
    for r in results:
        rep = checks.check_short(r, ctx["episode"])
        assert rep.ok, (r["id"], rep.blocking)
        for rule in ("SH-hook", "SH-P-1", "SH-P-2", "SH-vertical", "SH-loop", "SH-camera-span"):
            assert rule in rep.passed, (r["id"], rule)


def test_edit_structure(derived):
    ctx, results = derived
    ep = ctx["episode"]
    for r in results:
        e = r["edit"]
        segs = e["segments"]
        hook, tail = segs[0], segs[-1]
        assert hook["kind"] == "hook" and hook["source"] == "recut" and 30 <= hook["dst1"] - hook["dst0"] <= 90
        cand = next(s for s in ep["shorts"] if s["id"] == e["candidate"])
        assert cand["from"] <= hook["src0"] < hook["src1"] <= cand["to"] + 10          # re-cut from inside the beat
        assert tail["kind"] == "tail" and tail["src0"] == hook["src0"] and tail["dst1"] == e["durationFrames"]
        assert all(a["dst1"] == b["dst0"] for a, b in zip(segs, segs[1:]))
        body = [g for g in segs if g["kind"] == "body"]
        assert sum(g["src1"] - g["src0"] for g in body) <= cand["to"] - cand["from"] + 15   # tighter, never longer
        shots = e["shots"]
        assert all(s["to"] - s["from"] >= 18 for s in shots)                              # C9
        assert max(s["to"] - s["from"] for s in shots) <= 2.6 * FPS + 1                   # P-2 cadence
        hook_shots = [s for s in shots if s["from"] < hook["dst1"]]
        assert len(hook_shots) >= 2                                                       # P-1 hook row: 2-3 shots
        assert any(s["zoom"] == dv.PUNCH_IN for s in shots)                               # punch-ins inside held plates


def test_words_and_captions_retimed(derived):
    ctx, results = derived
    for r in results:
        ws, D = r["words"], r["edit"]["durationFrames"] / FPS
        assert ws and all(0 <= w["s"] < w["e"] <= D for w in ws)
        assert all(a["s"] <= b["s"] for a, b in zip(ws, ws[1:]))
        pages = r["pages"]
        assert pages and all(1 <= len(p["words"]) <= 3 for p in pages)
        hook_text = r["edit"]["hook"]["text"].split()
        assert [w["w"] for w in ws[: len(hook_text)]] == hook_text                       # the hook speaks first
        caps = r["episode"]["captions"]
        assert caps[0]["kind"] == "title" and caps[0]["from"] == 0 and caps[0]["to"] >= 2 * FPS
        assert r["props"]["title"]["text"] == r["edit"]["hook_line"]


def test_qc_episode_uses_vertical_cameras(derived):
    ctx, results = derived
    by_id = {s["id"]: s for s in ctx["episode"]["shots"]}
    r = results[0]
    q = r["episode"]
    assert (q["width"], q["height"]) == (1080, 1920) and q["durationFrames"] == r["edit"]["durationFrames"]
    for qs, es in zip(q["shots"], r["edit"]["shots"]):
        src = by_id[es["plate"]]
        d = es["from"] - es["src"]
        v0 = src["cameras"]["vertical"]["keys"]
        assert "cameras" not in qs and qs["from"] == es["from"] and qs["to"] == es["to"]
        k = next(k for k in qs["camera"]["keys"] if k["f"] - d in {x["f"] for x in v0})
        vk = next(x for x in v0 if x["f"] == k["f"] - d)
        assert k["look"] == vk["look"] and k["fov"] == vk["fov"]


def test_qc_runs_on_every_short(derived):
    ctx, results = derived
    for r in results:
        rep = finish.qc(r)
        assert os.path.exists(rep["path"])
        assert rep["sections"]["FRAMING"]["failed"] == 0, [x for x in rep["rules"] if x["section"] == "FRAMING" and x["status"] == "fail"]
        ids = {x["id"]: x for x in rep["rules"]}
        assert ids["C-6.hook_title"]["status"] == "pass" and ids["C-2.words_per_page"]["status"] == "pass"
        assert ids["C9.shot_duration"]["status"] == "pass"


def test_cli(epdir, tmp_path):
    r = subprocess.run([sys.executable, "-m", "factory.shorts", "derive", "--episode", epdir, "--n", "2", "--out", str(tmp_path), "--voice", "off"],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "2 short(s) from minidoc" in r.stdout and r.stdout.count("checklist PASS") == 2
    rep = json.loads(next(p for p in (tmp_path / d / "report.json" for d in os.listdir(tmp_path))).read_text())
    assert rep["checklist"]["ok"] and rep["qc"]["decision"] in ("PUBLISH", "AUTO_FIX", "RETURN")


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_audio_is_cut_in_sync(epdir, tmp_path):
    ep = tmp_path / "ep"
    shutil.copytree(epdir, ep)
    (ep / "audio").mkdir()
    # a stand-in narration (a steady tone) as long as the episode audio
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=362", "-ac", "1", str(ep / "audio" / "narration.mp3")],
                   check=True)
    ctx, results = dv.derive(str(ep), n=1, voice="off")
    r = results[0]
    wav = os.path.join(r["dir"], "audio.wav")
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", wav],
                               capture_output=True, text=True, check=True).stdout)
    assert abs(dur - r["edit"]["durationFrames"] / FPS) < 0.06
    assert r["edit"]["audio"] == "audio.wav" and r["episode"]["audio"]["narration"].endswith("audio.wav")

    def mean_db(*args):
        err = subprocess.run(["ffmpeg", "-hide_banner", *args, "-i", wav, "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
        return float(err.split("mean_volume:")[1].split("dB")[0])
    assert mean_db("-sseof", "-0.4") < -60                  # the loop tail is silent picture of the hook's first frames
    assert mean_db("-t", "1.0") > -40                       # the hook speaks from frame 0


def test_vo_pickup_hook_when_voice_stage_exists(epdir, tmp_path, monkeypatch):
    calls = []

    def synthesize(story, out_dir, **kw):
        os.makedirs(out_dir, exist_ok=True)
        text = story["narration"][0]["text"]
        calls.append(text)
        words = [{"w": w, "s": round(0.05 + 0.33 * i, 3), "e": round(0.05 + 0.33 * i + 0.3, 3)} for i, w in enumerate(text.split())]
        wp = os.path.join(out_dir, "pickup.words.json")
        with open(wp, "w") as fh:
            json.dump(words, fh)
        return {"audio": os.path.join(out_dir, "pickup.mp3"), "words": wp}

    import factory
    fake = types.ModuleType("factory.voice")
    fake.synthesize = synthesize
    monkeypatch.setitem(sys.modules, "factory.voice", fake)
    monkeypatch.setattr(factory, "voice", fake, raising=False)
    ctx, results = dv.derive(epdir, n=1, out_root=str(tmp_path), voice="auto")
    r = results[0]
    h = r["edit"]["hook"]
    assert calls == [r["edit"]["hook_line"]] and h["source"] == "vo_pickup" and 1.0 <= (h["dst1"] - h["dst0"]) / FPS <= 3.0
    assert [w["w"] for w in r["words"][:3]] == r["edit"]["hook_line"].split()[:3]
    assert checks.check_short(r, ctx["episode"]).ok


def test_voice_unavailable_falls_back_to_recut(epdir, tmp_path):
    ctx, results = dv.derive(epdir, n=1, out_root=str(tmp_path), voice="auto")
    assert results[0]["edit"]["hook"]["source"] == "recut"


def test_finish_stage_reads_vertical_plates(derived, tmp_path):
    ctx, results = derived
    r = results[0]
    s = r["props"]["episodeJson"]["shots"][3]
    plates = tmp_path / "plates_vertical" / s["plate"]
    plates.mkdir(parents=True)
    png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000")
    (plates / f"{s['src']:04d}.png").write_bytes(png)
    path, n = finish.stage(r, str(tmp_path / "plates_vertical"), public=str(tmp_path / "public"))
    props = json.load(open(path))
    assert n == 1 and props["manifest"] == {s["plate"]: {"frames": [s["src"]]}}
    assert (tmp_path / "public" / "finish" / r["id"] / "plates" / s["plate"] / f"{s['src']:04d}.png").exists()
    assert props["episodeJson"]["width"] == 1080 and props["platesDir"] == f"finish/{r['id']}/plates"


def test_retime_shot_moves_every_frame_field():
    src = {"id": "D1", "from": 100, "to": 160, "keyFrame": 130,
           "camera": {"space": "yacht", "keys": [{"f": 100, "cam": [0, 0, 0], "look": [0, 0, 1], "fov": 30}, {"f": 160, "cam": [0, 0, 0], "look": [0, 0, 1], "fov": 30}],
                      "shakes": [{"at": 120, "px": 4, "tau": 1}]},
           "cameras": {"main": {}, "vertical": {"space": "yacht", "keys": [{"f": 100, "cam": [0, 0, 0], "look": [0, 1, 1], "fov": 25},
                                                                           {"f": 160, "cam": [0, 0, 0], "look": [0, 1, 1], "fov": 25}],
                                                 "shakes": [{"at": 120, "px": 4, "tau": 1}]}},
           "short_candidate": "SC1", "yacht": {"x": 0, "z": 0, "heading": 0, "lights": [[100, 1], [140, 0]], "pitch": 0.1},
           "actors": [{"asset": "hero", "local": [0, 0, 0], "perf": {"stance": [[-10000, "helm"], [130, "stand"]], "poses": [{"pose": "x", "from": 110, "to": 150}],
                                                                     "verbs": [{"verb": "nod", "at": 120}]}, "tracks": [{"clip": "none", "from": 0}]}],
           "props": [{"prop": "lamp", "attach": "yacht", "light": [[100, 1]], "strobe": 140}], "fires": [[100, [1, 1, 1, 1, 1, 1]]]}
    s = dv.retime_shot(src, -90, 20, 60, "S001", zoom=1.15)
    assert s["camera"]["keys"][0] == {"f": 10, "cam": [0, 0, 0], "look": [0, 1, 1], "fov": 25} and s["camera"]["shakes"][0]["at"] == 30
    assert "cameras" not in s and "short_candidate" not in s and (s["from"], s["to"], s["id"], s["zoom"]) == (20, 60, "S001", 1.15)
    assert s["yacht"]["lights"] == [[10, 1], [50, 0]] and s["yacht"]["pitch"] == 0.1
    perf = s["actors"][0]["perf"]
    assert perf["stance"] == [[-10000, "helm"], [40, "stand"]] and perf["poses"][0]["from"] == 20 and perf["verbs"][0]["at"] == 30
    assert s["props"][0]["light"] == [[10, 1]] and s["props"][0]["strobe"] == 50 and s["fires"][0][0] == 10
    assert src["cameras"]["vertical"]["keys"][0]["f"] == 100                                 # the source is untouched


# ------------------------------------------------------------------ QC hooks used by docuseries/shorts
def test_qc_master_resolution_follows_format():
    from factory.qc import episode as qep, video_rules
    m = {"probe": {"width": 1920, "height": 1080, "fps": 30.0, "duration": 360.0, "has_audio": False}, "video": {"black": [], "freeze": []}}
    master = qep.Episode(path="x.json", root=ROOT, data={"format": "docuseries", "width": 1920, "height": 1080, "fps": 30, "durationFrames": 10800, "shots": []})
    res = {r["id"]: r for r in video_rules.video_rules(m, master)}
    assert res["TQ-VIDEO-RES"]["status"] == "pass"
    short = qep.Episode(path="x.json", root=ROOT, data={"width": 1080, "height": 1920, "fps": 30, "durationFrames": 10800, "shots": []})
    assert {r["id"]: r for r in video_rules.video_rules(m, short)}["TQ-VIDEO-RES"]["status"] == "fail"


def test_qc_hook_title_is_not_a_word_page():
    from factory.qc import captions, episode as qep
    caps = [{"kind": "title", "from": 0, "to": 75, "small": "would you survive the reef alone at", "big": "night?", "at": "top", "box": [100, 330, 850, 500]},
            {"from": 3, "to": 20, "small": "the", "big": "sea", "at": "mid", "box": [300, 1060, 650, 1210]}]
    ep = qep.Episode(path="x.json", root=ROOT, data={"width": 1080, "height": 1920, "fps": 30, "durationFrames": 90, "shots": [], "captions": caps})
    out, rows = captions.caption_checks(ep)
    res = {r["id"]: r for r in out}
    assert res["C-6.hook_title"]["status"] == "pass" and res["C-2.words_per_page"]["status"] == "pass"
    assert res["C-2.page_duration"]["status"] == "pass" and len(rows) == 2
