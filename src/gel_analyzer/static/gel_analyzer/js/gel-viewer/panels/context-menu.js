/**
 * ContextMenu - Right-Click Context Menu for GelViewer
 *
 * Handles context menu display and action dispatching
 * for lanes and bands.
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    /**
     * ContextMenu Class
     * Manages the right-click context menu.
     */
    class ContextMenu {
        /**
         * Create a ContextMenu instance.
         * @param {Object} options - Configuration options
         * @param {EventBus} options.eventBus - EventBus instance
         * @param {Function} options.getSelection - Function returning current selection {type, id}
         * @param {boolean} options.isEditable - Whether annotations can be edited
         * @param {Function} options.showMessage - Function to display messages
         * @param {Object} options.handlers - Action handlers (onEdit, onDelete, onSetType, etc.)
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            // Support both getSelection and getSelectedAnnotation callbacks
            this.getSelection = options.getSelection || options.getSelectedAnnotation || (() => null);
            this.isEditable = options.isEditable !== false;
            this.showMessage = options.showMessage || console.log;

            // Capture state + API hooks so the context menu can:
            // - look up the band that's currently selected (for the
            //   calibration-only "Set calibration value..." button visibility)
            // - know the active quantification calibration's unit (so the
            //   prompt label adapts to the locked unit)
            this._stateManager = options.stateManager || null;
            this._apiClient = options.apiClient || null;
            this._activeCalibUnitCache = undefined;

            // Support handlers passed as object or as individual callbacks
            this.handlers = options.handlers || {};
            if (options.onDeleteLane) this.handlers.onDeleteLane = options.onDeleteLane;
            if (options.onDeleteBand) this.handlers.onDeleteBand = options.onDeleteBand;
            if (options.onUpdateLane) this.handlers.onUpdateLane = options.onUpdateLane;
            if (options.onUpdateBand) this.handlers.onUpdateBand = options.onUpdateBand;
            if (options.onStartResize) this.handlers.onStartResize = options.onStartResize;

            // DOM elements
            this.menu = document.getElementById('context-menu');

            this._setup();
        }

        /**
         * Setup event handlers.
         */
        _setup() {
            // Always attach document listener for outside clicks (mousedown is more reliable)
            document.addEventListener('mousedown', (e) => {
                // Skip if menu doesn't exist or isn't visible
                if (!this.menu || !this.isVisible()) return;

                // Check if click is outside the menu
                if (!this.menu.contains(e.target)) {
                    this.hide();
                }
            });

            // Close on Escape key
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.isVisible()) {
                    this.hide();
                }
            });

            if (!this.menu) return;

            this.menu.addEventListener('click', (e) => {
                const item = e.target.closest('.gv-context-menu-item');
                if (!item) return;

                e.stopPropagation();
                const action = item.dataset.action;
                const value = item.dataset.value;

                this._handleAction(action, value);
                this.hide();
            });
        }

        // =====================================================================
        // Show / Hide
        // =====================================================================

        /**
         * Handle contextmenu event.
         * @param {MouseEvent} e - Context menu event
         */
        onContextMenu(e) {
            e.preventDefault();

            const selection = this.getSelection();

            // Only show if something is selected and editable
            if (!selection || !this.isEditable) {
                this.hide();
                return;
            }

            this.show(e.clientX, e.clientY, selection.type);
        }

        /**
         * Show the context menu.
         * @param {number} x - X coordinate
         * @param {number} y - Y coordinate
         * @param {string} type - Selected annotation type ('lane' or 'band')
         */
        show(x, y, type) {
            if (!this.menu) return;

            // Hide all content sections, show the relevant one
            this.menu.querySelectorAll('.gv-context-menu-content').forEach(content => {
                content.classList.remove('visible');
            });

            const contentSection = this.menu.querySelector(
                `.gv-context-menu-content[data-type="${type}"]`
            );
            if (contentSection) {
                contentSection.classList.add('visible');
            }

            // Position menu within viewport
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

            this.menu.style.left = menuX + 'px';
            this.menu.style.top = menuY + 'px';
            this.menu.classList.add('visible');

            // Toggle "Set calibration value..." visibility — only useful when
            // the selected band is already a CALIBRATION point.
            this._updateCalibrationButton(type);

            this.eventBus.emit(Events.CONTEXT_MENU_SHOWN, { x: menuX, y: menuY, type });
        }

        /**
         * Toggle the visibility/label of the "Set calibration value..." item.
         * Visible only when a CALIBRATION band is selected; the label adapts
         * to the active calibration's unit (UG -> "Set load (ug)..." vs
         * UG_ML -> "Set concentration (ug/mL)...").
         */
        _updateCalibrationButton(type) {
            const item = this.menu.querySelector('#ctx-set-calib-value');
            if (!item) return;

            const sel = this.getSelection();
            const band = sel?.type === 'band' && this._stateManager
                ? this._stateManager.getBand(sel.id)
                : null;
            const isCalibBand = band?.band_type === 'CALIBRATION';
            item.style.display = isCalibBand ? '' : 'none';

            // Adapt label to the locked unit, if any.
            if (isCalibBand) {
                this._getActiveCalibUnit().then(unit => {
                    const label = item.querySelector('#ctx-set-calib-value-label');
                    if (!label) return;
                    if (unit === 'UG_ML') {
                        label.textContent = 'Set concentration (ug/mL)...';
                    } else if (unit === 'UG') {
                        label.textContent = 'Set load (ug)...';
                    } else {
                        label.textContent = 'Set calibration value...';
                    }
                });
            }
        }

        /**
         * Prompt the user for the calibration loaded amount + unit and PATCH
         * the band. When an active calibration exists the unit is fixed; we
         * skip the second prompt and reuse the locked unit.
         */
        async _promptCalibrationValue(bandId) {
            const amountStr = window.prompt('Enter loaded amount:');
            if (amountStr === null || amountStr === '') return;
            const amount = parseFloat(amountStr);
            if (!isFinite(amount) || amount < 0) {
                this.showMessage('Invalid amount');
                return;
            }

            const lockedUnit = await this._getActiveCalibUnit();
            let unit;
            if (lockedUnit) {
                unit = lockedUnit;
            } else {
                unit = window.prompt('Unit (UG or UG_ML):', 'UG');
                if (unit === null) return;
                if (!['UG', 'UG_ML'].includes(unit)) {
                    this.showMessage('Invalid unit');
                    return;
                }
            }

            const payload = {
                band_type: 'CALIBRATION',
                quant_point: { load_amount: amount, load_unit: unit },
            };

            // Prefer the v1 PATCH endpoint so the nested quant_point reaches
            // the BandSerializer; if no apiClient is available, fall back to
            // the existing onUpdateBand callback so at least local state
            // stays in sync.
            if (this._apiClient && typeof this._apiClient.patchBand === 'function') {
                try {
                    await this._apiClient.patchBand(bandId, payload);
                    if (this._stateManager) {
                        const band = this._stateManager.getBand(bandId);
                        if (band) {
                            band.band_type = 'CALIBRATION';
                            band.quant_point = payload.quant_point;
                        }
                    }
                    this.showMessage('Calibration value saved');
                } catch (err) {
                    this.showMessage(`Save failed: ${err.message || err}`);
                }
                return;
            }

            if (this.handlers.onUpdateBand) {
                this.handlers.onUpdateBand(bandId, payload);
            }
        }

        /** Cached fetch of the active quant calibration's unit. */
        async _getActiveCalibUnit() {
            if (this._activeCalibUnitCache !== undefined) {
                return this._activeCalibUnitCache;
            }
            if (!this._apiClient || !this._apiClient.analysisId) {
                this._activeCalibUnitCache = null;
                return null;
            }
            try {
                const resp = await this._apiClient.getActiveQuantification(
                    this._apiClient.analysisId
                );
                this._activeCalibUnitCache = resp?.active?.unit || null;
            } catch (err) {
                console.warn('Could not load active quantification:', err);
                this._activeCalibUnitCache = null;
            }
            return this._activeCalibUnitCache;
        }

        /**
         * Hide the context menu.
         */
        hide() {
            if (this.menu) {
                this.menu.classList.remove('visible');
            }
            this.eventBus.emit(Events.CONTEXT_MENU_HIDDEN);
        }

        /**
         * Check if menu is visible.
         * @returns {boolean}
         */
        isVisible() {
            return this.menu && this.menu.classList.contains('visible');
        }

        // =====================================================================
        // Action Handling
        // =====================================================================

        /**
         * Handle a context menu action.
         * @param {string} action - Action name
         * @param {string} [value] - Optional value
         */
        _handleAction(action, value) {
            const selection = this.getSelection();
            if (!selection) return;

            const { type, id } = selection;

            switch (action) {
                case 'edit-properties':
                    if (this.handlers.onEditProperties) {
                        this.handlers.onEditProperties(type, id);
                    }
                    break;

                case 'resize':
                    if (type === 'lane' && this.handlers.onStartResize) {
                        this.handlers.onStartResize(id);
                    }
                    break;

                case 'set-type':
                    if (type === 'lane' && value) {
                        if (this.handlers.onSetLaneType) {
                            this.handlers.onSetLaneType(id, value);
                        } else if (this.handlers.onUpdateLane) {
                            this.handlers.onUpdateLane(id, { lane_type: value });
                        }
                    }
                    break;

                case 'set-mw':
                    if (type === 'band') {
                        const mw = prompt('Enter molecular weight (kDa):');
                        if (mw !== null && mw !== '') {
                            const mwValue = parseFloat(mw);
                            if (!isNaN(mwValue) && this.handlers.onUpdateBand) {
                                this.handlers.onUpdateBand(id, { molecular_weight: mwValue });
                            }
                        }
                    }
                    break;

                case 'set-band-type':
                    if (type === 'band' && value) {
                        if (this.handlers.onSetBandType) {
                            this.handlers.onSetBandType(id, value);
                        } else if (this.handlers.onUpdateBand) {
                            this.handlers.onUpdateBand(id, { band_type: value });
                        }
                    }
                    break;

                case 'set-calibration-value':
                    if (type === 'band') {
                        this._promptCalibrationValue(id);
                    }
                    break;

                case 'delete':
                    if (this.handlers.onDelete) {
                        this.handlers.onDelete(type, id);
                    } else if (type === 'lane' && this.handlers.onDeleteLane) {
                        this.handlers.onDeleteLane(id);
                    } else if (type === 'band' && this.handlers.onDeleteBand) {
                        this.handlers.onDeleteBand(id);
                    }
                    break;

                default:
                    console.warn(`Unknown context menu action: ${action}`);
            }
        }

        // =====================================================================
        // Resize Handles
        // =====================================================================

        /**
         * Show resize handles for a lane.
         * @param {Object} lane - Lane data
         * @param {Object} svg - SVG.js instance
         * @param {Object} handlesGroup - SVG group for handles
         * @param {number} scale - Current zoom scale
         * @param {Function} onResize - Callback when resize is complete
         */
        showResizeHandles(lane, svg, handlesGroup, scale, onResize) {
            // Clear existing handles
            handlesGroup.clear();

            const handleSize = 10 / scale;
            const handles = [
                { pos: 'nw', x: lane.x, y: lane.y },
                { pos: 'ne', x: lane.x + lane.width, y: lane.y },
                { pos: 'sw', x: lane.x, y: lane.y + lane.height },
                { pos: 'se', x: lane.x + lane.width, y: lane.y + lane.height },
            ];

            handles.forEach(h => {
                const handle = handlesGroup.rect(handleSize, handleSize)
                    .center(h.x, h.y)
                    .addClass('gv-handle')
                    .attr('data-handle', h.pos)
                    .attr('data-lane-id', lane.id);

                handle.css('cursor', h.pos === 'nw' || h.pos === 'se' ? 'nwse-resize' : 'nesw-resize');

                handle.on('mousedown', (e) => {
                    e.stopPropagation();
                    this._startHandleDrag(e, lane, h.pos, svg, handlesGroup, scale, onResize);
                });
            });

            this.showMessage('Drag corners to resize lane. Click elsewhere to finish.');
        }

        /**
         * Start dragging a resize handle.
         */
        _startHandleDrag(e, lane, handlePos, svg, handlesGroup, scale, onResize) {
            e.preventDefault();
            const startX = e.clientX;
            const startY = e.clientY;
            const startLane = { ...lane };

            const onMove = (moveEvent) => {
                const dx = (moveEvent.clientX - startX) / scale;
                const dy = (moveEvent.clientY - startY) / scale;

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
                const element = svg.findOne(`#lane-${lane.id}`);
                if (element) {
                    element.move(newX, newY).size(newWidth, newHeight);
                }

                // Update handles
                this.showResizeHandles(lane, svg, handlesGroup, scale, onResize);
            };

            const onUp = () => {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);

                // Call callback with final dimensions (rounded to integers)
                if (onResize) {
                    onResize(lane.id, {
                        x: Math.round(lane.x),
                        y: Math.round(lane.y),
                        width: Math.round(lane.width),
                        height: Math.round(lane.height)
                    });
                }

                // Clear handles
                handlesGroup.clear();
            };

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        }

        // =====================================================================
        // Molecular Weight Prompt
        // =====================================================================

        /**
         * Prompt for molecular weight value.
         * @param {Object} band - Band data
         * @param {Function} onUpdate - Callback with new MW value
         */
        promptMolecularWeight(band, onUpdate) {
            const currentMW = band.estimated_mw_kda || '';
            const newMW = prompt('Enter estimated molecular weight (kDa):', currentMW);

            if (newMW !== null) {
                const mwValue = parseFloat(newMW);
                if (!isNaN(mwValue) && mwValue > 0) {
                    onUpdate(band.id, { estimated_mw_kda: mwValue });
                } else if (newMW === '') {
                    onUpdate(band.id, { estimated_mw_kda: null });
                } else {
                    this.showMessage('Invalid molecular weight value');
                }
            }
        }
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.ContextMenu = ContextMenu;

})(window);
