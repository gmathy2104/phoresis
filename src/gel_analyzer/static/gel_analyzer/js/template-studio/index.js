/**
 * Ladder Template Studio — entry point.
 *
 * Wires the 3 panels (lane-picker, parallel-strips, validation-grid) to a
 * shared state + event bus, consumes window.LTS_CONTEXT for template id +
 * API URLs, and owns the bottom action bar.
 *
 * Panels are added in Phases 3 (lane picker), 4 (strips), 5 (grid).
 */
(function () {
    'use strict';

    const ctx = window.LTS_CONTEXT;
    if (!ctx) {
        console.error('[LTS] window.LTS_CONTEXT missing — studio cannot boot.');
        return;
    }

    const MIN_LANES = 3;
    const MAX_LANES = 10;

    // ─── Shared state ─────────────────────────────────────────────────
    const state = {
        availableLanes: [],        // rows returned by /studio/lanes/
        selectedLaneIds: new Set(),  // user-picked lane uuids
        autoAssignResult: null,    // payload returned by /auto-assign/
    };

    // ─── Event bus (tiny) ─────────────────────────────────────────────
    const listeners = {};
    const bus = {
        on(event, fn) {
            (listeners[event] = listeners[event] || []).push(fn);
        },
        emit(event, payload) {
            (listeners[event] || []).forEach(fn => {
                try {
                    fn(payload);
                } catch (err) {
                    console.error(`[LTS] listener for "${event}" threw:`, err);
                }
            });
        },
    };

    // ─── CSRF helper ──────────────────────────────────────────────────
    function getCsrf() {
        const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    // ─── API ──────────────────────────────────────────────────────────
    const api = {
        async lanesAvailable(params = {}) {
            const qs = new URLSearchParams(params).toString();
            const url = ctx.apiUrls.lanesAvailable + (qs ? '?' + qs : '');
            const resp = await fetch(url);
            if (!resp.ok) throw new Error(`lanes-available HTTP ${resp.status}`);
            return resp.json();
        },
        async autoAssign(laneIds, overrideBands) {
            const body = { lane_ids: laneIds };
            if (overrideBands && Object.keys(overrideBands).length) {
                body.override_bands = overrideBands;
            }
            const resp = await fetch(ctx.apiUrls.autoAssign, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrf(),
                },
                body: JSON.stringify(body),
            });
            if (!resp.ok) {
                const text = await resp.text();
                throw new Error(`auto-assign HTTP ${resp.status}: ${text}`);
            }
            return resp.json();
        },
        async save(lanesPayload) {
            const resp = await fetch(ctx.apiUrls.save, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrf(),
                },
                body: JSON.stringify({ lanes: lanesPayload }),
            });
            if (!resp.ok) {
                const text = await resp.text();
                throw new Error(`save HTTP ${resp.status}: ${text}`);
            }
            return resp.json();
        },
        async redetect(laneIds) {
            const resp = await fetch(ctx.apiUrls.redetect, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrf(),
                },
                body: JSON.stringify({ lane_ids: laneIds }),
            });
            if (!resp.ok) {
                const text = await resp.text();
                throw new Error(`redetect HTTP ${resp.status}: ${text}`);
            }
            return resp.json();
        },
    };

    // State for re-detection overrides: { lane_id: [candidate, ...] }.
    state.overrideBands = {};

    // ─── Action bar wiring ────────────────────────────────────────────
    const els = {
        autoAssignBtn: document.getElementById('lts-auto-assign'),
        redetectBtn: document.getElementById('lts-redetect'),
        saveBtn: document.getElementById('lts-save'),
        status: document.getElementById('lts-status'),
    };

    function updateActionBar() {
        const n = state.selectedLaneIds.size;
        const canAssign = n >= MIN_LANES;
        const overrideN = Object.keys(state.overrideBands || {}).length;
        els.autoAssignBtn.disabled = !canAssign;
        els.redetectBtn.disabled = n === 0;
        // Re-detected bands are ephemeral — cannot save until they're
        // persisted through the annotation view. Block Save in that case.
        els.saveBtn.disabled = !state.autoAssignResult || overrideN > 0;
        els.saveBtn.title = overrideN > 0
            ? 'Save is disabled while re-detected candidates are in use — persist them via the Annotation view first.'
            : '';

        if (n === 0) {
            els.status.textContent = `Pick ${MIN_LANES}–${MAX_LANES} lanes to begin.`;
        } else if (n < MIN_LANES) {
            els.status.textContent = `${n} lane${n === 1 ? '' : 's'} selected — pick at least ${MIN_LANES}.`;
        } else {
            const overrideNote = overrideN > 0 ? ` · ${overrideN} re-detected (preview only)` : '';
            els.status.textContent = `${n} lane${n === 1 ? '' : 's'} selected${overrideNote}. Ready for auto-assign.`;
        }
    }

    bus.on('selection:changed', updateActionBar);

    // Auto-assign handler.
    els.autoAssignBtn.addEventListener('click', async () => {
        const laneIds = Array.from(state.selectedLaneIds);
        if (laneIds.length < MIN_LANES) return;
        els.autoAssignBtn.disabled = true;
        els.autoAssignBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> Assigning…';
        try {
            // Only pass override bands for lanes currently selected.
            const overrides = {};
            for (const lid of laneIds) {
                if (state.overrideBands && state.overrideBands[lid]) {
                    overrides[lid] = state.overrideBands[lid];
                }
            }
            const result = await api.autoAssign(laneIds, overrides);
            state.autoAssignResult = result;
            bus.emit('autoAssign:result', result);
            updateActionBar();
            const totalFlagged = (result.lanes || []).reduce((s, l) => s + (l.flagged_count || 0), 0);
            els.status.textContent = `Auto-assigned ${result.lanes.length} lane${result.lanes.length === 1 ? '' : 's'}.`
                + (totalFlagged > 0 ? ` ${totalFlagged} match${totalFlagged === 1 ? '' : 'es'} flagged — review before saving.` : '');
        } catch (err) {
            console.error('[LTS] auto-assign failed:', err);
            els.status.textContent = 'Auto-assign failed: ' + err.message;
        } finally {
            els.autoAssignBtn.disabled = false;
            els.autoAssignBtn.innerHTML = '<i class="bi bi-lightning-charge"></i> Auto-assign top-N';
        }
    });

    // Re-detect (profile + noise subtraction) handler.
    els.redetectBtn.addEventListener('click', async () => {
        const laneIds = Array.from(state.selectedLaneIds);
        if (!laneIds.length) return;
        els.redetectBtn.disabled = true;
        els.redetectBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> Re-detecting…';
        try {
            const data = await api.redetect(laneIds);
            const lanes = data.lanes || {};
            let totalCandidates = 0;
            for (const lid of laneIds) {
                const entry = lanes[lid];
                if (entry && entry.candidates && entry.candidates.length) {
                    state.overrideBands[lid] = entry.candidates;
                    totalCandidates += entry.candidates.length;
                }
            }
            // Invalidate any stale auto-assign result.
            state.autoAssignResult = null;
            bus.emit('autoAssign:result', null);
            els.status.textContent = `Re-detected ${laneIds.length} lane${laneIds.length === 1 ? '' : 's'} — ${totalCandidates} candidate peaks. Run auto-assign to see matches.`;
            updateActionBar();
        } catch (err) {
            console.error('[LTS] redetect failed:', err);
            els.status.textContent = 'Re-detect failed: ' + err.message;
        } finally {
            els.redetectBtn.disabled = false;
            els.redetectBtn.innerHTML = '<i class="bi bi-activity"></i> Re-detect (profile)';
        }
    });

    // Save & Train handler.
    els.saveBtn.addEventListener('click', async () => {
        if (!state.autoAssignResult) return;
        const lanesPayload = (state.autoAssignResult.lanes || [])
            .filter(l => l.matches && l.matches.length > 0)
            .map(l => ({
                lane_id: l.lane_id,
                matches: l.matches.map(m => ({
                    template_band_order: m.template_band_order,
                    band_id: m.band_id,
                    mw_kda: m.mw_kda,
                    position_y: m.position_y,
                    rf: m.rf,
                    peak_intensity: m.peak_intensity,
                })),
            }));
        if (!lanesPayload.length) {
            els.status.textContent = 'Nothing to save — no lanes have matches.';
            return;
        }
        if (!confirm(`Save ${lanesPayload.length} calibration${lanesPayload.length === 1 ? '' : 's'} and train the template?`)) {
            return;
        }
        els.saveBtn.disabled = true;
        els.saveBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> Saving…';
        try {
            const result = await api.save(lanesPayload);
            const learn = result.learning || {};
            const summary = result.summary || {};
            els.status.textContent = `Saved ${result.calibration_ids.length} calibrations · trained ${learn.updated_bands}/${summary.bands_with_rf + summary.bands_without_rf || '?'} bands.`;
            bus.emit('save:complete', result);
            // Optional: redirect back to the detail page so the user sees new Rf stats.
            setTimeout(() => {
                window.location.href = `/admin/templates/${ctx.templateId}/calibrate/`;
            }, 1500);
        } catch (err) {
            console.error('[LTS] save failed:', err);
            els.status.textContent = 'Save failed: ' + err.message;
            els.saveBtn.disabled = false;
            els.saveBtn.innerHTML = '<i class="bi bi-save"></i> Save &amp; Train';
        }
    });

    // ─── Boot ─────────────────────────────────────────────────────────
    window.LTS = {
        ctx,
        state,
        bus,
        api,
        constants: { MIN_LANES, MAX_LANES },
    };

    // Panels register themselves by listening for 'studio:ready'.
    document.addEventListener('DOMContentLoaded', () => {
        bus.emit('studio:ready');
        updateActionBar();
    });
})();
