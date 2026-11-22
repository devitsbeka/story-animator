"""Canon checks (factory/canon/checks.py) on synthetic and fixture episodes: every automatable CAN-* sub-rule
must PASS on the canon-authored Sentinel fixture and FAIL on a targeted violation."""
import copy
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("FACTORY_SERIES", "none")

from factory.canon import checks as cc  # noqa: E402
from factory.director import compile as comp, librarian  # noqa: E402

FX = os.path.join(ROOT, "factory", "director", "fixtures", "sentinel")


def load(n):
    with open(os.path.join(FX, n)) as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def base():
    story, plan, bd = load("develop.3.json"), load("direct.2.json"), load("breakdown.1.json")
    man, _ = librarian.resolve(bd, ph=librarian.PolyHavenSearch(os.path.join(FX, "polyhaven_search.json")))
    return story, plan, bd, man


def fails(r):
    return {k for k, v in r.items() if isinstance(v, dict) and v.get("status") == "FAIL"}


def plan_fails(story, plan, bd, man, words=None):
    ep = comp.compile_episode(plan, story, man, "/tmp")
    return fails(cc.plan_rules(story, plan, ep, words, bd))


def shot(plan, sid):
    return next(s for s in plan["shots"] if s["id"] == sid)


def stub_words(story):
    from factory.run.voice import stub_timings
    return stub_timings(story)


# ------------------------------------------------------------------ the canon fixture passes, the legacy one does not
def test_canon_fixture_passes(base):
    story, plan, bd, man = base
    assert not fails(cc.story_rules(story))
    assert not plan_fails(story, plan, bd, man, stub_words(story))


def test_legacy_fixture_fails_the_canon(base):
    _, _, bd, man = base
    f = fails(cc.story_rules(load("develop.2.json")))
    assert {"CAN-S1a", "CAN-S2a", "CAN-N1a", "CAN-N2b", "CAN-N4a", "CAN-N4c", "CAN-N4f", "CAN-N2f-plan"} <= f
    f = plan_fails(load("develop.2.json"), load("direct.1.json"), bd, man)
    assert {"CAN-C2a", "CAN-L1a", "CAN-T1a", "CAN-H1a", "CAN-P1c", "CAN-P2c", "CAN-N3b"} <= f


# ------------------------------------------------------------------ story rules
@pytest.mark.parametrize("mutate,rule", [
    (lambda s: s["threats"][0].update(planted_t=s["threats"][0]["noticed_at"] - 1.0), "CAN-S1a"),
    (lambda s: s["knowledge_timeline"][4]["character_knows"].append("T_reef"), "CAN-S1b"),
    (lambda s: s["threats"][0].update(outcome="killed"), "CAN-S1c"),
    (lambda s: s["knowledge_timeline"][0].pop("audience_question"), "CAN-S2a"),
    (lambda s: s["knowledge_timeline"][3].update(mode="shared"), "CAN-S2b"),
    (lambda s: s["knowledge_timeline"][5].update(audience_question=s["knowledge_timeline"][4]["audience_question"]), "CAN-S2c"),
    (lambda s: s["knowledge_timeline"][6].update(audience_question="Who did this to him?"), "CAN-S2c"),
    (lambda s: s["knowledge_timeline"][4]["audience_knows"].extend(["X1", "X2"]), "CAN-S2e"),
    (lambda s: [k.update(mode="shared") for k in s["knowledge_timeline"] if k["mode"] == "dramatic_irony"], "CAN-S2f"),
    (lambda s: s["script_columns"].pop(1), "CAN-N1b"),
    (lambda s: s["script_columns"][0].update(picture=" "), "CAN-N1a"),
    (lambda s: s["narration_gaps"][3].update(len_s=0.5), "CAN-N2b"),
    (lambda s: s.update(narration_gaps=[g for g in s["narration_gaps"] if g["after_line"] != "L09"]), "CAN-N2b"),
    (lambda s: s.pop("narrator"), "CAN-N4a"),
    (lambda s: s["narration"][3].pop("adds"), "CAN-N4c"),
    (lambda s: s["narration"][5].update(text="The hull slams onto coral and tilts while foam bursts and the hero is knocked down."), "CAN-N4c"),
    (lambda s: s["narration"][2].update(text="Nothing.") or s["narration_gaps"][1].update(purpose="key_sfx"), "CAN-N4d"),
    (lambda s: s["narration"][4].update(text="The current is being pulled by the moon and the wind and the tide over the coral at night."), "CAN-N4f"),
    (lambda s: [ln.update(t1=min(ln["t1"] + 2.5, s["duration_s"])) for ln in s["narration"]], "CAN-N2f-plan"),
])
def test_story_rule_failures(base, mutate, rule):
    s = copy.deepcopy(base[0])
    mutate(s)
    assert rule in fails(cc.story_rules(s)), rule


# ------------------------------------------------------------------ plan rules
@pytest.mark.parametrize("mutate,rule", [
    (lambda s, p: shot(p, "A04").pop("extra_cu_reason"), "CAN-C2a"),
    (lambda s, p: [q.update(reserved_close_up=None) for q in p["sequences"]], "CAN-C2a"),
    (lambda s, p: shot(p, "R16").update(to=shot(p, "R16")["from"] + 30) or shot(p, "C17").update(**{"from": shot(p, "R16")["from"] + 30}), "CAN-C2c"),
    (lambda s, p: shot(p, "A01").pop("establishes"), "CAN-C1b"),
    (lambda s, p: p["sequences"][2]["action_order"].update(obstacle_audience_frame=shot(p, "A09")["from"] - 30), "CAN-E1b"),
    (lambda s, p: p["sequences"][2]["action_order"].update(cost_revealed="A08"), "CAN-E1a"),
    (lambda s, p: p["sequences"][2]["discovery_map"].pop(1), "CAN-E1d"),
    (lambda s, p: p["sequences"][2].update(tension="frantic"), "CAN-E1g"),
    (lambda s, p: shot(p, "B10").pop("impact_handheld"), "CAN-H1a"),
    (lambda s, p: shot(p, "B10")["impact_handheld"].update(lag_frames=20), "CAN-H1c"),
    (lambda s, p: shot(p, "C20")["camera"].update(handheld=0.2), "CAN-H1e"),
    (lambda s, p: shot(p, "C18")["hero"]["poses"][0].update(**{"from": shot(p, "C18")["from"] + 3}), "CAN-P1c"),
    (lambda s, p: shot(p, "B11")["hero"]["stance_changes"].__setitem__(0, [shot(p, "B11")["to"] - 4, "brace"]), "CAN-P1c"),
    (lambda s, p: shot(p, "R16")["turn_then_change"][0].update(settle_frames=2, change={"from": shot(p, "R16")["from"] + 26,
                                                                                       "to": shot(p, "R16")["from"] + 38}), "CAN-P1b"),
    (lambda s, p: shot(p, "C13")["hero"]["poses"][0].pop("why"), "CAN-P2c"),
    (lambda s, p: p["sequences"][0]["discovery_map"][0].update(frame=shot(p, "A04")["from"] + 2), "CAN-L1a"),
    (lambda s, p: p.pop("lookdev_test"), "CAN-T1a"),
    (lambda s, p: p["lookdev_test"].update(elements=["boat", "water", "actors"]), "CAN-T1b"),
    (lambda s, p: s["narration"][3]["reveal_order"].update(order="before"), "CAN-N3b"),
    (lambda s, p: s["narration"][8]["reveal_order"].update(reveal_frame=1), "CAN-N3b"),
    (lambda s, p: shot(p, "R16").update(line_ids=["L09"]) or s["narration_gaps"].__setitem__(
        4, dict(s["narration_gaps"][4], len_s=0.5)) or [ln.update(t0=ln["t0"] - 2.3) for ln in s["narration"] if ln["id"] == "L09"], "CAN-N3e"),
    (lambda s, p: s["narration"][10].update(text=s["narration"][10]["text"] + " That was the mistake."), "CAN-N4e"),
])
def test_plan_rule_failures(base, mutate, rule):
    story, plan, bd, man = base
    s, p = copy.deepcopy(story), copy.deepcopy(plan)
    mutate(s, p)
    assert rule in plan_fails(s, p, bd, man), rule


def test_match_action_exempts_the_bookend(base):
    story, plan, bd, man = base
    p = copy.deepcopy(plan)
    c18 = shot(p, "C18")
    c18["hero"]["poses"][0]["from"] = c18["from"] + 3
    assert "CAN-P1c" in plan_fails(story, p, bd, man)
    c18["match_action"] = True
    assert "CAN-P1c" not in plan_fails(story, p, bd, man)


def test_story_links_repoint_reveals(base):
    story, plan, bd, man = base
    s, p = copy.deepcopy(story), copy.deepcopy(plan)
    good = copy.deepcopy(s["narration"][3]["reveal_order"])
    s["narration"][3]["reveal_order"]["reveal_frame"] = 1
    assert "CAN-N3b" in plan_fails(s, p, bd, man)
    p["story_links"] = {"reveal_order": {s["narration"][3]["id"]: good}}
    assert "CAN-N3b" not in plan_fails(s, p, bd, man)


# ------------------------------------------------------------------ turn-then-change scheduling (compile.py)
def test_schedule_face_delays_the_change_past_the_turn():
    s = {"from": 100, "to": 180, "hero": {"mark": "BOW", "stance": "stand", "seed": 3,
                                          "poses": [{"pose": "look_left", "from": 112, "to": 180, "in": 12}]},
         "turn_then_change": [{"turn": {"from": 112, "to": 124, "deg": 70}, "settle_frames": 8,
                               "change": {"from": 118, "to": 130}, "emotion_from": "curious", "emotion_to": "resolve"}]}
    face = comp.schedule_face(s)
    assert face["emotion"][0] == [100, "curious"]
    f, name = face["emotion"][1]
    assert name == "resolve" and f >= 124 + 8          # delayed: never inside the head turn
    assert f - 1 in face["blinks"]                    # the thought blink


def test_schedule_face_fast_turn_blink():
    s = {"from": 0, "to": 90, "hero": {"mark": "BOW", "stance": "stand"},
         "turn_then_change": [{"turn": {"from": 20, "to": 28, "deg": 80}, "settle_frames": 6, "change": {"from": 34, "to": 44},
                               "emotion_from": "neutral", "emotion_to": "fear"}]}
    assert 26 in comp.schedule_face(s)["blinks"]       # 75 % of an 8-frame 80 deg turn


# ------------------------------------------------------------------ voice: gaps are made real and measured
def test_voice_gaps_enforce_splices_presence(tmp_path):
    from factory.run.voice import stub_timings, write_stub_wav
    from factory.voice import gaps
    story = {"narration": [{"id": "L01", "text": "One two three four.", "t0": 0.0, "t1": 1.6},
                           {"id": "L02", "text": "Five six seven eight.", "t0": 1.9, "t1": 3.4}],
             "narration_gaps": [{"id": "G1", "after_line": "L01", "start_s": 1.6, "len_s": 1.0, "purpose": "reaction", "filled_by": "room_tone"}]}
    words = stub_timings(story)
    wav = write_stub_wav(words, str(tmp_path / "n.wav"))
    wp = tmp_path / "n.words.json"
    wp.write_text(json.dumps(words))
    before = gaps.measure(story, words)[0]
    assert not before["ok"]
    rep = gaps.enforce(story, wav, str(wp), str(tmp_path / "gaps.json"))
    assert rep["ok"] and len(rep["inserts"]) == 1 and rep["gaps"][0]["measured_s"] >= 0.95
    from factory.voice import audio
    assert abs(audio.duration(wav) - (words[-1]["e"] + 0.6 + rep["inserts"][0]["dur_s"])) < 0.05
    again = gaps.enforce(story, wav, str(wp))
    assert again["inserts"] == [] and again["ok"]                   # idempotent


def test_voice_splice_is_capped():
    from factory.voice import gaps
    story = {"narration": [{"id": "L01", "text": "a b", "t0": 0, "t1": 1}, {"id": "L02", "text": "c d", "t0": 1.1, "t1": 2}],
             "narration_gaps": [{"id": "G1", "after_line": "L01", "len_s": 3.0, "purpose": "reaction", "filled_by": "room_tone"}]}
    words = [{"w": "a", "s": 0, "e": 0.4}, {"w": "b", "s": 0.5, "e": 0.9}, {"w": "c", "s": 1.1, "e": 1.5}, {"w": "d", "s": 1.6, "e": 2.0}]
    ins = gaps.plan_inserts(story, words)
    assert ins and ins[0][1] == gaps.MAX_SPLICE_S                    # never more than +0.8 s per gap


# ------------------------------------------------------------------ sound: gaps filled, words not covered
def test_designer_fills_key_sfx_gap_and_keeps_the_silence_off_the_words(base):
    from factory.sound import designer
    story, plan, bd, man = base
    ep = comp.compile_episode(plan, story, man, "/tmp")
    words = stub_words(story)
    snd = designer.design(ep, words, story=story)
    fps = snd["fps"]
    g4 = next(g for g in story["narration_gaps"] if g["id"] == "G4")
    cue = next(c for c in snd["cues"] if c.get("gap") == "G4")
    assert cue["sfx"] == "coral_crunch"
    lw = designer.line_word_frames(story, words, fps, ep["audio"]["offsetFrames"])
    nxt = lw["L07"][0]["f0"]
    assert lw["L06"][-1]["f1"] <= cue["at"] and cue["at"] + cue["dur"] * fps <= nxt
    assert g4["len_s"] >= cue["dur"] + 0.25
    sil = snd["silences"][0]
    allw = [w for ws in lw.values() for w in ws]
    assert not any(w["f0"] < sil["to"] + 5 and w["f1"] > sil["from"] - 5 for w in allw)


# ------------------------------------------------------------------ the gate on a real episode dir
def _episode_dir(tmp_path, base):
    from factory.sound import designer
    story, plan, bd, man = base
    d = tmp_path / "ep"
    (d / "audio").mkdir(parents=True)
    ep = comp.compile_episode(plan, story, man, str(d))
    words = stub_words(story)
    for n, doc in (("story.json", story), ("shotplan.json", plan), ("breakdown.json", bd), ("episode.json", ep),
                   ("audio/narration.words.json", words), ("sound.json", designer.design(ep, words, story=story))):
        (d / n).write_text(json.dumps(doc))
    return d


def test_run_all_on_the_canon_episode_has_no_fail(tmp_path, base):
    d = _episode_dir(tmp_path, base)
    r = cc.run_all(str(d / "episode.json"))
    assert not cc.failing(r), {k: v["detail"] for k, v in cc.failing(r).items()}
    assert r["_meta"]["words"] == "measured" and r["_meta"]["sound"]
    assert r["CAN-N2c"]["status"] == "PASS" and r["CAN-N2d"]["status"] == "PASS" and r["CAN-H1f"]["status"] == "PASS"
    p = subprocess.run([sys.executable, "-m", "factory.canon", "pass", "--episode", str(d), "--quiet"], cwd=ROOT,
                       capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stdout + p.stderr
    rep = json.load(open(d / "qc" / "canon_report.json"))
    assert rep["summary"]["FAIL"] == 0 and rep["rules"]["CAN-S1"]["status"] == "PASS"


def test_render_stage_needs_the_approved_lookdev(tmp_path, base):
    d = _episode_dir(tmp_path, base)
    assert cc.run_all(str(d / "episode.json"), stage="render")["CAN-T1a"]["status"] == "FAIL"
    plan = json.loads((d / "shotplan.json").read_text())
    plan["lookdev_test"].update(approved_by="t", approved_at="2026-11-22T10:00:00",
                                hash=cc.lookdev_hash(json.loads((d / "episode.json").read_text())), locks={"lut": "night"})
    (d / "shotplan.json").write_text(json.dumps(plan))
    assert cc.run_all(str(d / "episode.json"), stage="render")["CAN-T1a"]["status"] == "PASS"


def test_waterspout_fails_what_the_canon_docs_predict():
    ep = os.path.join(ROOT, "episodes", "waterspout", "episode.json")
    if not os.path.isfile(ep):
        pytest.skip("waterspout episode not in this checkout")
    r = cc.run_all(ep)
    f = fails(r)
    assert {"CAN-S1a", "CAN-S2a", "CAN-N2b", "CAN-N2f-plan", "CAN-N4e", "CAN-N4c", "CAN-P1c"} <= f
    assert "L08 'Mistake.'" in r["CAN-N4e"]["detail"] and "L06" in r["CAN-N4c"]["detail"]
    assert "H07: stance brace at 345" in r["CAN-P1c"]["detail"]
    assert "95%" in r["CAN-N2f-plan"]["detail"]
