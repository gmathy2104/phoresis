/**
 * LaneSpreadsheet — Handsontable-powered editable lane table for gel analysis detail.
 *
 * Provides spreadsheet UX (arrow keys, copy-paste, undo/redo, dropdown editors)
 * with auto-save to the Lane API on each cell change.
 *
 * Usage:
 *   const sheet = new LaneSpreadsheet({
 *       container: document.getElementById('lane-spreadsheet'),
 *       lanes: [...],  // Array of lane_to_dict() objects
 *       analysisId: 'uuid',
 *       csrfToken: '...',
 *       canEdit: true,
 *       onSampleClick: function(laneId, laneNumber) { ... },
 *   });
 *
 * @module gel_analyzer/lane-spreadsheet
 */
(function(global) {
    'use strict';

    var API_BASE = '/api';

    // ── Field mappings ─────────────────────────────────────────

    var LANE_TYPES = ['Sample', 'Ladder', 'Empty', 'Control', 'Dot'];
    var LANE_TYPE_MAP = { 'Sample': 'SAMPLE', 'Ladder': 'LADDER', 'Empty': 'EMPTY', 'Control': 'CONTROL', 'Dot': 'DOT' };
    var LANE_TYPE_REVERSE = {};
    Object.keys(LANE_TYPE_MAP).forEach(function(k) { LANE_TYPE_REVERSE[LANE_TYPE_MAP[k]] = k; });

    var CONDITIONS = ['\u2014', 'Reduced', 'Non-reduced'];
    var CONDITION_MAP = { '\u2014': null, 'Reduced': true, 'Non-reduced': false };
    var CONDITION_REVERSE = { 'null': '\u2014', 'true': 'Reduced', 'false': 'Non-reduced' };

    var LOAD_TYPES = ['\u2014', 'Total Protein', 'POI', 'Host Cell Protein', 'Other'];
    var LOAD_TYPE_MAP = { '\u2014': '', 'Total Protein': 'TOTAL', 'POI': 'POI', 'Host Cell Protein': 'HOST_CELL', 'Other': 'OTHER' };
    var LOAD_TYPE_REVERSE = { '': '\u2014', 'TOTAL': 'Total Protein', 'POI': 'POI', 'HOST_CELL': 'Host Cell Protein', 'OTHER': 'Other' };

    // ── Purity color renderer ──────────────────────────────────

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

    // ── Read-only numeric renderer ─────────────────────────────

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
        td.innerHTML = '';
        var span = document.createElement('span');
        span.style.cssText = 'display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:5px;background:linear-gradient(135deg,#3b82f6,#2563eb);color:#fff;font-size:0.7rem;font-weight:700;';
        span.textContent = value;
        td.style.textAlign = 'center';
        td.appendChild(span);
    }

    // ── Sample renderer ────────────────────────────────────────

    function sampleRenderer(instance, td, row, col, prop, value) {
        Handsontable.renderers.TextRenderer.apply(this, arguments);
        td.innerHTML = '';
        if (value && value !== '\u2014') {
            var link = document.createElement('span');
            link.style.cssText = 'font-weight:600;color:#1e293b;font-size:0.8rem;';
            link.textContent = value;
            td.appendChild(link);
        } else {
            td.style.color = '#94a3b8';
            td.style.fontStyle = 'italic';
            td.style.fontSize = '0.75rem';
            td.textContent = 'Click to assign...';
        }
        td.style.cursor = 'pointer';
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
        this.analysisId = opts.analysisId;
        this.csrfToken = opts.csrfToken;
        this.canEdit = opts.canEdit !== false;
        this.onSampleClick = opts.onSampleClick || function() {};
        this.hot = null;
        this._saveTimers = {};

        this._init();
    }

    LaneSpreadsheet.prototype._init = function() {
        var self = this;
        var data = this._buildData();

        this.hot = new Handsontable(this.container, {
            data: data,
            colHeaders: ['Lane', 'Type', 'Sample', 'Condition', 'Load (\u00B5g)', 'Load Type', 'Bands', 'POI (kDa)', 'Purity'],
            columns: [
                { data: 'lane_number', type: 'numeric', readOnly: true, renderer: laneNumberRenderer, width: 55 },
                { data: 'lane_type', type: 'dropdown', source: LANE_TYPES, readOnly: !this.canEdit, width: 90 },
                { data: 'sample_display', readOnly: true, renderer: sampleRenderer, width: 150 },
                { data: 'condition', type: 'dropdown', source: CONDITIONS, readOnly: !this.canEdit, width: 110 },
                { data: 'protein_load_ug', type: 'numeric', numericFormat: { pattern: '0.0' }, readOnly: !this.canEdit, width: 85 },
                { data: 'load_type', type: 'dropdown', source: LOAD_TYPES, readOnly: !this.canEdit, width: 120 },
                { data: 'band_count', type: 'numeric', readOnly: true, renderer: readOnlyNumericRenderer, width: 65 },
                { data: 'poi_kda', type: 'numeric', readOnly: true, renderer: readOnlyNumericRenderer, width: 80 },
                { data: 'purity', readOnly: true, renderer: purityRenderer, width: 80 },
            ],
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
                if (source === 'loadData' || !changes) return;
                changes.forEach(function(change) {
                    var row = change[0];
                    var prop = change[1];
                    var oldVal = change[2];
                    var newVal = change[3];
                    if (oldVal === newVal) return;
                    self._saveCell(row, prop, newVal);
                });
            },
            afterOnCellMouseDown: function(event, coords) {
                // Sample column click → open sample selector
                if (coords.col === 2 && self.canEdit) {
                    var laneData = self.lanes[coords.row];
                    if (laneData) {
                        self.onSampleClick(laneData.id, laneData.lane_number, coords.row);
                    }
                }
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
        return this.lanes.map(function(lane) {
            return {
                id: lane.id,
                lane_number: lane.lane_number,
                lane_type: LANE_TYPE_REVERSE[lane.lane_type] || 'Sample',
                sample_display: (lane.process_sample ? lane.process_sample.sample_id : lane.sample_name) || '',
                condition: CONDITION_REVERSE[String(lane.is_reduced)] || '\u2014',
                protein_load_ug: lane.protein_load_ug,
                load_type: LOAD_TYPE_REVERSE[lane.protein_load_type || ''] || '\u2014',
                band_count: lane._band_count !== undefined ? lane._band_count : (lane.bands ? lane.bands.length : 0),
                poi_kda: lane.poi_kda || null,
                purity: lane.purity || null,
            };
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

        // Debounce per lane
        var timerId = 'lane_' + lane.id;
        if (this._saveTimers[timerId]) clearTimeout(this._saveTimers[timerId]);

        this._saveTimers[timerId] = setTimeout(function() {
            self._putLane(lane.id, payload, row, prop);
        }, 300);
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

    // ── Update sample for a lane (called after sample modal) ───

    LaneSpreadsheet.prototype.updateSample = function(row, sampleId, sampleDisplay) {
        if (row < 0 || row >= this.lanes.length) return;
        this.hot.setDataAtRowProp(row, 'sample_display', sampleDisplay || '');
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
