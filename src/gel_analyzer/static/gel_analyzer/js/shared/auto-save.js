/**
 * AutoSave — single entry-point for every auto-save in the app.
 *
 * Every fire-and-forget API call (band update, calibration save, polygon
 * refine, densitometry refresh, ...) used to grow its own ad-hoc
 * try/catch with a different error UX. Four divergent patterns in
 * gel-viewer.js alone, growing every time we add a feature. This helper
 * collapses them into one shape:
 *
 *     AutoSave.run({
 *         operation: 'Band update',
 *         promise: apiClient.updateBand(id, data),
 *         context: { kind: 'band', id },
 *         source: inputElement,           // optional
 *         onSuccess: (result) => {...},   // optional
 *         onError: (err) => {...},        // optional
 *     });
 *
 * On success: emits AUTOSAVE_OK, runs onSuccess, returns the result.
 * On failure: shows an error toast, emits AUTOSAVE_FAILED, runs
 * onError, re-throws so awaiting callers see the failure.
 *
 * No success toast — too noisy on rapid edits. Panels that want a
 * green flash listen to AUTOSAVE_OK and decide per-context whether
 * the source input belongs to them.
 */
(function (global) {
    'use strict';

    /**
     * Build an AutoSave instance bound to a specific eventBus + toast.
     *
     * @param {Object} deps
     * @param {Object} deps.eventBus - GelViewer EventBus instance
     * @param {Function} deps.showToast - (message: string, kind?: 'error') => void
     * @returns {{run: Function}}
     */
    function create({ eventBus, showToast }) {
        if (!eventBus) {
            throw new Error('AutoSave.create: eventBus is required');
        }

        const Events = (global.GelViewer && global.GelViewer.Events) || {};
        const OK = Events.AUTOSAVE_OK || 'autosave:ok';
        const FAILED = Events.AUTOSAVE_FAILED || 'autosave:failed';

        function run({
            operation,
            promise,
            context = {},
            source = null,
            onSuccess = null,
            onError = null,
        }) {
            if (!operation || typeof operation !== 'string') {
                throw new Error('AutoSave.run: operation (string) is required');
            }
            if (!promise || typeof promise.then !== 'function') {
                throw new Error('AutoSave.run: promise must be thenable');
            }

            return promise
                .then((result) => {
                    eventBus.emit(OK, { operation, context, source, result });
                    if (typeof onSuccess === 'function') {
                        try { onSuccess(result); } catch (cbErr) {
                            console.error(`AutoSave onSuccess handler failed for "${operation}":`, cbErr);
                        }
                    }
                    return result;
                })
                .catch((err) => {
                    const message = (err && err.message) ? err.message : String(err);
                    if (typeof showToast === 'function') {
                        try { showToast(`❌ ${operation} failed: ${message}`, 'error'); } catch (_) { /* toast itself failing shouldn't mask the original error */ }
                    }
                    eventBus.emit(FAILED, { operation, error: err, message, context, source });
                    if (typeof onError === 'function') {
                        try { onError(err); } catch (cbErr) {
                            console.error(`AutoSave onError handler failed for "${operation}":`, cbErr);
                        }
                    }
                    // Always re-throw — callers that await may want to abort
                    // their own follow-up work.
                    throw err;
                });
        }

        return { run };
    }

    global.PhoresisShared = global.PhoresisShared || {};
    global.PhoresisShared.AutoSave = { create };
})(window);
