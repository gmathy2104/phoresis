# Phoresis design system

This document is the design source-of-truth: tokens, components, animations, accessibility, and the procedure for adding new components. The values here are mirrored in `src/phoresis_ui/static/phoresis_ui/css/tokens.css` (which is the canonical source for CSS values) and in `src/phoresis_ui/templatetags/ui_components.py` (which owns the markup for every reusable component).

## 1. Design philosophy

Phoresis aims for Linear / Vercel / Notion-class polish. The visual language is deliberately quiet: a deep lab blue (`#2563eb`) for the primary accent, a magenta (`#ec4899`) reserved for gel-band semantics (so detected bands and band counts always read the same way wherever they appear), and a neutral slate-tinted gray ramp for everything else. Dark mode is first-class — every token has both a light and a dark value, and the theme is switchable per-user with no flash-of-unstyled-content.

The product runs on a wet-lab user's laptop, so density is the second-most-important quality after polish: most screens are dense data views (lane lists, band tables, comparison panels), and the design rewards keyboard users (Ctrl+K palette, ESC-closes-everything, focus rings on every interactive element). The third quality is stability — animations are short (150-400 ms), purposeful, and never block input.

## 2. Tokens

All tokens live in `src/phoresis_ui/static/phoresis_ui/css/tokens.css`, exposed as CSS custom properties on `:root` (light) and `[data-theme="dark"]` (dark).

### Color — surfaces

| Token | Light | Dark |
|---|---|---|
| `--bg` | `#ffffff` | `#0b1220` |
| `--bg-elev-1` | `#f8fafc` | `#111a2e` |
| `--bg-elev-2` | `#f1f5f9` | `#172238` |
| `--fg` | `#0f172a` | `#e2e8f0` |
| `--fg-muted` | `#475569` | `#94a3b8` |
| `--border` | `#e2e8f0` | `#1e293b` |
| `--border-strong` | `#cbd5e1` | `#334155` |

### Color — accent (deep lab blue ramp)

| Token | Light | Dark |
|---|---|---|
| `--accent-50` | `#eff6ff` | `#0c1a35` |
| `--accent-100` | `#dbeafe` | `#102449` |
| `--accent-500` | `#2563eb` | `#3b82f6` |
| `--accent-600` | `#1d4ed8` | `#2563eb` |
| `--accent-fg` | `#ffffff` | `#ffffff` |

### Color — gel semantics

| Token | Light | Dark | Use |
|---|---|---|---|
| `--gel-band` | `#ec4899` | `#f472b6` | detected bands |
| `--gel-poi` | `#2563eb` | `#3b82f6` | protein of interest |
| `--gel-mw-ref` | `#10b981` | `#34d399` | molecular-weight ladder |
| `--gel-other` | `#64748b` | `#94a3b8` | unassigned / other |

### Color — status

| Token | Light | Dark |
|---|---|---|
| `--success` | `#16a34a` | `#22c55e` |
| `--warning` | `#d97706` | `#f59e0b` |
| `--danger` | `#dc2626` | `#ef4444` |
| `--info` | `#0284c7` | `#0ea5e9` |

### Typography

| Token | Value |
|---|---|
| `--font-sans` | `"Inter", system-ui, sans-serif` |
| `--font-mono` | `"JetBrains Mono", ui-monospace, monospace` |
| `--text-xs` | `0.75rem / 1rem` |
| `--text-sm` | `0.875rem / 1.25rem` |
| `--text-base` | `1rem / 1.5rem` |
| `--text-lg` | `1.125rem / 1.75rem` |
| `--text-xl` | `1.25rem / 1.75rem` |
| `--text-2xl` | `1.5rem / 2rem` |
| `--font-weight-normal` | `400` |
| `--font-weight-medium` | `500` |
| `--font-weight-semibold` | `600` |

### Spacing — 4 px rhythm

| Token | Value |
|---|---|
| `--space-1` | `4px` |
| `--space-2` | `8px` |
| `--space-3` | `12px` |
| `--space-4` | `16px` |
| `--space-6` | `24px` |
| `--space-8` | `32px` |
| `--space-12` | `48px` |

### Radius

| Token | Value | Use |
|---|---|---|
| `--radius-sm` | `6px` | inputs, badges |
| `--radius-md` | `10px` | buttons, cards |
| `--radius-lg` | `14px` | modals |
| `--radius-xl` | `20px` | hero panels |

### Shadow

| Token | Value |
|---|---|
| `--shadow-sm` | `0 1px 2px 0 rgb(0 0 0 / 0.05)` |
| `--shadow-md` | `0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)` |
| `--shadow-lg` | `0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)` |

In dark mode the shadow opacity is increased to `0.45` to preserve depth perception against the dark surface.

### Motion

| Token | Value | Use |
|---|---|---|
| `--ease-out` | `cubic-bezier(0.22, 1, 0.36, 1)` | default for entering elements |
| `--duration-fast` | `150ms` | hover / press |
| `--duration-base` | `250ms` | modals, theme flip |
| `--duration-slow` | `400ms` | page swap, KPI count-up |

## 3. Components catalogue

Every component is implemented as a Django templatetag in `src/phoresis_ui/templatetags/ui_components.py`. Tags either render inline HTML (for simple chrome) or include a partial from `src/phoresis_ui/templates/components/_*.html` (for tags with template loops or sub-tags). Tests live in `src/phoresis_ui/tests/test_components.py`.

### `{% btn %}`

```django
{% btn "Save" variant="primary" size="md" %}
{% btn "Loading" loading=True %}
{% btn "Open ladder" href="/ladders/" variant="ghost" icon="external-link" %}
{% btn "Delete" variant="danger" disabled=True %}
```

Variants: `primary` (default, accent-500 fill), `secondary` (border + neutral), `ghost` (no border, hover bg-elev-1), `danger` (red), `link` (text-only).
Sizes: `sm`, `md` (default), `lg`.
States: `loading=True` swaps the label for a spinner and sets `aria-busy="true"`; `disabled=True` adds `aria-disabled="true"` and disables pointer events; passing `href` renders an `<a>` with the same styling. All buttons emit a 600 ms ripple from the click point.

### `{% card_open %}` / `{% card_close %}`

```django
{% card_open title="Recent gels" subtitle="last 7 days" %}
  ... content ...
{% card_close %}
```

These are paired tags (not a single `{% card %}`) so the body can contain arbitrary template logic, includes, and other tags. The opening tag accepts `title`, `subtitle`, `actions` (HTML for the right-aligned action area), and `padding="none|sm|md|lg"`. Card chrome uses `--bg-elev-1` with `--border` and `--radius-md`.

### `{% badge %}`

```django
{% badge "Running" tone="info" %}
{% badge "12 bands" tone="brand" icon="band" %}
{% badge "Failed" tone="danger" %}
```

Tones: `neutral`, `brand`, `success`, `warning`, `danger`, `info`. Always carries a text label — color is never the only signal. Optional `icon=` renders a 14 px inline icon ahead of the label.

### `{% kpi %}`

```django
{% kpi value=42 label="Gels uploaded" trend="+12%" trend_dir="up" icon="image" %}
```

Renders the large dashboard tiles. The numeric value animates from 0 via CountUp.js (lazy-loaded) over 800 ms on first paint. `trend_dir` may be `up`, `down`, or `flat`; `up` is green, `down` is red — accompanied by a `▲`/`▼` glyph so the meaning isn't carried by color alone.

### `{% modal_chrome %}`

```django
{% modal_chrome id="confirm-delete" title="Delete analysis?" %}
  <p>This cannot be undone.</p>
  <div class="flex justify-end gap-2 mt-4">
    {% btn "Cancel" variant="ghost" data_dismiss="confirm-delete" %}
    {% btn "Delete" variant="danger" %}
  </div>
{% endmodal_chrome %}
```

Renders the standard modal shell. Pressing `Esc` closes the modal; clicking the backdrop closes the modal; the close (X) button is keyboard-focusable. Carries `role="dialog"` and `aria-modal="true"` (via Alpine `x-show` + `x-transition`); the trigger button should set `aria-haspopup="dialog"`. Enter animation: `scale-95 → 100` + opacity, 200 ms.

### `{% confirm %}`

Sugar over `{% modal_chrome %}` for "are you sure?" prompts. Accepts `title`, `body`, `confirm_label`, `confirm_variant`, and a `hx-post` URL so the confirm button submits via HTMX.

### `{% toast_container %}`

Inserts the global toast region into the layout (typically once in `app_base.html`). The region carries `aria-live="polite"` and `role="status"` so announcements are read by screen readers without stealing focus. Toasts auto-dismiss after 4 s and stack bottom-right.

### `{% empty_state %}`

```django
{% empty_state icon="image-off" title="No gels yet" body="Upload your first gel to get started." cta_label="Upload" cta_href="/images/upload/" %}
```

Centered illustration + heading + body + optional CTA. Used for first-run dashboard, empty analyses list, empty band table.

### `{% skeleton %}`

```django
{% skeleton class="h-4 w-32" %}
```

A shimmer-animated placeholder rectangle. Composes with Tailwind utilities (`h-`, `w-`, `rounded-`). Animation: 2 s shimmer (`translateX(-100% → 100%)`) on a gradient overlay; respects `prefers-reduced-motion` (see §9).

### Accessibility notes summary

- `{% btn disabled=True href=... %}` adds `aria-disabled="true"` and removes the default link behavior (the click is swallowed at the JS layer).
- `{% btn loading=True %}` adds `aria-busy="true"`.
- `{% modal_chrome %}` traps `Esc`, traps clicks on the backdrop, and adds `role="dialog"` + `aria-modal="true"`.
- `{% toast_container %}` uses `aria-live="polite"`.
- Every interactive component has a visible `:focus-visible` ring.

## 4. Layout

Phoresis ships two base templates:

- **`base.html`** — bare HTML shell, just `<head>` + `<main>`. Used for unauthenticated screens (login, password reset, branded `404.html` and `500.html`).
- **`app_base.html`** — the authenticated chrome. Inlines the sidebar, topbar, and command palette partials (`_sidebar.html`, `_topbar.html`, `_command_palette.html`) and exposes a `{% block content %}` slot for the page body.

Note: `_layout.html` was removed during cleanup; do not reference it. New authenticated pages should `{% extends "app_base.html" %}`.

Dimensions:

- **Sidebar** — 72 px collapsed (icon-only), 240 px expanded on hover or when pinned via `localStorage.phoresis_sidebar_pinned`. The pinned state is per-device and is restored before first paint.
- **Topbar** — 60 px fixed, contains breadcrumbs, the global search trigger (Ctrl+K), the theme toggle, and the user menu.
- **Content** — `max-w-7xl` with `px-6 md:px-8 py-6 md:py-8`. The 7xl ceiling keeps line lengths readable on 4K monitors without forcing a narrower app at 1280 px.

## 5. Animations & micro-interactions

The full §8.4 set, with timings:

- **Buttons** — 600 ms ripple from the click point (CSS keyframe `@keyframes ripple` + a small JS handler that injects the ripple span at the cursor coordinates).
- **HTMX** — top progress bar (3 px high, accent-500). Fades in on `htmx:beforeRequest` and out on `htmx:afterSwap` via CSS state classes.
- **Sidebar icons** — `group-hover:scale-110` (`transition-transform var(--duration-fast)`).
- **Forms** — `.ui-float` opt-in floating labels; the label translates from inside the input to above it on focus / non-empty.
- **Drag-drop** — dropzone pulses via the `data-active="true"` attribute (background tint + border glow).
- **Theme** — 250 ms color transition on `<html>` flip; only transitions `background-color`, `color`, and `border-color` (not box-shadow, to avoid flicker).
- **KPIs** — CountUp.js (lazy-loaded on first dashboard hit) over 800 ms with `--ease-out`.
- **Modals** — `scale-95 → scale-100` + opacity, 200 ms enter, 150 ms exit.
- **Skeletons** — 2 s shimmer (`translateX(-100% → 100%)`) on a horizontal gradient.
- **Page swaps** — View Transition API (Chrome / Edge); a graceful no-op in Firefox / Safari.

## 6. Light / Dark mode

Theme is held on `<html data-theme="light|dark">`. The pre-paint switcher is inlined at the top of `<head>` in `base.html`:

```html
<script>
  (function () {
    var t = localStorage.getItem("phoresis_theme") || "light";
    document.documentElement.setAttribute("data-theme", t);
  })();
</script>
```

This runs synchronously before the first paint, so the user never sees a flash of the wrong theme. The user's preference is also persisted server-side in `UserProfile.theme`; the `POST /accounts/theme/` endpoint syncs the value across devices on next login. The topbar theme toggle writes both `localStorage` and (debounced) the server side.

## 7. Icon system

Phoresis ships a curated subset of [Lucide](https://lucide.dev) (~50 icons) plus 8 custom domain SVGs. All icons are 24×24, `stroke-width="1.5"`, `stroke="currentColor"` so they inherit the surrounding text color and respect both themes for free.

**Custom set:** `gel`, `ladder`, `blot`, `electrophoresis`, `densitometry`, `lane`, `band`, `peak`.

**Sprite location:** `src/phoresis_ui/static/phoresis_ui/icons/lucide.svg` (Lucide subset) and the custom set as discrete files under `src/phoresis_ui/static/phoresis_ui/icons/phoresis/`.

**Usage:**

```django
{% icon "name" size=20 %}
{% icon "band" size=16 class="text-pink-500" %}
```

The `{% icon %}` tag (in `phoresis_ui/templatetags/ui_icons.py`) renders an `<svg>` `<use>` reference from the sprite, sized via `width`/`height` attributes. To add a new icon: drop the SVG into the appropriate sprite, register it in the icon registry, and reference it by name.

## 8. Phoresis app icon

The Phoresis app icon is a gradient lane silhouette overlaid with three horizontal bands tinted at the brand colors (accent blue, gel magenta, MW-ref green). The source vector lives at `assets/icons/phoresis.svg`. Raster outputs (`.ico`, `.png` at 16/32/48/256 px, plus the macOS-style mask SVG used in the Windows shortcut) are generated by `tools/generate_app_icon.py`, which uses Pillow only — no ImageMagick dependency, so it runs as part of `uv run` on a vanilla install.

## 9. Accessibility checklist

- **Focus rings** — `:focus-visible { outline: 2px solid var(--accent-500); outline-offset: 2px; }`. Mouse clicks suppress the ring; keyboard navigation always shows it.
- **Color contrast** — every `--fg` / `--bg` pair, every status color on its background, and every accent fill has been verified against WCAG 2.1 AA in both themes.
- **Keyboard** — `Ctrl+K` opens the command palette anywhere; `Tab` cycles all form fields and interactive chrome in DOM order; `Esc` closes the palette, modals, and the user menu.
- **ARIA** — toast container has `aria-live="polite"`; modals have `role="dialog"` + `aria-modal="true"` (driven by Alpine's `x-show` + `x-transition`); icon-only buttons carry `aria-label`.
- **Color-as-information rule** — every status badge, KPI trend, and band classification has a text or icon affordance in addition to color. A red-green colorblind user can read the entire UI.
- **Reduced motion** — `@media (prefers-reduced-motion: reduce)` neutralizes decorative animations and long transitions. Skeleton shimmer hides; dropzone pulse becomes a steady accent ring; ripple is hidden; theme/sidebar/modal motion collapses to instant. The app remains fully functional with the system "Reduce motion" preference enabled.

## 10. Adding a new component

1. **Define the templatetag** in `src/phoresis_ui/templatetags/ui_components.py`. Use `format_html()` for any caller-supplied arg (it auto-escapes); use `mark_safe()` only for trusted constants the templatetag itself controls.
2. **Add a partial** at `src/phoresis_ui/templates/components/_<name>.html` only if the component needs Django template features (loops, sub-tags, includes). Otherwise inline the HTML in the templatetag — fewer files, faster to read.
3. **Write a test** in `src/phoresis_ui/tests/test_components.py`. Assert the key DOM attributes (variant classes, `aria-*`, role) using `RequestFactory` + `Template().render()`.
4. **Document** the component in this file's §3 catalogue: usage example, variants, accessibility notes.
