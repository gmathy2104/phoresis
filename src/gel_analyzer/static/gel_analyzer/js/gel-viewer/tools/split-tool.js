/**
 * SplitTool - Band Splitting Tool for GelViewer
 *
 * Allows splitting bands horizontally by drawing a line across them.
 * Creates two new bands from the original.
 *
 * TODO: Complex tool - full extraction requires significant refactoring.
 */

(function(global) {
    'use strict';

    /**
     * SplitTool Class (Stub)
     */
    class SplitTool {
        /**
         * @param {Object} options
         * @param {Object} options.svg - SVG.js instance
         * @param {Object} options.drawingGroup - SVG group for preview line
         * @param {EventBus} options.eventBus - EventBus instance
         * @param {StateManager} options.stateManager - StateManager instance
         * @param {Function} options.onBandSplit - Callback(bandId, splitY)
         * @param {Function} options.getBandAtPoint - Function to find band at point
         * @param {Function} options.showMessage - Function to display messages
         */
        constructor(options) {
            this.svg = options.svg;
            this.drawingGroup = options.drawingGroup;
            this.eventBus = options.eventBus;
            this.stateManager = options.stateManager;
            this.onBandSplit = options.onBandSplit;
            this.getBandAtPoint = options.getBandAtPoint;
            this.showMessage = options.showMessage || console.log;
            this.getScale = options.getScale || (() => 1);

            // State
            this.startPoint = null;
            this.previewLine = null;
            this.selectedBand = null;

            // Base size (will be scaled)
            this.baseStrokeWidth = 2;
        }

        activate() {
            this.cancel();
            this.showMessage('Click on a band to split it horizontally');
        }

        deactivate() {
            this.cancel();
        }

        cancel() {
            this.startPoint = null;
            this.selectedBand = null;

            if (this.previewLine) {
                this.previewLine.remove();
                this.previewLine = null;
            }
        }

        // Event handlers
        onMouseDown(point, e) {
            // Find band at click point
            if (this.getBandAtPoint) {
                const band = this.getBandAtPoint(point.x, point.y);
                if (band) {
                    this.selectedBand = band;
                    this.startPoint = point;

                    // Get scale-adjusted stroke width
                    const scale = this.getScale();
                    const strokeWidth = this.baseStrokeWidth / scale;

                    // Create preview line with scaled stroke
                    this.previewLine = this.drawingGroup.line(
                        band.bbox_x, point.y,
                        band.bbox_x + band.bbox_width, point.y
                    ).addClass('gv-split-preview')
                     .stroke({ width: strokeWidth });

                    return true;
                }
            }

            this.showMessage('Click on a band to split it');
            return false;
        }

        onMouseMove(point, e) {
            if (this.previewLine && this.selectedBand) {
                // Update preview line position
                const band = this.selectedBand;
                this.previewLine.plot(
                    band.bbox_x, point.y,
                    band.bbox_x + band.bbox_width, point.y
                );
            }
        }

        onMouseUp(point, e) {
            if (this.selectedBand && this.startPoint) {
                const band = this.selectedBand;

                // Check if split point is within band
                if (point.y > band.bbox_y && point.y < band.bbox_y + band.bbox_height) {
                    if (this.onBandSplit) {
                        this.onBandSplit(band.id, point.y);
                    }
                } else {
                    this.showMessage('Split point must be within the band');
                }

                this.cancel();
            }
        }

        onDoubleClick(point, e) {
            // Not used for split tool
        }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.SplitTool = SplitTool;

})(window);
