"""
providers/runpod.py - RunPod GPU pods (REST API v2, https://api.runpod.io/v2; OpenAPI read 2026-11-21).

    env RUNPOD_API_KEY    (RunPod console -> Settings -> API Keys; scope: read/write for Pods + Catalog)

Calls used (request shapes from the v2 OpenAPI spec, see tests/farm/test_provider_runpod.py):
  GET    /v2/catalog/gpus?include=AVAILABILITY&product=POD&cloud=SECURE   price + stock per GPU type
  POST   /v2/pods                 {"name", "image", "gpu": {"id", "count"}, "cloud": "SECURE"|"COMMUNITY",
                                   "disk", "env": {..}, "entrypoint": [..], "cmd": [..], "ports": []}
  GET    /v2/pods                 list (filtered to names starting with "story-farm-")
  DELETE /v2/pods/{id}            terminate (irreversible; there is no volume to keep)

Create-failure semantics (from the spec's table): 400 = rule violation OR no capacity for that GPU/data centre
(-> CapacityError, try the next candidate), 402 = insufficient balance (QuotaError), 403 = no access to the pool
(CapacityError: skip), 401 = bad key (AuthError), 422 = contract violation (ProviderError: a bug, never retried),
429/5xx retried by Http then ProviderError.

Spot ("interruptible") pods are not in REST v2. They exist only in the deprecated GraphQL API
(`podRentInterruptable`, `bidPerGpu`; GraphQL is announced for retirement in 2027), so they are opt-in:
`interruptible: true` in providers.yaml; on any GraphQL error the provider falls back to on-demand REST.
"""
import json

from .base import (FAILED, FARM_LABEL, PENDING, RUNNING, STOPPED, TERMINATED, AuthError, CapacityError, Http,
                   Provider, ProviderError, QuotaError, WorkerHandle)

API = "https://api.runpod.io"
GRAPHQL = "https://api.runpod.io/graphql"
STATUS = {"PROVISIONING": PENDING, "STARTING": PENDING, "RUNNING": RUNNING, "EXITED": STOPPED, "ERROR": FAILED,
          "TERMINATED": TERMINATED}


class RunPod(Provider):
    name = "runpod"
    gpu_map = {"RTX4090": "NVIDIA GeForce RTX 4090", "L40S": "NVIDIA L40S", "L4": "NVIDIA L4",
               "A100": "NVIDIA A100 80GB PCIe", "A10G": "NVIDIA A40"}
    # list prices per GPU-hour (secure cloud) used only when the catalog cannot be read
    default_prices = {"RTX4090": 0.69, "L40S": 0.86, "L4": 0.43, "A100": 1.64, "A10G": 0.40}

    def __init__(self, cfg=None, env=None, transport=None, sleep=None):
        super().__init__(cfg, env)
        self.key = self.env.get("RUNPOD_API_KEY", "")
        kw = {"sleep": sleep} if sleep else {}
        self.http = Http(self.cfg.get("api", API), self.key, transport, "runpod", **kw)
        self.gql = Http(self.cfg.get("graphql", GRAPHQL), self.key, transport, "runpod-graphql", **kw)
        self._catalog = None

    # ------------------------------------------------------------------ catalog
    def clouds(self):
        c = self.cfg.get("cloud", ["SECURE", "COMMUNITY"])
        return [c] if isinstance(c, str) else list(c)

    def catalog(self, refresh=False):
        """{gpu_id: {cloud: {"price": float, "availability": str}}} for the configured clouds."""
        if self._catalog is not None and not refresh:
            return self._catalog
        out = {}
        for cloud in self.clouds():
            status, body = self.http.request("GET", "/v2/catalog/gpus",
                                             query={"include": "AVAILABILITY", "product": "POD", "cloud": cloud})
            self._raise_for(status, body, "catalog")
            for g in (body or {}).get("gpus", []):
                price = (g.get("price") or {}).get(cloud.lower())
                ok = bool(g.get(cloud.lower(), True))
                out.setdefault(g["id"], {})[cloud] = {
                    "price": float(price) if price is not None else None,
                    "availability": g.get("availability", "UNKNOWN") if ok else "NONE"}
        self._catalog = out
        return out

    # ------------------------------------------------------------------ interface
    def available(self):
        if not self.key:
            return False, "RUNPOD_API_KEY not set"
        try:
            cat = self.catalog(refresh=True)
        except AuthError as e:
            return False, f"auth: {e}"
        except ProviderError as e:
            return False, f"catalog: {e}"
        stocked = [(g, c) for g in self.gpu_classes() for c in self.clouds()
                   if cat.get(self.gpu_map[g], {}).get(c, {}).get("availability") in ("LOW", "MEDIUM", "HIGH")]
        if not stocked:
            return False, "no stock for " + ", ".join(self.gpu_classes()) + " in " + "/".join(self.clouds())
        return True, "stock: " + ", ".join(f"{g}@{c}" for g, c in stocked)

    def price_per_hour(self, gpu_class):
        gid = self.gpu_map.get(gpu_class)
        try:
            entry = self.catalog().get(gid, {}) if gid and self.key else {}
        except ProviderError:
            entry = {}
        prices = [v["price"] for c in self.clouds() for v in [entry.get(c)] if v and v.get("price") is not None]
        return min(prices) if prices else super().price_per_hour(gpu_class)

    def pod_payload(self, i, gpu_class, cloud, env, startup):
        """POST /v2/pods body for one worker. `startup` is the bootstrap command line (startup.bootstrap_command)."""
        return {
            "name": f"{FARM_LABEL}-{self.cfg.get('name', 'worker')}-{gpu_class.lower()}-{i}",
            "image": self.cfg.get("image", "nvidia/cuda:12.4.1-base-ubuntu22.04"),
            "gpu": {"id": self.gpu_map[gpu_class], "count": 1,
                    **({"minCudaVersion": self.cfg["min_cuda"]} if self.cfg.get("min_cuda") else {})},
            "cloud": cloud,
            "disk": int(self.cfg.get("disk_gb", 40)),
            "env": {k: str(v) for k, v in env.items()},
            "entrypoint": ["/bin/bash", "-c"],
            "cmd": [startup],
            "ports": [],
        }

    def interruptible_payload(self, i, gpu_class, cloud, env, startup, bid):
        """Deprecated GraphQL podRentInterruptable mutation (spot)."""
        return {"query": "mutation rent($input: PodRentInterruptableInput!) { podRentInterruptable(input: $input) "
                         "{ id costPerHr desiredStatus } }",
                "variables": {"input": {
                    "name": f"{FARM_LABEL}-{self.cfg.get('name', 'worker')}-{gpu_class.lower()}-{i}",
                    "imageName": self.cfg.get("image", "nvidia/cuda:12.4.1-base-ubuntu22.04"),
                    "gpuTypeId": self.gpu_map[gpu_class], "gpuCount": 1, "cloudType": cloud,
                    "bidPerGpu": float(bid), "containerDiskInGb": int(self.cfg.get("disk_gb", 40)),
                    "volumeInGb": 0, "ports": "",
                    "dockerArgs": "bash -c " + json.dumps(startup),
                    "env": [{"key": k, "value": str(v)} for k, v in env.items()]}}}

    def launch(self, n, gpu_class, env, startup, spot=False):
        if gpu_class not in self.gpu_map:
            raise CapacityError(f"runpod has no GPU class {gpu_class}")
        if not self.key:
            raise AuthError("RUNPOD_API_KEY not set")
        handles, last = [], None
        for i in range(n):
            pod = None
            for cloud in self.clouds():
                try:
                    if spot and self.cfg.get("interruptible"):
                        pod = self._create_interruptible(i, gpu_class, cloud, env, startup)
                    if pod is None:
                        pod = self._create(i, gpu_class, cloud, env, startup)
                    break
                except CapacityError as e:
                    last = e  # next cloud
            if pod is None:
                if handles:
                    return handles  # partial: the scheduler asks the next provider for the rest
                raise last or CapacityError(f"runpod: no capacity for {gpu_class}")
            handles.append(pod)
        return handles

    def _create(self, i, gpu_class, cloud, env, startup):
        status, body = self.http.request("POST", "/v2/pods", self.pod_payload(i, gpu_class, cloud, env, startup))
        self._raise_for(status, body, f"create {gpu_class}@{cloud}")
        return self._handle(body, gpu_class, spot=False)

    def _create_interruptible(self, i, gpu_class, cloud, env, startup):
        bid = self.cfg.get("bid_per_gpu") or round(self.price_per_hour(gpu_class) * 0.6, 3)
        status, body = self.gql.request("POST", "", self.interruptible_payload(i, gpu_class, cloud, env, startup, bid))
        pod = ((body or {}).get("data") or {}).get("podRentInterruptable") if status == 200 else None
        if not pod or (body or {}).get("errors"):
            return None  # GraphQL spot path is best-effort; fall back to on-demand REST
        return WorkerHandle(self.name, pod["id"], gpu_class, PENDING, float(pod.get("costPerHr") or bid), True,
                            detail={"cloud": cloud, "bid": bid})

    def _handle(self, pod, gpu_class=None, spot=False):
        gid = (pod.get("gpu") or {}).get("id")
        cls = gpu_class or next((k for k, v in self.gpu_map.items() if v == gid), gid or "unknown")
        return WorkerHandle(self.name, pod["id"], cls, STATUS.get(pod.get("status"), PENDING),
                            float(pod.get("cost") or 0.0), spot,
                            detail={"name": pod.get("name"), "cloud": pod.get("cloud"),
                                    "dataCenterId": pod.get("dataCenterId"), "status": pod.get("status")})

    def list(self):
        if not self.key:
            return []
        out, cursor = [], None
        while True:
            status, body = self.http.request("GET", "/v2/pods", query={"cursor": cursor} if cursor else None)
            self._raise_for(status, body, "list")
            for p in (body or {}).get("pods", []):
                if str(p.get("name", "")).startswith(FARM_LABEL + "-"):
                    out.append(self._handle(p))
            cursor = ((body or {}).get("pagination") or {}).get("nextCursor")
            if not cursor:
                return out

    def terminate(self, ids):
        done = []
        for pid in ids:
            status, body = self.http.request("DELETE", f"/v2/pods/{pid}")
            if status in (200, 204, 404):
                done.append(pid)
            else:
                self._raise_for(status, body, f"terminate {pid}")
        return done

    # ------------------------------------------------------------------ errors
    @staticmethod
    def _raise_for(status, body, what):
        if 200 <= status < 300:
            return
        detail = (body or {}).get("detail") or (body or {}).get("title") or str(body)[:200]
        msg = f"runpod {what}: HTTP {status}: {detail}"
        if status == 401:
            raise AuthError(msg)
        if status == 402:
            raise QuotaError(msg)
        if status in (400, 403, 404, 409):
            raise CapacityError(msg)
        raise ProviderError(msg)
