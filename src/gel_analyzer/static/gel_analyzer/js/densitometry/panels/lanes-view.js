/**
 * Lanes View — Measurements › Lanes: one row per lane, the gel's readout columns
 *
 * The Measurements panel shows either this view or today's band table (ResultsTablePanel, untouched), switched by a
 * "Lanes | Bands" control in the panel header (spec docs/superpowers/specs/2026-10-12-gel-modern-ui-design.md §4).
 * The columns, their labels and help titles, and every cell come from the server's page summary
 * (services/analysis_detail.py::summary_payload -> readout_columns / lane_rows): the analysis page prints the same
 * cells. This file formats; it never computes a value. A missing value shows its reason, grey, never a zero.
 *
 * Redraws on PAGE_SUMMARY_UPDATED (a run, a reference change, a quantification save) and marks the selected lane
 * on LANE_SELECTED. A row click selects its lane, as a click on the gel does.
 */

(function (global) {
    'use strict';

    const Events = global.Densitometry.Events;
    const VIEW_KEY = 'gelDensitometryMeasurementsView';

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // Units keep their case under the uppercased headers (docs/handover/known-traps.md): µg/mL, kDa.
    function unitText(value) {
        return esc(value).replace(
            /([µμ][A-Za-z]*(?:\/[A-Za-z]+)?|\bkDa\b)/g,
            '<span class="ga-wb-unit-text">$1</span>'
        );
    }

    function readView() {
        try {
            const saved = global.localStorage.getItem(VIEW_KEY);
            return saved === 'bands' ? 'bands' : 'lanes';
        } catch (_) {
            return 'lanes';
        }
    }

    function saveView(view) {
        try {
            global.localStorage.setItem(VIEW_KEY, view);
        } catch (_) {
            /* private window: the choice simply does not persist */
        }
    }

    // The note under the table, per readout: the texts of the readout panel and of analysis_detail's titles.
    const NOTES = {
        PURITY: 'Purity = POI share of the lane. A lane without a POI band has none.',
        MOLECULE_VARIANTS: "In % of the lane's counted signal (POI and other bands): above the POI band = HMWS (high molecular weight species), on it = main band, below it = LMWS (low molecular weight species).",
        HOST_CELL_PROTEINS: "% of ref. = the lane's HCP signal ÷ the reference lane's, on the same membrane. The signal in a.u. depends on the exposure: compare it within this blot only. POI bands (cross-reacting molecule) are left out of the HCP signal.",
    };

    class LanesView {
        /**
         * @param {Object} options
         * @param {HTMLElement} options.container - #results-table-panel
         * @param {EventBus} options.eventBus
         * @param {State} options.state
         */
        constructor(options) {
            this.container = options.container || null;
            this.eventBus = options.eventBus;
            this.state = options.state;
            if (!this.container) return;
            this.content = this.container.querySelector('.dm-panel-content');
            this.bandsView = this.content && this.content.querySelector('.dm-results-container');
            if (!this.content || !this.bandsView) return;

            this.view = readView();
            this._build();
            // The phone's lane picker (#dm-lane-picker, shown under 700 px): the lanes with bands as chips.
            this.picker = document.getElementById('dm-lane-picker');
            if (this.picker) {
                this.picker.addEventListener('click', (event) => {
                    const chip = event.target.closest('[data-lane-id]');
                    if (chip && typeof this.state.selectLane === 'function') {
                        this.state.selectLane(Number(chip.dataset.laneId));
                    }
                });
            }
            this.eventBus.on(Events.PAGE_SUMMARY_UPDATED, () => this.render());
            this.eventBus.on(Events.LANE_SELECTED, () => this._markSelected());
            this.render();
            this._apply();
        }

        _build() {
            const actions = this.container.querySelector('.dm-panel-header .dm-panel-actions');
            this.toggle = document.createElement('div');
            this.toggle.className = 'dm-lanes-toggle';
            this.toggle.setAttribute('role', 'group');
            this.toggle.setAttribute('aria-label', 'Rows');
            this.toggle.innerHTML = `
                <button type="button" data-rows="lanes" title="One row per lane: the gel's readout">Lanes</button>
                <button type="button" data-rows="bands" title="One row per band: areas, amounts, fit">Bands</button>`;
            if (actions) actions.insertBefore(this.toggle, actions.firstChild);
            this.toggle.querySelectorAll('[data-rows]').forEach((button) => {
                button.addEventListener('click', () => {
                    this.view = button.dataset.rows;
                    saveView(this.view);
                    this._apply();
                });
            });

            this.root = document.createElement('div');
            this.root.className = 'dm-lanes-view';
            this.content.appendChild(this.root);
            this.root.addEventListener('click', (event) => {
                // The sample's link opens its card; it does not select the lane on its way out.
                if (event.target.closest('a[href]')) return;
                const row = event.target.closest('[data-lane-id]');
                if (row && typeof this.state.selectLane === 'function') {
                    this.state.selectLane(Number(row.dataset.laneId));
                }
            });
        }

        _apply() {
            const lanes = this.view === 'lanes';
            this.root.hidden = !lanes;
            this.bandsView.style.display = lanes ? 'none' : '';
            this.toggle.querySelectorAll('[data-rows]').forEach((button) => {
                button.setAttribute('aria-pressed', String(button.dataset.rows === this.view));
            });
        }

        render() {
            if (!this.root) return;
            const summary = this.state.pageSummary;
            if (!summary || !summary.rows) {
                this.root.innerHTML = '<div class="dm-lanes-empty">The lane values could not be loaded.</div>';
                return;
            }
            const columns = summary.columns || [];
            const head = `<tr><th>Lane</th><th>Sample</th>${columns
                .map((column) => `<th class="r" title="${esc(column.title)}">${unitText(column.label)}</th>`)
                .join('')}</tr>`;
            const rows = summary.rows
                .map((row) => {
                    const cells = columns
                        .map((column) => {
                            const cell = (row.cells || {})[column.key];
                            if (!cell) return '<td class="r dm-lanes-off">—</td>';
                            if (!cell.text) {
                                return `<td class="r"><span class="dm-lanes-why">${esc(cell.reason || '—')}</span></td>`;
                            }
                            const tone = cell.tone ? ` dm-lanes-tone--${esc(cell.tone)}` : '';
                            return `<td class="r${tone}" data-label="${esc(column.label)}">${unitText(cell.text)}</td>`;
                        })
                        .join('');
                    const ref = row.is_reference ? ' <span class="ga-wb-ref">REF</span>' : '';
                    // A Process Development sample links to its identity card (row.sample_url, the server's
                    // reverse()), in this tab as the analysis page's links do; a free-text name stays text.
                    const sample = row.sample && row.sample_url
                        ? `<a class="dm-lanes-sample-link" href="${esc(row.sample_url)}" title="Open the sample">${esc(row.sample)}</a>`
                        : row.sample
                          ? esc(row.sample)
                          : row.lane_type === 'SAMPLE'
                            ? '<span class="dm-lanes-why">no sample</span>'
                            : `<span class="dm-lanes-off">${esc(String(row.lane_type || '').toLowerCase())}</span>`;
                    const classes = ['dm-lanes-row'];
                    if (row.is_reference) classes.push('is-reference');
                    if (!row.is_read) classes.push('is-unread');
                    return `<tr class="${classes.join(' ')}" data-lane-id="${esc(row.id)}">
                        <td><span class="ga-wb-lnum" data-lt="${esc(row.lane_type)}">${esc(row.lane_number)}</span>${ref}</td>
                        <td class="dm-lanes-sample">${sample}</td>${cells}</tr>`;
                })
                .join('');
            const note = NOTES[summary.readout] ? `<p class="dm-lanes-note">${esc(NOTES[summary.readout])}</p>` : '';
            this.root.innerHTML = `<div class="dm-lanes-scroll"><table class="dm-lanes-table">
                <thead>${head}</thead><tbody>${rows}</tbody></table></div>${note}`;
            if (this.picker) {
                this.picker.innerHTML = summary.rows
                    .filter((row) => row.lane_type !== 'EMPTY')
                    .map(
                        (row) => `<button type="button" data-lane-id="${esc(row.id)}" aria-pressed="false">
                            <span class="ga-wb-lnum" data-lt="${esc(row.lane_type)}">${esc(row.lane_number)}</span>
                            ${esc(row.sample || String(row.lane_type || '').toLowerCase())}${row.is_reference ? ' <span class="ga-wb-ref">REF</span>' : ''}</button>`
                    )
                    .join('');
            }
            this._markSelected();
        }

        _markSelected() {
            if (!this.root) return;
            const selected = this.state.selectedLaneId;
            const isSelected = (el) => selected != null && Number(el.dataset.laneId) === Number(selected);
            this.root.querySelectorAll('[data-lane-id]').forEach((row) => {
                row.classList.toggle('is-selected', isSelected(row));
            });
            if (this.picker) {
                this.picker.querySelectorAll('[data-lane-id]').forEach((chip) => {
                    chip.setAttribute('aria-pressed', String(isSelected(chip)));
                });
            }
        }
    }

    global.Densitometry = global.Densitometry || {};
    global.Densitometry.LanesView = LanesView;
})(window);
