"""Stage 8 finish: factory/finish/make_plates_manifest.py (plates manifest + captions + staged Remotion props) and a
Remotion render of the Finish composition (studio/src/finish) -> episodes/<id>/final/episode.mp4.

stub: the same manifest step, then ffmpeg concatenates the plates in film order with the mix (no captions/grade), so
the QC stage has a real mp4 to measure in CI time.
"""
import os
import shutil
import subprocess
import sys

from factory.director.paths import ROOT

FINISH_DIR = os.path.join(ROOT, "factory", "finish")


def _manifest(argv):
    if FINISH_DIR not in sys.path:
        sys.path.insert(0, FINISH_DIR)
    import make_plates_manifest
    rc = make_plates_manifest.main(argv)
    if rc:
        raise RuntimeError(f"make_plates_manifest exited {rc}")


def studio_dir():
    return os.environ.get("FACTORY_STUDIO", os.path.join(ROOT, "studio"))


def finish_real(spec, spec_path, plates, audio, out_mp4, log_path=None, log=print):
    st = studio_dir()
    if not os.path.isdir(os.path.join(st, "node_modules")):
        raise RuntimeError(f"Remotion studio at {st} has no node_modules (run `npm ci` there or set FACTORY_STUDIO)")
    pub = os.path.join(st, "public")
    argv = ["--episode", spec_path, "--plates", plates, "--stage", "--public", pub]
    if audio:
        argv += ["--audio", audio]
    _manifest(argv)
    props = os.path.join(pub, "finish", spec["id"], "props.json")
    cmd = ["npx", "remotion", "render", "src/index.ts", "Finish", os.path.abspath(out_mp4), f"--props={props}",
           "--codec", "h264", "--pixel-format", "yuv420p", "--crf", "18"]
    log(f"[finish] remotion render -> {out_mp4}")
    with open(log_path or os.devnull, "w") as fh:
        rc = subprocess.run(cmd, cwd=st, stdout=fh, stderr=subprocess.STDOUT).returncode
    if rc:
        raise RuntimeError(f"remotion render exited {rc} (log {log_path})")
    return {"mode": "remotion", "video": out_mp4, "props": props}


def finish_stub(spec, spec_path, plates, audio, out_mp4, log=print):
    argv = ["--episode", spec_path, "--plates", plates] + (["--audio", audio] if audio else [])
    _manifest(argv)
    fps = spec.get("fps", 30)
    work = os.path.join(os.path.dirname(out_mp4), "_stub")
    os.makedirs(work, exist_ok=True)
    lst = os.path.join(work, "frames.txt")
    last = None
    with open(lst, "w") as fh:
        for s in spec["shots"]:
            for f in range(int(s["from"]), int(s["to"])):
                p = os.path.join(plates, s["id"], f"{f:04d}.png")
                p = p if os.path.isfile(p) else last
                if p is None:
                    continue
                fh.write(f"file '{os.path.abspath(p)}'\nduration {1 / fps:.6f}\n")
                last = p
        if last:
            fh.write(f"file '{os.path.abspath(last)}'\n")
    total = spec["durationFrames"] / fps
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst]
    if audio and os.path.isfile(audio):
        cmd += ["-i", audio, "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-vf", f"fps={fps},scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "28", "-t", f"{total:.3f}", out_mp4]
    subprocess.run(cmd, check=True)
    shutil.rmtree(work, ignore_errors=True)
    return {"mode": "stub", "video": out_mp4}
