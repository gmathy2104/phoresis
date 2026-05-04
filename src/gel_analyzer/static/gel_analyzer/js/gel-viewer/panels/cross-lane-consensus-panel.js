/**
 * cross-lane-consensus-panel.js
 *
 * Cross-Lane Consensus Panel — fills gaps in band detection by voting across
 * lanes. Uses the hybrid band-detection output as input and adds bands at
 * y-positions that are supported by ≥N% of lanes but missing in some of them.
 *
 * Provides Preview (dry-run), Apply (persist), and Undo (5 min window) flows.
 *
 * Unlike DetectionPanel / CV2DetectionPanel (which reference pre-existing
 * HTML elements), this panel creates its own DOM (backdrop + panel div) —
 * following the same pattern as HybridDetectionPanel.
 *
 * @requires GelViewer.Events
 * @requires GelViewer.APIClient
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    const DEFAULTS = {
        anchor_min_support: 0.66,   // 0.50 - 0.90
        y_tolerance_px: 5,          // 3 - 20
        soft_vote_min_snr: 0.5,     // 0.2 - 2.0
        enable_smile_correction: true,
        lane_type: 'sample',        // 'sample' | 'ladder' | 'all'
    };

    // Undo button visibility window (ms) — 5 min per spec.
    const UNDO_WINDOW_MS = 5 * 60 * 1000;

    // Debounce window for re-preview after slider changes.
    const PREVIEW_DEBOUNCE_MS = 300;

    class CrossLaneConsensusPanel {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus - Event bus for communication
         * @param {APIClient} options.apiClient - API client for server requests
         * @param {StateManager} [options.stateManager] - State manager reference (unused for now, forward-compat)
         * @param {Object} [options.svg] - SVG.js instance for previews
         * @param {string} options.analysisId - Analysis UUID
         * @param {HTMLElement} [options.viewerContainer] - Viewer container element
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.apiClient = options.apiClient;
            this.stateManager = options.stateManager || null;
            this.svg = options.svg || null;
            this.analysisId = options.analysisId;
            this.viewerContainer = options.viewerContainer || null;

            this.params = { ...DEFAULTS };
            this.isVisible = false;

            this._previewTimeout = null;
            this._requestInFlight = false;
            this._lastPreviewResult = null;       // last successful preview result
            this._lastApplyResult = null;         // last successful apply (has run_id)
            this._applyTimestamp = 0;             // ms since epoch of last apply
            this._undoVisibilityTimer = null;
            this._undoCountdownTimer = null;

            this._previewGroup = null;

            this._setupDOM();
            this._bindEvents();
        }

        // ─── DOM Setup ────────────────────────────────────────────────

        _setupDOM() {
            // Backdrop
            this.backdrop = document.createElement('div');
            this.backdrop.className = 'gv-clc-backdrop';
            this.backdrop.style.display = 'none';
            document.body.appendChild(this.backdrop);

            // Panel
            this.panel = document.createElement('div');
            this.panel.className = 'gv-clc-panel';
            this.panel.style.display = 'none';
            this.panel.innerHTML = this._buildHTML();
            document.body.appendChild(this.panel);

            // SVG preview group — draw overlay bands here.
            if (this.svg) {
                this._previewGroup = this.svg.group().attr('id', 'cross-lane-previews');
            }

            // Cache DOM refs
            this._minSupportSlider   = this.panel.querySelector('#gv-clc-min-support');
            this._minSupportValue    = this.panel.querySelector('#gv-clc-min-support-value');
            this._yToleranceSlider   = this.panel.querySelector('#gv-clc-y-tolerance');
            this._yToleranceValue    = this.panel.querySelector('#gv-clc-y-tolerance-value');
            this._softVoteSnrSlider  = this.panel.querySelector('#gv-clc-soft-vote-snr');
            this._softVoteSnrValue   = this.panel.querySelector('#gv-clc-soft-vote-snr-value');
            this._smileToggle        = this.panel.querySelector('#gv-clc-smile');
            this._laneTypeRadios     = this.panel.querySelectorAll('input[name="gv-clc-lane-type"]');

            this._previewBtn         = this.panel.querySelector('#gv-clc-preview-btn');
            this._applyBtn           = this.panel.querySelector('#gv-clc-apply-btn');
            this._undoBtn            = this.panel.querySelector('#gv-clc-undo-btn');

            this._statusText         = this.panel.querySelector('#gv-clc-status');
            this._spinner            = this.panel.querySelector('#gv-clc-spinner');
            this._summary            = this.panel.querySelector('#gv-clc-summary');

            this._inputs = [
                this._minSupportSlider,
                this._yToleranceSlider,
                this._softVoteSnrSlider,
                this._smileToggle,
                ...Array.from(this._laneTypeRadios),
                this._previewBtn,
                this._applyBtn,
                this._undoBtn,
            ].filter(Boolean);

            this._applyBtn.disabled = true;
            this._undoBtn.style.display = 'none';
        }

        _buildHTML() {
            const d = DEFAULTS;
            return `
                <div class="gv-clc-header">
                    <span class="gv-clc-title">
                        <i class="bi bi-bezier2"></i> Cross-Lane Consensus
                    </span>
                    <button class="gv-clc-close" aria-label="Close">&times;</button>
                </div>
                <div class="gv-clc-body">
                    <div class="gv-clc-control">
                        <label class="gv-clc-label" for="gv-clc-min-support">
                            Min lane support
                        </label>
                        <div class="gv-clc-slider-row">
                            <input type="range" id="gv-clc-min-support"
                                   min="50" max="90" value="${Math.round(d.anchor_min_support * 100)}" step="1"
                                   class="gv-clc-slider">
                            <span class="gv-clc-slider-value" id="gv-clc-min-support-value">${Math.round(d.anchor_min_support * 100)}%</span>
                        </div>
                    </div>

                    <div class="gv-clc-control">
                        <label class="gv-clc-label" for="gv-clc-y-tolerance">
                            Y tolerance (px)
                        </label>
                        <div class="gv-clc-slider-row">
                            <input type="range" id="gv-clc-y-tolerance"
                                   min="3" max="20" value="${d.y_tolerance_px}" step="1"
                                   class="gv-clc-slider">
                            <span class="gv-clc-slider-value" id="gv-clc-y-tolerance-value">${d.y_tolerance_px}</span>
                        </div>
                    </div>

                    <div class="gv-clc-control">
                        <label class="gv-clc-label" for="gv-clc-soft-vote-snr">
                            Soft vote min SNR
                        </label>
                        <div class="gv-clc-slider-row">
                            <input type="range" id="gv-clc-soft-vote-snr"
                                   min="0.2" max="2.0" value="${d.soft_vote_min_snr}" step="0.1"
                                   class="gv-clc-slider">
                            <span class="gv-clc-slider-value" id="gv-clc-soft-vote-snr-value">${d.soft_vote_min_snr.toFixed(1)}</span>
                        </div>
                    </div>

                    <div class="gv-clc-toggles">
                        <label class="gv-clc-toggle"
                               title="Fit a polynomial to anchor bands to correct for gel smile / skew.">
                            <input type="checkbox" id="gv-clc-smile" ${d.enable_smile_correction ? 'checked' : ''}>
                            <span>Smile correction (polynomial fit)</span>
                        </label>
                    </div>

                    <div class="gv-clc-control">
                        <label class="gv-clc-label">Apply to</label>
                        <div class="gv-clc-radio-group">
                            <label><input type="radio" name="gv-clc-lane-type" value="sample" ${d.lane_type === 'sample' ? 'checked' : ''}> Sample lanes (default)</label>
                            <label><input type="radio" name="gv-clc-lane-type" value="ladder" ${d.lane_type === 'ladder' ? 'checked' : ''}> Ladder lanes only</label>
                            <label><input type="radio" name="gv-clc-lane-type" value="all" ${d.lane_type === 'all' ? 'checked' : ''}> All lanes</label>
                        </div>
                    </div>

                    <div class="gv-clc-actions">
                        <button id="gv-clc-preview-btn" class="gv-clc-btn gv-clc-btn-primary">
                            <i class="bi bi-eye"></i> Preview
                        </button>
                        <button id="gv-clc-apply-btn" class="gv-clc-btn gv-clc-btn-success">
                            <i class="bi bi-check-circle"></i> Apply
                        </button>
                        <button id="gv-clc-undo-btn" class="gv-clc-btn gv-clc-btn-warning">
                            <i class="bi bi-arrow-counterclockwise"></i> Undo
                        </button>
                    </div>

                    <div class="gv-clc-status-row">
                        <span class="gv-clc-spinner" id="gv-clc-spinner" style="display:none;">
                            <i class="bi bi-hourglass-split"></i>
                        </span>
                        <span class="gv-clc-status-text" id="gv-clc-status">Ready</span>
                    </div>

                    <div id="gv-clc-summary" class="gv-clc-summary" style="display:none;"></div>
                </div>
            `;
        }

        // ─── Event Binding ────────────────────────────────────────────

        _bindEvents() {
            this.panel.querySelector('.gv-clc-close').addEventListener('click', () => this.hide());
            this.backdrop.addEventListener('click', () => this.hide());

            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.isVisible) this.hide();
            });

            this._minSupportSlider.addEventListener('input', () => {
                const pct = parseInt(this._minSupportSlider.value, 10);
                this.params.anchor_min_support = pct / 100;
                this._minSupportValue.textContent = `${pct}%`;
                this._schedulePreview();
            });

            this._yToleranceSlider.addEventListener('input', () => {
                const px = parseInt(this._yToleranceSlider.value, 10);
                this.params.y_tolerance_px = px;
                this._yToleranceValue.textContent = `${px}`;
                this._schedulePreview();
            });

            this._softVoteSnrSlider.addEventListener('input', () => {
                const snr = parseFloat(this._softVoteSnrSlider.value);
                this.params.soft_vote_min_snr = snr;
                this._softVoteSnrValue.textContent = snr.toFixed(1);
                this._schedulePreview();
            });

            this._smileToggle.addEventListener('change', () => {
                this.params.enable_smile_correction = this._smileToggle.checked;
                this._schedulePreview();
            });

            this._laneTypeRadios.forEach(radio => {
                radio.addEventListener('change', () => {
                    if (radio.checked) {
                        this.params.lane_type = radio.value;
                        this._schedulePreview();
                    }
                });
            });

            this._previewBtn.addEventListener('click', () => this._runPreview());
            this._applyBtn.addEventListener('click', () => this._runApply());
            this._undoBtn.addEventListener('click', () => this._runUndo());
        }

        // ─── Preview Scheduling (debounced) ───────────────────────────

        _schedulePreview() {
            clearTimeout(this._previewTimeout);
            // Only auto-re-preview if a preview has already been run at least once.
            if (!this._lastPreviewResult) return;
            this._previewTimeout = setTimeout(() => this._runPreview(), PREVIEW_DEBOUNCE_MS);
        }

        // ─── Request-In-Flight State ──────────────────────────────────

        _setBusy(busy, statusMessage) {
            this._requestInFlight = busy;
            this._inputs.forEach(el => {
                if (!el) return;
                // Never re-enable Apply if there's nothing to apply.
                if (el === this._applyBtn && !busy && (!this._lastPreviewResult ||
                        !this._lastPreviewResult.result ||
                        !this._lastPreviewResult.result.added_bands ||
                        this._lastPreviewResult.result.added_bands.length === 0)) {
                    el.disabled = true;
                    return;
                }
                el.disabled = busy;
            });
            if (this._spinner) this._spinner.style.display = busy ? 'inline-block' : 'none';
            if (statusMessage !== undefined && this._statusText) {
                this._statusText.textContent = statusMessage;
            }
        }

        // ─── Preview (dry run) ────────────────────────────────────────

        async _runPreview() {
            if (!this.analysisId) return;

            this._setBusy(true, 'Previewing…');
            this._clearPreviewSVG();

            try {
                const data = await this.apiClient.previewCrossLaneConsensus(
                    this.analysisId, this.params
                );
                this._lastPreviewResult = data;

                const result = data.result || {};
                const addedBands = result.added_bands || [];
                this._renderPreviewBands(addedBands);
                this._updateSummary(result, /* applied */ false, addedBands.length);

                this._setBusy(false, `Preview: ${addedBands.length} band${addedBands.length === 1 ? '' : 's'} would be added`);
                // _setBusy already guards Apply when addedBands is empty.
            } catch (error) {
                console.error('[CrossLaneConsensus] Preview failed:', error);
                this._lastPreviewResult = null;
                this._setBusy(false, `Preview failed: ${error.message || error}`);
            }
        }

        // ─── Apply ────────────────────────────────────────────────────

        async _runApply() {
            if (!this.analysisId) return;
            if (!this._lastPreviewResult) return;

            this._setBusy(true, 'Applying…');

            try {
                const data = await this.apiClient.applyCrossLaneConsensus(
                    this.analysisId, this.params
                );
                this._lastApplyResult = data;
                this._applyTimestamp = Date.now();

                const result = data.result || {};
                const addedCount = (result.added_bands && result.added_bands.length) || 0;
                this._updateSummary(result, /* applied */ true, addedCount);

                // Clear preview overlay — the real bands will arrive via reload.
                this._clearPreviewSVG();
                this._lastPreviewResult = null;

                // Trigger data reload — existing pattern used by other detection panels.
                // The original plan referenced a BANDS_ADDED event; the codebase uses
                // DATA_RELOAD_REQUESTED which refreshes all bands via annotation reload.
                if (this.eventBus) {
                    this.eventBus.emit(Events.DATA_RELOAD_REQUESTED);
                }

                this._showUndoButton();
                this._setBusy(false, `Applied: ${addedCount} band${addedCount === 1 ? '' : 's'} added`);
                this._applyBtn.disabled = true;
            } catch (error) {
                console.error('[CrossLaneConsensus] Apply failed:', error);
                this._setBusy(false, `Apply failed: ${error.message || error}`);
            }
        }

        // ─── Undo ─────────────────────────────────────────────────────

        async _runUndo() {
            if (!this.analysisId) return;
            if (!this._lastApplyResult) return;

            const runId = this._lastApplyResult.result && this._lastApplyResult.result.run_id;
            if (!runId) return;

            this._setBusy(true, 'Undoing…');
            try {
                const data = await this.apiClient.undoCrossLaneConsensus(this.analysisId, runId);
                const deleted = (data && data.deleted_count) || 0;

                this._hideUndoButton();
                this._lastApplyResult = null;

                if (this.eventBus) {
                    this.eventBus.emit(Events.DATA_RELOAD_REQUESTED);
                }

                this._setBusy(false, `Undo: ${deleted} band${deleted === 1 ? '' : 's'} removed`);
            } catch (error) {
                console.error('[CrossLaneConsensus] Undo failed:', error);
                this._setBusy(false, `Undo failed: ${error.message || error}`);
            }
        }

        // ─── Undo Button Visibility ───────────────────────────────────

        _showUndoButton() {
            this._undoBtn.style.display = 'inline-block';
            this._undoBtn.disabled = false;
            this._updateUndoCountdown();

            // Hide the button 5 min after apply.
            clearTimeout(this._undoVisibilityTimer);
            this._undoVisibilityTimer = setTimeout(
                () => this._hideUndoButton(), UNDO_WINDOW_MS
            );

            // Live-update the countdown label every 10s.
            clearInterval(this._undoCountdownTimer);
            this._undoCountdownTimer = setInterval(() => this._updateUndoCountdown(), 10 * 1000);
        }

        _hideUndoButton() {
            this._undoBtn.style.display = 'none';
            clearTimeout(this._undoVisibilityTimer);
            clearInterval(this._undoCountdownTimer);
            this._undoVisibilityTimer = null;
            this._undoCountdownTimer = null;
        }

        _updateUndoCountdown() {
            if (!this._applyTimestamp) return;
            const elapsed = Date.now() - this._applyTimestamp;
            const remaining = Math.max(0, UNDO_WINDOW_MS - elapsed);
            const mins = Math.ceil(remaining / 60000);
            this._undoBtn.innerHTML = `<i class="bi bi-arrow-counterclockwise"></i> Undo (${mins}m)`;
            if (remaining <= 0) this._hideUndoButton();
        }

        // ─── SVG Preview Rendering ────────────────────────────────────

        /**
         * Render proposed bands as green dashed overlay rectangles.
         * @param {Array} addedBands - `added_bands` entries from API response
         */
        _renderPreviewBands(addedBands) {
            if (!this._previewGroup || !addedBands) return;
            for (const band of addedBands) {
                const w = band.bbox_width || 0;
                const h = band.bbox_height || 0;
                const x = band.bbox_x || 0;
                const y = band.bbox_y || 0;
                if (w <= 0 || h <= 0) continue;
                this._previewGroup
                    .rect(w, h)
                    .attr('x', x)
                    .attr('y', y)
                    .addClass('gv-clc-preview-band');
            }
        }

        _clearPreviewSVG() {
            if (this._previewGroup) {
                this._previewGroup.clear();
            }
        }

        // ─── Last-Run Summary ─────────────────────────────────────────

        /**
         * Render the last-run summary (anchors + tiers + consensus + bands + skipped + duration).
         *
         * @param {Object} result - serialized ConsensusResult
         * @param {boolean} applied - true if Apply (not just Preview)
         * @param {number} bandsCount - number of bands proposed/added
         */
        _updateSummary(result, applied, bandsCount) {
            if (!result) {
                this._summary.style.display = 'none';
                return;
            }
            const fits = result.anchor_fits || [];
            const nAnchors = fits.length;
            const nQuadratic = fits.filter(f => f.fit_kind === 'quadratic').length;
            const nLinear = fits.filter(f => f.fit_kind === 'linear').length;

            const anchorBreakdownBits = [];
            if (nQuadratic) anchorBreakdownBits.push(`${nQuadratic} quadratic`);
            if (nLinear) anchorBreakdownBits.push(`${nLinear} linear`);
            const anchorBreakdown = anchorBreakdownBits.length
                ? ` (${anchorBreakdownBits.join(', ')})` : '';

            const consensusCount = result.consensus_positions_count || 0;
            const skippedLanes = (result.skipped_lanes_no_signal || []).length;
            const duration = result.duration_ms || 0;
            const tier = result.fallback_tier;

            const bandsLabel = applied ? 'bands added' : 'bands (preview)';

            this._summary.innerHTML = `
                <div class="gv-clc-summary-header">Last run</div>
                <div class="gv-clc-summary-row">${nAnchors} anchor${nAnchors === 1 ? '' : 's'}${anchorBreakdown}</div>
                <div class="gv-clc-summary-row">Fallback tier: ${tier !== undefined ? tier : '—'}</div>
                <div class="gv-clc-summary-row">${consensusCount} consensus position${consensusCount === 1 ? '' : 's'}</div>
                <div class="gv-clc-summary-row">${bandsCount} ${bandsLabel}</div>
                <div class="gv-clc-summary-row">${skippedLanes} skipped (no signal)</div>
                <div class="gv-clc-summary-row">${(duration / 1000).toFixed(2)}s</div>
            `;
            this._summary.style.display = 'block';
        }

        // ─── Show / Hide / Toggle ─────────────────────────────────────

        show() {
            this.panel.style.display = 'block';
            this.backdrop.style.display = 'block';
            this.isVisible = true;

            if (this.eventBus) {
                this.eventBus.emit(Events.CROSS_LANE_PANEL_SHOWN);
            }
        }

        hide() {
            this._clearPreviewSVG();
            this.panel.style.display = 'none';
            this.backdrop.style.display = 'none';
            this.isVisible = false;

            if (this.eventBus) {
                this.eventBus.emit(Events.CROSS_LANE_PANEL_HIDDEN);
            }
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
    global.GelViewer.CrossLaneConsensusPanel = CrossLaneConsensusPanel;

})(window);
