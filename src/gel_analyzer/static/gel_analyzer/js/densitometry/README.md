# Densitometry Module

Quantitative analysis module for gel electrophoresis images. Provides Gaussian peak fitting, integration, normalization, and purity calculations.

## Architecture

### Backend

```
gel_analyzer/
├── models/
│   └── densitometry.py          # Django models
├── services/
│   └── densitometry/
│       ├── __init__.py              # Module exports
│       ├── models.py                # Dataclasses (params, results)
│       ├── service.py               # Main orchestrator
│       ├── advanced_peak_detector.py # Peak detection in profiles
│       ├── peak_deconvolution.py    # Multi-Gaussian deconvolution
│       ├── peak_integrator.py       # Gaussian fitting
│       ├── peak_matching.py         # Match peaks to existing bands
│       ├── normalizer.py            # Relative quantification
│       ├── purity_calculator.py     # Purity metrics
│       └── export.py                # CSV export
├── views/
│   ├── densitometry.py          # Main view
│   └── densitometry_api.py      # REST API endpoints
└── tasks.py                     # Celery tasks (extended)
```

### Frontend

```
static/gel_analyzer/js/densitometry/
├── densitometry-event-bus.js    # PubSub events
├── densitometry-state.js        # State management
├── densitometry-api-client.js   # API communication
├── densitometry-app.js          # Main orchestrator
└── panels/
    ├── gel-overview-panel.js    # Gel image with selection
    ├── chromatogram-panel.js    # D3.js electropherogram
    ├── band-zoom-panel.js       # Band detail + digital lane
    ├── results-table-panel.js   # Measurements › Bands: one row per band
    ├── lanes-view.js            # Measurements › Lanes: one row per lane, the gel's readout columns
    └── readout-panel.js         # Western readout chart (Variants / HCP vs reference tab)

static/gel_analyzer/js/shared/workbench-summary.js   # Summary strip + "⋯" menu of the workbench header
static/gel_analyzer/css/ga-workbench.css             # .ga-wb-* chrome and its night/day tokens
templates/gel_analyzer/workbench/_identity.html      # Header identity row: crumbs, status, assay, views, help, theme
```

## UI Layout

```
┌─────────────────────┬──────────────────────────────────┐
│   GEL OVERVIEW      │   ELECTROPHEROGRAM               │
│   (Interactive)     │   (Intensity vs Position/MW)     │
│                     │   - D3.js interactive chart      │
│   Click to select   │   - Background toggle (rescales) │
│   lanes/bands       │   - Peak highlighting, zoom/pan  │
├─────────────────────┼──────────────────────────────────┤
│   BAND DETAIL       │   MEASUREMENTS TABLE             │
│   - Zoomed view     │   - Sortable columns             │
│   - Digital lane    │   - Absolute intensities         │
│     (2 modes)       │   - Relative % (lane/gel)        │
│                     │   - Purity calculations          │
└─────────────────────┴──────────────────────────────────┘
```

### Panel contracts

| Panel | File | DOM root | Inputs from state | Outputs (events) |
|---|---|---|---|---|
| Gel Overview | `panels/gel-overview-panel.js` | `.dm-panel-gel-overview` | `state.lanes`, `state.bands`, `state.activeLaneId`, `state.activeBandId` | `LANE_SELECTED`, `BAND_SELECTED`, `BAND_HOVERED` |
| Electropherogram | `panels/chromatogram-panel.js` | `.dm-panel-chromatogram` | `state.profileData`, `state.bands`, calibration data | `PEAK_CLICKED`, `PEAK_HOVERED`, `ZOOM_CHANGED` |
| Band Detail | `panels/band-zoom-panel.js` | `.dm-panel-band-detail` | `state.activeLaneId`, `state.bands`, digital-lane mode | `DIGITAL_LANE_MODE_CHANGED` |
| Results Table | `panels/results-table-panel.js` | `.dm-panel-table` | `state.densitometryResults`, sort/filter | `TABLE_ROW_SELECTED`, `EXPORT_STARTED` |
| Readout chart (the Variants / HCP vs reference tab of the Graphical View, western assays only) | `panels/readout-panel.js` | `#dm-readout-container` | `state.readoutAssay`, `state.readouts`, `state.readoutReferenceLaneNumber` (filled by `state.setReadouts`) | — (redraws on `READOUTS_UPDATED`) |
| Lanes view (Measurements › Lanes; Bands = the Results Table) | `panels/lanes-view.js` | inside `#results-table-panel`, plus the phone's `#dm-lane-picker` | `state.pageSummary` (`columns`, `rows`, `readout`), `state.selectedLaneId` | `state.selectLane(id)` on a row / chip click; redraws on `PAGE_SUMMARY_UPDATED`, marks on `LANE_SELECTED`. Lanes \| Bands kept in `localStorage['gelDensitometryMeasurementsView']` |
| Summary strip (header) | `shared/workbench-summary.js` | `#ga-wb-summary` | the page summary payload (`cards`, `checks`, `next_step`, `hint`) | — (re-rendered by `densitometry.html` on `PAGE_SUMMARY_UPDATED`) |

A single global manager (`Densitometry.App`) owns the state and event bus; panels are dumb renderers that subscribe to events and call `app.selectLane(id)` / `app.selectBand(id)` upstream.

### Western readout (anti-HCP / protein of interest variants)

- **Values are the server's.** `GET /densitometry/` carries `assay`, `readout_reference_lane_id`, `reference_lane_number`, `can_write`, `is_editable` and `readouts` (one entry per SAMPLE lane plus the HCP reference lane: `lane_id`, `lane_number`, `lane_type`, `sample_name`, `values` or null, `reason`, `is_reference`), computed by `services/readout_publisher.py::lane_readouts` through `_lane_values`, the function that publishes them to Process Development. `readouts` is null when that computation failed (logged). The JS formats, it never computes a readout.
- **HCP reference select** (`#hcp-reference-select`, header): server-rendered by `views/densitometry.py` for an anti-HCP assay (options = SAMPLE + CONTROL lanes + the current reference, labels from the view), disabled for a reader or a locked analysis. `App._onReferenceLaneChange` → `ApiClient.setReadoutReferenceLane` (`POST /api/analyses/<uuid>/readout-reference/`) → `refreshReadouts()` re-fetches and applies ONLY the readout block (`state.setReadouts` → `READOUTS_UPDATED`) — never `state.loadResults`, which re-renders every panel.
- **REF**: the gel overview outlines the reference lane in amber and tags it under `L{n}`, inside the lane (`state.getHcpReferenceLaneId()`, redrawn on `READOUTS_UPDATED`); the readout chart, the Lanes view and the lane picker carry `.ga-wb-ref`.

### Page summary and band roles (one composition with the analysis page)

- **`page_summary`**: the page and `GET /densitometry/` carry the same block, `services/analysis_detail.py::summary_payload(page_summary(...))` — the composition behind `analyses/detail.html` (readout, `columns` + per-lane `rows` with each cell's text, tone or reason and the sample's `sample_url` — its Process Development identity card, null for a free-text name; the Lanes view and the analysis page's cards link the name with it, in the same tab —, `cards`, `checks`, `next_step`, `hint`). Text, numbers and booleans only: the view writes it with `script_json` into the page's `const pageSummary`, handed to the App, and `quant_calibration_info` (it holds a datetime) never reaches it. The JS renders it, never recomputes it. A run, a reference change or a quantification save re-fetches it: `state.setReadouts(payload)` → `state.setPageSummary(payload.page_summary)` → `PAGE_SUMMARY_UPDATED`. In the GET, `page_summary` is null when the composition failed (logged): the refresh then keeps the summary the page had. The page itself composes it as the analysis page does, unguarded.
- **`role` per band** (`lanes[].bands[].role` of the GET, copied to `band.role` by `state.loadResults`): `aggregate` / `main` / `clipping` (shown as HMWS / main band / LMWS) on an anti-molecule western, `hcp` / `left_out` on an anti-HCP one, null elsewhere — from `analysis_detail.band_role_map`, which calls `readouts.band_roles`, the classification `protein_variants` publishes with. Only lanes that carry a western value get roles (SAMPLE lanes and the HCP reference). The electropherogram, the band zoom, the gel overview and the 3D view colour a band by its role, never by a position test of their own.
- **Theme**: the page is night/day (`dsh-theme`, `localStorage['dshub-theme']`). The canvas and D3 panels read their colours from CSS tokens and redraw on `dsh:themechange`; a listener added on `document` is removed in `dispose()`.
- `ChromatogramPanel._createChart` re-appends `.dm-readout-container` like the other sub-view containers: a sub-view container it does not list is wiped by the next chart rebuild.

### D3.js electropherogram structure

The chromatogram panel follows the standard D3 enter/update/exit datajoin pattern:

```javascript
// Scale construction
const yScale = d3.scaleLinear()
    .domain([profile.yMin, profile.yMax])   // image pixel Y (top to bottom)
    .range([0, chartHeight]);

const xScale = d3.scaleLinear()
    .domain([0, intensityMax])               // linear by default
    .range([0, chartWidth]);
// Log mode: d3.scaleLog().domain([1, intensityMax]).range([0, chartWidth])

// Line generator
const line = d3.line()
    .x(d => xScale(d.intensity))
    .y(d => yScale(d.y));

// Datajoin for peak markers (e025e98e commit)
const peakMarkers = svg.selectAll('.dm-peak-marker')
    .data(state.bands, d => d.id);  // key fn for stable identity

peakMarkers.enter().append('line')
    .attr('class', 'dm-peak-marker')
    .merge(peakMarkers)
    .attr('y1', d => yScale(d.densitometry.peak_center_y))
    .attr('y2', d => yScale(d.densitometry.peak_center_y))
    .attr('x1', 0).attr('x2', chartWidth);

peakMarkers.exit().remove();
```

Vertical axis is image-pixel Y, drawn top-to-bottom to match the gel. When MW calibration is available, a second Y axis renders the log10 MW scale on the right (see `shared/mw-utils.js::renderMWAxis`).

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/analyses/<uuid>/densitometry/` | GET | Get stored results |
| `/api/analyses/<uuid>/densitometry/run/` | POST | Run sync (preview) |
| `/api/analyses/<uuid>/densitometry/async/` | POST | Run async (Celery) |
| `/api/analyses/<uuid>/densitometry/jobs/<job_id>/` | GET | Job status |
| `/api/lanes/<int>/profile/` | GET | Lane intensity profile |
| `/api/lanes/<int>/densitometry/` | GET | Lane summary |
| `/api/bands/<uuid>/densitometry/` | GET | Band details |
| `/api/analyses/<uuid>/densitometry/export/` | POST | Export CSV |
| `/api/analyses/<uuid>/readout-reference/` | POST | Set / clear the anti-HCP reference lane (`{"lane_id": int\|null}`), republishes the readouts |

## Async Job Tracking

Densitometry analysis runs via Celery with `DensitometryJob` model tracking:

```
Client clicks "Run Analysis"
  → POST /densitometry/async/  (creates DensitometryJob + Celery task)
  → Returns { job_id, task_id }
  → Client polls GET /densitometry/jobs/<job_id>/  every 1s
  → Task updates job.progress (0-100%)
  → Task marks job COMPLETED → client loads fresh results
```

**Race condition fix**: The view passes `job_id` to the Celery task so it finds the job by PK (not by `task_id`), avoiding a race where the warm worker starts before `task_id` is saved.

**Fallback**: Client-side polling also checks `celery_status === 'SUCCESS'` with `progress >= 100` to force completion if the DB status lags.

### Polling pattern

```javascript
async function pollJob(jobId) {
    const url = `/api/analyses/${analysisId}/densitometry/jobs/${jobId}/`;
    while (true) {
        const job = await fetch(url).then(r => r.json());
        eventBus.emit(Events.ANALYSIS_PROGRESS, { progress: job.progress });
        if (job.status === 'COMPLETED' || job.status === 'FAILED' || job.status === 'CANCELLED') {
            return job;
        }
        await new Promise(r => setTimeout(r, 2000));  // 2-second poll interval
    }
}
```

- Interval: **2 s** while `RUNNING` or `PENDING`. Stop on terminal status (`COMPLETED`, `FAILED`, `CANCELLED`).
- The polling is run by the `Densitometry.App` after a successful POST to `/densitometry/async/`. The button is disabled and a progress bar is rendered while polling is active.
- On `COMPLETED`, the app re-fetches `/densitometry/` to load the persisted `DensitometryResult` rows, then emits `ANALYSIS_COMPLETED` so all panels refresh from `state`.

## CSV export contract

Backend endpoint: `POST /api/analyses/<uuid>/densitometry/export/`, answered in the request (the page sends `async: false`). It reads the SAVED densitometry -- `DensitometryResult`, `LaneDensitometrySummary`, the last completed `DensitometryJob.params` -- and measures nothing: `services/densitometry/export.py::export_saved_csv`, the one function the endpoint and `export_densitometry_csv_task` call. No saved densitometry answers 409 `detail` "Run the densitometry first: ...", which `DensitometryApiClient.exportCSV` throws for the page's *Export failed* message.

The blocks, the columns and their order: the user guide, `gel_analyzer/docs/user/06-densitometry.md` -> *CSV export* (Lane Summary and Band Details tables). Column order and names do not change: Excel pivots and lab notebooks read them by position.

## MDB5-free constraint (CRITICAL)

The densitometry view (`densitometry.html`) extends `_ga_base_minimal.html` and **must remain MDB5-free**. See agent memory `MDB5-free views` in CLAUDE.md.

| Don't | Do |
|---|---|
| `mdb.Modal(elem)` | Custom modal with `display: none/block` and `.dm-magnify-overlay` styles |
| `data-mdb-toggle`, `data-mdb-target` | Native event listeners (`addEventListener('click', ...)`) |
| `bootstrap.Dropdown` | Vanilla menu with click-outside-to-close |
| `$()` (jQuery) | `document.querySelector()` / `document.querySelectorAll()` |
| MDB5 form components | Native `<input>` + `.dm-input` CSS |

Use `.dm-*` CSS prefix for all densitometry-specific styles. Shared utilities live in `js/shared/` (no DOM dependency).

## Coordinated state between JS and `densitometry.html`

`densitometry.html` exposes initial data through three channels:

1. **`data-*` attributes** on the root container `<div class="dm-app" data-analysis-id="..." data-csrf-token="..." data-can-edit="true">`. Read at init time only — never written back from JS.
2. **JSON islands** for initial lanes/bands payload:
    ```html
    <script id="initial-lanes" type="application/json">{{ lanes_json|safe }}</script>
    <script id="initial-bands" type="application/json">{{ bands_json|safe }}</script>
    ```
    Parsed once in `Densitometry.App.init()` and seeded into `state`.
3. **Server-rendered HTML scaffolding** for panel containers, header buttons, and the magnify overlay. JS hydrates these — it does not generate them from scratch.

All runtime state lives in the single `Densitometry.State` class. Panels never read DOM directly for state — they query `app.state.getActiveLane()` etc.

## Background Toggle

The electropherogram panel has a background visibility toggle (`bi-layers-half` button):

- **Background shown** (default): Y-axis scales to `max(correctedSignal, background)` — full context
- **Background hidden**: Y-axis rescales to corrected signal only — better peak visibility when background is large

The toggle calls `_renderProfile()` which recalculates `yScale.domain()` and redraws all chart elements.

## Events

```javascript
// Lane/Band selection
Events.LANE_SELECTED
Events.BAND_SELECTED
Events.BAND_HOVERED
Events.BAND_TYPE_CHANGED

// Analysis lifecycle
Events.ANALYSIS_STARTED
Events.ANALYSIS_PROGRESS
Events.ANALYSIS_COMPLETED
Events.ANALYSIS_ERROR
Events.ANALYSIS_OPTIONS_SELECTED

// Peak detection (auto-detection from profile)
Events.PEAKS_DETECTION_STARTED
Events.PEAKS_DETECTED
Events.PEAKS_DETECTION_ERROR
Events.ORPHAN_PEAK_CLICKED
Events.BANDS_CREATED

// Data events
Events.DATA_LOADED
Events.DATA_UPDATED
Events.PROFILE_LOADED
Events.READOUTS_UPDATED   // western readout block refreshed (state.setReadouts)
Events.PAGE_SUMMARY_UPDATED   // page summary refreshed (state.setPageSummary): Lanes view, summary strip, POI Purity
Events.QUANT_CALIBRATION_CHANGED   // quantification saved: the app re-fetches the readouts and the page summary

// Chart events
Events.PEAK_CLICKED
Events.PEAK_HOVERED
Events.ZOOM_CHANGED
Events.CHART_READY
Events.CHART_UPDATED

// View events
Events.VIEW_MODE_CHANGED
Events.DIGITAL_LANE_MODE_CHANGED
Events.IMAGE_ADJUSTED
Events.IMAGE_RESET

// Table events
Events.TABLE_ROW_SELECTED
Events.TABLE_SORT_CHANGED

// Export events
Events.EXPORT_STARTED
Events.EXPORT_COMPLETED
Events.EXPORT_ERROR

// Settings events
Events.PARAMS_CHANGED
Events.NORMALIZATION_CHANGED
```

## Usage

### Backend

```python
from gel_analyzer.services.densitometry import (
    DensitometryService,
    DensitometryParams,
)

# Create service with parameters
params = DensitometryParams(
    gaussian_fit_enabled=True,
    normalization_method='lane_total',
)
service = DensitometryService(params)

# Analyze (preview mode)
result = service.analyze_analysis(analysis, image)

# Analyze and save to database
result = service.analyze_and_save(analysis, image, user)
```

### Frontend

```javascript
// Initialize app
const app = new Densitometry.App({
    analysisId: '...',
    csrfToken: '...',
    lanes: [...],
    bands: [...],
});

await app.init();

// Select a lane programmatically
app.selectLane(laneId);

// Subscribe to events
app.eventBus.on(Densitometry.Events.BAND_SELECTED, (data) => {
    console.log('Band selected:', data.bandId);
});
```

## Normalization Methods

1. **LANE_TOTAL**: Each band as percentage of lane total area
2. **LOADING_CONTROL**: Relative to the MW_REFERENCE bands of its lane; the run is refused when a lane with bands has none carrying signal (the job ends FAILED, its `error_message` naming the lanes)

`relative_percent_gel` (share of the whole gel) is computed for every method. `gel_total` and `reference_band` were removed on 2026-10-05: posting them is a 400 naming why. The results table's `% lane` column is computed client-side as the lane-total share whatever the method; the chromatogram and band zoom show the stored `relative_percent_lane`.

## Purity Calculation

```
Purity (%) = POI_Area / (POI_Area + OTHER_Area) × 100
```

MW_REFERENCE bands are excluded from purity calculations.

## Digital Lane Modes

### Bands Mode

Horizontal rectangles with intensity-based coloring (Agilent Bioanalyzer style):
- Band width proportional to container
- Intensity-based opacity
- Color coding by band type (POI, OTHER, MW_REFERENCE)

### Pseudo-Gel Mode

Gradient rendering simulating gel appearance with **logarithmic intensity scale**:

```javascript
// Logarithmic scale: maps 0-100% to 0.3-1.0 range
// Provides better visibility for low-percentage bands
const percent = band.densitometry.relative_percent_lane;
const logValue = Math.log10(1 + percent);
const maxLog = Math.log10(101);
intensity = 0.3 + (logValue / maxLog) * 0.7;
```

| Pourcentage | Intensité |
|-------------|-----------|
| 1%  | 0.35 |
| 5%  | 0.54 |
| 10% | 0.66 |
| 25% | 0.80 |
| 50% | 0.90 |
| 100%| 1.00 |

This logarithmic mapping ensures bands with low percentages remain visible.

## MW Scale (Graduated)

Scientific graduated scale using calibration data from MW_REFERENCE bands.

### Calibration Points

The scale uses MW_REFERENCE bands from **all lanes** to build a calibration curve:

```javascript
_getCalibrationPoints() {
    const allBands = Array.from(this.state.bands.values());
    return allBands
        .filter(b => b.estimated_mw_kda && b.band_type === 'MW_REFERENCE')
        .map(b => ({
            y: b.position_y,
            mw: b.estimated_mw_kda,
            logMW: Math.log10(b.estimated_mw_kda)
        }))
        .sort((a, b) => a.y - b.y);
}
```

### Log-Linear Interpolation

Position is interpolated in log space for standard MW markers:

```javascript
_interpolateMWPosition(targetMW, calibPoints) {
    const targetLogMW = Math.log10(targetMW);
    // Find bracketing points
    for (let i = 0; i < calibPoints.length - 1; i++) {
        const p1 = calibPoints[i];
        const p2 = calibPoints[i + 1];
        if (targetLogMW >= Math.min(p1.logMW, p2.logMW) &&
            targetLogMW <= Math.max(p1.logMW, p2.logMW)) {
            const t = (targetLogMW - p1.logMW) / (p2.logMW - p1.logMW);
            return p1.y + t * (p2.y - p1.y);
        }
    }
    return null;
}
```

### Standard MW Markers

- **Values**: 10, 15, 25, 35, 55, 70, 100, 130, 180, 250 kDa
- Only displayed within calibration range (±20%)
- Consistent across band view and pseudo-gel view

## Tooltips System

CSS-based instant tooltips (no JavaScript delay):

```html
<button data-tooltip="Description" data-tooltip-pos="bottom">
    <i class="bi bi-icon"></i>
</button>
```

### CSS Implementation

```css
[data-tooltip]::after {
    content: attr(data-tooltip);
    position: absolute;
    bottom: calc(100% + 6px);
    opacity: 0;
    transition: opacity 0.15s ease;
    z-index: 9999;
}

[data-tooltip]:hover::after {
    opacity: 1;
}

/* Position variant */
[data-tooltip-pos="bottom"]::after {
    bottom: auto;
    top: calc(100% + 6px);
}
```

All panel buttons use this system for instant feedback.

**Panel Header Tooltips**: Tooltips in panel headers are forced to display **below** the buttons (instead of above) to avoid clipping by parent containers with `overflow: hidden`. The z-index is set to 9999.

```css
.dm-panel-header [data-tooltip]::after {
    bottom: auto;
    top: calc(100% + 6px);
}
```

## Cross-Navigation

The densitometry header includes navigation buttons to related views:

| Button | Icon | Target | Condition |
|--------|------|--------|-----------|
| **Annotate** | `bi-pencil-square` | Annotation editor | Disabled if analysis not editable |
| **Compare Lanes** | `bi-graph-up` | Sample Comparison | Always available |
| **Run Analysis** | `bi-play-circle` | (action) | Runs densitometry |
| **Export CSV** | `bi-download` | (action) | Exports results |
| **Image Adjust** | `bi-sliders` | (action) | Opens image adjustments |

The "Annotate" button uses `.dm-btn-outline` style (transparent background, border) to distinguish navigation from action buttons.

## Panel Magnification

Each panel has an expand button (⛶) in its header that opens a fullscreen magnification modal. The modal re-renders the panel content at full viewport dimensions for detailed inspection.

```javascript
// Triggered via panel header button
app._openMagnifyModal('chromatogram');  // or 'gelOverview', 'bandZoom', 'measurements'
```

The modal supports:
- Full viewport rendering with proper D3.js chart re-sizing
- Escape key and close button to dismiss
- Smooth fade-in/out transitions

**Font consistency**: The magnify overlay (`.dm-magnify-overlay`) is positioned outside `.dm-app`, so it has an explicit `font-family: 'Roboto'` declaration to ensure consistent typography in fullscreen mode.

## Shared Utilities

The densitometry module uses shared utilities extracted to `js/shared/`:

- **`chromatogram-utils.js`**: D3.js rendering (axes, traces, peaks, zoom, legend)
- **`mw-utils.js`**: MW calibration and scale rendering

These are also used by the Sample Comparison module for consistent electropherogram rendering.

## CSS Classes

- `.dm-*`: Densitometry module classes
- Colors: `--dm-poi-color`, `--dm-other-color`, `--dm-mw-ref-color`
- Panels: `.dm-panel-*`

## Dependencies

- **Backend**: scipy (curve_fit, trapezoid), numpy, Celery + Redis (async jobs)
- **Frontend**: D3.js v7, Three.js r160+ (optional 3D terrain view)

## Chromatogram Panel Toggle Buttons

| Button | Icon | ID | Action |
|--------|------|----|--------|
| MW Axis | `bi-rulers` | `mw-toggle-btn` | Switch position/MW X-axis |
| Background | `bi-layers-half` | `bg-toggle-btn` | Show/hide background + rescale Y-axis |
| Legend | `bi-list-ul` | `legend-toggle-btn` | Show/hide legend |
| Boundaries | `bi-border-left` | `boundaries-toggle-btn` | Show/hide band boundaries |
| Labels | `bi-fonts` | `labels-toggle-btn` | Show/hide MW/% labels |

## Related Files

- `gel_analyzer/templates/gel_analyzer/analyses/densitometry.html`
- `gel_analyzer/static/gel_analyzer/css/densitometry.css`
- `gel_analyzer/static/gel_analyzer/css/comparison.css` (comparison-specific overrides)
- `gel_analyzer/static/gel_analyzer/js/densitometry/3D_TERRAIN_VIEW.md` (3D view documentation)
- `gel_analyzer/services/report/REPORT_IMPLEMENTATION_GUIDE.md` (report generation)
- `gel_analyzer/migrations/0010_densitometry_models.py`

## References

- Backend deep-dive: [`gel_analyzer/docs/architecture/densitometry.md`](../../../../docs/architecture/densitometry.md)
- Quantification deep-dive: [`gel_analyzer/docs/architecture/quantification.md`](../../../../docs/architecture/quantification.md)
- User guide: [`gel_analyzer/docs/user/06-densitometry.md`](../../../../docs/user/06-densitometry.md)
- Models: `gel_analyzer/models/densitometry.py`
- Celery task: `gel_analyzer/tasks.py::run_densitometry_task`
- Shared D3 utilities: `gel_analyzer/static/gel_analyzer/js/shared/chromatogram-utils.js`, `mw-utils.js`
- MDB5-free constraint: agent memory `gel-analyzer/README.md` "MDB5-Free Views" section + main CLAUDE.md
