"""Stage 3 Library: resolve every breakdown element to REUSE / SOURCE / BUILD (deterministic, no LLM).

Order (factory/ARCHITECTURE.md, sourcing priority):
  1. REUSE an internal catalog entry (int:*) or an uncatalogued internal render asset (render_assets.json)
  2. BUILD with an existing code builder that the catalog does not list yet (cloud/blender/props.py BUILDERS)
  3. REUSE an already-sourced catalog entry (ph:*, acg:*) - its files and sha256 are in the catalog
  4. SOURCE from Poly Haven search (CC0) - status to_fetch until polyhaven.py fetch registers hashes
  5. BUILD a new procedural recipe proc:<element> (or remotion:<element> for overlays) - status to_build

Matching is on search_terms[0] (the primary noun): every word of it must appear in the candidate's id,
name or tags. Poly Haven hits must also match on the asset id or name (tags alone are too loose: a search
for 'coral' returns a shell tagged 'coral').
"""
import ast
import json
import os
import re
import sys

from .paths import CATALOG, HERE, PROPS_PY, SOURCES

KIND_OK = {
    "location": {"set", "world"}, "set": {"set", "model"}, "world": {"world"}, "hdri": {"hdri"}, "texture": {"texture"},
    "vehicle": {"vehicle", "model"}, "character": {"character"}, "prop": {"prop", "model"}, "fx": {"set", "world", "fx"},
    "system": {"system"}, "overlay": set(),
}
PH_KIND = {"prop": "model", "vehicle": "model", "set": "model", "location": "model", "hdri": "hdri", "texture": "texture"}


def load_catalog():
    with open(CATALOG) as fh:
        return json.load(fh)


def load_render_assets():
    with open(os.path.join(HERE, "render_assets.json")) as fh:
        d = json.load(fh)
    d.pop("_doc", None)
    return d


def builders():
    """props.py BUILDERS as {key: function name} (AST, no bpy)."""
    with open(PROPS_PY) as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "BUILDERS" for t in node.targets):
            return {k.value: v.id for k, v in zip(node.value.keys, node.value.values)}
    return {}


def _tokens(*parts):
    out = set()
    for p in parts:
        for t in (p if isinstance(p, (list, tuple)) else [p]):
            t = (t or "").lower()
            out.add(t)
            out |= set(re.split(r"[\s_:\-/.]+", t))
    out.discard("")
    return out


def _matches(term, toks):
    return all(w in toks for w in term.lower().split())


class PolyHavenSearch:
    """Poly Haven search with a JSON cache. mode='offline' reads only the cache (misses return []),
    'live' calls factory/library/sources/polyhaven.py search and records into the cache when record=True."""

    def __init__(self, cache_path, mode="offline", record=False):
        self.cache_path, self.mode, self.record = cache_path, mode, record
        self.cache = {}
        if cache_path and os.path.exists(cache_path):
            with open(cache_path) as fh:
                self.cache = json.load(fh)
        self.misses = []

    def search(self, term, kind):
        key = f"{kind}:{term.lower()}"
        if key in self.cache:
            return self.cache[key]
        if self.mode != "live":
            self.misses.append(key)
            return []
        if SOURCES not in sys.path:
            sys.path.insert(0, SOURCES)
        import polyhaven  # factory/library/sources/polyhaven.py (network)
        res = [list(r) for r in polyhaven.search(term.split(), kind)[:10]]
        self.cache[key] = res
        if self.record and self.cache_path:
            with open(self.cache_path, "w") as fh:
                json.dump(dict(sorted(self.cache.items())), fh, indent=1)
        return res


def resolve(breakdown, catalog=None, ph=None):
    catalog = catalog or load_catalog()
    assets = catalog.get("assets", {})
    reg = load_render_assets()
    blds = builders()
    catalogued_fns = {a.get("build", "").split(":")[-1] for a in assets.values() if "props.py" in a.get("build", "")}
    fn_to_key = {fn: k for k, fn in blds.items()}
    entries, attributions, gaps = [], [], []

    def render_key(cid, entry):
        if cid in reg:
            return reg[cid]["render_key"]
        b = entry.get("build", "")
        if "props.py:" in b:
            k = fn_to_key.get(b.split(":")[-1])
            return f"prop:{k}" if k else None
        return None

    def cand_tokens(cid, a):
        return _tokens(cid, a.get("name", ""), a.get("tags", []))

    internal = {k: v for k, v in assets.items() if v.get("provider") == "internal"}
    for k, v in reg.items():
        if v.get("uncatalogued") and k not in assets:
            internal[k] = {"id": k, "kind": v["kind"], "provider": "internal", "licence": "proprietary (ours)", "name": v["name"],
                           "tags": v["tags"], "build": v["file"]}
    external = {k: v for k, v in assets.items() if v.get("provider") != "internal"}

    def best(pool, el):
        term = el["search_terms"][0]
        ok = KIND_OK[el["kind"]]
        hits = [(cid, a) for cid, a in pool.items() if a.get("kind") in ok and _matches(term, cand_tokens(cid, a))]
        if not hits:
            return None
        allt = _tokens(el["search_terms"], el["name"])
        return max(hits, key=lambda h: (len(allt & cand_tokens(*h)), -len(h[0]), h[0]))  # most overlap, then shortest id

    for el in breakdown["elements"]:
        eid, kind, term = el["id"], el["kind"], el["search_terms"][0]
        base = {"element": eid, "kind": kind}
        if kind == "overlay":
            entries.append({**base, "decision": "BUILD", "recipe": f"remotion:{eid}", "licence": "proprietary (ours)", "status": "to_build",
                            "reason": "kinetic overlay, composited at stage 8 (Remotion)"})
            continue
        hit = best(internal, el)
        if hit:
            cid, a = hit
            e = {**base, "decision": "REUSE", "catalog_id": cid, "provider": "internal", "licence": a.get("licence", "proprietary (ours)"),
                 "status": "ready", "reason": f"internal library: {a.get('name', cid)} (matched '{term}')"}
            rk = render_key(cid, a)
            if rk:
                e["render_key"] = rk
            if cid not in assets:
                gaps.append(cid)
                e["reason"] += "; NOTE: not yet listed in factory/library/catalog.json"
            entries.append(e)
            continue
        if kind == "prop":
            bk = next((k for k, fn in blds.items() if fn not in catalogued_fns and _matches(term, _tokens(k, fn))), None)
            if bk:
                entries.append({**base, "decision": "BUILD", "recipe": f"cloud/blender/props.py:{blds[bk]}", "render_key": f"prop:{bk}",
                                "licence": "proprietary (ours)", "status": "ready",
                                "reason": f"existing code builder '{bk}' (not catalogued yet)"})
                gaps.append(f"props.py:{blds[bk]}")
                continue
        hit = best(external, el)
        if hit:
            cid, a = hit
            entries.append({**base, "decision": "REUSE", "catalog_id": cid, "provider": a["provider"], "asset_id": a.get("source_id", cid),
                            "url": a.get("url", ""), "authors": a.get("authors", []), "licence": a["licence"],
                            "files": [{"path": f["path"], "sha256": f["sha256"], "role": f.get("role", "")} for f in a.get("files", [])],
                            "status": "ready", "reason": f"already sourced into the library: {a.get('name', cid)} (matched '{term}')"})
            attributions.append(f"{a.get('name', cid)} by {', '.join(a.get('authors', [])) or 'unknown'} ({a['provider']}, {a['licence']}) {a.get('url', '')}".strip())
            continue
        if ph is not None and kind in PH_KIND and not el.get("story_specific"):
            res = ph.search(term, PH_KIND[kind])
            pick = next((r for r in res if _matches(term, _tokens(r[0], r[1] or ""))), None)
            if pick:
                aid, name = pick[0], pick[1]
                entries.append({**base, "decision": "SOURCE", "provider": "polyhaven", "asset_id": aid, "url": f"https://polyhaven.com/a/{aid}",
                                "licence": "CC0-1.0", "status": "to_fetch",
                                "reason": f"Poly Haven search '{term}' -> {name}; fetch with factory/library/sources/polyhaven.py fetch {aid}"})
                attributions.append(f"{name} (Poly Haven, CC0-1.0) https://polyhaven.com/a/{aid}")
                continue
        entries.append({**base, "decision": "BUILD", "recipe": f"proc:{eid}", "licence": "proprietary (ours)", "status": "to_build",
                        "reason": f"no library or Poly Haven match for '{term}'" + (" (story-specific)" if el.get("story_specific") else "")
                                  + ": procedural bpy recipe to write"})
    summary = {}
    for e in entries:
        summary[e["decision"]] = summary.get(e["decision"], 0) + 1
        summary[e["status"]] = summary.get(e["status"], 0) + 1
    man = {"id": breakdown["id"], "entries": entries, "attributions": attributions, "summary": summary}
    return man, sorted(set(gaps))
