"""Shared library-store helpers: every sourced file gets provenance (provider, url, licence, authors, sha256)."""
import hashlib, json, os, time, urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
STORE = os.environ.get("LIBRARY_STORE", os.path.join(ROOT, "library_store"))   # gitignored; synced to S3
CATALOG = os.path.join(ROOT, "factory", "library", "catalog.json")
UA = {"User-Agent": "episode-factory/0.1"}


def http_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return json.load(r)


def download(url, dest, tries=4):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    for t in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r, open(dest + ".part", "wb") as fh:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    fh.write(b)
            os.replace(dest + ".part", dest)
            return dest
        except Exception as e:
            print("retry", url, e)
            time.sleep(2 * (t + 1))
    raise RuntimeError(f"download failed {url}")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load_catalog():
    if os.path.exists(CATALOG):
        return json.load(open(CATALOG))
    return {"version": 1, "assets": {}}


def save_catalog(cat):
    os.makedirs(os.path.dirname(CATALOG), exist_ok=True)
    cat["assets"] = dict(sorted(cat["assets"].items()))
    json.dump(cat, open(CATALOG, "w"), indent=1)


def register(entry):
    """entry: {id, kind, provider, source_id, licence, authors, url, files:[{path, sha256, role}], tags, build?}"""
    cat = load_catalog()
    cat["assets"][entry["id"]] = entry
    save_catalog(cat)
    return entry
