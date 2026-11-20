/**
 * Sample Comparison App - Main Orchestrator
 *
 * Coordinates all panels and manages the comparison view lifecycle.
 * Panel implementations are in separate modules under panels/
 */

(function(global) {
    'use strict';

    // Get dependencies from namespaces
    const EventBus = global.GelAnalyzer?.Core?.EventBus;
    const ComparisonState = global.SampleComparison?.State;
    const ComparisonApi = global.SampleComparison?.Api;
    const ComparisonEvents = global.SampleComparison?.Events;

    // Get panel classes from namespace (loaded from separate files)
    const Panels = global.SampleComparison?.Panels || {};

    /**
     * Per-panel inner markup (headers / content / panel-local controls).
     *
     * This is the CORRECT per-panel inner DOM (Task 5/7 refactor): each panel
     * drills into these hooks via this.container.querySelector(...):
     *  - gelOverview / bandDetail / resultsTable drill to `.dm-panel-content`
     *  - chromatogram drills to `#chromatogram-container`
     *  - poiPurity renders directly into its own `#poi-purity-container`
     *    (`.dm-graphical-view-pane`) which lives INSIDE the chromatogram panel
     *    alongside `#chromatogram-container`, hidden by default — NOT a 5th grid
     *    cell (matches the `main` baseline scaffold).
     *  - sampleCards renders directly into its own `.dm-sample-cards` stripe
     *
     * Panel-relevant controls (gel toolbar, electropherogram POI-only) live in
     * this markup so the component is self-contained; the panels wire them via
     * this.container.querySelector(...) with tracked listeners.
     */
    // The readout tab of the graphical view, by the kind's readout (the comparison page mounts one kind at a
    // time): PURITY "Purity", a western "Variants" / "HCP vs reference", NONE none. No readout given (the dev
    // showcase): today's "POI Purity". The Profiles button keeps data-view="electropherogram" (the page chrome
    // and its tests key on it); any other view shows the readout pane.
    const READOUT_TABS = {
        PURITY: { view: 'poi-purity', label: 'Purity', icon: 'bi-bar-chart-fill', title: 'Purity of each lane, as the gel pages publish it' },
        MOLECULE_VARIANTS: { view: 'readout', label: 'Variants', icon: 'bi-bar-chart-steps', title: 'HMWS (high molecular weight species), main band and LMWS (low molecular weight species) of each lane' },
        HOST_CELL_PROTEINS: { view: 'readout', label: 'HCP vs reference', icon: 'bi-bar-chart-line', title: "HCP signal of each lane in % of its blot's reference lane" },
        NONE: null,
    };

    function viewToggleMarkup(readout) {
        const tab = readout ? READOUT_TABS[readout] : { view: 'poi-purity', label: 'POI Purity', icon: 'bi-bar-chart-fill', title: 'POI Purity across samples' };
        const first = readout ? 'Profiles' : 'Electropherogram';
        const second = tab
            ? `<button class="dm-view-btn" data-view="${tab.view}" title="${tab.title}"><i class="bi ${tab.icon}"></i> ${tab.label}</button>`
            : '';
        return `<div class="dm-view-toggle me-2">
                        <button class="dm-view-btn active" data-view="electropherogram" title="Electropherogram overlay"><i class="bi bi-activity"></i> ${first}</button>
                        ${second}
                    </div>`;
    }

    const PANEL_MARKUP = {
        gelOverview: `
            <div class="dm-panel-header">
                <span class="dm-panel-title">
                    <i class="bi bi-image me-2"></i>Gel Overview
                </span>
                <div class="dm-panel-actions">
                    <button class="dm-gel-enhance-btn" data-ga-control="gel-auto-enhance" title="Auto-enhance all images">
                        <i class="bi bi-magic"></i>
                    </button>
                    <button class="dm-gel-invert-btn" data-ga-control="gel-invert-toggle" title="Invert image colors">
                        <i class="bi bi-circle-half"></i>
                    </button>
                    <button class="dm-gel-bands-toggle active" data-ga-control="gel-bands-toggle" title="Toggle band overlays">
                        <i class="bi bi-layers"></i>
                    </button>
                    <button class="dm-panel-expand-btn" data-panel="gel-overview-panel" title="Expand to fullscreen">
                        <i class="bi bi-arrows-fullscreen"></i>
                    </button>
                </div>
            </div>
            <div class="dm-panel-content"></div>
        `,
        // Chromatogram panel hosts BOTH graphical-view panes: the chromatogram
        // pane (#chromatogram-container) and the POI-purity pane
        // (#poi-purity-container — the poiPurity panel's slot, hidden by default).
        chromatogram: `
            <div class="dm-panel-header">
                <span class="dm-panel-title">
                    <i class="bi bi-graph-up me-2"></i>Graphical View
                </span>
                <div class="dm-panel-actions">
                    __VIEW_TOGGLE__
                    <div id="electropherogram-controls" class="dm-ephero-controls">
                        <div class="dm-mode-toggle me-2">
                            <button class="dm-mode-btn active" data-mode="mw" title="MW axis (log scale)"><i class="bi bi-bar-chart"></i> MW</button>
                            <button class="dm-mode-btn" data-mode="position" title="Y position (pixels)"><i class="bi bi-rulers"></i> Pos</button>
                        </div>
                        <label class="dm-sync-toggle me-2" title="Show only Protein of Interest bands">
                            <input type="checkbox" data-ga-control="poi-only-mode"> POI Only
                        </label>
                    </div>
                    <button class="dm-panel-expand-btn" data-panel="chromatogram-panel" title="Expand to fullscreen">
                        <i class="bi bi-arrows-fullscreen"></i>
                    </button>
                </div>
            </div>
            <div class="dm-panel-content">
                <div id="chromatogram-container" class="dm-graphical-view-pane"></div>
                <div id="poi-purity-container" class="dm-graphical-view-pane" data-ga-panel="poiPurity" style="display: none;"></div>
            </div>
        `,
        bandDetail: `
            <div class="dm-panel-header">
                <span class="dm-panel-title">
                    <i class="bi bi-zoom-in me-2"></i>Band Detail
                </span>
                <div class="dm-panel-actions">
                    <button class="dm-panel-expand-btn" data-panel="band-zoom-panel" title="Expand to fullscreen">
                        <i class="bi bi-arrows-fullscreen"></i>
                    </button>
                </div>
            </div>
            <div class="dm-panel-content"></div>
        `,
        resultsTable: `
            <div class="dm-panel-header">
                <span class="dm-panel-title">
                    <i class="bi bi-table me-2"></i>Band Comparison
                </span>
                <div class="dm-panel-actions">
                    <button class="dm-panel-expand-btn" data-panel="results-panel" title="Expand to fullscreen">
                        <i class="bi bi-arrows-fullscreen"></i>
                    </button>
                </div>
            </div>
            <div class="dm-panel-content"></div>
        `,
    };

    /**
     * SampleComparisonApp Class
     *
     * Container-scoped (Task 7): builds its OWN skeleton inside containerEl. The
     * comparison view needs the baseline 2×2 grid scaffold (.dm-main with two
     * .dm-panel-row rows + .dm-splitter handles) so PanelSplitter can wire the
     * resize splitters — so the App constructs the .ga-viz-root scaffold itself
     * and mounts each panel into its slot (the generic GelAnalyzer.Viz.mount flat
     * loop is intentionally NOT used here; it stays available for simpler hosts).
     *
     * Page chrome (header toolbar, wizard / save / report modals, splitter,
     * magnifier) stays in the consumer template and talks to the public handle.
     */
    class SampleComparisonApp {
        /**
         * @param {Object} options
         * @param {HTMLElement} options.containerEl - Empty host div to mount into
         * @param {string} options.csrfToken
         * @param {Object} options.apiUrls
         * @param {AbortSignal} [options.signal] - Threaded into the API client
         * @param {Object} [options.options] - View-option overrides + extras
         */
        constructor(options) {
            this.options = options || {};

            // Host container
            this.containerEl = options.containerEl;

            // Initialize core dependencies
            this.eventBus = new EventBus();
            this.state = new ComparisonState(this.eventBus);
            this.api = new ComparisonApi({
                csrfToken: options.csrfToken,
                apiUrls: options.apiUrls,
                signal: options.signal || null,
            });

            // Panels (populated by _buildScaffold)
            this.panels = {};

            // Skeleton handles (owned by this App; teardown contract preserved).
            this._root = null;
            this._tooltipLayer = null;
        }

        init() {
            if (!this.containerEl) {
                throw new Error('[SampleComparisonApp] containerEl is required to mount');
            }

            console.log('[SampleComparisonApp] Initializing (container-scoped)...');

            // Build the .ga-viz-root scaffold (2×2 grid + splitters) and
            // instantiate/init all panels into their slots.
            this._buildScaffold();

            // Apply any initial view-option overrides via the state setters.
            if (this.options.options) {
                this.setOptions(this.options.options);
            }

            // Component logic: profile-fetch orchestration on SAMPLE_ADDED.
            this._setupEventHandlers();

            // Legacy path: if the consumer passed initialSamples in options,
            // hydrate them now. The Comparison.mount factory hydrates via
            // state.addSample after init() instead (dual-mode).
            const initPromise = (this.options.initialSamples && this.options.initialSamples.length)
                ? this._loadInitialData()
                : Promise.resolve();

            return initPromise.then(() => {
                console.log('[SampleComparisonApp] Initialized with', this.state.samples.size, 'samples');
            });
        }

        /**
         * Build the .ga-viz-root scaffold and construct each panel into its slot.
         *
         * Reproduces the `main` baseline panel-area DOM so the comparison view's
         * 2×2 grid + resize splitters work:
         *
         *   .ga-viz-root  (containment boundary — all:initial in containment.css;
         *                  flex-column inline so .dm-sample-cards + .dm-main stack
         *                  and .dm-main's flex:1 fills the host)
         *     .ga-viz-tooltip-layer
         *     .dm-sample-cards                       → sampleCards slot
         *     <main class="dm-main">
         *       .dm-panel-row.dm-row-top
         *         .dm-panel.dm-panel-gel-overview    → gelOverview slot
         *         .dm-splitter.dm-splitter-v [top-row]
         *         .dm-panel.dm-panel-chromatogram    → chromatogram slot
         *             (#chromatogram-container + #poi-purity-container=poiPurity)
         *       .dm-splitter.dm-splitter-h [main]
         *       .dm-panel-row.dm-row-bottom
         *         .dm-panel.dm-panel-band-detail     → bandDetail slot
         *         .dm-splitter.dm-splitter-v [bottom-row]
         *         .dm-panel.dm-panel-results         → resultsTable slot
         *
         * PanelSplitter (wired by page chrome against the mounted root) needs
         * .dm-main + .dm-splitter[data-splitter=top-row|main|bottom-row]; those
         * exact hooks are emitted here.
         */
        _buildScaffold() {
            const containerEl = this.containerEl;
            if (containerEl.dataset.gaVizMounted) {
                throw new Error('[SampleComparisonApp] container already has a mounted Viz component.');
            }
            if (!global.d3) {
                throw new Error('[SampleComparisonApp] d3 must be loaded before mounting.');
            }
            containerEl.dataset.gaVizMounted = '1';

            // CSS-contained root (same contract as GelAnalyzer.Viz.mount). The
            // inline flex-column wins over containment.css `display:block` (which
            // follows `all:initial`) so the scaffold fills the host height.
            const root = document.createElement('div');
            root.className = 'ga-viz-root';
            root.style.display = 'flex';
            root.style.flexDirection = 'column';

            const tooltipLayer = document.createElement('div');
            tooltipLayer.className = 'ga-viz-tooltip-layer';
            root.appendChild(tooltipLayer);

            // --- Scaffold DOM -------------------------------------------------
            const sampleCardsSlot = document.createElement('div');
            sampleCardsSlot.className = 'dm-sample-cards';
            sampleCardsSlot.dataset.gaPanel = 'sampleCards';
            sampleCardsSlot.innerHTML =
                '<div class="dm-sample-cards-empty">' +
                '<i class="bi bi-plus-circle me-2"></i> Click "Add Sample" to start comparing' +
                '</div>';
            root.appendChild(sampleCardsSlot);

            const main = document.createElement('main');
            main.className = 'dm-main';

            // Top row: gel overview | v-splitter | chromatogram(+poiPurity).
            const rowTop = document.createElement('div');
            rowTop.className = 'dm-panel-row dm-row-top';

            const gelOverviewSlot = this._makePanelSlot(
                'dm-panel dm-panel-gel-overview', 'gelOverview', PANEL_MARKUP.gelOverview, 'gel-overview-panel');
            const readout = (this.options.options && this.options.options.readout) || null;
            const chromatogramSlot = this._makePanelSlot(
                'dm-panel dm-panel-chromatogram', 'chromatogram',
                PANEL_MARKUP.chromatogram.replace('__VIEW_TOGGLE__', viewToggleMarkup(readout)), 'chromatogram-panel');

            rowTop.appendChild(gelOverviewSlot);
            rowTop.appendChild(this._makeSplitter('v', 'top-row'));
            rowTop.appendChild(chromatogramSlot);

            // Bottom row: band detail | v-splitter | results.
            const rowBottom = document.createElement('div');
            rowBottom.className = 'dm-panel-row dm-row-bottom';

            const bandDetailSlot = this._makePanelSlot(
                'dm-panel dm-panel-band-detail', 'bandDetail', PANEL_MARKUP.bandDetail, 'band-zoom-panel');
            const resultsSlot = this._makePanelSlot(
                'dm-panel dm-panel-results', 'resultsTable', PANEL_MARKUP.resultsTable, 'results-panel');

            rowBottom.appendChild(bandDetailSlot);
            rowBottom.appendChild(this._makeSplitter('v', 'bottom-row'));
            rowBottom.appendChild(resultsSlot);

            main.appendChild(rowTop);
            main.appendChild(this._makeSplitter('h', 'main'));
            main.appendChild(rowBottom);
            root.appendChild(main);

            // poiPurity slot lives INSIDE the chromatogram panel content.
            const poiPuritySlot = chromatogramSlot.querySelector('#poi-purity-container');

            // --- Construct panels into their slots ----------------------------
            const panelOptions = Object.assign({ app: this }, this.options.options || {});
            const slotMap = [
                ['sampleCards', Panels.SampleCards, sampleCardsSlot],
                ['gelOverview', Panels.GelOverview, gelOverviewSlot],
                ['chromatogram', Panels.Chromatogram, chromatogramSlot],
                ['poiPurity', Panels.PoiPurity, poiPuritySlot],
                ['bandDetail', Panels.BandDetail, bandDetailSlot],
                ['resultsTable', Panels.ResultsTable, resultsSlot],
            ];

            const panels = {};
            try {
                slotMap.forEach(([name, PanelClass, slotEl]) => {
                    if (!PanelClass || !slotEl) return;
                    const panel = new PanelClass({
                        container: slotEl,
                        eventBus: this.eventBus,
                        state: this.state,
                        options: panelOptions,
                        tooltipLayer,
                    });
                    panel.init();
                    panels[name] = panel;
                });
                containerEl.appendChild(root);
            } catch (e) {
                // Transactional mount: undo the partial skeleton + sentinel.
                Object.values(panels).forEach((p) => { try { p.destroy(); } catch (_) { /* ignore */ } });
                root.remove();
                delete containerEl.dataset.gaVizMounted;
                throw e;
            }

            this._root = root;
            this._tooltipLayer = tooltipLayer;
            this.panels = panels;
        }

        /**
         * Build a .dm-panel slot with its [data-ga-panel] tag + inner markup.
         * The baseline panel id (gel-overview-panel / chromatogram-panel /
         * band-zoom-panel / results-panel) is restored so id-keyed CSS keeps
         * working — notably `#chromatogram-panel .dm-panel-content { position:
         * relative }`, which contains the absolutely-positioned graphical-view
         * panes (#chromatogram-container / #poi-purity-container).
         */
        _makePanelSlot(className, name, markup, id) {
            const el = document.createElement('div');
            el.className = className;
            el.dataset.gaPanel = name;
            if (id) el.id = id;
            if (markup) el.innerHTML = markup;
            return el;
        }

        /**
         * Build a .dm-splitter handle. PanelSplitter keys off the .dm-splitter-h
         * / .dm-splitter-v class and the data-splitter value (main|top-row|bottom-row).
         */
        _makeSplitter(orientation, kind) {
            const el = document.createElement('div');
            const orientClass = orientation === 'h' ? 'dm-splitter-h' : 'dm-splitter-v';
            el.className = 'dm-splitter ' + orientClass;
            el.dataset.splitter = kind;
            el.setAttribute('role', 'separator');
            el.setAttribute('aria-orientation', orientation === 'h' ? 'horizontal' : 'vertical');
            el.setAttribute('tabindex', '0');
            el.setAttribute('title', 'Drag to resize · double-click to reset');
            return el;
        }

        /**
         * Apply known view options through the state setters (single source of
         * truth — never duplicate the logic here). Unknown keys are ignored.
         * @param {Object} partial
         */
        setOptions(partial) {
            if (!partial) return;
            if (partial.poiOnlyMode !== undefined) this.state.setPoiOnlyMode(partial.poiOnlyMode);
            if (partial.scaleMode !== undefined) this.state.setScaleMode(partial.scaleMode);
            if (partial.xAxisMode !== undefined) this.state.setXAxisMode(partial.xAxisMode);
            if (partial.normalizationMode !== undefined) this.state.setNormalizationMode(partial.normalizationMode);
            if (partial.mwTolerance !== undefined) this.state.setMwTolerance(partial.mwTolerance);
            if (partial.digitalLaneMode !== undefined) this.state.setDigitalLaneMode(partial.digitalLaneMode);
        }

        /**
         * Tear down the mounted component: destroys every panel, removes the
         * .ga-viz-root (which owns the tooltipLayer), clears the App-owned
         * eventBus, and clears the mount sentinel — same teardown contract the
         * generic GelAnalyzer.Viz.mount handle provides.
         */
        destroy() {
            Object.values(this.panels).forEach((p) => {
                try { p.destroy(); } catch (e) {
                    console.warn('[SampleComparisonApp] panel destroy threw:', e);
                }
            });
            this.panels = {};
            if (this._root) {
                this._root.remove();  // removes the contained tooltipLayer too
                this._root = null;
            }
            this._tooltipLayer = null;
            // App owns the eventBus → App tears it down (removes the
            // SAMPLE_ADDED orchestration handler registered in _setupEventHandlers).
            if (this.eventBus && this.eventBus.clear) {
                this.eventBus.clear();
            }
            if (this.containerEl && this.containerEl.dataset && this.containerEl.dataset.gaVizMounted) {
                delete this.containerEl.dataset.gaVizMounted;
            }
        }

        _setupEventHandlers() {
            // Sample added - fetch profile if needed
            this.eventBus.on(ComparisonEvents.SAMPLE_ADDED, async (data) => {
                const sampleData = data.sampleData;
                if (sampleData.profile && sampleData.lane?.id) {
                    this.state.setProfile(sampleData.lane.id, sampleData.profile);
                } else if (sampleData.lane && !sampleData.profile) {
                    try {
                        const profile = await this.api.getLaneProfile(sampleData.lane.id);
                        this.state.setProfile(sampleData.lane.id, profile);
                    } catch (e) {
                        if (e.name === 'AbortError') return;
                        console.warn('[SampleComparisonApp] Failed to load profile:', e);
                    }
                }
            });

        }

        async _loadInitialData() {
            const initialSamples = this.options.initialSamples || [];

            if (initialSamples.length === 0) {
                console.log('[SampleComparisonApp] No initial samples');
                return;
            }

            for (const sampleData of initialSamples) {
                this.state.addSample(sampleData);

                if (sampleData.profile && sampleData.lane?.id) {
                    this.state.setProfile(sampleData.lane.id, sampleData.profile);
                }
            }

            // Load profiles from API for samples without profile data
            for (const sampleData of this.state.getSamples()) {
                if (sampleData.lane && !this.state.getProfile(sampleData.lane.id)) {
                    try {
                        const profile = await this.api.getLaneProfile(sampleData.lane.id);
                        this.state.setProfile(sampleData.lane.id, profile);
                    } catch (e) {
                        if (e.name === 'AbortError') return;
                        console.warn('[SampleComparisonApp] Failed to load profile for lane', sampleData.lane.id);
                    }
                }
            }

            this.eventBus.emit(ComparisonEvents.DATA_LOADED, {
                samples: this.state.getSamples(),
            });
        }

        /**
         * Remove a sample by its sampleId. Kept (not dead): the sample-cards
         * panel's per-card remove button calls this.app.removeSample(id).
         * Page chrome (wizard/header) drives adds via the handle → state.addSample.
         */
        removeSample(sampleId) {
            this.state.removeSample(sampleId);
        }

        getState() {
            return this.state;
        }
    }

    // Export to namespace
    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.App = SampleComparisonApp;

    // =====================================================================
    // Public factory: GelAnalyzer.Viz.Comparison.mount(containerEl, cfg)
    //
    // Mounts the whole comparison component inline into ANY empty host div.
    // Data load: cfg.samples: [sampleData, ...] (already-resolved lane rows).
    // Phoresis compares lanes only: ds-hub's "resolve" mode (cfg.keys +
    // cfg.resolveUrl, Process Development samples) does not exist here.
    //
    // Returns a host-owned handle. The host calls handle.destroy() to abort
    // any in-flight fetch and tear down the component.
    // =====================================================================
    function mountComparison(containerEl, cfg) {
        cfg = cfg || {};

        const controller = new AbortController();

        const app = new SampleComparisonApp({
            containerEl,
            csrfToken: cfg.csrfToken,
            apiUrls: cfg.apiUrls,
            signal: controller.signal,
            options: cfg.options || {},
        });

        // init() returns a promise (skeleton is synchronous; legacy initial
        // data load is awaited). Hydrate AFTER init so panels are subscribed.
        // Guard against synchronous throws (missing containerEl, double-mount,
        // GelAnalyzer.Viz undefined) so callers get an inert handle, not a crash.
        let initResult;
        try {
            initResult = app.init();
        } catch (e) {
            controller.abort();
            (cfg.onError || console.error)(e);
            // Inert handle so the caller's code does not crash on a failed mount.
            return {
                destroy() {},
                getState: () => null,
                getPanel: () => null,
                setOptions: () => {},
                addSample: () => {},
                removeSample: () => {},
                on: () => {},
            };
        }

        Promise.resolve(initResult).then(() => {
            if (Array.isArray(cfg.samples) && cfg.samples.length) {
                // Hydrated rows.
                cfg.samples.forEach((s) => app.state.addSample(s));
                if (cfg.onLoaded) cfg.onLoaded();
            } else if (cfg.onLoaded) {
                cfg.onLoaded();
            }
        });

        return {
            destroy() {
                controller.abort();
                app.destroy();
            },
            getState: () => app.state,
            getPanel: (n) => app.panels[n],
            setOptions: (p) => app.setOptions(p),
            addSample: (s) => app.state.addSample(s),
            removeSample: (id) => app.state.removeSample(id),
            on: (evt, cb) => app.eventBus.on(evt, cb),
            // PDD interaction adapter hook (T3 — color injection repaint)
            // Emits DATA_LOADED so all panels re-read colors via sample.color.
            redraw: () => app.eventBus.emit(
                ComparisonEvents.DATA_LOADED,
                { samples: app.state.getSamples() }
            ),
        };
    }

    global.GelAnalyzer = global.GelAnalyzer || {};
    global.GelAnalyzer.Viz = global.GelAnalyzer.Viz || {};
    global.GelAnalyzer.Viz.Comparison = global.GelAnalyzer.Viz.Comparison || {};
    global.GelAnalyzer.Viz.Comparison.mount = mountComparison;

})(window);
