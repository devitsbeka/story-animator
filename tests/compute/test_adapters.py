"""Adapters: Lambda invoke/REPORT/account meter on stubbed clients, local CPU child process, registry gate, stubs,
and the Lambda handler itself against a fake presigned 'network' with the fake Blender."""
import gzip
import hashlib
import io
import json
import os
import sys
import tarfile

import pytest

from factory.compute import registry
from factory.compute.adapters import make
from factory.compute.adapters.aws_lambda import AwsLambda
from factory.compute.adapters.base import CapacityError
from factory.compute.adapters.stubs import STUBS

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))


class FakeLambda:
    def __init__(self, throttle=False):
        self.calls, self.throttle = [], throttle

    def invoke(self, **kw):
        if self.throttle:
            e = Exception("throttled")
            e.response = {"Error": {"Code": "TooManyRequestsException"}}
            raise e
        self.calls.append(kw)
        return {"StatusCode": 202, "ResponseMetadata": {"RequestId": f"0000000{len(self.calls)}-aaaa-bbbb-cccc-dddddddddddd"}}

    def get_function_configuration(self, FunctionName):
        return {"State": "Active", "MemorySize": 3008}

    def get_account_settings(self):
        return {"AccountLimit": {"ConcurrentExecutions": 10, "UnreservedConcurrentExecutions": 10}}

    def get_paginator(self, name):
        class P:
            def paginate(self_inner):
                return [{"Functions": [{"FunctionName": "story-compute-render", "MemorySize": 3008},
                                       {"FunctionName": "remotion-render", "MemorySize": 2048}]}]
        return P()


class FakeLogs:
    def __init__(self, events):
        self.events = events

    def get_paginator(self, name):
        ev = self.events

        class P:
            def paginate(self_inner, **kw):
                return [{"events": [{"message": m} for m in ev]}]
        return P()


class FakeCW:
    def get_metric_statistics(self, **kw):
        name = kw["Dimensions"][0]["Value"]
        if kw["MetricName"] == "Duration":
            return {"Datapoints": [{"Sum": 1_000_000.0 if name == "story-compute-render" else 500_000.0}]}
        return {"Datapoints": [{"Sum": 10.0}]}


CFG = {"adapter": "aws_lambda", "type": "cpu", "max_runtime_s": 900, "concurrency": 10,
       "quota": {"unit": "GB-s", "free": 400000, "period": "month", "unit_usd": 0.0000166667},
       "config": {"function": "story-compute-render", "memory_mb": 3008}, "spf": {"preview": 12}}


def test_lambda_invoke_report_and_usage(clock):
    lam = FakeLambda()
    rid = "00000001-aaaa-bbbb-cccc-dddddddddddd"
    logs = FakeLogs([f"REPORT RequestId: {rid}\tDuration: 120000.00 ms\tBilled Duration: 125000 ms\t"
                     f"Memory Size: 3008 MB\tMax Memory Used: 2100 MB\tInit Duration: 4000.12 ms"])
    a = AwsLambda("aws_lambda", CFG, lam=lam, logs=logs, cw=FakeCW(), clock=clock)
    ok, why = a.available()
    assert ok and a.concurrency() == 10 and a.worker_profile()["ramGb"] == pytest.approx(2.94, 0.01)
    h = a.start({"chunk": "A01a-f0", "attempt": "att1", "manifestUrl": "https://x/y?sig"})
    assert lam.calls[0]["InvocationType"] == "Event"
    assert json.loads(lam.calls[0]["Payload"]) == {"manifestUrl": "https://x/y?sig", "chunk": "A01a-f0",
                                                   "attempt": "att1"}
    assert a.slots() == 9
    a.refresh()
    pr = a.poll(h)
    assert pr["state"] == "exited" and pr["usage"]["GB-s"] == pytest.approx(125 * 3008 / 1024, abs=1e-3)
    assert a.usage_estimate(100)["GB-s"] == pytest.approx(100 * 3008 / 1024)


def test_lambda_timeout_line_marks_failure(clock):
    rid = "00000001-aaaa-bbbb-cccc-dddddddddddd"
    logs = FakeLogs([f"2026-11-22T13:00:00.000Z {rid} Task timed out after 900.00 seconds",
                     f"REPORT RequestId: {rid}\tDuration: 900000.00 ms\tBilled Duration: 900000 ms\t"
                     f"Memory Size: 3008 MB\tMax Memory Used: 3008 MB"])
    a = AwsLambda("aws_lambda", CFG, lam=FakeLambda(), logs=logs, cw=FakeCW(), clock=clock)
    h = a.start({"chunk": "c", "attempt": "a", "manifestUrl": "u"})
    a.refresh()
    assert a.poll(h)["state"] == "failed"


def test_lambda_throttle_is_capacity_error(clock):
    a = AwsLambda("aws_lambda", CFG, lam=FakeLambda(throttle=True), logs=FakeLogs([]), cw=FakeCW(), clock=clock)
    with pytest.raises(CapacityError):
        a.start({"chunk": "c", "attempt": "a", "manifestUrl": "u"})


def test_lambda_account_meter_counts_every_function(clock):
    a = AwsLambda("aws_lambda", CFG, lam=FakeLambda(), logs=FakeLogs([]), cw=FakeCW(), clock=clock)
    u = a.account_usage(clock() - 86400)
    assert u["GB-s"] == pytest.approx(1000 * 3008 / 1024 + 500 * 2, rel=1e-6)
    assert set(u["functions"]) == {"story-compute-render", "remotion-render"}


def test_registry_terms_gate_and_registry_merge(tmp_path):
    reg = tmp_path / "registry.yaml"
    reg.write_text("sources:\n"
                   "  - {id: kaggle, verdict: USE, quota: {free: 20}}\n"
                   "  - {id: colab, adapter: none, verdict: AVOID}\n"
                   "  - {id: hf_spaces, verdict: 'use with care'}\n")
    cfg = registry.load(registry_yaml=str(reg), calibration={})
    assert "kaggle" in cfg["providers"] and cfg["providers"]["kaggle"]["quota"]["free"] == 20
    assert cfg["providers"]["kaggle"]["quota"]["unit"] == "GPU-h"           # broker.yaml field kept
    assert "AVOID" in cfg["gated"]["colab"]
    assert "USE-WITH-CARE" in cfg["gated"]["hf_spaces"]
    cfg2 = registry.load(registry_yaml=str(reg), allow_care=["hf_spaces"], calibration={})
    assert "hf_spaces" in cfg2["providers"]
    cal = registry.load(registry_yaml=None, calibration={"aws_lambda": {"spf": {"preview": 7.5}, "build_s": 33}})
    assert cal["providers"]["aws_lambda"]["spf"]["preview"] == 7.5 and cal["providers"]["aws_lambda"]["build_s"] == 33


def test_stub_adapters_are_never_schedulable():
    for name, cls in STUBS.items():
        a = cls(name, {"adapter": name})
        ok, why = a.available()
        assert not ok and "stub" in why and a.slots() == 0 and cls.contract.strip()
        with pytest.raises(NotImplementedError):
            a.start({})
    assert make("gcp_cloud_run_jobs", {"adapter": "gcp_cloud_run_jobs"}).slots() == 0


# ---------------------------------------------------------------------------------------- the Lambda handler
class DictNet:
    """UrlNet over a dict of url -> bytes (what presigned GET/PUT do)."""

    def __init__(self, objs):
        self.objs = objs
        self.bytes_up = self.bytes_down = 0
        import threading
        self.lock = threading.Lock()

    def get_bytes(self, url):
        return self.objs[url]

    def get(self, target, dst, sha256=None):
        data = self.objs[target["url"]]
        if sha256 and hashlib.sha256(data).hexdigest() != sha256:
            raise RuntimeError("sha256 mismatch")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(data)
        self.bytes_down += len(data)
        return dst

    def put_file(self, target, path):
        with open(path, "rb") as fh:
            self.objs[target["url"]] = fh.read()

    def put_json(self, target, obj):
        self.objs[target["url"]] = json.dumps(obj).encode()


def code_tar():
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as tf:
        for rel in ("cloud/farm/presigned_pod.py",):
            tf.add(os.path.join(REPO, rel), arcname=rel)
        spec = json.dumps({"id": "ep", "shots": [{"id": "S0", "from": 0, "to": 3}]}).encode()
        ti = tarfile.TarInfo("episodes/ep/ep.json")
        ti.size = len(spec)
        tf.addfile(ti, io.BytesIO(spec))
    return buf.getvalue(), spec


def test_lambda_handler_renders_a_chunk_through_presigned_urls_only(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.join(REPO, "factory", "compute", "aws_lambda"))
    import handler
    monkeypatch.setattr(handler, "TMP", str(tmp_path / "tmp"))
    fake = tmp_path / "blender"
    fake.write_text(f"#!/bin/sh\nexec {sys.executable} {os.path.join(REPO, 'tests', 'farm', 'fake_blender.py')} \"$@\"\n")
    fake.chmod(0o755)
    data, spec = code_tar()
    put = lambda k: {"url": f"https://s3/{k}?sig", "method": "PUT", "headers": {}}  # noqa: E731
    man = {"kind": "story-farm-presigned-pod", "runId": "r", "pod": "att", "requireGpu": True, "heartbeatS": 30,
           "jobAttempts": 1, "threads": 2,
           "code": {"url": "https://s3/code?sig", "sha256": hashlib.sha256(data).hexdigest()},
           "spec": {"url": "https://s3/spec?sig", "sha256": hashlib.sha256(spec).hexdigest(),
                    "path": "episodes/ep/ep.json"},
           "library": [], "heartbeat": put("hb"), "done": put("done"), "podLog": put("log"),
           "jobs": [{"jobId": "att", "shot": "S0", "frameStart": 0, "frameEnd": 2, "quality": "preview",
                     "engine": "CYCLES", "res": "8x8", "samples": 2, "estSeconds": 10,
                     "plates": {str(f): put(f"plate{f}") for f in range(3)}, "log": put("joblog"),
                     "manifest": put("jobman")}]}
    objs = {"https://s3/man?sig": json.dumps(man).encode(), "https://s3/code?sig": data,
            "https://s3/spec?sig": spec}
    monkeypatch.setenv("FAKE_DEVICE", "CPU")
    out = handler.handler({"manifestUrl": "https://s3/man?sig", "attempt": "att", "chunk": "S0-f0"},
                          net=DictNet(objs), blender=str(fake))
    assert out["rc"] == 0 and out["frames"] == 3
    assert all(f"https://s3/plate{f}?sig" in objs for f in range(3))
    done = json.loads(objs["https://s3/done?sig"])
    assert done["status"] == "DONE"
    jm = json.loads(objs["https://s3/jobman?sig"])
    assert [f["frame"] for f in jm["files"]] == [0, 1, 2]
    # warm container: the code is not downloaded again
    objs.pop("https://s3/code?sig")
    out2 = handler.handler({"manifestUrl": "https://s3/man?sig", "attempt": "att2"}, net=DictNet(objs),
                           blender=str(fake))
    assert out2["rc"] == 0 and out2["freshCode"] is False
