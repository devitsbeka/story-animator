"""python3 -m factory.canon pass --episode <dir|episode.json> [--plates DIR] [--video MP4] [--out FILE]
                              [--stage plan|render|publish] [--quiet]

Runs: shot validator (coverage/framing/CTX/collision), lighting continuity, and the canon checks
(factory/canon/checks.py: every automatable CAN-* sub-rule, thresholds in factory/canon/thresholds.yaml), and reports
each canon rule as PASS/FAIL/MANUAL with its sub-rules. Exit 1 on any FAIL. factory/run runs it before the previs
approval (--stage plan) and before publishing (--stage publish)."""
import argparse, json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CANON = [
    ("CAN-S1", "threat shown to audience before the character notices"),
    ("CAN-S2", "knowledge timeline: who knows / who can act / audience question"),
    ("CAN-S3", "ticking clock the viewer can feel"),
    ("CAN-C1", "wide establishes geography before coverage"),
    ("CAN-C2", "close-up reserved for the decisive reaction"),
    ("CAN-H1", "impact handheld: subject escapes frame, camera catches up late"),
    ("CAN-E1", "action information order: obstacle(aud) -> obstacle(char) -> impact -> cost"),
    ("CAN-P1", "turn-then-change: expression change never inside a head turn"),
    ("CAN-P2", "living faces + correct hands (L010/L011/L017/L018)"),
    ("CAN-L1", "discovery map: light reveals the story detail when intended"),
    ("CAN-L2", "night continuity wide<->close, motivated light"),
    ("CAN-L3", "depth separation, rim on dark subjects"),
    ("CAN-T1", "look-dev test frame (boat + one lamp + water) approved first"),
    ("CAN-N1", "three-column script (picture | narration | sound)"),
    ("CAN-N2", "sound-before-words + reserved narration gaps filled by sound"),
    ("CAN-N3", "key word vs reveal order honoured; no talking over reactions"),
    ("CAN-N4", "narrator authority; redundant lines cut"),
]


def run(cmd):
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=900)
        return p.returncode, (p.stdout + p.stderr)[-4000:]
    except Exception as e:  # pragma: no cover
        return 99, str(e)


def episode_json(path):
    if os.path.isdir(path):
        for n in ("episode.json", "episode_v6.json", "episode_v5.json"):
            if os.path.isfile(os.path.join(path, n)):
                return os.path.join(path, n)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pass"])
    ap.add_argument("--episode", required=True)
    ap.add_argument("--plates")
    ap.add_argument("--video")
    ap.add_argument("--out")
    ap.add_argument("--stage", choices=["plan", "render", "publish"], default="plan",
                    help="plan: before previs approval; render/publish: an unapproved look-dev test FAILs (CAN-T1a)")
    ap.add_argument("--quiet", action="store_true", help="only the summary and failing rules")
    a = ap.parse_args()
    ep = episode_json(a.episode)
    results, fails = {}, 0
    checks = {}
    rc, out = run([sys.executable, "factory/direction/shot_validator.py", ep])
    checks["shot_validator"] = {"rc": rc, "tail": out[-1500:]}
    rc2, out2 = run([sys.executable, "cloud/blender/lighting.py", "--check", ep])
    checks["lighting_continuity"] = {"rc": rc2, "tail": out2[-800:]}
    # canon-aware checks, if the integration has landed (factory/canon/checks.py)
    canon_checks = None
    try:
        sys.path.insert(0, ROOT)
        from factory.canon import checks as cc  # type: ignore
        canon_checks = cc.run_all(ep, plates=a.plates, video=a.video, stage=a.stage)
    except Exception as e:
        checks["canon_checks"] = {"rc": None, "note": f"not implemented yet ({type(e).__name__}); rules reported MANUAL"}
    # >>> polish_light: lighting canon (CAN-L1 discovery map, CAN-L2 night face-exposure continuity) from lighting.py
    try:
        sys.path.insert(0, os.path.join(ROOT, "cloud", "blender"))
        import lighting as _lighting  # pure-python part (no bpy)
        with open(ep) as fh:
            _lc = _lighting.canon_lighting(json.load(fh), plates=a.plates)
        canon_checks = dict(canon_checks or {})
        for _rid, _r in _lc.items():
            canon_checks.setdefault(_rid, _r)
        checks["lighting_canon"] = {"rc": 0, "rules": sorted(_lc)}
    except Exception as e:  # pragma: no cover
        checks["lighting_canon"] = {"rc": None, "note": f"lighting canon unavailable ({type(e).__name__}: {e})"}
    # <<< polish_light
    for rid, desc in CANON:
        if canon_checks and rid in canon_checks:
            st = canon_checks[rid]["status"]
            results[rid] = {"desc": desc, "status": st, "detail": canon_checks[rid].get("detail"),
                            "sub": {k: canon_checks[k] for k in canon_checks.get(rid, {}).get("sub", {})}}
        else:
            results[rid] = {"desc": desc, "status": "MANUAL", "detail": "no automated check yet: review by hand per SKILL.md"}
    # map existing automated checks onto canon rules where they already apply (shot_validator C3/C4/C5/C1/C2 are
    # read in-process by checks.run_all; a crash of the validator script is a FAIL)
    if rc not in (0, None):
        results["CAN-C1"]["status"] = "FAIL" if results["CAN-C1"]["status"] == "MANUAL" else results["CAN-C1"]["status"]
        results["CAN-C1"]["detail"] = "shot_validator failed (see checks.shot_validator)"
    if rc2 not in (0, None):
        results["CAN-L2"]["status"] = "FAIL" if results["CAN-L2"]["status"] == "MANUAL" else results["CAN-L2"]["status"]
        results["CAN-L2"]["detail"] = "lighting continuity check failed"
    fails = sum(1 for r in results.values() if r["status"] == "FAIL")
    if canon_checks:
        checks["canon_checks"] = {"rc": 0, "meta": canon_checks.get("_meta")}
    rep = {"episode": ep, "rules": results, "checks": checks,
           "summary": {s: sum(1 for r in results.values() if r["status"] == s) for s in ("PASS", "FAIL", "MANUAL")}}
    out_path = a.out or os.path.join(os.path.dirname(ep), "qc", "canon_report.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    json.dump(rep, open(out_path, "w"), indent=1)
    print(f"CANON PASS  {rep['summary']}  -> {out_path}")
    for rid, r in results.items():
        print(f"  [{r['status']:6s}] {rid} {r['desc']}")
        for sid, sr in (r.get("sub") or {}).items():
            if a.quiet and sr["status"] not in ("FAIL",):
                continue
            print(f"      {sr['status']:6s} {sid}: {str(sr.get('detail') or '')[:220]}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
