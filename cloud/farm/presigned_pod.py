#!/usr/bin/env python3
"""
presigned_pod.py - the render loop inside a credential-free pod (started by providers/presigned_startup.sh).

    python3 cloud/farm/presigned_pod.py --manifest /work/manifest.json --work /work --repo /work/repo \\
        --blender /opt/blender/blender [--pod-log /work/pod.log]

Standard library + curl only. It never talks to an AWS API: every transfer is a curl GET/PUT of a presigned URL
taken from the manifest (cloud/farm/presigned.py:pod_manifest).

  1. GPU check (manifest requireGpu): nvidia-smi / kernel GPU list and a Cycles OptiX/CUDA probe; none -> FAILED.
  2. inputs: the spec and every library file (sha256-verified, skipped when already present and matching).
  3. jobs: blender -b -P cloud/blender/render_episode.py -- ... --skip-existing; every plate is PUT as soon as the
     renderer logs "shot <id> frame <f>: <s>s" (a final sweep catches the rest); per-job log + manifest are PUT.
     Cycles on CPU while requireGpu -> the job fails. Each job gets manifest jobAttempts tries.
  4. heartbeat: PUT {state, job, framesDone, ...} every heartbeatS seconds (and the pod log every 5th beat).
  5. done marker: PUT {status: DONE|PARTIAL|FAILED, jobs}; then idle (the orchestrator terminates the pod), or
     exit when the manifest says exitWhenDone (local tests).
"""
import argparse
import glob
import hashlib
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

FRAME_RE = re.compile(r"\[render_episode\] shot (\S+) frame (\d+): ([0-9.]+)s")
ALLOWED_EXTRA = {"--no-motion-blur": 0, "--haze": 1, "--exposure": 1, "--ocean-res": 1}


def log(event, **kw):
    print(json.dumps({"t": round(time.time(), 1), "event": event, **kw}, default=str), flush=True)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def png_complete(path):
    """A PNG is complete when it ends with the IEND chunk."""
    try:
        if os.path.getsize(path) < 45:
            return False
        with open(path, "rb") as fh:
            head = fh.read(8)
            fh.seek(-12, os.SEEK_END)
            tail = fh.read(12)
        return head == b"\x89PNG\r\n\x1a\n" and tail[4:8] == b"IEND"
    except OSError:
        return False


class TransferError(Exception):
    pass


class Net:
    """curl GET/PUT against presigned URLs (retries with backoff; never logs a URL's query string)."""

    def __init__(self, curl="curl", retries=5):
        self.curl, self.retries = curl, retries
        self.lock = threading.Lock()
        self.bytes_up = self.bytes_down = 0

    @staticmethod
    def _safe(url):
        return url.split("?", 1)[0]

    def _run(self, args, what):
        r = subprocess.run([self.curl, "-fsS", "--retry", str(self.retries), "--retry-all-errors",
                            "--connect-timeout", "20", "--max-time", "3600", *args], capture_output=True, text=True)
        if r.returncode != 0:
            raise TransferError(f"{what}: curl exit {r.returncode}: {r.stderr.strip()[:300]}")

    def get(self, target, dst, sha256=None):
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".part-", dir=os.path.dirname(dst) or ".")
        os.close(fd)
        try:
            self._run(["-L", "-o", tmp, target["url"]], f"GET {self._safe(target['url'])}")
            if sha256 and sha256_file(tmp) != sha256:
                raise TransferError(f"sha256 mismatch for {os.path.basename(dst)}")
            os.replace(tmp, dst)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        with self.lock:
            self.bytes_down += os.path.getsize(dst)
        return dst

    def put_file(self, target, path):
        hdr = []
        for k, v in (target.get("headers") or {}).items():
            hdr += ["-H", f"{k}: {v}"]
        self._run(["-X", "PUT", "-T", path, *hdr, "-o", os.devnull, target["url"]],
                  f"PUT {self._safe(target['url'])}")
        with self.lock:
            self.bytes_up += os.path.getsize(path)

    def put_json(self, target, obj):
        fd, tmp = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(obj, fh, indent=1, default=str)
        try:
            self.put_file(target, tmp)
        finally:
            os.unlink(tmp)


def gpu_names():
    names = []
    exe = shutil.which("nvidia-smi")
    if exe:
        try:
            out = subprocess.run([exe, "-L"], capture_output=True, text=True, timeout=30).stdout
            names = [x.strip() for x in out.splitlines() if x.startswith("GPU ")]
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not names and os.path.isdir("/proc/driver/nvidia/gpus"):
        names = [f"GPU {i}: bus {b}" for i, b in enumerate(sorted(os.listdir("/proc/driver/nvidia/gpus")))]
    return names


def cycles_devices(blender):
    expr = ("import bpy\np = bpy.context.preferences.addons['cycles'].preferences\nfound = []\n"
            "for t in ('OPTIX', 'CUDA'):\n    try:\n        p.compute_device_type = t\n        p.get_devices()\n"
            "    except Exception:\n        continue\n    found += [t + ':' + d.name for d in p.devices if d.type == t]\n"
            "print('CYCLES_DEVICES', ';'.join(found) or 'CPU')\n")
    try:
        out = subprocess.run([blender, "-b", "--factory-startup", "--python-expr", expr], capture_output=True,
                             text=True, timeout=300).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"error: {e}"
    for line in out.splitlines():
        if line.startswith("CYCLES_DEVICES"):
            return line.split(" ", 1)[1].strip()
    return "unknown"


def extra_args(xs):
    out, i = [], 0
    xs = list(xs or [])
    while i < len(xs):
        a = xs[i]
        if a not in ALLOWED_EXTRA:
            raise ValueError(f"extra arg {a!r} not allowed")
        n = ALLOWED_EXTRA[a]
        vals = xs[i + 1:i + 1 + n]
        for v in vals:
            float(v)
        out += [a, *map(str, vals)]
        i += 1 + n
    return out


def safe_rel(p):
    return p and not p.startswith("/") and ".." not in p.split("/")


class Pod:
    def __init__(self, manifest, work, repo, blender, net=None, pod_log=None, clock=time.time):
        self.m, self.work, self.repo, self.blender = manifest, work, repo, blender
        self.net = net or Net(os.environ.get("CURL", "curl"))
        self.pod_log = pod_log
        self.clock = clock
        self.state, self.job, self.device = "starting", None, None
        self.frames_total = sum(j["frameEnd"] - j["frameStart"] + 1 for j in manifest["jobs"])
        self.uploaded = set()
        self.errors = []
        self.gpus = []
        self.started = clock()
        self.stop = threading.Event()
        self.library = os.path.join(work, "library_store")
        self._beats = 0

    # --- heartbeat
    def beat(self):
        hb = {"t": self.clock(), "pod": self.m["pod"], "runId": self.m["runId"], "state": self.state,
              "job": self.job, "framesDone": len(self.uploaded), "framesTotal": self.frames_total,
              "device": self.device, "gpus": self.gpus, "host": socket.gethostname(),
              "uptimeS": round(self.clock() - self.started), "bytesUp": self.net.bytes_up,
              "bytesDown": self.net.bytes_down, "errors": self.errors[-5:]}
        try:
            self.net.put_json(self.m["heartbeat"], hb)
        except TransferError as e:
            log("heartbeat_failed", error=str(e)[:200])
        self._beats += 1
        if self._beats % 5 == 1:
            self.upload_pod_log()

    def upload_pod_log(self):
        if self.pod_log and os.path.isfile(self.pod_log) and self.m.get("podLog"):
            try:
                self.net.put_file(self.m["podLog"], self.pod_log)
            except TransferError as e:
                log("pod_log_upload_failed", error=str(e)[:200])

    def _heartbeat_loop(self):
        period = max(5, int(self.m.get("heartbeatS", 60)))
        while not self.stop.wait(period):
            self.beat()

    # --- steps
    def check_gpu(self):
        self.gpus = gpu_names()
        if not self.m.get("requireGpu", True):
            self.device = "any"
            return True
        devs = cycles_devices(self.blender)
        log("gpu_check", gpus=self.gpus, cycles=devs)
        if not self.gpus or not re.search(r"(OPTIX|CUDA):", devs):
            self.errors.append(f"no usable GPU: gpus={self.gpus} cycles={devs}")
            return False
        self.device = "OPTIX" if "OPTIX:" in devs else "CUDA"
        return True

    def fetch_inputs(self):
        spec = self.m["spec"]
        if not safe_rel(spec["path"]):
            raise ValueError(f"unsafe spec path {spec['path']!r}")
        self.spec_path = os.path.join(self.repo, spec["path"])
        self.net.get(spec, self.spec_path, spec.get("sha256"))
        n = skipped = 0
        for f in self.m.get("library") or []:
            if not safe_rel(f["path"]):
                raise ValueError(f"unsafe library path {f['path']!r}")
            dst = os.path.join(self.library, f["path"])
            if os.path.isfile(dst) and (not f.get("sha256") or sha256_file(dst) == f["sha256"]):
                skipped += 1
                continue
            self.net.get(f, dst, f.get("sha256"))
            n += 1
        log("inputs_ready", spec=spec["path"], library=n, libraryCached=skipped, bytesDown=self.net.bytes_down)

    def blender_cmd(self, job, out_dir):
        cmd = [self.blender, "-b", "--factory-startup", "-P",
               os.path.join(self.repo, "cloud", "blender", "render_episode.py"), "--",
               "--spec", self.spec_path, "--start", str(job["frameStart"]), "--end", str(job["frameEnd"]),
               "--out", out_dir, "--quality", job["quality"], "--engine", job["engine"], "--root", self.repo,
               "--skip-existing"]
        if job.get("res"):
            cmd += ["--res", str(job["res"])]
        if job.get("samples"):
            cmd += ["--samples", str(int(job["samples"]))]
        if self.m.get("threads"):
            cmd += ["--threads", str(int(self.m["threads"]))]
        if job["engine"] == "EEVEE" and self.m.get("requireGpu", True):
            cmd += ["--strict-engine"]
        return cmd + extra_args(job.get("extraArgs"))

    def _upload_plate(self, job, shot_dir, frame):
        key = str(frame)
        if (job["shot"], frame) in self.uploaded or key not in job["plates"]:
            return False
        p = os.path.join(shot_dir, f"{frame:04d}.png")
        if not png_complete(p):
            return False
        self.net.put_file(job["plates"][key], p)
        self.uploaded.add((job["shot"], frame))
        return True

    def render_job(self, job, attempt):
        out_dir = os.path.join(self.work, "plates")
        shot_dir = os.path.join(out_dir, job["shot"])
        os.makedirs(shot_dir, exist_ok=True)
        logpath = os.path.join(self.work, "logs", f"{job['jobId']}.log")
        os.makedirs(os.path.dirname(logpath), exist_ok=True)
        env = {**os.environ, "LIBRARY_STORE": self.library,
               "LIGHTING_CACHE": os.path.join(self.work, "lighting_cache"), "PYTHONUNBUFFERED": "1"}
        for k in [k for k in env if k.startswith("AWS_")]:
            env.pop(k)  # nothing in the render needs (or gets) cloud credentials
        cmd = self.blender_cmd(job, out_dir)
        log("render_start", job=job["jobId"], attempt=attempt, cmd=" ".join(cmd))
        uploads = queue.Queue()
        errors = []

        def uploader():
            while True:
                f = uploads.get()
                if f is None:
                    return
                try:
                    if self._upload_plate(job, shot_dir, f):
                        log("plate_uploaded", shot=job["shot"], frame=f)
                except TransferError as e:
                    errors.append(str(e)[:300])
        th = threading.Thread(target=uploader, daemon=True)
        th.start()
        timeout = max(1800.0, 4.0 * float(job.get("estSeconds") or 900))
        t0 = self.clock()
        spf = {}
        with open(logpath, "a") as lf:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=self.repo, env=env,
                                    text=True, bufsize=1)
            killer = threading.Timer(timeout, proc.kill)
            killer.start()
            try:
                for line in proc.stdout:
                    lf.write(line)
                    m = FRAME_RE.search(line)
                    if m and m.group(1) == job["shot"]:
                        spf[m.group(2)] = float(m.group(3))
                        uploads.put(int(m.group(2)))
                rc = proc.wait()
            finally:
                killer.cancel()
        for f in range(job["frameStart"], job["frameEnd"] + 1):   # sweep: frames rendered by an earlier attempt
            uploads.put(f)
        uploads.put(None)
        th.join()
        rman = []
        for p in sorted(glob.glob(os.path.join(shot_dir, "_render_*.json"))):
            try:
                with open(p) as fh:
                    rman.append(json.load(fh))
            except (OSError, ValueError):
                pass
        devices = sorted({r.get("device") for r in rman if r.get("device")})
        frames = range(job["frameStart"], job["frameEnd"] + 1)
        missing = [f for f in frames if (job["shot"], f) not in self.uploaded]
        status, err = "DONE", None
        if rc != 0:
            status, err = "FAILED", f"blender exited {rc}" + (" (timeout)" if self.clock() - t0 >= timeout else "")
        elif self.m.get("requireGpu", True) and "CPU" in devices:
            status, err = "FAILED", "Cycles rendered on CPU on a GPU pod"
        elif missing or errors:
            status, err = "FAILED", f"{len(missing)} plates not delivered" + (f"; {errors[0]}" if errors else "")
        files = []
        for f in frames:
            p = os.path.join(shot_dir, f"{f:04d}.png")
            if (job["shot"], f) in self.uploaded and os.path.isfile(p):
                files.append({"frame": f, "size": os.path.getsize(p), "sha256": sha256_file(p)})
        man = {"v": 1, "status": status, "error": err, "runId": self.m["runId"], "pod": self.m["pod"],
               "jobId": job["jobId"], "shot": job["shot"], "frameStart": job["frameStart"],
               "frameEnd": job["frameEnd"], "attempt": attempt, "renderSeconds": round(self.clock() - t0, 1),
               "gpus": self.gpus, "files": files, "missing": missing,
               "render": {"devices": devices, "secondsPerFrame": spf,
                          "resolution": rman[-1].get("resolution") if rman else None,
                          "samples": rman[-1].get("samples") if rman else None,
                          "blender": rman[-1].get("blender") if rman else None,
                          "warnings": sorted({w for r in rman for w in r.get("warnings", [])})}}
        for target, path_or_obj in ((job.get("log"), logpath), (job.get("manifest"), man)):
            if not target:
                continue
            try:
                if isinstance(path_or_obj, dict):
                    self.net.put_json(target, path_or_obj)
                else:
                    self.net.put_file(target, path_or_obj)
            except TransferError as e:
                log("job_upload_failed", job=job["jobId"], error=str(e)[:200])
        log("job_end", job=job["jobId"], status=status, error=err, uploaded=len(files), missing=len(missing))
        return man

    def run(self):
        hb = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.beat()
        hb.start()
        results, status = {}, "DONE"
        try:
            if not self.check_gpu():
                status = "FAILED"
                results["_gpu"] = self.errors[-1]
            else:
                self.state = "fetching"
                self.beat()
                self.fetch_inputs()
                self.state = "rendering"
                for job in self.m["jobs"]:
                    self.job = job["jobId"]
                    man = None
                    for attempt in range(1, int(self.m.get("jobAttempts", 2)) + 1):
                        man = self.render_job(job, attempt)
                        if man["status"] == "DONE":
                            break
                        self.errors.append(f"{job['jobId']} attempt {attempt}: {man['error']}")
                    results[job["jobId"]] = {"status": man["status"], "error": man["error"],
                                             "missing": man["missing"]}
                self.job = None
                bad = [k for k, v in results.items() if v["status"] != "DONE"]
                status = "DONE" if not bad else ("FAILED" if len(bad) == len(results) else "PARTIAL")
        except Exception as e:  # noqa: BLE001 - anything unexpected: report FAILED so the pod gets replaced
            status = "FAILED"
            self.errors.append(f"{type(e).__name__}: {e}"[:500])
            log("pod_failed", error=self.errors[-1])
        self.state = "done" if status == "DONE" else "failed"
        done = {"status": status, "pod": self.m["pod"], "runId": self.m["runId"], "t": self.clock(),
                "framesDone": len(self.uploaded), "framesTotal": self.frames_total, "jobs": results,
                "errors": self.errors[-10:], "device": self.device, "gpus": self.gpus,
                "seconds": round(self.clock() - self.started, 1)}
        self.beat()
        try:
            self.net.put_json(self.m["done"], done)
        except TransferError as e:
            log("done_marker_failed", error=str(e)[:200])
        log("pod_done", status=status, frames=len(self.uploaded), total=self.frames_total)
        self.upload_pod_log()
        if self.m.get("exitWhenDone"):
            self.stop.set()
            return 0 if status == "DONE" else 1
        self.state = "idle"
        while True:  # the orchestrator terminates the pod; keep heart-beating "idle" until then
            time.sleep(3600)


def main(argv=None):
    p = argparse.ArgumentParser(description="Credential-free render pod runner (presigned URLs only).")
    p.add_argument("--manifest", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--blender", default=os.environ.get("BLENDER", "/opt/blender/blender"))
    p.add_argument("--pod-log", default=None)
    a = p.parse_args(argv)
    with open(a.manifest) as fh:
        m = json.load(fh)
    if m.get("kind") != "story-farm-presigned-pod":
        raise SystemExit("not a presigned pod manifest")
    return Pod(m, a.work, a.repo, a.blender, pod_log=a.pod_log).run()


if __name__ == "__main__":
    sys.exit(main())
