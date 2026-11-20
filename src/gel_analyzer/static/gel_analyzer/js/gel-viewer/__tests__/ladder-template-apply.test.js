// Run: node gel_analyzer/static/gel_analyzer/js/gel-viewer/__tests__/ladder-template-apply.test.js
//
// A ladder's MW values from a template (owner, 2026-10-13): the lane form's Apply and the Band editor's share
// LadderTemplateApply. The server gives the template's values to the bands IT holds, in their saved order, so nothing
// is sent while the lane or a band of it waits for Save (the Band editor's own Apply, before, put the values one band
// off with no error, or failed on a web page parsed as JSON). Once applied, a value reaches the same band object
// through GelViewerApp._syncBandLocally, the path a hand edit of one MW takes, so the real CalibrationPanel marks its
// calibration stale; a choice of template waiting for Save is the one the server now holds. Real StateManager,
// EventBus, LadderTemplateApply, _syncBandLocally and CalibrationPanel; only the edges are stubbed (API, dialog, DOM).
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
const element = () => {
    let text = '';
    return {
        style: {}, classList: { add() {}, remove() {} }, addEventListener() {}, appendChild() {},
        set textContent(v) { text = String(v); },
        get innerHTML() { return text; },
        set innerHTML(v) { text = String(v); },
    };
};
globalThis.document = { getElementById: () => null, createElement: element, querySelector: () => null, addEventListener() {} };
globalThis.window = globalThis;
globalThis.addEventListener = () => {};  // the panel's window listeners

require('../event-bus.js');
require('../state-manager.js');
require('../ladder-template-apply.js');
require('../gel-viewer.js');
require('../panels/calibration-panel.js');
const { EventBus, StateManager, App, LadderTemplateApply, CalibrationPanel, Events } = window.GelViewer;

const TEMPLATE = 'tpl-all-blue';

function editor() {
    const eventBus = new EventBus();
    const sm = new StateManager({ analysisId: 'a1', eventBus });
    sm.setLane(7, { id: 7, lane_number: 1, lane_type: 'LADDER', ladder_template_id: null, x: 10, y: 0, width: 40, height: 300, bands: [] });
    [['b1', 50, 250], ['b2', 90, 140], ['b3', 130, null]].forEach(([id, y, mw]) => {
        sm.setBand(id, { id, lane_id: 7, position_y: y, band_type: 'MW_REFERENCE', estimated_mw_kda: mw, role: 'ladder' });
    });

    const app = Object.create(App.prototype);
    Object.assign(app, { stateManager: sm, eventBus, svg: { findOne: () => null } });
    const calibration = new CalibrationPanel({ eventBus, stateManager: sm, apiClient: {} });
    calibration.calibrationResult = { method: 'LOG_LINEAR' };  // a calibration already computed

    const posts = [];
    const apiClient = {
        applyLadderTemplate: async (laneId, templateId) => {
            posts.push([laneId, templateId]);
            return {
                bands_updated: 3, template_name: 'All Blue', warnings: null,
                bands: [['b1', 250], ['b2', 150], ['b3', 100]].map(([id, mw]) => ({ id, lane_id: 7, estimated_mw_kda: mw })),
            };
        },
    };
    const answers = [];
    const confirmationManager = { modal: {}, show: async () => answers.shift() };
    const helper = new LadderTemplateApply({
        eventBus, stateManager: sm, apiClient,
        onSyncBandLocal: (id, data) => app._syncBandLocally(id, data),
        getConfirmationManager: () => confirmationManager,
    });
    const events = [];
    eventBus.on(Events.BAND_UPDATED, (band) => events.push(['band', band.id]));
    eventBus.on(Events.MW_BANDS_UPDATED, (data) => events.push(['mw', data.laneId]));
    return { sm, helper, calibration, posts, answers, events };
}

async function testNothingSentWhileTheLaneWaitsForSave() {
    const { sm, helper, posts } = editor();

    // A band edit the server does not have (a PUT that failed): the values would go to the saved order.
    sm.trackBandUpdate('b2', { position_y: 10 });
    let outcome = await helper.apply(7, TEMPLATE);
    assert.strictEqual(outcome.status, 'refused');
    assert.match(outcome.message, /^Save first/);
    assert.strictEqual(sm.pendingCount(), 1, 'the edit still waits for Save');

    // A lane typed MW Ladder here: the server still holds another type.
    sm.confirmUpdateSaved('bands', 'b2', { position_y: 10 });
    sm.trackLaneUpdate(7, { lane_type: 'LADDER' });
    outcome = await helper.apply(7, TEMPLATE);
    assert.match(outcome.message, /^Save first/);

    // A band typed POI in the ladder: its value would run the auto-promote and make the lane a Sample lane.
    sm.confirmUpdateSaved('lanes', 7, { lane_type: 'LADDER' });
    sm.getBand('b3').band_type = 'POI';
    outcome = await helper.apply(7, TEMPLATE);
    assert.strictEqual(outcome.status, 'refused');
    assert.match(outcome.message, /^Band 3 \(POI\)/);

    assert.deepStrictEqual(posts, [], 'nothing was sent');
}

async function testAppliedValuesTakeTheHandEditPath() {
    const { sm, helper, calibration, posts, answers, events } = editor();
    const bands = sm.getBandsForLane(7);
    sm.trackLaneUpdate(7, { ladder_template_id: TEMPLATE });  // chosen in the form, waiting for Save
    sm.saveToLocalStorage();

    // The lane form asks before replacing values: "Keep values" sends nothing.
    answers.push(false);
    let outcome = await helper.apply(7, TEMPLATE, { confirmOverwrite: true, templateName: 'All Blue' });
    assert.strictEqual(outcome.status, 'cancelled');
    assert.deepStrictEqual(posts, []);

    answers.push(true);
    outcome = await helper.apply(7, TEMPLATE, { confirmOverwrite: true, templateName: 'All Blue' });
    assert.strictEqual(outcome.status, 'applied');
    assert.deepStrictEqual(posts, [[7, TEMPLATE]]);

    const after = sm.getBandsForLane(7);
    assert.ok(after.every((band, i) => band === bands[i]), 'the same band objects, not the server copies');
    assert.deepStrictEqual(after.map(b => b.estimated_mw_kda), [250, 150, 100]);
    assert.ok(after.every(b => b.role === 'ladder'), 'what only the editor holds stays');
    assert.deepStrictEqual(events, [['band', 'b2'], ['band', 'b3'], ['mw', 7]], 'b1 kept its value: no event');
    assert.strictEqual(calibration.isStale, true, 'the MW calibration is stale, as after a hand edit of one MW');

    assert.strictEqual(sm.getLane(7).ladder_template_id, TEMPLATE);
    assert.strictEqual(sm.pendingCount(), 0, 'the template choice is the one the server holds');
    assert.strictEqual(localStorage.getItem('gelViewer_a1'), null, 'and the crash backup no longer offers it');
}

(async () => {
    await testNothingSentWhileTheLaneWaitsForSave();
    await testAppliedValuesTakeTheHandEditPath();
    console.log('ladder-template-apply: 2 tests passed');
})().catch((err) => {
    console.error(err);
    process.exit(1);
});
