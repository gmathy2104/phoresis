// Run: node gel_analyzer/static/gel_analyzer/js/gel-viewer/__tests__/autodetect-replace.test.js
//
// The wand's Replace & Detect (GelViewerApp._autoDetect) deletes every lane on the server, then empties the maps
// with no reload: it must end with nothing pending. It did not (fixed 2026-10-12): a lane drawn and not yet saved
// was created again by the next Save beside the detected lanes, and the crash backup offered the stale changes back.
// The real _autoDetect runs on a real StateManager; only the outer edges are stubbed (API, dialog, SVG, ONNX).
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
globalThis.document = { getElementById: () => ({}) };
globalThis.window = globalThis;

require('../event-bus.js');
require('../state-manager.js');
require('../gel-viewer.js');
const { EventBus, StateManager, App } = window.GelViewer;

async function testReplaceLeavesNothingPending() {
    const sm = new StateManager({ analysisId: 'a1', eventBus: new EventBus() });

    // A saved lane edited and one of its bands edited, both waiting for Save; a lane drawn and never saved.
    sm.setLane(7, { id: 7, lane_number: 1, x: 10, y: 0, width: 40, height: 300, bands: [] });
    sm.trackLaneUpdate(7, { lane_type: 'CONTROL' });
    sm.setBand('b1', { id: 'b1', lane_id: 7, position_y: 50 });
    sm.trackBandUpdate('b1', { band_type: 'POI' });
    const drawn = { id: 'temp_1_0', _isNew: true, lane_number: 2, x: 100, y: 0, width: 40, height: 300, bands: [] };
    sm.setLane(drawn.id, drawn);
    sm.trackLaneCreation(drawn.id, drawn);
    sm.saveToLocalStorage();
    assert.strictEqual(sm.pendingCount(), 3, 'setup: three changes wait for Save');
    assert.ok(localStorage.getItem('gelViewer_a1'), 'setup: the crash backup holds them');

    let serverLanesDeleted = 0;
    const app = Object.create(App.prototype);
    Object.assign(app, {
        isEditable: true,
        stateManager: sm,
        readout: { referenceLaneId: 7 },
        confirmationManager: { confirmDetectLanes: async () => true },
        apiClient: { deleteAllLanes: async () => { serverLanesDeleted += 1; return { deleted_count: 1 }; } },
        renderer: { clearAll() {}, setReferenceLane() {} },
        inferenceEngine: { isInferring: false, runInference: async () => ({ detections: [] }) },
        reviewPanel: { show() {} },
        _updateToolbarState() {},
        _showLoading() {},
        _hideLoading() {},
        _showMessage() {},
    });

    await app._autoDetect();

    assert.strictEqual(serverLanesDeleted, 1, 'the replace path ran: every lane was deleted on the server');
    assert.strictEqual(sm.getLaneCount(), 0);
    assert.strictEqual(sm.hasPendingChanges(), false, 'no lane or band change may wait for the next Save');
    assert.strictEqual(sm.pendingCount(), 0, '"N unsaved changes" is hidden');
    assert.strictEqual(sm.isDirty, false);
    assert.strictEqual(localStorage.getItem('gelViewer_a1'), null, 'the backup offers nothing on the next load');
}

testReplaceLeavesNothingPending().then(
    () => console.log('autodetect replace: all assertions passed'),
    (err) => {
        console.error('autodetect replace: FAILED\n' + (err && err.stack ? err.stack : err));
        process.exitCode = 1;
    },
);
