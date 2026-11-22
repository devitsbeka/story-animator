#!/usr/bin/env python3
"""Deterministic camera repair (no LLM, no money): before a shot that failed the per-shot checks goes back to the
director, try to solve it with geometry. Lesson L027.

For each failing shot, candidate rigid moves of ALL its camera keys are tried in order of how little they change the
shot's intent (keep the look target, keep the lens):
  0. framing failures only (FRAME-CROP/EYES): tilt the aim, open the lens 6-18 %, or step back and re-aim
  1. dolly toward the look target by 10..45 %   (pulls the camera out of a wall it sits just behind)
  2. raise the camera by 0.25..1.0 m            (lifts it over rails / consoles / the cabin roof edge)
  3. orbit about the look target by +-10..40 deg (swings it out of a bulkhead)
  4. combinations of 1 + 2
The first candidate on which EVERY per-shot rule that the shot passed or failed now passes (COLLIDE, VIS,
FRAME-CROP, FRAME-EYES) is kept. Shots that no candidate fixes are returned for the director re-direct.

    fixed, still = repair_episode(ep, failing_ids)
"""
import copy
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shot_checks  # noqa: E402

FIXABLE = {"COLLIDE", "VIS", "FRAME-CROP", "FRAME-EYES"}


def _move(shot, dolly=0.0, rise=0.0, orbit_deg=0.0, tilt=0.0, widen=0.0):
    s = copy.deepcopy(shot)
    a = math.radians(orbit_deg)
    for k in s["camera"]["keys"]:
        if tilt:
            k["look"] = [k["look"][0], round(k["look"][1] + tilt, 4), k["look"][2]]
        if widen:
            k["fov"] = round(min(100.0, k["fov"] * (1.0 + widen)), 3)
        cx, cy, cz = k["cam"]
        lx, ly, lz = k["look"]
        dx, dz = cx - lx, cz - lz
        if orbit_deg:
            dx, dz = dx * math.cos(a) - dz * math.sin(a), dx * math.sin(a) + dz * math.cos(a)
        f = 1.0 - dolly
        k["cam"] = [round(lx + dx * f, 4), round(ly + (cy - ly) * f + rise, 4), round(lz + dz * f, 4)]
    return s


def candidates(rules=()):
    if rules & {"FRAME-CROP", "FRAME-EYES"} and not rules & {"COLLIDE"}:
        # framing: re-aim (tilt the look point; +y lowers the head in frame) or open the lens a little, keep the angle
        for t in (0.04, -0.04, 0.08, -0.08, 0.12, -0.12, 0.18, -0.18, 0.25, -0.25):
            yield {"tilt": t}
        for w in (0.06, 0.12, 0.18):
            yield {"widen": w}
            for t in (0.08, -0.08, 0.15, -0.15):
                yield {"widen": w, "tilt": t}
        # too tight for the rig's big head: step back (negative dolly) and re-aim at the head
        for d in (-0.2, -0.4, -0.6, -0.8):
            for t in (0.1, 0.2, 0.3, 0.4, 0.0, -0.1):
                yield {"dolly": d, "tilt": t}
        return
    for d in (0.10, 0.18, 0.26, 0.35, 0.45):
        yield {"dolly": d}
    for r in (0.25, 0.5):
        yield {"rise": r}
    for o in (10, -10, 20, -20, 30, -30, 40, -40):
        yield {"orbit_deg": o}
    for d in (0.18, 0.35):
        for r in (0.25, 0.5):
            yield {"dolly": d, "rise": r}
    for r in (0.75, 1.0):   # last resort: a higher angle
        yield {"rise": r}
    for t in (0.08, -0.08, 0.15, -0.15):
        for r in (0.25, 0.5):
            yield {"tilt": t, "rise": r}
    # boxed in (cockpit under the hardtop): lower the camera, swing wider, or combine a swing with a dolly
    for r in (-0.2, -0.4):
        yield {"rise": r}
        for d in (0.18, 0.35):
            yield {"rise": r, "dolly": d}
    for o in (50, -50, 60, -60, 75, -75, 90, -90):
        yield {"orbit_deg": o}
        for d in (0.18, 0.35):
            yield {"orbit_deg": o, "dolly": d}


def _fails(ep, shot):
    return {f["rule"] for f in shot_checks.check_shot(ep, shot) if f["status"] == "fail"}


def repair_shot(ep, shot):
    """-> (fixed_shot or None, move dict or None)"""
    before = _fails(ep, shot)
    if not before or not before <= FIXABLE:
        return None, None
    for mv in candidates(before):
        s2 = _move(shot, **mv)
        if not _fails(ep, s2):
            return s2, mv
    return None, None


def repair_episode(ep, failing_ids):
    """Repairs in place. -> (fixed {shot_id: move}, still_failing [shot ids])"""
    fixed, still = {}, []
    idx = {s["id"]: i for i, s in enumerate(ep["shots"])}
    for sid in failing_ids:
        i = idx.get(sid)
        if i is None:
            still.append(sid)
            continue
        s2, mv = repair_shot(ep, ep["shots"][i])
        if s2 is None:
            still.append(sid)
        else:
            s2.setdefault("direction", {})["camera_repair"] = mv   # recorded so a reviewer can see what geometry changed
            ep["shots"][i] = s2
            fixed[sid] = mv
    return fixed, still
