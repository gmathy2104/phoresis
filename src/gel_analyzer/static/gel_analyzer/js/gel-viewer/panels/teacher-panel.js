/**
 * Teacher Panel — 3-step calibration wizard for band detection.
 *
 * Lets the user mark background, small band, and large band regions
 * on the gel image, then calibrates detection parameters based on
 * those teaching examples.
 *
 * IIFE pattern, no MDB5. Registers as GelViewer.TeacherPanel.
 */
(function (global) {
    'use strict';

    const GelViewer = global.GelViewer || (global.GelViewer = {});
    const Events = GelViewer.Events;

    const STEPS = [
        {
            key: 'background',
            label: 'Background',
            icon: 'bi-cursor',
            instruction: 'Draw a rectangle on a <strong>band-free background</strong> region of the gel image.',
            color: 'var(--gv-teacher-bg-color)',
            cssClass: 'gv-teacher-rect-bg',
        },
        {
            key: 'small_band',
            label: 'Small Band',
            icon: 'bi-dash',
            instruction: 'Draw a rectangle around the <strong>thinnest / faintest band</strong> you want detected.',
            color: 'var(--gv-teacher-small-color)',
            cssClass: 'gv-teacher-rect-small',
        },
        {
            key: 'large_band',
            label: 'Large Band',
            icon: 'bi-arrows-expand',
            instruction: 'Draw a rectangle around the <strong>widest / most intense band</strong>.',
            color: 'var(--gv-teacher-large-color)',
            cssClass: 'gv-teacher-rect-large',
        },
    ];

    class TeacherPanel {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus
         * @param {APIClient} options.apiClient
         * @param {Object} options.stateManager
         * @param {Object} options.svg - SVG.js root element
         * @param {Object} options.drawingGroup - SVG group for overlays
         * @param {Function} options.getScale - Returns current zoom scale
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.apiClient = options.apiClient;
            this.stateManager = options.stateManager;
            this.svg = options.svg;
            this.drawingGroup = options.drawingGroup;
            this.viewer = options.viewer;
            this.getScale = options.getScale || (() => 1);
            this.getImagePoint = options.getImagePoint || (() => ({ x: 0, y: 0 }));

            // State
            this.currentStep = 0;
            this.regions = { background: null, small_band: null, large_band: null };
            this.mode = 'image'; // 'image' or 'profile'
            this.result = null;
            this.isOpen = false;

            // Drawing state
            this.isDrawing = false;
            this.startPoint = null;
            this.activeRect = null;
            this.drawnRects = {};  // key → SVG rect element

            // Bound mouse handlers for attach/detach
            this._boundMouseDown = (e) => this._onViewerMouseDown(e);
            this._boundMouseMove = (e) => this._onViewerMouseMove(e);
            this._boundMouseUp = (e) => this._onViewerMouseUp(e);

            // DOM refs
            this.panel = document.getElementById('teacher-panel');

            if (this.panel) {
                this._bindEvents();
            }
        }

        // ── Public API ────────────────────────────────

        show() {
            if (!this.panel) return;
            this.isOpen = true;  // Set BEFORE emitting to prevent re-entrant loop
            // Emit before rendering so detection panels can hide first
            this.eventBus.emit(Events.TEACHER_PANEL_SHOWN);
            this.panel.style.display = '';
            this.panel.classList.remove('gv-teacher-collapsed');
            this._reset();
            this._goToStep(0);
            this._attachMouseListeners();
        }

        hide() {
            if (!this.panel) return;
            this.isOpen = false;
            this.panel.style.display = 'none';
            this._clearAllRects();
            this._cancelDraw();
            this._detachMouseListeners();
            this.eventBus.emit(Events.TEACHER_PANEL_HIDDEN);
        }

        /**
         * Toggle collapse state (header-only vs full panel).
         */
        _toggleCollapse() {
            if (!this.panel) return;
            this.panel.classList.toggle('gv-teacher-collapsed');
        }

        toggle() {
            this.isOpen ? this.hide() : this.show();
        }

        // ── Viewer Mouse Listeners (attach/detach on show/hide) ──

        _attachMouseListeners() {
            if (!this.viewer) return;
            this.viewer.addEventListener('mousedown', this._boundMouseDown, true);
            this.viewer.addEventListener('mousemove', this._boundMouseMove, true);
            this.viewer.addEventListener('mouseup', this._boundMouseUp, true);
        }

        _detachMouseListeners() {
            if (!this.viewer) return;
            this.viewer.removeEventListener('mousedown', this._boundMouseDown, true);
            this.viewer.removeEventListener('mousemove', this._boundMouseMove, true);
            this.viewer.removeEventListener('mouseup', this._boundMouseUp, true);
        }

        _onViewerMouseDown(e) {
            if (!this.isOpen || this.mode !== 'image') return;
            if (this.result) return;
            if (e.button !== 0) return;

            const point = this.getImagePoint(e);
            if (!point) return;

            e.stopPropagation();
            this._cancelDraw();
            this.isDrawing = true;
            this.startPoint = { x: point.x, y: point.y };
        }

        _onViewerMouseMove(e) {
            if (!this.isDrawing || !this.startPoint) return;

            const point = this.getImagePoint(e);
            if (!point) return;

            e.stopPropagation();
            const rect = this._calcRect(this.startPoint, point);
            if (rect.width < 2 || rect.height < 2) return;

            this._renderDrawingRect(rect);
        }

        _onViewerMouseUp(e) {
            if (!this.isDrawing || !this.startPoint) return;
            this.isDrawing = false;

            const point = this.getImagePoint(e);
            if (!point) return;

            e.stopPropagation();
            const rect = this._calcRect(this.startPoint, point);
            const step = STEPS[this.currentStep];

            if (rect.width < 5 || rect.height < 5) {
                this._cancelDraw();
                return;
            }

            // Store region
            this.regions[step.key] = {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                source: 'image',
            };

            // Finalize drawn rect (keep it visible)
            this._finalizeRect(step);

            // Show card with dimensions
            this._updateCard(step.key);

            // Auto-advance to next step
            this._advanceStep();
        }

        // ── Event Binding ─────────────────────────────

        _bindEvents() {
            // Close button
            document.getElementById('teacher-close')?.addEventListener('click', () => this.hide());

            // Collapse toggle
            document.getElementById('teacher-collapse')?.addEventListener('click', () => this._toggleCollapse());

            // Escape key
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.isOpen) {
                    if (this.isDrawing) {
                        this._cancelDraw();
                    } else {
                        this.hide();
                    }
                }
            });

            // Step indicators (click to navigate)
            this.panel.querySelectorAll('.gv-teacher-step').forEach((el) => {
                el.addEventListener('click', () => {
                    const step = parseInt(el.dataset.step, 10);
                    if (!isNaN(step)) this._goToStep(step);
                });
            });

            // Mode toggle
            this.panel.querySelectorAll('.gv-teacher-mode-btn').forEach((btn) => {
                btn.addEventListener('click', () => {
                    this.mode = btn.dataset.mode;
                    this.panel.querySelectorAll('.gv-teacher-mode-btn').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');

                    if (this.mode === 'profile') {
                        const step = STEPS[this.currentStep];
                        this.eventBus.emit(Events.TEACHER_MARK_PROFILE_START, { step: step.key });
                    }
                });
            });

            // Skip button
            document.getElementById('teacher-skip')?.addEventListener('click', () => {
                this._advanceStep();
            });

            // Calibrate button
            document.getElementById('teacher-calibrate')?.addEventListener('click', () => {
                this._runCalibration();
            });

            // Apply button
            document.getElementById('teacher-apply')?.addEventListener('click', () => {
                this._applyResults();
            });

            // Clear buttons on cards
            this.panel.querySelectorAll('.gv-teacher-card-clear').forEach((btn) => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const key = btn.dataset.region;
                    this._clearRegion(key);
                });
            });

            // Listen for profile marking results
            this.eventBus.on(Events.TEACHER_MARK_PROFILE_RESULT, (data) => {
                this._onProfileResult(data);
            });

        }

        // ── Step Navigation ───────────────────────────

        _goToStep(stepIndex) {
            if (stepIndex < 0 || stepIndex >= STEPS.length) return;
            this.currentStep = stepIndex;

            // Update step indicators
            this.panel.querySelectorAll('.gv-teacher-step').forEach((el) => {
                const s = parseInt(el.dataset.step, 10);
                el.classList.toggle('active', s === stepIndex);
                el.classList.toggle('completed', this.regions[STEPS[s]?.key] != null);
            });

            // Update instruction
            const step = STEPS[stepIndex];
            const instructionEl = document.getElementById('teacher-instruction');
            if (instructionEl) {
                instructionEl.querySelector('.gv-teacher-instruction-icon').innerHTML =
                    `<i class="bi ${step.icon}"></i>`;
                instructionEl.querySelector('.gv-teacher-instruction-text').innerHTML =
                    step.instruction;
            }

            // Update skip/calibrate button state
            this._updateButtons();

            // If profile mode is active, re-trigger marking for the new step
            if (this.mode === 'profile') {
                this.eventBus.emit(Events.TEACHER_MARK_PROFILE_START, { step: step.key });
            }
        }

        _advanceStep() {
            if (this.currentStep < STEPS.length - 1) {
                this._goToStep(this.currentStep + 1);
            } else {
                // All steps done — enable calibrate
                this._updateButtons();
            }
        }

        _updateButtons() {
            const calibrateBtn = document.getElementById('teacher-calibrate');
            const skipBtn = document.getElementById('teacher-skip');
            const hasAnyRegion = Object.values(this.regions).some(r => r != null);

            if (calibrateBtn) {
                calibrateBtn.disabled = !hasAnyRegion;
            }

            // Hide skip when results are showing
            if (skipBtn) {
                skipBtn.style.display = this.result ? 'none' : '';
            }
        }

        // ── Region Management ─────────────────────────

        _clearRegion(key) {
            this.regions[key] = null;
            // Remove drawn rect
            if (this.drawnRects[key]) {
                this.drawnRects[key].remove();
                delete this.drawnRects[key];
            }
            // Hide card
            const card = document.getElementById(`teacher-card-${key}`);
            if (card) card.style.display = 'none';

            this._updateButtons();
        }

        _updateCard(key) {
            const region = this.regions[key];
            const card = document.getElementById(`teacher-card-${key}`);
            const body = document.getElementById(`teacher-card-${key}-body`);
            if (!card || !body || !region) return;

            card.style.display = '';
            body.innerHTML = `
                <div class="gv-teacher-card-stat">
                    <span class="gv-teacher-card-stat-label">Position:</span>
                    <span class="gv-teacher-card-stat-value">(${region.x}, ${region.y})</span>
                </div>
                <div class="gv-teacher-card-stat">
                    <span class="gv-teacher-card-stat-label">Size:</span>
                    <span class="gv-teacher-card-stat-value">${region.width} × ${region.height} px</span>
                </div>
                <div class="gv-teacher-card-stat">
                    <span class="gv-teacher-card-stat-label">Source:</span>
                    <span class="gv-teacher-card-stat-value">${region.source}</span>
                </div>
            `;
        }

        // ── SVG Drawing ───────────────────────────────

        _calcRect(p1, p2) {
            return {
                x: Math.min(p1.x, p2.x),
                y: Math.min(p1.y, p2.y),
                width: Math.abs(p2.x - p1.x),
                height: Math.abs(p2.y - p1.y),
            };
        }

        _renderDrawingRect(rect) {
            const step = STEPS[this.currentStep];
            if (this.activeRect) {
                this.activeRect
                    .attr({ x: rect.x, y: rect.y, width: rect.width, height: rect.height });
            } else if (this.drawingGroup) {
                this.activeRect = this.drawingGroup.rect(rect.width, rect.height)
                    .move(rect.x, rect.y)
                    .fill('none')
                    .stroke({ width: 2, color: step.color, dasharray: '6,3' })
                    .addClass(step.cssClass)
                    .attr('pointer-events', 'none');
            }
        }

        _finalizeRect(step) {
            // Remove old rect for this step
            if (this.drawnRects[step.key]) {
                this.drawnRects[step.key].remove();
            }

            if (this.activeRect) {
                // Make it solid
                this.activeRect.stroke({ width: 2, color: step.color, dasharray: '4,2' });
                this.drawnRects[step.key] = this.activeRect;
                this.activeRect = null;
            }
        }

        _cancelDraw() {
            this.isDrawing = false;
            this.startPoint = null;
            if (this.activeRect) {
                this.activeRect.remove();
                this.activeRect = null;
            }
        }

        _clearAllRects() {
            Object.values(this.drawnRects).forEach(r => r?.remove());
            this.drawnRects = {};
            this._cancelDraw();
        }

        // ── Profile Marking ───────────────────────────

        _onProfileResult(data) {
            if (!this.isOpen) return;
            const step = STEPS[this.currentStep];

            this.regions[step.key] = {
                y_start: data.y_start,
                y_end: data.y_end,
                source: 'profile',
                // Compute dimensions for card display
                x: 0,
                y: Math.min(data.y_start, data.y_end),
                width: 0,
                height: Math.abs(data.y_end - data.y_start),
            };

            this._updateCard(step.key);
            this._advanceStep();
        }

        // ── Calibration ───────────────────────────────

        async _runCalibration() {
            const calibrateBtn = document.getElementById('teacher-calibrate');
            if (!calibrateBtn || calibrateBtn.disabled) return;

            calibrateBtn.disabled = true;
            calibrateBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> <span>Calibrating...</span>';

            try {
                const result = await this.apiClient.calibrateDetection(this.regions);

                if (result.success) {
                    this.result = result;
                    this._showResults(result);
                } else {
                    this._showError(result.error || 'Calibration failed');
                }
            } catch (err) {
                this._showError(err.message || 'Calibration request failed');
            } finally {
                calibrateBtn.disabled = false;
                calibrateBtn.innerHTML = '<i class="bi bi-cpu"></i> <span>Calibrate</span>';
            }
        }

        _showResults(result) {
            const resultsEl = document.getElementById('teacher-results');
            if (!resultsEl) return;

            resultsEl.style.display = '';

            // Show apply button, hide calibrate
            const applyBtn = document.getElementById('teacher-apply');
            if (applyBtn) applyBtn.style.display = '';

            // Render diagnostics cards
            this._renderDiagnostics(result.diagnostics);

            // Render params table
            this._renderParamsTable(result.derived_params, result.explanations);

            this._updateButtons();
        }

        _renderDiagnostics(diagnostics) {
            const container = document.getElementById('teacher-diagnostics');
            if (!container) return;

            let html = '';

            if (diagnostics.background) {
                const bg = diagnostics.background;
                const polarity = diagnostics.polarity || 'unknown';
                const polarityLabel = polarity === 'bands_brighter' ? 'Bands brighter than background'
                    : polarity === 'bands_darker' ? 'Bands darker than background'
                    : 'Pending band selection';
                html += `
                    <div class="gv-teacher-diag-card">
                        <div class="gv-teacher-diag-title">
                            <span class="gv-teacher-card-dot" style="background: var(--gv-teacher-bg-color);"></span>
                            Background
                        </div>
                        <div class="gv-teacher-diag-stat">Mean intensity: <strong>${bg.mean}</strong></div>
                        <div class="gv-teacher-diag-stat">Noise (std): <strong>${bg.std}</strong></div>
                        <div class="gv-teacher-diag-stat">Range: [${bg.range[0]} — ${bg.range[1]}]</div>
                        <div class="gv-teacher-diag-stat gv-teacher-diag-highlight">${polarityLabel}</div>
                    </div>
                `;
            }

            if (diagnostics.small_band) {
                const sb = diagnostics.small_band;
                html += `
                    <div class="gv-teacher-diag-card">
                        <div class="gv-teacher-diag-title">
                            <span class="gv-teacher-card-dot" style="background: var(--gv-teacher-small-color);"></span>
                            Small Band
                        </div>
                        <div class="gv-teacher-diag-stat">Peak intensity: <strong>${sb.peak_intensity}</strong></div>
                        <div class="gv-teacher-diag-stat">Height: <strong>${sb.height_px} px</strong></div>
                        <div class="gv-teacher-diag-stat">SNR: <strong>${sb.snr}</strong></div>
                        <div class="gv-teacher-diag-stat">Prominence: <strong>${(sb.prominence_ratio * 100).toFixed(1)}%</strong></div>
                    </div>
                `;
            }

            if (diagnostics.large_band) {
                const lb = diagnostics.large_band;
                html += `
                    <div class="gv-teacher-diag-card">
                        <div class="gv-teacher-diag-title">
                            <span class="gv-teacher-card-dot" style="background: var(--gv-teacher-large-color);"></span>
                            Large Band
                        </div>
                        <div class="gv-teacher-diag-stat">Peak intensity: <strong>${lb.peak_intensity}</strong></div>
                        <div class="gv-teacher-diag-stat">Height: <strong>${lb.height_px} px</strong></div>
                        <div class="gv-teacher-diag-stat">SNR: <strong>${lb.snr}</strong></div>
                        <div class="gv-teacher-diag-stat">Prominence: <strong>${(lb.prominence_ratio * 100).toFixed(1)}%</strong></div>
                    </div>
                `;
            }

            container.innerHTML = html;
        }

        _renderParamsTable(derivedParams, explanations) {
            const tbody = document.getElementById('teacher-params-tbody');
            if (!tbody) return;

            // Map each explanation to a parameter name for display
            const paramKeys = [
                'invert_profile', 'sensitivity', 'min_band_width_px', 'max_band_width_px',
                'rolling_ball_radius', 'peak_prominence', 'min_intensity_ratio', 'peak_distance',
            ];

            // Build explanation lookup from explanation text heuristics
            const explMap = {};
            for (const exp of explanations) {
                for (const key of paramKeys) {
                    if (exp.toLowerCase().includes(key.replace(/_/g, ' ')) ||
                        exp.toLowerCase().includes(key)) {
                        explMap[key] = exp;
                    }
                }
            }

            let html = '';
            for (const key of paramKeys) {
                const val = derivedParams[key];
                if (val === undefined) continue;
                const explanation = explMap[key] || '';
                html += `
                    <tr>
                        <td class="gv-teacher-param-name">${key}</td>
                        <td class="gv-teacher-param-value">${val}</td>
                        <td class="gv-teacher-param-why">${explanation}</td>
                    </tr>
                `;
            }

            tbody.innerHTML = html;
        }

        _showError(message) {
            const resultsEl = document.getElementById('teacher-results');
            if (!resultsEl) return;

            resultsEl.style.display = '';
            const diag = document.getElementById('teacher-diagnostics');
            if (diag) {
                diag.innerHTML = `
                    <div class="gv-teacher-error">
                        <i class="bi bi-exclamation-triangle"></i>
                        <span>${message}</span>
                    </div>
                `;
            }
        }

        // ── Apply Results ─────────────────────────────

        _applyResults() {
            if (!this.result) return;

            this.eventBus.emit(Events.TEACHER_PARAMS_APPLIED, {
                params: this.result.derived_params,
            });

            this.hide();
        }

        // ── Reset ─────────────────────────────────────

        _reset() {
            this.currentStep = 0;
            this.regions = { background: null, small_band: null, large_band: null };
            this.result = null;
            this.mode = 'image';

            // Reset UI
            const resultsEl = document.getElementById('teacher-results');
            if (resultsEl) resultsEl.style.display = 'none';

            const applyBtn = document.getElementById('teacher-apply');
            if (applyBtn) applyBtn.style.display = 'none';

            // Reset mode toggle
            this.panel.querySelectorAll('.gv-teacher-mode-btn').forEach(b => {
                b.classList.toggle('active', b.dataset.mode === 'image');
            });

            // Hide all cards
            ['background', 'small_band', 'large_band'].forEach(key => {
                const card = document.getElementById(`teacher-card-${key}`);
                if (card) card.style.display = 'none';
            });

            // Clear diagnostics and params
            const diag = document.getElementById('teacher-diagnostics');
            if (diag) diag.innerHTML = '';
            const tbody = document.getElementById('teacher-params-tbody');
            if (tbody) tbody.innerHTML = '';

            this._clearAllRects();
            this._updateButtons();
        }
    }

    GelViewer.TeacherPanel = TeacherPanel;
})(window);
