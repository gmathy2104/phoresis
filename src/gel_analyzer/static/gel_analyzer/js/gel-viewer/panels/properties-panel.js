/**
 * PropertiesPanel - Lane/Band Properties Editor for GelViewer
 *
 * Handles the side panel for editing selected annotation properties.
 * Syncs with data table when visible.
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    /**
     * PropertiesPanel Class
     */
    class PropertiesPanel {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus - EventBus instance
         * @param {StateManager} options.stateManager - StateManager instance
         * @param {APIClient} options.apiClient - APIClient instance
         * @param {Function} options.onOpenSampleSelector - Callback to open sample selector
         * @param {Function} options.onDeleteLane - Callback to delete lane
         * @param {Function} options.onDeleteBand - Callback to delete band
         * @param {Function} options.onUpdateLane - Callback to update lane
         * @param {Function} options.onUpdateBand - Callback to update band
         * @param {Function} options.onSelectBand - Callback to select a band
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.stateManager = options.stateManager;
            this.apiClient = options.apiClient;
            this.onOpenSampleSelector = options.onOpenSampleSelector;
            this.onDeleteLane = options.onDeleteLane;
            this.onDeleteBand = options.onDeleteBand;
            this.onUpdateLane = options.onUpdateLane;
            this.onUpdateBand = options.onUpdateBand;
            this.onSelectBand = options.onSelectBand;

            // DOM elements
            this.panel = document.querySelector('.gv-properties');
            this.noSelection = document.querySelector('.gv-no-selection');
            this.contentContainer = document.querySelector('.gv-properties-content');

            // Current state
            this.currentType = null;
            this.currentId = null;

            // Cache for ladder templates (loaded once)
            this._ladderTemplatesCache = null;
            this._defaultTemplateId = null;

            // Subscribe to events
            this._setupEventListeners();
        }

        /**
         * Setup event bus subscriptions.
         */
        _setupEventListeners() {
            this.eventBus.on(Events.SELECTION_CHANGED, (data) => {
                if (data.type && data.id) {
                    this.show(data.type, data.id);
                } else {
                    this.hide();
                }
            });

            this.eventBus.on(Events.SELECTION_CLEARED, () => {
                this.hide();
            });

            // Listen for band save completion to re-enable type selector
            this.eventBus.on(Events.BAND_SAVE_COMPLETE, (data) => {
                this._onBandSaveComplete(data);
            });

            this.eventBus.on(Events.BAND_SAVE_FAILED, (data) => {
                this._onBandSaveFailed(data);
            });
        }

        /**
         * Handle band save completion - re-enable type selector.
         * @param {Object} data - Event data with id and tempId
         */
        _onBandSaveComplete(data) {
            // Check if this is the currently displayed band
            if (this.currentType === 'band' &&
                (this.currentId === data.id || this.currentId === data.tempId)) {
                // Update currentId if it was a temp ID
                if (this.currentId === data.tempId && data.id !== data.tempId) {
                    this.currentId = data.id;
                }
                // Re-enable type selector
                const bandTypeSelect = document.getElementById('prop-band-type');
                if (bandTypeSelect) {
                    bandTypeSelect.disabled = false;
                }
                // Hide saving indicator
                const savingIndicator = document.getElementById('prop-band-saving');
                if (savingIndicator) {
                    savingIndicator.style.display = 'none';
                }
            }
        }

        /**
         * Handle band save failure - re-enable type selector with error state.
         * @param {Object} data - Event data with id and error
         */
        _onBandSaveFailed(data) {
            if (this.currentType === 'band' && this.currentId === data.id) {
                // Re-enable type selector even on error
                const bandTypeSelect = document.getElementById('prop-band-type');
                if (bandTypeSelect) {
                    bandTypeSelect.disabled = false;
                }
                // Show error indicator
                const savingIndicator = document.getElementById('prop-band-saving');
                if (savingIndicator) {
                    savingIndicator.innerHTML = '<i class="bi bi-exclamation-triangle text-warning"></i> Save failed';
                    savingIndicator.style.display = 'inline';
                }
            }
        }

        /**
         * Show properties panel for a given annotation.
         * @param {string} type - 'lane' or 'band'
         * @param {string|number} id - Annotation ID
         */
        show(type, id) {
            this.currentType = type;
            this.currentId = id;

            if (this.panel) this.panel.classList.add('visible');
            if (this.noSelection) this.noSelection.style.display = 'none';

            if (type === 'lane') {
                const lane = this.stateManager.getLane(id);
                if (lane) this._renderLaneProperties(lane);
            } else if (type === 'band') {
                const band = this.stateManager.getBand(id);
                if (band) this._renderBandProperties(band);
            }
        }

        /**
         * Hide properties panel.
         */
        hide() {
            this.currentType = null;
            this.currentId = null;

            if (this.panel) this.panel.classList.remove('visible');
            if (this.noSelection) this.noSelection.style.display = 'block';
        }

        /**
         * Render lane properties form.
         * @param {Object} lane - Lane data
         */
        _renderLaneProperties(lane) {
            if (!this.contentContainer) return;

            // Build template selector HTML (only for LADDER lanes)
            const isLadder = lane.lane_type === 'LADDER';
            const templateSectionHTML = `
                <div class="mb-2" id="prop-template-section" style="display: ${isLadder ? 'block' : 'none'};">
                    <label class="form-label">MW Template</label>
                    <select class="form-select form-select-sm" id="prop-ladder-template" data-field="ladder_template_id">
                        <option value="">Select template...</option>
                        <!-- Populated dynamically -->
                    </select>
                    <small class="text-muted" id="prop-template-info"></small>
                </div>
            `;

            this.contentContainer.innerHTML = `
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

                    ${templateSectionHTML}

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
                            <span class="input-group-text">
                                <i class="bi bi-pencil"></i>
                            </span>
                            <input type="text" class="form-control form-control-sm" id="prop-sample-name"
                                   data-field="sample_name"
                                   value="${lane.sample_name || ''}" placeholder="Sample name (optional)" maxlength="255">
                        </div>
                    </div>

                    <div class="mb-2">
                        <label class="form-label">Notes</label>
                        <textarea class="form-control form-control-sm" id="prop-notes" data-field="notes" rows="2">${lane.notes || ''}</textarea>
                    </div>

                    <div class="mb-2 mt-3">
                        <label class="form-label d-flex align-items-center gap-1">
                            <i class="bi bi-bounding-box"></i> Dimensions
                        </label>
                        <div class="row g-1">
                            <div class="col-6">
                                <label class="form-label small text-muted mb-0">X</label>
                                <input type="number" class="form-control form-control-sm" id="prop-dim-x"
                                       data-field="x" value="${lane.x || 0}" min="0" step="1">
                            </div>
                            <div class="col-6">
                                <label class="form-label small text-muted mb-0">Y</label>
                                <input type="number" class="form-control form-control-sm" id="prop-dim-y"
                                       data-field="y" value="${lane.y || 0}" min="0" step="1">
                            </div>
                            <div class="col-6 mt-1">
                                <label class="form-label small text-muted mb-0">Width</label>
                                <input type="number" class="form-control form-control-sm" id="prop-dim-w"
                                       data-field="width" value="${lane.width || 0}" min="1" step="1">
                            </div>
                            <div class="col-6 mt-1">
                                <label class="form-label small text-muted mb-0">Height</label>
                                <input type="number" class="form-control form-control-sm" id="prop-dim-h"
                                       data-field="height" value="${lane.height || 0}" min="1" step="1">
                            </div>
                        </div>
                    </div>

                    <div class="gv-quick-form-actions mt-3">
                        <button class="btn btn-sm btn-outline-danger" id="prop-delete-lane-btn">
                            <i class="bi bi-trash"></i> Delete
                        </button>
                    </div>

                    <!-- Bands Section -->
                    <div class="gv-lane-bands-section mt-3">
                        <div class="d-flex justify-content-between align-items-center mb-2">
                            <label class="form-label mb-0">Bands in Lane</label>
                            <span class="badge bg-secondary" id="prop-band-count">0</span>
                        </div>
                        <div class="gv-band-list" id="prop-band-list">
                            <!-- Band items will be rendered here -->
                        </div>
                    </div>
                </div>
            `;

            this._setupLaneListeners(lane.id);
            this._renderLaneBands(lane.id);

            // Populate template dropdown if LADDER
            if (isLadder) {
                this._populateLadderTemplates(lane.ladder_template_id);
            }
        }

        /**
         * Render bands list for a lane.
         * @param {string|number} laneId - Lane ID
         */
        _renderLaneBands(laneId) {
            const bandList = document.getElementById('prop-band-list');
            const bandCount = document.getElementById('prop-band-count');
            if (!bandList) return;

            const bands = this.stateManager.getBandsForLane(laneId);

            if (bandCount) {
                bandCount.textContent = bands.length;
            }

            if (bands.length === 0) {
                bandList.innerHTML = `
                    <div class="gv-band-list-empty">
                        <small class="text-muted">No bands in this lane</small>
                    </div>
                `;
                return;
            }

            bandList.innerHTML = bands.map((band, index) => {
                const typeLabel = this._getBandTypeLabel(band.band_type);
                const mwLabel = band.estimated_mw_kda ? `${band.estimated_mw_kda} kDa` : '';
                const label = band.label || `Band ${index + 1}`;

                return `
                    <div class="gv-band-list-item" data-band-id="${band.id}">
                        <div class="gv-band-list-item-info">
                            <span class="gv-band-list-item-label">${label}</span>
                            <span class="gv-band-list-item-meta">
                                <span class="badge bg-${this._getBandTypeBadgeColor(band.band_type)} badge-sm">${typeLabel}</span>
                                ${mwLabel ? `<span class="text-muted ms-1">${mwLabel}</span>` : ''}
                            </span>
                        </div>
                        <button class="btn btn-sm btn-link gv-band-list-item-edit" title="Edit band">
                            <i class="bi bi-pencil"></i>
                        </button>
                    </div>
                `;
            }).join('');

            // Add click listeners
            bandList.querySelectorAll('.gv-band-list-item').forEach(item => {
                item.addEventListener('click', (e) => {
                    if (!e.target.closest('.gv-band-list-item-edit')) {
                        const bandId = item.dataset.bandId;
                        if (this.onSelectBand) {
                            this.onSelectBand(bandId);
                        }
                    }
                });

                const editBtn = item.querySelector('.gv-band-list-item-edit');
                if (editBtn) {
                    editBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const bandId = item.dataset.bandId;
                        if (this.onSelectBand) {
                            this.onSelectBand(bandId);
                        }
                    });
                }
            });
        }

        /**
         * Get display label for band type.
         * @param {string} bandType
         * @returns {string}
         */
        _getBandTypeLabel(bandType) {
            const labels = {
                'POI': 'POI',
                'MW_REFERENCE': 'MW Ref',
                'OTHER': 'Other'
            };
            return labels[bandType] || 'Other';
        }

        /**
         * Get badge color for band type.
         * @param {string} bandType
         * @returns {string}
         */
        _getBandTypeBadgeColor(bandType) {
            const colors = {
                'POI': 'purple',
                'MW_REFERENCE': 'warning',
                'OTHER': 'secondary'
            };
            return colors[bandType] || 'secondary';
        }

        // =====================================================================
        // Ladder Template Methods
        // =====================================================================

        /**
         * Load ladder templates from API (cached).
         * @returns {Promise<Array>} Array of templates
         */
        async _loadLadderTemplates() {
            if (this._ladderTemplatesCache) {
                return this._ladderTemplatesCache;
            }

            if (!this.apiClient) {
                console.warn('PropertiesPanel: No API client available');
                return [];
            }

            try {
                const response = await this.apiClient.getLadderTemplates();
                this._ladderTemplatesCache = response.templates || [];
                return this._ladderTemplatesCache;
            } catch (error) {
                console.error('Error loading ladder templates:', error);
                return [];
            }
        }

        /**
         * Get the organization's default ladder template ID.
         * @returns {Promise<string|null>} Default template ID or null
         */
        async _getDefaultTemplateId() {
            if (this._defaultTemplateId !== null) {
                return this._defaultTemplateId;
            }

            if (!this.apiClient) {
                return null;
            }

            try {
                const response = await this.apiClient.getDefaultLadderTemplate();
                this._defaultTemplateId = response.template_id || null;
                return this._defaultTemplateId;
            } catch (error) {
                console.error('Error getting default template:', error);
                this._defaultTemplateId = null;
                return null;
            }
        }

        /**
         * Populate the ladder templates dropdown.
         * @param {string|null} selectedId - Currently selected template ID
         */
        async _populateLadderTemplates(selectedId) {
            const select = document.getElementById('prop-ladder-template');
            const infoEl = document.getElementById('prop-template-info');
            if (!select) return;

            // Load templates
            const templates = await this._loadLadderTemplates();

            // Clear and rebuild options
            select.innerHTML = '<option value="">Select template...</option>';

            if (templates.length === 0) {
                if (infoEl) infoEl.textContent = 'No templates available';
                return;
            }

            // Group by manufacturer
            const byManufacturer = {};
            templates.forEach(t => {
                if (!byManufacturer[t.manufacturer]) {
                    byManufacturer[t.manufacturer] = [];
                }
                byManufacturer[t.manufacturer].push(t);
            });

            // Build optgroups
            Object.entries(byManufacturer).forEach(([mfr, temps]) => {
                const optgroup = document.createElement('optgroup');
                optgroup.label = mfr;
                temps.forEach(t => {
                    const opt = document.createElement('option');
                    opt.value = t.id;
                    opt.textContent = `${t.name} (${t.band_count} bands)`;
                    if (t.id === selectedId) opt.selected = true;
                    optgroup.appendChild(opt);
                });
                select.appendChild(optgroup);
            });

            // Update info text if template is selected
            if (selectedId) {
                const template = templates.find(t => t.id === selectedId);
                if (template && infoEl) {
                    infoEl.textContent = template.mw_range_display || '';
                }
            } else if (infoEl) {
                infoEl.textContent = '';
            }
        }

        /**
         * Handle lane type change - show/hide template section and auto-assign default.
         * @param {string|number} laneId - Lane ID
         * @param {string} newType - New lane type value
         */
        async _onLaneTypeChange(laneId, newType) {
            const templateSection = document.getElementById('prop-template-section');
            const templateSelect = document.getElementById('prop-ladder-template');

            if (newType === 'LADDER') {
                // Show template section
                if (templateSection) templateSection.style.display = 'block';

                // Get default template and auto-assign if no template selected
                const defaultId = await this._getDefaultTemplateId();
                if (defaultId && templateSelect && !templateSelect.value) {
                    await this._populateLadderTemplates(defaultId);
                    templateSelect.value = defaultId;

                    // Update the lane with the default template
                    if (this.onUpdateLane) {
                        this.onUpdateLane(laneId, { ladder_template_id: defaultId });
                    }
                } else if (!templateSelect?.value) {
                    // Just populate templates without selecting
                    await this._populateLadderTemplates(null);
                }
            } else {
                // Hide template section and clear template
                if (templateSection) templateSection.style.display = 'none';

                // Clear the template assignment
                if (this.onUpdateLane) {
                    this.onUpdateLane(laneId, { ladder_template_id: null });
                }
            }
        }

        /**
         * Setup event listeners for lane properties fields.
         * @param {string|number} id - Lane ID
         */
        _setupLaneListeners(id) {
            // Delete button
            const deleteBtn = document.getElementById('prop-delete-lane-btn');
            if (deleteBtn && this.onDeleteLane) {
                deleteBtn.addEventListener('click', () => this.onDeleteLane(id));
            }

            // Lane type change - special handler for template section
            const laneTypeSelect = document.getElementById('prop-lane-type');
            if (laneTypeSelect) {
                laneTypeSelect.addEventListener('change', async (e) => {
                    const newType = e.target.value;
                    // Handle the standard lane change
                    this._handleLaneChange(id, e.target);
                    // Handle template section visibility and auto-assign
                    await this._onLaneTypeChange(id, newType);
                });
            }

            // Template change - update info text
            const templateSelect = document.getElementById('prop-ladder-template');
            if (templateSelect) {
                templateSelect.addEventListener('change', async (e) => {
                    this._handleLaneChange(id, e.target);
                    // Update info text
                    const infoEl = document.getElementById('prop-template-info');
                    if (infoEl && e.target.value) {
                        const templates = await this._loadLadderTemplates();
                        const template = templates.find(t => t.id === e.target.value);
                        if (template) {
                            infoEl.textContent = template.mw_range_display || '';
                        }
                    } else if (infoEl) {
                        infoEl.textContent = '';
                    }
                });
            }

            // Other select fields (except lane_type and template) - immediate update
            this.contentContainer.querySelectorAll('select[data-field]').forEach(select => {
                // Skip lane_type and template (handled above)
                if (select.id === 'prop-lane-type' || select.id === 'prop-ladder-template') {
                    return;
                }
                select.addEventListener('change', (e) => {
                    this._handleLaneChange(id, e.target);
                });
            });

            // Input/textarea fields - debounced update
            this.contentContainer.querySelectorAll('input[data-field], textarea[data-field]').forEach(input => {
                let debounceTimer;
                input.addEventListener('input', (e) => {
                    clearTimeout(debounceTimer);
                    debounceTimer = setTimeout(() => {
                        this._handleLaneChange(id, e.target);
                    }, 300);
                });
                input.addEventListener('blur', (e) => {
                    clearTimeout(debounceTimer);
                    this._handleLaneChange(id, e.target);
                });
            });
        }

        /**
         * Handle lane property change.
         * @param {string|number} id - Lane ID
         * @param {HTMLElement} input - Changed input element
         */
        _handleLaneChange(id, input) {
            const field = input.dataset.field;
            let value = input.value;

            // Parse value based on field type
            if (field === 'is_reduced') {
                value = value === '' ? null : value === 'true';
            } else if (field === 'protein_load_ug') {
                value = value === '' ? null : parseFloat(value);
            } else if (field === 'ladder_template_id') {
                // Template ID: empty string means null
                value = value === '' ? null : value;
            } else if (['x', 'y', 'width', 'height'].includes(field)) {
                value = value === '' ? 0 : Math.round(parseInt(value, 10));
                if (isNaN(value) || value < 0) return;
                if ((field === 'width' || field === 'height') && value < 1) return;
            }

            // Update via callback
            if (this.onUpdateLane) {
                this.onUpdateLane(id, { [field]: value });
            }

            // Emit event for table sync
            this.eventBus.emit(Events.LANE_PROPERTY_CHANGED, { id, field, value });
        }

        /**
         * Render band properties form.
         * @param {Object} band - Band data
         */
        _renderBandProperties(band) {
            if (!this.contentContainer) return;

            // MW label depends on band type - known for references, estimated for others
            const isMwReference = band.band_type === 'MW_REFERENCE';
            const mwLabel = isMwReference ? 'MW (kDa)' : 'Estimated MW (kDa)';
            const mwPlaceholder = isMwReference ? 'e.g., 25, 50, 75...' : 'e.g., 150.0';

            // Check if band is still being saved (race condition protection)
            const isSaving = band._isSaving || false;
            const disabledAttr = isSaving ? 'disabled' : '';
            const savingIndicator = isSaving
                ? '<span id="prop-band-saving" class="gv-saving-indicator"><i class="bi bi-arrow-repeat gv-spin"></i> Saving...</span>'
                : '<span id="prop-band-saving" class="gv-saving-indicator" style="display: none;"></span>';

            this.contentContainer.innerHTML = `
                <div class="gv-quick-form">
                    <h6 class="mb-3">Band</h6>
                    <div class="mb-2">
                        <label class="form-label">Band Type ${savingIndicator}</label>
                        <select class="form-select form-select-sm" id="prop-band-type" data-field="band_type" ${disabledAttr}>
                            <option value="OTHER" ${band.band_type === 'OTHER' ? 'selected' : ''}>Other</option>
                            <option value="POI" ${band.band_type === 'POI' ? 'selected' : ''}>Protein of Interest</option>
                            <option value="MW_REFERENCE" ${band.band_type === 'MW_REFERENCE' ? 'selected' : ''}>MW Reference</option>
                        </select>
                    </div>
                    <div class="mb-2">
                        <label class="form-label">Label</label>
                        <input type="text" class="form-control form-control-sm" id="prop-label" data-field="label"
                               value="${band.label || ''}" placeholder="e.g., Main product">
                    </div>
                    <div class="mb-2">
                        <label class="form-label" id="prop-mw-label">${mwLabel}</label>
                        <input type="number" class="form-control form-control-sm" id="prop-mw" data-field="estimated_mw_kda"
                               value="${band.estimated_mw_kda || ''}" step="0.1" placeholder="${mwPlaceholder}">
                    </div>
                    <div class="mb-2">
                        <label class="form-label">Notes</label>
                        <textarea class="form-control form-control-sm" id="prop-band-notes" data-field="notes" rows="2">${band.notes || ''}</textarea>
                    </div>
                    <div class="gv-quick-form-actions">
                        <button class="btn btn-sm btn-primary" id="prop-save-band-btn">
                            <i class="bi bi-save me-1"></i> Save
                        </button>
                        <button class="btn btn-sm btn-outline-danger" id="prop-delete-band-btn">
                            <i class="bi bi-trash me-1"></i> Delete
                        </button>
                    </div>
                </div>
            `;

            this._setupBandListeners(band.id);
        }

        /**
         * Setup event listeners for band properties fields.
         * @param {string|number} id - Band ID
         */
        _setupBandListeners(id) {
            // Save button
            const saveBtn = document.getElementById('prop-save-band-btn');
            if (saveBtn) {
                saveBtn.addEventListener('click', () => this._saveBandProperties(id));
            }

            // Delete button
            const deleteBtn = document.getElementById('prop-delete-band-btn');
            if (deleteBtn && this.onDeleteBand) {
                deleteBtn.addEventListener('click', () => this.onDeleteBand(id));
            }

            // Band type change - update MW label dynamically AND track change
            const bandTypeSelect = document.getElementById('prop-band-type');
            const mwLabel = document.getElementById('prop-mw-label');
            const mwInput = document.getElementById('prop-mw');
            if (bandTypeSelect && mwLabel && mwInput) {
                bandTypeSelect.addEventListener('change', (e) => {
                    // Update MW label
                    const isMwReference = e.target.value === 'MW_REFERENCE';
                    mwLabel.textContent = isMwReference ? 'MW (kDa)' : 'Estimated MW (kDa)';
                    mwInput.placeholder = isMwReference ? 'e.g., 25, 50, 75...' : 'e.g., 150.0';
                    // Track the change immediately
                    this._handleBandChange(id, e.target);
                });
            }

            // Other select fields - immediate update
            this.contentContainer.querySelectorAll('select[data-field]:not(#prop-band-type)').forEach(select => {
                select.addEventListener('change', (e) => {
                    this._handleBandChange(id, e.target);
                });
            });

            // Input/textarea fields - debounced update
            this.contentContainer.querySelectorAll('input[data-field], textarea[data-field]').forEach(input => {
                let debounceTimer;
                input.addEventListener('input', (e) => {
                    clearTimeout(debounceTimer);
                    debounceTimer = setTimeout(() => {
                        this._handleBandChange(id, e.target);
                    }, 300);
                });
                input.addEventListener('blur', (e) => {
                    clearTimeout(debounceTimer);
                    this._handleBandChange(id, e.target);
                });
            });
        }

        /**
         * Handle band property change.
         * @param {string|number} id - Band ID
         * @param {HTMLElement} input - Changed input element
         */
        _handleBandChange(id, input) {
            const field = input.dataset.field;
            let value = input.value;

            // Parse value based on field type
            if (field === 'estimated_mw_kda') {
                value = value === '' ? null : parseFloat(value);
            }

            // Update via callback
            if (this.onUpdateBand) {
                this.onUpdateBand(id, { [field]: value });
            }

            // Emit event for potential sync
            this.eventBus.emit(Events.BAND_PROPERTY_CHANGED, { id, field, value });
        }

        /**
         * Save band properties from form.
         * @param {string|number} id - Band ID
         */
        _saveBandProperties(id) {
            const bandType = document.getElementById('prop-band-type')?.value;
            const label = document.getElementById('prop-label')?.value;
            const mw = document.getElementById('prop-mw')?.value;
            const notes = document.getElementById('prop-band-notes')?.value;

            if (this.onUpdateBand) {
                this.onUpdateBand(id, {
                    band_type: bandType,
                    label: label,
                    estimated_mw_kda: mw ? parseFloat(mw) : null,
                    notes: notes,
                });
            }
        }

        /**
         * Sync a field value from external source (e.g., data table).
         * @param {string} field - Field name
         * @param {*} value - New value
         */
        syncField(field, value) {
            const fieldMap = {
                'lane_type': 'prop-lane-type',
                'ladder_template_id': 'prop-ladder-template',
                'is_reduced': 'prop-is-reduced',
                'protein_load_ug': 'prop-protein-load',
                'protein_load_type': 'prop-load-type',
                'sample_name': 'prop-sample-name',
                'notes': 'prop-notes',
                'band_type': 'prop-band-type',
                'label': 'prop-label',
                'estimated_mw_kda': 'prop-mw',
                'x': 'prop-dim-x',
                'y': 'prop-dim-y',
                'width': 'prop-dim-w',
                'height': 'prop-dim-h'
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

        /**
         * Update sample name display after selection.
         * @param {string} sampleName - Selected sample name
         */
        updateSampleName(sampleName) {
            const input = document.getElementById('prop-sample-name');
            if (input) {
                input.value = sampleName || '';
            }
        }

        /**
         * Get current selection.
         * @returns {Object|null} {type, id} or null
         */
        getCurrentSelection() {
            if (this.currentType && this.currentId) {
                return { type: this.currentType, id: this.currentId };
            }
            return null;
        }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.PropertiesPanel = PropertiesPanel;

})(window);
