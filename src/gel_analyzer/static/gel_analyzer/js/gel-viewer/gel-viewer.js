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
    const HybridDetectionPanel = global.GelViewer.HybridDetectionPanel;
    const CrossLaneConsensusPanel = global.GelViewer.CrossLaneConsensusPanel;
    const CalibrationPanel = global.GelViewer.CalibrationPanel;
    // UNPLUGGED: Profile Peak Detection deprecated in favour of Auto (d1/d2) detection
    const ProfileDetectionPanel = null; // was: global.GelViewer.ProfileDetectionPanel;
    // Electropherogram Panel (D3.js)
    const ElectropherogramPanel = global.GelViewer.ElectropherogramPanel;
    // Phase 3: MobileSAM Polygon Refinement
    const SAMDecoderEngine = global.GelViewer.SAMDecoderEngine;
    // Confirmation dialogs
    const ConfirmationManager = global.GelViewer.ConfirmationManager;

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
            // Cross-Lane Consensus Panel
            this.crossLanePanel = null;
            // Profile Peak Detection
            this.profileDetectionPanel = null;
            // Electropherogram Panel
            this.electropherogramPanel = null;
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
                onToggleProfileDetectionPanel: () => this.profileDetectionPanel?.toggle(),
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
                getSelectedAnnotation: () => this.selectedType ? { type: this.selectedType, id: this.selectedId } : null
            });

            // UI Panels
            this.propertiesPanel = new PropertiesPanel({
                eventBus: this.eventBus,
                stateManager: this.stateManager,
                apiClient: this.apiClient,
                onDeleteLane: (id) => this._deleteLane(id),
                onDeleteBand: (id) => this._deleteBand(id),
                onUpdateLane: (id, data) => this._updateLane(id, data),
                onUpdateBand: (id, data) => this._updateBand(id, data),
                onSelectBand: (bandId) => this._selectAnnotation('band', bandId)
            });

            this.dataTablePanel = new DataTablePanel({
                eventBus: this.eventBus,
                stateManager: this.stateManager,
                apiClient: this.apiClient,
                onSelectAnnotation: (type, id) => this._selectAnnotation(type, id),
                onUpdateLane: (id, data, silent) => this._updateLane(id, data, silent)
            });

            this.bandTablePanel = new BandTablePanel({
                eventBus: this.eventBus,
                stateManager: this.stateManager,
                onSelectBand: (bandId) => this._selectAnnotation('band', bandId),
                onUpdateBand: (id, data) => this._updateBand(id, data),
                onDeleteBand: (id) => this._deleteBand(id)
            });

            this.adjustmentsPanel = new AdjustmentsPanel({
                eventBus: this.eventBus,
                imageElement: this.container.querySelector('.gv-image'),
                imageProxyUrl: this.options.imageProxyUrl
            });

            this.contextMenu = new ContextMenu({
                eventBus: this.eventBus,
                stateManager: this.stateManager,
                svg: this.svg,
                handlesGroup: this.handlesGroup,
                isEditable: this.isEditable,
                showMessage: (msg) => this._showMessage(msg),
                onDeleteLane: (id) => this._deleteLane(id),
                onDeleteBand: (id) => this._deleteBand(id),
                onUpdateLane: (id, data) => this._updateLane(id, data),
                onUpdateBand: (id, data) => this._updateBand(id, data),
                onStartResize: (id) => this._startLaneResize(id),
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
                    svg: this.svg,
                    onDetectionComplete: () => this._onDetectionComplete(),
                    electropherogramPanel: this.electropherogramPanel,
                });
            }

            if (CV2DetectionPanel) {
                this.cv2DetectionPanel = new CV2DetectionPanel({
                    eventBus: this.eventBus,
                    apiClient: this.apiClient,
                    stateManager: this.stateManager,
                    svg: this.svg,
                    onDetectionComplete: () => this._onDetectionComplete(),
                    electropherogramPanel: this.electropherogramPanel,
                });
            }

            if (HybridDetectionPanel) {
                this.hybridDetectionPanel = new HybridDetectionPanel({
                    eventBus: this.eventBus,
                    apiClient: this.apiClient,
                    stateManager: this.stateManager,
                    svg: this.svg,
                    onDetectionComplete: () => this._onDetectionComplete(),
                });
            }

            if (CrossLaneConsensusPanel) {
                this.crossLanePanel = new CrossLaneConsensusPanel({
                    eventBus: this.eventBus,
                    apiClient: this.apiClient,
                    stateManager: this.stateManager,
                    svg: this.svg,
                    analysisId: this.analysisId,
                    viewerContainer: this.canvasContainer,
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

            // Profile Peak Detection panel
            if (ProfileDetectionPanel) {
                this.profileDetectionPanel = new ProfileDetectionPanel({
                    eventBus: this.eventBus,
                    apiClient: this.apiClient,
                    stateManager: this.stateManager,
                    svg: this.svg,
                    analysisId: this.analysisId,
                    onDetectionComplete: (bandsCreated) => this._onProfileDetectionComplete(bandsCreated),
                    electropherogramPanel: this.electropherogramPanel,
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

            // Context menu requested
            this.eventBus.on(Events.CONTEXT_MENU_REQUESTED, (data) => {
                if (this.selectedType && this.isEditable) {
                    this.contextMenu.show(data.x, data.y, this.selectedType, this.selectedId);
                }
            });

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
                    console.error('Failed to update calibration data:', error);
                }
            });

            // ── Detection panel mutual exclusivity ──────────────────────────────────
            // Only one of the detection / cross-lane panels may be open at a time.
            // Centralized here so individual panels stay dumb about each other.
            const hideOtherDetectionPanels = (openedPanel) => {
                [
                    this.detectionPanel,
                    this.cv2DetectionPanel,
                    this.hybridDetectionPanel,
                    this.profileDetectionPanel,
                    this.crossLanePanel,
                ].forEach(p => {
                    if (p && p !== openedPanel && p.isVisible) p.hide();
                });
            };
            this.eventBus.on(Events.DETECTION_PANEL_SHOWN,         () => hideOtherDetectionPanels(this.detectionPanel));
            this.eventBus.on(Events.CV2_DETECTION_PANEL_SHOWN,     () => hideOtherDetectionPanels(this.cv2DetectionPanel));
            this.eventBus.on(Events.HYBRID_DETECTION_PANEL_SHOWN,  () => hideOtherDetectionPanels(this.hybridDetectionPanel));
            this.eventBus.on(Events.PROFILE_DETECTION_PANEL_SHOWN, () => hideOtherDetectionPanels(this.profileDetectionPanel));
            this.eventBus.on(Events.CROSS_LANE_PANEL_SHOWN,        () => hideOtherDetectionPanels(this.crossLanePanel));

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

            // Hybrid Detection panel toggle
            const hybridDetectionToggle = document.getElementById('toggle-hybrid-detection');
            if (hybridDetectionToggle) {
                hybridDetectionToggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.hybridDetectionPanel?.toggle();
                });
            }

            // Cross-Lane Consensus panel toggle
            const crossLaneToggle = document.getElementById('toggle-cross-lane-consensus');
            if (crossLaneToggle) {
                crossLaneToggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.crossLanePanel?.toggle();
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

            // Profile Peak Detection panel toggle
            const profileDetectionToggle = document.getElementById('toggle-profile-detection');
            if (profileDetectionToggle) {
                profileDetectionToggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.profileDetectionPanel?.toggle();
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

            // Table panel apply button - just close (changes are already applied locally)
            const tableApply = document.getElementById('apply-table-changes');
            if (tableApply) {
                tableApply.addEventListener('click', () => {
                    this.dataTablePanel?.hide();
                    this._showMessage('Changes applied locally');
                });
            }

            // Window resize
            let resizeTimeout;
            window.addEventListener('resize', () => {
                clearTimeout(resizeTimeout);
                resizeTimeout = setTimeout(() => this.viewport.fitToView(), 150);
            });

            // Warn before leaving with unsaved changes
            window.addEventListener('beforeunload', (e) => {
                if (this.stateManager.isDirty) {
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
            try {
                this._showLoading('Loading annotations...');
                const data = await this.apiClient.loadAnnotations();

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

                this.renderer.updateAnnotationsList();
                this.eventBus.emit(Events.ANNOTATIONS_LOADED, data);

                // Load calibration data if available (enables MW lines and auto MW calculation)
                this._loadCalibrationData();

                // Try to recover from localStorage
                this.stateManager.loadFromLocalStorage();
                this._applyRecoveredChanges();

            } catch (error) {
                console.error('Failed to load annotations:', error);
                this._showMessage('Failed to load annotations');
            } finally {
                this._hideLoading();
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
         * Apply changes recovered from localStorage.
         */
        _applyRecoveredChanges() {
            const pending = this.stateManager.pendingChanges;

            // Hide deleted lanes
            for (const laneId of pending.lanes.deleted) {
                this.renderer.removeLane(laneId);
                this.stateManager.deleteLane(laneId);
            }

            // Hide deleted bands
            for (const bandId of pending.bands.deleted) {
                this.renderer.removeBand(bandId);
                this.stateManager.deleteBand(bandId);
            }

            // Render created lanes
            for (const [id, laneData] of pending.lanes.created) {
                this.stateManager.setLane(id, laneData);
                this.renderer.renderLane(laneData);
            }

            // Render created bands
            for (const [id, bandData] of pending.bands.created) {
                this.stateManager.setBand(id, bandData);
                this.renderer.renderBand(bandData);
            }

            // Recalculate and update
            this._recalculateLaneNumbers();
            this.renderer.updateAnnotationsList();

            if (this.stateManager.isDirty) {
                this._showMessage('Previous session restored. Remember to save your changes.');
            }
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
        }

        _deselect() {
            console.log('_deselect called');
            this.selectedType = null;
            this.selectedId = null;

            // Update StateManager (this emits SELECTION_CLEARED)
            this.stateManager.clearSelection();

            this.renderer.clearSelection();
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
            this.renderer.updateAnnotationsList();
            this.stateManager.markDirty();

            this._selectAnnotation('lane', tempId);
            this._showMessage('Lane created (unsaved)');

            // Switch back to select tool after creating
            this.toolManager.setTool('select');
        }

        _updateLane(id, data, silent = false) {
            const lane = this.stateManager.getLane(id);
            if (!lane) return;

            Object.assign(lane, data);

            // Update type display if changed
            if (data.lane_type) {
                lane.lane_type_display = StateManager.getLaneTypeDisplay(data.lane_type);

                // Update SVG class
                const element = this.svg.findOne(`#lane-${id}`);
                if (element) {
                    element.removeClass('sample').removeClass('ladder')
                           .removeClass('control').removeClass('empty');
                    element.addClass(data.lane_type.toLowerCase());
                }
            }

            // Update SVG visuals if geometry changed
            if ('x' in data || 'y' in data || 'width' in data || 'height' in data || 'polygon' in data) {
                this.renderer.updateLane(lane);
                if ('x' in data) {
                    this._recalculateLaneNumbers();
                }
            }

            this.stateManager.trackLaneUpdate(id, data);
            this.stateManager.markDirty();

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

            const scale = this.viewport.getScale();
            this.contextMenu.showResizeHandles(
                lane, this.svg, this.handlesGroup, scale,
                (laneId, dims) => {
                    this._updateLane(laneId, dims);
                    this.renderer.updateAnnotationsList();
                }
            );
        }

        async _deleteLane(id) {
            const lane = this.stateManager.getLane(id);
            if (!lane) return;

            // Show confirmation dialog
            const bandCount = lane.bands?.length || 0;
            if (this.confirmationManager) {
                const confirmed = await this.confirmationManager.confirmDeleteLane(lane.lane_number, bandCount);
                if (!confirmed) return;
            }

            // Delete associated bands
            if (lane.bands) {
                lane.bands.forEach(band => {
                    this.stateManager.trackBandDeletion(band.id);
                    this.renderer.removeBand(band.id);
                    this.stateManager.deleteBand(band.id);
                });
            }

            this.stateManager.trackLaneDeletion(id);
            this.renderer.removeLane(id);
            this.stateManager.deleteLane(id);

            this._recalculateLaneNumbers();
            this.renderer.updateAnnotationsList();
            this.stateManager.markDirty();

            if (this.selectedId === id) {
                this._deselect();
            }

            this._showMessage('Lane deleted (unsaved)');
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
            this.renderer.updateAnnotationsList();
            this.stateManager.markDirty();

            this._selectAnnotation('band', tempId);
            this._showMessage('Band created');

            // Switch back to select tool after creating
            this.toolManager.setTool('select');

            // Async server call (fire-and-forget, like delete)
            // Resolve lane ID (could be temp ID if lane was just created)
            const realLaneId = lane?._isNew ? lane.id : laneId;
            if (!String(realLaneId).startsWith('temp_')) {
                this.apiClient.createBand(realLaneId, {
                    polygon: data.polygon,
                    position_y: data.position_y,
                    band_type: band.band_type,
                    estimated_mw_kda: band.estimated_mw_kda,
                    mw_estimation_method: band.mw_estimation_method,
                }).then(result => {
                    // Replace temp ID with real server ID
                    const oldId = tempId;
                    band.id = result.id;
                    band._isNew = false;
                    band._isSaving = false;  // Clear saving state

                    // Update state manager
                    this.stateManager.replaceBandId(oldId, result.id);

                    // Update SVG element ID
                    const element = this.svg.findOne(`#band-${oldId}`);
                    if (element) element.attr('id', `band-${result.id}`);

                    // Remove from pending creates (no longer needs batch save)
                    this.stateManager.pendingChanges.bands.created.delete(oldId);

                    // Check if still dirty (other pending changes)
                    if (!this.stateManager.hasPendingChanges()) {
                        this.stateManager.markClean();
                    }

                    // Update selection if this band was selected
                    if (this.selectedId === oldId) {
                        this.selectedId = result.id;
                    }

                    // Update annotations list to reflect new ID
                    this.renderer.updateAnnotationsList();

                    // Emit event so UI can re-enable type selector
                    this.eventBus.emit(Events.BAND_SAVE_COMPLETE, {
                        id: result.id,
                        tempId: oldId,
                    });
                }).catch(error => {
                    console.error('Failed to create band on server:', error);
                    // Clear saving state even on error - allow user to retry
                    band._isSaving = false;
                    // Emit event so UI can re-enable type selector
                    this.eventBus.emit(Events.BAND_SAVE_FAILED, {
                        id: tempId,
                        error: error.message || 'Save failed',
                    });
                    // Band stays local with temp ID, will be created on Save
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

        _updateBand(id, data) {
            const band = this.stateManager.getBand(id);
            if (!band) return;

            Object.assign(band, data);

            // Update SVG class if band_type changed
            if (data.band_type) {
                const element = this.svg.findOne(`#band-${id}`);
                if (element) {
                    // Remove all type classes
                    element.removeClass('other').removeClass('mw_reference').removeClass('poi');
                    // Add new type class
                    element.addClass(data.band_type.toLowerCase());
                }
            }

            this.stateManager.trackBandUpdate(id, data);

            // Async server call for persisted bands (fire-and-forget, like delete)
            const isTempBand = String(id).startsWith('temp_');
            if (!isTempBand) {
                this.apiClient.updateBand(id, data).then(() => {
                    // Remove from pending updates since already saved
                    this.stateManager.pendingChanges.bands.updated.delete(id);
                    // Check if still dirty (other pending changes)
                    if (!this.stateManager.hasPendingChanges()) {
                        this.stateManager.markClean();
                    }
                }).catch(error => {
                    console.error('Failed to update band on server:', error);
                    // Band stays in pending updates, will sync on Save
                    this.stateManager.markDirty();
                });
                this._showMessage('Band updated');
            } else {
                this.stateManager.markDirty();
                this._showMessage('Band updated (unsaved)');
            }
        }

        _deleteBand(id) {
            const band = this.stateManager.getBand(id);
            if (!band) return;

            const isTempBand = String(id).startsWith('temp_');

            // Remove from parent lane
            const laneId = band._parentLaneId || band.lane_id;
            const lane = this.stateManager.getLane(laneId);
            if (lane && lane.bands) {
                lane.bands = lane.bands.filter(b => b.id !== id);
            }

            // Update UI immediately (optimistic)
            this.renderer.removeBand(id);
            this.stateManager.deleteBand(id);
            this.renderer.updateAnnotationsList();

            if (this.selectedId === id) {
                this._deselect();
            }

            this._showMessage('Band deleted');

            // Delete on server in background (non-blocking)
            if (!isTempBand) {
                this.apiClient.deleteBand(id).catch(error => {
                    console.error('Failed to delete band on server:', error);
                    // Band already removed from UI - just log the error
                    // Could implement restore logic here if needed
                });
            } else {
                // For temp bands, track for cleanup
                this.stateManager.trackBandDeletion(id);
                this.stateManager.markDirty();
            }
        }

        async _splitBand(bandId, splitY) {
            const band = this.stateManager.getBand(bandId);
            if (!band) {
                this._showMessage('Band not found');
                return;
            }

            // Reject splits on bands that haven't been persisted yet — the
            // server roundtrip we use below would have nothing to delete and
            // the resulting state would diverge from the DB.
            if (String(bandId).startsWith('temp_')) {
                this._showMessage('Save the analysis before splitting new bands');
                return;
            }

            // Get the band's polygon points
            const polygon = band.polygon;
            if (!polygon || polygon.length < 3) {
                this._showMessage('Cannot split: invalid band polygon');
                return;
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
                this._showMessage('Cannot split at this position');
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
                this._showMessage('Cannot split: resulting shapes invalid');
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
                this._showMessage('Cannot split: unknown parent lane');
                return;
            }

            // Build the two band payloads up-front so we don't half-commit if
            // serialization throws.
            const upperBandData = {
                polygon: sortedUpper,
                position_y: Math.round(upperBbox.y + upperBbox.height / 2),
                bbox_x: Math.round(upperBbox.x),
                bbox_y: Math.round(upperBbox.y),
                bbox_width: Math.round(upperBbox.width),
                bbox_height: Math.round(upperBbox.height),
                band_type: band.band_type || 'OTHER',
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
                band_type: band.band_type || 'OTHER',
                label: band.label ? `${band.label} (lower)` : '',
                notes: band.notes || ''
            };

            // Drive all three calls through awaited apiClient calls (NOT the
            // optimistic-fire-and-forget _deleteBand/_createBand helpers). Their
            // background DELETE only console.errors on failure, which is what
            // led to "split creates new bands but old one stays" bugs visible
            // after a reload. We then DATA_RELOAD_REQUESTED so the renderer,
            // electropherogram, calibration panel, band table, etc. all rebuild
            // from canonical server state in one shot.
            this._showMessage('Splitting band…');
            try {
                await this.apiClient.deleteBand(bandId);
                await this.apiClient.createBand(parentLaneId, upperBandData);
                await this.apiClient.createBand(parentLaneId, lowerBandData);

                this.eventBus.emit(Events.DATA_RELOAD_REQUESTED);
                this._showMessage('Band split into two');
            } catch (error) {
                console.error('[GelViewer] Split failed:', error);
                this._showMessage(`Split failed: ${error.message || error}`);
                // Server may be in a half-state (delete OK, one create failed).
                // Reload to surface ground truth rather than leave stale UI.
                this.eventBus.emit(Events.DATA_RELOAD_REQUESTED);
            }

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
                    this.renderer.clearAll();
                } catch (error) {
                    console.error('Failed to clear existing lanes:', error);
                    this._hideLoading();
                    this._showMessage('Failed to clear existing lanes');
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
                        imageHeight: this.options.imageHeight
                    });

                    await this.inferenceEngine.initialize();
                }

                // Lazy initialization of ReviewPanel
                if (!this.reviewPanel) {
                    this.reviewPanel = new ReviewPanel({
                        eventBus: this.eventBus,
                        stateManager: this.stateManager,
                        renderer: this.renderer,
                        svg: this.svg,
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

                    // Show review panel
                    console.log('Auto-detect: Showing review panel...');
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

                    this._showMessage(`${detections.length} lanes detected - review and accept`);
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
                lane_shape: det.polygon ? 'POLYGON' : 'RECTANGLE',
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

                // Auto-normalize lane heights after detection
                this._normalizeLaneHeights();

                // Update annotations list
                this.renderer.updateAnnotationsList();

                this._showMessage(`${result.count} lanes created from detection (heights normalized)`);

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

            try {
                this._showLoading('Saving...');

                const pending = this.stateManager.pendingChanges;
                const idMapping = { lanes: {}, bands: {} };

                // Save created lanes
                for (const [tempId, data] of pending.lanes.created) {
                    const result = await this.apiClient.createLane(data);
                    idMapping.lanes[tempId] = result.id;

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
                }

                // Bulk update lanes
                if (pending.lanes.updated.size > 0) {
                    const lanesToUpdate = Array.from(pending.lanes.updated.entries())
                        .map(([id, data]) => ({ id, ...data }));
                    if (lanesToUpdate.length > 0) {
                        await this.apiClient.updateLanesBulk(lanesToUpdate);
                    }
                }

                // Bulk delete lanes
                const laneIdsToDelete = Array.from(pending.lanes.deleted)
                    .filter(id => !String(id).startsWith('temp_'));
                if (laneIdsToDelete.length > 0) {
                    await this.apiClient.deleteLanesBulk(laneIdsToDelete);
                }

                // Save created bands
                for (const [tempId, data] of pending.bands.created) {
                    const parentLaneId = data._parentLaneId;
                    const realLaneId = idMapping.lanes[parentLaneId] || parentLaneId;

                    const result = await this.apiClient.createBand(realLaneId, data);
                    idMapping.bands[tempId] = result.id;

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
                }

                // Save updated bands
                for (const [id, data] of pending.bands.updated) {
                    await this.apiClient.updateBand(id, data);
                }

                // Delete bands
                for (const id of pending.bands.deleted) {
                    if (!String(id).startsWith('temp_')) {
                        await this.apiClient.deleteBand(id);
                    }
                }

                // Mark clean
                this.stateManager.markClean();
                this.renderer.updateAnnotationsList();

                this._showMessage('All changes saved successfully');
                this.eventBus.emit(Events.SAVE_COMPLETED);

            } catch (error) {
                console.error('Save failed:', error);
                this._showMessage('Save failed: ' + error.message);
            } finally {
                this._hideLoading();
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
         * Handle profile peak detection complete callback.
         * @param {number} bandsCreated - Number of bands created
         */
        _onProfileDetectionComplete(bandsCreated) {
            console.log('GelViewer: _onProfileDetectionComplete called, bands created:', bandsCreated);
            this._showMessage(`Profile detection completed: ${bandsCreated} band${bandsCreated !== 1 ? 's' : ''} created`);
        }

        /**
         * Reload annotations from server.
         * Used after band detection or calibration to refresh display.
         */
        async _reloadAnnotations() {
            console.log('GelViewer: _reloadAnnotations called');
            try {
                const data = await this.apiClient.loadAnnotations();
                console.log('GelViewer: loaded data', { laneCount: data.lanes?.length, totalBands: data.lanes?.reduce((sum, l) => sum + (l.bands?.length || 0), 0) });

                // Clear existing state
                this.stateManager.lanes.clear();
                this.stateManager.bands.clear();

                // Clear SVG layers
                this.lanesGroup.clear();
                this.bandsGroup.clear();
                this.handlesGroup.clear();

                // Re-render from fresh data
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

                this.renderer.updateAnnotationsList();
                this.eventBus.emit(Events.DATA_LOADED, data);
                // Also emit ANNOTATIONS_LOADED so toolbar state updates
                this.eventBus.emit(Events.ANNOTATIONS_LOADED, data);

            } catch (error) {
                console.error('Failed to reload annotations:', error);
                this._showMessage('Failed to reload data');
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

            for (const lane of lanes) {
                if (lane.polygon && lane.polygon.length >= 3) {
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

                // Update polygon points if the lane has one
                if (lane.polygon && lane.polygon.length >= 3) {
                    const ys = lane.polygon.map(p => p[1]);
                    const oldTop = Math.min(...ys);
                    const oldBottom = Math.max(...ys);

                    // Only update if actually different
                    if (oldTop === normalizedY && oldBottom === normalizedBottom) {
                        continue;
                    }

                    // Remap polygon Y coords: top points -> normalizedY, bottom points -> normalizedBottom
                    const midY = (oldTop + oldBottom) / 2;
                    updateData.polygon = lane.polygon.map(p => {
                        const newY = p[1] < midY ? normalizedY : normalizedBottom;
                        return [p[0], newY];
                    });
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
                this.renderer.updateAnnotationsList();
                this._showMessage(`${updatedCount} lane${updatedCount !== 1 ? 's' : ''} normalized (y=${normalizedY}, h=${normalizedHeight}px)`);
            } else {
                this._showMessage('All lanes already have the same height');
            }
        }

        _findLaneAtPoint(x, y) {
            for (const [id, lane] of this.stateManager.lanes) {
                if (lane.polygon && lane.polygon.length >= 3) {
                    if (this._pointInPolygon(x, y, lane.polygon)) {
                        return id;
                    }
                } else {
                    if (x >= lane.x && x <= lane.x + lane.width &&
                        y >= lane.y && y <= lane.y + lane.height) {
                        return id;
                    }
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

        _pointInPolygon(x, y, polygon) {
            let inside = false;
            for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
                const xi = polygon[i][0], yi = polygon[i][1];
                const xj = polygon[j][0], yj = polygon[j][1];

                if (((yi > y) !== (yj > y)) &&
                    (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) {
                    inside = !inside;
                }
            }
            return inside;
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
                if (window.gaToast) gaToast(msg, 'danger'); else alert(msg);
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
                // Hybrid Detection: requires lanes
                'toggle-hybrid-detection': {
                    enabled: laneCount > 0,
                    disabledTooltip: 'Create lanes first to detect bands'
                },
                // Cross-Lane Consensus: requires lanes (post-processes existing bands)
                'toggle-cross-lane-consensus': {
                    enabled: laneCount > 0,
                    disabledTooltip: 'Create lanes first'
                },
                // Profile Peak Detection: requires lanes
                'toggle-profile-detection': {
                    enabled: laneCount > 0,
                    disabledTooltip: 'Create lanes first to detect peaks'
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
                'tool-band': {
                    enabled: laneCount > 0,
                    disabledTooltip: 'Create a lane first'
                },
                // Split tool: requires selected band
                'tool-split': {
                    enabled: hasSelectedBand,
                    disabledTooltip: 'Select a band first'
                },
                // Delete button: requires selection
                'btn-delete': {
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

            // Densitometry button (action bar <a> tag — uses different disabled pattern)
            const densitometryBtn = document.getElementById('btn-densitometry');
            if (densitometryBtn) {
                if (totalBands > 0) {
                    densitometryBtn.classList.remove('gv-action-btn-disabled');
                } else {
                    densitometryBtn.classList.add('gv-action-btn-disabled');
                }
            }
        }

        /**
         * Set a toolbar button's enabled/disabled state.
         * @param {string} buttonId - Button element ID
         * @param {boolean} enabled - Whether button should be enabled
         * @param {string} disabledTooltip - Tooltip to show when disabled
         */
        _setButtonState(buttonId, enabled, disabledTooltip) {
            const button = document.getElementById(buttonId);
            if (!button) return;

            const originalTooltip = button.dataset.tooltip || '';

            if (enabled) {
                button.disabled = false;
                button.classList.remove('gv-toolbar-btn-disabled');
                button.setAttribute('title', originalTooltip);
                // Store original tooltip for later restoration
                if (originalTooltip) {
                    button.dataset.tooltip = originalTooltip;
                }
            } else {
                button.disabled = true;
                button.classList.add('gv-toolbar-btn-disabled');
                button.setAttribute('title', disabledTooltip || 'Action not available');
            }

            // Update MDB tooltip if present
            if (typeof mdb !== 'undefined' && mdb.Tooltip) {
                const tooltipInstance = mdb.Tooltip.getInstance(button);
                if (tooltipInstance) {
                    tooltipInstance.dispose();
                    new mdb.Tooltip(button);
                }
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
