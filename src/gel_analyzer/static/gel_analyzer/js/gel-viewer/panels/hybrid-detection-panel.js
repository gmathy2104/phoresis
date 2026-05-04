/**
 * hybrid-detection-panel.js
 *
 * Hybrid Detection Panel — simplified band detection UI.
 *
 * Single sensitivity slider + two toggles. Internally cascades
 * CV2 primary detection with d1/d2 gap-fill for optimal results.
 *
 * Unlike CV2/Profile/Detection panels, this panel creates its own
 * DOM (backdrop + panel div) rather than referencing pre-existing
 * HTML elements.
 *
 * @requires GelViewer.Events
 * @requires GelViewer.DetectionPanelBase
 * @requires GelViewer.APIClient
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;
    const Base = global.GelViewer.DetectionPanelBase;

    const DEFAULTS = {
        sensitivity: 5,
        faint_bands: true,
        large_bands: true,
        split_wide_bands: true,
        mask_loading_wells: true,
        adaptive_threshold: true,
    };

    class HybridDetectionPanel {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus - Event bus for communication
         * @param {APIClient} options.apiClient - API client for server requests
         * @param {StateManager} options.stateManager - State manager reference
         * @param {Object} options.svg - SVG.js instance for previews
         * @param {Function} options.onDetectionComplete - Callback when detection completes
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.apiClient = options.apiClient;
            this.stateManager = options.stateManager;
            this.svg = options.svg;
            this.onDetectionComplete = options.onDetectionComplete;

            this.params = { ...DEFAULTS };
            this.isVisible = false;
            this._previewTimeout = null;
            this._previewResults = new Map(); // laneId → { bands, summary, laneNumber }
            this._previewGroup = null;

            // Hide animation guard (matches pattern in other panels)
            this._hideAnimationPending = false;

            this._setupDOM();
            this._bindEvents();
        }

        // ─── DOM Setup ────────────────────────────────────────────────

        _setupDOM() {
            // Backdrop
            this.backdrop = document.createElement('div');
            this.backdrop.className = 'gv-hybrid-backdrop';
            this.backdrop.style.display = 'none';
            document.body.appendChild(this.backdrop);

            // Panel
            this.panel = document.createElement('div');
            this.panel.className = 'gv-hybrid-panel';
            this.panel.style.display = 'none';
            this.panel.innerHTML = this._buildHTML();
            document.body.appendChild(this.panel);

            // SVG preview group — use SVG.js API to match other panels
            if (this.svg) {
                this._previewGroup = this.svg.group().attr('id', 'hybrid-band-previews');
            }

            // Cache DOM refs
            this._sensitivitySlider = this.panel.querySelector('#gv-hybrid-sensitivity');
            this._sensitivityValue  = this.panel.querySelector('#gv-hybrid-sensitivity-value');
            this._faintToggle       = this.panel.querySelector('#gv-hybrid-faint');
            this._largeToggle       = this.panel.querySelector('#gv-hybrid-large');
            this._splitWideToggle   = this.panel.querySelector('#gv-hdp-split-wide');
            this._maskWellsToggle   = this.panel.querySelector('#gv-hdp-mask-wells');
            this._adaptiveToggle    = this.panel.querySelector('#gv-hdp-adaptive');
            this._detectBtn         = this.panel.querySelector('#gv-hybrid-detect-btn');
            this._clearBtn          = this.panel.querySelector('#gv-hybrid-clear-btn');
            this._saveBtn           = this.panel.querySelector('#gv-hybrid-save-btn');
            this._resultsContainer  = this.panel.querySelector('#gv-hybrid-results');
        }

        _buildHTML() {
            return `
                <div class="gv-hybrid-header">
                    <span class="gv-hybrid-title">
                        <i class="bi bi-stars"></i> Hybrid Detection
                    </span>
                    <button class="gv-hybrid-close" aria-label="Close">&times;</button>
                </div>
                <div class="gv-hybrid-body">
                    <div class="gv-hybrid-control">
                        <label class="gv-hybrid-label">Sensitivity</label>
                        <div class="gv-hybrid-slider-row">
                            <span class="gv-hybrid-slider-label">Conservative</span>
                            <input type="range" id="gv-hybrid-sensitivity"
                                   min="1" max="10" value="5" step="1"
                                   class="gv-hybrid-slider">
                            <span class="gv-hybrid-slider-label">Aggressive</span>
                        </div>
                        <div class="gv-hybrid-slider-value" id="gv-hybrid-sensitivity-value">5 / 10</div>
                    </div>

                    <div class="gv-hybrid-toggles">
                        <label class="gv-hybrid-toggle">
                            <input type="checkbox" id="gv-hybrid-faint" checked>
                            <span>Detect faint bands</span>
                        </label>
                        <label class="gv-hybrid-toggle">
                            <input type="checkbox" id="gv-hybrid-large" checked>
                            <span>Handle large / diffuse bands</span>
                        </label>

                        <hr class="gv-hybrid-separator">

                        <label class="gv-hybrid-toggle"
                               title="Split wide CV2 bands that contain two overlapping peaks separated by a clean valley.">
                            <input type="checkbox" id="gv-hdp-split-wide" checked>
                            <span>Split doublets</span>
                        </label>
                        <label class="gv-hybrid-toggle"
                               title="Mask the chaotic top of lanes where loading wells produce false positives.">
                            <input type="checkbox" id="gv-hdp-mask-wells" checked>
                            <span>Mask loading wells</span>
                        </label>
                        <label class="gv-hybrid-toggle"
                               title="Apply a locally-calibrated threshold to 3 vertical zones of the lane.">
                            <input type="checkbox" id="gv-hdp-adaptive" checked>
                            <span>Adaptive threshold (per zone)</span>
                        </label>
                    </div>

                    <div class="gv-hybrid-control">
                        <label class="gv-hybrid-label">Apply to</label>
                        <div class="gv-hybrid-radio-group">
                            <label><input type="radio" name="gv-hybrid-lane-filter" value="all" checked> All lanes</label>
                            <label><input type="radio" name="gv-hybrid-lane-filter" value="selected"> Selected lane</label>
                            <label><input type="radio" name="gv-hybrid-lane-filter" value="sample"> Sample lanes only</label>
                            <label><input type="radio" name="gv-hybrid-lane-filter" value="ladder"> Ladder lanes only</label>
                        </div>
                    </div>

                    <div class="gv-hybrid-actions">
                        <button id="gv-hybrid-detect-btn" class="gv-hybrid-btn gv-hybrid-btn-primary">
                            <i class="bi bi-lightning-charge"></i> Detect Bands
                        </button>
                        <button id="gv-hybrid-clear-btn" class="gv-hybrid-btn gv-hybrid-btn-secondary">
                            <i class="bi bi-x-circle"></i> Clear
                        </button>
                    </div>

                    <div id="gv-hybrid-results" class="gv-hybrid-results" style="display:none;"></div>

                    <div class="gv-hybrid-actions">
                        <button id="gv-hybrid-save-btn" class="gv-hybrid-btn gv-hybrid-btn-success" style="display:none;">
                            <i class="bi bi-check-circle"></i> Save All
                        </button>
                    </div>
                </div>
            `;
        }

        // ─── Event Binding ────────────────────────────────────────────

        _bindEvents() {
            this.panel.querySelector('.gv-hybrid-close').addEventListener('click', () => this.hide());
            this.backdrop.addEventListener('click', () => this.hide());

            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.isVisible) this.hide();
            });

            this._sensitivitySlider.addEventListener('input', () => {
                this.params.sensitivity = parseInt(this._sensitivitySlider.value, 10);
                this._sensitivityValue.textContent = `${this.params.sensitivity} / 10`;
                this._schedulePreview();
            });

            this._faintToggle.addEventListener('change', () => {
                this.params.faint_bands = this._faintToggle.checked;
                this._schedulePreview();
            });

            this._largeToggle.addEventListener('change', () => {
                this.params.large_bands = this._largeToggle.checked;
                this._schedulePreview();
            });

            this._splitWideToggle.addEventListener('change', () => {
                this.params.split_wide_bands = this._splitWideToggle.checked;
                this._schedulePreview();
            });

            this._maskWellsToggle.addEventListener('change', () => {
                this.params.mask_loading_wells = this._maskWellsToggle.checked;
                this._schedulePreview();
            });

            this._adaptiveToggle.addEventListener('change', () => {
                this.params.adaptive_threshold = this._adaptiveToggle.checked;
                this._schedulePreview();
            });

            this._detectBtn.addEventListener('click', () => this._runDetection());
            this._clearBtn.addEventListener('click', () => this._clearPreviews());
            this._saveBtn.addEventListener('click', () => this._saveAll());
        }

        // ─── Lane Resolution ──────────────────────────────────────────

        /**
         * Get target lanes using Base helper (matches CV2/Detection/Profile panels).
         * Uses stateManager.getAllLanes() + getSelection() internally.
         * Filter values: 'all', 'selected', 'sample', 'ladder'
         */
        _getTargetLanes() {
            const filterRadio = this.panel.querySelector('input[name="gv-hybrid-lane-filter"]:checked');
            const filterValue = filterRadio ? filterRadio.value : 'all';

            if (Base) {
                return Base.getTargetLanes(filterValue, this.stateManager);
            }

            // Fallback if Base not available — use stateManager directly
            const lanesMap = this.stateManager && this.stateManager.getAllLanes
                ? this.stateManager.getAllLanes()
                : null;
            const allLanes = lanesMap ? Array.from(lanesMap.values()) : [];

            switch (filterValue) {
                case 'selected': {
                    const selection = this.stateManager && this.stateManager.getSelection
                        ? this.stateManager.getSelection()
                        : null;
                    const selectedId = selection && selection.type === 'lane' ? selection.id : null;
                    const selectedLane = allLanes.find(l => l.id === selectedId);
                    return selectedLane ? [selectedLane] : [];
                }
                case 'sample':
                    return allLanes.filter(l => l.lane_type === 'SAMPLE');
                case 'ladder':
                    return allLanes.filter(l => l.lane_type === 'LADDER');
                default:
                    return allLanes;
            }
        }

        // ─── Preview Scheduling ───────────────────────────────────────

        _schedulePreview() {
            clearTimeout(this._previewTimeout);
            this._previewTimeout = setTimeout(() => this._runDetection(), 300);
        }

        // ─── Detection (Preview Mode) ─────────────────────────────────

        async _runDetection() {
            const lanes = this._getTargetLanes();
            if (!lanes.length) return;

            this._detectBtn.disabled = true;
            this._detectBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> Detecting...';
            this._previewResults.clear();
            this._clearPreviewSVG();

            try {
                for (const lane of lanes) {
                    const result = await this.apiClient.detectBandsHybridPreview(lane.id, this.params);
                    if (result && result.success) {
                        this._previewResults.set(lane.id, {
                            bands: result.bands,
                            summary: result.summary,
                            laneNumber: lane.lane_number,
                        });
                        this._renderPreviewBands(lane, result.bands || []);
                    }
                }
                this._showResults();
            } catch (error) {
                console.error('[HybridDetection] Detection failed:', error);
            } finally {
                this._detectBtn.disabled = false;
                this._detectBtn.innerHTML = '<i class="bi bi-lightning-charge"></i> Detect Bands';
            }
        }

        // ─── Save ─────────────────────────────────────────────────────

        async _saveAll() {
            const lanes = this._getTargetLanes();
            if (!lanes.length) return;

            this._saveBtn.disabled = true;
            this._saveBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> Starting…';

            try {
                if (lanes.length === 1) {
                    // Single-lane path stays synchronous (endpoint writes bands before returning)
                    await this.apiClient.detectBandsHybridSave(lanes[0].id, this.params);
                } else {
                    // Multi-lane path: async Celery task — MUST poll until completion
                    // before reloading data, otherwise viewer reloads an empty DB.
                    const laneIds = lanes
                        .map(l => l.id)
                        .filter(id => !String(id).startsWith('temp_'));

                    const startResp = await this.apiClient.detectBandsHybridAsync(
                        laneIds, this.params, true,
                    );

                    if (startResp && startResp.task_id) {
                        this._saveBtn.innerHTML =
                            `<i class="bi bi-hourglass-split"></i> Processing 0/${laneIds.length}…`;
                        await this._pollTaskStatus(startResp.task_id, laneIds.length);
                    }
                }

                this._clearPreviews();

                // Only AFTER completion — reload bands from DB
                this.eventBus.emit(Events.DATA_RELOAD_REQUESTED);

                if (this.onDetectionComplete) {
                    this.onDetectionComplete();
                }

                this.hide();

            } catch (error) {
                console.error('[HybridDetection] Save failed:', error);
                this._saveBtn.innerHTML =
                    '<i class="bi bi-exclamation-triangle"></i> Save failed';
            } finally {
                // Re-enable button after a short delay so the user sees any final state
                setTimeout(() => {
                    this._saveBtn.disabled = false;
                    this._saveBtn.innerHTML = '<i class="bi bi-check-circle"></i> Save All';
                }, 800);
            }
        }

        /**
         * Poll the Celery task until completion, surfacing progress to the Save button.
         * Delegates to the shared DetectionPanelBase.pollTaskStatus helper used by
         * CV2 / Detection / Profile panels.
         */
        async _pollTaskStatus(taskId, totalLanes) {
            if (!Base || !Base.pollTaskStatus) {
                console.warn('[HybridDetection] pollTaskStatus helper unavailable — skipping poll');
                return;
            }

            const result = await Base.pollTaskStatus(this.apiClient, taskId, totalLanes, {
                intervalMs: 500,
                maxAttempts: 600,
                logPrefix: 'HybridDetection',
                onProgress: (current, total) => {
                    this._saveBtn.innerHTML =
                        `<i class="bi bi-hourglass-split"></i> Processing ${current}/${total}…`;
                },
            });

            const totalBands = (result && result.total_bands != null) ? result.total_bands : '?';
            this._saveBtn.innerHTML =
                `<i class="bi bi-check-circle"></i> Done — ${totalBands} bands`;
            return result;
        }

        // ─── SVG Preview Rendering ────────────────────────────────────

        /**
         * Render band preview rectangles using SVG.js API (matches CV2/Detection panels).
         */
        _renderPreviewBands(lane, bands) {
            if (!this._previewGroup) return;

            for (const band of bands) {
                this._previewGroup
                    .rect(band.bbox_width, band.bbox_height)
                    .attr('x', band.bbox_x)
                    .attr('y', band.bbox_y)
                    .addClass('gv-hybrid-preview-band');
            }
        }

        _clearPreviewSVG() {
            if (this._previewGroup) {
                this._previewGroup.clear();
            }
        }

        // ─── Preview Results Display ──────────────────────────────────

        _clearPreviews() {
            this._previewResults.clear();
            this._clearPreviewSVG();
            this._resultsContainer.style.display = 'none';
            this._saveBtn.style.display = 'none';
        }

        _showResults() {
            if (!this._previewResults.size) {
                this._resultsContainer.style.display = 'none';
                this._saveBtn.style.display = 'none';
                return;
            }

            let totalBands = 0;
            let html = '<div class="gv-hybrid-results-header">Results</div>';

            for (const [laneId, data] of this._previewResults) {
                const primary  = (data.summary && data.summary.primary_bands)  || 0;
                const gapFill  = (data.summary && data.summary.gap_fill_bands) || 0;
                const total    = (data.bands && data.bands.length) || 0;
                totalBands += total;
                const gapLabel = gapFill > 0 ? ` (${primary} + ${gapFill} gap-fill)` : '';
                html += `<div class="gv-hybrid-result-row">Lane ${data.laneNumber}: ${total} bands${gapLabel}</div>`;
            }

            html += `<div class="gv-hybrid-results-total">Total: ${totalBands} bands</div>`;

            this._resultsContainer.innerHTML = html;
            this._resultsContainer.style.display = 'block';
            this._saveBtn.style.display = totalBands > 0 ? 'block' : 'none';
        }

        // ─── Show / Hide / Toggle ─────────────────────────────────────

        show() {
            if (this._hideAnimationPending) return;

            this.panel.style.display = 'block';
            this.backdrop.style.display = 'block';
            this.isVisible = true;

            this.eventBus.emit(Events.HYBRID_DETECTION_PANEL_SHOWN);
        }

        hide() {
            this._clearPreviews();
            this.panel.style.display = 'none';
            this.backdrop.style.display = 'none';
            this.isVisible = false;

            this.eventBus.emit(Events.HYBRID_DETECTION_PANEL_HIDDEN);
        }

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
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.HybridDetectionPanel = HybridDetectionPanel;

})(window);
