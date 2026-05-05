# syntax=docker/dockerfile:1.7
###############################################################################
# Phoresis unified container — runs as web (gunicorn), worker (celery worker)
# or scheduler (celery beat) depending on the runtime CMD set in compose.
#
# Build args:
#   TORCH_VARIANT  cpu (default) | cuda
#   PYTHON_VERSION 3.12
#
# CPU build:
#   docker build -f docker/Dockerfile --build-arg TORCH_VARIANT=cpu  -t phoresis-app:cpu  .
# CUDA build (Blackwell sm_120 / RTX 50-series):
#   docker build -f docker/Dockerfile --build-arg TORCH_VARIANT=cuda -t phoresis-app:cuda .
#
# Why a single image (vs the legacy Dockerfile.web + Dockerfile.worker split)?
# web + worker + scheduler share 99% of their dependency tree (Django, Celery,
# torch, scipy, …). Building them as two separate images meant downloading
# and compiling the cu128 torch wheel twice (~3 GB × 2) because BuildKit
# can't dedupe layers across two Dockerfiles with separate COPY contexts.
# A single image cuts build time and bandwidth in half, and Watchtower has
# a single tag to poll. The runtime distinction is just a different CMD
# (gunicorn vs celery worker vs celery beat) plus per-service env flags
# (SKIP_COLLECTSTATIC=1 / SKIP_SEEDS=1 for non-web roles).
###############################################################################

ARG TORCH_VARIANT=cpu
ARG PYTHON_VERSION=3.12

# ============================================================================
# Stage 1: Frontend builder — compile Tailwind CSS bundle.
# Variant-agnostic (Tailwind has nothing to do with CUDA).
# ============================================================================
FROM node:20-bookworm-slim AS frontend
WORKDIR /build

COPY package.json tailwind.config.js postcss.config.js ./
# Tailwind CLI lives in devDependencies, so install full deps here.
RUN npm install --include=dev

COPY src/ ./src/
RUN npm run build:css

# ============================================================================
# Stage 2A: Python deps (CPU variant).
# Debian slim-bookworm ships Python 3.12 in its packages; using the official
# python image saves us the apt-get python3.12 dance.
# ============================================================================
FROM python:${PYTHON_VERSION}-slim-bookworm AS python-cpu
WORKDIR /app
# UV_PROJECT_ENVIRONMENT pins `uv sync` to /opt/venv. Without it, uv sync
# silently creates `.venv` in the project root and installs deps there,
# leaving /opt/venv empty (uv ignores VIRTUAL_ENV in favour of project
# discovery). UV_HTTP_TIMEOUT is bumped because PyPI / NVIDIA CDNs can be
# sluggish for big wheels (esp. behind VPN).
ENV UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv UV_HTTP_TIMEOUT=300

# apt cache mount keeps the package archive between builds — when the apt
# package list above doesn't change, this layer re-uses the cached debs.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev libjpeg-dev zlib1g-dev libtiff-dev \
        libfreetype6-dev liblcms2-dev libwebp-dev libopenjp2-7-dev \
        libgl1 libglib2.0-0 \
        curl ca-certificates

RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
# Single-shot install: `--extra cpu` tells uv to read the [tool.uv.sources]
# mapping in pyproject.toml and pull torch + torchvision from
# download.pytorch.org/whl/cpu (instead of the standard PyPI wheel which is
# ~2x bigger because it bundles CUDA stubs even on CPU). All other packages
# resolve from PyPI as usual.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/venv && \
    uv sync --no-dev --no-install-project --frozen --extra cpu && \
    /opt/venv/bin/python -c "import django, celery, torch; print('django', django.__version__, '/ celery', celery.__version__, '/ torch', torch.__version__, '(cpu)')"

# ============================================================================
# Stage 2B: Python deps (CUDA variant).
# CUDA 12.8 + cu128 PyTorch wheel for Blackwell (sm_120, RTX 50-series) support.
# Ubuntu 24.04 ships Python 3.12 natively — no deadsnakes PPA required.
# ============================================================================
FROM nvidia/cuda:12.8.0-runtime-ubuntu24.04 AS python-cuda
WORKDIR /app
ENV UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv UV_HTTP_TIMEOUT=300 DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev \
        build-essential libpq-dev libjpeg-dev zlib1g-dev libtiff-dev \
        libfreetype6-dev liblcms2-dev libwebp-dev libopenjp2-7-dev \
        libgl1 libglib2.0-0 \
        curl ca-certificates \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python3

RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
# Single-shot install: `--extra cuda` makes uv resolve torch + torchvision
# directly from download.pytorch.org/whl/cu128 thanks to the
# [tool.uv.sources] declarations in pyproject.toml. No more two-step "install
# CPU torch then swap to cu128" hack — saves ~700 MB of redundant download
# per build and keeps the lockfile as the single source of truth (the lock
# pins both torch +cpu and +cu128 variants; uv picks the right one based on
# the active extra).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv --python 3.12 /opt/venv && \
    uv sync --no-dev --no-install-project --frozen --extra cuda && \
    /opt/venv/bin/python -c "import django, celery, torch; print('django', django.__version__, '/ celery', celery.__version__, '/ torch', torch.__version__, '(cuda build; runtime gpu detect skipped in builder)')"

# ============================================================================
# Stage 3: Variant selector.
# ============================================================================
FROM python-${TORCH_VARIANT} AS python-base

# ============================================================================
# Stage 4: Final runtime image — used by web, worker, and scheduler.
# ============================================================================
FROM python-base AS runtime

# Re-declare so this stage can reference the global build arg in ENV below.
ARG TORCH_VARIANT=cpu

ENV DJANGO_SETTINGS_MODULE=phoresis.settings.prod \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH \
    PHORESIS_IMAGE_VARIANT=${TORCH_VARIANT} \
    PYTHONPATH=/app/src
# PYTHONPATH=/app/src so gunicorn (`phoresis.wsgi:application`) and any direct
# Python invocations (celery -A phoresis_core.celery_app …) can import
# `phoresis` and `phoresis_core` without going through manage.py's sys.path
# injection. manage.py still works the same way.

# Non-root user.
# Ubuntu 24.04 (CUDA stage base) ships with a default 'ubuntu' user at UID 1000.
# Remove it first so we can claim UID 1000 for 'phoresis' — keeps host-side
# bind-mount permissions consistent (Windows host UID maps to phoresis inside).
# On the CPU stage (Debian slim-bookworm) the userdel is a no-op.
RUN (userdel -r ubuntu 2>/dev/null || true) && \
    useradd --create-home --shell /bin/bash --uid 1000 phoresis
WORKDIR /app

# App code
COPY --chown=phoresis:phoresis manage.py conftest.py ./
COPY --chown=phoresis:phoresis src/ ./src/
COPY --chown=phoresis:phoresis docker/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --chown=phoresis:phoresis docker/gunicorn.conf.py /etc/gunicorn.conf.py

# Built CSS from Stage 1 (frontend) — present in every variant of the image,
# but only the web container actually serves it (collectstatic + Caddy).
# Worker / scheduler ignore it; the few hundred KB are noise vs the GB-scale
# torch wheels.
COPY --from=frontend --chown=phoresis:phoresis \
    /build/src/phoresis_ui/static/phoresis_ui/css/output.css \
    /app/src/phoresis_ui/static/phoresis_ui/css/output.css

# Mountpoints + entrypoint normalization.
# `sed -i 's/\r$//'` strips Windows CRLF line endings that git on Windows can
# inject (core.autocrlf=true). Without this, Linux reads the shebang as
# `#!/bin/sh\r` and fails with "no such file or directory" on container start.
RUN mkdir -p /srv/staticfiles /srv/media && \
    chown -R phoresis:phoresis /srv/staticfiles /srv/media && \
    sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && \
    chmod +x /usr/local/bin/entrypoint.sh

# Caddy serves static from this path; collectstatic in entrypoint writes here
# (skipped via SKIP_COLLECTSTATIC=1 in worker/scheduler).
ENV STATIC_ROOT=/srv/staticfiles MEDIA_ROOT=/srv/media

USER phoresis
EXPOSE 8000

# No HEALTHCHECK at the image level — both `web` and `worker` declare their
# own service-level healthcheck in docker-compose.yml (web: HTTP probe on
# /healthz/live/, worker: `celery inspect ping`). A single image-level HC
# would fit one role and silently mismatch the other.

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# Default CMD is the web role (gunicorn). Worker/scheduler override `command:`
# in compose — same image, different process.
CMD ["gunicorn", "-c", "/etc/gunicorn.conf.py", "phoresis.wsgi:application"]
