#!/usr/bin/env python3
"""Asset tier rule (lesson L008: the hero boat was a box-built placeholder in medium shots).

Catalog entries carry `tier`: placeholder | previs | hero. A shot whose camera comes closer than 10 m to an asset
(at any sampled frame) needs that asset at tier hero; a placeholder may only appear in previs. In previs the rule
warns (the boards are still useful), in final it blocks.

    python3 factory/direction/asset_tier.py episodes/sentinel/episode_v5.json [--mode final]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import camgeo as G  # noqa: E402

CATALOG = os.path.join(ROOT, "factory", "library", "catalog.json")
NEAR_M = 10.0
TIERS = ("placeholder", "previs", "hero")
# spec reference -> catalog id (actors[].asset, props[].prop, the shot's yacht)
REFS = {
    "actor:hero_v4": "int:hero_v4", "actor:jay": "bs:jay", "actor:hero": None,   # hero.glb (old Meshy hero): not catalogued
    "yacht": "int:yacht_14m",
    "prop:radio": "int:prop_radio", "prop:beacon": "int:prop_beacon", "prop:phone": "int:prop_phone", "prop:helm": "int:prop_helm",
    "prop:lamp": "int:prop_lamp", "prop:switches": "int:prop_switches", "prop:bag": "ph:trashbag",
    "prop:primrose": "int:prop_primrose", "prop:coastguard": "int:prop_coastguard_patrol", "prop:helicopter": "int:prop_helicopter_rescue",
    "prop:beach_torches": "int:prop_beach_torches", "prop:cargo_hold": "int:set_cargo_hold", "prop:rotor_wash": "int:fx_rotor_wash",
}
YACHT_HALF = (2.2, 7.0)   # body half-beam / half-length (m) for the nearest-point distance


def load_catalog(path=CATALOG):
    with open(path) as fh:
        return json.load(fh)["assets"]


def tier_of(ref, catalog):
    cid = REFS.get(ref)
    if cid is None:
        return None, "placeholder"           # not in the library at all: by definition a placeholder
    e = catalog.get(cid)
    if e is None:
        return cid, "placeholder"
    return cid, e.get("tier") or "unknown"


def _sample_frames(shot, step=3):
    f0, f1 = shot["from"], shot["to"] - 1
    fs = list(range(f0, f1 + 1, step))
    return fs + ([f1] if fs[-1] != f1 else [])


def shot_distances(shot):
    """-> {ref: min camera distance (m)} over sampled frames, for the yacht, actors and yacht/world props."""
    y = shot.get("yacht")
    out = {}

    def put(k, d):
        out[k] = min(out.get(k, 1e9), d)
    for f in _sample_frames(shot):
        cam = G.camera_world(shot, f, jitter=False)[0]
        yf = G.YachtFrame(y, f) if y else None
        body = yf.world_to_body(cam) if yf else None
        if body is not None:
            dx = max(0.0, abs(body[0]) - YACHT_HALF[0])
            dz = max(0.0, abs(body[2]) - YACHT_HALF[1])
            dy = max(0.0, body[1] - 4.5, -0.9 - body[1])
            put("yacht", (dx * dx + dy * dy + dz * dz) ** 0.5)
        for a in shot.get("actors") or []:
            if a.get("space", "yacht") == "yacht" and yf is None:
                continue
            loc = a["local"]
            h = a.get("height", 1.8)
            p = yf.body_to_world([loc[0], loc[1] + 0.72 * h, loc[2]]) if yf else [loc[0], loc[1] + 0.72 * h, loc[2]]
            put("actor:" + a.get("asset", "?"), G.norm(G.sub(cam, p)))
        for p in shot.get("props") or []:
            att = p.get("attach", "yacht")
            if att not in ("yacht", "world") or (att == "yacht" and yf is None):
                continue      # hand props travel with the actor (covered by the actor distance)
            loc = p.get("local", [0, 0, 0])
            w = yf.body_to_world(loc) if att == "yacht" else loc
            put("prop:" + p["prop"], G.norm(G.sub(cam, w)))
        for p in shot.get("props") or []:
            if p.get("attach") in ("handR", "handL") and "actor:hero_v4" in out:
                put("prop:" + p["prop"], out["actor:hero_v4"])
    return out


def check_episode(ep, mode="previs", catalog=None):
    """-> list of findings {shot, ref, catalog, tier, distance_m, severity} (severity warn|fail)."""
    catalog = catalog if catalog is not None else load_catalog()
    final = mode == "final"
    out = []
    for s in ep["shots"]:
        for ref, d in sorted(shot_distances(s).items()):
            cid, tier = tier_of(ref, catalog)
            if tier == "hero":
                continue
            if tier == "placeholder":
                out.append({"shot": s["id"], "ref": ref, "catalog": cid, "tier": tier, "distance_m": round(d, 2),
                            "severity": "fail" if final else "warn", "why": "placeholder on screen (previs only)"})
            elif d < NEAR_M:
                out.append({"shot": s["id"], "ref": ref, "catalog": cid, "tier": tier, "distance_m": round(d, 2),
                            "severity": "fail" if final else "warn", "why": f"camera {d:.1f} m < {NEAR_M} m needs tier hero"})
    return out


def tier_rule(ep, mode="previs", catalog=None):
    """shot_validator rule dict (id TIER)."""
    fs = check_episode(ep, mode, catalog)
    fails = [f for f in fs if f["severity"] == "fail"]
    status = "fail" if fails else ("warn" if fs else "pass")
    by = {}
    for f in fs:
        by.setdefault(f["ref"], []).append(f["shot"])
    detail = "; ".join(f"{r} ({next(x['tier'] for x in fs if x['ref'] == r)}): {len(v)} shots" for r, v in by.items()) or "all near assets are tier hero"
    return {"id": "TIER", "name": f"assets within {NEAR_M:.0f} m of the camera are tier hero; placeholders previs-only (mode {mode})",
            "status": status, "detail": detail, "shots": sorted({f["shot"] for f in fs}), "findings": fs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episode")
    ap.add_argument("--mode", choices=["previs", "final"], default="previs")
    a = ap.parse_args()
    r = tier_rule(json.load(open(a.episode)), a.mode)
    print(f"[{r['status'].upper()}] TIER {r['detail']}")
    for f in r["findings"][:40]:
        print(f"  {f['severity']:4} {f['shot']:5} {f['ref']:22} tier={f['tier']:11} {f['distance_m']:7.2f} m  {f['why']}")
    return 1 if r["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
