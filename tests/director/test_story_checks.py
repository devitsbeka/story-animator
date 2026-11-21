import pytest

from conftest import deep, load, rules
from docu_factory import make_docuseries
from factory.director import checks, text


def test_sentinel_story_passes_with_logged_overrides(story):
    rep = checks.check_story(story)
    assert rep.ok, rep.blocking
    # the delivered Sentinel script really misses these house heuristics; they are logged, not hidden
    assert {"N-1-hook", "R-2", "N-10"} <= set(rep.to_dict()["overridden"])
    # and it passes the structural ones
    for r in ("H-1", "H-6", "S1", "R-3", "R-5", "N-4", "N-1", "N-6", "R-6", "H-7", "R-beats-order"):
        assert r in rep.passed, r


def test_recorded_first_attempt_fails_hard_on_unsourced_number():
    rep = checks.check_story(load("develop.1.json"))
    assert not rep.ok
    hard = {i["rule"] for i in rep.blocking if i["severity"] == "HARD"}
    assert hard == {"N-4"}


def test_lexicons_come_from_the_recipe():
    assert "drown" in text.lex("threat") and "but" in text.lex("tension") and "finally" in text.lex("end-signal")


@pytest.mark.parametrize("mutate,rule", [
    (lambda s: s["narration"][4].update(text=s["narration"][4]["text"] + " And then they waited."), "R-3-and-then"),
    (lambda s: s["beats"][3].update(link=None), "R-3"),
    (lambda s: s["narration"][9].update(text="In conclusion, " + s["narration"][9]["text"]), "R-5"),
    (lambda s: s["spine"].update(because_of_that=["Because of that, one thing."]), "SCHEMA"),
    (lambda s: s["core_question"].update(answer_line="L05"), "H-6"),
    (lambda s: s["facts"][4].update(numbers=[]), "N-4"),
    (lambda s: s["resolution"].update(hero_action=" "), "S7"),
    (lambda s: s["narration"][3].update(beat="B99"), "INTEGRITY.beat_refs"),
    (lambda s: s["beats"].reverse(), "R-beats-order"),
    (lambda s: s["narration"].__setitem__(0, {**s["narration"][0], "t0": 5.0, "t1": 4.0}), "INTEGRITY.line_times"),
])
def test_hard_failures_block(story, mutate, rule):
    s = deep(story)
    mutate(s)
    rep = checks.check_story(s)
    assert not rep.ok and rule in rules(rep), rep.blocking


def test_heur_failure_blocks_unless_overridden(story):
    s = deep(story)
    s["overrides"] = [o for o in s["overrides"] if o["rule"] != "N-10"]
    rep = checks.check_story(s)
    assert rules(rep) == {"N-10"}
    assert "Fix every item below" in rep.retry_feedback() and "N-10" in rep.retry_feedback()


def test_override_cannot_excuse_a_hard_rule(story):
    s = deep(story)
    s["facts"][2].pop("numbers")
    s["overrides"].append({"rule": "N-4", "reason": "trying to skip sourcing a number"})
    assert "N-4" in rules(checks.check_story(s))


def test_numbers_skip_step_ordinals():
    assert text.numbers_in("Step two: do NOT go ashore.") == []
    assert text.numbers_in("channel sixteen in 1981 for thousands of years") == ["sixteen", "1981", "thousands"]


# ------------------------------------------------------------------ docuseries
def test_docuseries_story_passes():
    rep = checks.check_story(make_docuseries())
    assert rep.ok, rep.blocking
    for r in ("DOC-chapters", "DOC-cold-open", "DOC-tease", "DOC-short.CH1", "N-1", "R-2"):
        assert r in rep.passed


@pytest.mark.parametrize("mutate,rule", [
    (lambda s: s.update(chapters=s["chapters"][:4]), "DOC-chapters"),
    (lambda s: s.update(tease_next=""), "DOC-tease"),
    (lambda s: s["cold_open"].update(t1=120.0), "DOC-cold-open"),
    (lambda s: s["chapters"][1]["short_candidate"].update(out=s["chapters"][1]["short_candidate"]["in"] + 150), "DOC-short.CH2"),
    (lambda s: s["chapters"][2].update(short_candidate=None), "DOC-shorts-per-chapter"),
    (lambda s: s["narration"][40].pop("chapter"), "DOC-line-chapters"),
    (lambda s: s["chapters"][0]["spine"].update(payoff=" "), "DOC-spine.CH1"),
])
def test_docuseries_failures(mutate, rule):
    s = make_docuseries()
    mutate(s)
    assert rule in rules(checks.check_story(s))


def test_docuseries_uses_documentary_pace():
    s = make_docuseries()
    for ln in s["narration"]:          # deliver the same words 20% faster (~3.2 w/s): too fast for a docuseries
        ln["t0"], ln["t1"] = round(ln["t0"] * 0.8, 2), round(ln["t1"] * 0.8, 2)
    assert "N-1" in rules(checks.check_story(s))
