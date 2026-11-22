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
        obj = CP.object_subject(TILTED, [0.3, 2.4, -4.9], size=0.3)   # in the open cockpit (-3.0 is inside the cabin wall)
        return fn(f0, f1, obj)
    return fn(f0, f1, hero)


def shot_of(out, f0, f1):
    return {"id": "T", "from": f0, "to": f1 + 1, "camera": out["camera"], "yacht": TILTED, "direction": out["direction"]}


def test_catalog_complete():
    names = catalog_names()
    assert len(names) == 36, names
    assert set(names) == set(CP.PRESETS) - CP.CANON_PRESETS, set(names) ^ (set(CP.PRESETS) - CP.CANON_PRESETS)


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
        cex = d.get("centre_exempt") or []
        for f in range(cf, f1 + 1, 3):
            if any(w0 <= f <= w1 for w0, w1 in cex):
                continue
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


# >>> polish_camera
LEVEL = {"x": 0.0, "z": 0.0, "heading": 0.0, "lights": [[0, 0]]}


def test_jay_profile_frames_whole_face():
    """Jay's 0.55 m head: CU = forehead-to-chin with the cap inside, eyes on the 0.38 line, MS waist up."""
    prof = G.hero_profile("hero_v4")
    if prof is None:
        return
    assert 0.84 < prof.rest["eye"] < 0.89 and 0.66 < prof.rest["chin"] < 0.73
    hero = CP.hero_subject(LEVEL, [0.0, 1.9, 4.7], 0.0, profile=prof, acting_stance="stand")
    actor = {"asset": "hero_v4", "local": [0.0, 1.9, 4.7], "rotY": 0.0, "height": 1.8, "perf": {"stance": [[-10000, "stand"]]}}
    for size in ("MS", "MCU", "CU"):
        out = CP.dolly_in(0, 30, hero, size=(size, size), lens=CP.LENS_BY_SIZE[size])
        rep = SV.analyse_shot({"width": 1080, "height": 1920, "fps": 30}, shot_of(out, 0, 30) | {"yacht": LEVEL, "actors": [actor]})
        assert rep["size"] == size, (size, rep["size"], rep["frame_h"])
        assert abs(rep["eye_y_key"] - G.EYE_LINE) < 0.03, (size, rep["eye_y_key"])
        assert rep["key_top_y"] >= 0.0 and rep["key_chin_y"] <= 1.0 and not rep["face_crop"], (size, rep["key_top_y"], rep["face_crop"])


def test_collision_avoidance_on_the_real_yacht():
    """v3's A02 framing (front-left of the helm at 35 mm) puts the lens inside the cabin; the presets now move it out."""
    P = G.yacht_proxy()
    if P is None:
        return
    assert P.sdf([-0.09, 2.80, -2.69]) < 0          # v5 A04 lens: inside the (hollow) cabin
    assert P.sdf([0.0, 3.0, -5.0]) > 0.3            # open cockpit air
    hero = CP.hero_subject(LEVEL, [0.55, 1.42, -4.3], 0.0, profile=G.hero_profile("hero_v4"), acting_stance="helm")
    CP.COLLIDE = False
    raw = CP.arc_track(75, 118, hero, size=("MS", "MS"), az=(50, 35), el=4, lens=35)
    CP.COLLIDE = True
    fixed = CP.arc_track(75, 118, hero, size=("MS", "MS"), az=(50, 35), el=4, lens=35)
    body = lambda k: G.YachtFrame(LEVEL, k["f"]).world_to_body(G.YachtFrame(LEVEL, k["f"]).cam_to_world(k["cam"]))
    assert min(P.sdf(body(k)) for k in raw["camera"]["keys"]) < CP.CLEARANCE
    assert min(P.sdf(body(k)) for k in fixed["camera"]["keys"]) >= CP.CLEARANCE - 1e-6
    assert fixed["direction"]["collision_fix"]["keys_moved"] > 0
# <<< polish_camera


# >>> craft canon camera rules
def test_impact_handheld_escape_and_late_catch_up():
    """CAN-H1: the subject leaves the frame for exactly escape_frames, the operator reacts lag_frames late."""
    prof = G.hero_profile("hero_v4")
    hero = CP.hero_subject(LEVEL, [0.0, 1.9, 4.7], 0.0, profile=prof, acting_stance="stand")
    actor = {"asset": "hero_v4", "local": [0.0, 1.9, 4.7], "rotY": 0.0, "height": 1.8, "perf": {"stance": [[-10000, "stand"]]}}
    for esc, lag in ((6, 5), (4, 3), (9, 6)):
        out = CP.impact_handheld(0, 50, hero, impact=15, escape_frames=esc, lag_frames=lag, size="MS", az=(30, 20), el=8)
        ih = out["direction"]["impact_handheld"]
        assert ih["escape_frames"] == esc, ih
        s = shot_of(out, 0, 50) | {"yacht": LEVEL, "actors": [actor]}
        m = SV.analyse_shot({"width": 1080, "height": 1920, "fps": 30}, s)["impact"]
        assert abs(m["escape_frames"] - esc) <= 1 and abs(m["lag_frames"] - lag) <= 1 and m["recentred_at"], (esc, lag, m)
    # a strong shake without the reaction is a locked-off impact -> CAN-H1 fails; with it, it passes
    locked = CP.handheld_documentary(0, 50, hero, size="MS")
    locked["camera"]["shakes"] = [{"at": 15, "px": 14, "tau": 2.2}]
    ok = CP.impact_handheld(0, 50, hero, impact=15)
    for out, want in ((locked, "fail"), (ok, "pass")):
        a = SV.analyse_shot({"width": 1080, "height": 1920, "fps": 30}, shot_of(out, 0, 50) | {"yacht": LEVEL, "actors": [actor]})
        r = next(r for r in SV.canon_rules({}, [a]) if r["id"] == "CAN-H1")
        assert r["status"] == want, r


def test_reserved_close_up_and_geography():
    """CAN-C2: an unreserved hero CU fails, the reserved one passes. CAN-C1: v6 establishes every location."""
    prof = G.hero_profile("hero_v4")
    hero = CP.hero_subject(LEVEL, [0.0, 1.9, 4.7], 0.0, profile=prof, acting_stance="stand")
    actor = {"asset": "hero_v4", "local": [0.0, 1.9, 4.7], "rotY": 0.0, "height": 1.8, "perf": {"stance": [[-10000, "stand"]]}}
    out = CP.dolly_in(0, 30, hero, size=("CU", "CU"), lens=75)
    s = shot_of(out, 0, 30) | {"yacht": LEVEL, "actors": [actor]}
    a = SV.analyse_shot({"width": 1080, "height": 1920, "fps": 30}, s)
    assert next(r for r in SV.canon_rules({}, [a]) if r["id"] == "CAN-C2")["status"] == "fail"
    s["direction"] = dict(s["direction"], reserved_close_up="decides")
    a = SV.analyse_shot({"width": 1080, "height": 1920, "fps": 30}, s)
    assert next(r for r in SV.canon_rules({}, [a]) if r["id"] == "CAN-C2")["status"] == "pass"
    p6 = os.path.join(ROOT, "episodes/sentinel/episode_v6.json")
    if os.path.exists(p6):
        SV.load_coast(ROOT)
        st = {r["id"]: r["status"] for r in SV.validate(json.load(open(p6)))["rules"]}
        assert st["CAN-C1"] == st["CAN-C2"] == st["CAN-H1"] == "pass", st
# <<< craft canon camera rules


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
        # since polish_camera the real-geometry collision rule (COL) and the camera canon rules also flag v3; the
        # mesh-proxy rule must still catch exactly the in-cabin A02/A04 cameras
        prox = [r for r in fails if r["id"] == "PROXY"]
        assert prox and {"A02", "A04"} <= set(prox[0]["shots"]), fails
        c17 = next(x for x in r3["shots"] if x["id"] == "C17")
        assert c17["anchors"]["island"] > 0 and c17["ots"]
        if G.yacht_proxy() is not None:      # polish_camera: v3's A02/A04 lenses sit in the cabin (brown / black frames)
            col = next(r for r in r3["rules"] if r["id"] == "COL")
            assert col["status"] == "fail" and {"A02", "A04"} <= set(col["shots"]), col
    p6 = os.path.join(ROOT, "episodes/sentinel/episode_v6.json")
    if os.path.exists(p6):
        r6 = SV.validate(json.load(open(p6)))
        assert r6["summary"]["fail"] == 0, [r for r in r6["rules"] if r["status"] == "fail"]


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
