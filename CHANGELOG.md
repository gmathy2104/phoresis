# Changelog

All notable changes to Phoresis are documented here.

This file is auto-generated from [Conventional Commits](https://www.conventionalcommits.org/)
by [release-please](https://github.com/googleapis/release-please) on every tagged release.

For a human-readable explanation of each phase milestone, see `docs/specs/`.

---

## [1.0.10] - 2026-05-04

### install.ps1: support coexisting Postgres versions

- New `-DBPort <int>` parameter on `install.ps1` (default 5432) for hosts that already run another Postgres on 5432 — typical case: an existing PG13/14/15/16 on 5432, freshly-installed PG17 forced to 5433. The script now passes `-p $DBPort` to `psql` for DB provisioning and writes `DB_PORT=$DBPort` to `.env`. Detected during the first real install on a workstation that had PG16 + PG17 cohabiting.

## [1.0.9] - 2026-05-04

### install.ps1 robustness fix

- **`winget` resolution in elevated sessions**: `winget.exe` lives under `%LOCALAPPDATA%\Microsoft\WindowsApps` (USER PATH) but admin/elevated PowerShell sessions sometimes inherit only the SYSTEM PATH, leaving `winget` "not found" even when installed. Added `Resolve-Winget` helper in `_common.ps1` that falls back to the well-known location, plus actionable error messages pointing to the manual install URL when winget is genuinely absent.
- **Postgres 17 detection**: also probes `C:\Program Files\PostgreSQL\17\bin\psql.exe` and prepends to `$env:PATH` for the current session if found. Removes the "install Postgres → restart PowerShell → re-run install.ps1" loop when the installer was just run but the new shell hasn't been opened.

## [1.0.8] - 2026-05-04

### CI frontend cache fix

- **`package-lock.json` now committed.** The `actions/setup-node@v5` step in `ci.yml` uses `cache: "npm"` which requires the lockfile to be present in the repo root to compute its cache key. Phase 3 Task 1 had `.gitignored` the lockfile with a note "commit in Phase 5 (Docker reproducibility)" but Phase 5 never honored it — same oversight pattern as `uv.lock`, which was eventually committed in v1.0.0. Fix: dropped `package-lock.json` from `.gitignore` and committed the 46 KB file pinning Tailwind 4.2.4 + 45 transitive deps. Verified locally with a fresh `rm -rf node_modules && npm ci` which completes cleanly.

## [1.0.7] - 2026-05-04

### CI simplification + dev workflow improvements

- **`release.yml` ships CPU images only** (descope CUDA matrix). CUDA users build locally during `install.ps1` — fast on a real GPU machine, avoids GitHub-runner disk/time ceilings, eliminates matrix complexity. Drops 2 of 4 jobs from the release pipeline; CPU build now reliable in ~10 min.
- **`install.ps1` + `update.ps1`** branch on `PHORESIS_IMAGE_VARIANT`: CPU pulls from GHCR, CUDA does `docker compose build --build-arg TORCH_VARIANT=cuda` locally. One-time ~15-25 min build; subsequent rebuilds cheap thanks to the new cache mounts.
- **Dockerfile cache mounts**: added `--mount=type=cache,target=/root/.cache/uv` and `--mount=type=cache,target=/var/cache/apt` to all 4 deps stages (Dockerfile.web + Dockerfile.worker × CPU + CUDA). Marginal pyproject.toml/uv.lock changes now skip re-downloading the unchanged 90% of wheels — local rebuild ~5 min → ~20 s.
- **`docker/compose.dev.yml`**: new dev override that bind-mounts `./src`, `./manage.py`, `./conftest.py` into web + worker + scheduler containers, swaps gunicorn for `manage.py runserver` (Django auto-reloads), and switches `DJANGO_SETTINGS_MODULE` to `dev`. Pair with `npm run watch:css` on the host. Use: `docker compose -f docker/docker-compose.yml -f docker/compose.dev.yml up`.
- **README.md installation section**: rewrote with clear step-by-step (clone → `install.ps1` → first-boot DB setup → daily use → updates → backups → troubleshooting). Documents the auto-run migrations / `seed_groups` / `seed_ladder_templates` / `create_initial_users` flow.

## [1.0.6] - 2026-05-04

### CUDA build runner disk space fix

- **`release.yml` build-and-push job**: added `jlumbroso/free-disk-space@main` step gated on `if: matrix.variant == 'cuda'`. The CUDA images push the ubuntu-24.04 runner past its ~14 GB free disk (CUDA 12.8 base ~3 GB + 90 wheels including duplicated nvidia-cublas/cudnn ~6-8 GB + uv cache). Verified via run 25309016114 logs: `Free space left: 0 MB` then `failed to copy to ... No space left on device (os error 28)` during `uv sync`. The action frees ~28 GB by removing preinstalled Android SDK / .NET / Haskell toolchains we don't need. Targeted with `tool-cache: true` only — leaves docker-images and swap intact.

## [1.0.5] - 2026-05-04

### CUDA build pipeline fix

- **Dockerfile.{web,worker} CUDA stages**: reordered the install steps. Previously installed `torch torchvision` from cu128 first, then ran `uv sync --frozen` — which exited with code 2 because the manually-installed `torch==X.Y.Z+cu128` doesn't match `uv.lock`'s `torch==X.Y.Z` (no local version tag). New order: `uv sync --frozen` first (gets the full dep tree from lockfile, including CPU torch ~700 MB), then `uv pip install --reinstall-package torch --reinstall-package torchvision --extra-index-url cu128 torch torchvision` to swap them for cu128 builds. Adds ~700 MB of redundant download but keeps the lockfile as single source of truth and the build deterministic.

## [1.0.4] - 2026-05-04

### CI workflow validation fix

- **`ci.yml` codecov step**: GitHub Actions rejected the workflow with `Unrecognized named-value: 'secrets'` because `secrets.CODECOV_TOKEN` was used inside an `if:` expression (forbidden anti-exfiltration measure). Hoisted the secret into a job-level `env.CODECOV_TOKEN`, then changed the conditional to `if: env.CODECOV_TOKEN != ''`. Same behavior, valid syntax.

## [1.0.3] - 2026-05-04

### Blackwell (RTX 50-series) GPU support

- **Dockerfile.{web,worker} CUDA stages**: bumped base image from `nvidia/cuda:12.1.1-runtime-ubuntu24.04` to `nvidia/cuda:12.8.0-runtime-ubuntu24.04`, and PyTorch wheel index from `cu121` to `cu128`. CUDA 12.1 didn't include sm_120 PTX, so torch on RTX 50-series would silently fall back to CPU. Verified locally on an RTX 5090 (compute capability 12.0): `torch.cuda.is_available() == True`, `torch.version.cuda == '12.8'`, GEMM 2048×2048 runs on the GPU, all values finite. Backwards-compatible: cu128 supports sm_70+ (Volta and newer), covering RTX 20/30/40/50-series, GTX 16, and Quadro RTX/Tesla V100.
- **`install.ps1` GPU detection**: now also reads `compute_cap` from `nvidia-smi`. If the lowest compute capability across all detected GPUs is < 7.5 (pre-Volta: Pascal GTX 10-series and older), falls back to the CPU image with a clear warning. Override remains possible via `-Variant cuda`.

## [1.0.2] - 2026-05-04

### Build pipeline fixes

- **Dockerfile uv sync**: COPY `uv.lock` alongside `pyproject.toml` and use `uv sync --no-dev --no-install-project --frozen`. Previously the build tried to install the local `phoresis` package during the deps stage and failed with `OSError: Readme file does not exist: README.md` (only `pyproject.toml` was COPY'd at that point). The local package isn't needed during deps install — source is COPY'd later in the runtime stage. Affects all 4 image variants.
- **CUDA base image**: switched from `nvidia/cuda:12.1.1-runtime-ubuntu22.04` + deadsnakes PPA + `python3.12` apt-install (fragile, recently breaking) to `nvidia/cuda:12.1.1-runtime-ubuntu24.04` which ships Python 3.12 natively. Drops `software-properties-common`, `gnupg`, `add-apt-repository` from the CUDA stage.
- **GitHub Actions versions bumped** to clear Node.js 20 deprecation warnings: `actions/checkout@v4 → v5`, `actions/setup-node@v4 → v5`, `astral-sh/setup-uv@v3 → v6`, `codecov/codecov-action@v4 → v5`, `aquasecurity/trivy-action@0.28.0 → 0.30.0`. Docker actions (`setup-buildx-action`, `build-push-action`, `login-action`) stay on v3/v6 — their maintainers will publish Node 24 versions before the June 2026 cutoff.

## [1.0.1] - 2026-05-04

### Post-v1 hardening pass

- Branded `handler400` (Bad request) and `handler403` (Access denied / CSRF failure) pages wired in `phoresis_core.error_handling.views`. Same chrome and CTAs as the existing 404 / 500.
- `prefers-reduced-motion` media query in `input.css` neutralizes ripple, shimmer, dropzone pulse, and long transitions for users with system "Reduce motion" enabled. App stays fully functional.
- `CELERY_WORKER_MAX_TASKS_PER_CHILD = 50` (env-overridable via `CELERY_WORKER_MAX_TASKS_PER_CHILD`) so prefork children recycle to release memory after the ~100 MB ONNX models loaded by band-detection / SAM / densitometry services.

## [1.0.0] - 2026-05-04

### Phase 7 — Polish + docs + v1.0.0

- Micro-interactions: button ripple, HTMX top progress bar, sidebar icon scale on hover, dropzone pulse, floating labels.
- Branded 404 / 500 pages with `PHOR-YYYYMMDD-XXXXXX` reference IDs surfaced from the `ExceptionContextMiddleware`.
- Full documentation suite: root `README.md`, `docs/{ARCHITECTURE,DESIGN,DEVELOPMENT,DEPLOYMENT,INSTALL}.md`, plus per-app `README.md` files (5 apps).
- Pre-v1 cleanup: switched component badge variants to design tokens, escaped `</script>` breakout in `nav_palette_items_json`, made `{% btn disabled=True href=... %}` produce a11y-correct disabled anchors, replaced hardcoded URLs in sidebar + alpine-init with `{% url %}` reverses, removed legacy `_layout.html` (replaced by `app_base.html` in Phase 3), committed `uv.lock` for reproducible Docker builds.
- Media files moved from a Docker named volume to a host bind-mount at `${PHORESIS_MEDIA_DIR}` (default `%USERPROFILE%\Phoresis-Data\media`), so `docker compose down -v` cannot wipe user data.

## [0.6.0] - 2026-05-04

### Phase 6 — CI/CD + install scripts

- `release-please` config + initial `CHANGELOG.md`.
- `ci.yml` extended with frontend build, e2e (Playwright Chromium), Docker image build smoke, Trivy CVE scan.
- `release.yml` with 4-variant matrix build `(cpu, cuda) × (web, worker)`, GHCR push, GitHub Release with SBOM.
- 7 PowerShell scripts: `install.ps1` (clean-machine), `start.ps1` / `stop.ps1` (daily), `update.ps1` (with `-Rollback`), `backup.ps1` / `restore.ps1` (pg_dump + media tar, 30-day retention), plus `_common.ps1` shared helpers.
- Watchtower credentials story documented (PUBLIC GHCR by default, private fallback in 3 steps).

## [0.5.0] - 2026-05-04

### Phase 5 — Docker + Caddy packaging

- Healthz endpoints (`/healthz/`, `/healthz/celery/`, `/healthz/live/`).
- `seed_groups` management command.
- Multi-stage `Dockerfile.web` and `Dockerfile.worker` (CPU + CUDA variants).
- `Caddyfile` with `tls internal`, HSTS, static/media file serving.
- Six-service `docker-compose.yml` (Caddy / web / worker / scheduler / Redis / Watchtower).
- `compose.gpu.yml` override for NVIDIA Container Toolkit.

## [0.4.0] - 2026-05-03

### Phase 4 — Heavy viewers + DRF API + e2e

- 6 DRF viewsets + ~50 non-DRF JSON endpoints.
- Annotation, densitometry, comparison heavy viewers in Tailwind chrome.
- Report builders (docx / xlsx / pptx).
- Playwright golden-path e2e.

## [0.3.0] - 2026-05-03

### Phase 3 — Frontend foundation

- Tailwind 4 + design tokens + 9 component templatetags.
- Lucide sprite + 8 custom SVG icons.
- Alpine stores (theme / toast / modal / palette) + HTMX config.
- Layout shell (sidebar / topbar / command palette).
- Theme switcher with `UserProfile.theme` persistence.
- Phoresis app icon.
- Refonte of login / profile / dashboard / image and analysis shell pages.

## [0.2.0] - 2026-05-03

### Phase 2 — Models & services extraction

- 14 models cleaned of `process_sample`, FKs to `accounts.User`, +`sample_metadata`.
- All scientific services preserved (band_detection, calibration, densitometry, SAM, file_handler, scn_parser, template_learning, studio).
- 9 Celery tasks.
- ML models bundled (Git LFS).
- Admin ported.
- `seed_ladder_templates` + `create_initial_users` commands.

## [0.1.0] - 2026-05-03

### Phase 1 — Bootstrap & shims

- Django 5.2 project with split settings.
- `phoresis_core` (logging, celery, error handling, navigation registry).
- `accounts` app with custom `User` + `UserProfile` + 3 seeded groups.
- `dashboard` stub + `phoresis_ui` skeleton.
- pytest, ruff, pre-commit, GitHub Actions baseline CI.
