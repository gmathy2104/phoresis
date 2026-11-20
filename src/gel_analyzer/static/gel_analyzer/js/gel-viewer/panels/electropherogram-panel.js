/**
 * electropherogram-panel.js
 *
 * Electropherogram Panel for the Annotation Editor.
 * Displays the intensity profile of the selected lane using Plotly.js.
 *
 * Features:
 * - Shows intensity profile (processed or raw)
 * - Highlights bands with colored areas
 * - Shows preview peaks during detection
 * - Synchronizes with band selection
 * - Draggable threshold line via Plotly editable shapes
 * - Zoom, pan, hover tooltips out of the box
 *
 * @requires Plotly.js
 * @requires GelViewer.EventBus
 * @requires GelViewer.APIClient
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
     * Color palette for different band types and states.
     */
    const COLORS = {
        profile: '#2196F3',           // Blue - main profile line
        profileRaw: '#90CAF9',        // Light blue - raw profile
        background: 'rgba(200,200,200,0.3)', // Gray - background fill
        backgroundLine: 'rgba(200,200,200,0.6)',
        integrationFill: 'rgba(59,130,246,0.15)',
        integrationLine: 'rgba(59,130,246,0.4)',
        // Band fills: the gel overlay's band colours (gel_viewer_standalone.css .gv-band.*).
        bandOther: 'rgba(34, 197, 94, 0.25)',
        bandPOI: 'rgba(168, 85, 247, 0.25)',
        bandMWReference: 'rgba(249, 115, 22, 0.25)',
        bandCalibration: 'rgba(248, 113, 113, 0.3)',
        peakOrphan: '#FF9800',         // Orange - orphan peaks (preview)
        peakMatched: '#4CAF50',         // Green - matched peaks (preview)
        selected: 'rgba(233, 30, 99, 0.35)',
        threshold: '#ef4444',
        boundaryBaseline: '#3b82f6',
        boundaryValley: '#f59e0b',
        valley: '#9E9E9E',
        derivative1: '#10b981',           // Emerald - 1st derivative line
        derivative2: '#8b5cf6',           // Violet - 2nd derivative line
        derivativePeak: '#ef4444',        // Red - d1 peak markers
        derivativeValley: '#22c55e',      // Green - d1 valley markers
        derivativeInflection: '#06b6d4',  // Cyan - d2 inflection markers
    };

    /**
     * ElectropherogramPanel Class
     *
     * Plotly.js-based panel for visualizing lane intensity profiles.
     */
    class ElectropherogramPanel {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus - Event bus for communication
         * @param {APIClient} options.apiClient - API client for server requests
         * @param {StateManager} options.stateManager - State manager reference
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.apiClient = options.apiClient;
            this.stateManager = options.stateManager;

            // DOM elements
            this.panel = null;
            this.chartContainer = null;
            this.placeholder = null;
            this.loading = null;
            this.footer = null;

            // State
            this.isVisible = false;
            this.plotInitialized = false;
            this.currentLaneId = null;
            this.profileData = null;
            this.previewPeaks = [];
            this.selectedBandId = null;

            // Display options
            this.showRawProfile = false;
            this.showBands = true;
            this.showPeakMax = true;
            this.showBackground = false;
            // Valleys come from the OLD ProfileProcessor (Savitzky-Golay
            // smoothing + rolling-ball + derivative-based valley detection),
            // NOT from the hybrid detection model. They can show split points
            // that the hybrid model doesn't produce, and hide splits that
            // hybrid DOES produce — misleading the user about what's on the
            // gel. Default OFF so the electropherogram reflects hybrid bands
            // only. User can still toggle it on for debug/exploration.
            this.showValleys = false;
            this.showThreshold = true;

            // Derivative display options (controlled by detection panel)
            this.showFirstDerivative = false;
            this.showSecondDerivative = false;
            this.showDerivativeMarkers = false;

            // Threshold state
            this.thresholdValue = null;
            this.integrationBands = null;

            // Reparenting guard — set by DetectionPanelBase during DOM move
            this._reparenting = false;

            // Initialize
            this._init();
        }

        /**
         * Initialize the panel.
         */
        _init() {
            this._setupDOM();
            this._setupToolbar();
            this._bindEvents();
            this._setupBandCreateHandler();
        }

        /**
         * Setup Ctrl+click (Cmd+click on Mac) to create a band at the clicked Y position,
         * and Shift+drag to create a band spanning a range.
         * Empower-style manual peak/band creation.
         */
        _setupBandCreateHandler() {
            if (!this.chartContainer) return;

            // DOM click listener (capture phase) — fires before Plotly's plotly_click.
            // Ctrl+click (or Cmd+click on Mac) creates a band at the clicked Y position.
            this._bandCreateClickHandler = (e) => this._onBandCreateClick(e);
            this.chartContainer.addEventListener('click', this._bandCreateClickHandler, true);

            // Shift+drag to create a range-band
            this._bandDragState = null;
            this._bandDragMoveHandler = (e) => this._onBandDragMove(e);
            this._bandDragUpHandler = (e) => this._onBandDragUp(e);
            this._bandDragMouseDownHandler = (e) => this._onBandDragMouseDown(e);
            this.chartContainer.addEventListener('mousedown', this._bandDragMouseDownHandler, true);

            // Custom DOM cursor guide — a thin vertical line that follows the cursor X.
            // Replaces Plotly's native x-axis spike (which breaks over layout shapes).
            // See _showCursorGuide / _onCursorGuideMouseMove for details.
            this._cursorGuideActive = false;
            this._cursorGuideEl = document.createElement('div');
            this._cursorGuideEl.className = 'gv-electropherogram-cursor-guide';
            Object.assign(this._cursorGuideEl.style, {
                position: 'absolute',
                top: '0',
                bottom: '0',
                width: '1px',
                background: '#ef4444',         // red — matches COLORS.threshold
                pointerEvents: 'none',          // never blocks click/drag handlers
                zIndex: '10',                   // above Plotly plot area
                display: 'none',
                boxShadow: '0 0 0 1px rgba(255, 255, 255, 0.7)',  // halo for contrast
            });
            this.chartContainer.appendChild(this._cursorGuideEl);

            // Container-level mousemove listener — fires for every pointer move,
            // regardless of what SVG element is under the cursor.
            this._cursorGuideMoveHandler = (e) => this._onCursorGuideMouseMove(e);
            this._cursorGuideLeaveHandler = () => this._onCursorGuideMouseLeave();
            this.chartContainer.addEventListener('mousemove', this._cursorGuideMoveHandler);
            this.chartContainer.addEventListener('mouseleave', this._cursorGuideLeaveHandler);

            // Modifier cursor hint: show a fine custom crosshair when Ctrl / Cmd / Shift
            // is held over the chart (band-creation modifiers).
            this._bandCreateKeyDownHandler = (e) => {
                if ((e.ctrlKey || e.metaKey || e.shiftKey) && this.isVisible && !this._teacherMarkState) {
                    this.chartContainer.style.cursor = ElectropherogramPanel.PRECISE_CURSOR;
                    this._showCursorGuide();
                }
            };
            this._bandCreateKeyUpHandler = (e) => {
                // Only reset cursor when NO modifier is held
                if (!(e.ctrlKey || e.metaKey || e.shiftKey)) {
                    if (!this._teacherMarkState && !this._bandDragState) {
                        this.chartContainer.style.cursor = '';
                    }
                    this._hideCursorGuide();
                }
                // Esc cancels an active drag
                if (e.key === 'Escape' && this._bandDragState) {
                    this._cancelBandDrag();
                }
            };
            document.addEventListener('keydown', this._bandCreateKeyDownHandler);
            document.addEventListener('keyup', this._bandCreateKeyUpHandler);
        }

        /**
         * Shift+mousedown on the chart — begin drag-to-create-band.
         */
        _onBandDragMouseDown(e) {
            if (!e.shiftKey) return;
            if (!this.isVisible || this._teacherMarkState) return;
            if (!this.currentLaneId || !this.profileData) return;

            const plotEl = this.chartContainer;
            const xaxis = plotEl._fullLayout?.xaxis;
            if (!xaxis) return;

            e.stopPropagation();
            e.preventDefault();

            const rect = plotEl.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const startDataX = xaxis.p2d(mouseX - xaxis._offset);

            this._bandDragState = { startDataX, lastDataX: startDataX };
            this.chartContainer.style.cursor = ElectropherogramPanel.PRECISE_CURSOR;

            document.addEventListener('mousemove', this._bandDragMoveHandler, true);
            document.addEventListener('mouseup', this._bandDragUpHandler, true);
        }

        /**
         * Mousemove while Shift+dragging — update the temporary dashed overlay rect.
         */
        _onBandDragMove(e) {
            if (!this._bandDragState) return;
            const plotEl = this.chartContainer;
            const xaxis = plotEl._fullLayout?.xaxis;
            if (!xaxis) return;

            const rect = plotEl.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const currentDataX = xaxis.p2d(mouseX - xaxis._offset);
            this._bandDragState.lastDataX = currentDataX;

            const x0 = Math.min(this._bandDragState.startDataX, currentDataX);
            const x1 = Math.max(this._bandDragState.startDataX, currentDataX);

            const shapes = (plotEl.layout?.shapes || []).filter(s => !s._bandDragTemp);
            shapes.push({
                type: 'rect',
                xref: 'x', yref: 'paper',
                x0, x1, y0: 0, y1: 1,
                fillcolor: 'rgba(239, 68, 68, 0.18)',
                line: { color: '#ef4444', width: 1.5, dash: 'dash' },
                _bandDragTemp: true,
            });
            try {
                Plotly.relayout(plotEl, { shapes });
            } catch (err) {
                console.error('[ElectropherogramPanel] drag shape update error:', err);
            }
        }

        /**
         * Mouseup — finalize Shift+drag by creating a range-band via the API.
         */
        async _onBandDragUp(e) {
            if (!this._bandDragState) return;
            document.removeEventListener('mousemove', this._bandDragMoveHandler, true);
            document.removeEventListener('mouseup', this._bandDragUpHandler, true);

            const plotEl = this.chartContainer;
            const xaxis = plotEl._fullLayout?.xaxis;
            const startDataX = this._bandDragState.startDataX;
            let endDataX = this._bandDragState.lastDataX;

            if (xaxis) {
                const rect = plotEl.getBoundingClientRect();
                const mouseX = e.clientX - rect.left;
                endDataX = xaxis.p2d(mouseX - xaxis._offset);
            }

            this._bandDragState = null;
            this._removeBandDragTempShapes();

            if (!e.shiftKey && !e.ctrlKey && !e.metaKey && !this._teacherMarkState) {
                this.chartContainer.style.cursor = '';
            }

            const y0 = Math.round(Math.min(startDataX, endDataX));
            const y1 = Math.round(Math.max(startDataX, endDataX));
            if (y1 - y0 < 3) return;  // too short → probably an accidental click

            const yPositions = this.profileData.y_positions;
            if (!yPositions || y0 < yPositions[0] || y1 > yPositions[yPositions.length - 1]) {
                console.info('[ElectropherogramPanel] Shift+drag outside profile range, ignored.');
                return;
            }

            const lane = this.stateManager.getLane(this.currentLaneId);
            if (!lane) return;
            const positionY = Math.round((y0 + y1) / 2);

            const polygon = this._bandShape(lane, y0, y1);

            this._showStatusToast(`Creating band y=[${y0}, ${y1}]…`, 'loading');
            try {
                const result = await this.apiClient.createBand(this.currentLaneId, {
                    polygon,
                    position_y: positionY,
                    band_type: lane.lane_type === 'LADDER' ? 'MW_REFERENCE' : 'OTHER',
                });
                console.info(`[ElectropherogramPanel] Shift+drag created band id=${result.id} y=[${y0}, ${y1}]`);
                this._showStatusToast(`Band created y=[${y0}, ${y1}]`, 'success');
                this.eventBus.emit(Events.DATA_RELOAD_REQUESTED);
            } catch (err) {
                console.error('[ElectropherogramPanel] Shift+drag create band failed:', err);
                this._showStatusToast(`Create failed: ${err.message || err}`, 'error');
            }
        }

        /**
         * Cancel an in-progress Shift+drag (called from Escape).
         */
        _cancelBandDrag() {
            if (!this._bandDragState) return;
            this._bandDragState = null;
            document.removeEventListener('mousemove', this._bandDragMoveHandler, true);
            document.removeEventListener('mouseup', this._bandDragUpHandler, true);
            this._removeBandDragTempShapes();
            this.chartContainer.style.cursor = '';
        }

        /**
         * Remove any temporary Shift+drag rect overlays from the Plotly layout.
         */
        _removeBandDragTempShapes() {
            if (!this.chartContainer || !this.chartContainer.layout) return;
            const shapes = (this.chartContainer.layout.shapes || []).filter(s => !s._bandDragTemp);
            try {
                Plotly.relayout(this.chartContainer, { shapes });
            } catch (err) {
                console.error('[ElectropherogramPanel] drag temp cleanup error:', err);
            }
        }

        /**
         * Show the custom DOM cursor guide (vertical red line following the cursor).
         *
         * Replaces Plotly's native x-axis spike, which relies on hover events — and
         * hover does NOT fire when the cursor is over an SVG layout shape (e.g. band
         * highlight rects), because the shape element catches the pointer event
         * before Plotly's hover system sees it. Tuning hoverdistance doesn't help:
         * hover simply doesn't fire at all. The DOM overlay works everywhere because
         * we read `e.clientX` directly on a container-level mousemove listener.
         */
        _showCursorGuide() {
            if (!this.chartContainer || !this._cursorGuideEl) return;
            this._cursorGuideActive = true;
        }

        /**
         * Hide the custom DOM cursor guide.
         */
        _hideCursorGuide() {
            this._cursorGuideActive = false;
            if (this._cursorGuideEl) {
                this._cursorGuideEl.style.display = 'none';
            }
        }

        /**
         * Mousemove handler on chartContainer — positions the cursor guide DIV at
         * the cursor's X coordinate. Fires regardless of what's under the cursor
         * (shapes, profile trace, empty area) because the listener is on the
         * container itself, not tied to Plotly data hover.
         */
        _onCursorGuideMouseMove(e) {
            if (!this._cursorGuideActive || !this._cursorGuideEl) return;
            const rect = this.chartContainer.getBoundingClientRect();
            const x = e.clientX - rect.left;
            // Hide if outside chart area (negative or beyond right edge)
            if (x < 0 || x > rect.width) {
                this._cursorGuideEl.style.display = 'none';
                return;
            }
            this._cursorGuideEl.style.left = `${x}px`;
            this._cursorGuideEl.style.display = 'block';
        }

        /**
         * Mouseleave handler on chartContainer — hide the guide when cursor exits.
         */
        _onCursorGuideMouseLeave() {
            if (this._cursorGuideEl) {
                this._cursorGuideEl.style.display = 'none';
            }
        }

        /**
         * Handle Ctrl+click / Cmd+click on the chart: create a band at the clicked Y position.
         */
        async _onBandCreateClick(e) {
            // Only handle Ctrl+click / Cmd+click (Mac)
            if (!(e.ctrlKey || e.metaKey)) return;
            // Respect teacher mode
            if (this._teacherMarkState) return;
            // Need a lane loaded
            if (!this.currentLaneId || !this.profileData) return;
            if (!this.chartContainer) return;

            // Stop Plotly from processing this click (it would select a band)
            e.stopPropagation();
            e.preventDefault();

            // Convert clientX to data coordinate (profile Y position).
            const plotEl = this.chartContainer;
            const xaxis = plotEl._fullLayout?.xaxis;
            if (!xaxis) return;
            const rect = plotEl.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const positionY = Math.round(xaxis.p2d(mouseX - xaxis._offset));

            // Validate position is inside profile range
            const yPositions = this.profileData.y_positions;
            if (!yPositions || positionY < yPositions[0] || positionY > yPositions[yPositions.length - 1]) {
                console.info('[ElectropherogramPanel] Ctrl+click outside profile range, ignored.');
                return;
            }

            // Get lane bounds for bbox_x / bbox_width / default height
            const lane = this.stateManager.getLane(this.currentLaneId);
            if (!lane) return;

            // IF the click falls INSIDE an existing band → SPLIT that band at
            // the click position. Otherwise create a new band at Y.
            const hitBand = this._findBandAtY(lane, positionY);
            if (hitBand) {
                await this._splitBandAtY(hitBand, positionY, lane);
                return;
            }

            // Default band height for new-band creation — small, scientist
            // will resize if needed.
            const DEFAULT_BAND_HEIGHT = 10;
            const bboxY = Math.max(0, positionY - Math.floor(DEFAULT_BAND_HEIGHT / 2));
            const bboxHeight = DEFAULT_BAND_HEIGHT;

            const polygon = this._bandShape(lane, bboxY, bboxY + bboxHeight);

            this._showStatusToast(`Creating band at y=${positionY}…`, 'loading');
            try {
                const result = await this.apiClient.createBand(this.currentLaneId, {
                    polygon: polygon,
                    position_y: positionY,
                    band_type: lane.lane_type === 'LADDER' ? 'MW_REFERENCE' : 'OTHER',
                });
                console.info(`[ElectropherogramPanel] Ctrl+click created band id=${result.id} at y=${positionY}`);
                this._showStatusToast(`Band created at y=${positionY}`, 'success');
                this.eventBus.emit(Events.DATA_RELOAD_REQUESTED);
            } catch (error) {
                console.error('[ElectropherogramPanel] Ctrl+click create band failed:', error);
                this._showStatusToast(`Create failed: ${error.message || error}`, 'error');
            }
        }

        /**
         * Find the first existing band whose bbox_y..bbox_y+bbox_height range
         * contains the given profile Y position. Returns the band object or null.
         */
        _findBandAtY(lane, positionY) {
            if (!lane || !Array.isArray(lane.bands)) return null;
            for (const band of lane.bands) {
                if (band.bbox_y == null || band.bbox_height == null) continue;
                const top = band.bbox_y;
                const bottom = band.bbox_y + band.bbox_height;
                // Strictly inside — click right on the edge shouldn't split
                if (positionY > top && positionY < bottom) {
                    return band;
                }
            }
            return null;
        }

        /**
         * A band's outline between two rows: the lane's outline cut there (shared/lane-geometry.js `slice`, the band
         * model's rule, yolo_bands.py::_build), so a band made on a tilted lane follows its slant; the lane box's slice
         * when a row falls off the outline. Corners rounded, as the lanes'.
         */
        _bandShape(lane, yTop, yBottom) {
            const G = GelAnalyzer.LaneGeometry;
            const slice = G.slice(G.outline(lane), yTop, yBottom);
            if (slice) return G.clampRound(slice, Infinity, Infinity);
            const x = lane.x ?? lane.bbox?.x ?? 0;
            const w = lane.width ?? lane.bbox?.width ?? 40;
            return [[x, yTop], [x + w, yTop], [x + w, yBottom], [x, yBottom]];
        }

        /**
         * Split an existing band into two at the given Y position.
         *
         * Behavior (per user spec):
         *   - Upper band: same top edge as original, bottom edge = splitY.
         *   - Lower band: top edge = splitY, bottom edge = original bottom.
         *   - Original band is deleted.
         *   - On a tilted lane each half is the lane's outline cut at its rows (`_bandShape`), as a new band would
         *     be, so the halves follow its slant; on an upright lane (a rectangle, a Straight accept) each half keeps
         *     the band's own x extent, as before tilted lanes (a band drawn narrower than its lane stays narrow).
         *
         * After the 3 API calls complete, emit DATA_RELOAD_REQUESTED so both
         * the electropherogram and the main gel viewer re-fetch and display
         * the new bands side by side.
         */
        async _splitBandAtY(band, splitY, lane) {
            const top = band.bbox_y;
            const bottom = band.bbox_y + band.bbox_height;
            const MIN_H = 3;
            if (splitY - top < MIN_H || bottom - splitY < MIN_H) {
                this._showStatusToast('Split too close to edge — ignored', 'error');
                return;
            }

            const bandType = band.band_type || (lane.lane_type === 'LADDER' ? 'MW_REFERENCE' : 'OTHER');
            const parentLaneId = band.lane_id || this.currentLaneId;

            const G = GelAnalyzer.LaneGeometry;
            const tilted = !G.isUprightBox(G.outline(lane));
            const half = (yTop, yBottom) => (tilted
                ? this._bandShape(lane, yTop, yBottom)
                : [[band.bbox_x, yTop], [band.bbox_x + band.bbox_width, yTop],
                    [band.bbox_x + band.bbox_width, yBottom], [band.bbox_x, yBottom]]);
            const upperPolygon = half(top, splitY);
            const lowerPolygon = half(splitY, bottom);
            const upperPosY = Math.round((top + splitY) / 2);
            const lowerPosY = Math.round((splitY + bottom) / 2);

            this._showStatusToast(`Splitting band at y=${splitY}…`, 'loading');
            try {
                await this.apiClient.deleteBand(band.id);
                await this.apiClient.createBand(parentLaneId, {
                    polygon: upperPolygon,
                    position_y: upperPosY,
                    band_type: bandType,
                    label: band.label ? `${band.label} (upper)` : '',
                    notes: band.notes || '',
                });
                await this.apiClient.createBand(parentLaneId, {
                    polygon: lowerPolygon,
                    position_y: lowerPosY,
                    band_type: bandType,
                    label: band.label ? `${band.label} (lower)` : '',
                    notes: band.notes || '',
                });
                console.info(`[ElectropherogramPanel] Split band ${band.id} at y=${splitY} → upper[${top},${splitY}] + lower[${splitY},${bottom}]`);
                this._showStatusToast(`Band split at y=${splitY}`, 'success');
                // Reload so both the electropherogram AND the main gel
                // viewer pick up the new bands.
                this.eventBus.emit(Events.DATA_RELOAD_REQUESTED);
            } catch (error) {
                console.error('[ElectropherogramPanel] Split-at-Y failed:', error);
                this._showStatusToast(`Split failed: ${error.message || error}`, 'error');
            }
        }

        /**
         * Show a small floating toast inside the chart area.
         * type: 'loading' (spinner, stays), 'success' (green, auto-dismiss 2s),
         *       'error' (red, auto-dismiss 4s).
         * Replaces any existing toast.
         */
        _showStatusToast(message, type = 'loading') {
            if (!this.chartContainer) return;

            // Reuse existing toast element if present
            if (!this._statusToastEl) {
                const toast = document.createElement('div');
                toast.className = 'gv-epgram-status-toast';
                this.chartContainer.appendChild(toast);
                this._statusToastEl = toast;
            }
            const toast = this._statusToastEl;

            // Clear any previous auto-dismiss timer
            if (this._statusToastTimer) {
                clearTimeout(this._statusToastTimer);
                this._statusToastTimer = null;
            }

            // Icon per type
            const icon = {
                loading: '<span class="gv-epgram-spinner-inline"></span>',
                success: '<i class="bi bi-check-circle-fill"></i>',
                error: '<i class="bi bi-exclamation-triangle-fill"></i>',
            }[type] || '';

            toast.className = `gv-epgram-status-toast gv-epgram-status-${type}`;
            toast.innerHTML = `${icon}<span>${escapeHtml(message)}</span>`;
            toast.style.display = 'flex';

            // Auto-dismiss non-loading toasts
            if (type === 'success') {
                this._statusToastTimer = setTimeout(() => this._hideStatusToast(), 2000);
            } else if (type === 'error') {
                this._statusToastTimer = setTimeout(() => this._hideStatusToast(), 4000);
            }
        }

        _hideStatusToast() {
            if (this._statusToastEl) {
                this._statusToastEl.style.display = 'none';
            }
            if (this._statusToastTimer) {
                clearTimeout(this._statusToastTimer);
                this._statusToastTimer = null;
            }
        }

        /**
         * Setup DOM references.
         */
        _setupDOM() {
            this.panel = document.getElementById('electropherogram-panel');
            this.chartContainer = document.getElementById('electropherogram-chart');
            this.placeholder = document.getElementById('electropherogram-placeholder');
            this.loading = document.getElementById('electropherogram-loading');
            this.footer = document.getElementById('electropherogram-footer');

            // Close button
            const closeBtn = document.getElementById('electropherogram-close');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this.hide());
            }

            // Keyboard-shortcuts help popover
            const helpBtn = document.getElementById('electropherogram-help-btn');
            const helpPopover = document.getElementById('electropherogram-help-popover');
            if (helpBtn && helpPopover) {
                const hideHelp = () => {
                    helpPopover.setAttribute('hidden', '');
                    helpBtn.setAttribute('aria-expanded', 'false');
                    global.GelViewer.Layers?.close(helpPopover);
                };
                helpBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const isShown = !helpPopover.hasAttribute('hidden');
                    if (isShown) {
                        hideHelp();
                    } else {
                        helpPopover.removeAttribute('hidden');
                        helpBtn.setAttribute('aria-expanded', 'true');
                        // Esc closes the help alone, not the panel under it.
                        global.GelViewer.Layers?.open(helpPopover, {
                            close: hideHelp,
                            isOpen: () => !helpPopover.hasAttribute('hidden'),
                        });
                    }
                });
                // Close on outside click
                document.addEventListener('click', (e) => {
                    if (!helpBtn.contains(e.target) && !helpPopover.contains(e.target)) {
                        helpPopover.setAttribute('hidden', '');
                        helpBtn.setAttribute('aria-expanded', 'false');
                    }
                });
            }

            // Toggle buttons
            this._setupToggleButton('electropherogram-toggle-raw', 'showRawProfile');
            this._setupToggleButton('electropherogram-toggle-bands', 'showBands');
            this._setupToggleButton('electropherogram-toggle-peakmax', 'showPeakMax');
            this._setupToggleButton('electropherogram-toggle-background', 'showBackground');
            this._setupToggleButton('electropherogram-toggle-valleys', 'showValleys');
            this._setupToggleButton('electropherogram-toggle-threshold', 'showThreshold');

            // ResizeObserver for responsive chart
            this._setupResizeObserver();

            // Custom resize handle (bottom-left)
            this._setupResizeHandle();

            // Docked under the gel: the splitter on its top edge
            this._setupDockSplitter();
        }

        /**
         * The docked profile's splitter (owner, 2026-10-17): its top edge, dragged up or down, shares the height
         * between the gel and the profile; Up/Down move it by 20 px (Shift: 80), a double-click gives back the default
         * height. The height lives in --gv-profile-dock-height on the panel, which only the docked layout reads (the
         * floating profile keeps its corner handle), and is remembered by this browser. The gel area shrinks or grows
         * with it, and a gel shown whole re-fits itself (viewport.js); Plotly follows through _setupResizeObserver.
         */
        _setupDockSplitter() {
            const splitter = document.getElementById('electropherogram-dock-splitter');
            if (!splitter || !this.panel) return;

            const STORAGE_KEY = 'gv-profile-dock-height';
            const MIN_PROFILE = 140;  // px: the toolbar and a readable plot
            const MIN_GEL = 160;      // px left to the gel area above
            const panel = this.panel;

            const apply = (height, remember) => {
                const room = panel.parentElement ? panel.parentElement.clientHeight : global.innerHeight;
                const h = Math.round(Math.max(MIN_PROFILE, Math.min(height, room - MIN_GEL)));
                panel.style.setProperty('--gv-profile-dock-height', `${h}px`);
                splitter.setAttribute('aria-valuenow', String(h));
                if (remember) {
                    try {
                        global.localStorage.setItem(STORAGE_KEY, String(h));
                    } catch (e) {
                        // Storage refused (private window, blocked site data): the height holds for this page only.
                    }
                }
            };

            // The height this browser kept, bounded at its first drag (the window may be smaller today).
            try {
                const kept = Number(global.localStorage.getItem(STORAGE_KEY));
                if (kept >= MIN_PROFILE) panel.style.setProperty('--gv-profile-dock-height', `${kept}px`);
            } catch (e) {
                // Storage unreadable: the default height.
            }

            let drag = null;
            splitter.addEventListener('pointerdown', (e) => {
                if (e.button !== 0) return;
                e.preventDefault();  // no text selection, no focus jump
                drag = { y: e.clientY, height: panel.offsetHeight };
                try {
                    // The moves keep coming to the splitter when the pointer leaves its 8 px.
                    splitter.setPointerCapture(e.pointerId);
                } catch (err) {
                    // A pointer no longer active (released before this ran): the drag still follows the moves here.
                }
                splitter.classList.add('is-dragging');
                document.body.classList.add('gv-dock-resizing');
            });
            splitter.addEventListener('pointermove', (e) => {
                if (drag) apply(drag.height + (drag.y - e.clientY), false);
            });
            const end = () => {
                if (!drag) return;
                drag = null;
                splitter.classList.remove('is-dragging');
                document.body.classList.remove('gv-dock-resizing');
                apply(panel.offsetHeight, true);
            };
            splitter.addEventListener('pointerup', end);
            splitter.addEventListener('pointercancel', end);
            splitter.addEventListener('lostpointercapture', end);

            splitter.addEventListener('dblclick', () => {
                panel.style.removeProperty('--gv-profile-dock-height');
                splitter.removeAttribute('aria-valuenow');
                try {
                    global.localStorage.removeItem(STORAGE_KEY);
                } catch (e) {
                    // Nothing kept to forget.
                }
            });

            splitter.addEventListener('keydown', (e) => {
                if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
                e.preventDefault();
                // The editor's keys listen on document: an arrow here must not move the selected lane too.
                e.stopPropagation();
                const step = e.shiftKey ? 80 : 20;
                apply(panel.offsetHeight + (e.key === 'ArrowUp' ? step : -step), true);
            });
        }

        /**
         * Setup ResizeObserver for responsive chart.
         */
        _setupResizeObserver() {
            if (!this.chartContainer || !window.ResizeObserver) return;

            let resizeTimeout;
            this.resizeObserver = new ResizeObserver(() => {
                clearTimeout(resizeTimeout);
                resizeTimeout = setTimeout(() => {
                    if (this.isVisible && this.profileData && this.plotInitialized) {
                        try {
                            Plotly.Plots.resize(this.chartContainer);
                        } catch (e) {
                            console.error('[ElectropherogramPanel] Plotly resize error:', e);
                        }
                    }
                }, 100);
            });

            this.resizeObserver.observe(this.chartContainer);
        }

        /**
         * Setup custom resize handle for bottom-left corner.
         */
        _setupResizeHandle() {
            const handle = document.getElementById('electropherogram-resize-handle');
            if (!handle || !this.panel) return;

            let isResizing = false;
            let startX, startY, startWidth, startHeight;

            const onMouseDown = (e) => {
                e.preventDefault();
                isResizing = true;
                startX = e.clientX;
                startY = e.clientY;
                startWidth = this.panel.offsetWidth;
                startHeight = this.panel.offsetHeight;

                this.panel.classList.add('resizing');
                document.addEventListener('mousemove', onMouseMove);
                document.addEventListener('mouseup', onMouseUp);
            };

            const onMouseMove = (e) => {
                if (!isResizing) return;

                const deltaX = startX - e.clientX;
                const deltaY = e.clientY - startY;

                const newWidth = Math.max(400, Math.min(startWidth + deltaX, window.innerWidth * 0.9));
                const newHeight = Math.max(350, Math.min(startHeight + deltaY, window.innerHeight * 0.8));

                this.panel.style.width = `${newWidth}px`;
                this.panel.style.height = `${newHeight}px`;
            };

            const onMouseUp = () => {
                isResizing = false;
                this.panel.classList.remove('resizing');
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);

                // Plotly auto-resizes via ResizeObserver
            };

            handle.addEventListener('mousedown', onMouseDown);
        }

        /**
         * Setup custom chart toolbar (zoom/pan toggle, reset zoom, download PNG).
         * Replaces the Plotly modebar with a consistent custom UI.
         */
        _setupToolbar() {
            const zoomBtn = document.getElementById('electropherogram-mode-zoom');
            const panBtn = document.getElementById('electropherogram-mode-pan');
            const resetBtn = document.getElementById('electropherogram-reset-zoom');
            const downloadBtn = document.getElementById('electropherogram-download');

            if (zoomBtn) {
                zoomBtn.addEventListener('click', () => {
                    this._setDragMode('zoom');
                    zoomBtn.classList.add('active');
                    panBtn?.classList.remove('active');
                });
            }

            if (panBtn) {
                panBtn.addEventListener('click', () => {
                    this._setDragMode('pan');
                    panBtn.classList.add('active');
                    zoomBtn?.classList.remove('active');
                });
            }

            if (resetBtn) {
                resetBtn.addEventListener('click', () => this.resetZoom());
            }

            if (downloadBtn) {
                downloadBtn.addEventListener('click', () => this._downloadPNG());
            }
        }

        /**
         * Set the Plotly drag mode (zoom or pan).
         * @param {string} mode - 'zoom' or 'pan'
         */
        _setDragMode(mode) {
            if (!this.chartContainer || !this.plotInitialized) return;
            try {
                Plotly.relayout(this.chartContainer, { dragmode: mode });
            } catch (e) {
                console.error('[ElectropherogramPanel] dragmode error:', e);
            }
        }

        /**
         * Reset zoom to auto-range on both axes.
         */
        resetZoom() {
            if (!this.chartContainer || !this.plotInitialized) return;
            try {
                const update = {
                    'xaxis.autorange': true,
                    'yaxis.autorange': true,
                };
                // Reset derivative subplot axes if present
                if (this.showFirstDerivative) update['yaxis2.autorange'] = true;
                if (this.showSecondDerivative) update['yaxis3.autorange'] = true;
                Plotly.relayout(this.chartContainer, update);
            } catch (e) {
                console.error('[ElectropherogramPanel] resetZoom error:', e);
            }
        }

        /**
         * Download the chart as a PNG image.
         */
        _downloadPNG() {
            if (!this.chartContainer || !this.plotInitialized || typeof Plotly === 'undefined') return;
            // The PNG goes into reports: it keeps the light colours it always had, whatever Night | Day the page
            // shows (a copy of the layout is recoloured; the chart on screen is left as it is).
            const light = { bg: '#ffffff', legendBg: 'rgba(255,255,255,0.9)', text: '#334155', muted: '#6b7280',
                grid: '#e5e7eb', zero: '#94a3b8' };
            const layout = JSON.parse(JSON.stringify(this.chartContainer.layout || {}));
            layout.paper_bgcolor = 'transparent';
            layout.plot_bgcolor = light.bg;
            layout.font = Object.assign({}, layout.font, { color: light.muted });
            if (layout.legend) {
                layout.legend.bgcolor = light.legendBg;
                layout.legend.bordercolor = light.grid;
                layout.legend.font = Object.assign({}, layout.legend.font, { color: light.muted });
            }
            ['xaxis', 'yaxis', 'yaxis2', 'yaxis3'].forEach((name) => {
                const axis = layout[name];
                if (!axis) return;
                axis.gridcolor = light.grid;
                axis.zerolinecolor = light.zero;
                if (axis.title) axis.title.font = Object.assign({}, axis.title.font, { color: light.text });
            });
            Plotly.downloadImage({ data: this.chartContainer.data, layout }, {
                format: 'png',
                filename: `electropherogram_lane_${this.currentLaneId}`,
                height: 500,
                width: 800,
                scale: 2,
            });
        }

        /**
         * Setup a toggle button.
         */
        _setupToggleButton(buttonId, property) {
            const btn = document.getElementById(buttonId);
            if (btn) {
                btn.classList.toggle('active', this[property]);
                btn.dataset.active = String(this[property]);

                btn.addEventListener('click', () => {
                    this[property] = !this[property];
                    btn.classList.toggle('active', this[property]);
                    btn.dataset.active = String(this[property]);
                    if (this.profileData) {
                        this._render();
                    }
                });
            }
        }

        /**
         * Bind event listeners.
         */
        _bindEvents() {
            // Night | Day: the chart is drawn by script, its colours follow on a relayout (the zoom stays).
            window.addEventListener('dsh:themechange', () => this._applyPlotTheme());

            // Selection changed - handle lane and band selection
            this.eventBus.on(Events.SELECTION_CHANGED, (data) => {
                if (!data) return;

                if (data.type === 'lane') {
                    if (this.isVisible) {
                        this.loadProfile(data.id);
                    }
                } else if (data.type === 'band') {
                    this.selectedBandId = data.id;

                    const band = this.stateManager.getBand(data.id);
                    if (band && this.isVisible) {
                        const parentLaneId = band.lane_id || band._parentLaneId;
                        if (parentLaneId && parentLaneId !== this.currentLaneId) {
                            this.loadProfile(parentLaneId);
                        } else if (this.profileData) {
                            this._render();
                        }
                    } else if (this.profileData) {
                        this._render();
                    }
                }
            });

            // Selection cleared
            this.eventBus.on(Events.SELECTION_CLEARED, () => {
                this.selectedBandId = null;
                if (this.profileData) {
                    this._render();
                }
            });

            // Band detection preview
            this.eventBus.on(Events.BAND_DETECTION_PREVIEW, (data) => {
                if (data && data.bands) {
                    this.previewPeaks = data.bands.map(b => ({
                        y: b.position_y,
                        isOrphan: true,
                    }));
                    this.integrationBands = data.bands;
                    if (data.profile) {
                        this.profileData = data.profile;
                        if (!this.profileData.intensities && this.profileData.processed_intensities) {
                            this.profileData.intensities = this.profileData.processed_intensities;
                        }
                    }
                    this._render();
                }
            });

            // Clear detection preview
            this.eventBus.on(Events.BAND_DETECTION_PREVIEW_CLEAR, () => {
                this.previewPeaks = [];
                this.integrationBands = null;
                if (this.profileData) {
                    this._render();
                }
            });

            // Threshold changed from detection panel or drag
            this.eventBus.on(Events.THRESHOLD_CHANGED, (data) => {
                this.thresholdValue = data.value;
                if (this.isVisible && this.profileData) {
                    this._render();
                }
            });

            // Data reloaded — defer if panel is being reparented between DOM parents
            this.eventBus.on(Events.DATA_RELOAD_REQUESTED, () => {
                if (this._reparenting) {
                    // Defer until reparent completes (flag cleared in DetectionPanelBase.unembedElectropherogram)
                    console.info('[ElectropherogramPanel] Deferring reload during reparent');
                    return;
                }
                if (this.isVisible && this.currentLaneId) {
                    this.loadProfile(this.currentLaneId);
                }
            });

            // Band detection lifecycle — show loading indicator during detection
            this.eventBus.on(Events.BAND_DETECTION_STARTED, () => {
                if (this.isVisible) {
                    this._showLoading();
                }
            });
            this.eventBus.on(Events.BAND_DETECTION_COMPLETED, () => {
                if (this.isVisible && this.currentLaneId) {
                    this.loadProfile(this.currentLaneId);
                }
            });

            // Teacher profile marking mode
            this._teacherMarkState = null;
            this._teacherRegions = {};
            this.eventBus.on(Events.TEACHER_MARK_PROFILE_START, (data) => {
                this._enterTeacherMarkMode(data.step);
            });

            this.eventBus.on(Events.TEACHER_PANEL_HIDDEN, () => {
                this._clearTeacherRegions();
            });

            // Esc: GelViewer.Layers (show) calls _closeOnEscape.
        }

        /**
         * Esc on the panel: the teacher's mark mode is left first (the panel stays), then the panel closes.
         * @returns {boolean} false when the panel stays open
         */
        _closeOnEscape() {
            if (this._teacherMarkState) {
                this._exitTeacherMarkMode();
                return false;
            }
            this.hide();
            return true;
        }

        /**
         * Step-specific colors matching CSS vars in gel_viewer_standalone.css.
         */
        static TEACHER_COLORS = {
            background:  { stroke: '#3b82f6', fill: 'rgba(59, 130, 246, 0.15)' },
            small_band:  { stroke: '#22c55e', fill: 'rgba(34, 197, 94, 0.15)' },
            large_band:  { stroke: '#f97316', fill: 'rgba(249, 115, 22, 0.15)' },
        };

        /**
         * High-precision custom crosshair cursor used when Ctrl/Cmd is held
         * over the electropherogram for band creation. A fine red + with a
         * central gap, white halo for contrast on any background, and a
         * 0.6px red dot at the exact hotspot (10,10) — so the user sees
         * exactly which pixel they're about to click on.
         *
         * Rendered as a 20×20 data-URI SVG; hotspot is centered.
         */
        static PRECISE_CURSOR = (function() {
            const svg = "<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 20 20'>"
                + "<line x1='10' y1='1' x2='10' y2='7' stroke='white' stroke-width='3' stroke-linecap='round'/>"
                + "<line x1='10' y1='13' x2='10' y2='19' stroke='white' stroke-width='3' stroke-linecap='round'/>"
                + "<line x1='1' y1='10' x2='7' y2='10' stroke='white' stroke-width='3' stroke-linecap='round'/>"
                + "<line x1='13' y1='10' x2='19' y2='10' stroke='white' stroke-width='3' stroke-linecap='round'/>"
                + "<circle cx='10' cy='10' r='1.8' fill='white'/>"
                + "<line x1='10' y1='1' x2='10' y2='7' stroke='%23ef4444' stroke-width='1.2'/>"
                + "<line x1='10' y1='13' x2='10' y2='19' stroke='%23ef4444' stroke-width='1.2'/>"
                + "<line x1='1' y1='10' x2='7' y2='10' stroke='%23ef4444' stroke-width='1.2'/>"
                + "<line x1='13' y1='10' x2='19' y2='10' stroke='%23ef4444' stroke-width='1.2'/>"
                + "<circle cx='10' cy='10' r='0.6' fill='%23ef4444'/>"
                + "</svg>";
            return `url("data:image/svg+xml;utf8,${svg}") 10 10, crosshair`;
        })();

        /**
         * Enter teacher profile marking mode.
         */
        _enterTeacherMarkMode(step) {
            this._exitTeacherMarkMode();

            this._teacherMarkState = { step: step, firstY: null };

            if (!this.isVisible) this.show();

            if (this.chartContainer) {
                this.chartContainer.style.cursor = 'crosshair';
                this._teacherClickHandler = (e) => this._onTeacherClick(e);
                this._teacherMoveHandler = (e) => this._onTeacherMouseMove(e);
                this.chartContainer.addEventListener('click', this._teacherClickHandler);
                this.chartContainer.addEventListener('mousemove', this._teacherMoveHandler);
            }
        }

        _exitTeacherMarkMode() {
            this._teacherMarkState = null;
            if (this.chartContainer) {
                this.chartContainer.style.cursor = '';
                if (this._teacherClickHandler) {
                    this.chartContainer.removeEventListener('click', this._teacherClickHandler);
                    this._teacherClickHandler = null;
                }
                if (this._teacherMoveHandler) {
                    this.chartContainer.removeEventListener('mousemove', this._teacherMoveHandler);
                    this._teacherMoveHandler = null;
                }
            }
            // Remove temporary teacher shapes from the plot
            this._removeTeacherTempShapes();
        }

        /**
         * Handle teacher click on the Plotly chart.
         * Uses Plotly's layout coordinate system.
         */
        _onTeacherClick(e) {
            if (!this._teacherMarkState || !this.profileData) return;

            // Get the x-axis position from click coordinates
            const plotEl = this.chartContainer;
            const xaxis = plotEl._fullLayout?.xaxis;
            if (!xaxis) return;

            const rect = plotEl.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const posValue = xaxis.p2d(mouseX - xaxis._offset);

            const stepKey = this._teacherMarkState.step;

            if (this._teacherMarkState.firstY === null) {
                this._teacherMarkState.firstY = posValue;
                // Add a temporary vertical line shape
                this._addTeacherTempShape(posValue, stepKey);
            } else {
                // Second click — promote to permanent region
                const y1 = Math.round(this._teacherMarkState.firstY);
                const y2 = Math.round(posValue);

                this._promoteTeacherRegion(stepKey, Math.min(y1, y2), Math.max(y1, y2));

                this.eventBus.emit(Events.TEACHER_MARK_PROFILE_RESULT, {
                    y_start: Math.min(y1, y2),
                    y_end: Math.max(y1, y2),
                });
                this._exitTeacherMarkMode();
            }
        }

        _onTeacherMouseMove(e) {
            if (!this._teacherMarkState || this._teacherMarkState.firstY === null) return;
            if (!this.profileData) return;

            const plotEl = this.chartContainer;
            const xaxis = plotEl._fullLayout?.xaxis;
            if (!xaxis) return;

            const rect = plotEl.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const cursorPos = xaxis.p2d(mouseX - xaxis._offset);

            const stepKey = this._teacherMarkState.step;
            const colors = ElectropherogramPanel.TEACHER_COLORS[stepKey]
                || ElectropherogramPanel.TEACHER_COLORS.large_band;

            // Update temporary region shape
            const firstY = this._teacherMarkState.firstY;
            const x0 = Math.min(firstY, cursorPos);
            const x1 = Math.max(firstY, cursorPos);

            const layout = plotEl.layout || {};
            const shapes = (layout.shapes || []).filter(s => !s._teacherTemp);

            // Add temporary region shape
            shapes.push({
                type: 'rect',
                xref: 'x', yref: 'paper',
                x0: x0, x1: x1, y0: 0, y1: 1,
                fillcolor: colors.fill,
                line: { color: colors.stroke, width: 1 },
                _teacherTemp: true,
            });

            try {
                Plotly.relayout(plotEl, { shapes: shapes });
            } catch (e) {
                console.error('[ElectropherogramPanel] Plotly relayout error:', e);
            }
        }

        _addTeacherTempShape(posValue, stepKey) {
            const colors = ElectropherogramPanel.TEACHER_COLORS[stepKey]
                || ElectropherogramPanel.TEACHER_COLORS.large_band;

            const plotEl = this.chartContainer;
            const layout = plotEl.layout || {};
            const shapes = [...(layout.shapes || [])];

            shapes.push({
                type: 'line',
                xref: 'x', yref: 'paper',
                x0: posValue, x1: posValue, y0: 0, y1: 1,
                line: { color: colors.stroke, width: 1.5, dash: 'dash' },
                _teacherTemp: true,
            });

            try {
                Plotly.relayout(plotEl, { shapes: shapes });
            } catch (e) {
                console.error('[ElectropherogramPanel] Plotly relayout error:', e);
            }
        }

        _removeTeacherTempShapes() {
            if (!this.chartContainer || !this.chartContainer.layout) return;
            const shapes = (this.chartContainer.layout.shapes || []).filter(s => !s._teacherTemp);
            try {
                Plotly.relayout(this.chartContainer, { shapes: shapes });
            } catch (e) {
                console.error('[ElectropherogramPanel] Plotly relayout error:', e);
            }
        }

        /**
         * Promote a teacher region to a persistent overlay.
         */
        _promoteTeacherRegion(stepKey, posStart, posEnd) {
            // Remove previous permanent region for this step
            if (this._teacherRegions[stepKey]) {
                delete this._teacherRegions[stepKey];
            }

            const colors = ElectropherogramPanel.TEACHER_COLORS[stepKey]
                || ElectropherogramPanel.TEACHER_COLORS.large_band;

            this._teacherRegions[stepKey] = {
                x0: posStart, x1: posEnd,
                fillcolor: colors.fill,
                linecolor: colors.stroke,
                label: stepKey.replace('_', ' '),
            };

            // Re-render to include persistent regions
            this._render();
        }

        /**
         * Remove all persistent teacher region overlays.
         */
        _clearTeacherRegions() {
            this._teacherRegions = {};
            if (this.profileData) {
                this._render();
            }
        }

        /**
         * Check if panel is in embedded mode.
         */
        get isEmbedded() {
            return this.panel && this.panel.classList.contains('gv-embedded');
        }

        /**
         * Show the panel.
         */
        show() {
            if (this.panel) {
                this.panel.style.display = 'flex';
                global.GelViewer.Layers?.open(this.panel, {
                    close: () => this._closeOnEscape(),
                    isOpen: () => this.isVisible,
                });
            }
            this.isVisible = true;

            // Load profile for currently selected lane
            const selection = this.stateManager.getSelection();
            if (selection && selection.type === 'lane') {
                this.loadProfile(selection.id);
            }
        }

        /**
         * Hide the panel.
         */
        hide() {
            this._cancelDeferredRender();
            this._hideCursorGuide();
            if (this.panel) {
                this.panel.style.display = 'none';
                global.GelViewer.Layers?.close(this.panel);
            }
            this.isVisible = false;
        }

        /**
         * Toggle visibility.
         */
        toggle() {
            if (this.isVisible) {
                this.hide();
            } else {
                this.show();
            }
        }

        /**
         * Load and display profile for a lane.
         * @param {number} laneId - Lane ID
         */
        async loadProfile(laneId) {
            if (!laneId) return;

            this.currentLaneId = laneId;
            this._showLoading();

            try {
                const response = await this.apiClient.getLaneProfile(laneId);

                if (response.success && response.profile) {
                    this.profileData = response.profile;
                    this._updateLaneInfo(laneId);
                    this._render();
                    this._showFooter();
                } else {
                    throw new Error(response.error || 'Failed to load profile');
                }

            } catch (error) {
                console.error('[ElectropherogramPanel] Error loading profile:', error);
                this._showPlaceholder();
            }
        }

        /**
         * Update lane info display.
         */
        _updateLaneInfo(laneId) {
            const lane = this.stateManager.getLane(laneId);
            const infoEl = document.getElementById('electropherogram-lane-info');
            if (infoEl && lane) {
                infoEl.textContent = `Lane ${lane.lane_number} (${lane.lane_type})`;
            }
        }

        // =====================================================================
        //  Plotly.js Rendering Engine
        // =====================================================================

        /**
         * Build all Plotly trace objects.
         * @returns {Array} Array of Plotly trace objects
         */
        _buildTraces() {
            const traces = [];
            const yPos = this.profileData.y_positions;
            const intensities = this.profileData.intensities;

            if (!yPos || !intensities) return traces;

            // 1. Background curve (toggle-able)
            if (this.showBackground && this.profileData.background) {
                traces.push({
                    x: yPos,
                    y: this.profileData.background,
                    fill: 'tozeroy',
                    fillcolor: COLORS.background,
                    line: { color: COLORS.backgroundLine, width: 1 },
                    name: 'Background',
                    showlegend: true,
                    hoverinfo: 'skip',
                });
            }

            // 2. Integration areas (one trace per band)
            if (this.integrationBands && this.integrationBands.length > 0) {
                this.integrationBands.forEach((band, i) => {
                    const bandTop = band.bbox_y;
                    const bandBottom = band.bbox_y + (band.bbox_height || 0);

                    if (bandTop == null || bandBottom == null) return;

                    const areaX = [], areaY = [];
                    for (let j = 0; j < yPos.length; j++) {
                        if (yPos[j] >= bandTop && yPos[j] <= bandBottom) {
                            areaX.push(yPos[j]);
                            areaY.push(intensities[j]);
                        }
                    }

                    if (areaX.length < 2) return;

                    traces.push({
                        x: areaX,
                        y: areaY,
                        fill: 'tozeroy',
                        fillcolor: COLORS.integrationFill,
                        line: { color: COLORS.integrationLine, width: 0.5 },
                        name: `Band ${i + 1}`,
                        showlegend: false,
                        hovertemplate: `Band ${i + 1}<br>Area: ${band.integrated_area?.toFixed(1) || '?'}<br>Intensity: %{y:.1f}<extra></extra>`,
                    });
                });

                // Single legend proxy for integration fill
                traces.push({
                    x: [null], y: [null],
                    mode: 'lines',
                    line: { color: COLORS.integrationLine, width: 4 },
                    name: 'Integration',
                    showlegend: true,
                    hoverinfo: 'skip',
                });
            }

            // 3. Main profile line
            traces.push({
                x: yPos,
                y: intensities,
                mode: 'lines',
                line: { color: COLORS.profile, width: 2 },
                name: 'Profile',
                showlegend: true,
                hovertemplate: 'Position: %{x}<br>Intensity: %{y:.1f}<extra></extra>',
            });

            // 4. Raw profile (toggle-able)
            if (this.showRawProfile && this.profileData.raw_intensities) {
                traces.push({
                    x: yPos,
                    y: this.profileData.raw_intensities,
                    mode: 'lines',
                    line: { color: COLORS.profileRaw, width: 1, dash: 'dot' },
                    name: 'Raw',
                    showlegend: true,
                    hoverinfo: 'skip',
                });
            }

            // 5. Boundary markers — split by type for legend clarity
            if (this.integrationBands && this.integrationBands.length > 0) {
                const baseline = { x: [], y: [], text: [] };
                const valley = { x: [], y: [], text: [] };

                this.integrationBands.forEach(band => {
                    const bandTop = band.bbox_y;
                    const bandBottom = band.bbox_y + (band.bbox_height || 0);

                    if (band.left_boundary_type && bandTop != null) {
                        const idx = this._findClosestIndex(yPos, bandTop);
                        if (idx >= 0) {
                            const target = band.left_boundary_type === 'baseline' ? baseline : valley;
                            target.x.push(yPos[idx]);
                            target.y.push(
                                band.left_boundary_type === 'baseline' && this.thresholdValue != null
                                    ? this.thresholdValue
                                    : intensities[idx]
                            );
                            target.text.push(`${band.left_boundary_type} boundary`);
                        }
                    }

                    if (band.right_boundary_type && bandBottom != null) {
                        const idx = this._findClosestIndex(yPos, bandBottom);
                        if (idx >= 0) {
                            const target = band.right_boundary_type === 'baseline' ? baseline : valley;
                            target.x.push(yPos[idx]);
                            target.y.push(
                                band.right_boundary_type === 'baseline' && this.thresholdValue != null
                                    ? this.thresholdValue
                                    : intensities[idx]
                            );
                            target.text.push(`${band.right_boundary_type} boundary`);
                        }
                    }
                });

                if (baseline.x.length > 0) {
                    traces.push({
                        x: baseline.x, y: baseline.y,
                        mode: 'markers',
                        marker: { symbol: 'circle', color: COLORS.boundaryBaseline, size: 8, line: { width: 1, color: '#1e293b' } },
                        text: baseline.text, hoverinfo: 'text',
                        name: 'Baseline',
                        showlegend: true,
                    });
                }

                if (valley.x.length > 0) {
                    traces.push({
                        x: valley.x, y: valley.y,
                        mode: 'markers',
                        marker: { symbol: 'diamond', color: COLORS.boundaryValley, size: 8, line: { width: 1, color: '#1e293b' } },
                        text: valley.text, hoverinfo: 'text',
                        name: 'Valley',
                        showlegend: true,
                    });
                }
            }

            // 6. Band highlight regions are rendered as layout shapes (see _buildLayout)

            // 7. Legend proxy traces for shapes (shapes can't have legend entries)
            if (this.thresholdValue != null && this.showThreshold) {
                traces.push({
                    x: [null], y: [null],
                    mode: 'lines',
                    line: { color: COLORS.threshold, width: 2, dash: 'dash' },
                    name: 'Threshold',
                    showlegend: true,
                    hoverinfo: 'skip',
                });
            }

            if (this.showBands && this.currentLaneId) {
                const lane = this.stateManager.getLane(this.currentLaneId);
                if (lane && lane.bands && lane.bands.length > 0) {
                    traces.push({
                        x: [null], y: [null],
                        mode: 'lines',
                        line: { color: 'rgba(158, 158, 158, 0.6)', width: 6 },
                        name: 'Integration zone (bbox)',
                        showlegend: true,
                        hoverinfo: 'skip',
                    });
                    if (this.showPeakMax) {
                        traces.push({
                            x: [null], y: [null],
                            mode: 'lines+markers',
                            line: { color: '#dc2626', width: 1.25, dash: 'dash' },
                            marker: { symbol: 'triangle-down', color: '#dc2626', size: 8 },
                            name: 'Peak max (MW)',
                            showlegend: true,
                            hoverinfo: 'skip',
                        });
                    }
                }
            }

            // 8. Preview peak markers (triangles at detected peak positions)
            if (this.previewPeaks && this.previewPeaks.length > 0) {
                const px = [], py = [];
                this.previewPeaks.forEach(peak => {
                    const idx = this._findClosestIndex(yPos, peak.y);
                    if (idx >= 0) {
                        px.push(yPos[idx]);
                        py.push(intensities[idx]);
                    }
                });

                if (px.length > 0) {
                    traces.push({
                        x: px,
                        y: py,
                        mode: 'markers',
                        marker: {
                            symbol: 'triangle-down',
                            color: COLORS.peakOrphan,
                            size: 10,
                            line: { width: 1, color: '#ffffff' },
                        },
                        name: 'Preview',
                        showlegend: true,
                        hovertemplate: 'Peak at %{x}<br>Intensity: %{y:.1f}<extra></extra>',
                    });
                }
            }

            // 9. First derivative trace (stacked subplot)
            if (this.showFirstDerivative && this.profileData.first_derivative) {
                traces.push({
                    x: yPos,
                    y: this.profileData.first_derivative,
                    mode: 'lines',
                    line: { color: COLORS.derivative1, width: 1.5 },
                    name: 'dy/dx',
                    showlegend: true,
                    yaxis: 'y2',
                    hovertemplate: 'dy/dx: %{y:.2f}<extra></extra>',
                });
            }

            // 10. Second derivative trace (stacked subplot)
            if (this.showSecondDerivative && this.profileData.second_derivative) {
                // Determine correct yaxis based on which subplots are visible
                const d2Axis = this.showFirstDerivative ? 'y3' : 'y3';
                traces.push({
                    x: yPos,
                    y: this.profileData.second_derivative,
                    mode: 'lines',
                    line: { color: COLORS.derivative2, width: 1.5 },
                    name: 'd\u00B2y/dx\u00B2',
                    showlegend: true,
                    yaxis: d2Axis,
                    hovertemplate: 'd\u00B2y/dx\u00B2: %{y:.4f}<extra></extra>',
                });
            }

            // 11. Derivative zero-crossing markers (on MAIN profile y-axis)
            if (this.showDerivativeMarkers && this.profileData.derivative_zero_crossings) {
                const crossings = this.profileData.derivative_zero_crossings;
                const groups = {
                    peak: { x: [], y: [], symbol: 'triangle-down', color: COLORS.derivativePeak, name: 'd1 Peak' },
                    valley: { x: [], y: [], symbol: 'triangle-up', color: COLORS.derivativeValley, name: 'd1 Valley' },
                    inflection: { x: [], y: [], symbol: 'diamond', color: COLORS.derivativeInflection, name: 'd2 Inflection' },
                };

                crossings.forEach(m => {
                    const group = groups[m.type];
                    if (group && m.index < yPos.length) {
                        group.x.push(yPos[m.index]);
                        group.y.push(intensities[m.index]);
                    }
                });

                Object.values(groups).forEach(g => {
                    if (g.x.length > 0) {
                        traces.push({
                            x: g.x, y: g.y,
                            mode: 'markers',
                            marker: { symbol: g.symbol, color: g.color, size: 7, line: { width: 1, color: '#1e293b' } },
                            name: g.name,
                            showlegend: true,
                            hovertemplate: `${g.name}<br>Position: %{x}<br>Intensity: %{y:.1f}<extra></extra>`,
                        });
                    }
                });
            }

            return traces;
        }

        /**
         * Find the closest index in array to a target value.
         */
        _findClosestIndex(arr, target) {
            let closest = -1;
            let minDist = Infinity;
            for (let i = 0; i < arr.length; i++) {
                const dist = Math.abs(arr[i] - target);
                if (dist < minDist) {
                    minDist = dist;
                    closest = i;
                }
            }
            return closest;
        }

        /**
         * Build Plotly layout object with shapes.
         * @returns {Object} Plotly layout
         */
        /**
         * The chart's colours, read from the window's tokens (night or day, whichever the page shows).
         * The data colours (profile, derivatives, band regions) stay as COLORS draws them.
         */
        _plotTheme() {
            const css = getComputedStyle(this.panel || document.documentElement);
            const token = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
            return {
                bg: token('--ga-wb-surface', '#ffffff'),
                legendBg: token('--ga-wb-surface-2', '#f8fafc'),
                text: token('--ga-wb-text-2', '#334155'),
                muted: token('--ga-wb-muted', '#64748b'),
                grid: token('--ga-wb-border', '#e2e8f0'),
                zero: token('--ga-wb-border-2', '#cbd5e1'),
            };
        }

        /**
         * Recolour a chart already drawn (the theme changed under it); data, shapes and zoom stay.
         */
        _applyPlotTheme() {
            const el = this.chartContainer;
            if (typeof Plotly === 'undefined' || !el || !el.layout || !this.plotInitialized) return;
            const theme = this._plotTheme();
            const update = {
                paper_bgcolor: 'transparent',
                plot_bgcolor: theme.bg,
                'font.color': theme.muted,
                'legend.bgcolor': theme.legendBg,
                'legend.bordercolor': theme.grid,
                'legend.font.color': theme.muted,
            };
            ['xaxis', 'yaxis', 'yaxis2', 'yaxis3'].forEach((axis) => {
                if (!el.layout[axis]) return;
                update[`${axis}.gridcolor`] = theme.grid;
                update[`${axis}.zerolinecolor`] = theme.zero;
                update[`${axis}.title.font.color`] = theme.text;
            });
            Plotly.relayout(el, update);
        }

        _buildLayout() {
            const theme = this._plotTheme();
            const yPos = this.profileData.y_positions;
            const intensities = this.profileData.intensities;
            const shapes = [];
            const annotations = [];

            // Threshold line (draggable)
            if (this.thresholdValue != null && this.showThreshold) {
                const maxI = Math.max(...intensities);
                if (this.thresholdValue >= 0 && this.thresholdValue <= maxI * 1.2) {
                    // Invisible wide grab zone (12px) — makes threshold easier to drag
                    shapes.push({
                        type: 'line',
                        xref: 'paper',
                        yref: 'y',
                        x0: 0, x1: 1,
                        y0: this.thresholdValue,
                        y1: this.thresholdValue,
                        line: { color: 'transparent', width: 12 },
                        editable: true,
                    });
                    // Visible threshold line
                    shapes.push({
                        type: 'line',
                        xref: 'paper',
                        yref: 'y',
                        x0: 0, x1: 1,
                        y0: this.thresholdValue,
                        y1: this.thresholdValue,
                        line: { color: COLORS.threshold, width: 3, dash: 'dash' },
                        editable: true,
                    });

                    annotations.push({
                        xref: 'paper',
                        yref: 'y',
                        x: 1,
                        y: this.thresholdValue,
                        text: `T=${this.thresholdValue.toFixed(1)}`,
                        font: { size: 10, color: COLORS.threshold },
                        showarrow: false,
                        xanchor: 'right',
                        yanchor: 'bottom',
                        yshift: 2,
                    });
                }
            }

            // Valley markers (vertical dashed lines)
            if (this.showValleys && this.profileData.valleys) {
                this.profileData.valleys.forEach(idx => {
                    if (idx >= 0 && idx < yPos.length) {
                        shapes.push({
                            type: 'line',
                            xref: 'x', yref: 'paper',
                            x0: yPos[idx], x1: yPos[idx],
                            y0: 0, y1: 1,
                            line: { color: COLORS.valley, width: 0.75, dash: 'dot' },
                            opacity: 0.5,
                        });
                    }
                });
            }

            // Band highlight regions + peak-max markers.
            //
            // Two visually distinct overlays per band:
            //   - filled colored rect spanning [bbox_y, bbox_y + bbox_height]
            //     = the integration zone (server-side densitometry integrates
            //     over exactly this range — peak_integrator.integrate_band).
            //   - thin red vertical line + ▼ glyph at peak_center_y (or
            //     position_y if no fit yet) = the X position used to read MW
            //     off the calibration curve.
            if (this.showBands && this.currentLaneId) {
                const lane = this.stateManager.getLane(this.currentLaneId);
                if (lane && lane.bands) {
                    lane.bands.forEach(band => {
                        const y = band.position_y;
                        const yStart = (band.bbox_y != null) ? band.bbox_y : y - (band.bbox_height || 20) / 2;
                        const yEnd = (band.bbox_y != null) ? band.bbox_y + (band.bbox_height || 20) : y + (band.bbox_height || 20) / 2;

                        let fillColor = COLORS.bandOther;
                        if (band.band_type === 'POI') fillColor = COLORS.bandPOI;
                        else if (band.band_type === 'MW_REFERENCE') fillColor = COLORS.bandMWReference;
                        else if (band.band_type === 'CALIBRATION') fillColor = COLORS.bandCalibration;

                        const isSelected = band.id === this.selectedBandId;
                        if (isSelected) fillColor = COLORS.selected;

                        shapes.push({
                            type: 'rect',
                            xref: 'x', yref: 'paper',
                            x0: yStart, x1: yEnd,
                            y0: 0, y1: 1,
                            fillcolor: fillColor,
                            line: { width: isSelected ? 1.5 : 0, color: isSelected ? '#E91E63' : 'transparent' },
                            opacity: isSelected ? 0.6 : 0.4,
                            layer: 'below',
                        });

                        // Peak-max marker (toggle independently of bbox/Bands)
                        const peakX = band.densitometry?.peak_center_y ?? band.position_y;
                        if (this.showPeakMax && peakX != null) {
                            shapes.push({
                                type: 'line',
                                xref: 'x', yref: 'paper',
                                x0: peakX, x1: peakX,
                                y0: 0, y1: 1,
                                line: { color: '#dc2626', width: 1.25, dash: 'dash' },
                                opacity: 0.7,
                            });
                            annotations.push({
                                xref: 'x', yref: 'paper',
                                x: peakX,
                                y: 1,
                                text: '▼',
                                font: { size: 12, color: '#dc2626' },
                                showarrow: false,
                                xanchor: 'center',
                                yanchor: 'top',
                                yshift: 2,
                            });
                        }
                    });
                }
            }

            // Persistent teacher regions
            Object.entries(this._teacherRegions).forEach(([stepKey, region]) => {
                shapes.push({
                    type: 'rect',
                    xref: 'x', yref: 'paper',
                    x0: region.x0, x1: region.x1,
                    y0: 0, y1: 1,
                    fillcolor: region.fillcolor,
                    line: { color: region.linecolor, width: 1 },
                    _teacherPermanent: true,
                });

                annotations.push({
                    xref: 'x', yref: 'paper',
                    x: (region.x0 + region.x1) / 2,
                    y: 1,
                    text: region.label,
                    font: { size: 10, color: region.linecolor, weight: 600 },
                    showarrow: false,
                    yanchor: 'top',
                    yshift: -4,
                });
            });

            // Determine subplot layout based on derivative visibility
            const showD1 = this.showFirstDerivative && this.profileData.first_derivative;
            const showD2 = this.showSecondDerivative && this.profileData.second_derivative;
            const subplotCount = (showD1 ? 1 : 0) + (showD2 ? 1 : 0);

            const layout = {
                xaxis: {
                    title: { text: 'Position (px)', font: { size: 11, color: theme.text } },
                    autorange: true,
                    gridcolor: theme.grid,
                    zeroline: false,
                },
                yaxis: {
                    title: { text: 'Intensity', font: { size: 11, color: theme.text } },
                    autorange: true,
                    rangemode: 'tozero',
                    gridcolor: theme.grid,
                    zeroline: false,
                },
                shapes: shapes,
                annotations: annotations,
                margin: this._getAdaptiveMargins(),
                hovermode: 'x unified',
                hoverlabel: {
                    bgcolor: '#1f2937',
                    bordercolor: '#374151',
                    font: { color: '#f9fafb', size: 12, family: 'Roboto, sans-serif' },
                    namelength: -1,
                },
                showlegend: true,
                legend: {
                    orientation: 'h',
                    x: 0, y: 1.02,
                    xanchor: 'left', yanchor: 'bottom',
                    font: { size: 10, color: theme.muted },
                    bgcolor: theme.legendBg,
                    bordercolor: theme.grid,
                    borderwidth: 1,
                },
                font: { color: theme.muted },
                paper_bgcolor: 'transparent',
                plot_bgcolor: theme.bg,
                dragmode: 'zoom',
            };

            // Configure stacked subplots when derivatives are shown
            if (subplotCount > 0) {
                const gap = 0.03;
                if (subplotCount === 2) {
                    // 3-way split: main 55%, d1 20%, d2 20%
                    layout.yaxis.domain = [0.45, 1.0];
                    layout.yaxis2 = {
                        title: { text: 'dy/dx', font: { size: 10, color: theme.text } },
                        domain: [0.22, 0.42],
                        autorange: true, gridcolor: theme.grid,
                        zeroline: true, zerolinecolor: theme.zero, zerolinewidth: 1,
                    };
                    layout.yaxis3 = {
                        title: { text: 'd\u00B2y/dx\u00B2', font: { size: 10, color: theme.text } },
                        domain: [0.0, 0.19],
                        autorange: true, gridcolor: theme.grid,
                        zeroline: true, zerolinecolor: theme.zero, zerolinewidth: 1,
                    };
                } else if (showD1) {
                    // 2-way split: main 65%, d1 30%
                    layout.yaxis.domain = [0.35, 1.0];
                    layout.yaxis2 = {
                        title: { text: 'dy/dx', font: { size: 10, color: theme.text } },
                        domain: [0.0, 0.30],
                        autorange: true, gridcolor: theme.grid,
                        zeroline: true, zerolinecolor: theme.zero, zerolinewidth: 1,
                    };
                } else {
                    // 2-way split: main 65%, d2 30%
                    layout.yaxis.domain = [0.35, 1.0];
                    layout.yaxis3 = {
                        title: { text: 'd\u00B2y/dx\u00B2', font: { size: 10, color: theme.text } },
                        domain: [0.0, 0.30],
                        autorange: true, gridcolor: theme.grid,
                        zeroline: true, zerolinecolor: theme.zero, zerolinewidth: 1,
                    };
                }
            }

            return layout;
        }

        /**
         * Compute adaptive Plotly margins based on container size.
         * Base reference: 550x450 (standalone default). Scale < 1 shrinks
         * margins; > 1 grows them. Floor values prevent axis label clipping.
         * @returns {Object} Plotly margin object {t, r, b, l}
         */
        _getAdaptiveMargins() {
            const rect = this.chartContainer.getBoundingClientRect();
            const scale = Math.min(rect.width / 550, rect.height / 450);
            const isEmbedded = this.isEmbedded;
            return {
                t: isEmbedded ? Math.max(35, Math.round(45 * scale)) : Math.max(30, Math.round(40 * scale)),
                r: Math.max(15, Math.round(25 * scale)),
                b: Math.max(30, Math.round(45 * scale)),
                l: Math.max(40, Math.round(55 * scale)),
            };
        }

        /**
         * Build Plotly config object.
         * @returns {Object} Plotly config
         */
        _buildConfig() {
            return {
                responsive: true,
                displayModeBar: false,
                displaylogo: false,
                edits: {
                    shapePosition: true,  // Allow dragging shapes (threshold line)
                },
            };
        }

        /**
         * Render the chart using Plotly.
         * Defers rendering if the container has no dimensions (e.g. mid-transition).
         * @param {number} [attempt] - Current deferred-render attempt (internal use)
         */
        _render(attempt) {
            if (!this.profileData || !this.chartContainer) return;

            this._hidePlaceholder();
            this._hideLoading();

            // Plotly requires a container with real dimensions
            const rect = this.chartContainer.getBoundingClientRect();
            console.info('[ElectropherogramPanel] render:',
                {w: Math.round(rect.width), h: Math.round(rect.height), attempt: attempt || 0, initialized: this.plotInitialized});
            if (rect.width < 1 || rect.height < 1) {
                this._deferRender(attempt || 0);
                return;
            }

            const traces = this._buildTraces();
            const layout = this._buildLayout();
            const config = this._buildConfig();

            if (traces.length === 0) return;

            try {
                if (this.plotInitialized) {
                    // Fast update using Plotly.react
                    Plotly.react(this.chartContainer, traces, layout, config);
                } else {
                    // First render — clear any old SVG from D3 era
                    this.chartContainer.querySelectorAll('svg').forEach(s => s.remove());
                    Plotly.newPlot(this.chartContainer, traces, layout, config);
                    this._setupPlotlyEvents();
                    this.plotInitialized = true;
                }
            } catch (error) {
                console.error('[ElectropherogramPanel] Plotly render error:', error);
            }

            // Update stats
            this._updateStats();
        }

        /**
         * Deferred render: retry _render after the container has had time to lay out.
         * Attempts 0-1 use double requestAnimationFrame (~32 ms, covers standalone show).
         * Attempts 2+ use setTimeout with exponential backoff (covers modal transitions).
         * Gives up after 10 attempts.
         * @param {number} attempt - Current attempt number
         */
        _deferRender(attempt) {
            this._cancelDeferredRender();

            if (attempt >= 10) {
                console.warn('[ElectropherogramPanel] Gave up waiting for container dimensions after 10 attempts');
                return;
            }

            if (attempt <= 1) {
                // Double rAF — resolves most standalone show timing
                this._deferredRAF = requestAnimationFrame(() => {
                    this._deferredRAF = requestAnimationFrame(() => {
                        this._deferredRAF = null;
                        this._render(attempt + 1);
                    });
                });
            } else {
                // Exponential backoff for longer transitions (modal scale animation)
                const delay = 50 * Math.pow(2, attempt - 2); // 50, 100, 200, 400 …
                this._deferredTimer = setTimeout(() => {
                    this._deferredTimer = null;
                    this._render(attempt + 1);
                }, delay);
            }
        }

        /**
         * Cancel any pending deferred render.
         */
        _cancelDeferredRender() {
            if (this._deferredRAF) {
                cancelAnimationFrame(this._deferredRAF);
                this._deferredRAF = null;
            }
            if (this._deferredTimer) {
                clearTimeout(this._deferredTimer);
                this._deferredTimer = null;
            }
        }

        /**
         * Setup Plotly event listeners.
         */
        _setupPlotlyEvents() {
            const el = this.chartContainer;

            // Threshold drag via shape relayout
            el.on('plotly_relayout', (eventData) => {
                if (!eventData) return;

                for (const key in eventData) {
                    // Match shape y-position changes (threshold line)
                    if (key.match(/^shapes\[\d+\]\.y[01]$/)) {
                        const newY = eventData[key];
                        this.thresholdValue = newY;
                        this.eventBus.emit(Events.THRESHOLD_CHANGED, {
                            value: newY,
                            source: 'electropherogram',
                        });
                        // Update threshold annotation text
                        this._updateThresholdAnnotation(newY);
                        break;
                    }
                }
            });

            // Band click via plotly_click
            el.on('plotly_click', (data) => {
                if (!data || !data.points || data.points.length === 0) return;

                // Check if we're in teacher mode - don't handle band clicks
                if (this._teacherMarkState) return;

                // Try to find a band at the clicked x-position
                const clickedX = data.points[0].x;
                if (this.showBands && this.currentLaneId) {
                    const lane = this.stateManager.getLane(this.currentLaneId);
                    if (lane && lane.bands) {
                        for (const band of lane.bands) {
                            const yStart = (band.bbox_y != null) ? band.bbox_y : band.position_y - (band.bbox_height || 20) / 2;
                            const yEnd = (band.bbox_y != null) ? band.bbox_y + (band.bbox_height || 20) : band.position_y + (band.bbox_height || 20) / 2;
                            if (clickedX >= yStart && clickedX <= yEnd) {
                                this.selectedBandId = band.id;
                                this._render();
                                this.eventBus.emit(Events.BAND_SELECTED, { id: band.id });
                                break;
                            }
                        }
                    }
                }
            });
        }

        /**
         * Update threshold annotation text after drag.
         */
        _updateThresholdAnnotation(value) {
            if (!this.chartContainer || !this.chartContainer.layout) return;
            const annotations = this.chartContainer.layout.annotations || [];
            // Find threshold annotation (positioned at x=1 with T= text)
            for (let i = 0; i < annotations.length; i++) {
                if (annotations[i].text && annotations[i].text.startsWith('T=')) {
                    const update = {};
                    update[`annotations[${i}].text`] = `T=${value.toFixed(1)}`;
                    update[`annotations[${i}].y`] = value;
                    try {
                        Plotly.relayout(this.chartContainer, update);
                    } catch (e) {
                        console.error('[ElectropherogramPanel] Plotly relayout error:', e);
                    }
                    break;
                }
            }
        }

        /**
         * Update statistics display.
         */
        _updateStats() {
            if (!this.profileData) return;

            const lane = this.stateManager.getLane(this.currentLaneId);
            const bandCount = lane?.bands?.length || 0;

            const intensities = this.showRawProfile
                ? this.profileData.raw_intensities
                : this.profileData.intensities;

            const peakIntensity = Math.max(...intensities).toFixed(1);
            const yPositions = this.profileData.y_positions;
            const yRange = `${Math.min(...yPositions)}-${Math.max(...yPositions)}`;

            const bandCountEl = document.getElementById('electropherogram-band-count');
            const peakEl = document.getElementById('electropherogram-peak-intensity');
            const rangeEl = document.getElementById('electropherogram-y-range');

            if (bandCountEl) bandCountEl.textContent = bandCount;
            if (peakEl) peakEl.textContent = peakIntensity;
            if (rangeEl) rangeEl.textContent = yRange;
        }

        /**
         * Show placeholder.
         */
        _showPlaceholder() {
            if (this.placeholder) this.placeholder.style.display = 'flex';
            if (this.loading) this.loading.style.display = 'none';
            if (this.footer) this.footer.style.display = 'none';
            // Purge Plotly chart
            if (this.plotInitialized && this.chartContainer) {
                try {
                    Plotly.purge(this.chartContainer);
                } catch (e) {
                    console.error('[ElectropherogramPanel] Plotly purge error:', e);
                }
                this.plotInitialized = false;
            }
        }

        /**
         * Hide placeholder.
         */
        _hidePlaceholder() {
            if (this.placeholder) this.placeholder.style.display = 'none';
        }

        /**
         * Show loading indicator.
         */
        _showLoading() {
            if (this.placeholder) this.placeholder.style.display = 'none';
            if (this.loading) this.loading.style.display = 'flex';
        }

        /**
         * Hide loading indicator.
         */
        _hideLoading() {
            if (this.loading) this.loading.style.display = 'none';
        }

        /**
         * Show footer with stats.
         */
        _showFooter() {
            if (this.footer) this.footer.style.display = 'flex';
        }
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.ElectropherogramPanel = ElectropherogramPanel;

})(window);
