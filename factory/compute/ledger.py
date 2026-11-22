"""
ledger.py - quota ledger: free-tier consumption per provider per billing period, in each provider's NATIVE unit.

    unit examples: "GB-s" (AWS Lambda), "vCPU-s" (Cloud Run / Container Apps), "GPU-h" (Kaggle), "credits-usd"
    (Modal), "h" (member nodes' own max-hours), "requests" (Lambda's 1M free requests).

Rules
  * reserve() BEFORE work starts, with the estimate; commit() the measured amount after; release() if it never ran.
  * free capacity = quota x (1 - safety) - used - reserved. A reservation that does not fit the free remainder is
    REFUSED (QuotaExceeded) unless the run allows paid overflow; then the part beyond free is recorded as `paid`
    with its $ (unit price) and must also fit the run's budget. Free tiers are never exceeded silently.
  * observe() records the provider's own account-wide meter (e.g. Lambda GB-s from CloudWatch, which includes
    OTHER functions in the account sharing the same free tier): used = max(own commits, observed).
  * one JSON document per provider and period: <prefix><period>/<provider>.json. Concurrency: S3 If-Match optimistic writes (retry on
    a lost race) or a local flock'ed JSON file. Periods: month (UTC calendar), week (ISO, Mon 00:00 UTC), day.
"""
import datetime as dt
import json
import time
import uuid

from .store import LocalDirStore


class QuotaExceeded(Exception):
    pass


class BudgetExceeded(Exception):
    pass


def period_id(kind, now=None):
    t = dt.datetime.fromtimestamp(now if now is not None else time.time(), dt.timezone.utc)
    if kind == "month":
        return t.strftime("%Y-%m")
    if kind == "week":
        y, w, _ = t.isocalendar()
        return f"{y}-W{w:02d}"
    if kind == "day":
        return t.strftime("%Y-%m-%d")
    if kind in (None, "none", "lifetime"):
        return "lifetime"
    raise ValueError(f"unknown quota period {kind!r}")


def period_start(kind, now=None):
    t = dt.datetime.fromtimestamp(now if now is not None else time.time(), dt.timezone.utc)
    if kind == "month":
        s = t.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif kind == "week":
        s = (t - dt.timedelta(days=t.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif kind == "day":
        s = t.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        return 0.0
    return s.timestamp()


class Ledger:
    def __init__(self, store=None, prefix="compute/ledger/", clock=time.time, safety=0.05, retries=20):
        self.store = store or LocalDirStore(_default_dir())
        self.prefix = prefix.rstrip("/") + "/"
        self.clock = clock
        self.safety = safety
        self.retries = retries

    # --- document plumbing
    def _key(self, pid, quota):
        return f"{self.prefix}{period_id(quota.get('period', 'month'), self.clock())}/{pid}.json"

    def _load(self, pid, quota):
        doc, etag = self.store.get_json(self._key(pid, quota))
        if not doc:
            doc = {"provider": pid, "unit": quota.get("unit"), "period": period_id(quota.get("period", "month"),
                                                                                  self.clock()),
                   "quota": float(quota.get("free", 0) or 0), "used": 0.0, "observed": 0.0, "paid": 0.0,
                   "paidUsd": 0.0, "reserved": {}, "events": []}
        return doc, etag

    def _save(self, pid, quota, doc, etag):
        doc["quota"] = float(quota.get("free", 0) or 0)
        doc["events"] = doc["events"][-200:]
        if etag is None:
            return self.store.put_json_if_absent(self._key(pid, quota), doc)
        return self.store.put_json_if_match(self._key(pid, quota), doc, etag)

    def _update(self, pid, quota, fn):
        for _ in range(self.retries):
            doc, etag = self._load(pid, quota)
            out = fn(doc)
            if self._save(pid, quota, doc, etag):
                return out
        raise RuntimeError(f"ledger {pid}: too many concurrent writers")

    # --- reads
    @staticmethod
    def _used(doc):
        return max(float(doc["used"]), float(doc.get("observed") or 0))

    def state(self, pid, quota):
        doc, _ = self._load(pid, quota)
        cap = float(quota.get("free", 0) or 0) * (1 - self.safety)
        reserved = sum(r["free"] for r in doc["reserved"].values())
        return {"provider": pid, "unit": doc["unit"], "period": doc["period"], "freeQuota": float(quota.get("free", 0) or 0),
                "usable": round(cap, 3), "used": round(self._used(doc), 3), "observed": doc.get("observed"),
                "reserved": round(reserved, 3), "remainingFree": round(max(0.0, cap - self._used(doc) - reserved), 3),
                "paid": round(doc["paid"], 3), "paidUsd": round(doc["paidUsd"], 4),
                "openReservations": len(doc["reserved"])}

    def remaining_free(self, pid, quota):
        return self.state(pid, quota)["remainingFree"]

    # --- writes
    def reserve(self, pid, quota, amount, allow_paid=False, unit_usd=0.0, budget=None, tag=None):
        """-> reservation dict {id, free, paid, usd}. Raises QuotaExceeded / BudgetExceeded."""
        amount = float(amount)
        rid = f"{int(self.clock())}-{uuid.uuid4().hex[:8]}"

        def fn(doc):
            cap = float(quota.get("free", 0) or 0) * (1 - self.safety)
            reserved_free = sum(r["free"] for r in doc["reserved"].values())
            free_left = max(0.0, cap - self._used(doc) - reserved_free)
            free = min(amount, free_left)
            paid = amount - free
            if paid > 1e-9 and not allow_paid:
                raise QuotaExceeded(f"{pid}: {amount:.1f} {doc['unit']} needed, {free_left:.1f} free left this "
                                    f"{quota.get('period', 'month')} (quota {quota.get('free')}, safety "
                                    f"{self.safety:.0%}); paid overflow not allowed")
            usd = paid * float(unit_usd or 0)
            reserved_usd = sum(r.get("usd", 0) for r in doc["reserved"].values())
            if budget is not None and usd > 0 and doc["paidUsd"] + reserved_usd + usd > float(budget) + 1e-9:
                raise BudgetExceeded(f"{pid}: paid overflow ${usd:.4f} would exceed budget ${budget}")
            r = {"id": rid, "free": free, "paid": paid, "usd": usd, "t": self.clock(), "tag": tag, "amount": amount}
            doc["reserved"][rid] = r
            doc["events"].append({"t": self.clock(), "ev": "reserve", **r})
            return r
        return self._update(pid, quota, fn)

    def commit(self, pid, quota, rid, actual, unit_usd=0.0):
        """Settle a reservation with the measured amount (may be more or less than reserved)."""
        actual = float(actual)

        def fn(doc):
            r = doc["reserved"].pop(rid, None)
            cap = float(quota.get("free", 0) or 0) * (1 - self.safety)
            other = sum(x["free"] for x in doc["reserved"].values())
            free_left = max(0.0, cap - self._used(doc) - other)
            free = min(actual, free_left)   # this reservation is already popped: its share is back in free_left
            paid = actual - free
            doc["used"] = float(doc["used"]) + free
            doc["paid"] = float(doc["paid"]) + paid
            doc["paidUsd"] = float(doc["paidUsd"]) + paid * float(unit_usd or 0)
            ev = {"t": self.clock(), "ev": "commit", "id": rid, "actual": actual, "free": free, "paid": paid,
                  "overrun": bool(r and paid > r["paid"] + 1e-9)}
            doc["events"].append(ev)
            return ev
        return self._update(pid, quota, fn)

    def release(self, pid, quota, rid):
        def fn(doc):
            r = doc["reserved"].pop(rid, None)
            doc["events"].append({"t": self.clock(), "ev": "release", "id": rid, "had": r is not None})
            return r
        return self._update(pid, quota, fn)

    def observe(self, pid, quota, observed, source):
        def fn(doc):
            doc["observed"] = float(observed)
            doc["events"].append({"t": self.clock(), "ev": "observe", "observed": float(observed), "source": source})
            return float(observed)
        return self._update(pid, quota, fn)

    def report(self, providers):
        """providers: {pid: quota dict} -> list of states."""
        return [self.state(pid, q) for pid, q in providers.items() if q and q.get("free") is not None]


def _default_dir():
    import os
    return os.path.expanduser(os.environ.get("COMPUTE_STATE_DIR", "~/.story-compute"))


def dumps(o):
    return json.dumps(o, indent=1, default=str)
