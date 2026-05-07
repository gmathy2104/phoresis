/**
 * Results Table Panel — Densitometry Measurements (lane-level)
 *
 * Phase 7.2 refactor: one row per lane (was one row per band) with a
 * click-to-expand drill-down sub-table for the lane's bands. Columns are
 * grouped via <th colspan> into 4 sections:
 *   - Identity      Lane# | Type | Sample
 *   - Densitometry  Total area | # bands | POI area | % purity
 *   - Quantification Estimated amount | Recovery % (CONTROL only)
 *   - Quality       Avg fit R² | Quant residual flag
 *
 * The Quantification group is shown when an active calibration exists OR
 * when the lane is CONTROL. A column-preset selector (minimal / standard /
 * full) hides extra columns; the choice is persisted via safeLocalSet.
 *
 * Subscribes to QUANT_CALIBRATION_CHANGED so the table re-renders after the
 * user saves a new calibration (estimated amounts get back-filled by the
 * server-side apply_to_analysis() during save).
 */

(function (global) {
    'use strict';

    const Events = global.Densitometry.Events;

    const PRESET_KEY = 'phoresis.densito.tablePreset';
    const VALID_PRESETS = ['minimal', 'standard', 'full'];

    // Display labels for lane types — keep in sync with backend Lane.LaneType.
    const LANE_TYPE_DISPLAY = {
        SAMPLE: 'Sample',
        LADDER: 'Ladder',
        EMPTY: 'Empty',
        CONTROL: 'Control',
        CALIBRATION: 'Calibration',
        DOT: 'Dot',
    };

    class ResultsTablePanel {
        /**
         * @param {Object} options
         * @param {HTMLElement} options.container
         * @param {EventBus} options.eventBus
         * @param {State} options.state
         * @param {Object}  [options.apiClient]   - optional, for active-calib lookup
         * @param {string}  [options.analysisId]  - optional
         */
        constructor(options) {
            this.container = options.container;
            this.eventBus = options.eventBus;
            this.state = options.state;
            this.api = options.apiClient || null;
            this.analysisId = options.analysisId || null;

            // Sort state
            this.sortColumn = 'lane_number';
            this.sortDirection = 'asc';

            // Filter state
            this.filterLaneId = null;
            this.filterLaneType = null;  // quick filter: e.g. 'CONTROL'
            this.syncWithLane = false;   // Lane-level table doesn't auto-filter

            // Expanded lanes (drill-down)
            this.expandedLaneIds = new Set();

            // Active quantification calibration (or null)
            this.activeCalib = null;

            // Column preset
            let preset = 'standard';
            try {
                if (typeof safeLocalGet === 'function') {
                    const saved = safeLocalGet(PRESET_KEY, 'standard');
                    if (VALID_PRESETS.includes(saved)) preset = saved;
                }
            } catch (_) { /* ignore */ }
            this.preset = preset;

            // Resize handling
            this.resizeObserver = null;
            this.resizeTimeout = null;

            this._init();
        }

        _init() {
            if (!this.container) {
                console.warn('[ResultsTablePanel] No container element');
                return;
            }
            this.contentElement = this.container.querySelector('.dm-panel-content');
            if (!this.contentElement) {
                console.warn('[ResultsTablePanel] No .dm-panel-content element found');
                this.contentElement = this.container;
            }

            this._createLayout();
            this._setupEvents();
            this._setupResizeObserver();
            this._loadActiveCalibration();
        }

        // -----------------------------------------------------------------
        // Layout
        // -----------------------------------------------------------------

        _createLayout() {
            this.contentElement.innerHTML = `
                <div class="dm-results-container">
                    <div class="dm-quick-filters">
                        <button class="dm-chip active" data-filter="">All</button>
                        <button class="dm-chip" data-filter="SAMPLE">Samples</button>
                        <button class="dm-chip" data-filter="CONTROL">Controls</button>
                        <button class="dm-chip" data-filter="CALIBRATION">Calibration</button>
                        <button class="dm-chip" data-filter="LADDER">Ladders</button>
                    </div>

                    <div class="dm-table-presets">
                        <label for="dm-table-preset">Columns:</label>
                        <select id="dm-table-preset" class="dm-select dm-select-sm">
                            <option value="minimal">Minimal</option>
                            <option value="standard">Standard</option>
                            <option value="full">Full</option>
                        </select>
                    </div>

                    <div class="dm-results-table-wrapper">
                        <table class="dm-table dm-table--lane-level dm-preset-${this.preset}" id="results-table">
                            <thead id="results-thead"></thead>
                            <tbody id="results-tbody"></tbody>
                        </table>
                    </div>

                    <div class="dm-results-footer" id="table-summary"></div>
                </div>
            `;

            this._setupQuickFilters();
            this._setupPresetSelector();
            this._renderHeader();
        }

        _setupQuickFilters() {
            const chips = this.contentElement.querySelectorAll('.dm-chip');
            chips.forEach(chip => {
                chip.addEventListener('click', () => {
                    chips.forEach(c => c.classList.remove('active'));
                    chip.classList.add('active');
                    this.filterLaneType = chip.dataset.filter || null;
                    this._renderTable();
                });
            });
        }

        _setupPresetSelector() {
            const sel = this.contentElement.querySelector('#dm-table-preset');
            if (!sel) return;
            sel.value = this.preset;
            sel.addEventListener('change', (e) => {
                const v = e.target.value;
                if (!VALID_PRESETS.includes(v)) return;
                this.preset = v;
                try {
                    if (typeof safeLocalSet === 'function') safeLocalSet(PRESET_KEY, v);
                } catch (_) { /* ignore */ }
                this._applyPreset();
            });
        }

        _applyPreset() {
            const tbl = this.contentElement.querySelector('#results-table');
            if (!tbl) return;
            VALID_PRESETS.forEach(p => tbl.classList.remove(`dm-preset-${p}`));
            tbl.classList.add(`dm-preset-${this.preset}`);
        }

        _renderHeader() {
            const thead = this.contentElement.querySelector('#results-thead');
            if (!thead) return;
            // 11 data columns total. Top row groups; bottom row labels.
            thead.innerHTML = `
                <tr>
                    <th colspan="3" class="dm-section-identity">Identity</th>
                    <th colspan="4" class="dm-section-densito">Densitometry</th>
                    <th colspan="2" class="dm-section-quant">Quantification</th>
                    <th colspan="2" class="dm-section-quality">Quality</th>
                </tr>
                <tr>
                    <th class="col-lane">Lane#</th>
                    <th class="col-type">Type</th>
                    <th class="col-sample col-preset-standard">Sample</th>
                    <th class="col-total-area">Total area</th>
                    <th class="col-band-count col-preset-standard">#&nbsp;bands</th>
                    <th class="col-poi-area col-preset-full">POI area</th>
                    <th class="col-purity">% purity</th>
                    <th class="col-est-amount">Est. amount</th>
                    <th class="col-recovery col-preset-standard">Recovery %</th>
                    <th class="col-r2 col-preset-standard">Avg fit R²</th>
                    <th class="col-flag col-preset-full">Flag</th>
                </tr>
            `;
        }

        // -----------------------------------------------------------------
        // Events
        // -----------------------------------------------------------------

        _setupEvents() {
            this.eventBus.on(Events.DATA_LOADED, () => {
                this._renderTable();
            });

            this.eventBus.on(Events.DATA_UPDATED, () => {
                this._renderTable();
            });

            this.eventBus.on(Events.LANE_SELECTED, (data) => {
                if (data && data.laneId) this._highlightLane(data.laneId);
            });

            this.eventBus.on(Events.BAND_SELECTED, (data) => {
                if (data && data.bandId) this._highlightBand(data.bandId);
            });

            // Phase 7.2: refresh on calibration change.
            const quantEvent = (Events && Events.QUANT_CALIBRATION_CHANGED) || 'QUANT_CALIBRATION_CHANGED';
            this.eventBus.on(quantEvent, () => {
                this._loadActiveCalibration().then(() => this._renderTable());
            });
        }

        // -----------------------------------------------------------------
        // Active calibration lookup
        // -----------------------------------------------------------------

        async _loadActiveCalibration() {
            if (!this.api || !this.analysisId) return;
            try {
                const meta = await this.api.getActiveQuantification(this.analysisId);
                this.activeCalib = (meta && (meta.active || (meta.data && meta.data.active))) || null;
            } catch (err) {
                console.warn('[ResultsTablePanel] active-calib lookup failed:', err);
                this.activeCalib = null;
            }
            this._renderTable();
        }

        // -----------------------------------------------------------------
        // Per-lane summary
        // -----------------------------------------------------------------

        _summarizeLane(lane) {
            const bands = this.state.getBandsForLane(lane.id);
            let totalArea = 0;
            let poiArea = 0;
            let otherArea = 0;
            let r2Sum = 0;
            let r2Count = 0;
            let estAmountSum = 0;
            let estAmountCount = 0;

            bands.forEach(b => {
                const d = b.densitometry || {};
                const a = d.corrected_area || 0;
                totalArea += a;
                if (b.band_type === 'POI') poiArea += a;
                else if (b.band_type !== 'MW_REFERENCE') otherArea += a;

                if (d.fit_r_squared != null) {
                    r2Sum += d.fit_r_squared;
                    r2Count += 1;
                }
                if (d.estimated_amount != null) {
                    estAmountSum += d.estimated_amount;
                    estAmountCount += 1;
                }
            });

            const purityDenom = poiArea + otherArea;
            const purity = purityDenom > 0 ? (poiArea / purityDenom) * 100 : null;
            const avgR2 = r2Count > 0 ? r2Sum / r2Count : null;

            // Estimated amount for the lane: prefer POI band's estimated_amount,
            // else sum of band-level estimates if any.
            let laneEstAmount = null;
            const poiBand = bands.find(b => b.band_type === 'POI');
            if (poiBand && poiBand.densitometry && poiBand.densitometry.estimated_amount != null) {
                laneEstAmount = poiBand.densitometry.estimated_amount;
            } else if (estAmountCount > 0) {
                laneEstAmount = estAmountSum;
            }

            // Recovery % only meaningful for CONTROL lanes with a known load
            // amount (lane.protein_load_ug) AND an estimated_amount.
            let recoveryPct = null;
            if (lane.lane_type === 'CONTROL' && laneEstAmount != null && lane.protein_load_ug) {
                recoveryPct = (laneEstAmount / lane.protein_load_ug) * 100;
            }

            return {
                bands,
                bandCount: bands.length,
                totalArea,
                poiArea,
                purity,
                avgR2,
                estAmount: laneEstAmount,
                recoveryPct,
            };
        }

        // -----------------------------------------------------------------
        // Render
        // -----------------------------------------------------------------

        _renderTable() {
            const tbody = this.contentElement.querySelector('#results-tbody');
            if (!tbody) return;

            let lanes = this.state.getAllLanes();
            if (this.filterLaneType) {
                lanes = lanes.filter(l => l.lane_type === this.filterLaneType);
            }
            lanes = this._sortLanes(lanes);

            if (lanes.length === 0) {
                tbody.innerHTML = `<tr class="dm-empty-row"><td colspan="11">No lanes to display</td></tr>`;
                this._updateSummary(lanes, []);
                return;
            }

            const rows = [];
            const allSummaries = [];
            lanes.forEach(lane => {
                const summary = this._summarizeLane(lane);
                allSummaries.push({ lane, summary });
                rows.push(this._renderLaneRow(lane, summary));
                if (this.expandedLaneIds.has(lane.id)) {
                    rows.push(this._renderDrillDownRow(lane, summary));
                }
            });

            tbody.innerHTML = rows.join('');

            // Wire row click → toggle drill-down
            tbody.querySelectorAll('tr.dm-lane-row').forEach(row => {
                row.addEventListener('click', (e) => {
                    // Ignore clicks on inner buttons/links inside the row
                    if (e.target.closest('a, button')) return;
                    const laneId = row.dataset.laneId;
                    if (!laneId) return;
                    if (this.expandedLaneIds.has(laneId)) {
                        this.expandedLaneIds.delete(laneId);
                    } else {
                        this.expandedLaneIds.add(laneId);
                    }
                    this.state.selectLane(laneId);
                    this._renderTable();
                });
            });

            // Wire band-row click in any open drill-down
            tbody.querySelectorAll('tr.dm-band-row').forEach(row => {
                row.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const bandId = row.dataset.bandId;
                    if (bandId) this.state.selectBand(bandId);
                });
            });

            this._updateSummary(lanes, allSummaries);
        }

        _sortLanes(lanes) {
            const dir = this.sortDirection === 'asc' ? 1 : -1;
            return [...lanes].sort((a, b) => {
                const aVal = a.lane_number;
                const bVal = b.lane_number;
                if (aVal < bVal) return -dir;
                if (aVal > bVal) return dir;
                return 0;
            });
        }

        _renderLaneRow(lane, summary) {
            const laneType = lane.lane_type || 'SAMPLE';
            const typeLower = laneType.toLowerCase();
            const typeLabel = LANE_TYPE_DISPLAY[laneType] || laneType;
            const tintClass = (laneType === 'CALIBRATION')
                ? 'gv-table-row--calibration'
                : (laneType === 'CONTROL') ? 'gv-table-row--control' : '';

            const calibActive = !!this.activeCalib;
            const showQuantValue = calibActive || laneType === 'CONTROL';

            // Estimated amount
            let estAmountDisplay = '—';
            if (showQuantValue && summary.estAmount != null) {
                const unit = (this.activeCalib && this.activeCalib.unit === 'UG_ML') ? 'µg/mL' : 'µg';
                estAmountDisplay = `${summary.estAmount.toFixed(2)} ${unit}`;
            }

            // Recovery %
            let recoveryDisplay = '—';
            if (laneType === 'CONTROL' && summary.recoveryPct != null) {
                recoveryDisplay = `${summary.recoveryPct.toFixed(0)}%`;
            }

            // Out-of-spec flag
            let flagHtml = '';
            if (laneType === 'CONTROL' && summary.recoveryPct != null
                && (summary.recoveryPct < 80 || summary.recoveryPct > 120)) {
                flagHtml = '<span class="dm-flag dm-flag-warn" title="Out-of-spec recovery (target 80-120%)">&#9888;</span>';
            }

            const isExpanded = this.expandedLaneIds.has(lane.id);
            const expandIcon = isExpanded ? '&#9660;' : '&#9654;';

            return `
                <tr class="dm-lane-row ${tintClass}" data-lane-id="${lane.id}" data-lane-type="${laneType}">
                    <td class="col-lane dm-sticky-left">
                        <span class="dm-expand-icon">${expandIcon}</span> ${lane.lane_number}
                    </td>
                    <td class="col-type dm-sticky-left">
                        <span class="gv-prop-type-badge gv-prop-type-${typeLower}">${typeLabel}</span>
                    </td>
                    <td class="col-sample col-preset-standard">${this._escape(lane.sample_name || '')}</td>
                    <td class="col-total-area">${this._fmtNum(summary.totalArea, 0)}</td>
                    <td class="col-band-count col-preset-standard">${summary.bandCount}</td>
                    <td class="col-poi-area col-preset-full">${this._fmtNum(summary.poiArea, 0)}</td>
                    <td class="col-purity">${summary.purity != null ? summary.purity.toFixed(1) + '%' : '—'}</td>
                    <td class="col-est-amount">${estAmountDisplay}</td>
                    <td class="col-recovery col-preset-standard">${recoveryDisplay}</td>
                    <td class="col-r2 col-preset-standard">${summary.avgR2 != null ? summary.avgR2.toFixed(3) : '—'}</td>
                    <td class="col-flag col-preset-full">${flagHtml}</td>
                </tr>
            `;
        }

        _renderDrillDownRow(lane, summary) {
            const calibActive = !!this.activeCalib;
            const unit = (this.activeCalib && this.activeCalib.unit === 'UG_ML') ? 'µg/mL' : 'µg';

            const totalArea = summary.totalArea || 0;
            const rows = summary.bands.map(b => {
                const d = b.densitometry || {};
                const ba = d.corrected_area || 0;
                const pctLane = totalArea > 0 ? (ba / totalArea) * 100 : null;
                const typeLower = (b.band_type || 'OTHER').toLowerCase();
                const typeLabel = b.band_type || 'OTHER';
                const estCell = (calibActive && d.estimated_amount != null)
                    ? `${d.estimated_amount.toFixed(2)} ${unit}`
                    : '—';
                return `
                    <tr class="dm-band-row" data-band-id="${b.id}">
                        <td>${b.band_number || ''}</td>
                        <td>${b.estimated_mw_kda != null ? Math.round(b.estimated_mw_kda) : '—'}</td>
                        <td><span class="gv-prop-type-badge gv-prop-type-${typeLower}">${typeLabel}</span></td>
                        <td>${this._fmtNum(ba, 0)}</td>
                        <td>${pctLane != null ? pctLane.toFixed(1) + '%' : '—'}</td>
                        <td>${estCell}</td>
                    </tr>
                `;
            }).join('');

            return `
                <tr class="dm-lane-subrow" data-parent-lane-id="${lane.id}">
                    <td colspan="11">
                        <table class="dm-lane-subtable">
                            <thead>
                                <tr>
                                    <th>Band#</th>
                                    <th>MW (kDa)</th>
                                    <th>Type</th>
                                    <th>Corrected area</th>
                                    <th>% lane</th>
                                    <th>Est. amount</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${rows || '<tr><td colspan="6" style="text-align:center;color:#888;">No bands in this lane</td></tr>'}
                            </tbody>
                        </table>
                    </td>
                </tr>
            `;
        }

        _updateSummary(lanes, summaries) {
            const container = this.contentElement.querySelector('#table-summary');
            if (!container) return;
            const totalLanes = lanes.length;
            const totalBands = summaries.reduce((s, x) => s + x.summary.bandCount, 0);
            const purities = summaries
                .map(x => x.summary.purity)
                .filter(p => p != null);
            const avgPurity = purities.length
                ? purities.reduce((s, p) => s + p, 0) / purities.length
                : null;
            const calibActive = !!this.activeCalib;

            container.innerHTML = `
                <div class="dm-summary-stats">
                    <span class="dm-stat">
                        <span class="dm-stat-value">${totalLanes}</span>
                        <span class="dm-stat-label">Lanes</span>
                    </span>
                    <span class="dm-stat">
                        <span class="dm-stat-value">${totalBands}</span>
                        <span class="dm-stat-label">Bands</span>
                    </span>
                    ${avgPurity != null ? `
                        <span class="dm-stat dm-stat-purity">
                            <span class="dm-stat-value">${avgPurity.toFixed(1)}%</span>
                            <span class="dm-stat-label">Avg purity</span>
                        </span>
                    ` : ''}
                    ${calibActive ? `
                        <span class="dm-stat">
                            <span class="dm-stat-value">${this.activeCalib.method || ''}</span>
                            <span class="dm-stat-label">Active calib</span>
                        </span>
                    ` : ''}
                </div>
            `;
        }

        // -----------------------------------------------------------------
        // Highlight helpers
        // -----------------------------------------------------------------

        _highlightLane(laneId) {
            this.contentElement.querySelectorAll('tr.dm-lane-row.selected').forEach(r => r.classList.remove('selected'));
            const row = this.contentElement.querySelector(`tr.dm-lane-row[data-lane-id="${laneId}"]`);
            if (row) {
                row.classList.add('selected');
                row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        }

        _highlightBand(bandId) {
            this.contentElement.querySelectorAll('tr.dm-band-row.selected').forEach(r => r.classList.remove('selected'));
            const row = this.contentElement.querySelector(`tr.dm-band-row[data-band-id="${bandId}"]`);
            if (row) {
                row.classList.add('selected');
                row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        }

        // -----------------------------------------------------------------
        // Utils
        // -----------------------------------------------------------------

        _fmtNum(v, digits) {
            if (v == null || !isFinite(v)) return '—';
            const d = digits != null ? digits : 1;
            if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(1) + 'M';
            if (Math.abs(v) >= 1e3) return (v / 1e3).toFixed(1) + 'K';
            return v.toFixed(d);
        }

        _escape(s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        }

        // -----------------------------------------------------------------
        // Export (used by the CSV export button)
        // -----------------------------------------------------------------

        exportData() {
            const lanes = this._sortLanes(this.state.getAllLanes());
            const out = [];
            lanes.forEach(lane => {
                const summary = this._summarizeLane(lane);
                summary.bands.forEach(b => {
                    out.push({
                        lane_number: lane.lane_number,
                        lane_type: lane.lane_type,
                        sample_name: lane.sample_name || '',
                        band_id: b.id,
                        band_type: b.band_type,
                        position_y: b.position_y,
                        estimated_mw_kda: b.estimated_mw_kda,
                        corrected_area: (b.densitometry || {}).corrected_area,
                        relative_percent_lane: (b.densitometry || {}).relative_percent_lane,
                        fit_r_squared: (b.densitometry || {}).fit_r_squared,
                        estimated_amount: (b.densitometry || {}).estimated_amount,
                    });
                });
            });
            return out;
        }

        // -----------------------------------------------------------------
        // Resize observer
        // -----------------------------------------------------------------

        _setupResizeObserver() {
            if (this.resizeObserver) this.resizeObserver.disconnect();
            this.resizeObserver = new ResizeObserver(() => {
                if (this.resizeTimeout) cancelAnimationFrame(this.resizeTimeout);
                this.resizeTimeout = requestAnimationFrame(() => this._handleResize());
            });
            this.resizeObserver.observe(this.contentElement);
        }

        _handleResize() {
            const rect = this.contentElement.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) return;
            // CSS handles layout — nothing to recompute.
        }

        destroy() {
            if (this.resizeObserver) {
                this.resizeObserver.disconnect();
                this.resizeObserver = null;
            }
            if (this.resizeTimeout) {
                cancelAnimationFrame(this.resizeTimeout);
                this.resizeTimeout = null;
            }
        }
    }

    global.Densitometry = global.Densitometry || {};
    global.Densitometry.ResultsTablePanel = ResultsTablePanel;

})(window);
