/**
 * PropertiesPanel - Lane/Band Properties Editor for GelViewer
 *
 * Handles the side panel for editing selected annotation properties.
 * Syncs with data table when visible.
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
            this.toasts = options.toasts || null;
            this.onDeleteLane = options.onDeleteLane;
            this.onDeleteBand = options.onDeleteBand;
            this.onUpdateLane = options.onUpdateLane;
            this.onUpdateBand = options.onUpdateBand;
            // GelViewerApp._syncBandLocally: a type saved by the v1 PATCH reaches the SVG, the tables and the lane.
            this.onSyncBandLocal = options.onSyncBandLocal || null;
            this.onSelectBand = options.onSelectBand;
            // The server's reading (/data/ page_summary): a band's role and why (slice 3c).
            this.getReading = options.getReading || (() => null);
            // The lane form's "HCP reference" switch (slice 3c): GelViewerApp._setReferenceLane and its context.
            this.onSetReferenceLane = options.onSetReferenceLane || null;
            this.getReferenceContext = options.getReferenceContext || (() => null);
            // The MW Template's Apply on a ladder lane: LadderTemplateApply, the Band editor's Apply's path too.
            this.ladderTemplateApply = options.ladderTemplateApply || null;

            // Cached payload of the last failed save — re-fired when the
            // user clicks the inline Retry button. Cleared on success.
            this._lastFailedPayload = null;

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

            // Cache for active quantification calibration unit. `undefined`
            // means "not yet fetched"; null means "no active calibration"
            // (cached negative result so we don't refetch on every band view).
            this._activeCalibUnitCache = undefined;

            // Subscribe to events
            this._setupEventListeners();
        }

        /**
         * Setup event bus subscriptions.
         */
        _setupEventListeners() {
            // A fresh reading: the role line of the band shown, the roles in the lane's band list. Never the whole
            // form (a field being typed in stays as it is).
            this.eventBus.on(Events.READING_CHANGED, () => {
                if (this.currentType === 'band') {
                    const band = this.stateManager.getBand(this.currentId);
                    const slot = document.getElementById('prop-band-role');
                    if (band && slot) slot.innerHTML = this._roleLine(band);
                } else if (this.currentType === 'lane') {
                    this._renderReferenceSection(this.currentId);
                    // The role tags only, in place: a focused band-list button keeps the keyboard focus.
                    document.querySelectorAll('#prop-band-list .gv-band-list-item[data-band-id]').forEach((item) => {
                        const band = this.stateManager.getBand(item.dataset.bandId);
                        const pill = item.querySelector('.gv-band-pill');
                        if (!band || !pill) return;
                        item.querySelector('.gv-band-role-tag')?.remove();
                        pill.insertAdjacentHTML('afterend', this._roleTag(band));
                    });
                }
            });

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

            // Re-render the panel whenever the currently-displayed annotation
            // gets updated externally (e.g. from a data table edit, a context
            // menu action, or the auto-save path on this very panel). Without
            // this, the form keeps showing the pre-edit values until the user
            // re-selects the annotation — which was the regression the user
            // hit after the sectioned-layout port.
            this.eventBus.on(Events.LANE_UPDATED, (data) => {
                const updatedId = data && (data.id ?? data.laneId ?? (data.lane && data.lane.id));
                if (this.currentType === 'lane' && updatedId != null && String(this.currentId) === String(updatedId)) {
                    if (this._isTypingInForm()) return;
                    const lane = this.stateManager.getLane(this.currentId);
                    if (lane) this._renderLaneProperties(lane);
                }
            });
            this.eventBus.on(Events.BAND_UPDATED, (data) => {
                const updatedId = data && (data.id ?? data.bandId ?? (data.band && data.band.id));
                if (this.currentType === 'band' && updatedId != null && String(this.currentId) === String(updatedId)) {
                    if (this._isTypingInForm()) return;
                    const band = this.stateManager.getBand(this.currentId);
                    if (band) this._renderBandProperties(band);
                }
            });
            // MW values written (a ladder template, the MW calibration): the lane's band list shows them. The list
            // only, never the whole form (the template's notice and a field being typed in stay).
            this.eventBus.on(Events.MW_BANDS_UPDATED, () => {
                if (this.currentType === 'lane') this._renderLaneBands(this.currentId);
            });
        }

        /**
         * True while the user types in a text field of this form (Phoresis): a rebuild of the form then would take
         * the focus and the half-typed value (the sample name, a label, the notes). Selects, checkboxes and buttons
         * do not count: a lane type change relies on the rebuild (changeLaneType).
         * @returns {boolean}
         */
        _isTypingInForm() {
            const active = typeof document !== 'undefined' ? document.activeElement : null;
            if (!active || !this.contentContainer || typeof this.contentContainer.contains !== 'function') return false;
            if (!this.contentContainer.contains(active)) return false;
            const tag = String(active.tagName || '').toUpperCase();
            if (tag === 'TEXTAREA') return true;
            return tag === 'INPUT' && !['checkbox', 'radio', 'button', 'submit'].includes(active.type);
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

            // Wrap renders in try/catch so a single render failure (e.g. a
            // stale band record missing a field the new sectioned layout
            // expects) doesn't leave the panel stuck on the previous
            // selection — which masquerades as "switching is broken".
            try {
                if (type === 'lane') {
                    const lane = this.stateManager.getLane(id);
                    if (lane) {
                        this._renderLaneProperties(lane);
                    } else {
                        console.warn(`[PropertiesPanel] lane ${id} not found in stateManager`);
                    }
                } else if (type === 'band') {
                    const band = this.stateManager.getBand(id);
                    if (band) {
                        this._renderBandProperties(band);
                    } else {
                        console.warn(`[PropertiesPanel] band ${id} not found in stateManager`);
                    }
                }
            } catch (err) {
                console.error(`[PropertiesPanel] render failed for ${type} ${id}:`, err);
                // Surface the failure in the panel itself so the user knows
                // why the switch didn't take, instead of seeing stale data.
                if (this.contentContainer) {
                    this.contentContainer.innerHTML = `
                        <div class="text-danger small p-3">
                            <i class="bi bi-exclamation-triangle"></i>
                            Failed to render ${type} properties: ${escapeHtml((err && err.message) || err)}
                        </div>
                    `;
                }
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
            // CALIBRATION/CONTROL lanes use loading_volume_ul; everything else
            // keeps the legacy protein_load_ug + protein_load_type pair.
            const isCalibOrCtrl = ['CALIBRATION', 'CONTROL'].includes(lane.lane_type);
            const typeLabels = {
                SAMPLE: 'Sample', LADDER: 'MW Ladder', EMPTY: 'Empty',
                CONTROL: 'Control', CALIBRATION: 'Calibration', DOT: 'Dot',
            };
            const typeBadgeClass = `gv-prop-type-badge gv-prop-type-${(lane.lane_type || 'sample').toLowerCase()}`;
            const typeLabel = typeLabels[lane.lane_type] || 'Sample';

            this.contentContainer.innerHTML = `
                <div class="gv-prop-form">

                    <div class="gv-prop-header">
                        <span class="gv-prop-lane-badge">${lane.lane_number}</span>
                        <div class="gv-prop-header-text">
                            <div class="gv-prop-title">Lane ${lane.lane_number}</div>
                            <span class="${escapeHtml(typeBadgeClass)}" id="prop-lane-type-badge">${typeLabel}</span>
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
                                    <option value="CALIBRATION" ${lane.lane_type === 'CALIBRATION' ? 'selected' : ''}>Calibration Standard</option>
                                    <option value="DOT" ${lane.lane_type === 'DOT' ? 'selected' : ''}>Dot</option>
                                </select>
                            </div>
                            <div class="gv-prop-field gv-prop-col-2" id="prop-template-section" style="display: ${isLadder ? '' : 'none'};">
                                <label for="prop-ladder-template">MW Template</label>
                                <div class="gv-prop-template-row">
                                    <select id="prop-ladder-template" data-field="ladder_template_id" class="form-select form-select-sm">
                                        <option value="">Select template…</option>
                                    </select>
                                    ${this.ladderTemplateApply ? `<button type="button" class="gv-prop-apply-btn" id="prop-apply-template-btn" disabled
                                            title="Fill this ladder's band MW values from the template, top to bottom">Apply</button>` : ''}
                                </div>
                                <small class="gv-prop-hint" id="prop-template-info"></small>
                                <div class="gv-prop-template-notice" id="prop-template-notice" role="status" hidden></div>
                            </div>
                            <div class="gv-prop-field gv-prop-col-2">
                                <label for="prop-sample-name">Sample name</label>
                                <input type="text" id="prop-sample-name" data-field="sample_name"
                                       class="form-control form-control-sm"
                                       value="${escapeHtml(lane.sample_name || '')}"
                                       placeholder="Optional" maxlength="255">
                            </div>
                        </div>
                    </section>

                    <section class="gv-prop-section" id="prop-hcp-ref-section" hidden></section>

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
                                <label for="prop-protein-load">Load (<span class="gv-unit-text">µg</span>)</label>
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
                                <label for="prop-loading-volume">Loading volume (<span class="gv-unit-text">µL</span>)</label>
                                <input type="number" id="prop-loading-volume" data-field="loading_volume_ul"
                                       class="form-control form-control-sm"
                                       value="${lane.loading_volume_ul ?? ''}" step="0.1" min="0" placeholder="—">
                            </div>
                            <div class="gv-prop-field gv-prop-col-2">
                                <label for="prop-notes">Notes</label>
                                <textarea id="prop-notes" data-field="notes" class="form-control form-control-sm" rows="2" placeholder="Optional">${escapeHtml(lane.notes || '')}</textarea>
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

            this._setupLaneListeners(lane);
            this._renderReferenceSection(lane.id);
            this._renderLaneBands(lane.id);

            // Populate template dropdown if LADDER
            if (isLadder) {
                this._populateLadderTemplates(lane.ladder_template_id).then(() => this._syncApplyButton(lane));
            }
        }

        /**
         * The MW Template's Apply, when this form shows `lane`: on once a template is chosen, off while a request for
         * the lane is on its way (from here or from the Band editor).
         * @param {Object} lane - The lane shown: the StateManager's own object
         */
        _syncApplyButton(lane) {
            if (!this._showsLane(lane)) return;
            const btn = document.getElementById('prop-apply-template-btn');
            const select = document.getElementById('prop-ladder-template');
            if (!btn || !select) return;
            const running = this.ladderTemplateApply.isRunning(lane.id);
            btn.disabled = !select.value || running;
            btn.textContent = running ? 'Applying…' : 'Apply';
        }

        /**
         * The MW Template's Apply: LadderTemplateApply, the Band editor's Apply's path, asking first when the lane's
         * bands already hold MW values. Its warnings, refusal or error go under the select, as in the Band editor.
         * @param {Object} lane - The lane shown: the StateManager's own object
         */
        async _applyLadderTemplate(lane) {
            const select = document.getElementById('prop-ladder-template');
            const templateId = select ? select.value : '';
            if (!templateId || !this.ladderTemplateApply) return;

            this._showTemplateNotice(lane, '');
            // The list is loaded: the select's options came from it.
            const template = (this._ladderTemplatesCache || []).find(t => t.id === templateId);
            const pending = this.ladderTemplateApply.apply(lane.id, templateId, {
                confirmOverwrite: true,
                templateName: template ? template.name : '',
            });
            this._syncApplyButton(lane);  // "Applying…" while the question and the request are open
            const outcome = await pending;
            this._syncApplyButton(lane);

            this._showTemplateNotice(lane, global.GelViewer.LadderTemplateApply.noticeHtml(outcome));
            if (outcome.status === 'applied' && this.toasts) {
                this.toasts.success(`MW values from ${outcome.templateName}: ${outcome.bandsUpdated} band`
                    + `${outcome.bandsUpdated === 1 ? '' : 's'} of lane ${lane.lane_number}`);
            }
        }

        /**
         * The line under the MW Template select ('' hides it), when this form still shows `lane`.
         * @param {Object} lane
         * @param {string} html - LadderTemplateApply.noticeHtml
         */
        _showTemplateNotice(lane, html) {
            if (!this._showsLane(lane)) return;
            const notice = document.getElementById('prop-template-notice');
            if (!notice) return;
            notice.innerHTML = html;
            notice.hidden = !html;
        }

        /**
         * Whether this form still shows `lane` once a dialog or a request has ended (another annotation may have
         * been selected meanwhile; a Save gives a drawn lane its server id on the same object).
         * @param {Object} lane
         * @returns {boolean}
         */
        _showsLane(lane) {
            return this.currentType === 'lane'
                && (String(this.currentId) === String(lane.id) || this.stateManager.getLane(this.currentId) === lane);
        }

        /**
         * "Use as HCP reference" (slice 3c): on an anti-HCP blot, a SAMPLE or CONTROL lane's switch -- the same call
         * as the context menu's (saved at once, a click on the reference clears it). Disabled, saying why, without
         * write access or on a lane not saved yet; re-rendered once the call returns and on READING_CHANGED.
         * @param {string|number} laneId - Lane ID
         * @param {string} [laneType] - The type just picked in the form (the lane may not carry it yet)
         */
        _renderReferenceSection(laneId, laneType) {
            const section = document.getElementById('prop-hcp-ref-section');
            if (!section) return;
            const lane = this.stateManager.getLane(laneId);
            const ctx = this.getReferenceContext() || {};
            const type = laneType || lane?.lane_type;
            const shown = !!lane && !!this.onSetReferenceLane && ctx.assay?.readout === 'HOST_CELL_PROTEINS'
                && (type === 'SAMPLE' || type === 'CONTROL');
            section.hidden = !shown;
            if (!shown) {
                section.innerHTML = '';
                return;
            }

            const hadFocus = document.activeElement?.id === 'prop-hcp-ref';  // a refresh keeps the keyboard focus
            const isReference = ctx.referenceLaneId != null && Number(ctx.referenceLaneId) === Number(laneId);
            const unsaved = String(laneId).startsWith('temp_');
            const why = !ctx.canWrite ? 'You need write access to Gel Analyzer to change the HCP reference.'
                : ctx.editable === false ? 'This analysis is no longer editable.'
                : unsaved ? 'Save the lane first, then set it as the reference.' : '';
            const line = isReference
                ? 'Every HCP % of this blot is computed against this lane'
                : (ctx.referenceLaneId != null ? 'Moves the reference here (one lane per analysis)'
                    : 'Every HCP % of this blot will be computed against this lane');
            section.innerHTML = `
                <h6 class="gv-prop-section-title">HCP reference</h6>
                <label class="gv-prop-switch${why ? ' is-disabled' : ''}">
                    <input type="checkbox" role="switch" id="prop-hcp-ref" ${isReference ? 'checked' : ''} ${why ? 'disabled' : ''}
                           aria-labelledby="prop-hcp-ref-name" aria-describedby="prop-hcp-ref-line prop-hcp-ref-hint">
                    <span class="gv-prop-switch-track" aria-hidden="true"></span>
                    <span class="gv-prop-switch-text"><b id="prop-hcp-ref-name">Use as HCP reference</b><small id="prop-hcp-ref-line">${line}</small></span>
                </label>
                <p class="gv-prop-switch-hint" id="prop-hcp-ref-hint">${why || 'Saved at once, and the values are sent again; also on a right-click on the lane.'}</p>`;

            const input = section.querySelector('#prop-hcp-ref');
            if (hadFocus) input.focus({ preventScroll: true });
            input.addEventListener('change', async () => {
                input.disabled = true;  // one call at a time: the next click reads the reference this one sets
                try {
                    await this.onSetReferenceLane(laneId);
                } finally {
                    // Still this lane's form: the switch shows what the server now holds (unchanged on a failure).
                    if (this.currentType === 'lane' && String(this.currentId) === String(laneId)) {
                        const active = document.activeElement;
                        const free = !active || active === document.body || active === input;
                        this._renderReferenceSection(laneId);
                        if (free) document.getElementById('prop-hcp-ref')?.focus({ preventScroll: true });
                    }
                }
            });
        }

        /**
         * A band's part in the reading: its role's swatch, label and why (the server's words); with no role, the
         * server's hint for its lane (not analysed yet, no POI band...) or nothing -- the type says it all.
         * @param {Object} band
         * @returns {string} HTML
         */
        _roleLine(band) {
            const reading = this.getReading();
            if (!reading) return '';
            const text = band.role && reading.role_texts ? reading.role_texts[band.role] : null;
            if (text) {
                return `
                    <div class="gv-prop-role">
                        <i class="gv-role-sw role-${escapeHtml(band.role)}" aria-hidden="true"></i>
                        <span><b>${escapeHtml(text.label)}</b><small>${escapeHtml(text.why)}</small></span>
                    </div>`;
            }
            const laneId = String(band.lane_id ?? band._parentLaneId ?? '');
            const row = (reading.rows || []).find((r) => String(r.id) === laneId);
            if (row && row.role_hint) {
                return `<div class="gv-prop-role is-none"><small>${escapeHtml(row.role_hint)}</small></div>`;
            }
            return '';
        }

        /**
         * The role's label of a band in the lane's band list ('' with none).
         * @param {Object} band
         * @returns {string} HTML
         */
        _roleTag(band) {
            const reading = this.getReading();
            const text = band.role && reading && reading.role_texts ? reading.role_texts[band.role] : null;
            if (!text) return '';
            return `<span class="gv-band-role-tag" title="${escapeHtml(text.why)}"><i class="gv-role-sw role-${escapeHtml(band.role)}" aria-hidden="true"></i>${escapeHtml(text.label)}</span>`;
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
                const mwLabel = band.estimated_mw_kda != null
                    ? `${Number(band.estimated_mw_kda).toFixed(1)} <span class="gv-unit-text">kDa</span>` : '';
                const label = band.label || `Band ${index + 1}`;

                return `
                    <div class="gv-band-list-item" data-band-id="${band.id}">
                        <div class="gv-band-list-item-info">
                            <span class="gv-band-list-item-label">${escapeHtml(label)}</span>
                            <span class="gv-band-list-item-meta">
                                <span class="gv-band-pill gv-band-pill--${this._getBandTypeKey(band.band_type)}">${typeLabel}</span>
                                ${this._roleTag(band)}
                                ${mwLabel ? `<span class="text-muted ms-1">${mwLabel}</span>` : ''}
                            </span>
                        </div>
                        <button class="btn btn-sm btn-link gv-band-list-item-edit" title="Edit band">
                            <i class="bi bi-pencil"></i>
                        </button>
                    </div>
                `;
            }).join('');

            // Add click listeners. The band's id is read at the click (a Save gives a drawn band its server id while
            // this list stays open), not from data-band-id, written at render.
            bandList.querySelectorAll('.gv-band-list-item').forEach((item, index) => {
                const band = bands[index];
                item.addEventListener('click', (e) => {
                    if (!e.target.closest('.gv-band-list-item-edit')) {
                        if (this.onSelectBand) {
                            this.onSelectBand(band.id);
                        }
                    }
                });

                const editBtn = item.querySelector('.gv-band-list-item-edit');
                if (editBtn) {
                    editBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        if (this.onSelectBand) {
                            this.onSelectBand(band.id);
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
         * The band list pill's colour key (.gv-band-pill--<key>: the gel's band colours).
         * @param {string} bandType
         * @returns {string}
         */
        _getBandTypeKey(bandType) {
            const known = ['POI', 'MW_REFERENCE', 'CALIBRATION', 'OTHER'];
            return (known.includes(bandType) ? bandType : 'OTHER').toLowerCase();
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
         * Change a lane's type. The one path for the type select of this form, the Lane Editor table
         * (data-table-panel.js) and the lane menu's Lane Type group (context-menu.js): all ask the same calibration
         * confirmations and give the lane the same ladder template. The table and the menu once wrote the type
         * directly and skipped both.
         *
         * Nothing here touches the form's DOM: every lane write re-renders the form from the lane when it shows
         * that lane (LANE_UPDATED), badge, load sections, HCP reference and template list included. Never render a
         * section for `id` here: the form may show another lane.
         *
         * @param {string|number} id - Lane ID
         * @param {string} newType - New lane_type
         * @param {HTMLSelectElement|null} input - The <select> that asked, put back to the old type when the change
         *   does not happen; null from the menu
         * @returns {Promise<boolean>} true when the lane now has the new type
         */
        async changeLaneType(id, newType, input) {
            const lane = this.stateManager.getLane(id);
            if (!lane) return false;
            const oldType = lane.lane_type;
            if (newType === oldType) return true;

            // A CALIBRATION/CONTROL lane leaving those types may take calibration points with it: confirmed, then
            // purged on the server at once. A lane not saved yet has none there, and the v1 PATCH would answer 404
            // for its temporary id: its type changes like any other.
            const PROTECTED = ['CALIBRATION', 'CONTROL'];
            const isDowngrade = PROTECTED.includes(oldType) && !PROTECTED.includes(newType);
            const saved = !String(id).startsWith('temp_');
            let changed = true;
            if (isDowngrade && saved) {
                changed = await this._maybeConfirmLaneTypeChange(oldType, newType, id)
                    && await this._attemptLaneTypeDowngrade(id, newType, oldType, input);
            } else {
                if (this.onUpdateLane) this.onUpdateLane(id, { lane_type: newType });
                this.eventBus.emit(Events.LANE_PROPERTY_CHANGED, { id, field: 'lane_type', value: newType });
            }
            if (!changed) {
                if (input) input.value = oldType;
                return false;
            }

            await this._followLadderTemplate(id, newType);
            return true;
        }

        /**
         * The ladder template follows the lane type: a lane that becomes a MW ladder gets the default template
         * when it has none, a lane that stops being one loses its template.
         * @param {string|number} laneId - Lane ID
         * @param {string} newType - The lane's new type
         */
        async _followLadderTemplate(laneId, newType) {
            if (!this.onUpdateLane) return;
            const lane = this.stateManager.getLane(laneId);
            if (!lane) return;
            if (newType === 'LADDER') {
                if (lane.ladder_template_id) return;
                const defaultId = await this._getDefaultTemplateId();
                // Still a ladder once the default is known: a second change may have come meanwhile, or a Save given
                // the lane its server id (lane.id, not laneId).
                if (defaultId && lane.lane_type === 'LADDER' && !lane.ladder_template_id) {
                    this.onUpdateLane(lane.id, { ladder_template_id: defaultId });
                }
            } else if (lane.ladder_template_id) {
                this.onUpdateLane(lane.id, { ladder_template_id: null });
            }
        }

        /**
         * Confirm a lane-type downgrade if the lane has dependent CALIBRATION
         * bands. The user may not realize that downgrading from CALIBRATION /
         * CONTROL will remove the calibration points anchored on its bands.
         *
         * @returns {Promise<boolean>} true if the change should proceed
         */
        async _maybeConfirmLaneTypeChange(currentType, newType, laneId) {
            const isDowngrade = ['CALIBRATION', 'CONTROL'].includes(currentType)
                && !['CALIBRATION', 'CONTROL'].includes(newType);
            if (!isDowngrade) return true;

            const bands = (this.stateManager && typeof this.stateManager.getBandsForLane === 'function')
                ? (this.stateManager.getBandsForLane(laneId) || [])
                : [];
            const hasCalibPoints = bands.some(b => b.band_type === 'CALIBRATION');
            if (!hasCalibPoints) return true;

            // No dialog to ask with: nothing is deleted (show() itself answers yes without its modal).
            const cm = global.gelViewer && global.gelViewer.confirmationManager;
            const ok = cm && cm.modal ? await cm.show({
                title: 'Discard calibration points?',
                body:
                    '<p>This lane has <strong>calibration points</strong>.</p>' +
                    '<p>Changing the lane type will:</p>' +
                    '<ul>' +
                    '<li>Delete their loaded amounts and units</li>' +
                    '<li>Reset the bands to <strong>Other</strong></li>' +
                    '</ul>' +
                    '<p class="mb-0"><em>This cannot be undone.</em></p>',
                confirmText: 'Discard & change type',
                cancelText: 'Keep calibration',
                danger: true,
                icon: 'exclamation-triangle-fill',
            }) : false;
            if (!ok) return false;

            // Mirror the change locally so the UI stays consistent. The
            // backend's band_type_change.apply_band_type will delete
            // the ProteinQuantCalibrationPoint rows server-side once we
            // PATCH each band's band_type back to OTHER.
            for (const b of bands) {
                if (b.band_type === 'CALIBRATION' && this.apiClient && this.apiClient.patchBand) {
                    try {
                        await this.apiClient.patchBand(b.id, { band_type: 'OTHER' });
                        b.band_type = 'OTHER';
                        b.quant_point = null;
                    } catch (err) {
                        const msg = `Could not reset calibration band ${b.id}: ${err.message || err}`;
                        if (this.toasts) this.toasts.error(msg); else console.error(msg);
                        return false;
                    }
                }
            }
            return true;
        }

        /**
         * Setup event listeners for lane properties fields.
         *
         * Every handler reads `lane.id` when it runs. A Save gives a drawn lane its server id on this same object
         * (GelViewerApp._batchSave) while its form stays open: an id copied at render was the temp_ one, which finds
         * no lane any more -- a field changed after the Save was dropped without a word, "Delete lane" did nothing.
         * Not `this.currentId` either: a debounced field or a dialog can end after another annotation was selected.
         * @param {Object} lane - The lane shown: the StateManager's own object
         */
        _setupLaneListeners(lane) {
            // Delete button
            const deleteBtn = document.getElementById('prop-delete-lane-btn');
            if (deleteBtn && this.onDeleteLane) {
                deleteBtn.addEventListener('click', () => this.onDeleteLane(lane.id));
            }

            // Lane type: the path the Lane Editor table takes too (calibration confirmations, ladder template).
            const laneTypeSelect = document.getElementById('prop-lane-type');
            if (laneTypeSelect) {
                laneTypeSelect.addEventListener('change', (e) => this.changeLaneType(lane.id, e.target.value, e.target));
            }

            // The MW Template's Apply (ladder lanes)
            const applyTemplateBtn = document.getElementById('prop-apply-template-btn');
            if (applyTemplateBtn) {
                applyTemplateBtn.addEventListener('click', () => this._applyLadderTemplate(lane));
            }

            // Template change - update info text
            const templateSelect = document.getElementById('prop-ladder-template');
            if (templateSelect) {
                templateSelect.addEventListener('change', async (e) => {
                    this._handleLaneChange(lane.id, e.target);
                    this._syncApplyButton(lane);
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
                    this._handleLaneChange(lane.id, e.target);
                });
            });

            // Input/textarea fields - debounced update
            this.contentContainer.querySelectorAll('input[data-field], textarea[data-field]').forEach(input => {
                let debounceTimer;
                input.addEventListener('input', (e) => {
                    clearTimeout(debounceTimer);
                    debounceTimer = setTimeout(() => {
                        this._handleLaneChange(lane.id, e.target);
                    }, 300);
                });
                input.addEventListener('blur', (e) => {
                    clearTimeout(debounceTimer);
                    this._handleLaneChange(lane.id, e.target);
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
                // Trimmed once the field is left: while typing, a trailing space is the start of the next word.
                value = String(value || '');
                if (typeof document === 'undefined' || document.activeElement !== input) value = value.trim();
            }

            // Update via callback (the lane type has its own path: changeLaneType)
            if (this.onUpdateLane) {
                this.onUpdateLane(id, { [field]: value });
            }

            // Emit event for table sync
            this.eventBus.emit(Events.LANE_PROPERTY_CHANGED, { id, field, value });
        }

        /**
         * Handle a CALIBRATION/CONTROL → other lane_type change. The server
         * has the source-of-truth list of dependent calibration points; we
         * call the v1 PATCH endpoint, surface the 409 via the shared
         * ConfirmationManager, and re-fire with ?force=true on confirm.
         *
         * @param {string|number} id - Lane ID
         * @param {string} newValue - Target lane_type
         * @param {string} oldValue - Original lane_type (for revert on cancel)
         * @param {HTMLSelectElement|null} input - The <select> to revert on cancel (null from the lane menu)
         * @returns {Promise<boolean>} true when the lane now has the new type
         */
        async _attemptLaneTypeDowngrade(id, newValue, oldValue, input) {
            try {
                const result = await this.apiClient.patchLaneV1(id, { lane_type: newValue });
                if (result.ok) {
                    this._applyLaneTypeDowngrade(id, newValue, []);
                    return true;
                }
                if (!result.conflict) {
                    throw new Error(result.detail || 'Unexpected response');
                }
                const dependentCount = result.dependent_band_ids.length;
                const cm = global.gelViewer && global.gelViewer.confirmationManager;
                let confirmed = false;
                if (cm && cm.modal) {
                    confirmed = await cm.show({
                        title: 'Discard calibration points?',
                        body:
                            `<p>This lane has <strong>${dependentCount}</strong> ` +
                            `calibration point${dependentCount === 1 ? '' : 's'} tied to its bands.</p>` +
                            `<p>Changing the lane type will:</p>` +
                            `<ul>` +
                            `<li>Delete the calibration point${dependentCount === 1 ? '' : 's'}</li>` +
                            `<li>Re-tag the affected band${dependentCount === 1 ? '' : 's'} as <strong>Other</strong></li>` +
                            `</ul>` +
                            `<p class="mb-0"><em>This cannot be undone.</em></p>`,
                        confirmText: 'Discard & change type',
                        cancelText: 'Keep calibration',
                        danger: true,
                        icon: 'exclamation-triangle-fill',
                    });
                }
                // No dialog to ask with: nothing is deleted.
                if (!confirmed) {
                    if (input) input.value = oldValue;
                    return false;
                }
                const purgeResult = await this.apiClient.patchLaneV1(
                    id, { lane_type: newValue }, { force: true }
                );
                if (!purgeResult.ok) {
                    throw new Error(purgeResult.detail || 'Failed to purge calibration points');
                }
                this._applyLaneTypeDowngrade(id, newValue, result.dependent_band_ids);
                if (this.toasts && typeof this.toasts.success === 'function') {
                    this.toasts.success(
                        `Lane type changed; ${dependentCount} calibration point` +
                        `${dependentCount === 1 ? '' : 's'} discarded.`
                    );
                }
                return true;
            } catch (err) {
                console.error('Lane type downgrade failed:', err);
                if (input) input.value = oldValue;
                if (this.toasts && typeof this.toasts.error === 'function') {
                    this.toasts.error(`Could not change lane type: ${err.message || err}`);
                }
                return false;
            }
        }

        /**
         * Apply a successful lane_type downgrade locally. The server has
         * already committed both the lane update and (when forced) the
         * dependent band purge + re-tag, so we mirror that in-memory and
         * route through the standard onUpdateLane callback so the SVG,
         * tables, and dirty-queue stay in sync.
         *
         * @param {string|number} id - Lane ID
         * @param {string} newValue - New lane_type
         * @param {Array<string>} dependentBandIds - Band UUIDs re-tagged to OTHER
         */
        _applyLaneTypeDowngrade(id, newValue, dependentBandIds) {
            // Flip dependent bands locally before the lane update so the
            // table re-render picks up the correct band_type. Server already
            // persisted; we don't trackBandUpdate to avoid a redundant PUT.
            if (dependentBandIds && dependentBandIds.length > 0) {
                const bandSet = new Set(dependentBandIds.map(String));
                for (const band of this.stateManager.getBandsForLane(id)) {
                    if (bandSet.has(String(band.id)) && band.band_type === 'CALIBRATION') {
                        band.band_type = 'OTHER';
                        if (band.quant_point) band.quant_point = null;
                        this.eventBus.emit(Events.BAND_UPDATED, band);
                    }
                }
            }

            if (this.onUpdateLane) {
                this.onUpdateLane(id, { lane_type: newValue });
            }
            this.eventBus.emit(Events.LANE_PROPERTY_CHANGED, { id, field: 'lane_type', value: newValue });
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
            const mwLabel = isMwReference
                ? 'MW (<span class="gv-unit-text">kDa</span>)'
                : 'Estimated MW (<span class="gv-unit-text">kDa</span>)';
            const mwPlaceholder = isMwReference ? 'e.g., 25, 50, 75...' : 'e.g., 150.0';

            // Check if band is still being saved (race condition protection)
            const isSaving = band._isSaving || false;
            const disabledAttr = isSaving ? 'disabled' : '';
            const savingIndicator = isSaving
                ? '<span id="prop-band-saving" class="gv-saving-indicator"><i class="bi bi-arrow-repeat gv-spin"></i> Saving...</span>'
                : '<span id="prop-band-saving" class="gv-saving-indicator" style="display: none;"></span>';

            // Calibration sub-section data
            const qp = band.quant_point || {};
            const qpAmount = qp.load_amount ?? '';
            const qpUnit = qp.load_unit || 'UG';
            const hasDensito = band.corrected_area != null && band.corrected_area > 0;
            const densitoStatus = hasDensito
                ? '<span class="text-success"><i class="bi bi-check-circle"></i> Densitometry available</span>'
                : '<span class="text-warning"><i class="bi bi-exclamation-triangle"></i> Run densitometry to use this point</span>';

            // The band type's colour comes from the band list's pill classes (the gel's band colours, night and day).
            const bandBadgeClass = `gv-prop-type-badge gv-band-pill--${this._getBandTypeKey(band.band_type)}`;
            const bandTypeLabels = {
                POI: 'POI', MW_REFERENCE: 'MW Ref', CALIBRATION: 'Calibration', OTHER: 'Other',
            };

            this.contentContainer.innerHTML = `
                <div class="gv-prop-form">

                    <div class="gv-prop-header">
                        <span class="gv-prop-lane-badge">
                            <i class="bi bi-pentagon"></i>
                        </span>
                        <div class="gv-prop-header-text">
                            <div class="gv-prop-title">${(band.label || 'Band').replace(/</g, '&lt;')}</div>
                            <span class="${bandBadgeClass}" id="prop-band-type-badge">${bandTypeLabels[band.band_type] || 'Other'}</span>
                        </div>
                        ${savingIndicator}
                    </div>

                    <div id="prop-band-role">${this._roleLine(band)}</div>

                    <section class="gv-prop-section">
                        <h6 class="gv-prop-section-title">Identity</h6>
                        <div class="gv-prop-grid">
                            <div class="gv-prop-field gv-prop-col-2">
                                <label for="prop-band-type">Band type</label>
                                <select id="prop-band-type" data-field="band_type" class="form-select form-select-sm" ${disabledAttr}>
                                    <option value="OTHER" ${band.band_type === 'OTHER' ? 'selected' : ''}>Other</option>
                                    <option value="POI" ${band.band_type === 'POI' ? 'selected' : ''}>Protein of Interest</option>
                                    <option value="MW_REFERENCE" ${band.band_type === 'MW_REFERENCE' ? 'selected' : ''}>MW Reference</option>
                                    <option value="CALIBRATION" ${isCalibration ? 'selected' : ''}>Calibration Point</option>
                                </select>
                            </div>
                            <div class="gv-prop-field gv-prop-col-2">
                                <label for="prop-label">Label</label>
                                <input type="text" id="prop-label" data-field="label" class="form-control form-control-sm"
                                       value="${(band.label || '').replace(/"/g, '&quot;')}" placeholder="e.g., Main product">
                            </div>
                            <div class="gv-prop-field gv-prop-col-2">
                                <label for="prop-mw" id="prop-mw-label">${mwLabel}</label>
                                <input type="number" id="prop-mw" data-field="estimated_mw_kda" class="form-control form-control-sm"
                                       value="${band.estimated_mw_kda != null ? Number(band.estimated_mw_kda).toFixed(1) : ''}" step="0.1" placeholder="${mwPlaceholder}">
                            </div>
                        </div>
                    </section>

                    <section class="gv-prop-section" id="prop-band-calib-section"
                             style="display: ${isCalibration ? '' : 'none'};">
                        <h6 class="gv-prop-section-title">
                            <i class="bi bi-graph-up"></i> Calibration
                        </h6>
                        <div class="gv-prop-grid">
                            <div class="gv-prop-field">
                                <label for="prop-band-load-amount">Loaded amount</label>
                                <input type="number" id="prop-band-load-amount" data-field="quant_load_amount"
                                       class="form-control form-control-sm"
                                       min="0" step="0.01" value="${qpAmount}" placeholder="—">
                            </div>
                            <div class="gv-prop-field">
                                <label for="prop-band-load-unit">Unit</label>
                                <select id="prop-band-load-unit" data-field="quant_load_unit" class="form-select form-select-sm">
                                    <option value="UG" ${qpUnit === 'UG' ? 'selected' : ''}>µg</option>
                                    <option value="UG_ML" ${qpUnit === 'UG_ML' ? 'selected' : ''}>µg/mL</option>
                                </select>
                                <small class="gv-prop-hint" id="prop-band-load-unit-hint" style="display: none;">
                                    Unit fixed by active calibration
                                </small>
                            </div>
                            <div class="gv-prop-field gv-prop-col-2">
                                <small id="prop-band-densito-status">${densitoStatus}</small>
                            </div>
                        </div>
                    </section>

                    <section class="gv-prop-section">
                        <h6 class="gv-prop-section-title">Notes</h6>
                        <div class="gv-prop-grid">
                            <div class="gv-prop-field gv-prop-col-2">
                                <textarea id="prop-band-notes" data-field="notes" class="form-control form-control-sm" rows="2">${escapeHtml(band.notes || '')}</textarea>
                            </div>
                        </div>
                    </section>

                    <div id="prop-band-save-error" class="gv-prop-save-error" style="display: none;">
                        <i class="bi bi-exclamation-triangle-fill"></i>
                        <span id="prop-band-save-error-msg" class="gv-prop-save-error-msg"></span>
                        <button type="button" id="prop-band-save-retry" class="gv-prop-save-retry">
                            <i class="bi bi-arrow-clockwise"></i> Retry
                        </button>
                    </div>
                    <div class="gv-prop-actions">
                        <button class="btn btn-sm btn-primary" id="prop-save-band-btn">
                            <i class="bi bi-save me-1"></i> Save
                        </button>
                        <button class="btn btn-sm btn-outline-danger" id="prop-delete-band-btn">
                            <i class="bi bi-trash me-1"></i> Delete
                        </button>
                    </div>
                </div>
            `;

            this._setupBandListeners(band);

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
         * Setup event listeners for band properties fields. Every handler reads `band.id` when it runs, as the lane
         * form does (_setupLaneListeners): a band drawn in a saved lane gets its server id a moment after its form
         * opens (GelViewerApp._createBand), one in a new lane at the Save (_batchSave).
         * @param {Object} band - The band shown: the StateManager's own object
         */
        _setupBandListeners(band) {
            // Save button
            const saveBtn = document.getElementById('prop-save-band-btn');
            if (saveBtn) {
                saveBtn.addEventListener('click', () => this._saveBandProperties(band.id));
            }

            // Delete button
            const deleteBtn = document.getElementById('prop-delete-band-btn');
            if (deleteBtn && this.onDeleteBand) {
                deleteBtn.addEventListener('click', () => this.onDeleteBand(band.id));
            }

            // Band type change - update MW label dynamically + toggle Calibration section + track change
            const bandTypeSelect = document.getElementById('prop-band-type');
            const mwLabel = document.getElementById('prop-mw-label');
            const mwInput = document.getElementById('prop-mw');
            const calibSection = document.getElementById('prop-band-calib-section');
            if (bandTypeSelect && mwLabel && mwInput) {
                bandTypeSelect.addEventListener('change', (e) => {
                    const newType = e.target.value;
                    // Update MW label
                    const isMwReference = newType === 'MW_REFERENCE';
                    mwLabel.innerHTML = isMwReference
                        ? 'MW (<span class="gv-unit-text">kDa</span>)'
                        : 'Estimated MW (<span class="gv-unit-text">kDa</span>)';
                    mwInput.placeholder = isMwReference ? 'e.g., 25, 50, 75...' : 'e.g., 150.0';
                    // Toggle the Calibration section (load amount + unit)
                    if (calibSection) {
                        calibSection.style.display = newType === 'CALIBRATION' ? '' : 'none';
                    }
                    // Update the band type badge in the header
                    const typeBadge = document.getElementById('prop-band-type-badge');
                    if (typeBadge) {
                        const labels = { POI: 'POI', MW_REFERENCE: 'MW Ref', CALIBRATION: 'Calibration', OTHER: 'Other' };
                        typeBadge.textContent = labels[newType] || 'Other';
                        typeBadge.className = `gv-prop-type-badge gv-band-pill--${this._getBandTypeKey(newType)}`;
                    }
                    // Track the change immediately
                    this._handleBandChange(band.id, e.target);
                });
            }

            // Calibration sub-form: load_amount + load_unit auto-save on
            // blur / Enter. Goes through the v1 PATCH so the nested
            // quant_point is validated, flashes the input green on success.
            const loadAmountInput = document.getElementById('prop-band-load-amount');
            const loadUnitSelect = document.getElementById('prop-band-load-unit');
            if (loadAmountInput) {
                loadAmountInput.addEventListener('blur', () => {
                    this._autoSaveCalibrationValue(band.id, loadAmountInput);
                });
                loadAmountInput.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        loadAmountInput.blur();
                    }
                });
            }
            if (loadUnitSelect) {
                loadUnitSelect.addEventListener('change', () => {
                    this._autoSaveCalibrationValue(band.id, loadUnitSelect);
                });
            }

            // Other select fields - immediate update
            this.contentContainer.querySelectorAll('select[data-field]:not(#prop-band-type)').forEach(select => {
                select.addEventListener('change', (e) => {
                    this._handleBandChange(band.id, e.target);
                });
            });

            // Input/textarea fields - debounced update
            this.contentContainer.querySelectorAll('input[data-field], textarea[data-field]').forEach(input => {
                let debounceTimer;
                input.addEventListener('input', (e) => {
                    clearTimeout(debounceTimer);
                    debounceTimer = setTimeout(() => {
                        this._handleBandChange(band.id, e.target);
                    }, 300);
                });
                input.addEventListener('blur', (e) => {
                    clearTimeout(debounceTimer);
                    this._handleBandChange(band.id, e.target);
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

            // The Calibration sub-fields are saved via _autoSaveCalibrationValue
            // (so amount + unit are persisted atomically as a quant_point payload).
            // Don't push individual changes through onUpdateBand which would
            // fire a partial update that the v1 serializer can't validate.
            if (field === 'quant_load_amount' || field === 'quant_load_unit') {
                return;
            }
            // CALIBRATION is saved with its loaded amount or not at all (owner, 2026-10-13; the band PUT refuses it
            // alone): the select opens the Calibration section, and the amount's save sends the type with it
            // (_autoSaveCalibrationValue). Until then the band keeps its type, here and on the server.
            if (field === 'band_type' && value === 'CALIBRATION') {
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
         * Fetch and cache the unit of the active quantification calibration
         * for this analysis. When an active calibration exists, every new
         * CALIBRATION point must use the same unit so we lock the select.
         * @returns {Promise<string|null>} 'UG' | 'UG_ML' | null when no active
         */
        async _getActiveCalibUnit() {
            if (this._activeCalibUnitCache !== undefined) {
                return this._activeCalibUnitCache;
            }
            if (!this.apiClient || typeof this.apiClient.getActiveQuantification !== 'function') {
                this._activeCalibUnitCache = null;
                return null;
            }
            try {
                const resp = await this.apiClient.getActiveQuantification();
                this._activeCalibUnitCache = resp?.active?.unit || null;
            } catch (err) {
                console.warn('Could not load active quantification:', err);
                this._activeCalibUnitCache = null;
            }
            return this._activeCalibUnitCache;
        }

        /**
         * Mirror locally a band the v1 PATCH saved CALIBRATION with its amount. The type is saved only there
         * (_handleBandChange sends no lone CALIBRATION): when it changes now, the band's colour, the tables and the
         * lane follow through onSyncBandLocal, as for any type change; a later amount edit only updates the band.
         * @param {string|number} bandId
         * @param {Object} payload - The PATCH sent: band_type, quant_point (+ the form's fields on an explicit Save)
         */
        _mirrorSavedCalibration(bandId, payload) {
            const band = this.stateManager && this.stateManager.getBand ? this.stateManager.getBand(bandId) : null;
            if (!band) return;
            if (band.band_type !== 'CALIBRATION' && this.onSyncBandLocal) {
                this.onSyncBandLocal(bandId, payload);
                return;
            }
            Object.assign(band, payload);
        }

        /**
         * Auto-save the calibration loaded amount + unit on blur / Enter.
         * Sends band_type + quant_point through the v1 PATCH so the
         * BandSerializer validates atomically (auto-promotes the lane to
         * CALIBRATION on the server side via band_type_change.apply_band_type).
         * Silent on validation issues (empty / non-numeric / negative);
         * flashes the input green for ~1.2s on success.
         */
        _autoSaveCalibrationValue(bandId, sourceInput) {
            const bandTypeSelect = document.getElementById('prop-band-type');
            if (!bandTypeSelect || bandTypeSelect.value !== 'CALIBRATION') return;
            const amountStr = document.getElementById('prop-band-load-amount')?.value;
            const unit = document.getElementById('prop-band-load-unit')?.value || 'UG';
            if (amountStr === '' || amountStr == null) return;
            const amount = parseFloat(amountStr);
            if (!isFinite(amount) || amount < 0) return;

            const payload = {
                band_type: 'CALIBRATION',
                quant_point: { load_amount: amount, load_unit: unit },
            };

            if (!this.apiClient || typeof this.apiClient.patchBand !== 'function') return;

            this.apiClient.patchBand(bandId, payload).then(() => {
                this._mirrorSavedCalibration(bandId, payload);
                // Server may have auto-promoted the parent lane to CALIBRATION.
                // Refresh active calib unit cache + emit event for table sync.
                this._activeCalibUnitCache = undefined;
                // The form is drawn again when the type was saved now: the input to flash is the new one.
                this._flashSavedInput((sourceInput && document.getElementById(sourceInput.id)) || sourceInput);
                this._setSaveErrorState(null);
                this.eventBus.emit(Events.BAND_PROPERTY_CHANGED, {
                    id: bandId, field: 'quant_point', value: payload.quant_point,
                });
            }).catch(err => {
                console.error('Auto-save calibration value failed:', err);
                const msg = err && err.message ? err.message : String(err);
                // Reuse the inline error block + Retry button on the form.
                // The retry replays the full _saveBandProperties path so the
                // user gets a single recovery flow regardless of whether
                // the failure came from auto-save or the explicit Save click.
                this._setSaveErrorState(msg, { id: bandId, data: payload });
                if (this.toasts) {
                    this.toasts.error(`Auto-save failed: ${msg}`);
                }
            });
        }

        /**
         * Briefly highlight an input in green to signal "saved".
         */
        _flashSavedInput(input) {
            if (!input) return;
            input.classList.remove('gv-input-saved-flash');
            // Force reflow so the class re-add re-triggers the transition.
            input.offsetWidth;
            input.classList.add('gv-input-saved-flash');
            clearTimeout(input._savedFlashTimer);
            input._savedFlashTimer = setTimeout(() => {
                input.classList.remove('gv-input-saved-flash');
            }, 1200);
        }

        /**
         * Toggle the visibility of an inline error block under the band form.
         * When `errorMessage` is null/empty, the block hides AND the cached
         * failed payload is cleared (so a future Retry click is a no-op
         * instead of replaying a stale payload).
         *
         * When `errorMessage` is set, `retryPayload` should hold {id, data}
         * so the Retry button can re-fire the same save without making the
         * user re-type the form. If omitted (or undefined), the Retry
         * button is hidden — useful for non-recoverable errors.
         */
        _setSaveErrorState(errorMessage, retryPayload) {
            const errorBlock = document.getElementById('prop-band-save-error');
            const errorMsg = document.getElementById('prop-band-save-error-msg');
            const retryBtn = document.getElementById('prop-band-save-retry');
            if (!errorBlock) return;

            if (!errorMessage) {
                errorBlock.style.display = 'none';
                if (errorMsg) errorMsg.textContent = '';
                this._lastFailedPayload = null;
                return;
            }

            errorBlock.style.display = '';
            if (errorMsg) errorMsg.textContent = `Save failed: ${errorMessage}`;
            this._lastFailedPayload = retryPayload || null;

            // Show the Retry button only when we have a payload to replay.
            // Wire it once per error — replace the node to drop any previous
            // listener (cheaper than tracking + removeEventListener for a
            // button that lives in optimistic UI).
            if (retryBtn) {
                if (this._lastFailedPayload) {
                    const fresh = retryBtn.cloneNode(true);
                    retryBtn.parentNode.replaceChild(fresh, retryBtn);
                    fresh.style.display = '';
                    fresh.addEventListener('click', () => this._retryFailedSave());
                } else {
                    retryBtn.style.display = 'none';
                }
            }
        }

        /**
         * Replay the last failed save. The payload was cached by the
         * _saveBandProperties catch branch; calling _saveBandProperties
         * directly would re-read the form, which is what we want — the
         * user may have corrected the value that caused the failure
         * before clicking Retry.
         */
        _retryFailedSave() {
            const payload = this._lastFailedPayload;
            if (!payload || !payload.id) return;
            // Optimistic UX: hide the error block immediately so the user
            // sees the retry is in flight. _setSaveErrorState re-shows it
            // if the retry also fails.
            this._setSaveErrorState(null);
            this._saveBandProperties(payload.id);
        }

        /**
         * Save band properties from form.
         * Routes CALIBRATION saves through v1 PATCH (BandSerializer validation
         * + auto-promote + quant_point mirror) so the nested quant_point
         * payload is validated atomically. Other band types use the legacy
         * onUpdateBand path.
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
                const amount = amountStr === '' || amountStr == null ? null : parseFloat(amountStr);
                if (amount === null || !isFinite(amount) || amount < 0) {
                    const msg = 'Loaded amount is required and must be a positive number for CALIBRATION bands.';
                    if (this.toasts) this.toasts.warning(msg); else console.warn(msg);
                    return;
                }
                payload.quant_point = { load_amount: amount, load_unit: unit };

                // Route CALIBRATION save through v1 PATCH so the BandSerializer
                // validates the quant_point atomically.
                if (this.apiClient && typeof this.apiClient.patchBand === 'function') {
                    try {
                        await this.apiClient.patchBand(id, payload);
                        this._mirrorSavedCalibration(id, payload);
                        this._activeCalibUnitCache = undefined;
                        this._setSaveErrorState(null);
                        if (this.toasts) {
                            this.toasts.success('Calibration band saved');
                        }
                        this.eventBus.emit(Events.BAND_PROPERTY_CHANGED, {
                            id, field: 'band_type', value: bandType,
                        });
                    } catch (err) {
                        const msg = err && err.message ? err.message : String(err);
                        // Cache the failed payload + the band id so the
                        // inline Retry button can replay the save. Drop
                        // the legacy window.alert — toast + inline error
                        // line + Retry button are the new UX.
                        this._setSaveErrorState(msg, { id, data: payload });
                        if (this.toasts) {
                            this.toasts.error(`Could not save band: ${msg}`);
                        }
                    }
                    return;
                }
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
