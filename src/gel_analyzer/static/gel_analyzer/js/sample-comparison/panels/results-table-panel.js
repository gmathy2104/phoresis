/**
 * Comparison Results Table Panel — per-band, important-only.
 *
 * Phase 8.2: one row per *important* band rather than one row per lane,
 * mirroring the densitometry results-table-panel refactor. "Important"
 * = any band whose band_type is not OTHER (CALIBRATION / POI /
 * MW_REFERENCE). A sample lane with three POI bands now produces three
 * comparison rows so the per-band math is visible instead of being
 * collapsed into a lane summary.
 *
 * Columns are grouped via <th colspan> into 4 sections:
 *   - Identity      Lane# | Type | Sample | Band
 *   - Densitometry  Total area | Band area | % lane
 *   - Quantification Est. amount | Recovery % (CONTROL only) | Calib method
 *   - Quality       Fit R² | Flag
 *
 * Clicking a row calls state.selectBand(bandId) — the comparison state
 * auto-selects the parent sample and emits BAND_SELECTED + SAMPLE_SELECTED,
 * so the band detail / gel overview / chromatogram / POI / content panels
 * all sync the same way they do for a real gel-band click.
 *
 * Toolbar:
 *   - "Show only quantified bands" filter (toggles row visibility based
 *     on whether the band has a non-null estimated_amount)
 *   - Column preset selector (minimal | standard | full), persisted via
 *     safeLocalSet under `phoresis.compare.tableColumns`.
 *
 * The Quantification group is hidden when no compared analysis has an
 * active calibration AND no band has an estimated_amount.
 */

(function(global) {
    'use strict';

    const ComparisonEvents = global.SampleComparison?.Events;

    const PRESET_KEY = 'phoresis.compare.tableColumns';
    const VALID_PRESETS = ['minimal', 'standard', 'full'];

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

    function _isImportantBand(b) {
        return b && b.band_type && b.band_type !== 'OTHER';
    }

    class ComparisonResultsTablePanel {
        constructor(options) {
            this.container = options.container;
            this.eventBus = options.eventBus;
            this.state = options.state;

            this.contentElement = null;
            this.table = null;
            this.thead = null;
            this.tbody = null;

            this.sortDir = 'asc';

            // Filters
            this.onlyQuantified = false;

            // Column preset (persisted)
            let preset = 'standard';
            try {
                if (typeof safeLocalGet === 'function') {
                    const saved = safeLocalGet(PRESET_KEY, 'standard');
                    if (VALID_PRESETS.includes(saved)) preset = saved;
                }
            } catch (_) { /* ignore */ }
            this.preset = preset;

            this._init();
        }

        _init() {
            if (!this.container) return;

            this.contentElement = this.container.querySelector('.dm-panel-content');
            if (!this.contentElement) {
                this.contentElement = this.container;
            }

            this._createLayout();
            this._setupEvents();
            this._render();
        }

        _setupEvents() {
            this.eventBus.on(ComparisonEvents.DATA_LOADED, () => this._render());
            this.eventBus.on(ComparisonEvents.SAMPLE_ADDED, () => this._render());
            this.eventBus.on(ComparisonEvents.SAMPLE_REMOVED, () => this._render());
            this.eventBus.on(ComparisonEvents.SAMPLE_ORDER_CHANGED, () => this._render());
            this.eventBus.on(ComparisonEvents.BAND_SELECTED, (data) => {
                if (data && data.bandId) this._highlightBand(data.bandId);
            });
        }

        // -----------------------------------------------------------------
        // Layout
        // -----------------------------------------------------------------

        _createLayout() {
            this.contentElement.innerHTML = `
                <div class="cmp-results-container">
                    <div class="cmp-toolbar">
                        <label class="cmp-toolbar-filter">
                            <input type="checkbox" id="cmp-only-quant">
                            Show only quantified bands
                        </label>
                        <div class="cmp-toolbar-presets">
                            <label for="cmp-table-preset">Columns:</label>
                            <select id="cmp-table-preset" class="dm-select dm-select-sm">
                                <option value="minimal">Minimal</option>
                                <option value="standard">Standard</option>
                                <option value="full">Full</option>
                            </select>
                        </div>
                    </div>
                    <div class="cmp-results-table-wrapper">
                        <table class="dm-table dm-table--lane-level cmp-comparison-table cmp-preset-${this.preset}" id="cmp-results-table">
                            <thead id="cmp-results-thead"></thead>
                            <tbody id="cmp-results-tbody"></tbody>
                        </table>
                    </div>
                </div>
            `;

            this.table = this.contentElement.querySelector('#cmp-results-table');
            this.thead = this.contentElement.querySelector('#cmp-results-thead');
            this.tbody = this.contentElement.querySelector('#cmp-results-tbody');

            this._setupToolbar();
            this._renderHeader();
        }

        _setupToolbar() {
            const onlyQuant = this.contentElement.querySelector('#cmp-only-quant');
            if (onlyQuant) {
                onlyQuant.checked = this.onlyQuantified;
                onlyQuant.addEventListener('change', (e) => {
                    this.onlyQuantified = e.target.checked;
                    this._applyOnlyQuantFilter();
                });
            }

            const presetSel = this.contentElement.querySelector('#cmp-table-preset');
            if (presetSel) {
                presetSel.value = this.preset;
                presetSel.addEventListener('change', (e) => {
                    const v = e.target.value;
                    if (!VALID_PRESETS.includes(v)) return;
                    this.preset = v;
                    try {
                        if (typeof safeLocalSet === 'function') safeLocalSet(PRESET_KEY, v);
                    } catch (_) { /* ignore */ }
                    this._applyPreset();
                });
            }
        }

        _applyPreset() {
            if (!this.table) return;
            VALID_PRESETS.forEach(p => this.table.classList.remove(`cmp-preset-${p}`));
            this.table.classList.add(`cmp-preset-${this.preset}`);
        }

        _renderHeader() {
            if (!this.thead) return;
            // 11 data columns total. Top row groups; bottom row labels.
            this.thead.innerHTML = `
                <tr class="cmp-section-row">
                    <th colspan="4" class="cmp-section-identity">Identity</th>
                    <th colspan="3" class="cmp-section-densito">Densitometry</th>
                    <th colspan="2" class="cmp-section-quant" id="cmp-quant-header">Quantification</th>
                    <th colspan="2" class="cmp-section-quality">Quality</th>
                </tr>
                <tr class="cmp-column-row">
                    <th class="col-lane">Lane#</th>
                    <th class="col-type">Type</th>
                    <th class="col-sample col-preset-standard">Sample</th>
                    <th class="col-band">Band</th>
                    <th class="col-total-area">Total area</th>
                    <th class="col-band-area">Band area</th>
                    <th class="col-pct-lane col-preset-standard">% lane</th>
                    <th class="cmp-section-quant col-est-amount">Est. amount</th>
                    <th class="cmp-section-quant col-recovery col-preset-standard">Recovery %</th>
                    <th class="col-r2 col-preset-standard">Fit R²</th>
                    <th class="col-flag col-preset-full">Flag</th>
                </tr>
            `;
        }

        // -----------------------------------------------------------------
        // Render
        // -----------------------------------------------------------------

        _render() {
            if (!this.tbody) return;

            const samples = this.state.getSamples();
            if (samples.length === 0) {
                this.tbody.innerHTML = `
                    <tr class="dm-empty-row">
                        <td colspan="11">
                            <div class="dm-placeholder">
                                <i class="bi bi-table"></i>
                                <span>No samples to compare</span>
                            </div>
                        </td>
                    </tr>
                `;
                this._updateQuantHeaderVisibility(false);
                return;
            }

            // Sort samples by lane number for stable display order.
            const sortedSamples = [...samples].sort((a, b) => {
                const an = a.lane?.lane_number || 0;
                const bn = b.lane?.lane_number || 0;
                return this.sortDir === 'asc' ? an - bn : bn - an;
            });

            // Build (sample, important-band, lane-total) tuples; one row per band.
            const tuples = [];
            sortedSamples.forEach(sample => {
                const bands = sample.bands || [];
                const totalArea = bands.reduce(
                    (s, b) => s + ((b.densitometry || {}).corrected_area || 0), 0
                );
                const important = bands
                    .filter(_isImportantBand)
                    .sort((a, b) => (a.band_number || 0) - (b.band_number || 0));
                if (!important.length) return;
                important.forEach(band => tuples.push({ sample, band, totalArea }));
            });

            if (tuples.length === 0) {
                this.tbody.innerHTML = `
                    <tr class="dm-empty-row">
                        <td colspan="11">
                            <div class="dm-placeholder">
                                <i class="bi bi-table"></i>
                                <span>No important bands across the loaded samples</span>
                            </div>
                        </td>
                    </tr>
                `;
                this._updateQuantHeaderVisibility(false);
                return;
            }

            // Show the Quantification group when any tuple has an active
            // calibration on its parent analysis OR any band has an
            // estimated amount (server-side back-fill).
            const anyQuant = tuples.some(t =>
                (t.sample.analysis && t.sample.analysis.active_quant_calibration)
                || (t.band.densitometry && t.band.densitometry.estimated_amount != null)
            );
            this._updateQuantHeaderVisibility(anyQuant);

            this.tbody.innerHTML = tuples.map(t => this._renderBandRow(t)).join('');

            // Wire row click → select band (cascades through state.selectBand).
            this.tbody.querySelectorAll('tr.cmp-band-row').forEach(row => {
                row.addEventListener('click', (e) => {
                    if (e.target.closest('a, button')) return;
                    const bandId = row.dataset.bandId;
                    if (bandId) this.state.selectBand(bandId);
                });
                row.style.cursor = 'pointer';
            });

            // Apply current filter
            this._applyOnlyQuantFilter();
        }

        _updateQuantHeaderVisibility(visible) {
            const header = this.thead?.querySelector('#cmp-quant-header');
            if (header) header.style.display = visible ? '' : 'none';
            if (this.table) {
                this.table.querySelectorAll('.cmp-section-quant').forEach(el => {
                    el.style.display = visible ? '' : 'none';
                });
            }
        }

        _renderBandRow({ sample, band, totalArea }) {
            const lane = sample.lane || {};
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

            const calib = sample.analysis?.active_quant_calibration || null;
            const calibActive = !!calib;
            const calibUnit = calib && calib.unit;

            // Estimated amount — show when the band has one (server back-fills
            // the value during apply_to_analysis once a calibration is active).
            let estDisplay = '—';
            if (d.estimated_amount != null) {
                const unit = this._formatUnit(d.estimated_amount_unit || calibUnit);
                estDisplay = `${d.estimated_amount.toFixed(2)} ${unit}`;
            }

            // Recovery % + flag — only on CONTROL lanes' calibration band where
            // a known reference (quant_point.load_amount) exists AND the
            // server emitted an estimated amount on the band.
            let recoveryDisplay = '—';
            let flagHtml = '';
            if (laneType === 'CONTROL' && bandType === 'CALIBRATION') {
                const known = band.quant_point && band.quant_point.load_amount;
                if (known && d.estimated_amount != null) {
                    const pct = (d.estimated_amount / known) * 100;
                    recoveryDisplay = `${pct.toFixed(0)}%`;
                    if (pct < 80 || pct > 120) {
                        flagHtml = '<span class="cmp-status cmp-status-warn" title="Out-of-spec recovery (target 80-120%)">&#9888;</span>';
                    }
                }
            }

            const sampleName = this._escape(lane.sample_name || sample.label || '');
            const bandRefMain = `B${band.band_number || '?'}`;
            const mwSuffix = (bandType === 'MW_REFERENCE' && band.estimated_mw_kda != null)
                ? ` <span class="cmp-band-mw">${Math.round(band.estimated_mw_kda)} kDa</span>`
                : '';
            const bandRefHtml = `
                ${bandRefMain}
                <span class="gv-prop-type-badge gv-prop-type-${bandTypeLower}">${bandTypeLabel}</span>
                ${mwSuffix}
            `;

            // data-estimated-amount drives the "Show only quantified bands"
            // filter — set the dataset attribute only when the band has a
            // predicted estimated amount.
            const dataEstAttr = d.estimated_amount != null
                ? `data-estimated-amount="${d.estimated_amount}"`
                : '';

            return `
                <tr class="cmp-band-row ${tintClass}"
                    data-band-id="${band.id}"
                    data-sample-id="${sample.sampleId}"
                    data-lane-id="${lane.id || ''}"
                    data-lane-type="${laneType}"
                    data-band-type="${bandType}"
                    ${dataEstAttr}
                    style="border-left: 3px solid ${sample.color || 'transparent'};">
                    <td class="col-lane">${lane.lane_number != null ? lane.lane_number : ''}</td>
                    <td class="col-type">
                        <span class="gv-prop-type-badge gv-prop-type-${typeLower}">${typeLabel}</span>
                    </td>
                    <td class="col-sample col-preset-standard">${sampleName || '<span class="cmp-muted">—</span>'}</td>
                    <td class="col-band">${bandRefHtml}</td>
                    <td class="col-total-area">${this._fmtNum(totalArea, 0)}</td>
                    <td class="col-band-area">${this._fmtNum(bandArea, 0)}</td>
                    <td class="col-pct-lane col-preset-standard">${pctLane != null ? pctLane.toFixed(1) + '%' : '—'}</td>
                    <td class="cmp-section-quant col-est-amount">${estDisplay}</td>
                    <td class="cmp-section-quant col-recovery col-preset-standard">${recoveryDisplay}</td>
                    <td class="col-r2 col-preset-standard">${fitR2 != null ? fitR2.toFixed(3) : '—'}</td>
                    <td class="col-flag col-preset-full">${flagHtml}</td>
                </tr>
            `;
        }

        // -----------------------------------------------------------------
        // Filter handlers
        // -----------------------------------------------------------------

        _applyOnlyQuantFilter() {
            if (!this.table) return;
            const filter = this.onlyQuantified;
            this.table.querySelectorAll('tr.cmp-band-row').forEach(r => {
                const hasEst = r.dataset.estimatedAmount != null && r.dataset.estimatedAmount !== '';
                r.hidden = filter && !hasEst;
            });
        }

        // -----------------------------------------------------------------
        // Highlight
        // -----------------------------------------------------------------

        _highlightBand(bandId) {
            if (!this.tbody) return;
            this.tbody.querySelectorAll('tr.cmp-band-row.selected').forEach(r => r.classList.remove('selected'));
            if (!bandId) return;
            const row = this.tbody.querySelector(`tr.cmp-band-row[data-band-id="${bandId}"]`);
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

        _formatUnit(unit) {
            if (unit === 'UG_ML' || unit === 'µg/mL') return 'µg/mL';
            return 'µg';
        }

        _escape(s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        }
    }

    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.Panels = global.SampleComparison.Panels || {};
    global.SampleComparison.Panels.ResultsTable = ComparisonResultsTablePanel;

})(window);
