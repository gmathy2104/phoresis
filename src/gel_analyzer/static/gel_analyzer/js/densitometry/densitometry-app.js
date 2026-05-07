/**
 * Densitometry App - Main Orchestrator
 *
 * Coordinates all densitometry panels and manages the overall application flow.
 */

(function(global) {
    'use strict';

    const Events = global.Densitometry.Events;
    const EventBus = global.Densitometry.EventBus;
    const State = global.Densitometry.State;
    const ApiClient = global.Densitometry.ApiClient;

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
            if (this.closeBtn) {
                this.closeBtn.addEventListener('click', () => this.collapse());
            }
            if (this.modalOverlay) {
                this.modalOverlay.addEventListener('click', (e) => {
                    if (e.target === this.modalOverlay) {
                        this.collapse();
                    }
                });
            }
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
            if (this.activePanel) {
                this.collapse();
            }
            const content = panelElement.querySelector('.dm-panel-content');
            const titleEl = panelElement.querySelector('.dm-panel-title');
            const title = titleEl?.textContent?.trim() || 'Panel View';
            if (!content) {
                console.warn('[PanelMagnifier] Panel has no .dm-panel-content');
                return;
            }
            this.activePanel = panelElement;
            this.activePanelContent = content;
            if (this.modalTitle) {
                this.modalTitle.textContent = title;
            }
            this.modalContent.appendChild(content);
            panelElement.classList.add('dm-panel-expanded');
            this.modalOverlay.classList.add('active');
            setTimeout(() => {
                window.dispatchEvent(new Event('resize'));
            }, 50);
        }

        collapse() {
            if (!this.activePanel || !this.activePanelContent) {
                return;
            }
            this.activePanel.appendChild(this.activePanelContent);
            this.activePanel.classList.remove('dm-panel-expanded');
            if (this.modalOverlay) {
                this.modalOverlay.classList.remove('active');
            }
            this.activePanel = null;
            this.activePanelContent = null;
            setTimeout(() => {
                window.dispatchEvent(new Event('resize'));
            }, 50);
        }

        isExpanded() {
            return this.activePanel !== null;
        }
    }

    /**
     * DensitometryApp Class
     * Main entry point for the densitometry module.
     */
    class DensitometryApp {
        /**
         * @param {Object} options
         * @param {string} options.analysisId
         * @param {string} options.csrfToken
         * @param {Array} options.lanes - Initial lane data
         * @param {Array} options.bands - Initial band data
         * @param {Object} options.apiUrls - API URL endpoints
         */
        constructor(options) {
            this.analysisId = options.analysisId;
            this.imageUrl = options.imageUrl || '';

            // Create event bus
            this.eventBus = new EventBus();

            // Create state manager
            this.state = new State({
                eventBus: this.eventBus,
                analysisId: this.analysisId,
            });

            // Create API client
            this.api = new ApiClient({
                analysisId: this.analysisId,
                csrfToken: options.csrfToken,
            });

            // Panel references
            this.panels = {};

            // Track if results already exist
            this.hasExistingResults = false;

            // Load initial data
            this.state.loadData({
                lanes: options.lanes || [],
                bands: options.bands || [],
            });

            // Store calibration data for MW axis mode
            if (options.calibrationData) {
                this.state.calibrationData = options.calibrationData;
            }

            // Bind methods
            this._onRunAnalysis = this._onRunAnalysis.bind(this);
            this._onExportCSV = this._onExportCSV.bind(this);
            this._runAnalysisConfirmed = this._runAnalysisConfirmed.bind(this);
            this._onOptionsRun = this._onOptionsRun.bind(this);
        }

        /**
         * Initialize the application.
         */
        async init() {
            console.log('[DensitometryApp] Initializing...');

            // Initialize panels
            this._initPanels();

            // Initialize panel magnifier
            this._initMagnifier();

            // Setup event handlers
            this._setupEventHandlers();

            // Setup UI controls
            this._setupControls();

            // Load existing results if available
            await this._loadExistingResults();

            console.log('[DensitometryApp] Initialized');
        }

        /**
         * Initialize all panels.
         */
        _initPanels() {
            // Gel Overview Panel (top-left)
            if (global.Densitometry.GelOverviewPanel) {
                this.panels.gelOverview = new global.Densitometry.GelOverviewPanel({
                    container: document.getElementById('gel-overview-panel'),
                    eventBus: this.eventBus,
                    state: this.state,
                    imageUrl: this.imageUrl,
                });
            }

            // Chromatogram Panel (top-right)
            if (global.Densitometry.ChromatogramPanel) {
                this.panels.chromatogram = new global.Densitometry.ChromatogramPanel({
                    container: document.getElementById('chromatogram-panel'),
                    eventBus: this.eventBus,
                    state: this.state,
                    // Phase 7.1: needed by the Quantification curve tab to call
                    // /quantification/ + /quantification/preview/.
                    apiClient: this.api,
                    analysisId: this.analysisId,
                });
            }

            // Band Zoom Panel (bottom-left)
            if (global.Densitometry.BandZoomPanel) {
                this.panels.bandZoom = new global.Densitometry.BandZoomPanel({
                    container: document.getElementById('band-zoom-panel'),
                    eventBus: this.eventBus,
                    state: this.state,
                });
            }

            // Results Table Panel (bottom-right)
            if (global.Densitometry.ResultsTablePanel) {
                this.panels.resultsTable = new global.Densitometry.ResultsTablePanel({
                    container: document.getElementById('results-table-panel'),
                    eventBus: this.eventBus,
                    state: this.state,
                });
            }
        }

        /**
         * Initialize panel magnifier for fullscreen expansion.
         */
        _initMagnifier() {
            this.magnifier = new PanelMagnifier();

            // Wire up expand buttons for all panels
            document.querySelectorAll('.dm-panel-expand-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const panelId = btn.dataset.panel;
                    const panel = document.getElementById(panelId);
                    if (panel) {
                        this.magnifier.expand(panel);
                    }
                });
            });
        }

        /**
         * Setup event handlers.
         */
        _setupEventHandlers() {
            // Lane selection
            this.eventBus.on(Events.LANE_SELECTED, (data) => {
                this._onLaneSelected(data);
            });

            // Band selection
            this.eventBus.on(Events.BAND_SELECTED, (data) => {
                this._onBandSelected(data);
            });

            // Analysis events
            this.eventBus.on(Events.ANALYSIS_COMPLETED, (data) => {
                this._onAnalysisCompleted(data);
            });

            this.eventBus.on(Events.ANALYSIS_ERROR, (data) => {
                this._onAnalysisError(data);
            });

            // Orphan peak clicked - create band
            this.eventBus.on(Events.ORPHAN_PEAK_CLICKED, (data) => {
                this._onOrphanPeakClicked(data);
            });
        }

        /**
         * Setup UI controls (buttons, etc.).
         */
        _setupControls() {
            // Run Analysis button
            const runBtn = document.getElementById('run-analysis-btn');
            if (runBtn) {
                runBtn.addEventListener('click', this._onRunAnalysis);
            }

            // Stale-banner rerun button — same handler as the toolbar button,
            // but lets the user rerun directly from the warning banner.
            const staleRerunBtn = document.getElementById('stale-banner-rerun-btn');
            if (staleRerunBtn) {
                staleRerunBtn.addEventListener('click', this._onRunAnalysis);
            }

            // Export CSV button
            const exportBtn = document.getElementById('export-csv-btn');
            if (exportBtn) {
                exportBtn.addEventListener('click', this._onExportCSV);
            }

            // Normalization select
            const normSelect = document.getElementById('normalization-method');
            if (normSelect) {
                normSelect.addEventListener('change', (e) => {
                    this.state.setParams({ normalization_method: e.target.value });
                });
            }

            // Confirmation modal buttons
            const confirmCancel = document.getElementById('confirm-cancel-btn');
            const confirmProceed = document.getElementById('confirm-proceed-btn');

            if (confirmCancel) {
                confirmCancel.addEventListener('click', () => this._hideConfirmModal());
            }

            if (confirmProceed) {
                confirmProceed.addEventListener('click', () => {
                    this._hideConfirmModal();
                    this._showOptionsModal();
                });
            }

            // Analysis Options modal controls
            this._setupOptionsModal();

            // Quantification calibration modal — opened from the toolbar.
            // Re-renders all panels when a new calibration is saved so that
            // the freshly-applied estimated_amount values appear in tables /
            // chromatograms without a full page reload.
            this._setupQuantificationModal();
        }

        /**
         * Wire the Quantification calibration modal to the toolbar button.
         */
        _setupQuantificationModal() {
            const QuantModalCtor = global.Densitometry.QuantificationModal
                                || global.QuantificationModal;
            if (!QuantModalCtor) {
                console.warn('[DensitometryApp] QuantificationModal class not loaded');
                return;
            }
            const trigger = document.getElementById('open-quantification-modal');
            if (!trigger) {
                // Modal markup absent — nothing to wire.
                return;
            }
            this.quantModal = new QuantModalCtor({
                apiClient: this.api,
                analysisId: this.analysisId,
                eventBus: this.eventBus,
            });
            trigger.addEventListener('click', () => this.quantModal.open());

            // Re-load densitometry results after a new calibration is applied
            // — apply_to_analysis() bulk-updates DensitometryResult.estimated_amount
            // server-side, but the client cache still holds the old null/stale
            // values until we re-fetch.
            this.eventBus.on(
                Events.QUANT_CALIBRATION_CHANGED || 'QUANT_CALIBRATION_CHANGED',
                () => {
                    this._loadExistingResults().catch(err => {
                        console.error('[DensitometryApp] post-quant refresh failed:', err);
                    });
                }
            );
        }

        /**
         * Load existing densitometry results.
         */
        async _loadExistingResults() {
            try {
                const result = await this.api.getDensitometry();

                if (result.success && result.has_results) {
                    this.state.loadResults(result);
                    this.hasExistingResults = true;
                    this.showMessage('Loaded existing results', 'success');
                }
            } catch (error) {
                console.warn('[DensitometryApp] No existing results:', error.message);
                this.hasExistingResults = false;
            }

            this._updateStaleBanner();
        }

        /**
         * Toggle the "results out of date" banner.
         *
         * The Band post_save / post_delete signal in ``gel_analyzer.signals``
         * deletes ``LaneDensitometrySummary`` and sibling ``DensitometryResult``
         * rows whenever a band is added, edited or removed in the Annotation
         * module. After that, this page still serves stale numbers from the
         * page-render context (``state.lanes`` / ``state.bands``) — but the
         * post-load fetch returns *less* data than the band set demands:
         *
         *   - either ``has_results`` is false (lane summary was wiped, no
         *     other lane has results either),
         *   - or some bands in ``state.bands`` have no ``densitometry`` block
         *     attached because their ``DensitometryResult`` row was wiped.
         *
         * Either condition means the displayed totals / percentages reflect a
         * previous band set and should not be trusted. We surface a banner
         * with a one-click rerun rather than letting the user squint at the
         * chromatogram trying to figure out what's off.
         */
        _updateStaleBanner() {
            const banner = document.getElementById('stale-results-banner');
            if (!banner) return;

            const totalBands = this.state.bands.size;
            if (totalBands === 0) {
                // Nothing to integrate yet — no stale state possible.
                banner.hidden = true;
                return;
            }

            // Count bands with attached densitometry (filled by ``loadResults``).
            let bandsWithDensitometry = 0;
            for (const band of this.state.bands.values()) {
                if (band.densitometry) bandsWithDensitometry += 1;
            }

            // Stale if any band lacks a ``densitometry`` block. Two flavours:
            //   1. ``hasExistingResults`` is true but the fetch returned data
            //      for only some bands → at least one new band slipped in
            //      after the last Run Analysis.
            //   2. ``hasExistingResults`` is false but bands exist → the
            //      Band-edit signal wiped EVERY ``DensitometryResult`` for
            //      the analysis (the common post-split case). The earlier
            //      version of this method gated this branch on
            //      ``hasExistingResults`` too, which silenced the banner in
            //      the *exact* scenario it was added to surface.
            // Either way: bandsWithDensitometry < totalBands ⇔ stale.
            const isStale = bandsWithDensitometry < totalBands;

            banner.hidden = !isStale;
        }

        // =====================================================================
        // Event Handlers
        // =====================================================================

        /**
         * Handle lane selection.
         */
        _onLaneSelected(data) {
            console.log('[DensitometryApp] Lane selected:', data.laneId);

            // Load profile if not cached
            if (data.laneId && !this.state.getProfile(data.laneId)) {
                this._loadLaneProfile(data.laneId);
            }
        }

        /**
         * Handle band selection.
         */
        _onBandSelected(data) {
            console.log('[DensitometryApp] Band selected:', data.bandId);
        }

        /**
         * Load lane profile.
         */
        async _loadLaneProfile(laneId) {
            try {
                const result = await this.api.getLaneProfile(laneId);

                if (result.success) {
                    this.state.profiles.set(laneId, result.profile);
                    this.eventBus.emit(Events.PROFILE_LOADED, {
                        laneId,
                        profile: result.profile,
                    });
                }
            } catch (error) {
                console.error('[DensitometryApp] Failed to load profile:', error);
            }
        }

        /**
         * Handle analysis completed.
         */
        _onAnalysisCompleted(data) {
            console.log('[DensitometryApp] Analysis completed:', data);
            this.showMessage('Analysis complete', 'success');

            // Re-enable buttons
            this._setAnalysisRunning(false);
        }

        /**
         * Handle analysis error.
         */
        _onAnalysisError(data) {
            console.error('[DensitometryApp] Analysis error:', data);
            this.showMessage(data.error || 'Analysis failed', 'error');

            this._setAnalysisRunning(false);
        }

        /**
         * Handle orphan peak clicked - redirect to Annotation Editor.
         *
         * NOTE: Band creation is handled in the Annotation module,
         * not in Densitometry. This handler shows an info message
         * directing the user to the Annotation Editor.
         */
        _onOrphanPeakClicked(data) {
            const { peak } = data;

            // Inform user to use Annotation Editor for band creation
            this.showMessage(
                `Orphan peak at Y=${peak.y_position.toFixed(0)}px. ` +
                `To create a band, use the Annotation Editor.`,
                'info'
            );
        }

        // =====================================================================
        // Actions
        // =====================================================================

        /**
         * Handle Run Analysis button click.
         * Shows confirmation modal if results already exist, then options modal.
         */
        _onRunAnalysis() {
            if (this.hasExistingResults) {
                // Show confirmation modal first
                this._showConfirmModal();
            } else {
                // No existing results, show options modal directly
                this._showOptionsModal();
            }
        }

        /**
         * Setup Analysis Options modal controls.
         */
        _setupOptionsModal() {
            const optionsModal = document.getElementById('analysis-options-modal');
            if (!optionsModal) return;

            // Close button
            const closeBtn = document.getElementById('options-close-btn');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this._hideOptionsModal());
            }

            // Cancel button
            const cancelBtn = document.getElementById('options-cancel-btn');
            if (cancelBtn) {
                cancelBtn.addEventListener('click', () => this._hideOptionsModal());
            }

            // Run button
            const runBtn = document.getElementById('options-run-btn');
            if (runBtn) {
                runBtn.addEventListener('click', this._onOptionsRun);
            }

            // Close on overlay click
            optionsModal.addEventListener('click', (e) => {
                if (e.target === optionsModal) {
                    this._hideOptionsModal();
                }
            });

            // Advanced options toggle
            const toggleAdvanced = document.getElementById('toggle-advanced');
            const advancedContent = document.getElementById('advanced-options');
            if (toggleAdvanced && advancedContent) {
                toggleAdvanced.addEventListener('click', () => {
                    const isHidden = advancedContent.style.display === 'none';
                    advancedContent.style.display = isHidden ? 'block' : 'none';
                    toggleAdvanced.classList.toggle('expanded', isHidden);
                });
            }

            // Sensitivity slider value display
            const sensitivitySlider = document.getElementById('opt-sensitivity');
            const sensitivityValue = document.getElementById('opt-sensitivity-value');
            if (sensitivitySlider && sensitivityValue) {
                sensitivitySlider.addEventListener('input', () => {
                    sensitivityValue.textContent = sensitivitySlider.value;
                });
            }
        }

        /**
         * Handle "Run Analysis" click in options modal.
         */
        async _onOptionsRun() {
            const detectionMode = document.querySelector('input[name="detection-mode"]:checked')?.value || 'existing';

            // Get advanced options
            const sensitivity = parseFloat(document.getElementById('opt-sensitivity')?.value || 0.85);
            const minDistance = parseInt(document.getElementById('opt-min-distance')?.value || 10);
            const matchTolerance = parseInt(document.getElementById('opt-match-tolerance')?.value || 15);
            const enableDeconv = document.getElementById('opt-enable-deconv')?.checked || false;

            // Store detection params
            this.state.setPeakDetectionParams({
                sensitivity,
                min_peak_distance: minDistance,
                match_tolerance_px: matchTolerance,
                enable_deconvolution: enableDeconv,
            });

            // Emit event
            this.eventBus.emit(Events.ANALYSIS_OPTIONS_SELECTED, {
                mode: detectionMode,
                params: this.state.getPeakDetectionParams(),
            });

            // Hide modal
            this._hideOptionsModal();

            if (detectionMode === 'auto-detect') {
                // Auto-detect flow: detect peaks, create bands, then run analysis
                await this._runWithAutoDetection();
            } else {
                // Use existing bands flow
                await this._runAnalysisConfirmed();
            }
        }

        /**
         * Run analysis with automatic peak detection (VISUALIZATION ONLY).
         *
         * NOTE: This does NOT create bands. Peak detection is for visualization
         * only - orphan peaks are shown as markers on the chart. To create
         * actual bands, use the Annotation Editor.
         *
         * Flow:
         * 1. Detect peaks for all lanes (no DB changes)
         * 2. Display detected peaks as visual markers
         * 3. Run densitometry analysis on EXISTING bands only
         */
        async _runWithAutoDetection() {
            console.log('[DensitometryApp] Starting analysis with peak visualization...');

            this._showSpinner();
            this._setAnalysisRunning(true);
            this._updateSpinnerProgress(0);
            this._updateSpinnerText('Detecting peaks...');

            this.eventBus.emit(Events.PEAKS_DETECTION_STARTED);

            try {
                // Get detection params
                const detectionParams = this.state.getPeakDetectionParams();

                // Detect peaks for visualization only (no band creation)
                const detectResult = await this.api.detectAndCreateBands(
                    {
                        sensitivity: detectionParams.sensitivity,
                        min_peak_distance: detectionParams.min_peak_distance,
                        enable_shoulder_detection: true,
                        enable_deconvolution: detectionParams.enable_deconvolution,
                    },
                    detectionParams.match_tolerance_px
                );

                if (!detectResult.success) {
                    throw new Error(detectResult.error || 'Failed to detect peaks');
                }

                console.log('[DensitometryApp] Peak detection result:', detectResult);

                // Build info message
                const orphanCount = detectResult.lanes?.reduce((sum, l) => sum + (l.orphans || 0), 0) || 0;
                let message = `Detected ${detectResult.total_peaks_detected} peaks (${detectResult.bands_matched} matched, ${orphanCount} orphan)`;
                this.showMessage(message, 'info');

                // Store detected peaks per lane for visualization (visual markers only)
                if (detectResult.lanes) {
                    detectResult.lanes.forEach(lane => {
                        if (lane.peaks && lane.peaks.length > 0) {
                            this.state.setDetectedPeaks(lane.lane_id, lane.peaks);
                        }
                    });
                }

                this._updateSpinnerProgress(30);
                this._updateSpinnerText('Running densitometry analysis...');

                // Now run the actual analysis on EXISTING bands
                this.eventBus.emit(Events.ANALYSIS_STARTED);

                // Start async analysis
                const startResult = await this.api.runDensitometryAsync(
                    this.state.getParams()
                );

                if (!startResult.success) {
                    throw new Error(startResult.error || 'Failed to start analysis');
                }

                // Poll for completion
                const result = await this.api.pollJob(
                    startResult.job_id,
                    (status) => {
                        this.eventBus.emit(Events.ANALYSIS_PROGRESS, {
                            progress: status.progress,
                            status: status.status,
                        });
                        // Map 0-100% to 30-100% range
                        const mappedProgress = 30 + (status.progress * 0.7);
                        this._updateProgress(mappedProgress);
                        this._updateSpinnerProgress(mappedProgress);
                    }
                );

                // Load fresh results
                const freshResults = await this.api.getDensitometry();
                if (freshResults.success) {
                    this.state.loadResults(freshResults);
                    this.hasExistingResults = true;
                }

                this._updateStaleBanner();

                this.eventBus.emit(Events.ANALYSIS_COMPLETED, result);

            } catch (error) {
                console.error('[DensitometryApp] Auto-detection analysis error:', error);
                this.eventBus.emit(Events.PEAKS_DETECTION_ERROR, { error: error.message });
                this.eventBus.emit(Events.ANALYSIS_ERROR, { error: error.message });
            } finally {
                this._hideSpinner();
            }
        }

        /**
         * Update spinner text.
         */
        _updateSpinnerText(text) {
            const spinnerText = document.querySelector('.dm-spinner-text');
            if (spinnerText) {
                spinnerText.textContent = text;
            }
        }

        /**
         * Run densitometry analysis (after confirmation if needed).
         */
        async _runAnalysisConfirmed() {
            console.log('[DensitometryApp] Starting analysis...');

            this._showSpinner();
            this._setAnalysisRunning(true);
            this.eventBus.emit(Events.ANALYSIS_STARTED);

            try {
                // Start async analysis
                const startResult = await this.api.runDensitometryAsync(
                    this.state.getParams()
                );

                if (!startResult.success) {
                    throw new Error(startResult.error || 'Failed to start analysis');
                }

                // Poll for completion
                const result = await this.api.pollJob(
                    startResult.job_id,
                    (status) => {
                        this.eventBus.emit(Events.ANALYSIS_PROGRESS, {
                            progress: status.progress,
                            status: status.status,
                        });
                        this._updateProgress(status.progress);
                        this._updateSpinnerProgress(status.progress);
                    }
                );

                // Load fresh results
                const freshResults = await this.api.getDensitometry();
                if (freshResults.success) {
                    this.state.loadResults(freshResults);
                    this.hasExistingResults = true;  // Now we have results
                }

                this._updateStaleBanner();

                this.eventBus.emit(Events.ANALYSIS_COMPLETED, result);

            } catch (error) {
                this.eventBus.emit(Events.ANALYSIS_ERROR, { error: error.message });
            } finally {
                this._hideSpinner();
            }
        }

        /**
         * Export results to CSV.
         */
        async _onExportCSV() {
            console.log('[DensitometryApp] Exporting CSV...');

            try {
                const blob = await this.api.exportCSV(false);

                // Create download link
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `densitometry_${this.analysisId}.csv`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);

                this.showMessage('CSV exported', 'success');

            } catch (error) {
                console.error('[DensitometryApp] Export failed:', error);
                this.showMessage('Export failed: ' + error.message, 'error');
            }
        }

        // =====================================================================
        // UI Helpers
        // =====================================================================

        /**
         * Set analysis running state.
         */
        _setAnalysisRunning(running) {
            const runBtn = document.getElementById('run-analysis-btn');
            if (runBtn) {
                runBtn.disabled = running;
                runBtn.innerHTML = running
                    ? '<span class="spinner-border spinner-border-sm me-2"></span>Running...'
                    : '<i class="bi bi-play-circle me-2"></i>Run Analysis';
            }

            const progressBar = document.getElementById('analysis-progress');
            if (progressBar) {
                progressBar.style.display = running ? 'block' : 'none';
            }
        }

        /**
         * Update progress bar.
         */
        _updateProgress(percent) {
            const progressBar = document.getElementById('analysis-progress-bar');
            if (progressBar) {
                progressBar.style.width = `${percent}%`;
                progressBar.setAttribute('aria-valuenow', percent);
            }
        }

        /**
         * Show loading spinner overlay.
         */
        _showSpinner() {
            const spinner = document.getElementById('analysis-spinner');
            if (spinner) {
                spinner.style.display = 'flex';
            }
            this._updateSpinnerProgress(0);
        }

        /**
         * Hide loading spinner overlay.
         */
        _hideSpinner() {
            const spinner = document.getElementById('analysis-spinner');
            if (spinner) {
                spinner.style.display = 'none';
            }
        }

        /**
         * Update spinner progress text.
         */
        _updateSpinnerProgress(percent) {
            const progressText = document.getElementById('spinner-progress');
            if (progressText) {
                if (percent === 0) {
                    progressText.textContent = 'Starting...';
                } else if (percent >= 100) {
                    progressText.textContent = 'Finalizing...';
                } else {
                    progressText.textContent = `Processing... ${percent}%`;
                }
            }
        }

        /**
         * Show confirmation modal.
         */
        _showConfirmModal() {
            const modal = document.getElementById('confirm-modal');
            if (modal) {
                modal.style.display = 'flex';
            }
        }

        /**
         * Hide confirmation modal.
         */
        _hideConfirmModal() {
            const modal = document.getElementById('confirm-modal');
            if (modal) {
                modal.style.display = 'none';
            }
        }

        /**
         * Show Analysis Options modal.
         */
        _showOptionsModal() {
            const modal = document.getElementById('analysis-options-modal');
            if (modal) {
                modal.style.display = 'flex';
            }
        }

        /**
         * Hide Analysis Options modal.
         */
        _hideOptionsModal() {
            const modal = document.getElementById('analysis-options-modal');
            if (modal) {
                modal.style.display = 'none';
            }
        }

        /**
         * Show a message to the user.
         */
        showMessage(message, type = 'info') {
            const container = document.getElementById('message-container');
            if (!container) {
                console.log(`[${type}] ${message}`);
                return;
            }

            const alertClass = {
                success: 'alert-success',
                error: 'alert-danger',
                warning: 'alert-warning',
                info: 'alert-info',
            }[type] || 'alert-info';

            const alert = document.createElement('div');
            alert.className = `alert ${alertClass} alert-dismissible fade show`;
            alert.innerHTML = `
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;

            container.appendChild(alert);

            // Auto-dismiss after 5 seconds
            setTimeout(() => {
                alert.classList.remove('show');
                setTimeout(() => alert.remove(), 150);
            }, 5000);
        }

        // =====================================================================
        // Public API
        // =====================================================================

        /**
         * Select a lane programmatically.
         */
        selectLane(laneId) {
            this.state.selectLane(laneId);
        }

        /**
         * Select a band programmatically.
         */
        selectBand(bandId) {
            this.state.selectBand(bandId);
        }

        /**
         * Get current state.
         */
        getState() {
            return this.state;
        }
    }

    // Export
    global.Densitometry = global.Densitometry || {};
    global.Densitometry.App = DensitometryApp;

})(window);
