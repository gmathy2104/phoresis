/**
 * Comparison Results Table Panel
 *
 * Displays band comparison table with MW-aligned rows, showing each sample's
 * contribution to each MW group with difference calculations.
 */

(function(global) {
    'use strict';

    // Get dependencies from namespaces
    const ComparisonEvents = global.SampleComparison?.Events;
    const ComparisonMetrics = global.SampleComparison?.ComparisonMetrics;

    /**
     * ComparisonResultsTablePanel Class
     */
    class ComparisonResultsTablePanel {
        constructor(options) {
            this.container = options.container;
            this.eventBus = options.eventBus;
            this.state = options.state;

            this.contentElement = null;
            this.sortField = 'mw';
            this.sortDir = 'desc';

            this.metrics = ComparisonMetrics ? new ComparisonMetrics(this.state) : null;

            this._init();
        }

        _init() {
            if (!this.container) return;

            this.contentElement = this.container.querySelector('.dm-panel-content');
            if (!this.contentElement) {
                this.contentElement = this.container;
            }

            this._setupEvents();
            this._render();
        }

        _setupEvents() {
            this.eventBus.on(ComparisonEvents.DATA_LOADED, () => this._render());
            this.eventBus.on(ComparisonEvents.SAMPLE_ADDED, () => this._render());
            this.eventBus.on(ComparisonEvents.SAMPLE_REMOVED, () => this._render());
            this.eventBus.on(ComparisonEvents.SAMPLE_ORDER_CHANGED, () => this._render());
            this.eventBus.on(ComparisonEvents.MW_TOLERANCE_CHANGED, () => this._render());
            this.eventBus.on(ComparisonEvents.BAND_SELECTED, (data) => this._updateSelection(data.bandId));
            this.eventBus.on(ComparisonEvents.SAMPLE_SELECTED, (data) => this._highlightSampleColumn(data.sampleId));
        }

        _render() {
            const samples = this.state.getSamples();

            if (samples.length === 0) {
                this.contentElement.innerHTML = `
                    <div class="dm-placeholder">
                        <i class="bi bi-table"></i>
                        <span>No samples to compare</span>
                    </div>
                `;
                return;
            }

            // Check calibration status
            const calibrationStatus = this._getCalibrationStatus(samples);

            // Calculate metrics if available
            let metricsData = null;
            if (this.metrics) {
                metricsData = this.metrics.calculateMetrics();
            }

            // Build HTML with metrics summary and band comparison table
            let html = '';

            // Calibration warning if mixed status
            if (calibrationStatus.mixed) {
                html += this._renderCalibrationWarning(calibrationStatus);
            }

            // Metrics summary row
            if (metricsData && metricsData.hasSufficientData) {
                html += this._renderMetricsSummary(metricsData, calibrationStatus);
            }

            // Band comparison table
            html += this._renderBandComparisonTable(samples, metricsData);

            this.contentElement.innerHTML = html;

            // Attach handlers
            this._attachEventHandlers();
        }

        _getCalibrationStatus(samples) {
            const calibrated = samples.filter(s => s.calibration);
            const uncalibrated = samples.filter(s => !s.calibration);

            return {
                all: calibrated.length === samples.length,
                none: uncalibrated.length === samples.length,
                mixed: calibrated.length > 0 && uncalibrated.length > 0,
                calibratedCount: calibrated.length,
                uncalibratedCount: uncalibrated.length,
                calibratedNames: calibrated.map(s => s.label),
                uncalibratedNames: uncalibrated.map(s => s.label),
            };
        }

        _renderCalibrationWarning(status) {
            return `
                <div class="dm-calibration-warning">
                    <i class="bi bi-exclamation-triangle-fill"></i>
                    <div class="dm-warning-content">
                        <strong>Mixed Calibration Status</strong>
                        <span>${status.calibratedCount} sample(s) calibrated, ${status.uncalibratedCount} not calibrated.
                        MW alignment may be inaccurate for uncalibrated samples: ${status.uncalibratedNames.join(', ')}</span>
                    </div>
                </div>
            `;
        }

        _renderMetricsSummary(metrics, calibrationStatus = null) {
            return `
                <div class="dm-metrics-summary">
                    <div class="dm-metric">
                        <span class="dm-metric-value">${metrics.sampleCount}</span>
                        <span class="dm-metric-label">Samples</span>
                    </div>
                    ${calibrationStatus ? `
                    <div class="dm-metric ${calibrationStatus.mixed ? 'warning' : ''}">
                        <span class="dm-metric-value">${calibrationStatus.calibratedCount}/${metrics.sampleCount}</span>
                        <span class="dm-metric-label">Calibrated</span>
                    </div>` : ''}
                    <div class="dm-metric">
                        <span class="dm-metric-value">${metrics.matchedBands} / ${metrics.matchedBandGroups}</span>
                        <span class="dm-metric-label">Matched / Groups</span>
                    </div>
                    ${metrics.avgPoiPercent !== null ? `
                    <div class="dm-metric">
                        <span class="dm-metric-value">${metrics.avgPoiPercent.toFixed(1)}%</span>
                        <span class="dm-metric-label">Avg POI</span>
                    </div>` : ''}
                    ${metrics.maxPercentDiff > 0 ? `
                    <div class="dm-metric ${metrics.maxPercentDiff > 10 ? 'warning' : ''}">
                        <span class="dm-metric-value">\u0394${metrics.maxPercentDiff.toFixed(1)}%</span>
                        <span class="dm-metric-label">Max Diff</span>
                    </div>` : ''}
                </div>
            `;
        }

        _renderBandComparisonTable(samples, metricsData) {
            // Get band matches from metrics or create simple list
            let rows = [];

            if (metricsData?.bandMatches) {
                // Use grouped band data for MW-aligned comparison
                rows = metricsData.bandMatches.map(group => ({
                    mw: group.mw,
                    bands: group.bands,
                    mwDiffPct: group.mwDiffPct || 0,
                }));
            } else {
                // Fall back to flat band list
                const allBands = this.state.getAllBands();
                rows = allBands.map(band => ({
                    mw: band.estimated_mw_kda || 0,
                    bands: [band],
                    mwDiffPct: 0,
                }));
            }

            // Sort rows
            rows.sort((a, b) => {
                const dir = this.sortDir === 'asc' ? 1 : -1;
                return (b.mw - a.mw) * dir;
            });

            // Build table with dynamic columns for each sample
            let html = `<div class="dm-results-table-wrapper">
                <table class="dm-results-table dm-comparison-table">
                    <thead>
                        <tr>
                            <th class="sortable" data-field="mw">MW (kDa)</th>
            `;

            // Add column for each sample
            samples.forEach(sample => {
                const isSelected = sample.sampleId === this.state.selectedSampleId;
                html += `<th class="sample-col${isSelected ? ' selected-column' : ''}" data-sample-id="${sample.sampleId}" style="border-top: 3px solid ${sample.color}; cursor: pointer;">${sample.label || 'Sample'}</th>`;
            });

            html += `<th>\u0394%</th></tr>`;

            // Sub-header row with sample metadata (POI purity, condition, load)
            html += `<tr class="sample-meta-row">`;
            html += `<th></th>`; // MW column placeholder
            samples.forEach(sample => {
                const isSelectedCol = sample.sampleId === this.state.selectedSampleId;
                const colClass = isSelectedCol ? ' selected-column' : '';
                const parts = [];

                // POI purity
                const poiPct = sample.densitometry?.poi_percentage;
                if (poiPct != null) {
                    parts.push(`<span class="meta-label meta-poi">POI: ${poiPct.toFixed(1)}%</span>`);
                }

                // Condition (reduced/non-reduced)
                if (sample.lane?.is_reduced === true) {
                    parts.push(`<span class="meta-label">Reduced</span>`);
                } else if (sample.lane?.is_reduced === false) {
                    parts.push(`<span class="meta-label">Non-reduced</span>`);
                }

                // Protein load
                const load = sample.lane?.protein_load_ug;
                if (load != null) {
                    const loadType = sample.lane?.protein_load_type || '';
                    const typeLabel = loadType ? ` (${loadType})` : '';
                    parts.push(`<span class="meta-label">${load} \u00b5g${typeLabel}</span>`);
                }

                html += `<th class="sample-col${colClass}" data-sample-id="${sample.sampleId}">${parts.join('') || '<span class="meta-label" style="opacity:0.3">\u2014</span>'}</th>`;
            });
            html += `<th></th>`; // Δ% column placeholder
            html += `</tr>`;

            html += `</thead><tbody>`;

            // Render rows
            rows.forEach(row => {
                const isPoiRow = row.bands.some(b => b.band_type === 'POI');

                html += `<tr class="dm-table-row ${isPoiRow ? 'poi-row' : ''}">`;
                html += `<td class="mw-cell">${row.mw.toFixed(1)}</td>`;

                // Add cell for each sample
                samples.forEach(sample => {
                    const band = row.bands.find(b => b.sampleId === sample.sampleId);
                    const isSelectedCol = sample.sampleId === this.state.selectedSampleId;
                    const colClass = isSelectedCol ? ' selected-column' : '';
                    if (band) {
                        const pct = band.densitometry?.relative_percent_lane;
                        const typeClass = (band.band_type || 'OTHER').toLowerCase();
                        html += `
                            <td class="band-cell${colClass}" data-band-id="${band.id}" data-sample-id="${sample.sampleId}">
                                <span class="dm-band-type-dot ${typeClass}"></span>
                                ${pct != null ? pct.toFixed(1) + '%' : '-'}
                            </td>
                        `;
                    } else {
                        html += `<td class="band-cell empty${colClass}" data-sample-id="${sample.sampleId}">-</td>`;
                    }
                });

                // Diff column
                const percents = row.bands
                    .filter(b => b.densitometry?.relative_percent_lane != null)
                    .map(b => b.densitometry.relative_percent_lane);

                let diffHtml = '-';
                if (percents.length > 1) {
                    const diff = Math.max(...percents) - Math.min(...percents);
                    const diffClass = diff > 10 ? 'high' : diff > 5 ? 'medium' : 'low';
                    diffHtml = `<span class="diff-value ${diffClass}">${diff.toFixed(1)}</span>`;
                }
                html += `<td class="diff-cell">${diffHtml}</td>`;

                html += `</tr>`;
            });

            html += '</tbody></table></div>';
            return html;
        }

        _attachEventHandlers() {
            // Row click to select first band in that MW group
            this.contentElement.querySelectorAll('.band-cell[data-band-id]').forEach(cell => {
                cell.addEventListener('click', () => {
                    const bandId = cell.dataset.bandId;
                    this.state.selectBand(bandId);
                });
                cell.style.cursor = 'pointer';
            });

            // Sample column header click to select sample
            this.contentElement.querySelectorAll('th.sample-col').forEach(th => {
                th.addEventListener('click', () => {
                    const sampleId = th.dataset.sampleId;
                    if (sampleId) {
                        this.state.selectSample(sampleId);
                    }
                });
            });

            // Sort headers
            this.contentElement.querySelectorAll('th.sortable').forEach(th => {
                th.addEventListener('click', () => {
                    const field = th.dataset.field;
                    if (this.sortField === field) {
                        this.sortDir = this.sortDir === 'asc' ? 'desc' : 'asc';
                    } else {
                        this.sortField = field;
                        this.sortDir = 'desc';
                    }
                    this._render();
                });
            });
        }

        _updateSelection(selectedBandId) {
            if (!this.contentElement) return;

            // Remove previous selection
            this.contentElement.querySelectorAll('.dm-table-row.selected').forEach(row => {
                row.classList.remove('selected');
            });

            if (!selectedBandId) return;

            // Find the row containing a cell with the matching band ID
            const matchingCell = this.contentElement.querySelector(`.band-cell[data-band-id="${selectedBandId}"]`);
            if (matchingCell) {
                const row = matchingCell.closest('.dm-table-row');
                if (row) {
                    row.classList.add('selected');
                    // Scroll the row into view
                    row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
                }
            }
        }

        _highlightSampleColumn(sampleId) {
            if (!this.contentElement) return;

            // Remove all column highlights
            this.contentElement.querySelectorAll('.selected-column').forEach(el => {
                el.classList.remove('selected-column');
            });

            if (!sampleId) return;

            // Add highlight to matching header and cells
            this.contentElement.querySelectorAll(`[data-sample-id="${sampleId}"]`).forEach(el => {
                el.classList.add('selected-column');
            });
        }
    }

    // Export to namespace
    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.Panels = global.SampleComparison.Panels || {};
    global.SampleComparison.Panels.ResultsTable = ComparisonResultsTablePanel;

})(window);
