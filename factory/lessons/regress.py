"""The in-pipeline 'regress' check (factory/run: before previs approval and before publish).

Fast and in-process (no pytest, no renders):
  * the episode-level lesson rules on this run's episode.json: PROXY (L012, camera inside geometry: blocks) and TIER
    (L008: warns at previs; blocks at publish when the run renders at quality final),
  * the lessons ledger status (open lessons, lessons without a working check),
  * the film-craft canon pass (`python3 -m factory.canon pass`, .claude/skills/film-craft-canon): any canon rule
    reported FAIL blocks; MANUAL rules are listed as warnings for the human approval,
  * golden staleness: goldens whose inputs changed since their references were approved and that have no passing
    compare for the current inputs (a warning here; the merge gate is where goldens are enforced).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from . import ROOT


def _validator():
    d = os.path.join(ROOT, "factory", "direction")
    if d not in sys.path:
        sys.path.insert(0, d)
    import shot_validator
    return shot_validator


def canon_pass(spec_path, out_path, root=ROOT, plates=None, video=None, timeout=900):
    """Run the canon pass on one episode -> {"rc", "summary", "fail": [rule ids], "manual": [...], "report"}."""
    cmd = [sys.executable, "-m", "factory.canon", "pass", "--episode", os.path.abspath(spec_path), "--out", out_path]
    if plates:
        cmd += ["--plates", plates]
    if video:
        cmd += ["--video", video]
    try:
        p = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=timeout)
        rc, tail = p.returncode, (p.stdout + p.stderr)[-1500:]
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"rc": 99, "error": str(e), "fail": ["CANON-RUN"], "manual": []}
    if not os.path.exists(out_path):
        return {"rc": rc, "error": tail, "fail": ["CANON-RUN"], "manual": []}
    rep = json.load(open(out_path))
    rules = rep.get("rules") or {}
    return {"rc": rc, "summary": rep.get("summary"), "report": out_path,
            "fail": sorted(k for k, r in rules.items() if r.get("status") == "FAIL"),
            "manual": sorted(k for k, r in rules.items() if r.get("status") == "MANUAL"),
            "details": {k: r.get("detail") for k, r in rules.items() if r.get("status") == "FAIL"}}


def episode_regress(spec_path, gate="previs", quality="preview", root=ROOT, goldens=True, canon=True, plates=None, video=None):
    with open(spec_path, encoding="utf-8") as fh:
        ep = json.load(fh)
    mode = "final" if (gate == "publish" and quality == "final") else "previs"
    SV = _validator()
    SV.load_coast(root)
    rules = SV.lesson_rules(ep, mode)
    blocking = [r for r in rules if r["status"] == "fail"]
    warnings = [r for r in rules if r["status"] == "warn"]
    out = {"gate": gate, "mode": mode, "rules": [{k: r[k] for k in ("id", "status", "detail", "shots")} for r in rules]}
    try:
        from .checks import summary
        out["lessons"] = summary(root)
    except Exception as e:  # noqa: BLE001
        out["lessons"] = {"error": str(e)}
    if canon and os.environ.get("FACTORY_CANON", "1") != "0":
        qc_dir = os.path.join(os.path.dirname(os.path.abspath(spec_path)), "qc")
        os.makedirs(qc_dir, exist_ok=True)
        c = canon_pass(spec_path, os.path.join(qc_dir, f"canon_{gate}.json"), root, plates=plates, video=video)
        out["canon"] = c
        for rid in c["fail"]:
            blocking.append({"id": f"CANON:{rid}", "status": "fail", "detail": c.get("details", {}).get(rid) or c.get("error") or "canon rule FAIL",
                             "shots": []})
        if c.get("manual"):
            warnings.append({"id": "CANON-MANUAL", "status": "warn", "shots": [],
                             "detail": f"{len(c['manual'])} canon rule(s) need a human review per .claude/skills/film-craft-canon/SKILL.md: {c['manual']}"})
    if goldens:
        try:
            from factory.goldens import gate as ggate
            st = ggate.staleness(root)
            out["goldens"] = st
            if st.get("stale"):
                warnings.append({"id": "GOLDENS", "status": "warn", "detail": f"stale goldens (run `python -m factory.goldens compare`): {st['stale']}",
                                 "shots": []})
        except Exception as e:  # noqa: BLE001 - goldens are enforced by the merge gate
            out["goldens"] = {"error": str(e)}
    out["blocking"] = [f"{r['id']}: {str(r['detail'])[:300]}" for r in blocking]
    out["warnings"] = [f"{r['id']}: {str(r['detail'])[:300]}" for r in warnings]
    out["ok"] = not blocking
    return out
