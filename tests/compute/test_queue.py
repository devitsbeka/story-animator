"""Work-stealing queue: lease races, steals, chunk sizing, capability gating, speculation, dedupe."""
import threading
import time

import pytest

from factory.compute.store import MemoryStore
from factory.compute.workqueue import WorkQueue, make_atoms

from compute_testkit import BUCKET, MotoSafeS3Store


def jobs(n_shots=2, frames=12, quality="preview"):
    out = []
    for i in range(n_shots):
        a = i * 100
        out.append({"shot": f"S{i}", "frameStart": a, "frameEnd": a + frames - 1, "quality": quality,
                    "engine": "CYCLES", "estSecondsPerFrame": 3.0})
    return out


def worker(wid, spf=5.0, gpu=False, provider="p", **kw):
    return {"id": wid, "provider": provider, "gpu": gpu, "spf": {"preview": spf, "final": spf * 20},
            "buildS": 10, "coldStartS": 0, **kw}


def test_atoms_never_cross_a_cut_and_cover_every_frame():
    atoms = make_atoms(jobs(3, 10), 4)
    assert [a["frames"] for a in atoms] == [4, 4, 2] * 3
    assert all(a["frameEnd"] - a["frameStart"] + 1 == a["frames"] for a in atoms)
    assert sum(a["frames"] for a in atoms) == 30


@pytest.mark.parametrize("backend", ["memory", "s3"])
def test_lease_race_each_atom_owned_once(backend, request, clock):
    store = MemoryStore() if backend == "memory" else MotoSafeS3Store(request.getfixturevalue("s3"), BUCKET, "q")
    q = WorkQueue(store, "run1", clock=clock)
    q.init(make_atoms(jobs(2, 16), 2))
    owners = {}
    lock = threading.Lock()
    lost = []
    start = threading.Barrier(8)
    real = store.put_if_absent

    def slow_put(key, data):          # widen the window between "looks free" and the conditional write
        time.sleep(0.002)
        return real(key, data)
    store.put_if_absent = slow_put

    def grab(i):
        mine = WorkQueue(store, "run1", clock=clock)
        start.wait()
        while True:
            got = mine.claim(worker(f"w{i}"), max_frames=2)
            if not got:
                lost.append(mine.stats["lostRaces"])
                return
            with lock:
                for L in got:
                    assert L.atom not in owners, f"{L.atom} claimed twice"
                    owners[L.atom] = L.worker
    ts = [threading.Thread(target=grab, args=(i,)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(owners) == len(q.atoms()) == 16
    assert sum(lost) > 0                          # and workers really did collide (and lost cleanly)


def test_expired_lease_is_stolen_with_next_generation(clock):
    q = WorkQueue(MemoryStore(), "r", clock=clock, lease_s=60)
    q.init(make_atoms(jobs(1, 4), 4))
    [a] = q.claim(worker("slow"))
    assert a.gen == 0 and q.claim(worker("other")) == []
    clock.advance(30)
    assert q.heartbeat(a)                          # holder extends
    clock.advance(45)
    assert q.claim(worker("other")) == []          # still live thanks to the heartbeat
    clock.advance(61)
    [b] = q.claim(worker("other"))
    assert b.gen == 1 and b.worker == "other"
    assert not q.heartbeat(a) or q.lease_record(a.atom, 0)[0]["worker"] == "slow"
    assert q.progress()["steals"] == 1


def test_release_requeues_and_failures_park_an_atom(clock):
    q = WorkQueue(MemoryStore(), "r", clock=clock, max_failures=2)
    q.init(make_atoms(jobs(1, 2), 2))
    for i in range(2):
        [L] = q.claim(worker(f"w{i}"))
        q.release(L, reason="boom")
    assert q.claim(worker("w9")) == []
    assert q.progress()["parked"] == ["S0-f00000-00001"]


def test_chunk_size_follows_the_worker():
    q = WorkQueue(MemoryStore(), "r")
    q.init(make_atoms(jobs(1, 24), 2))
    small = q.claim(worker("lambda"), max_frames=4)
    big = q.claim(worker("pod"), max_frames=16)
    assert sum(L.record["frames"] for L in small) == 4
    assert sum(L.record["frames"] for L in big) == 16
    # contiguous and same shot
    fr = [(L.record["frameStart"], L.record["frameEnd"]) for L in big]
    assert all(fr[i][1] + 1 == fr[i + 1][0] for i in range(len(fr) - 1))
    # max_s caps by time: 10 s build + 5 s/frame within 25 s -> 1 atom (2 frames: 20 s); a 2nd would be 30 s
    rest = q.claim(worker("tiny"), max_s=25)
    assert sum(L.record["frames"] for L in rest) == 2


def test_work_stealing_fast_worker_takes_more(clock):
    """Two providers pull from one queue: the 4x faster one ends up with ~4x the frames."""
    q = WorkQueue(MemoryStore(), "r", clock=clock)
    q.init(make_atoms(jobs(1, 100), 2))
    fast, slow = worker("fast", spf=1.0, buildS=0), worker("slow", spf=4.0, buildS=0)
    busy = {"fast": 0.0, "slow": 0.0}
    held = {}
    done = {"fast": 0, "slow": 0}
    while not q.progress()["complete"]:
        for w in (fast, slow):
            if w["id"] in held and clock() >= busy[w["id"]]:
                for L in held.pop(w["id"]):
                    q.complete(L, {})
                    done[w["id"]] += L.record["frames"]
            if w["id"] not in held:
                got = q.claim(w, max_frames=2)
                if got:
                    held[w["id"]] = got
                    busy[w["id"]] = clock() + q.est(w, [L.record for L in got])
        clock.advance(1)
    assert done["fast"] + done["slow"] == 100
    assert 3.0 <= done["fast"] / done["slow"] <= 5.0


def test_final_on_cpu_only_when_deadline_allows(clock):
    q = WorkQueue(MemoryStore(), "r", clock=clock)
    q.init(make_atoms(jobs(1, 4, "final"), 4), {"cpu_final": "deadline", "deadline_t": clock() + 100})
    cpu = worker("cpu", spf=50)                       # 10 + 4*1000 s >> 100 s
    assert q.claim(cpu) == []
    assert q.claim(worker("gpu", gpu=True))
    q2 = WorkQueue(MemoryStore(), "r2", clock=clock)
    q2.init(make_atoms(jobs(1, 4, "final"), 4), {"cpu_final": "deadline", "deadline_t": clock() + 10 ** 6})
    assert q2.claim(cpu)
    q3 = WorkQueue(MemoryStore(), "r3", clock=clock)
    q3.init(make_atoms(jobs(1, 4, "final"), 4), {"cpu_final": "never"})
    assert q3.claim(worker("cpu", spf=0.001)) == []


def test_ram_and_quality_limits(clock):
    q = WorkQueue(MemoryStore(), "r", clock=clock)
    js = jobs(1, 4)
    js[0]["minRamGb"] = 16
    q.init(make_atoms(js, 4))
    assert q.claim(worker("small", ramGb=8)) == []
    assert q.claim(worker("member", ramGb=32, qualities=["final"])) == []
    assert q.claim(worker("big", ramGb=32))


def test_straggler_speculation_first_result_wins(clock):
    q = WorkQueue(MemoryStore(), "r", clock=clock, lease_s=10_000)
    q.init(make_atoms(jobs(1, 4), 4))
    slow = worker("slow", spf=100.0)
    [a] = q.claim(slow)                                  # est 10 + 400 s
    fast = worker("fast", spf=1.0, provider="gpu-pod")   # another provider: no 2x-overdue rule
    assert q.claim(fast) == []                           # nothing unclaimed ...
    [s] = q.speculate(fast)                              # ... so the fast one copies the straggler
    assert s.spec and s.atom == a.atom
    assert q.speculate(worker("fast2", spf=1.0, provider="gpu-pod")) == []   # at most one copy per generation
    assert q.complete(s, {"by": "fast"}) is True
    assert q.complete(a, {"by": "slow"}) is False        # the straggler's result is a duplicate
    assert q.result(a.atom)["by"] == "fast"
    assert q.progress()["complete"]


def test_no_speculation_when_it_would_not_help(clock):
    q = WorkQueue(MemoryStore(), "r", clock=clock)
    q.init(make_atoms(jobs(1, 4), 4))
    q.claim(worker("a", spf=1.0))
    assert q.speculate(worker("b", spf=1.0, provider="other")) == []      # same speed: no gain


def test_reopen_makes_atom_claimable_again(clock):
    q = WorkQueue(MemoryStore(), "r", clock=clock)
    q.init(make_atoms(jobs(1, 2), 2))
    [L] = q.claim(worker("untrusted"))
    q.complete(L, {"node": "n1"})
    assert q.progress()["complete"]
    q.reopen(L.atom, "failed spot check")
    assert not q.progress()["complete"]
    [M] = q.claim(worker("trusted"))
    assert M.atom == L.atom and M.gen == 1


def test_same_provider_speculates_only_on_a_real_anomaly(clock):
    """A worse-than-estimated chunk on the same kind of worker is a bad estimate, not a straggler (live run lesson:
    6 needless Lambda copies when the uncalibrated estimate was 136 s and chunks took ~250 s)."""
    q = WorkQueue(MemoryStore(), "r", clock=clock, lease_s=10_000)
    q.init(make_atoms(jobs(1, 4), 4))
    [a] = q.claim(worker("lam1", spf=1.0, provider="aws_lambda"))      # est 10 + 4 = 14 s
    clock.advance(40)                                                  # overdue, but < 2x est + 60 s
    assert q.speculate(worker("lam2", spf=1.0, provider="aws_lambda")) == []
    clock.advance(60)                                                  # 100 s > 2 x 14 + 60: anomaly
    [s] = q.speculate(worker("lam2", spf=1.0, provider="aws_lambda"))
    assert s.spec
