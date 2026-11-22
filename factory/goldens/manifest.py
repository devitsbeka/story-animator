"""Golden manifest (recipes), the reference store and the git-tracked baseline.

  manifest.json   recipes: kind (hero | synthetic | episode), spec/frames/mode, inputs (file globs, @groups), thresholds
  baseline.json   per golden: sha256 + metrics of the approved reference, inputs hash at approval, commit, note
  store           <library_store>/goldens (gitignored): refs/<id>.png, candidates/<stamp>/<id>.png, results/<id>.json
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def manifest_path(root=ROOT):
    return os.path.join(root, "factory", "goldens", "manifest.json")


def baseline_path(root=ROOT):
    return os.path.join(root, "factory", "goldens", "baseline.json")


def load(root=ROOT):
    with open(manifest_path(root)) as fh:
        m = json.load(fh)
    for gid, g in m["goldens"].items():
        g["id"] = gid
        for k, v in m["defaults"].items():
            g.setdefault(k, v)
        globs = []
        for pat in g.get("inputs", []):
            globs += m["input_groups"][pat[1:]] if pat.startswith("@") else [pat]
        if g.get("spec"):
            globs.append(g["spec"])
        g["globs"] = sorted(set(globs))
    return m


def load_baseline(root=ROOT):
    p = baseline_path(root)
    if not os.path.exists(p):
        return {"schema": "factory.goldens.baseline/1", "goldens": {}}
    with open(p) as fh:
        return json.load(fh)


def save_baseline(doc, root=ROOT):
    with open(baseline_path(root), "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
        fh.write("\n")


def find_library_store(root=ROOT):
    """$LIBRARY_STORE, else <root>/library_store, else the nearest parent checkout's library_store (agent worktrees
    live under <main>/.claude/worktrees/<name>)."""
    env = os.environ.get("LIBRARY_STORE")
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    d = os.path.abspath(root)
    while True:
        cand = os.path.join(d, "library_store")
        if os.path.isdir(cand) and os.path.isdir(os.path.join(cand, "characters")):
            return cand
        up = os.path.dirname(d)
        if up == d:
            return os.path.join(os.path.abspath(root), "library_store")
        d = up


def store_dir(root=ROOT):
    return os.environ.get("FACTORY_GOLDENS_STORE") or os.path.join(find_library_store(root), "goldens")


def ref_path(gid, root=ROOT, sha=None):
    """refs/<gid>/<sha256>.png - the approved reference named by baseline.json (or by `sha`)."""
    if sha is None:
        b = load_baseline(root)["goldens"].get(gid)
        sha = b["sha256"] if b else "none"
    return os.path.join(store_dir(root), "refs", gid, f"{sha}.png")


def result_path(gid, root=ROOT):
    return os.path.join(store_dir(root), "results", f"{gid}.json")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def tracked_files(root=ROOT):
    """Files under version control + untracked-but-not-ignored (what a branch would merge)."""
    try:
        p = subprocess.run(["git", "-C", root, "ls-files", "-co", "--exclude-standard"], capture_output=True, text=True, timeout=60)
        if p.returncode == 0:
            return sorted(set(p.stdout.split()))
    except (OSError, subprocess.SubprocessError):
        pass
    out = []
    for d, _, fs in os.walk(root):
        if "/.git" in d or "node_modules" in d:
            continue
        out += [os.path.relpath(os.path.join(d, f), root) for f in fs]
    return sorted(out)


def match(path, globs):
    return any(fnmatch.fnmatch(path, g) for g in globs)


def inputs_hash(g, root=ROOT, files=None):
    """sha256 over (path, content sha) of every file matching the golden's input globs + the recipe itself."""
    files = files if files is not None else tracked_files(root)
    h = hashlib.sha256()
    recipe = dict(g)   # the recipe (incl. its expanded globs): editing a golden's recipe changes only that golden
    h.update(json.dumps(recipe, sort_keys=True).encode())
    for f in files:
        if match(f, g["globs"]):
            p = os.path.join(root, f)
            if os.path.isfile(p):
                h.update(f.encode() + b"\0" + sha256(p).encode())
    return h.hexdigest()


def affected(changed_files, root=ROOT, manifest=None):
    """Goldens whose input globs match any changed file (a manifest change affects the goldens whose recipe changed:
    every golden, conservatively, since @golden_tooling covers manifest.json)."""
    m = manifest or load(root)
    return sorted(gid for gid, g in m["goldens"].items() if any(match(f, g["globs"]) for f in changed_files))
