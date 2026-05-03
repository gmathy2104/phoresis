# Phoresis — Phase 7 (Polish + Docs + v1.0.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Final polish pass — micro-interactions that didn't make it into Phase 3, custom 404/500 error pages — plus the complete documentation suite (root `README.md`, six top-level docs, five per-app READMEs, finalized `CHANGELOG.md` and `CONTRIBUTING.md`). Hands-on install + walk-through with the primary user. Tagged **`v1.0.0`**.

**Architecture:** Phase 7 doesn't add new code architecture — it tightens the existing surface. The micro-interactions (button ripple, HTMX progress bar, sidebar icon scale, drag-drop pulse) layer onto the design system from Phase 3. The 404/500 pages plug into Django's `handler404` / `handler500` and consume the `request._error_context` set by Phase 1's `ExceptionContextMiddleware` to surface a `PHOR-YYYYMMDD-XXXXXX` reference ID to the user.

Documentation is co-located with the artefact it describes:
- Root `README.md` — entry point, hero shot, install link, license.
- `docs/*.md` — six topical guides cross-linked from each other.
- `src/<app>/docs/README.md` — per-app deep dive (5 apps).

Per spec §14: "All docs written/updated incrementally during each phase, not dumped at the end. A final review pass at Phase 7 ensures consistency and completeness." Earlier phases left `docs/specs/` and `docs/superpowers/plans/` populated; Phase 7 fills the gap with end-user / dev / ops / design docs.

**Tech Stack delta:** No new deps. Adds Mermaid in markdown (rendered natively by GitHub); no local renderer needed.

---

## Build Order Rationale

1. **Polish micro-interactions** (Task 1) — fastest visual wins; informs the screenshots we need for INSTALL.md / DESIGN.md.
2. **Custom 404 / 500 pages** (Task 2) — small surface, important for "felt quality".
3. **Per-app READMEs** (Task 3) — five small files; finished first so the top-level docs can link into them.
4. **`docs/ARCHITECTURE.md`** (Task 4) — the cross-cutting view; Mermaid diagrams reused by other docs.
5. **`docs/DESIGN.md`** (Task 5) — design system reference, mostly extracted from spec §8 + Phase 3 templatetag catalogue.
6. **`docs/DEVELOPMENT.md`** (Task 6) — dev onboarding; references everything we've built.
7. **`docs/DEPLOYMENT.md`** (Task 7) — release flow (Phase 6) + Watchtower + rollback + troubleshooting.
8. **`docs/INSTALL.md`** (Task 8) — end-user-facing; screenshots from Task 1's polished UI.
9. **Root `README.md` + final `CHANGELOG.md` + `CONTRIBUTING.md` review** (Task 9) — entry-point + cross-link audit.
10. **Hands-on validation with the primary user + tag v1.0.0** (Task 10).

---

## File Structure (additions to Phase 6)

```
README.md                           # root — REWRITE (was a Phase 1 stub)
CHANGELOG.md                        # finalize (auto-managed but reviewed)
CONTRIBUTING.md                     # already exists from Phase 6 — extend

docs/
├── INSTALL.md                      # NEW — end-user install walkthrough
├── ARCHITECTURE.md                 # NEW — Mermaid diagrams + boundaries
├── DEVELOPMENT.md                  # NEW — dev onboarding
├── DEPLOYMENT.md                   # NEW — release/Watchtower/rollback
├── DESIGN.md                       # NEW — tokens + components + animations + a11y
└── images/                         # NEW — screenshots referenced by docs
    ├── hero-dashboard.png
    ├── install-step-1.png
    ├── install-step-2.png
    ├── install-step-3.png
    ├── annotate-viewer.png
    ├── densitometry-view.png
    └── comparison-view.png

src/phoresis_core/docs/README.md    # NEW
src/accounts/docs/README.md         # NEW
src/gel_analyzer/docs/README.md     # NEW
src/dashboard/docs/README.md        # NEW
src/phoresis_ui/docs/README.md      # NEW

src/phoresis_ui/templatetags/
└── ui_components.py                # EXTENDED: ripple, progress_bar templatetags

src/phoresis_ui/static/phoresis_ui/
├── css/input.css                   # EXTENDED: @layer additions for ripple, progress, dropzone
└── js/animations.js                # EXTENDED: ripple handler, dropzone listener

src/phoresis_ui/templates/
├── 404.html                        # NEW
└── 500.html                        # NEW

src/phoresis/urls.py                # MODIFIED: handler404 / handler500
```

---

## Task 1: Polish — micro-interactions from spec §8.4

**Files:**
- Modify: `src/phoresis_ui/static/phoresis_ui/css/input.css` (ripple + progress-bar + dropzone keyframes)
- Modify: `src/phoresis_ui/static/phoresis_ui/js/animations.js` (ripple handler + HTMX progress bar)
- Modify: `src/phoresis_ui/templatetags/ui_components.py` (`{% btn %}` adds `data-ripple` attr)
- Modify: `src/phoresis_ui/templates/components/_sidebar.html` (icon `scale-110` on hover)
- Modify: `src/gel_analyzer/templates/gel_analyzer/images/upload.html` (dropzone pulse)

The Phase 3 design system shipped most of §8.4. Phase 7 closes the gap on these:

| § 8.4 item | Phase 3 status | Phase 7 action |
|---|---|---|
| Buttons ripple on click | not done | add JS handler + CSS |
| HTMX top progress bar (GitHub-style) | not done | add HTMX `htmx:beforeRequest` listener + CSS bar |
| Sidebar icon `scale-110` on hover | partial (label slide done) | add `group-hover:scale-110` to icon span |
| Form fields: floating labels | not done | small CSS — opt-in via `<label class="ui-float">` |
| Drag-drop upload: dropzone pulse | not done | dragenter/dragleave handlers + keyframe |
| Theme toggle: smooth color transition | done (Phase 3) | — |
| KPI CountUp.js | done | — |
| Modals: scale-95→100 + opacity | done | — |
| Loading skeletons: shimmer | done | — |
| View Transition API | done (animations.js) | — |

- [ ] **Step 1: Extend `input.css` with ripple + progress + dropzone styles**

Append to `src/phoresis_ui/static/phoresis_ui/css/input.css` after the existing `@layer components`:

```css
@layer components {
  /* Ripple effect for buttons (data-ripple in btn templatetag) */
  .ui-ripple-host {
    position: relative;
    overflow: hidden;
  }
  .ui-ripple-host > .ui-ripple {
    position: absolute;
    border-radius: 9999px;
    transform: scale(0);
    animation: ui-ripple-anim 600ms var(--ease-out);
    background: currentColor;
    opacity: 0.25;
    pointer-events: none;
  }
  @keyframes ui-ripple-anim {
    to { transform: scale(4); opacity: 0; }
  }

  /* HTMX top progress bar */
  .ui-htmx-progress {
    position: fixed;
    top: 0; left: 0;
    height: 3px;
    width: 0;
    background: var(--color-accent-500);
    z-index: 100;
    transition: width 250ms var(--ease-out), opacity 200ms var(--ease-out) 50ms;
    box-shadow: 0 0 8px rgb(from var(--color-accent-500) r g b / 0.5);
    pointer-events: none;
    opacity: 0;
  }
  .ui-htmx-progress[data-state="loading"] { opacity: 1; width: 70%; }
  .ui-htmx-progress[data-state="done"]    { opacity: 0; width: 100%; }

  /* Dropzone pulse */
  .ui-dropzone {
    transition: transform 150ms var(--ease-out),
                background-color 150ms var(--ease-out),
                border-color 150ms var(--ease-out);
  }
  .ui-dropzone[data-active="true"] {
    transform: scale(1.02);
    background-color: var(--color-accent-50);
    border-color: var(--color-accent-500);
    animation: ui-dropzone-pulse 1.4s var(--ease-out) infinite;
  }
  @keyframes ui-dropzone-pulse {
    0%, 100% { box-shadow: 0 0 0 0 rgb(from var(--color-accent-500) r g b / 0.3); }
    50%      { box-shadow: 0 0 0 12px rgb(from var(--color-accent-500) r g b / 0); }
  }

  /* Floating labels (opt-in via .ui-float wrapper) */
  .ui-float {
    position: relative;
  }
  .ui-float > input,
  .ui-float > textarea {
    padding-top: 1.25rem;
    padding-bottom: 0.5rem;
  }
  .ui-float > label {
    position: absolute;
    top: 0.6rem;
    left: 0.75rem;
    pointer-events: none;
    color: var(--color-text-muted);
    font-size: 0.875rem;
    transform-origin: 0 0;
    transition: transform 150ms var(--ease-out), color 150ms var(--ease-out);
  }
  .ui-float > input:focus + label,
  .ui-float > input:not(:placeholder-shown) + label,
  .ui-float > textarea:focus + label,
  .ui-float > textarea:not(:placeholder-shown) + label {
    transform: translateY(-0.4rem) scale(0.85);
    color: var(--color-accent-600);
  }
}
```

- [ ] **Step 2: Extend `animations.js` with ripple + progress handlers**

Append to `src/phoresis_ui/static/phoresis_ui/js/animations.js`:

```javascript
// ============================================================================
// Ripple effect on buttons (opt-in via data-ripple on the host element)
// ============================================================================
document.addEventListener("click", (e) => {
  const host = e.target.closest("[data-ripple]");
  if (!host) return;
  host.classList.add("ui-ripple-host");
  const rect = host.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height);
  const ripple = document.createElement("span");
  ripple.className = "ui-ripple";
  ripple.style.width = ripple.style.height = `${size}px`;
  ripple.style.left = `${e.clientX - rect.left - size / 2}px`;
  ripple.style.top  = `${e.clientY - rect.top  - size / 2}px`;
  host.appendChild(ripple);
  setTimeout(() => ripple.remove(), 600);
});

// ============================================================================
// HTMX top progress bar
// ============================================================================
(function () {
  let bar = null;

  function ensureBar() {
    if (bar) return bar;
    bar = document.createElement("div");
    bar.className = "ui-htmx-progress";
    document.body.appendChild(bar);
    return bar;
  }

  document.addEventListener("htmx:beforeRequest", () => ensureBar().setAttribute("data-state", "loading"));
  document.addEventListener("htmx:afterRequest",  () => ensureBar().setAttribute("data-state", "done"));
  document.addEventListener("htmx:responseError", () => ensureBar().setAttribute("data-state", "done"));
})();
```

- [ ] **Step 3: Add `data-ripple` to the `{% btn %}` templatetag output**

Edit `src/phoresis_ui/templatetags/ui_components.py` — in the `btn` function, find the line that builds the `<button>` element and append `data-ripple` to the attributes. Apply the same to the `<a>` branch.

```python
    if href:
        return mark_safe(f'<a href="{href}" class="{cls}" data-ripple{htmx_attrs}>{inner}</a>')

    disabled_attr = " disabled" if disabled else ""
    return mark_safe(f'<button type="{type_}" class="{cls}" data-ripple{htmx_attrs}{disabled_attr}>{inner}</button>')
```

- [ ] **Step 4: Sidebar icon scale**

Edit `src/phoresis_ui/templates/components/_sidebar.html`. In each nav `<a>` block, wrap the icon in a span with `transform transition-transform group-hover:scale-110`:

```django
<a href="..." class="...">
    <span class="transition-transform group-hover:scale-110">
        {% icon "layout-dashboard" %}
    </span>
    ...
</a>
```

(Apply to all three nav items: Dashboard, Gel images, Analyses, Comparisons.)

- [ ] **Step 5: Dropzone in the upload template**

Edit `src/gel_analyzer/templates/gel_analyzer/images/upload.html`. Replace the `<input type="file">` with a styled wrapper that detects drag events:

```django
<div class="ui-dropzone rounded-lg border-2 border-dashed border-border bg-surface p-8 text-center"
     x-data="{ active: false }"
     :data-active="active"
     @dragenter.prevent="active = true"
     @dragleave.prevent="active = false"
     @dragover.prevent
     @drop.prevent="active = false; $refs.fileInput.files = $event.dataTransfer.files; $refs.fileInput.dispatchEvent(new Event('change', {bubbles:true}))">
    <div class="text-text-muted">
        {% load ui_icons %}{% icon "upload" size=32 class_="mx-auto mb-2" %}
        <p class="text-sm">Drop a gel image here or
            <label for="id_original_file" class="cursor-pointer text-accent-600 hover:underline">browse files</label>.
        </p>
    </div>
    <input id="id_original_file" type="file" name="original_file" required accept=".gel,.scn,.tiff,.tif,.png,.jpg,.jpeg"
           x-ref="fileInput"
           class="sr-only">
</div>
```

- [ ] **Step 6: Rebuild CSS**

```bash
npm run build:css
```

- [ ] **Step 7: Manual smoke**

```bash
.venv/Scripts/python.exe manage.py runserver 0.0.0.0:8000
```

In a browser:
- Click any `{% btn %}` → ripple animates from the click point.
- Navigate via HTMX (any HTMX-decorated link) → top progress bar slides in/out.
- Hover sidebar items → icon scales gently.
- Visit `/images/upload/` → dropzone pulses on dragenter; dropping a file populates the input.

If anything misbehaves, fix inline.

- [ ] **Step 8: Commit**

```bash
git add src/phoresis_ui/static/phoresis_ui/css/input.css src/phoresis_ui/static/phoresis_ui/js/animations.js src/phoresis_ui/templatetags/ui_components.py src/phoresis_ui/templates/components/_sidebar.html src/gel_analyzer/templates/gel_analyzer/images/upload.html
git commit -m "feat(phoresis_ui): polish micro-interactions (ripple, HTMX progress, sidebar scale, dropzone pulse, floating labels)"
```

---

## Task 2: Custom 404 + 500 pages

**Files:**
- Create: `src/phoresis_ui/templates/404.html`
- Create: `src/phoresis_ui/templates/500.html`
- Modify: `src/phoresis/urls.py` (add `handler404` / `handler500`)
- Modify: `src/phoresis_core/error_handling/views.py` (handler implementations)

The 500 handler reads `request._error_context` (set by Phase 1's `ExceptionContextMiddleware`) and surfaces the `error_id` to the user — so support requests carry a traceable reference.

- [ ] **Step 1: Create `src/phoresis_core/error_handling/views.py`**

```python
"""Error handler views for 404 / 500."""
from django.shortcuts import render
from django.template.response import TemplateResponse


def handler404(request, exception):
    """Custom 404 — branded, no error ID needed."""
    return TemplateResponse(request, "404.html", {"path": request.path}, status=404)


def handler500(request):
    """Custom 500 — surfaces the error_id from ExceptionContextMiddleware."""
    ctx = getattr(request, "_error_context", None) or {}
    return TemplateResponse(
        request,
        "500.html",
        {"error_id": ctx.get("error_id"), "path": request.path},
        status=500,
    )
```

- [ ] **Step 2: Create `src/phoresis_ui/templates/404.html`**

```django
{% extends 'components/base.html' %}
{% load ui_components ui_icons %}

{% block title %}Not found — Phoresis{% endblock %}

{% block content %}
<div class="mx-auto grid min-h-[calc(100vh-4rem)] max-w-md place-items-center text-center">
    <div>
        <div class="mb-6 inline-grid h-20 w-20 place-items-center rounded-2xl bg-amber-50 text-amber-700">
            {% icon "alert-triangle" size=40 %}
        </div>
        <h1 class="mb-2 text-3xl font-semibold">Page not found</h1>
        <p class="mb-8 text-sm text-text-muted">
            <span class="font-mono">{{ path }}</span> didn't match any route.
        </p>
        <div class="flex justify-center gap-2">
            {% btn "Back to dashboard" href="/" variant="primary" icon="layout-dashboard" %}
            {% btn "Browse gels" href="/images/" variant="secondary" icon="image" %}
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Create `src/phoresis_ui/templates/500.html`**

```django
{% extends 'components/base.html' %}
{% load ui_components ui_icons %}

{% block title %}Something went wrong — Phoresis{% endblock %}

{% block content %}
<div class="mx-auto grid min-h-[calc(100vh-4rem)] max-w-md place-items-center text-center">
    <div>
        <div class="mb-6 inline-grid h-20 w-20 place-items-center rounded-2xl bg-red-50 text-red-700">
            {% icon "alert-circle" size=40 %}
        </div>
        <h1 class="mb-2 text-3xl font-semibold">Something broke on our side</h1>
        <p class="mb-2 text-sm text-text-muted">
            We've logged the details. Try again in a moment, or come back to the dashboard.
        </p>
        {% if error_id %}
        <p class="mb-8 text-xs">
            <span class="text-text-muted">Reference</span>
            <code class="rounded bg-surface-elevated px-2 py-1 font-mono text-text">{{ error_id }}</code>
            <span class="text-text-muted">— include this if you contact support.</span>
        </p>
        {% endif %}
        <div class="flex justify-center gap-2">
            {% btn "Back to dashboard" href="/" variant="primary" icon="layout-dashboard" %}
            {% btn "Reload" href=path variant="secondary" icon="refresh-cw" %}
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 4: Wire the handlers in `src/phoresis/urls.py`**

Append to the bottom of the file (after `urlpatterns`):

```python
# Custom error handlers
handler404 = "phoresis_core.error_handling.views.handler404"
handler500 = "phoresis_core.error_handling.views.handler500"
```

- [ ] **Step 5: Add tests**

Create `src/phoresis_core/tests/test_error_handlers.py`:

```python
"""Tests for the custom 404 / 500 handler views."""
import pytest
from django.test import override_settings


@pytest.mark.django_db
def test_404_returns_branded_page(client) -> None:
    response = client.get("/this-route-does-not-exist-anywhere/")
    assert response.status_code == 404
    assert b"Page not found" in response.content
    assert b"Phoresis" in response.content


@pytest.mark.django_db
@override_settings(DEBUG=False, ALLOWED_HOSTS=["*"])
def test_500_handler_surfaces_error_id(client) -> None:
    """Trigger a 500 by hitting the /healthz/ endpoint with mocked failures.

    The default test client raises uncaught exceptions; we use raise_request_exception=False
    to actually hit the 500 handler.
    """
    from unittest.mock import patch
    with patch("phoresis_core.healthz._db_alive", side_effect=RuntimeError("boom")):
        response = client.get("/healthz/", raise_request_exception=False)
    assert response.status_code in (500, 503)
    # On 500 specifically, the error_id should be present:
    if response.status_code == 500:
        assert b"PHOR-" in response.content
```

> **Note:** Triggering a real 500 in tests is awkward — Django's test client by default re-raises exceptions. The check above is best-effort; the meaningful validation happens in the manual smoke (Step 7).

- [ ] **Step 6: Run tests**

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_core/tests/test_error_handlers.py -v
```
Expected: 1-2 tests pass. The `test_404_*` is reliable; the `test_500_*` may skip depending on how the underlying patching surfaces.

- [ ] **Step 7: Manual smoke**

```bash
.venv/Scripts/python.exe manage.py runserver 0.0.0.0:8000
```
Visit `http://127.0.0.1:8000/this-does-not-exist/` → 404 page renders with "Back to dashboard" button.

For a 500: temporarily patch a view to `raise RuntimeError("test")` (e.g., add it to `dashboard.views.home_view`), set `DEBUG=False` in dev.py, restart, hit `/`. The branded 500 page renders with a `PHOR-...` reference ID. Revert the patch.

- [ ] **Step 8: Commit**

```bash
git add src/phoresis_core/error_handling/views.py src/phoresis_ui/templates/404.html src/phoresis_ui/templates/500.html src/phoresis/urls.py src/phoresis_core/tests/test_error_handlers.py
git commit -m "feat: add branded 404 + 500 pages with PHOR- reference ID surfacing"
```

---

## Task 3: Per-app READMEs (5 files)

**Files:**
- Create: `src/phoresis_core/docs/README.md`
- Create: `src/accounts/docs/README.md`
- Create: `src/gel_analyzer/docs/README.md`
- Create: `src/dashboard/docs/README.md`
- Create: `src/phoresis_ui/docs/README.md`

Each per-app README follows the same structure: purpose, public surface (models / services / templatetags / commands), key files, integration notes. Short — 100-200 lines each.

- [ ] **Step 1: Create the 5 docs folders**

```bash
mkdir -p src/phoresis_core/docs src/accounts/docs src/gel_analyzer/docs src/dashboard/docs src/phoresis_ui/docs
```

- [ ] **Step 2: Write `src/phoresis_core/docs/README.md`**

Use this skeleton — write the actual content:

```markdown
# `phoresis_core`

Cross-cutting infrastructure shared by every Phoresis app.

## Purpose

Owns:
- Centralized loguru-based logging (`logging_config.py`).
- Celery app instance + `RobustTask` base class + `@robust_task` decorator (`celery_app.py`, `celery_utils.py`).
- Error capture: `ExceptionContextMiddleware`, `ErrorLog` model, error utility helpers (`error_handling/`).
- Navigation registry (`navigation/`) — singleton consumed by sidebar + command palette.
- Healthcheck endpoints (`healthz.py`).
- DRF Spectacular schema view (`api_schema.py`).

This is a *library* app — no user-facing views.

## Public surface

### Logging
- `from phoresis_core.logging_config import get_logger`
- Always use `get_logger(__name__)` (not `logging.getLogger`).

### Celery
- `from phoresis_core.celery_utils import robust_task`
- `@robust_task(soft_time_limit=300, time_limit=360)` — wraps `@shared_task(bind=True, base=RobustTask)`.
- `STALE_TASK_REGISTRY` — populated by gel_analyzer in Phase 2.

### Error handling
- `ExceptionContextMiddleware` — auto-installed in `MIDDLEWARE`.
- `phoresis_core.ErrorLog` — DB-persisted error log; admin lives at `/admin/phoresis_core/errorlog/`.
- `generate_error_id()` returns `PHOR-YYYYMMDD-XXXXXX`.

### Navigation
- `from phoresis_core.navigation import nav_registry` — register apps in their `nav.py`.
- `autodiscover_nav_modules()` runs in `PhoresisCoreConfig.ready()`.

### Health
- `GET /healthz/` — composite (DB + Redis + Celery).
- `GET /healthz/celery/` — worker-only.
- `GET /healthz/live/` — process liveness (no I/O).

## Key files

| File | Lines | Purpose |
|---|---|---|
| `logging_config.py` | ~190 | console + file + DB sinks; InterceptHandler |
| `celery_app.py` | ~30 | Celery instance + autodiscover |
| `celery_utils.py` | ~110 | RobustTask base + @robust_task |
| `error_handling/middleware.py` | ~150 | exception capture |
| `error_handling/utils.py` | ~120 | sanitize_dict, generate_error_id, signature, app-label extraction |
| `models.py` | ~90 | ErrorLog |
| `navigation/__init__.py` | ~140 | NavRegistry singleton |
| `healthz.py` | ~80 | readiness / celery / liveness |

## Integration notes

- `apps.py.ready()` calls `setup_logging()` and `autodiscover_nav_modules()` — apps must be in `INSTALLED_APPS` *after* `phoresis_core` so their `nav.py` modules are discoverable.
- The DB error sink calls `ErrorLog.objects.create(...)` synchronously inside `loguru` — never raise from this code path (silent except).
```

- [ ] **Step 3: Write `src/accounts/docs/README.md`**

```markdown
# `accounts`

User authentication, profile, and group permissions.

## Purpose

- Custom `User` model (`AbstractUser` + a friendlier `__str__`).
- `UserProfile` for theme / language / avatar / job_title (one-to-one with User).
- Three seeded groups: Lab User, Reviewer, Admin.
- Login / logout / profile views.
- Theme persistence endpoint (`POST /accounts/theme/`).

## Public surface

### Settings
- `AUTH_USER_MODEL = "accounts.User"` — set in `phoresis.settings.base`.
- `LOGIN_URL = "accounts:login"`.
- `LOGIN_REDIRECT_URL = "dashboard:home"`.

### Permission helpers
- `from accounts.permissions import is_lab_user, is_reviewer, is_admin`
- `from accounts.permissions import GROUP_LAB_USER, GROUP_REVIEWER, GROUP_ADMIN`

### Management commands
- `python manage.py seed_groups` — idempotent.
- `python manage.py create_initial_users --from-env --skip-existing` — used by `entrypoint.sh`.

## Key files

| File | Purpose |
|---|---|
| `models.py` | User + UserProfile |
| `signals.py` | post_save → auto-create UserProfile |
| `views.py` | LoginView, profile_view, theme_set_view |
| `permissions.py` | group helpers |
| `migrations/0002_seed_groups.py` | data migration seeding the 3 groups |

## Integration

- The `request.user.profile.theme` value is read by `base.html` to set the initial `data-theme` attribute on `<html>`, avoiding the dark/light flash on load.
- `LOGIN_REDIRECT_URL = "dashboard:home"` — non-namespaced (lazy resolve), so adding/renaming the dashboard route doesn't require an account migration.
```

- [ ] **Step 4: Write `src/gel_analyzer/docs/README.md`**

This is the longest per-app README — the gel_analyzer is the heart of Phoresis.

```markdown
# `gel_analyzer`

Gel electrophoresis image analysis — the scientific core of Phoresis.

## Purpose

End-to-end pipeline for SDS-PAGE / Dot Blot / Western Blot images:
- Upload + thumbnail + display-image generation.
- Lane and band annotation (interactive editor with SVG.js + ONNX SAM).
- MW calibration (single + multi-ladder, Hungarian + RANSAC matching).
- Hybrid band detection (CV2 + d1/d2 derivative + cross-lane consensus).
- Densitometry (Gaussian fitting, peak deconvolution, normalization, POI purity).
- Lane comparison (electropherograms + 4-panel cross-lane view).
- Report generation (Word, Excel, PowerPoint).

## Models (14)

| Model | Purpose | Notes |
|---|---|---|
| `GelImage` | uploaded gel + thumbnail + display | uploaded_by FK to accounts.User |
| `GelAnalysis` | analysis session | created_by, approved_by FKs |
| `Lane` | rectangle / quad / polygon lane | sample_metadata JSONField (no central sample registry — Phoresis is single-purpose) |
| `Band` | individual band | created_by FK; metadata JSONField for hybrid_phase etc. |
| `MWMarker` | MW value at a Y position | linked to LADDER lanes |
| `LadderTemplate` | reusable MW ladder | global templates seeded by `seed_ladder_templates` |
| `LadderBandDefinition` | individual band in a ladder | mw_kda + band_order |
| `LadderCalibration` | per-lane calibration result | log-linear / polynomial fit coefficients |
| `MultiLadderCalibrationConfig` | analysis-level multi-ladder config | gel-smile correction support |
| `DensitometryResult` | per-band Gaussian fit + integration | one-to-one with Band |
| `LaneDensitometrySummary` | per-lane aggregates + POI purity | one-to-one with Lane |
| `DensitometryJob` | async densitometry tracking | RUNNING/FAILED state machine |
| `SavedComparison` | persisted lane comparison | view_settings JSONField |
| `SavedComparisonLane` | M2M through with order | preserves comparison panel order |

## Services

```
services/
├── band_detection/        # 14 files — CV2 + derivative + hybrid + cross-lane
│   └── BandDetectionService — primary entry point
├── calibration/           # single + multi-ladder calibration
│   └── LadderCalibrationService, MultiLadderCalibrationService
├── densitometry/          # 10 files — Gaussian fitting + deconvolution + normalizer
│   └── DensitometryService — primary entry point
├── sam/                   # MobileSAM ONNX encoder + decoder
├── studio/                # template-learning UI for the admin
├── report/                # Word / Excel / PowerPoint exports (Phase 4)
├── file_handler.py        # upload pipeline (cv2 / tifffile / Pillow)
├── scn_parser.py          # Bio-Rad .scn format
└── template_learning.py   # learn ladder pattern from training calibrations
```

All services log via `phoresis_core.logging_config.get_logger(__name__)`.

## Celery tasks (9)

`tasks.py` exports:
- `detect_bands_lane_task`, `detect_bands_bulk_task`, `detect_bands_cv2_bulk_task`, `detect_bands_hybrid_bulk_task`
- `detect_peaks_profile_bulk_task` (DEPRECATED — kept for backward compat)
- `band_detection_ping_task`, `densitometry_ping_task`
- `run_densitometry_task`, `export_densitometry_csv_task`

All wrap `@robust_task(...)` from phoresis_core.

## URL surface

- `GET /images/`, `/images/upload/`, `/images/<uuid>/`, `/images/<uuid>/delete/`
- `GET /analyses/`, `/analyses/<uuid>/`, `/analyses/<uuid>/annotate/`, `/analyses/<uuid>/densitometry/`
- `GET /comparisons/`, `/comparisons/?lanes=<id1>,<id2>` or `?comparison=<uuid>`
- `POST /api/...` ~50 non-DRF JSON endpoints
- `/api/v2/...` 6 DRF ModelViewSets (Phase 4)

## ML models (108 MB, Git LFS)

`static/gel_analyzer/ml/`:
- `gel_analysis.onnx` (44 MB) — YOLO gel-type + lane/band detection
- `sam/mobile_sam.pt` (39 MB) + `sam/mobilesam_decoder.onnx` (16 MB) + `sam/mobilesam_decoder_quant.onnx` (8.5 MB)

## Integration notes

- `Lane.sample_metadata` is the extension point for analyzer-specific data — never break the existing schema; add fields here.
- `signals.py` is intentionally empty — see its docstring for how to reintroduce hooks if a future app adds a sample registry.
```

- [ ] **Step 5: Write `src/dashboard/docs/README.md`**

```markdown
# `dashboard`

Phoresis landing page — KPI cards + recent gels + quick actions.

## Purpose

Single home view (`/`) showing:
- 4 KPI cards (total gels, total analyses, pending, new in 7d) — animated via CountUp.js.
- Up to 6 recent gels grid with thumbnails.
- Empty state with upload CTA when no gels exist yet.

## Public surface

- `dashboard:home` — `/` (login required).
- `services.get_kpis()` and `services.get_recent_gels(limit=6)` are reusable from any app that wants the same aggregates.

## Key files

| File | Purpose |
|---|---|
| `views.py` | home_view |
| `services.py` | get_kpis(), get_recent_gels() |
| `templates/dashboard/home.html` | KPI grid + recent gels |
| `nav.py` | Dashboard registration in nav_registry (Management group, shortcut `D`) |

## Integration

- Imports `gel_analyzer.models.GelImage` and `GelAnalysis` lazily inside `services.py` to avoid circular imports if dashboard ever loads before gel_analyzer.
- Adding a new KPI card: extend `services.DashboardKPIs` and add a `{% kpi %}` cell in the template grid.
```

- [ ] **Step 6: Write `src/phoresis_ui/docs/README.md`**

```markdown
# `phoresis_ui`

The Phoresis design system — Tailwind CSS 4, design tokens, component templatetags, layout chrome, and icon set.

## Purpose

- CSS-variable-driven design tokens (`tokens.css`) consumed by Tailwind 4 via `@theme`.
- 9 component templatetags (`btn`, `card`, `badge`, `kpi`, `modal_chrome`, `confirm`, `toast_container`, `empty_state`, `skeleton`).
- Icon system: Lucide sprite (~50 curated icons) + 8 custom Phoresis SVGs (gel, ladder, blot, electrophoresis, densitometry, lane, band, peak).
- Layout chrome: `_layout.html`, `_sidebar.html`, `_topbar.html`, `_command_palette.html`.
- Alpine stores: `theme`, `toast`, `modal`, `palette`.
- HTMX 2 wiring: CSRF, indicators, auto-toast on response status.

## Public surface

### Templatetags

```django
{% load ui_components ui_icons %}

{% btn "Save" variant="primary" icon="check" %}
{% btn "Cancel" variant="ghost" %}
{% btn "Delete" variant="danger" hx_post="/x/" %}

{% badge "DRAFT" variant="warning" %}
{% kpi "Total" 42 icon="image" trend=5 %}
{% empty_state "No gels" message="Upload one." cta_label="Upload" cta_href="/images/upload/" %}
{% skeleton width="200px" %}

{% modal_chrome id_="my-modal" title="Edit lane" %}
{% confirm id_="delete-c1" title="Delete?" message="…" hx_post="/delete/" %}
{% toast_container %}

{% icon "home" size=20 %}        {# Lucide #}
{% icon "gel" %}                  {# custom Phoresis #}
```

### Alpine stores

```javascript
$store.theme.set('dark')          // 'auto' | 'light' | 'dark'
$store.toast.push({ variant: 'success', title: 'Saved' })
$store.modal.show('my-modal'); $store.modal.close()
$store.palette.show()             // also bound to Ctrl+K
```

## File structure

| Path | Purpose |
|---|---|
| `static/phoresis_ui/css/tokens.css` | design tokens (light + dark) |
| `static/phoresis_ui/css/input.css` | Tailwind directives + @theme + @layer components |
| `static/phoresis_ui/css/output.css` | built artefact (gitignored) |
| `static/phoresis_ui/js/alpine-init.js` | 4 stores |
| `static/phoresis_ui/js/htmx-config.js` | CSRF, error toasts |
| `static/phoresis_ui/js/animations.js` | CountUp, ripple, HTMX progress, view-transitions |
| `static/phoresis_ui/icons/lucide.svg` | sprite |
| `static/phoresis_ui/icons/custom/*.svg` | 8 Phoresis-specific glyphs |
| `templates/components/base.html` | extended by every page |
| `templates/components/_layout.html` | sidebar + topbar + content |

## Build

```bash
npm install
npm run build:css       # produces output.css
npm run watch:css       # dev watch mode
```

## Adding a new component

1. Add the templatetag in `ui_components.py`.
2. Create the partial in `templates/components/_<name>.html`.
3. Add a test in `tests/test_components.py`.
4. Document in `docs/DESIGN.md` component catalogue.
```

- [ ] **Step 7: Commit**

```bash
git add src/phoresis_core/docs/ src/accounts/docs/ src/gel_analyzer/docs/ src/dashboard/docs/ src/phoresis_ui/docs/
git commit -m "docs: add per-app README files (phoresis_core, accounts, gel_analyzer, dashboard, phoresis_ui)"
```

---

## Task 4: `docs/ARCHITECTURE.md`

**Files:**
- Create: `docs/ARCHITECTURE.md`
- Create: `docs/images/` (placeholder dir for screenshots — populated in Task 8)

The architecture doc is the single canonical reference for how Phoresis fits together. Mermaid diagrams render natively on GitHub.

- [ ] **Step 1: Create `docs/ARCHITECTURE.md`**

Required sections (write the actual prose):

1. **Overview** — 2-3 paragraphs: what Phoresis is, single-user laptop scope, how it relates to the original ds-hub-django.

2. **Apps & boundaries (Mermaid graph)**
   ```mermaid
   graph TD
     phoresis_ui[phoresis_ui<br/>design system] --> base[components/base.html]
     phoresis_core[phoresis_core<br/>infra] --> logging
     phoresis_core --> celery
     phoresis_core --> errors[ErrorLog]
     phoresis_core --> nav_registry
     accounts --> phoresis_core
     dashboard --> phoresis_core
     dashboard --> phoresis_ui
     dashboard --> gel_analyzer
     gel_analyzer --> phoresis_core
     gel_analyzer --> phoresis_ui
     gel_analyzer --> accounts
   ```

3. **Container layout (Mermaid C4)**
   ```mermaid
   graph TB
     subgraph Host["Host (Windows 11)"]
       PG[(PostgreSQL 17<br/>native)]
     end
     subgraph Docker["Docker Desktop / WSL2"]
       Caddy[Caddy 2<br/>:80 :443]
       Web[gunicorn<br/>4 workers]
       Worker[Celery worker<br/>queues: default heavy]
       Sched[Celery beat]
       Redis[(Redis 7)]
       WT[Watchtower]
     end
     Browser((Browser)) --> Caddy
     Caddy --> Web
     Web --> Redis
     Worker --> Redis
     Sched --> Redis
     Web -.host.docker.internal.-> PG
     Worker -.host.docker.internal.-> PG
     WT -->|pull every 03:00| GHCR[(ghcr.io)]
   ```

4. **Data flow — upload + analyze**
   ```mermaid
   sequenceDiagram
     Browser->>Caddy: POST /images/upload/ (HTMX)
     Caddy->>Web: reverse_proxy
     Web->>FileHandler: process_uploaded_file
     FileHandler-->>Web: {display_bytes, thumbnail_bytes, metadata}
     Web->>PG: INSERT GelImage
     Web-->>Browser: 302 → /images/<uuid>/
     Browser->>Caddy: GET /images/<uuid>/analyses/create/
     Caddy->>Web: reverse_proxy
     Web-->>Browser: HTML form
     Browser->>Caddy: POST .../create/
     Caddy->>Web: reverse_proxy
     Web->>PG: INSERT GelAnalysis
     Web-->>Browser: 302 → /analyses/<uuid>/annotate/
   ```

5. **Async hybrid band detection**
   ```mermaid
   sequenceDiagram
     Browser->>Web: POST /api/analyses/<uuid>/detect-bands-hybrid/async/
     Web->>Redis: enqueue detect_bands_hybrid_bulk_task (heavy queue)
     Web-->>Browser: 202 {task_id}
     Worker->>Redis: dequeue
     Worker->>HybridDetector: detect_all_lanes()
     HybridDetector-->>Worker: List[DetectedBand]
     Worker->>PG: bulk_create Band rows
     loop poll
       Browser->>Web: GET /api/celery-task/<id>/status/
       Web-->>Browser: {status: PROGRESS, percent: 60}
     end
     Browser->>Web: GET /api/celery-task/<id>/status/
     Web-->>Browser: {status: SUCCESS, bands: [...]}
   ```

6. **Watchtower update flow** — text + a small Mermaid sequence.

7. **CI/CD flow** — text + Mermaid showing `release-please` PR → tag → matrix build → GHCR push → Watchtower pull.

8. **Settings + secrets** — `.env` lifecycle (Phase 6 install.ps1 generates it; never committed).

9. **Volumes & persistence** — table of the 5 named volumes + native Postgres + which `down -v` wipes (and which it doesn't, by design).

- [ ] **Step 2: Create `docs/images/` placeholder**

```bash
mkdir -p docs/images
echo "# Screenshots" > docs/images/README.md
echo "Populated in Phase 7 Task 8 (INSTALL.md)." >> docs/images/README.md
```

- [ ] **Step 3: Commit**

```bash
git add docs/ARCHITECTURE.md docs/images/README.md
git commit -m "docs: add ARCHITECTURE.md with Mermaid diagrams (apps, containers, data flow, CI/CD)"
```

---

## Task 5: `docs/DESIGN.md`

**Files:**
- Create: `docs/DESIGN.md`

Sections (write the actual content):

- [ ] **Step 1: Create `docs/DESIGN.md`**

1. **Design philosophy** — Linear / Vercel / Notion class; deep lab blue + magenta (gel band) accents; light + dark first-class.

2. **Tokens** — full table referencing `tokens.css`:
   - Surfaces (light + dark)
   - Accent (deep lab blue ramp)
   - Gel semantics (band magenta, POI blue, MW reference green, other slate)
   - Status (success/warning/danger/info)
   - Typography (Inter sans, JetBrains Mono)
   - Spacing (4px rhythm)
   - Radius (6/10/14/20px)
   - Shadows (sm/md/lg)
   - Motion (ease-out cubic, 150/250/400ms durations)

3. **Components catalogue** — table from spec §8.2:
   - `{% btn %}` — variants × sizes × states (loading, disabled), ripple
   - `{% card %}` (open/close), `{% badge %}`, `{% kpi %}`, `{% modal_chrome %}`, `{% confirm %}`, `{% toast_container %}`, `{% empty_state %}`, `{% skeleton %}`
   - For each: usage example + accessibility notes (aria-label, focus trap, esc closes, etc.).

4. **Layout** — 72px collapsed icon-rail sidebar, 60px topbar, content max-w-7xl.

5. **Animations & micro-interactions** — full §8.4 list with timing values.

6. **Light/Dark mode** — `data-theme` attribute, `localStorage` + `UserProfile.theme` sync, transition specs.

7. **Icon system** — Lucide subset (list of 48) + 8 custom Phoresis (gel, ladder, blot, …) with quick visual + semantic guidance.

8. **Phoresis app icon** — direction chosen (gradient lane + 3 bands), where the artefacts live (`assets/icons/`).

9. **Accessibility checklist** — focus rings via `:focus-visible`, contrast ≥ AA in both modes, keyboard navigation (Ctrl+K, Tab through forms, Esc closes modals), ARIA on toast (`aria-live="polite"`), no text in images.

10. **Adding new components** — 4-step procedure (templatetag → partial → test → DESIGN.md entry).

- [ ] **Step 2: Commit**

```bash
git add docs/DESIGN.md
git commit -m "docs: add DESIGN.md (tokens, components, animations, accessibility)"
```

---

## Task 6: `docs/DEVELOPMENT.md`

**Files:**
- Create: `docs/DEVELOPMENT.md`

Sections:

- [ ] **Step 1: Create `docs/DEVELOPMENT.md`**

1. **Prerequisites** — Python 3.12, Node 20, Postgres 17, Redis 7, uv, Docker Desktop optional for local dev.

2. **Clone + setup**
   ```bash
   git clone https://github.com/gmathy2104/phoresis.git
   cd phoresis
   git lfs pull
   uv sync --extra dev
   npm install
   ```

3. **Database setup**
   ```bash
   psql -U postgres -c "CREATE USER phoresis WITH PASSWORD 'phoresis' SUPERUSER;"
   psql -U postgres -c "CREATE DATABASE phoresis OWNER phoresis;"
   .venv/Scripts/python.exe manage.py migrate
   .venv/Scripts/python.exe manage.py seed_groups
   .venv/Scripts/python.exe manage.py seed_ladder_templates
   .venv/Scripts/python.exe manage.py createsuperuser
   ```

4. **Run dev server**
   ```bash
   npm run watch:css      # terminal 1
   .venv/Scripts/python.exe manage.py runserver  # terminal 2
   # Optional terminal 3:
   .venv/Scripts/python.exe -m celery -A phoresis_core.celery_app worker --loglevel=info -Q default,heavy
   ```

5. **Tests**
   ```bash
   pytest -v                              # ~285 unit/integration tests
   pytest -m e2e -v                       # Playwright (Phase 4)
   pytest src/gel_analyzer/ -v            # one app
   pytest --cov=src --cov-report=html     # coverage report → htmlcov/
   ```

6. **Code style**
   - `ruff check .` + `ruff format .` (configured in `pyproject.toml`).
   - Pre-commit auto-runs on `git commit` (install via `pre-commit install`).
   - Conventional Commits — see `CONTRIBUTING.md`.

7. **Adding a Django app** — checklist: create directory, `__init__.py`, `apps.py`, add to `INSTALLED_APPS`, `nav.py` if visible to the navigation, migrations, tests.

8. **Adding a Celery task** — `@robust_task(soft_time_limit=..., time_limit=...)`, register in `STALE_TASK_REGISTRY` if it touches a model with a `RUNNING` status field.

9. **Working with the design system** — link to `docs/DESIGN.md` step 9 ("Adding new components").

10. **Debugging tips** — loguru output, `/admin/phoresis_core/errorlog/`, Django Debug Toolbar (dev only), pytest `-x --pdb`.

- [ ] **Step 2: Commit**

```bash
git add docs/DEVELOPMENT.md
git commit -m "docs: add DEVELOPMENT.md (clone, deps, run, tests, conventions)"
```

---

## Task 7: `docs/DEPLOYMENT.md`

**Files:**
- Create: `docs/DEPLOYMENT.md`

Sections:

- [ ] **Step 1: Create `docs/DEPLOYMENT.md`**

1. **Release flow** — Conventional Commits → release-please PR → merge → tag `vX.Y.Z` → matrix build → GHCR push → GitHub Release. Diagram from ARCHITECTURE.md re-used.

2. **Versioning** — SemVer rules (MAJOR breaking, MINOR feature, PATCH fix).

3. **Image variants** — `:vX.Y.Z-cpu` + `:latest-cpu` + `:vX.Y.Z-cuda` + `:latest-cuda`. How the user picks one in `.env` (`PHORESIS_IMAGE_VARIANT=cpu|cuda`).

4. **Watchtower** — pulls `:latest-{variant}` daily at 03:00, restarts only the labelled containers, never touches Caddy/Redis.

5. **Manual update** — `scripts/update.ps1`.

6. **Rollback** — `scripts/update.ps1 -Rollback v1.2.3`. How the pin disables Watchtower.

7. **Backup + restore** — `scripts/backup.ps1` daily via Task Scheduler; `scripts/restore.ps1` interactive.

8. **Healthchecks** — what each endpoint reports, how Caddy gates upstream, what to do when `/healthz/` returns 503.

9. **Logs** — where to find them: `docker compose logs <service>`, `logs/` volume mount on the host (Phase 5 `docker-compose.yml`).

10. **Common troubleshooting** — table:
    | Symptom | Likely cause | Fix |
    |---|---|---|
    | `https://phoresis/` shows cert warning | Caddy CA not trusted | Re-run `install.ps1` (it runs `Import-Certificate`) |
    | Web container in `unhealthy` loop | Postgres unreachable | Check `pg_hba.conf` allows Docker bridge subnet |
    | Worker stuck at "no workers" in /healthz/ | Redis container not started | `docker compose up -d redis` |
    | Pull fails on Watchtower | GHCR image went private | Add `WATCHTOWER_AUTH_USERNAME`/`PASSWORD` |

- [ ] **Step 2: Commit**

```bash
git add docs/DEPLOYMENT.md
git commit -m "docs: add DEPLOYMENT.md (release flow, Watchtower, rollback, troubleshooting)"
```

---

## Task 8: `docs/INSTALL.md` + screenshots

**Files:**
- Create: `docs/INSTALL.md`
- Capture: 6-8 screenshots into `docs/images/`

This is the doc the primary user (and any future colleague) reads first. Tested by walking the primary user through it (Task 10). Step-by-step, screenshot-heavy.

- [ ] **Step 1: Capture the required screenshots**

Run the local stack (`scripts/start.ps1` or `runserver`) and capture (Windows: Win+Shift+S):

| Filename | Content |
|---|---|
| `hero-dashboard.png` | logged-in dashboard with KPI cards animated, recent gels grid populated |
| `install-step-1.png` | PowerShell elevation prompt + first lines of install.ps1 output |
| `install-step-2.png` | the interactive `.env` prompt screen |
| `install-step-3.png` | desktop shortcut + browser at `https://phoresis/` |
| `annotate-viewer.png` | annotation editor with a gel image + lanes drawn |
| `densitometry-view.png` | densitometry view with electropherogram |
| `comparison-view.png` | 4-panel comparison view |
| `theme-toggle.png` | the topbar with the theme switcher highlighted |

Place all in `docs/images/`. Use 1280×800 viewport for consistency.

If a real gel image isn't available, the synthetic fixture from Phase 2 is fine — it's clearly a demo.

- [ ] **Step 2: Create `docs/INSTALL.md`**

Sections (write actual prose):

1. **Hero shot + intro** — 1 paragraph explaining what Phoresis does for the user.

2. **Prerequisites** — Windows 10/11, ≥16 GB RAM, ≥60 GB disk, internet, NVIDIA GPU optional.

3. **Step 1 — Download** — clone or download zip; `git lfs pull`.

4. **Step 2 — Run the installer (admin)** — right-click `scripts\install.ps1` → Run with PowerShell as Administrator. Screenshot.

5. **Step 3 — Docker Desktop install (if first run)** — explanation of the sign-out/sign-in interrupt; re-run the script after.

6. **Step 4 — Postgres password** — set during winget install; later prompted by install.ps1 to create the `phoresis` DB.

7. **Step 5 — `.env` prompts** — screenshots of admin email/password, lab user email/password.

8. **Step 6 — First boot** — what to expect (download images + start stack); the browser opens automatically.

9. **Step 7 — Sign in** — using the lab user credentials from step 5.

10. **Step 8 — Daily use** — desktop shortcut → start.ps1 → browser; close stops nothing (use Stop on the shortcut menu / `scripts\stop.ps1`).

11. **Backup setup** — Task Scheduler walkthrough (copy from Phase 6 CONTRIBUTING.md).

12. **Updating** — Watchtower handles automatically at 03:00. Manual: `scripts\update.ps1`.

13. **If something breaks** — link to `docs/DEPLOYMENT.md` troubleshooting + how to reach support (with the `PHOR-` reference ID).

14. **Uninstall** — `scripts\stop.ps1 -Wipe` to wipe volumes (NOT Postgres data); manually `winget uninstall Docker.DockerDesktop` and `winget uninstall PostgreSQL.PostgreSQL.17` if desired.

- [ ] **Step 3: Commit**

```bash
git add docs/INSTALL.md docs/images/
git commit -m "docs: add INSTALL.md (end-user walkthrough with screenshots)"
```

---

## Task 9: Root README + final CHANGELOG / CONTRIBUTING review

**Files:**
- Modify: `README.md` (root) — replaces the Phase 1 placeholder
- Modify: `CHANGELOG.md` — final review
- Modify: `CONTRIBUTING.md` — final review

- [ ] **Step 1: Replace `README.md`**

Sections:

1. **Hero shot** — `![Phoresis dashboard](docs/images/hero-dashboard.png)`

2. **Tagline** — "Standalone gel electrophoresis analysis platform — runs on your laptop, no cloud."

3. **Features** — 5-7 bullets:
   - SDS-PAGE / Dot Blot / Western Blot
   - Hybrid band detection (CV2 + d1/d2 derivative + cross-lane consensus)
   - MobileSAM polygon refinement
   - MW calibration (single + multi-ladder, gel-smile correction)
   - Densitometry with Gaussian fitting + POI purity
   - Word / Excel / PowerPoint reports
   - Local install + auto-update (no cloud, no telemetry)

4. **Quick start** — link to `docs/INSTALL.md`. Mention the 5-min target.

5. **Screenshots** — 3-4 from `docs/images/` (annotate, densitometry, comparison, theme toggle).

6. **For developers** — link to `docs/DEVELOPMENT.md`.

7. **Architecture** — 1-paragraph + link to `docs/ARCHITECTURE.md`.

8. **License** — link to `LICENSE`.

9. **Acknowledgements** — original `gel_analyzer` lineage, MobileSAM, Lucide, Tailwind, Django.

- [ ] **Step 2: Review `CHANGELOG.md`**

Run `release-please` locally if installed:
```bash
npx release-please release-pr --token $GITHUB_TOKEN --repo-url https://github.com/gmathy2104/phoresis --config-file .github/release-please-config.json --manifest-file .github/.release-please-manifest.json --dry-run
```

(Optional — the actual update happens via the Action when v1.0.0 lands.)

Manually verify:
- Each phase has an entry from v0.1.0 through v0.5.0 (Phase 6 is in-progress, Phase 7 closes with v1.0.0).
- All entries match the Conventional Commit messages used.

- [ ] **Step 3: Review `CONTRIBUTING.md`**

Verify it has:
- Release flow (Phase 6 added)
- Manual rollback (Phase 6 added)
- Image visibility (Phase 6 added)
- Scheduled backups (Phase 6 added)
- (NEW Phase 7) Documentation contributions guide — how to update docs when adding features.

Add a "Documentation" section:

```markdown
## Documentation

When you add or change a feature, update the relevant doc:

- New templatetag → `docs/DESIGN.md` component catalogue + `src/phoresis_ui/docs/README.md`.
- New service in `gel_analyzer` → `src/gel_analyzer/docs/README.md`.
- New PowerShell script → `docs/DEPLOYMENT.md` + maybe `docs/INSTALL.md`.
- New Celery task → `src/gel_analyzer/docs/README.md` + ARCHITECTURE.md if it changes the data flow.
- Architectural decision → consider an ADR under `docs/adr/` (template at `docs/adr/_template.md`).
```

- [ ] **Step 4: Cross-link audit**

Walk the docs and confirm every internal link works:
```bash
# Quick sanity scan — flags broken `(./docs/X.md)` links
.venv/Scripts/python.exe -c "
import re, pathlib
root = pathlib.Path('.')
md_files = list(root.glob('**/*.md'))
md_paths = {p.resolve() for p in md_files}
broken = []
for p in md_files:
    text = p.read_text(encoding='utf-8')
    for m in re.finditer(r'\]\(([^)]+\.md)\)', text):
        target = (p.parent / m.group(1)).resolve()
        if target not in md_paths and not str(target).startswith('http'):
            broken.append((p, m.group(1)))
for p, link in broken:
    print(f'{p}: {link}')
print(f'Total broken: {len(broken)}')
"
```
Fix any reported broken links.

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md CONTRIBUTING.md
git commit -m "docs: finalize README + CHANGELOG + CONTRIBUTING for v1.0.0"
```

---

## Task 10: Hands-on validation + tag v1.0.0

**Files:**
- (Manual step) Walk through with the primary user
- Tag `v1.0.0`

- [ ] **Step 1: Final automated checks**

```bash
.venv/Scripts/python.exe -m pytest -v
.venv/Scripts/python.exe -m pytest tests/e2e/ -m e2e -v
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m pre_commit run --all-files
npm run build:css
```
Expected: all green.

- [ ] **Step 2: Build the production images locally**

```bash
docker build -f docker/Dockerfile.web --build-arg TORCH_VARIANT=cpu -t phoresis-web:v1-test .
docker build -f docker/Dockerfile.worker --build-arg TORCH_VARIANT=cpu -t phoresis-worker:v1-test .
```

Set `PHORESIS_WEB_IMAGE=phoresis-web:v1-test` + `PHORESIS_WORKER_IMAGE=phoresis-worker:v1-test` in `.env` and bring up the stack:

```bash
docker compose -f docker/docker-compose.yml --env-file .env up -d
```

Wait for healthcheck.

- [ ] **Step 3: Walk through with the primary user**

Sit beside her (or screen-share) and have her:

1. Visit `https://phoresis/` — sign in.
2. Browse her existing test gels (uploaded from her own files).
3. Upload a new gel via the dropzone.
4. Create an analysis.
5. Open the annotation editor — place lanes, drag bands.
6. Run hybrid detection — verify bands are correct.
7. Open densitometry — verify electropherogram looks right.
8. Run a comparison between two lanes.
9. Generate a Word report — open it and confirm it's usable.
10. Toggle dark mode — verify she likes how it looks.
11. Sign out + sign in with a different role (admin) — confirm permissions feel right.

Take notes during the walk-through. Anything she stumbles on, asks "what does this do?", or says "I'd prefer if…" → file an issue (or fix inline if trivial).

- [ ] **Step 4: Address any high-priority feedback**

For each blocker (anything that prevents her from doing real work):
- Fix it inline if trivial.
- Document as a known issue in `docs/INSTALL.md` "Known issues" if non-trivial — *blocks the v1.0.0 tag*.

For nice-to-haves: note in a `docs/ROADMAP.md` (create if missing) and proceed to tag.

- [ ] **Step 5: Final commit**

```bash
git status
```
If anything changed:
```bash
git add -u
git commit -m "fix: rough-edge fixes from primary user walkthrough"
```

- [ ] **Step 6: Tag v1.0.0**

```bash
git tag -a v1.0.0 -m "Phoresis v1.0.0 — standalone gel electrophoresis analysis platform.

Phase 7 closes the project with:
- Final micro-interactions (ripple, HTMX progress bar, sidebar scale, dropzone pulse, floating labels).
- Custom 404 / 500 pages with PHOR- error reference IDs.
- Full documentation suite (README, INSTALL, ARCHITECTURE, DEVELOPMENT, DEPLOYMENT, DESIGN + 5 per-app READMEs).
- Hands-on validation with primary user.

See CHANGELOG.md for the full feature set."
```

- [ ] **Step 7: Push everything**

```bash
git push origin claude/hopeful-franklin-e45f1b
git push origin --tags
```

The push triggers `release.yml` on the v1.0.0 tag, building the 4-image matrix and pushing to GHCR. Watch the Actions tab; intervene only if something fails.

---

## Acceptance criteria for Phase 7

This phase is **done** when ALL of the following hold:

1. Every spec §8.4 micro-interaction is live in the running app (ripple, HTMX progress, sidebar scale, dropzone pulse, floating labels).
2. `/this-does-not-exist/` renders the branded 404 page; an actual 500 (e.g., DB down) renders the 500 page with a `PHOR-YYYYMMDD-XXXXXX` reference ID.
3. `docs/` contains 6 top-level docs (`README.md` at root, plus `INSTALL.md`, `ARCHITECTURE.md`, `DEVELOPMENT.md`, `DEPLOYMENT.md`, `DESIGN.md` under `docs/`).
4. 5 per-app `docs/README.md` files exist (one per: `phoresis_core`, `accounts`, `gel_analyzer`, `dashboard`, `phoresis_ui`).
5. `docs/images/` contains at least 6 screenshots referenced by `INSTALL.md` and the root `README.md`.
6. `CHANGELOG.md` has an entry for every released phase v0.1.0 through v0.6.0, plus the v1.0.0 entry covering Phase 7.
7. `CONTRIBUTING.md` covers release flow, rollback, image visibility, scheduled backups, and the documentation contribution guidance.
8. All internal markdown links resolve (cross-link audit script reports 0 broken).
9. The full automated suite is green: `pytest -v`, `pytest -m e2e -v`, `ruff check .`, `ruff format --check .`, `pre-commit run --all-files`, `npm run build:css`.
10. Hands-on walkthrough with the primary user completed; no blocking issues open.
11. The git tag `v1.0.0` exists. When pushed, `release.yml` triggers the 4-image matrix build and pushes to GHCR.
12. The author can run `scripts/install.ps1` on a freshly imaged Windows 11 VM and end up at `https://phoresis/` with the primary user account ready, in under 20 minutes (cold cache).

**Phoresis is now in production for the primary user. Subsequent feature work proceeds via Conventional Commits → release-please → Watchtower auto-update on her laptop at 03:00 daily.**
