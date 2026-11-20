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

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    /**
     * BandDetailPanel Class
     */
    class BandDetailPanel extends GelAnalyzer.Viz.Panel {
        constructor(options) {
            super(options);  // sets this.container/eventBus/state/options/tooltipLayer/_disposers

            this.contentElement = null;
            this.currentBandId = null;
            this.currentBand = null;
            this.currentSampleId = null;

            this.digitalLaneMode = 'bands';

            // Day mode (`data-theme="light"` on <html>, set only by hosts that offer it:
            // the PD dashboard) paints the lanes light, so the bands take darker shades of
            // the same hues. Read once: the host rebuilds the panel when the mode switches.
            const day = document.documentElement.getAttribute('data-theme') === 'light';
            this._day = day;
            this.colors = day ? {
                poi: '#9333ea',
                other: '#166534',
                mwReference: '#c2410c',
                calibration: '#f87171',  // red-400 in both modes: the CALIBRATION colour everywhere
            } : {
                poi: '#a855f7',
                other: '#22c55e',
                mwReference: '#f97316',
                calibration: '#f87171',  // Red-400 — CALIBRATION (matches annotation)
            };
        }

        init() {
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
            this._on(ComparisonEvents.BAND_SELECTED, (data) => {
                this._onBandSelected(data);
            });

            this._on(ComparisonEvents.SAMPLE_SELECTED, (data) => {
                this.currentSampleId = data.sampleId;
                this._renderDigitalLanes();
            });

            this._on(ComparisonEvents.DATA_LOADED, () => {
                this._renderDigitalLanes();
            });

            this._on(ComparisonEvents.SAMPLE_ADDED, () => {
                this._renderDigitalLanes();
            });

            this._on(ComparisonEvents.SAMPLE_REMOVED, () => {
                this._renderDigitalLanes();
            });

            this._on(ComparisonEvents.SAMPLE_ORDER_CHANGED, () => {
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

            // Render shared MW scale -- none when no band carries an MW: every band then
            // sits on its own lane's position_y range, which no kDa tick describes.
            if (mwScaleContainer) {
                mwScaleContainer.innerHTML = mwRange
                    ? this._renderSharedMWScale(mwRange)
                    : this._renderNoMWScale();
            }
        }

        _renderSingleLaneColumn(sampleData, mwRange, index) {
            const { sampleId, label, bands, color } = sampleData;
            const isSelected = sampleId === this.state.selectedSampleId;

            if (!bands || bands.length === 0) {
                return `
                    <div class="dm-lane-column ${isSelected ? 'selected' : ''}" data-sample-id="${sampleId}" style="border-top: 3px solid ${color};">
                        <div class="dm-lane-header" data-sample-id="${sampleId}">${escapeHtml(label || 'Sample')}</div>
                        <div class="dm-lane-body">
                            <div class="dm-lane-empty">No bands</div>
                        </div>
                    </div>
                `;
            }

            let bandsHtml = '';

            // For bands without an estimated MW, spread them by their actual gel
            // migration position (position_y) instead of stacking at one spot.
            // Normalized within this lane's own band position_y range.
            const laneYs = bands
                .map(b => b.position_y)
                .filter(y => y !== null && y !== undefined && !isNaN(y));
            const laneMinY = laneYs.length ? Math.min(...laneYs) : 0;
            const laneMaxY = laneYs.length ? Math.max(...laneYs) : 0;

            // Lane is "uncalibrated" when no band carries an estimated MW: bands are
            // then positioned by raw migration distance, not molecular weight.
            const isUncalibrated = !bands.some(b => b.estimated_mw_kda);

            bands.forEach(band => {
                // Position by MW if available
                let topPercent;
                if (band.estimated_mw_kda && mwRange && mwRange.maxMW > mwRange.minMW) {
                    // Log scale positioning: high MW at top (0%), low MW at bottom (100%)
                    const logMin = Math.log10(mwRange.minMW);
                    const logMax = Math.log10(mwRange.maxMW);
                    const logMW = Math.log10(band.estimated_mw_kda);
                    topPercent = ((logMax - logMW) / (logMax - logMin)) * 100;
                } else if (band.position_y !== null && band.position_y !== undefined && laneMaxY > laneMinY) {
                    // No MW: position by actual migration distance (position_y);
                    // larger position_y = further migrated = lower in the lane.
                    topPercent = ((band.position_y - laneMinY) / (laneMaxY - laneMinY)) * 100;
                } else {
                    // No MW and no usable position_y: center as a last resort.
                    topPercent = 50;
                }

                // Clamp to valid range
                topPercent = Math.max(2, Math.min(98, topPercent));

                const bandColor = this._getBandColor(band.band_type);
                const isSelected = band.id === this.currentBandId;
                const pseudo = this.digitalLaneMode === 'pseudo-gel';

                let opacity = 0.7;
                let paint = `background-color: ${bandColor};`;
                if (pseudo) {
                    // Pseudo-gel (the densitometry band zoom's look): a glow in the band's colour on a dark
                    // lane, its intensity on a log scale of the lane share (0-100 % -> 0.3-1).
                    const percent = band.densitometry?.relative_percent_lane;
                    opacity = percent ? 0.3 + (Math.log10(1 + percent) / Math.log10(101)) * 0.7 : 0.6;
                    paint = `background: linear-gradient(to bottom, transparent, ${bandColor} 45%, ${bandColor} 55%, transparent);`;
                } else {
                    if (band.densitometry?.relative_percent_lane) {
                        opacity = Math.max(0.4, Math.min(1, band.densitometry.relative_percent_lane / 40));
                    }
                    // A faint band at 0.4 still reads on a dark lane but fades out on a light
                    // one: by day the same ramp is lifted (0.4 -> 0.61, full stays full).
                    if (this._day) opacity = 0.35 + 0.65 * opacity;
                }

                bandsHtml += `
                    <div class="dm-digital-band ${pseudo ? 'dm-digital-band--pseudo ' : ''}${isSelected ? 'selected' : ''}"
                         style="top: ${topPercent}%;
                                ${paint}
                                opacity: ${isSelected ? 1 : opacity};"
                         data-band-id="${band.id}"
                         title="${escapeHtml(band.band_type)}${band.estimated_mw_kda ? ` (~${band.estimated_mw_kda.toFixed(0)} kDa)` : ''}${band.densitometry?.relative_percent_lane ? ` | ${band.densitometry.relative_percent_lane.toFixed(1)}%` : ''}">
                        ${isSelected ? '<span class="dm-band-marker"></span>' : ''}
                    </div>
                `;
            });

            const uncalWarn = isUncalibrated
                ? ` <i class="bi bi-exclamation-triangle-fill dm-lane-uncal-warn" style="color:#f59e0b;margin-left:3px;cursor:help;font-size:0.85em;" title="No MW calibration — bands positioned by raw migration distance, not molecular weight"></i>`
                : '';

            return `
                <div class="dm-lane-column ${isSelected ? 'selected' : ''}" data-sample-id="${sampleId}" style="border-top: 3px solid ${color};">
                    <div class="dm-lane-header" data-sample-id="${sampleId}">${escapeHtml(label || 'Sample')}${uncalWarn}</div>
                    <div class="dm-lane-body${this.digitalLaneMode === 'pseudo-gel' ? ' dm-lane-body--pseudo' : ''}">
                        ${bandsHtml}
                    </div>
                </div>
            `;
        }

        /** Padded MW range over all samples, or null when no band carries an MW. */
        _getCommonMWRange(samples) {
            // A calibration's template range alone positions no band: without a band
            // MW there is nothing for a kDa scale to describe.
            if (!samples.some(s => s.bands && s.bands.some(b => b.estimated_mw_kda))) return null;

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

        _renderNoMWScale() {
            return `
                <div class="dm-shared-mw-scale">
                    <div class="dm-mw-none" title="No MW calibration — bands positioned by raw migration distance, not molecular weight">No MW<br>calibration</div>
                </div>
            `;
        }

        _getBandColor(bandType) {
            switch (bandType) {
                case 'POI': return this.colors.poi;
                case 'MW_REFERENCE': return this.colors.mwReference;
                case 'CALIBRATION': return this.colors.calibration;
                default: return this.colors.other;
            }
        }
    }

    // Export to namespace
    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.Panels = global.SampleComparison.Panels || {};
    global.SampleComparison.Panels.BandDetail = BandDetailPanel;

})(window);
