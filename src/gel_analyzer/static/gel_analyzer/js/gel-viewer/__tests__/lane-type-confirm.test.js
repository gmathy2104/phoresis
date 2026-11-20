// Run: node gel_analyzer/static/gel_analyzer/js/gel-viewer/__tests__/lane-type-confirm.test.js
//
// The Lane Editor table changed a CALIBRATION lane's type without asking (fixed 2026-10-13), and so did the lane
// menu's Lane Type group: both wrote lane_type through onUpdateLane, so no "Discard calibration points?" and no
// ladder template, and the next Save sent the type through the bulk lane endpoint, which has no calibration guard:
// the lane became SAMPLE with its calibration points still on it, without an error. Both now take the properties
// form's own path, PropertiesPanel.changeLaneType. The real DataTablePanel and ContextMenu actions run into the real
// PropertiesPanel and GelViewerApp._updateLane on a real StateManager, wired as gel-viewer.js wires them; only the
// edges are stubbed (the dialog's answer, the API client, the SVG, the panels' DOM).
const assert = require('assert');

globalThis.window = globalThis;
globalThis.document = {
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener() {},
};
Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: { getItem: () => null, setItem() {}, removeItem() {} },
});

require('../../shared/lane-geometry.js');
require('../event-bus.js');
require('../state-manager.js');
require('../gel-viewer.js');
require('../panels/properties-panel.js');
require('../panels/data-table-panel.js');
require('../panels/context-menu.js');
const { EventBus, StateManager, App, PropertiesPanel, DataTablePanel, ContextMenu } = window.GelViewer;

const settle = () => new Promise((resolve) => setImmediate(resolve));

async function testTheTableAndTheMenuAskBeforeACalibrationLaneChangesType() {
    const eventBus = new EventBus();
    const sm = new StateManager({ analysisId: 'a1', eventBus });
    sm.setLane(7, { id: 7, lane_number: 3, lane_type: 'CALIBRATION', x: 10, y: 0, width: 40, height: 300, bands: [] });
    sm.setBand('b1', { id: 'b1', lane_id: 7, position_y: 50, band_type: 'CALIBRATION',
        quant_point: { load_amount: 2, load_unit: 'UG' } });

    const requests = [];
    const apiClient = {
        patchBand: async (id, data) => { requests.push(['band', id, data]); return {}; },
        patchLaneV1: async (id, data, opts) => { requests.push(['lane', id, data, opts]); return { ok: true }; },
    };
    const app = Object.create(App.prototype);
    Object.assign(app, { stateManager: sm, eventBus, svg: { findOne: () => null }, _showMessage() {} });

    const props = new PropertiesPanel({
        eventBus, stateManager: sm, apiClient, onUpdateLane: (id, data) => app._updateLane(id, data),
    });
    const table = new DataTablePanel({
        eventBus,
        stateManager: sm,
        onUpdateLane: (id, data, silent) => app._updateLane(id, data, silent),
        onChangeLaneType: (id, type, select) => props.changeLaneType(id, type, select),
    });
    const menu = new ContextMenu({
        eventBus,
        stateManager: sm,
        onUpdateLane: (id, data) => app._updateLane(id, data),
        handlers: { onSetLaneType: (id, type) => props.changeLaneType(id, type, null) },
        getSelectedAnnotation: () => ({ type: 'lane', id: 7 }),
    });

    const asked = [];
    globalThis.gelViewer = {
        confirmationManager: {
            modal: {},
            show: async (options) => { asked.push(options.title); return false; },  // "Keep calibration"
        },
    };

    const doors = {
        'the Lane Editor table': async () => {
            const select = { value: 'SAMPLE', dataset: { field: 'lane_type' }, closest: () => null };
            table._handleCellChange(7, select);
            await settle();
            return select;
        },
        'the lane menu': async () => {
            menu._handleAction('set-type', 'SAMPLE');
            await settle();
            return null;
        },
    };
    for (const [door, changeToSample] of Object.entries(doors)) {
        const select = await changeToSample();
        // The positive control: without it, every "nothing happened" below also holds for a door wired to nothing.
        assert.deepStrictEqual(asked.splice(0), ['Discard calibration points?'], `${door}: asks once, first`);
        assert.deepStrictEqual(requests, [], `${door}: "Keep calibration" sends nothing`);
        assert.strictEqual(sm.getLane(7).lane_type, 'CALIBRATION', `${door}: the lane keeps its type`);
        assert.strictEqual(sm.getBand('b1').band_type, 'CALIBRATION', `${door}: and its calibration band`);
        assert.strictEqual(sm.hasPendingChanges(), false, `${door}: nothing is left for the next Save`);
        if (select) assert.strictEqual(select.value, 'CALIBRATION', `${door}: the row goes back to the old type`);
    }
}

// A band typed POI in a CALIBRATION lane demoted the lane to SAMPLE by itself (_autoPromoteLaneForBand, a lane PUT
// with no calibration guard until 2026-10-13): the calibration points stayed on a SAMPLE lane. The lane type it
// implies now goes through changeLaneType, asked when the band's type changes, never at another edit of the band.
async function testABandTypedPoiInACalibrationLaneAsksBeforeTheLaneChanges() {
    const eventBus = new EventBus();
    const sm = new StateManager({ analysisId: 'a1', eventBus });
    sm.setLane(7, { id: 7, lane_number: 3, lane_type: 'CALIBRATION', x: 10, y: 0, width: 40, height: 300, bands: [] });
    sm.setBand('b1', { id: 'b1', lane_id: 7, position_y: 50, band_type: 'CALIBRATION',
        quant_point: { load_amount: 2, load_unit: 'UG' } });
    sm.setBand('b2', { id: 'b2', lane_id: 7, position_y: 120, band_type: 'OTHER' });

    const requests = [];
    const apiClient = {
        updateBand: async (id, data) => { requests.push(['band PUT', id, data]); },
        updateLane: async (id, data) => { requests.push(['lane PUT', id, data]); },
        patchBand: async (id, data) => { requests.push(['band', id, data]); return {}; },
        patchLaneV1: async (id, data, opts) => { requests.push(['lane', id, data, opts]); return { ok: true }; },
    };
    const app = Object.create(App.prototype);
    Object.assign(app, { stateManager: sm, eventBus, apiClient, svg: { findOne: () => null }, _showMessage() {} });
    app.propertiesPanel = new PropertiesPanel({
        eventBus, stateManager: sm, apiClient, onUpdateLane: (id, data) => app._updateLane(id, data),
    });

    const asked = [];
    globalThis.gelViewer = {
        confirmationManager: {
            modal: {},
            show: async (options) => { asked.push(options.title); return false; },  // "Keep calibration"
        },
    };

    app._updateBand('b2', { band_type: 'POI' });
    await settle();
    assert.deepStrictEqual(asked.splice(0), ['Discard calibration points?'], 'the new type asks, once');
    assert.deepStrictEqual(requests.splice(0), [['band PUT', 'b2', { band_type: 'POI' }]],
        '"Keep calibration": only the band is saved, nothing is sent for the lane');
    assert.strictEqual(sm.getLane(7).lane_type, 'CALIBRATION', 'the lane keeps its type');
    assert.strictEqual(sm.getBand('b2').band_type, 'POI', 'the band keeps its new type');

    app._updateBand('b2', { label: 'main band' });
    await settle();
    assert.deepStrictEqual(asked, [], 'another edit of the band does not ask again');
    assert.strictEqual(sm.getLane(7).lane_type, 'CALIBRATION', 'nor changes the lane');
}

testTheTableAndTheMenuAskBeforeACalibrationLaneChangesType()
    .then(testABandTypedPoiInACalibrationLaneAsksBeforeTheLaneChanges)
    .then(
        () => console.log('lane type confirmation: all assertions passed'),
        (err) => {
            console.error('lane type confirmation: FAILED\n' + (err && err.stack ? err.stack : err));
            process.exitCode = 1;
        },
    );
