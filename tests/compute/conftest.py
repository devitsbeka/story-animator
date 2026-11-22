import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compute_testkit import BUCKET, Clock  # noqa: E402


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
