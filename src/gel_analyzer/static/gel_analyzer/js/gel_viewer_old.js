/**
 * GelViewer - Interactive Annotation Viewer for Gel Analyzer
 *
 * Uses SVG.js for annotation rendering and manipulation.
 * Implements CVAT-style interface for lane and band annotation.
 *
 * @requires SVG.js 3.x (https://svgjs.dev/)
 */

(function(global) {
    'use strict';

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    /**
     * GelViewer Class
     *
     * Main controller for the annotation viewer.
     */
    class GelViewer {
        /**
         * Create a GelViewer instance.
         *
         * @param {Object} options - Configuration options
         * @param {string} options.containerId - ID of the viewer container element
         * @param {string} options.analysisId - UUID of the analysis
         * @param {string} options.imageUrl - URL of the gel image
         * @param {string} options.imageProxyUrl - Proxy URL for CORS-free image access
         * @param {number} options.imageWidth - Original image width
         * @param {number} options.imageHeight - Original image height
         * @param {string} options.csrfToken - CSRF token for API requests
         * @param {boolean} options.isEditable - Whether annotations can be edited
         */
        constructor(options) {
            this.containerId = options.containerId;
            this.analysisId = options.analysisId;
            this.imageUrl = options.imageUrl;
            this.imageProxyUrl = options.imageProxyUrl;
            this.imageWidth = options.imageWidth;
            this.imageHeight = options.imageHeight;
            this.csrfToken = options.csrfToken;
            this.isEditable = options.isEditable !== false;

            // State
            this.currentTool = 'select';
            this.scale = 1;
            this.panX = 0;
            this.panY = 0;
            this.minScale = 0.1;
            this.maxScale = 10;

            // Annotations storage
            this.lanes = new Map();
            this.bands = new Map();
            this.selectedAnnotation = null;

            // Pending changes for batch save (hybrid approach)
            this.pendingChanges = {
                lanes: {
                    created: new Map(),   // tempId -> data
                    updated: new Map(),   // id -> data
                    deleted: new Set(),   // Set of ids
                },
                bands: {
                    created: new Map(),   // tempId -> data
                    updated: new Map(),   // id -> data
                    deleted: new Set(),   // Set of ids
                }
            };
            this.tempIdCounter = 0;
            this.isDirty = false;

            // Drawing state
            this.isDrawing = false;
            this.drawingStart = null;
            this.drawingElement = null;
            this.bandPoints = [];

            // Lane shape drawing state
            this.laneShape = 'RECTANGLE';  // RECTANGLE, QUADRILATERAL, POLYGON
            this.laneShapePoints = [];     // For quad/polygon drawing
            this.laneShapePreviewPoints = null;  // For preview rendering

            // Split tool state
            this.splitStartPoint = null;
            this.splitPreviewLine = null;
            this.selectedBandForSplit = null;

            // Panning state
            this.isPanning = false;
            this.panStart = null;

            // Image adjustments state
            this.imageAdjustments = {
                brightness: 100,
                contrast: 100,
                saturation: 100,
                invert: false
            };
            this.adjustmentsPanelVisible = false;

            // Table panel state
            this.tablePanelVisible = false;
            this.tableInstance = null;

            // Sample selector state
            this.sampleSelectorLaneId = null;
            this.sampleSelectorCallback = null;

            // DOM elements
            this.container = null;
            this.viewer = null;
            this.canvasContainer = null;
            this.image = null;
            this.svg = null;

            // Initialize
            this._init();
        }

        /**
         * Initialize the viewer.
         */
        _init() {
            this.container = document.getElementById(this.containerId);
            if (!this.container) {
                console.error('GelViewer: Container not found:', this.containerId);
                return;
            }

            this._setupDOM();
            this._setupEventListeners();
            this._loadAnnotations();

            console.log('GelViewer initialized', {
                analysisId: this.analysisId,
                imageSize: `${this.imageWidth}x${this.imageHeight}`,
                isEditable: this.isEditable
            });

            // Note: localStorage recovery is called at the end of _loadAnnotations()
            // to ensure it runs AFTER server data is loaded
        }

        // =====================================================================
        // Dirty State Management (Hybrid Save Approach)
        // =====================================================================

        /**
         * Check if there are unsaved changes.
         * @returns {boolean}
         */
        hasUnsavedChanges() {
            return this.isDirty;
        }

        /**
         * Mark the state as dirty (unsaved changes).
         */
        _markDirty() {
            if (!this.isDirty) {
                this.isDirty = true;
                this._updateDirtyUI();
                this._saveToLocalStorage();
            }
        }

        /**
         * Mark the state as clean (no unsaved changes).
         */
        _markClean() {
            this.isDirty = false;
            this.pendingChanges = {
                lanes: { created: new Map(), updated: new Map(), deleted: new Set() },
                bands: { created: new Map(), updated: new Map(), deleted: new Set() }
            };
            this._updateDirtyUI();
            this._clearLocalStorage();
        }

        /**
         * Update UI to reflect dirty state.
         */
        _updateDirtyUI() {
            const indicator = document.getElementById('unsaved-indicator');
            const saveBtn = document.getElementById('save-btn');

            if (indicator) {
                indicator.style.display = this.isDirty ? 'flex' : 'none';
            }

            if (saveBtn) {
                saveBtn.classList.toggle('has-changes', this.isDirty);
            }
        }

        /**
         * Generate a temporary ID for new annotations.
         * @returns {string}
         */
        _generateTempId() {
            return `temp_${++this.tempIdCounter}_${Date.now()}`;
        }

        /**
         * Save pending changes to localStorage for crash recovery.
         */
        _saveToLocalStorage() {
            try {
                const data = {
                    analysisId: this.analysisId,
                    timestamp: Date.now(),
                    lanes: Array.from(this.lanes.entries()),
                    bands: Array.from(this.bands.entries()),
                    pendingChanges: {
                        lanes: {
                            created: Array.from(this.pendingChanges.lanes.created.entries()),
                            updated: Array.from(this.pendingChanges.lanes.updated.entries()),
                            deleted: Array.from(this.pendingChanges.lanes.deleted),
                        },
                        bands: {
                            created: Array.from(this.pendingChanges.bands.created.entries()),
                            updated: Array.from(this.pendingChanges.bands.updated.entries()),
                            deleted: Array.from(this.pendingChanges.bands.deleted),
                        }
                    }
                };
                localStorage.setItem(`gelViewer_${this.analysisId}`, JSON.stringify(data));
            } catch (e) {
                console.warn('Failed to save to localStorage:', e);
            }
        }

        /**
         * Load pending changes from localStorage (crash recovery).
         */
        _loadFromLocalStorage() {
            try {
                const stored = localStorage.getItem(`gelViewer_${this.analysisId}`);
                if (!stored) return;

                const data = JSON.parse(stored);

                // Only restore if less than 24 hours old
                if (Date.now() - data.timestamp > 24 * 60 * 60 * 1000) {
                    this._clearLocalStorage();
                    return;
                }

                // Check if there are pending changes
                const hasCreated = data.pendingChanges.lanes.created.length > 0 ||
                                   data.pendingChanges.bands.created.length > 0;
                const hasUpdated = data.pendingChanges.lanes.updated.length > 0 ||
                                   data.pendingChanges.bands.updated.length > 0;
                const hasDeleted = data.pendingChanges.lanes.deleted.length > 0 ||
                                   data.pendingChanges.bands.deleted.length > 0;

                if (hasCreated || hasUpdated || hasDeleted) {
                    // Ask user if they want to restore
                    if (confirm('Unsaved changes were found from a previous session. Do you want to restore them?')) {
                        // Restore pending changes
                        this.pendingChanges = {
                            lanes: {
                                created: new Map(data.pendingChanges.lanes.created),
                                updated: new Map(data.pendingChanges.lanes.updated),
                                deleted: new Set(data.pendingChanges.lanes.deleted),
                            },
                            bands: {
                                created: new Map(data.pendingChanges.bands.created),
                                updated: new Map(data.pendingChanges.bands.updated),
                                deleted: new Set(data.pendingChanges.bands.deleted),
                            }
                        };

                        // Hide deleted lanes (they were loaded from server but user deleted them)
                        for (const laneId of this.pendingChanges.lanes.deleted) {
                            const element = this.svg.findOne(`#lane-${laneId}`);
                            if (element) element.remove();
                            const label = this.svg.findOne(`#lane-label-${laneId}`);
                            if (label) label.remove();
                            this.lanes.delete(laneId);
                        }

                        // Hide deleted bands (they were loaded from server but user deleted/split them)
                        for (const bandId of this.pendingChanges.bands.deleted) {
                            const element = this.svg.findOne(`#band-${bandId}`);
                            if (element) element.remove();
                            this.bands.delete(bandId);
                            // Also remove from lane's bands array
                            for (const [, lane] of this.lanes) {
                                lane.bands = lane.bands.filter(b => b.id !== bandId);
                            }
                        }

                        // Render restored lanes
                        for (const [id, laneData] of this.pendingChanges.lanes.created) {
                            this.lanes.set(id, laneData);
                            this._renderLane(laneData);
                        }

                        // Render restored bands and add to parent lane
                        for (const [id, bandData] of this.pendingChanges.bands.created) {
                            this.bands.set(id, bandData);
                            this._renderBand(bandData);
                            // Add to parent lane's bands array
                            const parentLaneId = bandData._parentLaneId || bandData.lane_id;
                            const parentLane = this.lanes.get(parentLaneId);
                            if (parentLane && !parentLane.bands.find(b => b.id === id)) {
                                parentLane.bands.push(bandData);
                            }
                        }

                        // Update lane numbers and list
                        this._recalculateLaneNumbers();
                        this._updateAnnotationsList();

                        this.isDirty = true;
                        this._updateDirtyUI();
                        this._showMessage('Previous session restored. Remember to save your changes.');
                    } else {
                        this._clearLocalStorage();
                    }
                }
            } catch (e) {
                console.warn('Failed to load from localStorage:', e);
                this._clearLocalStorage();
            }
        }

        /**
         * Clear localStorage backup.
         */
        _clearLocalStorage() {
            try {
                localStorage.removeItem(`gelViewer_${this.analysisId}`);
            } catch (e) {
                console.warn('Failed to clear localStorage:', e);
            }
        }

        /**
         * Set up DOM structure.
         */
        _setupDOM() {
            this.viewer = this.container.querySelector('.gv-viewer');
            this.canvasContainer = this.container.querySelector('.gv-canvas-container');
            this.image = this.container.querySelector('.gv-image');

            // Create SVG overlay using SVG.js
            const svgContainer = this.container.querySelector('.gv-svg-overlay');
            this.svg = SVG(svgContainer).size(this.imageWidth, this.imageHeight);

            // Create layers for organized rendering
            this.lanesGroup = this.svg.group().attr('id', 'lanes-layer');
            this.bandsGroup = this.svg.group().attr('id', 'bands-layer');
            this.handlesGroup = this.svg.group().attr('id', 'handles-layer');
            this.drawingGroup = this.svg.group().attr('id', 'drawing-layer');

            // Wait for image to load before fitting to view
            // This prevents incorrect scale calculations
            const imageEl = document.getElementById('gel-image');
            if (imageEl) {
                if (imageEl.complete && imageEl.naturalHeight !== 0) {
                    // Image already loaded
                    this._fitToView();
                } else {
                    // Wait for image to load
                    imageEl.addEventListener('load', () => {
                        this._fitToView();
                    });
                    // Also handle error case
                    imageEl.addEventListener('error', () => {
                        console.warn('GelViewer: Image failed to load');
                        this._fitToView(); // Still fit to view with placeholder
                    });
                }
            } else {
                // No image element, fit to view anyway
                this._fitToView();
            }
        }

        /**
         * Set up event listeners.
         */
        _setupEventListeners() {
            // Viewer mouse events
            this.viewer.addEventListener('mousedown', this._onMouseDown.bind(this));
            this.viewer.addEventListener('mousemove', this._onMouseMove.bind(this));
            this.viewer.addEventListener('mouseup', this._onMouseUp.bind(this));
            this.viewer.addEventListener('mouseleave', this._onMouseLeave.bind(this));
            this.viewer.addEventListener('wheel', this._onWheel.bind(this), { passive: false });

            // Double-click to finish band polygon
            this.viewer.addEventListener('dblclick', this._onDoubleClick.bind(this));

            // Right-click context menu
            this.viewer.addEventListener('contextmenu', this._onContextMenu.bind(this));

            // Keyboard shortcuts
            document.addEventListener('keydown', this._onKeyDown.bind(this));

            // Click outside to close context menu
            document.addEventListener('click', this._hideContextMenu.bind(this));

            // Setup context menu item handlers
            this._setupContextMenuHandlers();

            // Setup image adjustments panel
            this._setupAdjustmentsPanel();

            // Setup lane shape dropdown
            this._setupLaneShapeDropdown();

            // Setup table panel
            this._setupTablePanel();

            // Setup sample selector modal
            this._setupSampleSelector();

            // Window resize - debounced fit to view
            let resizeTimeout;
            window.addEventListener('resize', () => {
                clearTimeout(resizeTimeout);
                resizeTimeout = setTimeout(() => this._fitToView(), 150);
            });
        }

        /**
         * Setup lane shape dropdown event handlers.
         */
        _setupLaneShapeDropdown() {
            const dropdown = document.querySelector('.gv-tool-dropdown');
            const trigger = dropdown?.querySelector('.gv-dropdown-trigger');
            const menu = document.getElementById('lane-shape-menu');

            if (trigger) {
                trigger.addEventListener('click', (e) => {
                    e.stopPropagation();
                    // If already lane tool, toggle dropdown
                    if (this.currentTool === 'lane') {
                        this._toggleLaneDropdown();
                    } else {
                        // Switch to lane tool with current shape
                        this.setTool('lane');
                    }
                });
            }

            if (menu) {
                menu.querySelectorAll('.gv-dropdown-item').forEach(item => {
                    item.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const shape = item.dataset.laneShape;
                        if (shape) {
                            this.setLaneShape(shape);
                        }
                    });
                });
            }

            // Close dropdown on outside click
            document.addEventListener('click', () => {
                if (dropdown) dropdown.classList.remove('open');
            });
        }

        /**
         * Setup table panel event handlers.
         */
        _setupTablePanel() {
            // Toggle button
            const toggleBtn = document.getElementById('toggle-table');
            if (toggleBtn) {
                toggleBtn.addEventListener('click', () => this._toggleTablePanel());
            }

            // Close button
            const closeBtn = document.getElementById('close-table-panel');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this._hideTablePanel());
            }

            // Apply button (refresh table with saved data)
            const applyBtn = document.getElementById('apply-table-changes');
            if (applyBtn) {
                applyBtn.addEventListener('click', () => {
                    this._showMessage('Changes applied.');
                    this._refreshTableData();
                });
            }

            // Cancel button
            const cancelBtn = document.getElementById('cancel-table-changes');
            if (cancelBtn) {
                cancelBtn.addEventListener('click', () => this._hideTablePanel());
            }

            // Resize handle for panel width
            const resizeHandle = document.getElementById('table-resize');
            const panel = document.getElementById('table-panel');
            if (resizeHandle && panel) {
                let isResizing = false;
                let startX = 0;
                let startWidth = 0;

                resizeHandle.addEventListener('mousedown', (e) => {
                    isResizing = true;
                    startX = e.clientX;
                    startWidth = panel.offsetWidth;
                    resizeHandle.classList.add('dragging');
                    document.body.style.cursor = 'ew-resize';
                    document.body.style.userSelect = 'none';
                    e.preventDefault();
                });

                document.addEventListener('mousemove', (e) => {
                    if (!isResizing) return;
                    const diff = startX - e.clientX;
                    const newWidth = Math.min(Math.max(startWidth + diff, 400), window.innerWidth * 0.85);
                    panel.style.width = `${newWidth}px`;
                });

                document.addEventListener('mouseup', () => {
                    if (isResizing) {
                        isResizing = false;
                        resizeHandle.classList.remove('dragging');
                        document.body.style.cursor = '';
                        document.body.style.userSelect = '';
                    }
                });
            }
        }

        /**
         * Setup sample selector modal event handlers.
         */
        _setupSampleSelector() {
            // Backdrop click to close
            const backdrop = document.getElementById('sample-modal');
            if (backdrop) {
                backdrop.addEventListener('click', (e) => {
                    if (e.target === backdrop) {
                        this._closeSampleSelector();
                    }
                });
            }

            // Close button
            const closeBtn = document.getElementById('sample-modal-close');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this._closeSampleSelector());
            }

            // Search input with debounce
            const searchInput = document.getElementById('sample-search-input');
            let searchTimeout;
            if (searchInput) {
                searchInput.addEventListener('input', () => {
                    clearTimeout(searchTimeout);
                    searchTimeout = setTimeout(() => this._searchSamples(), 300);
                });
            }

            // Filter changes trigger search
            const dsFilter = document.getElementById('sample-filter-ds');
            const sheetFilter = document.getElementById('sample-filter-sheet');
            [dsFilter, sheetFilter].forEach(filter => {
                if (filter) {
                    filter.addEventListener('change', () => this._searchSamples());
                }
            });

            // Cancel button
            const cancelBtn = document.getElementById('sample-modal-cancel');
            if (cancelBtn) {
                cancelBtn.addEventListener('click', () => this._closeSampleSelector());
            }

            // Select button
            const selectBtn = document.getElementById('sample-modal-select');
            if (selectBtn) {
                selectBtn.addEventListener('click', () => this._confirmSampleSelection());
            }
        }

        // =====================================================================
        // Tool Management
        // =====================================================================

        /**
         * Set the current tool.
         *
         * @param {string} toolName - Tool name: 'select', 'pan', 'lane', 'band', 'split'
         */
        setTool(toolName) {
            this.currentTool = toolName;

            // Update viewer cursor class
            this.viewer.className = 'gv-viewer tool-' + toolName;

            // Cancel any drawing in progress
            this._cancelDrawing();

            // Deselect when switching to drawing tools (except split which needs selection)
            if (toolName === 'lane' || toolName === 'band') {
                this._deselect();
            }

            // Update toolbar buttons
            document.querySelectorAll('.gv-toolbar-btn[data-tool]').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.tool === toolName);
            });

            // Close lane shape dropdown when switching tools
            const laneDropdown = document.querySelector('.gv-tool-dropdown');
            if (laneDropdown && toolName !== 'lane') {
                laneDropdown.classList.remove('open');
            }

            this._showMessage(`Tool: ${toolName.charAt(0).toUpperCase() + toolName.slice(1)}`);
        }

        /**
         * Set the lane shape for the lane tool.
         *
         * @param {string} shape - Shape name: 'RECTANGLE', 'QUADRILATERAL', 'POLYGON'
         */
        setLaneShape(shape) {
            this.laneShape = shape;

            // Update dropdown UI
            const menu = document.getElementById('lane-shape-menu');
            if (menu) {
                menu.querySelectorAll('.gv-dropdown-item').forEach(item => {
                    item.classList.toggle('active', item.dataset.laneShape === shape);
                });
            }

            // Update icon based on shape
            const icon = document.getElementById('lane-tool-icon');
            if (icon) {
                icon.className = 'bi';
                switch (shape) {
                    case 'RECTANGLE':
                        icon.classList.add('bi-square');
                        break;
                    case 'QUADRILATERAL':
                        icon.classList.add('bi-diamond');
                        break;
                    case 'POLYGON':
                        icon.classList.add('bi-hexagon');
                        break;
                }
            }

            // Switch to lane tool
            this.setTool('lane');

            // Close dropdown
            const dropdown = document.querySelector('.gv-tool-dropdown');
            if (dropdown) {
                dropdown.classList.remove('open');
            }

            this._showMessage(`Lane Tool: ${shape.charAt(0) + shape.slice(1).toLowerCase()}`);
        }

        /**
         * Toggle lane shape dropdown.
         */
        _toggleLaneDropdown() {
            const dropdown = document.querySelector('.gv-tool-dropdown');
            if (dropdown) {
                dropdown.classList.toggle('open');
            }
        }

        // =====================================================================
        // Mouse Event Handlers
        // =====================================================================

        _onMouseDown(e) {
            if (e.button !== 0) return; // Only left click

            const point = this._getImagePoint(e);

            switch (this.currentTool) {
                case 'pan':
                    this._startPan(e);
                    break;
                case 'lane':
                    if (this.isEditable) {
                        // Handle different lane shapes
                        if (this.laneShape === 'RECTANGLE') {
                            this._startLaneDraw(point);
                        } else {
                            // Quad or Polygon: click to add points
                            this._addLaneShapePoint(point);
                        }
                    }
                    break;
                case 'band':
                    if (this.isEditable) this._addBandPoint(point);
                    break;
                case 'split':
                    if (this.isEditable) this._handleSplitClick(point);
                    break;
                case 'select':
                    // Selection handled by SVG element click events
                    break;
            }
        }

        _onMouseMove(e) {
            const point = this._getImagePoint(e);

            if (this.isPanning) {
                this._updatePan(e);
            } else if (this.isDrawing && this.currentTool === 'lane' && this.laneShape === 'RECTANGLE') {
                this._updateLaneDraw(point);
            } else if (this.currentTool === 'lane' && this.laneShapePoints.length > 0) {
                // Update preview for quad/polygon lane drawing
                this._updateLaneShapePreview(point);
            } else if (this.currentTool === 'band' && this.bandPoints.length > 0) {
                this._updateBandPreview(point);
            } else if (this.currentTool === 'split' && this.splitStartPoint) {
                this._updateSplitPreview(point);
            }

            // Update status bar with coordinates
            this._updateCoordinates(point);
        }

        _onMouseUp(e) {
            if (this.isPanning) {
                this._endPan();
            } else if (this.isDrawing && this.currentTool === 'lane' && this.laneShape === 'RECTANGLE') {
                this._finishLaneDraw();
            }
        }

        _onMouseLeave(e) {
            if (this.isPanning) {
                this._endPan();
            }
        }

        _onDoubleClick(e) {
            if (this.currentTool === 'band' && this.bandPoints.length >= 3) {
                this._finishBandDraw();
            } else if (this.currentTool === 'lane' && this.laneShape === 'POLYGON' && this.laneShapePoints.length >= 3) {
                this._finishLanePolygonDraw();
            }
        }

        _onWheel(e) {
            e.preventDefault();

            // Throttle: max 1 zoom operation per 50ms to prevent erratic behavior
            const now = Date.now();
            if (this._lastWheelTime && now - this._lastWheelTime < 50) {
                return;
            }
            this._lastWheelTime = now;

            const point = this._getImagePoint(e);
            // Reduced sensitivity: 5% instead of 10% for smoother zoom
            const delta = e.deltaY > 0 ? 0.95 : 1.05;

            this._zoom(delta, point);
        }

        _onKeyDown(e) {
            // Don't handle if typing in an input
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

            switch (e.key.toLowerCase()) {
                case 'v':
                    this.setTool('select');
                    break;
                case 'h':
                    this.setTool('pan');
                    break;
                case 'l':
                    // Rectangle lane (default)
                    if (this.isEditable) this.setLaneShape('RECTANGLE');
                    break;
                case 'q':
                    // Quadrilateral lane
                    if (this.isEditable) this.setLaneShape('QUADRILATERAL');
                    break;
                case 'p':
                    // Polygon lane
                    if (this.isEditable) this.setLaneShape('POLYGON');
                    break;
                case 'b':
                    if (this.isEditable) this.setTool('band');
                    break;
                case 's':
                    // Split tool
                    if (this.isEditable) this.setTool('split');
                    break;
                case 't':
                    // Toggle table panel
                    this._toggleTablePanel();
                    break;
                case 'a':
                    this._toggleAdjustmentsPanel();
                    break;
                case 'delete':
                case 'backspace':
                    if (this.isEditable && this.selectedAnnotation) {
                        e.preventDefault();
                        this._deleteSelected();
                    }
                    break;
                case 'enter':
                    // Finish drawing if we have enough points
                    if (this.currentTool === 'band' && this.bandPoints.length >= 3) {
                        e.preventDefault();
                        this._finishBandDraw();
                    } else if (this.currentTool === 'lane' && this.laneShape === 'POLYGON' && this.laneShapePoints.length >= 3) {
                        e.preventDefault();
                        this._finishLanePolygonDraw();
                    }
                    break;
                case 'escape':
                    // Close panels and cancel operations
                    if (this.tablePanelVisible) {
                        this._hideTablePanel();
                    } else if (this.adjustmentsPanelVisible) {
                        this._hideAdjustmentsPanel();
                    } else if (this._isSampleSelectorOpen()) {
                        this._closeSampleSelector();
                    } else {
                        this._hideContextMenu();
                        this._cancelDrawing();
                        this._deselect();
                        this.handlesGroup.clear();
                    }
                    break;
                case '=':
                case '+':
                    this._zoom(1.2);
                    break;
                case '-':
                    this._zoom(0.8);
                    break;
                case '0':
                    this._fitToView();
                    break;
            }
        }

        // =====================================================================
        // Context Menu
        // =====================================================================

        _onContextMenu(e) {
            e.preventDefault();

            // Only show context menu if something is selected and we're editable
            if (!this.selectedAnnotation || !this.isEditable) {
                this._hideContextMenu();
                return;
            }

            this._showContextMenu(e.clientX, e.clientY);
        }

        _showContextMenu(x, y) {
            const menu = document.getElementById('context-menu');
            if (!menu) return;

            // Hide all content sections, show the relevant one
            menu.querySelectorAll('.gv-context-menu-content').forEach(content => {
                content.classList.remove('visible');
            });

            const contentSection = menu.querySelector(
                `.gv-context-menu-content[data-type="${this.selectedAnnotation.type}"]`
            );
            if (contentSection) {
                contentSection.classList.add('visible');
            }

            // Position menu, keeping it within viewport
            const menuWidth = 220;
            const menuHeight = 320;
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;

            let menuX = x;
            let menuY = y;

            if (x + menuWidth > viewportWidth) {
                menuX = viewportWidth - menuWidth - 10;
            }
            if (y + menuHeight > viewportHeight) {
                menuY = viewportHeight - menuHeight - 10;
            }

            menu.style.left = menuX + 'px';
            menu.style.top = menuY + 'px';
            menu.classList.add('visible');
        }

        _hideContextMenu() {
            const menu = document.getElementById('context-menu');
            if (menu) {
                menu.classList.remove('visible');
            }
        }

        _setupContextMenuHandlers() {
            const menu = document.getElementById('context-menu');
            if (!menu) return;

            menu.addEventListener('click', (e) => {
                const item = e.target.closest('.gv-context-menu-item');
                if (!item) return;

                e.stopPropagation();
                const action = item.dataset.action;
                const value = item.dataset.value;

                this._handleContextMenuAction(action, value);
                this._hideContextMenu();
            });
        }

        _handleContextMenuAction(action, value) {
            if (!this.selectedAnnotation) return;

            const { type, id } = this.selectedAnnotation;

            switch (action) {
                case 'edit-properties':
                    // Scroll properties panel into view and focus first input
                    const propsPanel = document.querySelector('.gv-properties');
                    if (propsPanel) {
                        propsPanel.classList.add('visible');
                        document.querySelector('.gv-no-selection')?.classList.add('d-none');
                        const firstInput = propsPanel.querySelector('input, select, textarea');
                        if (firstInput) {
                            setTimeout(() => firstInput.focus(), 100);
                        }
                    }
                    break;

                case 'resize':
                    if (type === 'lane') {
                        this._startLaneResize(id);
                    }
                    break;

                case 'set-type':
                    if (type === 'lane' && value) {
                        this._updateLane(id, { lane_type: value });
                    }
                    break;

                case 'set-mw':
                    if (type === 'band') {
                        this._promptMolecularWeight(id);
                    }
                    break;

                case 'set-band-type':
                    if (type === 'band' && value) {
                        this._updateBand(id, { band_type: value });
                    }
                    break;

                case 'delete':
                    this._deleteSelected();
                    break;
            }
        }

        _startLaneResize(id) {
            const lane = this.lanes.get(id);
            if (!lane) return;

            // Show resize handles on the lane
            this._showResizeHandles(lane);
            this._showMessage('Drag corners to resize lane. Click elsewhere to finish.');
        }

        _showResizeHandles(lane) {
            // Clear existing handles
            this.handlesGroup.clear();

            const handleSize = 10 / this.scale;
            const handles = [
                { pos: 'nw', x: lane.x, y: lane.y },
                { pos: 'ne', x: lane.x + lane.width, y: lane.y },
                { pos: 'sw', x: lane.x, y: lane.y + lane.height },
                { pos: 'se', x: lane.x + lane.width, y: lane.y + lane.height },
            ];

            handles.forEach(h => {
                const handle = this.handlesGroup.rect(handleSize, handleSize)
                    .center(h.x, h.y)
                    .addClass('gv-handle')
                    .attr('data-handle', h.pos)
                    .attr('data-lane-id', lane.id);

                handle.css('cursor', h.pos === 'nw' || h.pos === 'se' ? 'nwse-resize' : 'nesw-resize');

                // Make handle draggable
                handle.on('mousedown', (e) => {
                    e.stopPropagation();
                    this._startHandleDrag(e, lane, h.pos);
                });
            });
        }

        _startHandleDrag(e, lane, handlePos) {
            e.preventDefault();
            const startX = e.clientX;
            const startY = e.clientY;
            const startLane = { ...lane };

            const onMove = (moveEvent) => {
                const dx = (moveEvent.clientX - startX) / this.scale;
                const dy = (moveEvent.clientY - startY) / this.scale;

                let newX = startLane.x;
                let newY = startLane.y;
                let newWidth = startLane.width;
                let newHeight = startLane.height;

                switch (handlePos) {
                    case 'nw':
                        newX = startLane.x + dx;
                        newY = startLane.y + dy;
                        newWidth = startLane.width - dx;
                        newHeight = startLane.height - dy;
                        break;
                    case 'ne':
                        newY = startLane.y + dy;
                        newWidth = startLane.width + dx;
                        newHeight = startLane.height - dy;
                        break;
                    case 'sw':
                        newX = startLane.x + dx;
                        newWidth = startLane.width - dx;
                        newHeight = startLane.height + dy;
                        break;
                    case 'se':
                        newWidth = startLane.width + dx;
                        newHeight = startLane.height + dy;
                        break;
                }

                // Enforce minimum size
                if (newWidth < 20) { newWidth = 20; newX = startLane.x; }
                if (newHeight < 20) { newHeight = 20; newY = startLane.y; }

                // Update local state for preview
                lane.x = newX;
                lane.y = newY;
                lane.width = newWidth;
                lane.height = newHeight;

                // Update SVG
                const element = this.svg.findOne(`#lane-${lane.id}`);
                if (element) {
                    element.move(newX, newY).size(newWidth, newHeight);
                }

                // Update handles
                this._showResizeHandles(lane);
            };

            const onUp = () => {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);

                // Save to server - round to integers (model requires PositiveIntegerField)
                this._updateLane(lane.id, {
                    x: Math.round(lane.x),
                    y: Math.round(lane.y),
                    width: Math.round(lane.width),
                    height: Math.round(lane.height)
                });

                // Clear handles
                this.handlesGroup.clear();
            };

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        }

        _promptMolecularWeight(bandId) {
            const band = this.bands.get(bandId);
            if (!band) return;

            const currentMW = band.estimated_mw_kda || '';
            const newMW = prompt('Enter estimated molecular weight (kDa):', currentMW);

            if (newMW !== null) {
                const mwValue = parseFloat(newMW);
                if (!isNaN(mwValue) && mwValue > 0) {
                    this._updateBand(bandId, { estimated_mw_kda: mwValue });
                } else if (newMW === '') {
                    this._updateBand(bandId, { estimated_mw_kda: null });
                } else {
                    this._showMessage('Invalid molecular weight value');
                }
            }
        }

        // =====================================================================
        // Pan & Zoom
        // =====================================================================

        _startPan(e) {
            this.isPanning = true;
            this.panStart = { x: e.clientX - this.panX, y: e.clientY - this.panY };
            this.viewer.classList.add('panning');
        }

        _updatePan(e) {
            this.panX = e.clientX - this.panStart.x;
            this.panY = e.clientY - this.panStart.y;
            this._updateTransform();
        }

        _endPan() {
            this.isPanning = false;
            this.viewer.classList.remove('panning');
        }

        _zoom(factor, center = null) {
            const newScale = Math.max(this.minScale, Math.min(this.maxScale, this.scale * factor));

            if (newScale === this.scale) return;

            // Zoom towards mouse position
            if (center) {
                const rect = this.viewer.getBoundingClientRect();
                const viewX = center.x * this.scale + this.panX;
                const viewY = center.y * this.scale + this.panY;

                this.scale = newScale;

                // Adjust pan to keep the point under cursor
                this.panX = viewX - center.x * this.scale;
                this.panY = viewY - center.y * this.scale;
            } else {
                // Zoom towards center
                const rect = this.viewer.getBoundingClientRect();
                const centerX = rect.width / 2;
                const centerY = rect.height / 2;

                const oldScale = this.scale;
                this.scale = newScale;

                this.panX = centerX - (centerX - this.panX) * (newScale / oldScale);
                this.panY = centerY - (centerY - this.panY) * (newScale / oldScale);
            }

            this._updateTransform();
            this._updateZoomDisplay();
        }

        _fitToView() {
            const rect = this.viewer.getBoundingClientRect();

            // Calculate scale to fit within viewport
            const fitScale = Math.min(
                rect.width / this.imageWidth,
                rect.height / this.imageHeight
            );

            // Cap at 60% for comfortable viewing, use 90% of fit scale
            this.scale = Math.min(fitScale * 0.9, 0.6);

            // Calculate scaled dimensions
            const scaledWidth = this.imageWidth * this.scale;
            const scaledHeight = this.imageHeight * this.scale;

            // Center in viewport
            this.panX = (rect.width - scaledWidth) / 2;
            this.panY = (rect.height - scaledHeight) / 2;

            this._updateTransform();
            this._updateZoomDisplay();
        }

        _updateTransform() {
            this.canvasContainer.style.transform =
                `translate(${this.panX}px, ${this.panY}px) scale(${this.scale})`;
            this._updateMinimap();
        }

        _updateZoomDisplay() {
            const display = document.querySelector('.gv-zoom-display');
            if (display) {
                display.textContent = Math.round(this.scale * 100) + '%';
            }
        }

        /**
         * Update minimap viewport indicator to show visible area.
         */
        _updateMinimap() {
            const viewport = document.querySelector('.gv-minimap-viewport');
            const minimap = document.querySelector('.gv-minimap');
            if (!viewport || !minimap) return;

            // Get minimap dimensions
            const minimapRect = minimap.getBoundingClientRect();
            const minimapWidth = minimapRect.width;
            const minimapHeight = minimapRect.height;

            // Get viewer dimensions
            const viewerRect = this.viewer.getBoundingClientRect();
            const viewerWidth = viewerRect.width;
            const viewerHeight = viewerRect.height;

            // Calculate visible area in image coordinates
            const visibleLeft = -this.panX / this.scale;
            const visibleTop = -this.panY / this.scale;
            const visibleWidth = viewerWidth / this.scale;
            const visibleHeight = viewerHeight / this.scale;

            // Map to minimap coordinates (centered image in minimap)
            const imageAspect = this.imageWidth / this.imageHeight;
            const minimapAspect = minimapWidth / minimapHeight;

            let offsetX = 0, offsetY = 0;
            let scaledWidth, scaledHeight;

            if (imageAspect > minimapAspect) {
                // Image wider than minimap - full width, centered vertically
                scaledWidth = minimapWidth;
                scaledHeight = minimapWidth / imageAspect;
                offsetY = (minimapHeight - scaledHeight) / 2;
            } else {
                // Image taller than minimap - full height, centered horizontally
                scaledHeight = minimapHeight;
                scaledWidth = minimapHeight * imageAspect;
                offsetX = (minimapWidth - scaledWidth) / 2;
            }

            const finalScale = scaledWidth / this.imageWidth;

            // Calculate viewport rectangle
            let left = offsetX + (visibleLeft * finalScale);
            let top = offsetY + (visibleTop * finalScale);
            let width = visibleWidth * finalScale;
            let height = visibleHeight * finalScale;

            // Clamp to minimap bounds
            left = Math.max(offsetX, Math.min(left, offsetX + scaledWidth - 2));
            top = Math.max(offsetY, Math.min(top, offsetY + scaledHeight - 2));
            width = Math.min(width, scaledWidth);
            height = Math.min(height, scaledHeight);

            // Hide viewport if viewing full image (or more)
            if (width >= scaledWidth && height >= scaledHeight) {
                viewport.style.display = 'none';
            } else {
                viewport.style.display = 'block';
                viewport.style.left = `${left}px`;
                viewport.style.top = `${top}px`;
                viewport.style.width = `${Math.max(10, width)}px`;
                viewport.style.height = `${Math.max(10, height)}px`;
            }
        }

        // =====================================================================
        // Lane Drawing
        // =====================================================================

        _startLaneDraw(point) {
            this.isDrawing = true;
            this.drawingStart = point;

            // Create preview rectangle
            this.drawingElement = this.drawingGroup.rect(0, 0)
                .move(point.x, point.y)
                .addClass('gv-drawing-preview');
        }

        _updateLaneDraw(point) {
            if (!this.drawingElement) return;

            const x = Math.min(this.drawingStart.x, point.x);
            const y = Math.min(this.drawingStart.y, point.y);
            const width = Math.abs(point.x - this.drawingStart.x);
            const height = Math.abs(point.y - this.drawingStart.y);

            this.drawingElement.move(x, y).size(width, height);
        }

        _finishLaneDraw() {
            if (!this.drawingElement) return;

            const bbox = this.drawingElement.bbox();

            // Minimum size check
            if (bbox.width < 10 || bbox.height < 10) {
                this._cancelDrawing();
                this._showMessage('Lane too small. Draw a larger rectangle.');
                return;
            }

            // Create lane via API - round to integers (model requires PositiveIntegerField)
            // Don't send lane_number - let server calculate next available number
            this._createLane({
                x: Math.round(bbox.x),
                y: Math.round(bbox.y),
                width: Math.round(bbox.width),
                height: Math.round(bbox.height),
                lane_type: 'SAMPLE',
            });

            this._cancelDrawing();

            // Switch back to select tool after creating
            this.setTool('select');
        }

        // =====================================================================
        // Lane Shape Drawing (Quadrilateral/Polygon)
        // =====================================================================

        /**
         * Add a point for quadrilateral or polygon lane drawing.
         */
        _addLaneShapePoint(point) {
            this.laneShapePoints.push([point.x, point.y]);

            // Create preview polygon on first point
            if (this.laneShapePoints.length === 1) {
                this.drawingElement = this.drawingGroup.polygon([])
                    .addClass('gv-drawing-preview');
            }

            // For quadrilateral, auto-finish on 4th point
            if (this.laneShape === 'QUADRILATERAL' && this.laneShapePoints.length === 4) {
                this._finishLaneShapeDraw();
                return;
            }

            this._updateLaneShapePreview(point);
        }

        /**
         * Update preview polygon for quad/polygon lane drawing.
         */
        _updateLaneShapePreview(point) {
            if (!this.drawingElement || this.laneShapePoints.length === 0) return;

            // Add current mouse position as temporary point for preview
            const previewPoints = [...this.laneShapePoints, [point.x, point.y]];
            this.drawingElement.plot(previewPoints);
        }

        /**
         * Finish drawing a polygon lane (called on double-click or Enter).
         */
        _finishLanePolygonDraw() {
            if (this.laneShapePoints.length < 3) {
                this._cancelDrawing();
                this._showMessage('Need at least 3 points for a polygon lane.');
                return;
            }
            this._finishLaneShapeDraw();
        }

        /**
         * Finish drawing a quad or polygon lane and create it.
         */
        _finishLaneShapeDraw() {
            const points = this.laneShapePoints;

            // Calculate bounding box from polygon points
            const xs = points.map(p => p[0]);
            const ys = points.map(p => p[1]);
            const minX = Math.min(...xs);
            const maxX = Math.max(...xs);
            const minY = Math.min(...ys);
            const maxY = Math.max(...ys);
            const width = maxX - minX;
            const height = maxY - minY;

            // Minimum size check
            if (width < 10 || height < 10) {
                this._cancelDrawing();
                this._showMessage('Lane too small. Draw a larger shape.');
                return;
            }

            // Round polygon coordinates to integers
            const roundedPolygon = points.map(p => [Math.round(p[0]), Math.round(p[1])]);

            // Create lane with polygon data
            this._createLane({
                lane_shape: this.laneShape,
                polygon: roundedPolygon,
                x: Math.round(minX),
                y: Math.round(minY),
                width: Math.round(width),
                height: Math.round(height),
                lane_type: 'SAMPLE',
            });

            this._cancelDrawing();
            this.setTool('select');
        }

        // =====================================================================
        // Split Tool
        // =====================================================================

        /**
         * Handle click during split tool usage.
         */
        _handleSplitClick(point) {
            // First click - find a band at this point and start split line
            if (!this.splitStartPoint) {
                // Find band under click
                const band = this._findBandAtPoint(point);
                if (!band) {
                    this._showMessage('Click inside a band to split it.');
                    return;
                }

                this.selectedBandForSplit = band.id;
                this.splitStartPoint = point;

                // Create preview line
                this.splitPreviewLine = this.drawingGroup.line(point.x, point.y, point.x, point.y)
                    .addClass('gv-split-line');

                // Add start point marker
                this.drawingGroup.circle(8)
                    .center(point.x, point.y)
                    .addClass('gv-split-point');

                this._showMessage('Click to complete the split line.');
            } else {
                // Second click - complete the split
                this._executeSplit(this.splitStartPoint, point);
            }
        }

        /**
         * Update split line preview during mouse move.
         */
        _updateSplitPreview(point) {
            if (this.splitPreviewLine) {
                this.splitPreviewLine.plot(
                    this.splitStartPoint.x, this.splitStartPoint.y,
                    point.x, point.y
                );
            }
        }

        /**
         * Find a band at the given point.
         */
        _findBandAtPoint(point) {
            for (const [id, band] of this.bands) {
                if (band.polygon && band.polygon.length >= 3) {
                    if (this._pointInPolygon(point, band.polygon)) {
                        return band;
                    }
                }
            }
            return null;
        }

        /**
         * Check if a point is inside a polygon using ray casting.
         */
        _pointInPolygon(point, polygon) {
            let inside = false;
            const x = point.x;
            const y = point.y;

            for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
                const xi = polygon[i][0], yi = polygon[i][1];
                const xj = polygon[j][0], yj = polygon[j][1];

                const intersect = ((yi > y) !== (yj > y)) &&
                    (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
                if (intersect) inside = !inside;
            }

            return inside;
        }

        /**
         * Execute the band split operation.
         */
        _executeSplit(startPoint, endPoint) {
            const band = this.bands.get(this.selectedBandForSplit);
            if (!band || !band.polygon) {
                this._cancelSplit();
                this._showMessage('Band not found or has no polygon.');
                return;
            }

            // Use Sutherland-Hodgman clipping algorithm to split polygon
            const splitResult = this._splitPolygonByLine(
                band.polygon,
                startPoint,
                endPoint
            );

            if (!splitResult || splitResult.length < 2) {
                this._cancelSplit();
                this._showMessage('Could not split the band at this line.');
                return;
            }

            const [polygon1, polygon2] = splitResult;

            // Delete original band
            const laneId = band.lane_id;
            this._deleteBand(band.id);

            // Create two new bands
            if (polygon1.length >= 3) {
                const centerY1 = polygon1.reduce((sum, p) => sum + p[1], 0) / polygon1.length;
                this._createBand(laneId, {
                    polygon: polygon1.map(p => [Math.round(p[0]), Math.round(p[1])]),
                    position_y: Math.round(centerY1),
                    band_type: band.band_type || 'OTHER',
                });
            }

            if (polygon2.length >= 3) {
                const centerY2 = polygon2.reduce((sum, p) => sum + p[1], 0) / polygon2.length;
                this._createBand(laneId, {
                    polygon: polygon2.map(p => [Math.round(p[0]), Math.round(p[1])]),
                    position_y: Math.round(centerY2),
                    band_type: band.band_type || 'OTHER',
                });
            }

            this._cancelSplit();
            this._showMessage('Band split successfully.');

            // Switch back to select tool
            this.setTool('select');
        }

        /**
         * Split a polygon by a line into two polygons.
         * Uses a simplified approach based on the split line.
         */
        _splitPolygonByLine(polygon, startPoint, endPoint) {
            // Calculate line equation ax + by + c = 0
            const dx = endPoint.x - startPoint.x;
            const dy = endPoint.y - startPoint.y;
            const a = dy;
            const b = -dx;
            const c = dx * startPoint.y - dy * startPoint.x;

            // Classify points as above (positive) or below (negative) the line
            const signs = polygon.map(p => Math.sign(a * p[0] + b * p[1] + c));

            // Check if line actually crosses the polygon
            const hasPositive = signs.some(s => s > 0);
            const hasNegative = signs.some(s => s < 0);
            if (!hasPositive || !hasNegative) {
                return null; // Line doesn't split the polygon
            }

            // Find intersection points and build two polygons
            const polygon1 = [];
            const polygon2 = [];

            for (let i = 0; i < polygon.length; i++) {
                const curr = polygon[i];
                const next = polygon[(i + 1) % polygon.length];
                const currSign = signs[i];
                const nextSign = signs[(i + 1) % polygon.length];

                // Add current point to appropriate polygon
                if (currSign >= 0) polygon1.push([...curr]);
                if (currSign <= 0) polygon2.push([...curr]);

                // If edge crosses line, add intersection to both
                if (currSign !== 0 && nextSign !== 0 && currSign !== nextSign) {
                    const intersection = this._lineSegmentIntersection(
                        curr, next,
                        [startPoint.x, startPoint.y],
                        [endPoint.x, endPoint.y]
                    );
                    if (intersection) {
                        polygon1.push(intersection);
                        polygon2.push(intersection);
                    }
                }
            }

            return [polygon1, polygon2];
        }

        /**
         * Find intersection point of two line segments.
         */
        _lineSegmentIntersection(p1, p2, p3, p4) {
            const x1 = p1[0], y1 = p1[1];
            const x2 = p2[0], y2 = p2[1];
            const x3 = p3[0], y3 = p3[1];
            const x4 = p4[0], y4 = p4[1];

            const denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4);
            if (Math.abs(denom) < 1e-10) return null;

            const t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom;

            return [
                x1 + t * (x2 - x1),
                y1 + t * (y2 - y1)
            ];
        }

        /**
         * Cancel split operation.
         */
        _cancelSplit() {
            this.splitStartPoint = null;
            this.selectedBandForSplit = null;

            if (this.splitPreviewLine) {
                this.splitPreviewLine.remove();
                this.splitPreviewLine = null;
            }

            // Remove split point markers
            this.drawingGroup.find('.gv-split-point').forEach(el => el.remove());
        }

        // =====================================================================
        // Band Drawing (Polygon)
        // =====================================================================

        _addBandPoint(point) {
            this.bandPoints.push([point.x, point.y]);

            // Create or update preview polygon
            if (this.bandPoints.length === 1) {
                this.drawingElement = this.drawingGroup.polygon([])
                    .addClass('gv-drawing-preview');
            }

            this._updateBandPreview(point);
        }

        _updateBandPreview(point) {
            if (!this.drawingElement || this.bandPoints.length === 0) return;

            // Add current mouse position as temporary point
            const points = [...this.bandPoints, [point.x, point.y]];
            this.drawingElement.plot(points);
        }

        _finishBandDraw() {
            if (this.bandPoints.length < 3) {
                this._cancelDrawing();
                this._showMessage('Need at least 3 points for a band polygon.');
                return;
            }

            // Find which lane this band belongs to (by center point)
            const centerX = this.bandPoints.reduce((sum, p) => sum + p[0], 0) / this.bandPoints.length;
            const centerY = this.bandPoints.reduce((sum, p) => sum + p[1], 0) / this.bandPoints.length;

            let targetLane = null;
            for (const [id, lane] of this.lanes) {
                if (centerX >= lane.x && centerX <= lane.x + lane.width &&
                    centerY >= lane.y && centerY <= lane.y + lane.height) {
                    targetLane = lane;
                    break;
                }
            }

            if (!targetLane) {
                this._cancelDrawing();
                this._showMessage('Band must be inside a lane. Draw a lane first.');
                return;
            }

            // Auto-assign band type based on lane type
            let bandType = 'OTHER';
            if (targetLane.lane_type === 'LADDER') {
                bandType = 'MW_REFERENCE';
            }

            // Create band via API - round polygon coordinates to integers
            const roundedPolygon = this.bandPoints.map(p => [Math.round(p[0]), Math.round(p[1])]);
            this._createBand(targetLane.id, {
                polygon: roundedPolygon,
                position_y: Math.round(centerY),
                band_type: bandType,
            });

            this._cancelDrawing();

            // Switch back to select tool after creating
            this.setTool('select');
        }

        _cancelDrawing() {
            this.isDrawing = false;
            this.drawingStart = null;
            this.bandPoints = [];
            this.laneShapePoints = [];  // Clear lane shape points

            if (this.drawingElement) {
                this.drawingElement.remove();
                this.drawingElement = null;
            }

            // Cancel any split in progress
            this._cancelSplit();
        }

        // =====================================================================
        // Selection
        // =====================================================================

        _selectAnnotation(type, id) {
            this._deselect();

            this.selectedAnnotation = { type, id };

            // Highlight in SVG
            const element = this.svg.findOne(`#${type}-${id}`);
            if (element) {
                element.addClass('selected');
            }

            // Highlight in list
            document.querySelectorAll('.gv-annotation-item').forEach(item => {
                item.classList.toggle('selected',
                    item.dataset.type === type && item.dataset.id === String(id));
            });

            // Show properties panel
            this._showProperties(type, id);
        }

        _deselect() {
            if (this.selectedAnnotation) {
                const { type, id } = this.selectedAnnotation;
                const element = this.svg.findOne(`#${type}-${id}`);
                if (element) {
                    element.removeClass('selected');
                }
            }

            this.selectedAnnotation = null;

            // Clear highlights
            document.querySelectorAll('.gv-annotation-item.selected').forEach(item => {
                item.classList.remove('selected');
            });

            // Hide properties panel
            this._hideProperties();

            // Remove resize handles
            this.handlesGroup.clear();
        }

        _deleteSelected() {
            if (!this.selectedAnnotation) return;

            const { type, id } = this.selectedAnnotation;

            if (type === 'lane') {
                this._deleteLane(id);
            } else if (type === 'band') {
                this._deleteBand(id);
            }
        }

        // =====================================================================
        // API Operations
        // =====================================================================

        async _loadAnnotations() {
            this._showLoading('Loading annotations...');

            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/data/`, {
                    headers: { 'Accept': 'application/json' }
                });

                if (!response.ok) throw new Error('Failed to load annotations');

                const data = await response.json();

                // Clear existing
                this.lanes.clear();
                this.bands.clear();
                this.lanesGroup.clear();
                this.bandsGroup.clear();

                // Render lanes and bands
                for (const lane of data.lanes) {
                    this._renderLane(lane);
                    for (const band of lane.bands) {
                        this._renderBand(band);
                    }
                }

                // Update annotations list
                this._updateAnnotationsList();

                // Load from localStorage AFTER server data is loaded (crash recovery)
                this._loadFromLocalStorage();

            } catch (error) {
                console.error('Error loading annotations:', error);
                this._showMessage('Error loading annotations');
            } finally {
                this._hideLoading();
            }
        }

        /**
         * Create a new lane (local only - not saved until saveAll).
         * @param {Object} data - Lane data
         */
        _createLane(data) {
            // Generate temporary ID
            const tempId = this._generateTempId();

            // Calculate lane number based on X position
            const laneNumber = this._calculateLaneNumber(data.x);

            // Create local lane object
            const laneData = {
                id: tempId,
                lane_number: laneNumber,
                lane_type: data.lane_type || 'SAMPLE',
                lane_type_display: this._getLaneTypeDisplay(data.lane_type || 'SAMPLE'),
                detection_source: 'MANUAL',
                // Shape and geometry
                lane_shape: data.lane_shape || 'RECTANGLE',
                x: data.x,
                y: data.y,
                width: data.width,
                height: data.height,
                polygon: data.polygon || null,
                // Sample conditions
                is_reduced: data.is_reduced ?? null,
                condition_display: data.is_reduced === true ? 'Reduced' : (data.is_reduced === false ? 'Non-reduced' : ''),
                // Protein load
                protein_load_ug: data.protein_load_ug || null,
                protein_load_type: data.protein_load_type || '',
                protein_load_type_display: this._getProteinLoadTypeDisplay(data.protein_load_type),
                // Sample info
                sample_name: data.sample_name || '',
                process_sample: data.process_sample || null,
                process_sample_id: data.process_sample_id || null,
                notes: data.notes || '',
                bands: [],
                _isNew: true,  // Flag to identify unsaved lanes
            };

            // Store in pending changes
            this.pendingChanges.lanes.created.set(tempId, laneData);

            // Render immediately
            this._renderLane(laneData);

            // Recalculate all lane numbers based on X position
            this._recalculateLaneNumbers();

            // Update UI
            this._updateAnnotationsList();
            this._selectAnnotation('lane', tempId);

            // Mark dirty and update localStorage
            this._markDirty();
            this._saveToLocalStorage();

            this._showMessage('Lane created (unsaved)');
        }

        /**
         * Calculate lane number based on X position.
         */
        _calculateLaneNumber(x) {
            let number = 1;
            for (const [id, lane] of this.lanes) {
                if (lane.x < x) number++;
            }
            return number;
        }

        /**
         * Recalculate lane numbers based on X position (left to right).
         */
        _recalculateLaneNumbers() {
            // Get all lanes sorted by X position
            const sortedLanes = Array.from(this.lanes.values()).sort((a, b) => a.x - b.x);

            sortedLanes.forEach((lane, index) => {
                const newNumber = index + 1;
                if (lane.lane_number !== newNumber) {
                    lane.lane_number = newNumber;

                    // Update SVG label
                    const label = this.svg.findOne(`#lane-label-${lane.id}`);
                    if (label) {
                        label.text(String(newNumber));
                    }
                }
            });
        }

        /**
         * Get display name for lane type.
         */
        _getLaneTypeDisplay(laneType) {
            const displays = {
                'SAMPLE': 'Sample',
                'LADDER': 'MW Ladder',
                'CONTROL': 'Control',
                'EMPTY': 'Empty'
            };
            return displays[laneType] || laneType;
        }

        /**
         * Get display name for protein load type.
         */
        _getProteinLoadTypeDisplay(loadType) {
            if (!loadType) return '';
            const displays = {
                'TOTAL': 'Total Protein',
                'POI': 'Protein of Interest',
                'HOST_CELL': 'Host Cell Protein',
                'OTHER': 'Other'
            };
            return displays[loadType] || loadType;
        }

        /**
         * Update a lane (local only - not saved until saveAll).
         * @param {string|number} id - Lane ID
         * @param {Object} data - Updated lane data
         */
        _updateLane(id, data) {
            const lane = this.lanes.get(id);
            if (!lane) return;

            // Track old X position to see if we need to recalculate lane numbers
            const oldX = lane.x;
            const xChanged = 'x' in data && data.x !== oldX;

            // Update local data
            Object.assign(lane, data);

            // Update display name if lane type changed
            if (data.lane_type) {
                lane.lane_type_display = this._getLaneTypeDisplay(data.lane_type);
            }

            // Track as updated (only if it's an existing server-side lane)
            if (!lane._isNew) {
                const existingUpdates = this.pendingChanges.lanes.updated.get(id) || {};
                this.pendingChanges.lanes.updated.set(id, { ...existingUpdates, ...data });
            } else {
                // Update the pending creation data
                const createData = this.pendingChanges.lanes.created.get(id);
                if (createData) {
                    Object.assign(createData, data);
                }
            }

            // Update SVG element
            const element = this.svg.findOne(`#lane-${id}`);
            if (element) {
                if ('x' in data || 'y' in data || 'width' in data || 'height' in data) {
                    element.move(lane.x, lane.y).size(lane.width, lane.height);

                    // Also update the label position
                    const label = this.svg.findOne(`#lane-label-${id}`);
                    if (label) {
                        label.move(lane.x + 4, lane.y + 4);
                    }
                }

                // Update lane type CSS class for color coding
                if (data.lane_type) {
                    // Remove all type classes individually (SVG.js quirk)
                    element.removeClass('sample');
                    element.removeClass('ladder');
                    element.removeClass('control');
                    element.removeClass('empty');
                    // Add the new type class
                    element.addClass(data.lane_type.toLowerCase());
                }
            }

            // Recalculate lane numbers if X position changed
            if (xChanged) {
                this._recalculateLaneNumbers();
            }

            // Update UI
            this._updateAnnotationsList();

            // Mark dirty and save to localStorage
            this._markDirty();
            this._saveToLocalStorage();

            this._showMessage('Lane updated (unsaved)');
        }

        /**
         * Delete a lane (local only - not saved until saveAll).
         * @param {string|number} id - Lane ID
         */
        _deleteLane(id) {
            const lane = this.lanes.get(id);
            if (!lane) return;

            // If it's a new lane (not yet saved), just remove from pending creates
            if (lane._isNew) {
                this.pendingChanges.lanes.created.delete(id);
            } else {
                // Mark for deletion on server
                this.pendingChanges.lanes.deleted.add(id);
                // Also remove from updated if it was being updated
                this.pendingChanges.lanes.updated.delete(id);
            }

            // Remove associated bands
            for (const band of lane.bands) {
                if (band._isNew) {
                    this.pendingChanges.bands.created.delete(band.id);
                } else {
                    this.pendingChanges.bands.deleted.add(band.id);
                    this.pendingChanges.bands.updated.delete(band.id);
                }
                this.bands.delete(band.id);

                const bandElement = this.svg.findOne(`#band-${band.id}`);
                if (bandElement) bandElement.remove();
            }

            // Remove from storage
            this.lanes.delete(id);

            // Remove from SVG
            const element = this.svg.findOne(`#lane-${id}`);
            if (element) element.remove();

            // Remove lane label
            const labelElement = this.svg.findOne(`#lane-label-${id}`);
            if (labelElement) labelElement.remove();

            // Recalculate lane numbers
            this._recalculateLaneNumbers();

            // Update UI
            this._deselect();
            this._updateAnnotationsList();

            // Mark dirty and save to localStorage
            this._markDirty();
            this._saveToLocalStorage();

            this._showMessage('Lane deleted (unsaved)');
        }

        /**
         * Create a new band (local only - not saved until saveAll).
         * @param {string|number} laneId - Parent lane ID
         * @param {Object} data - Band data
         */
        _createBand(laneId, data) {
            const lane = this.lanes.get(laneId);
            if (!lane) {
                this._showMessage('Error: Lane not found');
                return;
            }

            // Generate temporary ID
            const tempId = this._generateTempId();

            // Create local band object
            const bandData = {
                id: tempId,
                lane_id: laneId,
                band_type: data.band_type || 'OTHER',
                band_type_display: this._getBandTypeDisplay(data.band_type || 'OTHER'),
                detection_source: 'MANUAL',
                position_y: data.position_y,
                polygon: data.polygon || [],
                bbox_x: data.bbox_x,
                bbox_y: data.bbox_y,
                bbox_width: data.bbox_width,
                bbox_height: data.bbox_height,
                estimated_mw_kda: data.estimated_mw_kda || null,
                intensity: null,
                relative_intensity: null,
                label: data.label || '',
                notes: data.notes || '',
                _isNew: true,  // Flag to identify unsaved bands
                _parentLaneId: laneId,  // Track parent lane for saving
            };

            // Store in pending changes
            this.pendingChanges.bands.created.set(tempId, bandData);

            // Render immediately
            this._renderBand(bandData);

            // Add to lane's bands array
            lane.bands.push(bandData);

            // Update UI
            this._updateAnnotationsList();
            this._selectAnnotation('band', tempId);

            // Mark dirty and save to localStorage
            this._markDirty();
            this._saveToLocalStorage();

            this._showMessage('Band created (unsaved)');
        }

        /**
         * Get display name for band type.
         */
        _getBandTypeDisplay(bandType) {
            const displays = {
                'MW_REFERENCE': 'MW Reference',
                'POI': 'Protein of Interest',
                'OTHER': 'Other'
            };
            return displays[bandType] || bandType;
        }

        /**
         * Update a band (local only - not saved until saveAll).
         * @param {string} id - Band ID
         * @param {Object} data - Updated band data
         */
        _updateBand(id, data) {
            const band = this.bands.get(id);
            if (!band) return;

            // Update local data
            Object.assign(band, data);

            // Update display name if band type changed
            if (data.band_type) {
                band.band_type_display = this._getBandTypeDisplay(data.band_type);
            }

            // Track as updated (only if it's an existing server-side band)
            if (!band._isNew) {
                const existingUpdates = this.pendingChanges.bands.updated.get(id) || {};
                this.pendingChanges.bands.updated.set(id, { ...existingUpdates, ...data });
            } else {
                // Update the pending creation data
                const createData = this.pendingChanges.bands.created.get(id);
                if (createData) {
                    Object.assign(createData, data);
                }
            }

            // Update SVG element
            const element = this.svg.findOne(`#band-${id}`);
            if (element) {
                if (data.polygon) {
                    element.plot(data.polygon);
                }

                // Update band type CSS class for color coding
                if (data.band_type) {
                    // Remove all type classes individually (SVG.js quirk)
                    element.removeClass('mw_reference');
                    element.removeClass('poi');
                    element.removeClass('other');
                    // Add the new type class
                    element.addClass(data.band_type.toLowerCase());
                }
            }

            // Update UI
            this._updateAnnotationsList();

            // Mark dirty and save to localStorage
            this._markDirty();
            this._saveToLocalStorage();

            this._showMessage('Band updated (unsaved)');
        }

        /**
         * Delete a band (local only - not saved until saveAll).
         * @param {string} id - Band ID
         */
        _deleteBand(id) {
            const band = this.bands.get(id);
            if (!band) return;

            // If it's a new band (not yet saved), just remove from pending creates
            if (band._isNew) {
                this.pendingChanges.bands.created.delete(id);
            } else {
                // Mark for deletion on server
                this.pendingChanges.bands.deleted.add(id);
                // Also remove from updated if it was being updated
                this.pendingChanges.bands.updated.delete(id);
            }

            // Remove from lane's bands array
            for (const [laneId, lane] of this.lanes) {
                lane.bands = lane.bands.filter(b => b.id !== id);
            }

            // Remove from storage
            this.bands.delete(id);

            // Remove from SVG
            const element = this.svg.findOne(`#band-${id}`);
            if (element) element.remove();

            // Update UI
            this._deselect();
            this._updateAnnotationsList();

            // Mark dirty and save to localStorage
            this._markDirty();
            this._saveToLocalStorage();

            this._showMessage('Band deleted (unsaved)');
        }

        // =====================================================================
        // Batch Save (Save All Changes to Server)
        // =====================================================================

        /**
         * Save all pending changes to the server.
         * This is the main save operation for the hybrid approach.
         */
        async saveAll() {
            if (!this.isDirty) {
                this._showMessage('No changes to save');
                return;
            }

            const saveBtn = document.getElementById('save-btn');
            if (saveBtn) {
                saveBtn.classList.add('saving');
                saveBtn.querySelector('span').textContent = 'Saving...';
            }

            this._showLoading('Saving all changes...');

            try {
                // Track ID mappings for newly created items
                const laneIdMap = new Map();  // tempId -> serverId
                const bandIdMap = new Map();  // tempId -> serverId

                // 1. Delete bands first (before lanes, to avoid FK issues)
                for (const bandId of this.pendingChanges.bands.deleted) {
                    await this._serverDeleteBand(bandId);
                }

                // 2. Delete lanes
                for (const laneId of this.pendingChanges.lanes.deleted) {
                    await this._serverDeleteLane(laneId);
                }

                // 3. Create new lanes
                for (const [tempId, laneData] of this.pendingChanges.lanes.created) {
                    const serverId = await this._serverCreateLane(laneData);
                    if (serverId) {
                        laneIdMap.set(tempId, serverId);
                    }
                }

                // 4. Update existing lanes
                for (const [laneId, updateData] of this.pendingChanges.lanes.updated) {
                    await this._serverUpdateLane(laneId, updateData);
                }

                // 5. Create new bands (with corrected lane IDs)
                for (const [tempId, bandData] of this.pendingChanges.bands.created) {
                    // Map the parent lane ID if it was a temp ID
                    let parentLaneId = bandData._parentLaneId || bandData.lane_id;
                    if (laneIdMap.has(parentLaneId)) {
                        parentLaneId = laneIdMap.get(parentLaneId);
                    }
                    const serverId = await this._serverCreateBand(parentLaneId, bandData);
                    if (serverId) {
                        bandIdMap.set(tempId, serverId);
                    }
                }

                // 6. Update existing bands
                for (const [bandId, updateData] of this.pendingChanges.bands.updated) {
                    await this._serverUpdateBand(bandId, updateData);
                }

                // All changes saved successfully
                this._markClean();

                // Reload from server to get correct IDs and lane numbers
                await this._loadAnnotations();

                this._showMessage('All changes saved successfully!');

            } catch (error) {
                console.error('Error saving changes:', error);
                this._showMessage('Error saving: ' + error.message);
            } finally {
                this._hideLoading();

                if (saveBtn) {
                    saveBtn.classList.remove('saving');
                    saveBtn.querySelector('span').textContent = 'Save';
                }
            }
        }

        /**
         * Server API: Create a lane.
         * @returns {Promise<number|null>} Server-assigned lane ID or null on failure
         */
        async _serverCreateLane(data) {
            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/lanes/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({
                        // Shape and geometry
                        lane_shape: data.lane_shape || 'RECTANGLE',
                        x: data.x,
                        y: data.y,
                        width: data.width,
                        height: data.height,
                        polygon: data.polygon || null,
                        // Type and sample info
                        lane_type: data.lane_type,
                        sample_name: data.sample_name,
                        notes: data.notes,
                        // New metadata fields
                        is_reduced: data.is_reduced,
                        protein_load_ug: data.protein_load_ug,
                        protein_load_type: data.protein_load_type,
                        process_sample_id: data.process_sample_id,
                    }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to create lane');
                }

                const result = await response.json();
                return result.lane.id;
            } catch (error) {
                console.error('Server error creating lane:', error);
                throw error;
            }
        }

        /**
         * Server API: Update a lane.
         */
        async _serverUpdateLane(id, data) {
            try {
                const response = await fetch(`/api/lanes/${id}/`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(data),
                });

                if (!response.ok) {
                    throw new Error('Failed to update lane');
                }
            } catch (error) {
                console.error('Server error updating lane:', error);
                throw error;
            }
        }

        /**
         * Server API: Delete a lane.
         */
        async _serverDeleteLane(id) {
            try {
                const response = await fetch(`/api/lanes/${id}/`, {
                    method: 'DELETE',
                    headers: { 'X-CSRFToken': this.csrfToken },
                });

                if (!response.ok) {
                    throw new Error('Failed to delete lane');
                }
            } catch (error) {
                console.error('Server error deleting lane:', error);
                throw error;
            }
        }

        /**
         * Server API: Create a band.
         * @returns {Promise<string|null>} Server-assigned band UUID or null on failure
         */
        async _serverCreateBand(laneId, data) {
            try {
                const response = await fetch(`/api/lanes/${laneId}/bands/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({
                        polygon: data.polygon,
                        position_y: data.position_y,
                        band_type: data.band_type,
                        estimated_mw_kda: data.estimated_mw_kda,
                        label: data.label,
                        notes: data.notes,
                    }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to create band');
                }

                const result = await response.json();
                return result.band.id;
            } catch (error) {
                console.error('Server error creating band:', error);
                throw error;
            }
        }

        /**
         * Server API: Update a band.
         */
        async _serverUpdateBand(id, data) {
            try {
                const response = await fetch(`/api/bands/${id}/`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(data),
                });

                if (!response.ok) {
                    throw new Error('Failed to update band');
                }
            } catch (error) {
                console.error('Server error updating band:', error);
                throw error;
            }
        }

        /**
         * Server API: Delete a band.
         */
        async _serverDeleteBand(id) {
            try {
                const response = await fetch(`/api/bands/${id}/`, {
                    method: 'DELETE',
                    headers: { 'X-CSRFToken': this.csrfToken },
                });

                if (!response.ok) {
                    throw new Error('Failed to delete band');
                }
            } catch (error) {
                console.error('Server error deleting band:', error);
                throw error;
            }
        }

        /**
         * Refresh lane numbers from server data.
         * Called after delete/reorder operations to keep lane numbers in sync.
         */
        _refreshLaneNumbers(serverLanes) {
            for (const serverLane of serverLanes) {
                const localLane = this.lanes.get(serverLane.id);
                if (localLane && localLane.lane_number !== serverLane.lane_number) {
                    // Update local data
                    localLane.lane_number = serverLane.lane_number;

                    // Update SVG label
                    const label = this.svg.findOne(`#lane-label-${serverLane.id}`);
                    if (label) {
                        label.text(String(serverLane.lane_number));
                    }
                }
            }
        }

        // =====================================================================
        // Rendering
        // =====================================================================

        _renderLane(data) {
            this.lanes.set(data.id, data);

            let shape;

            // Render based on lane shape type
            if (data.lane_shape && data.lane_shape !== 'RECTANGLE' && data.polygon && data.polygon.length >= 3) {
                // Quadrilateral or Polygon shape
                shape = this.lanesGroup.polygon(data.polygon)
                    .attr('id', `lane-${data.id}`)
                    .addClass('gv-lane');
            } else {
                // Default rectangle
                shape = this.lanesGroup.rect(data.width, data.height)
                    .move(data.x, data.y)
                    .attr('id', `lane-${data.id}`)
                    .addClass('gv-lane');
            }

            // Apply lane type as CSS class for color coding
            if (data.lane_type) {
                shape.addClass(data.lane_type.toLowerCase());
            }

            // Add shape class for styling
            if (data.lane_shape) {
                shape.addClass(`shape-${data.lane_shape.toLowerCase()}`);
            }

            // Add label - position at top-left of bounding box
            const labelX = data.polygon && data.polygon.length > 0
                ? Math.min(...data.polygon.map(p => p[0])) + 4
                : data.x + 4;
            const labelY = data.polygon && data.polygon.length > 0
                ? Math.min(...data.polygon.map(p => p[1])) + 4
                : data.y + 4;

            this.lanesGroup.text(String(data.lane_number))
                .move(labelX, labelY)
                .addClass('gv-lane-label')
                .attr('id', `lane-label-${data.id}`);

            // Click handler for selection
            shape.on('click', (e) => {
                e.stopPropagation();
                if (this.currentTool === 'select') {
                    this._selectAnnotation('lane', data.id);
                }
            });
        }

        _renderBand(data) {
            this.bands.set(data.id, data);

            if (data.polygon && data.polygon.length >= 3) {
                const poly = this.bandsGroup.polygon(data.polygon)
                    .attr('id', `band-${data.id}`)
                    .addClass('gv-band')
                    .addClass((data.band_type || 'OTHER').toLowerCase());

                // Click handler for selection
                poly.on('click', (e) => {
                    e.stopPropagation();
                    if (this.currentTool === 'select') {
                        this._selectAnnotation('band', data.id);
                    }
                });
            }
        }

        // =====================================================================
        // UI Updates
        // =====================================================================

        _updateAnnotationsList() {
            const list = document.querySelector('.gv-annotations-list');
            if (!list) return;

            list.innerHTML = '';

            // Update status bar counts
            const laneCount = document.getElementById('lane-count');
            const bandCount = document.getElementById('band-count');
            const totalBands = Array.from(this.lanes.values()).reduce((sum, l) => sum + l.bands.length, 0);
            if (laneCount) laneCount.textContent = `${this.lanes.size} lanes`;
            if (bandCount) bandCount.textContent = `${totalBands} bands`;

            // Lanes
            for (const [id, lane] of this.lanes) {
                const laneTypeClass = (lane.lane_type || 'SAMPLE').toLowerCase();
                const item = document.createElement('div');
                item.className = 'gv-annotation-item';
                item.dataset.type = 'lane';
                item.dataset.id = id;
                item.innerHTML = `
                    <div class="gv-annotation-icon lane ${escapeHtml(laneTypeClass)}">
                        <i class="bi bi-layout-three-columns"></i>
                    </div>
                    <div class="gv-annotation-info">
                        <div class="gv-annotation-name">Lane ${lane.lane_number}</div>
                        <div class="gv-annotation-meta">${escapeHtml(lane.sample_name || lane.lane_type_display)}</div>
                    </div>
                `;
                item.addEventListener('click', () => this._selectAnnotation('lane', id));
                list.appendChild(item);

                // Nested bands
                for (const band of lane.bands) {
                    const bandTypeClass = (band.band_type || 'OTHER').toLowerCase();
                    const bandItem = document.createElement('div');
                    bandItem.className = 'gv-annotation-item';
                    bandItem.dataset.type = 'band';
                    bandItem.dataset.id = band.id;
                    bandItem.style.paddingLeft = '32px';
                    bandItem.innerHTML = `
                        <div class="gv-annotation-icon band ${escapeHtml(bandTypeClass)}">
                            <i class="bi bi-grip-horizontal"></i>
                        </div>
                        <div class="gv-annotation-info">
                            <div class="gv-annotation-name">${escapeHtml(band.label || 'Band')}</div>
                            <div class="gv-annotation-meta">${band.estimated_mw_kda ? band.estimated_mw_kda + ' kDa' : ''}</div>
                        </div>
                    `;
                    bandItem.addEventListener('click', () => this._selectAnnotation('band', band.id));
                    list.appendChild(bandItem);
                }
            }
        }

        _showProperties(type, id) {
            const panel = document.querySelector('.gv-properties');
            const noSelection = document.querySelector('.gv-no-selection');

            if (panel) panel.classList.add('visible');
            if (noSelection) noSelection.style.display = 'none';

            if (type === 'lane') {
                const lane = this.lanes.get(id);
                this._renderLaneProperties(lane);
            } else if (type === 'band') {
                const band = this.bands.get(id);
                this._renderBandProperties(band);
            }
        }

        _hideProperties() {
            const panel = document.querySelector('.gv-properties');
            const noSelection = document.querySelector('.gv-no-selection');

            if (panel) panel.classList.remove('visible');
            if (noSelection) noSelection.style.display = 'block';
        }

        _renderLaneProperties(lane) {
            const container = document.querySelector('.gv-properties-content');
            if (!container) return;

            container.innerHTML = `
                <div class="gv-quick-form">
                    <h6 class="mb-3">Lane ${lane.lane_number}</h6>

                    <div class="mb-2">
                        <label class="form-label">Type</label>
                        <select class="form-select form-select-sm" id="prop-lane-type" data-field="lane_type">
                            <option value="SAMPLE" ${lane.lane_type === 'SAMPLE' ? 'selected' : ''}>Sample</option>
                            <option value="LADDER" ${lane.lane_type === 'LADDER' ? 'selected' : ''}>MW Ladder</option>
                            <option value="EMPTY" ${lane.lane_type === 'EMPTY' ? 'selected' : ''}>Empty</option>
                            <option value="CONTROL" ${lane.lane_type === 'CONTROL' ? 'selected' : ''}>Control</option>
                        </select>
                    </div>

                    <div class="mb-2">
                        <label class="form-label">Condition</label>
                        <select class="form-select form-select-sm" id="prop-is-reduced" data-field="is_reduced">
                            <option value="" ${lane.is_reduced == null ? 'selected' : ''}>—</option>
                            <option value="true" ${lane.is_reduced === true ? 'selected' : ''}>Reduced</option>
                            <option value="false" ${lane.is_reduced === false ? 'selected' : ''}>Non-reduced</option>
                        </select>
                    </div>

                    <div class="mb-2">
                        <label class="form-label">Protein Load (µg)</label>
                        <input type="number" class="form-control form-control-sm" id="prop-protein-load"
                               data-field="protein_load_ug"
                               value="${lane.protein_load_ug || ''}" step="0.1" min="0" placeholder="—">
                    </div>

                    <div class="mb-2">
                        <label class="form-label">Load Type</label>
                        <select class="form-select form-select-sm" id="prop-load-type" data-field="protein_load_type">
                            <option value="" ${!lane.protein_load_type ? 'selected' : ''}>—</option>
                            <option value="TOTAL" ${lane.protein_load_type === 'TOTAL' ? 'selected' : ''}>Total Protein</option>
                            <option value="POI" ${lane.protein_load_type === 'POI' ? 'selected' : ''}>Protein of Interest</option>
                            <option value="HOST_CELL" ${lane.protein_load_type === 'HOST_CELL' ? 'selected' : ''}>Host Cell Protein</option>
                            <option value="OTHER" ${lane.protein_load_type === 'OTHER' ? 'selected' : ''}>Other</option>
                        </select>
                    </div>

                    <div class="mb-2">
                        <label class="form-label">Sample</label>
                        <div class="input-group input-group-sm">
                            <input type="text" class="form-control" id="prop-sample-name"
                                   value="${escapeHtml(lane.sample_name || '')}" placeholder="Click to search..." readonly>
                            <button class="btn btn-outline-primary" type="button" id="prop-sample-search-btn">
                                <i class="bi bi-search"></i>
                            </button>
                        </div>
                    </div>

                    <div class="mb-2">
                        <label class="form-label">Notes</label>
                        <textarea class="form-control form-control-sm" id="prop-notes" data-field="notes" rows="2">${escapeHtml(lane.notes || '')}</textarea>
                    </div>

                    <div class="gv-quick-form-actions mt-3">
                        <button class="btn btn-sm btn-outline-danger" onclick="window.gelViewer._deleteLane(${lane.id})">
                            <i class="bi bi-trash"></i> Delete
                        </button>
                    </div>
                </div>
            `;

            // Add event listeners for live sync
            this._setupPropertiesListeners(lane.id, 'lane');
        }

        /**
         * Setup event listeners for properties panel fields.
         */
        _setupPropertiesListeners(id, type) {
            const container = document.querySelector('.gv-properties-content');
            if (!container) return;

            // Sample search button
            const sampleSearchBtn = document.getElementById('prop-sample-search-btn');
            const sampleInput = document.getElementById('prop-sample-name');
            if (sampleSearchBtn) {
                sampleSearchBtn.addEventListener('click', () => this._openSampleSelector(id));
            }
            if (sampleInput) {
                sampleInput.addEventListener('click', () => this._openSampleSelector(id));
            }

            // Select fields - immediate update
            container.querySelectorAll('select[data-field]').forEach(select => {
                select.addEventListener('change', (e) => {
                    this._handlePropertiesChange(id, type, e.target);
                });
            });

            // Input/textarea fields - debounced update
            container.querySelectorAll('input[data-field], textarea[data-field]').forEach(input => {
                let debounceTimer;
                input.addEventListener('input', (e) => {
                    clearTimeout(debounceTimer);
                    debounceTimer = setTimeout(() => {
                        this._handlePropertiesChange(id, type, e.target);
                    }, 300);
                });
                input.addEventListener('blur', (e) => {
                    clearTimeout(debounceTimer);
                    this._handlePropertiesChange(id, type, e.target);
                });
            });
        }

        /**
         * Handle changes from properties panel and sync with table.
         */
        _handlePropertiesChange(id, type, input) {
            const field = input.dataset.field;
            let value = input.value;

            // Parse value based on field type
            if (field === 'is_reduced') {
                value = value === '' ? null : value === 'true';
            } else if (field === 'protein_load_ug') {
                value = value === '' ? null : parseFloat(value);
            }

            if (type === 'lane') {
                const lane = this.lanes.get(id);
                if (lane) {
                    lane[field] = value;
                    this._updateLaneFromTable(id, { [field]: value }, true);

                    // Sync with table if visible
                    this._syncTableCell(id, field, value);
                }
            }
        }

        /**
         * Sync a table cell with updated value from properties panel.
         */
        _syncTableCell(laneId, field, value) {
            const row = document.querySelector(`tr[data-lane-id="${laneId}"]`);
            if (!row) return;

            const input = row.querySelector(`[data-field="${field}"]`);
            if (input) {
                if (input.tagName === 'SELECT') {
                    input.value = value === null ? '' : String(value);
                } else {
                    input.value = value || '';
                }
            }
        }

        /**
         * Sync properties panel with updated value from table.
         */
        _syncPropertiesField(field, value) {
            const fieldMap = {
                'lane_type': 'prop-lane-type',
                'is_reduced': 'prop-is-reduced',
                'protein_load_ug': 'prop-protein-load',
                'protein_load_type': 'prop-load-type',
                'sample_name': 'prop-sample-name',
                'notes': 'prop-notes'
            };

            const elementId = fieldMap[field];
            if (!elementId) return;

            const element = document.getElementById(elementId);
            if (element) {
                if (element.tagName === 'SELECT') {
                    element.value = value === null ? '' : String(value);
                } else {
                    element.value = value || '';
                }
            }
        }

        _renderBandProperties(band) {
            const container = document.querySelector('.gv-properties-content');
            if (!container) return;

            container.innerHTML = `
                <div class="gv-quick-form">
                    <h6 class="mb-3">Band</h6>
                    <div class="mb-2">
                        <label class="form-label">Band Type</label>
                        <select class="form-select form-select-sm" id="prop-band-type">
                            <option value="OTHER" ${band.band_type === 'OTHER' ? 'selected' : ''}>Other</option>
                            <option value="POI" ${band.band_type === 'POI' ? 'selected' : ''}>Protein of Interest</option>
                            <option value="MW_REFERENCE" ${band.band_type === 'MW_REFERENCE' ? 'selected' : ''}>MW Reference</option>
                        </select>
                    </div>
                    <div class="mb-2">
                        <label class="form-label">Label</label>
                        <input type="text" class="form-control form-control-sm" id="prop-label"
                               value="${escapeHtml(band.label || '')}" placeholder="e.g., Main product">
                    </div>
                    <div class="mb-2">
                        <label class="form-label">Estimated MW (kDa)</label>
                        <input type="number" class="form-control form-control-sm" id="prop-mw"
                               value="${band.estimated_mw_kda || ''}" step="0.1" placeholder="e.g., 150.0">
                    </div>
                    <div class="mb-2">
                        <label class="form-label">Notes</label>
                        <textarea class="form-control form-control-sm" id="prop-band-notes" rows="2">${escapeHtml(band.notes || '')}</textarea>
                    </div>
                    <div class="gv-quick-form-actions">
                        <button class="btn btn-sm btn-primary" onclick="window.gelViewer._saveBandProperties('${band.id}')">
                            <i class="bi bi-save me-1"></i> Save
                        </button>
                        <button class="btn btn-sm btn-outline-danger" onclick="window.gelViewer._deleteBand('${band.id}')">
                            <i class="bi bi-trash me-1"></i> Delete
                        </button>
                    </div>
                </div>
            `;
        }

        _saveLaneProperties(id) {
            const laneType = document.getElementById('prop-lane-type')?.value;
            const sampleName = document.getElementById('prop-sample-name')?.value;
            const notes = document.getElementById('prop-notes')?.value;

            this._updateLane(id, {
                lane_type: laneType,
                sample_name: sampleName,
                notes: notes,
            });
        }

        _saveBandProperties(id) {
            const bandType = document.getElementById('prop-band-type')?.value;
            const label = document.getElementById('prop-label')?.value;
            const mw = document.getElementById('prop-mw')?.value;
            const notes = document.getElementById('prop-band-notes')?.value;

            this._updateBand(id, {
                band_type: bandType,
                label: label,
                estimated_mw_kda: mw ? parseFloat(mw) : null,
                notes: notes,
            });
        }

        _showMessage(text, duration = 2000) {
            // Remove existing message
            const existing = document.querySelector('.gv-message');
            if (existing) existing.remove();

            const message = document.createElement('div');
            message.className = 'gv-message';
            message.textContent = text;
            this.viewer.appendChild(message);

            setTimeout(() => message.remove(), duration);
        }

        _showLoading(text = 'Processing...') {
            const overlay = document.getElementById('loading-overlay');
            const textEl = overlay?.querySelector('.gv-loading-text');

            if (textEl) {
                textEl.textContent = text;
            }

            if (overlay) {
                overlay.classList.add('visible');
            }
        }

        _hideLoading() {
            const overlay = document.getElementById('loading-overlay');
            if (overlay) {
                overlay.classList.remove('visible');
            }
        }

        _updateCoordinates(point) {
            const coordDisplay = document.querySelector('.gv-coordinates');
            if (coordDisplay) {
                coordDisplay.textContent = `${Math.round(point.x)}, ${Math.round(point.y)}`;
            }
        }

        // =====================================================================
        // Image Adjustments
        // =====================================================================

        /**
         * Setup image adjustments panel event handlers.
         */
        _setupAdjustmentsPanel() {
            // Toggle button
            const toggleBtn = document.getElementById('adjust-image');
            if (toggleBtn) {
                toggleBtn.addEventListener('click', () => this._toggleAdjustmentsPanel());
            }

            // Close button
            const closeBtn = document.getElementById('adjustments-close');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this._hideAdjustmentsPanel());
            }

            // Sliders
            const brightnessSlider = document.getElementById('adj-brightness');
            const contrastSlider = document.getElementById('adj-contrast');
            const saturationSlider = document.getElementById('adj-saturation');
            const invertCheckbox = document.getElementById('adj-invert');

            if (brightnessSlider) {
                brightnessSlider.addEventListener('input', (e) => {
                    this.imageAdjustments.brightness = parseInt(e.target.value);
                    this._updateAdjustmentValue('brightness');
                    this._applyImageAdjustments();
                });
            }

            if (contrastSlider) {
                contrastSlider.addEventListener('input', (e) => {
                    this.imageAdjustments.contrast = parseInt(e.target.value);
                    this._updateAdjustmentValue('contrast');
                    this._applyImageAdjustments();
                });
            }

            if (saturationSlider) {
                saturationSlider.addEventListener('input', (e) => {
                    this.imageAdjustments.saturation = parseInt(e.target.value);
                    this._updateAdjustmentValue('saturation');
                    this._applyImageAdjustments();
                });
            }

            if (invertCheckbox) {
                invertCheckbox.addEventListener('change', (e) => {
                    this.imageAdjustments.invert = e.target.checked;
                    this._applyImageAdjustments();
                });
            }

            // Auto-enhance button
            const autoEnhanceBtn = document.getElementById('adj-auto-enhance');
            if (autoEnhanceBtn) {
                autoEnhanceBtn.addEventListener('click', () => this._autoEnhance());
            }

            // Reset button
            const resetBtn = document.getElementById('adj-reset');
            if (resetBtn) {
                resetBtn.addEventListener('click', () => this._resetAdjustments());
            }
        }

        /**
         * Toggle adjustments panel visibility.
         */
        _toggleAdjustmentsPanel() {
            if (this.adjustmentsPanelVisible) {
                this._hideAdjustmentsPanel();
            } else {
                this._showAdjustmentsPanel();
            }
        }

        /**
         * Show adjustments panel.
         */
        _showAdjustmentsPanel() {
            const panel = document.getElementById('adjustments-panel');
            const toggleBtn = document.getElementById('adjust-image');

            if (panel) {
                panel.style.display = 'block';
                this.adjustmentsPanelVisible = true;
            }

            if (toggleBtn) {
                toggleBtn.classList.add('active');
            }
        }

        /**
         * Hide adjustments panel.
         */
        _hideAdjustmentsPanel() {
            const panel = document.getElementById('adjustments-panel');
            const toggleBtn = document.getElementById('adjust-image');

            if (panel) {
                panel.style.display = 'none';
                this.adjustmentsPanelVisible = false;
            }

            if (toggleBtn) {
                toggleBtn.classList.remove('active');
            }
        }

        /**
         * Update adjustment value display.
         */
        _updateAdjustmentValue(type) {
            const valueEl = document.getElementById(`adj-${type}-value`);
            if (valueEl) {
                valueEl.textContent = `${this.imageAdjustments[type]}%`;
            }
        }

        /**
         * Apply CSS filters to the image.
         */
        _applyImageAdjustments() {
            if (!this.image) return;

            const { brightness, contrast, saturation, invert } = this.imageAdjustments;

            this.image.style.filter = `
                brightness(${brightness}%)
                contrast(${contrast}%)
                saturate(${saturation}%)
                invert(${invert ? 1 : 0})
            `.trim().replace(/\s+/g, ' ');
        }

        /**
         * Reset adjustments to defaults.
         */
        _resetAdjustments() {
            this.imageAdjustments = {
                brightness: 100,
                contrast: 100,
                saturation: 100,
                invert: false
            };

            // Update sliders
            const brightnessSlider = document.getElementById('adj-brightness');
            const contrastSlider = document.getElementById('adj-contrast');
            const saturationSlider = document.getElementById('adj-saturation');
            const invertCheckbox = document.getElementById('adj-invert');

            if (brightnessSlider) brightnessSlider.value = 100;
            if (contrastSlider) contrastSlider.value = 100;
            if (saturationSlider) saturationSlider.value = 100;
            if (invertCheckbox) invertCheckbox.checked = false;

            // Update value displays
            this._updateAdjustmentValue('brightness');
            this._updateAdjustmentValue('contrast');
            this._updateAdjustmentValue('saturation');

            // Apply to image
            this._applyImageAdjustments();

            this._showMessage('Adjustments reset');
        }

        /**
         * Auto-enhance the image by analyzing the histogram.
         * Uses fetch-based loading to avoid CORS tainted canvas issues.
         */
        async _autoEnhance() {
            if (!this.image) {
                this._showMessage('No image to enhance');
                return;
            }

            this._showMessage('Analyzing image...');

            try {
                // Fetch image as blob to avoid CORS tainted canvas
                const imageToAnalyze = await this._loadImageForAnalysis();

                // Create a canvas to analyze the image
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');

                // Use a smaller size for performance (max 500px)
                const maxSize = 500;
                const scale = Math.min(1, maxSize / Math.max(imageToAnalyze.naturalWidth, imageToAnalyze.naturalHeight));
                canvas.width = Math.floor(imageToAnalyze.naturalWidth * scale);
                canvas.height = Math.floor(imageToAnalyze.naturalHeight * scale);

                // Draw the image
                ctx.drawImage(imageToAnalyze, 0, 0, canvas.width, canvas.height);

                // Get image data
                const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
                const data = imageData.data;

                // Calculate histogram
                const histogram = this._calculateHistogram(data);

                // Analyze histogram and calculate optimal adjustments
                const adjustments = this._analyzeHistogram(histogram);

                // Apply adjustments
                this.imageAdjustments.brightness = adjustments.brightness;
                this.imageAdjustments.contrast = adjustments.contrast;
                this.imageAdjustments.saturation = 100; // Keep saturation neutral

                // Update sliders
                const brightnessSlider = document.getElementById('adj-brightness');
                const contrastSlider = document.getElementById('adj-contrast');

                if (brightnessSlider) brightnessSlider.value = adjustments.brightness;
                if (contrastSlider) contrastSlider.value = adjustments.contrast;

                // Update value displays
                this._updateAdjustmentValue('brightness');
                this._updateAdjustmentValue('contrast');

                // Apply to image
                this._applyImageAdjustments();

                this._showMessage('Auto-enhancement applied');

            } catch (error) {
                console.error('Auto-enhance error:', error);
                if (error.message.includes('CORS') || error.message.includes('cross-origin') || error.name === 'SecurityError') {
                    this._showMessage('Cannot analyze: image server blocks access');
                } else {
                    this._showMessage('Auto-enhance failed');
                }
            }
        }

        /**
         * Load image for histogram analysis, avoiding CORS tainted canvas.
         * Uses the Django proxy endpoint for CORS-free access.
         * @returns {Promise<HTMLImageElement>}
         */
        async _loadImageForAnalysis() {
            // Use the proxy URL if available, otherwise fall back to direct URL
            const imageUrl = this.imageProxyUrl || this.image.src;

            // Fetch image as blob via Django proxy (same-origin, no CORS issues)
            const response = await fetch(imageUrl, {
                credentials: 'same-origin'
            });

            if (!response.ok) {
                throw new Error(`Failed to fetch image: ${response.status}`);
            }

            const blob = await response.blob();
            const objectUrl = URL.createObjectURL(blob);

            // Create new image from blob URL
            return new Promise((resolve, reject) => {
                const img = new Image();
                img.onload = () => {
                    // Clean up object URL after image loads
                    URL.revokeObjectURL(objectUrl);
                    resolve(img);
                };
                img.onerror = () => {
                    URL.revokeObjectURL(objectUrl);
                    reject(new Error('Failed to load image from blob'));
                };
                img.src = objectUrl;
            });
        }

        /**
         * Calculate histogram from image data.
         * @param {Uint8ClampedArray} data - Image pixel data
         * @returns {Array} Histogram (256 values)
         */
        _calculateHistogram(data) {
            const histogram = new Array(256).fill(0);
            const sampleStep = 4; // Sample every 4th pixel for speed

            for (let i = 0; i < data.length; i += 4 * sampleStep) {
                // Convert to grayscale using luminance formula
                const r = data[i];
                const g = data[i + 1];
                const b = data[i + 2];
                const gray = Math.round(0.299 * r + 0.587 * g + 0.114 * b);
                histogram[gray]++;
            }

            return histogram;
        }

        /**
         * Analyze histogram and calculate optimal adjustments.
         * @param {Array} histogram - Image histogram
         * @returns {Object} { brightness, contrast }
         */
        _analyzeHistogram(histogram) {
            // Find min and max values (5th and 95th percentile to ignore outliers)
            const total = histogram.reduce((a, b) => a + b, 0);
            const percentile5 = total * 0.05;
            const percentile95 = total * 0.95;

            let cumulative = 0;
            let minVal = 0;
            let maxVal = 255;

            for (let i = 0; i < 256; i++) {
                cumulative += histogram[i];
                if (cumulative >= percentile5 && minVal === 0) {
                    minVal = i;
                }
                if (cumulative >= percentile95) {
                    maxVal = i;
                    break;
                }
            }

            // Calculate mean brightness
            let sum = 0;
            let count = 0;
            for (let i = 0; i < 256; i++) {
                sum += i * histogram[i];
                count += histogram[i];
            }
            const mean = sum / count;

            // Calculate optimal adjustments
            // Contrast: stretch the histogram to use more of the 0-255 range
            const range = maxVal - minVal;
            let contrast = 100;
            if (range > 0 && range < 200) {
                // Increase contrast if the image has low dynamic range
                contrast = Math.round(Math.min(200, (200 / range) * 100));
            }

            // Brightness: adjust so mean is around 128 (middle gray)
            let brightness = 100;
            if (mean < 100) {
                // Image is too dark, increase brightness
                brightness = Math.round(Math.min(180, 100 + (128 - mean) * 0.5));
            } else if (mean > 160) {
                // Image is too bright, decrease brightness
                brightness = Math.round(Math.max(60, 100 - (mean - 128) * 0.5));
            }

            // Clamp values
            brightness = Math.max(50, Math.min(200, brightness));
            contrast = Math.max(80, Math.min(200, contrast));

            return { brightness, contrast };
        }

        // =====================================================================
        // Data Table Panel
        // =====================================================================

        /**
         * Toggle the data table panel visibility.
         */
        _toggleTablePanel() {
            if (this.tablePanelVisible) {
                this._hideTablePanel();
            } else {
                this._showTablePanel();
            }
        }

        /**
         * Show the data table panel.
         */
        _showTablePanel() {
            const panel = document.getElementById('table-panel');
            const toggleBtn = document.getElementById('toggle-table');

            if (panel) {
                panel.classList.add('open');
                this.tablePanelVisible = true;
                if (toggleBtn) toggleBtn.classList.add('active');

                // Initialize or refresh the table
                this._refreshTableData();
            }
        }

        /**
         * Hide the data table panel.
         */
        _hideTablePanel() {
            const panel = document.getElementById('table-panel');
            const toggleBtn = document.getElementById('toggle-table');

            if (panel) {
                panel.classList.remove('open');
                this.tablePanelVisible = false;
                if (toggleBtn) toggleBtn.classList.remove('active');
            }
        }

        /**
         * Refresh the table with current lane data.
         */
        _refreshTableData() {
            const tbody = document.querySelector('#lane-data-table tbody');
            const laneCountEl = document.getElementById('table-lane-count');
            if (!tbody) return;

            tbody.innerHTML = '';

            // Sort lanes by lane_number
            const sortedLanes = Array.from(this.lanes.values())
                .sort((a, b) => a.lane_number - b.lane_number);

            // Update lane count in footer
            if (laneCountEl) {
                const count = sortedLanes.length;
                laneCountEl.textContent = `${count} lane${count !== 1 ? 's' : ''}`;
            }

            // Show empty state if no lanes
            if (sortedLanes.length === 0) {
                const emptyRow = document.createElement('tr');
                emptyRow.innerHTML = `
                    <td colspan="6" class="gv-table-empty">
                        <i class="bi bi-inbox"></i>
                        <p>No lanes defined yet. Draw lanes on the gel image to get started.</p>
                    </td>
                `;
                tbody.appendChild(emptyRow);
                return;
            }

            for (const lane of sortedLanes) {
                const row = document.createElement('tr');
                row.dataset.laneId = lane.id;
                row.innerHTML = `
                    <td>${lane.lane_number}</td>
                    <td>
                        <select data-field="lane_type">
                            <option value="SAMPLE" ${lane.lane_type === 'SAMPLE' ? 'selected' : ''}>Sample</option>
                            <option value="LADDER" ${lane.lane_type === 'LADDER' ? 'selected' : ''}>Ladder</option>
                            <option value="EMPTY" ${lane.lane_type === 'EMPTY' ? 'selected' : ''}>Empty</option>
                            <option value="CONTROL" ${lane.lane_type === 'CONTROL' ? 'selected' : ''}>Control</option>
                        </select>
                    </td>
                    <td>
                        <select data-field="is_reduced">
                            <option value="" ${lane.is_reduced == null ? 'selected' : ''}>—</option>
                            <option value="true" ${lane.is_reduced === true ? 'selected' : ''}>Reduced</option>
                            <option value="false" ${lane.is_reduced === false ? 'selected' : ''}>Non-reduced</option>
                        </select>
                    </td>
                    <td>
                        <input type="number" data-field="protein_load_ug"
                               value="${lane.protein_load_ug || ''}" step="0.1" min="0" placeholder="—">
                    </td>
                    <td>
                        <select data-field="protein_load_type">
                            <option value="" ${!lane.protein_load_type ? 'selected' : ''}>—</option>
                            <option value="TOTAL" ${lane.protein_load_type === 'TOTAL' ? 'selected' : ''}>Total</option>
                            <option value="POI" ${lane.protein_load_type === 'POI' ? 'selected' : ''}>POI</option>
                            <option value="HOST_CELL" ${lane.protein_load_type === 'HOST_CELL' ? 'selected' : ''}>HCP</option>
                            <option value="OTHER" ${lane.protein_load_type === 'OTHER' ? 'selected' : ''}>Other</option>
                        </select>
                    </td>
                    <td class="sample-cell">
                        <div class="sample-link ${!lane.sample_name ? 'sample-link-empty' : ''}"
                             onclick="window.gelViewer._openSampleSelector(${lane.id})">
                            <i class="bi bi-${lane.sample_name ? 'link-45deg' : 'plus-circle'}"></i>
                            <span>${escapeHtml(lane.sample_name || 'Link sample...')}</span>
                        </div>
                    </td>
                `;

                // Add change handlers for selects (immediate)
                row.querySelectorAll('select').forEach(select => {
                    select.addEventListener('change', (e) => {
                        this._handleTableCellChange(lane.id, e.target);
                    });
                });

                // Use debounced 'input' event for text/number inputs
                row.querySelectorAll('input').forEach(input => {
                    let debounceTimer;
                    input.addEventListener('input', (e) => {
                        clearTimeout(debounceTimer);
                        debounceTimer = setTimeout(() => {
                            this._handleTableCellChange(lane.id, e.target, true);
                        }, 300);
                    });
                    // Also handle blur for immediate update when leaving field
                    input.addEventListener('blur', (e) => {
                        clearTimeout(debounceTimer);
                        this._handleTableCellChange(lane.id, e.target, true);
                    });
                });

                // Highlight row on click (but not when clicking inputs/buttons)
                row.addEventListener('click', (e) => {
                    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' ||
                        e.target.closest('.sample-link')) return;
                    tbody.querySelectorAll('tr').forEach(r => r.classList.remove('selected'));
                    row.classList.add('selected');
                    this._selectAnnotation('lane', lane.id);
                });

                tbody.appendChild(row);
            }
        }

        /**
         * Handle changes in table cells.
         * @param {number|string} laneId - Lane ID
         * @param {HTMLElement} input - The input/select element
         * @param {boolean} silent - If true, suppress the "Lane updated" message
         */
        _handleTableCellChange(laneId, input, silent = false) {
            const field = input.dataset.field;
            let value = input.value;

            // Parse value based on field type
            if (field === 'is_reduced') {
                value = value === '' ? null : value === 'true';
            } else if (field === 'protein_load_ug') {
                value = value === '' ? null : parseFloat(value);
            }

            // Update lane
            const lane = this.lanes.get(laneId);
            if (lane) {
                lane[field] = value;
                this._updateLaneFromTable(laneId, { [field]: value }, silent);

                // Sync with properties panel if this lane is selected
                if (this.selectedType === 'lane' && this.selectedId === laneId) {
                    this._syncPropertiesField(field, value);
                }
            }
        }

        /**
         * Update lane from table (variant of _updateLane with optional silent mode).
         */
        _updateLaneFromTable(id, data, silent = false) {
            const lane = this.lanes.get(id);
            if (!lane) return;

            // Update local data
            Object.assign(lane, data);

            // Update display name if lane type changed
            if (data.lane_type) {
                lane.lane_type_display = this._getLaneTypeDisplay(data.lane_type);

                // Update SVG element class for color coding
                const element = this.svg.findOne(`#lane-${id}`);
                if (element) {
                    element.removeClass('sample').removeClass('ladder')
                           .removeClass('control').removeClass('empty');
                    element.addClass(data.lane_type.toLowerCase());
                }
            }

            // Track as updated
            if (!lane._isNew) {
                const existingUpdates = this.pendingChanges.lanes.updated.get(id) || {};
                this.pendingChanges.lanes.updated.set(id, { ...existingUpdates, ...data });
            } else {
                const createData = this.pendingChanges.lanes.created.get(id);
                if (createData) {
                    Object.assign(createData, data);
                }
            }

            // Mark dirty and save to localStorage
            this._markDirty();
            this._saveToLocalStorage();

            // Only show message if not silent
            if (!silent) {
                this._showMessage('Lane updated (unsaved)');
            }
        }

        // =====================================================================
        // Sample Selector Modal
        // =====================================================================

        /**
         * Open the sample selector modal for a lane.
         */
        _openSampleSelector(laneId) {
            this.sampleSelectorLaneId = laneId;

            const backdrop = document.getElementById('sample-modal');
            if (backdrop) {
                backdrop.classList.add('open');

                // Load filter options
                this._loadFilterOptions();

                // Focus search input
                setTimeout(() => {
                    const searchInput = document.getElementById('sample-search-input');
                    if (searchInput) searchInput.focus();
                }, 100);
            }
        }

        /**
         * Close the sample selector modal.
         */
        _closeSampleSelector() {
            const backdrop = document.getElementById('sample-modal');
            if (backdrop) {
                backdrop.classList.remove('open');
            }

            this.sampleSelectorLaneId = null;

            // Clear search and results
            const searchInput = document.getElementById('sample-search-input');
            const results = document.getElementById('sample-results');
            if (searchInput) searchInput.value = '';
            if (results) results.innerHTML = '<div class="gv-sample-results-empty"><i class="bi bi-search"></i>Search for samples above</div>';
        }

        /**
         * Check if sample selector is open.
         */
        _isSampleSelectorOpen() {
            const backdrop = document.getElementById('sample-modal');
            return backdrop && backdrop.classList.contains('open');
        }

        /**
         * Load filter options (drug substances and sheets).
         */
        async _loadFilterOptions() {
            try {
                const response = await fetch('/api/samples/filter-options/');
                if (!response.ok) return;

                const data = await response.json();

                // Populate drug substance filter
                const dsFilter = document.getElementById('sample-filter-ds');
                if (dsFilter && data.drug_substances) {
                    dsFilter.innerHTML = '<option value="">All Drug Substances</option>';
                    data.drug_substances.forEach(ds => {
                        // API returns shortname and fullname, use shortname (fallback to fullname)
                        const displayName = ds.shortname || ds.fullname || `DS ${ds.id}`;
                        dsFilter.innerHTML += `<option value="${ds.id}">${escapeHtml(displayName)}</option>`;
                    });
                }

                // Populate sheet filter
                const sheetFilter = document.getElementById('sample-filter-sheet');
                if (sheetFilter && data.sheets) {
                    sheetFilter.innerHTML = '<option value="">All Process Sheets</option>';
                    data.sheets.forEach(sheet => {
                        // Include drug substance context if available
                        const displayName = sheet.drug_substance
                            ? `${sheet.name} (${sheet.drug_substance})`
                            : sheet.name;
                        sheetFilter.innerHTML += `<option value="${sheet.id}">${escapeHtml(displayName)}</option>`;
                    });
                }
            } catch (error) {
                console.error('Error loading filter options:', error);
            }
        }

        /**
         * Search for samples.
         */
        async _searchSamples() {
            const searchInput = document.getElementById('sample-search-input');
            const dsFilter = document.getElementById('sample-filter-ds');
            const sheetFilter = document.getElementById('sample-filter-sheet');
            const results = document.getElementById('sample-results');

            if (!results) return;

            const query = searchInput ? searchInput.value.trim() : '';
            const dsId = dsFilter ? dsFilter.value : '';
            const sheetId = sheetFilter ? sheetFilter.value : '';

            // Show loading spinner
            results.innerHTML = `
                <div class="gv-sample-loading">
                    <div class="gv-sample-loading-spinner"></div>
                    <p>Searching samples...</p>
                </div>
            `;

            try {
                const params = new URLSearchParams();
                if (query) params.append('q', query);
                if (dsId) params.append('ds', dsId);
                if (sheetId) params.append('sheet', sheetId);

                const response = await fetch(`/api/samples/search/?${params}`);
                if (!response.ok) throw new Error('Search failed');

                const data = await response.json();

                if (data.samples.length === 0) {
                    results.innerHTML = `
                        <div class="gv-sample-results-empty">
                            <i class="bi bi-inbox"></i>
                            <p>No samples found matching your criteria</p>
                        </div>
                    `;
                    return;
                }

                results.innerHTML = '';
                data.samples.forEach(sample => {
                    const item = document.createElement('div');
                    item.className = 'gv-sample-item';
                    item.dataset.sampleId = sample.id;
                    item.dataset.sampleName = sample.sample_id;
                    item.innerHTML = `
                        <div class="gv-sample-item-radio"></div>
                        <div class="gv-sample-item-content">
                            <div class="gv-sample-item-id">${escapeHtml(sample.sample_id)}</div>
                            <div class="gv-sample-item-meta">${escapeHtml(sample.display)}</div>
                        </div>
                    `;
                    item.addEventListener('click', () => {
                        results.querySelectorAll('.gv-sample-item').forEach(i => i.classList.remove('selected'));
                        item.classList.add('selected');
                    });
                    results.appendChild(item);
                });
            } catch (error) {
                console.error('Error searching samples:', error);
                results.innerHTML = `
                    <div class="gv-sample-results-empty">
                        <i class="bi bi-exclamation-triangle"></i>
                        <p>Error searching samples. Please try again.</p>
                    </div>
                `;
            }
        }

        /**
         * Confirm sample selection.
         */
        _confirmSampleSelection() {
            const selected = document.querySelector('#sample-results .gv-sample-item.selected');
            const customInput = document.getElementById('sample-custom-input');

            if (!this.sampleSelectorLaneId) return;

            let sampleName = '';
            let processSampleId = null;

            if (selected) {
                // ProcessSample selected
                processSampleId = parseInt(selected.dataset.sampleId);
                sampleName = selected.dataset.sampleName || selected.querySelector('.gv-sample-item-id').textContent;
            } else if (customInput && customInput.value.trim()) {
                // Free text sample name
                sampleName = customInput.value.trim();
            } else {
                // Nothing selected
                this._showMessage('Please select a sample or enter a custom name.');
                return;
            }

            // Update lane data
            this._updateLane(this.sampleSelectorLaneId, {
                process_sample_id: processSampleId,
                sample_name: processSampleId ? '' : sampleName  // Clear free text if ProcessSample selected
            });

            // Update local lane object for display
            const lane = this.lanes.get(this.sampleSelectorLaneId);
            if (lane) {
                lane.process_sample_id = processSampleId;
                lane.sample_name = sampleName;
            }

            // Update table sample-link if visible
            const sampleLink = document.querySelector(`tr[data-lane-id="${this.sampleSelectorLaneId}"] .sample-link`);
            if (sampleLink) {
                sampleLink.innerHTML = `
                    <i class="bi bi-link-45deg"></i>
                    <span>${escapeHtml(sampleName)}</span>
                `;
                sampleLink.classList.remove('sample-link-empty');
            }

            // Update properties panel if this lane is selected
            if (this.selectedType === 'lane' && this.selectedId === this.sampleSelectorLaneId) {
                const propSampleName = document.getElementById('prop-sample-name');
                if (propSampleName) propSampleName.value = sampleName;
            }

            this._showMessage(`Sample "${sampleName}" linked to lane.`);
            this._closeSampleSelector();
        }

        // =====================================================================
        // Utilities
        // =====================================================================

        _getImagePoint(e) {
            const rect = this.canvasContainer.getBoundingClientRect();
            return {
                x: (e.clientX - rect.left) / this.scale,
                y: (e.clientY - rect.top) / this.scale,
            };
        }
    }

    // Export to global
    global.GelViewer = GelViewer;

})(window);
