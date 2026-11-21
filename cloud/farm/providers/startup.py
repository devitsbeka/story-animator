"""
providers/startup.py - render the worker startup script and the one-line container command that carries it.

    script = render_startup({"FARM_CODE_SOURCE": "git", "FARM_GIT_URL": ..., "FARM_GIT_COMMIT": ..., ...})
    cmd    = bootstrap_command(script)     # 'echo <gzip+base64> | base64 -d | gunzip > /tmp/... && exec bash ...'

The settings block holds only non-secret values (it ends up in provider consoles and in dry-run files); secrets
go in the container env (see worker_env()). code_bundle() builds the S3 code tarball alternative to git.
"""
import base64
import gzip
import hashlib
import io
import os
import re
import shlex
import subprocess
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "worker_startup.sh")
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

# Same pinned Blender as cloud/farm/Dockerfile (official sha256 of blender-4.2.3-linux-x64.tar.xz).
BLENDER = {"BLENDER_VERSION": "4.2.3", "BLENDER_SERIES": "4.2",
           "BLENDER_SHA256": "3a64efd1982465395abab4259b4091d5c8c56054c7267e9633e4f702a71ea3f4"}
BASE_IMAGE = "nvidia/cuda:12.4.1-base-ubuntu22.04"
# What the renderer needs from the repo (mirrors cloud/farm/Dockerfile.dockerignore's allow-list).
CODE_PATHS = ["cloud/blender", "cloud/farm", "studio/public/assets", "studio/src/data", "factory/library", "assets"]
SECRET_ENV = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "GIT_TOKEN")
SETTING_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
MARKER = "# ---- settings rendered by providers/startup.py ----"


def render_startup(settings):
    """-> the full bash script: shebang, a settings block, then worker_startup.sh's body."""
    for k, v in settings.items():
        if not SETTING_RE.match(k):
            raise ValueError(f"bad setting name {k!r}")
        if k in SECRET_ENV:
            raise ValueError(f"{k} is a secret: pass it as container env, not in the startup script")
        if "\n" in str(v):
            raise ValueError(f"setting {k} contains a newline")
    with open(TEMPLATE) as fh:
        body = fh.read()
    shebang, rest = body.split("\n", 1)
    merged = {**BLENDER, **settings}
    block = "\n".join(f"export {k}={shlex.quote(str(v))}" for k, v in sorted(merged.items()))
    return f"{shebang}\n{MARKER}\n{block}\n# ---- end settings ----\n{rest}"


def bootstrap_command(script, path="/tmp/farm-startup.sh"):
    """A single shell line that unpacks `script` and execs it (fits container 'args'/'cmd' fields)."""
    blob = base64.b64encode(gzip.compress(script.encode(), mtime=0)).decode()
    return f"echo {blob} | base64 -d | gunzip > {path} && exec bash {path}"


def decode_bootstrap(cmd):
    """Inverse of bootstrap_command (tests, dry-run review)."""
    blob = cmd.split("echo ", 1)[1].split(" ", 1)[0]
    return gzip.decompress(base64.b64decode(blob)).decode()


def git_head(repo=REPO):
    return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()


def git_url(repo=REPO):
    url = subprocess.run(["git", "-C", repo, "remote", "get-url", "origin"], capture_output=True, text=True,
                         check=True).stdout.strip()
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url.split(":", 1)[1]
    if url.startswith("https://") and not url.endswith(".git"):
        url += ".git"
    return url


def code_bundle(commit, repo=REPO, paths=CODE_PATHS):
    """git archive of the renderer's paths at `commit` -> (bytes tar.gz, sha256). Deterministic for a commit."""
    have = [p for p in paths if subprocess.run(["git", "-C", repo, "cat-file", "-e", f"{commit}:{p}"],
                                               capture_output=True).returncode == 0]
    tar = subprocess.run(["git", "-C", repo, "archive", "--format=tar", commit, *have], capture_output=True,
                         check=True).stdout
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(tar)
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest()


def bundle_members(data):
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        return tf.getnames()


def code_settings(code_cfg, commit, bucket_key=None, sha256=None):
    """FARM_CODE_* settings for the startup script from providers.yaml `code:`."""
    src = code_cfg.get("source", "git")
    if src == "git":
        return {"FARM_CODE_SOURCE": "git", "FARM_GIT_URL": code_cfg.get("git_url") or git_url(),
                "FARM_GIT_COMMIT": commit}
    if src == "s3":
        return {"FARM_CODE_SOURCE": "s3", "FARM_CODE_KEY": bucket_key or code_key(commit),
                "FARM_CODE_SHA256": sha256 or ""}
    raise ValueError(f"code.source must be git or s3, not {src!r}")


def code_key(commit):
    return f"farm/code/{commit}.tar.gz"


def worker_env(farm, provider, gpu_class, secrets, extra=None):
    """Container env for an external worker: queue/bucket/table + the external IAM user's keys (+ GIT_TOKEN)."""
    env = {"FARM_BUCKET": farm["bucket"], "FARM_QUEUE_URL": farm["queue_url"], "FARM_TABLE": farm["table"],
           "AWS_REGION": farm.get("region", "us-east-1"), "FARM_PROVIDER": provider, "FARM_GPU_CLASS": gpu_class,
           "REQUIRE_GPU": "0" if gpu_class == "CPU" else "1",
           "NVIDIA_DRIVER_CAPABILITIES": "compute,utility,graphics"}
    for k in SECRET_ENV:
        if secrets.get(k):
            env[k] = secrets[k]
    env.update(extra or {})
    return env


def redact(env):
    """Secrets -> REDACTED (shell-safe, so a redacted env still renders as a Vast docker-flag string)."""
    def secret(k):
        return k in SECRET_ENV or "SECRET" in k or "TOKEN" in k or (k.endswith("_KEY") and k != "FARM_CODE_KEY")
    return {k: ("REDACTED" if secret(k) and not str(v).startswith("{{") else v) for k, v in env.items()}
