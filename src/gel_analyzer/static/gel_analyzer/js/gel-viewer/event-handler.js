/**
 * EventHandler - DOM Event Management for GelViewer
 *
 * Handles mouse events, keyboard shortcuts, and wheel zoom.
 * Delegates to tools and viewport for actual operations.
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    /**
     * EventHandler Class
     */
    class EventHandler {
        /**
         * @param {Object} options
         * @param {HTMLElement} options.viewer - The viewer container element
         * @param {HTMLElement} options.canvasContainer - Container for coordinate calculations
         * @param {EventBus} options.eventBus - EventBus instance
         * @param {ToolManager} options.toolManager - ToolManager instance
         * @param {Viewport} options.viewport - Viewport instance
         * @param {StateManager} options.stateManager - StateManager instance
         * @param {Function} options.getScale - Function to get current scale
         * @param {boolean} options.isEditable - Whether editing is allowed
         */
        constructor(options) {
            this.viewer = options.viewer;
            this.canvasContainer = options.canvasContainer;
            this.eventBus = options.eventBus;
            this.toolManager = options.toolManager;
            this.viewport = options.viewport;
            this.stateManager = options.stateManager;
            this.getScale = options.getScale || (() => 1);
            this.isEditable = options.isEditable !== false;

            // External callbacks
            this.onDeleteSelected = options.onDeleteSelected;
            this.onToggleTablePanel = options.onToggleTablePanel;
            this.onToggleBandTablePanel = options.onToggleBandTablePanel;
            this.onToggleAdjustmentsPanel = options.onToggleAdjustmentsPanel;
            this.onHideTablePanel = options.onHideTablePanel;
            this.onHideBandTablePanel = options.onHideBandTablePanel;
            this.onHideAdjustmentsPanel = options.onHideAdjustmentsPanel;
            this.onHideContextMenu = options.onHideContextMenu;
            this.onCancelDrawing = options.onCancelDrawing;
            this.onDeselect = options.onDeselect;
            this.onFitToView = options.onFitToView;
            this.onZoom = options.onZoom;
            this.getHandlesGroup = options.getHandlesGroup;
            this.onToggleBackgrounds = options.onToggleBackgrounds;
            this.onToggleDetectionPanel = options.onToggleDetectionPanel;
            this.onToggleCV2DetectionPanel = options.onToggleCV2DetectionPanel;
            this.onToggleCalibrationPanel = options.onToggleCalibrationPanel;
            this.onToggleElectropherogramPanel = options.onToggleElectropherogramPanel;
            this.onToggleProfileDetectionPanel = options.onToggleProfileDetectionPanel;
            this.onHideDetectionPanel = options.onHideDetectionPanel;
            this.onHideCV2DetectionPanel = options.onHideCV2DetectionPanel;
            this.onHideCalibrationPanel = options.onHideCalibrationPanel;
            this.onHideElectropherogramPanel = options.onHideElectropherogramPanel;

            // State checks
            this.isTablePanelVisible = options.isTablePanelVisible || (() => false);
            this.isBandTablePanelVisible = options.isBandTablePanelVisible || (() => false);
            this.isAdjustmentsPanelVisible = options.isAdjustmentsPanelVisible || (() => false);
            this.isDetectionPanelVisible = options.isDetectionPanelVisible || (() => false);
            this.isCV2DetectionPanelVisible = options.isCV2DetectionPanelVisible || (() => false);
            this.isCalibrationPanelVisible = options.isCalibrationPanelVisible || (() => false);
            this.isElectropherogramPanelVisible = options.isElectropherogramPanelVisible || (() => false);
            this.getSelectedAnnotation = options.getSelectedAnnotation || (() => null);

            // Throttling
            this._lastWheelTime = 0;

            // Bind methods
            this._onMouseDown = this._onMouseDown.bind(this);
            this._onMouseMove = this._onMouseMove.bind(this);
            this._onMouseUp = this._onMouseUp.bind(this);
            this._onMouseLeave = this._onMouseLeave.bind(this);
            this._onDoubleClick = this._onDoubleClick.bind(this);
            this._onWheel = this._onWheel.bind(this);
            this._onKeyDown = this._onKeyDown.bind(this);
            this._onContextMenu = this._onContextMenu.bind(this);
        }

        /**
         * Setup all event listeners.
         */
        setup() {
            if (!this.viewer) {
                console.warn('EventHandler: viewer element not available, skipping mouse event setup');
                // Still set up keyboard shortcuts even if viewer is missing
                document.addEventListener('keydown', this._onKeyDown);
                return;
            }

            // Mouse events on viewer
            this.viewer.addEventListener('mousedown', this._onMouseDown);
            this.viewer.addEventListener('mousemove', this._onMouseMove);
            this.viewer.addEventListener('mouseup', this._onMouseUp);
            this.viewer.addEventListener('mouseleave', this._onMouseLeave);
            this.viewer.addEventListener('dblclick', this._onDoubleClick);
            this.viewer.addEventListener('wheel', this._onWheel, { passive: false });
            this.viewer.addEventListener('contextmenu', this._onContextMenu);

            // Keyboard shortcuts (global)
            document.addEventListener('keydown', this._onKeyDown);
        }

        /**
         * Remove all event listeners.
         */
        destroy() {
            if (this.viewer) {
                this.viewer.removeEventListener('mousedown', this._onMouseDown);
                this.viewer.removeEventListener('mousemove', this._onMouseMove);
                this.viewer.removeEventListener('mouseup', this._onMouseUp);
                this.viewer.removeEventListener('mouseleave', this._onMouseLeave);
                this.viewer.removeEventListener('dblclick', this._onDoubleClick);
                this.viewer.removeEventListener('wheel', this._onWheel);
                this.viewer.removeEventListener('contextmenu', this._onContextMenu);
            }
            document.removeEventListener('keydown', this._onKeyDown);
        }

        /**
         * Convert screen coordinates to image coordinates.
         * @param {MouseEvent} e - Mouse event
         * @returns {Object} {x, y} in image coordinates
         */
        getImagePoint(e) {
            if (!this.canvasContainer) {
                return { x: 0, y: 0 };
            }
            const rect = this.canvasContainer.getBoundingClientRect();
            const scale = this.getScale();
            return {
                x: (e.clientX - rect.left) / scale,
                y: (e.clientY - rect.top) / scale,
            };
        }

        /**
         * Update coordinate display in status bar.
         * @param {Object} point - {x, y} coordinates
         */
        _updateCoordinates(point) {
            const coordDisplay = document.querySelector('.gv-coordinates');
            if (coordDisplay) {
                coordDisplay.textContent = `${Math.round(point.x)}, ${Math.round(point.y)}`;
            }
        }

        // =====================================================================
        // Mouse Event Handlers
        // =====================================================================

        _onMouseDown(e) {
            if (e.button !== 0) return; // Only left click

            const point = this.getImagePoint(e);
            const tool = this.toolManager.getActiveTool();

            if (tool && tool.onMouseDown) {
                tool.onMouseDown(point, e);
            }
        }

        _onMouseMove(e) {
            const point = this.getImagePoint(e);
            const tool = this.toolManager.getActiveTool();

            if (tool && tool.onMouseMove) {
                tool.onMouseMove(point, e);
            }

            // Always update coordinates
            this._updateCoordinates(point);
        }

        _onMouseUp(e) {
            const point = this.getImagePoint(e);
            const tool = this.toolManager.getActiveTool();

            if (tool && tool.onMouseUp) {
                tool.onMouseUp(point, e);
            }
        }

        _onMouseLeave(e) {
            // End pan if active
            if (this.viewport.isPanning) {
                this.viewport.endPan();
            }
        }

        _onDoubleClick(e) {
            const point = this.getImagePoint(e);
            const tool = this.toolManager.getActiveTool();

            if (tool && tool.onDoubleClick) {
                tool.onDoubleClick(point, e);
            }
        }

        _onWheel(e) {
            e.preventDefault();

            // Throttle: max 1 zoom operation per 50ms
            const now = Date.now();
            if (this._lastWheelTime && now - this._lastWheelTime < 50) {
                return;
            }
            this._lastWheelTime = now;

            const point = this.getImagePoint(e);
            // Reduced sensitivity: 5% per tick
            const delta = e.deltaY > 0 ? 0.95 : 1.05;

            if (this.onZoom) {
                this.onZoom(delta, point);
            }
        }

        _onContextMenu(e) {
            e.preventDefault();
            this.eventBus.emit(Events.CONTEXT_MENU_REQUESTED, {
                x: e.clientX,
                y: e.clientY,
                originalEvent: e
            });
        }

        // =====================================================================
        // Keyboard Shortcuts
        // =====================================================================

        _onKeyDown(e) {
            // Don't handle if typing in an input
            if (e.target.tagName === 'INPUT' ||
                e.target.tagName === 'TEXTAREA' ||
                e.target.tagName === 'SELECT') {
                return;
            }

            const key = e.key.toLowerCase();

            // Ctrl+S: Save
            if ((e.ctrlKey || e.metaKey) && key === 's') {
                e.preventDefault();
                this.eventBus.emit(Events.SAVE_REQUESTED);
                return;
            }

            switch (key) {
                case 'v':
                    // Shift+V: Toggle CV2 Vision Detection panel - requires lanes
                    if (e.shiftKey && this.onToggleCV2DetectionPanel) {
                        e.preventDefault();
                        if (this.stateManager.getLaneCount() > 0) {
                            this.onToggleCV2DetectionPanel();
                        } else {
                            this._showShortcutMessage('Create lanes first');
                        }
                    } else if (!e.shiftKey) {
                        this.toolManager.setTool('select');
                    }
                    break;

                case 'h':
                    this.toolManager.setTool('pan');
                    break;

                case 'l':
                    // Rectangle lane (default)
                    if (this.isEditable) {
                        this.toolManager.setLaneShape('RECTANGLE');
                    }
                    break;

                case 'q':
                    // Quadrilateral lane
                    if (this.isEditable) {
                        this.toolManager.setLaneShape('QUADRILATERAL');
                    }
                    break;

                case 'p':
                    // Shift+P: Toggle Profile Peak Detection panel
                    if (e.shiftKey && this.onToggleProfileDetectionPanel) {
                        e.preventDefault();
                        if (this.stateManager.getLaneCount() > 0) {
                            this.onToggleProfileDetectionPanel();
                        } else {
                            this._showShortcutMessage('Create lanes first');
                        }
                    } else if (this.isEditable && !e.shiftKey) {
                        // P: Polygon lane
                        this.toolManager.setLaneShape('POLYGON');
                    }
                    break;

                case 'b':
                    // Band tool requires lanes
                    if (this.isEditable) {
                        if (this.stateManager.getLaneCount() > 0) {
                            this.toolManager.setTool('band');
                        } else {
                            this._showShortcutMessage('Create a lane first');
                        }
                    }
                    break;

                case 's':
                    // Split tool (without Ctrl) - requires selected band
                    if (this.isEditable && !e.ctrlKey && !e.metaKey) {
                        const selection = this.getSelectedAnnotation();
                        if (selection && selection.type === 'band') {
                            this.toolManager.setTool('split');
                        } else {
                            this._showShortcutMessage('Select a band first');
                        }
                    }
                    break;

                case 't':
                    // Toggle lane table panel
                    if (this.onToggleTablePanel) {
                        this.onToggleTablePanel();
                    }
                    break;

                case 'e':
                    // Toggle band table panel (requires lane selected)
                    if (this.onToggleBandTablePanel) {
                        this.onToggleBandTablePanel();
                    }
                    break;

                case 'a':
                    // Toggle adjustments panel
                    if (this.onToggleAdjustmentsPanel) {
                        this.onToggleAdjustmentsPanel();
                    }
                    break;

                case 'f':
                    // Toggle annotation fills/backgrounds
                    if (this.onToggleBackgrounds) {
                        this.onToggleBackgrounds();
                    }
                    break;

                case 'd':
                    // Shift+D: Toggle detection panel - requires lanes
                    if (e.shiftKey && this.onToggleDetectionPanel) {
                        e.preventDefault();
                        if (this.stateManager.getLaneCount() > 0) {
                            this.onToggleDetectionPanel();
                        } else {
                            this._showShortcutMessage('Create lanes first');
                        }
                    }
                    break;

                case 'c':
                    // C: Toggle calibration panel - requires ladder lanes with bands
                    if (this.onToggleCalibrationPanel) {
                        const lanesMap = this.stateManager.getAllLanes();
                        const lanes = Array.from(lanesMap.values());
                        const ladderLanesWithBands = lanes.filter(
                            l => l.lane_type === 'LADDER' && l.bands && l.bands.length > 0
                        );
                        if (ladderLanesWithBands.length > 0) {
                            this.onToggleCalibrationPanel();
                        } else {
                            const ladderLanes = lanes.filter(l => l.lane_type === 'LADDER');
                            if (ladderLanes.length === 0) {
                                this._showShortcutMessage('Add Ladder lanes first');
                            } else {
                                this._showShortcutMessage('Add bands to Ladder lanes first');
                            }
                        }
                    }
                    break;

                case 'm':
                    // M: Toggle MW calibration lines - requires calibration
                    if (this.onToggleMWLines) {
                        // Check calibration via window.gelViewer since EventHandler doesn't have calibrationData
                        const isCalibrated = window.gelViewer?.calibrationData?.is_calibrated;
                        if (isCalibrated) {
                            this.onToggleMWLines();
                        } else {
                            this._showShortcutMessage('Calibrate MW first');
                        }
                    }
                    break;

                case 'g':
                    // G: Toggle electropherogram panel - requires lanes
                    if (this.onToggleElectropherogramPanel) {
                        if (this.stateManager.getLaneCount() > 0) {
                            this.onToggleElectropherogramPanel();
                        } else {
                            this._showShortcutMessage('Create lanes first');
                        }
                    }
                    break;

                case 'delete':
                case 'backspace':
                    if (this.isEditable && this.getSelectedAnnotation()) {
                        e.preventDefault();
                        if (this.onDeleteSelected) {
                            this.onDeleteSelected();
                        }
                    }
                    break;

                case 'enter':
                    // Finish drawing with Enter key
                    this._handleEnterKey(e);
                    break;

                case 'escape':
                    this._handleEscapeKey();
                    break;

                case '=':
                case '+':
                    if (this.onZoom) {
                        this.onZoom(1.2);
                    }
                    break;

                case '-':
                    if (this.onZoom) {
                        this.onZoom(0.8);
                    }
                    break;

                case '0':
                    if (this.onFitToView) {
                        this.onFitToView();
                    }
                    break;
            }
        }

        /**
         * Handle Enter key to finish drawing operations.
         * @param {KeyboardEvent} e
         */
        _handleEnterKey(e) {
            const tool = this.toolManager.getActiveTool();
            const toolName = this.toolManager.getTool();

            if (toolName === 'band' && tool && tool.points && tool.points.length >= 3) {
                e.preventDefault();
                const result = tool.finish();
                if (result) {
                    this.eventBus.emit(Events.BAND_DRAW_FINISHED, result);
                }
            } else if (toolName === 'lane') {
                const shape = this.toolManager.getLaneShape();
                if (shape === 'POLYGON' && tool && tool.shapePoints && tool.shapePoints.length >= 3) {
                    e.preventDefault();
                    const result = tool.finishPolygon();
                    if (result) {
                        this.eventBus.emit(Events.LANE_DRAW_FINISHED, result);
                    }
                }
            }
        }

        /**
         * Handle Escape key to close panels and cancel operations.
         */
        _handleEscapeKey() {
            // Close panels in priority order
            if (this.isDetectionPanelVisible()) {
                if (this.onHideDetectionPanel) this.onHideDetectionPanel();
            } else if (this.isCV2DetectionPanelVisible()) {
                if (this.onHideCV2DetectionPanel) this.onHideCV2DetectionPanel();
            } else if (this.isCalibrationPanelVisible()) {
                if (this.onHideCalibrationPanel) this.onHideCalibrationPanel();
            } else if (this.isBandTablePanelVisible()) {
                if (this.onHideBandTablePanel) this.onHideBandTablePanel();
            } else if (this.isTablePanelVisible()) {
                if (this.onHideTablePanel) this.onHideTablePanel();
            } else if (this.isAdjustmentsPanelVisible()) {
                if (this.onHideAdjustmentsPanel) this.onHideAdjustmentsPanel();
            } else {
                // Cancel current operations
                if (this.onHideContextMenu) this.onHideContextMenu();
                if (this.onCancelDrawing) this.onCancelDrawing();
                if (this.onDeselect) this.onDeselect();

                // Clear handles
                const handlesGroup = this.getHandlesGroup ? this.getHandlesGroup() : null;
                if (handlesGroup) {
                    handlesGroup.clear();
                }
            }
        }

        /**
         * Show a brief feedback message for shortcut prerequisites.
         * @param {string} message - Message to display
         */
        _showShortcutMessage(message) {
            // Use the global gelViewer's message system if available
            if (window.gelViewer && typeof window.gelViewer._showMessage === 'function') {
                window.gelViewer._showMessage(message);
            } else {
                console.log('Shortcut blocked:', message);
            }
        }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.EventHandler = EventHandler;

})(window);
