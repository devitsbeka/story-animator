"""Lesson regression cases: every lesson owns stress scenarios that reproduce its defect class in EVERY world kit.

A case is a selector over the stress axes ({"stance", "hands", "size", "emotion"}: a value, a glob like "sit*", or a
list of alternatives). factory/goldens/stress/generator.py expands it to one scenario per kit (reusing a matching base
scenario where one exists, generating one otherwise). `python -m factory.lessons add` derives a selector from the
symptom/rule text when --case is not given, writes it to factory/goldens/stress/cases.json, regenerates the stress
episode and records the scenario ids in the lesson's `regression_cases` field.
"""
from __future__ import annotations

import json
import re

from factory.goldens.stress import generator as SG

# keyword -> (tag, selector)
KEYWORDS = [
    (r"\b(sit|sitting|seat|seated|lean)", ("sit", {"stance": "sit*"})),
    (r"\b(finger|hand|hands|grip|palm|wrist|holding)", ("hands", {"hands": ["radio*", "phone", "beacon"]})),
    (r"\b(kneel|crouch|walk|rope|vocabulary)", ("vocab", {"stance": ["kneel", "crouch", "walk", "sit_log", "sit_rock", "sit_bench"]})),
    (r"\b(face|expression|eye|eyes|emotion|stare|uncanny)", ("face", {"size": "close"})),
    (r"\b(crop|close-up|close-ups|framing|camera|geometry|brown|black)", ("frame", {"size": "close"})),
    (r"\b(light|lighting|exposure)", ("light", {"size": "wide"})),
]


def derive(text):
    t = text.lower()
    for pat, (tag, sel) in KEYWORDS:
        if re.search(pat, t):
            return tag, dict(sel)
    return "generic", {"size": "medium"}


def parse_case(s):
    """'stance=sit*,hands=radio|phone,size=close' -> selector dict"""
    out = {}
    for part in filter(None, (p.strip() for p in s.split(","))):
        k, v = part.split("=", 1)
        if k not in ("stance", "hands", "size", "emotion", "tag"):
            raise ValueError(f"unknown case key {k!r}")
        out[k] = v.split("|") if "|" in v else v
    return out


def attach(lesson_id, selector=None, text="", path=None, cases_path=None):
    """Add a case for the lesson, regenerate the stress episode, write regression_cases into the ledger. -> ids"""
    import os
    from . import LEDGER, ledger_path, set_field
    if cases_path is None:
        # a scratch ledger (tests, dry runs) keeps its cases next to it; the real ledger writes the stress suite
        lp = os.path.abspath(ledger_path(path))
        cases_path = SG.CASES_PATH if lp == os.path.abspath(LEDGER) else os.path.join(os.path.dirname(lp), "stress_cases.json")
    tag, auto = derive(text)
    sel = dict(selector or auto)
    sel.setdefault("tag", tag)
    doc = SG.load_cases(cases_path)
    doc["cases"] = [c for c in doc["cases"] if not (c["lesson"] == lesson_id and c.get("tag") == sel["tag"])]
    doc["cases"].append({"lesson": lesson_id, **sel})
    with open(cases_path, "w") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")
    ids = sorted({e["id"] for c in doc["cases"] if c["lesson"] == lesson_id for e in SG.expand_case(c)})
    if cases_path == SG.CASES_PATH:
        SG.write()
    set_field(lesson_id, "regression_cases", ids, path)
    return ids
