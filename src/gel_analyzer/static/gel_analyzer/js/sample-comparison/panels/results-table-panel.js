/**
 * Comparison Results Table Panel — lane-level (Phase 8.1 refactor).
 *
 * One row per compared lane. Columns are split into 4 groups via <th colspan>:
 *   - Identity      Lane# | Type (badge) | Sample | Condition | Loading µg | Loading µL
 *   - Densitometry  Total area | # bands | POI area | % purity
 *   - Quantification (HIDDEN unless any compared analysis has an active calibration):
 *                   Estimated amount + unit | %Recovery (CONTROL only) | Calib method
 *   - Quality       Avg fit R² | # MW markers | Status icon
 *
 * Lane# + Type are sticky-left (CSS .cmp-sticky-left). Rows are tinted by lane
 * type using existing classes from gel_viewer_standalone.css
 * (`gv-table-row--calibration`, `gv-table-row--control`).
 *
 * Toolbar:
 *   - "Show only quantified lanes" filter (toggles row visibility based on
 *     whether the lane has a non-null estimated amount)
 *   - Column preset selector (minimal | standard | full), persisted via
 *     safeLocalSet under `phoresis.compare.tableColumns`.
 *
 * CONTROL-recovery semantics match Phase 7's results-table fix: the known
 * amount comes from the CONTROL lane's CALIBRATION-typed band's
 * quant_point.load_amount; the predicted comes from that band's
 * densitometry.estimated_amount. protein_load_ug is loading-metadata only.
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

    class ComparisonResultsTablePanel {
        constructor(options) {
            this.container = options.container;
            this.eventBus = options.eventBus;
            this.state = options.state;

            this.contentElement = null;
            this.table = null;
            this.thead = null;
            this.tbody = null;

            this.sortField = 'lane_number';
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
            this.eventBus.on(ComparisonEvents.SAMPLE_SELECTED, (data) => this._highlightLane(data?.sampleId));
            this.eventBus.on(ComparisonEvents.BAND_SELECTED, (data) => {
                if (data && data.sampleId) this._highlightLane(data.sampleId);
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
                            Show only quantified lanes
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

            // Identity has 4 visible columns by default (Sample, Condition,
            // Loading µg, Loading µL). The Loading µL column is hidden when no
            // sample uses it, but we keep the colspan stable to keep
            // header alignment simple.
            this.thead.innerHTML = `
                <tr class="cmp-section-row">
                    <th colspan="2" class="cmp-sticky-left">&nbsp;</th>
                    <th colspan="4" class="cmp-section-identity">Identity</th>
                    <th colspan="4" class="cmp-section-densito">Densitometry</th>
                    <th colspan="3" class="cmp-section-quant" id="cmp-quant-header">Quantification</th>
                    <th colspan="3" class="cmp-section-quality">Quality</th>
                </tr>
                <tr class="cmp-column-row">
                    <th class="cmp-sticky-left col-lane">Lane#</th>
                    <th class="cmp-sticky-left col-type">Type</th>
                    <th class="col-sample">Sample</th>
                    <th class="col-condition col-preset-standard">Condition</th>
                    <th class="col-load-ug">Loading (µg)</th>
                    <th class="col-load-ul col-preset-full" id="cmp-col-load-ul">Loading (µL)</th>
                    <th class="col-total-area">Total area</th>
                    <th class="col-band-count col-preset-standard"># bands</th>
                    <th class="col-poi-area col-preset-full">POI area</th>
                    <th class="col-purity">% purity</th>
                    <th class="cmp-section-quant col-est-amount">Est. amount</th>
                    <th class="cmp-section-quant col-recovery col-preset-standard">%Rec</th>
                    <th class="cmp-section-quant col-calib-method col-preset-full">Calib method</th>
                    <th class="col-r2 col-preset-standard">Avg fit R²</th>
                    <th class="col-mw-markers col-preset-full"># MW markers</th>
                    <th class="col-status">Status</th>
                </tr>
            `;
        }

        // -----------------------------------------------------------------
        // Per-lane summary
        // -----------------------------------------------------------------

        _summarizeLane(sample) {
            const lane = sample.lane || {};
            const bands = sample.bands || [];

            // Prefer the persisted lane-level summary fields; fall back to
            // computing them from the bands list when missing.
            const dlane = sample.densitometry || {};
            let totalArea = dlane.total_integrated_area;
            let poiArea = dlane.poi_integrated_area;
            let purity = dlane.poi_percentage;
            let bandCount = dlane.band_count != null ? dlane.band_count : bands.length;

            let r2Sum = 0;
            let r2Count = 0;
            let estAmountSum = 0;
            let estAmountCount = 0;

            if (totalArea == null || poiArea == null) {
                let _total = 0;
                let _poi = 0;
                let _other = 0;
                bands.forEach(b => {
                    const d = b.densitometry || {};
                    const a = d.corrected_area || 0;
                    _total += a;
                    if (b.band_type === 'POI') _poi += a;
                    else if (b.band_type !== 'MW_REFERENCE') _other += a;
                });
                if (totalArea == null) totalArea = _total;
                if (poiArea == null) poiArea = _poi;
                if (purity == null) {
                    const denom = _poi + _other;
                    purity = denom > 0 ? (_poi / denom) * 100 : null;
                }
            }

            bands.forEach(b => {
                const d = b.densitometry || {};
                if (d.fit_r_squared != null) {
                    r2Sum += d.fit_r_squared;
                    r2Count += 1;
                }
                if (d.estimated_amount != null) {
                    estAmountSum += d.estimated_amount;
                    estAmountCount += 1;
                }
            });

            const avgR2 = r2Count > 0 ? r2Sum / r2Count : null;

            // CONTROL recovery semantics (Phase 7 fix): known amount lives on
            // the CONTROL lane's CALIBRATION band's quant_point.load_amount;
            // predicted lives on that same band's densitometry.estimated_amount.
            // SAMPLE lanes show the POI band's predicted amount.
            // protein_load_ug is loading metadata only and does NOT feed the
            // recovery math.
            let laneEstAmount = null;
            let laneEstUnit = null;
            let knownAmount = null;
            let knownUnit = null;

            if (lane.lane_type === 'CONTROL') {
                const ctrlBand = bands.find(b =>
                    b.band_type === 'CALIBRATION' && b.quant_point && b.quant_point.load_amount != null
                );
                if (ctrlBand) {
                    knownAmount = ctrlBand.quant_point.load_amount;
                    knownUnit = ctrlBand.quant_point.load_unit;
                    if (ctrlBand.densitometry && ctrlBand.densitometry.estimated_amount != null) {
                        laneEstAmount = ctrlBand.densitometry.estimated_amount;
                        laneEstUnit = ctrlBand.densitometry.estimated_amount_unit;
                    }
                }
            } else {
                const poiBand = bands.find(b => b.band_type === 'POI');
                if (poiBand && poiBand.densitometry && poiBand.densitometry.estimated_amount != null) {
                    laneEstAmount = poiBand.densitometry.estimated_amount;
                    laneEstUnit = poiBand.densitometry.estimated_amount_unit;
                } else if (estAmountCount > 0) {
                    laneEstAmount = estAmountSum;
                }
            }

            let recoveryPct = null;
            if (lane.lane_type === 'CONTROL' && laneEstAmount != null && knownAmount) {
                recoveryPct = (laneEstAmount / knownAmount) * 100;
            }

            return {
                bands,
                bandCount,
                totalArea: totalArea || 0,
                poiArea: poiArea || 0,
                purity,
                avgR2,
                estAmount: laneEstAmount,
                estUnit: laneEstUnit,
                knownAmount,
                knownUnit,
                recoveryPct,
            };
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
                        <td colspan="16">
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

            // Step 2 of plan: hide the Quantification group when no compared
            // analysis has an active calibration.
            const anyActive = samples.some(s => s.analysis && s.analysis.active_quant_calibration);
            this._updateQuantHeaderVisibility(anyActive);

            // Detect whether to show Loading-µL column at all
            const hasLoadingUl = samples.some(s => s.lane && s.lane.loading_volume_ul != null);
            const ulHeader = this.thead.querySelector('#cmp-col-load-ul');
            if (ulHeader) ulHeader.style.display = hasLoadingUl ? '' : 'none';

            // Sort by lane number
            const sorted = [...samples].sort((a, b) => {
                const an = a.lane?.lane_number || 0;
                const bn = b.lane?.lane_number || 0;
                return this.sortDir === 'asc' ? an - bn : bn - an;
            });

            const rows = sorted.map(sample => {
                const summary = this._summarizeLane(sample);
                return this._renderLaneRow(sample, summary, anyActive, hasLoadingUl);
            });

            this.tbody.innerHTML = rows.join('');

            // Wire row click → select sample
            this.tbody.querySelectorAll('tr[data-row-type="lane"]').forEach(row => {
                row.addEventListener('click', () => {
                    const sampleId = row.dataset.sampleId;
                    if (sampleId) this.state.selectSample(sampleId);
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

        _renderLaneRow(sample, summary, quantActive, hasLoadingUl) {
            const lane = sample.lane || {};
            const laneType = lane.lane_type || 'SAMPLE';
            const typeLower = laneType.toLowerCase();
            const typeLabel = LANE_TYPE_DISPLAY[laneType] || laneType;

            const tintClass = (laneType === 'CALIBRATION')
                ? 'gv-table-row--calibration'
                : (laneType === 'CONTROL') ? 'gv-table-row--control' : '';

            // Identity
            const sampleName = this._escape(lane.sample_name || sample.label || '');
            const condition = lane.is_reduced === true
                ? 'Reduced'
                : lane.is_reduced === false ? 'Non-reduced' : '—';
            const loadUg = lane.protein_load_ug != null ? lane.protein_load_ug : null;
            const loadUl = lane.loading_volume_ul != null ? lane.loading_volume_ul : null;

            // Quantification cells
            const calib = sample.analysis?.active_quant_calibration || null;
            const showQuantValue = !!calib || laneType === 'CONTROL';

            let estAmountDisplay = '—';
            if (showQuantValue && summary.estAmount != null) {
                const unit = this._formatUnit(summary.estUnit || (calib && calib.unit));
                estAmountDisplay = `${summary.estAmount.toFixed(2)} ${unit}`;
            }

            let recoveryDisplay = '—';
            if (laneType === 'CONTROL' && summary.recoveryPct != null) {
                recoveryDisplay = `${summary.recoveryPct.toFixed(0)}%`;
            }

            const calibMethod = calib ? this._formatMethod(calib.method) : '—';

            // Quality
            const r2Display = summary.avgR2 != null ? summary.avgR2.toFixed(3) : '—';
            const mwMarkers = sample.analysis?.mw_marker_count != null
                ? sample.analysis.mw_marker_count
                : 0;

            // Status icon
            let statusIcon = '<span class="cmp-status cmp-status-ok" title="OK">&#10003;</span>';
            if (laneType === 'CONTROL' && summary.recoveryPct != null
                && (summary.recoveryPct < 80 || summary.recoveryPct > 120)) {
                statusIcon = '<span class="cmp-status cmp-status-warn" title="Out-of-spec recovery (target 80-120%)">&#9888;</span>';
            } else if (!sample.profile) {
                statusIcon = '<span class="cmp-status cmp-status-warn" title="No densitometry profile">&#9888;</span>';
            }

            // data-estimated-amount drives the "Show only quantified lanes"
            // filter — set the dataset attribute only when there IS a
            // predicted estimated amount for this lane.
            const dataEstAttr = summary.estAmount != null
                ? `data-estimated-amount="${summary.estAmount}"`
                : '';

            const ulCellStyle = hasLoadingUl ? '' : 'style="display:none;"';

            return `
                <tr class="cmp-lane-row ${tintClass}"
                    data-row-type="lane"
                    data-sample-id="${sample.sampleId}"
                    data-lane-id="${lane.id || ''}"
                    data-lane-type="${laneType}"
                    ${dataEstAttr}
                    style="border-left: 3px solid ${sample.color || 'transparent'};">
                    <td class="cmp-sticky-left col-lane">${lane.lane_number != null ? lane.lane_number : ''}</td>
                    <td class="cmp-sticky-left col-type">
                        <span class="gv-prop-type-badge gv-prop-type-${typeLower}">${typeLabel}</span>
                    </td>
                    <td class="col-sample">${sampleName || '<span class="cmp-muted">—</span>'}</td>
                    <td class="col-condition col-preset-standard">${condition}</td>
                    <td class="col-load-ug">${loadUg != null ? loadUg : '—'}</td>
                    <td class="col-load-ul col-preset-full" ${ulCellStyle}>${loadUl != null ? loadUl : '—'}</td>
                    <td class="col-total-area">${this._fmtNum(summary.totalArea, 0)}</td>
                    <td class="col-band-count col-preset-standard">${summary.bandCount}</td>
                    <td class="col-poi-area col-preset-full">${this._fmtNum(summary.poiArea, 0)}</td>
                    <td class="col-purity">${summary.purity != null ? summary.purity.toFixed(1) + '%' : '—'}</td>
                    <td class="cmp-section-quant col-est-amount">${estAmountDisplay}</td>
                    <td class="cmp-section-quant col-recovery col-preset-standard">${recoveryDisplay}</td>
                    <td class="cmp-section-quant col-calib-method col-preset-full">${calibMethod}</td>
                    <td class="col-r2 col-preset-standard">${r2Display}</td>
                    <td class="col-mw-markers col-preset-full">${mwMarkers}</td>
                    <td class="col-status">${statusIcon}</td>
                </tr>
            `;
        }

        // -----------------------------------------------------------------
        // Filter handlers
        // -----------------------------------------------------------------

        _applyOnlyQuantFilter() {
            if (!this.table) return;
            const filter = this.onlyQuantified;
            this.table.querySelectorAll('tr[data-row-type="lane"]').forEach(r => {
                const hasEst = r.dataset.estimatedAmount != null && r.dataset.estimatedAmount !== '';
                r.hidden = filter && !hasEst;
            });
        }

        // -----------------------------------------------------------------
        // Highlight
        // -----------------------------------------------------------------

        _highlightLane(sampleId) {
            if (!this.tbody) return;
            this.tbody.querySelectorAll('tr.cmp-lane-row.selected').forEach(r => r.classList.remove('selected'));
            if (!sampleId) return;
            const row = this.tbody.querySelector(`tr.cmp-lane-row[data-sample-id="${sampleId}"]`);
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

        _formatMethod(method) {
            const map = {
                LINEAR: 'Linear',
                POLYNOMIAL_2: 'Poly2',
                FOUR_PL: '4PL',
            };
            return map[method] || (method || '—');
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
