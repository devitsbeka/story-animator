"""
orchestrator.py - turn episode.json files into render runs on the farm, track them, finish them.

  plan     split + cost estimate, no AWS          orchestrator.py plan --spec episodes/sentinel/episode_v2.json
  submit   snapshot spec, register run, enqueue   orchestrator.py --stack story-farm submit --spec A.json --spec B.json --budget 60
  status   progress / spend of runs               orchestrator.py --stack story-farm status [--run RUN]
  watch    loop: progress, budget guard, finish   orchestrator.py --stack story-farm watch --finish
  finish   pull plates, Remotion finish, QC       orchestrator.py --stack story-farm finish --run RUN
  cancel   stop a run (workers skip its jobs)     orchestrator.py --stack story-farm cancel --run RUN
  retry    re-enqueue FAILED jobs of a run        orchestrator.py --stack story-farm retry --run RUN
  sync-library  upload $LIBRARY_STORE to S3       orchestrator.py --stack story-farm sync-library

Resources come from the CloudFormation stack outputs (--stack, read-only describe) or from
FARM_BUCKET / FARM_QUEUE_URL / FARM_TABLE.

Budget ceiling (N episodes in parallel): a run is accepted only if
    sum(max(estimate, spent) of active runs) + estimate(new run) <= --budget (or $FARM_BUDGET_USD).
Each run also gets its own cap (estimate x --overrun, default 1.5); `watch` cancels a run that spends past it.
Messages of several runs submitted together are interleaved round-robin (longest jobs first inside each run),
so episodes progress in parallel rather than one after another.
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import farmio  # noqa: E402
import jobs as jobsplit  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_PRICE = 0.60   # USD per GPU-hour: g6.xlarge spot, us-east-1 median Nov 2026 (see docs/farm.md)

# Finish/QC commands are templates so the finish and qc workstreams can change their CLIs without touching this.
# Placeholders: {repo} {spec} {plates} {episode_dir} {out} {props} {run} {episode}
DEFAULT_FINISH_CMD = ("cd {repo}/studio && npx remotion render src/index.ts Finish {out} --props={props} "
                      "--codec h264 --pixel-format yuv420p --crf 18")
DEFAULT_QC_CMD = "cd {repo} && python3 -m factory.qc run --episode {episode_dir} --video {out} --plates {plates}"


class BudgetExceeded(Exception):
    pass


def out(obj):
    json.dump(obj, sys.stdout, indent=1, default=str)
    sys.stdout.write("\n")


def asset_keys(spec):
    """Every repo-relative asset key the spec references under 'assets' (hero.glb, motions, props)."""
    keys = []

    def walk(v):
        if isinstance(v, str):
            if v.startswith("assets/") and ".." not in v.split("/"):
                keys.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(spec.get("assets") or {})
    return sorted(set(keys))


def make_run_id(spec, quality, now=None):
    return f"{spec['id']}-{quality}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime(now or time.time()))}"


def messages_for(run_id, spec, jobs):
    eid = spec["id"]
    akeys = asset_keys(spec)
    return [{
        "v": 1, "runId": run_id, "jobId": j["jobId"], "episodeId": eid, "specKey": farmio.spec_key(eid, run_id),
        "shot": j["shot"], "frameStart": j["frameStart"], "frameEnd": j["frameEnd"], "quality": j["quality"],
        "engine": j["engine"], "res": j.get("res"), "samples": j.get("samples"), "estSeconds": j["estSeconds"],
        "platesPrefix": farmio.plates_prefix(eid, run_id), "assetKeys": akeys,
    } for j in jobsplit.lpt_order(jobs)]


def interleave(lists):
    """Round-robin merge: [[a1,a2,a3],[b1]] -> [a1,b1,a2,a3]."""
    out_, i = [], 0
    while any(i < len(x) for x in lists):
        out_ += [x[i] for x in lists if i < len(x)]
        i += 1
    return out_


def run_spent(run):
    return float(run.get("gpuSeconds") or 0) / 3600.0 * float(run.get("usdPerGpuHour") or DEFAULT_PRICE)


def committed_usd(runs):
    return sum(max(float(r.get("estUsd") or 0), run_spent(r)) for r in runs if r.get("status") in farmio.RUN_ACTIVE)


class Farm:
    def __init__(self, s3, sqs, ddb, bucket, queue_url, table):
        self.s3, self.sqs, self.bucket, self.queue_url = s3, sqs, bucket, queue_url
        self.store = farmio.Store(ddb, table)

    # ------------------------------------------------------------------ submit
    def submit(self, specs, quality="final", engine=None, budget=None, usd_per_gpu_hour=DEFAULT_PRICE,
               workers=8, overrun=1.5, target_job_s=jobsplit.DEFAULT_TARGET_JOB_S, run_ids=None, force=False,
               dry_run=False, repo=REPO, res=None, samples=None, shots=None, calibration=None):
        plans = []
        committed = committed_usd(self.store.list_runs())
        for i, spec in enumerate(specs):
            js = jobsplit.split_episode(spec, quality, engine, target_job_s, calibration, shots=shots, res=res,
                                        samples=samples)
            jobsplit.check_coverage(spec, js)
            est = jobsplit.estimate(js, usd_per_gpu_hour, workers)
            rid = (run_ids[i] if run_ids else None) or make_run_id(spec, quality)
            if budget is not None and committed + est["usd"] > budget and not force:
                raise BudgetExceeded(f"run {rid} needs ~${est['usd']:.2f}; ${committed:.2f} already committed "
                                     f"of the ${budget:.2f} ceiling")
            committed += est["usd"]
            plans.append((rid, spec, js, est))
        if dry_run:
            return [{"runId": r, "episodeId": s["id"], "estimate": e} for r, s, _, e in plans]
        all_msgs = []
        for rid, spec, js, est in plans:
            eid = spec["id"]
            farmio.s3_put_json(self.s3, self.bucket, farmio.spec_key(eid, rid), spec)
            for key in asset_keys(spec):
                p = os.path.join(repo, key)
                if os.path.isfile(p):
                    remote = farmio.s3_list(self.s3, self.bucket, key).get(key)
                    if remote != os.path.getsize(p):
                        self.s3.upload_file(p, self.bucket, key, ExtraArgs={"ContentType": farmio._ctype(p)})
            msgs = messages_for(rid, spec, js)
            self.store.put_run({
                "runId": rid, "episodeId": eid, "quality": quality, "engine": js[0]["engine"] if js else engine,
                "status": "QUEUED", "jobCount": len(js), "doneJobs": 0, "gpuSeconds": 0.0, "estUsd": est["usd"],
                "estGpuHours": est["gpuHours"], "usdPerGpuHour": usd_per_gpu_hour,
                "budgetUsd": round(est["usd"] * overrun, 2), "createdAt": int(time.time()),
                "specKey": farmio.spec_key(eid, rid), "platesPrefix": farmio.plates_prefix(eid, rid),
            })
            self.store.put_jobs(rid, js)
            farmio.s3_put_json(self.s3, self.bucket, farmio.run_key(rid),
                               {"runId": rid, "episodeId": eid, "estimate": est, "messages": msgs})
            all_msgs.append(msgs)
        sent = farmio.send_jobs(self.sqs, self.queue_url, interleave(all_msgs))
        return [{"runId": r, "episodeId": s["id"], "jobs": len(j), "estimate": e, "enqueued": sent}
                for r, s, j, e in plans]

    # ------------------------------------------------------------------ status / guard
    def status(self, run_id):
        run = self.store.get_run(run_id)
        if not run:
            raise SystemExit(f"no run {run_id}")
        jobs = self.store.list_jobs(run_id)
        counts = {}
        for j in jobs:
            counts[j["status"]] = counts.get(j["status"], 0) + 1
        frames_done = sum(j["frameEnd"] - j["frameStart"] + 1 for j in jobs if j["status"] == "DONE")
        frames = sum(j["frameEnd"] - j["frameStart"] + 1 for j in jobs)
        return {"runId": run_id, "episodeId": run["episodeId"], "status": run["status"], "jobs": counts,
                "jobCount": run["jobCount"], "frames": f"{frames_done}/{frames}",
                "spentUsd": round(run_spent(run), 2), "estUsd": run.get("estUsd"), "budgetUsd": run.get("budgetUsd"),
                "failed": [{"jobId": j["sk"][4:], "error": j.get("lastError")} for j in jobs if j["status"] == "FAILED"]}

    def cancel(self, run_id, reason="by operator"):
        self.store.set_run_status(run_id, "CANCELLED", cancelReason=reason)
        return self.status(run_id)

    def tick(self, run_id):
        """One watch step for a run: update its status, enforce its budget. -> new status."""
        st = self.status(run_id)
        run = self.store.get_run(run_id)
        if run["status"] not in ("QUEUED", "RUNNING"):
            return run["status"]
        if run.get("budgetUsd") is not None and run_spent(run) > float(run["budgetUsd"]):
            self.cancel(run_id, f"spent ${run_spent(run):.2f} > run budget ${run['budgetUsd']}")
            return "CANCELLED"
        c = st["jobs"]
        n = run["jobCount"]
        if c.get("DONE", 0) == n:
            self.store.set_run_status(run_id, "RENDERED")
            return "RENDERED"
        if c.get("DONE", 0) + c.get("FAILED", 0) + c.get("CANCELLED", 0) == n and c.get("FAILED"):
            self.store.set_run_status(run_id, "FAILED")
            return "FAILED"
        if c.get("RUNNING") or c.get("DONE") or c.get("RETRYING"):
            if run["status"] != "RUNNING":
                self.store.set_run_status(run_id, "RUNNING")
            return "RUNNING"
        return run["status"]

    def retry(self, run_id):
        plan = farmio.s3_get_json(self.s3, self.bucket, farmio.run_key(run_id))
        if not plan:
            raise SystemExit(f"no plan for {run_id}")
        failed = {j["sk"][4:] for j in self.store.list_jobs(run_id) if j["status"] in ("FAILED", "CANCELLED")}
        msgs = [m for m in plan["messages"] if m["jobId"] in failed]
        for m in msgs:
            self.store.finish_job(run_id, m["jobId"], "PENDING", lastError="requeued")
        self.store.set_run_status(run_id, "QUEUED")
        return farmio.send_jobs(self.sqs, self.queue_url, msgs) if msgs else 0

    # ------------------------------------------------------------------ finish
    def pull_plates(self, run_id, dest_root=REPO):
        run = self.store.get_run(run_id)
        eid = run["episodeId"]
        spec = farmio.s3_get_json(self.s3, self.bucket, run["specKey"])
        plates = os.path.join(dest_root, "episodes", eid, "runs", run_id, "plates")
        got, skipped = farmio.sync_down(self.s3, self.bucket, run["platesPrefix"], plates)
        missing = []
        for shot in spec["shots"]:
            a, b = jobsplit.shot_frames(shot)
            for f in range(a, b + 1):
                if not os.path.isfile(os.path.join(plates, shot["id"], f"{f:04d}.png")):
                    missing.append(f"{shot['id']}/{f:04d}")
        spec_path = os.path.join(dest_root, run["specKey"])
        os.makedirs(os.path.dirname(spec_path), exist_ok=True)
        with open(spec_path, "w") as fh:
            json.dump(spec, fh, indent=1)
        return {"plates": plates, "spec": spec_path, "fetched": got, "unchanged": skipped, "missing": missing}

    def finish(self, run_id, finish_cmd=DEFAULT_FINISH_CMD, qc_cmd=DEFAULT_QC_CMD, repo=REPO, runner=None):
        """Pull plates, run Remotion finish then QC (templates), upload results. -> summary dict."""
        runner = runner or (lambda cmd: subprocess.run(cmd, shell=True).returncode)
        run = self.store.get_run(run_id)
        if run["status"] not in ("RENDERED", "FINISHING", "QC_FAILED", "FINISH_FAILED"):
            raise SystemExit(f"run {run_id} is {run['status']}, not RENDERED")
        self.store.set_run_status(run_id, "FINISHING")
        pulled = self.pull_plates(run_id, repo)
        if pulled["missing"]:
            self.store.set_run_status(run_id, "FINISH_FAILED", finishError=f"{len(pulled['missing'])} plates missing")
            return {"status": "FINISH_FAILED", **pulled, "missing": pulled["missing"][:20]}
        eid = run["episodeId"]
        final_dir = os.path.join(repo, "episodes", eid, "runs", run_id, "final")
        os.makedirs(final_dir, exist_ok=True)
        props = os.path.join(final_dir, "finish_props.json")
        audio = next((k for k in (f"episodes/{eid}/audio/mix_v1.m4a", f"episodes/{eid}/audio/narration.mp3")
                      if os.path.isfile(os.path.join(repo, k))), None)
        with open(props, "w") as fh:
            json.dump({"episodeJson": pulled["spec"], "platesDir": pulled["plates"], "audio": audio}, fh, indent=1)
        ctx = {"repo": shlex.quote(repo), "spec": shlex.quote(pulled["spec"]), "plates": shlex.quote(pulled["plates"]),
               "episode_dir": shlex.quote(os.path.join(repo, "episodes", eid)), "run": run_id, "episode": eid,
               "out": shlex.quote(os.path.join(final_dir, f"{eid}.mp4")), "props": shlex.quote(props)}
        result = {"plates": pulled["plates"], "final": os.path.join(final_dir, f"{eid}.mp4")}
        for name, tmpl, fail_status in (("finish", finish_cmd, "FINISH_FAILED"), ("qc", qc_cmd, "QC_FAILED")):
            if not tmpl:
                result[name] = "skipped"
                continue
            cmd = tmpl.format(**ctx)
            rc = runner(cmd)
            result[name] = {"cmd": cmd, "rc": rc}
            if rc != 0:
                self.store.set_run_status(run_id, fail_status, finishError=f"{name} exited {rc}")
                result["status"] = fail_status
                return result
        up, _ = farmio.sync_up(self.s3, self.bucket, final_dir, f"episodes/{eid}/runs/{run_id}/final")
        self.store.set_run_status(run_id, "DONE")
        result.update(status="DONE", uploaded=up)
        return result

    def sync_library(self, src):
        return dict(zip(("uploaded", "unchanged"), farmio.sync_up(self.s3, self.bucket, src, "library_store")))


# ---------------------------------------------------------------------------------------------- CLI
def load_specs(paths):
    specs = []
    for p in paths:
        with open(p) as fh:
            specs.append(json.load(fh))
    return specs


def farm_from_args(a):
    import boto3
    sess = boto3.session.Session(region_name=a.region)
    bucket, queue, table = os.environ.get("FARM_BUCKET"), os.environ.get("FARM_QUEUE_URL"), os.environ.get("FARM_TABLE")
    if a.stack:
        o = farmio.stack_outputs(sess.client("cloudformation"), a.stack)
        bucket, queue, table = o["BucketName"], o["RenderQueueUrl"], o["TableName"]
    if not (bucket and queue and table):
        raise SystemExit("need --stack or FARM_BUCKET/FARM_QUEUE_URL/FARM_TABLE")
    return Farm(sess.client("s3"), sess.client("sqs"), sess.client("dynamodb"), bucket, queue, table)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--stack", default=os.environ.get("FARM_STACK"))
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    sub = p.add_subparsers(dest="cmd", required=True)

    def split_args(sp):
        sp.add_argument("--spec", action="append", required=True)
        sp.add_argument("--quality", choices=sorted(jobsplit.PRESETS), default="final")
        sp.add_argument("--engine", choices=["CYCLES", "EEVEE"], default=None)
        sp.add_argument("--res", default=None, help="override WxH for every job (tests)")
        sp.add_argument("--samples", type=int, default=None)
        sp.add_argument("--shots", default=None, help="comma-separated shot ids (default: all)")
        sp.add_argument("--target-job-minutes", type=float, default=jobsplit.DEFAULT_TARGET_JOB_S / 60)
        sp.add_argument("--calibration", default=None, help="JSON {shotId: secondsPerFrame}")
        sp.add_argument("--usd-per-gpu-hour", type=float, default=DEFAULT_PRICE)
        sp.add_argument("--workers", type=int, default=8)

    sp = sub.add_parser("plan")
    split_args(sp)
    sp.add_argument("--jobs", action="store_true", help="print every job")
    sp = sub.add_parser("submit")
    split_args(sp)
    sp.add_argument("--budget", type=float, default=float(os.environ["FARM_BUDGET_USD"]) if os.environ.get("FARM_BUDGET_USD") else None)
    sp.add_argument("--overrun", type=float, default=1.5)
    sp.add_argument("--run-id", action="append", default=None)
    sp.add_argument("--force", action="store_true", help="ignore the budget ceiling")
    sp.add_argument("--dry-run", action="store_true")
    for name in ("status", "cancel", "retry", "finish"):
        sp = sub.add_parser(name)
        sp.add_argument("--run", required=(name != "status"))
        if name == "finish":
            sp.add_argument("--finish-cmd", default=os.environ.get("FARM_FINISH_CMD", DEFAULT_FINISH_CMD))
            sp.add_argument("--qc-cmd", default=os.environ.get("FARM_QC_CMD", DEFAULT_QC_CMD))
    sp = sub.add_parser("watch")
    sp.add_argument("--interval", type=int, default=60)
    sp.add_argument("--finish", action="store_true", help="finish + QC each run once it is RENDERED")
    sp.add_argument("--finish-cmd", default=os.environ.get("FARM_FINISH_CMD", DEFAULT_FINISH_CMD))
    sp.add_argument("--qc-cmd", default=os.environ.get("FARM_QC_CMD", DEFAULT_QC_CMD))
    sp.add_argument("--once", action="store_true")
    sp = sub.add_parser("sync-library")
    sp.add_argument("--src", default=os.environ.get("LIBRARY_STORE", os.path.join(REPO, "library_store")))
    a = p.parse_args(argv)

    if a.cmd == "plan":
        cal = json.load(open(a.calibration)) if a.calibration else None
        res = []
        for spec in load_specs(a.spec):
            js = jobsplit.split_episode(spec, a.quality, a.engine, a.target_job_minutes * 60, cal,
                                        shots=a.shots.split(",") if a.shots else None, res=a.res, samples=a.samples)
            jobsplit.check_coverage(spec, js)
            item = {"episodeId": spec["id"], "estimate": jobsplit.estimate(js, a.usd_per_gpu_hour, a.workers)}
            if a.jobs:
                item["jobs"] = js
            res.append(item)
        return out(res)

    farm = farm_from_args(a)
    if a.cmd == "submit":
        cal = json.load(open(a.calibration)) if a.calibration else None
        try:
            return out(farm.submit(load_specs(a.spec), a.quality, a.engine, a.budget, a.usd_per_gpu_hour, a.workers,
                                   a.overrun, a.target_job_minutes * 60, a.run_id, a.force, a.dry_run, res=a.res,
                                   samples=a.samples, shots=a.shots.split(",") if a.shots else None,
                                   calibration=cal))
        except BudgetExceeded as e:
            print(f"refused: {e}", file=sys.stderr)
            return 2
    if a.cmd == "status":
        runs = [farm.store.get_run(a.run)] if a.run else farm.store.list_runs()
        return out([farm.status(r["runId"]) for r in runs if r])
    if a.cmd == "cancel":
        return out(farm.cancel(a.run))
    if a.cmd == "retry":
        return out({"requeued": farm.retry(a.run)})
    if a.cmd == "finish":
        return out(farm.finish(a.run, a.finish_cmd, a.qc_cmd))
    if a.cmd == "sync-library":
        return out(farm.sync_library(a.src))
    if a.cmd == "watch":
        while True:
            watched = ("QUEUED", "RUNNING", "RENDERED") if a.finish else ("QUEUED", "RUNNING")
            active = [r for r in farm.store.list_runs() if r["status"] in watched]
            for r in active:
                st = farm.tick(r["runId"])
                if st == "RENDERED" and a.finish:
                    out(farm.finish(r["runId"], a.finish_cmd, a.qc_cmd))
            out([farm.status(r["runId"]) for r in active])
            if a.once or not active:
                return 0
            time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main() or 0)
