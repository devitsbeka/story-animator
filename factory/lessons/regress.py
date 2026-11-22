"""The in-pipeline 'regress' check (factory/run: before previs approval and before publish).

Fast and in-process (no pytest, no renders):
  * the episode-level lesson rules on this run's episode.json: PROXY (L012, camera inside geometry: blocks) and TIER
    (L008: warns at previs; blocks at publish when the run renders at quality final),
  * the lessons ledger status (open lessons, lessons without a working check),
  * golden staleness: goldens whose inputs changed since their references were approved and that have no passing
    compare for the current inputs (a warning here; the merge gate is where goldens are enforced).
"""
from __future__ import annotations

import json
import os
import sys

from . import ROOT


def _validator():
    d = os.path.join(ROOT, "factory", "direction")
    if d not in sys.path:
        sys.path.insert(0, d)
    import shot_validator
    return shot_validator


def episode_regress(spec_path, gate="previs", quality="preview", root=ROOT, goldens=True):
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
