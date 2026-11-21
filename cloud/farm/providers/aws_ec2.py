"""
providers/aws_ec2.py - the existing CloudFormation farm (spot ASG + on-demand fallback ASG, launch template that
pulls the worker image from ECR) behind the Provider interface.

available(): reads the G/VT vCPU quotas with service-quotas (read-only) - spot L-3819A6DF, on-demand L-DB2E81BA -
             and returns (False, reason) when both are 0 (the account state on 2026-11-21: requests CASE_OPENED),
             or when the groups recently failed to launch (InsufficientInstanceCapacity / VcpuLimitExceeded in the
             scaling activities).
launch():    raises the desired capacity of the spot group (or of the on-demand group when spot quota is 0 / spot
             is disabled) by n, clamped to the group max and to quota/4 vCPU per xlarge worker. Instances come up
             asynchronously; the scheduler's health timeout catches groups that never deliver.
list():      instances of both groups. terminate(): terminate-in-ASG with decrement (so the group does not replace).

The GPU class is what the launch template's instance types give (g6 = L4, g5 = A10G); `gpu_class` picks nothing
here, it is only recorded.
"""
import time

from .base import (FAILED, PENDING, RUNNING, TERMINATED, AuthError, CapacityError, Provider, ProviderError,
                   QuotaError, WorkerHandle)

SPOT_QUOTA, ONDEMAND_QUOTA = "L-3819A6DF", "L-DB2E81BA"
VCPU_PER_WORKER = 4  # g6.xlarge / g5.xlarge
LAUNCH_FAILURES = ("InsufficientInstanceCapacity", "VcpuLimitExceeded", "MaxSpotInstanceCountExceeded",
                   "SpotMaxPriceTooLow", "InsufficientCapacity", "Unsupported")


class AwsEc2(Provider):
    name = "aws_ec2"
    gpu_map = {"L4": "g6.xlarge", "A10G": "g5.xlarge"}
    # us-east-1 Linux, read 2026-11-21 (docs/farm.md): spot 7-day median / on-demand
    default_prices = {"L4": 0.60, "A10G": 0.69}
    on_demand_prices = {"L4": 0.8048, "A10G": 1.006}

    def __init__(self, cfg=None, env=None, session=None, clients=None, now=time.time):
        super().__init__(cfg, env)
        self._session, self._clients, self.now = session, dict(clients or {}), now
        self._groups = None

    def client(self, name):
        if name not in self._clients:
            if self._session is None:
                import boto3
                self._session = boto3.session.Session(region_name=self.cfg.get("region", "us-east-1"))
            self._clients[name] = self._session.client(name)
        return self._clients[name]

    def groups(self):
        """{"spot": name, "ondemand": name} from the stack outputs (or config)."""
        if self._groups:
            return self._groups
        g = {"spot": self.cfg.get("spot_group"), "ondemand": self.cfg.get("ondemand_group")}
        if not (g["spot"] and g["ondemand"]):
            stack = self.cfg.get("stack", "story-farm")
            r = self.client("cloudformation").describe_stacks(StackName=stack)["Stacks"][0]
            o = {x["OutputKey"]: x["OutputValue"] for x in r.get("Outputs", [])}
            g = {"spot": o["SpotGroupName"], "ondemand": o["OnDemandGroupName"]}
        self._groups = g
        return g

    def quota(self, code):
        r = self.client("service-quotas").get_service_quota(ServiceCode="ec2", QuotaCode=code)
        return float(r["Quota"]["Value"])

    def quota_workers(self):
        return {"spot": int(self.quota(SPOT_QUOTA) // VCPU_PER_WORKER),
                "ondemand": int(self.quota(ONDEMAND_QUOTA) // VCPU_PER_WORKER)}

    def recent_launch_failure(self, window_s=900):
        for kind, name in self.groups().items():
            acts = self.client("autoscaling").describe_scaling_activities(AutoScalingGroupName=name,
                                                                           MaxRecords=10).get("Activities", [])
            for a in acts:
                t = a.get("StartTime")
                ts = t.timestamp() if hasattr(t, "timestamp") else float(t or 0)
                if a.get("StatusCode") in ("Failed", "Cancelled") and self.now() - ts < window_s:
                    msg = a.get("StatusMessage", "")
                    if any(f in msg for f in LAUNCH_FAILURES):
                        return f"{kind} group: {msg[:160]}"
        return None

    # ------------------------------------------------------------------ interface
    def available(self):
        try:
            q = self.quota_workers()
        except Exception as e:  # noqa: BLE001 - NoCredentials, AccessDenied, network
            return False, f"service-quotas: {type(e).__name__}: {str(e)[:160]}"
        if q["spot"] <= 0 and q["ondemand"] <= 0:
            return False, (f"G/VT vCPU quota is 0 (spot {SPOT_QUOTA}, on-demand {ONDEMAND_QUOTA}); "
                           "quota increase pending")
        try:
            self.groups()
            fail = self.recent_launch_failure()
        except Exception as e:  # noqa: BLE001
            return False, f"stack/ASG: {type(e).__name__}: {str(e)[:160]}"
        if fail:
            return False, f"recent launch failure: {fail}"
        return True, f"quota spot {q['spot']} / on-demand {q['ondemand']} workers"

    def price_per_hour(self, gpu_class, spot=True):
        table = self.default_prices if spot else self.on_demand_prices
        p = (self.cfg.get("prices") or {}).get(gpu_class) if spot else None
        return float(p if p is not None else table.get(gpu_class, table["A10G"]))

    def _group(self, name):
        r = self.client("autoscaling").describe_auto_scaling_groups(AutoScalingGroupNames=[name])
        gs = r.get("AutoScalingGroups", [])
        if not gs:
            raise ProviderError(f"ASG {name} not found")
        return gs[0]

    def launch(self, n, gpu_class, env, startup, spot=True):
        """`env`/`startup` are baked into the launch template's user data; they are not used here."""
        try:
            q = self.quota_workers()
        except Exception as e:  # noqa: BLE001
            raise AuthError(f"service-quotas: {e}") from e
        kind = "spot" if spot and q["spot"] > 0 else "ondemand"
        if q[kind] <= 0:
            raise QuotaError(f"aws {kind} G/VT quota is 0")
        g = self._group(self.groups()[kind])
        live = [i for i in g.get("Instances", []) if not i["LifecycleState"].startswith("Terminat")]
        target = min(int(g["MaxSize"]), q[kind], max(int(g["DesiredCapacity"]), len(live)) + n)
        add = target - int(g["DesiredCapacity"])
        if add <= 0:
            raise CapacityError(f"aws {kind} group at its limit (max {g['MaxSize']}, quota {q[kind]} workers)")
        self.client("autoscaling").set_desired_capacity(AutoScalingGroupName=g["AutoScalingGroupName"],
                                                        DesiredCapacity=target, HonorCooldown=False)
        price = self.price_per_hour(gpu_class, spot=(kind == "spot"))
        # instances do not exist yet: placeholder handles, replaced by real ids on the next list()
        return [WorkerHandle(self.name, f"pending-{kind}-{int(self.now())}-{i}", gpu_class, PENDING, price,
                             kind == "spot", detail={"group": g["AutoScalingGroupName"], "placeholder": True})
                for i in range(add)]

    def list(self):
        out = []
        for kind, name in self.groups().items():
            g = self._group(name)
            for i in g.get("Instances", []):
                st = i["LifecycleState"]
                state = (RUNNING if st == "InService" else TERMINATED if st.startswith("Terminat")
                         else FAILED if i.get("HealthStatus") == "Unhealthy" else PENDING)
                cls = next((k for k, v in self.gpu_map.items() if v.split(".")[0] == i.get("InstanceType", "")
                            .split(".")[0]), "A10G")
                out.append(WorkerHandle(self.name, i["InstanceId"], cls, state,
                                        self.price_per_hour(cls, spot=(kind == "spot")), kind == "spot",
                                        detail={"group": name, "instanceType": i.get("InstanceType")}))
        return out

    def terminate(self, ids):
        done = []
        for iid in ids:
            if iid.startswith("pending-"):
                # a placeholder that never became an instance: give the desired capacity back
                kind = iid.split("-")[1]
                g = self._group(self.groups()[kind])
                live = [i for i in g.get("Instances", []) if not i["LifecycleState"].startswith("Terminat")]
                want = max(len(live), int(g["DesiredCapacity"]) - 1)
                if want < int(g["DesiredCapacity"]):
                    self.client("autoscaling").set_desired_capacity(AutoScalingGroupName=g["AutoScalingGroupName"],
                                                                    DesiredCapacity=want, HonorCooldown=False)
                done.append(iid)
                continue
            try:
                self.client("autoscaling").terminate_instance_in_auto_scaling_group(
                    InstanceId=iid, ShouldDecrementDesiredCapacity=True)
                done.append(iid)
            except Exception as e:  # noqa: BLE001
                if "not found" in str(e).lower() or "ValidationError" in str(e):
                    done.append(iid)
                else:
                    raise ProviderError(f"terminate {iid}: {e}") from e
        return done
