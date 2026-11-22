"""Run all checks and write the scored report (ENGAGEMENT section 8.2).

score = 30*Hook + 20*Retention + 15*Narration + 15*Pacing + 10*Captions + 10*Sound, each the
pass rate of the evaluated rules of that section (skipped rules are left out; a section with
no evaluated rule is left out and the weights renormalised, reported as `coverage`).
Gate: PUBLISH if Hook == 100%, score >= 85, no HARD fail and the TECH gate passes;
AUTO_FIX if 70 <= score < 85 (max 2 iterations) or only TECH fails; RETURN (Stage 1/4) if
score < 70 or any HARD rule fails; INCOMPLETE when no scored section was evaluated
(e.g. a plates-only run: read the TECH gate).
"""
from __future__ import annotations

import datetime
import json
import os
import time

from . import captions, episode as episode_mod, framing, narration, pacing, plates, video, video_rules, vision
from .common import FAIL, GATE_SECTIONS, PASS, SECTION_WEIGHTS, SKIP, WARN, rnd, rule

RECIPES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "recipes")


def section_rates(rules):
    rates = {}
    for sec in list(SECTION_WEIGHTS) + list(GATE_SECTIONS):
        ev = [r for r in rules if r["section"] == sec and r["status"] != SKIP]
        passed = sum(r["status"] in (PASS, WARN) for r in ev)
        rates[sec] = {"evaluated": len(ev), "passed": passed, "failed": len(ev) - passed,
                      "skipped": sum(1 for r in rules if r["section"] == sec and r["status"] == SKIP),
                      "pass_rate": rnd(passed / len(ev), 4) if ev else None}
    return rates


def score(rules, iteration=0):
    rates = section_rates(rules)
    used = {s: w for s, w in SECTION_WEIGHTS.items() if rates[s]["pass_rate"] is not None}
    wsum = sum(used.values())
    sc = 100.0 * sum(w * rates[s]["pass_rate"] for s, w in used.items()) / wsum if wsum else 0.0
    hard_fail = [r["id"] for r in rules if r["hard"] and r["status"] == FAIL]
    tech_ok = rates["TECH"]["failed"] == 0
    hook_ok = rates["HOOK"]["pass_rate"] == 1.0
    if not wsum:
        decision = "INCOMPLETE"  # nothing scoreable (e.g. plates only): read the TECH gate
    elif hard_fail or sc < 70:
        decision = "RETURN"
    elif hook_ok and sc >= 85 and tech_ok:
        decision = "PUBLISH"
    else:
        decision = "AUTO_FIX"
    if decision == "AUTO_FIX" and iteration >= 2:
        decision = "RETURN"
    return {
        "engagement_score": rnd(sc, 2),
        "coverage": rnd(wsum / sum(SECTION_WEIGHTS.values()), 3),
        "sections": rates,
        "hard_failures": hard_fail,
        "gates": {"hook_100": hook_ok, "score_ge_85": sc >= 85, "score_ge_70": sc >= 70, "no_hard_fail": not hard_fail, "tech": tech_ok,
                  "framing": rates["FRAMING"]["failed"] == 0},
        "decision": decision,
        "iteration": iteration,
    }


def run(episode=None, spec=None, video_path=None, plates_dir=None, out_dir=None, run_vision=None, partial_plates=False,
        iteration=0, vision_client=None, log=print):
    t0 = time.time()
    rules, details, inputs = [], {}, {}
    ep = episode_mod.load(episode, spec) if (episode or spec) else None
    if ep:
        inputs["episode"] = os.path.relpath(ep.path)
        out_dir = out_dir or os.path.join(ep.ep_dir, "qc")
        log(f"[qc] episode {ep.data.get('id')} {ep.frames} f @ {ep.fps} fps, {len(ep.shots)} shots, {len(ep.words)} words")
        rules += narration.narration_checks(ep)
        rules += pacing.pacing_checks(ep)
        cr, rows = captions.caption_checks(ep)
        rules += cr
        details["captions"] = rows
        fr, per = framing.framing_checks(ep)
        rules += fr
        details["framing"] = per
    out_dir = out_dir or "qc"
    os.makedirs(out_dir, exist_ok=True)
    if video_path:
        inputs["video"] = video_path
        if not video.available():
            rules.append(rule("TQ-VIDEO", "TECH", SKIP, detail="ffmpeg/ffprobe not installed"))
        elif not os.path.isfile(video_path):
            rules.append(rule("TQ-VIDEO", "TECH", FAIL, detail=f"video not found: {video_path}"))
        else:
            log(f"[qc] measuring {video_path} (ffprobe, ebur128, silencedetect, blackdetect, freezedetect, scene)")
            m = video_rules.measure(video_path)
            rules += video_rules.video_rules(m, ep)
            rules += video_rules.detected_cut_rules(m, ep)
            a = m.get("audio") or {}
            details["video"] = {"probe": m["probe"], "black": m["video"]["black"], "freeze": m["video"]["freeze"],
                                "cuts_detected": rnd(m["video"]["cuts_merged"], 2), "unique_frames": m["video"].get("unique_frames"),
                                "loudness": {k: a.get(k) for k in ("integrated", "lra", "true_peak")}, "silences": rnd(a.get("silences"), 3),
                                "motion_0_05": rnd(m.get("motion_0_05"), 5), "loop_ssim": rnd(m.get("loop_ssim"), 4)}
            # >>> quality_gate (L006): delivery profile of the master (informational section DELIVERY; the
            # deliverables themselves are produced and enforced by factory/deliver.py)
            try:
                from . import delivery
                dm = delivery.measure(video_path)
                rules += delivery.delivery_rules(dm, delivery.FINAL)
                details["delivery"] = dm
            except Exception as e:  # noqa: BLE001 - measured again (and enforced) at delivery
                details["delivery"] = {"error": str(e)}
            # <<< quality_gate
    if plates_dir:
        inputs["plates"] = plates_dir
        log(f"[qc] checking plates in {plates_dir}")
        pr, per_frame = plates.plate_checks(plates_dir, ep, partial=partial_plates)
        rules += pr
        details["plates"] = per_frame
        if ep:
            details["framing_overlays"] = _overlays(ep, plates_dir, os.path.join(out_dir, "framing_overlays"))
    if video_path or plates_dir:
        log("[qc] vision review hook (contact sheet + rubric)")
        vr, info = vision.review(os.path.join(out_dir, "vision"), RECIPES, video_path if video_path and os.path.isfile(video_path) else None,
                                 plates_dir, ep, client=vision_client, run_model=run_vision)
        rules += vr
        details["vision"] = info
    s = score(rules, iteration)
    try:  # >>> quality_gate: lessons ledger status rides in every QC report
        from factory.lessons import checks as lesson_checks
        details["lessons"] = lesson_checks.summary()
    except Exception as e:  # noqa: BLE001
        details["lessons"] = {"error": str(e)}
    s["gates"]["delivery"] = all(r["status"] != FAIL for r in rules if r["section"] == "DELIVERY")  # <<< quality_gate
    report = {
        "schema": "factory.qc.report/1",
        "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "inputs": inputs,
        **s,
        "rules": rules,
        "details": details,
        "seconds": rnd(time.time() - t0, 1),
    }
    path = os.path.join(out_dir, "report.json")
    with open(path, "w") as fh:
        json.dump(report, fh, indent=1, default=str)
    report["path"] = path
    return report


def _overlays(ep, plates_dir, out):
    """Framing cross-check: the projected subject drawn on up to 12 rendered plates."""
    os.makedirs(out, exist_ok=True)
    shots = {s["id"]: s for s in ep.shots}
    res = []
    for sid, g in sorted(plates.discover(plates_dir).items()):
        if sid not in shots:
            continue
        for f, p in sorted(g["frames"].items())[:2]:
            dst = os.path.join(out, f"{sid}_{f:04d}.png")
            r = framing.overlay(p, dst, shots[sid], f, ep.width, ep.height)
            res.append({"plate": dst, "kind": r["kind"], "eye": rnd(r["eye"], 3)})
            if len(res) >= 12:
                return res
    return res


def summary_text(rep):
    lines = [f"engagement_score {rep['engagement_score']} (coverage {rep['coverage']})  decision {rep['decision']}"]
    for sec, v in rep["sections"].items():
        lines.append(f"  {sec:<10} pass_rate {v['pass_rate']}  ({v['passed']}/{v['evaluated']}, skipped {v['skipped']})")
    if rep["hard_failures"]:
        lines.append("  HARD failures: " + ", ".join(rep["hard_failures"]))
    for r in rep["rules"]:
        if r["status"] == FAIL:
            lines.append(f"  FAIL {r['id']:<26} {r['section']:<9} measured={json.dumps(r['measured'], default=str)[:110]}")
    lines.append(f"  report: {rep.get('path')}")
    return "\n".join(lines)
