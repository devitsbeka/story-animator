import os
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "cloud", "farm"))

import threading  # noqa: E402

from factory.compute.store import S3Store as _S3Store  # noqa: E402

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


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def s3(monkeypatch, tmp_path):
    for k in ("AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("COMPUTE_STATE_DIR", str(tmp_path / "state"))
    from moto import mock_aws
    import boto3
    with mock_aws():
        c = boto3.client("s3", region_name="us-east-1")
        c.create_bucket(Bucket=BUCKET)
        yield c


_MOTO = threading.Lock()


class MotoSafeS3Store(_S3Store):
    """moto is not thread-safe per request (object bodies live in spooled temp files a concurrent overwrite can
    close under a reader). Real S3 is atomic per request, so emulate exactly that: one lock around each single
    request. Requests of different writers still interleave freely between a read and its conditional write,
    which is the race this test is about."""

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
