/**
 * Gel Overview Panel - Interactive Gel Image with Band Selection
 *
 * Displays the gel image with highlighted lanes and bands.
 * Features:
 * - Click on lanes/bands to select
 * - Visual indicators for POI bands (green)
 * - Image adjustments (brightness, contrast, invert)
 * - Proper fit-to-view with padding (like annotation module)
 * - ResizeObserver for responsive resizing
 */

(function(global) {
    'use strict';

    const Events = global.Densitometry.Events;

    /**
     * GelOverviewPanel Class
     */
    class GelOverviewPanel {
        /**
         * @param {Object} options
         * @param {HTMLElement} options.container
         * @param {EventBus} options.eventBus
         * @param {State} options.state
         * @param {string} options.imageUrl
         */
        constructor(options) {
            this.container = options.container;
            this.eventBus = options.eventBus;
            this.state = options.state;
            this.imageUrl = options.imageUrl || '';

            // Canvas elements
            this.canvas = null;
            this.ctx = null;
            this.image = null;
            this.imageLoaded = false;

            // View state
            this.scale = 1;
            this.offsetX = 0;
            this.offsetY = 0;

            // Adjustments
            this.adjustments = {
                brightness: 100,
                contrast: 100,
                invert: false,
            };

            // Band overlay visibility
            this.showBands = true;

            // Colors — kept in sync with the annotation gel-viewer
            // (gel_viewer.css / gel_viewer_standalone.css). CALIBRATION /
            // CONTROL / LADDER differentiation: the panel used to fall
            // through everything to "lane" blue and any non-POI/MW_REFERENCE
            // band to "bandOther" green, which hid the CALIBRATION points
            // completely.
            this.colors = {
                // Lane colors by lane_type
                laneSample:            'rgba(59, 130, 246, 0.35)',  // Blue
                laneSelected:          'rgba(59, 130, 246, 0.55)',  // Brighter blue
                laneSampleBorder:      '#3b82f6',
                laneLadder:            'rgba(249, 115, 22, 0.35)',  // Orange
                laneLadderBorder:      '#f97316',
                laneCalibration:       'rgba(248, 113, 113, 0.35)', // Red-400
                laneCalibrationBorder: '#f87171',
                // CONTROL is green, as in the annotation editor and the analysis page (one gel palette).
                laneControl:           'rgba(34, 197, 94, 0.30)',
                laneControlBorder:     '#22c55e',
                laneEmpty:             'rgba(107, 114, 128, 0.20)', // Grey
                laneEmptyBorder:       '#6b7280',
                // Anti-HCP reference lane: outline + "REF" tag, the editor's
                // amber (gel_viewer_standalone.css --gv-ref-color)
                laneReferenceBorder:   '#f59e0b',                   // Amber-500
                laneReferenceInk:      '#0f172a',
                // Legacy aliases (kept so any direct reference still works
                // until the call sites switch to lane-type-specific keys)
                lane:                  'rgba(59, 130, 246, 0.35)',
                laneBorder:            '#3b82f6',
                // Band colors by band_type
                bandPOI:               'rgba(168, 85, 247, 0.35)',  // Purple
                bandOther:             'rgba(34, 197, 94, 0.35)',   // Green
                bandRef:               'rgba(249, 115, 22, 0.35)',  // Orange
                bandCalibration:       'rgba(248, 113, 113, 0.45)', // Red-400 (slightly stronger so CALIBRATION points stand out)
                bandSelected:          '#ef4444',                   // Red border
                // A western band's role (services/readouts.py::band_roles, from the server)
                bandAggregate:         'rgba(244, 114, 182, 0.45)',
                bandMain:              'rgba(168, 85, 247, 0.40)',
                bandClipping:          'rgba(56, 189, 248, 0.45)',
                bandLeftOut:           'rgba(100, 116, 139, 0.40)',
            };

            // ResizeObserver with debouncing
            this.resizeObserver = null;
            this.resizeTimeout = null;

            // Store last valid dimensions for edge cases
            this.lastValidDimensions = { width: 0, height: 0 };

            this._init();
        }

        /**
         * Initialize the panel.
         */
        _init() {
            if (!this.container) {
                console.warn('[GelOverviewPanel] No container element');
                return;
            }

            // Find the content element (inside the panel, not the panel itself)
            this.contentElement = this.container.querySelector('.dm-panel-content');
            if (!this.contentElement) {
                console.warn('[GelOverviewPanel] No .dm-panel-content element found');
                this.contentElement = this.container;  // Fallback
            }

            // Show loading state initially
            this._showLoading();

            this._setupEvents();
            this._setupPanelButtons();

            // Load image if URL provided (with slight delay to ensure layout is ready)
            if (this.imageUrl) {
                requestAnimationFrame(() => {
                    this._loadImage(this.imageUrl);
                });
            }
        }

        /**
         * Show loading state.
         */
        _showLoading() {
            this.contentElement.innerHTML = `
                <div class="dm-loading">
                    <div class="dm-spinner"></div>
                    <span>Loading gel image...</span>
                </div>
            `;
        }

        /**
         * Show error state.
         */
        _showError(message) {
            this.contentElement.innerHTML = `
                <div class="dm-loading dm-error">
                    <i class="bi bi-exclamation-triangle" style="font-size: 2rem; color: var(--dm-danger);"></i>
                    <span>${message}</span>
                </div>
            `;
        }

        /**
         * Create the canvas element.
         */
        _createCanvas() {
            this.contentElement.innerHTML = '';

            // Create canvas container
            const container = document.createElement('div');
            container.className = 'dm-gel-canvas-container';
            this.contentElement.appendChild(container);

            // Create canvas
            this.canvas = document.createElement('canvas');
            this.canvas.className = 'dm-gel-canvas';
            container.appendChild(this.canvas);

            this.ctx = this.canvas.getContext('2d');

            // Setup canvas event listeners
            this._setupCanvasEvents();

            // Setup ResizeObserver for better responsiveness
            this._setupResizeObserver();

            // Initial resize
            this._resizeCanvas();
        }

        /**
         * Setup ResizeObserver for responsive resizing with debouncing.
         */
        _setupResizeObserver() {
            if (this.resizeObserver) {
                this.resizeObserver.disconnect();
            }

            this.resizeObserver = new ResizeObserver(() => {
                // Debounce with requestAnimationFrame for smooth resizing
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
         * Handle resize - unified method for proper sequencing.
         */
        _handleResize() {
            if (!this.canvas || !this.imageLoaded) return;

            const rect = this.contentElement.getBoundingClientRect();

            // Bail out if container has no dimensions
            if (rect.width === 0 || rect.height === 0) {
                return;
            }

            // Skip if dimensions haven't changed significantly
            if (Math.abs(rect.width - this.lastValidDimensions.width) < 1 &&
                Math.abs(rect.height - this.lastValidDimensions.height) < 1) {
                return;
            }

            // Store valid dimensions
            this.lastValidDimensions = { width: rect.width, height: rect.height };

            // Step 1: Resize canvas (this clears the canvas)
            this.canvas.width = rect.width;
            this.canvas.height = rect.height;

            // Step 2: Recalculate fit (scale and offset)
            this._calculateFit();

            // Step 3: Render with new dimensions
            this._render();
        }

        /**
         * Calculate fit scale and offset (without rendering).
         */
        _calculateFit() {
            if (!this.image || !this.canvas) return;

            // Calculate fit scale
            const fitScale = Math.min(
                this.canvas.width / this.image.width,
                this.canvas.height / this.image.height
            );

            // Apply 90% padding factor
            this.scale = fitScale * 0.9;

            // Cap maximum scale at 60% for comfort
            if (this.scale > 0.6 && this.image.width > 500) {
                this.scale = 0.6;
            }

            // Center the image
            const scaledWidth = this.image.width * this.scale;
            const scaledHeight = this.image.height * this.scale;
            this.offsetX = (this.canvas.width - scaledWidth) / 2;
            this.offsetY = (this.canvas.height - scaledHeight) / 2;
        }

        /**
         * Resize canvas to fit container (legacy, used by _createCanvas).
         */
        _resizeCanvas() {
            if (!this.canvas) return;

            const rect = this.contentElement.getBoundingClientRect();

            if (rect.width === 0 || rect.height === 0) {
                return;
            }

            this.lastValidDimensions = { width: rect.width, height: rect.height };
            this.canvas.width = rect.width;
            this.canvas.height = rect.height;
        }

        /**
         * Load the gel image.
         */
        _loadImage(url) {
            this.imageLoaded = false;
            this._showLoading();

            this.image = new Image();
            this.image.crossOrigin = 'anonymous';

            this.image.onload = () => {
                this.imageLoaded = true;

                // Create canvas now that we have the image
                this._createCanvas();

                // Wait for next frame to ensure canvas has dimensions
                // _fitImageToCanvas() will calculate fit and call _render()
                requestAnimationFrame(() => {
                    this._fitImageToCanvas();
                });
            };

            this.image.onerror = () => {
                console.error('[GelOverviewPanel] Failed to load image:', url);
                this._showError('Failed to load gel image');
            };

            this.image.src = url;
        }

        /**
         * Set image URL.
         */
        setImageUrl(url) {
            this.imageUrl = url;
            this._loadImage(url);
        }

        /**
         * Fit image to canvas while maintaining aspect ratio.
         * Called after image loads to do initial fit and render.
         */
        _fitImageToCanvas() {
            if (!this.image || !this.canvas) return;

            const rect = this.contentElement.getBoundingClientRect();

            // Check if container has valid dimensions
            if (rect.width === 0 || rect.height === 0) {
                // Container not ready, retry after layout
                requestAnimationFrame(() => this._fitImageToCanvas());
                return;
            }

            // Update canvas size if needed (only on initial fit)
            if (this.canvas.width !== rect.width || this.canvas.height !== rect.height) {
                this.canvas.width = rect.width;
                this.canvas.height = rect.height;
                this.lastValidDimensions = { width: rect.width, height: rect.height };
            }

            // Calculate fit
            this._calculateFit();

            // Render the image
            this._render();
        }

        /**
         * Setup event listeners.
         */
        _setupEvents() {
            // Event bus events
            this.eventBus.on(Events.LANE_SELECTED, () => this._render());
            this.eventBus.on(Events.BAND_SELECTED, () => this._render());
            this.eventBus.on(Events.DATA_UPDATED, () => this._render());
            this.eventBus.on(Events.BANDS_CREATED, () => this._render());  // Re-render when new bands are created
            this.eventBus.on(Events.READOUTS_UPDATED, () => this._render());  // HCP reference moved: redraw the REF tag

            // Image adjustments
            this.eventBus.on(Events.IMAGE_ADJUSTED, (data) => {
                this.adjustments = { ...this.adjustments, ...data };
                this._render();
            });

            this.eventBus.on(Events.IMAGE_RESET, () => {
                this.adjustments = { brightness: 100, contrast: 100, invert: false };
                this._render();
            });
        }

        /**
         * Setup panel header buttons (auto-enhance, invert, band toggle).
         */
        _setupPanelButtons() {
            // Auto-enhance button
            const enhanceBtn = document.getElementById('gel-auto-enhance');
            if (enhanceBtn) {
                enhanceBtn.addEventListener('click', () => {
                    const isActive = enhanceBtn.classList.toggle('active');
                    if (isActive) {
                        this._autoEnhance();
                    } else {
                        this.adjustments = { brightness: 100, contrast: 100, invert: this.adjustments.invert };
                        this._render();
                    }
                });
            }

            // Invert toggle button
            const invertBtn = document.getElementById('gel-invert-toggle');
            if (invertBtn) {
                invertBtn.addEventListener('click', () => {
                    this.adjustments.invert = !this.adjustments.invert;
                    invertBtn.classList.toggle('active', this.adjustments.invert);
                    this._render();
                });
            }

            // Band overlay toggle button
            const bandsBtn = document.getElementById('gel-bands-toggle');
            if (bandsBtn) {
                bandsBtn.addEventListener('click', () => {
                    this.showBands = !this.showBands;
                    bandsBtn.classList.toggle('active', this.showBands);
                    this._render();
                });
            }
        }

        /**
         * Auto-enhance by analyzing the gel image histogram.
         */
        _autoEnhance() {
            if (!this.image || !this.imageLoaded) return;

            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');

            const maxSize = 500;
            const w = this.image.naturalWidth || this.image.width;
            const h = this.image.naturalHeight || this.image.height;
            const scale = Math.min(1, maxSize / Math.max(w, h));
            canvas.width = Math.floor(w * scale);
            canvas.height = Math.floor(h * scale);

            ctx.drawImage(this.image, 0, 0, canvas.width, canvas.height);
            const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;

            // Build grayscale histogram
            const histogram = new Array(256).fill(0);
            const step = 4;
            for (let i = 0; i < data.length; i += 4 * step) {
                const gray = Math.round(0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]);
                histogram[gray]++;
            }

            // Analyze: percentiles + mean
            const total = histogram.reduce((a, b) => a + b, 0);
            const p5 = total * 0.05;
            const p95 = total * 0.95;
            let cumulative = 0, minVal = 0, maxVal = 255;
            for (let i = 0; i < 256; i++) {
                cumulative += histogram[i];
                if (cumulative >= p5 && minVal === 0) minVal = i;
                if (cumulative >= p95) { maxVal = i; break; }
            }

            let sum = 0, count = 0;
            for (let i = 0; i < 256; i++) {
                sum += i * histogram[i];
                count += histogram[i];
            }
            const mean = sum / count;

            const range = maxVal - minVal;
            let contrast = 100;
            if (range > 0 && range < 200) {
                contrast = Math.round(Math.min(200, (200 / range) * 100));
            }

            let brightness = 100;
            if (mean < 100) {
                brightness = Math.round(Math.min(180, 100 + (128 - mean) * 0.5));
            } else if (mean > 160) {
                brightness = Math.round(Math.max(60, 100 - (mean - 128) * 0.5));
            }

            brightness = Math.max(50, Math.min(200, brightness));
            contrast = Math.max(80, Math.min(200, contrast));

            this.adjustments.brightness = brightness;
            this.adjustments.contrast = contrast;
            this._render();
        }

        /**
         * Setup canvas event listeners (called after canvas is created).
         */
        _setupCanvasEvents() {
            if (!this.canvas) return;

            // Canvas click
            this.canvas.addEventListener('click', (e) => this._onClick(e));
            this.canvas.addEventListener('mousemove', (e) => this._onMouseMove(e));
        }

        /**
         * Handle canvas click.
         */
        _onClick(event) {
            if (!this.canvas) return;

            const point = this._getCanvasPoint(event);
            const imagePoint = this._canvasToImage(point);

            // Check if clicked on a band
            const band = this._getBandAtPoint(imagePoint);
            if (band) {
                this.state.selectBand(band.id);
                return;
            }

            // Check if clicked on a lane
            const lane = this._getLaneAtPoint(imagePoint);
            if (lane) {
                this.state.selectLane(lane.id);
                return;
            }

            // Clicked on empty space - clear selection
            this.state.clearSelection();
        }

        /**
         * Handle mouse move.
         */
        _onMouseMove(event) {
            if (!this.canvas) return;

            const point = this._getCanvasPoint(event);
            const imagePoint = this._canvasToImage(point);

            // Check hover state
            const band = this._getBandAtPoint(imagePoint);
            if (band) {
                this.canvas.style.cursor = 'pointer';
                this.eventBus.emit(Events.BAND_HOVERED, { bandId: band.id, band });
                return;
            }

            const lane = this._getLaneAtPoint(imagePoint);
            if (lane) {
                this.canvas.style.cursor = 'pointer';
                this.eventBus.emit(Events.LANE_HOVERED, { laneId: lane.id, lane });
                return;
            }

            this.canvas.style.cursor = 'default';
        }

        /**
         * Get canvas coordinates from mouse event.
         */
        _getCanvasPoint(event) {
            const rect = this.canvas.getBoundingClientRect();
            return {
                x: event.clientX - rect.left,
                y: event.clientY - rect.top,
            };
        }

        /**
         * Convert canvas coordinates to image coordinates.
         */
        _canvasToImage(point) {
            return {
                x: (point.x - this.offsetX) / this.scale,
                y: (point.y - this.offsetY) / this.scale,
            };
        }

        /**
         * Convert image coordinates to canvas coordinates.
         */
        _imageToCanvas(point) {
            return {
                x: point.x * this.scale + this.offsetX,
                y: point.y * this.scale + this.offsetY,
            };
        }

        /**
         * Get band at point.
         */
        _getBandAtPoint(point) {
            const bands = this.state.getAllBands();

            for (const band of bands) {
                if (!band.bbox) continue;

                const bbox = band.bbox;
                if (
                    point.x >= bbox.x &&
                    point.x <= bbox.x + bbox.width &&
                    point.y >= bbox.y &&
                    point.y <= bbox.y + bbox.height
                ) {
                    return band;
                }
            }

            return null;
        }

        /**
         * Get lane at point: inside its outline (the server's Rule 2), not its box -- a tilted lane's box takes in
         * its neighbours.
         */
        _getLaneAtPoint(point) {
            const G = GelAnalyzer.LaneGeometry;
            const lanes = this.state.getAllLanes();

            for (const lane of lanes) {
                if (!lane.bbox && !lane.outline) continue;
                if (G.pointInPolygon(point.x, point.y, G.outlineOfPayload(lane))) {
                    return lane;
                }
            }

            return null;
        }

        /**
         * Render the canvas.
         */
        _render() {
            if (!this.ctx || !this.canvas) return;

            const ctx = this.ctx;

            // Clear canvas
            ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

            // Draw image
            if (this.image && this.imageLoaded) {
                this._drawImage();
            }

            // Draw lanes and bands (if overlay enabled)
            if (this.showBands) {
                this._drawLanes();
                this._drawBands();
            }
        }

        /**
         * Draw the gel image with adjustments.
         */
        _drawImage() {
            const ctx = this.ctx;

            ctx.save();

            // Apply transformations
            ctx.translate(this.offsetX, this.offsetY);
            ctx.scale(this.scale, this.scale);

            // Apply CSS filters for adjustments
            ctx.filter = this._getFilterString();

            ctx.drawImage(this.image, 0, 0);

            ctx.restore();
        }

        /**
         * Get CSS filter string for adjustments.
         */
        _getFilterString() {
            const { brightness, contrast, invert } = this.adjustments;
            return `brightness(${brightness}%) contrast(${contrast}%) invert(${invert ? 1 : 0})`;
        }

        /**
         * Draw lane overlays.
         */
        _drawLanes() {
            if (!this.ctx) return;

            const ctx = this.ctx;
            const lanes = this.state.getAllLanes();
            const selectedLaneId = this.state.selectedLaneId;
            // Anti-HCP western only (null otherwise); redrawn on READOUTS_UPDATED.
            const referenceLaneId = typeof this.state.getHcpReferenceLaneId === 'function'
                ? this.state.getHcpReferenceLaneId()
                : null;

            const G = GelAnalyzer.LaneGeometry;

            lanes.forEach(lane => {
                if (!lane.bbox && !lane.outline) return;

                // The lane's outline (a rectangle's four corners), its label at the left end of its top row.
                const outline = G.outlineOfPayload(lane);
                const [labelX, labelY] = G.topLeft(outline);
                const topLeft = this._imageToCanvas({ x: labelX, y: labelY });
                const tracePath = () => {
                    ctx.beginPath();
                    outline.forEach(([x, y], i) => {
                        const p = this._imageToCanvas({ x, y });
                        if (i === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y);
                    });
                    ctx.closePath();
                };

                const isSelected = lane.id === selectedLaneId;
                const isReference = referenceLaneId !== null && Number(lane.id) === referenceLaneId;

                // Fill + border colors keyed off lane_type so a CALIBRATION
                // lane reads red, CONTROL reads cyan, LADDER reads orange —
                // matching the annotation page.
                let fill, border;
                switch (lane.lane_type) {
                    case 'CALIBRATION':
                        fill = this.colors.laneCalibration;
                        border = this.colors.laneCalibrationBorder;
                        break;
                    case 'CONTROL':
                        fill = this.colors.laneControl;
                        border = this.colors.laneControlBorder;
                        break;
                    case 'LADDER':
                        fill = this.colors.laneLadder;
                        border = this.colors.laneLadderBorder;
                        break;
                    case 'EMPTY':
                        fill = this.colors.laneEmpty;
                        border = this.colors.laneEmptyBorder;
                        break;
                    case 'SAMPLE':
                    default:
                        fill = this.colors.laneSample;
                        border = this.colors.laneSampleBorder;
                }
                ctx.fillStyle = isSelected ? this.colors.laneSelected : fill;
                tracePath();
                ctx.fill();

                // Border (the HCP reference gets its own, whatever its type)
                ctx.strokeStyle = isReference ? this.colors.laneReferenceBorder : border;
                ctx.lineWidth = isReference ? 2.5 : (isSelected ? 2 : 1);
                tracePath();
                ctx.stroke();

                // Lane number label
                const label = `L${lane.lane_number}`;
                ctx.fillStyle = '#fff';
                ctx.font = '12px sans-serif';
                ctx.fillText(
                    label,
                    topLeft.x + 5,
                    topLeft.y + 15
                );

                // "REF" tag under the label, inside the lane: right of the label it ran over the next
                // lane's number on a gel with narrow lanes
                if (isReference) {
                    const tagX = topLeft.x + 4;
                    const tagY = topLeft.y + 20;
                    ctx.font = 'bold 9px sans-serif';
                    const tagWidth = ctx.measureText('REF').width + 6;
                    ctx.fillStyle = this.colors.laneReferenceBorder;
                    ctx.fillRect(tagX, tagY, tagWidth, 12);
                    ctx.fillStyle = this.colors.laneReferenceInk;
                    ctx.fillText('REF', tagX + 3, tagY + 9.5);
                }
            });
        }

        /**
         * Draw band overlays.
         */
        _drawBands() {
            if (!this.ctx) return;

            const ctx = this.ctx;
            const bands = this.state.getAllBands();
            const selectedBandId = this.state.selectedBandId;

            bands.forEach(band => {
                if (!band.bbox) return;

                const topLeft = this._imageToCanvas({ x: band.bbox.x, y: band.bbox.y });
                const width = band.bbox.width * this.scale;
                const height = band.bbox.height * this.scale;

                const isSelected = band.id === selectedBandId;

                // Fill color based on band type — CALIBRATION used to
                // fall through to bandOther (green), making calibration
                // points indistinguishable from regular bands once the
                // user crossed over from annotate to densito.
                let fillColor;
                const roleFill = {
                    aggregate: this.colors.bandAggregate,
                    main: this.colors.bandMain,
                    clipping: this.colors.bandClipping,
                    left_out: this.colors.bandLeftOut,
                    hcp: this.colors.bandOther,
                }[band.role];
                if (roleFill) {
                    fillColor = roleFill;
                } else switch (band.band_type) {
                    case 'POI':
                        fillColor = this.colors.bandPOI;
                        break;
                    case 'MW_REFERENCE':
                        fillColor = this.colors.bandRef;
                        break;
                    case 'CALIBRATION':
                        fillColor = this.colors.bandCalibration;
                        break;
                    default:
                        fillColor = this.colors.bandOther;
                }

                ctx.fillStyle = fillColor;
                ctx.fillRect(topLeft.x, topLeft.y, width, height);

                // Border for selected
                if (isSelected) {
                    ctx.strokeStyle = this.colors.bandSelected;
                    ctx.lineWidth = 2;
                    ctx.strokeRect(topLeft.x, topLeft.y, width, height);
                }
            });
        }

        /**
         * Set adjustments.
         */
        setAdjustments(adjustments) {
            this.adjustments = { ...this.adjustments, ...adjustments };
            this._render();
        }

        /**
         * Reset adjustments.
         */
        resetAdjustments() {
            this.adjustments = { brightness: 100, contrast: 100, invert: false };
            this._render();
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
    global.Densitometry.GelOverviewPanel = GelOverviewPanel;

})(window);
