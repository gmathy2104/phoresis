/**
 * Parallel Strip View panel — shows each selected lane side-by-side as
 * a vertical gel crop. After auto-assign, overlays the matched bands
 * with MW labels + flagged markers.
 *
 * Listens:
 *   - studio:ready
 *   - selection:changed   (Set<laneId>)
 *   - autoAssign:result   ({template_id, band_count_expected, lanes: [...]})
 */
(function () {
    'use strict';

    const LTS = window.LTS;
    if (!LTS) return;

    const { bus, state } = LTS;
    const STRIP_W = 62;
    const STRIP_MIN_H = 480;

    const panelEl = document.querySelector('.lts-panel-strips');
    if (!panelEl) return;

    let laneResultById = new Map();  // lane_id -> auto-assign lane result

    function render() {
        panelEl.innerHTML = `
            <h2 class="lts-panel-title"><i class="bi bi-bar-chart-steps"></i> Parallel strips</h2>
            <div class="lts-strips-wrapper" id="lts-strips-wrapper"></div>
        `;
        renderStrips();
    }

    function renderStrips() {
        const wrap = document.getElementById('lts-strips-wrapper');
        if (!wrap) return;

        const selectedIds = Array.from(state.selectedLaneIds);
        if (!selectedIds.length) {
            wrap.innerHTML = `
                <div class="lts-strips-empty">
                    <i class="bi bi-layers"></i>
                    <p>Pick lanes from the left panel — they'll appear here.</p>
                </div>
            `;
            return;
        }

        // Resolve selected lane rows to full metadata from state.availableLanes.
        const rows = selectedIds
            .map(id => state.availableLanes.find(r => r.lane_id === id))
            .filter(Boolean);

        wrap.innerHTML = rows.map(renderOne).join('');
    }

    function renderOne(r) {
        const bbox = r.lane_bbox || {};
        const result = laneResultById.get(r.lane_id);
        const ctx = LTS.ctx;
        const bandDefs = (ctx && ctx.bandDefinitions) || [];

        // Choose strip height so full lane fits + leaves breathing room.
        const stripH = Math.max(STRIP_MIN_H, Math.min(700, (bbox.height || STRIP_MIN_H)));
        const scale = stripH / Math.max(1, bbox.height || 1);
        const bgW = r.gel_image_width * scale;
        const bgH = r.gel_image_height * scale;
        const offX = -bbox.x * scale + Math.max(0, (STRIP_W - bbox.width * scale) / 2);
        const offY = -bbox.y * scale;

        let cropStyle = 'background: repeating-linear-gradient(45deg,#1e293b,#1e293b 6px,#0f172a 6px,#0f172a 12px);';
        if (r.gel_image_id) {
            const imgUrl = `/api/images/${r.gel_image_id}/proxy/`;
            cropStyle = `background-image: url(${imgUrl});`
                + `background-size: ${bgW.toFixed(1)}px ${bgH.toFixed(1)}px;`
                + `background-position: ${offX.toFixed(1)}px ${offY.toFixed(1)}px;`
                + `background-repeat: no-repeat;background-color:#0f172a;`;
        }

        // Expected_rf overlay: when the template is trained, show where each
        // MW is *expected* as a faint dashed blue line on the LEFT edge of
        // the strip. Instantly reveals whether the algorithm's placement
        // matches the template's learned positions.
        let expectedOverlay = '';
        if (bandDefs.length && bandDefs.every(d => typeof d.expected_rf === 'number')) {
            expectedOverlay = bandDefs.map(d => {
                // Y position of expected_rf on the strip: rf is 0..1 relative
                // to lane_top..lane_bottom. Strip origin = lane_top.
                const y = d.expected_rf * (bbox.height || 1) * scale;
                if (y < 0 || y > stripH) return '';
                const mw = d.mw_kda;
                const mwLabel = mw >= 100 ? mw.toFixed(0) : mw.toFixed(1);
                return `<div class="lts-strip-expected" style="top:${y.toFixed(1)}px;" title="Expected ${mw} kDa @ Rf ${d.expected_rf.toFixed(3)}"><span class="lts-strip-expected-label">${mwLabel}</span></div>`;
            }).join('');
        }

        // Band overlay: after auto-assign, render ALL detected bands. Matched
        // bands get a solid green/amber tick + MW label; dropped ones get a
        // thin grey outline (so the user can SEE the algorithm's choices).
        let overlays = '';
        let rSquaredLabel = '<span class="lts-strip-meta-pending">Not assigned</span>';
        if (result && result.all_bands && result.all_bands.length) {
            overlays = result.all_bands.map(b => {
                const bandY = (b.position_y - bbox.y) * scale;
                if (!b.matched) {
                    return `
                        <div class="lts-strip-band is-dropped" style="top:${bandY.toFixed(1)}px;"
                             title="Dropped · Rf ${(b.rf || 0).toFixed(3)}${b.intensity_peak ? ' · peak ' + Math.round(b.intensity_peak) : ''}">
                            <span class="lts-strip-band-tick"></span>
                        </div>
                    `;
                }
                const flaggedCls = b.matched_flagged ? ' is-flagged' : '';
                const mw = b.matched_mw_kda;
                const mwLabel = typeof mw === 'number'
                    ? (mw >= 100 ? mw.toFixed(0) : mw.toFixed(1))
                    : mw;
                return `
                    <div class="lts-strip-band${flaggedCls}" style="top:${bandY.toFixed(1)}px;"
                         title="MW ${escapeAttr(mw)} · Rf ${(b.rf || 0).toFixed(3)}${b.matched_flagged ? ' · FLAGGED' : ''}">
                        <span class="lts-strip-band-tick"></span>
                        <span class="lts-strip-band-label">${escapeHtml(mwLabel)}</span>
                    </div>
                `;
            }).join('');
            const r2 = result.r_squared;
            const r2fmt = r2 !== null && r2 !== undefined ? r2.toFixed(4) : '—';
            const r2cls = r2 === null || r2 === undefined ? 'na'
                : r2 >= 0.99 ? 'excellent'
                : r2 >= 0.95 ? 'good'
                : r2 >= 0.9 ? 'ok' : 'poor';
            rSquaredLabel = `<span class="lts-strip-meta-r2 lts-strip-meta-r2-${r2cls}">R² ${r2fmt}</span>`;
            if (result.flagged_count > 0) {
                rSquaredLabel += ` <span class="lts-strip-meta-flag">${result.flagged_count} flagged</span>`;
            }
        }

        // Strategy badge — makes it obvious whether the lane was reused from
        // a prior human calibration vs freshly auto-matched.
        let strategyBadge = '';
        if (result && result.matching_strategy) {
            const map = {
                existing_calibration: { label: 'EXISTING', cls: 'is-existing', title: 'Reused saved band↔MW matches' },
                rf_priors: { label: 'AUTO', cls: 'is-auto', title: 'Auto-matched via Rf priors + Hungarian/RANSAC' },
                top_n_intensity: { label: 'AUTO (top-N)', cls: 'is-auto', title: 'Untrained template — top-N by intensity fallback' },
            };
            const s = map[result.matching_strategy] || { label: result.matching_strategy, cls: 'is-auto', title: '' };
            strategyBadge = `<span class="lts-strip-strategy ${s.cls}" title="${s.title}">${escapeHtml(s.label)}</span>`;
        }

        return `
            <div class="lts-strip" data-lane-id="${r.lane_id}">
                <div class="lts-strip-head">
                    <div class="lts-strip-title">Lane ${r.lane_number} ${strategyBadge}</div>
                    <div class="lts-strip-sub" title="${escapeAttr(r.analysis_name)}">${escapeHtml(truncate(r.analysis_name, 18))}</div>
                </div>
                <div class="lts-strip-image-wrap" style="height:${stripH}px;">
                    <div class="lts-strip-image" style="${cropStyle} width:${STRIP_W}px;height:${stripH}px;">
                    </div>
                    <div class="lts-strip-expected-layer" style="width:${STRIP_W}px;height:${stripH}px;">${expectedOverlay}</div>
                    <div class="lts-strip-overlay" style="width:${STRIP_W}px;height:${stripH}px;">${overlays}</div>
                </div>
                <div class="lts-strip-meta">${rSquaredLabel}</div>
            </div>
        `;
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
        return escapeHtml(s);
    }

    // ─── Wiring ───────────────────────────────────────────────────────
    bus.on('studio:ready', render);
    bus.on('selection:changed', renderStrips);
    bus.on('autoAssign:result', (result) => {
        laneResultById.clear();
        if (result && result.lanes) {
            result.lanes.forEach(lane => laneResultById.set(lane.lane_id, lane));
        }
        renderStrips();
    });
})();
