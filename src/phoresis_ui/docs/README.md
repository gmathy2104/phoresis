# `phoresis_ui`

The Phoresis design system — Tailwind CSS 4, design tokens, component templatetags, layout chrome, and icon set.

## Purpose

- CSS-variable-driven design tokens (`tokens.css`) consumed by Tailwind 4 via `@theme`.
- 9 component templatetags (`btn`, `card`, `badge`, `kpi`, `modal_chrome`, `confirm`, `toast_container`, `empty_state`, `skeleton`).
- Icon system: Lucide sprite (~50 curated icons) + 8 custom Phoresis SVGs (gel, ladder, blot, electrophoresis, densitometry, lane, band, peak).
- Layout chrome: `app_base.html`, `_sidebar.html`, `_topbar.html`, `_command_palette.html`.
- Alpine stores: `theme`, `toast`, `modal`, `palette`.
- HTMX 2 wiring: CSRF, indicators, auto-toast on response status.
- Micro-interactions: button ripple, HTMX top progress bar, sidebar icon scale on hover, dropzone pulse, floating labels.

## Public surface

### Templatetags

```django
{% load ui_components ui_icons %}

{% btn "Save" variant="primary" icon="check" %}
{% btn "Cancel" variant="ghost" %}
{% btn "Delete" variant="danger" hx_post="/x/" %}
{% btn "View" href="/x/" disabled=True %}            {# anchor with aria-disabled #}

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
$store.theme.set('dark')          // 'auto' | 'light' | 'dark' (also POSTs to /accounts/theme/ for authenticated users)
$store.toast.push({ variant: 'success', title: 'Saved' })
$store.modal.show('my-modal'); $store.modal.close()
$store.palette.show()             // also bound to Ctrl+K
```

### Authenticated-page base template

Page templates that need the sidebar/topbar chrome should `{% extends 'components/app_base.html' %}` (NOT `components/base.html` — that's the bare HTML5 shell). Then override `{% block content %}`.

```django
{% extends 'components/app_base.html' %}
{% load ui_components ui_icons %}

{% block title %}My page — Phoresis{% endblock %}
{% block content %}…my page content…{% endblock %}
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
| `templates/components/base.html` | bare HTML5 shell — extended by login + 404/500 |
| `templates/components/app_base.html` | extends base + inlines sidebar/topbar/palette/toast |
| `templates/components/_sidebar.html` | nav rail |
| `templates/components/_topbar.html` | search + theme toggle + avatar menu |
| `templates/components/_command_palette.html` | Ctrl+K modal |

## Build

```bash
npm install
npm run build:css       # produces output.css
npm run watch:css       # dev watch mode
```

## Adding a new component

1. Add the templatetag in `ui_components.py`.
2. Create the partial in `templates/components/_<name>.html` (only if it needs Django template features).
3. Add a test in `tests/test_components.py`.
4. Document in `docs/DESIGN.md` component catalogue (Phase 7 Task 5).
