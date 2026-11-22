# Blender 4.2 LTS on AWS Lambda (container image, x86_64, CPU Cycles).
#
# Built by AWS CodeBuild in the operator's account (no Docker needed locally):
#   python3 -m factory.compute.aws_lambda.deploy build
# The image holds Blender + the handler only. The repo code, episode spec and library files arrive per chunk
# through presigned GET URLs in the chunk manifest (cached in /tmp across warm invocations), so code changes do
# NOT need an image rebuild, and the function itself holds no AWS data permissions at all.
FROM public.ecr.aws/lambda/python:3.12

ARG BLENDER_VERSION=4.2.3
ARG BLENDER_SERIES=4.2
ARG BLENDER_SHA256=3a64efd1982465395abab4259b4091d5c8c56054c7267e9633e4f702a71ea3f4

# Blender links these X11/GL client libs even in -b (background) mode. Installed one by one so a renamed package
# in a newer AL2023 does not kill the build; the blender smoke test below is the real gate.
RUN set -eux; \
    dnf install -y --setopt=install_weak_deps=0 tar xz gzip findutils; \
    for p in libX11 libXi libXxf86vm libXfixes libXrender libxkbcommon libSM libICE \
             mesa-libGL mesa-libEGL libglvnd-glx libglvnd-egl libgomp; do \
        dnf install -y --setopt=install_weak_deps=0 "$p" || echo "WARN: package $p unavailable"; \
    done; \
    dnf clean all; rm -rf /var/cache/dnf

# The official tarball is staged next to the build source (deploy.py copies it to S3 after checking its sha256;
# download.blender.org refuses CodeBuild's IPs with HTTP 403). Checked again here.
COPY blender.tar.xz /tmp/blender.tar.xz
RUN set -eux; \
    echo "${BLENDER_SHA256}  /tmp/blender.tar.xz" | sha256sum -c -; \
    mkdir -p /opt/blender; \
    tar -xJf /tmp/blender.tar.xz -C /opt/blender --strip-components=1; \
    rm /tmp/blender.tar.xz; \
    (ldd /opt/blender/blender | grep "not found" || true); \
    HOME=/tmp /opt/blender/blender -b --factory-startup \
      --python-expr "import bpy; print('BLENDER_OK', bpy.app.version_string)" | tee /tmp/smoke.txt; \
    grep -q BLENDER_OK /tmp/smoke.txt; rm -f /tmp/smoke.txt

# Lambda's file system is read-only except /tmp: point every Blender/Python cache there.
ENV HOME=/tmp \
    BLENDER=/opt/blender/blender \
    BLENDER_USER_CONFIG=/tmp/blender/config \
    BLENDER_USER_SCRIPTS=/tmp/blender/scripts \
    BLENDER_USER_DATAFILES=/tmp/blender/datafiles \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY handler.py ${LAMBDA_TASK_ROOT}/
CMD ["handler.handler"]
