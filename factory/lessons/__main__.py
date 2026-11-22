"""python -m factory.lessons add|list|status|check|close|inject-briefs

  add --symptom S --root-cause R --rule X --gate direct,qc [--check C] [--found WHO]   append a new open lesson
  list [--gate G] [--open]                                                           print the ledger
  status [--json]                    which lessons have a working (implemented) check, which are open
  check [--slow] [--only L006,L008]  run the lesson checks (exit 1 on any failure / missing check)
  close L006 [--status closed|partially-closed] [--check TEXT]   mark a lesson after its check runs in a gate
  inject-briefs [--check]            write the LESSONS block into the common agent brief templates
"""
from __future__ import annotations

import argparse
import json
import sys

from . import GATES, STATUSES, add_lesson, inject_briefs, lessons_block, load_lessons, set_status


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m factory.lessons", description="lessons ledger: defect -> rule -> check -> gate")
    ap.add_argument("--ledger", help="ledger path (default factory/lessons/lessons.yaml or $FACTORY_LESSONS)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="append a new lesson (next id, status open)")
    a.add_argument("--symptom", required=True)
    a.add_argument("--root-cause", required=True)
    a.add_argument("--rule", required=True)
    a.add_argument("--gate", required=True, help=f"comma list of {','.join(GATES)}")
    a.add_argument("--check", default="TODO: automate")
    a.add_argument("--found")
    a.add_argument("--case", help="stress selector, e.g. 'stance=sit*,hands=radio|phone,size=close' (default: derived from the text)")
    a.add_argument("--no-case", action="store_true", help="do not attach a stress regression case (tests only)")
    ac = sub.add_parser("attach-case", help="attach a stress regression case to an existing lesson")
    ac.add_argument("id")
    ac.add_argument("--case")
    li = sub.add_parser("list")
    li.add_argument("--gate")
    li.add_argument("--open", action="store_true", help="only lessons that are not closed")
    li.add_argument("--block", action="store_true", help="print the LESSONS prompt block instead")
    st = sub.add_parser("status")
    st.add_argument("--json", action="store_true")
    ck = sub.add_parser("check")
    ck.add_argument("--slow", action="store_true", help="also run Blender / golden checks")
    ck.add_argument("--only", help="comma list of lesson ids")
    ck.add_argument("--episode")
    ck.add_argument("--json", action="store_true")
    cl = sub.add_parser("close")
    cl.add_argument("id")
    cl.add_argument("--status", default="closed", choices=STATUSES)
    cl.add_argument("--check")
    ib = sub.add_parser("inject-briefs")
    ib.add_argument("--check", action="store_true", help="exit 1 if any brief template is stale")
    args = ap.parse_args(argv)
    path = args.ledger

    if args.cmd == "add":
        lid = add_lesson(args.symptom, args.root_cause, args.rule, args.gate, args.check, args.found, path)
        if not args.no_case:
            from .cases import attach, parse_case
            ids = attach(lid, parse_case(args.case) if args.case else None, f"{args.symptom} {args.rule}", path)
            print(f"{lid}: regression_cases {ids} (stress scenarios in every world kit; render + approve them)")
        print(f"added {lid} (open). Next: implement its check, register it in factory/lessons/checks.py, then "
              f"`python -m factory.lessons close {lid}`")
        return 0
    if args.cmd == "attach-case":
        from . import get
        from .cases import attach, parse_case
        d = get(args.id, path)
        ids = attach(args.id, parse_case(args.case) if args.case else None, f"{d.get('symptom', '')} {d.get('rule', '')}", path)
        print(f"{args.id}: regression_cases {ids}")
        return 0
    if args.cmd == "list":
        if args.block:
            print(lessons_block(args.gate.split(",") if args.gate else None, path))
            return 0
        for d in load_lessons(path):
            if args.gate and args.gate not in d["gate"]:
                continue
            if args.open and d["status"] == "closed":
                continue
            print(f"{d['id']}  {d['status']:<16} gate={','.join(d['gate']):<22} {' '.join(str(d.get('rule', '')).split())[:110]}")
        return 0
    if args.cmd == "status":
        from .checks import status
        rows = status(path=path)
        if args.json:
            print(json.dumps(rows, indent=1))
            return 0
        print(f"{'id':5} {'ledger':16} {'check':12} checks")
        for r in rows:
            chk = "automated" if r["automated"] else ("partial" if any(c["implemented"] for c in r["checks"]) else "NONE")
            names = "; ".join(f"{c['kind']}:{c['name']}{'' if c['implemented'] else ' [MISSING]'}" for c in r["checks"]) or "-"
            print(f"{r['id']:5} {r['ledger']:16} {chk:12} {names[:150]}")
        op = [r["id"] for r in rows if r["open"]]
        print(f"open: {', '.join(op) or 'none'}  |  without a working check: {', '.join(r['id'] for r in rows if not r['automated']) or 'none'}")
        return 0
    if args.cmd == "check":
        from .checks import run_checks
        res = run_checks(include_slow=args.slow, only=set(args.only.split(",")) if args.only else None, episode=args.episode,
                         log=(lambda m: print(m, file=sys.stderr)) if args.json else print)   # --json: stdout is pure JSON
        if args.json:
            print(json.dumps(res, indent=1))
        else:
            for r in res["results"]:
                print(f"[{r['status'].upper():7}] {r['lesson']} {r['name']}" + (f"  ({r.get('why')})" if r.get("why") else ""))
                if r["status"] == "fail" and r.get("tail"):
                    print("    " + r["tail"].strip().replace("\n", "\n    ")[-1200:])
            print("LESSON CHECKS " + ("PASS" if res["ok"] else "FAIL"))
        return 0 if res["ok"] else 1
    if args.cmd == "close":
        set_status(args.id, args.status, args.check, path)
        print(f"{args.id} -> {args.status}")
        return 0
    if args.cmd == "inject-briefs":
        res = inject_briefs(check_only=args.check, path=path)
        for f, ch in res:
            print(f"{'STALE' if (ch and args.check) else ('updated' if ch else 'ok')}: {f}")
        return 1 if args.check and any(ch for _, ch in res) else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
