/**
 * profile-detection-panel.js
 *
 * Profile Peak Detection Panel for detecting bands from intensity profiles.
 * Uses the advanced peak detection algorithms from densitometry services.
 *
 * @requires GelViewer.EventBus
 * @requires GelViewer.APIClient
 * @requires GelViewer.DetectionPanelBase
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;
    const Base = global.GelViewer.DetectionPanelBase;

    /**
     * Default detection parameters.
     */
    const DEFAULT_PARAMS = {
        sensitivity: 0.80,
        min_peak_distance: 15,
        match_tolerance_px: 15,
        smoothing_window: 11,
        enable_deconvolution: false,
        enable_shoulder_detection: false,  // Disabled to reduce overlapping bands
    };

    /**
     * ProfileDetectionPanel Class
     *
     * UI panel for profile-based peak detection.
     */
    class ProfileDetectionPanel {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus - Event bus for communication
         * @param {APIClient} options.apiClient - API client for server requests
         * @param {StateManager} options.stateManager - State manager reference
         * @param {Object} options.svg - SVG.js instance for previews
         * @param {string} options.analysisId - Analysis UUID for async detection
         * @param {Function} options.onDetectionComplete - Callback when detection completes
         * @param {Object} [options.electropherogramPanel] - Electropherogram panel reference
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.apiClient = options.apiClient;
            this.stateManager = options.stateManager;
            this.svg = options.svg;
            this.analysisId = options.analysisId;
            this.onDetectionComplete = options.onDetectionComplete;
            this.electropherogramPanel = options.electropherogramPanel || null;

            // State
            this.isVisible = false;
            this.isProcessing = false;
            this.params = { ...DEFAULT_PARAMS };
            this.previewResults = [];
            this.targetLanes = [];
            this.laneFilter = 'all';
            this.pollIntervalMs = 500;

            // DOM references
            this.panel = null;
            this.backdrop = null;
            this.previewGroup = null;

            // Embed state — managed by DetectionPanelBase
            this._embedState = null;

            // Initialize
            this._setupDOM();
            this._bindEvents();
        }

        /**
         * Setup DOM references.
         */
        _setupDOM() {
            this.panel = document.getElementById('profile-detection-panel');
            this.backdrop = document.getElementById('profile-detection-backdrop');

            // Create SVG group for peak previews
            if (this.svg) {
                this.previewGroup = this.svg.group().attr('id', 'profile-peak-previews');
            }
        }

        /**
         * Bind event listeners.
         */
        _bindEvents() {
            // Close button
            const closeBtn = document.getElementById('profile-detection-close');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this.hide());
            }

            // Backdrop click to close
            if (this.backdrop) {
                this.backdrop.addEventListener('click', () => this.hide());
            }

            // Lane filter select
            const filterSelect = document.getElementById('profile-detection-lane-filter');
            if (filterSelect) {
                filterSelect.addEventListener('change', (e) => {
                    this.laneFilter = e.target.value;
                    this._updateTargetLanes();
                });
            }

            // Parameter sliders — using shared base
            this._bindSlider('profile-detection-sensitivity', 'sensitivity');
            this._bindSlider('profile-detection-min-distance', 'min_peak_distance');
            this._bindSlider('profile-detection-match-tolerance', 'match_tolerance_px');
            this._bindSlider('profile-detection-smoothing', 'smoothing_window');

            // Checkboxes
            const deconvCheckbox = document.getElementById('profile-detection-deconv');
            if (deconvCheckbox) {
                deconvCheckbox.addEventListener('change', (e) => {
                    this.params.enable_deconvolution = e.target.checked;
                });
            }

            const shoulderCheckbox = document.getElementById('profile-detection-shoulder');
            if (shoulderCheckbox) {
                shoulderCheckbox.addEventListener('change', (e) => {
                    this.params.enable_shoulder_detection = e.target.checked;
                });
            }

            // Action buttons
            const resetBtn = document.getElementById('profile-detection-reset');
            if (resetBtn) {
                resetBtn.addEventListener('click', () => this._resetParams());
            }

            const previewBtn = document.getElementById('profile-detection-preview');
            if (previewBtn) {
                previewBtn.addEventListener('click', () => this._runPreview());
            }

            const detectBtn = document.getElementById('profile-detection-detect');
            if (detectBtn) {
                detectBtn.addEventListener('click', () => this._runDetection());
            }

            // Teach button — opens Teacher Panel
            const teachBtn = document.getElementById('profile-detection-teach');
            if (teachBtn) {
                teachBtn.addEventListener('click', () => {
                    this.eventBus.emit(Events.TEACHER_PANEL_SHOWN);
                });
            }

            // Hide/restore when teacher opens/closes — shared logic
            Base.setupTeacherEvents(this.eventBus, this);

            // Listen for teacher calibration results — map applicable params
            this.eventBus.on(Events.TEACHER_PARAMS_APPLIED, (data) => {
                if (data && data.params) {
                    const p = data.params;
                    this._taughtKeys = new Set();
                    if (p.sensitivity !== undefined) {
                        this.params.sensitivity = p.sensitivity;
                        this._taughtKeys.add('sensitivity');
                    }
                    if (p.peak_distance !== undefined) {
                        this.params.min_peak_distance = p.peak_distance;
                        this._taughtKeys.add('min_peak_distance');
                    }
                    if (p.smoothing_window !== undefined) {
                        this.params.smoothing_window = p.smoothing_window;
                        this._taughtKeys.add('smoothing_window');
                    }
                    this._syncSlidersToParams();
                    this._markTaughtSliders();
                }
            });

            // Keyboard shortcuts
            document.addEventListener('keydown', (e) => {
                if (!this.isVisible) return;

                if (e.key === 'Escape') {
                    this.hide();
                } else if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey) {
                    if (!this.isProcessing) {
                        this._runDetection();
                    }
                }
            });

            // Listen for lane selection changes
            this.eventBus.on(Events.LANE_SELECTED, () => {
                if (this.isVisible && this.laneFilter === 'selected') {
                    this._updateTargetLanes();
                }
            });
        }

        /**
         * Bind slider to parameter — delegates to shared base.
         */
        _bindSlider(sliderId, paramKey) {
            Base.bindSlider(sliderId, paramKey, this.params);
        }

        /**
         * Get slider-to-param mapping as [sliderId, paramKey] pairs.
         */
        _getSliderMap() {
            return [
                ['profile-detection-sensitivity', 'sensitivity'],
                ['profile-detection-min-distance', 'min_peak_distance'],
                ['profile-detection-match-tolerance', 'match_tolerance_px'],
                ['profile-detection-smoothing', 'smoothing_window'],
            ];
        }

        /**
         * Reset parameters to defaults.
         */
        _resetParams() {
            // Clear all keys then copy defaults — preserves object reference
            // for slider closures that captured this.params
            for (const key of Object.keys(this.params)) delete this.params[key];
            Object.assign(this.params, DEFAULT_PARAMS);
            this._clearTaughtBadges();
            this._syncSlidersToParams();

            // Checkboxes
            const deconvCheckbox = document.getElementById('profile-detection-deconv');
            if (deconvCheckbox) {
                deconvCheckbox.checked = this.params.enable_deconvolution;
            }

            const shoulderCheckbox = document.getElementById('profile-detection-shoulder');
            if (shoulderCheckbox) {
                shoulderCheckbox.checked = this.params.enable_shoulder_detection;
            }

            // Clear previews
            this._clearPreviews();
        }

        /**
         * Visually mark sliders whose values came from the teacher.
         */
        _markTaughtSliders() {
            const sliderParamMap = Object.fromEntries(this._getSliderMap());
            Base.markTaughtSliders(sliderParamMap, this._taughtKeys);
        }

        /**
         * Clear all taught badges.
         */
        _clearTaughtBadges() {
            this._taughtKeys = Base.clearTaughtBadges(this.panel);
        }

        /**
         * Sync slider UI to current params.
         */
        _syncSlidersToParams() {
            Base.syncSlidersToParams(this._getSliderMap(), this.params);
        }

        /**
         * Show the panel.
         */
        show() {
            if (this._hideAnimationPending) return;

            this._updateTargetLanes();
            Base.showPanel(this.panel, this.backdrop);
            this.isVisible = true;

            // Embed electropherogram panel into chart host
            this._embedElectropherogram();

            // Auto-load profile for first target lane
            if (this.electropherogramPanel && this.targetLanes.length > 0) {
                const firstLane = this.targetLanes[0];
                this.electropherogramPanel.loadProfile(firstLane.id);
            }

            this.eventBus.emit(Events.PROFILE_DETECTION_PANEL_SHOWN);
        }

        /**
         * Hide the panel.
         */
        hide() {
            this._unembedElectropherogram();
            this._clearPreviews();

            this._hideAnimationPending = true;
            Base.hidePanel(this.panel, this.backdrop, () => {
                this._hideAnimationPending = false;
            });

            this.isVisible = false;
            this.eventBus.emit(Events.PROFILE_DETECTION_PANEL_HIDDEN);
        }

        /**
         * Toggle visibility.
         */
        toggle() {
            if (this.isVisible) {
                this.hide();
            } else {
                this.show();
            }
        }

        /**
         * Embed electropherogram panel into this panel's chart host.
         */
        _embedElectropherogram() {
            this._embedState = Base.embedElectropherogram(
                this.electropherogramPanel,
                'profile-detection-chart-host',
                'profile-detection-chart-placeholder'
            );
        }

        /**
         * Return electropherogram panel to its original location.
         */
        _unembedElectropherogram() {
            Base.unembedElectropherogram(
                this.electropherogramPanel,
                this._embedState,
                'profile-detection-chart-placeholder'
            );
            this._embedState = null;
        }

        /**
         * Update target lanes based on filter.
         */
        _updateTargetLanes() {
            this.targetLanes = Base.getTargetLanes(this.laneFilter, this.stateManager);

            // Update count display
            const countEl = document.querySelector('#profile-detection-lane-count .count');
            if (countEl) {
                countEl.textContent = this.targetLanes.length;
            }

            // Update lane list
            this._renderLaneList();
        }

        /**
         * Render lane list in the panel.
         */
        _renderLaneList() {
            const listEl = document.getElementById('profile-detection-lane-list');
            if (!listEl) return;

            if (this.targetLanes.length === 0) {
                listEl.innerHTML = '<div class="gv-detection-lane-empty">No lanes match filter</div>';
                return;
            }

            listEl.innerHTML = this.targetLanes.map(lane => `
                <div class="gv-detection-lane-item" data-lane-id="${lane.id}">
                    <span class="gv-detection-lane-number">Lane ${lane.lane_number}</span>
                    <span class="gv-detection-lane-type">${lane.lane_type}</span>
                    <span class="gv-detection-lane-bands">${lane.bands?.length || 0} bands</span>
                </div>
            `).join('');

            // Bind click handlers for lane items → load profile in embedded electropherogram
            listEl.querySelectorAll('.gv-detection-lane-item').forEach(item => {
                item.addEventListener('click', () => {
                    const laneId = parseInt(item.dataset.laneId, 10);
                    if (laneId && this.electropherogramPanel) {
                        this.electropherogramPanel.loadProfile(laneId);
                        // Highlight active lane
                        listEl.querySelectorAll('.gv-detection-lane-item').forEach(i => i.classList.remove('active'));
                        item.classList.add('active');
                    }
                });
            });
        }

        /**
         * Run preview detection (first lane only, no save).
         */
        async _runPreview() {
            if (this.isProcessing || this.targetLanes.length === 0) return;

            this.isProcessing = true;
            Base.setButtonsEnabled(this._getButtonIds(), false);
            this._clearPreviews();

            try {
                // Preview on first lane only
                const lane = this.targetLanes[0];

                const result = await this.apiClient.detectPeaksFromProfile(lane.id, {
                    ...this.params,
                    preview: true,
                });

                if (result.success) {
                    this.previewResults = [{
                        laneId: lane.id,
                        peaks: result.peaks,
                    }];

                    this._renderPreviews();
                    this._updatePreviewStats(result);

                    // Emit preview data so embedded electropherogram can show peaks
                    this.eventBus.emit(Events.BAND_DETECTION_PREVIEW, {
                        laneId: lane.id,
                        bands: result.peaks || [],
                        bandCount: result.peaks?.length || 0,
                        profile: result.profile || null,
                    });
                } else {
                    throw new Error(result.error || 'Preview failed');
                }

            } catch (error) {
                console.error('[ProfileDetectionPanel] Preview error:', error);
                this.eventBus.emit(Events.PROFILE_DETECTION_ERROR, { error: error.message });
            } finally {
                this.isProcessing = false;
                Base.setButtonsEnabled(this._getButtonIds(), true);
            }
        }

        /**
         * Run full detection and save bands via Celery async task.
         */
        async _runDetection() {
            if (this.isProcessing || this.targetLanes.length === 0) return;

            this.isProcessing = true;
            Base.setButtonsEnabled(this._getButtonIds(), false);
            this._showProgress();

            this.eventBus.emit(Events.PROFILE_DETECTION_STARTED);

            try {
                const allIds = this.targetLanes.map(l => l.id);
                const laneIds = allIds.filter(id => !String(id).startsWith('temp_'));
                const unsavedCount = allIds.length - laneIds.length;

                if (laneIds.length === 0) {
                    this.eventBus.emit(Events.PROFILE_DETECTION_ERROR, {
                        error: 'Please save your annotations before running detection.',
                    });
                    return;
                }
                if (unsavedCount > 0) {
                    console.warn(`[ProfileDetectionPanel] Skipping ${unsavedCount} unsaved lane(s)`);
                }

                // Start async task
                console.log('[ProfileDetectionPanel] Starting async detection for', laneIds.length, 'lanes');
                const startResponse = await this.apiClient.detectPeaksProfileAsync(
                    this.analysisId,
                    laneIds,
                    this.params
                );

                if (!startResponse.success) {
                    throw new Error(startResponse.error || 'Failed to start detection task');
                }

                const taskId = startResponse.task_id;
                console.log('[ProfileDetectionPanel] Task started:', taskId);

                // Poll for completion using shared base
                const result = await Base.pollTaskStatus(this.apiClient, taskId, laneIds.length, {
                    intervalMs: this.pollIntervalMs,
                    maxAttempts: 600,
                    logPrefix: 'ProfileDetectionPanel',
                    onProgress: (current, total) => {
                        this._updateProgress(current, total);
                    },
                });

                const totalBandsCreated = result.total_bands_created || 0;

                // Emit completion
                this.eventBus.emit(Events.PROFILE_DETECTION_COMPLETED, {
                    lanesProcessed: result.lanes_processed || laneIds.length,
                    bandsCreated: totalBandsCreated,
                });

                // Request data reload
                this.eventBus.emit(Events.DATA_RELOAD_REQUESTED);

                // Hide panel
                this.hide();

                // Call callback if provided
                if (this.onDetectionComplete) {
                    this.onDetectionComplete(totalBandsCreated);
                }

            } catch (error) {
                console.error('[ProfileDetectionPanel] Detection error:', error);
                this.eventBus.emit(Events.PROFILE_DETECTION_ERROR, { error: error.message });
            } finally {
                this.isProcessing = false;
                Base.setButtonsEnabled(this._getButtonIds(), true);
                this._hideProgress();
            }
        }

        /**
         * Get button IDs for enable/disable.
         */
        _getButtonIds() {
            return [
                'profile-detection-preview',
                'profile-detection-detect',
                'profile-detection-reset',
            ];
        }

        /**
         * Render preview peaks on SVG.
         */
        _renderPreviews() {
            if (!this.previewGroup) return;

            this.previewGroup.clear();

            this.previewResults.forEach(result => {
                const lane = this.stateManager.getLane(result.laneId);
                if (!lane) return;

                result.peaks.forEach(peak => {
                    const x = lane.x;
                    const y = peak.y_position - (peak.width_px / 2);
                    const width = lane.width;
                    const height = peak.width_px;

                    // Different colors for orphan vs matched
                    const strokeColor = peak.is_orphan ? '#FF9800' : '#4CAF50';
                    const fillColor = peak.is_orphan ? 'rgba(255, 152, 0, 0.2)' : 'rgba(76, 175, 80, 0.2)';

                    this.previewGroup.rect(width, height)
                        .move(x, y)
                        .fill(fillColor)
                        .stroke({ color: strokeColor, width: 2, dasharray: '5,3' })
                        .attr('class', 'profile-peak-preview')
                        .attr('data-peak-y', peak.y_position);
                });
            });
        }

        /**
         * Clear preview overlays.
         */
        _clearPreviews() {
            if (this.previewGroup) {
                this.previewGroup.clear();
            }
            this.previewResults = [];

            // Reset stats display
            const statsEl = document.getElementById('profile-detection-preview-stats');
            if (statsEl) {
                statsEl.style.display = 'none';
            }

            const emptyEl = document.querySelector('#profile-detection-preview-content .gv-detection-preview-empty');
            if (emptyEl) {
                emptyEl.style.display = 'flex';
            }

            this.eventBus.emit(Events.BAND_DETECTION_PREVIEW_CLEAR);
        }

        /**
         * Update preview statistics display.
         */
        _updatePreviewStats(result) {
            const statsEl = document.getElementById('profile-detection-preview-stats');
            const emptyEl = document.querySelector('#profile-detection-preview-content .gv-detection-preview-empty');

            if (statsEl) {
                statsEl.style.display = 'flex';
            }
            if (emptyEl) {
                emptyEl.style.display = 'none';
            }

            const totalEl = document.getElementById('profile-detection-preview-total');
            const orphansEl = document.getElementById('profile-detection-preview-orphans');
            const matchedEl = document.getElementById('profile-detection-preview-matched');

            if (totalEl) {
                totalEl.textContent = result.total_peaks || result.peaks?.length || 0;
            }
            if (orphansEl) {
                orphansEl.textContent = result.orphan_count || result.peaks?.filter(p => p.is_orphan).length || 0;
            }
            if (matchedEl) {
                matchedEl.textContent = result.matched_count || result.peaks?.filter(p => !p.is_orphan).length || 0;
            }
        }

        /**
         * Show progress bar.
         */
        _showProgress() {
            Base.showProgress('profile-detection-progress', 'profile-detection-progress-fill', 'profile-detection-progress-text', 0, 0);
        }

        /**
         * Hide progress bar.
         */
        _hideProgress() {
            Base.hideProgress('profile-detection-progress');
        }

        /**
         * Update progress display.
         */
        _updateProgress(current, total) {
            Base.showProgress('profile-detection-progress', 'profile-detection-progress-fill', 'profile-detection-progress-text', current, total);
        }
    }

    // Export
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.ProfileDetectionPanel = ProfileDetectionPanel;

})(window);
