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
        "prop": {"type": "string"}, "attach": {"enum": ["yacht", "handR", "handL"]}, "actor": {"type": "string"},
        "local": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
        "rotY": {"type": "number"}, "rot": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
        "scale": {"type": "number"}, "light": _KEYS, "show": _KEYS, "strobe": {"type": "integer"},
    },
}


@functools.lru_cache(maxsize=1)
def render_contract():
    with open(EPISODE_SCHEMA) as fh:
        s = copy.deepcopy(json.load(fh))
    s["$defs"]["actor"]["properties"]["perf"] = PERF
    s["$defs"]["shot"]["properties"]["props"] = {"type": "array", "items": PROP}
    Draft202012Validator.check_schema(s)
    return s


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
