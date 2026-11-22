"""Fakes for broker tests: workers that 'render' by following the presigned chunk manifest against moto S3."""
import hashlib
import io
import json
import urllib.parse

from factory.compute.adapters.base import Adapter, CapacityError


def key_of(url):
    return urllib.parse.unquote(urllib.parse.urlsplit(url).path.lstrip("/"))


def png_bytes(shot, frame, w=8, h=8, liar=False):
    from PIL import Image
    seed = int(hashlib.sha256(f"{shot}{frame}{'x' if liar else ''}".encode()).hexdigest()[:6], 16)
    base = (seed % 200, (seed >> 8) % 200, (seed >> 16) % 200)
    if liar:
        base = (255 - base[0], 255 - base[1], 255 - base[2])
    im = Image.new("RGB", (w, h), base)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def render_manifest(s3, bucket, manifest, mode="ok", spf=1.0):
    """Do what presigned_pod.Pod does, straight against S3: plates, job manifest, done marker."""
    files = []
    w, h = 8, 8
    for job in manifest["jobs"]:
        for f in range(job["frameStart"], job["frameEnd"] + 1):
            if mode == "skip" and f == job["frameStart"]:
                continue
            data = png_bytes(job["shot"], f, w, h, liar=(mode == "liar"))
            s3.put_object(Bucket=bucket, Key=key_of(job["plates"][str(f)]["url"]), Body=data)
            sha = hashlib.sha256(data).hexdigest() if mode != "badsha" else "0" * 64
            files.append({"frame": f, "size": len(data), "sha256": sha})
        jm = {"status": "DONE" if mode not in ("skip",) else "FAILED", "jobId": job["jobId"], "files": files,
              "renderSeconds": 5 + spf * job_frames(job),
              "render": {"secondsPerFrame": {str(f["frame"]): spf for f in files}}}
        s3.put_object(Bucket=bucket, Key=key_of(job["manifest"]["url"]), Body=json.dumps(jm).encode())
    s3.put_object(Bucket=bucket, Key=key_of(manifest["done"]["url"]),
                  Body=json.dumps({"status": "DONE" if mode != "skip" else "PARTIAL"}).encode())


def job_frames(j):
    return j["frameEnd"] - j["frameStart"] + 1


class FakeAdapter(Adapter):
    """Push adapter; a task finishes `duration(frames)` seconds after start (fake clock)."""

    def __init__(self, pid, cfg, s3, bucket, clock, spf=5.0, overhead=10.0, mode="ok", conc=1, gbs_per_s=None,
                 fail_start=False, real_spf=None):
        super().__init__(pid, {**cfg, "concurrency": conc, "spf": {"preview": spf, "final": spf * 10},
                               "build_s": overhead, "cold_start_s": 0}, clock)
        self.s3, self.bucket, self.spf, self.overhead, self.mode = s3, bucket, spf, overhead, mode
        self.gbs_per_s = gbs_per_s
        self.fail_start = fail_start
        self.real_spf = real_spf if real_spf is not None else spf   # what it really takes (stragglers)
        self.started = []
        self.finished = {}

    def start(self, task):
        if self.fail_start:
            raise CapacityError("no stock")
        man = json.loads(self.s3.get_object(Bucket=self.bucket, Key=key_of(task["manifestUrl"]))["Body"].read())
        frames = sum(job_frames(j) for j in man["jobs"])
        h = {"attempt": task["attempt"], "t0": self.clock(), "due": self.clock() + self.overhead + frames * self.real_spf,
             "frames": frames}
        self.running[task["attempt"]] = {**h, "_man": man}
        self.started.append(task["attempt"])
        return h

    def poll(self, handle):
        rec = self.running.get(handle["attempt"])
        if rec is None:
            return {"state": "lost"}
        if self.clock() < rec["due"]:
            return {"state": "running"}
        if handle["attempt"] not in self.finished:
            if self.mode != "crash":
                render_manifest(self.s3, self.bucket, rec["_man"], self.mode, self.spf)
            self.finished[handle["attempt"]] = True
        usage = {}
        if self.gbs_per_s:
            usage["GB-s"] = (rec["due"] - rec["t0"]) * self.gbs_per_s
        return {"state": "exited" if self.mode != "crash" else "failed", "usage": usage,
                "error": "crashed" if self.mode == "crash" else None}

    def usage_estimate(self, est_s):
        return {"GB-s": est_s * self.gbs_per_s} if self.gbs_per_s else {}
