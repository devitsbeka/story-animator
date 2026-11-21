"""
jobs.py - split an episode.json into GPU render jobs and estimate what they cost (pure Python, no AWS).

A JOB is one contiguous, INCLUSIVE frame range inside ONE shot (render_episode.py rebuilds the whole scene
for every shot a range touches, so a job never straddles a cut). Long or expensive shots are cut into
several jobs so that every job takes roughly `target_job_s` GPU seconds:

    est_job_s = overhead_s + build_s + frames * spf(shot)

`spf(shot)` (GPU seconds per frame) comes from, in order:
  1. a calibration table {shotId: seconds_per_frame} measured on a previous run (see calibration_from_manifests),
  2. the quality preset's base seconds/frame x a shot complexity factor read from the spec.

Job ids are deterministic ("<episode>-<shot>-f<start:05d>-<end:05d>-<quality>"), so re-submitting the same
plan enqueues the same ids and the worker's done-manifest check makes the re-run a no-op.

    python cloud/farm/jobs.py --spec episodes/sentinel/episode_v2.json --quality final --workers 8
"""
import argparse
import heapq
import json
import math
import sys

# Base GPU seconds/frame on one L4 (g6) / A10G (g5) at the preset's resolution and samples, before the shot
# complexity factor. Derived from measured CPU plates (Sentinel v2, Cycles, 270x480, 16 spp: 8.6-13.5 s/frame on
# 2 shared CPU threads) scaled by pixels x samples and a ~35x GPU/2-thread-CPU ratio (Blender Open Data).
# Replace with measured numbers after the first cloud run: calibration_from_manifests() does that per shot.
PRESETS = {
    "preview": {"engine": "CYCLES", "scale": 0.5, "samples": 16, "spf": 3.0, "build_s": 40.0},
    "final": {"engine": "CYCLES", "scale": 1.0, "samples": 128, "spf": 40.0, "build_s": 60.0},
}
JOB_OVERHEAD_S = 25.0        # container already warm: sync deltas, spec download, Blender start, uploads
DEFAULT_TARGET_JOB_S = 900.0  # ~15 min per job: short enough for spot, long enough to amortise the build
MIN_FRAMES_PER_JOB = 8
MAX_SHOT_COMPLEXITY = 2.5


def shot_frames(shot):
    """Shots use [from, to) (render_episode.shots_for_range renders from..to-1)."""
    a, b = int(shot["from"]), int(shot["to"])
    if b <= a:
        raise ValueError(f"shot {shot.get('id')} has empty frame range {a}..{b}")
    return a, b - 1


def shot_complexity(shot):
    """Cheap, monotone cost factor from what the spec puts in the shot (1.0 = ocean + sky + yacht)."""
    f = 1.0
    f += 0.15 * len(shot.get("actors") or [])
    f += 0.04 * len(shot.get("props") or [])
    isl = shot.get("island")
    if isl and (not isinstance(isl, dict) or isl.get("visible", True)):
        f += 0.20  # instanced trees / rocks / shrubs
    if shot.get("fires"):
        f += 0.15  # emissive fire cards along the tree line
    f += 0.10 * len(shot.get("fx") or [])
    cam = shot.get("camera") or {}
    if isinstance(cam, dict) and (cam.get("dof") or cam.get("fStop")):
        f += 0.10
    return min(f, MAX_SHOT_COMPLEXITY)


def seconds_per_frame(shot, quality, calibration=None):
    if calibration and shot["id"] in calibration:
        return float(calibration[shot["id"]])
    return PRESETS[quality]["spf"] * shot_complexity(shot)


def job_id(episode_id, shot_id, start, end, quality):
    return f"{episode_id}-{shot_id}-f{start:05d}-{end:05d}-{quality}"


def _even_ranges(a, b, k):
    """Split inclusive [a, b] into k contiguous, non-empty inclusive ranges whose sizes differ by <= 1."""
    n = b - a + 1
    k = max(1, min(k, n))
    bounds = [a + (i * n) // k for i in range(k + 1)]
    return [(bounds[i], bounds[i + 1] - 1) for i in range(k)]


def split_episode(spec, quality="final", engine=None, target_job_s=DEFAULT_TARGET_JOB_S, calibration=None,
                  shots=None, frame_range=None, min_frames=MIN_FRAMES_PER_JOB, res=None, samples=None):
    """-> list of job dicts (film order). `shots`: optional iterable of shot ids; `frame_range`: (start, end) incl."""
    if quality not in PRESETS:
        raise ValueError(f"unknown quality {quality!r} (expected one of {sorted(PRESETS)})")
    if target_job_s <= 0:
        raise ValueError("target_job_s must be > 0")
    preset = PRESETS[quality]
    eid = spec["id"]
    want = set(shots) if shots else None
    jobs = []
    for shot in spec["shots"]:
        if want is not None and shot["id"] not in want:
            continue
        a, b = shot_frames(shot)
        if frame_range:
            a, b = max(a, frame_range[0]), min(b, frame_range[1])
            if a > b:
                continue
        n = b - a + 1
        spf = seconds_per_frame(shot, quality, calibration)
        k = max(1, math.ceil(n * spf / target_job_s))
        k = min(k, max(1, n // max(1, min_frames)))
        for s, e in _even_ranges(a, b, k):
            frames = e - s + 1
            jobs.append({
                "jobId": job_id(eid, shot["id"], s, e, quality),
                "episodeId": eid,
                "shot": shot["id"],
                "frameStart": s,
                "frameEnd": e,
                "frames": frames,
                "quality": quality,
                "engine": engine or preset["engine"],
                "res": res,
                "samples": samples,
                "estSecondsPerFrame": round(spf, 3),
                "estSeconds": round(JOB_OVERHEAD_S + preset["build_s"] + frames * spf, 1),
            })
    if want is not None:
        missing = want - {s["id"] for s in spec["shots"]}
        if missing:
            raise ValueError(f"unknown shot ids: {sorted(missing)}")
    return jobs


def check_coverage(spec, jobs):
    """Raise if jobs overlap, leave gaps inside a shot, or straddle a cut. Returns frame count."""
    by_shot = {}
    for j in jobs:
        by_shot.setdefault(j["shot"], []).append((j["frameStart"], j["frameEnd"]))
    total = 0
    for shot in spec["shots"]:
        if shot["id"] not in by_shot:
            continue
        a, b = shot_frames(shot)
        rs = sorted(by_shot[shot["id"]])
        for (s, e) in rs:
            if s < a or e > b or s > e:
                raise AssertionError(f"job {s}..{e} outside shot {shot['id']} {a}..{b}")
        for (s0, e0), (s1, _) in zip(rs, rs[1:]):
            if s1 != e0 + 1:
                raise AssertionError(f"shot {shot['id']}: gap/overlap between {e0} and {s1}")
        total += sum(e - s + 1 for s, e in rs)
    if len({j["jobId"] for j in jobs}) != len(jobs):
        raise AssertionError("duplicate job ids")
    return total


def lpt_order(jobs):
    """Longest-processing-time first: the order to enqueue so N workers finish close together."""
    return sorted(jobs, key=lambda j: (-j["estSeconds"], j["jobId"]))


def makespan(jobs, workers):
    """Wall-clock seconds for `workers` identical GPUs pulling `jobs` in LPT order (greedy list scheduling)."""
    if workers < 1:
        raise ValueError("workers must be >= 1")
    heap = [0.0] * min(workers, max(1, len(jobs)))
    heapq.heapify(heap)
    for j in lpt_order(jobs):
        t = heapq.heappop(heap)
        heapq.heappush(heap, t + j["estSeconds"])
    return max(heap) if jobs else 0.0


def estimate(jobs, usd_per_gpu_hour, workers=1, boot_s=240.0):
    """Cost model: every GPU-second billed (incl. per-job overhead) + one cold boot per worker."""
    gpu_s = sum(j["estSeconds"] for j in jobs)
    w = max(1, min(workers, len(jobs) or 1))
    billed_s = gpu_s + w * boot_s
    return {
        "jobs": len(jobs),
        "frames": sum(j["frames"] for j in jobs),
        "gpuHours": round(gpu_s / 3600, 3),
        "billedHours": round(billed_s / 3600, 3),
        "usdPerGpuHour": usd_per_gpu_hour,
        "usd": round(billed_s / 3600 * usd_per_gpu_hour, 2),
        "workers": w,
        "wallClockMinutes": round((makespan(jobs, w) + boot_s) / 60, 1),
    }


def calibration_from_manifests(manifests):
    """Per-shot measured GPU seconds/frame from worker job manifests (mean over frames, build excluded)."""
    acc = {}
    for m in manifests:
        spf = (m.get("render") or {}).get("secondsPerFrame") or {}
        if not spf:
            continue
        acc.setdefault(m["shot"], []).extend(float(v) for v in spf.values())
    return {k: round(sum(v) / len(v), 3) for k, v in acc.items() if v}


def main(argv=None):
    p = argparse.ArgumentParser(description="Split an episode into GPU render jobs and estimate cost.")
    p.add_argument("--spec", required=True)
    p.add_argument("--quality", choices=sorted(PRESETS), default="final")
    p.add_argument("--engine", choices=["CYCLES", "EEVEE"], default=None)
    p.add_argument("--target-job-minutes", type=float, default=DEFAULT_TARGET_JOB_S / 60)
    p.add_argument("--calibration", help="JSON {shotId: secondsPerFrame}")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--usd-per-gpu-hour", type=float, default=0.60)
    p.add_argument("--json", action="store_true", help="print the job list as JSON")
    a = p.parse_args(argv)
    with open(a.spec) as fh:
        spec = json.load(fh)
    cal = json.load(open(a.calibration)) if a.calibration else None
    jobs = split_episode(spec, a.quality, a.engine, a.target_job_minutes * 60, cal)
    check_coverage(spec, jobs)
    if a.json:
        json.dump(jobs, sys.stdout, indent=1)
    else:
        json.dump(estimate(jobs, a.usd_per_gpu_hour, a.workers), sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
