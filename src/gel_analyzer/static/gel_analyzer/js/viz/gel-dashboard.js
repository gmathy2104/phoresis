/**
 * GelAnalyzer.Viz.GelDashboard — the gel dashboard page (templates/gel_analyzer/dashboard/gels.html).
 *
 * A picker of analysed gels and their lanes on the left; on the right two tiles fed by the ticked lanes:
 *
 *   - "Gel": the whole gel of the lane in focus, every lane outlined and numbered, the lane's bands, its kDa
 *     axis and its stored intensity profile (GelAnalyzer.Viz.SampleLaneGel).
 *   - the comparison component (GelAnalyzer.Viz.Comparison, through GelAnalyzer.SampleComparison.Kinds so
 *     that ONE assay is drawn at a time): lanes side by side on a common kDa axis, intensity profiles,
 *     purity / western readout chart, band detail and band table.
 *
 * Nothing is computed here. A lane's data is the comparison item the server builds
 * (api_lane_comparison_data: services/comparison_items.lane_item + enrich), fetched once per lane and kept;
 * the tiles are the components the comparison page mounts. The selection lives in the URL (?lanes=1,2,3), so
 * a dashboard can be bookmarked; nothing is stored in the browser.
 *
 *   GelAnalyzer.Viz.GelDashboard.init({ gels, selected, maxLanes, purityThresholds, csrfToken, apiUrls });
 */
(function (global) {
    'use strict';

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    const TYPE_CLASS = {
        SAMPLE: 'sample', LADDER: 'ladder', CONTROL: 'control', EMPTY: 'empty', DOT: 'dot', CALIBRATION: 'calibration',
    };

    function init(cfg) {
        const $ = (id) => document.getElementById(id);
        const els = {
            gels: $('gd-gels'), search: $('gd-search'), note: $('gd-picker-note'), count: $('gd-count'),
            clear: $('gd-clear'), open: $('gd-open-comparison'),
            gelHost: $('gd-gel'), gelEmpty: $('gd-gel-empty'), gelSub: $('gd-gel-sub'), gelOpen: $('gd-gel-open'),
            gelBands: $('gd-gel-bands'), gelDim: $('gd-gel-dim'),
            cmpHost: $('gd-comparison'), cmpEmpty: $('gd-cmp-empty'),
        };
        const toast = (message, level) => (global.gaToast ? global.gaToast(message, level || 'warning') : console.warn(message));
        const Events = (global.SampleComparison && global.SampleComparison.Events) || {};
        const maxLanes = cfg.maxLanes || 20;

        const gels = cfg.gels || [];
        const laneIndex = new Map();      // lane id -> {gel, lane}
        gels.forEach((gel) => gel.lanes.forEach((lane) => laneIndex.set(lane.id, { gel, lane })));

        const selected = [];              // lane ids, in the order they were ticked
        const items = new Map();          // lane id -> comparison item (fetched once)
        const pending = new Set();        // lane ids being fetched
        let focusId = null;               // the lane whose gel the "Gel" tile shows
        let gelHandle = null;
        let gelEntryKey = null;
        let filter = '';

        // ------------------------------------------------------------------ the comparison tile

        const kinds = global.GelAnalyzer.SampleComparison.Kinds.create({
            host: els.cmpHost,
            items: [],
            apiUrls: cfg.apiUrls,
            csrfToken: cfg.csrfToken,
            purityThresholds: cfg.purityThresholds,
            switchEl: $('gd-kinds'),
            otherEl: $('gd-other'),
        });
        // A lane closed from inside the component (its card's ✕) is unticked here too.
        if (Events.SAMPLE_REMOVED) {
            kinds.handle.on(Events.SAMPLE_REMOVED, (data) => {
                const id = data && data.sampleId;
                const laneId = Number(String(id).replace('lane_', ''));
                const at = selected.indexOf(laneId);
                if (at >= 0) {
                    selected.splice(at, 1);
                    if (focusId === laneId) focusId = selected.length ? selected[selected.length - 1] : null;
                    refresh();
                }
            });
        }

        // ------------------------------------------------------------------ data

        function laneUrl(laneId) {
            return cfg.apiUrls.laneData.replace('{laneId}', laneId);
        }

        async function fetchItem(laneId) {
            if (items.has(laneId)) return items.get(laneId);
            const response = await fetch(laneUrl(laneId), { credentials: 'same-origin', headers: { Accept: 'application/json' } });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const item = await response.json();
            items.set(laneId, item);
            return item;
        }

        async function tick(laneId) {
            if (selected.includes(laneId) || pending.has(laneId)) return;
            if (selected.length + pending.size >= maxLanes) {
                toast(`The dashboard shows up to ${maxLanes} lanes: untick one first.`);
                renderPicker();
                return;
            }
            pending.add(laneId);
            renderPicker();
            try {
                const item = await fetchItem(laneId);
                pending.delete(laneId);
                selected.push(laneId);
                kinds.handle.addSample(item);
                focusId = laneId;
            } catch (error) {
                pending.delete(laneId);
                const known = laneIndex.get(laneId);
                toast(`Lane ${known ? known.lane.number : laneId} could not be loaded (${error.message}).`, 'danger');
            }
            refresh();
        }

        function untick(laneId) {
            const at = selected.indexOf(laneId);
            if (at < 0) return;
            selected.splice(at, 1);
            if (focusId === laneId) focusId = selected.length ? selected[selected.length - 1] : null;
            kinds.handle.dropSample(`lane_${laneId}`);
            refresh();
        }

        // ------------------------------------------------------------------ the "Gel" tile

        function gelEntry(laneId) {
            const item = items.get(laneId);
            if (!item || !item.strip) return null;
            // The item carries the profile once (item.profile); the strip entry leaves it out on purpose.
            const profile = item.profile && item.profile.y_positions && item.profile.intensities
                && item.profile.y_positions.length === item.profile.intensities.length
                ? { y: item.profile.y_positions, intensity: item.profile.intensities }
                : null;
            return Object.assign({}, item.strip, { profile });
        }

        function renderGelTile() {
            const SampleLaneGel = global.GelAnalyzer.Viz.SampleLaneGel;
            const entry = focusId != null ? gelEntry(focusId) : null;
            const known = focusId != null ? laneIndex.get(focusId) : null;
            if (!entry || !SampleLaneGel) {
                if (gelHandle) { gelHandle.destroy(); gelHandle = null; gelEntryKey = null; }
                els.gelHost.hidden = true;
                els.gelEmpty.hidden = false;
                els.gelSub.textContent = '';
                els.gelOpen.hidden = true;
                return;
            }
            els.gelEmpty.hidden = true;
            els.gelHost.hidden = false;
            const options = { dimOthers: els.gelDim.checked, bandOverlay: els.gelBands.checked };
            // One mount per lane: the component builds its image once per entry (the proxy answers no-cache).
            if (gelEntryKey !== focusId) {
                if (gelHandle) gelHandle.destroy();
                gelHandle = SampleLaneGel.mount(els.gelHost, Object.assign({ entry, selfLabel: 'in focus' }, options));
                gelEntryKey = focusId;
            } else if (gelHandle) {
                gelHandle.update(options);
            }
            const gel = known ? known.gel : null;
            const purity = entry.purity != null ? ` · purity ${Number(entry.purity).toFixed(1)} %` : '';
            els.gelSub.textContent = gel
                ? `${gel.filename}${gel.name ? ' — ' + gel.name : ''} · lane ${entry.lane_number}${purity}`
                : `Lane ${entry.lane_number}${purity}`;
            if (gel) {
                els.gelOpen.href = gel.url;
                els.gelOpen.hidden = false;
            }
        }

        // ------------------------------------------------------------------ the picker

        function matches(gel) {
            if (!filter) return true;
            const haystack = [gel.filename, gel.name, gel.assay].concat(gel.lanes.map((lane) => lane.sample)).join(' ').toLowerCase();
            return haystack.includes(filter);
        }

        function gelHtml(gel) {
            const pickable = gel.lanes.filter((lane) => lane.analysed);
            const tickedHere = pickable.filter((lane) => selected.includes(lane.id)).length;
            const samples = pickable.filter((lane) => lane.type === 'SAMPLE');
            const open = tickedHere > 0 || !!filter;
            const lanes = gel.lanes.map((lane) => {
                const checked = selected.includes(lane.id);
                const busy = pending.has(lane.id);
                const purity = lane.purity != null ? `<span class="gd-lane-purity">${lane.purity.toFixed(1)} %</span>` : '';
                const focus = checked
                    ? `<button type="button" class="gd-lane-focus${focusId === lane.id ? ' is-on' : ''}" data-focus="${lane.id}" title="Show this lane on its gel" aria-label="Show lane ${lane.number} on its gel"><i class="bi bi-eye" aria-hidden="true"></i></button>`
                    : '';
                return `
                    <li class="gd-lane${lane.analysed ? '' : ' is-off'}${busy ? ' is-busy' : ''}">
                        <label title="${lane.analysed ? '' : 'No densitometry yet for this lane'}">
                            <input type="checkbox" data-lane="${lane.id}"${checked || busy ? ' checked' : ''}${lane.analysed && !busy ? '' : ' disabled'}>
                            <span class="gd-lane-n gd-lane-n--${TYPE_CLASS[lane.type] || 'sample'}" title="${esc(lane.type_label)}">${lane.number}</span>
                            <span class="gd-lane-name">${esc(lane.sample || lane.type_label)}</span>
                        </label>
                        ${purity}${focus}
                    </li>`;
            }).join('');
            return `
                <details class="gd-gel" data-gel="${esc(gel.id)}"${open ? ' open' : ''}>
                    <summary>
                        <span class="gd-gel-name" title="${esc(gel.filename)}">${esc(gel.filename)}</span>
                        ${tickedHere ? `<span class="gd-gel-n">${tickedHere}</span>` : ''}
                        <span class="gd-gel-meta">${esc(gel.assay)} · ${esc(gel.created)}${gel.name ? ' · ' + esc(gel.name) : ''}</span>
                    </summary>
                    <div class="gd-gel-tools">
                        <button type="button" class="gd-link" data-all="${esc(gel.id)}"${samples.length ? '' : ' disabled'}>Tick the ${samples.length} sample lane${samples.length === 1 ? '' : 's'}</button>
                        <button type="button" class="gd-link" data-none="${esc(gel.id)}"${tickedHere ? '' : ' disabled'}>Untick</button>
                        <a class="gd-link" href="${esc(gel.url)}">Analysis</a>
                    </div>
                    <ul class="gd-lanes">${lanes}</ul>
                </details>`;
        }

        function renderPicker() {
            // Keep what the user opened: <details> are rebuilt, their open state is not ours to lose.
            const wasOpen = new Set([...els.gels.querySelectorAll('details[open]')].map((d) => d.dataset.gel));
            const shown = gels.filter(matches);
            if (!gels.length) {
                els.gels.innerHTML = '<p class="gd-none">No analysed gel yet. Run the densitometry of an analysis: its lanes then appear here.</p>';
                return;
            }
            els.gels.innerHTML = shown.length
                ? shown.map(gelHtml).join('')
                : '<p class="gd-none">No gel matches this filter.</p>';
            els.gels.querySelectorAll('details').forEach((d) => { if (wasOpen.has(d.dataset.gel)) d.open = true; });
        }

        // ------------------------------------------------------------------ the page

        function syncUrl() {
            const url = new URL(global.location.href);
            if (selected.length) url.searchParams.set('lanes', selected.join(','));
            else url.searchParams.delete('lanes');
            global.history.replaceState(null, '', url.pathname + (url.search ? url.search.replace(/%2C/g, ',') : ''));
        }

        function refresh() {
            const n = selected.length;
            els.count.textContent = kinds.countText ? kinds.countText() : `${n} lane${n === 1 ? '' : 's'}`;
            els.clear.disabled = !n;
            els.cmpHost.hidden = !n;
            els.cmpEmpty.hidden = !!n;
            if (n) {
                els.open.href = `${els.open.dataset.href}?lanes=${selected.join(',')}`;
                els.open.classList.remove('is-disabled');
                els.open.removeAttribute('aria-disabled');
            } else {
                els.open.removeAttribute('href');
                els.open.classList.add('is-disabled');
                els.open.setAttribute('aria-disabled', 'true');
            }
            renderPicker();
            renderGelTile();
            syncUrl();
        }

        els.gels.addEventListener('change', (event) => {
            const box = event.target.closest('input[data-lane]');
            if (!box) return;
            const laneId = Number(box.dataset.lane);
            if (box.checked) tick(laneId);
            else untick(laneId);
        });
        els.gels.addEventListener('click', (event) => {
            const focus = event.target.closest('[data-focus]');
            if (focus) {
                focusId = Number(focus.dataset.focus);
                refresh();
                return;
            }
            const all = event.target.closest('[data-all]');
            const none = event.target.closest('[data-none]');
            if (!all && !none) return;
            const gel = gels.find((g) => g.id === (all || none).dataset[all ? 'all' : 'none']);
            if (!gel) return;
            if (all) {
                // One after the other: the order ticked is the order drawn.
                gel.lanes.filter((lane) => lane.analysed && lane.type === 'SAMPLE')
                    .reduce((chain, lane) => chain.then(() => tick(lane.id)), Promise.resolve());
            } else {
                gel.lanes.forEach((lane) => untick(lane.id));
            }
        });
        els.search.addEventListener('input', () => {
            filter = els.search.value.trim().toLowerCase();
            renderPicker();
        });
        els.clear.addEventListener('click', () => {
            selected.slice().forEach((laneId) => untick(laneId));
        });
        [els.gelBands, els.gelDim].forEach((box) => box.addEventListener('change', renderGelTile));

        refresh();
        // ?lanes= from the URL, in order; a lane that no longer exists or has no densitometry is skipped.
        (cfg.selected || [])
            .filter((laneId) => laneIndex.has(laneId) && laneIndex.get(laneId).lane.analysed)
            .reduce((chain, laneId) => chain.then(() => tick(laneId)), Promise.resolve());

        return { selected: () => selected.slice(), kinds };
    }

    global.GelAnalyzer = global.GelAnalyzer || {};
    global.GelAnalyzer.Viz = global.GelAnalyzer.Viz || {};
    global.GelAnalyzer.Viz.GelDashboard = { init };
})(window);
