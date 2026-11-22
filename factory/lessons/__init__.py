"""The lessons ledger (factory/lessons/lessons.yaml): every defect found becomes a rule with an automated check.

    from factory.lessons import load_lessons, rules_for_gate, lessons_block
    rules_for_gate("direct")          # open + closed lessons whose gate list contains "direct"
    lessons_block(["direct", "asset"]) # the LESSONS text injected into director prompts / agent briefs

CLI: python -m factory.lessons add|list|status|check|close|inject-briefs (see __main__.py and README.md).
"""
from __future__ import annotations

import os
import re

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LEDGER = os.path.join(HERE, "lessons.yaml")

STATUSES = ("open", "partially-closed", "closed")
GATES = ("develop", "library", "asset", "direct", "render", "qc", "deliver", "merge", "run")
FIELDS = ("id", "found", "symptom", "root_cause", "rule", "check", "gate", "status")
# director stage -> the gates whose rules its prompt carries
STAGE_GATES = {"develop": ["develop"], "breakdown": ["develop", "library"], "direct": ["direct", "library", "asset"]}


def ledger_path(path=None):
    return path or os.environ.get("FACTORY_LESSONS") or LEDGER


def load_lessons(path=None):
    """-> list of lesson dicts (gate always a list, status lower-case)."""
    with open(ledger_path(path), encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or []
    if not isinstance(doc, list):
        raise ValueError(f"{ledger_path(path)}: expected a YAML list of lessons")
    out = []
    for i, d in enumerate(doc):
        if not isinstance(d, dict) or not d.get("id"):
            raise ValueError(f"lesson #{i + 1} has no id")
        d = dict(d)
        g = d.get("gate") or []
        d["gate"] = [g] if isinstance(g, str) else list(g)
        d["status"] = str(d.get("status", "open")).lower()
        out.append(d)
    return out


def get(lesson_id, path=None):
    for d in load_lessons(path):
        if d["id"] == lesson_id:
            return d
    raise KeyError(lesson_id)


def is_open(d):
    return d["status"] != "closed"


def rules_for_gate(gate, path=None, statuses=STATUSES):
    """Lessons (open, partially-closed and closed) whose gate list contains `gate` (or any of a list of gates)."""
    gates = {gate} if isinstance(gate, str) else set(gate)
    return [d for d in load_lessons(path) if d["status"] in statuses and gates & set(d["gate"])]


def lessons_block(gates=None, path=None, title="LESSONS"):
    """Prompt/brief text: one line per rule, grouped by gate (every gate when gates is None)."""
    ls = load_lessons(path)
    gates = list(GATES) if gates is None else ([gates] if isinstance(gates, str) else list(gates))
    lines = [f"{title} (factory/lessons/lessons.yaml: defects already found once; each rule is enforced by a check - "
             "never repeat one. OPEN = check not automated yet: self-enforce.)"]
    seen = set()
    for g in gates:
        rows = [d for d in ls if g in d["gate"] and d["id"] not in seen]
        if not rows:
            continue
        lines.append(f"[gate {g}]")
        for d in rows:
            seen.add(d["id"])
            tag = "closed" if d["status"] == "closed" else d["status"].upper()
            lines.append(f"- {d['id']} ({tag}): {' '.join(str(d.get('rule', '')).split())}")
    return "\n".join(lines) if seen else ""


def next_id(path=None):
    n = max((int(m.group(1)) for d in load_lessons(path) if (m := re.match(r"L(\d+)$", d["id"]))), default=0)
    return f"L{n + 1:03d}"


def _yaml_scalar(s):
    s = " ".join(str(s).split())
    return yaml.safe_dump(s, default_flow_style=True, width=10_000, allow_unicode=True).strip().removesuffix("\n...").strip()


def add_lesson(symptom, root_cause, rule, gate, check="TODO: automate", found=None, path=None):
    """Append a lesson (next id, status open) as text, so the ledger's comments and layout survive. -> the new id."""
    import datetime
    p = ledger_path(path)
    gates = [g.strip() for g in (gate.split(",") if isinstance(gate, str) else gate) if g.strip()]
    bad = [g for g in gates if g not in GATES]
    if not gates or bad:
        raise ValueError(f"gate must be one or more of {GATES} (got {gates})")
    for name, v in (("symptom", symptom), ("root_cause", root_cause), ("rule", rule)):
        if not str(v or "").strip():
            raise ValueError(f"{name} is required")
    lid = next_id(p)
    found = found or f"user, {datetime.date.today().isoformat()}"
    block = (f"\n- id: {lid}\n  found: {_yaml_scalar(found)}\n  symptom: {_yaml_scalar(symptom)}\n"
             f"  root_cause: {_yaml_scalar(root_cause)}\n  rule: {_yaml_scalar(rule)}\n  check: {_yaml_scalar(check)}\n"
             f"  gate: [{', '.join(gates)}]\n  status: open\n")
    with open(p, encoding="utf-8") as fh:
        text = fh.read()
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text.rstrip("\n") + "\n" + block)
    load_lessons(p)  # still parses
    return lid


def set_status(lesson_id, status, check=None, path=None):
    """Edit one lesson's status (and optionally its check text) in place."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    p = ledger_path(path)
    with open(p, encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(rf"^- id: {re.escape(lesson_id)}\s*$", text, re.M)
    if not m:
        raise KeyError(lesson_id)
    nxt = re.search(r"^- id: ", text[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(text)
    block = text[m.start():end]
    block = re.sub(r"^  status: .*$", f"  status: {status}", block, count=1, flags=re.M)
    if check:
        block = re.sub(r"^  check: .*$", f"  check: {_yaml_scalar(check)}", block, count=1, flags=re.M)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text[:m.start()] + block + text[end:])
    load_lessons(p)


# ------------------------------------------------------------------ agent briefs
BRIEF_BEGIN, BRIEF_END = "<!-- LESSONS:BEGIN (generated by `python -m factory.lessons inject-briefs`; do not edit) -->", "<!-- LESSONS:END -->"
BRIEF_TEMPLATES = ("_common_v2.md", "_common_hero.md", "_common_polish.md")


def brief_text(path=None):
    return f"{BRIEF_BEGIN}\n{lessons_block(None, path)}\n{BRIEF_END}"


def inject_briefs(briefs_dir=None, check_only=False, path=None):
    """Write the LESSONS block into every common brief template. -> list of (file, changed)."""
    briefs_dir = briefs_dir or os.path.join(ROOT, "factory", "briefs")
    block = brief_text(path)
    out = []
    for name in BRIEF_TEMPLATES:
        f = os.path.join(briefs_dir, name)
        if not os.path.isfile(f):
            continue
        with open(f, encoding="utf-8") as fh:
            text = fh.read()
        if BRIEF_BEGIN in text and BRIEF_END in text:
            new = text[:text.index(BRIEF_BEGIN)] + block + text[text.index(BRIEF_END) + len(BRIEF_END):]
        else:
            new = text.rstrip("\n") + "\n" + block + "\n"
        changed = new != text
        if changed and not check_only:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(new)
        out.append((f, changed))
    return out
