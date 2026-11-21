"""Technical checks on rendered plates (`<plates>/<SHOT>/<frame:04d>.png` + `_render_*.json`).

Per frame: decodes, non-finite values, fully black, clipped highlights, Blender's magenta
missing-texture colour. Across frames: resolution consistency (and manifest match, 9:16),
frame-to-frame luminance flicker inside a shot that no keyed light change or camera shake
explains, and frame coverage of the manifests and of the episode.
"""
from __future__ import annotations

import glob
import json
import os
import re

import numpy as np

from .common import FAIL, PASS, WARN, check, rnd, rule, skip

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def load_plate(path):
    from PIL import Image
    im = Image.open(path)
    im.load()
    if im.mode in ("I;16", "I;16B", "I"):
        a = np.asarray(im, dtype=np.float32) / 65535.0
        a = np.stack([a] * 3, -1)
    elif im.mode == "F":
        a = np.asarray(im, dtype=np.float32)
        a = np.stack([a] * 3, -1)
    else:
        a = np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0
    return a


def frame_stats(a):
    finite = np.isfinite(a)
    nonfinite = float(1 - finite.mean())
    a = np.where(finite, a, 0.0)
    y = a[..., :3] @ LUMA
    clipped = float((a[..., :3].max(-1) >= 0.995).mean())
    magenta = float(((a[..., 0] > 0.9) & (a[..., 1] < 0.1) & (a[..., 2] > 0.9)).mean())
    return {"mean": float(y.mean()), "p995": float(np.percentile(y, 99.5)), "clipped": clipped, "magenta": magenta, "nonfinite": nonfinite,
            "size": (a.shape[1], a.shape[0])}


def discover(plates_dir):
    """-> {shot_id: {"frames": {f: path}, "manifests": [dict]}} (also accepts a flat dir of ####.png)."""
    out = {}
    flat = sorted(glob.glob(os.path.join(plates_dir, "*.png")))
    dirs = [d for d in sorted(glob.glob(os.path.join(plates_dir, "*"))) if os.path.isdir(d)]
    groups = [("_flat", plates_dir, flat)] if flat else []
    groups += [(os.path.basename(d), d, sorted(glob.glob(os.path.join(d, "*.png")))) for d in dirs]
    for sid, d, pngs in groups:
        frames = {}
        for p in pngs:
            m = re.search(r"(\d+)\.png$", os.path.basename(p))
            if m:
                frames[int(m.group(1))] = p
        mans = []
        for mp in sorted(glob.glob(os.path.join(d, "_render_*.json"))):
            try:
                with open(mp) as fh:
                    mans.append(json.load(fh))
            except (OSError, ValueError):
                mans.append({"_broken": mp})
        if frames or mans:
            out[sid] = {"frames": frames, "manifests": mans}
    return out


def _light_events(shot, fps):
    """Frames where the episode itself changes the light or shakes the camera (flicker allowed)."""
    ev = set()
    if not shot:
        return ev
    lk = (shot.get("yacht") or {}).get("lights")
    if isinstance(lk, list):
        ks = sorted(lk, key=lambda k: k[0])
        for (f0, v0), (f1, v1) in zip(ks, ks[1:]):
            if abs(v1 - v0) > 0.05:
                ev.update(range(int(f0), int(f1) + 1))
    for sh in (shot.get("camera") or {}).get("shakes") or []:
        ev.update(range(int(sh["at"]), int(sh["at"] + sh["tau"] * 6) + 1))
    for f, _ in shot.get("fires") or []:
        ev.update(range(int(f), int(f) + 12))
    return ev


def plate_checks(plates_dir, ep=None, partial=False, flicker_rel=0.25, flicker_abs=0.01):
    found = discover(plates_dir)
    if not found:
        return [rule("TQ-PLATE-COUNT", "TECH", FAIL, 0, "plates present", f"no plates under {plates_dir}")], {}
    shots = {s["id"]: s for s in (ep.shots if ep else [])}
    fps = ep.fps if ep else 30.0
    stats, decode_err = {}, []
    for sid, g in found.items():
        for f, p in sorted(g["frames"].items()):
            try:
                stats[(sid, f)] = frame_stats(load_plate(p))
            except Exception as e:  # noqa: BLE001 - any decode failure is a QC failure
                decode_err.append(f"{p}: {e}")
    out = [check("TQ-PLATE-DECODE", "TECH", not decode_err, f"{len(stats)} decoded", "every plate decodes", decode_err[:10] or None)]
    nonfin = [f"{s}/{f}" for (s, f), v in stats.items() if v["nonfinite"] > 0]
    out.append(check("TQ-PLATE-NAN", "TECH", not nonfin, len(nonfin), "no NaN/inf pixels", nonfin[:10] or None))
    black = [f"{s}/{f}" for (s, f), v in stats.items() if v["p995"] < 0.01]
    out.append(check("TQ-PLATE-BLACK", "TECH", not black, len(black), "no fully black frame (luma p99.5 >= 0.01)", black[:10] or None))
    over = [f"{s}/{f} ({rnd(v['clipped'] * 100, 2)}%)" for (s, f), v in stats.items() if v["clipped"] > 0.02]
    out.append(check("TQ-PLATE-OVEREXPOSED", "TECH", not over, len(over), "<= 2% clipped pixels per frame", over[:10] or None))
    mag = [f"{s}/{f}" for (s, f), v in stats.items() if v["magenta"] > 0.001]
    out.append(check("TQ-PLATE-MISSING-TEX", "TECH", not mag, len(mag), "no Blender missing-texture magenta (> 0.1% of pixels)", mag[:10] or None))
    # resolution
    sizes = {v["size"] for v in stats.values()}
    man_res = {tuple(m["resolution"]) for g in found.values() for m in g["manifests"] if "resolution" in m}
    aspect_ok = all(abs(w / h - 9 / 16) < 0.01 for w, h in sizes)
    res_ok = len(sizes) == 1 and aspect_ok and (not man_res or sizes <= man_res)
    out.append(check("TQ-PLATE-RES", "TECH", res_ok, sorted(sizes), "one resolution, 9:16, equal to the render manifests",
                     {"manifests": sorted(man_res), "final_1080x1920": sizes == {(1080, 1920)}}))
    # flicker
    flick = []
    for sid, g in found.items():
        fr = sorted(f for f in g["frames"] if (sid, f) in stats)
        allowed = _light_events(shots.get(sid), fps)
        for a, b in zip(fr, fr[1:]):
            if b != a + 1:
                continue
            ya, yb = stats[(sid, a)]["mean"], stats[(sid, b)]["mean"]
            d = abs(yb - ya)
            if d > flicker_abs and d / max(ya, yb, 0.02) > flicker_rel and b not in allowed:
                flick.append({"shot": sid, "frames": [a, b], "luma": [rnd(ya, 4), rnd(yb, 4)]})
    pairs = sum(1 for sid, g in found.items() for f in g["frames"] if f + 1 in g["frames"])
    if pairs == 0:
        out.append(skip("TQ-PLATE-FLICKER", "TECH", "no consecutive frames to compare"))
    else:
        out.append(check("TQ-PLATE-FLICKER", "TECH", not flick, f"{len(flick)} jumps in {pairs} pairs",
                         f"frame-to-frame luma change <= {int(flicker_rel * 100)}% (or <= {flicker_abs}) unless a keyed light/shake/fire event", flick[:10] or None))
    # coverage
    missing_man = []
    for sid, g in found.items():
        for m in g["manifests"]:
            if "frames" in m:
                for f in range(m["frames"][0], m["frames"][1] + 1):
                    if f not in g["frames"]:
                        missing_man.append(f"{sid}/{f:04d}")
    out.append(check("TQ-PLATE-MANIFEST", "TECH", not missing_man, len(missing_man), "every frame a render manifest lists exists", missing_man[:10] or None))
    if ep:
        expect = {(s["id"], f) for s in ep.shots for f in range(s["from"], s["to"])}
        have = {(sid, f) for sid, g in found.items() for f in g["frames"]}
        cov = len(expect & have) / len(expect) if expect else 0.0
        extra = sorted(f"{s}/{f}" for s, f in have - expect)
        status = PASS if cov == 1.0 and not extra else (WARN if partial and not extra else FAIL)
        out.append(rule("TQ-PLATE-COUNT", "TECH", status, {"coverage": rnd(cov, 4), "frames": len(have), "expected": len(expect)},
                        "every episode frame rendered under its shot id" + (" (partial run: coverage is a warning)" if partial else ""),
                        {"not_in_episode": extra[:10]} if extra else None))
    warns = [f"{sid}: {w}" for sid, g in found.items() for m in g["manifests"] for w in m.get("warnings", [])]
    out.append(rule("TQ-PLATE-RENDER-WARNINGS", "TECH", WARN if warns else PASS, len(warns), "no renderer warnings", warns[:10] or None))
    per_frame = {f"{s}/{f:04d}": {k: (rnd(v, 4) if k != "size" else v) for k, v in st.items()} for (s, f), st in sorted(stats.items())}
    return out, per_frame
