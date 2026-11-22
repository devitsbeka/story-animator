"""
handler.py - AWS Lambda entry point: render ONE chunk from a presigned chunk manifest, PUT every frame.

Event (sent by factory/compute/adapters/aws_lambda.py, InvocationType=Event):
    {"manifestUrl": "<presigned GET of the chunk manifest>", "chunk": "<chunk id>", "attempt": "<attempt id>"}

The manifest is the same document a credential-free GPU pod reads (cloud/farm/presigned.py:pod_manifest,
kind "story-farm-presigned-pod"): presigned GET URLs for code tarball / spec / library files (sha256 each) and
presigned PUT URLs for every plate, the job log + manifest, the heartbeat and the done marker. The function's
IAM role grants CloudWatch Logs only: it cannot read or write any bucket except through those URLs.

Standard library only (urllib). The render loop itself is cloud/farm/presigned_pod.py:Pod, imported from the code
tarball, so a code change never needs an image rebuild. Warm invocations reuse /tmp/code/<sha>/ and /tmp/library/.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request

TMP = os.environ.get("CHUNK_TMP", "/tmp")
BLENDER = os.environ.get("BLENDER", "/opt/blender/blender")
_COLD = True


def log(event, **kw):
    print(json.dumps({"t": round(time.time(), 1), "event": event, **kw}, default=str), flush=True)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


class TransferError(Exception):
    pass


class UrlNet:
    """The presigned_pod.Net interface (get / put_file / put_json, bytes_up/down) over urllib, with retries."""

    def __init__(self, retries=5, timeout=120):
        self.retries, self.timeout = retries, timeout
        self.lock = threading.Lock()
        self.bytes_up = self.bytes_down = 0

    @staticmethod
    def _safe(url):
        return url.split("?", 1)[0]

    def _do(self, req, sink=None):
        err = None
        for i in range(self.retries):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    if sink is None:
                        return r.read()
                    shutil.copyfileobj(r, sink, 1 << 20)
                    return None
            except urllib.error.HTTPError as e:
                err = f"HTTP {e.code}"
                if e.code in (400, 403, 404, 412):
                    break   # signature expired / object gone / precondition: retrying cannot help
            except (urllib.error.URLError, OSError) as e:
                err = str(e)
            time.sleep(min(2 ** i, 10))
        raise TransferError(f"{req.get_method()} {self._safe(req.full_url)}: {err}")

    def get(self, target, dst, sha256=None):
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".part-", dir=os.path.dirname(dst) or ".")
        try:
            with os.fdopen(fd, "wb") as fh:
                self._do(urllib.request.Request(target["url"], method="GET"), sink=fh)
            if sha256 and sha256_file(tmp) != sha256:
                raise TransferError(f"sha256 mismatch for {os.path.basename(dst)}")
            os.replace(tmp, dst)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        with self.lock:
            self.bytes_down += os.path.getsize(dst)
        return dst

    def get_bytes(self, url):
        return self._do(urllib.request.Request(url, method="GET"))

    def put_bytes(self, target, data):
        req = urllib.request.Request(target["url"], data=data, method="PUT",
                                     headers=dict(target.get("headers") or {}))
        self._do(req)
        with self.lock:
            self.bytes_up += len(data)

    def put_file(self, target, path):
        with open(path, "rb") as fh:
            self.put_bytes(target, fh.read())

    def put_json(self, target, obj):
        self.put_bytes(target, json.dumps(obj, indent=1, default=str).encode())


def fetch_code(net, code):
    """-> repo dir for this code sha (download + sha256 check + extract once per container)."""
    sha = code["sha256"]
    root = os.path.join(TMP, "code")
    repo = os.path.join(root, sha)
    if os.path.isfile(os.path.join(repo, ".ok")):
        return repo, False
    if os.path.isdir(root):
        for old in os.listdir(root):        # keep /tmp small: one code version per container
            shutil.rmtree(os.path.join(root, old), ignore_errors=True)
    tgz = os.path.join(root, f"{sha}.tar.gz")
    net.get(code, tgz, sha)
    os.makedirs(repo, exist_ok=True)
    with tarfile.open(tgz) as tf:
        tf.extractall(repo, filter="data")
    os.unlink(tgz)
    open(os.path.join(repo, ".ok"), "w").close()
    return repo, True


def load_pod_module(repo):
    path = os.path.join(repo, "cloud", "farm", "presigned_pod.py")
    spec = importlib.util.spec_from_file_location(f"presigned_pod_{abs(hash(repo))}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def handler(event, context=None, net=None, blender=BLENDER):
    global _COLD
    cold, _COLD = _COLD, False
    t0 = time.time()
    net = net or UrlNet()
    attempt = event.get("attempt") or "attempt"
    m = json.loads(net.get_bytes(event["manifestUrl"]))
    if m.get("kind") != "story-farm-presigned-pod":
        raise ValueError("not a presigned chunk manifest")
    m["exitWhenDone"] = True
    m["requireGpu"] = False
    repo, fresh_code = fetch_code(net, m["code"])
    mod = load_pod_module(repo)
    work = os.path.join(TMP, "work", attempt)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    pod_log = os.path.join(work, "pod.log")
    for d in ("BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_DATAFILES"):
        if os.environ.get(d):
            os.makedirs(os.environ[d], exist_ok=True)
    pod = mod.Pod(m, work, repo, blender, net=net, pod_log=pod_log)
    pod.library = os.path.join(TMP, "library")          # shared across warm invocations (sha256-checked)
    rc = pod.run()
    out = {"chunk": event.get("chunk"), "attempt": attempt, "rc": rc, "frames": len(pod.uploaded),
           "framesTotal": pod.frames_total, "seconds": round(time.time() - t0, 1), "coldStart": cold,
           "freshCode": fresh_code, "memoryMb": int(getattr(context, "memory_limit_in_mb", 0) or 0),
           "cpus": os.cpu_count(), "bytesDown": net.bytes_down, "bytesUp": net.bytes_up,
           "errors": pod.errors[-3:]}
    shutil.rmtree(work, ignore_errors=True)
    log("chunk_done", **out)
    return out
