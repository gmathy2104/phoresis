// Run: node gel_analyzer/static/gel_analyzer/js/gel-viewer/__tests__/session-expired.test.js
//
// Signed out, a band PUT was redirected (302) to the login page; fetch followed it, the login page answered 200 with
// its HTML, and the client only looked at `response.ok`: the editor dropped the pending change and said "Band updated"
// (measured on devlocal 2026-10-13, task_b27a3d8b). Logging in again then got a 403: a login rotates the CSRF token and
// the client sent the one the page was rendered with. The real GelViewerApp._updateBand runs on a real StateManager and
// a real APIClient; only fetch and the cookie jar are stubbed.
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
globalThis.document = { getElementById: () => null, addEventListener() {}, cookie: '' };
globalThis.window = globalThis;

require('../event-bus.js');
require('../state-manager.js');
require('../api-client.js');
require('../gel-viewer.js');
const { EventBus, StateManager, APIClient, App, Events } = window.GelViewer;

const html = { get: (name) => (name.toLowerCase() === 'content-type' ? 'text/html; charset=utf-8' : null) };
const json = { get: (name) => (name.toLowerCase() === 'content-type' ? 'application/json' : null) };
const answers = [];
const sent = [];
globalThis.fetch = async (url, init) => {
    sent.push({ url, method: init && init.method, csrf: init && init.headers && init.headers['X-CSRFToken'] });
    return answers.shift();
};
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

async function testSignedOutSaveStaysPending() {
    const eventBus = new EventBus();
    const sm = new StateManager({ analysisId: 'a1', eventBus });
    sm.setLane(7, { id: 7, lane_number: 1, x: 10, y: 0, width: 40, height: 300, bands: [], lane_type: 'CALIBRATION' });
    sm.setBand('b1', { id: 'b1', lane_id: 7, position_y: 50, band_type: 'POI', estimated_mw_kda: 55 });
    sm.setBand('b2', { id: 'b2', lane_id: 7, position_y: 90, band_type: 'OTHER' });
    sm.setBand('bq', { id: 'bq', lane_id: 7, position_y: 120, band_type: 'CALIBRATION' });
    sm.setBand('bp', { id: 'bp', lane_id: 7, position_y: 150, band_type: 'CALIBRATION' });

    const api = new APIClient({ analysisId: 'a1', imageId: 'i1', csrfToken: 'page-token', eventBus });
    const app = Object.create(App.prototype);
    const laneQuestions = [];
    Object.assign(app, {
        stateManager: sm, eventBus, svg: { findOne: () => null }, apiClient: api, renderer: { removeBand() {} },
        propertiesPanel: { changeLaneType: (laneId, type) => laneQuestions.push([laneId, type]) },
        _showMessage() {}, _updateToolbarState() {},
    });
    const notices = [];
    let restored = 0;
    eventBus.on(Events.SESSION_EXPIRED, ({ message }) => notices.push(message));
    eventBus.on(Events.SESSION_RESTORED, () => { restored += 1; });

    // Signed out: the PUT lands on the login page, 200.
    answers.push({
        ok: true, status: 200, redirected: true, headers: html, json: async () => { throw new SyntaxError('<'); },
        url: 'http://localhost/authentication/login/?next=/api/bands/b1/',
    });
    app._updateBand('b1', { estimated_mw_kda: 62.5 });
    await settle();
    assert.deepStrictEqual(sm.pendingChanges.bands.updated.get('b1'), { estimated_mw_kda: 62.5 },
        'the change the server never got stays pending for the next Save');
    assert.strictEqual(sm.hasPendingChanges(), true);
    assert.strictEqual(notices.length, 1, 'the editor is told');
    assert.match(notices[0], /signed out/);
    assert.match(notices[0], /Log in again/);

    // A success that is not JSON (no redirect seen) fails too; the notice is not repeated while signed out.
    answers.push({ ok: true, status: 200, redirected: false, url: 'http://localhost/x/', headers: html });
    await assert.rejects(api.updateBand('b1', { estimated_mw_kda: 62.5 }), /web page, not data/);
    assert.strictEqual(notices.length, 1, 'one notice, however many requests fail behind it');

    // A saved band deleted while signed out (the DELETE lands on the login page, 405): no reload to bring it back
    // would work either, so the delete waits for the next Save like any other change.
    answers.push({ ok: false, status: 405, redirected: true, headers: html,
        url: 'http://localhost/authentication/login/?next=/api/bands/b2/' });
    await app._deleteBand('b2');
    await settle();
    assert.strictEqual(sm.pendingChanges.bands.deleted.has('b2'), true, 'the delete stays pending');

    // A band of a CALIBRATION lane typed POI while signed out: its PUT did not land, its calibration point is still
    // there, so the lane question is not asked (it waits for a saved PUT, 4bdc44f74); the type stays pending.
    answers.push({ ok: true, status: 200, redirected: true, headers: html,
        url: 'http://localhost/authentication/login/?next=/api/bands/bq/' });
    app._updateBand('bq', { band_type: 'POI' });
    await settle();
    assert.deepStrictEqual(laneQuestions, [], 'no lane question over a PUT that did not land');
    assert.deepStrictEqual(sm.pendingChanges.bands.updated.get('bq'), { band_type: 'POI' });

    // Logged in again in another tab: the login rotated the CSRF cookie, the PUT sends the new token and is saved.
    document.cookie = 'sessionid_x=s; csrftoken=rotated';
    answers.push({ ok: true, status: 200, redirected: false, url: 'http://localhost/api/bands/b1/',
        headers: json, json: async () => ({ success: true }) });
    app._updateBand('b1', { estimated_mw_kda: 62.5 });
    await settle();
    assert.strictEqual(sent[sent.length - 1].csrf, 'rotated', 'the token the server holds now, not the page one');
    assert.strictEqual(sm.pendingChanges.bands.updated.has('b1'), false, 'the band edit is saved');
    assert.strictEqual(restored, 1, 'the first answer through closes the notice');

    // Logged in, the same edit on another band of the lane asks the lane question once its PUT is saved.
    answers.push({ ok: true, status: 200, redirected: false, url: 'http://localhost/api/bands/bp/',
        headers: json, json: async () => ({ success: true }) });
    app._updateBand('bp', { band_type: 'POI' });
    await settle();
    assert.deepStrictEqual(laneQuestions, [[7, 'SAMPLE']], 'a saved PUT asks the lane question');

    // A refusal with its JSON body is no session problem: the lane_type guard's 409 and the ladder template's 400
    // reach their callers as before, and nothing is announced.
    answers.push({ ok: false, status: 409, redirected: false, url: 'http://localhost/api/v1/lanes/7/',
        headers: json, json: async () => ({ detail: 'calibration points', dependent_band_ids: ['b1'] }) });
    const conflict = await api.patchLaneV1(7, { lane_type: 'SAMPLE' });
    assert.deepStrictEqual(conflict.dependent_band_ids, ['b1'], 'the 409 reaches the lane form');
    answers.push({ ok: false, status: 400, redirected: false, url: 'http://localhost/x/', headers: json,
        json: async () => ({ error: 'Lane 1: ladder_template_id must be a ladder template' }) });
    await assert.rejects(api.updateLanesBulk([{ id: 7 }]), /ladder_template_id must be/);
    assert.strictEqual(notices.length, 1, 'no "log in again" for a refusal');
}

testSignedOutSaveStaysPending().then(
    () => console.log('session expired: all assertions passed'),
    (err) => {
        console.error('session expired: FAILED\n' + (err && err.stack ? err.stack : err));
        process.exitCode = 1;
    },
);
