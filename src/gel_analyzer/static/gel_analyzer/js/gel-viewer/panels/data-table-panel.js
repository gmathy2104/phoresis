/**
 * DataTablePanel - Bulk Lane Editing Table for GelViewer
 *
 * Provides an Excel-like table for editing multiple lane properties at once.
 * Two-way sync with properties panel.
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

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
         * @param {Function} options.onOpenSampleSelector - Callback to open sample selector
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.stateManager = options.stateManager;
            this.onSelectAnnotation = options.onSelectAnnotation;
            this.onUpdateLane = options.onUpdateLane;
            this.onOpenSampleSelector = options.onOpenSampleSelector;

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

            // Cancel button (hide without saving)
            const cancelBtn = document.getElementById('cancel-table-changes');
            if (cancelBtn) {
                cancelBtn.addEventListener('click', () => this.hide());
            }

            // Apply button (save changes)
            const applyBtn = document.getElementById('apply-table-changes');
            if (applyBtn) {
                applyBtn.addEventListener('click', () => {
                    // Emit save event and hide
                    this.eventBus.emit('save:requested');
                    this.hide();
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
                    <div class="sample-link ${!(lane.process_sample || lane.sample_name) ? 'sample-link-empty' : ''}" data-lane-id="${lane.id}">
                        <i class="bi bi-${lane.process_sample ? 'flask' : lane.sample_name ? 'link-45deg' : 'plus-circle'}"></i>
                        <span>${lane.process_sample?.sample_id || lane.sample_name || 'Link sample...'}</span>
                    </div>
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

            // Sample link click
            const sampleLink = row.querySelector('.sample-link');
            if (sampleLink && this.onOpenSampleSelector) {
                sampleLink.addEventListener('click', () => {
                    this.onOpenSampleSelector(laneId);
                });
            }

            // Row click for selection
            row.addEventListener('click', (e) => {
                if (e.target.tagName === 'INPUT' ||
                    e.target.tagName === 'SELECT' ||
                    e.target.closest('.sample-link')) {
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

            // Parse value based on field type
            if (field === 'is_reduced') {
                value = value === '' ? null : value === 'true';
            } else if (field === 'protein_load_ug') {
                value = value === '' ? null : parseFloat(value);
            }

            // Update lane via callback
            if (this.onUpdateLane) {
                this.onUpdateLane(laneId, { [field]: value }, true); // silent=true
            }

            // Emit event for properties panel sync
            this.eventBus.emit(Events.TABLE_CELL_CHANGED, { id: laneId, field, value });
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
        }

        /**
         * Update sample cell display after sample selection.
         * @param {string|number} laneId
         * @param {string} sampleName
         */
        updateSampleCell(laneId, sampleName) {
            const row = this.tbody?.querySelector(`tr[data-lane-id="${laneId}"]`);
            if (!row) return;

            const sampleLink = row.querySelector('.sample-link');
            if (sampleLink) {
                sampleLink.innerHTML = `
                    <i class="bi bi-${sampleName ? 'link-45deg' : 'plus-circle'}"></i>
                    <span>${sampleName || 'Link sample...'}</span>
                `;
                sampleLink.classList.toggle('sample-link-empty', !sampleName);
            }
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
