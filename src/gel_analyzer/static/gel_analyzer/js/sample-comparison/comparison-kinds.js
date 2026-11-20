/**
 * Comparison Kinds — one assay at a time on the gel comparison page (GelAnalyzer.SampleComparison.Kinds)
 *
 * A comparison may hold lanes of several assays (an SDS-PAGE, an anti-L1 and an anti-HCP western of the same
 * run). They are never drawn on one axis (owner, 2026-10-11 and 2026-10-12): the page shows ONE kind — one
 * assay, keyed by its name, the server's `item.kind` (services/comparison_items.py::kind_of) — and a switch.
 *
 * The page holds the ROSTER: every lane, every kind, in order. The comparison component is mounted with the
 * active kind's lanes only; a kind change destroys it and mounts it again (the PD sample comparison's way).
 * The page chrome (comparison-page-chrome.js) talks to `kinds.handle`, a STABLE handle that forwards to the
 * component mounted now: it remembers the view options (normalisation, tolerance, axis, POI only) and replays
 * them on every mount, re-attaches the chrome's event listeners, and routes the wizard's additions through
 * the roster. Save reads the roster (`kinds.laneIds()`): every kind's lanes, never only the visible ones.
 *
 * Usage (compare.html):
 *   const kinds = GelAnalyzer.SampleComparison.Kinds.create({
 *       host, items, apiUrls, csrfToken, purityThresholds,
 *       switchEl, otherEl,            // the kind switch, the "N lanes in other assays" line
 *   });
 *   GelAnalyzer.SampleComparison.initPageChrome({ handle: kinds.handle, roster: kinds, hostEl: host, ... });
 */
(function (global) {
    'use strict';

    const STORE_KEY = 'gelComparisonKind';
    const LANES_VIEW_KEY = 'gelComparisonLanesView';

    // The cell a strip shows under it, by the kind's readout (services/analysis_detail.readout_columns keys).
    const HEADLINE_CELL = {
        PURITY: 'purity',
        MOLECULE_VARIANTS: 'main_band_percent',
        HOST_CELL_PROTEINS: 'hcp_signal_vs_reference_percent',
    };

    function esc(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function readStored() {
        try {
            return global.localStorage.getItem(STORE_KEY);
        } catch (_) {
            return null;
        }
    }

    function store(key, storeKey) {
        try {
            global.localStorage.setItem(storeKey || STORE_KEY, key);
        } catch (_) {
            /* private window: the choice simply does not persist */
        }
    }

    function readLanesView() {
        try {
            return global.localStorage.getItem(LANES_VIEW_KEY) === 'crops' ? 'crops' : 'side';
        } catch (_) {
            return 'side';
        }
    }

    /** The kind of an item: the server's; a host that sends none gets one by gel type. */
    function kindOf(item) {
        if (item && item.kind && item.kind.key) return item.kind;
        const gelType = (item && item.gel_type) || (item && item.analysis && item.analysis.gel_type) || 'Gel';
        const key = `${gelType} · no assay`;
        return { key, label: key, readout: 'NONE', readout_label: 'No readout', columns: [] };
    }

    function create(cfg) {
        cfg = cfg || {};
        const Events = (global.SampleComparison && global.SampleComparison.Events) || {};
        const toast = (msg, level) => (global.gaToast ? global.gaToast(msg, level || 'info') : console.info(msg));

        // The roster: every lane once (a duplicate lane would make Save fail half-way: the saved comparison's
        // lanes are unique and its PUT is not atomic).
        const roster = [];
        const ids = new Set();
        (cfg.items || []).forEach((item) => {
            if (item && item.id && !ids.has(item.id)) {
                ids.add(item.id);
                roster.push(item);
            }
        });

        const options = {};         // the view options the chrome set, replayed on every mount
        const listeners = [];       // [event, fn] the chrome registered, re-attached on every mount
        const mountHooks = [];      // run after every mount (the chrome re-binds its root controls)
        const changeHooks = [];     // run after every roster change (the chrome's lane count)
        const unmountHooks = [];    // run before every unmount (the chrome collapses its magnifier)
        let current = null;
        let activeKey = null;
        let strips = null;          // the LaneStrips handle of the mount
        let lanesView = readLanesView();

        /** The kinds in the roster: purity kinds first, then the others, each in order of first appearance. */
        function kinds() {
            const map = new Map();
            roster.forEach((item) => {
                const kind = kindOf(item);
                if (!map.has(kind.key)) map.set(kind.key, Object.assign({}, kind, { count: 0 }));
                map.get(kind.key).count += 1;
            });
            const all = [...map.values()];
            return all.filter((k) => k.readout === 'PURITY').concat(all.filter((k) => k.readout !== 'PURITY'));
        }

        function kindByKey(key) {
            return kinds().find((k) => k.key === key) || null;
        }

        function itemsOf(key) {
            return roster.filter((item) => kindOf(item).key === key);
        }

        function defaultKey() {
            const list = kinds();
            if (!list.length) return null;
            const stored = readStored();
            if (stored && list.some((k) => k.key === stored)) return stored;
            return list[0].key;  // purity kinds first
        }

        // ------------------------------------------------------------------ mount

        function onRemoved(data) {
            const id = data && data.sampleId;
            const index = roster.findIndex((item) => item.id === id);
            if (index >= 0) {
                roster.splice(index, 1);
                ids.delete(id);
            }
            if (activeKey && !itemsOf(activeKey).length) {
                // The last lane of this kind went: show the next kind (or the empty page).
                const next = defaultKey();
                if (next !== activeKey) {
                    activeKey = next;
                    mount();
                    return;
                }
            }
            renderChrome();
        }

        function onReordered(data) {
            // The visible kind's lanes take the new order inside the roster; the other kinds keep their places.
            const order = (data && data.sampleOrder) || [];
            const slots = [];
            roster.forEach((item, index) => {
                if (kindOf(item).key === activeKey) slots.push(index);
            });
            const byId = new Map(roster.map((item) => [item.id, item]));
            const reordered = order.map((id) => byId.get(id)).filter(Boolean);
            if (reordered.length !== slots.length) return;
            slots.forEach((slot, i) => { roster[slot] = reordered[i]; });
        }

        // ------------------------------------------------------------------ lanes side by side

        /** The kind's lanes as LaneStrips strips: the server's entry, the lane's colour and its readout. */
        function stripsOf(state, kind) {
            const key = kind ? HEADLINE_CELL[kind.readout] : null;
            return (state ? state.getSamples() : []).filter((s) => s.strip).map((s) => {
                const profile = s.profile && s.profile.y_positions
                    ? { y: s.profile.y_positions, intensity: s.profile.intensities }
                    : null;
                const r = s.readout || {};
                const cell = key ? (r.cells || {})[key] : null;
                let readout = null;
                if (key) {
                    if (r.carries === false || !cell) readout = { text: '—', cls: 'is-muted' };
                    else readout = cell.text ? { text: cell.text, cls: '' } : { text: cell.reason || '—', cls: 'is-muted' };
                }
                return {
                    key: s.sampleId,
                    color: s.color,
                    label: s.label,
                    entry: Object.assign({}, s.strip, { profile }),
                    readout,
                };
            });
        }

        /** The top-left panel: Side by side (LaneStrips, on a common kDa axis) | Crops (today's GelOverview). */
        function attachStrips() {
            const LaneStrips = global.GelAnalyzer && global.GelAnalyzer.Viz && global.GelAnalyzer.Viz.LaneStrips;
            const panel = cfg.host && cfg.host.querySelector('#gel-overview-panel');
            if (!LaneStrips || !panel || !current) return;
            const header = panel.querySelector('.dm-panel-header');
            const actions = header && header.querySelector('.dm-panel-actions');
            const content = panel.querySelector('.dm-panel-content');
            if (!actions || !content) return;

            const title = header.querySelector('.dm-panel-title');
            const toggle = document.createElement('div');
            toggle.className = 'dm-mode-toggle ga-cmp-lanesview';
            toggle.setAttribute('role', 'group');
            toggle.setAttribute('aria-label', 'Lanes view');
            toggle.innerHTML = `
                <button type="button" class="dm-mode-btn" data-lanes-view="side" title="The lanes side by side on a common kDa axis">Side by side</button>
                <button type="button" class="dm-mode-btn" data-lanes-view="crops" title="Each lane cropped from its gel image">Crops</button>`;
            actions.insertBefore(toggle, actions.firstChild);

            const host = document.createElement('div');
            host.className = 'ga-cmp-strips';
            panel.appendChild(host);
            const kind = activeKey ? kindByKey(activeKey) : null;
            strips = LaneStrips.mount(host, { strips: stripsOf(current.getState(), kind), kind: kind ? kind.label : '' });

            const cropControls = actions.querySelectorAll('[data-ga-control]');
            const apply = () => {
                const side = lanesView === 'side';
                host.hidden = !side;
                content.style.display = side ? 'none' : '';
                // The panel magnifier takes the panel's .dm-panel-content: the view shown. (GelOverview keeps
                // the element it found at init, so moving the class does not lose it.)
                content.classList.toggle('dm-panel-content', !side);
                host.classList.toggle('dm-panel-content', side);
                cropControls.forEach((el) => { el.style.display = side ? 'none' : ''; });
                if (title) title.lastChild.textContent = side ? 'Lanes side by side' : 'Gel Overview';
                toggle.querySelectorAll('[data-lanes-view]').forEach((b) => {
                    b.classList.toggle('active', b.dataset.lanesView === lanesView);
                });
                if (side && strips) strips.update({});
                setTimeout(() => global.dispatchEvent(new Event('resize')), 50);
            };
            toggle.addEventListener('click', (e) => {
                const button = e.target.closest('[data-lanes-view]');
                if (!button) return;
                lanesView = button.dataset.lanesView;
                store(lanesView, LANES_VIEW_KEY);
                apply();
            });
            const refresh = () => {
                if (strips) strips.update({ strips: stripsOf(current.getState(), kind) });
            };
            [Events.SAMPLE_ADDED, Events.SAMPLE_REMOVED, Events.SAMPLE_ORDER_CHANGED, Events.PROFILE_LOADED]
                .filter(Boolean)
                .forEach((event) => current.on(event, refresh));
            apply();
        }

        function mount() {
            if (current) {
                unmountHooks.forEach((fn) => { try { fn(); } catch (e) { console.warn(e); } });
                if (strips) {
                    strips.destroy();
                    strips = null;
                }
                current.destroy();
                current = null;
            }
            const kind = activeKey ? kindByKey(activeKey) : null;
            const mountOptions = Object.assign({}, options, {
                readout: kind ? kind.readout : 'NONE',
                columns: kind ? kind.columns || [] : [],
                kindLabel: kind ? kind.label : '',
                purityThresholds: cfg.purityThresholds || null,
            });
            current = global.GelAnalyzer.Viz.Comparison.mount(cfg.host, {
                samples: activeKey ? itemsOf(activeKey) : [],
                apiUrls: cfg.apiUrls,
                csrfToken: cfg.csrfToken,
                options: mountOptions,
            });
            // The roster first: the chrome's listeners then read it already updated.
            current.on(Events.SAMPLE_REMOVED, onRemoved);
            current.on(Events.SAMPLE_ORDER_CHANGED, onReordered);
            listeners.forEach(([event, fn]) => current.on(event, fn));
            current.on(Events.POI_ONLY_MODE_CHANGED, (d) => { options.poiOnlyMode = !!(d && d.enabled); });
            // The POI-only box is panel markup: it shows the remembered choice.
            const poiOnly = cfg.host && cfg.host.querySelector('[data-ga-control="poi-only-mode"]');
            if (poiOnly) poiOnly.checked = !!options.poiOnlyMode;
            attachStrips();
            renderChrome();
            mountHooks.forEach((fn) => { try { fn(current); } catch (e) { console.warn(e); } });
        }

        function selectKind(key) {
            if (!key || key === activeKey || !kindByKey(key)) return;
            activeKey = key;
            store(key);
            mount();
        }

        // ------------------------------------------------------------------ chrome

        function renderChrome() {
            changeHooks.forEach((fn) => { try { fn(); } catch (e) { console.warn(e); } });
            const list = kinds();
            if (cfg.switchEl) {
                cfg.switchEl.hidden = list.length < 2;
                cfg.switchEl.innerHTML = list.map((k) => `
                    <button type="button" data-kind="${esc(k.key)}" aria-pressed="${k.key === activeKey}"
                            title="${esc(k.readout_label)}">${esc(k.label)} <span class="ga-wb-kind-n">${k.count}</span></button>`).join('');
            }
            if (cfg.otherEl) {
                const others = list.filter((k) => k.key !== activeKey);
                const n = others.reduce((sum, k) => sum + k.count, 0);
                cfg.otherEl.hidden = !others.length;
                cfg.otherEl.innerHTML = others.length
                    ? `<span class="ga-wb-other-n">${n} lane${n === 1 ? '' : 's'} in other assay${others.length === 1 ? '' : 's'}:</span>` +
                      others.map((k) => `<button type="button" class="ga-wb-other-kind" data-kind="${esc(k.key)}">${esc(k.label)} · ${k.count}</button>`).join('')
                    : '';
            }
        }

        [cfg.switchEl, cfg.otherEl].forEach((el) => {
            if (!el) return;
            el.addEventListener('click', (e) => {
                const button = e.target.closest('[data-kind]');
                if (button) selectKind(button.dataset.kind);
            });
        });

        // ------------------------------------------------------------------ the stable handle

        const handle = {
            getState: () => (current ? current.getState() : null),
            getPanel: (name) => (current ? current.getPanel(name) : null),
            setOptions(partial) {
                Object.assign(options, partial || {});
                if (current) current.setOptions(partial);
            },
            /** The wizard's lane: once in the roster; drawn now when it is of the kind shown. */
            addSample(item) {
                if (!item || !item.id) return false;
                if (ids.has(item.id)) {
                    const where = kindOf(roster.find((i) => i.id === item.id)).label;
                    toast(`${item.label || 'This lane'} is already in the comparison (${where}).`, 'warning');
                    return false;
                }
                ids.add(item.id);
                roster.push(item);
                const key = kindOf(item).key;
                if (!activeKey) {
                    activeKey = key;
                    mount();
                } else if (key === activeKey && current) {
                    current.addSample(item);
                    renderChrome();
                } else {
                    toast(`${item.label || 'Lane'} added to ${kindOf(item).label}.`, 'info');
                    renderChrome();
                }
                return true;
            },
            removeSample: (id) => (current ? current.removeSample(id) : undefined),
            /**
             * Phoresis (gel dashboard): take a lane out of the roster whatever its kind. removeSample only reaches
             * the kind shown now; a lane of another kind is dropped from the roster directly.
             */
            dropSample(id) {
                const item = roster.find((i) => i.id === id);
                if (!item) return false;
                if (current && kindOf(item).key === activeKey) {
                    current.removeSample(id);   // SAMPLE_REMOVED -> onRemoved updates the roster and the chrome
                    return true;
                }
                roster.splice(roster.indexOf(item), 1);
                ids.delete(id);
                renderChrome();
                return true;
            },
            on(event, fn) {
                listeners.push([event, fn]);
                if (current) current.on(event, fn);
            },
            redraw: () => (current && current.redraw ? current.redraw() : undefined),
            destroy() {
                if (current) current.destroy();
                current = null;
            },
        };

        activeKey = defaultKey();
        mount();

        // Night | Day (dsh-theme.js): the panels read the theme when they are built and a lane takes its colour
        // when it is added, so the comparison is mounted again -- the PD dashboard re-mounts its tiles the same way.
        global.addEventListener('dsh:themechange', () => mount());

        return {
            handle,
            /** Every lane id of the comparison, every kind, in order: what Save posts. */
            laneIds: () => roster.map((item) => item.lane && item.lane.id).filter(Boolean),
            labels: () => roster.map((item) => item.label || ''),
            total: () => roster.length,
            activeKind: () => (activeKey ? kindByKey(activeKey) : null),
            activeCount: () => (activeKey ? itemsOf(activeKey).length : 0),
            kinds,
            options: () => Object.assign({}, options),
            onMount(fn) { mountHooks.push(fn); },
            onChange(fn) { changeHooks.push(fn); },
            beforeUnmount(fn) { unmountHooks.push(fn); },
            countText() {
                const total = roster.length;
                const list = kinds();
                const base = `${total} lane${total === 1 ? '' : 's'}`;
                return list.length > 1 ? `${base} · ${list.length} assays` : base;
            },
        };
    }

    global.GelAnalyzer = global.GelAnalyzer || {};
    global.GelAnalyzer.SampleComparison = global.GelAnalyzer.SampleComparison || {};
    global.GelAnalyzer.SampleComparison.Kinds = { create, kindOf };
})(window);
