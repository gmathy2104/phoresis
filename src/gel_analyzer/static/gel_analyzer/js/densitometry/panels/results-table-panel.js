/**
 * Results Table Panel — Densitometry Measurements (per-band, important-only)
 *
 * Phase 7.3: one row per "important" band rather than one row per lane.
 * "Important" = any band whose band_type is not OTHER, i.e. MW_REFERENCE
 * (ladder markers), CALIBRATION (calibration / control points), and POI
 * (samples). This means a SAMPLE lane with three POI bands now produces
 * three measurement rows, one per POI — the lane-per-row shape used to
 * collapse them into a single line which hid the per-band math the user
 * cares about.
 *
 * Columns are grouped via <th colspan> into 4 sections:
 *   - Identity      Lane# | Type | Sample | Band
 *   - Densitometry  Total area | Band area | % lane
 *   - Quantification Estimated amount (+ its calibration-range chip) | Recovery % (CONTROL only)
 *   - Quality       Fit R² | Flag
 *
 * A band the server flags saturated (band.densitometry.saturated) carries a
 * "Saturated" badge in its Band cell; the page's "To check" strip names it too.
 *
 * Clicking a row calls state.selectBand(bandId) — same behaviour as
 * clicking a band on the gel: the parent lane is auto-selected, band
 * detail / gel overview / chromatogram / quantification curve all sync.
 *
 * Subscribes to QUANT_CALIBRATION_CHANGED so the table re-renders after
 * the user saves a new calibration (server-side apply_to_analysis()
 * back-fills estimated_amount during save).
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

    const BAND_TYPE_DISPLAY = {
        POI: 'POI',
        CALIBRATION: 'Calibration',
        MW_REFERENCE: 'Marker',
        OTHER: 'Other',
    };

    // Bands eligible for the table — explicitly excludes OTHER (impurities /
    // unclassified peaks the user told us they don't care about here).
    function _isImportantBand(b) {
        return b && b.band_type && b.band_type !== 'OTHER';
    }

    // Calibration range of an estimated amount — DensitometryResult.CalibrationRange,
    // stored by the server beside the amount (apply_to_analysis). Outside the
    // standards' areas the amount is extrapolated: kept, flagged.
    const CALIBRATION_RANGE = {
        IN_RANGE: { label: 'in range', out: false, title: 'Band area within the calibration standards’ areas' },
        ABOVE_RANGE: { label: 'above range', out: true, title: 'Band area above the largest calibration standard: the amount is extrapolated' },
        BELOW_RANGE: { label: 'below range', out: true, title: 'Band area below the smallest calibration standard: the amount is extrapolated' },
    };

    /** A small chip for a calibration-range code; '' for none or an unknown code. Shared with the quantification modal. */
    function calibrationRangeChip(code) {
        const r = CALIBRATION_RANGE[code];
        if (!r) return '';
        const cls = r.out ? 'dm-range-chip dm-range-chip--out' : 'dm-range-chip dm-range-chip--in';
        return `<span class="${cls}" data-range="${code}" title="${r.title}">${r.out ? '&#9888; ' : ''}${r.label}</span>`;
    }

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

            // Sort state — by lane number then band order within lane.
            this.sortColumn = 'lane_number';
            this.sortDirection = 'asc';

            // Filter state
            this.filterLaneType = null;  // quick filter: e.g. 'CONTROL'

            // Active quantification calibration (or null)
            this.activeCalib = null;

            // Column preset
            let preset = 'standard';
            try {
                const saved = global.localStorage.getItem(PRESET_KEY) || 'standard';
                if (VALID_PRESETS.includes(saved)) preset = saved;
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
                    try {
                        global.localStorage.setItem(PRESET_KEY, v);
                    } catch (_) { /* private window: the preset simply does not persist */ }
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
                    <th colspan="4" class="dm-section-identity">Identity</th>
                    <th colspan="3" class="dm-section-densito">Densitometry</th>
                    <th colspan="2" class="dm-section-quant">Quantification</th>
                    <th colspan="2" class="dm-section-quality">Quality</th>
                </tr>
                <tr>
                    <th class="col-lane">Lane#</th>
                    <th class="col-type">Type</th>
                    <th class="col-sample col-preset-standard">Sample</th>
                    <th class="col-band">Band</th>
                    <th class="col-total-area">Total area</th>
                    <th class="col-band-area">Band area</th>
                    <th class="col-pct-lane col-preset-standard">% lane</th>
                    <th class="col-est-amount">Est. amount</th>
                    <th class="col-recovery col-preset-standard">Recovery %</th>
                    <th class="col-r2 col-preset-standard">Fit R²</th>
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
        // Per-lane totals — used as the % lane denominator. Total area is
        // the sum of all bands in the lane (including OTHER) so the user
        // sees an honest contribution figure.
        // -----------------------------------------------------------------

        _laneTotalArea(lane) {
            const bands = this.state.getBandsForLane(lane.id) || [];
            return bands.reduce((s, b) => s + ((b.densitometry || {}).corrected_area || 0), 0);
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

            // Build (lane, important-band, lane-total) tuples.
            const tuples = [];
            lanes.forEach(lane => {
                const bands = this.state.getBandsForLane(lane.id) || [];
                const important = bands
                    .filter(_isImportantBand)
                    .sort((a, b) => (a.band_number || 0) - (b.band_number || 0));
                if (!important.length) return;
                const totalArea = bands.reduce(
                    (s, b) => s + ((b.densitometry || {}).corrected_area || 0), 0
                );
                important.forEach(band => tuples.push({ lane, band, totalArea }));
            });

            if (tuples.length === 0) {
                tbody.innerHTML = `<tr class="dm-empty-row"><td colspan="11">No important bands to display</td></tr>`;
                this._updateSummary([], 0);
                return;
            }

            tbody.innerHTML = tuples.map(t => this._renderBandRow(t)).join('');

            // Wire row click → select band (cascades to lane / panels / curve).
            tbody.querySelectorAll('tr.dm-band-row').forEach(row => {
                row.addEventListener('click', (e) => {
                    if (e.target.closest('a, button')) return;
                    const bandId = row.dataset.bandId;
                    if (bandId) this.state.selectBand(bandId);
                });
            });

            this._updateSummary(lanes, tuples.length);
        }

        _sortLanes(lanes) {
            const dir = this.sortDirection === 'asc' ? 1 : -1;
            return [...lanes].sort((a, b) => {
                if (a.lane_number < b.lane_number) return -dir;
                if (a.lane_number > b.lane_number) return dir;
                return 0;
            });
        }

        _renderBandRow({ lane, band, totalArea }) {
            const laneType = lane.lane_type || 'SAMPLE';
            const typeLower = laneType.toLowerCase();
            const typeLabel = LANE_TYPE_DISPLAY[laneType] || laneType;
            const tintClass = (laneType === 'CALIBRATION')
                ? 'gv-table-row--calibration'
                : (laneType === 'CONTROL') ? 'gv-table-row--control' : '';

            const bandType = band.band_type || 'OTHER';
            const bandTypeLabel = BAND_TYPE_DISPLAY[bandType] || bandType;
            const bandTypeLower = bandType.toLowerCase();

            const d = band.densitometry || {};
            const bandArea = d.corrected_area || 0;
            const pctLane = totalArea > 0 ? (bandArea / totalArea) * 100 : null;
            const fitR2 = d.fit_r_squared;

            const calibActive = !!this.activeCalib;
            const unit = (this.activeCalib && this.activeCalib.unit === 'UG_ML') ? 'µg/mL' : 'µg';

            // Estimated amount — only meaningful when an active calibration
            // exists (samples + controls), or when the row IS a control
            // calibration band (its known reference is used by recovery).
            let estDisplay = '—';
            if (calibActive && d.estimated_amount != null) {
                estDisplay = `${d.estimated_amount.toFixed(2)} ${unit}${calibrationRangeChip(d.estimated_amount_range)}`;
            }

            // Recovery % — only on CONTROL lanes' calibration band where a
            // known reference (quant_point.load_amount) is set AND a
            // predicted estimated_amount exists.
            let recoveryDisplay = '—';
            let flagHtml = '';
            if (laneType === 'CONTROL' && bandType === 'CALIBRATION') {
                const known = band.quant_point && band.quant_point.load_amount;
                if (known && d.estimated_amount != null) {
                    const pct = (d.estimated_amount / known) * 100;
                    recoveryDisplay = `${pct.toFixed(0)}%`;
                    if (pct < 80 || pct > 120) {
                        flagHtml = '<span class="dm-flag dm-flag-warn" title="Out-of-spec recovery (target 80-120%)">&#9888;</span>';
                    }
                }
            }

            // Band reference cell — band_number with a small type badge.
            // For ladder markers, surface the MW so the user immediately
            // sees which marker this row is.
            const bandRefMain = `B${band.band_number || '?'}`;
            const mwSuffix = (bandType === 'MW_REFERENCE' && band.estimated_mw_kda != null)
                ? ` <span class="dm-band-mw">${Math.round(band.estimated_mw_kda)} kDa</span>`
                : '';
            // Saturation: the server's flag (services/densitometry/saturation.py, its threshold), shown in the
            // Band cell so every column preset carries it. A warning only: the areas are not corrected.
            let saturatedHtml = '';
            if (d.saturated === true) {
                const share = d.saturated_pixel_fraction != null
                    ? `${(d.saturated_pixel_fraction * 100).toFixed(1)} % of its pixels`
                    : 'Its pixels';
                const why = `${share} sit at the end of the image's scale, where the scanner clips: `
                    + 'its area reads too low. Load less or image with a shorter exposure.';
                saturatedHtml = `<span class="dm-saturated-badge" title="${this._escape(why)}">Saturated</span>`;
            }

            const bandRefHtml = `
                ${bandRefMain}
                <span class="gv-prop-type-badge gv-prop-type-${this._escape(bandTypeLower)}">${this._escape(bandTypeLabel)}</span>
                ${mwSuffix}
                ${saturatedHtml}
            `;

            return `
                <tr class="dm-band-row ${tintClass}" data-band-id="${band.id}" data-lane-id="${lane.id}" data-lane-type="${this._escape(laneType)}" data-band-type="${this._escape(bandType)}">
                    <td class="col-lane">${lane.lane_number}</td>
                    <td class="col-type">
                        <span class="gv-prop-type-badge gv-prop-type-${this._escape(typeLower)}">${this._escape(typeLabel)}</span>
                    </td>
                    <td class="col-sample col-preset-standard">${this._escape(lane.sample_name || '')}</td>
                    <td class="col-band">${bandRefHtml}</td>
                    <td class="col-total-area">${this._fmtNum(totalArea, 0)}</td>
                    <td class="col-band-area">${this._fmtNum(bandArea, 0)}</td>
                    <td class="col-pct-lane col-preset-standard">${pctLane != null ? pctLane.toFixed(1) + '%' : '—'}</td>
                    <td class="col-est-amount">${estDisplay}</td>
                    <td class="col-recovery col-preset-standard">${recoveryDisplay}</td>
                    <td class="col-r2 col-preset-standard">${fitR2 != null ? fitR2.toFixed(3) : '—'}</td>
                    <td class="col-flag col-preset-full">${flagHtml}</td>
                </tr>
            `;
        }

        _updateSummary(lanes, importantBandCount) {
            const container = this.contentElement.querySelector('#table-summary');
            if (!container) return;
            const calibActive = !!this.activeCalib;

            container.innerHTML = `
                <div class="dm-summary-stats">
                    <span class="dm-stat">
                        <span class="dm-stat-value">${lanes.length}</span>
                        <span class="dm-stat-label">Lanes</span>
                    </span>
                    <span class="dm-stat">
                        <span class="dm-stat-value">${importantBandCount}</span>
                        <span class="dm-stat-label">Important bands</span>
                    </span>
                    ${calibActive ? `
                        <span class="dm-stat">
                            <span class="dm-stat-value">${this._escape(this.activeCalib.method || '')}</span>
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
            // Lane selection no longer maps 1:1 to a row, but we can dim
            // rows whose lane doesn't match — leave alone for now; the
            // band-level highlight covers the common case (state.selectBand
            // sets selectedLaneId via selectLane internally).
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
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        // -----------------------------------------------------------------
        // Export — one CSV row per important band, mirroring the table.
        // -----------------------------------------------------------------

        exportData() {
            const lanes = this._sortLanes(this.state.getAllLanes());
            const out = [];
            lanes.forEach(lane => {
                const bands = this.state.getBandsForLane(lane.id) || [];
                const totalArea = bands.reduce(
                    (s, b) => s + ((b.densitometry || {}).corrected_area || 0), 0
                );
                const important = bands
                    .filter(_isImportantBand)
                    .sort((a, b) => (a.band_number || 0) - (b.band_number || 0));
                important.forEach(band => {
                    const d = band.densitometry || {};
                    out.push({
                        lane_number: lane.lane_number,
                        lane_type: lane.lane_type,
                        sample_name: lane.sample_name || '',
                        band_id: band.id,
                        band_number: band.band_number,
                        band_type: band.band_type,
                        estimated_mw_kda: band.estimated_mw_kda,
                        total_area: totalArea,
                        band_area: d.corrected_area,
                        pct_lane: totalArea > 0 ? (d.corrected_area || 0) / totalArea * 100 : null,
                        fit_r_squared: d.fit_r_squared,
                        estimated_amount: d.estimated_amount,
                        estimated_amount_range: d.estimated_amount_range,
                        saturated: d.saturated,
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
    global.Densitometry.calibrationRangeChip = calibrationRangeChip;

})(window);
