/**
 * SampleSelector - Sample Selection Modal for GelViewer
 *
 * Modal for searching and selecting ProcessSample records
 * or entering free-text sample names for lanes.
 *
 * Features:
 * - Persists filter selections (drug substance, sheet) across modal opens
 * - Shows current assignment context when re-assigning a lane
 * - Search with debounce
 */

(function(global) {
    'use strict';

    /**
     * SampleSelector Class
     * Manages the sample selection modal.
     */
    class SampleSelector {
        /**
         * Create a SampleSelector instance.
         * @param {Object} options - Configuration options
         * @param {APIClient} options.apiClient - APIClient instance for API calls
         * @param {EventBus} options.eventBus - EventBus instance
         * @param {Function} options.showMessage - Function to display messages
         * @param {Function} options.onSelect - Callback when sample is selected (laneId, sampleData)
         * @param {Function} [options.getLaneData] - Optional getter for lane data (returns {sample_name, process_sample_id})
         */
        constructor(options) {
            this.apiClient = options.apiClient;
            this.eventBus = options.eventBus;
            this.showMessage = options.showMessage || console.log;
            // Support both onSelect and onSampleSelected for compatibility
            this.onSelect = options.onSelect || options.onSampleSelected || (() => {});
            this.getLaneData = options.getLaneData || null;

            // State
            this.currentLaneId = null;
            this.searchTimeout = null;
            this._savedDsFilter = '';
            this._savedSheetFilter = '';
            this._filterOptionsLoaded = false;

            // DOM elements
            this.backdrop = document.getElementById('sample-modal');
            this.searchInput = document.getElementById('sample-search-input');
            this.dsFilter = document.getElementById('sample-filter-ds');
            this.sheetFilter = document.getElementById('sample-filter-sheet');
            this.resultsContainer = document.getElementById('sample-results');
            this.customInput = document.getElementById('sample-custom-input');
            this.contextEl = document.getElementById('sample-context');

            this._setup();
        }

        /**
         * Setup event handlers.
         */
        _setup() {
            // Backdrop click to close
            if (this.backdrop) {
                this.backdrop.addEventListener('click', (e) => {
                    if (e.target === this.backdrop) {
                        this.close();
                    }
                });
            }

            // Close button
            const closeBtn = document.getElementById('sample-modal-close');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this.close());
            }

            // Search input with debounce
            if (this.searchInput) {
                this.searchInput.addEventListener('input', () => {
                    clearTimeout(this.searchTimeout);
                    this.searchTimeout = setTimeout(() => this._search(), 300);
                });
            }

            // Filter changes trigger search
            [this.dsFilter, this.sheetFilter].forEach(filter => {
                if (filter) {
                    filter.addEventListener('change', () => this._search());
                }
            });

            // Cancel button
            const cancelBtn = document.getElementById('sample-modal-cancel');
            if (cancelBtn) {
                cancelBtn.addEventListener('click', () => this.close());
            }

            // Select button
            const selectBtn = document.getElementById('sample-modal-select');
            if (selectBtn) {
                selectBtn.addEventListener('click', () => this._confirm());
            }
        }

        // =====================================================================
        // Open / Close
        // =====================================================================

        /**
         * Open the modal for a specific lane.
         * @param {string|number} laneId - Lane ID to link sample to
         * @param {Object} [context] - Optional context {sample_name, process_sample_id}
         */
        open(laneId, context) {
            this.currentLaneId = laneId;

            if (this.backdrop) {
                this.backdrop.classList.add('open');

                // Load filter options (only once, then restore saved selections)
                if (!this._filterOptionsLoaded) {
                    this._loadFilterOptions();
                } else {
                    // Restore previously saved filter selections
                    this._restoreFilters();
                }

                // Show context for current lane assignment
                this._showCurrentAssignment(context);

                // If lane has an existing sample, pre-populate search
                if (context && context.sample_name) {
                    if (this.searchInput) {
                        this.searchInput.value = context.sample_name;
                    }
                    // Auto-search to show the current sample in results
                    setTimeout(() => this._search(), 150);
                }

                // Focus search input
                setTimeout(() => {
                    if (this.searchInput) this.searchInput.focus();
                }, 100);
            }
        }

        /**
         * Close the modal.
         */
        close() {
            // Save current filter selections before closing
            this._saveFilters();

            if (this.backdrop) {
                this.backdrop.classList.remove('open');
            }

            this.currentLaneId = null;

            // Clear search and results
            if (this.searchInput) this.searchInput.value = '';
            if (this.resultsContainer) {
                this.resultsContainer.innerHTML = `
                    <div class="gv-sample-results-empty">
                        <i class="bi bi-search"></i>
                        Search for samples above
                    </div>
                `;
            }
            if (this.customInput) this.customInput.value = '';

            // Hide context
            if (this.contextEl) this.contextEl.style.display = 'none';
        }

        /**
         * Check if modal is open.
         * @returns {boolean}
         */
        isOpen() {
            return this.backdrop && this.backdrop.classList.contains('open');
        }

        // =====================================================================
        // Filter Persistence
        // =====================================================================

        /**
         * Save current filter dropdown values.
         */
        _saveFilters() {
            if (this.dsFilter) this._savedDsFilter = this.dsFilter.value;
            if (this.sheetFilter) this._savedSheetFilter = this.sheetFilter.value;
        }

        /**
         * Restore previously saved filter selections.
         */
        _restoreFilters() {
            if (this.dsFilter && this._savedDsFilter) {
                this.dsFilter.value = this._savedDsFilter;
            }
            if (this.sheetFilter && this._savedSheetFilter) {
                this.sheetFilter.value = this._savedSheetFilter;
            }
        }

        // =====================================================================
        // Current Assignment Context
        // =====================================================================

        /**
         * Show the current lane assignment in the modal header.
         */
        _showCurrentAssignment(context) {
            if (!this.contextEl) return;

            // Try to get context from getLaneData callback if not provided
            if (!context && this.getLaneData && this.currentLaneId) {
                context = this.getLaneData(this.currentLaneId);
            }

            if (context && (context.sample_name || context.process_sample_id)) {
                const name = context.sample_name || context.display_name || '';
                const isLinked = !!context.process_sample_id;

                this.contextEl.innerHTML =
                    '<div class="gv-sample-context-inner">' +
                        '<span class="gv-sample-context-label">Current:</span> ' +
                        '<span class="gv-sample-context-name' + (isLinked ? ' linked' : '') + '">' +
                            (isLinked ? '<i class="bi bi-link-45deg"></i> ' : '') +
                            this._escapeHtml(name) +
                        '</span>' +
                    '</div>';
                this.contextEl.style.display = '';
            } else {
                this.contextEl.innerHTML = '';
                this.contextEl.style.display = 'none';
            }
        }

        // =====================================================================
        // Filter Options
        // =====================================================================

        /**
         * Load filter options (drug substances and sheets).
         */
        async _loadFilterOptions() {
            try {
                const data = await this.apiClient.getSampleFilterOptions();

                // Populate drug substance filter
                if (this.dsFilter && data.drug_substances) {
                    this.dsFilter.innerHTML = '<option value="">All Drug Substances</option>';
                    data.drug_substances.forEach(ds => {
                        const displayName = ds.shortname || ds.fullname || `DS ${ds.id}`;
                        this.dsFilter.innerHTML += `<option value="${ds.id}">${displayName}</option>`;
                    });
                }

                // Populate sheet filter
                if (this.sheetFilter && data.sheets) {
                    this.sheetFilter.innerHTML = '<option value="">All Process Sheets</option>';
                    data.sheets.forEach(sheet => {
                        const displayName = sheet.drug_substance
                            ? `${sheet.name} (${sheet.drug_substance})`
                            : sheet.name;
                        this.sheetFilter.innerHTML += `<option value="${sheet.id}">${displayName}</option>`;
                    });
                }

                this._filterOptionsLoaded = true;

                // Restore any saved filter selections after populating
                this._restoreFilters();

            } catch (error) {
                console.error('Error loading filter options:', error);
            }
        }

        // =====================================================================
        // Search
        // =====================================================================

        /**
         * Search for samples.
         */
        async _search() {
            if (!this.resultsContainer) return;

            const query = this.searchInput ? this.searchInput.value.trim() : '';
            const dsId = this.dsFilter ? this.dsFilter.value : '';
            const sheetId = this.sheetFilter ? this.sheetFilter.value : '';

            // Show loading spinner
            this.resultsContainer.innerHTML = `
                <div class="gv-sample-loading">
                    <div class="gv-sample-loading-spinner"></div>
                    <p>Searching samples...</p>
                </div>
            `;

            try {
                const samples = await this.apiClient.searchSamples({
                    query,
                    drugSubstanceId: dsId || undefined,
                    sheetId: sheetId || undefined
                });

                if (samples.length === 0) {
                    this.resultsContainer.innerHTML = `
                        <div class="gv-sample-results-empty">
                            <i class="bi bi-inbox"></i>
                            <p>No samples found matching your criteria</p>
                        </div>
                    `;
                    return;
                }

                this._renderResults(samples);

            } catch (error) {
                console.error('Error searching samples:', error);
                this.resultsContainer.innerHTML = `
                    <div class="gv-sample-results-empty">
                        <i class="bi bi-exclamation-triangle"></i>
                        <p>Error searching samples. Please try again.</p>
                    </div>
                `;
            }
        }

        /**
         * Render search results.
         */
        _renderResults(samples) {
            this.resultsContainer.innerHTML = '';

            // Get current lane's process_sample_id for highlighting
            let currentPsId = null;
            if (this.getLaneData && this.currentLaneId) {
                const laneData = this.getLaneData(this.currentLaneId);
                if (laneData) currentPsId = laneData.process_sample_id;
            }

            samples.forEach(sample => {
                const item = document.createElement('div');
                const isCurrent = currentPsId && sample.id === currentPsId;
                item.className = 'gv-sample-item' + (isCurrent ? ' current' : '');
                item.dataset.sampleId = sample.id;
                item.dataset.sampleName = sample.sample_id;

                const cdwBadge = sample.cdw_batch_id
                    ? `<span class="gv-sample-cdw-badge" title="CDW Batch ID">${sample.cdw_batch_id}</span>`
                    : '';

                const currentBadge = isCurrent
                    ? '<span class="gv-sample-current-badge">current</span>'
                    : '';

                item.innerHTML = `
                    <div class="gv-sample-item-radio"></div>
                    <div class="gv-sample-item-content">
                        <div class="gv-sample-item-id">${sample.sample_id} ${cdwBadge} ${currentBadge}</div>
                        <div class="gv-sample-item-meta">${sample.display || ''}</div>
                    </div>
                `;

                item.addEventListener('click', () => {
                    this.resultsContainer.querySelectorAll('.gv-sample-item').forEach(i => {
                        i.classList.remove('selected');
                    });
                    item.classList.add('selected');

                    // Clear custom input when selecting from list
                    if (this.customInput) this.customInput.value = '';
                });

                this.resultsContainer.appendChild(item);
            });
        }

        // =====================================================================
        // Selection
        // =====================================================================

        /**
         * Confirm sample selection.
         */
        _confirm() {
            const selected = this.resultsContainer?.querySelector('.gv-sample-item.selected');

            if (!this.currentLaneId) return;

            let sampleName = '';
            let processSampleId = null;

            if (selected) {
                // ProcessSample selected
                processSampleId = parseInt(selected.dataset.sampleId);
                sampleName = selected.dataset.sampleName ||
                            selected.querySelector('.gv-sample-item-id')?.textContent || '';
            } else if (this.customInput && this.customInput.value.trim()) {
                // Free text sample name
                sampleName = this.customInput.value.trim();
            } else {
                this.showMessage('Please select a sample or enter a custom name.');
                return;
            }

            // Call the callback with selection data
            this.onSelect(this.currentLaneId, {
                process_sample_id: processSampleId,
                sample_name: processSampleId ? '' : sampleName,
                display_name: sampleName
            });

            this.showMessage(`Sample "${sampleName}" linked to lane.`);
            this.close();
        }

        // =====================================================================
        // Utilities
        // =====================================================================

        _escapeHtml(str) {
            const div = document.createElement('div');
            div.textContent = str || '';
            return div.innerHTML;
        }
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.SampleSelector = SampleSelector;

})(window);
