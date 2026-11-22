"""Golden regression: numpy SSIM against known properties, metric thresholds, and the gate logic (compare / approve /
refuse 'worse' / staleness / affected) with tiny synthetic images and a fake renderer - no Blender."""
import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from factory.goldens import gate, manifest as M, metrics  # noqa: E402
from factory.goldens import __main__ as gcli  # noqa: E402


def img(seed=0, h=64, w=48):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w] / max(h, w)
    base = np.stack([0.3 + 0.4 * x, 0.2 + 0.5 * y, 0.5 - 0.3 * x * y], -1)
    base[20:40, 10:30] = [0.9, 0.7, 0.4]                      # a "hero" block with edges
    return np.clip(base + rng.normal(0, 0.01, base.shape), 0, 1)


# ------------------------------------------------------------------ SSIM
def test_ssim_identity_and_symmetry():
    a, b = img(0), img(1)
    assert metrics.ssim(a, a) == pytest.approx(1.0, abs=1e-9)
    assert metrics.ssim(a, b) == pytest.approx(metrics.ssim(b, a), abs=1e-12)
    assert 0.0 < metrics.ssim(a, b) < 1.0


def test_ssim_known_values():
    # constant images: SSIM = (2 mu_x mu_y + C1) / (mu_x^2 + mu_y^2 + C1) (variance terms equal C2/C2)
    a, b = np.full((32, 32), 0.5), np.full((32, 32), 0.25)
    c1 = 0.01 ** 2
    assert metrics.ssim(a, b) == pytest.approx((2 * 0.5 * 0.25 + c1) / (0.5 ** 2 + 0.25 ** 2 + c1), rel=1e-9)
    # contrast inversion of a zero-mean-around-0.5 pattern is strongly dissimilar
    rng = np.random.default_rng(3)
    p = 0.5 + 0.2 * rng.standard_normal((40, 40))
    assert metrics.ssim(p, 1.0 - p) < 0.0


def test_ssim_monotonic_in_noise_and_detects_local_damage():
    a = img(0)
    s = [metrics.ssim(a, np.clip(a + np.random.default_rng(9).normal(0, sd, a.shape), 0, 1)) for sd in (0.01, 0.05, 0.15)]
    assert s[0] > s[1] > s[2]
    broken = a.copy()
    broken[22:34, 12:24] = 0.0                                # a local hole (a broken hand)
    sm = metrics.ssim_map(a, broken)
    assert metrics.tile_ssim(sm) < sm.mean() < 1.0


def test_ssim_gaussian_window_matches_bruteforce():
    a, b = img(0, 24, 24), img(5, 24, 24)
    k = metrics.gaussian_kernel()
    w = np.outer(k, k)
    x, y = metrics.luma(a), metrics.luma(b)
    i, j = 3, 4
    px, py = x[i:i + 11, j:j + 11], y[i:i + 11, j:j + 11]
    mx, my = (w * px).sum(), (w * py).sum()
    vx, vy = (w * px * px).sum() - mx * mx, (w * py * py).sum() - my * my
    cxy = (w * px * py).sum() - mx * my
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    want = ((2 * mx * my + c1) * (2 * cxy + c2)) / ((mx ** 2 + my ** 2 + c1) * (vx + vy + c2))
    assert metrics.ssim_map(a, b)[i, j] == pytest.approx(want, rel=1e-9)


def test_compare_thresholds_and_metrics():
    a = img(0)
    same = metrics.compare(a, a.copy())
    assert same["pass"] and same["metrics"]["identical"] and same["metrics"]["ssim"] == 1.0
    darker = metrics.compare(a, a * 0.8)
    assert not darker["pass"] and any("luminance" in r for r in darker["reasons"])
    flat = np.full_like(a, 0.0) + a.mean((0, 1))                 # all detail gone, same mean colour
    r = metrics.compare(a, flat, {"ssim_min": 0.0, "tile_ssim_min": -1.0})
    assert not r["pass"] and any("edge density" in x for x in r["reasons"]) and r["metrics"]["rgb_delta"] < 1e-6
    assert not metrics.compare(a, a[:32])["pass"]                     # size change


# ------------------------------------------------------------------ gate logic
@pytest.fixture
def groot(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "factory" / "goldens").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "renderer.py").write_text("v1")
    (root / "src" / "hero.py").write_text("h1")
    man = {"schema": "factory.goldens/1", "defaults": {"res": "48x64", "samples": 1, "threads": 1, "engine": "CYCLES", "seed": 0, "lib": "curated", "timeout_s": 5},
           "input_groups": {"renderer": ["src/renderer.py"]},
           "goldens": {"g_scene": {"kind": "synthetic", "inputs": ["@renderer"], "rubric": "scene"},
                       "g_hero": {"kind": "synthetic", "inputs": ["src/hero.py"], "thresholds": {"ssim_min": 0.99}, "rubric": "hero"}}}
    (root / "factory" / "goldens" / "manifest.json").write_text(json.dumps(man))
    monkeypatch.setenv("FACTORY_GOLDENS_STORE", str(tmp_path / "store"))
    state = {"g_scene": img(0), "g_hero": img(1)}

    def render_fn(gid, out, r, log):
        metrics.save(state[gid], out)
    return str(root), state, render_fn


def test_first_compare_has_no_reference_then_approve_then_pass(groot):
    root, state, rf = groot
    res = gate.run_compare(root=root, render_fn=rf, use_vision=False, log=lambda m: None)
    assert not res["ok"] and {r["status"] for r in res["results"]} == {gate.NEW}
    with pytest.raises(gate.ApprovalRefused):
        gate.approve(["g_scene"], "", root=root)                      # a note is mandatory
    assert gate.approve(["g_scene", "g_hero"], "initial baseline", root=root) == ["g_scene", "g_hero"]
    base = M.load_baseline(root)["goldens"]
    assert set(base) == {"g_scene", "g_hero"} and base["g_hero"]["note"] == "initial baseline"
    assert os.path.exists(M.ref_path("g_hero", root))
    assert "initial reference" in open(os.path.join(root, "factory", "goldens", "CHANGELOG.md")).read()
    res = gate.run_compare(root=root, render_fn=rf, use_vision=False, log=lambda m: None)
    assert res["ok"] and all(r["metrics"]["identical"] for r in res["results"])
    assert os.path.exists(res["diff_sheet"])
    assert gate.staleness(root) == {"stale": [], "unbaselined": [], "fresh": ["g_hero", "g_scene"]}


def test_degradation_fails_with_diff_sheet_and_staleness(groot):
    root, state, rf = groot
    gate.render_only(root=root, render_fn=rf, log=lambda m: None)
    gate.approve(["g_scene", "g_hero"], "baseline", root=root)
    (root_hero := os.path.join(root, "src", "hero.py")) and open(root_hero, "w").write("h2")   # change an input
    assert gate.staleness(root)["stale"] == ["g_hero"]
    assert M.affected(["src/hero.py"], root) == ["g_hero"] and M.affected(["src/renderer.py"], root) == ["g_scene"]
    broken = state["g_hero"].copy()
    broken[20:40, 10:30] = 0.05                                       # the hero block goes black
    state["g_hero"] = broken
    res = gate.run_compare(["g_hero"], root=root, render_fn=rf, use_vision=False, log=lambda m: None)
    r = res["results"][0]
    assert not res["ok"] and r["status"] == gate.FAIL and r["reasons"]
    from PIL import Image
    sheet = Image.open(res["diff_sheet"])
    assert sheet.width >= 3 * 48                                       # ref | cand | diff
    assert gate.staleness(root)["stale"] == ["g_hero"]                # failing compare does not refresh it


def test_vision_worse_is_never_approved_and_better_can_be(groot):
    root, state, rf = groot
    gate.render_only(root=root, render_fn=rf, log=lambda m: None)
    gate.approve(["g_scene", "g_hero"], "baseline", root=root)
    state["g_scene"] = np.clip(state["g_scene"] * 1.3, 0, 1)

    class Fake:
        def __init__(self, verdict):
            self.verdict = verdict
            self.messages = self

        def create(self, **kw):
            assert kw["messages"][0]["content"][0]["type"] == "image"
            v = self.verdict

            class R:
                stop_reason = "end_turn"
                content = [type("B", (), {"type": "text", "text": json.dumps({"verdict": v, "confidence": 0.9, "reason": "test"})})()]
            return R()
    res = gate.run_compare(["g_scene"], root=root, render_fn=rf, vision_client=Fake("worse"), log=lambda m: None)
    assert res["results"][0]["verdict"]["verdict"] == "worse"
    with pytest.raises(gate.ApprovalRefused, match="WORSE"):
        gate.approve(["g_scene"], "looks fine to me", root=root)
    gate.approve(["g_scene"], "human override after review", root=root, accept_worse=True)
    assert M.load_baseline(root)["goldens"]["g_scene"]["accepted_worse"] is True
    state["g_scene"] = np.clip(state["g_scene"] * 0.9, 0, 1)
    res = gate.run_compare(["g_scene"], root=root, render_fn=rf, vision_client=Fake("better"), log=lambda m: None)
    assert res["results"][0]["status"] == gate.FAIL and res["results"][0]["verdict"]["verdict"] == "better"
    assert gate.approve(["g_scene"], "improved grade", root=root) == ["g_scene"]


def test_vision_unavailable_without_key(groot, monkeypatch, tmp_path):
    from factory.goldens import vision
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(vision, "SECRETS", str(tmp_path / "none.env"))
    a = tmp_path / "a.png"
    metrics.save(img(0), str(a))
    assert vision.judge(str(a), str(a), "x")["verdict"] == "unavailable"
    env = tmp_path / "s.env"
    env.write_text("OTHER=1\nexport ANTHROPIC_API_KEY='sk-test'\n")
    assert vision.ensure_key(str(env)) and os.environ["ANTHROPIC_API_KEY"] == "sk-test"


def test_approve_refuses_stale_candidate(groot):
    root, state, rf = groot
    gate.render_only(["g_hero"], root=root, render_fn=rf, log=lambda m: None)
    open(os.path.join(root, "src", "hero.py"), "w").write("h3")
    with pytest.raises(gate.ApprovalRefused, match="different inputs"):
        gate.approve(["g_hero"], "x", root=root)


def test_render_failure_is_a_fail_not_a_crash(groot):
    root, state, rf = groot

    def boom(gid, out, r, log):
        raise RuntimeError("blender died")
    res = gate.run_compare(["g_scene"], root=root, render_fn=boom, use_vision=False, log=lambda m: None)
    assert not res["ok"] and "render failed" in res["results"][0]["reasons"][0]


def test_repo_manifest_is_complete():
    m = M.load()
    g = m["goldens"]
    assert {"hero_turnaround", "hero_pose_sheet", "hero_face_sheet", "yacht_turnaround"} <= set(g)
    assert sum(k.startswith("sentinel_") for k in g) == 6 and sum(k.startswith("kit_") for k in g) == 4
    assert all(x["res"] == "360x640" and x["engine"] == "CYCLES" and x["threads"] <= 2 for x in g.values())
    assert set(M.affected(["cloud/blender/cloudrig_adapter.py"])) >= {"hero_turnaround", "hero_face_sheet", "sentinel_C13"}
    assert M.affected(["README.md"]) == []
    assert gcli.main(["affected", "--files", "assets/props/yacht.glb"]) == 0
