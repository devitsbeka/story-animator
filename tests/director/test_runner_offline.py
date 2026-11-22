import json
import os
import shutil
import subprocess
import sys

import pytest

from director_helpers import FX, ROOT
from docu_factory import make_docuseries
from factory.director import checks, librarian
from factory.director.llm import FixtureClient, LLMError
from factory.director.runner import Runner, StageFailed

IDEA = "Solo sailor's yacht runs aground on North Sentinel's reef at night: what do you actually do?"
WORDS = os.path.join(ROOT, "episodes", "sentinel", "audio", "narration.words.json")


def _runner(out, fixtures=FX, fmt="short", **kw):
    client = FixtureClient(fixtures)
    ph = librarian.PolyHavenSearch(os.path.join(FX, "polyhaven_search.json"))
    with open(WORDS) as fh:
        words = json.load(fh)
    return Runner(str(out), client, IDEA, fmt, ph=ph, words=words, log=lambda *a: None, **kw), client


def test_full_chain_offline(tmp_path):
    run, client = _runner(tmp_path / "ep")
    out = run.run()
    d = tmp_path / "ep"
    for f in ("idea.json", "story.json", "breakdown.json", "manifest.json", "shotplan.json", "episode.json",
              "reports/develop.json", "reports/library.json", "reports/direct.json", "_llm/develop.1.json", "_llm/develop.2.json"):
        assert (d / f).exists(), f
    assert all(r.ok for r in run.reports.values())
    ep = json.loads((d / "episode.json").read_text())
    # the canon-directed attempt (fixtures/sentinel/build_canon.py): 33 shots + the reserved close-up R16, gaps re-timed
    assert checks.check_episode(ep).ok and len(ep["shots"]) == 34 and ep["durationFrames"] == 2612
    assert out["manifest"]["summary"]["REUSE"] >= 20
    # stage 1 needed two retries: the second request carried the validator's errors back (N-4), the third the
    # film-craft canon's (the recorded pre-canon story has no threats / knowledge timeline / gaps)
    dev = [c for c in client.calls if c["stage"] == "develop"]
    assert len(dev) == 3
    fb = dev[1]["messages"][-1]["content"]
    assert dev[1]["messages"][-2]["role"] == "assistant" and "[HARD N-4]" in fb and "overrides" in fb
    fb3 = dev[2]["messages"][-1]["content"]
    assert "[HARD CAN-S1a]" in fb3 and "[HARD CAN-N2b]" in fb3
    assert "FILM-CRAFT CANON" in dev[0]["system"][0]["text"] and "CAN-S2" in dev[0]["system"][0]["text"]
    assert len([c for c in client.calls if c["stage"] == "direct"]) == 2
    # system prompt: one cached block that embeds the recipe checklists
    sys_blocks = dev[0]["system"]
    assert len(sys_blocks) == 1 and sys_blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "**Checklist: Hook**" in sys_blocks[0]["text"] and "Story spine" in sys_blocks[0]["text"]
    direct = next(c for c in client.calls if c["stage"] == "direct")
    assert "POSES:" in direct["system"][0]["text"] and "<manifest.json>" in direct["messages"][0]["content"]
    assert direct["schema"]["properties"]["shots"]["type"] == "array"
    rep = json.loads((d / "reports/develop.1.json").read_text())
    assert rep["ok"] is False and rep["meta"]["model"] == "fixture"


def test_resume_reuses_valid_artifacts(tmp_path):
    run, _ = _runner(tmp_path / "ep")
    run.run()
    run2, client2 = _runner(tmp_path / "ep")
    run2.run()
    assert client2.calls == []                      # nothing regenerated
    run3, client3 = _runner(tmp_path / "ep", force=True)
    run3.run(("develop",))
    assert len(client3.calls) == 3


def test_offline_without_a_corrected_response_fails_cleanly(tmp_path):
    fx = tmp_path / "fx"
    fx.mkdir()
    shutil.copy(os.path.join(FX, "develop.1.json"), fx / "develop.1.json")
    run, _ = _runner(tmp_path / "ep", fixtures=str(fx))
    with pytest.raises(LLMError, match="develop attempt 2"):
        run.run()
    run, _ = _runner(tmp_path / "ep2", fixtures=str(fx), max_attempts=1)
    with pytest.raises(StageFailed) as e:
        run.run()
    assert e.value.stage == "develop" and "N-4" in str(e.value)


def test_format_mismatch_is_a_hard_failure(tmp_path):
    run, _ = _runner(tmp_path / "ep", fmt="docuseries", max_attempts=2)
    with pytest.raises(StageFailed) as e:
        run.run(("develop",))
    assert "FORMAT" in {i["rule"] for i in e.value.report.blocking}


def test_docuseries_develop_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_CANON", "0")   # docu_factory's synthetic story predates the canon (the minidoc fixture carries it)
    fx = tmp_path / "fx"
    fx.mkdir()
    (fx / "develop.1.json").write_text(json.dumps(make_docuseries()))
    run, client = _runner(tmp_path / "ep", fixtures=str(fx), fmt="docuseries")
    out = run.run(("develop",))
    assert out["story"]["format"] == "docuseries" and len(out["story"]["chapters"]) == 5
    assert "documentary register" in client.calls[0]["system"][0]["text"]


def test_cli_offline_end_to_end(tmp_path):
    out = tmp_path / "cli_ep"
    r = subprocess.run([sys.executable, "-m", "factory.director", "run", "--idea", IDEA, "--format", "short", "--out", str(out),
                        "--offline", "--words", WORDS], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK: develop pass, breakdown pass, library pass, direct pass" in r.stdout
    v = subprocess.run([sys.executable, "-m", "factory.director", "validate", "--dir", str(out)], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert v.returncode == 0, v.stdout + v.stderr
    assert v.stdout.count("PASS") == 5
