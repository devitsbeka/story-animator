"""Broker end to end on moto S3 with fake providers: mix, work stealing, failures, quota caps, stragglers."""
import json

import pytest

from factory.compute.broker import Broker, png_size
from factory.compute.store import S3Store

from conftest import BUCKET
from fakes import FakeAdapter, png_bytes

SPEC = {"id": "ep", "shots": [{"id": "S0", "from": 0, "to": 24}, {"id": "S1", "from": 24, "to": 40}]}


def cfg(**kw):
    base = {"type": "cpu", "max_runtime_s": 900, "terms": "USE", "trusted": True, "priority": 50,
            "hardware": {"ram_gb": 10}}
    return {**base, **kw}


def inputs():
    return {"episodeId": "ep", "code": {"key": "compute/code/x.tar.gz", "sha256": "0" * 64, "size": 1},
            "spec": {"key": "compute/runs/x/inputs/episode.json", "sha256": "0" * 64, "path": "episodes/ep/ep.json"},
            "library": []}


def make_broker(s3, clock, tmp_path, adapters, configs):
    spec = tmp_path / "ep.json"
    spec.write_text(json.dumps(SPEC))
    conf = {"defaults": {"safety": 0.0, "spot_check_fraction": 0.0}, "providers": configs, "gated": {}}
    b = Broker(s3, BUCKET, store=S3Store(s3, BUCKET), config=conf, adapters=adapters, clock=clock, sleep=clock.sleep,
               state_dir=str(tmp_path / "runs"))
    return b, str(spec)


def run(b, spec, clock, max_ticks=500, **kw):
    st = b.submit(spec, "preview", res="8x8", samples=4, inputs=inputs(), run_id=kw.pop("run_id", "r1"), **kw)
    for _ in range(max_ticks):
        st = b.tick(st)
        if st["status"] in ("COMPLETE", "FAILED", "STOPPED"):
            break
        clock.advance(5)
    return st


def plates(s3, run_id="r1"):
    pre = f"compute/plates/{run_id}/"
    out = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=pre):
        for o in page.get("Contents", []):
            out[o["Key"][len(pre):]] = s3.get_object(Bucket=BUCKET, Key=o["Key"])["Body"].read()
    return out


def test_two_free_providers_share_one_job(s3, clock, tmp_path):
    lam_cfg = cfg(quota={"unit": "GB-s", "free": 400000, "period": "month"}, priority=10, concurrency=10)
    loc_cfg = cfg(priority=90, max_runtime_s=86400)
    lam = FakeAdapter("aws_lambda", lam_cfg, s3, BUCKET, clock, spf=6, conc=10, gbs_per_s=10.0)
    loc = FakeAdapter("local_cpu", loc_cfg, s3, BUCKET, clock, spf=11, conc=1)
    b, spec = make_broker(s3, clock, tmp_path, {"aws_lambda": lam, "local_cpu": loc},
                          {"aws_lambda": lam_cfg, "local_cpu": loc_cfg})
    st = run(b, spec, clock, deadline_min=30)
    assert st["status"] == "COMPLETE"
    got = plates(s3)
    assert len(got) == 40 and all(png_size(v) == (8, 8) for v in got.values())
    assert len(lam.started) >= 10 and len(loc.started) >= 1          # both providers really rendered
    led = b.ledger.state("aws_lambda", lam_cfg["quota"])
    assert led["used"] > 0 and led["reserved"] == 0
    assert st["usage"]["aws_lambda"]["GB-s"] == pytest.approx(led["used"])
    assert st["spentUsd"] == 0
    assert "aws_lambda" in st["calibration"]


def test_failing_provider_is_disabled_and_work_moves(s3, clock, tmp_path):
    bad_cfg, good_cfg = cfg(priority=10), cfg(priority=20)
    bad = FakeAdapter("flaky", bad_cfg, s3, BUCKET, clock, spf=1, conc=4, mode="crash")
    good = FakeAdapter("steady", good_cfg, s3, BUCKET, clock, spf=3, conc=2)
    b, spec = make_broker(s3, clock, tmp_path, {"flaky": bad, "steady": good}, {"flaky": bad_cfg, "steady": good_cfg})
    st = run(b, spec, clock)
    assert st["status"] == "COMPLETE" and len(plates(s3)) == 40
    assert "flaky" in st["disabled"]
    assert all(t["status"] == "failed" for t in st["tasks"].values() if t["provider"] == "flaky")


def test_capacity_error_at_start_falls_back(s3, clock, tmp_path):
    a_cfg, b_cfg = cfg(priority=10), cfg(priority=20)
    a = FakeAdapter("nostock", a_cfg, s3, BUCKET, clock, conc=4, fail_start=True)
    c = FakeAdapter("other", b_cfg, s3, BUCKET, clock, spf=2, conc=2)
    b, spec = make_broker(s3, clock, tmp_path, {"nostock": a, "other": c}, {"nostock": a_cfg, "other": b_cfg})
    st = run(b, spec, clock)
    assert st["status"] == "COMPLETE" and "nostock" in st["disabled"]


def test_free_tier_is_never_exceeded(s3, clock, tmp_path):
    q = {"unit": "GB-s", "free": 1500, "period": "month"}
    lam_cfg = cfg(quota=q, priority=10)
    loc_cfg = cfg(priority=90, max_runtime_s=86400)
    lam = FakeAdapter("aws_lambda", lam_cfg, s3, BUCKET, clock, spf=6, conc=10, gbs_per_s=10.0)
    loc = FakeAdapter("local_cpu", loc_cfg, s3, BUCKET, clock, spf=11, conc=1)
    b, spec = make_broker(s3, clock, tmp_path, {"aws_lambda": lam, "local_cpu": loc},
                          {"aws_lambda": lam_cfg, "local_cpu": loc_cfg})
    st = run(b, spec, clock, max_ticks=2000)
    assert st["status"] == "COMPLETE" and len(plates(s3)) == 40
    led = b.ledger.state("aws_lambda", q)
    assert led["used"] <= 1500 and led["paid"] == 0
    assert len(loc.started) >= 1           # the rest went to the free local CPU


def test_straggler_is_re_executed_on_a_faster_provider(s3, clock, tmp_path):
    slow_cfg, fast_cfg = cfg(priority=10, max_runtime_s=86400), cfg(priority=20, max_runtime_s=86400)
    slow = FakeAdapter("slowpoke", slow_cfg, s3, BUCKET, clock, spf=1, real_spf=200, overhead=0, conc=1)
    fast = FakeAdapter("fast", fast_cfg, s3, BUCKET, clock, spf=1, overhead=0, conc=1)
    b, spec = make_broker(s3, clock, tmp_path, {"slowpoke": slow, "fast": fast},
                          {"slowpoke": slow_cfg, "fast": fast_cfg})
    st = run(b, spec, clock, max_ticks=3000)
    assert st["status"] == "COMPLETE"
    specs = [t for t in st["tasks"].values() if t["spec"]]
    assert specs and specs[0]["provider"] == "fast"
    assert st["progress"]["speculative"] >= 1
    for e in st["events"]:
        if e["ev"] in ("started", "task_done", "task_duplicate", "cancelled", "complete"):
            print(e)
    assert st["wallS"] < 200 * 10        # did not wait for the straggler's 2000+ s chunk
    assert any(t["status"] == "cancelled" for t in st["tasks"].values() if t["provider"] == "slowpoke")


def test_paid_provider_unused_when_free_suffices_and_blocked_without_allow(s3, clock, tmp_path):
    free_cfg = cfg(priority=10, max_runtime_s=86400)
    paid_cfg = cfg(priority=50, price_usd_h=0.69, type="gpu", max_runtime_s=86400)
    free = FakeAdapter("free", free_cfg, s3, BUCKET, clock, spf=2, conc=4)
    paid = FakeAdapter("runpod", paid_cfg, s3, BUCKET, clock, spf=0.5, conc=4)
    b, spec = make_broker(s3, clock, tmp_path, {"free": free, "runpod": paid}, {"free": free_cfg, "runpod": paid_cfg})
    st = run(b, spec, clock, deadline_min=60, allow_paid=True, budget=5)
    assert st["status"] == "COMPLETE" and paid.started == []
    # an impossible deadline without --allow-paid still renders for free, never on the paid pod
    st2 = run(b, spec, clock, deadline_min=0.1, allow_paid=False, run_id="r2")
    assert st2["status"] == "COMPLETE" and paid.started == []


def test_png_size_rejects_truncated():
    data = png_bytes("S0", 1)
    assert png_size(data) == (8, 8)
    assert png_size(data[:-5]) is None
