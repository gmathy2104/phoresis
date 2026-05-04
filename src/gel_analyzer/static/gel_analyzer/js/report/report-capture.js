/**
 * Report Capture Module - High-Resolution Image Capture for Word Reports
 *
 * Captures all densitometry panels as base64 PNG images for Word report generation.
 * Includes gel overview, 2D/3D electropherograms, and digital lane visualizations.
 *
 * Features:
 * - High-resolution capture (3x scale factor for ~300 DPI print quality)
 * - Canvas, SVG, and WebGL capture support
 * - Automatic CSS inlining for SVG serialization
 * - Per-lane capture with automatic lane switching
 * - Graceful error handling
 */

(function(global) {
    'use strict';

    const Events = global.Densitometry.Events;

    /**
     * ReportCapture Class
     *
     * Captures high-resolution images of all densitometry panels for report generation.
     */
    class ReportCapture {
        /**
         * @param {DensitometryApp} app - Reference to DensitometryApp instance
         * @param {Object} options - Configuration options
         * @param {number} options.scaleFactor - Resolution scale factor (default: 3)
         * @param {string} options.format - Image format (default: 'image/png')
         * @param {number} options.quality - Image quality 0-1 (default: 1.0)
         */
        constructor(app, options = {}) {
            this.app = app;
            this.scaleFactor = options.scaleFactor || 3;
            this.format = options.format || 'image/png';
            this.quality = options.quality || 1.0;

            // Store original selected lane for restoration
            this.originalSelectedLaneId = null;
        }

        // =====================================================================
        // Main Capture Method
        // =====================================================================

        /**
         * Capture all panels for all lanes.
         * Returns an object with gel overview and per-lane captures.
         *
         * @returns {Promise<Object>} - Captured images organized by panel type
         * @example
         * {
         *     gel_overview: "data:image/png;base64,...",
         *     lanes: {
         *         "1": {
         *             electropherogram_2d: "data:image/png;base64,...",
         *             electropherogram_3d: "data:image/png;base64,...",  // or null
         *             digital_lane: "data:image/png;base64,...",
         *         },
         *         "2": { ... }
         *     }
         * }
         */
        async captureAll() {
            console.log('[ReportCapture] Starting capture of all panels');

            const result = {
                gel_overview: null,
                lanes: {}
            };

            // Store original selection
            this.originalSelectedLaneId = this.app.state.selectedLaneId;

            try {
                // 1. Capture gel overview (always visible)
                result.gel_overview = await this._captureGelOverview();

                // 2. Get sorted lanes
                const lanes = this._getSortedLanes();

                // 3. Capture each lane
                for (const lane of lanes) {
                    console.log(`[ReportCapture] Capturing lane ${lane.lane_number}`);

                    const laneCaptures = {
                        electropherogram_2d: null,
                        electropherogram_3d: null,
                        digital_lane: null
                    };

                    try {
                        // Select lane and wait for render
                        this.app.state.selectLane(lane.id);
                        await this._waitForRender(200);

                        // Capture 2D electropherogram
                        laneCaptures.electropherogram_2d = await this._captureChromatogram2D();

                        // Capture 3D electropherogram (if available)
                        laneCaptures.electropherogram_3d = await this._captureChromatogram3D();

                        // Capture digital lane
                        laneCaptures.digital_lane = await this._captureDigitalLane();

                    } catch (error) {
                        console.warn(`[ReportCapture] Failed to capture lane ${lane.lane_number}:`, error);
                    }

                    // Store under lane number (not ID, for easier reporting)
                    result.lanes[lane.lane_number] = laneCaptures;
                }

                // Restore original selection
                if (this.originalSelectedLaneId) {
                    this.app.state.selectLane(this.originalSelectedLaneId);
                } else {
                    this.app.state.clearSelection();
                }

                console.log('[ReportCapture] Capture complete');
                return result;

            } catch (error) {
                console.error('[ReportCapture] Fatal error during capture:', error);
                // Restore selection on error
                if (this.originalSelectedLaneId) {
                    this.app.state.selectLane(this.originalSelectedLaneId);
                }
                throw error;
            }
        }

        // =====================================================================
        // Panel Capture Methods
        // =====================================================================

        /**
         * Capture gel overview panel (canvas-based).
         * @returns {Promise<string|null>} - Base64 PNG data URL or null on error
         */
        async _captureGelOverview() {
            try {
                const panel = this.app.panels.gelOverview;
                if (!panel || !panel.canvas) {
                    console.warn('[ReportCapture] Gel overview panel not available');
                    return null;
                }

                return this._captureCanvas(panel.canvas);
            } catch (error) {
                console.warn('[ReportCapture] Failed to capture gel overview:', error);
                return null;
            }
        }

        /**
         * Capture 2D chromatogram (D3.js SVG).
         * @returns {Promise<string|null>} - Base64 PNG data URL or null on error
         */
        async _captureChromatogram2D() {
            try {
                const panel = this.app.panels.chromatogram;
                if (!panel || !panel.svg) {
                    console.warn('[ReportCapture] Chromatogram panel not available');
                    return null;
                }

                // Ensure 2D mode is active
                const was3D = panel.is3DMode;
                if (was3D) {
                    panel._enforce3DVisibility(false);
                    await this._waitForRender(100);
                }

                const svgNode = panel.svg.node();
                const result = await this._captureSVG(svgNode);

                // Restore 3D mode if it was active
                if (was3D) {
                    panel._enforce3DVisibility(true);
                }

                return result;
            } catch (error) {
                console.warn('[ReportCapture] Failed to capture 2D chromatogram:', error);
                return null;
            }
        }

        /**
         * Capture 3D chromatogram (Three.js WebGL canvas).
         * @returns {Promise<string|null>} - Base64 PNG data URL or null on error
         */
        async _captureChromatogram3D() {
            try {
                const panel = this.app.panels.chromatogram;
                if (!panel || !panel.renderer3D) {
                    return null; // 3D not available
                }

                // Check if 3D container exists
                const container3d = panel.contentElement?.querySelector('.dm-chromatogram-3d-container');
                if (!container3d) {
                    return null;
                }

                // Switch to 3D mode
                const was2D = !panel.is3DMode;
                if (was2D) {
                    panel.is3DMode = true;
                    panel._enforce3DVisibility(true);

                    // Render current profile in 3D
                    const profile = panel.state.getProfile(panel.currentLaneId);
                    const bands = panel._getBandsForCurrentLane();
                    if (profile && panel.renderer3D) {
                        panel.renderer3D.render(profile, bands);
                    }

                    await this._waitForRender(300); // Extra time for WebGL
                }

                // Find the Three.js canvas
                const canvas = container3d.querySelector('canvas');
                if (!canvas) {
                    console.warn('[ReportCapture] 3D canvas not found');
                    return null;
                }

                const result = await this._captureWebGL(canvas);

                // Restore 2D mode if needed
                if (was2D) {
                    panel.is3DMode = false;
                    panel._enforce3DVisibility(false);
                }

                return result;
            } catch (error) {
                console.warn('[ReportCapture] Failed to capture 3D chromatogram:', error);
                return null;
            }
        }

        /**
         * Capture digital lane visualization.
         * @returns {Promise<string|null>} - Base64 PNG data URL or null on error
         */
        async _captureDigitalLane() {
            try {
                const panel = this.app.panels.bandZoom;
                if (!panel) {
                    console.warn('[ReportCapture] Band zoom panel not available');
                    return null;
                }

                // Find digital lane container
                const container = panel.contentElement?.querySelector('.dm-digital-lane-main');
                if (!container) {
                    console.warn('[ReportCapture] Digital lane container not found');
                    return null;
                }

                // Capture as HTML to canvas
                return await this._captureHTMLElement(container);
            } catch (error) {
                console.warn('[ReportCapture] Failed to capture digital lane:', error);
                return null;
            }
        }

        // =====================================================================
        // Capture Primitives
        // =====================================================================

        /**
         * Capture a canvas element at high resolution.
         * @param {HTMLCanvasElement} canvasElement - Canvas to capture
         * @returns {string} - Base64 PNG data URL
         */
        _captureCanvas(canvasElement) {
            if (!canvasElement || !canvasElement.getContext) {
                throw new Error('Invalid canvas element');
            }

            // Create offscreen canvas at high resolution
            const offscreen = document.createElement('canvas');
            offscreen.width = canvasElement.width * this.scaleFactor;
            offscreen.height = canvasElement.height * this.scaleFactor;

            const ctx = offscreen.getContext('2d');
            ctx.scale(this.scaleFactor, this.scaleFactor);
            ctx.drawImage(canvasElement, 0, 0);

            return offscreen.toDataURL(this.format, this.quality);
        }

        /**
         * Capture an SVG element as high-resolution PNG.
         * @param {SVGElement} svgElement - SVG element to capture
         * @returns {Promise<string>} - Base64 PNG data URL
         */
        async _captureSVG(svgElement) {
            if (!svgElement || svgElement.tagName !== 'svg') {
                throw new Error('Invalid SVG element');
            }

            // Clone SVG to avoid modifying original
            const clonedSvg = svgElement.cloneNode(true);

            // Ensure xmlns attribute for standalone SVG
            clonedSvg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');

            // Inline CSS styles (critical for Word compatibility)
            this._inlineStyles(clonedSvg);

            // Inline external <image> hrefs to prevent tainted canvas
            await this._inlineSVGImages(clonedSvg);

            // Get SVG dimensions
            const bbox = svgElement.getBBox();
            const width = parseFloat(svgElement.getAttribute('width')) || bbox.width;
            const height = parseFloat(svgElement.getAttribute('height')) || bbox.height;

            // Serialize SVG to data URI (NOT blob URI — blob taints canvas in Chrome)
            const svgString = new XMLSerializer().serializeToString(clonedSvg);
            const url = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svgString);

            return new Promise((resolve, reject) => {
                const img = new Image();
                img.onload = () => {
                    const canvas = document.createElement('canvas');
                    canvas.width = width * this.scaleFactor;
                    canvas.height = height * this.scaleFactor;

                    const ctx = canvas.getContext('2d');
                    ctx.scale(this.scaleFactor, this.scaleFactor);
                    ctx.drawImage(img, 0, 0, width, height);

                    resolve(canvas.toDataURL(this.format, this.quality));
                };

                img.onerror = (error) => {
                    reject(new Error('Failed to load SVG as image: ' + error));
                };

                img.src = url;
            });
        }

        /**
         * Capture a WebGL canvas (Three.js).
         * @param {HTMLCanvasElement} canvasElement - WebGL canvas to capture
         * @returns {string} - Base64 PNG data URL
         */
        _captureWebGL(canvasElement) {
            if (!canvasElement || !canvasElement.getContext) {
                throw new Error('Invalid WebGL canvas element');
            }

            // Note: Three.js renderer should have preserveDrawingBuffer: true
            // If not, force a render first (handled by caller)

            // Create offscreen canvas at high resolution
            const offscreen = document.createElement('canvas');
            offscreen.width = canvasElement.width * this.scaleFactor;
            offscreen.height = canvasElement.height * this.scaleFactor;

            const ctx = offscreen.getContext('2d');
            ctx.scale(this.scaleFactor, this.scaleFactor);
            ctx.drawImage(canvasElement, 0, 0, canvasElement.width, canvasElement.height);

            return offscreen.toDataURL(this.format, this.quality);
        }

        /**
         * Capture an HTML element by rendering to canvas.
         * Uses foreignObject approach with inline styles.
         * Converts external resources to data URIs to prevent tainted canvas.
         *
         * @param {HTMLElement} element - Element to capture
         * @returns {Promise<string>} - Base64 PNG data URL
         */
        async _captureHTMLElement(element) {
            const rect = element.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) {
                throw new Error('Element has no dimensions');
            }

            // Clone element and inline all external resources to avoid tainted canvas
            const clonedElement = element.cloneNode(true);
            this._inlineHTMLStyles(clonedElement);
            await this._inlineExternalResources(clonedElement, element);

            // Create canvas at high resolution
            const canvas = document.createElement('canvas');
            canvas.width = rect.width * this.scaleFactor;
            canvas.height = rect.height * this.scaleFactor;

            const ctx = canvas.getContext('2d');
            ctx.scale(this.scaleFactor, this.scaleFactor);

            // Fill with background
            ctx.fillStyle = '#fff';
            ctx.fillRect(0, 0, rect.width, rect.height);

            // Build foreignObject SVG
            const svgNS = 'http://www.w3.org/2000/svg';
            const svg = document.createElementNS(svgNS, 'svg');
            svg.setAttribute('width', rect.width);
            svg.setAttribute('height', rect.height);
            svg.setAttribute('xmlns', svgNS);

            const foreignObject = document.createElementNS(svgNS, 'foreignObject');
            foreignObject.setAttribute('width', '100%');
            foreignObject.setAttribute('height', '100%');
            foreignObject.appendChild(clonedElement);
            svg.appendChild(foreignObject);

            // Serialize to data URI (NOT blob URI — blob taints canvas in Chrome)
            const svgString = new XMLSerializer().serializeToString(svg);
            const url = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svgString);

            return new Promise((resolve, reject) => {
                const img = new Image();
                img.onload = () => {
                    ctx.drawImage(img, 0, 0, rect.width, rect.height);
                    resolve(canvas.toDataURL(this.format, this.quality));
                };
                img.onerror = (error) => {
                    reject(new Error('Failed to render HTML element: ' + error));
                };
                img.src = url;
            });
        }

        /**
         * Convert external resources (images, canvases) inside a cloned element
         * to inline data URIs to prevent tainted canvas errors.
         *
         * @param {Element} clonedRoot - Cloned DOM tree (will be mutated)
         * @param {Element} originalRoot - Original DOM tree (for reading canvas pixels)
         */
        async _inlineExternalResources(clonedRoot, originalRoot) {
            // 1. Convert <img> elements to inline data URIs
            const clonedImgs = clonedRoot.querySelectorAll('img');
            const originalImgs = originalRoot.querySelectorAll('img');

            for (let i = 0; i < clonedImgs.length; i++) {
                const clonedImg = clonedImgs[i];
                const originalImg = originalImgs[i];
                if (!originalImg || !originalImg.complete || originalImg.naturalWidth === 0) continue;

                try {
                    const c = document.createElement('canvas');
                    c.width = originalImg.naturalWidth;
                    c.height = originalImg.naturalHeight;
                    const cx = c.getContext('2d');
                    cx.drawImage(originalImg, 0, 0);
                    clonedImg.src = c.toDataURL('image/png');
                } catch (e) {
                    // If even this is tainted, fetch via same-origin proxy
                    try {
                        const dataUri = await this._fetchAsDataUri(originalImg.src);
                        if (dataUri) clonedImg.src = dataUri;
                    } catch (_) {
                        clonedImg.removeAttribute('src');
                        console.warn('[ReportCapture] Could not inline image, removed src');
                    }
                }
            }

            // 2. Replace <canvas> elements with <img> snapshots
            const clonedCanvases = clonedRoot.querySelectorAll('canvas');
            const originalCanvases = originalRoot.querySelectorAll('canvas');

            for (let i = 0; i < clonedCanvases.length; i++) {
                const clonedCanvas = clonedCanvases[i];
                const originalCanvas = originalCanvases[i];
                if (!originalCanvas) continue;

                try {
                    const dataUrl = originalCanvas.toDataURL('image/png');
                    const replacement = document.createElement('img');
                    replacement.src = dataUrl;
                    replacement.width = originalCanvas.width;
                    replacement.height = originalCanvas.height;
                    replacement.style.cssText = clonedCanvas.style.cssText;
                    clonedCanvas.parentNode.replaceChild(replacement, clonedCanvas);
                } catch (e) {
                    clonedCanvas.remove();
                    console.warn('[ReportCapture] Could not inline canvas, removed');
                }
            }

            // 3. Handle SVG <image> elements with external href
            const svgImages = clonedRoot.querySelectorAll('image');
            for (const svgImg of svgImages) {
                const href = svgImg.getAttribute('href') || svgImg.getAttributeNS('http://www.w3.org/1999/xlink', 'href');
                if (href && !href.startsWith('data:')) {
                    try {
                        const dataUri = await this._fetchAsDataUri(href);
                        if (dataUri) {
                            svgImg.setAttribute('href', dataUri);
                            svgImg.removeAttributeNS('http://www.w3.org/1999/xlink', 'href');
                        }
                    } catch (_) {
                        svgImg.remove();
                        console.warn('[ReportCapture] Could not inline SVG image, removed');
                    }
                }
            }
        }

        /**
         * Inline external <image> hrefs inside a cloned SVG to prevent tainted canvas.
         * @param {SVGElement} clonedSvg - Cloned SVG element (will be mutated)
         */
        async _inlineSVGImages(clonedSvg) {
            const images = clonedSvg.querySelectorAll('image');
            for (const svgImg of images) {
                const href = svgImg.getAttribute('href')
                    || svgImg.getAttributeNS('http://www.w3.org/1999/xlink', 'href');
                if (href && !href.startsWith('data:')) {
                    try {
                        const dataUri = await this._fetchAsDataUri(href);
                        if (dataUri) {
                            svgImg.setAttribute('href', dataUri);
                            svgImg.removeAttributeNS('http://www.w3.org/1999/xlink', 'href');
                        }
                    } catch (e) {
                        svgImg.remove();
                        console.warn('[ReportCapture] Could not inline SVG <image>, removed');
                    }
                }
            }
        }

        /**
         * Fetch a URL as a base64 data URI via same-origin request.
         * @param {string} url - URL to fetch
         * @returns {Promise<string>} - data URI string
         */
        async _fetchAsDataUri(url) {
            const response = await fetch(url, { credentials: 'same-origin' });
            const blob = await response.blob();
            return new Promise((resolve) => {
                const reader = new FileReader();
                reader.onloadend = () => resolve(reader.result);
                reader.readAsDataURL(blob);
            });
        }

        // =====================================================================
        // Style Inlining (for SVG/HTML serialization)
        // =====================================================================

        /**
         * Inline computed CSS styles onto SVG elements.
         * Required for SVG serialization to preserve external CSS.
         *
         * @param {Element} element - Root element to process (modifies in place)
         */
        _inlineStyles(element) {
            const elements = [element, ...element.querySelectorAll('*')];

            elements.forEach(el => {
                const computedStyle = window.getComputedStyle(el);

                // Key SVG style properties to inline
                const stylesToCopy = [
                    'fill', 'stroke', 'stroke-width', 'stroke-dasharray',
                    'opacity', 'font-size', 'font-family', 'font-weight',
                    'text-anchor', 'dominant-baseline', 'display', 'visibility',
                    'color', 'background-color', 'border', 'padding', 'margin'
                ];

                stylesToCopy.forEach(prop => {
                    const value = computedStyle.getPropertyValue(prop);
                    if (value && value !== 'none' && value !== 'normal') {
                        el.style[prop] = value;
                    }
                });
            });
        }

        /**
         * Inline computed CSS styles onto HTML elements.
         * Similar to _inlineStyles but for HTML elements.
         *
         * @param {Element} element - Root element to process (modifies in place)
         */
        _inlineHTMLStyles(element) {
            const elements = [element, ...element.querySelectorAll('*')];

            elements.forEach(el => {
                const computedStyle = window.getComputedStyle(el);

                // Copy all computed styles (more comprehensive for HTML)
                const styleDeclaration = el.style;
                for (let i = 0; i < computedStyle.length; i++) {
                    const prop = computedStyle[i];
                    const value = computedStyle.getPropertyValue(prop);
                    if (value && value !== 'none' && value !== 'normal') {
                        styleDeclaration.setProperty(prop, value);
                    }
                }
            });
        }

        // =====================================================================
        // Helper Methods
        // =====================================================================

        /**
         * Wait for render to complete.
         * Uses requestAnimationFrame + setTimeout for D3 transitions and WebGL.
         *
         * @param {number} delay - Additional delay in ms (default: 150)
         * @returns {Promise<void>}
         */
        async _waitForRender(delay = 150) {
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    setTimeout(resolve, delay);
                });
            });
        }

        /**
         * Get lanes sorted by lane number.
         * @returns {Array} - Sorted array of lane objects
         */
        _getSortedLanes() {
            const lanes = Array.from(this.app.state.lanes.values());
            return lanes.sort((a, b) => {
                const numA = a.lane_number || 0;
                const numB = b.lane_number || 0;
                return numA - numB;
            });
        }
    }

    // Export
    global.Densitometry = global.Densitometry || {};
    global.Densitometry.ReportCapture = ReportCapture;

})(window);
