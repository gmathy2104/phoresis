/**
 * Quantification Curve Renderer
 *
 * Standalone Canvas2D renderer for the quantification calibration curve.
 * Used by:
 *   - QuantificationModal (modal preview, see quantification-modal.js)
 *   - chromatogram-panel "Quantification curve" tab (Phase 7, planned)
 *
 * Chart.js is NOT vendored in this project (and AGENTS.md §1 forbids CDNs),
 * so we draw a small scatter+polyline manually.
 *
 * Public API:
 *   QuantificationCurveRenderer.render(canvas, result, opts)
 *   QuantificationCurveRenderer.evalCurve(result, x)
 *
 * `result` is the JSON returned by the /quantification/preview/ endpoint
 * (`QuantResult.to_dict()` server-side):
 *   {
 *     success, method, unit, equation, r_squared,
 *     coefficients: { ... method-specific ... },
 *     calibration_points: [{lane_number, load_amount, load_unit,
 *                            corrected_area, residual_pct, is_excluded,
 *                            band_id}, ...],
 *     control_points:    [{lane_number, known_amount, predicted_amount,
 *                            recovery_pct, out_of_spec, corrected_area}, ...],
 *     sample_projections:[{lane_number, sample_label, corrected_area,
 *                            estimated_amount}, ...],
 *   }
 */
(function (global) {
    'use strict';

    const COLORS = {
        FIT: '#8B5CF6',
        EXCLUDED: 'rgba(139, 92, 246, 0.3)',
        CONTROL: '#06B6D4',
        SAMPLE: '#9CA3AF',
        CURVE: '#8B5CF6',
        AXIS: '#6B7280',
        GRID: 'rgba(0,0,0,0.08)',
        EMPTY: '#9CA3AF',
    };

    function evalCurve(r, x) {
        if (!r || !r.coefficients) return null;
        try {
            if (r.method === 'LINEAR') {
                const { a, b } = r.coefficients;
                if (a == null || b == null) return null;
                return a * x + b;
            }
            if (r.method === 'POLYNOMIAL_2') {
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

    function _yLabel(r) {
        return `Amount (${r && r.unit === 'UG_ML' ? 'µg/mL' : 'µg'})`;
    }

    function _fmtTick(v) {
        if (!Number.isFinite(v)) return '';
        if (Math.abs(v) >= 1000) return v.toFixed(0);
        if (Math.abs(v) >= 10) return v.toFixed(1);
        return v.toFixed(2);
    }

    function _drawCircle(ctx, x, y, r, color) {
        ctx.save();
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
    }

    function _drawDiamond(ctx, x, y, r, color) {
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

    function _drawCross(ctx, x, y, r, color) {
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

    function _drawText(ctx, x, y, text, color, align) {
        ctx.save();
        ctx.fillStyle = color;
        ctx.font = '12px system-ui, sans-serif';
        ctx.textAlign = align || 'left';
        ctx.fillText(text, x, y);
        ctx.restore();
    }

    function _drawAxes(ctx, w, h, xLo, xHi, yLo, yHi, xLabel, yLabel, margin) {
        const plotW = w - margin.left - margin.right;
        const plotH = h - margin.top - margin.bottom;

        ctx.save();
        ctx.strokeStyle = COLORS.AXIS;
        ctx.lineWidth = 1;
        ctx.strokeRect(margin.left, margin.top, plotW, plotH);

        ctx.fillStyle = COLORS.AXIS;
        ctx.font = '11px system-ui, sans-serif';
        ctx.strokeStyle = COLORS.GRID;

        const ticks = 4;
        for (let i = 0; i <= ticks; i++) {
            const xv = xLo + (xHi - xLo) * (i / ticks);
            const X = margin.left + (i / ticks) * plotW;
            ctx.beginPath();
            ctx.moveTo(X, margin.top);
            ctx.lineTo(X, margin.top + plotH);
            ctx.stroke();
            ctx.fillText(_fmtTick(xv), X - 12, margin.top + plotH + 14);

            const yv = yLo + (yHi - yLo) * (i / ticks);
            const Y = margin.top + (1 - i / ticks) * plotH;
            ctx.beginPath();
            ctx.moveTo(margin.left, Y);
            ctx.lineTo(margin.left + plotW, Y);
            ctx.stroke();
            ctx.fillText(_fmtTick(yv), 4, Y + 4);
        }

        ctx.fillStyle = COLORS.AXIS;
        ctx.font = '12px system-ui, sans-serif';
        ctx.fillText(xLabel, margin.left + plotW / 2 - 36, h - 6);
        ctx.save();
        ctx.translate(12, margin.top + plotH / 2 + 30);
        ctx.rotate(-Math.PI / 2);
        ctx.fillText(yLabel, 0, 0);
        ctx.restore();
        ctx.restore();
    }

    function _drawLegend(ctx, x, y, showCtrls) {
        ctx.save();
        ctx.font = '11px system-ui, sans-serif';
        const rows = [
            { color: COLORS.FIT, label: 'Calibration', shape: 'circle' },
            { color: COLORS.EXCLUDED, label: 'Excluded', shape: 'circle' },
        ];
        if (showCtrls) {
            rows.push({ color: COLORS.CONTROL, label: 'Controls', shape: 'diamond' });
        }
        rows.push({ color: COLORS.SAMPLE, label: 'Samples', shape: 'cross' });
        rows.forEach((row, i) => {
            const ry = y + i * 14 + 4;
            if (row.shape === 'circle') _drawCircle(ctx, x + 6, ry, 4, row.color);
            else if (row.shape === 'diamond') _drawDiamond(ctx, x + 6, ry, 5, row.color);
            else _drawCross(ctx, x + 6, ry, 4, row.color);
            ctx.fillStyle = COLORS.AXIS;
            ctx.fillText(row.label, x + 16, ry + 4);
        });
        ctx.restore();
    }

    /**
     * Render the calibration curve onto a canvas.
     * @param {HTMLCanvasElement} canvas
     * @param {Object} r - quantification result (see file header)
     * @param {Object} [opts]
     * @param {boolean} [opts.showControls=true]
     */
    function render(canvas, r, opts) {
        if (!canvas || !r) return;
        opts = opts || {};
        const showCtrls = opts.showControls !== false;

        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const dpr = global.devicePixelRatio || 1;
        // Honour the canvas's CSS-declared size (set via attributes in the
        // template). Only resize the backing store for crisp rendering.
        const cssW = canvas.width / dpr || canvas.width;
        const cssH = canvas.height / dpr || canvas.height;
        const targetW = (canvas.dataset && canvas.dataset.cssWidth)
            ? parseInt(canvas.dataset.cssWidth, 10) : cssW;
        const targetH = (canvas.dataset && canvas.dataset.cssHeight)
            ? parseInt(canvas.dataset.cssHeight, 10) : cssH;
        canvas.style.width = targetW + 'px';
        canvas.style.height = targetH + 'px';
        if (canvas.width !== targetW * dpr || canvas.height !== targetH * dpr) {
            canvas.width = targetW * dpr;
            canvas.height = targetH * dpr;
        }
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, targetW, targetH);

        const calibPoints = r.calibration_points || [];
        const controlPoints = r.control_points || [];
        const samplePoints = r.sample_projections || [];

        const fitPoints = calibPoints
            .filter(p => !p.is_excluded && p.corrected_area != null && p.load_amount != null)
            .map(p => ({ x: +p.corrected_area, y: +p.load_amount }));
        const ghostPoints = calibPoints
            .filter(p => p.is_excluded && p.corrected_area != null && p.load_amount != null)
            .map(p => ({ x: +p.corrected_area, y: +p.load_amount }));
        const ctrls = showCtrls
            ? controlPoints
                .filter(c => c.corrected_area != null && c.predicted_amount != null)
                .map(c => ({ x: +c.corrected_area, y: +c.predicted_amount }))
            : [];
        const samples = samplePoints
            .filter(s => s.corrected_area != null && s.estimated_amount != null)
            .map(s => ({ x: +s.corrected_area, y: +s.estimated_amount }));

        const allPts = [...fitPoints, ...ghostPoints, ...ctrls, ...samples];
        const margin = { left: 56, right: 14, top: 14, bottom: 36 };

        if (!allPts.length) {
            _drawAxes(ctx, targetW, targetH, 0, 1, 0, 1, 'Corrected area', _yLabel(r), margin);
            _drawText(ctx, targetW / 2, targetH / 2, 'No data to plot', COLORS.EMPTY, 'center');
            return;
        }

        const xs = allPts.map(p => p.x);
        const xMin = Math.min(...xs);
        const xMax = Math.max(...xs);
        const curve = [];
        if (r.success && xMax > xMin) {
            for (let i = 0; i <= 50; i++) {
                const x = xMin + (xMax - xMin) * (i / 50);
                const y = evalCurve(r, x);
                if (y !== null && Number.isFinite(y)) curve.push({ x, y });
            }
        }
        const ys = [...allPts.map(p => p.y), ...curve.map(p => p.y)].filter(Number.isFinite);
        const yMin = Math.min(...ys);
        const yMax = Math.max(...ys);
        const xPad = (xMax - xMin) * 0.05 || 1;
        const yPad = (yMax - yMin) * 0.05 || 1;
        const xLo = xMin - xPad;
        const xHi = xMax + xPad;
        const yLo = yMin - yPad;
        const yHi = yMax + yPad;

        const plotW = targetW - margin.left - margin.right;
        const plotH = targetH - margin.top - margin.bottom;
        const sx = (x) => margin.left + (x - xLo) / (xHi - xLo) * plotW;
        const sy = (y) => margin.top + (1 - (y - yLo) / (yHi - yLo)) * plotH;

        _drawAxes(ctx, targetW, targetH, xLo, xHi, yLo, yHi, 'Corrected area', _yLabel(r), margin);

        if (curve.length > 1) {
            ctx.save();
            ctx.strokeStyle = COLORS.CURVE;
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

        ghostPoints.forEach(p => _drawCircle(ctx, sx(p.x), sy(p.y), 5, COLORS.EXCLUDED));
        fitPoints.forEach(p => _drawCircle(ctx, sx(p.x), sy(p.y), 5, COLORS.FIT));
        ctrls.forEach(p => _drawDiamond(ctx, sx(p.x), sy(p.y), 7, COLORS.CONTROL));
        samples.forEach(p => _drawCross(ctx, sx(p.x), sy(p.y), 6, COLORS.SAMPLE));

        _drawLegend(ctx, margin.left + plotW - 130, margin.top + 4, showCtrls);
    }

    global.Densitometry = global.Densitometry || {};
    global.Densitometry.QuantificationCurveRenderer = { render, evalCurve };
    // Top-level alias for parity with the modal class export.
    global.QuantificationCurveRenderer = global.Densitometry.QuantificationCurveRenderer;
})(window);
