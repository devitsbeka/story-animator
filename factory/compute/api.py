"""
api.py - one call for the rest of the factory: render frames through the compute broker and get plates on disk.

    from factory.compute.api import render
    res = render("episodes/x/episode.json", "preview", frames=[(0, 23), (700, 700)], res="270x480", samples=12,
                 dest="episodes/x/plates", providers=None, deadline_min=60, budget=0.0)

Used by factory/run (render stage with --render compute, previs keyframes, agents' verification renders).
Providers default to $COMPUTE_PROVIDERS (comma list) or every schedulable provider in broker.yaml; paid overflow
only with allow_paid=True (or $COMPUTE_ALLOW_PAID=1) and within `budget`.
"""
import os
import time


def default_providers():
    v = os.environ.get("COMPUTE_PROVIDERS")
    return [x for x in v.split(",") if x] if v else None


def render(spec_path, quality="preview", frames=None, res=None, samples=None, dest=None, providers=None,
           deadline_min=None, budget=0.0, allow_paid=None, code_mode="head", library="auto", broker=None,
           interval=10.0, max_wall_min=None, log=print, run_id=None):
    from .broker import Broker
    if allow_paid is None:
        allow_paid = os.environ.get("COMPUTE_ALLOW_PAID") == "1"
    b = broker or Broker.from_env(providers=providers or default_providers())
    t0 = time.time()
    st = b.load(run_id) if run_id else b.submit(spec_path, quality, frames, res, samples, deadline_min, budget,
                                                allow_paid, code_mode=code_mode, library=library)
    log(f"[compute] run {st['runId']}: {st['frames']} frames, plan "
        f"{[(r['provider'], r['workers']) for r in st['plan']['providers']]} ~{st['plan']['expectedMin']} min")
    st = b.run_until_done(st, interval=interval, max_s=max_wall_min * 60 if max_wall_min else None)
    out = {"mode": "compute", "runId": st["runId"], "status": st["status"], "frames": st["frames"],
           "usd": st["spentUsd"], "usage": st["usage"], "seconds": round(time.time() - t0, 1),
           "summary": b.summary(st)}
    if st["status"] != "COMPLETE":
        out.update(missing=["?"], missingCount=st["frames"] - (st.get("progress") or {}).get("framesDone", 0))
        return out
    if dest:
        out["pulled"] = b.pull(st, dest)
    out.update(missing=[], missingCount=0)
    return out
