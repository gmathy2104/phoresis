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

## Quick start (end-user)

```powershell
# Run as Administrator
.\scripts\install.ps1
```

Five minutes later (warm cache; 10–20 minutes cold), `https://phoresis/` opens in your browser. See [docs/INSTALL.md](docs/INSTALL.md) for the full walkthrough.

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
