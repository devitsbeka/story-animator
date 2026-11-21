"""python -m factory.shorts derive --episode episodes/<id> [--n 3] [--voice auto|off] [--render] [--no-qc]

Derives vertical shorts from a finished docuseries episode dir (story.json + episode.json from factory.director,
optional audio/narration.mp3 + narration.words.json, optional plates_vertical/ from
`render_episode.py --camera vertical`). Writes episodes/<id>/shorts/<SC>/{edit,episode,words,props}.json (+ audio.wav),
then runs the shorts checklist and factory.qc on every short; --render stages the plates and renders Finish to
shorts/<SC>/short.mp4 first, so QC also measures the video."""
import argparse
import json
import os
import sys

from . import checks, derive as dv, finish


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m factory.shorts", description="Derive vertical shorts from a long-form docuseries episode")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("derive")
    d.add_argument("--episode", required=True, help="episode dir with story.json + episode.json (format docuseries)")
    d.add_argument("--n", type=int, default=None, help="number of shorts (default: every eligible candidate)")
    d.add_argument("--out", default=None, help="output root (default <episode>/shorts)")
    d.add_argument("--voice", choices=["auto", "off"], default="auto", help="VO pickup hook via factory.voice when available")
    d.add_argument("--plates", default=None, help="vertical plates dir (default <episode>/plates_vertical)")
    d.add_argument("--render", action="store_true", help="stage plates + render Finish to shorts/<SC>/short.mp4")
    d.add_argument("--frames", default=None, help="with --render: frame range a-b (preview)")
    d.add_argument("--no-qc", action="store_true")
    a = ap.parse_args(argv)

    ctx, results = dv.derive(a.episode, a.n, a.out, a.voice)
    ok = True
    summary = []
    for res in results:
        rep = checks.check_short(res, ctx["episode"])
        video = None
        if a.render:
            props, n = finish.stage(res, a.plates or os.path.join(a.episode, "plates_vertical"))
            video = os.path.join(res["dir"], "short.mp4")
            finish.render(props, video, a.frames)
            print(f"[{res['id']}] rendered {video} ({n} plate frames staged)")
        q = None if a.no_qc else finish.qc(res, video)
        e = res["edit"]
        row = {"id": res["id"], "candidate": e["candidate"], "seconds": round(e["durationFrames"] / 30, 2), "shots": len(e["shots"]),
               "hook": {"source": e["hook"]["source"], "seconds": round((e["hook"]["dst1"] - e["hook"]["dst0"]) / 30, 2)},
               "checklist": rep.to_dict(), "qc": q and {"decision": q["decision"], "engagement_score": q["engagement_score"],
                                                        "coverage": q["coverage"], "hard_failures": q["hard_failures"], "report": q["path"]}}
        with open(os.path.join(res["dir"], "report.json"), "w") as fh:
            json.dump(row, fh, indent=1)
        ok &= rep.ok
        summary.append(row)
        print(f"[{res['id']}] {row['seconds']} s, {row['shots']} shots, hook {row['hook']['source']} {row['hook']['seconds']} s, "
              f"checklist {'PASS' if rep.ok else 'FAIL'}" + (f", qc {q['decision']} score {q['engagement_score']} (coverage {q['coverage']})" if q else ""))
        for i in rep.blocking:
            print(f"    [{i['severity']} {i['rule']}] {i['msg']}")
    print(f"{len(results)} short(s) from {ctx['episode']['id']} (words: {ctx['words_source']})")
    return 0 if ok and results else 1


if __name__ == "__main__":
    sys.exit(main())
