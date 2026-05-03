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
    └── results-table-panel.js   # Measurements table
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
2. **GEL_TOTAL**: Each band as percentage of entire gel area
3. **LOADING_CONTROL**: Relative to MW_REFERENCE bands
4. **REFERENCE_BAND**: Relative to a specific band

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
