"""aws_ec2 (fake AWS clients) and local (real child processes, a stand-in for worker.py) providers."""
import subprocess
import sys
import time

import pytest

from fakes import aws_clients
from providers import CapacityError, QuotaError, PENDING, RUNNING, STOPPED
from providers.aws_ec2 import AwsEc2
from providers.local import Local

CFG = {"max_workers": 2, "gpu_classes": ["L4", "A10G"], "stack": "story-farm"}


def test_quota_zero_is_unavailable_with_reason():
    clients, _ = aws_clients(spot=0, ondemand=0)
    ok, reason = AwsEc2(CFG, clients=clients).available()
    assert not ok and "quota is 0" in reason and "L-3819A6DF" in reason
    assert ("ec2", "L-3819A6DF") in clients["service-quotas"].calls


def test_no_credentials_is_unavailable():
    clients, _ = aws_clients()
    clients["service-quotas"].error = RuntimeError("Unable to locate credentials")
    ok, reason = AwsEc2(CFG, clients=clients).available()
    assert not ok and "credentials" in reason


def test_recent_capacity_failure_is_unavailable():
    clients, asg = aws_clients(spot=8, ondemand=8)
    assert AwsEc2(CFG, clients=clients).available()[0]
    asg.fail("story-farm-spot-workers")
    ok, reason = AwsEc2(CFG, clients=clients).available()
    assert not ok and "InsufficientInstanceCapacity" in reason


def test_launch_raises_spot_desired_capacity_within_quota_and_max():
    clients, asg = aws_clients(spot=8, ondemand=4, spot_max=4)
    p = AwsEc2(CFG, clients=clients)
    hs = p.launch(3, "L4", {}, "", spot=True)
    assert asg.desired_calls == [("story-farm-spot-workers", 2)]  # quota 8 vCPU = 2 workers
    assert len(hs) == 2 and all(h.detail["placeholder"] and h.spot for h in hs)
    with pytest.raises(CapacityError):
        p.launch(1, "L4", {}, "", spot=True)
    # spot quota 0 -> on-demand group
    clients2, asg2 = aws_clients(spot=0, ondemand=4)
    h = AwsEc2(CFG, clients=clients2).launch(1, "A10G", {}, "", spot=True)[0]
    assert asg2.desired_calls == [("story-farm-ondemand-workers", 1)] and not h.spot
    assert h.price_per_hour == pytest.approx(1.006)
    with pytest.raises(QuotaError):
        AwsEc2(CFG, clients=aws_clients(0, 0)[0]).launch(1, "L4", {}, "")


def test_list_and_terminate_and_placeholder_release():
    clients, asg = aws_clients(spot=8, ondemand=4)
    p = AwsEc2(CFG, clients=clients)
    ph = p.launch(2, "L4", {}, "")
    asg.boot("story-farm-spot-workers", "i-1", "g6.xlarge")
    hs = p.list()
    assert [(h.id, h.status, h.gpu_class, h.worker_key) for h in hs] == [("i-1", RUNNING, "L4", "aws_ec2:i-1")]
    assert p.terminate(["i-1"]) == ["i-1"] and asg.terminated == ["i-1"]
    assert asg.groups["story-farm-spot-workers"]["DesiredCapacity"] == 1
    p.terminate([ph[1].id])                        # placeholder that never booted gives capacity back
    assert asg.groups["story-farm-spot-workers"]["DesiredCapacity"] == 0


def sleeper_popen(argv, **kw):
    """Stand-in for worker.py: a real process that lives until terminated."""
    kw.pop("env", None)
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **kw)


def test_local_launch_list_terminate(tmp_path):
    seen = {}

    def popen(argv, **kw):
        seen.update(kw["env"])
        assert argv[-1].endswith("cloud/farm/worker.py")
        return sleeper_popen(argv, **kw)
    p = Local({"max_workers": 1, "threads": 2}, state_dir=str(tmp_path), popen=popen)
    assert p.available()[0]
    h = p.launch(1, "CPU", {"FARM_BUCKET": "b"}, "")[0]
    assert seen["REQUIRE_GPU"] == "0" and seen["FARM_PROVIDER_WORKER_ID"] == h.worker_key == f"local:{h.id}"
    assert seen["FARM_BUCKET"] == "b" and seen["RENDER_THREADS"] == "2"
    assert [x.status for x in p.list()] == [RUNNING]
    assert not p.available()[0]                    # slot taken
    assert p.terminate([h.id]) == [h.id]
    t = time.time()
    while time.time() - t < 5 and p.list():
        time.sleep(0.05)
    assert p.list() == [] and p.available()[0]


def test_local_dead_process_reads_stopped(tmp_path):
    p = Local({"max_workers": 1}, state_dir=str(tmp_path),
              popen=lambda argv, **kw: subprocess.Popen([sys.executable, "-c", "pass"], stdout=kw["stdout"]))
    h = p.launch(1, "CPU", {}, "")[0]
    t = time.time()
    while time.time() - t < 5 and p.list()[0].status != STOPPED:
        time.sleep(0.05)
    assert p.list()[0].status == STOPPED and h.status == PENDING
