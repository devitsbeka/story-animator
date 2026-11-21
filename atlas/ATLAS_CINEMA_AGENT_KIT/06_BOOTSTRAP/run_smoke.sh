#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-/tmp/atlas-smoke}"
command -v blender >/dev/null || { echo 'Missing Blender CLI. Install on cloud worker, not user machine.'; exit 2; }
command -v ffmpeg >/dev/null || { echo 'Missing ffmpeg'; exit 2; }
command -v ffprobe >/dev/null || { echo 'Missing ffprobe'; exit 2; }
blender -b -t 2 --python "$ROOT/06_BOOTSTRAP/smoke_scene.py" -- --output "$OUT" --frames 48 --res 480
python3 "$ROOT/06_BOOTSTRAP/verify_render.py" "$OUT" --frames 48
ffmpeg -hide_banner -loglevel error -y -framerate 24 -i "$OUT/frame_%04d.png" -c:v libx264 -pix_fmt yuv420p "$OUT/output.mp4"
ffprobe -v error -show_entries stream=width,height,codec_name -show_entries format=duration -of json "$OUT/output.mp4"
ls -lh "$OUT/output.mp4"
