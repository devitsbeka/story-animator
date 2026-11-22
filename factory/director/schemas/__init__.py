"""JSON Schemas for the director's artifacts, plus the episode.json render contract.

The render contract is cloud/spec/episode.schema.json extended with the fields the current Blender
renderer reads but the spec has not caught up with (actors[].perf, shots[].props) - episode_v2.json
uses both. Extending here keeps cloud/spec untouched.
"""
import copy
import functools
import json
import os

from jsonschema import Draft202012Validator

from ..paths import EPISODE_SCHEMA, SCHEMAS

NAMES = ("story", "breakdown", "manifest", "shotplan")


@functools.lru_cache(maxsize=None)
def load(name):
    with open(os.path.join(SCHEMAS, f"{name}.schema.json")) as fh:
        s = json.load(fh)
    Draft202012Validator.check_schema(s)
    return s


_KEYS = {"type": "array", "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}}
PERF = {
    "type": "object", "additionalProperties": False, "required": ["stance", "poses", "verbs"],
    "description": "cloud/blender/acting.py performance: base stance keys + timed poses + procedural verbs.",
    "properties": {
        "stance": {"type": "array", "items": {"type": "array", "minItems": 2, "maxItems": 2,
                                               "prefixItems": [{"type": "number"}, {"type": "string"}]}},
        "poses": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["pose", "from", "to"],
                                              "properties": {"pose": {"type": "string"}, "from": {"type": "number"}, "to": {"type": "number"},
                                                             "in": {"type": "number"}, "out": {"type": "number"}, "ease": {"type": "string"}}}},
        "verbs": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["verb", "at"],
                                              "properties": {"verb": {"type": "string"}, "at": {"type": "number"}, "dur": {"type": "number"},
                                                             "amount": {"type": "number"}}}},
        "breath": {"type": "number"}, "seed": {"type": "integer"}, "blend": {"type": "number"},
    },
}
PROP = {
    "type": "object", "additionalProperties": False, "required": ["prop", "attach"],
    "description": "cloud/blender/render_episode.py build_props(): a props.py BUILDERS key attached to the yacht or a hand.",
    "properties": {
        "prop": {"type": "string"}, "attach": {"enum": ["yacht", "handR", "handL", "set"]}, "actor": {"type": "string"},
        "local": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
        "rotY": {"type": "number"}, "rot": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
        "scale": {"type": "number"}, "light": _KEYS, "show": _KEYS, "strobe": {"type": "integer"},
    },
}


SET_REF = {
    "type": "object", "additionalProperties": False, "required": ["kit"],
    "description": "World kit set (factory/worlds/kits/<kit>.json) built by cloud/blender/set_assembly.py instead of the yacht/island world.",
    "properties": {"kit": {"type": "string", "pattern": "^[a-z0-9_]+$"}, "seed": {"type": "integer", "minimum": 0},
                   "ambience": {"type": "array", "items": {"type": "string"}, "description": "the kit's ambience bed ids (for stage 5)"}},
}
LIGHTING = {"type": "object", "description": "cloud/blender/lighting.py: {preset, ...preset parameters, cheat_reason, light_event}",
            "properties": {"preset": {"type": "string"}}}


@functools.lru_cache(maxsize=1)
def render_contract():
    with open(EPISODE_SCHEMA) as fh:
        s = copy.deepcopy(json.load(fh))
    s["$defs"]["actor"]["properties"]["perf"] = PERF
    s["$defs"]["shot"]["properties"]["props"] = {"type": "array", "items": PROP}
    _docuseries_contract(s)
    # >>> world_kits: shots on a world-kit set (cloud/blender/set_assembly.py) + per-shot lighting presets
    s["$defs"]["shot"]["properties"]["set"] = SET_REF
    s["$defs"]["shot"]["properties"]["lighting"] = LIGHTING
    s["properties"]["world"]["properties"]["set"] = SET_REF
    s["properties"]["world"]["properties"]["lighting"] = LIGHTING
    s["$defs"]["actor"]["properties"]["space"] = {"enum": ["yacht", "set"], "description": "yacht: yacht-local; set: world-kit set space (= world)"}
    # <<< world_kits
    # >>> canon: impact handheld window (CAN-H1, read by shot_validator) + scheduled face keys (CAN-P1)
    s["$defs"]["shot"]["properties"]["impact_handheld"] = {"type": "object", "description": "CAN-H1 window: impact_frame, escape/lag/recover frames"}
    s["$defs"]["actor"]["properties"]["perf"]["properties"]["face"] = {
        "type": "object", "description": "cloudrig_adapter face_spec: emotion [[f, name, amt?]], blinks [f], blend, seed (compile.schedule_face)"}
    # <<< canon
    # >>> series defaults (lesson L021, factory/series/default.json): compile binds hero_v4 as a .blend entry and the
    # procedural yacht as 'proc:yacht_v2'; the render contract has to accept what the compiler emits
    glb = {"$ref": "#/$defs/glbKey"}
    s["properties"]["assets"]["properties"]["characters"]["additionalProperties"] = {"oneOf": [
        glb, {"type": "object", "required": ["kind", "file"], "properties": {"kind": {"enum": ["blend", "glb"]}, "file": {"type": "string"}}}]}
    s["properties"]["assets"]["properties"]["props"]["additionalProperties"] = {"oneOf": [
        glb, {"type": "string", "pattern": "^proc:[a-z0-9_]+$"}]}
    # <<< series defaults
    Draft202012Validator.check_schema(s)
    return s


# >>> docuseries: 16:9 masters, dual-frame shots (cameras.main / cameras.vertical) and the shorts plan
def _docuseries_contract(s):
    s["properties"]["width"] = {"enum": [1080, 1920, 3840], "description": "1080 (9:16 short) or 1920/3840 (16:9 master)"}
    s["properties"]["height"] = {"enum": [1920, 1080, 2160]}
    s["properties"]["format"] = {"enum": ["short", "docuseries"]}
    s["properties"]["vertical"] = {"type": "object", "additionalProperties": False, "required": ["width", "height"],
                                   "description": "frame of cameras.vertical (render_episode.py --camera vertical)",
                                   "properties": {"width": {"const": 1080}, "height": {"const": 1920}}}
    s["properties"]["shorts"] = {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "chapter", "from", "to", "hook_line", "shots"],
        "description": "story short_candidate beats in film frames [from, to), with the dual-frame shots that cover them",
        "properties": {"id": {"type": "string"}, "chapter": {"type": "string"}, "from": {"type": "integer"}, "to": {"type": "integer"},
                       "hook_line": {"type": "string"}, "setup": {"type": "string"}, "turn": {"type": "string"},
                       "payoff": {"type": "string"}, "shots": {"type": "array", "items": {"type": "string"}}}}}
    sh = s["$defs"]["shot"]["properties"]
    sh["short_candidate"] = {"type": "string"}
    sh["cameras"] = {"type": "object", "additionalProperties": False, "required": ["main", "vertical"],
                     "properties": {"main": {"$ref": "#/$defs/camera"}, "vertical": {"$ref": "#/$defs/camera"}}}
    sh["vertical"] = {"type": "object", "description": "shotplan staging hints for the vertical camera (subject, tighten, aim)"}
# <<< docuseries


def _fmt(e):
    loc = "/".join(str(p) for p in e.absolute_path) or "<root>"
    return f"{loc}: {e.message[:300]}"


def validate(name, doc):
    """List of human-readable schema errors ([] when valid). name in NAMES or 'episode'."""
    schema = render_contract() if name == "episode" else load(name)
    v = Draft202012Validator(schema)
    return [_fmt(e) for e in sorted(v.iter_errors(doc), key=lambda e: list(e.absolute_path))]


# keywords the Messages API structured-output grammar does not need; local validation still enforces them
_STRIP = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength", "pattern", "minItems",
          "maxItems", "prefixItems", "$schema", "$id", "title", "format"}


def api_schema(name):
    """A copy of the schema reduced to the subset safe for output_config.format (constraints are re-checked
    locally after the response)."""
    def walk(n):
        if isinstance(n, dict):
            out = {}
            for k, v in n.items():
                if k in _STRIP:
                    continue
                if k == "properties":
                    out[k] = {pk: walk(pv) for pk, pv in v.items()}   # property names are never keywords
                else:
                    out[k] = walk(v)
            if out.get("type") == "array" and "items" not in out:
                out["items"] = {}
            return out
        if isinstance(n, list):
            return [walk(x) for x in n]
        return n
    return walk(load(name))
