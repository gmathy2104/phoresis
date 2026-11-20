// Run: node gel_analyzer/static/gel_analyzer/js/gel-viewer/__tests__/set-mw.test.js
//
// The band menu's "Set Molecular Weight" sent {molecular_weight} (fixed 2026-10-13): the band PUT reads only
// estimated_mw_kda, so the value was dropped, yet the view still saved the band and its post_save receiver wiped the
// lane's densitometry. Any band save does that, so an answer left unchanged must send nothing either. The real
// ContextMenu action runs into the real GelViewerApp._updateBand on a real StateManager; only the edges are stubbed
// (the editor's value window ConfirmationManager.prompt - it answers the text as typed or null, as window.prompt
// did - the API client, the SVG, the menu's DOM).
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
require('../panels/context-menu.js');
const { EventBus, StateManager, App, ContextMenu } = window.GelViewer;

async function testSetMolecularWeight() {
    const eventBus = new EventBus();
    const sm = new StateManager({ analysisId: 'a1', eventBus });
    sm.setLane(7, { id: 7, lane_number: 1, x: 10, y: 0, width: 40, height: 300, bands: [] });
    sm.setBand('b1', { id: 'b1', lane_id: 7, position_y: 50, band_type: 'POI', estimated_mw_kda: 55 });

    const puts = [];
    const app = Object.create(App.prototype);
    Object.assign(app, {
        stateManager: sm,
        eventBus,
        svg: { findOne: () => null },
        apiClient: { updateBand: async (id, data) => { puts.push({ id, data }); } },
        _showMessage() {},
    });

    const messages = [];
    const menu = new ContextMenu({
        eventBus,
        stateManager: sm,
        showMessage: (m) => messages.push(m),
        onUpdateBand: (id, data) => app._updateBand(id, data),
        getSelectedAnnotation: () => ({ type: 'band', id: 'b1' }),
    });

    const offered = [];
    const answers = [];
    globalThis.gelViewer = {
        confirmationManager: {
            prompt: async (options) => {
                offered.push(options.value);
                return answers.shift();
            },
        },
    };
    const setMW = async (answer) => {
        answers.push(answer);
        menu._handleAction('set-mw');
        await new Promise((resolve) => setImmediate(resolve));
    };

    await setMW('62,5');
    assert.deepStrictEqual(puts, [{ id: 'b1', data: { estimated_mw_kda: 62.5 } }], 'the field the band PUT reads');
    assert.strictEqual(offered[0], 55, 'the prompt offers the current MW');
    assert.strictEqual(sm.getBand('b1').estimated_mw_kda, 62.5, 'the properties read the new MW');
    assert.strictEqual(sm.hasPendingChanges(), false, 'saved at once: nothing left for the next Save');

    await setMW('62.5');
    assert.strictEqual(puts.length, 1, 'an unchanged MW sends nothing: any band save wipes the lane densitometry');

    await setMW('abc');
    await setMW('0');
    assert.strictEqual(puts.length, 1, 'an invalid MW sends nothing');
    assert.deepStrictEqual(messages, ['Invalid molecular weight value', 'Invalid molecular weight value']);

    await setMW(null);
    assert.strictEqual(puts.length, 1, 'Cancel sends nothing');

    await setMW('');
    assert.deepStrictEqual(puts[1], { id: 'b1', data: { estimated_mw_kda: null } }, 'an empty answer clears the MW');
    assert.strictEqual(sm.getBand('b1').estimated_mw_kda, null);
}

testSetMolecularWeight().then(
    () => console.log('set molecular weight: all assertions passed'),
    (err) => {
        console.error('set molecular weight: FAILED\n' + (err && err.stack ? err.stack : err));
        process.exitCode = 1;
    },
);
