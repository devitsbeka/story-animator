"""Finish + QC for derived shorts: stage the Remotion 'Finish' inputs (vertical plates, audio, props.json) and
render; then run factory.qc (the shorts checklist) on the short's episode.json and mp4."""
import json
import os
import shutil
import subprocess

from factory.director.paths import ROOT

STUDIO = os.path.join(ROOT, "studio")


def stage(res, plates_vertical, public=os.path.join(STUDIO, "public")):
    """Copy the vertical plate frames the edit reads into studio/public/finish/<short>/plates/<shot>/####.png,
    the audio next to them, and write props.json (manifest = the frames actually available)."""
    sid, props = res["id"], json.loads(json.dumps(res["props"]))
    root = os.path.join(public, "finish", sid)
    manifest = {}
    for s in props["episodeJson"]["shots"]:
        need = range(s["src"], s["src"] + s["to"] - s["from"])
        for f in need:
            src = os.path.join(plates_vertical, s["plate"], f"{f:04d}.png")
            if os.path.exists(src):
                dst = os.path.join(root, "plates", s["plate"], f"{f:04d}.png")
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if not os.path.exists(dst):
                    shutil.copy2(src, dst)
                manifest.setdefault(s["plate"], set()).add(f)
    props["manifest"] = {k: {"frames": sorted(v)} for k, v in manifest.items()}
    audio = os.path.join(res["dir"], "audio.wav")
    if os.path.exists(audio):
        shutil.copy2(audio, os.path.join(root, "audio.wav"))
        props["audio"] = f"finish/{sid}/audio.wav"
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, "props.json")
    with open(path, "w") as fh:
        json.dump(props, fh)
    return path, sum(len(v["frames"]) for v in props["manifest"].values())


def render(props_path, out_mp4, frames=None, timeout=3600):
    """npx remotion render Finish (9:16) with the staged props; frames='a-b' renders a range (preview)."""
    cmd = ["npx", "remotion", "render", "src/index.ts", "Finish", os.path.abspath(out_mp4), f"--props={os.path.abspath(props_path)}",
           "--codec", "h264", "--pixel-format", "yuv420p", "--crf", "20", "--concurrency", "2"]
    if frames:
        cmd += ["--frames", frames]
    subprocess.run(cmd, cwd=STUDIO, check=True, timeout=timeout)
    return cmd


def qc(res, video=None, log=lambda *a: None):
    from factory.qc.report import run
    return run(spec=os.path.join(res["dir"], "episode.json"), video_path=video, out_dir=os.path.join(res["dir"], "qc"),
               run_vision=False, log=log)
