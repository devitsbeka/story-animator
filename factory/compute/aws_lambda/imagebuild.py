"""
imagebuild.py - assemble the Blender Lambda container image WITHOUT Docker and push it to ECR (boto3 only).

Why: CodeBuild is the intended builder (buildspec.yml), but new accounts start with every CodeBuild
"concurrently running builds" quota at 0 (StartBuild -> AccountLimitExceededException) until a quota request is
approved. An OCI image is just tarballs + JSON, so this module builds the SAME image the Dockerfile describes:

  layer 0..n  public.ecr.aws/lambda/python:3.12 (linux/amd64), pulled from the public registry, unchanged
  layer +1    the X11/GL client libraries Blender links against, from the Amazon Linux 2023 RPM repository
              (dependency closure of the sonames the base image lacks; RPM payload -> cpio -> tar, no rpm tool)
  layer +2    /opt/blender = the official blender-4.2.3-linux-x64.tar.xz (sha256-pinned, same as the Dockerfile)
  layer +3    /var/task/handler.py
  config      the base config + ENV (HOME=/tmp, BLENDER_USER_* in /tmp, ...) + CMD ["handler.handler"]

`verify_rootfs()` runs the real Blender binary against the assembled AL2023 libraries on this machine (through the
image's own ld-linux and glibc) before anything is pushed, so a missing library fails here, not in Lambda.

    python3 -m factory.compute.aws_lambda.imagebuild build --out /tmp/compute_broker/image
    python3 -m factory.compute.aws_lambda.imagebuild push  --out /tmp/compute_broker/image --repo story-compute/blender-lambda --tag <tag>
"""
import argparse
import gzip
import hashlib
import io
import json
import lzma
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_REPO, BASE_TAG = "lambda/python", "3.12"
AL2023_MIRRORLIST = "https://cdn.amazonlinux.com/al2023/core/mirrors/latest/x86_64/mirror.list"
BLENDER_VERSION, BLENDER_SERIES = "4.2.3", "4.2"
BLENDER_SHA256 = "3a64efd1982465395abab4259b4091d5c8c56054c7267e9633e4f702a71ea3f4"
BLENDER_URL = (f"https://download.blender.org/release/Blender{BLENDER_SERIES}/"
               f"blender-{BLENDER_VERSION}-linux-x64.tar.xz")
# What `ldd blender` needs beyond glibc/libstdc++ (checked on 4.2.3): resolved to AL2023 packages + their closure.
NEEDED_SONAMES = ["libX11.so.6", "libXrender.so.1", "libXxf86vm.so.1", "libXfixes.so.3", "libXi.so.6",
                  "libxkbcommon.so.0", "libXext.so.6", "libSM.so.6", "libICE.so.6", "libGL.so.1", "libEGL.so.1",
                  "libxcb.so.1", "libXau.so.6", "libgomp.so.1", "libuuid.so.1", "libz.so.1"]
ENV = {"HOME": "/tmp", "BLENDER": "/opt/blender/blender", "BLENDER_USER_CONFIG": "/tmp/blender/config",
       "BLENDER_USER_SCRIPTS": "/tmp/blender/scripts", "BLENDER_USER_DATAFILES": "/tmp/blender/datafiles",
       "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
MT_MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"
MT_CONFIG = "application/vnd.docker.container.image.v1+json"
MT_LAYER = "application/vnd.docker.image.rootfs.diff.tar.gzip"
ACCEPT = ", ".join(["application/vnd.oci.image.index.v1+json", "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.oci.image.manifest.v1+json", MT_MANIFEST])


def log(msg, **kw):
    print(json.dumps({"t": round(time.time(), 1), "msg": msg, **kw}, default=str), file=sys.stderr, flush=True)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def http(url, headers=None, dest=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=300) as r:
        if dest is None:
            return r.read()
        with open(dest + ".part", "wb") as fh:
            shutil.copyfileobj(r, fh, 1 << 20)
        os.replace(dest + ".part", dest)
        return dest


# ----------------------------------------------------------------------------------------------- base image
def pull_base(out, repo=BASE_REPO, tag=BASE_TAG):
    """-> (config dict, [layer dicts {path, digest, size}]) of linux/amd64, blobs cached under out/blobs."""
    tok = json.loads(http(f"https://public.ecr.aws/token/?scope=repository:{repo}:pull"))["token"]
    H = {"Authorization": f"Bearer {tok}", "Accept": ACCEPT}
    base = f"https://public.ecr.aws/v2/{repo}"
    m = json.loads(http(f"{base}/manifests/{tag}", H))
    if "manifests" in m:
        pick = [x for x in m["manifests"] if x.get("platform", {}).get("architecture") == "amd64"
                and x.get("platform", {}).get("os") == "linux"]
        m = json.loads(http(f"{base}/manifests/{pick[0]['digest']}", H))
    blobs = os.path.join(out, "blobs")
    os.makedirs(blobs, exist_ok=True)

    def blob(d):
        p = os.path.join(blobs, d.replace(":", "_"))
        if not (os.path.isfile(p) and "sha256:" + sha256_file(p) == d):
            http(f"{base}/blobs/{d}", {"Authorization": f"Bearer {tok}"}, p)
            if "sha256:" + sha256_file(p) != d:
                raise RuntimeError(f"digest mismatch for base blob {d}")
        return p
    cfg_path = blob(m["config"]["digest"])
    with open(cfg_path) as fh:
        cfg = json.load(fh)
    layers = []
    for L in m["layers"]:
        if "gzip" not in L["mediaType"]:
            raise RuntimeError(f"base layer media type {L['mediaType']} not supported (gzip only)")
        layers.append({"path": blob(L["digest"]), "digest": L["digest"], "size": L["size"]})
    log("base pulled", repo=repo, tag=tag, layers=len(layers), mb=round(sum(x["size"] for x in layers) / 1e6, 1))
    return cfg, layers


def extract_layers(layers, rootfs):
    """Apply gzip layers into a directory (whiteouts honoured). -> set of paths (relative, no leading /)."""
    os.makedirs(rootfs, exist_ok=True)
    names = set()
    for L in layers:
        with tarfile.open(L["path"], "r:gz") as tf:
            for m in tf.getmembers():
                n = m.name.lstrip("./")
                base = os.path.basename(n)
                if base.startswith(".wh."):
                    victim = os.path.join(os.path.dirname(n), base[4:])
                    names.discard(victim)
                    vp = os.path.join(rootfs, victim)
                    if os.path.islink(vp) or os.path.isfile(vp):
                        os.unlink(vp)
                    elif os.path.isdir(vp):
                        shutil.rmtree(vp, ignore_errors=True)
                    continue
                names.add(n)
                if m.isdev():
                    continue
                try:
                    tf.extract(m, rootfs, filter="tar", set_attrs=False)
                except (OSError, tarfile.TarError):
                    pass
    return names


# ----------------------------------------------------------------------------------------------- AL2023 RPMs
def _vkey(v):
    return [int(x) if x.isdigit() else x for x in re.split(r"[^0-9A-Za-z]+|(?<=\d)(?=\D)|(?<=\D)(?=\d)", v) if x]


def al2023_packages(cache):
    mirror = http(AL2023_MIRRORLIST).decode().split()[0].rstrip("/")
    os.makedirs(cache, exist_ok=True)
    prim = os.path.join(cache, "primary.xml.gz")
    if not os.path.isfile(prim) or time.time() - os.path.getmtime(prim) > 86400:
        repomd = http(f"{mirror}/repodata/repomd.xml").decode()
        href = re.search(r'<data type="primary">.*?<location href="([^"]+)"', repomd, re.S).group(1)
        http(f"{mirror}/{href}", dest=prim)
    ns = {"c": "http://linux.duke.edu/metadata/common", "rpm": "http://linux.duke.edu/metadata/rpm"}
    pkgs = {}
    for _, el in ET.iterparse(gzip.open(prim), events=("end",)):
        if el.tag != "{http://linux.duke.edu/metadata/common}package":
            continue
        arch = el.findtext("c:arch", namespaces=ns)
        if arch not in ("x86_64", "noarch"):
            el.clear()
            continue
        v = el.find("c:version", ns).attrib
        rec = {"name": el.findtext("c:name", namespaces=ns), "arch": arch,
               "evr": (int(v.get("epoch") or 0), _vkey(v["ver"]), _vkey(v["rel"])),
               "version": f"{v['ver']}-{v['rel']}", "href": el.find("c:location", ns).attrib["href"],
               "sha256": el.findtext("c:checksum", namespaces=ns),
               "provides": [e.attrib["name"] for e in el.findall("c:format/rpm:provides/rpm:entry", ns)],
               "requires": [e.attrib["name"] for e in el.findall("c:format/rpm:requires/rpm:entry", ns)]}
        cur = pkgs.get(rec["name"])
        try:
            newer = cur is None or rec["evr"] > cur["evr"]
        except TypeError:
            newer = str(rec["evr"]) > str(cur["evr"])
        if newer:
            pkgs[rec["name"]] = rec
        el.clear()
    return mirror, pkgs


def _soname(req):
    m = re.match(r"(lib[^()]+\.so[.0-9]*)\(.*64bit\)$", req)
    return m.group(1) if m else None


def resolve(pkgs, have_files, sonames=NEEDED_SONAMES):
    """Packages providing `sonames` the base lacks, plus their library closure (only libs the base lacks)."""
    have = {os.path.basename(n) for n in have_files}
    prov = {}
    for p in pkgs.values():
        for e in p["provides"]:
            prov.setdefault(e, []).append(p["name"])
    want, seen, order = list(sonames), set(), []
    while want:
        so = want.pop()
        if so in seen:
            continue
        seen.add(so)
        if so in have:
            continue
        cands = prov.get(f"{so}()(64bit)") or []
        if not cands:
            log("no AL2023 provider", soname=so)
            continue
        name = sorted(cands, key=lambda n: (n.endswith("-devel"), len(n)))[0]
        if name in order:
            continue
        order.append(name)
        for r in pkgs[name]["requires"]:
            s = _soname(r)
            if s:
                want.append(s)
    return order


def rpm_payload(data):
    """-> decompressed cpio bytes of an RPM (lead + signature header (8-aligned) + header + payload)."""
    off = 96

    def header(o):
        if data[o:o + 3] != b"\x8e\xad\xe8":
            raise ValueError("bad rpm header magic")
        n = int.from_bytes(data[o + 8:o + 12], "big")
        size = int.from_bytes(data[o + 12:o + 16], "big")
        return o + 16 + 16 * n + size
    off = header(off)
    off += (-off) % 8
    off = header(off)
    pay = data[off:]
    if pay[:6] == b"\xfd7zXZ\x00":
        return lzma.decompress(pay)
    if pay[:4] == b"\x28\xb5\x2f\xfd":
        import zstandard
        return zstandard.ZstdDecompressor().stream_reader(io.BytesIO(pay)).read()
    if pay[:2] == b"\x1f\x8b":
        return gzip.decompress(pay)
    raise ValueError(f"unknown rpm payload compression {pay[:6]!r}")


def cpio_entries(buf):
    """newc cpio -> [(name, mode, data)] (hardlinked files keep their data on the last link)."""
    out, o = [], 0
    while o < len(buf):
        if buf[o:o + 6] not in (b"070701", b"070702"):
            raise ValueError(f"bad cpio magic at {o}")
        f = [int(buf[o + 6 + 8 * i:o + 14 + 8 * i], 16) for i in range(13)]
        mode, filesize, namesize = f[1], f[6], f[11]
        name = buf[o + 110:o + 110 + namesize - 1].decode()
        o += 110 + namesize
        o += (-o) % 4
        data = buf[o:o + filesize]
        o += filesize
        o += (-o) % 4
        if name == "TRAILER!!!":
            break
        out.append((name, mode, data))
    return out


# ----------------------------------------------------------------------------------------------- layers
class LayerWriter:
    """Deterministic gzip tar layer -> (path, digest, diff_id, size)."""

    def __init__(self, path, base_names=(), base_links=None):
        self.path = path
        self.base = set(base_names)
        self.links = base_links or {}
        self.raw = hashlib.sha256()
        self.fh = open(path, "wb")
        self.gz = gzip.GzipFile(fileobj=self.fh, mode="wb", mtime=0, compresslevel=6)
        self._tee = _Tee(self.gz, self.raw)
        self.tf = tarfile.open(fileobj=self._tee, mode="w", format=tarfile.PAX_FORMAT)
        self.dirs = set()

    def canon(self, name):
        name = name.lstrip("./").lstrip("/")
        top, _, rest = name.partition("/")
        if top in self.links and rest:
            name = self.links[top].rstrip("/") + "/" + rest
        return name

    def _parents(self, name):
        parts = name.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            d = "/".join(parts[:i])
            if d in self.dirs or d in self.base or d in self.links:
                continue
            ti = tarfile.TarInfo(d)
            ti.type, ti.mode, ti.mtime = tarfile.DIRTYPE, 0o755, 0
            self.tf.addfile(ti)
            self.dirs.add(d)

    def add_bytes(self, name, data, mode=0o644):
        name = self.canon(name)
        self._parents(name)
        ti = tarfile.TarInfo(name)
        ti.size, ti.mode, ti.mtime = len(data), mode & 0o7777, 0
        self.tf.addfile(ti, io.BytesIO(data))

    def add_symlink(self, name, target):
        name = self.canon(name)
        self._parents(name)
        ti = tarfile.TarInfo(name)
        ti.type, ti.linkname, ti.mode, ti.mtime = tarfile.SYMTYPE, target, 0o777, 0
        self.tf.addfile(ti)

    def add_dir(self, name, mode=0o755):
        name = self.canon(name).rstrip("/")
        if not name or name in self.dirs or name in self.base or name in self.links:
            return
        self._parents(name + "/x")
        ti = tarfile.TarInfo(name)
        ti.type, ti.mode, ti.mtime = tarfile.DIRTYPE, mode & 0o7777, 0
        self.tf.addfile(ti)
        self.dirs.add(name)

    def close(self):
        self.tf.close()
        self.gz.close()
        self.fh.close()
        return {"path": self.path, "digest": "sha256:" + sha256_file(self.path),
                "diff_id": "sha256:" + self.raw.hexdigest(), "size": os.path.getsize(self.path)}


class _Tee:
    def __init__(self, f, h):
        self.f, self.h = f, h

    def write(self, b):
        self.h.update(b)
        return self.f.write(b)

    def tell(self):
        return self.f.tell()


def base_symlinks(rootfs):
    return {n: os.readlink(os.path.join(rootfs, n)) for n in os.listdir(rootfs)
            if os.path.islink(os.path.join(rootfs, n))}


def build(out, handler_path=os.path.join(HERE, "handler.py"), blender_tarball=None):
    os.makedirs(out, exist_ok=True)
    cfg, base_layers = pull_base(out)
    rootfs = os.path.join(out, "rootfs")
    shutil.rmtree(rootfs, ignore_errors=True)
    base_names = extract_layers(base_layers, rootfs)
    links = base_symlinks(rootfs)
    # --- layer: AL2023 libs
    mirror, pkgs = al2023_packages(os.path.join(out, "rpmcache"))
    names = resolve(pkgs, base_names)
    log("al2023 packages", packages=names)
    lw = LayerWriter(os.path.join(out, "layer-libs.tar.gz"), base_names, links)
    rpms = []
    for n in names:
        p = pkgs[n]
        dst = os.path.join(out, "rpmcache", os.path.basename(p["href"]))
        if not (os.path.isfile(dst) and sha256_file(dst) == p["sha256"]):
            http(urllib.parse.urljoin(mirror + "/", p["href"]), dest=dst)
        if sha256_file(dst) != p["sha256"]:
            raise RuntimeError(f"sha256 mismatch for {p['href']}")
        with open(dst, "rb") as fh:
            entries = cpio_entries(rpm_payload(fh.read()))
        for name, mode, data in entries:
            kind = mode & 0o170000
            rel = name.lstrip("./")
            if rel.startswith("usr/share/doc") or rel.startswith("usr/share/man") or rel.startswith("usr/share/licenses"):
                continue
            if kind == 0o040000:
                lw.add_dir(rel, mode)
            elif kind == 0o120000:
                lw.add_symlink(rel, data.decode())
            elif kind == 0o100000 and data:
                lw.add_bytes(rel, data, mode)
            # also materialise into the rootfs for verify_rootfs()
            tgt = os.path.join(rootfs, lw.canon(rel))
            if kind == 0o040000:
                os.makedirs(tgt, exist_ok=True)
            elif kind in (0o120000, 0o100000):
                os.makedirs(os.path.dirname(tgt), exist_ok=True)
                if os.path.lexists(tgt):
                    os.unlink(tgt)
                if kind == 0o120000:
                    os.symlink(data.decode(), tgt)
                elif data:
                    with open(tgt, "wb") as fh:
                        fh.write(data)
                    os.chmod(tgt, mode & 0o777)
        rpms.append({"name": n, "version": p["version"], "sha256": p["sha256"]})
    libs = lw.close()
    # --- layer: Blender
    tb = blender_tarball or os.path.join(out, f"blender-{BLENDER_VERSION}-linux-x64.tar.xz")
    if not (os.path.isfile(tb) and sha256_file(tb) == BLENDER_SHA256):
        log("downloading blender", url=BLENDER_URL)
        http(BLENDER_URL, dest=tb)
    if sha256_file(tb) != BLENDER_SHA256:
        raise RuntimeError("blender tarball sha256 mismatch")
    lw = LayerWriter(os.path.join(out, "layer-blender.tar.gz"), base_names, links)
    bdir = os.path.join(rootfs, "opt", "blender")
    shutil.rmtree(bdir, ignore_errors=True)
    lw.add_dir("opt/blender")
    with tarfile.open(tb, "r:xz") as tf:
        for m in tf:
            parts = m.name.split("/", 1)
            if len(parts) < 2 or not parts[1]:
                continue
            rel = "opt/blender/" + parts[1]
            tgt = os.path.join(rootfs, rel)
            if m.isdir():
                lw.add_dir(rel, m.mode)
                os.makedirs(tgt, exist_ok=True)
            elif m.issym():
                lw.add_symlink(rel, m.linkname)
                os.makedirs(os.path.dirname(tgt), exist_ok=True)
                if os.path.lexists(tgt):
                    os.unlink(tgt)
                os.symlink(m.linkname, tgt)
            elif m.isfile():
                data = tf.extractfile(m).read()
                lw.add_bytes(rel, data, m.mode)
                os.makedirs(os.path.dirname(tgt), exist_ok=True)
                with open(tgt, "wb") as fh:
                    fh.write(data)
                os.chmod(tgt, m.mode & 0o777)
    blender_layer = lw.close()
    # --- layer: handler
    lw = LayerWriter(os.path.join(out, "layer-handler.tar.gz"), base_names, links)
    with open(handler_path, "rb") as fh:
        hdata = fh.read()
    lw.add_bytes("var/task/handler.py", hdata, 0o644)
    handler_layer = lw.close()
    # --- config
    new = json.loads(json.dumps(cfg))
    c = new.setdefault("config", {})
    env = [e for e in c.get("Env", []) if e.split("=", 1)[0] not in ENV]
    c["Env"] = env + [f"{k}={v}" for k, v in ENV.items()]
    c["Cmd"] = ["handler.handler"]
    new["rootfs"]["diff_ids"] = list(new["rootfs"]["diff_ids"]) + [libs["diff_id"], blender_layer["diff_id"],
                                                                   handler_layer["diff_id"]]
    now = "2024-01-01T00:00:00Z"
    new.setdefault("history", []).extend([
        {"created": now, "created_by": f"story-compute imagebuild: AL2023 rpms {','.join(names)}"},
        {"created": now, "created_by": f"story-compute imagebuild: blender {BLENDER_VERSION} sha256 {BLENDER_SHA256}"},
        {"created": now, "created_by": "story-compute imagebuild: handler.py"}])
    cfg_bytes = json.dumps(new, sort_keys=True, separators=(",", ":")).encode()
    cfg_path = os.path.join(out, "config.json")
    with open(cfg_path, "wb") as fh:
        fh.write(cfg_bytes)
    layers = [{"path": L["path"], "digest": L["digest"], "size": L["size"]} for L in base_layers] + \
             [{k: L[k] for k in ("path", "digest", "size")} for L in (libs, blender_layer, handler_layer)]
    manifest = {"schemaVersion": 2, "mediaType": MT_MANIFEST,
                "config": {"mediaType": MT_CONFIG, "size": len(cfg_bytes),
                           "digest": "sha256:" + hashlib.sha256(cfg_bytes).hexdigest()},
                "layers": [{"mediaType": MT_LAYER, "size": L["size"], "digest": L["digest"]} for L in layers]}
    plan = {"manifest": manifest, "config": cfg_path, "layers": layers, "rpms": rpms, "rootfs": rootfs,
            "tag": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:16],
            "bytes": sum(L["size"] for L in layers) + len(cfg_bytes)}
    with open(os.path.join(out, "image.json"), "w") as fh:
        json.dump(plan, fh, indent=1)
    log("image assembled", tag=plan["tag"], mb=round(plan["bytes"] / 1e6, 1), layers=len(layers))
    return plan


def verify_rootfs(rootfs, timeout=300):
    """Run the image's Blender with the image's own loader + libraries (AL2023 glibc), headless."""
    ld = os.path.join(rootfs, "usr", "lib64", "ld-linux-x86-64.so.2")
    libpath = ":".join(os.path.join(rootfs, d) for d in ("usr/lib64", "usr/lib64/pulseaudio", "opt/blender/lib"))
    blender = os.path.join(rootfs, "opt", "blender", "blender")
    real_ld = os.path.realpath(ld)
    os.chmod(real_ld, os.stat(real_ld).st_mode | 0o755)   # base layers are extracted without attributes
    # Run through ld.so, /proc/self/exe is the loader, and Blender looks for <exe dir>/4.2/: link it there
    # for the duration of the check (the rootfs copy only; the pushed layers are untouched).
    link = os.path.join(os.path.dirname(real_ld), BLENDER_SERIES)
    if not os.path.lexists(link):
        os.symlink(os.path.join(rootfs, "opt", "blender", BLENDER_SERIES), link)
    env = {"HOME": "/tmp", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    cmd = [ld, "--library-path", libpath, blender, "-b", "--factory-startup", "--python-expr",
           "import bpy; print('BLENDER_OK', bpy.app.version_string)"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    finally:
        if os.path.islink(link):
            os.unlink(link)
    ok = "BLENDER_OK" in r.stdout
    missing = re.findall(r"error while loading shared libraries: (\S+)", r.stderr)
    return {"ok": ok, "rc": r.returncode, "missing": missing,
            "out": (r.stdout + r.stderr)[-800:] if not ok else r.stdout.strip().splitlines()[-1]}


# ----------------------------------------------------------------------------------------------- push
def push(plan, ecr, repo, tag=None, part=20 * 1024 * 1024):
    tag = tag or plan["tag"]
    blobs = [{"path": plan["config"], "digest": plan["manifest"]["config"]["digest"]}] + plan["layers"]
    have = set()
    for i in range(0, len(blobs), 100):
        r = ecr.batch_check_layer_availability(repositoryName=repo, layerDigests=[b["digest"] for b in blobs[i:i + 100]])
        have |= {L["layerDigest"] for L in r.get("layers", []) if L.get("layerAvailability") == "AVAILABLE"}
    sent = 0
    for b in blobs:
        if b["digest"] in have:
            continue
        up = ecr.initiate_layer_upload(repositoryName=repo)
        uid = up["uploadId"]
        psize = min(part, int(up.get("partSize") or part))
        with open(b["path"], "rb") as fh:
            first = 0
            while True:
                chunk = fh.read(psize)
                if not chunk:
                    break
                ecr.upload_layer_part(repositoryName=repo, uploadId=uid, partFirstByte=first,
                                      partLastByte=first + len(chunk) - 1, layerPartBlob=chunk)
                first += len(chunk)
        ecr.complete_layer_upload(repositoryName=repo, uploadId=uid, layerDigests=[b["digest"]])
        sent += os.path.getsize(b["path"])
        log("blob pushed", digest=b["digest"][:19], mb=round(os.path.getsize(b["path"]) / 1e6, 1))
    try:
        r = ecr.put_image(repositoryName=repo, imageManifest=json.dumps(plan["manifest"]),
                          imageManifestMediaType=MT_MANIFEST, imageTag=tag)
        digest = r["image"]["imageId"]["imageDigest"]
    except ecr.exceptions.ImageAlreadyExistsException:
        digest = ecr.describe_images(repositoryName=repo, imageIds=[{"imageTag": tag}])["imageDetails"][0]["imageDigest"]
    return {"repo": repo, "tag": tag, "digest": digest, "pushedMb": round(sent / 1e6, 1)}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("cmd", choices=["build", "verify", "push"])
    p.add_argument("--out", default="/tmp/compute_broker/image")
    p.add_argument("--repo", default="story-compute/blender-lambda")
    p.add_argument("--tag", default=None)
    p.add_argument("--blender-tarball", default=None)
    a = p.parse_args(argv)
    if a.cmd == "build":
        plan = build(a.out, blender_tarball=a.blender_tarball)
        v = verify_rootfs(plan["rootfs"])
        print(json.dumps({"tag": plan["tag"], "mb": round(plan["bytes"] / 1e6, 1), "rpms": plan["rpms"],
                          "verify": v}, indent=1))
        return 0 if v["ok"] else 1
    with open(os.path.join(a.out, "image.json")) as fh:
        plan = json.load(fh)
    if a.cmd == "verify":
        v = verify_rootfs(plan["rootfs"])
        print(json.dumps(v, indent=1))
        return 0 if v["ok"] else 1
    import boto3
    print(json.dumps(push(plan, boto3.client("ecr", region_name="us-east-1"), a.repo, a.tag), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
