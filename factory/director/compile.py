"""Stage 4 compiler: shotplan.json (the director's decisions) + story + manifest -> episode.json for
cloud/blender/render_episode.py. Deterministic; the same shot plan always yields the same episode."""
import math
import os
import re

from . import camera as cam
from . import docuseries as doc
from . import text as tx
from .paths import EPISODE_SCHEMA
from .staging import ISLANDS, MARKS, PROP_DEFAULTS, shore_frame, yacht_state

FPS = 30
DEFAULT_HANDHELD, DEFAULT_DRIFT = 0.12, 0.08   # canon CAN-H1e: baseline handheld <= 0.12; shake is event-driven


def _point(p, isl, sf):
    fr, v = p["frame"], p["v"]
    if fr in ("yacht", "world", "set"):  # set: world-kit local = world (world_kits)
        return list(v)
    if fr == "shore":
        s, (ux, uz), (px, pz) = sf
        return [s[0] + ux * v[0] + px * v[2], v[1], s[1] + uz * v[0] + pz * v[2]]
    if fr == "island":
        return [isl["x"] + v[0], v[1], isl["z"] + v[2]]
    raise ValueError(fr)


def compile_camera(s, isl, marks=None):
    c = s["camera"]
    f0, f1 = s["from"], s["to"]
    if c["rig"] == "orbit":
        out = cam.orbit((marks or MARKS)[c["mark"]], f0, f1, c["az"], c["dist"], c["height"], c["fov"], c["ease"],
                        c.get("target", "chest"), tuple(c.get("aim", (0, 0, 0))))
        if marks is not None:
            out["space"] = "world"  # world_kits: kit marks are set-local = world
    else:
        sf = shore_frame(isl) if isl else None
        cams = [_point(p, isl, sf) for p in c["cam"]]
        looks = [_point(p, isl, sf) for p in c["look"]]
        out = cam.path(f0, f1, cams, looks, c["fov"], c["ease"], space=c.get("space", "world"))
    out["handheld"] = c.get("handheld", DEFAULT_HANDHELD)
    out["drift"] = c.get("drift", DEFAULT_DRIFT)
    if c.get("shakes"):
        out["shakes"] = c["shakes"]
    ih = s.get("impact_handheld")  # canon CAN-H1: reactive impact layer (camera_presets.impact_handheld_layer)
    if ih:
        out = _impact_layer(out, s, ih)
    return out


# >>> canon: CAN-H1 impact layer + CAN-P1 turn-then-change face scheduling ---------------------------------------------
def _impact_layer(camera, s, ih):
    import sys
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "direction")
    if d not in sys.path:
        sys.path.insert(0, d)
    import camera_presets as cp
    out = cp.impact_handheld_layer(camera, s["from"], s["to"], ih["impact_frame"], ih.get("escape_frames", 4), ih.get("lag_frames", 5),
                                   ih.get("recover_frames", 12), ih.get("amplitude_deg", 6.0), ih.get("direction", 1.0))
    out.pop("impact_window", None)
    return out


def _turn_windows(s):
    h = s.get("hero") or {}
    w = [(p["from"], p["from"] + int(p.get("in", 8))) for p in h.get("poses", []) if re.search(r"(look_|turn|glance)", p["pose"])]
    w += [(t["turn"]["from"], t["turn"]["to"]) for t in s.get("turn_then_change") or [] if t.get("turn")]
    return sorted(w)


def schedule_face(s, settle_min=6, blend_default=10):
    """Turn, settle, then change (Animation Mentor p.19): emotion keys + blinks for the shot's turn_then_change entries.
    A face change that would land inside a head turn (declared turn or a look_/turn pose's `in` window) is delayed until
    `settle_frames` (>= settle_min) after that turn settles; a thought blink lands 1 f before the change, and a fast turn
    (>= 45 deg in <= 10 f) gets a blink at 75 % of the turn. Returns the cloudrig face_spec dict or None."""
    tts = s.get("turn_then_change") or []
    if not tts:
        return None
    emo, blinks, blend = [[s["from"], tts[0].get("emotion_from") or (s.get("hero") or {}).get("emotion") or "neutral"]], [], blend_default
    wins = _turn_windows(s)
    for t in tts:
        tr, ch = t["turn"], t["change"]
        n = max(1, ch["to"] - ch["from"])
        blend = max(6, n)
        start = ch["from"]
        if t.get("mode") != "pre_turn":
            settle = max(settle_min, int(t.get("settle_frames", settle_min)))
            start = max(start, tr["to"] + settle)
            for a, b in wins:            # never inside any other head turn either
                if start < b and start + blend > a:
                    start = b + settle
        emo.append([start, t.get("emotion_to") or "neutral"])
        if not t.get("no_blink"):
            blinks.append(start - 1)
        deg = abs(tr.get("deg") or 0)
        if deg >= 45 and tr["to"] - tr["from"] <= 10:
            blinks.append(int(round(tr["from"] + 0.75 * (tr["to"] - tr["from"]))))
    return {"emotion": emo, "blinks": sorted(set(blinks)), "blend": blend, "seed": (s.get("hero") or {}).get("seed", 1)}
# <<< canon ------------------------------------------------------------------------------------------------------------


def compile_hero(h, marks=None, space="yacht"):
    mark = (marks or MARKS)[h["mark"]]
    stance = [[-10000, h["stance"]]] + [list(x) for x in h.get("stance_changes", [])]
    poses = [{"pose": p["pose"], "from": p["from"], "to": p["to"], "in": p.get("in", 8), "out": p.get("out", 10),
              "ease": p.get("ease", "smooth")} for p in h.get("poses", [])]
    verbs = [{"verb": v["verb"], "at": v["at"], "dur": v.get("dur", 24), "amount": v.get("amount", 1.0)} for v in h.get("verbs", [])]
    perf = {"stance": stance, "poses": poses, "verbs": verbs, "breath": h.get("breath", 1.0), "seed": h.get("seed", 1), "blend": 12}
    return [{"asset": "hero", "space": space, "local": list(mark["local"]), "rotY": round(mark["rotY"], 5), "height": 1.8,
             "perf": perf, "tracks": [{"clip": "none", "from": 0}]}]


def compile_prop(p):
    out = {"prop": p["prop"], "attach": p["attach"]}
    out.update(PROP_DEFAULTS.get((p["prop"], p["attach"]), {}))
    out.update({k: v for k, v in p.items() if k not in ("prop", "attach")})
    return out


# >>> world_kits: a shot on a world-kit set
def shot_kit(s, world_set=None):
    from factory.worlds import kits
    k = s.get("set") or world_set
    if not k:
        return None
    kit = kits.load(k)
    return None if kit.get("legacy") else kit


def compile_set_shot(s, kit):
    from factory.worlds import layout
    seed = s.get("set_seed", kit.get("seed", 0))
    marks = layout.marks(kit, seed)
    out = {"id": s["id"], "title": s["title"], "from": s["from"], "to": s["to"],
           "keyFrame": s.get("key_frame", (s["from"] + s["to"]) // 2), "camera": compile_camera(s, None, marks),
           "set": {"kit": kit["id"], "seed": seed, "ambience": [a["id"] for a in kit.get("ambience", [])]},
           "island": None,
           "lighting": {"preset": kit["lighting"]["preset"], **(kit["lighting"].get("overrides") or {})},
           "env": {"moonDir": list(kit["sky"]["key_dir"]), "dawn": float(kit["sky"].get("dawn", 0.0)), **(s.get("env") or {})}}
    out["env"].pop("seaState", None)
    if s.get("hero"):
        out["actors"] = compile_hero(s["hero"], marks, "set")
        face = schedule_face(s)  # canon CAN-P1
        if face:
            out["actors"][0]["perf"]["face"] = face
    if s.get("impact_handheld"):  # canon CAN-H1f
        out["impact_handheld"] = dict(s["impact_handheld"])
    if s.get("props"):
        out["props"] = [compile_prop(p) for p in s["props"]]
    return out
# <<< world_kits


def compile_shot(s, world_island, world_set=None):
    kit = shot_kit(s, world_set)
    if kit is not None:
        return compile_set_shot(s, kit)
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
        face = schedule_face(s)  # canon CAN-P1
        if face:
            out["actors"][0]["perf"]["face"] = face
    if s.get("impact_handheld"):  # canon CAN-H1f: the window travels with the shot for the validator / QC
        out["impact_handheld"] = dict(s["impact_handheld"])
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


def _series_defaults():
    f = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "series", os.environ.get("FACTORY_SERIES", "default") + ".json")
    if os.environ.get("FACTORY_SERIES") == "none" or not os.path.isfile(f):
        return None
    import json as _json
    return _json.load(open(f))


def compile_episode(plan, story, manifest, out_dir):
    shots = [compile_shot(s, plan["world"]["island"], plan["world"].get("set")) for s in plan["shots"]]
    chars, props = {}, {}
    for e in manifest["entries"]:
        rk = e.get("render_key", "")
        if rk.startswith("characters/"):
            chars[rk.split("/", 1)[1]] = _glb_for(e)
        elif rk.startswith("props/"):
            props[rk.split("/", 1)[1]] = _glb_for(e)
    # series defaults (lesson L021): bind the current hero-tier assets, never superseded placeholders
    series = _series_defaults()
    if series:
        hk = series["hero"]["key"]
        chars.pop("hero", None)
        chars[hk] = series["hero"]["entry"]
        for sh in shots:
            for a in sh.get("actors") or []:
                if a.get("asset") == "hero":
                    a["asset"] = hk
        props.update(series.get("props", {}))
    eid = story["id"]
    w = plan["world"]
    fmt = story.get("format", "short")
    W, H = doc.frame_size(fmt)
    ep = {
        "$schema": os.path.relpath(EPISODE_SCHEMA, os.path.abspath(out_dir)).replace(os.sep, "/"),
        "version": 1, "id": eid, "title": story["title"], "fps": FPS, "width": W, "height": H,
        "durationFrames": shots[-1]["to"],
        "audio": {"narration": f"episodes/{eid}/audio/narration.mp3", "wordsJson": f"episodes/{eid}/audio/narration.words.json",
                  "offsetFrames": plan["audio_offset_frames"]},
        "world": {"moonDir": w["moonDir"], "seaState": w["seaState"], "dawn": w["dawn"], "island": dict(ISLANDS[w["island"]]) if w["island"] else None},
        "assets": {"characters": chars, "motions": {}, "props": props},
        "captions": captions(story, plan["audio_offset_frames"]),
        "shots": shots,
        "source": {"builder": "factory/director (stage 4)", "story": "story.json", "shotplan": "shotplan.json", "manifest": "manifest.json"},
    }
    if fmt == "docuseries":
        _dual_frame(ep, plan, story)
    if w.get("set"):  # world_kits
        ep["world"]["set"] = {"kit": w["set"]}
    return ep


def _dual_frame(ep, plan, story):
    """docuseries: every shot tagged short_candidate records a second 9:16 camera (cameras.vertical) derived from the
    16:9 one; ep.shorts lists each candidate in film frames with the shots that cover it."""
    ep["format"] = "docuseries"
    ep["vertical"] = {"width": doc.VERTICAL[0], "height": doc.VERTICAL[1]}
    by_id = {s["id"]: s for s in ep["shots"]}
    for ps in plan["shots"]:
        s = by_id[ps["id"]]
        if not ps.get("short_candidate"):
            continue
        s["short_candidate"] = ps["short_candidate"]
        if ps.get("vertical"):
            s["vertical"] = ps["vertical"]
        s["cameras"] = {"main": s["camera"], "vertical": doc.vertical_camera(s, s["camera"], ps.get("vertical"))}
    off = plan["audio_offset_frames"]
    shorts = []
    for sc in doc.candidates(story):
        f0, f1 = doc.candidate_frames(sc, off)
        shorts.append({"id": sc["id"], "chapter": sc["chapter"], "from": f0, "to": f1, "hook_line": sc["hook_line"],
                       "setup": sc["setup"], "turn": sc["turn"], "payoff": sc["payoff"],
                       "shots": [s["id"] for s in ep["shots"] if s.get("short_candidate") == sc["id"]]})
    ep["shorts"] = shorts


def _glb_for(entry):
    from .librarian import load_render_assets
    reg = load_render_assets()
    return reg.get(entry.get("catalog_id", ""), {}).get("file", f"assets/{entry['element']}.glb")
