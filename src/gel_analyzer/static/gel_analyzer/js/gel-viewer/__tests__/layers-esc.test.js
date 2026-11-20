// Run: node gel_analyzer/static/gel_analyzer/js/gel-viewer/__tests__/layers-esc.test.js
//
// The owner's rule for the editor's windows (2026-10-12), carried by GelViewer.Layers (layers.js): Esc closes the
// window on top and only that one, and never decides - a confirm closed by Esc answers "cancel" without a click on
// any of its buttons (the backup restore reads a click on Cancel as Discard) - and a modal holds the editor's
// shortcuts while it is open (Delete behind a confirm opened a second one) and keeps Tab inside it. The real layers.js and the real
// ConfirmationManager run on a minimal DOM stand-in; the editor's shortcuts are one keydown listener on document,
// in the bubble phase, as EventHandler's.
const assert = require('assert');

class FakeElement {
    constructor(id, parent = null, tag = 'div') {
        this.id = id;
        this.tag = tag;
        this.parent = parent;
        this.isConnected = true;
        this.listeners = {};
        this.classes = new Set();
        this.attrs = {};
        this.textContent = '';
        this.innerHTML = '';
        this.className = '';
        this.disabled = false;
        this.children = [];
        if (parent) parent.children.push(this);
        if (id) byId.set(id, this);
    }

    get classList() {
        const c = this.classes;
        return { add: (x) => c.add(x), remove: (x) => c.delete(x), contains: (x) => c.has(x) };
    }

    addEventListener(type, fn) {
        (this.listeners[type] = this.listeners[type] || []).push(fn);
    }

    removeEventListener(type, fn) {
        this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn);
    }

    contains(node) {
        for (let n = node; n; n = n.parent) if (n === this) return true;
        return false;
    }

    matches(selector) {
        return selector.split(',').map((s) => s.trim()).includes(this.tag);
    }

    click() {
        (this.listeners.click || []).forEach((fn) => fn({ target: this }));
    }

    focus() {
        document.activeElement = this;
    }

    /** Descendants in document order whose tag the selector names (enough for layers.js's FOCUSABLE list). */
    querySelectorAll(selector) {
        const tags = selector.split(',').map((part) => part.trim().split(/[[:]/)[0]).filter(Boolean);
        const found = [];
        const walk = (node) => node.children.forEach((child) => {
            if (tags.includes(child.tag)) found.push(child);
            walk(child);
        });
        walk(this);
        return found;
    }

    getClientRects() { return [{}]; }
    closest() { return null; }
    querySelector() { return null; }
    setAttribute(k, v) { this.attrs[k] = v; }
    removeAttribute(k) { delete this.attrs[k]; }
}

const byId = new Map();
const documentKeydown = { capture: [], bubble: [] };
globalThis.Element = FakeElement;
globalThis.window = globalThis;
globalThis.requestAnimationFrame = (fn) => fn();
globalThis.document = {
    activeElement: null,
    body: null,
    getElementById: (id) => byId.get(id) || null,
    addEventListener(type, fn, capture) {
        if (type === 'keydown') documentKeydown[capture ? 'capture' : 'bubble'].push(fn);
    },
};
const body = new FakeElement(null, null, 'body');
document.body = body;
document.activeElement = body;

// The confirm dialog's markup (annotate_standalone.html), the parts ConfirmationManager reads.
const confirmModal = new FakeElement('gv-confirm-modal', body);
const confirmCancel = new FakeElement('gv-confirm-cancel', confirmModal, 'button');
const confirmAction = new FakeElement('gv-confirm-action', confirmModal, 'button');
new FakeElement('gv-confirm-title', confirmModal);
new FakeElement('gv-confirm-body', confirmModal);

require('../layers.js');
require('../confirmation-manager.js');
const { Layers, ConfirmationManager } = window.GelViewer;

// The editor's shortcuts: what reaches them.
const editorKeys = [];
document.addEventListener('keydown', (e) => editorKeys.push(e.key), false);

/** A keydown as the browser delivers it: document capture, then the target and its ancestors, then document. */
function press(key, target = document.activeElement || body, extra = {}) {
    const ev = {
        key, target, repeat: false, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...extra,
        defaultPrevented: false, stopped: false, stoppedNow: false,
        preventDefault() { this.defaultPrevented = true; },
        stopPropagation() { this.stopped = true; },
        stopImmediatePropagation() { this.stopped = true; this.stoppedNow = true; },
    };
    for (const fn of documentKeydown.capture) {
        fn(ev);
        if (ev.stoppedNow) return ev;
    }
    if (ev.stopped) return ev;
    for (let n = target; n; n = n.parent) {
        for (const fn of n.listeners.keydown || []) {
            fn(ev);
            if (ev.stoppedNow) return ev;
        }
        if (ev.stopped) return ev;
    }
    for (const fn of documentKeydown.bubble) {
        fn(ev);
        if (ev.stoppedNow) return ev;
    }
    return ev;
}

function testEscClosesTheTopLayerOnly() {
    const closed = [];
    const panel = new FakeElement('panel', body);
    const dialog = new FakeElement('dialog', body);
    Layers.open(panel, { close: () => { closed.push('panel'); Layers.close(panel); } });
    Layers.open(dialog, { modal: true, close: () => { closed.push('dialog'); Layers.close(dialog); } });
    assert.strictEqual(Layers.top(), dialog, 'setup: the dialog opened last is on top');

    press('Escape', body, { repeat: true });
    assert.deepStrictEqual(closed, [], 'a held Esc (auto-repeat) closes nothing more');

    press('Escape');
    assert.deepStrictEqual(closed, ['dialog'], 'one Esc closes the top window and only that one');
    assert.strictEqual(Layers.top(), panel, 'the panel under it stays open, now on top');

    press('Escape');
    assert.deepStrictEqual(closed, ['dialog', 'panel'], 'the next Esc closes the panel');
    assert.strictEqual(Layers.hasOpen(), false);
}

async function testEscAnswersCancelWithoutAClick() {
    const confirm = new ConfirmationManager();
    // As GelViewerApp._offerBackup does: a click on Cancel deletes the crash backup (Discard).
    let discarded = false;
    confirmCancel.addEventListener('click', () => { discarded = true; });
    let confirmedByClick = false;
    confirmAction.addEventListener('click', () => { confirmedByClick = true; });

    const answer = confirm.show({ title: 'Restore unsaved changes?', danger: false });
    assert.ok(confirmModal.classList.contains('show'), 'setup: the dialog is shown');
    assert.strictEqual(Layers.top(), confirmModal, 'setup: and on top of the stack');

    press('Escape');
    assert.strictEqual(await answer, false, 'Esc answers "cancel": nothing is decided');
    assert.strictEqual(discarded, false, 'no click on Cancel (it would discard the backup)');
    assert.strictEqual(confirmedByClick, false, 'no click on the action button');
    assert.ok(!confirmModal.classList.contains('show'), 'the dialog is closed');
    assert.strictEqual(Layers.hasOpen(), false);

    // Witness: a real click on Cancel does run the page's handler, so "not discarded" above is not vacuous.
    const second = confirm.show({ title: 'Restore unsaved changes?', danger: false });
    confirmCancel.click();
    assert.strictEqual(await second, false);
    assert.strictEqual(discarded, true, 'witness: a click on Cancel reaches the Discard handler');
}

async function testAModalHoldsTheEditorShortcuts() {
    const confirm = new ConfirmationManager();
    editorKeys.length = 0;

    // Witness first: with no window open, Delete reaches the editor.
    press('Delete', body);
    assert.deepStrictEqual(editorKeys, ['Delete'], 'witness: the editor hears Delete when nothing is open');

    const answer = confirm.show({ title: 'Delete Lane' });
    editorKeys.length = 0;
    const fromOutside = press('Delete', body);
    assert.deepStrictEqual(editorKeys, [], 'Delete aimed behind the dialog does not reach the editor');
    assert.ok(fromOutside.defaultPrevented, 'and does nothing in the page either');
    press('Delete', confirmCancel);
    assert.deepStrictEqual(editorKeys, [], 'Delete from inside the dialog stops at the dialog');
    const save = press('s', body, { ctrlKey: true });
    assert.deepStrictEqual(editorKeys, [], 'Ctrl+S does not save behind the dialog');
    assert.ok(save.defaultPrevented, "and does not open the browser's Save page as");
    press('Control', body);
    assert.deepStrictEqual(editorKeys, ['Control'], 'a modifier alone goes on (the profile crosshair)');

    press('Escape');
    assert.strictEqual(await answer, false);
    editorKeys.length = 0;
    press('Delete', body);
    assert.deepStrictEqual(editorKeys, ['Delete'], 'once the dialog is closed the editor hears Delete again');
}

async function testTabStaysInsideAModal() {
    const confirm = new ConfirmationManager();
    const answer = confirm.show({ title: 'Delete Lane' });
    assert.strictEqual(document.activeElement, confirmCancel, 'setup: a destructive confirm opens on Cancel');

    confirmAction.focus();
    let tab = press('Tab', confirmAction);
    assert.strictEqual(document.activeElement, confirmCancel, 'Tab on the last control goes back to the first');
    assert.ok(tab.defaultPrevented, 'and the browser does not move the focus out of the dialog');

    tab = press('Tab', confirmCancel, { shiftKey: true });
    assert.strictEqual(document.activeElement, confirmAction, 'Shift+Tab on the first control goes to the last');
    assert.ok(tab.defaultPrevented);

    // Witness: between the ends Tab is the browser's (the trap does not swallow every Tab).
    confirmCancel.focus();
    tab = press('Tab', confirmCancel);
    assert.strictEqual(tab.defaultPrevented, false, 'a Tab that stays inside the dialog is left to the browser');

    // The focus left the dialog (a click on the page behind): Tab brings it back in, Shift+Tab at the end.
    body.focus();
    press('Tab', body);
    assert.strictEqual(document.activeElement, confirmCancel, 'Tab from outside the dialog goes to its first control');
    body.focus();
    press('Tab', body, { shiftKey: true });
    assert.strictEqual(document.activeElement, confirmAction, 'Shift+Tab from outside goes to its last control');

    press('Escape');
    assert.strictEqual(await answer, false);
}

(async () => {
    testEscClosesTheTopLayerOnly();
    await testEscAnswersCancelWithoutAClick();
    await testAModalHoldsTheEditorShortcuts();
    await testTabStaysInsideAModal();
})().then(
    () => console.log('layers esc: all assertions passed'),
    (err) => {
        console.error('layers esc: FAILED\n' + (err && err.stack ? err.stack : err));
        process.exitCode = 1;
    },
);
