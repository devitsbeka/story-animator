"""Job splitting + cost model (pure Python, uses the real Sentinel v2 episode)."""
import json
import os

import pytest

import jobs

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SPEC_PATH = os.path.join(REPO, "episodes", "sentinel", "episode_v2.json")


@pytest.fixture(scope="module")
def spec():
    with open(SPEC_PATH) as fh:
        return json.load(fh)


def toy(shots):
    """shots: [(id, from, to)] -> minimal spec"""
    return {"id": "toy", "fps": 30, "durationFrames": shots[-1][2],
            "shots": [{"id": i, "from": a, "to": b, "actors": [], "props": []} for i, a, b in shots]}


@pytest.mark.parametrize("quality", ["preview", "final"])
def test_sentinel_covers_every_frame_exactly_once(spec, quality):
    js = jobs.split_episode(spec, quality)
    assert jobs.check_coverage(spec, js) == spec["durationFrames"] == 2416
    frames = [f for j in js for f in range(j["frameStart"], j["frameEnd"] + 1)]
    assert sorted(frames) == list(range(spec["durationFrames"]))


def test_jobs_never_straddle_a_cut(spec):
    bounds = {s["id"]: (s["from"], s["to"] - 1) for s in spec["shots"]}
    for j in jobs.split_episode(spec, "final"):
        a, b = bounds[j["shot"]]
        assert a <= j["frameStart"] <= j["frameEnd"] <= b


def test_final_jobs_respect_target_and_min_frames(spec):
    target = 900
    js = jobs.split_episode(spec, "final", target_job_s=target)
    preset = jobs.PRESETS["final"]
    for j in js:
        assert j["frames"] >= jobs.MIN_FRAMES_PER_JOB
        # a job may exceed target only by less than one frame's worth (+ fixed overheads)
        render_s = j["estSeconds"] - jobs.JOB_OVERHEAD_S - preset["build_s"]
        assert render_s <= target + j["estSecondsPerFrame"] + 1e-6
    # expensive shots are split, cheap preview shots are not
    assert len(js) > len(spec["shots"])
    assert len(jobs.split_episode(spec, "preview")) == len(spec["shots"])


def test_chunks_inside_a_shot_are_even():
    js = jobs.split_episode(toy([("S1", 0, 100)]), "final", target_job_s=300)
    sizes = [j["frames"] for j in js]
    assert sum(sizes) == 100 and max(sizes) - min(sizes) <= 1 and len(js) > 1


def test_min_frames_caps_splitting():
    # 10 frames of a shot that "costs" 1000 s/frame would want 10 jobs; min 8 frames/job allows only 1
    js = jobs.split_episode(toy([("S1", 0, 10)]), "final", calibration={"S1": 1000}, target_job_s=100)
    assert len(js) == 1 and js[0]["frames"] == 10


def test_job_ids_are_deterministic_and_unique(spec):
    a = jobs.split_episode(spec, "final")
    b = jobs.split_episode(spec, "final")
    assert [j["jobId"] for j in a] == [j["jobId"] for j in b]
    assert len({j["jobId"] for j in a}) == len(a)
    # A01 = 75 frames x 57.2 s/frame (1 actor, 2 props, island) -> 5 jobs of 15 frames
    assert a[0]["jobId"] == "sentinel-A01-f00000-00014-final"
    assert [j["frames"] for j in a if j["shot"] == "A01"] == [15] * 5


def test_calibration_overrides_the_model(spec):
    cal = {"A01": 2.0}
    j = [x for x in jobs.split_episode(spec, "final", calibration=cal) if x["shot"] == "A01"]
    assert len(j) == 1 and j[0]["estSecondsPerFrame"] == 2.0


def test_shot_and_frame_filters(spec):
    js = jobs.split_episode(spec, "preview", shots=["B10", "C13"])
    assert {j["shot"] for j in js} == {"B10", "C13"}
    js = jobs.split_episode(spec, "preview", frame_range=(700, 705))
    assert [(j["shot"], j["frameStart"], j["frameEnd"]) for j in js] == [("B10", 700, 705)]
    with pytest.raises(ValueError):
        jobs.split_episode(spec, "preview", shots=["NOPE"])
    with pytest.raises(ValueError):
        jobs.split_episode(spec, "ultra")


def test_complexity_is_monotone():
    base = {"id": "x", "from": 0, "to": 10}
    more = dict(base, actors=[{}], props=[{}, {}], island={"asset": "island"}, fires=[[0, [1]]])
    assert jobs.shot_complexity(more) > jobs.shot_complexity(base) == 1.0
    assert jobs.shot_complexity(dict(base, actors=[{}] * 50)) == jobs.MAX_SHOT_COMPLEXITY


def test_makespan_and_estimate():
    js = [{"jobId": str(i), "estSeconds": s, "frames": 1} for i, s in enumerate([10, 10, 10, 30])]
    assert jobs.makespan(js, 1) == 60
    assert jobs.makespan(js, 2) == 30        # LPT: [30] [10,10,10]
    assert jobs.makespan(js, 10) == 30
    est = jobs.estimate(js, usd_per_gpu_hour=3.6, workers=2, boot_s=0)
    assert est["usd"] == pytest.approx(0.06) and est["frames"] == 4 and est["workers"] == 2


def test_lpt_order_longest_first():
    js = [{"jobId": "a", "estSeconds": 1}, {"jobId": "b", "estSeconds": 5}, {"jobId": "c", "estSeconds": 3}]
    assert [j["jobId"] for j in jobs.lpt_order(js)] == ["b", "c", "a"]


def test_calibration_from_manifests():
    ms = [{"shot": "A01", "render": {"secondsPerFrame": {"0": 10, "1": 20}}},
          {"shot": "A01", "render": {"secondsPerFrame": {"2": 30}}},
          {"shot": "A02", "render": {}}]
    assert jobs.calibration_from_manifests(ms) == {"A01": 20.0}


def test_bad_shot_range_rejected():
    with pytest.raises(ValueError):
        jobs.split_episode(toy([("S1", 5, 5)]), "final")
