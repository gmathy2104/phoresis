/**
 * MW Utilities - Backward Compatibility Shim
 *
 * Re-exports from shared/mw-utils.js under the SampleComparison namespace.
 * New code should use GelAnalyzer.MWUtils etc. directly.
 */

(function(global) {
    'use strict';

    const GA = global.GelAnalyzer || {};

    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.MWUtils = GA.MWUtils;
    global.SampleComparison.NormalizationUtils = GA.NormalizationUtils;
    global.SampleComparison.BandMatchingUtils = GA.BandMatchingUtils;
    global.SampleComparison.CalibrationMethods = GA.CalibrationMethods;
    global.SampleComparison.NormalizationModes = GA.NormalizationModes;

})(window);
