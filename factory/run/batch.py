"""Run N ideas concurrently under one budget ceiling.

Each idea runs as its own `python -m factory.run` process (own episode dir and run.json), at most --max-parallel at a
time. Admission control: an idea starts only if
    spent(finished runs) + allowance(running runs) + estimate(idea) <= budget
and is given allowance = min(budget - committed, estimate x overrun) as its own --budget, which the child enforces
before every stage (and passes to the farm as the submit ceiling). Ideas that do not fit are recorded as
`budget_refused`; they are retried after every completion, so a cheap finish frees room for a waiting idea.
"""
import json
import os
import subprocess
import sys
import threading
import time

from . import costs
from .pipeline import slug
from .state import now_iso

EXIT_STATUS = {0: "published", 3: "awaiting_approval", 4: "returned", 5: "budget_exceeded", 1: "failed", 2: "error"}


def read_ideas(path):
    """One idea per line; blank lines and # comments ignored. Optional 'short|' or 'docuseries|' prefix sets the format."""
    out = []
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        fmt = None
        if "|" in ln and ln.split("|", 1)[0].strip() in ("short", "docuseries"):
            fmt, ln = (x.strip() for x in ln.split("|", 1))
        out.append({"idea": ln, "format": fmt})
    return out


def run_batch(ideas, child_args, episodes_dir, fmt="short", render="local", quality="preview", offline=False,
              max_parallel=2, budget=None, overrun=1.5, log=print, python=sys.executable, cwd=None):
    os.makedirs(episodes_dir, exist_ok=True)
    items = []
    for it in ideas:
        f = it.get("format") or fmt
        eid = slug(it["idea"])
        items.append({"idea": it["idea"], "format": f, "episodeId": eid,
                      "estimate": costs.estimate_episode(f, render, quality, offline=offline)["usd"], "status": "queued"})
    lock = threading.Lock()
    path = os.path.join(episodes_dir, f"batch_{time.strftime('%Y%m%d_%H%M%S')}.json")
    doc = {"schema": "factory.run.batch/1", "created": now_iso(), "budgetUSD": budget, "maxParallel": max_parallel,
           "items": items, "file": path}

    def save():
        doc["updated"] = now_iso()
        doc["committedUSD"] = round(committed(), 4)
        with open(path + ".part", "w") as fh:
            json.dump(doc, fh, indent=1)
        os.replace(path + ".part", path)

    def committed():
        tot = 0.0
        for it in items:
            if it["status"] == "running":
                tot += it["allowance"] if it.get("allowance") is not None else it["estimate"]
            elif "spentUSD" in it:
                tot += it["spentUSD"]
        return tot

    def child(it):
        cmd = [python, "-m", "factory.run", it["idea"], "--format", it["format"], "--episode-id", it["episodeId"],
               "--episodes-dir", episodes_dir, *child_args]
        if os.path.exists(os.path.join(episodes_dir, it["episodeId"], "run.json")):
            cmd.append("--resume")
        if it.get("allowance") is not None:
            cmd += ["--budget", f"{it['allowance']:.4f}"]
        logp = os.path.join(episodes_dir, it["episodeId"] + ".batch.log")
        os.makedirs(os.path.dirname(logp), exist_ok=True)
        t0 = time.time()
        with open(logp, "w") as fh:
            rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=cwd).returncode
        rj = os.path.join(episodes_dir, it["episodeId"], "run.json")
        run = json.load(open(rj)) if os.path.exists(rj) else {}
        with lock:
            it.update(status=run.get("status") or EXIT_STATUS.get(rc, f"rc{rc}"), rc=rc, seconds=round(time.time() - t0, 1),
                      spentUSD=float((run.get("cost") or {}).get("totalUSD") or 0), log=logp,
                      qcDecision=(run.get("qc") or {}).get("decision"))
            save()
        log(f"[batch] {it['episodeId']}: {it['status']} (${it['spentUSD']:.2f}, {it['seconds']}s)")

    threads = []
    with lock:
        save()
    while True:
        with lock:
            running = sum(1 for it in items if it["status"] == "running")
            queued = [it for it in items if it["status"] in ("queued", "budget_refused")]
            started = False
            for it in queued:
                if running >= max_parallel:
                    break
                c = committed()
                if budget is not None and c + it["estimate"] > budget + 1e-9:
                    if it["status"] != "budget_refused":
                        log(f"[batch] {it['episodeId']}: waiting/refused (needs ~${it['estimate']:.2f}, ${c:.2f} committed of ${budget:.2f})")
                    it["status"] = "budget_refused"
                    continue
                it["allowance"] = None if budget is None else round(min(budget - c, max(it["estimate"] * overrun, it["estimate"])), 4)
                it["status"] = "running"
                running += 1
                started = True
                th = threading.Thread(target=child, args=(it,), daemon=True)
                threads.append(th)
                th.start()
            save()
            any_running = any(it["status"] == "running" for it in items)
        if not any_running and not started:
            break
        time.sleep(0.2)
    for th in threads:
        th.join()
    with lock:
        doc["finished"] = now_iso()
        save()
    return doc
