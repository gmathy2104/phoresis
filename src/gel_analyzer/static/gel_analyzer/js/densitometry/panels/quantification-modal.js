/**
 * Quantification Calibration Modal
 *
 * Drives the modal scaffolded in
 *   templates/gel_analyzer/includes/_quantification_modal.html
 *
 * Lifecycle:
 *   - open()         : show modal + immediately POST /preview/ to populate
 *   - refit()        : POST current form (method/unit/excluded_band_ids) to
 *                      /preview/ and re-render the three tables + curve
 *   - save()         : POST same body to /quantification/ which fits + saves
 *                      + applies (bulk-updates DensitometryResult.estimated_amount)
 *                      and broadcasts QUANT_CALIBRATION_CHANGED on the bus
 *
 * Per-point exclusion checkboxes call _debouncedRefit (200ms) so the user
 * can toggle several at a time without thrashing the server.
 *
 * The curve renderer uses a small Canvas2D scatter+polyline. Chart.js is NOT
 * vendored in this project (and AGENTS.md §1 forbids CDNs), so we draw the
 * fit curve, fit/excluded points, optional control points, and sample
 * projections manually. See _renderCurve below.
 */
(function (global) {
    'use strict';

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    class QuantificationModal {
        /**
         * @param {Object} opts
         * @param {Object} opts.apiClient - DensitometryApiClient
         * @param {string} opts.analysisId
         * @param {Object} opts.eventBus - DensitometryEventBus
         */
        constructor({ apiClient, analysisId, eventBus }) {
            this.api = apiClient;
            this.analysisId = analysisId;
            this.bus = eventBus;
            this.el = document.getElementById('quantification-modal');
            this.lastResult = null;
            this._refitTimer = null;

            if (!this.el) {
                console.warn('[QuantificationModal] #quantification-modal not in DOM — modal disabled');
                return;
            }
            this._wire();
        }

        // -----------------------------------------------------------------
        // Public lifecycle
        // -----------------------------------------------------------------

        open() {
            if (!this.el) return;
            this.el.hidden = false;
            this.refit().catch(err => {
                console.error('[QuantificationModal] initial refit failed:', err);
            });
        }

        close() {
            if (!this.el) return;
            this.el.hidden = true;
        }

        async refit() {
            const body = this._readForm();
            try {
                const r = await this.api.previewQuantification(this.analysisId, body);
                this.lastResult = r;
                // 422 returns a domain result with success=false (no points
                // yet, < 2 calibration points, densitometry missing, …). We
                // render the result either way — _render shows the empty
                // tables + the inline reason from r.error_message — so the
                // modal is informational, not an "error" state.
                this._render(r);
            } catch (err) {
                // Real transport errors only (network, 500, auth, …).
                console.error('[QuantificationModal] preview failed:', err);
                this._renderError(err);
            }
        }

        async save() {
            if (!this.lastResult || !this.lastResult.success || this._isLocked()) return;
            const body = this._readForm();
            try {
                const calib = await this.api.saveQuantification(this.analysisId, body);
                // saveQuantification also goes through _fetchDomain — a 422
                // here means the user tried to save a state that became
                // invalid between refit and save (rare; e.g. another tab
                // excluded the last point). Surface the reason inline.
                if (calib && calib.success === false) {
                    this._renderError(new Error(calib.error_message || 'Save failed'));
                    return;
                }
                if (this.bus && typeof this.bus.emit === 'function') {
                    // The bus's own event name ('quant:calibration:changed'): the table, the curve view and
                    // the page summary subscribe to it. The bare literal used before reached none of them.
                    const Events = global.Densitometry && global.Densitometry.Events;
                    this.bus.emit((Events && Events.QUANT_CALIBRATION_CHANGED) || 'quant:calibration:changed', { calib });
                }
                this.close();
            } catch (err) {
                console.error('[QuantificationModal] save failed:', err);
                this._renderError(err);
            }
        }

        // -----------------------------------------------------------------
        // Wiring
        // -----------------------------------------------------------------

        _wire() {
            this.el.querySelectorAll('[data-close]').forEach(b => {
                b.addEventListener('click', () => this.close());
            });
            const refitBtn = document.getElementById('qcm-refit');
            if (refitBtn) refitBtn.addEventListener('click', () => this.refit());

            const saveBtn = document.getElementById('qcm-save');
            if (saveBtn) saveBtn.addEventListener('click', () => this.save());

            ['qcm-method', 'qcm-unit'].forEach(id => {
                const sel = document.getElementById(id);
                if (sel) sel.addEventListener('change', () => this.refit());
            });

            const showCtrls = document.getElementById('qcm-show-controls-on-curve');
            if (showCtrls) {
                showCtrls.addEventListener('change', () => {
                    if (this.lastResult) this._render(this.lastResult);
                });
            }

            // Night | Day: the curve's canvas is drawn by script, it follows on a redraw.
            window.addEventListener('dsh:themechange', () => {
                if (this.lastResult) this._render(this.lastResult);
            });

            // Close on Escape
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.el && !this.el.hidden) this.close();
            });
        }

        _readForm() {
            const excluded = Array.from(
                document.querySelectorAll('#qcm-points-table input[type=checkbox]:checked')
            ).map(cb => cb.dataset.bandId).filter(Boolean);
            return {
                method: document.getElementById('qcm-method')?.value || 'LINEAR',
                unit: document.getElementById('qcm-unit')?.value || 'UG',
                excluded_band_ids: excluded,
            };
        }

        _debouncedRefit() {
            clearTimeout(this._refitTimer);
            this._refitTimer = setTimeout(() => this.refit(), 200);
        }

        // -----------------------------------------------------------------
        // Rendering
        // -----------------------------------------------------------------

        _render(r) {
            this._renderPointsTable(r.calibration_points || []);
            this._renderControlsTable(r.control_points || []);
            this._renderSamplesTable(r.sample_projections || [], r.calibration_area_range);

            const r2El = document.getElementById('qcm-r2');
            if (r2El) r2El.textContent = (typeof r.r_squared === 'number') ? r.r_squared.toFixed(4) : '—';

            const nEl = document.getElementById('qcm-n');
            if (nEl) {
                const n = (r.calibration_points || []).filter(p => !p.is_excluded).length;
                nEl.textContent = n;
            }

            const eqEl = document.getElementById('qcm-equation');
            if (eqEl) {
                // On a successful fit show the equation; on a domain failure
                // (success=false, returned with 422) show the reason inline
                // so the user knows what to do next (mark more CALIBRATION
                // bands, run densitometry, …). NOT prefixed with "error: " —
                // it's an expected informational state, not a crash.
                if (r.success) {
                    eqEl.textContent = r.equation || '—';
                } else if (r.error_message) {
                    eqEl.textContent = r.error_message;
                } else {
                    eqEl.textContent = '—';
                }
            }

            this._renderCurve(r);

            const saveBtn = document.getElementById('qcm-save');
            if (saveBtn) saveBtn.disabled = !r.success || this._isLocked();
        }

        /**
         * Save & apply is locked server-side on an approved analysis (the
         * template marks the button data-locked and shows why): a fit may
         * still be previewed, never saved.
         */
        _isLocked() {
            const saveBtn = document.getElementById('qcm-save');
            return !!(saveBtn && saveBtn.hasAttribute('data-locked'));
        }

        _renderError(err) {
            // Reserved for genuine transport errors (network, 500, auth) —
            // domain-level failures (no points, missing densito) go through
            // _render with r.success=false instead.
            const eqEl = document.getElementById('qcm-equation');
            if (eqEl) eqEl.textContent = `error: ${err.message || err}`;
            const saveBtn = document.getElementById('qcm-save');
            if (saveBtn) saveBtn.disabled = true;
        }

        _fmtNum(v, digits = 1) {
            if (v === null || v === undefined || Number.isNaN(v)) return '—';
            return Number(v).toFixed(digits);
        }

        _renderPointsTable(points) {
            const tbody = document.querySelector('#qcm-points-table tbody');
            if (!tbody) return;
            if (!points.length) {
                tbody.innerHTML = `<tr><td colspan="5" class="dm-table-empty">No calibration points marked.</td></tr>`;
                return;
            }
            tbody.innerHTML = points.map(p => {
                const rowCls = p.is_excluded ? 'dm-row-ghost' : '';
                const residual = (p.residual_pct !== null && p.residual_pct !== undefined)
                    ? `${Number(p.residual_pct).toFixed(1)}%` : '—';
                const load = (p.load_amount !== null && p.load_amount !== undefined)
                    ? `${p.load_amount} ${p.load_unit || ''}`.trim() : '—';
                const checked = p.is_excluded ? 'checked' : '';
                const bandId = p.band_id || '';
                return `
                    <tr class="${rowCls}">
                        <td>${p.lane_number ?? '—'}</td>
                        <td>${escapeHtml(load)}</td>
                        <td>${this._fmtNum(p.corrected_area, 1)}</td>
                        <td>${residual}</td>
                        <td><input type="checkbox" data-band-id="${bandId}" ${checked}></td>
                    </tr>
                `;
            }).join('');
            tbody.querySelectorAll('input[type=checkbox]').forEach(cb => {
                cb.addEventListener('change', () => this._debouncedRefit());
            });
        }

        _renderControlsTable(controls) {
            const tbody = document.querySelector('#qcm-controls-table tbody');
            if (!tbody) return;
            if (!controls.length) {
                tbody.innerHTML = `<tr><td colspan="5" class="dm-table-empty">No control lanes marked.</td></tr>`;
                return;
            }
            tbody.innerHTML = controls.map(c => {
                const cls = c.out_of_spec ? 'dm-row-warn' : '';
                const recovery = (c.recovery_pct !== null && c.recovery_pct !== undefined)
                    ? `${Number(c.recovery_pct).toFixed(1)}%` : '—';
                return `
                    <tr class="${cls}">
                        <td>${c.lane_number ?? '—'}</td>
                        <td>${c.known_amount ?? '—'}</td>
                        <td>${this._fmtNum(c.predicted_amount, 2)}</td>
                        <td>${recovery}</td>
                        <td>${this._rangeCell(c.calibration_range)}</td>
                    </tr>
                `;
            }).join('');
        }

        _renderSamplesTable(samples, areaRange) {
            const tbody = document.querySelector('#qcm-samples-table tbody');
            const caption = document.getElementById('qcm-samples-range');
            if (caption) {
                caption.textContent = (Array.isArray(areaRange) && areaRange.length === 2)
                    ? `Calibration range: area ${this._fmtNum(areaRange[0], 1)} – ${this._fmtNum(areaRange[1], 1)} (non-excluded standards). Outside it the amount is extrapolated.`
                    : '';
            }
            if (!tbody) return;
            if (!samples.length) {
                tbody.innerHTML = `<tr><td colspan="5" class="dm-table-empty">No sample lanes to project.</td></tr>`;
                return;
            }
            tbody.innerHTML = samples.map(s => `
                <tr>
                    <td>${s.lane_number ?? '—'}</td>
                    <td>${escapeHtml(s.sample_label ?? '—')}</td>
                    <td>${this._fmtNum(s.corrected_area, 1)}</td>
                    <td>${this._fmtNum(s.estimated_amount, 2)}</td>
                    <td>${this._rangeCell(s.calibration_range)}</td>
                </tr>
            `).join('');
        }

        /** The calibration-range chip of a projection (results-table-panel.js renders it, loaded first); '—' for none. */
        _rangeCell(code) {
            const chip = global.Densitometry && global.Densitometry.calibrationRangeChip;
            return (chip && chip(code)) || '—';
        }

        // -----------------------------------------------------------------
        // Curve rendering — delegates to QuantificationCurveRenderer
        // (Canvas2D; Chart.js is NOT vendored — see AGENTS.md §1).
        // -----------------------------------------------------------------

        _renderCurve(r) {
            const canvas = document.getElementById('qcm-curve-chart');
            if (!canvas) return;
            const renderer = global.Densitometry && global.Densitometry.QuantificationCurveRenderer;
            if (!renderer) {
                console.warn('[QuantificationModal] QuantificationCurveRenderer not loaded');
                return;
            }
            const showCtrlsEl = document.getElementById('qcm-show-controls-on-curve');
            const showCtrls = showCtrlsEl ? !!showCtrlsEl.checked : true;
            renderer.render(canvas, r, { showControls: showCtrls });
        }

        _evalCurve(r, x) {
            const renderer = global.Densitometry && global.Densitometry.QuantificationCurveRenderer;
            if (renderer && typeof renderer.evalCurve === 'function') {
                return renderer.evalCurve(r, x);
            }
            return null;
        }
    }

    // Export.
    global.Densitometry = global.Densitometry || {};
    global.Densitometry.QuantificationModal = QuantificationModal;
    // Also expose at top level for the wiring snippet in densitometry-app.js.
    global.QuantificationModal = QuantificationModal;
})(window);
