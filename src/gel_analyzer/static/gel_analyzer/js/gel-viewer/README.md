# GelViewer JavaScript Architecture

> Comprehensive documentation for the GelViewer annotation editor.
> Last updated: January 2026

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Module Structure](#module-structure)
4. [Core Components](#core-components)
5. [Tools System](#tools-system)
6. [UI Panels](#ui-panels)
7. [Events System](#events-system)
8. [Data Flow](#data-flow)
9. [CSS Architecture](#css-architecture)
10. [Keyboard Shortcuts](#keyboard-shortcuts)
11. [API Endpoints](#api-endpoints)
12. [Development Guide](#development-guide)

---

## Overview

GelViewer is a client-side annotation editor for gel electrophoresis images (SDS-PAGE, Western Blot, Dot Blot). It provides interactive drawing tools for annotating lanes and bands on gel images with a hybrid save approach (local state + manual save).

### Key Features

- **Interactive SVG annotation** using SVG.js 3.x
- **Multiple lane shapes**: Rectangle, Quadrilateral, Polygon
- **Band annotation** with MW reference, POI, and other types
- **Band splitting** tool for separating overlapping bands
- **Hybrid save**: Local changes with explicit save to server
- **Immediate band persistence**: Band creation and type changes save immediately (fire-and-forget)
- **Crash recovery**: localStorage persistence of pending changes
- **Two-panel editing**: Lane Editor (right) and Band Editor (left)
- **Sample integration**: Link lanes to ProcessSample records
- **Image adjustments**: Brightness, contrast, invert
- **Toolbar safeguards**: Buttons disabled when prerequisites not met
- **Confirmation dialogs**: Pharma Corporate styled modals before destructive actions
- **MW Calibration**: Multi-ladder calibration with position-aware interpolation

### MDB5-Free Architecture

> **Important**: This viewer is designed to work **without MDB5 (Material Design Bootstrap)**. The standalone template (`annotate_standalone.html`) uses a minimal base template that does NOT include MDB5 JavaScript or CSS.
>
> All UI components (modals, panels, tooltips, buttons) are implemented with:
> - Pure CSS styling (`gel_viewer_standalone.css`)
> - Vanilla JavaScript with inline style fallbacks
> - SVG.js for canvas rendering
>
> **Do NOT add MDB5 dependencies** to this module. If you need modal dialogs, use `ConfirmationManager` which provides MDB5-compatible API with pure JavaScript fallback.

### Dependencies

```javascript
// Required: SVG.js 3.x (only external dependency)
<script src="https://cdn.jsdelivr.net/npm/@svgdotjs/svg.js@3.1.2/dist/svg.min.js"></script>
```

---

## Architecture

### Design Principles

1. **Event-Driven**: Components communicate via EventBus (PubSub pattern)
2. **Modular**: Each component is self-contained in its own file
3. **Namespace**: All components live under `window.GelViewer.*`
4. **No Framework**: Vanilla JavaScript, no React/Vue dependencies
5. **Hybrid Save**: Changes tracked locally, saved to server on demand

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         GelViewerApp                            │
│                     (Main Orchestrator)                         │
└────────────────────────────┬────────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
    ┌──────────┐      ┌───────────┐      ┌──────────┐
    │ EventBus │◄────►│StateManager│◄────►│APIClient │
    │ (PubSub) │      │  (State)   │      │  (HTTP)  │
    └────┬─────┘      └─────┬─────┘      └──────────┘
         │                  │
    ┌────┴────────────┬─────┴───────────────┐
    │                 │                     │
    ▼                 ▼                     ▼
┌─────────┐    ┌───────────┐        ┌────────────┐
│Renderer │    │ToolManager│        │   Panels   │
│  (SVG)  │    │ + Tools   │        │ + Modals   │
└─────────┘    └───────────┘        └────────────┘
```

### Initialization Flow

```javascript
// 1. HTML loads script files in order (event-bus.js first)
// 2. Each module registers to window.GelViewer namespace
// 3. Template initializes GelViewerApp:

const viewer = new GelViewerApp({
    containerId: 'gel-viewer-container',
    analysisId: '{{ analysis.id }}',
    imageUrl: '{{ image_url }}',
    imageProxyUrl: '{{ proxy_url }}',
    imageWidth: {{ width }},
    imageHeight: {{ height }},
    csrfToken: '{{ csrf_token }}',
    isEditable: true
});
```

---

## Module Structure

```
gel-viewer/
├── README.md                    # This documentation
├── gel-viewer.js               # Main orchestrator (GelViewerApp)
├── event-bus.js                # EventBus + Events constants
├── state-manager.js            # State management + localStorage
├── api-client.js               # Server communication (CRUD + bulk APIs)
├── renderer.js                 # SVG rendering of annotations
├── corner-handles.js           # Corner handles of a selected 4-point lane (tilted lanes)
├── viewport.js                 # Pan/zoom viewport control
├── event-handler.js            # Mouse/keyboard event handling
├── confirmation-manager.js     # MDB5-free confirmation dialogs
│
├── tools/
│   ├── tool-manager.js         # Tool switching and registration
│   ├── select-tool.js          # Selection tool
│   ├── pan-tool.js             # Pan/scroll tool
│   ├── lane-tool.js            # Lane drawing tool
│   ├── band-tool.js            # Band drawing tool
│   └── split-tool.js           # Band splitting tool
│
├── panels/
│   ├── data-table-panel.js            # Lane Editor (right panel)
│   ├── band-table-panel.js            # Band Editor (left panel)
│   ├── properties-panel.js            # Sidebar properties panel
│   ├── adjustments-panel.js           # Image adjustments panel
│   ├── calibration-panel.js           # Multi-ladder MW calibration
│   ├── detection-panel-base.js        # Base class for detection panels
│   ├── detection-panel.js             # d1/d2 derivative detection (hidden from toolbar)
│   ├── cv2-detection-panel.js         # CV2 Vision detection (hidden from toolbar)
│   ├── band-model-panel.js            # Band detection by the YOLO band model (toolbar, Shift+Y)
│   ├── electropherogram-panel.js      # Inline electropherogram + Ctrl/Shift shortcuts
│   ├── context-menu.js                # Right-click context menu
│   ├── review-panel.js                # YOLO detection review panel
│   └── teacher-panel.js               # Detection teaching/calibration
│
├── inference/                   # Phase 3: YOLO inference
│   ├── inference-engine.js     # Main orchestrator, lazy model loading
│   ├── inference-worker.js     # Web Worker for ONNX Runtime
│   ├── inference-utils.js      # Image preprocessing utilities
│   ├── band-model-engine.js    # Band model: main-thread side, one worker, model loaded once
│   ├── band-model-worker.js    # Band model: ONNX Runtime Web 1.24.3, WebGPU then WASM, ultralytics-exact pre/post
│   └── postprocess.js          # NMS, detection parsing
│
└── modals/
    └── sample-selector.js      # ProcessSample search modal
```

### Script Load Order

Scripts must be loaded in this order in HTML:

```html
<!-- Core (order matters) -->
<script src=".../shared/lane-geometry.js"></script>  <!-- GelAnalyzer.LaneGeometry: shape.py's rules -->
<script src=".../event-bus.js"></script>
<script src=".../state-manager.js"></script>
<script src=".../api-client.js"></script>
<script src=".../ladder-template-apply.js"></script>  <!-- GelViewer.LadderTemplateApply: both Apply buttons -->
<script src=".../viewport.js"></script>
<script src=".../renderer.js"></script>
<script src=".../corner-handles.js"></script>
<script src=".../event-handler.js"></script>

<!-- Tools -->
<script src=".../tools/tool-manager.js"></script>
<script src=".../tools/select-tool.js"></script>
<script src=".../tools/pan-tool.js"></script>
<script src=".../tools/lane-tool.js"></script>
<script src=".../tools/band-tool.js"></script>
<script src=".../tools/split-tool.js"></script>

<!-- Inference (Phase 3) -->
<script src=".../inference/inference-utils.js"></script>
<script src=".../inference/postprocess.js"></script>
<script src=".../inference/inference-engine.js"></script>
<!-- Note: inference-worker.js is loaded by the engine as a Web Worker -->

<!-- Panels -->
<script src=".../panels/properties-panel.js"></script>
<script src=".../panels/data-table-panel.js"></script>
<script src=".../panels/band-table-panel.js"></script>
<script src=".../panels/adjustments-panel.js"></script>
<script src=".../panels/calibration-panel.js"></script>
<script src=".../panels/detection-panel-base.js"></script>
<script src=".../panels/detection-panel.js"></script>
<script src=".../panels/cv2-detection-panel.js"></script>
<script src=".../inference/band-model-engine.js"></script>
<script src=".../panels/band-model-panel.js"></script>
<script src=".../panels/electropherogram-panel.js"></script>
<script src=".../panels/context-menu.js"></script>
<script src=".../panels/review-panel.js"></script>
<script src=".../panels/teacher-panel.js"></script>

<!-- Modals -->
<script src=".../modals/sample-selector.js"></script>

<!-- Main (must be last) -->
<script src=".../gel-viewer.js"></script>
```

---

## Core Components

### EventBus (`event-bus.js`)

Central pub/sub system for loose coupling between modules.

```javascript
// Subscribe to event
const unsubscribe = eventBus.on('lane:created', (data) => {
    console.log('Lane created:', data);
});

// Subscribe once (auto-unsubscribe)
eventBus.once('save:completed', () => {
    console.log('First save done!');
});

// Emit event
eventBus.emit('lane:created', { id: 123, lane_type: 'SAMPLE' });

// Unsubscribe
unsubscribe();
// or: eventBus.off('lane:created', handler);
```

#### Event Constants

All event names are defined in `Events` object for type safety:

```javascript
const Events = GelViewer.Events;

// Lane events
Events.LANE_CREATED          // 'lane:created'
Events.LANE_UPDATED          // 'lane:updated'
Events.LANE_DELETED          // 'lane:deleted'
Events.LANE_SELECTED         // 'lane:selected'
Events.LANE_PROPERTY_CHANGED // 'lane:property:changed'
Events.LANE_DRAW_FINISHED    // 'lane:draw:finished'

// Band events
Events.BAND_CREATED          // 'band:created'
Events.BAND_UPDATED          // 'band:updated'
Events.BAND_DELETED          // 'band:deleted'
Events.BAND_SELECTED         // 'band:selected'
Events.BAND_SPLIT            // 'band:split'
Events.BAND_DRAW_FINISHED    // 'band:draw:finished'
Events.BAND_PROPERTY_CHANGED // 'band:property:changed'

// Selection events
Events.SELECTION_CHANGED     // 'selection:changed'
Events.SELECTION_CLEARED     // 'selection:cleared'

// Tool events
Events.TOOL_CHANGED          // 'tool:changed'
Events.LANE_SHAPE_CHANGED    // 'lane:shape:changed'

// State events
Events.STATE_DIRTY           // 'state:dirty'
Events.STATE_CLEAN           // 'state:clean'
Events.PENDING_CHANGED       // 'state:pending-changed' (markDirty / afterImmediateSave / markClean; the unsaved count)
Events.STATE_SAVING          // 'state:saving'
Events.STATE_SAVED           // 'state:saved'

// Viewport events
Events.VIEWPORT_CHANGED      // 'viewport:changed'
Events.ZOOM_CHANGED          // 'zoom:changed'

// UI events
Events.ANNOTATIONS_LOADED    // 'annotations:loaded'
Events.TABLE_CELL_CHANGED    // 'table:cell:changed'
Events.CONTEXT_MENU_REQUESTED // 'context:menu:requested'

// Save events
Events.SAVE_REQUESTED        // 'save:requested'
Events.SAVE_COMPLETED        // 'save:completed'

// Image events
Events.IMAGE_ADJUSTED        // 'image:adjusted'
Events.IMAGE_RESET           // 'image:reset'

// Inference events (Phase 3)
Events.INFERENCE_STARTED     // 'inference:started'
Events.INFERENCE_PROGRESS    // 'inference:progress'
Events.INFERENCE_COMPLETED   // 'inference:completed'
Events.INFERENCE_ERROR       // 'inference:error'
Events.REVIEW_ACCEPTED       // 'review:accepted'
Events.REVIEW_REJECTED       // 'review:rejected'

// Detection panel events (Phase 10 — mutually exclusive panels)
Events.BAND_MODEL_PANEL_SHOWN          // 'band-model:panel:shown'
Events.BAND_MODEL_PANEL_HIDDEN         // 'band-model:panel:hidden'
```

---

### StateManager (`state-manager.js`)

Centralized state management with pending changes tracking and localStorage persistence.

#### Data Structures

```javascript
// Lanes Map: Map<id, LaneData>
stateManager.lanes = new Map();

// LaneData structure
{
    id: 123,                    // Server ID or temp_xxx
    lane_number: 1,             // Auto-calculated from X position
    lane_type: 'SAMPLE',        // SAMPLE | LADDER | CONTROL | EMPTY
    lane_type_display: 'Sample',
    lane_shape: 'RECTANGLE',    // RECTANGLE | QUADRILATERAL | POLYGON
    x: 100, y: 50,              // Bounding box
    width: 80, height: 400,
    polygon: [[x1,y1], ...],    // For non-rectangle shapes
    sample_name: 'Sample 1',       // Custom text (empty when process_sample is set)
    process_sample: null,           // { id, sample_id } or null (FK to ProcessSample)
    process_sample_id: null,        // FK ID (used in API writes)
    is_reduced: true,           // Reduced/Non-reduced condition
    protein_load_ug: 10.0,
    protein_load_type: 'TOTAL', // TOTAL | POI | HOST_CELL | OTHER
    notes: '',
    bands: [],                  // Array of child bands
    _isNew: true,               // Temp flag for unsaved
}

// Bands Map: Map<id, BandData>
stateManager.bands = new Map();

// BandData structure
{
    id: 'uuid-xxx',
    lane_id: 123,               // Parent lane ID
    _parentLaneId: 123,         // Internal reference
    band_type: 'OTHER',         // MW_REFERENCE | POI | OTHER
    polygon: [[x1,y1], ...],    // Band shape points
    position_y: 250,            // Y center for sorting
    bbox_x: 100, bbox_y: 200,   // Bounding box
    bbox_width: 80, bbox_height: 20,
    estimated_mw_kda: null,     // Molecular weight
    label: '',
    notes: '',
    _isNew: true,
}
```

#### Pending Changes (Hybrid Save)

```javascript
// Pending changes structure
stateManager.pendingChanges = {
    lanes: {
        created: new Map(),   // tempId -> LaneData
        updated: new Map(),   // id -> partial update data
        deleted: new Set(),   // Set of IDs
    },
    bands: {
        created: new Map(),
        updated: new Map(),
        deleted: new Set(),
    }
};

// Track operations
stateManager.trackLaneCreation(tempId, laneData);
stateManager.trackLaneUpdate(id, { lane_type: 'LADDER' });
stateManager.trackLaneDeletion(id);

// Check state
stateManager.isDirty;           // Has unsaved changes
stateManager.hasPendingChanges(); // Alternative check
```

**The pending sets are what the next Save writes, so they always match the canvas** (fixed 2026-10-12: an unsaved band
deleted stayed in `bands.created` and the Save created it again, or POSTed to `/api/lanes/temp_…/bands/` and failed on
every attempt):
- Outside `_batchSave`, only StateManager writes `pendingChanges`; `gel-viewer.js` never edits the sets directly. Every
  entry that leaves them outside Save ends in `afterImmediateSave()` (below), so the crash backup forgets it too.
- `trackBandDeletion` / `trackLaneDeletion` read the pending sets, not the maps, so call order does not matter. An
  unsaved band or lane is only forgotten (clean when nothing is left). A lane takes the new bands drawn in it with it.
- A PUT made outside the Save (band edit, lane auto-promote) confirms only the fields it sent
  (`confirmUpdateSaved(kind, id, sent)`): a resize of the same lane waiting for Save stays pending. `confirmBandCreated`
  closes a band POST; `forgetBandUpdate` drops the pending edit of a saved band deleted on the server at once, and
  `forgetLaneUpdate` that of a saved lane (with the new bands drawn in it). A saved lane is deleted on the server at
  once, as a saved band is (`_deleteLane`, 2026-10-17: it waited for Save under a dialog saying "permanently"); its
  saved bands go with it server-side (CASCADE), so none of them is tracked. Signed out, the lane goes back to the
  pending deletes; any other refusal reloads.
- A band deleted or split while its own POST is in flight is flagged `_removed`; the POST then deletes what it created.
- `_reloadAnnotations` keeps the unsaved changes that still apply (`keepPendingApplicable`, called before the maps are
  cleared) and draws them again over the server's data (`_redrawPendingChanges`): new lanes and bands still on the
  canvas, edits and deletions of annotations the server still has. It drops the rest with a toast: an annotation the
  server no longer has, a band whose lane is gone, a band still in its own POST.
- The wand's *Replace & Detect* empties the server and the canvas with no reload, so it ends in `markClean()`
  (`_autoDetect`, fixed 2026-10-12: a lane drawn by hand came back at the next Save beside the detected ones;
  `node __tests__/autodetect-replace.test.js` runs the real `_autoDetect` on a real StateManager). *Remove
  all lanes* / *Remove all bands* reload instead, and `keepPendingApplicable` drops what they removed.

#### ID Replacement (Temp → Server)

When bands are created, they get a temporary ID until saved to the server:

```javascript
// Replace temp ID with real server ID after immediate save
stateManager.replaceBandId(oldTempId, newServerId);
// Updates bands Map, parent lane's bands array, and SVG element
```

#### LocalStorage Persistence

The crash backup mirrors `pendingChanges` (what Save would send), nothing else:

```javascript
// Every markDirty() reschedules it (500 ms after the last change); beforeunload writes it at once.
localStorage.setItem(`gelViewer_${analysisId}`, JSON.stringify({
    version: 2,              // a backup without it (the old first-change-only one) is dropped unread
    analysisId: 'uuid',
    timestamp: Date.now(),   // older than 24 h -> dropped
    pendingChanges: {...}    // the Maps and Sets as arrays
}));

// An entry that leaves pendingChanges outside Save (a band sent at once, an unsaved band deleted, an entry a
// reload made stale), then:
stateManager.afterImmediateSave();   // clean if nothing else waits, else the backup is rewritten without it

// _batchSave removes each entry from pendingChanges as soon as the server has it (a created lane also
// re-points its pending bands and rewrites the backup): a retry, or a backup left by a save that failed
// half way, never creates it twice. markClean() at the end deletes the backup.

// On load (GelViewerApp._offerBackup, after the server's lanes are drawn, editable analyses only):
const backup = stateManager.loadFromLocalStorage();          // null when none, expired or old format
const { changes, dropped } = stateManager.recoverable(backup); // drops edits/deletions of lanes or bands the
                                                               // server no longer has, and their bands
// -> a dialog lists `changes` (and `dropped`): Restore replays them through the editor's own tracking
//    (_restoreChanges: they become unsaved changes, Save sends them); Discard deletes the backup.
```

Known limit: a restored lane edit has no server version to be checked against (the payload carries none), so
it overwrites a change made to the same lane elsewhere in between once the user saves. The user guide says so.

---

### APIClient (`api-client.js`)

Server communication layer for CRUD operations.

```javascript
const api = new APIClient({
    analysisId: 'uuid',
    csrfToken: 'xxx',
    eventBus: eventBus
});

// Load all annotations
const data = await api.loadAnnotations();
// Returns: { lanes: [...], bands: [...] }

// Lane CRUD
const { id } = await api.createLane(laneData);
await api.updateLane(id, { lane_type: 'LADDER' });
await api.deleteLane(id);

// Band CRUD
const { id } = await api.createBand(laneId, bandData);
await api.updateBand(id, { estimated_mw_kda: 66.5 });
await api.deleteBand(id);

// Bulk operations (Phase 3)
const result = await api.createLanesBulk(lanesArray);  // Returns { lanes, count }
const result = await api.updateLanesBulk(lanesArray);  // Array of {id, ...fields}
const result = await api.deleteLanesBulk(laneIdsArray); // Array of lane IDs

// YOLO results
await api.saveYoloResults({ detections, inferred_gel_type });

// Sample search
const samples = await api.searchSamples({
    query: 'Pool',
    drugSubstanceId: 1,
    sheetId: 5
});

const filterOptions = await api.getSampleFilterOptions();
// Returns: { drug_substances: [...], sheets: [...] }
```

**A signed-out answer is a failure, never a save** (2026-10-13, task_b27a3d8b). Signed out, `@login_required` answers
302 to the login page and fetch follows it: a PUT is replayed there and answered **200** with HTML, a POST becomes a
GET of it (200), a DELETE gets 405. Reading `response.ok` alone, `updateBand` / `updateLane` resolved on the login
page, so the editor dropped the pending change and said "Band updated" (measured on devlocal; `saveBandModel` resolved
with `{}`). Every call goes through `APIClient._request`: a redirect to the login page (the `next=` that
`redirect_to_login` adds), a 401 (the DRF endpoints) or a success that is not JSON throws a `SessionExpiredError`, so
the caller fails as on any refusal and the change stays pending -- a band deleted at once (`_deleteBand`) goes back to
the pending deletes instead of a reload that would fail the same way, and "Band updated" waits for the server's answer.
`Events.SESSION_EXPIRED` ({message}) is emitted once, `Events.SESSION_RESTORED` when an answer comes through again;
`GelViewerApp` shows the first as a sticky error toast and closes it on the second. A new call uses `this._request`,
never `fetch`. The `X-CSRFToken` sent is the `csrftoken` **cookie** (`csrfToken` getter; the page's `{{ csrf_token }}`
is only the fallback): a login rotates the token, and after logging in again in another tab the page's one was refused
(403). `node __tests__/session-expired.test.js` holds these rules.

---

### Renderer (`renderer.js`)

SVG rendering of lanes and bands using SVG.js.

```javascript
const renderer = new Renderer({
    svg: svgInstance,
    lanesGroup: svg.group(),
    bandsGroup: svg.group(),
    stateManager: stateManager,
    eventBus: eventBus,
    onSelectAnnotation: (type, id) => { ... }
});

// Render annotations
renderer.renderLane(laneData);
renderer.renderBand(bandData);

// Update visuals
renderer.updateLaneNumber(id, newNumber);
renderer.selectAnnotation('lane', id);
renderer.clearSelection();

// Remove from SVG
renderer.removeLane(id);
renderer.removeBand(id);
```

#### SVG Structure

```html
<svg class="gv-svg-overlay">
    <g id="lanes-layer">
        <rect id="lane-123" class="gv-lane sample" />
        <text id="lane-label-123" class="gv-lane-label">1</text>
        <!-- or polygon for non-rectangle -->
        <polygon id="lane-456" class="gv-lane ladder shape-quadrilateral" />
    </g>
    <g id="bands-layer">
        <polygon id="band-uuid" class="gv-band other" />
    </g>
    <g id="handles-layer">
        <!-- Resize handles when selected -->
    </g>
    <g id="drawing-layer">
        <!-- Preview shapes during drawing -->
    </g>
</svg>
```

---

### Viewport (`viewport.js`)

Pan and zoom control for the image canvas.

```javascript
const viewport = new Viewport({
    viewer: document.querySelector('.gv-viewer'),
    canvasContainer: document.querySelector('.gv-canvas-container'),
    svg: svgInstance,
    imageWidth: 1200,
    imageHeight: 800,
    eventBus: eventBus
});

// Methods
viewport.fitToView();           // Fit image to container
viewport.zoom(1.2);             // Zoom in 20%
viewport.zoom(0.8);             // Zoom out 20%
viewport.zoom(1.5, {x, y});     // Zoom to point
viewport.setScale(1.0);         // Set absolute scale
viewport.getScale();            // Get current scale
viewport.pan(dx, dy);           // Pan by delta
viewport.centerOn(x, y);        // Center on point
```

---

## Tools System

### ToolManager (`tools/tool-manager.js`)

Manages tool switching and registration.

```javascript
const toolManager = new ToolManager({
    viewer: viewerElement,
    eventBus: eventBus,
    isEditable: true,
    showMessage: (msg) => { ... },
    cancelDrawing: () => { ... },
    deselect: () => { ... }
});

// Register tools
toolManager.registerTool('select', selectToolInstance);
toolManager.registerTool('pan', panToolInstance);
toolManager.registerTool('lane', laneToolInstance);
toolManager.registerTool('band', bandToolInstance);
toolManager.registerTool('split', splitToolInstance);

// Switch tools
toolManager.setTool('lane');
toolManager.setTool('select');

// Lane shape (for lane tool)
toolManager.setLaneShape('RECTANGLE');    // Default
toolManager.setLaneShape('QUADRILATERAL');
toolManager.setLaneShape('POLYGON');
toolManager.getLaneShape();

// Query
toolManager.getTool();          // Current tool name
toolManager.isDrawingTool();    // lane, band, or split?
toolManager.getActiveTool();    // Tool instance
```

### Available Tools

| Tool | Key | Description |
|------|-----|-------------|
| `select` | V | Select and move annotations |
| `pan` | H | Pan/scroll the viewport |
| `lane` | L | Draw lane rectangles/polygons |
| `band` | B | Draw bands inside lanes |
| `split` | S | Split bands horizontally |

---

### LaneTool (`tools/lane-tool.js`)

Draws lanes with multiple shape modes.

**Rectangle Mode:**
- Click and drag to create rectangle
- Auto-calculates lane number from X position

**Quadrilateral Mode:**
- Click 4 corners in sequence
- Creates a 4-point polygon

**Polygon Mode:**
- Click to add points
- Press Enter or double-click to finish
- Creates N-point polygon

```javascript
const laneTool = new LaneTool({
    svg: svgInstance,
    drawingGroup: drawingGroup,
    eventBus: eventBus,
    stateManager: stateManager,
    toolManager: toolManager,
    onLaneCreated: (data) => { ... },
    showMessage: (msg) => { ... },
    getScale: () => viewport.getScale()
});
```

### Lane Resizing

Lanes can be resized after creation in three ways:

**Corner handles (4-point lanes, `corner-handles.js`):** selecting a QUADRILATERAL lane -- or an upright 4-point
POLYGON one -- shows a round handle on each corner, on an editable analysis (Right-click → "Resize Lane" selects a
tilted one; an upright one gets the box handles below, so it is resized without being tilted). Dragging a corner moves
its x freely; its y moves both corners of that edge, so top and bottom stay horizontal and the side's slope changes.
Corners stay in the image, each edge keeps 6 px of width and the top stays 6 px above the bottom (the sides never
cross). The scale is read on every move (a zoom mid-drag keeps the corner under the pointer); Esc mid-drag restores the
lane and commits nothing, and so does a `pointercancel` or a drag cut short by a new selection. The drop commits one
`_updateLane()` with `lane_shape: 'QUADRILATERAL'`, the rounded corners and their outer box (the server's Rule 1),
saved as any lane edit.

**Box handles (Context Menu: rectangles, upright 4-point lanes, >4-point polygons):**
- Right-click a lane → "Resize Lane"
- Four corner drag handles appear on the box (NW, NE, SW, SE); minimum size 20 px. They are given a copy of the lane,
  so `_updateLane()` still sees the box before the drag
- Calls `_updateLane()` on mouse-up with the final box; if X changes, lane numbers are recalculated

**Numeric Resize (Properties Panel):** the X, Y, Width, Height fields, debounced.

A box-only change on a lane drawn by its polygon (the box handles, the fields) maps the polygon onto the new box in
`_updateLane()` (affine per axis, clamped to the image, rounded) -- the same mapping the server applies
(`shape.py::normalize_lane_write`, D12) -- so the outline follows instead of snapping back until a reload. It always
maps from the polygon and box as they were before the lane's first box-only edit (`lane._boxEditBase`, dropped by any
write carrying a polygon and by a reload), so typing W 85 → 6 → 62 gives what one 85 → 62 mapping gives.

### Lane Height Normalization

Normalizes all lane heights to a uniform top/bottom extent. Useful after YOLO detection where individual lanes may have slightly different vertical boundaries.

**Algorithm:**
1. Find global min-Y (topmost edge) and max-(Y+height) (bottommost edge) across all lanes
2. For polygon lanes: remap top polygon points to `globalTop`, bottom points to `globalBottom`
3. For rectangle lanes: set `y = globalTop`, `height = globalBottom - globalTop`

**Trigger points:**
- **Toolbar button** (distribute-vertical icon): Manual normalization on demand
- **Auto-normalize after YOLO detection**: Called automatically in `_acceptDetections()` after bulk lane creation

```javascript
// Manual trigger
gelViewer._normalizeLaneHeights();

// Shows loading overlay during processing
// Status message: "18 lanes normalized (y=120, h=710px)"
```

---

### BandTool (`tools/band-tool.js`)

Draws bands inside lanes.

- Must click inside an existing lane
- Click and drag to create band rectangle
- Auto-converts to polygon for storage
- Inherits band type from parent lane (MW_REFERENCE for LADDER lanes)

```javascript
const bandTool = new BandTool({
    svg: svgInstance,
    drawingGroup: drawingGroup,
    eventBus: eventBus,
    stateManager: stateManager,
    onBandCreated: (laneId, data) => { ... },
    findLaneAtPoint: (x, y) => laneId,
    showMessage: (msg) => { ... },
    getScale: () => viewport.getScale()
});
```

---

### SplitTool (`tools/split-tool.js`)

Splits existing bands horizontally.

- Click on a band to select it
- Click again to define split line Y position
- Creates two bands from the original

```javascript
const splitTool = new SplitTool({
    svg: svgInstance,
    drawingGroup: drawingGroup,
    eventBus: eventBus,
    stateManager: stateManager,
    onBandSplit: (bandId, splitY) => { ... },
    getBandAtPoint: (x, y) => band,
    showMessage: (msg) => { ... },
    getScale: () => viewport.getScale()
});
```

---

## UI Panels

### DataTablePanel - Lane Editor (`panels/data-table-panel.js`)

Excel-like table for bulk lane editing. **Slides from RIGHT side.**

**Features:**
- All lanes in sortable table
- Inline editing of all lane properties
- Two-way sync with properties panel
- Click row to select lane on canvas
- Sample column shows `process_sample.sample_id` (flask icon) or custom `sample_name` (link icon)
- Type goes through `PropertiesPanel.changeLaneType` (`onChangeLaneType`), the form's own path: the
  CALIBRATION/CONTROL downgrade confirmations and the ladder template rule. Never `onUpdateLane` for `lane_type`:
  that skipped both. The lane menu's Lane Type group takes it too (`ContextMenu`'s `handlers.onSetLaneType`)
- Footer: **Close** keeps the edits (unsaved, like every edit); **Save all** is the editor's Save
  (`onSaveAll` → `_batchSave`), so every pending change, bands included; the rows are rebuilt after it

**Columns:**
| Column | Field | Editable |
|--------|-------|----------|
| # | lane_number | No (auto) |
| Type | lane_type | Yes (select) |
| Condition | is_reduced | Yes (select) |
| Load (ug) | protein_load_ug | Yes (number) |
| Load Type | protein_load_type | Yes (select) |
| Sample | process_sample / sample_name | Yes (modal) |

```javascript
const dataTablePanel = new DataTablePanel({
    eventBus: eventBus,
    stateManager: stateManager,
    onSelectAnnotation: (type, id) => { ... },
    onUpdateLane: (id, data, silent) => { ... },
    onChangeLaneType: (id, type, select) => propertiesPanel.changeLaneType(id, type, select),
    onSaveAll: () => viewer._batchSave(),
    onOpenSampleSelector: (laneId) => { ... }
});

dataTablePanel.show();
dataTablePanel.hide();
dataTablePanel.toggle();
dataTablePanel.refresh();
dataTablePanel.highlightRow(laneId);
dataTablePanel.updateSampleCell(laneId, sampleName);
```

---

### BandTablePanel - Band Editor (`panels/band-table-panel.js`)

Table for editing bands within a selected lane. **Slides from LEFT side.**

**Features:**
- Shows bands for currently selected lane
- Different columns for LADDER vs SAMPLE lanes
- Inline editing with debounced updates
- Two-way sync with properties panel

**Columns (Sample lanes):**
| Column | Field | Editable |
|--------|-------|----------|
| # | index | No |
| Type | band_type | Yes (select) |
| Est. MW | estimated_mw_kda | Yes (number) |
| Label | label | Yes (text) |
| Notes | notes | Yes (text) |
| Actions | delete | Button |

**Columns (Ladder lanes):**
| Column | Field | Editable |
|--------|-------|----------|
| # | index | No |
| MW (kDa) | estimated_mw_kda | Yes (number) |
| Label | label | Yes (text) |
| Notes | notes | Yes (text) |
| Actions | delete | Button |

**Ladder template (LADDER lanes):** the MW Template select and **Apply** above the table go through
`LadderTemplateApply` (`ladder-template-apply.js`), the lane form's Apply's path too -- see *PropertiesPanel*.
This one asks nothing before replacing values (owner, 2026-10-13): the table shows the ones it replaces.

```javascript
const bandTablePanel = new BandTablePanel({
    eventBus: eventBus,
    stateManager: stateManager,
    onSelectBand: (bandId) => { ... },
    onUpdateBand: (id, data) => { ... },
    onDeleteBand: (id) => { ... },
    ladderTemplateApply: ladderTemplateApply
});

bandTablePanel.showForLane(laneId);
bandTablePanel.show();  // Uses current selection
bandTablePanel.hide();
bandTablePanel.toggle();
```

---

### PropertiesPanel (`panels/properties-panel.js`)

Sidebar panel showing properties of selected annotation.

**Features:**
- Dynamic form based on selection type
- Real-time updates to state
- Sample selector integration (displays `process_sample.sample_id` with flask icon, or custom `sample_name` with pencil icon)
- Band list for selected lane (redrawn on `MW_BANDS_UPDATED`: a template applied, the MW calibration applied)
- Dimension editing (X, Y, Width, Height) with live SVG update
- MW Template's **Apply** on a LADDER lane (owner, 2026-10-13): `LadderTemplateApply`, asking *Replace MW values?*
  first when a band of the lane holds one; its warnings, refusal or error go under the select

**`LadderTemplateApply` (`ladder-template-apply.js`)** is the ONE path that fills a ladder's MW values from a
template, for both Apply buttons (this form's, the Band editor's): same request (`apiClient.applyLadderTemplate`,
a `WRITES` entry), same refusals, same warnings (`noticeHtml`), same events. The server gives the values to the bands
IT holds, in their saved order, so nothing is sent while `StateManager.laneWaitsForSave(laneId)` (the lane never
saved, its type waiting, a band of it created / edited / deleted and not saved): the Band editor's raw `fetch` once
answered a JSON parse error (unsaved lane: a 404 page), "only available for LADDER type lanes" (type not saved yet), or
put every value one band off (band not saved). Nor while a band of the lane is typed POI or Calibration: a ladder's
bands are MW Reference or Other, and a band that says otherwise is refused, never worked around (until 2026-10-13 its
value also turned the lane back into a SAMPLE lane, whose template the server then dropped). Each changed value reaches
the SAME band object through `_syncBandLocally`, a hand edit's path once saved, so `CalibrationPanel._onBandChanged`
marks the calibration stale (no second rule; owner, 2026-10-13); the band objects were replaced by the server's copies
before (role, lane link and calibration point lost). A template choice waiting for Save is the one the server now
holds: dropped from the pending lane edit. `node __tests__/ladder-template-apply.test.js` holds these rules.

```javascript
const propertiesPanel = new PropertiesPanel({
    eventBus: eventBus,
    stateManager: stateManager,
    onOpenSampleSelector: (laneId) => { ... },
    onDeleteLane: (id) => { ... },
    onDeleteBand: (id) => { ... },
    onUpdateLane: (id, data) => { ... },
    onUpdateBand: (id, data) => { ... },
    onSelectBand: (bandId) => { ... }
});
```

---

### AdjustmentsPanel (`panels/adjustments-panel.js`)

Image brightness, contrast, and invert controls.

```javascript
const adjustmentsPanel = new AdjustmentsPanel({
    eventBus: eventBus,
    imageElement: document.querySelector('.gv-image'),
    imageProxyUrl: '/proxy/image.png'
});

adjustmentsPanel.show();
adjustmentsPanel.hide();
adjustmentsPanel.toggle();
adjustmentsPanel.reset();           // Reset to defaults
adjustmentsPanel.setAdjustments({   // Set values
    brightness: 1.2,
    contrast: 1.1,
    invert: false
});
```

---

### BandModelPanel (`panels/band-model-panel.js`)

Band detection by the YOLO band model, after the lanes (Grégory 2026-10-09). Toolbar target icon (`#toggle-band-model`), **Shift+Y**; requires saved lanes, refuses while the state is dirty. Flow: `GET band-model/` (model URL + sha256 + settings, the gel window of a scanned page, `editable`, `can_write`) → `BandModelEngine.load()` (download with %, sha256 checked in the browser, session: WebGPU else WASM) → `detect(#gel-image)` → `POST band-model/preview/` (boxes from `min_confidence` up; the server places them in the lanes) → the slider filters the preview on the page (`band.score`) → `POST band-model/save/` at the slider's value → `DATA_RELOAD_REQUESTED`. Every phase is shown in `#gv-bm-stage` (download %, checking, preparing, finding the bands on the GPU/CPU with the elapsed seconds, placing, saving); refusals show the server's words (403 reader / not editable / approved, 409 another model, 503 file not matching settings). Save is greyed for a reader or a non-editable analysis, with the reason. `localStorage.setItem('gelViewer.bandModelBackend', 'wasm')` forces the CPU path, to check the fallback on a PC with a GPU. Emits `Events.BAND_MODEL_PANEL_SHOWN` / `_HIDDEN`; mutually exclusive with the other detection panels. CSS prefix `.gv-bm-*`.

`inference/band-model-worker.js` reproduces ultralytics 8.3 predict BIT-EXACTLY: rect letterbox (stride 32, grey 114), cv2's fixed-point INTER_LINEAR with OpenCV's SIMD rounding, strict `score > min_confidence`, greedy NMS, `scale_boxes`. Measured 2026-10-09 against ultralytics on 46 bench gels + a synthetic scanned page: 7 640 / 7 640 boxes at 0.25, 47 / 47 gels identical (WebGPU, ~0.9 s per gel; WASM ~20 s). Parity harness: gel_analyzer/README.md, *Band model*.

The Hybrid Detection, Cross-Lane Consensus and Profile Peak panels it replaced were deleted on 2026-10-13 (owner), Shift+P with them. Bands a consensus run saved still draw with `.gv-band-cross-lane`.

---

### ElectropherogramPanel (`panels/electropherogram-panel.js`)

Inline D3.js intensity profile for the currently selected lane. Toggle with `G`. In addition to the chart it provides mouse shortcuts for fast annotation, a custom cursor guide, an in-panel status toast, and a "?" help popover.

**Mouse shortcuts**

| Gesture | Action |
|---------|--------|
| `Ctrl+click` (empty area) | Create a band at the clicked Y |
| `Ctrl+click` (inside existing band) | Split that band at the clicked Y — deletes the original and creates an upper + lower sub-band (1 px valley gap). Split children persist `metadata.hybrid_phase = "split"` |
| `Shift+click & drag` | Create a range-band spanning the drag |
| `Esc` | Cancel an in-progress drag |
| `?` header button | Toggle shortcut popover |

**Custom DOM cursor guide**: a thin red DOM line overlays the Plotly chart whenever Ctrl or Shift is held. This replaced Plotly's built-in spike (which vanished behind band shapes) so the guide stays visible over SVG annotations. A precise SVG crosshair cursor is set on the chart while the modifier is held.

**Status toast**: inline feedback during split operations — "Splitting…" (spinner) → "Band split" or "Split failed" with auto-dismiss.

---

### ContextMenu (`panels/context-menu.js`)

Right-click context menu for annotations.

**Opening** (`GelViewerApp._openContextMenu`, on `Events.CONTEXT_MENU_REQUESTED` from the EventHandler; owner brief
2026-10-13): a right-click, or a 500 ms long-press on a touch screen, selects what is under the point -- a band (its
polygon, else its box; the last one when two overlap), else the lane by its outline -- and opens that one's menu there;
bare gel opens nothing and keeps the selection; a press on a resize handle (`.gv-corner-handle`, `.gv-handle`) is a
drag and never opens it. **Shift+F10** / the **Menu** key open the selection's menu over the middle of the part of its
shape that is on screen (else of the gel's view, else of the window; never off screen), as a `GelViewer.Layers` modal: the focus goes to the first item (Up / Down / Home / End, Tab,
Enter), the letter shortcuts are held behind it, and Esc or an item gives the focus back. Nothing opens while a shape is
being drawn, nor on a non-editable analysis. The items act on the selection, which is then the target. The
`contextmenu` event the browser sends after the key (on keyup, on Windows) is swallowed for 1 s
(`EventHandler._onDocumentContextMenu`); a long-press that Android also reports as `contextmenu` opens one menu, and the
finger's lift is cancelled (no mousedown to close the menu again, no click under it).

**Lane options:**
- Edit Properties
- Resize Lane (shows drag handles)
- Set Type (Sample, Ladder, Control, Empty)
- Use as HCP reference (anti-HCP western only, see below)
- Delete Lane

**Band options:**
- Edit Properties
- Set Type (Other, MW Reference, POI)
- Set Molecular Weight (writes `estimated_mw_kda`; an unchanged answer sends nothing, since any band save wipes the
  lane's densitometry; `node __tests__/set-mw.test.js`)
- Delete Band

```javascript
const contextMenu = new ContextMenu({
    eventBus: eventBus,
    stateManager: stateManager,
    svg: svgInstance,
    handlesGroup: handlesGroup,
    isEditable: true,
    showMessage: (msg) => { ... },
    onDeleteLane: (id) => { ... },
    onDeleteBand: (id) => { ... },
    onUpdateLane: (id, data) => { ... },
    onUpdateBand: (id, data) => { ... },
    onStartResize: (id) => { ... },
    onSetReferenceLane: (id) => { ... },      // "Use as HCP reference"
    getReferenceContext: () => ({ assay, referenceLaneId, canWrite }),
    getSelectedAnnotation: () => ({ type, id })
});

contextMenu.show(x, y, type, id);
contextMenu.hide();

// Resize handles (called via onStartResize)
contextMenu.showResizeHandles(lane, svg, handlesGroup, scale, onResize);
```

The menu is positioned from its measured size once visible (conditional items change its height).

**"Use as HCP reference"** (`#ctx-set-hcp-ref`, static markup in `annotate_standalone.html`, after the lane types). `_updateReferenceItem` shows it only for a SAMPLE or CONTROL lane when `gel_image.assay.readout === 'HOST_CELL_PROTEINS'`, checks it on the current reference (ids compared with `Number()`) and disables it when `analysis.can_write` is false. `GelViewerApp._setReferenceLane` saves at once — `APIClient.setReadoutReferenceLane(laneId | null)` → `POST /api/analyses/<uuid>/readout-reference/`, which republishes the readouts; clicking the reference clears it; a `temp_` lane is refused with a toast. The context (`GelViewerApp.readout = {assay, referenceLaneId, canWrite}`) is read from `/data/` by `_loadAnnotations` AND `_reloadAnnotations`. `Renderer.setReferenceLane(id)` draws the amber **REF** tag (`.gv-ref-badge`, `pointer-events: none`) and the `.gv-lane--reference` outline; `renderLane` draws it (load, reload, recovery), `updateLane` / `updateLaneNumber` move it, `removeLane` drops it. Never an id starting `lane-` on the badge: lanes are looked up by `#lane-<id>`.

---

### SampleSelector Modal (`modals/sample-selector.js`)

Modal for searching and selecting ProcessSample records.

**Features:**
- Text search across sample names
- Hierarchical filters (Drug Substance -> Process Sheet)
- Free text fallback option
- Integration with Lane Editor and Properties Panel

```javascript
const sampleSelector = new SampleSelector({
    eventBus: eventBus,
    apiClient: apiClient,
    onSampleSelected: (laneId, sampleData) => { ... }
});

sampleSelector.open(laneId);
sampleSelector.close();
sampleSelector.isOpen();
```

---

### ConfirmationManager (`confirmation-manager.js`)

MDB5-free dialogs with a Promise-based API, on the window kit (night and day), registered with `GelViewer.Layers`
(Esc = cancel, never a decision).

**The editor never calls the browser's `confirm` / `alert` / `prompt`** (unthemed, and Esc on them is the browser's):
a question is `show()` or a preset, a value is `prompt()`, a message is a toast (`GelViewerApp.toasts`, or `gaToast`
in the template, which routes there). With no dialog to ask with, a destructive path does nothing, never asks natively.

```javascript
const confirmationManager = new ConfirmationManager();

// Generic confirmation
const confirmed = await confirmationManager.show({
    title: 'Confirm Action',
    body: '<p>Are you sure?</p>',
    confirmText: 'Yes',
    cancelText: 'No',
    danger: true,           // Red button (default) or blue (false)
    icon: 'exclamation-triangle-fill'  // Bootstrap icon
});

// Preset confirmations
await confirmationManager.confirmDetectLanes(existingCount, bandCount);
await confirmationManager.confirmDetectBands(existingCount, laneCount);
await confirmationManager.confirmRemoveAllLanes(laneCount, bandCount);
await confirmationManager.confirmRemoveAllBands(bandCount);
await confirmationManager.confirmRecalibration();
await confirmationManager.confirmDeleteLane(laneNumber, bandCount);
await confirmationManager.confirmDeleteBand(label, laneNumber);   // label escaped: it is the user's text

// One value: what window.prompt answered - the text as typed (the caller parses it) or null (Cancel, Esc, a click beside)
const answer = await confirmationManager.prompt({
    title: 'Set molecular weight',
    label: 'Estimated MW (kDa)',
    value: band.estimated_mw_kda ?? '',
    inputMode: 'decimal',   // a phone's number pad; the field stays text
});
```

A band delete asks in `GelViewerApp._deleteBand`, where every path meets (Delete key, toolbar, context menu,
properties panel, Band Editor): a caller never asks again, and never with `window.confirm`
(`node __tests__/band-delete-confirm.test.js`: the Delete key on a saved band, cancel then confirm). Once the band has
left the state, `_deleteBand` emits `BAND_DELETED` with the band (its one emitter): the Band Editor drops the row, the
toolbar refreshes, and a ladder band marks the MW calibration stale, as editing one does (owner, 2026-10-13).

**Styling:** `show()` fills `#gv-confirm-modal` (the template), restyled on the window kit's tokens; `prompt()` is built
from the kit's own classes (`.gv-win-layer` > `.gv-win-backdrop` + `.gv-win`, `gel_viewer_standalone.css`).

---

## Inference System (Phase 3)

### InferenceEngine (`inference/inference-engine.js`)

Orchestrates YOLO inference using ONNX Runtime Web in a Web Worker.

```javascript
const inferenceEngine = new InferenceEngine({
    eventBus: eventBus,
    modelUrl: '/static/gel_analyzer/ml/gel_analysis.onnx'
});

// Initialize (loads ONNX Runtime + model)
await inferenceEngine.initialize();

// Run inference on image
const detections = await inferenceEngine.runInference(imageElement);
// Returns: [{ bbox: [x,y,w,h], confidence: 0.95, class_name: 'sample_lane', lane_type: 'SAMPLE', polygon: [[x1,y1],...] }]

// Get inferred gel type
const gelType = inferenceEngine.getInferredGelType(detections);
// Returns: 'SDS_PAGE' | 'DOT_BLOT' | 'UNKNOWN'

// Cancel running inference
inferenceEngine.cancel();

// Clean up
inferenceEngine.destroy();
```

**Lazy Loading**: Model is only loaded when `initialize()` is called (first auto-detect).

**Web Worker**: All ONNX operations run in `inference-worker.js` to keep UI responsive.

### InferenceWorker (`inference/inference-worker.js`)

Web Worker for non-blocking ONNX Runtime inference.

**Message Protocol**:
```javascript
// Main thread → Worker
{ type: 'LOAD_MODEL', payload: { modelUrl: '...' } }
{ type: 'RUN_INFERENCE', payload: { imageData: ImageData, config: {...} } }
{ type: 'CANCEL' }

// Worker → Main thread
{ type: 'MODEL_LOADED', payload: { success: true } }
{ type: 'INFERENCE_PROGRESS', payload: { stage: 'preprocessing' | 'inference' | 'postprocess' } }
{ type: 'INFERENCE_COMPLETE', payload: { detections: [...] } }
{ type: 'INFERENCE_ERROR', payload: { error: '...' } }
```

### ReviewPanel (`panels/review-panel.js`)

Review of the lanes the lane model found, **on the gel itself** (Grégory 2026-10-10; it replaced a 260 px floating list that showed five lanes at a time over the gel).

```javascript
const reviewPanel = new ReviewPanel({
    eventBus, stateManager,
    svg,                      // the overlay: outlines in image pixels
    viewport,                 // pan/zoom: tags placed in screen pixels, the gel fitted on show
    onAccept: (detections) => { ... }   // the kept detections, left to right, types as reviewed
});

reviewPanel.show(detections, inferredGelType);   // detections sorted by x, from the 25 % floor
reviewPanel.acceptSelected();  // accept the kept lanes (Ctrl+Enter)
reviewPanel.rejectAll();       // create nothing (Esc)
reviewPanel.hide();
```

- **Bar** (`includes/_review_panel.html`, inside `.gv-viewer-wrapper`): `N of M lanes kept`, the gel type, the
  **Min. confidence** slider, Reject all / Accept N. While it is open the wrapper has `.gv-reviewing`: the viewer
  starts 48 px lower and the gel is fitted with `viewport.fitToView({maxScale: 3, fill: 0.97, padX, padY})` — fuller
  than the editor's 90 %, with room for the tags; `hide()` fits again with the defaults (90 %, capped at 3; the cap
  was 60 % until 2026-10-17, and a gel smaller than the viewer stayed small).
- **On the gel**: each detection is an SVG outline (`.gv-detection-preview.t-<type>`, `.kept` / `.dropped`, `pointer-events: all`
  since the overlay has none); its tag (number among the kept lanes, type) and confidence are HTML in `.gv-review-tags`,
  laid over `.gv-viewer` in screen pixels and moved on `PAN_CHANGED` / `ZOOM_CHANGED` / `VIEWPORT_CHANGED` — SVG text in image
  pixels was a few screen pixels high at fit on a large gel. Tags sit above the middle of a lane's two highest corners,
  so a tilted lane gets its tag above its own top.
- **Threshold**: `gel-viewer.js` builds the `InferenceEngine` with a 25 % floor; the slider starts at
  `ReviewPanel.DEFAULT_THRESHOLD` (50 %, the old cut), so an untouched review keeps what it always kept. Moving it
  re-applies the threshold to every lane; a click overrides it for one lane.
- **Clicks**: a lane toggles kept/dropped (a press that moved more than 4 px was a pan, not a click); a tag opens
  the type menu (the properties panel's six lane types). `_autoDetect` switches to the Select tool before `show()`.
- **Keyboard** (capture phase on `window`): ←/→ focus, Space toggle, Enter type menu, Ctrl+Enter accept, Esc closes
  the menu, else rejects. The editor's letter shortcuts are held back while the review is open; zoom (`+ - 0`),
  Tab and browser chords pass.
- **Straight / Follow the lanes** (spec `docs/superpowers/specs/2026-10-10-gel-lane-tilt-design.md` §10, opt-in after
  the bench of §9). `show()` posts every detection's `{index, box, mask_slope}` with a token to `lanes/tilt/`
  (`apiClient.measureLaneTilt`, `AbortController`, 10 s); a reply is applied only to the review that sent it
  (`hide()` bumps the token and aborts). The bar's segmented control (`#review-shape-straight` / `#review-shape-follow`)
  opens on Straight; Follow becomes clickable once a lane is tilted (the server's `source` not `straight`). In both
  modes `_computeShapes()` draws every lane **as it will be saved**: its box or its axis, cut at the common top and
  bottom of the KEPT lanes (recomputed on every keep/drop/slider move), clamped and rounded; `getSelectedDetections()`
  hands those outlines to `_acceptDetections` with `lane_shape` `QUADRILATERAL` when tilted, else `POLYGON` — so Accept
  never waits and the post-create `_normalizeLaneHeights()` is gone. `#review-cross` warns when two kept lanes overlap by
  more than a quarter of their summed widths (their central profiles would read the same pixels).
- **The worker's mask slope**: `inference-worker.js::maskSlope` fits each kept detection's OWN mask row centres before
  the 20 % shrink rewrites its box — `tools/proofs/lane_tilt/capture.js::maskAxes` verbatim, the fit the bench
  validated (parity: 88 detections, 2.3e-16) — and `scaleDetections` sends it in image space as `mask_slope`. Never
  "simplify" it.
- **Normalize heights** (`gel-viewer.js::_normalizeLaneHeights`): a 4-point lane's sides are extended or cut as lines
  (`_extendQuad`), so a tilted lane keeps its slope; its box follows.

---

## Events System

### Event Flow Examples

**Creating a Lane:**
```
User draws rectangle
    → LaneTool.onMouseUp()
    → GelViewerApp._createLane()
    → StateManager.setLane()
    → StateManager.trackLaneCreation()
    → StateManager.markDirty()
    → EventBus.emit(STATE_DIRTY), EventBus.emit(PENDING_CHANGED) → GelViewerApp._refreshStatus()
    → Renderer.renderLane()
    → EventBus.emit(LANE_CREATED)
    → PropertiesPanel updates
    → DataTablePanel updates
```

**Selecting an Annotation:**
```
User clicks lane
    → Renderer click handler
    → GelViewerApp._selectAnnotation()
    → StateManager.setSelection()
    → EventBus.emit(SELECTION_CHANGED)
    → PropertiesPanel.showLane()
    → DataTablePanel.highlightRow()
    → Renderer.selectAnnotation() // visual highlight
```

**Saving Changes:**
```
User clicks Save button
    → GelViewerApp._batchSave()
    → For each pending lane create: APIClient.createLane()
    → For each pending lane update: APIClient.updateLane()
    → For each pending lane delete: APIClient.deleteLane()
    → (same for bands)
    → StateManager.markClean()
    → EventBus.emit(SAVE_COMPLETED)
    → StateManager.clearLocalStorage()
```

---

## Data Flow

### Hybrid Save Approach

The viewer uses a hybrid save approach:
- **Lanes**: Changes tracked locally, saved to server on explicit "Save" click
- **Bands**: Created and type-changed immediately (fire-and-forget), other changes batched

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────┐
│   User Action   │────►│   StateManager   │────►│  localStorage │
│  (draw, edit)   │     │  (track change)  │     │   (backup)    │
└─────────────────┘     └────────┬─────────┘     └──────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
                    ▼                         ▼
         ┌──────────────────┐      ┌──────────────────┐
         │  Immediate Save  │      │   Batch Save     │
         │ (band create/    │      │ (user clicks     │
         │  type change)    │      │  "Save" button)  │
         └────────┬─────────┘      └────────┬─────────┘
                  │                         │
                  └────────────┬────────────┘
                               ▼
                      ┌──────────────────┐
                      │  Django Backend  │
                      │   (database)     │
                      └──────────────────┘
```

### Immediate Band Operations (Fire-and-Forget)

Band creation and type changes are saved immediately to the server without requiring the user to click "Save":

```javascript
// Band Creation - immediate POST
_createBand(laneId, data) {
    const tempId = stateManager.generateTempId();
    // ... create local band with tempId ...

    // Immediate async save (fire-and-forget)
    apiClient.createBand(laneId, bandData).then(result => {
        stateManager.replaceBandId(tempId, result.id);  // Replace temp → real ID
        band._isNew = false;
    }).catch(error => {
        // Band stays local, will be saved on batch Save
    });
}

// Band Type Change - immediate PUT
_updateBand(id, data) {
    // ... update local state ...

    // Immediate async save for persisted bands
    if (!id.startsWith('temp_')) {
        apiClient.updateBand(id, data).catch(error => {
            // Change stays in pending, will sync on batch Save
        });
    }
}
```

**Benefits:**
- Changes persist without explicit save
- UI stays responsive (non-blocking)
- Graceful fallback to batch save on network errors
- State automatically marked clean when no pending changes

### Temporary IDs

New annotations use temporary IDs (`temp_1_1704067200000`) until saved:

```javascript
// Before save
lane.id = 'temp_1_1704067200000'
lane._isNew = true

// After save (or immediate band save)
const { id } = await api.createLane(laneData);
lane.id = 123  // Real server ID
lane._isNew = false
```

---

## CSS Architecture

### Files

| File | Purpose |
|------|---------|
| `gel_viewer.css` | Main styles (Bootstrap integration) |
| `gel_viewer_standalone.css` | Clean styles (no Bootstrap) |

### CSS Prefixes

| Prefix | Component |
|--------|-----------|
| `.gv-*` | GelViewer general |
| `.gv-lane` | Lane annotations |
| `.gv-band` | Band annotations |
| `.gv-table-*` | Lane Editor panel |
| `.gv-band-table-*` | Band Editor panel |

### Key Classes

```css
/* Viewer container */
.gv-container
.gv-viewer
.gv-canvas-container
.gv-svg-overlay

/* Annotations */
.gv-lane                    /* Base lane class */
.gv-lane.sample             /* Sample lane type */
.gv-lane.ladder             /* Ladder lane type */
.gv-lane.control            /* Control lane type */
.gv-lane.empty              /* Empty lane type */
.gv-lane.selected           /* Selected state */
.gv-lane-label              /* Lane number label */

.gv-band                    /* Base band class */
.gv-band.other              /* Other band type */
.gv-band.mw_reference       /* MW Reference type */
.gv-band.poi                /* Protein of Interest */
.gv-band.selected           /* Selected state */
.gv-band.gv-band-split      /* Red dashed stroke — bands with metadata.hybrid_phase='split' */
.gv-band.gv-band-cross-lane /* Bands with metadata.hybrid_phase='cross_lane_filled' */

/* Lane Editor (right panel) */
.gv-table-panel             /* Container */
.gv-table-panel.open        /* Visible state */
.gv-table-header            /* Blue header */
.gv-table-body              /* Scrollable content */
.gv-data-table              /* Table element */
.gv-table-footer            /* Footer with buttons */

/* Band Editor (left panel) */
.gv-band-table-panel        /* Container */
.gv-band-table-panel.open   /* Visible state */
.gv-band-table-header       /* Teal/cyan header */
.gv-band-table-content      /* Scrollable content */
.gv-band-table              /* Table element */
.gv-band-table-footer       /* Footer */

/* Toolbar */
.gv-toolbar
.gv-toolbar-btn
.gv-toolbar-btn.active

/* Hide backgrounds mode */
.gv-svg-overlay.backgrounds-hidden .gv-lane,
.gv-svg-overlay.backgrounds-hidden .gv-band {
    fill: transparent !important;
}
```

### Panel Positioning

```
┌──────────────────────────────────────────┐
│              GelViewer                   │
│                                          │
│ ┌──────────┐              ┌────────────┐ │
│ │  BAND    │              │    LANE    │ │
│ │  EDITOR  │              │   EDITOR   │ │
│ │  (Teal)  │              │   (Blue)   │ │
│ │ ← Left   │              │   Right →  │ │
│ │  z:105   │              │   z:100    │ │
│ └──────────┘              └────────────┘ │
└──────────────────────────────────────────┘
```

---

## Keyboard Shortcuts

| Key | Action | Prerequisites |
|-----|--------|---------------|
| `V` | Select tool | - |
| `H` | Pan tool (Hand) | - |
| `L` | Lane tool (Rectangle) | - |
| `Q` | Lane tool (Quadrilateral) | - |
| `P` | Lane tool (Polygon) | - |
| `B` | Band tool | Requires lanes |
| `S` | Split tool | Requires band selected |
| `D` | Auto-Detect lanes (YOLO) | - |
| `Shift+D` | Toggle Detection Panel | Requires lanes |
| `Shift+Y` | Toggle the band model panel (YOLO bands) | Requires lanes |
| `C` | Toggle Calibration Panel | Requires ladder lanes with bands |
| `M` | Toggle MW Lines | Requires calibration |
| `T` | Toggle Lane Editor | - |
| `E` | Toggle Band Editor | - |
| `F` | Toggle annotation fills | - |
| `A` | Toggle image adjustments | - |
| `Delete` / `Backspace` | Delete selected | Requires selection |
| `Shift+F10` / `ContextMenu` | Open the selection's context menu over it, the focus in the menu | Requires selection |
| `Escape` | Close a panel / menu / dialog, cancel drawing, deselect; idle (`GelViewerApp.isIdle()`): back to the analysis | - |
| `Enter` | Finish polygon / Accept detections | - |
| `Ctrl+S` / `Cmd+S` | Save changes | - |
| `0` | Fit to view | - |
| `+` / `-` | Zoom in/out | - |

**Note**: Shortcuts with prerequisites show feedback messages when blocked (e.g., "Create lanes first"). Letter
shortcuts are bare keys (Shift allowed): with Ctrl / Cmd / Alt the key is the browser's (`EventHandler._onKeyDown`).
Every window and menu registers with `GelViewer.Layers` (`layers.js`, loaded before every panel) from its own
show / hide: Esc closes the top layer only and never decides, a modal layer keeps Tab and the editor's keys,
the focus goes in and comes back. A new window calls `GelViewer.Layers.open(el, {close, isOpen, modal,
initialFocus})` / `close(el)` and adds no Esc listener of its own. With no layer open, Esc leaves the editor only
from `GelViewerApp.isIdle()` (a capture-phase listener in `annotate_standalone.html`).
`node __tests__/layers-esc.test.js` holds the rule on the real `layers.js` and `ConfirmationManager`: one Esc closes
the top window only, a confirm closed by Esc answers "cancel" without a click on Cancel (the backup restore reads
that click as Discard), and a modal keeps Delete and Ctrl+S from the editor while it is open.

### Electropherogram Panel Mouse Shortcuts

When the electropherogram panel is open, Ctrl and Shift enable direct-manipulation shortcuts on the D3.js chart. A thin red DOM cursor guide + precise SVG crosshair follow the pointer whenever a modifier is held.

| Gesture | Action |
|---------|--------|
| `Ctrl+click` (empty area) | Create band at clicked Y |
| `Ctrl+click` (inside existing band) | Split the band at Y (delete + create upper + lower) |
| `Shift+click & drag` | Create range-band spanning the drag |
| `Esc` | Cancel in-progress drag |
| Header `?` button | Show shortcut popover |

Status toast reports "Splitting…" / "Band split" / "Split failed" inline. Split children are stamped with `metadata.hybrid_phase = "split"` and rendered with the `.gv-band-split` CSS class (red dashed stroke).

---

## API Endpoints

### Analysis Data

```
GET /gel-analyzer/api/analyses/{uuid}/data/
Response: {
    lanes: [
        {
            id: 123,
            lane_number: 1,
            lane_type: "SAMPLE",
            lane_shape: "RECTANGLE",
            x: 100, y: 50, width: 80, height: 400,
            polygon: null,
            sample_name: "Sample 1",
            process_sample: { "id": 39, "sample_id": "T033HPV16Ea-DMAE-W001" },  // or null
            bands: [...]
        }
    ]
}
```

### Lane CRUD

```
POST /gel-analyzer/api/analyses/{uuid}/lanes/
Body: { lane_type, x, y, width, height, polygon, detection_source, confidence, ... }
Response: { lane: { id: 123, ... } }

PUT /gel-analyzer/api/lanes/{id}/
Body: { lane_type, sample_name, ... }

DELETE /gel-analyzer/api/lanes/{id}/
```

### Bulk Operations (Phase 3)

```
POST /gel-analyzer/api/analyses/{uuid}/lanes/bulk/
Body: { lanes: [{ lane_type, x, y, width, height, polygon, detection_source, confidence, ... }, ...] }
Response: { success: true, lanes: [...], count: N }

PUT /gel-analyzer/api/analyses/{uuid}/lanes/bulk-update/
Body: { lanes: [{ id, lane_type, sample_name, ... }, ...] }
Response: { success: true, lanes: [...], count: N }

POST /gel-analyzer/api/analyses/{uuid}/lanes/bulk-delete/
Body: { lane_ids: [1, 2, 3] }
Response: { success: true, deleted_count: N, lanes: [...] }

POST /gel-analyzer/api/analyses/{uuid}/yolo-results/
Body: { detections: [...], inferred_gel_type: 'SDS_PAGE' }
Response: { success: true }
```

### Band CRUD

```
POST /gel-analyzer/api/lanes/{lane_id}/bands/
Body: { polygon, band_type, estimated_mw_kda, ... }
Response: { band: { id: "uuid", ... } }

PUT /gel-analyzer/api/bands/{uuid}/
Body: { band_type, estimated_mw_kda, ... }

DELETE /gel-analyzer/api/bands/{uuid}/
```

### Sample Search

```
GET /gel-analyzer/api/samples/search/?q=Pool&drug_substance=1&sheet=5
Response: {
    samples: [
        { id: 456, name: "Pool-1", ... }
    ]
}

GET /gel-analyzer/api/samples/filter-options/
Response: {
    drug_substances: [{ id: 1, name: "mAb-001" }],
    sheets: [{ id: 5, name: "Sheet-001", drug_substance_id: 1 }]
}
```

---

## Cross-Navigation

The editor wears the gel workbench header (`workbench/_identity.html`, `active='annotate'`, `theme=False` until the
editor has a day mode): back to the analysis, crumbs, the analysis name, status and assay, and the views of the
analysis — Analysis · Annotate · Densitometry.

On this page Densitometry is always the link `#ga-wb-view-densitometry`: `_updateToolbarState` greys it (`.is-off`,
`aria-disabled`, title from `data-title-off`) while the gel has no band, live, and the template refuses a click on it
greyed with that title as the reason (a greyed link would still follow).

Save sits at the right end of the toolbar (`.gv-toolbar-save`): `#unsaved-indicator` ("N unsaved changes",
`StateManager.pendingCount()`, `hidden` at 0) and `#save-btn` (`.has-changes`, `.saving`, `.saved`), both written by
`GelViewerApp._refreshStatus()` with the status bar's `#lane-count` / `#band-count`.

The dialogs wear the window kit on the workbench tokens (`--ga-wb-*`, night on `:root`, day on
`:root[data-theme="light"]`): a 44 px header with a neutral border, one primary button at a time, the accent kept
for focus, hover and a chosen item, texts no smaller than 11 px. A chart drawn by script reads its colours from the
tokens when it draws (`calibration-panel.js` `_chartTheme()`, `electropherogram-panel.js` `_plotTheme()`) and is
relaid out on the window event `dsh:themechange` (the zoom stays). Data colours (the profile, the derivatives, band
regions, the gel's lane and band types) are not tokens and read the same night and day.

---

## Development Guide

### Adding a New Tool

1. Create file in `tools/new-tool.js`:

```javascript
(function(global) {
    'use strict';

    class NewTool {
        constructor(options) {
            this.eventBus = options.eventBus;
            // ...
        }

        activate() { /* Called when tool selected */ }
        deactivate() { /* Called when switching away */ }
        cancel() { /* Called on Escape */ }

        onMouseDown(e, point) { }
        onMouseMove(e, point) { }
        onMouseUp(e, point) { }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.NewTool = NewTool;
})(window);
```

2. Register in `gel-viewer.js`:

```javascript
const newTool = new NewTool({ ... });
this.toolManager.registerTool('newtool', newTool);
```

3. Add toolbar button in HTML with `data-tool="newtool"`

4. Add keyboard shortcut in `event-handler.js`

### Adding a New Event

1. Add to `Events` object in `event-bus.js`:

```javascript
const Events = {
    // ...
    NEW_EVENT: 'new:event',
};
```

2. Emit from source:

```javascript
this.eventBus.emit(Events.NEW_EVENT, { data });
```

3. Subscribe in listeners:

```javascript
this.eventBus.on(Events.NEW_EVENT, (data) => {
    // Handle event
});
```

### Adding a New Panel

1. Create pre-rendered HTML in template (avoid DOM race conditions)
2. Create JS class in `panels/new-panel.js`
3. Get DOM references in constructor: `document.getElementById('...')`
4. Subscribe to relevant events
5. Export to `GelViewer.NewPanel`

### Debugging Tips

```javascript
// Enable verbose logging
localStorage.setItem('gelViewer_debug', 'true');

// Log all events
eventBus.on('*', (event, data) => console.log(event, data));

// Check state
console.log('Lanes:', stateManager.lanes);
console.log('Bands:', stateManager.bands);
console.log('Pending:', stateManager.pendingChanges);
console.log('Dirty:', stateManager.isDirty);

// Write the crash backup now (the pending changes only)
stateManager.saveToLocalStorage();

// Clear localStorage
stateManager.clearLocalStorage();
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Jan 2026 | Initial release with lane/band annotation |
| 1.1 | Jan 2026 | Added quadrilateral and polygon lane shapes |
| 1.2 | Jan 2026 | Added Band Editor panel (left slide) |
| 1.3 | Jan 2026 | Lane Editor moved to right slide, compact styling |
| 1.4 | Jan 2026 | Band Editor teal/cyan color scheme |
| 2.0 | Jan 2026 | **Phase 3**: YOLO inference, review panel, bulk APIs |
| 2.1 | Jan 2026 | Toolbar safeguards, ConfirmationManager, Pharma Corporate styling |
| 2.2 | Jan 2026 | Multi-ladder MW calibration with position-aware interpolation |
| 2.3 | Jan 2026 | **Immediate band persistence**: Band creation and type changes save immediately (fire-and-forget) |
| 2.4 | Feb 2026 | **ProcessSample display**: Show `process_sample.sample_id` in properties panel, lane editor, annotation sidebar, and densitometry labels with flask icon |
| 3.0 | Apr 2026 | **Phase 10**: HybridDetectionPanel + CrossLaneConsensusPanel, electropherogram keyboard shortcuts (Ctrl+click, Shift+drag, Esc), custom DOM cursor guide + SVG crosshair, status toast, `.gv-band-split` / `.gv-band-cross-lane` CSS, Band.metadata JSONField persistence, `HYBRID_DETECTION_PANEL_*` + `CROSS_LANE_PANEL_*` events, Profile d1/d2 + CV2 Vision toolbar buttons hidden |

---

## Related Documentation

- [Gel Analyzer module README](../../../../docs/README.md) — Django app documentation
- [Phoresis architecture](../../../../../../docs/ARCHITECTURE.md) — system overview, data flow, container layout
