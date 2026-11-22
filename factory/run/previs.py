"""Stage 6 previs: one low-res keyframe per shot (local Blender, render_episode.py), a labelled contact sheet and an
animatic (each keyframe held for its shot's duration, narration underneath). Ends at the HUMAN APPROVAL GATE.

    boards/keys/<shot>/<frame>.png   boards/contact_sheet.png   boards/animatic.mp4   boards/previs.json
"""
import json
import os
import subprocess

from . import render

FFMPEG = "ffmpeg"


def key_frame(shot):
    k = shot.get("keyFrame")
    a, b = int(shot["from"]), int(shot["to"])
    return int(k) if k is not None and a <= int(k) < b else (a + b - 1) // 2



def _shot_hash(spec, s):
    """L028: a cached key is only valid for the exact shot it was rendered from (camera repairs, re-directs)."""
    import hashlib
    blob = json.dumps({"shot": s, "world": spec.get("world"), "assets": spec.get("assets")}, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def _cached(spec, keys_dir, s):
    png = os.path.join(keys_dir, s["id"], f"{key_frame(s):04d}.png")
    hp = png + ".hash"
    if not os.path.isfile(png):
        return False
    if not os.path.isfile(hp) or open(hp).read().strip() != _shot_hash(spec, s):
        os.remove(png)          # stale: rendered from an older version of this shot
        return False
    return True


def _stamp(spec, keys_dir, sel):
    for s in sel:
        png = os.path.join(keys_dir, s["id"], f"{key_frame(s):04d}.png")
        if os.path.isfile(png):
            with open(png + ".hash", "w") as fh:
                fh.write(_shot_hash(spec, s))


def black_keys(spec, keys_dir, sel, thresh=0.02):
    """L028: keys whose mean luminance < thresh (a camera inside geometry renders black) unless the shot declares an
    intentional black (direction.black / fade)."""
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return []
    out = []
    for s in sel:
        d = s.get("direction") or {}
        if d.get("black") or d.get("fade") in ("in", "out", "black"):
            continue
        png = os.path.join(keys_dir, s["id"], f"{key_frame(s):04d}.png")
        if os.path.isfile(png):
            m = ImageStat.Stat(Image.open(png).convert("L")).mean[0] / 255.0
            if m < thresh:
                out.append(s["id"])
    return out


def render_keys(spec, spec_path, keys_dir, shots=None, res="144x256", samples=4, engine="EEVEE", workers=1,
                threads=2, blender=None, log_dir=None, stub=False, log=print, backend="local", compute=None):
    sel = [s for s in spec["shots"] if not shots or s["id"] in shots]
    if stub:
        return _stub_keys(sel, keys_dir, res)
    if backend == "compute":   # >>> compute_broker: one frame per shot, spread over the free providers
        todo = [(key_frame(s), key_frame(s)) for s in sel if not _cached(spec, keys_dir, s)]
        if todo:
            if compute is None:
                from factory.compute import api as compute
            log(f"[previs] {len(todo)} keyframe(s) through the compute broker at {res}, {samples} spp")
            compute.render(spec_path, "preview", frames=todo, res=res, samples=samples, dest=keys_dir, log=log)
        _stamp(spec, keys_dir, sel)
        blk = black_keys(spec, keys_dir, sel)
        missing = [s["id"] for s in sel if not os.path.isfile(os.path.join(keys_dir, s["id"], f"{key_frame(s):04d}.png"))] + blk
        return {"keys": len(sel) - len(missing), "missing": missing, "failed": [], "black": blk, "backend": "compute"}
    # <<< compute_broker
    cmds = []
    for s in sel:
        f = key_frame(s)
        if _cached(spec, keys_dir, s):
            continue
        job = {"frameStart": f, "frameEnd": f, "quality": "preview", "engine": engine, "res": res, "samples": samples}
        cmds.append((f"key_{s['id']}_{f:04d}", render.blender_cmd(job, spec_path, keys_dir, blender, threads)))
    env = dict(os.environ)
    env.setdefault("LIBRARY_STORE", os.path.join(render.ROOT, "library_store"))
    log(f"[previs] rendering {len(cmds)} keyframe(s) at {res}, {samples} spp ({len(sel) - len(cmds)} cached)")
    rcs = render.run_cmds(cmds, workers, log_dir, env, log=log) if cmds else {}
    _stamp(spec, keys_dir, sel)
    blk = black_keys(spec, keys_dir, sel)
    missing = [s["id"] for s in sel if not os.path.isfile(os.path.join(keys_dir, s["id"], f"{key_frame(s):04d}.png"))] + blk
    return {"keys": len(sel) - len(missing), "missing": missing, "failed": sorted(k for k, v in rcs.items() if v), "black": blk}


def _stub_keys(shots, keys_dir, res):
    from PIL import Image, ImageDraw
    w, h = (int(v) for v in res.lower().split("x"))
    for i, s in enumerate(shots):
        f = key_frame(s)
        p = os.path.join(keys_dir, s["id"], f"{f:04d}.png")
        if os.path.exists(p):
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        im = Image.new("RGB", (w, h), (18 + (i * 29) % 60, 26 + (i * 17) % 50, 60 + (i * 37) % 90))
        dr = ImageDraw.Draw(im)
        dr.rectangle([0, int(h * 0.62), w, h], fill=(10, 24, 48))                       # sea
        dr.ellipse([int(w * 0.4), int(h * 0.42), int(w * 0.6), int(h * 0.58)], fill=(225, 190, 150))  # hero
        dr.text((4, 4), s["id"], fill=(255, 255, 255))
        cam = s.get("camera") or {}
        dr.text((4, h - 14), str(cam.get("preset") or cam.get("fov") or "")[:22], fill=(200, 200, 200))
        im.save(p)
    return {"keys": len(shots), "missing": [], "failed": [], "stub": True}


def contact_sheet(spec, keys_dir, out_png, cols=6, thumb=(144, 256)):
    from PIL import Image, ImageDraw
    shots = spec["shots"]
    cols = max(1, min(cols, len(shots)))
    rows = max(1, (len(shots) + cols - 1) // cols)
    lab = 30
    sheet = Image.new("RGB", (cols * (thumb[0] + 8) + 8, rows * (thumb[1] + lab + 8) + 8), (16, 16, 20))
    dr = ImageDraw.Draw(sheet)
    fps = spec.get("fps", 30)
    for i, s in enumerate(shots):
        x = 8 + (i % cols) * (thumb[0] + 8)
        y = 8 + (i // cols) * (thumb[1] + lab + 8)
        p = os.path.join(keys_dir, s["id"], f"{key_frame(s):04d}.png")
        if os.path.isfile(p):
            sheet.paste(Image.open(p).convert("RGB").resize(thumb), (x, y))
        else:
            dr.rectangle([x, y, x + thumb[0], y + thumb[1]], outline=(200, 60, 60))
            dr.text((x + 6, y + thumb[1] // 2), "no key", fill=(200, 60, 60))
        dur = (int(s["to"]) - int(s["from"])) / fps
        dr.text((x, y + thumb[1] + 3), f"{s['id']}  {dur:.1f}s", fill=(235, 235, 235))
        dr.text((x, y + thumb[1] + 16), str(s.get("title", ""))[:24], fill=(160, 160, 170))
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    sheet.save(out_png)
    return out_png


def animatic(spec, keys_dir, out_mp4, audio=None, offset_frames=0, size=(270, 480), work=None):
    """Concat-demuxer slideshow: keyframe of each shot held for the shot's duration, narration delayed by the offset."""
    from PIL import Image
    fps = spec.get("fps", 30)
    work = work or os.path.join(os.path.dirname(out_mp4), "_animatic")
    os.makedirs(work, exist_ok=True)
    lst = []
    blank = os.path.join(work, "blank.png")
    Image.new("RGB", size, (0, 0, 0)).save(blank)
    for s in spec["shots"]:
        p = os.path.join(keys_dir, s["id"], f"{key_frame(s):04d}.png")
        lst.append((os.path.abspath(p) if os.path.isfile(p) else blank, (int(s["to"]) - int(s["from"])) / fps))
    txt = os.path.join(work, "list.txt")
    with open(txt, "w") as fh:
        for p, d in lst:
            fh.write(f"file '{p}'\nduration {d:.4f}\n")
        fh.write(f"file '{lst[-1][0]}'\n")
    total = spec.get("durationFrames", spec["shots"][-1]["to"]) / fps
    cmd = [FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", txt]
    if audio and os.path.isfile(audio):
        cmd += ["-i", audio, "-filter_complex",
                f"[1:a]adelay={int(round(offset_frames / fps * 1000))}:all=1,apad[a]", "-map", "0:v", "-map", "[a]",
                "-c:a", "aac", "-b:a", "96k"]
    cmd += ["-vf", f"scale={size[0]}:{size[1]}:force_original_aspect_ratio=decrease,pad={size[0]}:{size[1]}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-movflags", "+faststart", "-t", f"{total:.3f}", out_mp4]
    subprocess.run(cmd, check=True)
    return out_mp4


def run(spec, spec_path, boards_dir, audio=None, shots=None, stub=False, res="144x256", samples=4, workers=1,
        blender=None, log=print, backend="local", mix=None):
    keys = os.path.join(boards_dir, "keys")
    k = render_keys(spec, spec_path, keys, shots=shots, res=res, samples=samples, workers=workers, blender=blender,
                    log_dir=os.path.join(boards_dir, "logs"), stub=stub, log=log, backend=backend)
    sheet = contact_sheet(spec, keys, os.path.join(boards_dir, "contact_sheet.png"))
    # the animatic is watched, not just read: keyframe resolution (even), and the full mix when the sound stage made
    # one (film timeline, no offset) instead of the bare narration
    try:
        w, h = (int(x) for x in str(res).lower().split("x"))
        size = (w - w % 2, h - h % 2)
    except ValueError:
        size = (270, 480)
    off = (spec.get("audio") or {}).get("offsetFrames", 0)
    if mix and os.path.isfile(mix):
        audio, off = mix, 0
    anim = animatic(spec, keys, os.path.join(boards_dir, "animatic.mp4"), audio, off, size=size)
    info = {"keys_dir": keys, "contact_sheet": sheet, "animatic": anim, **k}
    with open(os.path.join(boards_dir, "previs.json"), "w") as fh:
        json.dump(info, fh, indent=1)
    return info
