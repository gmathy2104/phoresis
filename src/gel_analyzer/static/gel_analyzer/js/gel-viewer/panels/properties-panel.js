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
            this.onDeleteLane = options.onDeleteLane;
            this.onDeleteBand = options.onDeleteBand;
            this.onUpdateLane = options.onUpdateLane;
            this.onUpdateBand = options.onUpdateBand;
            // Local-only sync helper (state + SVG + emit BAND_UPDATED) for
            // callers that already persisted via the v1 PATCH endpoint —
            // lets _saveBandProperties trigger the auto-promote-lane flow
            // without re-issuing an API call.
            this.onSyncBandLocal = options.onSyncBandLocal;
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

            // Re-render when the displayed band changes underneath us
            // (e.g. right-click "Set as Calibration" emits BAND_UPDATED
            // after the v1 PATCH; without this the panel still shows the
            // old band_type/quant_point until the user reselects).
            this.eventBus.on(Events.BAND_UPDATED, (band) => {
                if (!band) return;
                const updatedId = band.id || band.band_id;
                if (this.currentType !== 'band' || this.currentId !== updatedId) return;
                // Don't rebuild the DOM if the user is actively editing a
                // field in this panel — the form values are the source of
                // truth while focus is on them, and a rebuild would wipe
                // any half-typed value (e.g. "5" they were typing into
                // Loaded amount before tabbing).
                const active = document.activeElement;
                if (active && this.contentContainer && this.contentContainer.contains(active)) {
                    return;
                }
                this.show('band', updatedId);
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

            const isLadder = lane.lane_type === 'LADDER';
            const isCalibOrCtrl = ['CALIBRATION', 'CONTROL'].includes(lane.lane_type);
            const typeBadgeClass = `gv-prop-type-badge gv-prop-type-${(lane.lane_type || 'sample').toLowerCase()}`;
            this.contentContainer.innerHTML = `
                <div class="gv-prop-form">

                    <div class="gv-prop-header">
                        <span class="gv-prop-lane-badge">${lane.lane_number}</span>
                        <div class="gv-prop-header-text">
                            <div class="gv-prop-title">Lane ${lane.lane_number}</div>
                            <span class="${typeBadgeClass}" id="prop-lane-type-badge">${lane.lane_type_display || 'Sample'}</span>
                        </div>
                    </div>

                    <section class="gv-prop-section">
                        <h6 class="gv-prop-section-title">Identity</h6>
                        <div class="gv-prop-grid">
                            <div class="gv-prop-field gv-prop-col-2">
                                <label for="prop-lane-type">Type</label>
                                <select id="prop-lane-type" data-field="lane_type" class="form-select form-select-sm">
                                    <option value="SAMPLE" ${lane.lane_type === 'SAMPLE' ? 'selected' : ''}>Sample</option>
                                    <option value="LADDER" ${lane.lane_type === 'LADDER' ? 'selected' : ''}>MW Ladder</option>
                                    <option value="EMPTY" ${lane.lane_type === 'EMPTY' ? 'selected' : ''}>Empty</option>
                                    <option value="CONTROL" ${lane.lane_type === 'CONTROL' ? 'selected' : ''}>Control</option>
                                    <option value="CALIBRATION" ${lane.lane_type === 'CALIBRATION' ? 'selected' : ''}>Calibration</option>
                                </select>
                            </div>
                            <div class="gv-prop-field gv-prop-col-2" id="prop-template-section" style="display: ${isLadder ? '' : 'none'};">
                                <label for="prop-ladder-template">MW Template</label>
                                <select id="prop-ladder-template" data-field="ladder_template_id" class="form-select form-select-sm">
                                    <option value="">Select template…</option>
                                </select>
                                <small class="text-muted gv-prop-hint" id="prop-template-info"></small>
                            </div>
                            <div class="gv-prop-field gv-prop-col-2">
                                <label for="prop-sample-name">Sample name</label>
                                <input type="text" id="prop-sample-name" data-field="sample_name"
                                       class="form-control form-control-sm"
                                       value="${(lane.sample_name || '').replace(/"/g, '&quot;')}"
                                       placeholder="Optional" maxlength="255">
                            </div>
                        </div>
                    </section>

                    <section class="gv-prop-section">
                        <h6 class="gv-prop-section-title">Conditions</h6>
                        <div class="gv-prop-grid">
                            <div class="gv-prop-field">
                                <label for="prop-is-reduced">Condition</label>
                                <select id="prop-is-reduced" data-field="is_reduced" class="form-select form-select-sm">
                                    <option value="" ${lane.is_reduced == null ? 'selected' : ''}>—</option>
                                    <option value="true" ${lane.is_reduced === true ? 'selected' : ''}>Reduced</option>
                                    <option value="false" ${lane.is_reduced === false ? 'selected' : ''}>Non-reduced</option>
                                </select>
                            </div>
                            <div class="gv-prop-field" id="prop-protein-load-section"
                                 style="display: ${isCalibOrCtrl ? 'none' : ''};">
                                <label for="prop-protein-load">Load (µg)</label>
                                <input type="number" id="prop-protein-load" data-field="protein_load_ug"
                                       class="form-control form-control-sm"
                                       value="${lane.protein_load_ug || ''}" step="0.1" min="0" placeholder="—">
                            </div>
                            <div class="gv-prop-field gv-prop-col-2" id="prop-load-type-section"
                                 style="display: ${isCalibOrCtrl ? 'none' : ''};">
                                <label for="prop-load-type">Load type</label>
                                <select id="prop-load-type" data-field="protein_load_type" class="form-select form-select-sm">
                                    <option value="" ${!lane.protein_load_type ? 'selected' : ''}>—</option>
                                    <option value="TOTAL" ${lane.protein_load_type === 'TOTAL' ? 'selected' : ''}>Total Protein</option>
                                    <option value="POI" ${lane.protein_load_type === 'POI' ? 'selected' : ''}>Protein of Interest</option>
                                    <option value="HOST_CELL" ${lane.protein_load_type === 'HOST_CELL' ? 'selected' : ''}>Host Cell Protein</option>
                                    <option value="OTHER" ${lane.protein_load_type === 'OTHER' ? 'selected' : ''}>Other</option>
                                </select>
                            </div>
                            <div class="gv-prop-field gv-prop-col-2" id="prop-loading-volume-section"
                                 style="display: ${isCalibOrCtrl ? '' : 'none'};">
                                <label for="prop-loading-volume">Loading volume (µL)</label>
                                <input type="number" id="prop-loading-volume" data-field="loading_volume_ul"
                                       class="form-control form-control-sm"
                                       value="${lane.loading_volume_ul ?? ''}" step="0.1" min="0" placeholder="—">
                            </div>
                            <div class="gv-prop-field gv-prop-col-2">
                                <label for="prop-notes">Notes</label>
                                <textarea id="prop-notes" data-field="notes" class="form-control form-control-sm" rows="2" placeholder="Optional">${lane.notes || ''}</textarea>
                            </div>
                        </div>
                    </section>

                    <section class="gv-prop-section">
                        <h6 class="gv-prop-section-title">
                            <i class="bi bi-bounding-box"></i> Position
                        </h6>
                        <div class="gv-prop-grid">
                            <div class="gv-prop-field"><label for="prop-dim-x">X</label>
                                <input type="number" id="prop-dim-x" data-field="x" class="form-control form-control-sm" value="${lane.x || 0}" min="0" step="1"></div>
                            <div class="gv-prop-field"><label for="prop-dim-y">Y</label>
                                <input type="number" id="prop-dim-y" data-field="y" class="form-control form-control-sm" value="${lane.y || 0}" min="0" step="1"></div>
                            <div class="gv-prop-field"><label for="prop-dim-w">Width</label>
                                <input type="number" id="prop-dim-w" data-field="width" class="form-control form-control-sm" value="${lane.width || 0}" min="1" step="1"></div>
                            <div class="gv-prop-field"><label for="prop-dim-h">Height</label>
                                <input type="number" id="prop-dim-h" data-field="height" class="form-control form-control-sm" value="${lane.height || 0}" min="1" step="1"></div>
                        </div>
                    </section>

                    <section class="gv-prop-section">
                        <div class="gv-prop-section-title-row">
                            <h6 class="gv-prop-section-title gv-prop-section-title--inline">Bands</h6>
                            <span class="gv-prop-pill" id="prop-band-count">0</span>
                        </div>
                        <div class="gv-band-list" id="prop-band-list"></div>
                    </section>

                    <div class="gv-prop-actions">
                        <button class="btn btn-sm btn-outline-danger" id="prop-delete-lane-btn">
                            <i class="bi bi-trash"></i> Delete lane
                        </button>
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
                'CALIBRATION': 'Calib',
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
                'CALIBRATION': 'info',
                'OTHER': 'secondary'
            };
            return colors[bandType] || 'secondary';
        }

        /**
         * Fetch and cache the unit of the active quantification calibration
         * for this analysis. When an active calibration exists, every new
         * CALIBRATION point must use the same unit so we lock the select.
         * @returns {Promise<string|null>} 'UG' | 'UG_ML' | null when no active
         */
        async _getActiveCalibUnit() {
            if (this._activeCalibUnitCache !== undefined) {
                return this._activeCalibUnitCache;
            }
            if (!this.apiClient || !this.apiClient.analysisId) {
                this._activeCalibUnitCache = null;
                return null;
            }
            try {
                const resp = await this.apiClient.getActiveQuantification(
                    this.apiClient.analysisId
                );
                this._activeCalibUnitCache = resp?.active?.unit || null;
            } catch (err) {
                console.warn('Could not load active quantification:', err);
                this._activeCalibUnitCache = null;
            }
            return this._activeCalibUnitCache;
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
         * Confirm a lane-type downgrade if the lane has dependent CALIBRATION
         * points, and immediately PATCH the server with ?force=true to purge
         * them. The subsequent normal update flow will see a consistent state.
         *
         * @returns {Promise<boolean>} true if the change should proceed
         */
        async _maybeConfirmLaneTypeChange(currentType, newType, laneId) {
            const isDowngrade = ['CALIBRATION', 'CONTROL'].includes(currentType)
                && !['CALIBRATION', 'CONTROL'].includes(newType);
            if (!isDowngrade) return true;

            const bands = this.stateManager.getBandsForLane(laneId) || [];
            const hasCalibPoints = bands.some(b => b.band_type === 'CALIBRATION');
            if (!hasCalibPoints) return true;

            const ok = window.confirm(
                'This lane has calibration points. Their loaded amounts and '
                + 'units will be deleted, and the bands reset to OTHER. Continue?'
            );
            if (!ok) return false;

            // Immediate ?force=true PATCH so the server purges the dependent
            // ProteinQuantCalibrationPoint rows + flips the bands back to OTHER.
            // Without this, the subsequent batched bulk save would 409 (or, on
            // the legacy endpoint, leave inconsistent state).
            try {
                await this.apiClient.updateLane(laneId, { lane_type: newType }, { force: true });
                // Reflect band-type change locally — the server has reset all
                // dependent CALIBRATION bands to OTHER. We mirror that in state
                // so the UI stays consistent without a full reload.
                bands.forEach(b => {
                    if (b.band_type === 'CALIBRATION') {
                        b.band_type = 'OTHER';
                        b.quant_point = null;
                    }
                });
            } catch (err) {
                window.alert(`Could not change lane type: ${err.message || err}`);
                return false;
            }
            return true;
        }

        /**
         * Handle lane type change - show/hide template section and auto-assign default.
         * @param {string|number} laneId - Lane ID
         * @param {string} newType - New lane type value
         */
        async _onLaneTypeChange(laneId, newType) {
            const templateSection = document.getElementById('prop-template-section');
            const templateSelect = document.getElementById('prop-ladder-template');

            // Update the type badge in the header
            const typeBadge = document.getElementById('prop-lane-type-badge');
            if (typeBadge) {
                const labels = {
                    SAMPLE: 'Sample',
                    LADDER: 'MW Ladder',
                    EMPTY: 'Empty',
                    CONTROL: 'Control',
                    CALIBRATION: 'Calibration',
                    DOT: 'Dot',
                };
                typeBadge.textContent = labels[newType] || 'Sample';
                typeBadge.className = `gv-prop-type-badge gv-prop-type-${(newType || 'sample').toLowerCase()}`;
            }

            // Toggle protein-load vs loading-volume sections based on the new type.
            // CALIBRATION/CONTROL lanes use loading_volume_ul; everything else
            // keeps the legacy protein_load_ug + protein_load_type pair.
            const isCalibOrCtrl = ['CALIBRATION', 'CONTROL'].includes(newType);
            const loadSection = document.getElementById('prop-protein-load-section');
            const loadTypeSection = document.getElementById('prop-load-type-section');
            const volumeSection = document.getElementById('prop-loading-volume-section');
            if (loadSection) loadSection.style.display = isCalibOrCtrl ? 'none' : '';
            if (loadTypeSection) loadTypeSection.style.display = isCalibOrCtrl ? 'none' : '';
            if (volumeSection) volumeSection.style.display = isCalibOrCtrl ? '' : 'none';

            if (newType === 'LADDER') {
                // Show template section (clear inline display so the .gv-prop-field flex layout applies)
                if (templateSection) templateSection.style.display = '';

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
                // Capture the current value at render time so we can detect
                // downgrades (CALIBRATION/CONTROL -> other) and revert if the
                // user cancels the destructive confirmation prompt.
                let currentType = laneTypeSelect.value;
                laneTypeSelect.addEventListener('change', async (e) => {
                    const newType = e.target.value;
                    const proceed = await this._maybeConfirmLaneTypeChange(
                        currentType, newType, id
                    );
                    if (!proceed) {
                        // Roll the <select> back to its prior value.
                        e.target.value = currentType;
                        return;
                    }
                    currentType = newType;
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
            } else if (field === 'protein_load_ug' || field === 'loading_volume_ul') {
                value = value === '' ? null : parseFloat(value);
            } else if (field === 'ladder_template_id') {
                // Template ID: empty string means null
                value = value === '' ? null : value;
            } else if (['x', 'y', 'width', 'height'].includes(field)) {
                value = value === '' ? 0 : Math.round(parseInt(value, 10));
                if (isNaN(value) || value < 0) return;
                if ((field === 'width' || field === 'height') && value < 1) return;
            } else if (field === 'sample_name') {
                value = String(value || '').trim();
            }

            // Update via callback (mutates local state + marks dirty for batched save)
            if (this.onUpdateLane) {
                this.onUpdateLane(id, { [field]: value });
            }

            // Auto-persist text fields immediately — user expects "type and forget"
            // for free-text identifiers like sample_name.
            if (field === 'sample_name' && this.apiClient) {
                this._autoPersistField(id, input, { sample_name: value });
            }

            // Emit event for table sync
            this.eventBus.emit(Events.LANE_PROPERTY_CHANGED, { id, field, value });
        }

        /**
         * Persist a single lane field to the API immediately, with a save-flash
         * on the input. Debounced per (lane, field) so rapid typing collapses
         * to a single PUT.
         */
        _autoPersistField(laneId, input, payload) {
            if (!this._fieldSaveTimers) this._fieldSaveTimers = {};
            const key = `${laneId}:${Object.keys(payload)[0]}`;
            if (this._fieldSaveTimers[key]) clearTimeout(this._fieldSaveTimers[key]);
            this._fieldSaveTimers[key] = setTimeout(async () => {
                try {
                    await this.apiClient.updateLane(laneId, payload);
                    this._flashInput(input, true);
                } catch (err) {
                    console.error('Auto-save failed for lane field:', err);
                    this._flashInput(input, false);
                }
            }, 350);
        }

        _flashInput(input, ok) {
            if (!input) return;
            const cls = ok ? 'gv-field-saved' : 'gv-field-save-error';
            input.classList.add(cls);
            setTimeout(() => input.classList.remove(cls), 700);
        }

        /**
         * Render band properties form.
         * @param {Object} band - Band data
         */
        _renderBandProperties(band) {
            if (!this.contentContainer) return;

            // MW label depends on band type - known for references, estimated for others
            const isMwReference = band.band_type === 'MW_REFERENCE';
            const isCalibration = band.band_type === 'CALIBRATION';
            const mwLabel = isMwReference ? 'MW (kDa)' : 'Estimated MW (kDa)';
            const mwPlaceholder = isMwReference ? 'e.g., 25, 50, 75...' : 'e.g., 150.0';

            // Check if band is still being saved (race condition protection)
            const isSaving = band._isSaving || false;
            const disabledAttr = isSaving ? 'disabled' : '';
            const savingIndicator = isSaving
                ? '<span id="prop-band-saving" class="gv-saving-indicator"><i class="bi bi-arrow-repeat gv-spin"></i> Saving...</span>'
                : '<span id="prop-band-saving" class="gv-saving-indicator" style="display: none;"></span>';

            const qp = band.quant_point || {};
            const qpAmount = qp.load_amount ?? '';
            const qpUnit = qp.load_unit || 'UG';
            const hasDensito = band.corrected_area != null && band.corrected_area > 0;
            const densitoStatus = hasDensito
                ? '<span class="text-success"><i class="bi bi-check-circle"></i> Densitometry available</span>'
                : '<span class="text-warning"><i class="bi bi-exclamation-triangle"></i> Run densitometry to use this point</span>';

            this.contentContainer.innerHTML = `
                <div class="gv-quick-form">
                    <h6 class="mb-3">Band</h6>
                    <div class="mb-2">
                        <label class="form-label">Band Type ${savingIndicator}</label>
                        <select class="form-select form-select-sm" id="prop-band-type" data-field="band_type" ${disabledAttr}>
                            <option value="OTHER" ${band.band_type === 'OTHER' ? 'selected' : ''}>Other</option>
                            <option value="POI" ${band.band_type === 'POI' ? 'selected' : ''}>Protein of Interest</option>
                            <option value="MW_REFERENCE" ${band.band_type === 'MW_REFERENCE' ? 'selected' : ''}>MW Reference</option>
                            <option value="CALIBRATION" ${isCalibration ? 'selected' : ''}>Calibration Point</option>
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
                    <section class="gv-prop-section mb-2" id="prop-band-calib-section"
                             style="display: ${isCalibration ? '' : 'none'};">
                        <h6 class="gv-prop-section-title">Calibration</h6>
                        <div class="mb-2">
                            <label class="form-label" for="prop-band-load-amount">Loaded amount</label>
                            <input type="number" class="form-control form-control-sm"
                                   id="prop-band-load-amount" data-field="quant_load_amount"
                                   min="0" step="0.01" value="${qpAmount}" placeholder="—">
                        </div>
                        <div class="mb-2">
                            <label class="form-label" for="prop-band-load-unit">Unit</label>
                            <select class="form-select form-select-sm"
                                    id="prop-band-load-unit" data-field="quant_load_unit">
                                <option value="UG" ${qpUnit === 'UG' ? 'selected' : ''}>µg</option>
                                <option value="UG_ML" ${qpUnit === 'UG_ML' ? 'selected' : ''}>µg/mL</option>
                            </select>
                            <small class="text-muted" id="prop-band-load-unit-hint" style="display: none;">
                                Unit fixed by active calibration
                            </small>
                        </div>
                        <div class="mb-1">
                            <small id="prop-band-densito-status">${densitoStatus}</small>
                        </div>
                    </section>
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

            // After the form is in the DOM, lock the unit if there's an active
            // quantification calibration on this analysis (units must agree).
            this._getActiveCalibUnit().then(unit => {
                if (!unit) return;
                const select = document.getElementById('prop-band-load-unit');
                const hint = document.getElementById('prop-band-load-unit-hint');
                if (select) {
                    select.value = unit;
                    select.disabled = true;
                }
                if (hint) hint.style.display = '';
            });
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
            const calibSection = document.getElementById('prop-band-calib-section');
            if (bandTypeSelect && mwLabel && mwInput) {
                bandTypeSelect.addEventListener('change', (e) => {
                    // Update MW label
                    const isMwReference = e.target.value === 'MW_REFERENCE';
                    mwLabel.textContent = isMwReference ? 'MW (kDa)' : 'Estimated MW (kDa)';
                    mwInput.placeholder = isMwReference ? 'e.g., 25, 50, 75...' : 'e.g., 150.0';
                    // Toggle the Calibration section
                    if (calibSection) {
                        calibSection.style.display = e.target.value === 'CALIBRATION' ? '' : 'none';
                    }
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

            // The Calibration sub-fields are saved via _saveBandProperties (so
            // amount + unit are persisted atomically as a quant_point payload).
            // Don't push individual changes through onUpdateBand which would
            // fire a partial update that the v1 serializer can't validate.
            if (field === 'quant_load_amount' || field === 'quant_load_unit') {
                return;
            }

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
        async _saveBandProperties(id) {
            const bandType = document.getElementById('prop-band-type')?.value;
            const label = document.getElementById('prop-label')?.value;
            const mw = document.getElementById('prop-mw')?.value;
            const notes = document.getElementById('prop-band-notes')?.value;

            const payload = {
                band_type: bandType,
                label: label,
                estimated_mw_kda: mw ? parseFloat(mw) : null,
                notes: notes,
            };

            if (bandType === 'CALIBRATION') {
                const amountStr = document.getElementById('prop-band-load-amount')?.value;
                const unit = document.getElementById('prop-band-load-unit')?.value || 'UG';
                const amount = amountStr === '' || amountStr == null
                    ? null
                    : parseFloat(amountStr);
                if (amount === null || !isFinite(amount) || amount < 0) {
                    window.alert('Loaded amount is required and must be a positive number for CALIBRATION bands.');
                    return;
                }
                payload.quant_point = {
                    load_amount: amount,
                    load_unit: unit,
                };
            }

            // Route through the v1 PATCH endpoint so the nested quant_point
            // payload is validated against the CALIBRATION rules in
            // _validate_band_quant_point. Falls back to the legacy onUpdateBand
            // for non-CALIBRATION saves to preserve the existing flow.
            if (bandType === 'CALIBRATION' && this.apiClient && this.apiClient.patchBand) {
                try {
                    await this.apiClient.patchBand(id, payload);
                    // Run the unified local sync: mutate state, swap SVG
                    // class to calibration-red, emit BAND_UPDATED so the
                    // auto-promote-lane listener fires (parent lane →
                    // CALIBRATION) and the band table refreshes.
                    if (this.onSyncBandLocal) {
                        this.onSyncBandLocal(id, payload);
                    } else {
                        // Fallback for callers that didn't wire onSyncBandLocal.
                        const band = this.stateManager.getBand(id);
                        if (band) {
                            Object.assign(band, payload);
                            band.quant_point = payload.quant_point;
                        }
                    }
                    this.eventBus.emit(Events.BAND_PROPERTY_CHANGED, {
                        id, field: 'band_type', value: bandType,
                    });
                } catch (err) {
                    window.alert(`Could not save band: ${err.message || err}`);
                }
                return;
            }

            if (this.onUpdateBand) {
                this.onUpdateBand(id, payload);
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
                'loading_volume_ul': 'prop-loading-volume',
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
