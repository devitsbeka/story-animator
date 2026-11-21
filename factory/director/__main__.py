"""python -m factory.director run --idea "..." --format short|docuseries --out episodes/<id> [--offline]
python -m factory.director validate --dir episodes/<id>"""
import argparse
import json
import os
import sys

from . import checks, librarian
from .llm import DEFAULT_MODEL, AnthropicClient, FixtureClient, LLMError
from .paths import FIXTURES
from .runner import STAGES, Runner, StageFailed, load_words


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m factory.director", description="Automated directing stages 1-4")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="idea -> story -> breakdown -> manifest -> episode.json")
    r.add_argument("--idea", required=True)
    r.add_argument("--format", choices=["short", "docuseries"], default="short")
    r.add_argument("--out", required=True, help="episode dir, e.g. episodes/<id>")
    r.add_argument("--offline", action="store_true", help="replay recorded responses instead of calling the API")
    r.add_argument("--fixtures", default=os.path.join(FIXTURES, "sentinel"), help="recorded responses dir (offline)")
    r.add_argument("--model", default=os.environ.get("DIRECTOR_MODEL", DEFAULT_MODEL))
    r.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    r.add_argument("--no-fallbacks", action="store_true", help="do not send the server-side refusal fallback")
    r.add_argument("--max-attempts", type=int, default=3)
    r.add_argument("--stages", default=",".join(STAGES), help=f"comma list from {STAGES}")
    r.add_argument("--words", default=None, help="narration word timings (stage 5) for the cut-on-word check")
    r.add_argument("--polyhaven", choices=["cache", "live"], default=None,
                   help="Poly Haven search: cache only (default offline) or live (default online)")
    r.add_argument("--record", action="store_true", help="live Poly Haven results are written back into the fixture cache")
    r.add_argument("--force", action="store_true", help="regenerate artifacts even if valid ones exist")
    v = sub.add_parser("validate", help="re-run every checklist on an episode dir")
    v.add_argument("--dir", required=True)
    a = ap.parse_args(argv)

    if a.cmd == "validate":
        return validate_dir(a.dir)

    stages = tuple(s.strip() for s in a.stages.split(",") if s.strip())
    bad = [s for s in stages if s not in STAGES]
    if bad:
        ap.error(f"unknown stages {bad}")
    if a.offline:
        client = FixtureClient(a.fixtures)
    else:
        try:
            client = AnthropicClient(a.model, a.effort, fallbacks=not a.no_fallbacks)
        except LLMError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    ph_mode = a.polyhaven or ("cache" if a.offline else "live")
    ph = librarian.PolyHavenSearch(os.path.join(a.fixtures, "polyhaven_search.json"), mode="live" if ph_mode == "live" else "offline",
                                   record=a.record)
    run = Runner(a.out, client, a.idea, a.format, ph=ph, max_attempts=a.max_attempts, words=load_words(a.out, a.words), force=a.force)
    try:
        run.run(stages)
    except (StageFailed, LLMError) as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    print("OK: " + ", ".join(f"{k} {'pass' if r.ok else 'FAIL'}" for k, r in run.reports.items()))
    return 0


def validate_dir(d):
    def rd(n):
        p = os.path.join(d, n)
        return json.load(open(p)) if os.path.exists(p) else None
    story, bd, man, plan, ep = (rd(n) for n in ("story.json", "breakdown.json", "manifest.json", "shotplan.json", "episode.json"))
    reps = {}
    if story:
        reps["story"] = checks.check_story(story)
    if story and bd:
        reps["breakdown"] = checks.check_breakdown(bd, story)
    if bd and man:
        reps["manifest"] = checks.check_manifest(man, bd, librarian.load_catalog())
    if story and bd and man and plan:
        reps["shotplan"] = checks.check_shotplan(plan, story, bd, man, load_words(d))
    if ep:
        reps["episode"] = checks.check_episode(ep)
    ok = True
    for k, r in reps.items():
        ok &= r.ok
        print(f"{k:10s} {'PASS' if r.ok else 'FAIL'}  passed {len(r.passed)}  blocking {len(r.blocking)}  overridden {sum(i['overridden'] for i in r.issues)}")
        for i in r.blocking[:10]:
            print(f"   [{i['severity']} {i['rule']}] {i['msg'][:200]}")
    return 0 if ok and reps else 1


if __name__ == "__main__":
    sys.exit(main())
