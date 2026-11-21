"""Pull the relevant rules and checklists out of factory/recipes/*.md for each stage's system prompt.

The recipes are the single source of taste: we embed their text verbatim (no paraphrase), so a recipe edit
changes the prompts on the next run. Sections are selected by heading prefix.
"""
import os
import re

from .paths import RECIPES


def _read(name):
    with open(os.path.join(RECIPES, name), encoding="utf-8") as fh:
        return fh.read()


def section(md, heading_prefix):
    """Text of the markdown section whose heading starts with `heading_prefix` (e.g. '## 1.'),
    up to the next heading of the same or higher level."""
    lines = md.splitlines()
    level = len(heading_prefix) - len(heading_prefix.lstrip("#"))
    out, on = [], False
    for ln in lines:
        m = re.match(r"^(#+)\s", ln)
        if on and m and len(m.group(1)) <= level:
            break
        if not on and ln.startswith(heading_prefix):
            on = True
        if on:
            out.append(ln)
    if not out:
        raise KeyError(f"recipe section {heading_prefix!r} not found")
    return "\n".join(out).strip()


def checklists(md):
    """Every '**Checklist ...**' / '**CHECKLIST ...**' block (heading line + its '- [ ]' items)."""
    out, cur = [], None
    for ln in md.splitlines():
        if re.match(r"^\*\*(Checklist|CHECKLIST)", ln):
            cur = [ln]
            out.append(cur)
            continue
        if cur is not None:
            if ln.startswith("- [ ]") or (ln.startswith("  ") and cur):
                cur.append(ln)
            elif ln.strip() == "" and len(cur) == 1:
                continue
            else:
                cur = None
    return "\n\n".join("\n".join(b) for b in out)


ENG = "ENGAGEMENT_RECIPE.md"
PIX = "PIXAR_RECIPE.md"

# stage -> list of (file, heading prefix) sections embedded verbatim
STAGE_SECTIONS = {
    "develop": [(ENG, "## 1. HOOK"), (ENG, "## 2. RETENTION"), (ENG, "## 3. NARRATION"), (ENG, "## 7. THUMBNAIL"),
                (ENG, "## Appendix A"), (ENG, "## Appendix B"), (PIX, "## 2. Story Structure")],
    "breakdown": [(PIX, "### 2.3 Stakes"), (PIX, "### 3.3 Establishing")],
    "direct": [(ENG, "## 4. PACING"), (PIX, "## 3. Shot Design"), (PIX, "### 5.2 Acting beats"), (PIX, "### 5.4 Holds"),
               (PIX, "### 4.3 Consistency")],
}


def stage_recipe_text(stage):
    parts = []
    for fname, head in STAGE_SECTIONS.get(stage, []):
        parts.append(f"<recipe file=\"factory/recipes/{fname}\" section=\"{head.lstrip('# ')}\">\n{section(_read(fname), head)}\n</recipe>")
    return "\n\n".join(parts)


def all_checklists():
    return checklists(_read(ENG)) + "\n\n" + checklists(_read(PIX))
