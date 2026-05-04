/**
 * SelectTool - Selection Tool for GelViewer
 *
 * Handles annotation selection via click events.
 * Note: Actual selection is handled by SVG element click events
 * set up in the Renderer. This tool mainly indicates selection mode.
 */

(function(global) {
    'use strict';

    /**
     * SelectTool Class
     */
    class SelectTool {
        constructor(options) {
            this.eventBus = options.eventBus;
        }

        activate() {
            // Selection mode is passive - clicks on SVG elements trigger selection
        }

        deactivate() {
            // Nothing to clean up
        }

        onMouseDown(point, e) {
            // Click on empty space - handled by orchestrator to deselect
            return false; // Indicate not handled
        }

        onMouseMove(point, e) {
            // No action in select mode
        }

        onMouseUp(point, e) {
            // No action in select mode
        }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.SelectTool = SelectTool;

})(window);
