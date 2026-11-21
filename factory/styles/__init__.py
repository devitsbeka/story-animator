"""Styles as data: load a house style and stamp it onto an episode.

    from factory.styles import load_style, apply_style_to_episode
    style = load_style("pixar_night_survival")
    ep2 = apply_style_to_episode(ep, style)          # new dict; ep is not modified

A style is `factory/styles/<id>.json`, validated against `style.schema.json` plus semantic checks against the code
that consumes it (lighting presets and parameters in cloud/blender/lighting.py, camera moves in
factory/direction/camera_presets.py, finish transitions). `apply_style_to_episode` writes:

  episode.style            the resolved style (minus prose); consumers read it:
                             cloud/blender/lighting.py      style.lighting.time_of_day -> preset when none is explicit
                             cloud/blender/render_episode   style.look (AgX view transform, look, exposure)
                             factory/finish/make_plates_manifest.py -> Finish props grade / captionStyle / transitions
                             factory/sound/designer.py      style.music (bpm, key, SFX density)
  episode.world.lighting   {preset, sequences: {<seq>: {preset, fill_ratio, ...}}} from the style's time-of-day table
                           (explicit episode values win unless override_lighting=True)
  episode.fps              the style's fps; every frame field is retimed (factory/styles/retime.py)
  camera handheld          scaled by style.camera.handheld.default / HOUSE_HANDHELD (softer motion for documentary)

CLI: python -m factory.styles list | show <id> | apply --episode E --style S --out O | check <episode.json>
"""
from __future__ import annotations

import copy
import functools
import importlib.util
import json
import os

from .retime import retime_episode

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SCHEMA_PATH = os.path.join(HERE, "style.schema.json")
DEFAULT_BY_FORMAT = {"short": "pixar_night_survival", "docuseries": "documentary_naturalistic"}
HOUSE_HANDHELD = 0.12  # the camera_presets.py default every existing episode was directed with
FINISH_TRANSITIONS = ("cut", "push", "whip")  # studio/src/finish/types.ts Transition
PROSE_KEYS = ("$schema", "description")


class StyleError(ValueError):
    pass


# ------------------------------------------------------------------ consumers' code (pure python imports)
@functools.lru_cache(maxsize=1)
def lighting_module():
    """cloud/blender/lighting.py imported without bpy (its pure-python half)."""
    path = os.path.join(REPO, "cloud", "blender", "lighting.py")
    spec = importlib.util.spec_from_file_location("_style_lighting", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _camera_moves():
    from factory.direction import camera_presets as cp  # noqa: WPS433 (lazy: pulls numpy-free geometry only)
    return {n for n in dir(cp) if callable(getattr(cp, n)) and not n.startswith("_")}


# ------------------------------------------------------------------ load / validate
def list_styles():
    return sorted(f[:-5] for f in os.listdir(HERE) if f.endswith(".json") and not f.endswith(".schema.json"))


def style_path(style_id):
    if os.path.isfile(style_id):
        return os.path.abspath(style_id)
    p = os.path.join(HERE, f"{style_id}.json")
    if not os.path.isfile(p):
        raise StyleError(f"unknown style '{style_id}' (have: {', '.join(list_styles())})")
    return p


def validate_style(style):
    """List of problems (empty = valid): JSON schema, then semantic checks against the consuming code."""
    import jsonschema

    errs = []
    schema = json.load(open(SCHEMA_PATH))
    v = jsonschema.Draft202012Validator(schema)
    for e in sorted(v.iter_errors(style), key=lambda e: list(e.path)):
        errs.append(f"schema /{'/'.join(str(p) for p in e.path)}: {e.message}")
    if errs:
        return errs
    L = lighting_module()
    lt = style["lighting"]
    if lt["default_preset"] not in L.PRESETS:
        errs.append(f"lighting.default_preset '{lt['default_preset']}' is not a lighting.py preset")
    for tod, entry in lt["time_of_day"].items():
        if entry["preset"] not in L.PRESETS:
            errs.append(f"lighting.time_of_day.{tod}.preset '{entry['preset']}' is not a lighting.py preset")
        for k in entry:
            if k != "preset" and k not in L.BASE:
                errs.append(f"lighting.time_of_day.{tod}.{k} is not a lighting.py preset parameter")
    for mood, (lo, hi) in lt["key_fill"].items():
        if lo > hi:
            errs.append(f"lighting.key_fill.{mood}: min {lo} > max {hi}")
    moves = _camera_moves()
    for m in style["camera"]["vocabulary"] + style["camera"].get("avoid", []):
        if m not in moves:
            errs.append(f"camera move '{m}' is not in factory/direction/camera_presets.py")
    if set(style["camera"]["vocabulary"]) & set(style["camera"].get("avoid", [])):
        errs.append("camera.vocabulary and camera.avoid overlap")
    tr = style["transitions"]
    if tr["default"] not in tr["vocabulary"]:
        errs.append(f"transitions.default '{tr['default']}' not in transitions.vocabulary")
    m = style["music"]
    if not m["bpm_range"][0] <= m["bpm"] <= m["bpm_range"][1]:
        errs.append(f"music.bpm {m['bpm']} outside bpm_range {m['bpm_range']}")
    lo, hi = style["narration"]["wps"]
    if lo > hi:
        errs.append(f"narration.wps min {lo} > max {hi}")
    c = style["captions"]
    sf = c["safe"]
    if not (0 <= sf["x0"] < sf["x1"] <= 1080 and 0 <= sf["y0"] < sf["y1"] <= 1920):
        errs.append(f"captions.safe {sf} is not inside the 1080x1920 canvas")
    if "band" in c and not (sf["y0"] <= c["band"]["y0"] < c["band"]["y1"] <= sf["y1"]):
        errs.append(f"captions.band {c['band']} is not inside captions.safe")
    lens = style["lens"]
    if "range_mm" in lens:
        a, b = lens["range_mm"]
        bad = [k for k, mm in {**lens["by_emotion"], **lens["by_size"]}.items() if not a <= mm <= b]
        if bad:
            errs.append(f"lens values outside range_mm {lens['range_mm']}: {bad}")
    return errs


def _fill_defaults(style):
    s = copy.deepcopy(style)
    s.setdefault("formats", [])
    s["grade"].setdefault("coolShadows", 1.0)
    c = s["captions"]
    c.setdefault("stroke", None)
    c.setdefault("stroke_em", 0.0)
    c.setdefault("shadow", False)
    c.setdefault("pop", 1.0)
    c.setdefault("plate", None)
    c.setdefault("band", {"y0": c["safe"]["y0"], "y1": c["safe"]["y1"]})
    c.setdefault("paging", {})
    c["paging"] = {"max_words": 3, "max_chars_3": 14, "max_page_s": 1.2, **c["paging"]}
    s["camera"].setdefault("drift", 0.05)
    s["camera"].setdefault("avoid", [])
    s["music"].setdefault("energy_max", 5)
    sd = s["music"]["sfx_density"]
    sd.setdefault("whoosh_on_cuts", True)
    sd.setdefault("ui_ticks", True)
    return s


@functools.lru_cache(maxsize=32)
def _load_cached(path, mtime):
    with open(path) as fh:
        raw = json.load(fh)
    errs = validate_style(raw)
    if errs:
        raise StyleError(f"style {os.path.basename(path)} is invalid:\n  " + "\n  ".join(errs))
    return _fill_defaults(raw)


def load_style(style_id):
    """Validated, defaults-filled style dict (a fresh copy each call). `style_id` is an id or a path to a json."""
    p = style_path(style_id)
    return copy.deepcopy(_load_cached(p, os.path.getmtime(p)))


def default_style_for_format(fmt):
    return DEFAULT_BY_FORMAT.get(fmt or "short", DEFAULT_BY_FORMAT["short"])


def _as_style(style):
    return load_style(style) if isinstance(style, str) else style


# ------------------------------------------------------------------ derived views
def episode_stamp(style):
    """What goes into episode.style: the resolved style without prose."""
    s = _as_style(style)
    return {k: copy.deepcopy(v) for k, v in s.items() if k not in PROSE_KEYS}


def resolved_style(style):
    """The style plus what it resolves to in the consuming code (snapshotted by the tests)."""
    s = _as_style(style)
    L = lighting_module()
    out = episode_stamp(s)
    res = {}
    for tod, entry in s["lighting"]["time_of_day"].items():
        cfg = dict(L.BASE)
        cfg.update(L.PRESETS[entry["preset"]])
        cfg.update({k: v for k, v in entry.items() if k in L.BASE})
        res[tod] = {"preset": entry["preset"], "family": cfg["family"], "key_energy": cfg["key_energy"],
                    "fill_ratio": cfg["fill_ratio"], "rim_energy": cfg["rim_energy"], "exposure_ev": cfg["exposure_ev"],
                    "hdri": cfg["hdri"], "haze_density": cfg["haze_density"]}
    out["resolved"] = {
        "lighting": res,
        "finish": finish_props(s),
        "music": music_palette(s),
        "handheld_scale": round(s["camera"]["handheld"]["default"] / HOUSE_HANDHELD, 4),
    }
    return json.loads(json.dumps(out))  # tuples -> lists, as in a json file


def finish_props(style):
    """Props for the Remotion Finish composition (studio/src/finish/types.ts FinishProps)."""
    s = _as_style(style)
    c = s["captions"]
    cap = {"mode": c["mode"], "font": c["font"]["family"], "weight": c["font"]["weight"], "italic": bool(c["font"].get("italic")),
           "capHeight": c.get("cap_height_px", [72, 92]), "fill": c["fill"], "stroke": c["stroke"], "strokeEm": c["stroke_em"],
           "shadow": c["shadow"], "pop": c["pop"], "plate": c["plate"], "tones": c["tones"], "safe": c["safe"], "band": c["band"]}
    return {"grade": dict(s["grade"]), "captionStyle": cap, "transitions": list(s["transitions"]["vocabulary"])}


def music_palette(style):
    """What factory/sound/designer.py takes from the style."""
    s = _as_style(style)
    m = s["music"]
    return {"engine": m["engine"], "bpm": m["bpm"], "bpm_range": list(m["bpm_range"]), "key": m["key"],
            "moods": list(m.get("moods", [])), "instrumentation": list(m.get("instrumentation", [])),
            "energy_max": m["energy_max"], "sfx_density": dict(m["sfx_density"])}


def style_prompt_text(style):
    """The STYLE section injected into the director's system prompt (factory/director/prompts.py)."""
    s = _as_style(style)
    lt, cam, cap, mus, nar = s["lighting"], s["camera"], s["captions"], s["music"], s["narration"]
    acts = "\n".join(f"  - {a['act']}: {a['dominant']['name']} {a['dominant']['hex']}, accent {a['accent']['name']} {a['accent']['hex']}, "
                     f"saturation {a['sat'][0]}-{a['sat'][1]}, value key {a['value_key']}" for a in s["palette"]["acts"])
    res = "; ".join(f"{r['name']} {r['hex']} withheld until {r['until']}" for r in s["palette"].get("reserved", []))
    tod = "; ".join(f"{k}: {v['preset']} (key:fill {v.get('fill_ratio', '-')}:1)" for k, v in lt["time_of_day"].items())
    kf = "; ".join(f"{k} {a}-{b}:1" for k, (a, b) in lt["key_fill"].items())
    lens = ", ".join(f"{k} {v}" for k, v in s["lens"]["by_emotion"].items())
    hh = ", ".join(f"{k} {v}" for k, v in cam["handheld"].items())
    return "\n".join([
        f"STYLE `{s['id']}` v{s['version']}: {s['title']}. {s.get('description', '')}",
        f"FRAME: {s['frame']['fps']} fps. LOOK: {s['look']['view_transform']} '{s['look']['look']}', exposure {s['look']['exposure']}.",
        "COLOUR SCRIPT (one key per act):\n" + acts + (f"\n  reserved: {res}" if res else ""),
        f"LIGHTING presets by time of day: {tod}. Key:fill by mood: {kf}. Shadow floor {lt.get('shadow_floor', 0.03)} linear.",
        f"LENSES (35 mm FF equivalent) by emotion: {lens}; default {s['lens']['default_mm']} mm.",
        f"CAMERA moves to use: {', '.join(cam['vocabulary'])}" + (f"; avoid: {', '.join(cam['avoid'])}" if cam.get("avoid") else "")
        + f". Handheld amounts: {hh}. Default ease {cam['default_ease']}."
        + (f" Typical shot length {cam['shot_seconds'][0]}-{cam['shot_seconds'][1]} s." if cam.get("shot_seconds") else ""),
        f"TRANSITIONS: {', '.join(s['transitions']['vocabulary'])} (default {s['transitions']['default']}). {s['transitions'].get('notes', '')}".rstrip(),
        f"CAPTIONS: {cap['mode']} in {cap['font']['family']} {cap['font']['weight']}, up to {cap['paging']['max_words']} words per page.",
        f"MUSIC: {mus['engine']} {mus['key']} at {mus['bpm']} bpm (range {mus['bpm_range'][0]}-{mus['bpm_range'][1]}), moods {', '.join(mus.get('moods', []))}; "
        f"at most {mus['sfx_density']['max_transients']} SFX transients per {mus['sfx_density']['window_s']} s.",
        f"NARRATION: {nar['voice']['register']}, {nar['wps'][0]}-{nar['wps'][1]} words/s.",
        f"MATERIALS: outline {s['materials']['outline']}; skin subsurface {s['materials'].get('skin_subsurface', 0)}; {s['materials'].get('notes', '')}".rstrip(),
    ])


# ------------------------------------------------------------------ apply to an episode
def style_world_lighting(ep, style):
    """world.lighting derived from the style for this episode's sequences (lighting.style_lighting per sequence)."""
    s = _as_style(style)
    L = lighting_module()
    probe = {**ep, "style": {"lighting": s["lighting"]}}
    seqs = {}
    for shot in ep.get("shots") or []:
        seq = L.sequence_of(shot)
        if seq not in seqs:
            seqs[seq] = L.style_lighting(probe, shot)
    return {"preset": s["lighting"]["time_of_day"]["night"]["preset"] if "night" in s["lighting"]["time_of_day"] else s["lighting"]["default_preset"],
            "sequences": {k: v for k, v in seqs.items() if v}}


def _merge_lighting(style_wl, existing):
    out = copy.deepcopy(style_wl)
    ex = copy.deepcopy(existing or {})
    seq_ex = ex.pop("sequences", {}) or {}
    out.update(ex)
    for k, v in seq_ex.items():
        out["sequences"][k] = v
    return out


def _scale_keys_or_scalar(v, k):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(v * k, 4)
    if isinstance(v, list):
        return [[f, round(x * k, 4)] for f, x in v]
    return v


def apply_style_to_episode(episode, style, *, retime=True, override_lighting=False, scale_handheld=True):
    """New episode dict with `style` applied (the input is not modified). See the module docstring."""
    s = _as_style(style)
    ep = copy.deepcopy(episode)
    fps = s["frame"]["fps"]
    if int(ep.get("fps", 30)) != fps:
        if not retime:
            raise StyleError(f"episode is {ep.get('fps')} fps, style {s['id']} is {fps} fps (pass retime=True)")
        ep = retime_episode(ep, fps)
    applied = {"fps": fps}
    world = ep.setdefault("world", {})
    swl = style_world_lighting(ep, s)
    world["lighting"] = swl if override_lighting else _merge_lighting(swl, world.get("lighting"))
    applied["lighting_sequences"] = {k: v["preset"] for k, v in world["lighting"].get("sequences", {}).items()}
    target = s["camera"]["handheld"]["default"] / HOUSE_HANDHELD
    prev = float(((episode.get("style") or {}).get("applied") or {}).get("handheld_scale", 1.0))
    k = target / prev  # relative to a previous stamp, so re-applying a style is idempotent
    applied["handheld_scale"] = round(prev, 4)
    if scale_handheld and abs(k - 1.0) > 1e-9:
        for shot in ep.get("shots") or []:
            cam = shot.get("camera") or {}
            for name in ("handheld", "drift"):
                if name in cam:
                    cam[name] = _scale_keys_or_scalar(cam[name], k)
            d = shot.get("direction")
            if isinstance(d, dict) and "handheld" in d:
                d["handheld"] = _scale_keys_or_scalar(d["handheld"], k)
        applied["handheld_scale"] = round(target, 4)
    ep["style"] = {**episode_stamp(s), "applied": applied}
    src = ep.setdefault("source", {})
    if isinstance(src, dict):
        src["style"] = f"factory/styles/{s['id']}.json@v{s['version']}"
    return ep


# ------------------------------------------------------------------ episode checks (python port of cloud/spec/validate.mjs)
def check_episode(ep):
    """Semantic validity of an episode (the checks of cloud/spec/validate.mjs that the schema cannot express, plus the
    style stamp). Returns (errors, warnings)."""
    E, W = [], []
    for k in ("id", "title", "fps", "width", "height", "durationFrames", "audio", "world", "assets", "shots", "captions"):
        if k not in ep:
            E.append(f"missing top-level '{k}'")
    if E:
        return E, W
    D = ep["durationFrames"]
    prev = 0
    for s in ep["shots"]:
        tag = f"shot {s['id']}"
        if s["from"] >= s["to"]:
            E.append(f"{tag}: from {s['from']} >= to {s['to']}")
        if s["from"] < 0 or s["to"] > D:
            E.append(f"{tag}: [{s['from']},{s['to']}) outside 0..{D}")
        if s["from"] != prev:
            (E if s["from"] < prev else W).append(f"{tag}: starts at {s['from']}, previous ended at {prev}")
        prev = s["to"]
        if "keyFrame" in s and not s["from"] <= s["keyFrame"] < s["to"]:
            W.append(f"{tag}: keyFrame outside the shot")
        kf = [k["f"] for k in s["camera"]["keys"]]
        if kf != sorted(kf):
            E.append(f"{tag}: camera keys not sorted")
        for name, v in {"handheld": s["camera"].get("handheld"), **(s.get("yacht") or {})}.items():
            if isinstance(v, list) and [k[0] for k in v] != sorted(k[0] for k in v):
                E.append(f"{tag}: {name} keys not sorted")
        if s.get("fires") and [k[0] for k in s["fires"]] != sorted(k[0] for k in s["fires"]):
            E.append(f"{tag}: fires keys not sorted")
        for a in s.get("actors") or []:
            if a["asset"] not in ep["assets"]["characters"]:
                E.append(f"{tag}: actor asset '{a['asset']}' not in assets.characters")
            for t in a.get("tracks") or []:
                if t["clip"] != "none" and t["clip"] not in ep["assets"]["motions"]:
                    E.append(f"{tag}: clip '{t['clip']}' not in assets.motions")
    if prev != D:
        W.append(f"shots end at {prev}, film is {D} frames")
    for i, c in enumerate(ep["captions"]):
        if c["from"] >= c["to"]:
            E.append(f"caption {i}: from >= to")
        if c["to"] > D:
            E.append(f"caption {i}: ends after the film")
    st = ep.get("style")
    if st is not None:
        if st.get("frame", {}).get("fps") != ep["fps"]:
            E.append(f"style fps {st.get('frame', {}).get('fps')} != episode fps {ep['fps']}")
        L = lighting_module()
        wl = (ep.get("world") or {}).get("lighting") or {}
        for seq, entry in (wl.get("sequences") or {}).items():
            if entry.get("preset") not in L.PRESETS:
                E.append(f"world.lighting.sequences.{seq}: unknown preset {entry.get('preset')}")
        for shot in ep["shots"]:
            cfg = L.resolve(ep, shot)
            if cfg is None:
                continue
            if cfg["fill_ratio"] < 1:
                E.append(f"shot {shot['id']}: key:fill {cfg['fill_ratio']} < 1")
        _rows, problems = L.check_sequences(ep)
        E.extend(f"lighting: {p}" for p in problems)
    return E, W


__all__ = ["load_style", "list_styles", "validate_style", "apply_style_to_episode", "retime_episode", "episode_stamp",
           "resolved_style", "finish_props", "music_palette", "style_prompt_text", "style_world_lighting",
           "default_style_for_format", "check_episode", "StyleError", "DEFAULT_BY_FORMAT"]
