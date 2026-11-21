"""scheduler.py fallback / health / budget / rebalance scenarios with the real provider classes over fakes.

AWS = fake service-quotas + autoscaling clients, RunPod + Vast = mocked HTTP APIs that keep pod state, local =
real sleeper child processes. A fake clock drives timeouts; heartbeats are a dict the test writes, standing in for
the pk=WORKER items worker.py puts in DynamoDB. Nothing touches the network or spends money."""
import copy
import os
import subprocess
import sys

import pytest

import scheduler as sched
from fakes import aws_clients
from http_mock import MockTransport
from providers import make

FARM = {"bucket": "farm-b", "queue_url": "https://sqs.us-east-1.amazonaws.com/1/q", "table": "farm-t",
        "region": "us-east-1"}
SECRETS = {"AWS_ACCESS_KEY_ID": "AKIAEXTERNAL", "AWS_SECRET_ACCESS_KEY": "s3cr3t/x+y", "GIT_TOKEN": ""}
CODE = {"FARM_CODE_SOURCE": "git", "FARM_GIT_URL": "https://github.com/o/r.git", "FARM_GIT_COMMIT": "a" * 40}


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class RunPodAPI(MockTransport):
    def __init__(self, stock="HIGH", create_status=201):
        super().__init__()
        self.pods, self.stock, self.create_status, self.n = {}, stock, create_status, 0
        self.route("GET", "/v2/catalog/gpus", lambda c: (200, {"gpus": [
            {"id": "NVIDIA GeForce RTX 4090", "secure": True, "community": True, "availability": self.stock,
             "price": {"secure": 0.69, "community": 0.59}},
            {"id": "NVIDIA L40S", "secure": True, "community": True, "availability": self.stock,
             "price": {"secure": 0.86, "community": 0.79}}]}))
        self.route("POST", "/v2/pods", self.create)
        self.route("GET", "/v2/pods", lambda c: (200, {"pods": list(self.pods.values()), "pagination": {}}))
        self.route("DELETE", "/v2/pods/[^/]+", self.delete)

    def create(self, call):
        if self.create_status != 201:
            return self.create_status, {"title": "Bad Request", "status": self.create_status,
                                        "detail": "There are no longer any instances available"}
        self.n += 1
        pid = f"rp{self.n}"
        b = call["json"]
        self.pods[pid] = {"id": pid, "name": b["name"], "status": "PROVISIONING", "cost": 0.69,
                          "gpu": {"id": b["gpu"]["id"], "count": 1}, "cloud": b["cloud"], "env": b["env"]}
        return 201, self.pods[pid]

    def delete(self, call):
        self.pods.pop(call["path"].rsplit("/", 1)[1], None)
        return 204, None


class VastAPI(MockTransport):
    def __init__(self, offers=True):
        super().__init__()
        self.instances, self.has_offers = {}, offers
        self.route("GET", "/api/v0/users/current", (200, {"balance": 20}))
        self.route("POST", "/api/v0/bundles", lambda c: (200, {"offers": [
            {"id": 501, "gpu_name": "RTX 4090", "dph_total": 0.40, "min_bid": 0.2, "reliability": 0.99},
            {"id": 502, "gpu_name": "RTX 4090", "dph_total": 0.42, "min_bid": 0.2, "reliability": 0.99},
            {"id": 503, "gpu_name": "RTX 4090", "dph_total": 0.44, "min_bid": 0.2, "reliability": 0.99}]
            if self.has_offers and "RTX 4090" in c["json"]["gpu_name"]["in"] else []}))
        self.route("PUT", r"/api/v0/asks/\d+", self.create)
        self.route("GET", "/api/v1/instances", lambda c: (200, {"instances": list(self.instances.values()),
                                                                "next_token": None}))
        self.route("DELETE", r"/api/v0/instances/\d+", self.delete)

    def create(self, call):
        iid = 900 + len(self.instances) + 1
        self.instances[str(iid)] = {"id": iid, "label": call["json"]["label"], "actual_status": "loading",
                                    "gpu_name": "RTX 4090", "dph_total": 0.40, "env": call["json"]["env"]}
        return 200, {"success": True, "new_contract": iid}

    def delete(self, call):
        self.instances.pop(call["path"].rsplit("/", 1)[1], None)
        return 200, {"success": True}


def sleeper(argv, **kw):
    kw.pop("env", None)
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], **kw)


@pytest.fixture
def world(tmp_path):
    cfg = sched.load_config()
    cfg = copy.deepcopy(cfg)
    cfg["budget"] = {"max_usd_per_hour": 6.0, "max_total_usd": 80.0}
    clock = Clock()
    clients, asg = aws_clients(spot=0, ondemand=0)
    rp_api, vast_api = RunPodAPI(), VastAPI()
    hb = {}
    w = {"cfg": cfg, "clock": clock, "clients": clients, "asg": asg, "rp": rp_api, "vast": vast_api, "hb": hb,
         "tmp": tmp_path}

    def build(env=None):
        env = {"RUNPOD_API_KEY": "rk", "VAST_API_KEY": "vk"} if env is None else env
        c = w["cfg"]
        provs = {"aws_ec2": make("aws_ec2", c["providers"]["aws_ec2"], {}, clients=clients, now=clock),
                 "runpod": make("runpod", c["providers"]["runpod"], env, transport=rp_api, sleep=lambda s: None),
                 "vastai": make("vastai", c["providers"]["vastai"], env, transport=vast_api, sleep=lambda s: None),
                 "local": make("local", c["providers"]["local"], {}, state_dir=str(tmp_path), popen=sleeper)}
        return sched.Scheduler(c, provs, FARM, SECRETS, heartbeats=lambda: hb,
                               state_path=str(tmp_path / "scheduler.json"), now=clock, code=CODE)
    w["build"] = build
    yield w
    # never leave sleeper processes behind
    build().stop_all("test teardown")


def beat(world, key, state="idle", age=0):
    world["hb"][key] = {"sk": key, "t": world["clock"]() - age, "state": state}


def providers_of(res):
    return [x["worker"].split(":")[0] for x in res["launched"]]


def test_aws_quota_zero_falls_back_to_runpod(world):
    s = world["build"]()
    res = s.tick(backlog_jobs=10, backlog_gpu_s=10 * 3600)      # 10 A10G-hours / 2 h target = 5 units
    assert "quota is 0" in res["unavailable"]["aws_ec2"]
    assert providers_of(res) == ["runpod", "runpod"]           # 2 x RTX4090 = 5.0 units
    assert world["asg"].desired_calls == []
    body = world["rp"].find("POST", "/v2/pods")[0]["json"]
    assert body["gpu"]["id"] == "NVIDIA GeForce RTX 4090"
    assert body["env"]["FARM_QUEUE_URL"] == FARM["queue_url"] and body["env"]["AWS_ACCESS_KEY_ID"] == "AKIAEXTERNAL"
    assert body["env"]["FARM_PROVIDER"] == "runpod" and body["env"]["FARM_GPU_CLASS"] == "RTX4090"
    assert sched.startup.decode_bootstrap(body["cmd"][0]).count("FARM_GIT_COMMIT=" + "a" * 40) == 1
    assert res["usdPerHour"] == pytest.approx(1.38)


def test_runpod_capacity_error_falls_back_to_vast(world):
    world["rp"].create_status = 400
    s = world["build"]()
    res = s.tick(10, 10 * 3600)
    assert providers_of(res) == ["vastai", "vastai"]
    cd = s.state["cooldown"]
    assert cd["runpod/RTX4090/ondemand"]["kind"] == "capacity" and cd["runpod/L40S/ondemand"]["kind"] == "capacity"
    env = world["vast"].find("PUT", r"/api/v0/asks/\d+")[0]["json"]["env"]
    assert "-e FARM_PROVIDER=vastai" in env and "-e AWS_SECRET_ACCESS_KEY=s3cr3t/x+y" in env
    # cooldown holds: the next tick does not hammer RunPod again
    n = len(world["rp"].find("POST", "/v2/pods"))
    world["clock"].advance(60)
    s.tick(10, 10 * 3600)
    assert len(world["rp"].find("POST", "/v2/pods")) == n


def test_all_gpu_providers_down_falls_back_to_local(world):
    world["rp"].stock = "NONE"
    world["vast"].has_offers = False
    s = world["build"]()
    res = s.tick(4)
    assert providers_of(res) == ["local"]
    assert set(res["unavailable"]) == {"aws_ec2", "runpod", "vastai"}
    assert len(s.providers["local"].list()) == 1


def test_missing_keys_mean_unavailable_not_crash(world):
    s = world["build"](env={})
    s.secrets = {}
    res = s.tick(4)
    assert "RUNPOD_API_KEY not set" in res["unavailable"]["runpod"] or "keys not set" in res["unavailable"]["runpod"]
    assert providers_of(res) == ["local"]


def test_unhealthy_worker_is_replaced_by_next_provider(world):
    s = world["build"]()
    res = s.tick(2, 2 * 3600)                                  # 1 unit -> one RTX4090 pod
    assert providers_of(res) == ["runpod"]
    world["clock"].advance(s.sc["health_timeout_s"] + 1)       # never heartbeats
    res = s.tick(2, 2 * 3600)
    assert [t["worker"] for t in res["terminated"]] == ["runpod:rp1"] and "no heartbeat" in res["terminated"][0]["reason"]
    assert world["rp"].find("DELETE", "/v2/pods/rp1")         # terminated through the API
    assert s.state["cooldown"]["runpod/RTX4090/ondemand"]["kind"] == "unhealthy"
    # same tick: L40S on RunPod is the next option (still RunPod, different GPU class)
    assert [x["option"] for x in res["launched"]] == ["runpod/L40S/ondemand"]
    assert list(world["rp"].pods) == ["rp2"] and "l40s" in world["rp"].pods["rp2"]["name"]


def test_healthy_then_idle_worker_is_terminated_when_queue_empty(world):
    s = world["build"]()
    s.tick(2, 2 * 3600)
    key = "runpod:rp1"
    world["rp"].pods["rp1"]["status"] = "RUNNING"
    world["clock"].advance(300)
    beat(world, key, "rendering")
    s.tick(2, 2 * 3600)
    assert s.state["workers"][key]["healthyAt"] and s.state["workers"][key]["status"] == "RUNNING"
    world["clock"].advance(120)
    beat(world, key, "idle")
    res = s.tick(0)                                            # queue empty but only idle 120 s
    assert res["terminated"] == []
    world["clock"].advance(s.sc["idle_terminate_s"])
    beat(world, key, "idle")
    res = s.tick(0)
    assert [t["worker"] for t in res["terminated"]] == [key] and "idle" in res["terminated"][0]["reason"]


def test_lost_heartbeat_kills_worker(world):
    s = world["build"]()
    s.tick(2, 2 * 3600)
    beat(world, "runpod:rp1", "rendering")
    s.tick(2, 2 * 3600)
    world["clock"].advance(s.sc["heartbeat_lost_s"] + 5)      # heartbeat item now stale
    res = s.tick(2, 2 * 3600)
    assert res["terminated"][0]["reason"] == "heartbeat lost"


def test_hourly_budget_caps_the_fleet(world):
    world["cfg"]["budget"]["max_usd_per_hour"] = 1.0
    s = world["build"]()
    res = s.tick(20, 40 * 3600)                                # would want 8 workers
    assert len(res["launched"]) == 1 and res["usdPerHour"] <= 1.0


def test_total_budget_ceiling_stops_everything(world):
    world["cfg"]["budget"]["max_total_usd"] = 2.0
    s = world["build"]()
    s.tick(10, 10 * 3600)                                      # 2 pods x $0.69/h
    world["clock"].advance(3600)
    beat(world, "runpod:rp1", "rendering")
    beat(world, "runpod:rp2", "rendering")
    s.tick(10, 10 * 3600)
    assert s.state["spentUsd"] == pytest.approx(1.38, abs=0.01)
    world["clock"].advance(1800)
    beat(world, "runpod:rp1", "rendering")
    beat(world, "runpod:rp2", "rendering")
    res = s.tick(10, 10 * 3600)
    assert s.state["spentUsd"] >= 2.0 and len(res["terminated"]) == 2 and res["launched"] == []
    assert world["rp"].pods == {} and s.state["events"][-1]["event"] == "budget_exhausted"
    assert s.state["spentByProvider"]["runpod"] == pytest.approx(s.state["spentUsd"])


def test_per_provider_max_workers_spills_to_next_provider(world):
    world["cfg"]["providers"]["runpod"]["max_workers"] = 1
    s = world["build"]()
    res = s.tick(10, 10 * 3600)
    assert providers_of(res) == ["runpod", "vastai"]


def test_rebalance_moves_from_local_to_aws_when_quota_arrives(world):
    for p in ("runpod", "vastai"):
        world["cfg"]["providers"][p]["enabled"] = False
    s = world["build"]()
    res = s.tick(2)
    assert providers_of(res) == ["local"]
    local_key = res["launched"][0]["worker"]
    beat(world, local_key, "rendering")
    world["clock"].advance(60)
    s.tick(2)
    # quota approved: AWS becomes available, scheduler launches a replacement
    world["clients"]["service-quotas"].values.update({"L-3819A6DF": 8, "L-DB2E81BA": 8})
    world["clock"].advance(60)
    beat(world, local_key, "rendering")
    res = s.tick(2)
    assert providers_of(res) == ["aws_ec2"] and res["launched"][0]["why"] == f"rebalance:{local_key}"
    assert world["asg"].desired_calls == [("story-farm-spot-workers", 1)]
    # the instance boots, is adopted in place of the placeholder and heartbeats; local finishes its job -> idle
    world["asg"].boot("story-farm-spot-workers", "i-0abc")
    world["clock"].advance(240)
    beat(world, "aws_ec2:i-0abc", "idle")
    beat(world, local_key, "rendering")
    res = s.tick(2)
    assert "aws_ec2:i-0abc" in s.live() and res["terminated"] == []   # local is busy: not cut mid-job
    world["clock"].advance(60)
    beat(world, local_key, "idle")
    beat(world, "aws_ec2:i-0abc", "rendering")
    res = s.tick(2)
    assert [t["worker"] for t in res["terminated"]] == [local_key] and "rebalanced" in res["terminated"][0]["reason"]
    assert list(s.live()) == ["aws_ec2:i-0abc"]


def test_local_not_used_while_gpu_workers_exist(world):
    world["cfg"]["providers"]["runpod"]["max_workers"] = 1
    world["vast"].has_offers = False
    s = world["build"]()
    res = s.tick(10, 20 * 3600)
    assert providers_of(res) == ["runpod"]                     # deficit remains, but local stays off


def test_cheapest_strategy_ranks_by_dollars_per_speed(world):
    world["cfg"]["strategy"] = "cheapest"
    s = world["build"]()
    keys = [o.key for o in s.options()]
    assert keys[-1].startswith("local/")
    assert keys.index("vastai/RTX4090/ondemand") < keys.index("runpod/RTX4090/ondemand")
    res = s.tick(2, 2 * 3600)
    assert providers_of(res) == ["vastai"]


def test_state_survives_restart_and_status_reports_providers(world):
    s = world["build"]()
    s.tick(2, 2 * 3600)
    s2 = world["build"]()
    st = s2.status()
    rows = {r["provider"]: r for r in st["providers"]}
    assert rows["runpod"]["live"] == 1 and rows["aws_ec2"]["live"] == 0
    assert any(e["event"] == "launched" for e in st["recentEvents"])
    assert os.path.isfile(world["tmp"] / "scheduler.json")


def test_exited_container_is_removed_and_option_cooled(world):
    s = world["build"]()
    s.tick(2, 2 * 3600)
    world["rp"].pods["rp1"]["status"] = "EXITED"              # crashed during boot (e.g. bad code checkout)
    world["clock"].advance(120)
    res = s.tick(2, 2 * 3600)
    assert res["terminated"][0] == {"worker": "runpod:rp1", "reason": "container stopped"}
    assert "rp1" not in world["rp"].pods and s.state["cooldown"]["runpod/RTX4090/ondemand"]["kind"] == "unhealthy"
    assert [x["option"] for x in res["launched"]] == ["runpod/L40S/ondemand"]


def test_plan_table_uses_speed_and_calibration(world):
    cfg = world["cfg"]
    provs = sched.build_providers(cfg, env={}, offline=True, state_dir=str(world["tmp"]))
    rows = {r["option"]: r for r in sched.plan_table(cfg, provs, 10.0)}
    assert rows["runpod/RTX4090/ondemand"]["gpuHours"] == pytest.approx(4.0)        # 10 / 2.5
    assert rows["aws_ec2/L4/spot"]["usd"] == pytest.approx(10 / 0.9 * 0.60, abs=0.01)
    cal = sched.speed_calibration_from_manifests([
        {"status": "DONE", "gpuClass": "A10G", "estSeconds": 900, "gpuSeconds": 1000},
        {"status": "DONE", "gpuClass": "RTX4090", "estSeconds": 900, "gpuSeconds": 300},
        {"status": "FAILED", "gpuClass": "RTX4090", "estSeconds": 900, "gpuSeconds": 10}])
    assert cal == {"A10G": 1.0, "RTX4090": 3.333}
