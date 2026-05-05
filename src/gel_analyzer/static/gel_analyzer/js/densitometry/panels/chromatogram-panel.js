/**
 * Chromatogram Panel - Electropherogram Visualization
 *
 * Displays the intensity profile as an interactive chart using D3.js.
 * Features:
 * - Intensity vs Y position (or MW if calibrated)
 * - Peak highlighting (POI in green)
 * - Interactive zoom and pan (brush-to-zoom)
 * - Click on peaks to select bands
 * - Peak boundaries, gradient area fills, MW labels
 *
 * Uses shared GelAnalyzer.ChartUtils for rendering.
 */

(function(global) {
    'use strict';

    const Events = global.Densitometry.Events;
    const ChartUtils = global.GelAnalyzer?.ChartUtils;
    const MWUtils = global.GelAnalyzer?.MWUtils;

    /**
     * ChromatogramPanel Class
     */
    class ChromatogramPanel {
        /**
         * @param {Object} options
         * @param {HTMLElement} options.container
         * @param {EventBus} options.eventBus
         * @param {State} options.state
         */
        constructor(options) {
            this.container = options.container;
            this.eventBus = options.eventBus;
            this.state = options.state;

            // Chart dimensions
            this.margin = { top: 20, right: 30, bottom: 50, left: 60 };
            this.width = 0;
            this.height = 0;

            // D3 elements
            this.svg = null;
            this.chartGroup = null;
            this.xScale = null;
            this.yScale = null;
            this.xScaleOriginal = null;
            this.yScaleOriginal = null;
            this.line = null;
            this.area = null;

            // Zoom
            this.zoom = null;
            this.zoomRect = null;
            this.brush = null;
            this.brushGroup = null;
            this.currentTransform = d3.zoomIdentity;

            // Data
            this.currentLaneId = null;
            this.chartData = null;
            this.bgData = null;
            this.bandBoundsMap = new Map();
            this.peakDataMap = new Map();

            // Resize handling
            this.resizeObserver = null;
            this.resizeTimeout = null;

            // Legend state
            this.legendVisible = true;

            // Annotation visibility states
            this.showBoundaries = true;
            this.showLabels = true;
            this.showDetectedPeaks = true;
            this.showPeakMax = true;

            // Background visibility — default OFF so the Y-axis scales to
            // the corrected signal and small peaks are visible right away.
            // Toggle in the chart toolbar to overlay the raw background.
            this.showBackground = false;

            // 3D view state
            this.is3DMode = false;
            this.renderer3D = null;

            // Current view mode (synced via VIEW_MODE_CHANGED event)
            this.currentView = 'electropherogram';

            // X axis mode: 'position' (default) or 'mw' (molecular weight)
            this.xAxisMode = 'position';

            // Calibration data (loaded from analysis context)
            this.calibrationData = null;
            this.laneGeometry = null;

            // Colors
            this.colors = {
                profile: '#2196F3',
                background: '#E0E0E0',
                poi: '#22C55E',
                other: '#9E9E9E',
                mwReference: '#FFC107',
                orphanPeak: '#FF9800',
                matchedPeak: '#4CAF50',
                shoulderPeak: '#9C27B0',
            };

            this._init();
        }

        /**
         * Initialize the panel.
         */
        _init() {
            if (!this.container) {
                console.warn('[ChromatogramPanel] No container element');
                return;
            }

            // Find the content element (inside the panel, not the panel itself)
            this.contentElement = this.container.querySelector('.dm-panel-content');
            if (!this.contentElement) {
                console.warn('[ChromatogramPanel] No .dm-panel-content element found');
                this.contentElement = this.container;  // Fallback
            }

            // Create chart container
            this._createChart();

            // Setup event listeners
            this._setupEvents();

            // Setup resize observer (replaces window resize listener)
            this._setupResizeObserver();
        }

        /**
         * Create the D3 chart.
         */
        _createChart() {
            // Clear existing — but preserve 3D and POI containers if they exist
            const container3d = this.contentElement.querySelector('.dm-chromatogram-3d-container');
            const containerPoi = this.contentElement.querySelector('.dm-poi-purity-container');
            this.contentElement.innerHTML = '';
            if (container3d) {
                this.contentElement.appendChild(container3d);
            }
            if (containerPoi) {
                this.contentElement.appendChild(containerPoi);
            }

            // Get dimensions
            const rect = this.contentElement.getBoundingClientRect();
            this.width = rect.width - this.margin.left - this.margin.right;
            this.height = rect.height - this.margin.top - this.margin.bottom;

            if (this.width <= 0 || this.height <= 0) {
                this.width = 400;
                this.height = 300;
            }

            // Create SVG
            this.svg = d3.select(this.contentElement)
                .append('svg')
                .attr('width', this.width + this.margin.left + this.margin.right)
                .attr('height', this.height + this.margin.top + this.margin.bottom)
                .attr('class', 'dm-chromatogram-svg');

            // Create chart group
            this.chartGroup = this.svg.append('g')
                .attr('transform', `translate(${this.margin.left},${this.margin.top})`);

            // Create scales
            this.xScale = d3.scaleLinear().range([0, this.width]);
            this.yScale = d3.scaleLinear().range([this.height, 0]);

            // Create axes groups
            this.xAxisGroup = this.chartGroup.append('g')
                .attr('class', 'x-axis')
                .attr('transform', `translate(0,${this.height})`);

            this.yAxisGroup = this.chartGroup.append('g')
                .attr('class', 'y-axis');

            // Create line generator
            this.line = d3.line()
                .x(d => this.xScale(d.x))
                .y(d => this.yScale(d.y))
                .curve(d3.curveMonotoneX);

            // Create area generator (for background fill)
            this.area = d3.area()
                .x(d => this.xScale(d.x))
                .y0(this.height)
                .y1(d => this.yScale(d.y))
                .curve(d3.curveMonotoneX);

            // Add clip path
            this.svg.append('defs')
                .append('clipPath')
                .attr('id', 'chart-clip')
                .append('rect')
                .attr('width', this.width)
                .attr('height', this.height);

            // Chart content group with clip path
            this.contentGroup = this.chartGroup.append('g')
                .attr('clip-path', 'url(#chart-clip)');

            // Background path
            this.contentGroup.append('path')
                .attr('class', 'background-area')
                .attr('fill', this.colors.background)
                .attr('opacity', 0.3);

            // Main profile line
            this.contentGroup.append('path')
                .attr('class', 'profile-line')
                .attr('fill', 'none')
                .attr('stroke', this.colors.profile)
                .attr('stroke-width', 2);

            // Peak highlights group (existing bands)
            this.peakGroup = this.contentGroup.append('g')
                .attr('class', 'peak-highlights');

            // Detected peaks group (auto-detected markers)
            this.detectedPeaksGroup = this.contentGroup.append('g')
                .attr('class', 'detected-peaks');

            // Zoom overlay rect (for brush-to-zoom)
            this.zoomRect = this.chartGroup.append('rect')
                .attr('class', 'zoom-rect')
                .attr('width', this.width)
                .attr('height', this.height)
                .attr('fill', 'none')
                .attr('pointer-events', 'all');

            // Axis labels
            this.xAxisLabel = this.chartGroup.append('text')
                .attr('class', 'x-axis-label')
                .attr('x', this.width / 2)
                .attr('y', this.height + 40)
                .attr('text-anchor', 'middle')
                .text(this._getXAxisLabel());

            this.chartGroup.append('text')
                .attr('class', 'y-axis-label')
                .attr('transform', 'rotate(-90)')
                .attr('x', -this.height / 2)
                .attr('y', -45)
                .attr('text-anchor', 'middle')
                .text('Intensity');

            // Legend (in top-left corner)
            this.legendGroup = this.chartGroup.append('g')
                .attr('class', 'chart-legend')
                .attr('transform', 'translate(10, 10)');

            this._renderLegend();

            // Setup toggle buttons in panel header
            this._setupLegendToggle();

            // Add zoom behavior (brush-to-zoom)
            this._setupZoom();

            // Add placeholder text
            this._showPlaceholder('Select a lane to view its profile');
        }

        /**
         * Get X axis label based on mode.
         */
        _getXAxisLabel() {
            return this.xAxisMode === 'mw'
                ? 'Molecular Weight (kDa)'
                : 'Y Position (pixels)';
        }

        /**
         * Setup zoom behavior with brush-to-zoom.
         */
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

            // Double-click to reset zoom
            this.zoomRect.on('dblclick', () => {
                this._resetZoom();
            });

            // Wire up the HTML zoom-reset button
            const zoomResetBtn = this.container.querySelector('#zoom-reset-btn');
            if (zoomResetBtn) {
                zoomResetBtn.addEventListener('click', () => {
                    this._resetZoom();
                });
            }

            // Add zoom hint text
            if (ChartUtils) {
                ChartUtils.addZoomHintText(this.chartGroup, this.width, this.height);
            }
        }

        /**
         * Handle brush end event for brush-to-zoom.
         */
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

        /**
         * Reset zoom to identity.
         */
        _resetZoom() {
            if (this.zoomRect && this.zoom) {
                this.zoomRect.transition()
                    .duration(300)
                    .call(this.zoom.transform, d3.zoomIdentity);
            }
        }

        /**
         * Handle zoom event.
         */
        _onZoom(event) {
            this.currentTransform = event.transform;

            const newXScale = event.transform.rescaleX(this.xScaleOriginal || this.xScale);
            // Keep Y scale fixed at base — only zoom X axis
            const yScale = this.yScaleOriginal || this.yScale;

            // Update X axis only (Y stays fixed)
            this.xAxisGroup.call(
                this._isLogScale(newXScale)
                    ? d3.axisBottom(newXScale).ticks(8, '.0f').tickFormat(d => `${d}`)
                    : d3.axisBottom(newXScale)
            );

            // Update line using fixed Y scale
            const useMWMode = this.xAxisMode === 'mw';
            const newLine = d3.line()
                .x(d => newXScale(d.x))
                .y(d => yScale(d.y))
                .curve(d3.curveMonotoneX)
                .defined(d => useMWMode ? (d.x > 0 && !isNaN(newXScale(d.x))) : true);

            this.contentGroup.select('.profile-line')
                .attr('d', newLine(this.chartData || []));

            // Update area with fixed Y scale
            const newArea = d3.area()
                .x(d => newXScale(d.x))
                .y0(this.height)
                .y1(d => yScale(d.y))
                .curve(d3.curveMonotoneX)
                .defined(d => useMWMode ? (d.x > 0 && !isNaN(newXScale(d.x))) : true);

            this.contentGroup.select('.background-area')
                .attr('d', newArea(this.bgData || []));

            // Update peaks with fixed Y scale
            this._updatePeakPositions(newXScale, yScale);

            // Update detected peaks with fixed Y scale
            this._updateDetectedPeakPositions(newXScale, yScale);

            this.eventBus.emit(Events.ZOOM_CHANGED, { transform: event.transform });
        }

        /**
         * Check if a scale is a log scale.
         */
        _isLogScale(scale) {
            // d3 log scales have a .base() method
            return typeof scale.base === 'function';
        }

        /**
         * Setup event listeners.
         */
        _setupEvents() {
            // Lane selected
            this.eventBus.on(Events.LANE_SELECTED, (data) => {
                if (data.laneId) {
                    this._loadLaneProfile(data.laneId);
                } else {
                    this._clear();
                }
            });

            // Profile loaded
            this.eventBus.on(Events.PROFILE_LOADED, (data) => {
                if (data.laneId === this.currentLaneId) {
                    if (this.is3DMode && this.renderer3D) {
                        const bands = this._getBandsForCurrentLane();
                        this.renderer3D.render(data.profile, bands);
                    } else {
                        this._renderProfile(data.profile);
                    }
                }
            });

            // Data updated
            this.eventBus.on(Events.DATA_UPDATED, (data) => {
                if (this.currentLaneId) {
                    this._loadLaneProfile(this.currentLaneId);
                }
            });

            // Band selected - highlight on chart
            this.eventBus.on(Events.BAND_SELECTED, (data) => {
                this._highlightSelectedBand(data.bandId);
            });

            // Peaks detected - render markers
            this.eventBus.on(Events.PEAKS_DETECTED, (data) => {
                if (data.laneId === this.currentLaneId) {
                    this._renderDetectedPeaks(data.peaks);
                }
            });

            // Bands created - refresh to show new bands
            this.eventBus.on(Events.BANDS_CREATED, () => {
                if (this.currentLaneId) {
                    this._renderPeaks();
                    // Clear detected peaks markers since they're now bands
                    this._clearDetectedPeaks();
                }
            });

            // View mode changed (from switchView in densitometry.html)
            this.eventBus.on(Events.VIEW_MODE_CHANGED, (data) => {
                this.currentView = data.view;
            });
        }

        /**
         * Load lane profile.
         */
        _loadLaneProfile(laneId) {
            this.currentLaneId = laneId;

            // Load calibration data for MW axis mode
            this._loadCalibrationData(laneId);

            // Check if profile is cached
            const profile = this.state.getProfile(laneId);
            if (profile) {
                if (this.is3DMode && this.renderer3D) {
                    // In 3D mode: only update terrain, skip 2D render
                    const bands = this._getBandsForCurrentLane();
                    this.renderer3D.render(profile, bands);
                } else {
                    // 2D mode: render the D3.js chart
                    this._renderProfile(profile);
                }
            } else {
                if (!this.is3DMode) {
                    this._showPlaceholder('Loading profile...');
                }
            }
        }

        /**
         * Load calibration data for the current lane's analysis.
         */
        _loadCalibrationData(laneId) {
            const lane = this.state.getLane(laneId);
            if (!lane) return;

            // Get lane geometry from bbox
            const bbox = lane.bbox || {};
            this.laneGeometry = {
                top: bbox.y || lane.y || 0,
                bottom: (bbox.y || lane.y || 0) + (bbox.height || lane.height || 0),
            };

            // Calibration data: check lane, then analysis-level (from state)
            if (lane.calibration) {
                this.calibrationData = lane.calibration;
            } else if (lane.analysis_calibration) {
                this.calibrationData = lane.analysis_calibration;
            } else if (this.state.calibrationData) {
                this.calibrationData = this.state.calibrationData;
            } else {
                this.calibrationData = null;
            }
        }

        /**
         * Render the profile chart.
         */
        _renderProfile(profile) {
            if (!profile || !profile.y_positions || profile.y_positions.length === 0) {
                this._showPlaceholder('No profile data available');
                return;
            }

            // Hide placeholder
            this._hidePlaceholder();

            const useMWMode = this.xAxisMode === 'mw' && this.calibrationData && this.laneGeometry && MWUtils;

            // Build chart data — always include yPos for peak matching
            // In MW mode, x = MW (kDa); in position mode, x = y_position (px)
            if (useMWMode) {
                this.chartData = [];
                for (let i = 0; i < profile.y_positions.length; i++) {
                    const y = profile.y_positions[i];
                    const mw = MWUtils.positionToMW(y, this.laneGeometry, this.calibrationData);
                    const intensity = profile.intensities[i];
                    if (mw !== null && isFinite(mw) && mw > 0) {
                        this.chartData.push({
                            x: mw,
                            y: intensity,
                            yPos: y,
                            raw: profile.raw_intensities ? profile.raw_intensities[i] : null,
                            mw: mw,
                        });
                    }
                }
                // Sort by MW descending → screen-x ascending (required for curveMonotoneX)
                this.chartData.sort((a, b) => b.x - a.x);
            } else {
                this.chartData = profile.y_positions.map((y, i) => ({
                    x: y,
                    y: profile.intensities[i],
                    yPos: y,
                    raw: profile.raw_intensities ? profile.raw_intensities[i] : null,
                    mw: profile.mw_values ? profile.mw_values[i] : null,
                }));
            }

            // Background data
            if (profile.background) {
                this.bgData = [];
                for (let i = 0; i < profile.y_positions.length; i++) {
                    const y = profile.y_positions[i];
                    const xVal = useMWMode ? MWUtils.positionToMW(y, this.laneGeometry, this.calibrationData) : y;
                    if (xVal !== null && isFinite(xVal) && xVal > 0) {
                        this.bgData.push({ x: xVal, y: profile.background[i] || 0, yPos: y });
                    }
                }
                if (useMWMode) {
                    this.bgData.sort((a, b) => b.x - a.x);
                }
            } else {
                this.bgData = [];
            }

            // Update scales
            const xExtent = d3.extent(this.chartData, d => d.x);

            // Calculate yMax — include background only when visible
            let yMax = d3.max(this.chartData, d => d.y);
            if (this.showBackground && this.bgData && this.bgData.length > 0) {
                const bgMax = d3.max(this.bgData, d => d.y);
                yMax = Math.max(yMax, bgMax);
            }
            yMax *= 1.1;  // Add 10% padding

            if (useMWMode) {
                // Data is sorted MW descending; xExtent[0] = smallest MW, xExtent[1] = largest MW
                const minMW = Math.max(5, xExtent[0] * 0.9);
                const maxMW = xExtent[1] * 1.1;
                this.xScale = d3.scaleLog()
                    .domain([maxMW, minMW])  // High MW on left, low MW on right
                    .range([0, this.width]);
            } else {
                this.xScale = d3.scaleLinear()
                    .domain(xExtent)
                    .range([0, this.width]);
            }

            this.yScale.domain([0, yMax]);

            // Store original scales for zoom
            this.xScaleOriginal = this.xScale.copy();
            this.yScaleOriginal = this.yScale.copy();

            // Reset zoom
            this.currentTransform = d3.zoomIdentity;
            if (this.zoomRect && this.zoom) {
                this.zoomRect.call(this.zoom.transform, d3.zoomIdentity);
            }

            // Update line/area generators
            const xScaleRef = this.xScale;
            this.line = d3.line()
                .x(d => xScaleRef(d.x))
                .y(d => this.yScale(d.y))
                .curve(d3.curveMonotoneX)
                .defined(d => isFinite(d.x) && d.x > 0 && isFinite(xScaleRef(d.x)));

            this.area = d3.area()
                .x(d => xScaleRef(d.x))
                .y0(this.height)
                .y1(d => this.yScale(d.y))
                .curve(d3.curveMonotoneX)
                .defined(d => isFinite(d.x) && d.x > 0 && isFinite(xScaleRef(d.x)));

            // Update axes
            if (useMWMode) {
                this.xAxisGroup.call(
                    d3.axisBottom(this.xScale)
                        .ticks(8, '.0f')
                        .tickFormat(d => `${d}`)
                );
            } else {
                this.xAxisGroup.call(d3.axisBottom(this.xScale));
            }
            this.yAxisGroup.call(d3.axisLeft(this.yScale));

            // Update axis label
            if (this.xAxisLabel) {
                this.xAxisLabel.text(this._getXAxisLabel());
            }

            // Update background area (hidden when showBackground is false)
            this.contentGroup.select('.background-area')
                .datum(this.bgData)
                .attr('d', this.area)
                .attr('display', this.showBackground ? 'block' : 'none');

            // Update profile line
            this.contentGroup.select('.profile-line')
                .datum(this.chartData)
                .attr('d', this.line);

            // Render peaks
            this._renderPeaks();

            this.eventBus.emit(Events.CHART_READY, { laneId: this.currentLaneId });
        }

        /**
         * Render peak highlights with boundaries, labels, and annotations.
         * Uses ChartUtils for shared rendering functions.
         */
        _renderPeaks() {
            const bands = this.state.getBandsForLane(this.currentLaneId);
            const defs = this.svg.select('defs');

            // Clear existing peaks and gradients
            this.peakGroup.selectAll('*').remove();
            defs.selectAll('.peak-gradient').remove();
            this.bandBoundsMap.clear();
            this.peakDataMap.clear();

            if (!bands || bands.length === 0) return;

            const useMWMode = this.xAxisMode === 'mw' && this.calibrationData && this.laneGeometry && MWUtils;

            // Render each band
            bands.forEach(band => {
                const color = this._getBandColor(band.band_type);
                const peakY = band.densitometry?.peak_center_y || band.position_y;

                // Always find closest data point by Y position (stable across modes)
                const dataPoint = ChartUtils
                    ? ChartUtils.findClosestDataPoint(this.chartData, peakY, 10, 'yPos')
                    : this.chartData.find(d => Math.abs(d.yPos - peakY) < 10);
                if (!dataPoint) return;

                // Store peak data for zoom updates
                this.peakDataMap.set(band.id, { x: dataPoint.x, y: dataPoint.y });

                // Integration boundaries == band bbox edges. The server-side
                // densitometry integrator uses bbox_y / bbox_y + bbox_height
                // as the integration region, so the dashed lines drawn here
                // now reflect what is actually integrated (was ±3σ before
                // the May 2026 fix — that was misleading vs the real area).
                const bounds = ChartUtils
                    ? ChartUtils.calculateBandBounds(band)
                    : {
                        peakY,
                        leftBound: band.bbox_y ?? peakY - 20,
                        rightBound: (band.bbox_y != null && band.bbox_height != null)
                            ? band.bbox_y + band.bbox_height
                            : peakY + 20,
                        sigma: band.densitometry?.sigma ?? null,
                    };

                // In MW mode, convert bounds to MW
                let renderBounds;
                if (useMWMode) {
                    const leftMW = MWUtils.positionToMW(bounds.leftBound, this.laneGeometry, this.calibrationData);
                    const rightMW = MWUtils.positionToMW(bounds.rightBound, this.laneGeometry, this.calibrationData);
                    if (leftMW && rightMW) {
                        renderBounds = { leftBound: Math.max(leftMW, rightMW), rightBound: Math.min(leftMW, rightMW) };
                    } else {
                        renderBounds = { leftBound: dataPoint.x * 1.1, rightBound: dataPoint.x * 0.9 };
                    }
                } else {
                    renderBounds = { leftBound: bounds.leftBound, rightBound: bounds.rightBound };
                }

                this.bandBoundsMap.set(band.id, renderBounds);

                const onClick = () => this._onPeakClick(band.id);

                // 1. Draw boundary lines (if enabled)
                if (this.showBoundaries && ChartUtils) {
                    ChartUtils.renderPeakBoundaries(
                        this.peakGroup, this.xScale, renderBounds, color, this.height,
                        { bandId: band.id, onClick }
                    );
                } else if (this.showBoundaries) {
                    // Fallback without ChartUtils
                    this._renderBoundaryLinesFallback(band, renderBounds, color);
                }

                // 2. Draw peak area with gradient fill
                if (band.densitometry && band.densitometry.corrected_area > 0 && ChartUtils) {
                    ChartUtils.renderPeakAreaFill(
                        this.peakGroup, defs, this.xScale, this.yScale,
                        this.chartData, renderBounds, color, this.height,
                        { bandId: band.id, onClick }
                    );
                } else if (band.densitometry && band.densitometry.corrected_area > 0) {
                    this._renderPeakAreaFallback(band, renderBounds, color, defs);
                }

                // 3a. Draw peak-maximum marker — vertical red line + ▼ on top
                // axis, the exact X position used to read MW off the
                // calibration curve. Distinct from the bbox boundaries above.
                if (this.showPeakMax && ChartUtils && ChartUtils.renderPeakMaxMarker) {
                    ChartUtils.renderPeakMaxMarker(
                        this.peakGroup, this.xScale, dataPoint.x, this.height,
                        { bandId: band.id, onClick }
                    );
                }

                // 3b. Draw peak marker (circle on the curve at peak intensity)
                if (ChartUtils) {
                    ChartUtils.renderPeakMarker(
                        this.peakGroup, this.xScale, this.yScale, dataPoint, band, color,
                        {
                            onClick,
                            onMouseEnter: (event) => this._onPeakHover(event, band),
                            onMouseLeave: () => this._hideTooltip(),
                        }
                    );
                } else {
                    // Fallback
                    this.peakGroup.append('circle')
                        .attr('class', 'peak-marker')
                        .attr('cx', this.xScale(dataPoint.x))
                        .attr('cy', this.yScale(dataPoint.y))
                        .attr('r', 5)
                        .attr('fill', color)
                        .attr('stroke', '#fff')
                        .attr('stroke-width', 2)
                        .attr('data-band-id', band.id)
                        .style('cursor', 'pointer')
                        .on('click', onClick)
                        .on('mouseenter', (event) => this._onPeakHover(event, band))
                        .on('mouseleave', () => this._hideTooltip());
                }

                // 4. Add labels (if enabled)
                if (this.showLabels) {
                    // MW label above peak
                    if (ChartUtils) {
                        ChartUtils.renderMWLabel(
                            this.peakGroup, this.xScale, this.yScale, dataPoint, band, color,
                            { bandId: band.id, onClick }
                        );
                    } else if (band.estimated_mw_kda) {
                        this.peakGroup.append('text')
                            .attr('class', 'peak-label peak-mw-label')
                            .attr('x', this.xScale(dataPoint.x))
                            .attr('y', this.yScale(dataPoint.y) - 15)
                            .attr('text-anchor', 'middle')
                            .attr('font-size', '10px')
                            .attr('font-weight', 'bold')
                            .attr('fill', color)
                            .attr('data-band-id', band.id)
                            .style('cursor', 'pointer')
                            .on('click', onClick)
                            .text(`${band.estimated_mw_kda.toFixed(0)} kDa`);
                    }

                    // Band type indicator
                    const typeSymbols = { 'POI': '\u2605', 'MW_REFERENCE': 'M', 'OTHER': '' };
                    const symbol = typeSymbols[band.band_type];
                    if (symbol) {
                        this.peakGroup.append('text')
                            .attr('class', 'peak-label band-type-badge')
                            .attr('x', this.xScale(dataPoint.x) + 10)
                            .attr('y', this.yScale(dataPoint.y) + 4)
                            .attr('font-size', '11px')
                            .attr('fill', color)
                            .attr('data-band-id', band.id)
                            .style('cursor', 'pointer')
                            .on('click', onClick)
                            .text(symbol);
                    }

                    // Percentage label below x-axis
                    if (band.densitometry?.relative_percent_lane != null) {
                        this.peakGroup.append('text')
                            .attr('class', 'peak-label peak-percent-label')
                            .attr('x', this.xScale(dataPoint.x))
                            .attr('y', this.height + 25)
                            .attr('text-anchor', 'middle')
                            .attr('font-size', '9px')
                            .attr('fill', '#666')
                            .attr('data-band-id', band.id)
                            .style('cursor', 'pointer')
                            .on('click', onClick)
                            .text(`${band.densitometry.relative_percent_lane.toFixed(1)}%`);
                    }
                }
            });
        }

        /**
         * Fallback boundary rendering without ChartUtils.
         */
        _renderBoundaryLinesFallback(band, bounds, color) {
            ['left', 'right'].forEach(side => {
                const boundX = side === 'left' ? bounds.leftBound : bounds.rightBound;
                this.peakGroup.append('line')
                    .attr('class', `band-boundary band-boundary-${side}`)
                    .attr('x1', this.xScale(boundX))
                    .attr('y1', 0)
                    .attr('x2', this.xScale(boundX))
                    .attr('y2', this.height)
                    .attr('stroke', color)
                    .attr('stroke-width', 1)
                    .attr('stroke-dasharray', '4,2')
                    .attr('opacity', 0.5)
                    .attr('data-band-id', band.id)
                    .attr('data-bound', side)
                    .style('cursor', 'pointer')
                    .on('click', () => this._onPeakClick(band.id));
            });
        }

        /**
         * Fallback peak area rendering without ChartUtils.
         */
        _renderPeakAreaFallback(band, bounds, color, defs) {
            const peakData = this.chartData.filter(
                d => d.x >= Math.min(bounds.leftBound, bounds.rightBound) &&
                     d.x <= Math.max(bounds.leftBound, bounds.rightBound)
            );
            if (peakData.length === 0) return;

            const gradientId = `peak-gradient-${band.id}`;
            const gradient = defs
                .append('linearGradient')
                .attr('class', 'peak-gradient')
                .attr('id', gradientId)
                .attr('x1', '0%').attr('y1', '100%')
                .attr('x2', '0%').attr('y2', '0%');
            gradient.append('stop').attr('offset', '0%').attr('stop-color', color).attr('stop-opacity', 0.05);
            gradient.append('stop').attr('offset', '100%').attr('stop-color', color).attr('stop-opacity', 0.4);

            const peakArea = d3.area()
                .x(d => this.xScale(d.x)).y0(this.height).y1(d => this.yScale(d.y)).curve(d3.curveMonotoneX);

            this.peakGroup.append('path')
                .datum(peakData).attr('class', 'peak-area')
                .attr('d', peakArea).attr('fill', `url(#${gradientId})`)
                .attr('data-band-id', band.id).style('cursor', 'pointer')
                .on('click', () => this._onPeakClick(band.id));
        }

        /**
         * Get color for band type.
         */
        _getBandColor(bandType) {
            if (ChartUtils) {
                return ChartUtils.getBandColor(bandType, this.colors);
            }
            switch (bandType) {
                case 'POI': return this.colors.poi;
                case 'MW_REFERENCE': return this.colors.mwReference;
                default: return this.colors.other;
            }
        }

        /**
         * Render the chart legend.
         */
        _renderLegend() {
            if (!this.legendGroup) return;

            this.legendGroup.selectAll('*').remove();

            // Set visibility based on state
            this.legendGroup.attr('display', this.legendVisible ? 'block' : 'none');

            if (!this.legendVisible) return;

            const items = [
                { color: this.colors.profile, label: 'Profile', type: 'line' },
                { color: this.colors.background, label: 'Background', opacity: 0.3 },
                { color: this.colors.poi, label: 'POI' },
                { color: this.colors.mwReference, label: 'MW Ref' },
                { color: this.colors.other, label: 'Other' },
                { color: '#666', label: 'Integration (bbox)', type: 'dashed' },
                { color: '#dc2626', label: 'Peak max (MW)', type: 'peakmax' },
            ];

            // Background rect for readability — sized to fit all items.
            this.legendGroup.append('rect')
                .attr('x', -8)
                .attr('y', -8)
                .attr('width', 140)
                .attr('height', items.length * 18 + 12)
                .attr('fill', 'rgba(255,255,255,0.9)')
                .attr('stroke', '#ddd')
                .attr('stroke-width', 1)
                .attr('rx', 4);

            items.forEach((item, i) => {
                const y = i * 18;

                if (item.type === 'line') {
                    // Solid line swatch for profile
                    this.legendGroup.append('line')
                        .attr('x1', 0)
                        .attr('y1', y + 7)
                        .attr('x2', 14)
                        .attr('y2', y + 7)
                        .attr('stroke', item.color)
                        .attr('stroke-width', 2);
                } else if (item.type === 'dashed') {
                    // Dashed line swatch for boundaries
                    this.legendGroup.append('line')
                        .attr('x1', 0)
                        .attr('y1', y + 7)
                        .attr('x2', 14)
                        .attr('y2', y + 7)
                        .attr('stroke', item.color)
                        .attr('stroke-width', 1.5)
                        .attr('stroke-dasharray', '3,2');
                } else if (item.type === 'peakmax') {
                    // Dashed vertical line + ▼ glyph swatch — matches the
                    // dashed rendering in renderPeakMaxMarker so the legend
                    // mirrors what's drawn on the chart.
                    this.legendGroup.append('line')
                        .attr('x1', 7)
                        .attr('y1', y + 2)
                        .attr('x2', 7)
                        .attr('y2', y + 14)
                        .attr('stroke', item.color)
                        .attr('stroke-width', 1.25)
                        .attr('stroke-dasharray', '3,3')
                        .attr('opacity', 0.7);
                    this.legendGroup.append('path')
                        .attr('d', 'M -4,0 L 4,0 L 0,5 Z')
                        .attr('transform', `translate(7, ${y + 2})`)
                        .attr('fill', item.color);
                } else {
                    // Rectangle swatch for areas/peaks
                    this.legendGroup.append('rect')
                        .attr('x', 0)
                        .attr('y', y)
                        .attr('width', 14)
                        .attr('height', 14)
                        .attr('fill', item.color)
                        .attr('opacity', item.opacity || 1)
                        .attr('rx', 2);
                }

                // Label
                this.legendGroup.append('text')
                    .attr('x', 20)
                    .attr('y', y + 11)
                    .attr('font-size', '11px')
                    .attr('fill', '#333')
                    .text(item.label);
            });
        }

        /**
         * Setup toggle buttons in panel header (legend, boundaries, labels, MW/Pos).
         */
        _setupLegendToggle() {
            const header = this.container.querySelector('.dm-panel-header');
            if (!header) return;

            // Check if actions container already exists
            let actions = header.querySelector('.dm-panel-actions');
            if (!actions) {
                actions = document.createElement('div');
                actions.className = 'dm-panel-actions';
                header.appendChild(actions);
            }

            // Remove previously created toggle buttons to avoid duplication on re-init
            actions.querySelectorAll('.dm-panel-btn[id$="-toggle-btn"]').forEach(b => b.remove());

            // Has calibration data available?
            const hasCal = this.calibrationData || this.state?.hasCalibration?.();

            // Create toggle buttons (in order: MW/Pos, background, legend, boundaries, labels)
            const toggles = [
                {
                    id: 'mw-toggle-btn',
                    icon: 'bi-rulers',
                    title: 'MW Axis Mode',
                    active: this.xAxisMode === 'mw',
                    hidden: false, // Show always, disable if no calibration
                    handler: () => this._toggleMWMode()
                },
                {
                    id: 'bg-toggle-btn',
                    icon: 'bi-layers-half',
                    title: 'Toggle Background',
                    active: this.showBackground,
                    handler: () => this._toggleBackground()
                },
                {
                    id: 'legend-toggle-btn',
                    icon: 'bi-list-ul',
                    title: 'Toggle Legend',
                    active: this.legendVisible,
                    handler: () => this._toggleLegend()
                },
                {
                    id: 'boundaries-toggle-btn',
                    icon: 'bi-border-left',
                    title: 'Toggle Integration Bounds (bbox)',
                    active: this.showBoundaries,
                    handler: () => this._toggleBoundaries()
                },
                {
                    id: 'peakmax-toggle-btn',
                    icon: 'bi-caret-down-fill',
                    title: 'Toggle Peak Max (MW)',
                    active: this.showPeakMax,
                    handler: () => this._togglePeakMax()
                },
                {
                    id: 'labels-toggle-btn',
                    icon: 'bi-fonts',
                    title: 'Toggle Labels',
                    active: this.showLabels,
                    handler: () => this._toggleLabels()
                }
            ];

            // Get reference point for insertion (before existing direct-child buttons like zoom reset)
            const existingBtn = actions.querySelector(':scope > button');

            toggles.forEach(toggle => {
                if (toggle.hidden) return;

                const btn = document.createElement('button');
                btn.className = `dm-panel-btn ${toggle.active ? 'active' : ''}`;
                btn.id = toggle.id;
                btn.setAttribute('data-tooltip', toggle.title);
                btn.innerHTML = `<i class="bi ${toggle.icon}"></i>`;
                btn.addEventListener('click', toggle.handler);

                if (existingBtn) {
                    actions.insertBefore(btn, existingBtn);
                } else {
                    actions.appendChild(btn);
                }
            });
        }

        /**
         * Toggle MW axis mode.
         */
        _toggleMWMode() {
            if (!this.calibrationData && !this.state?.hasCalibration?.()) {
                console.warn('[ChromatogramPanel] No calibration data available for MW mode');
                return;
            }

            this.xAxisMode = this.xAxisMode === 'mw' ? 'position' : 'mw';

            // Update button state
            const toggleBtn = this.container.querySelector('#mw-toggle-btn');
            if (toggleBtn) {
                toggleBtn.classList.toggle('active', this.xAxisMode === 'mw');
                toggleBtn.setAttribute('data-tooltip',
                    this.xAxisMode === 'mw' ? 'Switch to Position' : 'Switch to MW');
            }

            // Re-render with new axis mode
            if (this.currentLaneId) {
                const profile = this.state.getProfile(this.currentLaneId);
                if (profile) {
                    this._renderProfile(profile);
                }
            }
        }

        /**
         * Toggle background visibility and rescale Y-axis accordingly.
         * When hidden, Y-axis scales to corrected signal only → better visibility.
         */
        _toggleBackground() {
            this.showBackground = !this.showBackground;

            // Update button state
            const toggleBtn = this.container.querySelector('#bg-toggle-btn');
            if (toggleBtn) {
                toggleBtn.classList.toggle('active', this.showBackground);
                toggleBtn.setAttribute('data-tooltip',
                    this.showBackground ? 'Hide Background' : 'Show Background');
            }

            // Re-render to recalculate Y-axis scale
            if (this.currentLaneId) {
                const profile = this.state.getProfile(this.currentLaneId);
                if (profile) {
                    this._renderProfile(profile);
                }
            }
        }

        /**
         * Toggle legend visibility.
         */
        _toggleLegend() {
            this.legendVisible = !this.legendVisible;

            // Update button state
            const toggleBtn = this.container.querySelector('#legend-toggle-btn');
            if (toggleBtn) {
                toggleBtn.classList.toggle('active', this.legendVisible);
                toggleBtn.setAttribute('data-tooltip', this.legendVisible ? 'Hide Legend' : 'Show Legend');
            }

            // Update legend display
            if (this.legendGroup) {
                this.legendGroup.attr('display', this.legendVisible ? 'block' : 'none');
            }
        }

        /**
         * Toggle band boundary lines visibility.
         */
        _toggleBoundaries() {
            this.showBoundaries = !this.showBoundaries;

            // Update button state
            const toggleBtn = this.container.querySelector('#boundaries-toggle-btn');
            if (toggleBtn) {
                toggleBtn.classList.toggle('active', this.showBoundaries);
                toggleBtn.setAttribute('data-tooltip', this.showBoundaries ? 'Hide Boundaries' : 'Show Boundaries');
            }

            // Re-render peaks to apply change
            if (this.currentLaneId) {
                this._renderPeaks();
            }
        }

        /**
         * Toggle the peak-maximum marker (red dashed line + ▼).
         */
        _togglePeakMax() {
            this.showPeakMax = !this.showPeakMax;

            const toggleBtn = this.container.querySelector('#peakmax-toggle-btn');
            if (toggleBtn) {
                toggleBtn.classList.toggle('active', this.showPeakMax);
                toggleBtn.setAttribute(
                    'data-tooltip',
                    this.showPeakMax ? 'Hide Peak Max (MW)' : 'Show Peak Max (MW)'
                );
            }

            if (this.currentLaneId) {
                this._renderPeaks();
            }
        }

        /**
         * Toggle labels visibility (MW, %, type badges).
         */
        _toggleLabels() {
            this.showLabels = !this.showLabels;

            // Update button state
            const toggleBtn = this.container.querySelector('#labels-toggle-btn');
            if (toggleBtn) {
                toggleBtn.classList.toggle('active', this.showLabels);
                toggleBtn.setAttribute('data-tooltip', this.showLabels ? 'Hide Labels' : 'Show Labels');
            }

            // Re-render peaks to apply change
            if (this.currentLaneId) {
                this._renderPeaks();
            }
        }

        /**
         * Toggle 3D terrain view.
         */
        _toggle3DView() {
            this.is3DMode = !this.is3DMode;

            const btn = this.container.querySelector('#view-3d-toggle-btn');
            if (btn) {
                btn.classList.toggle('active', this.is3DMode);
                btn.setAttribute('data-tooltip', this.is3DMode ? 'Switch to 2D' : '3D Terrain View');
            }

            // Ensure 3D container exists (created dynamically since panel content is rebuilt by JS)
            this._ensure3DContainer();

            if (this.is3DMode) {
                this._enforce3DVisibility(true);

                // Lazy-init 3D renderer
                const container3d = this.contentElement?.querySelector('.dm-chromatogram-3d-container');
                if (!this.renderer3D && window.Densitometry?.Chromatogram3DRenderer && container3d) {
                    this.renderer3D = new window.Densitometry.Chromatogram3DRenderer({
                        container: container3d,
                    });
                    this.renderer3D.init();
                }

                // Render current profile in 3D
                if (this.renderer3D && this.currentLaneId) {
                    const profile = this.state.getProfile(this.currentLaneId);
                    const bands = this._getBandsForCurrentLane();
                    if (profile) {
                        this.renderer3D.render(profile, bands);
                    }
                } else if (!window.Densitometry?.Chromatogram3DRenderer) {
                    console.warn('[ChromatogramPanel] 3D renderer not loaded yet — Three.js module may still be loading');
                }
            } else {
                this._enforce3DVisibility(false);

                // Only rebuild 2D chart if electropherogram is the active view
                if (this.currentView === 'electropherogram') {
                    setTimeout(() => {
                        this._createChart();
                        if (this.currentLaneId) {
                            const profile = this.state.getProfile(this.currentLaneId);
                            if (profile) {
                                this._renderProfile(profile);
                            }
                        }
                    }, 50);
                }
            }
        }

        /**
         * Ensure the 3D container div exists inside panel content.
         */
        _ensure3DContainer() {
            if (!this.contentElement) return null;
            let container3d = this.contentElement.querySelector('.dm-chromatogram-3d-container');
            if (!container3d) {
                container3d = document.createElement('div');
                container3d.className = 'dm-chromatogram-3d-container';
                container3d.id = 'chromatogram-3d-container';
                container3d.style.display = 'none';
                this.contentElement.appendChild(container3d);
            }
            return container3d;
        }

        /**
         * Enforce correct visibility of 2D vs 3D elements.
         * @param {boolean} show3D - true to show 3D and hide 2D, false for reverse
         */
        _enforce3DVisibility(show3D) {
            // Target the chromatogram SVG specifically (not the POI SVG inside its container)
            const svgEl = this.contentElement?.querySelector('svg.dm-chromatogram-svg') || this.svg?.node();
            const container3d = this.contentElement?.querySelector('.dm-chromatogram-3d-container');
            const containerPoi = this.contentElement?.querySelector('.dm-poi-purity-container');
            const placeholder = this.contentElement?.querySelector('.dm-chart-placeholder');
            const legendPanel = this.contentElement?.querySelector('.dm-chart-legend-panel');
            const zoomControls = this.contentElement?.querySelector('.dm-zoom-controls');

            if (show3D) {
                if (svgEl) svgEl.style.display = 'none';
                if (containerPoi) containerPoi.style.display = 'none';
                if (placeholder) placeholder.style.display = 'none';
                if (legendPanel) legendPanel.style.display = 'none';
                if (zoomControls) zoomControls.style.display = 'none';
                if (container3d) container3d.style.display = 'block';
            } else {
                // Don't blindly show SVG — respect the current view mode
                const showSvg = this.currentView === 'electropherogram';
                const showPoi = this.currentView === 'poi-purity';
                if (svgEl) svgEl.style.display = showSvg ? 'block' : 'none';
                if (containerPoi) containerPoi.style.display = showPoi ? 'flex' : 'none';
                if (legendPanel) legendPanel.style.display = '';
                if (zoomControls) zoomControls.style.display = '';
                if (container3d) container3d.style.display = 'none';
            }
        }

        /**
         * Get bands for the current lane (helper for 3D view).
         */
        _getBandsForCurrentLane() {
            if (!this.currentLaneId || !this.state) return [];
            const allBands = Array.from(this.state.bands?.values() || []);
            return allBands.filter(b => b.lane === this.currentLaneId || b.lane_id === this.currentLaneId);
        }

        /**
         * Handle peak click.
         */
        _onPeakClick(bandId) {
            this.state.selectBand(bandId);
            this.eventBus.emit(Events.PEAK_CLICKED, { bandId });
        }

        /**
         * Handle peak hover.
         */
        _onPeakHover(event, band) {
            const tooltip = ChartUtils
                ? ChartUtils.getOrCreateTooltip()
                : this._getTooltip();

            let content = `<strong>${band.band_type}</strong><br>`;
            content += `Position: ${band.position_y}px<br>`;

            if (band.estimated_mw_kda) {
                content += `MW: ${band.estimated_mw_kda.toFixed(1)} kDa<br>`;
            }

            if (band.densitometry) {
                content += `Area: ${band.densitometry.corrected_area.toFixed(0)}<br>`;
                if (band.densitometry.relative_percent_lane) {
                    content += `% Lane: ${band.densitometry.relative_percent_lane.toFixed(1)}%`;
                }
            }

            if (ChartUtils) {
                ChartUtils.showTooltip(tooltip, content, event);
            } else {
                tooltip.innerHTML = content;
                tooltip.style.left = `${event.pageX + 10}px`;
                tooltip.style.top = `${event.pageY - 10}px`;
                tooltip.style.display = 'block';
            }

            this.eventBus.emit(Events.PEAK_HOVERED, { bandId: band.id, band });
        }

        /**
         * Hide tooltip.
         */
        _hideTooltip() {
            const tooltip = ChartUtils
                ? ChartUtils.getOrCreateTooltip()
                : this._getTooltip();
            if (ChartUtils) {
                ChartUtils.hideTooltip(tooltip);
            } else {
                tooltip.style.display = 'none';
            }
        }

        /**
         * Get or create tooltip element (fallback without ChartUtils).
         */
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

        /**
         * Highlight selected band on chart.
         * Uses ChartUtils.highlightBand for shared highlight logic.
         */
        _highlightSelectedBand(bandId) {
            if (ChartUtils) {
                ChartUtils.highlightBand(this.peakGroup, bandId, {
                    highlightArea: true,
                    highlightBoundaries: true,
                });
            } else {
                // Fallback
                this.peakGroup.selectAll('.peak-area')
                    .style('opacity', null)
                    .style('stroke', null)
                    .style('stroke-width', null);
                this.peakGroup.selectAll('.peak-marker')
                    .attr('r', 5)
                    .attr('stroke-width', 2);
                this.peakGroup.selectAll('.band-boundary')
                    .style('opacity', 0.5)
                    .style('stroke-width', 1);

                if (bandId) {
                    this.peakGroup.selectAll(`.peak-area[data-band-id="${bandId}"]`)
                        .style('opacity', 1)
                        .style('stroke', '#2196F3')
                        .style('stroke-width', 2);
                    this.peakGroup.selectAll(`.peak-marker[data-band-id="${bandId}"]`)
                        .attr('r', 8)
                        .attr('stroke-width', 3);
                    this.peakGroup.selectAll(`.band-boundary[data-band-id="${bandId}"]`)
                        .style('opacity', 1)
                        .style('stroke-width', 2);
                }
            }

            // Also highlight in 3D view if active
            if (this.is3DMode && this.renderer3D && bandId) {
                this.renderer3D.highlightBand(bandId);
            }
        }

        /**
         * Update peak positions during zoom.
         */
        _updatePeakPositions(xScale, yScale) {
            const bands = this.state.getBandsForLane(this.currentLaneId);
            if (!bands || !this.chartData) return;

            // Use ChartUtils for markers and MW labels
            if (ChartUtils) {
                ChartUtils.updatePeakPositions(this.peakGroup, this.peakDataMap, xScale, yScale);
                ChartUtils.updateBoundaryPositions(this.peakGroup, xScale, this.bandBoundsMap);
                ChartUtils.updatePeakAreaPositions(this.peakGroup, xScale, yScale, this.chartData, this.bandBoundsMap, this.height);
            } else {
                // Fallback: update manually
                this._updatePeakPositionsFallback(xScale, yScale, bands);
            }

            // Update type badge and percent label (these are densitometry-specific)
            const self = this;
            bands.forEach(band => {
                const peakData = self.peakDataMap.get(band.id);
                if (!peakData) return;

                self.peakGroup.selectAll(`.band-type-badge[data-band-id="${band.id}"]`)
                    .attr('x', xScale(peakData.x) + 10)
                    .attr('y', yScale(peakData.y) + 4);

                self.peakGroup.selectAll(`.peak-percent-label[data-band-id="${band.id}"]`)
                    .attr('x', xScale(peakData.x));
            });
        }

        /**
         * Fallback peak position update without ChartUtils.
         */
        _updatePeakPositionsFallback(xScale, yScale, bands) {
            const self = this;
            bands.forEach(band => {
                const peakData = self.peakDataMap.get(band.id);
                if (!peakData) return;

                self.peakGroup.selectAll(`.peak-marker[data-band-id="${band.id}"]`)
                    .attr('cx', xScale(peakData.x))
                    .attr('cy', yScale(peakData.y));

                self.peakGroup.selectAll(`.peak-mw-label[data-band-id="${band.id}"]`)
                    .attr('x', xScale(peakData.x))
                    .attr('y', yScale(peakData.y) - 15);

                const bounds = self.bandBoundsMap.get(band.id);
                if (bounds) {
                    self.peakGroup.selectAll(`.band-boundary[data-band-id="${band.id}"]`)
                        .each(function() {
                            const line = d3.select(this);
                            const boundType = line.attr('data-bound');
                            const boundX = boundType === 'left' ? bounds.leftBound : bounds.rightBound;
                            line.attr('x1', xScale(boundX)).attr('x2', xScale(boundX));
                        });
                }
            });
        }

        /**
         * Show placeholder message.
         */
        _showPlaceholder(message) {
            this._hidePlaceholder();

            const placeholder = document.createElement('div');
            placeholder.className = 'dm-chart-placeholder';
            placeholder.innerHTML = `<span>${message}</span>`;
            this.contentElement.appendChild(placeholder);
        }

        /**
         * Hide placeholder.
         */
        _hidePlaceholder() {
            const placeholder = this.contentElement.querySelector('.dm-chart-placeholder');
            if (placeholder) placeholder.remove();
        }

        /**
         * Clear the chart.
         */
        _clear() {
            this.currentLaneId = null;
            this.chartData = null;
            this.bgData = null;
            this.bandBoundsMap.clear();
            this.peakDataMap.clear();

            this.contentGroup.select('.profile-line').datum([]).attr('d', null);
            this.contentGroup.select('.background-area').datum([]).attr('d', null);
            this.peakGroup.selectAll('*').remove();
            this._clearDetectedPeaks();

            // Clear 3D terrain if active
            if (this.renderer3D) {
                this.renderer3D._clearTerrain();
            }

            // Exit 3D mode on clear
            if (this.is3DMode) {
                this.is3DMode = false;
                const btn = this.container.querySelector('#view-3d-toggle-btn');
                if (btn) {
                    btn.classList.remove('active');
                    btn.setAttribute('data-tooltip', '3D Terrain View');
                }
                this._enforce3DVisibility(false);
            }

            this._showPlaceholder('Select a lane to view its profile');
        }

        // =====================================================================
        // Detected Peaks Visualization
        // =====================================================================

        /**
         * Render detected peaks as triangle markers.
         * @param {Array} peaks - Array of detected peaks
         */
        _renderDetectedPeaks(peaks) {
            if (!this.detectedPeaksGroup || !peaks || !this.showDetectedPeaks) {
                return;
            }

            // Clear existing
            this.detectedPeaksGroup.selectAll('*').remove();

            if (!this.chartData || this.chartData.length === 0) {
                return;
            }

            const self = this;

            // Triangle path generator (pointing down)
            const triangleSize = 8;
            const trianglePath = (x, y) => {
                return `M ${x} ${y - triangleSize} L ${x - triangleSize} ${y - triangleSize * 2} L ${x + triangleSize} ${y - triangleSize * 2} Z`;
            };

            // Render each peak
            peaks.forEach((peak, index) => {
                const peakY = peak.y_position;

                // Find closest data point for peak height
                const dataPoint = this.chartData.find(d => Math.abs(d.x - peakY) < 5);
                if (!dataPoint) return;

                const cx = this.xScale(peakY);
                const cy = this.yScale(dataPoint.y);

                // Determine peak class and color based on status
                let peakClass, color;
                if (peak.is_orphan) {
                    peakClass = 'dm-detected-peak-orphan';
                    color = this.colors.orphanPeak;
                } else {
                    peakClass = 'dm-detected-peak-matched';
                    color = this.colors.matchedPeak;
                }

                // Add shoulder class if applicable
                if (peak.is_shoulder) {
                    peakClass = 'dm-detected-peak-shoulder';
                    color = this.colors.shoulderPeak;
                }

                // Create triangle marker
                const marker = this.detectedPeaksGroup.append('path')
                    .attr('class', `detected-peak-marker ${peakClass}`)
                    .attr('d', trianglePath(cx, cy))
                    .attr('fill', color)
                    .attr('stroke', d3.color(color).darker(0.5))
                    .attr('stroke-width', 1.5)
                    .attr('data-peak-index', index)
                    .attr('data-y-position', peakY)
                    .attr('data-is-orphan', peak.is_orphan);

                // Add interactivity for orphan peaks
                if (peak.is_orphan) {
                    marker
                        .style('cursor', 'pointer')
                        .on('click', () => this._onOrphanPeakClick(peak, index))
                        .on('mouseenter', (event) => this._onDetectedPeakHover(event, peak))
                        .on('mouseleave', () => this._hideTooltip());
                } else {
                    marker
                        .style('cursor', 'default')
                        .on('mouseenter', (event) => this._onDetectedPeakHover(event, peak))
                        .on('mouseleave', () => this._hideTooltip());
                }

                // Add vertical dashed line for orphan peaks
                if (peak.is_orphan) {
                    this.detectedPeaksGroup.append('line')
                        .attr('class', 'dm-peak-detection-line')
                        .attr('x1', cx)
                        .attr('y1', cy)
                        .attr('x2', cx)
                        .attr('y2', this.height)
                        .attr('stroke', color)
                        .attr('stroke-width', 1)
                        .attr('stroke-dasharray', '3, 3')
                        .attr('opacity', 0.5)
                        .attr('data-peak-index', index);
                }
            });
        }

        /**
         * Clear detected peaks markers.
         */
        _clearDetectedPeaks() {
            if (this.detectedPeaksGroup) {
                this.detectedPeaksGroup.selectAll('*').remove();
            }
        }

        /**
         * Handle orphan peak click (emit event to create band).
         */
        _onOrphanPeakClick(peak, index) {
            console.log('[ChromatogramPanel] Orphan peak clicked:', peak);
            this.eventBus.emit(Events.ORPHAN_PEAK_CLICKED, {
                peak,
                index,
                laneId: this.currentLaneId,
            });
        }

        /**
         * Handle hover over detected peak marker.
         */
        _onDetectedPeakHover(event, peak) {
            const tooltip = ChartUtils
                ? ChartUtils.getOrCreateTooltip()
                : this._getTooltip();

            let statusClass, statusLabel;
            if (peak.is_orphan) {
                statusClass = 'peak-status-orphan';
                statusLabel = 'Orphan';
            } else {
                statusClass = 'peak-status-matched';
                statusLabel = 'Matched';
            }
            if (peak.is_shoulder) {
                statusClass = 'peak-status-shoulder';
                statusLabel = 'Shoulder';
            }

            let content = `<span class="peak-status ${statusClass}">${statusLabel}</span><br>`;
            content += `<strong>Position:</strong> ${peak.y_position.toFixed(1)} px<br>`;
            content += `<strong>Height:</strong> ${peak.height.toFixed(0)}<br>`;

            if (peak.width_px) {
                content += `<strong>Width:</strong> ${peak.width_px.toFixed(1)} px<br>`;
            }

            if (peak.prominence) {
                content += `<strong>Prominence:</strong> ${peak.prominence.toFixed(0)}<br>`;
            }

            if (peak.matched_band_id) {
                content += `<strong>Band ID:</strong> ${peak.matched_band_id.slice(0, 8)}...<br>`;
            }

            if (peak.is_orphan) {
                content += `<em style="color: #FF9800;">Click to create band</em>`;
            }

            if (ChartUtils) {
                ChartUtils.showTooltip(tooltip, content, event);
                tooltip.classList.add('peak-tooltip');
            } else {
                tooltip.innerHTML = content;
                tooltip.classList.add('peak-tooltip');
                tooltip.style.left = `${event.pageX + 10}px`;
                tooltip.style.top = `${event.pageY - 10}px`;
                tooltip.style.display = 'block';
            }
        }

        /**
         * Update detected peak positions during zoom.
         */
        _updateDetectedPeakPositions(xScale, yScale) {
            if (!this.detectedPeaksGroup || !this.chartData) return;

            const self = this;
            const triangleSize = 8;

            const trianglePath = (x, y) => {
                return `M ${x} ${y - triangleSize} L ${x - triangleSize} ${y - triangleSize * 2} L ${x + triangleSize} ${y - triangleSize * 2} Z`;
            };

            // Update markers
            this.detectedPeaksGroup.selectAll('.detected-peak-marker').each(function() {
                const marker = d3.select(this);
                const peakY = parseFloat(marker.attr('data-y-position'));

                const dataPoint = self.chartData.find(d => Math.abs(d.x - peakY) < 5);
                if (!dataPoint) return;

                const cx = xScale(peakY);
                const cy = yScale(dataPoint.y);

                marker.attr('d', trianglePath(cx, cy));
            });

            // Update detection lines
            this.detectedPeaksGroup.selectAll('.dm-peak-detection-line').each(function() {
                const line = d3.select(this);
                const peakIndex = parseInt(line.attr('data-peak-index'));
                const marker = self.detectedPeaksGroup.select(`.detected-peak-marker[data-peak-index="${peakIndex}"]`);

                if (!marker.empty()) {
                    const peakY = parseFloat(marker.attr('data-y-position'));
                    const dataPoint = self.chartData.find(d => Math.abs(d.x - peakY) < 5);
                    if (dataPoint) {
                        const cx = xScale(peakY);
                        const cy = yScale(dataPoint.y);
                        line.attr('x1', cx).attr('x2', cx).attr('y1', cy);
                    }
                }
            });
        }

        /**
         * Setup ResizeObserver with debouncing.
         */
        _setupResizeObserver() {
            if (this.resizeObserver) {
                this.resizeObserver.disconnect();
            }

            this.resizeObserver = new ResizeObserver(() => {
                // Debounce with requestAnimationFrame
                if (this.resizeTimeout) {
                    cancelAnimationFrame(this.resizeTimeout);
                }
                this.resizeTimeout = requestAnimationFrame(() => {
                    this._handleResize();
                });
            });

            this.resizeObserver.observe(this.contentElement);
        }

        /**
         * Handle resize - recreate chart or resize 3D renderer.
         */
        _handleResize() {
            const rect = this.contentElement.getBoundingClientRect();

            // Skip if container has no dimensions
            if (rect.width === 0 || rect.height === 0) return;

            if (this.is3DMode && this.renderer3D) {
                // In 3D mode: only resize the 3D renderer, don't touch 2D chart
                this.renderer3D.onResize();
                // Ensure visibility state is correct (magnifier may have triggered resize)
                this._enforce3DVisibility(true);
                return;
            }

            // If the current view is not electropherogram, skip chart rebuild entirely.
            // Creating a new SVG while POI Purity or another view is active causes stacking.
            if (this.currentView !== 'electropherogram') {
                return;
            }

            const newWidth = rect.width - this.margin.left - this.margin.right;
            const newHeight = rect.height - this.margin.top - this.margin.bottom;

            // Skip if dimensions haven't changed significantly
            if (Math.abs(newWidth - this.width) < 5 && Math.abs(newHeight - this.height) < 5) {
                return;
            }

            // Recreate chart and re-render (2D mode only)
            this._createChart();
            if (this.currentLaneId) {
                const profile = this.state.getProfile(this.currentLaneId);
                if (profile) {
                    this._renderProfile(profile);
                }
            }
        }

        /**
         * Cleanup resources.
         */
        destroy() {
            if (this.resizeObserver) {
                this.resizeObserver.disconnect();
                this.resizeObserver = null;
            }
            if (this.resizeTimeout) {
                cancelAnimationFrame(this.resizeTimeout);
                this.resizeTimeout = null;
            }
            if (this.renderer3D) {
                this.renderer3D.dispose();
                this.renderer3D = null;
            }
        }
    }

    // Export
    global.Densitometry = global.Densitometry || {};
    global.Densitometry.ChromatogramPanel = ChromatogramPanel;

})(window);
