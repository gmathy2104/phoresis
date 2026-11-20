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

            // Support handlers passed as object or as individual callbacks
            this.handlers = options.handlers || {};
            if (options.onDeleteLane) this.handlers.onDeleteLane = options.onDeleteLane;
            if (options.onDeleteBand) this.handlers.onDeleteBand = options.onDeleteBand;
            if (options.onUpdateLane) this.handlers.onUpdateLane = options.onUpdateLane;
            if (options.onUpdateBand) this.handlers.onUpdateBand = options.onUpdateBand;
            if (options.onSyncBandLocal) this.handlers.onSyncBandLocal = options.onSyncBandLocal;
            if (options.onStartResize) this.handlers.onStartResize = options.onStartResize;
            if (options.onSetReferenceLane) this.handlers.onSetReferenceLane = options.onSetReferenceLane;

            // Anti-HCP reference lane: returns { assay, referenceLaneId, canWrite }
            // (GelViewerApp.readout, refreshed on every annotations load).
            this.getReferenceContext = options.getReferenceContext || (() => null);

            // Optional plumbing for CALIBRATION-aware actions: apiClient lets
            // us PATCH /api/v1/bands/<id>/ with a quant_point payload (so the
            // BandSerializer validates the nested write); stateManager lets
            // us toggle the "Set calibration value..." item based on the
            // selected band's current type.
            this._apiClient = options.apiClient || null;
            this._stateManager = options.stateManager || null;

            // Cache the active quantification calibration's unit (UG/UG_ML/null)
            // so a band that's already a CALIBRATION point gets a unit-aware
            // prompt label and a locked unit during the prompt flow.
            this._activeCalibUnitCache = undefined;

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

            // Esc: GelViewer.Layers (show) closes the menu, and only the menu.

            if (!this.menu) return;

            this.menu.addEventListener('click', (e) => {
                const item = e.target.closest('.gv-context-menu-item');
                if (!item || item.disabled) return;

                e.stopPropagation();
                const action = item.dataset.action;
                const value = item.dataset.value;

                // Closed first: a menu opened from the keyboard gives the focus back before the item acts, and the
                // item may move it (Edit Properties to the form, a dialog into itself and back there).
                this.hide();
                this._handleAction(action, value);
            });

            this.menu.addEventListener('keydown', (e) => this._onMenuKeyDown(e));

            // A right-click, or the Menu key, on the menu itself: never the browser's menu over it.
            this.menu.addEventListener('contextmenu', (e) => e.preventDefault());
        }

        /**
         * Up / Down move between the items (round the end), Home / End to the first / last; Tab goes on as well,
         * Enter or Space acts, Esc closes (GelViewer.Layers).
         */
        _onMenuKeyDown(e) {
            const steps = { ArrowDown: 1, ArrowUp: -1 };
            if (!(e.key in steps) && e.key !== 'Home' && e.key !== 'End') return;
            const items = this._items();
            if (!items.length) return;
            e.preventDefault();
            const n = items.length;
            const i = items.indexOf(document.activeElement);
            let next;
            if (e.key === 'Home') next = 0;
            else if (e.key === 'End') next = n - 1;
            else if (i === -1) next = steps[e.key] > 0 ? 0 : n - 1;
            else next = (i + steps[e.key] + n) % n;
            items[next].focus();
        }

        /** The items of the menu shown, in order: visible and enabled. */
        _items() {
            if (!this.menu) return [];
            return Array.from(this.menu.querySelectorAll('.gv-context-menu-content.visible .gv-context-menu-item'))
                .filter(item => !item.disabled && item.getClientRects().length > 0);
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
         * Show the context menu of the selection (GelViewerApp selects what it is opened on first).
         * @param {number} x - X coordinate
         * @param {number} y - Y coordinate
         * @param {string} type - Selected annotation type ('lane' or 'band')
         * @param {{keyboard?: boolean}} [options] - keyboard: opened by Shift+F10 / the Menu key. The menu then takes
         *     the focus (first item; arrows, Tab, Enter) and keeps the editor's letter keys from acting behind it
         *     (a GelViewer.Layers modal), and gives the focus back where it was when it closes. Opened by the pointer
         *     it leaves the focus alone.
         */
        show(x, y, type, { keyboard = false } = {}) {
            if (!this.menu) return;
            const layers = global.GelViewer.Layers;
            // Shown again (another lane, or from the keyboard over a menu the pointer opened): a fresh layer, so it
            // takes this opening's focus rule.
            layers?.close(this.menu);

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

            // Toggle the conditional items BEFORE measuring: they change the
            // menu's height. "Set calibration value..." only for a band that
            // is already a CALIBRATION point; "Use as HCP reference" only for
            // a SAMPLE/CONTROL lane of an anti-HCP western.
            this._updateCalibrationButton(type);
            this._updateReferenceItem(type);

            this.menu.classList.add('visible');
            layers?.open(this.menu, {
                close: () => this.hide(),
                isOpen: () => this.isVisible(),
                modal: keyboard,
                initialFocus: keyboard ? () => this._items()[0] : undefined,
            });

            // Position menu within viewport (measured once visible; the
            // constants are the fallback for a menu not laid out yet).
            const menuWidth = this.menu.offsetWidth || 240;
            const menuHeight = this.menu.offsetHeight || 420;
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;

            let menuX = x;
            let menuY = y;

            if (x + menuWidth > viewportWidth) {
                menuX = viewportWidth - menuWidth - 10;
            }
            if (y + menuHeight > viewportHeight) {
                menuY = Math.max(10, viewportHeight - menuHeight - 10);
            }
            // Never above or left of the window either (a keyboard-opened menu holds the keys: it must be seen).
            menuX = Math.max(10, menuX);
            menuY = Math.max(10, menuY);

            this.menu.style.left = menuX + 'px';
            this.menu.style.top = menuY + 'px';

            this.eventBus.emit(Events.CONTEXT_MENU_SHOWN, { x: menuX, y: menuY, type });
        }

        /**
         * Show/check/disable the "Use as HCP reference" lane item.
         *
         * Visible only for a lane, on an anti-HCP western (the image's assay
         * reads HOST_CELL_PROTEINS), and a SAMPLE or CONTROL lane (an HCP
         * standard is often typed CONTROL). Checked when the lane is the
         * current reference (ids compared as numbers: the server sends ints,
         * a temp lane id never matches). Disabled for a user without write
         * access. No "not editable" branch: the editor never opens a
         * non-editable analysis for editing.
         */
        _updateReferenceItem(type) {
            const group = this.menu.querySelector('#ctx-hcp-ref-group');
            const item = this.menu.querySelector('#ctx-set-hcp-ref');
            if (!group || !item) return;

            const sel = this.getSelection();
            const ctx = this.getReferenceContext() || {};
            const lane = type === 'lane' && sel?.type === 'lane' && this._stateManager
                ? this._stateManager.getLane(sel.id)
                : null;
            const visible = !!lane
                && ctx.assay?.readout === 'HOST_CELL_PROTEINS'
                && (lane.lane_type === 'SAMPLE' || lane.lane_type === 'CONTROL');

            group.style.display = visible ? '' : 'none';
            if (!visible) return;

            const isReference = ctx.referenceLaneId != null
                && Number(sel.id) === Number(ctx.referenceLaneId);
            item.classList.toggle('is-checked', isReference);
            item.setAttribute('aria-pressed', isReference ? 'true' : 'false');
            item.disabled = !ctx.canWrite;
            item.title = ctx.canWrite
                ? (isReference ? 'Click to clear the HCP reference' : '')
                : 'You need write access to Gel Analyzer to change the HCP reference';
        }

        /**
         * Toggle the visibility/label of the "Set calibration value..." item.
         * Visible only when a CALIBRATION band is selected; the label adapts
         * to the active calibration's unit (UG → "Set load (µg)..." vs
         * UG_ML → "Set concentration (µg/mL)...").
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

            if (isCalibBand) {
                this._getActiveCalibUnit().then(unit => {
                    const label = item.querySelector('#ctx-set-calib-value-label');
                    if (!label) return;
                    if (unit === 'UG_ML') {
                        label.textContent = 'Set concentration (µg/mL)...';
                    } else if (unit === 'UG') {
                        label.textContent = 'Set load (µg)...';
                    } else {
                        label.textContent = 'Set calibration value...';
                    }
                });
            }
        }

        /**
         * Fetch and cache the active calibration unit. `undefined` = not fetched;
         * null = no active calibration; 'UG'/'UG_ML' = locked unit.
         */
        async _getActiveCalibUnit() {
            if (this._activeCalibUnitCache !== undefined) return this._activeCalibUnitCache;
            if (!this._apiClient || typeof this._apiClient.getActiveQuantification !== 'function') {
                this._activeCalibUnitCache = null;
                return null;
            }
            try {
                const resp = await this._apiClient.getActiveQuantification();
                this._activeCalibUnitCache = resp?.active?.unit || null;
            } catch (err) {
                console.warn('Could not load active quantification:', err);
                this._activeCalibUnitCache = null;
            }
            return this._activeCalibUnitCache;
        }

        /**
         * Open an inline modal asking for the calibration loaded amount + unit,
         * then PATCH the band via /api/v1/bands/<id>/ (BandSerializer validates
         * the quant_point + auto-promotes the parent lane on the server side).
         *
         * Replaces a previous window.prompt-based flow. The modal:
         *   • respects any pre-existing quant_point (pre-fills amount + unit)
         *   • locks the unit select when an active calibration exists, and
         *     surfaces a hint explaining why
         *   • Esc / backdrop click cancels; Enter submits; numeric validation
         *     happens client-side before the patch
         */
        async _promptCalibrationValue(bandId) {
            const lockedUnit = await this._getActiveCalibUnit();
            const existingBand = this._stateManager ? this._stateManager.getBand(bandId) : null;
            const existingQp = existingBand?.quant_point || {};
            const initialAmount = existingQp.load_amount ?? '';
            const initialUnit = existingQp.load_unit || lockedUnit || 'UG';

            const result = await this._openCalibValueModal({
                amount: initialAmount,
                unit: initialUnit,
                lockedUnit,
            });
            if (result === null) return; // user cancelled

            const { amount, unit } = result;
            const payload = {
                band_type: 'CALIBRATION',
                quant_point: { load_amount: amount, load_unit: unit },
            };

            if (this._apiClient && typeof this._apiClient.patchBand === 'function') {
                try {
                    await this._apiClient.patchBand(bandId, payload);
                    // After the server save, run the same local sync as a
                    // normal type change: SVG class swap + BAND_UPDATED emit.
                    // gel-viewer's onSyncBandLocal handler does both, which
                    // also triggers the parent-lane auto-promote listener.
                    if (this.handlers.onSyncBandLocal) {
                        this.handlers.onSyncBandLocal(bandId, payload);
                    } else if (this._stateManager) {
                        const band = this._stateManager.getBand(bandId);
                        if (band) {
                            band.band_type = 'CALIBRATION';
                            band.quant_point = payload.quant_point;
                        }
                    }
                    this._activeCalibUnitCache = undefined;
                    this.showMessage('Calibration value saved');
                } catch (err) {
                    this.showMessage(`Save failed: ${err.message || err}`);
                }
                return;
            }

            // Fallback if no apiClient — at least update local state.
            if (this.handlers.onUpdateBand) {
                this.handlers.onUpdateBand(bandId, payload);
            }
        }

        /**
         * Render an inline modal to collect calibration value + unit. Returns
         * a Promise that resolves to {amount: number, unit: 'UG'|'UG_ML'} or
         * null if the user cancelled. Idempotent (re-opening replaces any
         * lingering instance). Tied to gv-cv-modal-* CSS in
         * gel_viewer_standalone.css.
         */
        _openCalibValueModal({ amount, unit, lockedUnit }) {
            return new Promise((resolve) => {
                // A previous instance still open is answered "cancel" (removing it left its promise pending).
                if (this._cancelCalibValueModal) this._cancelCalibValueModal();
                document.querySelectorAll('.gv-cv-modal').forEach(el => el.remove());

                const isLocked = !!lockedUnit;
                const wrapper = document.createElement('div');
                wrapper.className = 'gv-cv-modal';
                wrapper.innerHTML = `
                    <div class="gv-cv-modal-backdrop"></div>
                    <div class="gv-cv-modal-card" role="dialog" aria-modal="true" aria-labelledby="gv-cv-modal-title">
                        <header class="gv-cv-modal-header">
                            <h3 id="gv-cv-modal-title">
                                <i class="bi bi-graph-up me-2"></i>Set calibration value
                            </h3>
                            <button type="button" class="gv-cv-modal-close" aria-label="Close">&times;</button>
                        </header>
                        <div class="gv-cv-modal-body">
                            <div class="gv-prop-grid">
                                <div class="gv-prop-field">
                                    <label for="gv-cv-amount">Loaded amount</label>
                                    <input type="number" id="gv-cv-amount" class="form-control form-control-sm"
                                           min="0" step="0.01" value="${amount === '' ? '' : amount}"
                                           placeholder="e.g., 10.0" autofocus>
                                </div>
                                <div class="gv-prop-field">
                                    <label for="gv-cv-unit">Unit</label>
                                    <select id="gv-cv-unit" class="form-select form-select-sm" ${isLocked ? 'disabled' : ''}>
                                        <option value="UG" ${unit === 'UG' ? 'selected' : ''}>µg (load)</option>
                                        <option value="UG_ML" ${unit === 'UG_ML' ? 'selected' : ''}>µg/mL (concentration)</option>
                                    </select>
                                    ${isLocked
                                        ? '<small class="gv-prop-hint"><i class="bi bi-lock-fill"></i> Locked by active calibration</small>'
                                        : '<small class="gv-prop-hint">Choose µg for an absolute load, µg/mL for a concentration.</small>'}
                                </div>
                            </div>
                            <div class="gv-cv-modal-error" id="gv-cv-error" style="display:none;"></div>
                        </div>
                        <footer class="gv-cv-modal-footer">
                            <button type="button" class="btn btn-sm btn-outline-secondary" id="gv-cv-cancel">Cancel</button>
                            <button type="button" class="btn btn-sm btn-primary" id="gv-cv-save">
                                <i class="bi bi-check2 me-1"></i>Save
                            </button>
                        </footer>
                    </div>
                `;
                document.body.appendChild(wrapper);

                const amountInput = wrapper.querySelector('#gv-cv-amount');
                const unitSelect = wrapper.querySelector('#gv-cv-unit');
                const errorEl = wrapper.querySelector('#gv-cv-error');
                const cancelBtn = wrapper.querySelector('#gv-cv-cancel');
                const saveBtn = wrapper.querySelector('#gv-cv-save');
                const closeBtn = wrapper.querySelector('.gv-cv-modal-close');
                const backdrop = wrapper.querySelector('.gv-cv-modal-backdrop');

                const cleanup = () => {
                    this._cancelCalibValueModal = null;
                    global.GelViewer.Layers?.close(wrapper);
                    wrapper.remove();
                };
                const cancel = () => { cleanup(); resolve(null); };
                this._cancelCalibValueModal = cancel;
                const submit = () => {
                    const raw = amountInput.value;
                    const amt = parseFloat(raw);
                    if (raw === '' || !isFinite(amt) || amt < 0) {
                        errorEl.style.display = '';
                        errorEl.textContent = 'Enter a positive number for the loaded amount.';
                        amountInput.focus();
                        return;
                    }
                    const u = unitSelect.value;
                    if (!['UG', 'UG_ML'].includes(u)) {
                        errorEl.style.display = '';
                        errorEl.textContent = 'Pick a valid unit.';
                        return;
                    }
                    cleanup();
                    resolve({ amount: amt, unit: u });
                };

                cancelBtn.addEventListener('click', cancel);
                closeBtn.addEventListener('click', cancel);
                backdrop.addEventListener('click', cancel);
                saveBtn.addEventListener('click', submit);
                // Enter saves from the amount only (on Cancel or the close button it pressed them, and saved);
                // Esc is GelViewer.Layers: cancel, nothing saved.
                amountInput.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') { e.preventDefault(); submit(); }
                });
                global.GelViewer.Layers?.open(wrapper, {
                    modal: true,
                    close: cancel,
                    isOpen: () => wrapper.isConnected,
                    initialFocus: amountInput,
                });

                // Defer the select so the focus has landed (Layers moves it after layout)
                requestAnimationFrame(() => requestAnimationFrame(() => {
                    if (amountInput && document.activeElement === amountInput) amountInput.select();
                }));
            });
        }

        /**
         * Hide the context menu.
         */
        hide() {
            if (this.menu) {
                // The layer first: it gives a keyboard-opened menu's focus back while the item that has it is still
                // shown (a hidden element drops the focus). When the page itself had it (nothing focusable to give
                // it back to), it leaves the item: an Enter is never sent to a menu that is gone.
                global.GelViewer.Layers?.close(this.menu);
                if (this.menu.contains(document.activeElement)) document.activeElement.blur();
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
                    } else {
                        // The menu opens for the selection, whose properties the sidebar shows: bring them to the
                        // top of the sidebar and put the focus on the form itself (Tab goes on to its fields). Not
                        // on a field: the editor's letter shortcuts are not read in a select, they type into it and
                        // change the lane or band type. A sidebar slid off the screen (narrow window, an editor
                        // open) is left alone: moving it into view shifted the whole editor sideways.
                        const sidebar = document.querySelector('.gv-sidebar');
                        const form = sidebar && sidebar.querySelector('.gv-prop-form');
                        const box = sidebar && sidebar.getBoundingClientRect();
                        if (form && box.width > 0 && box.left >= 0 && box.right <= window.innerWidth + 1) {
                            const body = form.closest('.gv-sidebar-body');
                            if (body) body.scrollTop = 0;
                            // On a phone the properties are under the gel, in the scrolling content: bring them up.
                            const main = sidebar.closest('.gv-main');
                            if (main && /auto|scroll/.test(getComputedStyle(main).overflowY)) {
                                sidebar.scrollIntoView({ block: 'start', inline: 'nearest' });
                            }
                            if (!form.hasAttribute('tabindex')) form.setAttribute('tabindex', '-1');
                            form.focus({ preventScroll: true });
                        }
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

                case 'set-hcp-reference':
                    // GelViewerApp decides set vs clear (clicking the current
                    // reference clears it) and saves at once.
                    if (type === 'lane' && this.handlers.onSetReferenceLane) {
                        this.handlers.onSetReferenceLane(id);
                    }
                    break;

                case 'set-mw': {
                    // The field the band form's "MW (kDa)" writes, through the same onUpdateBand path.
                    const band = type === 'band' && this._stateManager ? this._stateManager.getBand(id) : null;
                    if (band && this.handlers.onUpdateBand) {
                        this.promptMolecularWeight(band, this.handlers.onUpdateBand);
                    }
                    break;
                }

                case 'set-band-type':
                    if (type === 'band' && value) {
                        // CALIBRATION needs a quant_point (load_amount + unit)
                        // — route through the prompt flow so the v1 PATCH
                        // delivers a complete payload to the BandSerializer.
                        if (value === 'CALIBRATION') {
                            this._promptCalibrationValue(id);
                        } else if (this.handlers.onSetBandType) {
                            this.handlers.onSetBandType(id, value);
                        } else if (this.handlers.onUpdateBand) {
                            this.handlers.onUpdateBand(id, { band_type: value });
                        }
                    }
                    break;

                case 'set-calib-value':
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
         * Prompt for molecular weight value. An empty answer clears it; an unchanged one sends nothing, since any band
         * save wipes the lane's densitometry (signals.invalidate_densitometry_on_band_save). Asked in the editor's own
         * value window (ConfirmationManager.prompt: the text as typed, or null); with none to ask with, nothing changes.
         * @param {Object} band - Band data
         * @param {Function} onUpdate - Callback with new MW value
         */
        async promptMolecularWeight(band, onUpdate) {
            const cm = global.gelViewer && global.gelViewer.confirmationManager;
            if (!cm) return;
            const currentMW = band.estimated_mw_kda ?? null;
            const answer = await cm.prompt({
                title: 'Set molecular weight',
                label: 'Estimated molecular weight (kDa)',
                value: currentMW ?? '',
                hint: 'Leave empty to clear it.',
                inputMode: 'decimal',
                confirmText: 'Save',
                icon: 'rulers',
            });
            if (answer === null) return;

            const text = answer.trim().replace(',', '.');
            const mwValue = text === '' ? null : Number(text);
            if (mwValue !== null && !(Number.isFinite(mwValue) && mwValue > 0)) {
                this.showMessage('Invalid molecular weight value');
            } else if (mwValue !== currentMW) {
                onUpdate(band.id, { estimated_mw_kda: mwValue });
            }
        }
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.ContextMenu = ContextMenu;

})(window);
