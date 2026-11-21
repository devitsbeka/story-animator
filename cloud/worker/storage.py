"""
storage.py - one tiny interface over the two storage backends the worker uses.

  STORAGE=local  ROOT=<dir>      keys are paths relative to <dir>  (dev / tests, no secrets)
  STORAGE=r2                     Cloudflare R2 through its S3 API (boto3)
                                 env: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
                                 optional R2_ENDPOINT (default https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com)

Keys are the shared storage layout (assets/..., episodes/<id>/...), identical in both backends.
Every write is atomic (temp file + rename locally; S3 PUTs are atomic), so a key that exists is complete.
"""
import os
import shutil
import tempfile
import time

CONTENT_TYPES = {
    ".png": "image/png", ".mp4": "video/mp4", ".json": "application/json", ".jsonl": "application/x-ndjson",
    ".log": "text/plain", ".txt": "text/plain", ".glb": "model/gltf-binary", ".mp3": "audio/mpeg",
}


def content_type(key):
    return CONTENT_TYPES.get(os.path.splitext(key)[1].lower(), "application/octet-stream")


def retry(fn, what, attempts=4, base=0.5, log=None):
    """Call fn() with exponential backoff; re-raise after the last attempt. FileNotFoundError is not retried."""
    for i in range(attempts):
        try:
            return fn()
        except FileNotFoundError:
            raise
        except Exception as e:  # noqa: BLE001 - storage errors vary by backend
            if i == attempts - 1:
                raise
            if log:
                log("storage_retry", level="warn", op=what, attempt=i + 1, error=str(e)[:300])
            time.sleep(base * (2 ** i))


def _atomic_copy(src, dst):
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".part-", dir=os.path.dirname(dst) or ".")
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class LocalStorage:
    kind = "local"

    def __init__(self, root):
        self.root = os.path.abspath(root)

    def path(self, key):
        p = os.path.abspath(os.path.join(self.root, key))
        if not (p == self.root or p.startswith(self.root + os.sep)):
            raise ValueError(f"key escapes storage root: {key}")
        return p

    def stat(self, key):
        """-> {'size', 'etag'} or None."""
        p = self.path(key)
        if not os.path.isfile(p):
            return None
        st = os.stat(p)
        return {"size": st.st_size, "etag": f"{st.st_size}-{int(st.st_mtime_ns)}"}

    def exists(self, key):
        return self.stat(key) is not None

    def list(self, prefix):
        """-> {key: size} for every file under prefix."""
        base = self.path(prefix.rstrip("/"))
        out = {}
        if not os.path.isdir(base):
            return out
        for d, _, files in os.walk(base):
            for f in files:
                if f.startswith(".part-"):
                    continue
                p = os.path.join(d, f)
                out[os.path.relpath(p, self.root).replace(os.sep, "/")] = os.path.getsize(p)
        return out

    def download(self, key, dst):
        src = self.path(key)
        if not os.path.isfile(src):
            raise FileNotFoundError(key)
        if os.path.abspath(dst) != src:
            _atomic_copy(src, dst)
        return dst

    def upload(self, src, key):
        dst = self.path(key)
        if os.path.abspath(src) != dst:
            _atomic_copy(src, dst)
        return key


class R2Storage:
    kind = "r2"

    def __init__(self, bucket, client):
        self.bucket = bucket
        self.s3 = client

    @classmethod
    def from_env(cls):
        import boto3
        from botocore.config import Config

        missing = [k for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET") if not os.environ.get(k)]
        if missing and not os.environ.get("R2_ENDPOINT"):
            raise RuntimeError(f"STORAGE=r2 needs env vars: {', '.join(missing)}")
        endpoint = os.environ.get("R2_ENDPOINT") or f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=os.environ.get("R2_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("R2_SECRET_ACCESS_KEY"),
            region_name="auto",
            config=Config(signature_version="s3v4", retries={"max_attempts": 6, "mode": "standard"},
                          connect_timeout=10, read_timeout=120, max_pool_connections=32),
        )
        return cls(os.environ["R2_BUCKET"], client)

    def stat(self, key):
        from botocore.exceptions import ClientError

        try:
            h = self.s3.head_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise
        return {"size": h["ContentLength"], "etag": h.get("ETag", "").strip('"')}

    def exists(self, key):
        return self.stat(key) is not None

    def list(self, prefix):
        out = {}
        pag = self.s3.get_paginator("list_objects_v2")
        for page in pag.paginate(Bucket=self.bucket, Prefix=prefix):
            for o in page.get("Contents", []) or []:
                out[o["Key"]] = o["Size"]
        return out

    def download(self, key, dst):
        from botocore.exceptions import ClientError

        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".part-", dir=os.path.dirname(dst) or ".")
        os.close(fd)
        try:
            self.s3.download_file(self.bucket, key, tmp)
            os.replace(tmp, dst)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                raise FileNotFoundError(key) from e
            raise
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return dst

    def upload(self, src, key):
        self.s3.upload_file(src, self.bucket, key, ExtraArgs={"ContentType": content_type(key)})
        return key


def from_env():
    kind = os.environ.get("STORAGE", "local").lower()
    if kind == "local":
        return LocalStorage(os.environ.get("ROOT") or os.getcwd())
    if kind in ("r2", "s3"):
        return R2Storage.from_env()
    raise RuntimeError(f"unknown STORAGE={kind!r} (local|r2)")
