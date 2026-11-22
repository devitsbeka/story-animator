"""canon CAN-P1 'turn, then change' check over an episode spec (no Blender needed).

  python3 cloud/blender/test/can_p1_check.py episodes/sentinel/episode_v5.json

For every actor with a perf + face emotion keys: lists head turns (cloudrig_adapter.head_turns), the authored keys
that would land inside a turn, and the keys after cloudrig_adapter.turn_then_change (what bake() really plays).
Exit 1 if any baked expression change (cross-fade start .. +blend*0.6) still overlaps a head turn.
"""
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
if "bpy" not in sys.modules:                        # pure-python use of acting / cloudrig_adapter timing helpers
    sys.modules["bpy"] = types.ModuleType("bpy")
    mu = types.ModuleType("mathutils")
    for n in ("Euler", "Matrix", "Quaternion", "Vector"):
        setattr(mu, n, object)
    sys.modules["mathutils"] = mu
import cloudrig_adapter as cra  # noqa: E402


def overlaps(k, turns, ramp):
    return [t for t in turns if t[0] <= k[0] + ramp * 0.6 and k[0] <= t[1]]


def main(path):
    spec = json.load(open(path))
    bad = moved = 0
    for sh in spec["shots"]:
        for a in sh.get("actors", []):
            perf, fs = a.get("perf"), a.get("face") or {}
            keys = fs.get("emotion") or []
            if not perf or len(keys) < 2:
                continue
            f0, f1 = sh["from"] - 1, sh["to"] + 1
            turns = cra.head_turns(perf, f0, f1)
            fixed = cra.turn_then_change(cra.sync_sneeze(fs, perf), perf, f0, f1)["emotion"]
            ramp = fs.get("blend", 10)
            for raw, k in zip(keys, fixed):
                if raw[1] in cra.STARE + cra.EYES_SHUT or k is fixed[0]:
                    continue
                if k[0] != raw[0]:
                    moved += 1
                    print(f"{sh['id']}: '{raw[1]}' {raw[0]} -> {k[0]} (turns {turns})")
                if overlaps(k, turns, ramp):
                    bad += 1
                    print(f"FAIL {sh['id']}: '{k[1]}' at {k[0]} still inside a head turn {overlaps(k, turns, ramp)}")
    print(f"CAN-P1 {'FAIL' if bad else 'PASS'}: {moved} key(s) re-timed off head turns, {bad} still overlapping")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "..", "..", "episodes", "sentinel", "episode_v5.json")))
