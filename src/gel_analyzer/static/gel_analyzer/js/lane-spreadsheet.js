/**
 * LaneSpreadsheet — Handsontable-powered editable lane table for gel analysis detail.
 *
 * Provides spreadsheet UX (arrow keys, copy-paste, undo/redo, dropdown editors)
 * with auto-save to the Lane API on each cell change. The lane fields (type,
 * sample name, condition, load, load type) are editable. Phoresis has no
 * Process Development samples: the Sample cell is the lane's free-text
 * `sample_name` (ds-hub opens a sample picker there instead).
 *
 * The value columns after them are the SERVER's (services/analysis_detail.py):
 * `readoutColumns` names them for the gel's readout (purity, aggregates / main
 * band / clipping, HCP signal...), and each lane carries `cells[key]` =
 * {text, reason, tone}, already formatted. This file prints them and never
 * computes a value. A page that passes no `readoutColumns` gets the three
 * read-only columns Phoresis always showed (Bands, POI (kDa), Purity), read
 * from the lane's `_band_count` / `poi_kda` / `purity`.
 *
 * Usage:
 *   const sheet = new LaneSpreadsheet({
 *       container: document.getElementById('lane-spreadsheet'),
 *       lanes: [...],  // lane_to_dict() objects + `cells`, `_band_count`, `poi_kda`, `purity`
 *       readoutColumns: [{key, label, title}, ...],  // optional
 *       analysisId: 'uuid',
 *       csrfToken: '...',
 *       canEdit: true,
 *   });
 *
 * @module gel_analyzer/lane-spreadsheet
 */
(function(global) {
    'use strict';

    var API_BASE = '/api';

    // ── Field mappings ─────────────────────────────────────────

    var LANE_TYPES = ['Sample', 'Ladder', 'Empty', 'Control', 'Dot', 'Calibrant'];
    var LANE_TYPE_MAP = {
        'Sample': 'SAMPLE', 'Ladder': 'LADDER', 'Empty': 'EMPTY',
        'Control': 'CONTROL', 'Dot': 'DOT', 'Calibrant': 'CALIBRATION'
    };
    var LANE_TYPE_REVERSE = {};
    Object.keys(LANE_TYPE_MAP).forEach(function(k) { LANE_TYPE_REVERSE[LANE_TYPE_MAP[k]] = k; });

    // Lane types that anchor ProteinQuantCalibrationPoint rows. Downgrading
    // FROM one of these requires the v1 PATCH safeguard so attached points
    // don't get orphaned silently.
    var POINT_ANCHOR_LANE_TYPES = ['CALIBRATION', 'CONTROL'];

    var CONDITIONS = ['\u2014', 'Reduced', 'Non-reduced'];
    var CONDITION_MAP = { '\u2014': null, 'Reduced': true, 'Non-reduced': false };
    var CONDITION_REVERSE = { 'null': '\u2014', 'true': 'Reduced', 'false': 'Non-reduced' };

    var LOAD_TYPES = ['\u2014', 'Total Protein', 'POI', 'Host Cell Protein', 'Other'];
    var LOAD_TYPE_MAP = { '\u2014': '', 'Total Protein': 'TOTAL', 'POI': 'POI', 'Host Cell Protein': 'HOST_CELL', 'Other': 'OTHER' };
    var LOAD_TYPE_REVERSE = { '': '\u2014', 'TOTAL': 'Total Protein', 'POI': 'POI', 'HOST_CELL': 'Host Cell Protein', 'OTHER': 'Other' };

    // The analysis page is a Tailwind template without ds-hub's `ga-hot-*` /
    // `ga-ad-*` stylesheet: the renderers carry ds-hub's class names AND
    // Phoresis's inline styles, so the grid reads the same with or without it.
    var TONE_COLORS = { ok: '#22c55e', good: '#22c55e', warn: '#f59e0b', fair: '#f59e0b', bad: '#ef4444', poor: '#ef4444' };

    // ── Value cell renderer (the server's text, or the reason it is missing) ──

    function valueRenderer(instance, td, row, col, prop, value) {
        Handsontable.renderers.TextRenderer.apply(this, arguments);
        var rowData = instance.getSourceDataAtRow(row) || {};
        var cell = (rowData._cells || {})[prop.slice(5)] || null;  // 'cell_<key>'
        td.className = 'ga-hot-val';
        td.style.textAlign = 'center';
        if (!cell) {
            td.textContent = '';
        } else if (cell.reason) {
            td.className += ' is-reason';
            td.style.color = '#94a3b8';
            td.style.fontStyle = 'italic';
            td.style.fontSize = '0.75rem';
            td.textContent = cell.reason;
        } else {
            td.style.fontWeight = '600';
            if (cell.tone) {
                td.className += ' is-' + cell.tone;
                if (TONE_COLORS[cell.tone]) td.style.color = TONE_COLORS[cell.tone];
            }
            td.textContent = cell.text;
        }
    }

    // ── Purity color renderer (pages without readoutColumns) ───

    function purityRenderer(instance, td, row, col, prop, value) {
        Handsontable.renderers.NumericRenderer.apply(this, arguments);
        td.style.textAlign = 'center';
        td.style.fontWeight = '600';
        if (value != null && value !== '') {
            var v = parseFloat(value);
            if (v >= 90) { td.style.color = '#22c55e'; }
            else if (v >= 70) { td.style.color = '#f59e0b'; }
            else { td.style.color = '#ef4444'; }
            td.textContent = v.toFixed(1) + '%';
        } else {
            td.style.color = '#cbd5e1';
            td.textContent = '\u2014';
        }
    }

    // ── Read-only numeric renderer (pages without readoutColumns) ──

    function readOnlyNumericRenderer(instance, td, row, col, prop, value) {
        Handsontable.renderers.NumericRenderer.apply(this, arguments);
        td.style.textAlign = 'center';
        if (value == null || value === '') {
            td.style.color = '#cbd5e1';
            td.textContent = '\u2014';
        } else {
            td.style.fontWeight = '600';
        }
    }

    // ── Lane number renderer ───────────────────────────────────

    function laneNumberRenderer(instance, td, row, col, prop, value) {
        Handsontable.renderers.TextRenderer.apply(this, arguments);
        var rowData = instance.getSourceDataAtRow(row) || {};
        td.innerHTML = '';
        td.className = 'ga-hot-lane';
        td.style.textAlign = 'center';
        var span = document.createElement('span');
        span.className = 'ga-ad-lnum ga-ad-lnum--' + String(rowData._lane_type || 'sample').toLowerCase();
        span.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:5px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;font-size:0.7rem;font-weight:700;';
        span.textContent = value;
        td.appendChild(span);
        if (rowData._is_reference) {
            var ref = document.createElement('span');
            ref.className = 'ga-ad-ref';
            ref.style.cssText = 'margin-left:4px;font-size:0.6rem;font-weight:700;color:#2563eb;';
            ref.title = 'HCP reference lane';
            ref.textContent = 'REF';
            td.appendChild(ref);
        }
    }

    // ── Sample renderer ────────────────────────────────────────

    function sampleRenderer(instance, td, row, col, prop, value) {
        Handsontable.renderers.TextRenderer.apply(this, arguments);
        td.innerHTML = '';
        td.className = 'ga-hot-sample';
        if (value && value !== '\u2014') {
            var span = document.createElement('span');
            span.className = 'ga-hot-sample-name';
            span.style.cssText = 'font-weight:600;color:#1e293b;font-size:0.8rem;';
            span.textContent = value;
            td.appendChild(span);
        } else {
            td.className += ' is-empty';
            td.style.color = '#94a3b8';
            td.style.fontStyle = 'italic';
            td.style.fontSize = '0.75rem';
            td.textContent = 'Click to name...';
        }
    }

    // ── Save flash effect ──────────────────────────────────────

    function flashCell(hot, row, col, success) {
        var td = hot.getCell(row, col);
        if (!td) return;
        var color = success ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)';
        td.style.transition = 'background-color 0.1s';
        td.style.backgroundColor = color;
        setTimeout(function() {
            td.style.backgroundColor = '';
            td.style.transition = '';
        }, 600);
    }

    // ── Main class ─────────────────────────────────────────────

    function LaneSpreadsheet(opts) {
        this.container = opts.container;
        this.lanes = opts.lanes || [];
        this.readoutColumns = opts.readoutColumns || [];
        this.analysisId = opts.analysisId;
        this.csrfToken = opts.csrfToken;
        this.canEdit = opts.canEdit !== false;
        this.hot = null;
        this._saveTimers = {};

        this._init();
    }

    LaneSpreadsheet.prototype._init = function() {
        var self = this;
        var data = this._buildData();
        var headers = ['Lane', 'Type', 'Sample', 'Condition', 'Load (\u00B5g)', 'Load Type'];
        var columns = [
            { data: 'lane_number', type: 'numeric', readOnly: true, renderer: laneNumberRenderer, width: 62 },
            { data: 'lane_type', type: 'dropdown', source: LANE_TYPES, readOnly: !this.canEdit, width: 90 },
            // Free-text sample name, edited in place (no sample picker in Phoresis).
            { data: 'sample_display', readOnly: !this.canEdit, renderer: sampleRenderer, width: 150 },
            { data: 'condition', type: 'dropdown', source: CONDITIONS, readOnly: !this.canEdit, width: 110 },
            // Intl-style numericFormat, as Phoresis's vendored Handsontable expects (not a numbro pattern).
            { data: 'protein_load_ug', type: 'numeric', numericFormat: { minimumFractionDigits: 1, maximumFractionDigits: 1 }, readOnly: !this.canEdit, width: 85 },
            { data: 'load_type', type: 'dropdown', source: LOAD_TYPES, readOnly: !this.canEdit, width: 120 },
        ];
        if (this.readoutColumns.length) {
            // The readout's value columns, read-only (derived server-side from the densitometry).
            this.readoutColumns.forEach(function(column) {
                headers.push(column.label);
                columns.push({ data: 'cell_' + column.key, readOnly: true, renderer: valueRenderer, width: 86 });
            });
        } else {
            // No readout columns passed: the lane payload's own read-only stats.
            headers.push('Bands', 'POI (kDa)', 'Purity');
            columns.push(
                { data: 'band_count', type: 'numeric', readOnly: true, renderer: readOnlyNumericRenderer, width: 65 },
                { data: 'poi_kda', type: 'numeric', readOnly: true, renderer: readOnlyNumericRenderer, width: 80 },
                { data: 'purity', readOnly: true, renderer: purityRenderer, width: 80 }
            );
        }

        this.hot = new Handsontable(this.container, {
            data: data,
            themeName: 'ht-theme-main',
            colHeaders: headers,
            columns: columns,
            rowHeaders: false,
            stretchH: 'all',
            autoWrapRow: true,
            autoWrapCol: true,
            licenseKey: 'non-commercial-and-evaluation',
            className: 'ga-lane-hot',
            height: 'auto',
            fixedColumnsStart: 1,
            manualColumnResize: true,
            undo: true,
            contextMenu: this.canEdit ? ['undo', 'redo', '---------', 'copy', 'cut'] : ['copy'],
            copyPaste: true,
            afterChange: function(changes, source) {
                // 'loadData' fires once on init; 'guardRevert' fires when the
                // CALIBRATION/CONTROL downgrade prompt is cancelled and the
                // dropdown snaps back — neither should re-trigger _saveCell.
                if (source === 'loadData' || source === 'guardRevert' || !changes) return;
                changes.forEach(function(change) {
                    var row = change[0];
                    var prop = change[1];
                    var oldVal = change[2];
                    var newVal = change[3];
                    if (oldVal === newVal) return;
                    self._saveCell(row, prop, newVal);
                });
            },
            cells: function(row, col) {
                var cellProperties = {};
                if (col === 0) cellProperties.renderer = laneNumberRenderer;
                return cellProperties;
            },
        });
    };

    // ── Build HOT data from lane objects ────────────────────────

    LaneSpreadsheet.prototype._buildData = function() {
        var readoutColumns = this.readoutColumns;
        return this.lanes.map(function(lane) {
            var cells = lane.cells || {};
            var row = {
                id: lane.id,
                lane_number: lane.lane_number,
                lane_type: LANE_TYPE_REVERSE[lane.lane_type] || 'Sample',
                sample_display: lane.sample_name || '',
                condition: CONDITION_REVERSE[String(lane.is_reduced)] || '\u2014',
                protein_load_ug: lane.protein_load_ug,
                load_type: LOAD_TYPE_REVERSE[lane.protein_load_type || ''] || '\u2014',
                _lane_type: lane.lane_type,
                _is_reference: !!lane.is_reference,
                _cells: cells,
                band_count: lane._band_count !== undefined ? lane._band_count : (lane.bands ? lane.bands.length : 0),
                poi_kda: lane.poi_kda || null,
                purity: (lane.purity === undefined || lane.purity === null) ? null : lane.purity,
            };
            // The text is what a copy takes; the renderer reads _cells for the reason and the tone.
            readoutColumns.forEach(function(column) {
                var cell = cells[column.key];
                row['cell_' + column.key] = cell ? (cell.reason || cell.text) : '';
            });
            return row;
        });
    };

    // ── Auto-save cell change ──────────────────────────────────

    LaneSpreadsheet.prototype._saveCell = function(row, prop, value) {
        var self = this;
        var lane = this.lanes[row];
        if (!lane) return;

        // Build API payload from changed property
        var payload = {};
        switch (prop) {
            case 'lane_type':
                payload.lane_type = LANE_TYPE_MAP[value] || 'SAMPLE';
                break;
            case 'sample_display':
                payload.sample_name = (value == null) ? '' : String(value).trim();
                break;
            case 'condition':
                payload.is_reduced = CONDITION_MAP[value];
                if (payload.is_reduced === undefined) payload.is_reduced = null;
                break;
            case 'protein_load_ug':
                payload.protein_load_ug = (value === '' || value == null) ? null : parseFloat(value);
                break;
            case 'load_type':
                payload.protein_load_type = LOAD_TYPE_MAP[value] || '';
                break;
            default:
                return; // Read-only column, skip
        }

        // Lane-type downgrades from CALIBRATION/CONTROL anchor protein quant
        // calibration points server-side. The legacy PUT endpoint blindly
        // orphans them; the v1 PATCH endpoint guards the change with a 409
        // + dependent_band_ids list. Re-route those specific edits through
        // v1 (no debounce — we need to prompt synchronously).
        if (prop === 'lane_type') {
            var newCode = payload.lane_type;
            var oldCode = lane.lane_type;
            var isDowngrade = POINT_ANCHOR_LANE_TYPES.indexOf(oldCode) !== -1
                && POINT_ANCHOR_LANE_TYPES.indexOf(newCode) === -1
                && oldCode !== newCode;
            if (isDowngrade) {
                this._patchLaneTypeWithGuard(lane, newCode, row, prop);
                return;
            }
        }

        // Debounce per lane
        var timerId = 'lane_' + lane.id;
        if (this._saveTimers[timerId]) clearTimeout(this._saveTimers[timerId]);

        this._saveTimers[timerId] = setTimeout(function() {
            self._putLane(lane.id, payload, row, prop);
        }, 300);
    };

    // ── Lane type downgrade with cascade safeguard ─────────────
    //
    // CALIBRATION/CONTROL → other lane types via the v1 PATCH endpoint.
    // 409 → confirm with the user, re-fire with ?force=true on confirm.
    // Cancel → revert the dropdown to the original value.
    //
    // After a *forced* purge, the value cells (purity, readouts, measured
    // load) are computed server-side from data the HOT doesn't
    // carry — and bands were retagged CALIBRATION→OTHER. Cheapest way to
    // recover a coherent view is a page reload; the user has explicitly
    // confirmed the destructive action so the reload is expected.
    LaneSpreadsheet.prototype._patchLaneTypeWithGuard = function(lane, newCode, row, prop) {
        var self = this;
        var col = this.hot.propToCol(prop);
        var url = '/api/v1/lanes/' + lane.id + '/';

        function doPatch(force) {
            return fetch(url + (force ? '?force=true' : ''), {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': self.csrfToken,
                },
                body: JSON.stringify({ lane_type: newCode }),
            });
        }

        function revertSelect() {
            // Use the lane's pre-change code so the dropdown snaps back.
            self.hot.setDataAtRowProp(row, prop, LANE_TYPE_REVERSE[lane.lane_type] || 'Sample', 'guardRevert');
            flashCell(self.hot, row, col, false);
        }

        function applyLocal() {
            lane.lane_type = newCode;
            flashCell(self.hot, row, col, true);
        }

        doPatch(false)
            .then(function(resp) {
                if (resp.ok) {
                    applyLocal();
                    return null;
                }
                if (resp.status === 409) {
                    return resp.json().then(function(body) {
                        var count = (body && body.dependent_band_ids && body.dependent_band_ids.length) || 0;
                        var msg = 'Lane ' + lane.lane_number + ': ' + count +
                            ' calibration point' + (count === 1 ? '' : 's') +
                            ' on this lane will be discarded and the affected band' +
                            (count === 1 ? '' : 's') + ' re-tagged as Other.\n\nContinue?';
                        if (!window.confirm(msg)) {
                            revertSelect();
                            return null;
                        }
                        return doPatch(true).then(function(resp2) {
                            if (!resp2.ok) throw new Error('HTTP ' + resp2.status);
                            // Don't applyLocal — flash the cell green, then reload.
                            // The value cells are derived
                            // server-side from data the HOT doesn't carry,
                            // and N bands just changed band_type. A reload
                            // is the only honest way to surface the new state.
                            flashCell(self.hot, row, col, true);
                            setTimeout(function() { window.location.reload(); }, 400);
                        });
                    });
                }
                throw new Error('HTTP ' + resp.status);
            })
            .catch(function(err) {
                console.error('Lane type save error:', err);
                revertSelect();
            });
    };

    LaneSpreadsheet.prototype._putLane = function(laneId, payload, row, prop) {
        var self = this;
        var col = this.hot.propToCol(prop);

        fetch(API_BASE + '/lanes/' + laneId + '/', {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.csrfToken,
            },
            body: JSON.stringify(payload),
        })
        .then(function(resp) {
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.json();
        })
        .then(function(data) {
            // Update local lane data
            if (data.lane) {
                var idx = self.lanes.findIndex(function(l) { return l.id === laneId; });
                if (idx >= 0) {
                    Object.assign(self.lanes[idx], data.lane);
                }
            }
            flashCell(self.hot, row, col, true);
        })
        .catch(function(err) {
            console.error('Lane save error:', err);
            flashCell(self.hot, row, col, false);
        });
    };

    // ── Destroy ────────────────────────────────────────────────

    LaneSpreadsheet.prototype.destroy = function() {
        if (this.hot) {
            this.hot.destroy();
            this.hot = null;
        }
        Object.values(this._saveTimers).forEach(clearTimeout);
    };

    global.LaneSpreadsheet = LaneSpreadsheet;

})(window);
