"""
providers/base.py - the interface every compute provider implements, plus a tiny injectable HTTP client.

    Provider.available()                          -> (ok: bool, reason: str)
    Provider.launch(n, gpu_class, env, startup)   -> [WorkerHandle]      (raises CapacityError / QuotaError / ...)
    Provider.list()                               -> [WorkerHandle]      (this farm's workers only)
    Provider.terminate(ids)                       -> [ids terminated]
    Provider.price_per_hour(gpu_class)            -> float USD per worker-hour (one GPU)

A provider never decides HOW MANY workers to run or WHEN to fall back: that is scheduler.py. A provider only
translates "n workers of gpu_class with this env and this startup script" into its API, and reports failures as
typed exceptions so the scheduler can fall back to the next provider.

GPU classes are provider-neutral names (A10G, L4, RTX4090, L40S, A100, CPU); each provider maps them to its own
ids (EC2 instance types, RunPod gpu ids, Vast gpu_name values).
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field

# Worker states reported by list(): normalised from each provider's own status vocabulary.
PENDING, RUNNING, STOPPED, FAILED, TERMINATED = "PENDING", "RUNNING", "STOPPED", "FAILED", "TERMINATED"

FARM_LABEL = "story-farm"   # name prefix / label every farm worker carries so list() never touches other machines


class ProviderError(Exception):
    """Generic provider/API failure (5xx, malformed response, network). Scheduler: fall back, retry later."""


class CapacityError(ProviderError):
    """The provider has no capacity for this GPU class right now (no offers, placement failed, ICE)."""


class QuotaError(ProviderError):
    """Account limit: quota 0, insufficient balance, plan limit. Retrying soon will not help."""


class AuthError(ProviderError):
    """Missing or rejected credentials."""


@dataclass
class WorkerHandle:
    provider: str
    id: str
    gpu_class: str
    status: str = PENDING
    price_per_hour: float = 0.0
    spot: bool = False
    launched_at: float = field(default_factory=time.time)
    detail: dict = field(default_factory=dict)

    @property
    def worker_key(self):
        """What the worker reports as FARM_PROVIDER_WORKER_ID in its heartbeat (see startup.py)."""
        return f"{self.provider}:{self.id}"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


class Provider:
    name = "base"
    gpu_map = {}        # gpu_class -> provider-specific id(s)
    default_prices = {}  # gpu_class -> USD/h used when the live catalog cannot be read

    def __init__(self, cfg=None, env=None):
        self.cfg = dict(cfg or {})
        self.env = env if env is not None else {}

    # --- interface
    def available(self):
        raise NotImplementedError

    def launch(self, n, gpu_class, env, startup):
        raise NotImplementedError

    def list(self):
        raise NotImplementedError

    def terminate(self, ids):
        raise NotImplementedError

    def price_per_hour(self, gpu_class):
        p = (self.cfg.get("prices") or {}).get(gpu_class, self.default_prices.get(gpu_class))
        if p is None:
            raise ProviderError(f"{self.name}: no price for {gpu_class}")
        return float(p)

    # --- helpers
    def gpu_classes(self):
        """GPU classes this provider is configured to offer, in preference order."""
        return [g for g in (self.cfg.get("gpu_classes") or list(self.gpu_map)) if g in self.gpu_map]

    def max_workers(self):
        return int(self.cfg.get("max_workers", 0))

    def spot_options(self):
        """[True, False] if spot first, [False] if spot disabled, [True] if spot only."""
        mode = self.cfg.get("spot", "first")
        return {"first": [True, False], "only": [True], "never": [False], True: [True, False],
                False: [False]}.get(mode, [True, False])

    def describe(self):
        return {"provider": self.name, "gpuClasses": self.gpu_classes(), "maxWorkers": self.max_workers()}


# ----------------------------------------------------------------------------------------------- HTTP
def urllib_transport(method, url, headers, body, timeout=30):
    """Default transport: -> (status, headers dict, body bytes). Never raises on HTTP status codes."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read() or b""
    except (urllib.error.URLError, OSError) as e:
        raise ProviderError(f"{method} {url}: {e}") from e


class Http:
    """JSON over HTTP with a bearer key. `transport` is injectable so tests (and dry runs) never hit the network."""

    def __init__(self, base, api_key, transport=None, provider="http", retries=3, sleep=time.sleep):
        self.base, self.api_key, self.provider = base.rstrip("/"), api_key, provider
        self.transport = transport or urllib_transport
        self.retries, self.sleep = retries, sleep

    def request(self, method, path, body=None, query=None):
        url = self.base + path
        if query:
            url += "?" + urllib.parse.urlencode(query, doseq=True)
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json",
                   "User-Agent": "story-farm-scheduler/1"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        for attempt in range(self.retries + 1):
            status, rh, raw = self.transport(method, url, headers, data)
            if status == 429 or status >= 500:
                if attempt < self.retries:
                    wait = float((rh or {}).get("Retry-After") or 2 ** attempt)
                    self.sleep(min(wait, 30.0))
                    continue
            break
        try:
            payload = json.loads(raw.decode() or "null") if raw else None
        except ValueError:
            payload = {"raw": raw[:500].decode(errors="replace")}
        return status, payload
