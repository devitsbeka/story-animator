"""
base.py - the adapter contract every compute provider implements for the broker.

A TASK is one chunk (a run of consecutive frames of one shot) described by a presigned chunk manifest: the
worker needs nothing but that URL (no cloud credentials). Adapters only start, poll and stop tasks; the broker
owns leases, the ledger and verification.

    available()            -> (ok, reason)       credentials/quota/endpoint reachable (no launch)
    slots()                -> int                tasks that may start right now (concurrency - running)
    workers()              -> [worker dict]      for push adapters one generic worker per free slot; for
                                                 member nodes one per live idle node (its own capabilities)
    start(task)            -> handle dict        async: returns immediately; task = {chunk, attempt,
                                                 manifestUrl, doneKey, estS, worker}
    poll(handle)           -> {"state": running|done|failed|lost, "usage": {unit: amount}, ...}
    cancel(handle)         -> None               best effort
    usage_estimate(estS)   -> {unit: amount}     what one task of estS seconds consumes (for ledger reserve)

Failures are typed so the broker can re-plan: CapacityError (no slots / stock), QuotaError (free tier or account
limit), AuthError, ProviderError (anything else), NotImplementedError (stub adapters).
"""


class ProviderError(Exception):
    pass


class CapacityError(ProviderError):
    pass


class QuotaError(ProviderError):
    pass


class AuthError(ProviderError):
    pass


class Adapter:
    name = "base"
    push = True          # push: the broker starts one task per chunk; pull: workers fetch work themselves
    trusted = True

    def __init__(self, pid, cfg, clock=None):
        import time
        self.pid, self.cfg = pid, cfg or {}
        self.clock = clock or time.time
        self.running = {}

    # --- capability view used by the queue / planner
    def worker_profile(self):
        c = self.cfg
        hw = c.get("hardware") or {}
        return {"provider": self.pid, "gpu": c.get("type") == "gpu", "ramGb": float(hw.get("ram_gb") or 0) or 1e9,
                "spf": dict(c.get("spf") or {}), "buildS": float(c.get("build_s", 30)),
                "coldStartS": float(c.get("cold_start_s", 0)), "maxRuntimeS": float(c.get("max_runtime_s", 900)),
                "trusted": bool(c.get("trusted", True))}

    def available(self):
        return True, "ok"

    def concurrency(self):
        return int(self.cfg.get("concurrency") or 1)

    def slots(self):
        return max(0, self.concurrency() - len(self.running))

    def workers(self):
        prof = self.worker_profile()
        return [{**prof, "id": f"{self.pid}:{i}"} for i in range(self.slots())]

    def start(self, task):
        raise NotImplementedError

    def poll(self, handle):
        raise NotImplementedError

    def cancel(self, handle):
        self.running.pop(handle.get("attempt"), None)

    def finish(self, handle):
        self.running.pop(handle.get("attempt"), None)

    def usage_estimate(self, est_s):
        q = self.cfg.get("quota") or {}
        if not q.get("unit"):
            return {}
        return {q["unit"]: float(est_s) * float(q.get("per_task_s") or 1.0)}

    def price_per_task(self, est_s):
        """$ for one task of est_s seconds if run PAID (hourly price or quota unit price beyond free)."""
        if self.cfg.get("price_usd_h"):
            return float(self.cfg["price_usd_h"]) * est_s / 3600.0
        q = self.cfg.get("quota") or {}
        return float(q.get("unit_usd") or 0) * float(q.get("per_task_s") or 1.0) * est_s


class StubAdapter(Adapter):
    """A provider whose launch contract is documented but not implemented yet: never schedulable."""
    contract = ""

    def available(self):
        return False, f"{self.pid}: adapter stub (contract documented, launch not implemented)"

    def slots(self):
        return 0

    def start(self, task):
        raise NotImplementedError(f"{self.pid}: stub adapter; see factory/compute/adapters/stubs.py")

    def poll(self, handle):
        return {"state": "lost", "error": "stub"}
