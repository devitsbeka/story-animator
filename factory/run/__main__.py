"""python -m factory.run "idea" --format short|docuseries --style pixar_night_survival --render local|farm
                     --quality preview|final [--offline] [--resume] [--episode-id X] [--auto-approve] ...
python -m factory.run batch ideas.txt --max-parallel N --budget USD [same options]
python -m factory.run approve --episode-id X [--reject] [--note "..."]
python -m factory.run status --episode-id X

Exit codes: 0 published, 3 awaiting approval, 4 returned by QC, 5 budget exceeded, 1 failed, 2 usage error."""
import argparse
import json
import os
import sys

from .pipeline import DEFAULT_EPISODES, ORDER, STUBBABLE, Options, Pipeline
from .state import RunState

EXIT = {"published": 0, "done": 0, "awaiting_approval": 3, "returned": 4, "budget_exceeded": 5, "failed": 1, "running": 1}


def common(ap, defaults=True):
    d = (lambda v: v) if defaults else (lambda v: None)
    ap.add_argument("--format", choices=["short", "docuseries"], default=d("short"))
    ap.add_argument("--style", default=d("pixar_night_survival"))
    ap.add_argument("--render", choices=["local", "farm", "compute"], default=d("local"))
    ap.add_argument("--quality", choices=["preview", "final"], default=d("preview"))
    ap.add_argument("--offline", action="store_true", default=None, help="replay recorded LLM responses, stub/reference voice, no vision model")
    ap.add_argument("--stub", default=None, help=f"comma list of heavy steps to stub: {','.join(sorted(STUBBABLE))} (or 'all')")
    ap.add_argument("--auto-approve", action="store_true", default=None, help="skip the human approval gate after previs")
    ap.add_argument("--episodes-dir", default=None, help=f"default {DEFAULT_EPISODES}")
    ap.add_argument("--fixtures", default=None, help="director fixture dir for --offline")
    ap.add_argument("--voice", choices=["auto", "stub", "module"], default=None)
    ap.add_argument("--workers", type=int, default=None, help="local render / previs processes")
    ap.add_argument("--render-res", default=None, help="override plate resolution WxH (local render)")
    ap.add_argument("--render-samples", type=int, default=None)
    ap.add_argument("--render-engine", choices=["CYCLES", "EEVEE"], default=None)
    ap.add_argument("--blender", default=None, help="blender command (default $BLENDER or /opt/blender/...)")
    ap.add_argument("--previs-res", default=None)
    ap.add_argument("--previs-samples", type=int, default=None)
    ap.add_argument("--previs-shots", default=None, help="comma list: only these shots get previs keyframes")
    ap.add_argument("--budget", type=float, default=None, help="USD ceiling for this episode (batch: for all)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--effort", default=None, choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--parallel-stages", type=int, default=None)
    ap.add_argument("--shot-gate-pose", choices=["enforce", "warn", "off"], default=None,
                    help="Blender pose QC in the per-shot gate before previs/render (default warn: recorded + logged)")
    ap.add_argument("--regress", choices=["enforce", "warn", "off"], default=None, help="lessons/goldens regress check at previs + publish (quality_gate)")
    ap.add_argument("--no-deliver", dest="deliver", action="store_false", default=None, help="skip the delivery copies at publish (L006)")


def options_from(a, base=None):
    o = base or Options()
    m = {"format": "fmt"}
    for k in ("format", "style", "render", "quality", "offline", "auto_approve", "episodes_dir", "fixtures", "voice", "workers",
              "render_res", "render_samples", "render_engine", "blender", "previs_res", "previs_samples", "budget", "model",
              "effort", "parallel_stages", "regress", "deliver", "shot_gate_pose"):
        v = getattr(a, k, None)
        if v is not None:
            setattr(o, m.get(k, k), v)
    if getattr(a, "stub", None) is not None:
        o.stubs = frozenset(STUBBABLE if a.stub == "all" else (s.strip() for s in a.stub.split(",") if s.strip()))
        bad = o.stubs - STUBBABLE
        if bad:
            raise SystemExit(f"unknown --stub {sorted(bad)}; choose from {sorted(STUBBABLE)}")
    if getattr(a, "previs_shots", None):
        o.previs_shots = tuple(s.strip() for s in a.previs_shots.split(",") if s.strip())
    return o


def run_main(argv):
    ap = argparse.ArgumentParser(prog="python -m factory.run", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("idea", nargs="?", default=None)
    ap.add_argument("--episode-id", default=None)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--fresh", action="store_true", help="discard run.json and regenerate every artifact")
    ap.add_argument("--from-stage", choices=ORDER, default=None, help="re-run this stage and everything after it")
    common(ap, defaults=False)
    a = ap.parse_args(argv)
    eps = a.episodes_dir or DEFAULT_EPISODES
    base = None
    if a.resume:
        if not a.episode_id:
            ap.error("--resume needs --episode-id")
        rj = os.path.join(eps, a.episode_id, "run.json")
        if not os.path.exists(rj):
            if not a.idea:
                ap.error(f"nothing to resume: {rj} does not exist")
        else:
            base = Options.from_dict(RunState.load(rj).doc.get("options") or {})
    elif not a.idea:
        ap.error("give an idea (or --resume --episode-id X)")
    o = options_from(a, base)
    if a.idea:
        o.idea = a.idea
    o.episodes_dir = eps
    try:
        pipe = Pipeline(o, a.episode_id, resume=a.resume, fresh=a.fresh, from_stage=a.from_stage)
    except (FileExistsError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    doc = pipe.run()
    print(summary(doc))
    return EXIT.get(doc["status"], 1)


def summary(doc):
    lines = [f"episode {doc['episodeId']}: {doc['status']}  cost ${doc['cost']['totalUSD']:.3f}  time {doc['time']['totalSeconds']:.0f}s"]
    for n in ORDER:
        s = doc["stages"].get(n, {})
        lines.append(f"  {n:<9} {s.get('status', '-'):<18} {float(s.get('seconds') or 0):7.1f}s  ${float(s.get('costUSD') or 0):.3f}"
                     + (f"  {s['error'][:120]}" if s.get("error") else ""))
    q = doc.get("qc") or {}
    if q.get("decision"):
        lines.append(f"  QC decision {q['decision']} after {len(q.get('iterations', []))} iteration(s): {q.get('report')}")
    return "\n".join(lines)


def approve_main(argv):
    ap = argparse.ArgumentParser(prog="python -m factory.run approve")
    ap.add_argument("--episode-id", required=True)
    ap.add_argument("--episodes-dir", default=DEFAULT_EPISODES)
    ap.add_argument("--reject", action="store_true")
    ap.add_argument("--note", default=None)
    ap.add_argument("--by", default=os.environ.get("USER", "operator"))
    a = ap.parse_args(argv)
    rj = os.path.join(a.episodes_dir, a.episode_id, "run.json")
    st = RunState.load(rj)
    st.doc["approval"] = {"approved": not a.reject, "by": a.by, "note": a.note,
                          "at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S")}
    st.event(f"previs {'rejected' if a.reject else 'approved'} by {a.by}" + (f": {a.note}" if a.note else ""))
    print(f"{a.episode_id}: previs {'REJECTED' if a.reject else 'APPROVED'}; continue with "
          f"`python -m factory.run --resume --episode-id {a.episode_id}`"
          + (" --from-stage direct" if a.reject else ""))
    return 0


def status_main(argv):
    ap = argparse.ArgumentParser(prog="python -m factory.run status")
    ap.add_argument("--episode-id", required=True)
    ap.add_argument("--episodes-dir", default=DEFAULT_EPISODES)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    doc = RunState.load(os.path.join(a.episodes_dir, a.episode_id, "run.json")).doc
    print(json.dumps(doc, indent=1) if a.json else summary(doc))
    return 0


def batch_main(argv):
    from . import batch
    ap = argparse.ArgumentParser(prog="python -m factory.run batch")
    ap.add_argument("ideas", help="text file, one idea per line (optional 'short|' / 'docuseries|' prefix)")
    ap.add_argument("--max-parallel", type=int, default=2)
    ap.add_argument("--overrun", type=float, default=1.5, help="per-idea allowance = estimate x overrun")
    common(ap, defaults=True)
    a, rest = ap.parse_known_args(argv)
    eps = a.episodes_dir or DEFAULT_EPISODES
    child = ["--style", a.style, "--render", a.render, "--quality", a.quality]
    for flag, v in (("--offline", a.offline), ("--auto-approve", a.auto_approve)):
        if v:
            child.append(flag)
    for flag, v in (("--stub", a.stub), ("--fixtures", a.fixtures), ("--voice", a.voice), ("--workers", a.workers),
                    ("--render-res", a.render_res), ("--render-samples", a.render_samples), ("--render-engine", a.render_engine),
                    ("--blender", a.blender), ("--previs-res", a.previs_res), ("--previs-samples", a.previs_samples),
                    ("--previs-shots", a.previs_shots), ("--model", a.model), ("--effort", a.effort)):
        if v is not None:
            child += [flag, str(v)]
    doc = batch.run_batch(batch.read_ideas(a.ideas), child + rest, eps, a.format, a.render, a.quality, bool(a.offline),
                          a.max_parallel, a.budget, a.overrun)
    for it in doc["items"]:
        print(f"{it['episodeId']:<52} {it['status']:<18} ${it.get('spentUSD', 0):.2f}  est ${it['estimate']:.2f}")
    print(f"batch report: {doc['file']}")
    return 0 if all(it["status"] in ("published", "awaiting_approval", "returned") for it in doc["items"]) else 1


def load_secrets(path=None):
    """Fill missing API keys from the secrets file (~/.factory_secrets.env, lines `export NAME=value`). Values are
    never printed or logged; variables already set in the environment win."""
    path = path or os.environ.get("FACTORY_SECRETS", os.path.expanduser("~/.factory_secrets.env"))
    if not os.path.isfile(path):
        return []
    got = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:]
            k, sep, v = line.partition("=")
            k, v = k.strip(), v.strip().strip("'\"")
            if sep and k.isidentifier() and v and not os.environ.get(k):
                os.environ[k] = v
                got.append(k)
    return got


def main(argv=None):
    load_secrets()
    argv = list(sys.argv[1:] if argv is None else argv)
    sub = {"batch": batch_main, "approve": approve_main, "status": status_main}
    if argv and argv[0] in sub:
        return sub[argv[0]](argv[1:])
    return run_main(argv)


if __name__ == "__main__":
    sys.exit(main())
