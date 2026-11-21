"""Librarian side of world kits: map a breakdown location to an existing kit (REUSE) or propose a new kit (BUILD)
assembled from what the library already holds.

match(element, scenes)       -> (kit_id, score, reason) | None
propose(element, scenes)     -> a kit draft (valid against kit.schema.json when the library covers it) + notes
"""
import re

from . import kits as K

STOP = {"the", "a", "an", "of", "in", "on", "at", "and", "with", "to", "by", "set", "location", "scene", "place", "area", "exterior",
        "interior", "ext", "int", "wide", "big", "small", "old", "new"}
# loose synonyms -> the vocabulary kits are tagged with
SYN = {"rainforest": "jungle", "rain forest": "jungle", "woods": "forest", "woodland": "forest", "gorge": "canyon", "ravine": "canyon",
       "mesa": "canyon", "dunes": "desert", "sahara": "desert", "glacier": "snow", "alps": "alpine", "summit": "peak",
       "downtown": "city", "metropolis": "city", "boulevard": "street", "alleyway": "alley", "ocean": "sea"}
TERRAIN_HINTS = [("canyon", {"canyon", "gorge", "ravine", "cliff", "cliffs", "wadi", "mesa"}),
                 ("ridge", {"ridge", "mountain", "summit", "peak", "alpine", "snow", "glacier", "pass"}),
                 ("street", {"street", "city", "road", "alley", "avenue", "town", "urban", "downtown"}),
                 ("noise", set())]
LIGHT_BY_TIME = {"night": "moonlight_practical_mix", "dawn": "dawn", "day": "midday", "dusk": "golden_hour"}
KEY_BY_TIME = {"night": [0.4, 0.6, -0.5], "dawn": [0.8, 0.12, 0.4], "day": [0.4, 0.85, 0.35], "dusk": [-0.7, 0.25, 0.6]}


def tokens(*parts):
    out = set()
    for p in parts:
        for t in (p if isinstance(p, (list, tuple, set)) else [p]):
            t = (t or "").lower()
            for k, v in SYN.items():
                if k in t:
                    out.add(v)
            for w in re.split(r"[^a-z0-9]+", t):
                if w and w not in STOP:
                    out.add(w)
                    out.add(SYN.get(w, w))
                    if w.endswith("s") and len(w) > 3:
                        out.add(w[:-1])
    return out


def kit_tokens(kit):
    return tokens(kit["tags"], kit["id"], kit["name"])


def scenes_for(element, scenes):
    return [s for s in scenes or [] if s.get("location") == element["id"]]


def match(element, scenes=None, kits=None):
    kits = kits if kits is not None else K.all_kits()
    prim = tokens(element["search_terms"][0])
    allt = tokens(element["search_terms"], element["name"])
    best = None
    for kid, kit in kits.items():
        kt = kit_tokens(kit)
        prim_hit = bool(prim) and prim <= kt
        overlap = len(allt & kt)
        if not (prim_hit or overlap >= 3):
            continue
        tod = {s.get("time_of_day") for s in scenes_for(element, scenes)}
        score = (int(prim_hit), overlap, int(kit["sky"]["time_of_day"] in tod), kid)
        if best is None or score > best[1]:
            best = (kid, score)
    if best is None:
        return None
    kid, (ph, ov, tod_ok, _) = best
    why = f"world kit '{kid}' ({'primary term' if ph else 'tags'} match, {ov} shared terms"
    why += ", same time of day)" if tod_ok else "; time of day differs: override the kit sky per shot via env)"
    return kid, ov + 10 * ph, why


def _slug(s):
    return re.sub(r"[^a-z0-9_]+", "_", s.lower()).strip("_")[:40] or "new_set"


def propose(element, scenes=None, catalog=None):
    """A draft kit for a location the library has no kit for: terrain shape from the location nouns, sky + lighting from
    the scenes' time of day / weather, scatter layers and ground from catalog assets whose tags share the location's
    terms. Returns {"kit": draft, "errors": [...], "notes": [...]}; errors list what the library is still missing."""
    cat = catalog if catalog is not None else K._catalog()
    allt = tokens(element["search_terms"], element["name"], element.get("must_do", []))
    sc = scenes_for(element, scenes)
    tod = sc[0]["time_of_day"] if sc else "day"
    weather = sc[0].get("weather", "clear") if sc else "clear"
    ttype = next(t for t, words in TERRAIN_HINTS if not words or words & allt)
    notes = []

    def hits(kind):
        out = []
        for cid, a in sorted(cat.items()):
            if a.get("kind") != kind or not a.get("files"):
                continue
            at = tokens(a.get("tags", []), a.get("name", ""), cid.split(":")[-1])
            n = len(at & allt)
            if n:
                out.append((n, cid, a))
        return [c for _, c, _ in sorted(out, key=lambda x: (-x[0], x[1]))]

    models = hits("model")
    textures = hits("texture")
    big = [c for c in models if any(w in c for w in ("tree", "cliff", "boulder", "lamp"))][:3]
    small = [c for c in models if c not in big][:3]
    scatter = []
    if big:
        scatter.append({"id": "large", "assets": big, "density": 0.4, "region": {"shape": "ring", "center": [0, 0], "r": [12, 55]}, "height": [4, 14]})
    if small:
        scatter.append({"id": "small", "assets": small, "density": 2.0, "region": {"shape": "ring", "center": [0, 0], "r": [6, 45]}, "height": [0.4, 1.6]})
    if not scatter:
        notes.append(f"no library models share terms with {sorted(allt)}: source some (factory/library/sources/polyhaven.py search ...)")
    mat = {"color": [0.35, 0.33, 0.3], "tile_m": 4.0}
    if textures:
        mat["texture"] = textures[0]
    else:
        notes.append("no library ground texture matches: flat colour until one is sourced")
    params = {"canyon": {"floor_half": 9, "wall_w": 15, "wall_h": 35, "meander_amp": 6, "meander_len": 150},
              "ridge": {"slope": 0.7, "crest_w": 3, "rise": 0.05}, "street": {"road_half": 5, "walk_w": 3, "curb_h": 0.15}}.get(ttype, {})
    sounds = [cid for cid, a in sorted(cat.items()) if a.get("kind") == "sfx" and tokens(a.get("name", ""), a.get("tags", [])) & allt]
    amb = [{"id": s, "gain_db": -18} for s in sounds[:2]] or [{"id": f"sfx_{_slug(element['id'])}", "status": "to_generate",
                                                               "prompt": f"ambience bed: {element['name']}, {tod}, {weather}, no music"}]
    kit = {
        "id": _slug(element["id"]), "name": element["name"], "version": 1,
        "description": f"Proposed by the librarian for breakdown element '{element['id']}': {element['name']}.",
        "tags": sorted(allt)[:16] or [element["id"]], "seed": 1,
        "extent": {"half": [60, 60]},
        "terrain": {"type": ttype, "res": 96, "amp": 1.0 if ttype != "street" else 0.3, "freq": 0.03, "octaves": 4, "params": params,
                    "clearings": [{"at": [0, 0], "r": 6, "blend": 6}], "material": mat},
        "sky": {"type": "night_procedural" if tod == "night" else ("overcast" if weather in ("overcast", "rain", "fog", "storm") else "day_physical"),
                "time_of_day": tod, "key_dir": KEY_BY_TIME[tod], "weather": weather if weather != "storm" else "rain"},
        "lighting": {"preset": "soft_overcast" if weather in ("overcast", "fog") and tod == "day" else LIGHT_BY_TIME[tod]},
        "scatter": scatter, "pieces": [],
        "marks": {"CENTER": {"at": [0, 0], "rotY": 0.0, "kind": "stand", "desc": "set centre, facing +z"}},
        "camera_zones": [{"id": "centre", "region": {"shape": "disc", "center": [0, 0], "r": 10}, "y": [0.3, 10]},
                         {"id": "aerial", "region": {"shape": "all"}, "y": [25, 200]}],
        "lights": [], "ambience": amb,
        "provenance": {"author": "factory/director librarian (proposal)", "element": element["id"], "must_do": element.get("must_do", [])},
    }
    return {"kit": kit, "errors": K.validate(kit, cat), "notes": notes}
