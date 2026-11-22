"""python -m factory.goldens render|compare|approve|status|affected

  render  [--only a,b]                         render candidates into the store (no comparison; for a first baseline)
  compare [--only a,b | --changed-from REF] [--no-vision] [--auto-approve-better --note N]
                                               render + compare against the approved references; FAIL (exit 1) if any
                                               golden degrades beyond its thresholds; writes a side-by-side diff sheet
  approve (--only a,b | --all) --note "why"   [--accept-worse]   promote the latest candidates to references,
                                               update baseline.json and CHANGELOG.md (explicit; never automatic for 'worse')
  status                                       baseline / staleness per golden
  affected --changed-from REF | --files f1,f2  which goldens a change touches (input globs + recipe changes)
"""
from __future__ import annotations

import argparse
import json
import sys

from . import gate
from . import manifest as M


def affected_from(ref, root=M.ROOT):
    files = gate.changed_files(ref, root)
    ids = set(M.affected(files, root))
    # recipes edited in manifest.json (a changed recipe affects only that golden)
    if "factory/goldens/manifest.json" in files:
        old = gate._git(root, "show", f"{gate._git(root, 'merge-base', ref, 'HEAD') or ref}:factory/goldens/manifest.json")
        cur = M.load(root)["goldens"]
        try:
            prev = json.loads(old)["goldens"] if old else {}
        except ValueError:
            prev = {}
        for gid, g in cur.items():
            p = prev.get(gid)
            if p is None or any(p.get(k) != g.get(k) for k in p.keys() | (g.keys() - {"id", "globs"} - set(M.load(root)["defaults"]))):
                ids.add(gid)
    return sorted(ids), files


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m factory.goldens", description="golden-frame visual regression")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("--only")
    c = sub.add_parser("compare")
    c.add_argument("--only")
    c.add_argument("--changed-from", help="compare only the goldens affected by changes since this git ref")
    c.add_argument("--no-vision", action="store_true")
    c.add_argument("--auto-approve-better", action="store_true", help="approve goldens the vision review judged 'better' (never 'worse')")
    c.add_argument("--note")
    c.add_argument("--json", action="store_true")
    a = sub.add_parser("approve")
    a.add_argument("--only")
    a.add_argument("--all", action="store_true")
    a.add_argument("--note", required=True)
    a.add_argument("--accept-worse", action="store_true", help="a human overrides a 'worse' vision verdict (recorded)")
    sub.add_parser("status")
    st = sub.add_parser("stress", help="scenario stress suite: shot checks + pose QC + stress goldens (+ vision)")
    st.add_argument("--only")
    st.add_argument("--no-render", action="store_true")
    st.add_argument("--no-pose", action="store_true")
    st.add_argument("--vision", action="store_true")
    st.add_argument("--update-known", action="store_true", help="record today's failures as known (needs --note)")
    st.add_argument("--note")
    af = sub.add_parser("affected")
    af.add_argument("--changed-from")
    af.add_argument("--files")
    args = ap.parse_args(argv)
    m = M.load()
    only = args.only.split(",") if getattr(args, "only", None) else None

    if args.cmd == "render":
        for x in gate.render_only(only):
            print(f"rendered {x['id']}: {x['candidate']}")
        return 0
    if args.cmd == "compare":
        if args.changed_from:
            only, files = affected_from(args.changed_from)
            print(f"{len(files)} changed file(s) since {args.changed_from} -> goldens: {only or 'none'}")
            if not only:
                print("GOLDENS PASS (no golden affected)")
                return 0
        res = gate.run_compare(only, use_vision=not args.no_vision)
        if args.auto_approve_better:
            better = [r["id"] for r in res["results"] if r["status"] == gate.FAIL and (r.get("verdict") or {}).get("verdict") == "better"]
            if better:
                gate.approve(better, args.note or "auto-approved: vision review judged better", accept_worse=False)
                print(f"auto-approved (vision: better): {better}")
                for rr in res["results"]:
                    if rr["id"] in better:
                        rr["status"] = gate.PASS
                res["ok"] = all(rr["status"] == gate.PASS for rr in res["results"])
        if args.json:
            print(json.dumps(res, indent=1, default=str))
        for rr in res["results"]:
            v = (rr.get("verdict") or {}).get("verdict")
            mm = rr.get("metrics") or {}
            print(f"[{rr['status'].upper():12}] {rr['id']:26} ssim={mm.get('ssim')} tile={mm.get('tile_ssim')} dRGB={mm.get('rgb_delta')} "
                  f"dY={mm.get('luma_delta')} dEdge={mm.get('edge_delta')}" + (f" vision={v}" if v else "")
                  + (f"  <- {'; '.join(rr['reasons'])}" if rr.get("reasons") else ""))
        print(f"diff sheet: {res['diff_sheet']}")
        print("GOLDENS " + ("PASS" if res["ok"] else "FAIL"))
        return 0 if res["ok"] else 1
    if args.cmd == "approve":
        ids = sorted(m["goldens"]) if args.all else only
        if not ids:
            ap.error("give --only a,b or --all")
        try:
            done = gate.approve(ids, args.note, accept_worse=args.accept_worse)
        except gate.ApprovalRefused as e:
            print(f"REFUSED: {e}")
            return 1
        print(f"approved {done}; baseline.json and CHANGELOG.md updated (commit them)")
        return 0
    if args.cmd == "status":
        base = M.load_baseline()["goldens"]
        st = gate.staleness()
        for gid in sorted(m["goldens"]):
            b = base.get(gid)
            s = "stale" if gid in st["stale"] else ("UNBASELINED" if gid in st["unbaselined"] else "fresh")
            print(f"{gid:26} {s:12} " + (f"approved {b['approved_at']} sha {b['sha256'][:10]} luma {b['stats']['mean_luma']}" if b else ""))
        return 0
    if args.cmd == "stress":
        from .stress import run as srun
        rep = srun.run(only, render=not args.no_render, pose=not args.no_pose, vision=args.vision)
        print(srun.summary_text(rep))
        if args.update_known:
            if not args.note:
                ap.error("--update-known needs --note")
            srun.update_known(rep, args.note)
            print(f"known_failures.json updated ({len(rep['regressions'])} newly recorded)")
            return 0
        return 0 if rep["ok"] else 1
    if args.cmd == "affected":
        if args.files:
            print("\n".join(M.affected(args.files.split(","))))
        else:
            ids, _ = affected_from(args.changed_from or "HEAD")
            print("\n".join(ids))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
