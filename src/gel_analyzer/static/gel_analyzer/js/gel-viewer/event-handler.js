/**
 * EventHandler - DOM Event Management for GelViewer
 *
 * Handles mouse events, keyboard shortcuts, and wheel zoom.
 * Delegates to tools and viewport for actual operations.
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    // Touch: a finger held this long without moving more than this is a long-press, the right-click of a touch screen.
    const LONG_PRESS_MS = 500;
    const LONG_PRESS_SLOP_PX = 10;

    // A lane's resize handles (corner-handles.js, the box handles of Resize Lane): a press there is a drag, held as
    // long as the user likes; it never opens the menu.
    const HANDLE = '.gv-corner-handle, .gv-handle';

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
            this.onToggleBandModelPanel = options.onToggleBandModelPanel;
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
            this.isContextMenuVisible = options.isContextMenuVisible || (() => false);

            // Throttling
            this._lastWheelTime = 0;

            // Context menu: the long-press under way ({x, y, timer, fired}), and until when a contextmenu event is
            // the one that follows Shift+F10 / the Menu key.
            this._longPress = null;
            this._keyboardMenuUntil = 0;

            // Bind methods
            this._onMouseDown = this._onMouseDown.bind(this);
            this._onMouseMove = this._onMouseMove.bind(this);
            this._onMouseUp = this._onMouseUp.bind(this);
            this._onMouseLeave = this._onMouseLeave.bind(this);
            this._onDoubleClick = this._onDoubleClick.bind(this);
            this._onWheel = this._onWheel.bind(this);
            this._onKeyDown = this._onKeyDown.bind(this);
            this._onContextMenu = this._onContextMenu.bind(this);
            this._onDocumentContextMenu = this._onDocumentContextMenu.bind(this);
            this._onDocumentPointerDown = this._onDocumentPointerDown.bind(this);
            this._onTouchStart = this._onTouchStart.bind(this);
            this._onTouchMove = this._onTouchMove.bind(this);
            this._onTouchEnd = this._onTouchEnd.bind(this);
            this._cancelLongPress = this._cancelLongPress.bind(this);
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
            this.viewer.addEventListener('touchstart', this._onTouchStart, { passive: true });
            document.addEventListener('contextmenu', this._onDocumentContextMenu, true);
            document.addEventListener('pointerdown', this._onDocumentPointerDown, true);

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
                this.viewer.removeEventListener('touchstart', this._onTouchStart);
                document.removeEventListener('contextmenu', this._onDocumentContextMenu, true);
                document.removeEventListener('pointerdown', this._onDocumentPointerDown, true);
            }
            this._cancelLongPress();
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
            if (e.target instanceof Element && e.target.closest(HANDLE)) return;
            const press = this._longPress;
            if (press) {
                // A long-press the browser reports as a contextmenu too (Chrome on Android): one menu, whichever
                // comes first.
                clearTimeout(press.timer);
                if (press.fired) return;
            }
            this._requestContextMenuAt(e.clientX, e.clientY);
            if (press) press.fired = this.isContextMenuVisible();
        }

        /**
         * The menu of what is under this screen point (GelViewerApp picks the band, else the lane, there).
         * @param {number} clientX
         * @param {number} clientY
         */
        _requestContextMenuAt(clientX, clientY) {
            this.eventBus.emit(Events.CONTEXT_MENU_REQUESTED, {
                x: clientX,
                y: clientY,
                point: this.getImagePoint({ clientX, clientY }),
            });
        }

        /**
         * The contextmenu event the browser sends after Shift+F10 / the Menu key (on Windows the Menu key's comes on
         * keyup, whatever the keydown did) is the keyboard's, already answered: no browser menu over ours, and not
         * a right-click on the focused element. Document, capture phase: it runs before the viewer's listener.
         */
        _onDocumentContextMenu(e) {
            if (performance.now() > this._keyboardMenuUntil) return;
            this._keyboardMenuUntil = 0;
            e.preventDefault();
            e.stopPropagation();
        }

        /**
         * A pointer pressed after the key: the next contextmenu is a right-click or a long-press, not the key's (a
         * browser that sends none after a prevented keydown, Firefox, would otherwise lose a right-click for 1 s).
         */
        _onDocumentPointerDown() {
            this._keyboardMenuUntil = 0;
        }

        // Touch: a long-press opens the menu like a right-click. A finger that moves, lifts or is joined by another
        // before LONG_PRESS_MS is a tap, a scroll or a pinch. The rest of a touch is followed on its touchstart target:
        // touch events keep going there even once it is off the page (a corner handle redrawn under the finger), where
        // they never reach the viewer.

        _onTouchStart(e) {
            this._cancelLongPress();
            if (e.touches.length !== 1) return;
            if (e.target instanceof Element && e.target.closest(HANDLE)) return;
            const { clientX, clientY } = e.touches[0];
            const press = { x: clientX, y: clientY, fired: false, timer: 0, target: e.target };
            press.target.addEventListener('touchmove', this._onTouchMove, { passive: true });
            press.target.addEventListener('touchend', this._onTouchEnd);
            press.target.addEventListener('touchcancel', this._cancelLongPress);
            press.timer = setTimeout(() => {
                if (this._longPress !== press) return;
                this._requestContextMenuAt(clientX, clientY);
                press.fired = this.isContextMenuVisible();
            }, LONG_PRESS_MS);
            this._longPress = press;
        }

        _onTouchMove(e) {
            const press = this._longPress;
            if (!press || press.fired) return;
            const touch = e.touches[0];
            if (e.touches.length !== 1
                || Math.hypot(touch.clientX - press.x, touch.clientY - press.y) > LONG_PRESS_SLOP_PX) {
                this._cancelLongPress();
            }
        }

        _onTouchEnd(e) {
            const press = this._longPress;
            this._cancelLongPress();
            // The finger lifting off a long-press that opened the menu: no mouse events, no click. Its mousedown
            // would close the menu again, its click act on what is under it.
            if (press && press.fired && e.cancelable) e.preventDefault();
        }

        _cancelLongPress() {
            const press = this._longPress;
            if (!press) return;
            clearTimeout(press.timer);
            press.target.removeEventListener('touchmove', this._onTouchMove);
            press.target.removeEventListener('touchend', this._onTouchEnd);
            press.target.removeEventListener('touchcancel', this._cancelLongPress);
            this._longPress = null;
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

            // The character shortcuts are bare keys, Shift allowed (Shift+Y / D / V / P). With Ctrl, Cmd or Alt a
            // character is the browser's: Ctrl+C copies (it opened the calibration), Ctrl+A selects, Ctrl+F finds,
            // Ctrl+0 / + / - zoom the page. Delete, Backspace, Enter and Escape keep their meaning with a modifier.
            if ((e.ctrlKey || e.metaKey || e.altKey) && key.length === 1) {
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
                    // P: Polygon lane (Shift+P is free: its Profile Peak panel is gone)
                    if (this.isEditable && !e.shiftKey) {
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

                case 'y':
                    // Shift+Y: Toggle the band model panel (YOLO bands, after the lanes) - requires lanes
                    if (e.shiftKey && this.onToggleBandModelPanel) {
                        e.preventDefault();
                        if (this.stateManager.getLaneCount() > 0) {
                            this.onToggleBandModelPanel();
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

                case 'contextmenu':
                case 'f10':
                    // The Menu key and Shift+F10 (F10 alone, or with Ctrl / Alt, is the browser's): the keyboard's
                    // right-click, on the selection. Its contextmenu event, sent after, is this same request.
                    if (key === 'f10' && !(e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey)) break;
                    e.preventDefault();
                    this._keyboardMenuUntil = performance.now() + 1000;
                    if (e.repeat) break;
                    if (this.getSelectedAnnotation()) {
                        this.eventBus.emit(Events.CONTEXT_MENU_REQUESTED, { keyboard: true });
                    } else {
                        this._showShortcutMessage('Select a lane or band first');
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
                document.querySelector('.gv-tool-dropdown.open')?.classList.remove('open');
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
