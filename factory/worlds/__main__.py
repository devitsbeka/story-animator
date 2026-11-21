"""python -m factory.worlds list
python -m factory.worlds validate [kit ...]
python -m factory.worlds layout <kit> [--seed N] [--json]
python -m factory.worlds propose --manifest episodes/<id>/manifest.json [--write]   (librarian kit proposals -> kits/)"""
import argparse
import json
import os
import sys

from . import kits, layout


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m factory.worlds")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    v = sub.add_parser("validate")
    v.add_argument("ids", nargs="*")
    lo = sub.add_parser("layout")
    lo.add_argument("kit")
    lo.add_argument("--seed", type=int, default=None)
    lo.add_argument("--json", action="store_true")
    pr = sub.add_parser("propose")
    pr.add_argument("--manifest", required=True)
    pr.add_argument("--write", action="store_true", help="write valid proposals to factory/worlds/kits/<id>.json")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        for k in kits.kit_ids():
            kit = kits.load(k)
            print(f"{k:24s} {kit['sky']['time_of_day']:6s} {kit['lighting']['preset']:24s} marks={sorted(kit['marks'])} {'(legacy)' if kit.get('legacy') else ''}")
        return 0
    if a.cmd == "validate":
        bad = 0
        for k in a.ids or kits.kit_ids():
            errs = kits.validate(kits.load(k))
            bad += bool(errs)
            print(f"{k:24s} {'OK' if not errs else 'FAIL'}")
            for e in errs:
                print("   ", e)
        return 1 if bad else 0
    if a.cmd == "layout":
        plan = layout.layout(kits.load(a.kit), a.seed)
        print(json.dumps(plan if a.json else layout.summary(plan), indent=1))
        return 0
    man = json.load(open(a.manifest))
    n = 0
    for e in man["entries"]:
        p = e.get("kit_proposal")
        if not p:
            continue
        kid = p["kit"]["id"]
        print(f"{e['element']} -> kit {kid}: {'valid' if not p['errors'] else str(len(p['errors'])) + ' errors'}")
        for x in p["errors"] + p["notes"]:
            print("   ", x)
        if a.write and not p["errors"]:
            path = os.path.join(kits.KITS_DIR, f"{kid}.json")
            if os.path.exists(path):
                print(f"    {path} exists; not overwritten")
                continue
            with open(path, "w") as fh:
                json.dump(p["kit"], fh, indent=1)
                fh.write("\n")
            print(f"    wrote {path}")
            n += 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
