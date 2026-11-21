"""
presigned.py - credential-free render farm: GPU pods (RunPod first, Vast.ai) that hold NO cloud credentials.

The operator machine (this one, AWS operator creds) does everything that needs AWS; a pod only ever sees ONE
environment variable, MANIFEST_URL: a presigned S3 GET of its pod manifest. The manifest holds presigned GET
URLs for every input (code tarball, episode spec, library files) and presigned PUT URLs for every output the pod
is expected to write (each plate PNG, per-job log + manifest, a heartbeat object it overwrites each minute, its
own log, a done marker). Presigned URLs live at most 7 days (SigV4 limit with IAM-user keys). No AWS keys, no
tokens, no SQS/DynamoDB in the pod.

    python3 cloud/farm/presigned.py plan   --spec episodes/sentinel/episode_v4.json --quality preview --workers 4
    python3 cloud/farm/presigned.py submit --spec ... --quality final --provider runpod --gpu RTX4090 --workers 4 \\
                                           --budget 40 [--frames 0-299] [--dry-run]
    python3 cloud/farm/presigned.py watch  --run RUN [--once] [--interval 60]
    python3 cloud/farm/presigned.py stop   --run RUN

Run it with the operator credentials (not the session's env keys), e.g.
    env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN python3 cloud/farm/presigned.py ...

S3 layout (bucket from the 'story-farm' stack outputs; every key under --root, default farm/presigned/):
  <root>code/<sha256>.tar.gz                    code tarball (git archive of HEAD + spec + referenced assets)
  library_store/<rel>                           library files (reused when `orchestrator.py sync-library` uploaded
                                                them; missing ones are uploaded there, or under --library-prefix)
  <root>runs/<run>/inputs/episode.json          spec snapshot
  <root>runs/<run>/state.json                   orchestrator state (pods, assignments, spend)
  <root>runs/<run>/pods/<pod>/manifest.json     pod manifest (the only thing MANIFEST_URL points at)
  <root>runs/<run>/pods/<pod>/heartbeat.json    PUT by the pod every minute
  <root>runs/<run>/pods/<pod>/done.json         PUT by the pod when all its jobs ended (status DONE|PARTIAL|FAILED)
  <root>runs/<run>/pods/<pod>/pod.log           startup + runner log
  <root>runs/<run>/pods/<pod>/jobs/<job>.json   per-job manifest (files, sha256, device, seconds/frame)
  <root>runs/<run>/pods/<pod>/logs/<job>.log    Blender log per job
  <root>plates/<run>/<shot>/<frame:04d>.png     plates (PUT one by one, as soon as Blender writes each)

watch: polls S3 (heartbeats, done markers, plates) + the provider list; terminates pods that are done, idle or
dead (no heartbeat within boot_timeout_s of launch, or silent for heartbeat_lost_s, or the provider reports them
gone); re-assigns the frames a dead/failed pod did not deliver to a NEW pod with a fresh manifest; enforces the
budget ($/h of live pods and total spend); pulls the plates into episodes/<id>/plates/ when every frame exists.
"""
import argparse
import ast
import copy
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import jobs as jobsplit  # noqa: E402
import providers as prov  # noqa: E402
from providers.startup import BLENDER, bootstrap_command  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
STARTUP = os.path.join(HERE, "providers", "presigned_startup.sh")
DEFAULT_ROOT = "farm/presigned/"
DEFAULT_LIBRARY_PREFIX = "library_store/"
LIBRARY_PREFIXES = ("library_store/", "library/")   # where `orchestrator.py sync-library` (and older runs) put it
MAX_EXPIRY_S = 7 * 24 * 3600
CODE_PATHS = ["cloud", "factory", "studio/src/data", "assets"]   # `assets` is the repo symlink to studio/public/assets
SKIP_PARTS = ("node_modules", "__pycache__", ".pytest_cache")
NON_VISUAL_KINDS = {"music", "sfx", "voice", "audio", "ambience"}
TERMINAL = ("COMPLETE", "STOPPED", "FAILED", "BUDGET_EXCEEDED")
GPU_PROVIDERS = ("runpod", "vastai")
DEFAULTS = {"heartbeat_s": 60, "boot_timeout_s": 1800, "heartbeat_lost_s": 600, "max_replacements": 3,
            "job_attempts": 2, "max_usd_per_hour": 4.0}


def log(msg, **kw):
    print(json.dumps({"t": round(time.time(), 1), "msg": msg, **kw}, default=str), file=sys.stderr, flush=True)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def redact_url(url):
    """Drop the query string (the presigned signature) from a URL."""
    u = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "REDACTED" if u.query else "", ""))


# ----------------------------------------------------------------------------------------------- keys
class Layout:
    def __init__(self, root=DEFAULT_ROOT, library_prefix=DEFAULT_LIBRARY_PREFIX):
        self.root = root.rstrip("/") + "/"
        self.library_prefix = library_prefix.rstrip("/") + "/"

    def code(self, sha):
        return f"{self.root}code/{sha}.tar.gz"

    def run(self, run):
        return f"{self.root}runs/{run}/"

    def spec(self, run):
        return self.run(run) + "inputs/episode.json"

    def state(self, run):
        return self.run(run) + "state.json"

    def plates_prefix(self, run):
        return f"{self.root}plates/{run}/"

    def plate(self, run, shot, frame):
        return f"{self.plates_prefix(run)}{shot}/{int(frame):04d}.png"

    def pod(self, run, pod):
        return self.run(run) + f"pods/{pod}/"

    def manifest(self, run, pod):
        return self.pod(run, pod) + "manifest.json"

    def heartbeat(self, run, pod):
        return self.pod(run, pod) + "heartbeat.json"

    def done(self, run, pod):
        return self.pod(run, pod) + "done.json"

    def pod_log(self, run, pod):
        return self.pod(run, pod) + "pod.log"

    def job_manifest(self, run, pod, job):
        return self.pod(run, pod) + f"jobs/{job}.json"

    def job_log(self, run, pod, job):
        return self.pod(run, pod) + f"logs/{job}.log"

    def library(self, rel):
        return self.library_prefix + rel


# ----------------------------------------------------------------------------------------------- S3 helpers
def s3_client(region="us-east-1", profile=None):
    import boto3
    from botocore.config import Config
    sess = boto3.session.Session(region_name=region, profile_name=profile) if profile else \
        boto3.session.Session(region_name=region)
    cfg = Config(signature_version="s3v4", s3={"addressing_style": "virtual"},
                 retries={"max_attempts": 8, "mode": "adaptive"})
    return sess.client("s3", config=cfg), sess


def s3_list(s3, bucket, prefix):
    """-> {key: (size, last_modified_epoch)}"""
    out = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []) or []:
            out[o["Key"]] = (o["Size"], o["LastModified"].timestamp())
    return out


def s3_get_json(s3, bucket, key):
    """-> (obj, last_modified_epoch) or (None, None)."""
    from botocore.exceptions import ClientError
    try:
        r = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(r["Body"].read() or b"null"), r["LastModified"].timestamp()
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return None, None
        raise
    except ValueError:
        return {"unparseable": True}, None


def s3_put_json(s3, bucket, key, obj):
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(obj, indent=1, default=str).encode(),
                  ContentType="application/json")


def presign(s3, method, bucket, key, expires, content_type=None):
    """-> {"url", "method", "headers"}: what the pod sends with curl (headers that are part of the signature)."""
    expires = int(min(max(60, expires), MAX_EXPIRY_S))
    params = {"Bucket": bucket, "Key": key}
    headers = {}
    if method == "PUT":
        if content_type:
            params["ContentType"] = content_type
            headers["Content-Type"] = content_type
        url = s3.generate_presigned_url("put_object", Params=params, ExpiresIn=expires, HttpMethod="PUT")
    else:
        url = s3.generate_presigned_url("get_object", Params=params, ExpiresIn=expires, HttpMethod="GET")
    return {"url": url, "method": method, "headers": headers}


def stack_bucket(sess, stack):
    cfn = sess.client("cloudformation")
    outs = cfn.describe_stacks(StackName=stack)["Stacks"][0].get("Outputs", [])
    return {o["OutputKey"]: o["OutputValue"] for o in outs}["BucketName"]


# ----------------------------------------------------------------------------------------------- inputs: code
def asset_keys(spec):
    """Repo-relative 'assets/...' keys under spec['assets'] (same rule as orchestrator.asset_keys)."""
    keys = []

    def walk(v):
        if isinstance(v, str):
            if v.startswith("assets/") and ".." not in v.split("/"):
                keys.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(spec.get("assets") or {})
    return sorted(set(keys))


def _skip(name):
    return any(p in name.split("/") for p in SKIP_PARTS)


def _tarinfo(name, size=0, mode=0o644, kind=tarfile.REGTYPE, linkname=""):
    ti = tarfile.TarInfo(name)
    ti.size, ti.mode, ti.mtime, ti.type, ti.linkname = size, mode, 0, kind, linkname
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    return ti


def code_tarball(repo, spec_rel, spec_bytes, spec, mode="head", paths=CODE_PATHS):
    """-> (tar.gz bytes, sha256, member names). Deterministic for the same inputs.

    mode "head": `git archive HEAD` of `paths` (what is committed; the default for real runs);
    mode "worktree": tracked + untracked-not-ignored files of `paths` as they are on disk (dev/tests).
    Then the spec (at spec_rel) and every asset the spec references (from disk, often not in git) are added."""
    members = {}  # name -> (TarInfo, bytes|None)
    if mode == "head":
        have = [p for p in paths if subprocess.run(["git", "-C", repo, "cat-file", "-e", f"HEAD:{p}"],
                                                   capture_output=True).returncode == 0]
        raw = subprocess.run(["git", "-C", repo, "archive", "--format=tar", "HEAD", *have], capture_output=True,
                             check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tf:
            for m in tf.getmembers():
                if _skip(m.name) or m.isdir():
                    continue
                if m.issym():
                    members[m.name] = (_tarinfo(m.name, kind=tarfile.SYMTYPE, linkname=m.linkname, mode=0o777), None)
                elif m.isfile():
                    data = tf.extractfile(m).read()
                    members[m.name] = (_tarinfo(m.name, len(data), 0o755 if m.mode & 0o111 else 0o644), data)
    elif mode == "worktree":
        names = subprocess.run(["git", "-C", repo, "ls-files", "-co", "--exclude-standard", "-z", "--", *paths],
                               capture_output=True, check=True).stdout.decode().split("\0")
        for n in sorted(x for x in names if x):
            p = os.path.join(repo, n)
            if _skip(n) or not os.path.lexists(p):
                continue
            if os.path.islink(p):
                members[n] = (_tarinfo(n, kind=tarfile.SYMTYPE, linkname=os.readlink(p), mode=0o777), None)
            elif os.path.isfile(p):
                with open(p, "rb") as fh:
                    data = fh.read()
                members[n] = (_tarinfo(n, len(data), 0o755 if os.access(p, os.X_OK) else 0o644), data)
    else:
        raise ValueError(f"code mode must be head or worktree, not {mode!r}")
    members[spec_rel] = (_tarinfo(spec_rel, len(spec_bytes)), spec_bytes)
    for key in asset_keys(spec):
        p = os.path.join(repo, key)
        if not os.path.isfile(p):
            log("asset missing locally (renderer will warn)", key=key)
            continue
        real = os.path.relpath(os.path.realpath(p), os.path.realpath(repo))
        name = real if not real.startswith("..") else key
        if name in members:
            continue
        with open(p, "rb") as fh:
            data = fh.read()
        members[name] = (_tarinfo(name, len(data)), data)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=6) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tf:
            for name in sorted(members):
                ti, data = members[name]
                tf.addfile(ti, io.BytesIO(data) if data is not None else None)
    out = buf.getvalue()
    return out, sha256_bytes(out), sorted(members)


# ----------------------------------------------------------------------------------------------- inputs: library
def _strings(obj, acc=None):
    acc = set() if acc is None else acc
    if isinstance(obj, str):
        acc.add(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(str(k))
            _strings(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _strings(v, acc)
    return acc


def renderer_literals(src_dirs):
    """String literals in the renderer's Python sources -> (plain strings, path regexes).

    f-strings and str.format templates become regexes ('{...}' -> one path segment), so
    f"polyhaven/island_tree_0{i}/island_tree_0{i}_1k.gltf" matches the three island trees."""
    plain, pats = set(), set()
    fmt = re.compile(r"\{[^{}]*\}")
    for d in src_dirs:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".py"):
                continue
            try:
                tree = ast.parse(open(os.path.join(d, fn)).read())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 300:
                    s = node.value
                    plain.add(s)
                    if "/" in s and fmt.search(s):
                        pats.add("".join(re.escape(x) if i % 2 == 0 else "[^/]*"
                                         for i, x in enumerate(_interleave(fmt, s))))
                elif isinstance(node, ast.JoinedStr):
                    parts = []
                    for v in node.values:
                        parts.append(re.escape(v.value) if isinstance(v, ast.Constant) else "[^/]*")
                    rx = "".join(parts)
                    if "/" in rx:
                        pats.add(rx)
    return plain, [re.compile(p) for p in sorted(pats) if _specific(p)]


def _specific(rx):
    """Keep a path pattern only if its asset-directory segment has >= 3 literal characters: f"polyhaven/{n}/..."
    would match the whole library (those names show up as plain constants and are matched by source id)."""
    segs = rx.split("/")
    seg = segs[1] if len(segs) > 2 else segs[-1]
    return len(re.sub(r"\[\^/\]\*|\\", "", seg)) >= 3


def _interleave(fmt, s):
    """'a{}b{x}c' -> ['a', '{}', 'b', '{x}', 'c'] (literal / placeholder alternating)."""
    out, pos = [], 0
    for m in fmt.finditer(s):
        out += [s[pos:m.start()], m.group(0)]
        pos = m.end()
    return out + [s[pos:]]


def spec_kits(spec, repo):
    ids = set()
    refs = [(spec.get("world") or {}).get("set")] + [s.get("set") for s in spec.get("shots", [])]
    for r in refs:
        if isinstance(r, str):
            ids.add(r)
        elif isinstance(r, dict) and r.get("kit"):
            ids.add(r["kit"])
    kits = []
    for k in sorted(ids):
        p = os.path.join(repo, "factory", "worlds", "kits", f"{k}.json")
        if os.path.isfile(p):
            with open(p) as fh:
                kits.append(json.load(fh))
    return kits


def select_library(spec, catalog, repo=REPO, store=None, include_renderer=True):
    """Library files (paths relative to library_store/) a render of `spec` may read.

    -> {rel: {"asset", "why", "sha256"}}. An asset is selected when its catalog id or one of its file paths
    appears in the spec or in a world kit the spec uses ('spec'), or in the renderer's own sources ('renderer':
    HDRIs, deck texture, island trees). Audio kinds are never selected. Files under library_store/lod/<asset dir>
    (scatter LOD caches) ride along when they exist locally. Over-selection is safe; under-selection only makes
    the renderer warn and fall back."""
    store = store or os.path.join(repo, "library_store")
    strs = _strings(spec)
    for kit in spec_kits(spec, repo):
        strs |= _strings(kit)
    strs |= {s[len("library_store/"):] for s in list(strs) if s.startswith("library_store/")}
    strs |= {s[4:] for s in list(strs) if s.startswith("lib:")}
    plain, pats = renderer_literals([os.path.join(repo, "cloud", "blender")]) if include_renderer else (set(), [])
    chosen = {}
    assets = (catalog or {}).get("assets") or {}
    for cid, e in sorted(assets.items()):
        if e.get("kind") in NON_VISUAL_KINDS:
            continue
        files = [f for f in e.get("files") or [] if f.get("path")]
        paths = [f["path"] for f in files]
        why = None
        if cid in strs or any(p in strs for p in paths):
            why = "spec"
        elif include_renderer and (cid in plain or any(p in plain for p in paths)
                                   or (len(e.get("source_id") or "") >= 6 and e.get("source_id") in plain)
                                   or any(rx.fullmatch(p) for rx in pats for p in paths)):
            why = "renderer"
        if not why:
            continue
        for f in files:
            chosen[f["path"]] = {"asset": cid, "why": why, "sha256": f.get("sha256")}
        for d in sorted({p.split("/")[1] for p in paths if p.count("/") >= 2}):
            lod = os.path.join(store, "lod", d)
            if os.path.isdir(lod):
                for dp, _, fns in os.walk(lod):
                    for fn in sorted(fns):
                        rel = os.path.relpath(os.path.join(dp, fn), store).replace(os.sep, "/")
                        chosen.setdefault(rel, {"asset": cid, "why": why + ":lod", "sha256": None})
    # explicit library_store/ paths in the spec that the catalog does not list (e.g. characters/jay.blend)
    for s in sorted(strs):
        if "/" in s and not s.startswith(("assets/", "/", "episodes/")) and ".." not in s.split("/") \
                and os.path.isfile(os.path.join(store, s)):
            chosen.setdefault(s, {"asset": None, "why": "spec:path", "sha256": None})
    return chosen


# ----------------------------------------------------------------------------------------------- planning
def parse_frames(s):
    if not s:
        return None
    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", s)
    if not m:
        raise ValueError(f"--frames must look like A-B, not {s!r}")
    a, b = int(m.group(1)), int(m.group(2))
    if a > b:
        raise ValueError("--frames A-B needs A <= B")
    return a, b


def assign(jobs, n):
    """LPT: longest jobs first onto the least-loaded pod. -> list of non-empty job lists (<= n)."""
    n = max(1, min(int(n), len(jobs) or 1))
    bins = [[0.0, i, []] for i in range(n)]
    for j in jobsplit.lpt_order(jobs):
        b = min(bins, key=lambda x: (x[0], x[1]))
        b[0] += float(j["estSeconds"])
        b[2].append(j)
    out = [sorted(b[2], key=lambda j: (j["frameStart"], j["shot"])) for b in bins if b[2]]
    return out


def job_frames(job):
    return [(job["shot"], f) for f in range(job["frameStart"], job["frameEnd"] + 1)]


def missing_jobs(jobs, have, suffix):
    """Sub-jobs (contiguous runs) of `jobs` whose frames are not in `have` {(shot, frame)}; ids get `suffix`."""
    out = []
    for j in jobs:
        run = []
        for f in range(j["frameStart"], j["frameEnd"] + 1):
            if (j["shot"], f) not in have:
                run.append(f)
        groups, cur = [], []
        for f in run:
            if cur and f != cur[-1] + 1:
                groups.append(cur)
                cur = []
            cur.append(f)
        if cur:
            groups.append(cur)
        for g in groups:
            nj = dict(j)
            nj["frameStart"], nj["frameEnd"], nj["frames"] = g[0], g[-1], len(g)
            spf = float(j.get("estSecondsPerFrame") or 0)
            nj["estSeconds"] = round(jobsplit.JOB_OVERHEAD_S + jobsplit.PRESETS[j["quality"]]["build_s"]
                                     + len(g) * spf, 1)
            nj["jobId"] = f"{j['episodeId']}-{j['shot']}-f{g[0]:05d}-{g[-1]:05d}-{j['quality']}-{suffix}"
            out.append(nj)
    return out


# ----------------------------------------------------------------------------------------------- pod manifest
def pod_manifest(s3, bucket, layout, run, pod, jobs, inputs, opts, now=None):
    """The JSON a pod reads (and the only thing it can reach without asking): presigned URLs, nothing else."""
    now = now or time.time()
    exp = int(min(opts.get("expires_s", MAX_EXPIRY_S), MAX_EXPIRY_S))

    def get(key):
        return presign(s3, "GET", bucket, key, exp)

    def put(key, ctype):
        return presign(s3, "PUT", bucket, key, exp, ctype)

    mjobs = []
    for j in jobs:
        mjobs.append({
            "jobId": j["jobId"], "shot": j["shot"], "frameStart": j["frameStart"], "frameEnd": j["frameEnd"],
            "quality": j["quality"], "engine": j["engine"], "res": j.get("res"), "samples": j.get("samples"),
            "estSeconds": j.get("estSeconds"), "extraArgs": list(opts.get("extra_args") or []),
            "plates": {str(f): put(layout.plate(run, j["shot"], f), "image/png")
                       for f in range(j["frameStart"], j["frameEnd"] + 1)},
            "log": put(layout.job_log(run, pod, j["jobId"]), "text/plain"),
            "manifest": put(layout.job_manifest(run, pod, j["jobId"]), "application/json"),
        })
    return {
        "v": 1, "kind": "story-farm-presigned-pod", "runId": run, "pod": pod, "episodeId": inputs["episodeId"],
        "createdAt": int(now), "expiresAt": int(now + exp),
        "requireGpu": bool(opts.get("require_gpu", True)), "gpuClass": opts.get("gpu"),
        "heartbeatS": int(opts.get("heartbeat_s", DEFAULTS["heartbeat_s"])),
        "jobAttempts": int(opts.get("job_attempts", DEFAULTS["job_attempts"])),
        "threads": int(opts.get("threads", 0)), "exitWhenDone": bool(opts.get("exit_when_done", False)),
        "blender": {"version": BLENDER["BLENDER_VERSION"], "sha256": BLENDER["BLENDER_SHA256"],
                    "url": (f"https://download.blender.org/release/Blender{BLENDER['BLENDER_SERIES']}/"
                            f"blender-{BLENDER['BLENDER_VERSION']}-linux-x64.tar.xz")},
        "code": {**get(inputs["code"]["key"]), "sha256": inputs["code"]["sha256"], "size": inputs["code"]["size"]},
        "spec": {**get(inputs["spec"]["key"]), "sha256": inputs["spec"]["sha256"], "path": inputs["spec"]["path"]},
        "library": [{**get(f["key"]), "path": f["path"], "sha256": f.get("sha256"), "size": f.get("size")}
                    for f in inputs.get("library", [])],
        "jobs": mjobs,
        "heartbeat": put(layout.heartbeat(run, pod), "application/json"),
        "done": put(layout.done(run, pod), "application/json"),
        "podLog": put(layout.pod_log(run, pod), "text/plain"),
    }


# ----------------------------------------------------------------------------------------------- providers
def provider_cfg(name, providers_yaml=None):
    path = providers_yaml or os.path.join(HERE, "providers.yaml")
    try:
        import yaml
        with open(path) as fh:
            cfg = (yaml.safe_load(fh) or {}).get("providers", {}).get(name, {}) or {}
    except (ImportError, OSError):
        cfg = {}
    cfg = dict(cfg)
    if name == "runpod":
        cfg["cloud"] = "SECURE"          # presigned pods: Runpod-owned hardware only
        cfg.setdefault("disk_gb", 40)    # Blender (~1 GB unpacked) + library subset + plates
        cfg.setdefault("image", "nvidia/cuda:12.4.1-base-ubuntu22.04")
    return cfg


def provider_env(name):
    env = dict(os.environ)
    if name == "runpod" and not env.get("RUNPOD_API_KEY"):
        env["RUNPOD_API_KEY"] = "proxy-injected"   # the network proxy injects the real key for api.runpod.io
    if name == "vastai" and not env.get("VAST_API_KEY"):
        env["VAST_API_KEY"] = "proxy-injected"
    return env


def pod_env_and_startup(provider_name, manifest_url, startup_path=STARTUP):
    """-> (container env, bootstrap command). The env carries MANIFEST_URL only (+ the NVIDIA capability flag the
    container runtime reads at create time so OptiX's libnvoptix gets mounted; not a secret)."""
    with open(startup_path) as fh:
        script = fh.read()
    env = {"MANIFEST_URL": manifest_url, "NVIDIA_DRIVER_CAPABILITIES": "compute,utility,graphics"}
    if provider_name == "vastai":
        # Vast's env field is a docker-flag string that rejects '&'/'%': ship the URL inside the (base64) script
        shebang, rest = script.split("\n", 1)
        script = f"{shebang}\nexport MANIFEST_URL='{manifest_url}'\n{rest}"
        env = {"NVIDIA_DRIVER_CAPABILITIES": "compute,utility,graphics"}
    return env, bootstrap_command(script, path="/tmp/presigned-startup.sh")


def make_provider(name, cfg, env=None, transport=None):
    kw = {"transport": transport} if transport else {}
    return prov.make(name, cfg, env if env is not None else provider_env(name), **kw)


def create_payload(name, cfg, gpu, env, startup):
    """The exact create body the provider would send for one pod (dry run / review)."""
    p = make_provider(name, cfg, env={"RUNPOD_API_KEY": "x", "VAST_API_KEY": "x"})
    if name == "runpod":
        return {"method": "POST", "url": f"{p.http.base}/v2/pods",
                "body": p.pod_payload(0, gpu, "SECURE", env, startup)}
    if name == "vastai":
        return {"method": "PUT", "url": f"{p.http.base}/api/v0/asks/<offer id>",
                "body": p.create_payload(0, gpu, env, startup)}
    raise ValueError(f"presigned mode supports {GPU_PROVIDERS}, not {name!r}")


def redact_payload(payload):
    out = copy.deepcopy(payload)
    body = out.get("body", {})
    env = body.get("env")
    if isinstance(env, dict) and env.get("MANIFEST_URL"):
        env["MANIFEST_URL"] = redact_url(env["MANIFEST_URL"])
    elif isinstance(env, str):
        body["env"] = re.sub(r"(https://[^?\s']+)\?[^\s']*", r"\1?REDACTED", env)
    return out


# ----------------------------------------------------------------------------------------------- the farm
class PresignedFarm:
    """One run. All AWS calls use the operator's client `s3`; pods only get presigned URLs."""

    def __init__(self, s3, bucket, layout=None, provider_name="runpod", provider=None, provider_config=None,
                 repo=REPO, state_dir=None, clock=time.time, transport=None):
        self.s3, self.bucket = s3, bucket
        self.layout = layout or Layout()
        self.provider_name = provider_name
        self.cfg = provider_config if provider_config is not None else provider_cfg(provider_name)
        self.transport = transport
        self.provider = provider
        self.repo = repo
        self.state_dir = state_dir or os.path.expanduser(os.environ.get("FARM_STATE_DIR", "~/.story-farm/presigned"))
        self.clock = clock

    # --- provider plumbing (one provider object per pod so the pod's name carries its id)
    def _prov(self, pod=None):
        if self.provider is not None and pod is None:
            return self.provider
        cfg = dict(self.cfg)
        if pod:
            cfg["name"] = pod
        if self.provider is not None and hasattr(self.provider, "for_pod"):
            return self.provider.for_pod(pod)
        return make_provider(self.provider_name, cfg, transport=self.transport)

    # --- inputs
    def prepare_inputs(self, spec_path, spec, run, code_mode="head", library="auto", extra_library=(),
                       upload=True):
        """Upload (or reuse) code tarball, spec snapshot and library files. -> inputs dict (keys + sha256)."""
        with open(spec_path, "rb") as fh:
            spec_bytes = fh.read()
        spec_rel = os.path.relpath(os.path.abspath(spec_path), self.repo).replace(os.sep, "/")
        if spec_rel.startswith(".."):
            spec_rel = f"episodes/{spec['id']}/{os.path.basename(spec_path)}"
        data, sha, members = code_tarball(self.repo, spec_rel, spec_bytes, spec, mode=code_mode)
        code_key = self.layout.code(sha)
        lib_root = os.environ.get("LIBRARY_STORE") or os.path.join(self.repo, "library_store")
        if library == "none":
            chosen = {}
        else:
            cat_path = os.path.join(self.repo, "factory", "library", "catalog.json")
            with open(cat_path) as fh:
                catalog = json.load(fh)
            chosen = select_library(spec, catalog, self.repo, lib_root, include_renderer=(library == "auto"))
        for rel in extra_library:
            chosen.setdefault(rel, {"asset": None, "why": "extra", "sha256": None})
        remote = {}
        for pre in dict.fromkeys((self.layout.library_prefix, *LIBRARY_PREFIXES)):
            try:
                for k, (size, _) in s3_list(self.s3, self.bucket, pre).items():
                    remote.setdefault(k[len(pre):], (k, size))
            except Exception as e:  # noqa: BLE001 - dry run without network: plan uploads for everything
                log("library listing failed", prefix=pre, error=str(e)[:200])
        lib, uploaded, reused, missing = [], 0, 0, []
        for rel in sorted(chosen):
            local = os.path.join(lib_root, rel)
            have_local = os.path.isfile(local)
            size = os.path.getsize(local) if have_local else None
            r = remote.get(rel)
            if r and (size is None or r[1] == size):
                key, size = r[0], r[1]
                reused += 1
            elif have_local:
                key = self.layout.library(rel)
                if upload:
                    self.s3.upload_file(local, self.bucket, key)
                uploaded += 1
            else:
                missing.append(rel)
                continue
            fsha = chosen[rel].get("sha256") or (sha256_file(local) if have_local else None)
            lib.append({"path": rel, "key": key, "sha256": fsha, "size": size, "asset": chosen[rel]["asset"],
                        "why": chosen[rel]["why"]})
        spec_key = self.layout.spec(run)
        if upload:
            if code_key not in s3_list(self.s3, self.bucket, code_key):
                self.s3.put_object(Bucket=self.bucket, Key=code_key, Body=data, ContentType="application/gzip")
            self.s3.put_object(Bucket=self.bucket, Key=spec_key, Body=spec_bytes, ContentType="application/json")
        return {"episodeId": spec["id"],
                "code": {"key": code_key, "sha256": sha, "size": len(data), "members": len(members),
                         "mode": code_mode},
                "spec": {"key": spec_key, "sha256": sha256_bytes(spec_bytes), "path": spec_rel},
                "library": lib,
                "librarySummary": {"files": len(lib), "bytes": sum(f["size"] or 0 for f in lib), "reused": reused,
                                   "uploaded": uploaded, "missing": missing[:50]}}

    # --- state
    def state_path(self, run):
        return os.path.join(self.state_dir, f"{run}.json")

    def save(self, st):
        st["updatedAt"] = int(self.clock())
        os.makedirs(self.state_dir, exist_ok=True)
        tmp = self.state_path(st["runId"]) + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(st, fh, indent=1, default=str)
        os.replace(tmp, self.state_path(st["runId"]))
        s3_put_json(self.s3, self.bucket, self.layout.state(st["runId"]), st)

    def load(self, run):
        obj, _ = s3_get_json(self.s3, self.bucket, self.layout.state(run))
        if obj:
            return obj
        p = self.state_path(run)
        if os.path.isfile(p):
            with open(p) as fh:
                return json.load(fh)
        raise SystemExit(f"no state for run {run} (s3://{self.bucket}/{self.layout.state(run)} or {p})")

    # --- plan / submit
    @staticmethod
    def plan(spec, quality, workers, frames=None, engine=None, res=None, samples=None, price=0.69,
             target_job_s=jobsplit.DEFAULT_TARGET_JOB_S):
        js = jobsplit.split_episode(spec, quality, engine, target_job_s, frame_range=frames, res=res, samples=samples)
        if not js:
            raise SystemExit("no frames selected")
        jobsplit.check_coverage(spec, js)
        pods = assign(js, workers)
        est = jobsplit.estimate(js, price, len(pods))
        return js, pods, est

    def submit(self, spec_path, quality="preview", workers=1, budget=None, gpu="RTX4090", frames=None,
               engine=None, res=None, samples=None, run_id=None, dry_run=False, code_mode="head", library="auto",
               extra_library=(), opts=None, price=None, max_usd_per_hour=None):
        opts = {**DEFAULTS, **(opts or {})}
        with open(spec_path) as fh:
            spec = json.load(fh)
        if price is None:
            try:
                price = self._prov().price_per_hour(gpu) if not dry_run else None
            except Exception as e:  # noqa: BLE001
                log("price lookup failed; using list price", error=str(e)[:200])
            if price is None:
                price = float(prov.make(self.provider_name, self.cfg, {}).default_prices.get(gpu, 0.69)) \
                    if self.provider_name in GPU_PROVIDERS else 0.0
        js, groups, est = self.plan(spec, quality, workers, frames, engine, res, samples, price)
        rate_cap = float(max_usd_per_hour if max_usd_per_hour is not None else
                         self.cfg.get("max_usd_per_hour", opts["max_usd_per_hour"]))
        if price * len(groups) > rate_cap:
            raise SystemExit(f"refused: {len(groups)} pods x ${price:.2f}/h = ${price * len(groups):.2f}/h > "
                             f"${rate_cap:.2f}/h ceiling (lower --workers or raise --max-usd-per-hour)")
        if budget is not None and est["usd"] > budget:
            raise SystemExit(f"refused: estimate ${est['usd']:.2f} > budget ${budget:.2f}")
        run = run_id or f"{spec['id']}-{quality}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime(self.clock()))}"
        inputs = self.prepare_inputs(spec_path, spec, run, code_mode, library, extra_library, upload=not dry_run)
        st = {"v": 1, "runId": run, "episodeId": spec["id"], "status": "SUBMITTING", "quality": quality,
              "provider": self.provider_name, "gpu": gpu, "usdPerHour": price, "budgetUsd": budget,
              "maxUsdPerHour": rate_cap, "estimate": est, "bucket": self.bucket, "root": self.layout.root,
              "inputs": inputs, "opts": {**opts, "gpu": gpu}, "jobs": js,
              "frames": sum(j["frames"] for j in js), "pods": [], "spentUsd": 0.0, "createdAt": int(self.clock()),
              "events": []}
        launched = []
        for i, group in enumerate(groups):
            pod = self._new_pod(st, group, f"p{i}", dry_run=dry_run)
            launched.append(pod)
        if dry_run:
            return {"dryRun": True, "runId": run, "estimate": est, "usdPerHour": price,
                    "inputs": {k: v for k, v in inputs.items() if k != "library"},
                    "library": [{k: f[k] for k in ("path", "key", "size", "why")} for f in inputs["library"]][:400],
                    "pods": [{"pod": p["pod"], "jobs": p["jobs"], "frames": p["frames"], "manifestKey": p["manifestKey"],
                              "manifestUrls": p["urls"], "createRequest": p["payload"]} for p in launched]}
        st["status"] = "RUNNING"
        self.save(st)
        return self.summary(st)

    def _new_pod(self, st, jobs, tag, dry_run=False):
        run = st["runId"]
        pod = f"{run}-{tag}"
        man = pod_manifest(self.s3, self.bucket, self.layout, run, pod, jobs, st["inputs"], st["opts"],
                           now=self.clock())
        mkey = self.layout.manifest(run, pod)
        murl = presign(self.s3, "GET", self.bucket, mkey, st["opts"].get("expires_s", MAX_EXPIRY_S))["url"]
        env, startup = pod_env_and_startup(self.provider_name, murl)
        rec = {"pod": pod, "tag": tag, "jobs": [j["jobId"] for j in jobs], "jobSpecs": jobs,
               "frames": sum(j["frames"] for j in jobs), "manifestKey": mkey, "status": "PLANNED",
               "launchedAt": None, "endedAt": None, "providerId": None, "price": st["usdPerHour"]}
        if dry_run:
            rec["payload"] = redact_payload(create_payload(self.provider_name, self.cfg, st["gpu"], env, startup))
            rec["urls"] = {"total": sum(len(j["plates"]) + 2 for j in man["jobs"]) + 4 + len(man["library"]),
                           "expiresAt": man["expiresAt"]}
            return rec
        s3_put_json(self.s3, self.bucket, mkey, man)
        try:
            handles = self._prov(pod).launch(1, st["gpu"], env, startup)
            h = handles[0]
            rec.update(status="LAUNCHED", providerId=h.id, launchedAt=int(self.clock()),
                       price=float(h.price_per_hour or st["usdPerHour"]))
            self._event(st, "launched", pod=pod, providerId=h.id, frames=rec["frames"])
        except prov.ProviderError as e:
            rec.update(status="LAUNCH_FAILED", error=f"{type(e).__name__}: {e}"[:500], endedAt=int(self.clock()))
            self._event(st, "launch_failed", pod=pod, error=rec["error"])
        st["pods"].append(rec)
        return rec

    def _event(self, st, what, **kw):
        st.setdefault("events", []).append({"t": int(self.clock()), "event": what, **kw})
        st["events"] = st["events"][-200:]
        log(what, run=st["runId"], **kw)

    # --- watch
    def have_plates(self, st):
        pre = self.layout.plates_prefix(st["runId"])
        have = set()
        for k, (size, _) in s3_list(self.s3, self.bucket, pre).items():
            m = re.fullmatch(r"([^/]+)/(\d+)\.png", k[len(pre):])
            if m and size > 0:
                have.add((m.group(1), int(m.group(2))))
        return have

    def spend(self, st, now):
        total, rate = 0.0, 0.0
        for p in st["pods"]:
            if not p.get("launchedAt"):
                continue
            end = p.get("endedAt") or now
            total += max(0.0, end - p["launchedAt"]) / 3600.0 * float(p.get("price") or 0)
            if not p.get("endedAt"):
                rate += float(p.get("price") or 0)
        return round(total, 4), round(rate, 4)

    def _terminate(self, st, recs, reason):
        ids = [p["providerId"] for p in recs if p.get("providerId") and not p.get("endedAt")]
        done = set()
        if ids:
            try:
                done = set(self._prov().terminate(ids))
            except prov.ProviderError as e:
                self._event(st, "terminate_failed", ids=ids, error=str(e)[:300])
        now = int(self.clock())
        for p in recs:
            if p.get("endedAt"):
                continue
            if not p.get("providerId") or p["providerId"] in done:
                p["endedAt"] = now
                p["endReason"] = reason
                self._event(st, "terminated", pod=p["pod"], providerId=p.get("providerId"), reason=reason)

    def tick(self, st):
        """One watch step. Mutates and saves `st`; returns its status."""
        if st["status"] in TERMINAL:
            return st["status"]
        now = self.clock()
        opts = {**DEFAULTS, **st.get("opts", {})}
        have = self.have_plates(st)
        want = {fr for j in st["jobs"] for fr in job_frames(j)}
        try:
            listed = {h.id: h for h in self._prov().list()}
            list_ok = True
        except prov.ProviderError as e:
            listed, list_ok = {}, False
            self._event(st, "provider_list_failed", error=str(e)[:200])
        reassign = []
        for p in st["pods"]:
            if p.get("endedAt"):
                if p["status"] == "LAUNCH_FAILED" and not p.get("reassigned"):
                    p["reassigned"] = True
                    reassign.append(p)
                continue
            run, pod = st["runId"], p["pod"]
            hb, hb_t = s3_get_json(self.s3, self.bucket, self.layout.heartbeat(run, pod))
            done, _ = s3_get_json(self.s3, self.bucket, self.layout.done(run, pod))
            p["heartbeat"] = {k: hb.get(k) for k in ("state", "job", "framesDone", "framesTotal", "device", "t")} \
                if isinstance(hb, dict) else None
            p["lastHeartbeat"] = hb_t
            pod_frames = {fr for j in p["jobSpecs"] for fr in job_frames(j)}
            missing = pod_frames - have
            h = listed.get(p.get("providerId"))
            pstat = h.status if h else (prov.TERMINATED if list_ok else None)
            if isinstance(done, dict) and done.get("status"):
                p["status"] = f"DONE:{done['status']}"
                self._terminate(st, [p], f"done ({done['status']})")
                if missing:
                    p["reassigned"] = True
                    reassign.append(p)
                continue
            if not missing and isinstance(hb, dict) and hb.get("state") in ("idle", "done"):
                p["status"] = "IDLE"
                self._terminate(st, [p], "all frames delivered, idle")
                continue
            dead = None
            if hb_t is None and now - (p["launchedAt"] or now) > opts["boot_timeout_s"]:
                dead = f"no heartbeat {int(now - p['launchedAt'])}s after launch"
            elif hb_t is not None and now - hb_t > opts["heartbeat_lost_s"]:
                dead = f"heartbeat silent {int(now - hb_t)}s"
            elif pstat in (prov.TERMINATED, prov.FAILED, prov.STOPPED) and p.get("providerId"):
                dead = f"provider reports {pstat}"
            if dead:
                p["status"] = "DEAD"
                p["deadReason"] = dead
                self._terminate(st, [p], dead)
                if missing:
                    p["reassigned"] = True
                    reassign.append(p)
                continue
            p["status"] = "RUNNING" if hb_t else "BOOTING"
        # spend / budget
        spent, rate = self.spend(st, now)
        st["spentUsd"], st["usdPerHourLive"] = spent, rate
        budget = st.get("budgetUsd")
        if budget is not None and spent >= float(budget):
            self._terminate(st, st["pods"], f"budget: spent ${spent:.2f} >= ${budget}")
            st["status"] = "BUDGET_EXCEEDED"
            self.save(st)
            return st["status"]
        # re-assign undelivered frames of dead / failed pods to fresh pods
        for p in reassign:
            gen = int(p.get("generation", 0)) + 1
            todo = missing_jobs(p["jobSpecs"], have, f"r{gen}")
            if not todo:
                continue
            if gen > int(opts["max_replacements"]):
                self._event(st, "replacements_exhausted", pod=p["pod"], frames=sum(j["frames"] for j in todo))
                st.setdefault("abandoned", []).extend(j["jobId"] for j in todo)
                continue
            live_rate = self.spend(st, now)[1]
            if live_rate + float(st["usdPerHour"]) > float(st.get("maxUsdPerHour") or 1e9):
                self._event(st, "replacement_deferred_rate_cap", pod=p["pod"])
                p["reassigned"] = False
                continue
            tag = f"{p['tag']}r{gen}"
            new = self._new_pod(st, todo, tag)
            new["generation"] = gen
            self._event(st, "reassigned", fromPod=p["pod"], toPod=new["pod"], frames=new["frames"])
        st["framesDone"] = len(want & have)
        if want <= have:
            self._terminate(st, st["pods"], "run complete")
            st["status"] = "COMPLETE"
        elif all(p.get("endedAt") for p in st["pods"]) and st.get("abandoned"):
            st["status"] = "FAILED"
        self.save(st)
        return st["status"]

    def pull(self, st, dest=None):
        dest = dest or os.path.join(self.repo, "episodes", st["episodeId"], "plates")
        pre = self.layout.plates_prefix(st["runId"])
        got = skipped = 0
        for k, (size, _) in s3_list(self.s3, self.bucket, pre).items():
            rel = k[len(pre):]
            dst = os.path.join(dest, rel)
            if os.path.isfile(dst) and os.path.getsize(dst) == size:
                skipped += 1
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            self.s3.download_file(self.bucket, k, dst + ".part")
            os.replace(dst + ".part", dst)
            got += 1
        st["pulled"] = {"dest": dest, "fetched": got, "unchanged": skipped, "at": int(self.clock())}
        self.save(st)
        return st["pulled"]

    def watch(self, run, interval=60, once=False, pull=True, dest=None, sleep=time.sleep, max_ticks=None):
        st = self.load(run)
        n = 0
        while True:
            status = self.tick(st)
            n += 1
            print(json.dumps(self.summary(st)), flush=True)
            if status == "COMPLETE" and pull and not st.get("pulled"):
                print(json.dumps({"pulled": self.pull(st, dest)}), flush=True)
            if status in TERMINAL or once or (max_ticks and n >= max_ticks):
                return st
            sleep(interval)

    def stop(self, run, reason="stopped by operator"):
        st = self.load(run)
        self._terminate(st, st["pods"], reason)
        st["spentUsd"] = self.spend(st, self.clock())[0]
        if st["status"] not in TERMINAL:
            st["status"] = "STOPPED"
        self.save(st)
        return self.summary(st)

    @staticmethod
    def summary(st):
        return {"runId": st["runId"], "status": st["status"], "frames": f"{st.get('framesDone', 0)}/{st['frames']}",
                "spentUsd": st.get("spentUsd"), "budgetUsd": st.get("budgetUsd"),
                "usdPerHourLive": st.get("usdPerHourLive"),
                "pods": [{k: p.get(k) for k in ("pod", "providerId", "status", "frames", "lastHeartbeat", "endReason",
                                                "deadReason", "error")} for p in st["pods"]]}


# ----------------------------------------------------------------------------------------------- CLI
def main(argv=None):
    p = argparse.ArgumentParser(description="Credential-free GPU pods driven by presigned S3 URLs.")
    p.add_argument("cmd", choices=["plan", "submit", "watch", "stop"])
    p.add_argument("--spec")
    p.add_argument("--run")
    p.add_argument("--quality", choices=sorted(jobsplit.PRESETS), default="preview")
    p.add_argument("--engine", choices=["CYCLES", "EEVEE"], default="CYCLES")
    p.add_argument("--res", default=None)
    p.add_argument("--samples", type=int, default=None)
    p.add_argument("--provider", choices=GPU_PROVIDERS, default="runpod")
    p.add_argument("--gpu", default="RTX4090")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--budget", type=float, default=None, help="total USD ceiling for the run")
    p.add_argument("--max-usd-per-hour", type=float, default=None, help="ceiling on the live pods' summed $/h")
    p.add_argument("--price", type=float, default=None, help="USD/h per pod (default: provider catalog)")
    p.add_argument("--frames", default=None, help="A-B (inclusive) subset of film frames")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--stack", default=os.environ.get("FARM_STACK", "story-farm"))
    p.add_argument("--bucket", default=os.environ.get("FARM_BUCKET"))
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    p.add_argument("--profile", default=os.environ.get("FARM_AWS_PROFILE"))
    p.add_argument("--root", default=DEFAULT_ROOT, help="S3 prefix for code/runs/plates")
    p.add_argument("--library-prefix", default=DEFAULT_LIBRARY_PREFIX)
    p.add_argument("--library", choices=["auto", "spec", "none"], default="auto",
                   help="auto: spec + renderer-referenced library files; spec: spec/kit only; none")
    p.add_argument("--code", choices=["head", "worktree"], default="head")
    p.add_argument("--expires-hours", type=float, default=168.0)
    p.add_argument("--interval", type=int, default=60)
    p.add_argument("--once", action="store_true")
    p.add_argument("--dest", default=None, help="where watch pulls plates (default episodes/<id>/plates)")
    p.add_argument("--no-pull", action="store_true")
    p.add_argument("--state-dir", default=None)
    a = p.parse_args(argv)

    if a.cmd == "plan":
        if not a.spec:
            p.error("plan needs --spec")
        spec = json.load(open(a.spec))
        price = a.price or prov.make(a.provider, {}, {}).default_prices.get(a.gpu, 0.69)
        js, groups, est = PresignedFarm.plan(spec, a.quality, a.workers, parse_frames(a.frames), a.engine, a.res,
                                             a.samples, price)
        print(json.dumps({"episodeId": spec["id"], "estimate": est, "usdPerHour": price,
                          "pods": [{"jobs": len(g), "frames": sum(j["frames"] for j in g),
                                    "estSeconds": round(sum(j["estSeconds"] for j in g), 1)} for g in groups]},
                         indent=1))
        return 0
    s3, sess = s3_client(a.region, a.profile)
    bucket = a.bucket or stack_bucket(sess, a.stack)
    farm = PresignedFarm(s3, bucket, Layout(a.root, a.library_prefix), a.provider, state_dir=a.state_dir)
    if a.cmd == "submit":
        if not a.spec:
            p.error("submit needs --spec")
        res = farm.submit(a.spec, a.quality, a.workers, a.budget, a.gpu, parse_frames(a.frames), a.engine, a.res,
                          a.samples, a.run, a.dry_run, a.code, a.library,
                          opts={"expires_s": int(a.expires_hours * 3600)}, price=a.price,
                          max_usd_per_hour=a.max_usd_per_hour)
        print(json.dumps(res, indent=1, default=str))
        return 0
    if not a.run:
        p.error(f"{a.cmd} needs --run")
    if a.cmd == "watch":
        st = farm.watch(a.run, a.interval, a.once, not a.no_pull, a.dest)
        return 0 if st["status"] in ("COMPLETE", "RUNNING") else 1
    if a.cmd == "stop":
        print(json.dumps(farm.stop(a.run), indent=1))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
