"""factory.run: the whole chain on Sentinel offline (heavy steps stubbed), resume, approval gate, QC retry loop,
local/farm render paths, batch + budget. The real Blender previs smoke test is opt-in: RUN_BLENDER_SMOKE=1."""
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import FAKE_BLENDER, IDEA, ROOT
from factory.run import batch, pipeline, render, voice
from factory.run.pipeline import Options, Pipeline, failing_shots, plan_fix

QUICK_STUBS = frozenset({"previs", "render", "finish", "mix"})
SENTINEL = os.path.join(ROOT, "episodes", "sentinel", "episode_v4.json")


def opts(tmp_path, **kw):
    base = dict(idea=IDEA, offline=True, stubs=QUICK_STUBS, auto_approve=True, episodes_dir=str(tmp_path / "eps"))
    base.update(kw)
    return Options(**base)


def cli(*args, cwd=ROOT):
    return subprocess.run([sys.executable, "-m", "factory.run", *args], cwd=cwd, capture_output=True, text=True, timeout=900)


def rule(rid, section, status="fail", measured=None, detail=None, hard=False):
    return {"id": rid, "section": section, "status": status, "measured": measured, "detail": detail, "hard": hard}


# ------------------------------------------------------------------------------------------- end to end (CLI)
def test_offline_sentinel_chain_cli_then_resume(tmp_path):
    eps = tmp_path / "eps"
    r = cli(IDEA, "--format", "short", "--style", "pixar_night_survival", "--render", "local", "--quality", "preview",
            "--offline", "--stub", "previs,render,finish", "--auto-approve", "--episodes-dir", str(eps), "--episode-id", "sen")
    assert r.returncode in (0, 4), r.stdout[-3000:] + r.stderr[-3000:]
    d = eps / "sen"
    run = json.loads((d / "run.json").read_text())
    assert run["status"] in ("published", "returned")
    assert [run["stages"][s]["status"] for s in pipeline.ORDER] == ["done"] * len(pipeline.ORDER)
    for f in ("story.json", "breakdown.json", "manifest.json", "shotplan.json", "episode.json", "audio/narration.mp3",
              "audio/narration.words.json", "sound.json", "audio/mix_v1.m4a", "audio/mix_v1.report.json",
              "boards/contact_sheet.png", "boards/animatic.mp4", "plates/plates_manifest.json", "final/episode.mp4",
              "qc/report.json", "qc/report.iter0.json"):
        assert (d / f).exists(), f
    ep = json.loads((d / "episode.json").read_text())
    assert ep["id"] == "sen" and len(ep["shots"]) == 33
    assert ep["audio"]["narration"].endswith("sen/audio/narration.mp3")
    assert run["stages"]["voice"]["info"]["provider"] == "reference:episodes/sentinel"
    assert run["stages"]["sound"]["info"]["mix"] == "ffmpeg"          # the real mixer ran
    # cost/time accounting per stage
    assert set(run["cost"]["byStage"]) == set(pipeline.ORDER) and run["cost"]["totalUSD"] == 0.0
    assert run["time"]["totalSeconds"] > 0 and all(run["stages"][s]["seconds"] >= 0 for s in pipeline.ORDER)
    assert run["qc"]["decision"] in ("PUBLISH", "RETURN") and run["qc"]["iterations"]
    assert "episode sen:" in r.stdout and "QC decision" in r.stdout
    # resume: nothing re-runs
    attempts = {s: run["stages"][s]["attempts"] for s in pipeline.ORDER}
    r2 = cli("--resume", "--episode-id", "sen", "--episodes-dir", str(eps))
    assert r2.returncode == r.returncode, r2.stdout + r2.stderr
    run2 = json.loads((d / "run.json").read_text())
    assert {s: run2["stages"][s]["attempts"] for s in pipeline.ORDER} == attempts
    # starting the same episode again without --resume is refused
    r3 = cli(IDEA, "--offline", "--episodes-dir", str(eps), "--episode-id", "sen")
    assert r3.returncode == 2 and "--resume" in r3.stderr
    st = cli("status", "--episode-id", "sen", "--episodes-dir", str(eps))
    assert st.returncode == 0 and "qc" in st.stdout


def test_approval_gate_pauses_then_resumes(tmp_path):
    eps = tmp_path / "eps"
    common = ["--offline", "--stub", "previs,render,finish,mix", "--episodes-dir", str(eps), "--episode-id", "gate"]
    r = cli(IDEA, *common)
    assert r.returncode == 3, r.stdout + r.stderr
    run = json.loads((eps / "gate" / "run.json").read_text())
    assert run["status"] == "awaiting_approval"
    assert run["stages"]["previs"]["status"] == "awaiting_approval"
    assert run["stages"]["render"]["status"] == "pending" and run["stages"]["sound"]["status"] == "done"
    assert (eps / "gate" / "boards" / "contact_sheet.png").exists() and (eps / "gate" / "boards" / "animatic.mp4").exists()
    # resume without approval: still waiting
    assert cli("--resume", "--episode-id", "gate", "--episodes-dir", str(eps)).returncode == 3
    a = cli("approve", "--episode-id", "gate", "--episodes-dir", str(eps), "--note", "boards ok", "--by", "tester")
    assert a.returncode == 0 and "APPROVED" in a.stdout
    r2 = cli("--resume", "--episode-id", "gate", "--episodes-dir", str(eps))
    assert r2.returncode in (0, 4), r2.stdout + r2.stderr
    run = json.loads((eps / "gate" / "run.json").read_text())
    assert run["approval"]["by"] == "tester" and run["stages"]["qc"]["status"] == "done"
    assert run["stages"]["develop"]["attempts"] == 1          # stages 1-6 were not redone


# ------------------------------------------------------------------------------------------- QC retry loop
def _plates_mtime(d, shot):
    p = os.path.join(d, "plates", shot)
    return {f: os.path.getmtime(os.path.join(p, f)) for f in os.listdir(p) if f.endswith(".png")}


def test_auto_fix_rerenders_failing_shots_once_then_publishes(tmp_path):
    calls = []

    def fake_qc(pipe, it):
        calls.append(it)
        if it == 0:
            return {"decision": "AUTO_FIX", "engagement_score": 80, "rules": [
                rule("TQ-PLATE-BLACK", "TECH", measured={"black": ["A03/0130"]}, detail="A03 has black frames")]}
        return {"decision": "PUBLISH", "engagement_score": 90, "rules": [rule("H-1", "HOOK", "pass")]}
    pipe = Pipeline(opts(tmp_path), "fix", log=lambda m: None, hooks={"qc": fake_qc})
    before = {}

    orig = pipe.stage_render

    def spy(t0, shots=None):
        if shots:
            before["A03"] = _plates_mtime(pipe.dir, "A03")
            before["A04"] = _plates_mtime(pipe.dir, "A04")
        return orig(t0, shots=shots)
    pipe.stage_render = spy
    doc = pipe.run()
    assert calls == [0, 1]
    assert doc["status"] == "published" and doc["qc"]["decision"] == "PUBLISH"
    it0 = doc["qc"]["iterations"][0]
    assert it0["fix"] == {"stages": [7], "shots": ["A03"], "rules": ["TQ-PLATE-BLACK"]}
    assert _plates_mtime(pipe.dir, "A04") == before["A04"]                      # untouched
    assert all(v > before["A03"][k] for k, v in _plates_mtime(pipe.dir, "A03").items())  # re-rendered
    assert os.path.exists(os.path.join(pipe.dir, "qc", "report.iter1.json"))


def test_auto_fix_is_tried_once_then_returns(tmp_path):
    calls = []

    def fake_qc(pipe, it):
        calls.append(it)
        return {"decision": "AUTO_FIX", "engagement_score": 75, "rules": [
            rule("P-3.cut_on_word", "PACING", detail={"off_by_frames": {"A07": 4.0}})]}
    pipe = Pipeline(opts(tmp_path), "fix2", log=lambda m: None, hooks={"qc": fake_qc})
    doc = pipe.run()
    assert calls == [0, 1]
    assert doc["status"] == "returned" and doc["qc"]["decision"] == "RETURN"
    fix = doc["qc"]["iterations"][0]["fix"]
    assert fix["stages"] == [4, 7] and fix["shots"] == ["A07"]
    assert doc["stages"]["direct"]["attempts"] == 1                       # re-direct runs inside stage 9
    assert os.path.exists(os.path.join(pipe.dir, "_llm", "direct.1.json"))
    assert doc["qc"]["returnReport"]["failing"] == ["P-3.cut_on_word"]


def test_return_stops_with_report(tmp_path):
    def fake_qc(pipe, it):
        return {"decision": "RETURN", "engagement_score": 50, "hard_failures": ["H-1"],
                "rules": [rule("H-1", "HOOK", hard=True)]}
    pipe = Pipeline(opts(tmp_path), "ret", log=lambda m: None, hooks={"qc": fake_qc})
    doc = pipe.run()
    assert doc["status"] == "returned" and len(doc["qc"]["iterations"]) == 1
    assert doc["qc"]["returnReport"]["hard_failures"] == ["H-1"] and "stage 1/4" in doc["qc"]["returnReport"]["next"]


def test_failing_shots_and_plan():
    ids = ["A01a", "A01b", "A03", "A30", "C21"]
    rep = {"rules": [rule("H1", "FRAMING", measured="20/24", detail=["C21"]),
                     rule("TQ-X", "TECH", measured={"x": "A01b/0042"}),
                     rule("ok", "TECH", status="pass", detail="A30")],
           "details": {"framing": [{"shot": "A03", "status": "fail"}, {"shot": "A30", "status": "pass"}]}}
    assert failing_shots(rep, ids) == ["A01b", "A03", "C21"]
    assert plan_fix(rep, {"shots": [{"id": i} for i in ids]})["stages"] == [4, 7]
    tech = {"rules": [rule("TQ-X", "TECH", measured="A30")]}
    assert plan_fix(tech, {"shots": [{"id": i} for i in ids]}) == {"stages": [7], "shots": ["A30"], "rules": ["TQ-X"]}


# ------------------------------------------------------------------------------------------- budget / failures
def test_budget_ceiling_stops_the_run(tmp_path):
    o = opts(tmp_path, budget=0.5)
    pipe = Pipeline(o, "bud", log=lambda m: None)
    pipe.st.add_cost("develop", 0.0)
    orig = pipe.stage_breakdown

    def pricey(t0):
        res = orig(t0)
        res["usd"] = 0.75
        return res
    pipe.stage_breakdown = pricey
    doc = pipe.run()
    assert doc["status"] == "budget_exceeded" and "budget" in doc["error"]
    assert doc["stages"]["breakdown"]["costUSD"] == 0.75 and doc["stages"]["direct"]["status"] == "pending"


def test_failed_stage_is_recorded_and_resume_retries(tmp_path):
    pipe = Pipeline(opts(tmp_path), "boom", log=lambda m: None)
    pipe.stage_sound = lambda t0: (_ for _ in ()).throw(RuntimeError("mixer exploded"))
    doc = pipe.run()
    assert doc["status"] == "failed" and doc["stages"]["sound"]["status"] == "failed"
    assert "mixer exploded" in doc["stages"]["sound"]["error"] and doc["stages"]["finish"]["status"] == "pending"
    pipe2 = Pipeline(opts(tmp_path), "boom", resume=True, log=lambda m: None)
    doc2 = pipe2.run()
    assert doc2["stages"]["sound"]["status"] == "done" and doc2["stages"]["sound"]["attempts"] == 2
    assert doc2["stages"]["develop"]["attempts"] == 1 and doc2["status"] in ("published", "returned")


def test_from_stage_resets_descendants(tmp_path):
    pipe = Pipeline(opts(tmp_path, stubs=frozenset(QUICK_STUBS)), "fs", log=lambda m: None,
                    hooks={"qc": lambda p, i: {"decision": "PUBLISH", "rules": []}})
    pipe.run()
    p2 = Pipeline(opts(tmp_path), "fs", resume=True, from_stage="render", log=lambda m: None,
                  hooks={"qc": lambda p, i: {"decision": "PUBLISH", "rules": []}})
    assert p2.st.stage("render")["status"] == "pending" and p2.st.stage("qc")["status"] == "pending"
    assert p2.st.stage("previs")["status"] == "done"
    doc = p2.run()
    assert doc["stages"]["render"]["attempts"] == 2 and doc["stages"]["previs"]["attempts"] == 1


# ------------------------------------------------------------------------------------------- stage units
def test_local_render_shards_jobs_and_runs_workers(tmp_path):
    spec = json.load(open(SENTINEL))
    spec["shots"] = spec["shots"][:3]
    sp = tmp_path / "ep.json"
    sp.write_text(json.dumps(spec))
    res = render.render_local(spec, str(sp), str(tmp_path / "plates"), "preview", shots=None, workers=2,
                              blender=FAKE_BLENDER, log_dir=str(tmp_path / "logs"), log=lambda m: None)
    js = render.split(spec, "preview")
    assert res["jobs"] == len(js) and res["missingCount"] == 0 and not res["failedJobs"]
    n = sum(s["to"] - s["from"] for s in spec["shots"])
    assert res["frames"] == n and len(list((tmp_path / "plates").glob("*/*.png"))) == n
    cmd = render.blender_cmd(js[0], str(sp), "/x", "blender", 2)
    assert cmd[:5] == ["blender", "-b", "--factory-startup", "-P", render.RENDER_PY]
    assert ["--start", str(js[0]["frameStart"])] == cmd[cmd.index("--start"):cmd.index("--start") + 2] and "--skip-existing" in cmd


class FakeFarm:
    def __init__(self, plates_src):
        self.ticks, self.plates_src, self.submitted = 0, plates_src, []

    def submit(self, specs, quality, budget=None, shots=None):
        self.submitted.append({"quality": quality, "budget": budget, "shots": shots})
        return [{"runId": "run-1", "jobs": 4, "estimate": {"usd": 1.25}}]

    def tick(self, rid):
        self.ticks += 1
        return "RUNNING" if self.ticks < 3 else "RENDERED"

    def status(self, rid):
        return {"spentUsd": 1.1, "frames": "10/10"}

    def pull_plates(self, rid, root):
        return {"plates": self.plates_src, "missing": []}


def test_farm_render_submits_watches_and_pulls(tmp_path):
    spec = json.load(open(SENTINEL))
    seen = []
    farm = FakeFarm(str(tmp_path / "pulled"))
    res = render.render_farm(spec, str(tmp_path), str(tmp_path), "final", budget=5.0, farm=farm, poll_s=0,
                             on_submit=lambda rid, sub: seen.append(rid), log=lambda m: None, sleep=lambda s: None)
    assert res["runId"] == "run-1" and res["usd"] == 1.1 and res["plates"].endswith("pulled") and seen == ["run-1"]
    assert farm.submitted == [{"quality": "final", "budget": 5.0, "shots": None}] and farm.ticks == 3
    # resume with a known run id: no second submit
    farm2 = FakeFarm(str(tmp_path / "pulled"))
    render.render_farm(spec, str(tmp_path), str(tmp_path), "final", run_id="run-1", farm=farm2, poll_s=0,
                       log=lambda m: None, sleep=lambda s: None)
    assert farm2.submitted == []
    est = render.farm_estimate(spec, "final")
    assert est["usd"] > 0 and est["jobs"] >= len(spec["shots"])


def test_pipeline_farm_mode_records_cost(tmp_path):
    farm = FakeFarm(None)
    pipe = Pipeline(opts(tmp_path, render="farm", stubs=frozenset({"previs", "finish", "mix"}), farm_poll_s=0), "farm",
                    log=lambda m: None, hooks={"farm": farm, "qc": lambda p, i: {"decision": "PUBLISH", "rules": []}})
    farm.plates_src = os.path.join(pipe.dir, "pulled_plates")
    render.stub_plates(json.load(open(SENTINEL)) | {"shots": []}, farm.plates_src)
    orig_pull = farm.pull_plates

    def pull(rid, root):
        render.stub_plates(json.load(open(os.path.join(pipe.dir, "episode.json"))), farm.plates_src)
        return orig_pull(rid, root)
    farm.pull_plates = pull
    import time as _t
    pipeline_sleep = render.time.sleep
    render.time.sleep = lambda s: None
    try:
        doc = pipe.run()
    finally:
        render.time.sleep = pipeline_sleep
    assert doc["status"] == "published", doc.get("error")
    assert doc["stages"]["render"]["costUSD"] == 1.1 and doc["cost"]["totalUSD"] == 1.1
    assert doc["stages"]["render"]["farmRunId"] == "run-1"
    assert doc["stages"]["render"]["info"]["plates"].endswith("pulled_plates")
    assert _t is not None


def test_stub_voice_timings_follow_lines(tmp_path):
    story = {"id": "nothing-here-xyz", "narration": [{"text": "[excited] You are alone. Night falls!", "t0": 0.5, "t1": 2.5},
                                                    {"text": "Then the reef.", "t0": 3.0, "t1": 4.0}]}
    sp = tmp_path / "story.json"
    sp.write_text(json.dumps(story))
    res = voice.synthesize(str(sp), str(tmp_path), offline=True)
    words = json.load(open(res["words"]))
    assert res["provider"] == "stub" and [w["w"] for w in words] == ["You", "are", "alone.", "Night", "falls!", "Then", "the", "reef."]
    assert words[0]["s"] == 0.5 and words[4]["e"] <= 2.5 and words[5]["s"] == 3.0
    assert all(a["e"] <= b["s"] for a, b in zip(words, words[1:]))
    assert os.path.getsize(res["audio"]) > 48000 * 2 * 4


def test_voice_module_interface_is_used_online(tmp_path, monkeypatch):
    import types
    calls = []

    def synthesize(story_json, out_dir):
        calls.append((story_json, out_dir))
        a, w = os.path.join(out_dir, "vo.mp3"), os.path.join(out_dir, "vo.words.json")
        open(a, "wb").write(b"x")
        open(w, "w").write("[]")
        return {"audio": a, "words": w}
    monkeypatch.setitem(sys.modules, "factory.voice", types.SimpleNamespace(synthesize=synthesize))
    sp = tmp_path / "story.json"
    sp.write_text(json.dumps({"id": "z", "narration": [{"text": "abc def", "t0": 0, "t1": 1}]}))
    res = voice.synthesize(str(sp), str(tmp_path), offline=False)
    assert res["provider"] == "factory.voice" and calls == [(str(sp), str(tmp_path / "audio"))] and res["usd"] > 0


# ------------------------------------------------------------------------------------------- batch
def test_batch_runs_ideas_concurrently_under_a_budget(tmp_path):
    ideas = tmp_path / "ideas.txt"
    ideas.write_text("# two ideas\n" + IDEA + "\nshort|Night dive gone wrong: your torch dies at 30 metres\n")
    items = batch.read_ideas(str(ideas))
    assert len(items) == 2 and items[1]["format"] == "short"
    # online-sized estimates (~$1.92 each) against a $2 ceiling: the second idea must wait for the first to finish
    doc = batch.run_batch(items, ["--offline", "--stub", "previs,render,finish,mix", "--auto-approve"], str(tmp_path / "eps"),
                          offline=False, max_parallel=2, budget=2.0, log=lambda m: None, cwd=ROOT)
    st = [it["status"] for it in doc["items"]]
    assert all(s in ("published", "returned") for s in st), [open(it["log"]).read()[-2000:] for it in doc["items"]]
    assert doc["items"][0]["allowance"] == 2.0
    assert os.path.exists(doc["file"]) and json.load(open(doc["file"]))["items"][1]["spentUSD"] == 0.0
    for it in doc["items"]:
        assert os.path.exists(os.path.join(tmp_path, "eps", it["episodeId"], "run.json"))


def test_batch_parallel_without_budget(tmp_path, monkeypatch):
    seen = []

    class P:
        returncode = 4

    def fake_run(cmd, stdout=None, stderr=None, cwd=None):
        import time
        seen.append(("start", cmd[3], time.time()))
        time.sleep(0.5)
        seen.append(("end", cmd[3], time.time()))
        return P()
    monkeypatch.setattr(batch.subprocess, "run", fake_run)
    items = [{"idea": f"idea number {i}", "format": None} for i in range(4)]
    doc = batch.run_batch(items, [], str(tmp_path / "eps"), max_parallel=2, log=lambda m: None)
    assert [it["status"] for it in doc["items"]] == ["returned"] * 4
    starts = sorted(t for k, _, t in seen if k == "start")
    assert starts[1] - starts[0] < 0.3 and starts[2] - starts[0] >= 0.45     # 2 at a time


# ------------------------------------------------------------------------------------------- real Blender smoke
@pytest.mark.skipif(os.environ.get("RUN_BLENDER_SMOKE") != "1", reason="real Blender previs (~2 min/keyframe): RUN_BLENDER_SMOKE=1")
def test_real_previs_keyframes_two_shots(tmp_path):
    from factory.run import previs
    spec = json.load(open(SENTINEL))
    spec["shots"] = spec["shots"][:2]
    spec["durationFrames"] = spec["shots"][-1]["to"]
    sp = tmp_path / "ep.json"
    sp.write_text(json.dumps(spec))
    os.environ.setdefault("LIBRARY_STORE", "/tmp/empty_lib")
    os.makedirs(os.environ["LIBRARY_STORE"], exist_ok=True)
    info = previs.run(spec, str(sp), str(tmp_path / "boards"), audio=os.path.join(ROOT, "episodes/sentinel/audio/narration.mp3"),
                      res="72x128", samples=2, workers=1, log=print)
    assert info["keys"] == 2 and not info["missing"], info
    from PIL import Image
    for s in spec["shots"]:
        im = Image.open(tmp_path / "boards" / "keys" / s["id"] / f"{previs.key_frame(s):04d}.png")
        assert im.size == (72, 128)
    assert os.path.getsize(info["animatic"]) > 1000 and os.path.getsize(info["contact_sheet"]) > 1000
    shutil.copytree(tmp_path / "boards", "/tmp/run_orchestrator/smoke_boards", dirs_exist_ok=True)
