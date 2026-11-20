// Run: node gel_analyzer/static/gel_analyzer/js/gel-viewer/__tests__/form-after-save.test.js
//
// A lane drawn and saved with its form still open kept a form wired to its temp_ id (seen 2026-10-13): Save gives the
// lane its server id on the same object, but every handler had copied the temp id at render, so a Type changed after
// the Save reached GelViewerApp._updateLane(temp_...), which found no lane and returned without a word, and "Delete
// lane" did nothing. A band's form had the same flaw, and a band saved by the batch Save also kept the selection and
// the panel on its temp id. The real PropertiesPanel form handlers run into the real GelViewerApp._batchSave,
// _updateLane and _updateBand on a real StateManager; only the edges are stubbed (the API client, the SVG, the form's
// elements, which a render replaces as innerHTML does).
const assert = require('assert');

globalThis.window = globalThis;
Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: { getItem: () => null, setItem() {}, removeItem() {} },
});

function el() {
    const listeners = {};
    return {
        value: '', style: {}, dataset: {}, innerHTML: '', textContent: '',
        addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
        fire(type) { for (const fn of listeners[type] || []) fn({ target: this }); },
    };
}
let formElements = new Map();  // the elements of the form shown: a render makes new ones
globalThis.document = {
    getElementById: (id) => {
        if (!id.startsWith('prop-')) return null;
        if (!formElements.has(id)) formElements.set(id, el());
        return formElements.get(id);
    },
    createElement: () => ({ textContent: '', get innerHTML() { return this.textContent; } }),
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener() {},
};

require('../../shared/lane-geometry.js');
require('../event-bus.js');
require('../state-manager.js');
require('../gel-viewer.js');
require('../panels/properties-panel.js');
const { EventBus, StateManager, App, PropertiesPanel } = window.GelViewer;

function editor() {
    const eventBus = new EventBus();
    const sm = new StateManager({ analysisId: 'a1', eventBus });
    const calls = { deleteLane: [], deleteBand: [], putBand: [] };
    const app = Object.create(App.prototype);
    Object.assign(app, {
        stateManager: sm,
        eventBus,
        svg: { findOne: () => null },
        apiClient: {
            createLane: async () => ({ id: 42 }),
            createBand: async () => ({ id: 'b99' }),
            updateBand: async (id, data) => { calls.putBand.push([id, data]); },
        },
        _showMessage() {},
        _scheduleReadingRefresh() {},
    });
    app.propertiesPanel = new PropertiesPanel({
        eventBus,
        stateManager: sm,
        apiClient: {},
        onUpdateLane: (id, data) => app._updateLane(id, data),
        onUpdateBand: (id, data) => app._updateBand(id, data),
        onDeleteLane: (id) => calls.deleteLane.push(id),
        onDeleteBand: (id) => calls.deleteBand.push(id),
    });
    app.propertiesPanel.contentContainer = {
        set innerHTML(_) { formElements = new Map(); },
        querySelectorAll: () => [],
    };
    const show = (type, id) => {
        app.selectedType = type;
        app.selectedId = id;
        app.propertiesPanel.show(type, id);
    };
    return { sm, app, calls, show };
}

function drawLane(sm) {
    const lane = { id: 'temp_1_0', lane_number: 1, lane_type: 'SAMPLE', x: 10, y: 0, width: 40, height: 300,
        bands: [], _isNew: true };
    sm.setLane(lane.id, lane);
    sm.trackLaneCreation(lane.id, lane);
    return lane;
}

async function testALaneFormOpenAcrossTheSaveActsOnTheSavedLane() {
    const { sm, app, calls, show } = editor();
    drawLane(sm);
    show('lane', 'temp_1_0');
    const type = document.getElementById('prop-lane-type');
    const del = document.getElementById('prop-delete-lane-btn');

    await app._batchSave();
    assert.strictEqual(sm.getLane('temp_1_0'), undefined, 'the lane is held under its server id now');

    type.value = 'CONTROL';
    type.fire('change');
    assert.strictEqual(sm.getLane(42).lane_type, 'CONTROL', 'the Type picked after the Save is the lane\'s');
    assert.deepStrictEqual(sm.pendingChanges.lanes.updated.get(42), { lane_type: 'CONTROL' }, 'and the next Save sends it');

    del.fire('click');
    assert.deepStrictEqual(calls.deleteLane, [42], '"Delete lane" deletes the saved lane');
}

async function testABandFormOpenAcrossTheSaveActsOnTheSavedBand() {
    const { sm, app, calls, show } = editor();
    const lane = drawLane(sm);
    const band = { id: 'temp_2_0', lane_id: 'temp_1_0', _parentLaneId: 'temp_1_0', position_y: 80, band_type: 'OTHER',
        _isNew: true };
    sm.setBand(band.id, band);
    sm.trackBandCreation(band.id, band);
    lane.bands.push(band);
    show('band', 'temp_2_0');
    const type = document.getElementById('prop-band-type');
    type.dataset.field = 'band_type';
    const del = document.getElementById('prop-delete-band-btn');

    await app._batchSave();
    assert.strictEqual(app.selectedId, 'b99', 'the selection follows the band (the Delete key reads it)');
    assert.strictEqual(app.propertiesPanel.currentId, 'b99', 'so does the form shown');

    type.value = 'POI';
    type.fire('change');
    assert.deepStrictEqual(calls.putBand, [['b99', { band_type: 'POI' }]], 'the Type picked after the Save is sent');
    assert.strictEqual(sm.getBand('b99').band_type, 'POI');

    del.fire('click');
    assert.deepStrictEqual(calls.deleteBand, ['b99'], '"Delete" deletes the saved band');
}

(async () => {
    await testALaneFormOpenAcrossTheSaveActsOnTheSavedLane();
    await testABandFormOpenAcrossTheSaveActsOnTheSavedBand();
})().then(
    () => console.log('form after save: all assertions passed'),
    (err) => {
        console.error('form after save: FAILED\n' + (err && err.stack ? err.stack : err));
        process.exitCode = 1;
    },
);
