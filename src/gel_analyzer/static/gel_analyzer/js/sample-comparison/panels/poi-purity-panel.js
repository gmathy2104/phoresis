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

        /**
         * Build a grouped-bar dataset: one group per sample, one bar per
         * POI band inside the group. Per-bar purity =
         * band.corrected_area / lane_total × 100. The previous
         * lane.densitometry.poi_percentage shape collapsed multi-POI
         * lanes into a single sum which hid the per-POI math the user
         * cares about.
         */
        _getChartData() {
            const samples = this.state.getSamples();
            if (!samples || samples.length === 0) return [];

            return samples.map(sample => {
                const allBands = sample.bands || [];
                const totalArea = allBands.reduce(
                    (s, b) => s + ((b.densitometry || {}).corrected_area || 0), 0
                );
                const poiBands = allBands
                    .filter(b => b.band_type === 'POI')
                    .sort((a, b) => (a.band_number || 0) - (b.band_number || 0));
                const bars = (totalArea > 0 ? poiBands : []).map((b, idx) => {
                    const area = (b.densitometry || {}).corrected_area || 0;
                    return {
                        bandId: b.id,
                        bandNumber: b.band_number,
                        bandKey: `b${b.band_number || idx}`,
                        mw: b.estimated_mw_kda,
                        area,
                        purity: (area / totalArea) * 100,
                    };
                });

                return {
                    sampleId: sample.sampleId,
                    label: sample.label || `Sample ${sample.sampleId}`,
                    color: sample.color || '#2196F3',
                    gelName: sample.analysis?.name || sample.gel_name || '',
                    totalBands: allBands.length,
                    poiCount: poiBands.length,
                    bars,
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
            if (data.length === 0 || !data.some(d => d.bars && d.bars.length > 0)) {
                this._showEmptyState(data.length === 0
                    ? 'Add samples to view POI purity'
                    : 'No POI bands across the loaded samples — calibrate or annotate POIs first.');
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

            // Apply current selection — both sample-level dimming and
            // band-level outline.
            this._highlightSelection(this.state.selectedSampleId, this.state.selectedBandId);
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
            const groupWidth = this.xScale.bandwidth();
            const barRadius = 4;
            const selectedBandId = this.state.selectedBandId;
            const selectedSampleId = this.state.selectedSampleId;

            data.forEach((d, i) => {
                const groupX = this.xScale(d.sampleId);
                const sampleGroup = this.chartGroup.append('g')
                    .attr('class', 'dm-poi-bar-group')
                    .attr('data-sample-id', d.sampleId);

                if (!d.bars || d.bars.length === 0) {
                    // Sample has no POI band → render a dashed N/A placeholder.
                    const phHeight = this.height * 0.3;
                    const phY = this.height - phHeight;
                    sampleGroup.append('rect')
                        .attr('class', 'dm-poi-bar dm-poi-bar-nodata')
                        .attr('x', groupX)
                        .attr('y', phY)
                        .attr('width', groupWidth)
                        .attr('height', phHeight)
                        .attr('rx', barRadius)
                        .attr('fill', 'none')
                        .attr('stroke', 'rgba(255,255,255,0.2)')
                        .attr('stroke-width', 1.5)
                        .attr('stroke-dasharray', '4,3');

                    sampleGroup.append('text')
                        .attr('x', groupX + groupWidth / 2)
                        .attr('y', phY + phHeight / 2)
                        .attr('text-anchor', 'middle')
                        .attr('dominant-baseline', 'middle')
                        .attr('fill', 'rgba(255,255,255,0.4)')
                        .attr('font-size', '11px')
                        .attr('font-family', 'Roboto, sans-serif')
                        .text('N/A');

                    sampleGroup.style('cursor', 'pointer')
                        .on('click', () => self.state.selectSample(d.sampleId));
                    return;
                }

                // Inner band scale: one bar per POI inside the sample group.
                const xInner = d3.scaleBand()
                    .domain(d.bars.map(b => b.bandKey))
                    .range([0, groupWidth])
                    .padding(0.12);

                d.bars.forEach((bar, j) => {
                    const bx = groupX + xInner(bar.bandKey);
                    const bw = xInner.bandwidth();
                    const by = this.yScale(bar.purity);
                    const bh = this.height - by;

                    const initialPath = this._roundedTopRect(bx, this.height, bw, 0, Math.min(barRadius, bw / 2));
                    const targetPath = this._roundedTopRect(bx, by, bw, bh, Math.min(barRadius, bw / 2, bh));
                    const isSelected = !!(selectedBandId && bar.bandId === selectedBandId);

                    const barGroup = sampleGroup.append('g')
                        .attr('class', 'dm-poi-bar-cell')
                        .attr('data-band-id', bar.bandId)
                        .attr('data-sample-id', d.sampleId)
                        .style('cursor', 'pointer');

                    barGroup.append('path')
                        .attr('class', 'dm-poi-bar' + (isSelected ? ' selected' : ''))
                        .attr('d', initialPath)
                        .attr('fill', d.color)
                        .attr('opacity', 0.85)
                        .attr('stroke', isSelected ? '#fff' : null)
                        .attr('stroke-width', isSelected ? 1.5 : null)
                        .transition()
                        .duration(400)
                        .delay(i * 60 + j * 30)
                        .ease(d3.easeCubicOut)
                        .attr('d', targetPath);

                    if (bw >= 22) {
                        barGroup.append('text')
                            .attr('class', 'dm-poi-value-label')
                            .attr('x', bx + bw / 2)
                            .attr('y', this.height)
                            .attr('text-anchor', 'middle')
                            .attr('fill', '#fff')
                            .attr('font-family', "'Roboto Mono', monospace")
                            .attr('font-size', bw < 32 ? '10px' : '12px')
                            .attr('font-weight', '600')
                            .text(`${bar.purity.toFixed(0)}%`)
                            .transition()
                            .duration(400)
                            .delay(i * 60 + j * 30)
                            .ease(d3.easeCubicOut)
                            .attr('y', by - 6);
                    }

                    barGroup
                        .on('mouseenter', function(event) {
                            d3.select(this).select('.dm-poi-bar').attr('filter', 'brightness(1.2)');
                            self._showTooltip(event, d, bar);
                        })
                        .on('mousemove', function(event) {
                            self._moveTooltip(event);
                        })
                        .on('mouseleave', function() {
                            d3.select(this).select('.dm-poi-bar').attr('filter', null);
                            self._hideTooltip();
                        })
                        .on('click', function() {
                            // state.selectBand cascades through the comparison
                            // state: parent sample auto-selected, then band
                            // detail / results-table / chromatogram all sync.
                            if (bar.bandId && self.state.selectBand) {
                                self.state.selectBand(bar.bandId);
                            } else {
                                self.state.selectSample(d.sampleId);
                            }
                        });
                });

                // Dim the entire group when another sample is selected.
                if (selectedSampleId && selectedSampleId !== d.sampleId) {
                    sampleGroup.attr('opacity', 0.4);
                }
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

        _showTooltip(event, d, bar) {
            const tooltip = this._getTooltip();

            let html = `<strong style="color:${d.color}">${d.label}</strong><br>`;
            if (bar) {
                html += `POI B${bar.bandNumber || '?'}`;
                if (bar.mw != null) html += ` &middot; ${Math.round(bar.mw)} kDa`;
                html += `<br>Area: ${Math.round(bar.area)}<br>`;
                html += `Purity: <strong>${bar.purity.toFixed(1)}%</strong><br>`;
            } else {
                html += `POI Purity: <em>N/A</em><br>`;
            }
            if (d.gelName) {
                html += `Source: ${d.gelName}<br>`;
            }
            html += `Bands: ${d.poiCount} POI / ${d.totalBands} total`;

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

            // Sample-level dimming: full group fades out when another
            // sample is selected.
            this.chartGroup.selectAll('.dm-poi-bar-group')
                .attr('opacity', function() {
                    const id = d3.select(this).attr('data-sample-id');
                    if (!sampleId) return 1;
                    return id === sampleId ? 1 : 0.4;
                });

            // Band-level outline: white stroke on the matching bar.
            this.chartGroup.selectAll('.dm-poi-bar-cell .dm-poi-bar')
                .attr('stroke', null)
                .attr('stroke-width', null);
            if (bandId) {
                this.chartGroup
                    .selectAll(`.dm-poi-bar-cell[data-band-id="${bandId}"] .dm-poi-bar`)
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
                this._highlightSelection(data && data.sampleId, this.state.selectedBandId);
            });
            this.eventBus.on(ComparisonEvents.BAND_SELECTED, (data) => {
                this._highlightSelection(this.state.selectedSampleId, data && data.bandId);
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
