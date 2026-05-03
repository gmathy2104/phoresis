/**
 * Comparison Metrics - Band matching and quantitative comparison utilities
 *
 * Provides:
 * - Band matching across samples by MW
 * - Profile correlation calculation
 * - Metrics summary generation
 */

(function(global) {
    'use strict';

    // Get MWUtils from namespace
    const MWUtils = global.SampleComparison?.MWUtils;
    const BandMatchingUtils = global.SampleComparison?.BandMatchingUtils;

    /**
     * ComparisonMetrics class - calculates and manages comparison metrics
     */
    class ComparisonMetrics {
        constructor(state) {
            this.state = state;
        }

        /**
         * Calculate all comparison metrics for current samples.
         * @returns {Object} Metrics object with all calculated values
         */
        calculateMetrics() {
            const samples = this.state.getSamples();

            if (samples.length < 2) {
                return {
                    hasSufficientData: false,
                    sampleCount: samples.length,
                };
            }

            // Get band matches
            const bandMatches = BandMatchingUtils
                ? BandMatchingUtils.matchBandsByMW(samples, this.state.mwTolerance)
                : this._fallbackMatchBands(samples);

            // Calculate metrics
            const metrics = {
                hasSufficientData: true,
                sampleCount: samples.length,
                totalBands: this._countTotalBands(samples),
                matchedBandGroups: bandMatches.length,
                matchedBands: this._countMatchedBands(bandMatches),
                avgPoiPercent: this._calculateAvgPoiPercent(samples),
                maxPercentDiff: this._calculateMaxPercentDiff(bandMatches),
                bandMatches: bandMatches,
            };

            // Calculate pairwise correlations if profiles available
            metrics.correlations = this._calculatePairwiseCorrelations(samples);

            return metrics;
        }

        /**
         * Fallback band matching if BandMatchingUtils not available.
         * @private
         */
        _fallbackMatchBands(samples, tolerancePct = 5) {
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

            // Sort by MW descending
            allBands.sort((a, b) => b.estimated_mw_kda - a.estimated_mw_kda);

            // Cluster bands within tolerance
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

                // Calculate average MW for the group
                group.mw = group.bands.reduce((sum, b) => sum + b.estimated_mw_kda, 0)
                    / group.bands.length;

                // Calculate max % difference within group
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
         * Count total bands across all samples.
         * @private
         */
        _countTotalBands(samples) {
            return samples.reduce((sum, s) => sum + (s.bands?.length || 0), 0);
        }

        /**
         * Count bands that appear in multiple samples.
         * @private
         */
        _countMatchedBands(bandMatches) {
            return bandMatches.filter(g => g.bands.length > 1).length;
        }

        /**
         * Calculate average POI percentage across samples.
         * @private
         */
        _calculateAvgPoiPercent(samples) {
            const poiPercents = samples
                .filter(s => s.densitometry?.poi_percentage != null)
                .map(s => s.densitometry.poi_percentage);

            if (poiPercents.length === 0) return null;
            return poiPercents.reduce((a, b) => a + b, 0) / poiPercents.length;
        }

        /**
         * Calculate maximum % difference between matched bands.
         * @private
         */
        _calculateMaxPercentDiff(bandMatches) {
            let maxDiff = 0;

            bandMatches.forEach(group => {
                if (group.bands.length < 2) return;

                // Compare relative percentages
                const percents = group.bands
                    .filter(b => b.densitometry?.relative_percent_lane != null)
                    .map(b => b.densitometry.relative_percent_lane);

                if (percents.length < 2) return;

                const min = Math.min(...percents);
                const max = Math.max(...percents);
                const diff = max - min;

                if (diff > maxDiff) maxDiff = diff;
            });

            return maxDiff;
        }

        /**
         * Calculate pairwise profile correlations.
         * @private
         */
        _calculatePairwiseCorrelations(samples) {
            const correlations = [];

            for (let i = 0; i < samples.length; i++) {
                for (let j = i + 1; j < samples.length; j++) {
                    const s1 = samples[i];
                    const s2 = samples[j];

                    // Need MW-aligned profiles for correlation
                    if (!s1.mw_profile?.intensities || !s2.mw_profile?.intensities) {
                        continue;
                    }

                    const r = BandMatchingUtils
                        ? BandMatchingUtils.calculateCorrelation(
                              s1.mw_profile.intensities,
                              s2.mw_profile.intensities
                          )
                        : null;

                    if (r !== null) {
                        correlations.push({
                            sample1: s1.label,
                            sample2: s2.label,
                            correlation: r,
                        });
                    }
                }
            }

            return correlations;
        }

        /**
         * Generate band comparison table data.
         * @returns {Array} Array of row objects for table rendering
         */
        generateBandComparisonTable() {
            const samples = this.state.getSamples();
            const bandMatches = BandMatchingUtils
                ? BandMatchingUtils.matchBandsByMW(samples, this.state.mwTolerance)
                : this._fallbackMatchBands(samples);

            // Sort by MW descending
            bandMatches.sort((a, b) => b.mw - a.mw);

            // Generate rows
            const rows = [];

            bandMatches.forEach(group => {
                const row = {
                    mw: group.mw,
                    mwFormatted: group.mw.toFixed(1),
                    values: {},
                    maxDiff: null,
                };

                // Add value for each sample
                samples.forEach(sample => {
                    const band = group.bands.find(b => b.sampleId === sample.sampleId);
                    if (band) {
                        row.values[sample.sampleId] = {
                            percent: band.densitometry?.relative_percent_lane || null,
                            bandType: band.band_type,
                            color: sample.color,
                        };
                    } else {
                        row.values[sample.sampleId] = null;
                    }
                });

                // Calculate max difference
                const percents = Object.values(row.values)
                    .filter(v => v?.percent != null)
                    .map(v => v.percent);

                if (percents.length > 1) {
                    row.maxDiff = Math.max(...percents) - Math.min(...percents);
                }

                rows.push(row);
            });

            return rows;
        }
    }

    // Export to namespace
    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.ComparisonMetrics = ComparisonMetrics;

})(window);
