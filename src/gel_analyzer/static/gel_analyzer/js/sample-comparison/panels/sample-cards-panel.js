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

    /**
     * SampleCardsPanel Class
     */
    class SampleCardsPanel {
        constructor(options) {
            this.container = options.container;
            this.eventBus = options.eventBus;
            this.state = options.state;
            this.app = options.app;

            this._init();
        }

        _init() {
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
            this.eventBus.on(ComparisonEvents.SAMPLE_ADDED, () => this._render());
            this.eventBus.on(ComparisonEvents.SAMPLE_REMOVED, () => this._render());
            this.eventBus.on(ComparisonEvents.SAMPLE_ORDER_CHANGED, () => this._render());
            this.eventBus.on(ComparisonEvents.SAMPLE_SELECTED, (data) => {
                this._updateSelection(data.sampleId);
            });
        }

        _render() {
            const samples = this.state.getSamples();

            // Update sample count in header
            const countEl = document.getElementById('sample-count');
            if (countEl) {
                countEl.textContent = `${samples.length} item(s)`;
            }

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

                // Get step name from ProcessSample if available
                const stepName = sample?.step_name || '-';

                html += `
                    <div class="dm-sample-card ${cardClass}"
                         data-sample-id="${sampleId}"
                         style="border-left-color: ${color}">
                        <button class="dm-sample-card-remove" data-sample-id="${sampleId}" title="Remove">
                            <i class="bi bi-x"></i>
                        </button>
                        <div class="dm-sample-card-title">
                            ${label || 'Sample'}
                            ${hasComparabilityIssues ? `<i class="bi bi-exclamation-triangle-fill dm-critical-icon" title="${comparabilityMessage}"></i>` : ''}
                            ${!hasComparabilityIssues && isCalibrated ? '<i class="bi bi-check-circle-fill dm-calibrated-icon" title="MW Calibrated"></i>' : ''}
                            ${!hasComparabilityIssues && !isCalibrated && showCalibrationWarning ? '<i class="bi bi-exclamation-triangle-fill dm-uncalibrated-icon" title="Not calibrated - MW comparison may be inaccurate"></i>' : ''}
                        </div>
                        <div class="dm-sample-card-meta">
                            ${stepName} | Lane #${lane?.lane_number || '-'} | ${bandCount} band${bandCount !== 1 ? 's' : ''}
                        </div>
                    </div>
                `;
            });

            this.container.innerHTML = html;

            this.container.querySelectorAll('.dm-sample-card').forEach(card => {
                card.addEventListener('click', (e) => {
                    if (!e.target.closest('.dm-sample-card-remove')) {
                        // sampleId is a string like "lane_122" or "process_sample_15"
                        const sampleId = card.dataset.sampleId;
                        this.state.selectSample(sampleId);
                    }
                });
            });

            this.container.querySelectorAll('.dm-sample-card-remove').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    // sampleId is a string like "lane_122" or "process_sample_15"
                    const sampleId = btn.dataset.sampleId;
                    this.app.removeSample(sampleId);
                });
            });

            // Attach drag-and-drop reorder
            if (this.dragReorder) {
                this.dragReorder.container = this.container;
                this.dragReorder.attach();
            }
        }

        _updateSelection(selectedId) {
            this.container.querySelectorAll('.dm-sample-card').forEach(card => {
                // sampleId is a string like "lane_122" or "process_sample_15"
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
