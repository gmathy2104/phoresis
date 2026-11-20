/**
 * Viewport - Pan & Zoom Controller for GelViewer
 *
 * Handles viewport transformations, pan/zoom operations,
 * and minimap updates.
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    /**
     * Viewport Class
     * Manages pan/zoom and viewport state.
     */
    class Viewport {
        /**
         * Create a Viewport instance.
         * @param {Object} options - Configuration options
         * @param {HTMLElement} options.viewer - The viewer element
         * @param {HTMLElement} options.canvasContainer - The canvas container element
         * @param {number} options.imageWidth - Original image width
         * @param {number} options.imageHeight - Original image height
         * @param {EventBus} options.eventBus - EventBus instance
         */
        constructor(options) {
            this.viewer = options.viewer;
            this.canvasContainer = options.canvasContainer;
            this.imageWidth = options.imageWidth;
            this.imageHeight = options.imageHeight;
            this.eventBus = options.eventBus;

            // Viewport state
            this.scale = 1;
            this.panX = 0;
            this.panY = 0;
            this.minScale = 0.1;
            this.maxScale = 10;

            // Pan state
            this.isPanning = false;
            this.panStart = null;

            // Showing the whole gel (fitToView, with its options), until a zoom or a pan (slice 3c)
            this._fitted = false;
            this._fitOptions = {};

            this._setupZoomControls();
            this._watchViewerSize();
        }

        /**
         * The gel area changes size without a window resize: the profile docked under it opens or closes, d1/d2
         * borrows it and gives it back, the sidebar slides out. A gel shown whole is fitted again, with the options
         * of its last fit (the lane review's room for its tags); a zoom on a lane is kept.
         */
        _watchViewerSize() {
            if (!this.viewer || !global.ResizeObserver) return;
            let frame = null;
            this._resizeObserver = new ResizeObserver(() => {
                if (frame) cancelAnimationFrame(frame);
                frame = requestAnimationFrame(() => {
                    frame = null;
                    if (this._fitted) this.fitToView(this._fitOptions);
                });
            });
            this._resizeObserver.observe(this.viewer);
        }

        /**
         * Whether the viewer shows the whole gel as fitToView left it (no zoom, no pan since).
         * @returns {boolean}
         */
        isFitted() {
            return this._fitted;
        }

        /**
         * Setup zoom control buttons.
         */
        _setupZoomControls() {
            const zoomInBtn = document.getElementById('zoom-in');
            const zoomOutBtn = document.getElementById('zoom-out');
            // Support both 'zoom-fit' (new) and 'fit-to-view' (legacy) button IDs
            const fitToViewBtn = document.getElementById('zoom-fit') || document.getElementById('fit-to-view');

            if (zoomInBtn) {
                zoomInBtn.addEventListener('click', () => this.zoom(1.2));
            }
            if (zoomOutBtn) {
                zoomOutBtn.addEventListener('click', () => this.zoom(0.8));
            }
            if (fitToViewBtn) {
                fitToViewBtn.addEventListener('click', () => this.fitToView());
            }
        }

        // =====================================================================
        // Pan Operations
        // =====================================================================

        /**
         * Start panning.
         * @param {MouseEvent} e - Mouse event
         */
        startPan(e) {
            if (!this.viewer) return;
            this.isPanning = true;
            this.panStart = { x: e.clientX - this.panX, y: e.clientY - this.panY };
            this.viewer.classList.add('panning');
        }

        /**
         * Update pan position.
         * @param {MouseEvent} e - Mouse event
         */
        updatePan(e) {
            if (!this.isPanning) return;

            this.panX = e.clientX - this.panStart.x;
            this.panY = e.clientY - this.panStart.y;
            this._fitted = false;
            this._updateTransform();

            this.eventBus.emit(Events.PAN_CHANGED, {
                panX: this.panX,
                panY: this.panY
            });
        }

        /**
         * End panning.
         */
        endPan() {
            this.isPanning = false;
            if (this.viewer) {
                this.viewer.classList.remove('panning');
            }
        }

        /**
         * Check if currently panning.
         * @returns {boolean}
         */
        getIsPanning() {
            return this.isPanning;
        }

        // =====================================================================
        // Zoom Operations
        // =====================================================================

        /**
         * Zoom by a factor.
         * @param {number} factor - Zoom factor (1.2 = zoom in 20%, 0.8 = zoom out 20%)
         * @param {Object} [center] - Center point for zoom {x, y}
         */
        zoom(factor, center = null) {
            const newScale = Math.max(this.minScale, Math.min(this.maxScale, this.scale * factor));

            if (newScale === this.scale) return;
            this._fitted = false;

            if (center) {
                // Zoom towards point
                const viewX = center.x * this.scale + this.panX;
                const viewY = center.y * this.scale + this.panY;

                this.scale = newScale;

                this.panX = viewX - center.x * this.scale;
                this.panY = viewY - center.y * this.scale;
            } else if (this.viewer) {
                // Zoom towards center (requires viewer element)
                const rect = this.viewer.getBoundingClientRect();
                const centerX = rect.width / 2;
                const centerY = rect.height / 2;

                const oldScale = this.scale;
                this.scale = newScale;

                this.panX = centerX - (centerX - this.panX) * (newScale / oldScale);
                this.panY = centerY - (centerY - this.panY) * (newScale / oldScale);
            } else {
                // No viewer, just update scale without centering
                this.scale = newScale;
            }

            this._updateTransform();
            this._updateZoomDisplay();

            this.eventBus.emit(Events.ZOOM_CHANGED, {
                scale: this.scale,
                panX: this.panX,
                panY: this.panY
            });
        }

        /**
         * Set zoom to a specific scale.
         * @param {number} scale - Target scale value
         */
        setZoom(scale) {
            const factor = scale / this.scale;
            this.zoom(factor);
        }

        /**
         * Handle wheel event for zoom.
         * @param {WheelEvent} e - Wheel event
         */
        handleWheel(e) {
            e.preventDefault();

            const factor = e.deltaY < 0 ? 1.1 : 0.9;
            const point = this.getImagePoint(e);
            this.zoom(factor, point);
        }

        // =====================================================================
        // Fit to View
        // =====================================================================

        /**
         * Fit the image to the viewport.
         *
         * The gel fills the viewer (90 % of the fitting scale). The cap was 60 % until 2026-10-17: a gel image smaller
         * than the viewer (a large screen, a cropped gel) stopped at 60 % and sat small in the middle, which read as
         * "Fit does nothing" (owner). 3 is the lane review's cap: a tiny image is enlarged, never absurdly.
         * @param {Object} [options]
         * @param {number} [options.maxScale=3] - zoom cap
         * @param {number} [options.fill=0.9] - share of the fitting scale used
         * @param {number} [options.padX=0] - screen pixels kept free left and right
         * @param {number} [options.padY=0] - screen pixels kept free above and below (the lane review's tags)
         */
        fitToView(options = {}) {
            if (!this.viewer) {
                console.warn('Viewport: viewer element not available');
                return;
            }
            const rect = this.viewer.getBoundingClientRect();
            const { maxScale = 3, fill = 0.9, padX = 0, padY = 0 } = options;

            // Calculate scale to fit within viewport
            const fitScale = Math.min(
                (rect.width - 2 * padX) / this.imageWidth,
                (rect.height - 2 * padY) / this.imageHeight
            );

            this.scale = Math.min(fitScale * fill, maxScale);

            // Calculate scaled dimensions
            const scaledWidth = this.imageWidth * this.scale;
            const scaledHeight = this.imageHeight * this.scale;

            // Center in viewport
            this.panX = (rect.width - scaledWidth) / 2;
            this.panY = (rect.height - scaledHeight) / 2;
            this._fitted = true;
            this._fitOptions = options;

            this._updateTransform();
            this._updateZoomDisplay();

            this.eventBus.emit(Events.VIEWPORT_CHANGED, {
                scale: this.scale,
                panX: this.panX,
                panY: this.panY
            });
        }

        // =====================================================================
        // Transform Updates
        // =====================================================================

        /**
         * Update the CSS transform.
         */
        _updateTransform() {
            if (this.canvasContainer) {
                this.canvasContainer.style.transform =
                    `translate(${this.panX}px, ${this.panY}px) scale(${this.scale})`;
            }
            this._updateMinimap();
        }

        /**
         * Update the zoom display.
         */
        _updateZoomDisplay() {
            const display = document.querySelector('.gv-zoom-display');
            if (display) {
                display.textContent = Math.round(this.scale * 100) + '%';
            }
        }

        /**
         * Update minimap viewport indicator.
         */
        _updateMinimap() {
            const viewport = document.querySelector('.gv-minimap-viewport');
            const minimap = document.querySelector('.gv-minimap');
            if (!viewport || !minimap || !this.viewer) return;

            const minimapRect = minimap.getBoundingClientRect();
            const minimapWidth = minimapRect.width;
            const minimapHeight = minimapRect.height;

            const viewerRect = this.viewer.getBoundingClientRect();
            const viewerWidth = viewerRect.width;
            const viewerHeight = viewerRect.height;

            // Calculate visible area in image coordinates
            const visibleLeft = -this.panX / this.scale;
            const visibleTop = -this.panY / this.scale;
            const visibleWidth = viewerWidth / this.scale;
            const visibleHeight = viewerHeight / this.scale;

            // Map to minimap coordinates
            const imageAspect = this.imageWidth / this.imageHeight;
            const minimapAspect = minimapWidth / minimapHeight;

            let offsetX = 0, offsetY = 0;
            let scaledWidth, scaledHeight;

            if (imageAspect > minimapAspect) {
                scaledWidth = minimapWidth;
                scaledHeight = minimapWidth / imageAspect;
                offsetY = (minimapHeight - scaledHeight) / 2;
            } else {
                scaledHeight = minimapHeight;
                scaledWidth = minimapHeight * imageAspect;
                offsetX = (minimapWidth - scaledWidth) / 2;
            }

            const finalScale = scaledWidth / this.imageWidth;

            let left = offsetX + (visibleLeft * finalScale);
            let top = offsetY + (visibleTop * finalScale);
            let width = visibleWidth * finalScale;
            let height = visibleHeight * finalScale;

            // Clamp to minimap bounds
            left = Math.max(offsetX, Math.min(left, offsetX + scaledWidth - 2));
            top = Math.max(offsetY, Math.min(top, offsetY + scaledHeight - 2));
            width = Math.min(width, scaledWidth);
            height = Math.min(height, scaledHeight);

            // Hide viewport if viewing full image
            if (width >= scaledWidth && height >= scaledHeight) {
                viewport.style.display = 'none';
            } else {
                viewport.style.display = 'block';
                viewport.style.left = `${left}px`;
                viewport.style.top = `${top}px`;
                viewport.style.width = `${Math.max(10, width)}px`;
                viewport.style.height = `${Math.max(10, height)}px`;
            }
        }

        // =====================================================================
        // Coordinate Utilities
        // =====================================================================

        /**
         * Convert screen coordinates to image coordinates.
         * @param {MouseEvent} e - Mouse event
         * @returns {Object} Image coordinates {x, y}
         */
        getImagePoint(e) {
            if (!this.canvasContainer) {
                return { x: 0, y: 0 };
            }
            const rect = this.canvasContainer.getBoundingClientRect();
            return {
                x: (e.clientX - rect.left) / this.scale,
                y: (e.clientY - rect.top) / this.scale,
            };
        }

        /**
         * Get current viewport state.
         * @returns {Object} {scale, panX, panY}
         */
        getState() {
            return {
                scale: this.scale,
                panX: this.panX,
                panY: this.panY
            };
        }

        /**
         * Get the current scale.
         * @returns {number}
         */
        getScale() {
            return this.scale;
        }
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.Viewport = Viewport;

})(window);
