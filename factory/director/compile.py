"""Stage 4 compiler: shotplan.json (the director's decisions) + story + manifest -> episode.json for
cloud/blender/render_episode.py. Deterministic; the same shot plan always yields the same episode."""
import math
import os
import re

from . import camera as cam
from . import text as tx
from .paths import EPISODE_SCHEMA
from .staging import ISLANDS, MARKS, PROP_DEFAULTS, shore_frame, yacht_state

FPS = 30
DEFAULT_HANDHELD, DEFAULT_DRIFT = 0.15, 0.08


def _point(p, isl, sf):
    fr, v = p["frame"], p["v"]
    if fr in ("yacht", "world"):
        return list(v)
    if fr == "shore":
        s, (ux, uz), (px, pz) = sf
        return [s[0] + ux * v[0] + px * v[2], v[1], s[1] + uz * v[0] + pz * v[2]]
    if fr == "island":
        return [isl["x"] + v[0], v[1], isl["z"] + v[2]]
    raise ValueError(fr)


def compile_camera(s, isl):
    c = s["camera"]
    f0, f1 = s["from"], s["to"]
    if c["rig"] == "orbit":
        out = cam.orbit(MARKS[c["mark"]], f0, f1, c["az"], c["dist"], c["height"], c["fov"], c["ease"],
                        c.get("target", "chest"), tuple(c.get("aim", (0, 0, 0))))
    else:
        sf = shore_frame(isl) if isl else None
        cams = [_point(p, isl, sf) for p in c["cam"]]
        looks = [_point(p, isl, sf) for p in c["look"]]
        out = cam.path(f0, f1, cams, looks, c["fov"], c["ease"], space=c.get("space", "world"))
    out["handheld"] = c.get("handheld", DEFAULT_HANDHELD)
    out["drift"] = c.get("drift", DEFAULT_DRIFT)
    if c.get("shakes"):
        out["shakes"] = c["shakes"]
    return out


def compile_hero(h):
    mark = MARKS[h["mark"]]
    stance = [[-10000, h["stance"]]] + [list(x) for x in h.get("stance_changes", [])]
    poses = [{"pose": p["pose"], "from": p["from"], "to": p["to"], "in": p.get("in", 8), "out": p.get("out", 10),
              "ease": p.get("ease", "smooth")} for p in h.get("poses", [])]
    verbs = [{"verb": v["verb"], "at": v["at"], "dur": v.get("dur", 24), "amount": v.get("amount", 1.0)} for v in h.get("verbs", [])]
    perf = {"stance": stance, "poses": poses, "verbs": verbs, "breath": h.get("breath", 1.0), "seed": h.get("seed", 1), "blend": 12}
    return [{"asset": "hero", "space": "yacht", "local": list(mark["local"]), "rotY": round(mark["rotY"], 5), "height": 1.8,
             "perf": perf, "tracks": [{"clip": "none", "from": 0}]}]


def compile_prop(p):
    out = {"prop": p["prop"], "attach": p["attach"]}
    out.update(PROP_DEFAULTS.get((p["prop"], p["attach"]), {}))
    out.update({k: v for k, v in p.items() if k not in ("prop", "attach")})
    return out


def compile_shot(s, world_island):
    isl_name = s["island"]
    isl = dict(ISLANDS[isl_name]) if isl_name else None
    ys = dict(s["yacht"])
    if ys["state"] == "leaving":
        sf = shore_frame(isl or ISLANDS[world_island])
        a, b = ys["offset"]
        (ux, uz), (px, pz) = sf[1], sf[2]
        ys["offset"] = [ux * a + px * b, uz * a + pz * b]
    out = {"id": s["id"], "title": s["title"], "from": s["from"], "to": s["to"],
           "keyFrame": s.get("key_frame", (s["from"] + s["to"]) // 2), "camera": compile_camera(s, isl)}
    y = yacht_state(ys, s["from"])
    if y is not None:
        out["yacht"] = y
    out["island"] = isl
    if s.get("hero"):
        out["actors"] = compile_hero(s["hero"])
    if s.get("props"):
        out["props"] = [compile_prop(p) for p in s["props"]]
    if s.get("fires"):
        out["fires"] = s["fires"]
    if s.get("env"):
        out["env"] = s["env"]
    return out


def captions(story, offset):
    """One caption per narration sentence group: context words small, the last word big; threat words red."""
    caps = []
    threat = tx.lex("threat") + ["died", "deadly", "dead", "stuck", "never", "not"]
    for ln in story["narration"]:
        ws = tx.words(re.sub(r"\[[^\]]*\]", "", ln["text"]))
        if not ws:
            continue
        f0, f1 = offset + round(ln["t0"] * FPS), offset + round(ln["t1"] * FPS)
        c = {"from": f0, "to": max(f1, f0 + 1), "small": " ".join(ws[:-1][-4:]).lower(), "big": ws[-1].lower(), "at": "top"}
        if tx.count_lexicon(ln["text"], threat, stems=True):
            c["tone"] = "red"
        caps.append(c)
    return caps


def compile_episode(plan, story, manifest, out_dir):
    shots = [compile_shot(s, plan["world"]["island"]) for s in plan["shots"]]
    chars, props = {}, {}
    for e in manifest["entries"]:
        rk = e.get("render_key", "")
        if rk.startswith("characters/"):
            chars[rk.split("/", 1)[1]] = _glb_for(e)
        elif rk.startswith("props/"):
            props[rk.split("/", 1)[1]] = _glb_for(e)
    eid = story["id"]
    w = plan["world"]
    ep = {
        "$schema": os.path.relpath(EPISODE_SCHEMA, os.path.abspath(out_dir)).replace(os.sep, "/"),
        "version": 1, "id": eid, "title": story["title"], "fps": FPS, "width": 1080, "height": 1920,
        "durationFrames": shots[-1]["to"],
        "audio": {"narration": f"episodes/{eid}/audio/narration.mp3", "wordsJson": f"episodes/{eid}/audio/narration.words.json",
                  "offsetFrames": plan["audio_offset_frames"]},
        "world": {"moonDir": w["moonDir"], "seaState": w["seaState"], "dawn": w["dawn"], "island": dict(ISLANDS[w["island"]]) if w["island"] else None},
        "assets": {"characters": chars, "motions": {}, "props": props},
        "captions": captions(story, plan["audio_offset_frames"]),
        "shots": shots,
        "source": {"builder": "factory/director (stage 4)", "story": "story.json", "shotplan": "shotplan.json", "manifest": "manifest.json"},
    }
    return ep


def _glb_for(entry):
    from .librarian import load_render_assets
    reg = load_render_assets()
    return reg.get(entry.get("catalog_id", ""), {}).get("file", f"assets/{entry['element']}.glb")
