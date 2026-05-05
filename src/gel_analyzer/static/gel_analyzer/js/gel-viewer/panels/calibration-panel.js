/**
 * calibration-panel.js
 *
 * MW Calibration Panel for ladder-based molecular weight calibration.
 * Right-sliding panel with 4-step workflow: Template → Ladder Lanes → Curve → Apply.
 *
 * @requires GelViewer.EventBus
 * @requires GelViewer.APIClient
 * @requires Plotly (external CDN)
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    /**
     * Calibration methods available.
     */
    const CALIBRATION_METHODS = {
        LOG_LINEAR: 'Log-Linear (recommended)',
        POLYNOMIAL_2: 'Polynomial (degree 2)',
        POLYNOMIAL_3: 'Polynomial (degree 3)',
    };

    /**
     * R² quality thresholds.
     */
    const R2_THRESHOLDS = {
        EXCELLENT: 0.99,
        GOOD: 0.95,
    };

    /**
     * CalibrationPanel Class
     *
     * UI panel for MW ladder calibration workflow.
     */
    class CalibrationPanel {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus - Event bus for communication
         * @param {APIClient} options.apiClient - API client for server requests
         * @param {StateManager} options.stateManager - State manager reference
         * @param {Function} options.onCalibrationApplied - Callback when calibration is applied
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.apiClient = options.apiClient;
            this.stateManager = options.stateManager;
            this.onCalibrationApplied = options.onCalibrationApplied;

            // State
            this.isVisible = false;
            this.isProcessing = false;
            this.templates = [];
            this.selectedTemplate = null;
            this.ladderLanes = [];
            this.matchResults = [];
            this.calibrationResult = null;
            this.isMultiLadder = false;
            this.unmatchedTemplateBands = [];
            this.isStale = false;  // True when calibration may be out of date

            // Per-marker exclusion: ladder band UUIDs the user has dropped from
            // the fit via the marker table checkboxes. Persists between runs
            // so toggling a checkbox re-fits without losing the rest of the
            // selection.
            this.excludedBandIds = new Set();

            // DOM references
            this.panel = null;
            this.chartContainer = null;

            // Initialize
            this._setupDOM();
            this._bindEvents();
        }

        /**
         * Setup DOM references.
         */
        _setupDOM() {
            this.panel = document.getElementById('calibration-panel');
            this.backdrop = document.getElementById('calibration-backdrop');
            this.chartContainer = document.getElementById('calibration-chart');
        }

        /**
         * Bind event listeners.
         */
        _bindEvents() {
            // Close button
            const closeBtn = document.getElementById('calibration-close');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this.hide());
            }

            // Backdrop click to close modal
            if (this.backdrop) {
                this.backdrop.addEventListener('click', () => this.hide());
            }

            // Template select
            const templateSelect = document.getElementById('calibration-template');
            if (templateSelect) {
                templateSelect.addEventListener('change', (e) => {
                    this._onTemplateSelected(e.target.value);
                });
            }

            // Method select
            const methodSelect = document.getElementById('calibration-method');
            if (methodSelect) {
                methodSelect.addEventListener('change', () => {
                    if (this.calibrationResult) {
                        // Re-calibrate with new method
                        this._runCalibration();
                    }
                });
            }

            // Run Calibration button (combined match + calibrate)
            const runBtn = document.getElementById('calibration-run');
            if (runBtn) {
                runBtn.addEventListener('click', () => this._runCalibration());
            }

            // Apply button
            const applyBtn = document.getElementById('calibration-apply');
            if (applyBtn) {
                applyBtn.addEventListener('click', () => this._applyCalibration());
            }

            // Reset button
            const resetBtn = document.getElementById('calibration-reset');
            if (resetBtn) {
                resetBtn.addEventListener('click', () => this._reset());
            }

            // Keyboard shortcuts
            document.addEventListener('keydown', (e) => {
                if (!this.isVisible) return;

                if (e.key === 'Escape') {
                    this.hide();
                }
            });

            // Listen for lane changes
            this.eventBus.on(Events.LANE_CREATED, () => this._updateLadderLanes());
            this.eventBus.on(Events.LANE_DELETED, () => this._onLaneDeleted());
            this.eventBus.on(Events.LANES_BULK_CREATED, () => this._updateLadderLanes());
            this.eventBus.on(Events.DATA_LOADED, () => {
                if (this.isVisible) {
                    this._updateLadderLanes();
                }
            });

            // Listen for band changes in ladder lanes
            this.eventBus.on(Events.BAND_CREATED, (data) => this._onBandChanged(data, 'created'));
            this.eventBus.on(Events.BAND_DELETED, (data) => this._onBandChanged(data, 'deleted'));
            this.eventBus.on(Events.BAND_UPDATED, (data) => this._onBandChanged(data, 'updated'));

            // Listen for bulk operations (e.g., "Remove All Bands")
            // DATA_RELOAD_REQUESTED is emitted after bulk deletions
            this.eventBus.on(Events.DATA_RELOAD_REQUESTED, () => this._onDataReloadRequested());

            // Listen for MW values applied (e.g., from Band Editor template)
            // This refreshes the ladder lanes view when MW values are assigned
            this.eventBus.on(Events.MW_BANDS_UPDATED, (data) => this._onMWBandsUpdated(data));
        }

        /**
         * Show the calibration panel (modal).
         */
        show() {
            // Load templates if not already loaded
            if (this.templates.length === 0) {
                this._loadTemplates();
            }

            this._updateLadderLanes();

            if (this.backdrop) {
                this.backdrop.style.display = 'block';
            }
            if (this.panel) {
                this.panel.style.display = 'flex';
                // Force reflow for animation
                this.panel.offsetHeight;
                requestAnimationFrame(() => {
                    if (this.backdrop) this.backdrop.classList.add('open');
                    this.panel.classList.add('open');

                    // Load existing calibration AFTER modal is visible
                    // This ensures Plotly chart renders correctly
                    setTimeout(() => {
                        this._loadExistingCalibration();
                    }, 350); // Wait for animation to complete
                });
            }

            this.isVisible = true;

            this.eventBus.emit(Events.CALIBRATION_PANEL_SHOWN);
        }

        /**
         * Hide the calibration panel (modal).
         */
        hide() {
            if (this.panel) {
                this.panel.classList.remove('open');
            }
            if (this.backdrop) {
                this.backdrop.classList.remove('open');
            }

            // Delay hiding to allow animation
            setTimeout(() => {
                if (!this.isVisible) {
                    if (this.panel) this.panel.style.display = 'none';
                    if (this.backdrop) this.backdrop.style.display = 'none';
                }
            }, 350);

            this.isVisible = false;

            this.eventBus.emit(Events.CALIBRATION_PANEL_HIDDEN);
        }

        /**
         * Toggle panel visibility.
         */
        toggle() {
            if (this.isVisible) {
                this.hide();
            } else {
                this.show();
            }
        }

        /**
         * Load ladder templates from server.
         */
        async _loadTemplates() {
            const select = document.getElementById('calibration-template');
            if (!select) return;

            try {
                const response = await this.apiClient.getLadderTemplates();
                this.templates = response.templates || [];

                // Clear and populate select
                select.innerHTML = '<option value="">Select a template...</option>';

                // Group by manufacturer
                const grouped = this._groupByManufacturer(this.templates);

                for (const [manufacturer, templates] of Object.entries(grouped)) {
                    const optgroup = document.createElement('optgroup');
                    optgroup.label = manufacturer;

                    for (const template of templates) {
                        const option = document.createElement('option');
                        option.value = template.id;
                        option.textContent = template.name;
                        optgroup.appendChild(option);
                    }

                    select.appendChild(optgroup);
                }

            } catch (error) {
                console.error('Failed to load templates:', error);
                select.innerHTML = '<option value="">Failed to load templates</option>';
            }
        }

        /**
         * Group templates by manufacturer.
         */
        _groupByManufacturer(templates) {
            const grouped = {};
            for (const template of templates) {
                const mfr = template.manufacturer || 'Other';
                if (!grouped[mfr]) {
                    grouped[mfr] = [];
                }
                grouped[mfr].push(template);
            }
            return grouped;
        }

        /**
         * Handle template selection.
         */
        async _onTemplateSelected(templateId) {
            const infoEl = document.getElementById('calibration-template-info');

            if (!templateId) {
                this.selectedTemplate = null;
                if (infoEl) infoEl.style.display = 'none';
                this._updateFooterHint('Select a template to begin calibration.');
                return;
            }

            try {
                const template = await this.apiClient.getLadderTemplate(templateId);
                this.selectedTemplate = template;

                // Update template info display
                if (infoEl) {
                    infoEl.style.display = 'block';
                    document.getElementById('calibration-template-manufacturer').textContent =
                        template.manufacturer || '-';
                    document.getElementById('calibration-template-bands').textContent =
                        `${template.bands?.length || 0} bands`;

                    // Calculate range
                    const bands = template.bands || [];
                    if (bands.length > 0) {
                        const mws = bands.map(b => b.mw_kda);
                        const min = Math.min(...mws);
                        const max = Math.max(...mws);
                        document.getElementById('calibration-template-range').textContent =
                            `${min} - ${max} kDa`;
                    }
                }

                // Enable the Run Calibration button
                this._enableRunButton();

                this.eventBus.emit(Events.CALIBRATION_TEMPLATE_SELECTED, {
                    templateId: template.id,
                    templateName: template.name,
                });

            } catch (error) {
                console.error('Failed to load template:', error);
                this._showMessage('Failed to load template');
            }
        }

        /**
         * Update ladder lanes list.
         */
        _updateLadderLanes() {
            const lanesMap = this.stateManager?.getAllLanes();
            const allLanes = lanesMap ? Array.from(lanesMap.values()) : [];
            this.ladderLanes = allLanes.filter(l => l.lane_type === 'LADDER');
            this.isMultiLadder = this.ladderLanes.length > 1;

            this._renderLadderList();
            this._updateMultiLadderInfo();
            this._checkBandCounts();

            // Auto-select template from LADDER lane if set and no template selected
            if (!this.selectedTemplate && this.ladderLanes.length > 0) {
                const laneWithTemplate = this.ladderLanes.find(l => l.ladder_template_id);
                if (laneWithTemplate) {
                    const select = document.getElementById('calibration-template');
                    if (select && !select.value) {
                        select.value = laneWithTemplate.ladder_template_id;
                        this._onTemplateSelected(laneWithTemplate.ladder_template_id);
                    }
                }
            }
        }

        /**
         * Check band counts and MW assignment status.
         * Uses stateManager.getBandsForLane() for fresh band data.
         */
        _checkBandCounts() {
            const minBands = 3;
            const warning = document.getElementById('calibration-band-warning');
            if (!warning) return;

            // Get fresh band data from StateManager (not from cached lane.bands)
            const lanesBandData = this.ladderLanes.map(lane => {
                const bands = this.stateManager?.getBandsForLane(lane.id) || lane.bands || [];
                return { lane, bands };
            });

            // Check for lanes with insufficient bands
            const insufficientBandLanes = lanesBandData.filter(({ bands }) =>
                bands.length < minBands
            );

            // Check for lanes with bands but no MW assigned
            const noMWLanes = lanesBandData.filter(({ bands }) => {
                if (bands.length < minBands) return false;
                const bandsWithMW = bands.filter(b =>
                    b.estimated_mw_kda !== null && b.estimated_mw_kda !== undefined && b.estimated_mw_kda > 0
                ).length;
                return bandsWithMW < minBands;
            });

            if (insufficientBandLanes.length > 0) {
                const laneNumbers = insufficientBandLanes.map(({ lane }) => `#${lane.lane_number || '?'}`).join(', ');
                warning.innerHTML = `
                    <i class="bi bi-exclamation-triangle-fill"></i>
                    <span>Lanes ${laneNumbers} have fewer than 3 bands. Run band detection first.</span>
                `;
                warning.style.display = 'flex';
            } else if (noMWLanes.length > 0) {
                const laneNumbers = noMWLanes.map(({ lane }) => `#${lane.lane_number || '?'}`).join(', ');
                warning.innerHTML = `
                    <i class="bi bi-exclamation-triangle-fill"></i>
                    <span>Lanes ${laneNumbers} need MW values assigned. Use Band Editor or apply a ladder template.</span>
                `;
                warning.style.display = 'flex';
            } else {
                warning.style.display = 'none';
            }
        }

        /**
         * Show warning for lanes with insufficient bands.
         * @deprecated Use _checkBandCounts instead
         */
        _showBandCountWarning(lanes) {
            const warning = document.getElementById('calibration-band-warning');
            if (!warning) return;

            const laneNumbers = lanes.map(l => `#${l.lane_number || '?'}`).join(', ');
            warning.innerHTML = `
                <i class="bi bi-exclamation-triangle-fill"></i>
                <span>Lanes ${laneNumbers} have fewer than 3 bands. Run band detection first.</span>
            `;
            warning.style.display = 'flex';
        }

        /**
         * Hide band count warning.
         */
        _hideBandCountWarning() {
            const warning = document.getElementById('calibration-band-warning');
            if (warning) {
                warning.style.display = 'none';
            }
        }

        /**
         * Handle band changes (create/update/delete) to detect calibration staleness.
         * @param {Object} data - Event data with band info
         * @param {string} action - 'created', 'updated', or 'deleted'
         */
        _onBandChanged(data, action) {
            if (!data) return;

            // Get the lane ID from band data
            const laneId = data.lane_id || data.laneId || data._parentLaneId;
            if (!laneId) return;

            // Check if this band is in a ladder lane
            const lane = this.stateManager?.getLane(laneId);
            if (!lane || lane.lane_type !== 'LADDER') return;

            // Band in a ladder lane was changed - mark calibration as stale
            if (this.calibrationResult) {
                this._markCalibrationStale(`Ladder lane #${lane.lane_number} was modified (band ${action})`);
            }

            // Update ladder lanes display if panel is visible
            if (this.isVisible) {
                this._updateLadderLanes();
            }
        }

        /**
         * Handle lane deletion - check if it affects calibration.
         */
        _onLaneDeleted() {
            // Check if any ladder lanes were deleted
            const previousLadderCount = this.ladderLanes.length;
            this._updateLadderLanes();

            // If ladder lanes decreased and we have calibration, mark as stale
            if (this.calibrationResult && this.ladderLanes.length < previousLadderCount) {
                this._markCalibrationStale('A ladder lane was deleted');
            }
        }

        /**
         * Handle data reload request (e.g., after bulk band deletion).
         * Check if ladder lane band counts changed significantly.
         */
        _onDataReloadRequested() {
            if (!this.calibrationResult) return;

            // Store previous band counts per ladder lane
            const previousCounts = {};
            for (const lane of this.ladderLanes) {
                previousCounts[lane.id] = this.stateManager?.getBandsForLane(lane.id)?.length || 0;
            }

            // Re-check ladder lanes after short delay (to let state update)
            setTimeout(() => {
                let bandsChanged = false;

                for (const lane of this.ladderLanes) {
                    const currentCount = this.stateManager?.getBandsForLane(lane.id)?.length || 0;
                    const prevCount = previousCounts[lane.id] || 0;

                    if (currentCount !== prevCount) {
                        bandsChanged = true;
                        console.log(`[CalibrationPanel] Ladder lane #${lane.lane_number} band count changed: ${prevCount} → ${currentCount}`);
                    }
                }

                if (bandsChanged) {
                    this._markCalibrationStale('Ladder lane bands were modified (bulk operation)');
                    if (this.isVisible) {
                        this._updateLadderLanes();
                    }
                }
            }, 100);
        }

        /**
         * Handle MW_BANDS_UPDATED event (e.g., from Band Editor template application).
         * Refreshes the ladder lanes display to show updated MW status.
         * @param {Object} data - Event data with laneId, templateName, bandsUpdated
         */
        _onMWBandsUpdated(data) {
            console.log('[CalibrationPanel] MW_BANDS_UPDATED event:', data);

            // Refresh ladder lanes to get updated band data
            this._updateLadderLanes();

            // If panel is visible, re-check band counts / MW status
            if (this.isVisible) {
                this._checkBandCounts();
            }
        }

        /**
         * Mark calibration as stale (out of date).
         * @param {string} reason - Why calibration is stale
         */
        _markCalibrationStale(reason) {
            if (this.isStale) return;  // Already marked

            this.isStale = true;
            console.warn('CalibrationPanel: Calibration marked as stale -', reason);

            // Update UI to show stale warning
            this._showStaleWarning(reason);

            // Emit event for other modules
            this.eventBus.emit('calibration:stale', { reason });
        }

        /**
         * Clear stale state (after recalibration).
         */
        _clearStaleState() {
            this.isStale = false;
            this._hideStaleWarning();
        }

        /**
         * Show stale calibration warning in the UI.
         * @param {string} reason - Why calibration is stale
         */
        _showStaleWarning(reason) {
            // Find or create warning element
            let warning = document.getElementById('calibration-stale-warning');
            if (!warning) {
                warning = document.createElement('div');
                warning.id = 'calibration-stale-warning';
                warning.className = 'gv-calibration-stale-warning';

                // Insert after R² display in Step 4
                const r2Container = document.getElementById('calibration-r2');
                if (r2Container) {
                    r2Container.parentNode.insertBefore(warning, r2Container.nextSibling);
                }
            }

            warning.innerHTML = `
                <i class="bi bi-exclamation-triangle-fill text-warning"></i>
                <div>
                    <strong>Recalibration recommended</strong>
                    <span>${reason || 'Ladder data has changed since last calibration'}</span>
                </div>
            `;
            warning.style.display = 'flex';
        }

        /**
         * Hide stale calibration warning.
         */
        _hideStaleWarning() {
            const warning = document.getElementById('calibration-stale-warning');
            if (warning) {
                warning.style.display = 'none';
            }
        }

        /**
         * Render the ladder lanes list.
         * Uses stateManager.getBandsForLane() for fresh band data.
         */
        _renderLadderList() {
            const listEl = document.getElementById('calibration-ladder-list');
            const actionsEl = document.getElementById('calibration-ladder-actions');

            if (!listEl) return;

            if (this.ladderLanes.length === 0) {
                listEl.innerHTML = `
                    <div class="gv-calibration-empty">
                        <i class="bi bi-exclamation-triangle text-warning"></i>
                        <p>No ladder lanes found. Mark lanes as "Ladder" type first.</p>
                    </div>
                `;
                if (actionsEl) actionsEl.style.display = 'none';
                return;
            }

            listEl.innerHTML = this.ladderLanes.map(lane => {
                // Get fresh band data from StateManager (not from cached lane.bands)
                const bands = this.stateManager?.getBandsForLane(lane.id) || lane.bands || [];
                const bandCount = bands.length;
                // Count bands with MW assigned (estimated_mw_kda is not null and not 0)
                const bandsWithMW = bands.filter(b =>
                    b.estimated_mw_kda !== null && b.estimated_mw_kda !== undefined && b.estimated_mw_kda > 0
                ).length;

                const matchResult = this.matchResults.find(r => r.laneId === lane.id);

                // Determine status: check if bands have MW assigned
                let statusIcon, statusClass, mwStatus;
                if (bandsWithMW >= 3) {
                    // Enough bands with MW for calibration
                    statusIcon = '<i class="bi bi-check-circle-fill text-success"></i>';
                    statusClass = 'ready';
                    mwStatus = `<span class="mw-status mw-ok">${bandsWithMW} MW</span>`;
                } else if (bandsWithMW > 0) {
                    // Some bands have MW but not enough
                    statusIcon = '<i class="bi bi-exclamation-circle-fill text-warning"></i>';
                    statusClass = 'partial';
                    mwStatus = `<span class="mw-status mw-partial">${bandsWithMW}/${bandCount} MW</span>`;
                } else {
                    // No bands have MW assigned
                    statusIcon = '<i class="bi bi-x-circle-fill text-danger"></i>';
                    statusClass = 'no-mw';
                    mwStatus = `<span class="mw-status mw-none">No MW</span>`;
                }

                return `
                    <div class="gv-calibration-ladder-item ${statusClass}" data-lane-id="${lane.id}">
                        <div class="gv-calibration-ladder-info">
                            <span class="lane-number">#${lane.lane_number || '?'}</span>
                            <span class="band-count">${bandCount} bands</span>
                            ${mwStatus}
                        </div>
                        <div class="gv-calibration-ladder-status">
                            ${statusIcon}
                        </div>
                    </div>
                `;
            }).join('');

            if (actionsEl) {
                actionsEl.style.display = this.selectedTemplate ? 'flex' : 'none';
            }
        }

        /**
         * Update multi-ladder info display.
         */
        _updateMultiLadderInfo() {
            const infoEl = document.getElementById('calibration-multi-info');
            if (infoEl) {
                infoEl.style.display = this.isMultiLadder ? 'block' : 'none';
            }

            // Update calibrate button text
            const calibrateText = document.getElementById('calibration-calibrate-text');
            if (calibrateText) {
                calibrateText.textContent = this.isMultiLadder ?
                    'Calibrate All Ladders' : 'Calibrate';
            }
        }

        /**
         * Match template to ladder lane bands.
         */
        async _matchTemplate() {
            if (!this.selectedTemplate || this.ladderLanes.length === 0) {
                this._showMessage('Select a template and ensure ladder lanes exist');
                return;
            }

            if (this.isProcessing) return;
            this.isProcessing = true;

            try {
                this.matchResults = [];

                for (const lane of this.ladderLanes) {
                    const result = await this.apiClient.matchTemplate(
                        lane.id,
                        this.selectedTemplate.id
                    );

                    this.matchResults.push({
                        laneId: lane.id,
                        laneNumber: lane.lane_number,
                        matches: result.matches || [],
                        r2Preview: result.r2_preview,
                    });
                }

                this._renderLadderList();
                this._renderCalibrationPreview();
                this._enableRunButton();
                this._updateFooterHint('Review the preview, then click "Run Calibration".');

                this.eventBus.emit(Events.CALIBRATION_TEMPLATE_MATCHED, {
                    templateId: this.selectedTemplate.id,
                    ladderCount: this.ladderLanes.length,
                    matchResults: this.matchResults,
                });

            } catch (error) {
                console.error('Failed to match template:', error);
                this._showMessage('Failed to match template to bands');
            } finally {
                this.isProcessing = false;
            }
        }

        /**
         * Render calibration curve preview with Plotly.
         */
        _renderCalibrationPreview() {
            if (!this.chartContainer || this.matchResults.length === 0) return;

            // Clear empty state
            const emptyEl = this.chartContainer.querySelector('.gv-calibration-chart-empty');
            if (emptyEl) emptyEl.style.display = 'none';

            // Prepare data for all ladder lanes
            const traces = [];
            const colors = ['#8b5cf6', '#10b981', '#f59e0b', '#ef4444'];

            for (let i = 0; i < this.matchResults.length; i++) {
                const result = this.matchResults[i];
                const matches = result.matches || [];

                // Extract Rf and log(MW) values
                const xValues = matches.map(m => m.rf);
                const yValues = matches.map(m => Math.log10(m.mw_kda));

                traces.push({
                    x: xValues,
                    y: yValues,
                    mode: 'markers',
                    type: 'scatter',
                    name: `Ladder #${result.laneNumber || (i + 1)}`,
                    marker: {
                        color: colors[i % colors.length],
                        size: 10,
                        symbol: 'circle',
                    },
                    hovertemplate: 'Rf: %{x:.3f}<br>MW: %{customdata:.1f} kDa<extra></extra>',
                    customdata: matches.map(m => m.mw_kda),
                });
            }

            // Add trend line for first ladder (preview)
            if (this.matchResults.length > 0 && this.matchResults[0].matches.length > 1) {
                const matches = this.matchResults[0].matches;
                const xVals = matches.map(m => m.rf);
                const yVals = matches.map(m => Math.log10(m.mw_kda));

                // Simple linear regression for preview
                const { slope, intercept } = this._linearRegression(xVals, yVals);

                const xRange = [Math.min(...xVals), Math.max(...xVals)];
                traces.push({
                    x: xRange,
                    y: xRange.map(x => slope * x + intercept),
                    mode: 'lines',
                    type: 'scatter',
                    name: 'Fit (preview)',
                    line: {
                        color: '#8b5cf6',
                        width: 2,
                        dash: 'dash',
                    },
                    hoverinfo: 'skip',
                });
            }

            const layout = {
                margin: { l: 50, r: 20, t: 20, b: 45 },
                xaxis: {
                    title: { text: 'Rf (Relative Migration)', font: { size: 12, color: '#5b21b6' } },
                    tickfont: { size: 10, color: '#4b5563' },
                    range: [0, 1],
                    gridcolor: '#e5e7eb',
                    linecolor: '#8b5cf6',
                    linewidth: 2,
                    showgrid: true,
                    zeroline: true,
                    zerolinecolor: '#d1d5db',
                },
                yaxis: {
                    title: { text: 'log₁₀(MW) kDa', font: { size: 12, color: '#5b21b6' } },
                    tickfont: { size: 10, color: '#4b5563' },
                    gridcolor: '#e5e7eb',
                    linecolor: '#8b5cf6',
                    linewidth: 2,
                    showgrid: true,
                    zeroline: true,
                    zerolinecolor: '#d1d5db',
                },
                showlegend: this.matchResults.length > 1,
                legend: {
                    font: { size: 10 },
                    x: 0.02,
                    y: 0.98,
                    bgcolor: 'rgba(255,255,255,0.9)',
                },
                paper_bgcolor: '#ffffff',
                plot_bgcolor: '#ffffff',
            };

            const config = {
                responsive: true,
                displayModeBar: false,
            };

            if (typeof Plotly !== 'undefined') {
                Plotly.newPlot(this.chartContainer, traces, layout, config);
            }
        }

        /**
         * Simple linear regression for preview.
         */
        _linearRegression(x, y) {
            const n = x.length;
            const sumX = x.reduce((a, b) => a + b, 0);
            const sumY = y.reduce((a, b) => a + b, 0);
            const sumXY = x.reduce((acc, xi, i) => acc + xi * y[i], 0);
            const sumXX = x.reduce((acc, xi) => acc + xi * xi, 0);

            const slope = (n * sumXY - sumX * sumY) / (n * sumXX - sumX * sumX);
            const intercept = (sumY - slope * sumX) / n;

            return { slope, intercept };
        }

        /**
         * Enable the Run Calibration button.
         */
        _enableRunButton() {
            const btn = document.getElementById('calibration-run');
            if (btn) btn.disabled = false;

            // Method section is now always visible in Step 3, no need to show/hide

            this._updateFooterHint('Ready to calibrate. Click "Run Calibration".');
        }

        /**
         * Disable the Run Calibration button.
         */
        _disableRunButton() {
            const btn = document.getElementById('calibration-run');
            if (btn) btn.disabled = true;
        }

        /**
         * Render the per-marker table (checkbox + name + Y + residual %).
         *
         * Lets the user drop high-residual outlier markers from the fit
         * without leaving the modal — toggling a checkbox re-runs the
         * calibration with the updated exclusion list. Multi-ladder results
         * are split into one section per ladder so a marker bad on one
         * ladder lane can still be kept on the other.
         */
        _renderMarkersTable(result) {
            const body = document.getElementById('calibration-markers-body');
            const wrapper = document.getElementById('calibration-markers');
            if (!body || !wrapper) return;

            // Normalise the API response: single vs multi-ladder shapes differ.
            let calibrations;
            if (result.calibrations) {
                calibrations = result.calibrations;
            } else if (result.result) {
                calibrations = [result.result];
            } else {
                calibrations = [result];
            }

            // Sync excludedBandIds with what the server persisted (covers reload
            // from existing calibration where the user wasn't the one who set it).
            const persisted = new Set();
            for (const cal of calibrations) {
                for (const id of (cal.excluded_band_ids || [])) {
                    persisted.add(String(id));
                }
            }
            // Keep transient session exclusions union with persisted state.
            for (const id of persisted) this.excludedBandIds.add(id);

            const allMatches = calibrations.flatMap(cal => (cal.band_matches || []).map(m => ({ ...m, _calibration_id: cal.calibration_id })));
            if (allMatches.length === 0) {
                wrapper.style.display = 'none';
                return;
            }
            wrapper.style.display = '';

            const fmt = (v, digits = 2) => (v == null ? '–' : Number(v).toFixed(digits));
            const residualClass = (pct) => {
                if (pct == null) return 'is-na';
                const a = Math.abs(pct);
                if (a < 5) return 'is-excellent';
                if (a < 15) return 'is-acceptable';
                return 'is-poor';
            };

            const rows = [];
            const isMulti = calibrations.length > 1;

            for (const cal of calibrations) {
                const matches = (cal.band_matches || []).slice().sort((a, b) => (b.mw_kda || 0) - (a.mw_kda || 0));
                if (isMulti) {
                    rows.push(`<div class="gv-calibration-marker-group-header">Ladder #${cal.calibration_id?.slice(0, 6) || ''} (X=${cal.ladder_x_position ?? '–'})</div>`);
                }
                if (matches.length === 0) {
                    rows.push('<div class="gv-calibration-marker-group-header" style="color:#dc2626">No matched markers (all excluded?)</div>');
                    continue;
                }
                for (const m of matches) {
                    const id = String(m.band_id);
                    const excluded = this.excludedBandIds.has(id);
                    const pct = m.residual_pct;
                    const sign = pct == null ? '' : (pct > 0 ? '+' : '');
                    const cls = residualClass(pct);
                    rows.push(`
                        <div class="gv-calibration-marker-row${excluded ? ' is-excluded' : ''}" data-band-id="${id}">
                            <input type="checkbox" class="gv-marker-checkbox" data-band-id="${id}" ${excluded ? '' : 'checked'}>
                            <span class="gv-marker-name">${fmt(m.mw_kda, 0)} kDa</span>
                            <span class="gv-marker-stat">y=${m.position_y ?? '–'}</span>
                            <span class="gv-marker-stat">Rf=${fmt(m.rf, 4)}</span>
                            <span class="gv-marker-residual ${cls}">${pct == null ? 'n/a' : `${sign}${pct.toFixed(1)}%`}</span>
                        </div>
                    `);
                }
            }

            // For excluded markers we still want the user to be able to see/restore
            // them — list ones that aren't in band_matches because they were dropped
            // from the fit on this run.
            const matchedIds = new Set(allMatches.map(m => String(m.band_id)));
            const droppedIds = Array.from(this.excludedBandIds).filter(id => !matchedIds.has(id));
            if (droppedIds.length > 0) {
                rows.push('<div class="gv-calibration-marker-group-header">Excluded from fit</div>');
                for (const id of droppedIds) {
                    const ladderBand = this._lookupLadderBand(id);
                    const name = ladderBand?.estimated_mw_kda != null
                        ? `${ladderBand.estimated_mw_kda.toFixed(0)} kDa`
                        : 'Marker';
                    const y = ladderBand?.position_y ?? '–';
                    rows.push(`
                        <div class="gv-calibration-marker-row is-excluded" data-band-id="${id}">
                            <input type="checkbox" class="gv-marker-checkbox" data-band-id="${id}">
                            <span class="gv-marker-name">${name}</span>
                            <span class="gv-marker-stat">y=${y}</span>
                            <span class="gv-marker-stat">excluded</span>
                            <span class="gv-marker-residual is-na">–</span>
                        </div>
                    `);
                }
            }

            body.innerHTML = rows.join('');

            // Wire toggle handlers
            body.querySelectorAll('.gv-marker-checkbox').forEach(cb => {
                cb.addEventListener('change', (e) => this._onMarkerToggle(e.target));
            });
        }

        /**
         * Look up a band that is currently excluded — needed to display its
         * MW even when the server response no longer contains it under
         * `band_matches`.
         */
        _lookupLadderBand(bandId) {
            for (const lane of this.ladderLanes) {
                const bands = this.stateManager?.getBandsForLane(lane.id) || lane.bands || [];
                const found = bands.find(b => String(b.id) === String(bandId));
                if (found) return found;
            }
            return null;
        }

        /**
         * Marker checkbox toggled — flip the exclusion state and re-run the
         * calibration so the chart, R² and residuals reflect the new fit.
         */
        async _onMarkerToggle(checkbox) {
            const id = String(checkbox.dataset.bandId);
            if (checkbox.checked) {
                this.excludedBandIds.delete(id);
            } else {
                this.excludedBandIds.add(id);
            }
            // Disable the checkbox briefly to avoid spamming during re-fit,
            // and bypass the recalibration-confirmation dialog (the toggle is
            // an explicit user action — no need to ask for confirmation).
            checkbox.disabled = true;
            this._skipConfirmRecalibration = true;
            try {
                await this._runCalibration();
            } finally {
                checkbox.disabled = false;
            }
        }

        /**
         * Show the Results step (Step 4) + Apply step, hide the empty placeholder.
         */
        _showResultsStep() {
            const step4 = document.getElementById('calibration-step-4');
            const stepApply = document.getElementById('calibration-step-apply');
            const placeholder = document.getElementById('calibration-results-empty');
            if (step4) step4.style.display = 'block';
            if (stepApply) stepApply.style.display = 'block';
            if (placeholder) placeholder.style.display = 'none';
        }

        /**
         * Hide the Results step (Step 4) + Apply step, show the empty placeholder.
         */
        _hideResultsStep() {
            const step4 = document.getElementById('calibration-step-4');
            const stepApply = document.getElementById('calibration-step-apply');
            const placeholder = document.getElementById('calibration-results-empty');
            if (step4) step4.style.display = 'none';
            if (stepApply) stepApply.style.display = 'none';
            if (placeholder) placeholder.style.display = '';
        }

        /**
         * Combined Match + Calibrate action.
         * This is the main user action - one click does it all.
         */
        async _runCalibration() {
            if (!this.selectedTemplate || this.ladderLanes.length === 0) {
                this._showMessage('Select a template and ensure ladder lanes with bands exist');
                return;
            }

            // Check if any ladder lane has enough bands (use fresh data from StateManager)
            const lanesWithBands = this.ladderLanes.filter(l => {
                const bands = this.stateManager?.getBandsForLane(l.id) || l.bands || [];
                return bands.length >= 3;
            });
            if (lanesWithBands.length === 0) {
                this._showMessage('Ladder lanes need at least 3 bands for calibration');
                return;
            }

            // Check if bands have MW values assigned (use fresh data from StateManager)
            const lanesWithMW = lanesWithBands.filter(l => {
                const bands = this.stateManager?.getBandsForLane(l.id) || l.bands || [];
                const bandsWithMW = bands.filter(b =>
                    b.estimated_mw_kda !== null && b.estimated_mw_kda !== undefined && b.estimated_mw_kda > 0
                );
                return bandsWithMW.length >= 3;
            });

            if (lanesWithMW.length === 0) {
                this._showMessage('Bands need MW values assigned. Use Band Editor or apply a ladder template first.');
                return;
            }

            // Confirm if recalibrating (existing calibration will be replaced),
            // but skip the dialog when the recalibration was triggered by a
            // marker checkbox toggle — that's the whole point of the live
            // exclusion UX.
            if (this.calibrationResult && !this._skipConfirmRecalibration) {
                const confirmationManager = window.gelViewer?.confirmationManager;
                if (confirmationManager) {
                    const confirmed = await confirmationManager.confirmRecalibration();
                    if (!confirmed) return;
                }
            }
            this._skipConfirmRecalibration = false;

            if (this.isProcessing) return;
            this.isProcessing = true;

            const btn = document.getElementById('calibration-run');
            const btnText = document.getElementById('calibration-run-text');
            if (btn) btn.disabled = true;
            if (btnText) btnText.textContent = 'Calibrating...';

            try {
                const method = document.getElementById('calibration-method')?.value || 'LOG_LINEAR';
                let result;

                const excludedIds = Array.from(this.excludedBandIds);

                if (this.isMultiLadder) {
                    // Multi-ladder calibration
                    result = await this.apiClient.calibrateMulti(
                        this.selectedTemplate.id,
                        method,
                        excludedIds
                    );
                } else {
                    // Single ladder calibration
                    const laneId = this.ladderLanes[0]?.id;
                    result = await this.apiClient.calibrateSingle(
                        laneId,
                        this.selectedTemplate.id,
                        method,
                        excludedIds
                    );
                }

                this.calibrationResult = result;

                // Clear stale state - calibration is now fresh
                this._clearStaleState();

                // Store unmatched template bands
                this.unmatchedTemplateBands = result.unmatched_template_bands || [];

                // Show Step 4 (Results) now that calibration is complete
                this._showResultsStep();

                this._updateCalibrationChart(result);
                this._updateR2Display(result);
                this._updateCalibrationStatus(result);
                this._renderUnmatchedBands();
                this._renderCalibrationWarnings(result.warnings);
                this._renderMarkersTable(result);
                this._enableApplyButton();
                this._updateFooterHint('Calibration complete! Review residuals and uncheck outliers if needed.');

                this.eventBus.emit(Events.CALIBRATION_APPLIED, {
                    method,
                    isMultiLadder: this.isMultiLadder,
                    result,
                });

            } catch (error) {
                console.error('Calibration failed:', error);
                this._showMessage('Calibration failed: ' + (error.message || 'Unknown error'));
            } finally {
                this.isProcessing = false;
                if (btn) btn.disabled = false;
                if (btnText) btnText.textContent = 'Run Calibration';
            }
        }

        /**
         * Update calibration chart with actual fit.
         */
        _updateCalibrationChart(result) {
            if (!this.chartContainer) return;

            // Handle different API response structures:
            // Single calibration: {success, calibration, result: {band_matches, coefficients, ...}}
            // Multi calibration: {success, calibrations: [{band_matches, coefficients, ...}, ...]}
            let calibrations;
            if (result.result) {
                // Single calibration - extract the nested result
                calibrations = [result.result];
            } else if (result.calibrations) {
                // Multi calibration
                calibrations = result.calibrations;
            } else {
                calibrations = [result];
            }

            const traces = [];
            const colors = ['#8b5cf6', '#10b981', '#f59e0b', '#ef4444'];

            for (let i = 0; i < calibrations.length; i++) {
                const cal = calibrations[i];
                // Handle API key "band_matches" and legacy keys "points"/"calibration_points"
                const points = cal.band_matches || cal.calibration_points || cal.points || [];

                if (points.length === 0) {
                    console.warn(`Calibration ${i + 1} has no point data`);
                    continue;
                }

                // Data points
                const xValues = points.map(p => p.rf);
                const yValues = points.map(p => Math.log10(p.mw_kda));

                traces.push({
                    x: xValues,
                    y: yValues,
                    mode: 'markers',
                    type: 'scatter',
                    name: `Ladder ${i + 1}`,
                    marker: {
                        color: colors[i % colors.length],
                        size: 10,
                    },
                    hovertemplate: 'Rf: %{x:.3f}<br>MW: %{customdata:.1f} kDa<extra></extra>',
                    customdata: points.map(p => p.mw_kda),
                });

                // Fit line
                if (xValues.length > 1 && cal.coefficients) {
                    const xRange = [Math.min(...xValues) - 0.05, Math.max(...xValues) + 0.05];
                    const coeffs = cal.coefficients;

                    let yRange;
                    if (cal.method === 'LOG_LINEAR' || !cal.method) {
                        // Log-linear: log(MW) = slope * Rf + intercept
                        yRange = xRange.map(x => coeffs.slope * x + coeffs.intercept);
                    } else {
                        // Polynomial
                        yRange = xRange.map(x => {
                            let y = 0;
                            for (let j = 0; j < coeffs.length; j++) {
                                y += coeffs[j] * Math.pow(x, j);
                            }
                            return y;
                        });
                    }

                    traces.push({
                        x: xRange,
                        y: yRange,
                        mode: 'lines',
                        type: 'scatter',
                        name: i === 0 ? 'Fit' : '',
                        showlegend: i === 0,
                        line: {
                            color: colors[i % colors.length],
                            width: 2,
                        },
                        hoverinfo: 'skip',
                    });
                }
            }

            const layout = {
                margin: { l: 50, r: 20, t: 20, b: 45 },
                xaxis: {
                    title: { text: 'Rf (Relative Migration)', font: { size: 12, color: '#5b21b6' } },
                    tickfont: { size: 10, color: '#4b5563' },
                    gridcolor: '#e5e7eb',
                    linecolor: '#8b5cf6',
                    linewidth: 2,
                    showgrid: true,
                    zeroline: true,
                    zerolinecolor: '#d1d5db',
                },
                yaxis: {
                    title: { text: 'log₁₀(MW) kDa', font: { size: 12, color: '#5b21b6' } },
                    tickfont: { size: 10, color: '#4b5563' },
                    gridcolor: '#e5e7eb',
                    linecolor: '#8b5cf6',
                    linewidth: 2,
                    showgrid: true,
                    zeroline: true,
                    zerolinecolor: '#d1d5db',
                },
                showlegend: calibrations.length > 1,
                legend: {
                    font: { size: 10 },
                    x: 0.02,
                    y: 0.98,
                    bgcolor: 'rgba(255,255,255,0.9)',
                },
                paper_bgcolor: '#ffffff',
                plot_bgcolor: '#ffffff',
            };

            const config = {
                responsive: true,
                displayModeBar: false,
            };

            if (typeof Plotly !== 'undefined') {
                Plotly.react(this.chartContainer, traces, layout, config);
            }
        }

        /**
         * Update R² display.
         */
        _updateR2Display(result) {
            const r2Container = document.getElementById('calibration-r2');
            const r2Value = document.getElementById('calibration-r2-value');
            const r2Indicator = document.getElementById('calibration-r2-indicator');

            if (!r2Container || !r2Value || !r2Indicator) return;

            r2Container.style.display = 'flex';

            // Prefer the backend-computed average when provided — avoids
            // divergence between client-side recomputation and what the
            // server actually persisted. Fall back to per-calibration
            // average only if the backend didn't supply the aggregate
            // (older responses or single-lane path).
            let avgR2 = null;
            if (result.average_r_squared != null) {
                avgR2 = result.average_r_squared;
            } else if (Array.isArray(result.calibrations) && result.calibrations.length > 0) {
                const r2s = result.calibrations.map(c => c.r_squared).filter(r => r != null);
                if (r2s.length > 0) {
                    avgR2 = r2s.reduce((a, b) => a + b, 0) / r2s.length;
                }
            } else if (result.r_squared != null) {
                avgR2 = result.r_squared;
            }
            if (avgR2 == null) avgR2 = 0;

            r2Value.textContent = avgR2.toFixed(4);

            // Set indicator class
            r2Indicator.className = 'gv-calibration-r2-indicator';
            if (avgR2 >= R2_THRESHOLDS.EXCELLENT) {
                r2Indicator.classList.add('excellent');
            } else if (avgR2 >= R2_THRESHOLDS.GOOD) {
                r2Indicator.classList.add('good');
            } else {
                r2Indicator.classList.add('poor');
            }
        }

        /**
         * Update calibration status display.
         */
        _updateCalibrationStatus(result) {
            const statusValue = document.getElementById('calibration-status-value');
            if (statusValue) {
                statusValue.innerHTML = `
                    <i class="bi bi-check-circle text-success"></i>
                    Calibrated
                `;
            }
        }

        /**
         * Render unmatched template bands warning.
         * Shows which template bands were not detected and are excluded from calibration.
         */
        _renderUnmatchedBands() {
            const container = document.getElementById('calibration-unmatched');
            const title = document.getElementById('calibration-unmatched-title');
            const list = document.getElementById('calibration-unmatched-list');

            if (!container || !list) return;

            // Hide if no unmatched bands
            if (!this.unmatchedTemplateBands || this.unmatchedTemplateBands.length === 0) {
                container.style.display = 'none';
                return;
            }

            // Update title
            const count = this.unmatchedTemplateBands.length;
            if (title) {
                title.textContent = `${count} template band${count > 1 ? 's' : ''} not detected`;
            }

            // Render the list of unmatched bands
            list.innerHTML = this.unmatchedTemplateBands.map(band => `
                <span class="gv-calibration-unmatched-item">
                    <i class="bi bi-x"></i>
                    ${band.mw_kda} kDa
                </span>
            `).join('');

            container.style.display = 'block';
        }

        /**
         * Hide unmatched bands section.
         */
        _hideUnmatchedBands() {
            const container = document.getElementById('calibration-unmatched');
            if (container) {
                container.style.display = 'none';
            }
            this.unmatchedTemplateBands = [];
        }

        /**
         * Render calibration warnings from API response.
         * @param {string[]} warnings - Array of warning messages
         */
        _renderCalibrationWarnings(warnings) {
            const container = document.getElementById('calibration-warnings');
            if (!container) return;

            // Hide if no warnings
            if (!warnings || warnings.length === 0) {
                container.style.display = 'none';
                return;
            }

            // Render warnings
            container.innerHTML = `
                <div class="gv-calibration-warnings-header">
                    <i class="bi bi-exclamation-triangle-fill"></i>
                    <span>${warnings.length} warning${warnings.length > 1 ? 's' : ''}</span>
                </div>
                <ul class="gv-calibration-warnings-list">
                    ${warnings.map(w => `<li>${w}</li>`).join('')}
                </ul>
            `;
            container.style.display = 'block';
        }

        /**
         * Hide calibration warnings section.
         */
        _hideCalibrationWarnings() {
            const container = document.getElementById('calibration-warnings');
            if (container) {
                container.style.display = 'none';
            }
        }

        /**
         * Enable apply button.
         */
        _enableApplyButton() {
            const btn = document.getElementById('calibration-apply');
            if (btn) btn.disabled = false;
        }

        /**
         * Apply calibration to all bands.
         */
        async _applyCalibration() {
            if (!this.calibrationResult) return;

            if (this.isProcessing) return;
            this.isProcessing = true;

            // Show loading state on button
            const btn = document.getElementById('calibration-apply');
            const btnIcon = btn?.querySelector('i');
            const btnText = btn?.querySelector('span');
            const originalIcon = btnIcon?.className;
            const originalText = btnText?.textContent;

            if (btn) btn.disabled = true;
            if (btnIcon) btnIcon.className = 'bi bi-arrow-repeat gv-spin';
            if (btnText) btnText.textContent = 'Applying...';

            try {
                let result;

                if (this.isMultiLadder) {
                    result = await this.apiClient.applyMultiCalibration();
                } else {
                    result = await this.apiClient.applyCalibration();
                }

                // Update status display
                const bandsStatus = document.getElementById('calibration-bands-status');
                const bandsUpdated = document.getElementById('calibration-bands-updated');

                if (bandsStatus) bandsStatus.style.display = 'flex';
                if (bandsUpdated) {
                    const updated = result.bands_updated || 0;
                    const total = (result.bands_updated || 0) + (result.bands_failed || 0);
                    bandsUpdated.textContent = `${updated}/${total}`;
                }

                this._showMessage(`MW values applied to ${result.bands_updated || 0} bands`);
                this._updateFooterHint('Calibration applied successfully!');

                // Emit event for band editor to update
                this.eventBus.emit(Events.MW_BANDS_UPDATED, {
                    bandsUpdated: result.bands_updated,
                    bandsFailed: result.bands_failed,
                });

                // Trigger data reload to refresh bands
                this.eventBus.emit(Events.DATA_RELOAD_REQUESTED);

                // Re-emit CALIBRATION_APPLIED so MW lines update with new data
                this.eventBus.emit(Events.CALIBRATION_APPLIED, {
                    method: this.calibrationResult?.method || 'LOG_LINEAR',
                    isMultiLadder: this.isMultiLadder,
                    afterApply: true,
                });

                if (this.onCalibrationApplied) {
                    this.onCalibrationApplied(result);
                }

            } catch (error) {
                console.error('Failed to apply calibration:', error);
                this._showMessage('Failed to apply calibration');
            } finally {
                this.isProcessing = false;
                // Restore button state
                if (btnIcon) btnIcon.className = originalIcon;
                if (btnText) btnText.textContent = originalText;
                if (btn) btn.disabled = false;
            }
        }

        /**
         * Load existing calibration if present.
         */
        async _loadExistingCalibration() {
            try {
                // Check for multi-calibration first
                const multiCal = await this.apiClient.getMultiCalibration();

                if (multiCal && multiCal.calibrations && multiCal.calibrations.length > 0) {
                    this.calibrationResult = multiCal;
                    this.isMultiLadder = multiCal.calibrations.length > 1;

                    // Restore the persisted exclusion list so the UI shows the
                    // exact same state the user left when last closed.
                    this.excludedBandIds.clear();
                    for (const cal of multiCal.calibrations) {
                        for (const id of (cal.excluded_band_ids || [])) {
                            this.excludedBandIds.add(String(id));
                        }
                    }

                    // Set template if we have one (API returns template_id, not template object)
                    if (multiCal.template_id) {
                        const select = document.getElementById('calibration-template');
                        if (select) {
                            select.value = multiCal.template_id;
                            await this._onTemplateSelected(multiCal.template_id);
                        }
                    }

                    // Show Results step since calibration exists
                    this._showResultsStep();

                    this._updateCalibrationChart(multiCal);
                    this._updateR2Display(multiCal);
                    this._updateCalibrationStatus(multiCal);
                    this._renderMarkersTable(multiCal);
                    this._enableRunButton();
                    this._enableApplyButton();
                    this._updateFooterHint('Existing calibration loaded. You can recalibrate or apply to bands.');
                    return;
                }

                // Fall back to single calibration check
                const cal = await this.apiClient.getCalibration();

                if (cal && cal.r_squared) {
                    this.calibrationResult = cal;
                    // Restore exclusion list from the persisted single-ladder cal
                    this.excludedBandIds.clear();
                    for (const id of (cal.excluded_band_ids || cal.result?.excluded_band_ids || [])) {
                        this.excludedBandIds.add(String(id));
                    }
                    // Show Results step since calibration exists
                    this._showResultsStep();
                    this._updateCalibrationChart(cal);
                    this._updateR2Display(cal);
                    this._updateCalibrationStatus(cal);
                    this._renderMarkersTable(cal);
                    this._enableApplyButton();
                }

            } catch (error) {
                // No existing calibration - that's fine
                console.debug('No existing calibration found');
            }
        }

        /**
         * Reset calibration panel to initial state.
         */
        _reset() {
            // Reset state
            this.selectedTemplate = null;
            this.matchResults = [];
            this.calibrationResult = null;
            this.unmatchedTemplateBands = [];
            this.excludedBandIds.clear();
            this._clearStaleState();

            // Reset UI
            this._hideUnmatchedBands();
            this._hideCalibrationWarnings();
            const templateSelect = document.getElementById('calibration-template');
            if (templateSelect) templateSelect.value = '';

            const infoEl = document.getElementById('calibration-template-info');
            if (infoEl) infoEl.style.display = 'none';

            // Hide Results step (Step 4)
            this._hideResultsStep();

            const r2Container = document.getElementById('calibration-r2');
            if (r2Container) r2Container.style.display = 'none';

            const runBtn = document.getElementById('calibration-run');
            if (runBtn) runBtn.disabled = true;

            const applyBtn = document.getElementById('calibration-apply');
            if (applyBtn) applyBtn.disabled = true;

            const statusValue = document.getElementById('calibration-status-value');
            if (statusValue) {
                statusValue.innerHTML = `
                    <i class="bi bi-x-circle text-muted"></i>
                    Not calibrated
                `;
            }

            const bandsStatus = document.getElementById('calibration-bands-status');
            if (bandsStatus) bandsStatus.style.display = 'none';

            // Clear chart
            if (this.chartContainer) {
                const emptyEl = this.chartContainer.querySelector('.gv-calibration-chart-empty');
                if (emptyEl) {
                    emptyEl.style.display = 'flex';
                }
                if (typeof Plotly !== 'undefined') {
                    Plotly.purge(this.chartContainer);
                }
            }

            this._renderLadderList();
            this._updateFooterHint('Select a template to begin calibration.');
        }

        /**
         * Update footer hint text.
         */
        _updateFooterHint(text) {
            const hintEl = document.getElementById('calibration-footer-hint');
            if (hintEl) hintEl.textContent = text;
        }

        /**
         * Show a message to the user.
         */
        _showMessage(text) {
            const existing = document.querySelector('.gv-message');
            if (existing) existing.remove();

            const message = document.createElement('div');
            message.className = 'gv-message';
            message.textContent = text;

            const viewer = document.querySelector('.gv-viewer');
            if (viewer) {
                viewer.appendChild(message);
                setTimeout(() => message.remove(), 3000);
            }
        }

        /**
         * Check if panel is currently visible.
         * @returns {boolean}
         */
        isOpen() {
            return this.isVisible;
        }

        /**
         * Get calibration result.
         * @returns {Object|null}
         */
        getCalibrationResult() {
            return this.calibrationResult;
        }
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.CalibrationPanel = CalibrationPanel;

})(window);
