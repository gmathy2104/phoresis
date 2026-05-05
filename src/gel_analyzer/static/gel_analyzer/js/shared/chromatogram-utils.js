/**
 * Chromatogram Chart Utilities - Shared rendering functions
 *
 * Composable utility functions used by both the Densitometry and Comparison
 * chromatogram panels. Provides peak rendering, zoom setup, tooltip management,
 * and band calculation helpers.
 *
 * Namespace: GelAnalyzer.ChartUtils
 */

(function(global) {
    'use strict';

    /**
     * ChartUtils - Static utility methods for chromatogram chart rendering.
     */
    const ChartUtils = {

        // =====================================================================
        // Peak Rendering
        // =====================================================================

        /**
         * Render a peak marker (circle) on the chart.
         *
         * @param {d3.Selection} peakGroup - D3 selection for peak highlights group
         * @param {d3.Scale} xScale - Current X scale
         * @param {d3.Scale} yScale - Current Y scale
         * @param {Object} point - Data point { x, y }
         * @param {Object} band - Band data object
         * @param {string} color - Marker fill color
         * @param {Object} opts - Options { onClick, onMouseEnter, onMouseLeave }
         * @returns {d3.Selection} The created circle element
         */
        renderPeakMarker(peakGroup, xScale, yScale, point, band, color, opts = {}) {
            const marker = peakGroup.append('circle')
                .attr('class', 'peak-marker')
                .attr('cx', xScale(point.x))
                .attr('cy', yScale(point.y))
                .attr('r', 5)
                .attr('fill', color)
                .attr('stroke', '#fff')
                .attr('stroke-width', 2)
                .attr('data-band-id', band.id)
                .style('cursor', 'pointer');

            if (opts.sampleId) {
                marker.attr('data-sample-id', opts.sampleId);
            }

            if (opts.onClick) {
                marker.on('click', opts.onClick);
            }
            if (opts.onMouseEnter) {
                marker.on('mouseenter', opts.onMouseEnter);
            }
            if (opts.onMouseLeave) {
                marker.on('mouseleave', opts.onMouseLeave);
            }

            return marker;
        },

        /**
         * Render peak boundary lines (dashed vertical lines at ±3σ).
         *
         * @param {d3.Selection} peakGroup - D3 selection for peak highlights group
         * @param {d3.Scale} xScale - Current X scale
         * @param {Object} bounds - Band bounds { leftBound, rightBound }
         * @param {string} color - Line stroke color
         * @param {number} height - Chart height
         * @param {Object} opts - Options { bandId, opacity, onClick }
         * @returns {Object} { leftLine, rightLine } D3 selections
         */
        renderPeakBoundaries(peakGroup, xScale, bounds, color, height, opts = {}) {
            const bandId = opts.bandId || '';
            const opacity = opts.opacity !== undefined ? opts.opacity : 0.5;

            const leftLine = peakGroup.append('line')
                .attr('class', 'band-boundary band-boundary-left')
                .attr('x1', xScale(bounds.leftBound))
                .attr('y1', 0)
                .attr('x2', xScale(bounds.leftBound))
                .attr('y2', height)
                .attr('stroke', color)
                .attr('stroke-width', 1)
                .attr('stroke-dasharray', '4,2')
                .attr('opacity', opacity)
                .attr('data-band-id', bandId)
                .attr('data-bound', 'left')
                .style('cursor', 'pointer');

            const rightLine = peakGroup.append('line')
                .attr('class', 'band-boundary band-boundary-right')
                .attr('x1', xScale(bounds.rightBound))
                .attr('y1', 0)
                .attr('x2', xScale(bounds.rightBound))
                .attr('y2', height)
                .attr('stroke', color)
                .attr('stroke-width', 1)
                .attr('stroke-dasharray', '4,2')
                .attr('opacity', opacity)
                .attr('data-band-id', bandId)
                .attr('data-bound', 'right')
                .style('cursor', 'pointer');

            if (opts.onClick) {
                leftLine.on('click', opts.onClick);
                rightLine.on('click', opts.onClick);
            }

            return { leftLine, rightLine };
        },

        /**
         * Render peak area fill with gradient.
         *
         * @param {d3.Selection} peakGroup - D3 selection for peak highlights group
         * @param {d3.Selection} defs - SVG defs selection for gradient definitions
         * @param {d3.Scale} xScale - Current X scale
         * @param {d3.Scale} yScale - Current Y scale
         * @param {Array} chartData - Full chart data array
         * @param {Object} bounds - Band bounds { leftBound, rightBound }
         * @param {string} color - Fill color
         * @param {number} height - Chart height
         * @param {Object} opts - Options { bandId, onClick }
         * @returns {d3.Selection|null} The created path element, or null if no data
         */
        renderPeakAreaFill(peakGroup, defs, xScale, yScale, chartData, bounds, color, height, opts = {}) {
            const bandId = opts.bandId || '';

            const minBound = Math.min(bounds.leftBound, bounds.rightBound);
            const maxBound = Math.max(bounds.leftBound, bounds.rightBound);
            const peakData = chartData.filter(
                d => d.x >= minBound && d.x <= maxBound
            );

            if (peakData.length === 0) return null;

            // Create gradient
            const gradientId = `peak-gradient-${bandId}`;

            // Remove existing gradient with same ID
            defs.select(`#${gradientId}`).remove();

            const gradient = defs
                .append('linearGradient')
                .attr('class', 'peak-gradient')
                .attr('id', gradientId)
                .attr('x1', '0%')
                .attr('y1', '100%')
                .attr('x2', '0%')
                .attr('y2', '0%');

            gradient.append('stop')
                .attr('offset', '0%')
                .attr('stop-color', color)
                .attr('stop-opacity', 0.05);

            gradient.append('stop')
                .attr('offset', '100%')
                .attr('stop-color', color)
                .attr('stop-opacity', 0.4);

            const peakArea = d3.area()
                .x(d => xScale(d.x))
                .y0(height)
                .y1(d => yScale(d.y))
                .curve(d3.curveMonotoneX);

            const path = peakGroup.append('path')
                .datum(peakData)
                .attr('class', 'peak-area')
                .attr('d', peakArea)
                .attr('fill', `url(#${gradientId})`)
                .attr('data-band-id', bandId)
                .style('cursor', 'pointer');

            if (opts.onClick) {
                path.on('click', opts.onClick);
            }

            return path;
        },

        /**
         * Render MW label above a peak.
         *
         * @param {d3.Selection} peakGroup - D3 selection for peak highlights group
         * @param {d3.Scale} xScale - Current X scale
         * @param {d3.Scale} yScale - Current Y scale
         * @param {Object} point - Data point { x, y }
         * @param {Object} band - Band data with estimated_mw_kda
         * @param {string} color - Text fill color
         * @param {Object} opts - Options { bandId, onClick, fontFamily }
         * @returns {d3.Selection|null} The created text element, or null if no MW data
         */
        renderMWLabel(peakGroup, xScale, yScale, point, band, color, opts = {}) {
            if (!band.estimated_mw_kda) return null;

            const label = peakGroup.append('text')
                .attr('class', 'peak-label peak-mw-label')
                .attr('x', xScale(point.x))
                .attr('y', yScale(point.y) - 15)
                .attr('text-anchor', 'middle')
                .attr('font-size', '10px')
                .attr('font-weight', 'bold')
                .attr('fill', color)
                .attr('data-band-id', band.id)
                .text(`${band.estimated_mw_kda.toFixed(0)} kDa`);

            if (opts.fontFamily) {
                label.attr('font-family', opts.fontFamily);
            }

            if (opts.onClick) {
                label.style('cursor', 'pointer').on('click', opts.onClick);
            }

            return label;
        },


        // =====================================================================
        // Position Updates (Zoom)
        // =====================================================================

        /**
         * Update all peak element positions during zoom.
         *
         * @param {d3.Selection} peakGroup - D3 selection for peak highlights group
         * @param {Map} peakDataMap - Map of bandId -> { x, y } peak positions
         * @param {d3.Scale} xScale - Zoomed X scale
         * @param {d3.Scale} yScale - Zoomed Y scale
         */
        updatePeakPositions(peakGroup, peakDataMap, xScale, yScale) {
            // Update markers
            peakGroup.selectAll('.peak-marker').each(function() {
                const marker = d3.select(this);
                const bandId = marker.attr('data-band-id');
                const peakData = peakDataMap.get(bandId);

                if (peakData) {
                    marker
                        .attr('cx', xScale(peakData.x))
                        .attr('cy', yScale(peakData.y));
                }
            });

            // Update MW labels
            peakGroup.selectAll('.peak-mw-label').each(function() {
                const label = d3.select(this);
                const bandId = label.attr('data-band-id');
                const peakData = peakDataMap.get(bandId);

                if (peakData) {
                    label
                        .attr('x', xScale(peakData.x))
                        .attr('y', yScale(peakData.y) - 15);
                }
            });
        },

        /**
         * Update boundary line positions during zoom.
         *
         * @param {d3.Selection} peakGroup - D3 selection for peak highlights group
         * @param {d3.Scale} xScale - Zoomed X scale
         * @param {Map} bandBoundsMap - Map of bandId -> { leftBound, rightBound }
         */
        updateBoundaryPositions(peakGroup, xScale, bandBoundsMap) {
            peakGroup.selectAll('.band-boundary').each(function() {
                const line = d3.select(this);
                const bandId = line.attr('data-band-id');
                const boundType = line.attr('data-bound');
                const bounds = bandBoundsMap.get(bandId);

                if (bounds) {
                    const boundX = boundType === 'left' ? bounds.leftBound : bounds.rightBound;
                    line.attr('x1', xScale(boundX))
                        .attr('x2', xScale(boundX));
                }
            });
        },

        /**
         * Update peak area fills during zoom.
         *
         * @param {d3.Selection} peakGroup - D3 selection for peak highlights group
         * @param {d3.Scale} xScale - Zoomed X scale
         * @param {d3.Scale} yScale - Zoomed Y scale
         * @param {Array} chartData - Full chart data
         * @param {Map} bandBoundsMap - Map of bandId -> { leftBound, rightBound }
         * @param {number} height - Chart height
         */
        updatePeakAreaPositions(peakGroup, xScale, yScale, chartData, bandBoundsMap, height) {
            peakGroup.selectAll('.peak-area').each(function() {
                const path = d3.select(this);
                const bandId = path.attr('data-band-id');
                const bounds = bandBoundsMap.get(bandId);

                if (bounds && chartData) {
                    const minBound = Math.min(bounds.leftBound, bounds.rightBound);
                    const maxBound = Math.max(bounds.leftBound, bounds.rightBound);
                    const peakData = chartData.filter(
                        d => d.x >= minBound && d.x <= maxBound
                    );

                    if (peakData.length > 0) {
                        const peakArea = d3.area()
                            .x(d => xScale(d.x))
                            .y0(height)
                            .y1(d => yScale(d.y))
                            .curve(d3.curveMonotoneX);

                        path.datum(peakData).attr('d', peakArea);
                    }
                }
            });
        },


        // =====================================================================
        // Selection / Highlighting
        // =====================================================================

        /**
         * Highlight a selected band on the chart.
         *
         * @param {d3.Selection} peakGroup - D3 selection for peak highlights group
         * @param {string|null} bandId - Band ID to highlight, or null to reset all
         * @param {Object} opts - Options { highlightArea, highlightBoundaries }
         */
        highlightBand(peakGroup, bandId, opts = {}) {
            const highlightArea = opts.highlightArea !== false;
            const highlightBoundaries = opts.highlightBoundaries !== false;

            // Reset all peaks to default
            peakGroup.selectAll('.peak-area')
                .style('opacity', null)
                .style('stroke', null)
                .style('stroke-width', null);

            peakGroup.selectAll('.peak-marker')
                .attr('r', 5)
                .attr('stroke-width', 2);

            peakGroup.selectAll('.band-boundary')
                .style('opacity', 0.5)
                .style('stroke-width', 1);

            if (bandId) {
                // Highlight selected peak area
                if (highlightArea) {
                    peakGroup.selectAll(`.peak-area[data-band-id="${bandId}"]`)
                        .style('opacity', 1)
                        .style('stroke', '#2196F3')
                        .style('stroke-width', 2);
                }

                // Enlarge selected marker
                peakGroup.selectAll(`.peak-marker[data-band-id="${bandId}"]`)
                    .attr('r', 8)
                    .attr('stroke-width', 3);

                // Highlight boundaries
                if (highlightBoundaries) {
                    peakGroup.selectAll(`.band-boundary[data-band-id="${bandId}"]`)
                        .style('opacity', 1)
                        .style('stroke-width', 2);
                }
            }
        },

        /**
         * Reset all band highlights to default state.
         *
         * @param {d3.Selection} peakGroup - D3 selection for peak highlights group
         */
        resetBandHighlights(peakGroup) {
            this.highlightBand(peakGroup, null);
        },


        // =====================================================================
        // Helpers
        // =====================================================================

        /**
         * Get color for a band type.
         *
         * @param {string} bandType - Band type ('POI', 'MW_REFERENCE', 'OTHER')
         * @param {Object} colorMap - Color map (optional, uses defaults)
         * @returns {string} CSS color string
         */
        getBandColor(bandType, colorMap = null) {
            const colors = colorMap || {
                poi: '#22C55E',
                mwReference: '#FFC107',
                other: '#9E9E9E',
            };

            switch (bandType) {
                case 'POI': return colors.poi;
                case 'MW_REFERENCE': return colors.mwReference;
                default: return colors.other;
            }
        },

        /**
         * Find the closest data point to a target value.
         *
         * @param {Array} chartData - Array of { x, y } data points
         * @param {number} targetValue - Target X value to find
         * @param {number} tolerance - Maximum allowed distance (default: 5)
         * @param {string} field - Field to search ('x' or 'yPos', default: 'x')
         * @returns {Object|null} Closest data point, or null if none within tolerance
         */
        findClosestDataPoint(chartData, targetValue, tolerance = 5, field = 'x') {
            if (!chartData || chartData.length === 0) return null;

            let closestPoint = null;
            let minDist = Infinity;

            chartData.forEach(d => {
                const val = d[field] !== undefined ? d[field] : d.x;
                const dist = Math.abs(val - targetValue);
                if (dist < minDist) {
                    minDist = dist;
                    closestPoint = d;
                }
            });

            if (minDist > tolerance) return null;
            return closestPoint;
        },

        /**
         * Calculate band bounds (integration boundaries).
         *
         * Returns the bbox edges, NOT ±3σ. The server-side integrator
         * (services/densitometry/peak_integrator.py:132-144) uses bbox_y /
         * bbox_y + bbox_height as the integration region — anything else
         * shown on the chromatogram would mislead the user about what was
         * actually integrated.
         *
         * peakY remains the peak center used for MW estimation, which is a
         * separate concept (read on the calibration curve) and gets its
         * own marker in the rendering layer.
         *
         * @param {Object} band - Band data object
         * @returns {Object} { peakY, leftBound, rightBound, sigma }
         */
        calculateBandBounds(band) {
            const peakY = band.densitometry?.peak_center_y ?? band.position_y;
            const sigma = band.densitometry?.sigma ?? band.densitometry?.peak_sigma ?? null;

            const bboxTop = band.bbox_y;
            const bboxHeight = band.bbox_height;
            if (bboxTop != null && bboxHeight != null && bboxHeight > 0) {
                return {
                    peakY,
                    leftBound: bboxTop,
                    rightBound: bboxTop + bboxHeight,
                    sigma,
                };
            }

            // Fallback for legacy bands missing bbox: use ±3σ if a fit exists,
            // else a fixed 20-px window centered on the peak (mirrors the
            // server-side fallback in peak_integrator.integrate_band).
            const halfWidth = sigma ? sigma * 3 : 20;
            return {
                peakY,
                leftBound: peakY - halfWidth,
                rightBound: peakY + halfWidth,
                sigma,
            };
        },

        /**
         * Render a peak-maximum marker — the X position used to read the
         * molecular weight off the calibration curve. Visually distinct
         * from integration bounds: solid red vertical line + ▼ on the top
         * axis.
         *
         * @param {d3.Selection} peakGroup - D3 selection for peak highlights group
         * @param {d3.Scale} xScale - Current X scale
         * @param {number} peakX - Peak max position in chart-X units
         * @param {number} chartHeight - Chart drawing height
         * @param {Object} opts - { bandId, color, onClick }
         * @returns {Object} { line, glyph }
         */
        renderPeakMaxMarker(peakGroup, xScale, peakX, chartHeight, opts = {}) {
            const bandId = opts.bandId || '';
            const color = opts.color || '#dc2626';

            const line = peakGroup.append('line')
                .attr('class', 'band-peak-max')
                .attr('x1', xScale(peakX))
                .attr('y1', 0)
                .attr('x2', xScale(peakX))
                .attr('y2', chartHeight)
                .attr('stroke', color)
                .attr('stroke-width', 1.25)
                .attr('stroke-dasharray', '3,3')
                .attr('opacity', 0.7)
                .attr('data-band-id', bandId)
                .style('pointer-events', 'none');

            const glyph = peakGroup.append('path')
                .attr('class', 'band-peak-max-glyph')
                .attr('d', 'M -5,0 L 5,0 L 0,7 Z')
                .attr('transform', `translate(${xScale(peakX)}, 0)`)
                .attr('fill', color)
                .attr('opacity', 0.9)
                .attr('data-band-id', bandId)
                .style('cursor', opts.onClick ? 'pointer' : 'default');

            if (opts.onClick) {
                glyph.on('click', opts.onClick);
            }

            return { line, glyph };
        },


        // =====================================================================
        // Tooltip
        // =====================================================================

        /**
         * Get or create a tooltip element.
         *
         * @param {string} id - Element ID for the tooltip
         * @param {string} className - CSS class name
         * @returns {HTMLElement} Tooltip element
         */
        getOrCreateTooltip(id = 'dm-chart-tooltip', className = 'dm-tooltip') {
            let tooltip = document.getElementById(id);
            if (!tooltip) {
                tooltip = document.createElement('div');
                tooltip.id = id;
                tooltip.className = className;
                document.body.appendChild(tooltip);
            }
            return tooltip;
        },

        /**
         * Show a tooltip with content at the mouse position.
         *
         * @param {HTMLElement} tooltip - Tooltip element
         * @param {string} content - HTML content
         * @param {MouseEvent} event - Mouse event for positioning
         * @param {Object} opts - Options { offsetX, offsetY }
         */
        showTooltip(tooltip, content, event, opts = {}) {
            const offsetX = opts.offsetX || 10;
            const offsetY = opts.offsetY || -10;

            tooltip.innerHTML = content;
            tooltip.style.left = `${event.pageX + offsetX}px`;
            tooltip.style.top = `${event.pageY + offsetY}px`;
            tooltip.style.display = 'block';
        },

        /**
         * Hide a tooltip.
         *
         * @param {HTMLElement} tooltip - Tooltip element
         */
        hideTooltip(tooltip) {
            if (tooltip) {
                tooltip.style.display = 'none';
            }
        },


        // =====================================================================
        // Zoom Utilities
        // =====================================================================

        /**
         * Setup brush-to-zoom on a chart.
         *
         * @param {d3.Selection} chartGroup - Chart group element
         * @param {number} width - Chart width
         * @param {number} height - Chart height
         * @param {d3.ZoomBehavior} zoom - D3 zoom behavior
         * @param {d3.Selection} zoomTarget - Element to apply zoom transform to
         * @param {Object} opts - Options { maxScale, transitionDuration }
         * @returns {d3.BrushBehavior} The brush behavior
         */
        setupBrushZoom(chartGroup, width, height, zoom, zoomTarget, opts = {}) {
            const maxScale = opts.maxScale || 20;
            const transitionDuration = opts.transitionDuration || 300;

            const brush = d3.brushX()
                .extent([[0, 0], [width, height]])
                .on('end', (event) => {
                    if (!event.selection) return;

                    const [x0, x1] = event.selection;

                    // Clear brush selection
                    chartGroup.select('.brush-group').call(brush.move, null);

                    // Skip tiny selections
                    if (Math.abs(x1 - x0) < 10) return;

                    const scale = width / (x1 - x0);
                    const clampedScale = Math.min(Math.max(scale, 1), maxScale);

                    const newTransform = d3.zoomIdentity
                        .scale(clampedScale)
                        .translate(-x0, 0);

                    zoomTarget.transition()
                        .duration(transitionDuration)
                        .call(zoom.transform, newTransform);
                });

            chartGroup.append('g')
                .attr('class', 'brush-group')
                .call(brush);

            return brush;
        },

        /**
         * Add zoom hint text below the chart.
         *
         * @param {d3.Selection} chartGroup - Chart group element
         * @param {number} width - Chart width
         * @param {number} height - Chart height
         * @param {Object} opts - Options { text, fontFamily, fill }
         */
        addZoomHintText(chartGroup, width, height, opts = {}) {
            chartGroup.selectAll('.zoom-hint').remove();

            const text = opts.text || 'Drag to select zoom region \u2022 Double-click to reset';
            const fill = opts.fill || 'rgba(255,255,255,0.4)';
            const fontFamily = opts.fontFamily || 'Inter, system-ui, sans-serif';

            chartGroup.append('text')
                .attr('class', 'zoom-hint')
                .attr('x', width / 2)
                .attr('y', height + 28)
                .attr('text-anchor', 'middle')
                .attr('fill', fill)
                .attr('font-size', '10px')
                .attr('font-family', fontFamily)
                .text(text);
        },

        /**
         * Create a zoom reset HTML button.
         *
         * @param {HTMLElement} container - Container element
         * @param {Function} onReset - Callback when reset is clicked
         * @returns {HTMLElement} The controls container element
         */
        createZoomResetButton(container, onReset) {
            const controls = document.createElement('div');
            controls.className = 'dm-zoom-controls';
            controls.innerHTML = `
                <button class="dm-zoom-btn dm-zoom-reset" title="Reset zoom (1:1)">
                    <i class="bi bi-arrows-angle-contract"></i>
                </button>
            `;

            container.appendChild(controls);

            controls.querySelector('.dm-zoom-reset').addEventListener('click', () => {
                if (onReset) onReset();
            });

            return controls;
        },
    };

    // Export to namespace
    global.GelAnalyzer = global.GelAnalyzer || {};
    global.GelAnalyzer.ChartUtils = ChartUtils;

})(window);
