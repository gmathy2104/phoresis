/**
 * Renderer - SVG Rendering for GelViewer
 *
 * Handles rendering of lanes and bands as SVG elements,
 * and maintains the annotations list sidebar.
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    /**
     * Renderer Class
     */
    class Renderer {
        /**
         * @param {Object} options
         * @param {Object} options.svg - SVG.js instance
         * @param {Object} options.lanesGroup - SVG group for lanes
         * @param {Object} options.bandsGroup - SVG group for bands
         * @param {StateManager} options.stateManager - StateManager instance
         * @param {EventBus} options.eventBus - EventBus instance
         * @param {Function} options.onSelectAnnotation - Callback for selection
         */
        constructor(options) {
            this.svg = options.svg;
            this.lanesGroup = options.lanesGroup;
            this.bandsGroup = options.bandsGroup;
            this.calibrationLinesGroup = options.calibrationLinesGroup;
            this.stateManager = options.stateManager;
            this.eventBus = options.eventBus;
            this.onSelectAnnotation = options.onSelectAnnotation;

            // Anti-HCP reference lane (server id, a number) or null. Set by
            // GelViewerApp before each (re)render through setReferenceLane;
            // renderLane draws the "REF" badge, so load, reload and recovery
            // all get it.
            this.referenceLaneId = null;
        }

        // =====================================================================
        // Lane Rendering
        // =====================================================================

        /**
         * Render a lane.
         * @param {Object} data - Lane data
         */
        renderLane(data) {
            this.stateManager.setLane(data.id, data);

            let shape;

            // Render based on lane shape type
            if (data.lane_shape && data.lane_shape !== 'RECTANGLE' && data.polygon && data.polygon.length >= 3) {
                shape = this.lanesGroup.polygon(data.polygon)
                    .attr('id', `lane-${data.id}`)
                    .addClass('gv-lane');
            } else {
                shape = this.lanesGroup.rect(data.width, data.height)
                    .move(data.x, data.y)
                    .attr('id', `lane-${data.id}`)
                    .addClass('gv-lane');
            }

            // Apply lane type class.
            // Supported types map to CSS rules in gel_viewer_standalone.css:
            //   .gv-lane.sample / .ladder / .control / .calibration / .empty
            // Any future lane_type just needs a matching CSS rule — this
            // generic lowercase mapping does not need touching.
            if (data.lane_type) {
                shape.addClass(data.lane_type.toLowerCase());
            }

            // Add shape class
            if (data.lane_shape) {
                shape.addClass(`shape-${data.lane_shape.toLowerCase()}`);
            }

            // Add label
            const { x: labelX, y: labelY } = this._labelAnchor(data);

            this.lanesGroup.text(String(data.lane_number))
                .move(labelX, labelY)
                .addClass('gv-lane-label')
                .attr('id', `lane-label-${data.id}`);

            if (this._isReference(data.id)) {
                this._drawRefBadge(data.id, { x: labelX, y: labelY }, data.lane_number);
            }

            // Click handler
            shape.on('click', (e) => {
                e.stopPropagation();
                if (this.onSelectAnnotation) {
                    this.onSelectAnnotation('lane', data.id);
                }
            });
        }

        /**
         * Where a lane's number goes: inside the left end of the top row of the shape drawn (a rectangle's top-left
         * corner). Rule 2 (shared/lane-geometry.js): a RECTANGLE lane is drawn and labelled by its box whatever polygon
         * it stores, and a tilted lane's label sits at its own top, not over its foot's minimum x.
         */
        _labelAnchor(lane) {
            const G = GelAnalyzer.LaneGeometry;
            const drawn = lane.lane_shape ? lane : { ...lane, lane_shape: 'RECTANGLE' };
            const [x, y] = G.topLeft(G.outline(drawn));
            return { x: x + 4, y: y + 4 };
        }

        /**
         * Update a lane's visual representation.
         * @param {Object} lane - Lane data
         */
        updateLane(lane) {
            const element = this.svg.findOne(`#lane-${lane.id}`);
            if (!element) return;

            if (lane.lane_shape !== 'RECTANGLE' && lane.polygon && lane.polygon.length >= 3) {
                // Update polygon shape
                element.plot(lane.polygon);
            } else {
                // Update rectangle position/size
                element.move(lane.x, lane.y).size(lane.width, lane.height);
            }
            const labelAnchor = this._labelAnchor(lane);
            const label = this.svg.findOne(`#lane-label-${lane.id}`);
            if (label) {
                label.move(labelAnchor.x, labelAnchor.y);
            }

            // The REF badge follows the label.
            if (this._isReference(lane.id)) {
                this._drawRefBadge(lane.id, labelAnchor, lane.lane_number);
            }
        }

        /**
         * Update lane label number.
         * @param {string|number} id - Lane ID
         * @param {number} number - New lane number
         */
        updateLaneNumber(id, number) {
            const label = this.svg.findOne(`#lane-label-${id}`);
            if (label) {
                label.text(String(number));
            }

            // A wider number pushes the REF badge right: redraw it at the
            // anchor it was drawn from.
            if (this._isReference(id)) {
                const badge = this.lanesGroup.findOne('.gv-ref-badge');
                const lane = this.stateManager.getLane(id);
                const anchor = badge
                    ? { x: Number(badge.attr('data-anchor-x')), y: Number(badge.attr('data-anchor-y')) }
                    : (lane ? this._labelAnchor(lane) : null);
                if (anchor) this._drawRefBadge(id, anchor, number);
            }
        }

        /**
         * Remove a lane from rendering.
         * @param {string|number} id - Lane ID
         */
        removeLane(id) {
            const element = this.svg.findOne(`#lane-${id}`);
            if (element) element.remove();

            const label = this.svg.findOne(`#lane-label-${id}`);
            if (label) label.remove();

            // The reference itself stays the server's (an unsaved delete can
            // be undone by a reload); only its badge goes with the lane.
            if (this._isReference(id)) {
                this._clearRefBadge();
            }
        }

        // =====================================================================
        // HCP reference lane badge
        // =====================================================================

        /**
         * Mark lane ``id`` as the anti-HCP reference (null clears). Exactly
         * one badge at a time; drawn now if the lane is already rendered,
         * otherwise by renderLane when it is.
         * @param {number|string|null} id - Server lane id
         */
        setReferenceLane(id) {
            this.referenceLaneId = (id === null || id === undefined || id === '') ? null : Number(id);
            this._clearRefBadge();
            if (this.referenceLaneId === null) return;

            const lane = this.stateManager.getLane(this.referenceLaneId);
            if (lane && this.svg.findOne(`#lane-${lane.id}`)) {
                this._drawRefBadge(lane.id, this._labelAnchor(lane), lane.lane_number);
            }
        }

        _isReference(id) {
            return this.referenceLaneId !== null && Number(id) === this.referenceLaneId;
        }

        /**
         * Draw the "REF" tag right of the lane number and outline the lane.
         * A class on the lane shape and a class on the badge -- never an id
         * starting "lane-" (the lane lookups use #lane-<id>). The badge is
         * pointer-events: none (CSS) so the lane under it stays clickable.
         */
        _drawRefBadge(laneId, anchor, laneNumber) {
            this._clearRefBadge();

            const element = this.svg.findOne(`#lane-${laneId}`);
            if (element) element.addClass('gv-lane--reference');

            const digits = String(laneNumber ?? '').length || 1;
            const x = anchor.x + digits * 7 + 4;   // the label is 12px, ~7px per digit
            const y = anchor.y + 1;
            const width = 22;
            const height = 12;

            const badge = this.lanesGroup.group()
                .addClass('gv-ref-badge')
                .attr({ 'data-ref-lane': laneId, 'data-anchor-x': anchor.x, 'data-anchor-y': anchor.y });
            badge.rect(width, height).move(x, y).radius(2).addClass('gv-ref-badge-bg');
            badge.plain('REF').addClass('gv-ref-badge-text').attr({
                x: x + width / 2,
                y: y + height / 2,
                'text-anchor': 'middle',
                'dominant-baseline': 'central',
            });
        }

        _clearRefBadge() {
            this.lanesGroup.find('.gv-ref-badge').forEach(el => el.remove());
            this.lanesGroup.find('.gv-lane--reference').forEach(el => el.removeClass('gv-lane--reference'));
        }

        // =====================================================================
        // Band Rendering
        // =====================================================================

        /**
         * Render a band.
         * @param {Object} data - Band data
         */
        renderBand(data) {
            this.stateManager.setBand(data.id, data);

            let element;

            if (data.polygon && data.polygon.length >= 3) {
                // Use polygon if available
                element = this.bandsGroup.polygon(data.polygon);
            } else if (data.bbox_x != null && data.bbox_y != null && data.bbox_width && data.bbox_height) {
                // Fall back to bounding box rectangle
                element = this.bandsGroup.rect(data.bbox_width, data.bbox_height)
                    .move(data.bbox_x, data.bbox_y);
            }

            if (element) {
                element
                    .attr('id', `band-${data.id}`)
                    .addClass('gv-band')
                    .addClass((data.band_type || 'OTHER').toLowerCase());
                // Its part in the reading (the server's, /data/): drawn when the gel is coloured by readout (3c).
                if (data.role) element.addClass(`role-${data.role}`);

                // Hybrid-phase visual marker: if the band came from a split
                // (metadata.hybrid_phase === 'split'), add a CSS class so the
                // two adjacent sub-bands are visually distinguishable on the
                // gel (their shared edge at the valley is otherwise invisible
                // with the default stroke-width of 0.5).
                const phase = data.metadata?.hybrid_phase;
                if (phase === 'split') {
                    element.addClass('gv-band-split');
                } else if (phase === 'cross_lane_filled') {
                    element.addClass('gv-band-cross-lane');
                }

                // Click handler
                element.on('click', (e) => {
                    e.stopPropagation();
                    if (this.onSelectAnnotation) {
                        this.onSelectAnnotation('band', data.id);
                    }
                });
            }
        }

        /**
         * Update a band's visual representation.
         * @param {Object} band - Band data
         */
        updateBand(band) {
            const element = this.svg.findOne(`#band-${band.id}`);
            if (!element) return;

            if (band.polygon && band.polygon.length >= 3) {
                // Update polygon
                if (element.type === 'polygon') {
                    element.plot(band.polygon);
                }
            } else if (band.bbox_x != null && band.bbox_y != null) {
                // Update rectangle position/size
                if (element.type === 'rect') {
                    element.move(band.bbox_x, band.bbox_y);
                    if (band.bbox_width) element.width(band.bbox_width);
                    if (band.bbox_height) element.height(band.bbox_height);
                }
            }
        }

        /**
         * A band's part in the reading changed (a fresh /data/): its `role-*` class follows.
         * @param {string} id - Band ID
         * @param {?string} role - The server's role, or null
         */
        setBandRole(id, role) {
            const element = this.svg.findOne(`#band-${id}`);
            if (!element) return;
            (element.classes() || []).filter((name) => name.startsWith('role-')).forEach((name) => element.removeClass(name));
            if (role) element.addClass(`role-${role}`);
        }

        /**
         * Remove a band from rendering.
         * @param {string} id - Band ID
         */
        removeBand(id) {
            const element = this.svg.findOne(`#band-${id}`);
            if (element) element.remove();
        }

        // =====================================================================
        // Selection Visual
        // =====================================================================

        /**
         * Apply selection highlight to an annotation.
         * @param {string} type - 'lane' or 'band'
         * @param {string|number} id - Annotation ID
         */
        selectAnnotation(type, id) {
            // Remove previous selection
            this.svg.find('.gv-selected').forEach(el => el.removeClass('gv-selected'));

            // Add selection to new element
            const element = this.svg.findOne(`#${type}-${id}`);
            if (element) {
                element.addClass('gv-selected');
            }
        }

        /**
         * Clear selection highlight.
         */
        clearSelection() {
            this.svg.find('.gv-selected').forEach(el => el.removeClass('gv-selected'));
        }

        // =====================================================================
        // MW Calibration Lines
        // =====================================================================

        /**
         * Render MW calibration lines across the gel.
         * @param {Object} calibrationData - From getMultiCalibration() API
         */
        renderCalibrationLines(calibrationData) {
            // Clear existing lines
            if (this.calibrationLinesGroup) {
                this.calibrationLinesGroup.clear();
            }

            if (!calibrationData?.is_calibrated) {
                console.warn('Cannot render MW lines: no calibration');
                return;
            }

            const calibrations = calibrationData.calibrations || [];

            if (calibrations.length === 0) {
                console.warn('Cannot render MW lines: empty calibrations');
                return;
            }

            // Collect unique MW values from all band_matches across all calibrations
            // This shows lines for ALL actually matched bands, regardless of template
            const matchedMWsMap = new Map(); // mw_kda -> { mw, name }
            for (const cal of calibrations) {
                if (cal.band_matches) {
                    for (const match of cal.band_matches) {
                        const roundedMW = Math.round(match.mw_kda * 100) / 100;
                        if (!matchedMWsMap.has(roundedMW)) {
                            matchedMWsMap.set(roundedMW, {
                                mw_kda: match.mw_kda,
                                name: match.name || ''
                            });
                        }
                    }
                }
            }

            // Sort MW values descending (highest MW at top)
            const sortedMWs = Array.from(matchedMWsMap.values())
                .sort((a, b) => b.mw_kda - a.mw_kda);

            console.log(`Rendering MW lines for ${sortedMWs.length} matched bands across ${calibrations.length} ladders`);

            // For each matched MW value, draw a line using actual band positions
            for (const band of sortedMWs) {
                const mw = band.mw_kda;
                const points = [];

                // Get Y position at each ladder using actual band_matches positions
                for (const cal of calibrations) {
                    const y = this._mwToY(mw, cal);
                    if (y !== null) {
                        points.push({ x: cal.ladder_x_position, y: y });
                    }
                }

                if (points.length >= 1) {
                    // Draw line/curve connecting the points
                    this._drawMWLine(points, mw, band.name);
                }
            }
        }

        /**
         * Get Y position for a MW value using actual band_matches positions.
         * Falls back to coefficient calculation only if MW not found in matches.
         *
         * Using actual band positions ensures MW lines pass exactly through
         * the matched bands, avoiding regression residual offsets (which can
         * be significant at high/low MW where log-linear is less accurate).
         *
         * @param {number} mw - Molecular weight in kDa
         * @param {Object} calibration - Calibration data with band_matches
         * @returns {number|null} Y position in pixels
         */
        _mwToY(mw, calibration) {
            const { band_matches, coefficients, lane_top, lane_bottom, method } = calibration;

            // FIRST: Try to find exact match in band_matches (actual band positions)
            // This ensures lines pass through real band positions, not regression estimates
            if (band_matches && band_matches.length > 0) {
                const match = band_matches.find(m => Math.abs(m.mw_kda - mw) < 0.1);
                if (match) {
                    // Use the actual position_y from the matched band
                    return match.position_y;
                }
            }

            // FALLBACK: Calculate from coefficients (for MWs not in template)
            if (!coefficients || lane_bottom <= lane_top) {
                return null;
            }

            // log₁₀(MW) = slope × Rf + intercept
            // Rf = (log₁₀(MW) - intercept) / slope
            const logMW = Math.log10(mw);
            let rf;

            if (method === 'LOG_LINEAR' || !method) {
                const slope = coefficients.slope;
                const intercept = coefficients.intercept;
                if (!slope || slope === 0) {
                    return null;
                }
                rf = (logMW - intercept) / slope;
            } else if (method && method.startsWith('POLYNOMIAL_')) {
                // For polynomial, would need numeric root finding
                // For now, skip polynomial support
                console.warn('Polynomial MW lines not yet supported');
                return null;
            } else {
                return null;
            }

            // Clamp Rf to valid range
            rf = Math.max(0, Math.min(1, rf));

            // Y = lane_top + Rf × (lane_bottom - lane_top)
            return lane_top + rf * (lane_bottom - lane_top);
        }

        /**
         * Draw a single MW calibration line.
         * @param {Array} points - Array of {x, y} points
         * @param {number} mw - Molecular weight in kDa
         * @param {string} name - Optional band name
         */
        _drawMWLine(points, mw, name) {
            if (!this.calibrationLinesGroup) return;

            // Sort by X position
            points.sort((a, b) => a.x - b.x);

            // Extend line to gel edges (extrapolate)
            const gelWidth = this.svg.width();
            const extendedPoints = this._extendLineToEdges(points, gelWidth);

            // Draw as polyline
            const pathData = extendedPoints.map((p, i) =>
                `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`
            ).join(' ');

            this.calibrationLinesGroup.path(pathData)
                .addClass('gv-mw-line')
                .attr('data-mw', mw);

            // Add MW label at left edge
            const labelY = extendedPoints[0].y;
            const labelText = name ? `${mw} kDa (${name})` : `${mw} kDa`;
            this.calibrationLinesGroup.text(labelText)
                .move(5, labelY - 10)
                .addClass('gv-mw-label')
                .attr('data-mw', mw);
        }

        /**
         * Extend calibration line points to gel edges via linear extrapolation.
         * @param {Array} points - Array of {x, y} points sorted by x
         * @param {number} gelWidth - Width of the gel image
         * @returns {Array} Extended points array
         */
        _extendLineToEdges(points, gelWidth) {
            if (points.length === 0) return [];
            if (points.length === 1) {
                // Single point - extend horizontally
                return [
                    { x: 0, y: points[0].y },
                    { x: points[0].x, y: points[0].y },
                    { x: gelWidth, y: points[0].y }
                ];
            }

            const result = [...points];

            // Extend to left edge (x = 0)
            const first = points[0];
            const second = points[1];
            if (first.x > 0) {
                const slope = (second.y - first.y) / (second.x - first.x);
                const yAtZero = first.y - slope * first.x;
                result.unshift({ x: 0, y: yAtZero });
            }

            // Extend to right edge (x = gelWidth)
            const last = points[points.length - 1];
            const secondLast = points[points.length - 2];
            if (last.x < gelWidth) {
                const slope = (last.y - secondLast.y) / (last.x - secondLast.x);
                const yAtEnd = last.y + slope * (gelWidth - last.x);
                result.push({ x: gelWidth, y: yAtEnd });
            }

            return result;
        }

        // =====================================================================
        // Clear All
        // =====================================================================

        /**
         * Clear all rendered elements.
         */
        clearAll() {
            this.lanesGroup.clear();
            this.bandsGroup.clear();
            if (this.calibrationLinesGroup) {
                this.calibrationLinesGroup.clear();
            }
        }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.Renderer = Renderer;

})(window);
