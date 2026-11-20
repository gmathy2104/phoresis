/**
 * Layers - the annotation editor's open windows and menus, the last opened on top.
 *
 * One rule for every window (owner, 2026-10-12): Esc closes the top layer only and never decides - a confirm
 * answers "cancel", the backup restore keeps its backup, a form closes unsaved. A modal layer keeps the focus (it
 * moves in when it opens, Tab stays inside, it goes back where it came from) and keeps the editor's shortcuts
 * from acting behind it (Delete behind a confirm opened a second one).
 *
 * Each window registers from its own show / hide:
 *     GelViewer.Layers.open(el, {close, isOpen, modal, initialFocus, returnTo});
 *     GelViewer.Layers.close(el);
 *   close(reason)  what Esc does ('escape'); it may decline by returning false (a drawing to cancel first): the
 *                  layer stays. The window's own hide calls Layers.close(el) - the handler never pops first.
 *   isOpen()       optional: a window also closed by other paths (a menu, a reparented panel) is dropped as soon as
 *                  it says it is closed, so an Esc is never swallowed by a window that is gone.
 *   modal          traps Tab, holds the editor's keys, moves the focus in (initialFocus: an element or a function
 *                  returning one; else the layer itself, which needs tabindex="-1").
 *
 * The keydown listener is on document in the capture phase, added when this file loads: it runs before the page's
 * Esc-leave (annotate_standalone.html, also capture, added later) and before every bubble-phase handler (the
 * EventHandler, the panels). Only Escape and Tab are taken; Ctrl+S and the rest go on unless a modal holds them.
 * The lane review and the corner drag listen on window in the capture phase and run before this.
 */

(function (global) {
    'use strict';

    const FOCUSABLE = 'a[href], button, input, select, textarea, summary, [tabindex]:not([tabindex="-1"])';
    const FIELD = 'input, textarea, select, [contenteditable="true"]';

    /** @type {Array<{el: Element, close: Function|null, isOpen: Function|null, modal: boolean, returnTo: Element|null}>} */
    const stack = [];

    function shown(el) {
        return el.isConnected && el.getClientRects().length > 0;
    }

    function prune() {
        for (let i = stack.length - 1; i >= 0; i--) {
            const entry = stack[i];
            if (!entry.el.isConnected || (entry.isOpen && !entry.isOpen())) {
                release(entry);
                stack.splice(i, 1);
            }
        }
    }

    function topEntry() {
        prune();
        return stack.length ? stack[stack.length - 1] : null;
    }

    function focusables(root) {
        return Array.from(root.querySelectorAll(FOCUSABLE)).filter(
            (node) => !node.disabled && !node.closest('[hidden]') && shown(node)
        );
    }

    const MODIFIERS = new Set(['Control', 'Shift', 'Alt', 'Meta']);

    // Ctrl / Cmd+S held by a modal: no save behind it, and not the browser's "Save page as" either.
    function blockSaveChord(e) {
        if ((e.ctrlKey || e.metaKey) && e.key && e.key.toLowerCase() === 's') e.preventDefault();
    }

    // A modal's own controls get every key; nothing past its root reaches the editor (bubble phase). A modifier
    // pressed alone goes on: nothing in the editor acts on it, the profile shows its crosshair with it.
    function holdKeys(e) {
        if (MODIFIERS.has(e.key)) return;
        blockSaveChord(e);
        e.stopPropagation();
    }

    function release(entry) {
        if (entry.modal) entry.el.removeEventListener('keydown', holdKeys);
    }

    function focusIn(entry, initialFocus) {
        const target = typeof initialFocus === 'function' ? initialFocus() : initialFocus;
        const attempt = () => {
            if (!stack.includes(entry)) return true;
            const el = target && target.isConnected ? target : entry.el;
            if (el && typeof el.focus === 'function') el.focus({ preventScroll: true });
            return document.activeElement === el;
        };
        // After the window is painted (a display change in the same frame refuses the focus); once more after a
        // fade-in (a window still visibility: hidden refuses it too).
        requestAnimationFrame(() => {
            if (!attempt()) setTimeout(attempt, 200);
        });
    }

    function trapTab(e, root) {
        const items = focusables(root);
        if (!items.length) {
            e.preventDefault();
            root.focus({ preventScroll: true });
            return;
        }
        const first = items[0];
        const last = items[items.length - 1];
        const index = items.indexOf(document.activeElement);
        // Outside the dialog, or on the dialog box itself (focused, not a tab stop): the browser would leave it.
        if (index === -1) {
            e.preventDefault();
            (e.shiftKey ? last : first).focus();
        } else if (e.shiftKey && index === 0) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && index === items.length - 1) {
            e.preventDefault();
            first.focus();
        }
    }

    const Layers = {
        open(el, options = {}) {
            if (!el) return;
            const existing = stack.find((entry) => entry.el === el);
            if (existing) {
                // Shown again (the Band Editor follows the selected lane; a menu closed by a click and opened
                // again): back on top, fresh callbacks.
                existing.close = options.close || existing.close;
                existing.isOpen = options.isOpen || existing.isOpen;
                stack.splice(stack.indexOf(existing), 1);
                stack.push(existing);
                return;
            }
            const entry = {
                el,
                close: options.close || null,
                isOpen: options.isOpen || null,
                modal: Boolean(options.modal),
                returnTo: options.returnTo || document.activeElement,
            };
            stack.push(entry);
            if (entry.modal) {
                el.addEventListener('keydown', holdKeys);
                focusIn(entry, options.initialFocus);
            }
        },

        close(el) {
            const index = stack.findIndex((entry) => entry.el === el);
            if (index === -1) return;
            const wasTop = index === stack.length - 1;
            const [entry] = stack.splice(index, 1);
            release(entry);
            // The focus goes back from a modal on top only, and only if it was in the dialog (a click elsewhere
            // that closed it put the focus where the user wanted it). A panel or a menu gives nothing back.
            const focusInside = !document.activeElement || document.activeElement === document.body
                || el.contains(document.activeElement);
            if (entry.modal && wasTop && focusInside && entry.returnTo && entry.returnTo.isConnected) {
                entry.returnTo.focus({ preventScroll: true });
            }
        },

        top() {
            const entry = topEntry();
            return entry ? entry.el : null;
        },

        hasOpen() {
            return topEntry() !== null;
        },

        hasModal() {
            prune();
            return stack.some((entry) => entry.modal);
        },
    };

    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape' && e.key !== 'Tab') {
            // A key aimed at the page behind a modal (the focus left the dialog): held back, its typing too.
            const entry = topEntry();
            if (entry && entry.modal && !entry.el.contains(e.target) && !MODIFIERS.has(e.key)) {
                blockSaveChord(e);
                if (!e.ctrlKey && !e.metaKey && !e.altKey) e.preventDefault();
                e.stopImmediatePropagation();
            }
            return;
        }
        const entry = topEntry();
        if (!entry) return;

        if (e.key === 'Tab') {
            if (entry.modal) trapTab(e, entry.el);
            return;
        }

        e.preventDefault();
        e.stopImmediatePropagation();
        if (e.repeat) return;  // a held Esc closes one layer

        // Under a panel or a menu, the first Esc leaves the field being typed in (wherever it is); the next one
        // closes the panel. In a modal it closes the dialog, its fields included (cancel, nothing decided).
        const target = e.target;
        if (!entry.modal && target instanceof Element && target.matches(FIELD)) {
            target.blur();
            return;
        }
        if (entry.close) entry.close('escape');
    }, true);

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.Layers = Layers;

})(window);
