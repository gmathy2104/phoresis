/**
 * Readout Panel — the western readout as a chart, one bar per lane
 *
 * The readout tab of the Graphical View (#graphical-view-toggle,
 * data-view="readout"): "Variants" on an anti-molecule western, "HCP vs
 * reference" on an anti-HCP one (an SDS-PAGE gel has the POI Purity tab
 * instead, drawn by densitometry.html). The tab and the container are
 * server-rendered only for an assay with a western readout (spec
 * 2026-10-12-gel-modern-ui-design.md §4).
 *
 * The values are the SERVER's: `state.readouts`, filled from
 * api_get_densitometry's `readouts` block, which
 * services/readout_publisher.py::lane_readouts computes through the very
 * function that publishes them to Process Development. The bars are drawn by
 * js/shared/readout-charts.js (the gel comparison draws the same); nothing here computes a readout.
 *
 *   - Host-cell proteins (anti-HCP): the lane's HCP signal in % of the
 *     reference lane's, on a log axis (0.1–1000 %) with a line at 100 %; the
 *     reference bar is amber and carries REF. Without a reference value, the
 *     raw signal (a.u.) on a linear axis, and the note says why.
 *   - Protein of interest variants (anti-molecule): one stacked bar per lane,
 *     HMWS | Main band | LMWS (high / low molecular weight species), in gel
 *     order (top to bottom).
 *   - A missing value shows its reason, muted ("no reference lane", "no POI
 *     band", "not analysed yet"...), never a zero.
 *
 * Redraws on READOUTS_UPDATED (initial fetch, reference-lane change, run
 * completed) and when the tab is opened (render()).
 */

(function (global) {
    'use strict';

    const Events = global.Densitometry.Events;

    const HCP = 'HOST_CELL_PROTEINS';
    const VARIANTS = 'MOLECULE_VARIANTS';

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    class ReadoutPanel {
        /**
         * @param {Object} options
         * @param {HTMLElement|null} options.container - #dm-readout-container (absent: no western assay)
         * @param {EventBus} options.eventBus
         * @param {State} options.state
         */
        constructor(options) {
            this.container = options.container || null;
            this.eventBus = options.eventBus;
            this.state = options.state;

            if (this.container) {
                this.eventBus.on(Events.READOUTS_UPDATED, () => this.render());
                this.render();
            }
        }

        /** Rebuild the chart from state (cheap: one row per lane). */
        render() {
            if (!this.container) return;
            this.container.innerHTML = this._html();
        }

        _html() {
            const assay = this.state.readoutAssay;
            if (!assay || (assay.readout !== HCP && assay.readout !== VARIANTS)) {
                return this._empty('The assay of this image has no western readout.');
            }

            const header = this._header(assay);
            if (!this.state.readoutsLoaded) {
                return header + this._empty('Loading the readout…');
            }
            const readouts = this.state.readouts;
            if (readouts === null) {
                return header + this._empty('The readout could not be computed. The error is in the server log.', true);
            }
            if (!readouts.length) {
                return header + this._empty('No sample lane on this gel yet.');
            }

            return header + (assay.readout === HCP ? this._hcpChart(readouts) : this._variantsChart(readouts));
        }

        _header(assay) {
            let note = '';
            // The lane number comes with the fetch: no note before it.
            if (assay.readout === HCP && this.state.readoutsLoaded) {
                const n = this.state.readoutReferenceLaneNumber;
                note = this.state.getHcpReferenceLaneId() !== null && n !== null && n !== undefined
                    ? `Reference: lane ${esc(n)}`
                    : 'No reference lane: pick one in the header, or in the annotation editor (the lane\'s HCP reference switch, or a right-click on the lane).';
                note = `<span class="dm-readout-ref-note">${note}</span>`;
            }
            const what = assay.readout === HCP ? 'HCP vs reference' : 'Variants';
            return `
                <div class="dm-readout-header">
                    <span class="dm-readout-title">${what} — ${esc(assay.name)}</span>
                    ${note}
                </div>`;
        }

        _empty(text, isError = false) {
            return `<div class="dm-readout-empty${isError ? ' is-error' : ''}">${esc(text)}</div>`;
        }

        _laneLabel(entry) {
            const sample = entry.sample_name ? `<span class="dm-readout-sample">${esc(entry.sample_name)}</span>` : '';
            const ref = entry.is_reference ? '<span class="ga-wb-ref">REF</span>' : '';
            return `<div class="dm-ro-label"><span class="dm-readout-lane-num">L${esc(entry.lane_number)}</span>${ref}${sample}</div>`;
        }

        /** Anti-HCP (js/shared/readout-charts.js, the comparison's chart too). */
        _hcpChart(readouts) {
            return global.GelAnalyzer.ReadoutCharts.hcp(readouts, { label: (entry) => this._laneLabel(entry) });
        }

        /** Anti-molecule: HMWS / main band / LMWS, stacked in the gel's order (D2). */
        _variantsChart(readouts) {
            return global.GelAnalyzer.ReadoutCharts.variants(readouts, { label: (entry) => this._laneLabel(entry) });
        }
    }

    global.Densitometry = global.Densitometry || {};
    global.Densitometry.ReadoutPanel = ReadoutPanel;
})(window);
