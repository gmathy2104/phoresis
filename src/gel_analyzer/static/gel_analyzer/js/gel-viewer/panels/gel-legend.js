/**
 * GelLegend - "Bands by Type | Readout" over the gel, and what each colour means (slice 3c).
 *
 * Type: the band types' colours, as the gel has always drawn them. Readout: the colour of each band's part in the
 * reading -- the server's roles (/data/ `role` per band, `renderer.setBandRole`) and the server's words (page_summary
 * `guide`); a band with no role keeps its type colour. The mode only adds `.gv-colour-readout` to `.gv-viewer`
 * (CSS does the rest): the gel image and the bands are untouched. Remembered per viewer.
 * Hidden while the lanes are reviewed and while the teacher panel (same corner) is open; on a phone the switch
 * stays and the swatches go.
 */

(function (global) {
    'use strict';

    const Events = global.GelViewer.Events;
    const MODE_KEY = 'gv-colour-by';

    // Readouts whose bands get a role or a reading of their own (a gel with no assay has neither).
    const READ_GELS = new Set(['PURITY', 'MOLECULE_VARIANTS', 'HOST_CELL_PROTEINS']);

    // The editor's own names (the band pills, the lane form); the colours are the gel's (ga-workbench tokens).
    const BAND_TYPES = [
        ['--ga-wb-b-poi', 'POI'],
        ['--ga-wb-b-other', 'Other'],
        ['--ga-wb-b-mw', 'MW Reference'],
        ['--ga-wb-lt-calibration', 'Calibration Point'],
    ];
    const LANE_TYPES = [
        ['--ga-wb-lt-sample', 'Sample', false],
        ['--ga-wb-lt-ladder', 'MW Ladder', false],
        ['--ga-wb-lt-control', 'Control', false],
        ['--ga-wb-lt-empty', 'Empty', true],
    ];
    // The guide's swatch names -> tokens (as reading-card.js).
    const SWATCH_TOKENS = {
        'b-poi': '--ga-wb-b-poi',
        'b-other': '--ga-wb-b-other',
        'b-mw': '--ga-wb-b-mw',
        'z-aggregate': '--ga-wb-z-aggregate',
        'z-main': '--ga-wb-z-main',
        'z-clipping': '--ga-wb-z-clipping',
    };

    function escapeHtml(value) {
        const d = document.createElement('div');
        d.textContent = value == null ? '' : String(value);
        return d.innerHTML.replace(/"/g, '&quot;');
    }

    function readMode() {
        try {
            return global.localStorage.getItem(MODE_KEY) === 'readout' ? 'readout' : 'type';
        } catch (e) {
            return 'type';
        }
    }

    function writeMode(mode) {
        try {
            global.localStorage.setItem(MODE_KEY, mode);
        } catch (e) {
            // A private window or blocked storage: Type again next time.
        }
    }

    function fill(token) {
        return `<i class="gv-legend-sw" aria-hidden="true" style="background: var(${token})"></i>`;
    }

    class GelLegend {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus
         * @param {HTMLElement} options.container - #gel-legend
         * @param {HTMLElement} options.viewer - .gv-viewer (gets .gv-colour-readout)
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.container = options.container;
            this.viewer = options.viewer;
            this.mode = readMode();
            this.reading = null;
            if (!this.container) return;

            this.eventBus.on(Events.READING_CHANGED, (reading) => {
                this.reading = reading;
                this.render();
            });
            this.eventBus.on(Events.TEACHER_PANEL_SHOWN, () => this.container.classList.add('is-covered'));
            this.eventBus.on(Events.TEACHER_PANEL_HIDDEN, () => this.container.classList.remove('is-covered'));
        }

        /** Readout mode only where the server reads the gel; otherwise (no assay, no reading) Type, no switch. */
        _readable() {
            return !!(this.reading && READ_GELS.has(this.reading.readout));
        }

        render() {
            if (!this.container) return;
            const readable = this._readable();
            const mode = readable ? this.mode : 'type';
            this.viewer?.classList.toggle('gv-colour-readout', mode === 'readout');

            const swatches = mode === 'readout'
                ? (this.reading.guide || []).filter((item) => item.swatch !== 'ref').map((item) => {
                    const sw = item.swatch === 'left-out'
                        ? '<i class="gv-legend-sw gv-legend-sw--hatch" aria-hidden="true"></i>'
                        : fill(SWATCH_TOKENS[item.swatch] || '--ga-wb-b-other');
                    return `<li title="${escapeHtml(item.text)}">${sw}${escapeHtml(item.label)}</li>`;
                })
                : BAND_TYPES.map(([token, label]) => `<li>${fill(token)}${label}</li>`);
            const lanes = LANE_TYPES.map(([token, label, dashed]) =>
                `<li><i class="gv-legend-sw gv-legend-sw--lane${dashed ? ' is-dashed' : ''}" aria-hidden="true" style="border-color: var(${token})"></i>${label}</li>`);
            if (this.reading && this.reading.readout === 'HOST_CELL_PROTEINS') {
                lanes.push('<li><span class="gv-legend-ref" aria-hidden="true">REF</span>HCP reference</li>');
            }

            const toggle = readable ? `
                <div class="gv-legend-mode" role="group" aria-label="Colour the bands by">
                    <span class="gv-legend-label">Bands by</span>
                    <span class="gv-legend-seg">
                        <button type="button" data-colour-by="type" aria-pressed="${mode === 'type'}">Type</button>
                        <button type="button" data-colour-by="readout" aria-pressed="${mode === 'readout'}">Readout</button>
                    </span>
                </div>` : '<div class="gv-legend-mode"><span class="gv-legend-label">Bands by type</span></div>';

            const focused = this.container.contains(document.activeElement) ? document.activeElement.dataset.colourBy : null;
            this.container.innerHTML = `${toggle}
                <ul class="gv-legend-list gv-legend-swatches">${swatches.join('')}</ul>
                <ul class="gv-legend-list gv-legend-lanes">${lanes.join('')}</ul>`;
            this.container.hidden = false;

            this.container.querySelectorAll('[data-colour-by]').forEach((button) => {
                button.addEventListener('click', () => {
                    if (this.mode === button.dataset.colourBy) return;
                    this.mode = button.dataset.colourBy;
                    writeMode(this.mode);
                    this.render();
                });
            });
            if (focused) this.container.querySelector(`[data-colour-by="${focused}"]`)?.focus({ preventScroll: true });
        }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.GelLegend = GelLegend;

})(window);
