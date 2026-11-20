/**
 * Sample Comparison API Client
 *
 * Handles API communication for the comparison component: lane profiles and
 * the CSV export. Phoresis compares lanes only: ds-hub's Process Development
 * sample endpoints (sample densitometry, comparisons/resolve/) do not exist here.
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
         * @param {string} options.apiUrls.laneProfile - URL for lane profile
         * @param {string} [options.apiUrls.export] - URL for CSV export
         */
        constructor(options) {
            this.csrfToken = options.csrfToken;
            this.apiUrls = options.apiUrls || {};
            this.signal = options.signal || null;   // NEW
        }

        /**
         * Get profile data for a lane.
         * @param {number} laneId - Lane ID
         * @returns {Promise<Object>} Profile data with y_positions, intensities, etc.
         */
        async getLaneProfile(laneId) {
            const url = this._buildUrl(this.apiUrls.laneProfile, { laneId });

            const response = await fetch(url, {
                signal: this.signal,
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
                signal: this.signal,
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
            options = options || {};
            const lines = [];
            const BandMatchingUtils = window.SampleComparison?.BandMatchingUtils;
            // A text cell: quoted, inner quotes doubled, and a leading = + - @ neutralised (a spreadsheet would
            // run it as a formula).
            const q = (value) => {
                let text = value === null || value === undefined ? '' : String(value);
                if (/^[=+\-@]/.test(text)) text = `'${text}`;
                return `"${text.replace(/"/g, '""')}"`;
            };
            const tolerance = options.mwTolerance || 5;

            // === Section 1: Summary ===
            lines.push('# Sample Comparison Export');
            lines.push(`# Generated: ${new Date().toISOString()}`);
            if (options.kind) lines.push(`# Assay: ${options.kind}`);
            lines.push(`# Samples: ${samples.length}`);
            lines.push(`# MW tolerance: ${tolerance} %`);
            lines.push('');

            // === Section 1b: the readout of the kind (the analysis page's cells), when the page sent it ===
            const columns = options.columns || [];
            if (columns.length && samples.some((s) => s.readout)) {
                lines.push('# Readout');
                lines.push(['Lane', 'Gel', 'Lane Number', ...columns.map((c) => c.label)].map(q).join(','));
                samples.forEach((s) => {
                    const r = s.readout || {};
                    const cells = columns.map((c) => {
                        if (r.carries === false && c.key !== 'bands') return '';
                        const cell = (r.cells || {})[c.key];
                        return cell ? (cell.text || cell.reason || '') : '';
                    });
                    lines.push([s.label || '', s.analysis?.name || '', s.lane?.lane_number ?? '', ...cells].map(q).join(','));
                });
                lines.push('');
            }

            // === Section 2: MW-Aligned Band Comparison Table ===
            lines.push('# MW-Aligned Band Comparison');

            // Build header with sample names
            const header = [q('MW (kDa)')];
            samples.forEach(s => header.push(q(`${s.label || 'Sample'} %`)));
            header.push(q('Max Diff %'));
            lines.push(header.join(','));

            // Get band matches (the tolerance of the page's MW tolerance field)
            const bandMatches = BandMatchingUtils
                ? BandMatchingUtils.matchBandsByMW(samples, tolerance)
                : this._fallbackMatchBands(samples, tolerance);

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
            ].map(q).join(','));

            samples.forEach(sampleData => {
                // A Phoresis lane always has sample: null (no ProcessSample): the two sample columns stay empty.
                const { lane, bands } = sampleData;
                const sample = sampleData.sample || {};
                const name = sample.sample_id || lane?.sample_name || sampleData.label || '';
                const lead = [sample.id ?? '', q(name), q(sample.step_name || ''), lane?.lane_number ?? ''];

                if (!bands || bands.length === 0) {
                    lines.push([...lead, q('N/A'), '', '', '', '', '', ''].join(','));
                } else {
                    bands.forEach(band => {
                        lines.push([
                            ...lead,
                            q(band.band_type),
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
