"""Shared helpers for tests/compute (a uniquely named module: other test dirs have their own conftest/fakes)."""
import os
import sys
import threading

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for p in (REPO, os.path.join(REPO, "cloud", "farm")):
    if p not in sys.path:
        sys.path.insert(0, p)

from factory.compute.store import S3Store  # noqa: E402

BUCKET = "story-compute-test"


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s

    def sleep(self, s):
        self.t += s


_MOTO = threading.Lock()


class MotoSafeS3Store(S3Store):
    """moto is not thread-safe per request (object bodies live in spooled temp files a concurrent overwrite can
    close under a reader). Real S3 is atomic per request, so emulate exactly that: one lock around each single
    request. Requests of different writers still interleave freely between a read and its conditional write,
    which is the race the tests are about."""

    def get(self, key):
        with _MOTO:
            return super().get(key)

    def put_if_absent(self, key, data):
        with _MOTO:
            return super().put_if_absent(key, data)

    def put_if_match(self, key, data, etag):
        with _MOTO:
            return super().put_if_match(key, data, etag)

    def list(self, prefix):
        with _MOTO:
            return super().list(prefix)
