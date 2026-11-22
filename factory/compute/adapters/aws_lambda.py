"""
aws_lambda.py - render chunks on the Blender container-image Lambda (factory/compute/aws_lambda/).

start():  lambda.invoke(InvocationType="Event", Payload={"manifestUrl", "chunk", "attempt"}) -> 202 + RequestId.
          Up to the account's concurrency (ConcurrentExecutions / UnreservedConcurrentExecutions; 10 today).
poll():   the function's CloudWatch log group: the REPORT line of that RequestId gives the end of the task and
          the BILLED duration and memory -> exact GB-s for the ledger; "Task timed out" / errors -> failed. The
          broker treats a task as done only when its done marker + frames are in S3.
quota:    400 000 GB-s + 1 000 000 requests per month free (AWS always-free tier), shared with every other
          function in the account: account_usage() reads AWS/Lambda Duration x MemorySize for ALL functions
          this month from CloudWatch, which the broker feeds to Ledger.observe() before planning.
"""
import json
import re

from .base import Adapter, AuthError, CapacityError, ProviderError, QuotaError

REPORT_RE = re.compile(r"REPORT RequestId: (\S+)\s+Duration: ([0-9.]+) ms\s+Billed Duration: (\d+) ms\s+"
                       r"Memory Size: (\d+) MB\s+Max Memory Used: (\d+) MB(?:\s+Init Duration: ([0-9.]+) ms)?")
ERR_RE = re.compile(r"(\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b).*?"
                    r"(Task timed out|Runtime\.\w+|Error: Runtime exited)")


class AwsLambda(Adapter):
    name = "aws_lambda"

    def __init__(self, pid, cfg, session=None, clock=None, lam=None, logs=None, cw=None):
        super().__init__(pid, cfg, clock)
        c = cfg.get("config") or {}
        self.function = c.get("function", "story-compute-render")
        self.region = c.get("region", "us-east-1")
        self.memory_mb = int(c.get("memory_mb", 10240))
        self.session = session
        self._lam, self._logs, self._cw = lam, logs, cw
        self.reports = {}
        self.errors = {}
        self._account_limit = None

    # --- clients
    def _client(self, name):
        import boto3
        sess = self.session or boto3.session.Session(region_name=self.region)
        return sess.client(name, region_name=self.region)

    @property
    def lam(self):
        if self._lam is None:
            self._lam = self._client("lambda")
        return self._lam

    @property
    def logs(self):
        if self._logs is None:
            self._logs = self._client("logs")
        return self._logs

    @property
    def cw(self):
        if self._cw is None:
            self._cw = self._client("cloudwatch")
        return self._cw

    # --- capability
    def available(self):
        try:
            f = self.lam.get_function_configuration(FunctionName=self.function)
        except Exception as e:  # noqa: BLE001
            return False, f"{self.function}: {type(e).__name__}: {str(e)[:160]}"
        if f.get("State") not in (None, "Active"):
            return False, f"{self.function} state {f.get('State')}"
        self.memory_mb = int(f.get("MemorySize") or self.memory_mb)
        try:
            acct = self.lam.get_account_settings()["AccountLimit"]
            self._account_limit = int(acct.get("UnreservedConcurrentExecutions") or acct.get("ConcurrentExecutions"))
        except Exception:  # noqa: BLE001
            pass
        return True, f"{self.function} {self.memory_mb} MB, account concurrency {self._account_limit}"

    def concurrency(self):
        c = int(self.cfg.get("concurrency") or 10)
        return min(c, self._account_limit) if self._account_limit else c

    def worker_profile(self):
        p = super().worker_profile()
        p["ramGb"] = self.memory_mb / 1024.0
        return p

    def usage_estimate(self, est_s):
        return {"GB-s": float(est_s) * self.memory_mb / 1024.0, "requests": 1.0}

    def price_per_task(self, est_s):
        q = self.cfg.get("quota") or {}
        return float(q.get("unit_usd") or 0.0000166667) * est_s * self.memory_mb / 1024.0 + 0.0000002

    # --- tasks
    def start(self, task):
        payload = {"manifestUrl": task["manifestUrl"], "chunk": task["chunk"], "attempt": task["attempt"]}
        try:
            r = self.lam.invoke(FunctionName=self.function, InvocationType="Event", Payload=json.dumps(payload))
        except Exception as e:  # noqa: BLE001
            code = getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__)
            if code in ("TooManyRequestsException", "EC2ThrottledException", "ResourceConflictException"):
                raise CapacityError(f"lambda {code}") from e
            if code in ("AccessDeniedException", "UnrecognizedClientException"):
                raise AuthError(f"lambda {code}") from e
            if code in ("CodeStorageExceededException",):
                raise QuotaError(f"lambda {code}") from e
            raise ProviderError(f"lambda invoke: {code}: {str(e)[:200]}") from e
        status = r.get("StatusCode")
        if status != 202:
            raise ProviderError(f"lambda async invoke returned {status}")
        rid = r["ResponseMetadata"]["RequestId"]
        h = {"attempt": task["attempt"], "requestId": rid, "t0": self.clock(), "provider": self.pid}
        self.running[task["attempt"]] = h
        return h

    def refresh(self):
        """Read REPORT / error lines for every running request (one paginated FilterLogEvents per tick)."""
        pending = {h["requestId"]: h for h in self.running.values() if h["requestId"] not in self.reports}
        if not pending:
            return
        start_ms = int(min(h["t0"] for h in pending.values()) * 1000) - 60000
        kw = {"logGroupName": f"/aws/lambda/{self.function}", "startTime": start_ms,
              "filterPattern": '?REPORT ?"Task timed out" ?"Runtime." ?"Error: Runtime"'}
        try:
            for page in self.logs.get_paginator("filter_log_events").paginate(**kw):
                for ev in page.get("events", []):
                    msg = ev.get("message", "")
                    m = REPORT_RE.search(msg)
                    if m and m.group(1) in pending:
                        self.reports[m.group(1)] = {
                            "durationMs": float(m.group(2)), "billedMs": int(m.group(3)),
                            "memoryMb": int(m.group(4)), "maxMemoryMb": int(m.group(5)),
                            "initMs": float(m.group(6)) if m.group(6) else None}
                        continue
                    e = ERR_RE.search(msg)
                    if e and e.group(1) in pending:
                        self.errors[e.group(1)] = msg.strip()[:300]
        except Exception as e:  # noqa: BLE001 - log group not created yet (no invocation finished)
            if "ResourceNotFoundException" not in f"{type(e).__name__}{e}":
                raise

    def poll(self, handle):
        rid = handle["requestId"]
        rep = self.reports.get(rid)
        if rep:
            gbs = rep["billedMs"] / 1000.0 * rep["memoryMb"] / 1024.0
            return {"state": "failed" if rid in self.errors else "exited", "report": rep,
                    "usage": {"GB-s": round(gbs, 3), "requests": 1.0}, "error": self.errors.get(rid)}
        timeout = float(self.cfg.get("max_runtime_s", 900))
        if self.clock() - handle["t0"] > timeout + 600:
            return {"state": "lost", "usage": self.usage_estimate(timeout), "error": "no REPORT line"}
        return {"state": "running"}

    # --- account meter (free tier is account-wide)
    def account_usage(self, since_epoch, until_epoch=None):
        import datetime as dt
        until_epoch = until_epoch or self.clock()
        start = dt.datetime.fromtimestamp(since_epoch, dt.timezone.utc)
        end = dt.datetime.fromtimestamp(until_epoch, dt.timezone.utc)
        gbs = reqs = 0.0
        per = {}
        for page in self.lam.get_paginator("list_functions").paginate():
            for f in page["Functions"]:
                name, mem = f["FunctionName"], float(f.get("MemorySize") or 128)
                dims = [{"Name": "FunctionName", "Value": name}]
                d = self.cw.get_metric_statistics(Namespace="AWS/Lambda", MetricName="Duration", Dimensions=dims,
                                                  StartTime=start, EndTime=end, Period=86400 * 31,
                                                  Statistics=["Sum"])
                i = self.cw.get_metric_statistics(Namespace="AWS/Lambda", MetricName="Invocations",
                                                  Dimensions=dims, StartTime=start, EndTime=end,
                                                  Period=86400 * 31, Statistics=["Sum"])
                ms = sum(p["Sum"] for p in d.get("Datapoints", []))
                n = sum(p["Sum"] for p in i.get("Datapoints", []))
                g = ms / 1000.0 * mem / 1024.0
                per[name] = {"GB-s": round(g, 1), "invocations": int(n), "memoryMb": int(mem)}
                gbs += g
                reqs += n
        return {"GB-s": round(gbs, 3), "requests": reqs, "functions": per}
