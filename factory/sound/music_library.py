"""Licensed music library adapters (Pixabay Music / Free Music Archive style) + catalog provenance.

No scraping. A library track enters the factory only through a curated *intake manifest*: a JSON file a person
fills in after downloading a track by hand from the provider's site under its licence (the provider pages are the
source of truth for the licence; we record what they said and when). The adapter validates the licence for the
intended use, copies the file into $LIBRARY_STORE/music/<provider>/, hashes it, analyses tempo/beats, and registers
it in factory/library/catalog.json with full provenance. Once registered, any adapter can `search` the catalog.

Intake manifest (one per provider batch), e.g. factory/library/intake/pixabay_music.json:
  {"provider": "pixabay", "tracks": [
     {"source_id": "123456", "title": "Dark Tension", "author": "SomeArtist",
      "url": "https://pixabay.com/music/...-123456/", "licence": "Pixabay Content License",
      "licence_url": "https://pixabay.com/service/license-summary/", "retrieved": "2026-11-21",
      "file": "/path/to/downloaded.mp3", "bpm": 110, "key": "D minor", "mood": ["tense"], "tags": ["cinematic"]}]}

Classes:
  MusicTrack            normalised track record (what score.py needs + provenance)
  MusicSource           interface: search(), get(), fetch()  - every provider implements it
  CatalogSource         search registered music in catalog.json (any provider, incl. ElevenLabs stems)
  ManifestSource        intake from a curated manifest (base for library providers), licence policy enforced
  PixabayMusicSource    Pixabay Content License: commercial OK, no attribution required (attribution kept anyway)
  FMASource             Free Music Archive: per-track Creative Commons; NC / ND rejected for commercial use, BY needs
                        attribution (attribution line generated)

CLI:
  python3 -m factory.sound.music_library search --mood tense --bpm 110 --min-dur 30
  python3 -m factory.sound.music_library intake --provider pixabay --manifest factory/library/intake/pixabay_music.json
"""
import argparse, dataclasses, json, os, shutil, sys
from typing import List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
STORE = os.environ.get("LIBRARY_STORE", os.path.join(ROOT, "library_store"))
sys.path.insert(0, os.path.join(ROOT, "factory", "library", "sources"))
import common  # noqa: E402  (catalog read/write, sha256)


class LicenceError(ValueError):
    pass


@dataclasses.dataclass
class MusicTrack:
    id: str
    provider: str
    source_id: str
    title: str
    authors: List[str]
    licence: str
    url: Optional[str] = None
    licence_url: Optional[str] = None
    file: Optional[str] = None            # path relative to $LIBRARY_STORE
    sha256: Optional[str] = None
    duration_s: Optional[float] = None
    bpm: Optional[float] = None
    key: Optional[str] = None
    mood: List[str] = dataclasses.field(default_factory=list)
    tags: List[str] = dataclasses.field(default_factory=list)
    role: Optional[str] = None            # tension | dark | resolve (score.py stem role)
    attribution: Optional[str] = None     # line to print in the credits, when the licence requires it
    commercial_ok: bool = True
    retrieved: Optional[str] = None

    def path(self, store=None):
        return os.path.join(store or STORE, self.file) if self.file else None

    def catalog_entry(self):
        return {
            "id": self.id, "kind": "music", "provider": self.provider, "source_id": self.source_id,
            "name": self.title, "licence": self.licence, "authors": self.authors, "url": self.url,
            "provenance": {"licence_url": self.licence_url, "retrieved": self.retrieved, "attribution": self.attribution,
                           "commercial_ok": self.commercial_ok, "intake": "factory/sound/music_library.py"},
            "files": [{"path": self.file, "sha256": self.sha256, "role": "audio"}] if self.file else [],
            "tags": sorted(set(self.tags + self.mood + (["music"] + ([self.role] if self.role else [])))),
            "music": {"role": self.role, "bpm_measured": self.bpm, "key": self.key, "mood": self.mood, "duration_s": self.duration_s},
        }

    @classmethod
    def from_catalog(cls, e):
        m = e.get("music", {})
        f = (e.get("files") or [{}])[0]
        prov = e.get("provenance", {})
        return cls(id=e["id"], provider=e["provider"], source_id=e.get("source_id", ""), title=e.get("name", e["id"]),
                   authors=e.get("authors", []), licence=e.get("licence", ""), url=e.get("url"),
                   licence_url=prov.get("licence_url"), file=f.get("path"), sha256=f.get("sha256"),
                   duration_s=m.get("duration_s") or prov.get("duration_s"),
                   bpm=m.get("bpm_measured") or m.get("bpm_nominal"), key=m.get("key"),
                   mood=m.get("mood") or [], tags=e.get("tags", []), role=m.get("role"),
                   attribution=prov.get("attribution"), commercial_ok=prov.get("commercial_ok", True),
                   retrieved=prov.get("retrieved") or prov.get("generated"))


def _match(t: MusicTrack, mood=None, bpm=None, bpm_tol=0.06, min_dur=None, role=None, tags=None, commercial=True):
    if commercial and not t.commercial_ok:
        return False
    if mood and mood not in t.mood and mood not in t.tags:
        return False
    if role and t.role != role:
        return False
    if min_dur and (t.duration_s or 0) < min_dur:
        return False
    if tags and not set(tags) <= set(t.tags):
        return False
    if bpm and t.bpm:
        # half / double time also stitch on the same grid
        if not any(abs(t.bpm * k - bpm) / bpm <= bpm_tol for k in (0.5, 1.0, 2.0)):
            return False
    elif bpm and not t.bpm:
        return False
    return True


class MusicSource:
    """Interface every music provider implements."""
    provider = "abstract"

    def search(self, **query) -> List[MusicTrack]:
        raise NotImplementedError

    def get(self, track_id) -> MusicTrack:
        for t in self.search():
            if t.id == track_id:
                return t
        raise KeyError(track_id)

    def fetch(self, track: MusicTrack, store=None) -> str:
        """Local path of the track's audio in the library store (no network for curated providers)."""
        p = track.path(store)
        if not p or not os.path.exists(p):
            raise FileNotFoundError(f"{track.id}: {p} not in the library store")
        return p


class CatalogSource(MusicSource):
    provider = "catalog"

    def __init__(self, catalog=None):
        self.catalog = catalog

    def _cat(self):
        return self.catalog if self.catalog is not None else common.load_catalog()

    def search(self, **q):
        ts = [MusicTrack.from_catalog(e) for e in self._cat()["assets"].values() if e.get("kind") == "music"]
        return [t for t in ts if _match(t, **q)]


class ManifestSource(MusicSource):
    """Curated intake. Subclasses set provider/prefix and implement licence_policy()."""
    provider = "manifest"
    prefix = "lib"
    REQUIRED = ("source_id", "title", "author", "url", "licence", "retrieved", "file")

    def __init__(self, manifest_path=None, manifest=None, store=None):
        self.manifest = manifest if manifest is not None else (json.load(open(manifest_path)) if manifest_path else {"tracks": []})
        self.store = store or STORE

    def licence_policy(self, rec):
        """-> (commercial_ok, attribution or None); raise LicenceError to reject."""
        return True, None

    def to_track(self, rec):
        missing = [k for k in self.REQUIRED if not rec.get(k)]
        if missing:
            raise ValueError(f"{self.provider} track {rec.get('source_id')}: missing {missing}")
        ok, attribution = self.licence_policy(rec)
        ext = os.path.splitext(rec["file"])[1] or ".mp3"
        rel = os.path.join("music", self.provider, f"{rec['source_id']}{ext}")
        t = MusicTrack(id=f"{self.prefix}:music_{rec['source_id']}", provider=self.provider, source_id=str(rec["source_id"]),
                       title=rec["title"], authors=[rec["author"]], licence=rec["licence"], url=rec["url"],
                       licence_url=rec.get("licence_url"), file=rel, bpm=rec.get("bpm"), key=rec.get("key"),
                       mood=list(rec.get("mood", [])), tags=list(rec.get("tags", [])), role=rec.get("role"),
                       attribution=attribution, commercial_ok=ok, retrieved=rec["retrieved"])
        return t

    def search(self, **q):
        out = []
        for rec in self.manifest.get("tracks", []):
            try:
                t = self.to_track(rec)
            except (LicenceError, ValueError):
                continue
            if _match(t, **q):
                out.append(t)
        return out

    def intake(self, analyse=True, register=True, decode=None):
        """Copy, hash, analyse and register every manifest track. Returns (registered, rejected)."""
        done, rejected = [], []
        for rec in self.manifest.get("tracks", []):
            try:
                t = self.to_track(rec)
            except (LicenceError, ValueError) as e:
                rejected.append({"source_id": rec.get("source_id"), "reason": str(e)})
                continue
            dst = t.path(self.store)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.abspath(rec["file"]) != os.path.abspath(dst):
                shutil.copyfile(rec["file"], dst)
            t.sha256 = common.sha256(dst)
            if analyse:
                sys.path.insert(0, HERE)
                import beats
                if decode is None:
                    from audio_util import decode as decode_fn
                else:
                    decode_fn = decode
                x = decode_fn(dst)
                a = beats.analyse(x, 48000, prior_bpm=rec.get("bpm"))
                t.bpm, t.duration_s = round(a["bpm"], 2), round(a["dur"], 3)
            if register:
                common.register(t.catalog_entry())
            done.append(t)
        return done, rejected


class PixabayMusicSource(ManifestSource):
    """Pixabay Music under the Pixabay Content License (free for commercial use, no attribution required; tracks may
    not be redistributed standalone or sold as-is). Content ID-registered tracks are rejected: they trigger claims on
    YouTube/Facebook uploads."""
    provider = "pixabay"
    prefix = "pixabay"

    def licence_policy(self, rec):
        if "pixabay" not in rec["licence"].lower():
            raise LicenceError(f"unexpected licence for Pixabay track: {rec['licence']!r}")
        if rec.get("content_id"):
            raise LicenceError("track is registered with a Content ID service (upload claims)")
        return True, f"Music: \"{rec['title']}\" by {rec['author']} (Pixabay)"


class FMASource(ManifestSource):
    """Free Music Archive: licence is per track (Creative Commons). CC0 / CC BY / CC BY-SA allowed (BY needs
    attribution, SA flagged in tags); NC and ND rejected for a commercial, edited score."""
    provider = "fma"
    prefix = "fma"

    def licence_policy(self, rec):
        lic = rec["licence"].upper().replace("-", " ")
        if "CC0" in lic or "PUBLIC DOMAIN" in lic:
            return True, None
        if not lic.startswith("CC BY"):
            raise LicenceError(f"unsupported FMA licence {rec['licence']!r}")
        if " NC" in lic:
            raise LicenceError(f"{rec['licence']}: non-commercial")
        if " ND" in lic:
            raise LicenceError(f"{rec['licence']}: no derivatives (the score edits and stitches tracks)")
        if " SA" in lic:
            rec.setdefault("tags", []).append("share_alike")
        return True, f"\"{rec['title']}\" by {rec['author']}, {rec['licence']} ({rec['url']})"


PROVIDERS = {"pixabay": PixabayMusicSource, "fma": FMASource}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["search", "intake"])
    ap.add_argument("--provider", choices=list(PROVIDERS))
    ap.add_argument("--manifest")
    ap.add_argument("--mood")
    ap.add_argument("--role")
    ap.add_argument("--bpm", type=float)
    ap.add_argument("--min-dur", type=float)
    a = ap.parse_args()
    if a.cmd == "search":
        for t in CatalogSource().search(mood=a.mood, role=a.role, bpm=a.bpm, min_dur=a.min_dur):
            print(f"{t.id:32s} {t.provider:10s} {t.bpm or '-':>7} BPM {t.duration_s or '-':>7}s  {t.licence[:60]}")
    else:
        src = PROVIDERS[a.provider](a.manifest)
        done, rej = src.intake()
        print("registered", [t.id for t in done])
        for r in rej:
            print("rejected", r)


if __name__ == "__main__":
    main()
