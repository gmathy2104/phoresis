/**
 * Band Zoom Panel - Compact Band Info with Digital Lane
 *
 * Redesigned layout: Horizontal split with compact info card (left) and
 * prominent digital lane visualization (right).
 *
 * Features:
 * - Compact info card with key metrics
 * - Digital lane (two modes: bands or pseudo-gel)
 * - Dynamic band width based on container
 * - Better selection indicators
 */

(function(global) {
    'use strict';

    const Events = global.Densitometry.Events;

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    /**
     * BandZoomPanel Class
     */
    class BandZoomPanel {
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

            // Current selection
            this.currentBandId = null;
            this.currentLaneId = null;
            this.currentBand = null;

            // Digital lane mode
            this.digitalLaneMode = 'bands';  // 'bands' or 'pseudo-gel'

            // Colors - Match annotation panel + handle CALIBRATION (the panel
            // used to fall through to "other" green for calibration bands,
            // making them indistinguishable from regular bands in the
            // digital-lane / pseudo-gel views).
            this.colors = {
                poi: '#a855f7',          // Purple
                other: '#22c55e',        // Green
                mwReference: '#f97316',  // Orange
                calibration: '#f87171',  // Red-400 — same as annotation
                // A western band's role (services/readouts.py::band_roles, from the server)
                aggregate: '#f472b6',
                main: '#a855f7',
                clipping: '#38bdf8',
                leftOut: '#64748b',
            };

            // Resize handling
            this.resizeObserver = null;
            this.resizeTimeout = null;

            this._init();
        }

        /**
         * Initialize the panel.
         */
        _init() {
            if (!this.container) {
                console.warn('[BandZoomPanel] No container element');
                return;
            }

            // Find the content element
            this.contentElement = this.container.querySelector('.dm-panel-content');
            if (!this.contentElement) {
                console.warn('[BandZoomPanel] No .dm-panel-content element found');
                this.contentElement = this.container;
            }

            this._createLayout();
            this._setupEvents();
            this._setupModeToggle();
            this._setupResizeObserver();
        }

        /**
         * Create the panel layout - Horizontal split.
         */
        _createLayout() {
            this.contentElement.innerHTML = `
                <div class="dm-band-detail-container">
                    <!-- Compact Info Card (Left) -->
                    <div class="dm-band-info-card" id="band-info-card">
                        <div class="dm-info-card-placeholder">
                            <i class="bi bi-hand-index"></i>
                            <span>Select a band</span>
                        </div>
                    </div>

                    <!-- Digital Lane (Right - Primary) -->
                    <div class="dm-digital-lane-main">
                        <div class="dm-digital-lane-content" id="digital-lane">
                            <div class="dm-lane-placeholder">
                                <i class="bi bi-list-columns"></i>
                                <span>Select a lane</span>
                            </div>
                        </div>
                    </div>
                </div>
            `;

            // Setup click handlers using event delegation
            this._setupClickHandlers();
        }

        /**
         * Setup click handlers using event delegation.
         * Called once after layout creation - handlers persist across re-renders.
         */
        _setupClickHandlers() {
            const digitalLaneContainer = this.contentElement.querySelector('#digital-lane');
            if (!digitalLaneContainer || digitalLaneContainer._clickHandlerAttached) return;

            digitalLaneContainer.addEventListener('click', (e) => {
                // Find clicked band (bubbles up from child elements)
                const bandEl = e.target.closest('.dm-digital-band');

                if (bandEl) {
                    e.stopPropagation();
                    const bandId = bandEl.dataset.bandId;
                    console.log('[BandZoomPanel] Band clicked:', bandId);
                    if (bandId && this.state) {
                        this.state.selectBand(bandId);
                    }
                } else if (e.target.closest('.dm-digital-bands') || e.target === digitalLaneContainer) {
                    // Click on empty space - deselect
                    if (this.state) {
                        this.state.clearSelection();
                    }
                }
            });

            digitalLaneContainer._clickHandlerAttached = true;
            console.log('[BandZoomPanel] Click handlers attached via event delegation');
        }

        /**
         * Setup mode toggle in panel header.
         */
        _setupModeToggle() {
            // Find or create mode toggle in panel header
            const header = this.container.querySelector('.dm-panel-header');
            if (!header) return;

            // Check if toggle already exists
            let toggle = header.querySelector('.dm-mode-toggle');
            if (!toggle) {
                // Insert toggle into existing panel-actions div (before expand button)
                const existingActions = header.querySelector('.dm-panel-actions');
                if (existingActions) {
                    toggle = document.createElement('div');
                    toggle.className = 'dm-mode-toggle';
                    toggle.innerHTML = `
                        <button class="dm-mode-btn active" data-mode="bands" data-tooltip="Band view">
                            <i class="bi bi-distribute-vertical"></i>
                        </button>
                        <button class="dm-mode-btn" data-mode="pseudo-gel" data-tooltip="Pseudo-gel view">
                            <i class="bi bi-grip-vertical"></i>
                        </button>
                    `;
                    existingActions.insertBefore(toggle, existingActions.firstChild);
                }
            }

            // Setup click handlers
            toggle.querySelectorAll('.dm-mode-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const mode = e.currentTarget.dataset.mode;
                    this._setDigitalLaneMode(mode);

                    // Update button states
                    toggle.querySelectorAll('.dm-mode-btn').forEach(b => {
                        b.classList.toggle('active', b.dataset.mode === mode);
                    });
                });
            });
        }

        /**
         * Setup event listeners.
         */
        _setupEvents() {
            this.eventBus.on(Events.BAND_SELECTED, (data) => {
                this._onBandSelected(data);
            });

            this.eventBus.on(Events.LANE_SELECTED, (data) => {
                this._onLaneSelected(data);
            });

            this.eventBus.on(Events.DATA_UPDATED, () => {
                if (this.currentLaneId) {
                    this._renderDigitalLane();
                }
                if (this.currentBand) {
                    this._renderBandInfoCard(this.currentBand);
                }
            });
        }

        /**
         * Handle band selection.
         */
        _onBandSelected(data) {
            this.currentBandId = data.bandId;
            this.currentBand = data.band || null;

            if (data.bandId && data.band) {
                this._renderBandInfoCard(data.band);
                // Re-render digital lane to update selection
                if (this.currentLaneId) {
                    this._renderDigitalLane();
                }
            } else {
                this._clearBandInfoCard();
            }
        }

        /**
         * Handle lane selection.
         */
        _onLaneSelected(data) {
            this.currentLaneId = data.laneId;

            if (data.laneId) {
                this._renderDigitalLane();
            } else {
                this._clearDigitalLane();
            }
        }

        /**
         * Render compact band info card.
         */
        _renderBandInfoCard(band) {
            const card = this.contentElement.querySelector('#band-info-card');
            if (!card || !band) return;

            const typeColors = {
                'POI': { bg: '#a855f7', label: 'POI' },
                'MW_REFERENCE': { bg: '#f97316', label: 'REF' },
                'CALIBRATION': { bg: '#f87171', label: 'Calib' },
                'OTHER': { bg: '#22c55e', label: 'Other' }
            };
            const typeInfo = typeColors[band.band_type] || typeColors['OTHER'];

            let html = `
                <div class="dm-info-card-content">
                    <div class="dm-info-badge" style="background: ${typeInfo.bg}">
                        ${typeInfo.label}
                    </div>
                    <div class="dm-info-stats">
            `;

            // MW (if available) - show first as it's most important
            if (band.estimated_mw_kda) {
                html += `
                    <div class="dm-stat">
                        <span class="dm-stat-value">${band.estimated_mw_kda.toFixed(0)}</span>
                        <span class="dm-stat-label"><span class="ga-wb-unit-text">kDa</span></span>
                    </div>
                `;
            }

            // Densitometry data
            if (band.densitometry) {
                const d = band.densitometry;
                if (d.relative_percent_lane !== null && d.relative_percent_lane !== undefined) {
                    html += `
                        <div class="dm-stat dm-stat-highlight">
                            <span class="dm-stat-value">${d.relative_percent_lane.toFixed(1)}</span>
                            <span class="dm-stat-label">%</span>
                        </div>
                    `;
                }
                if (d.corrected_area) {
                    html += `
                        <div class="dm-stat">
                            <span class="dm-stat-value">${this._formatArea(d.corrected_area)}</span>
                            <span class="dm-stat-label">Area</span>
                        </div>
                    `;
                }
            }

            // Position (muted, less important)
            html += `
                <div class="dm-stat dm-stat-muted">
                    <span class="dm-stat-value">${Math.round(band.position_y)}</span>
                    <span class="dm-stat-label">Y <span class="ga-wb-unit-text">px</span></span>
                </div>
            `;

            html += `
                    </div>
                </div>
            `;

            card.innerHTML = html;
        }

        /**
         * Format area value for display.
         */
        _formatArea(area) {
            if (area >= 1000000) return (area / 1000000).toFixed(1) + 'M';
            if (area >= 1000) return (area / 1000).toFixed(1) + 'K';
            return Math.round(area).toString();
        }

        /**
         * Clear band info card.
         */
        _clearBandInfoCard() {
            const card = this.contentElement.querySelector('#band-info-card');
            if (card) {
                card.innerHTML = `
                    <div class="dm-info-card-placeholder">
                        <i class="bi bi-hand-index"></i>
                        <span>Select a band</span>
                    </div>
                `;
            }
        }

        /**
         * Set digital lane display mode.
         */
        _setDigitalLaneMode(mode) {
            this.digitalLaneMode = mode;

            // Re-render if we have data
            if (this.currentLaneId) {
                this._renderDigitalLane();
            }

            this.eventBus.emit(Events.DIGITAL_LANE_MODE_CHANGED, { mode });
        }

        /**
         * Render digital lane visualization.
         */
        _renderDigitalLane() {
            const container = this.contentElement.querySelector('#digital-lane');
            if (!container || !this.currentLaneId) return;

            const bands = this.state.getBandsForLane(this.currentLaneId);
            const lane = this.state.getLane(this.currentLaneId);

            if (!bands || bands.length === 0) {
                container.innerHTML = `
                    <div class="dm-lane-placeholder">
                        <i class="bi bi-x-circle"></i>
                        <span>No bands in lane</span>
                    </div>
                `;
                return;
            }

            if (this.digitalLaneMode === 'bands') {
                this._renderDigitalLaneBands(container, bands, lane);
            } else {
                this._renderDigitalLanePseudoGel(container, bands, lane);
            }
        }

        /**
         * Render digital lane in bands mode (wider, responsive).
         */
        _renderDigitalLaneBands(container, bands, lane) {
            const containerRect = container.getBoundingClientRect();

            // Get normalized position calculator based on actual band range
            const posRange = this._getBandPositionRange(bands);

            // Store for MW scale alignment
            this._currentPosRange = posRange;

            // Dynamic width - use 50% of container, min 60px, max 120px
            const bandWidth = Math.max(60, Math.min(120, containerRect.width * 0.5));

            let html = `<div class="dm-digital-bands" style="width: ${bandWidth}px;">`;

            bands.forEach(band => {
                // Use normalized position (0-100%)
                const normalizedPos = posRange.normalize(band.position_y);

                // Calculate band height as percentage of visual range
                const bandHeightPx = band.bbox ? band.bbox.height : 10;
                const rangeHeight = posRange.maxY - posRange.minY;
                const bandHeightPercent = (bandHeightPx / rangeHeight) * 100;

                const color = this._getBandColor(band.band_type, band);

                // Intensity-based opacity
                let opacity = 0.7;
                if (band.densitometry && band.densitometry.relative_percent_lane) {
                    opacity = Math.max(0.4, Math.min(1, band.densitometry.relative_percent_lane / 40));
                }

                const isSelected = band.id === this.currentBandId;

                html += `
                    <div class="dm-digital-band ${isSelected ? 'selected' : ''}"
                         style="top: ${normalizedPos}%;
                                height: ${Math.max(bandHeightPercent, 2)}%;
                                background-color: ${color};
                                opacity: ${isSelected ? 1 : opacity};"
                         data-band-id="${band.id}"
                         title="${escapeHtml(band.band_type)}${band.estimated_mw_kda ? ` (~${band.estimated_mw_kda.toFixed(0)} kDa)` : ''}">
                        ${isSelected ? '<span class="dm-band-marker"></span>' : ''}
                    </div>
                `;
            });

            html += '</div>';

            // Add graduated MW scale if calibration is available
            html += this._renderMWScale(bands, posRange);

            container.innerHTML = html;
            // Click handlers are set up once via event delegation in _setupClickHandlers()
        }

        /**
         * Render scientific MW scale with standard markers.
         * Uses calibration from MW_REFERENCE bands across all lanes.
         * @param {Array} bands - Array of band objects (current lane)
         * @param {Object} posRange - Position range with normalize function
         */
        _renderMWScale(bands, posRange) {
            const calibPoints = this._getCalibrationPoints();
            if (!calibPoints || calibPoints.length < 2) {
                return '';  // No calibration available
            }

            // Standard MW reference points (kDa)
            const standardMWs = [10, 15, 25, 35, 55, 70, 100, 130, 180, 250];

            // Get MW range from calibration
            const mwValues = calibPoints.map(p => p.mw);
            const minMW = Math.min(...mwValues);
            const maxMW = Math.max(...mwValues);

            // Filter to MW values within calibration range (with small margin)
            const visibleMWs = standardMWs.filter(mw => mw >= minMW * 0.8 && mw <= maxMW * 1.2);

            if (visibleMWs.length === 0) return '';

            let html = '<div class="dm-mw-scale-graduated">';

            visibleMWs.forEach(mw => {
                const y = this._interpolateMWPosition(mw, calibPoints);
                if (y !== null) {
                    const normalizedPos = posRange.normalize(y);
                    // Allow slight overflow for edge markers
                    if (normalizedPos >= -5 && normalizedPos <= 105) {
                        html += `
                            <div class="dm-mw-marker" style="top: ${Math.max(0, Math.min(100, normalizedPos))}%;">
                                <span class="dm-mw-line"></span>
                                <span class="dm-mw-value">${mw}</span>
                            </div>
                        `;
                    }
                }
            });

            html += '</div>';
            return html;
        }

        /**
         * Render digital lane in pseudo-gel mode.
         */
        _renderDigitalLanePseudoGel(container, bands, lane) {
            const containerRect = container.getBoundingClientRect();

            // Get normalized position calculator based on actual band range
            const posRange = this._getBandPositionRange(bands);

            // Canvas sizing
            const canvasWidth = Math.max(80, Math.min(containerRect.width * 0.6, 150));
            const canvasHeight = Math.max(150, containerRect.height - 20);

            const canvas = document.createElement('canvas');
            canvas.width = canvasWidth;
            canvas.height = canvasHeight;
            canvas.className = 'dm-pseudo-gel-canvas';

            const ctx = canvas.getContext('2d');

            // Dark background
            ctx.fillStyle = '#1a1a1a';
            ctx.fillRect(0, 0, canvas.width, canvas.height);

            // Draw each band using normalized position
            bands.forEach(band => {
                const normalizedPos = posRange.normalize(band.position_y) / 100;
                const y = normalizedPos * canvas.height;

                // Calculate band height
                const bandHeightPx = band.bbox ? band.bbox.height : 10;
                const rangeHeight = posRange.maxY - posRange.minY;
                const bandHeight = (bandHeightPx / rangeHeight) * canvas.height;

                // Intensity from densitometry (logarithmic scale for better dynamic range)
                let intensity = 0.6;
                if (band.densitometry && band.densitometry.relative_percent_lane) {
                    // Log scale: maps 0-100% to 0.3-1.0 range
                    // Provides better visibility for low-percentage bands
                    const percent = band.densitometry.relative_percent_lane;
                    const logValue = Math.log10(1 + percent);
                    const maxLog = Math.log10(101);  // Normalize to 100%
                    intensity = 0.3 + (logValue / maxLog) * 0.7;
                }

                // Create gradient
                const gradient = ctx.createLinearGradient(0, y - bandHeight/2, 0, y + bandHeight/2);
                const color = this._getBandColor(band.band_type, band);

                gradient.addColorStop(0, 'transparent');
                gradient.addColorStop(0.2, this._adjustColorIntensity(color, intensity * 0.5));
                gradient.addColorStop(0.5, this._adjustColorIntensity(color, intensity));
                gradient.addColorStop(0.8, this._adjustColorIntensity(color, intensity * 0.5));
                gradient.addColorStop(1, 'transparent');

                ctx.fillStyle = gradient;
                ctx.fillRect(8, y - bandHeight/2, canvas.width - 16, bandHeight);

                // Highlight selected band
                if (band.id === this.currentBandId) {
                    ctx.strokeStyle = '#ef4444';
                    ctx.lineWidth = 2;
                    ctx.strokeRect(4, y - bandHeight/2 - 2, canvas.width - 8, bandHeight + 4);
                }
            });

            container.innerHTML = '';
            container.appendChild(canvas);

            // Add graduated MW scale overlay if calibration is available
            this._addMWScaleOverlay(container, bands, posRange, canvas.height);
        }

        /**
         * Add graduated MW scale overlay for pseudo-gel mode.
         * Uses calibration from MW_REFERENCE bands across all lanes.
         * @param {HTMLElement} container - Container element
         * @param {Array} bands - Array of band objects (current lane)
         * @param {Object} posRange - Position range with normalize function
         * @param {number} canvasHeight - Height of the canvas in pixels
         */
        _addMWScaleOverlay(container, bands, posRange, canvasHeight) {
            const calibPoints = this._getCalibrationPoints();
            if (!calibPoints || calibPoints.length < 2) {
                return;  // No calibration available
            }

            // Standard MW reference points (kDa)
            const standardMWs = [10, 15, 25, 35, 55, 70, 100, 130, 180, 250];

            // Get MW range from calibration
            const mwValues = calibPoints.map(p => p.mw);
            const minMW = Math.min(...mwValues);
            const maxMW = Math.max(...mwValues);

            // Filter to MW values within calibration range
            const visibleMWs = standardMWs.filter(mw => mw >= minMW * 0.8 && mw <= maxMW * 1.2);

            if (visibleMWs.length === 0) return;

            const scale = document.createElement('div');
            scale.className = 'dm-mw-scale-overlay dm-mw-scale-graduated';
            scale.style.height = `${canvasHeight}px`;

            visibleMWs.forEach(mw => {
                const y = this._interpolateMWPosition(mw, calibPoints);
                if (y !== null) {
                    const normalizedPos = posRange.normalize(y) / 100;
                    const pixelY = normalizedPos * canvasHeight;

                    // Allow slight overflow for edge markers
                    if (normalizedPos >= -0.05 && normalizedPos <= 1.05) {
                        const marker = document.createElement('div');
                        marker.className = 'dm-mw-marker';
                        marker.style.top = `${Math.max(0, Math.min(canvasHeight, pixelY))}px`;
                        marker.innerHTML = `<span class="dm-mw-line"></span><span class="dm-mw-value">${mw}</span>`;
                        scale.appendChild(marker);
                    }
                }
            });

            container.appendChild(scale);
        }

        /**
         * Calculate min/max Y positions and create position mapper.
         * This normalizes band positions to fill the visual space.
         * @param {Array} bands - Array of band objects
         * @returns {Object} { minY, maxY, normalize: (y) => percent }
         */
        _getBandPositionRange(bands) {
            if (!bands || bands.length === 0) {
                return { minY: 0, maxY: 100, normalize: (y) => y };
            }

            // Get min/max Y positions from bands
            const yPositions = bands.map(b => b.position_y);
            const minY = Math.min(...yPositions);
            const maxY = Math.max(...yPositions);

            // Add padding (5% on each side)
            const range = maxY - minY || 1;  // Avoid division by zero
            const padding = range * 0.05;
            const paddedMin = minY - padding;
            const paddedMax = maxY + padding;
            const paddedRange = paddedMax - paddedMin;

            return {
                minY: paddedMin,
                maxY: paddedMax,
                normalize: (y) => ((y - paddedMin) / paddedRange) * 100
            };
        }

        /**
         * Get calibration points from MW_REFERENCE bands across all lanes.
         * @returns {Array|null} Array of calibration points or null if insufficient data
         */
        _getCalibrationPoints() {
            if (!this.state || !this.state.bands) return null;

            // Get all MW_REFERENCE bands from the state (all lanes)
            const allBands = Array.from(this.state.bands.values());
            const calibBands = allBands.filter(b =>
                b.estimated_mw_kda && b.band_type === 'MW_REFERENCE'
            );

            if (calibBands.length < 2) return null;

            // Build calibration points (sorted by position)
            return calibBands
                .map(b => ({
                    y: b.position_y,
                    mw: b.estimated_mw_kda,
                    logMW: Math.log10(b.estimated_mw_kda)
                }))
                .sort((a, b) => a.y - b.y);
        }

        /**
         * Interpolate Y position for a target MW using log-linear interpolation.
         * @param {number} targetMW - Target MW in kDa
         * @param {Array} calibPoints - Calibration points array
         * @returns {number|null} Interpolated Y position or null if out of range
         */
        _interpolateMWPosition(targetMW, calibPoints) {
            const targetLogMW = Math.log10(targetMW);

            // Find bracketing points
            for (let i = 0; i < calibPoints.length - 1; i++) {
                const p1 = calibPoints[i];
                const p2 = calibPoints[i + 1];

                const minLog = Math.min(p1.logMW, p2.logMW);
                const maxLog = Math.max(p1.logMW, p2.logMW);

                if (targetLogMW >= minLog && targetLogMW <= maxLog) {
                    // Linear interpolation in log space
                    const t = (targetLogMW - p1.logMW) / (p2.logMW - p1.logMW);
                    return p1.y + t * (p2.y - p1.y);
                }
            }
            return null;
        }

        /**
         * Get color for band type.
         */
        _getBandColor(bandType, band = null) {
            // On a western, the band's role from the server (the classification the published values sum).
            const role = band && band.role;
            if (role === 'aggregate') return this.colors.aggregate;
            if (role === 'main') return this.colors.main;
            if (role === 'clipping') return this.colors.clipping;
            if (role === 'left_out') return this.colors.leftOut;
            if (role === 'hcp') return this.colors.other;
            // CALIBRATION used to fall through to "other" (green), making
            // calibration points invisible in the per-band view. Now they
            // render in red to match the annotation panel.
            if (bandType === 'CALIBRATION') return this.colors.calibration;
            switch (bandType) {
                case 'POI': return this.colors.poi;
                case 'MW_REFERENCE': return this.colors.mwReference;
                case 'CALIBRATION': return this.colors.calibration;
                default: return this.colors.other;
            }
        }

        /**
         * Adjust color intensity.
         */
        _adjustColorIntensity(hexColor, intensity) {
            const r = parseInt(hexColor.slice(1, 3), 16);
            const g = parseInt(hexColor.slice(3, 5), 16);
            const b = parseInt(hexColor.slice(5, 7), 16);

            const newR = Math.round(r * intensity);
            const newG = Math.round(g * intensity);
            const newB = Math.round(b * intensity);

            return `rgb(${newR}, ${newG}, ${newB})`;
        }

        /**
         * Clear digital lane view.
         */
        _clearDigitalLane() {
            const container = this.contentElement.querySelector('#digital-lane');
            if (container) {
                container.innerHTML = `
                    <div class="dm-lane-placeholder">
                        <i class="bi bi-list-columns"></i>
                        <span>Select a lane</span>
                    </div>
                `;
            }
        }

        /**
         * Setup ResizeObserver with debouncing.
         */
        _setupResizeObserver() {
            if (this.resizeObserver) {
                this.resizeObserver.disconnect();
            }

            this.resizeObserver = new ResizeObserver(() => {
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
         * Handle resize - re-render content.
         */
        _handleResize() {
            const rect = this.contentElement.getBoundingClientRect();
            // Skip if container has no dimensions (panel hidden/collapsed)
            if (rect.width === 0 || rect.height === 0) return;

            // Re-render digital lane if we have a lane selected
            if (this.currentLaneId) {
                this._renderDigitalLane();
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
        }
    }

    // Export
    global.Densitometry = global.Densitometry || {};
    global.Densitometry.BandZoomPanel = BandZoomPanel;

})(window);
