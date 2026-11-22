#!/usr/bin/env bash
# presigned_startup.sh - boot a credential-free story-farm render pod (RunPod / Vast.ai / any CUDA box).
#
# The pod gets exactly one input: MANIFEST_URL, a presigned S3 GET of its pod manifest (cloud/farm/presigned.py
# writes it). Everything else - code tarball, spec, library files, and the presigned PUT URLs for every plate,
# log, heartbeat and the done marker - is in that manifest. There are NO cloud credentials in this container.
#
# Steps: tools (apt) -> manifest -> GPU fail-fast -> Blender 4.2.3 (pinned sha256) -> code tarball (sha256)
#        -> exec cloud/farm/presigned_pod.py (inputs, renders, uploads, heartbeats, done marker, then idles).
# Any failure before the runner starts PUTs a FAILED done marker (so the orchestrator replaces the pod at once)
# and then idles (or exits when the manifest says exitWhenDone).
#
# Overridable for local runs (a pod uses the defaults): BLENDER (existing binary: skip the install),
# PRESIGNED_HOME (work dir), PRESIGNED_REPO (code dir), CURL.
set -euo pipefail

: "${MANIFEST_URL:?MANIFEST_URL (presigned GET of the pod manifest) is required}"
: "${PRESIGNED_HOME:=/work}"
: "${PRESIGNED_REPO:=$PRESIGNED_HOME/repo}"
: "${BLENDER_DIR:=/opt/blender}"
: "${BLENDER:=$BLENDER_DIR/blender}"
: "${BLENDER_VERSION:=4.2.3}"
: "${BLENDER_SERIES:=4.2}"
: "${BLENDER_SHA256:=3a64efd1982465395abab4259b4091d5c8c56054c7267e9633e4f702a71ea3f4}"
: "${CURL:=curl}"
export DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
export NVIDIA_DRIVER_CAPABILITIES="${NVIDIA_DRIVER_CAPABILITIES:-compute,utility,graphics}"

mkdir -p "$PRESIGNED_HOME"
POD_LOG="$PRESIGNED_HOME/pod.log"
exec > >(tee -a "$POD_LOG") 2>&1

log() { printf '{"t":"%s","event":"startup","msg":"%s"}\n' "$(date -u +%FT%TZ)" "$*"; }
MANIFEST="$PRESIGNED_HOME/manifest.json"
EXIT_WHEN_DONE=0

# mf <python expression on d> : read a field of the manifest
mf() { python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); v=eval(sys.argv[2]); print("" if v is None else v)' "$MANIFEST" "$1"; }

put_file() {  # put_file <json path of a presigned PUT target, e.g. d["done"]> <file>
  local url ctype
  url=$(mf "$1[\"url\"]") ctype=$(mf "$1[\"headers\"].get(\"Content-Type\", \"\")")
  "$CURL" -fsS --retry 5 --retry-all-errors --connect-timeout 20 -X PUT -T "$2" ${ctype:+-H "Content-Type: $ctype"} \
    -o /dev/null "$url"
}

fail() {
  local msg="$1"
  log "FATAL: $msg"
  trap - ERR
  if [ -s "$MANIFEST" ] && command -v python3 >/dev/null 2>&1; then
    python3 -c 'import json,sys,time; print(json.dumps({"status":"FAILED","stage":"startup","error":sys.argv[1],"t":time.time()}))' \
      "$msg" > "$PRESIGNED_HOME/done.json" || true
    put_file 'd["done"]' "$PRESIGNED_HOME/done.json" || true
    put_file 'd["podLog"]' "$POD_LOG" || true
  fi
  if [ "$EXIT_WHEN_DONE" = "1" ]; then exit 1; fi
  log "idling until the orchestrator terminates this pod"
  while true; do sleep 3600; done
}
trap 'fail "startup error at line $LINENO"' ERR

# ---------------------------------------------------------------------------------------------- tools
need_apt=0
for t in curl python3 tar xz sha256sum; do command -v "$t" >/dev/null 2>&1 || need_apt=1; done
[ -x "$BLENDER" ] || need_apt=1
if [ "$need_apt" = "1" ] && command -v apt-get >/dev/null 2>&1; then
  SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"
  log "installing system packages"
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq --no-install-recommends \
    ca-certificates curl xz-utils python3 \
    libx11-6 libxi6 libxxf86vm1 libxfixes3 libxrender1 libxkbcommon0 libsm6 libice6 \
    libgl1 libegl1 libglvnd0 libgomp1 >/dev/null
fi

# ---------------------------------------------------------------------------------------------- manifest
log "fetching pod manifest"
"$CURL" -fsSL --retry 8 --retry-all-errors --connect-timeout 20 -o "$MANIFEST.part" "$MANIFEST_URL" \
  || { log "FATAL: cannot fetch the manifest (expired URL?)"; while true; do sleep 3600; done; }
mv "$MANIFEST.part" "$MANIFEST"
EXIT_WHEN_DONE=$(mf '1 if d.get("exitWhenDone") else 0')
log "manifest for pod $(mf 'd["pod"]') run $(mf 'd["runId"]'): $(mf 'len(d["jobs"])') jobs, expires $(mf 'd["expiresAt"]')"

# ---------------------------------------------------------------------------------------------- GPU fail-fast
if [ "$(mf '1 if d.get("requireGpu", True) else 0')" = "1" ]; then
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L; then
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader || true
  elif [ -d /proc/driver/nvidia/gpus ] && [ -n "$(ls -A /proc/driver/nvidia/gpus 2>/dev/null)" ]; then
    log "nvidia-smi missing but the kernel lists GPUs: $(ls /proc/driver/nvidia/gpus | tr '\n' ' ')"
  else
    fail "no NVIDIA GPU visible (requireGpu)"
  fi
fi

# ---------------------------------------------------------------------------------------------- Blender (pinned)
if [ ! -x "$BLENDER" ]; then
  url=$(mf 'd["blender"]["url"]')
  want=$(mf 'd["blender"]["sha256"]'); want=${want:-$BLENDER_SHA256}
  tarball="$PRESIGNED_HOME/blender-${BLENDER_VERSION}.tar.xz"
  log "downloading Blender $BLENDER_VERSION"
  "$CURL" -fsSL --retry 5 --retry-all-errors -o "$tarball" "${url:-https://download.blender.org/release/Blender${BLENDER_SERIES}/blender-${BLENDER_VERSION}-linux-x64.tar.xz}"
  echo "${want}  ${tarball}" | sha256sum -c - >/dev/null || fail "blender tarball checksum mismatch"
  mkdir -p "$BLENDER_DIR"
  tar -xJf "$tarball" -C "$BLENDER_DIR" --strip-components=1
  rm -f "$tarball"
  BLENDER="$BLENDER_DIR/blender"
fi
"$BLENDER" -b --factory-startup --python-expr "import bpy; print('blender', bpy.app.version_string)" 2>/dev/null \
  | grep '^blender ' || fail "blender does not start"

# ---------------------------------------------------------------------------------------------- code (sha256)
log "fetching code tarball"
"$CURL" -fsSL --retry 5 --retry-all-errors --connect-timeout 20 -o "$PRESIGNED_HOME/code.tar.gz" "$(mf 'd["code"]["url"]')"
echo "$(mf 'd["code"]["sha256"]')  $PRESIGNED_HOME/code.tar.gz" | sha256sum -c - >/dev/null || fail "code tarball checksum mismatch"
mkdir -p "$PRESIGNED_REPO"
tar -xzf "$PRESIGNED_HOME/code.tar.gz" -C "$PRESIGNED_REPO"
rm -f "$PRESIGNED_HOME/code.tar.gz"
[ -f "$PRESIGNED_REPO/cloud/farm/presigned_pod.py" ] || fail "presigned_pod.py missing from the code tarball"
[ -e "$PRESIGNED_REPO/assets" ] || [ -L "$PRESIGNED_REPO/assets" ] || ln -s studio/public/assets "$PRESIGNED_REPO/assets"

trap - ERR
log "starting presigned_pod.py"
exec python3 "$PRESIGNED_REPO/cloud/farm/presigned_pod.py" --manifest "$MANIFEST" --work "$PRESIGNED_HOME" \
  --repo "$PRESIGNED_REPO" --blender "$BLENDER" --pod-log "$POD_LOG"
