/**
 * LaneTool - Lane Drawing Tool for GelViewer
 *
 * Handles lane annotation drawing in three modes:
 * - Rectangle: Click and drag
 * - Quadrilateral: Click 4 points
 * - Polygon: Click N points, double-click to finish
 *
 * TODO: This is a stub - core drawing logic is in the main orchestrator.
 * Full extraction requires access to SVG drawing groups and state management.
 */

(function(global) {
    'use strict';

    /**
     * LaneTool Class (Stub)
     */
    class LaneTool {
        /**
         * @param {Object} options
         * @param {Object} options.svg - SVG.js instance
         * @param {Object} options.drawingGroup - SVG group for drawing previews
         * @param {EventBus} options.eventBus - EventBus instance
         * @param {StateManager} options.stateManager - StateManager instance
         * @param {ToolManager} options.toolManager - ToolManager instance
         * @param {Function} options.onLaneCreated - Callback when lane is created
         * @param {Function} options.showMessage - Function to display messages
         */
        constructor(options) {
            this.svg = options.svg;
            this.drawingGroup = options.drawingGroup;
            this.eventBus = options.eventBus;
            this.stateManager = options.stateManager;
            this.toolManager = options.toolManager;
            this.onLaneCreated = options.onLaneCreated;
            this.showMessage = options.showMessage || console.log;
            this.getScale = options.getScale || (() => 1);

            // Drawing state
            this.isDrawing = false;
            this.drawingStart = null;
            this.drawingElement = null;
            this.shapePoints = [];
            this.shapePreviewPoints = null;

            // Base sizes (will be scaled)
            this.basePointRadius = 8;
            this.baseStrokeWidth = 2;
        }

        activate() {
            this.cancel();
        }

        deactivate() {
            this.cancel();
        }

        cancel() {
            this.isDrawing = false;
            this.drawingStart = null;
            this.shapePoints = [];
            this.shapePreviewPoints = null;

            if (this.drawingElement) {
                this.drawingElement.remove();
                this.drawingElement = null;
            }

            if (this.drawingGroup) {
                this.drawingGroup.clear();
            }
        }

        getShape() {
            return this.toolManager ? this.toolManager.getLaneShape() : 'RECTANGLE';
        }

        // Rectangle drawing methods
        startRectangle(point) {
            this.isDrawing = true;
            this.drawingStart = point;

            const scale = this.getScale();
            const strokeWidth = this.baseStrokeWidth / scale;

            this.drawingElement = this.drawingGroup.rect(0, 0)
                .move(point.x, point.y)
                .addClass('gv-drawing-preview')
                .stroke({ width: strokeWidth });
        }

        updateRectangle(point) {
            if (!this.drawingElement) return;

            const x = Math.min(this.drawingStart.x, point.x);
            const y = Math.min(this.drawingStart.y, point.y);
            const width = Math.abs(point.x - this.drawingStart.x);
            const height = Math.abs(point.y - this.drawingStart.y);

            this.drawingElement.move(x, y).size(width, height);
        }

        finishRectangle() {
            if (!this.drawingElement) return null;

            const bbox = this.drawingElement.bbox();

            // Minimum size check
            if (bbox.width < 10 || bbox.height < 10) {
                this.cancel();
                this.showMessage('Lane too small. Draw a larger rectangle.');
                return null;
            }

            const data = {
                lane_shape: 'RECTANGLE',
                x: Math.round(bbox.x),
                y: Math.round(bbox.y),
                width: Math.round(bbox.width),
                height: Math.round(bbox.height)
            };

            this.cancel();
            return data;
        }

        // Quad/Polygon point-based drawing
        addPoint(point) {
            const shape = this.getShape();
            this.shapePoints.push([point.x, point.y]);

            this._updatePreview();

            // Auto-finish quadrilateral at 4 points
            if (shape === 'QUADRILATERAL' && this.shapePoints.length === 4) {
                return this.finishPolygon();
            }

            return null;
        }

        updatePreview(point) {
            this.shapePreviewPoints = [point.x, point.y];
            this._updatePreview();
        }

        _updatePreview() {
            if (this.shapePoints.length === 0) return;

            this.drawingGroup.clear();

            // Get scale-adjusted sizes
            const scale = this.getScale();
            const pointRadius = this.basePointRadius / scale;
            const strokeWidth = this.baseStrokeWidth / scale;

            // Build points array for preview
            const points = [...this.shapePoints];
            if (this.shapePreviewPoints) {
                points.push(this.shapePreviewPoints);
            }

            // Draw preview polygon with scaled stroke
            if (points.length >= 2) {
                this.drawingGroup.polygon(points)
                    .addClass('gv-drawing-preview')
                    .stroke({ width: strokeWidth });
            }

            // Draw points with scaled radius
            points.forEach((p, i) => {
                const isPreview = i === points.length - 1 && this.shapePreviewPoints;
                this.drawingGroup.circle(pointRadius * 2)
                    .center(p[0], p[1])
                    .addClass(isPreview ? 'gv-drawing-point-preview' : 'gv-drawing-point');
            });
        }

        finishPolygon() {
            const shape = this.getShape();
            const minPoints = shape === 'QUADRILATERAL' ? 4 : 3;

            if (this.shapePoints.length < minPoints) {
                this.showMessage(`${shape} requires at least ${minPoints} points.`);
                return null;
            }

            // Calculate bounding box
            const xs = this.shapePoints.map(p => p[0]);
            const ys = this.shapePoints.map(p => p[1]);
            const bbox = {
                x: Math.min(...xs),
                y: Math.min(...ys),
                width: Math.max(...xs) - Math.min(...xs),
                height: Math.max(...ys) - Math.min(...ys)
            };

            if (bbox.width < 10 || bbox.height < 10) {
                this.cancel();
                this.showMessage('Lane too small.');
                return null;
            }

            const data = {
                lane_shape: shape,
                x: Math.round(bbox.x),
                y: Math.round(bbox.y),
                width: Math.round(bbox.width),
                height: Math.round(bbox.height),
                polygon: this.shapePoints.map(p => [Math.round(p[0]), Math.round(p[1])])
            };

            this.cancel();
            return data;
        }

        // Main event handlers (called by orchestrator)
        onMouseDown(point, e) {
            const shape = this.getShape();

            if (shape === 'RECTANGLE') {
                this.startRectangle(point);
                return true;
            } else {
                const result = this.addPoint(point);
                if (result && this.onLaneCreated) {
                    this.onLaneCreated(result);
                }
                return true;
            }
        }

        onMouseMove(point, e) {
            const shape = this.getShape();

            if (shape === 'RECTANGLE' && this.isDrawing) {
                this.updateRectangle(point);
            } else if (this.shapePoints.length > 0) {
                this.updatePreview(point);
            }
        }

        onMouseUp(point, e) {
            const shape = this.getShape();

            if (shape === 'RECTANGLE' && this.isDrawing) {
                const result = this.finishRectangle();
                if (result && this.onLaneCreated) {
                    this.onLaneCreated(result);
                }
            }
        }

        onDoubleClick(point, e) {
            const shape = this.getShape();

            if (shape === 'POLYGON' && this.shapePoints.length >= 3) {
                const result = this.finishPolygon();
                if (result && this.onLaneCreated) {
                    this.onLaneCreated(result);
                }
            }
        }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.LaneTool = LaneTool;

})(window);
