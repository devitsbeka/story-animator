"""Planner: free capacity first, paid overflow only to hit the deadline (and only when allowed)."""
from factory.compute import planner


def prov(pid, spf, conc, free=True, gpu=False, cold=10, build=20, runtime=900, ledger_free=None, usage_per_s=None,
         price_h=0.0, priority=50):
    return {"id": pid, "free": free, "priority": priority, "ledgerFree": ledger_free, "usagePerS": usage_per_s,
            "priceUsdPerS": price_h / 3600.0, "available": True, "concurrency": conc,
            "profile": {"gpu": gpu, "spf": {"preview": spf, "final": spf * 15}, "coldStartS": cold, "buildS": build,
                        "maxRuntimeS": runtime, "concurrency": conc}}


LAMBDA = prov("aws_lambda", 6.0, 10, ledger_free=380000, usage_per_s=10.0, priority=10)
LOCAL = prov("local_cpu", 11.0, 1, runtime=86400, priority=90)
RUNPOD = prov("runpod", 1.2, 4, free=False, gpu=True, cold=420, build=10, runtime=86400, price_h=0.69)


def test_free_only_when_free_meets_deadline():
    p = planner.plan(2416, "preview", [LAMBDA, LOCAL, RUNPOD], deadline_s=4 * 3600, allow_paid=True)
    assert p["feasible"] and p["usd"] == 0
    assert {r["provider"] for r in p["providers"]} == {"aws_lambda", "local_cpu"}
    assert sum(r["frames"] for r in p["providers"]) == 2416
    lam = next(r for r in p["providers"] if r["provider"] == "aws_lambda")
    assert lam["workers"] == 10 and lam["frames"] > 2000          # 10 Lambdas carry the bulk
    assert lam["secondsPerChunk"] <= 900 * 0.6


def test_paid_added_only_to_hit_deadline():
    p = planner.plan(2416, "preview", [LAMBDA, LOCAL, RUNPOD], deadline_s=20 * 60, allow_paid=True)
    assert any(r["provider"] == "runpod" for r in p["providers"]) and p["usd"] > 0
    assert p["expectedMin"] <= 20
    p2 = planner.plan(2416, "preview", [LAMBDA, LOCAL, RUNPOD], deadline_s=20 * 60, allow_paid=False)
    assert not p2["feasible"] and all(r["free"] for r in p2["providers"])
    assert any("allow-paid" in n for n in p2["notes"])


def test_quota_limits_frames_on_a_metered_provider():
    tight = dict(LAMBDA, ledgerFree=5000)        # GB-s left this month
    p = planner.plan(2416, "preview", [tight, LOCAL], deadline_s=None)
    lam = next(r for r in p["providers"] if r["provider"] == "aws_lambda")
    assert lam["usage"] <= 5000 + 1 and lam["frames"] < 100
    assert next(r for r in p["providers"] if r["provider"] == "local_cpu")["frames"] > 2000


def test_no_capacity_without_paid():
    empty = dict(LAMBDA, ledgerFree=0)
    p = planner.plan(500, "preview", [empty], deadline_s=600, allow_paid=False)
    assert not p["feasible"] and p["expectedMin"] is None


def test_final_prefers_gpu_and_skips_cpu_that_cannot_make_the_deadline():
    gpu_free = prov("member_node", 2.0, 2, gpu=True, priority=20)
    p = planner.plan(200, "final", [LAMBDA, gpu_free], deadline_s=60 * 60)
    ids = [r["provider"] for r in p["providers"]]
    assert ids[0] == "member_node"
    slow_cpu = prov("cpu", 30.0, 1, runtime=900)   # final 450 s/frame: one chunk takes > the 5 min deadline
    p2 = planner.plan(50, "final", [slow_cpu, gpu_free], deadline_s=5 * 60)
    assert all(r["provider"] != "cpu" for r in p2["providers"])


def test_small_job_spreads_over_all_workers():
    p = planner.plan(24, "preview", [LAMBDA], deadline_s=30 * 60)
    lam = p["providers"][0]
    assert lam["workers"] == 10 and lam["chunkFrames"] == 3     # ceil(24 / 10): 4 x 3 + 6 x 2 frames


def test_budget_breach_is_infeasible():
    p = planner.plan(5000, "preview", [RUNPOD], deadline_s=30 * 60, allow_paid=True, budget_usd=0.01)
    assert not p["feasible"] and any("budget" in n for n in p["notes"])
