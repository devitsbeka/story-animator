"""ambientCG adapter (CC0 PBR materials). API v2: https://ambientcg.com/api/v2/full_json
Usage: python3 ambientcg.py search <words> | fetch <AssetId> [--res 2K-JPG]"""
import argparse, os, sys, zipfile
sys.path.insert(0, os.path.dirname(__file__))
from common import STORE, http_json, download, sha256, register

API = "https://ambientcg.com/api/v2/full_json"


def search(words):
    q = "+".join(words)
    d = http_json(f"{API}?type=Material&q={q}&limit=40&include=downloadData,tagData")
    return [(a["assetId"], a.get("displayName"), a.get("downloadCount", 0)) for a in d.get("foundAssets", [])]


def fetch(asset_id, res="2K-JPG"):
    d = http_json(f"{API}?id={asset_id}&include=downloadData,tagData")
    a = d["foundAssets"][0]
    dls = a["downloadFolders"]["default"]["downloadFiletypeCategories"]["zip"]["downloads"]
    dl = next((x for x in dls if x["attribute"] == res), dls[0])
    out = os.path.join(STORE, "ambientcg", asset_id)
    z = download(dl["downloadLink"] if dl["downloadLink"].startswith("http") else dl["fullDownloadPath"], os.path.join(out, dl["fileName"]))
    with zipfile.ZipFile(z) as zf:
        zf.extractall(out)
    files = []
    for f in sorted(os.listdir(out)):
        p = os.path.join(out, f)
        if f.lower().endswith((".jpg", ".png")):
            role = next((r for r in ("Color", "NormalGL", "Roughness", "Displacement", "AmbientOcclusion", "Metalness", "Opacity") if r in f), "other")
            files.append({"path": os.path.relpath(p, STORE), "sha256": sha256(p), "role": role})
    e = {"id": f"acg:{asset_id}", "kind": "texture", "provider": "ambientcg", "source_id": asset_id, "name": a.get("displayName"),
         "licence": "CC0-1.0", "authors": ["ambientCG"], "url": f"https://ambientcg.com/view?id={asset_id}", "res": res,
         "files": files, "tags": a.get("tags", [])}
    register(e)
    return e


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "search"])
    ap.add_argument("args", nargs="+")
    ap.add_argument("--res", default="2K-JPG")
    a = ap.parse_args()
    if a.cmd == "search":
        for r in search(a.args):
            print(*r)
    else:
        for i in a.args:
            e = fetch(i, a.res)
            print("OK", e["id"], len(e["files"]), "files")
