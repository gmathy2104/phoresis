/**
 * Comparison Page Chrome Controller
 *
 * Wires the consumer template's page chrome (header toolbar, sample-selector
 * wizard, save-comparison modal, report-config modal, panel splitters, panel
 * magnifier, view/axis toggles) to a mounted GelAnalyzer.Viz.Comparison handle.
 *
 * The comparison COMPONENT now self-builds its panel skeleton + self-wires its
 * panel-local controls (gel toolbar, POI-only toggle). Everything OUTSIDE the
 * mount host (#sample-comparison-app) is page chrome and lives here, talking to
 * the component exclusively through the public handle:
 *   handle.getState() / addSample() / removeSample() / setOptions() / on()
 *
 * Usage (from the template, after mounting):
 *   GelAnalyzer.SampleComparison.initPageChrome({
 *       handle,                       // GelAnalyzer.Viz.Comparison.mount(...) result
 *       hostEl,                       // the #sample-comparison-app mount host
 *       csrfToken,                    // CSRF token string
 *       apiUrls,                      // { laneData, laneProfile, imagesWithDensitometry }
 *       savedComparisonId,            // string | null
 *       savedComparison,              // parsed JSON | null
 *       urls: { savedComparisons, generateReportTemplate },
 *       roster,                       // GelAnalyzer.SampleComparison.Kinds (optional)
 *   });
 *
 * With a `roster` (comparison-kinds.js: one assay mounted at a time), `handle` is the roster's STABLE handle
 * and the component is re-mounted on every kind switch: the controls that live inside the mounted root
 * (splitters, panel expand, the graphical-view and axis toggles) are re-bound by attachRoot() after each
 * mount, everything bound by id or on document is bound ONCE here (binding it again would double every Save),
 * and Save posts the roster's lanes -- every kind's, not only the visible ones.
 */
(function (global) {
    'use strict';

    const ComparisonEvents = global.SampleComparison?.Events || {};

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function initPageChrome(cfg) {
        cfg = cfg || {};
        const handle = cfg.handle;
        const hostEl = cfg.hostEl;
        const csrfToken = cfg.csrfToken;
        const apiUrls = cfg.apiUrls || {};
        const urls = cfg.urls || {};

        if (!handle) {
            console.error('[ComparisonPageChrome] handle is required');
            return null;
        }

        // Convenience accessors that always route through the live state.
        const getState = () => handle.getState();

        // =====================================================================
        // #sample-count — keep in sync with the live sample total
        // =====================================================================
        const sampleCountEl = document.getElementById('sample-count');
        const roster = cfg.roster || null;
        const updateSampleCount = (total) => {
            if (!sampleCountEl) return;
            if (roster) {
                sampleCountEl.textContent = roster.countText();
                return;
            }
            const n = (typeof total === 'number')
                ? total
                : (getState() ? getState().getSamples().length : 0);
            sampleCountEl.textContent = `${n} item(s)`;
        };
        // SAMPLE_ADDED / SAMPLE_REMOVED carry { totalSamples } in their payload.
        handle.on(ComparisonEvents.SAMPLE_ADDED, (d) => updateSampleCount(d && d.totalSamples));
        handle.on(ComparisonEvents.SAMPLE_REMOVED, (d) => updateSampleCount(d && d.totalSamples));

        // =====================================================================
        // Panel Splitters (operate on the mounted .ga-viz-root)
        // Defaults match the comparison view's original proportions.
        // =====================================================================
        let panelSplitter = null;
        const attachSplitter = (vizRoot) => {
            if (!global.GelAnalyzer?.Shared?.PanelSplitter || !hostEl) return;
            panelSplitter = new global.GelAnalyzer.Shared.PanelSplitter({
                appEl: vizRoot || hostEl,
                storageKey: 'gelComparisonLayout',
                defaults: { rowTopPct: 60, gelOverviewPct: 22, bandDetailPct: 34 },
            });
            panelSplitter.init();
            global.panelSplitter = panelSplitter;  // expose for debug / reset
        };

        // =====================================================================
        // Panel Magnifier — expand a generated .dm-panel to fullscreen overlay
        // The component generates panels as [data-ga-panel] / .dm-panel inside
        // the mount root; expand buttons in those generated headers carry
        // data-panel-expand (none today) — fall back to per-panel expand chrome
        // discovered inside the root.
        // =====================================================================
        const magnifier = {
            overlay: document.getElementById('panel-magnify-overlay'),
            title: document.getElementById('magnify-title'),
            content: document.getElementById('magnify-content'),
            closeBtn: document.getElementById('magnify-close'),
            activePanel: null,
            activeContent: null,

            expand(panelEl) {
                if (!panelEl || !this.overlay || !this.content) return;
                if (this.activePanel) this.collapse();

                const content = panelEl.querySelector('.dm-panel-content');
                const titleEl = panelEl.querySelector('.dm-panel-title');
                if (!content) return;

                this.activePanel = panelEl;
                this.activeContent = content;
                if (this.title) this.title.textContent = (titleEl?.textContent || 'Panel View').trim();

                this.content.appendChild(content);
                panelEl.classList.add('dm-panel-expanded');
                this.overlay.classList.add('active');
                setTimeout(() => global.dispatchEvent(new Event('resize')), 50);
            },

            collapse() {
                if (!this.activePanel || !this.activeContent) return;
                this.activePanel.appendChild(this.activeContent);
                this.activePanel.classList.remove('dm-panel-expanded');
                if (this.overlay) this.overlay.classList.remove('active');
                this.activePanel = null;
                this.activeContent = null;
                setTimeout(() => global.dispatchEvent(new Event('resize')), 50);
            },
        };
        if (magnifier.closeBtn) magnifier.closeBtn.addEventListener('click', () => magnifier.collapse());
        if (magnifier.overlay) {
            magnifier.overlay.addEventListener('click', (e) => {
                if (e.target === magnifier.overlay) magnifier.collapse();
            });
        }
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && magnifier.activePanel) magnifier.collapse();
        });
        // Wire expand buttons that the consumer template renders against generated
        // panels (delegated so it works even if panels re-render their headers).
        const attachExpand = (vizRoot) => {
            if (!vizRoot) return;
            vizRoot.addEventListener('click', (e) => {
                const btn = e.target.closest('.dm-panel-expand-btn');
                if (!btn) return;
                const panelEl = btn.closest('.dm-panel');
                if (panelEl) magnifier.expand(panelEl);
            });
        };
        // A kind switch destroys the mounted root: a panel shown in the magnifier goes home first.
        if (roster) roster.beforeUnmount(() => magnifier.collapse());

        // =====================================================================
        // Graphical View toggle (Electropherogram / POI Purity)
        // Both views live INSIDE the single generated chromatogram panel as two
        // .dm-graphical-view-pane children (#chromatogram-container and the
        // poiPurity slot #poi-purity-container). The toggle swaps which pane is
        // visible — the chromatogram panel itself stays mounted (matches the
        // `main` baseline). Do NOT hide the whole [data-ga-panel="chromatogram"]
        // wrapper, or the nested poiPurity pane goes with it.
        //
        // The view-toggle + mode-toggle buttons now live in the generated
        // chromatogram panel header (inside vizRoot) — queried by class/data-*
        // attributes rather than the removed top-toolbar ids.
        // =====================================================================
        let lastView = 'electropherogram';
        const attachToggles = (vizRoot) => {
            if (!vizRoot) return;
            const chromPane = vizRoot.querySelector('#chromatogram-container');
            const poiPane = vizRoot.querySelector('[data-ga-panel="poiPurity"]')
                || vizRoot.querySelector('#poi-purity-container');
            // #electropherogram-controls is inside the generated chromatogram panel header.
            const epheroControls = vizRoot.querySelector('#electropherogram-controls');

            // Scope view/mode toggle delegation to the chromatogram panel only, so that
            // the Band Detail panel's own .dm-mode-btn[data-mode="bands|pseudo-gel"] buttons
            // are never caught by the chromatogram axis handler (they live in a different subtree).
            const chromoPanel = vizRoot.querySelector('.dm-panel-chromatogram')
                || vizRoot.querySelector('[data-ga-panel="chromatogram"]');

            // Default: electropherogram visible, poi purity hidden (matches markup default).
            if (poiPane) poiPane.style.display = 'none';
            const showView = (view) => {
                chromoPanel.querySelectorAll('.dm-view-btn[data-view]').forEach((b) => {
                    b.classList.toggle('active', b.dataset.view === view);
                });
                const profiles = view === 'electropherogram';
                if (chromPane) chromPane.style.display = profiles ? '' : 'none';
                if (poiPane) poiPane.style.display = profiles ? 'none' : '';
                if (epheroControls) epheroControls.style.display = profiles ? '' : 'none';
                setTimeout(() => global.dispatchEvent(new Event('resize')), 50);
            };

            // Wire view-toggle buttons (.dm-view-btn[data-view]) scoped to the chromatogram panel.
            if (chromoPanel) {
                chromoPanel.addEventListener('click', function (e) {
                    const btn = e.target.closest('.dm-view-btn[data-view]');
                    if (!btn) return;
                    lastView = btn.dataset.view;
                    showView(lastView);
                });
                // A re-mount (a kind or theme switch) keeps the view: the readout tab when the new kind has one.
                if (lastView !== 'electropherogram') {
                    const again = chromoPanel.querySelector(`.dm-view-btn[data-view="${lastView}"]`)
                        || chromoPanel.querySelector('.dm-view-btn[data-view]:not([data-view="electropherogram"])');
                    if (again) showView(again.dataset.view);
                }

                // Wire axis mode-toggle buttons (.dm-mode-btn[data-mode]) scoped to the
                // chromatogram panel — Band Detail's bands/pseudo-gel buttons are excluded.
                chromoPanel.addEventListener('click', function (e) {
                    const btn = e.target.closest('.dm-mode-btn[data-mode]');
                    if (!btn) return;
                    const mode = btn.dataset.mode;
                    handle.setOptions({ xAxisMode: mode });
                    chromoPanel.querySelectorAll('.dm-mode-btn[data-mode]').forEach((b) => {
                        b.classList.toggle('active', b.dataset.mode === mode);
                    });
                });

                // A re-mount starts on the remembered axis.
                const axis = roster ? roster.options().xAxisMode : null;
                if (axis) {
                    chromoPanel.querySelectorAll('.dm-mode-btn[data-mode]').forEach((b) => {
                        b.classList.toggle('active', b.dataset.mode === axis);
                    });
                }
            }
        };

        // The controls inside the mounted root: now, and after every re-mount (a kind switch).
        const attachRoot = () => {
            const vizRoot = hostEl ? hostEl.querySelector('.ga-viz-root') : null;
            attachSplitter(vizRoot);
            attachExpand(vizRoot);
            attachToggles(vizRoot);
            updateSampleCount();
        };
        attachRoot();
        if (roster) {
            roster.onMount(() => attachRoot());
            roster.onChange(() => updateSampleCount());
        }

        // =====================================================================
        // MW Tolerance + Normalization mode → handle.setOptions(...)
        // =====================================================================
        const mwToleranceInput = document.getElementById('mw-tolerance');
        if (mwToleranceInput) {
            mwToleranceInput.addEventListener('change', (e) => {
                const val = parseInt(e.target.value, 10);
                if (!isNaN(val) && val >= 1 && val <= 20) {
                    handle.setOptions({ mwTolerance: val });
                }
            });
        }
        const normSelect = document.getElementById('normalization-mode');
        if (normSelect) {
            normSelect.addEventListener('change', function () {
                handle.setOptions({ normalizationMode: this.value });
            });
        }

        // =====================================================================
        // Export CSV (header button) — builds CSV via the component API client.
        // The handle does not expose export, so we read samples off the state
        // and reuse the same approach as the legacy export (delegated to a
        // lightweight client here).
        // =====================================================================
        const exportBtn = document.getElementById('export-btn');
        if (exportBtn) {
            exportBtn.addEventListener('click', async () => {
                const state = getState();
                const samples = state ? state.getSamples() : [];
                if (!samples.length) {
                    global.gaToast?.('No samples to export.', 'warning');
                    return;
                }
                try {
                    const ApiClass = global.SampleComparison?.Api;
                    const api = ApiClass ? new ApiClass({ csrfToken, apiUrls }) : null;
                    if (!api || !api.exportToCSV) {
                        global.gaToast?.('Export not available.', 'warning');
                        return;
                    }
                    const kind = roster ? roster.activeKind() : null;
                    const blob = await api.exportToCSV(samples, {
                        mwTolerance: state.mwTolerance || 5,
                        columns: kind ? kind.columns || [] : [],
                        kind: kind ? kind.label : '',
                    });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    const slug = kind ? `_${kind.label.replace(/[^A-Za-z0-9]+/g, '-').replace(/^-|-$/g, '')}` : '';
                    a.download = `sample_comparison${slug}_${new Date().toISOString().slice(0, 10)}.csv`;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    URL.revokeObjectURL(url);
                } catch (err) {
                    console.error('[ComparisonPageChrome] Export failed:', err);
                    global.gaToast?.('Export failed.', 'danger');
                }
            });
        }

        // =====================================================================
        // Sample Selector Wizard Modal (2-step: gel → lanes)
        // =====================================================================
        const wizardModal = {
            modal: document.getElementById('sample-selector-modal'),
            step1: document.getElementById('wizard-step-1'),
            step2: document.getElementById('wizard-step-2'),
            stepIndicator1: document.getElementById('step-indicator-1'),
            stepIndicator2: document.getElementById('step-indicator-2'),
            stepConnector: document.getElementById('step-connector'),
            gelGridContainer: document.getElementById('gel-grid-container'),
            laneList: document.getElementById('lane-list'),
            backBtn: document.getElementById('wizard-back-btn'),
            cancelBtn: document.getElementById('wizard-cancel-btn'),
            addBtn: document.getElementById('wizard-add-btn'),
            closeBtn: document.getElementById('modal-close-btn'),

            currentStep: 1,
            gels: [],
            selectedGel: null,
            selectedLanes: new Set(),
            isLoading: false,
            searchTimeout: null,
            currentPage: 1,
            hasMore: false,

            init() {
                if (!this.modal) return;
                this.setupEventListeners();
            },

            setupEventListeners() {
                document.getElementById('add-sample-btn')?.addEventListener('click', () => this.open());
                this.closeBtn?.addEventListener('click', () => this.close());
                this.cancelBtn?.addEventListener('click', () => this.close());
                this.modal?.addEventListener('click', (e) => {
                    if (e.target === this.modal) this.close();
                });
                this.backBtn?.addEventListener('click', () => this.goToStep1());
                this.addBtn?.addEventListener('click', () => this.addSelectedLanes());

                document.getElementById('gel-search')?.addEventListener('input', () => {
                    this.debounceSearch(() => this.loadGels(true));
                });
                document.getElementById('filter-gel-type')?.addEventListener('change', () => this.loadGels(true));
                document.getElementById('filter-date-range')?.addEventListener('change', () => this.loadGels(true));

                document.getElementById('lane-search')?.addEventListener('input', () => this.filterLanes());
                document.getElementById('filter-samples-only')?.addEventListener('change', () => this.filterLanes());
            },

            debounceSearch(callback, delay = 300) {
                if (this.searchTimeout) clearTimeout(this.searchTimeout);
                this.searchTimeout = setTimeout(callback, delay);
            },

            open() {
                this.modal.style.display = 'flex';
                this.goToStep1();
                this.loadGels(true);
            },

            close() {
                this.modal.style.display = 'none';
                this.selectedLanes.clear();
                this.selectedGel = null;
            },

            goToStep1() {
                this.currentStep = 1;
                this.step1.classList.add('active');
                this.step2.classList.remove('active');
                this.stepIndicator1.classList.add('active');
                this.stepIndicator1.classList.remove('completed');
                this.stepIndicator2.classList.remove('active');
                this.stepConnector.classList.remove('completed');
                this.backBtn.style.display = 'none';
                this.addBtn.style.display = 'none';
                this.selectedLanes.clear();
            },

            goToStep2(gel) {
                this.selectedGel = gel;
                this.currentStep = 2;
                this.step1.classList.remove('active');
                this.step2.classList.add('active');
                this.stepIndicator1.classList.remove('active');
                this.stepIndicator1.classList.add('completed');
                this.stepIndicator1.querySelector('.dm-step-number').innerHTML = '<i class="bi bi-check"></i>';
                this.stepIndicator2.classList.add('active');
                this.stepConnector.classList.add('completed');
                this.backBtn.style.display = 'flex';
                this.addBtn.style.display = 'flex';
                this.loadLanesForGel(gel);
                this.updatePreview(gel);
            },

            async loadGels(reset = false) {
                if (this.isLoading) return;
                if (reset) {
                    this.currentPage = 1;
                    this.gels = [];
                }
                this.isLoading = true;

                const params = new URLSearchParams();
                params.set('page', this.currentPage);
                params.set('page_size', 24);

                const search = document.getElementById('gel-search')?.value?.trim();
                if (search) params.set('search', search);

                const gelType = document.getElementById('filter-gel-type')?.value;
                if (gelType) params.set('gel_type', gelType);

                const dateRange = document.getElementById('filter-date-range')?.value;
                if (dateRange) {
                    const days = parseInt(dateRange);
                    const from = new Date();
                    from.setDate(from.getDate() - days);
                    params.set('date_from', from.toISOString().split('T')[0]);
                }

                if (reset) {
                    this.gelGridContainer.innerHTML = `
                        <div class="dm-gel-grid-loading">
                            <div class="dm-spinner"></div>
                            <span>Loading gel images...</span>
                        </div>
                    `;
                }

                try {
                    const response = await fetch(`${apiUrls.imagesWithDensitometry}?${params}`);
                    const data = await response.json();
                    this.gels = reset ? data.results : [...this.gels, ...data.results];
                    this.hasMore = !!data.next;
                    this.renderGelGrid();
                } catch (error) {
                    console.error('Error loading gels:', error);
                    this.gelGridContainer.innerHTML = `
                        <div class="dm-gel-grid-empty">
                            <i class="bi bi-exclamation-triangle"></i>
                            <span>Failed to load gel images</span>
                        </div>
                    `;
                } finally {
                    this.isLoading = false;
                }
            },

            renderGelGrid() {
                if (this.gels.length === 0) {
                    this.gelGridContainer.innerHTML = `
                        <div class="dm-gel-grid-empty">
                            <i class="bi bi-images"></i>
                            <span>No gel images found</span>
                            <p class="dm-text-muted">Try adjusting your filters</p>
                        </div>
                    `;
                    return;
                }

                let html = '<div class="dm-gel-grid">';
                this.gels.forEach((gel) => {
                    const analysis = gel.analysis || {};
                    const hasCalibration = analysis.has_calibration;
                    const mwRange = analysis.mw_range;
                    const mwRangeStr = mwRange && mwRange.min && mwRange.max
                        ? `${mwRange.min}-${mwRange.max} kDa`
                        : 'Not calibrated';

                    html += `
                        <div class="dm-gel-card" data-gel-id="${gel.id}">
                            <div class="dm-gel-thumbnail">
                                ${gel.thumbnail_url
                                    ? `<img src="${escapeHtml(gel.thumbnail_url)}" alt="${escapeHtml(gel.original_filename)}">`
                                    : '<div class="dm-placeholder-icon"><i class="bi bi-image"></i></div>'
                                }
                            </div>
                            <div class="dm-gel-info">
                                <div class="dm-gel-filename" title="${escapeHtml(gel.original_filename)}">${escapeHtml(gel.original_filename)}</div>
                                <div class="dm-gel-meta">
                                    <span class="dm-gel-type-badge">${escapeHtml(gel.gel_type_display || gel.gel_type)}</span>
                                    <span>${gel.uploaded_at ? new Date(gel.uploaded_at).toLocaleDateString() : '-'}</span>
                                </div>
                                <div class="dm-gel-stats">
                                    <span class="dm-gel-stat">
                                        <i class="bi bi-list-ol"></i> ${analysis.lane_count || 0} lanes
                                    </span>
                                    <span class="dm-gel-stat ${hasCalibration ? 'calibrated' : 'uncalibrated'}">
                                        <i class="bi bi-${hasCalibration ? 'check-circle' : 'exclamation-triangle'}"></i>
                                        ${hasCalibration ? mwRangeStr : 'No calibration'}
                                    </span>
                                </div>
                            </div>
                        </div>
                    `;
                });
                html += '</div>';

                if (this.hasMore) {
                    html += `<button class="dm-load-more" id="load-more-gels">Load more...</button>`;
                }

                this.gelGridContainer.innerHTML = html;

                this.gelGridContainer.querySelectorAll('.dm-gel-card').forEach((card) => {
                    card.addEventListener('click', () => {
                        const gelId = card.dataset.gelId;
                        const gel = this.gels.find((g) => g.id === gelId);
                        if (gel) this.goToStep2(gel);
                    });
                });

                document.getElementById('load-more-gels')?.addEventListener('click', () => {
                    this.currentPage++;
                    this.loadGels(false);
                });
            },

            updatePreview(gel) {
                const analysis = gel.analysis || {};
                document.getElementById('preview-gel-name').textContent = analysis.name || gel.original_filename;
                document.getElementById('preview-gel-info').textContent =
                    `${gel.gel_type_display || gel.gel_type} | ${analysis.lane_count || 0} lanes`;

                const imageContainer = document.getElementById('preview-gel-image');
                if (gel.thumbnail_url) {
                    imageContainer.innerHTML = `<img src="${escapeHtml(gel.thumbnail_url)}" alt="${escapeHtml(gel.original_filename)}">`;
                } else {
                    imageContainer.innerHTML = '<div class="dm-placeholder-icon"><i class="bi bi-image"></i></div>';
                }

                const mwRange = analysis.mw_range;
                const calibrationText = analysis.has_calibration && mwRange
                    ? `${mwRange.min}-${mwRange.max} kDa`
                    : 'Not calibrated';
                document.getElementById('preview-calibration').textContent = calibrationText;
            },

            async loadLanesForGel(gel) {
                const analysisId = gel.analysis?.id;
                if (!analysisId) {
                    this.laneList.innerHTML = '<div class="dm-text-muted">No analysis found for this gel.</div>';
                    return;
                }

                this.laneList.innerHTML = `
                    <div class="dm-gel-grid-loading">
                        <div class="dm-spinner"></div>
                        <span>Loading lanes...</span>
                    </div>
                `;

                try {
                    const response = await fetch(`/api/analyses/${analysisId}/data/`);
                    const data = await response.json();
                    if (data.lanes && data.lanes.length > 0) {
                        this.renderLaneList(data.lanes, gel.analysis);
                    } else {
                        this.laneList.innerHTML = '<div class="dm-text-muted">No lanes found in this analysis.</div>';
                    }
                } catch (error) {
                    console.error('Error loading lanes:', error);
                    this.laneList.innerHTML = '<div class="dm-text-muted">Failed to load lanes.</div>';
                }
            },

            renderLaneList(lanes) {
                let html = '';
                lanes.forEach((lane) => {
                    const isLadder = lane.lane_type === 'LADDER';
                    const hasDensitometry = lane.has_densitometry !== false;

                    let laneName = `Lane ${lane.lane_number}`;
                    if (lane.sample_name) {
                        laneName += `: ${lane.sample_name}`;
                    }

                    const bandCount = lane.bands?.length || 0;

                    html += `
                        <div class="dm-lane-option"
                             data-lane-id="${lane.id}"
                             data-lane-type="${escapeHtml(lane.lane_type)}"
                             data-lane-name="${escapeHtml(laneName.toLowerCase())}">
                            <input type="checkbox" class="dm-lane-checkbox" data-lane-id="${lane.id}">
                            <div class="dm-lane-details">
                                <div class="dm-lane-name">${escapeHtml(laneName)}</div>
                                <div class="dm-lane-meta-row">
                                    <span>${bandCount} band${bandCount !== 1 ? 's' : ''}</span>
                                    ${isLadder ? '<span class="dm-lane-tag ladder">Ladder</span>' : '<span class="dm-lane-tag">Sample</span>'}
                                    ${hasDensitometry
                                        ? '<span class="dm-lane-status calibrated"><i class="bi bi-check-circle"></i> Ready</span>'
                                        : '<span class="dm-lane-status uncalibrated"><i class="bi bi-exclamation-triangle"></i> No data</span>'
                                    }
                                </div>
                            </div>
                        </div>
                    `;
                });

                this.laneList.innerHTML = html;

                this.laneList.querySelectorAll('.dm-lane-option').forEach((option) => {
                    option.addEventListener('click', (e) => {
                        if (e.target.type === 'checkbox') return;
                        const checkbox = option.querySelector('.dm-lane-checkbox');
                        checkbox.checked = !checkbox.checked;
                        this.toggleLaneSelection(parseInt(option.dataset.laneId), checkbox.checked);
                    });
                    option.querySelector('.dm-lane-checkbox').addEventListener('change', (e) => {
                        this.toggleLaneSelection(parseInt(option.dataset.laneId), e.target.checked);
                    });
                });

                this.updateSelectionCount();
            },

            toggleLaneSelection(laneId, selected) {
                if (selected) {
                    this.selectedLanes.add(laneId);
                } else {
                    this.selectedLanes.delete(laneId);
                }
                const option = this.laneList.querySelector(`[data-lane-id="${laneId}"]`);
                if (option) option.classList.toggle('selected', selected);
                this.updateSelectionCount();
            },

            updateSelectionCount() {
                const countEl = document.getElementById('selection-count');
                if (countEl) countEl.textContent = this.selectedLanes.size;
                this.addBtn.disabled = this.selectedLanes.size === 0;
            },

            filterLanes() {
                const search = document.getElementById('lane-search')?.value?.toLowerCase().trim() || '';
                const samplesOnly = document.getElementById('filter-samples-only')?.checked;
                this.laneList.querySelectorAll('.dm-lane-option').forEach((option) => {
                    const laneName = option.dataset.laneName || '';
                    const laneType = option.dataset.laneType || '';
                    const matchSearch = !search || laneName.includes(search);
                    const matchType = !samplesOnly || laneType !== 'LADDER';
                    option.style.display = matchSearch && matchType ? '' : 'none';
                });
            },

            async addSelectedLanes() {
                if (this.selectedLanes.size === 0) return;

                this.addBtn.disabled = true;
                this.addBtn.innerHTML = '<span class="dm-spinner-sm me-1"></span> Adding...';

                let addedCount = 0;
                for (const laneId of this.selectedLanes) {
                    try {
                        const url = apiUrls.laneData.replace('{laneId}', laneId);
                        const response = await fetch(url, { headers: { 'X-CSRFToken': csrfToken } });
                        if (response.ok) {
                            const data = await response.json();
                            // Drive the component through the handle.
                            const added = handle.addSample(data);
                            if (added !== false) addedCount++;
                        }
                    } catch (error) {
                        console.error(`Error adding lane ${laneId}:`, error);
                    }
                }

                this.addBtn.innerHTML = '<i class="bi bi-plus-circle me-1"></i> Add Selected';
                this.addBtn.disabled = false;
                if (addedCount > 0) this.close();
            },
        };
        wizardModal.init();

        // =====================================================================
        // Save Comparison Modal
        // =====================================================================
        const normSelectRef = normSelect;
        const mwToleranceRef = mwToleranceInput;
        const saveModal = {
            overlay: document.getElementById('save-comparison-modal'),
            nameInput: document.getElementById('save-comp-name'),
            descInput: document.getElementById('save-comp-description'),
            publicCheckbox: document.getElementById('save-comp-public'),
            lanesSummary: document.getElementById('save-comp-lanes-summary'),
            errorEl: document.getElementById('save-comp-error'),
            submitBtn: document.getElementById('save-comp-submit'),
            submitText: document.getElementById('save-comp-submit-text'),
            saveAsLink: document.getElementById('save-as-link'),
            saveAsBtn: document.getElementById('save-comp-save-as'),
            titleEl: document.getElementById('save-modal-title'),
            saveBtnText: document.getElementById('save-btn-text'),
            currentComparisonId: cfg.savedComparisonId || null,
            savedComparison: cfg.savedComparison || null,

            open() {
                // Every kind's lanes (the roster), not only the assay shown.
                const state = getState();
                const labels = roster ? roster.labels() : (state ? state.getSamples() : []).map((s) => s.label);
                if (labels.length === 0) {
                    global.gaToast?.('Add at least one sample before saving.', 'warning');
                    return;
                }

                this.lanesSummary.textContent =
                    `Lanes: ${labels.join(', ')} (${labels.length} lane${labels.length !== 1 ? 's' : ''})`;

                if (this.savedComparison && this.currentComparisonId) {
                    this.nameInput.value = this.savedComparison.name || '';
                    this.descInput.value = this.savedComparison.description || '';
                    this.publicCheckbox.checked = this.savedComparison.is_public || false;
                    this.titleEl.textContent = 'Update Comparison';
                    this.submitText.textContent = 'Update';
                    this.saveAsLink.style.display = 'block';
                    // A saved comparison over the page's cap loads its first lanes (views/comparison.py,
                    // the `truncated` flag set at load): an Update would drop the others without a word.
                    // Say it, and keep only "Save as new copy". Never decided from the live roster: lanes
                    // added or removed since would hide the loss or refuse a legitimate Update.
                    this.truncated = !!this.savedComparison.truncated;
                    this.submitBtn.disabled = this.truncated;
                    if (this.truncated) {
                        this.showError(`This comparison holds ${this.savedComparison.lane_count} lanes and the page ` +
                            'loads the first 20: Update would drop the others. Use "Save as new copy" to keep these.');
                    }
                } else {
                    this.nameInput.value = '';
                    this.descInput.value = '';
                    this.publicCheckbox.checked = false;
                    this.titleEl.textContent = 'Save Comparison';
                    this.submitText.textContent = 'Save';
                    this.saveAsLink.style.display = 'none';
                    this.truncated = false;
                    this.submitBtn.disabled = false;
                }

                if (!this.truncated) this.errorEl.style.display = 'none';
                this.overlay.style.display = 'flex';
                setTimeout(() => this.nameInput.focus(), 100);
            },

            close() {
                this.overlay.style.display = 'none';
            },

            async submit(saveAsNew = false) {
                const name = this.nameInput.value.trim();
                if (!name) {
                    this.showError('Please enter a name.');
                    this.nameInput.focus();
                    return;
                }

                if (this.truncated && !saveAsNew) return;
                const state = getState() || {};
                const viewOptions = roster ? roster.options() : {};
                const laneIds = roster
                    ? roster.laneIds()
                    : (state.getSamples ? state.getSamples() : []).map((s) => s.lane?.id).filter(Boolean);
                if (laneIds.length === 0) {
                    this.showError('No lanes to save.');
                    return;
                }

                const payload = {
                    name,
                    description: this.descInput.value.trim(),
                    is_public: this.publicCheckbox.checked,
                    lane_ids: laneIds,
                    view_settings: {
                        normalization_mode: viewOptions.normalizationMode || state.normalizationMode || 'raw',
                        x_axis_mode: viewOptions.xAxisMode || state.xAxisMode || 'mw',
                        poi_only: viewOptions.poiOnlyMode ?? state.poiOnlyMode ?? false,
                        mw_tolerance: viewOptions.mwTolerance || state.mwTolerance || 5,
                    },
                };

                this.submitBtn.disabled = true;
                this.submitText.textContent = 'Saving...';

                try {
                    let url, method;
                    if (this.currentComparisonId && !saveAsNew) {
                        url = urls.savedComparisons + this.currentComparisonId + '/';
                        method = 'PUT';
                    } else {
                        url = urls.savedComparisons;
                        method = 'POST';
                    }

                    const response = await fetch(url, {
                        method,
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
                        body: JSON.stringify(payload),
                    });
                    const data = await response.json();
                    if (!response.ok) {
                        this.showError(data.error || 'Failed to save.');
                        return;
                    }

                    this.currentComparisonId = data.id;
                    this.savedComparison = {
                        id: data.id,
                        name: data.name,
                        description: data.description,
                        is_public: data.is_public,
                        view_settings: data.view_settings,
                        lane_count: data.lane_count,
                    };
                    this.truncated = false;

                    const newUrl = new URL(global.location);
                    newUrl.searchParams.delete('lanes');
                    newUrl.searchParams.set('comparison', data.id);
                    history.replaceState(null, '', newUrl.toString());

                    this.saveBtnText.textContent = 'Saved';
                    this.close();
                } catch (err) {
                    this.showError('Network error. Please try again.');
                    console.error('Save comparison error:', err);
                } finally {
                    this.submitBtn.disabled = false;
                    this.submitText.textContent = this.currentComparisonId ? 'Update' : 'Save';
                }
            },

            showError(msg) {
                this.errorEl.textContent = msg;
                this.errorEl.style.display = 'block';
            },
        };

        document.getElementById('save-comparison-btn')?.addEventListener('click', () => saveModal.open());
        document.getElementById('save-modal-close')?.addEventListener('click', () => saveModal.close());
        document.getElementById('save-comp-cancel')?.addEventListener('click', () => saveModal.close());
        document.getElementById('save-comp-submit')?.addEventListener('click', () => saveModal.submit(false));
        if (saveModal.saveAsBtn) {
            saveModal.saveAsBtn.addEventListener('click', () => saveModal.submit(true));
        }
        saveModal.overlay?.addEventListener('click', function (e) {
            if (e.target === this) saveModal.close();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && saveModal.overlay && saveModal.overlay.style.display === 'flex') {
                saveModal.close();
            }
        });

        // Apply view settings from a loaded saved comparison.
        if (saveModal.savedComparison && saveModal.savedComparison.view_settings) {
            const settings = saveModal.savedComparison.view_settings;
            const opts = {};
            if (settings.normalization_mode && settings.normalization_mode !== 'raw') {
                opts.normalizationMode = settings.normalization_mode;
                if (normSelectRef) normSelectRef.value = settings.normalization_mode;
            }
            if (settings.x_axis_mode) {
                opts.xAxisMode = settings.x_axis_mode;
                // Scope to chromoPanel so Band Detail's bands/pseudo-gel buttons are not touched.
                const rootNow = hostEl ? hostEl.querySelector('.ga-viz-root') : null;
                const chromoPanelForRestore = rootNow
                    ? (rootNow.querySelector('.dm-panel-chromatogram')
                        || rootNow.querySelector('[data-ga-panel="chromatogram"]'))
                    : null;
                if (chromoPanelForRestore && settings.x_axis_mode) {
                    chromoPanelForRestore.querySelectorAll('.dm-mode-btn[data-mode]').forEach((b) => {
                        b.classList.toggle('active', b.dataset.mode === settings.x_axis_mode);
                    });
                }
            }
            if (settings.poi_only) {
                opts.poiOnlyMode = true;
                const box = hostEl ? hostEl.querySelector('[data-ga-control="poi-only-mode"]') : null;
                if (box) box.checked = true;
            }
            if (settings.mw_tolerance) {
                opts.mwTolerance = settings.mw_tolerance;
                if (mwToleranceRef) mwToleranceRef.value = settings.mw_tolerance;
            }
            if (Object.keys(opts).length) handle.setOptions(opts);
        }

        // =====================================================================
        // Generate Report (Modal)
        // =====================================================================
        const reportBtn = document.getElementById('generate-report-btn');
        const reportModal = {
            overlay: document.getElementById('report-config-modal'),
            generateBtn: document.getElementById('report-modal-generate'),
            generateText: document.getElementById('report-generate-text'),
            formatNote: document.getElementById('report-format-note'),

            open() {
                this.overlay.querySelectorAll('input[data-group-toggle]').forEach((cb) => { cb.checked = true; });
                this.overlay.querySelectorAll('input[data-section-key]').forEach((cb) => { cb.checked = true; });
                document.getElementById('report-band-overlay').checked = true;
                // Reset gel-image variant toggles to spec D3 default: FULL checked, others unchecked.
                this.overlay.querySelectorAll('input[data-gel-variant]').forEach((cb) => {
                    cb.checked = (cb.dataset.gelVariant === 'FULL');
                });
                const docxRadio = this.overlay.querySelector('input[value="docx"]');
                if (docxRadio) docxRadio.checked = true;
                this.onFormatChange();
                this.updateAllGroups();
                this.overlay.style.display = 'flex';
            },

            close() {
                this.overlay.style.display = 'none';
            },

            getFormat() {
                const checked = this.overlay.querySelector('input[name="report-format"]:checked');
                return checked ? checked.value : 'docx';
            },

            getSections() {
                const sections = [];
                this.overlay.querySelectorAll('input[data-section-key]:checked').forEach((cb) => {
                    if (!cb.disabled) sections.push(cb.dataset.sectionKey);
                });
                return sections;
            },

            onGroupToggle(groupName) {
                const toggle = this.overlay.querySelector(`input[data-group-toggle="${groupName}"]`);
                const body = this.overlay.querySelector(`[data-group-body="${groupName}"]`);
                if (!toggle || !body) return;
                const enabled = toggle.checked;

                body.querySelectorAll('input[data-section-key]').forEach((cb) => {
                    if (enabled) {
                        const opt = cb.closest('.dm-report-section-option');
                        const isFormatDisabled = opt && opt.classList.contains('format-disabled');
                        if (!isFormatDisabled) {
                            cb.disabled = false;
                            cb.checked = true;
                        }
                    } else {
                        cb.disabled = true;
                        cb.checked = false;
                    }
                });

                const bandOverlay = body.querySelector('#report-band-overlay');
                if (bandOverlay) {
                    bandOverlay.disabled = !enabled;
                    if (!enabled) bandOverlay.checked = false;
                }

                // Handle the gel-image variant sub-options (LANES_ONLY / KEY_BANDS / FULL).
                // When the group is disabled they go disabled+unchecked; when re-enabled,
                // updateDependencies() (driven by the gel_images checkbox) restores them.
                // We only need to force-clear them here on disable.
                body.querySelectorAll('input[data-gel-variant]').forEach((cb) => {
                    cb.disabled = !enabled;
                    if (!enabled) cb.checked = false;
                });

                body.classList.toggle('dm-report-group-disabled', !enabled);
                const chevron = this.overlay.querySelector(`[data-group="${groupName}"] .dm-report-group-chevron`);
                if (chevron) chevron.classList.toggle('collapsed', !enabled);

                this.updateDependencies();
            },

            updateDependencies() {
                this.overlay.querySelectorAll('[data-depends-on]').forEach((opt) => {
                    const dependsOn = opt.dataset.dependsOn;
                    const parentCb = this.overlay.querySelector(`input[data-section-key="${dependsOn}"]`);
                    const childCb = opt.querySelector('input');
                    if (!parentCb || !childCb) return;
                    const parentEnabled = parentCb.checked && !parentCb.disabled;
                    if (!parentEnabled) {
                        childCb.disabled = true;
                        childCb.checked = false;
                        opt.classList.add('disabled-section');
                    } else {
                        childCb.disabled = false;
                        opt.classList.remove('disabled-section');
                    }
                });
            },

            syncGroupFromChildren(groupName) {
                const toggle = this.overlay.querySelector(`input[data-group-toggle="${groupName}"]`);
                const body = this.overlay.querySelector(`[data-group-body="${groupName}"]`);
                if (!toggle || !body) return;
                const children = body.querySelectorAll('input[data-section-key]');
                if (children.length === 0) return;
                const checkedCount = Array.from(children).filter((cb) => cb.checked && !cb.disabled).length;
                const enabledCount = Array.from(children).filter((cb) => !cb.disabled).length;
                if (checkedCount === 0) {
                    toggle.checked = false;
                    toggle.indeterminate = false;
                } else if (checkedCount < enabledCount) {
                    toggle.checked = true;
                    toggle.indeterminate = true;
                } else {
                    toggle.checked = true;
                    toggle.indeterminate = false;
                }
            },

            updateAllGroups() {
                ['summary', 'gel_visuals', 'detailed'].forEach((g) => {
                    this.onGroupToggle(g);
                    this.syncGroupFromChildren(g);
                });
                this.updateDependencies();
            },

            onFormatChange() {
                const fmt = this.getFormat();
                const isExcel = fmt === 'xlsx';

                this.overlay.querySelectorAll('.dm-report-section-option[data-image-only]').forEach((opt) => {
                    const cb = opt.querySelector('input');
                    if (isExcel) {
                        cb.checked = false;
                        cb.disabled = true;
                        opt.classList.add('disabled-section', 'format-disabled');
                    } else {
                        const parentGroup = opt.dataset.parentGroup;
                        const groupToggle = parentGroup
                            ? this.overlay.querySelector(`input[data-group-toggle="${parentGroup}"]`)
                            : null;
                        const groupEnabled = !groupToggle || groupToggle.checked;
                        if (groupEnabled) cb.disabled = false;
                        opt.classList.remove('disabled-section', 'format-disabled');
                    }
                });

                const gelGroup = this.overlay.querySelector('[data-group="gel_visuals"]');
                if (gelGroup) {
                    const groupToggle = gelGroup.querySelector('input[data-group-toggle]');
                    if (isExcel) {
                        gelGroup.classList.add('disabled-section');
                        if (groupToggle) {
                            groupToggle.checked = false;
                            groupToggle.disabled = true;
                        }
                        this.onGroupToggle('gel_visuals');
                    } else {
                        gelGroup.classList.remove('disabled-section');
                        if (groupToggle) {
                            groupToggle.disabled = false;
                            groupToggle.checked = true;
                        }
                        this.onGroupToggle('gel_visuals');
                    }
                }

                this.formatNote.style.display = isExcel ? 'block' : 'none';
                this.updateDependencies();
            },

            async generate() {
                const comparisonId = saveModal.currentComparisonId;
                if (!comparisonId) {
                    global.gaToast?.('Please save the comparison first.', 'warning');
                    return;
                }

                const format = this.getFormat();
                const sections = this.getSections();
                const bandOverlayCb = document.getElementById('report-band-overlay');
                const bandOverlay = bandOverlayCb ? (bandOverlayCb.checked && !bandOverlayCb.disabled) : true;

                // Collect checked gel-image variant toggles (spec D3 — one PPTX gel
                // slide per selected variant, per compared analysis). Backend defaults
                // to ["FULL"] when the list is absent/empty, so send ["FULL"] if none.
                const gelVariants = [];
                this.overlay.querySelectorAll('input[data-gel-variant]:checked').forEach((cb) => {
                    if (!cb.disabled) gelVariants.push(cb.dataset.gelVariant);
                });
                const gel_variants = gelVariants.length ? gelVariants : ['FULL'];

                if (sections.length === 0) {
                    global.gaToast?.('Please select at least one section.', 'warning');
                    return;
                }

                this.generateBtn.disabled = true;
                this.generateText.textContent = 'Generating...';

                try {
                    const reportUrl = urls.generateReportTemplate
                        .replace('00000000-0000-0000-0000-000000000000', comparisonId);

                    const response = await fetch(reportUrl, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
                        body: JSON.stringify({ format, sections, band_overlay: bandOverlay, gel_variants }),
                    });

                    if (!response.ok) {
                        const err = await response.json().catch(() => ({}));
                        throw new Error(err.error || `Server error (${response.status})`);
                    }

                    const blob = await response.blob();
                    const disposition = response.headers.get('Content-Disposition') || '';
                    const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
                    const fallbackExt = { docx: '.docx', xlsx: '.xlsx', pptx: '.pptx' }[format] || '.docx';
                    const filename = filenameMatch ? filenameMatch[1] : `comparison_report${fallbackExt}`;

                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    URL.revokeObjectURL(url);

                    this.close();

                    const label = reportBtn.querySelector('.dm-btn-label');
                    if (label) {
                        label.textContent = 'Downloaded';
                        setTimeout(() => { label.textContent = 'Report'; }, 3000);
                    }
                } catch (err) {
                    console.error('[Report] Generation failed:', err);
                    global.gaToast?.('Report generation failed: ' + err.message, 'danger');
                } finally {
                    this.generateBtn.disabled = false;
                    this.generateText.textContent = 'Generate Report';
                }
            },
        };

        if (reportBtn) {
            const updateReportBtnState = () => {
                reportBtn.disabled = !saveModal.currentComparisonId;
            };
            const saveBtnText = document.getElementById('save-btn-text');
            if (saveBtnText) {
                const observer = new MutationObserver(() => updateReportBtnState());
                observer.observe(saveBtnText, { childList: true, characterData: true, subtree: true });
            }

            reportBtn.addEventListener('click', () => {
                if (reportBtn.disabled) return;
                if (!saveModal.currentComparisonId) {
                    global.gaToast?.('Please save the comparison first before generating a report.', 'warning');
                    return;
                }
                reportModal.open();
            });

            document.getElementById('report-modal-close')?.addEventListener('click', () => reportModal.close());
            document.getElementById('report-modal-cancel')?.addEventListener('click', () => reportModal.close());
            reportModal.overlay.addEventListener('click', (e) => {
                if (e.target === reportModal.overlay) reportModal.close();
            });
            document.getElementById('report-modal-generate')?.addEventListener('click', () => reportModal.generate());

            reportModal.overlay.querySelectorAll('input[name="report-format"]').forEach((radio) => {
                radio.addEventListener('change', () => reportModal.onFormatChange());
            });
            reportModal.overlay.querySelectorAll('input[data-group-toggle]').forEach((toggle) => {
                toggle.addEventListener('change', () => reportModal.onGroupToggle(toggle.dataset.groupToggle));
            });
            reportModal.overlay.querySelectorAll('.dm-report-child-option input[data-section-key]').forEach((cb) => {
                cb.addEventListener('change', () => {
                    const parentGroup = cb.closest('[data-parent-group]')?.dataset.parentGroup;
                    if (parentGroup) reportModal.syncGroupFromChildren(parentGroup);
                    reportModal.updateDependencies();
                });
            });

            document.getElementById('report-select-all')?.addEventListener('click', (e) => {
                e.preventDefault();
                reportModal.overlay.querySelectorAll('input[data-group-toggle]').forEach((cb) => {
                    if (!cb.disabled) cb.checked = true;
                });
                ['summary', 'gel_visuals', 'detailed'].forEach((g) => reportModal.onGroupToggle(g));
                reportModal.overlay.querySelectorAll('input[data-section-key]').forEach((cb) => {
                    if (!cb.disabled) cb.checked = true;
                });
                const bandCb = document.getElementById('report-band-overlay');
                if (bandCb && !bandCb.disabled) bandCb.checked = true;
                // Restore the gel-image variant default (FULL checked, others unchecked).
                reportModal.overlay.querySelectorAll('input[data-gel-variant]').forEach((cb) => {
                    if (!cb.disabled) cb.checked = (cb.dataset.gelVariant === 'FULL');
                });
                reportModal.overlay.querySelectorAll('.dm-report-section-option:not(.dm-report-child-option) input[data-section-key]').forEach((cb) => {
                    if (!cb.disabled) cb.checked = true;
                });
                reportModal.updateDependencies();
            });
            document.getElementById('report-select-none')?.addEventListener('click', (e) => {
                e.preventDefault();
                reportModal.overlay.querySelectorAll('input[data-group-toggle]').forEach((cb) => {
                    if (!cb.disabled) {
                        cb.checked = false;
                        cb.indeterminate = false;
                    }
                });
                ['summary', 'gel_visuals', 'detailed'].forEach((g) => reportModal.onGroupToggle(g));
                reportModal.overlay.querySelectorAll('input[data-section-key]').forEach((cb) => {
                    if (!cb.disabled) cb.checked = false;
                });
                const bandCb = document.getElementById('report-band-overlay');
                if (bandCb) bandCb.checked = false;
                reportModal.overlay.querySelectorAll('input[data-gel-variant]').forEach((cb) => {
                    cb.checked = false;
                });
                reportModal.updateDependencies();
            });

            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && reportModal.overlay.style.display === 'flex') {
                    reportModal.close();
                }
            });
        }

        // Initial sample count sync.
        updateSampleCount();

        // Expose for debugging.
        const api = { handle, wizardModal, saveModal, reportModal, magnifier, panelSplitter };
        global.sampleComparisonChrome = api;
        return api;
    }

    global.GelAnalyzer = global.GelAnalyzer || {};
    global.GelAnalyzer.SampleComparison = global.GelAnalyzer.SampleComparison || {};
    global.GelAnalyzer.SampleComparison.initPageChrome = initPageChrome;

})(window);
