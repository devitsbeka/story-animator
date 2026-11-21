# syntax=docker/dockerfile:1.7
# Blender 4.2 LTS GPU render worker for the story-animator farm.
#
#   build (from the REPO ROOT, so the repo code is in the context):
#     DOCKER_BUILDKIT=1 docker build -f cloud/farm/Dockerfile -t story-farm-worker:$(git rev-parse --short HEAD) .
#   run on a GPU host (what the launch template does):
#     docker run --gpus all -e FARM_BUCKET=... -e FARM_QUEUE_URL=... -e FARM_TABLE=... \
#                -v /cache:/cache story-farm-worker:<tag>
#
# The NVIDIA container toolkit injects the host driver (libcuda, libnvoptix) at run time, so the image needs
# no CUDA toolkit: Blender ships its own precompiled CUDA/OptiX kernels. "graphics" also exposes libEGL_nvidia
# so EEVEE can render headless on the GPU.
FROM nvidia/cuda:12.4.1-base-ubuntu22.04

ARG BLENDER_VERSION=4.2.3
ARG BLENDER_SERIES=4.2
ARG BLENDER_SHA256=3a64efd1982465395abab4259b4091d5c8c56054c7267e9633e4f702a71ea3f4
ARG UID=1000

ENV DEBIAN_FRONTEND=noninteractive \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Blender's runtime libs (X11/GL stubs it links against even in -b mode) + python3 for the worker.
# Unpinned on purpose: take the distro's current security updates at build time.
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl xz-utils python3 python3-pip \
        libx11-6 libxi6 libxxf86vm1 libxfixes3 libxrender1 libxkbcommon0 libsm6 libice6 \
        libgl1 libegl1 libglvnd0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Official Blender tarball, checksum-pinned.
RUN curl -fsSL -o /tmp/blender.tar.xz \
        "https://download.blender.org/release/Blender${BLENDER_SERIES}/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
    && echo "${BLENDER_SHA256}  /tmp/blender.tar.xz" | sha256sum -c - \
    && mkdir -p /opt/blender \
    && tar -xJf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 \
    && rm /tmp/blender.tar.xz \
    && /opt/blender/blender -b --factory-startup --python-expr "import bpy; print('blender', bpy.app.version_string)"

COPY cloud/farm/requirements.txt /tmp/farm-requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/farm-requirements.txt && rm /tmp/farm-requirements.txt

RUN useradd --create-home --uid "${UID}" --shell /usr/sbin/nologin render \
    && mkdir -p /opt/factory /work /cache/library_store \
    && chown -R render:render /opt/factory /work /cache

# Repo code the renderer needs (see Dockerfile.dockerignore for what is excluded).
COPY --chown=render:render cloud/blender /opt/factory/cloud/blender
COPY --chown=render:render cloud/farm /opt/factory/cloud/farm
# assets/ is a symlink to studio/public/assets in the repo: copy the target and recreate the link.
COPY --chown=render:render studio/public/assets /opt/factory/studio/public/assets
RUN ln -s studio/public/assets /opt/factory/assets
COPY --chown=render:render studio/src/data /opt/factory/studio/src/data
COPY --chown=render:render factory/library /opt/factory/factory/library

ENV FARM_REPO=/opt/factory \
    FARM_WORK=/work \
    LIBRARY_STORE=/cache/library_store \
    BLENDER=/opt/blender/blender \
    HEALTH_FILE=/tmp/farm-worker.health

USER ${UID}:${UID}
WORKDIR /opt/factory
VOLUME ["/cache", "/work"]

# Healthy while the worker loop has touched its health file in the last 3 minutes (long first library sync
# is covered by the start period).
HEALTHCHECK --interval=60s --timeout=10s --start-period=900s --retries=3 \
    CMD ["python3", "/opt/factory/cloud/farm/healthcheck.py"]

ENTRYPOINT ["python3", "/opt/factory/cloud/farm/worker.py"]
