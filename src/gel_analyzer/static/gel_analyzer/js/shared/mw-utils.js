/**
 * MW Utilities - Molecular Weight Conversion and Normalization (Shared)
 *
 * Provides utilities for:
 * - Converting Y positions to MW using calibration data
 * - Normalizing intensity profiles
 * - Band matching across samples
 *
 * Namespace: GelAnalyzer.MWUtils, GelAnalyzer.NormalizationUtils,
 *            GelAnalyzer.BandMatchingUtils, GelAnalyzer.CalibrationMethods,
 *            GelAnalyzer.NormalizationModes
 */

(function(global) {
    'use strict';

    /**
     * CalibrationMethods enum matches backend CalibrationMethod.
     */
    const CalibrationMethods = {
        LOG_LINEAR: 'LOG_LINEAR',
        POLYNOMIAL_2: 'POLYNOMIAL_2',
        POLYNOMIAL_3: 'POLYNOMIAL_3',
    };

    /**
     * NormalizationModes enum.
     */
    const NormalizationModes = {
        RAW: 'raw',
        TOTAL: 'total',      // Normalize by total lane intensity (sum = 100%)
        MAX_PEAK: 'max_peak', // Normalize by max peak (max = 100%)
        REFERENCE: 'reference', // Normalize by reference band
    };

    /**
     * MWUtils class - static utility methods for MW calculations.
     */
    class MWUtils {
        /**
         * Calculate relative migration (Rf) from Y position.
         * Rf = 0 at well (lane top), Rf = 1 at dye front (lane bottom)
         *
         * @param {number} positionY - Y position in pixels
         * @param {number} laneTop - Y position of lane top (well)
         * @param {number} laneBottom - Y position of lane bottom (dye front)
         * @returns {number} Rf value (0-1)
         */
        static calculateRf(positionY, laneTop, laneBottom) {
            if (laneBottom <= laneTop) return 0;
            const rf = (positionY - laneTop) / (laneBottom - laneTop);
            return Math.max(0, Math.min(1, rf));
        }

        /**
         * Estimate MW from Rf using calibration coefficients.
         *
         * @param {number} rf - Relative migration (0-1)
         * @param {Object} calibration - Calibration data with method and coefficients
         * @returns {number|null} Estimated MW in kDa, or null if calculation fails
         */
        static estimateMW(rf, calibration) {
            if (!calibration || !calibration.coefficients) return null;

            try {
                const { method, coefficients } = calibration;

                if (method === CalibrationMethods.LOG_LINEAR) {
                    const slope = coefficients.slope || 0;
                    const intercept = coefficients.intercept || 0;
                    const logMW = slope * rf + intercept;
                    return Math.pow(10, logMW);
                }

                if (method === CalibrationMethods.POLYNOMIAL_2 ||
                    method === CalibrationMethods.POLYNOMIAL_3) {
                    const coeffs = coefficients.coeffs || [];
                    if (coeffs.length === 0) return null;

                    // Evaluate polynomial: coeffs[0]*x^n + coeffs[1]*x^(n-1) + ... + coeffs[n]
                    let logMW = 0;
                    for (let i = 0; i < coeffs.length; i++) {
                        const power = coeffs.length - 1 - i;
                        logMW += coeffs[i] * Math.pow(rf, power);
                    }
                    return Math.pow(10, logMW);
                }
            } catch (e) {
                console.warn('[MWUtils] estimateMW error:', e);
            }

            return null;
        }

        /**
         * Convert Y position to MW using calibration.
         *
         * @param {number} positionY - Y position in pixels
         * @param {Object} laneGeometry - Lane geometry { top, bottom }
         * @param {Object} calibration - Calibration data
         * @returns {number|null} Estimated MW in kDa
         */
        static positionToMW(positionY, laneGeometry, calibration) {
            if (!laneGeometry || !calibration) return null;
            const rf = this.calculateRf(positionY, laneGeometry.top, laneGeometry.bottom);
            return this.estimateMW(rf, calibration);
        }

        /**
         * Convert MW to Rf using calibration (inverse function).
         * Only supports LOG_LINEAR calibration.
         *
         * @param {number} mw - Molecular weight in kDa
         * @param {Object} calibration - Calibration data
         * @returns {number|null} Rf value (0-1), or null if not calculable
         */
        static mwToRf(mw, calibration) {
            if (!calibration || !calibration.coefficients) return null;
            if (mw <= 0) return null;

            try {
                const { method, coefficients } = calibration;

                if (method === CalibrationMethods.LOG_LINEAR) {
                    const slope = coefficients.slope || 0;
                    const intercept = coefficients.intercept || 0;
                    if (slope === 0) return null;
                    const logMW = Math.log10(mw);
                    return (logMW - intercept) / slope;
                }

                // For polynomial calibrations, would need numerical methods (bisection/Newton)
                // Not implemented for simplicity
            } catch (e) {
                console.warn('[MWUtils] mwToRf error:', e);
            }

            return null;
        }

        /**
         * Convert profile Y positions to MW values.
         *
         * @param {Array<number>} yPositions - Array of Y positions
         * @param {Object} laneGeometry - Lane geometry { top, bottom }
         * @param {Object} calibration - Calibration data
         * @returns {Array<number|null>} Array of MW values
         */
        static convertProfileToMW(yPositions, laneGeometry, calibration) {
            if (!yPositions || !laneGeometry || !calibration) return [];
            return yPositions.map(y => this.positionToMW(y, laneGeometry, calibration));
        }

        /**
         * Get common MW range across multiple samples.
         *
         * @param {Array<Object>} samples - Array of sample data with calibration
         * @returns {Object} { minMW, maxMW } common range
         */
        static getCommonMWRange(samples) {
            let minMW = Infinity;
            let maxMW = 0;

            samples.forEach(sample => {
                if (sample.calibration?.mw_range) {
                    const range = sample.calibration.mw_range;
                    if (range.min && range.min < minMW) minMW = range.min;
                    if (range.max && range.max > maxMW) maxMW = range.max;
                }

                // Also check band MW values
                if (sample.bands) {
                    sample.bands.forEach(band => {
                        if (band.estimated_mw_kda) {
                            if (band.estimated_mw_kda < minMW) minMW = band.estimated_mw_kda;
                            if (band.estimated_mw_kda > maxMW) maxMW = band.estimated_mw_kda;
                        }
                    });
                }
            });

            // Default range if nothing found
            if (minMW === Infinity) minMW = 10;
            if (maxMW === 0) maxMW = 250;

            return { minMW, maxMW };
        }
    }

    /**
     * Normalization utilities for intensity profiles.
     */
    class NormalizationUtils {
        /**
         * Normalize intensities based on mode.
         *
         * @param {Array<number>} intensities - Raw intensity values
         * @param {string} mode - Normalization mode
         * @param {Object} options - Additional options (e.g., referenceValue)
         * @returns {Array<number>} Normalized intensities
         */
        static normalizeProfile(intensities, mode, options = {}) {
            if (!intensities || intensities.length === 0) return [];

            switch (mode) {
                case NormalizationModes.TOTAL:
                    return this._normalizeByTotal(intensities);

                case NormalizationModes.MAX_PEAK:
                    return this._normalizeByMax(intensities);

                case NormalizationModes.REFERENCE:
                    return this._normalizeByReference(intensities, options.referenceValue);

                case NormalizationModes.RAW:
                default:
                    return intensities;
            }
        }

        /**
         * Normalize by total (sum = 100%).
         * @private
         */
        static _normalizeByTotal(intensities) {
            const sum = intensities.reduce((a, b) => a + b, 0);
            if (sum === 0) return intensities.map(() => 0);
            return intensities.map(i => (i / sum) * 100);
        }

        /**
         * Normalize by max peak (max = 100%).
         * @private
         */
        static _normalizeByMax(intensities) {
            const max = Math.max(...intensities);
            if (max === 0) return intensities.map(() => 0);
            return intensities.map(i => (i / max) * 100);
        }

        /**
         * Normalize by reference value.
         * @private
         */
        static _normalizeByReference(intensities, referenceValue) {
            if (!referenceValue || referenceValue === 0) {
                return intensities;
            }
            return intensities.map(i => (i / referenceValue) * 100);
        }

        /**
         * Get reference intensity for a band.
         *
         * @param {Object} band - Band data with densitometry
         * @returns {number|null} Reference intensity value
         */
        static getBandReferenceValue(band) {
            if (band?.densitometry?.corrected_area) {
                return band.densitometry.corrected_area;
            }
            if (band?.densitometry?.peak_amplitude) {
                return band.densitometry.peak_amplitude;
            }
            return null;
        }
    }

    /**
     * Band matching utilities for cross-sample comparison.
     */
    class BandMatchingUtils {
        /**
         * Match bands across samples by MW within tolerance.
         *
         * @param {Array<Object>} samples - Array of sample data
         * @param {number} tolerancePct - MW tolerance percentage (e.g., 5 for ±5%)
         * @returns {Array<Object>} Array of matched band groups
         */
        static matchBandsByMW(samples, tolerancePct = 5) {
            const allBands = [];
            samples.forEach(sample => {
                if (sample.bands) {
                    sample.bands.forEach(band => {
                        if (band.estimated_mw_kda) {
                            allBands.push({
                                ...band,
                                sampleId: sample.sampleId,
                                sampleName: sample.label,
                                sampleColor: sample.color,
                            });
                        }
                    });
                }
            });

            allBands.sort((a, b) => b.estimated_mw_kda - a.estimated_mw_kda);

            const matched = [];
            const used = new Set();

            allBands.forEach(band => {
                if (used.has(band.id)) return;

                const group = {
                    mw: band.estimated_mw_kda,
                    bands: [band],
                };

                allBands.forEach(other => {
                    if (other.id === band.id || used.has(other.id)) return;

                    const pctDiff = Math.abs(other.estimated_mw_kda - band.estimated_mw_kda)
                        / band.estimated_mw_kda * 100;

                    if (pctDiff <= tolerancePct) {
                        group.bands.push(other);
                    }
                });

                group.bands.forEach(b => used.add(b.id));

                group.mw = group.bands.reduce((sum, b) => sum + b.estimated_mw_kda, 0)
                    / group.bands.length;

                if (group.bands.length > 1) {
                    const mwValues = group.bands.map(b => b.estimated_mw_kda);
                    const minMW = Math.min(...mwValues);
                    const maxMW = Math.max(...mwValues);
                    group.mwDiffPct = ((maxMW - minMW) / minMW) * 100;
                } else {
                    group.mwDiffPct = 0;
                }

                matched.push(group);
            });

            return matched;
        }

        /**
         * Calculate profile correlation (Pearson) between two samples.
         *
         * @param {Array<number>} intensities1 - First profile intensities
         * @param {Array<number>} intensities2 - Second profile intensities
         * @returns {number} Pearson correlation coefficient (-1 to 1)
         */
        static calculateCorrelation(intensities1, intensities2) {
            if (!intensities1 || !intensities2) return null;
            if (intensities1.length !== intensities2.length) return null;

            const n = intensities1.length;
            if (n === 0) return null;

            const mean1 = intensities1.reduce((a, b) => a + b, 0) / n;
            const mean2 = intensities2.reduce((a, b) => a + b, 0) / n;

            let cov = 0;
            let var1 = 0;
            let var2 = 0;

            for (let i = 0; i < n; i++) {
                const d1 = intensities1[i] - mean1;
                const d2 = intensities2[i] - mean2;
                cov += d1 * d2;
                var1 += d1 * d1;
                var2 += d2 * d2;
            }

            const std1 = Math.sqrt(var1);
            const std2 = Math.sqrt(var2);

            if (std1 === 0 || std2 === 0) return null;

            return cov / (std1 * std2);
        }

        /**
         * Interpolate profile to common MW grid for comparison.
         *
         * @param {Array<number>} mwValues - Original MW values
         * @param {Array<number>} intensities - Original intensities
         * @param {Array<number>} targetMWGrid - Target MW grid
         * @returns {Array<number>} Interpolated intensities
         */
        static interpolateToMWGrid(mwValues, intensities, targetMWGrid) {
            if (!mwValues || !intensities || !targetMWGrid) return [];

            const validData = [];
            for (let i = 0; i < mwValues.length; i++) {
                if (mwValues[i] !== null && intensities[i] !== null) {
                    validData.push({ mw: mwValues[i], intensity: intensities[i] });
                }
            }

            if (validData.length < 2) return targetMWGrid.map(() => 0);

            validData.sort((a, b) => a.mw - b.mw);

            return targetMWGrid.map(targetMW => {
                let lower = null;
                let upper = null;

                for (let i = 0; i < validData.length - 1; i++) {
                    if (validData[i].mw <= targetMW && validData[i + 1].mw >= targetMW) {
                        lower = validData[i];
                        upper = validData[i + 1];
                        break;
                    }
                }

                if (!lower || !upper) {
                    if (targetMW <= validData[0].mw) return validData[0].intensity;
                    if (targetMW >= validData[validData.length - 1].mw) {
                        return validData[validData.length - 1].intensity;
                    }
                    return 0;
                }

                const t = (targetMW - lower.mw) / (upper.mw - lower.mw);
                return lower.intensity + t * (upper.intensity - lower.intensity);
            });
        }
    }

    // Export to shared namespace
    global.GelAnalyzer = global.GelAnalyzer || {};
    global.GelAnalyzer.MWUtils = MWUtils;
    global.GelAnalyzer.NormalizationUtils = NormalizationUtils;
    global.GelAnalyzer.BandMatchingUtils = BandMatchingUtils;
    global.GelAnalyzer.CalibrationMethods = CalibrationMethods;
    global.GelAnalyzer.NormalizationModes = NormalizationModes;

})(window);
