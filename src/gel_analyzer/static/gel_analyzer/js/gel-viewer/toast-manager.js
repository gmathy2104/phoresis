/**
 * ToastManager — top-left stack of state-aware notifications.
 *
 * Each toast is an instance returned from the manager so callers can morph
 * it as the underlying async work progresses:
 *
 *     const t = toasts.pending('Saving band...');
 *     try {
 *         const result = await apiClient.createBand(...);
 *         t.success(`Band saved (#${result.id})`);
 *     } catch (err) {
 *         t.error(`Save failed: ${err.message}`, { sticky: true });
 *     }
 *
 * The same DOM node is reused across pending → success/error, so the user
 * sees the spinner morph into a checkmark or warning — clearer than a
 * separate "saved" toast spawning next to the "saving" one.
 *
 * Auto-dismiss timings (overridable per call):
 *   - pending  : never (waits for resolution or explicit dismiss)
 *   - success  : 2500ms
 *   - info     : 3000ms
 *   - error    : sticky by default (manual close) — error toasts shouldn't
 *                vanish while the user is still reading why their save failed
 *
 * Stack ordering: newest at the bottom (visual order matches event order),
 * top-left anchored. The container is created lazily on first use so the
 * module is safe to load on pages that never need a toast.
 */
(function (global) {
    'use strict';

    const DEFAULT_DURATIONS = {
        success: 2500,
        info: 3000,
        warning: 4000,   // a refusal with its reason (gaToast's warning, routed here in the editor)
        error: 0,        // sticky
        pending: 0,      // never auto-dismiss while pending
    };

    const ICONS = {
        success: '<i class="bi bi-check-circle-fill"></i>',
        info:    '<i class="bi bi-info-circle-fill"></i>',
        warning: '<i class="bi bi-exclamation-circle-fill"></i>',
        error:   '<i class="bi bi-exclamation-triangle-fill"></i>',
        pending: '<span class="gv-toast-spinner" aria-hidden="true"></span>',
    };

    class Toast {
        constructor(manager, opts) {
            this.manager = manager;
            this.type = opts.type || 'info';
            this.message = opts.message || '';
            this.sticky = opts.sticky === true || (DEFAULT_DURATIONS[this.type] === 0);
            this._dismissTimer = null;
            this._dismissAt = 0;       // wall-clock when the timer was set to fire
            this._remainingMs = 0;     // remaining time when paused (hover)
            this._paused = false;
            this._dismissed = false;
            this._el = this._build();
        }

        _build() {
            const el = document.createElement('div');
            el.className = `gv-toast gv-toast--${this.type}`;
            el.setAttribute('role', this.type === 'error' ? 'alert' : 'status');
            el.innerHTML = `
                <span class="gv-toast-icon">${ICONS[this.type] || ICONS.info}</span>
                <span class="gv-toast-message"></span>
                <button class="gv-toast-close" aria-label="Dismiss">&times;</button>
            `;
            el.querySelector('.gv-toast-message').textContent = this.message;
            el.querySelector('.gv-toast-close').addEventListener('click', () => this.dismiss());
            // Pause auto-dismiss while the user is hovering the toast or has
            // tabbed into it — gives them time to read longer messages.
            el.addEventListener('mouseenter', () => this._pause());
            el.addEventListener('mouseleave', () => this._resume());
            el.addEventListener('focusin', () => this._pause());
            el.addEventListener('focusout', () => this._resume());
            return el;
        }

        _setupAutoDismiss(ms = null) {
            if (this.sticky) return;
            const dur = ms != null ? ms : DEFAULT_DURATIONS[this.type];
            if (!dur || dur <= 0) return;
            clearTimeout(this._dismissTimer);
            this._dismissAt = Date.now() + dur;
            this._remainingMs = dur;
            this._dismissTimer = setTimeout(() => this.dismiss(), dur);
        }

        _pause() {
            if (this.sticky || this._dismissed || this._paused) return;
            if (!this._dismissTimer) return;
            this._paused = true;
            clearTimeout(this._dismissTimer);
            this._dismissTimer = null;
            this._remainingMs = Math.max(0, this._dismissAt - Date.now());
        }

        _resume() {
            if (this.sticky || this._dismissed || !this._paused) return;
            this._paused = false;
            if (this._remainingMs > 0) {
                this._setupAutoDismiss(this._remainingMs);
            }
        }

        _morph(nextType, nextMessage, opts = {}) {
            if (this._dismissed) {
                // The user dismissed the toast manually before the async
                // work landed — don't resurrect it; surface the resolution
                // as a fresh toast instead so they still get the feedback.
                return this.manager.show({
                    type: nextType,
                    message: nextMessage,
                    sticky: opts.sticky,
                });
            }
            this.type = nextType;
            this.message = nextMessage;
            this.sticky = opts.sticky === true || (DEFAULT_DURATIONS[nextType] === 0);
            this._el.className = `gv-toast gv-toast--${nextType}`;
            this._el.setAttribute('role', nextType === 'error' ? 'alert' : 'status');
            this._el.querySelector('.gv-toast-icon').innerHTML = ICONS[nextType] || ICONS.info;
            this._el.querySelector('.gv-toast-message').textContent = nextMessage;
            clearTimeout(this._dismissTimer);
            this._setupAutoDismiss();
            return this;
        }

        success(message, opts) { return this._morph('success', message, opts); }
        error(message, opts)   { return this._morph('error', message, { sticky: true, ...(opts || {}) }); }
        info(message, opts)    { return this._morph('info', message, opts); }
        update(message)        { this._el.querySelector('.gv-toast-message').textContent = message; this.message = message; return this; }

        dismiss() {
            if (this._dismissed) return;
            this._dismissed = true;
            clearTimeout(this._dismissTimer);
            this._el.classList.add('gv-toast--leaving');
            // Match the CSS leave-animation duration; if styles never load
            // we still remove the node after the fallback delay.
            setTimeout(() => {
                if (this._el.parentNode) this._el.parentNode.removeChild(this._el);
                this.manager._unregister(this);
            }, 220);
        }
    }

    class ToastManager {
        constructor(opts = {}) {
            this.position = opts.position || 'top-left';
            this.container = null;
            this.toasts = new Set();
            // Insertion order — the most-recently-added toast is dismissed
            // on Escape (mirrors clicking its X). Set keeps insertion order
            // already but we keep a parallel array for stable last-of access.
            this._order = [];
            this._escHandler = (e) => this._handleEscape(e);
        }

        _ensureContainer() {
            if (this.container && document.body.contains(this.container)) return this.container;
            this.container = document.createElement('div');
            this.container.className = `gv-toast-container gv-toast-container--${this.position}`;
            // ARIA live region so screen readers announce toasts as they
            // arrive. `polite` defers to the user's current speech context;
            // individual error toasts override with role=alert (assertive).
            this.container.setAttribute('aria-live', 'polite');
            this.container.setAttribute('aria-atomic', 'false');
            this.container.setAttribute('aria-relevant', 'additions');
            document.body.appendChild(this.container);
            return this.container;
        }

        /**
         * True while a toast that Esc would dismiss is up (GelViewerApp.isIdle: Esc closes it, not the page).
         */
        hasOpen() {
            return this._order.some(t => !t._dismissed && t.type !== 'pending');
        }

        _handleEscape(e) {
            if (e.key !== 'Escape') return;
            // Pick the most-recently-added, non-pending toast — pending
            // toasts are tied to an in-flight op and shouldn't be silenced
            // by a stray keystroke.
            for (let i = this._order.length - 1; i >= 0; i--) {
                const t = this._order[i];
                if (!t._dismissed && t.type !== 'pending') {
                    e.stopPropagation();
                    t.dismiss();
                    return;
                }
            }
        }

        /**
         * Show a toast. Returns the Toast instance so the caller can
         * .success() / .error() / .dismiss() it later.
         */
        show({ type = 'info', message = '', sticky, duration } = {}) {
            const t = new Toast(this, { type, message, sticky });
            this._ensureContainer().appendChild(t._el);
            this.toasts.add(t);
            this._order.push(t);
            if (this.toasts.size === 1) {
                document.addEventListener('keydown', this._escHandler);
            }
            // Defer the enter-animation a tick so the browser registers the
            // initial transform state before the transition runs.
            requestAnimationFrame(() => t._el.classList.add('gv-toast--entered'));
            t._setupAutoDismiss(duration != null ? duration : null);
            return t;
        }

        /** Shorthand for `show({type: 'pending'})` — caller will resolve. */
        pending(message) { return this.show({ type: 'pending', message, sticky: true }); }
        success(message, opts) { return this.show({ type: 'success', message, ...(opts || {}) }); }
        info(message, opts)    { return this.show({ type: 'info', message, ...(opts || {}) }); }
        warning(message, opts) { return this.show({ type: 'warning', message, ...(opts || {}) }); }
        error(message, opts)   { return this.show({ type: 'error', message, sticky: true, ...(opts || {}) }); }

        _unregister(toast) {
            this.toasts.delete(toast);
            const idx = this._order.indexOf(toast);
            if (idx !== -1) this._order.splice(idx, 1);
            if (this.toasts.size === 0) {
                document.removeEventListener('keydown', this._escHandler);
            }
        }

        /** Dismiss every live toast — used on view teardown or batch resets. */
        clear() {
            for (const t of [...this.toasts]) t.dismiss();
        }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.ToastManager = ToastManager;
})(window);
