// Run: node gel_analyzer/static/gel_analyzer/js/gel-viewer/__tests__/poi-band-mw-edit-keeps-ladder.test.js
//
// An MW edit of a POI band turned its MW Ladder lane back into a Sample lane (found on devlocal, 2026-10-13): the lane
// auto-promote listened to BAND_UPDATED, which every band edit fires (an MW, a label, a ladder template's Apply), so a
// POI band left in a lane retyped MW Ladder made it SAMPLE again at its first touch, and the lane PUT made the server
// drop the ladder template. Owner, 2026-10-13: the lane follows a band's type only when that type changes. The edits
// go through the real GelViewerApp._updateBand on a real StateManager, with the editor's own event wiring
// (_wireEventBus); only the edges are stubbed (the API client, the SVG, the toolbar).
const assert = require('assert');

globalThis.window = globalThis;
globalThis.document = { getElementById: () => null, querySelector: () => null, addEventListener() {} };
Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: { getItem: () => null, setItem() {}, removeItem() {} },
});

require('../event-bus.js');
require('../state-manager.js');
require('../gel-viewer.js');
const { EventBus, StateManager, App, Events } = window.GelViewer;

const settle = () => new Promise((resolve) => setImmediate(resolve));

function editor(laneType, bands) {
    const eventBus = new EventBus();
    const sm = new StateManager({ analysisId: 'a1', eventBus });
    sm.setLane(7, { id: 7, lane_number: 2, lane_type: laneType, ladder_template_id: 'tpl', x: 10, y: 0, width: 40,
        height: 300, bands: [] });
    bands.forEach(([id, y, type]) => sm.setBand(id, { id, lane_id: 7, position_y: y, band_type: type,
        estimated_mw_kda: null }));

    const requests = [];
    const apiClient = {
        updateBand: async (id, data) => { requests.push(['band PUT', id, data]); },
        updateLane: async (id, data) => { requests.push(['lane PUT', id, data]); },
    };
    const app = Object.create(App.prototype);
    Object.assign(app, { stateManager: sm, eventBus, apiClient, svg: { findOne: () => null }, _showMessage() {},
        _updateToolbarState() {} });
    app._wireEventBus();
    return { app, sm, eventBus, requests };
}

async function testAnMwEditOfAPoiBandLeavesTheLadderALadder() {
    const { app, sm, eventBus, requests } = editor('LADDER', [['b1', 50, 'MW_REFERENCE'], ['b2', 120, 'POI']]);

    // The band form's Save sends the type with the other fields, unchanged; the Band editor's table sends the field.
    app._updateBand('b2', { band_type: 'POI', label: '', estimated_mw_kda: 52, notes: '' });
    await settle();
    app._updateBand('b2', { estimated_mw_kda: 55 });
    await settle();
    // A band update that is no edit of the type at all (a polygon refined in place).
    eventBus.emit(Events.BAND_UPDATED, sm.getBand('b2'));
    await settle();

    assert.deepStrictEqual(requests, [
        ['band PUT', 'b2', { band_type: 'POI', label: '', estimated_mw_kda: 52, notes: '' }],
        ['band PUT', 'b2', { estimated_mw_kda: 55 }],
    ], 'only the band is saved: no lane PUT, so the server keeps the ladder template');
    assert.strictEqual(sm.getLane(7).lane_type, 'LADDER', 'the lane stays an MW Ladder');
    assert.strictEqual(sm.getBand('b2').estimated_mw_kda, 55, 'and the band has its MW');
    assert.strictEqual(sm.hasPendingChanges(), false, 'nothing is left for the next Save');
}

async function testANewTypeStillTakesTheLaneWithIt() {
    const { app, sm, requests } = editor('SAMPLE', [['b1', 50, 'OTHER'], ['b2', 120, 'OTHER']]);

    app._updateBand('b1', { band_type: 'MW_REFERENCE' });
    await settle();
    assert.strictEqual(sm.getLane(7).lane_type, 'LADDER', 'a band typed MW Reference makes the lane a ladder');
    assert.deepStrictEqual(requests.splice(0), [
        ['lane PUT', 7, { lane_type: 'LADDER' }],
        ['band PUT', 'b1', { band_type: 'MW_REFERENCE' }],
    ]);

    app._updateBand('b2', { band_type: 'POI' });
    await settle();
    assert.strictEqual(sm.getLane(7).lane_type, 'SAMPLE', 'and a band typed POI there makes it a sample lane again');
    assert.deepStrictEqual(requests, [
        ['lane PUT', 7, { lane_type: 'SAMPLE' }],
        ['band PUT', 'b2', { band_type: 'POI' }],
    ]);
}

testAnMwEditOfAPoiBandLeavesTheLadderALadder()
    .then(testANewTypeStillTakesTheLaneWithIt)
    .then(
        () => console.log('poi-band-mw-edit-keeps-ladder: 2 tests passed'),
        (err) => {
            console.error('poi-band-mw-edit-keeps-ladder: FAILED\n' + (err && err.stack ? err.stack : err));
            process.exitCode = 1;
        },
    );
