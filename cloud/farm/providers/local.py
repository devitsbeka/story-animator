"""
providers/local.py - render workers as processes on THIS machine (CPU Cycles, or a local GPU if there is one).
Last resort: never needs an account, never costs money, slow (CPU ~0.03x an A10G for Cycles).

Each worker is `python3 cloud/farm/worker.py` with REQUIRE_GPU=0 and its own work dir; pid + metadata live in
<state_dir>/local/<id>.json so list()/terminate() work across scheduler invocations.
"""
import json
import os
import signal
import subprocess
import sys
import time
import uuid

from .base import PENDING, RUNNING, STOPPED, Provider, WorkerHandle

HERE = os.path.dirname(os.path.abspath(__file__))
WORKER = os.path.abspath(os.path.join(HERE, "..", "worker.py"))


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # a zombie child counts as gone
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().split(") ", 1)[1][:1] != "Z"
    except OSError:
        return True


class Local(Provider):
    name = "local"
    gpu_map = {"CPU": "cpu"}
    default_prices = {"CPU": 0.0}

    def __init__(self, cfg=None, env=None, state_dir=None, popen=subprocess.Popen):
        super().__init__(cfg, env)
        self.dir = os.path.join(state_dir or os.path.expanduser("~/.story-farm"), "local")
        self.popen = popen

    def spot_options(self):
        return [False]

    def available(self):
        if not self.cfg.get("enabled", True):
            return False, "local workers disabled"
        free = self.max_workers() - len([h for h in self.list() if h.status in (PENDING, RUNNING)])
        if free <= 0:
            return False, f"local: all {self.max_workers()} slots busy"
        return True, f"local: {free} free slot(s), {os.cpu_count()} cpus"

    def launch(self, n, gpu_class, env, startup, spot=False):
        os.makedirs(self.dir, exist_ok=True)
        out = []
        for _ in range(n):
            wid = uuid.uuid4().hex[:10]
            work = os.path.join(self.dir, wid)
            os.makedirs(work, exist_ok=True)
            penv = {**os.environ, **{k: str(v) for k, v in env.items()},
                    "REQUIRE_GPU": "0", "FARM_IMDS": "0", "FARM_PROVIDER": self.name,
                    "FARM_PROVIDER_WORKER_ID": f"{self.name}:{wid}", "FARM_WORK": os.path.join(work, "work"),
                    "HEALTH_FILE": os.path.join(work, "health.json"),
                    "RENDER_THREADS": str(self.cfg.get("threads", 2))}
            log = open(os.path.join(work, "worker.log"), "ab")
            proc = self.popen([sys.executable, WORKER], env=penv, stdout=log, stderr=subprocess.STDOUT,
                              start_new_session=True)
            meta = {"id": wid, "pid": proc.pid, "launched_at": time.time(), "gpu_class": "CPU"}
            with open(os.path.join(self.dir, f"{wid}.json"), "w") as fh:
                json.dump(meta, fh)
            out.append(WorkerHandle(self.name, wid, "CPU", PENDING, 0.0, False, detail={"pid": proc.pid}))
        return out

    def list(self):
        if not os.path.isdir(self.dir):
            return []
        out = []
        for name in sorted(os.listdir(self.dir)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(self.dir, name)) as fh:
                m = json.load(fh)
            st = RUNNING if _alive(m["pid"]) else STOPPED
            out.append(WorkerHandle(self.name, m["id"], "CPU", st, 0.0, False, m["launched_at"], {"pid": m["pid"]}))
        return out

    def terminate(self, ids):
        done = []
        for wid in ids:
            p = os.path.join(self.dir, f"{wid}.json")
            if not os.path.isfile(p):
                done.append(wid)
                continue
            with open(p) as fh:
                pid = json.load(fh)["pid"]
            if _alive(pid):
                try:
                    os.killpg(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            os.remove(p)
            done.append(wid)
        return done
