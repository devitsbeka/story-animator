#!/usr/bin/env python3
"""
make_plates_manifest.py - scan a Blender plates dir and write the inputs of the Remotion
'Finish' composition (studio/src/finish).

  python3 factory/finish/make_plates_manifest.py --episode episodes/<id>/episode_v2.json \
      --plates episodes/<id>/plates [--stage] [--from N --to M] [--audio path] [--words path]

Plates layout (what cloud/blender/render_episode.py writes):
  <plates>/<shotId>/<frame:04d>.png     frame = ABSOLUTE film frame at the episode fps

Writes:
  <plates>/plates_manifest.json         {shotId: {"frames": [...], "width", "height"}}
With --stage (for `remotion render`, which can only read studio/public via staticFile):
  studio/public/finish/<id>/plates/<shotId>/####.png   (copied, only when changed)
  studio/public/finish/<id>/<audio file>
  studio/public/finish/<id>/props.json  -> pass with `--props=public/finish/<id>/props.json`

props.json = {episodeJson, platesDir, manifest, audio, captions, steps, range?}
  episodeJson  slim copy of the episode (id, fps, size, audio offset, shots[id, from, to, title, transition])
  platesDir    staticFile-relative dir holding <shot>/####.png
  captions     1-3 word pages built from the narration word timings (ENGAGEMENT_RECIPE 5, C-2..C-5)
  steps        STEP tracker spans (C-7), from the episode's "step N" captions or the words
"""
import argparse
import json
import os
import re
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from captions import build_pages, build_steps  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
FRAME_RE = re.compile(r"^(\d{4,6})\.png$")


def png_size(path):
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return int(w), int(h)


def scan_plates(plates_dir):
    """{shotId: {"frames": sorted absolute frames, "width", "height"}} for every shot dir with PNGs."""
    out = {}
    if not os.path.isdir(plates_dir):
        return out
    for shot in sorted(os.listdir(plates_dir)):
        d = os.path.join(plates_dir, shot)
        if not os.path.isdir(d):
            continue
        frames = sorted(int(m.group(1)) for m in (FRAME_RE.match(n) for n in os.listdir(d)) if m)
        if not frames:
            continue
        size = png_size(os.path.join(d, f"{frames[0]:04d}.png")) or (0, 0)
        out[shot] = {"frames": frames, "width": size[0], "height": size[1]}
    return out


def slim_episode(ep):
    shots = []
    for s in ep.get("shots", []):
        e = {"id": s["id"], "from": int(s["from"]), "to": int(s["to"]), "title": s.get("title", "")}
        for k in ("transition", "step"):
            if k in s:
                e[k] = s[k]
        shots.append(e)
    return {
        "id": ep.get("id", "episode"), "title": ep.get("title", ""),
        "fps": int(ep.get("fps", 30)), "width": int(ep.get("width", 1080)), "height": int(ep.get("height", 1920)),
        "durationFrames": int(ep.get("durationFrames", shots[-1]["to"] if shots else 1)),
        "audio": {"offsetFrames": int((ep.get("audio") or {}).get("offsetFrames", 0))},
        "shots": shots,
    }


# --- style system hook (factory/styles): episode.style -> Finish props (grade, captionStyle, transitions) ---
def style_finish_props(style):
    if not style or "grade" not in style or "captions" not in style:
        return {}
    sys.path.insert(0, REPO)
    from factory.styles import finish_props
    return finish_props(style)
# --- end style system hook ---------------------------------------------------------------------------------


def resolve(path, base):
    if not path:
        return None
    for cand in (path, os.path.join(base, path), os.path.join(REPO, path)):
        if os.path.exists(cand):
            return os.path.abspath(cand)
    return None


def pick_audio(ep, ep_dir, explicit):
    if explicit:
        return resolve(explicit, ep_dir)
    for cand in (os.path.join(ep_dir, "audio", "mix_v1.m4a"),
                 resolve((ep.get("audio") or {}).get("mix"), ep_dir),
                 resolve((ep.get("audio") or {}).get("narration"), ep_dir),
                 os.path.join(ep_dir, "audio", "narration.mp3")):
        if cand and os.path.exists(cand):
            return os.path.abspath(cand)
    return None


def copy_if_changed(src, dst):
    if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return True


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--episode", required=True, help="episode json (shots with from/to)")
    p.add_argument("--plates", required=True, help="plates dir with <shot>/####.png")
    p.add_argument("--audio", default=None, help="audio file (default: <ep>/audio/mix_v1.m4a, else narration)")
    p.add_argument("--words", default=None, help="narration words json [{w,s,e}] (default: episode audio.wordsJson)")
    p.add_argument("--stage", action="store_true", help="copy plates + audio into studio/public/finish/<id>/ and write props.json")
    p.add_argument("--public", default=os.path.join(REPO, "studio", "public"), help="Remotion public dir")
    p.add_argument("--from", dest="rng_from", type=int, default=None, help="render range start (film frame)")
    p.add_argument("--to", dest="rng_to", type=int, default=None, help="render range end (film frame, exclusive)")
    a = p.parse_args(argv)

    ep_path = os.path.abspath(a.episode)
    ep_dir = os.path.dirname(ep_path)
    with open(ep_path) as fh:
        ep = json.load(fh)
    slim = slim_episode(ep)
    plates = scan_plates(a.plates)
    known = {s["id"] for s in slim["shots"]}
    for shot, info in plates.items():
        if shot not in known:
            print(f"[manifest] WARNING: plates for unknown shot {shot} (ignored by Finish)", file=sys.stderr)
    with open(os.path.join(a.plates, "plates_manifest.json"), "w") as fh:
        json.dump({"episode": slim["id"], "fps": slim["fps"], "shots": plates}, fh, indent=1)
    n = sum(len(v["frames"]) for v in plates.values())
    print(f"[manifest] {len(plates)} shots, {n} plate frames -> {os.path.join(a.plates, 'plates_manifest.json')}")

    words_path = resolve(a.words or (ep.get("audio") or {}).get("wordsJson"), ep_dir)
    words = json.load(open(words_path)) if words_path else []
    fps, off = slim["fps"], slim["audio"]["offsetFrames"]
    style = ep.get("style") or {}  # style system hook (factory/styles): caption paging + finish props
    pages = build_pages(words, fps=fps, offset=off, anchors=ep.get("captions") or [],
                        paging=(style.get("captions") or {}).get("paging"))
    steps = build_steps(words, slim["shots"], fps=fps, offset=off, anchors=ep.get("captions") or [])
    print(f"[manifest] {len(pages)} caption pages, {len(steps)} steps (words: {words_path})")

    if not a.stage:
        return 0
    eid = slim["id"]
    pub_root = os.path.join(a.public, "finish", eid)
    copied = 0
    for shot, info in plates.items():
        for f in info["frames"]:
            name = f"{f:04d}.png"
            copied += copy_if_changed(os.path.join(a.plates, shot, name), os.path.join(pub_root, "plates", shot, name))
    audio_src = pick_audio(ep, ep_dir, a.audio)
    audio_rel = None
    if audio_src:
        dst = os.path.join(pub_root, "audio" + os.path.splitext(audio_src)[1])
        copy_if_changed(audio_src, dst)
        audio_rel = os.path.relpath(dst, a.public).replace(os.sep, "/")
    else:
        print("[manifest] WARNING: no audio found; Finish renders silent", file=sys.stderr)
    props = {
        "episodeJson": slim,
        "platesDir": f"finish/{eid}/plates",
        "manifest": {k: {"frames": v["frames"]} for k, v in plates.items()},
        "audio": audio_rel,
        "captions": pages,
        "steps": steps,
    }
    props.update(style_finish_props(style))  # style system hook
    if a.rng_from is not None or a.rng_to is not None:
        props["range"] = {"from": a.rng_from or 0, "to": a.rng_to or slim["durationFrames"]}
    props_path = os.path.join(pub_root, "props.json")
    with open(props_path, "w") as fh:
        json.dump(props, fh)
    print(f"[manifest] staged {copied} new plate files, audio={audio_rel} -> {props_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
