from factory.qc import narration, pacing
from helpers import hero_shot, make_episode, words_from


def _by(rules):
    return {r["id"]: r for r in rules}


def test_good_hook_passes():
    w = words_from("Your boat sinks in 90 seconds. What do you do?", t0=0.1)
    ep = make_episode(words=w, frames=600)
    by = _by(narration.narration_checks(ep))
    assert by["H-1.first_word"]["status"] == "pass"
    assert by["H-1.proposition"]["status"] == "pass"
    assert by["H-1.banned_opener"]["status"] == "pass"
    assert by["H-7"]["status"] == "pass"


def test_bad_hook_and_end_signal():
    w = words_from("Hey guys welcome to the channel today we look at boats. Finally that's it thanks for watching friends. " * 3, t0=0.5)
    ep = make_episode(words=w, frames=1800)
    by = _by(narration.narration_checks(ep))
    assert by["H-1.first_word"]["status"] == "fail"
    assert by["H-1.proposition"]["status"] == "fail"
    assert by["H-1.banned_opener"]["status"] == "fail"
    assert by["R-5"]["status"] == "fail" and by["R-5"]["hard"]


def test_sentences_split():
    s = narration.sentences(words_from("One two. Three four five! Six?"))
    assert [len(x) for x in s] == [2, 3, 1]


def test_pacing_asl_and_gap():
    shots = [hero_shot(f"S{i}", i * 60, (i + 1) * 60) for i in range(10)]  # 10 x 2.0 s = 20 s
    ep = make_episode(shots=shots)
    by = _by(pacing.pacing_checks(ep))
    assert by["P-1.asl_overall"]["status"] == "pass"
    assert by["P-2.visual_change_gap"]["status"] == "pass"
    assert by["C9.shot_duration"]["status"] == "pass"
    long_ = [hero_shot("L", 0, 300)]  # one 10 s shot
    by = _by(pacing.pacing_checks(make_episode(shots=long_)))
    assert by["P-1.asl_overall"]["status"] == "fail"
    assert by["P-2.visual_change_gap"]["status"] == "fail"
    assert by["C9.shot_duration"]["detail"]["too_long"] == ["L"]
    assert by["R-9.dead_air"]["status"] == "fail"


def test_cut_on_word():
    shots = [hero_shot("A", 0, 30), hero_shot("B", 30, 60), hero_shot("C", 60, 90)]
    ep = make_episode(shots=shots, words=words_from("go now", t0=1.0, dt=1.0))  # starts at 30 f and 60 f
    assert _by(pacing.pacing_checks(ep))["P-3.cut_on_word"]["status"] == "pass"
    ep = make_episode(shots=shots, words=words_from("go now", t0=1.3, dt=1.0))  # 9 f late
    assert _by(pacing.pacing_checks(ep))["P-3.cut_on_word"]["status"] == "fail"


def test_late_narration_does_not_crash():
    ep = make_episode(words=words_from("Late start here.", t0=4.0), frames=300)
    by = _by(narration.narration_checks(ep))
    assert by["H-7"]["status"] == "fail" and by["H-1.first_word"]["status"] == "fail"
