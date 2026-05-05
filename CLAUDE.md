# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read this first

[`AGENTS.md`](AGENTS.md) holds the **non-negotiable project policies** — no CDNs, Django comment syntax, Git LFS for ML models, Caddy/proxy headers, container init order, PowerShell 5.1 compatibility, media-volume safety, etc. Re-read it before any non-trivial change. The rules in there are scarred-by-incidents lessons; do not relitigate them.

Per-app deep-dives live under `src/<app>/docs/README.md` and architectural detail under `docs/ARCHITECTURE.md`.

## Project shape

Phoresis is a single-user, laptop-deployed gel-electrophoresis analyzer (SDS-PAGE / Dot Blot / Western Blot). Django 5.2 + DRF + Celery on the backend; Tailwind 4 + HTMX + Alpine on the frontend. Six-container Docker stack (Caddy + Django web + Celery worker + Celery beat + Redis + Watchtower) talking to a **native** PostgreSQL on the Windows host via `host.docker.internal:5432`.

Apps and dependency direction (strict, one-way):

```
phoresis_ui  (leaf design system)  ← imports nothing from feature apps
phoresis_core (loguru, Celery, ErrorLog, robust_task, nav registry)
accounts     → phoresis_core
gel_analyzer → phoresis_core, phoresis_ui, accounts   (the only feature app)
dashboard    → phoresis_core, phoresis_ui, gel_analyzer
```

Nothing imports from `dashboard`. `gel_analyzer` is theoretically extractable.

Source layout uses a **`src/` layout** with packages flat under it (`src/phoresis/`, `src/gel_analyzer/`, …). `pythonpath = ["src"]` is set in `pyproject.toml` so tests resolve them; the Django project module is `phoresis` (settings at `phoresis.settings.{base,dev,prod,test}`).

## Common commands

All `manage.py` invocations need DB env vars inline — this is the project convention copied verbatim into every doc and CI log:

```bash
DB_HOST=127.0.0.1 DB_USER=phoresis DB_PASSWORD=phoresis DB_NAME=phoresis \
  .venv/Scripts/python.exe manage.py <cmd>
```

| Task | Command |
|---|---|
| Install Python deps | `uv sync --extra dev` |
| Install Node deps | `npm install` |
| CSS rebuild (watch) | `npm run watch:css` |
| CSS one-shot build | `npm run build:css` (output: `src/phoresis_ui/static/phoresis_ui/css/output.css`) |
| Dev server | `… manage.py runserver` |
| Celery worker | `… python -m celery -A phoresis_core.celery_app worker --loglevel=info -Q default,heavy` |
| Migrations | `… manage.py migrate` / `makemigrations <app>` |
| Seed groups + ladders | `… manage.py seed_groups && … manage.py seed_ladder_templates` |
| Lint + format | `uv run ruff check .` and `uv run ruff format .` |
| Pre-commit (full) | `uv run pre-commit run --all-files` |
| Full test suite | `… python -m pytest -v` |
| Single app | `… python -m pytest src/gel_analyzer/ -v` |
| Single test | `… python -m pytest src/gel_analyzer/tests/test_x.py::TestY::test_z -v` |
| Speed-up (re-use DB) | add `--reuse-db`; use `--create-db` once after a new migration |
| Coverage | `… python -m pytest --cov=src --cov-report=html` |
| Playwright e2e (opt-in) | `… python -m pytest -m e2e -v` (`-m "not e2e"` is the default in `pyproject.toml`) |
| Production-like stack | `pwsh scripts/phoresis.ps1 <up|down|logs|…>` (always passes `--env-file <root>/.env -f docker/docker-compose.yml`) |

Pytest defaults (`pyproject.toml`): `DJANGO_SETTINGS_MODULE=phoresis.settings.test`, `pythonpath=["src"]`, `-m "not e2e"`. There are 4 intentional **xfails** documenting upstream scipy 1.14 + a `BandDetectionParams` quirk — do not "fix" them without coordination (see commit `2b4d527`).

## Async / Celery

Wrap every Celery task with `@robust_task(...)` from `phoresis_core.celery_utils` — it adds structured loguru logging, writes failures to `ErrorLog`, and emits a `PHOR-` reference id surfaced to the user on the 500 page. Tasks that flip a model status to `RUNNING` must register in `STALE_TASK_REGISTRY` (same module) so the periodic janitor can reset stuck rows. Heavy work (band detection) goes on the `heavy` queue so it never blocks the `default` queue.

Long-running endpoints follow the **enqueue + poll** pattern: HTTP 202 + `task_id` returned synchronously; browser polls `/api/celery-task/<id>/status/` every 1s; tasks publish progress via `update_state(state="PROGRESS", meta={"percent": …})`.

## Settings & path conventions

- Anything pointing at a writable filesystem path (`STATIC_ROOT`, `MEDIA_ROOT`, log dirs, ML model dirs) **must** be `os.environ`-overridable with a sensible local-dev fallback. Hard-coding `BASE_DIR / "X"` breaks the moment the container runs read-only — see AGENTS.md §5.
- ML model paths anchor on `SRC_DIR` (`= BASE_DIR / "src"`), **not** `BASE_DIR`, because source is `COPY`d to `/app/src/...` in the image.
- `accounts.backends.EmailOrUsernameModelBackend` accepts both username and email (case-insensitive on email). The installer always asks for an email; users naturally try logging in with it.

## Release flow

Conventional Commits on `main` → `release-please` keeps a draft Release PR open → merging it tags `vX.Y.Z`, triggers a single CPU build, and publishes `ghcr.io/gmathy2104/phoresis-app:{vX.Y.Z,latest}-cpu`. The same image runs as web (`gunicorn`), worker (`celery worker`), and scheduler (`celery beat`) — they differ only by the runtime CMD and a couple of `SKIP_*` env flags. **CUDA images are not shipped via CI by design** — GPU users build locally on `update.ps1` (CUDA build uses `--extra cuda` via `[tool.uv.sources]` in `pyproject.toml`, no two-step torch swap). Watchtower polls `:latest-cpu` (or `:latest-cuda` if `PHORESIS_IMAGE_VARIANT=cuda`) at 03:00 daily and recreates the three `web` / `worker` / `scheduler` containers; Caddy and Redis intentionally lack the watchtower label.

Direct pushes to `main` were authorised for the v1.0.x bug-hunt cycle. From v1.1.x onward, prefer PRs unless the user explicitly says otherwise.

## Reminders that keep biting

- `{# … #}` is **single-line only** in Django templates. Multi-line means `{% comment %} … {% endcomment %}`. Run `grep -rn '{#[^#]*$' src/` before committing template changes (AGENTS.md §2 — shipped 3× already).
- Never reference a CDN. Vendor everything under `src/<app>/static/<app>/{js,css}/vendor/` and reference via `{% static %}`. For dynamic ES `import()`, expose the URL through `window.PHORESIS_URLS.<key>` in `base.html` so WhiteNoise's manifest hash applies (AGENTS.md §1).
- Wrap every `localStorage` / `sessionStorage` access in `try/catch` — Edge Tracking Prevention / Safari Lockdown / Firefox Strict throw `SecurityError` and an unguarded throw inside `alpine:init` kills every `$store.*` on the page (AGENTS.md §3). Reference helpers: `safeLocalGet` / `safeLocalSet` in `src/phoresis_ui/static/phoresis_ui/js/alpine-init.js`.
- Media lives in the **external named volume** `phoresis_phoresis_media`, not a host bind-mount. `docker compose down -v` cannot wipe it; the only supported wipe path is `scripts/wipe-media.ps1` (auto-backs up + 3 confirmations). Don't change the `external: true` declaration (AGENTS.md §9).
- Git LFS holds the ML model binaries (`src/gel_analyzer/static/gel_analyzer/ml/...`). A clone without git-lfs leaves 134-byte pointer files; the worker fails opaquely inside onnxruntime. `install.ps1` has a guard for this — leave it (AGENTS.md §4).
- PowerShell scripts must run on **Windows PowerShell 5.1** (no em-dashes/smart quotes in source, no `-SkipCertificateCheck`, use `curl.exe -k` and `-o NUL`). See AGENTS.md §10.
