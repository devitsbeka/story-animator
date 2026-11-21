"""Vast.ai provider against a mocked REST API (shapes from docs.vast.ai/api-reference, read 2026-11-21)."""
import pytest

from http_mock import MockTransport
from providers import AuthError, CapacityError, ProviderError, QuotaError, PENDING, RUNNING
from providers.vastai import VastAI

KEY = {"VAST_API_KEY": "vast_test_key"}
CFG = {"max_workers": 4, "gpu_classes": ["RTX4090", "L40S"], "min_reliability": 0.98, "max_dph": 0.9,
       "disk_gb": 40, "spot": "never"}


def offer(oid, gpu="RTX 4090", dph=0.41, min_bid=0.2, rel=0.995):
    return {"id": oid, "ask_contract_id": oid, "machine_id": 9000 + oid, "gpu_name": gpu, "num_gpus": 1,
            "dph_total": dph, "min_bid": min_bid, "reliability": rel, "cuda_max_good": 12.8, "disk_space": 200,
            "inet_down": 900, "verified": True, "rentable": True}


@pytest.fixture
def api():
    t = MockTransport()
    t.route("GET", "/api/v0/users/current", (200, {"id": 1, "balance": 12.5, "email": "x"}))

    def search(call):
        names = call["json"]["gpu_name"]["in"]
        offers = [offer(11, "RTX 4090", 0.45), offer(12, "RTX 4090", 0.38), offer(13, "RTX 3090", 0.2)]
        return 200, {"offers": [o for o in offers if o["gpu_name"] in names] if "RTX 4090" in names else []}
    t.route("POST", "/api/v0/bundles", search)
    n = {"i": 0}

    def create(call):
        n["i"] += 1
        return 200, {"success": True, "new_contract": 7000 + n["i"]}
    t.route("PUT", r"/api/v0/asks/\d+", create)
    return t


def vast(t, cfg=CFG, env=KEY):
    return VastAI(cfg, env, transport=t, sleep=lambda s: None)


def test_search_request_shape(api):
    offers = vast(api).offers("RTX4090")
    assert [o["id"] for o in offers] == [12, 11]             # cheapest first, 3090 filtered out
    q = api.find("POST", "/api/v0/bundles")[0]
    b = q["json"]
    assert q["headers"]["Authorization"] == "Bearer vast_test_key"
    assert b["gpu_name"] == {"in": ["RTX 4090"]} and b["num_gpus"] == {"eq": 1}
    assert b["reliability"] == {"gte": 0.98} and b["dph_total"] == {"lte": 0.9}
    assert b["rentable"] == {"eq": True} and b["verified"] == {"eq": True} and b["rented"] == {"eq": False}
    assert b["type"] == "ondemand" and b["order"] == [["dph_total", "asc"]] and b["limit"] > 0
    assert vast(api).offer_query("RTX4090", spot=True)["type"] == "bid"


def test_available(api):
    ok, reason = vast(api).available()
    assert ok and "RTX4090" in reason and "0.380" in reason
    assert vast(api, env={}).available() == (False, "VAST_API_KEY not set")
    api.route("GET", "/api/v0/users/current", (200, {"balance": 0}))
    assert not vast(api).available()[0]
    api.route("GET", "/api/v0/users/current", (200, {"balance": 5}))
    api.route("POST", "/api/v0/bundles", (200, {"offers": []}))
    ok, reason = vast(api).available()
    assert not ok and "no matching offers" in reason


def test_create_request_shape(api):
    hs = vast(api).launch(2, "RTX4090", {"FARM_BUCKET": "b", "AWS_SECRET_ACCESS_KEY": "ab/c+d="}, "echo boot")
    assert [h.id for h in hs] == ["7001", "7002"] and all(h.status == PENDING for h in hs)
    puts = api.find("PUT", r"/api/v0/asks/\d+")
    assert [c["path"] for c in puts] == ["/api/v0/asks/12", "/api/v0/asks/11"]
    b = puts[0]["json"]
    assert b["runtype"] == "args" and b["args"] == ["bash", "-c", "echo boot"]
    assert b["env"] == "-e FARM_BUCKET=b -e AWS_SECRET_ACCESS_KEY=ab/c+d="
    assert b["disk"] == 40 and b["label"].startswith("story-farm-") and b["image"].startswith("nvidia/cuda:")
    assert "price" not in b and b["cancel_unavail"] is True
    assert hs[0].price_per_hour == pytest.approx(0.38) and hs[0].worker_key == "vastai:7001"


def test_bid_sets_price_from_min_bid(api):
    h = vast(api, {**CFG, "spot": "first", "bid_markup": 1.5}).launch(1, "RTX4090", {}, "x", spot=True)[0]
    b = api.find("PUT", r"/api/v0/asks/\d+")[0]["json"]
    assert b["price"] == pytest.approx(0.3) and h.spot and h.price_per_hour == pytest.approx(0.3)


def test_gone_offer_moves_to_next_and_all_gone_is_capacity(api):
    seq = iter([(410, {"success": False, "error": "no_such_ask", "msg": "offer gone"}),
                (200, {"success": True, "new_contract": 42})])
    api.route("PUT", r"/api/v0/asks/\d+", lambda c: next(seq))
    assert [h.id for h in vast(api).launch(1, "RTX4090", {}, "x")] == ["42"]
    api.route("PUT", r"/api/v0/asks/\d+", (410, {"success": False, "error": "no_such_ask"}))
    with pytest.raises(CapacityError, match="every offer failed"):
        vast(api).launch(1, "RTX4090", {}, "x")
    with pytest.raises(CapacityError, match="no offers"):
        vast(api).launch(1, "L40S", {}, "x")


def test_error_mapping(api):
    api.route("PUT", r"/api/v0/asks/\d+", (400, {"success": False, "error": "insufficient_credit", "msg": "pay"}))
    with pytest.raises(QuotaError):
        vast(api).launch(1, "RTX4090", {}, "x")
    api.route("POST", "/api/v0/bundles", (401, {"success": False, "error": "auth", "msg": "bad key"}))
    with pytest.raises(AuthError):
        vast(api).launch(1, "RTX4090", {}, "x")
    api.route("POST", "/api/v0/bundles", (500, {"msg": "oops"}))
    with pytest.raises(ProviderError):
        vast(api).launch(1, "RTX4090", {}, "x")


def test_env_must_be_shell_safe():
    with pytest.raises(ProviderError, match="shell-safe"):
        VastAI.env_string({"A": "has space"})
    with pytest.raises(ProviderError):
        VastAI.env_string({"A": "x;rm -rf /"})


def test_list_and_destroy(api):
    pages = {None: {"success": True, "instances": [
        {"id": 1, "label": "story-farm-w-rtx4090-0", "actual_status": "running", "gpu_name": "RTX 4090",
         "dph_total": 0.4, "is_bid": False},
        {"id": 2, "label": "my-own-box", "actual_status": "running", "gpu_name": "RTX 4090"}], "next_token": "t2"},
        "t2": {"success": True, "instances": [{"id": 3, "label": "story-farm-w-l40s-0", "actual_status": "loading",
                                               "gpu_name": "L40S", "dph_total": 0.8}], "next_token": None}}
    api.route("GET", "/api/v1/instances", lambda c: (200, pages[c["query"].get("after_token")]))
    assert [(h.id, h.status, h.gpu_class) for h in vast(api).list()] == [("1", RUNNING, "RTX4090"),
                                                                        ("3", PENDING, "L40S")]
    api.route("DELETE", r"/api/v0/instances/\d+", (200, {"success": True, "msg": "Instance destroyed successfully"}))
    assert vast(api).terminate(["1", "3"]) == ["1", "3"]
    assert [c["path"] for c in api.find("DELETE", r"/api/v0/instances/\d+")] == ["/api/v0/instances/1",
                                                                                 "/api/v0/instances/3"]
