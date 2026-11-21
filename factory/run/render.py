"""Stage 7 render.

local: shard the episode into jobs with cloud/farm/jobs.py (one contiguous frame range inside one shot each) and run
       cloud/blender/render_episode.py per job, sequentially or with N worker processes. Plates land in
       episodes/<id>/plates/<shot>/####.png; --skip-existing makes a re-run resume where it stopped.
farm:  cloud/farm/orchestrator.py Farm.submit -> tick until RENDERED -> pull_plates (AWS; needs FARM_STACK or
       FARM_BUCKET/FARM_QUEUE_URL/FARM_TABLE).
stub:  in-process placeholder plates (tiny PNGs, a slow push-in on the previs keyframe when there is one) so the whole
       chain runs in CI time.
"""
import argparse
import concurrent.futures as cf
import importlib.util
import os
import shlex
import subprocess
import time

from factory.director.paths import RENDER_PY, ROOT

DEFAULT_BLENDER = os.environ.get("BLENDER", "/opt/blender/blender-4.2.3-linux-x64/blender")
FARM_DIR = os.path.join(ROOT, "cloud", "farm")


def _load(name, path):
    import sys
    if FARM_DIR not in sys.path:
        sys.path.insert(0, FARM_DIR)      # orchestrator.py imports its siblings (farmio, jobs) by bare name
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def jobs_mod():
    return _load("farm_jobs", os.path.join(FARM_DIR, "jobs.py"))


def split(spec, quality, engine=None, shots=None, res=None, samples=None, target_job_s=None):
    j = jobs_mod()
    js = j.split_episode(spec, quality, engine, target_job_s or j.DEFAULT_TARGET_JOB_S, shots=shots, res=res, samples=samples)
    j.check_coverage(spec, js)
    return js


def farm_estimate(spec, quality, workers=8, usd_per_gpu_hour=None):
    from . import costs
    j = jobs_mod()
    js = j.split_episode(spec, quality)
    return j.estimate(js, usd_per_gpu_hour or costs.prices()["farm_usd_per_gpu_hour"], workers)


def blender_cmd(job, spec_path, plates, blender=None, threads=None, extra=()):
    cmd = [*shlex.split(blender or DEFAULT_BLENDER), "-b", "--factory-startup", "-P", RENDER_PY, "--",
           "--spec", spec_path, "--start", str(job["frameStart"]), "--end", str(job["frameEnd"]),
           "--out", plates, "--quality", job["quality"], "--engine", job["engine"], "--root", ROOT, "--skip-existing"]
    if job.get("res"):
        cmd += ["--res", str(job["res"])]
    if job.get("samples"):
        cmd += ["--samples", str(int(job["samples"]))]
    if threads:
        cmd += ["--threads", str(threads)]
    return cmd + list(extra)


def run_cmds(cmds, workers=1, log_dir=None, env=None, timeout=None, log=print):
    """[(name, argv)] -> {name: returncode}. N in parallel, each logs to <log_dir>/<name>.log."""
    os.makedirs(log_dir, exist_ok=True) if log_dir else None

    def one(item):
        name, argv = item
        t0 = time.time()
        logf = open(os.path.join(log_dir, f"{name}.log"), "w") if log_dir else subprocess.DEVNULL
        try:
            rc = subprocess.run(argv, stdout=logf, stderr=subprocess.STDOUT, env=env, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            rc = -9
        finally:
            if log_dir:
                logf.close()
        log(f"[render] {name}: rc={rc} ({time.time() - t0:.1f}s)")
        return name, rc

    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return dict(ex.map(one, cmds))


def missing_frames(spec, plates, shots=None):
    out = []
    for s in spec["shots"]:
        if shots and s["id"] not in shots:
            continue
        for f in range(int(s["from"]), int(s["to"])):
            if not os.path.isfile(os.path.join(plates, s["id"], f"{f:04d}.png")):
                out.append(f"{s['id']}/{f:04d}")
    return out


def render_local(spec, spec_path, plates, quality="preview", engine=None, shots=None, workers=1, res=None, samples=None,
                 threads=None, blender=None, log_dir=None, env=None, log=print):
    js = split(spec, quality, engine, shots=shots, res=res, samples=samples)
    env = dict(env or os.environ)
    env.setdefault("LIBRARY_STORE", os.path.join(ROOT, "library_store"))
    cmds = [(j["jobId"], blender_cmd(j, spec_path, plates, blender, threads)) for j in js]
    log(f"[render] local: {len(js)} jobs, {sum(j['frames'] for j in js)} frames, {workers} worker(s)")
    t0 = time.time()
    rcs = run_cmds(cmds, workers, log_dir, env, log=log)
    miss = missing_frames(spec, plates, shots)
    return {"mode": "local", "jobs": len(js), "frames": sum(j["frames"] for j in js), "failedJobs": sorted(k for k, v in rcs.items() if v),
            "missing": miss[:50], "missingCount": len(miss), "seconds": round(time.time() - t0, 1),
            "cpuHours": round((time.time() - t0) * max(1, workers) / 3600, 4), "usd": 0.0}


# ------------------------------------------------------------------------------------------------ stub
def stub_plates(spec, plates, shots=None, size=(108, 192), keys_dir=None):
    """Placeholder plates for every frame: the previs keyframe (if any) with a slow push-in, else a graded card."""
    from PIL import Image, ImageDraw
    n = 0
    for i, s in enumerate(spec["shots"]):
        if shots and s["id"] not in shots:
            continue
        base = None
        if keys_dir:
            d = os.path.join(keys_dir, s["id"])
            cands = sorted(f for f in os.listdir(d) if f.endswith(".png")) if os.path.isdir(d) else []
            if cands:
                base = Image.open(os.path.join(d, cands[0])).convert("RGB").resize((size[0] * 2, size[1] * 2))
        if base is None:
            base = Image.new("RGB", (size[0] * 2, size[1] * 2))
            dr = ImageDraw.Draw(base)
            hue = (i * 47) % 255
            for y in range(base.height):
                t = y / base.height
                dr.line([(0, y), (base.width, y)], fill=(int(20 + 60 * t), int(30 + (hue % 90) * t), int(70 + 100 * (1 - t))))
            dr.ellipse([base.width * 0.35, base.height * 0.4, base.width * 0.65, base.height * 0.55], fill=(220, 190, 150))
            dr.text((8, 8), s["id"], fill=(255, 255, 255))
        d = os.path.join(plates, s["id"])
        os.makedirs(d, exist_ok=True)
        a, b = int(s["from"]), int(s["to"])
        for f in range(a, b):
            p = os.path.join(d, f"{f:04d}.png")
            if os.path.exists(p):
                continue
            t = (f - a) / max(1, b - a - 1)
            z = 1.0 - 0.12 * t                     # push-in so the frames are not frozen
            w, h = base.width * z, base.height * z
            x0, y0 = (base.width - w) / 2, (base.height - h) / 2
            base.crop((int(x0), int(y0), int(x0 + w), int(y0 + h))).resize(size).save(p, optimize=False, compress_level=1)
            n += 1
    return {"mode": "stub", "frames": n, "usd": 0.0, "missing": [], "missingCount": 0}


# ------------------------------------------------------------------------------------------------ farm
def farm_client():
    orch = _load("farm_orchestrator", os.path.join(FARM_DIR, "orchestrator.py"))
    a = argparse.Namespace(stack=os.environ.get("FARM_STACK"), region=os.environ.get("AWS_REGION", "us-east-1"))
    return orch, orch.farm_from_args(a)


def render_farm(spec, ep_dir, episodes_root, quality, budget=None, shots=None, run_id=None, on_submit=None, farm=None,
                poll_s=60, timeout_s=48 * 3600, log=print, sleep=time.sleep):
    """Submit (unless run_id is already known: resume), watch until RENDERED, pull plates. -> result dict."""
    if farm is None:
        _, farm = farm_client()
    if not run_id:
        sub = farm.submit([spec], quality, budget=budget, shots=shots)
        run_id = sub[0]["runId"]
        log(f"[render] farm run {run_id}: {sub[0].get('jobs')} jobs, est ${sub[0]['estimate']['usd']}")
        if on_submit:
            on_submit(run_id, sub[0])
    t0 = time.time()
    while True:
        st = farm.tick(run_id)
        if st in ("RENDERED", "DONE"):
            break
        if st in ("FAILED", "CANCELLED"):
            info = farm.status(run_id)
            raise RuntimeError(f"farm run {run_id} {st}: {info.get('failed') or info}")
        if time.time() - t0 > timeout_s:
            raise RuntimeError(f"farm run {run_id} still {st} after {timeout_s}s")
        sleep(poll_s)
    info = farm.status(run_id)
    pulled = farm.pull_plates(run_id, episodes_root)
    if pulled["missing"]:
        raise RuntimeError(f"farm run {run_id}: {len(pulled['missing'])} plates missing after pull")
    return {"mode": "farm", "runId": run_id, "plates": pulled["plates"], "usd": float(info.get("spentUsd") or 0),
            "frames": info.get("frames"), "missing": [], "missingCount": 0}
