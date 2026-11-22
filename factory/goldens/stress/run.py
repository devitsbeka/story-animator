"""Run the scenario stress suite: every scenario must pass every check (or be a KNOWN failure tied to an open lesson).

    python -m factory.goldens stress [--only id,id] [--no-render] [--no-pose] [--vision] [--update-known --note N]

Per scenario:
  shot checks   FRAME-CROP, FRAME-EYES, COLLIDE, VIS (factory/direction/shot_checks.py)
  VOCAB         the scenario's stance / hand use exists in the renderer vocabulary (kneel, crouch, walk, rope...)
  pose QC       POSE-SEAT, POSE-SPINE, POSE-FINGERS, POSE-WRIST, POSE-PALM, POSE-GRIP, FACE-LIFE over the 2 s clip
                (cloud/blender/test/pose_qc.py --full-clip, one Blender process for the whole suite)
  golden        stress_<id> render vs its approved reference (factory/goldens gate; 360x640, 8 spp, curated library)
  vision        HANDS-1, FACE-2, FACE-3, FRAME-1 (--vision; needs ANTHROPIC_API_KEY)
known_failures.json lists (scenario, rule) pairs that fail today because of an OPEN lesson; the suite FAILS on any
failure not listed there (a regression or an unowned defect) and reports listed ones that now pass (prune them).
Renders run in parallel only when the memory budget allows (2 workers with >= 9 GB available), else sequentially.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime
import json
import os
import subprocess
import sys

from . import generator

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = generator.ROOT
KNOWN = os.path.join(HERE, "known_failures.json")
BLENDER = os.environ.get("BLENDER", "/opt/blender/blender-4.2.3-linux-x64/blender")


def load_known(path=KNOWN):
    if not os.path.exists(path):
        return {"schema": "factory.goldens.stress.known/1", "note": "", "failures": {}}
    with open(path) as fh:
        return json.load(fh)


def mem_available_gb():
    try:
        avail = None
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                avail = int(line.split()[1]) / 1e6
        for cg in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
            if os.path.exists(cg):
                lim = open(cg).read().strip()
                cur_p = cg.replace("memory.max", "memory.current").replace("limit_in_bytes", "usage_in_bytes")
                if lim.isdigit() and os.path.exists(cur_p):
                    free = (int(lim) - int(open(cur_p).read().strip())) / 1e9
                    avail = min(avail or free, free)
        return avail or 0.0
    except (OSError, ValueError):
        return 0.0


def render_workers():
    return 2 if mem_available_gb() >= 9.0 else 1


def shot_checks(spec, only=None):
    d = os.path.join(ROOT, "factory", "direction")
    if d not in sys.path:
        sys.path.insert(0, d)
    import shot_checks as SC
    out = {}
    for s in spec["shots"]:
        if only and s["id"] not in only:
            continue
        out[s["id"]] = [{"rule": f["rule"], "status": f["status"], "measured": f["measured"]} for f in SC.check_shot(spec, s)]
    return out


def pose_qc(spec_path, only, out_json, log=print):
    env = dict(os.environ)
    from factory.goldens import manifest as M
    env["LIBRARY_STORE"] = M.find_library_store(ROOT)
    cmd = [BLENDER, "-b", "--python-exit-code", "1", "--factory-startup", "-P", os.path.join(ROOT, "cloud", "blender", "test", "pose_qc.py"),
           "--", "--spec", spec_path, "--full-clip", "--max-frames", "1", "--out", out_json]
    if only:
        cmd += ["--shots", ",".join(sorted(only))]
    log(f"[stress] pose QC ({'all' if not only else len(only)} scenarios, one Blender process)")
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=7200, env=env)
    if p.returncode != 0 or not os.path.exists(out_json):
        raise RuntimeError(f"pose QC failed rc={p.returncode}: {(p.stdout + p.stderr)[-1500:]}")
    doc = json.load(open(out_json))
    by = {}
    for m in doc["measurements"]:
        sys.path.insert(0, os.path.join(ROOT, "cloud", "blender"))
        import pose_rules
        by.setdefault(m["shot"], []).extend({"rule": f["rule"], "status": f["status"], "measured": f["measured"]} for f in pose_rules.evaluate(m))
    return by


def run(only=None, render=True, pose=True, vision=False, out_dir=None, log=print, render_fn=None, pose_fn=None, vision_client=None):
    if not generator.is_current():
        generator.write()
        log("[stress] regenerated stress_episode.json")
    spec = json.load(open(generator.SPEC_PATH))
    meta = {s["id"]: s for s in spec["stress"]["scenarios"]}
    only = set(only) if only else None
    ids = [i for i in meta if not only or i in only]
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    from factory.goldens import gate, manifest as M
    out_dir = out_dir or os.path.join(M.store_dir(ROOT), "stress", stamp)
    os.makedirs(out_dir, exist_ok=True)
    rules = {i: [] for i in ids}
    for sid, fs in shot_checks(spec, only).items():
        rules[sid] += fs
    for sid in ids:
        miss = meta[sid]["vocab_missing"]
        rules[sid].append({"rule": "VOCAB", "status": "fail" if miss else "pass", "measured": miss})
    if pose:
        by = (pose_fn or pose_qc)(generator.SPEC_PATH, only, os.path.join(out_dir, "pose_qc.json"), log)
        for sid in ids:
            got = by.get(sid)
            rules[sid] += got if got else [{"rule": "POSE-QC", "status": "fail", "measured": "no measurement (rig missing?)"}]
    golden = {}
    if render:
        gids = [f"stress_{i}" for i in ids]
        workers = render_workers()
        log(f"[stress] rendering {len(gids)} stress goldens with {workers} worker(s) ({mem_available_gb():.1f} GB available)")
        cands = {}
        rf = render_fn or gate._render

        def one(g):
            p = os.path.join(out_dir, f"{g}.png")
            try:
                rf(g, p, ROOT, log)
                return g, p
            except Exception as e:  # noqa: BLE001
                log(f"[stress] {g}: render failed: {e}")
                return g, None
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            for g, p in ex.map(one, gids):
                if p:
                    cands[g] = p
        res = gate.run_compare([g for g in gids if g in cands], ROOT, candidates=cands, out_dir=out_dir, use_vision=False, log=log) if cands else {"results": []}
        for r in res["results"]:
            golden[r["id"]] = r
        for g in gids:
            sid = g[len("stress_"):]
            r = golden.get(g)
            st = "fail" if r is None else ("pass" if r["status"] == gate.PASS else ("new" if r["status"] == gate.NEW else "fail"))
            rules[sid].append({"rule": "GOLDEN", "status": st, "measured": None if r is None else (r.get("reasons") or (r.get("metrics") or {}).get("ssim"))})
            if vision and g in cands:
                from factory.goldens import vision as V
                ctx = {k: meta[sid][k] for k in ("kit", "stance", "hands", "size", "emotion")}
                for rid, v in V.rubric(cands[g], ctx, client=vision_client).items():
                    rules[sid].append({"rule": rid, "status": v["status"], "measured": v["note"]})
    known = load_known()["failures"]
    regress, known_hit, fixed = [], [], []
    for sid in ids:
        fails = {r["rule"] for r in rules[sid] if r["status"] == "fail"}
        kn = set(known.get(sid, {}))
        regress += [(sid, r) for r in sorted(fails - kn)]
        known_hit += [(sid, r) for r in sorted(fails & kn)]
        fixed += [(sid, r) for r in sorted(kn - fails) if any(x["rule"] == r for x in rules[sid])]
    report = {"at": stamp, "scenarios": {sid: {"meta": meta[sid], "rules": rules[sid]} for sid in ids}, "regressions": regress,
              "known_failures_hit": known_hit, "fixed": fixed, "ok": not regress, "ok_strict": not regress and not known_hit, "out_dir": out_dir,
              "diff_sheet": os.path.join(out_dir, "diff_sheet.png") if render else None}
    with open(os.path.join(out_dir, "stress_report.json"), "w") as fh:
        json.dump(report, fh, indent=1, default=str)
    return report


def update_known(report, note, path=KNOWN):
    """Record the current failures as known (each must be owned by an open lesson; the note says which)."""
    doc = load_known(path)
    doc["note"] = note
    doc["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    for sid, sc in report["scenarios"].items():
        f = sorted({r["rule"] for r in sc["rules"] if r["status"] == "fail"})
        if f:
            doc["failures"][sid] = {r: owner(r, sc["meta"]) for r in f}
        else:
            doc["failures"].pop(sid, None)
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
        fh.write("\n")
    return doc


OWNERS = {"POSE-FINGERS": "L017", "POSE-PALM": "L017", "POSE-GRIP": "L010", "POSE-WRIST": "L017", "HANDS-1": "L017",
          "POSE-SEAT": "L009", "POSE-SPINE": "L009", "FACE-LIFE": "L018", "FACE-2": "L011", "FACE-3": "L018",
          "FRAME-CROP": "L012", "FRAME-EYES": "L012", "FRAME-1": "L012", "COLLIDE": "L012", "VIS": "L012", "VOCAB": "L020",
          "GOLDEN": "-", "POSE-QC": "L003"}


def owner(rule, meta):
    return OWNERS.get(rule.split(".")[0], "unowned")


def summary_text(rep):
    lines = []
    for sid, sc in rep["scenarios"].items():
        f = [r["rule"] for r in sc["rules"] if r["status"] == "fail"]
        lines.append(f"  {sid:24} {'ok' if not f else 'FAIL ' + ','.join(f)}")
    lines.append(f"regressions (not in known_failures.json): {rep['regressions'] or 'none'}")
    lines.append(f"known failures still failing: {len(rep['known_failures_hit'])}; now passing (prune): {rep['fixed'] or 'none'}")
    lines.append(f"report: {os.path.join(rep['out_dir'], 'stress_report.json')}" + (f"  diff sheet: {rep['diff_sheet']}" if rep.get("diff_sheet") else ""))
    lines.append(f"strict (every scenario passes every rule, known failures included): {'PASS' if rep.get('ok_strict') else 'FAIL'}")
    lines.append("STRESS " + ("PASS" if rep["ok"] else "FAIL"))
    return "\n".join(lines)
