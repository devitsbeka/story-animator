"""Registry: lesson id -> the automated checks that enforce it.

A check is runnable from the repo root:
  pytest   python -m pytest -q <target>            (fast, CPU only; the lesson's regression test lives here)
  cmd      argv list; "{episode}" is replaced by the current episode spec
  blender  blender -b --factory-startup -P <script> -- <args>  (slow: needs Blender + library_store)
  golden   python -m factory.goldens compare --only <ids>        (slow: renders)

`status` reports, per lesson, whether every check's files exist (implemented) and the ledger status.
`run_checks` executes the fast checks (and the slow ones with include_slow) and returns per-check results.
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import time

from . import ROOT, is_open, load_lessons

BLENDER = os.environ.get("BLENDER", "/opt/blender/blender-4.2.3-linux-x64/blender")

CHECKS = {
    "L001": [
        {"name": "hero asset QC (eye bones, lid controls)", "kind": "blender", "target": "factory/characters/check_hero_v4.py", "slow": True},
        {"name": "golden face sheet", "kind": "golden", "target": "hero_face_sheet", "slow": True},
    ],
    "L002": [{"name": "director: every narration line -> picture + action", "kind": "pytest", "target": "tests/director/test_story_checks.py"}],
    "L003": [{"name": "CloudRig IK reach test (12 poses)", "kind": "blender", "target": "cloud/blender/test/cloudrig_adapter_test.py", "slow": True}],
    "L004": [
        {"name": "shot validator unit tests", "kind": "pytest", "target": "factory/direction/test_direction.py"},
        # the validator on the current episode runs in tools/merge_gate.sh as a no-new-failures comparison vs the base
    ],
    "L005": [{"name": "sequence lighting continuity", "kind": "cmd", "target": ["{python}", "cloud/blender/lighting.py", "--check", "{episode}"]}],
    "L006": [{"name": "delivery profile (H.264 High, yuv420p, faststart, GOP <= 1 s, bitrate cap) + deliver.py refusal",
              "kind": "pytest", "target": "tests/qc/test_delivery.py"}],
    "L007": [{"name": "final-video TECH/SOUND rules", "kind": "pytest", "target": "tests/qc/test_video.py"}],
    "L008": [
        {"name": "catalog tiers + camera-distance tier rule", "kind": "pytest", "target": "tests/direction/test_asset_tier.py"},
        {"name": "golden yacht turnaround", "kind": "golden", "target": "yacht_turnaround", "slow": True},
    ],
    "L009": [
        {"name": "pose QC evaluator (seat contact, spine pitch)", "kind": "pytest", "target": "tests/blender/test_pose_qc.py"},
        {"name": "pose QC on the episode (Blender)", "kind": "blender", "target": "cloud/blender/test/pose_qc.py", "args": ["--strict"], "slow": True},
        {"name": "golden pose sheet", "kind": "golden", "target": "hero_pose_sheet", "slow": True},
    ],
    "L010": [
        {"name": "pose QC evaluator (finger curl, grip contact)", "kind": "pytest", "target": "tests/blender/test_pose_qc.py"},
        {"name": "pose QC on the episode (Blender)", "kind": "blender", "target": "cloud/blender/test/pose_qc.py", "args": ["--strict"], "slow": True},
    ],
    "L011": [{"name": "golden face sheet", "kind": "golden", "target": "hero_face_sheet", "slow": True}],
    "L012": [
        {"name": "camera-in-geometry (mesh proxies)", "kind": "pytest", "target": "tests/direction/test_mesh_proxy.py"},
        {"name": "render runner fails on a missing plate", "kind": "pytest", "target": "tests/run/test_render_completeness.py"},
    ],
    "L013": [{"name": "schema-too-large fallback", "kind": "pytest", "target": "tests/director/test_llm_anthropic.py"}],
    "L014": [{"name": "per-stage cost ceiling + attempts alert", "kind": "pytest", "target": "tests/run/test_cost_ceiling.py"}],
    "L015": [{"name": "farm ships library_store-prefixed spec assets (select_library)", "kind": "pytest", "target": "tests/farm/test_presigned.py"}],
    "L022": [{"name": "stress suite fast checks (VOCAB + shot checks on every scenario, no new failures)", "kind": "cmd",
              "target": ["{python}", "-m", "factory.goldens", "stress", "--no-render", "--no-pose"]},
             {"name": "stress suite full (pose QC + stress goldens)", "kind": "cmd", "target": ["{python}", "-m", "factory.goldens", "stress"], "slow": True}],
    "L017": [
        {"name": "pose QC evaluator (palm normal incl. relaxed palms-to-thighs, wrist bend, finger curl, feet flat)", "kind": "pytest",
         "target": "tests/blender/test_pose_qc.py"},
        {"name": "stress suite full (pose QC on every scenario, HANDS regression cases)", "kind": "cmd",
         "target": ["{python}", "-m", "factory.goldens", "stress", "--no-render"], "slow": True},
    ],
    "L018": [
        {"name": "FACE-LIFE evaluator (no frozen face > 0.5 s, face motion floor)", "kind": "pytest", "target": "tests/blender/test_pose_qc.py"},
        {"name": "stress suite full (FACE-LIFE over the 2 s clip of every scenario)", "kind": "cmd",
         "target": ["{python}", "-m", "factory.goldens", "stress", "--no-render"], "slow": True},
    ],
    "L019": [{"name": "glazing asset gate (no emissive glass, glass transmits/reflects) on the hero yacht", "kind": "blender",
              "target": "cloud/blender/test/glazing_check.py", "args": ["--strict"], "slow": True}],
    "L020": [{"name": "EEVEE only with a real GPU context (egl_available)", "kind": "pytest", "target": "tests/lessons/test_lead_lessons.py"}],
    "L021": [{"name": "series defaults bind hero_v4 + proc:yacht_v2", "kind": "pytest", "target": "tests/lessons/test_lead_lessons.py"}],
    "L016": [{"name": "golden night sky under camera motion (TODO: recipe not defined yet)", "kind": "golden", "target": "night_sky_motion", "slow": True}],
    "L030": [{"name": "voice pace retake: every canon block in 2.2-3.3 w/s (tempo, pause tightening, re-voice; gaps kept; "
                      "cap + cost ceiling; pace stress scenarios)", "kind": "pytest", "target": "tests/voice/test_pace_retake.py"},
             {"name": "canon CAN-N4f-pace shares pacing.block_pace and checks retake speed / total tempo", "kind": "pytest",
              "target": "tests/canon/test_checks.py"}],
    "L031": [
        {"name": "stress hand-intent list never overrides authored pose hand shapes", "kind": "pytest", "target": "tests/blender/test_acting_hands.py"},
        {"name": "stress suite full in suite order (POSE-PALM / POSE-GRIP with the renderer's prop placement, FACE-LIFE)", "kind": "cmd",
         "target": ["{python}", "-m", "factory.goldens", "stress", "--no-render"], "slow": True},
    ],
    "L032": [{"name": "stress suite full (FOOT-ANKLE / FOOT-FLAT / FOOT-CONTACT on every seated + planted scenario)", "kind": "cmd",
              "target": ["{python}", "-m", "factory.goldens", "stress", "--no-render"], "slow": True}],
}


def current_episode(root=ROOT):
    """Newest episodes/sentinel/episode_v<N>.json (the episode the merge gate validates)."""
    env = os.environ.get("FACTORY_CURRENT_EPISODE")
    if env:
        return env
    cands = glob.glob(os.path.join(root, "episodes", "sentinel", "episode_v*.json"))
    num = lambda p: int(re.search(r"_v(\d+)\.json$", p).group(1))  # noqa: E731
    return max(cands, key=num) if cands else os.path.join(root, "episodes", "sentinel", "episode.json")


def check_files(c):
    if c["kind"] in ("pytest", "blender"):
        return [c["target"].split("::")[0]]
    if c["kind"] == "cmd":
        return [a for a in c["target"] if a.endswith(".py")]
    return []


def implemented(c, root=ROOT):
    if c["kind"] == "golden":
        from factory.goldens import manifest
        return c["target"] in manifest.load(root=root)["goldens"]
    return all(os.path.exists(os.path.join(root, f)) for f in check_files(c))


def status(root=ROOT, path=None):
    """-> rows {id, ledger, checks: [{name, kind, implemented, slow}], automated (all fast checks exist), rule}."""
    rows = []
    for d in load_lessons(path):
        cs = [{"name": c["name"], "kind": c["kind"], "target": c["target"], "slow": bool(c.get("slow")),
               "implemented": implemented(c, root)} for c in CHECKS.get(d["id"], [])]
        rows.append({"id": d["id"], "ledger": d["status"], "open": is_open(d), "gate": d["gate"], "checks": cs,
                     "automated": bool(cs) and all(c["implemented"] for c in cs), "rule": d.get("rule", "")})
    return rows


def argv_for(c, root=ROOT, episode=None):
    py = sys.executable
    if c["kind"] == "pytest":
        return [py, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", c["target"]]
    if c["kind"] == "cmd":
        ep = episode or current_episode(root)
        return [a.replace("{episode}", ep).replace("{python}", py) for a in c["target"]]
    if c["kind"] == "blender":
        return [BLENDER, "-b", "--python-exit-code", "1", "--factory-startup", "-P", c["target"]] + (["--", *c["args"]] if c.get("args") else [])
    if c["kind"] == "golden":
        return [py, "-m", "factory.goldens", "compare", "--only", c["target"]]
    raise ValueError(c["kind"])


def run_checks(root=ROOT, include_slow=False, only=None, episode=None, timeout=1800, log=print, runner=None):
    """Run the lesson checks (deduplicated by argv). -> {"ok": bool, "results": [...]}"""
    runner = runner or (lambda argv: subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=timeout))
    done, results = {}, []
    opened = {d["id"]: is_open(d) for d in load_lessons()}
    for lid, cs in CHECKS.items():
        if only and lid not in only:
            continue
        for c in cs:
            if c.get("slow") and not include_slow:
                results.append({"lesson": lid, "name": c["name"], "status": "skipped", "why": "slow (use --slow)"})
                continue
            if not implemented(c, root):
                # an open lesson may still lack its check (todo); a closed lesson whose check vanished is a failure
                results.append({"lesson": lid, "name": c["name"], "status": "todo" if opened.get(lid, True) else "missing", "why": f"not implemented: {check_files(c) or c['target']}"})
                continue
            argv = argv_for(c, root, episode)
            key = tuple(argv)
            if key not in done:
                t0 = time.time()
                try:
                    p = runner(argv)
                    done[key] = (p.returncode, (p.stdout or "")[-1500:] + (p.stderr or "")[-1500:], round(time.time() - t0, 1))
                except subprocess.TimeoutExpired:
                    done[key] = (-9, "timeout", round(time.time() - t0, 1))
                log(f"[lessons] {lid} {c['name']}: rc={done[key][0]} ({done[key][2]}s)")
            rc, tail, secs = done[key]
            results.append({"lesson": lid, "name": c["name"], "status": "pass" if rc == 0 else "fail", "rc": rc,
                            "seconds": secs, "argv": argv, "tail": tail if rc else ""})
    ok = all(r["status"] in ("pass", "skipped", "todo") for r in results)
    return {"ok": ok, "results": results}


def summary(root=ROOT, path=None):
    """Compact lessons status (for QC reports and run.json)."""
    rows = status(root, path)
    return {"total": len(rows), "closed": sum(not r["open"] for r in rows),
            "open": [r["id"] for r in rows if r["open"]],
            "automated": [r["id"] for r in rows if r["automated"]],
            "not_automated": [r["id"] for r in rows if not r["automated"]]}
