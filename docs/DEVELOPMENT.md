# Development guide

This guide is for contributors working on the Phoresis codebase: cloning the repo, running the dev stack, executing the test suite, and following the project's coding / commit conventions. End users installing Phoresis from a release should read [INSTALL.md](INSTALL.md) instead.

## 1. Prerequisites

- **Python 3.12** (other 3.12.x patch releases are fine; 3.11 and 3.13 are untested).
- **Node.js 20 LTS** for the Tailwind 4 build pipeline.
- **PostgreSQL 17** running on the host. The dev stack assumes a `phoresis` superuser with password `phoresis` on `127.0.0.1:5432`.
- **Redis 7** for Celery's broker + result backend. Either install natively or run `docker run -p 6379:6379 redis:7`.
- **uv** ([astral-sh/uv](https://github.com/astral-sh/uv)) for Python dependency resolution and virtualenv management.
- **Docker Desktop** (Windows) — optional for local dev; required only if you want to exercise the production-like Caddy + container stack.

## 2. Clone + setup

```bash
git clone https://github.com/gmathy2104/phoresis.git
cd phoresis
git lfs pull                      # pulls the synthetic gel fixtures used by tests
uv sync --extra dev --extra cpu   # creates .venv/ and installs dev + runtime deps
npm install                       # Tailwind 4 + sprite tooling
```

`uv sync --extra dev --extra cpu` resolves `pyproject.toml` against the committed `uv.lock` so every contributor gets the same versions. The `--extra cpu` is what selects the CPU-only torch wheel from `download.pytorch.org/whl/cpu` — without it, `torch` is not installed (it lives in mutually-exclusive `cpu`/`cuda` extras so the right wheel comes from the right index in one shot, no `--reinstall-package` swap). On a workstation with a CUDA GPU you can use `--extra cuda` instead, which fetches torch cu128 directly. Pre-commit hooks (`ruff`, `trailing-whitespace`, `end-of-file-fixer`, secret scanner) are installed automatically by:

```bash
uv run pre-commit install
```

## 3. Database setup

Create the dev database and run migrations:

```bash
psql -U postgres -c "CREATE USER phoresis WITH PASSWORD 'phoresis' SUPERUSER;"
psql -U postgres -c "CREATE DATABASE phoresis OWNER phoresis;"

DB_HOST=127.0.0.1 DB_USER=phoresis DB_PASSWORD=phoresis DB_NAME=phoresis \
  .venv/Scripts/python.exe manage.py migrate

DB_HOST=127.0.0.1 DB_USER=phoresis DB_PASSWORD=phoresis DB_NAME=phoresis \
  .venv/Scripts/python.exe manage.py seed_groups

DB_HOST=127.0.0.1 DB_USER=phoresis DB_PASSWORD=phoresis DB_NAME=phoresis \
  .venv/Scripts/python.exe manage.py seed_ladder_templates

DB_HOST=127.0.0.1 DB_USER=phoresis DB_PASSWORD=phoresis DB_NAME=phoresis \
  .venv/Scripts/python.exe manage.py createsuperuser
```

The `DB_*` env-var prefix on every `manage.py` invocation is the project convention — `pyproject.toml` and `conftest.py` both expect it. You can also export the variables once per shell, but the docs (and CI logs) always show them inline so the snippet copy-pastes cleanly.

`seed_groups` creates the `Lab Users` permission group; `seed_ladder_templates` populates the standard MW ladders (Precision Plus, Spectra BR, etc.).

## 4. Run the dev server

Three terminals (or one terminal with three split panes):

```bash
# Terminal 1 — CSS rebuild on change
npm run watch:css

# Terminal 2 — Django dev server
DB_HOST=127.0.0.1 DB_USER=phoresis DB_PASSWORD=phoresis DB_NAME=phoresis \
  .venv/Scripts/python.exe manage.py runserver

# Terminal 3 (optional) — Celery worker, only needed for async band detection
DB_HOST=127.0.0.1 DB_USER=phoresis DB_PASSWORD=phoresis DB_NAME=phoresis \
  .venv/Scripts/python.exe -m celery -A phoresis_core.celery_app worker --loglevel=info -Q default,heavy
```

The dev server runs on `http://127.0.0.1:8000/`. The DRF browsable API is mounted at `/api/v1/`. Without the worker, any "detect bands (async)" action will sit in the queue forever — the synchronous detection path still works.

## 5. Tests

The suite is **525+ tests passing** across the apps, with 6 skipped (platform / optional-dependency cases) and 4 xfailed (pre-existing upstream scipy + `BandDetectionParams` quirks marked during the standalone extraction — see commit `2b4d527`).

```bash
DB_HOST=127.0.0.1 DB_USER=phoresis DB_PASSWORD=phoresis DB_NAME=phoresis \
  .venv/Scripts/python.exe -m pytest -v

# Just one app
DB_HOST=127.0.0.1 DB_USER=phoresis DB_PASSWORD=phoresis DB_NAME=phoresis \
  .venv/Scripts/python.exe -m pytest src/gel_analyzer/ -v

# Playwright e2e (Phase 4)
DB_HOST=127.0.0.1 DB_USER=phoresis DB_PASSWORD=phoresis DB_NAME=phoresis \
  .venv/Scripts/python.exe -m pytest -m e2e -v

# Coverage report -> htmlcov/
DB_HOST=127.0.0.1 DB_USER=phoresis DB_PASSWORD=phoresis DB_NAME=phoresis \
  .venv/Scripts/python.exe -m pytest --cov=src --cov-report=html
```

The 4 xfails are intentional — they document upstream scipy 1.14 behavior that the original code relied on, plus one `BandDetectionParams` validation quirk we preserve for fixture compatibility. They are NOT regressions and should not be "fixed" without coordination.

## 6. Code style & commit conventions

- **Lint + format** — `ruff check .` and `ruff format .` (configured in `pyproject.toml`, pinned to `0.15.12` in `.pre-commit-config.yaml`).
- **Pre-commit** — `pre-commit install` runs the hook chain on every `git commit`. Accept and re-stage any reformat the hooks produce.
- **Conventional Commits** — every commit on `main` is one of `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `build:`, `chore:`, `ci:`. `release-please` reads these to compute the next semver bump and to generate `CHANGELOG.md`. A breaking change uses `feat!:` or appends `BREAKING CHANGE:` in the trailer.

Examples:

```
feat(gel_analyzer): add hybrid band detector with progress streaming
fix(accounts): redirect to /login/ on session expiry
docs: add DEPLOYMENT.md (release flow, Watchtower, rollback)
refactor(phoresis_ui): extract card chrome into _card.html
```

## 7. Adding a Django app

1. Create `src/<app_name>/` with `__init__.py`, `apps.py`, and at minimum an empty `urls.py`.
2. Add the app's dotted path to `INSTALLED_APPS` in `phoresis_core/settings.py`.
3. If the app should appear in the global navigation, add a `nav.py` that registers entries via `phoresis_core.nav.register()`.
4. Generate the initial migration with `manage.py makemigrations <app_name>` and commit it.
5. Create `tests/` with at minimum a `test_smoke.py` to keep the suite balanced.

## 8. Adding a Celery task

Wrap the function with `@robust_task(...)` from `phoresis_core.celery_utils`:

```python
from phoresis_core.celery_utils import robust_task

@robust_task(soft_time_limit=300, time_limit=360)
def detect_bands_hybrid_bulk_task(analysis_uuid: str) -> dict:
    ...
```

`robust_task` wraps `@shared_task`, adds structured loguru logging on both entry and any uncaught exception, writes a row to `ErrorLog` on failure, and emits a `PHOR-` reference ID the user can quote when reporting a problem. If the task touches a model with a `RUNNING`-style status field (so a worker crash could leave the DB stuck), register the task in `STALE_TASK_REGISTRY` (`phoresis_core/celery_utils.py`) — the periodic janitor task will reset stale rows on the next beat tick.

## 9. Working with the design system

When adding or modifying UI: read [DESIGN.md §10 "Adding a new component"](DESIGN.md#10-adding-a-new-component) before reaching for ad-hoc Tailwind. Reusable chrome lives in `phoresis_ui/templatetags/ui_components.py`; tokens live in `phoresis_ui/static/phoresis_ui/css/tokens.css`. Don't introduce new colors or radii outside of `tokens.css` — they will fall out of light/dark sync.

## 10. Debugging tips

- **Loguru output** — the runserver logs to stderr in pretty colored format; the worker logs in JSON. Both honor `PHORESIS_LOG_LEVEL` from `.env`.
- **`/admin/phoresis_core/errorlog/`** — every `robust_task` failure ends up here with stack trace, args, and the `PHOR-` reference ID the user saw on the 500 page.
- **Django Debug Toolbar** — installed in dev only (gated by `DEBUG=True`); the SQL panel is the fastest way to spot N+1 queries.
- **`pytest -x --pdb`** — drops into the debugger on the first failing test. Combine with `-k "test_band_detection"` to narrow down.
- **`docker compose logs -f web worker`** — when running the production-like stack, this is the equivalent of the dev server output above.
