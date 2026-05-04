# Phoresis — Phase 1 (Bootstrap & Shims) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring up the Phoresis Django project skeleton with `phoresis_core` (logging, celery, error handling, navigation), a custom-user `accounts` app (User + UserProfile + 3 seeded groups + login/logout/profile), a stub `dashboard`, an empty `phoresis_ui` shell, and a minimal CI pipeline — so that `runserver` boots, `/` and `/admin/` serve, and `pytest` is green.

**Architecture:** Standard Django 5.2 project with `src/` layout. Six top-level packages under `src/`: `phoresis` (project — settings/urls/wsgi/asgi), `phoresis_core` (cross-cutting infra — logging, celery_app, error handling, navigation, ErrorLog model), `accounts` (custom AUTH_USER_MODEL), `dashboard` (home view stub), `phoresis_ui` (Tailwind/HTMX shell — empty for now). Settings are split (`base / dev / test / prod`). Each task wires its own app into `INSTALLED_APPS`/`MIDDLEWARE`/`urls.py` as its final step, so every commit boots cleanly.

**Tech Stack:** Python 3.12, Django 5.2, Celery 5, Redis 7, Postgres 17, uv (dep mgmt), pytest + pytest-django + factory-boy, ruff (lint+format), pre-commit, GitHub Actions, loguru, psycopg 3, hatchling (build backend).

**Source repo for ports:** `C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/` (read-only reference; copy-and-clean, never `git filter-repo`).

---

## Build Order Rationale

Apps are added to `INSTALLED_APPS` only **after** their `apps.py.ready()` and any modules it imports exist. Otherwise `manage.py` commands crash on app registry boot. Concretely:

1. **Repo scaffold** — pyproject + .gitignore + .editorconfig.
2. **Django project (Task 2)** — minimal settings: INSTALLED_APPS = Django built-ins only, no AUTH_USER_MODEL, no project-specific middleware. `manage.py check` boots clean.
3. **Tooling (Task 3)** — pytest, ruff, pre-commit.
4. **`accounts` (Tasks 4-6)** — built **before** `phoresis_core` because accounts has zero dependencies on phoresis_core. Sets `AUTH_USER_MODEL = "accounts.User"` from day one. ErrorLog (Task 9) declares its FK against the already-set string — Django resolves it at migration time.
5. **`phoresis_core` (Tasks 7-10)** — logging → celery_app + celery_utils → error_handling → navigation. Each task adds itself to settings as its final wiring step.
6. **`dashboard` (Task 11)** — added late so accounts views' "redirect to dashboard:home" test reverse can finally resolve.
7. **`phoresis_ui` (Task 12)** — empty shell, last because nothing else depends on it in Phase 1.
8. **CI (Task 13)**, **Smoke (Task 14)**.

---

## File Structure

```
phoresis/                            # repo root (worktree)
├── .editorconfig
├── .env.example
├── .github/
│   └── workflows/
│       └── ci.yml
├── .gitignore                       # already exists, we extend it
├── .pre-commit-config.yaml
├── LICENSE                          # already exists
├── README.md                        # already exists
├── docs/...                         # specs + plans (already exist)
├── conftest.py
├── manage.py
├── pyproject.toml
└── src/
    ├── phoresis/                    # Django project
    │   ├── __init__.py              # imports celery_app from phoresis_core
    │   ├── asgi.py
    │   ├── wsgi.py
    │   ├── urls.py
    │   └── settings/
    │       ├── __init__.py
    │       ├── base.py
    │       ├── dev.py
    │       ├── test.py
    │       └── prod.py
    ├── phoresis_core/
    │   ├── __init__.py
    │   ├── apps.py
    │   ├── admin.py                 # ErrorLog admin
    │   ├── celery_app.py            # Celery() instance, autodiscover_tasks
    │   ├── celery_utils.py          # RobustTask + @robust_task
    │   ├── logging_config.py
    │   ├── models.py                # ErrorLog
    │   ├── error_handling/
    │   │   ├── __init__.py
    │   │   ├── middleware.py
    │   │   └── utils.py
    │   ├── navigation/
    │   │   ├── __init__.py          # NavRegistry singleton + nav_registry
    │   │   └── registry.py          # autodiscover_nav_modules
    │   ├── migrations/
    │   │   ├── __init__.py
    │   │   └── 0001_initial.py      # auto-generated
    │   └── tests/
    │       ├── __init__.py
    │       ├── test_celery_utils.py
    │       ├── test_error_handling.py
    │       ├── test_logging.py
    │       └── test_navigation.py
    ├── accounts/
    │   ├── __init__.py
    │   ├── admin.py
    │   ├── apps.py
    │   ├── forms.py
    │   ├── models.py                # User + UserProfile
    │   ├── permissions.py           # is_lab_user / is_reviewer / is_admin
    │   ├── signals.py
    │   ├── urls.py
    │   ├── views.py
    │   ├── nav.py                   # registers in nav_registry — added in Task 10's wrap-up
    │   ├── migrations/
    │   │   ├── __init__.py
    │   │   ├── 0001_initial.py
    │   │   └── 0002_seed_groups.py
    │   ├── templates/accounts/
    │   │   ├── login.html
    │   │   └── profile.html
    │   └── tests/
    │       ├── __init__.py
    │       ├── factories.py
    │       ├── test_models.py
    │       ├── test_seed_groups.py
    │       ├── test_signals.py
    │       └── test_views.py
    ├── dashboard/
    │   ├── __init__.py
    │   ├── apps.py
    │   ├── nav.py
    │   ├── urls.py
    │   ├── views.py
    │   ├── templates/dashboard/
    │   │   └── home.html
    │   └── tests/
    │       ├── __init__.py
    │       └── test_views.py
    └── phoresis_ui/
        ├── __init__.py
        ├── apps.py
        ├── templatetags/
        │   ├── __init__.py
        │   ├── ui_components.py
        │   └── ui_icons.py
        ├── templates/components/
        │   └── base.html
        └── tests/
            ├── __init__.py
            └── test_templatetags.py
```

---

## Task 1: Repo scaffolding (pyproject.toml, src layout, .gitignore extensions)

**Files:**
- Create: `pyproject.toml`
- Create: `.editorconfig`
- Create: `.env.example`
- Modify: `.gitignore`

- [ ] **Step 1: Confirm starting state**

```bash
ls -la
```
Expected: `LICENSE`, `README.md`, `docs/`, `.gitignore`, `.git`. Nothing else.

- [ ] **Step 2: Extend `.gitignore`**

Append (do not replace) the following block to `.gitignore`:

```
# --- Python / uv ---
__pycache__/
*.py[cod]
*.egg-info/
.eggs/
.venv/
venv/
.python-version

# --- Django ---
*.log
*.pot
db.sqlite3
db.sqlite3-journal
media/
staticfiles/
local_settings.py

# --- uv ---
uv.lock

# --- pytest / coverage / mypy ---
.pytest_cache/
.coverage
.coverage.*
htmlcov/
coverage.xml
.mypy_cache/
.ruff_cache/

# --- IDE ---
.idea/
.vscode/
*.swp
*~

# --- env ---
.env
.env.local
.env.*.local

# --- node (Phase 3+) ---
node_modules/
```

`uv.lock` is gitignored in Phase 1 because we don't yet have a frozen prod build. Phase 5 commits it once docker images stabilise.

- [ ] **Step 3: Create `.editorconfig`**

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 4

[*.{yml,yaml,json,toml,html,css,js,md}]
indent_size = 2

[Makefile]
indent_style = tab
```

- [ ] **Step 4: Create `.env.example`**

```dotenv
# Django
DJANGO_SETTINGS_MODULE=phoresis.settings.dev
DJANGO_SECRET_KEY=dev-insecure-change-me
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,phoresis

# Database (native Postgres on host)
DB_NAME=phoresis
DB_USER=phoresis
DB_PASSWORD=phoresis
DB_HOST=127.0.0.1
DB_PORT=5432

# Redis (Celery broker + cache)
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB_CELERY=0
REDIS_DB_CACHE=1

# Initial users (seeded by create_initial_users in Phase 6)
ADMIN_EMAIL=admin@phoresis.local
ADMIN_PASSWORD=change-me
PRIMARY_USER_EMAIL=lab@phoresis.local
PRIMARY_USER_PASSWORD=change-me
PRIMARY_USER_FULL_NAME=Lab User
```

- [ ] **Step 5: Create `pyproject.toml`**

```toml
[project]
name = "phoresis"
version = "0.1.0"
description = "Phoresis — standalone gel electrophoresis analysis platform"
readme = "README.md"
license = { text = "Proprietary" }
requires-python = ">=3.12"
authors = [{ name = "Grégory Mathy" }]
keywords = ["django", "gel", "electrophoresis", "sds-page", "western-blot", "densitometry"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Environment :: Web Environment",
    "Framework :: Django :: 5.2",
    "Intended Audience :: Science/Research",
    "License :: Other/Proprietary License",
    "Operating System :: Microsoft :: Windows :: Windows 11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Scientific/Engineering :: Bio-Informatics",
]

dependencies = [
    "Django>=5.2,<6.0",
    "psycopg[binary]>=3.2",
    "celery>=5.4",
    "redis>=5.0",
    "django-redis>=5.4",
    "djangorestframework>=3.15",
    "django-simple-history>=3.8",
    "loguru>=0.7",
    "gunicorn>=23.0",
    "whitenoise>=6.7",
    "Pillow>=10.4",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-django>=4.9",
    "pytest-cov>=5.0",
    "pytest-xdist>=3.6",
    "factory-boy>=3.3",
    "freezegun>=1.5",
    "ruff>=0.7",
    "pre-commit>=4.0",
    "ipython>=8.27",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/phoresis", "src/phoresis_core", "src/accounts", "src/dashboard", "src/phoresis_ui"]

# ===== Ruff =====
[tool.ruff]
line-length = 120
target-version = "py312"
src = ["src"]
extend-exclude = ["**/migrations/*"]

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "C4", "UP", "SIM"]
ignore = [
    "E501",   # line length (formatter handles it)
    "B008",   # Django: function calls in argument defaults
]

[tool.ruff.lint.per-file-ignores]
"**/migrations/*" = ["E501", "F401", "I001"]
"__init__.py" = ["F401"]
"src/phoresis/settings/*" = ["F405", "F403"]

[tool.ruff.lint.isort]
known-first-party = ["phoresis", "phoresis_core", "accounts", "dashboard", "phoresis_ui", "gel_analyzer"]
section-order = ["future", "standard-library", "third-party", "django", "first-party", "local-folder"]

[tool.ruff.lint.isort.sections]
django = ["django"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

# ===== Pytest =====
[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "phoresis.settings.test"
python_files = ["test_*.py", "*_test.py"]
pythonpath = ["src"]
addopts = ["--strict-markers", "-ra", "--reuse-db"]
testpaths = ["src"]
filterwarnings = [
    "ignore::DeprecationWarning",
    "ignore::PendingDeprecationWarning",
]

# ===== Coverage =====
[tool.coverage.run]
branch = true
source = ["src"]
omit = ["*/migrations/*", "*/tests/*", "*/test_*.py", "src/phoresis/wsgi.py", "src/phoresis/asgi.py"]

[tool.coverage.report]
exclude_lines = ["pragma: no cover", "def __repr__", "raise NotImplementedError", "if TYPE_CHECKING:"]
show_missing = true
skip_covered = true
```

- [ ] **Step 6: Initialize uv and install deps**

```bash
uv sync --extra dev
```
Expected: `.venv/` created at the worktree root, deps install, no errors. `uv.lock` generated (gitignored).

If `uv` is not on PATH:
```bash
pip install uv
uv sync --extra dev
```

- [ ] **Step 7: Verify the Python env**

```bash
.venv/Scripts/python.exe -c "import django; print(django.get_version())"
```
Expected: `5.2.x` (any 5.2 patch).

- [ ] **Step 8: Commit**

```bash
git add .gitignore .editorconfig .env.example pyproject.toml
git commit -m "chore: scaffold pyproject.toml, .editorconfig, .env.example (Phase 1)"
```

---

## Task 2: Django project skeleton (`src/phoresis/`) — minimal settings

The settings file in this task contains **only Django built-ins** in `INSTALLED_APPS` and `MIDDLEWARE`. AUTH_USER_MODEL is **not** set yet. Each subsequent task adds its own app/middleware as its final wiring step.

**Files:**
- Create: `src/phoresis/__init__.py`
- Create: `src/phoresis/asgi.py`
- Create: `src/phoresis/wsgi.py`
- Create: `src/phoresis/urls.py`
- Create: `src/phoresis/settings/__init__.py`
- Create: `src/phoresis/settings/base.py`
- Create: `src/phoresis/settings/dev.py`
- Create: `src/phoresis/settings/test.py`
- Create: `src/phoresis/settings/prod.py`
- Create: `manage.py` (root)
- Create: `conftest.py` (root)

- [ ] **Step 1: Create `manage.py` at the repo root**

```python
#!/usr/bin/env python
"""Django administrative tasks — adds src/ to sys.path before delegating."""
import os
import sys
from pathlib import Path


def main() -> None:
    src_dir = Path(__file__).resolve().parent / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "phoresis.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Did you `uv sync --extra dev` and activate the venv?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create `conftest.py` at the repo root**

```python
"""Top-level conftest — ensures src/ is importable for pytest."""
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
```

- [ ] **Step 3: Create `src/phoresis/settings/base.py`**

Minimal — no project-specific apps, no AUTH_USER_MODEL, no project middleware. All those land in later tasks.

```python
"""
Base settings shared by all environments.

Phase 1 base.py is intentionally minimal — Django built-ins only.
Each Phoresis app appends itself to INSTALLED_APPS / MIDDLEWARE in its
own task. This keeps every intermediate commit able to boot via
`manage.py check` and `manage.py makemigrations`.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]
SRC_DIR = BASE_DIR / "src"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "simple_history",
    # Phoresis apps are appended in their own tasks (4, 7, 11, 12).
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    # ExceptionContextMiddleware is appended in Task 9.
]

ROOT_URLCONF = "phoresis.urls"
WSGI_APPLICATION = "phoresis.wsgi.application"
ASGI_APPLICATION = "phoresis.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "phoresis"),
        "USER": os.environ.get("DB_USER", "phoresis"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "phoresis"),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
# AUTH_USER_MODEL is set in Task 4 once accounts.User exists.

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Brussels"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

REDIS_HOST = os.environ.get("REDIS_HOST", "127.0.0.1")
REDIS_PORT = os.environ.get("REDIS_PORT", "6379")
REDIS_DB_CELERY = os.environ.get("REDIS_DB_CELERY", "0")
REDIS_DB_CACHE = os.environ.get("REDIS_DB_CACHE", "1")
_REDIS_BASE = f"redis://{REDIS_HOST}:{REDIS_PORT}"

CELERY_BROKER_URL = f"{_REDIS_BASE}/{REDIS_DB_CELERY}"
CELERY_RESULT_BACKEND = f"{_REDIS_BASE}/{REDIS_DB_CELERY}"
CELERY_TASK_QUEUES = ("default", "heavy")
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TIMEZONE = TIME_ZONE

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"{_REDIS_BASE}/{REDIS_DB_CACHE}",
    }
}

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Phase 1 — STALE_TASK_REGISTRY is empty until gel_analyzer lands in Phase 2.
STALE_TASK_TIMEOUT_HOURS = 2
```

- [ ] **Step 4: Create `src/phoresis/settings/dev.py`**

```python
"""Development settings — local Postgres, DEBUG=True."""
from .base import *  # noqa: F401, F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "phoresis"]

# Phase 1: keep manifest storage off in dev to avoid collectstatic friction
STORAGES["staticfiles"]["BACKEND"] = "django.contrib.staticfiles.storage.StaticFilesStorage"  # noqa: F405

INTERNAL_IPS = ["127.0.0.1"]
```

- [ ] **Step 5: Create `src/phoresis/settings/test.py`**

```python
"""Test settings — eager Celery, fast password hasher, in-memory cache."""
from .base import *  # noqa: F401, F403

DEBUG = False
SECRET_KEY = "test-secret-not-secret"
ALLOWED_HOSTS = ["*"]

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
STORAGES["staticfiles"]["BACKEND"] = "django.contrib.staticfiles.storage.StaticFilesStorage"  # noqa: F405
```

- [ ] **Step 6: Create `src/phoresis/settings/prod.py`**

```python
"""Production settings — strict, no DEBUG, env-driven secrets."""
from .base import *  # noqa: F401, F403

DEBUG = False
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]  # noqa: F405 — must be set in prod
ALLOWED_HOSTS = [h.strip() for h in os.environ["DJANGO_ALLOWED_HOSTS"].split(",") if h.strip()]  # noqa: F405

SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
```

- [ ] **Step 7: Create `src/phoresis/settings/__init__.py`**

```python
"""Settings package — explicit submodule selection via DJANGO_SETTINGS_MODULE."""
```

- [ ] **Step 8: Create `src/phoresis/__init__.py`**

```python
"""Phoresis Django project. Celery app is wired in Task 8."""
```

(`celery_app` import is added in Task 8 once `phoresis_core/celery_app.py` exists.)

- [ ] **Step 9: Create `src/phoresis/wsgi.py`**

```python
"""WSGI entry point — used by gunicorn in the web container (Phase 5)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "phoresis.settings.dev")
application = get_wsgi_application()
```

- [ ] **Step 10: Create `src/phoresis/asgi.py`**

```python
"""ASGI entry point — reserved for future async views/SSE."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "phoresis.settings.dev")
application = get_asgi_application()
```

- [ ] **Step 11: Create `src/phoresis/urls.py`**

Phase 1 baseline — only `/admin/`. Each app inserts its own `include()` in its own task.

```python
"""Root URLconf for the Phoresis project.

App-specific includes are added in their respective tasks:
- accounts: Task 6
- dashboard: Task 11
"""
from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
]
```

- [ ] **Step 12: Verify the project boots**

```bash
.venv/Scripts/python.exe manage.py check
```
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 13: Commit**

```bash
git add manage.py conftest.py src/phoresis/
git commit -m "feat(phoresis): scaffold Django project with split settings (Phase 1)"
```

---

## Task 3: Test/lint tooling smoke (pytest + ruff + pre-commit)

**Files:**
- Create: `.pre-commit-config.yaml`

- [ ] **Step 1: Run a one-off pytest to confirm wiring**

`pytest` collects from `testpaths = ["src"]` per `pyproject.toml`. There are no tests yet, so the run should report "no tests ran" — that's success.

```bash
.venv/Scripts/python.exe -m pytest -v
```
Expected: exit code 5 ("no tests collected") or 0. **NOT** an import error or settings error.

If this fails with `ModuleNotFoundError: phoresis.settings.test`, double-check `conftest.py` and `pyproject.toml`'s `pythonpath = ["src"]`.

- [ ] **Step 2: Run ruff against current code**

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
```
Expected: no errors. If ruff fixes anything (e.g., import order in `settings/base.py`), apply the fixes:
```bash
.venv/Scripts/python.exe -m ruff check . --fix
.venv/Scripts/python.exe -m ruff format .
```

- [ ] **Step 3: Create `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: check-added-large-files
        args: ['--maxkb=1000']
      - id: check-merge-conflict
      - id: detect-private-key

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.7.4
    hooks:
      - id: ruff
        args: ['--fix']
      - id: ruff-format

  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2
    hooks:
      - id: gitleaks
```

- [ ] **Step 4: Install + run pre-commit once across all files**

```bash
.venv/Scripts/python.exe -m pre_commit install
.venv/Scripts/python.exe -m pre_commit run --all-files
```
Expected: hooks may auto-fix some files. Re-stage with `git add -u` if so before committing.

- [ ] **Step 5: Commit**

```bash
git add .pre-commit-config.yaml
git add -u  # picks up any pre-commit auto-fixes
git commit -m "chore: configure pre-commit (ruff, gitleaks, hygiene hooks)"
```

---

## Task 4: `accounts` app — User + UserProfile + signal + migration + INSTALLED_APPS wiring

**Files:**
- Create: `src/accounts/__init__.py`
- Create: `src/accounts/apps.py`
- Create: `src/accounts/models.py`
- Create: `src/accounts/signals.py`
- Create: `src/accounts/admin.py`
- Create: `src/accounts/permissions.py`
- Create: `src/accounts/tests/__init__.py`
- Create: `src/accounts/tests/factories.py`
- Create: `src/accounts/tests/test_models.py`
- Create: `src/accounts/tests/test_signals.py`
- Create: `src/accounts/migrations/__init__.py`
- Auto-generated: `src/accounts/migrations/0001_initial.py`
- Modify: `src/phoresis/settings/base.py` (append `accounts` to `INSTALLED_APPS`; set `AUTH_USER_MODEL`)

- [ ] **Step 1: Write the failing model tests**

`src/accounts/tests/__init__.py`: empty file.

`src/accounts/tests/test_models.py`:
```python
"""Tests for the accounts.User and accounts.UserProfile models."""
import pytest

from accounts.models import User, UserProfile


@pytest.mark.django_db
def test_user_can_be_created_with_email_and_password() -> None:
    user = User.objects.create_user(username="alice", email="alice@example.com", password="pwd12345")
    assert user.username == "alice"
    assert user.email == "alice@example.com"
    assert user.check_password("pwd12345")


@pytest.mark.django_db
def test_user_profile_default_theme_is_auto() -> None:
    user = User.objects.create_user(username="bob", email="bob@example.com", password="pwd12345")
    profile = user.profile  # OneToOne reverse accessor
    assert profile.theme == UserProfile.THEME_AUTO
    assert profile.language == UserProfile.LANG_EN


@pytest.mark.django_db
def test_user_str_uses_full_name_when_available() -> None:
    user = User.objects.create_user(
        username="carol", email="c@example.com", password="x", first_name="Carol", last_name="Danvers"
    )
    assert str(user) == "Carol Danvers"


@pytest.mark.django_db
def test_user_str_falls_back_to_username() -> None:
    user = User.objects.create_user(username="lone", email="l@example.com", password="x")
    assert str(user) == "lone"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest src/accounts/tests/test_models.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'accounts'`.

- [ ] **Step 3: Create `src/accounts/__init__.py`**

```python
"""Phoresis user and authentication app."""
```

- [ ] **Step 4: Create `src/accounts/apps.py`**

```python
"""Django app config for accounts."""
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Accounts"

    def ready(self) -> None:
        from . import signals  # noqa: F401 — registers post_save signal
```

- [ ] **Step 5: Create `src/accounts/models.py`**

```python
"""User and UserProfile models for Phoresis.

`AUTH_USER_MODEL = "accounts.User"` is set in `phoresis.settings.base` so this
custom user is the project's user model from day one — avoiding the painful
mid-project swap that Django warns about.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Phoresis user — `AbstractUser` + a friendlier `__str__`."""

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["first_name", "last_name", "username"]

    def __str__(self) -> str:
        full = self.get_full_name().strip()
        return full or self.username


class UserProfile(models.Model):
    """Per-user UI preferences and metadata.

    Created automatically via `accounts.signals.create_user_profile` whenever a
    `User` is created, so `user.profile` is always safe to access.
    """

    THEME_AUTO = "auto"
    THEME_LIGHT = "light"
    THEME_DARK = "dark"
    THEME_CHOICES = [
        (THEME_AUTO, "Auto"),
        (THEME_LIGHT, "Light"),
        (THEME_DARK, "Dark"),
    ]

    LANG_EN = "en"
    LANG_FR = "fr"
    LANG_CHOICES = [
        (LANG_EN, "English"),
        (LANG_FR, "Français"),
    ]

    user = models.OneToOneField(
        "accounts.User", on_delete=models.CASCADE, related_name="profile"
    )
    theme = models.CharField(max_length=10, choices=THEME_CHOICES, default=THEME_AUTO)
    language = models.CharField(max_length=2, choices=LANG_CHOICES, default=LANG_EN)
    avatar = models.ImageField(upload_to="accounts/avatars/", blank=True, null=True)
    job_title = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User profile"
        verbose_name_plural = "User profiles"

    def __str__(self) -> str:
        return f"{self.user} — profile"
```

- [ ] **Step 6: Create `src/accounts/signals.py`**

```python
"""Signal handlers for the accounts app."""
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **_kwargs) -> None:
    """Create the matching `UserProfile` row when a new `User` is created."""
    if created:
        UserProfile.objects.create(user=instance)
```

- [ ] **Step 7: Create `src/accounts/permissions.py`**

```python
"""Group-based permission helpers for accounts."""
from django.contrib.auth.models import AbstractUser

GROUP_LAB_USER = "Lab User"
GROUP_REVIEWER = "Reviewer"
GROUP_ADMIN = "Admin"

ALL_GROUPS = (GROUP_LAB_USER, GROUP_REVIEWER, GROUP_ADMIN)


def _in_group(user: AbstractUser, name: str) -> bool:
    return user.is_authenticated and (user.is_superuser or user.groups.filter(name=name).exists())


def is_admin(user: AbstractUser) -> bool:
    return _in_group(user, GROUP_ADMIN)


def is_reviewer(user: AbstractUser) -> bool:
    return _in_group(user, GROUP_REVIEWER) or is_admin(user)


def is_lab_user(user: AbstractUser) -> bool:
    return _in_group(user, GROUP_LAB_USER) or is_reviewer(user) or is_admin(user)
```

- [ ] **Step 8: Create `src/accounts/admin.py`**

```python
"""Admin registrations for accounts."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User, UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    fk_name = "user"
    extra = 0


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    inlines = [UserProfileInline]
    list_display = ("username", "email", "first_name", "last_name", "is_staff", "is_active")
    list_filter = ("is_staff", "is_superuser", "is_active", "groups")
    search_fields = ("username", "first_name", "last_name", "email")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "theme", "language", "job_title", "updated_at")
    list_filter = ("theme", "language")
    search_fields = ("user__username", "user__email", "job_title")
```

- [ ] **Step 9: Wire `accounts` into settings/base.py**

Edit `src/phoresis/settings/base.py`. Find the line `# Phoresis apps are appended in their own tasks (4, 7, 11, 12).` and **replace it** with:

```python
    # Phoresis apps
    "accounts",
    # phoresis_core (Task 7), dashboard (Task 11), phoresis_ui (Task 12) appended later.
```

Also, find `# AUTH_USER_MODEL is set in Task 4 once accounts.User exists.` and **replace it** with:

```python
AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"
LOGOUT_REDIRECT_URL = "accounts:login"
```

(`accounts:login` and `dashboard:home` are lazy reverses — they are resolved at request time, so it is OK that the namespaces don't exist yet. Tests that hit these URLs only run after Tasks 6 and 11.)

- [ ] **Step 10: Create migrations directory and run `makemigrations`**

```bash
mkdir -p src/accounts/migrations
touch src/accounts/migrations/__init__.py
.venv/Scripts/python.exe manage.py makemigrations accounts
```
Expected: creates `src/accounts/migrations/0001_initial.py`. Output mentions `User` and `UserProfile`.

- [ ] **Step 11: Run the model tests**

```bash
.venv/Scripts/python.exe -m pytest src/accounts/tests/test_models.py -v
```
Expected: 4 tests pass.

If Postgres is not yet provisioned locally, create the user and DB once:
```bash
psql -U postgres -c "CREATE USER phoresis WITH PASSWORD 'phoresis' SUPERUSER;"
psql -U postgres -c "CREATE DATABASE phoresis OWNER phoresis;"
```
Subsequent runs reuse `test_phoresis` thanks to `--reuse-db`.

- [ ] **Step 12: Add the signal test**

`src/accounts/tests/test_signals.py`:
```python
"""Tests for accounts.signals."""
import pytest

from accounts.models import User, UserProfile


@pytest.mark.django_db
def test_user_profile_is_auto_created_on_user_creation() -> None:
    user = User.objects.create_user(username="dora", email="d@example.com", password="x")
    assert UserProfile.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_user_profile_is_not_recreated_on_save() -> None:
    user = User.objects.create_user(username="erin", email="e@example.com", password="x")
    user.first_name = "Erin"
    user.save()
    assert UserProfile.objects.filter(user=user).count() == 1
```

- [ ] **Step 13: Add a UserFactory**

`src/accounts/tests/factories.py`:
```python
"""factory-boy factories for accounts tests."""
import factory
from django.contrib.auth.hashers import make_password

from accounts.models import User


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")
    first_name = "Test"
    last_name = "User"
    password = factory.LazyFunction(lambda: make_password("test-pwd"))
```

- [ ] **Step 14: Run all accounts tests**

```bash
.venv/Scripts/python.exe -m pytest src/accounts/ -v
```
Expected: 6 tests pass.

- [ ] **Step 15: Commit**

```bash
git add src/accounts/ src/phoresis/settings/base.py
git commit -m "feat(accounts): add custom User + UserProfile + auto-profile signal"
```

---

## Task 5: Group seed migration (Lab User / Reviewer / Admin)

**Files:**
- Create: `src/accounts/migrations/0002_seed_groups.py`
- Create: `src/accounts/tests/test_seed_groups.py`

- [ ] **Step 1: Write the failing test**

`src/accounts/tests/test_seed_groups.py`:
```python
"""Tests for the 0002_seed_groups data migration."""
import pytest
from django.contrib.auth.models import Group

from accounts.permissions import GROUP_ADMIN, GROUP_LAB_USER, GROUP_REVIEWER


@pytest.mark.django_db
def test_three_groups_are_seeded() -> None:
    names = set(Group.objects.values_list("name", flat=True))
    assert {GROUP_LAB_USER, GROUP_REVIEWER, GROUP_ADMIN}.issubset(names)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest src/accounts/tests/test_seed_groups.py -v
```
Expected: FAIL — assertion error (the three groups aren't in the empty Group table).

- [ ] **Step 3: Write the data migration**

`src/accounts/migrations/0002_seed_groups.py`:
```python
"""Seed the three Phoresis groups: Lab User, Reviewer, Admin.

Phase 1 only seeds the Group rows — concrete `Permission` rows are attached
in Phase 2 once `gel_analyzer` models exist.
"""
from django.db import migrations

GROUPS = ["Lab User", "Reviewer", "Admin"]


def seed_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in GROUPS:
        Group.objects.get_or_create(name=name)


def unseed_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=GROUPS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(seed_groups, reverse_code=unseed_groups),
    ]
```

- [ ] **Step 4: Re-run test to verify it passes**

The test database needs the new migration applied. Force a re-create with `--create-db`:
```bash
.venv/Scripts/python.exe -m pytest src/accounts/tests/test_seed_groups.py -v --create-db
```
Expected: PASS.

Subsequent runs without `--create-db` still pass (the migration is part of the test DB now).

- [ ] **Step 5: Commit**

```bash
git add src/accounts/migrations/0002_seed_groups.py src/accounts/tests/test_seed_groups.py
git commit -m "feat(accounts): seed Lab User / Reviewer / Admin groups via data migration"
```

---

## Task 6: Login / logout / profile views, URLs, templates

**Files:**
- Create: `src/accounts/forms.py`
- Create: `src/accounts/views.py`
- Create: `src/accounts/urls.py`
- Create: `src/accounts/templates/accounts/login.html`
- Create: `src/accounts/templates/accounts/profile.html`
- Create: `src/accounts/tests/test_views.py`
- Modify: `src/phoresis/urls.py` (include accounts URLs)

The templates are intentionally self-contained (don't extend `phoresis_ui/components/base.html`) in Phase 1. The polished, base-extending versions land in Phase 3.

- [ ] **Step 1: Write the failing view tests**

`src/accounts/tests/test_views.py`:
```python
"""Integration tests for accounts views."""
import pytest
from django.urls import reverse

from accounts.tests.factories import UserFactory


@pytest.mark.django_db
def test_login_get_returns_200(client) -> None:
    response = client.get(reverse("accounts:login"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_login_post_with_valid_creds_redirects_to_dashboard(client) -> None:
    """Will fail until Task 11 (`dashboard:home`) lands."""
    UserFactory(username="frank")
    response = client.post(
        reverse("accounts:login"),
        {"username": "frank", "password": "test-pwd"},
    )
    assert response.status_code == 302
    assert response.url == reverse("dashboard:home")


@pytest.mark.django_db
def test_login_post_with_bad_creds_returns_200_with_error(client) -> None:
    response = client.post(
        reverse("accounts:login"),
        {"username": "ghost", "password": "wrong"},
    )
    assert response.status_code == 200
    assert b"correct" in response.content.lower() or b"invalid" in response.content.lower()


@pytest.mark.django_db
def test_profile_requires_login(client) -> None:
    response = client.get(reverse("accounts:profile"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


@pytest.mark.django_db
def test_profile_view_authenticated_returns_200(client) -> None:
    user = UserFactory(username="hank")
    client.force_login(user)
    response = client.get(reverse("accounts:profile"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_logout_redirects_to_login(client) -> None:
    user = UserFactory(username="iris")
    client.force_login(user)
    response = client.post(reverse("accounts:logout"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest src/accounts/tests/test_views.py -v
```
Expected: FAIL with `NoReverseMatch: 'login' is not a registered namespace 'accounts'`.

- [ ] **Step 3: Create `src/accounts/forms.py`**

```python
"""Forms for the accounts app."""
from django.contrib.auth.forms import AuthenticationForm


class PhoresisLoginForm(AuthenticationForm):
    """Phase 1: vanilla AuthenticationForm. Tailwind styling lands in Phase 3."""
```

- [ ] **Step 4: Create `src/accounts/templates/accounts/login.html`**

Self-contained — no `{% extends %}`. Replaced with the polished version in Phase 3.

```django
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Phoresis — Login</title>
</head>
<body>
    <h1>Phoresis</h1>
    <h2>Sign in</h2>
    {% if form.non_field_errors %}
        <ul class="errors">
            {% for error in form.non_field_errors %}<li>{{ error }}</li>{% endfor %}
        </ul>
    {% endif %}
    <form method="post" action="{% url 'accounts:login' %}">
        {% csrf_token %}
        {{ form.as_p }}
        <button type="submit">Sign in</button>
    </form>
</body>
</html>
```

- [ ] **Step 5: Create `src/accounts/templates/accounts/profile.html`**

```django
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Phoresis — Profile</title>
</head>
<body>
    <h1>Phoresis</h1>
    <h2>Profile — {{ user }}</h2>
    <dl>
        <dt>Username</dt><dd>{{ user.username }}</dd>
        <dt>Email</dt><dd>{{ user.email }}</dd>
        <dt>Theme</dt><dd>{{ user.profile.theme }}</dd>
        <dt>Language</dt><dd>{{ user.profile.language }}</dd>
    </dl>
    <form method="post" action="{% url 'accounts:logout' %}">
        {% csrf_token %}
        <button type="submit">Sign out</button>
    </form>
</body>
</html>
```

- [ ] **Step 6: Create `src/accounts/views.py`**

```python
"""Views for the accounts app."""
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from .forms import PhoresisLoginForm


class PhoresisLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = PhoresisLoginForm
    redirect_authenticated_user = True


@login_required
def profile_view(request: HttpRequest) -> HttpResponse:
    return render(request, "accounts/profile.html")
```

- [ ] **Step 7: Create `src/accounts/urls.py`**

```python
"""URL config for accounts — login, logout, profile."""
from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.PhoresisLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("profile/", views.profile_view, name="profile"),
]
```

- [ ] **Step 8: Wire accounts URLs into the project**

Edit `src/phoresis/urls.py` — replace the file with:

```python
"""Root URLconf for the Phoresis project.

App-specific includes are added in their respective tasks:
- accounts: this task
- dashboard: Task 11
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include(("accounts.urls", "accounts"), namespace="accounts")),
]
```

- [ ] **Step 9: Run the view tests, skipping the dashboard-dependent one**

```bash
.venv/Scripts/python.exe -m pytest src/accounts/tests/test_views.py -v -k "not dashboard"
```
Expected: 5 tests pass. The skipped sixth (`test_login_post_with_valid_creds_redirects_to_dashboard`) re-runs in Task 11.

- [ ] **Step 10: Commit**

```bash
git add src/accounts/forms.py src/accounts/views.py src/accounts/urls.py src/accounts/templates/ src/accounts/tests/test_views.py src/phoresis/urls.py
git commit -m "feat(accounts): add login/logout/profile views (plain templates pending Phase 3)"
```

---

## Task 7: `phoresis_core` skeleton + logging_config + INSTALLED_APPS wiring

**Files:**
- Create: `src/phoresis_core/__init__.py`
- Create: `src/phoresis_core/apps.py`
- Create: `src/phoresis_core/logging_config.py`
- Create: `src/phoresis_core/tests/__init__.py`
- Create: `src/phoresis_core/tests/test_logging.py`
- Modify: `src/phoresis/settings/base.py` (append `phoresis_core` to `INSTALLED_APPS`)

> **Note on staging order:** `db_error_sink` defers its imports of
> `phoresis_core.error_handling.utils.extract_app_label` and `phoresis_core.models.ErrorLog`
> until called at runtime (ERROR-level log). Task 7's tests never trigger ERROR
> records, so the deferred imports are harmless. Task 9 fills in those modules.

- [ ] **Step 1: Write the failing tests**

`src/phoresis_core/tests/__init__.py`: empty.

`src/phoresis_core/tests/test_logging.py`:
```python
"""Tests for phoresis_core.logging_config."""
from phoresis_core.logging_config import get_logger, setup_logging


def test_get_logger_returns_callable_logger() -> None:
    logger = get_logger("test.module")
    logger.info("smoke test")  # no exception
    assert logger is not None


def test_setup_logging_is_idempotent() -> None:
    setup_logging()
    setup_logging()  # second call is a no-op
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_core/tests/test_logging.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'phoresis_core'`.

- [ ] **Step 3: Create `src/phoresis_core/__init__.py`**

```python
"""Phoresis core — logging, celery utilities, error handling, navigation registry."""
```

- [ ] **Step 4: Create `src/phoresis_core/apps.py`**

```python
"""App config for phoresis_core."""
from django.apps import AppConfig


class PhoresisCoreConfig(AppConfig):
    name = "phoresis_core"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Phoresis Core"

    def ready(self) -> None:
        # Wire loguru once Django is fully initialised.
        from .logging_config import setup_logging
        setup_logging()
        # Navigation autodiscover is added in Task 10 (extends this method).
```

- [ ] **Step 5: Create `src/phoresis_core/logging_config.py`**

Port of `ds-hub-django/base/logging_config.py`, adapted: `db_error_sink` writes to `phoresis_core.ErrorLog`; no `ErrorNotificationDigest` integration in Phase 1.

```python
"""Centralised loguru configuration for Phoresis.

Provides:
- Console sink (always on, colourised in DEBUG)
- File sinks (only in DEBUG, rotated daily, 30-day retention)
- DB error sink — writes ERROR+ records to phoresis_core.ErrorLog
- InterceptHandler — bridges stdlib `logging` to loguru
"""
from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

from django.conf import settings
from loguru import logger

CONSOLE_FORMAT_DEV = (
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{extra[name]}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)

CONSOLE_FORMAT_PROD = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[name]} | {message}"
FILE_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[name]}:{function}:{line} | {message}"


class InterceptHandler(logging.Handler):
    """Route stdlib logging records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).bind(name=record.name).log(level, record.getMessage())


def db_error_sink(message) -> None:
    """Persist ERROR+ records to `phoresis_core.ErrorLog`."""
    from django.utils.timezone import now

    from phoresis_core.error_handling.utils import extract_app_label
    from phoresis_core.models import ErrorLog

    record = message.record

    ignored_loggers = {"django.request", "django.server", "django.security", "celery.app.trace"}
    logger_name = record.get("extra", {}).get("name", "")
    if logger_name in ignored_loggers:
        return

    try:
        exception_type = None
        exception_text = None
        if record["exception"]:
            exception_type = record["exception"].type.__name__
            exception_text = "".join(
                traceback.format_exception(
                    record["exception"].type, record["exception"].value, record["exception"].traceback
                )
            )

        extra = record.get("extra", {})
        file_path = str(record["file"].path) if record["file"] else None
        source_type = extra.get("source_type") or ErrorLog.SOURCE_TYPE_OTHER
        app_label = extra.get("app_label") or extract_app_label(file_path)

        ErrorLog.objects.create(
            timestamp=now(),
            level=record["level"].name,
            message=str(record["message"]),
            pathname=file_path,
            func_name=record["function"],
            lineno=record["line"],
            exception_type=exception_type,
            exception_text=exception_text,
            user=extra.get("user"),
            request_path=extra.get("request_path"),
            error_id=extra.get("error_id"),
            http_method=extra.get("http_method"),
            user_agent=extra.get("user_agent"),
            referer=extra.get("referer"),
            client_ip=extra.get("client_ip"),
            view_name=extra.get("view_name"),
            view_func_name=extra.get("view_func_name"),
            request_data=extra.get("request_data"),
            error_signature=extra.get("error_signature"),
            is_handled=extra.get("is_handled", False),
            source_type=source_type,
            app_label=app_label,
            task_name=extra.get("task_name"),
            task_id=extra.get("task_id"),
            queue_name=extra.get("queue_name"),
            retry_count=extra.get("retry_count"),
            hostname=extra.get("hostname"),
            task_args=extra.get("task_args"),
            task_kwargs=extra.get("task_kwargs"),
        )
    except Exception:
        # Never raise from a log sink — would create an infinite error loop.
        pass


_logging_configured = False


def setup_logging() -> None:
    """Configure loguru — safe to call multiple times (idempotent)."""
    global _logging_configured
    if _logging_configured:
        return

    logger.remove()

    debug_mode = bool(getattr(settings, "DEBUG", False))
    base_dir = Path(getattr(settings, "BASE_DIR", Path.cwd()))

    logger.add(
        sys.stdout,
        format=CONSOLE_FORMAT_DEV if debug_mode else CONSOLE_FORMAT_PROD,
        level="DEBUG" if debug_mode else "INFO",
        colorize=True,
        backtrace=debug_mode,
        diagnose=debug_mode,
        filter=lambda r: r["extra"].setdefault("name", "root") or True,
    )

    if debug_mode:
        log_dir = base_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        logger.add(
            log_dir / "phoresis_{time:YYYY-MM-DD}.log",
            format=FILE_FORMAT,
            level="INFO",
            rotation="00:00",
            retention="30 days",
            compression="gz",
            enqueue=False,
            filter=lambda r: r["extra"].setdefault("name", "root") or True,
        )
        logger.add(
            log_dir / "errors_{time:YYYY-MM-DD}.log",
            format=FILE_FORMAT,
            level="ERROR",
            rotation="00:00",
            retention="90 days",
            compression="gz",
            enqueue=False,
            filter=lambda r: r["extra"].setdefault("name", "root") or True,
        )

    logger.add(db_error_sink, level="ERROR", enqueue=False)

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for name in ("django", "django.request", "django.db.backends", "django.security",
                 "celery", "celery.task", "celery.worker"):
        std_logger = logging.getLogger(name)
        std_logger.handlers = [InterceptHandler()]
        std_logger.propagate = False

    _logging_configured = True
    logger.bind(name="phoresis_core.logging_config").info("Loguru configured")


def get_logger(name: str | None = None):
    """Return a loguru logger bound with `name` (typically `__name__`)."""
    return logger.bind(name=name or "root")


__all__ = ("get_logger", "setup_logging", "logger", "InterceptHandler")
```

- [ ] **Step 6: Wire `phoresis_core` into settings/base.py**

Edit `src/phoresis/settings/base.py`. Find:
```python
    # Phoresis apps
    "accounts",
    # phoresis_core (Task 7), dashboard (Task 11), phoresis_ui (Task 12) appended later.
```
Replace with:
```python
    # Phoresis apps
    "phoresis_core",
    "accounts",
    # dashboard (Task 11), phoresis_ui (Task 12) appended later.
```

(Note: `phoresis_core` precedes `accounts` so its `apps.ready()` runs first — this matches the source repo's app ordering.)

- [ ] **Step 7: Run the logging tests**

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_core/tests/test_logging.py -v
```
Expected: 2 tests pass. (`db_error_sink` is registered but never fires at INFO level, so its missing-module imports remain dormant.)

- [ ] **Step 8: Commit**

```bash
git add src/phoresis_core/__init__.py src/phoresis_core/apps.py src/phoresis_core/logging_config.py src/phoresis_core/tests/ src/phoresis/settings/base.py
git commit -m "feat(phoresis_core): port loguru configuration with DB error sink"
```

---

## Task 8: `phoresis_core` celery_app + celery_utils

**Files:**
- Create: `src/phoresis_core/celery_app.py`
- Create: `src/phoresis_core/celery_utils.py`
- Create: `src/phoresis_core/tests/test_celery_utils.py`
- Modify: `src/phoresis/__init__.py` (re-export `celery_app`)

- [ ] **Step 1: Write the failing test**

`src/phoresis_core/tests/test_celery_utils.py`:
```python
"""Tests for phoresis_core.celery_utils."""
from phoresis_core.celery_utils import RobustTask, robust_task


def test_robust_task_decorator_returns_celery_task() -> None:
    @robust_task(soft_time_limit=10, time_limit=20)
    def my_task(self, x):
        return x * 2

    assert hasattr(my_task, "delay")
    assert hasattr(my_task, "apply_async")


def test_robust_task_uses_robust_task_base() -> None:
    @robust_task(soft_time_limit=10, time_limit=20)
    def my_task(self, x):
        return x

    assert isinstance(my_task, RobustTask) or issubclass(my_task.__class__, RobustTask)


def test_robust_task_runs_eagerly_in_test_mode(settings) -> None:
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True

    @robust_task(soft_time_limit=10, time_limit=20)
    def add(self, a, b):
        return a + b

    result = add.apply(args=(2, 3)).get()
    assert result == 5
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_core/tests/test_celery_utils.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'phoresis_core.celery_utils'`.

- [ ] **Step 3: Create `src/phoresis_core/celery_app.py`**

Per spec §7.1, the Celery instance lives in `phoresis_core/celery_app.py` (not `phoresis/celery.py`).

```python
"""Celery application entry point — instantiated at Django startup."""
import os

from celery import Celery
from celery.signals import setup_logging as celery_setup_logging

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "phoresis.settings.dev")

app = Celery("phoresis")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@celery_setup_logging.connect
def configure_celery_logging(**_kwargs) -> None:
    """Route Celery's own logging through loguru, not the stdlib root logger."""
    from phoresis_core.logging_config import setup_logging
    setup_logging()


@app.task(bind=True)
def debug_task(self) -> None:
    """Smoke-test task — `from phoresis_core.celery_app import debug_task; debug_task.delay()`."""
    from phoresis_core.logging_config import get_logger
    get_logger("celery.debug").info(f"Request: {self.request!r}")
```

- [ ] **Step 4: Create `src/phoresis_core/celery_utils.py`**

Port of `ds-hub-django/base/celery_utils.py`. `STALE_TASK_REGISTRY` is intentionally empty in Phase 1 — `gel_analyzer.DensitometryJob` adds itself in Phase 2.

```python
"""Celery utilities for robust task execution.

Provides:
- `RobustTask`: Celery `Task` base class with loguru integration, SoftTimeLimit
  catch, idempotent failure-handler hook, and DB connection cleanup.
- `@robust_task`: decorator facade for `@shared_task(bind=True, base=RobustTask, ...)`.
- `STALE_TASK_REGISTRY`: list of (app_label, model_name, ...) entries used by a
  future zombie-task sweeper; empty in Phase 1, populated in Phase 2.
"""
from __future__ import annotations

import time

from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db import close_old_connections

from .logging_config import get_logger

logger = get_logger(__name__)

# (app_label, model_name, status_field, running_value, failed_value, error_field, timestamp_field)
STALE_TASK_REGISTRY: list[tuple[str, str, str, str, str, str, str]] = []
STALE_TASK_TIMEOUT_HOURS_DEFAULT = 2

_warned_no_time_limit: set[str] = set()


class RobustTask(Task):
    """Celery `Task` base with loguru context, timing, and failure hooks."""

    def __call__(self, *args, **kwargs):
        task_id = self.request.id or "unknown"
        task_name = self.name or self.__class__.__name__
        retries = self.request.retries or 0

        self._failure_handled = False

        if (
            not getattr(self, "soft_time_limit", None)
            and not getattr(self, "time_limit", None)
            and task_name not in _warned_no_time_limit
        ):
            _warned_no_time_limit.add(task_name)
            logger.warning(
                f"Task {task_name} has no time limit configured — "
                f"add soft_time_limit/time_limit."
            )

        bound = logger.bind(task_id=task_id, task_name=task_name, task_retries=retries)
        bound.info(f"=== TASK STARTED === {task_name} args={_safe_repr(args)} kwargs={_safe_repr(kwargs)}")

        start = time.monotonic()
        try:
            result = super().__call__(*args, **kwargs)
            elapsed_ms = (time.monotonic() - start) * 1000
            bound.info(f"=== TASK COMPLETED === {task_name} elapsed={elapsed_ms:.1f}ms")
            return result
        except SoftTimeLimitExceeded as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            bound.error(f"=== TASK TIMEOUT === {task_name} hit soft time limit after {elapsed_ms:.1f}ms")
            self._do_handle_failure(exc)
            raise
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            bound.exception(f"=== TASK FAILED === {task_name} after {elapsed_ms:.1f}ms")
            self._do_handle_failure(exc)
            raise

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        self._do_handle_failure(exc)
        close_old_connections()

    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        close_old_connections()

    def _do_handle_failure(self, exc) -> None:
        if getattr(self, "_failure_handled", False):
            return
        self._failure_handled = True

        model = getattr(self, "_failure_model", None)
        if model is None:
            return

        status_field = getattr(self, "_failure_status_field", "status")
        status_value = getattr(self, "_failure_status_value", "FAILED")
        error_field = getattr(self, "_failure_error_field", None)

        try:
            setattr(model, status_field, status_value)
            if error_field:
                setattr(model, error_field, f"{type(exc).__name__}: {exc}"[:1000])
            update_fields = [status_field] + ([error_field] if error_field else [])
            model.save(update_fields=update_fields)
        except Exception as save_exc:
            logger.warning(
                f"handle_failure could not update model "
                f"{model.__class__.__name__}: {save_exc}"
            )


def robust_task(_func=None, **kwargs):
    """Decorator facade for `@shared_task(bind=True, base=RobustTask, ...)`."""
    kwargs["bind"] = True
    kwargs["base"] = RobustTask

    if _func is not None:
        return shared_task(**kwargs)(_func)

    def decorator(func):
        return shared_task(**kwargs)(func)

    return decorator


def _safe_repr(obj, max_len: int = 200) -> str:
    try:
        r = repr(obj)
        return r if len(r) <= max_len else r[:max_len] + "..."
    except Exception:
        return "<unrepresentable>"
```

- [ ] **Step 5: Re-export `celery_app` from `phoresis/__init__.py`**

Edit `src/phoresis/__init__.py` — replace the file with:

```python
"""Phoresis Django project — re-exports the Celery app for autodiscovery."""
from phoresis_core.celery_app import app as celery_app

__all__ = ("celery_app",)
```

- [ ] **Step 6: Run the celery_utils tests**

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_core/tests/test_celery_utils.py -v
```
Expected: 3 tests pass.

- [ ] **Step 7: Smoke-test the Celery wiring (no broker required — eager mode)**

```bash
.venv/Scripts/python.exe -c "import sys; sys.path.insert(0, 'src'); import os; os.environ['DJANGO_SETTINGS_MODULE']='phoresis.settings.test'; import django; django.setup(); from phoresis_core.celery_app import debug_task; debug_task.apply().get(); print('OK')"
```
Expected: prints `OK`.

- [ ] **Step 8: Commit**

```bash
git add src/phoresis_core/celery_app.py src/phoresis_core/celery_utils.py src/phoresis_core/tests/test_celery_utils.py src/phoresis/__init__.py
git commit -m "feat(phoresis_core): add celery_app instance + RobustTask + @robust_task"
```

---

## Task 9: `phoresis_core` error_handling — utils, ErrorLog model, middleware

**Files:**
- Create: `src/phoresis_core/error_handling/__init__.py`
- Create: `src/phoresis_core/error_handling/utils.py`
- Create: `src/phoresis_core/error_handling/middleware.py`
- Create: `src/phoresis_core/models.py`
- Create: `src/phoresis_core/admin.py`
- Create: `src/phoresis_core/migrations/__init__.py`
- Auto-generated: `src/phoresis_core/migrations/0001_initial.py`
- Create: `src/phoresis_core/tests/test_error_handling.py`
- Modify: `src/phoresis/settings/base.py` (append `ExceptionContextMiddleware` to `MIDDLEWARE`)

- [ ] **Step 1: Write the failing tests**

`src/phoresis_core/tests/test_error_handling.py`:
```python
"""Tests for phoresis_core.error_handling — utils, model, middleware."""
import datetime as dt
import re
from unittest.mock import MagicMock

import pytest

from phoresis_core.error_handling.middleware import ExceptionContextMiddleware
from phoresis_core.error_handling.utils import (
    extract_app_label,
    generate_error_id,
    generate_error_signature,
    get_client_ip,
    sanitize_dict,
)
from phoresis_core.models import ErrorLog


def test_generate_error_id_format() -> None:
    eid = generate_error_id()
    assert re.fullmatch(r"PHOR-\d{8}-[A-F0-9]{6}", eid), eid


def test_generate_error_signature_is_deterministic() -> None:
    a = generate_error_signature("ValueError", "/x/y.py", "f", 10)
    b = generate_error_signature("ValueError", "/x/y.py", "f", 10)
    c = generate_error_signature("KeyError", "/x/y.py", "f", 10)
    assert a == b
    assert a != c
    assert len(a) == 32  # md5 hex


def test_sanitize_dict_redacts_sensitive_keys() -> None:
    data = {"username": "alice", "password": "secret", "nested": {"api_key": "k"}}
    sanitized = sanitize_dict(data)
    assert sanitized["username"] == "alice"
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["nested"]["api_key"] == "[REDACTED]"


def test_sanitize_dict_truncates_long_strings() -> None:
    data = {"text": "x" * 2000}
    sanitized = sanitize_dict(data, max_value_length=100)
    assert sanitized["text"].endswith("[TRUNCATED]")
    assert len(sanitized["text"]) <= 130  # 100 + "...[TRUNCATED]"


def test_get_client_ip_prefers_x_forwarded_for() -> None:
    request = MagicMock()
    request.META = {"HTTP_X_FORWARDED_FOR": "203.0.113.1, 10.0.0.1", "REMOTE_ADDR": "10.0.0.2"}
    assert get_client_ip(request) == "203.0.113.1"


def test_get_client_ip_falls_back_to_remote_addr() -> None:
    request = MagicMock()
    request.META = {"REMOTE_ADDR": "192.168.1.1"}
    assert get_client_ip(request) == "192.168.1.1"


def test_extract_app_label_handles_none() -> None:
    assert extract_app_label(None) is None
    assert extract_app_label("") is None


def test_extract_app_label_returns_none_for_site_packages() -> None:
    assert extract_app_label("/usr/lib/.venv/site-packages/django/db/base.py") is None


@pytest.mark.django_db
def test_error_log_can_be_created() -> None:
    log = ErrorLog.objects.create(level="ERROR", message="boom", source_type=ErrorLog.SOURCE_TYPE_HTTP)
    assert log.pk is not None
    assert log.level == "ERROR"
    assert log.timestamp <= dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=1)


@pytest.mark.django_db
def test_exception_middleware_attaches_error_context_to_request(rf) -> None:
    middleware = ExceptionContextMiddleware(get_response=lambda r: None)
    request = rf.get("/some/path/")
    request._error_context = None  # mimic __call__ initialisation
    request.user = MagicMock(is_authenticated=False)

    middleware.process_exception(request, ValueError("bad"))

    ctx = request._error_context
    assert ctx is not None
    assert ctx["exception_type"] == "ValueError"
    assert ctx["exception_message"] == "bad"
    assert ctx["http_method"] == "GET"
    assert ctx["request_path"] == "/some/path/"
    assert re.fullmatch(r"PHOR-\d{8}-[A-F0-9]{6}", ctx["error_id"])
```

- [ ] **Step 2: Run tests to verify failure**

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_core/tests/test_error_handling.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'phoresis_core.error_handling'`.

- [ ] **Step 3: Create `src/phoresis_core/error_handling/__init__.py`**

```python
"""Error handling — middleware, utility helpers, ErrorLog model glue."""
```

- [ ] **Step 4: Create `src/phoresis_core/error_handling/utils.py`**

Port of `ds-hub-django/base/error_handling/utils.py`, with `PHOR-` prefix instead of `EDIPA-`.

```python
"""Utility helpers for error handling."""
from __future__ import annotations

import hashlib
import uuid
from datetime import date
from functools import lru_cache
from typing import Any

SENSITIVE_KEYS: frozenset[str] = frozenset({
    "password", "passwd", "pwd", "secret", "token", "api_key", "apikey", "auth",
    "authorization", "credit_card", "creditcard", "cc", "cvv", "ssn",
    "csrfmiddlewaretoken", "sessionid", "key", "private", "access_token",
    "refresh_token", "bearer", "credential",
})


def generate_error_id() -> str:
    """Return a unique human-readable error reference (`PHOR-YYYYMMDD-XXXXXX`)."""
    return f"PHOR-{date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


def generate_error_signature(
    exception_type: str, pathname: str | None, func_name: str | None, lineno: int | None
) -> str:
    """Return an md5 signature for deduplication."""
    parts = [exception_type or "", pathname or "", func_name or "", str(lineno) if lineno else ""]
    return hashlib.md5(":".join(parts).encode()).hexdigest()


def sanitize_dict(
    data: Any, max_depth: int = 3, max_value_length: int = 1000, _current_depth: int = 0
) -> Any:
    """Redact sensitive keys, truncate long strings, cap recursion."""
    if _current_depth >= max_depth:
        return "[MAX_DEPTH_REACHED]"
    if data is None:
        return None
    if isinstance(data, dict):
        out = {}
        for key, value in data.items():
            key_str = str(key).lower()
            if any(s in key_str for s in SENSITIVE_KEYS):
                out[key] = "[REDACTED]"
            elif isinstance(value, dict):
                out[key] = sanitize_dict(value, max_depth, max_value_length, _current_depth + 1)
            elif isinstance(value, (list, tuple)):
                out[key] = [
                    sanitize_dict(item, max_depth, max_value_length, _current_depth + 1)
                    if isinstance(item, (dict, list, tuple))
                    else item
                    for item in value
                ]
            elif isinstance(value, str) and len(value) > max_value_length:
                out[key] = value[:max_value_length] + "...[TRUNCATED]"
            else:
                out[key] = value
        return out
    if isinstance(data, (list, tuple)):
        return [
            sanitize_dict(item, max_depth, max_value_length, _current_depth + 1)
            if isinstance(item, (dict, list, tuple))
            else item
            for item in data
        ]
    return data


def get_client_ip(request) -> str | None:
    """Return the client IP, preferring X-Forwarded-For over REMOTE_ADDR."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    ip = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "")
    if ip and ":" in ip and "." in ip:
        ip = ip.split(":")[0]
    return ip or None


def truncate_string(value: str, max_length: int = 500) -> str:
    if not value or len(value) <= max_length:
        return value
    return value[:max_length] + "..."


@lru_cache(maxsize=1)
def _local_app_labels() -> frozenset:
    from django.apps import apps
    from django.conf import settings

    base_dir = str(getattr(settings, "BASE_DIR", "")).replace("\\", "/").lower()
    if not base_dir:
        return frozenset()
    labels = set()
    for app_config in apps.get_app_configs():
        app_path = str(getattr(app_config, "path", "")).replace("\\", "/").lower()
        if app_path.startswith(base_dir):
            labels.add(app_config.label)
    return frozenset(labels)


def extract_app_label(pathname: str | None) -> str | None:
    """Derive a Django app_label from a file path, or None if outside local apps."""
    if not pathname:
        return None
    normalized = pathname.replace("\\", "/").lower()
    if "/.venv/" in normalized or "/site-packages/" in normalized:
        return None
    labels = _local_app_labels()
    if not labels:
        return None
    for segment in normalized.split("/"):
        if segment in labels:
            return segment
    return None
```

- [ ] **Step 5: Create `src/phoresis_core/models.py`**

```python
"""Core models — `ErrorLog` for error persistence."""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.timezone import now


class ErrorLog(models.Model):
    """Persistence target for ERROR-level loguru records.

    Populated by `phoresis_core.logging_config.db_error_sink`.
    """

    SOURCE_TYPE_HTTP = "http"
    SOURCE_TYPE_CELERY = "celery"
    SOURCE_TYPE_COMMAND = "command"
    SOURCE_TYPE_OTHER = "other"
    SOURCE_TYPE_CHOICES = (
        (SOURCE_TYPE_HTTP, "HTTP request"),
        (SOURCE_TYPE_CELERY, "Celery task"),
        (SOURCE_TYPE_COMMAND, "Management command"),
        (SOURCE_TYPE_OTHER, "Other / unknown"),
    )

    timestamp = models.DateTimeField(default=now)
    level = models.CharField(max_length=20)
    message = models.TextField()
    pathname = models.TextField(blank=True, null=True)
    func_name = models.CharField(max_length=255, blank=True, null=True)
    lineno = models.IntegerField(blank=True, null=True)
    exception_type = models.CharField(max_length=255, blank=True, null=True)
    exception_text = models.TextField(blank=True, null=True)

    request_path = models.TextField(blank=True, null=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        help_text="User who triggered the error (if any)",
    )
    error_id = models.CharField(
        max_length=25, unique=True, null=True, blank=True, db_index=True,
        help_text="Unique reference shown to users (e.g., PHOR-20260503-A7F3B2)",
    )

    http_method = models.CharField(max_length=10, blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    referer = models.TextField(blank=True, null=True)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    view_name = models.CharField(max_length=255, blank=True, null=True)
    view_func_name = models.CharField(max_length=255, blank=True, null=True)

    source_type = models.CharField(
        max_length=20, choices=SOURCE_TYPE_CHOICES, blank=True, null=True, db_index=True,
    )
    app_label = models.CharField(max_length=50, blank=True, null=True, db_index=True)

    task_name = models.CharField(max_length=255, blank=True, null=True)
    task_id = models.CharField(max_length=255, blank=True, null=True)
    queue_name = models.CharField(max_length=64, blank=True, null=True)
    retry_count = models.IntegerField(blank=True, null=True)
    hostname = models.CharField(max_length=255, blank=True, null=True)
    task_args = models.JSONField(blank=True, null=True)
    task_kwargs = models.JSONField(blank=True, null=True)

    request_data = models.JSONField(blank=True, null=True)
    error_signature = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    is_handled = models.BooleanField(default=False)

    is_acknowledged = models.BooleanField(default=False)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="acknowledged_errors",
    )
    acknowledged_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = "Error log"
        verbose_name_plural = "Error logs"
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        if self.error_id:
            return f"[{self.error_id}] {self.level} – {self.message[:60]}"
        return f"[{self.level}] {self.timestamp} – {self.message[:80]}"
```

- [ ] **Step 6: Create `src/phoresis_core/admin.py`**

```python
"""Admin registrations for phoresis_core."""
from django.contrib import admin

from .models import ErrorLog


@admin.register(ErrorLog)
class ErrorLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "level", "source_type", "app_label", "exception_type", "error_id", "is_acknowledged")
    list_filter = ("level", "source_type", "app_label", "is_acknowledged")
    search_fields = ("message", "exception_type", "error_id", "view_name")
    date_hierarchy = "timestamp"
    readonly_fields = tuple(
        f.name for f in ErrorLog._meta.fields
        if f.name not in ("is_acknowledged", "acknowledged_by", "acknowledged_at")
    )
```

- [ ] **Step 7: Create `src/phoresis_core/error_handling/middleware.py`**

```python
"""Exception-context capture middleware."""
from __future__ import annotations

import traceback

from django.urls import Resolver404, resolve

from phoresis_core.logging_config import get_logger

from .utils import (
    extract_app_label,
    generate_error_id,
    generate_error_signature,
    get_client_ip,
    sanitize_dict,
)

logger = get_logger(__name__)


class ExceptionContextMiddleware:
    """Capture full request context on unhandled exceptions for ErrorLog.

    Runs early in the stack; stores context on `request._error_context` so
    custom 500 views can render an error reference ID to the user.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request._error_context = None
        return self.get_response(request)

    def process_exception(self, request, exception):
        error_id = generate_error_id()

        view_name = view_func_name = None
        try:
            match = resolve(request.path_info)
            view_name = match.view_name
            view_func_name = getattr(match.func, "__name__", str(match.func))
        except Resolver404:
            view_name = view_func_name = "unknown"
        except Exception:
            pass

        request_data = {}
        try:
            if request.GET:
                request_data["GET"] = sanitize_dict(dict(request.GET))
            if request.POST:
                request_data["POST_keys"] = list(request.POST.keys())
        except Exception:
            pass

        exc_pathname = exc_func_name = exc_lineno = None
        try:
            tb_info = traceback.extract_tb(exception.__traceback__)
            if tb_info:
                last = tb_info[-1]
                exc_pathname, exc_func_name, exc_lineno = last.filename, last.name, last.lineno
        except Exception:
            pass

        exception_type = type(exception).__name__
        error_signature = generate_error_signature(exception_type, exc_pathname, exc_func_name, exc_lineno)
        app_label = extract_app_label(exc_pathname)

        user = request.user if (hasattr(request, "user") and request.user.is_authenticated) else None

        error_context = {
            "error_id": error_id,
            "exception_type": exception_type,
            "exception_message": str(exception),
            "traceback": traceback.format_exc(),
            "http_method": request.method,
            "user_agent": request.META.get("HTTP_USER_AGENT", ""),
            "referer": request.META.get("HTTP_REFERER", ""),
            "client_ip": get_client_ip(request),
            "view_name": view_name,
            "view_func_name": view_func_name,
            "request_data": request_data,
            "user": user,
            "request_path": request.path,
            "error_signature": error_signature,
            "exc_pathname": exc_pathname,
            "exc_func_name": exc_func_name,
            "exc_lineno": exc_lineno,
        }
        request._error_context = error_context

        logger.bind(
            error_id=error_id,
            user=user,
            request_path=request.path,
            http_method=request.method,
            user_agent=error_context["user_agent"],
            referer=error_context["referer"],
            client_ip=error_context["client_ip"],
            view_name=view_name,
            view_func_name=view_func_name,
            request_data=request_data,
            error_signature=error_signature,
            is_handled=False,
            source_type="http",
            app_label=app_label,
        ).exception(f"Unhandled exception [Error ID: {error_id}]: {exception}")

        return None
```

- [ ] **Step 8: Generate the migration**

```bash
mkdir -p src/phoresis_core/migrations
touch src/phoresis_core/migrations/__init__.py
.venv/Scripts/python.exe manage.py makemigrations phoresis_core
```
Expected: creates `0001_initial.py` for ErrorLog.

- [ ] **Step 9: Wire ExceptionContextMiddleware into settings/base.py**

Edit `src/phoresis/settings/base.py`. Find `# ExceptionContextMiddleware is appended in Task 9.` and replace with:

```python
    "phoresis_core.error_handling.middleware.ExceptionContextMiddleware",
```

- [ ] **Step 10: Run tests**

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_core/tests/test_error_handling.py -v --create-db
```
Expected: 9 tests pass.

- [ ] **Step 11: Run all phoresis_core tests to confirm no regression**

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_core/ -v
```
Expected: 14 tests pass (2 logging + 3 celery_utils + 9 error_handling).

- [ ] **Step 12: Commit**

```bash
git add src/phoresis_core/error_handling/ src/phoresis_core/models.py src/phoresis_core/admin.py src/phoresis_core/migrations/ src/phoresis_core/tests/test_error_handling.py src/phoresis/settings/base.py
git commit -m "feat(phoresis_core): add ErrorLog model + ExceptionContextMiddleware + utils"
```

---

## Task 10: `phoresis_core` navigation registry + autodiscover

**Files:**
- Create: `src/phoresis_core/navigation/__init__.py`
- Create: `src/phoresis_core/navigation/registry.py`
- Create: `src/phoresis_core/tests/test_navigation.py`
- Modify: `src/phoresis_core/apps.py` (extend `ready()` to call `autodiscover_nav_modules`)

- [ ] **Step 1: Write the failing test**

`src/phoresis_core/tests/test_navigation.py`:
```python
"""Tests for phoresis_core.navigation."""
import pytest

from phoresis_core.navigation import NavRegistry, nav_registry


@pytest.fixture
def fresh_registry():
    """Provide an isolated NavRegistry per test."""
    yield NavRegistry()


def test_register_app_stores_minimal_entry(fresh_registry: NavRegistry) -> None:
    fresh_registry.register_app(
        app_label="acc",
        display_name="Accounts",
        group="Management",
        icon="user",
        pages=[{"name": "Profile", "url": "/accounts/profile/"}],
    )
    apps = fresh_registry.get_apps()
    assert "acc" in apps
    assert apps["acc"]["display_name"] == "Accounts"
    assert apps["acc"]["pages"][0]["name"] == "Profile"


def test_register_app_rejects_duplicate_label(fresh_registry: NavRegistry) -> None:
    fresh_registry.register_app(
        app_label="x", display_name="X", group="Lab Tools", icon="i", pages=[]
    )
    with pytest.raises(ValueError, match="already registered"):
        fresh_registry.register_app(
            app_label="x", display_name="X2", group="Lab Tools", icon="i", pages=[]
        )


def test_get_groups_returns_all_canonical_groups_even_when_empty(fresh_registry: NavRegistry) -> None:
    groups = fresh_registry.get_groups()
    assert set(groups.keys()) == {"Research", "Analytics & Data", "Management", "Lab Tools"}
    assert all(g["apps"] == [] for g in groups.values())


def test_get_flat_items_yields_pages_and_actions(fresh_registry: NavRegistry) -> None:
    fresh_registry.register_app(
        app_label="x", display_name="X", group="Lab Tools", icon="i",
        pages=[{"name": "Home", "url": "/x/"}],
        actions=[{"name": "New X", "url": "/x/new/"}],
    )
    items = fresh_registry.get_flat_items()
    assert any(i["name"] == "X — Home" and i["type"] == "page" for i in items)
    assert any(i["name"] == "New X" and i["type"] == "action" for i in items)


def test_module_singleton_is_a_NavRegistry() -> None:
    assert isinstance(nav_registry, NavRegistry)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_core/tests/test_navigation.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'phoresis_core.navigation'`.

- [ ] **Step 3: Create `src/phoresis_core/navigation/__init__.py`**

Port of `ds-hub-django/base/navigation/__init__.py`. Adapt `GROUP_DEFINITIONS` to use Lucide icon names (Phoresis uses Lucide; `bi-*` was Bootstrap Icons in the source).

```python
"""NavRegistry — central navigation singleton for Phoresis.

Apps register themselves via `nav.py` files at app-ready time. The registry
feeds the command palette (Ctrl+K), the sidebar, and the keyboard shortcuts.

Usage::

    from phoresis_core.navigation import nav_registry

    nav_registry.register_app(
        app_label="gel_analyzer",
        display_name="Gel Analyzer",
        group="Lab Tools",
        icon="image",
        url="/gel-analyzer/",
        pages=[{"name": "Upload", "url": "/gel-analyzer/upload/", "icon": "upload"}],
        actions=[{"name": "New Analysis", "url": "/gel-analyzer/new/", "icon": "plus"}],
        shortcut_key="g",
    )
"""
from __future__ import annotations

from typing import Any


class NavRegistry:
    """Singleton-style registry for Phoresis navigation."""

    GROUP_DEFINITIONS: dict[str, dict[str, str]] = {
        "Lab Tools":       {"color": "#3b82f6", "icon": "wrench"},
        "Research":        {"color": "#a855f7", "icon": "flask-conical"},
        "Analytics & Data":{"color": "#22c55e", "icon": "trending-up"},
        "Management":      {"color": "#f59e0b", "icon": "kanban"},
    }
    GROUP_ORDER: list[str] = ["Research", "Analytics & Data", "Management", "Lab Tools"]

    def __init__(self) -> None:
        self._apps: dict[str, dict[str, Any]] = {}
        self._searchables: dict[str, list[dict[str, Any]]] = {}

    def register_app(
        self,
        *,
        app_label: str,
        display_name: str,
        group: str,
        icon: str,
        url: str | None = None,
        pages: list[dict[str, Any]],
        actions: list[dict[str, Any]] | None = None,
        shortcut_key: str | None = None,
        keywords: list[str] | None = None,
        permission: str | None = None,
    ) -> None:
        if app_label in self._apps:
            raise ValueError(
                f"NavRegistry: app_label '{app_label}' is already registered. "
                "Each app_label must be unique."
            )
        self._apps[app_label] = {
            "app_label": app_label,
            "display_name": display_name,
            "group": group,
            "icon": icon,
            "url": url,
            "pages": pages,
            "actions": actions or [],
            "shortcut_key": shortcut_key.upper() if shortcut_key else "",
            "keywords": keywords or [],
            "permission": permission,
        }

    def register_searchable(self, *, app_label: str, models: list[dict[str, Any]]) -> None:
        self._searchables.setdefault(app_label, []).extend(models)

    def get_apps(self) -> dict[str, dict[str, Any]]:
        return dict(self._apps)

    def get_groups(self) -> dict[str, dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for name in self.GROUP_ORDER:
            defn = self.GROUP_DEFINITIONS[name]
            groups[name] = {"color": defn["color"], "icon": defn["icon"], "apps": []}
        for app in self._apps.values():
            if app["group"] in groups:
                groups[app["group"]]["apps"].append(app)
        return groups

    def get_flat_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for app in self._apps.values():
            label, display, group = app["app_label"], app["display_name"], app["group"]
            for page in app.get("pages", []):
                items.append({
                    "name": f"{display} — {page['name']}",
                    "url": page["url"],
                    "type": "page",
                    "icon": page.get("icon", app["icon"]),
                    "app_label": label,
                    "group": group,
                    "keywords": page.get("keywords", []),
                })
            for action in app.get("actions", []):
                items.append({
                    "name": action["name"],
                    "url": action["url"],
                    "type": "action",
                    "icon": action.get("icon", app["icon"]),
                    "app_label": label,
                    "group": group,
                    "keywords": action.get("keywords", []),
                })
        return items

    def get_searchables(self) -> dict[str, list[dict[str, Any]]]:
        return dict(self._searchables)

    def clear(self) -> None:
        self._apps.clear()
        self._searchables.clear()


nav_registry = NavRegistry()
```

- [ ] **Step 4: Create `src/phoresis_core/navigation/registry.py`**

```python
"""Auto-discovery of `nav.py` modules across installed apps.

Called from `PhoresisCoreConfig.ready()` — same pattern as Django's
`admin.autodiscover()`. nav.py modules **must not** import ORM models at
module level; defer to `apps.get_model(...)` inside functions if needed.
"""
from importlib import import_module

from django.apps import apps as django_apps
from django.utils.module_loading import module_has_submodule


def autodiscover_nav_modules() -> None:
    """Import `nav.py` from every installed app that has one."""
    for app_config in django_apps.get_app_configs():
        if module_has_submodule(app_config.module, "nav"):
            import_module(f"{app_config.name}.nav")
```

- [ ] **Step 5: Update `phoresis_core/apps.py` to call autodiscover**

Edit `src/phoresis_core/apps.py`. Find `# Navigation autodiscover is added in Task 10 (extends this method).` and replace with:

```python
        from .navigation.registry import autodiscover_nav_modules
        autodiscover_nav_modules()
```

- [ ] **Step 6: Run the navigation tests**

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_core/tests/test_navigation.py -v
```
Expected: 5 tests pass.

- [ ] **Step 7: Sanity-check that `manage.py check` still works**

```bash
.venv/Scripts/python.exe manage.py check
```
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 8: Commit**

```bash
git add src/phoresis_core/navigation/ src/phoresis_core/tests/test_navigation.py src/phoresis_core/apps.py
git commit -m "feat(phoresis_core): port NavRegistry singleton + nav.py autodiscover"
```

---

## Task 11: `dashboard` stub (home view + nav.py + INSTALLED_APPS wiring)

**Files:**
- Create: `src/dashboard/__init__.py`
- Create: `src/dashboard/apps.py`
- Create: `src/dashboard/views.py`
- Create: `src/dashboard/urls.py`
- Create: `src/dashboard/nav.py`
- Create: `src/dashboard/templates/dashboard/home.html`
- Create: `src/dashboard/tests/__init__.py`
- Create: `src/dashboard/tests/test_views.py`
- Modify: `src/phoresis/settings/base.py` (append `dashboard` to `INSTALLED_APPS`)
- Modify: `src/phoresis/urls.py` (include dashboard URLs at `/`)

- [ ] **Step 1: Write the failing tests**

`src/dashboard/tests/__init__.py`: empty.

`src/dashboard/tests/test_views.py`:
```python
"""Tests for the dashboard home view."""
import pytest
from django.urls import reverse

from accounts.tests.factories import UserFactory


@pytest.mark.django_db
def test_home_redirects_anonymous_to_login(client) -> None:
    response = client.get(reverse("dashboard:home"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


@pytest.mark.django_db
def test_home_returns_200_for_authenticated_user(client) -> None:
    user = UserFactory(username="jay")
    client.force_login(user)
    response = client.get(reverse("dashboard:home"))
    assert response.status_code == 200
    assert b"Phoresis" in response.content
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest src/dashboard/tests/test_views.py -v
```
Expected: FAIL — `NoReverseMatch` for `dashboard:home`.

- [ ] **Step 3: Create `src/dashboard/__init__.py`**

```python
"""Phoresis dashboard — landing page with KPIs (full version in Phase 3)."""
```

- [ ] **Step 4: Create `src/dashboard/apps.py`**

```python
"""App config for dashboard."""
from django.apps import AppConfig


class DashboardConfig(AppConfig):
    name = "dashboard"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Dashboard"
```

- [ ] **Step 5: Create `src/dashboard/views.py`**

```python
"""Dashboard views — Phase 1 stub."""
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


@login_required
def home_view(request: HttpRequest) -> HttpResponse:
    return render(request, "dashboard/home.html")
```

- [ ] **Step 6: Create `src/dashboard/urls.py`**

```python
"""URL config for the dashboard app."""
from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.home_view, name="home"),
]
```

- [ ] **Step 7: Create `src/dashboard/templates/dashboard/home.html`**

Self-contained — does not yet extend `phoresis_ui/components/base.html`. The polished version comes in Phase 3.

```django
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Phoresis — Dashboard</title>
</head>
<body>
    <header>
        <h1>Phoresis</h1>
        <nav>
            Welcome, {{ user }}.
            <a href="{% url 'accounts:profile' %}">Profile</a>
            <form method="post" action="{% url 'accounts:logout' %}" style="display:inline">
                {% csrf_token %}
                <button type="submit">Sign out</button>
            </form>
        </nav>
    </header>
    <main>
        <p>Welcome to Phoresis. Phase 1 bootstrap is live — the full dashboard arrives in Phase 3.</p>
    </main>
</body>
</html>
```

- [ ] **Step 8: Create `src/dashboard/nav.py`**

```python
"""Register the Dashboard app in the navigation registry."""
from phoresis_core.navigation import nav_registry

nav_registry.register_app(
    app_label="dashboard",
    display_name="Dashboard",
    group="Management",
    icon="layout-dashboard",
    url="/",
    pages=[{"name": "Home", "url": "/", "icon": "home"}],
    keywords=["home", "overview", "kpi"],
    shortcut_key="d",
)
```

- [ ] **Step 9: Wire `dashboard` into settings/base.py**

Edit `src/phoresis/settings/base.py`. Find:
```python
    # Phoresis apps
    "phoresis_core",
    "accounts",
    # dashboard (Task 11), phoresis_ui (Task 12) appended later.
```
Replace with:
```python
    # Phoresis apps
    "phoresis_core",
    "accounts",
    "dashboard",
    # phoresis_ui (Task 12) appended later.
```

- [ ] **Step 10: Wire `dashboard` URLs into the project**

Edit `src/phoresis/urls.py` — replace the file with:

```python
"""Root URLconf for the Phoresis project."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include(("accounts.urls", "accounts"), namespace="accounts")),
    path("", include(("dashboard.urls", "dashboard"), namespace="dashboard")),
]
```

- [ ] **Step 11: Run tests**

```bash
.venv/Scripts/python.exe -m pytest src/dashboard/tests/test_views.py -v
```
Expected: 2 tests pass.

- [ ] **Step 12: Re-run the previously-skipped accounts test**

```bash
.venv/Scripts/python.exe -m pytest src/accounts/tests/test_views.py::test_login_post_with_valid_creds_redirects_to_dashboard -v
```
Expected: PASS — the redirect to `dashboard:home` now resolves.

- [ ] **Step 13: Commit**

```bash
git add src/dashboard/ src/phoresis/settings/base.py src/phoresis/urls.py
git commit -m "feat(dashboard): add stub home view + nav.py registration"
```

---

## Task 12: `phoresis_ui` skeleton (templatetags + base.html stub)

**Files:**
- Create: `src/phoresis_ui/__init__.py`
- Create: `src/phoresis_ui/apps.py`
- Create: `src/phoresis_ui/templatetags/__init__.py`
- Create: `src/phoresis_ui/templatetags/ui_components.py`
- Create: `src/phoresis_ui/templatetags/ui_icons.py`
- Create: `src/phoresis_ui/templates/components/base.html`
- Create: `src/phoresis_ui/tests/__init__.py`
- Create: `src/phoresis_ui/tests/test_templatetags.py`
- Modify: `src/phoresis/settings/base.py` (append `phoresis_ui` to `INSTALLED_APPS`)

- [ ] **Step 1: Write the failing test**

`src/phoresis_ui/tests/__init__.py`: empty.

`src/phoresis_ui/tests/test_templatetags.py`:
```python
"""Tests for the phoresis_ui templatetag scaffolding."""
from django.template import Context, Template


def test_ui_components_load_without_error() -> None:
    Template("{% load ui_components %}").render(Context({}))


def test_ui_icons_load_without_error() -> None:
    Template("{% load ui_icons %}").render(Context({}))


def test_base_template_extends_render() -> None:
    template = Template(
        "{% extends 'components/base.html' %}{% block content %}HELLO{% endblock %}"
    )
    rendered = template.render(Context({}))
    assert "HELLO" in rendered
    assert "Phoresis" in rendered
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_ui/tests/test_templatetags.py -v
```
Expected: FAIL — `'ui_components' is not a registered tag library` (or similar).

- [ ] **Step 3: Create `src/phoresis_ui/__init__.py`**

```python
"""Phoresis UI — design system, templatetags, base templates."""
```

- [ ] **Step 4: Create `src/phoresis_ui/apps.py`**

```python
"""App config for phoresis_ui."""
from django.apps import AppConfig


class PhoresisUIConfig(AppConfig):
    name = "phoresis_ui"
    default_auto_field = "django.db.models.BigAutoField"
    verbose_name = "Phoresis UI"
```

- [ ] **Step 5: Create `src/phoresis_ui/templatetags/__init__.py`**

Empty file.

- [ ] **Step 6: Create `src/phoresis_ui/templatetags/ui_components.py`**

```python
"""UI component templatetags. Phase 1 stub — components ship in Phase 3."""
from django import template

register = template.Library()
```

- [ ] **Step 7: Create `src/phoresis_ui/templatetags/ui_icons.py`**

```python
"""Icon templatetags. Phase 1 stub — Lucide sprite ships in Phase 3."""
from django import template

register = template.Library()
```

- [ ] **Step 8: Create `src/phoresis_ui/templates/components/base.html`**

```django
{% load static %}
<!DOCTYPE html>
<html lang="en" data-theme="auto">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Phoresis{% endblock %}</title>
    {% block head %}{% endblock %}
</head>
<body>
    <header>
        <h1>Phoresis</h1>
    </header>
    <main>
        {% block content %}{% endblock %}
    </main>
    {% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 9: Wire `phoresis_ui` into settings/base.py**

Edit `src/phoresis/settings/base.py`. Find:
```python
    # Phoresis apps
    "phoresis_core",
    "accounts",
    "dashboard",
    # phoresis_ui (Task 12) appended later.
```
Replace with:
```python
    # Phoresis apps
    "phoresis_core",
    "accounts",
    "dashboard",
    "phoresis_ui",
```

- [ ] **Step 10: Run tests**

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_ui/tests/test_templatetags.py -v
```
Expected: 3 tests pass.

- [ ] **Step 11: Commit**

```bash
git add src/phoresis_ui/ src/phoresis/settings/base.py
git commit -m "feat(phoresis_ui): add Phase 1 skeleton — empty templatetags + base.html stub"
```

---

## Task 13: GitHub Actions CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Verify `.github/` directory exists**

```bash
ls -la .github 2>&1
```
If it doesn't exist:
```bash
mkdir -p .github/workflows
```

- [ ] **Step 2: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

env:
  DJANGO_SETTINGS_MODULE: phoresis.settings.test

jobs:
  lint:
    name: Lint (ruff)
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v3
      - name: Install dependencies
        run: uv sync --extra dev
      - name: Ruff check
        run: uv run ruff check .
      - name: Ruff format check
        run: uv run ruff format --check .

  test:
    name: Test (pytest, Postgres + Redis)
    runs-on: ubuntu-24.04
    services:
      postgres:
        image: postgres:17
        env:
          POSTGRES_DB: phoresis
          POSTGRES_USER: phoresis
          POSTGRES_PASSWORD: phoresis
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7
        ports: ['6379:6379']
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      DB_HOST: 127.0.0.1
      DB_PORT: 5432
      DB_NAME: phoresis
      DB_USER: phoresis
      DB_PASSWORD: phoresis
      REDIS_HOST: 127.0.0.1
      REDIS_PORT: 6379
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v3
      - name: Install dependencies
        run: uv sync --extra dev
      - name: Run migrations
        run: uv run python manage.py migrate --noinput
      - name: Pytest
        run: uv run pytest -v --create-db
```

- [ ] **Step 3: Validate workflow syntax locally (optional)**

If [`actionlint`](https://github.com/rhysd/actionlint) is installed:
```bash
actionlint .github/workflows/ci.yml
```
Expected: no output. If actionlint isn't installed, skip — GitHub validates on first push.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint + test workflow (ruff, pytest, Postgres 17, Redis 7)"
```

---

## Task 14: End-to-end smoke (full migrate, runserver, /admin/, all tests, tag v0.1.0)

Verification-only task — no new files. Confirms the Phase 1 deliverable works end-to-end before tagging `v0.1.0`.

- [ ] **Step 1: Apply all migrations against the local DB**

```bash
.venv/Scripts/python.exe manage.py migrate
```
Expected: applies migrations for `auth`, `contenttypes`, `sessions`, `admin`, `accounts` (0001 + 0002), `phoresis_core` (0001), `simple_history`. Last lines mention `0002_seed_groups` running.

- [ ] **Step 2: Verify the three groups exist**

```bash
.venv/Scripts/python.exe manage.py shell -c "from django.contrib.auth.models import Group; print(sorted(Group.objects.values_list('name', flat=True)))"
```
Expected: `['Admin', 'Lab User', 'Reviewer']`.

- [ ] **Step 3: Verify nav_registry picked up the dashboard registration**

```bash
.venv/Scripts/python.exe manage.py shell -c "from phoresis_core.navigation import nav_registry; print(list(nav_registry.get_apps().keys()))"
```
Expected: `['dashboard']` (the only nav.py in Phase 1).

- [ ] **Step 4: Create a superuser interactively**

```bash
.venv/Scripts/python.exe manage.py createsuperuser --username admin --email admin@phoresis.local
```
Enter a password when prompted. Expected: `Superuser created successfully.`

- [ ] **Step 5: Start the dev server (foreground in a separate terminal)**

```bash
.venv/Scripts/python.exe manage.py runserver 0.0.0.0:8000
```
Expected console output: loguru banner "Loguru configured", then Django dev server header at `http://0.0.0.0:8000/`.

- [ ] **Step 6: Curl the dashboard root (anonymous)**

```bash
curl -i -s http://127.0.0.1:8000/
```
Expected: `HTTP/1.1 302 Found` and `Location: /accounts/login/?next=/`.

- [ ] **Step 7: Curl the login page**

```bash
curl -s http://127.0.0.1:8000/accounts/login/ | head -20
```
Expected: HTML containing `Phoresis` and `<form method="post"`.

- [ ] **Step 8: Curl the admin**

```bash
curl -i -s http://127.0.0.1:8000/admin/
```
Expected: `HTTP/1.1 302 Found` and `Location: /admin/login/?next=/admin/`. Then:
```bash
curl -s http://127.0.0.1:8000/admin/login/ | head -10
```
Expected: HTML containing `Django administration`.

- [ ] **Step 9: Stop runserver and run the full test suite**

Stop the dev server (Ctrl+C in the runserver terminal). Then:
```bash
.venv/Scripts/python.exe -m pytest -v
```
Expected: ~37 tests pass total (4 model + 2 signals + 1 seed-groups + 6 view + 5 navigation + 9 error-handling + 3 celery_utils + 2 logging + 2 dashboard + 3 templatetags). Zero failures, zero errors.

- [ ] **Step 10: Run ruff one final time**

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
```
Expected: no errors. If anything is off, fix and re-stage before tagging.

- [ ] **Step 11: Run pre-commit one final time**

```bash
.venv/Scripts/python.exe -m pre_commit run --all-files
```
Expected: every hook passes.

- [ ] **Step 12: Tag v0.1.0**

```bash
git tag -a v0.1.0 -m "Phase 1: Bootstrap & shims — Django project, accounts, phoresis_core, dashboard stub, phoresis_ui skeleton, CI"
git log --oneline | head -20
git tag --list
```
Expected: `v0.1.0` listed.

- [ ] **Step 13: Final cleanup commit (only if Steps 10–11 surfaced fixes)**

If anything was auto-fixed:
```bash
git add -u
git commit -m "chore: ruff/pre-commit auto-fixes from Phase 1 final pass"
git tag -f v0.1.0 -m "Phase 1: Bootstrap & shims (re-tagged after final fixes)"
```

Otherwise, no commit needed — Phase 1 is complete.

---

## Acceptance criteria for Phase 1

This phase is **done** when ALL of the following hold:

1. `uv sync --extra dev` from a clean clone succeeds in under 2 minutes.
2. `python manage.py check` passes after every commit on the branch — no intermediate broken states.
3. `python manage.py migrate` applies cleanly against an empty Postgres 17 DB.
4. `python manage.py runserver` starts without warnings; `http://127.0.0.1:8000/admin/login/` and `http://127.0.0.1:8000/accounts/login/` render valid HTML.
5. The three groups `Lab User`, `Reviewer`, `Admin` exist after migration.
6. `pytest -v` runs end-to-end with 0 failures and 0 errors. Test count is approximately 37 (margin for additions during execution).
7. `ruff check .` and `ruff format --check .` are both clean.
8. `pre-commit run --all-files` is green.
9. `.github/workflows/ci.yml` is committed and YAML-valid.
10. The git tag `v0.1.0` exists pointing at the final Phase 1 commit.
11. App-level invariants from the spec §7.1–§7.5 that Phase 1 commits to are met:
    - `AUTH_USER_MODEL = "accounts.User"` (verified by `User.objects.create_user`).
    - `phoresis_core.ErrorLog` exists, has the expected source-type choices, and is registered in admin.
    - `phoresis_core.navigation.nav_registry` exists and `dashboard.nav` registers cleanly via autodiscover.
    - `phoresis_core.celery_app.app` is the project Celery instance, re-exported as `phoresis.celery_app`.
    - `phoresis_ui` is loadable; `{% load ui_components %}` and `{% load ui_icons %}` succeed.
