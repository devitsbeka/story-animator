"""
planner.py - how many workers on which providers, so a job finishes by its deadline at the lowest cost.

Per provider p (from its calibrated profile):
    chunk c_p     frames per task: the largest c with cold + build + c*spf <= runtime_fraction * max_runtime
                  (providers with long/no runtime limit get chunks of ~target_chunk_s, never more than a shot)
    t_chunk       cold + build + c_p * spf                        (seconds per task)
    fps_p         workers_p * c_p / t_chunk                        (frames/s at full concurrency)
    freecap_p     remaining free quota / units per frame          (inf when the provider has no metered quota)
    $/frame       paid price per frame (hourly price or quota unit price beyond free)

Mix:
  1. FREE providers run in parallel (the work-stealing queue balances them); the finish time T solves
     sum_p min(fps_p * (T - cold_p), freecap_p) = frames  (water-filling, bisection).
  2. If T > deadline (or free quota runs out), and paid overflow is allowed, add PAID options cheapest $/frame
     first, each contributing up to fps_p * (deadline - cold_p) frames, until the remainder fits; then T again.
  3. final quality: GPU providers first; CPU providers only take final frames when one of their chunks finishes
     inside the deadline (queue policy cpu_final=deadline enforces the same rule at claim time).
Output: per provider workers, frames, chunk size, expected minutes, quota units, $; plus feasibility.
Re-planning is the same call with the remaining frames, the elapsed time and the live provider set.
"""
import math

INF = float("inf")


def spf_of(prof, quality):
    s = (prof.get("spf") or {}).get(quality)
    return float(s) if s else None


def chunk_frames(prof, quality, runtime_fraction=0.6, target_chunk_s=900.0, max_frames=None):
    spf = spf_of(prof, quality)
    if not spf:
        return 0
    overhead = float(prof.get("coldStartS", 0)) + float(prof.get("buildS", 0))
    limit = float(prof.get("maxRuntimeS") or 900) * runtime_fraction
    budget = min(limit, max(target_chunk_s, overhead + spf))
    c = int((budget - overhead) // spf)
    if max_frames:
        c = min(c, int(max_frames))
    return max(0, c)


def provider_rates(prof, quality, frames, ledger_free=None, usage_per_s=None, runtime_fraction=0.6,
                   target_chunk_s=900.0, shot_frames=None):
    c = chunk_frames(prof, quality, runtime_fraction, target_chunk_s, max_frames=shot_frames)
    if c <= 0:
        return None
    spf = spf_of(prof, quality)
    t_chunk = float(prof.get("coldStartS", 0)) + float(prof.get("buildS", 0)) + c * spf
    workers = int(prof.get("concurrency") or 1)
    fps1 = c / t_chunk
    # quota: units consumed per frame = usage_per_s * t_chunk / c
    if ledger_free is None or usage_per_s is None:
        freecap = INF
    else:
        per_frame = usage_per_s * t_chunk / c
        freecap = ledger_free / per_frame if per_frame > 0 else INF
    return {"chunk": c, "tChunk": t_chunk, "workers": workers, "fps1": fps1, "fps": workers * fps1,
            "freecap": freecap, "usagePerFrame": (usage_per_s or 0) * t_chunk / c}


def _done_by(rates, T):
    tot = 0.0
    for r in rates:
        t = max(0.0, T - r["cold"])
        tot += min(r["fps"] * t, r["cap"])
    return tot


def finish_time(rates, frames):
    if frames <= 0:
        return 0.0
    if _done_by(rates, 1e9) < frames - 1e-6:
        return INF
    lo, hi = 0.0, 1.0
    while _done_by(rates, hi) < frames:
        hi *= 2
    for _ in range(80):
        mid = (lo + hi) / 2
        if _done_by(rates, mid) >= frames:
            hi = mid
        else:
            lo = mid
    return hi


def plan(frames, quality, providers, deadline_s=None, budget_usd=None, allow_paid=False, shot_frames=None,
         runtime_fraction=0.6, target_chunk_s=900.0, min_chunk=1, _adapted=False, _share=None):
    """Small jobs: chunks shrink to ceil(frames / total workers) (>= min_chunk) so every worker gets a share
    (more parallelism beats amortising the scene build when the job is short).

    providers: [{"id", "profile", "free": bool, "ledgerFree": units|None, "usagePerS": units/s|None,
                    "priceUsdPerS": $/s of one worker when paid (0 for free), "priority": int, "available": bool}]
    -> plan dict."""
    deadline = float(deadline_s) if deadline_s else INF
    rows, skipped = [], []
    for p in providers:
        prof = p["profile"]
        if not p.get("available", True):
            skipped.append({"id": p["id"], "why": p.get("reason") or "unavailable"})
            continue
        r = provider_rates({**prof, "concurrency": p.get("concurrency", prof.get("concurrency", 1))}, quality, frames,
                           p.get("ledgerFree"), p.get("usagePerS"), runtime_fraction, target_chunk_s, shot_frames)
        if r is None:
            skipped.append({"id": p["id"], "why": f"no {quality} throughput (spf unknown or chunk does not fit)"})
            continue
        gpu = bool(prof.get("gpu"))
        if quality == "final" and not gpu and r["tChunk"] + float(prof.get("coldStartS", 0)) > deadline:
            skipped.append({"id": p["id"], "why": "CPU cannot finish a final chunk inside the deadline"})
            continue
        price_frame = float(p.get("priceUsdPerS") or 0) * r["tChunk"] / r["chunk"]
        rows.append({"id": p["id"], "gpu": gpu, "free": bool(p.get("free")), "priority": p.get("priority", 50),
                     "cold": float(prof.get("coldStartS", 0)), "cap": r["freecap"] if p.get("free") else INF,
                     "usdPerFrame": price_frame, **r})
    order_key = (lambda r: (not r["gpu"], r["priority"], -r["fps"])) if quality == "final" else \
        (lambda r: (r["priority"], -r["fps"]))
    if not _adapted and rows:
        W = sum(r["workers"] for r in rows if r["free"]) or sum(r["workers"] for r in rows)
        cap = max(min_chunk, math.ceil(frames / max(1, W)))
        if any(r["chunk"] > cap for r in rows):
            return plan(frames, quality, providers, deadline_s, budget_usd, allow_paid,
                        min(cap, shot_frames) if shot_frames else cap, runtime_fraction, target_chunk_s, min_chunk,
                        _adapted=True, _share=max(float(min_chunk), frames / max(1, W)))
    free = sorted([r for r in rows if r["free"]], key=order_key)
    paid = sorted([r for r in rows if not r["free"]], key=lambda r: (r["usdPerFrame"], -r["fps"]))
    use = list(free)
    T = finish_time(use, frames)
    notes = []
    if (T > deadline or T == INF) and allow_paid:
        for r in paid:
            use.append(r)
            T = finish_time(use, frames)
            if T <= deadline:
                break
    elif (T > deadline or T == INF) and paid:
        notes.append("free capacity alone misses the deadline; pass --allow-paid to add paid workers")
    if T == INF:
        notes.append("not enough capacity (free quota exhausted and no paid overflow)")
    # frames per provider at time T (capped by free quota); scale so they sum to `frames`
    alloc = []
    tot = 0.0
    for r in use:
        f = 0.0 if T == INF else min(r["fps"] * max(0.0, T - r["cold"]), r["cap"])
        alloc.append(f)
        tot += f
    if T != INF and tot > 0:
        alloc = [a * frames / tot for a in alloc]
    out_rows, usd = [], 0.0
    for r, f in zip(use, alloc):
        if f <= 0.5 and T != INF:
            continue
        per = min(float(r["chunk"]), _share) if _share else float(r["chunk"])
        n_chunks = max(1, math.ceil(f / per - 1e-9)) if f > 0 else 0
        workers = min(r["workers"], n_chunks) if n_chunks else 0
        cost = 0.0 if r["free"] else f * r["usdPerFrame"]
        usd += cost
        out_rows.append({"provider": r["id"], "workers": workers, "frames": round(f), "chunkFrames": r["chunk"],
                         "secondsPerChunk": round(r["tChunk"], 1), "framesPerMin": round(r["fps"] * 60, 2),
                         "freeQuotaFrames": None if r["cap"] == INF else round(r["cap"]),
                         "usage": round(f * r["usagePerFrame"], 1), "usd": round(cost, 4), "free": r["free"],
                         "gpu": r["gpu"]})
    feasible = T != INF and T <= deadline
    if budget_usd is not None and usd > float(budget_usd) + 1e-9:
        feasible = False
        notes.append(f"plan costs ${usd:.2f} > budget ${float(budget_usd):.2f}")
    return {"frames": frames, "quality": quality, "deadlineMin": None if deadline == INF else round(deadline / 60, 1),
            "expectedMin": None if T == INF else round(T / 60, 2), "usd": round(usd, 4), "feasible": feasible,
            "allowPaid": bool(allow_paid), "providers": out_rows, "skipped": skipped, "notes": notes}
