// Run: node gel_analyzer/static/gel_analyzer/js/gel-viewer/__tests__/lane-delete-saves.test.js
//
// A confirmed lane delete waited for Save (seen 2026-10-17): the lane and its bands left the canvas under a dialog
// saying "permanently" and "cannot be undone", and nothing reached the server until Save -- while a saved band was
// deleted at once. A saved lane is now deleted on the server at once, as a band is (GelViewerApp._deleteLane); its
// saved bands go with it server-side and nothing waits for Save. The real _deleteLane runs on a real StateManager;
// only the edges are stubbed (the dialog's answer, the API client, the SVG renderer, the toasts).
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
globalThis.document = { getElementById: () => null, addEventListener() {} };
globalThis.window = globalThis;

require('../event-bus.js');
require('../state-manager.js');
require('../gel-viewer.js');
const { EventBus, Events, StateManager, App } = window.GelViewer;

const settle = () => new Promise((resolve) => setImmediate(resolve));

function editor({ answer = true, deleteLane = async () => {} } = {}) {
    const eventBus = new EventBus();
    const sm = new StateManager({ analysisId: 'a1', eventBus });
    const deletes = [];
    const toasts = [];
    const lanesDeleted = [];
    eventBus.on(Events.LANE_DELETED, (lane) => lanesDeleted.push(lane.id));
    const app = Object.create(App.prototype);
    Object.assign(app, {
        isEditable: true,
        stateManager: sm,
        eventBus,
        selectedType: 'lane',
        selectedId: null,
        confirmationManager: { confirmDeleteLane: async () => answer },
        apiClient: { deleteLane: async (id) => { deletes.push(id); return deleteLane(id); } },
        renderer: { removeBand() {}, removeLane() {}, updateLaneNumber() {} },
        toasts: {
            pending: () => ({ success: (m) => toasts.push(['success', m]), error: (m) => toasts.push(['error', m]),
                info: (m) => toasts.push(['info', m]) }),
            info: (m) => toasts.push(['info', m]),
        },
        _deselect() { this.selectedType = null; this.selectedId = null; },
        _updateToolbarState() {},
    });
    return { sm, app, deletes, toasts, lanesDeleted };
}

function savedLane(sm, id, number, bandIds) {
    const lane = { id, lane_number: number, x: number * 50, y: 0, width: 40, height: 300, bands: [] };
    sm.setLane(id, lane);
    for (const bandId of bandIds) {
        const band = { id: bandId, lane_id: id, position_y: 40, band_type: 'POI' };
        sm.setBand(bandId, band);
        lane.bands.push(band);
    }
    return lane;
}

async function testAConfirmedDeleteOfASavedLaneIsSentAtOnce() {
    const { sm, app, deletes, toasts, lanesDeleted } = editor();
    savedLane(sm, 7, 3, ['b1', 'b2']);
    savedLane(sm, 8, 4, ['b3']);
    // Edits waiting for Save on the lane and one of its bands, one on another lane
    sm.trackLaneUpdate(7, { width: 44 });
    sm.trackBandUpdate('b1', { position_y: 42 });
    sm.trackLaneUpdate(8, { width: 45 });
    app.selectedId = 7;

    await app._deleteLane(7);
    await settle();
    assert.deepStrictEqual(deletes, [7], 'one DELETE, at once, no Save needed');
    assert.strictEqual(sm.getLane(7), undefined);
    assert.strictEqual(sm.getBand('b1'), undefined, 'its bands leave the canvas with it');
    assert.strictEqual(sm.pendingChanges.bands.deleted.size, 0, 'its saved bands go with it on the server: none tracked');
    assert.strictEqual(sm.pendingChanges.lanes.deleted.size, 0, 'nothing left for Save to delete');
    assert.strictEqual(sm.pendingCount(), 1, 'only the other lane\'s edit still waits for Save');
    assert.deepStrictEqual(toasts.at(-1), ['success', 'Lane 3 deleted']);
    assert.deepStrictEqual(lanesDeleted, [7], 'LANE_DELETED announced');
    assert.strictEqual(app.selectedId, null, 'deselected');
}

async function testCancelSendsNothing() {
    const { sm, app, deletes, lanesDeleted } = editor({ answer: false });
    savedLane(sm, 7, 3, ['b1']);
    await app._deleteLane(7);
    await settle();
    assert.deepStrictEqual(deletes, []);
    assert.ok(sm.getLane(7) && sm.getBand('b1'), 'the lane and its band stay');
    assert.deepStrictEqual(lanesDeleted, []);
}

async function testSignedOutTheDeleteWaitsForSave() {
    const expired = Object.assign(new Error('Your session has expired'), { name: 'SessionExpiredError' });
    const { sm, app, deletes, toasts } = editor({ deleteLane: async () => { throw expired; } });
    savedLane(sm, 7, 3, ['b1', 'b2']);
    await app._deleteLane(7);
    await settle();
    assert.deepStrictEqual(deletes, [7]);
    assert.ok(sm.pendingChanges.lanes.deleted.has(7), 'the next Save deletes it, once logged in again');
    assert.strictEqual(sm.pendingCount(), 1, 'the lane counts once');
    assert.strictEqual(toasts.at(-1)[0], 'info');
}

async function testALaneNeverSavedIsOnlyForgotten() {
    const { sm, app, deletes } = editor();
    const lane = { id: 'temp_1_0', _isNew: true, lane_number: 1, x: 10, y: 0, width: 40, height: 300, bands: [] };
    sm.setLane(lane.id, lane);
    sm.trackLaneCreation(lane.id, lane);
    const band = { id: 'temp_2_0', _isNew: true, _parentLaneId: lane.id, lane_id: lane.id, position_y: 40 };
    sm.setBand(band.id, band);
    sm.trackBandCreation(band.id, band);
    lane.bands.push(band);

    await app._deleteLane(lane.id);
    await settle();
    assert.deepStrictEqual(deletes, [], 'nothing on the server to delete');
    assert.strictEqual(sm.hasPendingChanges(), false, 'nothing left for Save to create');
}

(async () => {
    await testAConfirmedDeleteOfASavedLaneIsSentAtOnce();
    await testCancelSendsNothing();
    await testSignedOutTheDeleteWaitsForSave();
    await testALaneNeverSavedIsOnlyForgotten();
})().then(
    () => console.log('lane delete saves: all assertions passed'),
    (err) => {
        console.error('lane delete saves: FAILED\n' + (err && err.stack ? err.stack : err));
        process.exitCode = 1;
    },
);
