"""
presigned_pod.py - PAID overflow: RunPod / Vast.ai GPU pods that hold no cloud credentials.

Reuses cloud/farm/presigned.py: the pod boots the public CUDA image with providers/presigned_startup.sh, reads
ONE env var MANIFEST_URL (the chunk manifest built by the broker, same format) and runs presigned_pod.py. The
broker terminates the pod as soon as the chunk's done marker is in S3 (pods idle otherwise), so a pod bills
boot + render only. Chunks for pods are big (the planner sizes them to ~15 min) to amortise the ~7 min boot.
"""
import os
import sys

from .base import Adapter, CapacityError, ProviderError, QuotaError

FARM = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "cloud", "farm"))


def _presigned():
    if FARM not in sys.path:
        sys.path.insert(0, FARM)
    import presigned  # noqa: E402
    return presigned


class PresignedPod(Adapter):
    name = "presigned_pod"

    def __init__(self, pid, cfg, clock=None, provider_factory=None):
        super().__init__(pid, cfg, clock)
        c = cfg.get("config") or {}
        self.provider_name = c.get("provider", pid)
        self.gpu = c.get("gpu", "RTX4090")
        self.factory = provider_factory

    def _provider(self, name=None):
        ps = _presigned()
        pcfg = ps.provider_cfg(self.provider_name)
        if name:
            pcfg["name"] = name
        if self.factory:
            return self.factory(self.provider_name, pcfg)
        return ps.make_provider(self.provider_name, pcfg)

    def available(self):
        try:
            return self._provider().available()
        except Exception as e:  # noqa: BLE001
            return False, f"{type(e).__name__}: {str(e)[:160]}"

    def start(self, task):
        ps = _presigned()
        env, startup = ps.pod_env_and_startup(self.provider_name, task["manifestUrl"])
        prov = self._provider(f"story-farm-{task['attempt']}")
        try:
            h = prov.launch(1, self.gpu, env, startup)[0]
        except ps.prov.CapacityError as e:
            raise CapacityError(str(e)) from e
        except ps.prov.QuotaError as e:
            raise QuotaError(str(e)) from e
        except ps.prov.ProviderError as e:
            raise ProviderError(str(e)) from e
        rec = {"attempt": task["attempt"], "podId": h.id, "t0": self.clock(), "provider": self.pid,
               "usdPerHour": float(h.price_per_hour or self.cfg.get("price_usd_h") or 0)}
        self.running[task["attempt"]] = rec
        return rec

    def poll(self, handle):
        usd = handle["usdPerHour"] * (self.clock() - handle["t0"]) / 3600.0
        try:
            live = {w.id: w.status for w in self._provider().list()}
        except Exception as e:  # noqa: BLE001
            return {"state": "running", "usage": {"usd": usd}, "warn": str(e)[:160]}
        st = live.get(handle["podId"])
        if st is None or st in ("TERMINATED", "FAILED", "STOPPED"):
            return {"state": "exited" if st == "STOPPED" else "lost", "usage": {"usd": usd}}
        return {"state": "running", "usage": {"usd": usd}}

    def finish(self, handle):
        self.cancel(handle)

    def cancel(self, handle):
        self.running.pop(handle["attempt"], None)
        try:
            self._provider().terminate([handle["podId"]])
        except Exception:  # noqa: BLE001 - best effort; presigned.py stop --run also sweeps story-farm-* pods
            pass

    def usage_estimate(self, est_s):
        return {"usd": float(self.cfg.get("price_usd_h") or 0) * est_s / 3600.0}
