# Phoresis

> Standalone gel electrophoresis analysis platform — runs on your laptop, no cloud.

![Phoresis dashboard](docs/images/hero-dashboard.png)

[![Status](https://img.shields.io/badge/status-v1.0.0-brightgreen)](CHANGELOG.md)
[![License](https://img.shields.io/badge/license-private-lightgrey)](LICENSE)

Phoresis is a Django-based lab application for SDS-PAGE, Dot Blot, and Western Blot gel image analysis. Originally extracted from a larger lab notebook monorepo, it ships as a single-command Docker install on Windows 11 with a modern Tailwind 4 + HTMX + Alpine frontend.

## Features

- **Lane and band annotation** — interactive SVG editor with rectangle, quadrilateral, and polygon lanes; MobileSAM (ONNX) polygon refinement.
- **Hybrid band detection** — CV2 primary + d1/d2 derivative gap-fill + cross-lane consensus.
- **MW calibration** — single and multi-ladder; Hungarian + RANSAC matching; polynomial smile correction.
- **Densitometry** — Gaussian peak fitting, deconvolution, normalization, POI purity, CSV export.
- **Lane comparison** — side-by-side digital lanes, electropherograms, MW-aligned cross-lane view.
- **Report generation** — Word, Excel, PowerPoint exports.
- **Dark / light auto** — full parity, smooth transitions, designed for long lab sessions.
- **Local install + auto-update** — no cloud, no telemetry. Watchtower pulls new images at 03:00 daily.

## Installation (Windows 11)

Step-by-step. First run takes 10–25 minutes depending on whether you have a GPU.

### 1. Clone the repository

```powershell
git clone https://github.com/gmathy2104/phoresis.git
cd phoresis
git lfs pull
```

The `git lfs pull` step downloads the bundled ML models (~108 MB: YOLO + MobileSAM ONNX). Skip it and the app will start but band detection won't work.

### 2. Run the installer (one command, as Administrator)

Right-click PowerShell → "Run as Administrator", then:

```powershell
.\scripts\install.ps1
```

The script is **idempotent** — re-runnable safely if anything is interrupted. It does, in order:

| Step | What | Notes |
|---|---|---|
| 1 | Verifies Windows 10/11 + admin elevation | exits early if not |
| 2 | Installs Docker Desktop via `winget` if missing | needs sign-out/sign-in for WSL2; script asks you to re-run |
| 3 | Installs PostgreSQL 17 via `winget` if missing | you set the `postgres` superuser password during install |
| 4 | Provisions the `phoresis` DB + user (asks for `postgres` password once) | idempotent — does nothing if already created |
| 5 | Detects your GPU via `nvidia-smi` | sm_75+ → CUDA variant; otherwise CPU. Override with `-Variant cpu` or `-Variant cuda` |
| 6 | Adds `127.0.0.1 phoresis` to your hosts file | for `https://phoresis/` |
| 7 | Creates `%USERPROFILE%\Phoresis-Data\media\` (host bind-mount) | overridable with `-DataDir D:\Phoresis-Data` |
| 8 | Migrates from a legacy `phoresis_media` Docker volume if present | one-shot |
| 9 | Generates `.env` (asks: admin email/password, primary lab user email/password/name) | only on first run; delete `.env` to regenerate |
| 10 | **CPU**: pulls `ghcr.io/gmathy2104/phoresis-{web,worker}:latest-cpu` from GHCR<br>**CUDA**: builds the images locally with `docker compose build` (~15-25 min one-time, fast on subsequent updates thanks to layer cache) | CUDA images are NOT shipped via CI by design — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) §"CI/CD flow" |
| 11 | `docker compose up -d` brings up Caddy + Django + Celery worker + Celery beat + Redis + Watchtower | |
| 12 | Waits for `https://phoresis/healthz/live/` to return 200 | up to 90 s |
| 13 | Trusts Caddy's self-signed root CA so the browser accepts `https://phoresis/` | |
| 14 | Creates a `Phoresis.lnk` desktop shortcut wired to `start.ps1` | |
| 15 | Opens `https://phoresis/` in your default browser | |

### 3. First-time database setup happens automatically

Inside the running web container, the entrypoint runs:

```bash
python manage.py migrate              # applies all migrations
python manage.py seed_groups          # creates the 3 default groups (Lab User / Reviewer / Admin)
python manage.py seed_ladder_templates # seeds standard MW ladders
python manage.py create_initial_users --from-env --skip-existing
                                      # creates admin + primary lab user from .env values
python manage.py collectstatic --noinput  # bakes static files
```

You don't have to run any of these by hand. Sign in with the **primary lab user** credentials you entered in step 9.

### 4. Daily use

Double-click the **Phoresis** desktop shortcut, or run:

```powershell
.\scripts\start.ps1     # bring the stack up + open the browser
.\scripts\stop.ps1      # stop the stack (volumes preserved; cannot wipe user data)
```

### 5. Updating the application

```powershell
.\scripts\update.ps1            # pull or rebuild images, run migrations, restart
.\scripts\update.ps1 -Rollback v1.0.0   # roll back to a specific tag
```

CPU users get auto-updates from Watchtower at 03:00 daily (pulls latest GHCR image, runs migrations on container restart). GPU users update manually via `update.ps1`, which rebuilds the CUDA images locally.

### 6. Backups

```powershell
.\scripts\backup.ps1    # pg_dump + media tar to %USERPROFILE%\Phoresis-Backups\YYYY-MM-DD_HHmmss
.\scripts\restore.ps1   # interactive snapshot picker
```

Schedule daily backups via Windows Task Scheduler — see [CONTRIBUTING.md](CONTRIBUTING.md) §"Scheduled backups".

### Troubleshooting

If anything in step 2 misbehaves, see [docs/INSTALL.md](docs/INSTALL.md) for screenshots and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) §"Common troubleshooting".

## Screenshots

| | |
|---|---|
| ![Annotate](docs/images/annotate-viewer.png) | ![Densitometry](docs/images/densitometry-view.png) |
| Lane and band annotation editor | Densitometry view with electropherogram |
| ![Comparison](docs/images/comparison-view.png) | ![Theme toggle](docs/images/theme-toggle.png) |
| Cross-lane comparison | Light / dark theme switch |

## For developers

Clone, install deps, run dev server:

```bash
git clone https://github.com/gmathy2104/phoresis.git
cd phoresis && git lfs pull
uv sync --extra dev
npm install
DB_HOST=127.0.0.1 DB_USER=phoresis DB_PASSWORD=phoresis DB_NAME=phoresis \
  .venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py runserver
```

Full guide: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Architecture

Phoresis runs as a six-container Docker stack (Caddy + Django web + Celery worker + Celery beat + Redis + Watchtower) talking to a native PostgreSQL on the Windows host. Media files live at a host bind-mount path (`%USERPROFILE%\Phoresis-Data\media`), not in a Docker volume — so `docker compose down -v` cannot wipe user data. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design with Mermaid diagrams.

## Documentation

- [INSTALL.md](docs/INSTALL.md) — end-user installation walkthrough
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — apps, containers, data flow, CI/CD
- [DEVELOPMENT.md](docs/DEVELOPMENT.md) — clone, deps, run, tests, conventions
- [DEPLOYMENT.md](docs/DEPLOYMENT.md) — release flow, Watchtower, rollback, troubleshooting
- [DESIGN.md](docs/DESIGN.md) — design tokens, component catalogue, animations, accessibility
- [CHANGELOG.md](CHANGELOG.md) — release notes per version
- [CONTRIBUTING.md](CONTRIBUTING.md) — Conventional Commits, release flow, scheduled backups

Per-app deep-dives: [phoresis_core](src/phoresis_core/docs/README.md) · [accounts](src/accounts/docs/README.md) · [gel_analyzer](src/gel_analyzer/docs/README.md) · [dashboard](src/dashboard/docs/README.md) · [phoresis_ui](src/phoresis_ui/docs/README.md).

## License

See [LICENSE](LICENSE).

## Acknowledgements

- Original `gel_analyzer` lineage from `ds-hub-django` (the multi-app lab platform Phoresis was extracted from).
- [MobileSAM](https://github.com/ChaoningZhang/MobileSAM) for polygon refinement.
- [Lucide Icons](https://lucide.dev/) for the icon system (curated subset).
- [Tailwind CSS 4](https://tailwindcss.com/), [HTMX](https://htmx.org/), [Alpine.js](https://alpinejs.dev/), [Django](https://www.djangoproject.com/), [Caddy](https://caddyserver.com/).
