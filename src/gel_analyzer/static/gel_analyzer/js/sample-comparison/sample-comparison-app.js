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
     * PanelMagnifier Class
     *
     * Handles expanding panels to fullscreen modal view.
     * Moves panel content to modal (preserving event handlers) and back on close.
     */
    class PanelMagnifier {
        constructor() {
            this.activePanel = null;
            this.activePanelContent = null;
            this.modalOverlay = null;
            this.modalTitle = null;
            this.modalContent = null;

            this._initElements();
            this._setupEventHandlers();
        }

        _initElements() {
            this.modalOverlay = document.getElementById('panel-magnify-overlay');
            this.modalTitle = document.getElementById('magnify-title');
            this.modalContent = document.getElementById('magnify-content');
            this.closeBtn = document.getElementById('magnify-close');
        }

        _setupEventHandlers() {
            // Close button
            if (this.closeBtn) {
                this.closeBtn.addEventListener('click', () => this.collapse());
            }

            // Backdrop click
            if (this.modalOverlay) {
                this.modalOverlay.addEventListener('click', (e) => {
                    if (e.target === this.modalOverlay) {
                        this.collapse();
                    }
                });
            }

            // ESC key
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.activePanel) {
                    this.collapse();
                }
            });
        }

        expand(panelElement) {
            if (!panelElement || !this.modalOverlay || !this.modalContent) {
                console.warn('[PanelMagnifier] Missing panel or modal elements');
                return;
            }

            // Already expanded?
            if (this.activePanel) {
                this.collapse();
            }

            // Get panel content and title
            const content = panelElement.querySelector('.dm-panel-content');
            const titleEl = panelElement.querySelector('.dm-panel-title');
            const title = titleEl?.textContent?.trim() || 'Panel View';

            if (!content) {
                console.warn('[PanelMagnifier] Panel has no .dm-panel-content');
                return;
            }

            // Store references
            this.activePanel = panelElement;
            this.activePanelContent = content;

            // Update modal title
            if (this.modalTitle) {
                this.modalTitle.textContent = title;
            }

            // Move content to modal
            this.modalContent.appendChild(content);

            // Mark panel as expanded
            panelElement.classList.add('dm-panel-expanded');

            // Show modal
            this.modalOverlay.classList.add('active');

            // Trigger resize for D3/canvas components
            setTimeout(() => {
                window.dispatchEvent(new Event('resize'));
            }, 50);

            console.log('[PanelMagnifier] Expanded:', panelElement.id);
        }

        collapse() {
            if (!this.activePanel || !this.activePanelContent) {
                return;
            }

            // Move content back to original panel
            this.activePanel.appendChild(this.activePanelContent);

            // Remove expanded state
            this.activePanel.classList.remove('dm-panel-expanded');

            // Hide modal
            if (this.modalOverlay) {
                this.modalOverlay.classList.remove('active');
            }

            const panelId = this.activePanel.id;

            // Clear references
            this.activePanel = null;
            this.activePanelContent = null;

            // Trigger resize for D3/canvas components
            setTimeout(() => {
                window.dispatchEvent(new Event('resize'));
            }, 50);

            console.log('[PanelMagnifier] Collapsed:', panelId);
        }

        isExpanded() {
            return this.activePanel !== null;
        }
    }

    /**
     * SampleComparisonApp Class
     */
    class SampleComparisonApp {
        constructor(options) {
            this.options = options;

            // Initialize core dependencies
            this.eventBus = new EventBus();
            this.state = new ComparisonState(this.eventBus);
            this.api = new ComparisonApi({
                csrfToken: options.csrfToken,
                apiUrls: options.apiUrls,
            });

            // Panels
            this.panels = {};

            // DOM references
            this.container = options.container || document.getElementById('sample-comparison-app');

            // Loading state
            this.isLoading = false;

            // Panel magnifier for fullscreen expansion
            this.magnifier = null;
        }

        async init() {
            if (!this.container) {
                console.error('[SampleComparisonApp] Container not found');
                return;
            }

            console.log('[SampleComparisonApp] Initializing...');

            this._initPanels();
            this._initMagnifier();
            this._setupEventHandlers();
            this._setupControls();
            await this._loadInitialData();

            console.log('[SampleComparisonApp] Initialized with', this.state.samples.size, 'samples');
        }

        _initMagnifier() {
            this.magnifier = new PanelMagnifier();

            // Wire up expand buttons for all panels
            document.querySelectorAll('.dm-panel-expand-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const panelId = btn.dataset.panel;
                    const panel = document.getElementById(panelId);
                    if (panel) {
                        this.magnifier.expand(panel);
                    }
                });
            });

            console.log('[SampleComparisonApp] Magnifier initialized');
        }

        _initPanels() {
            // Get panel classes from namespace
            const SampleCardsPanel = Panels.SampleCards;
            const GelOverviewPanel = Panels.GelOverview;
            const ComparisonChromatogramPanel = Panels.Chromatogram;
            const BandDetailPanel = Panels.BandDetail;
            const ComparisonResultsTablePanel = Panels.ResultsTable;

            // Sample cards panel
            if (SampleCardsPanel) {
                this.panels.sampleCards = new SampleCardsPanel({
                    container: document.getElementById('samples-container'),
                    eventBus: this.eventBus,
                    state: this.state,
                    app: this,
                });
            }

            // Gel Overview panel (with canvas)
            if (GelOverviewPanel) {
                this.panels.gelOverview = new GelOverviewPanel({
                    container: document.getElementById('gel-overview-panel'),
                    eventBus: this.eventBus,
                    state: this.state,
                });
            }

            // Chromatogram comparison panel (D3.js multi-profile)
            if (ComparisonChromatogramPanel) {
                this.panels.chromatogram = new ComparisonChromatogramPanel({
                    container: document.getElementById('chromatogram-panel'),
                    eventBus: this.eventBus,
                    state: this.state,
                });
            }

            // Band Detail panel with digital lane
            if (BandDetailPanel) {
                this.panels.bandDetail = new BandDetailPanel({
                    container: document.getElementById('band-zoom-panel'),
                    eventBus: this.eventBus,
                    state: this.state,
                });
            }

            // Results table panel
            if (ComparisonResultsTablePanel) {
                this.panels.resultsTable = new ComparisonResultsTablePanel({
                    container: document.getElementById('results-panel'),
                    eventBus: this.eventBus,
                    state: this.state,
                });
            }

            // POI Purity panel
            const PoiPurityPanel = Panels.PoiPurity;
            if (PoiPurityPanel) {
                this.panels.poiPurity = new PoiPurityPanel({
                    container: document.getElementById('poi-purity-container'),
                    eventBus: this.eventBus,
                    state: this.state,
                });
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
                        console.warn('[SampleComparisonApp] Failed to load profile:', e);
                    }
                }
            });

        }

        _setupControls() {
            // Add sample button
            const addBtn = document.getElementById('add-sample-btn');
            if (addBtn) {
                addBtn.addEventListener('click', () => this._showSampleSelector());
            }

            // Export button
            const exportBtn = document.getElementById('export-btn');
            if (exportBtn) {
                exportBtn.addEventListener('click', () => this._exportCSV());
            }

            // POI-only mode checkbox
            const poiOnlyCheckbox = document.getElementById('poi-only-mode');
            if (poiOnlyCheckbox) {
                poiOnlyCheckbox.addEventListener('change', (e) => {
                    this.state.setPoiOnlyMode(e.target.checked);
                });
            }

            // Sample selector modal
            const modalCloseBtn = document.getElementById('modal-close-btn');
            if (modalCloseBtn) {
                modalCloseBtn.addEventListener('click', () => this._hideSampleSelector());
            }

            const modalOverlay = document.getElementById('sample-selector-modal');
            if (modalOverlay) {
                modalOverlay.addEventListener('click', (e) => {
                    if (e.target === modalOverlay) {
                        this._hideSampleSelector();
                    }
                });
            }

            const searchInput = document.getElementById('sample-search');
            if (searchInput) {
                searchInput.addEventListener('input', (e) => {
                    this._filterAvailableSamples(e.target.value);
                });
            }

            const sampleList = document.getElementById('available-samples');
            if (sampleList) {
                sampleList.addEventListener('click', (e) => {
                    const option = e.target.closest('.dm-sample-option');
                    if (option) {
                        const sampleId = option.dataset.sampleId;
                        this._addSampleById(sampleId);
                        this._hideSampleSelector();
                    }
                });
            }
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
                        console.warn('[SampleComparisonApp] Failed to load profile for lane', sampleData.lane.id);
                    }
                }
            }

            this.eventBus.emit(ComparisonEvents.DATA_LOADED, {
                samples: this.state.getSamples(),
            });
        }

        async addSample(sampleId) {
            if (!this.state.canAddMore()) {
                this._showMessage('Maximum 4 samples allowed', 'warning');
                return;
            }

            this._setLoading(true);

            try {
                const data = await this.api.getSampleDensitometry(sampleId);
                const success = this.state.addSample(data);

                if (!success) {
                    this._showMessage('Sample already added or max reached', 'warning');
                } else {
                    if (data.profile && data.lane?.id) {
                        this.state.setProfile(data.lane.id, data.profile);
                    }
                }
            } catch (e) {
                console.error('[SampleComparisonApp] Failed to add sample:', e);
                this._showMessage(e.message || 'Failed to load sample', 'error');
            } finally {
                this._setLoading(false);
            }
        }

        async _addSampleById(sampleId) {
            await this.addSample(sampleId);
        }

        removeSample(sampleId) {
            this.state.removeSample(sampleId);
        }

        _showSampleSelector() {
            const modal = document.getElementById('sample-selector-modal');
            if (modal) {
                modal.style.display = 'flex';
            }
        }

        _hideSampleSelector() {
            const modal = document.getElementById('sample-selector-modal');
            if (modal) {
                modal.style.display = 'none';
            }
        }

        _filterAvailableSamples(query) {
            const list = document.getElementById('available-samples');
            if (!list) return;

            const options = list.querySelectorAll('.dm-sample-option');
            const lowerQuery = query.toLowerCase();

            options.forEach(option => {
                const text = option.textContent.toLowerCase();
                option.style.display = text.includes(lowerQuery) ? '' : 'none';
            });
        }

        async _exportCSV() {
            const samples = this.state.getSamples();
            if (samples.length === 0) {
                this._showMessage('No samples to export', 'warning');
                return;
            }

            try {
                const blob = await this.api.exportToCSV(samples);

                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `sample_comparison_${new Date().toISOString().slice(0, 10)}.csv`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);

                this._showMessage('Export successful', 'success');
            } catch (e) {
                console.error('[SampleComparisonApp] Export failed:', e);
                // Was 'Export failed' generic — surface the actual cause
                // so a 500 / network / permission error reads as such.
                this._showMessage(`❌ Export failed: ${(e && e.message) || e}`, 'error');
            }
        }

        _setLoading(loading) {
            this.isLoading = loading;
        }

        _showMessage(message, type = 'info') {
            console[type === 'error' ? 'error' : type === 'warning' ? 'warn' : 'log'](
                `[SampleComparison] ${message}`
            );
        }

        getState() {
            return this.state;
        }
    }

    // Export to namespace
    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.App = SampleComparisonApp;

})(window);
