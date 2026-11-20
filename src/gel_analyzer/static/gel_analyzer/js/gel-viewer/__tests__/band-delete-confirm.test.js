// Run: node gel_analyzer/static/gel_analyzer/js/gel-viewer/__tests__/band-delete-confirm.test.js
//
// The Delete key deleted a SAVED band on the server at once, no question asked, and the lane's densitometry went
// with it (seen 2026-10-13, fixed in 914596466): only the Band Editor asked, with window.confirm. Every path now asks
// once in GelViewerApp._deleteBand, through the editor's own dialog (confirmDeleteBand). The real EventHandler key
// handler runs into the real _deleteSelected / _deleteBand on a real StateManager; only the edges are stubbed (the
// dialog's answer, the API client, the SVG renderer, the toasts). A delete is announced (BAND_DELETED) to the real
// Band Editor and MW calibration panels.
const assert = require('assert');

const stored = new Map();
Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
        getItem: (k) => (stored.has(k) ? stored.get(k) : null),
        setItem: (k, v) => stored.set(k, String(v)),
        removeItem: (k) => stored.delete(k),
    },
});
globalThis.document = {
    getElementById: () => null,
    // The calibration panel's stale warning and its escapeHtml: an element whose innerHTML is what it was given.
    createElement: () => ({ style: {}, textContent: '', get innerHTML() { return this.textContent; },
        set innerHTML(v) { this.textContent = v; } }),
    addEventListener() {},
};
globalThis.window = globalThis;
globalThis.addEventListener = () => {};  // the calibration panel's dsh:themechange

require('../event-bus.js');
require('../state-manager.js');
require('../event-handler.js');
require('../gel-viewer.js');
require('../panels/band-table-panel.js');
require('../panels/calibration-panel.js');
const { EventBus, StateManager, EventHandler, App, BandTablePanel, CalibrationPanel } = window.GelViewer;

const settle = () => new Promise((resolve) => setImmediate(resolve));

function editor(onAsk) {
    const eventBus = new EventBus();
    const sm = new StateManager({ analysisId: 'a1', eventBus });
    const lane = { id: 7, lane_number: 3, x: 10, y: 0, width: 40, height: 300, bands: [] };
    sm.setLane(7, lane);

    const asked = [];
    const deletes = [];
    const app = Object.create(App.prototype);
    Object.assign(app, {
        isEditable: true,
        stateManager: sm,
        eventBus,
        selectedType: null,
        selectedId: null,
        confirmationManager: {
            confirmDeleteBand: async (label, laneNumber) => {
                asked.push([label, laneNumber]);
                return onAsk();
            },
        },
        apiClient: { deleteBand: async (id) => { deletes.push(id); } },
        renderer: { removeBand() {} },
        toasts: { pending: () => ({ success() {}, error() {} }), info() {} },
        _deselect() { this.selectedType = null; this.selectedId = null; },
        _updateToolbarState() {},
    });
    const keys = new EventHandler({
        eventBus,
        stateManager: sm,
        isEditable: true,
        onDeleteSelected: () => app._deleteSelected(),
        getSelectedAnnotation: () => (app.selectedType ? { type: app.selectedType, id: app.selectedId } : null),
    });
    const press = async (key) => {
        keys._onKeyDown({ key, target: { tagName: 'DIV' }, preventDefault() {} });
        await settle();
    };
    return { sm, eventBus, lane, app, asked, deletes, press };
}

async function testTheDeleteKeyAsksBeforeDeletingASavedBand() {
    const answers = [];
    const { sm, lane, app, asked, deletes, press } = editor(() => answers.shift());
    for (const band of [{ id: 'b0', position_y: 20 }, { id: 'b1', position_y: 50, label: '' }]) {
        const b = { ...band, lane_id: 7, band_type: 'POI' };
        sm.setBand(b.id, b);
        lane.bands.push(b);
    }
    app.selectedType = 'band';
    app.selectedId = 'b1';

    answers.push(false);
    await press('Delete');
    answers.push(false);
    await press('Backspace');
    assert.deepStrictEqual(deletes, [], 'cancel (Esc, backdrop, Cancel): nothing sent to the server');
    assert.deepStrictEqual(asked, [['Band 2', 3], ['Band 2', 3]], 'each key asks, naming the band as the panels do');
    assert.ok(sm.getBand('b1'), 'cancel: the band stays');
    assert.strictEqual(app.selectedId, 'b1', 'cancel: still selected');

    answers.push(true);
    await press('Delete');
    assert.deepStrictEqual(deletes, ['b1'], 'confirm: exactly one delete');
    assert.strictEqual(sm.getBand('b1'), undefined);
    assert.deepStrictEqual(lane.bands.map((b) => b.id), ['b0'], 'gone from its lane');

    await press('Delete');
    assert.strictEqual(asked.length, 3, 'nothing selected any more: nothing asked');
    assert.deepStrictEqual(deletes, ['b1']);
}

async function testADrawnBandSavedWhileTheDialogIsOpenIsStillDeleted() {
    // A band drawn on a saved lane is POSTed at once (_createBand); when the answer lands while the dialog is open,
    // the same object takes its server id and the temp id leaves the StateManager.
    let land = null;
    const { sm, lane, app, deletes, press } = editor(() => { land(); return true; });
    const band = { id: 'temp_1_0', lane_id: 7, _parentLaneId: 7, position_y: 80, band_type: 'OTHER', _isNew: true };
    sm.setBand(band.id, band);
    sm.trackBandCreation(band.id, band);
    lane.bands.push(band);
    land = () => {
        band.id = 'b9';
        band._isNew = false;
        sm.replaceBandId('temp_1_0', 'b9');
        sm.confirmBandCreated('temp_1_0');
        app.selectedId = 'b9';
    };
    app.selectedType = 'band';
    app.selectedId = 'temp_1_0';

    await press('Delete');
    assert.deepStrictEqual(deletes, ['b9'], 'deleted on the server under the id it has now');
    assert.strictEqual(sm.getBand('b9'), undefined);
    assert.strictEqual(sm.hasPendingChanges(), false, 'nothing left for the next Save to create again');
}

async function testADeletedLadderBandLeavesTheBandEditorAndMakesTheCalibrationStale() {
    // Nothing emitted BAND_DELETED (fixed 2026-10-13): the open Band Editor kept the deleted band's row, and deleting
    // a ladder band never marked the MW calibration stale, as editing one does (owner, 2026-10-13: a delete does too).
    // The real panels listen on the same bus; only the Band Editor's table drawing is replaced by a record of the
    // rows it would draw.
    const { sm, eventBus, lane, app, deletes, press } = editor(() => true);
    lane.lane_type = 'LADDER';
    for (const [id, y] of [['b0', 20], ['b1', 50]]) {
        const b = { id, lane_id: 7, position_y: y, band_type: 'MW_REFERENCE' };
        sm.setBand(id, b);
        lane.bands.push(b);
    }
    const bandEditor = new BandTablePanel({ eventBus, stateManager: sm, onDeleteBand: (id) => app._deleteBand(id) });
    Object.assign(bandEditor, { visible: true, currentLaneId: 7 });  // open on the lane, as showForLane leaves it
    const drawn = [];
    bandEditor.refresh = () => drawn.push(sm.getBandsForLane(7).map((b) => b.id));
    const calibration = new CalibrationPanel({ eventBus, stateManager: sm, apiClient: {} });
    calibration.calibrationResult = { r_squared: 0.998 };  // a calibration exists, as _loadExistingCalibration leaves it
    const stale = [];
    eventBus.on('calibration:stale', (d) => stale.push(d.reason));

    app.selectedType = 'band';
    app.selectedId = 'b1';
    await press('Delete');
    assert.deepStrictEqual(deletes, ['b1']);
    assert.deepStrictEqual(drawn, [['b0']], 'the Band Editor redraws once, without the deleted band');
    assert.strictEqual(calibration.isStale, true, 'a ladder band deleted: the MW calibration is stale');
    assert.deepStrictEqual(stale, ['Ladder lane #3 was modified (band deleted)']);
}

(async () => {
    await testTheDeleteKeyAsksBeforeDeletingASavedBand();
    await testADrawnBandSavedWhileTheDialogIsOpenIsStillDeleted();
    await testADeletedLadderBandLeavesTheBandEditorAndMakesTheCalibrationStale();
})().then(
    () => console.log('band delete confirm: all assertions passed'),
    (err) => {
        console.error('band delete confirm: FAILED\n' + (err && err.stack ? err.stack : err));
        process.exitCode = 1;
    },
);
