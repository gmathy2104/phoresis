/**
 * Readout Panel (the comparison's readout tab; was "POI Purity" for every gel)
 *
 * The tab reads the lanes for their KIND's readout (options.readout; the comparison page mounts one kind at a
 * time -- services/comparison_items.py, owner 2026-10-12):
 *   - PURITY: D3 bars of the purity the gel pages publish (sample.readout.purity, the server's published
 *     rule), with the gel pages' two thresholds (options.purityThresholds = analysis_detail.PURITY_GOOD /
 *     PURITY_FAIR); a lane with no value names its reason, never "N/A" or a zero.
 *   - MOLECULE_VARIANTS / HOST_CELL_PROTEINS: the densitometry page's charts (js/shared/readout-charts.js)
 *     over the lanes' readout values; an a.u. signal is drawn only when every lane comes from one blot.
 * Without a readout (the dev showcase), the raw POI share of the lane as before.
 */

(function(global) {
    'use strict';

    const ComparisonEvents = global.SampleComparison?.Events;

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    class ComparisonPoiPurityPanel extends GelAnalyzer.Viz.Panel {
        constructor(options) {
            super(options);  // sets this.container/eventBus/state/options/tooltipLayer/_disposers

            this.margin = { top: 30, right: 30, bottom: 60, left: 60 };
            this.width = 0;
            this.height = 0;

            // D3 elements
            this.svg = null;
            this.chartGroup = null;
            this.xScale = null;
            this.yScale = null;

            // Thresholds: the gel pages' (analysis_detail.PURITY_GOOD / PURITY_FAIR), else the historic 90 / 70.
            const t = (this.options && this.options.purityThresholds) || {};
            this.thresholds = [
                { value: t.good ?? 90, label: 'Target', color: '#22c55e' },
                { value: t.fair ?? 70, label: 'Minimum', color: '#ffc107' },
            ];
            this.readout = (this.options && this.options.readout) || null;
        }

        init() {
            if (!this.container) return;
            this._setupEvents();
            this._setupResizeObserver();
        }

        // =====================================================================
        // Data Extraction
        // =====================================================================

        _getChartData() {
            const samples = this.state.getSamples();
            if (!samples || samples.length === 0) return [];

            return samples.map(sample => {
                // The server's published purity when the page sent the lane's readout; else the raw POI share.
                const readout = sample.readout || null;
                const poiPurity = readout ? (readout.purity ?? null) : (sample.densitometry?.poi_percentage ?? null);
                const totalBands = sample.bands?.length || 0;
                const poiBands = sample.bands?.filter(b => b.band_type === 'POI').length || 0;
                const reason = readout
                    ? (readout.carries === false ? '—' : (readout.reason || '—'))
                    : 'N/A';

                return {
                    sampleId: sample.sampleId,
                    label: sample.label || `Sample ${sample.sampleId}`,
                    color: sample.color || '#2196F3',
                    poiPurity: poiPurity,
                    reason: reason,
                    gelName: sample.analysis?.name || sample.gel_name || '',
                    totalBands: totalBands,
                    poiBands: poiBands,
                };
            });
        }

        // =====================================================================
        // Rendering
        // =====================================================================

        _render() {
            if (!this.container) return;

            if (this.readout === 'MOLECULE_VARIANTS' || this.readout === 'HOST_CELL_PROTEINS') {
                this._renderWestern();
                return;
            }

            const data = this._getChartData();

            // Clear previous content
            this.container.innerHTML = '';

            const rect = this.container.getBoundingClientRect();
            this.width = rect.width - this.margin.left - this.margin.right;
            this.height = rect.height - this.margin.top - this.margin.bottom;

            if (this.width <= 0 || this.height <= 0) {
                this.width = 400;
                this.height = 250;
            }

            // Empty state
            if (data.length === 0 || !data.some(d => d.poiPurity !== null)) {
                this._showEmptyState(data.length === 0
                    ? 'Add samples to view POI purity'
                    : 'No purity value for these lanes: ' + data.map(d => `${d.label} (${d.reason})`).join(', '));
                return;
            }

            // Create SVG
            this.svg = d3.select(this.container)
                .append('svg')
                .attr('width', this.width + this.margin.left + this.margin.right)
                .attr('height', this.height + this.margin.top + this.margin.bottom)
                .attr('class', 'dm-poi-purity-svg');

            this.chartGroup = this.svg.append('g')
                .attr('transform', `translate(${this.margin.left},${this.margin.top})`);

            // Scales
            this.xScale = d3.scaleBand()
                .domain(data.map(d => d.sampleId))
                .range([0, this.width])
                .padding(0.3);

            this.yScale = d3.scaleLinear()
                .domain([0, 100])
                .range([this.height, 0]);

            // Grid lines
            this._renderGrid();

            // Axes
            this._renderAxes(data);

            // Threshold lines
            this._renderThresholds();

            // Bars
            this._renderBars(data);

            // Apply selection if any
            if (this.state.selectedSampleId) {
                this._highlightSelectedSample(this.state.selectedSampleId);
            }
        }

        _renderGrid() {
            const gridValues = [20, 40, 60, 80, 100];

            this.chartGroup.selectAll('.dm-poi-grid-line')
                .data(gridValues)
                .enter()
                .append('line')
                .attr('class', 'dm-poi-grid-line')
                .attr('x1', 0)
                .attr('x2', this.width)
                .attr('y1', d => this.yScale(d))
                .attr('y2', d => this.yScale(d))
                .style('stroke', 'var(--dm-line-8)')
                .attr('stroke-width', 1);
        }

        _renderAxes(data) {
            // X axis
            const xAxis = this.chartGroup.append('g')
                .attr('class', 'x-axis')
                .attr('transform', `translate(0,${this.height})`)
                .call(d3.axisBottom(this.xScale)
                    .tickFormat((id) => {
                        const item = data.find(d => d.sampleId === id);
                        return item ? item.label : id;
                    })
                );

            // Rotate labels if needed
            xAxis.selectAll('text')
                .style('fill', 'var(--dm-fg-70)')
                .attr('font-family', 'Roboto, sans-serif')
                .attr('font-size', '11px')
                .each(function() {
                    const text = d3.select(this);
                    if (text.text().length > 12) {
                        text.attr('transform', 'rotate(-25)')
                            .attr('text-anchor', 'end')
                            .attr('dx', '-0.5em')
                            .attr('dy', '0.5em');
                    }
                });

            xAxis.selectAll('.domain, .tick line')
                .style('stroke', 'var(--dm-line-30)');

            // Y axis
            const yAxis = this.chartGroup.append('g')
                .attr('class', 'y-axis')
                .call(d3.axisLeft(this.yScale)
                    .ticks(5)
                    .tickFormat(d => `${d}%`)
                );

            yAxis.selectAll('text')
                .style('fill', 'var(--dm-fg-70)')
                .attr('font-family', 'Roboto, sans-serif')
                .attr('font-size', '10px');

            yAxis.selectAll('.domain, .tick line')
                .style('stroke', 'var(--dm-line-30)');

            // Y axis label
            this.chartGroup.append('text')
                .attr('transform', 'rotate(-90)')
                .attr('x', -this.height / 2)
                .attr('y', -45)
                .attr('text-anchor', 'middle')
                .style('fill', 'var(--dm-fg-70)')
                .attr('font-size', '12px')
                .attr('font-family', 'Roboto, sans-serif')
                .text(this.readout ? 'Purity (%)' : 'POI Purity (%)');
        }

        _renderThresholds() {
            this.thresholds.forEach(threshold => {
                const y = this.yScale(threshold.value);

                // Dashed line
                this.chartGroup.append('line')
                    .attr('class', 'dm-poi-threshold-line')
                    .attr('x1', 0)
                    .attr('x2', this.width)
                    .attr('y1', y)
                    .attr('y2', y)
                    .attr('stroke', threshold.color)
                    .attr('stroke-width', 1.5)
                    .attr('stroke-dasharray', '6,4')
                    .attr('opacity', 0.6);

                // Label
                this.chartGroup.append('text')
                    .attr('class', 'dm-poi-threshold-label')
                    .attr('x', this.width - 4)
                    .attr('y', y - 5)
                    .attr('text-anchor', 'end')
                    .attr('fill', threshold.color)
                    .attr('font-size', '10px')
                    .attr('font-family', 'Roboto, sans-serif')
                    .attr('opacity', 0.7)
                    .text(`${threshold.label} (${threshold.value}%)`);
            });
        }

        _renderBars(data) {
            const self = this;
            const barWidth = this.xScale.bandwidth();
            const barRadius = Math.min(4, barWidth / 4);

            data.forEach((d, i) => {
                const x = this.xScale(d.sampleId);
                const hasData = d.poiPurity !== null;
                const barHeight = hasData ? this.height - this.yScale(d.poiPurity) : this.height * 0.3;
                const barY = hasData ? this.yScale(d.poiPurity) : this.height - barHeight;

                const barGroup = this.chartGroup.append('g')
                    .attr('class', 'dm-poi-bar-group')
                    .attr('data-sample-id', d.sampleId)
                    .style('cursor', 'pointer');

                if (hasData) {
                    // Rounded-top bar using path
                    const path = this._roundedTopRect(x, this.height, barWidth, 0, barRadius);
                    const targetPath = this._roundedTopRect(x, barY, barWidth, barHeight, barRadius);

                    barGroup.append('path')
                        .attr('class', 'dm-poi-bar')
                        .attr('d', path)
                        .attr('fill', d.color)
                        .attr('opacity', 0.85)
                        .transition()
                        .duration(500)
                        .delay(i * 80)
                        .ease(d3.easeCubicOut)
                        .attr('d', targetPath);

                    // Value label
                    barGroup.append('text')
                        .attr('class', 'dm-poi-value-label')
                        .attr('x', x + barWidth / 2)
                        .attr('y', this.height)
                        .attr('text-anchor', 'middle')
                        .style('fill', 'var(--dm-fg-100)')
                        .attr('font-family', "'Roboto Mono', monospace")
                        .attr('font-size', '12px')
                        .attr('font-weight', '600')
                        .text(`${d.poiPurity.toFixed(1)}%`)
                        .transition()
                        .duration(500)
                        .delay(i * 80)
                        .ease(d3.easeCubicOut)
                        .attr('y', barY - 8);
                } else {
                    // No-data bar: dashed outline
                    barGroup.append('rect')
                        .attr('class', 'dm-poi-bar dm-poi-bar-nodata')
                        .attr('x', x)
                        .attr('y', barY)
                        .attr('width', barWidth)
                        .attr('height', barHeight)
                        .attr('rx', barRadius)
                        .attr('fill', 'none')
                        .style('stroke', 'var(--dm-line-20)')
                        .attr('stroke-width', 1.5)
                        .attr('stroke-dasharray', '4,3');

                    // N/A label
                    barGroup.append('text')
                        .attr('x', x + barWidth / 2)
                        .attr('y', barY + barHeight / 2)
                        .attr('text-anchor', 'middle')
                        .attr('dominant-baseline', 'middle')
                        .style('fill', 'var(--dm-fg-40)')
                        .attr('font-size', '11px')
                        .attr('font-family', 'Roboto, sans-serif')
                        .text(d.reason.length > 14 ? d.reason.slice(0, 13) + '…' : d.reason);
                }

                // Interaction handlers
                barGroup
                    .on('mouseenter', function(event) {
                        d3.select(this).select('.dm-poi-bar')
                            .attr('filter', 'brightness(1.2)');
                        self._showTooltip(event, d);
                    })
                    .on('mousemove', function(event) {
                        self._moveTooltip(event);
                    })
                    .on('mouseleave', function() {
                        d3.select(this).select('.dm-poi-bar')
                            .attr('filter', null);
                        self._hideTooltip();
                    })
                    .on('click', function() {
                        self.state.selectSample(d.sampleId);
                    });
            });
        }

        /**
         * Create SVG path for a rectangle with rounded top corners.
         */
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


        /**
         * A western kind: the densitometry page's chart (js/shared/readout-charts.js) over the lanes' readout
         * values, one row per lane in the comparison's order and colour. On anti-HCP each lane is read against
         * ITS blot's reference lane; the a.u. signal is drawn only when every lane comes from one blot.
         */
        _renderWestern() {
            const Charts = global.GelAnalyzer && global.GelAnalyzer.ReadoutCharts;
            const samples = this.state.getSamples() || [];
            if (!Charts) {
                this._showEmptyState('The readout charts are not loaded on this page.');
                return;
            }
            if (!samples.length) {
                this._showEmptyState('Add lanes to view their readout');
                return;
            }
            const esc = Charts.esc;
            const entries = samples.map((sample) => {
                const r = sample.readout || {};
                return {
                    sampleId: sample.sampleId,
                    label: sample.label,
                    color: sample.color,
                    gel: sample.analysis?.name || '',
                    laneNumber: sample.lane?.lane_number,
                    referenceLaneNumber: r.reference_lane_number,
                    values: r.values || null,
                    reason: r.reason || null,
                    is_reference: !!r.is_reference,
                    carries: r.carries,
                };
            });
            const hcp = this.readout === 'HOST_CELL_PROTEINS';
            const label = (entry) => {
                const ref = entry.is_reference ? '<span class="ga-wb-ref">REF</span>' : '';
                const against = hcp && !entry.is_reference && entry.referenceLaneNumber != null
                    ? ` · ref. L${esc(entry.referenceLaneNumber)}` : '';
                return `<div class="dm-ro-label" data-sample-id="${esc(entry.sampleId)}">
                    <i class="ga-wb-sw" style="background:${esc(entry.color)}"></i>
                    <span class="dm-readout-sample">${esc(entry.label)}</span>${ref}
                    <small class="dm-readout-gel">L${esc(entry.laneNumber)} · ${esc(entry.gel)}${against}</small></div>`;
            };
            const blots = new Set(samples.map((sample) => sample.analysis?.id).filter(Boolean));
            const html = hcp
                ? Charts.hcp(entries, {
                    label,
                    signalComparable: blots.size <= 1,
                    note: `% of ref. = each lane's HCP signal ÷ its own blot's reference lane, on the same membrane:
                        it compares across blots. The signal in a.u. depends on the exposure: it is compared within
                        one blot only. POI bands (cross-reacting molecule) are left out of the HCP signal.`,
                })
                : Charts.variants(entries, { label });
            this.container.innerHTML = `<div class="dm-readout-view">${html}</div>`;
            this.container.querySelectorAll('.dm-ro-label[data-sample-id]').forEach((el) => {
                el.style.cursor = 'pointer';
                el.addEventListener('click', () => this.state.selectSample(el.dataset.sampleId));
            });
        }

        // =====================================================================
        // Tooltip
        // =====================================================================

        _showTooltip(event, d) {
            const tooltip = this._getTooltip();
            const hasData = d.poiPurity !== null;

            let html = `<strong style="color:${d.color}">${escapeHtml(d.label)}</strong><br>`;
            if (hasData) {
                html += `Purity: <strong>${d.poiPurity.toFixed(1)}%</strong><br>`;
            } else {
                html += `Purity: <em>${escapeHtml(d.reason)}</em><br>`;
            }
            if (d.gelName) {
                html += `Source: ${escapeHtml(d.gelName)}<br>`;
            }
            html += `Bands: ${d.poiBands} POI / ${d.totalBands} total`;

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
            // Scope the lookup to the panel's tooltipLayer (Task 7) so two
            // mounted components on one page don't share a single tooltip.
            const host = this.tooltipLayer || document.body;
            let tooltip = host.querySelector('.dm-chart-tooltip');
            if (!tooltip) {
                tooltip = document.createElement('div');
                tooltip.className = 'dm-tooltip dm-chart-tooltip';
                host.appendChild(tooltip);
            }
            return tooltip;
        }

        // =====================================================================
        // Selection Highlighting
        // =====================================================================

        _highlightSelectedSample(sampleId) {
            if (!this.chartGroup) return;

            const barGroups = this.chartGroup.selectAll('.dm-poi-bar-group');

            if (!sampleId) {
                // Clear selection - restore all bars
                barGroups.select('.dm-poi-bar').attr('opacity', 0.85);
                barGroups.select('.dm-poi-bar:not(.dm-poi-bar-nodata)').style('stroke', null).attr('stroke-width', null);
                return;
            }

            barGroups.each(function() {
                const group = d3.select(this);
                const id = group.attr('data-sample-id');
                const bar = group.select('.dm-poi-bar');
                const isSelected = id === sampleId;

                if (bar.classed('dm-poi-bar-nodata')) {
                    bar.attr('stroke-opacity', isSelected ? 1 : 0.3);
                } else {
                    bar.attr('opacity', isSelected ? 1 : 0.3);
                }

                // Theme colours through inline styles (SVG attributes take no CSS variable).
                if (isSelected && !bar.classed('dm-poi-bar-nodata')) {
                    bar.style('stroke', 'var(--dm-fg-100)')
                       .attr('stroke-width', 2);
                } else {
                    bar.style('stroke', bar.classed('dm-poi-bar-nodata') ? 'var(--dm-line-20)' : null)
                       .attr('stroke-width', bar.classed('dm-poi-bar-nodata') ? 1.5 : null);
                }
            });
        }

        // =====================================================================
        // Empty State
        // =====================================================================

        _showEmptyState(message) {
            this.container.innerHTML = '';

            const wrapper = document.createElement('div');
            wrapper.className = 'dm-poi-placeholder';
            wrapper.innerHTML = `
                <i class="bi bi-bar-chart" style="font-size: 2rem; opacity: 0.3; margin-bottom: 8px;"></i>
                <span style="color: var(--dm-fg-50); font-size: 0.85rem;"></span>
            `;
            // Text, never HTML: the message names lanes, and a lane's label is user-entered.
            wrapper.querySelector('span').textContent = message;
            this.container.appendChild(wrapper);
        }

        // =====================================================================
        // Events
        // =====================================================================

        _setupEvents() {
            this._on(ComparisonEvents.DATA_LOADED, () => this._render());
            this._on(ComparisonEvents.SAMPLE_ADDED, () => this._render());
            this._on(ComparisonEvents.SAMPLE_REMOVED, () => this._render());
            this._on(ComparisonEvents.SAMPLE_ORDER_CHANGED, () => this._render());
            this._on(ComparisonEvents.SAMPLE_SELECTED, (data) => {
                this._highlightSelectedSample(data.sampleId);
            });
        }

        // =====================================================================
        // Resize
        // =====================================================================

        _setupResizeObserver() {
            if (!this.container) return;
            // Cancel-previous debounce: keep local id, register one teardown disposer.
            this._observe(this.container, () => {
                if (this._resizeTimeout) {
                    cancelAnimationFrame(this._resizeTimeout);
                }
                this._resizeTimeout = requestAnimationFrame(() => this._handleResize());
            });
            this._disposers.push(() => cancelAnimationFrame(this._resizeTimeout));
        }

        _handleResize() {
            const rect = this.container.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) return;

            // Only re-render if container is visible (display is not none)
            if (this.container.offsetParent === null) return;

            const newWidth = rect.width - this.margin.left - this.margin.right;
            const newHeight = rect.height - this.margin.top - this.margin.bottom;

            if (Math.abs(newWidth - this.width) < 5 && Math.abs(newHeight - this.height) < 5) {
                return;
            }

            this._render();
        }
    }

    // Export to namespace
    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.Panels = global.SampleComparison.Panels || {};
    global.SampleComparison.Panels.PoiPurity = ComparisonPoiPurityPanel;

})(window);
