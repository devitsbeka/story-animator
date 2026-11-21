"""Stand-in for `blender -b -P render_episode.py -- ...` in worker tests: writes tiny PNG plates + the
renderer's _render_<a>_<b>.json exactly where render_episode.py would. Behaviour via env:
FAKE_RC (exit code), FAKE_DEVICE (OPTIX|CPU), FAKE_SKIP (frame to leave out), FAKE_SLEEP (seconds),
FAKE_CALLS (file: append one line per call)."""
import argparse
import json
import os
import struct
import sys
import time
import zlib


def png(w=2, h=2):
    raw = b"".join(b"\x00" + b"\x80\x40\x20" * w for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


argv = sys.argv[sys.argv.index("--") + 1:]
p = argparse.ArgumentParser()
for k in ("--spec", "--start", "--end", "--out", "--quality", "--engine", "--root", "--res", "--samples", "--threads",
          "--haze", "--exposure", "--ocean-res"):
    p.add_argument(k)
for k in ("--skip-existing", "--strict-engine", "--no-motion-blur"):
    p.add_argument(k, action="store_true")
a = p.parse_args(argv)
if os.environ.get("FAKE_CALLS"):
    with open(os.environ["FAKE_CALLS"], "a") as fh:
        fh.write(" ".join(argv) + "\n")
time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
if os.environ.get("FAKE_RC", "0") != "0":
    print("fake blender: failing on purpose")
    sys.exit(int(os.environ["FAKE_RC"]))
spec = json.load(open(a.spec))
s, e = int(a.start), int(a.end)
skip = int(os.environ.get("FAKE_SKIP", "-1"))
for shot in spec["shots"]:
    frames = [f for f in range(max(s, shot["from"]), min(e, shot["to"] - 1) + 1)]
    if not frames:
        continue
    d = os.path.join(a.out, shot["id"])
    os.makedirs(d, exist_ok=True)
    done = {}
    for f in frames:
        path = os.path.join(d, f"{f:04d}.png")
        if f == skip or (a.skip_existing and os.path.exists(path)):
            continue
        with open(path, "wb") as fh:
            fh.write(png())
        done[str(f)] = 0.5
    with open(os.path.join(d, f"_render_{frames[0]}_{frames[-1]}.json"), "w") as fh:
        json.dump({"shot": shot["id"], "frames": [frames[0], frames[-1]], "engine": a.engine,
                   "device": os.environ.get("FAKE_DEVICE", "OPTIX"), "quality": a.quality, "resolution": [2, 2],
                   "samples": 1, "blender": "fake", "secondsPerFrame": done, "warnings": []}, fh)
print(f"fake blender rendered {s}..{e}")
