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

    const POINT_COLORS = {
        FIT: '#8B5CF6',           // violet — non-excluded calibration points
        EXCLUDED: 'rgba(139, 92, 246, 0.3)',  // ghost violet
        CONTROL: '#06B6D4',       // cyan — controls (diamond)
        SAMPLE: '#9CA3AF',        // grey — samples (cross)
        CURVE: '#8B5CF6',         // violet — fitted curve
        AXIS: '#6B7280',
        GRID: 'rgba(0,0,0,0.08)',
    };

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
                this._render(r);
            } catch (err) {
                console.error('[QuantificationModal] preview failed:', err);
                this._renderError(err);
            }
        }

        async save() {
            if (!this.lastResult || !this.lastResult.success) return;
            const body = this._readForm();
            try {
                const calib = await this.api.saveQuantification(this.analysisId, body);
                if (this.bus && typeof this.bus.emit === 'function') {
                    this.bus.emit('QUANT_CALIBRATION_CHANGED', { calib });
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
            this._renderSamplesTable(r.sample_projections || []);

            const r2El = document.getElementById('qcm-r2');
            if (r2El) r2El.textContent = (typeof r.r_squared === 'number') ? r.r_squared.toFixed(4) : '—';

            const nEl = document.getElementById('qcm-n');
            if (nEl) {
                const n = (r.calibration_points || []).filter(p => !p.is_excluded).length;
                nEl.textContent = n;
            }

            const eqEl = document.getElementById('qcm-equation');
            if (eqEl) eqEl.textContent = r.equation || '—';

            this._renderCurve(r);

            const saveBtn = document.getElementById('qcm-save');
            if (saveBtn) saveBtn.disabled = !r.success;
        }

        _renderError(err) {
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
                        <td>${load}</td>
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
                tbody.innerHTML = `<tr><td colspan="4" class="dm-table-empty">No control lanes marked.</td></tr>`;
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
                    </tr>
                `;
            }).join('');
        }

        _renderSamplesTable(samples) {
            const tbody = document.querySelector('#qcm-samples-table tbody');
            if (!tbody) return;
            if (!samples.length) {
                tbody.innerHTML = `<tr><td colspan="4" class="dm-table-empty">No sample lanes to project.</td></tr>`;
                return;
            }
            tbody.innerHTML = samples.map(s => `
                <tr>
                    <td>${s.lane_number ?? '—'}</td>
                    <td>${s.sample_label ?? '—'}</td>
                    <td>${this._fmtNum(s.corrected_area, 1)}</td>
                    <td>${this._fmtNum(s.estimated_amount, 2)}</td>
                </tr>
            `).join('');
        }

        // -----------------------------------------------------------------
        // Curve rendering — Canvas2D fallback (Chart.js NOT vendored).
        // -----------------------------------------------------------------

        _renderCurve(r) {
            const canvas = document.getElementById('qcm-curve-chart');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            if (!ctx) return;

            // Resize for DPR-aware crispness.
            const dpr = window.devicePixelRatio || 1;
            const cssW = canvas.width;
            const cssH = canvas.height;
            // Honour the original CSS size; only bump backing store.
            canvas.style.width = cssW + 'px';
            canvas.style.height = cssH + 'px';
            if (canvas.width !== cssW * dpr || canvas.height !== cssH * dpr) {
                canvas.width = cssW * dpr;
                canvas.height = cssH * dpr;
            }
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, cssW, cssH);

            const calibPoints = r.calibration_points || [];
            const controlPoints = r.control_points || [];
            const samplePoints = r.sample_projections || [];

            const fitPoints = calibPoints
                .filter(p => !p.is_excluded && p.corrected_area != null && p.load_amount != null)
                .map(p => ({ x: +p.corrected_area, y: +p.load_amount }));
            const ghostPoints = calibPoints
                .filter(p => p.is_excluded && p.corrected_area != null && p.load_amount != null)
                .map(p => ({ x: +p.corrected_area, y: +p.load_amount }));

            const showCtrlsEl = document.getElementById('qcm-show-controls-on-curve');
            const showCtrls = showCtrlsEl ? !!showCtrlsEl.checked : true;
            const ctrls = showCtrls
                ? controlPoints
                    .filter(c => c.corrected_area != null && c.predicted_amount != null)
                    .map(c => ({ x: +c.corrected_area, y: +c.predicted_amount }))
                : [];
            const samples = samplePoints
                .filter(s => s.corrected_area != null && s.estimated_amount != null)
                .map(s => ({ x: +s.corrected_area, y: +s.estimated_amount }));

            // Build curve: 50 evaluation points across area range.
            const allPts = [...fitPoints, ...ghostPoints, ...ctrls, ...samples];
            if (!allPts.length) {
                this._drawAxes(ctx, cssW, cssH, 0, 1, 0, 1, 'Corrected area', this._yLabel(r));
                this._drawText(ctx, cssW / 2, cssH / 2, 'No data to plot', '#9CA3AF', 'center');
                return;
            }
            const xs = allPts.map(p => p.x);
            const xMin = Math.min(...xs);
            const xMax = Math.max(...xs);
            const curve = [];
            if (r.success && xMax > xMin) {
                for (let i = 0; i <= 50; i++) {
                    const x = xMin + (xMax - xMin) * (i / 50);
                    const y = this._evalCurve(r, x);
                    if (y !== null && Number.isFinite(y)) curve.push({ x, y });
                }
            }

            // Determine y range: include all points + curve.
            const ys = [...allPts.map(p => p.y), ...curve.map(p => p.y)].filter(Number.isFinite);
            const yMin = Math.min(...ys);
            const yMax = Math.max(...ys);
            // Pad ranges 5%.
            const xPad = (xMax - xMin) * 0.05 || 1;
            const yPad = (yMax - yMin) * 0.05 || 1;
            const xLo = xMin - xPad;
            const xHi = xMax + xPad;
            const yLo = yMin - yPad;
            const yHi = yMax + yPad;

            const margin = { left: 56, right: 14, top: 14, bottom: 36 };
            const plotW = cssW - margin.left - margin.right;
            const plotH = cssH - margin.top - margin.bottom;

            const sx = (x) => margin.left + (x - xLo) / (xHi - xLo) * plotW;
            const sy = (y) => margin.top + (1 - (y - yLo) / (yHi - yLo)) * plotH;

            // Grid + axes.
            this._drawAxes(ctx, cssW, cssH, xLo, xHi, yLo, yHi, 'Corrected area', this._yLabel(r), margin);

            // Curve line.
            if (curve.length > 1) {
                ctx.save();
                ctx.strokeStyle = POINT_COLORS.CURVE;
                ctx.lineWidth = 2;
                ctx.beginPath();
                curve.forEach((p, i) => {
                    const X = sx(p.x), Y = sy(p.y);
                    if (i === 0) ctx.moveTo(X, Y);
                    else ctx.lineTo(X, Y);
                });
                ctx.stroke();
                ctx.restore();
            }

            // Excluded (ghost) points.
            ghostPoints.forEach(p => this._drawCircle(ctx, sx(p.x), sy(p.y), 5, POINT_COLORS.EXCLUDED));
            // Fit points.
            fitPoints.forEach(p => this._drawCircle(ctx, sx(p.x), sy(p.y), 5, POINT_COLORS.FIT));
            // Controls (cyan diamond).
            ctrls.forEach(p => this._drawDiamond(ctx, sx(p.x), sy(p.y), 7, POINT_COLORS.CONTROL));
            // Samples (grey cross).
            samples.forEach(p => this._drawCross(ctx, sx(p.x), sy(p.y), 6, POINT_COLORS.SAMPLE));

            // Tiny legend (top-right of plot).
            this._drawLegend(ctx, margin.left + plotW - 130, margin.top + 4, showCtrls);
        }

        _yLabel(r) {
            return `Amount (${r && r.unit === 'UG_ML' ? 'µg/mL' : 'µg'})`;
        }

        _evalCurve(r, x) {
            if (!r || !r.coefficients) return null;
            try {
                if (r.method === 'LINEAR') {
                    const { a, b } = r.coefficients;
                    if (a == null || b == null) return null;
                    return a * x + b;
                }
                if (r.method === 'POLYNOMIAL_2') {
                    // The fitter exposes either {coeffs:[a,b,c]} or {a,b,c}.
                    let a, b, c;
                    if (Array.isArray(r.coefficients.coeffs)) {
                        [a, b, c] = r.coefficients.coeffs;
                    } else {
                        a = r.coefficients.a;
                        b = r.coefficients.b;
                        c = r.coefficients.c;
                    }
                    if (a == null || b == null || c == null) return null;
                    return a * x * x + b * x + c;
                }
                if (r.method === 'FOUR_PL') {
                    const { a, d, c, b } = r.coefficients;
                    if (a == null || b == null || c == null || d == null) return null;
                    if (c === 0) return null;
                    return d + (a - d) / (1 + Math.pow(x / c, b));
                }
            } catch (e) {
                return null;
            }
            return null;
        }

        // -----------------------------------------------------------------
        // Canvas helpers
        // -----------------------------------------------------------------

        _drawAxes(ctx, w, h, xLo, xHi, yLo, yHi, xLabel, yLabel, margin) {
            margin = margin || { left: 56, right: 14, top: 14, bottom: 36 };
            const plotW = w - margin.left - margin.right;
            const plotH = h - margin.top - margin.bottom;

            ctx.save();
            // Plot border.
            ctx.strokeStyle = POINT_COLORS.AXIS;
            ctx.lineWidth = 1;
            ctx.strokeRect(margin.left, margin.top, plotW, plotH);

            // Gridlines + tick labels.
            ctx.fillStyle = POINT_COLORS.AXIS;
            ctx.font = '11px system-ui, sans-serif';
            ctx.strokeStyle = POINT_COLORS.GRID;

            const ticks = 4;
            for (let i = 0; i <= ticks; i++) {
                // X.
                const xv = xLo + (xHi - xLo) * (i / ticks);
                const X = margin.left + (i / ticks) * plotW;
                ctx.beginPath();
                ctx.moveTo(X, margin.top);
                ctx.lineTo(X, margin.top + plotH);
                ctx.stroke();
                ctx.fillText(this._fmtTick(xv), X - 12, margin.top + plotH + 14);

                // Y.
                const yv = yLo + (yHi - yLo) * (i / ticks);
                const Y = margin.top + (1 - i / ticks) * plotH;
                ctx.beginPath();
                ctx.moveTo(margin.left, Y);
                ctx.lineTo(margin.left + plotW, Y);
                ctx.stroke();
                ctx.fillText(this._fmtTick(yv), 4, Y + 4);
            }

            // Axis titles.
            ctx.fillStyle = POINT_COLORS.AXIS;
            ctx.font = '12px system-ui, sans-serif';
            ctx.fillText(xLabel, margin.left + plotW / 2 - 36, h - 6);
            ctx.save();
            ctx.translate(12, margin.top + plotH / 2 + 30);
            ctx.rotate(-Math.PI / 2);
            ctx.fillText(yLabel, 0, 0);
            ctx.restore();
            ctx.restore();
        }

        _fmtTick(v) {
            if (!Number.isFinite(v)) return '';
            if (Math.abs(v) >= 1000) return v.toFixed(0);
            if (Math.abs(v) >= 10) return v.toFixed(1);
            return v.toFixed(2);
        }

        _drawCircle(ctx, x, y, r, color) {
            ctx.save();
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.arc(x, y, r, 0, Math.PI * 2);
            ctx.fill();
            ctx.restore();
        }

        _drawDiamond(ctx, x, y, r, color) {
            ctx.save();
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.moveTo(x, y - r);
            ctx.lineTo(x + r, y);
            ctx.lineTo(x, y + r);
            ctx.lineTo(x - r, y);
            ctx.closePath();
            ctx.fill();
            ctx.restore();
        }

        _drawCross(ctx, x, y, r, color) {
            ctx.save();
            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(x - r, y - r);
            ctx.lineTo(x + r, y + r);
            ctx.moveTo(x - r, y + r);
            ctx.lineTo(x + r, y - r);
            ctx.stroke();
            ctx.restore();
        }

        _drawText(ctx, x, y, text, color, align) {
            ctx.save();
            ctx.fillStyle = color;
            ctx.font = '12px system-ui, sans-serif';
            ctx.textAlign = align || 'left';
            ctx.fillText(text, x, y);
            ctx.restore();
        }

        _drawLegend(ctx, x, y, showCtrls) {
            ctx.save();
            ctx.font = '11px system-ui, sans-serif';
            ctx.fillStyle = POINT_COLORS.AXIS;
            const rows = [
                { color: POINT_COLORS.FIT,      label: 'Calibration', shape: 'circle' },
                { color: POINT_COLORS.EXCLUDED, label: 'Excluded',    shape: 'circle' },
            ];
            if (showCtrls) {
                rows.push({ color: POINT_COLORS.CONTROL, label: 'Controls', shape: 'diamond' });
            }
            rows.push({ color: POINT_COLORS.SAMPLE, label: 'Samples', shape: 'cross' });
            rows.forEach((row, i) => {
                const ry = y + i * 14 + 4;
                if (row.shape === 'circle') {
                    this._drawCircle(ctx, x + 6, ry, 4, row.color);
                } else if (row.shape === 'diamond') {
                    this._drawDiamond(ctx, x + 6, ry, 5, row.color);
                } else {
                    this._drawCross(ctx, x + 6, ry, 4, row.color);
                }
                ctx.fillStyle = POINT_COLORS.AXIS;
                ctx.fillText(row.label, x + 16, ry + 4);
            });
            ctx.restore();
        }
    }

    // Export.
    global.Densitometry = global.Densitometry || {};
    global.Densitometry.QuantificationModal = QuantificationModal;
    // Also expose at top level for the wiring snippet in densitometry-app.js.
    global.QuantificationModal = QuantificationModal;
})(window);
