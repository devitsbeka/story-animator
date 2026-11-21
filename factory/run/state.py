"""episodes/<id>/run.json: the run's state, per-stage status, artifacts, cost and time. Written atomically after
every change, so a crash leaves the last consistent state and `--resume` picks up from it."""
import datetime
import json
import os
import threading
import time

SCHEMA = "factory.run/1"
PENDING, RUNNING, DONE, FAILED, AWAITING, SKIPPED = "pending", "running", "done", "failed", "awaiting_approval", "skipped"
# run-level statuses
R_RUNNING, R_AWAITING, R_PUBLISHED, R_RETURNED, R_FAILED, R_BUDGET, R_DONE = (
    "running", "awaiting_approval", "published", "returned", "failed", "budget_exceeded", "done")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class RunState:
    def __init__(self, path, doc):
        self.path, self.doc = path, doc
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ io
    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as fh:
            return cls(path, json.load(fh))

    @classmethod
    def create(cls, path, meta, stage_names):
        doc = {"schema": SCHEMA, **meta, "status": R_RUNNING, "created": now_iso(), "updated": now_iso(),
               "stages": {s: {"status": PENDING} for s in stage_names},
               "approval": None, "qc": {"iterations": []}, "cost": {"totalUSD": 0.0, "byStage": {}},
               "time": {"totalSeconds": 0.0, "byStage": {}}, "events": []}
        st = cls(path, doc)
        st.save()
        return st

    def save(self):
        with self._lock:
            self.doc["updated"] = now_iso()
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            tmp = f"{self.path}.{os.getpid()}.{threading.get_ident()}.part"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.doc, fh, indent=1, ensure_ascii=False, default=str)
                fh.write("\n")
            os.replace(tmp, self.path)

    # ------------------------------------------------------------------ helpers
    def stage(self, name):
        return self.doc["stages"].setdefault(name, {"status": PENDING})

    def event(self, msg, **kw):
        with self._lock:
            self.doc["events"].append({"t": now_iso(), "msg": msg, **kw})
            self.doc["events"] = self.doc["events"][-400:]
            self.save()

    def update_stage(self, name, **kw):
        with self._lock:
            self.stage(name).update(kw)
            self._totals()
            self.save()

    def add_cost(self, name, usd, seconds=0.0):
        """Accumulate cost/time on a stage (stages that re-run in the QC loop add up)."""
        with self._lock:
            s = self.stage(name)
            s["costUSD"] = round(float(s.get("costUSD") or 0) + float(usd or 0), 4)
            s["seconds"] = round(float(s.get("seconds") or 0) + float(seconds or 0), 2)
            self._totals()
            self.save()

    def _totals(self):
        by_c = {k: round(float(v.get("costUSD") or 0), 4) for k, v in self.doc["stages"].items()}
        by_t = {k: round(float(v.get("seconds") or 0), 2) for k, v in self.doc["stages"].items()}
        self.doc["cost"] = {"totalUSD": round(sum(by_c.values()), 4), "byStage": by_c,
                            "budgetUSD": self.doc.get("cost", {}).get("budgetUSD")}
        self.doc["time"] = {"totalSeconds": round(sum(by_t.values()), 2), "byStage": by_t}

    def set_status(self, status, **kw):
        with self._lock:
            self.doc["status"] = status
            self.doc.update(kw)
            self.save()

    @property
    def spent(self):
        return float(self.doc.get("cost", {}).get("totalUSD") or 0)


class Timer:
    def __enter__(self):
        self.t0 = time.time()
        return self

    def __exit__(self, *a):
        self.seconds = time.time() - self.t0
