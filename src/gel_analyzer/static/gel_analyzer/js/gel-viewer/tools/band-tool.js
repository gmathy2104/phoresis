/**
 * BandTool - Band Drawing Tool for GelViewer
 *
 * Handles band annotation drawing as polygons within lanes.
 * Click to add points, double-click to finish.
 */

(function(global) {
    'use strict';

    /**
     * BandTool Class
     */
    class BandTool {
        /**
         * @param {Object} options
         * @param {Object} options.svg - SVG.js instance
         * @param {Object} options.drawingGroup - SVG group for drawing previews
         * @param {EventBus} options.eventBus - EventBus instance
         * @param {StateManager} options.stateManager - StateManager instance
         * @param {Function} options.onBandCreated - Callback(laneId, bandData)
         * @param {Function} options.findLaneAtPoint - Function to find lane at point
         * @param {Function} options.showMessage - Function to display messages
         */
        constructor(options) {
            this.svg = options.svg;
            this.drawingGroup = options.drawingGroup;
            this.eventBus = options.eventBus;
            this.stateManager = options.stateManager;
            this.onBandCreated = options.onBandCreated;
            this.findLaneAtPoint = options.findLaneAtPoint;
            this.showMessage = options.showMessage || console.log;
            this.getScale = options.getScale || (() => 1);

            // Drawing state
            this.points = [];
            this.previewPoint = null;

            // Base sizes (will be scaled)
            this.basePointRadius = 6;
            this.baseStrokeWidth = 2;
        }

        activate() {
            this.cancel();
        }

        deactivate() {
            this.cancel();
        }

        cancel() {
            this.points = [];
            this.previewPoint = null;

            if (this.drawingGroup) {
                this.drawingGroup.clear();
            }
        }

        addPoint(point) {
            this.points.push([point.x, point.y]);
            this._updatePreview();
        }

        updatePreview(point) {
            this.previewPoint = [point.x, point.y];
            this._updatePreview();
        }

        _updatePreview() {
            if (this.points.length === 0) return;

            this.drawingGroup.clear();

            // Get scale-adjusted sizes
            const scale = this.getScale();
            const pointRadius = this.basePointRadius / scale;
            const strokeWidth = this.baseStrokeWidth / scale;

            // Build points array
            const allPoints = [...this.points];
            if (this.previewPoint) {
                allPoints.push(this.previewPoint);
            }

            // Draw preview polygon with scaled stroke
            if (allPoints.length >= 2) {
                this.drawingGroup.polygon(allPoints)
                    .addClass('gv-drawing-preview')
                    .stroke({ width: strokeWidth });
            }

            // Draw points with scaled radius
            allPoints.forEach((p, i) => {
                const isPreview = i === allPoints.length - 1 && this.previewPoint;
                this.drawingGroup.circle(pointRadius * 2)
                    .center(p[0], p[1])
                    .addClass(isPreview ? 'gv-drawing-point-preview' : 'gv-drawing-point');
            });
        }

        finish() {
            if (this.points.length < 3) {
                this.showMessage('Band requires at least 3 points.');
                this.cancel();
                return null;
            }

            // Calculate bounding box
            const xs = this.points.map(p => p[0]);
            const ys = this.points.map(p => p[1]);
            const bbox = {
                x: Math.min(...xs),
                y: Math.min(...ys),
                width: Math.max(...xs) - Math.min(...xs),
                height: Math.max(...ys) - Math.min(...ys)
            };

            // Find parent lane
            const centerX = (bbox.x + bbox.width / 2);
            const centerY = (bbox.y + bbox.height / 2);
            const laneId = this.findLaneAtPoint ? this.findLaneAtPoint(centerX, centerY) : null;

            if (!laneId) {
                this.showMessage('Bands must be drawn within a lane.');
                this.cancel();
                return null;
            }

            const bandData = {
                position_y: Math.round(centerY),
                polygon: this.points.map(p => [Math.round(p[0]), Math.round(p[1])]),
                bbox_x: Math.round(bbox.x),
                bbox_y: Math.round(bbox.y),
                bbox_width: Math.round(bbox.width),
                bbox_height: Math.round(bbox.height)
            };

            this.cancel();

            return { laneId, bandData };
        }

        // Event handlers
        onMouseDown(point, e) {
            this.addPoint(point);
            return true;
        }

        onMouseMove(point, e) {
            if (this.points.length > 0) {
                this.updatePreview(point);
            }
        }

        onMouseUp(point, e) {
            // Nothing specific on mouse up
        }

        onDoubleClick(point, e) {
            const result = this.finish();
            if (result && this.onBandCreated) {
                this.onBandCreated(result.laneId, result.bandData);
            }
        }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.BandTool = BandTool;

})(window);
