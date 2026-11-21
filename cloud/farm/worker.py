"""
worker.py - GPU render worker: SQS job -> S3 sync -> Blender (render_episode.py) -> plates + manifest in S3.

    python3 cloud/farm/worker.py            # long-running loop (the container entrypoint)
    python3 cloud/farm/worker.py --once     # process at most one message, then exit (smoke tests)

Job message (JSON, written by orchestrator.py):
  {"v": 1, "runId", "jobId", "episodeId", "specKey", "shot", "frameStart", "frameEnd" (inclusive),
   "quality": "preview"|"final", "engine": "CYCLES"|"EEVEE", "res": "WxH"|null, "samples": int|null,
   "platesPrefix": "episodes/<id>/runs/<runId>/plates/", "assetKeys": ["assets/..."], "extraArgs": [...]}

Guarantees
  * idempotent: a job whose S3 manifest says DONE is acknowledged without rendering; plates already in S3 for
    the job's frames are pulled back first and Blender runs with --skip-existing, so retries resume.
  * one owner: a DynamoDB lease (conditional update) stops duplicate SQS deliveries rendering twice.
  * heartbeats: while Blender runs the message visibility and the lease are extended every HEARTBEAT_S.
  * retries: failures back off via message visibility; after MAX_ATTEMPTS receives SQS moves the message to
    the DLQ (redrive maxReceiveCount in the stack must equal MAX_ATTEMPTS) and the job is marked FAILED.
  * spot: the IMDS interruption notice (2 min warning) uploads finished frames and releases the message.
  * cost: no GPU -> refuse to start (REQUIRE_GPU=1); Cycles silently on CPU -> job fails instead of running
    for hours; idle for IDLE_SHUTDOWN_S -> the instance terminates itself and decrements the ASG.

Env: FARM_BUCKET, FARM_QUEUE_URL, FARM_TABLE, AWS_REGION (required on AWS); FARM_REPO=/opt/factory,
FARM_WORK=/work, LIBRARY_STORE=/cache/library_store, BLENDER=/opt/blender/blender, VISIBILITY_S=600,
HEARTBEAT_S=120, MAX_ATTEMPTS=4, IDLE_SHUTDOWN_S=600, REQUIRE_GPU=1, FARM_IMDS=1, LIBRARY_RESYNC_S=1800,
RENDER_THREADS=0, HEALTH_FILE=/tmp/farm-worker.health, FARM_ASG_NAME (optional; discovered via IMDS).
Provider-agnostic (scheduler.py / providers/): FARM_PROVIDER (aws_ec2|runpod|vastai|local), FARM_PROVIDER_WORKER_ID
(<provider>:<machine id>, what the scheduler launched), FARM_GPU_CLASS, HEARTBEAT_DDB_S=60 (0 = no DynamoDB
heartbeat). The same code runs on EC2, RunPod, Vast.ai or locally; only these env vars differ.
"""
import argparse
import glob
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import farmio  # noqa: E402

ALLOWED_EXTRA = {"--no-motion-blur": 0, "--haze": 1, "--exposure": 1, "--ocean-res": 1}
REQUIRED_FIELDS = ("runId", "jobId", "episodeId", "specKey", "shot", "frameStart", "frameEnd", "quality", "engine",
                   "platesPrefix")


def log(event, **kw):
    print(json.dumps({"t": round(time.time(), 1), "event": event, **kw}), flush=True)


class JobError(Exception):
    pass


class Interrupted(Exception):
    pass


def env(name, default=None, cast=str):
    v = os.environ.get(name)
    return cast(v) if v not in (None, "") else default


class Config:
    def __init__(self):
        self.bucket = env("FARM_BUCKET")
        self.queue_url = env("FARM_QUEUE_URL")
        self.table = env("FARM_TABLE")
        self.region = env("AWS_REGION", env("AWS_DEFAULT_REGION", "us-east-1"))
        self.repo = env("FARM_REPO", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
        self.work = env("FARM_WORK", "/work")
        self.library = env("LIBRARY_STORE", "/cache/library_store")
        self.library_prefix = env("FARM_LIBRARY_PREFIX", "library_store/")
        self.blender = env("BLENDER", "/opt/blender/blender")
        self.visibility_s = env("VISIBILITY_S", 600, int)
        self.heartbeat_s = env("HEARTBEAT_S", 120, int)
        self.max_attempts = env("MAX_ATTEMPTS", 4, int)
        self.idle_shutdown_s = env("IDLE_SHUTDOWN_S", 600, int)
        self.require_gpu = env("REQUIRE_GPU", "1") == "1"
        self.imds = env("FARM_IMDS", "1") == "1"
        self.library_resync_s = env("LIBRARY_RESYNC_S", 1800, int)
        self.threads = env("RENDER_THREADS", 0, int)
        self.health_file = env("HEALTH_FILE", "/tmp/farm-worker.health")
        self.asg_name = env("FARM_ASG_NAME")
        self.poll_s = env("POLL_S", 5, int)
        self.wait_s = env("RECEIVE_WAIT_S", 20, int)
        self.keep_work = env("KEEP_WORK", "0") == "1"
        self.provider = env("FARM_PROVIDER")
        self.provider_worker_id = env("FARM_PROVIDER_WORKER_ID")
        self.gpu_class = env("FARM_GPU_CLASS")
        self.heartbeat_ddb_s = env("HEARTBEAT_DDB_S", 60, int)
        missing = [k for k, v in (("FARM_BUCKET", self.bucket), ("FARM_QUEUE_URL", self.queue_url),
                                  ("FARM_TABLE", self.table)) if not v]
        if missing:
            raise SystemExit(f"worker needs env: {', '.join(missing)}")


# ----------------------------------------------------------------------------------------------- instance metadata
class Imds:
    """Tiny IMDSv2 client; disabled off-EC2 (first failure turns it off)."""

    BASE = "http://169.254.169.254/latest"

    def __init__(self, enabled=True):
        self.enabled = enabled
        self._tok, self._tok_t = None, 0

    def _token(self):
        if self._tok and time.time() - self._tok_t < 300:
            return self._tok
        req = urllib.request.Request(self.BASE + "/api/token", method="PUT",
                                     headers={"X-aws-ec2-metadata-token-ttl-seconds": "600"})
        self._tok = urllib.request.urlopen(req, timeout=1).read().decode()
        self._tok_t = time.time()
        return self._tok

    def get(self, path):
        if not self.enabled:
            return None
        try:
            req = urllib.request.Request(f"{self.BASE}/meta-data/{path}", headers={"X-aws-ec2-metadata-token": self._token()})
            return urllib.request.urlopen(req, timeout=1).read().decode()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        except (urllib.error.URLError, socket.timeout, OSError):
            self.enabled = False
            return None

    def spot_interruption(self):
        try:
            return self.get("spot/instance-action")
        except Exception:  # noqa: BLE001
            return None


def gpu_names():
    exe = shutil.which("nvidia-smi")
    out = ""
    if exe:
        try:
            out = subprocess.run([exe, "-L"], capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.TimeoutExpired):
            out = ""
    names = [line.strip() for line in out.splitlines() if line.startswith("GPU ")]
    if not names and os.path.isdir("/proc/driver/nvidia/gpus"):
        # containers (RunPod/Vast) sometimes mount the driver without nvidia-smi: read the kernel's view
        for i, bus in enumerate(sorted(os.listdir("/proc/driver/nvidia/gpus"))):
            model = "NVIDIA GPU"
            try:
                with open(os.path.join("/proc/driver/nvidia/gpus", bus, "information")) as fh:
                    for line in fh:
                        if line.startswith("Model:"):
                            model = line.split(":", 1)[1].strip()
            except OSError:
                pass
            names.append(f"GPU {i}: {model} (bus {bus})")
    return names


# ----------------------------------------------------------------------------------------------- job helpers
def validate(job):
    missing = [k for k in REQUIRED_FIELDS if k not in job]
    if missing:
        raise JobError(f"job message missing {missing}")
    if job["quality"] not in ("preview", "final") or job["engine"] not in ("CYCLES", "EEVEE"):
        raise JobError(f"bad quality/engine {job['quality']}/{job['engine']}")
    if not (isinstance(job["frameStart"], int) and isinstance(job["frameEnd"], int) and job["frameStart"] <= job["frameEnd"]):
        raise JobError(f"bad frame range {job['frameStart']}..{job['frameEnd']}")
    for k in [job["specKey"], job["platesPrefix"], *job.get("assetKeys", [])]:
        if k.startswith("/") or ".." in k.split("/"):
            raise JobError(f"unsafe key {k!r}")
    if not job["platesPrefix"].endswith("/"):
        raise JobError("platesPrefix must end with '/'")
    if any(c in job["shot"] for c in "/\\") or job["shot"] in (".", ".."):
        raise JobError(f"unsafe shot id {job['shot']!r}")
    return job


def extra_args(job):
    out, xs = [], list(job.get("extraArgs") or [])
    i = 0
    while i < len(xs):
        a = xs[i]
        if a not in ALLOWED_EXTRA:
            raise JobError(f"extra arg {a!r} not allowed")
        n = ALLOWED_EXTRA[a]
        vals = xs[i + 1:i + 1 + n]
        if len(vals) != n:
            raise JobError(f"extra arg {a} needs {n} value(s)")
        for v in vals:
            float(v)  # numbers only
        out += [a, *map(str, vals)]
        i += 1 + n
    return out


def expected_plates(job):
    return [f"{f:04d}.png" for f in range(job["frameStart"], job["frameEnd"] + 1)]


def blender_cmd(cfg, job, spec_path, out_dir):
    cmd = [*shlex.split(cfg.blender), "-b", "--factory-startup", "-P",
           os.path.join(cfg.repo, "cloud", "blender", "render_episode.py"), "--",
           "--spec", spec_path, "--start", str(job["frameStart"]), "--end", str(job["frameEnd"]),
           "--out", out_dir, "--quality", job["quality"], "--engine", job["engine"], "--root", cfg.repo,
           "--skip-existing"]
    if job.get("res"):
        cmd += ["--res", str(job["res"])]
    if job.get("samples"):
        cmd += ["--samples", str(int(job["samples"]))]
    if cfg.threads:
        cmd += ["--threads", str(cfg.threads)]
    if job["engine"] == "EEVEE":
        cmd += ["--strict-engine"]  # never fall back to CPU Cycles on a paid GPU box
    return cmd + extra_args(job)


# ----------------------------------------------------------------------------------------------- worker
class Worker:
    def __init__(self, cfg, s3, sqs, ddb, autoscaling=None, imds=None):
        self.cfg, self.s3, self.sqs, self.autoscaling = cfg, s3, sqs, autoscaling
        self.store = farmio.Store(ddb, cfg.table)
        self.imds = imds or Imds(cfg.imds)
        self.instance_id = self.imds.get("instance-id") if self.imds.enabled else None
        self.instance_type = (self.imds.get("instance-type") if self.imds.enabled else None) or "local"
        self.worker_id = f"{self.instance_id or socket.gethostname()}:{os.getpid()}"
        self.provider = cfg.provider or ("aws_ec2" if self.instance_id else "local")
        self.provider_worker_id = cfg.provider_worker_id or f"{self.provider}:{self.instance_id or socket.gethostname()}"
        if not cfg.gpu_class and self.instance_type:
            cfg.gpu_class = {"g6": "L4", "g5": "A10G", "g4dn": "T4"}.get(self.instance_type.split(".")[0])
        self._hb = (0.0, None)  # (last DynamoDB heartbeat time, state)
        self.gpus = []
        self.current_job = None
        self.asg = cfg.asg_name
        self.library_synced_at = 0.0
        self.stop = False
        self.proc = None

    # --- lifecycle
    def health(self, state):
        try:
            with open(self.cfg.health_file, "w") as fh:
                json.dump({"t": time.time(), "state": state, "worker": self.worker_id}, fh)
        except OSError:
            pass
        self.heartbeat(state)

    def heartbeat(self, state):
        """Throttled DynamoDB heartbeat the scheduler uses to tell healthy, busy and idle workers apart."""
        last_t, last_state = self._hb
        if not self.cfg.heartbeat_ddb_s or (state == last_state and time.time() - last_t < self.cfg.heartbeat_ddb_s):
            return
        try:
            self.store.put_heartbeat(self.provider_worker_id, state=state, workerId=self.worker_id,
                                     provider=self.provider, gpuClass=self.cfg.gpu_class, gpus=self.gpus or None,
                                     instanceType=self.instance_type, job=self.current_job)
            self._hb = (time.time(), state)
        except Exception as e:  # noqa: BLE001 - a heartbeat must never stop rendering
            log("heartbeat_failed", error=str(e)[:200])
            self._hb = (time.time(), state)

    def preflight(self):
        gpus = self.gpus = gpu_names()
        log("preflight", worker=self.worker_id, instanceType=self.instance_type, gpus=gpus, provider=self.provider,
            providerWorkerId=self.provider_worker_id, gpuClass=self.cfg.gpu_class)
        if self.cfg.require_gpu and not gpus:
            raise SystemExit("REQUIRE_GPU=1 but nvidia-smi sees no GPU (check --gpus all / drivers)")
        if self.instance_id and self.autoscaling and not self.asg:
            try:
                r = self.autoscaling.describe_auto_scaling_instances(InstanceIds=[self.instance_id])
                if r["AutoScalingInstances"]:
                    self.asg = r["AutoScalingInstances"][0]["AutoScalingGroupName"]
            except Exception as e:  # noqa: BLE001
                log("asg_lookup_failed", error=str(e)[:200])
        self.sync_library(force=True)

    def sync_library(self, force=False):
        if not force and time.time() - self.library_synced_at < self.cfg.library_resync_s:
            return
        t = time.time()
        got, skipped = farmio.sync_down(self.s3, self.cfg.bucket, self.cfg.library_prefix, self.cfg.library)
        self.library_synced_at = time.time()
        log("library_synced", fetched=got, unchanged=skipped, seconds=round(time.time() - t, 1))

    def protect(self, on):
        if not (self.asg and self.instance_id and self.autoscaling):
            return
        try:
            self.autoscaling.set_instance_protection(InstanceIds=[self.instance_id], AutoScalingGroupName=self.asg,
                                                     ProtectedFromScaleIn=on)
        except Exception as e:  # noqa: BLE001
            log("protect_failed", on=on, error=str(e)[:200])

    def self_terminate(self, idle_s):
        log("idle_shutdown", idleSeconds=round(idle_s), asg=self.asg, instance=self.instance_id)
        if self.asg and self.instance_id and self.autoscaling:
            self.protect(False)
            self.autoscaling.terminate_instance_in_auto_scaling_group(InstanceId=self.instance_id,
                                                                      ShouldDecrementDesiredCapacity=True)
        # off-ASG (dev) or after the API call: just leave; the instance terminates under us

    def run(self, once=False):
        signal.signal(signal.SIGTERM, self._sigterm)
        self.preflight()
        last_work = time.time()
        while not self.stop:
            self.health("idle")
            msgs = self.sqs.receive_message(
                QueueUrl=self.cfg.queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=self.cfg.wait_s,
                VisibilityTimeout=self.cfg.visibility_s, MessageSystemAttributeNames=["ApproximateReceiveCount"],
            ).get("Messages", [])
            if not msgs:
                idle = time.time() - last_work
                if once:
                    return 0
                if self.cfg.idle_shutdown_s and idle >= self.cfg.idle_shutdown_s:
                    self.self_terminate(idle)
                    return 0
                continue
            self.handle(msgs[0])
            last_work = time.time()
            if once:
                return 0
        return 0

    def _sigterm(self, *_):
        log("sigterm")
        self.stop = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    # --- one message
    def handle(self, msg):
        receipt = msg["ReceiptHandle"]
        receives = int(msg.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
        try:
            job = validate(json.loads(msg["Body"]))
        except (ValueError, JobError) as e:
            log("bad_message", error=str(e)[:300], receives=receives)
            # poison: make it visible again at once so it reaches the DLQ after MAX_ATTEMPTS receives
            self._visibility(receipt, 0)
            return "bad"
        run_id, job_id = job["runId"], job["jobId"]
        mkey = farmio.manifest_key(run_id, job_id)
        done = farmio.s3_get_json(self.s3, self.cfg.bucket, mkey)
        if done and done.get("status") == "DONE":
            log("already_done", job=job_id)
            self.store.finish_job(run_id, job_id, "DONE", manifestKey=mkey, gpuSeconds=done.get("gpuSeconds", 0))
            self._delete(receipt)
            return "skipped"
        run = self.store.get_run(run_id)
        if run and run.get("status") == "CANCELLED":
            log("run_cancelled", job=job_id)
            self.store.finish_job(run_id, job_id, "CANCELLED")
            self._delete(receipt)
            return "cancelled"
        if not self.store.claim_job(run_id, job_id, self.worker_id, self.cfg.visibility_s):
            log("lease_held_elsewhere", job=job_id)
            self._visibility(receipt, min(self.cfg.visibility_s, 300))
            return "busy"
        self.protect(True)
        self.current_job = job_id
        self.health("rendering")
        t0 = time.time()
        logpath = os.path.join(self.cfg.work, f"{job_id}.{receives}.log")
        try:
            result = self.render(job, receipt, logpath, t0, receives)
        except Interrupted as e:
            log("interrupted", job=job_id, reason=str(e))
            self._upload_log(job, logpath, receives)
            self.store.finish_job(run_id, job_id, "PENDING", lastError=f"interrupted: {e}")
            self._visibility(receipt, 0)
            return "interrupted"
        except Exception as e:  # noqa: BLE001 - any failure is retried via SQS
            err = f"{type(e).__name__}: {e}"[:1000]
            final = receives >= self.cfg.max_attempts
            log("job_failed", job=job_id, attempt=receives, final=final, error=err)
            self._upload_log(job, logpath, receives)
            self.store.finish_job(run_id, job_id, "FAILED" if final else "RETRYING", lastError=err)
            # back off: 60 s, 120 s, 240 s ... (SQS max 12 h); the final receive goes to the DLQ next time
            self._visibility(receipt, min(60 * 2 ** (receives - 1), 3600))
            return "failed"
        finally:
            self.protect(False)
            self.current_job = None
            if not self.cfg.keep_work:
                shutil.rmtree(os.path.join(self.cfg.work, job_id), ignore_errors=True)
                if os.path.exists(logpath):
                    os.remove(logpath)  # already uploaded to S3
        self._delete(receipt)
        log("job_done", job=job_id, seconds=result["gpuSeconds"], frames=len(result["files"]))
        return "done"

    def render(self, job, receipt, logpath, t0, attempt):
        cfg, b = self.cfg, self.cfg.bucket
        run_id, job_id, eid = job["runId"], job["jobId"], job["episodeId"]
        jdir = os.path.join(cfg.work, job_id)
        out_dir = os.path.join(jdir, "plates")
        shot_dir = os.path.join(out_dir, job["shot"])
        os.makedirs(shot_dir, exist_ok=True)
        # 1. inputs: library (periodic delta), spec snapshot, episode assets, frames from earlier attempts
        self.sync_library()
        spec_path = os.path.join(cfg.repo, job["specKey"])
        farmio.download_atomic(self.s3, b, job["specKey"], spec_path)
        for key in job.get("assetKeys") or []:
            if farmio.s3_exists(self.s3, b, key):
                farmio.download_atomic(self.s3, b, key, os.path.join(cfg.repo, key))
        want = set(expected_plates(job))
        prefix = f"{job['platesPrefix']}{job['shot']}/"
        resumed = 0
        for key, size in farmio.s3_list(self.s3, b, prefix).items():
            name = key[len(prefix):]
            if name in want and size > 0:
                farmio.download_atomic(self.s3, b, key, os.path.join(shot_dir, name))
                resumed += 1
        t_sync = time.time() - t0
        # 2. Blender with heartbeats
        cmd = blender_cmd(cfg, job, spec_path, out_dir)
        log("render_start", job=job_id, attempt=attempt, resumedFrames=resumed, cmd=" ".join(cmd))
        timeout = max(1800.0, 4.0 * float(job.get("estSeconds") or 900))
        t1 = time.time()
        with open(logpath, "w") as lf:
            self.proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=cfg.repo)
            last_hb = time.time()
            while self.proc.poll() is None:
                time.sleep(cfg.poll_s)
                self.health("rendering")
                if self.stop:
                    self._kill()
                    self._upload_partial(job, shot_dir, want)
                    raise Interrupted("SIGTERM")
                notice = self.imds.spot_interruption()
                if notice:
                    self._kill()
                    self._upload_partial(job, shot_dir, want)
                    raise Interrupted(f"spot interruption {notice[:120]}")
                if time.time() - t1 > timeout:
                    self._kill()
                    self._upload_partial(job, shot_dir, want)
                    raise JobError(f"render timed out after {timeout:.0f}s")
                if time.time() - last_hb >= cfg.heartbeat_s:
                    self._visibility(receipt, cfg.visibility_s)
                    if not self.store.renew_lease(run_id, job_id, self.worker_id, cfg.visibility_s):
                        self._kill()
                        raise JobError("lost the job lease")
                    run = self.store.get_run(run_id)
                    if run and run.get("status") == "CANCELLED":
                        self._kill()
                        raise Interrupted("run cancelled")
                    last_hb = time.time()
            rc = self.proc.returncode
            self.proc = None
        t_render = time.time() - t1
        if rc != 0:
            raise JobError(f"blender exited {rc} (log {farmio.log_key(run_id, job_id, attempt)})")
        # 3. verify every frame and the renderer's own manifests
        missing = sorted(n for n in want if not (os.path.isfile(os.path.join(shot_dir, n))
                                                 and os.path.getsize(os.path.join(shot_dir, n)) > 0))
        if missing:
            raise JobError(f"{len(missing)} plates missing after render, e.g. {missing[:3]}")
        rman = []
        for p in sorted(glob.glob(os.path.join(shot_dir, "_render_*.json"))):
            with open(p) as fh:
                rman.append(json.load(fh))
        devices = {m.get("device") for m in rman}
        if cfg.require_gpu and "CPU" in devices:
            raise JobError("Cycles rendered on CPU on a GPU worker (OptiX/CUDA not available in the container)")
        # 4. upload plates (+ renderer manifests) and the log, then the job manifest last
        files = []
        remote = farmio.s3_list(self.s3, b, prefix)
        for name in sorted(os.listdir(shot_dir)):
            p = os.path.join(shot_dir, name)
            if not (name in want or name.startswith("_render_")):
                continue
            key = prefix + name
            size = os.path.getsize(p)
            if not (name in want and remote.get(key) == size):
                self.s3.upload_file(p, b, key, ExtraArgs={"ContentType": farmio._ctype(p)})
            if name in want:
                files.append({"key": key, "size": size, "sha256": farmio.sha256_file(p)})
        self._upload_log(job, logpath, attempt)
        spf = {}
        for m in rman:
            spf.update(m.get("secondsPerFrame") or {})
        gpu_s = round(time.time() - t0, 1)
        manifest = {
            "v": 1, "status": "DONE", "runId": run_id, "jobId": job_id, "episodeId": eid, "shot": job["shot"],
            "frameStart": job["frameStart"], "frameEnd": job["frameEnd"], "quality": job["quality"],
            "engine": job["engine"], "attempt": attempt, "worker": self.worker_id, "instanceType": self.instance_type,
            "provider": self.provider, "providerWorkerId": self.provider_worker_id, "gpuClass": self.cfg.gpu_class,
            "gpus": self.gpus, "estSeconds": job.get("estSeconds"),
            "files": files, "resumedFrames": resumed, "gpuSeconds": gpu_s, "syncSeconds": round(t_sync, 1),
            "renderSeconds": round(t_render, 1), "finishedAt": int(time.time()),
            "render": {"devices": sorted(d for d in devices if d), "secondsPerFrame": spf,
                       "resolution": rman[-1].get("resolution") if rman else None,
                       "samples": rman[-1].get("samples") if rman else None,
                       "blender": rman[-1].get("blender") if rman else None,
                       "warnings": sorted({w for m in rman for w in m.get("warnings", [])})},
            "logKey": farmio.log_key(run_id, job_id, attempt),
        }
        mkey = farmio.manifest_key(run_id, job_id)
        farmio.s3_put_json(self.s3, b, mkey, manifest)
        self.store.finish_job(run_id, job_id, "DONE", manifestKey=mkey, gpuSeconds=gpu_s, attemptDone=attempt,
                              provider=self.provider, providerWorkerId=self.provider_worker_id)
        return manifest

    # --- small helpers
    def _kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc = None

    def _upload_partial(self, job, shot_dir, want):
        prefix = f"{job['platesPrefix']}{job['shot']}/"
        n = 0
        for name in sorted(want):
            p = os.path.join(shot_dir, name)
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                try:
                    self.s3.upload_file(p, self.cfg.bucket, prefix + name, ExtraArgs={"ContentType": "image/png"})
                    n += 1
                except Exception as e:  # noqa: BLE001
                    log("partial_upload_failed", error=str(e)[:200])
                    break
        log("partial_uploaded", job=job["jobId"], frames=n)

    def _upload_log(self, job, logpath, attempt):
        if os.path.isfile(logpath):
            try:
                self.s3.upload_file(logpath, self.cfg.bucket, farmio.log_key(job["runId"], job["jobId"], attempt),
                                    ExtraArgs={"ContentType": "text/plain"})
            except Exception as e:  # noqa: BLE001
                log("log_upload_failed", error=str(e)[:200])

    def _visibility(self, receipt, seconds):
        try:
            self.sqs.change_message_visibility(QueueUrl=self.cfg.queue_url, ReceiptHandle=receipt,
                                               VisibilityTimeout=int(seconds))
        except Exception as e:  # noqa: BLE001 - receipt may have expired; SQS redelivers anyway
            log("visibility_failed", error=str(e)[:200])

    def _delete(self, receipt):
        self.sqs.delete_message(QueueUrl=self.cfg.queue_url, ReceiptHandle=receipt)


def main(argv=None):
    p = argparse.ArgumentParser(description="Blender GPU render worker (SQS -> S3).")
    p.add_argument("--once", action="store_true", help="handle at most one message, then exit")
    a = p.parse_args(argv)
    import boto3
    from botocore.config import Config as BotoConfig
    cfg = Config()
    os.makedirs(cfg.work, exist_ok=True)
    bc = BotoConfig(region_name=cfg.region, retries={"max_attempts": 8, "mode": "adaptive"})
    w = Worker(cfg, boto3.client("s3", config=bc), boto3.client("sqs", config=bc), boto3.client("dynamodb", config=bc),
               boto3.client("autoscaling", config=bc))
    return w.run(once=a.once)


if __name__ == "__main__":
    sys.exit(main())
