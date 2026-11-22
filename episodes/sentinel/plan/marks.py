"""
marks.py - the Sentinel yacht marks in one place (re-exports cloud/blender/yacht_marks.py for the episode builders).

  from marks import MARKS, HELM, SWITCH, RAIL, BOW, COCKPIT, SITMARK, BENCH

MARKS follows the yacht the episode uses: build_v5.YACHT / $SENTINEL_YACHT ('proc:yacht_v2' by default -> MARKS_V2;
'assets/props/yacht.glb' -> MARKS_V1).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "cloud", "blender"))
from yacht_marks import MARKS_V1, MARKS_V2, remap, move_point  # noqa: E402,F401

YACHT = os.environ.get("SENTINEL_YACHT", "proc:yacht_v2")
MARKS = MARKS_V2 if YACHT.startswith("proc:yacht_v2") else MARKS_V1
HELM, SWITCH, RAIL, BOW, COCKPIT, SITMARK = (MARKS[k] for k in ("HELM", "SWITCH", "RAIL", "BOW", "COCKPIT", "SITMARK"))
BENCH = MARKS.get("BENCH")
