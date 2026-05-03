/**
 * CropTool - Image Crop Tool for GelViewer
 *
 * Lets the user draw a crop rectangle over the gel image.
 * Displays a dim overlay (SVG path with evenodd fill-rule)
 * to show the region that will be discarded.
 *
 * Emits CROP_REQUESTED via the EventBus with {x, y, width, height}.
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    // Minimum crop size in display pixels
    const MIN_CROP_SIZE = 50;

    class CropTool {
        /**
         * @param {Object} options
         * @param {Object} options.svg - SVG.js instance
         * @param {Object} options.drawingGroup - SVG group for drawing previews
         * @param {EventBus} options.eventBus - EventBus instance
         * @param {number} options.imageWidth - Image width in display pixels
         * @param {number} options.imageHeight - Image height in display pixels
         * @param {Function} options.showMessage - Function to display messages
         * @param {Function} options.getScale - Function returning current viewport scale
         */
        constructor(options) {
            this.svg = options.svg;
            this.drawingGroup = options.drawingGroup;
            this.eventBus = options.eventBus;
            this.imageWidth = options.imageWidth;
            this.imageHeight = options.imageHeight;
            this.showMessage = options.showMessage || console.log;
            this.getScale = options.getScale || (() => 1);

            // Drawing state
            this.isDrawing = false;
            this.startPoint = null;
            this.overlayPath = null;
            this.cropRect = null;
        }

        activate() {
            this.cancel();
            this.showMessage('Crop: Click and drag to select region');
        }

        deactivate() {
            this.cancel();
        }

        cancel() {
            this.isDrawing = false;
            this.startPoint = null;
            if (this.overlayPath) {
                this.overlayPath.remove();
                this.overlayPath = null;
            }
            if (this.cropRect) {
                this.cropRect.remove();
                this.cropRect = null;
            }
            if (this.drawingGroup) {
                this.drawingGroup.clear();
            }
        }

        /**
         * Handle mouse down — start drawing crop rectangle.
         */
        onMouseDown(point) {
            this.cancel();
            this.isDrawing = true;
            this.startPoint = { x: point.x, y: point.y };
        }

        /**
         * Handle mouse move — update crop rectangle and overlay.
         */
        onMouseMove(point) {
            if (!this.isDrawing || !this.startPoint) return;

            const rect = this._calcRect(this.startPoint, point);
            if (rect.width < 2 || rect.height < 2) return;

            this._renderOverlay(rect);
            this._renderCropRect(rect);
        }

        /**
         * Handle mouse up — finalize crop rectangle.
         */
        onMouseUp(point) {
            if (!this.isDrawing || !this.startPoint) return;
            this.isDrawing = false;

            const rect = this._calcRect(this.startPoint, point);

            // Minimum size check
            if (rect.width < MIN_CROP_SIZE || rect.height < MIN_CROP_SIZE) {
                this.showMessage(`Crop area too small (minimum ${MIN_CROP_SIZE}x${MIN_CROP_SIZE}px)`);
                this.cancel();
                return;
            }

            // Emit crop request with rounded integer coordinates
            const cropData = {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height)
            };

            this.eventBus.emit(Events.CROP_REQUESTED, cropData);
        }

        // =====================================================================
        // Private helpers
        // =====================================================================

        /**
         * Calculate rectangle from two corner points, clamped to image bounds.
         */
        _calcRect(p1, p2) {
            let x = Math.min(p1.x, p2.x);
            let y = Math.min(p1.y, p2.y);
            let x2 = Math.max(p1.x, p2.x);
            let y2 = Math.max(p1.y, p2.y);

            // Clamp to image bounds
            x = Math.max(0, x);
            y = Math.max(0, y);
            x2 = Math.min(this.imageWidth, x2);
            y2 = Math.min(this.imageHeight, y2);

            return { x, y, width: x2 - x, height: y2 - y };
        }

        /**
         * Render dim overlay with cutout for the crop area.
         * Uses a single SVG <path> with fill-rule: evenodd.
         */
        _renderOverlay(rect) {
            const W = this.imageWidth;
            const H = this.imageHeight;
            const { x, y, width, height } = rect;

            // Outer rect (clockwise) + inner rect (counter-clockwise) = evenodd hole
            const d = [
                `M 0 0 L ${W} 0 L ${W} ${H} L 0 ${H} Z`,
                `M ${x} ${y} L ${x} ${y + height} L ${x + width} ${y + height} L ${x + width} ${y} Z`
            ].join(' ');

            if (this.overlayPath) {
                this.overlayPath.plot(d);
            } else {
                this.overlayPath = this.drawingGroup.path(d)
                    .fill('rgba(0, 0, 0, 0.5)')
                    .attr('fill-rule', 'evenodd')
                    .addClass('gv-crop-overlay')
                    .attr('pointer-events', 'none');
            }
        }

        /**
         * Render the dashed crop rectangle border.
         */
        _renderCropRect(rect) {
            const scale = this.getScale();
            const strokeWidth = 2 / scale;
            const dashArray = `${6 / scale},${3 / scale}`;

            if (this.cropRect) {
                this.cropRect
                    .move(rect.x, rect.y)
                    .size(rect.width, rect.height)
                    .stroke({ width: strokeWidth, dasharray: dashArray });
            } else {
                this.cropRect = this.drawingGroup.rect(rect.width, rect.height)
                    .move(rect.x, rect.y)
                    .fill('none')
                    .stroke({ color: '#ffffff', width: strokeWidth, dasharray: dashArray })
                    .addClass('gv-crop-rect')
                    .attr('pointer-events', 'none');
            }
        }
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.CropTool = CropTool;

})(window);
