/**
 * DataTablePanel - Bulk Lane Editing Table for GelViewer
 *
 * Provides an Excel-like table for editing multiple lane properties at once.
 * Two-way sync with properties panel.
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    /**
     * DataTablePanel Class
     */
    class DataTablePanel {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus - EventBus instance
         * @param {StateManager} options.stateManager - StateManager instance
         * @param {Function} options.onSelectAnnotation - Callback for selection
         * @param {Function} options.onUpdateLane - Callback to update lane
         * @param {APIClient} options.apiClient - APIClient (used for auto-save of the sample name)
         * @param {Function} options.onChangeLaneType - (laneId, newType, select) => Promise<boolean>: the properties
         *   form's own lane-type path (PropertiesPanel.changeLaneType), confirmations and ladder template included
         * @param {Function} options.onSaveAll - () => Promise: the editor's Save, of every unsaved change
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.stateManager = options.stateManager;
            this.onSelectAnnotation = options.onSelectAnnotation;
            this.onUpdateLane = options.onUpdateLane;
            this.apiClient = options.apiClient;
            this._fieldSaveTimers = {};
            this.onChangeLaneType = options.onChangeLaneType;
            this.onSaveAll = options.onSaveAll;

            // DOM elements
            this.panel = document.getElementById('table-panel');
            this.toggleBtn = document.getElementById('toggle-table');
            this.tbody = document.querySelector('#lane-data-table tbody');
            this.laneCountEl = document.getElementById('table-lane-count');

            // State
            this.visible = false;

            // Setup DOM event listeners
            this._setupDOMListeners();

            // Subscribe to events
            this._setupEventListeners();
        }

        /**
         * Setup DOM event listeners.
         */
        _setupDOMListeners() {
            // Close button
            const closeBtn = document.getElementById('close-table-panel');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this.hide());
            }

            // Close (footer): the table's edits stay, unsaved, like every edit in the editor until a save. It
            // was "Cancel" and reverted nothing.
            const footerCloseBtn = document.getElementById('close-table-footer');
            if (footerCloseBtn) {
                footerCloseBtn.addEventListener('click', () => this.hide());
            }

            // Save all: the editor's Save (Ctrl+S), so EVERY unsaved change, the bands' included, not only this
            // table's. It was "Apply", said "applied locally" and saved everything. The panel stays open; its rows
            // are rebuilt once the save is over, a lane the save created now has its real id.
            const saveAllBtn = document.getElementById('save-all-from-table');
            if (saveAllBtn && this.onSaveAll) {
                saveAllBtn.addEventListener('click', async () => {
                    await this.onSaveAll();
                    if (this.visible) this.refresh();
                });
            }
        }

        /**
         * Setup event bus subscriptions.
         */
        _setupEventListeners() {
            // Sync from properties panel changes
            this.eventBus.on(Events.LANE_PROPERTY_CHANGED, (data) => {
                this.syncCell(data.id, data.field, data.value);
            });

            // Refresh when lanes change
            this.eventBus.on(Events.LANE_CREATED, () => {
                if (this.visible) this.refresh();
            });

            this.eventBus.on(Events.LANE_DELETED, () => {
                if (this.visible) this.refresh();
            });

            // Refresh when annotations are loaded
            this.eventBus.on(Events.ANNOTATIONS_LOADED, () => {
                if (this.visible) this.refresh();
            });
        }

        /**
         * Toggle panel visibility.
         */
        toggle() {
            console.log('DataTablePanel.toggle() called, visible:', this.visible);
            if (this.visible) {
                this.hide();
            } else {
                this.show();
            }
        }

        /**
         * Show the data table panel.
         */
        show() {
            console.log('DataTablePanel.show() called, panel:', this.panel);
            if (this.panel) {
                this.panel.style.display = 'flex';  // Force display
                this.panel.classList.add('open');
                this.visible = true;
                if (this.toggleBtn) this.toggleBtn.classList.add('active');
                // Mark the page-level container so the responsive CSS can
                // slide the Properties sidebar out of the way on narrow
                // viewports. Without this the Lane Editor (which lives
                // inside .gv-viewer-wrapper, not the whole .gv-main flex
                // row) was getting clipped on its right edge by the
                // sidebar column. See gel_viewer_standalone.css
                // `.gv-main.lane-editor-open .gv-sidebar` rule.
                const main = document.querySelector('.gv-main');
                if (main) main.classList.add('lane-editor-open');
                global.GelViewer.Layers?.open(this.panel, { close: () => this.hide(), isOpen: () => this.visible });
                console.log('DataTablePanel: Panel opened');

                // Refresh the table
                this.refresh();
            } else {
                console.warn('DataTablePanel: panel element is null!');
            }
        }

        /**
         * Hide the data table panel.
         */
        hide() {
            console.log('DataTablePanel.hide() called');
            if (this.panel) {
                this.panel.style.display = 'none';  // Force hide
                this.panel.classList.remove('open');
                this.visible = false;
                if (this.toggleBtn) this.toggleBtn.classList.remove('active');
                const main = document.querySelector('.gv-main');
                if (main) main.classList.remove('lane-editor-open');
                global.GelViewer.Layers?.close(this.panel);
            }
        }

        /**
         * Check if panel is visible.
         * @returns {boolean}
         */
        isVisible() {
            return this.visible;
        }

        /**
         * Refresh the table with current lane data.
         */
        refresh() {
            if (!this.tbody) return;

            this.tbody.innerHTML = '';

            // Get sorted lanes
            const sortedLanes = this.stateManager.getLanesSortedByPosition();

            // Update lane count in footer
            if (this.laneCountEl) {
                const count = sortedLanes.length;
                this.laneCountEl.textContent = `${count} lane${count !== 1 ? 's' : ''}`;
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
                this.tbody.appendChild(emptyRow);
                return;
            }

            // Render each lane row
            for (const lane of sortedLanes) {
                const row = this._createRow(lane);
                this.tbody.appendChild(row);
            }
        }

        /**
         * Create a table row for a lane.
         * @param {Object} lane - Lane data
         * @returns {HTMLTableRowElement}
         */
        _createRow(lane) {
            const row = document.createElement('tr');
            row.dataset.laneId = lane.id;
            row.dataset.laneType = lane.lane_type || '';

            row.innerHTML = `
                <td>${lane.lane_number}</td>
                <td>
                    <select data-field="lane_type">
                        <option value="SAMPLE" ${lane.lane_type === 'SAMPLE' ? 'selected' : ''}>Sample</option>
                        <option value="LADDER" ${lane.lane_type === 'LADDER' ? 'selected' : ''}>MW Ladder</option>
                        <option value="EMPTY" ${lane.lane_type === 'EMPTY' ? 'selected' : ''}>Empty</option>
                        <option value="CONTROL" ${lane.lane_type === 'CONTROL' ? 'selected' : ''}>Control</option>
                        <option value="CALIBRATION" ${lane.lane_type === 'CALIBRATION' ? 'selected' : ''}>Calibration Standard</option>
                        <option value="DOT" ${lane.lane_type === 'DOT' ? 'selected' : ''}>Dot</option>
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
                        <option value="TOTAL" ${lane.protein_load_type === 'TOTAL' ? 'selected' : ''}>Total Protein</option>
                        <option value="POI" ${lane.protein_load_type === 'POI' ? 'selected' : ''}>Protein of Interest</option>
                        <option value="HOST_CELL" ${lane.protein_load_type === 'HOST_CELL' ? 'selected' : ''}>Host Cell Protein</option>
                        <option value="OTHER" ${lane.protein_load_type === 'OTHER' ? 'selected' : ''}>Other</option>
                    </select>
                </td>
                <td class="sample-cell">
                    <input type="text" data-field="sample_name"
                           value="${escapeHtml(lane.sample_name || '')}"
                           placeholder="Sample name…" maxlength="255">
                </td>
            `;

            // Add event listeners
            this._setupRowListeners(row, lane.id);

            return row;
        }

        /**
         * Setup event listeners for a row.
         * @param {HTMLTableRowElement} row
         * @param {string|number} laneId
         */
        _setupRowListeners(row, laneId) {
            // Select fields - immediate update
            row.querySelectorAll('select').forEach(select => {
                select.addEventListener('change', (e) => {
                    this._handleCellChange(laneId, e.target);
                });
            });

            // Input fields - debounced update
            row.querySelectorAll('input').forEach(input => {
                let debounceTimer;
                input.addEventListener('input', (e) => {
                    clearTimeout(debounceTimer);
                    debounceTimer = setTimeout(() => {
                        this._handleCellChange(laneId, e.target);
                    }, 300);
                });
                input.addEventListener('blur', (e) => {
                    clearTimeout(debounceTimer);
                    this._handleCellChange(laneId, e.target);
                });
            });

            // Row click for selection
            row.addEventListener('click', (e) => {
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') {
                    return;
                }

                // Highlight row
                this.tbody.querySelectorAll('tr').forEach(r => r.classList.remove('selected'));
                row.classList.add('selected');

                // Select annotation
                if (this.onSelectAnnotation) {
                    this.onSelectAnnotation('lane', laneId);
                }
            });
        }

        /**
         * Handle cell value change.
         * @param {string|number} laneId
         * @param {HTMLElement} input
         */
        _handleCellChange(laneId, input) {
            const field = input.dataset.field;
            let value = input.value;

            if (field === 'lane_type') {
                this._changeLaneType(laneId, input);
                return;
            }

            // Parse value based on field type
            if (field === 'is_reduced') {
                value = value === '' ? null : value === 'true';
            } else if (field === 'protein_load_ug') {
                value = value === '' ? null : parseFloat(value);
            } else if (field === 'sample_name') {
                value = String(value || '').trim();
            }

            // Update lane via callback
            if (this.onUpdateLane) {
                this.onUpdateLane(laneId, { [field]: value }, true); // silent=true
            }

            // Auto-persist sample_name immediately (free-text identifier; Phoresis). A lane the server does not
            // have yet (temp id) waits for Save like its other fields; once the PUT lands, the name no longer
            // counts as an unsaved change.
            if (field === 'sample_name' && this.apiClient && !String(laneId).startsWith('temp_')) {
                const key = `${laneId}:sample_name`;
                if (this._fieldSaveTimers[key]) clearTimeout(this._fieldSaveTimers[key]);
                this._fieldSaveTimers[key] = setTimeout(async () => {
                    try {
                        const saved = { sample_name: value };
                        await this.apiClient.updateLane(laneId, saved);
                        this.stateManager.confirmUpdateSaved?.('lanes', laneId, saved);
                        input.classList.add('gv-field-saved');
                        setTimeout(() => input.classList.remove('gv-field-saved'), 700);
                    } catch (err) {
                        console.error('Auto-save failed for sample_name:', err);
                        input.classList.add('gv-field-save-error');
                        setTimeout(() => input.classList.remove('gv-field-save-error'), 700);
                    }
                }, 350);
            }

            // Emit event for properties panel sync
            this.eventBus.emit(Events.TABLE_CELL_CHANGED, { id: laneId, field, value });
        }

        /**
         * A row's type goes through the properties form's own path (onChangeLaneType): the same calibration
         * confirmations, the same ladder template. Once it is settled the row shows the lane's type: the new one, or
         * the old one back when a confirmation was declined or the server refused.
         * @param {string|number} laneId
         * @param {HTMLSelectElement} select
         */
        async _changeLaneType(laneId, select) {
            try {
                if (this.onChangeLaneType) await this.onChangeLaneType(laneId, select.value, select);
            } finally {
                const lane = this.stateManager.getLane(laneId);
                if (lane) this.syncCell(laneId, 'lane_type', lane.lane_type);
            }
        }

        /**
         * Sync a cell with updated value from properties panel.
         * @param {string|number} laneId
         * @param {string} field
         * @param {*} value
         */
        syncCell(laneId, field, value) {
            const row = this.tbody?.querySelector(`tr[data-lane-id="${laneId}"]`);
            if (!row) return;

            const input = row.querySelector(`[data-field="${field}"]`);
            if (input) {
                if (input.tagName === 'SELECT') {
                    input.value = value === null ? '' : String(value);
                } else {
                    input.value = value || '';
                }
            }
            if (field === 'lane_type') row.dataset.laneType = value || '';
        }

        /**
         * Highlight a row by lane ID.
         * @param {string|number} laneId
         */
        highlightRow(laneId) {
            if (!this.tbody) return;

            this.tbody.querySelectorAll('tr').forEach(r => r.classList.remove('selected'));

            const row = this.tbody.querySelector(`tr[data-lane-id="${laneId}"]`);
            if (row) {
                row.classList.add('selected');
            }
        }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.DataTablePanel = DataTablePanel;

})(window);
