/**
 * Band Detail Panel
 *
 * Shows selected band information and side-by-side digital lane visualization
 * with MW-aligned band positioning for visual comparison across samples.
 */

(function(global) {
    'use strict';

    // Get events and utilities from namespace
    const ComparisonEvents = global.SampleComparison?.Events;
    const DragReorder = global.SampleComparison?.DragReorder;

    /**
     * BandDetailPanel Class
     */
    class BandDetailPanel {
        constructor(options) {
            this.container = options.container;
            this.eventBus = options.eventBus;
            this.state = options.state;

            this.contentElement = null;
            this.currentBandId = null;
            this.currentBand = null;
            this.currentSampleId = null;

            this.digitalLaneMode = 'bands';

            this.colors = {
                poi: '#a855f7',
                other: '#22c55e',
                mwReference: '#f97316',
            };

            this._init();
        }

        _init() {
            if (!this.container) return;

            this.contentElement = this.container.querySelector('.dm-panel-content');
            if (!this.contentElement) {
                this.contentElement = this.container;
            }

            // Initialize drag-and-drop reorder for lane columns
            if (DragReorder) {
                this.laneReorder = new DragReorder({
                    container: null, // Set dynamically after render
                    itemSelector: '.dm-lane-column',
                    dataKey: 'sampleId',
                    onReorder: (newOrder) => {
                        this.state.reorderSamples(newOrder);
                    },
                });
            }

            this._createLayout();
            this._setupEvents();
            this._setupModeToggle();
        }

        _createLayout() {
            this.contentElement.innerHTML = `
                <div class="dm-band-detail-container dm-side-by-side">
                    <!-- Side-by-side Digital Lanes (Full Width) -->
                    <div class="dm-digital-lanes-container">
                        <div class="dm-digital-lanes-wrapper" id="digital-lanes">
                            <div class="dm-lane-placeholder">
                                <i class="bi bi-list-columns"></i>
                                <span>Add samples to compare lanes</span>
                            </div>
                        </div>
                        <!-- MW Scale on the right -->
                        <div class="dm-mw-scale-container" id="mw-scale"></div>
                    </div>
                </div>
            `;

            this._setupClickHandlers();
        }

        _setupClickHandlers() {
            const digitalLanesContainer = this.contentElement.querySelector('#digital-lanes');
            if (!digitalLanesContainer || digitalLanesContainer._clickHandlerAttached) return;

            digitalLanesContainer.addEventListener('click', (e) => {
                const bandEl = e.target.closest('.dm-digital-band');

                if (bandEl) {
                    e.stopPropagation();
                    const bandId = bandEl.dataset.bandId;
                    if (bandId && this.state) {
                        this.state.selectBand(bandId);
                    }
                    return;
                }

                // Lane header click → select sample
                const headerEl = e.target.closest('.dm-lane-header');
                if (headerEl) {
                    e.stopPropagation();
                    const sampleId = headerEl.dataset.sampleId;
                    if (sampleId && this.state) {
                        this.state.selectSample(sampleId);
                    }
                    return;
                }

                // Lane column click (anywhere in the column) → select sample
                const columnEl = e.target.closest('.dm-lane-column');
                if (columnEl) {
                    const sampleId = columnEl.dataset.sampleId;
                    if (sampleId && this.state) {
                        this.state.selectSample(sampleId);
                    }
                }
            });

            digitalLanesContainer._clickHandlerAttached = true;
        }

        _setupModeToggle() {
            const header = this.container.querySelector('.dm-panel-header');
            if (!header) return;

            let toggle = header.querySelector('.dm-mode-toggle');
            if (!toggle) {
                // Check if dm-panel-actions already exists (may contain expand button)
                let actions = header.querySelector('.dm-panel-actions');
                const expandBtn = actions?.querySelector('.dm-panel-expand-btn');

                if (!actions) {
                    actions = document.createElement('div');
                    actions.className = 'dm-panel-actions';
                    header.appendChild(actions);
                }

                // Create mode toggle element
                const toggleDiv = document.createElement('div');
                toggleDiv.className = 'dm-mode-toggle';
                toggleDiv.innerHTML = `
                    <button class="dm-mode-btn active" data-mode="bands" data-tooltip="Band view">
                        <i class="bi bi-distribute-vertical"></i>
                    </button>
                    <button class="dm-mode-btn" data-mode="pseudo-gel" data-tooltip="Pseudo-gel view">
                        <i class="bi bi-grip-vertical"></i>
                    </button>
                `;

                // Insert mode toggle BEFORE expand button (so expand stays at the end)
                if (expandBtn) {
                    actions.insertBefore(toggleDiv, expandBtn);
                } else {
                    actions.appendChild(toggleDiv);
                }

                toggle = toggleDiv;
            }

            toggle.querySelectorAll('.dm-mode-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const mode = e.currentTarget.dataset.mode;
                    this._setDigitalLaneMode(mode);

                    toggle.querySelectorAll('.dm-mode-btn').forEach(b => {
                        b.classList.toggle('active', b.dataset.mode === mode);
                    });
                });
            });
        }

        _setupEvents() {
            this.eventBus.on(ComparisonEvents.BAND_SELECTED, (data) => {
                this._onBandSelected(data);
            });

            this.eventBus.on(ComparisonEvents.SAMPLE_SELECTED, (data) => {
                this.currentSampleId = data.sampleId;
                this._renderDigitalLanes();
            });

            this.eventBus.on(ComparisonEvents.DATA_LOADED, () => {
                this._renderDigitalLanes();
            });

            this.eventBus.on(ComparisonEvents.SAMPLE_ADDED, () => {
                this._renderDigitalLanes();
            });

            this.eventBus.on(ComparisonEvents.SAMPLE_REMOVED, () => {
                this._renderDigitalLanes();
            });

            this.eventBus.on(ComparisonEvents.SAMPLE_ORDER_CHANGED, () => {
                this._renderDigitalLanes();
            });
        }

        _onBandSelected(data) {
            this.currentBandId = data.bandId;
            this.currentBand = data.band || null;

            if (data.bandId && data.band) {
                this._renderDigitalLanes();
            }
        }

        _setDigitalLaneMode(mode) {
            this.digitalLaneMode = mode;
            this._renderDigitalLanes();
        }

        _renderDigitalLanes() {
            const lanesContainer = this.contentElement.querySelector('#digital-lanes');
            const mwScaleContainer = this.contentElement.querySelector('#mw-scale');
            if (!lanesContainer) return;

            const samples = this.state.getSamples();

            if (samples.length === 0) {
                lanesContainer.innerHTML = `
                    <div class="dm-lane-placeholder">
                        <i class="bi bi-list-columns"></i>
                        <span>Add samples to compare lanes</span>
                    </div>
                `;
                if (mwScaleContainer) mwScaleContainer.innerHTML = '';
                return;
            }

            // Calculate common MW range across all samples
            const mwRange = this._getCommonMWRange(samples);

            // Render each sample's lane side-by-side
            let html = '<div class="dm-lanes-grid">';

            samples.forEach((sampleData, index) => {
                html += this._renderSingleLaneColumn(sampleData, mwRange, index);
            });

            html += '</div>';
            lanesContainer.innerHTML = html;

            // Attach drag-and-drop reorder to lanes grid
            const lanesGrid = lanesContainer.querySelector('.dm-lanes-grid');
            if (lanesGrid && this.laneReorder) {
                this.laneReorder.container = lanesGrid;
                this.laneReorder.attach();
            }

            // Render shared MW scale
            if (mwScaleContainer && mwRange.minMW < mwRange.maxMW) {
                mwScaleContainer.innerHTML = this._renderSharedMWScale(mwRange);
            }
        }

        _renderSingleLaneColumn(sampleData, mwRange, index) {
            const { sampleId, label, bands, color } = sampleData;
            const isSelected = sampleId === this.state.selectedSampleId;

            if (!bands || bands.length === 0) {
                return `
                    <div class="dm-lane-column ${isSelected ? 'selected' : ''}" data-sample-id="${sampleId}" style="border-top: 3px solid ${color};">
                        <div class="dm-lane-header" data-sample-id="${sampleId}">${label || 'Sample'}</div>
                        <div class="dm-lane-body">
                            <div class="dm-lane-empty">No bands</div>
                        </div>
                    </div>
                `;
            }

            let bandsHtml = '';

            bands.forEach(band => {
                // Position by MW if available
                let topPercent;
                if (band.estimated_mw_kda && mwRange.maxMW > mwRange.minMW) {
                    // Log scale positioning: high MW at top (0%), low MW at bottom (100%)
                    const logMin = Math.log10(mwRange.minMW);
                    const logMax = Math.log10(mwRange.maxMW);
                    const logMW = Math.log10(band.estimated_mw_kda);
                    topPercent = ((logMax - logMW) / (logMax - logMin)) * 100;
                } else {
                    // Fall back to Y position
                    topPercent = 50;
                }

                // Clamp to valid range
                topPercent = Math.max(2, Math.min(98, topPercent));

                const bandColor = this._getBandColor(band.band_type);
                const isSelected = band.id === this.currentBandId;

                let opacity = 0.7;
                if (band.densitometry?.relative_percent_lane) {
                    opacity = Math.max(0.4, Math.min(1, band.densitometry.relative_percent_lane / 40));
                }

                bandsHtml += `
                    <div class="dm-digital-band ${isSelected ? 'selected' : ''}"
                         style="top: ${topPercent}%;
                                background-color: ${bandColor};
                                opacity: ${isSelected ? 1 : opacity};"
                         data-band-id="${band.id}"
                         title="${band.band_type}${band.estimated_mw_kda ? ` (~${band.estimated_mw_kda.toFixed(0)} kDa)` : ''}${band.densitometry?.relative_percent_lane ? ` | ${band.densitometry.relative_percent_lane.toFixed(1)}%` : ''}">
                        ${isSelected ? '<span class="dm-band-marker"></span>' : ''}
                    </div>
                `;
            });

            return `
                <div class="dm-lane-column ${isSelected ? 'selected' : ''}" data-sample-id="${sampleId}" style="border-top: 3px solid ${color};">
                    <div class="dm-lane-header" data-sample-id="${sampleId}">${label || 'Sample'}</div>
                    <div class="dm-lane-body">
                        ${bandsHtml}
                    </div>
                </div>
            `;
        }

        _getCommonMWRange(samples) {
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

            // Add padding
            minMW = minMW * 0.8;
            maxMW = maxMW * 1.2;

            return { minMW, maxMW };
        }

        _renderSharedMWScale(mwRange) {
            const standardMWs = [10, 15, 20, 25, 37, 50, 75, 100, 150, 250];
            const visibleMWs = standardMWs.filter(mw => mw >= mwRange.minMW && mw <= mwRange.maxMW);

            if (visibleMWs.length === 0) return '';

            const logMin = Math.log10(mwRange.minMW);
            const logMax = Math.log10(mwRange.maxMW);

            let html = '<div class="dm-shared-mw-scale">';

            visibleMWs.forEach(mw => {
                const logMW = Math.log10(mw);
                const topPercent = ((logMax - logMW) / (logMax - logMin)) * 100;

                if (topPercent >= 0 && topPercent <= 100) {
                    html += `
                        <div class="dm-mw-tick" style="top: ${topPercent}%;">
                            <span class="dm-mw-line"></span>
                            <span class="dm-mw-value">${mw}</span>
                        </div>
                    `;
                }
            });

            html += '</div>';
            return html;
        }

        _getBandColor(bandType) {
            switch (bandType) {
                case 'POI': return this.colors.poi;
                case 'MW_REFERENCE': return this.colors.mwReference;
                default: return this.colors.other;
            }
        }
    }

    // Export to namespace
    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.Panels = global.SampleComparison.Panels || {};
    global.SampleComparison.Panels.BandDetail = BandDetailPanel;

})(window);
