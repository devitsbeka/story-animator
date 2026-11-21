"""Pure-Python parts of cloud/blender/scatter_lod.py (camera samples, frustum + screen size, tier choice)."""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "cloud", "blender"))
import scatter_lod as L  # noqa: E402


def cam_looking(pos, fwd, fov_v_deg=40.0, aspect=1080 / 1920):
    """A camera sample at pos looking along fwd (Z up, no roll) with a vertical fov."""
    f = [c / math.sqrt(sum(x * x for x in fwd)) for c in fwd]
    up0 = (0.0, 0.0, 1.0)
    r = (f[1] * up0[2] - f[2] * up0[1], f[2] * up0[0] - f[0] * up0[2], f[0] * up0[1] - f[1] * up0[0])
    rn = math.sqrt(sum(x * x for x in r))
    r = [x / rn for x in r]
    u = (r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0])
    # Blender camera matrix columns: right, up, -forward, position
    m = [[r[i], u[i], -f[i], pos[i]] for i in range(3)] + [[0, 0, 0, 1]]
    sensor = 24.0
    lens = (sensor / 2) / math.tan(math.radians(fov_v_deg) / 2)
    return L.camera_sample(m, lens, sensor, aspect)


def test_camera_sample_axes_and_fov():
    s = cam_looking((0, 0, 0), (0, 1, 0), 40.0)
    assert s["fwd"] == pytest.approx((0, 1, 0))
    assert s["up"] == pytest.approx((0, 0, 1))
    assert s["tan_v"] == pytest.approx(math.tan(math.radians(20)))
    assert s["tan_h"] == pytest.approx(s["tan_v"] * 1080 / 1920)


def test_project_size_scales_with_distance():
    s = cam_looking((0, 0, 0), (0, 1, 0), 40.0)
    ins1, px1, d1 = L.project(s, (0, 100, 0), 10.0)
    ins2, px2, d2 = L.project(s, (0, 400, 0), 10.0)
    assert ins1 and ins2
    assert d1 == pytest.approx(100) and d2 == pytest.approx(400)
    assert px1 == pytest.approx(4 * px2)
    # 20 m object at 100 m, 40 deg fov, 1920 px: 20 / (2*100*tan20) * 1920
    assert px1 == pytest.approx(20 / (200 * math.tan(math.radians(20))) * 1920)


def test_project_culls_behind_and_beside():
    s = cam_looking((0, 0, 0), (0, 1, 0), 40.0)
    assert not L.project(s, (0, -50, 0), 5.0)[0]          # behind
    assert not L.project(s, (200, 100, 0), 5.0)[0]        # far to the right of a narrow 9:16 view
    assert L.project(s, (0, 0, 0), 5.0)[0]                # camera inside the bounds
    # just outside the edge: kept by the margin, culled without it
    th = s["tan_h"]
    x = 100 * th * 1.1 + 1.0
    assert L.project(s, (x, 100, 0), 0.5, margin=0.2)[0]
    assert not L.project(s, (x, 100, 0), 0.5, margin=0.0)[0]


def test_classify_tiers():
    assert L.classify(False, 1000, 10) is None
    assert L.classify(True, L.HERO_PX + 1, 500) == "full"
    assert L.classify(True, 10, L.HERO_DIST - 1) == "full"          # hero zone by distance
    assert L.classify(True, L.HERO_PX - 1, 500) == "mid"
    assert L.classify(True, L.FAR_PX + 1, 500) == "mid"
    assert L.classify(True, L.FAR_PX - 1, 900) == "far"


def test_plan_tiers_takes_the_max_over_the_shot():
    # a dolly from 2 km to 30 m: the tree is "full" because of the closest frame, and a tree behind the start
    # position that the camera never turns to is culled
    samples = [cam_looking((0, -d, 0), (0, 1, 0), 40.0) for d in (2000, 1000, 30)]
    tiers = L.plan_tiers([((0, 0, 0), 15.0), ((0, -3000, 0), 15.0), ((0, 3000, 0), 15.0)], samples)
    assert tiers[0] == "full"
    assert tiers[1] is None
    assert tiers[2] == "far"
    assert L.summarize(tiers) == {"cull": 1, "full": 1, "mid": 0, "far": 1}


def test_frame_samples_stride():
    assert L.frame_samples(10, 14) == [10, 11, 12, 13, 14]
    fr = L.frame_samples(0, 999, 48)
    assert fr[0] == 0 and fr[-1] == 999 and len(fr) <= 49
    assert all(b > a for a, b in zip(fr, fr[1:]))


def test_bounding_radius_holds_the_bbox():
    meta = {"bbox_min": [-2.4, -2.4, 0.0], "bbox_max": [2.4, 2.4, 5.0]}
    r = L.bounding_radius(meta, 3.0)
    assert r == pytest.approx(3.0 * math.sqrt(2.4 ** 2 * 2 + 25))


def test_enabled_env(monkeypatch):
    monkeypatch.setenv("ISLAND_LOD", "0")
    assert not L.enabled()
    monkeypatch.setenv("ISLAND_LOD", "1")
    assert L.enabled()
    monkeypatch.delenv("ISLAND_LOD")
    assert L.enabled()


def test_load_meta_rejects_stale_or_incomplete(tmp_path):
    d = tmp_path / "lod" / "tree"
    d.mkdir(parents=True)
    (d / "lod.json").write_text('{"version": %d, "tiers": {"far": {"blend": "tree_far.blend"}}}' % L.BAKE_VERSION)
    assert L.load_meta(str(tmp_path), "tree") is None       # blend missing
    (d / "tree_far.blend").write_bytes(b"x")
    assert L.load_meta(str(tmp_path), "tree")["tiers"]["far"]["blend"] == "tree_far.blend"
    (d / "lod.json").write_text('{"version": -1, "tiers": {}}')
    assert L.load_meta(str(tmp_path), "tree") is None       # old bake version
    assert L.load_meta(str(tmp_path), "nothing") is None


def test_extent_drives_size_and_radius_drives_culling():
    s = cam_looking((0, 0, 0), (0, 1, 0), 40.0)
    _, px_r, _ = L.project(s, (0, 100, 0), 10.0)
    _, px_e, _ = L.project(s, (0, 100, 0), 10.0, extent=5.0)
    assert px_e == pytest.approx(px_r / 4)


def test_numpy_and_pure_paths_agree(monkeypatch):
    import random
    rnd = random.Random(7)
    samples = [cam_looking((rnd.uniform(-50, 50), rnd.uniform(-400, -100), rnd.uniform(1, 30)),
                           (rnd.uniform(-0.5, 0.5), 1, rnd.uniform(-0.2, 0.1)), rnd.uniform(25, 60)) for _ in range(12)]
    spheres = [((rnd.uniform(-600, 600), rnd.uniform(-300, 900), rnd.uniform(0, 20)), rnd.uniform(1, 30), rnd.uniform(1, 20))
               for _ in range(400)]
    fast = L.plan_stats(spheres, samples)
    import builtins
    real_import = builtins.__import__

    def no_numpy(name, *a, **k):
        if name == "numpy":
            raise ImportError
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_numpy)
    slow = L.plan_stats(spheres, samples)
    assert [a[0] for a in fast] == [b[0] for b in slow]
    for a, b in zip(fast, slow):
        assert a[1] == pytest.approx(b[1], rel=1e-6, abs=1e-6)
        assert a[2] == pytest.approx(b[2])
    assert any(a[0] for a in fast) and not all(a[0] for a in fast)


def test_margin_only_objects_stay_cheap():
    # a big object just outside the frame edge: kept (margin) but never counted as big -> far tier
    s = cam_looking((0, 0, 0), (0, 1, 0), 40.0)
    x = 100 * s["tan_h"] * 1.1 + 1.0
    (inside, px, _), = L.plan_stats([((x, 100, 0), 0.5, 80.0)], [s])
    assert inside and px == 0.0
    assert L.plan_tiers([((x, 100, 0), 0.5, 80.0)], [s]) == ["far"]
