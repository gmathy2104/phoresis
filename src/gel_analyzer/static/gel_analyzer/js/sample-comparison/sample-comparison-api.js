/**
 * Sample Comparison API Client
 *
 * Handles API communication for fetching sample densitometry data
 * and lane profiles from the process_development endpoints.
 */

(function(global) {
    'use strict';

    /**
     * SampleComparisonApi Class
     */
    class SampleComparisonApi {
        /**
         * @param {Object} options
         * @param {string} options.csrfToken - CSRF token for POST requests
         * @param {Object} options.apiUrls - URL templates
         * @param {string} options.apiUrls.sampleData - URL for sample densitometry data
         * @param {string} options.apiUrls.laneProfile - URL for lane profile
         * @param {string} [options.apiUrls.export] - URL for CSV export
         */
        constructor(options) {
            this.csrfToken = options.csrfToken;
            this.apiUrls = options.apiUrls || {};
        }

        /**
         * Get densitometry data for a ProcessSample.
         * @param {number|string} sampleId - ProcessSample ID
         * @returns {Promise<Object>} Sample data with lane, bands, and profile
         */
        async getSampleDensitometry(sampleId) {
            const url = this._buildUrl(this.apiUrls.sampleData, { sampleId });

            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                },
            });

            if (!response.ok) {
                const error = await this._parseError(response);
                throw new Error(error.message || `Failed to fetch sample ${sampleId}`);
            }

            return response.json();
        }

        /**
         * Get profile data for a lane.
         * @param {number} laneId - Lane ID
         * @returns {Promise<Object>} Profile data with y_positions, intensities, etc.
         */
        async getLaneProfile(laneId) {
            const url = this._buildUrl(this.apiUrls.laneProfile, { laneId });

            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                },
            });

            if (!response.ok) {
                const error = await this._parseError(response);
                throw new Error(error.message || `Failed to fetch profile for lane ${laneId}`);
            }

            return response.json();
        }

        /**
         * Fetch multiple samples in parallel.
         * @param {Array<number|string>} sampleIds - Array of sample IDs
         * @returns {Promise<Array>} Array of sample data objects
         */
        async getMultipleSamples(sampleIds) {
            const promises = sampleIds.map(id => this.getSampleDensitometry(id));
            return Promise.all(promises);
        }

        /**
         * Export comparison data to CSV.
         * @param {Array<Object>} samples - Array of sample data
         * @param {Object} [options] - Export options
         * @param {boolean} [options.includeProfiles] - Include profile data
         * @returns {Promise<Blob>} CSV file as Blob
         */
        async exportToCSV(samples, options = {}) {
            if (!this.apiUrls.export) {
                // Generate CSV locally if no server endpoint
                return this._generateLocalCSV(samples, options);
            }

            const response = await fetch(this.apiUrls.export, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
                body: JSON.stringify({
                    sample_ids: samples.map(s => s.sampleId),
                    include_profiles: options.includeProfiles || false,
                }),
            });

            if (!response.ok) {
                throw new Error('Failed to export CSV');
            }

            return response.blob();
        }

        /**
         * Generate CSV locally from sample data.
         * Enhanced to include MW-aligned comparison and band matching.
         * @private
         */
        _generateLocalCSV(samples, options) {
            const lines = [];
            const BandMatchingUtils = window.SampleComparison?.BandMatchingUtils;

            // === Section 1: Summary ===
            lines.push('# Sample Comparison Export');
            lines.push(`# Generated: ${new Date().toISOString()}`);
            lines.push(`# Samples: ${samples.length}`);
            lines.push('');

            // === Section 2: MW-Aligned Band Comparison Table ===
            lines.push('# MW-Aligned Band Comparison');

            // Build header with sample names
            const header = ['MW (kDa)'];
            samples.forEach(s => header.push(`${s.label || 'Sample'} %`));
            header.push('Max Diff %');
            lines.push(header.join(','));

            // Get band matches
            const bandMatches = BandMatchingUtils
                ? BandMatchingUtils.matchBandsByMW(samples, 5)
                : this._fallbackMatchBands(samples);

            // Sort by MW descending
            bandMatches.sort((a, b) => b.mw - a.mw);

            // Add rows
            bandMatches.forEach(group => {
                const row = [group.mw.toFixed(1)];

                samples.forEach(sample => {
                    const band = group.bands.find(b => b.sampleId === sample.sampleId);
                    if (band && band.densitometry?.relative_percent_lane != null) {
                        row.push(band.densitometry.relative_percent_lane.toFixed(2));
                    } else {
                        row.push('');
                    }
                });

                // Calculate max diff
                const percents = group.bands
                    .filter(b => b.densitometry?.relative_percent_lane != null)
                    .map(b => b.densitometry.relative_percent_lane);

                if (percents.length > 1) {
                    row.push((Math.max(...percents) - Math.min(...percents)).toFixed(2));
                } else {
                    row.push('');
                }

                lines.push(row.join(','));
            });

            lines.push('');

            // === Section 3: Detailed Band Data ===
            lines.push('# Detailed Band Data');
            lines.push([
                'Sample ID',
                'Sample Name',
                'Step',
                'Lane Number',
                'Band Type',
                'Band Position (Y)',
                'Estimated MW (kDa)',
                'Corrected Area',
                'Relative % (Lane)',
                'Peak Amplitude',
                'Fit R²',
            ].join(','));

            samples.forEach(sampleData => {
                const { sample, lane, bands } = sampleData;

                if (!bands || bands.length === 0) {
                    lines.push([
                        sample.id,
                        `"${sample.sample_id || ''}"`,
                        `"${sample.step_name || ''}"`,
                        lane?.lane_number || '',
                        'N/A',
                        '', '', '', '', '', '',
                    ].join(','));
                } else {
                    bands.forEach(band => {
                        lines.push([
                            sample.id,
                            `"${sample.sample_id || ''}"`,
                            `"${sample.step_name || ''}"`,
                            lane?.lane_number || '',
                            band.band_type,
                            band.position_y,
                            band.estimated_mw_kda || '',
                            band.densitometry?.corrected_area?.toFixed(2) || '',
                            band.densitometry?.relative_percent_lane?.toFixed(2) || '',
                            band.densitometry?.peak_amplitude?.toFixed(2) || '',
                            band.densitometry?.fit_r_squared?.toFixed(4) || '',
                        ].join(','));
                    });
                }
            });

            const csvContent = lines.join('\n');
            return Promise.resolve(new Blob([csvContent], { type: 'text/csv' }));
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
                group.mw = group.bands.reduce((sum, b) => sum + b.estimated_mw_kda, 0) / group.bands.length;
                matched.push(group);
            });

            return matched;
        }

        /**
         * Build URL from template.
         * @private
         */
        _buildUrl(template, params) {
            if (!template) {
                throw new Error('URL template not provided');
            }

            let url = template;
            Object.keys(params).forEach(key => {
                url = url.replace(`{${key}}`, params[key]);
            });
            return url;
        }

        /**
         * Parse error response.
         * @private
         */
        async _parseError(response) {
            try {
                const data = await response.json();
                return {
                    status: response.status,
                    message: data.error || data.message || data.detail || 'Unknown error',
                };
            } catch (e) {
                return {
                    status: response.status,
                    message: `HTTP ${response.status}: ${response.statusText}`,
                };
            }
        }
    }

    // Export to namespace
    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.Api = SampleComparisonApi;

})(window);
