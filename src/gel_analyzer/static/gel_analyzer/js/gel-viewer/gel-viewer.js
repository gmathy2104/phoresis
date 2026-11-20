/**
 * GelViewer - Main Orchestrator
 *
 * Coordinates all modules for the gel annotation viewer.
 * Uses EventBus for loose coupling between components.
 *
 * @requires SVG.js 3.x (https://svgjs.dev/)
 */

(function(global) {
    'use strict';

    // Import from namespace
    const EventBus = global.GelViewer.EventBus;
    const Events = global.GelViewer.Events;
    const APIClient = global.GelViewer.APIClient;
    const StateManager = global.GelViewer.StateManager;
    const Viewport = global.GelViewer.Viewport;
    const Renderer = global.GelViewer.Renderer;
    const CornerHandles = global.GelViewer.CornerHandles;
    const EventHandler = global.GelViewer.EventHandler;
    const ToolManager = global.GelViewer.ToolManager;
    const LaneTool = global.GelViewer.LaneTool;
    const BandTool = global.GelViewer.BandTool;
    const SplitTool = global.GelViewer.SplitTool;
    const SelectTool = global.GelViewer.SelectTool;
    const PanTool = global.GelViewer.PanTool;
    const CropTool = global.GelViewer.CropTool;
    const PropertiesPanel = global.GelViewer.PropertiesPanel;
    const DataTablePanel = global.GelViewer.DataTablePanel;
    const BandTablePanel = global.GelViewer.BandTablePanel;
    const AdjustmentsPanel = global.GelViewer.AdjustmentsPanel;
    const ContextMenu = global.GelViewer.ContextMenu;
    // Phase 3: YOLO Inference
    const InferenceEngine = global.GelViewer.InferenceEngine;
    const ReviewPanel = global.GelViewer.ReviewPanel;
    // Phase 3: Auto Detection & MW Calibration
    const DetectionPanel = global.GelViewer.DetectionPanel;
    const CV2DetectionPanel = global.GelViewer.CV2DetectionPanel;
    const BandModelPanel = global.GelViewer.BandModelPanel;
    const CalibrationPanel = global.GelViewer.CalibrationPanel;
    // Electropherogram Panel (D3.js)
    const ElectropherogramPanel = global.GelViewer.ElectropherogramPanel;
    // Phase 3: MobileSAM Polygon Refinement
    const SAMDecoderEngine = global.GelViewer.SAMDecoderEngine;
    // Confirmation dialogs
    const ConfirmationManager = global.GelViewer.ConfirmationManager;
    // A ladder's MW values from a template: the lane form's Apply and the Band editor's
    const LadderTemplateApply = global.GelViewer.LadderTemplateApply;

    /**
     * GelViewer Main Class
     */
    class GelViewerApp {
        /**
         * @param {Object} options
         * @param {string} options.containerId - Container element ID
         * @param {string} options.analysisId - Analysis UUID
         * @param {string} options.imageUrl - Gel image URL
         * @param {string} options.imageProxyUrl - Proxy URL for CORS
         * @param {number} options.imageWidth - Image width
         * @param {number} options.imageHeight - Image height
         * @param {string} options.csrfToken - CSRF token
         * @param {boolean} options.isEditable - Allow editing
         */
        constructor(options) {
            this.options = options;
            this.analysisId = options.analysisId;
            this.isEditable = options.isEditable !== false;

            // Core instances
            this.eventBus = new EventBus();
            // Shared AutoSave helper — every fire-and-forget API call in
            // the app goes through this.autoSave.run(...) so error toasts,
            // success/failure events, and inline retry feedback stay
            // consistent across panels. Defined at boot so module
            // constructors below can capture it.
            this.autoSave = (window.PhoresisShared && window.PhoresisShared.AutoSave)
                ? window.PhoresisShared.AutoSave.create({
                    eventBus: this.eventBus,
                    showToast: (msg) => this._showMessage(msg),
                })
                : null;
            this.svg = null;

            // SVG groups
            this.lanesGroup = null;
            this.bandsGroup = null;
            this.calibrationLinesGroup = null;
            this.handlesGroup = null;
            this.drawingGroup = null;

            // DOM elements
            this.container = null;
            this.viewer = null;
            this.canvasContainer = null;

            // Module instances (initialized in _init)
            this.apiClient = null;
            this.stateManager = null;
            this.viewport = null;
            this.renderer = null;
            this.eventHandler = null;
            this.toolManager = null;
            // Bottom-right toast stack (top-left covered the header's back arrow) — pending/success/error feedback.
            // Built lazily here so any code path that runs before _init can
            // still call this.toasts.* without a null check.
            this.toasts = (global.GelViewer && global.GelViewer.ToastManager)
                ? new global.GelViewer.ToastManager({ position: 'bottom-right' })
                : null;
            this.propertiesPanel = null;
            this.dataTablePanel = null;
            this.bandTablePanel = null;
            this.adjustmentsPanel = null;
            this.contextMenu = null;

            // Phase 3: YOLO Inference
            this.inferenceEngine = null;
            this.reviewPanel = null;

            // Phase 3: Auto Detection & MW Calibration
            this.detectionPanel = null;
            this.calibrationPanel = null;
            // Electropherogram Panel
            this.electropherogramPanel = null;
            // The server's reading of the annotations (/data/ page_summary; slice 3c), its refresh timer and order
            this.reading = null;
            this._readingTimer = null;
            this._readingSeq = 0;
            this._batchSaving = false;
            // Teacher Panel (band detection calibration)
            this.teacherPanel = null;

            // Phase 3: MobileSAM Polygon Refinement
            this.samDecoderEngine = null;

            // Confirmation dialogs
            this.confirmationManager = null;

            // Selection state
            this.selectedType = null;
            this.selectedId = null;

            // Display state
            this.backgroundsHidden = false;

            // MW calibration lines state
            this.showMWLines = false;
            this.calibrationData = null;

            // Western readout context, refreshed from every annotations load
            // (_applyReadoutContext): the image's assay {id, name, readout},
            // the anti-HCP reference lane id, and whether the user may write.
            this.readout = { assay: null, referenceLaneId: null, canWrite: false };

            // Initialize
            this._init();
        }

        /**
         * Initialize the viewer.
         */
        _init() {
            this.container = document.getElementById(this.options.containerId);
            if (!this.container) {
                console.error('GelViewer: Container not found:', this.options.containerId);
                return;
            }

            this._setupDOM();
            this._initModules();
            this._wireEventBus();
            this._loadAnnotations();

            console.log('GelViewer initialized', {
                analysisId: this.analysisId,
                imageSize: `${this.options.imageWidth}x${this.options.imageHeight}`,
                isEditable: this.isEditable
            });
        }

        /**
         * Setup DOM elements and SVG.
         */
        _setupDOM() {
            this.viewer = this.container.querySelector('.gv-viewer');
            this.canvasContainer = this.container.querySelector('.gv-canvas-container');

            if (!this.viewer) {
                console.error('GelViewer: .gv-viewer element not found in container', {
                    containerId: this.options.containerId,
                    container: this.container,
                    innerHTML: this.container?.innerHTML?.substring(0, 500)
                });
            }
            if (!this.canvasContainer) {
                console.error('GelViewer: .gv-canvas-container element not found in container');
            }

            // Create SVG overlay
            const svgContainer = this.container.querySelector('.gv-svg-overlay');
            if (!svgContainer) {
                console.error('GelViewer: .gv-svg-overlay element not found');
                return;
            }
            this.svg = SVG(svgContainer).size(this.options.imageWidth, this.options.imageHeight);

            // Create SVG layers
            this.lanesGroup = this.svg.group().attr('id', 'lanes-layer');
            this.bandsGroup = this.svg.group().attr('id', 'bands-layer');
            this.calibrationLinesGroup = this.svg.group().attr('id', 'calibration-lines-layer');
            this.handlesGroup = this.svg.group().attr('id', 'handles-layer');
            this.drawingGroup = this.svg.group().attr('id', 'drawing-layer');
        }

        /**
         * Initialize all modules.
         */
        _initModules() {
            // Core modules
            this.apiClient = new APIClient({
                analysisId: this.analysisId,
                imageId: this.options.imageId,
                csrfToken: this.options.csrfToken,
                eventBus: this.eventBus
            });

            this.stateManager = new StateManager({
                analysisId: this.analysisId,
                eventBus: this.eventBus
            });

            this.viewport = new Viewport({
                viewer: this.viewer,
                canvasContainer: this.canvasContainer,
                svg: this.svg,
                imageWidth: this.options.imageWidth,
                imageHeight: this.options.imageHeight,
                eventBus: this.eventBus
            });

            this.renderer = new Renderer({
                svg: this.svg,
                lanesGroup: this.lanesGroup,
                bandsGroup: this.bandsGroup,
                calibrationLinesGroup: this.calibrationLinesGroup,
                stateManager: this.stateManager,
                eventBus: this.eventBus,
                onSelectAnnotation: (type, id) => this._selectAnnotation(type, id)
            });

            // A selected 4-point lane is resized by its corners (corner-handles.js, spec 2026-10-10 §3).
            this.cornerHandles = new CornerHandles({
                handlesGroup: this.handlesGroup,
                viewport: this.viewport,
                renderer: this.renderer,
                imageWidth: this.options.imageWidth,
                imageHeight: this.options.imageHeight,
                onCommit: (id, data) => {
                    this._updateLane(id, data);
                }
            });

            // Tool Manager and Tools
            this.toolManager = new ToolManager({
                viewer: this.viewer,
                eventBus: this.eventBus,
                isEditable: this.isEditable,
                showMessage: (msg) => this._showMessage(msg),
                cancelDrawing: () => this._cancelDrawing(),
                deselect: () => this._deselect()
            });

            this._initTools();

            // Event Handler
            this.eventHandler = new EventHandler({
                viewer: this.viewer,
                canvasContainer: this.canvasContainer,
                eventBus: this.eventBus,
                toolManager: this.toolManager,
                viewport: this.viewport,
                stateManager: this.stateManager,
                getScale: () => this.viewport.scale,
                isEditable: this.isEditable,
                onDeleteSelected: () => this._deleteSelected(),
                onToggleTablePanel: () => this.dataTablePanel?.toggle(),
                onToggleBandTablePanel: () => this.bandTablePanel?.toggle(),
                onToggleAdjustmentsPanel: () => this.adjustmentsPanel?.toggle(),
                onHideTablePanel: () => this.dataTablePanel?.hide(),
                onHideBandTablePanel: () => this.bandTablePanel?.hide(),
                onHideAdjustmentsPanel: () => this.adjustmentsPanel?.hide(),
                onHideContextMenu: () => this.contextMenu?.hide(),
                onCancelDrawing: () => this._cancelDrawing(),
                onDeselect: () => this._deselect(),
                onFitToView: () => this.viewport.fitToView(),
                onZoom: (delta, point) => this.viewport.zoom(delta, point),
                getHandlesGroup: () => this.handlesGroup,
                onToggleBackgrounds: () => this.toggleBackgrounds(),
                onToggleDetectionPanel: () => this.detectionPanel?.toggle(),
                onToggleCV2DetectionPanel: () => this.cv2DetectionPanel?.toggle(),
                onToggleCalibrationPanel: () => this.calibrationPanel?.toggle(),
                onToggleMWLines: () => this.toggleMWLines(),
                onToggleElectropherogramPanel: () => this.electropherogramPanel?.toggle(),
                onToggleBandModelPanel: () => this.bandModelPanel?.toggle(),
                onHideDetectionPanel: () => this.detectionPanel?.hide(),
                onHideCV2DetectionPanel: () => this.cv2DetectionPanel?.hide(),
                onHideCalibrationPanel: () => this.calibrationPanel?.hide(),
                onHideElectropherogramPanel: () => this.electropherogramPanel?.hide(),
                isTablePanelVisible: () => this.dataTablePanel?.isVisible() || false,
                isBandTablePanelVisible: () => this.bandTablePanel?.isVisible() || false,
                isAdjustmentsPanelVisible: () => this.adjustmentsPanel?.isVisible() || false,
                isDetectionPanelVisible: () => this.detectionPanel?.isOpen() || false,
                isCV2DetectionPanelVisible: () => this.cv2DetectionPanel?.isOpen() || false,
                isCalibrationPanelVisible: () => this.calibrationPanel?.isOpen() || false,
                isElectropherogramPanelVisible: () => this.electropherogramPanel?.isVisible || false,
                getSelectedAnnotation: () => this.selectedType ? { type: this.selectedType, id: this.selectedId } : null,
                isContextMenuVisible: () => this.contextMenu?.isVisible() || false
            });

            // The one path that fills a ladder's MW values from a template, for the two buttons that do it (the lane
            // form's MW Template and the Band editor). The dialog is created after the panels: read when asked.
            this.ladderTemplateApply = LadderTemplateApply ? new LadderTemplateApply({
                eventBus: this.eventBus,
                stateManager: this.stateManager,
                apiClient: this.apiClient,
                onSyncBandLocal: (id, data) => this._syncBandLocally(id, data),
                getConfirmationManager: () => this.confirmationManager,
            }) : null;

            // UI Panels
            this.propertiesPanel = new PropertiesPanel({
                eventBus: this.eventBus,
                stateManager: this.stateManager,
                apiClient: this.apiClient,
                // Forward the toast manager so save failures surface as a
                // non-blocking top-left toast in addition to the inline
                // error line + Retry button on the properties panel itself.
                toasts: this.toasts,
                // Phoresis's shared AutoSave helper (null when shared/auto-save.js is not loaded).
                autoSave: this.autoSave,
                onDeleteLane: (id) => this._deleteLane(id),
                onDeleteBand: (id) => this._deleteBand(id),
                onUpdateLane: (id, data) => this._updateLane(id, data),
                onUpdateBand: (id, data) => this._updateBand(id, data),
                onSyncBandLocal: (id, data) => this._syncBandLocally(id, data),
                onSelectBand: (bandId) => this._selectAnnotation('band', bandId),
                getReading: () => this.reading,
                // The lane form's "HCP reference" switch: the context menu's own two (slice 3c).
                onSetReferenceLane: (id) => this._setReferenceLane(id),
                getReferenceContext: () => this.readout,
                ladderTemplateApply: this.ladderTemplateApply,
            });

            // "How this gel is read" (slice 3c): renders itself on READING_CHANGED.
            this.readingCard = global.GelViewer.ReadingCard
                ? new global.GelViewer.ReadingCard({ eventBus: this.eventBus, container: document.getElementById('reading-card') })
                : null;
            // "Bands by Type | Readout" over the gel (slice 3c): renders itself on READING_CHANGED.
            this.gelLegend = global.GelViewer.GelLegend
                ? new global.GelViewer.GelLegend({
                    eventBus: this.eventBus,
                    container: document.getElementById('gel-legend'),
                    viewer: this.container.querySelector('.gv-viewer'),
                })
                : null;

            this.dataTablePanel = new DataTablePanel({
                eventBus: this.eventBus,
                stateManager: this.stateManager,
                apiClient: this.apiClient,
                onSelectAnnotation: (type, id) => this._selectAnnotation(type, id),
                onUpdateLane: (id, data, silent) => this._updateLane(id, data, silent),
                // A row's type asks what the form asks (calibration points, ladder template): one path.
                onChangeLaneType: (id, type, select) => this.propertiesPanel.changeLaneType(id, type, select),
                onSaveAll: () => this._batchSave(),
            });

            this.bandTablePanel = new BandTablePanel({
                eventBus: this.eventBus,
                stateManager: this.stateManager,
                onSelectBand: (bandId) => this._selectAnnotation('band', bandId),
                onUpdateBand: (id, data) => this._updateBand(id, data),
                // "Calib." asks the loaded amount, the context menu's dialog: the type is saved with it or not at all.
                onSetCalibration: (id) => this.contextMenu?._promptCalibrationValue(id),
                onDeleteBand: (id) => this._deleteBand(id),
                ladderTemplateApply: this.ladderTemplateApply,
            });

            this.adjustmentsPanel = new AdjustmentsPanel({
                eventBus: this.eventBus,
                imageElement: this.container.querySelector('.gv-image'),
                imageProxyUrl: this.options.imageProxyUrl
            });

            this.contextMenu = new ContextMenu({
                eventBus: this.eventBus,
                stateManager: this.stateManager,
                apiClient: this.apiClient,
                svg: this.svg,
                handlesGroup: this.handlesGroup,
                isEditable: this.isEditable,
                showMessage: (msg) => this._showMessage(msg),
                onDeleteLane: (id) => this._deleteLane(id),
                onDeleteBand: (id) => this._deleteBand(id),
                onUpdateLane: (id, data) => this._updateLane(id, data),
                // Lane Type from the menu: the form's path too (calibration points, ladder template). The menu reads
                // onSetLaneType from `handlers` only; without it, it wrote the type through onUpdateLane.
                handlers: { onSetLaneType: (id, type) => this.propertiesPanel.changeLaneType(id, type, null) },
                onUpdateBand: (id, data) => this._updateBand(id, data),
                onSyncBandLocal: (id, data) => this._syncBandLocally(id, data),
                onStartResize: (id) => this._startLaneResize(id),
                onSetReferenceLane: (id) => this._setReferenceLane(id),
                getReferenceContext: () => this.readout,
                getSelectedAnnotation: () => ({ type: this.selectedType, id: this.selectedId })
            });

            // Electropherogram Panel (Plotly.js intensity profile) — init before DetectionPanel
            if (ElectropherogramPanel) {
                this.electropherogramPanel = new ElectropherogramPanel({
                    eventBus: this.eventBus,
                    apiClient: this.apiClient,
                    stateManager: this.stateManager
                });
            }

            // Phase 3: Auto Detection & MW Calibration panels
            if (DetectionPanel) {
                this.detectionPanel = new DetectionPanel({
                    eventBus: this.eventBus,
                    apiClient: this.apiClient,
                    stateManager: this.stateManager,
                    onDetectionComplete: () => this._onDetectionComplete(),
                    electropherogramPanel: this.electropherogramPanel,
                });
            }

            if (CV2DetectionPanel) {
                this.cv2DetectionPanel = new CV2DetectionPanel({
                    eventBus: this.eventBus,
                    apiClient: this.apiClient,
                    stateManager: this.stateManager,
                    onDetectionComplete: () => this._onDetectionComplete(),
                    electropherogramPanel: this.electropherogramPanel,
                });
            }

            if (BandModelPanel) {
                // The YOLO band model, run in the browser after the lane model (band-model-panel.js).
                this.bandModelPanel = new BandModelPanel({
                    eventBus: this.eventBus,
                    apiClient: this.apiClient,
                    stateManager: this.stateManager,
                    svg: this.svg,
                    workerUrl: this.options.bandModelWorkerUrl,
                    onDetectionComplete: () => this._onDetectionComplete(),
                });
            }

            if (CalibrationPanel) {
                this.calibrationPanel = new CalibrationPanel({
                    eventBus: this.eventBus,
                    apiClient: this.apiClient,
                    stateManager: this.stateManager,
                    onCalibrationApplied: (result) => this._onCalibrationApplied(result)
                });
            }

            // Teacher Panel (band detection calibration wizard)
            const TeacherPanel = GelViewer.TeacherPanel;
            if (TeacherPanel) {
                this.teacherPanel = new TeacherPanel({
                    eventBus: this.eventBus,
                    apiClient: this.apiClient,
                    stateManager: this.stateManager,
                    svg: this.svg,
                    drawingGroup: this.drawingGroup,
                    viewer: this.viewer,
                    getScale: () => this.viewport?.getScale() || 1,
                    getImagePoint: (e) => this.eventHandler?.getImagePoint(e),
                });

                // Open teacher when event fires from detection panel
                this.eventBus.on(Events.TEACHER_PANEL_SHOWN, () => {
                    if (!this.teacherPanel.isOpen) {
                        this.teacherPanel.show();
                    }
                });
            }

            // Confirmation dialogs
            if (ConfirmationManager) {
                this.confirmationManager = new ConfirmationManager();
            }

            // Phase 3: YOLO Inference modules (lazy initialization)
            // InferenceEngine and ReviewPanel are created only when needed
            // to avoid loading ONNX Runtime until user clicks Auto-Detect

            // Setup event listeners
            this.eventHandler.setup();
            this._setupUIEventListeners();

            // Fit to view after image loads
            this._setupImageLoad();
        }

        /**
         * Initialize drawing tools.
         */
        _initTools() {
            const laneTool = new LaneTool({
                svg: this.svg,
                drawingGroup: this.drawingGroup,
                eventBus: this.eventBus,
                stateManager: this.stateManager,
                toolManager: this.toolManager,
                onLaneCreated: (data) => this._createLane(data),
                showMessage: (msg) => this._showMessage(msg),
                getScale: () => this.viewport.getScale()
            });

            const bandTool = new BandTool({
                svg: this.svg,
                drawingGroup: this.drawingGroup,
                eventBus: this.eventBus,
                stateManager: this.stateManager,
                onBandCreated: (laneId, data) => this._createBand(laneId, data),
                findLaneAtPoint: (x, y) => this._findLaneAtPoint(x, y),
                showMessage: (msg) => this._showMessage(msg),
                getScale: () => this.viewport.getScale()
            });

            const splitTool = new SplitTool({
                svg: this.svg,
                drawingGroup: this.drawingGroup,
                eventBus: this.eventBus,
                stateManager: this.stateManager,
                onBandSplit: (bandId, splitY) => this._splitBand(bandId, splitY),
                getBandAtPoint: (x, y) => this._getBandAtPoint(x, y),
                showMessage: (msg) => this._showMessage(msg),
                getScale: () => this.viewport.getScale()
            });

            const selectTool = new SelectTool({
                eventBus: this.eventBus
            });

            const panTool = new PanTool({
                viewport: this.viewport,
                eventBus: this.eventBus
            });

            const cropTool = new CropTool({
                svg: this.svg,
                drawingGroup: this.drawingGroup,
                eventBus: this.eventBus,
                imageWidth: this.options.imageWidth,
                imageHeight: this.options.imageHeight,
                showMessage: (msg) => this._showMessage(msg),
                getScale: () => this.viewport.getScale()
            });

            // Register tools
            this.toolManager.registerTool('select', selectTool);
            this.toolManager.registerTool('pan', panTool);
            this.toolManager.registerTool('lane', laneTool);
            this.toolManager.registerTool('band', bandTool);
            this.toolManager.registerTool('split', splitTool);
            this.toolManager.registerTool('crop', cropTool);

            // Set default tool
            this.toolManager.setTool('select');
        }

        /**
         * Wire up EventBus subscriptions.
         */
        _wireEventBus() {
            // Save requested
            this.eventBus.on(Events.SAVE_REQUESTED, () => {
                this._batchSave();
            });

            // Tool changed
            this.eventBus.on(Events.TOOL_CHANGED, (data) => {
                this._cancelDrawing();
            });

            // Lane shape changed
            this.eventBus.on(Events.LANE_SHAPE_CHANGED, (data) => {
                this._cancelDrawing();
            });

            // Context menu requested: a right-click or a long-press (a point), or Shift+F10 / the Menu key
            this.eventBus.on(Events.CONTEXT_MENU_REQUESTED, (data) => this._openContextMenu(data));

            // Table cell changed - sync to properties
            this.eventBus.on(Events.TABLE_CELL_CHANGED, (data) => {
                if (this.selectedType === 'lane' && this.selectedId === data.id) {
                    this.propertiesPanel.syncField(data.field, data.value);
                }
            });

            // Lane drawing finished (Enter key for polygon lanes)
            this.eventBus.on(Events.LANE_DRAW_FINISHED, (data) => {
                if (data) {
                    this._createLane(data);
                }
            });

            // Band drawing finished (Enter key)
            this.eventBus.on(Events.BAND_DRAW_FINISHED, (data) => {
                if (data && data.laneId && data.bandData) {
                    this._createBand(data.laneId, data.bandData);
                }
            });

            // Data reload requested (from detection/calibration panels)
            this.eventBus.on(Events.DATA_RELOAD_REQUESTED, () => {
                this._reloadAnnotations();
            });

            // A write reached the server: the reading (checks, band roles) is read again once the writes settle.
            this.eventBus.on(Events.SERVER_WRITTEN, () => this._scheduleReadingRefresh());

            // Signed out: the failed write stays pending (api-client.js); one sticky notice says how to get it saved,
            // gone as soon as an answer comes through again.
            this.eventBus.on(Events.SESSION_EXPIRED, ({ message }) => {
                this._signedOutToast?.dismiss();
                this._signedOutToast = this.toasts ? this.toasts.error(message) : null;
                if (!this._signedOutToast) this._showMessage(message, 10000);
            });
            this.eventBus.on(Events.SESSION_RESTORED, () => {
                this._signedOutToast?.dismiss();
                this._signedOutToast = null;
            });

            // Calibration applied - update MW lines if visible
            this.eventBus.on(Events.CALIBRATION_APPLIED, async (data) => {
                console.log('Calibration applied event received', data);
                try {
                    // Fetch updated calibration data (includes template_bands)
                    this.calibrationData = await this.apiClient.getMultiCalibration();
                    console.log('Updated calibration data:', this.calibrationData);

                    // If MW lines are visible, re-render them
                    if (this.showMWLines && this.calibrationData?.is_calibrated) {
                        this.renderer.renderCalibrationLines(this.calibrationData);
                    }

                    // Update toolbar state
                    this._updateToolbarState();
                } catch (error) {
                    // Was silent before — surface the actual server error
                    // so a calibration refresh that fails (e.g. 500 from
                    // the server, network drop) doesn't just leave the
                    // user wondering why MW lines are stale.
                    console.error('Failed to update calibration data:', error);
                    this._showMessage(`❌ Calibration refresh failed: ${(error && error.message) || error}`);
                }
            });

            // ── Detection panel mutual exclusivity ──────────────────────────────────
            // Only one of the detection panels may be open at a time.
            // Centralized here so individual panels stay dumb about each other.
            const hideOtherDetectionPanels = (openedPanel) => {
                [
                    this.detectionPanel,
                    this.cv2DetectionPanel,
                    this.bandModelPanel,
                ].forEach(p => {
                    if (p && p !== openedPanel && p.isVisible) p.hide();
                });
            };
            this.eventBus.on(Events.DETECTION_PANEL_SHOWN,     () => hideOtherDetectionPanels(this.detectionPanel));
            this.eventBus.on(Events.CV2_DETECTION_PANEL_SHOWN, () => hideOtherDetectionPanels(this.cv2DetectionPanel));
            this.eventBus.on(Events.BAND_MODEL_PANEL_SHOWN,    () => hideOtherDetectionPanels(this.bandModelPanel));

            // Crop requested
            this.eventBus.on(Events.CROP_REQUESTED, (cropData) => this._handleCropRequested(cropData));

            // Toolbar state updates - listen to relevant events
            this.eventBus.on(Events.LANE_CREATED, () => this._updateToolbarState());
            this.eventBus.on(Events.LANE_DELETED, () => this._updateToolbarState());
            this.eventBus.on(Events.BAND_CREATED, () => this._updateToolbarState());
            this.eventBus.on(Events.BAND_DELETED, () => this._updateToolbarState());
            this.eventBus.on(Events.SELECTION_CHANGED, () => this._updateToolbarState());
            this.eventBus.on(Events.SELECTION_CLEARED, () => this._updateToolbarState());
            this.eventBus.on(Events.ANNOTATIONS_LOADED, () => this._updateToolbarState());
            // Every change tracked, saved at once or forgotten: the toolbar's rules (they call _refreshStatus).
            this.eventBus.on(Events.PENDING_CHANGED, () => this._updateToolbarState());

            // Corner handles keep their screen size through a zoom and a fit (the Fit button, a window resize).
            const refreshCornerHandles = () => {
                if (this.cornerHandles.laneId !== null) {
                    this.cornerHandles.refresh(this.stateManager.getLane(this.cornerHandles.laneId));
                }
            };
            this.eventBus.on(Events.ZOOM_CHANGED, refreshCornerHandles);
            this.eventBus.on(Events.VIEWPORT_CHANGED, refreshCornerHandles);
        }

        /**
         * Setup additional UI event listeners.
         */
        _setupUIEventListeners() {
            // Save button
            const saveBtn = document.getElementById('btn-save');
            if (saveBtn) {
                saveBtn.addEventListener('click', () => this._batchSave());
            }

            // Table panel toggle
            const tableToggle = document.getElementById('toggle-table');
            console.log('Setting up toggle-table button:', tableToggle);
            if (tableToggle) {
                tableToggle.addEventListener('click', (e) => {
                    console.log('Lane Editor button clicked');
                    e.stopPropagation();
                    this.dataTablePanel?.toggle();
                });
            } else {
                console.warn('toggle-table button not found in DOM');
            }

            // Band table panel toggle
            const bandTableToggle = document.getElementById('toggle-band-table');
            console.log('Setting up toggle-band-table button:', bandTableToggle);
            if (bandTableToggle) {
                bandTableToggle.addEventListener('click', (e) => {
                    console.log('Band Editor button clicked');
                    e.stopPropagation();
                    this.bandTablePanel?.toggle();
                });
            } else {
                console.warn('toggle-band-table button not found in DOM');
            }

            // Toggle backgrounds button
            const backgroundsToggle = document.getElementById('toggle-backgrounds');
            if (backgroundsToggle) {
                backgroundsToggle.addEventListener('click', () => this.toggleBackgrounds());
            }

            // Auto-Detect button (Phase 3: YOLO inference)
            const autoDetectBtn = document.getElementById('btn-auto-detect');
            if (autoDetectBtn) {
                autoDetectBtn.addEventListener('click', () => this._autoDetect());
            }

            // Crop button
            const cropBtn = document.getElementById('btn-crop');
            if (cropBtn) {
                cropBtn.addEventListener('click', () => {
                    this.toolManager.setTool('crop');
                });
            }

            // Detection panel toggle (Phase 3: Auto detection)
            const detectionToggle = document.getElementById('toggle-detection');
            if (detectionToggle) {
                detectionToggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.detectionPanel?.toggle();
                });
            }

            // CV2 Vision Detection panel toggle
            const cv2DetectionToggle = document.getElementById('toggle-cv2-detection');
            if (cv2DetectionToggle) {
                cv2DetectionToggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.cv2DetectionPanel?.toggle();
                });
            }

            // Band model panel toggle (the YOLO band model, after the lane model)
            const bandModelToggle = document.getElementById('toggle-band-model');
            if (bandModelToggle) {
                bandModelToggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.bandModelPanel?.toggle();
                });
            }

            // Calibration panel toggle (Phase 3: MW calibration)
            const calibrationToggle = document.getElementById('toggle-calibration');
            if (calibrationToggle) {
                calibrationToggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.calibrationPanel?.toggle();
                });
            }

            // Normalize lane heights button
            const normalizeLanesBtn = document.getElementById('normalize-lanes-btn');
            if (normalizeLanesBtn) {
                normalizeLanesBtn.addEventListener('click', () => this._normalizeLaneHeights());
            }

            // Electropherogram panel toggle
            const electropherogramToggle = document.getElementById('toggle-electropherogram');
            if (electropherogramToggle) {
                electropherogramToggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.electropherogramPanel?.toggle();
                });
            }

            // MW Lines toggle
            const mwLinesToggle = document.getElementById('toggle-mw-lines');
            if (mwLinesToggle) {
                mwLinesToggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.toggleMWLines();
                });
            }

            // Table panel close
            const tableClose = document.getElementById('close-table-panel');
            if (tableClose) {
                tableClose.addEventListener('click', () => this.dataTablePanel?.hide());
            }

            // Window resize: the viewport's ResizeObserver re-fits a gel shown whole (with its last fit's options) and
            // keeps a zoom (slice 3c); without ResizeObserver, the old re-fit.
            if (!global.ResizeObserver) {
                let resizeTimeout;
                window.addEventListener('resize', () => {
                    clearTimeout(resizeTimeout);
                    resizeTimeout = setTimeout(() => this.viewport.fitToView(), 150);
                });
            }

            // Warn before leaving with unsaved changes
            window.addEventListener('beforeunload', (e) => {
                if (this.stateManager.isDirty) {
                    // The last change may still wait out the backup's delay: write it now, whatever the user answers.
                    this.stateManager.saveToLocalStorage();
                    e.preventDefault();
                    e.returnValue = '';
                }
            });
        }

        /**
         * Setup image load handling.
         */
        _setupImageLoad() {
            const imageEl = document.getElementById('gel-image');
            if (imageEl) {
                if (imageEl.complete && imageEl.naturalHeight !== 0) {
                    this.viewport.fitToView();
                } else {
                    imageEl.addEventListener('load', () => this.viewport.fitToView());
                    imageEl.addEventListener('error', () => this.viewport.fitToView());
                }
            } else {
                this.viewport.fitToView();
            }
        }

        // =====================================================================
        // Annotation Loading
        // =====================================================================

        async _loadAnnotations() {
            let loaded = false;
            try {
                this._showLoading('Loading annotations...');
                const data = await this.apiClient.loadAnnotations();

                // Before the lanes: renderLane draws the REF badge.
                this._applyReadoutContext(data);

                // Render lanes and bands
                if (data.lanes) {
                    data.lanes.forEach(lane => {
                        this.stateManager.setLane(lane.id, lane);
                        this.renderer.renderLane(lane);

                        if (lane.bands) {
                            lane.bands.forEach(band => {
                                this.stateManager.setBand(band.id, band);
                                this.renderer.renderBand(band);
                            });
                        }
                    });
                }

                this.eventBus.emit(Events.ANNOTATIONS_LOADED, data);
                // Once the lanes and bands exist: the reading card, the forms and the legend read them.
                this.eventBus.emit(Events.READING_CHANGED, this.reading);

                // Load calibration data if available (enables MW lines and auto MW calculation)
                this._loadCalibrationData();
                loaded = true;

            } catch (error) {
                console.error('Failed to load annotations:', error);
                this._showMessage(`❌ Failed to load annotations: ${(error && error.message) || error}`);
            } finally {
                this._hideLoading();
            }

            // Only against what the server returned: a backup is never offered over a load that failed.
            if (loaded) {
                await this._offerBackup();
            }
        }

        /**
         * Load calibration data if available.
         * This enables the MW Lines toggle and auto MW calculation for new bands.
         */
        async _loadCalibrationData() {
            try {
                this.calibrationData = await this.apiClient.getMultiCalibration();
                if (this.calibrationData?.is_calibrated) {
                    console.log('Calibration data loaded:', {
                        isCalibrated: true,
                        calibrationCount: this.calibrationData.calibrations?.length
                    });
                    this._updateToolbarState();
                }
            } catch (error) {
                // Calibration may not exist yet - this is normal
                console.log('No calibration data available');
                this.calibrationData = null;
            }
        }

        /**
         * Offer the backup of unsaved changes an earlier visit left (a crash, a tab closed without saving), never
         * apply it silently: what still fits the lanes and bands just loaded is listed, Restore replays it as unsaved
         * changes (Save sends them), Discard deletes the backup. A read-only analysis offers nothing (nothing could
         * be saved): its backup waits out its 24 h.
         */
        async _offerBackup() {
            if (!this.isEditable) return;
            const backup = this.stateManager.loadFromLocalStorage();
            if (!backup) return;

            const { changes, dropped } = this.stateManager.recoverable(backup);
            const count = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
            const kept = StateManager.countChanges(changes);
            if (kept === 0) {
                this.stateManager.clearLocalStorage();
                const msg = `A local backup of ${count(dropped, 'unsaved change')} was discarded: the lanes or bands it changed no longer exist.`;
                if (this.toasts) this.toasts.info(msg); else this._showMessage(msg);
                return;
            }

            const { lanes, bands } = changes;
            const newLanes = new Set(lanes.created.map(([id]) => String(id)));
            const bandsInNewLanes = bands.created.filter(([, b]) => newLanes.has(String(b._parentLaneId))).length;
            const items = [
                lanes.created.length && count(lanes.created.length, 'new lane')
                    + (bandsInNewLanes ? ` (with ${count(bandsInNewLanes, 'band')})` : ''),
                bands.created.length - bandsInNewLanes && `${count(bands.created.length - bandsInNewLanes, 'new band')} on saved lanes`,
                lanes.updated.length && `${count(lanes.updated.length, 'lane')} edited`,
                bands.updated.length && `${count(bands.updated.length, 'band')} edited`,
                lanes.deleted.length && `${count(lanes.deleted.length, 'lane')} deleted`,
                bands.deleted.length && `${count(bands.deleted.length, 'band')} deleted`,
            ].filter(Boolean);
            const when = new Date(backup.timestamp).toLocaleString();

            // Only the Discard button deletes the backup. Esc (which the page also reads as "leave the editor") or a
            // click beside the dialog decides nothing: the offer comes back at the next load, unless a new change
            // rewrites the backup first. Captured on the dialog, so the flag is set before the button's own handler
            // resumes this function.
            let discarded = false;
            const onDiscard = (e) => { if (e.target.closest('#gv-confirm-cancel')) discarded = true; };
            const cm = this.confirmationManager;
            // No dialog to ask with: nothing is decided, the offer comes back at the next load.
            if (!(cm && cm.modal)) return;
            cm.modal.addEventListener('click', onDiscard, true);
            const restore = await cm.show({
                title: 'Restore unsaved changes?',
                body:
                    `<p>This browser kept changes to this analysis that were never saved (last change ${when}):</p>` +
                    `<ul>${items.map(item => `<li>${item}</li>`).join('')}</ul>` +
                    (dropped ? `<p class="text-muted">${count(dropped, 'other change')} left out: the lane or band no longer exists.</p>` : '') +
                    '<p class="mb-0"><strong>Restore</strong> puts them back as unsaved changes: check them, then Save. ' +
                    '<strong>Discard</strong> deletes this backup.</p>',
                confirmText: 'Restore',
                cancelText: 'Discard',
                danger: false,
                icon: 'clock-history',
            });
            cm.modal.removeEventListener('click', onDiscard, true);

            if (restore) {
                this._restoreChanges(changes);
                const msg = `${count(kept, 'unsaved change')} restored: check them, then Save.`;
                if (this.toasts) this.toasts.success(msg); else this._showMessage(msg);
            } else if (discarded) {
                this.stateManager.clearLocalStorage();
            }
        }

        /**
         * Replay a backup's changes (StateManager.recoverable) through the editor's own tracking: they are drawn, count
         * as unsaved, and Save sends them, as if they had just been made.
         */
        _restoreChanges(changes) {
            const sm = this.stateManager;
            const removeBand = (id) => {
                sm.trackBandDeletion(id);
                this.renderer.removeBand(id);
                sm.deleteBand(id);
            };

            for (const laneId of changes.lanes.deleted) {
                sm.getBandsForLane(laneId).forEach(band => removeBand(band.id));
                sm.trackLaneDeletion(laneId);
                this.renderer.removeLane(laneId);
                sm.deleteLane(laneId);
            }
            for (const bandId of changes.bands.deleted) {
                if (sm.getBand(bandId)) removeBand(bandId);
            }
            for (const [laneId, data] of changes.lanes.updated) {
                this._updateLane(laneId, data, true);
            }
            for (const [laneId, lane] of changes.lanes.created) {
                lane.bands = [];  // refilled below with the very band objects the state holds
                this.renderer.renderLane(lane);
                sm.trackLaneCreation(laneId, lane);
            }
            for (const [bandId, band] of changes.bands.created) {
                band._isSaving = false;
                const lane = sm.getLane(band._parentLaneId);
                lane.bands = lane.bands || [];
                lane.bands.push(band);
                this.renderer.renderBand(band);
                sm.trackBandCreation(bandId, band);
            }
            for (const [bandId, data] of changes.bands.updated) {
                const band = this._syncBandLocally(bandId, data);
                if (!band) continue;  // went with a lane deleted above
                this.renderer.updateBand(band);
                sm.trackBandUpdate(bandId, data);
            }

            this._recalculateLaneNumbers();
        }

        /**
         * Draw the unsaved changes over the server's lanes and bands _reloadAnnotations just drew: hide what is deleted,
         * draw what is new, each band in its lane's list.
         */
        _redrawPendingChanges() {
            const sm = this.stateManager;
            const pending = sm.pendingChanges;
            const laneOf = (band) => sm.getLane(band._parentLaneId || band.lane_id);

            // Hide deleted lanes, with their bands
            for (const laneId of pending.lanes.deleted) {
                for (const band of sm.getLane(laneId)?.bands || []) {
                    this.renderer.removeBand(band.id);
                    sm.deleteBand(band.id);
                }
                this.renderer.removeLane(laneId);
                sm.deleteLane(laneId);
            }

            // Hide deleted bands
            for (const bandId of pending.bands.deleted) {
                const band = sm.getBand(bandId);
                const lane = band && laneOf(band);
                if (lane && lane.bands) lane.bands = lane.bands.filter(b => b.id !== bandId);
                this.renderer.removeBand(bandId);
                sm.deleteBand(bandId);
            }

            // Render created lanes; a lane never saved holds only new bands, put back below
            for (const [id, laneData] of pending.lanes.created) {
                laneData.bands = [];
                sm.setLane(id, laneData);
                this.renderer.renderLane(laneData);
            }

            // Render created bands
            for (const [id, bandData] of pending.bands.created) {
                const lane = laneOf(bandData);
                if (lane) {
                    lane.bands = lane.bands || [];
                    lane.bands.push(bandData);
                }
                sm.setBand(id, bandData);
                this.renderer.renderBand(bandData);
            }

            // Recalculate and update
            this._recalculateLaneNumbers();
        }

        // =====================================================================
        // Selection
        // =====================================================================

        _selectAnnotation(type, id) {
            console.log('_selectAnnotation called:', { type, id });
            this.selectedType = type;
            this.selectedId = id;

            // Update StateManager selection (this emits SELECTION_CHANGED)
            this.stateManager.setSelection(type, id);

            this.renderer.selectAnnotation(type, id);

            // Highlight in table
            if (type === 'lane') {
                this.dataTablePanel?.highlightRow(id);
            }

            const lane = type === 'lane' ? this.stateManager.getLane(id) : null;
            if (this._showsCorners(lane)) {
                this.cornerHandles.show(lane);
            } else {
                this.cornerHandles.hide();
            }
        }

        /** A selected 4-point lane shows its corner handles -- on an analysis that can still be edited. */
        _showsCorners(lane) {
            return !!lane && this.isEditable && CornerHandles.fits(lane);
        }

        _deselect() {
            console.log('_deselect called');
            this.selectedType = null;
            this.selectedId = null;

            // Update StateManager (this emits SELECTION_CLEARED)
            this.stateManager.clearSelection();

            this.renderer.clearSelection();
            this.cornerHandles.hide();
        }

        _deleteSelected() {
            if (this.selectedType === 'lane') {
                this._deleteLane(this.selectedId);
            } else if (this.selectedType === 'band') {
                this._deleteBand(this.selectedId);
            }
        }

        // =====================================================================
        // Lane Operations
        // =====================================================================

        _createLane(data) {
            const tempId = this.stateManager.generateTempId();
            const nextNumber = this.stateManager.getNextLaneNumber();

            const lane = {
                id: tempId,
                lane_number: nextNumber,
                lane_type: 'SAMPLE',
                lane_type_display: 'Sample',
                bands: [],
                _isNew: true,
                ...data
            };

            this.stateManager.setLane(tempId, lane);
            this.stateManager.trackLaneCreation(tempId, lane);
            this.renderer.renderLane(lane);
            this._recalculateLaneNumbers();
            this.stateManager.markDirty();

            this._selectAnnotation('lane', tempId);
            this._showMessage('Lane created (unsaved)');

            // Switch back to select tool after creating
            this.toolManager.setTool('select');
        }

        _updateLane(id, data, silent = false) {
            const lane = this.stateManager.getLane(id);
            if (!lane) return;

            const G = GelAnalyzer.LaneGeometry;
            const boxKeys = ['x', 'y', 'width', 'height'];
            if (!('polygon' in data) && boxKeys.some(k => k in data) && G.hasOutline(lane)) {
                // The properties panel and the box handles change the box only; the server maps the stored polygon
                // onto the new box (shape.py::normalize_lane_write, D12). Do the same here, or the outline snaps back
                // until a reload. Always from the polygon as it was before the first box-only edit, never from a
                // rounded intermediate: typing W 85 -> 6 -> 62 must give what one 85 -> 62 mapping gives.
                if (!lane._boxEditBase) {
                    lane._boxEditBase = {
                        polygon: lane.polygon.map(p => [p[0], p[1]]),
                        box: [lane.x, lane.y, lane.width, lane.height],
                    };
                }
                const base = lane._boxEditBase;
                const newBox = boxKeys.map(k => (k in data ? data[k] : lane[k]));
                const polygon = G.clampRound(G.mapPolygonToBox(base.polygon, base.box, newBox),
                    this.options.imageWidth, this.options.imageHeight);
                const [x, y, width, height] = G.outerBox(polygon);
                data = { ...data, polygon, x, y, width, height };
            } else if ('polygon' in data) {
                delete lane._boxEditBase;  // a new outline (corners, normalize): the next box edit maps from it
            }

            Object.assign(lane, data);

            // Update type display if changed
            if (data.lane_type) {
                lane.lane_type_display = StateManager.getLaneTypeDisplay(data.lane_type);

                // Update SVG class
                const element = this.svg.findOne(`#lane-${id}`);
                if (element) {
                    element.removeClass('sample').removeClass('ladder')
                           .removeClass('control').removeClass('calibration')
                           .removeClass('empty').removeClass('dot');
                    element.addClass(data.lane_type.toLowerCase());
                }
            }

            // Update SVG visuals if geometry changed
            if ('x' in data || 'y' in data || 'width' in data || 'height' in data || 'polygon' in data) {
                this.renderer.updateLane(lane);
                if ('x' in data) {
                    this._recalculateLaneNumbers();
                }
                this.cornerHandles.refresh(lane);
            }

            this.stateManager.trackLaneUpdate(id, data);
            this.stateManager.markDirty();

            this.eventBus.emit(Events.LANE_UPDATED, lane);

            if (!silent) {
                this._showMessage('Lane updated (unsaved)');
            }
        }

        /**
         * Start interactive lane resize with drag handles.
         * @param {string|number} id - Lane ID
         */
        _startLaneResize(id) {
            const lane = this.stateManager.getLane(id);
            if (!lane) return;

            // A tilted 4-point lane is resized by its corners: selecting it shows them. An upright one (a Straight
            // accept) gets the box handles, so it can be widened or shortened without being tilted; its polygon is
            // mapped onto the new box (_updateLane) and stays upright.
            if (CornerHandles.fits(lane) && !GelAnalyzer.LaneGeometry.isUprightBox(lane.polygon)) {
                this._selectAnnotation('lane', id);
                return;
            }

            this.cornerHandles.hide();
            const scale = this.viewport.getScale();
            // A copy: the handles write their preview into the lane they are given, and _updateLane must still see
            // the box before the drag to map a polygon lane's outline onto the new one (D12).
            this.contextMenu.showResizeHandles(
                { ...lane }, this.svg, this.handlesGroup, scale,
                (laneId, dims) => {
                    this._updateLane(laneId, dims);
                }
            );
        }

        async _deleteLane(id) {
            let lane = this.stateManager.getLane(id);
            if (!lane) return;

            // Every path asks here, once: Delete key, toolbar, context menu, properties panel, Lane Editor. A saved
            // lane is deleted on the server at once, with its bands, below -- as a saved band is (_deleteBand). Until
            // 2026-10-17 it waited for Save, under a dialog saying "permanently" and "cannot be undone" (owner).
            if (this.confirmationManager) {
                const bandCount = lane.bands?.length || 0;
                const confirmed = await this.confirmationManager.confirmDeleteLane(lane.lane_number, bandCount);
                if (!confirmed) return;
                // While the dialog was open: a reload replaced it, a Delete elsewhere removed it.
                id = lane.id;
                lane = this.stateManager.getLane(id);
                if (!lane) return;
            }

            const sm = this.stateManager;
            const isTempLane = String(id).startsWith('temp_');
            const laneNumber = lane.lane_number;

            // Its bands leave the canvas with it. A band never saved is forgotten (a POST still in flight deletes what
            // it created, _createBand). A saved band goes with the lane on the server (CASCADE): nothing of it waits
            // for Save, and no pending edit may PUT to it.
            for (const band of lane.bands || []) {
                band._removed = true;
                if (String(band.id).startsWith('temp_')) {
                    sm.trackBandDeletion(band.id);
                } else {
                    sm.forgetBandUpdate(band.id);
                }
                this.renderer.removeBand(band.id);
                sm.deleteBand(band.id);
            }

            if (isTempLane) {
                // Never saved: forgetting it is the whole deletion.
                sm.trackLaneDeletion(id);
            } else {
                sm.forgetLaneUpdate(id);
            }
            this.renderer.removeLane(id);
            sm.deleteLane(id);

            this._recalculateLaneNumbers();

            if (this.selectedId === id) {
                this._deselect();
            }

            if (isTempLane) {
                if (this.toasts) this.toasts.info(`Lane ${laneNumber} removed`);
            } else {
                const toast = this.toasts ? this.toasts.pending(`Deleting lane ${laneNumber}…`) : null;
                this.apiClient.deleteLane(id).then(() => {
                    if (toast) toast.success(`Lane ${laneNumber} deleted`);
                }).catch(error => {
                    console.error('Failed to delete lane on server:', error);
                    if (error && error.name === 'SessionExpiredError') {
                        // Signed out: the server never saw the delete. It waits for the next Save, once logged in
                        // again, like every other change (the Save's lane DELETE takes the bands with it).
                        sm.trackLaneDeletion(id);
                        if (toast) toast.info(`Not deleted on the server yet: ${error.message}. Save deletes it.`);
                        return;
                    }
                    if (toast) {
                        toast.error(`Delete failed: ${error.message || error}. The lane reappeared because the server rejected the change.`);
                    }
                    // The server refused (an analysis no longer editable, an error): the canvas is wrong, the server
                    // is the truth.
                    this.eventBus.emit(Events.DATA_RELOAD_REQUESTED);
                });
            }
            // Nothing emitted LANE_DELETED before 2026-10-17, as BAND_DELETED before 2026-10-13: the toolbar refreshes,
            // the Lane Editor drops the row, a ladder lane marks the MW calibration stale. Once the lane has left the
            // state; the lane itself is the payload.
            this.eventBus.emit(Events.LANE_DELETED, lane);
        }

        // =====================================================================
        // Anti-HCP reference lane (western readouts)
        // =====================================================================

        /**
         * Store the readout context of an /data/ payload and hand the
         * reference to the renderer. Called by _loadAnnotations AND
         * _reloadAnnotations before the lanes are rendered. The badge is only
         * meaningful on an anti-HCP western: another assay draws none.
         */
        _applyReadoutContext(data) {
            const analysis = data?.analysis || {};
            const assay = data?.gel_image?.assay || null;
            // The server's reading (slice 3c): null when its summary failed (the API serves null, logged there).
            this.reading = data?.page_summary || null;
            this.readout = {
                assay,
                referenceLaneId: analysis.readout_reference_lane_id ?? null,
                canWrite: analysis.can_write === true,
                editable: analysis.is_editable !== false,
            };
            this.renderer.setReferenceLane(
                assay?.readout === 'HOST_CELL_PROTEINS' ? this.readout.referenceLaneId : null
            );
        }

        /**
         * Read the reading again once the writes settle (~400 ms after the last). A refresh already on its way read
         * the server before this write: it is dropped (it would put the old reference, the old roles back). During
         * a batch Save nothing is read: its end schedules one refresh (a write slower than 400 ms would otherwise
         * read the gel half saved).
         */
        _scheduleReadingRefresh() {
            this._readingSeq++;
            clearTimeout(this._readingTimer);
            if (this._batchSaving) return;
            this._readingTimer = setTimeout(() => this._refreshReading(), 400);
        }

        /**
         * The server's reading after a write: page_summary and the bands' roles, nothing else -- no canvas rebuild,
         * no selection change, no pending edit touched (a quiet /data/: the panels that reload on DATA_LOADED stay).
         * A newer refresh wins; a failure keeps the last reading.
         */
        async _refreshReading() {
            const seq = ++this._readingSeq;
            let data;
            try {
                data = await this.apiClient.loadAnnotations({ quiet: true });
            } catch (error) {
                console.warn('GelViewer: reading refresh failed, the last one stays', error);
                return;
            }
            if (seq !== this._readingSeq) return;
            this._applyReadoutContext(data);
            (data.lanes || []).forEach((lane) => {
                (lane.bands || []).forEach((band) => {
                    const local = this.stateManager.getBand(band.id);
                    if (!local) return;
                    const role = band.role ?? null;
                    if ((local.role ?? null) === role) return;
                    local.role = role;
                    this.renderer.setBandRole(band.id, role);
                });
            });
            this.eventBus.emit(Events.READING_CHANGED, this.reading);
        }

        /**
         * "Use as HCP reference" on lane ``id``: saved at once (not with the
         * batch save) through POST readout-reference, which republishes the
         * readouts. Clicking the current reference clears it. A lane not saved
         * yet has no server id: refused with a toast, no call.
         */
        async _setReferenceLane(id) {
            if (String(id).startsWith('temp_')) {
                const msg = 'Save the lane first, then set it as the reference.';
                if (this.toasts) this.toasts.error(msg); else this._showMessage(msg);
                return;
            }

            const laneId = Number(id);
            const current = this.readout.referenceLaneId;
            const clearing = current !== null && current !== undefined && Number(current) === laneId;

            const toast = this.toasts
                ? this.toasts.pending(clearing ? 'Clearing the HCP reference…' : 'Setting the HCP reference…')
                : null;
            try {
                const result = await this.apiClient.setReadoutReferenceLane(clearing ? null : laneId);
                this.readout.referenceLaneId = result.reference_lane_id ?? null;
                this.renderer.setReferenceLane(this.readout.referenceLaneId);
                const msg = this.readout.referenceLaneId === null
                    ? 'HCP reference cleared'
                    : `Lane ${result.reference_lane_number} is the HCP reference`;
                if (toast) toast.success(msg); else this._showMessage(msg);
            } catch (error) {
                console.error('Failed to set the HCP reference lane:', error);
                const msg = `Could not change the HCP reference: ${error.message || error}`;
                if (toast) toast.error(msg); else this._showMessage(msg);
            }
        }

        // =====================================================================
        // Band Operations
        // =====================================================================

        _createBand(laneId, data) {
            const tempId = this.stateManager.generateTempId();

            // Check if parent lane is a LADDER - auto-set band type to MW_REFERENCE
            const lane = this.stateManager.getLane(laneId);
            let defaultBandType = 'OTHER';
            if (lane && lane.lane_type === 'LADDER') {
                defaultBandType = 'MW_REFERENCE';
            }

            // Auto-calculate MW if calibration exists (skip for ladder lanes)
            let estimatedMW = null;
            let estimationMethod = null;
            if (this.calibrationData?.is_calibrated && lane && lane.lane_type !== 'LADDER') {
                estimatedMW = this._estimateBandMW(data.position_y, lane);
                if (estimatedMW) {
                    estimationMethod = this.calibrationData.calibrations?.[0]?.method || 'LOG_LINEAR';
                }
            }

            const band = {
                id: tempId,
                band_type: defaultBandType,
                _isNew: true,
                _isSaving: true,  // Prevent race condition on type change
                _parentLaneId: laneId,
                lane_id: laneId,
                estimated_mw_kda: estimatedMW,
                mw_estimation_method: estimationMethod,
                ...data
            };

            this.stateManager.setBand(tempId, band);
            this.stateManager.trackBandCreation(tempId, band);

            // Add to lane's bands array
            if (lane) {
                lane.bands = lane.bands || [];
                lane.bands.push(band);
            }

            // Render immediately (optimistic UI)
            this.renderer.renderBand(band);
            this.stateManager.markDirty();

            this._selectAnnotation('band', tempId);

            // Switch back to select tool after creating
            this.toolManager.setTool('select');

            // Async server call (fire-and-forget, like delete)
            // Resolve lane ID (could be temp ID if lane was just created)
            const realLaneId = lane?._isNew ? lane.id : laneId;
            if (!String(realLaneId).startsWith('temp_')) {
                // Pending toast morphs into success/error when the server lands.
                const toast = this.toasts ? this.toasts.pending('Saving band…') : null;
                this.apiClient.createBand(realLaneId, {
                    polygon: data.polygon,
                    position_y: data.position_y,
                    band_type: band.band_type,
                    estimated_mw_kda: band.estimated_mw_kda,
                    mw_estimation_method: band.mw_estimation_method,
                }).then(result => {
                    if (band._removed) {
                        // Deleted or split while this POST was in flight: the server's copy would come back at the next load.
                        this.apiClient.deleteBand(result.id).then(
                            () => { if (toast) toast.info('Band removed'); },
                            (error) => { if (toast) toast.error(`Band removed here, not on the server: ${error.message || error}`); }
                        );
                        return;
                    }

                    // Replace temp ID with real server ID
                    const oldId = tempId;
                    band.id = result.id;
                    band._isNew = false;
                    band._isSaving = false;
                    this.stateManager.replaceBandId(oldId, result.id);
                    const element = this.svg.findOne(`#band-${oldId}`);
                    if (element) element.attr('id', `band-${result.id}`);

                    // No longer needs the batch save, nor the backup; clean if nothing else is pending.
                    this.stateManager.confirmBandCreated(oldId);

                    // Update selection if this band was selected
                    if (this.selectedId === oldId) {
                        this.selectedId = result.id;
                    }

                    // Emit event so UI can re-enable type selector
                    this.eventBus.emit(Events.BAND_SAVE_COMPLETE, {
                        id: result.id,
                        tempId: oldId,
                    });

                    if (toast) toast.success(`Band saved (#${result.id})`);
                }).catch(error => {
                    console.error('Failed to create band on server:', error);
                    // Clear saving state even on error - allow user to retry
                    band._isSaving = false;
                    this.eventBus.emit(Events.BAND_SAVE_FAILED, {
                        id: tempId,
                        error: (error && error.message) || 'Save failed',
                    });
                    // Band stays local with temp ID, will be created on Save
                    if (toast) toast.error(`Band save failed: ${error.message || error}`);
                });
            } else {
                // Lane is new (temp ID), band will be saved in batch save
                // Clear saving state immediately - no race condition here
                band._isSaving = false;
                this.eventBus.emit(Events.BAND_SAVE_COMPLETE, {
                    id: tempId,
                    tempId: tempId,
                    deferred: true,  // Indicates save was deferred to batch
                });
                if (this.toasts) {
                    this.toasts.info('Band created (will save with lane)');
                }
            }
        }

        /**
         * Estimate MW for a band position using calibration data.
         * Uses position-weighted interpolation for multi-ladder calibration.
         */
        _estimateBandMW(positionY, lane) {
            if (!this.calibrationData?.is_calibrated) return null;

            const calibrations = this.calibrationData.calibrations;
            if (!calibrations?.length) return null;

            // Rf MUST be computed in the LADDER lane's reference frame —
            // that's the frame the calibration curve was fit in. Using the
            // sample lane's bbox (lane.y / lane.height) skews the estimate
            // whenever the sample bbox doesn't perfectly match the ladder
            // bbox, which happens routinely when lanes are drawn or resized
            // by hand. Each calibration carries its ladder's lane_top /
            // lane_bottom from the server (LadderCalibrationData.to_dict).
            if (calibrations.length === 1) {
                return this._calculateMWUsingLadderFrame(positionY, calibrations[0]);
            }

            // Multi-ladder: each ladder applies its own frame, then we
            // interpolate the resulting MWs across X position.
            const laneCenterX = lane.x + lane.width / 2;
            return this._interpolateMWFromCalibrations(positionY, laneCenterX, calibrations);
        }

        /**
         * MW from a single calibration, using THAT ladder's lane bounds for Rf.
         * Returns null if Rf falls outside [0,1] or if MW is non-physical.
         */
        _calculateMWUsingLadderFrame(positionY, calibration) {
            const top = calibration.lane_top;
            const bottom = calibration.lane_bottom;
            if (top == null || bottom == null || bottom <= top) return null;

            const rf = (positionY - top) / (bottom - top);
            if (rf < 0 || rf > 1) return null;

            return this._calculateMWFromCalibration(rf, calibration);
        }

        /**
         * Calculate MW from Rf using calibration coefficients.
         */
        _calculateMWFromCalibration(rf, calibration) {
            const coeffs = calibration.coefficients;
            let log10MW;

            if (coeffs.slope !== undefined) {
                // Log-linear: log10(MW) = slope * Rf + intercept
                log10MW = coeffs.slope * rf + coeffs.intercept;
            } else if (coeffs.coeffs) {
                // Polynomial: evaluate polynomial
                log10MW = coeffs.coeffs.reduce((acc, c, i) =>
                    acc + c * Math.pow(rf, coeffs.coeffs.length - 1 - i), 0);
            } else {
                return null;
            }

            const mw = Math.pow(10, log10MW);
            return mw > 0 && mw < 1000 ? Math.round(mw * 100) / 100 : null;
        }

        /**
         * Interpolate MW between multiple ladders based on X position.
         *
         * Each ladder's MW is computed using THAT ladder's own lane_top /
         * lane_bottom for the Rf calculation — mirrors the server-side
         * MultiLadderCalibrationService. Mixing reference frames here would
         * make the gel-smile correction worse than no correction at all.
         */
        _interpolateMWFromCalibrations(positionY, xPosition, calibrations) {
            // Sort by X position
            const sorted = [...calibrations].sort((a, b) =>
                a.ladder_x_position - b.ladder_x_position);

            // Find nearest calibrations
            let left = null, right = null;
            for (const cal of sorted) {
                if (cal.ladder_x_position <= xPosition) left = cal;
                if (cal.ladder_x_position >= xPosition && !right) right = cal;
            }

            // Edge cases
            if (!left) return this._calculateMWUsingLadderFrame(positionY, right);
            if (!right) return this._calculateMWUsingLadderFrame(positionY, left);
            if (left === right) return this._calculateMWUsingLadderFrame(positionY, left);

            // Interpolate between two ladders — each in its own Rf frame.
            const leftMW = this._calculateMWUsingLadderFrame(positionY, left);
            const rightMW = this._calculateMWUsingLadderFrame(positionY, right);
            if (!leftMW || !rightMW) return leftMW || rightMW;

            const t = (xPosition - left.ladder_x_position) /
                      (right.ladder_x_position - left.ladder_x_position);
            return Math.round((leftMW * (1 - t) + rightMW * t) * 100) / 100;
        }

        /**
         * Apply a band patch locally — mutate state, refresh the SVG class
         * if band_type changed, and emit BAND_UPDATED so panels refresh.
         * Does NOT call the server. Reusable from any caller that already
         * persisted via its own endpoint (e.g. context menu's PATCH for
         * calibration quant_point).
         *
         * Every band edit of the editor ends here, so this is where the band's previous type is known: when the type
         * changes, and only then, the lane follows it (_autoPromoteLaneForBand) or, a CALIBRATION lane, is asked
         * (_askLaneTypeForBand) -- owner, 2026-10-13. The promote once listened to BAND_UPDATED, which every edit
         * fires (an MW, a label, a ladder template's Apply): a POI band left in a lane retyped MW Ladder turned it back
         * into a Sample lane at its first edit, and the lane PUT made the server drop its ladder template.
         * @param {Object} [options]
         * @param {boolean} [options.askLaneType=true] - false: the caller asks the lane question itself
         *     (_updateBand, once its PUT is saved)
         */
        _syncBandLocally(id, data, { askLaneType = true } = {}) {
            const band = this.stateManager.getBand(id);
            if (!band) return null;

            const typeChanged = 'band_type' in data && data.band_type !== band.band_type;
            Object.assign(band, data);

            if (data.band_type) {
                const element = this.svg.findOne(`#band-${id}`);
                if (element) {
                    element
                        .removeClass('other')
                        .removeClass('mw_reference')
                        .removeClass('poi')
                        .removeClass('calibration')
                        .removeClass('control');
                    element.addClass(data.band_type.toLowerCase());
                }
            }

            this.eventBus.emit(Events.BAND_UPDATED, band);
            if (typeChanged) {
                this._autoPromoteLaneForBand(band);
                if (askLaneType) this._askLaneTypeForBand(band);
            }
            return band;
        }

        /**
         * Semantic mapping: when a band gets a specific type, what lane type
         * does it imply?
         *
         * - CALIBRATION band → CALIBRATION lane (server also enforces this)
         * - MW_REFERENCE band → LADDER lane (MW ref bands belong to ladders)
         * - POI band → SAMPLE lane (POI = point of interest in a sample)
         *
         * OTHER is intentionally absent: it's a generic catch-all and a band
         * being re-typed to OTHER doesn't imply anything about the lane.
         * Auto-promoting OTHER → SAMPLE silently downgraded LADDER lanes
         * whenever a user re-typed an MW_REFERENCE band to OTHER (e.g. to
         * remove a spurious marker), wiping the LADDER classification. The
         * neutral mapping respects user intent on the band without dragging
         * the lane along.
         *
         * Guards in _autoPromoteLaneForBand still skip the promotion if the
         * lane is CONTROL (deliberate choice) or already at the target type.
         * A CALIBRATION lane is never left automatically: _askLaneTypeForBand
         * asks, when a band there is given another type.
         */
        static get BAND_TO_LANE_PROMOTE() {
            return {
                CALIBRATION: 'CALIBRATION',
                MW_REFERENCE: 'LADDER',
                POI: 'SAMPLE',
            };
        }

        /**
         * Auto-promote the parent lane when a band's type implies a specific
         * lane type. Run by _syncBandLocally when the band's type changes,
         * never on another edit of the band. Skips:
         *  - bands with no implied lane type (OTHER)
         *  - lanes already at the target type (idempotent)
         *  - CONTROL lanes (deliberate analytical choice — a CONTROL band
         *    in a CONTROL lane stays as a control point, not a promotion)
         *  - CALIBRATION lanes: leaving one may discard its calibration
         *    points, which is asked, never automatic (_askLaneTypeForBand);
         *    the lane PUT below refuses it (409) while the lane holds points
         *
         * For CALIBRATION the server already promotes via
         * apply_band_type (every band_type write); this is purely the local visual sync.
         * For MW_REFERENCE / POI the local change is also pushed via
         * apiClient.updateLane so the lane_type persists.
         */
        _autoPromoteLaneForBand(band) {
            if (!band) return;
            const targetType = GelViewerApp.BAND_TO_LANE_PROMOTE[band.band_type];
            if (!targetType) return;

            const laneId = band.lane_id || band._parentLaneId;
            if (!laneId) return;
            const lane = this.stateManager.getLane(laneId);
            if (!lane) return;
            if (lane.lane_type === targetType) return;
            if (lane.lane_type === 'CONTROL') return;
            if (lane.lane_type === 'CALIBRATION') return;

            lane.lane_type = targetType;
            if (typeof StateManager !== 'undefined' && StateManager.getLaneTypeDisplay) {
                lane.lane_type_display = StateManager.getLaneTypeDisplay(targetType);
            }
            const element = this.svg.findOne(`#lane-${laneId}`);
            if (element) {
                element
                    .removeClass('sample')
                    .removeClass('ladder')
                    .removeClass('control')
                    .removeClass('calibration')
                    .removeClass('empty')
                    .removeClass('dot');
                element.addClass(targetType.toLowerCase());
            }
            const displayLabel = (StateManager && StateManager.getLaneTypeDisplay)
                ? StateManager.getLaneTypeDisplay(targetType)
                : targetType;
            this._showMessage(`Lane ${lane.lane_number} → ${displayLabel} (auto)`);
            this.eventBus.emit(Events.LANE_UPDATED, lane);

            // The server already auto-promotes CALIBRATION via the band PATCH
            // (band_type_change.apply_band_type) — re-PUTting the
            // lane there would be redundant. For MW_REFERENCE → LADDER and
            // POI → SAMPLE the server doesn't auto-promote, so persist the
            // lane change explicitly. Fire-and-forget; if it fails the
            // optimistic UI is already updated and the next batch save will
            // pick it up via the dirty tracker.
            if (band.band_type !== 'CALIBRATION'
                && this.apiClient
                && typeof this.apiClient.updateLane === 'function'
                && !String(laneId).startsWith('temp_')) {
                const change = { lane_type: targetType };
                this.stateManager.trackLaneUpdate(laneId, change);
                this.apiClient.updateLane(laneId, change).then(() => {
                    // Only the type was saved: a resize of this lane waiting for Save stays pending.
                    this.stateManager.confirmUpdateSaved('lanes', laneId, change);
                }).catch((err) => {
                    console.warn(`Auto-promote lane PUT failed for lane ${laneId}:`, err);
                    this.stateManager.markDirty();
                });
            }
        }

        /**
         * A band just typed POI or MW_REFERENCE in a CALIBRATION lane: the lane type it implies goes through the lane
         * form's own path, PropertiesPanel.changeLaneType, which asks before discarding calibration points and purges
         * them on the server (the v1 PATCH, ?force=true). "Keep calibration" leaves the lane as it is. Asked when the
         * band's type changes only (_syncBandLocally), never on another edit of the band: an answer is not asked
         * again at every label or drag.
         * @param {Object} band - The band, its new type already set
         */
        _askLaneTypeForBand(band) {
            const targetType = GelViewerApp.BAND_TO_LANE_PROMOTE[band.band_type];
            if (!targetType || targetType === 'CALIBRATION' || !this.propertiesPanel) return;
            const lane = this.stateManager.getLane(band.lane_id || band._parentLaneId);
            if (!lane || lane.lane_type !== 'CALIBRATION') return;
            this.propertiesPanel.changeLaneType(lane.id, targetType, null);
        }

        _updateBand(id, data) {
            const stored = this.stateManager.getBand(id);
            const typeChanged = !!stored && 'band_type' in data && data.band_type !== stored.band_type;
            // The lane question waits for the PUT: leaving CALIBRATION, the PUT deletes the band's calibration point,
            // which the lane's guard would otherwise still count ("Discard calibration points?" for a point no band
            // shows any more).
            const band = this._syncBandLocally(id, data, { askLaneType: false });
            if (!band) return;

            this.stateManager.trackBandUpdate(id, data);

            // Async server call for persisted bands (fire-and-forget, like delete)
            const isTempBand = String(id).startsWith('temp_');
            if (!isTempBand) {
                // "Band updated" once the server has it, never before: signed out, it was said over a change the
                // server never got (api-client.js, SessionExpiredError).
                this.apiClient.updateBand(id, data).then(() => {
                    // Only these fields were saved: an earlier edit whose PUT failed stays pending.
                    this.stateManager.confirmUpdateSaved('bands', id, data);
                    this._showMessage('Band updated');
                    if (typeChanged) this._askLaneTypeForBand(band);
                }).catch(error => {
                    console.error('Failed to update band on server:', error);
                    // Band stays in pending updates, will sync on Save. No lane question: the PUT did not land (signed
                    // out or refused), so the band's calibration point is still there.
                    this.stateManager.markDirty();
                    this._showMessage(`Band changed here, not saved: ${error.message}. The next Save sends it.`, 6000);
                });
            } else {
                this.stateManager.markDirty();
                this._showMessage('Band updated (unsaved)');
                // An unsaved band holds no calibration point.
                if (typeChanged) this._askLaneTypeForBand(band);
            }
        }

        async _deleteBand(id) {
            let band = this.stateManager.getBand(id);
            if (!band) return;

            // Every path asks here, once: Delete key, toolbar, context menu, properties panel, Band Editor. A saved
            // band is deleted on the server at once, below.
            if (this.confirmationManager) {
                const laneId = band._parentLaneId || band.lane_id;
                const lane = this.stateManager.getLane(laneId);
                // "Band N" as the properties panel and the Band Editor number it (top to bottom in its lane).
                const index = this.stateManager.getBandsForLane(laneId).findIndex(b => b.id === id);
                const name = band.label || (index >= 0 ? `Band ${index + 1}` : 'this band');
                const confirmed = await this.confirmationManager.confirmDeleteBand(name, lane ? lane.lane_number : null);
                if (!confirmed) return;
                // While the dialog was open: a just-drawn band's POST may have landed (same object, server id now,
                // _createBand), a reload replaced it, the lane's delete removed it.
                id = band.id;
                band = this.stateManager.getBand(id);
                if (!band) return;
            }

            const isTempBand = String(id).startsWith('temp_');

            // Leave the pending sets first. Never saved: forgotten, or the next Save creates it again. Saved: deleted
            // on the server below, so no pending edit may PUT to it.
            band._removed = true;  // a POST still in flight deletes what it created (_createBand)
            if (isTempBand) {
                this.stateManager.trackBandDeletion(id);
            } else {
                this.stateManager.forgetBandUpdate(id);
            }

            // Remove from parent lane
            const laneId = band._parentLaneId || band.lane_id;
            const lane = this.stateManager.getLane(laneId);
            if (lane && lane.bands) {
                lane.bands = lane.bands.filter(b => b.id !== id);
            }

            // Update UI immediately (optimistic)
            this.renderer.removeBand(id);
            this.stateManager.deleteBand(id);

            if (this.selectedId === id) {
                this._deselect();
            }

            // Delete on server in background — pending toast morphs into
            // success/error so the user actually knows whether the server
            // confirmed (the previous fire-and-forget showed "Band deleted"
            // even when the DELETE silently failed in the background).
            if (!isTempBand) {
                const toast = this.toasts ? this.toasts.pending('Deleting band…') : null;
                this.apiClient.deleteBand(id).then(() => {
                    if (toast) toast.success('Band deleted');
                }).catch(error => {
                    console.error('Failed to delete band on server:', error);
                    if (error && error.name === 'SessionExpiredError') {
                        // Signed out: the server never saw the delete, and a reload would fail the same way. The
                        // delete waits for the next Save, once logged in again, like every other change (info, not a
                        // sticky error: the session notice and the unsaved count say it until then).
                        this.stateManager.trackBandDeletion(id);
                        if (toast) toast.info(`Not deleted on the server yet: ${error.message}. Save deletes it.`);
                        return;
                    }
                    if (toast) {
                        toast.error(`Delete failed: ${error.message || error}. The band reappeared because the server rejected the change.`);
                    }
                    // Server rejected the delete — the local optimistic
                    // removal is now wrong. Reload from server so state
                    // matches the truth. Cheaper + safer than trying to
                    // restore the band from a cached copy.
                    this.eventBus.emit(Events.DATA_RELOAD_REQUESTED);
                });
            } else {
                if (this.toasts) this.toasts.info('Band removed (unsaved)');
            }
            // The one emitter of BAND_DELETED (nothing emitted it before 2026-10-13), once the band has left the state:
            // the Band Editor drops its row, the toolbar refreshes counts, Split and Densitometry (a saved band leaves
            // no pending change), and a ladder band marks the MW calibration stale -- as editing one does (owner,
            // 2026-10-13). The band itself is the payload: its lane_id names the lane.
            this.eventBus.emit(Events.BAND_DELETED, band);
        }

        async _splitBand(bandId, splitY) {
            const band = this.stateManager.getBand(bandId);
            if (!band) {
                if (this.toasts) this.toasts.error('Band not found');
                return;
            }

            // Get the band's polygon points
            const polygon = band.polygon;
            if (!polygon || polygon.length < 3) {
                if (this.toasts) this.toasts.error('Cannot split: invalid band polygon');
                return;
            }

            // If splitting a CALIBRATION band: the backend cascade-deletes
            // the attached ProteinQuantCalibrationPoint (OneToOne CASCADE)
            // and the two halves would inherit band_type=CALIBRATION but
            // with no point — an orphan state. Prompt the user, then on
            // confirm flip both halves to OTHER so they're at least
            // self-consistent. The user can re-tag whichever half belongs
            // to the curve afterwards.
            const isCalibrationSplit = band.band_type === 'CALIBRATION';
            if (isCalibrationSplit) {
                const cm = this.confirmationManager;
                let confirmed = false;
                if (cm && cm.modal) {
                    confirmed = await cm.show({
                        title: 'Split a calibration band?',
                        body:
                            '<p>This band is tagged <strong>Calibration</strong> and ' +
                            'carries a calibration point used by the quantification curve.</p>' +
                            '<p>Splitting it will:</p>' +
                            '<ul>' +
                            '<li>Discard the attached calibration point</li>' +
                            '<li>Re-tag both halves as <strong>Other</strong></li>' +
                            '</ul>' +
                            '<p class="mb-0"><em>Re-mark whichever half belongs to the ' +
                            'curve afterwards. This cannot be undone.</em></p>',
                        confirmText: 'Split & discard point',
                        cancelText: 'Keep band intact',
                        danger: true,
                        icon: 'exclamation-triangle-fill',
                    });
                }
                // No dialog to ask with: nothing is split.
                if (!confirmed) {
                    // Drop the split tool — the user has acknowledged, no
                    // sense leaving them stuck mid-gesture.
                    this.toolManager.setTool('select');
                    return;
                }
            }

            // Split the polygon into upper and lower portions
            const upperPoints = [];
            const lowerPoints = [];

            // Find intersections of the split line with polygon edges
            const intersections = [];
            for (let i = 0; i < polygon.length; i++) {
                const p1 = polygon[i];
                const p2 = polygon[(i + 1) % polygon.length];

                // Check if edge crosses the split line
                if ((p1[1] <= splitY && p2[1] >= splitY) || (p1[1] >= splitY && p2[1] <= splitY)) {
                    if (p1[1] !== p2[1]) {
                        const t = (splitY - p1[1]) / (p2[1] - p1[1]);
                        const intersectX = p1[0] + t * (p2[0] - p1[0]);
                        intersections.push({ x: intersectX, y: splitY, edgeIndex: i });
                    }
                }
            }

            // Need exactly 2 intersections to split
            if (intersections.length < 2) {
                if (this.toasts) this.toasts.error('Cannot split at this position');
                return;
            }

            // Sort intersections by X coordinate
            intersections.sort((a, b) => a.x - b.x);

            // Build upper polygon (points above split line + intersection points)
            // Build lower polygon (points below split line + intersection points)
            for (const point of polygon) {
                if (point[1] <= splitY) {
                    upperPoints.push([...point]);
                }
                if (point[1] >= splitY) {
                    lowerPoints.push([...point]);
                }
            }

            // Add intersection points to both polygons
            const leftInt = [Math.round(intersections[0].x), Math.round(splitY)];
            const rightInt = [Math.round(intersections[intersections.length - 1].x), Math.round(splitY)];

            // Insert intersection points in correct order
            upperPoints.push(leftInt, rightInt);
            lowerPoints.push(leftInt, rightInt);

            // Sort points to form proper polygons (convex hull approximation)
            const sortPolygonPoints = (points) => {
                if (points.length < 3) return points;
                const centerX = points.reduce((sum, p) => sum + p[0], 0) / points.length;
                const centerY = points.reduce((sum, p) => sum + p[1], 0) / points.length;
                return points.sort((a, b) => {
                    const angleA = Math.atan2(a[1] - centerY, a[0] - centerX);
                    const angleB = Math.atan2(b[1] - centerY, b[0] - centerX);
                    return angleA - angleB;
                });
            };

            const sortedUpper = sortPolygonPoints(upperPoints);
            const sortedLower = sortPolygonPoints(lowerPoints);

            if (sortedUpper.length < 3 || sortedLower.length < 3) {
                if (this.toasts) this.toasts.error('Cannot split: resulting shapes invalid');
                return;
            }

            // Calculate bounding boxes for new bands
            const calcBbox = (points) => {
                const xs = points.map(p => p[0]);
                const ys = points.map(p => p[1]);
                return {
                    x: Math.min(...xs),
                    y: Math.min(...ys),
                    width: Math.max(...xs) - Math.min(...xs),
                    height: Math.max(...ys) - Math.min(...ys)
                };
            };

            const upperBbox = calcBbox(sortedUpper);
            const lowerBbox = calcBbox(sortedLower);

            // Get the parent lane ID
            const parentLaneId = band.lane_id || band._parentLaneId;
            if (!parentLaneId) {
                if (this.toasts) this.toasts.error('Cannot split: unknown parent lane');
                return;
            }

            // Halves inherit the original's band_type, except for a confirmed
            // CALIBRATION split (which loses its point — see the prompt
            // above): in that case downgrade both halves to OTHER so they
            // aren't stranded as point-less calibration bands.
            const halfBandType = isCalibrationSplit ? 'OTHER' : (band.band_type || 'OTHER');

            // Build payloads for the two halves
            const upperBandData = {
                polygon: sortedUpper,
                position_y: Math.round(upperBbox.y + upperBbox.height / 2),
                bbox_x: Math.round(upperBbox.x),
                bbox_y: Math.round(upperBbox.y),
                bbox_width: Math.round(upperBbox.width),
                bbox_height: Math.round(upperBbox.height),
                band_type: halfBandType,
                label: band.label ? `${band.label} (upper)` : '',
                notes: band.notes || ''
            };
            const lowerBandData = {
                polygon: sortedLower,
                position_y: Math.round(lowerBbox.y + lowerBbox.height / 2),
                bbox_x: Math.round(lowerBbox.x),
                bbox_y: Math.round(lowerBbox.y),
                bbox_width: Math.round(lowerBbox.width),
                bbox_height: Math.round(lowerBbox.height),
                band_type: halfBandType,
                label: band.label ? `${band.label} (lower)` : '',
                notes: band.notes || ''
            };

            // Single atomic POST /api/bands/<id>/split/ — the backend
            // deletes the original + creates the two halves in a single
            // transaction and returns both new band dicts. Replaces the
            // legacy DELETE → CREATE → CREATE → reload chain (4 RTTs) with
            // 1 RTT. Also removes the "DELETE arrives after the CREATEs"
            // race that motivated the previous sequential await pattern.
            const toast = this.toasts ? this.toasts.pending('Splitting band…') : null;
            const isTempBand = String(bandId).startsWith('temp_');

            // Temp bands aren't on the server yet — DATA_RELOAD_REQUESTED
            // would re-fetch the server state which doesn't know about
            // them, so the split would silently vanish. Apply the split
            // entirely locally: remove the original from state + SVG,
            // create two new temp bands with the computed polygons, push
            // them into the lane, and mark the analysis dirty so the
            // batch save persists all three operations together.
            if (isTempBand) {
                // 1. Drop the original temp band from state + SVG
                const parentLane = this.stateManager.getLane(parentLaneId);
                if (parentLane && parentLane.bands) {
                    parentLane.bands = parentLane.bands.filter(b => b.id !== bandId);
                }
                this.renderer.removeBand(bandId);
                this.stateManager.deleteBand(bandId);
                // It never reached the server: forgetting its pending creation is the whole deletion. A POST still in
                // flight deletes what it created (_createBand).
                band._removed = true;
                this.stateManager.trackBandDeletion(bandId);

                // 2. Insert the two halves as fresh temp bands
                const makeTempHalf = (halfData) => {
                    const tempId = this.stateManager.generateTempId();
                    const half = {
                        id: tempId,
                        _isNew: true,
                        _parentLaneId: parentLaneId,
                        lane_id: parentLaneId,
                        ...halfData,
                    };
                    this.stateManager.setBand(tempId, half);
                    this.stateManager.trackBandCreation(tempId, half);
                    if (parentLane) {
                        parentLane.bands = parentLane.bands || [];
                        parentLane.bands.push(half);
                    }
                    this.renderer.renderBand(half);
                    return half;
                };
                const upperHalf = makeTempHalf(upperBandData);
                const lowerHalf = makeTempHalf(lowerBandData);

                this.stateManager.markDirty();
                if (toast) {
                    toast.info('Band split (will save with lane)');
                }
                // Select the upper half so the user has a meaningful focus
                // after the split, mirroring the post-split UX on persisted
                // bands (which select via the reload's natural flow).
                this._selectAnnotation('band', upperHalf.id);
                this.toolManager.setTool('select');
                return;
            }

            try {
                const result = await this.apiClient.splitBand(bandId, {
                    upper: upperBandData,
                    lower: lowerBandData,
                });
                if (toast) {
                    toast.success(
                        `Band split into 2 (#${result.upper?.id || '?'}, #${result.lower?.id || '?'})`
                    );
                }
            } catch (error) {
                console.error('[GelViewer] Split failed:', error);
                if (toast) {
                    toast.error(`Split failed: ${error.message || error}. Reloading from server…`);
                }
                // Atomic endpoint rolled back on its side, but the local
                // state may have already drifted (e.g. user kept editing).
                // Reload to be safe — matches the old behaviour.
                this.eventBus.emit(Events.DATA_RELOAD_REQUESTED);
                this.toolManager.setTool('select');
                return;
            }

            // Reload from server so local state picks up the new band IDs
            // for the two halves and drops the deleted original. Cheaper
            // than splicing the result into the optimistic state by hand
            // (we'd have to update lane.bands, the SVG, the band table,
            // the densitometry view…). The single reload is fast enough
            // and keeps every panel in sync the same way as before.
            this.eventBus.emit(Events.DATA_RELOAD_REQUESTED);

            // Switch back to select tool
            this.toolManager.setTool('select');
        }

        // =====================================================================
        // Phase 3: YOLO Inference
        // =====================================================================

        /**
         * Run auto-detection using YOLO model.
         * Initializes InferenceEngine and ReviewPanel on first use.
         */
        async _autoDetect() {
            if (!this.isEditable) {
                this._showMessage('Cannot auto-detect: analysis is not editable');
                return;
            }

            // Check if inference is already running
            if (this.inferenceEngine && this.inferenceEngine.isInferring) {
                this._showMessage('Detection already in progress...');
                return;
            }

            // Confirmation if lanes already exist - REPLACE behavior
            const existingLaneCount = this.stateManager.getLaneCount();
            const existingBandCount = this.stateManager.getBandCount();
            if (existingLaneCount > 0 && this.confirmationManager) {
                const confirmed = await this.confirmationManager.confirmDetectLanes(existingLaneCount, existingBandCount);
                if (!confirmed) return;

                // Delete all existing lanes (and their bands) before detection
                this._showLoading('Clearing existing annotations...');
                try {
                    await this.apiClient.deleteAllLanes();
                    this.stateManager.clearAll();
                    // Nothing pending can still apply: the saved lanes are gone with their bands, the unsaved ones
                    // with the canvas. Left pending, a lane drawn by hand came back at the next Save beside the
                    // detected ones, an edit of a replaced lane failed every Save, and the backup offered them again.
                    this.stateManager.markClean();
                    this.renderer.clearAll();
                    // Every lane is gone server-side, the HCP reference with it (SET_NULL).
                    this.readout.referenceLaneId = null;
                    this.renderer.setReferenceLane(null);
                    this._updateToolbarState();
                } catch (error) {
                    console.error('Failed to clear existing lanes:', error);
                    this._hideLoading();
                    this._showMessage(`❌ Failed to clear existing lanes: ${(error && error.message) || error}`);
                    return;
                }
            }

            try {
                // Lazy initialization of InferenceEngine
                if (!this.inferenceEngine) {
                    this._showLoading('Loading AI model...');

                    this.inferenceEngine = new InferenceEngine({
                        eventBus: this.eventBus,
                        modelUrl: '/static/gel_analyzer/ml/gel_analysis.onnx',
                        imageWidth: this.options.imageWidth,
                        imageHeight: this.options.imageHeight,
                        // A 25 % floor: the review's slider starts at 50 %, the old cut, and can bring back
                        // a lane the model saw below it (review-panel.js).
                        confidenceThreshold: 0.25
                    });

                    await this.inferenceEngine.initialize();
                }

                // Lazy initialization of ReviewPanel
                if (!this.reviewPanel) {
                    this.reviewPanel = new ReviewPanel({
                        eventBus: this.eventBus,
                        stateManager: this.stateManager,
                        svg: this.svg,
                        viewport: this.viewport,
                        apiClient: this.apiClient,
                        onAccept: (detections) => this._acceptDetections(detections)
                    });
                }

                // Get the gel image element
                const imageEl = document.getElementById('gel-image');
                if (!imageEl) {
                    throw new Error('Gel image not found');
                }
                console.log('Auto-detect: Image element found', {
                    src: imageEl.src,
                    naturalWidth: imageEl.naturalWidth,
                    naturalHeight: imageEl.naturalHeight
                });

                this._showLoading('Detecting lanes...');

                // Run inference
                console.log('Auto-detect: Starting inference...');
                const results = await this.inferenceEngine.runInference(imageEl);
                console.log('Auto-detect: Inference complete', results);

                // Extract detections from results
                const detections = results?.detections || [];
                const gelType = results?.inferredGelType || 'UNKNOWN';
                console.log('Auto-detect: Detections:', detections.length, 'Gel type:', gelType);

                this._hideLoading();

                if (detections && detections.length > 0) {
                    console.log('Auto-detect: Processing', detections.length, 'detections');

                    // Show the review; a click on the gel is a click on a detected lane, not a lane being drawn
                    console.log('Auto-detect: Showing review panel...');
                    this.toolManager.setTool('select');
                    this.reviewPanel.show(detections, gelType);

                    // Save raw YOLO results to server
                    try {
                        await this.apiClient.saveYoloResults({
                            detections: detections,
                            inferred_gel_type: gelType
                        });
                        console.log('Auto-detect: YOLO results saved to server');
                    } catch (saveError) {
                        console.warn('Failed to save YOLO results:', saveError);
                        // Don't block the UI if saving fails
                    }

                    const kept = this.reviewPanel.getSelectedDetections().length;
                    this._showMessage(`${kept} lanes detected - review them on the gel`);
                } else {
                    console.log('Auto-detect: No detections returned');
                    this._showMessage('No lanes detected');
                }

            } catch (error) {
                console.error('Auto-detect error:', error);
                this._hideLoading();
                this._showMessage('Detection failed: ' + error.message);
            }
        }

        /**
         * Accept detections and create lanes from them.
         * Uses bulk API to create all lanes in a single request.
         * @param {Array} detections - Array of detection objects to accept
         */
        async _acceptDetections(detections) {
            if (!detections || detections.length === 0) {
                this._showMessage('No detections to accept');
                return;
            }

            // Prepare lane data for bulk creation
            const lanesData = detections.map((det, index) => ({
                lane_number: index + 1,  // Will be recalculated by server
                lane_type: det.lane_type || 'SAMPLE',
                // The review's shape: QUADRILATERAL when it follows a tilted lane, else today's 4-point POLYGON
                lane_shape: det.lane_shape || (det.polygon ? 'POLYGON' : 'RECTANGLE'),
                polygon: det.polygon || null,
                x: det.bbox ? Math.round(det.bbox[0]) : 0,
                y: det.bbox ? Math.round(det.bbox[1]) : 0,
                width: det.bbox ? Math.round(det.bbox[2]) : 0,
                height: det.bbox ? Math.round(det.bbox[3]) : 0,
                detection_source: 'YOLO',
                confidence: det.confidence || null,
            }));

            try {
                this._showLoading('Creating lanes...');

                // Single API call for all lanes
                const result = await this.apiClient.createLanesBulk(lanesData);

                this._hideLoading();

                // Update local state with server-assigned IDs
                for (const serverLane of result.lanes) {
                    // Add display properties
                    serverLane.lane_type_display = StateManager.getLaneTypeDisplay(serverLane.lane_type);
                    serverLane.bands = serverLane.bands || [];

                    // Store in state manager
                    this.stateManager.setLane(serverLane.id, serverLane);

                    // Render the lane
                    this.renderer.renderLane(serverLane);
                }

                // No height normalisation afterwards: the review already cut every lane at the common top and bottom
                // of the kept lanes, and saved what it showed (spec 2026-10-10 §10).

                const tilted = detections.filter(d => d.lane_shape === 'QUADRILATERAL').length;
                this._showMessage(tilted
                    ? `${result.count} lanes created, ${tilted} following their tilt`
                    : `${result.count} lanes created from detection`);

                // Update toolbar state (e.g., disable crop button now that lanes exist)
                this._updateToolbarState();

            } catch (error) {
                console.error('Bulk lane creation failed:', error);
                this._hideLoading();
                this._showMessage('Failed to create lanes: ' + error.message);
            }
        }

        /**
         * Create a lane from a YOLO detection result.
         * @param {Object} detection - Detection object with polygon, bbox, lane_type, confidence
         */
        _createLaneFromDetection(detection) {
            const tempId = this.stateManager.generateTempId();
            const nextNumber = this.stateManager.getNextLaneNumber();

            // Build lane object from detection
            const lane = {
                id: tempId,
                lane_number: nextNumber,
                lane_type: detection.lane_type || 'SAMPLE',
                lane_type_display: StateManager.getLaneTypeDisplay(detection.lane_type || 'SAMPLE'),
                lane_shape: detection.polygon ? 'POLYGON' : 'RECTANGLE',
                polygon: detection.polygon || null,
                x: detection.bbox ? Math.round(detection.bbox[0]) : 0,
                y: detection.bbox ? Math.round(detection.bbox[1]) : 0,
                width: detection.bbox ? Math.round(detection.bbox[2]) : 0,
                height: detection.bbox ? Math.round(detection.bbox[3]) : 0,
                detection_source: 'YOLO',
                confidence: detection.confidence || null,
                bands: [],
                _isNew: true
            };

            // Store in state manager
            this.stateManager.setLane(tempId, lane);
            this.stateManager.trackLaneCreation(tempId, lane);

            // Render the lane
            this.renderer.renderLane(lane);
        }

        // =====================================================================
        // Batch Save
        // =====================================================================

        async _batchSave() {
            if (!this.stateManager.isDirty) {
                this._showMessage('No changes to save');
                return;
            }

            const saveBtn = document.getElementById('save-btn');
            this._batchSaving = true;  // the reading is read once, at the end (_scheduleReadingRefresh)
            try {
                saveBtn?.classList.add('saving');
                this._showLoading('Saving...');

                const pending = this.stateManager.pendingChanges;
                const idMapping = { lanes: {}, bands: {} };

                // Every entry leaves `pending` as soon as the server has it, and a created one leaves the backup at
                // once: a save that fails half way (or a tab closed during it) must not make a retry or a restored
                // backup create it twice.

                // Save created lanes
                for (const [tempId, data] of pending.lanes.created) {
                    const result = await this.apiClient.createLane(data);
                    idMapping.lanes[tempId] = result.id;
                    pending.lanes.created.delete(tempId);
                    for (const band of pending.bands.created.values()) {
                        if (band._parentLaneId === tempId) band._parentLaneId = band.lane_id = result.id;
                    }
                    this.stateManager.saveToLocalStorage();

                    // Update local state with real ID
                    const lane = this.stateManager.getLane(tempId);
                    if (lane) {
                        lane.id = result.id;
                        lane._isNew = false;
                        this.stateManager.deleteLane(tempId);
                        this.stateManager.setLane(result.id, lane);

                        // Update SVG element ID
                        const element = this.svg.findOne(`#lane-${tempId}`);
                        if (element) element.attr('id', `lane-${result.id}`);
                        const label = this.svg.findOne(`#lane-label-${tempId}`);
                        if (label) label.attr('id', `lane-label-${result.id}`);
                    }
                    // The selection and the form shown follow the new id (a temp_ id finds no lane any more).
                    if (this.selectedId === tempId) this.selectedId = result.id;
                    if (this.propertiesPanel?.currentType === 'lane' && this.propertiesPanel.currentId === tempId) {
                        this.propertiesPanel.currentId = result.id;
                    }
                }

                // Bulk update lanes
                if (pending.lanes.updated.size > 0) {
                    const lanesToUpdate = Array.from(pending.lanes.updated.entries())
                        .map(([id, data]) => ({ id, ...data }));
                    if (lanesToUpdate.length > 0) {
                        await this.apiClient.updateLanesBulk(lanesToUpdate);
                    }
                    pending.lanes.updated.clear();
                }

                // Bulk delete lanes
                const laneIdsToDelete = Array.from(pending.lanes.deleted)
                    .filter(id => !String(id).startsWith('temp_'));
                if (laneIdsToDelete.length > 0) {
                    await this.apiClient.deleteLanesBulk(laneIdsToDelete);
                    // The server nulls the reference of a deleted lane (SET_NULL):
                    // follow it, or the menu would keep checking a ghost.
                    const ref = this.readout.referenceLaneId;
                    if (ref !== null && laneIdsToDelete.some(id => Number(id) === Number(ref))) {
                        this.readout.referenceLaneId = null;
                        this.renderer.setReferenceLane(null);
                    }
                }
                pending.lanes.deleted.clear();

                // Save created bands
                for (const [tempId, data] of pending.bands.created) {
                    const parentLaneId = data._parentLaneId;
                    const realLaneId = idMapping.lanes[parentLaneId] || parentLaneId;

                    const result = await this.apiClient.createBand(realLaneId, data);
                    idMapping.bands[tempId] = result.id;
                    pending.bands.created.delete(tempId);
                    this.stateManager.saveToLocalStorage();

                    // Update local state
                    const band = this.stateManager.getBand(tempId);
                    if (band) {
                        band.id = result.id;
                        band._isNew = false;
                        this.stateManager.deleteBand(tempId);
                        this.stateManager.setBand(result.id, band);

                        // Update SVG element ID
                        const element = this.svg.findOne(`#band-${tempId}`);
                        if (element) element.attr('id', `band-${result.id}`);
                    }
                    // The selection and the form shown follow the new id, as a lane's do above.
                    if (this.selectedId === tempId) this.selectedId = result.id;
                    if (this.propertiesPanel?.currentType === 'band' && this.propertiesPanel.currentId === tempId) {
                        this.propertiesPanel.currentId = result.id;
                    }
                }

                // Save updated bands
                for (const [id, data] of pending.bands.updated) {
                    await this.apiClient.updateBand(id, data);
                    pending.bands.updated.delete(id);
                }

                // Delete bands
                for (const id of pending.bands.deleted) {
                    if (!String(id).startsWith('temp_')) {
                        await this.apiClient.deleteBand(id);
                    }
                    pending.bands.deleted.delete(id);
                }

                // Mark clean
                this.stateManager.markClean();

                this._showMessage('All changes saved successfully');
                this.eventBus.emit(Events.SAVE_COMPLETED);
                if (saveBtn) {
                    saveBtn.classList.add('saved');
                    clearTimeout(this._savedTimer);
                    this._savedTimer = setTimeout(() => saveBtn.classList.remove('saved'), 1500);
                }

            } catch (error) {
                console.error('Save failed:', error);
                this._showMessage('Save failed: ' + error.message);
                this.stateManager.saveToLocalStorage();  // what did not reach the server, and only that
            } finally {
                saveBtn?.classList.remove('saving');
                this._hideLoading();
                this._refreshStatus();
                this._batchSaving = false;
                this._scheduleReadingRefresh();
            }
        }

        // =====================================================================
        // Phase 3: Auto Detection & MW Calibration Callbacks
        // =====================================================================

        /**
         * Handle detection complete callback.
         * Reloads annotations to refresh the view with new bands.
         */
        _onDetectionComplete() {
            console.log('GelViewer: _onDetectionComplete called');
            this._reloadAnnotations();
            this._showMessage('Band detection completed');
        }

        /**
         * Handle calibration applied callback.
         * @param {Object} result - Calibration result with bands_updated count
         */
        _onCalibrationApplied(result) {
            // Bands have been updated with MW values - refresh display
            this._reloadAnnotations();
        }

        /**
         * Reload annotations from server.
         * Used after band detection or calibration to refresh display.
         */
        async _reloadAnnotations() {
            console.log('GelViewer: _reloadAnnotations called');
            // A reading refresh already on its way (or waiting) read the server before this reload: it must not land
            // after it, nor read again what the reload reads.
            this._readingSeq++;
            clearTimeout(this._readingTimer);
            try {
                const data = await this.apiClient.loadAnnotations();
                console.log('GelViewer: loaded data', { laneCount: data.lanes?.length, totalBands: data.lanes?.reduce((sum, l) => sum + (l.bands?.length || 0), 0) });

                // The unsaved changes still applicable ride through the reload and are drawn again below; the others
                // are dropped, so the next Save writes what the canvas shows. Before the maps are cleared: it reads them.
                const dropped = this.stateManager.keepPendingApplicable(data.lanes || []);
                const pending = this.stateManager.pendingChanges;

                // Clear existing state
                this.stateManager.lanes.clear();
                this.stateManager.bands.clear();

                // Clear SVG layers
                this.lanesGroup.clear();
                this.bandsGroup.clear();
                this.handlesGroup.clear();

                // Before the lanes: renderLane draws the REF badge.
                this._applyReadoutContext(data);

                // Re-render from fresh data, with the edits still waiting for Save
                if (data.lanes) {
                    data.lanes.forEach(lane => {
                        const laneEdit = pending.lanes.updated.get(lane.id);
                        if (laneEdit) {
                            Object.assign(lane, laneEdit);
                            if (laneEdit.lane_type) lane.lane_type_display = StateManager.getLaneTypeDisplay(laneEdit.lane_type);
                        }
                        this.stateManager.setLane(lane.id, lane);
                        this.renderer.renderLane(lane);

                        if (lane.bands) {
                            lane.bands.forEach(band => {
                                Object.assign(band, pending.bands.updated.get(band.id));
                                this.stateManager.setBand(band.id, band);
                                this.renderer.renderBand(band);
                            });
                        }
                    });
                }

                // Hides the deletions, draws the new lanes and bands, refreshes the list.
                this._redrawPendingChanges();
                if (dropped > 0 && this.toasts) {
                    this.toasts.info(`Reload: ${dropped} unsaved change${dropped > 1 ? 's' : ''} dropped (no longer applicable)`);
                }
                // The handles layer was cleared: a 4-point lane still selected gets its corners back, as drawn.
                const selected = this.selectedType === 'lane' ? this.stateManager.getLane(this.selectedId) : null;
                if (this._showsCorners(selected)) {
                    this.cornerHandles.show(selected);
                } else {
                    this.cornerHandles.hide();
                }
                // The SVG nodes were drawn again: the selection's outline too (.gv-selected).
                if (this.selectedType !== null) {
                    this.renderer.selectAnnotation(this.selectedType, this.selectedId);
                }
                this.eventBus.emit(Events.DATA_LOADED, data);
                // Also emit ANNOTATIONS_LOADED so toolbar state updates
                this.eventBus.emit(Events.ANNOTATIONS_LOADED, data);
                this.eventBus.emit(Events.READING_CHANGED, this.reading);

            } catch (error) {
                console.error('Failed to reload annotations:', error);
                this._showMessage(`❌ Failed to reload data: ${(error && error.message) || error}`);
            }
        }

        // =====================================================================
        // Utility Methods
        // =====================================================================

        _cancelDrawing() {
            this.drawingGroup.clear();
            const tool = this.toolManager.getActiveTool();
            if (tool && tool.cancel) {
                tool.cancel();
            }
        }

        _recalculateLaneNumbers() {
            const lanes = this.stateManager.getLanesSortedByPosition();
            lanes.forEach((lane, index) => {
                lane.lane_number = index + 1;
                this.renderer.updateLaneNumber(lane.id, lane.lane_number);
            });
        }

        /**
         * Normalize all lane heights to the same top/bottom extent.
         * Takes the global min Y (topmost) and max Y+height (bottommost)
         * across all lanes and applies those uniformly.
         */
        _normalizeLaneHeights() {
            const lanes = this.stateManager.getLanesSortedByPosition();
            if (lanes.length < 2) {
                this._showMessage('Need at least 2 lanes to normalize');
                return;
            }

            this._showLoading('Normalizing lane heights...');

            // Find global top and bottom boundaries
            let globalTop = Infinity;
            let globalBottom = -Infinity;

            // Rule 2: a lane is read by its polygon unless it is a RECTANGLE (which may still store one).
            const G = GelAnalyzer.LaneGeometry;
            for (const lane of lanes) {
                if (G.hasOutline(lane)) {
                    // Use polygon Y extents
                    const ys = lane.polygon.map(p => p[1]);
                    globalTop = Math.min(globalTop, Math.min(...ys));
                    globalBottom = Math.max(globalBottom, Math.max(...ys));
                } else {
                    globalTop = Math.min(globalTop, lane.y);
                    globalBottom = Math.max(globalBottom, lane.y + lane.height);
                }
            }

            const normalizedY = Math.round(globalTop);
            const normalizedBottom = Math.round(globalBottom);
            const normalizedHeight = normalizedBottom - normalizedY;

            let updatedCount = 0;
            for (const lane of lanes) {
                const updateData = {
                    y: normalizedY,
                    height: normalizedHeight
                };

                // Update polygon points if the lane is drawn by one
                if (G.hasOutline(lane)) {
                    const ys = lane.polygon.map(p => p[1]);
                    const oldTop = Math.min(...ys);
                    const oldBottom = Math.max(...ys);

                    // Only update if actually different
                    if (oldTop === normalizedY && oldBottom === normalizedBottom) {
                        continue;
                    }

                    if (lane.polygon.length === 4) {
                        // A 4-point lane (the wand's, a tilted one, a Q-drawn one): its sides extended or cut as
                        // lines, so a tilted lane keeps its slope (spec 2026-10-10 §3); the box follows (Rule 1).
                        updateData.polygon = this._extendQuad(lane.polygon, normalizedY, normalizedBottom);
                        const xs = updateData.polygon.map(p => p[0]);
                        updateData.x = Math.min(...xs);
                        updateData.width = Math.max(...xs) - updateData.x;
                    } else {
                        // Remap polygon Y coords: top points -> normalizedY, bottom points -> normalizedBottom
                        const midY = (oldTop + oldBottom) / 2;
                        updateData.polygon = lane.polygon.map(p => {
                            const newY = p[1] < midY ? normalizedY : normalizedBottom;
                            return [p[0], newY];
                        });
                    }
                } else {
                    if (lane.y === normalizedY && lane.height === normalizedHeight) {
                        continue;
                    }
                }

                this._updateLane(lane.id, updateData, true);
                updatedCount++;
            }

            this._hideLoading();

            if (updatedCount > 0) {
                this._showMessage(`${updatedCount} lane${updatedCount !== 1 ? 's' : ''} normalized (y=${normalizedY}, h=${normalizedHeight}px)`);
            } else {
                this._showMessage('All lanes already have the same height');
            }
        }

        /**
         * A 4-point lane's sides extended or cut, as lines, to yTop / yBottom; corners found by geometry (a Q-drawn
         * lane's come in click order), clamped to the image, rounded; TL, TR, BR, BL
         * (services/lane_geometry/shape.py::extend_quad + order_corners).
         */
        _extendQuad(points, yTop, yBottom) {
            const G = GelAnalyzer.LaneGeometry;
            return G.clampRound(G.extendQuad(points, yTop, yBottom), this.options.imageWidth || Infinity, Infinity);
        }

        /** The lane under a point, by its outline (Rule 2: a RECTANGLE lane is hit by its box, whatever it stores). */
        _findLaneAtPoint(x, y) {
            const G = GelAnalyzer.LaneGeometry;
            for (const [id, lane] of this.stateManager.lanes) {
                if (G.pointInPolygon(x, y, G.outline(lane))) {
                    return id;
                }
            }
            return null;
        }

        _getBandAtPoint(x, y) {
            for (const [id, band] of this.stateManager.bands) {
                if (band.polygon && this._pointInPolygon(x, y, band.polygon)) {
                    return band;
                }
            }
            return null;
        }

        // =====================================================================
        // Context menu
        // =====================================================================

        /**
         * Open the context menu on what it was asked for (owner brief, 2026-10-13). A right-click or a long-press
         * (`point`) selects the band under it, else the lane, and opens that one's menu there; on bare gel it opens
         * nothing and the selection stays. Shift+F10 / the Menu key (`keyboard`) open the selection's menu over it,
         * the focus in the menu. Never while a shape is being drawn, nor on an analysis that cannot be edited.
         * @param {{x?: number, y?: number, point?: {x: number, y: number}, keyboard?: boolean}} request
         */
        _openContextMenu({ x, y, point, keyboard }) {
            if (!this.isEditable || this._isDrawing()) {
                this.contextMenu.hide();
                return;
            }
            if (keyboard) {
                if (!this.selectedType) return;
                const selected = this.selectedType === 'lane'
                    ? this.stateManager.getLane(this.selectedId)
                    : this.stateManager.getBand(this.selectedId);
                if (!selected) {
                    // A selection left behind by a reload that took its lane or band away: no menu for nothing.
                    this._deselect();
                    this._showMessage('Select a lane or band first');
                    return;
                }
                const anchor = this._contextMenuAnchor(this.selectedType, this.selectedId);
                this.contextMenu.show(anchor.x, anchor.y, this.selectedType, { keyboard: true });
                return;
            }
            const target = point ? this._annotationAtPoint(point.x, point.y) : null;
            if (!target) {
                this.contextMenu.hide();
                return;
            }
            if (target.type !== this.selectedType || target.id !== this.selectedId) {
                this._selectAnnotation(target.type, target.id);
            }
            this.contextMenu.show(x, y, target.type);
        }

        /** A shape under way: no context menu over it, and Esc cancels it first (isIdle). */
        _isDrawing() {
            const tool = this.toolManager?.getActiveTool();
            if (tool && (tool.isDrawing || tool.startPoint || tool.points?.length || tool.shapePoints?.length)) {
                return true;
            }
            return Boolean(this.drawingGroup && this.drawingGroup.children().length > 0);
        }

        /**
         * What a click at this image point lands on: a band (drawn as the renderer draws it: its polygon, else its
         * box; the last one in the list when two overlap, as they stack), else the lane by its outline (Rule 2,
         * _findLaneAtPoint), else null.
         * @returns {{type: 'band'|'lane', id: *}|null}
         */
        _annotationAtPoint(x, y) {
            let bandId = null;
            for (const [id, band] of this.stateManager.bands) {
                if (band.polygon && band.polygon.length >= 3) {
                    if (this._pointInPolygon(x, y, band.polygon)) bandId = id;
                } else if (band.bbox_x != null && band.bbox_y != null && band.bbox_width && band.bbox_height) {
                    if (x >= band.bbox_x && x <= band.bbox_x + band.bbox_width
                        && y >= band.bbox_y && y <= band.bbox_y + band.bbox_height) bandId = id;
                }
            }
            if (bandId !== null) return { type: 'band', id: bandId };
            const laneId = this._findLaneAtPoint(x, y);
            return laneId !== null ? { type: 'lane', id: laneId } : null;
        }

        /**
         * Where Shift+F10 / the Menu key open the menu: the middle of the part of the selected shape that is on
         * screen, inside the gel's view (zoomed in, panned) and the window (on a phone the page scrolls the gel away);
         * else the middle of what is left of the view, else of the window. Never off screen: the menu takes the keys.
         */
        _contextMenuAnchor(type, id) {
            const clip = (a, b) => ({
                left: Math.max(a.left, b.left),
                right: Math.min(a.right, b.right),
                top: Math.max(a.top, b.top),
                bottom: Math.min(a.bottom, b.bottom),
            });
            const empty = (r) => r.left > r.right || r.top > r.bottom;
            const screen = { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight };
            const view = clip((this.viewer || this.container).getBoundingClientRect(), screen);
            const shape = this.svg.findOne(`#${type}-${id}`);
            const part = shape ? clip(shape.node.getBoundingClientRect(), view) : null;
            const box = part && !empty(part) ? part : (!empty(view) ? view : screen);
            return { x: (box.left + box.right) / 2, y: (box.top + box.bottom) / 2 };
        }

        _pointInPolygon(x, y, polygon) {
            return GelAnalyzer.LaneGeometry.pointInPolygon(x, y, polygon);
        }

        _showMessage(text, duration = 2000) {
            const existing = document.querySelector('.gv-message');
            if (existing) existing.remove();

            const message = document.createElement('div');
            message.className = 'gv-message';
            message.textContent = text;

            // Append to viewer if available, otherwise to container
            const parent = this.viewer || this.container;
            if (parent) {
                parent.appendChild(message);
                setTimeout(() => message.remove(), duration);
            } else {
                console.log('GelViewer message:', text);
            }
        }

        _showLoading(text = 'Processing...') {
            const overlay = document.getElementById('loading-overlay');
            const textEl = overlay?.querySelector('.gv-loading-text');

            if (textEl) textEl.textContent = text;
            if (overlay) overlay.classList.add('visible');
        }

        _hideLoading() {
            const overlay = document.getElementById('loading-overlay');
            if (overlay) overlay.classList.remove('visible');
        }

        // =====================================================================
        // Public API
        // =====================================================================

        setTool(tool) {
            this.toolManager.setTool(tool);
        }

        setLaneShape(shape) {
            this.toolManager.setLaneShape(shape);
        }

        hasUnsavedChanges() {
            return this.stateManager.isDirty;
        }

        /**
         * True when Esc has nothing left to close, cancel or deselect: no selection, no drawing under way, no panel,
         * menu, dialog, overlay or toast open (each by the marker its own show / hide sets). The page's Esc leaves
         * the editor only then; it reads this in the capture phase, before the handlers that close things run.
         * @returns {boolean}
         */
        isIdle() {
            if (this.selectedType !== null) return false;
            if (this._isDrawing()) return false;

            const open = [
                this.dataTablePanel?.isVisible(),
                this.bandTablePanel?.isVisible(),
                this.adjustmentsPanel?.isVisible(),
                this.contextMenu?.isVisible(),
                this.detectionPanel?.isOpen(),
                this.cv2DetectionPanel?.isOpen(),
                this.calibrationPanel?.isOpen(),
                this.reviewPanel?.isOpen(),
                this.electropherogramPanel?.isVisible,
                this.bandModelPanel?.isVisible,
                this.teacherPanel?.isOpen,
                this.toasts?.hasOpen?.(),
            ];
            if (open.some(Boolean)) return false;

            // The confirm dialog (crash-backup restore included), the Remove-all and loading overlays, the lane-shape
            // menu: their own classes.
            return !document.querySelector(
                '#gv-confirm-modal.show, #action-modal.visible, #loading-overlay.visible, .gv-tool-dropdown.open'
            );
        }

        save() {
            return this._batchSave();
        }

        fitToView() {
            this.viewport.fitToView();
        }

        zoomIn() {
            this.viewport.zoom(1.2);
        }

        zoomOut() {
            this.viewport.zoom(0.8);
        }

        /**
         * Toggle annotation background fills visibility.
         */
        toggleBackgrounds() {
            this.backgroundsHidden = !this.backgroundsHidden;

            // Toggle CSS class on SVG overlay
            const svgOverlay = this.container.querySelector('.gv-svg-overlay');
            if (svgOverlay) {
                if (this.backgroundsHidden) {
                    svgOverlay.classList.add('backgrounds-hidden');
                } else {
                    svgOverlay.classList.remove('backgrounds-hidden');
                }
            }

            // Toggle button active state
            const toggleBtn = document.getElementById('toggle-backgrounds');
            if (toggleBtn) {
                if (this.backgroundsHidden) {
                    toggleBtn.classList.add('backgrounds-hidden-active');
                    toggleBtn.title = 'Show Annotation Fills (F)';
                } else {
                    toggleBtn.classList.remove('backgrounds-hidden-active');
                    toggleBtn.title = 'Hide Annotation Fills (F)';
                }
            }

            this._showMessage(this.backgroundsHidden ? 'Backgrounds hidden' : 'Backgrounds shown');
        }

        /**
         * Toggle MW calibration lines visibility.
         */
        async toggleMWLines() {
            this.showMWLines = !this.showMWLines;

            // Update button state
            const toggleBtn = document.getElementById('toggle-mw-lines');
            if (toggleBtn) {
                if (this.showMWLines) {
                    toggleBtn.classList.add('active');
                } else {
                    toggleBtn.classList.remove('active');
                }
            }

            if (this.showMWLines) {
                // Fetch calibration data if not cached
                if (!this.calibrationData) {
                    try {
                        this.calibrationData = await this.apiClient.getMultiCalibration();
                    } catch (error) {
                        console.error('Failed to fetch calibration data:', error);
                        this._showMessage('No calibration available');
                        this.showMWLines = false;
                        toggleBtn?.classList.remove('active');
                        return;
                    }
                }

                // Check if calibrated
                if (!this.calibrationData?.is_calibrated) {
                    this._showMessage('Run calibration first to show MW lines');
                    this.showMWLines = false;
                    toggleBtn?.classList.remove('active');
                    return;
                }

                // Render the lines
                this.renderer.renderCalibrationLines(this.calibrationData);
                this._showMessage('MW lines shown');
            } else {
                // Clear the lines
                this.calibrationLinesGroup.clear();
                this._showMessage('MW lines hidden');
            }
        }

        /**
         * Update calibration data and optionally show lines.
         * @param {Object} data - Calibration data from API
         * @param {boolean} showLines - Whether to show lines
         */
        updateCalibrationData(data, showLines = false) {
            this.calibrationData = data;
            if (showLines && data?.is_calibrated) {
                this.showMWLines = true;
                const toggleBtn = document.getElementById('toggle-mw-lines');
                toggleBtn?.classList.add('active');
                this.renderer.renderCalibrationLines(data);
            }
        }

        // =====================================================================
        // MobileSAM Polygon Refinement
        // =====================================================================

        /**
         * Initialize the SAM decoder engine (lazy).
         * @returns {Promise<void>}
         */
        async initSAMDecoder() {
            if (this.samDecoderEngine && this.samDecoderEngine.isInitialized) {
                return;
            }

            if (!SAMDecoderEngine) {
                console.warn('SAMDecoderEngine not available');
                return;
            }

            this._showLoading('Loading SAM model...');

            try {
                this.samDecoderEngine = new SAMDecoderEngine({
                    eventBus: this.eventBus,
                    analysisId: this.analysisId,
                    useQuantized: true,  // Use quantized model by default
                });

                await this.samDecoderEngine.initialize();
                console.log('SAM decoder initialized');

                this._hideLoading();

            } catch (error) {
                this._hideLoading();
                console.error('Failed to initialize SAM decoder:', error);
                throw error;
            }
        }

        /**
         * Refine a single band's polygon using MobileSAM.
         * @param {string} bandId - Band identifier
         * @returns {Promise<Array>} Refined polygon points
         */
        async refineBandPolygon(bandId) {
            // Initialize SAM if not already
            await this.initSAMDecoder();

            // Get band data
            const band = this.stateManager.getBand(bandId);
            if (!band) {
                throw new Error(`Band ${bandId} not found`);
            }

            // Get bounding box from band
            const bbox = this._getBandBBox(band);

            try {
                this._showLoading('Refining polygon...');

                // Run SAM refinement
                const polygon = await this.samDecoderEngine.refineBand(bandId, bbox);

                this._hideLoading();

                // Update band polygon
                if (polygon && polygon.length > 2) {
                    band.polygon = polygon;
                    this.stateManager.setBand(bandId, band);
                    this.stateManager.trackBandUpdate(bandId, { polygon });
                    this.renderer.renderBand(band);
                    this.eventBus.emit(Events.BAND_UPDATED, band);
                }

                return polygon;

            } catch (error) {
                this._hideLoading();
                console.error('Failed to refine band polygon:', error);
                throw error;
            }
        }

        /**
         * Refine polygons for multiple bands using MobileSAM.
         * @param {Array<string>} bandIds - Array of band IDs to refine
         * @returns {Promise<Object>} Results with success/failure counts
         */
        async refineBandPolygonsBatch(bandIds) {
            // Initialize SAM if not already
            await this.initSAMDecoder();

            // Prepare band data
            const bands = bandIds
                .map(id => {
                    const band = this.stateManager.getBand(id);
                    if (!band) return null;
                    return {
                        bandId: id,
                        bbox: this._getBandBBox(band),
                    };
                })
                .filter(b => b !== null);

            if (bands.length === 0) {
                return { success: 0, failed: 0 };
            }

            try {
                this._showLoading(`Refining ${bands.length} bands...`);

                // Run batch refinement
                const results = await this.samDecoderEngine.refineBandsBatch(bands);

                this._hideLoading();

                // Update bands with refined polygons
                let success = 0;
                let failed = 0;

                for (const result of results) {
                    if (result.success && result.polygon && result.polygon.length > 2) {
                        const band = this.stateManager.getBand(result.bandId);
                        if (band) {
                            band.polygon = result.polygon;
                            this.stateManager.setBand(result.bandId, band);
                            this.stateManager.trackBandUpdate(result.bandId, { polygon: result.polygon });
                            this.renderer.renderBand(band);
                            success++;
                        }
                    } else {
                        failed++;
                    }
                }

                this._showMessage(`Refined ${success} band${success !== 1 ? 's' : ''}`);

                return { success, failed, results };

            } catch (error) {
                this._hideLoading();
                console.error('Failed to refine band polygons:', error);
                throw error;
            }
        }

        // =====================================================================
        // Image Crop
        // =====================================================================

        /**
         * Handle crop request from CropTool.
         * Shows confirmation dialog, then calls backend crop API.
         */
        async _handleCropRequested(cropData) {
            const confirmed = await this.confirmationManager.confirmCrop(
                cropData.width, cropData.height
            );

            // Cancel crop drawing regardless of confirmation
            const cropTool = this.toolManager.getToolInstance('crop');
            if (cropTool) cropTool.cancel();

            if (!confirmed) {
                this.toolManager.setTool('select');
                return;
            }

            try {
                // Auto-save pending deletions before cropping so the backend
                // sees the current state (e.g. all lanes/bands removed).
                if (this.stateManager.isDirty) {
                    this._showLoading('Saving changes before crop...');
                    await this._batchSave();
                }

                this._showLoading('Cropping image...');
                await this.apiClient.cropImage(cropData);
                // Reload with cache-bust to bypass proxy max-age caching
                window.location.href = window.location.pathname + '?_=' + Date.now();
            } catch (error) {
                this._hideLoading();
                console.warn('Crop rejected:', error.message);
                const msg = 'Failed to crop image: ' + error.message;
                if (this.toasts) this.toasts.error(msg); else this._showMessage(msg);
                this.toolManager.setTool('select');
            }
        }

        // =====================================================================
        // Toolbar State Management
        // =====================================================================

        /**
         * Update toolbar button states based on current data.
         * Enables/disables buttons based on prerequisites.
         */
        _updateToolbarState() {
            // Gather state - getAllLanes() returns a Map, convert to array
            const lanesMap = this.stateManager.getAllLanes();
            const lanes = Array.from(lanesMap.values());
            const laneCount = lanes.length;
            const ladderLanes = lanes.filter(l => l.lane_type === 'LADDER');
            const ladderLaneCount = ladderLanes.length;

            // Count bands
            let totalBands = 0;
            let ladderBandsCount = 0;
            let nonLadderBandsCount = 0;
            lanes.forEach(lane => {
                const bandCount = lane.bands?.length || 0;
                totalBands += bandCount;
                if (lane.lane_type === 'LADDER') {
                    ladderBandsCount += bandCount;
                } else {
                    nonLadderBandsCount += bandCount;
                }
            });

            // Check calibration state
            const isCalibrated = this.calibrationData?.is_calibrated || false;

            // Selection state
            const hasSelection = this.selectedType !== null;
            const hasSelectedBand = this.selectedType === 'band';

            // Button state rules
            const buttonRules = {
                // Crop: disabled when lanes exist (coordinates would be invalidated)
                'btn-crop': {
                    enabled: laneCount === 0,
                    disabledTooltip: 'Remove all lanes before cropping'
                },
                // Band Detection (Auto): requires lanes
                'toggle-detection': {
                    enabled: laneCount > 0,
                    disabledTooltip: 'Create lanes first to detect bands'
                },
                // CV2 Vision Detection: requires lanes
                'toggle-cv2-detection': {
                    enabled: laneCount > 0,
                    disabledTooltip: 'Create lanes first to detect bands'
                },
                // Band model: requires lanes (the bands go to the saved lanes)
                'toggle-band-model': {
                    enabled: laneCount > 0,
                    disabledTooltip: 'Create lanes first to detect bands'
                },
                // Electropherogram: requires lanes
                'toggle-electropherogram': {
                    enabled: laneCount > 0,
                    disabledTooltip: 'Create lanes first'
                },
                // Calibration: requires ladder lanes with bands
                'toggle-calibration': {
                    enabled: ladderLaneCount > 0 && ladderBandsCount > 0,
                    disabledTooltip: ladderLaneCount === 0
                        ? 'Add Ladder lanes first'
                        : 'Add bands to Ladder lanes first'
                },
                // MW Lines: requires calibration
                'toggle-mw-lines': {
                    enabled: isCalibrated,
                    disabledTooltip: 'Calibrate MW first'
                },
                // Band tool: requires lanes
                '[data-tool="band"]': {
                    enabled: laneCount > 0,
                    disabledTooltip: 'Create a lane first'
                },
                // Split tool: a band to split (the tool finds the band under the click; only the S key needs a
                // band selected first)
                '[data-tool="split"]': {
                    enabled: totalBands > 0,
                    disabledTooltip: 'No band to split'
                },
                // Delete button: requires selection
                '#delete-selected': {
                    enabled: hasSelection,
                    disabledTooltip: 'Select an annotation first'
                },
                // Remove all lanes: requires lanes
                'remove-all-lanes': {
                    enabled: laneCount > 0,
                    disabledTooltip: 'No lanes to remove'
                },
                // Remove all bands: requires bands
                'remove-all-bands': {
                    enabled: totalBands > 0,
                    disabledTooltip: 'No bands to remove'
                }
            };

            // Apply states to buttons
            Object.entries(buttonRules).forEach(([buttonId, rule]) => {
                this._setButtonState(buttonId, rule.enabled, rule.disabledTooltip);
            });

            // Densitometry, in the header's views (workbench/_identity.html): greyed while the gel has no band.
            // The page refuses a click on it greyed, with its title as the reason.
            const densitometry = document.getElementById('ga-wb-view-densitometry');
            if (densitometry) {
                const off = totalBands === 0;
                densitometry.classList.toggle('is-off', off);
                if (off) {
                    densitometry.setAttribute('aria-disabled', 'true');
                    densitometry.removeAttribute('href');
                } else {
                    densitometry.removeAttribute('aria-disabled');
                    densitometry.setAttribute('href', densitometry.dataset.href);
                }
                densitometry.title = off ? densitometry.dataset.titleOff : densitometry.dataset.titleOn;
            }

            this._refreshStatus();
        }

        /**
         * The editor's live status: "N unsaved changes" beside Save (StateManager.pendingCount, hidden at 0), Save's
         * look, the status bar's lane and band counts. On every move of the pending changes (PENDING_CHANGED) and
         * from _updateToolbarState (annotations loaded or reloaded, selection, lanes or bands added or removed).
         */
        _refreshStatus() {
            const count = this.stateManager.pendingCount();
            const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

            const indicator = document.getElementById('unsaved-indicator');
            if (indicator) {
                indicator.hidden = count === 0;
                const label = indicator.querySelector('span');
                if (label) label.textContent = plural(count, 'unsaved change');
            }
            document.getElementById('save-btn')?.classList.toggle('has-changes', count > 0);

            const lanes = document.getElementById('lane-count');
            if (lanes) lanes.textContent = plural(this.stateManager.getLaneCount(), 'lane');
            const bands = document.getElementById('band-count');
            if (bands) bands.textContent = plural(this.stateManager.getBandCount(), 'band');
        }

        /**
         * Set a toolbar button's enabled/disabled state. Its tooltip (data-tooltip) says why it is disabled, and
         * comes back to the template's text (kept once in data-tooltip-default) when it is enabled again.
         * @param {string} target - The button's id, else a selector ('[data-tool="band"]')
         * @param {boolean} enabled - Whether button should be enabled
         * @param {string} disabledTooltip - Tooltip to show when disabled
         */
        _setButtonState(target, enabled, disabledTooltip) {
            const button = document.getElementById(target) || document.querySelector(target);
            if (!button) return;

            if (button.dataset.tooltipDefault === undefined) {
                button.dataset.tooltipDefault = button.dataset.tooltip || '';
            }

            if (enabled) {
                button.disabled = false;
                button.classList.remove('gv-toolbar-btn-disabled');
                button.dataset.tooltip = button.dataset.tooltipDefault;
            } else {
                button.disabled = true;
                button.classList.add('gv-toolbar-btn-disabled');
                button.dataset.tooltip = disabledTooltip || 'Action not available';
            }
        }

        /**
         * Get bounding box for a band.
         * @param {Object} band - Band object
         * @returns {Array<number>} [x, y, width, height]
         */
        _getBandBBox(band) {
            if (band.polygon && band.polygon.length >= 3) {
                // Calculate bbox from polygon
                const xs = band.polygon.map(p => p[0]);
                const ys = band.polygon.map(p => p[1]);
                const minX = Math.min(...xs);
                const minY = Math.min(...ys);
                const maxX = Math.max(...xs);
                const maxY = Math.max(...ys);
                return [minX, minY, maxX - minX, maxY - minY];
            }

            // Use stored bbox
            return [
                band.bbox_x || band.x || 0,
                band.bbox_y || band.y || 0,
                band.bbox_width || band.width || 50,
                band.bbox_height || band.height || 20,
            ];
        }

        /**
         * Check if SAM decoder is available and ready.
         * @returns {boolean}
         */
        isSAMReady() {
            return this.samDecoderEngine && this.samDecoderEngine.isReady();
        }
    }

    // Export to global
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.App = GelViewerApp;

    // Also export as GelViewer for backward compatibility
    global.GelViewerApp = GelViewerApp;

})(window);
