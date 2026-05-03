/**
 * Lane Picker panel — cross-gel LADDER lane search with multi-select.
 *
 * Mounts into .lts-panel-picker, replaces the placeholder on boot.
 * Emits `selection:changed` with the updated Set of lane ids.
 */
(function () {
    'use strict';

    const LTS = window.LTS;
    if (!LTS) {
        console.error('[LaneP icker] LTS core not found.');
        return;
    }

    const { bus, api, state, constants } = LTS;
    const { MAX_LANES } = constants;

    // Mini-crop thumbnail dims (px).
    const CROP_W = 34;
    const CROP_H = 100;

    const panelEl = document.querySelector('.lts-panel-picker');
    if (!panelEl) return;

    function render() {
        panelEl.innerHTML = `
            <h2 class="lts-panel-title"><i class="bi bi-collection"></i> Lane picker</h2>
            <div class="lts-picker-filters">
                <label class="lts-filter-toggle">
                    <input type="checkbox" id="lts-f-only-bands" checked>
                    <span>Only lanes with bands</span>
                </label>
                <label class="lts-filter-toggle">
                    <input type="checkbox" id="lts-f-exclude-cal">
                    <span>Hide already calibrated for this template</span>
                </label>
                <input type="search" class="lts-filter-search" id="lts-f-search"
                       placeholder="Filter by analysis name…">
            </div>
            <div class="lts-picker-meta" id="lts-picker-meta">Loading…</div>
            <div class="lts-picker-list" id="lts-picker-list"></div>
        `;

        els.onlyBands = panelEl.querySelector('#lts-f-only-bands');
        els.excludeCal = panelEl.querySelector('#lts-f-exclude-cal');
        els.search = panelEl.querySelector('#lts-f-search');
        els.meta = panelEl.querySelector('#lts-picker-meta');
        els.list = panelEl.querySelector('#lts-picker-list');

        els.onlyBands.addEventListener('change', fetchLanes);
        els.excludeCal.addEventListener('change', fetchLanes);
        els.search.addEventListener('input', () => {
            clearTimeout(searchDebounce);
            searchDebounce = setTimeout(renderList, 200);
        });
    }

    const els = {};
    let searchDebounce = null;

    async function fetchLanes() {
        els.meta.textContent = 'Loading…';
        els.list.innerHTML = '';
        try {
            const params = {
                only_with_bands: els.onlyBands.checked ? '1' : '0',
                exclude_calibrated: els.excludeCal.checked ? '1' : '0',
                limit: 200,
            };
            const data = await api.lanesAvailable(params);
            state.availableLanes = data.rows || [];
            renderList();
        } catch (err) {
            console.error('[LanePicker] fetch failed:', err);
            els.meta.textContent = 'Failed to load lanes.';
        }
    }

    function renderList() {
        const q = (els.search.value || '').trim().toLowerCase();
        const rows = state.availableLanes.filter(r => {
            if (!q) return true;
            return (r.analysis_name || '').toLowerCase().includes(q)
                || (r.gel_image_filename || '').toLowerCase().includes(q);
        });

        els.meta.textContent = `${rows.length} lane${rows.length === 1 ? '' : 's'} available${
            q ? ' (filtered)' : ''
        } · ${state.selectedLaneIds.size} selected`;

        if (!rows.length) {
            els.list.innerHTML = '<div class="lts-empty">No LADDER lanes match the filters.</div>';
            return;
        }

        els.list.innerHTML = rows.map(renderRow).join('');
        els.list.querySelectorAll('.lts-picker-row').forEach(rowEl => {
            rowEl.addEventListener('click', (e) => {
                // Click anywhere on the row toggles selection except on the analysis link.
                if (e.target.closest('a')) return;
                toggleLane(rowEl.dataset.laneId);
            });
        });
    }

    function renderRow(r) {
        const bbox = r.lane_bbox || {};
        const selected = state.selectedLaneIds.has(r.lane_id);
        const disabled = !selected && state.selectedLaneIds.size >= MAX_LANES;

        // CSS-cropped thumbnail: we load the full gel image as background and scale
        // so the lane height fits CROP_H, then offset so the lane column is visible.
        let cropStyle = 'background: repeating-linear-gradient(45deg,#1e293b,#1e293b 6px,#0f172a 6px,#0f172a 12px);';
        if (r.gel_image_id && r.gel_image_width && r.gel_image_height && bbox.height) {
            const scale = CROP_H / Math.max(1, bbox.height);
            const bgW = r.gel_image_width * scale;
            const bgH = r.gel_image_height * scale;
            const offX = -bbox.x * scale + Math.max(0, (CROP_W - bbox.width * scale) / 2);
            const offY = -bbox.y * scale;
            const imgUrl = `/gel-analyzer/api/images/${r.gel_image_id}/proxy/`;
            cropStyle = `background-image: url(${imgUrl});`
                + `background-size: ${bgW.toFixed(1)}px ${bgH.toFixed(1)}px;`
                + `background-position: ${offX.toFixed(1)}px ${offY.toFixed(1)}px;`
                + `background-repeat: no-repeat;background-color:#0f172a;`;
        }

        const calibratedBadge = r.already_calibrated_for_this_template
            ? '<span class="lts-row-badge lts-row-badge-cal" title="Already calibrated for this template">CAL</span>'
            : '';

        const dateLabel = r.created_at ? new Date(r.created_at).toLocaleDateString() : '';

        return `
            <label class="lts-picker-row${selected ? ' is-selected' : ''}${disabled ? ' is-disabled' : ''}"
                   data-lane-id="${r.lane_id}">
                <input type="checkbox" class="lts-row-check" ${selected ? 'checked' : ''} ${disabled ? 'disabled' : ''}>
                <div class="lts-row-crop" style="${cropStyle}" aria-hidden="true"></div>
                <div class="lts-row-info">
                    <div class="lts-row-title">
                        Lane ${r.lane_number}
                        ${calibratedBadge}
                    </div>
                    <div class="lts-row-sub" title="${escapeAttr(r.analysis_name)}">${escapeHtml(truncate(r.analysis_name, 28))}</div>
                    <div class="lts-row-meta">
                        <span><i class="bi bi-grip-horizontal"></i> ${r.band_count} bands</span>
                        ${dateLabel ? `<span><i class="bi bi-calendar3"></i> ${dateLabel}</span>` : ''}
                    </div>
                </div>
            </label>
        `;
    }

    function toggleLane(laneId) {
        if (state.selectedLaneIds.has(laneId)) {
            state.selectedLaneIds.delete(laneId);
        } else {
            if (state.selectedLaneIds.size >= MAX_LANES) return;
            state.selectedLaneIds.add(laneId);
        }
        // Invalidate stale auto-assign.
        state.autoAssignResult = null;
        bus.emit('autoAssign:result', null);
        renderList();
        bus.emit('selection:changed', state.selectedLaneIds);
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
        return String(s || '').replace(/"/g, '&quot;');
    }

    // ─── Boot ─────────────────────────────────────────────────────────
    bus.on('studio:ready', () => {
        render();
        fetchLanes();
    });

    // Re-render when selection changes via another source (strip-view, etc).
    bus.on('selection:changed', () => {
        if (document.getElementById('lts-picker-list')) renderList();
    });
})();
