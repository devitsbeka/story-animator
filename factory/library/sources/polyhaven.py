"""Poly Haven adapter (CC0): models (glTF), HDRIs (EXR/HDR), textures (PBR maps).
API: https://api.polyhaven.com/assets?t=<type>, /info/<id>, /files/<id>.
Usage: python3 polyhaven.py fetch <id> [--res 2k] [--kind model|hdri|texture]
       python3 polyhaven.py search <words> [--kind model]
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from common import STORE, http_json, download, sha256, register

API = "https://api.polyhaven.com"
TYPES = {"model": "models", "hdri": "hdris", "texture": "textures"}


def search(words, kind="model"):
    a = http_json(f"{API}/assets?t={TYPES[kind]}")
    ws = [w.lower() for w in words]
    out = []
    for k, v in a.items():
        hay = " ".join([k, v.get("name", ""), *v.get("tags", []), *v.get("categories", [])]).lower()
        if all(w in hay for w in ws):
            out.append((k, v.get("name"), v.get("download_count", 0)))
    return sorted(out, key=lambda x: -x[2])


def fetch(asset_id, res="2k", kind=None):
    info = http_json(f"{API}/info/{asset_id}")
    kind = kind or {0: "hdri", 1: "texture", 2: "model"}[info["type"]]
    files = http_json(f"{API}/files/{asset_id}")
    d = os.path.join(STORE, "polyhaven", asset_id)
    got = []
    if kind == "model":
        g = files["gltf"].get(res) or files["gltf"][sorted(files["gltf"])[0]]
        g = g["gltf"]
        main = download(g["url"], os.path.join(d, os.path.basename(g["url"])))
        got.append({"path": os.path.relpath(main, STORE), "sha256": sha256(main), "role": "gltf"})
        for rel, inc in g.get("include", {}).items():
            p = download(inc["url"], os.path.join(d, rel))
            got.append({"path": os.path.relpath(p, STORE), "sha256": sha256(p), "role": "include"})
    elif kind == "hdri":
        h = files["hdri"].get(res) or files["hdri"]["2k"]
        f = h.get("exr") or h.get("hdr")
        p = download(f["url"], os.path.join(d, os.path.basename(f["url"])))
        got.append({"path": os.path.relpath(p, STORE), "sha256": sha256(p), "role": "hdri"})
    else:
        for mapname in ("Diffuse", "nor_gl", "Rough", "Displacement", "AO", "arm"):
            m = files.get(mapname)
            if not m:
                continue
            r = m.get(res) or m[sorted(m)[0]]
            f = r.get("jpg") or r.get("png") or r.get("exr")
            p = download(f["url"], os.path.join(d, os.path.basename(f["url"])))
            got.append({"path": os.path.relpath(p, STORE), "sha256": sha256(p), "role": mapname})
    entry = {
        "id": f"ph:{asset_id}", "kind": kind, "provider": "polyhaven", "source_id": asset_id,
        "name": info.get("name"), "licence": "CC0-1.0", "authors": list(info.get("authors", {}).keys()),
        "url": f"https://polyhaven.com/a/{asset_id}", "res": res, "files": got,
        "tags": info.get("tags", []) + info.get("categories", []),
        "dims_mm": info.get("dimensions"),
    }
    register(entry)
    return entry


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "search"])
    ap.add_argument("args", nargs="+")
    ap.add_argument("--res", default="2k")
    ap.add_argument("--kind", default=None)
    a = ap.parse_args()
    if a.cmd == "search":
        for r in search(a.args, a.kind or "model")[:40]:
            print(*r)
    else:
        for i in a.args:
            e = fetch(i, a.res, a.kind)
            print("OK", e["id"], e["kind"], len(e["files"]), "files")
