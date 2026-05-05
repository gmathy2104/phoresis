/**
 * BandTablePanel - Band Editing Table for GelViewer
 *
 * Provides an Excel-like table for editing bands within a selected lane.
 * Different column layouts for sample lanes vs ladder/marker lanes.
 * Two-way sync with properties panel.
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    /**
     * BandTablePanel Class
     */
    class BandTablePanel {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus - EventBus instance
         * @param {StateManager} options.stateManager - StateManager instance
         * @param {Function} options.onSelectBand - Callback for band selection
         * @param {Function} options.onUpdateBand - Callback to update band
         * @param {Function} options.onDeleteBand - Callback to delete band
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.stateManager = options.stateManager;
            this.onSelectBand = options.onSelectBand;
            this.onUpdateBand = options.onUpdateBand;
            this.onDeleteBand = options.onDeleteBand;

            // Current lane context
            this.currentLaneId = null;
            this.currentLaneType = null;

            // DOM elements - get from pre-rendered HTML (like DataTablePanel)
            this.panel = document.getElementById('band-table-panel');
            this.thead = this.panel?.querySelector('thead');
            this.tbody = this.panel?.querySelector('tbody');
            this.bandCountEl = document.getElementById('band-table-count');
            this.laneTitleEl = document.getElementById('band-table-lane-title');

            // Ladder template selector elements (will be created dynamically)
            this.templateSelectorContainer = null;
            this.ladderTemplates = [];  // Cached templates from API

            // State
            this.visible = false;

            // Log DOM element status for debugging
            console.log('BandTablePanel constructor:', {
                panel: !!this.panel,
                thead: !!this.thead,
                tbody: !!this.tbody,
                bandCountEl: !!this.bandCountEl,
                laneTitleEl: !!this.laneTitleEl
            });

            if (!this.panel) {
                console.error('BandTablePanel: #band-table-panel element not found in DOM!');
            }

            // Setup DOM event listeners
            this._setupDOMListeners();

            // Subscribe to events
            this._setupEventListeners();
        }

        /**
         * Setup DOM event listeners on pre-rendered elements.
         */
        _setupDOMListeners() {
            // Setup close button
            const closeBtn = document.getElementById('close-band-table-btn');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this.hide());
            } else {
                console.warn('BandTablePanel: close button not found');
            }

            // Add band button (placeholder - would need band creation without drawing)
            const addBtn = document.getElementById('band-table-add-btn');
            if (addBtn) {
                addBtn.addEventListener('click', () => {
                    // Could emit event to start band drawing for this lane
                    this.eventBus.emit('band:table:add-requested', { laneId: this.currentLaneId });
                });
            } else {
                console.warn('BandTablePanel: add button not found');
            }
        }

        /**
         * Setup event bus subscriptions.
         */
        _setupEventListeners() {
            // Sync from properties panel changes
            this.eventBus.on(Events.BAND_PROPERTY_CHANGED, (data) => {
                this.syncCell(data.id, data.field, data.value);
            });

            // Refresh when bands change
            this.eventBus.on(Events.BAND_CREATED, () => {
                console.log('BandTablePanel: BAND_CREATED event');
                if (this.visible && this.currentLaneId) this.refresh();
            });

            this.eventBus.on(Events.BAND_DELETED, () => {
                console.log('BandTablePanel: BAND_DELETED event');
                if (this.visible && this.currentLaneId) this.refresh();
            });

            this.eventBus.on(Events.BAND_UPDATED, () => {
                console.log('BandTablePanel: BAND_UPDATED event');
                if (this.visible && this.currentLaneId) this.refresh();
            });

            // Listen for MW calibration applied (Phase 3)
            this.eventBus.on(Events.MW_BANDS_UPDATED, () => {
                console.log('BandTablePanel: MW_BANDS_UPDATED event - refreshing MW values');
                if (this.visible && this.currentLaneId) this.refresh();
            });

            // Listen for band save completion to re-enable type selector
            this.eventBus.on(Events.BAND_SAVE_COMPLETE, (data) => {
                console.log('BandTablePanel: BAND_SAVE_COMPLETE event', data);
                if (this.visible && this.currentLaneId) this.refresh();
            });

            this.eventBus.on(Events.BAND_SAVE_FAILED, (data) => {
                console.log('BandTablePanel: BAND_SAVE_FAILED event', data);
                if (this.visible && this.currentLaneId) this.refresh();
            });

            // Listen for lane selection to show bands
            this.eventBus.on(Events.SELECTION_CHANGED, (data) => {
                console.log('BandTablePanel: SELECTION_CHANGED event', data);
                if (data.type === 'lane' && this.visible) {
                    this.showForLane(data.id);
                }
            });

            // Hide when selection is cleared
            this.eventBus.on(Events.SELECTION_CLEARED, () => {
                console.log('BandTablePanel: SELECTION_CLEARED event');
                if (this.visible) {
                    this.hide();
                }
            });
        }

        /**
         * Show the panel for a specific lane.
         * @param {string|number} laneId
         */
        showForLane(laneId) {
            const lane = this.stateManager.getLane(laneId);
            if (!lane) return;

            this.currentLaneId = laneId;
            this.currentLaneType = lane.lane_type;

            // Update title
            if (this.laneTitleEl) {
                const laneLabel = lane.lane_type === 'LADDER' ? 'MW Ladder' : `Lane ${lane.lane_number}`;
                this.laneTitleEl.textContent = `Bands in ${laneLabel}`;
            }

            // Build header based on lane type
            this._buildHeader();

            // Show template selector for LADDER lanes
            this._renderLadderTemplateSelector();

            // Show panel
            if (this.panel) {
                this.panel.style.display = 'flex';  // Override inline hide
                this.panel.classList.add('open');
                this.visible = true;
                console.log('BandTablePanel: showForLane()', { laneId, laneType: this.currentLaneType });
            }

            // Refresh table content
            this.refresh();
        }

        /**
         * Show the panel (requires a lane to be selected).
         */
        show() {
            const selection = this.stateManager.getSelection();
            console.log('BandTablePanel.show() called, selection:', selection);
            if (selection && selection.type === 'lane') {
                this.showForLane(selection.id);
            } else {
                console.log('BandTablePanel: No lane selected, cannot show band editor');
            }
        }

        /**
         * Hide the band table panel.
         */
        hide() {
            if (this.panel) {
                this.panel.style.display = 'none';  // Reset inline style
                this.panel.classList.remove('open');
                this.visible = false;
                console.log('BandTablePanel: hide()');
            }

            // Remove template selector
            if (this.templateSelectorContainer) {
                this.templateSelectorContainer.remove();
                this.templateSelectorContainer = null;
            }

            this.currentLaneId = null;
            this.currentLaneType = null;
        }

        /**
         * Toggle panel visibility.
         */
        toggle() {
            if (this.visible) {
                this.hide();
            } else {
                this.show();
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
         * Build table header based on lane type.
         */
        _buildHeader() {
            if (!this.thead) return;

            if (this.currentLaneType === 'LADDER') {
                // Ladder lane: #, MW (kDa), Label, Notes, Actions
                this.thead.innerHTML = `
                    <tr>
                        <th style="width: 40px;">#</th>
                        <th style="width: 100px;">MW (kDa)</th>
                        <th style="width: 120px;">Label</th>
                        <th>Notes</th>
                        <th style="width: 50px;"></th>
                    </tr>
                `;
            } else {
                // Sample/other lanes: #, Type, Est. MW, Label, Notes, Actions
                this.thead.innerHTML = `
                    <tr>
                        <th style="width: 40px;">#</th>
                        <th style="width: 100px;">Type</th>
                        <th style="width: 100px;">Est. MW</th>
                        <th style="width: 120px;">Label</th>
                        <th>Notes</th>
                        <th style="width: 50px;"></th>
                    </tr>
                `;
            }
        }

        /**
         * Refresh the table with current band data.
         */
        refresh() {
            if (!this.tbody || !this.currentLaneId) return;

            this.tbody.innerHTML = '';

            // Get bands for the current lane
            const bands = this.stateManager.getBandsForLane(this.currentLaneId);

            // Update band count
            if (this.bandCountEl) {
                const count = bands.length;
                this.bandCountEl.textContent = `${count} band${count !== 1 ? 's' : ''}`;
            }

            // Show empty state if no bands
            if (bands.length === 0) {
                const colspan = this.currentLaneType === 'LADDER' ? 5 : 6;
                const emptyRow = document.createElement('tr');
                emptyRow.innerHTML = `
                    <td colspan="${colspan}" class="gv-band-table-empty">
                        <i class="bi bi-layers"></i>
                        <p>No bands in this lane. Draw bands using the Band tool (B).</p>
                    </td>
                `;
                this.tbody.appendChild(emptyRow);
                return;
            }

            // Render each band row
            bands.forEach((band, index) => {
                const row = this._createRow(band, index + 1);
                this.tbody.appendChild(row);
            });
        }

        /**
         * Create a table row for a band.
         * @param {Object} band - Band data
         * @param {number} index - Band number (1-based)
         * @returns {HTMLTableRowElement}
         */
        _createRow(band, index) {
            const row = document.createElement('tr');
            row.dataset.bandId = band.id;

            if (this.currentLaneType === 'LADDER') {
                // Ladder row: #, MW, Label, Notes, Delete
                row.innerHTML = `
                    <td class="band-index">${index}</td>
                    <td>
                        <input type="number" data-field="estimated_mw_kda"
                               value="${band.estimated_mw_kda || ''}" step="0.1" min="0"
                               placeholder="MW" class="band-input-mw">
                    </td>
                    <td>
                        <input type="text" data-field="label"
                               value="${band.label || ''}" placeholder="Label" class="band-input-label">
                    </td>
                    <td>
                        <input type="text" data-field="notes"
                               value="${band.notes || ''}" placeholder="Notes" class="band-input-notes">
                    </td>
                    <td class="band-actions">
                        <button class="band-delete-btn" title="Delete band">
                            <i class="bi bi-trash"></i>
                        </button>
                    </td>
                `;
            } else {
                // Sample row: #, Type, Est. MW, Label, Notes, Delete
                // Format MW value - show up to 1 decimal for display
                const mwValue = band.estimated_mw_kda;
                const mwDisplay = mwValue != null ? parseFloat(mwValue).toFixed(1) : '';
                const mwClass = mwValue != null ? 'band-input-mw has-mw' : 'band-input-mw';

                // Check if band is still being saved (race condition protection)
                const isSaving = band._isSaving || false;
                const disabledAttr = isSaving ? 'disabled' : '';
                const savingBadge = isSaving ? '<span class="band-saving-badge">Saving...</span>' : '';

                row.innerHTML = `
                    <td class="band-index">${index}</td>
                    <td>
                        <select data-field="band_type" class="band-select-type" ${disabledAttr}>
                            <option value="OTHER" ${band.band_type === 'OTHER' ? 'selected' : ''}>Other</option>
                            <option value="POI" ${band.band_type === 'POI' ? 'selected' : ''}>POI</option>
                            <option value="MW_REFERENCE" ${band.band_type === 'MW_REFERENCE' ? 'selected' : ''}>MW Ref</option>
                        </select>
                        ${savingBadge}
                    </td>
                    <td>
                        <input type="number" data-field="estimated_mw_kda"
                               value="${mwDisplay}" step="0.1" min="0"
                               placeholder="—" class="${mwClass}"
                               title="${mwValue != null ? mwValue.toFixed(2) + ' kDa' : 'Not calibrated'}">
                    </td>
                    <td>
                        <input type="text" data-field="label"
                               value="${band.label || ''}" placeholder="Label" class="band-input-label">
                    </td>
                    <td>
                        <input type="text" data-field="notes"
                               value="${band.notes || ''}" placeholder="Notes" class="band-input-notes">
                    </td>
                    <td class="band-actions">
                        <button class="band-delete-btn" title="Delete band">
                            <i class="bi bi-trash"></i>
                        </button>
                    </td>
                `;
            }

            // Add event listeners
            this._setupRowListeners(row, band.id);

            return row;
        }

        /**
         * Setup event listeners for a row.
         * @param {HTMLTableRowElement} row
         * @param {string} bandId
         */
        _setupRowListeners(row, bandId) {
            // Select fields - immediate update
            row.querySelectorAll('select').forEach(select => {
                select.addEventListener('change', (e) => {
                    this._handleCellChange(bandId, e.target);
                });
            });

            // Input fields - debounced update
            row.querySelectorAll('input').forEach(input => {
                let debounceTimer;
                input.addEventListener('input', (e) => {
                    clearTimeout(debounceTimer);
                    debounceTimer = setTimeout(() => {
                        this._handleCellChange(bandId, e.target);
                    }, 300);
                });
                input.addEventListener('blur', (e) => {
                    clearTimeout(debounceTimer);
                    this._handleCellChange(bandId, e.target);
                });
            });

            // Delete button
            const deleteBtn = row.querySelector('.band-delete-btn');
            if (deleteBtn && this.onDeleteBand) {
                deleteBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (confirm('Delete this band?')) {
                        this.onDeleteBand(bandId);
                    }
                });
            }

            // Row click for selection
            row.addEventListener('click', (e) => {
                if (e.target.tagName === 'INPUT' ||
                    e.target.tagName === 'SELECT' ||
                    e.target.closest('.band-delete-btn')) {
                    return;
                }

                // Highlight row
                this.tbody.querySelectorAll('tr').forEach(r => r.classList.remove('selected'));
                row.classList.add('selected');

                // Select band
                if (this.onSelectBand) {
                    this.onSelectBand(bandId);
                }
            });
        }

        /**
         * Handle cell value change.
         * @param {string} bandId
         * @param {HTMLElement} input
         */
        _handleCellChange(bandId, input) {
            const field = input.dataset.field;
            let value = input.value;

            // Parse value based on field type
            if (field === 'estimated_mw_kda') {
                value = value === '' ? null : parseFloat(value);
            }

            // Update band via callback
            if (this.onUpdateBand) {
                this.onUpdateBand(bandId, { [field]: value });
            }

            // Emit event for properties panel sync
            this.eventBus.emit(Events.BAND_PROPERTY_CHANGED, { id: bandId, field, value });
        }

        /**
         * Sync a cell with updated value from properties panel.
         * @param {string} bandId
         * @param {string} field
         * @param {*} value
         */
        syncCell(bandId, field, value) {
            const row = this.tbody?.querySelector(`tr[data-band-id="${bandId}"]`);
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
         * Highlight a row by band ID.
         * @param {string} bandId
         */
        highlightRow(bandId) {
            if (!this.tbody) return;

            this.tbody.querySelectorAll('tr').forEach(r => r.classList.remove('selected'));

            const row = this.tbody.querySelector(`tr[data-band-id="${bandId}"]`);
            if (row) {
                row.classList.add('selected');
            }
        }

        // =====================================================================
        // Ladder Template Selection (for LADDER lanes)
        // =====================================================================

        /**
         * Load available ladder templates from API.
         * @returns {Promise<Array>}
         */
        async _loadLadderTemplates() {
            if (this.ladderTemplates.length > 0) {
                return this.ladderTemplates;  // Use cached
            }

            try {
                const response = await fetch('/api/ladder-templates/');
                if (!response.ok) {
                    throw new Error('Failed to load templates');
                }
                const data = await response.json();
                this.ladderTemplates = data.templates || [];
                console.log('BandTablePanel: Loaded', this.ladderTemplates.length, 'ladder templates');
                return this.ladderTemplates;
            } catch (error) {
                console.error('BandTablePanel: Error loading ladder templates:', error);
                return [];
            }
        }

        /**
         * Render the ladder template selector for LADDER lanes.
         */
        _renderLadderTemplateSelector() {
            // Remove existing selector if any
            if (this.templateSelectorContainer) {
                this.templateSelectorContainer.remove();
                this.templateSelectorContainer = null;
            }

            // Only show for LADDER lanes
            if (this.currentLaneType !== 'LADDER') {
                return;
            }

            // Create container
            this.templateSelectorContainer = document.createElement('div');
            this.templateSelectorContainer.className = 'gv-band-table-template-selector';
            this.templateSelectorContainer.innerHTML = `
                <div class="template-selector-row">
                    <label>MW Template:</label>
                    <select id="ladder-template-select" class="template-select">
                        <option value="">-- Select template --</option>
                    </select>
                    <button id="apply-template-btn" class="template-apply-btn" disabled>
                        Apply
                    </button>
                </div>
                <div id="template-warning" class="template-warning" style="display: none;"></div>
            `;

            // Insert before thead (after panel header)
            const table = this.panel?.querySelector('table');
            if (table) {
                table.parentNode.insertBefore(this.templateSelectorContainer, table);
            }

            // Populate dropdown
            this._populateTemplateDropdown();

            // Setup event listeners
            const select = this.templateSelectorContainer.querySelector('#ladder-template-select');
            const applyBtn = this.templateSelectorContainer.querySelector('#apply-template-btn');

            if (select) {
                select.addEventListener('change', () => {
                    applyBtn.disabled = !select.value;
                    // Clear previous warning
                    const warningEl = this.templateSelectorContainer.querySelector('#template-warning');
                    if (warningEl) warningEl.style.display = 'none';
                });
            }

            if (applyBtn) {
                applyBtn.addEventListener('click', () => this._applyLadderTemplate());
            }
        }

        /**
         * Populate the template dropdown with loaded templates.
         */
        async _populateTemplateDropdown() {
            const select = this.templateSelectorContainer?.querySelector('#ladder-template-select');
            if (!select) return;

            const templates = await this._loadLadderTemplates();

            // Group templates by manufacturer
            const byManufacturer = {};
            templates.forEach(t => {
                const key = t.manufacturer || 'Other';
                if (!byManufacturer[key]) byManufacturer[key] = [];
                byManufacturer[key].push(t);
            });

            // Build options with optgroups
            Object.keys(byManufacturer).sort().forEach(manufacturer => {
                const optgroup = document.createElement('optgroup');
                optgroup.label = manufacturer;

                byManufacturer[manufacturer].forEach(template => {
                    const option = document.createElement('option');
                    option.value = template.id;
                    option.textContent = `${template.name} (${template.band_count} bands, ${template.mw_range_min}-${template.mw_range_max} kDa)`;
                    optgroup.appendChild(option);
                });

                select.appendChild(optgroup);
            });

            // Pre-select if lane already has a template
            const lane = this.stateManager.getLane(this.currentLaneId);
            if (lane?.ladder_template_id) {
                select.value = lane.ladder_template_id;
                const applyBtn = this.templateSelectorContainer?.querySelector('#apply-template-btn');
                if (applyBtn) applyBtn.disabled = false;
            }
        }

        /**
         * Apply the selected ladder template to fill band MW values.
         */
        async _applyLadderTemplate() {
            const select = this.templateSelectorContainer?.querySelector('#ladder-template-select');
            const applyBtn = this.templateSelectorContainer?.querySelector('#apply-template-btn');
            const warningEl = this.templateSelectorContainer?.querySelector('#template-warning');

            if (!select?.value || !this.currentLaneId) return;

            const templateId = select.value;

            // Disable button during request
            if (applyBtn) {
                applyBtn.disabled = true;
                applyBtn.textContent = 'Applying...';
            }

            try {
                const response = await fetch(`/api/lanes/${this.currentLaneId}/apply-ladder-template/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this._getCSRFToken(),
                    },
                    body: JSON.stringify({ template_id: templateId }),
                });

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.error || 'Failed to apply template');
                }

                // Show warnings if any
                if (warningEl) {
                    if (data.warnings && data.warnings.length > 0) {
                        warningEl.innerHTML = data.warnings.map(w => `<span class="warning-icon">⚠</span> ${w}`).join('<br>');
                        warningEl.style.display = 'block';
                    } else {
                        warningEl.style.display = 'none';
                    }
                }

                // Update state with new band data
                if (data.bands) {
                    data.bands.forEach(bandData => {
                        this.stateManager.setBand(bandData.id, bandData);
                    });
                }

                // Refresh table to show new MW values
                this.refresh();

                // Emit event for other components (renderer, etc.)
                this.eventBus.emit(Events.MW_BANDS_UPDATED, {
                    laneId: this.currentLaneId,
                    templateName: data.template_name,
                    bandsUpdated: data.bands_updated,
                });

                console.log('BandTablePanel: Applied template', data.template_name, '- updated', data.bands_updated, 'bands');

            } catch (error) {
                console.error('BandTablePanel: Error applying template:', error);
                if (warningEl) {
                    warningEl.innerHTML = `<span class="warning-icon">❌</span> ${error.message}`;
                    warningEl.style.display = 'block';
                }
            } finally {
                // Re-enable button
                if (applyBtn) {
                    applyBtn.disabled = !select.value;
                    applyBtn.textContent = 'Apply';
                }
            }
        }

        /**
         * Get CSRF token from cookie.
         * @returns {string}
         */
        _getCSRFToken() {
            const name = 'csrftoken';
            const cookies = document.cookie.split(';');
            for (let cookie of cookies) {
                const [key, value] = cookie.trim().split('=');
                if (key === name) return value;
            }
            return '';
        }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.BandTablePanel = BandTablePanel;

})(window);
