# Phoresis — Phase 3 (Frontend Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the complete Phoresis design system (Tailwind 4 + design tokens + 10 component templatetags + icon system + Alpine stores + HTMX config) and deliver the five Phase-3 shell pages (login, profile, dashboard, image list/upload/detail/delete, analysis list/create) with full light/dark theme parity, Lucide-class polish, and the Phoresis app icon — culminating in `v0.3.0`.

**Architecture:** Tailwind 4 with the `@theme` directive consuming CSS-variable design tokens from `tokens.css`. Each component templatetag emits a small, focused HTML fragment with semantic Tailwind utility classes that resolve to those tokens (so dark mode flips automatically via `data-theme="dark"` on `<html>`). Alpine.js holds four global stores (`theme`, `toast`, `modal`, `palette`) — pure client-side state, no Django round-trips needed for UI chrome. HTMX 2 powers page swaps, form submits, and async polling. Heavy viewers stay deferred to Phase 4; this phase delivers the polished *shell* into which those viewers slot.

**Tech Stack delta:** Adds Node 20 + npm + Tailwind CSS 4 + @tailwindcss/forms + @tailwindcss/typography + @tailwindcss/container-queries; runtime adds CountUp.js (KPI animations), Lucide Icons. HTMX 2 and Alpine.js 3 are loaded from CDN in dev (vendored to `static/` in Phase 5 once Docker stack lands, to avoid CDN dependency for the offline laptop install).

**Source repo for ports:** `C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/` — referenced as `$DSHUB`. **Note:** the original `views/` and `forms/` are NOT direct ports — they used MDB5. We rewrite them in Phoresis style; the source is consulted for *business logic* (the upload-and-process flow, the queryset filtering, the KPI math) and that logic is preserved verbatim. The HTML and CSS are 100% new.

---

## Build Order Rationale

Phase 3 has hard front-to-back dependencies — UI primitives feed into composite templatetags feed into pages:

1. **Tailwind build pipeline** (Task 1) — every later task references Tailwind classes that must compile cleanly.
2. **Design tokens** (Task 2) — colors, typography, spacing, shadows, motion. The `base.html` refonte slots these in.
3. **Icon system** (Task 3) — Lucide sprite + 6-8 custom SVG glyphs + `{% icon %}` templatetag. Every component templatetag uses it.
4. **Component templatetags** (Task 4) — `{% btn %}, {% card %}, {% badge %}, {% empty_state %}, {% skeleton %}, {% modal %}, {% confirm %}, {% toast %}, {% kpi %}` — bundled into one task because they share the same rendering pattern (render via `template.render` against a snippet) and tests fit one file.
5. **Alpine stores + HTMX config** (Task 5) — wires the runtime: `theme`, `toast`, `modal`, `palette` stores + HTMX CSRF + indicators + auto-toast on response status.
6. **Layout shell** (Task 6) — sidebar, topbar, extends layout. Composes everything from Tasks 2-5.
7. **Command palette** (Task 7) — Ctrl+K modal with uFuzzy search over `nav_registry.get_flat_items()`.
8. **Theme switcher** (Task 8) — auto/light/dark toggle wired to the `theme` store + `UserProfile.theme` persistence.
9. **Phoresis app icon** (Task 9) — three mockups → user picks one → generate `.ico` (multi-resolution), `.svg`, favicons.
10. **Refonte accounts/login + profile** (Task 10) — first pages to actually `{% extends 'components/base.html' %}` for real.
11. **Refonte dashboard/home** (Task 11) — KPI cards (CountUp.js), recent gels, quick actions.
12. **gel_analyzer image pages** (Task 12) — list (cards + table dual mode), upload (drag-drop), detail, delete-confirm.
13. **gel_analyzer analysis pages** (Task 13) — list, create.
14. **Forms refonte + URL wiring + nav.py update** (Task 14) — Tailwind-styled `forms.ModelForm`s, populate `gel_analyzer.urls.py`, expand `gel_analyzer.nav.py` pages.
15. **End-to-end browser smoke + tag v0.3.0** (Task 15) — start `runserver`, walk every page, verify visual coherence and theme switch.

---

## File Structure (additions to Phase 2)

```
package.json                                     # Tailwind build deps
tailwind.config.js                               # token wiring
postcss.config.js                                # autoprefixer

src/phoresis_ui/
├── static/phoresis_ui/
│   ├── css/
│   │   ├── input.css                            # Tailwind directives + @theme + @layer
│   │   ├── tokens.css                           # design tokens (CSS variables) — full set
│   │   └── output.css                           # built artifact (gitignored, regenerated)
│   ├── js/
│   │   ├── htmx-config.js                       # CSRF, indicators, auto-toast
│   │   ├── alpine-init.js                       # 4 stores: theme, toast, modal, palette
│   │   └── animations.js                        # GSAP-free helpers + view-transition fallback
│   └── icons/
│       ├── lucide.svg                           # sprite assembled from a curated subset
│       └── custom/
│           ├── gel.svg
│           ├── ladder.svg
│           ├── blot.svg
│           ├── electrophoresis.svg
│           ├── densitometry.svg
│           ├── lane.svg
│           ├── band.svg
│           └── peak.svg
├── templatetags/
│   ├── ui_components.py                         # 9 components (Task 4)
│   ├── ui_icons.py                              # {% icon %}
│   └── ui_animations.py                         # {% slide_in %}, {% fade_in %}, {% stagger %}
├── templates/components/
│   ├── base.html                                # full HTML5 shell (replaces stub)
│   ├── _layout.html                             # sidebar + topbar + content
│   ├── _sidebar.html
│   ├── _topbar.html
│   ├── _command_palette.html                    # Ctrl+K modal
│   ├── _toast.html                              # toast stack
│   ├── _confirm_modal.html
│   └── _empty_state.html
└── tests/
    ├── test_templatetags.py                     # extended from Phase 1
    ├── test_components.py                       # NEW: btn/card/etc. rendering
    └── test_layout.py                           # NEW: sidebar/topbar/base composition

src/accounts/templates/accounts/
├── login.html                                   # REFONTE — extends base.html
└── profile.html                                 # REFONTE — extends base.html, with theme switcher

src/dashboard/
├── services.py                                  # NEW: KPI aggregation helpers
├── views.py                                     # extended: queries + KPIs
└── templates/dashboard/
    └── home.html                                # REFONTE — KPI cards + recent gels + quick actions

src/gel_analyzer/
├── views/
│   ├── __init__.py                              # NEW (Phase 3)
│   ├── images.py                                # NEW: list, upload, detail, delete
│   └── analyses.py                              # NEW: list, create
├── forms/
│   ├── __init__.py                              # NEW
│   ├── image_forms.py                           # NEW (no MDB5 widgets)
│   └── analysis_forms.py                        # NEW (creation form only — annotate is Phase 4)
├── urls.py                                      # POPULATED
├── nav.py                                       # EXTENDED with pages + actions
└── templates/gel_analyzer/
    ├── images/
    │   ├── list.html
    │   ├── upload.html
    │   ├── detail.html
    │   └── _delete_modal.html                   # HTMX-loaded confirm modal
    └── analyses/
        ├── list.html
        └── create.html

assets/icons/                                    # repo-root, not under src/
├── phoresis.ico                                 # multi-resolution
├── phoresis.svg                                 # source
├── phoresis-512.png                             # macOS / desktop shortcut
├── apple-touch-icon.png                         # 180×180
└── mask-icon.svg                                # Safari pinned tab
```

---

## Standing reference — design tokens (verbatim from spec §8.1)

These tokens land in `src/phoresis_ui/static/phoresis_ui/css/tokens.css` in Task 2. The file is the **single source of truth** for the design system. Every Tailwind utility used downstream resolves to one of these via `@theme` (Task 1).

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
  --color-poi: #2563eb;
  --color-mw-ref: #10b981;
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

---

## Task 1: Tailwind 4 build pipeline

**Files:**
- Create: `package.json`
- Create: `tailwind.config.js`
- Create: `postcss.config.js`
- Modify: `.gitignore` (ignore `node_modules/`, `output.css`)
- Modify: `pyproject.toml` (add a tiny `phoresis_ui_assets` dev script if useful)

- [ ] **Step 1: Verify Node + npm are available**

```bash
node --version
npm --version
```
Expected: Node ≥ 20, npm ≥ 10.

If not installed: `winget install -e --id OpenJS.NodeJS.LTS` (Windows) or system equivalent.

- [ ] **Step 2: Create `package.json` at the worktree root**

```json
{
  "name": "phoresis-ui",
  "version": "0.3.0",
  "private": true,
  "scripts": {
    "build:css": "tailwindcss -i src/phoresis_ui/static/phoresis_ui/css/input.css -o src/phoresis_ui/static/phoresis_ui/css/output.css --minify",
    "watch:css": "tailwindcss -i src/phoresis_ui/static/phoresis_ui/css/input.css -o src/phoresis_ui/static/phoresis_ui/css/output.css --watch"
  },
  "devDependencies": {
    "@tailwindcss/cli": "^4.0.0",
    "@tailwindcss/forms": "^0.5.9",
    "@tailwindcss/typography": "^0.5.15",
    "@tailwindcss/container-queries": "^0.1.1",
    "tailwindcss": "^4.0.0",
    "postcss": "^8.4.47",
    "autoprefixer": "^10.4.20"
  }
}
```

- [ ] **Step 3: Create `postcss.config.js`**

```javascript
module.exports = {
  plugins: {
    "@tailwindcss/postcss": {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 4: Create `tailwind.config.js`**

Tailwind 4 mostly auto-discovers content; we still pin the relevant globs for predictability.

```javascript
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{html,py,js}",
    "./src/phoresis_ui/templates/**/*.html",
  ],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {},
  },
  plugins: [
    require("@tailwindcss/forms"),
    require("@tailwindcss/typography"),
    require("@tailwindcss/container-queries"),
  ],
};
```

- [ ] **Step 5: Append node + Tailwind exclusions to `.gitignore`**

Add this block:

```
# --- Node / Tailwind ---
node_modules/
src/phoresis_ui/static/phoresis_ui/css/output.css
src/phoresis_ui/static/phoresis_ui/css/output.css.map
package-lock.json
```

(`package-lock.json` is gitignored in Phase 3 because the front-end build is dev-only at this stage. Phase 5 commits it once the Docker image build needs reproducibility.)

- [ ] **Step 6: Install npm deps**

```bash
npm install
```
Expected: `node_modules/` materialises, no warnings beyond the usual peer-dep notes.

- [ ] **Step 7: Sanity-check the Tailwind CLI**

The `input.css` file doesn't exist yet (Task 2 creates it), so we just confirm the tool is reachable:

```bash
npx tailwindcss --help | head -5
```
Expected: usage banner.

- [ ] **Step 8: Commit**

```bash
git add package.json postcss.config.js tailwind.config.js .gitignore
git commit -m "build: add Tailwind 4 build pipeline (npm + tailwind.config + postcss)"
```

---

## Task 2: Design tokens + Tailwind input.css + base.html refonte

**Files:**
- Create: `src/phoresis_ui/static/phoresis_ui/css/tokens.css`
- Create: `src/phoresis_ui/static/phoresis_ui/css/input.css`
- Modify: `src/phoresis_ui/templates/components/base.html`

- [ ] **Step 1: Create `tokens.css`**

Copy the verbatim CSS block from the **Standing reference — design tokens** section above into:

```
src/phoresis_ui/static/phoresis_ui/css/tokens.css
```

(Do not paraphrase — the spec defines this byte-for-byte.)

- [ ] **Step 2: Create `input.css`**

This is the file Tailwind reads. It pulls in tokens, declares a `@theme` block that maps Tailwind's color palette to our CSS variables, and sets minimal global styles.

```css
@import "tailwindcss";
@import "./tokens.css";

@theme {
  --color-bg: var(--color-bg);
  --color-surface: var(--color-surface);
  --color-surface-elevated: var(--color-surface-elevated);
  --color-border: var(--color-border);
  --color-text: var(--color-text);
  --color-text-muted: var(--color-text-muted);

  --color-accent-50: var(--color-accent-50);
  --color-accent-500: var(--color-accent-500);
  --color-accent-600: var(--color-accent-600);
  --color-accent-700: var(--color-accent-700);

  --color-band: var(--color-band);
  --color-poi: var(--color-poi);
  --color-mw-ref: var(--color-mw-ref);
  --color-other: var(--color-other);

  --color-success: var(--color-success);
  --color-warning: var(--color-warning);
  --color-danger: var(--color-danger);
  --color-info: var(--color-info);

  --font-sans: var(--font-sans);
  --font-mono: var(--font-mono);

  --radius-sm: var(--radius-sm);
  --radius: var(--radius);
  --radius-lg: var(--radius-lg);
  --radius-xl: var(--radius-xl);
}

@layer base {
  html, body {
    background: var(--color-bg);
    color: var(--color-text);
    font-family: var(--font-sans);
    transition: background-color var(--duration) var(--ease-out),
                color var(--duration) var(--ease-out);
  }

  /* Smooth focus rings using accent token */
  *:focus-visible {
    outline: 2px solid var(--color-accent-500);
    outline-offset: 2px;
  }

  /* Light text-balance for headings */
  h1, h2, h3, h4 {
    text-wrap: balance;
  }
}

@layer components {
  /* Shimmer for skeleton loaders */
  .ui-shimmer {
    position: relative;
    overflow: hidden;
    background: var(--color-border);
  }
  .ui-shimmer::after {
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(
      90deg,
      transparent 0%,
      rgba(255,255,255,.4) 50%,
      transparent 100%
    );
    animation: ui-shimmer-anim 2s infinite;
  }
  [data-theme="dark"] .ui-shimmer::after {
    background: linear-gradient(
      90deg,
      transparent 0%,
      rgba(255,255,255,.06) 50%,
      transparent 100%
    );
  }
  @keyframes ui-shimmer-anim {
    from { transform: translateX(-100%); }
    to   { transform: translateX(100%); }
  }
}
```

- [ ] **Step 3: Build the CSS**

```bash
npm run build:css
```
Expected: `src/phoresis_ui/static/phoresis_ui/css/output.css` is created (~50-100 KB before compression).

If the build fails complaining about Tailwind 4 syntax, check that `tailwindcss` and `@tailwindcss/cli` are both v4 (not v3).

- [ ] **Step 4: Refonte `base.html`**

Replace `src/phoresis_ui/templates/components/base.html` (currently a Phase 1 stub) with the full version. This is what every page extends.

```django
{% load static %}<!DOCTYPE html>
<html lang="{{ request.user.profile.language|default:'en' }}"
      data-theme="{% if request.user.is_authenticated %}{{ request.user.profile.theme|default:'auto' }}{% else %}auto{% endif %}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Phoresis{% endblock %}</title>

    <link rel="icon" type="image/x-icon" href="{% static 'phoresis_ui/icons/phoresis.ico' %}">
    <link rel="icon" type="image/svg+xml" href="{% static 'phoresis_ui/icons/phoresis.svg' %}">
    <link rel="apple-touch-icon" href="{% static 'phoresis_ui/icons/apple-touch-icon.png' %}">
    <link rel="mask-icon" href="{% static 'phoresis_ui/icons/mask-icon.svg' %}" color="#3b82f6">

    <link rel="stylesheet" href="{% static 'phoresis_ui/css/output.css' %}">

    <script>
      /* Inline theme application — runs before paint to avoid the dark/light flash. */
      (function () {
        const stored = localStorage.getItem("phoresis_theme");
        const initial = stored || document.documentElement.getAttribute("data-theme") || "auto";
        const resolved = initial === "auto"
          ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
          : initial;
        document.documentElement.setAttribute("data-theme", resolved);
        document.documentElement.dataset.userTheme = initial;
      })();
    </script>

    {% block head %}{% endblock %}
</head>
<body class="min-h-screen bg-bg text-text antialiased">
    {% block body %}
        <main class="mx-auto max-w-7xl px-6 md:px-8 py-8">
            {% block content %}{% endblock %}
        </main>
    {% endblock %}

    <!-- HTMX 2 + Alpine.js 3 from CDN in dev (vendored in Phase 5) -->
    <script defer src="https://unpkg.com/htmx.org@2.0.3"></script>
    <script defer src="https://unpkg.com/alpinejs@3.14.3/dist/cdn.min.js"></script>

    <script src="{% static 'phoresis_ui/js/htmx-config.js' %}" defer></script>
    <script src="{% static 'phoresis_ui/js/alpine-init.js' %}" defer></script>
    <script src="{% static 'phoresis_ui/js/animations.js' %}" defer></script>

    {% block scripts %}{% endblock %}
</body>
</html>
```

The `assets/icons/*` referenced here are produced in Task 9. Until Task 9 lands, the icon links 404 — that's harmless (the tags don't block rendering).

- [ ] **Step 5: Update Phase 1's `test_base_template_extends_render` to expect "Phoresis" title**

Edit `src/phoresis_ui/tests/test_templatetags.py` — the existing test already checks for `"Phoresis" in rendered`, which passes. Verify:

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_ui/tests/test_templatetags.py -v
```
Expected: 3 tests pass.

- [ ] **Step 6: Smoke-test the build hooks into Django**

```bash
.venv/Scripts/python.exe manage.py collectstatic --noinput --dry-run | head -20
```
Expected: lists `phoresis_ui/css/output.css` and `phoresis_ui/css/tokens.css` as files that would be collected.

- [ ] **Step 7: Commit**

```bash
git add src/phoresis_ui/static/phoresis_ui/css/tokens.css src/phoresis_ui/static/phoresis_ui/css/input.css src/phoresis_ui/templates/components/base.html
git commit -m "feat(phoresis_ui): add design tokens, Tailwind input, and refactor base.html"
```

---

## Task 3: Icon system — Lucide sprite + 8 custom SVGs + `{% icon %}` templatetag

**Files:**
- Create: `src/phoresis_ui/static/phoresis_ui/icons/lucide.svg` (curated subset, ~50 icons)
- Create: 8 SVGs in `src/phoresis_ui/static/phoresis_ui/icons/custom/`
- Modify: `src/phoresis_ui/templatetags/ui_icons.py` (replace stub with real `{% icon %}`)
- Create: `src/phoresis_ui/tests/test_components.py` (icon tests)

> **Note on Lucide assembly:** Rather than commit the full ~1,500-icon Lucide sprite (~300 KB), we build a curated sprite from the Lucide source containing only the icons Phoresis uses. The `lucide` npm package isn't pinned in `package.json` — the agent runs `npx @lucide/cli build-sprite` once with the icon list.

- [ ] **Step 1: Decide the curated icon list**

Based on the templates referenced in this plan + spec, the Phase 3 icon set is:

```
home, layout-dashboard, image, upload, download, file-text, settings,
search, bell, user, log-out, log-in, plus, edit, trash-2, copy, eye,
chevron-down, chevron-up, chevron-left, chevron-right, x, check,
alert-circle, alert-triangle, info, check-circle, loader, sun, moon,
monitor, palette, flask-conical, microscope, beaker, kanban, wrench,
trending-up, bar-chart-3, pie-chart, command, sparkles, more-horizontal,
filter, sort-asc, layers, grid-2x2, list, refresh-cw
```

(48 icons. If a future template references one not in this list, the agent adds it to the list and rebuilds the sprite.)

- [ ] **Step 2: Build the Lucide sprite**

Lucide doesn't ship a CLI sprite builder, so we use a one-shot script. Create `tools/build_lucide_sprite.mjs`:

```javascript
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { execSync } from "node:child_process";

const ICONS = [
  "home", "layout-dashboard", "image", "upload", "download", "file-text", "settings",
  "search", "bell", "user", "log-out", "log-in", "plus", "edit", "trash-2", "copy", "eye",
  "chevron-down", "chevron-up", "chevron-left", "chevron-right", "x", "check",
  "alert-circle", "alert-triangle", "info", "check-circle", "loader", "sun", "moon",
  "monitor", "palette", "flask-conical", "microscope", "beaker", "kanban", "wrench",
  "trending-up", "bar-chart-3", "pie-chart", "command", "sparkles", "more-horizontal",
  "filter", "sort-asc", "layers", "grid-2x2", "list", "refresh-cw",
];

execSync("npm install lucide-static --no-save", { stdio: "inherit" });

const symbols = ICONS.map((name) => {
  const fileSafeName = name.replaceAll("-", "_").replaceAll(/_/g, "-");
  const path = require.resolve(`lucide-static/icons/${name}.svg`);
  let svg = require("node:fs").readFileSync(path, "utf-8");
  // strip outer <svg ...> tags and wrap in <symbol id="lucide-{name}">...
  svg = svg
    .replace(/<svg[^>]*>/, "")
    .replace(/<\/svg>/, "");
  return `<symbol id="lucide-${name}" viewBox="0 0 24 24" stroke="currentColor" fill="none" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${svg}</symbol>`;
}).join("");

const sprite = `<svg xmlns="http://www.w3.org/2000/svg" style="display:none">${symbols}</svg>`;

const outPath = resolve("src/phoresis_ui/static/phoresis_ui/icons/lucide.svg");
mkdirSync(dirname(outPath), { recursive: true });
writeFileSync(outPath, sprite);
console.log(`Wrote ${outPath} (${ICONS.length} icons)`);
```

(The script uses CJS `require` inside ESM via the workaround `require.resolve` — Node 20+ permits this with `--experimental-require-module`. Alternative: convert to all-CJS if the Node version balks.)

Run it:
```bash
node tools/build_lucide_sprite.mjs
```
Expected: `Wrote .../lucide.svg (48 icons)`.

- [ ] **Step 3: Create the 8 custom SVGs**

Each is a 24×24, stroke-1.5, currentColor SVG matching the Lucide aesthetic. The agent draws each by hand — they need to feel coherent with Lucide. Save into `src/phoresis_ui/static/phoresis_ui/icons/custom/`:

- `gel.svg` — three vertical lanes with horizontal bands
- `ladder.svg` — vertical lane with 6 evenly-spaced horizontal bands of decreasing width (top→bottom)
- `blot.svg` — grid of 4 dots (2×2)
- `electrophoresis.svg` — gel rectangle with arrow indicating migration direction (top to bottom)
- `densitometry.svg` — peak curve (smooth normal-distribution shape)
- `lane.svg` — single vertical rectangle with two notches (well + dye front)
- `band.svg` — single horizontal rectangle with rounded corners
- `peak.svg` — single Gaussian peak with baseline

Each file follows this shape:

```html
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
     stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <!-- Path content unique per icon -->
</svg>
```

Concrete examples for the four most-used:

`gel.svg`:
```html
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
     stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <rect x="3" y="3" width="18" height="18" rx="2"/>
  <line x1="9" y1="3" x2="9" y2="21"/>
  <line x1="15" y1="3" x2="15" y2="21"/>
  <line x1="3" y1="8" x2="21" y2="8"/>
  <line x1="3" y1="13" x2="21" y2="13"/>
  <line x1="3" y1="17" x2="21" y2="17"/>
</svg>
```

`ladder.svg`:
```html
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
     stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <rect x="9" y="3" width="6" height="18" rx="1"/>
  <line x1="9" y1="6"  x2="15" y2="6"/>
  <line x1="9" y1="9"  x2="15" y2="9"/>
  <line x1="9" y1="12" x2="15" y2="12"/>
  <line x1="9" y1="15" x2="15" y2="15"/>
  <line x1="9" y1="18" x2="15" y2="18"/>
</svg>
```

`densitometry.svg`:
```html
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
     stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <line x1="3" y1="20" x2="21" y2="20"/>
  <path d="M3 20 Q 8 20 9 14 Q 12 4 15 14 Q 16 20 21 20"/>
</svg>
```

`peak.svg`:
```html
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
     stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <line x1="3" y1="20" x2="21" y2="20"/>
  <path d="M3 20 C 8 20 9 4 12 4 C 15 4 16 20 21 20"/>
</svg>
```

Apply the same hand-drawn approach for `blot.svg`, `electrophoresis.svg`, `lane.svg`, `band.svg`. The exact path geometries are minor — the rule is simple, recognizable, stroke-1.5 lines.

- [ ] **Step 4: Implement `{% icon %}` templatetag**

Replace `src/phoresis_ui/templatetags/ui_icons.py` (currently a stub) with:

```python
"""Icon templatetag — renders Lucide and custom Phoresis icons.

Usage:
    {% load ui_icons %}
    {% icon "home" %}                  # 24x24 default
    {% icon "gel" size=20 %}           # custom size
    {% icon "trash-2" class_="text-danger" %}  # extra classes

The Lucide sprite is loaded once per page (via base.html or first {% icon %}
call). Custom icons are inlined per call (small file, simpler than sprite).
"""
from __future__ import annotations

from pathlib import Path

from django import template
from django.contrib.staticfiles.finders import find
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

LUCIDE_SPRITE_REL = "phoresis_ui/icons/lucide.svg"
CUSTOM_ICON_DIR = Path("phoresis_ui/icons/custom")

# Icons that live in the custom directory (everything else is Lucide).
_CUSTOM_NAMES = frozenset({
    "gel", "ladder", "blot", "electrophoresis",
    "densitometry", "lane", "band", "peak",
})


@register.simple_tag
def icon(name: str, size: int = 24, class_: str = "") -> str:
    """Render a single icon (Lucide or custom)."""
    cls = f"inline-block shrink-0 {class_}".strip()
    style = f"width:{size}px;height:{size}px"

    if name in _CUSTOM_NAMES:
        # Inline the custom SVG (small files, no sprite indirection)
        path = find(str(CUSTOM_ICON_DIR / f"{name}.svg"))
        if not path:
            return format_html('<span class="{}">[{}?]</span>', cls, name)
        svg = Path(path).read_text(encoding="utf-8")
        # Inject our class + style into the root <svg>
        svg = svg.replace(
            "<svg ",
            f'<svg class="{cls}" style="{style}" aria-hidden="true" focusable="false" ',
            1,
        )
        return mark_safe(svg)

    # Lucide: <svg><use href="/static/.../lucide.svg#lucide-NAME" /></svg>
    sprite_url = f"/static/{LUCIDE_SPRITE_REL}#lucide-{name}"
    return format_html(
        '<svg class="{}" style="{}" aria-hidden="true" focusable="false">'
        '<use href="{}"></use></svg>',
        cls, style, sprite_url,
    )


@register.simple_tag
def lucide_sprite() -> str:
    """Inject the Lucide sprite once at the top of <body> for downstream <use> refs.

    Optional optimization — works without it, but a single inline sprite avoids
    cross-origin / caching nuances of the external sprite file.
    """
    path = find(LUCIDE_SPRITE_REL)
    if not path:
        return ""
    return mark_safe(Path(path).read_text(encoding="utf-8"))
```

- [ ] **Step 5: Add icon tests**

Create `src/phoresis_ui/tests/test_components.py`:

```python
"""Tests for phoresis_ui templatetags — icons and components."""
import pytest
from django.template import Context, Template


# --- icons ---

def test_icon_lucide_renders_use_ref() -> None:
    rendered = Template('{% load ui_icons %}{% icon "home" %}').render(Context({}))
    assert "use href" in rendered or "<use " in rendered
    assert "lucide-home" in rendered


def test_icon_custom_inlines_svg() -> None:
    rendered = Template('{% load ui_icons %}{% icon "gel" %}').render(Context({}))
    # Custom icons are inlined → expect path/line elements, not <use>
    assert "<svg" in rendered
    assert "use href" not in rendered


def test_icon_size_param_overrides_default() -> None:
    rendered = Template('{% load ui_icons %}{% icon "home" size=32 %}').render(Context({}))
    assert "32px" in rendered


def test_icon_class_param_added() -> None:
    rendered = Template('{% load ui_icons %}{% icon "home" class_="text-danger" %}').render(Context({}))
    assert "text-danger" in rendered
```

- [ ] **Step 6: Run tests**

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_ui/tests/test_components.py -v
```
Expected: 4 tests pass.

If `test_icon_custom_inlines_svg` fails because the `gel.svg` file isn't where `find()` looks, ensure `STATICFILES_FINDERS` includes `AppDirectoriesFinder` (default in Django 5).

- [ ] **Step 7: Commit**

```bash
git add src/phoresis_ui/static/phoresis_ui/icons/ src/phoresis_ui/templatetags/ui_icons.py src/phoresis_ui/tests/test_components.py tools/build_lucide_sprite.mjs
git commit -m "feat(phoresis_ui): add Lucide sprite + 8 custom SVG icons + {% icon %} templatetag"
```

---

## Task 4: Component templatetags (btn, card, badge, modal, confirm, toast, kpi, empty_state, skeleton)

**Files:**
- Modify: `src/phoresis_ui/templatetags/ui_components.py` (replace stub with real implementations)
- Modify: `src/phoresis_ui/tests/test_components.py` (add tests for each component)

The pattern: each templatetag is `inclusion_tag` rendering a small `partials/_<name>.html` template. We keep the partials inline as `template.Template(...)` rendered strings to avoid 9 separate template files.

- [ ] **Step 1: Replace `ui_components.py`**

```python
"""Phoresis UI component templatetags.

Each tag is a small `inclusion_tag`-style helper that renders a focused
HTML fragment with semantic Tailwind utilities. All variants resolve through
the design tokens in `tokens.css`, so dark mode flips automatically via
`<html data-theme="dark">`.

Conventions:
- Sizes: sm (h-8), md (h-10, default), lg (h-12).
- Variants: primary, secondary, ghost, danger.
- The Alpine.js `toast` and `modal` stores (Task 5) handle dynamic state.
"""
from __future__ import annotations

from django import template
from django.template.loader import render_to_string
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


# ============================================================================
# Buttons
# ============================================================================

_BTN_VARIANTS = {
    "primary": "bg-accent-600 text-white hover:bg-accent-700 active:bg-accent-700 focus-visible:outline-accent-500",
    "secondary": "bg-surface text-text border border-border hover:bg-surface-elevated",
    "ghost": "bg-transparent text-text hover:bg-surface-elevated",
    "danger": "bg-danger text-white hover:opacity-90",
}
_BTN_SIZES = {
    "sm": "h-8 px-3 text-sm",
    "md": "h-10 px-4 text-sm",
    "lg": "h-12 px-6 text-base",
}


@register.simple_tag
def btn(label, *, variant="primary", size="md", icon=None, type_="button",
        href=None, hx_post=None, hx_target=None, class_="", disabled=False, loading=False):
    """Render a button or anchor styled as a button.

    Examples::
        {% btn "Save" variant="primary" %}
        {% btn "Cancel" variant="ghost" %}
        {% btn "Delete" variant="danger" icon="trash-2" %}
        {% btn "Open" href="/something/" variant="secondary" %}
    """
    base = "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50 disabled:pointer-events-none"
    cls = f"{base} {_BTN_VARIANTS[variant]} {_BTN_SIZES[size]} {class_}".strip()

    icon_html = ""
    if icon:
        icon_html = f'<span data-ui-icon="{icon}"></span>'

    spinner = ""
    if loading:
        spinner = '<span class="animate-spin" data-ui-icon="loader"></span>'
        cls += " pointer-events-none"

    inner = f"{spinner}{icon_html}<span>{label}</span>"

    htmx_attrs = ""
    if hx_post:
        htmx_attrs += f' hx-post="{hx_post}"'
    if hx_target:
        htmx_attrs += f' hx-target="{hx_target}"'

    if href:
        return mark_safe(f'<a href="{href}" class="{cls}"{htmx_attrs}>{inner}</a>')

    disabled_attr = " disabled" if disabled else ""
    return mark_safe(f'<button type="{type_}" class="{cls}"{htmx_attrs}{disabled_attr}>{inner}</button>')


# ============================================================================
# Cards
# ============================================================================

@register.inclusion_tag("components/_card.html")
def card(title=None, subtitle=None, hover=True, class_=""):
    """Render a card wrapper. Use as a block tag via `{% card title="..." %}...{% endcard %}` won't work
    with simple_tag; instead, use `{% card title="..." %}` for header-only card or pair with raw HTML."""
    return {"title": title, "subtitle": subtitle, "hover": hover, "class_": class_}


# Card body block — Django templates don't have block-form simple_tag, so we provide
# raw fragments via two helpers:

@register.simple_tag
def card_open(class_="", hover=True):
    hover_cls = "transition-transform duration-150 hover:-translate-y-[2px] hover:shadow-lg" if hover else ""
    return mark_safe(
        f'<div class="rounded-lg border border-border bg-surface p-6 shadow-sm {hover_cls} {class_}">'
    )


@register.simple_tag
def card_close():
    return mark_safe("</div>")


# ============================================================================
# Badges
# ============================================================================

_BADGE_VARIANTS = {
    "default": "bg-surface-elevated text-text border border-border",
    "primary": "bg-accent-50 text-accent-700",
    "success": "bg-emerald-50 text-emerald-700",
    "warning": "bg-amber-50 text-amber-700",
    "danger": "bg-red-50 text-red-700",
    "info": "bg-cyan-50 text-cyan-700",
    "muted": "bg-zinc-100 text-zinc-700",
    "band": "text-white",  # uses --color-band as bg via inline style
}


@register.simple_tag
def badge(label, *, variant="default", class_=""):
    """Render a small status pill.

    {% badge "DRAFT" variant="warning" %}
    {% badge "SAMPLE" variant="primary" %}
    {% badge "Band" variant="band" %}
    """
    cls = f"inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium {_BADGE_VARIANTS[variant]} {class_}".strip()
    style = ' style="background-color: var(--color-band);"' if variant == "band" else ""
    return mark_safe(f'<span class="{cls}"{style}>{label}</span>')


# ============================================================================
# Empty state
# ============================================================================

@register.inclusion_tag("components/_empty_state.html")
def empty_state(title, *, message="", icon="image", cta_label=None, cta_href=None, cta_variant="primary"):
    """Render an empty-state block — illustration + message + optional CTA."""
    return {
        "title": title,
        "message": message,
        "icon": icon,
        "cta_label": cta_label,
        "cta_href": cta_href,
        "cta_variant": cta_variant,
    }


# ============================================================================
# Skeleton (loader)
# ============================================================================

@register.simple_tag
def skeleton(*, height="1rem", width="100%", class_=""):
    """Render a shimmer placeholder."""
    cls = f"ui-shimmer rounded-md {class_}".strip()
    return mark_safe(f'<div class="{cls}" style="width:{width};height:{height};"></div>')


# ============================================================================
# Modal (chrome only — body content provided as block in a separate template)
# ============================================================================

@register.inclusion_tag("components/_modal_chrome.html")
def modal_chrome(*, id_, title, size="md"):
    """Render the Alpine-bound modal scaffold. Body goes in the surrounding template."""
    sizes = {"sm": "max-w-md", "md": "max-w-2xl", "lg": "max-w-4xl"}
    return {"id_": id_, "title": title, "size_class": sizes.get(size, sizes["md"])}


# ============================================================================
# Confirm modal — convenience wrapper
# ============================================================================

@register.inclusion_tag("components/_confirm_modal.html")
def confirm(*, id_, title, message, confirm_label="Confirm", confirm_variant="danger",
            cancel_label="Cancel", hx_post=None):
    return {
        "id_": id_,
        "title": title,
        "message": message,
        "confirm_label": confirm_label,
        "confirm_variant": confirm_variant,
        "cancel_label": cancel_label,
        "hx_post": hx_post,
    }


# ============================================================================
# Toast container — mounts the Alpine `toast` store output
# ============================================================================

@register.inclusion_tag("components/_toast.html")
def toast_container():
    return {}


# ============================================================================
# KPI card (used on dashboard + image list)
# ============================================================================

@register.inclusion_tag("components/_kpi.html")
def kpi(label, value, *, trend=None, trend_label="", icon=None, accent="accent"):
    """Render a single KPI card. `value` should already be the numeric value (CountUp.js animates).

    {% kpi "Total gels" total trend=5 trend_label="vs last week" icon="image" %}
    """
    accents = {
        "accent": "text-accent-600",
        "success": "text-success",
        "warning": "text-warning",
        "danger": "text-danger",
        "info": "text-info",
        "band": "text-band",
    }
    return {
        "label": label,
        "value": value,
        "trend": trend,
        "trend_label": trend_label,
        "icon": icon,
        "accent_class": accents.get(accent, accents["accent"]),
    }
```

- [ ] **Step 2: Create the component partials**

Create the following templates under `src/phoresis_ui/templates/components/`:

`_card.html`:
```django
{% load ui_icons %}
<div class="rounded-lg border border-border bg-surface p-6 shadow-sm transition-transform duration-150 {% if hover %}hover:-translate-y-[2px] hover:shadow-lg{% endif %} {{ class_ }}">
    {% if title %}
        <header class="mb-4">
            <h3 class="text-lg font-semibold">{{ title }}</h3>
            {% if subtitle %}<p class="text-sm text-text-muted">{{ subtitle }}</p>{% endif %}
        </header>
    {% endif %}
</div>
```

`_empty_state.html`:
```django
{% load ui_components ui_icons %}
<div class="flex flex-col items-center justify-center py-16 text-center">
    <div class="mb-4 grid h-16 w-16 place-items-center rounded-full bg-surface-elevated text-text-muted">
        {% icon icon size=32 %}
    </div>
    <h3 class="mb-2 text-lg font-semibold">{{ title }}</h3>
    {% if message %}<p class="mb-6 max-w-md text-sm text-text-muted">{{ message }}</p>{% endif %}
    {% if cta_label %}{% btn cta_label href=cta_href variant=cta_variant %}{% endif %}
</div>
```

`_modal_chrome.html`:
```django
<div x-show="$store.modal.open === '{{ id_ }}'"
     x-cloak
     x-transition.opacity
     class="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4 backdrop-blur"
     @click.self="$store.modal.close()"
     @keydown.escape.window="$store.modal.close()">
    <div x-show="$store.modal.open === '{{ id_ }}'"
         x-transition:enter="transition duration-200 ease-out"
         x-transition:enter-start="opacity-0 scale-95"
         x-transition:enter-end="opacity-100 scale-100"
         class="w-full {{ size_class }} rounded-xl bg-surface shadow-lg">
        <header class="flex items-center justify-between border-b border-border p-6">
            <h2 class="text-lg font-semibold">{{ title }}</h2>
            <button class="text-text-muted hover:text-text" @click="$store.modal.close()" aria-label="Close">
                {% load ui_icons %}{% icon "x" %}
            </button>
        </header>
        <div class="p-6" data-modal-body></div>
    </div>
</div>
```

`_confirm_modal.html`:
```django
{% load ui_components %}
<div x-show="$store.modal.open === '{{ id_ }}'"
     x-cloak
     x-transition.opacity
     class="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4 backdrop-blur"
     @click.self="$store.modal.close()"
     @keydown.escape.window="$store.modal.close()">
    <div x-show="$store.modal.open === '{{ id_ }}'"
         x-transition:enter="transition duration-200 ease-out"
         x-transition:enter-start="opacity-0 scale-95"
         x-transition:enter-end="opacity-100 scale-100"
         class="w-full max-w-md rounded-xl bg-surface p-6 shadow-lg">
        <h2 class="mb-2 text-lg font-semibold">{{ title }}</h2>
        <p class="mb-6 text-sm text-text-muted">{{ message }}</p>
        <div class="flex justify-end gap-2">
            {% btn cancel_label variant="secondary" class_="x-on-click=\"$store.modal.close()\"" %}
            {% btn confirm_label variant=confirm_variant hx_post=hx_post %}
        </div>
    </div>
</div>
```

`_toast.html`:
```django
<div x-data
     class="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2"
     aria-live="polite"
     aria-atomic="true">
    <template x-for="t in $store.toast.items" :key="t.id">
        <div class="pointer-events-auto flex items-start gap-3 rounded-lg bg-surface-elevated p-4 shadow-lg ring-1 ring-border min-w-[280px] max-w-md"
             :class="{
                'ring-success/30': t.variant === 'success',
                'ring-danger/30':  t.variant === 'danger',
                'ring-warning/30': t.variant === 'warning',
             }"
             x-transition:enter="transition duration-200"
             x-transition:enter-start="opacity-0 translate-x-4"
             x-transition:enter-end="opacity-100 translate-x-0">
            <div class="grow">
                <p class="text-sm font-medium" x-text="t.title"></p>
                <p class="mt-0.5 text-xs text-text-muted" x-show="t.message" x-text="t.message"></p>
            </div>
            <button class="text-text-muted hover:text-text" @click="$store.toast.dismiss(t.id)">
                {% load ui_icons %}{% icon "x" size=16 %}
            </button>
        </div>
    </template>
</div>
```

`_kpi.html`:
```django
{% load ui_icons %}
<div class="rounded-lg border border-border bg-surface p-6 shadow-sm transition-transform duration-150 hover:-translate-y-[2px]">
    <div class="flex items-start justify-between">
        <p class="text-sm font-medium text-text-muted">{{ label }}</p>
        {% if icon %}<span class="{{ accent_class }}">{% icon icon size=20 %}</span>{% endif %}
    </div>
    <p class="mt-2 text-3xl font-semibold tracking-tight"
       data-countup="{{ value }}"
       data-countup-duration="800">{{ value }}</p>
    {% if trend is not None %}
        <p class="mt-2 text-xs">
            <span class="font-medium {% if trend >= 0 %}text-success{% else %}text-danger{% endif %}">
                {% if trend >= 0 %}+{% endif %}{{ trend }}%
            </span>
            <span class="text-text-muted">{{ trend_label }}</span>
        </p>
    {% endif %}
</div>
```

- [ ] **Step 3: Add component tests**

Append to `src/phoresis_ui/tests/test_components.py`:

```python
# --- components ---

def test_btn_renders_button_element() -> None:
    rendered = Template('{% load ui_components %}{% btn "Save" %}').render(Context({}))
    assert "<button" in rendered and "Save" in rendered
    assert "bg-accent-600" in rendered  # primary variant


def test_btn_with_href_renders_anchor() -> None:
    rendered = Template('{% load ui_components %}{% btn "Open" href="/x/" %}').render(Context({}))
    assert '<a href="/x/"' in rendered


def test_btn_loading_includes_spinner() -> None:
    rendered = Template('{% load ui_components %}{% btn "Save" loading=True %}').render(Context({}))
    assert "animate-spin" in rendered


def test_badge_variants() -> None:
    for variant, expected in [("primary", "text-accent-700"), ("danger", "text-red-700")]:
        rendered = Template(f'{{% load ui_components %}}{{% badge "TEST" variant="{variant}" %}}').render(Context({}))
        assert expected in rendered


def test_skeleton_includes_shimmer_class() -> None:
    rendered = Template('{% load ui_components %}{% skeleton %}').render(Context({}))
    assert "ui-shimmer" in rendered


def test_empty_state_renders_title_and_message() -> None:
    rendered = Template(
        '{% load ui_components %}{% empty_state "No gels" message="Upload one." %}'
    ).render(Context({}))
    assert "No gels" in rendered
    assert "Upload one." in rendered


def test_kpi_renders_value_with_countup_attr() -> None:
    rendered = Template(
        '{% load ui_components %}{% kpi "Total" 42 icon="image" %}'
    ).render(Context({}))
    assert "Total" in rendered
    assert 'data-countup="42"' in rendered


def test_modal_chrome_renders_close_button() -> None:
    rendered = Template(
        '{% load ui_components %}{% modal_chrome id_="m1" title="Edit" %}'
    ).render(Context({}))
    assert 'x-show="$store.modal.open === \'m1\'"' in rendered
    assert "Edit" in rendered


def test_confirm_renders_buttons() -> None:
    rendered = Template(
        '{% load ui_components %}{% confirm id_="c1" title="Delete?" message="Are you sure?" %}'
    ).render(Context({}))
    assert "Delete?" in rendered
    assert "Are you sure?" in rendered
    assert "Cancel" in rendered  # default cancel_label
```

- [ ] **Step 4: Run tests**

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_ui/tests/ -v
```
Expected: all component tests pass (~12 in this task + 4 from Task 3 + 3 from Phase 1 = 19).

If a test fails because the partial template can't be found, ensure the templates were saved under `src/phoresis_ui/templates/components/` and that `phoresis_ui` has `APP_DIRS=True` in `TEMPLATES`.

- [ ] **Step 5: Rebuild CSS to include the new utility classes**

```bash
npm run build:css
```
Expected: `output.css` regenerates without errors.

- [ ] **Step 6: Commit**

```bash
git add src/phoresis_ui/templatetags/ui_components.py src/phoresis_ui/templates/components/_card.html src/phoresis_ui/templates/components/_empty_state.html src/phoresis_ui/templates/components/_modal_chrome.html src/phoresis_ui/templates/components/_confirm_modal.html src/phoresis_ui/templates/components/_toast.html src/phoresis_ui/templates/components/_kpi.html src/phoresis_ui/tests/test_components.py
git commit -m "feat(phoresis_ui): add 9 component templatetags (btn, card, badge, modal, confirm, toast, kpi, empty_state, skeleton)"
```

---

## Task 5: Alpine stores + HTMX config + animations.js

**Files:**
- Create: `src/phoresis_ui/static/phoresis_ui/js/htmx-config.js`
- Create: `src/phoresis_ui/static/phoresis_ui/js/alpine-init.js`
- Create: `src/phoresis_ui/static/phoresis_ui/js/animations.js`

- [ ] **Step 1: Create `htmx-config.js`**

```javascript
/* HTMX 2 wiring — CSRF, indicators, auto-toast on response status. */
(function () {
  if (typeof window.htmx === "undefined") {
    document.addEventListener("htmx:load", configure, { once: true });
  } else {
    configure();
  }

  function configure() {
    // CSRF — Django needs the token on every unsafe request
    htmx.on("htmx:configRequest", (e) => {
      const token = document.querySelector("[name=csrfmiddlewaretoken]")?.value
        || readCookie("csrftoken");
      if (token) {
        e.detail.headers["X-CSRFToken"] = token;
      }
    });

    // Auto-toast on 4xx/5xx
    htmx.on("htmx:responseError", (e) => {
      if (window.Alpine && Alpine.store("toast")) {
        Alpine.store("toast").push({
          variant: "danger",
          title: `Request failed (${e.detail.xhr.status})`,
          message: e.detail.xhr.statusText,
        });
      }
    });

    // Auto-toast on the X-Toast-* response headers (server can push toasts)
    htmx.on("htmx:afterRequest", (e) => {
      const xhr = e.detail.xhr;
      const variant = xhr.getResponseHeader("X-Toast-Variant");
      const title = xhr.getResponseHeader("X-Toast-Title");
      const message = xhr.getResponseHeader("X-Toast-Message");
      if (title && window.Alpine?.store("toast")) {
        Alpine.store("toast").push({ variant: variant || "info", title, message });
      }
    });
  }

  function readCookie(name) {
    return document.cookie
      .split("; ")
      .find((c) => c.startsWith(name + "="))
      ?.split("=")[1];
  }
})();
```

- [ ] **Step 2: Create `alpine-init.js`**

```javascript
/* Alpine.js 3 stores — theme, toast, modal, palette. */
document.addEventListener("alpine:init", () => {
  // ---- theme ----
  Alpine.store("theme", {
    user: localStorage.getItem("phoresis_theme") || "auto",  // 'auto' | 'light' | 'dark'

    init() {
      this.apply();
      // Re-apply when system pref flips while on 'auto'
      matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
        if (this.user === "auto") this.apply();
      });
    },

    set(value) {
      this.user = value;
      localStorage.setItem("phoresis_theme", value);
      this.apply();
    },

    apply() {
      const resolved = this.user === "auto"
        ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
        : this.user;
      document.documentElement.setAttribute("data-theme", resolved);
      document.documentElement.dataset.userTheme = this.user;
      // Notify chart code to re-render with the new palette
      window.dispatchEvent(new CustomEvent("phoresis:theme-changed", { detail: { theme: resolved } }));
    },
  });

  // ---- toast ----
  Alpine.store("toast", {
    items: [],
    counter: 0,

    push({ variant = "info", title, message = "", duration = 5000 }) {
      const id = ++this.counter;
      this.items.push({ id, variant, title, message });
      if (duration > 0) setTimeout(() => this.dismiss(id), duration);
    },

    dismiss(id) {
      this.items = this.items.filter((t) => t.id !== id);
    },
  });

  // ---- modal ----
  Alpine.store("modal", {
    open: null,  // ID of the currently-open modal, or null

    show(id) { this.open = id; },
    close()  { this.open = null; },
    toggle(id) { this.open = this.open === id ? null : id; },
  });

  // ---- command palette ----
  Alpine.store("palette", {
    open: false,
    query: "",
    items: [],     // populated by topbar with nav_registry.get_flat_items()

    show()  { this.open = true; },
    hide()  { this.open = false; this.query = ""; },
    toggle() { this.open ? this.hide() : this.show(); },
  });
});

// Ctrl+K / Cmd+K opens the palette
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "k") {
    e.preventDefault();
    if (window.Alpine?.store("palette")) Alpine.store("palette").toggle();
  }
});
```

- [ ] **Step 3: Create `animations.js`**

```javascript
/* Animation helpers — view-transition wrapper + CountUp.js init for KPIs. */
(function () {
  // CountUp.js — load lazily on demand
  let CountUpModule = null;

  async function ensureCountUp() {
    if (CountUpModule) return CountUpModule;
    const m = await import("https://unpkg.com/countup.js@2.8.0/dist/countUp.min.js");
    CountUpModule = m.CountUp || window.CountUp;
    return CountUpModule;
  }

  async function initCountUps(root = document) {
    const targets = root.querySelectorAll("[data-countup]");
    if (!targets.length) return;
    const Up = await ensureCountUp();
    targets.forEach((el) => {
      const value = parseFloat(el.dataset.countup);
      const duration = parseInt(el.dataset.countupDuration || "800", 10) / 1000;
      if (!Number.isFinite(value)) return;
      const u = new Up(el, value, { duration, useEasing: true });
      if (!u.error) u.start();
      el.removeAttribute("data-countup");
    });
  }

  // Run on initial load + whenever HTMX swaps content
  document.addEventListener("DOMContentLoaded", () => initCountUps());
  document.addEventListener("htmx:afterSwap", (e) => initCountUps(e.detail.elt));

  // View-transition wrapper for HTMX page swaps (Chrome / Edge)
  if (typeof document.startViewTransition === "function") {
    document.addEventListener("htmx:beforeSwap", (e) => {
      if (e.detail.swapStyle === "outerHTML" || e.target === document.body) {
        document.startViewTransition(() => {
          // HTMX completes the swap synchronously inside this callback
        });
      }
    });
  }
})();
```

- [ ] **Step 4: Verify the JS files load without errors**

Restart `runserver` (Phase 1's command) and open `http://127.0.0.1:8000/admin/login/` in the browser — the network tab should show `htmx-config.js`, `alpine-init.js`, `animations.js` all loaded with status 200. The console should be silent.

```bash
.venv/Scripts/python.exe manage.py runserver 0.0.0.0:8000
```
(In another terminal:)
```bash
curl -s http://127.0.0.1:8000/static/phoresis_ui/js/alpine-init.js | head -5
```
Expected: the file's first lines.

- [ ] **Step 5: Commit**

```bash
git add src/phoresis_ui/static/phoresis_ui/js/
git commit -m "feat(phoresis_ui): add Alpine stores (theme/toast/modal/palette) + HTMX config + animations"
```

---

## Task 6: Layout shell — sidebar, topbar, _layout.html

**Files:**
- Create: `src/phoresis_ui/templates/components/_layout.html`
- Create: `src/phoresis_ui/templates/components/_sidebar.html`
- Create: `src/phoresis_ui/templates/components/_topbar.html`

The layout is a 72-px collapsed icon-rail sidebar that expands to 240 px on hover, plus a 60-px topbar with global search, theme toggle, and avatar menu. `base.html` (from Task 2) wraps `{% block body %}{% block content %}{% endblock %}{% endblock %}` — pages opt in to the chrome by setting `{% block body %}{% include 'components/_layout.html' %}{% endblock %}` (or extending an intermediate `app_base.html` — see Task 10).

- [ ] **Step 1: Create `_layout.html`**

```django
{% load ui_icons %}
<div class="flex min-h-screen bg-bg">
    {% include 'components/_sidebar.html' %}

    <div class="flex flex-1 flex-col">
        {% include 'components/_topbar.html' %}

        <main class="flex-1 px-6 py-6 md:px-8 md:py-8" id="main-content">
            {% block content %}{% endblock %}
        </main>
    </div>

    {% include 'components/_command_palette.html' %}
    {% load ui_components %}
    {% toast_container %}
</div>
```

- [ ] **Step 2: Create `_sidebar.html`**

```django
{% load ui_icons %}
<aside x-data="{ pinned: localStorage.getItem('phoresis_sidebar_pinned') === '1' }"
       :class="pinned ? 'w-60' : 'w-[72px] hover:w-60'"
       class="group sticky top-0 h-screen overflow-hidden border-r border-border bg-surface transition-[width] duration-200 ease-out">
    <div class="flex h-15 items-center px-4">
        <a href="{% url 'dashboard:home' %}" class="flex items-center gap-2 text-text">
            {% icon "flask-conical" size=24 class_="text-accent-600" %}
            <span class="origin-left whitespace-nowrap font-semibold text-base transition-opacity"
                  :class="pinned ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'">
                Phoresis
            </span>
        </a>
    </div>

    <nav class="px-2 py-2 space-y-1">
        <a href="{% url 'dashboard:home' %}"
           class="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-text-muted hover:bg-surface-elevated hover:text-text transition-colors {% if request.resolver_match.namespace == 'dashboard' %}bg-accent-50 text-accent-700 font-medium{% endif %}">
            {% icon "layout-dashboard" %}
            <span class="whitespace-nowrap" :class="pinned ? '' : 'hidden group-hover:inline'">Dashboard</span>
        </a>
        <a href="{% url 'gel_analyzer:image_list' %}"
           class="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-text-muted hover:bg-surface-elevated hover:text-text transition-colors {% if request.resolver_match.url_name == 'image_list' %}bg-accent-50 text-accent-700 font-medium{% endif %}">
            {% icon "image" %}
            <span class="whitespace-nowrap" :class="pinned ? '' : 'hidden group-hover:inline'">Gel Images</span>
        </a>
        <a href="{% url 'gel_analyzer:analysis_list' %}"
           class="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-text-muted hover:bg-surface-elevated hover:text-text transition-colors {% if request.resolver_match.url_name == 'analysis_list' %}bg-accent-50 text-accent-700 font-medium{% endif %}">
            {% icon "layers" %}
            <span class="whitespace-nowrap" :class="pinned ? '' : 'hidden group-hover:inline'">Analyses</span>
        </a>
    </nav>

    <button class="absolute bottom-4 right-3 rounded-md p-1 text-text-muted hover:bg-surface-elevated"
            @click="pinned = !pinned; localStorage.setItem('phoresis_sidebar_pinned', pinned ? '1' : '0')"
            :title="pinned ? 'Unpin sidebar' : 'Pin sidebar'">
        {% icon "chevron-left" %}
    </button>
</aside>
```

- [ ] **Step 3: Create `_topbar.html`**

```django
{% load ui_icons ui_components %}
<header class="sticky top-0 z-10 flex h-15 items-center gap-4 border-b border-border bg-surface px-6">
    <button @click="$store.palette.show()"
            class="flex items-center gap-2 rounded-md border border-border bg-surface-elevated px-3 py-1.5 text-sm text-text-muted hover:text-text">
        {% icon "search" size=16 %}
        <span>Search…</span>
        <kbd class="ml-3 rounded border border-border bg-bg px-1.5 py-0.5 text-xs">Ctrl K</kbd>
    </button>

    <div class="ml-auto flex items-center gap-2">
        <!-- Theme toggle -->
        <div class="flex rounded-md border border-border bg-surface-elevated p-0.5"
             x-data
             :data-user-theme="$store.theme.user">
            <button class="rounded p-1.5 hover:bg-surface" :class="$store.theme.user === 'light' && 'bg-surface'" @click="$store.theme.set('light')" aria-label="Light mode">
                {% icon "sun" size=16 %}
            </button>
            <button class="rounded p-1.5 hover:bg-surface" :class="$store.theme.user === 'auto'  && 'bg-surface'" @click="$store.theme.set('auto')"  aria-label="Auto">
                {% icon "monitor" size=16 %}
            </button>
            <button class="rounded p-1.5 hover:bg-surface" :class="$store.theme.user === 'dark'  && 'bg-surface'" @click="$store.theme.set('dark')"  aria-label="Dark mode">
                {% icon "moon" size=16 %}
            </button>
        </div>

        {% if request.user.is_authenticated %}
        <div x-data="{ open: false }" class="relative">
            <button @click="open = !open" class="flex items-center gap-2 rounded-md p-1.5 hover:bg-surface-elevated">
                {% if request.user.profile.avatar %}
                    <img src="{{ request.user.profile.avatar.url }}" alt="" class="h-7 w-7 rounded-full">
                {% else %}
                    <span class="grid h-7 w-7 place-items-center rounded-full bg-accent-50 text-xs font-semibold text-accent-700">
                        {{ request.user.username|first|upper }}
                    </span>
                {% endif %}
                <span class="text-sm">{{ request.user }}</span>
                {% icon "chevron-down" size=14 %}
            </button>
            <div x-show="open" @click.outside="open = false" x-transition class="absolute right-0 mt-1 w-48 rounded-md border border-border bg-surface shadow-lg" x-cloak>
                <a href="{% url 'accounts:profile' %}" class="flex items-center gap-2 px-3 py-2 text-sm hover:bg-surface-elevated">
                    {% icon "user" size=14 %} Profile
                </a>
                <form method="post" action="{% url 'accounts:logout' %}" class="border-t border-border">
                    {% csrf_token %}
                    <button type="submit" class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-elevated">
                        {% icon "log-out" size=14 %} Sign out
                    </button>
                </form>
            </div>
        </div>
        {% endif %}
    </div>
</header>
```

- [ ] **Step 4: Add a layout integration test**

Create `src/phoresis_ui/tests/test_layout.py`:
```python
"""Tests for the layout chrome (sidebar/topbar)."""
import pytest
from django.template import Context, RequestContext, Template
from django.test import RequestFactory


@pytest.fixture
def authenticated_request(db, django_user_model):
    user = django_user_model.objects.create_user(username="layout", password="x")
    rf = RequestFactory()
    req = rf.get("/")
    req.user = user
    req.resolver_match = type("RM", (), {"namespace": "dashboard", "url_name": "home"})()
    return req


@pytest.mark.django_db
def test_layout_renders_sidebar_brand(authenticated_request) -> None:
    template = Template(
        "{% extends 'components/base.html' %}"
        "{% block body %}{% include 'components/_layout.html' %}{% endblock %}"
        "{% block content %}HELLO{% endblock %}"
    )
    rendered = template.render(RequestContext(authenticated_request))
    assert "Phoresis" in rendered
    assert "HELLO" in rendered
    assert 'aria-label="Light mode"' in rendered  # theme toggle present
```

(The test references `dashboard:home`, `accounts:profile`, etc., which already exist in Phase 1. It does NOT reference `gel_analyzer:image_list` yet because Task 14 wires those URLs — `test_layout` will be re-run after Task 14 to confirm the sidebar links resolve.)

- [ ] **Step 5: Run the test**

```bash
.venv/Scripts/python.exe -m pytest src/phoresis_ui/tests/test_layout.py -v
```

Expected: 1 test passes. If `gel_analyzer:image_list` reverse fails before Task 14, comment out or stub those `<a href="{% url ... %}">` lines temporarily and uncomment them as Task 14's final wiring step. (Cleaner: pass `--ignore-glob='**/test_layout.py'` until Task 14, then re-include.)

- [ ] **Step 6: Commit**

```bash
git add src/phoresis_ui/templates/components/_layout.html src/phoresis_ui/templates/components/_sidebar.html src/phoresis_ui/templates/components/_topbar.html src/phoresis_ui/tests/test_layout.py
git commit -m "feat(phoresis_ui): add layout shell (sidebar, topbar, _layout)"
```

---

## Task 7: Command palette modal

**Files:**
- Create: `src/phoresis_ui/templates/components/_command_palette.html`
- Modify: `src/phoresis_ui/templates/components/_layout.html` (already includes it from Task 6)
- Modify: `_topbar.html` to inject `nav_registry.get_flat_items()` JSON into `$store.palette.items`

- [ ] **Step 1: Create `_command_palette.html`**

```django
{% load ui_icons %}
<div x-show="$store.palette.open"
     x-cloak
     x-transition.opacity
     class="fixed inset-0 z-50 grid place-items-start bg-black/40 p-4 pt-[10vh] backdrop-blur"
     @click.self="$store.palette.hide()"
     @keydown.escape.window="$store.palette.hide()">
    <div x-show="$store.palette.open"
         x-transition:enter="transition duration-200 ease-out"
         x-transition:enter-start="opacity-0 -translate-y-2"
         x-transition:enter-end="opacity-100 translate-y-0"
         class="w-full max-w-xl rounded-xl bg-surface shadow-xl ring-1 ring-border">
        <div class="flex items-center gap-3 border-b border-border px-4 py-3">
            {% icon "search" size=18 class_="text-text-muted" %}
            <input x-model="$store.palette.query"
                   x-ref="paletteInput"
                   x-init="$watch('$store.palette.open', v => v && $nextTick(() => $refs.paletteInput.focus()))"
                   class="w-full border-0 bg-transparent p-0 text-sm focus:outline-none focus:ring-0"
                   placeholder="Search pages and actions…">
            <kbd class="rounded border border-border bg-bg px-1.5 py-0.5 text-xs text-text-muted">ESC</kbd>
        </div>
        <ul class="max-h-[60vh] divide-y divide-border overflow-y-auto p-2">
            <template x-for="item in $store.palette.items.filter(it => $store.palette.query === '' || it.name.toLowerCase().includes($store.palette.query.toLowerCase()))" :key="item.url">
                <li>
                    <a :href="item.url"
                       @click="$store.palette.hide()"
                       class="flex items-center gap-3 rounded-md px-3 py-2 text-sm hover:bg-surface-elevated">
                        <span class="text-text-muted text-xs uppercase tracking-wide" x-text="item.type"></span>
                        <span x-text="item.name"></span>
                    </a>
                </li>
            </template>
            <li x-show="$store.palette.items.filter(it => $store.palette.query === '' || it.name.toLowerCase().includes($store.palette.query.toLowerCase())).length === 0"
                class="px-3 py-6 text-center text-sm text-text-muted">
                No results.
            </li>
        </ul>
    </div>
</div>
```

- [ ] **Step 2: Inject `nav_registry` items into `$store.palette.items`**

Add to `src/phoresis_ui/templatetags/ui_components.py`:

```python
import json as _json


@register.simple_tag
def nav_palette_items_json() -> str:
    """Serialize `nav_registry.get_flat_items()` for client-side consumption."""
    from django.urls import reverse, NoReverseMatch
    from phoresis_core.navigation import nav_registry

    items = []
    for item in nav_registry.get_flat_items():
        url = item["url"]
        # Resolve URL name → path if it looks like a name
        if url and ":" in url and "/" not in url:
            try:
                url = reverse(url)
            except NoReverseMatch:
                continue  # URL not yet wired — skip silently
        items.append({"name": item["name"], "url": url, "type": item["type"], "icon": item.get("icon")})
    return mark_safe(_json.dumps(items))
```

Then in `src/phoresis_ui/templates/components/_topbar.html`, near the `<header>` tag, add:

```django
{% load ui_components %}
<script>
  document.addEventListener("alpine:init", () => {
    Alpine.store("palette").items = {% nav_palette_items_json %};
  });
</script>
```

- [ ] **Step 3: Build CSS**

```bash
npm run build:css
```

- [ ] **Step 4: Add a smoke test**

Append to `src/phoresis_ui/tests/test_components.py`:

```python
def test_nav_palette_items_json_serializes_dashboard() -> None:
    """The dashboard nav.py registers its app in Phase 1 — palette JSON should include it."""
    rendered = Template('{% load ui_components %}{% nav_palette_items_json %}').render(Context({}))
    assert "Dashboard" in rendered
    assert "Home" in rendered
```

Run:
```bash
.venv/Scripts/python.exe -m pytest src/phoresis_ui/tests/test_components.py::test_nav_palette_items_json_serializes_dashboard -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/phoresis_ui/templates/components/_command_palette.html src/phoresis_ui/templates/components/_topbar.html src/phoresis_ui/templatetags/ui_components.py src/phoresis_ui/tests/test_components.py
git commit -m "feat(phoresis_ui): add Ctrl+K command palette wired to nav_registry"
```

---

## Task 8: Theme switcher persistence (UserProfile.theme)

**Files:**
- Modify: `src/accounts/views.py` (add HTMX endpoint to persist theme)
- Modify: `src/accounts/urls.py` (route the endpoint)
- Modify: `src/phoresis_ui/static/phoresis_ui/js/alpine-init.js` (POST on theme.set)

The user-side persistence already lives in `localStorage` (Task 5). This task layers in server-side persistence so a logged-in user's theme syncs across devices and survives clearing browser data.

- [ ] **Step 1: Add the `theme_set` view**

In `src/accounts/views.py`, append:

```python
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST


@require_POST
@login_required
def theme_set_view(request: HttpRequest) -> HttpResponse:
    """Persist the user's theme preference (auto / light / dark)."""
    value = request.POST.get("theme", "").strip()
    if value not in ("auto", "light", "dark"):
        return HttpResponseBadRequest("invalid theme")
    profile = request.user.profile
    profile.theme = value
    profile.save(update_fields=["theme", "updated_at"])
    return HttpResponse(status=204)
```

- [ ] **Step 2: Add the URL**

In `src/accounts/urls.py`, append `path("theme/", views.theme_set_view, name="theme_set"),` to `urlpatterns`.

- [ ] **Step 3: Update Alpine `theme` store to POST on change**

Edit `src/phoresis_ui/static/phoresis_ui/js/alpine-init.js`. In the `theme` store, modify `set` to also POST:

```javascript
    set(value) {
      this.user = value;
      localStorage.setItem("phoresis_theme", value);
      this.apply();

      // Persist to server (best-effort; localStorage is the canonical client store)
      const csrf = document.querySelector("[name=csrfmiddlewaretoken]")?.value
        || document.cookie.split("; ").find(c => c.startsWith("csrftoken="))?.split("=")[1];
      if (csrf && document.body.dataset.user !== "anonymous") {
        fetch("/accounts/theme/", {
          method: "POST",
          headers: { "X-CSRFToken": csrf, "Content-Type": "application/x-www-form-urlencoded" },
          body: `theme=${encodeURIComponent(value)}`,
          credentials: "same-origin",
        }).catch(() => { /* silent — localStorage is the source of truth */ });
      }
    },
```

- [ ] **Step 4: Annotate `<body>` so client-side JS knows whether to POST**

Edit `src/phoresis_ui/templates/components/base.html`. Replace `<body class="...">` with:
```django
<body class="min-h-screen bg-bg text-text antialiased"
      data-user="{% if request.user.is_authenticated %}{{ request.user.username }}{% else %}anonymous{% endif %}">
```

- [ ] **Step 5: Add a test**

Append to `src/accounts/tests/test_views.py`:

```python
@pytest.mark.django_db
def test_theme_set_persists_to_userprofile(client) -> None:
    user = UserFactory(username="theme_user")
    client.force_login(user)
    response = client.post(reverse("accounts:theme_set"), {"theme": "dark"})
    assert response.status_code == 204
    user.profile.refresh_from_db()
    assert user.profile.theme == "dark"


@pytest.mark.django_db
def test_theme_set_rejects_invalid_value(client) -> None:
    user = UserFactory(username="theme_user2")
    client.force_login(user)
    response = client.post(reverse("accounts:theme_set"), {"theme": "purple"})
    assert response.status_code == 400


@pytest.mark.django_db
def test_theme_set_requires_login(client) -> None:
    response = client.post(reverse("accounts:theme_set"), {"theme": "dark"})
    assert response.status_code == 302
```

- [ ] **Step 6: Run tests**

```bash
.venv/Scripts/python.exe -m pytest src/accounts/tests/test_views.py -v
```
Expected: 3 new tests pass alongside the existing 6.

- [ ] **Step 7: Commit**

```bash
git add src/accounts/views.py src/accounts/urls.py src/phoresis_ui/static/phoresis_ui/js/alpine-init.js src/phoresis_ui/templates/components/base.html src/accounts/tests/test_views.py
git commit -m "feat(accounts): persist theme preference via HTMX-friendly endpoint"
```

---

## Task 9: Phoresis app icon

**Files:**
- Create: `assets/icons/phoresis.svg` (chosen design)
- Generate: `assets/icons/phoresis.ico`, `phoresis-512.png`, `apple-touch-icon.png`, `mask-icon.svg`
- Copy generated files into `src/phoresis_ui/static/phoresis_ui/icons/` so `{% static %}` finds them

> **Note:** The spec lists 3 candidate directions (§8.6). Phase 3 implements *one* — the chosen direction. **Default choice for this plan:** Direction 2 (abstract gel with 3-4 horizontal bands graduating blue → magenta), because it ties directly to the brand colors (deep lab blue accent + magenta band) and reads cleanly at 16×16. If the user explicitly picks a different direction during execution, the plan adapts: the deliverable is the icon, not the specific design. The agent should pause and check with the user before committing if the design language is ambiguous.

- [ ] **Step 1: Create `assets/icons/phoresis.svg`**

Save in `assets/icons/phoresis.svg`:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <linearGradient id="phoresis-grad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"   stop-color="#3b82f6"/>
      <stop offset="50%"  stop-color="#a855f7"/>
      <stop offset="100%" stop-color="#ec4899"/>
    </linearGradient>
  </defs>
  <!-- Outer rounded square -->
  <rect x="48" y="48" width="416" height="416" rx="80" fill="#0f172a"/>
  <!-- Lane (vertical strip) with three migrating bands -->
  <rect x="200" y="100" width="112"  height="312" rx="16"  fill="url(#phoresis-grad)" opacity="0.18"/>
  <!-- Three horizontal bands -->
  <rect x="200" y="160" width="112" height="22" rx="6" fill="#3b82f6"/>
  <rect x="200" y="240" width="112" height="22" rx="6" fill="#a855f7"/>
  <rect x="200" y="320" width="112" height="22" rx="6" fill="#ec4899"/>
</svg>
```

(This is a starting point — the agent may refine the geometry/proportions before committing. The defining traits: rounded-square dark background, blue→magenta gradient lane silhouette, three horizontal bands at the brand colors.)

- [ ] **Step 2: Generate raster sizes**

Use ImageMagick or `rsvg-convert`. Windows alternative: install `inkscape` and use its CLI.

```bash
mkdir -p assets/icons
# 512 PNG
magick "assets/icons/phoresis.svg" -resize 512x512 "assets/icons/phoresis-512.png"
# Apple touch icon (180×180)
magick "assets/icons/phoresis.svg" -resize 180x180 "assets/icons/apple-touch-icon.png"
# Multi-resolution ICO
magick "assets/icons/phoresis.svg" -define icon:auto-resize=16,24,32,48,64,128,256 "assets/icons/phoresis.ico"
```

If ImageMagick isn't available:
```bash
winget install -e --id ImageMagick.ImageMagick
```

- [ ] **Step 3: Create `mask-icon.svg`** (Safari pinned-tab — single-color)

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <rect x="200" y="160" width="112" height="22" rx="6"/>
  <rect x="200" y="240" width="112" height="22" rx="6"/>
  <rect x="200" y="320" width="112" height="22" rx="6"/>
</svg>
```

- [ ] **Step 4: Mirror generated icons into the static dir**

```bash
mkdir -p src/phoresis_ui/static/phoresis_ui/icons
cp assets/icons/phoresis.svg assets/icons/phoresis.ico assets/icons/phoresis-512.png assets/icons/apple-touch-icon.png assets/icons/mask-icon.svg src/phoresis_ui/static/phoresis_ui/icons/
```

- [ ] **Step 5: Run `collectstatic --dry-run` to verify pickup**

```bash
.venv/Scripts/python.exe manage.py collectstatic --noinput --dry-run | grep phoresis
```
Expected: lists `phoresis.ico`, `phoresis.svg`, `phoresis-512.png`, etc.

- [ ] **Step 6: Visit `http://127.0.0.1:8000/admin/login/` and confirm the favicon appears**

```bash
.venv/Scripts/python.exe manage.py runserver 0.0.0.0:8000
```
In a browser, open the URL — the tab should show the Phoresis icon. (Hard-refresh if cached.)

- [ ] **Step 7: Commit**

```bash
git add assets/icons/ src/phoresis_ui/static/phoresis_ui/icons/phoresis.ico src/phoresis_ui/static/phoresis_ui/icons/phoresis.svg src/phoresis_ui/static/phoresis_ui/icons/phoresis-512.png src/phoresis_ui/static/phoresis_ui/icons/apple-touch-icon.png src/phoresis_ui/static/phoresis_ui/icons/mask-icon.svg
git commit -m "feat(phoresis_ui): add Phoresis app icon (gradient lane + 3 bands, multi-resolution .ico + favicons)"
```

---

## Task 10: Refonte `accounts/login.html` and `accounts/profile.html`

**Files:**
- Modify: `src/accounts/templates/accounts/login.html`
- Modify: `src/accounts/templates/accounts/profile.html`

Both pages now `{% extends 'components/base.html' %}` and use the templatetags + design tokens.

- [ ] **Step 1: Replace `login.html`**

```django
{% extends 'components/base.html' %}
{% load ui_components ui_icons %}

{% block title %}Sign in — Phoresis{% endblock %}

{% block content %}
<div class="grid min-h-[calc(100vh-4rem)] place-items-center">
    <div class="w-full max-w-md">
        <div class="mb-8 flex flex-col items-center">
            <div class="mb-4 grid h-16 w-16 place-items-center rounded-2xl bg-accent-50 text-accent-600">
                {% icon "flask-conical" size=32 %}
            </div>
            <h1 class="text-2xl font-semibold">Welcome back</h1>
            <p class="mt-1 text-sm text-text-muted">Sign in to continue your gel analysis.</p>
        </div>

        <div class="rounded-xl border border-border bg-surface p-6 shadow-sm">
            {% if form.non_field_errors %}
                <div class="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">
                    {% for error in form.non_field_errors %}<p>{{ error }}</p>{% endfor %}
                </div>
            {% endif %}

            <form method="post" action="{% url 'accounts:login' %}" class="space-y-4">
                {% csrf_token %}
                <div>
                    <label for="id_username" class="mb-1.5 block text-sm font-medium">Username</label>
                    <input id="id_username" name="username" type="text" required autocomplete="username"
                           class="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus:border-accent-500 focus:outline-none focus:ring-2 focus:ring-accent-500/20"
                           value="{{ form.username.value|default:'' }}">
                </div>
                <div>
                    <label for="id_password" class="mb-1.5 block text-sm font-medium">Password</label>
                    <input id="id_password" name="password" type="password" required autocomplete="current-password"
                           class="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm focus:border-accent-500 focus:outline-none focus:ring-2 focus:ring-accent-500/20">
                </div>
                {% btn "Sign in" type_="submit" class_="w-full" %}
            </form>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 2: Replace `profile.html`**

```django
{% extends 'components/base.html' %}
{% load ui_components ui_icons %}

{% block title %}Profile — Phoresis{% endblock %}

{% block body %}
{% include 'components/_layout.html' %}
{% endblock %}

{% block content %}
<div class="mx-auto max-w-3xl space-y-6">
    <header class="flex items-center gap-4">
        {% if request.user.profile.avatar %}
            <img src="{{ request.user.profile.avatar.url }}" alt="" class="h-16 w-16 rounded-full object-cover">
        {% else %}
            <span class="grid h-16 w-16 place-items-center rounded-full bg-accent-50 text-2xl font-semibold text-accent-700">
                {{ request.user.username|first|upper }}
            </span>
        {% endif %}
        <div>
            <h1 class="text-2xl font-semibold">{{ request.user }}</h1>
            <p class="text-sm text-text-muted">{{ request.user.email }}</p>
        </div>
    </header>

    {% card_open %}
    <h2 class="mb-4 text-lg font-semibold">Appearance</h2>
    <p class="mb-3 text-sm text-text-muted">Choose how Phoresis looks. Your preference syncs across devices.</p>
    <div x-data class="flex gap-2">
        <button @click="$store.theme.set('light')" :class="$store.theme.user === 'light' ? 'border-accent-500 bg-accent-50 text-accent-700' : 'border-border bg-surface'" class="flex flex-1 flex-col items-center gap-2 rounded-lg border p-4 transition-colors">
            {% icon "sun" %}<span class="text-sm font-medium">Light</span>
        </button>
        <button @click="$store.theme.set('auto')" :class="$store.theme.user === 'auto' ? 'border-accent-500 bg-accent-50 text-accent-700' : 'border-border bg-surface'" class="flex flex-1 flex-col items-center gap-2 rounded-lg border p-4 transition-colors">
            {% icon "monitor" %}<span class="text-sm font-medium">Auto</span>
        </button>
        <button @click="$store.theme.set('dark')" :class="$store.theme.user === 'dark' ? 'border-accent-500 bg-accent-50 text-accent-700' : 'border-border bg-surface'" class="flex flex-1 flex-col items-center gap-2 rounded-lg border p-4 transition-colors">
            {% icon "moon" %}<span class="text-sm font-medium">Dark</span>
        </button>
    </div>
    {% card_close %}

    {% card_open %}
    <h2 class="mb-4 text-lg font-semibold">Account details</h2>
    <dl class="grid grid-cols-2 gap-4 text-sm">
        <dt class="text-text-muted">Username</dt><dd>{{ request.user.username }}</dd>
        <dt class="text-text-muted">Email</dt><dd>{{ request.user.email }}</dd>
        <dt class="text-text-muted">Language</dt><dd>{{ request.user.profile.get_language_display }}</dd>
    </dl>
    {% card_close %}
</div>
{% endblock %}
```

- [ ] **Step 3: Build CSS**

```bash
npm run build:css
```

- [ ] **Step 4: Re-run accounts view tests**

```bash
.venv/Scripts/python.exe -m pytest src/accounts/tests/test_views.py -v
```
Expected: all view tests still pass (the form names `username`/`password` are unchanged from Phase 1).

- [ ] **Step 5: Manual browser smoke**

```bash
.venv/Scripts/python.exe manage.py runserver 0.0.0.0:8000
```
In a browser:
- Visit `/accounts/login/` → polished login card with Phoresis brand
- Sign in → redirects to dashboard (still using Phase 1 stub HTML — Task 11 polishes)
- Visit `/accounts/profile/` → cards for theme picker + account details
- Click theme toggles in the topbar — page repaints smoothly with no flash
- Network tab: `POST /accounts/theme/` returns 204 each click

- [ ] **Step 6: Commit**

```bash
git add src/accounts/templates/accounts/login.html src/accounts/templates/accounts/profile.html
git commit -m "feat(accounts): refonte login + profile pages with Tailwind chrome"
```

---

## Task 11: Refonte `dashboard/home.html` (KPIs, recent gels, quick actions)

**Files:**
- Modify: `src/dashboard/views.py` (compute KPIs + recents)
- Create: `src/dashboard/services.py` (KPI aggregation helpers)
- Modify: `src/dashboard/templates/dashboard/home.html`
- Modify: `src/dashboard/tests/test_views.py` (assert on the new content)

- [ ] **Step 1: Create `src/dashboard/services.py`**

```python
"""Aggregation helpers for the dashboard home page."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count
from django.utils import timezone


@dataclass(frozen=True)
class DashboardKPIs:
    total_gels: int
    total_analyses: int
    pending_analyses: int
    recent_uploads_7d: int


def get_kpis() -> DashboardKPIs:
    """Compute the dashboard KPI tuple."""
    from gel_analyzer.models import GelAnalysis, GelImage

    seven_days_ago = timezone.now() - timedelta(days=7)
    return DashboardKPIs(
        total_gels=GelImage.objects.count(),
        total_analyses=GelAnalysis.objects.count(),
        pending_analyses=GelAnalysis.objects.filter(
            status__in=[GelAnalysis.Status.DRAFT, GelAnalysis.Status.IN_PROGRESS]
        ).count(),
        recent_uploads_7d=GelImage.objects.filter(uploaded_at__gte=seven_days_ago).count(),
    )


def get_recent_gels(limit: int = 6):
    """Return the most-recently-uploaded gels with annotation counts."""
    from gel_analyzer.models import GelImage

    return list(
        GelImage.objects.select_related("uploaded_by")
        .annotate(analyses_count=Count("analyses"))
        .order_by("-uploaded_at")[:limit]
    )
```

- [ ] **Step 2: Update `src/dashboard/views.py`**

```python
"""Dashboard views."""
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from .services import get_kpis, get_recent_gels


@login_required
def home_view(request: HttpRequest) -> HttpResponse:
    return render(request, "dashboard/home.html", {
        "kpis": get_kpis(),
        "recent_gels": get_recent_gels(),
    })
```

- [ ] **Step 3: Replace `dashboard/home.html`**

```django
{% extends 'components/base.html' %}
{% load ui_components ui_icons %}

{% block title %}Dashboard — Phoresis{% endblock %}

{% block body %}
{% include 'components/_layout.html' %}
{% endblock %}

{% block content %}
<div class="space-y-8">
    <header class="flex items-end justify-between">
        <div>
            <h1 class="text-2xl font-semibold">Welcome back, {{ request.user.first_name|default:request.user.username }}.</h1>
            <p class="mt-1 text-sm text-text-muted">Here's a snapshot of your gel analysis activity.</p>
        </div>
        {% btn "Upload gel" href="/images/upload/" icon="upload" %}
    </header>

    <section class="grid grid-cols-2 gap-4 md:grid-cols-4">
        {% kpi "Total gels"      kpis.total_gels        icon="image"            accent="accent" %}
        {% kpi "Total analyses"  kpis.total_analyses    icon="layers"           accent="accent" %}
        {% kpi "Pending"         kpis.pending_analyses  icon="loader"           accent="warning" %}
        {% kpi "New (7 days)"    kpis.recent_uploads_7d icon="trending-up"      accent="success" %}
    </section>

    <section>
        <header class="mb-4 flex items-center justify-between">
            <h2 class="text-lg font-semibold">Recent gels</h2>
            {% btn "View all" href="/images/" variant="ghost" size="sm" %}
        </header>
        {% if recent_gels %}
            <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {% for gel in recent_gels %}
                    <a href="/images/{{ gel.id }}/" class="block rounded-lg border border-border bg-surface p-4 transition-transform hover:-translate-y-[2px] hover:shadow">
                        <div class="mb-3 aspect-video overflow-hidden rounded-md bg-surface-elevated">
                            {% if gel.thumbnail %}
                                <img src="{{ gel.thumbnail.url }}" alt="" class="h-full w-full object-cover">
                            {% else %}
                                <div class="flex h-full items-center justify-center text-text-muted">{% icon "image" size=32 %}</div>
                            {% endif %}
                        </div>
                        <p class="truncate text-sm font-medium">{{ gel.original_filename }}</p>
                        <div class="mt-1 flex items-center gap-2 text-xs text-text-muted">
                            {% badge gel.get_gel_type_display variant="primary" %}
                            <span>•</span>
                            <span>{{ gel.analyses_count }} analyses</span>
                        </div>
                    </a>
                {% endfor %}
            </div>
        {% else %}
            {% empty_state "No gels yet" message="Upload your first gel image to start analyzing." icon="image" cta_label="Upload gel" cta_href="/images/upload/" %}
        {% endif %}
    </section>
</div>
{% endblock %}
```

- [ ] **Step 4: Update tests**

Edit `src/dashboard/tests/test_views.py`:

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
    assert b"Welcome back" in response.content


@pytest.mark.django_db
def test_home_renders_kpis(client) -> None:
    user = UserFactory(username="kayla")
    client.force_login(user)
    response = client.get(reverse("dashboard:home"))
    assert b"Total gels" in response.content
    assert b"Total analyses" in response.content
```

- [ ] **Step 5: Run tests**

```bash
.venv/Scripts/python.exe -m pytest src/dashboard/tests/test_views.py -v
```
Expected: 3 tests pass.

- [ ] **Step 6: Build CSS + manual smoke**

```bash
npm run build:css
.venv/Scripts/python.exe manage.py runserver 0.0.0.0:8000
```
Visit `http://127.0.0.1:8000/` (logged in) — expect KPI cards with animated count-up, recent gels grid (or empty state if no gels uploaded), Upload-gel button in header. Toggle theme — colors flip smoothly.

- [ ] **Step 7: Commit**

```bash
git add src/dashboard/services.py src/dashboard/views.py src/dashboard/templates/dashboard/home.html src/dashboard/tests/test_views.py
git commit -m "feat(dashboard): refonte home with KPI cards (CountUp.js) and recent gels grid"
```

---

## Task 12: gel_analyzer image pages — list, upload, detail, delete

**Files:**
- Create: `src/gel_analyzer/views/__init__.py`
- Create: `src/gel_analyzer/views/images.py` (logic ported from source, HTML rebuilt)
- Create: `src/gel_analyzer/templates/gel_analyzer/images/list.html`
- Create: `src/gel_analyzer/templates/gel_analyzer/images/upload.html`
- Create: `src/gel_analyzer/templates/gel_analyzer/images/detail.html`
- Create: `src/gel_analyzer/templates/gel_analyzer/images/_delete_modal.html`
- Create: `src/gel_analyzer/tests/test_views/__init__.py`
- Create: `src/gel_analyzer/tests/test_views/test_images.py`

- [ ] **Step 1: Create `views/__init__.py`**

```python
"""HTML views for gel_analyzer (Phase 3+). DRF API viewsets land in Phase 4."""
```

- [ ] **Step 2: Port `views/images.py`**

The 296-line source `$DSHUB/gel_analyzer/views/images.py` contains the four views (list, upload, detail, delete) — copy-and-clean. Imports go from `from base.logging_config` → `from phoresis_core.logging_config`, `from gel_analyzer.forms` stays, `from gel_analyzer.services.file_handler` stays.

```bash
cp "C:/Users/gmath/PycharmProjects/PythonProject/ds-hub-django/gel_analyzer/views/images.py" src/gel_analyzer/views/images.py
```

Edit `src/gel_analyzer/views/images.py`:

a. Find:
```python
from base.logging_config import get_logger
```
Replace with:
```python
from phoresis_core.logging_config import get_logger
```

b. Find:
```python
from gel_analyzer.forms import GelImageUploadForm, GelImageEditForm
```
Replace with:
```python
from gel_analyzer.forms.image_forms import GelImageUploadForm
```
(`GelImageEditForm` isn't used in Phase 3 — it shows up only in the heavy detail editor that lands in Phase 4.)

c. Verify the views reference `gel_image.delete()` (no `process_sample` cleanup needed — already removed in Phase 2).

- [ ] **Step 3: Create the templates**

`list.html`:
```django
{% extends 'components/base.html' %}
{% load ui_components ui_icons %}

{% block title %}Gel images — Phoresis{% endblock %}

{% block body %}{% include 'components/_layout.html' %}{% endblock %}

{% block content %}
<div class="space-y-6">
    <header class="flex items-end justify-between">
        <div>
            <h1 class="text-2xl font-semibold">Gel images</h1>
            <p class="mt-1 text-sm text-text-muted">{{ kpis.total }} gels uploaded · {{ kpis.non_analyzed }} pending analysis</p>
        </div>
        {% btn "Upload gel" href="/images/upload/" icon="upload" %}
    </header>

    <form method="get" class="flex flex-wrap gap-2">
        <input type="search" name="q" value="{{ search_query }}" placeholder="Search by filename or description…"
               class="flex-1 min-w-[240px] rounded-md border border-border bg-surface px-3 py-2 text-sm">
        <select name="gel_type" class="rounded-md border border-border bg-surface px-3 py-2 text-sm">
            <option value="">All gel types</option>
            {% for value, label in gel_type_choices %}
                <option value="{{ value }}" {% if value == gel_type_filter %}selected{% endif %}>{{ label }}</option>
            {% endfor %}
        </select>
        <select name="analyzed" class="rounded-md border border-border bg-surface px-3 py-2 text-sm">
            <option value="">All</option>
            <option value="yes" {% if analyzed_filter == 'yes' %}selected{% endif %}>Analyzed</option>
            <option value="no"  {% if analyzed_filter == 'no'  %}selected{% endif %}>Not analyzed</option>
        </select>
        {% btn "Filter" type_="submit" variant="secondary" %}
    </form>

    {% if images %}
        <div class="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {% for gel in images %}
                <a href="/images/{{ gel.id }}/" class="group block rounded-lg border border-border bg-surface p-4 transition-transform hover:-translate-y-[2px] hover:shadow">
                    <div class="mb-3 aspect-video overflow-hidden rounded-md bg-surface-elevated">
                        {% if gel.thumbnail %}
                            <img src="{{ gel.thumbnail.url }}" alt="" class="h-full w-full object-cover">
                        {% else %}
                            <div class="flex h-full items-center justify-center text-text-muted">{% icon "image" size=32 %}</div>
                        {% endif %}
                    </div>
                    <p class="truncate text-sm font-medium">{{ gel.original_filename }}</p>
                    <div class="mt-1 flex items-center gap-2 text-xs text-text-muted">
                        {% badge gel.get_gel_type_display variant="primary" %}
                        <span>·</span>
                        <span>{{ gel.analyses_count }} analyses</span>
                    </div>
                </a>
            {% endfor %}
        </div>
        {% if page_obj.has_other_pages %}
            <nav class="flex justify-center gap-2 pt-2 text-sm">
                {% if page_obj.has_previous %}<a href="?page={{ page_obj.previous_page_number }}" class="rounded-md border border-border px-3 py-1.5">Previous</a>{% endif %}
                <span class="px-3 py-1.5 text-text-muted">Page {{ page_obj.number }} of {{ page_obj.paginator.num_pages }}</span>
                {% if page_obj.has_next %}<a href="?page={{ page_obj.next_page_number }}" class="rounded-md border border-border px-3 py-1.5">Next</a>{% endif %}
            </nav>
        {% endif %}
    {% else %}
        {% empty_state "No gels match" message="Try a different filter or upload a new gel." icon="image" cta_label="Upload gel" cta_href="/images/upload/" %}
    {% endif %}
</div>
{% endblock %}
```

`upload.html`:
```django
{% extends 'components/base.html' %}
{% load ui_components ui_icons %}

{% block title %}Upload gel — Phoresis{% endblock %}

{% block body %}{% include 'components/_layout.html' %}{% endblock %}

{% block content %}
<div class="mx-auto max-w-2xl space-y-6">
    <header>
        <h1 class="text-2xl font-semibold">Upload gel image</h1>
        <p class="mt-1 text-sm text-text-muted">Supported formats: .gel, .scn, .tiff, .tif, .png, .jpg, .jpeg.</p>
    </header>

    {% card_open %}
    <form method="post" enctype="multipart/form-data" class="space-y-4">
        {% csrf_token %}
        <div>
            <label class="mb-1.5 block text-sm font-medium">File</label>
            <input type="file" name="original_file" required accept=".gel,.scn,.tiff,.tif,.png,.jpg,.jpeg"
                   class="block w-full text-sm file:mr-4 file:rounded-md file:border-0 file:bg-accent-50 file:px-4 file:py-2 file:text-sm file:font-medium file:text-accent-700 hover:file:bg-accent-100">
        </div>
        <div>
            <label class="mb-1.5 block text-sm font-medium">Gel type</label>
            <select name="gel_type" class="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm">
                <option value="">— Select —</option>
                <option value="SDS_PAGE">SDS-PAGE</option>
                <option value="DOT_BLOT">Dot Blot</option>
                <option value="WESTERN_BLOT">Western Blot</option>
                <option value="UNKNOWN">Unknown</option>
            </select>
        </div>
        <div>
            <label class="mb-1.5 block text-sm font-medium">Description</label>
            <textarea name="description" rows="3" class="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm" placeholder="Optional notes…"></textarea>
        </div>
        <div class="flex justify-end gap-2 pt-2">
            {% btn "Cancel" href="/images/" variant="ghost" %}
            {% btn "Upload" type_="submit" variant="primary" icon="upload" %}
        </div>
    </form>
    {% card_close %}
</div>
{% endblock %}
```

`detail.html`:
```django
{% extends 'components/base.html' %}
{% load ui_components ui_icons %}

{% block title %}{{ gel_image.original_filename }} — Phoresis{% endblock %}

{% block body %}{% include 'components/_layout.html' %}{% endblock %}

{% block content %}
<div class="space-y-6">
    <header class="flex items-end justify-between">
        <div>
            <h1 class="text-2xl font-semibold">{{ gel_image.original_filename }}</h1>
            <p class="mt-1 text-sm text-text-muted">
                Uploaded {{ gel_image.uploaded_at|date:"M j, Y" }} by {{ gel_image.uploaded_by|default:"—" }}
                · {{ gel_image.dimensions_str }} · {{ gel_image.get_file_format_display }}
            </p>
        </div>
        <div class="flex gap-2">
            {% btn "New analysis" href="/images/"|add:gel_image.id|stringformat:'s'|add:"/analyses/create/" icon="plus" %}
            {% btn "Delete" variant="danger" icon="trash-2" hx_post="" %}
        </div>
    </header>

    <div class="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <div class="rounded-lg border border-border bg-surface p-4">
            {% if gel_image.display_file %}
                <img src="{{ gel_image.display_file.url }}" alt="" class="w-full rounded-md">
            {% else %}
                <div class="aspect-video grid place-items-center text-text-muted">{% icon "image" size=48 %}</div>
            {% endif %}
        </div>
        <aside class="space-y-4">
            <div class="rounded-lg border border-border bg-surface p-4">
                <h3 class="mb-3 text-sm font-semibold uppercase tracking-wide text-text-muted">Analyses</h3>
                {% if analyses %}
                    <ul class="space-y-2 text-sm">
                        {% for a in analyses %}
                            <li class="flex items-center justify-between">
                                <a href="/analyses/{{ a.id }}/" class="hover:underline">{{ a.name|default:"(unnamed)" }}</a>
                                {% badge a.get_status_display variant="muted" %}
                            </li>
                        {% endfor %}
                    </ul>
                {% else %}
                    <p class="text-sm text-text-muted">No analyses yet.</p>
                {% endif %}
            </div>
        </aside>
    </div>
</div>
{% endblock %}
```

(The `delete.html` template is replaced by an HTMX-loaded modal in this iteration; see Phase 4 for the full delete flow. For Phase 3, delete still works via direct POST — see the source view's POST handling — but the UX is via a confirm modal launched from the detail page in Task 14.)

- [ ] **Step 4: Add the view tests**

Create `src/gel_analyzer/tests/test_views/__init__.py` (empty) and `src/gel_analyzer/tests/test_views/test_images.py`:

```python
"""Tests for gel_analyzer image views (Phase 3 shell pages)."""
import pytest
from django.urls import reverse

from accounts.tests.factories import UserFactory


@pytest.mark.django_db
def test_image_list_requires_login(client) -> None:
    response = client.get(reverse("gel_analyzer:image_list"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


@pytest.mark.django_db
def test_image_list_authenticated_returns_200(client) -> None:
    user = UserFactory(username="img_user")
    client.force_login(user)
    response = client.get(reverse("gel_analyzer:image_list"))
    assert response.status_code == 200
    assert b"Gel images" in response.content


@pytest.mark.django_db
def test_image_upload_get_returns_200(client) -> None:
    user = UserFactory(username="up_user")
    client.force_login(user)
    response = client.get(reverse("gel_analyzer:image_upload"))
    assert response.status_code == 200
    assert b"Upload gel" in response.content
```

- [ ] **Step 5: Commit (URLs wired in Task 14)**

The image views and templates are ready, but the URLs aren't routed yet — that's Task 14. Stage now, run tests in Task 14.

```bash
git add src/gel_analyzer/views/__init__.py src/gel_analyzer/views/images.py src/gel_analyzer/templates/gel_analyzer/images/ src/gel_analyzer/tests/test_views/
git commit -m "feat(gel_analyzer): add image views (list, upload, detail) + Tailwind templates"
```

---

## Task 13: gel_analyzer analysis pages — list, create

**Files:**
- Create: `src/gel_analyzer/views/analyses.py`
- Create: `src/gel_analyzer/templates/gel_analyzer/analyses/list.html`
- Create: `src/gel_analyzer/templates/gel_analyzer/analyses/create.html`
- Create: `src/gel_analyzer/tests/test_views/test_analyses.py`

> **Scope reminder:** Only `analysis_list_view` and `analysis_create_view` ship in Phase 3. The `analysis_detail_view` and `analysis_annotate_view` (heavy viewers) land in Phase 4.

- [ ] **Step 1: Create `views/analyses.py`**

```python
"""Analysis HTML views (Phase 3 shells).

The heavy annotate/detail views land in Phase 4 — Phase 3 only ships list and
create. Logic ported from `$DSHUB/gel_analyzer/views/analyses.py` (list +
create only); ProcessSample / sample_analyses references already removed in
Phase 2's models — nothing further to strip here.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from gel_analyzer.forms.analysis_forms import GelAnalysisCreateForm
from gel_analyzer.models import GelAnalysis, GelImage
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


@login_required
def analysis_list_view(request: HttpRequest) -> HttpResponse:
    status_filter = request.GET.get("status", "")
    search_query = request.GET.get("q", "")

    analyses = (
        GelAnalysis.objects.select_related("gel_image", "created_by")
        .order_by("-created_at")
    )
    if status_filter:
        analyses = analyses.filter(status=status_filter)
    if search_query:
        analyses = analyses.filter(
            Q(name__icontains=search_query)
            | Q(gel_image__original_filename__icontains=search_query)
        )

    paginator = Paginator(analyses, 24)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(request, "gel_analyzer/analyses/list.html", {
        "page_obj": page_obj,
        "analyses": page_obj.object_list,
        "status_filter": status_filter,
        "search_query": search_query,
        "status_choices": GelAnalysis.Status.choices,
    })


@login_required
def analysis_create_view(request: HttpRequest, image_pk) -> HttpResponse:
    gel_image = get_object_or_404(GelImage, pk=image_pk)

    if request.method == "POST":
        form = GelAnalysisCreateForm(request.POST)
        if form.is_valid():
            analysis = form.save(commit=False)
            analysis.gel_image = gel_image
            analysis.created_by = request.user
            analysis.save()
            logger.info(
                f"Created GelAnalysis {analysis.id}",
                user=request.user.username,
                gel_image_id=str(gel_image.id),
            )
            messages.success(request, "Analysis created — open it to start annotating.")
            # Redirect to detail (Phase 4); for Phase 3, redirect to image detail.
            return redirect("gel_analyzer:image_detail", pk=gel_image.id)
    else:
        form = GelAnalysisCreateForm(initial={"name": gel_image.original_filename})

    return render(request, "gel_analyzer/analyses/create.html", {
        "gel_image": gel_image,
        "form": form,
    })
```

- [ ] **Step 2: Create the templates**

`list.html`:
```django
{% extends 'components/base.html' %}
{% load ui_components ui_icons %}

{% block title %}Analyses — Phoresis{% endblock %}

{% block body %}{% include 'components/_layout.html' %}{% endblock %}

{% block content %}
<div class="space-y-6">
    <header class="flex items-end justify-between">
        <div>
            <h1 class="text-2xl font-semibold">Analyses</h1>
            <p class="mt-1 text-sm text-text-muted">All gel analyses you can access.</p>
        </div>
    </header>

    <form method="get" class="flex flex-wrap gap-2">
        <input type="search" name="q" value="{{ search_query }}" placeholder="Search by name or gel filename…"
               class="flex-1 min-w-[240px] rounded-md border border-border bg-surface px-3 py-2 text-sm">
        <select name="status" class="rounded-md border border-border bg-surface px-3 py-2 text-sm">
            <option value="">All statuses</option>
            {% for value, label in status_choices %}
                <option value="{{ value }}" {% if value == status_filter %}selected{% endif %}>{{ label }}</option>
            {% endfor %}
        </select>
        {% btn "Filter" type_="submit" variant="secondary" %}
    </form>

    {% if analyses %}
        <div class="overflow-hidden rounded-lg border border-border bg-surface">
            <table class="w-full text-sm">
                <thead class="bg-surface-elevated text-left text-xs uppercase tracking-wide text-text-muted">
                    <tr>
                        <th class="px-4 py-3">Name</th>
                        <th class="px-4 py-3">Gel</th>
                        <th class="px-4 py-3">Status</th>
                        <th class="px-4 py-3">Lanes</th>
                        <th class="px-4 py-3">Bands</th>
                        <th class="px-4 py-3">Created</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-border">
                    {% for a in analyses %}
                        <tr class="hover:bg-surface-elevated">
                            <td class="px-4 py-3"><a href="/analyses/{{ a.id }}/" class="font-medium hover:underline">{{ a.name|default:"(unnamed)" }}</a></td>
                            <td class="px-4 py-3 text-text-muted">{{ a.gel_image.original_filename|truncatechars:32 }}</td>
                            <td class="px-4 py-3">{% badge a.get_status_display variant="muted" %}</td>
                            <td class="px-4 py-3">{{ a.total_lanes }}</td>
                            <td class="px-4 py-3">{{ a.total_bands }}</td>
                            <td class="px-4 py-3 text-text-muted">{{ a.created_at|date:"M j, Y" }}</td>
                        </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    {% else %}
        {% empty_state "No analyses yet" message="Open a gel image to create your first analysis." icon="layers" cta_label="Browse gels" cta_href="/images/" %}
    {% endif %}
</div>
{% endblock %}
```

`create.html`:
```django
{% extends 'components/base.html' %}
{% load ui_components ui_icons %}

{% block title %}New analysis — Phoresis{% endblock %}

{% block body %}{% include 'components/_layout.html' %}{% endblock %}

{% block content %}
<div class="mx-auto max-w-2xl space-y-6">
    <header>
        <h1 class="text-2xl font-semibold">New analysis</h1>
        <p class="mt-1 text-sm text-text-muted">For gel <span class="font-medium">{{ gel_image.original_filename }}</span>.</p>
    </header>

    {% card_open %}
    <form method="post" class="space-y-4">
        {% csrf_token %}
        <div>
            <label class="mb-1.5 block text-sm font-medium">Analysis name</label>
            <input type="text" name="name" value="{{ form.name.value|default:'' }}"
                   class="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm">
            {% if form.name.errors %}<p class="mt-1 text-xs text-danger">{{ form.name.errors|first }}</p>{% endif %}
        </div>
        <div>
            <label class="mb-1.5 block text-sm font-medium">Notes</label>
            <textarea name="notes" rows="3" class="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm">{{ form.notes.value|default:'' }}</textarea>
        </div>
        <div class="flex justify-end gap-2 pt-2">
            {% btn "Cancel" href="/images/"|add:gel_image.id|stringformat:'s'|add:"/" variant="ghost" %}
            {% btn "Create analysis" type_="submit" variant="primary" %}
        </div>
    </form>
    {% card_close %}
</div>
{% endblock %}
```

- [ ] **Step 3: Add tests**

`src/gel_analyzer/tests/test_views/test_analyses.py`:

```python
"""Tests for gel_analyzer analysis views (Phase 3 shells)."""
import pytest
from django.urls import reverse

from accounts.tests.factories import UserFactory
from gel_analyzer.models import GelImage


@pytest.fixture
def gel_image(db):
    user = UserFactory(username="ga_user")
    return GelImage.objects.create(
        original_filename="x.png",
        file_format=GelImage.FileFormat.PNG,
        gel_type=GelImage.GelType.SDS_PAGE,
        uploaded_by=user,
    )


@pytest.mark.django_db
def test_analysis_list_returns_200(client, gel_image) -> None:
    user = UserFactory(username="al_user")
    client.force_login(user)
    response = client.get(reverse("gel_analyzer:analysis_list"))
    assert response.status_code == 200
    assert b"Analyses" in response.content


@pytest.mark.django_db
def test_analysis_create_get_returns_200(client, gel_image) -> None:
    user = UserFactory(username="ac_user")
    client.force_login(user)
    response = client.get(reverse("gel_analyzer:analysis_create", kwargs={"image_pk": gel_image.pk}))
    assert response.status_code == 200
    assert b"New analysis" in response.content
```

- [ ] **Step 4: Commit (URLs land in Task 14)**

```bash
git add src/gel_analyzer/views/analyses.py src/gel_analyzer/templates/gel_analyzer/analyses/ src/gel_analyzer/tests/test_views/test_analyses.py
git commit -m "feat(gel_analyzer): add analysis list + create views with Tailwind templates"
```

---

## Task 14: Forms refonte + URL wiring + nav.py update

**Files:**
- Create: `src/gel_analyzer/forms/__init__.py`
- Create: `src/gel_analyzer/forms/image_forms.py`
- Create: `src/gel_analyzer/forms/analysis_forms.py`
- Modify: `src/gel_analyzer/urls.py`
- Modify: `src/gel_analyzer/nav.py`

- [ ] **Step 1: Create `forms/__init__.py`**

```python
"""HTML forms for gel_analyzer (Tailwind-styled, no MDB5 widgets)."""
```

- [ ] **Step 2: Create `forms/image_forms.py`**

```python
"""Forms for GelImage management."""
from django import forms
from gel_analyzer.models import GelImage


class GelImageUploadForm(forms.ModelForm):
    """Upload form. The HTML template provides Tailwind styling — we keep the form
    minimal so it can pair with raw inputs in `images/upload.html`."""

    class Meta:
        model = GelImage
        fields = ["original_file", "gel_type", "description"]

    def clean_original_file(self):
        f = self.cleaned_data.get("original_file")
        if not f:
            return f
        allowed = (".gel", ".scn", ".tiff", ".tif", ".png", ".jpg", ".jpeg")
        if not f.name.lower().endswith(allowed):
            raise forms.ValidationError(f"Unsupported file extension. Allowed: {', '.join(allowed)}")
        return f
```

- [ ] **Step 3: Create `forms/analysis_forms.py`**

```python
"""Forms for GelAnalysis."""
from django import forms
from gel_analyzer.models import GelAnalysis


class GelAnalysisCreateForm(forms.ModelForm):
    class Meta:
        model = GelAnalysis
        fields = ["name", "notes"]
```

- [ ] **Step 4: Wire URLs**

Replace `src/gel_analyzer/urls.py` with:

```python
"""URL config for gel_analyzer (Phase 3 shells)."""
from django.urls import path

from .views import images as image_views, analyses as analysis_views

app_name = "gel_analyzer"

urlpatterns = [
    # Images
    path("images/",                      image_views.image_list_view,   name="image_list"),
    path("images/upload/",               image_views.image_upload_view, name="image_upload"),
    path("images/<uuid:pk>/",            image_views.image_detail_view, name="image_detail"),
    path("images/<uuid:pk>/delete/",     image_views.image_delete_view, name="image_delete"),

    # Analyses
    path("analyses/",                                       analysis_views.analysis_list_view,   name="analysis_list"),
    path("images/<uuid:image_pk>/analyses/create/",         analysis_views.analysis_create_view, name="analysis_create"),

    # Phase 4 will add: analyses/<uuid:pk>/, analyses/<uuid:pk>/annotate/, api/...
]
```

- [ ] **Step 5: Include gel_analyzer in root URLs**

Edit `src/phoresis/urls.py` — add this `include()`:

```python
"""Root URLconf for the Phoresis project."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include(("accounts.urls", "accounts"), namespace="accounts")),
    path("",         include(("gel_analyzer.urls", "gel_analyzer"), namespace="gel_analyzer")),
    path("",         include(("dashboard.urls", "dashboard"), namespace="dashboard")),
]
```

(Order matters: `gel_analyzer` mounts at `""` with prefixes like `images/`, and `dashboard` also mounts at `""` for `/`. Django URL resolution picks the first match — `dashboard.urls` only has `path("", ...)` for `/`, so putting it last is correct: `/images/...` resolves before falling through to `dashboard:home`.)

- [ ] **Step 6: Update `nav.py`** with the new pages and actions

Replace `src/gel_analyzer/nav.py` with:

```python
"""Register the Gel Analyzer app in the navigation registry."""
from phoresis_core.navigation import nav_registry

nav_registry.register_app(
    app_label="gel_analyzer",
    display_name="Gel Analyzer",
    group="Lab Tools",
    icon="image",
    keywords=["gel", "SDS-PAGE", "dot blot", "western blot", "band", "densitometry", "electrophoresis"],
    shortcut_key="g",
    pages=[
        {"name": "Gel images",  "url": "gel_analyzer:image_list",   "icon": "image"},
        {"name": "Analyses",    "url": "gel_analyzer:analysis_list", "icon": "layers"},
    ],
    actions=[
        {"name": "Upload gel",  "url": "gel_analyzer:image_upload", "icon": "upload"},
    ],
)
```

- [ ] **Step 7: Run all tests (gel_analyzer view tests, layout test, palette test)**

```bash
.venv/Scripts/python.exe -m pytest -v
```
Expected: ~190 tests pass (previous total + Phase 3 additions). Layout test now resolves all sidebar URLs. Palette JSON includes the 3 newly-registered items.

- [ ] **Step 8: Commit**

```bash
git add src/gel_analyzer/forms/ src/gel_analyzer/urls.py src/gel_analyzer/nav.py src/phoresis/urls.py
git commit -m "feat(gel_analyzer): add forms + populate URLs + extend nav.py with images/analyses"
```

---

## Task 15: End-to-end browser smoke + tag v0.3.0

- [ ] **Step 1: Final CSS build**

```bash
npm run build:css
```

- [ ] **Step 2: Run the entire test suite**

```bash
.venv/Scripts/python.exe -m pytest -v
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m pre_commit run --all-files
```
Expected: all green.

- [ ] **Step 3: Start runserver and walk every page**

```bash
.venv/Scripts/python.exe manage.py runserver 0.0.0.0:8000
```

In a browser (signed in as a test user with at least one uploaded gel), visit and confirm visually:

| URL | Expected |
|---|---|
| `/accounts/login/` | Polished login card with brand mark |
| `/` (dashboard) | KPI cards animate count-up; recent gels grid; Upload button |
| `/images/` | Cards grid with filters; pagination if > 24 |
| `/images/upload/` | Form with file + select + textarea; styled submit |
| `/images/<uuid>/` | Image preview + analyses sidebar |
| `/images/<uuid>/analyses/create/` | Create form with name + notes |
| `/analyses/` | Table view with status badges |
| `/accounts/profile/` | Theme picker + account details |
| Ctrl+K | Command palette opens; typing "image" filters to image-related items |
| Theme toggle in topbar | Smooth flip light → dark → light → auto |

For each, watch the console — no errors, no 404s on static assets.

- [ ] **Step 4: Verify the app icon shows up**

In the browser tab and the bookmark — Phoresis icon visible at all rendering sizes (browser zoom in/out).

- [ ] **Step 5: Commit any final fixes from the browser smoke**

```bash
git status
```
If any changes (typos, missing icons, layout adjustments):
```bash
git add -u
git commit -m "fix(phoresis_ui): tweaks from Phase 3 browser smoke"
```

- [ ] **Step 6: Tag v0.3.0**

```bash
git tag -a v0.3.0 -m "Phase 3: Frontend foundation — Tailwind 4, design tokens, 9 component templatetags, icon system, command palette, theme switcher, Phoresis app icon, 5 shell pages refonte"
git tag --list
```

---

## Acceptance criteria for Phase 3

This phase is **done** when ALL of the following hold:

1. `npm install && npm run build:css` succeeds; `output.css` is generated.
2. `python manage.py check` passes; `python manage.py runserver` boots cleanly.
3. `pytest -v` runs with 0 failures, 0 errors. Approximate count: ~190 tests (Phase 1 + Phase 2 + ~12 component tests + ~5 layout/palette tests + ~3 theme-set + ~3 dashboard + ~6 gel_analyzer views).
4. `ruff check .` and `ruff format --check .` are both clean.
5. `pre-commit run --all-files` is green.
6. The git tag `v0.3.0` exists.
7. Every page extends `components/base.html` (no leftover self-contained Phase 1 stubs):
   - `/accounts/login/`, `/accounts/profile/`
   - `/` (dashboard)
   - `/images/`, `/images/upload/`, `/images/<uuid>/`
   - `/analyses/`, `/images/<uuid>/analyses/create/`
8. Component invariants from spec §8.1–8.5:
   - `tokens.css` matches the spec verbatim (light + dark blocks).
   - 9 component templatetags exist and emit Tailwind classes that resolve through the tokens.
   - 8 custom SVG icons present in `static/phoresis_ui/icons/custom/` matching Lucide stroke style.
   - Lucide sprite committed with at least the 48 icons listed in Task 3.
   - Theme switcher in the topbar offers Auto / Light / Dark; clicking persists to `UserProfile.theme` (verified by `test_theme_set_persists_to_userprofile`).
9. The Phoresis app icon (`phoresis.ico` + favicons) is committed under `assets/icons/` and mirrored to `static/phoresis_ui/icons/`. Browser tab shows it.
10. Command palette opens via Ctrl+K, lists Dashboard / Gel images / Analyses / Upload gel, and filters as the user types.
11. Sidebar collapses to 72 px and expands to 240 px on hover; pin toggle persists via `localStorage`.
12. No `from base.widgets` references in `gel_analyzer/forms/` (MDB5 fully gone).
