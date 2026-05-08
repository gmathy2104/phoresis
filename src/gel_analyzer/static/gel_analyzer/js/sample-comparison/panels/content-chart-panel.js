/**
 * Content Chart Panel — Estimated POI content across compared samples.
 *
 * Mirrors the POI Purity panel's grouped-bar shape: one outer scaleBand
 * per sample, one inner scaleBand per POI band inside the group. The Y
 * axis is the estimated amount (µg or µg/mL depending on the active
 * calibration of the source analysis). Renders only the bands whose
 * server-side densitometry record has an estimated_amount — the host
 * page should hide this view button when no compared sample has any
 * quantified band.
 *
 * Click on a bar → state.selectBand(bandId) so the cascade matches a
 * real gel-band click: parent sample auto-selected, then band detail /
 * results-table / chromatogram / POI-purity all sync.
 */

(function (global) {
    'use strict';

    const ComparisonEvents = global.SampleComparison?.Events;

    class ComparisonContentChartPanel {
        constructor(options) {
            this.container = options.container;
            this.eventBus = options.eventBus;
            this.state = options.state;

            this.margin = { top: 30, right: 40, bottom: 60, left: 70 };
            this.width = 0;
            this.height = 0;

            this.svg = null;
            this.chartGroup = null;
            this.xScale = null;
            this.yScale = null;

            this._init();
        }

        _init() {
            if (!this.container) return;
            this._setupEvents();
            this._setupResizeObserver();
        }

        // =====================================================================
        // Public — call from the host page when this view is activated to
        // force a redraw against a freshly-visible container.
        // =====================================================================

        render() {
            this._render();
        }

        /**
         * Whether this panel has anything to draw — the host page uses
         * this to decide if the "Content" view button should appear.
         */
        hasData() {
            const data = this._getChartData();
            return data.some(d => d.bars && d.bars.length > 0);
        }

        // =====================================================================
        // Data Extraction
        // =====================================================================

        _getChartData() {
            const samples = this.state.getSamples();
            if (!samples || samples.length === 0) return [];

            return samples.map(sample => {
                const allBands = sample.bands || [];
                const calib = sample.analysis?.active_quant_calibration || null;
                const calibUnit = calib && calib.unit;

                const poiBands = allBands
                    .filter(b => b.band_type === 'POI'
                        && b.densitometry
                        && b.densitometry.estimated_amount != null)
                    .sort((a, b) => (a.band_number || 0) - (b.band_number || 0));

                const bars = poiBands.map((b, idx) => {
                    const d = b.densitometry || {};
                    return {
                        bandId: b.id,
                        bandNumber: b.band_number,
                        bandKey: `b${b.band_number || idx}`,
                        mw: b.estimated_mw_kda,
                        amount: d.estimated_amount,
                        unit: this._formatUnit(d.estimated_amount_unit || calibUnit),
                    };
                });

                return {
                    sampleId: sample.sampleId,
                    label: sample.label || `Sample ${sample.sampleId}`,
                    color: sample.color || '#2196F3',
                    gelName: sample.analysis?.name || sample.gel_name || '',
                    poiCount: poiBands.length,
                    bars,
                };
            });
        }

        _formatUnit(unit) {
            if (unit === 'UG_ML' || unit === 'µg/mL') return 'µg/mL';
            return 'µg';
        }

        // =====================================================================
        // Rendering
        // =====================================================================

        _render() {
            if (!this.container) return;

            const data = this._getChartData();

            this.container.innerHTML = '';

            const rect = this.container.getBoundingClientRect();
            this.width = rect.width - this.margin.left - this.margin.right;
            this.height = rect.height - this.margin.top - this.margin.bottom;

            if (this.width <= 0 || this.height <= 0) {
                this.width = 400;
                this.height = 250;
            }

            if (data.length === 0 || !data.some(d => d.bars && d.bars.length > 0)) {
                this._showEmptyState(data.length === 0
                    ? 'Add samples to view estimated content'
                    : 'No quantified POIs across the loaded samples — apply a calibration in the source analysis to fill this in.');
                return;
            }

            // Pick a single Y unit to label the axis. If samples disagree
            // (e.g. one in µg and one in µg/mL), fall back to "amount" and
            // let the per-bar tooltip carry the actual unit. In practice
            // a user's compared analyses will share the same calibration
            // unit, so this is mostly a defensive label.
            const allUnits = new Set();
            data.forEach(d => d.bars.forEach(b => allUnits.add(b.unit)));
            const unitLabel = allUnits.size === 1 ? Array.from(allUnits)[0] : 'amount';

            // Y domain: 0 → max amount + 10% headroom.
            const allAmounts = data.flatMap(d => d.bars.map(b => b.amount)).filter(v => v != null && isFinite(v));
            const yMax = allAmounts.length > 0 ? Math.max(...allAmounts) * 1.1 : 1;

            this.svg = d3.select(this.container)
                .append('svg')
                .attr('width', this.width + this.margin.left + this.margin.right)
                .attr('height', this.height + this.margin.top + this.margin.bottom)
                .attr('class', 'cmp-content-chart-svg');

            this.chartGroup = this.svg.append('g')
                .attr('transform', `translate(${this.margin.left},${this.margin.top})`);

            this.xScale = d3.scaleBand()
                .domain(data.map(d => d.sampleId))
                .range([0, this.width])
                .padding(0.3);

            this.yScale = d3.scaleLinear()
                .domain([0, yMax])
                .range([this.height, 0]);

            this._renderGrid();
            this._renderAxes(data, unitLabel);
            this._renderBars(data);

            this._highlightSelection(this.state.selectedSampleId, this.state.selectedBandId);
        }

        _renderGrid() {
            const ticks = this.yScale.ticks(5);
            this.chartGroup.selectAll('.cmp-content-grid-line')
                .data(ticks)
                .enter()
                .append('line')
                .attr('class', 'cmp-content-grid-line')
                .attr('x1', 0)
                .attr('x2', this.width)
                .attr('y1', d => this.yScale(d))
                .attr('y2', d => this.yScale(d))
                .attr('stroke', 'rgba(255,255,255,0.08)')
                .attr('stroke-width', 1);
        }

        _renderAxes(data, unitLabel) {
            const xAxis = this.chartGroup.append('g')
                .attr('class', 'x-axis')
                .attr('transform', `translate(0,${this.height})`)
                .call(d3.axisBottom(this.xScale)
                    .tickFormat((id) => {
                        const item = data.find(d => d.sampleId === id);
                        return item ? item.label : id;
                    })
                );

            xAxis.selectAll('text')
                .attr('fill', 'rgba(255,255,255,0.7)')
                .attr('font-family', 'Roboto, sans-serif')
                .attr('font-size', '11px')
                .each(function () {
                    const text = d3.select(this);
                    if (text.text().length > 12) {
                        text.attr('transform', 'rotate(-25)')
                            .attr('text-anchor', 'end')
                            .attr('dx', '-0.5em')
                            .attr('dy', '0.5em');
                    }
                });

            xAxis.selectAll('.domain, .tick line')
                .attr('stroke', 'rgba(255,255,255,0.3)');

            const yAxis = this.chartGroup.append('g')
                .attr('class', 'y-axis')
                .call(d3.axisLeft(this.yScale).ticks(5));

            yAxis.selectAll('text')
                .attr('fill', 'rgba(255,255,255,0.7)')
                .attr('font-family', 'Roboto, sans-serif')
                .attr('font-size', '10px');

            yAxis.selectAll('.domain, .tick line')
                .attr('stroke', 'rgba(255,255,255,0.3)');

            this.chartGroup.append('text')
                .attr('transform', 'rotate(-90)')
                .attr('x', -this.height / 2)
                .attr('y', -55)
                .attr('text-anchor', 'middle')
                .attr('fill', 'rgba(255,255,255,0.7)')
                .attr('font-size', '12px')
                .attr('font-family', 'Roboto, sans-serif')
                .text(`Estimated content (${unitLabel})`);
        }

        _renderBars(data) {
            const self = this;
            const groupWidth = this.xScale.bandwidth();
            const barRadius = 4;

            data.forEach((d, i) => {
                const groupX = this.xScale(d.sampleId);
                const sampleGroup = this.chartGroup.append('g')
                    .attr('class', 'cmp-content-bar-group')
                    .attr('data-sample-id', d.sampleId);

                if (!d.bars || d.bars.length === 0) {
                    // No quantified POI on this sample → dashed N/A placeholder.
                    sampleGroup.append('rect')
                        .attr('class', 'cmp-content-bar cmp-content-bar-nodata')
                        .attr('x', groupX)
                        .attr('y', this.height * 0.7)
                        .attr('width', groupWidth)
                        .attr('height', this.height * 0.3)
                        .attr('rx', barRadius)
                        .attr('fill', 'none')
                        .attr('stroke', 'rgba(255,255,255,0.2)')
                        .attr('stroke-width', 1.5)
                        .attr('stroke-dasharray', '4,3');

                    sampleGroup.append('text')
                        .attr('x', groupX + groupWidth / 2)
                        .attr('y', this.height * 0.85)
                        .attr('text-anchor', 'middle')
                        .attr('dominant-baseline', 'middle')
                        .attr('fill', 'rgba(255,255,255,0.4)')
                        .attr('font-size', '11px')
                        .text('N/A');
                    return;
                }

                const xInner = d3.scaleBand()
                    .domain(d.bars.map(b => b.bandKey))
                    .range([0, groupWidth])
                    .padding(0.12);

                d.bars.forEach((bar, j) => {
                    const bx = groupX + xInner(bar.bandKey);
                    const bw = xInner.bandwidth();
                    const by = this.yScale(bar.amount);
                    const bh = this.height - by;
                    const r = Math.min(barRadius, bw / 2, bh);

                    const initialPath = self._roundedTopRect(bx, this.height, bw, 0, Math.min(barRadius, bw / 2));
                    const targetPath = self._roundedTopRect(bx, by, bw, bh, r);

                    const cell = sampleGroup.append('g')
                        .attr('class', 'cmp-content-bar-cell')
                        .attr('data-band-id', bar.bandId)
                        .attr('data-sample-id', d.sampleId)
                        .style('cursor', 'pointer');

                    cell.append('path')
                        .attr('class', 'cmp-content-bar')
                        .attr('d', initialPath)
                        .attr('fill', d.color)
                        .attr('opacity', 0.85)
                        .transition()
                        .duration(400)
                        .delay(i * 60 + j * 30)
                        .ease(d3.easeCubicOut)
                        .attr('d', targetPath);

                    if (bw >= 32) {
                        cell.append('text')
                            .attr('class', 'cmp-content-value-label')
                            .attr('x', bx + bw / 2)
                            .attr('y', this.height)
                            .attr('text-anchor', 'middle')
                            .attr('fill', '#fff')
                            .attr('font-family', "'Roboto Mono', monospace")
                            .attr('font-size', bw < 48 ? '10px' : '12px')
                            .attr('font-weight', '600')
                            .text(bar.amount.toFixed(bar.amount < 1 ? 2 : 1))
                            .transition()
                            .duration(400)
                            .delay(i * 60 + j * 30)
                            .ease(d3.easeCubicOut)
                            .attr('y', by - 6);
                    }

                    cell
                        .on('mouseenter', function (event) {
                            d3.select(this).select('.cmp-content-bar').attr('filter', 'brightness(1.2)');
                            self._showTooltip(event, d, bar);
                        })
                        .on('mousemove', function (event) {
                            self._moveTooltip(event);
                        })
                        .on('mouseleave', function () {
                            d3.select(this).select('.cmp-content-bar').attr('filter', null);
                            self._hideTooltip();
                        })
                        .on('click', function () {
                            if (bar.bandId && self.state.selectBand) {
                                self.state.selectBand(bar.bandId);
                            } else {
                                self.state.selectSample(d.sampleId);
                            }
                        });
                });
            });
        }

        _roundedTopRect(x, y, width, height, radius) {
            if (height <= 0) {
                return `M${x},${y} h${width} v0 h${-width} Z`;
            }
            const r = Math.min(radius, height / 2, width / 2);
            return `M${x},${y + height}` +
                `v${-(height - r)}` +
                `a${r},${r} 0 0 1 ${r},${-r}` +
                `h${width - 2 * r}` +
                `a${r},${r} 0 0 1 ${r},${r}` +
                `v${height - r}` +
                `Z`;
        }

        // =====================================================================
        // Tooltip
        // =====================================================================

        _showTooltip(event, d, bar) {
            const tooltip = this._getTooltip();
            let html = `<strong style="color:${d.color}">${d.label}</strong><br>`;
            html += `POI B${bar.bandNumber || '?'}`;
            if (bar.mw != null) html += ` &middot; ${Math.round(bar.mw)} kDa`;
            html += `<br>Content: <strong>${bar.amount.toFixed(2)} ${bar.unit}</strong>`;
            if (d.gelName) html += `<br>Source: ${d.gelName}`;
            tooltip.innerHTML = html;
            tooltip.style.left = `${event.pageX + 15}px`;
            tooltip.style.top = `${event.pageY - 10}px`;
            tooltip.style.display = 'block';
        }

        _moveTooltip(event) {
            const tooltip = this._getTooltip();
            tooltip.style.left = `${event.pageX + 15}px`;
            tooltip.style.top = `${event.pageY - 10}px`;
        }

        _hideTooltip() {
            const tooltip = this._getTooltip();
            tooltip.style.display = 'none';
        }

        _getTooltip() {
            let tooltip = document.getElementById('dm-chart-tooltip');
            if (!tooltip) {
                tooltip = document.createElement('div');
                tooltip.id = 'dm-chart-tooltip';
                tooltip.className = 'dm-tooltip';
                document.body.appendChild(tooltip);
            }
            return tooltip;
        }

        // =====================================================================
        // Selection Highlighting
        // =====================================================================

        _highlightSelection(sampleId, bandId) {
            if (!this.chartGroup) return;

            this.chartGroup.selectAll('.cmp-content-bar-group')
                .attr('opacity', function () {
                    const id = d3.select(this).attr('data-sample-id');
                    if (!sampleId) return 1;
                    return id === sampleId ? 1 : 0.4;
                });

            this.chartGroup.selectAll('.cmp-content-bar-cell .cmp-content-bar')
                .attr('stroke', null)
                .attr('stroke-width', null);
            if (bandId) {
                this.chartGroup
                    .selectAll(`.cmp-content-bar-cell[data-band-id="${bandId}"] .cmp-content-bar`)
                    .attr('stroke', '#fff')
                    .attr('stroke-width', 1.5);
            }
        }

        // =====================================================================
        // Empty State
        // =====================================================================

        _showEmptyState(message) {
            this.container.innerHTML = '';
            const wrapper = document.createElement('div');
            wrapper.className = 'dm-poi-placeholder';
            wrapper.innerHTML = `
                <i class="bi bi-currency-exchange" style="font-size: 2rem; opacity: 0.3; margin-bottom: 8px;"></i>
                <span style="color: rgba(255,255,255,0.5); font-size: 0.85rem;">${message}</span>
            `;
            this.container.appendChild(wrapper);
        }

        // =====================================================================
        // Events + Resize
        // =====================================================================

        _setupEvents() {
            this.eventBus.on(ComparisonEvents.DATA_LOADED, () => this._renderAndRefreshButton());
            this.eventBus.on(ComparisonEvents.SAMPLE_ADDED, () => this._renderAndRefreshButton());
            this.eventBus.on(ComparisonEvents.SAMPLE_REMOVED, () => this._renderAndRefreshButton());
            this.eventBus.on(ComparisonEvents.SAMPLE_ORDER_CHANGED, () => this._render());
            this.eventBus.on(ComparisonEvents.SAMPLE_SELECTED, (data) => {
                this._highlightSelection(data && data.sampleId, this.state.selectedBandId);
            });
            this.eventBus.on(ComparisonEvents.BAND_SELECTED, (data) => {
                this._highlightSelection(this.state.selectedSampleId, data && data.bandId);
            });
        }

        _renderAndRefreshButton() {
            this._render();
            // Notify host page so the view-toggle button can show/hide.
            this.eventBus.emit('content-chart:availability', { available: this.hasData() });
        }

        _setupResizeObserver() {
            if (!this.container) return;
            this._resizeObserver = new ResizeObserver(() => {
                if (this._resizeTimeout) cancelAnimationFrame(this._resizeTimeout);
                this._resizeTimeout = requestAnimationFrame(() => this._handleResize());
            });
            this._resizeObserver.observe(this.container);
        }

        _handleResize() {
            const rect = this.container.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) return;
            if (this.container.offsetParent === null) return;
            const newWidth = rect.width - this.margin.left - this.margin.right;
            const newHeight = rect.height - this.margin.top - this.margin.bottom;
            if (Math.abs(newWidth - this.width) < 5 && Math.abs(newHeight - this.height) < 5) {
                return;
            }
            this._render();
        }

        destroy() {
            if (this._resizeObserver) {
                this._resizeObserver.disconnect();
                this._resizeObserver = null;
            }
            if (this._resizeTimeout) {
                cancelAnimationFrame(this._resizeTimeout);
                this._resizeTimeout = null;
            }
        }
    }

    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.Panels = global.SampleComparison.Panels || {};
    global.SampleComparison.Panels.ContentChart = ComparisonContentChartPanel;

})(window);
