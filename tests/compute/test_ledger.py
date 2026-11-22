"""Quota ledger: free tiers are never exceeded unless paid overflow is explicitly allowed."""
import threading

import pytest

from factory.compute.ledger import BudgetExceeded, Ledger, QuotaExceeded, period_id
from factory.compute.store import LocalDirStore, MemoryStore, S3Store

from conftest import BUCKET, MotoSafeS3Store

LAMBDA = {"unit": "GB-s", "free": 400000, "period": "month", "unit_usd": 0.0000166667}


def test_reserve_commit_within_free(clock):
    L = Ledger(MemoryStore(), clock=clock, safety=0.05)
    r = L.reserve("aws_lambda", LAMBDA, 10000)
    assert r["free"] == 10000 and r["paid"] == 0
    st = L.state("aws_lambda", LAMBDA)
    assert st["reserved"] == 10000 and st["remainingFree"] == 380000 - 10000
    L.commit("aws_lambda", LAMBDA, r["id"], 8000)
    st = L.state("aws_lambda", LAMBDA)
    assert st["used"] == 8000 and st["reserved"] == 0 and st["remainingFree"] == 372000


def test_free_tier_cap_refuses_without_paid(clock):
    L = Ledger(MemoryStore(), clock=clock, safety=0.05)
    L.reserve("aws_lambda", LAMBDA, 379000)
    with pytest.raises(QuotaExceeded):
        L.reserve("aws_lambda", LAMBDA, 2000)       # 95 % of 400k = 380k usable
    r = L.reserve("aws_lambda", LAMBDA, 1000)        # exactly fits
    assert r["paid"] == 0


def test_paid_overflow_only_when_allowed_and_within_budget(clock):
    L = Ledger(MemoryStore(), clock=clock, safety=0.0)
    L.commit("aws_lambda", LAMBDA, "x", 399000)
    r = L.reserve("aws_lambda", LAMBDA, 3000, allow_paid=True, unit_usd=LAMBDA["unit_usd"], budget=1.0)
    assert r["free"] == 1000 and r["paid"] == 2000 and r["usd"] == pytest.approx(2000 * LAMBDA["unit_usd"])
    with pytest.raises(BudgetExceeded):
        L.reserve("aws_lambda", LAMBDA, 10 ** 6, allow_paid=True, unit_usd=LAMBDA["unit_usd"], budget=1.0)
    ev = L.commit("aws_lambda", LAMBDA, r["id"], 3500, unit_usd=LAMBDA["unit_usd"])
    assert ev["free"] == 1000 and ev["paid"] == 2500
    assert L.state("aws_lambda", LAMBDA)["paidUsd"] == pytest.approx(2500 * LAMBDA["unit_usd"], rel=1e-3)


def test_observed_account_meter_counts_other_functions(clock):
    L = Ledger(MemoryStore(), clock=clock, safety=0.0)
    L.commit("aws_lambda", LAMBDA, "own", 1000)
    L.observe("aws_lambda", LAMBDA, 395000, source="cloudwatch")     # e.g. Remotion renders in the account
    assert L.state("aws_lambda", LAMBDA)["remainingFree"] == 5000
    with pytest.raises(QuotaExceeded):
        L.reserve("aws_lambda", LAMBDA, 6000)


def test_release_returns_reservation(clock):
    L = Ledger(MemoryStore(), clock=clock)
    r = L.reserve("p", {"unit": "h", "free": 10, "period": "week"}, 5)
    L.release("p", {"unit": "h", "free": 10, "period": "week"}, r["id"])
    assert L.state("p", {"unit": "h", "free": 10, "period": "week"})["reserved"] == 0


def test_periods_reset(clock):
    L = Ledger(MemoryStore(), clock=clock, safety=0.0)
    q = {"unit": "GPU-h", "free": 30, "period": "week"}
    L.commit("kaggle", q, "a", 30)
    assert L.remaining_free("kaggle", q) == 0
    clock.advance(7 * 86400)
    assert L.remaining_free("kaggle", q) == 30
    assert period_id("month", 1_800_000_000) == "2027-01"
    assert period_id("week", 1_800_000_000).startswith("2027-W")


@pytest.mark.parametrize("backend", ["memory", "dir", "s3"])
def test_concurrent_reservations_never_exceed(backend, request, tmp_path, clock):
    store = {"memory": MemoryStore, "dir": lambda: LocalDirStore(str(tmp_path / "led"))}.get(backend)
    store = store() if store else S3Store(request.getfixturevalue("s3"), BUCKET)
    q = {"unit": "GB-s", "free": 1000, "period": "month"}
    ok, refused, errors = [], [], []

    def go():
        import boto3
        mine = MotoSafeS3Store(boto3.client("s3", region_name="us-east-1"), BUCKET) if backend == "s3" else store
        L = Ledger(mine, clock=clock, safety=0.0, retries=200)      # one client per writer, like real processes
        for _ in range(5):
            try:
                ok.append(L.reserve("aws_lambda", q, 30)["free"])
            except QuotaExceeded:
                refused.append(1)
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))
    ts = [threading.Thread(target=go) for _ in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    assert sum(ok) <= 1000 and len(ok) == 33 and len(refused) == 17
    assert Ledger(store, clock=clock, safety=0.0).state("aws_lambda", q)["reserved"] == pytest.approx(990)
