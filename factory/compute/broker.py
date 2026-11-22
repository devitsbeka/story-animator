"""
broker.py - one render job split across MANY providers at once, free capacity first.

    b = Broker.from_env(providers=["aws_lambda", "local_cpu"])
    run = b.submit("episodes/sentinel/episode_v5.json", quality="preview", frames=(0, 23), res="270x480",
                   samples=12, deadline_min=30, budget=0, allow_paid=False)
    b.run_until_done(run)            # tick loop; or b.tick(run) from another loop (cloud/farm/scheduler.py)

Per tick:
  1. reconcile running tasks: done marker in S3 -> verify frames (trusted: plates present; untrusted: sha256 +
     PNG header + attempt-scoped copy + deterministic spot checks) -> queue.complete (first result wins) ->
     ledger.commit(measured usage) -> calibration; provider failure / lost / exited-without-marker -> lease
     released (the atom becomes claimable by ANY provider), usage still committed, provider strikes.
  2. re-plan with the remaining frames, elapsed time and live providers (planner.plan) -> target workers each.
  3. fill free slots: for each provider in plan order, claim the next chunk sized for that provider from the
     shared queue (work stealing), reserve its quota in the ledger (refused if it would exceed the free tier
     and paid overflow is not allowed), write the presigned chunk manifest, start the task.
     Nothing left to claim -> speculative copies of stragglers on faster free workers.
State: compute/runs/<run>/broker.json in S3 (and ~/.story-compute/runs/<run>.json).
"""
import hashlib
import json
import math
import os
import statistics
import sys
import time

from . import planner as planmod
from . import registry as reg
from .ledger import BudgetExceeded, Ledger, QuotaExceeded, period_start
from .members import Members, MemberNodes, spot_check_selected
from .store import S3Store
from .workqueue import Lease, WorkQueue, make_atoms

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FARM = os.path.join(REPO, "cloud", "farm")
ROOT = "compute/"
TERMINAL = ("COMPLETE", "FAILED", "STOPPED", "INFEASIBLE")


def _farm():
    if FARM not in sys.path:
        sys.path.insert(0, FARM)
    import jobs as jobsplit  # noqa: E402
    import presigned  # noqa: E402
    return jobsplit, presigned


def log(msg, **kw):
    print(json.dumps({"t": round(time.time(), 1), "msg": msg, **kw}, default=str), file=sys.stderr, flush=True)


def png_size(data):
    """(width, height) from a PNG's IHDR, or None if it is not a complete PNG."""
    if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR" or not data.endswith(
            b"IEND\xaeB`\x82"):
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def psnr_downsampled(a_bytes, b_bytes, factor=4):
    """PSNR (dB) of two PNGs after a box downsample (robust to Monte-Carlo noise, sensitive to wrong content)."""
    import io

    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(io.BytesIO(a_bytes)).convert("RGB"), dtype=np.float64)
    b = np.asarray(Image.open(io.BytesIO(b_bytes)).convert("RGB"), dtype=np.float64)
    if a.shape != b.shape:
        return 0.0
    h, w = (a.shape[0] // factor) * factor, (a.shape[1] // factor) * factor

    def ds(x):
        return x[:h, :w].reshape(h // factor, factor, w // factor, factor, 3).mean(axis=(1, 3))
    mse = float(((ds(a) - ds(b)) ** 2).mean())
    return 99.0 if mse <= 1e-9 else 10 * math.log10(255.0 ** 2 / mse)


def build_adapters(cfgs, session=None, members=None, clock=time.time, overrides=None):
    from .adapters import make
    out = {}
    for pid, cfg in cfgs.items():
        if overrides and pid in overrides:
            out[pid] = overrides[pid]
            continue
        out[pid] = make(pid, cfg, session=session, members=members, clock=clock)
    return out


class Broker:
    def __init__(self, s3, bucket, store=None, ledger=None, config=None, adapters=None, clock=time.time,
                 sleep=time.sleep, state_dir=None, root=ROOT, repo=REPO, session=None):
        self.s3, self.bucket = s3, bucket
        self.store = store or S3Store(s3, bucket)
        self.ledger = ledger or Ledger(self.store, prefix=root + "ledger/", clock=clock)
        self.config = config or reg.load()
        self.clock, self.sleep = clock, sleep
        self.state_dir = state_dir or os.path.join(reg.state_dir(), "runs")
        self.root = root
        self.repo = repo
        self.members = Members(self.store, s3, bucket, clock=clock)
        self.adapters = adapters if adapters is not None else build_adapters(
            self.config["providers"], session=session, members=self.members, clock=clock)
        jobsplit, presigned = _farm()
        self.jobsplit, self.presigned = jobsplit, presigned
        self.layout = presigned.Layout(root=root)
        self.defaults = {"safety": 0.05, "chunk_runtime_fraction": 0.6, "spot_check_fraction": 0.02,
                         "lease_margin_s": 120, **(self.config.get("defaults") or {})}
        self.ledger.safety = float(self.defaults["safety"])

    @classmethod
    def from_env(cls, providers=None, allow_care=(), region="us-east-1", farm_stack="story-farm", **kw):
        import boto3
        from botocore.config import Config
        sess = boto3.session.Session(region_name=region)
        s3 = sess.client("s3", config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"},
                                             retries={"max_attempts": 8, "mode": "adaptive"}))
        outs = sess.client("cloudformation").describe_stacks(StackName=farm_stack)["Stacks"][0]["Outputs"]
        bucket = {o["OutputKey"]: o["OutputValue"] for o in outs}["BucketName"]
        cfg = reg.load(providers=providers, allow_care=allow_care)
        return cls(s3, bucket, config=cfg, session=sess, **kw)

    # ------------------------------------------------------------------------------------------- state
    def _state_key(self, run):
        return f"{self.root}runs/{run}/broker.json"

    def save(self, st):
        st["updatedAt"] = self.clock()
        self.store.put_json(self._state_key(st["runId"]), st)
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            with open(os.path.join(self.state_dir, f"{st['runId']}.json"), "w") as fh:
                json.dump(st, fh, indent=1, default=str)
        except OSError:
            pass

    def load(self, run):
        st, _ = self.store.get_json(self._state_key(run))
        if not st:
            raise KeyError(f"no broker state for run {run}")
        return st

    def queue(self, run):
        return WorkQueue(self.store, prefix=f"{self.root}runs/{run}/queue", clock=self.clock)

    def event(self, st, what, **kw):
        st.setdefault("events", []).append({"t": round(self.clock(), 1), "ev": what, **kw})
        st["events"] = st["events"][-400:]

    # ------------------------------------------------------------------------------------------- quota
    def quota(self, pid):
        return (self.config["providers"].get(pid) or {}).get("quota") or None

    def observe_meters(self):
        """Account-wide meters (Lambda: every function in the account shares the free tier)."""
        out = {}
        for pid, ad in self.adapters.items():
            q = self.quota(pid)
            if q and hasattr(ad, "account_usage"):
                try:
                    u = ad.account_usage(period_start(q.get("period", "month"), self.clock()))
                    self.ledger.observe(pid, q, u.get(q["unit"], 0.0), source="cloudwatch")
                    out[pid] = u
                except Exception as e:  # noqa: BLE001
                    out[pid] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
        return out

    # ------------------------------------------------------------------------------------------- planning
    def provider_inputs(self, st=None):
        rows = []
        for pid, ad in self.adapters.items():
            cfg = self.config["providers"].get(pid, {})
            ok, why = ad.available()
            if st and pid in st.get("disabled", {}):
                ok, why = False, st["disabled"][pid]
            prof = {**reg.profile(pid, cfg), **ad.worker_profile()}
            prof["concurrency"] = ad.concurrency()
            q = cfg.get("quota") or {}
            free_ = not cfg.get("price_usd_h")
            ledger_free = usage_per_s = None
            if q.get("unit") and q.get("free") is not None:
                ledger_free = self.ledger.remaining_free(pid, q)
                usage_per_s = ad.usage_estimate(1.0).get(q["unit"], 0.0)
            price_s = 0.0
            if not free_:
                price_s = float(cfg.get("price_usd_h") or 0) / 3600.0
            elif ledger_free is not None and ledger_free <= 0 and st and st.get("allowPaid"):
                free_, price_s, ledger_free = False, ad.price_per_task(1.0), None
            rows.append({"id": pid, "profile": prof, "free": free_, "ledgerFree": ledger_free,
                         "usagePerS": usage_per_s, "priceUsdPerS": price_s, "priority": cfg.get("priority", 50),
                         "available": ok and prof["concurrency"] > 0, "reason": why,
                         "concurrency": prof["concurrency"]})
        return rows

    def make_plan(self, frames, quality, deadline_s, budget, allow_paid, st=None, shot_frames=None):
        return planmod.plan(frames, quality, self.provider_inputs(st), deadline_s, budget, allow_paid,
                            shot_frames=shot_frames,
                            runtime_fraction=float(self.defaults["chunk_runtime_fraction"]))

    def plan_job(self, spec_path, quality="preview", frames=None, res=None, samples=None, deadline_min=None,
                 budget=None, allow_paid=False):
        with open(spec_path) as fh:
            spec = json.load(fh)
        js = self.jobsplit.split_episode(spec, quality, frame_range=frames, res=res, samples=samples)
        n = sum(j["frames"] for j in js)
        p = self.make_plan(n, quality, deadline_min * 60 if deadline_min else None, budget, allow_paid,
                           shot_frames=max(j["frames"] for j in js) if js else None)
        p["shots"] = sorted({j["shot"] for j in js})
        p["gated"] = self.config.get("gated", {})
        return p

    # ------------------------------------------------------------------------------------------- submit
    def submit(self, spec_path, quality="preview", frames=None, res=None, samples=None, deadline_min=None,
               budget=0.0, allow_paid=False, run_id=None, code_mode="head", library="auto", engine=None,
               extra_args=None, inputs=None):
        with open(spec_path) as fh:
            spec = json.load(fh)
        js = self.jobsplit.split_episode(spec, quality, engine=engine, frame_range=frames, res=res, samples=samples)
        if not js:
            raise SystemExit("no frames selected")
        self.jobsplit.check_coverage(spec, js)
        n = sum(j["frames"] for j in js)
        self.observe_meters()
        deadline_s = deadline_min * 60 if deadline_min else None
        p = self.make_plan(n, quality, deadline_s, budget, allow_paid, shot_frames=max(j["frames"] for j in js))
        if not p["providers"]:
            raise SystemExit(f"no provider can take this job: {json.dumps(p, default=str)[:800]}")
        # atoms: small enough that the smallest planned chunk is a few of them (fair splitting of short jobs)
        atom = min(8, max(1, min(r["chunkFrames"] for r in p["providers"]) // 3))
        run = run_id or f"{spec['id']}-{quality}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime(self.clock()))}"
        farm = self.presigned.PresignedFarm(self.s3, self.bucket, layout=self.layout, repo=self.repo,
                                            state_dir=os.path.join(reg.state_dir(), "presigned"))
        if inputs is None:
            inputs = farm.prepare_inputs(spec_path, spec, run, code_mode=code_mode, library=library)
        now = self.clock()
        q = self.queue(run)
        q.init(make_atoms(js, atom), {"cpu_final": "deadline", "deadline_t": now + deadline_s if deadline_s else None})
        st = {"v": 1, "runId": run, "episodeId": spec["id"], "status": "RUNNING", "quality": quality,
              "frames": n, "res": res, "samples": samples, "createdAt": now,
              "deadlineT": now + deadline_s if deadline_s else None, "budgetUsd": budget, "allowPaid": allow_paid,
              "atomFrames": atom, "inputs": inputs, "plan": p, "tasks": {}, "spentUsd": 0.0, "usage": {},
              "verifications": [], "disabled": {}, "strikes": {}, "extraArgs": extra_args or [], "events": []}
        self.event(st, "submitted", frames=n, atoms=len(q.atoms()), plan=p["providers"], expectedMin=p["expectedMin"])
        self.save(st)
        return st

    # ------------------------------------------------------------------------------------------- manifests
    def chunk_job(self, st, attempt, atoms):
        a0, a1 = atoms[0], atoms[-1]
        est = None
        return {"jobId": attempt, "shot": a0["shot"], "frameStart": a0["frameStart"], "frameEnd": a1["frameEnd"],
                "frames": a1["frameEnd"] - a0["frameStart"] + 1, "quality": a0["quality"], "engine": a0["engine"],
                "res": a0.get("res"), "samples": a0.get("samples"), "estSeconds": est}

    def attempt_plate_key(self, run, attempt, shot, frame):
        return self.layout.pod(run, attempt) + f"plates/{shot}/{int(frame):04d}.png"

    def write_manifest(self, st, attempt, atoms, worker, est_s):
        run = st["runId"]
        job = self.chunk_job(st, attempt, atoms)
        job["estSeconds"] = round(est_s, 1)
        trusted = worker.get("trusted", True)
        expires = int(min(7 * 86400, max(3600, (est_s + 1800) * (1 if trusted else 2))))
        opts = {"expires_s": expires, "require_gpu": bool(worker.get("gpu")) and worker.get("provider") != "member_node",
                "threads": int((self.config["providers"].get(worker["provider"], {}).get("config") or {}).get(
                    "threads", 0)), "exit_when_done": True, "heartbeat_s": 30, "job_attempts": 1,
                "extra_args": st.get("extraArgs") or [], "gpu": worker.get("gpu")}
        man = self.presigned.pod_manifest(self.s3, self.bucket, self.layout, run, attempt, [job], st["inputs"], opts,
                                          now=self.clock())
        if not trusted:   # untrusted: frames go to an attempt-scoped prefix, promoted only after verification
            man["jobs"][0]["plates"] = {
                str(f): self.presigned.presign(self.s3, "PUT", self.bucket,
                                               self.attempt_plate_key(run, attempt, job["shot"], f), expires,
                                               "image/png")
                for f in range(job["frameStart"], job["frameEnd"] + 1)}
        key = self.layout.manifest(run, attempt)
        self.store.put_json(key, man)
        url = self.presigned.presign(self.s3, "GET", self.bucket, key, expires)["url"]
        return url, job

    # ------------------------------------------------------------------------------------------- tick
    def tick(self, st):
        if st["status"] in TERMINAL:
            return st
        q = self.queue(st["runId"])
        for ad in self.adapters.values():
            if hasattr(ad, "refresh"):
                try:
                    ad.refresh()
                except Exception as e:  # noqa: BLE001
                    self.event(st, "refresh_failed", provider=ad.pid, error=str(e)[:200])
        self.reconcile(st, q)
        self.run_verifications(st, q)
        prog = q.progress(self.clock())
        st["progress"] = prog
        open_verifs = [v for v in st["verifications"] if v["status"] in ("pending", "running")]
        if prog["complete"] and not open_verifs:
            for t in st["tasks"].values():         # speculative leftovers: stop paying for them
                if t["status"] == "running":
                    self._cancel(st, t, "run complete")
            st["status"] = "COMPLETE"
            st["completedAt"] = self.clock()
            st["wallS"] = round(st["completedAt"] - st["createdAt"], 1)
            self.event(st, "complete", wallS=st["wallS"], usage=st["usage"], usd=st["spentUsd"])
            self.save(st)
            return st
        if prog["parked"] and not prog["framesQueued"] - sum(
                a["frames"] for a in q.atoms() if a["id"] in prog["parked"]) and not self._running(st):
            st["status"] = "FAILED"
            self.event(st, "failed", parked=prog["parked"])
            self.save(st)
            return st
        remaining = prog["frames"] - prog["framesDone"]
        left_s = (st["deadlineT"] - self.clock()) if st.get("deadlineT") else None
        spent_ok = st.get("budgetUsd") is None or st["spentUsd"] <= float(st["budgetUsd"]) + 1e-9
        p = self.make_plan(max(1, remaining), st["quality"], max(60.0, left_s) if left_s is not None else None,
                           None if st.get("budgetUsd") is None else max(0.0, float(st["budgetUsd"]) - st["spentUsd"]),
                           st["allowPaid"] and spent_ok, st=st)
        st["livePlan"] = {"t": round(self.clock(), 1), "expectedMin": p["expectedMin"], "feasible": p["feasible"],
                          "providers": [{k: r[k] for k in ("provider", "workers", "chunkFrames", "frames")}
                                        for r in p["providers"]]}
        self.fill(st, q, p)
        self.save(st)
        return st

    def _running(self, st, pid=None):
        return [t for t in st["tasks"].values() if t["status"] == "running" and (pid is None or t["provider"] == pid)]

    def fill(self, st, q, p):
        prof_rows = {r["provider"]: r for r in p["providers"]}
        order = [r["provider"] for r in p["providers"]]
        pools = {pid: ad_workers for pid in order if (ad_workers := self.adapters[pid].workers())}
        slots = {pid: max(0, min(prof_rows[pid]["workers"] - len(self._running(st, pid)), len(pools.get(pid, []))))
                 for pid in order}
        queued = (st.get("progress") or {}).get("framesQueued") or 0
        for pid in order:
            ad = self.adapters[pid]
            target = prof_rows[pid]["workers"]
            chunk = prof_rows[pid]["chunkFrames"]
            for worker in pools.get(pid, []):
                if len(self._running(st, pid)) >= target:
                    break
                # adaptive chunk: share what is still queued fairly among the free slots of every provider
                free_slots = max(1, sum(slots.values()))
                share = max(1, math.ceil(queued / free_slots)) if queued else chunk
                max_frames = max(1, min(chunk, share))
                cfgp = self.config["providers"].get(pid, {})
                worker = {**reg.profile(pid, cfgp), **worker}
                max_s = float(worker.get("maxRuntimeS", 900)) * float(self.defaults["chunk_runtime_fraction"])
                worker["leaseS"] = float(worker.get("maxRuntimeS", 900)) + float(self.defaults["lease_margin_s"])
                leases = q.next_chunk(worker, max_frames=max_frames, max_s=max_s,
                                      speculate=worker.get("trusted", True))
                if not leases:
                    break
                if not self.start_task(st, q, ad, worker, leases):
                    break
                queued = max(0, queued - sum(L.record["frames"] for L in leases if not L.spec))
                slots[pid] = max(0, slots[pid] - 1)

    def start_task(self, st, q, ad, worker, leases):
        pid = ad.pid
        atoms = [L.record for L in leases]
        spec = leases[0].spec
        attempt = f"{pid}-{atoms[0]['shot']}-f{atoms[0]['frameStart']:05d}-{atoms[-1]['frameEnd']:05d}-" \
                  f"g{leases[0].gen}{'s' if spec else ''}-{hashlib.sha1(f'{self.clock()}{worker['id']}'.encode()).hexdigest()[:6]}"
        attempt = attempt.replace(":", "_")
        est = q.est(worker, atoms)
        quota = self.quota(pid)
        rid = None
        if quota and quota.get("unit"):
            amount = ad.usage_estimate(est).get(quota["unit"], 0.0) * 1.25
            try:
                res = self.ledger.reserve(pid, quota, amount, allow_paid=st["allowPaid"],
                                          unit_usd=float(quota.get("unit_usd") or 0),
                                          budget=None if st.get("budgetUsd") is None else
                                          max(0.0, float(st["budgetUsd"]) - st["spentUsd"]), tag=attempt)
                rid = res["id"]
            except (QuotaExceeded, BudgetExceeded) as e:
                for L in leases:
                    q.release(L, reason=f"quota: {e}", failed=False)
                st["disabled"][pid] = str(e)[:300]
                self.event(st, "quota_refused", provider=pid, error=str(e)[:300])
                return False
        try:
            url, job = self.write_manifest(st, attempt, atoms, worker, est)
            h = ad.start({"chunk": atoms[0]["id"], "attempt": attempt, "manifestUrl": url, "estS": est,
                          "worker": worker})
        except Exception as e:  # noqa: BLE001 - capacity / API: give the atoms back, cool the provider
            for L in leases:
                q.release(L, reason=f"start failed: {e}", failed=False)
            if rid:
                self.ledger.release(pid, quota, rid)
            self._strike(st, pid, f"start: {type(e).__name__}: {e}")
            return False
        st["tasks"][attempt] = {"attempt": attempt, "provider": pid, "worker": worker["id"], "status": "running",
                                "atoms": [a["id"] for a in atoms], "leases": [{**L.to_dict(), "etag": L.etag}
                                                                             for L in leases],
                                "shot": job["shot"], "frameStart": job["frameStart"], "frameEnd": job["frameEnd"],
                                "frames": job["frames"], "spec": spec, "estS": round(est, 1), "t0": self.clock(),
                                "handle": {k: v for k, v in h.items() if not k.startswith("_")}, "reservation": rid,
                                "trusted": worker.get("trusted", True), "node": worker.get("node")}
        self.event(st, "started", attempt=attempt, provider=pid, frames=job["frames"], estS=round(est, 1), spec=spec)
        return True

    def _leases(self, t):
        return [Lease(x["atom"], x["gen"], x["worker"], x.get("etag"), x["key"], x.get("spec", False)) for x in t["leases"]]

    def _strike(self, st, pid, why):
        n = st["strikes"].get(pid, 0) + 1
        st["strikes"][pid] = n
        self.event(st, "strike", provider=pid, n=n, why=why[:300])
        if n >= 3:
            st["disabled"][pid] = f"3 consecutive failures: {why[:200]}"
            self.event(st, "provider_disabled", provider=pid)

    def _settle(self, st, t, usage):
        pid = t["provider"]
        quota = self.quota(pid)
        actual = None
        if quota and quota.get("unit"):
            actual = usage.get(quota["unit"])
            if actual is None:
                actual = self.adapters[pid].usage_estimate(self.clock() - t["t0"]).get(quota["unit"], 0.0)
            if t.get("reservation"):
                ev = self.ledger.commit(pid, quota, t["reservation"], actual, unit_usd=float(quota.get("unit_usd") or 0))
                st["spentUsd"] = round(st["spentUsd"] + ev["paid"] * float(quota.get("unit_usd") or 0), 6)
        if "usd" in usage:
            st["spentUsd"] = round(st["spentUsd"] + float(usage["usd"]), 6)
        u = st["usage"].setdefault(pid, {})
        for k, v in usage.items():
            u[k] = round(u.get(k, 0.0) + float(v), 4)
        u["tasks"] = u.get("tasks", 0) + 1
        t["usage"] = usage

    def _cancel(self, st, t, why):
        ad = self.adapters[t["provider"]]
        try:
            ad.cancel(t["handle"])
        except Exception:  # noqa: BLE001
            pass
        t["status"] = "cancelled"
        t["endedAt"] = self.clock()
        # a cancelled push task may keep running (an async Lambda cannot be stopped): book its full estimate
        self._settle(st, t, ad.usage_estimate(max(self.clock() - t["t0"], float(t.get("estS") or 0))))
        self.event(st, "cancelled", attempt=t["attempt"], why=why)

    def reconcile(self, st, q):
        run = st["runId"]
        for t in list(st["tasks"].values()):
            if t["status"] != "running":
                continue
            ad = self.adapters[t["provider"]]
            done, _ = self.store.get_json(self.layout.done(run, t["attempt"]))
            pr = ad.poll(t["handle"]) if ad else {"state": "lost"}
            leases = self._leases(t)
            if done is None and pr["state"] == "running":
                if self.clock() - t["t0"] < float(ad.worker_profile().get("maxRuntimeS", 900)):
                    for L in leases:
                        q.heartbeat(L, extend_s=float(ad.worker_profile().get("maxRuntimeS", 900))
                                    + float(self.defaults["lease_margin_s"]))
                    t["leases"] = [{**L.to_dict(), "etag": L.etag} for L in leases]
                continue
            if done is None and pr["state"] == "exited" and self.clock() - t.get("exitSeenT", self.clock()) < 30:
                t.setdefault("exitSeenT", self.clock())        # give the last PUTs a moment to land
                continue
            t["endedAt"] = self.clock()
            t["seconds"] = round(t["endedAt"] - t["t0"], 1)
            t["poll"] = {k: v for k, v in pr.items() if k != "usage"}
            self._settle(st, t, pr.get("usage") or {})
            ad.finish(t["handle"])
            if done is None:
                t["status"] = "failed"
                for L in leases:
                    q.release(L, reason=f"{pr['state']}: {pr.get('error')}", failed=not L.spec)
                self._strike(st, t["provider"], f"{pr['state']}: {pr.get('error')}")
                continue
            ok_frames = self.verify(st, t, q)
            st["strikes"][t["provider"]] = 0 if ok_frames else st["strikes"].get(t["provider"], 0)
            self.calibrate(st, t)

    def verify(self, st, t, q):
        """Accept the frames of a finished task atom by atom. -> number of accepted atoms."""
        run = st["runId"]
        jm, _ = self.store.get_json(self.layout.job_manifest(run, t["attempt"], t["attempt"]))
        files = {int(f["frame"]): f for f in (jm or {}).get("files", [])}
        want_res = st.get("res")
        accepted = 0
        for L, aid in zip(self._leases(t), t["atoms"]):
            atom = next(a for a in q.atoms() if a["id"] == aid)
            frames = range(atom["frameStart"], atom["frameEnd"] + 1)
            good, why = True, None
            if t["trusted"]:
                have = set(self.store.list(f"{self.layout.plates_prefix(run)}{atom['shot']}/"))
                missing = [f for f in frames if self.layout.plate(run, atom["shot"], f) not in have]
                if missing:
                    good, why = False, f"missing frames {missing[:5]}"
            else:
                for f in frames:
                    data, _ = self.store.get(self.attempt_plate_key(run, t["attempt"], atom["shot"], f))
                    meta = files.get(f)
                    if data is None or meta is None:
                        good, why = False, f"frame {f} missing"
                        break
                    if hashlib.sha256(data).hexdigest() != meta.get("sha256"):
                        good, why = False, f"frame {f} sha256 differs from the node's manifest"
                        break
                    size = png_size(data)
                    if size is None or (want_res and f"{size[0]}x{size[1]}" != want_res):
                        good, why = False, f"frame {f} not a complete PNG of {want_res}: {size}"
                        break
            if not good:
                q.release(L, reason=f"verify: {why}", failed=not L.spec)
                self.event(st, "rejected", attempt=t["attempt"], atom=aid, why=why)
                if not t["trusted"] and t.get("node"):
                    self.members.update_record(t["node"], strikes=1)
                continue
            if not t["trusted"]:
                if q.result(aid):          # someone else already delivered it
                    q.complete(L, {"attempt": t["attempt"]})
                    continue
                for f in frames:
                    self.s3.copy_object(Bucket=self.bucket, Key=self.layout.plate(run, atom["shot"], f),
                                        CopySource={"Bucket": self.bucket,
                                                    "Key": self.attempt_plate_key(run, t["attempt"], atom["shot"], f)},
                                        ContentType="image/png", MetadataDirective="REPLACE")
            won = q.complete(L, {"attempt": t["attempt"], "provider": t["provider"], "node": t.get("node"),
                                 "trusted": t["trusted"], "sha256": {str(f): files.get(f, {}).get("sha256")
                                                                     for f in frames}})
            if won:
                accepted += 1
                if not t["trusted"] and t.get("node"):
                    rec = self.members.update_record(t["node"], accepted=1) or {}
                    first = int(rec.get("accepted", 1)) == 1
                    if first or spot_check_selected(t["attempt"] + aid, float(self.defaults["spot_check_fraction"])):
                        st["verifications"].append({"atom": aid, "node": t["node"], "attempt": t["attempt"],
                                                    "status": "pending", "why": "probation" if first else "sampled",
                                                    "t": self.clock()})
            else:
                self.event(st, "duplicate", attempt=t["attempt"], atom=aid)
        t["status"] = "done" if accepted == len(t["atoms"]) else ("partial" if accepted else "duplicate"
                                                                    if t.get("spec") else "rejected")
        self.event(st, "task_" + t["status"], attempt=t["attempt"], provider=t["provider"], accepted=accepted,
                   seconds=t.get("seconds"), usage=t.get("usage"))
        return accepted

    # --- spot checks of untrusted results: re-render on a trusted provider, compare
    def run_verifications(self, st, q, threshold_db=28.0):
        run = st["runId"]
        for v in st["verifications"]:
            if v["status"] == "pending":
                for pid, ad in self.adapters.items():
                    if not ad.trusted or pid in st["disabled"] or not ad.workers():
                        continue
                    atom = next(a for a in q.atoms() if a["id"] == v["atom"])
                    worker = {**reg.profile(pid, self.config["providers"].get(pid, {})), **ad.workers()[0]}
                    attempt = f"verify-{pid}-{v['atom']}-{hashlib.sha1(str(self.clock()).encode()).hexdigest()[:6]}"
                    est = q.est(worker, [atom])
                    try:
                        url, _ = self.write_manifest(st, attempt, [atom], {**worker, "trusted": False}, est)
                        h = ad.start({"chunk": atom["id"], "attempt": attempt, "manifestUrl": url, "estS": est,
                                      "worker": worker})
                    except Exception as e:  # noqa: BLE001
                        self.event(st, "verify_start_failed", provider=pid, error=str(e)[:200])
                        continue
                    v.update(status="running", verifyAttempt=attempt, provider=pid,
                             handle={k: x for k, x in h.items() if not k.startswith("_")}, t0=self.clock())
                    self.event(st, "spot_check_started", atom=v["atom"], node=v["node"], provider=pid)
                    break
            elif v["status"] == "running":
                ad = self.adapters[v["provider"]]
                done, _ = self.store.get_json(self.layout.done(run, v["verifyAttempt"]))
                pr = ad.poll(v["handle"])
                if done is None and pr["state"] == "running":
                    continue
                ad.finish(v["handle"])
                atom = next(a for a in q.atoms() if a["id"] == v["atom"])
                scores = []
                for f in range(atom["frameStart"], atom["frameEnd"] + 1):
                    a, _ = self.store.get(self.attempt_plate_key(run, v["attempt"], atom["shot"], f))
                    b, _ = self.store.get(self.attempt_plate_key(run, v["verifyAttempt"], atom["shot"], f))
                    if a is None or b is None:
                        continue
                    scores.append(psnr_downsampled(a, b))
                if not scores:
                    v["status"] = "pending"          # the re-render failed: try again on the next tick
                    continue
                v["psnr"] = round(min(scores), 2)
                if v["psnr"] >= threshold_db:
                    v["status"] = "passed"
                    self.members.update_record(v["node"], verified=1)
                else:
                    v["status"] = "failed"
                    self.distrust(st, q, v["node"], f"spot check {v['atom']} PSNR {v['psnr']} dB < {threshold_db}")
                self.event(st, "spot_check_" + v["status"], atom=v["atom"], node=v["node"], psnr=v.get("psnr"))

    def distrust(self, st, q, node, why):
        """A node failed verification: revoke it and re-open every atom it delivered in this run."""
        self.members.update_record(node, failedChecks=1)
        try:
            self.members.revoke(node, reason=why)
        except KeyError:
            pass
        n = 0
        for t in st["tasks"].values():
            if t.get("node") != node:
                continue
            for aid in t["atoms"]:
                res = q.result(aid)
                if res and res.get("node") == node:
                    q.reopen(aid, why)
                    n += 1
        self.event(st, "node_distrusted", node=node, why=why, reopened=n)

    def calibrate(self, st, t):
        jm, _ = self.store.get_json(self.layout.job_manifest(st["runId"], t["attempt"], t["attempt"]))
        spf = list(((jm or {}).get("render") or {}).get("secondsPerFrame", {}).values())
        if not spf or not t.get("trusted"):
            return
        med = statistics.median(spf)
        frames = t["frames"]
        render_s = float((jm or {}).get("renderSeconds") or 0)
        build = max(0.0, render_s - med * frames)
        pid = t["provider"]
        c = st.setdefault("calibration", {}).setdefault(pid, {"spf": {}, "samples": 0})
        n = c["samples"]
        old = c["spf"].get(st["quality"])
        # normalise to the broker's reference resolution/samples is not attempted: calibration is per (res, spp)
        c["spf"][st["quality"]] = round(med if old is None else (old * n + med) / (n + 1), 3)
        c["build_s"] = round(build if not c.get("build_s") else (c["build_s"] * n + build) / (n + 1), 2)
        c["cold_start_s"] = round(max(0.0, t["seconds"] - render_s), 1) if t.get("seconds") else c.get("cold_start_s")
        c["samples"] = n + 1
        c["res"], c["samplesPerPixel"] = st.get("res"), st.get("samples")

    # ------------------------------------------------------------------------------------------- loops
    def run_until_done(self, st, interval=10.0, max_s=None, on_tick=None):
        t_end = self.clock() + max_s if max_s else None
        while st["status"] not in TERMINAL:
            st = self.tick(st)
            if on_tick:
                on_tick(st)
            if st["status"] in TERMINAL:
                break
            if t_end and self.clock() > t_end:
                self.stop(st, "max wall time reached")
                break
            self.sleep(interval)
        return st

    def stop(self, st, why="stopped"):
        for t in st["tasks"].values():
            if t["status"] == "running":
                self._cancel(st, t, why)
        st["status"] = "STOPPED"
        self.event(st, "stopped", why=why)
        self.save(st)
        return st

    def pull(self, st, dest):
        run = st["runId"]
        os.makedirs(dest, exist_ok=True)
        n = 0
        for key in self.store.list(self.layout.plates_prefix(run)):
            rel = key[len(self.layout.plates_prefix(run)):]
            out = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            data, _ = self.store.get(key)
            with open(out, "wb") as fh:
                fh.write(data)
            n += 1
        return {"dest": dest, "frames": n}

    def summary(self, st):
        tasks = list(st["tasks"].values())
        by = {}
        for t in tasks:
            b = by.setdefault(t["provider"], {"tasks": 0, "done": 0, "failed": 0, "frames": 0, "seconds": []})
            b["tasks"] += 1
            b["done"] += t["status"] in ("done", "partial")
            b["failed"] += t["status"] in ("failed", "rejected")
            b["frames"] += t["frames"] if t["status"] in ("done", "partial") else 0
            if t.get("seconds"):
                b["seconds"].append(t["seconds"])
        for b in by.values():
            s = b.pop("seconds")
            b["taskSecondsMedian"] = round(statistics.median(s), 1) if s else None
            b["taskSecondsMax"] = round(max(s), 1) if s else None
        return {"runId": st["runId"], "status": st["status"], "frames": st["frames"],
                "progress": st.get("progress"), "wallS": st.get("wallS"), "spentUsd": st["spentUsd"],
                "usage": st["usage"], "providers": by, "plan": {k: st["plan"].get(k) for k in
                                                                ("expectedMin", "usd", "feasible", "providers")},
                "livePlan": st.get("livePlan"), "disabled": st.get("disabled"), "calibration": st.get("calibration"),
                "verifications": st.get("verifications")}
