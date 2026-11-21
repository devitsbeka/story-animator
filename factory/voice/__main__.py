"""CLI.

  python -m factory.voice synth  --story S --out DIR [--voice ID] [--model M] [--takes auto|1|2] [--offline]
  python -m factory.voice plan   --story S                       # MCP calls to make (agent route)
  python -m factory.voice import --story S --out DIR --take [CHUNK=]AUDIO[:TRANSCRIPT] [--take ...]
"""
import argparse
import json
import sys

from .backends import ImportBackend, PlaceholderBackend, RestBackend
from .stage import mcp_plan, synthesize


def _takes(specs):
    chunks = {}
    for spec in specs:
        ci, rest = (spec.split("=", 1) if "=" in spec else ("0", spec))
        aud, _, tr = rest.partition(":")
        chunks.setdefault(int(ci), []).append({"audio": aud, "transcript": tr or None})
    return [chunks[k] for k in sorted(chunks)]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m factory.voice")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("synth", "plan", "import"):
        p = sub.add_parser(name)
        p.add_argument("--story", required=True)
        p.add_argument("--voice")
        p.add_argument("--model")
        p.add_argument("--format", dest="fmt")
        p.add_argument("--max-chars", type=int, default=2500)
        if name != "plan":
            p.add_argument("--out", required=True)
            p.add_argument("--takes", default="auto")
            p.add_argument("--no-normalize", action="store_true")
            p.add_argument("--no-tempo-fix", action="store_true")
            p.add_argument("--cache-dir")
            p.add_argument("--basename", default="narration")
        if name == "synth":
            p.add_argument("--offline", action="store_true", help="placeholder tones, no credits")
        if name == "import":
            p.add_argument("--take", action="append", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "plan":
        print(json.dumps(mcp_plan(a.story, a.voice, a.model, a.max_chars, a.fmt), indent=1))
        return 0
    if a.cmd == "import":
        backend = ImportBackend(_takes(a.take))
    else:
        backend = PlaceholderBackend() if a.offline else RestBackend()
    res = synthesize(a.story, a.out, voice=a.voice, model=a.model, backend=backend, takes=a.takes,
                     cache_dir=a.cache_dir, fmt=a.fmt, normalize=not a.no_normalize,
                     tempo_fix=not a.no_tempo_fix, max_chars=a.max_chars, basename=a.basename,
                     log=lambda m: print(m, file=sys.stderr))
    with open(res["report"]) as fh:
        rep = json.load(fh)
    print(json.dumps({**res, "pacing": rep["pacing"], "loudness": rep["loudness"],
                      "timing_sources": rep["timing_sources"], "clipping": rep["clipping"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
