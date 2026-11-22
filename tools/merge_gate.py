#!/usr/bin/env python3
"""MERGE GATE: run before merging any agent branch. `tools/merge_gate.sh <branch> [--base REF] [--skip-goldens]`

In throw-away worktrees of <branch> and of the base (default: the current HEAD of the repo you run it from):
  1. pytest     every tests/<area> directory (one process per directory: their conftests collide) + the
                direction tests; a failure is a regression unless the same test also fails on the base
  2. lessons    python -m factory.lessons check (fast lesson checks) + inject-briefs --check (briefs carry the ledger)
  3. validator  factory/direction/shot_validator.py on each side's current episode: FAIL on (rule, shot) failures
                the base does not have
  4. lighting   cloud/blender/lighting.py --check on the current episode: FAIL on new problems
  4b. stress    python -m factory.goldens stress --no-render: every generated scenario (stances x hands x kits x sizes x
                emotions) through the shot checks + Blender pose QC; FAIL on failures not in known_failures.json
  4c. canon     python3 -m factory.canon pass on each side's current episode (film-craft canon, SKILL.md): FAIL on a
                canon rule that FAILs on the branch and not on the base, or when the pass cannot run on the branch
  5. goldens    python -m factory.goldens compare --changed-from <base> (only goldens whose inputs the branch
                changed; renders at 360x640, low samples, one at a time) -> diff sheet
Prints PASS/FAIL with reasons and writes <out>/merge_gate.json. Exit 0 = PASS.
Runtime on 4 CPUs: ~10 min without affected goldens; + ~1-4 min per affected golden.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PY = sys.executable


def sh(cmd, cwd, env=None, timeout=3600):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr, round(time.time() - t0, 1)
    except subprocess.TimeoutExpired as e:
        return -9, (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), "timeout", round(time.time() - t0, 1)


def git(*a, cwd=REPO):
    rc, out, err, _ = sh(["git", *a], cwd)
    if rc:
        raise RuntimeError(f"git {' '.join(a)}: {err.strip()}")
    return out.strip()


def add_worktree(ref, path):
    git("worktree", "add", "--detach", "--force", path, ref)
    return path


def test_dirs(root):
    out = [os.path.join("tests", d) for d in sorted(os.listdir(os.path.join(root, "tests")))
           if os.path.isdir(os.path.join(root, "tests", d)) and any(f.startswith("test_") for f in os.listdir(os.path.join(root, "tests", d)))]
    if os.path.exists(os.path.join(root, "factory", "direction", "test_direction.py")):
        out.append("factory/direction/test_direction.py")
    return out


def run_pytest(root, env, log):
    """-> {target: {"rc", "failed": [nodeids], "summary"}}"""
    res = {}
    for t in test_dirs(root):
        rc, out, err, secs = sh([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rfE", t], root, env, timeout=2400)
        failed = sorted(set(re.findall(r"^(?:FAILED|ERROR) (\S+)", out, re.M)))
        if rc not in (0, 5) and not failed:
            failed = [f"{t}::<collection or crash rc={rc}>"]
        summ = (out.strip().splitlines() or [""])[-1]
        res[t] = {"rc": rc, "failed": failed, "summary": summ, "seconds": secs}
        log(f"  pytest {t}: {summ} ({secs}s)")
    return res


def recheck_on_base(base_root, env, failed):
    """Which of the branch's failing node ids also fail on the base (pre-existing, not a regression)."""
    pre = []
    for nid in failed:
        if "<collection" in nid:
            continue
        rc, out, err, _ = sh([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", nid], base_root, env, timeout=1800)
        if rc not in (0, 5):
            pre.append(nid)
    return pre


def current_episode(root):
    import glob
    c = glob.glob(os.path.join(root, "episodes", "sentinel", "episode_v*.json"))
    return max(c, key=lambda p: int(re.search(r"_v(\d+)\.json$", p).group(1))) if c else None


def validator_fails(root, env, out_json):
    ep = current_episode(root)
    if not ep:
        return None, "no episode"
    rc, out, err, _ = sh([PY, "factory/direction/shot_validator.py", ep, "--quiet", "--out", out_json], root, env, timeout=600)
    if not os.path.exists(out_json):
        return None, (err or out)[-600:]
    rep = json.load(open(out_json))
    validator_fails.rule_ids = {r["id"] for r in rep["rules"]}
    pairs = set()
    for r in rep["rules"]:
        if r["status"] == "fail":
            pairs |= {(r["id"], s) for s in (r.get("shots") or ["*"])}
    return pairs, os.path.relpath(ep, root)


def lighting_problems(root, env):
    ep = current_episode(root)
    rc, out, err, _ = sh([PY, "cloud/blender/lighting.py", "--check", ep], root, env, timeout=600)
    return set(re.findall(r"^\s+- (.+)$", out, re.M)), rc


def canon_fails(root, env, out_json):
    """-> (set of FAIL canon rule ids, None) or (None, error) when the pass did not run (no factory/canon yet = base)."""
    ep = current_episode(root)
    if not ep:
        return None, "no episode"
    if not os.path.exists(os.path.join(root, "factory", "canon", "__main__.py")):
        return None, "no factory/canon on this side"
    rc, out, err, _ = sh([PY, "-m", "factory.canon", "pass", "--episode", ep, "--out", out_json], root, env, timeout=900)
    if not os.path.exists(out_json):
        return None, (err or out)[-600:]
    rules = json.load(open(out_json)).get("rules") or {}
    return {k for k, r in rules.items() if r.get("status") == "FAIL"}, None


def main(argv=None):
    ap = argparse.ArgumentParser(description="merge gate for an agent branch")
    ap.add_argument("branch")
    ap.add_argument("--base", default="HEAD", help="ref the branch will be merged into (default: HEAD of this checkout)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--skip-goldens", action="store_true")
    ap.add_argument("--skip-pytest", action="store_true")
    ap.add_argument("--skip-pose", action="store_true", help="stress suite without the Blender pose QC")
    ap.add_argument("--keep", action="store_true", help="keep the temp worktrees")
    a = ap.parse_args(argv)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", a.branch)
    tmp = os.environ.get("MERGE_GATE_TMP", "/tmp/merge_gate")
    out_dir = a.out or os.path.join(tmp, f"{safe}-{stamp}")
    os.makedirs(out_dir, exist_ok=True)
    base_sha = git("rev-parse", a.base)
    br_sha = git("rev-parse", a.branch)
    log_lines = []

    def log(m):
        print(m, flush=True)
        log_lines.append(m)
    log(f"MERGE GATE {a.branch} ({br_sha[:10]}) -> base {a.base} ({base_sha[:10]})  out {out_dir}")
    wt_b = add_worktree(br_sha, os.path.join(out_dir, "branch"))
    wt_base = add_worktree(base_sha, os.path.join(out_dir, "base"))
    sys.path.insert(0, REPO)
    from factory.goldens import manifest as GM
    env = dict(os.environ, LIBRARY_STORE=GM.find_library_store(REPO), FACTORY_GOLDENS_STORE=GM.store_dir(REPO),
               PYTHONDONTWRITEBYTECODE="1")
    env.pop("FACTORY_CURRENT_EPISODE", None)
    reasons, report = [], {"branch": a.branch, "branch_sha": br_sha, "base": a.base, "base_sha": base_sha, "steps": {}}
    try:
        # 1 pytest
        if not a.skip_pytest:
            log("[1/5] pytest (per test directory)")
            pt = run_pytest(wt_b, env, log)
            failed = sorted({n for v in pt.values() for n in v["failed"]})
            pre = recheck_on_base(wt_base, env, failed) if failed else []
            new = [n for n in failed if n not in pre]
            report["steps"]["pytest"] = {"targets": pt, "failed": failed, "preexisting_on_base": pre, "new_failures": new}
            if new:
                reasons.append(f"pytest: {len(new)} new failure(s): {new[:8]}")
            if pre:
                log(f"  (pre-existing on base, not blocking: {pre[:8]})")
        # 2 lessons
        log("[2/5] lesson checks")
        rc, out, err, secs = sh([PY, "-m", "factory.lessons", "check", "--json"], wt_b, env, timeout=3600)
        try:
            lc = json.loads(out)
        except ValueError:
            lc = {"ok": False, "results": [], "error": (err or out)[-800:]}
        rc2, out2, _, _ = sh([PY, "-m", "factory.lessons", "inject-briefs", "--check"], wt_b, env)
        report["steps"]["lessons"] = {"ok": lc["ok"], "results": lc.get("results"), "briefs_current": rc2 == 0, "seconds": secs}
        bad = [f"{r['lesson']} {r['name']}" for r in lc.get("results", []) if r["status"] in ("fail", "missing")]
        if not lc["ok"]:
            reasons.append(f"lesson checks failed: {bad[:8] or lc.get('error')}")
        if rc2:
            reasons.append("agent brief templates are stale: run `python -m factory.lessons inject-briefs`")
        log(f"  lessons: {'PASS' if lc['ok'] else 'FAIL ' + str(bad[:5])}; briefs {'current' if rc2 == 0 else 'STALE'}")
        # 3 shot validator
        log("[3/5] shot validator on the current episode (no new failures vs base)")
        vb, epb = validator_fails(wt_b, env, os.path.join(out_dir, "validator_branch.json"))
        rules_branch = getattr(validator_fails, "rule_ids", set())
        va, epa = validator_fails(wt_base, env, os.path.join(out_dir, "validator_base.json"))
        rules_base = getattr(validator_fails, "rule_ids", set())
        if vb is None:
            reasons.append(f"shot validator did not run on the branch: {epb}")
            new_v = []
        else:
            diff = sorted(vb - (va or set()))
            # a rule the base does not have is a NEW CHECK: its findings are pre-existing defects it now reveals
            # (reported, not blocking); a failure of a rule the base already had is a regression
            new_checks = [p for p in diff if p[0] not in rules_base]
            new_v = [p for p in diff if p[0] in rules_base]
            if new_checks:
                log(f"  new validator rules on this branch reveal existing defects (not blocking): {new_checks[:12]}")
            report["steps"]["validator_new_checks"] = new_checks
            if new_v:
                reasons.append(f"shot validator: new failures {new_v[:10]} on {epb}")
        report["steps"]["validator"] = {"episode": epb, "base_episode": epa, "new_failures": new_v,
                                        "fixed": sorted((va or set()) - (vb or set())), "branch_failures": sorted(vb or [])}
        log(f"  validator ({epb}): {len(vb or [])} failing (rule, shot) pairs, new vs base: {new_v[:10] or 'none'}")
        # 4 lighting
        log("[4/5] lighting --check")
        lb, _ = lighting_problems(wt_b, env)
        la, _ = lighting_problems(wt_base, env)
        new_l = sorted(lb - la)
        report["steps"]["lighting"] = {"problems": sorted(lb), "new": new_l}
        if new_l:
            reasons.append(f"lighting --check: new problems {new_l[:5]}")
        log(f"  lighting: {len(lb)} problem(s), new: {new_l[:5] or 'none'}")
        # 4c canon pass (film-craft canon) - no new FAIL vs the base
        log("[4c] canon pass (python3 -m factory.canon pass)")
        cb, eb = canon_fails(wt_b, env, os.path.join(out_dir, "canon_branch.json"))
        ca, _ = canon_fails(wt_base, env, os.path.join(out_dir, "canon_base.json"))
        if cb is None:
            reasons.append(f"canon pass did not run on the branch: {eb}")
            new_c = []
        else:
            new_c = sorted(cb - (ca or set()))
            if new_c:
                reasons.append(f"canon pass: new FAIL {new_c}")
        report["steps"]["canon"] = {"branch_fail": sorted(cb or []), "base_fail": sorted(ca or []), "new": new_c,
                                    "report": os.path.join(out_dir, "canon_branch.json")}
        log(f"  canon: FAIL on branch {sorted(cb or []) or 'none'}, new vs base: {new_c or 'none'}")
        # 4b stress suite (fast shot checks + VOCAB + Blender pose QC on every scenario; the stress goldens themselves
        # are compared in step 5 when the branch affects them). FAIL on any failure not in known_failures.json.
        log("[4b] scenario stress suite (shot checks + pose QC on every scenario)")
        scmd = [PY, "-m", "factory.goldens", "stress", "--no-render"] + (["--no-pose"] if a.skip_pose else [])
        rc, out, err, secs = sh(scmd, wt_b, env, timeout=3 * 3600)
        report["steps"]["stress"] = {"rc": rc, "output": out[-4000:], "seconds": secs}
        for line in out.splitlines()[-4:]:
            log("  " + line)
        if rc:
            reasons.append("stress suite: scenarios failing outside known_failures.json - " +
                           next((l for l in out.splitlines() if l.startswith("regressions")), (err or out)[-300:]))
        # 5 goldens
        if a.skip_goldens:
            report["steps"]["goldens"] = {"skipped": True}
            log("[5/5] goldens: skipped (--skip-goldens)")
        else:
            log("[5/5] golden regression (affected goldens only)")
            gcmd = [PY, "-m", "factory.goldens", "compare", "--changed-from", base_sha]
            if not os.environ.get("MERGE_GATE_VISION"):      # MERGE_GATE_VISION=1: ask the vision reviewer on changed goldens
                gcmd.append("--no-vision")
            rc, out, err, secs = sh(gcmd, wt_b, env, timeout=6 * 3600)
            sheet = re.search(r"diff sheet: (\S+)", out)
            report["steps"]["goldens"] = {"rc": rc, "output": out[-3000:], "diff_sheet": sheet.group(1) if sheet else None, "seconds": secs}
            for line in out.splitlines():
                if line.startswith("[") or line.startswith("GOLDENS") or "goldens:" in line:
                    log("  " + line)
            if rc:
                reasons.append(f"goldens: regression (see {sheet.group(1) if sheet else out_dir}); if intended, render + "
                               "`python -m factory.goldens approve --only <ids> --note ...` on the branch and commit baseline.json")
    finally:
        report["reasons"] = reasons
        report["verdict"] = "PASS" if not reasons else "FAIL"
        with open(os.path.join(out_dir, "merge_gate.json"), "w") as fh:
            json.dump(report, fh, indent=1, default=str)
        if not a.keep:
            for w in (wt_b, wt_base):
                sh(["git", "worktree", "remove", "--force", w], REPO)
    print("=" * 72)
    print(f"MERGE GATE {report['verdict']}: {a.branch} ({br_sha[:10]})")
    for r in reasons:
        print(f"  - {r}")
    gs = report["steps"].get("goldens", {})
    if gs.get("diff_sheet"):
        print(f"  diff sheet: {gs['diff_sheet']}")
    print(f"  report: {os.path.join(out_dir, 'merge_gate.json')}")
    return 0 if not reasons else 1


if __name__ == "__main__":
    sys.exit(main())
