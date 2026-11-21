"""
chunker.py - split an episode's frame range into render chunks (one RENDER JOB each).

  python chunker.py --duration 2416 --seconds 8                # -> JSON list of chunks
  python chunker.py --spec episodes/sentinel/episode.json --seconds 8 --snap
  python chunker.py --spec ... --chunks 12 --jobs --quality final --engine CYCLES   # -> RENDER JOB messages

A chunk is {chunk, frameStart, frameEnd} with frameEnd INCLUSIVE (same convention as
render_episode.py --end). Chunks are contiguous, non-overlapping and cover 0..durationFrames-1.
chunk ids are "f<start:05d>-<end:05d>" so they sort in film order and segments/<chunk>.mp4 concat cleanly.

--snap moves each interior boundary to the nearest shot boundary when one lies within
`snap_tolerance` x the nominal chunk length: every shot a chunk touches is rebuilt in Blender,
so chunks that do not straddle shot cuts save a scene build each.
"""
import argparse
import json
import math
import sys


def chunk_id(start, end):
    return f"f{start:05d}-{end:05d}"


def split(duration_frames, fps=30, seconds_per_chunk=8.0, n_chunks=None, shot_starts=None,
          snap_tolerance=0.35, min_frames=1):
    """Return [{chunk, frameStart, frameEnd}] covering [0, duration_frames)."""
    duration_frames = int(duration_frames)
    if duration_frames <= 0:
        raise ValueError("duration_frames must be > 0")
    if n_chunks is None:
        if seconds_per_chunk <= 0:
            raise ValueError("seconds_per_chunk must be > 0")
        target = max(1, int(round(seconds_per_chunk * fps)))
        n_chunks = max(1, math.ceil(duration_frames / target))
    n_chunks = max(1, min(int(n_chunks), duration_frames // max(1, min_frames)))
    # even split: boundaries b_0=0 < b_1 < ... < b_n=duration
    bounds = [round(i * duration_frames / n_chunks) for i in range(n_chunks + 1)]
    if shot_starts:
        nominal = duration_frames / n_chunks
        tol = snap_tolerance * nominal
        cuts = sorted({int(s) for s in shot_starts if 0 < int(s) < duration_frames})
        for i in range(1, n_chunks):
            best = min(cuts, key=lambda c: abs(c - bounds[i]), default=None)
            if best is not None and abs(best - bounds[i]) <= tol and bounds[i - 1] + min_frames <= best:
                bounds[i] = best
        # keep strictly increasing / minimum size after snapping
        for i in range(1, n_chunks + 1):
            if bounds[i] < bounds[i - 1] + min_frames:
                bounds[i] = min(duration_frames, bounds[i - 1] + min_frames)
        bounds[-1] = duration_frames
        bounds = [b for i, b in enumerate(bounds) if i == 0 or b > bounds[i - 1]]
    out = []
    for a, b in zip(bounds, bounds[1:]):
        out.append({"chunk": chunk_id(a, b - 1), "frameStart": a, "frameEnd": b - 1})
    return out


def split_spec(spec, seconds_per_chunk=8.0, n_chunks=None, snap=True, **kw):
    starts = [s["from"] for s in spec.get("shots", [])] if snap else None
    return split(spec["durationFrames"], spec.get("fps", 30), seconds_per_chunk, n_chunks, starts, **kw)


def jobs_for(spec, chunks, quality="preview", engine="EEVEE", job_prefix=None):
    eid = spec["id"]
    prefix = job_prefix or eid
    return [{
        "jobId": f"{prefix}-{c['chunk']}-{quality}",
        "episodeId": eid,
        "chunk": c["chunk"],
        "frameStart": c["frameStart"],
        "frameEnd": c["frameEnd"],
        "quality": quality,
        "engine": engine,
        "outputPrefix": f"episodes/{eid}/plates/",
    } for c in chunks]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--duration", type=int, help="durationFrames")
    g.add_argument("--spec", help="episode.json (gives durationFrames, fps and shot cuts)")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--seconds", type=float, default=8.0, help="target seconds per chunk")
    p.add_argument("--chunks", type=int, default=None, help="exact number of chunks (overrides --seconds)")
    p.add_argument("--snap", action="store_true", help="snap boundaries to shot cuts (needs --spec)")
    p.add_argument("--jobs", action="store_true", help="emit RENDER JOB messages (needs --spec)")
    p.add_argument("--quality", choices=["preview", "final"], default="preview")
    p.add_argument("--engine", choices=["EEVEE", "CYCLES"], default="EEVEE")
    a = p.parse_args(argv)
    if a.spec:
        with open(a.spec) as fh:
            spec = json.load(fh)
        chunks = split_spec(spec, a.seconds, a.chunks, snap=a.snap)
        out = jobs_for(spec, chunks, a.quality, a.engine) if a.jobs else chunks
    else:
        if a.jobs or a.snap:
            p.error("--jobs/--snap need --spec")
        out = split(a.duration, a.fps, a.seconds, a.chunks)
    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
