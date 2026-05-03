/**
 * Comparison Report Capture Module
 *
 * All report visuals (electropherograms, gel images, digital gel, per-lane views)
 * are rendered server-side with Pillow/matplotlib. This module is kept as a no-op
 * shell so the report generation caller doesn't break.
 */

(function(global) {
    'use strict';

    class ComparisonReportCapture {
        constructor(app, options = {}) {
            this.app = app;
        }

        /**
         * All captures are now server-side. Returns empty result immediately.
         * @returns {Promise<Object>}
         */
        async captureAll() {
            console.log('[ComparisonReportCapture] All visuals rendered server-side, no client captures needed');
            return { gel_images: {}, lanes: {} };
        }
    }

    // Export
    global.Densitometry = global.Densitometry || {};
    global.Densitometry.ComparisonReportCapture = ComparisonReportCapture;

})(window);
