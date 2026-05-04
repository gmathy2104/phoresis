/**
 * Comparison Chromatogram Panel
 *
 * D3.js multi-profile visualization with MW/position toggle, zoom,
 * peak markers, and interactive legend. Supports overlay mode.
 */

(function(global) {
    'use strict';

    // Get dependencies from namespaces
    const ComparisonEvents = global.SampleComparison?.Events;
    const MWUtils = global.SampleComparison?.MWUtils;
    const NormalizationUtils = global.SampleComparison?.NormalizationUtils;

    /**
     * ComparisonChromatogramPanel Class
     */
    class ComparisonChromatogramPanel {
        constructor(options) {
            this.container = options.container;
            this.eventBus = options.eventBus;
            this.state = options.state;

            this.contentElement = null;
            this.margin = { top: 20, right: 20, bottom: 50, left: 70 };
            this.width = 0;
            this.height = 0;

            // Legend state
            this.legendCollapsed = false;
            this.legendContainer = null;

            // D3 elements
            this.svg = null;
            this.chartGroup = null;
            this.xScale = null;
            this.yScale = null;
            this.xScaleOriginal = null;
            this.yScaleOriginal = null;

            // Zoom state
            this.currentTransform = d3.zoomIdentity;
            this.zoom = null;

            // Store profile data for zoom updates
            this.profileDataSets = [];
            this.peakDataMap = new Map();

            // Axis mode: 'mw' (log scale) or 'position' (Y pixel)
            this.xAxisMode = 'mw';

            this.colors = {
                profile: '#2196F3',
                background: '#E0E0E0',
                poi: '#22C55E',
                other: '#9E9E9E',
                mwReference: '#FFC107',
            };

            this._init();
        }

        _init() {
            if (!this.container) return;

            this.contentElement = this.container.querySelector('#chromatogram-container')
                                || this.container.querySelector('.dm-panel-content');
            if (!this.contentElement) {
                this.contentElement = this.container;
            }

            this._createChart();
            this._setupEvents();
            this._setupResizeObserver();
        }

        _createChart() {
            this.contentElement.innerHTML = '';

            const rect = this.contentElement.getBoundingClientRect();
            this.width = rect.width - this.margin.left - this.margin.right;
            this.height = rect.height - this.margin.top - this.margin.bottom;

            if (this.width <= 0 || this.height <= 0) {
                this.width = 400;
                this.height = 250;
            }

            // Create SVG
            this.svg = d3.select(this.contentElement)
                .append('svg')
                .attr('width', this.width + this.margin.left + this.margin.right)
                .attr('height', this.height + this.margin.top + this.margin.bottom)
                .attr('class', 'dm-chromatogram-svg');

            // Defs for gradients and clip path
            const defs = this.svg.append('defs');

            defs.append('clipPath')
                .attr('id', 'comparison-chart-clip')
                .append('rect')
                .attr('width', this.width)
                .attr('height', this.height);

            // Chart group
            this.chartGroup = this.svg.append('g')
                .attr('transform', `translate(${this.margin.left},${this.margin.top})`);

            // Scales
            this.xScale = d3.scaleLinear().range([0, this.width]);
            this.yScale = d3.scaleLinear().range([this.height, 0]);

            // Axes groups
            this.xAxisGroup = this.chartGroup.append('g')
                .attr('class', 'x-axis')
                .attr('transform', `translate(0,${this.height})`);

            this.yAxisGroup = this.chartGroup.append('g')
                .attr('class', 'y-axis');

            // Content group with clip path
            this.contentGroup = this.chartGroup.append('g')
                .attr('class', 'chart-content')
                .attr('clip-path', 'url(#comparison-chart-clip)');

            // Profiles group
            this.profilesGroup = this.contentGroup.append('g')
                .attr('class', 'profiles');

            // Peak highlights group
            this.peakGroup = this.contentGroup.append('g')
                .attr('class', 'peak-highlights');

            // Zoom overlay rect
            this.zoomRect = this.chartGroup.append('rect')
                .attr('class', 'zoom-rect')
                .attr('width', this.width)
                .attr('height', this.height)
                .attr('fill', 'none')
                .attr('pointer-events', 'all');

            // Create legend and zoom controls
            this._createLegendContainer();
            this._createZoomControls();

            // Axis labels
            this.xAxisLabel = this.chartGroup.append('text')
                .attr('class', 'x-axis-label')
                .attr('x', this.width / 2)
                .attr('y', this.height + 40)
                .attr('text-anchor', 'middle')
                .attr('fill', 'rgba(255,255,255,0.7)')
                .attr('font-size', '12px')
                .attr('font-family', 'Inter, system-ui, sans-serif')
                .text(this._getXAxisLabel());

            this.chartGroup.append('text')
                .attr('class', 'y-axis-label')
                .attr('transform', 'rotate(-90)')
                .attr('x', -this.height / 2)
                .attr('y', -55)
                .attr('text-anchor', 'middle')
                .attr('fill', 'rgba(255,255,255,0.7)')
                .attr('font-size', '12px')
                .attr('font-family', 'Inter, system-ui, sans-serif')
                .text('Intensity');

            this._setupZoom();
            this._showPlaceholder('Add samples to compare profiles');
        }

        _setupZoom() {
            this.zoom = d3.zoom()
                .scaleExtent([1, 20])
                .translateExtent([[0, 0], [this.width, this.height]])
                .extent([[0, 0], [this.width, this.height]])
                .on('zoom', (event) => this._onZoom(event));

            this.zoomRect.call(this.zoom);
            this.zoomRect.on('.zoom', null);

            // Brush for selection-to-zoom
            this.brush = d3.brushX()
                .extent([[0, 0], [this.width, this.height]])
                .on('end', (event) => this._onBrushEnd(event));

            this.brushGroup = this.chartGroup.append('g')
                .attr('class', 'brush-group')
                .call(this.brush);

            this.zoomRect.on('dblclick', () => {
                this.zoomRect.transition()
                    .duration(300)
                    .call(this.zoom.transform, d3.zoomIdentity);
            });

            this._addZoomHint();
        }

        _onBrushEnd(event) {
            if (!event.selection) return;

            const [x0, x1] = event.selection;
            this.brushGroup.call(this.brush.move, null);

            if (Math.abs(x1 - x0) < 10) return;

            const scale = this.width / (x1 - x0);
            const clampedScale = Math.min(Math.max(scale, 1), 20);

            const newTransform = d3.zoomIdentity
                .scale(clampedScale)
                .translate(-x0, 0);

            this.zoomRect.transition()
                .duration(300)
                .call(this.zoom.transform, newTransform);
        }

        _addZoomHint() {
            this.chartGroup.selectAll('.zoom-hint').remove();

            this.chartGroup.append('text')
                .attr('class', 'zoom-hint')
                .attr('x', this.width / 2)
                .attr('y', this.height + 28)
                .attr('text-anchor', 'middle')
                .attr('fill', 'rgba(255,255,255,0.4)')
                .attr('font-size', '10px')
                .attr('font-family', 'Inter, system-ui, sans-serif')
                .text('Drag to select zoom region \u2022 Double-click to reset');
        }

        _onZoom(event) {
            this.currentTransform = event.transform;

            const zoomedXScale = this.currentTransform.rescaleX(this.xScaleOriginal || this.xScale);
            const yScale = this.yScaleOriginal || this.yScale;

            this.xAxisGroup.call(d3.axisBottom(zoomedXScale));
            this._styleAxes();

            this._updateProfilesWithZoom(zoomedXScale, yScale);
            this._updatePeaksWithZoom(zoomedXScale, yScale);
        }

        _updateProfilesWithZoom(xScale, yScale) {
            const zoomedLine = d3.line()
                .x(d => xScale(d.x))
                .y(d => yScale(d.y))
                .curve(d3.curveMonotoneX);

            const zoomedArea = d3.area()
                .x(d => xScale(d.x))
                .y0(this.height)
                .y1(d => yScale(d.y))
                .curve(d3.curveMonotoneX);

            this.profilesGroup.selectAll('.profile-line').each(function() {
                const path = d3.select(this);
                const data = path.datum();
                if (data && data.length > 0) {
                    path.attr('d', zoomedLine(data));
                }
            });

            this.profilesGroup.selectAll('.profile-area').each(function() {
                const path = d3.select(this);
                const data = path.datum();
                if (data && data.length > 0) {
                    path.attr('d', zoomedArea(data));
                }
            });
        }

        _updatePeaksWithZoom(xScale, yScale) {
            const self = this;

            this.peakGroup.selectAll('.peak-marker').each(function() {
                const marker = d3.select(this);
                const bandId = marker.attr('data-band-id');
                const peakData = self.peakDataMap.get(bandId);

                if (peakData) {
                    marker
                        .attr('cx', xScale(peakData.x))
                        .attr('cy', yScale(peakData.y));
                }
            });

            this.peakGroup.selectAll('.peak-mw-label').each(function() {
                const label = d3.select(this);
                const bandId = label.attr('data-band-id');
                const peakData = self.peakDataMap.get(bandId);

                if (peakData) {
                    label
                        .attr('x', xScale(peakData.x))
                        .attr('y', yScale(peakData.y) - 12);
                }
            });
        }

        _styleAxes() {
            this.chartGroup.selectAll('.x-axis text, .y-axis text')
                .attr('fill', 'rgba(255,255,255,0.7)')
                .attr('font-family', 'Inter, system-ui, sans-serif')
                .attr('font-size', '10px');
            this.chartGroup.selectAll('.domain, .tick line')
                .attr('stroke', 'rgba(255,255,255,0.3)');
        }

        _setupEvents() {
            this.eventBus.on(ComparisonEvents.DATA_LOADED, () => this._renderProfiles());
            this.eventBus.on(ComparisonEvents.SAMPLE_ADDED, () => this._renderProfiles());
            this.eventBus.on(ComparisonEvents.SAMPLE_REMOVED, () => this._renderProfiles());
            this.eventBus.on(ComparisonEvents.SAMPLE_ORDER_CHANGED, () => this._renderProfiles());
            this.eventBus.on(ComparisonEvents.PROFILE_LOADED, () => this._renderProfiles());
            this.eventBus.on(ComparisonEvents.POI_ONLY_MODE_CHANGED, () => this._renderProfiles());
            this.eventBus.on(ComparisonEvents.BAND_SELECTED, (data) => this._highlightSelectedBand(data.bandId));
            this.eventBus.on(ComparisonEvents.SAMPLE_SELECTED, (data) => this._highlightSelectedSample(data.sampleId));
            this.eventBus.on(ComparisonEvents.X_AXIS_MODE_CHANGED, (data) => {
                this.xAxisMode = data.mode;
                this._updateXAxisLabel();
                this._renderProfiles();
            });
            this.eventBus.on(ComparisonEvents.NORMALIZATION_MODE_CHANGED, () => this._renderProfiles());
            this.eventBus.on(ComparisonEvents.TRACE_VISIBILITY_CHANGED, () => this._renderProfiles());
        }

        _getXAxisLabel() {
            return this.xAxisMode === 'mw'
                ? 'Molecular Weight (kDa)'
                : 'Y Position (pixels)';
        }

        _updateXAxisLabel() {
            if (this.xAxisLabel) {
                this.xAxisLabel.text(this._getXAxisLabel());
            }
        }

        _renderProfiles() {
            const profiles = this.state.getAllProfiles();
            const useMWMode = this.xAxisMode === 'mw' || this.state.xAxisMode === 'mw';

            if (profiles.length === 0) {
                this._showPlaceholder('Add samples to compare profiles');
                return;
            }

            this._hidePlaceholder();

            let allData = [];
            this.profileDataSets = [];
            this.peakDataMap.clear();

            const hasMWData = profiles.some(p => p.mw_profile?.mw_values?.length > 0);

            profiles.forEach(p => {
                if (!p.profile || !p.profile.y_positions) return;

                let data;

                if (useMWMode && hasMWData && p.mw_profile?.mw_values) {
                    data = [];
                    for (let i = 0; i < p.mw_profile.mw_values.length; i++) {
                        const mw = p.mw_profile.mw_values[i];
                        const intensity = p.mw_profile.intensities[i];
                        if (mw !== null && intensity !== null && mw > 0) {
                            data.push({ x: mw, y: intensity, yPos: p.mw_profile.y_positions[i] });
                        }
                    }
                } else if (useMWMode && p.calibration && p.lane_geometry && MWUtils) {
                    data = [];
                    for (let i = 0; i < p.profile.y_positions.length; i++) {
                        const y = p.profile.y_positions[i];
                        const mw = MWUtils.positionToMW(y, p.lane_geometry, p.calibration);
                        const intensity = p.profile.intensities[i];
                        if (mw !== null && mw > 0) {
                            data.push({ x: mw, y: intensity, yPos: y });
                        }
                    }
                } else {
                    data = p.profile.y_positions.map((y, i) => ({
                        x: y,
                        y: p.profile.intensities[i],
                        yPos: y,
                    }));
                }

                if (data.length > 0) {
                    allData = allData.concat(data);
                    this.profileDataSets.push({
                        ...p,
                        chartData: data,
                        useMWMode: useMWMode && (hasMWData || (p.calibration && p.lane_geometry)),
                    });
                }
            });

            if (allData.length === 0) {
                this._showPlaceholder('No profile data available');
                return;
            }

            const xExtent = d3.extent(allData, d => d.x);
            let yMax = d3.max(allData, d => d.y) * 1.1;

            if (this.state.scaleMode === 'normalized') {
                yMax = 1.1;
            }

            if (useMWMode && hasMWData) {
                const minMW = Math.max(5, xExtent[0] * 0.9);
                const maxMW = xExtent[1] * 1.1;

                this.xScale = d3.scaleLog()
                    .domain([maxMW, minMW])
                    .range([0, this.width])
                    .clamp(true);
            } else {
                this.xScale = d3.scaleLinear()
                    .domain(xExtent)
                    .range([0, this.width]);
            }

            this.yScale = d3.scaleLinear()
                .domain([0, yMax])
                .range([this.height, 0]);

            this.xScaleOriginal = this.xScale.copy();
            this.yScaleOriginal = this.yScale.copy();

            this.currentTransform = d3.zoomIdentity;
            if (this.zoomRect && this.zoom) {
                this.zoomRect.call(this.zoom.transform, d3.zoomIdentity);
            }

            if (useMWMode && hasMWData) {
                this.xAxisGroup.call(
                    d3.axisBottom(this.xScale)
                        .ticks(8, '.0f')
                        .tickFormat(d => `${d}`)
                );
            } else {
                this.xAxisGroup.call(d3.axisBottom(this.xScale));
            }
            this.yAxisGroup.call(d3.axisLeft(this.yScale));
            this._styleAxes();

            this._updateXAxisLabel();

            this.profilesGroup.selectAll('*').remove();
            this.peakGroup.selectAll('*').remove();
            this.svg.select('defs').selectAll('.profile-gradient').remove();

            const line = d3.line()
                .x(d => this.xScale(d.x))
                .y(d => this.yScale(d.y))
                .curve(d3.curveMonotoneX)
                .defined(d => d.x > 0 && !isNaN(this.xScale(d.x)));

            const area = d3.area()
                .x(d => this.xScale(d.x))
                .y0(this.height)
                .y1(d => this.yScale(d.y))
                .curve(d3.curveMonotoneX)
                .defined(d => d.x > 0 && !isNaN(this.xScale(d.x)));

            this.profileDataSets.forEach((profileData, index) => {
                if (!this._isTraceVisible(profileData.sampleId)) {
                    return;
                }

                let chartData = profileData.chartData;

                // Filter trace to POI regions if POI-only mode is active
                if (this.state.poiOnlyMode) {
                    chartData = this._filterChartDataToPOI(chartData, profileData.sampleId, profileData.useMWMode);
                }

                if (NormalizationUtils && this.state.normalizationMode !== 'raw') {
                    const intensities = chartData.map(d => d.y);
                    const normalized = NormalizationUtils.normalizeProfile(
                        intensities,
                        this.state.normalizationMode
                    );
                    chartData = chartData.map((d, i) => ({ ...d, y: normalized[i] }));
                } else if (this.state.scaleMode === 'normalized') {
                    const maxY = d3.max(chartData, d => d.y) || 1;
                    chartData = chartData.map(d => ({ ...d, y: d.y / maxY }));
                }

                profileData.chartData = chartData;

                const gradientId = `profile-gradient-${index}-${Date.now()}`;
                const gradient = this.svg.select('defs')
                    .append('linearGradient')
                    .attr('class', 'profile-gradient')
                    .attr('id', gradientId)
                    .attr('x1', '0%')
                    .attr('y1', '100%')
                    .attr('x2', '0%')
                    .attr('y2', '0%');

                gradient.append('stop')
                    .attr('offset', '0%')
                    .attr('stop-color', profileData.color)
                    .attr('stop-opacity', 0);

                gradient.append('stop')
                    .attr('offset', '100%')
                    .attr('stop-color', profileData.color)
                    .attr('stop-opacity', 0.3);

                this.profilesGroup.append('path')
                    .datum(chartData)
                    .attr('class', 'profile-area')
                    .attr('fill', `url(#${gradientId})`)
                    .attr('data-sample-id', profileData.sampleId)
                    .attr('d', area);

                const sampleId = profileData.sampleId;
                const self = this;

                this.profilesGroup.append('path')
                    .datum(chartData)
                    .attr('class', 'profile-line')
                    .attr('fill', 'none')
                    .attr('stroke', profileData.color)
                    .attr('stroke-width', 2)
                    .attr('data-sample-id', sampleId)
                    .attr('d', line)
                    .style('cursor', 'pointer')
                    .on('mouseenter', function() {
                        d3.select(this).attr('stroke-width', 3);
                    })
                    .on('mouseleave', function() {
                        const isSelected = self.state.selectedSampleId === sampleId;
                        d3.select(this).attr('stroke-width', isSelected ? 3 : 2);
                    })
                    .on('click', () => {
                        this.state.selectSample(sampleId);
                    });

                this._renderPeaksForSample(profileData.sampleId, profileData.color, chartData, profileData.useMWMode);
            });

            this._renderLegend(this.profileDataSets);
        }

        /**
         * Filter chart data to only include points within POI band boundaries.
         * Used when POI-only mode is active.
         */
        _filterChartDataToPOI(chartData, sampleId, useMWMode) {
            const sampleData = this.state.getSample(sampleId);
            if (!sampleData || !sampleData.bands) return chartData;

            // Get POI bands with their boundaries
            const poiBands = sampleData.bands.filter(b => b.band_type === 'POI');
            if (poiBands.length === 0) return [];

            // Build ranges from POI bands
            const ranges = [];
            poiBands.forEach(band => {
                if (useMWMode && band.estimated_mw_kda) {
                    // MW mode: use MW value +/- tolerance (20% range around peak)
                    const mw = band.estimated_mw_kda;
                    const tolerance = mw * 0.15; // 15% on each side
                    ranges.push({ min: mw - tolerance, max: mw + tolerance, type: 'mw' });
                } else if (band.bbox && band.bbox.y !== null && band.bbox.height) {
                    // Position mode: use bbox boundaries
                    const yTop = band.bbox.y;
                    const yBottom = band.bbox.y + band.bbox.height;
                    ranges.push({ min: yTop, max: yBottom, type: 'position' });
                } else if (band.position_y) {
                    // Fallback: use position_y with estimated width
                    const y = band.position_y;
                    const estimatedHalfHeight = 15; // pixels
                    ranges.push({ min: y - estimatedHalfHeight, max: y + estimatedHalfHeight, type: 'position' });
                }
            });

            if (ranges.length === 0) return chartData;

            // Filter chart data to only include points within any POI range
            return chartData.filter(d => {
                return ranges.some(range => {
                    if (range.type === 'mw') {
                        // For MW mode, check MW value (d.x is MW)
                        return d.x >= range.min && d.x <= range.max;
                    } else {
                        // For position mode, check Y position
                        const yPos = d.yPos !== undefined ? d.yPos : d.x;
                        return yPos >= range.min && yPos <= range.max;
                    }
                });
            });
        }

        _renderPeaksForSample(sampleId, color, chartData, useMWMode = false) {
            const sampleData = this.state.getSample(sampleId);
            if (!sampleData || !sampleData.bands) return;

            // Check POI-only mode - filter to show only POI peaks when enabled
            const poiOnlyMode = this.state.poiOnlyMode;

            sampleData.bands.forEach(band => {
                // Skip non-POI bands if POI-only mode is active
                if (poiOnlyMode && band.band_type !== 'POI') {
                    return;
                }
                let closestPoint = null;
                let minDist = Infinity;

                if (useMWMode && band.estimated_mw_kda) {
                    const targetMW = band.estimated_mw_kda;
                    chartData.forEach(d => {
                        if (d.x > 0) {
                            const dist = Math.abs(d.x - targetMW);
                            if (dist < minDist) {
                                minDist = dist;
                                closestPoint = d;
                            }
                        }
                    });
                    const tolerance = targetMW * 0.1;
                    if (minDist > tolerance) closestPoint = null;
                } else {
                    const peakY = band.position_y;
                    chartData.forEach(d => {
                        const yPos = d.yPos !== undefined ? d.yPos : d.x;
                        const dist = Math.abs(yPos - peakY);
                        if (dist < minDist) {
                            minDist = dist;
                            closestPoint = d;
                        }
                    });
                    if (minDist > 10) closestPoint = null;
                }

                if (!closestPoint) return;

                this.peakDataMap.set(band.id, {
                    x: closestPoint.x,
                    y: closestPoint.y,
                    sampleId: sampleId,
                    band: band,
                    color: color
                });

                const peakColor = this._getBandColor(band.band_type);

                this.peakGroup.append('circle')
                    .attr('class', 'peak-marker')
                    .attr('cx', this.xScale(closestPoint.x))
                    .attr('cy', this.yScale(closestPoint.y))
                    .attr('r', 5)
                    .attr('fill', peakColor)
                    .attr('stroke', '#fff')
                    .attr('stroke-width', 2)
                    .attr('data-band-id', band.id)
                    .attr('data-sample-id', sampleId)
                    .style('cursor', 'pointer')
                    .on('click', () => this.state.selectBand(band.id))
                    .on('mouseenter', (event) => this._onPeakHover(event, band, sampleData))
                    .on('mouseleave', () => this._hideTooltip());

                if (band.estimated_mw_kda) {
                    this.peakGroup.append('text')
                        .attr('class', 'peak-mw-label')
                        .attr('x', this.xScale(closestPoint.x))
                        .attr('y', this.yScale(closestPoint.y) - 12)
                        .attr('text-anchor', 'middle')
                        .attr('font-size', '10px')
                        .attr('font-weight', 'bold')
                        .attr('font-family', 'Inter, system-ui, sans-serif')
                        .attr('fill', peakColor)
                        .attr('data-band-id', band.id)
                        .text(`${band.estimated_mw_kda.toFixed(0)} kDa`);
                }
            });
        }

        _getBandColor(bandType) {
            switch (bandType) {
                case 'POI': return this.colors.poi;
                case 'MW_REFERENCE': return this.colors.mwReference;
                default: return this.colors.other;
            }
        }

        _createLegendContainer() {
            if (this.legendContainer) {
                this.legendContainer.remove();
            }

            this.legendContainer = document.createElement('div');
            this.legendContainer.className = 'dm-chart-legend-panel';
            if (this.legendCollapsed) {
                this.legendContainer.classList.add('collapsed');
            }

            this.legendContainer.innerHTML = `
                <div class="dm-legend-header">
                    <span class="dm-legend-title">Samples</span>
                    <button class="dm-legend-toggle" title="${this.legendCollapsed ? 'Show legend' : 'Hide legend'}">
                        <i class="bi bi-chevron-${this.legendCollapsed ? 'left' : 'right'}"></i>
                    </button>
                </div>
                <div class="dm-legend-content"></div>
            `;

            this.contentElement.style.position = 'relative';
            this.contentElement.appendChild(this.legendContainer);

            const toggleBtn = this.legendContainer.querySelector('.dm-legend-toggle');
            toggleBtn.addEventListener('click', () => this._toggleLegend());
        }

        _createZoomControls() {
            if (this.zoomControls) {
                this.zoomControls.remove();
            }

            const controls = document.createElement('div');
            controls.className = 'dm-zoom-controls';
            controls.innerHTML = `
                <button class="dm-zoom-btn dm-zoom-reset" title="Reset zoom (1:1)">
                    <i class="bi bi-arrows-angle-contract"></i>
                </button>
            `;

            this.contentElement.appendChild(controls);

            controls.querySelector('.dm-zoom-reset').addEventListener('click', () => {
                this._resetZoom();
            });

            this.zoomControls = controls;
        }

        _resetZoom() {
            if (this.zoomRect && this.zoom) {
                this.zoomRect.transition()
                    .duration(300)
                    .call(this.zoom.transform, d3.zoomIdentity);
            }
        }

        _toggleLegend() {
            this.legendCollapsed = !this.legendCollapsed;
            this.legendContainer.classList.toggle('collapsed', this.legendCollapsed);

            const toggleBtn = this.legendContainer.querySelector('.dm-legend-toggle');
            const icon = toggleBtn.querySelector('i');
            icon.className = `bi bi-chevron-${this.legendCollapsed ? 'left' : 'right'}`;
            toggleBtn.title = this.legendCollapsed ? 'Show legend' : 'Hide legend';
        }

        _calculateLegendWidth(profiles) {
            const tempSpan = document.createElement('span');
            tempSpan.style.cssText = 'position: absolute; visibility: hidden; font-size: 11px; font-family: Inter, system-ui, sans-serif;';
            document.body.appendChild(tempSpan);

            let maxWidth = 0;
            profiles.forEach(p => {
                tempSpan.textContent = p.sampleName || `Sample ${p.sampleId}`;
                maxWidth = Math.max(maxWidth, tempSpan.offsetWidth);
            });

            document.body.removeChild(tempSpan);

            const calculatedWidth = maxWidth + 74;
            return Math.min(200, Math.max(140, calculatedWidth));
        }

        _renderLegend(profiles) {
            if (!this.legendContainer) return;

            const contentEl = this.legendContainer.querySelector('.dm-legend-content');
            if (!contentEl) return;

            contentEl.innerHTML = '';

            if (!profiles || profiles.length === 0) {
                this.legendContainer.style.display = 'none';
                return;
            }

            this.legendContainer.style.display = '';

            const legendWidth = this._calculateLegendWidth(profiles);
            this.legendContainer.style.width = this.legendCollapsed ? '' : `${legendWidth}px`;

            profiles.forEach(p => {
                const isVisible = this._isTraceVisible(p.sampleId);
                const isSelected = p.sampleId === this.state.selectedSampleId;
                const item = document.createElement('div');
                item.className = `dm-legend-item${isVisible ? '' : ' hidden-trace'}${isSelected ? ' selected' : ''}`;
                item.dataset.sampleId = p.sampleId;

                item.innerHTML = `
                    <button class="dm-visibility-toggle" title="${isVisible ? 'Hide trace' : 'Show trace'}">
                        <i class="bi bi-eye${isVisible ? '-fill' : '-slash'}"></i>
                    </button>
                    <span class="dm-legend-swatch" style="background-color: ${p.color}"></span>
                    <span class="dm-legend-label">${p.sampleName || `Sample ${p.sampleId}`}</span>
                `;

                const visToggle = item.querySelector('.dm-visibility-toggle');
                visToggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this._toggleTraceVisibility(p.sampleId);
                });

                item.addEventListener('click', () => {
                    this.state.selectSample(p.sampleId);
                });

                contentEl.appendChild(item);
            });
        }

        _isTraceVisible(sampleId) {
            if (this.state.isTraceVisible) {
                return this.state.isTraceVisible(sampleId);
            }
            return true;
        }

        _toggleTraceVisibility(sampleId) {
            if (this.state.toggleTraceVisibility) {
                this.state.toggleTraceVisibility(sampleId);
            } else {
                console.warn('[ComparisonChromatogramPanel] Trace visibility not implemented in state');
            }
        }

        _onPeakHover(event, band, sampleData) {
            const tooltip = this._getTooltip();

            let content = `<strong style="color:${sampleData.color}">${sampleData.label}</strong><br>`;
            content += `<span class="peak-type">${band.band_type}</span><br>`;

            if (band.estimated_mw_kda) {
                content += `MW: ${band.estimated_mw_kda.toFixed(1)} kDa<br>`;
            }

            if (band.densitometry) {
                if (band.densitometry.corrected_area) {
                    content += `Area: ${Math.round(band.densitometry.corrected_area)}<br>`;
                }
                if (band.densitometry.relative_percent_lane) {
                    content += `% Lane: ${band.densitometry.relative_percent_lane.toFixed(1)}%`;
                }
            }

            tooltip.innerHTML = content;
            tooltip.style.left = `${event.pageX + 15}px`;
            tooltip.style.top = `${event.pageY - 10}px`;
            tooltip.style.display = 'block';
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

        _highlightSelectedBand(bandId) {
            this.peakGroup.selectAll('.peak-marker')
                .attr('r', 5)
                .attr('stroke-width', 2);

            if (bandId) {
                this.peakGroup.selectAll(`.peak-marker[data-band-id="${bandId}"]`)
                    .attr('r', 8)
                    .attr('stroke-width', 3);
            }
        }

        _highlightSelectedSample(sampleId) {
            if (!sampleId) return;

            // Dim all traces, then raise selected
            this.profilesGroup.selectAll('.profile-line')
                .attr('stroke-opacity', 0.3)
                .attr('stroke-width', 1.5);

            this.profilesGroup.selectAll('.profile-area')
                .attr('fill-opacity', 0.15);

            // Emphasize selected sample's trace
            const selectedLine = this.profilesGroup
                .selectAll(`.profile-line[data-sample-id="${sampleId}"]`)
                .attr('stroke-opacity', 1)
                .attr('stroke-width', 3);

            // Raise the selected line to render on top
            if (selectedLine.node()) {
                selectedLine.raise();
            }

            this.profilesGroup
                .selectAll(`.profile-area[data-sample-id="${sampleId}"]`)
                .attr('fill-opacity', 1);

            // Update legend selection
            this._updateLegendSelection(sampleId);
        }

        _updateLegendSelection(sampleId) {
            if (!this.legendContainer) return;

            this.legendContainer.querySelectorAll('.dm-legend-item').forEach(item => {
                item.classList.toggle('selected', item.dataset.sampleId === sampleId);
            });
        }

        _showPlaceholder(message) {
            this.profilesGroup.selectAll('*').remove();
            this.peakGroup.selectAll('*').remove();
            if (this.legendContainer) {
                this.legendContainer.style.display = 'none';
            }

            this.chartGroup.selectAll('.placeholder').remove();
            this.chartGroup.append('text')
                .attr('class', 'placeholder')
                .attr('x', this.width / 2)
                .attr('y', this.height / 2)
                .attr('text-anchor', 'middle')
                .attr('fill', 'rgba(255,255,255,0.5)')
                .attr('font-family', 'Inter, system-ui, sans-serif')
                .text(message);
        }

        _hidePlaceholder() {
            this.chartGroup.selectAll('.placeholder').remove();
        }

        _setupResizeObserver() {
            if (this.resizeObserver) {
                this.resizeObserver.disconnect();
            }

            this.resizeObserver = new ResizeObserver(() => {
                if (this.resizeTimeout) {
                    cancelAnimationFrame(this.resizeTimeout);
                }
                this.resizeTimeout = requestAnimationFrame(() => this._handleResize());
            });
            this.resizeObserver.observe(this.contentElement);
        }

        _handleResize() {
            const rect = this.contentElement.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) return;

            const newWidth = rect.width - this.margin.left - this.margin.right;
            const newHeight = rect.height - this.margin.top - this.margin.bottom;

            if (Math.abs(newWidth - this.width) < 5 && Math.abs(newHeight - this.height) < 5) {
                return;
            }

            this._createChart();
            this._renderProfiles();
        }

        destroy() {
            if (this.resizeObserver) {
                this.resizeObserver.disconnect();
                this.resizeObserver = null;
            }
            if (this.resizeTimeout) {
                cancelAnimationFrame(this.resizeTimeout);
                this.resizeTimeout = null;
            }
            if (this.legendContainer) {
                this.legendContainer.remove();
                this.legendContainer = null;
            }
            if (this.zoomControls) {
                this.zoomControls.remove();
                this.zoomControls = null;
            }
        }
    }

    // Export to namespace
    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.Panels = global.SampleComparison.Panels || {};
    global.SampleComparison.Panels.Chromatogram = ComparisonChromatogramPanel;

})(window);
