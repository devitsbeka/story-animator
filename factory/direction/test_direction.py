#!/usr/bin/env python3
"""Tests for camera_presets + shot_validator (plain asserts; run with `python3 factory/direction/test_direction.py`
or pytest). No Blender needed: the projection uses the renderer's own camera maths (camgeo)."""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import camera_presets as CP  # noqa: E402
import camgeo as G  # noqa: E402
import shot_validator as SV  # noqa: E402

CATALOG = os.path.join(ROOT, "atlas/ATLAS_CINEMA_AGENT_KIT/03_CATALOGS/camera_presets.yaml")
TILTED = {"x": 10.0, "z": -20.0, "heading": 0.7, "lights": [[0, 0]], "pitch": -0.10, "roll": 0.14, "sink": 0.25}


def catalog_names():
    names, on = [], False
    for line in open(CATALOG):
        if line.startswith("preset_names:"):
            on = True
            continue
        if on:
            if line.startswith("- "):
                names.append(line[2:].strip())
            elif line.strip():
                break
    return names


def call(name, f0, f1, hero, far):
    fn = CP.PRESETS[name]
    if name in ("over_shoulder", "pov", "high_reveal", "push_reveal"):
        return fn(f0, f1, hero, far)
    if name == "whip_pan":
        return fn(f0, f1, far, hero)
    if name in ("pan_left", "pan_right"):
        a, b = hero.point(f0, "feet"), hero.point(f0, "head_top")
        a = G.add(a, [-1.5, 0, 0]); b = G.add(b, [1.5, 0, 0])
        return fn(f0, f1, hero, a, b)
    if name == "architecture_walkthrough":
        S = hero.point(f0, None)
        return fn(f0, f1, hero, [G.add(S, [6, 1, -8]), G.add(S, [7, 1, -2]), G.add(S, [5, 1, 4])])
    if name in ("product_turntable", "extreme_closeup"):
        obj = CP.object_subject(TILTED, [0.3, 2.4, -3.0], size=0.3)
        return fn(f0, f1, obj)
    return fn(f0, f1, hero)


def shot_of(out, f0, f1):
    return {"id": "T", "from": f0, "to": f1 + 1, "camera": out["camera"], "yacht": TILTED, "direction": out["direction"]}


def test_catalog_complete():
    names = catalog_names()
    assert len(names) == 36, names
    assert set(names) == set(CP.PRESETS), set(names) ^ set(CP.PRESETS)


def test_lens_roundtrip():
    for mm in (18, 24, 35, 50, 85, 135):
        assert abs(G.vfov_to_lens(G.lens_to_vfov(mm)) - mm) < 1e-9
    # 35 mm equivalent on 9:16 is a ~56.6 deg vertical fov; 50 mm ~41.3
    assert 56 < G.lens_to_vfov(35) < 57.5 and 41 < G.lens_to_vfov(50) < 42


def test_yacht_transforms_invert():
    for f in (0, 50):
        yf = G.YachtFrame(TILTED, f)
        p = [1.2, 3.4, -5.6]
        assert max(abs(a - b) for a, b in zip(yf.world_to_body(yf.body_to_world(p)), p)) < 1e-9
        assert max(abs(a - b) for a, b in zip(yf.world_to_cam(yf.cam_to_world(p)), p)) < 1e-9


def test_all_presets():
    hero = CP.hero_subject(TILTED, [0.0, 1.9, 4.7], 0.0)
    far = CP.world_subject([300.0, 3.0, 900.0], height=40, name="island")
    f0, f1 = 100, 160
    for name in CP.PRESETS:
        out = call(name, f0, f1, hero, far)
        cam, d = out["camera"], out["direction"]
        ks = cam["keys"]
        assert d["preset"] == name and d["motivation"], name
        assert ks[0]["f"] == f0 and ks[-1]["f"] == f1, name
        assert all(0 < b["f"] - a["f"] <= 3 for a, b in zip(ks, ks[1:])), name
        assert all(k["ease"] == "linear" for k in ks), name
        assert all(math.isfinite(v) for k in ks for v in k["cam"] + k["look"] + [k["fov"]]), name
        assert all(0 < k["fov"] < 120 for k in ks), name
        # the camera moves (path or look or lens)
        moved = (math.dist(ks[0]["cam"], ks[-1]["cam"]) > 0.02 or math.dist(ks[0]["look"], ks[-1]["look"]) > 0.02
                 or abs(math.log(ks[0]["fov"] / ks[-1]["fov"])) > 0.01)
        assert moved, name
        # subject dead centre through the renderer's camera (no handheld / drift)
        s = shot_of(out, f0, f1)
        a = SV.analyse_shot({"width": 1080, "height": 1920, "fps": 30}, s)
        cf = d.get("centre_from", f0)
        for f in range(cf, f1 + 1, 3):
            c, l, fov, roll = G.camera_world(s, f, jitter=False)
            S = SV.track_at(d["subject"]["track"], f)
            x, y, dep = G.project(c, l, roll, fov, 1080 / 1920, S)
            assert dep > 0, (name, f)
            if not (d["pov"] or d["insert"]):
                assert abs(x - 0.5) < 0.02, (name, f, x)
        assert not a["collisions"] or name in ("low_reveal",), (name, a["collisions"])


def test_hero_framing_sizes_and_eyes():
    hero = CP.hero_subject(TILTED, [0.0, 1.42, -4.6], math.pi)
    for size in ("WS", "MS", "MCU", "CU"):
        out = CP.dolly_in(0, 30, hero, size=(size, size), lens=CP.LENS_BY_SIZE[size])
        rep = SV.analyse_shot({"width": 1080, "height": 1920, "fps": 30}, shot_of(out, 0, 30) | {"actors": [
            {"asset": "hero", "local": [0.0, 1.42, -4.6], "rotY": math.pi, "height": 1.8}]})
        assert rep["size"] == size, (size, rep["size"], rep["frame_h"])
        if size in ("MCU", "CU"):
            assert 0.30 <= rep["eye_y_key"] <= 0.45, (size, rep["eye_y_key"])


def test_far_target_survives_tilted_yacht():
    """A yacht-space OTS at an island 900 m away: the reef tilt must not throw the look off the target."""
    hero = CP.hero_subject(TILTED, [0.0, 1.9, 4.7], 0.0)
    far = CP.world_subject([300.0, 3.0, 900.0], height=40, name="island")
    out = CP.over_shoulder(0, 30, hero, far)
    assert out["camera"]["space"] == "yacht"
    s = shot_of(out, 0, 30)
    c, l, fov, roll = G.camera_world(s, 15, jitter=False)
    x, y, d = G.project(c, l, roll, fov, 9 / 16, [300.0, 3.0, 900.0])
    assert abs(x - 0.5) < 1e-3 and abs(y - 0.5) < 1e-3, (x, y)


def test_validator_flags_bad_and_passes_v3():
    v2 = json.load(open(os.path.join(ROOT, "episodes/sentinel/episode_v2.json")))
    SV.load_coast(ROOT)
    r2 = SV.validate(v2)
    st2 = {r["id"]: r["status"] for r in r2["rules"]}
    assert st2["CTX"] == "fail" and st2["C8"] == "fail" and st2["H1"] == "fail"
    p3 = os.path.join(ROOT, "episodes/sentinel/episode_v3.json")
    if os.path.exists(p3):
        r3 = SV.validate(json.load(open(p3)))
        # quality_gate: v3 passed every shot-language rule, but its A02/A04 cameras sit inside the cabin (L012,
        # rendered brown/black) - the mesh-proxy rule must catch exactly that
        fails = [r for r in r3["rules"] if r["status"] == "fail"]
        assert [r["id"] for r in fails] == ["PROXY"], fails
        assert {"A02", "A04"} <= set(fails[0]["shots"])
        c17 = next(x for x in r3["shots"] if x["id"] == "C17")
        assert c17["anchors"]["island"] > 0 and c17["ots"]


if __name__ == "__main__":
    n = 0
    for k, fn in list(globals().items()):
        if k.startswith("test_") and callable(fn):
            fn()
            n += 1
            print("ok", k)
    print(f"{n} tests passed")


def test_impact_handheld_layer_escapes_and_recovers():
    """canon CAN-H1: the subject leaves the centre after the impact, the aim error peaks lag frames late, re-centred by
    impact + lag + recover; the validator exempts that window (H1f)."""
    hero = CP.hero_subject(TILTED, [0.0, 1.9, 4.7], 0.0)
    f0, f1, imp = 100, 160, 115
    out = CP.LAYERS["impact_handheld"](f0, f1, hero, base="handheld_documentary", impact_frame=imp, escape_frames=3,
                                       lag_frames=5, recover_frames=10, amplitude_deg=8)
    d = out["direction"]
    assert d["impact_window"] == [imp, imp + 18] and d["motivation"] == "impact"
    s = shot_of(out, f0, f1)
    xs = {}
    for f in range(f0, f1 + 1):
        c, l, fov, roll = G.camera_world(s, f, jitter=False)
        x, y, dep = G.project(c, l, roll, fov, 1080 / 1920, SV.track_at(d["subject"]["track"], f))
        xs[f] = abs(x - 0.5)
    assert xs[imp - 1] < 0.03 and xs[imp + 3] > 0.08                       # escapes within escape_frames
    assert max(range(imp, imp + 19), key=lambda f: xs[f]) in range(imp + 3, imp + 7)   # peak ~ lag frames late
    assert xs[imp + 19] < 0.03                                              # re-found
    a = SV.analyse_shot({"width": 1080, "height": 1920, "fps": 30}, s)
    assert a["impact_exempt"] == [imp, imp + 18] and a["max_dx"] < 0.08    # centring judged outside the window only
