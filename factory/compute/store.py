"""
store.py - the tiny object-store contract the broker needs for ATOMIC state, with two implementations.

    put_if_absent(key, data)        -> bool   create only if the key does not exist (S3: If-None-Match: *)
    put_if_match(key, data, etag)   -> bool   overwrite only if unchanged since read     (S3: If-Match: <etag>)
    put(key, data)                           unconditional
    get(key)                        -> (bytes, etag) | (None, None)
    list(prefix)                    -> sorted [key]
    delete(key)

S3 has supported conditional writes on PutObject since Aug 2024 (If-None-Match) / Nov 2024 (If-Match); a lost
race comes back as 412 PreconditionFailed (or 409 ConditionalRequestConflict while another conditional write
on the same key is in flight), which both map to False here. MemoryStore gives the same semantics in-process
(thread-safe) for tests and for single-machine runs; LocalDirStore persists them on disk with a lock file.
"""
import fcntl
import hashlib
import json
import os
import threading


class Store:
    def get_json(self, key):
        data, etag = self.get(key)
        if data is None:
            return None, None
        try:
            return json.loads(data), etag
        except ValueError:
            return {"unparseable": True}, etag

    def put_json(self, key, obj):
        return self.put(key, _dump(obj))

    def put_json_if_absent(self, key, obj):
        return self.put_if_absent(key, _dump(obj))

    def put_json_if_match(self, key, obj, etag):
        return self.put_if_match(key, _dump(obj), etag)


def _dump(obj):
    return json.dumps(obj, sort_keys=True, default=str).encode()


def _etag(data):
    return '"' + hashlib.md5(data).hexdigest() + '"'  # noqa: S324 - same scheme as S3 single-part ETags


class MemoryStore(Store):
    def __init__(self):
        self.objs = {}
        self.lock = threading.Lock()
        self.calls = 0

    def put_if_absent(self, key, data):
        with self.lock:
            self.calls += 1
            if key in self.objs:
                return False
            self.objs[key] = bytes(data)
            return True

    def put_if_match(self, key, data, etag):
        with self.lock:
            self.calls += 1
            cur = self.objs.get(key)
            if cur is None or _etag(cur) != etag:
                return False
            self.objs[key] = bytes(data)
            return True

    def put(self, key, data):
        with self.lock:
            self.calls += 1
            self.objs[key] = bytes(data)
            return True

    def get(self, key):
        with self.lock:
            self.calls += 1
            d = self.objs.get(key)
            return (d, _etag(d)) if d is not None else (None, None)

    def list(self, prefix):
        with self.lock:
            self.calls += 1
            return sorted(k for k in self.objs if k.startswith(prefix))

    def delete(self, key):
        with self.lock:
            self.objs.pop(key, None)


class LocalDirStore(Store):
    """Directory-backed store; one flock serialises conditional writes across processes on this machine."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self._lockpath = os.path.join(self.root, ".lock")

    def _p(self, key):
        p = os.path.abspath(os.path.join(self.root, key))
        if not p.startswith(self.root + os.sep):
            raise ValueError(f"unsafe key {key!r}")
        return p

    def _locked(self, fn):
        with open(self._lockpath, "a") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                return fn()
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    def _write(self, key, data):
        p = self._p(key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, p)
        return True

    def put_if_absent(self, key, data):
        return self._locked(lambda: False if os.path.exists(self._p(key)) else self._write(key, data))

    def put_if_match(self, key, data, etag):
        def go():
            cur, tag = self._read(key)
            if cur is None or tag != etag:
                return False
            return self._write(key, data)
        return self._locked(go)

    def put(self, key, data):
        return self._locked(lambda: self._write(key, data))

    def _read(self, key):
        p = self._p(key)
        if not os.path.isfile(p):
            return None, None
        with open(p, "rb") as fh:
            d = fh.read()
        return d, _etag(d)

    def get(self, key):
        return self._read(key)

    def list(self, prefix):
        out = []
        for dp, _, fs in os.walk(self.root):
            for f in fs:
                if f.endswith(".tmp") or f == ".lock":
                    continue
                k = os.path.relpath(os.path.join(dp, f), self.root).replace(os.sep, "/")
                if k.startswith(prefix):
                    out.append(k)
        return sorted(out)

    def delete(self, key):
        p = self._p(key)
        if os.path.exists(p):
            os.unlink(p)


class S3Store(Store):
    """Conditional writes on S3 (bucket + key prefix). `s3` is a boto3 client with operator credentials."""

    def __init__(self, s3, bucket, prefix=""):
        self.s3, self.bucket = s3, bucket
        self.prefix = prefix.rstrip("/") + "/" if prefix else ""

    def _k(self, key):
        return self.prefix + key

    @staticmethod
    def _lost_race(e):
        code = str(e.response.get("Error", {}).get("Code", ""))
        status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return code in ("PreconditionFailed", "ConditionalRequestConflict", "412", "409") or status in (409, 412)

    def put_if_absent(self, key, data):
        from botocore.exceptions import ClientError
        try:
            self.s3.put_object(Bucket=self.bucket, Key=self._k(key), Body=data, IfNoneMatch="*")
            return True
        except ClientError as e:
            if self._lost_race(e):
                return False
            raise

    def put_if_match(self, key, data, etag):
        from botocore.exceptions import ClientError
        try:
            self.s3.put_object(Bucket=self.bucket, Key=self._k(key), Body=data, IfMatch=etag)
            return True
        except ClientError as e:
            if self._lost_race(e) or e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return False
            raise

    def put(self, key, data):
        self.s3.put_object(Bucket=self.bucket, Key=self._k(key), Body=data)
        return True

    def get(self, key):
        from botocore.exceptions import ClientError
        try:
            r = self.s3.get_object(Bucket=self.bucket, Key=self._k(key))
            return r["Body"].read(), r["ETag"]
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None, None
            raise

    def list(self, prefix):
        out = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=self._k(prefix)):
            for o in page.get("Contents", []) or []:
                out.append(o["Key"][len(self.prefix):])
        return sorted(out)

    def delete(self, key):
        self.s3.delete_object(Bucket=self.bucket, Key=self._k(key))
