/**
 * Validation Grid panel — matrix of (template MW × selected lanes).
 *
 * After auto-assign, each cell shows whether the lane matched a band
 * at this expected MW: green = matched, amber = flagged, grey = missing.
 * Footer rows show per-lane R² + flagged count.
 *
 * Click a cell → highlight the band (emits `cell:highlighted`).
 * Click a cell again → clear highlight.
 */
(function () {
    'use strict';

    const LTS = window.LTS;
    if (!LTS) return;

    const { bus, state, ctx } = LTS;

    const panelEl = document.querySelector('.lts-panel-grid');
    if (!panelEl) return;

    function render() {
        panelEl.innerHTML = `
            <h2 class="lts-panel-title"><i class="bi bi-grid-3x3-gap"></i> Validation grid</h2>
            <div class="lts-grid-wrapper" id="lts-grid-wrapper"></div>
        `;
        renderGrid();
    }

    function renderGrid() {
        const wrap = document.getElementById('lts-grid-wrapper');
        if (!wrap) return;

        const result = state.autoAssignResult;
        if (!result) {
            wrap.innerHTML = `
                <div class="lts-grid-empty">
                    <i class="bi bi-check2-square"></i>
                    <p>Pick lanes and click <b>Auto-assign top-N</b> to see the match grid.</p>
                </div>
            `;
            return;
        }

        const lanes = result.lanes || [];
        if (!lanes.length) {
            wrap.innerHTML = '<div class="lts-grid-empty"><p>Auto-assign returned no lanes.</p></div>';
            return;
        }

        // Template bands sorted by band_order (1 = highest MW).
        const bandDefs = (ctx.bandDefinitions || []).slice().sort((a, b) => a.band_order - b.band_order);

        // Build a lookup: lane_id → (band_order → match)
        const matchLookup = new Map();
        for (const lane of lanes) {
            const inner = new Map();
            for (const m of (lane.matches || [])) {
                inner.set(m.template_band_order, m);
            }
            matchLookup.set(lane.lane_id, inner);
        }

        const totalsMatched = bandDefs.map(bd => {
            let n = 0;
            for (const lane of lanes) {
                if (matchLookup.get(lane.lane_id).has(bd.band_order)) n++;
            }
            return n;
        });

        const headerHtml = `
            <thead>
                <tr>
                    <th class="lts-grid-corner">MW (kDa)</th>
                    ${lanes.map(l => {
                        const stratMap = {
                            existing_calibration: ['EXISTING', 'is-existing'],
                            rf_priors: ['AUTO', 'is-auto'],
                            top_n_intensity: ['AUTO', 'is-auto'],
                        };
                        const [label, cls] = stratMap[l.matching_strategy] || ['', ''];
                        const badge = label ? `<span class="lts-grid-strategy ${cls}">${label}</span>` : '';
                        return `
                        <th class="lts-grid-lanecol" title="${escapeAttr(l.analysis_name)}">
                            <div class="lts-grid-lanecol-title">Lane ${l.lane_number} ${badge}</div>
                            <div class="lts-grid-lanecol-sub">${escapeHtml(truncate(l.analysis_name, 14))}</div>
                        </th>
                        `;
                    }).join('')}
                </tr>
            </thead>
        `;

        const rowsHtml = bandDefs.map((bd, idx) => {
            const cellHtml = lanes.map(l => {
                const m = matchLookup.get(l.lane_id).get(bd.band_order);
                if (!m) {
                    return `<td class="lts-grid-cell is-missing" title="Missing on Lane ${l.lane_number}"><i class="bi bi-dash"></i></td>`;
                }
                const flaggedCls = m.flagged ? ' is-flagged' : ' is-matched';
                const icon = m.flagged ? 'bi-exclamation-triangle-fill' : 'bi-check-circle-fill';
                const title = `Lane ${l.lane_number} · ${bd.mw_kda} kDa\nRf ${(m.rf||0).toFixed(3)}${m.peak_intensity ? ` · peak ${Math.round(m.peak_intensity)}` : ''}${m.flagged ? ' · FLAGGED' : ''}`;
                return `
                    <td class="lts-grid-cell${flaggedCls}"
                        data-lane-id="${l.lane_id}" data-band-order="${bd.band_order}"
                        title="${escapeAttr(title)}">
                        <i class="bi ${icon}"></i>
                    </td>
                `;
            }).join('');
            const mwLabel = bd.mw_kda >= 100 ? bd.mw_kda.toFixed(0) : bd.mw_kda.toFixed(1);
            const supportBadge = `
                <span class="lts-grid-support" title="${totalsMatched[idx]} of ${lanes.length} lanes matched">
                    ${totalsMatched[idx]}/${lanes.length}
                </span>
            `;
            return `
                <tr>
                    <th class="lts-grid-mwcol">
                        <span>${mwLabel}</span>
                        ${supportBadge}
                    </th>
                    ${cellHtml}
                </tr>
            `;
        }).join('');

        const footerHtml = `
            <tfoot>
                <tr class="lts-grid-footer lts-grid-footer-r2">
                    <th class="lts-grid-mwcol">R²</th>
                    ${lanes.map(l => {
                        const r2 = l.r_squared;
                        const r2fmt = r2 !== null && r2 !== undefined ? r2.toFixed(4) : '—';
                        const r2cls = r2 === null || r2 === undefined ? 'na'
                            : r2 >= 0.99 ? 'excellent'
                            : r2 >= 0.95 ? 'good'
                            : r2 >= 0.9 ? 'ok' : 'poor';
                        return `<td class="lts-grid-r2 lts-grid-r2-${r2cls}">${r2fmt}</td>`;
                    }).join('')}
                </tr>
                <tr class="lts-grid-footer lts-grid-footer-flag">
                    <th class="lts-grid-mwcol">Flagged</th>
                    ${lanes.map(l => `<td class="lts-grid-flagcount ${l.flagged_count > 0 ? 'has-flags' : ''}">${l.flagged_count}</td>`).join('')}
                </tr>
                ${lanes.some(l => l.warnings && l.warnings.length) ? `
                <tr class="lts-grid-footer lts-grid-footer-warn">
                    <th class="lts-grid-mwcol">Warn</th>
                    ${lanes.map(l => `
                        <td class="lts-grid-warncount ${(l.warnings || []).length ? 'has-warns' : ''}"
                            title="${escapeAttr((l.warnings || []).join('\n'))}">
                            ${(l.warnings || []).length || ''}
                        </td>
                    `).join('')}
                </tr>
                ` : ''}
            </tfoot>
        `;

        wrap.innerHTML = `
            <table class="lts-grid-table">
                ${headerHtml}
                <tbody>${rowsHtml}</tbody>
                ${footerHtml}
            </table>
        `;

        wrap.querySelectorAll('.lts-grid-cell').forEach(cell => {
            cell.addEventListener('click', () => {
                wrap.querySelectorAll('.lts-grid-cell.is-highlighted').forEach(c => c.classList.remove('is-highlighted'));
                cell.classList.add('is-highlighted');
                bus.emit('cell:highlighted', {
                    laneId: cell.dataset.laneId,
                    bandOrder: parseInt(cell.dataset.bandOrder, 10),
                });
            });
        });
    }

    // ─── Utility ──────────────────────────────────────────────────────
    function truncate(s, n) {
        s = s || '';
        return s.length > n ? s.slice(0, n - 1) + '…' : s;
    }
    function escapeHtml(s) {
        return String(s || '').replace(/[&<>"']/g, c =>
            ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
        );
    }
    function escapeAttr(s) {
        return escapeHtml(s).replace(/\n/g, '&#10;');
    }

    // ─── Wiring ───────────────────────────────────────────────────────
    bus.on('studio:ready', render);
    bus.on('autoAssign:result', renderGrid);
    bus.on('selection:changed', () => {
        // If selection changes after an auto-assign, the grid is stale.
        // index.js already clears state.autoAssignResult — just re-render.
        renderGrid();
    });
})();
