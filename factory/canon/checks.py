"""Automated craft-canon checks (called by `python3 -m factory.canon pass`).

run_all(episode_json, plates=None, video=None) -> {rule_id: {"status": "PASS"|"FAIL", "detail": str}}

Only rules with an automated check appear; the pass reports the rest as MANUAL.

Camera rules (computed by factory/direction/shot_validator.py with the renderer's own camera maths):
  CAN-C1  per location, a wide (WS/EWS) holding the hero, the boat and the island / tree line / fires in one
          composition comes before any hero coverage.
  CAN-C2  hero close-ups (CU/ECU at the median or at the end of the move) only on the shot the director marked
          reserved_close_up for its sequence (direction.reserved_close_up = beat id, or episode canon.reserved_close_up).
  CAN-H1  every impact shot (direction.impact / impact_handheld, or a camera shake >= 12 px) is reactive handheld:
          the subject is out of frame for 2-12 frames after the hit and the camera starts to catch up 2-10 frames
          late, then re-centres (camera_presets.impact_handheld).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CAMERA_RULES = ("CAN-C1", "CAN-C2", "CAN-H1")


def camera_rules(ep_path):
    sys.path.insert(0, os.path.join(ROOT, "factory", "direction"))
    import shot_validator as V  # noqa: E402
    V.load_coast(ROOT)
    rep = V.validate(json.load(open(ep_path)))
    out = {}
    for r in rep["rules"]:
        if r["id"] in CAMERA_RULES:
            out[r["id"]] = {"status": "PASS" if r["status"] == "pass" else "FAIL", "detail": r["detail"], "shots": r["shots"]}
    return out


def run_all(ep_path, plates=None, video=None):
    return camera_rules(ep_path)
