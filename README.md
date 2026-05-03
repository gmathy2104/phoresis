# Phoresis

> Standalone gel electrophoresis analysis platform — locally installable, modern UI, scientific-grade.

[![Status](https://img.shields.io/badge/status-bootstrap-orange)](docs/specs/2026-05-03-phoresis-standalone-design.md)
[![License](https://img.shields.io/badge/license-private-lightgrey)]()

Phoresis is a Django-based, self-hostable lab application for SDS-PAGE / Dot Blot / Western Blot gel image analysis. Extracted from a larger lab notebook monorepo, redesigned from scratch with a Tailwind 4 + HTMX 2 + Alpine.js 3 frontend, packaged as a single-command Docker install on Windows.

**Status:** project bootstrap. See the [design spec](docs/specs/2026-05-03-phoresis-standalone-design.md) for the full plan.

## Highlights

- 🧪 **Lane & band annotation** — interactive SVG editor with rectangle / quadrilateral / polygon lanes
- 🤖 **Hybrid band detection** — CV2 primary + d1/d2 derivative gap-fill + cross-lane consensus
- 📊 **Densitometry** — Gaussian peak fitting, normalization, purity computation, CSV export
- ⚖️ **MW calibration** — single & multi-ladder, Hungarian + RANSAC matching, polynomial smile correction
- 🎯 **Sample comparison** — side-by-side digital lanes, MW-aligned table, drag-reorder
- 📄 **Report generation** — Word, Excel, PowerPoint
- 🧠 **MobileSAM polygon refinement** — bbox → precise polygon via Meta's MobileSAM (CPU or CUDA)
- 🌓 **Dark/light auto** — full parity, smooth transitions, designed for long lab sessions

## Quick start (end-user)

> Phoresis is currently in pre-release. The one-command install will be available at v1.0.0.

```powershell
# Coming with v0.6.0:
.\scripts\install.ps1
```

Then open `https://phoresis/` in your browser.

## Quick start (developer)

> Coming with v0.1.0. See [DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Roadmap

7-phase build, ~3-5 weeks effort. See the full [design spec](docs/specs/2026-05-03-phoresis-standalone-design.md#12-roadmap-7-phases).

| Phase | Tag | Focus |
|---|---|---|
| 1 | v0.1.0 | Bootstrap & shims |
| 2 | v0.2.0 | Models & services extraction |
| 3 | v0.3.0 | Frontend foundation |
| 4 | v0.4.0 | Heavy viewers ported |
| 5 | v0.5.0 | Docker + Caddy packaging |
| 6 | v0.6.0 | CI/CD + install scripts |
| 7 | **v1.0.0** | Polish + docs + release |

## License

Private.
