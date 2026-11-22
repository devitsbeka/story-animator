"""
python -m factory.compute - the multi-provider compute broker (free capacity first).

    python -m factory.compute plan   --spec EP.json --quality preview --frames 0-23 --deadline-min 30 --budget 0
    python -m factory.compute run    --spec EP.json --quality preview --frames 0-23 --res 270x480 --samples 12 \\
                                     --providers aws_lambda,local_cpu --deadline-min 30 --budget 0 [--allow-paid] \\
                                     [--pull DIR]
    python -m factory.compute status [--run RUN]
    python -m factory.compute ledger
    python -m factory.compute invite --name alice [--days 7]      member nodes (docs/member_nodes.md)
    python -m factory.compute revoke --node n-xxxx
    python -m factory.compute nodes

Use the operator's ~/.aws default profile (not the session env keys):
    env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN python -m factory.compute ...
"""
import argparse
import json
import sys

from . import registry as reg


def parse_frames(s):
    if not s:
        return None
    a, b = s.split("-")
    return int(a), int(b)


def out(o):
    print(json.dumps(o, indent=1, default=str))


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m factory.compute", description=__doc__.split("\n\n")[0])
    p.add_argument("cmd", choices=["plan", "run", "status", "ledger", "invite", "revoke", "nodes", "providers"])
    p.add_argument("--spec")
    p.add_argument("--quality", choices=["preview", "final"], default="preview")
    p.add_argument("--frames", help="A-B inclusive film frames")
    p.add_argument("--res", default=None, help="WxH override, e.g. 270x480")
    p.add_argument("--samples", type=int, default=None)
    p.add_argument("--deadline-min", type=float, default=None)
    p.add_argument("--budget", type=float, default=0.0, help="USD for paid overflow (0 = free only)")
    p.add_argument("--allow-paid", action="store_true")
    p.add_argument("--providers", default=None, help="comma list (default: every schedulable provider)")
    p.add_argument("--allow-care", default="", help="comma list of USE-WITH-CARE providers to enable")
    p.add_argument("--run", default=None)
    p.add_argument("--code", choices=["head", "worktree"], default="head")
    p.add_argument("--library", choices=["auto", "spec", "none"], default="auto")
    p.add_argument("--pull", default=None, help="download the frames here when complete")
    p.add_argument("--interval", type=float, default=10.0)
    p.add_argument("--max-wall-min", type=float, default=None)
    p.add_argument("--name"), p.add_argument("--days", type=float, default=7.0), p.add_argument("--node")
    p.add_argument("--region", default="us-east-1")
    a = p.parse_args(argv)
    providers = [x for x in (a.providers or "").split(",") if x] or None
    care = [x for x in a.allow_care.split(",") if x]
    if a.cmd == "providers":
        cfg = reg.load(providers=providers, allow_care=care)
        out({"schedulable": sorted(cfg["providers"]), "gated": cfg["gated"],
             "unknownAdapters": cfg["unknownAdapters"]})
        return 0
    from .broker import Broker
    b = Broker.from_env(providers=providers, allow_care=care, region=a.region)
    if a.cmd == "plan":
        out(b.plan_job(a.spec, a.quality, parse_frames(a.frames), a.res, a.samples, a.deadline_min, a.budget,
                       a.allow_paid))
    elif a.cmd == "run":
        if a.run:
            st = b.load(a.run)
        else:
            st = b.submit(a.spec, a.quality, parse_frames(a.frames), a.res, a.samples, a.deadline_min, a.budget,
                          a.allow_paid, code_mode=a.code, library=a.library)
        print(json.dumps({"runId": st["runId"], "plan": st["plan"]}, default=str), file=sys.stderr, flush=True)

        def progress(s):
            pr = s.get("progress") or {}
            print(json.dumps({"run": s["runId"], "status": s["status"], "framesDone": pr.get("framesDone"),
                              "frames": pr.get("frames"), "leased": pr.get("framesLeased"),
                              "running": sum(1 for t in s["tasks"].values() if t["status"] == "running"),
                              "expectedMin": (s.get("livePlan") or {}).get("expectedMin")}), file=sys.stderr,
                  flush=True)
        st = b.run_until_done(st, interval=a.interval, max_s=a.max_wall_min * 60 if a.max_wall_min else None,
                              on_tick=progress)
        res = b.summary(st)
        if a.pull and st["status"] == "COMPLETE":
            res["pulled"] = b.pull(st, a.pull)
        out(res)
        return 0 if st["status"] == "COMPLETE" else 1
    elif a.cmd == "status":
        if a.run:
            out(b.summary(b.load(a.run)))
        else:
            runs = sorted({k.split("/")[2] for k in b.store.list("compute/runs/") if k.endswith("/broker.json")})
            out({"runs": runs})
    elif a.cmd == "ledger":
        meters = b.observe_meters()
        quotas = {pid: q for pid in b.config["providers"] if (q := b.quota(pid)) and q.get("free") is not None}
        out({"ledger": b.ledger.report(quotas), "meters": meters})
    elif a.cmd == "invite":
        out(b.members.invite(a.name or "member", a.days))
    elif a.cmd == "revoke":
        out(b.members.revoke(a.node))
    elif a.cmd == "nodes":
        out([{"node": n["node"], "name": (n["record"] or {}).get("name"), "live": b.members.live(n),
              "revoked": (n["record"] or {}).get("revoked"), "caps": (n["hello"] or {}).get("caps"),
              "limits": (n["hello"] or {}).get("limits"), "heartbeat": n["heartbeat"],
              "accepted": (n["record"] or {}).get("accepted"), "verified": (n["record"] or {}).get("verified")}
             for n in b.members.nodes()])
    return 0


if __name__ == "__main__":
    sys.exit(main())
