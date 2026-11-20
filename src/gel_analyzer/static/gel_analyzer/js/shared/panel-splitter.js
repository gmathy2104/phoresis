/**
 * PanelSplitter — drag-resizable splitters between panels in .dm-app layouts.
 *
 * Wires the 3 splitters in the standard 4-panel layout used by the comparison
 * and densitometry views:
 *   - horizontal splitter between .dm-row-top and .dm-row-bottom
 *       → controls --dm-row-top-pct
 *   - vertical splitter inside .dm-row-top (gel ↔ chromatogram)
 *       → controls --dm-gel-overview-pct
 *   - vertical splitter inside .dm-row-bottom (band-detail ↔ results)
 *       → controls --dm-band-detail-pct
 *
 * Usage:
 *   const splitter = new GelAnalyzer.Shared.PanelSplitter({
 *       appEl: document.getElementById('sample-comparison-app'),
 *       storageKey: 'gelComparisonLayout',  // unique per view
 *   });
 *   splitter.init();
 *
 * Interactions:
 *   - Mouse drag to resize.
 *   - Double-click on a splitter to reset that axis to default.
 *   - Focused splitter + arrow keys (Shift = ×5) to nudge.
 *   - Layout persisted to localStorage; .resetAll() clears it.
 */
(function (global) {
    'use strict';

    const FALLBACK_DEFAULTS = {
        rowTopPct: 50,
        gelOverviewPct: 35,
        bandDetailPct: 35,
    };

    const MIN_PCT = 15;
    const MAX_PCT = 85;

    class PanelSplitter {
        constructor({ appEl, storageKey, defaults } = {}) {
            this.appEl = appEl;
            this.storageKey = storageKey || 'dmPanelLayout';
            this.defaults = Object.assign({}, FALLBACK_DEFAULTS, defaults || {});
            this.mainEl = null;
            this.splitters = [];
            this._dragState = null;
            this._onMove = this._onMove.bind(this);
            this._onUp = this._onUp.bind(this);
        }

        init() {
            if (!this.appEl) return;
            this.mainEl = this.appEl.querySelector('.dm-main');
            if (!this.mainEl) return;

            this._restoreLayout();

            this.splitters = Array.from(this.appEl.querySelectorAll('.dm-splitter'));
            this.splitters.forEach((el) => {
                el.addEventListener('mousedown', (e) => this._onDown(e, el));
                el.addEventListener('dblclick', () => this._reset(el));
                el.addEventListener('keydown', (e) => this._onKey(e, el));
            });
        }

        resetAll() {
            this._applyPct('main', this.defaults.rowTopPct);
            this._applyPct('top-row', this.defaults.gelOverviewPct);
            this._applyPct('bottom-row', this.defaults.bandDetailPct);
            try {
                localStorage.removeItem(this.storageKey);
            } catch (_) { /* ignore */ }
            window.dispatchEvent(new Event('resize'));
        }

        // ----- drag -----

        _onDown(e, el) {
            if (e.button !== 0) return;
            e.preventDefault();

            const orientation = el.classList.contains('dm-splitter-h') ? 'h' : 'v';
            const kind = el.dataset.splitter;
            const container = orientation === 'h' ? this.mainEl : el.parentElement;
            const rect = container.getBoundingClientRect();
            const cs = getComputedStyle(container);

            // Inner (content-box) dimensions, excluding container padding.
            const padTop = parseFloat(cs.paddingTop) || 0;
            const padBottom = parseFloat(cs.paddingBottom) || 0;
            const padLeft = parseFloat(cs.paddingLeft) || 0;
            const padRight = parseFloat(cs.paddingRight) || 0;
            const innerSize = orientation === 'h'
                ? rect.height - padTop - padBottom
                : rect.width - padLeft - padRight;
            const innerStart = orientation === 'h'
                ? rect.top + padTop
                : rect.left + padLeft;
            const splitterHalf = (orientation === 'h' ? el.offsetHeight : el.offsetWidth) / 2;

            this._dragState = {
                el, kind, orientation,
                innerStart, innerSize, splitterHalf,
                lastEvent: e,
                rafPending: false,
            };

            el.classList.add('is-dragging');
            document.body.classList.add(
                orientation === 'h' ? 'dm-splitter-dragging-h' : 'dm-splitter-dragging-v'
            );
            window.addEventListener('mousemove', this._onMove);
            window.addEventListener('mouseup', this._onUp);
        }

        _onMove(e) {
            if (!this._dragState) return;
            this._dragState.lastEvent = e;
            if (this._dragState.rafPending) return;
            this._dragState.rafPending = true;
            requestAnimationFrame(() => {
                if (!this._dragState) return;
                this._dragState.rafPending = false;
                this._processMove(this._dragState.lastEvent);
            });
        }

        _processMove(e) {
            const { kind, orientation, innerStart, innerSize, splitterHalf } = this._dragState;
            const pos = orientation === 'h' ? e.clientY : e.clientX;
            const offset = pos - innerStart - splitterHalf;
            const pct = (offset / innerSize) * 100;
            this._applyPct(kind, this._clamp(pct));
            // Let D3 charts and other resize-aware panels redraw during drag.
            window.dispatchEvent(new Event('resize'));
        }

        _onUp() {
            if (!this._dragState) return;
            const { el, orientation } = this._dragState;
            el.classList.remove('is-dragging');
            document.body.classList.remove(
                orientation === 'h' ? 'dm-splitter-dragging-h' : 'dm-splitter-dragging-v'
            );
            window.removeEventListener('mousemove', this._onMove);
            window.removeEventListener('mouseup', this._onUp);
            this._dragState = null;
            this._saveLayout();
            window.dispatchEvent(new Event('resize'));
        }

        // ----- keyboard -----

        _onKey(e, el) {
            const orientation = el.classList.contains('dm-splitter-h') ? 'h' : 'v';
            const step = e.shiftKey ? 5 : 1;
            let delta = 0;
            if (orientation === 'h') {
                if (e.key === 'ArrowUp') delta = -step;
                else if (e.key === 'ArrowDown') delta = step;
                else return;
            } else {
                if (e.key === 'ArrowLeft') delta = -step;
                else if (e.key === 'ArrowRight') delta = step;
                else return;
            }
            e.preventDefault();
            const kind = el.dataset.splitter;
            const next = this._clamp(this._readPct(kind) + delta);
            this._applyPct(kind, next);
            this._saveLayout();
            window.dispatchEvent(new Event('resize'));
        }

        // ----- reset -----

        _reset(el) {
            const kind = el.dataset.splitter;
            this._applyPct(kind, this._defaultPct(kind));
            this._saveLayout();
            window.dispatchEvent(new Event('resize'));
        }

        // ----- helpers -----

        _defaultPct(kind) {
            if (kind === 'main') return this.defaults.rowTopPct;
            if (kind === 'top-row') return this.defaults.gelOverviewPct;
            if (kind === 'bottom-row') return this.defaults.bandDetailPct;
            return 50;
        }

        _propName(kind) {
            if (kind === 'main') return '--dm-row-top-pct';
            if (kind === 'top-row') return '--dm-gel-overview-pct';
            if (kind === 'bottom-row') return '--dm-band-detail-pct';
            return null;
        }

        _readPct(kind) {
            const prop = this._propName(kind);
            if (!prop) return this._defaultPct(kind);
            const v = getComputedStyle(this.mainEl).getPropertyValue(prop).trim();
            if (v.endsWith('%')) return parseFloat(v);
            return this._defaultPct(kind);
        }

        _applyPct(kind, pct) {
            const prop = this._propName(kind);
            if (!prop) return;
            this.mainEl.style.setProperty(prop, pct.toFixed(2) + '%');
        }

        _clamp(v) {
            return Math.max(MIN_PCT, Math.min(MAX_PCT, v));
        }

        _saveLayout() {
            try {
                const layout = {
                    rowTopPct: this._readPct('main'),
                    gelOverviewPct: this._readPct('top-row'),
                    bandDetailPct: this._readPct('bottom-row'),
                };
                localStorage.setItem(this.storageKey, JSON.stringify(layout));
            } catch (_) { /* ignore */ }
        }

        _restoreLayout() {
            try {
                const raw = localStorage.getItem(this.storageKey);
                if (!raw) return;
                const layout = JSON.parse(raw);
                if (typeof layout.rowTopPct === 'number') {
                    this._applyPct('main', this._clamp(layout.rowTopPct));
                }
                if (typeof layout.gelOverviewPct === 'number') {
                    this._applyPct('top-row', this._clamp(layout.gelOverviewPct));
                }
                if (typeof layout.bandDetailPct === 'number') {
                    this._applyPct('bottom-row', this._clamp(layout.bandDetailPct));
                }
            } catch (_) { /* ignore */ }
        }
    }

    global.GelAnalyzer = global.GelAnalyzer || {};
    global.GelAnalyzer.Shared = global.GelAnalyzer.Shared || {};
    global.GelAnalyzer.Shared.PanelSplitter = PanelSplitter;

}(window));
