#!/usr/bin/env python3
"""Per-shot checks (no Blender, no render) run on EVERY shot of EVERY episode by factory/run before previs approval
and before render, and on every stress scenario (factory/goldens/stress):

  FRAME-CROP  the hero's head (top of skull .. chin, using the actual rig's head metrics) is inside the frame at the
              key frame (close-ups must not crop the face - L012)
  FRAME-EYES  on MCU/CU the eyes sit in the upper band y in [0.25, 0.47] (0 = top)
  COLLIDE     camera not inside yacht / prop geometry (mesh proxies, L012) and not below the ground on a set
  VIS         the hero is in front of the camera and on screen at the key frame
  TIER        (final quality only) assets within 10 m of the camera are tier hero (L008)

    python3 factory/direction/shot_checks.py <episode.json> [--quality final]   -> failing shots + rules
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import camgeo as G  # noqa: E402

# head landmarks as fractions of the standing height, measured on the rig (CloudRigPuppet.describe(): top 1.1323,
# eyes 0.9937, mouth 0.8438 of 1.1323 m for Jay/hero_v4); chin ~ mouth - 0.045. The old hero.glb is close to human.
LANDMARKS = {"hero_v4": {"top": 1.0, "eyes": 0.878, "chin": 0.70}, "jay": {"top": 1.0, "eyes": 0.878, "chin": 0.70},
             "default": {"top": 1.0, "eyes": 0.93, "chin": 0.86}}
# how far the head drops (fraction of height) in non-standing stances
STANCE_DROP = {"sit": 0.36, "down": 0.45}
EYE_BAND = (0.25, 0.47)


def _stance_at(a, f):
    st = "stand"
    for k in sorted((a.get("perf") or {}).get("stance") or [], key=lambda k: k[0]):
        if k[0] <= f:
            st = k[1]
    return st


def hero_actor(shot):
    acts = shot.get("actors") or []
    return next((a for a in acts if str(a.get("asset", "")).startswith("hero")), acts[0] if acts else None)


def head_points(shot, a, f):
    lm = LANDMARKS.get(a.get("asset"), LANDMARKS["default"])
    h = a.get("height", 1.8)
    st = _stance_at(a, f)
    drop = STANCE_DROP["sit"] if st.startswith("sit") else STANCE_DROP.get(st, 0.0)
    loc = a["local"]
    yf = G.YachtFrame(shot.get("yacht") if a.get("space", "yacht") == "yacht" else None, f)
    pt = lambda frac: yf.body_to_world([loc[0], loc[1] + h * (frac - drop), loc[2]])  # noqa: E731
    return {"top": pt(lm["top"]), "eyes": pt(lm["eyes"]), "chin": pt(lm["chin"]), "chest": pt(0.72 + drop * 0.2), "stance": st}


def check_shot(ep, shot, quality="preview"):
    """-> list of findings {shot, rule, status, measured, expected} (status pass|fail|skip)."""
    import mesh_proxy as _mp
    _mp.set_yacht_model(ep)
    W, H = ep.get("width", 1080), ep.get("height", 1920)
    aspect = W / H
    key = int(shot.get("keyFrame", (shot["from"] + shot["to"] - 1) // 2))
    out = []

    def add(rule, ok, measured, expected):
        out.append({"shot": shot["id"], "rule": rule, "status": "pass" if ok else "fail", "measured": measured, "expected": expected})
    a = hero_actor(shot)
    cam, look, fov, roll = G.camera_world(shot, key, jitter=False)
    subj = ((shot.get("direction") or {}).get("subject") or {}).get("kind", "hero")
    if a is not None and subj == "hero":     # place / object / insert shots frame something else on purpose
        hp = head_points(shot, a, key)
        proj = {k: G.project(cam, look, roll, fov, aspect, hp[k]) for k in ("top", "eyes", "chin", "chest")}
        vis = proj["chest"][0] is not None and 0.0 <= proj["chest"][0] <= 1.0 and 0.0 <= proj["chest"][1] <= 1.0
        add("VIS", vis, None if proj["chest"][0] is None else [round(proj["chest"][0], 3), round(proj["chest"][1], 3)], "hero chest on screen at the key frame")
        d = shot.get("direction") or {}
        exempt = bool(d.get("insert") or d.get("pov") or d.get("ots") or "OTS" in (d.get("size") or []))   # OTS frames the back of the head
        if vis and not exempt:
            t, c, e = proj["top"], proj["chin"], proj["eyes"]
            inside = all(p[0] is not None and -0.005 <= p[1] <= 1.005 and 0.03 <= p[0] <= 0.97 for p in (t, c))
            add("FRAME-CROP", inside, {"top_y": round(t[1], 3) if t[0] is not None else None, "chin_y": round(c[1], 3) if c[0] is not None else None},
                "top of head and chin inside the frame (rig head metrics)")
            depth = max(proj["eyes"][2] or 1e-3, 1e-3)
            size = G.classify_size(G.frame_height_at(depth, fov), a.get("height", 1.8))
            if size in ("MCU", "CU", "ECU") and e[0] is not None:
                add("FRAME-EYES", EYE_BAND[0] <= e[1] <= EYE_BAND[1], {"eye_y": round(e[1], 3), "size": size}, f"eyes y in {list(EYE_BAND)} on MCU/CU")
    # collisions
    import mesh_proxy
    hits = mesh_proxy.shot_hits(shot) if mesh_proxy.load("yacht") else []
    ground = None
    if not shot.get("yacht") and a is not None and a.get("space") == "set":
        f0 = shot["from"]
        ys = [G.camera_world(shot, f, jitter=False)[0][1] for f in range(f0, shot["to"], 3)]
        ground = min(ys) - a["local"][1]
    add("COLLIDE", not hits and (ground is None or ground > 0.15),
        {"inside": sorted({p for _, ps in hits for p in ps})[:4], "first_frame": hits[0][0] if hits else None,
         "min_height_above_mark": None if ground is None else round(ground, 3)},
        "camera outside yacht/prop proxies and >= 0.15 m above the set floor")
    if quality == "final":
        import asset_tier
        fs = [x for x in asset_tier.check_episode({"shots": [shot]}, "final") if x["severity"] == "fail"]
        add("TIER", not fs, [f"{x['ref']}({x['tier']}, {x['distance_m']} m)" for x in fs][:4], "near assets tier hero")
    return out


def check_episode(ep, quality="preview", shots=None):
    """-> {"findings": [...], "failing": {shot: [rules]}, "ok": bool}"""
    import mesh_proxy
    mesh_proxy.set_yacht_model(ep)
    fs = []
    for s in ep["shots"]:
        if shots and s["id"] not in shots:
            continue
        fs += check_shot(ep, s, quality)
    failing = {}
    for f in fs:
        if f["status"] == "fail":
            failing.setdefault(f["shot"], []).append(f["rule"])
    return {"findings": fs, "failing": failing, "ok": not failing}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episode")
    ap.add_argument("--quality", default="preview")
    a = ap.parse_args()
    r = check_episode(json.load(open(a.episode)), a.quality)
    for f in r["findings"]:
        if f["status"] == "fail":
            print(f"FAIL {f['shot']:22} {f['rule']:11} measured={json.dumps(f['measured'])}  ({f['expected']})")
    print(f"{len(r['failing'])} failing shot(s) of {len({f['shot'] for f in r['findings']})}")
    return 1 if r["failing"] else 0


if __name__ == "__main__":
    sys.exit(main())
