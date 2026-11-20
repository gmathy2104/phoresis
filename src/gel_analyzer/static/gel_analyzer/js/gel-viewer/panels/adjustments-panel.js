/**
 * AdjustmentsPanel - Image Adjustments for GelViewer
 *
 * Handles brightness, contrast, saturation adjustments
 * and auto-enhancement via histogram analysis.
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    /**
     * AdjustmentsPanel Class
     * Manages image adjustment controls and filters.
     */
    class AdjustmentsPanel {
        /**
         * Create an AdjustmentsPanel instance.
         * @param {Object} options - Configuration options
         * @param {HTMLElement} options.imageElement - The gel image element
         * @param {string} options.imageProxyUrl - Proxy URL for CORS-free image access
         * @param {EventBus} options.eventBus - EventBus instance
         * @param {Function} options.showMessage - Function to display messages
         */
        constructor(options) {
            this.imageElement = options.imageElement;
            this.imageProxyUrl = options.imageProxyUrl;
            this.eventBus = options.eventBus;
            // Built without one (GelViewerApp): the editor's toasts, read when a message comes (they exist by then).
            this.showMessage = options.showMessage
                || ((message) => (global.gelViewer && global.gelViewer.toasts
                    ? global.gelViewer.toasts.info(message) : console.log(message)));

            // State
            this.adjustments = {
                brightness: 100,
                contrast: 100,
                saturation: 100,
                invert: false
            };
            this._isVisible = false;

            // DOM elements
            this.panel = document.getElementById('adjustments-panel');
            this.toggleBtn = document.getElementById('adjust-image');

            this._setup();
        }

        /**
         * Setup event handlers.
         */
        _setup() {
            // Toggle button
            if (this.toggleBtn) {
                this.toggleBtn.addEventListener('click', () => this.toggle());
            }

            // Close button
            const closeBtn = document.getElementById('adjustments-close');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this.hide());
            }

            // Sliders
            this._setupSlider('brightness');
            this._setupSlider('contrast');
            this._setupSlider('saturation');

            // Invert checkbox
            const invertCheckbox = document.getElementById('adj-invert');
            if (invertCheckbox) {
                invertCheckbox.addEventListener('change', (e) => {
                    this.adjustments.invert = e.target.checked;
                    this._apply();
                });
            }

            // Auto-enhance button
            const autoEnhanceBtn = document.getElementById('adj-auto-enhance');
            if (autoEnhanceBtn) {
                autoEnhanceBtn.addEventListener('click', () => this.autoEnhance());
            }

            // Reset button
            const resetBtn = document.getElementById('adj-reset');
            if (resetBtn) {
                resetBtn.addEventListener('click', () => this.reset());
            }
        }

        /**
         * Setup a slider with value display.
         */
        _setupSlider(name) {
            const slider = document.getElementById(`adj-${name}`);
            if (slider) {
                slider.addEventListener('input', (e) => {
                    this.adjustments[name] = parseInt(e.target.value);
                    this._updateValueDisplay(name);
                    this._apply();
                });
            }
        }

        /**
         * Update the value display for a slider.
         */
        _updateValueDisplay(name) {
            const valueEl = document.getElementById(`adj-${name}-value`);
            if (valueEl) {
                valueEl.textContent = `${this.adjustments[name]}%`;
            }
        }

        // =====================================================================
        // Panel Visibility
        // =====================================================================

        /**
         * Toggle panel visibility.
         */
        toggle() {
            if (this._isVisible) {
                this.hide();
            } else {
                this.show();
            }
        }

        /**
         * Show the panel.
         */
        show() {
            if (this.panel) {
                this.panel.style.display = 'block';
                this._isVisible = true;
                global.GelViewer.Layers?.open(this.panel, { close: () => this.hide(), isOpen: () => this._isVisible });
            }
            if (this.toggleBtn) {
                this.toggleBtn.classList.add('active');
            }
        }

        /**
         * Hide the panel.
         */
        hide() {
            if (this.panel) {
                this.panel.style.display = 'none';
                this._isVisible = false;
                global.GelViewer.Layers?.close(this.panel);
            }
            if (this.toggleBtn) {
                this.toggleBtn.classList.remove('active');
            }
        }

        // =====================================================================
        // Apply Adjustments
        // =====================================================================

        /**
         * Apply CSS filters to the image.
         */
        _apply() {
            if (!this.imageElement) return;

            const { brightness, contrast, saturation, invert } = this.adjustments;

            this.imageElement.style.filter = `
                brightness(${brightness}%)
                contrast(${contrast}%)
                saturate(${saturation}%)
                invert(${invert ? 1 : 0})
            `.trim().replace(/\s+/g, ' ');

            this.eventBus.emit(Events.IMAGE_ADJUSTED, this.adjustments);
        }

        /**
         * Reset all adjustments to defaults.
         */
        reset() {
            this.adjustments = {
                brightness: 100,
                contrast: 100,
                saturation: 100,
                invert: false
            };

            // Update sliders
            const brightnessSlider = document.getElementById('adj-brightness');
            const contrastSlider = document.getElementById('adj-contrast');
            const saturationSlider = document.getElementById('adj-saturation');
            const invertCheckbox = document.getElementById('adj-invert');

            if (brightnessSlider) brightnessSlider.value = 100;
            if (contrastSlider) contrastSlider.value = 100;
            if (saturationSlider) saturationSlider.value = 100;
            if (invertCheckbox) invertCheckbox.checked = false;

            // Update value displays
            this._updateValueDisplay('brightness');
            this._updateValueDisplay('contrast');
            this._updateValueDisplay('saturation');

            // Apply to image
            this._apply();

            this.eventBus.emit(Events.IMAGE_RESET);
            this.showMessage('Adjustments reset');
        }

        // =====================================================================
        // Auto-Enhancement
        // =====================================================================

        /**
         * Auto-enhance the image by analyzing the histogram.
         */
        async autoEnhance() {
            if (!this.imageElement) {
                this.showMessage('No image to enhance');
                return;
            }

            this.showMessage('Analyzing image...');

            try {
                const imageToAnalyze = await this._loadImageForAnalysis();
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');

                // Use smaller size for performance
                const maxSize = 500;
                const scale = Math.min(1, maxSize / Math.max(imageToAnalyze.naturalWidth, imageToAnalyze.naturalHeight));
                canvas.width = Math.floor(imageToAnalyze.naturalWidth * scale);
                canvas.height = Math.floor(imageToAnalyze.naturalHeight * scale);

                ctx.drawImage(imageToAnalyze, 0, 0, canvas.width, canvas.height);

                const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
                const histogram = this._calculateHistogram(imageData.data);
                const optimal = this._analyzeHistogram(histogram);

                // Apply calculated adjustments
                this.adjustments.brightness = optimal.brightness;
                this.adjustments.contrast = optimal.contrast;
                this.adjustments.saturation = 100;

                // Update sliders
                const brightnessSlider = document.getElementById('adj-brightness');
                const contrastSlider = document.getElementById('adj-contrast');

                if (brightnessSlider) brightnessSlider.value = optimal.brightness;
                if (contrastSlider) contrastSlider.value = optimal.contrast;

                this._updateValueDisplay('brightness');
                this._updateValueDisplay('contrast');

                this._apply();
                this.showMessage('Auto-enhancement applied');

            } catch (error) {
                console.error('Auto-enhance error:', error);
                if (error.message.includes('CORS') || error.message.includes('cross-origin') || error.name === 'SecurityError') {
                    this.showMessage('Cannot analyze: image server blocks access');
                } else {
                    this.showMessage('Auto-enhance failed');
                }
            }
        }

        /**
         * Load image for histogram analysis, avoiding CORS issues.
         */
        async _loadImageForAnalysis() {
            const imageUrl = this.imageProxyUrl || this.imageElement.src;

            const response = await fetch(imageUrl, {
                credentials: 'same-origin'
            });

            if (!response.ok) {
                throw new Error(`Failed to fetch image: ${response.status}`);
            }

            const blob = await response.blob();
            const objectUrl = URL.createObjectURL(blob);

            return new Promise((resolve, reject) => {
                const img = new Image();
                img.onload = () => {
                    URL.revokeObjectURL(objectUrl);
                    resolve(img);
                };
                img.onerror = () => {
                    URL.revokeObjectURL(objectUrl);
                    reject(new Error('Failed to load image from blob'));
                };
                img.src = objectUrl;
            });
        }

        /**
         * Calculate histogram from image data.
         */
        _calculateHistogram(data) {
            const histogram = new Array(256).fill(0);
            const sampleStep = 4;

            for (let i = 0; i < data.length; i += 4 * sampleStep) {
                const r = data[i];
                const g = data[i + 1];
                const b = data[i + 2];
                const gray = Math.round(0.299 * r + 0.587 * g + 0.114 * b);
                histogram[gray]++;
            }

            return histogram;
        }

        /**
         * Analyze histogram and calculate optimal adjustments.
         */
        _analyzeHistogram(histogram) {
            const total = histogram.reduce((a, b) => a + b, 0);
            const percentile5 = total * 0.05;
            const percentile95 = total * 0.95;

            let cumulative = 0;
            let minVal = 0;
            let maxVal = 255;

            for (let i = 0; i < 256; i++) {
                cumulative += histogram[i];
                if (cumulative >= percentile5 && minVal === 0) {
                    minVal = i;
                }
                if (cumulative >= percentile95) {
                    maxVal = i;
                    break;
                }
            }

            // Calculate mean brightness
            let sum = 0;
            let count = 0;
            for (let i = 0; i < 256; i++) {
                sum += i * histogram[i];
                count += histogram[i];
            }
            const mean = sum / count;

            // Calculate optimal contrast
            const range = maxVal - minVal;
            let contrast = 100;
            if (range > 0 && range < 200) {
                contrast = Math.round(Math.min(200, (200 / range) * 100));
            }

            // Calculate optimal brightness
            let brightness = 100;
            if (mean < 100) {
                brightness = Math.round(Math.min(180, 100 + (128 - mean) * 0.5));
            } else if (mean > 160) {
                brightness = Math.round(Math.max(60, 100 - (mean - 128) * 0.5));
            }

            // Clamp values
            brightness = Math.max(50, Math.min(200, brightness));
            contrast = Math.max(80, Math.min(200, contrast));

            return { brightness, contrast };
        }

        // =====================================================================
        // Getters
        // =====================================================================

        /**
         * Get current adjustments.
         */
        getAdjustments() {
            return { ...this.adjustments };
        }

        /**
         * Check if panel is visible.
         * @returns {boolean}
         */
        isVisible() {
            return this._isVisible;
        }
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.AdjustmentsPanel = AdjustmentsPanel;

})(window);
