"""CLI for the style system.

  python -m factory.styles list
  python -m factory.styles show pixar_night_survival [--resolved] [--prompt]
  python -m factory.styles apply --episode episodes/sentinel/episode_v4.json --style documentary_naturalistic --out /tmp/ep.json
  python -m factory.styles check /tmp/ep.json
"""
import argparse
import json
import os
import sys

from . import apply_style_to_episode, check_episode, list_styles, load_style, resolved_style, style_prompt_text, validate_style


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m factory.styles", description="styles as data: list, show, apply, check")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sh = sub.add_parser("show")
    sh.add_argument("style")
    sh.add_argument("--resolved", action="store_true", help="include what the style resolves to in the consuming code")
    sh.add_argument("--prompt", action="store_true", help="print the director STYLE section instead")
    a_ = sub.add_parser("apply")
    a_.add_argument("--episode", required=True)
    a_.add_argument("--style", required=True)
    a_.add_argument("--out", required=True)
    a_.add_argument("--override-lighting", action="store_true", help="replace the episode's own world.lighting")
    a_.add_argument("--no-retime", action="store_true", help="fail instead of retiming to the style fps")
    ck = sub.add_parser("check")
    ck.add_argument("episode")
    a = ap.parse_args(argv)

    if a.cmd == "list":
        for sid in list_styles():
            s = load_style(sid)
            print(f"{sid:28s} v{s['version']}  {s['frame']['fps']} fps  formats={','.join(s['formats'])}  {s['title']}")
        return 0
    if a.cmd == "show":
        if a.prompt:
            print(style_prompt_text(a.style))
            return 0
        doc = resolved_style(a.style) if a.resolved else load_style(a.style)
        print(json.dumps(doc, indent=1))
        return 0
    if a.cmd == "apply":
        ep = json.load(open(a.episode))
        out = apply_style_to_episode(ep, a.style, retime=not a.no_retime, override_lighting=a.override_lighting)
        errs, warns = check_episode(out)
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        with open(a.out, "w") as fh:
            json.dump(out, fh, indent=1)
            fh.write("\n")
        st = out["style"]["applied"]
        print(f"wrote {a.out}: style {out['style']['id']} fps {out['fps']} ({out['durationFrames']} frames), "
              f"lighting {st['lighting_sequences']}" + (f", handheld x{st['handheld_scale']}" if "handheld_scale" in st else ""))
        for w in warns:
            print("warn:", w)
        for e in errs:
            print("ERROR:", e)
        return 1 if errs else 0
    if a.cmd == "check":
        ep = json.load(open(a.episode))
        if "style" in ep:
            for e in validate_style({k: v for k, v in ep["style"].items() if k not in ("applied", "resolved")}):
                print("STYLE ERROR:", e)
        errs, warns = check_episode(ep)
        for w in warns:
            print("warn:", w)
        for e in errs:
            print("ERROR:", e)
        print(("OK " if not errs else "INVALID ") + a.episode)
        return 1 if errs else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
