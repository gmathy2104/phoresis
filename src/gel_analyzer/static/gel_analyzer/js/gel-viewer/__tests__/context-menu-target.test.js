// Run: node gel_analyzer/static/gel_analyzer/js/gel-viewer/__tests__/context-menu-target.test.js
//
// The context menu opened only when something was already selected, and always for that selection: a right-click on
// lane 3 while lane 1 was selected opened lane 1's menu, and its items changed lane 1 (fixed 2026-10-13). It now opens
// on what is under the pointer, and Shift+F10 / the Menu key open the selection's. The real EventHandler, EventBus,
// StateManager, lane geometry and GelViewerApp selection run; only the outer edges are stubbed (the menu's DOM, the
// renderer's SVG).
const assert = require('assert');

globalThis.window = globalThis;
globalThis.document = { getElementById: () => null, querySelector: () => null, querySelectorAll: () => [] };
// The gel under the pointer: not a resize handle.
globalThis.Element = class { closest() { return null; } };
Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: { getItem: () => null, setItem() {}, removeItem() {} },
});
globalThis.innerWidth = 800;
globalThis.innerHeight = 600;

require('../../shared/lane-geometry.js');
require('../event-bus.js');
require('../state-manager.js');
require('../corner-handles.js');
require('../event-handler.js');
require('../gel-viewer.js');
const { EventBus, StateManager, EventHandler, App } = window.GelViewer;

function testTheMenuOpensOnWhatIsUnderThePointer() {
    const bus = new EventBus();
    const sm = new StateManager({ analysisId: 'a1', eventBus: bus });
    // Image = screen here (container at 0,0, scale 1). Lanes 1 and 3; one band in lane 3 at y 90-110.
    sm.setLane(1, { id: 1, lane_number: 1, lane_shape: 'RECTANGLE', x: 0, y: 0, width: 100, height: 400, bands: [] });
    sm.setLane(3, { id: 3, lane_number: 3, lane_shape: 'RECTANGLE', x: 200, y: 0, width: 100, height: 400, bands: [] });
    sm.setBand('b3', { id: 'b3', lane_id: 3, polygon: [[210, 90], [290, 90], [290, 110], [210, 110]] });

    const shown = [];
    const app = Object.create(App.prototype);
    Object.assign(app, {
        isEditable: true,
        eventBus: bus,
        stateManager: sm,
        selectedType: null,
        selectedId: null,
        contextMenu: {
            show: (x, y, type, options) => shown.push({ x, y, type, keyboard: !!options?.keyboard,
                selected: `${app.selectedType}:${app.selectedId}` }),
            hide() {},
            isVisible: () => false,
        },
        renderer: { selectAnnotation() {}, clearSelection() {} },
        cornerHandles: { show() {}, hide() {} },
        toolManager: { getActiveTool: () => null },
        drawingGroup: null,
        viewer: { getBoundingClientRect: () => ({ left: 0, top: 0, right: 800, bottom: 600, width: 800, height: 600 }) },
        // The selected shape on screen, for the keyboard's anchor: the band b3's box.
        svg: { findOne: () => ({ node: { getBoundingClientRect: () => ({ left: 210, top: 90, right: 290, bottom: 110 }) } }) },
        _showMessage() {},
    });
    app._wireEventBus();

    const handler = new EventHandler({
        viewer: null,
        canvasContainer: { getBoundingClientRect: () => ({ left: 0, top: 0 }) },
        eventBus: bus,
        toolManager: app.toolManager,
        viewport: {},
        stateManager: sm,
        getScale: () => 1,
        getSelectedAnnotation: () => (app.selectedType ? { type: app.selectedType, id: app.selectedId } : null),
        isContextMenuVisible: () => false,
    });
    const rightClick = (x, y) => handler._onContextMenu({ preventDefault() {}, clientX: x, clientY: y, target: new Element() });

    // The bug: lane 1 selected, a right-click on lane 3 (between its bands) opens lane 3's menu, lane 3 selected.
    app._selectAnnotation('lane', 1);
    rightClick(250, 300);
    assert.deepStrictEqual(shown.pop(), { x: 250, y: 300, type: 'lane', keyboard: false, selected: 'lane:3' },
        'the menu is the menu of the lane under the pointer, not of the selection');

    // A band under the pointer wins over its lane.
    rightClick(250, 100);
    assert.deepStrictEqual(shown.pop(), { x: 250, y: 100, type: 'band', keyboard: false, selected: 'band:b3' });

    // Bare gel: no menu, the selection stays.
    rightClick(500, 100);
    assert.strictEqual(shown.length, 0, 'nothing under the pointer: no menu');
    assert.strictEqual(`${app.selectedType}:${app.selectedId}`, 'band:b3');

    // The Menu key: the selection's menu over the middle of its shape, opened from the keyboard.
    const key = { key: 'ContextMenu', target: { tagName: 'BODY' }, repeat: false, preventDefault() {} };
    handler._onKeyDown(key);
    assert.deepStrictEqual(shown.pop(), { x: 250, y: 100, type: 'band', keyboard: true, selected: 'band:b3' });
}

try {
    testTheMenuOpensOnWhatIsUnderThePointer();
    console.log('context menu target: all assertions passed');
} catch (err) {
    console.error('context menu target: FAILED\n' + (err && err.stack ? err.stack : err));
    process.exitCode = 1;
}
