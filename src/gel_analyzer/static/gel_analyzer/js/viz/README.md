# GelAnalyzer Viz Layer

A two-layer JavaScript framework for mounting gel-analyzer visualizations **inline** in any host DOM element — CSS-contained, teardown-safe, reusable from a process-dev dashboard or any other page.

## Table of Contents

1. [Two-layer design overview](#1-two-layer-design-overview)
2. [GelAnalyzer.Viz.Panel — base class](#2-gelanalyzervizpanel--base-class)
3. [GelAnalyzer.Viz.mount — generic runtime](#3-gelanalyzervizdmount--generic-runtime)
4. [GelAnalyzer.Viz.Comparison.mount — full comparison wrapper](#4-gelanalyzervizdcomparisonmount--full-comparison-wrapper)
5. [.ga-viz-root CSS containment](#5-ga-viz-root-css-containment)
6. [DRY Django partials](#6-dry-django-partials)
7. [Resolve endpoint and showcase](#7-resolve-endpoint-and-showcase)
8. [Generalization playbook](#8-generalization-playbook)
9. [GelAnalyzer.Viz.BrushZoom — shared zoom gesture](#9-gelanalyzervizbrushzoom--shared-zoom-gesture)

---

## 1. Two-layer design overview

```
Foundation layer
  panel-base.js        GelAnalyzer.Viz.Panel   — base class, lifecycle + tracked teardown
  mount.js             GelAnalyzer.Viz.mount   — generic runtime: builds root, creates panels
  brush-zoom.js        GelAnalyzer.Viz.BrushZoom — the curve panels' shared zoom gesture (§9)
  containment.css      .ga-viz-root            — all:initial CSS boundary

Feature layer (built on top of the foundation)
  sample-comparison-app.js   GelAnalyzer.Viz.Comparison.mount
                               — 6-panel comparison view + dual data-load mode
```

**Goal**: any host page (MDB5, Bootstrap, bare HTML) can mount a gel-analyzer visualization in an empty `<div>` without worrying about CSS bleed-in, global ID conflicts, or memory leaks. The host receives a handle and calls `handle.destroy()` when it no longer needs the component — everything tears down: DOM, event listeners, resize observers, D3 zoom handlers, pending animation frames, and the AbortController that guards in-flight fetches.

---

## 2. `GelAnalyzer.Viz.Panel` — base class

**File**: `gel_analyzer/static/gel_analyzer/js/viz/panel-base.js`

### Constructor

```js
new PanelSubclass({ container, eventBus, state, options, tooltipLayer })
```

| Option | Type | Description |
|---|---|---|
| `container` | `HTMLElement` | The panel's root DOM element (created by `mount` or `App._buildScaffold`). |
| `eventBus` | `EventBus` | Shared bus for cross-panel events. |
| `state` | `*` | Shared reactive state object. |
| `options` | `Object` | View-option overrides (e.g. `poiOnlyMode`, `scaleMode`). Defaults to `{}`. |
| `tooltipLayer` | `HTMLElement\|null` | Positioned `<div>` inside `.ga-viz-root` for floating tooltips; `null` if not provided. |

### Lifecycle methods (override in subclass)

| Method | Called by | Description |
|---|---|---|
| `init()` | `mount` / `App._buildScaffold` after construction | Build DOM, subscribe to events, draw first render. **Never call from the constructor** — subclass class-fields initialize after `super()`, so they would be `undefined` inside a ctor-called `init()`. |
| `render()` | Panel itself, on state changes | Idempotent redraw. Call as many times as needed; should not accumulate side-effects. |
| `destroy()` | `mount` handle / `App.destroy()` | Runs all registered disposers in order, then clears `_disposers`. Tears down everything registered via the tracked helpers. |

### Tracked-teardown helpers

All side-effects registered through these helpers are automatically cleaned up by `destroy()`. Register everything here so that `destroy()` undoes the world completely, enabling repeated mount/unmount cycles without leaks.

| Helper | Signature | Description |
|---|---|---|
| `_on(evt, handler)` | `(string, Function)` | Subscribe to an eventBus event; registers `eventBus.off(evt, handler)` as disposer. |
| `_onWindow(type, handler)` | `(string, Function)` | `window.addEventListener`; registers `removeEventListener` as disposer. |
| `_observe(el, cb)` | `(Element, Function)` | Wraps `new ResizeObserver(cb).observe(el)`; registers `observer.disconnect()` as disposer. Safe no-op if `el` is null/undefined. |
| `_raf(fn)` | `(Function) → id` | One-shot `requestAnimationFrame`; registers `cancelAnimationFrame(id)` as disposer. **Do not call inside a per-render / debounce loop** — each call registers its own cancel. For resize-coalescing patterns, keep a local `id` and call `cancelAnimationFrame` yourself (register one teardown disposer if needed). |
| `_d3zoom(selection)` | `(d3.Selection)` | Registers `selection.on('.zoom', null).on('.brush', null)` as disposer — removes D3 zoom/brush handlers. |
| `_d3interrupt(selection)` | `(d3.Selection)` | Registers `selection.interrupt()` as disposer — stops any running D3 transitions. |

### Example subclass skeleton

```js
class MyPanel extends GelAnalyzer.Viz.Panel {
    constructor(opts) { super(opts); }

    init() {
        this._on('myEvent', (data) => this._handleData(data));
        this._observe(this.container, () => this.render());
        this.render();
    }

    render() {
        // idempotent draw
    }
}
```

---

## 3. `GelAnalyzer.Viz.mount` — generic runtime

**File**: `gel_analyzer/static/gel_analyzer/js/viz/mount.js`

```js
const handle = GelAnalyzer.Viz.mount(containerEl, {
    panelDefs,   // Array<{ name, PanelClass, containerClass, markup? }>
    eventBus,    // optional — created internally if omitted
    state,       // shared state object passed to every panel
    options,     // view-option object passed to every panel
});
```

### What it builds

```
containerEl
  └─ .ga-viz-root           ← CSS containment boundary (containment.css)
       ├─ .ga-viz-tooltip-layer
       ├─ [panelDefs[0].containerClass]  data-ga-panel="name0"
       │     (panelDefs[0].markup injected as innerHTML before Panel construction)
       ├─ [panelDefs[1].containerClass]  data-ga-panel="name1"
       └─ ...
```

### `panelDefs` entry shape

| Field | Required | Description |
|---|---|---|
| `name` | yes | String key; used for `handle.getPanel(name)` and `data-ga-panel` attribute. |
| `PanelClass` | yes | A class extending `GelAnalyzer.Viz.Panel`. |
| `containerClass` | no | CSS class(es) applied to the panel's wrapper `<div>`. |
| `markup` | no | HTML string written into the wrapper **before** the panel is constructed, so `init()` can `querySelector` into expected sub-elements (e.g. `.dm-panel-header`, `.dm-panel-content`). |

### Mounting a single panel or a subset

You can pass a `panelDefs` array with just one entry — or any subset — to embed only what you need:

```js
// Embed just the chromatogram panel in a process-dev dashboard cell:
const handle = GelAnalyzer.Viz.mount(dashboardCell, {
    panelDefs: [{
        name: 'chromatogram',
        PanelClass: SampleComparison.Panels.Chromatogram,
        containerClass: 'dm-panel',
        markup: PANEL_MARKUP.chromatogram,
    }],
    state: myPopulatedState,   // shared state with the data the panel needs
    options: { poiOnlyMode: false },
});
```

This is a first-class use-case: hosts that only need one panel (e.g. only the gel overview, or only the results table) are fully supported by the generic `mount`. The 6-panel `Comparison.mount` is just a convenience wrapper.

### Guards

`mount` throws immediately if:
- `containerEl` is not a DOM element.
- `window.d3` is not loaded.
- `containerEl` is already mounted (detected via `data-ga-viz-mounted="1"` sentinel).

### Transactional rollback

If any panel constructor or `init()` throws, `mount` calls `destroy()` on every panel that succeeded, removes the `.ga-viz-root`, clears the sentinel, and re-throws — leaving `containerEl` exactly as it was.

### Returned handle

| Property / method | Description |
|---|---|
| `handle.destroy()` | Destroys all panels, removes `.ga-viz-root` from the DOM, clears the sentinel, and — if `mount` created the `eventBus` — calls `eventBus.clear()`. |
| `handle.getPanel(name)` | Returns the panel instance by name. |
| `handle.getState()` | Returns the `state` object passed to `mount`. |
| `handle.on(evt, cb)` | Subscribes to the shared `eventBus`. |
| `handle._eventBus` | Direct access to the event bus (use for diagnostics only). |
| `handle._panels` | Direct access to the panels dict (use for diagnostics only). |

---

## 4. `GelAnalyzer.Viz.Comparison.mount` — full comparison wrapper

**File**: `gel_analyzer/static/gel_analyzer/js/sample-comparison/sample-comparison-app.js`

The "all 6 panels + orchestration" convenience wrapper built on top of the foundation. It does not use the generic `GelAnalyzer.Viz.mount` flat loop internally (the comparison needs a 2×2 grid scaffold with resize splitters that the generic mount does not provide), but it honours the same containment and teardown contract.

```js
const handle = GelAnalyzer.Viz.Comparison.mount(containerEl, cfg);
```

### Configuration (`cfg`)

| Field | Mode | Description |
|---|---|---|
| `cfg.samples` | A | Array of already-resolved sample data objects. Hydrated after `init()` via `state.addSample`. |
| `cfg.keys` + `cfg.resolveUrl` | B | Array of opaque string keys (cdw_batch_ids or sample_ids) + the URL of the resolve endpoint. The factory POSTs `{ keys }` to `resolveUrl`, hydrates resolved items, and calls `cfg.onError` for ambiguous/unresolved keys. |
| `cfg.csrfToken` | both | Django CSRF token for POST requests. |
| `cfg.apiUrls` | both | Object with `laneData`, `laneProfile`, `imagesWithDensitometry` URL templates. Defaults via `GelAnalyzer.Viz.Comparison.defaultApiUrls` (published by `_comparison_assets.html`). |
| `cfg.options` | both | Initial view-option overrides (same keys as `handle.setOptions`). |
| `cfg.onError` | both | Callback for resolve errors or mount failures. Defaults to `console.error`. |

### Dual data-load modes

**Mode A — hydrated**: pass `cfg.samples` with pre-fetched item dicts. Used when the host already has the data (e.g. from a server-rendered template or a previous API call).

**Mode B — resolve**: pass `cfg.keys + cfg.resolveUrl`. The factory sends a POST to the resolve endpoint, gets back `{resolved, ambiguous, unresolved}`, hydrates the resolved items, and surfaces any issues via `cfg.onError`.

### Returned handle

| Method | Description |
|---|---|
| `handle.destroy()` | Aborts in-flight fetches (via `AbortController`), destroys all 6 panels, removes `.ga-viz-root`, clears the event bus. |
| `handle.getState()` | Returns the `ComparisonState` instance. |
| `handle.getPanel(name)` | Returns a named panel (`sampleCards`, `gelOverview`, `chromatogram`, `poiPurity`, `bandDetail`, `resultsTable`). |
| `handle.setOptions(partial)` | Updates view options; routes through `state` setters (source of truth). Supported keys: `poiOnlyMode`, `scaleMode`, `xAxisMode`, `normalizationMode`, `mwTolerance`, `digitalLaneMode`. |
| `handle.addSample(sampleData)` | Adds a sample row to the comparison. |
| `handle.removeSample(sampleId)` | Removes a sample by its ID. |
| `handle.on(evt, cb)` | Subscribes to the shared event bus. |

### On-error / failed-mount guard

If `app.init()` throws (double-mount, missing `containerEl`, `d3` not loaded), the factory catches the error, calls `cfg.onError`, and returns an **inert handle** (all methods are no-ops) so the caller's code does not crash.

### The 6 panels and their slots

| Panel name | DOM slot | Nested inside |
|---|---|---|
| `sampleCards` | `.dm-sample-cards` | `.ga-viz-root` (above main grid) |
| `gelOverview` | `.dm-panel.dm-panel-gel-overview` | top row, left |
| `chromatogram` | `.dm-panel.dm-panel-chromatogram` | top row, right |
| `poiPurity` | `#poi-purity-container` | **inside chromatogram slot** (hidden by default) |
| `bandDetail` | `.dm-panel.dm-panel-band-detail` | bottom row, left |
| `resultsTable` | `.dm-panel.dm-panel-results` | bottom row, right |

---

## 5. `.ga-viz-root` CSS containment

**File**: `gel_analyzer/static/gel_analyzer/css/containment.css`

```css
.ga-viz-root {
    all: initial;                /* cuts MDB5/Bootstrap cascade at the boundary */
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 14px;
    line-height: 1.5;
    color: #e2e8f0;
    box-sizing: border-box;
    display: block;
    width: 100%;
    height: 100%;
}
```

`all: initial` resets every inherited CSS property to its browser default, so the host page's MDB5 or Bootstrap Reboot cascade cannot bleed into the component.

The file then applies defensive element resets (for `button`, `input`, `select`, `textarea`, `table`, `svg text`) wrapped in `:where(.ga-viz-root)`. The `:where()` pseudo-class has **specificity zero**, so these resets only neutralise un-styled elements — any component class rule (e.g. `.dm-view-btn`) wins because it has at least `(0,1,0)` specificity. Do not hoist these resets to `.ga-viz-root button` (specificity `(0,1,1)`) as that would beat the panels' own button styling and collapse padding/border.

The `.ga-viz-tooltip-layer` lives inside `.ga-viz-root` so it is CSS-contained and torn down automatically when the host calls `handle.destroy()`.

---

## 6. DRY Django partials

Three Django template partials under `gel_analyzer/templates/gel_analyzer/viz/`:

### `_foundation_assets.html`

Loads the minimal foundation needed for **any** `GelAnalyzer.Viz` component:
- D3.js (CDN)
- `core/event-bus.js`
- Shared utilities: `api-error.js`, `auto-save.js`, `chromatogram-utils.js`, `mw-utils.js`, `panel-splitter.js`
- `viz/panel-base.js`, `viz/mount.js` and `viz/brush-zoom.js`

Include this (or have `_comparison_assets.html` include it transitively) on any page that mounts a Viz component.

### `_comparison_assets.html`

Includes `_foundation_assets.html` transitively, then loads all comparison-specific scripts in dependency order:
- `sample-comparison-state.js`, `sample-comparison-api.js`, `mw-utils.js`, `comparison-metrics.js`
- `drag-reorder.js`
- Six panel scripts (`sample-cards-panel.js`, `gel-overview-panel.js`, `chromatogram-panel.js`, `poi-purity-panel.js`, `band-detail-panel.js`, `results-table-panel.js`)
- `sample-comparison-app.js` (orchestrator + `Viz.Comparison.mount` factory)
- `comparison-page-chrome.js` (wires the host template's header, modals, splitters, magnifier to the handle)

Also publishes `window.GelAnalyzer.Viz.Comparison.defaultApiUrls` — a pre-resolved object with `laneData`, `laneProfile`, and `imagesWithDensitometry` URL templates. Hosts that cannot call `{% url %}` themselves (e.g. cross-app embeds) use this as their `cfg.apiUrls` fallback.

### `_comparison_styles.html`

Loads the three CSS files needed for the comparison component:
- `densitometry.css` — shared `.dm-*` panel/dark-theme chrome (reused from the densitometry view)
- `comparison.css` — comparison-specific layout, sample cards, results table
- `containment.css` — `.ga-viz-root` CSS boundary

---

## 7. Resolve endpoint and showcase

### `comparisons/resolve/` endpoint

**URL name**: `gel_analyzer:api_comparison_resolve`
**Method**: POST
**Auth**: `@login_required`
**View**: `gel_analyzer/views/comparison.py::resolve_comparison_samples`
**Service**: `gel_analyzer/services/comparison_resolve.py::resolve_samples_to_items`

Accepts `{ "keys": ["key1", "key2", ...] }` where each key is an opaque string (cdw_batch_id or sample_id). For each key:

1. Try `ProcessSample.cdw_batch_id` exact match (priority).
2. Fall back to `ProcessSample.sample_id` exact match.

Returns three buckets:

```json
{
    "resolved": [ { /* item dict — same shape as resolve_samples_to_items output */ } ],
    "ambiguous": [ { "key": "...", "candidates": [pk1, pk2] } ],
    "unresolved": [ "key_that_matched_nothing" ]
}
```

`Comparison.mount` Mode B posts to this endpoint and routes the response accordingly.

### Showcase page

**URL**: `/viz/showcase/`
**URL name**: `gel_analyzer:viz_showcase`
**View**: `gel_analyzer/views/comparison.py::viz_showcase_view`
**Template**: `gel_analyzer/templates/gel_analyzer/viz/showcase.html`

A developer/demo page that proves, in a single page load on an MDB5 host:

1. **Inline mount**: `GelAnalyzer.Viz.Comparison.mount` mounts into a host `<div>` on an MDB5 page without CSS bleed-in.
2. **CSS containment**: `.ga-viz-root` boundary isolates the component from Bootstrap Reboot.
3. **Mode B resolve**: the showcase enters comma-separated cdw_batch_id/sample_id keys, posts to `comparisons/resolve/`, and hydrates the resolved items.
4. **Clean teardown**: `handle.destroy()` removes all DOM and resets the sentinel — the host `<div>` can be remounted with no leak.

The showcase deliberately does **not** include `comparison-page-chrome.js` and wires its own minimal host controls directly to the handle (mount/unmount buttons, POI-only toggle). This demonstrates that the component handle is the only public surface the host needs.

---

## 8. Generalization playbook

Apply this pattern to another app or feature (e.g. `cps_parser`, `dls_parser`, mass-balance charts):

> **Status:** ported to `cps_parser` (PR #115, `.cpc-viz-root`, `CPSComparison.Viz.Comparison.mount`) and `dls_parser` (PR #116, `.dlc-viz-root`, `DLSComparison.Viz.Comparison.mount`); also applied net-new to `process_development` chromatogram comparison (`UnicornComparison`, `.ucc-viz-root`, June 2026 — no pre-existing view ported). Both reuse this foundation transitively via their own `_foundation_assets.html` and add a `comparisons/resolve/` endpoint (cdw_batch_id → sample_id fallback). See `dls_parser/README.md#viz-layer-inline-mount` for a worked example.

### Step-by-step

**a. Reuse the foundation — do not re-invent it**

Include `_foundation_assets.html` to get D3, EventBus, `GelAnalyzer.Viz.Panel`, and `GelAnalyzer.Viz.mount`. Copy `containment.css` (or `{% include %}` it) and rename the boundary class (e.g. `.mb-viz-root`) if you need a separate containment scope for a different app.

**b. Build each panel as a `GelAnalyzer.Viz.Panel` subclass**

```js
class MyChartPanel extends GelAnalyzer.Viz.Panel {
    constructor(opts) { super(opts); }
    init() {
        this._observe(this.container, () => this.render());
        this._on('dataUpdated', () => this.render());
    }
    render() { /* D3 draw */ }
}
```

Route **every** side-effect through `_on`, `_onWindow`, `_observe`, `_raf`, `_d3zoom`, `_d3interrupt`. Raw `addEventListener` calls outside these helpers will leak on unmount.

**c. Container-scope the panel — no global IDs**

Use `this.container.querySelector(...)` not `document.getElementById(...)`. If the panel needs sub-elements, pass their markup in `panelDef.markup` so `mount` injects them before `init()` runs.

**d. Build a skeleton (or supply `markup` per panelDef)**

For a simple flat layout, let `GelAnalyzer.Viz.mount` build the skeleton:

```js
const handle = GelAnalyzer.Viz.mount(hostEl, {
    panelDefs: [
        { name: 'chart', PanelClass: MbChartPanel, containerClass: 'mb-chart-panel' },
        { name: 'table', PanelClass: MbTablePanel, containerClass: 'mb-table-panel' },
    ],
    state: myState,
    options: {},
});
```

For complex layouts (e.g. the comparison 2×2 grid with resize splitters), build your own scaffold in an `App` class that follows the same `init()` / `destroy()` / sentinel contract as `SampleComparisonApp`.

**e. Expose a `<App>.Viz.<Feature>.mount()` wrapper returning a handle**

```js
function mountMassBalance(containerEl, cfg) {
    const app = new MassBalanceApp({ containerEl, ...cfg });
    app.init();
    return {
        destroy: () => app.destroy(),
        getPanel: (n) => app.panels[n],
        // ...
    };
}
window.MassBalance = window.MassBalance || {};
window.MassBalance.Viz = window.MassBalance.Viz || {};
window.MassBalance.Viz.mount = mountMassBalance;
```

### Single-panel embedding is first-class

Any host can embed just one panel — pass a one-entry `panelDefs` and a `state` pre-populated with the data that panel reads. This is the primary path for embedding a single chart in a process-dev dashboard cell without pulling in the full comparison orchestration layer.

### Containment checklist for a new app

- [ ] CSS boundary class (`all: initial`) in your containment CSS, mirroring `containment.css`.
- [ ] All event listeners go through the tracked helpers.
- [ ] No `document.getElementById` inside panels (use `this.container.querySelector`).
- [ ] `handle.destroy()` leaves `containerEl` in exactly the same state as before mount (double-check the `data-ga-viz-mounted` sentinel is cleared).
- [ ] Test a mount → interact → destroy → remount cycle in the browser before shipping.

---

## 9. `GelAnalyzer.Viz.BrushZoom` — shared zoom gesture

**File**: `gel_analyzer/static/gel_analyzer/js/viz/brush-zoom.js` (loaded by `_foundation_assets.html`; the legacy `/cps-parser/compare/` page, which has no foundation, loads it on its own).

One gesture for every curve panel: brush a range on X, Y re-fits to what the window shows, and a double-click on the plot or the **Reset zoom** badge brings the full view back. Used by the CPS distribution and sedimentation panels and the DLS comparison distribution panel.

| Function | What it does |
|---|---|
| `attachX(layer, opts)` | `d3.brushX` on `layer` (a `<g>` in plot coordinates, appended **after** the traces), the hover on the brush's own `.overlay`, the badge (a "Drag to zoom" hint on hover, "↺ Reset zoom" while zoomed) and `guard()` on the SVG. `opts`: `xScale, width, height, zoomed, onZoom([x0, x1]), onReset(), onHover(event, mx), onLeave()`. |
| `fitY(values, zeroBased)` | Y domain for the window from the Y of the points inside it; `null` when nothing is visible. |
| `guard(el)` | Stops `mousedown` / `pointerdown` / `touchstart` from bubbling to a host drag handler, and sets `user-select: none`. |

Three rules the panels follow:

- **The window lives in DATA units on the panel** (`this._zoomX`), and `_draw()` rebuilds from it. A resize, a mode switch or a full remount draws the same window again. There are no transitions and no `xScale.domain()` mutation in place.
- **No hover `<rect>` on top of the brush.** It swallows every `mousedown`, so the brush never starts. The CPS and DLS brushes were dead that way until 2026-09-25.
- **d3's brush stops propagation only when the gesture ENDS.** Without `guard()`, the press also starts a PD dashboard tile drag, because Gridstack listens on `.grid-stack-item-content`.

**Host channel (PD dashboard).** A tile passes `options.zoom = { view, onChange }` to `GelAnalyzer.Viz.mount`:
- `view` is `{ x: [a, b], y: null }` or `null`, and the panel starts from it;
- `onChange(view)` reports every zoom and reset.

The dashboard keeps it in `node.cfg.view`, so a theme or style remount restores the zoom. `saveCB` leaves it out of the saved board, and a new step or sheet selection clears it. Standalone pages pass nothing and the panel keeps its window to itself.

## SampleLaneGel — one gel, one lane put forward

`js/viz/sample-lane-gel.js` + `css/sample-lane-gel.css`: `GelAnalyzer.Viz.SampleLaneGel.mount(el, {entry, dimOthers, bandOverlay})`
→ `{update(opts), destroy()}`. Read-only: the whole gel (display file through `api_image_proxy`), every lane
outlined, a veil over everything but the entry's lane, its bands, its `L<n>` pill, the kDa axis of the nearest
ladder calibration and the lane's stored profile on the same y scale — one SVG in image-pixel space. A lane is
read by its outline (Rule 2, `gel_analyzer/CLAUDE.md`): each item of `entry.lanes` carries the server's `outline`
(`shape.outline_of`), read through `GelAnalyzer.LaneGeometry.outlineOfPayload` (`js/shared/lane-geometry.js`, which
the host loads first — `gel_analyzer/viz/_foundation_assets.html` does). The lane number sits over the middle of
the outline's top row, the pill under the middle of its bottom row (`LaneGeometry.bottomCentre`), and a band with no
box is the outline cut at its rows (`LaneGeometry.slice`); band boxes are drawn as stored, as on the densitometry
page. `entry` is one item of
`GET /api/samples/<pk>/gels/` (`services/sample_gels.py`). Colours are `--slg-*` custom
properties the host maps (first host: the process-dev sample page, `process_development/css/sample_detail.css`).

The photo is drawn once per entry (the image proxy answers `no-cache`): the slab, the `<image>` and the viewBox are a
base layer built once, and `update()` / `dsh:themechange` redraw only the overlay `<g>` (lanes, veil, bands, outline,
pill, axis, profile). Without the display file's `width` and `height` the photo is not drawn at all — lane coordinates are
display-file pixels, and a stretched photo would put the overlay beside the real bands — and the slab carries an
"image size unknown" note instead.

## LaneStrips — the samples' lanes side by side on one kDa axis

`js/viz/lane-strips.js` + `css/lane-strips.css`: `GelAnalyzer.Viz.LaneStrips.mount(el, {strips, kind, showProfiles, eventBus})`
→ `{update(opts), destroy()}`. Read-only. Spec: `docs/superpowers/specs/2026-10-11-sample-comparison-design.md` §3.
First host: the process-dev sample comparison page (`process_development/js/sample-compare/scmp-gel.js`).

| Option | Description |
|---|---|
| `strips` | `[{key, color, label, entry}]`, one column each, in this order. `entry` is one item of `GET /api/samples/<pk>/gels/` (`services/sample_gels.py`); `color` is the sample's resolved hex; `label` its short name (the host puts the ★ in it). |
| `kind` | The assay shown, for the accessible name only: the host chooses each strip's entry. |
| `showProfiles` | The profile panel (default on). |
| `eventBus` | A `GelAnalyzer.Core.EventBus`. Hovering or focusing a strip, its foot or its profile emits `'sample:highlight'` `{key}` (`null` on leave); the panel dims every other strip on the same event, whoever emits it. |

`update(opts)` merges options and redraws (new `strips` after a theme switch: their colours). The host loads the gel
foundation first (`gel_analyzer/viz/_foundation_assets.html`: d3, `LaneGeometry`, `Viz`).

**The axis.** log10(kDa), top = high MW. A strip's `mw_ticks` (the band rows of the ladder nearest its lane) are
normalised first: ticks on one image row merge, or are both dropped when their kDa differ; then the longest
subsequence, in row order, of strictly decreasing kDa is kept, so a tick out of order costs that tick alone (equal
lengths: the widest kDa range wins, then the lowest y of the first tick). Between two kept ticks the lane's rows map
linearly onto the axis, so every ladder band lands on its kDa in every strip. The range is the union of the strips'
calibrated ranges; the labels are the standard ladder values inside it, a label dropped when it would collide. The
rows above the top tick and below the bottom one keep the strip's mean scale and sit in hatched "above ladder" /
"below ladder" bands, each as tall as the tallest strip's outside part. When the two bands would together exceed the
axis's own height (one inconsistent ladder), the outside scale of each strip is capped at one common value, found by
bisection so that the bands fit exactly (`outScale = min(mean, cap)`): the strip with the degenerate ladder is
compressed, the consistent strips keep their own scale unless the budget is too small for them too. Never clipped, so
an aggregate above the ladder stays visible. A band's name goes in the gutter beside the kDa labels: both lines when
they fit inside the band clear of every label, else the first word on one line, else nothing (the hatching and its
tooltip remain). The axis labels are integers (`10`, `50`); the POI mark's tooltip and the SVG's `aria-label` print
a molecular weight as the sample page's gel tile does: no decimal from 100 kDa, else one (`POI · 50.0 kDa`). This is
the rule of the sample page's kDa ticks, not Gel Analyzer's fitted curve: a band's `estimated_mw_kda` (in the POI
mark's tooltip) can differ by a few %.

**Drawing.** One `<image>` per URL in a `<defs>`, created once for the mount's life (a URL → element map: the image
proxy answers `no-cache`, so a redraw never re-creates it). Each segment of a strip (between two ticks, or outside
them) is a nested `<svg>` whose `viewBox` is the segment's rows over the outline's outer box
(`LaneGeometry.outerBox`), holding a `<use>` of the image clipped by the lane's outline
(`LaneGeometry.outlineOfPayload`, one `<clipPath>` per strip; Rule 2, `gel_analyzer/CLAUDE.md`). Adjacent segments
overlap by 0.5 px against hairline seams. A tilted lane keeps its slant in its column; a straight tilted edge kinks
slightly between segments of different scale. No `image.url` or no known size: a slab reading "no image" (the
profile is still drawn). An image that fails to load, or a strip whose lane is missing from `entry.lanes`, is
named in the list under the strips; the others draw.

**Under the strips (HTML, never in the SVG):** the lane's readout (its purity, or the readout's state),
"L&lt;n&gt; · &lt;gel&gt;" linking to the analysis, and its notes ("matrix value from another source; showing L&lt;n&gt; of
&lt;gel&gt;" when the sample's official row sits elsewhere). In a column narrower than 56 px the link shows "L&lt;n&gt;"
and the notes move to the list.

**No usable calibration** (under 2 ticks after normalisation): the strip goes to a group titled "No kDa calibration —
aligned by lane top/bottom", from its outline's top to its bottom, with its own small profile beside it and the
reason ("no ladder calibration" / "ladder ticks out of order") under it. Westerns usually land here.

**Profiles.** One line per strip in its colour, y through the strip's own map (out-of-ladder rows included), x the
intensity over that profile's maximum within the drawn rows; a gap in `y` (a polygon lane) breaks the line. Under
480 px the panel moves under the strips.

**Redraws.** `render()` redraws everything but the images: on `update()`, on a change of the container's width
(ResizeObserver: a tile drawn hidden draws when shown) and on `dsh:themechange`. Colours are `--ga-lst-*` custom
properties, night on `:root` and day on `:root[data-theme="light"]` (`.ga-viz-root` resets `color`); a sample's
colour is set inline, since a presentation attribute loses to `containment.css`'s `svg text { fill: currentColor }`.

**Checks in the browser.** No Django test loads this file. Its pure helpers are exposed for crafted payloads in the
console: `LaneStrips._normalizeTicks(ticks)` → `{ticks: [{y, mw_kda}], reason}`,
`LaneStrips._segments(ticks, outline)` → `[{kind: 'above' | 'ladder' | 'below', y0, y1, …}]` and
`LaneStrips._buildAxis(strips)` → `{kTop, kBot, unit, above, below, cap, capped}`, each strip `{ticks, top, bottom}` (it
sets each strip's `mean` and `outScale`), `LaneStrips._drawFrame(svg, f, x0, x1)` (the gutter and the bands) and
`LaneStrips._formatKda(value)`.
