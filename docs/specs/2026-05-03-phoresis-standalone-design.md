# Phoresis — Standalone Gel Analyzer — Design

**Date:** 2026-05-03
**Status:** Draft (pending user review)
**Scope:** Brand-new repository, extracted from `ds-hub-django/gel_analyzer/`
**Repo:** `gmathy2104/phoresis` (private GitHub) — images at `ghcr.io/gmathy2104/phoresis-{web,worker}`
**Target user:** A single primary lab user (project author's wife), running on her own Windows 11 ASUS laptop, with the option to scale to a small lab team later.
**Production URL:** `https://phoresis/` (local, via host file + Caddy auto-HTTPS)

---

## 1. Problem statement

The `gel_analyzer` Django app inside `ds-hub-django` (a large biopharmaceutical lab notebook monorepo) is a feature-complete gel electrophoresis analysis platform. The primary user uses it daily for SDS-PAGE, Dot Blot and Western Blot analysis: lane/band annotation, MW calibration, hybrid CV2+derivative band detection, MobileSAM polygon refinement, densitometry, sample comparison, Word/Excel/PowerPoint reports.

Today the application is only accessible through the central ds-hub-django deployment, which:

1. Is hosted on shared corporate infrastructure (Azure), not portable.
2. Is tied to features she does not use (CDW Databricks integration, ProcessSample workflow, multi-app navigation).
3. Has a UI built on MDB5 (Material Design Bootstrap 5), which we want to replace with a modern Tailwind/HTMX/Alpine stack of significantly higher visual quality.
4. Cannot be installed locally on her laptop for offline / off-network usage.

**Goal:** extract `gel_analyzer` into a standalone, locally-installable Django project named **Phoresis**, with a redesigned modern UI, fully containerized except for Postgres (which stays native on her host for data safety), and ship-quality auto-update via GitHub Container Registry + Watchtower.

## 2. Goals

- **G1.** Preserve 100% of the scientific functionality of `gel_analyzer` (band detection, calibration, densitometry, comparison, ladder templates, MobileSAM, hybrid detection, cross-lane consensus, reports, YOLO inference, all Celery tasks).
- **G2.** Eliminate every coupling to apps outside `gel_analyzer/` (`process_development.ProcessSample`, `process_development.SampleAnalysis`, `authentication.UserProxy`, `cdw_explorer`, `databricks`).
- **G3.** Replace MDB5 entirely with a hand-crafted Tailwind 4 + HTMX 2 + Alpine.js 3 design system that delivers a distinctly modern visual identity (Linear / Vercel / Notion class).
- **G4.** Package the app for one-click install on Windows 11 with full Docker stack (web, worker, scheduler, redis, caddy, watchtower) + native Postgres host install.
- **G5.** Auto-update via `ghcr.io` + Watchtower with no user intervention.
- **G6.** Stay "upscale-ready": multi-user-capable Django auth from day one, modular Django apps so future analyzers (DLS, CPS, Western blot variants) can be added cleanly.
- **G7.** Provide complete, kept-current documentation (architecture, install for end-user, dev onboarding, deployment).

## 3. Non-goals

- **N1.** No CDW / Databricks / ProcessSample integration. Lanes use a free-text `sample_name` plus an extensible `sample_metadata` JSONField. Code comments document how to reintroduce a hard FK or generic relation later if needed.
- **N2.** No multi-tenant / SaaS posture. Single primary user, possibly a few colleagues over LAN later. No org/team hierarchy.
- **N3.** No data migration from ds-hub-django. **Fresh start** — primary user re-uploads gels she actively works on; old data stays accessible in ds-hub-django for archival.
- **N4.** No mobile/tablet UI. Desktop-only (laptop).
- **N5.** No DirectML / AMD / Intel GPU support in v1. NVIDIA CUDA detected and used if available, fallback to CPU otherwise.
- **N6.** No SaaS-grade observability (no Datadog, no Prometheus). Sentry is optional and disabled by default. Local logs + admin-side `/admin/system/` dashboard suffice.
- **N7.** Code reuse from `ds-hub-django` is by **copy-and-clean**, not by `git filter-repo` history preservation. The original repo remains the historical source-of-truth.

## 4. Decision log (resolved during brainstorm)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Multi-user Django auth from day one (`AUTH_USER_MODEL = "accounts.User"`, 3 seeded groups) | "Upscale-ready" principle — avoid painful auth migration later if a colleague needs access. |
| D2 | Tailwind 4 + HTMX 2 + Alpine.js 3 frontend stack | Best fit with Django, plays well with the existing vanilla-JS interactive viewers, lets us achieve high design quality fast. |
| D3 | Fresh start — no data migration from ds-hub-django | Simplifies extraction; old data stays in ds-hub-django. |
| D4 | Hybrid packaging — Postgres NATIVE on Windows host, rest in docker-compose | Protects user data from `docker compose down -v` accidents. Trades one-time install friction for long-term safety. |
| D5 | Fresh repo from scratch (no git history import) | Cleanest path. Original repo remains consultable for blame/debug if needed. |
| D6 | Project name: **Phoresis** | Scientific, distinct, scales beyond gels (could later cover capillary electrophoresis, blots, etc.). |
| D7 | Auto-update via `ghcr.io` + Watchtower; image visibility (public vs private) decided at Phase 6, default-leaning **public** | Zero-friction for end-user; image contains no secrets so public is acceptable; private fallback documented. |
| D8 | Auto light/dark theme with full parity, accent: **deep lab blue** with **magenta accents** for bands/peaks | Most professional + durable; magenta evokes ethidium-bromide stained gels. |
| D9 | Multi-app structure (`phoresis_core` + `accounts` + `gel_analyzer` + `dashboard` + `phoresis_ui`) | Better long-term structure; easy to add future analyzers without refactoring. |
| D10 | URL: `https://phoresis/` via Caddy `tls internal` + Windows hosts entry | Professional feel; trains for LAN/WAN exposure later (just edit Caddyfile). |
| D11 | NVIDIA CUDA auto-detected at install; two image variants `:latest-cpu` and `:latest-cuda` | Best of both worlds; optional GPU acceleration without forcing it. |
| D12 | Lucide Icons + 6-8 custom SVG icons (gel, ladder, blot, electrophoresis) in matching style | Modern look (Linear-class), domain-appropriate for the rare gel-specific glyphs. |
| D13 | Custom Phoresis app icon for Windows shortcut and favicons | Branding; project-specific identity. |

## 5. Architecture overview

### 5.1 High-level diagram

```
HOST (Windows 11)
│
├─ PostgreSQL 17 (native install via winget)
│  └─ port 5432, database "phoresis", user "phoresis"
│
└─ Docker Desktop (WSL2 backend)
   └─ phoresis_compose stack:
      │
      ├─ caddy        :80, :443      ← reverse-proxy, HTTPS auto via tls internal
      │
      ├─ web          :8000 (internal)  ← gunicorn 4 workers + Django
      │  └─ host.docker.internal:5432  → native Postgres
      │
      ├─ worker       (no port)         ← Celery worker (queue: default + heavy)
      │
      ├─ scheduler    (no port)         ← Celery Beat (periodic jobs)
      │
      ├─ redis        :6379 (internal)  ← Celery broker + cache
      │
      └─ watchtower                      ← auto-update images @ 03:00 daily
         └─ watches phoresis-{web,worker,scheduler} only
```

### 5.2 Django app boundaries

```
src/
├── phoresis/                 # Django project (settings, urls, wsgi, asgi)
├── phoresis_core/            # logging, widgets, celery, navigation, errors
├── accounts/                 # User custom (AUTH_USER_MODEL), profile, perms
├── gel_analyzer/             # main app — port 1:1 cleaned (14 models, services, JS)
├── dashboard/                # home page (KPIs, recent gels, quick actions)
└── phoresis_ui/              # design system: Tailwind components, templatetags, icons
```

### 5.3 Data flow examples

**Upload + analyze a gel:**
```
Browser  --(HTMX form POST)-->  web:gunicorn  -->  /images/upload/ view
                                                    --> GelImage.save()
                                                    --> file_handler.process_image()
                                                    --> redirect to /analyses/create/
                                                    --> create GelAnalysis, render annotation viewer
```

**Async hybrid band detection:**
```
Browser (annotation viewer)  --(HTMX POST)-->  /api/analyses/<uuid>/detect-bands-hybrid/async/
   web --> Celery task `detect_bands_hybrid_bulk_task` enqueued (heavy queue, redis)
   worker picks task --> HybridDetector.detect_all_lanes() --> Band.objects.bulk_create()
   Browser polls `/api/celery-task/<uuid>/status/` (HTMX) --> renders bands when done
```

**Watchtower update flow:**
```
03:00 daily:
   watchtower --(query ghcr.io)--> new digest available?
       yes:
         pull new images
         stop containers (graceful, drain in-flight requests)
         start containers with new images
         entrypoint.sh runs migrate + collectstatic
         Caddy retries upstream until /healthz/ green
         cleanup old images
         (optional) shoutrrr → email "Phoresis updated to vX.Y.Z"
```

## 6. Tech stack

### 6.1 Backend
- Python 3.12
- Django 5.2 + djangorestframework
- Celery 5 + redis 7 (broker)
- Postgres 17 (native host) + psycopg 3
- gunicorn (4 workers in container)
- whitenoise (compressed static files, even though Caddy serves them directly — fallback)
- django-simple-history (audit trails — port from monorepo)
- loguru (logging — port from `base/logging_config.py`)
- scipy, numpy, opencv-python (cv2), tifffile, Pillow (image processing)
- torch (CPU or CUDA variant) + onnxruntime (MobileSAM + YOLO inference)
- python-docx, openpyxl, python-pptx (report generation)

### 6.2 Frontend
- Tailwind CSS 4 (with `@theme` directive, container queries plugin, forms plugin)
- HTMX 2 (server-driven interactivity)
- Alpine.js 3 (client-side state for stores: theme, toast, modal, command-palette)
- D3.js v7 (chromatograms, electropherograms — preserved)
- SVG.js 3.x (annotation editor — preserved)
- ONNX Runtime Web (browser-side YOLO + SAM decoder)
- Lucide Icons (sprite injected once) + 6-8 custom SVG icons in matching style
- View Transition API (native, with Alpine fallbacks)
- CountUp.js (number animations on KPIs)

### 6.3 Infrastructure
- Docker Desktop (Windows, WSL2 backend)
- Caddy 2 (reverse proxy + HTTPS via `tls internal`)
- Watchtower (auto-update)
- GitHub Actions (CI + release)
- ghcr.io (image registry)
- uv (Python deps + venv management)

### 6.4 Quality / dev tooling
- ruff (lint + format)
- djlint (Django template lint)
- mypy (strict on `phoresis_core` + `accounts`, lenient on `gel_analyzer`)
- pytest + pytest-django + pytest-cov + pytest-xdist + factory-boy + freezegun
- playwright (e2e)
- pre-commit (ruff, djlint, mypy, gitleaks, large-file check)
- conventional-changelog (auto CHANGELOG)
- Trivy (CVE scan in CI)

## 7. Apps & responsibilities (detailed)

### 7.1 `phoresis_core/`

```
phoresis_core/
├── logging_config.py         # Loguru wrapper (port of base/logging_config.py)
├── celery_app.py             # Celery config, queues (default + heavy), beat
├── celery_utils.py           # @robust_task decorator (port)
├── widgets/
│   ├── search_select.py      # Tailwind + Alpine.js, replaces MDB5 search-select
│   ├── date_picker.py        # idem, replaces MDB5 datepicker
│   └── multi_select.py       # idem
├── navigation/
│   ├── __init__.py           # nav_registry singleton (simplified port)
│   └── registry.py           # auto-discovery of <app>/nav.py
├── error_handling.py         # ErrorLog model + ExceptionContextMiddleware
│                             # observability rule: try/except + log-and-swallow
├── api_schema.py             # DRF schema view custom (PhoresisSchemaView)
└── admin.py                  # ErrorLog admin + Phoresis-customized admin site
```

CSS prefix: `.pc-*`

### 7.2 `accounts/`

```
accounts/
├── models.py                 # User(AbstractUser) + UserProfile (theme, language, avatar)
├── views.py                  # login, logout, profile, password-change (HTMX)
├── forms.py                  # Forms styled with phoresis_ui templatetags
├── admin.py                  # UserAdmin custom + UserProfileInline
├── permissions.py            # is_lab_user, is_reviewer, is_admin helpers
└── templates/accounts/       # login.html, profile.html
```

`AUTH_USER_MODEL = "accounts.User"` set from `phoresis/settings/base.py` day one.

3 groups seeded by migration `0002_seed_groups`:
- `Lab User` — read + write own analyses, no approvals, no admin
- `Reviewer` — Lab User + can approve/reject analyses, view all
- `Admin` — full access, manage users, ladder templates

CSS prefix: `.acc-*`

### 7.3 `gel_analyzer/`

Port 1:1 of the existing app, with these specific changes:

**Models (14 total, all preserved):**
- `Lane` — drop `process_sample` FK, drop `sample_analyses` GenericRelation, add `sample_metadata = JSONField(default=dict, blank=True)`. Replace `created_by`, `updated_by` FKs to `settings.AUTH_USER_MODEL`.
- `GelImage`, `GelAnalysis`, `LaneDensitometrySummary`, `LadderTemplate`, `LadderCalibration`, `MultiLadderCalibrationConfig`, `SavedComparison` — same pattern: replace `authentication.UserProxy` references with `settings.AUTH_USER_MODEL`.
- `Band`, `MWMarker`, `LadderBandDefinition`, `DensitometryResult`, `DensitometryJob` — unchanged.

**Code cleanup:**
- Delete `signals.py` (341 lines of ProcessSample / SampleAnalysis sync) — replace with empty file containing a docstring explaining how to reintroduce signals if external sample registry comes back.
- Delete `management/commands/backfill_lane_sample_analyses.py`.
- Strip `views/api.py` of `search_samples_json` and any ProcessSample-related endpoint.
- Strip `views/comparison.py` of the `?samples=` query mode — keep `?lanes=` and `?comparison=<uuid>` only.
- Strip `views/densitometry_api.py` of the ProcessSample summary endpoint.
- Rewrite all `from base.*` imports to `from phoresis_core.*` (54 imports across 50 files).
- Rewrite all `from authentication.models import UserProxy` to `from django.conf import settings; settings.AUTH_USER_MODEL` for FK declarations, and `from accounts.models import User` for runtime lookups.

**Services (preserved intact):**
- `band_detection/` (CV2 detector, hybrid detector with d1/d2 gap-fill, cross-lane consensus, profile/derivative detectors, geometry builder)
- `calibration/` (single + multi-ladder, Hungarian + RANSAC matching)
- `densitometry/` (Gaussian fitting, peak deconvolution, peak matching, advanced peak detector)
- `sam/` (MobileSAM encoder + decoder)
- `file_handler.py`, `scn_parser.py`, `template_learning.py`, `studio/`

**JS/CSS (preserved 100%):**
- 69 JS files in `static/gel_analyzer/js/` — unchanged
- `gel_viewer_standalone.css`, `densitometry.css`, `comparison.css` — unchanged
- The annotation editor, densitometry view, and comparison view are already MDB5-free and remain so

**Templates (rewritten for shell, preserved for viewers):**
- Shell pages (`home.html`, `images/list.html`, `images/upload.html`, `images/detail.html`, `analyses/list.html`, `analyses/create.html`) — rewritten in Tailwind + HTMX
- Heavy viewer pages (`analyses/annotate_standalone.html`, `analyses/densitometry.html`, `comparisons/compare.html`) — Tailwind chrome wrapper, but the core JS-driven UI inside is preserved unchanged

**Celery tasks (8 preserved):**
- `detect_bands_lane_task`, `detect_bands_bulk_task`, `detect_bands_cv2_bulk_task`, `detect_bands_hybrid_bulk_task`
- `band_detection_ping_task`, `densitometry_ping_task`
- `run_densitometry_task`, `export_densitometry_csv_task`
- `detect_peaks_profile_bulk_task` (kept for backward compat, marked DEPRECATED)

**Admin:** port intact, `process_sample` field removed from LaneAdmin.

**Management commands:**
- `seed_ladder_templates.py` — seeds ~10 standard ladders (Bio-Rad Precision Plus, NEB Color Prestained, ThermoFisher PageRuler, etc.)
- `create_initial_users.py` — seeds admin + primary user from `.env`

CSS prefixes preserved: `.ga-*` (general), `.gv-*` (viewer), `.dm-*` (densitometry/comparison)

### 7.4 `dashboard/`

```
dashboard/
├── views.py                  # home_view (KPIs, recent gels, quick actions)
├── services.py               # aggregations (counts, stats, recents)
└── templates/dashboard/      # home.html (Tailwind, animated)
```

Replaces the `home_view` from `gel_analyzer/views/home.py` — this is the "wow" landing page when she opens Phoresis.

CSS prefix: `.dsh-*`

### 7.5 `phoresis_ui/`

```
phoresis_ui/
├── templatetags/
│   ├── ui_components.py      # {% btn %}, {% card %}, {% modal %}, {% badge %},
│   │                         # {% kpi %}, {% empty_state %}, {% skeleton %},
│   │                         # {% confirm %}, {% toast %}
│   ├── ui_icons.py           # {% icon "name" %} (Lucide + custom)
│   └── ui_animations.py      # {% slide_in %}, {% fade_in %}, {% stagger %}
├── templates/components/
│   ├── base.html             # extends Django base, includes layout, theme init
│   ├── _layout.html          # sidebar + topbar + content area
│   ├── _sidebar.html         # collapsible icon-rail with hover-expand
│   ├── _topbar.html          # search, notifications, theme toggle, avatar
│   ├── _command_palette.html # Ctrl+K modal (uFuzzy search)
│   ├── _toast.html
│   ├── _confirm_modal.html
│   └── _empty_state.html
├── static/phoresis_ui/
│   ├── css/
│   │   ├── input.css         # Tailwind directives + custom @layer
│   │   └── tokens.css        # Design tokens (colors, spacing, radius, shadows)
│   ├── js/
│   │   ├── htmx-config.js    # CSRF, indicators, error toasts
│   │   ├── alpine-init.js    # global stores: theme, toast, modal, palette
│   │   └── animations.js     # GSAP / view-transition helpers
│   └── icons/
│       ├── lucide.svg        # Lucide sprite
│       └── custom/           # gel.svg, ladder.svg, blot.svg, electrophoresis.svg, ...
└── tailwind.config.js        # tokens, plugins (forms, typography, container-queries)
```

CSS prefix: `.ui-*`

This is where the "design class" lives. Every new view extends `components/base.html` and uses templatetags → automatic visual coherence.

## 8. Design system

### 8.1 Design tokens

Full reference (`phoresis_ui/static/phoresis_ui/css/tokens.css`):

```css
:root {
  /* Surfaces — light */
  --color-bg: #fafafa;
  --color-surface: #ffffff;
  --color-surface-elevated: #ffffff;
  --color-border: #e5e7eb;
  --color-text: #18181b;
  --color-text-muted: #71717a;

  /* Accent — deep lab blue */
  --color-accent-50: #eff6ff;
  --color-accent-500: #3b82f6;
  --color-accent-600: #2563eb;
  --color-accent-700: #1d4ed8;

  /* Gel semantics */
  --color-band: #ec4899;        /* magenta — bands / peaks */
  --color-poi: #2563eb;         /* protein of interest */
  --color-mw-ref: #10b981;      /* MW reference */
  --color-other: #94a3b8;

  /* Status */
  --color-success: #10b981;
  --color-warning: #f59e0b;
  --color-danger: #ef4444;
  --color-info: #06b6d4;

  /* Typography */
  --font-sans: "Inter", "Segoe UI", system-ui, sans-serif;
  --font-mono: "JetBrains Mono", "Cascadia Code", monospace;

  /* Spacing — 4px rhythm */
  --space-1: 0.25rem; --space-2: 0.5rem; --space-3: 0.75rem;
  --space-4: 1rem;    --space-6: 1.5rem; --space-8: 2rem;

  /* Radius */
  --radius-sm: 6px; --radius: 10px; --radius-lg: 14px; --radius-xl: 20px;

  /* Shadows */
  --shadow-sm: 0 1px 2px rgba(0,0,0,.04);
  --shadow:    0 4px 12px rgba(0,0,0,.06);
  --shadow-lg: 0 12px 32px rgba(0,0,0,.08);

  /* Motion */
  --ease-out: cubic-bezier(0.22, 1, 0.36, 1);
  --duration-fast: 150ms;
  --duration: 250ms;
  --duration-slow: 400ms;
}

[data-theme="dark"] {
  --color-bg: #09090b;
  --color-surface: #18181b;
  --color-surface-elevated: #27272a;
  --color-border: #27272a;
  --color-text: #fafafa;
  --color-text-muted: #a1a1aa;

  --color-accent-500: #60a5fa;
  --color-accent-600: #3b82f6;

  --color-band: #f472b6;
}
```

Tailwind 4 is configured to consume these tokens directly (`bg-surface`, `text-muted`, `ring-accent-500`, etc.) via `@theme` in `input.css`.

Summary:

- **Colors light/dark** — full parity. Both modes designed first-class, not afterthought.
- **Accent**: deep lab blue (`#3b82f6` primary, `#1d4ed8` strong)
- **Band/peak**: magenta (`#ec4899` light, `#f472b6` dark)
- **Semantic**: `--color-poi` blue, `--color-mw-ref` green, `--color-other` slate
- **Typography**: Inter sans-serif + JetBrains Mono
- **Spacing**: 4px rhythm, custom scale
- **Radius**: 6 / 10 / 14 / 20px
- **Shadow**: subtle (4 / 12 / 32 px blur, 4-8% opacity)
- **Easing**: `cubic-bezier(0.22, 1, 0.36, 1)` (smooth-out)
- **Durations**: 150 / 250 / 400ms

### 8.2 Component catalog

| Component | Usage | Key behavior |
|---|---|---|
| `{% btn %}` | buttons | 4 variants (primary, secondary, ghost, danger) × 3 sizes; loading state with inline spinner; ripple on click |
| `{% card %}` | wrappers | Hover lift `translate-y-[-2px]` + shadow upgrade |
| `{% kpi %}` | dashboard | Animated number (CountUp.js), trend arrow, mini sparkline (D3) |
| `{% modal %}` | dialogs | Backdrop blur, scale-in, focus trap, Esc closes |
| `{% toast %}` | notifications | Stack bottom-right, slide-in, auto-dismiss, swipeable |
| `{% badge %}` | status pills | 8 semantic colors |
| `{% empty_state %}` | empty lists | SVG illustration + CTA, ample whitespace |
| `{% skeleton %}` | loading | Shimmer animation while HTMX fetches |
| `{% confirm %}` | confirmations | Standardized modal, danger button highlighted |
| `{% icon %}` | icons | Lucide + custom, currentColor, 24×24 stroke 1.5 |

### 8.3 Layout

- **Sidebar**: 72px icon-rail collapsed (Lucide icons), expands to 240px on hover or pin-toggle, 250ms transition.
- **Topbar**: 60px, global search (Ctrl+K → command palette à la Linear), notifications badge (Celery jobs), settings, avatar dropdown.
- **Content area**: padding `px-6 md:px-8`, `max-w-7xl` default (override per page).

### 8.4 Animations & micro-interactions

- View Transition API for HTMX page swaps (Chrome/Edge); Alpine `x-transition` fallback.
- HTMX feedback: top progress bar (GitHub-style), button loading state, automatic toast on response status.
- Buttons: ripple on click.
- Cards: lift on hover.
- Sidebar items: icon scale-110 + label slide-in on hover.
- Modals: scale-95→100 + opacity 0→100, 250ms.
- Form fields: ring focus animated, floating labels (subtle, not Material-loud).
- Drag-drop upload: dropzone pulses + scales on dragenter, green pulse on drop.
- KPI numbers: CountUp.js 800ms on dashboard mount.
- Loading skeletons: shimmer wave 2s loop on fetches > 200ms.
- Theme toggle: smooth color transition 300ms (CSS variables animated via `transition-colors`).

### 8.5 Dark/light mode

- Auto-detect via `matchMedia("(prefers-color-scheme: dark)")`.
- User override stored in localStorage and synced to `UserProfile.theme`.
- Toggle in avatar dropdown: segmented Auto / Light / Dark.
- 300ms smooth transition on switch (no flash).
- All D3/SVG visuals (electropherograms, gel renders, comparisons) have light/dark palettes; theme-changed event triggers their re-render.

### 8.6 App icon

3 directions presented at design time, one chosen. Candidates:
1. Stylized **Φ** built from vertical bands (lanes).
2. Abstract **gel** with 3-4 horizontal bands graduating blue → magenta.
3. **Lane rectangle** with internal bands + subtle glassmorphism.

Deliverables: `phoresis.ico` (multi-resolution 16/24/32/48/64/128/256), `phoresis.svg` (favicon source), `phoresis-512.png` (desktop shortcut), `apple-touch-icon`, `mask-icon`. Bundled in `assets/icons/`. `install.ps1` wires the `.ico` to the desktop shortcut.

## 9. Packaging & deployment

### 9.1 Container layout (already detailed in §5.1)

`docker/docker-compose.yml` orchestrates: caddy, web, worker, scheduler, redis, watchtower. Postgres is **native** on the host; containers reach it via `host.docker.internal:5432`.

Volumes:
- `phoresis_media` (uploaded gel images, generated thumbnails)
- `phoresis_staticfiles` (collected static after `collectstatic`)
- `phoresis_redis` (broker persistence)
- `caddy_data`, `caddy_config` (HTTPS cert state)

### 9.2 Caddyfile

```caddy
phoresis {
    tls internal
    encode gzip zstd
    header {
        Strict-Transport-Security max-age=31536000
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy strict-origin-when-cross-origin
    }
    handle_path /static/* {
        root * /srv/staticfiles
        file_server
    }
    handle_path /media/* {
        root * /srv/media
        file_server
    }
    reverse_proxy web:8000
}
```

### 9.3 GPU/CPU adaptive install

`install.ps1` detects NVIDIA GPU via `nvidia-smi`:
- If detected + Docker Desktop ≥ 4.16 + WSL2 backend + NVIDIA Container Toolkit → writes `PHORESIS_IMAGE_VARIANT=cuda` in `.env`, includes `compose.gpu.yml` override (with `deploy.resources.reservations.devices`).
- Otherwise → `PHORESIS_IMAGE_VARIANT=cpu` (default).
- User can switch later via re-run or manual `.env` edit.

Two image variants per service published to ghcr.io:
- `ghcr.io/gmathy2104/phoresis-web:latest-cpu` (~2 GB, torch CPU)
- `ghcr.io/gmathy2104/phoresis-web:latest-cuda` (~5 GB, CUDA 12.1 runtime + torch+cu121)
- Same for `phoresis-worker`.

DirectML / AMD / Intel GPU support: explicitly out of scope for v1.

### 9.4 PowerShell scripts

| Script | Purpose |
|---|---|
| `install.ps1` | Verifies Win11, prompts UAC, installs Docker Desktop + Postgres 17 if missing (via `winget` primarily; falls back to direct EnterpriseDB installer URL if winget unavailable), creates DB and user, detects GPU, adds `127.0.0.1 phoresis` to hosts, generates `.env` interactively, `docker login ghcr.io` if image is private, `docker compose pull && up -d`, waits healthcheck, opens browser, creates desktop shortcut wired to `phoresis.ico`. ~5 min on a clean machine. |
| `start.ps1` | `docker compose up -d` + `Start-Process "https://phoresis/"`. Used by desktop shortcut. |
| `stop.ps1` | `docker compose down` (volumes preserved). |
| `update.ps1` | Manual `docker compose pull && up -d`. Supports `--rollback v1.2.3` flag. |
| `backup.ps1` | `pg_dump phoresis > %USERPROFILE%\Phoresis-Backups\db_YYYYMMDD.sql` + tar media volume. Keeps 30 days. Schedulable via Task Scheduler. |
| `restore.ps1` | Interactive: lists backups, prompts which to restore. |

### 9.5 Health checks

- `/healthz/` — DB + Redis + Celery worker ping. Used by Caddy upstream check.
- `/healthz/celery/` — separate endpoint for worker-only check.
- Watchtower verifies `/healthz/` after update. Future enhancement: rollback if KO (not v1).

## 10. CI/CD & update flow

### 10.1 Workflows

**`.github/workflows/ci.yml`** (per push + PR):
- `lint`: ruff + djlint + mypy
- `test`: pytest with Postgres 17 + Redis services, coverage uploaded to Codecov
- `e2e`: Playwright with full docker-compose.test stack
- `build-tailwind`: tailwindcss build (output uploaded as artifact)

**`.github/workflows/release.yml`** (per `v*.*.*` tag):
- Matrix `(cpu, cuda) × (web, worker)` = 4 image builds
- Push to ghcr.io with tags `:vX.Y.Z-{variant}` and `:latest-{variant}`
- Auto-generate release notes from Conventional Commits (`conventional-changelog`)
- Create GitHub release

### 10.2 Versioning

- Conventional Commits → auto-CHANGELOG
- SemVer:
  - MAJOR: breaking change (destructive migration, feature removal)
  - MINOR: new feature, backward-compatible
  - PATCH: bug fix, backward-compatible
- Watchtower follows `:latest-{variant}` by default
- Pinning: `.env` → `PHORESIS_IMAGE_TAG=v1.2.3-cpu`, disable Watchtower for that container

### 10.3 Migrations

`docker/entrypoint.sh` (web container):
```sh
#!/bin/sh
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py seed_groups
python manage.py seed_ladder_templates --skip-existing
python manage.py create_initial_users --from-env --skip-existing
exec "$@"
```

Idempotent — safe to run on every container start.

### 10.4 Secrets

- `.env` at repo root (gitignored), generated interactively by `install.ps1`
- Variables: `DJANGO_SECRET_KEY`, `DB_PASSWORD`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`, `PRIMARY_USER_EMAIL`, `PRIMARY_USER_PASSWORD`, `PRIMARY_USER_FULL_NAME`, `PHORESIS_IMAGE_VARIANT`, `WATCHTOWER_NOTIFICATION_URL` (optional)
- CI: GitHub Secrets `GITHUB_TOKEN` (auto), `CODECOV_TOKEN`
- Image is published with no embedded secrets — runtime config only via env vars

## 11. Test strategy

### 11.1 Pyramid

```
         /\
        /e2e\           ~ 15 Playwright tests (golden paths)
       /------\
      /  intg  \         ~ 60 pytest-django tests (views + DRF + signals)
     /----------\
    /    unit    \       ~ 250 pytest tests (services, models, helpers)
   /--------------\
```

### 11.2 Coverage targets

- ≥ 80% global
- ≥ 90% on `phoresis_core` and `accounts` (small, simple, must be rock-solid)
- `gel_analyzer/services/` ≥ 75% (legacy + scientific code, partial typing)

### 11.3 Tooling

- pytest + pytest-django + pytest-cov + pytest-xdist + factory-boy + freezegun
- `CELERY_TASK_ALWAYS_EAGER = True` in test settings (no Redis needed)
- DB fixture: pytest-django reuses `test_phoresis` DB across runs (`--reuse-db` like the monorepo)
- Playwright Python for e2e

### 11.4 e2e golden paths

1. Login → dashboard → upload gel → create analysis → place lanes/bands → save → logout
2. Run hybrid detection async → poll Celery → verify bands created
3. Run densitometry async → verify results + CSV export
4. Compare 2 lanes via ad-hoc URL → verify all 4 panels load
5. Toggle dark mode → verify persistence after refresh
6. Backup → restore → verify data preserved (CI-only)

### 11.5 Runtime quality

- Sentry — optional, off by default. Enable via `.env` `SENTRY_DSN=...`.
- `phoresis_core.ErrorLog` — DB persistence of errors, dashboard at `/admin/errors/`. Always on.
- Loguru — rotating logs in `logs/phoresis-{date}.log`, gzipped, 30-day retention.
- Trivy — CVE scan on built images in CI; CRITICAL vulnerabilities block release.
- Custom `/admin/system/` page — DB size, media size, last backup, Celery status, container uptimes, "Download support bundle" button (zip with logs + `docker compose ps` + `docker stats` + version info).

## 12. Roadmap (7 phases)

Each phase produces a clean PR + an intermediate release (`vX.Y.0`) for granular rollback. Per-phase implementation plans will be expanded via the `superpowers:writing-plans` skill after this spec is approved.

| Phase | Effort | Deliverable | Tag |
|---|---|---|---|
| **1. Bootstrap & shims** | 3-4d | Repo created, `pyproject.toml` (uv), Django project, `phoresis_core` (logging, celery_utils, error_handling, navigation registry), `accounts` (User+UserProfile, login/logout views), `dashboard` stub, `phoresis_ui` skeleton (empty templatetags + base.html stub), pytest + ruff + pre-commit, CI lint+test workflow. `runserver` + `/admin/` work. | v0.1.0 |
| **2. Models & services extraction** | 4-5d | `gel_analyzer` ported: 14 models with cleanups (no `process_sample`, FKs to `accounts.User`), all services intact, 8 Celery tasks, ML models bundled, admin ported, `seed_ladder_templates` + `create_initial_users`. ~150 service tests pass. Hybrid detection on a test gel produces correct bands. | v0.2.0 |
| **3. Frontend foundation** | 5-6d | `phoresis_ui` complete: Tailwind 4 build, design tokens, all templatetags, layout/sidebar/topbar/command-palette templates, Lucide sprite + 6-8 custom icons, theme switcher. Phoresis app icon finalized. Pages: login, dashboard, image list/upload/detail, analysis list/create. | v0.3.0 |
| **4. Heavy viewers ported** | 3-4d | Annotation, densitometry, comparison views in new Tailwind chrome (preserved JS internals). DRF API viewsets ported. Playwright e2e for end-to-end gel workflow passes. | v0.4.0 |
| **5. Docker + Caddy packaging** | 3-4d | `Dockerfile.web`, `Dockerfile.worker` (multi-stage, cpu/cuda variants), `docker-compose.yml` + `compose.gpu.yml` override, `Caddyfile`, `entrypoint.sh`, healthchecks. Local `docker compose up` → `https://phoresis/` accessible. | v0.5.0 |
| **6. CI/CD + install scripts** | 2-3d | Release workflow (matrix build, ghcr.io push, GitHub release auto), `install.ps1` (GPU detect, hosts entry, Postgres install, .env interactif), `start.ps1`/`stop.ps1`/`update.ps1`/`backup.ps1`/`restore.ps1`, Watchtower wired. Clean-machine install validated on author's PC. | v0.6.0 |
| **7. Polish + docs + v1 release** | 3-4d | Final animations + micro-interactions, custom 404/500 pages, full docs (`README.md`, `INSTALL.md`, `ARCHITECTURE.md`, `DEVELOPMENT.md`, `DEPLOYMENT.md`, `DESIGN.md`, per-app READMEs), `CHANGELOG.md`, `CONTRIBUTING.md`. Install on primary user's PC + final hands-on validation with her. | **v1.0.0** |

Total effort estimate: **~3-5 weeks** (single dev, intermittent).

## 13. Open questions / future work (deferred)

- Public vs private ghcr.io image — to confirm at Phase 6 (lean public for simplicity).
- Whether to ship `Phoresis.lnk` shortcut with embedded `phoresis.ico` directly, or use `Set-Shortcut` PowerShell — implementation detail at Phase 6.
- Future analyzer apps (DLS, CPS, Western blot dedicated view) — design assumes they'd plug in as new Django apps in `src/`, sharing `phoresis_core` and `phoresis_ui`. No immediate work; mentioned to validate "upscale-ready" architecture choice.
- LAN exposure — `Caddyfile` ready (just change site address from `phoresis` to `phoresis.lan` + add `bind 0.0.0.0`); not v1.
- Sentry self-hosted vs sentry.io — neither is wired up for v1; simple `SENTRY_DSN` env wiring documented.
- Per-image rollback automation if `/healthz/` fails post-update — out of scope for v1; manual rollback via `update.ps1 --rollback`.
- Multi-language UI (FR/EN switch via `UserProfile.language`) — schema is ready, actual `gettext` translation files deferred to post-v1.

## 14. Documentation deliverables (kept current throughout)

- `README.md` (root) — quick start, hero screenshot, link to install guide.
- `docs/INSTALL.md` — step-by-step install for non-technical end-user, with screenshots, tested by walking the primary user through it.
- `docs/ARCHITECTURE.md` — full architecture with Mermaid diagrams (apps, dependencies, data flow, container layout, CI/CD flow).
- `docs/DEVELOPMENT.md` — dev onboarding (clone, uv install, run tests, conventions, pre-commit setup).
- `docs/DEPLOYMENT.md` — release flow, Watchtower behavior, rollback procedure, troubleshooting.
- `docs/DESIGN.md` — design system reference (tokens, components, animations, accessibility).
- `<app>/docs/README.md` per app (5 files: phoresis_core, accounts, gel_analyzer, dashboard, phoresis_ui).
- `CHANGELOG.md` — auto-generated from Conventional Commits.
- `CONTRIBUTING.md` — for any future external contributor.

All docs written/updated **incrementally during each phase**, not dumped at the end. A final review pass at Phase 7 ensures consistency and completeness.

---

**End of design document.**
