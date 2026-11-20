/**
 * detection-panel.js
 *
 * Band Detection Panel for automatic band detection (d1/d2 derivative analysis).
 * Bottom-sliding panel with parameter controls and preview functionality.
 *
 * @requires GelViewer.EventBus
 * @requires GelViewer.APIClient
 * @requires GelViewer.DetectionPanelBase
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;
    const Base = global.GelViewer.DetectionPanelBase;

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    /**
     * Default detection parameters matching backend defaults.
     */
    /**
     * Default detection parameters — permissive defaults to favour recall.
     * Must stay in sync with BandDetectionParams defaults in models.py.
     */
    const DEFAULT_PARAMS = {
        // Preprocessing
        smoothing_window: 7,
        smoothing_polyorder: 3,         // No slider — advanced internal
        background_method: 'rolling_ball',
        rolling_ball_radius: 50,
        profile_width_percent: 50,
        lane_edge_margin_percent: 0,    // No slider — advanced internal
        clahe_enabled: true,
        invert_profile: 'auto',
        // Derivative detection
        d2_significance_factor: 1.5,
        slope_threshold_factor: 1.0,
        min_snr: 1.0,
        threshold_factor: 1.5,
        min_peak_height: 0,         // 0 = auto
        min_valley_depth_factor: 1.0,
        min_band_width_px: 3,
        max_band_width_px: 120,
        derivative_window: 15,
        derivative_polyorder: 4,
        show_derivatives: false,
        refine_peaks: true,
    };

    /**
     * DetectionPanel Class
     *
     * UI panel for auto band detection (d1/d2 derivative) with parameter tuning.
     */
    class DetectionPanel {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus - Event bus for communication
         * @param {APIClient} options.apiClient - API client for server requests
         * @param {StateManager} options.stateManager - State manager reference
         * @param {Function} options.onDetectionComplete - Callback when detection completes
         * @param {Object} [options.electropherogramPanel] - Electropherogram panel reference
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.apiClient = options.apiClient;
            this.stateManager = options.stateManager;
            this.onDetectionComplete = options.onDetectionComplete;
            this.electropherogramPanel = options.electropherogramPanel || null;

            // State
            this.isVisible = false;
            this.isProcessing = false;
            this.params = { ...DEFAULT_PARAMS };
            this.targetLanes = [];
            this.laneFilter = 'all';

            // Currently active lane (shown in electropherogram)
            this._activeLaneId = null;

            // Debounce timer for preview
            this.previewDebounceTimer = null;
            this.DEBOUNCE_MS = 300;

            // DOM references
            this.panel = null;

            // Embed state — managed by DetectionPanelBase
            this._embedState = null;

            // Initialize
            this._setupDOM();
            this._bindEvents();
            this._loadDefaultParams();
        }

        /**
         * Setup DOM references.
         */
        _setupDOM() {
            this.panel = document.getElementById('detection-panel');
            this.backdrop = document.getElementById('detection-backdrop');
        }

        /**
         * Bind event listeners.
         */
        _bindEvents() {
            // Close button
            const closeBtn = document.getElementById('detection-close');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this.hide());
            }

            // A click on the backdrop closes nothing (owner, 2026-10-13): a stray click lost the tuned parameters.
            // The x button and Esc close.

            // Lane filter select
            const filterSelect = document.getElementById('detection-lane-filter');
            if (filterSelect) {
                filterSelect.addEventListener('change', (e) => {
                    this.laneFilter = e.target.value;
                    this._updateTargetLanes();
                });
            }

            // Quick parameter sliders
            this._bindSlider('detection-d2-significance', 'd2_significance_factor');
            this._bindSlider('detection-slope-threshold', 'slope_threshold_factor');
            this._bindSlider('detection-valley-depth', 'min_valley_depth_factor');
            this._bindSlider('detection-min-snr', 'min_snr');
            this._bindSlider('detection-smoothing', 'smoothing_window');

            // Advanced parameter sliders
            this._bindSlider('detection-min-width', 'min_band_width_px');
            this._bindSlider('detection-max-width', 'max_band_width_px');
            this._bindSlider('detection-rolling-radius', 'rolling_ball_radius');
            this._bindSlider('detection-profile-width', 'profile_width_percent');
            this._bindSlider('detection-derivative-window', 'derivative_window');

            // CLAHE checkbox
            const claheCheckbox = document.getElementById('detection-clahe');
            if (claheCheckbox) {
                claheCheckbox.addEventListener('change', () => {
                    this.params.clahe_enabled = claheCheckbox.checked;
                });
            }

            // Invert profile select
            const invertSelect = document.getElementById('detection-invert');
            if (invertSelect) {
                invertSelect.addEventListener('change', (e) => {
                    this.params.invert_profile = e.target.value;
                });
            }

            // Show Derivatives master toggle
            const derivMaster = document.getElementById('detection-show-derivatives');
            if (derivMaster) {
                derivMaster.addEventListener('change', () => {
                    this.params.show_derivatives = derivMaster.checked;
                    const optionsEl = document.getElementById('detection-derivative-options');
                    if (optionsEl) optionsEl.style.display = derivMaster.checked ? '' : 'none';
                    this._syncDerivativeToggles();
                });
            }

            // Refine peaks checkbox
            const refinePeaksCheckbox = document.getElementById('detection-refine-peaks');
            if (refinePeaksCheckbox) {
                refinePeaksCheckbox.addEventListener('change', () => {
                    this.params.refine_peaks = refinePeaksCheckbox.checked;
                });
            }

            // Derivative sub-toggles
            const d1Check = document.getElementById('detection-show-d1');
            if (d1Check) {
                d1Check.addEventListener('change', () => {
                    if (this.electropherogramPanel) {
                        this.electropherogramPanel.showFirstDerivative = d1Check.checked;
                        if (this.electropherogramPanel.profileData) this.electropherogramPanel._render();
                    }
                });
            }
            const d2Check = document.getElementById('detection-show-d2');
            if (d2Check) {
                d2Check.addEventListener('change', () => {
                    if (this.electropherogramPanel) {
                        this.electropherogramPanel.showSecondDerivative = d2Check.checked;
                        if (this.electropherogramPanel.profileData) this.electropherogramPanel._render();
                    }
                });
            }
            const markersCheck = document.getElementById('detection-show-markers');
            if (markersCheck) {
                markersCheck.addEventListener('change', () => {
                    if (this.electropherogramPanel) {
                        this.electropherogramPanel.showDerivativeMarkers = markersCheck.checked;
                        if (this.electropherogramPanel.profileData) this.electropherogramPanel._render();
                    }
                });
            }

            // Auto-threshold checkbox
            const autoThresholdCheckbox = document.getElementById('detection-auto-threshold');
            if (autoThresholdCheckbox) {
                autoThresholdCheckbox.addEventListener('change', () => {
                    const isAuto = autoThresholdCheckbox.checked;
                    this.params.min_peak_height = isAuto ? 0 : (this._lastThresholdUsed || 0);
                    this._updateThresholdVisibility(isAuto);
                    this._schedulePreview();
                });
            }

            // Threshold factor slider (in Advanced)
            this._bindSlider('detection-threshold-factor', 'threshold_factor');

            // Manual threshold input
            const manualInput = document.getElementById('detection-manual-threshold');
            if (manualInput) {
                manualInput.addEventListener('change', () => {
                    const val = parseFloat(manualInput.value) || 0;
                    this.params.min_peak_height = val;
                    const valueDisplay = document.getElementById('detection-manual-threshold-value');
                    if (valueDisplay) valueDisplay.textContent = val.toFixed(0);
                    this.eventBus.emit(Events.THRESHOLD_CHANGED, { value: val, source: 'panel' });
                    this._schedulePreview();
                });
            }

            // Listen for threshold changes from electropherogram drag
            this.eventBus.on(Events.THRESHOLD_CHANGED, (data) => {
                if (data.source === 'panel') return; // avoid loop
                const val = data.value;
                this.params.min_peak_height = val;
                // Switch to manual mode
                const autoCheckbox = document.getElementById('detection-auto-threshold');
                if (autoCheckbox && autoCheckbox.checked) {
                    autoCheckbox.checked = false;
                    this._updateThresholdVisibility(false);
                }
                const manualEl = document.getElementById('detection-manual-threshold');
                if (manualEl) manualEl.value = val.toFixed(1);
                const manualValueEl = document.getElementById('detection-manual-threshold-value');
                if (manualValueEl) manualValueEl.textContent = val.toFixed(0);
            });

            // Background method select
            const bgMethodSelect = document.getElementById('detection-bg-method');
            if (bgMethodSelect) {
                bgMethodSelect.addEventListener('change', (e) => {
                    this.params.background_method = e.target.value;
                    this._schedulePreview();
                });
            }

            // Action buttons
            const resetBtn = document.getElementById('detection-reset');
            if (resetBtn) {
                resetBtn.addEventListener('click', () => this._resetParams());
            }

            const previewBtn = document.getElementById('detection-preview');
            if (previewBtn) {
                previewBtn.addEventListener('click', () => this._runPreview());
            }

            const detectBtn = document.getElementById('detection-detect');
            if (detectBtn) {
                detectBtn.addEventListener('click', () => this._runDetection());
            }

            // Diagnose button — runs parameter sweep diagnostic
            const diagnoseBtn = document.getElementById('detection-diagnose');
            if (diagnoseBtn) {
                diagnoseBtn.addEventListener('click', () => this._runDiagnostic());
            }

            // Teach button — opens Teacher Panel
            const teachBtn = document.getElementById('detection-teach');
            if (teachBtn) {
                teachBtn.addEventListener('click', () => {
                    this.eventBus.emit(Events.TEACHER_PANEL_SHOWN);
                });
            }

            // Hide detection panel when teacher opens, restore when it closes
            Base.setupTeacherEvents(this.eventBus, this);

            // Listen for teacher calibration results
            this.eventBus.on(Events.TEACHER_PARAMS_APPLIED, (data) => {
                if (data && data.params) {
                    this._taughtKeys = new Set(Object.keys(data.params));
                    Object.assign(this.params, data.params);
                    this._syncSlidersToParams();
                    this._markTaughtSliders();
                }
            });

            // Esc: GelViewer.Layers (show) closes the panel.

            // Listen for lane selection changes
            this.eventBus.on(Events.LANE_SELECTED, () => {
                if (this.isVisible && this.laneFilter === 'selected') {
                    this._updateTargetLanes();
                }
            });
        }

        /**
         * Bind a slider to a parameter.
         */
        _bindSlider(sliderId, paramKey) {
            Base.bindSlider(
                sliderId, paramKey, this.params,
                (k, v) => this._formatParamValue(k, v),
                () => this._schedulePreview()
            );
        }

        /**
         * Format parameter value for display.
         */
        _formatParamValue(key, value) {
            if (['threshold_factor', 'min_valley_depth_factor', 'd2_significance_factor', 'slope_threshold_factor', 'min_snr'].includes(key)) {
                return value.toFixed(1);
            }
            if (key === 'profile_width_percent') {
                return `${value}%`;
            }
            return Math.round(value).toString();
        }

        /**
         * Load default parameters from server.
         */
        async _loadDefaultParams() {
            try {
                const response = await this.apiClient.getDetectionParams();
                if (response && response.params) {
                    Object.assign(this.params, response.params);
                    this._syncSlidersToParams();
                }
            } catch (error) {
                console.warn('Failed to load default params, using built-in defaults:', error);
            }
        }

        /**
         * Sync slider positions to current params.
         */
        _syncSlidersToParams() {
            Base.syncSlidersToParams(this._getSliderMap(), this.params,
                (k, v) => this._formatParamValue(k, v));

            // Background method
            const bgMethodSelect = document.getElementById('detection-bg-method');
            if (bgMethodSelect && this.params.background_method) {
                bgMethodSelect.value = this.params.background_method;
            }

            // Invert profile
            const invertSelect = document.getElementById('detection-invert');
            if (invertSelect && this.params.invert_profile) {
                invertSelect.value = this.params.invert_profile;
            }

            // Show derivatives checkbox
            const derivMaster = document.getElementById('detection-show-derivatives');
            if (derivMaster) {
                derivMaster.checked = !!this.params.show_derivatives;
                const optionsEl = document.getElementById('detection-derivative-options');
                if (optionsEl) optionsEl.style.display = this.params.show_derivatives ? '' : 'none';
            }

            // CLAHE checkbox
            const claheCheckbox = document.getElementById('detection-clahe');
            if (claheCheckbox) claheCheckbox.checked = this.params.clahe_enabled !== false;

            // Refine peaks checkbox
            const refinePeaksCheckbox = document.getElementById('detection-refine-peaks');
            if (refinePeaksCheckbox) {
                refinePeaksCheckbox.checked = this.params.refine_peaks !== false;
            }

            // Auto-threshold checkbox
            const isAuto = this.params.min_peak_height === 0;
            const autoCheckbox = document.getElementById('detection-auto-threshold');
            if (autoCheckbox) autoCheckbox.checked = isAuto;
            this._updateThresholdVisibility(isAuto);

            // Manual threshold input
            const manualInput = document.getElementById('detection-manual-threshold');
            if (manualInput) manualInput.value = this.params.min_peak_height;
        }

        /**
         * Get slider-to-param mapping as [sliderId, paramKey] pairs.
         */
        _getSliderMap() {
            return [
                // Quick params
                ['detection-d2-significance', 'd2_significance_factor'],
                ['detection-slope-threshold', 'slope_threshold_factor'],
                ['detection-valley-depth', 'min_valley_depth_factor'],
                ['detection-min-snr', 'min_snr'],
                ['detection-smoothing', 'smoothing_window'],
                // Advanced params
                ['detection-threshold-factor', 'threshold_factor'],
                ['detection-derivative-window', 'derivative_window'],
                ['detection-min-width', 'min_band_width_px'],
                ['detection-max-width', 'max_band_width_px'],
                ['detection-rolling-radius', 'rolling_ball_radius'],
                ['detection-profile-width', 'profile_width_percent'],
            ];
        }

        /**
         * Visually mark sliders whose values came from the teacher.
         */
        _markTaughtSliders() {
            const sliderParamMap = Object.fromEntries(this._getSliderMap());
            Base.markTaughtSliders(sliderParamMap, this._taughtKeys);

            // Also mark invert_profile select
            const invertLabel = document.getElementById('detection-invert')?.closest('.gv-detection-checkbox-row');
            if (invertLabel && this._taughtKeys?.has('invert_profile')) {
                let badge = invertLabel.querySelector('.gv-taught-badge');
                if (!badge) {
                    badge = document.createElement('span');
                    badge.className = 'gv-taught-badge';
                    badge.title = 'Set by Teacher';
                    badge.textContent = 'T';
                    invertLabel.appendChild(badge);
                }
            }
        }

        /**
         * Clear all taught badges.
         */
        _clearTaughtBadges() {
            this._taughtKeys = Base.clearTaughtBadges(this.panel);
        }

        /**
         * Reset parameters to defaults.
         */
        _resetParams() {
            // Clear all keys then copy defaults — preserves object reference
            // for slider closures that captured this.params
            for (const key of Object.keys(this.params)) delete this.params[key];
            Object.assign(this.params, DEFAULT_PARAMS);
            this._lastThresholdUsed = null;
            this._syncSlidersToParams();
            this._clearTaughtBadges();

            // Reset CLAHE checkbox
            const claheCheckbox = document.getElementById('detection-clahe');
            if (claheCheckbox) claheCheckbox.checked = true;

            // Reset invert profile select
            const invertSelect = document.getElementById('detection-invert');
            if (invertSelect) invertSelect.value = 'auto';

            // Reset auto-threshold checkbox
            const autoCheckbox = document.getElementById('detection-auto-threshold');
            if (autoCheckbox) autoCheckbox.checked = true;
            this._updateThresholdVisibility(true);

            // Reset derivative toggles
            const derivMaster = document.getElementById('detection-show-derivatives');
            if (derivMaster) derivMaster.checked = false;
            const derivOptions = document.getElementById('detection-derivative-options');
            if (derivOptions) derivOptions.style.display = 'none';
            ['detection-show-d1', 'detection-show-d2', 'detection-show-markers'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.checked = true;
            });
            this._syncDerivativeToggles();

            // Reset refine_peaks checkbox
            const refinePeaksCheckbox = document.getElementById('detection-refine-peaks');
            if (refinePeaksCheckbox) refinePeaksCheckbox.checked = true;

            // Emit threshold reset
            this.eventBus.emit(Events.THRESHOLD_CHANGED, { value: null, source: 'panel' });

            this._clearPreviews();
            this._hidePreviewStats();
        }

        /**
         * Schedule a debounced preview.
         */
        _schedulePreview() {
            if (this.previewDebounceTimer) {
                clearTimeout(this.previewDebounceTimer);
            }

            this.previewDebounceTimer = setTimeout(() => {
                this._runPreview();
            }, this.DEBOUNCE_MS);
        }

        /**
         * Show the detection panel (modal).
         * Embeds the electropherogram panel into the chart host area.
         */
        show() {
            if (this._hideAnimationPending) return;

            this._updateTargetLanes();
            Base.showPanel(this.panel, this.backdrop);
            this.isVisible = true;
            global.GelViewer.Layers?.open(this.panel, {
                modal: true,
                close: () => this.hide(),
                isOpen: () => this.isVisible,
            });

            // Embed electropherogram panel into chart host
            this._embedElectropherogram();

            // Auto-load profile: use active lane if still in target list, else first lane
            if (this.electropherogramPanel && this.targetLanes.length > 0) {
                const activeLane = this._activeLaneId
                    ? this.targetLanes.find(l => l.id === this._activeLaneId)
                    : null;
                const lane = activeLane || this.targetLanes[0];
                this._activeLaneId = lane.id;
                this.electropherogramPanel.loadProfile(lane.id);
                this._highlightLaneItem(lane.id);
            }

            this.eventBus.emit(Events.DETECTION_PANEL_SHOWN);
        }

        /**
         * Hide the detection panel (modal).
         * Returns the electropherogram to its original location.
         */
        hide() {
            global.GelViewer.Layers?.close(this.panel);
            // Return electropherogram to original parent before animating out
            this._unembedElectropherogram();
            this._clearPreviews();

            this._hideAnimationPending = true;
            Base.hidePanel(this.panel, this.backdrop, () => {
                this._hideAnimationPending = false;
            });

            this.isVisible = false;
            this.eventBus.emit(Events.DETECTION_PANEL_HIDDEN);
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
         * Update target lanes based on filter.
         */
        _updateTargetLanes() {
            this.targetLanes = Base.getTargetLanes(this.laneFilter, this.stateManager);
            this._updateLaneCount();
            this._updateLaneList();
        }

        /**
         * Update lane count display.
         */
        _updateLaneCount() {
            const countEl = document.getElementById('detection-lane-count');
            if (countEl) {
                const count = this.targetLanes.length;
                countEl.innerHTML = `<span class="count">${count}</span> lane${count !== 1 ? 's' : ''}`;
            }
        }

        /**
         * Update lane list in sidebar.
         * Each lane item is clickable to load its profile in the electropherogram.
         */
        _updateLaneList() {
            const listEl = document.getElementById('detection-lane-list');
            if (!listEl) return;

            if (this.targetLanes.length === 0) {
                listEl.innerHTML = '<div class="gv-detection-lane-empty">No lanes match filter</div>';
                return;
            }

            listEl.innerHTML = this.targetLanes.slice(0, 10).map(lane => `
                <div class="gv-detection-lane-item" data-lane-id="${lane.id}">
                    <span class="lane-number">#${lane.lane_number || '?'}</span>
                    <span class="lane-type">${escapeHtml(lane.lane_type)}</span>
                </div>
            `).join('');

            if (this.targetLanes.length > 10) {
                listEl.innerHTML += `<div class="gv-detection-lane-more">+${this.targetLanes.length - 10} more</div>`;
            }

            // Bind click handlers for lane items → load profile
            listEl.querySelectorAll('.gv-detection-lane-item').forEach(item => {
                item.addEventListener('click', () => {
                    const laneId = parseInt(item.dataset.laneId, 10);
                    if (laneId && this.electropherogramPanel) {
                        this._activeLaneId = laneId;
                        this.electropherogramPanel.loadProfile(laneId);
                        this._highlightLaneItem(laneId);
                        // Hide chart placeholder
                        const placeholder = document.getElementById('detection-chart-placeholder');
                        if (placeholder) placeholder.style.display = 'none';
                    }
                });
            });
        }

        /**
         * Run preview detection (no save).
         */
        async _runPreview() {
            if (this.targetLanes.length === 0) {
                this._showMessage('No lanes selected for detection');
                return;
            }

            if (this.isProcessing) return;

            this.isProcessing = true;
            this._clearPreviews();

            try {
                // Preview on the active lane (or first lane as fallback)
                const activeLane = this._activeLaneId
                    ? this.targetLanes.find(l => l.id === this._activeLaneId)
                    : null;
                const lane = activeLane || this.targetLanes[0];
                const result = await this.apiClient.previewBandDetection(lane.id, this.params);

                // Log what we SENT to the backend
                console.log(
                    `%c[Detection] SENT params: d2=${this.params.d2_significance_factor}, ` +
                    `slope=${this.params.slope_threshold_factor}, threshold=${this.params.threshold_factor}, ` +
                    `snr=${this.params.min_snr}, deriv_win=${this.params.derivative_window}`,
                    'color: #f59e0b;'
                );

                if (result && result.bands) {
                    this._showPreviewStats(result.bands.length, 1);
                    this._updatePolarityBadge(result.profile?.was_inverted);

                    // Log diagnostics — what the backend ACTUALLY USED
                    if (result.diagnostics) {
                        const d = result.diagnostics;
                        const p = d.params_used || {};
                        console.log(
                            `%c[Detection] USED params: d2=${p.d2_significance_factor}, ` +
                            `slope=${p.slope_threshold_factor}, threshold=${p.threshold_factor}, ` +
                            `snr=${p.min_snr}, deriv_win=${p.derivative_window}`,
                            'color: #10b981;'
                        );
                        console.log(
                            `%c[Detection] ${result.bands.length} bands | ` +
                            `rejected: amp=${d.rejection_counts?.rejected_amplitude}, ` +
                            `slope=${d.rejection_counts?.rejected_slope}, ` +
                            `d2=${d.rejection_counts?.rejected_d2}, ` +
                            `width=${d.rejection_counts?.rejected_width}, ` +
                            `snr=${d.rejection_counts?.rejected_snr} | ` +
                            `thresholds: amp=${d.thresholds?.amplitude}, ` +
                            `d2=${d.thresholds?.d2_curvature}, slope=${d.thresholds?.slope}`,
                            'color: #3b82f6; font-weight: bold;'
                        );
                    }

                    // Update threshold from backend response
                    if (result.profile?.threshold_used != null) {
                        this._lastThresholdUsed = result.profile.threshold_used;
                        this.eventBus.emit(Events.THRESHOLD_CHANGED, {
                            value: result.profile.threshold_used,
                            source: 'preview',
                        });
                    }
                }

                this.eventBus.emit(Events.BAND_DETECTION_PREVIEW, {
                    laneId: lane.id,
                    bands: result.bands || [],
                    bandCount: result.bands?.length || 0,
                    profile: result.profile || null,
                });

            } catch (error) {
                console.error('Preview error:', error);
                this._showMessage('Detection preview failed');
                this.eventBus.emit(Events.BAND_DETECTION_ERROR, { error: error.message });
            } finally {
                this.isProcessing = false;
            }
        }

        /**
         * Run detection and save bands.
         */
        async _runDetection() {
            if (this.targetLanes.length === 0) {
                this._showMessage('No lanes selected for detection');
                return;
            }

            if (this.isProcessing) return;

            // Check for existing bands in target lanes (auto-detected ones will be replaced)
            let existingBandCount = 0;
            this.targetLanes.forEach(lane => {
                const bands = lane.bands || [];
                // Count only auto-detected bands (not manual ones)
                const autoBands = bands.filter(b => b.detection_source === 'CV2' || b.detection_source === 'SAM' || !b.detection_source);
                existingBandCount += autoBands.length;
            });

            // Confirm if bands exist
            if (existingBandCount > 0) {
                const confirmationManager = window.gelViewer?.confirmationManager;
                if (confirmationManager) {
                    const confirmed = await confirmationManager.confirmDetectBands(
                        existingBandCount,
                        this.targetLanes.length
                    );
                    if (!confirmed) return;
                }
            }

            this.isProcessing = true;
            this._clearPreviews();
            this._showProgress(0, this.targetLanes.length);

            this.eventBus.emit(Events.BAND_DETECTION_STARTED, {
                laneCount: this.targetLanes.length,
            });

            try {
                const allIds = this.targetLanes.map(l => l.id);
                const laneIds = allIds.filter(id => !String(id).startsWith('temp_'));
                const unsavedCount = allIds.length - laneIds.length;

                if (laneIds.length === 0) {
                    this._showMessage('Please save your annotations before running detection.', 'warning');
                    return;
                }
                if (unsavedCount > 0) {
                    console.warn(`[DetectionPanel] Skipping ${unsavedCount} unsaved lane(s)`);
                }

                // DEBUG: Log params being sent to detect-and-save
                console.log(
                    `%c[Detection SAVE] SENDING params: d2=${this.params.d2_significance_factor}, ` +
                    `slope=${this.params.slope_threshold_factor}, threshold=${this.params.threshold_factor}, ` +
                    `snr=${this.params.min_snr}, deriv_win=${this.params.derivative_window}, ` +
                    `smoothing=${this.params.smoothing_window}, valley=${this.params.min_valley_depth_factor}`,
                    'color: #ef4444; font-weight: bold;'
                );
                console.log('[Detection SAVE] Full params:', JSON.parse(JSON.stringify(this.params)));

                if (laneIds.length === 1) {
                    // Single lane - use synchronous endpoint
                    const result = await this.apiClient.detectAndSaveBands(laneIds[0], this.params);
                    this._hideProgress();

                    // DEBUG: Log what backend actually used
                    if (result.diagnostics?.params_used) {
                        const p = result.diagnostics.params_used;
                        console.log(
                            `%c[Detection SAVE] USED params: d2=${p.d2_significance_factor}, ` +
                            `slope=${p.slope_threshold_factor}, threshold=${p.threshold_factor}, ` +
                            `snr=${p.min_snr}, deriv_win=${p.derivative_window}`,
                            'color: #10b981; font-weight: bold;'
                        );
                    }

                    const bandCount = result.created_count || 0;
                    this._showMessage(`Detected ${bandCount} bands`);

                    this.eventBus.emit(Events.BAND_DETECTION_COMPLETED, {
                        success: true,
                        totalBands: bandCount,
                        laneCount: 1,
                    });

                } else {
                    // Multiple lanes - use async bulk endpoint
                    const taskResult = await this.apiClient.detectBandsBulkAsync(laneIds, this.params);

                    if (taskResult.task_id) {
                        // Poll for completion
                        await this._pollTaskStatus(taskResult.task_id, laneIds.length);
                    }
                }

                // Trigger data reload
                console.log('DetectionPanel: emitting DATA_RELOAD_REQUESTED');
                this.eventBus.emit(Events.DATA_RELOAD_REQUESTED);

                if (this.onDetectionComplete) {
                    console.log('DetectionPanel: calling onDetectionComplete callback');
                    this.onDetectionComplete();
                }

                // Close panel to show detected bands
                this.hide();

            } catch (error) {
                console.error('Detection error:', error);
                this._showMessage(`Detection failed: ${error.message}`);
                this.eventBus.emit(Events.BAND_DETECTION_ERROR, { error: error.message });
            } finally {
                this.isProcessing = false;
                this._hideProgress();
            }
        }

        /**
         * Poll async task status.
         */
        async _pollTaskStatus(taskId, totalLanes) {
            const result = await Base.pollTaskStatus(this.apiClient, taskId, totalLanes, {
                intervalMs: 500,
                maxAttempts: 120,
                logPrefix: 'DetectionPanel',
                onProgress: (current, total) => {
                    this._showProgress(current, total);
                    this.eventBus.emit(Events.BAND_DETECTION_PROGRESS, { current, total });
                },
            });

            this._hideProgress();
            const totalBands = result?.total_bands || 0;
            this._showMessage(`Detected ${totalBands} bands in ${totalLanes} lanes`);
            this.eventBus.emit(Events.BAND_DETECTION_COMPLETED, {
                success: true,
                totalBands,
                laneCount: totalLanes,
            });
        }

        /**
         * Show progress bar.
         */
        _showProgress(current, total) {
            Base.showProgress('detection-progress', 'detection-progress-fill', 'detection-progress-text', current, total);
        }

        /**
         * Hide progress bar.
         */
        _hideProgress() {
            Base.hideProgress('detection-progress');
        }

        /**
         * Show preview statistics in the embedded preview bar.
         */
        _showPreviewStats(totalBands, laneCount) {
            const barEl = document.getElementById('detection-preview-bar');
            const totalEl = document.getElementById('detection-preview-total');
            const lanesEl = document.getElementById('detection-preview-lanes');
            const avgEl = document.getElementById('detection-preview-avg');

            if (barEl) {
                barEl.style.display = 'flex';
            }

            if (totalEl) totalEl.textContent = totalBands;
            if (lanesEl) lanesEl.textContent = laneCount;
            if (avgEl) avgEl.textContent = laneCount > 0 ? (totalBands / laneCount).toFixed(1) : '0';
        }

        /**
         * Hide preview statistics.
         */
        _hidePreviewStats() {
            const barEl = document.getElementById('detection-preview-bar');
            if (barEl) {
                barEl.style.display = 'none';
            }
        }

        /**
         * Clear the preview: the electropherogram's markers and the polarity badge.
         * A preview is never drawn on the gel: this modal covers it (owner, 2026-10-13).
         */
        _clearPreviews() {
            // Hide polarity badge
            const badge = document.getElementById('detection-polarity-badge');
            if (badge) badge.style.display = 'none';

            this.eventBus.emit(Events.BAND_DETECTION_PREVIEW_CLEAR);
        }

        /**
         * Update polarity status badge after detection.
         */
        _updatePolarityBadge(wasInverted) {
            const badge = document.getElementById('detection-polarity-badge');
            if (!badge) return;
            badge.style.display = 'inline-flex';
            if (wasInverted) {
                badge.textContent = 'White background';
                badge.className = 'gv-detection-polarity-badge gv-polarity-white-bg';
                badge.title = 'Detected white/light background (Coomassie, Silver stain). If wrong, change "Invert Profile" above.';
            } else {
                badge.textContent = 'Black background';
                badge.className = 'gv-detection-polarity-badge gv-polarity-black-bg';
                badge.title = 'Detected dark background (fluorescence, chemiluminescence). If wrong, change "Invert Profile" above.';
            }
        }

        /**
         * Show a message to the user.
         */
        _showMessage(text) {
            const existing = document.querySelector('.gv-message');
            if (existing) existing.remove();

            // Over the panel's own backdrop: in .gv-viewer it was drawn under it (.gv-main is a stacking context).
            const message = document.createElement('div');
            message.className = 'gv-message gv-message--over';
            message.setAttribute('role', 'status');
            message.textContent = text;
            document.body.appendChild(message);
            setTimeout(() => message.remove(), 3000);
        }

        /**
         * Sync derivative toggle states to the electropherogram panel.
         */
        _syncDerivativeToggles() {
            if (!this.electropherogramPanel) return;

            const d1Check = document.getElementById('detection-show-d1');
            const d2Check = document.getElementById('detection-show-d2');
            const markersCheck = document.getElementById('detection-show-markers');
            const isActive = this.params.show_derivatives;

            this.electropherogramPanel.showFirstDerivative = isActive && (d1Check ? d1Check.checked : true);
            this.electropherogramPanel.showSecondDerivative = isActive && (d2Check ? d2Check.checked : true);
            this.electropherogramPanel.showDerivativeMarkers = isActive && (markersCheck ? markersCheck.checked : true);

            if (this.electropherogramPanel.profileData) {
                this.electropherogramPanel._render();
            }
        }

        /**
         * Show/hide threshold controls based on auto/manual mode.
         */
        _updateThresholdVisibility(isAuto) {
            const factorRow = document.getElementById('detection-threshold-factor-row');
            const manualRow = document.getElementById('detection-manual-threshold-row');

            if (factorRow) factorRow.style.display = isAuto ? '' : 'none';
            if (manualRow) manualRow.style.display = isAuto ? 'none' : '';
        }

        /**
         * Embed the electropherogram panel into the detection modal's chart host.
         */
        _embedElectropherogram() {
            this._embedState = Base.embedElectropherogram(
                this.electropherogramPanel,
                'detection-chart-host',
                'detection-chart-placeholder'
            );
        }

        /**
         * Return the electropherogram panel to its original location.
         */
        _unembedElectropherogram() {
            Base.unembedElectropherogram(
                this.electropherogramPanel,
                this._embedState,
                'detection-chart-placeholder'
            );
            this._embedState = null;
        }

        /**
         * Highlight a lane item in the sidebar list.
         */
        _highlightLaneItem(laneId) {
            const listEl = document.getElementById('detection-lane-list');
            if (!listEl) return;

            // Remove active from all
            listEl.querySelectorAll('.gv-detection-lane-item').forEach(item => {
                item.classList.remove('active');
            });

            // Add active to matching
            const target = listEl.querySelector(`.gv-detection-lane-item[data-lane-id="${laneId}"]`);
            if (target) {
                target.classList.add('active');
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
         * Run diagnostic parameter sweep.
         * Tests multiple parameter combinations and logs results to console.
         */
        async _runDiagnostic() {
            if (this.targetLanes.length === 0) {
                this._showMessage('No lanes selected for diagnostic');
                return;
            }

            if (this.isProcessing) return;
            this.isProcessing = true;

            const lane = this._activeLaneId
                ? this.targetLanes.find(l => l.id === this._activeLaneId)
                : this.targetLanes[0];

            if (!lane) {
                this._showMessage('Select a lane first');
                this.isProcessing = false;
                return;
            }

            this._showMessage('Running diagnostic sweep...');

            try {
                const response = await fetch(
                    `/api/lanes/${lane.id}/detect-bands/diagnostic/`,
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': this.apiClient.csrfToken,
                        },
                        body: JSON.stringify({ params: this.params }),
                    }
                );

                const data = await response.json();

                if (data.success) {
                    // Pretty-print results to console
                    console.group('%c[Detection Diagnostic] Parameter Sweep Results', 'color: #f59e0b; font-weight: bold; font-size: 14px;');

                    console.log('%cSummary:', 'color: #ef4444; font-weight: bold;');
                    (data.summary || []).forEach(line => console.log(`  ${line}`));

                    console.log('\n%cDetailed Results:', 'color: #3b82f6; font-weight: bold;');
                    console.table(data.sweep_results.map(r => ({
                        'Config': r.label,
                        'Bands': r.band_count,
                        'Rejected (amplitude)': r.diagnostics?.rejection_counts?.rejected_amplitude ?? '?',
                        'Rejected (slope)': r.diagnostics?.rejection_counts?.rejected_slope ?? '?',
                        'Rejected (d2)': r.diagnostics?.rejection_counts?.rejected_d2 ?? '?',
                        'Rejected (width)': r.diagnostics?.rejection_counts?.rejected_width ?? '?',
                        'Rejected (SNR)': r.diagnostics?.rejection_counts?.rejected_snr ?? '?',
                        'd1 crossings': r.diagnostics?.rejection_counts?.d1_downward_crossings ?? '?',
                        'Shoulders': r.diagnostics?.rejection_counts?.shoulders_found ?? '?',
                    })));

                    // Show noise/threshold info from first result
                    const firstDiag = data.sweep_results[0]?.diagnostics;
                    if (firstDiag) {
                        console.log('\n%cNoise & Thresholds (user params):', 'color: #10b981; font-weight: bold;');
                        console.table({
                            'Signal range': firstDiag.signal_range?.join(' - ') ?? '?',
                            'noise_d1': firstDiag.noise?.noise_d1,
                            'noise_d2': firstDiag.noise?.noise_d2,
                            'noise_signal': firstDiag.noise?.noise_signal,
                            'Amplitude threshold': firstDiag.thresholds?.amplitude,
                            'd2 threshold': firstDiag.thresholds?.d2_curvature,
                            'Slope threshold': firstDiag.thresholds?.slope,
                            'Baseline pts': firstDiag.noise?.baseline_points,
                        });
                    }

                    console.groupEnd();

                    const bestCount = Math.max(...data.sweep_results.map(r => r.band_count));
                    this._showMessage(
                        `Diagnostic: best=${bestCount} bands. See browser console (F12) for details.`
                    );
                } else {
                    this._showMessage('Diagnostic failed: ' + (data.error || 'unknown'));
                }

            } catch (error) {
                console.error('[DetectionPanel] Diagnostic error:', error);
                this._showMessage('Diagnostic request failed');
            } finally {
                this.isProcessing = false;
            }
        }

        /**
         * Get current detection parameters.
         * @returns {Object}
         */
        getParams() {
            return { ...this.params };
        }
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.DetectionPanel = DetectionPanel;

})(window);
