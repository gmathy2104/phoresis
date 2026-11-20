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

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    /**
     * ComparisonResultsTablePanel Class
     */
    class ComparisonResultsTablePanel extends GelAnalyzer.Viz.Panel {
        constructor(options) {
            super(options);  // sets this.container/eventBus/state/options/tooltipLayer/_disposers

            this.contentElement = null;
            this.sortField = 'mw';
            this.sortDir = 'desc';

            this.metrics = ComparisonMetrics ? new ComparisonMetrics(this.state) : null;
        }

        init() {
            if (!this.container) return;

            this.contentElement = this.container.querySelector('.dm-panel-content');
            if (!this.contentElement) {
                this.contentElement = this.container;
            }

            this._setupEvents();
            this._render();
        }

        _setupEvents() {
            this._on(ComparisonEvents.DATA_LOADED, () => this._render());
            this._on(ComparisonEvents.SAMPLE_ADDED, () => this._render());
            this._on(ComparisonEvents.SAMPLE_REMOVED, () => this._render());
            this._on(ComparisonEvents.SAMPLE_ORDER_CHANGED, () => this._render());
            this._on(ComparisonEvents.MW_TOLERANCE_CHANGED, () => this._render());
            this._on(ComparisonEvents.BAND_SELECTED, (data) => this._updateSelection(data.bandId));
            this._on(ComparisonEvents.SAMPLE_SELECTED, (data) => this._highlightSampleColumn(data.sampleId));
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
                        MW alignment may be inaccurate for uncalibrated samples: ${escapeHtml(status.uncalibratedNames.join(', '))}</span>
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
                    ${this._averageMetric(metrics)}
                    ${metrics.maxPercentDiff > 0 ? `
                    <div class="dm-metric ${metrics.maxPercentDiff > 10 ? 'warning' : ''}">
                        <span class="dm-metric-value">Δ${metrics.maxPercentDiff.toFixed(1)}%</span>
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
                html += `<th class="sample-col${isSelected ? ' selected-column' : ''}" data-sample-id="${sample.sampleId}" style="border-top: 3px solid ${sample.color}; cursor: pointer;">${escapeHtml(sample.label || 'Sample')}</th>`;
            });

            html += `<th>Δ%</th></tr>`;

            // Sub-header row with sample metadata (POI purity, condition, load)
            html += `<tr class="sample-meta-row">`;
            html += `<th></th>`; // MW column placeholder
            samples.forEach(sample => {
                const isSelectedCol = sample.sampleId === this.state.selectedSampleId;
                const colClass = isSelectedCol ? ' selected-column' : '';
                const parts = [];

                // POI purity (a host that sends no readout rows; the comparison page prints them below)
                const poiPct = sample.densitometry?.poi_percentage;
                if (!this._readoutColumns().length && poiPct != null) {
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
                    parts.push(`<span class="meta-label">${escapeHtml(load)} µg${escapeHtml(typeLabel)}</span>`);
                }

                html += `<th class="sample-col${colClass}" data-sample-id="${sample.sampleId}">${parts.join('') || '<span class="meta-label" style="opacity:0.3">—</span>'}</th>`;
            });
            html += `<th></th>`; // Δ% column placeholder
            html += `</tr>`;

            html += `</thead><tbody>`;

            // The kind's readout first (the analysis page's labels and cells), then the bands by MW.
            html += this._renderReadoutRows(samples);

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
                        // Surface the protein quantification result (back-filled
                        // by ProteinQuantCalibrationService.apply_to_analysis)
                        // in the tooltip so users can read the absolute amount
                        // alongside the relative %.
                        const estAmt = band.densitometry?.estimated_amount;
                        const estUnit = band.densitometry?.estimated_amount_unit;
                        const tooltip = estAmt != null
                            ? `${band.band_type || 'Band'}: ${pct != null ? pct.toFixed(1) + '% lane, ' : ''}${estAmt.toFixed(2)} ${estUnit === 'UG_ML' ? 'µg/mL' : 'µg'}`
                            : `${band.band_type || 'Band'}${pct != null ? ': ' + pct.toFixed(1) + '% lane' : ''}`;
                        html += `
                            <td class="band-cell${colClass}" data-band-id="${band.id}" data-sample-id="${sample.sampleId}" title="${escapeHtml(tooltip)}">
                                <span class="dm-band-type-dot ${escapeHtml(typeClass)}"></span>
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


        // =====================================================================
        // Readout rows (the comparison page: options.readout / options.columns of the kind mounted)
        // =====================================================================

        /** The kind's value columns (services/analysis_detail.readout_columns), [] for a host without them. */
        _readoutColumns() {
            const columns = (this.options && this.options.columns) || [];
            const samples = this.state.getSamples();
            const blots = new Set(samples.map((s) => s.analysis?.id).filter(Boolean));
            // An a.u. signal depends on the membrane's exposure: compared within one blot only (spec §5).
            return columns.filter((c) => !(c.key === 'hcp_total_signal' && blots.size > 1));
        }

        _unitText(text) {
            return escapeHtml(text).replace(/(\bkDa\b|[µμ]g(?:\/mL)?|\ba\.u\.)/g, '<span class="ga-wb-unit-text">$1</span>');
        }

        _readoutCell(sample, key) {
            const readout = sample.readout;
            if (!readout || (readout.carries === false && key !== 'bands')) {
                return '<span class="dm-readout-muted">—</span>';
            }
            const cell = (readout.cells || {})[key];
            if (!cell) return '<span class="dm-readout-muted">—</span>';
            if (!cell.text) return `<span class="dm-readout-muted">${escapeHtml(cell.reason || '—')}</span>`;
            const tone = cell.tone ? ` dm-readout-tone--${escapeHtml(cell.tone)}` : '';
            return `<span class="dm-readout-value${tone}">${this._unitText(cell.text)}</span>`;
        }

        _renderReadoutRows(samples) {
            const columns = this._readoutColumns();
            if (!columns.length) return '';
            const selected = this.state.selectedSampleId;
            const colClass = (sample) => (sample.sampleId === selected ? ' selected-column' : '');
            let html = '';
            columns.forEach((column) => {
                html += `<tr class="dm-readout-row"><td class="mw-cell dm-readout-label" title="${escapeHtml(column.title || '')}">${this._unitText(column.label)}</td>`;
                samples.forEach((sample) => {
                    html += `<td class="band-cell${colClass(sample)}" data-sample-id="${sample.sampleId}">${this._readoutCell(sample, column.key)}</td>`;
                });
                html += '<td></td></tr>';
            });
            if ((this.options && this.options.readout) === 'HOST_CELL_PROTEINS') {
                // Each lane is read against its own blot's reference lane.
                html += '<tr class="dm-readout-row"><td class="mw-cell dm-readout-label" title="The reference lane of the lane\'s blot">Reference</td>';
                samples.forEach((sample) => {
                    const r = sample.readout || {};
                    const text = r.is_reference
                        ? '<span class="ga-wb-ref">REF</span>'
                        : (r.reference_lane_number != null
                            ? `L${escapeHtml(r.reference_lane_number)}`
                            : '<span class="dm-readout-muted">no reference lane</span>');
                    html += `<td class="band-cell${colClass(sample)}" data-sample-id="${sample.sampleId}">${text}</td>`;
                });
                html += '<td></td></tr>';
            }
            html += `<tr class="dm-readout-sep"><td colspan="${samples.length + 2}">Bands by MW</td></tr>`;
            return html;
        }

        /**
         * "Avg purity" of a purity kind, from the published values; none on a western kind. The lanes
         * averaged are the ones the server's mean purity counts (services/mean_purity.py, the row's
         * `in_mean_purity`: SAMPLE lanes), as on the analysis page: a control lane is shown, not averaged.
         */
        _averageMetric(metrics) {
            const readout = this.options && this.options.readout;
            if (!readout) {
                return metrics.avgPoiPercent !== null ? `
                    <div class="dm-metric">
                        <span class="dm-metric-value">${metrics.avgPoiPercent.toFixed(1)}%</span>
                        <span class="dm-metric-label">Avg POI</span>
                    </div>` : '';
            }
            if (readout !== 'PURITY') return '';
            const lanes = this.state.getSamples()
                .map((s) => s.readout)
                .filter((r) => r && r.in_mean_purity);
            if (!lanes.length) return '';
            const values = lanes
                .map((r) => r.purity)
                .filter((v) => v !== null && v !== undefined && isFinite(v));
            const mean = values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
            // MeanPurity.lanes_text's words.
            const averaged = `${values.length} of ${lanes.length} sample lanes`;
            return `
                    <div class="dm-metric" title="Mean of the sample lanes' purity; a control lane, or a lane without a POI band, is left out">
                        <span class="dm-metric-value">${mean === null ? '—' : `${mean.toFixed(1)}%`}</span>
                        <span class="dm-metric-label">Avg purity · ${averaged}</span>
                    </div>`;
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
