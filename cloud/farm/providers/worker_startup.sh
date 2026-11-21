#!/usr/bin/env bash
# worker_startup.sh - boot a story-farm render worker on a plain CUDA container (RunPod, Vast.ai, any GPU box).
#
# No custom Docker image: this runs as the container command of a public NVIDIA CUDA base image
# (nvidia/cuda:12.4.1-base-ubuntu22.04), installs what the farm Dockerfile would have baked in, then execs
# cloud/farm/worker.py, which polls the same SQS queue as the AWS workers. When the worker exits (idle timeout),
# the container stops and the scheduler terminates the machine.
#
# providers/startup.py renders this file: it prepends a block of FARM_* settings (no secrets) and the rendered
# script is shipped gzip+base64 inside the container command. Secrets arrive as container env vars only:
#   AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY  keys of the least-privilege 'farm-worker-external' IAM user
#   GIT_TOKEN                                  read-only deploy token (only for FARM_CODE_SOURCE=git, private repo)
# Settings (all have defaults below so `bash -n` and shellcheck see a complete script):
#   FARM_CODE_SOURCE git|s3   FARM_GIT_URL FARM_GIT_COMMIT   FARM_CODE_KEY FARM_CODE_SHA256
#   FARM_BUCKET FARM_QUEUE_URL FARM_TABLE AWS_REGION   FARM_PROVIDER FARM_GPU_CLASS   REQUIRE_GPU
set -euo pipefail

: "${FARM_CODE_SOURCE:=git}"
: "${FARM_GIT_URL:=}"
: "${FARM_GIT_COMMIT:=}"
: "${FARM_CODE_KEY:=}"
: "${FARM_CODE_SHA256:=}"
: "${FARM_PROVIDER:=external}"
: "${FARM_GPU_CLASS:=unknown}"
: "${REQUIRE_GPU:=1}"
: "${AWS_REGION:=us-east-1}"
: "${BLENDER_VERSION:=4.2.3}"
: "${BLENDER_SERIES:=4.2}"
: "${BLENDER_SHA256:=3a64efd1982465395abab4259b4091d5c8c56054c7267e9633e4f702a71ea3f4}"
: "${FARM_ROOT:=/opt/factory}"
: "${FARM_VENV:=/opt/farm-venv}"
: "${BLENDER_DIR:=/opt/blender}"
: "${FARM_WORK_DIR:=/work}"
: "${FARM_CACHE_DIR:=/cache}"

export DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
# Blender links libGL/EGL; OptiX needs libnvoptix, which the NVIDIA runtime only mounts with these capabilities.
export NVIDIA_DRIVER_CAPABILITIES="${NVIDIA_DRIVER_CAPABILITIES:-compute,utility,graphics}"

log() { printf '{"t":"%s","event":"startup","provider":"%s","msg":"%s"}\n' "$(date -u +%FT%TZ)" "$FARM_PROVIDER" "$*"; }
die() { log "FATAL: $*"; exit "${2:-1}"; }

for v in FARM_BUCKET FARM_QUEUE_URL FARM_TABLE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY; do
  [ -n "${!v:-}" ] || die "missing env $v" 2
done

# The id the scheduler knows this machine by (it matches heartbeats to launched handles).
if [ -z "${FARM_PROVIDER_WORKER_ID:-}" ]; then
  case "$FARM_PROVIDER" in
    runpod) FARM_PROVIDER_WORKER_ID="runpod:${RUNPOD_POD_ID:-$(hostname)}" ;;
    vastai) vid="${CONTAINER_ID:-${VAST_CONTAINERLABEL:-$(hostname)}}"; FARM_PROVIDER_WORKER_ID="vastai:${vid#C.}" ;;
    *) FARM_PROVIDER_WORKER_ID="${FARM_PROVIDER}:$(hostname)" ;;
  esac
fi
export FARM_PROVIDER_WORKER_ID
log "booting worker ${FARM_PROVIDER_WORKER_ID} gpuClass=${FARM_GPU_CLASS}"

# ---------------------------------------------------------------------------------------------- system packages
if command -v apt-get >/dev/null 2>&1; then
  SUDO=""
  [ "$(id -u)" -eq 0 ] || SUDO="sudo"
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq --no-install-recommends \
    ca-certificates curl xz-utils git python3 python3-venv \
    libx11-6 libxi6 libxxf86vm1 libxfixes3 libxrender1 libxkbcommon0 libsm6 libice6 \
    libgl1 libegl1 libglvnd0 libgomp1 >/dev/null
fi

# ---------------------------------------------------------------------------------------------- GPU
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L; then
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader || true
elif [ "$REQUIRE_GPU" = "1" ]; then
  die "REQUIRE_GPU=1 but nvidia-smi sees no GPU" 3
fi
if ! ldconfig -p 2>/dev/null | grep -q libnvoptix; then
  log "libnvoptix not mounted: Cycles will use CUDA instead of OptiX (same pixels, ~20% slower)"
fi

# ---------------------------------------------------------------------------------------------- Blender (pinned)
if [ ! -x "$BLENDER_DIR/blender" ]; then
  tarball="/tmp/blender-${BLENDER_VERSION}.tar.xz"
  curl -fsSL --retry 5 -o "$tarball" \
    "https://download.blender.org/release/Blender${BLENDER_SERIES}/blender-${BLENDER_VERSION}-linux-x64.tar.xz"
  echo "${BLENDER_SHA256}  ${tarball}" | sha256sum -c - >/dev/null || die "blender tarball checksum mismatch" 4
  mkdir -p "$BLENDER_DIR"
  tar -xJf "$tarball" -C "$BLENDER_DIR" --strip-components=1
  rm -f "$tarball"
fi
"$BLENDER_DIR/blender" -b --factory-startup --python-expr "import bpy; print('blender', bpy.app.version_string)" \
  | grep '^blender ' || die "blender does not start" 4

# ---------------------------------------------------------------------------------------------- python deps
[ -x "$FARM_VENV/bin/python" ] || python3 -m venv "$FARM_VENV"
"$FARM_VENV/bin/pip" install -q --upgrade pip >/dev/null
"$FARM_VENV/bin/pip" install -q "boto3==1.35.99"

# ---------------------------------------------------------------------------------------------- code (pinned)
mkdir -p "$FARM_ROOT"
case "$FARM_CODE_SOURCE" in
  git)
    [ -n "$FARM_GIT_URL" ] && [ -n "$FARM_GIT_COMMIT" ] || die "FARM_GIT_URL/FARM_GIT_COMMIT required" 2
    git_auth=()
    if [ -n "${GIT_TOKEN:-}" ]; then
      basic=$(printf 'x-access-token:%s' "$GIT_TOKEN" | base64 | tr -d '\n')
      git_auth=(-c "http.extraHeader=Authorization: Basic ${basic}")
    fi
    if [ ! -d "$FARM_ROOT/.git" ]; then git init -q "$FARM_ROOT"; fi
    git -C "$FARM_ROOT" "${git_auth[@]}" fetch -q --depth 1 "$FARM_GIT_URL" "$FARM_GIT_COMMIT"
    git -C "$FARM_ROOT" checkout -q --force FETCH_HEAD
    got=$(git -C "$FARM_ROOT" rev-parse HEAD)
    case "$got" in "$FARM_GIT_COMMIT"*) ;; *) die "checked out $got, wanted $FARM_GIT_COMMIT" 5 ;; esac
    unset GIT_TOKEN basic
    ;;
  s3)
    [ -n "$FARM_CODE_KEY" ] || die "FARM_CODE_KEY required" 2
    "$FARM_VENV/bin/python" - "$FARM_BUCKET" "$FARM_CODE_KEY" /tmp/farm-code.tar.gz <<'PY'
import sys, boto3
boto3.client("s3").download_file(sys.argv[1], sys.argv[2], sys.argv[3])
PY
    if [ -n "$FARM_CODE_SHA256" ]; then
      echo "${FARM_CODE_SHA256}  /tmp/farm-code.tar.gz" | sha256sum -c - >/dev/null || die "code tarball checksum mismatch" 5
    fi
    tar -xzf /tmp/farm-code.tar.gz -C "$FARM_ROOT"
    rm -f /tmp/farm-code.tar.gz
    ;;
  *) die "unknown FARM_CODE_SOURCE=$FARM_CODE_SOURCE" 2 ;;
esac
[ -f "$FARM_ROOT/cloud/farm/worker.py" ] || die "worker.py missing from the code checkout" 5
# assets/ is a symlink to studio/public/assets in the repo (git keeps it; recreate if the archive dropped it)
[ -e "$FARM_ROOT/assets" ] || [ -L "$FARM_ROOT/assets" ] || ln -s studio/public/assets "$FARM_ROOT/assets"

# ---------------------------------------------------------------------------------------------- Cycles device probe
probe=$("$BLENDER_DIR/blender" -b --factory-startup --python-expr "
import bpy
p = bpy.context.preferences.addons['cycles'].preferences
found = []
for t in ('OPTIX', 'CUDA'):
    try:
        p.compute_device_type = t
        p.get_devices()
    except Exception:
        continue
    found += [t + ':' + d.name for d in p.devices if d.type == t]
print('CYCLES_DEVICES', ';'.join(found) or 'CPU')
" 2>/dev/null | grep '^CYCLES_DEVICES' || true)
log "${probe:-CYCLES_DEVICES unknown}"
if [ "$REQUIRE_GPU" = "1" ] && ! printf '%s' "$probe" | grep -Eq 'OPTIX:|CUDA:'; then
  die "Cycles sees no OptiX/CUDA device" 3
fi

# ---------------------------------------------------------------------------------------------- run
mkdir -p "$FARM_WORK_DIR" "$FARM_CACHE_DIR/library_store"
export FARM_REPO="$FARM_ROOT" FARM_WORK="$FARM_WORK_DIR" LIBRARY_STORE="$FARM_CACHE_DIR/library_store"
export BLENDER="$BLENDER_DIR/blender"
export FARM_IMDS=0 HEALTH_FILE=/tmp/farm-worker.health AWS_DEFAULT_REGION="$AWS_REGION"
export FARM_PROVIDER FARM_GPU_CLASS REQUIRE_GPU AWS_REGION
log "starting worker.py"
exec "$FARM_VENV/bin/python" "$FARM_ROOT/cloud/farm/worker.py"
