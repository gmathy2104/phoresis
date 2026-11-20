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

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    /**
     * ComparisonChromatogramPanel Class
     */
    class ComparisonChromatogramPanel extends GelAnalyzer.Viz.Panel {
        constructor(options) {
            super(options);  // sets this.container/eventBus/state/options/tooltipLayer/_disposers

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

            // Brush-zoom window in the data units of _zoomUnit ('mw' | 'position'), in
            // pixel order (the MW axis runs high to low); null = full view. Y re-fits to
            // it. A PD dashboard tile hands in { view, onChange } as options.zoom.
            this._zoomX = null;
            this._zoomUnit = null;
            this._xUnit = null;
            this._xLog = false;
            this.xScaleZoomed = null;
            this.zoomUi = null;
            const zoom = this.options.zoom;
            if (zoom && zoom.view && Array.isArray(zoom.view.x)) {
                this._zoomX = zoom.view.x.slice();
                this._zoomUnit = zoom.view.xUnit || null;
            }

            // Store profile data for zoom updates
            this.profileDataSets = [];
            this.peakDataMap = new Map();

            // Axis mode: 'mw' (log scale) or 'position' (Y pixel)
            this.xAxisMode = 'mw';

            // Day mode (`data-theme="light"` on <html>, set only by hosts that offer it:
            // the PD dashboard) draws on white, so the peak markers take darker shades of
            // the same hues. Read once: the host rebuilds the panel when the mode switches.
            const day = document.documentElement.getAttribute('data-theme') === 'light';
            this.colors = {
                profile: '#2196F3',
                background: '#E0E0E0',
                poi: day ? '#15803d' : '#22C55E',
                other: day ? '#6b7280' : '#9E9E9E',
                mwReference: day ? '#b45309' : '#FFC107',
                calibration: '#f87171',  // Red-400 — CALIBRATION (matches annotation), both modes
            };

            // Unique clip-path id so multiple mounted instances don't collide.
            this._clipId = 'comparison-chart-clip-' + Math.random().toString(36).slice(2);
        }

        init() {
            if (!this.container) return;

            this.contentElement = this.container.querySelector('#chromatogram-container')
                                || this.container.querySelector('.dm-panel-content');
            if (!this.contentElement) {
                this.contentElement = this.container;
            }

            this._createChart();
            this._setupEvents();
            this._setupControls();
            this._setupResizeObserver();
        }

        /**
         * Wire panel-relevant controls living in the mounted skeleton header
         * (Task 7). Container-scoped lookup + tracked listener so repeated
         * mount/unmount cycles don't duplicate handlers.
         */
        _setupControls() {
            const poiOnly = this.container.querySelector('[data-ga-control="poi-only-mode"]');
            if (poiOnly) {
                const handler = (e) => this.state.setPoiOnlyMode(e.target.checked);
                poiOnly.addEventListener('change', handler);
                this._disposers.push(() => poiOnly.removeEventListener('change', handler));
            }
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

            // (A press inside the chart never reaches the dashboard's tile drag:
            // BrushZoom.attachX guards the SVG, see _setupZoom.)

            // Defs for gradients and clip path
            const defs = this.svg.append('defs');

            defs.append('clipPath')
                .attr('id', this._clipId)
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
                .attr('clip-path', `url(#${this._clipId})`);

            // Profiles group
            this.profilesGroup = this.contentGroup.append('g')
                .attr('class', 'profiles');

            // Peak highlights group
            this.peakGroup = this.contentGroup.append('g')
                .attr('class', 'peak-highlights');

            // Create legend
            this._createLegendContainer();

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
            // The shared gesture (GelAnalyzer.Viz.BrushZoom): brush on X, Y re-fits,
            // "Reset zoom" badge + double-click. The badge sits top LEFT: the legend
            // overlays the top right. The brush layer stays on top of the traces.
            this.brushGroup = this.chartGroup.append('g').attr('class', 'brush-group');
            this.zoomUi = global.GelAnalyzer.Viz.BrushZoom.attachX(this.brushGroup, {
                getXScale: () => this.xScaleZoomed || this.xScale,
                width: this.width,
                height: this.height,
                zoomed: false,
                badgeAt: 'left',
                onZoom: (domain) => this._setZoom(domain),
                onReset: () => this._setZoom(null),
            });
            this._disposers.push(() => { if (this.brushGroup) this.brushGroup.on('.brush', null); });
        }

        _setZoom(domain) {
            this._zoomX = domain;
            this._zoomUnit = domain ? this._xUnit : null;
            const zoom = this.options.zoom;
            if (zoom && typeof zoom.onChange === 'function') {
                zoom.onChange(domain ? { x: domain.slice(), y: null, xUnit: this._xUnit } : null);
            }
            this._applyZoom();
        }

        /** Traces, peaks and axes at the zoom window, or at the full view. */
        _applyZoom() {
            if (!this.xScaleOriginal || !this.yScaleOriginal) return;
            const zoomed = !!this._zoomX && this._zoomUnit === this._xUnit;
            const xScale = this.xScaleOriginal.copy();
            let yScale = this.yScaleOriginal.copy();
            if (zoomed) {
                // Unclamped: a point outside the window leaves the plot and is clipped,
                // instead of piling up on its edge (the full-view MW scale clamps).
                xScale.domain(this._zoomX).clamp(false);
                const lo = Math.min(this._zoomX[0], this._zoomX[1]);
                const hi = Math.max(this._zoomX[0], this._zoomX[1]);
                const values = [];
                this.profileDataSets.forEach(p => {
                    if (!this._isTraceVisible(p.sampleId)) return;
                    p.chartData.forEach(d => { if (d.x >= lo && d.x <= hi) values.push(d.y); });
                });
                const fitted = global.GelAnalyzer.Viz.BrushZoom.fitY(values, true);
                if (fitted) yScale = yScale.domain(fitted).nice();
            }
            this.xScaleZoomed = xScale;
            this._drawXAxis(xScale);
            this.yAxisGroup.call(d3.axisLeft(yScale));
            this._styleAxes();
            this._updateProfilesWithZoom(xScale, yScale);
            this._updatePeaksWithZoom(xScale, yScale);
            if (this.zoomUi) this.zoomUi.setZoomed(zoomed);
        }

        _drawXAxis(xScale) {
            if (this._xLog) {
                this.xAxisGroup.call(
                    d3.axisBottom(xScale)
                        .ticks(8, '.0f')
                        .tickFormat(d => `${d}`)
                );
            } else {
                this.xAxisGroup.call(d3.axisBottom(xScale));
            }
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
            this._on(ComparisonEvents.DATA_LOADED, () => this._renderProfiles());
            this._on(ComparisonEvents.SAMPLE_ADDED, () => this._renderProfiles());
            this._on(ComparisonEvents.SAMPLE_REMOVED, () => this._renderProfiles());
            this._on(ComparisonEvents.SAMPLE_ORDER_CHANGED, () => this._renderProfiles());
            this._on(ComparisonEvents.PROFILE_LOADED, () => this._renderProfiles());
            this._on(ComparisonEvents.POI_ONLY_MODE_CHANGED, () => this._renderProfiles());
            this._on(ComparisonEvents.BAND_SELECTED, (data) => this._highlightSelectedBand(data.bandId));
            this._on(ComparisonEvents.SAMPLE_SELECTED, (data) => this._highlightSelectedSample(data.sampleId));
            this._on(ComparisonEvents.X_AXIS_MODE_CHANGED, (data) => {
                this.xAxisMode = data.mode;
                if (this._zoomX) this._setZoom(null);
                this._updateXAxisLabel();
                this._renderProfiles();
            });
            this._on(ComparisonEvents.NORMALIZATION_MODE_CHANGED, () => this._renderProfiles());
            this._on(ComparisonEvents.TRACE_VISIBILITY_CHANGED, () => this._renderProfiles());
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
            this._xUnit = useMWMode ? 'mw' : 'position';
            this._xLog = useMWMode && hasMWData;

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

            // The Y domain of the values the traces will be drawn with (normalised below, at render): Total and
            // Max Peak give 0-100 per trace, the per-trace scaling 0-1. A fixed [0, 1.1] clipped the first two.
            if (NormalizationUtils && this.state.normalizationMode !== 'raw') {
                const mode = this.state.normalizationMode;
                yMax = 1.1 * Math.max(1e-9, ...this.profileDataSets.map((set) => {
                    // As drawn below: the POI-only filter first, then the normalisation.
                    const drawn = this.state.poiOnlyMode
                        ? this._filterChartDataToPOI(set.chartData, set.sampleId, set.useMWMode)
                        : set.chartData;
                    if (!drawn || !drawn.length) return 0;
                    const values = NormalizationUtils.normalizeProfile(drawn.map(d => d.y), mode);
                    return d3.max(values) || 0;
                }));
            } else if (this.state.scaleMode === 'normalized') {
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

            this._drawXAxis(this.xScale);
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
            // Redraw at the zoom window kept across this render (or the full view).
            this._applyZoom();
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
                case 'CALIBRATION': return this.colors.calibration;
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
                    <span class="dm-legend-label">${escapeHtml(p.sampleName || `Sample ${p.sampleId}`)}</span>
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

            let content = `<strong style="color:${sampleData.color}">${escapeHtml(sampleData.label)}</strong><br>`;
            content += `<span class="peak-type">${escapeHtml(band.band_type)}</span><br>`;

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
            // Cancel-previous debounce: keep local id, register one teardown disposer.
            this._observe(this.contentElement, () => {
                if (this.resizeTimeout) {
                    cancelAnimationFrame(this.resizeTimeout);
                }
                this.resizeTimeout = requestAnimationFrame(() => this._handleResize());
            });
            this._disposers.push(() => cancelAnimationFrame(this.resizeTimeout));
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
            // Base class destroy() runs all _disposers (eventBus.off, ResizeObserver.disconnect,
            // cancelAnimationFrame, .brush null).
            super.destroy();
            // DOM cleanup not covered by _disposers:
            if (this.legendContainer) {
                this.legendContainer.remove();
                this.legendContainer = null;
            }
        }
    }

    // Export to namespace
    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.Panels = global.SampleComparison.Panels || {};
    global.SampleComparison.Panels.Chromatogram = ComparisonChromatogramPanel;

})(window);
