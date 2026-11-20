/**
 * Sample Cards Panel
 *
 * Displays the horizontal row of sample cards at the top of the comparison view.
 * Each card shows sample metadata, calibration status, and allows selection/removal.
 */

(function(global) {
    'use strict';

    // Get events and utilities from namespace
    const ComparisonEvents = global.SampleComparison?.Events;
    const DragReorder = global.SampleComparison?.DragReorder;

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    /**
     * SampleCardsPanel Class
     */
    // The cell a lane card shows, by the kind's readout (services/analysis_detail.readout_columns keys).
    const HEADLINE_CELL = {
        PURITY: 'purity',
        MOLECULE_VARIANTS: 'main_band_percent',
        HOST_CELL_PROTEINS: 'hcp_signal_vs_reference_percent',
    };
    const HEADLINE_LABEL = {
        purity: 'Purity',
        main_band_percent: 'Main band',
        hcp_signal_vs_reference_percent: '% of ref.',
    };

    class SampleCardsPanel extends GelAnalyzer.Viz.Panel {
        constructor(options) {
            super(options);  // sets this.container/eventBus/state/options/tooltipLayer/_disposers
            // The App (needed for removeSample) comes in the panel options (sample-comparison-app.js
            // panelOptions = {app, ...}); read at the top level it was undefined and the card's X threw.
            this.app = options.app || (options.options && options.options.app) || null;
        }

        init() {
            if (!this.container) return;

            // Initialize drag-and-drop reorder
            if (DragReorder) {
                this.dragReorder = new DragReorder({
                    container: this.container,
                    itemSelector: '.dm-sample-card',
                    dataKey: 'sampleId',
                    onReorder: (newOrder) => {
                        this.state.reorderSamples(newOrder);
                    },
                });
            }

            this._setupEvents();
            this._render();
        }

        _setupEvents() {
            this._on(ComparisonEvents.SAMPLE_ADDED, () => this._render());
            this._on(ComparisonEvents.SAMPLE_REMOVED, () => this._render());
            this._on(ComparisonEvents.SAMPLE_ORDER_CHANGED, () => this._render());
            this._on(ComparisonEvents.SAMPLE_SELECTED, (data) => {
                this._updateSelection(data.sampleId);
            });
        }

        _render() {
            const samples = this.state.getSamples();

            // Sample-count display is page chrome (header subtitle) and lives
            // OUTSIDE the component (Task 7). Consumers wire it to the
            // SAMPLE_ADDED / SAMPLE_REMOVED eventBus events (which carry
            // totalSamples). The panel no longer reaches out of its container.

            if (samples.length === 0) {
                this.container.innerHTML = `
                    <div class="dm-sample-cards-empty">
                        <i class="bi bi-plus-circle me-2"></i> Click "Add Sample" to start comparing
                    </div>
                `;
                return;
            }

            let html = '';
            const hasAnyCalibration = samples.some(s => s.calibration);
            const allCalibrated = samples.every(s => s.calibration);

            samples.forEach(sampleData => {
                // Use sampleId and label from sampleData - sample may be null for standalone lanes
                const { sampleId, label, sample, lane, bands, color, calibration, comparability } = sampleData;
                const isSelected = sampleId === this.state.selectedSampleId;
                const bandCount = bands?.length || 0;
                const isCalibrated = !!calibration;

                // Check comparability status
                const hasComparabilityIssues = comparability && !comparability.is_valid;
                const comparabilityMessage = comparability?.message || 'Sample has data issues';

                // Show warning if mixed calibration status
                const showCalibrationWarning = hasAnyCalibration && !allCalibrated && !hasComparabilityIssues;

                // Determine card class based on issues
                let cardClass = isSelected ? 'selected' : '';
                if (hasComparabilityIssues) {
                    cardClass += ' has-critical-issues';
                } else if (!isCalibrated && showCalibrationWarning) {
                    cardClass += ' uncalibrated';
                }

                // ds-hub's process step of a ProcessSample; a Phoresis lane has none (sample: null).
                const stepPrefix = sample?.step_name ? `${escapeHtml(sample.step_name)} | ` : '';

                html += `
                    <div class="dm-sample-card ${cardClass}"
                         data-sample-id="${sampleId}"
                         style="border-left-color: ${color}">
                        <button class="dm-sample-card-remove" data-sample-id="${sampleId}" title="Remove">
                            <i class="bi bi-x"></i>
                        </button>
                        <div class="dm-sample-card-title">
                            ${escapeHtml(label || 'Sample')}
                            ${hasComparabilityIssues ? `<i class="bi bi-exclamation-triangle-fill dm-critical-icon" title="${escapeHtml(comparabilityMessage)}"></i>` : ''}
                            ${!hasComparabilityIssues && isCalibrated ? '<i class="bi bi-check-circle-fill dm-calibrated-icon" title="MW Calibrated"></i>' : ''}
                            ${!hasComparabilityIssues && !isCalibrated && showCalibrationWarning ? '<i class="bi bi-exclamation-triangle-fill dm-uncalibrated-icon" title="Not calibrated - MW comparison may be inaccurate"></i>' : ''}
                        </div>
                        <div class="dm-sample-card-meta">
                            ${stepPrefix}Lane #${lane?.lane_number || '-'} | ${bandCount} band${bandCount !== 1 ? 's' : ''}
                        </div>
                        ${this._readLine(sampleData)}
                    </div>
                `;
            });

            this.container.innerHTML = html;

            this.container.querySelectorAll('.dm-sample-card').forEach(card => {
                card.addEventListener('click', (e) => {
                    if (!e.target.closest('.dm-sample-card-remove')) {
                        // sampleId is the lane's: "lane_122"
                        const sampleId = card.dataset.sampleId;
                        this.state.selectSample(sampleId);
                    }
                });
            });

            this.container.querySelectorAll('.dm-sample-card-remove').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    // sampleId is the lane's: "lane_122"
                    const sampleId = btn.dataset.sampleId;
                    if (this.app) this.app.removeSample(sampleId);
                    else this.state.removeSample(sampleId);
                });
            });

            // Attach drag-and-drop reorder
            if (this.dragReorder) {
                this.dragReorder.container = this.container;
                this.dragReorder.attach();
            }
        }


        /**
         * What the lane reads for its kind (the comparison page sends `readout`, services/comparison_items.py):
         * the purity, the main band or the HCP % of the reference -- the analysis page's cell, or its reason --
         * and a link to the analysis it comes from. Nothing for a host that sends no readout.
         */
        _readLine(sampleData) {
            const readout = sampleData.readout;
            const analysis = sampleData.analysis || {};
            if (!readout && !analysis.url) return '';
            const key = HEADLINE_CELL[(this.options && this.options.readout) || ''];
            let value = '';
            if (readout && key) {
                const cell = (readout.cells || {})[key];
                if (readout.carries === false || !cell) {
                    value = '<span class="dm-readout-muted">—</span>';
                } else if (cell.text) {
                    value = `<span>${escapeHtml(HEADLINE_LABEL[key])}</span> <b>${escapeHtml(cell.text)}</b>`;
                } else {
                    value = `<span class="dm-readout-muted">${escapeHtml(cell.reason || '—')}</span>`;
                }
            }
            const link = analysis.url
                ? `<a class="dm-sample-card-link" href="${escapeHtml(analysis.url)}" title="Open the analysis: ${escapeHtml(analysis.name || '')}" aria-label="Open the analysis" draggable="false"><i class="bi bi-box-arrow-up-right"></i></a>`
                : '';
            return `<div class="dm-sample-card-read">${value}${link}</div>`;
        }

        _updateSelection(selectedId) {
            this.container.querySelectorAll('.dm-sample-card').forEach(card => {
                // sampleId is the lane's: "lane_122"
                const cardId = card.dataset.sampleId;
                card.classList.toggle('selected', cardId === selectedId);
            });
        }
    }

    // Export to namespace
    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.Panels = global.SampleComparison.Panels || {};
    global.SampleComparison.Panels.SampleCards = SampleCardsPanel;

})(window);
