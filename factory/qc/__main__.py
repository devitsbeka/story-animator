"""CLI: python -m factory.qc run --episode episodes/sentinel --video <mp4> --plates <dir>"""
from __future__ import annotations

import argparse
import sys

from .report import run, summary_text


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m factory.qc", description="Stage 9 automated QC: technical, loudness, pacing, captions, framing, vision hook")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run QC and write qc/report.json")
    r.add_argument("--episode", help="episode dir (newest episode_v<N>.json) or an episode json")
    r.add_argument("--spec", help="explicit episode json (overrides the --episode lookup)")
    r.add_argument("--video", help="final mp4")
    r.add_argument("--plates", help="rendered plates dir (<SHOT>/<frame>.png)")
    r.add_argument("--out", help="output dir (default <episode>/qc)")
    r.add_argument("--partial-plates", action="store_true", help="plates are a sample: incomplete coverage is a warning, not a failure")
    v = r.add_mutually_exclusive_group()
    v.add_argument("--vision", dest="vision", action="store_true", default=None, help="force the vision-model call")
    v.add_argument("--no-vision", dest="vision", action="store_false", help="never call the vision model (sheet + prompt are still written)")
    r.add_argument("--iteration", type=int, default=0, help="auto-fix iteration count (AUTO_FIX becomes RETURN at 2)")
    r.add_argument("--strict", action="store_true", help="exit 1 unless the decision is PUBLISH")
    a = ap.parse_args(argv)
    if not (a.episode or a.spec or a.video or a.plates):
        ap.error("give at least one of --episode/--spec, --video, --plates")
    rep = run(a.episode, a.spec, a.video, a.plates, a.out, a.vision, a.partial_plates, a.iteration)
    print(summary_text(rep))
    return 1 if a.strict and rep["decision"] != "PUBLISH" else 0


if __name__ == "__main__":
    sys.exit(main())
