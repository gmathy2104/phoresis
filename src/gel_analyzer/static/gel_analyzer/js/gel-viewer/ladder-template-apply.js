/**
 * LadderTemplateApply - Fill an MW Ladder lane's band MW values from a ladder template
 *
 * The one path for both buttons that do it: the lane form's Apply beside MW Template (properties-panel.js) and the
 * Band editor's (band-table-panel.js). Same request, same refusals, same warnings, same events: they cannot drift.
 *
 * The server (POST /api/lanes/<id>/apply-ladder-template/) gives the template's values to the lane's bands as IT
 * holds them -- the saved bands, top to bottom by their saved position -- and refuses a lane it does not hold as a
 * LADDER. So nothing is sent while the lane or one of its bands waits for Save (StateManager.laneWaitsForSave): a lane
 * never saved has no id the URL takes, a lane typed MW Ladder here is still another type there, and a band drawn,
 * moved or deleted here and not saved shifts every value below it onto the wrong band, with no error. Nor while one
 * of its bands is typed POI or Calibration (_foreignBands).
 *
 * Once applied, each band whose value changed takes it through onSyncBandLocal (GelViewerApp._syncBandLocally), the
 * path a hand edit of one MW takes once saved: the band object keeps all the editor holds on it (role, lane link,
 * calibration point), and its BAND_UPDATED marks the MW calibration stale (CalibrationPanel._onBandChanged) as an edit
 * of one ladder MW does (owner, 2026-10-13). Then MW_BANDS_UPDATED, once: the Band editor's table, the lane form's
 * band list and the MW calibration panel's ladder list read the new values.
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    const SAVE_FIRST = 'Save first (Ctrl+S): this lane has changes not saved yet, and the template goes to the bands '
        + 'as they are saved.';
    const NOT_A_LADDER = 'Only an MW Ladder lane takes a ladder template.';
    const RUNNING = 'The template is being applied to this lane.';

    function escapeHtml(s) {
        return String(s ?? '').replace(/[&<>"']/g, (c) => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    class LadderTemplateApply {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus
         * @param {StateManager} options.stateManager
         * @param {APIClient} options.apiClient
         * @param {Function} options.onSyncBandLocal - GelViewerApp._syncBandLocally: a value the server already saved
         * @param {Function} [options.getConfirmationManager] - The editor's dialog (created after the panels)
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.stateManager = options.stateManager;
            this.apiClient = options.apiClient;
            this.onSyncBandLocal = options.onSyncBandLocal;
            this.getConfirmationManager = options.getConfirmationManager || (() => null);
            this._running = new Set();  // String(lane id) with a request on its way
        }

        /**
         * @param {string|number} laneId
         * @returns {boolean} A request for this lane is on its way
         */
        isRunning(laneId) {
            return this._running.has(String(laneId));
        }

        /**
         * Why this lane cannot take a template now, or null.
         * @param {string|number} laneId
         * @returns {string|null}
         */
        refusal(laneId) {
            if (this.isRunning(laneId)) return RUNNING;
            return this._whyNot(this.stateManager.getLane(laneId));
        }

        _whyNot(lane) {
            if (!lane || lane.lane_type !== 'LADDER') return NOT_A_LADDER;
            if (this.stateManager.laneWaitsForSave(lane.id)) return SAVE_FIRST;
            return this._foreignBands(lane);
        }

        /**
         * A ladder's bands are MW Reference or Other. A band typed POI or Calibration there (a lane retyped MW Ladder
         * after its bands were typed) is data that contradicts itself: refused, naming the bands, never worked around.
         * Until 2026-10-13 its value also turned the lane back into a Sample lane (the auto-promote ran on any band
         * update, not only a type change), and the server then dropped its template (with_ladder_template).
         * @returns {string|null}
         */
        _foreignBands(lane) {
            const names = { POI: 'POI', CALIBRATION: 'Calibration' };
            const foreign = this.stateManager.getBandsForLane(lane.id)
                .map((band, index) => ({ n: index + 1, type: band.band_type }))
                .filter(b => b.type in names);
            if (foreign.length === 0) return null;
            const one = foreign.length === 1;
            const list = foreign.map(b => `Band ${b.n} (${names[b.type]})`).join(', ');
            return `${list} ${one ? 'is' : 'are'} not MW Reference or Other, as a ladder's bands are. `
                + `Retype ${one ? 'it' : 'them'}, then apply.`;
        }

        /**
         * Apply a template to a lane. Never throws: the outcome says what happened, noticeHtml() puts it in words.
         * @param {string|number} laneId
         * @param {string} templateId
         * @param {Object} [opts]
         * @param {boolean} [opts.confirmOverwrite=false] - Ask before replacing MW values the lane's bands hold (the
         *   lane form's shortcut; the Band editor's table shows the values it replaces)
         * @param {string} [opts.templateName] - For the question
         * @returns {Promise<Object>} {status: 'applied'|'refused'|'cancelled'|'failed', message, warnings,
         *   templateName, bandsUpdated}
         */
        async apply(laneId, templateId, { confirmOverwrite = false, templateName = '' } = {}) {
            if (!templateId) return { status: 'refused', message: 'Choose a template first.' };
            const refused = this.refusal(laneId);
            if (refused) return { status: 'refused', message: refused };

            const lane = this.stateManager.getLane(laneId);
            const key = String(lane.id);
            this._running.add(key);
            try {
                if (confirmOverwrite && !(await this._confirmOverwrite(lane, templateName))) {
                    return { status: 'cancelled' };
                }
                // The dialog may have stayed open: an edit made meanwhile is still unsaved.
                const late = this._whyNot(this.stateManager.getLane(lane.id));
                if (late) return { status: 'refused', message: late };

                let data;
                try {
                    data = await this.apiClient.applyLadderTemplate(lane.id, templateId);
                } catch (error) {
                    return { status: 'failed', message: (error && error.message) || String(error) };
                }
                this._takeResult(lane, templateId, data);
                return {
                    status: 'applied',
                    warnings: data.warnings || [],
                    templateName: data.template_name,
                    bandsUpdated: data.bands_updated,
                };
            } finally {
                this._running.delete(key);
            }
        }

        /**
         * The editor's own dialog when a band of the lane already holds an MW value; no dialog to ask with, nothing
         * is replaced (ConfirmationManager.show answers yes without its modal).
         * @returns {Promise<boolean>} true to go on
         */
        async _confirmOverwrite(lane, templateName) {
            const bands = this.stateManager.getBandsForLane(lane.id);
            const valued = bands.filter(b => b.estimated_mw_kda != null).length;
            if (valued === 0) return true;
            const cm = this.getConfirmationManager();
            if (!cm || !cm.modal) return false;
            return cm.show({
                title: 'Replace MW values?',
                body:
                    `<p><strong>${valued}</strong> of the ${bands.length} bands of lane ${escapeHtml(lane.lane_number)} `
                    + 'already have an MW value.</p>'
                    + `<p class="mb-0">Applying <strong>${escapeHtml(templateName || 'this template')}</strong> `
                    + 'replaces them, top to bottom.</p>',
                confirmText: 'Replace MW values',
                cancelText: 'Keep values',
                danger: true,
                icon: 'exclamation-triangle-fill',
            });
        }

        /**
         * The server's answer into the editor: the bands' values, the lane's template, then MW_BANDS_UPDATED.
         */
        _takeResult(lane, templateId, data) {
            const sm = this.stateManager;
            const here = new Map(sm.getBandsForLane(lane.id).map(b => [String(b.id), b]));
            for (const served of data.bands || []) {
                const band = here.get(String(served.id));
                if (!band) continue;
                const mw = served.estimated_mw_kda ?? null;
                if ((band.estimated_mw_kda ?? null) === mw) continue;
                this.onSyncBandLocal(band.id, { estimated_mw_kda: mw });
            }

            // The server now holds this template on the lane: a choice of template still waiting for Save is
            // superseded (sent later, it would put back a template the values no longer come from).
            const edit = sm.getPendingChanges().lanes.updated.get(lane.id);
            if (edit && 'ladder_template_id' in edit) {
                edit.ladder_template_id = templateId;
                sm.confirmUpdateSaved('lanes', lane.id, { ladder_template_id: templateId });
            }
            if (lane.ladder_template_id !== templateId) {
                lane.ladder_template_id = templateId;
                this.eventBus.emit(Events.LANE_UPDATED, lane);
            }

            this.eventBus.emit(Events.MW_BANDS_UPDATED, {
                laneId: lane.id,
                templateName: data.template_name,
                bandsUpdated: data.bands_updated,
            });
        }

        /**
         * An outcome in the words both panels show: the server's warnings (band-count mismatch...), a refusal or the
         * error; '' when there is nothing to say.
         * @param {Object} outcome - from apply()
         * @returns {string} HTML
         */
        static noticeHtml(outcome) {
            if (!outcome) return '';
            if (outcome.status === 'applied') {
                return (outcome.warnings || [])
                    .map(w => `<span class="warning-icon">⚠</span> ${escapeHtml(w)}`).join('<br>');
            }
            if (outcome.status === 'refused') return `<span class="warning-icon">⚠</span> ${escapeHtml(outcome.message)}`;
            if (outcome.status === 'failed') return `<span class="warning-icon">❌</span> ${escapeHtml(outcome.message)}`;
            return '';
        }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.LadderTemplateApply = LadderTemplateApply;

})(window);
