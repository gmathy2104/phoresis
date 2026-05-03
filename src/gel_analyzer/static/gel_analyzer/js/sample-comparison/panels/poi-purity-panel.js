/**
 * POI Purity Panel
 *
 * D3.js bar chart showing POI purity percentage per sample.
 * Supports tooltips, click-to-select, threshold lines, and animated transitions.
 */

(function(global) {
    'use strict';

    const ComparisonEvents = global.SampleComparison?.Events;

    class ComparisonPoiPurityPanel {
        constructor(options) {
            this.container = options.container;
            this.eventBus = options.eventBus;
            this.state = options.state;

            this.margin = { top: 30, right: 30, bottom: 60, left: 60 };
            this.width = 0;
            this.height = 0;

            // D3 elements
            this.svg = null;
            this.chartGroup = null;
            this.xScale = null;
            this.yScale = null;

            // Thresholds
            this.thresholds = [
                { value: 90, label: 'Target', color: '#22c55e' },
                { value: 70, label: 'Minimum', color: '#ffc107' },
            ];

            this._init();
        }

        _init() {
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
                const poiPurity = sample.densitometry?.poi_percentage ?? null;
                const totalBands = sample.bands?.length || 0;
                const poiBands = sample.bands?.filter(b => b.band_type === 'POI').length || 0;

                return {
                    sampleId: sample.sampleId,
                    label: sample.label || `Sample ${sample.sampleId}`,
                    color: sample.color || '#2196F3',
                    poiPurity: poiPurity,
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
                    : 'No POI purity data available for selected samples');
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
                .attr('stroke', 'rgba(255,255,255,0.08)')
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
                .attr('fill', 'rgba(255,255,255,0.7)')
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
                .attr('stroke', 'rgba(255,255,255,0.3)');

            // Y axis
            const yAxis = this.chartGroup.append('g')
                .attr('class', 'y-axis')
                .call(d3.axisLeft(this.yScale)
                    .ticks(5)
                    .tickFormat(d => `${d}%`)
                );

            yAxis.selectAll('text')
                .attr('fill', 'rgba(255,255,255,0.7)')
                .attr('font-family', 'Roboto, sans-serif')
                .attr('font-size', '10px');

            yAxis.selectAll('.domain, .tick line')
                .attr('stroke', 'rgba(255,255,255,0.3)');

            // Y axis label
            this.chartGroup.append('text')
                .attr('transform', 'rotate(-90)')
                .attr('x', -this.height / 2)
                .attr('y', -45)
                .attr('text-anchor', 'middle')
                .attr('fill', 'rgba(255,255,255,0.7)')
                .attr('font-size', '12px')
                .attr('font-family', 'Roboto, sans-serif')
                .text('POI Purity (%)');
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
                        .attr('fill', '#fff')
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
                        .attr('stroke', 'rgba(255,255,255,0.2)')
                        .attr('stroke-width', 1.5)
                        .attr('stroke-dasharray', '4,3');

                    // N/A label
                    barGroup.append('text')
                        .attr('x', x + barWidth / 2)
                        .attr('y', barY + barHeight / 2)
                        .attr('text-anchor', 'middle')
                        .attr('dominant-baseline', 'middle')
                        .attr('fill', 'rgba(255,255,255,0.4)')
                        .attr('font-size', '11px')
                        .attr('font-family', 'Roboto, sans-serif')
                        .text('N/A');
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

        // =====================================================================
        // Tooltip
        // =====================================================================

        _showTooltip(event, d) {
            const tooltip = this._getTooltip();
            const hasData = d.poiPurity !== null;

            let html = `<strong style="color:${d.color}">${d.label}</strong><br>`;
            if (hasData) {
                html += `POI Purity: <strong>${d.poiPurity.toFixed(1)}%</strong><br>`;
            } else {
                html += `POI Purity: <em>N/A</em><br>`;
            }
            if (d.gelName) {
                html += `Source: ${d.gelName}<br>`;
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

        _highlightSelectedSample(sampleId) {
            if (!this.chartGroup) return;

            const barGroups = this.chartGroup.selectAll('.dm-poi-bar-group');

            if (!sampleId) {
                // Clear selection - restore all bars
                barGroups.select('.dm-poi-bar').attr('opacity', 0.85);
                barGroups.select('.dm-poi-bar').attr('stroke', null).attr('stroke-width', null);
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

                if (isSelected && !bar.classed('dm-poi-bar-nodata')) {
                    bar.attr('stroke', '#fff')
                       .attr('stroke-width', 2);
                } else {
                    bar.attr('stroke', bar.classed('dm-poi-bar-nodata') ? 'rgba(255,255,255,0.2)' : null)
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
                <span style="color: rgba(255,255,255,0.5); font-size: 0.85rem;">${message}</span>
            `;
            this.container.appendChild(wrapper);
        }

        // =====================================================================
        // Events
        // =====================================================================

        _setupEvents() {
            this.eventBus.on(ComparisonEvents.DATA_LOADED, () => this._render());
            this.eventBus.on(ComparisonEvents.SAMPLE_ADDED, () => this._render());
            this.eventBus.on(ComparisonEvents.SAMPLE_REMOVED, () => this._render());
            this.eventBus.on(ComparisonEvents.SAMPLE_ORDER_CHANGED, () => this._render());
            this.eventBus.on(ComparisonEvents.SAMPLE_SELECTED, (data) => {
                this._highlightSelectedSample(data.sampleId);
            });
        }

        // =====================================================================
        // Resize
        // =====================================================================

        _setupResizeObserver() {
            if (!this.container) return;

            this._resizeObserver = new ResizeObserver(() => {
                if (this._resizeTimeout) {
                    cancelAnimationFrame(this._resizeTimeout);
                }
                this._resizeTimeout = requestAnimationFrame(() => this._handleResize());
            });
            this._resizeObserver.observe(this.container);
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

    // Export to namespace
    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.Panels = global.SampleComparison.Panels || {};
    global.SampleComparison.Panels.PoiPurity = ComparisonPoiPurityPanel;

})(window);
