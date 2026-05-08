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

    // ====================================================================
    // Interactive D3/SVG renderer for the panel "Quantification curve" view
    // ====================================================================
    //
    // The Canvas2D `render` above is kept for the calibration modal
    // (fixed-size chart inside a 2x2 grid cell, no interactivity). The
    // panel sub-view in densito's Graphical View needs more:
    //   - dark theme matching the chromatogram (D3 SVG)
    //   - responsive sizing (re-renders on container resize, e.g. when
    //     the magnifier expands the panel to full screen)
    //   - hover tooltip on calibration / control / sample points
    //   - click on a sample point → emit BAND_SELECTED so the gel
    //     overview, results table, and band detail panels follow
    //   - external highlight(bandId) so a click in any of the other
    //     panels selects the matching point on the curve
    //
    // Returns a small controller {update, highlight, clearHighlight,
    // resize, destroy} so the host (chromatogram-panel) can drive
    // re-renders without re-querying anything.

    const PANEL_COLORS = {
        FIT: '#a78bfa',                // Violet-400 — calibration fit points
        EXCLUDED: 'rgba(167, 139, 250, 0.35)',
        CONTROL: '#22d3ee',            // Cyan-400 — controls
        SAMPLE: '#f87171',             // Red-400 — sample projections
        CURVE: '#a78bfa',              // Violet-400 — fit curve
        AXIS: 'rgba(255, 255, 255, 0.45)',
        AXIS_LINE: 'rgba(255, 255, 255, 0.18)',
        GRID: 'rgba(255, 255, 255, 0.06)',
        TEXT: 'rgba(255, 255, 255, 0.72)',
        TEXT_MUTED: 'rgba(255, 255, 255, 0.45)',
        EMPTY: 'rgba(255, 255, 255, 0.4)',
        HIGHLIGHT: '#fbbf24',          // Amber-400 — selection ring
    };

    /**
     * Normalize a server-side QuantPoint into the {x, y, ...} shape used
     * by the renderer. The caller passes the explicit y field name
     * ('load_amount' / 'predicted_amount' / 'estimated_amount') because
     * the right choice depends on the point's *role*, not on which
     * fields happen to be populated:
     *
     *   - calibration  → load_amount (the measured truth that the fit
     *                    is trying to approximate; predicted_amount on a
     *                    calibration point is by construction the curve
     *                    eval at that area, so plotting it puts the
     *                    point on the line and erases the residual).
     *   - control      → predicted_amount (matches the modal's modal
     *                    QC table, where Predicted is what the curve
     *                    evaluates and Recovery = Predicted/Known).
     *   - sample       → estimated_amount (the projection the user
     *                    cares about).
     */
    function _normalizePoint(p, yField) {
        const yRaw = (yField && p[yField] != null) ? p[yField] : null;
        return {
            band_id: p.band_id || null,
            lane_id: p.lane_id || null,
            lane_number: p.lane_number ?? null,
            sample_label: p.sample_label || null,
            x: p.corrected_area != null ? +p.corrected_area : null,
            y: yRaw != null ? +yRaw : null,
            is_excluded: !!p.is_excluded,
            recovery_pct: p.recovery_pct != null ? +p.recovery_pct : null,
            out_of_spec: !!p.out_of_spec,
            // Loaded amount kept on the side for tooltips on calibration
            // ghosts (the user wants to see "Load: X" even when they
            // toggled the point off the fit).
            load_amount: p.load_amount != null ? +p.load_amount : null,
        };
    }

    /**
     * Mount an interactive quantification curve into a container.
     * @param {HTMLElement} container - host div (will get an SVG child)
     * @param {Object} result - quantification result (same shape as render)
     * @param {Object} [opts]
     * @param {Object} [opts.state] - densitometry state — preferred path for
     *     clicks so state.selectBand() runs and the parent lane is also
     *     selected, mirroring a real gel-band click. Falls back to raw
     *     eventBus.emit when state is absent.
     * @param {Object} [opts.eventBus] - bus to emit BAND_SELECTED on point click
     * @param {Object} [opts.events] - GelViewer/Densitometry Events constants
     * @param {HTMLElement} [opts.tooltip] - optional pre-built tooltip element
     * @returns {Object} controller — update / highlight / clearHighlight / resize / destroy
     */
    function renderInteractive(container, result, opts) {
        opts = opts || {};
        if (!container || typeof container.querySelector !== 'function') return null;
        if (typeof global.d3 === 'undefined') {
            console.warn('[QuantificationCurveRenderer] D3 not loaded — falling back to canvas');
            return null;
        }
        const d3 = global.d3;

        // Tooltip — created if the host page didn't provide one.
        let tooltip = opts.tooltip || container.parentElement?.querySelector('.dm-quantification-tooltip');
        const tooltipOwned = !tooltip;
        if (!tooltip) {
            tooltip = document.createElement('div');
            tooltip.className = 'dm-quantification-tooltip';
            container.appendChild(tooltip);
        }

        // Reuse existing SVG if present (prevents duplicates after resize).
        container.querySelectorAll('svg.dm-quantification-svg').forEach(s => s.remove());
        const svg = d3.select(container)
            .append('svg')
            .attr('class', 'dm-quantification-svg')
            .attr('width', '100%')
            .attr('height', '100%');

        // Internal state mutated by update / highlight.
        const state = {
            result,
            svg,
            tooltip,
            tooltipOwned,
            highlightedBandId: null,
            // Reference to the DOM points so highlight() doesn't re-render.
            pointSelections: { fit: null, ghost: null, control: null, sample: null },
            // Last known plot scales — used by external highlight() to pulse
            // a single point without rebuilding the chart.
            scales: { x: null, y: null },
            // Plot sizing — kept so resize can short-circuit when nothing changed.
            lastWidth: 0,
            lastHeight: 0,
        };

        function _eventName() {
            const ev = opts.events;
            if (ev && ev.BAND_SELECTED) return ev.BAND_SELECTED;
            return 'band:selected';
        }

        // Route clicks through state.selectBand() when available so the
        // selection cascades exactly like a real gel-band click: parent
        // lane gets auto-selected, state.selectedBandId updates, and the
        // BAND_SELECTED event payload includes {band, previousBandId}
        // that downstream listeners (results-table, band-zoom, band-detail,
        // gel-overview) read. The raw emit fallback exists for standalone
        // / testing use where no state is wired.
        function _selectBand(bandId) {
            if (!bandId) return;
            if (opts.state && typeof opts.state.selectBand === 'function') {
                opts.state.selectBand(bandId);
                return;
            }
            if (opts.eventBus) {
                opts.eventBus.emit(_eventName(), { bandId });
            }
        }

        function _showTooltip(html, mouseEvent) {
            if (!tooltip) return;
            tooltip.innerHTML = html;
            tooltip.classList.add('visible');
            const rect = container.getBoundingClientRect();
            const x = mouseEvent.clientX - rect.left + 12;
            const y = mouseEvent.clientY - rect.top + 12;
            tooltip.style.left = x + 'px';
            tooltip.style.top = y + 'px';
        }

        function _hideTooltip() {
            if (tooltip) tooltip.classList.remove('visible');
        }

        function _renderEmpty(message) {
            svg.selectAll('*').remove();
            const w = container.clientWidth || 400;
            const h = container.clientHeight || 300;
            svg.append('text')
                .attr('x', w / 2)
                .attr('y', h / 2)
                .attr('text-anchor', 'middle')
                .attr('fill', PANEL_COLORS.EMPTY)
                .attr('font-size', '13px')
                .text(message);
        }

        function _draw() {
            const r = state.result;
            if (!r) {
                _renderEmpty('No quantification calibration loaded.');
                return;
            }

            // Per-role y field — see _normalizePoint docstring for why
            // each role picks a different source field.
            const calibPoints = (r.calibration_points || []).map(p => _normalizePoint(p, 'load_amount'));
            const controlPoints = (r.control_points || []).map(p => _normalizePoint(p, 'predicted_amount'));
            const samplePoints = (r.sample_projections || []).map(p => _normalizePoint(p, 'estimated_amount'));

            const fitPoints = calibPoints.filter(p => !p.is_excluded && p.x != null && p.y != null);
            const ghostPoints = calibPoints.filter(p => p.is_excluded && p.x != null && p.y != null);
            const ctrls = controlPoints.filter(p => p.x != null && p.y != null);
            const samples = samplePoints.filter(p => p.x != null && p.y != null);
            const allPts = [...fitPoints, ...ghostPoints, ...ctrls, ...samples];

            const w = container.clientWidth || 400;
            const h = container.clientHeight || 300;
            state.lastWidth = w;
            state.lastHeight = h;
            svg.attr('viewBox', `0 0 ${w} ${h}`);
            svg.selectAll('*').remove();

            if (!allPts.length) {
                _renderEmpty('No data to plot — run densitometry on calibration lanes first.');
                return;
            }

            const margin = { top: 18, right: 24, bottom: 42, left: 60 };
            const plotW = Math.max(60, w - margin.left - margin.right);
            const plotH = Math.max(60, h - margin.top - margin.bottom);

            const xs = allPts.map(p => p.x);
            const xMin = d3.min(xs);
            const xMax = d3.max(xs);

            // Pre-compute the curve so its y-range contributes to scale.
            const curve = [];
            if (r.success && xMax > xMin) {
                for (let i = 0; i <= 80; i++) {
                    const x = xMin + (xMax - xMin) * (i / 80);
                    const y = evalCurve(r, x);
                    if (y !== null && Number.isFinite(y)) curve.push({ x, y });
                }
            }
            const ys = [...allPts.map(p => p.y), ...curve.map(p => p.y)].filter(Number.isFinite);
            const yMin = d3.min(ys);
            const yMax = d3.max(ys);

            const xPad = (xMax - xMin) * 0.05 || 1;
            const yPad = (yMax - yMin) * 0.05 || 1;

            const xScale = d3.scaleLinear()
                .domain([xMin - xPad, xMax + xPad])
                .range([0, plotW]);
            const yScale = d3.scaleLinear()
                .domain([yMin - yPad, yMax + yPad])
                .range([plotH, 0]);
            state.scales.x = xScale;
            state.scales.y = yScale;

            const root = svg.append('g')
                .attr('transform', `translate(${margin.left},${margin.top})`);

            // Grid + axes — match the chromatogram's subdued style.
            const xAxis = d3.axisBottom(xScale).ticks(5).tickSizeOuter(0);
            const yAxis = d3.axisLeft(yScale).ticks(5).tickSizeOuter(0);

            const gridX = root.append('g')
                .attr('class', 'dm-qcurve-grid')
                .attr('transform', `translate(0,${plotH})`)
                .call(d3.axisBottom(xScale).ticks(5).tickSize(-plotH).tickFormat(''));
            gridX.selectAll('line').attr('stroke', PANEL_COLORS.GRID);
            gridX.selectAll('path').remove();

            const gridY = root.append('g')
                .attr('class', 'dm-qcurve-grid')
                .call(d3.axisLeft(yScale).ticks(5).tickSize(-plotW).tickFormat(''));
            gridY.selectAll('line').attr('stroke', PANEL_COLORS.GRID);
            gridY.selectAll('path').remove();

            const xg = root.append('g')
                .attr('transform', `translate(0,${plotH})`)
                .call(xAxis);
            xg.selectAll('line, path').attr('stroke', PANEL_COLORS.AXIS_LINE);
            xg.selectAll('text').attr('fill', PANEL_COLORS.TEXT_MUTED).attr('font-size', '11px');

            const yg = root.append('g').call(yAxis);
            yg.selectAll('line, path').attr('stroke', PANEL_COLORS.AXIS_LINE);
            yg.selectAll('text').attr('fill', PANEL_COLORS.TEXT_MUTED).attr('font-size', '11px');

            // Axis labels.
            root.append('text')
                .attr('x', plotW / 2)
                .attr('y', plotH + 32)
                .attr('text-anchor', 'middle')
                .attr('fill', PANEL_COLORS.TEXT)
                .attr('font-size', '12px')
                .text('Corrected area');

            root.append('text')
                .attr('transform', `translate(-44,${plotH / 2}) rotate(-90)`)
                .attr('text-anchor', 'middle')
                .attr('fill', PANEL_COLORS.TEXT)
                .attr('font-size', '12px')
                .text(`Amount (${r.unit === 'UG_ML' ? 'µg/mL' : 'µg'})`);

            // Equation + R² in the top-left, only if we have a successful fit.
            if (r.success && (r.equation || typeof r.r_squared === 'number')) {
                const meta = root.append('g').attr('transform', `translate(8, 6)`);
                if (r.equation) {
                    meta.append('text')
                        .attr('fill', PANEL_COLORS.TEXT)
                        .attr('font-size', '11px')
                        .attr('font-family', 'monospace')
                        .text(r.equation);
                }
                if (typeof r.r_squared === 'number') {
                    meta.append('text')
                        .attr('y', 14)
                        .attr('fill', PANEL_COLORS.TEXT_MUTED)
                        .attr('font-size', '11px')
                        .text(`R² = ${r.r_squared.toFixed(4)}`);
                }
            }

            // The fit curve.
            if (curve.length > 1) {
                const lineGen = d3.line()
                    .x(d => xScale(d.x))
                    .y(d => yScale(d.y))
                    .curve(d3.curveMonotoneX);
                root.append('path')
                    .datum(curve)
                    .attr('class', 'dm-qcurve-fit')
                    .attr('fill', 'none')
                    .attr('stroke', PANEL_COLORS.CURVE)
                    .attr('stroke-width', 2)
                    .attr('d', lineGen);
            }

            // Points groups (drawn in this order so samples render on top
            // of the fit line, controls on top of samples for visibility).
            const pointsLayer = root.append('g').attr('class', 'dm-qcurve-points');

            // Excluded calibration ghosts.
            state.pointSelections.ghost = pointsLayer.selectAll('.dm-qcurve-ghost')
                .data(ghostPoints, d => d.band_id || `ghost-${d.x}-${d.y}`)
                .enter()
                .append('circle')
                .attr('class', 'dm-qcurve-point dm-qcurve-ghost')
                .attr('cx', d => xScale(d.x))
                .attr('cy', d => yScale(d.y))
                .attr('r', 5)
                .attr('fill', PANEL_COLORS.EXCLUDED)
                .attr('stroke', PANEL_COLORS.FIT)
                .attr('stroke-dasharray', '2,2')
                .attr('cursor', 'pointer')
                .on('mousemove', (event, d) => {
                    _showTooltip(`
                        <div class="dm-quantification-tooltip-label">Calibration (excluded)</div>
                        <div class="dm-quantification-tooltip-row">Lane ${d.lane_number ?? '—'}</div>
                        <div class="dm-quantification-tooltip-row">Area: ${d.x.toFixed(1)}</div>
                        <div class="dm-quantification-tooltip-row">Load: ${d.y.toFixed(2)} ${r.unit === 'UG_ML' ? 'µg/mL' : 'µg'}</div>
                    `, event);
                })
                .on('mouseleave', _hideTooltip)
                .on('click', (event, d) => _selectBand(d.band_id));

            // Active calibration points.
            state.pointSelections.fit = pointsLayer.selectAll('.dm-qcurve-fit-point')
                .data(fitPoints, d => d.band_id || `fit-${d.x}-${d.y}`)
                .enter()
                .append('circle')
                .attr('class', 'dm-qcurve-point dm-qcurve-fit-point')
                .attr('cx', d => xScale(d.x))
                .attr('cy', d => yScale(d.y))
                .attr('r', 5.5)
                .attr('fill', PANEL_COLORS.FIT)
                .attr('stroke', '#1e1b4b')
                .attr('stroke-width', 1)
                .attr('cursor', 'pointer')
                .on('mousemove', (event, d) => {
                    _showTooltip(`
                        <div class="dm-quantification-tooltip-label">Calibration point</div>
                        <div class="dm-quantification-tooltip-row">Lane ${d.lane_number ?? '—'}</div>
                        <div class="dm-quantification-tooltip-row">Area: ${d.x.toFixed(1)}</div>
                        <div class="dm-quantification-tooltip-row">Load: ${d.y.toFixed(2)} ${r.unit === 'UG_ML' ? 'µg/mL' : 'µg'}</div>
                    `, event);
                })
                .on('mouseleave', _hideTooltip)
                .on('click', (event, d) => _selectBand(d.band_id));

            // Control diamonds.
            state.pointSelections.control = pointsLayer.selectAll('.dm-qcurve-control')
                .data(ctrls, d => d.band_id || `ctrl-${d.x}-${d.y}`)
                .enter()
                .append('path')
                .attr('class', 'dm-qcurve-point dm-qcurve-control')
                .attr('d', d3.symbol().type(d3.symbolDiamond).size(80))
                .attr('transform', d => `translate(${xScale(d.x)},${yScale(d.y)})`)
                .attr('fill', PANEL_COLORS.CONTROL)
                .attr('stroke', d => d.out_of_spec ? '#ef4444' : '#0e7490')
                .attr('stroke-width', d => d.out_of_spec ? 2 : 1)
                .attr('cursor', 'pointer')
                .on('mousemove', (event, d) => {
                    _showTooltip(`
                        <div class="dm-quantification-tooltip-label">Control · Lane ${d.lane_number ?? '—'}</div>
                        <div class="dm-quantification-tooltip-row">Area: ${d.x.toFixed(1)}</div>
                        <div class="dm-quantification-tooltip-row">Predicted: ${d.y.toFixed(2)} ${r.unit === 'UG_ML' ? 'µg/mL' : 'µg'}</div>
                        ${d.recovery_pct != null ? `<div class="dm-quantification-tooltip-row">Recovery: ${d.recovery_pct.toFixed(1)}%${d.out_of_spec ? ' ⚠ OOS' : ''}</div>` : ''}
                    `, event);
                })
                .on('mouseleave', _hideTooltip)
                .on('click', (event, d) => _selectBand(d.band_id));

            // Sample crosses (POI band projections).
            const sampleSize = 9;
            const sampleGroup = pointsLayer.selectAll('.dm-qcurve-sample-group')
                .data(samples, d => d.band_id || `samp-${d.x}-${d.y}`)
                .enter()
                .append('g')
                .attr('class', 'dm-qcurve-point dm-qcurve-sample-group')
                .attr('transform', d => `translate(${xScale(d.x)},${yScale(d.y)})`)
                .attr('cursor', 'pointer')
                .style('color', PANEL_COLORS.SAMPLE)
                .on('mousemove', (event, d) => {
                    _showTooltip(`
                        <div class="dm-quantification-tooltip-label">Sample · Lane ${d.lane_number ?? '—'}</div>
                        ${d.sample_label ? `<div class="dm-quantification-tooltip-row">${d.sample_label}</div>` : ''}
                        <div class="dm-quantification-tooltip-row">Area: ${d.x.toFixed(1)}</div>
                        <div class="dm-quantification-tooltip-row">Predicted: ${d.y.toFixed(2)} ${r.unit === 'UG_ML' ? 'µg/mL' : 'µg'}</div>
                    `, event);
                })
                .on('mouseleave', _hideTooltip)
                .on('click', (event, d) => _selectBand(d.band_id));
            // Cross-shaped marker drawn as two lines so we can scale the
            // group when highlighting without redrawing.
            sampleGroup.append('line')
                .attr('x1', -sampleSize / 2).attr('y1', -sampleSize / 2)
                .attr('x2', sampleSize / 2).attr('y2', sampleSize / 2)
                .attr('stroke', PANEL_COLORS.SAMPLE)
                .attr('stroke-width', 2)
                .attr('stroke-linecap', 'round');
            sampleGroup.append('line')
                .attr('x1', -sampleSize / 2).attr('y1', sampleSize / 2)
                .attr('x2', sampleSize / 2).attr('y2', -sampleSize / 2)
                .attr('stroke', PANEL_COLORS.SAMPLE)
                .attr('stroke-width', 2)
                .attr('stroke-linecap', 'round');
            state.pointSelections.sample = sampleGroup;

            // Legend — same order as the modal.
            const legend = root.append('g')
                .attr('class', 'dm-qcurve-legend')
                .attr('transform', `translate(${plotW - 110}, 6)`);
            const legendRows = [
                { color: PANEL_COLORS.FIT, label: 'Calibration', shape: 'circle' },
                { color: PANEL_COLORS.EXCLUDED, label: 'Excluded', shape: 'circle-ghost' },
                { color: PANEL_COLORS.CONTROL, label: 'Controls', shape: 'diamond' },
                { color: PANEL_COLORS.SAMPLE, label: 'Samples', shape: 'cross' },
            ];
            legendRows.forEach((row, i) => {
                const ly = i * 16 + 4;
                if (row.shape === 'circle') {
                    legend.append('circle')
                        .attr('cx', 0).attr('cy', ly).attr('r', 5).attr('fill', row.color);
                } else if (row.shape === 'circle-ghost') {
                    legend.append('circle')
                        .attr('cx', 0).attr('cy', ly).attr('r', 5)
                        .attr('fill', row.color)
                        .attr('stroke', PANEL_COLORS.FIT)
                        .attr('stroke-dasharray', '2,2');
                } else if (row.shape === 'diamond') {
                    legend.append('path')
                        .attr('d', d3.symbol().type(d3.symbolDiamond).size(70))
                        .attr('transform', `translate(0, ${ly})`)
                        .attr('fill', row.color);
                } else if (row.shape === 'cross') {
                    legend.append('line')
                        .attr('x1', -4).attr('y1', ly - 4).attr('x2', 4).attr('y2', ly + 4)
                        .attr('stroke', row.color).attr('stroke-width', 2);
                    legend.append('line')
                        .attr('x1', -4).attr('y1', ly + 4).attr('x2', 4).attr('y2', ly - 4)
                        .attr('stroke', row.color).attr('stroke-width', 2);
                }
                legend.append('text')
                    .attr('x', 12).attr('y', ly + 4)
                    .attr('fill', PANEL_COLORS.TEXT_MUTED)
                    .attr('font-size', '11px')
                    .text(row.label);
            });

            // Re-apply any pending external highlight after the rebuild.
            if (state.highlightedBandId) {
                _applyHighlight(state.highlightedBandId);
            }
        }

        function _applyHighlight(bandId) {
            // Lift every point back to its base look first.
            const sels = state.pointSelections;
            ['fit', 'ghost', 'control'].forEach(k => {
                if (!sels[k]) return;
                sels[k].classed('is-highlighted', false)
                    .attr('r', function (d, i, nodes) {
                        // restore radius for circles only
                        return nodes[i].tagName === 'circle' ? (k === 'fit' ? 5.5 : 5) : null;
                    });
            });
            if (sels.sample) sels.sample.classed('is-highlighted', false)
                .attr('transform', d => `translate(${state.scales.x(d.x)},${state.scales.y(d.y)})`);

            if (!bandId) return;

            // Match by band_id across all four point sets.
            const matchSelector = (sel, scaleFn) => {
                if (!sel) return;
                sel.each(function (d) {
                    if (d && d.band_id === bandId) {
                        const node = d3.select(this);
                        node.classed('is-highlighted', true);
                        if (this.tagName === 'circle') {
                            node.attr('r', +node.attr('r') * 1.6);
                        } else if (this.tagName === 'g') {
                            // Sample cross — scale up via transform on the group.
                            node.attr('transform', `translate(${state.scales.x(d.x)},${state.scales.y(d.y)}) scale(1.6)`);
                        } else if (this.tagName === 'path') {
                            // Control diamond.
                            node.attr('transform', `translate(${state.scales.x(d.x)},${state.scales.y(d.y)}) scale(1.5)`);
                        }
                    }
                });
            };
            matchSelector(sels.fit);
            matchSelector(sels.ghost);
            matchSelector(sels.control);
            matchSelector(sels.sample);
        }

        // Initial draw.
        _draw();

        return {
            update(newResult) {
                state.result = newResult;
                _draw();
            },
            highlight(bandId) {
                state.highlightedBandId = bandId || null;
                _applyHighlight(state.highlightedBandId);
            },
            clearHighlight() {
                state.highlightedBandId = null;
                _applyHighlight(null);
            },
            resize() {
                // Only redraw if container size actually changed — avoids
                // expensive rebuilds during continuous resize observers.
                const w = container.clientWidth || 0;
                const h = container.clientHeight || 0;
                if (w === state.lastWidth && h === state.lastHeight) return;
                _draw();
            },
            destroy() {
                svg.remove();
                if (tooltipOwned && tooltip && tooltip.parentNode) {
                    tooltip.parentNode.removeChild(tooltip);
                }
            },
        };
    }

    global.Densitometry = global.Densitometry || {};
    global.Densitometry.QuantificationCurveRenderer = { render, evalCurve, renderInteractive };
    // Top-level alias for parity with the modal class export.
    global.QuantificationCurveRenderer = global.Densitometry.QuantificationCurveRenderer;
})(window);
