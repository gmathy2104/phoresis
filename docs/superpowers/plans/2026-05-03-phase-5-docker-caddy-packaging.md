# Phoresis — Phase 5 (Docker + Caddy Packaging) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package Phoresis as a containerized stack runnable via `docker compose up` on Windows 11 + Docker Desktop (WSL2). Six containers — caddy, web, worker, scheduler, redis, watchtower — orchestrated by `docker-compose.yml`, with native Postgres staying on the host. The web image comes in two variants (CPU / CUDA) selected at build time. Caddy serves `https://phoresis/` with `tls internal` (self-signed). Healthchecks gate startup ordering. Tagged `v0.5.0`.

**Architecture (recap from spec §5.1):**

```
HOST (Windows 11)
│
├─ PostgreSQL 17 (native, port 5432)
│
└─ Docker Desktop (WSL2)
   └─ phoresis_compose stack:
      ├─ caddy        :80, :443  ← reverse proxy + TLS internal
      ├─ web          :8000 internal  ← gunicorn 4 workers
      │  └─ host.docker.internal:5432  → native Postgres
      ├─ worker       no port    ← Celery (queues: default, heavy)
      ├─ scheduler    no port    ← Celery Beat
      ├─ redis        :6379 internal  ← broker + cache
      └─ watchtower               ← auto-update phoresis-{web,worker,scheduler}
```

**Tech Stack delta:** No new Python deps. Adds Docker artifacts + Caddyfile. The `/healthz/` and `/healthz/celery/` endpoints are introduced in `phoresis_core` so Caddy and Watchtower have something to gate on. A new `seed_groups` management command formalizes the group-seeding contract that the data migration already satisfies (idempotent — useful for re-seeding after manual deletes and explicit in the `entrypoint.sh`).

**Source repo for ports:** `$DSHUB = C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/`. **Target:** `$PHOR = .../phoresis/.claude/worktrees/hopeful-franklin-e45f1b/`. Source `docker/` directory provides reference patterns; we don't directly port — we write Phoresis's config from scratch since the architecture is materially different (no Azure, no shared lab infra).

---

## Build Order Rationale

1. **Healthz endpoints** (Task 1) — Caddy and Watchtower depend on them; needs to be in place before any compose service can be `service_healthy`-gated.
2. **`seed_groups` command** (Task 2) — entrypoint references it.
3. **docker/ scaffold** (Task 3) — `.dockerignore`, `docker/entrypoint.sh`, gunicorn config; the foundations every Dockerfile pulls in.
4. **Dockerfile.web** (Task 4) — multi-stage (Node CSS build → Python deps → runtime), CPU + CUDA variants via `ARG TORCH_VARIANT`.
5. **Dockerfile.worker** (Task 5) — same pattern, no frontend stage.
6. **Caddyfile** (Task 6) — reverse-proxy + tls internal + static/media file servers.
7. **docker-compose.yml** (Task 7) — full stack including watchtower with `phoresis-only` label scope.
8. **compose.gpu.yml override** (Task 8) — NVIDIA Container Toolkit device reservations.
9. **Hosts entry + smoke + tag v0.5.0** (Task 9) — `127.0.0.1 phoresis`, `docker compose up`, walk `https://phoresis/`, tag.

---

## File Structure (additions to Phase 4)

```
.dockerignore
docker/
├── Caddyfile
├── Dockerfile.web                 # multi-stage, ARG TORCH_VARIANT={cpu,cuda}
├── Dockerfile.worker              # multi-stage, ARG TORCH_VARIANT={cpu,cuda}
├── docker-compose.yml
├── compose.gpu.yml
├── entrypoint.sh                  # runs migrate, collectstatic, seeds — idempotent
└── gunicorn.conf.py

src/accounts/management/commands/
└── seed_groups.py                  # NEW: idempotent (data migration also seeds them; this is the explicit command)

src/phoresis_core/
└── healthz.py                      # NEW: readiness + liveness + celery-only

src/phoresis_core/tests/
└── test_healthz.py                 # NEW

src/phoresis/urls.py                # extended: /healthz/ + /healthz/celery/
```

---

## Task 1: `/healthz/` and `/healthz/celery/` endpoints

**Files:**
- Create: `src/phoresis_core/healthz.py`
- Create: `src/phoresis_core/tests/test_healthz.py`
- Modify: `src/phoresis/urls.py`

The `/healthz/` endpoint composes three subsystem checks: DB, Redis, Celery worker presence. Used by Caddy as the upstream-health probe and by Watchtower for post-update verification.

`/healthz/celery/` is worker-only (cheaper — Caddy can poll it independently for fine-grained worker monitoring without paying the DB+Redis cost).

- [ ] **Step 1: Write the failing test**

Create `src/phoresis_core/tests/test_healthz.py`:

```python
"""Tests for the /healthz/ endpoints."""
from unittest.mock import patch

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_healthz_returns_200_when_all_subsystems_ok(client) -> None:
    """When DB + Redis + Celery all respond, /healthz/ returns 200."""
    with patch("phoresis_core.healthz._celery_alive", return_value=True), \
         patch("phoresis_core.healthz._redis_alive",  return_value=True):
        response = client.get(reverse("healthz"))
    assert response.status_code == 200
    body = response.json()
    assert body["overall"] == "ok"
    assert body["subsystems"]["db"]      == "ok"
    assert body["subsystems"]["redis"]   == "ok"
    assert body["subsystems"]["celery"]  == "ok"


@pytest.mark.django_db
def test_healthz_returns_503_when_redis_down(client) -> None:
    with patch("phoresis_core.healthz._celery_alive", return_value=True), \
         patch("phoresis_core.healthz._redis_alive",  return_value=False):
        response = client.get(reverse("healthz"))
    assert response.status_code == 503
    assert response.json()["overall"] == "error"


@pytest.mark.django_db
def test_healthz_celery_only_returns_200_when_workers_alive(client) -> None:
    with patch("phoresis_core.healthz._celery_alive", return_value=True):
        response = client.get(reverse("healthz_celery"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_healthz_celery_only_returns_503_when_no_workers(client) -> None:
    with patch("phoresis_core.healthz._celery_alive", return_value=False):
        response = client.get(reverse("healthz_celery"))
    assert response.status_code == 503
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_core/tests/test_healthz.py -v
```
Expected: FAIL with `NoReverseMatch: 'healthz' is not a registered namespace`.

- [ ] **Step 3: Create `src/phoresis_core/healthz.py`**

```python
"""Healthcheck endpoints for Phoresis.

- /healthz/         readiness: DB + Redis + Celery (200 when all ok, 503 if DB or Redis down,
                                                    200 'degraded' if only Celery down)
- /healthz/celery/  worker-only liveness (200 if at least one worker responds, 503 otherwise)

Used by:
- Caddy upstream health-check (Phase 5 docker-compose)
- Watchtower post-update verification (Phase 6)
- /admin/system/ dashboard (post-v1 nice-to-have)
"""
from __future__ import annotations

from django.db import connections
from django.db.utils import OperationalError
from django.http import HttpRequest, JsonResponse


def _db_alive() -> bool:
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except OperationalError:
        return False
    except Exception:
        return False


def _redis_alive() -> bool:
    try:
        from django_redis import get_redis_connection
        get_redis_connection("default").ping()
        return True
    except Exception:
        return False


def _celery_alive() -> bool:
    try:
        from phoresis_core.celery_app import app
        # `inspect().ping()` returns a dict {worker_name: {'ok': 'pong'}} per responding worker
        # or None if the broker is unreachable / no workers respond within the timeout.
        result = app.control.inspect(timeout=1).ping()
        return bool(result)
    except Exception:
        return False


def readiness(request: HttpRequest) -> JsonResponse:
    """Composite readiness probe — DB + Redis + Celery."""
    db_ok = _db_alive()
    redis_ok = _redis_alive()
    celery_ok = _celery_alive()

    subsystems = {
        "db":     "ok" if db_ok else "error",
        "redis":  "ok" if redis_ok else "error",
        "celery": "ok" if celery_ok else "no workers",
    }

    if not (db_ok and redis_ok):
        # Hard fail — request handling not viable
        overall, status = "error", 503
    elif not celery_ok:
        # Degraded but request handling still works for sync flows
        overall, status = "degraded", 200
    else:
        overall, status = "ok", 200

    return JsonResponse({"overall": overall, "subsystems": subsystems}, status=status)


def celery_only(request: HttpRequest) -> JsonResponse:
    """Cheap worker-only liveness — used by Caddy and the admin dashboard."""
    if _celery_alive():
        return JsonResponse({"status": "ok"}, status=200)
    return JsonResponse({"status": "down"}, status=503)


def liveness(request: HttpRequest) -> JsonResponse:
    """Static liveness probe — process is up, no DB/Redis/Celery touched.

    Used by container orchestrators (Docker `HEALTHCHECK`) to distinguish
    'process alive' from 'fully ready to serve'. Always 200 unless the WSGI
    server itself is wedged (in which case the response never reaches us).
    """
    return JsonResponse({"status": "alive"}, status=200)
```

- [ ] **Step 4: Wire URLs**

Edit `src/phoresis/urls.py`:

```python
"""Root URLconf for the Phoresis project."""
from django.contrib import admin
from django.urls import include, path

from phoresis_core import healthz

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include(("accounts.urls", "accounts"), namespace="accounts")),
    path("",         include(("gel_analyzer.urls", "gel_analyzer"), namespace="gel_analyzer")),
    path("healthz/",        healthz.readiness,    name="healthz"),
    path("healthz/celery/", healthz.celery_only,  name="healthz_celery"),
    path("healthz/live/",   healthz.liveness,     name="healthz_live"),
    path("",         include(("dashboard.urls", "dashboard"), namespace="dashboard")),
]
```

(`/healthz/live/` is the Docker `HEALTHCHECK` target — cheap and deterministic.)

- [ ] **Step 5: Run tests**

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_core/tests/test_healthz.py -v
```
Expected: 4 tests pass.

- [ ] **Step 6: Hit it from runserver as a smoke**

```bash
.venv/Scripts/python.exe manage.py runserver 0.0.0.0:8000
```
In another terminal:
```bash
curl -i http://127.0.0.1:8000/healthz/
```
Expected: depending on whether your local Redis/Celery are running:
- DB up + Redis up + Celery up → 200, `{"overall":"ok",...}`
- DB up + Redis down → 503, `{"overall":"error",...}`
- DB up + Redis up + Celery down → 200, `{"overall":"degraded","subsystems":{"celery":"no workers",...}}`

```bash
curl -i http://127.0.0.1:8000/healthz/live/
```
Expected: 200, `{"status":"alive"}` always.

- [ ] **Step 7: Commit**

```bash
git add src/phoresis_core/healthz.py src/phoresis_core/tests/test_healthz.py src/phoresis/urls.py
git commit -m "feat(phoresis_core): add /healthz/ readiness + /healthz/celery/ + /healthz/live/ probes"
```

---

## Task 2: `seed_groups` management command

**Files:**
- Create: `src/accounts/management/__init__.py`
- Create: `src/accounts/management/commands/__init__.py`
- Create: `src/accounts/management/commands/seed_groups.py`
- Create: `src/accounts/tests/test_seed_groups_command.py`

The data migration `accounts/0002_seed_groups.py` already creates the three groups when migrations run. The dedicated command makes the seeding intent explicit in `entrypoint.sh` and gives operators an idempotent re-seed path if the groups are ever manually deleted.

- [ ] **Step 1: Write the failing test**

Create `src/accounts/tests/test_seed_groups_command.py`:

```python
"""Tests for the seed_groups management command."""
import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command

from accounts.permissions import GROUP_ADMIN, GROUP_LAB_USER, GROUP_REVIEWER


@pytest.mark.django_db
def test_seed_groups_command_creates_three_groups() -> None:
    Group.objects.all().delete()  # ensure clean slate
    call_command("seed_groups")
    names = set(Group.objects.values_list("name", flat=True))
    assert {GROUP_LAB_USER, GROUP_REVIEWER, GROUP_ADMIN}.issubset(names)


@pytest.mark.django_db
def test_seed_groups_command_is_idempotent() -> None:
    call_command("seed_groups")
    count = Group.objects.filter(name__in=[GROUP_LAB_USER, GROUP_REVIEWER, GROUP_ADMIN]).count()
    call_command("seed_groups")
    assert Group.objects.filter(name__in=[GROUP_LAB_USER, GROUP_REVIEWER, GROUP_ADMIN]).count() == count
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest src/accounts/tests/test_seed_groups_command.py -v
```
Expected: FAIL — `Unknown command: 'seed_groups'`.

- [ ] **Step 3: Create the command structure**

```bash
mkdir -p src/accounts/management/commands
touch src/accounts/management/__init__.py src/accounts/management/commands/__init__.py
```

- [ ] **Step 4: Create `seed_groups.py`**

```python
"""Idempotent seed for the three Phoresis groups.

Phase 1's data migration `0002_seed_groups` already creates the rows on
fresh databases; this command makes the contract explicit in scripted
contexts (entrypoint.sh, install.ps1) and lets operators re-seed after
manual cleanup without re-running migrations.
"""
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.permissions import ALL_GROUPS


class Command(BaseCommand):
    help = "Create the three Phoresis groups (Lab User, Reviewer, Admin) — idempotent."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        for name in ALL_GROUPS:
            _, created = Group.objects.get_or_create(name=name)
            verb = "created" if created else "exists"
            self.stdout.write(f"  {name}: {verb}")
        self.stdout.write(self.style.SUCCESS(f"{len(ALL_GROUPS)} groups ready"))
```

- [ ] **Step 5: Run the test**

```bash
.venv/Scripts/python.exe -m pytest src/accounts/tests/test_seed_groups_command.py -v
```
Expected: 2 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/accounts/management/ src/accounts/tests/test_seed_groups_command.py
git commit -m "feat(accounts): add seed_groups management command (idempotent re-seed of the 3 groups)"
```

---

## Task 3: Docker scaffolding — .dockerignore, entrypoint.sh, gunicorn config

**Files:**
- Create: `.dockerignore`
- Create: `docker/entrypoint.sh`
- Create: `docker/gunicorn.conf.py`

- [ ] **Step 1: Create `.dockerignore`**

```
# Version control
.git/
.gitignore
.gitattributes

# Worktrees and Claude artifacts
.claude/

# Python build / cache
__pycache__/
*.py[cod]
*.egg-info/
.eggs/
.venv/
venv/
.python-version

# Tests / coverage
.pytest_cache/
.coverage
.coverage.*
htmlcov/
coverage.xml
.mypy_cache/
.ruff_cache/

# Node
node_modules/

# Generated CSS (rebuilt in image)
src/phoresis_ui/static/phoresis_ui/css/output.css
src/phoresis_ui/static/phoresis_ui/css/output.css.map

# Docs / specs (not needed in runtime image)
docs/

# Local env files
.env
.env.local
.env.*.local

# IDE
.idea/
.vscode/
*.swp

# Django local
db.sqlite3
db.sqlite3-journal
media/
staticfiles/
local_settings.py
logs/

# Test fixtures (heavy gel images aren't shipped in runtime image)
src/gel_analyzer/tests/data/

# OS
.DS_Store
Thumbs.db

# Build outputs
dist/
build/
*.tar.gz
```

- [ ] **Step 2: Create `docker/entrypoint.sh`**

```sh
#!/bin/sh
# Phoresis web/worker container entrypoint.
#
# Idempotent — safe to run on every container start. Run order matches
# spec section 10.3:
#   1. migrate           — applies pending schema + data migrations
#   2. collectstatic     — produces /srv/staticfiles for Caddy to serve
#   3. seed_groups       — idempotent (no-op after migrate; re-seeds if dropped)
#   4. seed_ladder_templates --skip-existing
#   5. create_initial_users --from-env --skip-existing
#   6. exec "$@"         — hands off to the per-container CMD (gunicorn / celery)
#
# Web container needs steps 1-5; worker / scheduler need ONLY 1 (migrate is
# safe & necessary because the worker imports the same models). The compose
# file passes `SKIP_COLLECTSTATIC=1` and `SKIP_SEEDS=1` to worker/scheduler
# to short-circuit those phases.

set -e

cd /app

echo "==> [entrypoint] migrate"
python manage.py migrate --noinput

if [ "${SKIP_COLLECTSTATIC:-0}" != "1" ]; then
    echo "==> [entrypoint] collectstatic"
    python manage.py collectstatic --noinput --clear
fi

if [ "${SKIP_SEEDS:-0}" != "1" ]; then
    echo "==> [entrypoint] seed_groups"
    python manage.py seed_groups

    echo "==> [entrypoint] seed_ladder_templates"
    python manage.py seed_ladder_templates --skip-existing || \
        echo "    (seed_ladder_templates not idempotent on this DB — continuing)"

    echo "==> [entrypoint] create_initial_users"
    python manage.py create_initial_users --from-env --skip-existing || \
        echo "    (no initial users env vars set — skipping)"
fi

echo "==> [entrypoint] exec $@"
exec "$@"
```

Make it executable:
```bash
chmod +x docker/entrypoint.sh
```

(On Windows, `chmod` is a no-op but git tracks the executable bit via `core.fileMode` — confirm with `git update-index --chmod=+x docker/entrypoint.sh` after staging.)

- [ ] **Step 3: Create `docker/gunicorn.conf.py`**

```python
"""Gunicorn config for the Phoresis web container."""
import multiprocessing
import os

# Bind to the internal port; Caddy proxies in.
bind = f"0.0.0.0:{os.environ.get('GUNICORN_PORT', '8000')}"

# 4 sync workers per spec §5.1; can be tuned via env.
workers = int(os.environ.get("GUNICORN_WORKERS", "4"))
worker_class = "sync"
threads = int(os.environ.get("GUNICORN_THREADS", "2"))

# Timeout — gel image processing on upload can take ~10s on big files; default 30s is tight.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 5

# Logging — to stdout/stderr so Docker captures (loguru's InterceptHandler keeps the format consistent).
accesslog = "-"
errorlog = "-"
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)ss'

# Reload disabled in production.
reload = False

# Preload reduces per-worker memory by sharing the import graph (loguru, torch, etc.).
preload_app = True
```

- [ ] **Step 4: Commit**

```bash
git add .dockerignore docker/entrypoint.sh docker/gunicorn.conf.py
git update-index --chmod=+x docker/entrypoint.sh
git commit -m "feat(docker): add .dockerignore, entrypoint.sh (idempotent migrate/seeds), gunicorn.conf"
```

---

## Task 4: `Dockerfile.web` — multi-stage with CPU + CUDA variants

**Files:**
- Create: `docker/Dockerfile.web`

> **Variant strategy:** A single Dockerfile with `ARG TORCH_VARIANT={cpu,cuda}` switches the base image, the torch wheel index, and (in CUDA mode) installs Python 3.12 from deadsnakes since the NVIDIA CUDA images don't ship Python.

- [ ] **Step 1: Create `docker/Dockerfile.web`**

```dockerfile
# syntax=docker/dockerfile:1.7
###############################################################################
# Phoresis web container — multi-stage build with CPU/CUDA variants.
#
# Build args:
#   TORCH_VARIANT  cpu (default) | cuda
#   PYTHON_VERSION 3.12 (default)
#
# CPU build:
#   docker build -f docker/Dockerfile.web --build-arg TORCH_VARIANT=cpu  -t phoresis-web:cpu  .
# CUDA build:
#   docker build -f docker/Dockerfile.web --build-arg TORCH_VARIANT=cuda -t phoresis-web:cuda .
###############################################################################

ARG TORCH_VARIANT=cpu
ARG PYTHON_VERSION=3.12

# ============================================================================
# Stage 1: Frontend builder — compile Tailwind CSS bundle.
# ============================================================================
FROM node:20-bookworm-slim AS frontend
WORKDIR /build

COPY package.json tailwind.config.js postcss.config.js ./
RUN npm install --omit=dev

COPY src/ ./src/
RUN npx tailwindcss \
    -i src/phoresis_ui/static/phoresis_ui/css/input.css \
    -o src/phoresis_ui/static/phoresis_ui/css/output.css \
    --minify

# ============================================================================
# Stage 2A: Python deps (CPU variant).
# ============================================================================
FROM python:${PYTHON_VERSION}-slim-bookworm AS python-cpu
WORKDIR /app
ENV UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev libjpeg-dev zlib1g-dev libtiff-dev \
        libfreetype6-dev liblcms2-dev libwebp-dev libopenjp2-7-dev \
        libgl1 libglib2.0-0 \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

COPY pyproject.toml ./
RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install --extra-index-url https://download.pytorch.org/whl/cpu \
        --no-cache --requirement <(uv pip compile pyproject.toml --extra dev=false 2>/dev/null || \
            uv pip install -r <(grep -E '^\s*"' pyproject.toml | tr -d '",' | xargs -I{} echo {}) || true) || true

# Simpler approach — just `uv sync` against the project, no dev extras:
RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

# ============================================================================
# Stage 2B: Python deps (CUDA variant).
# ============================================================================
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04 AS python-cuda
WORKDIR /app
ENV UV_LINK_MODE=copy DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common curl ca-certificates gnupg \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev \
        build-essential libpq-dev libjpeg-dev zlib1g-dev libtiff-dev \
        libfreetype6-dev liblcms2-dev libwebp-dev libopenjp2-7-dev \
        libgl1 libglib2.0-0 \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python3 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

COPY pyproject.toml ./
RUN uv venv --python 3.12 /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install --extra-index-url https://download.pytorch.org/whl/cu121 \
        torch torchvision && \
    uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

# ============================================================================
# Stage 3: Variant selector.
# ============================================================================
FROM python-${TORCH_VARIANT} AS python-base

# ============================================================================
# Stage 4: Final runtime image.
# ============================================================================
FROM python-base AS runtime

ENV DJANGO_SETTINGS_MODULE=phoresis.settings.prod \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH \
    PHORESIS_IMAGE_VARIANT=${TORCH_VARIANT}

# Non-root user
RUN useradd --create-home --shell /bin/bash --uid 1000 phoresis
WORKDIR /app

# App code
COPY --chown=phoresis:phoresis manage.py conftest.py ./
COPY --chown=phoresis:phoresis src/ ./src/
COPY --chown=phoresis:phoresis docker/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --chown=phoresis:phoresis docker/gunicorn.conf.py /etc/gunicorn.conf.py

# Built CSS from Stage 1
COPY --from=frontend --chown=phoresis:phoresis \
    /build/src/phoresis_ui/static/phoresis_ui/css/output.css \
    /app/src/phoresis_ui/static/phoresis_ui/css/output.css

# Static + media volume mountpoints
RUN mkdir -p /srv/staticfiles /srv/media && \
    chown -R phoresis:phoresis /srv/staticfiles /srv/media && \
    chmod +x /usr/local/bin/entrypoint.sh

# Caddy serves static from this path; collectstatic in entrypoint writes here.
ENV STATIC_ROOT=/srv/staticfiles MEDIA_ROOT=/srv/media

USER phoresis
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz/live/', timeout=3).status == 200 else 1)"

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["gunicorn", "-c", "/etc/gunicorn.conf.py", "phoresis.wsgi:application"]
```

> **About the `uv sync --frozen 2>/dev/null || uv sync` fallback:** if `uv.lock` isn't committed (it's gitignored in Phase 1), the `--frozen` invocation fails and we fall back to a fresh resolve. Phase 6 will commit `uv.lock` to harden this for production builds.

- [ ] **Step 2: Build the CPU image (smoke)**

```bash
docker build -f docker/Dockerfile.web --build-arg TORCH_VARIANT=cpu -t phoresis-web:cpu-test .
```
Expected: ~5-15 minutes on first build (downloads torch CPU ~700 MB). Subsequent builds use Docker layer cache.

If the build fails at `uv sync` because of a Python version mismatch, double-check the base image's Python version matches `requires-python = ">=3.12"` in `pyproject.toml`.

- [ ] **Step 3: (Optional) Build the CUDA image** — only if NVIDIA + Docker Desktop GPU support are available

```bash
docker build -f docker/Dockerfile.web --build-arg TORCH_VARIANT=cuda -t phoresis-web:cuda-test .
```
Expected: ~10-30 minutes (downloads torch+cu121 ~2 GB plus CUDA runtime). Skip if no GPU access.

- [ ] **Step 4: Smoke-run the CPU image**

```bash
docker run --rm phoresis-web:cpu-test python -c "import django, torch; print(django.get_version(), torch.__version__)"
```
Expected: `5.2.x 2.x.x+cpu` (the `+cpu` suffix confirms CPU-only torch).

- [ ] **Step 5: Commit**

```bash
git add docker/Dockerfile.web
git commit -m "feat(docker): add multi-stage Dockerfile.web (CPU + CUDA variants via TORCH_VARIANT)"
```

---

## Task 5: `Dockerfile.worker`

**Files:**
- Create: `docker/Dockerfile.worker`

The worker image differs from web by:
1. No frontend builder stage (no static assets in worker container).
2. CMD launches Celery instead of gunicorn.
3. `SKIP_COLLECTSTATIC=1` and `SKIP_SEEDS=1` are passed via compose (worker just needs `migrate`).

- [ ] **Step 1: Create `docker/Dockerfile.worker`**

```dockerfile
# syntax=docker/dockerfile:1.7
###############################################################################
# Phoresis worker container — Celery worker (queues: default, heavy)
# and Celery beat (scheduler), CPU/CUDA variants.
###############################################################################

ARG TORCH_VARIANT=cpu
ARG PYTHON_VERSION=3.12

# ============================================================================
# Stage A: Python deps (CPU). Identical pattern to Dockerfile.web's python-cpu.
# ============================================================================
FROM python:${PYTHON_VERSION}-slim-bookworm AS python-cpu
WORKDIR /app
ENV UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev libjpeg-dev zlib1g-dev libtiff-dev \
        libfreetype6-dev liblcms2-dev libwebp-dev libopenjp2-7-dev \
        libgl1 libglib2.0-0 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

COPY pyproject.toml ./
RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

# ============================================================================
# Stage B: Python deps (CUDA). Same as Dockerfile.web's python-cuda.
# ============================================================================
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04 AS python-cuda
WORKDIR /app
ENV UV_LINK_MODE=copy DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common curl ca-certificates gnupg \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev \
        build-essential libpq-dev libjpeg-dev zlib1g-dev libtiff-dev \
        libfreetype6-dev liblcms2-dev libwebp-dev libopenjp2-7-dev \
        libgl1 libglib2.0-0 \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python3 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

COPY pyproject.toml ./
RUN uv venv --python 3.12 /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install --extra-index-url https://download.pytorch.org/whl/cu121 torch torchvision && \
    uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

# ============================================================================
# Stage selector + runtime
# ============================================================================
FROM python-${TORCH_VARIANT} AS runtime

ENV DJANGO_SETTINGS_MODULE=phoresis.settings.prod \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH \
    PHORESIS_IMAGE_VARIANT=${TORCH_VARIANT} \
    SKIP_COLLECTSTATIC=1 \
    SKIP_SEEDS=1

RUN useradd --create-home --shell /bin/bash --uid 1000 phoresis
WORKDIR /app

COPY --chown=phoresis:phoresis manage.py ./
COPY --chown=phoresis:phoresis src/ ./src/
COPY --chown=phoresis:phoresis docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN mkdir -p /srv/media && chown -R phoresis:phoresis /srv/media && chmod +x /usr/local/bin/entrypoint.sh

ENV MEDIA_ROOT=/srv/media

USER phoresis

# Celery worker doesn't have a meaningful HTTP healthcheck — use `celery inspect ping` via shell.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD celery -A phoresis_core.celery_app inspect ping --timeout 3 || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["celery", "-A", "phoresis_core.celery_app", "worker", "--loglevel=info", "-Q", "default,heavy", "--concurrency=2"]
```

- [ ] **Step 2: Build CPU worker image**

```bash
docker build -f docker/Dockerfile.worker --build-arg TORCH_VARIANT=cpu -t phoresis-worker:cpu-test .
```
Expected: similar timing to web (most layers cached from Task 4). Smaller final image (~1.5 GB vs web's ~2 GB) since no frontend stage.

- [ ] **Step 3: Smoke-run the worker (without broker — should fail healthcheck but at least the binary launches)**

```bash
docker run --rm phoresis-worker:cpu-test celery --version
```
Expected: prints celery version.

- [ ] **Step 4: Commit**

```bash
git add docker/Dockerfile.worker
git commit -m "feat(docker): add multi-stage Dockerfile.worker (Celery worker/beat, CPU + CUDA)"
```

---

## Task 6: Caddyfile

**Files:**
- Create: `docker/Caddyfile`

- [ ] **Step 1: Create the Caddyfile**

Verbatim from spec §9.2 with one addition (healthz upstream check tuning):

```caddy
{
    # Global options — none needed for laptop install. Phase 6 may add `email`
    # if/when external CAs ever get used.
}

phoresis {
    tls internal {
        # Caddy's built-in CA — first request triggers a self-signed cert.
        # User accepts it once in the browser; install.ps1 (Phase 6) automates
        # trusting it via certutil for a friction-free experience.
    }

    encode gzip zstd

    header {
        # Strict-Transport-Security: 1 year HSTS — only in effect for `phoresis`,
        # not the localhost upstream so dev tools remain usable.
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy strict-origin-when-cross-origin
        # Hide upstream identification.
        -Server
    }

    # Static files served directly by Caddy (collectstatic writes here).
    handle_path /static/* {
        root * /srv/staticfiles
        file_server {
            precompressed gzip
        }
    }

    # User-uploaded media (gel images, thumbnails) — also served directly.
    handle_path /media/* {
        root * /srv/media
        file_server
    }

    # Reverse-proxy everything else to gunicorn.
    reverse_proxy web:8000 {
        # Use /healthz/live/ — cheap (no DB/Redis touch) and stable on every boot.
        health_uri /healthz/live/
        health_interval 10s
        health_timeout 5s
        health_status 200

        # Forward client info so loguru's `client_ip` field stays accurate.
        header_up X-Forwarded-Proto https
        header_up X-Real-IP {remote_host}
    }
}

# Catch-all for HTTP -> HTTPS redirect on any other host header.
:80 {
    redir https://phoresis{uri} permanent
}
```

- [ ] **Step 2: Validate the syntax with the Caddy CLI (optional, requires Caddy installed locally)**

```bash
caddy validate --config docker/Caddyfile --adapter caddyfile
```
Expected: `Valid configuration`. Skip if Caddy isn't installed locally — `docker compose up` will surface syntax errors at startup.

- [ ] **Step 3: Commit**

```bash
git add docker/Caddyfile
git commit -m "feat(docker): add Caddyfile (tls internal, static/media file servers, /healthz/live/ upstream check)"
```

---

## Task 7: `docker-compose.yml` — full stack

**Files:**
- Create: `docker/docker-compose.yml`

- [ ] **Step 1: Create the compose file**

```yaml
# Phoresis — local laptop deployment stack (Phase 5).
#
# Postgres is intentionally NOT in here — it stays native on the Windows host
# (per spec §9.1) so `docker compose down -v` can never wipe user data.
# Containers reach it via host.docker.internal:5432.

name: phoresis

services:

  # ────────────────────── reverse proxy + TLS ──────────────────────
  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - phoresis_staticfiles:/srv/staticfiles:ro
      - phoresis_media:/srv/media:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      web:
        condition: service_healthy
    networks: [phoresis_net]
    labels:
      com.centurylinklabs.watchtower.enable: "false"   # Caddy not auto-updated by Watchtower

  # ────────────────────── Django web ──────────────────────
  web:
    image: ${PHORESIS_WEB_IMAGE:-ghcr.io/gmathy2104/phoresis-web:latest-${PHORESIS_IMAGE_VARIANT:-cpu}}
    restart: unless-stopped
    env_file: ../.env
    environment:
      DJANGO_SETTINGS_MODULE: phoresis.settings.prod
      DB_HOST: host.docker.internal
      REDIS_HOST: redis
      GUNICORN_WORKERS: 4
    volumes:
      - phoresis_staticfiles:/srv/staticfiles
      - phoresis_media:/srv/media
    depends_on:
      redis:
        condition: service_healthy
    extra_hosts:
      - "host.docker.internal:host-gateway"
    networks: [phoresis_net]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz/live/', timeout=3).status==200 else 1)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 60s
    labels:
      com.centurylinklabs.watchtower.enable: "true"

  # ────────────────────── Celery worker ──────────────────────
  worker:
    image: ${PHORESIS_WORKER_IMAGE:-ghcr.io/gmathy2104/phoresis-worker:latest-${PHORESIS_IMAGE_VARIANT:-cpu}}
    restart: unless-stopped
    env_file: ../.env
    environment:
      DJANGO_SETTINGS_MODULE: phoresis.settings.prod
      DB_HOST: host.docker.internal
      REDIS_HOST: redis
      SKIP_COLLECTSTATIC: "1"
      SKIP_SEEDS: "1"
    volumes:
      - phoresis_media:/srv/media
    depends_on:
      redis:
        condition: service_healthy
      web:
        condition: service_healthy   # ensures migrations are done before worker starts
    extra_hosts:
      - "host.docker.internal:host-gateway"
    networks: [phoresis_net]
    command: ["celery", "-A", "phoresis_core.celery_app", "worker", "--loglevel=info", "-Q", "default,heavy", "--concurrency=2"]
    labels:
      com.centurylinklabs.watchtower.enable: "true"

  # ────────────────────── Celery beat (scheduler) ──────────────────────
  scheduler:
    image: ${PHORESIS_WORKER_IMAGE:-ghcr.io/gmathy2104/phoresis-worker:latest-${PHORESIS_IMAGE_VARIANT:-cpu}}
    restart: unless-stopped
    env_file: ../.env
    environment:
      DJANGO_SETTINGS_MODULE: phoresis.settings.prod
      DB_HOST: host.docker.internal
      REDIS_HOST: redis
      SKIP_COLLECTSTATIC: "1"
      SKIP_SEEDS: "1"
    depends_on:
      redis:
        condition: service_healthy
      web:
        condition: service_healthy
    extra_hosts:
      - "host.docker.internal:host-gateway"
    networks: [phoresis_net]
    command: ["celery", "-A", "phoresis_core.celery_app", "beat", "--loglevel=info"]
    labels:
      com.centurylinklabs.watchtower.enable: "true"

  # ────────────────────── Redis (broker + cache) ──────────────────────
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes", "--save", "60", "1000"]
    volumes:
      - phoresis_redis:/data
    networks: [phoresis_net]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    labels:
      com.centurylinklabs.watchtower.enable: "false"

  # ────────────────────── Watchtower (auto-update) ──────────────────────
  # Per spec §10.2 — pulls new images at 03:00 daily and restarts only the
  # containers labelled `watchtower.enable=true` (web, worker, scheduler).
  # Phase 6 will harden the credentials story and the notification URL.
  watchtower:
    image: containrrr/watchtower:1.7
    restart: unless-stopped
    environment:
      WATCHTOWER_LABEL_ENABLE: "true"
      WATCHTOWER_CLEANUP: "true"           # remove old images
      WATCHTOWER_INCLUDE_RESTARTING: "true"
      WATCHTOWER_SCHEDULE: "0 0 3 * * *"   # 03:00 daily
      WATCHTOWER_NOTIFICATION_URL: "${WATCHTOWER_NOTIFICATION_URL:-}"
      TZ: "${TZ:-Europe/Brussels}"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    networks: [phoresis_net]

networks:
  phoresis_net:
    driver: bridge

volumes:
  phoresis_staticfiles:
  phoresis_media:
  phoresis_redis:
  caddy_data:
  caddy_config:
```

- [ ] **Step 2: Validate compose syntax**

```bash
docker compose -f docker/docker-compose.yml config --quiet
```
Expected: no output (syntax valid). If `--quiet` rejects something, output the parsed config:
```bash
docker compose -f docker/docker-compose.yml config
```

- [ ] **Step 3: Commit**

```bash
git add docker/docker-compose.yml
git commit -m "feat(docker): add docker-compose.yml (caddy + web + worker + scheduler + redis + watchtower)"
```

---

## Task 8: `compose.gpu.yml` override (NVIDIA Container Toolkit)

**Files:**
- Create: `docker/compose.gpu.yml`

When the user opts into the CUDA variant, this override layers GPU device reservations onto the `web` and `worker` services. Activated with `docker compose -f docker/docker-compose.yml -f docker/compose.gpu.yml up -d`.

- [ ] **Step 1: Create `docker/compose.gpu.yml`**

```yaml
# Phoresis — GPU override.
#
# Activate with:
#   docker compose -f docker/docker-compose.yml -f docker/compose.gpu.yml up -d
#
# Requirements:
# - Docker Desktop >= 4.16 (Windows)
# - WSL2 backend
# - NVIDIA Container Toolkit installed in WSL2 distro
# - PHORESIS_IMAGE_VARIANT=cuda set in .env so the *-cuda image tags are pulled
#
# `runtime: nvidia` and `deploy.resources.reservations.devices` are equivalent
# in modern Compose; we use the latter (Compose Spec 2024).

services:

  web:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1                # all visible GPUs; or `count: all`
              capabilities: ["gpu"]

  worker:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: ["gpu"]
```

- [ ] **Step 2: Validate the merged compose**

```bash
docker compose -f docker/docker-compose.yml -f docker/compose.gpu.yml config --quiet
```
Expected: no output. If `deploy.resources.reservations.devices` triggers a Compose v2 vs v3 warning, ignore — it's supported.

- [ ] **Step 3: Commit**

```bash
git add docker/compose.gpu.yml
git commit -m "feat(docker): add compose.gpu.yml override for NVIDIA Container Toolkit"
```

---

## Task 9: Hosts entry + local end-to-end smoke + tag v0.5.0

**Files:**
- (Manual) `C:\Windows\System32\drivers\etc\hosts`
- (Manual) Optional: `.env` for local testing
- No new committed files in this task — just verification.

> **Note:** Editing the hosts file requires admin rights. The Phase 6 `install.ps1` will automate this; Phase 5's smoke does it manually so we can validate the stack now.

- [ ] **Step 1: Add a hosts entry**

Open PowerShell **as Administrator**:
```powershell
Add-Content -Path "$env:windir\System32\drivers\etc\hosts" -Value "`n127.0.0.1`tphoresis"
ipconfig /flushdns
```
Verify:
```bash
ping -n 1 phoresis
```
Expected: replies from `127.0.0.1`.

- [ ] **Step 2: Provision native Postgres + create DB if not done already**

If the user hasn't set up Postgres locally yet:
```powershell
winget install -e --id PostgreSQL.PostgreSQL.17
# After install, set a password for `postgres`, then:
psql -U postgres -c "CREATE USER phoresis WITH PASSWORD 'phoresis' SUPERUSER;"
psql -U postgres -c "CREATE DATABASE phoresis OWNER phoresis;"
```
(Skip if already done — Phase 1 Task 4 step 11 walked through this.)

- [ ] **Step 3: Create a local `.env` at the worktree root**

Copy `.env.example` → `.env` and fill in real values for local testing:

```bash
cp .env.example .env
```

Edit `.env`:
```dotenv
DJANGO_SETTINGS_MODULE=phoresis.settings.prod
DJANGO_SECRET_KEY=local-test-secret-not-for-production
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=phoresis,localhost,127.0.0.1

DB_NAME=phoresis
DB_USER=phoresis
DB_PASSWORD=phoresis
DB_PORT=5432
# DB_HOST is overridden by docker-compose to host.docker.internal — no need to set here

REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB_CELERY=0
REDIS_DB_CACHE=1

ADMIN_EMAIL=admin@phoresis.local
ADMIN_PASSWORD=local-admin-pwd
PRIMARY_USER_EMAIL=lab@phoresis.local
PRIMARY_USER_PASSWORD=local-lab-pwd
PRIMARY_USER_FULL_NAME=Local Lab User

PHORESIS_IMAGE_VARIANT=cpu

# Override images to use the locally-built test tags (Phase 5 only — Phase 6 wires ghcr)
PHORESIS_WEB_IMAGE=phoresis-web:cpu-test
PHORESIS_WORKER_IMAGE=phoresis-worker:cpu-test
```

- [ ] **Step 4: Bring up the stack**

```bash
docker compose -f docker/docker-compose.yml --env-file .env up -d
docker compose -f docker/docker-compose.yml ps
```
Expected: all services healthy within ~90s. `caddy`, `web`, `worker`, `scheduler`, `redis`, `watchtower` all `running`.

If any service is `unhealthy`:
```bash
docker compose -f docker/docker-compose.yml logs <service-name>
```

Common issues:
- **`web` can't reach Postgres:** the host's Postgres needs to listen on `0.0.0.0` or at least allow connections from the Docker bridge subnet. Edit `postgresql.conf` (`listen_addresses = '*'`) and `pg_hba.conf` (add `host all all 172.16.0.0/12 md5`), restart Postgres.
- **`web` migrate fails on `accounts.0001`:** stale `phoresis` DB from earlier phases. Drop and recreate: `psql -U postgres -c "DROP DATABASE phoresis; CREATE DATABASE phoresis OWNER phoresis;"`.
- **Caddy reports `web upstream unhealthy`:** the `/healthz/live/` URL hasn't routed yet — confirm Task 1's URL wiring lands.

- [ ] **Step 5: Hit `https://phoresis/`**

Open a browser to `https://phoresis/`. Expected: Caddy's TLS-internal cert prompts a security warning the first time. Accept it — subsequent visits are clean. Page should redirect to `/accounts/login/` and show the Phoresis login.

```bash
curl -k https://phoresis/healthz/
```
Expected: `{"overall":"ok","subsystems":{"db":"ok","redis":"ok","celery":"ok"}}`.

```bash
curl -k -L -o /dev/null -w "%{http_code}\n" https://phoresis/
```
Expected: `200` (after redirect to login).

- [ ] **Step 6: Sign in with the seeded primary user**

In the browser:
- Username: `lab` (extracted from PRIMARY_USER_EMAIL by `create_initial_users`)
- Password: `local-lab-pwd`

Verify:
- Dashboard loads, KPI cards render (will show 0s — empty DB).
- Sidebar links work.
- Theme switch works.

- [ ] **Step 7: Run a Celery task end-to-end**

In another terminal:
```bash
docker compose -f docker/docker-compose.yml exec web python -c "from gel_analyzer.tasks import band_detection_ping_task; r = band_detection_ping_task.delay(); print(r.get(timeout=10))"
```
Expected: a heartbeat dict like `{'ok': True, 'task_name': 'band_detection_ping_task', ...}` printed within 5-10s.

- [ ] **Step 8: Tear down and bring back up — verify state survives**

```bash
docker compose -f docker/docker-compose.yml down
docker compose -f docker/docker-compose.yml --env-file .env up -d
```
Wait ~60s, then re-visit `https://phoresis/`. Sign in again with the same credentials. Theme preference persists, ladder templates still in DB (verify in admin), worker still pings.

If you need to wipe everything:
```bash
docker compose -f docker/docker-compose.yml down -v
```
(Note: `-v` wipes `phoresis_staticfiles`, `phoresis_media`, `phoresis_redis`, `caddy_data`. **Native Postgres is untouched** by design — that's the whole point of keeping it on the host.)

- [ ] **Step 9: Run any non-e2e tests that touch healthz to confirm nothing regressed**

```bash
.venv/Scripts/python.exe -m pytest -v
```
Expected: ~285 tests pass (Phase 4 total + 4 healthz + 2 seed_groups command).

- [ ] **Step 10: Final lint pass**

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m pre_commit run --all-files
```
Expected: all green.

- [ ] **Step 11: Commit any final fixes from the smoke**

```bash
git status
```
If anything changed:
```bash
git add -u
git commit -m "fix(docker): tweaks from Phase 5 stack smoke"
```

- [ ] **Step 12: Tag v0.5.0**

```bash
git tag -a v0.5.0 -m "Phase 5: Docker + Caddy packaging — multi-stage Dockerfile.web/worker (CPU+CUDA), Caddyfile (tls internal), docker-compose with caddy/web/worker/scheduler/redis/watchtower, /healthz/ probes, seed_groups command"
git tag --list
```

---

## Acceptance criteria for Phase 5

This phase is **done** when ALL of the following hold:

1. `docker build -f docker/Dockerfile.web --build-arg TORCH_VARIANT=cpu -t phoresis-web:cpu .` succeeds.
2. `docker build -f docker/Dockerfile.worker --build-arg TORCH_VARIANT=cpu -t phoresis-worker:cpu .` succeeds.
3. `docker compose -f docker/docker-compose.yml --env-file .env up -d` brings all 6 services to a healthy state within 90 seconds on a clean machine (Postgres provisioned).
4. `https://phoresis/` is reachable in a browser (after accepting the self-signed cert), redirects to `/accounts/login/`, and a sign-in with the seeded primary user lands on the dashboard.
5. `https://phoresis/healthz/` returns `200 {"overall":"ok"}` when the full stack is up.
6. `https://phoresis/healthz/celery/` returns `200 {"status":"ok"}` when a worker is up, `503 {"status":"down"}` when worker is paused (`docker compose pause worker`).
7. `https://phoresis/static/...` and `https://phoresis/media/...` paths are served by Caddy (not by Django) — verified by checking response headers (`server: Caddy` for static, no `X-Powered-By` from Django).
8. A Celery task triggered via `docker compose exec web python -c "from gel_analyzer.tasks import band_detection_ping_task; band_detection_ping_task.delay().get()"` returns within 10s.
9. `docker compose down` followed by `docker compose up -d` preserves: theme preference, ladder templates, user accounts, gel images uploaded between cycles. `down -v` preserves Postgres data (it's on the host, not in volumes).
10. `pytest -v` runs with 0 failures, 0 errors. Approximate count: ~285 (Phase 4 + Phase 5 additions).
11. `ruff check .`, `ruff format --check .`, `pre-commit run --all-files` all green.
12. The git tag `v0.5.0` exists.
13. Spec §5.1 / §9.1 / §9.2 invariants:
    - Native Postgres on the host (port 5432); containers reach it via `host.docker.internal:5432`.
    - 5 named volumes: `phoresis_staticfiles`, `phoresis_media`, `phoresis_redis`, `caddy_data`, `caddy_config`.
    - Watchtower scoped to `com.centurylinklabs.watchtower.enable=true` containers only (web, worker, scheduler) — not Caddy or Redis.
    - Caddy serves `/static/*` and `/media/*` directly from volume mounts; everything else proxied to `web:8000`.
    - HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy headers all present on responses.
14. Two image variants buildable: `:cpu` and `:cuda` for both `phoresis-web` and `phoresis-worker` (CUDA build tested optional — only required if a GPU box is available).
