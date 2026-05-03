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
│   ├── profile-detection-panel.js     # UNPLUGGED profile peak detection
│   ├── hybrid-detection-panel.js      # Hybrid Detection (CV2 + d1/d2 cascade)
│   ├── cross-lane-consensus-panel.js  # Cross-Lane Consensus (anchor-based smile correction)
│   ├── electropherogram-panel.js      # Inline electropherogram + Ctrl/Shift shortcuts
│   ├── context-menu.js                # Right-click context menu
│   ├── review-panel.js                # YOLO detection review panel
│   └── teacher-panel.js               # Detection teaching/calibration
│
├── inference/                   # Phase 3: YOLO inference
│   ├── inference-engine.js     # Main orchestrator, lazy model loading
│   ├── inference-worker.js     # Web Worker for ONNX Runtime
│   ├── inference-utils.js      # Image preprocessing utilities
│   └── postprocess.js          # NMS, detection parsing
│
└── modals/
    └── sample-selector.js      # ProcessSample search modal
```

### Script Load Order

Scripts must be loaded in this order in HTML:

```html
<!-- Core (order matters) -->
<script src=".../event-bus.js"></script>
<script src=".../state-manager.js"></script>
<script src=".../api-client.js"></script>
<script src=".../viewport.js"></script>
<script src=".../renderer.js"></script>
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
<script src=".../panels/hybrid-detection-panel.js"></script>
<script src=".../panels/cross-lane-consensus-panel.js"></script>
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
Events.HYBRID_DETECTION_PANEL_SHOWN    // 'hybrid_detection_panel:shown'
Events.HYBRID_DETECTION_PANEL_HIDDEN   // 'hybrid_detection_panel:hidden'
Events.CROSS_LANE_PANEL_SHOWN          // 'cross_lane_panel:shown'
Events.CROSS_LANE_PANEL_HIDDEN         // 'cross_lane_panel:hidden'
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

#### ID Replacement (Temp → Server)

When bands are created, they get a temporary ID until saved to the server:

```javascript
// Replace temp ID with real server ID after immediate save
stateManager.replaceBandId(oldTempId, newServerId);
// Updates bands Map, parent lane's bands array, and SVG element
```

#### LocalStorage Persistence

Crash recovery saves state to localStorage on every change:

```javascript
// Auto-saved on markDirty()
localStorage.setItem(`gelViewer_${analysisId}`, JSON.stringify({
    analysisId: 'uuid',
    timestamp: Date.now(),
    lanes: [...],
    bands: [...],
    pendingChanges: {...}
}));

// Restored on page load (if < 24 hours old)
const recovered = stateManager.loadFromLocalStorage();
if (recovered) {
    // Apply recovered changes to UI
}

// Cleared on successful save
stateManager.clearLocalStorage();
```

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

// Update sidebar list
renderer.updateAnnotationsList();
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

Lanes can be resized after creation via two methods:

**Interactive Resize (Context Menu):**
- Right-click a lane → "Resize Lane"
- Four corner drag handles appear (NW, NE, SW, SE)
- Drag any handle to resize; minimum size enforced (20px)
- Handles scale with zoom level for consistent interaction
- Calls `_updateLane()` on mouse-up with final dimensions
- If X position changes, lane numbers are recalculated

**Numeric Resize (Properties Panel):**
- Select a lane to open the Properties Panel
- Edit X, Y, Width, Height fields in the "Dimensions" section
- Changes apply in real-time with debounced updates
- SVG updates immediately via `renderer.updateLane()`

Both methods work with rectangle and polygon shapes. For polygons, the renderer calls `element.plot(lane.polygon)` instead of `element.move().size()`.

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

```javascript
const bandTablePanel = new BandTablePanel({
    eventBus: eventBus,
    stateManager: stateManager,
    onSelectBand: (bandId) => { ... },
    onUpdateBand: (id, data) => { ... },
    onDeleteBand: (id) => { ... }
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
- Band list for selected lane
- Dimension editing (X, Y, Width, Height) with live SVG update

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

### HybridDetectionPanel (`panels/hybrid-detection-panel.js`)

UI for the Hybrid Detection algorithm (CV2 primary + d1/d2 gap-fill cascade). Sensitivity slider (1-10) plus 5 feature toggles:

| Toggle | Parameter | Effect |
|--------|-----------|--------|
| Faint Bands | `faint_bands` | Lowers SNR threshold in gap-fill phase |
| Large Bands | `large_bands` | Expands max band height search window |
| Split Wide Bands | `split_wide_bands` | Runs `find_peaks` sub-detection (≥15% amplitude prominence) on each detected band |
| Mask Loading Wells | `mask_loading_wells` | Masks top 12% + grows cap to 15% when detecting wells |
| Adaptive Threshold | `adaptive_threshold` | 3-zone MAD-based per-zone CV2 threshold |

**Async save with progress polling**: clicking Save dispatches the `detect_bands_hybrid_bulk_task` Celery task and polls for progress, surfacing stage/percent to the user instead of blocking the UI. Emits `Events.HYBRID_DETECTION_PANEL_SHOWN` / `_HIDDEN` and closes when `CROSS_LANE_PANEL_SHOWN` fires (mutual exclusivity).

---

### CrossLaneConsensusPanel (`panels/cross-lane-consensus-panel.js`)

UI for the Cross-Lane Consensus post-processing pass. Sliders for `min_lane_support`, `y_tolerance`, `snr_threshold`, and smile parameters. Three action buttons:

| Button | Behaviour |
|--------|-----------|
| Preview | `POST /analyses/<uuid>/cross-lane-consensus/` with `dry_run: true`; renders candidate bands as ghosts without persisting |
| Apply | Same endpoint with `dry_run: false`; persists new/adjusted bands stamped with `metadata.consensus_run_id` |
| Undo | `DELETE /analyses/<uuid>/cross-lane-consensus/?run_id=<uuid>`; available for 5 minutes after an apply |

Emits `Events.CROSS_LANE_PANEL_SHOWN` / `_HIDDEN`. CSS prefix `.gv-clc-*`. Mutually exclusive with `HybridDetectionPanel`.

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

**Lane options:**
- Edit Properties
- Resize Lane (shows drag handles)
- Set Type (Sample, Ladder, Control, Empty)
- Delete Lane

**Band options:**
- Edit Properties
- Set Type (Other, MW Reference, POI)
- Set Molecular Weight
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
    getSelectedAnnotation: () => ({ type, id })
});

contextMenu.show(x, y, type, id);
contextMenu.hide();

// Resize handles (called via onStartResize)
contextMenu.showResizeHandles(lane, svg, handlesGroup, scale, onResize);
```

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

MDB5-free confirmation dialogs with Promise-based API and "Pharma Corporate" styling.

**Features:**
- Works without MDB5 using inline CSS fallback
- Professional blue gradient headers
- Pill-shaped buttons with hover effects
- Blur backdrop effect
- Preset methods for common confirmations

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
```

**Styling (Pharma Corporate):**
- Header: Gradient background (#0d6efd → #0856d6 or red for danger)
- Content: Clean white with blue-highlighted text
- Buttons: Pill-shaped (50px radius) with shadow
- Backdrop: Dark with blur effect
- Info boxes: Gradient backgrounds with colored borders

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

Panel for reviewing and accepting/rejecting YOLO detections.

```javascript
const reviewPanel = new ReviewPanel({
    eventBus: eventBus,
    stateManager: stateManager,
    renderer: renderer,
    onAccept: (detections) => { ... }
});

// Show panel with detections
reviewPanel.show(detections, inferredGelType);

// Actions
reviewPanel.acceptAll();       // Accept all detections
reviewPanel.acceptSelected();  // Accept only checked items
reviewPanel.rejectAll();       // Discard all and close

// Hide panel
reviewPanel.hide();
```

**Features**:
- Checkbox list of all detections
- Confidence scores and class badges
- Detection preview on canvas (dashed outline)
- Accept All / Accept Selected / Reject All buttons
- Keyboard: `Enter` to accept selected, `Escape` to reject all

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
    → EventBus.emit(STATE_DIRTY)
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
| `C` | Toggle Calibration Panel | Requires ladder lanes with bands |
| `M` | Toggle MW Lines | Requires calibration |
| `T` | Toggle Lane Editor | - |
| `E` | Toggle Band Editor | - |
| `F` | Toggle annotation fills | - |
| `A` | Toggle image adjustments | - |
| `Delete` / `Backspace` | Delete selected | Requires selection |
| `Escape` | Cancel drawing / Close panel | - |
| `Enter` | Finish polygon / Accept detections | - |
| `Ctrl+S` / `Cmd+S` | Save changes | - |
| `0` | Fit to view | - |
| `+` / `-` | Zoom in/out | - |

**Note**: Shortcuts with prerequisites show feedback messages when blocked (e.g., "Create lanes first").

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

The annotation toolbar includes navigation buttons to related views:

| Button | Icon | CSS Class | Target | Condition |
|--------|------|-----------|--------|-----------|
| **Densitometry** | `bi-bar-chart-line` | `.gv-densitometry-btn` | Densitometry view | Disabled if no bands detected (`total_bands == 0`) |
| **View Results** | `bi-eye` | `.gv-action-btn` | Analysis detail | Always available |
| **Save** | `bi-save` | `.gv-save-btn` | (action) | Always available |

The **Densitometry** button uses a green background (`.gv-densitometry-btn`) to distinguish it as a module-switch action. When disabled (no bands), it uses `.gv-action-btn-disabled` with `opacity: 0.4` and `pointer-events: none`.

```html
<!-- In annotate_standalone.html toolbar -->
{% if analysis.total_bands > 0 %}
<a href="{% url 'gel_analyzer:analysis_densitometry' pk=analysis.pk %}"
   class="gv-action-btn gv-densitometry-btn"
   data-tooltip="Densitometry Analysis">
    <i class="bi bi-bar-chart-line"></i>
    <span>Densitometry</span>
</a>
{% else %}
<span class="gv-action-btn gv-action-btn-disabled"
      data-tooltip="Requires bands to be detected first">
    <i class="bi bi-bar-chart-line"></i>
    <span>Densitometry</span>
</span>
{% endif %}
```

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

// Force save to localStorage
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

- [Gel Analyzer Module README](../../README.md) - Django app documentation
- [CLAUDE.md](../../../../../CLAUDE.md) - Project-wide guidance
