"""
scheduler.py - keep the right number of render workers alive on whichever providers can deliver them.

The queue (SQS), state (DynamoDB) and storage (S3) stay on AWS; only the machines that poll the queue move.
Every `tick(backlog)`:

  1. reconcile   list() every enabled provider; adopt farm workers we did not know about, drop vanished ones
  2. account     spend += price x elapsed for every live worker (state file), per provider
  3. health      a worker that has not heartbeated (DynamoDB pk=WORKER) within health_timeout_s of launch, whose
                 heartbeat went silent for heartbeat_lost_s, or whose container stopped/failed is terminated; its
                 option goes on cooldown so the next tick falls back to the next option
  4. budget      spend >= max_total_usd -> terminate everything; summed $/h > max_usd_per_hour -> cut idle workers
  5. scale up    desired = backlog (A10G-seconds) / drain target, capped by job count and max_workers_total; fill
                 the deficit from the ranked options (provider order, spot first, cheapest $/speed GPU), calling
                 available() first and falling through on CapacityError / QuotaError / AuthError / ProviderError
  6. rebalance   workers on a worse option than one that is available again get a replacement; they are
                 terminated once idle (never mid-job unless over budget)
  7. scale down  nothing queued: workers idle >= idle_terminate_s are terminated; surplus idle workers too

The scheduler records every decision in the state file (events) and workers record their provider in each job
manifest and job item, so "who rendered what" is answerable afterwards.

    scheduler.py plan --spec episodes/sentinel/episode_v2.json --quality final     price/speed table, no network
    scheduler.py dry-run --out /tmp/farm-dry-run                                    render startup script + payloads
    scheduler.py --stack story-farm status | tick | stop-all                        live (reads/creates workers)
    scheduler.py calibrate --manifests DIR                                          measured speed per gpuClass
"""
import argparse
import glob
import json
import math
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import providers as prov  # noqa: E402
from providers import startup  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "providers.yaml")
DEFAULT_STATE = os.path.expanduser(os.environ.get("FARM_STATE_DIR", "~/.story-farm"))
SPEED_DEFAULTS = {"A10G": 1.0, "L4": 0.9, "RTX4090": 2.5, "L40S": 2.2, "A100": 1.8, "T4": 0.4, "CPU": 0.03}
LIVE = (prov.PENDING, prov.RUNNING)
EXTERNAL = ("runpod", "vastai")


def load_config(path=CONFIG):
    import yaml
    with open(path) as fh:
        cfg = yaml.safe_load(fh) or {}
    cfg.setdefault("order", list(prov.NAMES))
    cfg.setdefault("strategy", "priority")
    cfg.setdefault("budget", {})
    cfg.setdefault("scaling", {})
    cfg.setdefault("providers", {})
    sp = dict(SPEED_DEFAULTS)
    sp.update(cfg.get("speed") or {})
    if cfg.get("speed_calibration") and os.path.isfile(cfg["speed_calibration"]):
        with open(cfg["speed_calibration"]) as fh:
            sp.update(json.load(fh))
    cfg["speed"] = sp
    return cfg


class Option:
    """One way to get a worker: (provider, gpu class, spot or on-demand)."""

    def __init__(self, provider, gpu_class, spot, price, speed, order_idx):
        self.provider, self.gpu_class, self.spot = provider, gpu_class, spot
        self.price, self.speed, self.order_idx = price, speed, order_idx

    @property
    def key(self):
        return f"{self.provider}/{self.gpu_class}/{'spot' if self.spot else 'ondemand'}"

    @property
    def usd_per_unit_hour(self):
        """$ per A10G-equivalent hour: what a frame costs, relative."""
        return self.price / self.speed if self.speed else math.inf

    def to_dict(self):
        return {"option": self.key, "usdPerHour": round(self.price, 4), "speed": self.speed,
                "usdPerA10GHour": round(self.usd_per_unit_hour, 4)}


class Scheduler:
    def __init__(self, config, providers, farm=None, secrets=None, heartbeats=None, state_path=None,
                 now=time.time, code=None):
        self.cfg, self.providers = config, providers   # providers: {name: Provider}
        self.farm = farm or {}
        self.secrets = secrets or {}
        self.heartbeats = heartbeats or (lambda: {})
        self.state_path = state_path or os.path.join(DEFAULT_STATE, "scheduler.json")
        self.now = now
        self.code = code   # startup settings for code (FARM_CODE_*); computed lazily
        self.state = self._load()
        self._avail = {}
        self.sc = {"drain_target_hours": 2.0, "max_workers_total": 8, "health_timeout_s": 1200,
                   "heartbeat_lost_s": 600, "idle_terminate_s": 600, "rebalance": True, "rebalance_margin": 0.2,
                   "max_launches_per_tick": 4, **(config.get("scaling") or {})}
        self.cool = {"capacity": 600, "quota": 3600, "auth": 3600, "error": 300, "unhealthy": 1800,
                     **(self.sc.get("cooldown_s") or {})}

    # ------------------------------------------------------------------ state
    def _load(self):
        try:
            with open(self.state_path) as fh:
                st = json.load(fh)
        except (OSError, ValueError):
            st = {}
        st.setdefault("workers", {})
        st.setdefault("cooldown", {})
        st.setdefault("spentUsd", 0.0)
        st.setdefault("spentByProvider", {})
        st.setdefault("events", [])
        st.setdefault("lastTick", None)
        return st

    def save(self):
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.state, fh, indent=1, sort_keys=True)
        os.replace(tmp, self.state_path)

    def event(self, name, **kw):
        e = {"t": round(self.now(), 1), "event": name, **kw}
        self.state["events"] = (self.state["events"] + [e])[-500:]
        return e

    def pcfg(self, name):
        return self.cfg["providers"].get(name) or {}

    def enabled(self):
        return [n for n in self.cfg["order"] if n in self.providers and self.pcfg(n).get("enabled", True)]

    # ------------------------------------------------------------------ options
    def speed(self, gpu_class):
        return float(self.cfg["speed"].get(gpu_class, 1.0))

    def options(self):
        """Every (provider, gpu, spot) option, ranked best first per the strategy."""
        opts = []
        for idx, name in enumerate(self.enabled()):
            p = self.providers[name]
            for spot in p.spot_options():
                for g in p.gpu_classes():
                    try:
                        price = p.price_per_hour(g, spot=spot) if name == "aws_ec2" else p.price_per_hour(g)
                    except prov.ProviderError:
                        continue
                    opts.append(Option(name, g, spot, float(price), self.speed(g), idx))
        return sorted(opts, key=self.rank)

    def rank(self, o):
        local = o.provider == "local"
        if self.cfg.get("strategy") == "cheapest":
            return (local, o.usd_per_unit_hour, o.order_idx, not o.spot)
        return (o.order_idx, not o.spot, o.usd_per_unit_hour)

    def better(self, o, w_opt):
        """Is option `o` worth moving a worker away from `w_opt`?"""
        if w_opt is None or o.provider == "local":
            return False
        if w_opt.provider == "local":
            return True
        if self.cfg.get("strategy") == "cheapest":
            return o.usd_per_unit_hour < w_opt.usd_per_unit_hour * (1 - float(self.sc["rebalance_margin"]))
        return o.order_idx < w_opt.order_idx

    def cooling(self, key):
        c = self.state["cooldown"].get(key)
        return bool(c and c["until"] > self.now())

    def cooldown(self, key, kind, reason):
        self.state["cooldown"][key] = {"until": self.now() + float(self.cool.get(kind, 300)), "kind": kind,
                                       "reason": str(reason)[:300]}
        self.event("cooldown", option=key, kind=kind, reason=str(reason)[:300])

    def available(self, name):
        if name not in self._avail:
            if self.cooling(name):
                c = self.state["cooldown"][name]
                self._avail[name] = (False, f"cooldown ({c['kind']}): {c['reason']}")
            else:
                ok, reason = self.external_ready(name)
                if ok:
                    try:
                        ok, reason = self.providers[name].available()
                    except Exception as e:  # noqa: BLE001 - a provider bug must not stop the farm
                        ok, reason = False, f"{type(e).__name__}: {e}"
                self._avail[name] = (ok, reason)
                if not ok:
                    self.event("unavailable", provider=name, reason=reason)
        return self._avail[name]

    def external_ready(self, name):
        if name not in EXTERNAL:
            return True, ""
        missing = [k for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY") if not self.secrets.get(k)]
        if missing and not (self.pcfg(name).get("secret_names")):
            return False, "external worker keys not set (FARM_EXTERNAL_AWS_ACCESS_KEY_ID/_SECRET_ACCESS_KEY)"
        if not all(self.farm.get(k) for k in ("bucket", "queue_url", "table")):
            return False, "farm bucket/queue/table unknown"
        return True, ""

    # ------------------------------------------------------------------ worker env / startup
    def code_settings(self):
        if self.code is None:
            ccfg = self.cfg.get("code") or {}
            commit = ccfg.get("commit") or startup.git_head()
            self.code = startup.code_settings(ccfg, commit)
        return self.code

    def startup_for(self, name, gpu_class):
        if name not in EXTERNAL:
            return ""
        return startup.bootstrap_command(startup.render_startup(self.code_settings()))

    def env_for(self, name, gpu_class):
        if name == "aws_ec2":
            return {}
        if name == "local":
            return {"FARM_BUCKET": self.farm.get("bucket", ""), "FARM_QUEUE_URL": self.farm.get("queue_url", ""),
                    "FARM_TABLE": self.farm.get("table", ""), "AWS_REGION": self.farm.get("region", "us-east-1")}
        secrets = dict(self.secrets)
        names = self.pcfg(name).get("secret_names") or {}
        if name == "runpod":
            for k, n in names.items():  # RunPod resolves {{ RUNPOD_SECRET_x }} inside the pod; key never leaves
                secrets[k] = "{{ RUNPOD_SECRET_%s }}" % n
        return startup.worker_env(self.farm, name, gpu_class, secrets)

    # ------------------------------------------------------------------ the loop step
    def live(self, provider=None):
        return {k: w for k, w in self.state["workers"].items()
                if w["status"] in LIVE and (provider is None or w["provider"] == provider)}

    def option_of(self, w, opts):
        return next((o for o in opts if o.provider == w["provider"] and o.gpu_class == w["gpu_class"]
                     and o.spot == bool(w.get("spot"))), None)

    def tick(self, backlog_jobs, backlog_gpu_s=None):
        """One scheduling step. backlog_gpu_s: remaining work in A10G GPU-seconds (default 900 s per job)."""
        self._avail = {}
        now = self.now()
        backlog_gpu_s = float(backlog_gpu_s if backlog_gpu_s is not None else 900.0 * backlog_jobs)
        actions = {"launched": [], "terminated": [], "unavailable": {}, "errors": []}
        self.reconcile(actions)
        self.account(now)
        hb = self._heartbeats(actions)
        self.check_health(hb, actions)
        if self.enforce_budget(hb, actions):
            self.state["lastTick"] = now
            self.save()
            return self.summary(actions, backlog_jobs, 0)
        opts = self.options()
        desired = self.desired_units(backlog_jobs, backlog_gpu_s)
        if self.sc.get("rebalance") and backlog_jobs > 0:
            self.rebalance(opts, hb, actions)
        self.scale_up(desired, backlog_jobs, opts, hb, actions)
        self.scale_down(backlog_jobs, desired, opts, hb, actions)
        self.state["lastTick"] = now
        self.save()
        return self.summary(actions, backlog_jobs, desired)

    def _heartbeats(self, actions):
        try:
            return self.heartbeats() or {}
        except Exception as e:  # noqa: BLE001
            actions["errors"].append(f"heartbeats: {e}")
            return {}

    def reconcile(self, actions):
        for name in self.enabled():
            try:
                listed = self.providers[name].list()
            except Exception as e:  # noqa: BLE001
                actions["errors"].append(f"{name} list: {e}")
                continue
            seen = set()
            for h in listed:
                key = h.worker_key
                seen.add(key)
                w = self.state["workers"].get(key)
                if w is None:
                    if h.status not in LIVE:
                        continue
                    # adopt (e.g. an ASG instance that replaced our placeholder, or a pre-existing worker)
                    ph = sorted((k for k, x in self.live(name).items() if x.get("detail", {}).get("placeholder")),
                                key=lambda k: self.state["workers"][k]["launched_at"])
                    launched = h.launched_at
                    if ph:
                        launched = self.state["workers"].pop(ph[0])["launched_at"]
                        for other in self.state["workers"].values():  # rebalance links follow the adoption
                            if other.get("replacedBy") == ph[0]:
                                other["replacedBy"] = key
                    w = self.state["workers"][key] = {**h.to_dict(), "launched_at": launched, "healthyAt": None}
                    self.event("adopted", worker=key, replaces=ph[0] if ph else None)
                w["status"] = h.status
                w["price_per_hour"] = h.price_per_hour or w.get("price_per_hour", 0.0)
                w.setdefault("detail", {}).update(h.detail or {})
            for key, w in self.live(name).items():
                if key not in seen and not w.get("detail", {}).get("placeholder"):
                    w["status"] = prov.TERMINATED
                    w["endedAt"] = self.now()
                    self.event("vanished", worker=key)

    def account(self, now):
        last = self.state.get("lastTick")
        if last is None:
            return
        dt_h = max(0.0, now - float(last)) / 3600.0
        for w in self.state["workers"].values():
            if w["status"] in LIVE or (w.get("endedAt") and w["endedAt"] > last):
                end = min(now, w.get("endedAt") or now)
                h = max(0.0, end - max(float(last), float(w["launched_at"]))) / 3600.0
                h = min(h, dt_h)
                usd = h * float(w.get("price_per_hour") or 0)
                w["spentUsd"] = round(float(w.get("spentUsd", 0)) + usd, 6)
                self.state["spentUsd"] = round(self.state["spentUsd"] + usd, 6)
                sp = self.state["spentByProvider"]
                sp[w["provider"]] = round(sp.get(w["provider"], 0.0) + usd, 6)

    def check_health(self, hb, actions):
        now = self.now()
        # stopped/failed containers still exist (RunPod EXITED, Vast exited): remove them; one that never came
        # up healthy puts its option on cooldown
        for key, w in list(self.state["workers"].items()):
            if w["status"] in (prov.STOPPED, prov.FAILED) and not w.get("endedAt"):
                never = w.get("healthyAt") is None
                if self.kill(key, f"container {w['status'].lower()}", actions) and never:
                    self.cooldown(self.opt_key(w), "unhealthy", f"{key}: {w['status'].lower()} before first heartbeat")
        for key, w in list(self.live().items()):
            beat = hb.get(key)
            fresh = beat and now - float(beat.get("t", 0)) < float(self.sc["heartbeat_lost_s"])
            if beat and (w.get("healthyAt") is None) and fresh:
                w["healthyAt"] = now
                self.event("healthy", worker=key, bootSeconds=round(now - w["launched_at"]))
            if beat:
                w["hbState"] = beat.get("state")
                if beat.get("state") == "rendering":
                    w["lastBusyAt"] = float(beat.get("t", now))
            reason = None
            if w["status"] not in LIVE:
                continue
            if w.get("healthyAt") is None and now - w["launched_at"] > float(self.sc["health_timeout_s"]):
                reason = ("unhealthy", f"no heartbeat {round(now - w['launched_at'])}s after launch")
            elif w.get("healthyAt") is not None and not fresh:
                reason = ("unhealthy", "heartbeat lost")
            if reason:
                self.kill(key, reason[1], actions)
                self.cooldown(self.opt_key(w), reason[0], f"{key}: {reason[1]}")

    @staticmethod
    def opt_key(w):
        return f"{w['provider']}/{w['gpu_class']}/{'spot' if w.get('spot') else 'ondemand'}"

    def kill(self, key, reason, actions):
        w = self.state["workers"][key]
        try:
            self.providers[w["provider"]].terminate([w["id"]])
        except Exception as e:  # noqa: BLE001
            actions["errors"].append(f"terminate {key}: {e}")
            self.event("terminate_failed", worker=key, error=str(e)[:200])
            return False
        w["status"] = prov.TERMINATED
        w["endedAt"] = self.now()
        w["endReason"] = reason
        actions["terminated"].append({"worker": key, "reason": reason})
        self.event("terminated", worker=key, reason=reason)
        return True

    def rate(self):
        return sum(float(w.get("price_per_hour") or 0) for w in self.live().values())

    def idle(self, w, hb_state=None):
        return (w.get("hbState") or hb_state) == "idle" or w["status"] == prov.PENDING and w.get("healthyAt") is None

    def enforce_budget(self, hb, actions):
        b = self.cfg.get("budget") or {}
        total = float(b.get("max_total_usd") or 0)
        if total and self.state["spentUsd"] >= total:
            for key in list(self.live()):
                self.kill(key, f"budget: spent ${self.state['spentUsd']:.2f} >= ${total:.2f}", actions)
            self.event("budget_exhausted", spent=self.state["spentUsd"], ceiling=total)
            return True
        cap = float(b.get("max_usd_per_hour") or 0)
        if cap:
            # over the hourly ceiling (prices moved, config lowered): cut idle first, then most expensive
            ws = sorted(self.live().items(), key=lambda kv: (not self.idle(kv[1]), -float(kv[1]["price_per_hour"])))
            for key, w in ws:
                if self.rate() <= cap + 1e-9:
                    break
                self.kill(key, f"budget: ${self.rate():.2f}/h > ${cap:.2f}/h", actions)
        return False

    def desired_units(self, backlog_jobs, backlog_gpu_s):
        if backlog_jobs <= 0:
            return 0.0
        return backlog_gpu_s / (float(self.sc["drain_target_hours"]) * 3600.0)

    def units(self, workers):
        """Capacity in A10G units; workers already being replaced (rebalance) do not count."""
        return sum(self.speed(w["gpu_class"]) for w in workers.values() if not w.get("replacedBy"))

    def headroom(self, name):
        return int(self.pcfg(name).get("max_workers", 0)) - len(self.live(name))

    def can_afford(self, name, price, n=1):
        b = self.cfg.get("budget") or {}
        cap = float(b.get("max_usd_per_hour") or 0)
        if cap and self.rate() + price * n > cap + 1e-9:
            return False
        pcap = float(self.pcfg(name).get("max_usd_per_hour") or 0)
        prate = sum(float(w.get("price_per_hour") or 0) for w in self.live(name).values())
        if pcap and prate + price * n > pcap + 1e-9:
            return False
        total = float(b.get("max_total_usd") or 0)
        if total and self.state["spentUsd"] + price * n * 0.25 >= total:  # need >= 15 min of headroom
            return False
        return True

    def launch_on(self, o, n, actions, why="scale_up"):
        name = o.provider
        p = self.providers[name]
        try:
            handles = p.launch(n, o.gpu_class, self.env_for(name, o.gpu_class), self.startup_for(name, o.gpu_class),
                               spot=o.spot)
        except prov.QuotaError as e:
            self.cooldown(name, "quota", e)
        except prov.AuthError as e:
            self.cooldown(name, "auth", e)
        except prov.CapacityError as e:
            self.cooldown(o.key, "capacity", e)
        except Exception as e:  # noqa: BLE001 - API errors, network, bugs: fall back, retry later
            self.cooldown(o.key, "error", f"{type(e).__name__}: {e}")
        else:
            for h in handles:
                d = h.to_dict()
                d.update(launched_at=self.now(), healthyAt=None, why=why, price_per_hour=h.price_per_hour or o.price)
                self.state["workers"][h.worker_key] = d
                actions["launched"].append({"worker": h.worker_key, "option": o.key, "why": why,
                                            "usdPerHour": d["price_per_hour"]})
                self.event("launched", worker=h.worker_key, option=o.key, why=why, usdPerHour=d["price_per_hour"])
            return handles
        actions["errors"].append(f"{o.key}: {self.state['cooldown'].get(o.key, self.state['cooldown'].get(name))}")
        return []

    def usable(self, o, actions):
        if self.cooling(o.key) or self.cooling(o.provider):
            return False
        ok, reason = self.available(o.provider)
        if not ok:
            actions["unavailable"][o.provider] = reason
        return ok

    def scale_up(self, desired, backlog_jobs, opts, hb, actions):
        budget_launches = int(self.sc["max_launches_per_tick"])
        live = self.live()
        units = self.units(live)
        n_live = len(live)
        cap_total = int(self.sc["max_workers_total"])
        n_live -= sum(1 for w in live.values() if w.get("replacedBy"))
        for o in opts:
            enough = units >= desired and units > 0
            if enough or n_live >= min(cap_total, backlog_jobs) or budget_launches <= 0:
                return
            if o.provider == "local" and self.pcfg("local").get("only_when_no_gpu", True):
                if any(w["provider"] != "local" for w in self.live().values()):
                    continue
            if not self.usable(o, actions):
                continue
            need = max(1, math.ceil((desired - units) / max(o.speed, 1e-6)))
            n = min(need, self.headroom(o.provider), cap_total - n_live, backlog_jobs - n_live, budget_launches)
            while n > 0 and not self.can_afford(o.provider, o.price, n):
                n -= 1
            if n <= 0:
                continue
            got = self.launch_on(o, n, actions)
            budget_launches -= len(got)
            n_live += len(got)
            units += len(got) * o.speed

    def rebalance(self, opts, hb, actions):
        """Replace workers on worse options when a better one is usable; old ones go when idle."""
        live = self.live()
        replaced = {w.get("replacedBy") for w in live.values() if w.get("replacedBy")}
        movers = sorted(((k, w) for k, w in live.items() if not w.get("replacedBy") and k not in replaced),
                        key=lambda kv: self.rank(self.option_of(kv[1], opts) or opts[-1]) if opts else 0,
                        reverse=True)
        launches = 0
        for key, w in movers:
            if launches >= 2:
                break
            w_opt = self.option_of(w, opts)
            target = next((o for o in opts if self.better(o, w_opt) and self.usable(o, actions)
                           and self.headroom(o.provider) > 0
                           and self.rate() - float(w.get("price_per_hour") or 0) + o.price
                           <= float((self.cfg.get("budget") or {}).get("max_usd_per_hour") or math.inf)), None)
            if not target:
                continue
            got = self.launch_on(target, 1, actions, why=f"rebalance:{key}")
            if got:
                w["replacedBy"] = got[0].worker_key
                launches += 1

    def scale_down(self, backlog_jobs, desired, opts, hb, actions):
        now = self.now()
        live = self.live()
        # replaced workers: go once idle and their replacement is healthy (or the replacement died)
        for key, w in list(live.items()):
            rep = w.get("replacedBy")
            if not rep:
                continue
            r = self.state["workers"].get(rep)
            if r is None or r["status"] not in LIVE:
                w.pop("replacedBy", None)
                continue
            if r.get("healthyAt") and (self.idle(w) or w["status"] == prov.PENDING):
                self.kill(key, f"rebalanced to {rep}", actions)
        live = self.live()
        if backlog_jobs <= 0:
            for key, w in live.items():
                quiet = now - float(w.get("lastBusyAt") or w.get("healthyAt") or w["launched_at"])
                if w.get("healthyAt") is None:
                    self.kill(key, "no backlog (never came up)", actions)
                elif self.idle(w) and quiet >= float(self.sc["idle_terminate_s"]):
                    self.kill(key, f"idle {round(quiet)}s, queue empty", actions)
            return
        # surplus: more capacity than desired -> drop idle workers on the worst options
        live = self.live()
        units = self.units(live)
        order = sorted(live.items(), key=lambda kv: self.rank(self.option_of(kv[1], opts) or opts[-1]) if opts else 0,
                       reverse=True)
        for key, w in order:
            s = self.speed(w["gpu_class"])
            if units - s < desired or not self.idle(w) or w.get("healthyAt") is None:
                continue
            quiet = now - float(w.get("lastBusyAt") or w.get("healthyAt") or w["launched_at"])
            if quiet >= float(self.sc["idle_terminate_s"]):
                if self.kill(key, "surplus idle worker", actions):
                    units -= s

    def summary(self, actions, backlog_jobs, desired):
        return {"backlogJobs": backlog_jobs, "desiredUnits": round(desired, 2),
                "liveUnits": round(self.units(self.live()), 2), "usdPerHour": round(self.rate(), 4),
                "spentUsd": round(self.state["spentUsd"], 4), **actions}

    # ------------------------------------------------------------------ reporting
    def status(self, probe=False):
        rows = []
        for name in self.enabled():
            live = self.live(name)
            row = {"provider": name, "live": len(live), "maxWorkers": self.pcfg(name).get("max_workers"),
                   "usdPerHour": round(sum(float(w.get("price_per_hour") or 0) for w in live.values()), 4),
                   "spentUsd": round(self.state["spentByProvider"].get(name, 0.0), 4),
                   "workers": [{"id": k, "gpu": w["gpu_class"], "status": w["status"], "hb": w.get("hbState"),
                                "healthy": bool(w.get("healthyAt")), "spot": w.get("spot")}
                               for k, w in live.items()]}
            cd = {k: v for k, v in self.state["cooldown"].items() if (k == name or k.startswith(name + "/"))
                  and v["until"] > self.now()}
            if cd:
                row["cooldown"] = cd
            if probe:
                row["available"] = self.available(name)
            rows.append(row)
        return {"providers": rows, "spentUsd": round(self.state["spentUsd"], 4), "usdPerHour": round(self.rate(), 4),
                "budget": self.cfg.get("budget"), "recentEvents": self.state["events"][-10:]}

    def stop_all(self, reason="stop-all"):
        actions = {"terminated": [], "errors": []}
        for name in self.enabled():
            try:
                for h in self.providers[name].list():
                    if h.status in LIVE and h.worker_key not in self.state["workers"]:
                        self.state["workers"][h.worker_key] = {**h.to_dict(), "healthyAt": None}
            except Exception as e:  # noqa: BLE001
                actions["errors"].append(f"{name} list: {e}")
        for key in list(self.live()):
            self.kill(key, reason, actions)
        self.save()
        return actions


# ---------------------------------------------------------------------------------------------- planning
def plan_table(cfg, providers_, gpu_hours, workers=None):
    """Price/speed table per option for `gpu_hours` of A10G-equivalent work (jobs.estimate's gpuHours)."""
    s = Scheduler(cfg, providers_, state_path=os.devnull)
    rows = []
    for o in s.options():
        n = workers or int(s.pcfg(o.provider).get("max_workers") or 1)
        hours = gpu_hours / o.speed
        rows.append({**o.to_dict(), "workers": n, "gpuHours": round(hours, 2),
                     "wallHours": round(hours / max(n, 1), 2), "usd": round(hours * o.price, 2)})
    return rows


def speed_calibration_from_manifests(manifests, base_class="A10G"):
    """{gpuClass: speed} from worker manifests: model estimate (A10G-based) / measured seconds, median per class."""
    per = {}
    for m in manifests:
        g, est, got = m.get("gpuClass"), m.get("estSeconds"), m.get("gpuSeconds")
        if m.get("status") == "DONE" and g and est and got:
            per.setdefault(g, []).append(float(est) / float(got))
    out = {g: round(statistics.median(v), 3) for g, v in per.items()}
    if base_class in out and out[base_class] > 0:  # keep A10G == 1.0 as the unit
        b = out[base_class]
        out = {g: round(v / b, 3) for g, v in out.items()}
    return out


class OfflineTransport:
    """For plan/dry-run: any HTTP call fails, so providers fall back to their static price tables."""

    def __call__(self, method, url, headers, body, timeout=30):
        raise prov.ProviderError(f"offline: {method} {url}")


def build_providers(cfg, env=None, offline=False, state_dir=DEFAULT_STATE, aws_session=None):
    env = dict(os.environ if env is None else env)
    out = {}
    for name in cfg["order"]:
        pc = cfg["providers"].get(name) or {}
        if not pc.get("enabled", True):
            continue
        if name in ("runpod", "vastai"):
            kw = {"transport": OfflineTransport()} if offline else {}
            e = {k: ("" if offline else v) for k, v in env.items()}
            out[name] = prov.make(name, pc, e, **kw)
        elif name == "aws_ec2":
            out[name] = prov.make(name, pc, env, session=aws_session)
        else:
            out[name] = prov.make(name, pc, env, state_dir=state_dir)
    return out


def external_secrets(env=None):
    env = os.environ if env is None else env
    return {"AWS_ACCESS_KEY_ID": env.get("FARM_EXTERNAL_AWS_ACCESS_KEY_ID", ""),
            "AWS_SECRET_ACCESS_KEY": env.get("FARM_EXTERNAL_AWS_SECRET_ACCESS_KEY", ""),
            "GIT_TOKEN": env.get("FARM_GIT_TOKEN", "")}


def dry_run(cfg, out_dir, farm=None, commit=None, gpu_hours=None):
    """Render everything a launch would send, to files, with secrets redacted. No network, no spend."""
    os.makedirs(os.path.join(out_dir, "payloads"), exist_ok=True)
    # placeholders are shell-safe on purpose (Vast's env is a docker-flag string)
    farm = farm or {"bucket": "story-farm-ACCOUNT-us-east-1", "region": "us-east-1",
                    "queue_url": "https://sqs.us-east-1.amazonaws.com/ACCOUNT/story-farm-render",
                    "table": "story-farm-jobs"}
    secrets = {"AWS_ACCESS_KEY_ID": "FARM_EXTERNAL_AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY":
               "FARM_EXTERNAL_AWS_SECRET_ACCESS_KEY", "GIT_TOKEN": "FARM_GIT_TOKEN"}
    ccfg = cfg.get("code") or {}
    try:
        commit = commit or ccfg.get("commit") or startup.git_head()
        code = startup.code_settings(ccfg, commit)
    except Exception:  # noqa: BLE001 - no git here: still render, with a placeholder
        code = startup.code_settings({**ccfg, "git_url": ccfg.get("git_url") or "https://github.com/OWNER/REPO.git"},
                                     commit or "COMMIT")
    script = startup.render_startup(code)
    boot = startup.bootstrap_command(script)
    files = {}

    def write(rel, text):
        p = os.path.join(out_dir, rel)
        with open(p, "w") as fh:
            fh.write(text)
        files[rel] = os.path.getsize(p)

    write("startup.sh", script)
    write("bootstrap.txt", boot + "\n")
    provs = build_providers(cfg, env={}, offline=True, state_dir=os.path.join(out_dir, "state"))
    s = Scheduler(cfg, provs, farm, secrets, state_path=os.path.join(out_dir, "state", "scheduler.json"), code=code)
    for name, p in provs.items():
        for g in p.gpu_classes():
            env = startup.redact(s.env_for(name, g)) if name in EXTERNAL else s.env_for(name, g)
            if name == "runpod":
                bodies = [p.pod_payload(0, g, c, env, boot) for c in p.clouds()]
                if p.cfg.get("interruptible"):
                    bodies.append(p.interruptible_payload(0, g, p.clouds()[0], env, boot,
                                                          p.cfg.get("bid_per_gpu") or 0.3))
                payload = {"method": "POST", "url": f"{p.http.base}/v2/pods", "bodies": bodies}
            elif name == "vastai":
                payload = {"search": {"method": "POST", "url": f"{p.http.base}/api/v0/bundles",
                                      "body": p.offer_query(g, spot=False)},
                           "create": {"method": "PUT", "url": f"{p.http.base}/api/v0/asks/<offer_id>",
                                      "body": p.create_payload(0, g, env, boot)}}
            elif name == "aws_ec2":
                payload = {"calls": ["service-quotas:GetServiceQuota ec2/L-3819A6DF",
                                     "service-quotas:GetServiceQuota ec2/L-DB2E81BA",
                                     "autoscaling:SetDesiredCapacity <stack>-spot-workers (+n)"],
                           "note": "workers boot from the launch template user data (ECR image)"}
            else:
                payload = {"argv": [sys.executable, "cloud/farm/worker.py"], "env": {**env, "REQUIRE_GPU": "0"}}
            write(f"payloads/{name}-{g}.json", json.dumps(payload, indent=1) + "\n")
    rows = plan_table(cfg, provs, gpu_hours or 41.9)
    write("plan.json", json.dumps({"gpuHoursA10G": gpu_hours or 41.9, "options": rows}, indent=1) + "\n")
    return files


# ---------------------------------------------------------------------------------------------- live glue
def farm_backlog(farm_obj):
    """(jobs waiting or running, A10G GPU-seconds left) from SQS + the job table."""
    import farmio
    a = farm_obj.sqs.get_queue_attributes(QueueUrl=farm_obj.queue_url, AttributeNames=[
        "ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"])["Attributes"]
    n = int(a.get("ApproximateNumberOfMessages", 0)) + int(a.get("ApproximateNumberOfMessagesNotVisible", 0))
    secs = 0.0
    for r in farm_obj.store.list_runs():
        if r.get("status") in ("QUEUED", "RUNNING"):
            secs += sum(float(j.get("estSeconds") or 0) for j in farm_obj.store.list_jobs(r["runId"])
                        if j.get("status") not in farmio.TERMINAL_JOB)
    return n, (secs if secs else 900.0 * n)


def scheduler_for(farm_obj, cfg_path=CONFIG, region="us-east-1", state_dir=DEFAULT_STATE, env=None):
    cfg = load_config(cfg_path)
    import boto3
    sess = boto3.session.Session(region_name=region)
    provs = build_providers(cfg, env, state_dir=state_dir, aws_session=sess)
    farm = {"bucket": farm_obj.bucket, "queue_url": farm_obj.queue_url, "table": farm_obj.store.table,
            "region": region}
    return Scheduler(cfg, provs, farm, external_secrets(env), heartbeats=farm_obj.store.list_heartbeats,
                     state_path=os.path.join(state_dir, "scheduler.json"),
                     code=ensure_code(cfg, farm_obj) if any(n in provs for n in EXTERNAL) else None)


def ensure_code(cfg, farm_obj):
    """FARM_CODE_* settings; for code.source = s3 also upload farm/code/<commit>.tar.gz once (idempotent)."""
    import farmio
    ccfg = cfg.get("code") or {}
    commit = ccfg.get("commit") or startup.git_head()
    if ccfg.get("source", "git") != "s3":
        return startup.code_settings(ccfg, commit)
    key = startup.code_key(commit)
    data, sha = startup.code_bundle(commit)
    if not farmio.s3_exists(farm_obj.s3, farm_obj.bucket, key):
        farm_obj.s3.put_object(Bucket=farm_obj.bucket, Key=key, Body=data, ContentType="application/gzip")
    return startup.code_settings(ccfg, commit, key, sha)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--config", default=os.environ.get("FARM_PROVIDERS", CONFIG))
    p.add_argument("--stack", default=os.environ.get("FARM_STACK"))
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    p.add_argument("--state-dir", default=DEFAULT_STATE)
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("plan")
    sp.add_argument("--spec", action="append")
    sp.add_argument("--quality", default="final")
    sp.add_argument("--gpu-hours", type=float, default=None)
    sp.add_argument("--workers", type=int, default=None)
    sp = sub.add_parser("dry-run")
    sp.add_argument("--out", required=True)
    sp.add_argument("--commit", default=None)
    sub.add_parser("status").add_argument("--probe", action="store_true", help="also call available()")
    sub.add_parser("tick")
    sub.add_parser("stop-all")
    sp = sub.add_parser("calibrate")
    sp.add_argument("--manifests", required=True, help="dir of farm/runs/<run>/jobs/*.json")
    sp.add_argument("--out", default=None)
    a = p.parse_args(argv)
    cfg = load_config(a.config)

    def out(o):
        json.dump(o, sys.stdout, indent=1, default=str)
        sys.stdout.write("\n")

    if a.cmd == "plan":
        gh = a.gpu_hours
        if gh is None:
            import jobs as jobsplit
            gh = 0.0
            for path in a.spec or []:
                with open(path) as fh:
                    spec = json.load(fh)
                gh += jobsplit.estimate(jobsplit.split_episode(spec, a.quality), 1.0, 1)["gpuHours"]
        return out({"gpuHoursA10G": round(gh, 2),
                    "options": plan_table(cfg, build_providers(cfg, offline=True, state_dir=a.state_dir), gh,
                                          a.workers)})
    if a.cmd == "dry-run":
        return out(dry_run(cfg, a.out, commit=a.commit))
    if a.cmd == "calibrate":
        ms = []
        for path in glob.glob(os.path.join(a.manifests, "*.json")):
            with open(path) as fh:
                ms.append(json.load(fh))
        cal = speed_calibration_from_manifests(ms)
        if a.out:
            with open(a.out, "w") as fh:
                json.dump(cal, fh, indent=1)
        return out(cal)
    import orchestrator
    farm_obj = orchestrator.farm_from_args(a)
    s = scheduler_for(farm_obj, a.config, a.region, a.state_dir)
    if a.cmd == "status":
        return out(s.status(probe=a.probe))
    if a.cmd == "tick":
        return out(s.tick(*farm_backlog(farm_obj)))
    if a.cmd == "stop-all":
        return out(s.stop_all())


if __name__ == "__main__":
    sys.exit(main() or 0)
