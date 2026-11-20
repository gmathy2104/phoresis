/**
 * cv2-detection-panel.js
 *
 * CV2 Vision Band Detection Panel — adaptive threshold + morphological
 * band detection using OpenCV on the backend.
 *
 * Uses DetectionPanelBase static helpers (slider binding, show/hide
 * animation, lane filtering, task polling, button state,
 * teacher event setup).
 *
 * @requires GelViewer.Events
 * @requires GelViewer.DetectionPanelBase
 * @requires GelViewer.APIClient
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
     * Default CV2 detection parameters.
     * Must stay in sync with CV2DetectionParams dataclass defaults.
     */
    const DEFAULT_PARAMS = {
        block_size: 35,
        threshold_bias: 10,
        morph_kernel: 3,
        min_band_area: 50,
        max_band_area: 5000,
        tophat_radius: 25,
        clahe_enabled: true,
        faint_band_boost: true,
    };

    /**
     * CV2DetectionPanel Class
     *
     * UI panel for CV2 vision-based band detection with parameter tuning.
     */
    class CV2DetectionPanel {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus - Event bus for communication
         * @param {APIClient} options.apiClient - API client for server requests
         * @param {StateManager} options.stateManager - State manager reference
         * @param {Function} options.onDetectionComplete - Callback when detection completes
         * @param {Object} [options.electropherogramPanel] - Unused (kept for API compat)
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
            this._bgType = 'auto';        // auto-detected background type
            this._bgOverride = 'auto';     // user override: 'auto', 'dark', 'light'

            // Currently active lane
            this._activeLaneId = null;

            // Debounce timer for preview
            this.previewDebounceTimer = null;
            this.DEBOUNCE_MS = 300;

            // DOM references
            this.panel = null;
            this.backdrop = null;

            // Embed state — managed by DetectionPanelBase
            // No electropherogram embedding — CV2 works on 2D image directly

            // Hide animation guard
            this._hideAnimationPending = false;

            // Teacher state
            this._wasVisibleBeforeTeacher = false;

            // Slider-to-param mapping — Array of pairs for syncSlidersToParams
            this._sliderMap = [
                ['cv2-detection-block-size', 'block_size'],
                ['cv2-detection-threshold-bias', 'threshold_bias'],
                ['cv2-detection-morph-kernel', 'morph_kernel'],
                ['cv2-detection-min-area', 'min_band_area'],
                ['cv2-detection-max-area', 'max_band_area'],
                ['cv2-detection-tophat-radius', 'tophat_radius'],
            ];

            // Initialize
            this._setupDOM();
            this._bindEvents();
        }

        // ─── DOM Setup ────────────────────────────────────────────────

        /**
         * Setup DOM references.
         */
        _setupDOM() {
            this.panel = document.getElementById('cv2-detection-panel');
            this.backdrop = document.getElementById('cv2-detection-backdrop');
        }

        // ─── Event Binding ────────────────────────────────────────────

        /**
         * Bind event listeners.
         */
        _bindEvents() {
            // Close button
            const closeBtn = document.getElementById('cv2-detection-close');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this.hide());
            }

            // A click on the backdrop closes nothing (owner, 2026-10-13): a stray click lost the tuned parameters.
            // The x button and Esc close.

            // Lane filter select
            const filterSelect = document.getElementById('cv2-detection-lane-filter');
            if (filterSelect) {
                filterSelect.addEventListener('change', (e) => {
                    this.laneFilter = e.target.value;
                    this._updateTargetLanes();
                });
            }

            // Bind parameter sliders
            for (const [sliderId, paramKey] of this._sliderMap) {
                this._bindSlider(sliderId, paramKey);
            }

            // CLAHE checkbox
            const claheCheckbox = document.getElementById('cv2-detection-clahe');
            if (claheCheckbox) {
                claheCheckbox.addEventListener('change', () => {
                    this.params.clahe_enabled = claheCheckbox.checked;
                    this._schedulePreview();
                });
            }

            // Faint band boost checkbox
            const faintCheckbox = document.getElementById('cv2-detection-faint-boost');
            if (faintCheckbox) {
                faintCheckbox.addEventListener('change', () => {
                    this.params.faint_band_boost = faintCheckbox.checked;
                    // Show/hide tophat radius slider based on boost toggle
                    const tophatGroup = document.getElementById('cv2-tophat-radius-group');
                    if (tophatGroup) {
                        tophatGroup.style.display = faintCheckbox.checked ? '' : 'none';
                    }
                    this._schedulePreview();
                });
            }

            // Background type override
            const bgSelect = document.getElementById('cv2-detection-bg-override');
            if (bgSelect) {
                bgSelect.addEventListener('change', (e) => {
                    this._bgOverride = e.target.value;
                    // Update the badge to reflect the override
                    if (this._bgOverride !== 'auto') {
                        this._bgType = this._bgOverride;
                    }
                    this._updateBgBadge();
                    this._schedulePreview();
                });
            }

            // Action buttons
            const resetBtn = document.getElementById('cv2-detection-reset');
            if (resetBtn) {
                resetBtn.addEventListener('click', () => this._resetParams());
            }

            const previewBtn = document.getElementById('cv2-detection-preview');
            if (previewBtn) {
                previewBtn.addEventListener('click', () => this._runPreview());
            }

            const detectBtn = document.getElementById('cv2-detection-detect');
            if (detectBtn) {
                detectBtn.addEventListener('click', () => this._runDetection());
            }

            // Esc: GelViewer.Layers (show) closes the panel.

            // Listen for lane selection changes
            this.eventBus.on(Events.LANE_SELECTED, () => {
                if (this.isVisible && this.laneFilter === 'selected') {
                    this._updateTargetLanes();
                }
            });

            // Teacher integration
            Base.setupTeacherEvents(this.eventBus, this);
        }

        /**
         * Bind a slider to a parameter, with debounced preview.
         */
        _bindSlider(sliderId, paramKey) {
            Base.bindSlider(
                sliderId, paramKey, this.params,
                (k, v) => this._formatParamValue(k, v),
                () => this._schedulePreview()
            );
        }

        // ─── Parameter Formatting ─────────────────────────────────────

        /**
         * Format parameter value for display.
         */
        _formatParamValue(key, value) {
            if (key === 'threshold_bias') {
                return value.toFixed(1);
            }
            return Math.round(value).toString();
        }

        // ─── Slider Sync ─────────────────────────────────────────────

        /**
         * Sync slider positions to current params.
         */
        _syncSlidersToParams() {
            Base.syncSlidersToParams(this._sliderMap, this.params,
                (k, v) => this._formatParamValue(k, v));

            // CLAHE checkbox
            const claheCheckbox = document.getElementById('cv2-detection-clahe');
            if (claheCheckbox) {
                claheCheckbox.checked = this.params.clahe_enabled !== false;
            }

            // Faint band boost checkbox
            const faintCheckbox = document.getElementById('cv2-detection-faint-boost');
            if (faintCheckbox) {
                faintCheckbox.checked = this.params.faint_band_boost !== false;
            }

            // Show/hide tophat group based on faint boost
            const tophatGroup = document.getElementById('cv2-tophat-radius-group');
            if (tophatGroup) {
                tophatGroup.style.display = this.params.faint_band_boost !== false ? '' : 'none';
            }
        }

        // ─── Reset ───────────────────────────────────────────────────

        /**
         * Reset parameters to defaults (or re-calibrate).
         */
        async _resetParams() {
            // Clear and copy defaults — preserves object reference for slider closures
            for (const key of Object.keys(this.params)) delete this.params[key];
            Object.assign(this.params, DEFAULT_PARAMS);
            this._syncSlidersToParams();
            this._clearPreviews();
            this._hidePreviewStats();

            // Re-run auto-calibration
            await this._loadCalibratedParams();
        }

        // ─── Auto-Calibration ─────────────────────────────────────────

        /**
         * Load auto-calibrated params from server and apply to sliders.
         */
        async _loadCalibratedParams() {
            try {
                const response = await this.apiClient.getCV2CalibratedParams();
                if (response && response.params) {
                    Object.assign(this.params, response.params);
                    this._syncSlidersToParams();

                    // Update background type badge
                    if (response.bg_type) {
                        this._bgType = response.bg_type;
                        this._updateBgBadge();
                    }

                    console.log(
                        `%c[CV2Detection] Auto-calibrated: bg=${response.bg_type}, ` +
                        `block=${this.params.block_size}, bias=${this.params.threshold_bias}`,
                        'color: #10b981;'
                    );
                }
            } catch (error) {
                console.warn('[CV2Detection] Auto-calibration failed, using defaults:', error);
            }
        }

        /**
         * Update the background type badge in the UI.
         */
        _updateBgBadge() {
            const badge = document.getElementById('cv2-detection-bg-badge');
            if (!badge) return;

            const type = this._bgType;
            badge.dataset.type = type;
            badge.textContent = type === 'dark'
                ? 'Dark background'
                : 'Light background';
        }

        // ─── Show / Hide / Toggle ─────────────────────────────────────

        /**
         * Show the CV2 detection panel (modal).
         * Auto-calibrates sliders from current image.
         */
        async show() {
            if (this._hideAnimationPending) return;

            this._updateTargetLanes();
            Base.showPanel(this.panel, this.backdrop);
            this.isVisible = true;
            global.GelViewer.Layers?.open(this.panel, {
                modal: true,
                close: () => this.hide(),
                isOpen: () => this.isVisible,
            });

            // Auto-calibrate sliders from image
            await this._loadCalibratedParams();

            // Auto-select first lane if none active
            if (this.targetLanes.length > 0 && !this._activeLaneId) {
                this._activeLaneId = this.targetLanes[0].id;
                this._highlightLaneItem(this._activeLaneId);
            }

            this.eventBus.emit(Events.CV2_DETECTION_PANEL_SHOWN);
        }

        /**
         * Hide the CV2 detection panel (modal).
         */
        hide() {
            global.GelViewer.Layers?.close(this.panel);
            this._clearPreviews();

            this._hideAnimationPending = true;
            Base.hidePanel(this.panel, this.backdrop, () => {
                this._hideAnimationPending = false;
            });

            this.isVisible = false;
            this.eventBus.emit(Events.CV2_DETECTION_PANEL_HIDDEN);
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
         * Check if panel is currently visible.
         * @returns {boolean}
         */
        isOpen() {
            return this.isVisible;
        }

        // ─── Lane Management ──────────────────────────────────────────

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
            const countEl = document.getElementById('cv2-detection-lane-count');
            if (countEl) {
                const count = this.targetLanes.length;
                countEl.innerHTML = `<span class="count">${count}</span> lane${count !== 1 ? 's' : ''}`;
            }
        }

        /**
         * Update lane list in sidebar.
         * Each lane item is clickable to load its profile and trigger preview.
         */
        _updateLaneList() {
            const listEl = document.getElementById('cv2-detection-lane-list');
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

            // Bind click handlers for lane items
            listEl.querySelectorAll('.gv-detection-lane-item').forEach(item => {
                item.addEventListener('click', () => {
                    const laneId = parseInt(item.dataset.laneId, 10);
                    if (laneId) {
                        this._activeLaneId = laneId;
                        this._highlightLaneItem(laneId);
                        // Auto-preview on lane click
                        this._schedulePreview();
                    }
                });
            });
        }

        /**
         * Highlight a lane item in the sidebar list.
         */
        _highlightLaneItem(laneId) {
            const listEl = document.getElementById('cv2-detection-lane-list');
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

        // ─── Debounced Preview ────────────────────────────────────────

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

        // ─── Preview ─────────────────────────────────────────────────

        /**
         * Run preview detection on the active lane (no save).
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

                console.log(
                    `%c[CV2Detection] Preview: lane=${lane.id}, block=${this.params.block_size}, ` +
                    `bias=${this.params.threshold_bias}, morph=${this.params.morph_kernel}, ` +
                    `area=[${this.params.min_band_area}, ${this.params.max_band_area}]`,
                    'color: #f59e0b;'
                );

                const bgType = this._bgOverride !== 'auto' ? this._bgOverride : this._bgType;
                console.log(`%c[CV2] Preview: bg_type=${bgType} (override=${this._bgOverride}, calibrated=${this._bgType})`, 'color: #f59e0b;');
                const result = await this.apiClient.detectBandsCV2Preview(lane.id, this.params, bgType);

                if (result && result.bands) {
                    this._showPreviewStats(result.band_count || result.bands.length, 1);
                }

                this.eventBus.emit(Events.CV2_DETECTION_PREVIEW, {
                    laneId: lane.id,
                    bands: result.bands || [],
                    bandCount: result.band_count || 0,
                });

            } catch (error) {
                console.error('[CV2Detection] Preview error:', error);
                this._showMessage('CV2 detection preview failed');
                this.eventBus.emit(Events.CV2_DETECTION_ERROR, { error: error.message });
            } finally {
                this.isProcessing = false;
            }
        }

        // ─── Detect & Save ────────────────────────────────────────────

        /**
         * Run detection and save bands.
         */
        async _runDetection() {
            if (this.targetLanes.length === 0) {
                this._showMessage('No lanes selected for detection');
                return;
            }

            if (this.isProcessing) return;

            // Check for existing CV2 bands in target lanes
            let existingBandCount = 0;
            this.targetLanes.forEach(lane => {
                const bands = lane.bands || [];
                const cv2Bands = bands.filter(b => b.detection_source === 'CV2_VISION');
                existingBandCount += cv2Bands.length;
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

            this.eventBus.emit(Events.CV2_DETECTION_STARTED, {
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
                    console.warn(`[CV2Detection] Skipping ${unsavedCount} unsaved lane(s)`);
                }

                console.log(
                    `%c[CV2Detection SAVE] params: block=${this.params.block_size}, ` +
                    `bias=${this.params.threshold_bias}, morph=${this.params.morph_kernel}, ` +
                    `area=[${this.params.min_band_area}, ${this.params.max_band_area}], ` +
                    `tophat=${this.params.tophat_radius}, clahe=${this.params.clahe_enabled}, ` +
                    `faint=${this.params.faint_band_boost}`,
                    'color: #ef4444; font-weight: bold;'
                );

                const bgType = this._bgOverride !== 'auto' ? this._bgOverride : this._bgType;

                if (laneIds.length === 1) {
                    // Single lane — use synchronous save endpoint
                    const result = await this.apiClient.detectBandsCV2Save(laneIds[0], this.params, true, bgType);
                    this._hideProgress();

                    const bandCount = result.created_count || result.band_count || 0;
                    this._showMessage(`Detected ${bandCount} CV2 bands`);

                    this.eventBus.emit(Events.CV2_DETECTION_COMPLETED, {
                        success: true,
                        totalBands: bandCount,
                        laneCount: 1,
                    });

                } else {
                    // Multiple lanes — use async bulk endpoint with save
                    const taskResult = await this.apiClient.detectBandsCV2Async(
                        laneIds, this.params, true, bgType  // saveResults + bgType
                    );

                    if (taskResult.task_id) {
                        await this._pollTaskStatus(taskResult.task_id, laneIds.length);
                    }
                }

                // Trigger data reload
                console.log('[CV2Detection] Emitting DATA_RELOAD_REQUESTED');
                this.eventBus.emit(Events.DATA_RELOAD_REQUESTED);

                if (this.onDetectionComplete) {
                    console.log('[CV2Detection] Calling onDetectionComplete callback');
                    this.onDetectionComplete();
                }

                // Close panel to show detected bands
                this.hide();

            } catch (error) {
                console.error('[CV2Detection] Detection error:', error);
                this._showMessage(`CV2 detection failed: ${error.message}`);
                this.eventBus.emit(Events.CV2_DETECTION_ERROR, { error: error.message });
            } finally {
                this.isProcessing = false;
                this._hideProgress();
            }
        }

        // ─── Task Polling ─────────────────────────────────────────────

        /**
         * Poll async task status.
         */
        async _pollTaskStatus(taskId, totalLanes) {
            const result = await Base.pollTaskStatus(this.apiClient, taskId, totalLanes, {
                intervalMs: 500,
                maxAttempts: 120,
                logPrefix: 'CV2Detection',
                onProgress: (current, total) => {
                    this._showProgress(current, total);
                    this.eventBus.emit(Events.CV2_DETECTION_PROGRESS, { current, total });
                },
            });

            this._hideProgress();
            const totalBands = result?.total_bands || 0;
            this._showMessage(`Detected ${totalBands} CV2 bands in ${totalLanes} lanes`);
            this.eventBus.emit(Events.CV2_DETECTION_COMPLETED, {
                success: true,
                totalBands,
                laneCount: totalLanes,
            });
        }

        // ─── Progress UI ──────────────────────────────────────────────

        /**
         * Show progress bar.
         */
        _showProgress(current, total) {
            Base.showProgress(
                'cv2-detection-progress',
                'cv2-detection-progress-fill',
                'cv2-detection-progress-text',
                current, total
            );
        }

        /**
         * Hide progress bar.
         */
        _hideProgress() {
            Base.hideProgress('cv2-detection-progress');
        }

        // ─── Preview Stats ────────────────────────────────────────────

        /**
         * Show preview statistics in the embedded preview bar.
         */
        _showPreviewStats(totalBands, laneCount) {
            const barEl = document.getElementById('cv2-detection-preview-bar');
            const statsEl = document.getElementById('cv2-detection-preview-stats');

            if (barEl) barEl.style.display = 'flex';
            if (statsEl) {
                const avg = laneCount > 0 ? (totalBands / laneCount).toFixed(1) : '0';
                statsEl.textContent = `${totalBands} band${totalBands !== 1 ? 's' : ''} detected`;
            }
        }

        /**
         * Hide preview statistics.
         */
        _hidePreviewStats() {
            const barEl = document.getElementById('cv2-detection-preview-bar');
            if (barEl) barEl.style.display = 'none';
        }

        // ─── Preview ──────────────────────────────────────────────────

        /**
         * Clear the preview. A preview is never drawn on the gel, only counted in the panel
         * (owner, 2026-10-13): the backdrop dims and blurs the gel behind it.
         */
        _clearPreviews() {
            this.eventBus.emit(Events.CV2_DETECTION_PREVIEW_CLEAR);
        }

        // ─── User Messages ────────────────────────────────────────────

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

        // ─── Public Getters ───────────────────────────────────────────

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
    global.GelViewer.CV2DetectionPanel = CV2DetectionPanel;

})(window);
