/**
 * PanTool - Pan Navigation Tool for GelViewer
 *
 * Handles viewport panning via click and drag.
 * Delegates to Viewport for actual pan operations.
 */

(function(global) {
    'use strict';

    /**
     * PanTool Class
     */
    class PanTool {
        /**
         * @param {Object} options
         * @param {Viewport} options.viewport - Viewport instance
         * @param {EventBus} options.eventBus - EventBus instance
         */
        constructor(options) {
            this.viewport = options.viewport;
            this.eventBus = options.eventBus;
        }

        activate() {
            // Pan mode activated
        }

        deactivate() {
            this.viewport.endPan();
        }

        onMouseDown(point, e) {
            this.viewport.startPan(e);
            return true;
        }

        onMouseMove(point, e) {
            this.viewport.updatePan(e);
        }

        onMouseUp(point, e) {
            this.viewport.endPan();
        }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.PanTool = PanTool;

})(window);
