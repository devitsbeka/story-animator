"""
providers/vastai.py - Vast.ai marketplace GPUs (REST API, https://console.vast.ai; docs read 2026-11-21).

    env VAST_API_KEY      (cloud.vast.ai -> Account -> Keys -> "+ New" API key)

Calls used (shapes from docs.vast.ai/api-reference, see tests/farm/test_provider_vast.py):
  POST   /api/v0/bundles          search offers: {"gpu_name": {"in": [..]}, "num_gpus": {"eq": 1},
                                   "reliability": {"gte": 0.98}, "dph_total": {"lte": X}, "rentable": {"eq": true},
                                   "verified": {"eq": true}, "rented": {"eq": false}, "type": "ondemand"|"bid",
                                   "order": [["dph_total", "asc"]], "limit": N}  -> {"offers": [...]}
  PUT    /api/v0/asks/{offer_id}  create instance: {"image", "disk", "label", "runtype": "args", "args": [..],
                                   "env": "-e K=V ...", "price" (bids only), "cancel_unavail": true}
                                   -> {"success": true, "new_contract": <instance id>}
  GET    /api/v1/instances        list (paginated by next_token), filtered by label prefix "story-farm-"
  DELETE /api/v0/instances/{id}   destroy
  GET    /api/v0/users/current  account balance (<= 0 -> unavailable)

runtype "args" makes the startup script the container command: no SSH/Jupyter, no ports exposed.
Vast's `env` is a docker-flag STRING, not a dict, so values are restricted to shell-safe characters.
Failures: 410 (offer gone) / no_such_ask -> try the next offer; no offers -> CapacityError; 401/403 -> AuthError;
insufficient credit -> QuotaError.
"""
import re

from .base import (FAILED, FARM_LABEL, PENDING, RUNNING, STOPPED, AuthError, CapacityError, Http, Provider,
                   ProviderError, QuotaError, WorkerHandle)

API = "https://console.vast.ai"
SAFE_ENV = re.compile(r"^[A-Za-z0-9_./:@+=,%-]*$")
STATUS = {"running": RUNNING, "loading": PENDING, "created": PENDING, "scheduling": PENDING, "exited": STOPPED,
          "stopped": STOPPED, "offline": FAILED, "error": FAILED}


class VastAI(Provider):
    name = "vastai"
    gpu_map = {"RTX4090": ["RTX 4090"], "L40S": ["L40S"], "L4": ["L4"], "A100": ["A100 PCIE", "A100 SXM4"],
               "A10G": ["A10", "A40"]}
    default_prices = {"RTX4090": 0.40, "L40S": 0.75, "L4": 0.30, "A100": 1.00, "A10G": 0.35}

    def __init__(self, cfg=None, env=None, transport=None, sleep=None):
        super().__init__(cfg, env)
        self.key = self.env.get("VAST_API_KEY", "")
        self.http = Http(self.cfg.get("api", API), self.key, transport, "vastai", **({"sleep": sleep} if sleep else {}))

    # ------------------------------------------------------------------ offers
    def offer_query(self, gpu_class, spot=False, limit=20):
        q = {"gpu_name": {"in": self.gpu_map[gpu_class]}, "num_gpus": {"eq": 1},
             "reliability": {"gte": float(self.cfg.get("min_reliability", 0.98))},
             "rentable": {"eq": True}, "verified": {"eq": bool(self.cfg.get("verified_only", True))},
             "rented": {"eq": False}, "disk_space": {"gte": int(self.cfg.get("disk_gb", 40))},
             "cuda_max_good": {"gte": float(self.cfg.get("min_cuda", 12.0))},
             "inet_down": {"gte": float(self.cfg.get("min_inet_down_mbps", 200))},
             "type": "bid" if spot else "ondemand", "order": [["dph_total", "asc"]], "limit": limit}
        if self.cfg.get("max_dph"):
            q["dph_total"] = {"lte": float(self.cfg["max_dph"])}
        return q

    def offers(self, gpu_class, spot=False):
        status, body = self.http.request("POST", "/api/v0/bundles", self.offer_query(gpu_class, spot))
        self._raise_for(status, body, "search offers")
        offers = (body or {}).get("offers") or []
        if isinstance(offers, dict):  # the docs' example shows a single object
            offers = [offers]
        names = {n.lower().replace("_", " ") for n in self.gpu_map[gpu_class]}
        good = [o for o in offers if str(o.get("gpu_name", "")).lower().replace("_", " ") in names]
        return sorted(good, key=lambda o: float(o.get("dph_total") or 1e9))

    # ------------------------------------------------------------------ interface
    def available(self):
        if not self.key:
            return False, "VAST_API_KEY not set"
        try:
            status, body = self.http.request("GET", "/api/v0/users/current")
            self._raise_for(status, body, "account")
            bal = (body or {}).get("balance", (body or {}).get("credit"))
            if bal is not None and float(bal) <= 0:
                return False, f"vast balance {bal} <= 0"
            for g in self.gpu_classes():
                for spot in self.spot_options():
                    found = self.offers(g, spot)
                    if found:
                        return True, f"{len(found)} offers for {g} from ${float(found[0]['dph_total']):.3f}/h"
        except ProviderError as e:
            return False, str(e)
        return False, "no matching offers for " + ", ".join(self.gpu_classes())

    def price_per_hour(self, gpu_class):
        if self.key and gpu_class in self.gpu_map:
            try:
                o = self.offers(gpu_class)
                if o:
                    return float(o[0]["dph_total"])
            except ProviderError:
                pass
        return super().price_per_hour(gpu_class)

    @staticmethod
    def env_string(env):
        bad = [k for k, v in env.items() if not SAFE_ENV.match(str(v)) or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k)]
        if bad:
            raise ProviderError(f"vast env values must be shell-safe (docker-flag string); offending: {bad}")
        return " ".join(f"-e {k}={v}" for k, v in env.items())

    def create_payload(self, i, gpu_class, env, startup, bid=None):
        body = {"image": self.cfg.get("image", "nvidia/cuda:12.4.1-base-ubuntu22.04"),
                "disk": int(self.cfg.get("disk_gb", 40)),
                "label": f"{FARM_LABEL}-{self.cfg.get('name', 'worker')}-{gpu_class.lower()}-{i}",
                "runtype": "args", "args": ["bash", "-c", startup], "env": self.env_string(env),
                "target_state": "running", "cancel_unavail": True}
        if bid is not None:
            body["price"] = round(float(bid), 4)
        return body

    def launch(self, n, gpu_class, env, startup, spot=False):
        if gpu_class not in self.gpu_map:
            raise CapacityError(f"vastai has no GPU class {gpu_class}")
        if not self.key:
            raise AuthError("VAST_API_KEY not set")
        offers = self.offers(gpu_class, spot)
        if not offers:
            raise CapacityError(f"vastai: no offers for {gpu_class} ({'bid' if spot else 'on-demand'})")
        handles, errors = [], []
        for o in offers:
            if len(handles) >= n:
                break
            bid = None
            if spot:
                bid = max(float(o.get("min_bid") or 0) * float(self.cfg.get("bid_markup", 1.15)), 0.001)
            status, body = self.http.request("PUT", f"/api/v0/asks/{o['id']}",
                                             self.create_payload(len(handles), gpu_class, env, startup, bid))
            if status in (400, 404, 410) or (200 <= status < 300 and not (body or {}).get("success")):
                errors.append(f"offer {o['id']}: HTTP {status} {(body or {}).get('error') or (body or {}).get('msg')}")
                if (body or {}).get("error") in ("insufficient_credit", "insufficient_funds"):
                    raise QuotaError("vastai: " + errors[-1])
                continue
            self._raise_for(status, body, f"create on offer {o['id']}")
            price = bid if spot else float(o.get("dph_total") or 0)
            handles.append(WorkerHandle(self.name, str(body["new_contract"]), gpu_class, PENDING, price, spot,
                                        detail={"offer": o["id"], "machine": o.get("machine_id"),
                                                "reliability": o.get("reliability"), "gpu_name": o.get("gpu_name")}))
        if not handles:
            raise CapacityError("vastai: every offer failed: " + "; ".join(errors[:5]))
        return handles

    def list(self):
        if not self.key:
            return []
        out, token = [], None
        while True:
            q = {"limit": 25, **({"after_token": token} if token else {})}
            status, body = self.http.request("GET", "/api/v1/instances", query=q)
            self._raise_for(status, body, "list")
            for inst in (body or {}).get("instances", []):
                if not str(inst.get("label") or "").startswith(FARM_LABEL + "-"):
                    continue
                st = STATUS.get(str(inst.get("actual_status") or inst.get("cur_state") or "").lower(), PENDING)
                cls = next((k for k, v in self.gpu_map.items() if inst.get("gpu_name") in v), str(inst.get("gpu_name")))
                out.append(WorkerHandle(self.name, str(inst["id"]), cls, st, float(inst.get("dph_total") or 0),
                                        bool(inst.get("is_bid")),
                                        detail={"label": inst.get("label"), "status_msg": inst.get("status_msg")}))
            token = (body or {}).get("next_token")
            if not token:
                return out

    def terminate(self, ids):
        done = []
        for iid in ids:
            status, body = self.http.request("DELETE", f"/api/v0/instances/{iid}")
            if status in (200, 204, 404):
                done.append(iid)
            else:
                self._raise_for(status, body, f"destroy {iid}")
        return done

    @staticmethod
    def _raise_for(status, body, what):
        if 200 <= status < 300:
            return
        b = body or {}
        msg = f"vastai {what}: HTTP {status}: {b.get('error') or ''} {b.get('msg') or str(b)[:200]}".strip()
        if status in (401, 403):
            raise AuthError(msg)
        if b.get("error") in ("insufficient_credit", "insufficient_funds") or status == 402:
            raise QuotaError(msg)
        if status in (400, 404, 410):
            raise CapacityError(msg)
        raise ProviderError(msg)
