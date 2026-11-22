"""Golden regression logic: render -> compare (metrics + thresholds + vision verdict) -> diff sheet -> approve.

    compare_one(gid, cand_png)        metrics vs the approved reference, FAIL beyond the golden's thresholds
    run_compare(gids, ...)            render candidates (or take given ones), compare all, write results + diff sheet
    approve(gids, note, ...)          candidate -> reference; baseline.json + CHANGELOG.md (refuses a 'worse' verdict)
    staleness(root)                   goldens whose inputs changed since approval without a passing compare since
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import time

from . import manifest as M
from . import metrics

PASS, FAIL, NEW = "pass", "fail", "no_reference"


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _git(root, *a):
    try:
        p = subprocess.run(["git", "-C", root, *a], capture_output=True, text=True, timeout=60)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def write_result(gid, res, root=M.ROOT):
    p = M.result_path(gid, root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        json.dump(res, fh, indent=1, default=str)
    return p


def read_result(gid, root=M.ROOT):
    p = M.result_path(gid, root)
    if not os.path.exists(p):
        return None
    with open(p) as fh:
        return json.load(fh)


def compare_one(gid, cand_png, root=M.ROOT, manifest=None, baseline=None, vision_client=None, use_vision=True):
    m = manifest or M.load(root)
    g = m["goldens"][gid]
    base = (baseline or M.load_baseline(root))["goldens"].get(gid)
    ref = M.ref_path(gid, root, base["sha256"] if base else "none")
    res = {"id": gid, "candidate": cand_png, "reference": ref, "at": _now(), "thresholds": None, "verdict": None}
    if base is None or not os.path.exists(ref):
        res.update(status=NEW, reasons=["no approved reference (run `python -m factory.goldens approve`)" if base is None else
                                         f"reference missing from the store ({ref}); restore it or re-approve"])
        return res
    if M.sha256(ref) != base["sha256"]:
        res.update(status=FAIL, reasons=[f"stored reference {ref} does not match baseline.json sha256 (store corrupted or stale)"])
        return res
    c = metrics.compare(metrics.load(ref), metrics.load(cand_png), g.get("thresholds"))
    res.update(status=PASS if c["pass"] else FAIL, reasons=c["reasons"], metrics=c["metrics"], thresholds=c["thresholds"])
    if use_vision and not c["metrics"].get("identical"):
        from . import vision
        res["verdict"] = vision.judge(ref, cand_png, g.get("rubric", "overall visual quality"),
                                      {k: c["metrics"][k] for k in ("ssim", "tile_ssim", "rgb_delta", "luma_delta", "edge_delta")},
                                      client=vision_client)
    return res


def run_compare(gids=None, root=M.ROOT, candidates=None, out_dir=None, render_fn=None, vision_client=None, use_vision=True,
                log=print):
    """Render (unless `candidates` {gid: png} is given) and compare. -> {"ok", "results", "diff_sheet", "out_dir"}"""
    m = M.load(root)
    gids = list(gids) if gids is not None else sorted(m["goldens"])
    unknown = [g for g in gids if g not in m["goldens"]]
    if unknown:
        raise KeyError(f"unknown goldens {unknown}")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = out_dir or os.path.join(M.store_dir(root), "candidates", stamp)
    os.makedirs(out_dir, exist_ok=True)
    baseline = M.load_baseline(root)
    files = M.tracked_files(root)
    results, rows = [], []
    for gid in gids:
        if candidates and gid in candidates:
            cand = candidates[gid]
        else:
            cand = os.path.join(out_dir, f"{gid}.png")
            try:
                (render_fn or _render)(gid, cand, root, log)
            except Exception as e:  # noqa: BLE001 - a golden that cannot render is a failure, not a crash
                r = {"id": gid, "status": FAIL, "reasons": [f"render failed: {e}"], "at": _now(), "candidate": None}
                results.append(r)
                write_result(gid, dict(r, inputs_hash=M.inputs_hash(m["goldens"][gid], root, files)), root)
                rows.append((gid, None, None, FAIL))
                continue
        r = compare_one(gid, cand, root, m, baseline, vision_client, use_vision)
        r["inputs_hash"] = M.inputs_hash(m["goldens"][gid], root, files)
        r["commit"] = _git(root, "rev-parse", "HEAD")
        write_result(gid, r, root)
        results.append(r)
        ref = M.ref_path(gid, root)
        rows.append((gid, metrics.load(ref) if os.path.exists(ref) else None, metrics.load(cand), r["status"]))
        log(f"[goldens] {gid}: {r['status'].upper()}" + (f" ({'; '.join(r['reasons'])})" if r.get("reasons") else "")
            + (f" vision={r['verdict']['verdict']}" if r.get("verdict") else ""))
    sheet = None
    shown = [x for x in rows if x[1] is not None or x[2] is not None]
    if shown:
        sheet = metrics.diff_sheet(shown, os.path.join(out_dir, "diff_sheet.png"))
    ok = all(r["status"] == PASS for r in results)
    summary = {"ok": ok, "results": results, "diff_sheet": sheet, "out_dir": out_dir, "at": _now()}
    with open(os.path.join(out_dir, "compare.json"), "w") as fh:
        json.dump(summary, fh, indent=1, default=str)
    return summary


def _render(gid, out_png, root, log):
    from .render import render_golden
    try:
        return render_golden(gid, out_png, root, log)
    except RuntimeError as e:
        if "rc=-9" not in str(e):        # -9: OOM-killed by the shared memory cgroup (or timeout): retry once
            raise
        log(f"[goldens] {gid}: killed (rc=-9, memory pressure?) - retrying once")
        time.sleep(20)
        return render_golden(gid, out_png, root, log)


def render_only(gids=None, root=M.ROOT, out_dir=None, render_fn=None, log=print):
    """Render candidates and record them (status 'rendered') so `approve` can promote them."""
    m = M.load(root)
    gids = list(gids) if gids is not None else sorted(m["goldens"])
    out_dir = out_dir or os.path.join(M.store_dir(root), "candidates", datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)
    files = M.tracked_files(root)
    out = []
    for gid in gids:
        cand = os.path.join(out_dir, f"{gid}.png")
        (render_fn or _render)(gid, cand, root, log)
        r = {"id": gid, "status": "rendered", "candidate": cand, "at": _now(), "inputs_hash": M.inputs_hash(m["goldens"][gid], root, files),
             "commit": _git(root, "rev-parse", "HEAD"), "stats": metrics.stats(metrics.load(cand))}
        write_result(gid, r, root)
        out.append(r)
    return out


class ApprovalRefused(RuntimeError):
    pass


def approve(gids, note, root=M.ROOT, accept_worse=False, by=None, changelog=True):
    """Promote each golden's latest candidate to the reference. Refuses without a note, without a candidate, or when
    the vision review judged it 'worse' (unless accept_worse, which is recorded)."""
    if not (note or "").strip():
        raise ApprovalRefused("approve needs --note (why this change is an intended improvement)")
    m = M.load(root)
    base = M.load_baseline(root)
    files = M.tracked_files(root)
    done = []
    for gid in gids:
        if gid not in m["goldens"]:
            raise KeyError(gid)
        r = read_result(gid, root)
        if not r or not r.get("candidate") or not os.path.exists(r["candidate"]):
            raise ApprovalRefused(f"{gid}: no rendered candidate (run `python -m factory.goldens compare --only {gid}` first)")
        cur = M.inputs_hash(m["goldens"][gid], root, files)
        if r.get("inputs_hash") != cur:
            raise ApprovalRefused(f"{gid}: the candidate was rendered from different inputs than the working tree; re-run compare")
        v = (r.get("verdict") or {}).get("verdict")
        if v == "worse" and not accept_worse:
            raise ApprovalRefused(f"{gid}: vision review judged the candidate WORSE ({(r.get('verdict') or {}).get('reason', '')[:200]}); "
                                  "fix it, or pass --accept-worse with a note if a human disagrees")
        sha = M.sha256(r["candidate"])
        ref = M.ref_path(gid, root, sha)       # content-addressed: branches and main never overwrite each other's refs
        os.makedirs(os.path.dirname(ref), exist_ok=True)
        prev = base["goldens"].get(gid)
        shutil.copyfile(r["candidate"], ref)
        entry = {"sha256": sha, "stats": metrics.stats(metrics.load(ref)), "inputs_hash": cur, "approved_at": _now(),
                 "commit": _git(root, "rev-parse", "HEAD"), "note": note, "by": by or os.environ.get("USER", "operator"),
                 "vision": v, "metrics_vs_previous": r.get("metrics") and {k: r["metrics"].get(k) for k in ("ssim", "tile_ssim", "rgb_delta", "luma_delta", "edge_delta")},
                 "accepted_worse": bool(v == "worse")}
        base["goldens"][gid] = entry
        done.append((gid, prev, entry))
    M.save_baseline(base, root)
    if changelog and done:
        _changelog(done, note, root)
    for gid, _, _ in done:
        r = read_result(gid, root)
        r["status"] = PASS
        r["approved"] = True
        write_result(gid, r, root)
    return [d[0] for d in done]


def _changelog(done, note, root):
    p = os.path.join(root, "factory", "goldens", "CHANGELOG.md")
    lines = [f"\n## {datetime.date.today().isoformat()} - {', '.join(g for g, _, _ in done)}\n", f"{note.strip()}\n"]
    for gid, prev, e in done:
        mv = e.get("metrics_vs_previous") or {}
        lines.append(f"- `{gid}`: {'re-approved' if prev else 'initial reference'} sha256 {e['sha256'][:12]}"
                     + (f", vs previous ssim {mv.get('ssim')} luma d {mv.get('luma_delta')}" if prev and mv else "")
                     + (f", vision: {e['vision']}" if e.get("vision") else "") + (" (ACCEPTED DESPITE 'worse')" if e.get("accepted_worse") else "")
                     + f", commit {str(e.get('commit'))[:10]}\n")
    with open(p, "a") as fh:
        fh.writelines(lines)


def staleness(root=M.ROOT):
    """-> {"stale": [ids], "unbaselined": [ids], "fresh": [ids]}: stale = inputs changed since approval and no passing
    compare recorded for the current inputs."""
    m = M.load(root)
    base = M.load_baseline(root)["goldens"]
    files = M.tracked_files(root)
    out = {"stale": [], "unbaselined": [], "fresh": []}
    for gid, g in sorted(m["goldens"].items()):
        b = base.get(gid)
        if not b:
            out["unbaselined"].append(gid)
            continue
        cur = M.inputs_hash(g, root, files)
        if cur == b.get("inputs_hash"):
            out["fresh"].append(gid)
            continue
        r = read_result(gid, root)
        (out["fresh"] if r and r.get("inputs_hash") == cur and r.get("status") == PASS else out["stale"]).append(gid)
    return out


def changed_files(base_ref, root=M.ROOT):
    """Files changed on this branch since it forked from base_ref (committed + working tree)."""
    mb = _git(root, "merge-base", base_ref, "HEAD") or base_ref
    a = (_git(root, "diff", "--name-only", f"{mb}..HEAD") or "").split()
    b = (_git(root, "diff", "--name-only", "HEAD") or "").split()
    c = (_git(root, "ls-files", "-o", "--exclude-standard") or "").split()
    return sorted(set(a + b + c))
