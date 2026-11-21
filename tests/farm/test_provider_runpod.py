"""RunPod provider against a mocked REST v2 API (shapes from https://api.runpod.io/v2/openapi.json, 2026-11-21)."""
import pytest

from http_mock import MockTransport
from providers import AuthError, CapacityError, ProviderError, QuotaError, RUNNING, PENDING
from providers.runpod import RunPod
from providers.startup import bootstrap_command, decode_bootstrap

KEY = {"RUNPOD_API_KEY": "rp_test_key"}
CFG = {"max_workers": 4, "gpu_classes": ["RTX4090", "L40S"], "cloud": ["SECURE", "COMMUNITY"], "disk_gb": 40}


def gpu(gid, name, secure, community, avail="HIGH", on_secure=True):
    return {"id": gid, "name": name, "pool": "ADA_24", "manufacturer": "NVIDIA", "memory": 24, "secure": on_secure,
            "community": True, "price": {"secure": secure, "community": community},
            "maxCount": {"secure": 8, "community": 4}, "availability": avail}


def catalog(avail_4090="HIGH", avail_l40s="LOW"):
    return lambda call: (200, {"gpus": [gpu("NVIDIA GeForce RTX 4090", "RTX 4090", 0.69, 0.34, avail_4090),
                                        gpu("NVIDIA L40S", "L40S", 0.86, 0.79, avail_l40s),
                                        gpu("NVIDIA H100 80GB HBM3", "H100", 2.99, 2.69)]})


def pod(pid, name, status="PROVISIONING", gid="NVIDIA GeForce RTX 4090", cost=0.69):
    return {"id": pid, "name": name, "status": status, "actions": ["stop", "terminate"], "image": "x", "args": "",
            "disk": 40, "mounts": {}, "ports": [], "env": {}, "registry": None, "cloud": "SECURE",
            "dataCenterId": "US-TX-3", "cudaVersion": "12.8", "ssh": {}, "template": None, "cost": cost,
            "locked": False, "runtime": None, "createdAt": "2026-11-21T00:00:00Z", "startedAt": None,
            "globalNetworking": {}, "gpu": {"id": gid, "count": 1, "vcpuCount": 16, "memory": 64}}


@pytest.fixture
def api():
    t = MockTransport()
    t.route("GET", "/v2/catalog/gpus", catalog())
    n = {"i": 0}

    def create(call):
        n["i"] += 1
        return 201, pod(f"pod{n['i']}", call["json"]["name"], gid=call["json"]["gpu"]["id"])
    t.route("POST", "/v2/pods", create)
    return t


def rp(t, cfg=CFG, env=KEY):
    return RunPod(cfg, env, transport=t, sleep=lambda s: None)


def test_available_reads_catalog_with_availability(api):
    ok, reason = rp(api).available()
    assert ok and "RTX4090@SECURE" in reason
    calls = api.find("GET", "/v2/catalog/gpus")
    assert {c["query"]["cloud"] for c in calls} == {"SECURE", "COMMUNITY"}
    assert all(c["query"]["include"] == "AVAILABILITY" and c["query"]["product"] == "POD" for c in calls)
    assert calls[0]["headers"]["Authorization"] == "Bearer rp_test_key"


def test_no_key_and_no_stock_are_unavailable(api):
    assert rp(api, env={}).available() == (False, "RUNPOD_API_KEY not set")
    api.route("GET", "/v2/catalog/gpus", catalog("NONE", "NONE"))
    ok, reason = rp(api).available()
    assert not ok and "no stock" in reason


def test_bad_key_is_unavailable(api):
    api.route("GET", "/v2/catalog/gpus", (401, {"title": "Unauthorized", "status": 401, "detail": "invalid api key"}))
    ok, reason = rp(api).available()
    assert not ok and "auth" in reason


def test_price_is_cheapest_configured_cloud(api):
    p = rp(api)
    assert p.price_per_hour("RTX4090") == pytest.approx(0.34)   # community
    assert rp(api, {**CFG, "cloud": "SECURE"}).price_per_hour("L40S") == pytest.approx(0.86)


def test_launch_request_shape(api):
    startup = bootstrap_command("#!/bin/bash\necho hi\n")
    hs = rp(api).launch(2, "RTX4090", {"FARM_BUCKET": "b", "AWS_ACCESS_KEY_ID": "AKIA"}, startup)
    assert [h.id for h in hs] == ["pod1", "pod2"] and all(h.status == PENDING for h in hs)
    body = api.find("POST", "/v2/pods")[0]["json"]
    assert body["gpu"] == {"id": "NVIDIA GeForce RTX 4090", "count": 1}
    assert body["cloud"] == "SECURE" and body["disk"] == 40 and body["ports"] == []
    assert body["image"].startswith("nvidia/cuda:") and body["name"].startswith("story-farm-")
    assert body["env"] == {"FARM_BUCKET": "b", "AWS_ACCESS_KEY_ID": "AKIA"}
    assert body["entrypoint"] == ["/bin/bash", "-c"] and decode_bootstrap(body["cmd"][0]).endswith("echo hi\n")
    # only documented CreatePodRequest fields
    assert set(body) <= {"name", "image", "gpu", "cloud", "disk", "env", "entrypoint", "cmd", "ports", "args",
                         "registry", "dataCenterIds", "mounts", "templateId", "globalNetworking"}
    assert hs[0].worker_key == "runpod:pod1" and hs[0].price_per_hour == pytest.approx(0.69)


def test_capacity_400_tries_next_cloud_then_raises(api):
    def create(call):
        if call["json"]["cloud"] == "SECURE":
            return 400, {"title": "Bad Request", "status": 400,
                         "detail": "There are no longer any instances available with the requested specifications."}
        return 201, pod("podc", call["json"]["name"])
    api.route("POST", "/v2/pods", create)
    hs = rp(api).launch(1, "RTX4090", {}, "true")
    assert hs[0].id == "podc"
    assert [c["json"]["cloud"] for c in api.find("POST", "/v2/pods")] == ["SECURE", "COMMUNITY"]
    api.route("POST", "/v2/pods", (400, {"title": "Bad Request", "status": 400, "detail": "no capacity"}))
    with pytest.raises(CapacityError, match="no capacity"):
        rp(api).launch(1, "RTX4090", {}, "true")


def test_error_mapping(api):
    for status, exc in ((402, QuotaError), (401, AuthError), (422, ProviderError), (500, ProviderError)):
        api.route("POST", "/v2/pods", (status, {"title": "x", "status": status, "detail": f"err {status}"}))
        with pytest.raises(exc):
            rp(api, {**CFG, "cloud": "SECURE"}).launch(1, "L40S", {}, "true")


def test_429_and_5xx_are_retried(api):
    seq = iter([(429, {"title": "Too Many Requests", "status": 429, "detail": "rate"}),
                (503, {"title": "x", "status": 503, "detail": "busy"}), (201, pod("pod9", "story-farm-w-x-0"))])
    api.route("POST", "/v2/pods", lambda c: next(seq))
    assert rp(api, {**CFG, "cloud": "SECURE"}).launch(1, "RTX4090", {}, "true")[0].id == "pod9"


def test_partial_launch_returns_what_it_got(api):
    seq = iter([(201, pod("p1", "story-farm-a")), (400, {"title": "b", "status": 400, "detail": "no capacity"}),
                (400, {"title": "b", "status": 400, "detail": "no capacity"})])
    api.route("POST", "/v2/pods", lambda c: next(seq))
    assert [h.id for h in rp(api).launch(3, "RTX4090", {}, "true")] == ["p1"]


def test_list_filters_farm_pods_and_paginates(api):
    pages = {None: {"pods": [pod("a", "story-farm-w-rtx4090-0", "RUNNING"), pod("b", "someone-elses-notebook")],
                    "pagination": {"nextCursor": "c2"}},
             "c2": {"pods": [pod("c", "story-farm-w-l40s-1", "EXITED", "NVIDIA L40S")], "pagination": {}}}
    api.route("GET", "/v2/pods", lambda call: (200, pages[call["query"].get("cursor")]))
    hs = rp(api).list()
    assert [(h.id, h.status, h.gpu_class) for h in hs] == [("a", RUNNING, "RTX4090"), ("c", "STOPPED", "L40S")]


def test_terminate_uses_delete_and_tolerates_404(api):
    api.route("DELETE", "/v2/pods/[^/]+", lambda c: (404, None) if c["path"].endswith("gone") else (204, None))
    assert rp(api).terminate(["p1", "gone"]) == ["p1", "gone"]
    assert [c["path"] for c in api.find("DELETE", "/v2/pods/.*")] == ["/v2/pods/p1", "/v2/pods/gone"]


def test_interruptible_uses_graphql_then_falls_back(api):
    cfg = {**CFG, "interruptible": True, "bid_per_gpu": 0.25, "cloud": "COMMUNITY"}
    api.route("POST", "/graphql", lambda c: (200, {"data": {"podRentInterruptable": {
        "id": "spot1", "costPerHr": 0.25, "desiredStatus": "RUNNING"}}}))
    h = rp(api, cfg).launch(1, "RTX4090", {"A": "1"}, "true", spot=True)[0]
    assert h.id == "spot1" and h.spot
    q = api.find("POST", "/graphql")[0]["json"]
    inp = q["variables"]["input"]
    assert "podRentInterruptable" in q["query"] and inp["bidPerGpu"] == 0.25 and inp["gpuTypeId"].endswith("4090")
    assert inp["cloudType"] == "COMMUNITY" and inp["env"] == [{"key": "A", "value": "1"}]
    api.route("POST", "/graphql", (200, {"errors": [{"message": "There are no longer any instances available"}]}))
    h = rp(api, cfg).launch(1, "RTX4090", {}, "true", spot=True)[0]
    assert not h.spot and h.id.startswith("pod")   # fell back to on-demand REST
