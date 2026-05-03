/**
 * Results Table Panel - Densitometry Measurements Table
 *
 * Displays a table of all band measurements with sorting and filtering.
 * Features:
 * - Absolute and relative intensities
 * - Purity calculations
 * - Click to select bands
 * - Sortable columns
 */

(function(global) {
    'use strict';

    const Events = global.Densitometry.Events;

    /**
     * ResultsTablePanel Class
     */
    class ResultsTablePanel {
        /**
         * @param {Object} options
         * @param {HTMLElement} options.container
         * @param {EventBus} options.eventBus
         * @param {State} options.state
         */
        constructor(options) {
            this.container = options.container;
            this.eventBus = options.eventBus;
            this.state = options.state;

            // Sort state
            this.sortColumn = 'lane_number';
            this.sortDirection = 'asc';

            // Filter state
            this.filterLaneId = null;  // null = all lanes
            this.filterBandType = null;  // null = all types

            // View state
            this.compactMode = false;
            this.syncWithLane = true;  // Enabled by default - table follows lane selection

            // Resize handling
            this.resizeObserver = null;
            this.resizeTimeout = null;

            this._init();
        }

        /**
         * Initialize the panel.
         */
        _init() {
            if (!this.container) {
                console.warn('[ResultsTablePanel] No container element');
                return;
            }

            // Find the content element (inside the panel, not the panel itself)
            this.contentElement = this.container.querySelector('.dm-panel-content');
            if (!this.contentElement) {
                console.warn('[ResultsTablePanel] No .dm-panel-content element found');
                this.contentElement = this.container;  // Fallback
            }

            this._createLayout();
            this._setupEvents();
            this._setupResizeObserver();
        }

        /**
         * Create the panel layout.
         */
        _createLayout() {
            this.contentElement.innerHTML = `
                <div class="dm-results-container">
                    <!-- Quick Filter Chips -->
                    <div class="dm-quick-filters">
                        <button class="dm-chip active" data-filter="">All</button>
                        <button class="dm-chip dm-chip-poi" data-filter="POI">
                            <span class="dm-chip-icon">★</span> POI
                        </button>
                        <button class="dm-chip dm-chip-other" data-filter="OTHER">Other</button>
                        <button class="dm-chip dm-chip-mw" data-filter="MW_REFERENCE">
                            <span class="dm-chip-icon">M</span> MW Ref
                        </button>
                    </div>

                    <!-- Toolbar -->
                    <div class="dm-results-toolbar">
                        <div class="dm-filter-controls">
                            <select id="filter-lane" class="dm-select dm-select-sm">
                                <option value="">All Lanes</option>
                            </select>
                            <label class="dm-sync-toggle" data-tooltip="Auto-filter to selected lane">
                                <input type="checkbox" id="sync-lane-filter" checked>
                                <i class="bi bi-link-45deg"></i>
                                <span>Sync</span>
                            </label>
                        </div>
                        <div class="dm-view-controls">
                            <button id="compact-toggle" class="dm-btn dm-btn-sm" data-tooltip="Toggle compact view">
                                <i class="bi bi-layout-text-sidebar-reverse"></i>
                            </button>
                        </div>
                    </div>

                    <!-- Table -->
                    <div class="dm-results-table-wrapper">
                        <table class="dm-results-table" id="results-table">
                            <thead>
                                <tr>
                                    <th data-column="lane_number" class="sortable col-lane">Lane</th>
                                    <th data-column="band_type" class="sortable col-type">Type</th>
                                    <th data-column="detection_source" class="sortable col-source">Source</th>
                                    <th data-column="position_y" class="sortable col-position">Pos</th>
                                    <th data-column="estimated_mw_kda" class="sortable col-mw">MW</th>
                                    <th data-column="corrected_area" class="sortable col-area">Area</th>
                                    <th data-column="relative_percent_lane" class="sortable col-percent">%</th>
                                    <th data-column="fit_r_squared" class="sortable col-rsquared">R²</th>
                                </tr>
                            </thead>
                            <tbody id="results-tbody">
                                <!-- Rows will be inserted here -->
                            </tbody>
                        </table>
                    </div>

                    <!-- Summary Footer -->
                    <div class="dm-results-footer" id="table-summary">
                        <!-- Summary stats will be inserted here -->
                    </div>
                </div>
            `;

            this._setupFilterHandlers();
            this._setupQuickFilters();
            this._setupViewControls();
            this._setupSortHandlers();
        }

        /**
         * Setup filter dropdown handlers.
         */
        _setupFilterHandlers() {
            const laneSelect = this.contentElement.querySelector('#filter-lane');
            laneSelect.addEventListener('change', (e) => {
                this.filterLaneId = e.target.value || null;
                this._renderTable();
            });

            // Sync toggle
            const syncToggle = this.contentElement.querySelector('#sync-lane-filter');
            syncToggle.addEventListener('change', (e) => {
                this.syncWithLane = e.target.checked;
                if (this.syncWithLane && this.state.selectedLaneId) {
                    this.filterLaneId = this.state.selectedLaneId;
                    laneSelect.value = this.state.selectedLaneId;
                    this._renderTable();
                }
            });
        }

        /**
         * Setup quick filter chip handlers.
         */
        _setupQuickFilters() {
            const chips = this.contentElement.querySelectorAll('.dm-chip');
            chips.forEach(chip => {
                chip.addEventListener('click', () => {
                    // Update active state
                    chips.forEach(c => c.classList.remove('active'));
                    chip.classList.add('active');

                    // Apply filter
                    this.filterBandType = chip.dataset.filter || null;
                    this._renderTable();
                });
            });
        }

        /**
         * Setup view control handlers.
         */
        _setupViewControls() {
            const compactToggle = this.contentElement.querySelector('#compact-toggle');
            compactToggle.addEventListener('click', () => {
                this._toggleCompactMode();
            });
        }

        /**
         * Setup sort handlers.
         */
        _setupSortHandlers() {
            this.contentElement.querySelectorAll('th.sortable').forEach(th => {
                th.addEventListener('click', () => {
                    this._onSort(th.dataset.column);
                });
            });
        }

        /**
         * Toggle compact view mode.
         */
        _toggleCompactMode() {
            this.compactMode = !this.compactMode;

            const table = this.contentElement.querySelector('.dm-results-table');
            const toggle = this.contentElement.querySelector('#compact-toggle');

            if (table) {
                table.classList.toggle('compact', this.compactMode);
            }
            if (toggle) {
                toggle.classList.toggle('active', this.compactMode);
                toggle.setAttribute('data-tooltip', this.compactMode ? 'Show all columns' : 'Compact view');
            }
        }

        /**
         * Setup event listeners.
         */
        _setupEvents() {
            this.eventBus.on(Events.DATA_LOADED, () => {
                this._populateLaneFilter();
                this._renderTable();
            });

            this.eventBus.on(Events.DATA_UPDATED, () => {
                this._renderTable();
            });

            this.eventBus.on(Events.BAND_SELECTED, (data) => {
                this._highlightRow(data.bandId);
            });

            this.eventBus.on(Events.LANE_SELECTED, (data) => {
                // Sync with lane selection if enabled
                if (this.syncWithLane && data.laneId) {
                    this.filterLaneId = data.laneId;
                    const laneSelect = this.contentElement.querySelector('#filter-lane');
                    if (laneSelect) {
                        laneSelect.value = data.laneId;
                    }
                    this._renderTable();
                }
            });
        }

        /**
         * Populate the lane filter dropdown.
         */
        _populateLaneFilter() {
            const select = this.contentElement.querySelector('#filter-lane');
            const lanes = this.state.getAllLanes();

            // Keep the "All Lanes" option
            select.innerHTML = '<option value="">All Lanes</option>';

            lanes.forEach(lane => {
                const option = document.createElement('option');
                option.value = lane.id;
                option.textContent = `Lane ${lane.lane_number}`;
                select.appendChild(option);
            });
        }

        /**
         * Handle column sort.
         */
        _onSort(column) {
            if (this.sortColumn === column) {
                this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                this.sortColumn = column;
                this.sortDirection = 'asc';
            }

            // Update sort indicators
            this.contentElement.querySelectorAll('th.sortable').forEach(th => {
                th.classList.remove('sort-asc', 'sort-desc');
                if (th.dataset.column === column) {
                    th.classList.add(`sort-${this.sortDirection}`);
                }
            });

            this._renderTable();

            this.eventBus.emit(Events.TABLE_SORT_CHANGED, {
                column: this.sortColumn,
                direction: this.sortDirection,
            });
        }

        /**
         * Render the results table.
         */
        _renderTable() {
            const tbody = this.contentElement.querySelector('#results-tbody');
            if (!tbody) return;

            // Get and filter bands
            let bands = this.state.getAllBands();

            if (this.filterLaneId) {
                bands = bands.filter(b => b.lane_id === this.filterLaneId);
            }

            if (this.filterBandType) {
                bands = bands.filter(b => b.band_type === this.filterBandType);
            }

            // Sort bands
            bands = this._sortBands(bands);

            // Render rows
            if (bands.length === 0) {
                tbody.innerHTML = `
                    <tr class="dm-empty-row">
                        <td colspan="8">No bands to display</td>
                    </tr>
                `;
            } else {
                tbody.innerHTML = bands.map(band => this._renderRow(band)).join('');

                // Add click handlers
                tbody.querySelectorAll('tr[data-band-id]').forEach(row => {
                    row.addEventListener('click', () => {
                        const bandId = row.dataset.bandId;
                        this.state.selectBand(bandId);
                    });
                });
            }

            // Update summary
            this._updateSummary(bands);
        }

        /**
         * Sort bands array.
         */
        _sortBands(bands) {
            const col = this.sortColumn;
            const dir = this.sortDirection === 'asc' ? 1 : -1;

            return [...bands].sort((a, b) => {
                let aVal, bVal;

                switch (col) {
                    case 'lane_number':
                        aVal = a.lane_number;
                        bVal = b.lane_number;
                        break;
                    case 'band_type':
                        aVal = a.band_type;
                        bVal = b.band_type;
                        break;
                    case 'detection_source':
                        aVal = a.detection_source || '';
                        bVal = b.detection_source || '';
                        break;
                    case 'position_y':
                        aVal = a.position_y;
                        bVal = b.position_y;
                        break;
                    case 'estimated_mw_kda':
                        aVal = a.estimated_mw_kda || 0;
                        bVal = b.estimated_mw_kda || 0;
                        break;
                    case 'corrected_area':
                        aVal = a.densitometry?.corrected_area || 0;
                        bVal = b.densitometry?.corrected_area || 0;
                        break;
                    case 'relative_percent_lane':
                        aVal = a.densitometry?.relative_percent_lane || 0;
                        bVal = b.densitometry?.relative_percent_lane || 0;
                        break;
                    case 'fit_r_squared':
                        aVal = a.densitometry?.fit_r_squared || 0;
                        bVal = b.densitometry?.fit_r_squared || 0;
                        break;
                    default:
                        aVal = 0;
                        bVal = 0;
                }

                if (aVal < bVal) return -dir;
                if (aVal > bVal) return dir;
                return 0;
            });
        }

        /**
         * Render a single table row.
         */
        _renderRow(band) {
            const d = band.densitometry || {};
            const isSelected = band.id === this.state.selectedBandId;

            // Type badge with icon
            const typeConfig = {
                'POI': { class: 'dm-type-poi', icon: '★', label: 'POI' },
                'OTHER': { class: 'dm-type-other', icon: '', label: 'Other' },
                'MW_REFERENCE': { class: 'dm-type-mw', icon: 'M', label: 'MW' }
            };
            const type = typeConfig[band.band_type] || typeConfig['OTHER'];

            // Detection source badge
            const sourceConfig = {
                'MANUAL': { class: 'dm-source-manual', label: 'Manual' },
                'YOLO': { class: 'dm-source-yolo', label: 'YOLO' },
                'SAM': { class: 'dm-source-sam', label: 'SAM' },
                'CV2': { class: 'dm-source-auto', label: 'Auto (d1/d2)' },
                'PROFILE': { class: 'dm-source-profile', label: 'Profile' }
            };
            const source = sourceConfig[band.detection_source] || { class: 'dm-source-unknown', label: band.detection_source || '?' };

            // Format area with K/M suffix
            const areaFormatted = this._formatArea(d.corrected_area);

            // Percent with visual bar
            const percent = d.relative_percent_lane;
            const percentHtml = percent != null
                ? `<div class="dm-percent-cell">
                     <div class="dm-percent-bar" style="width: ${Math.min(percent, 100)}%"></div>
                     <span class="dm-percent-value">${percent.toFixed(1)}%</span>
                   </div>`
                : '-';

            // R² with quality indicator
            const r2 = d.fit_r_squared;
            const r2Html = r2 != null
                ? `<span class="dm-r2-value ${r2 >= 0.95 ? 'dm-r2-good' : r2 >= 0.9 ? 'dm-r2-ok' : 'dm-r2-poor'}">${r2.toFixed(3)}</span>`
                : '-';

            return `
                <tr data-band-id="${band.id}" class="${isSelected ? 'selected' : ''}">
                    <td class="col-lane">${band.lane_number}</td>
                    <td class="col-type">
                        <span class="dm-type-badge ${type.class}">
                            ${type.icon ? `<span class="dm-badge-icon">${type.icon}</span>` : ''}${type.label}
                        </span>
                    </td>
                    <td class="col-source">
                        <span class="dm-source-badge ${source.class}">${source.label}</span>
                    </td>
                    <td class="col-position">${band.position_y}</td>
                    <td class="col-mw">${band.estimated_mw_kda ? Math.round(band.estimated_mw_kda) : '-'}</td>
                    <td class="col-area">${areaFormatted}</td>
                    <td class="col-percent">${percentHtml}</td>
                    <td class="col-rsquared">${r2Html}</td>
                </tr>
            `;
        }

        /**
         * Format area with K/M suffix.
         */
        _formatArea(value) {
            if (!value) return '-';
            if (value >= 1000000) return (value / 1000000).toFixed(1) + 'M';
            if (value >= 1000) return (value / 1000).toFixed(1) + 'K';
            return Math.round(value).toString();
        }

        /**
         * Update summary statistics.
         */
        _updateSummary(bands) {
            const container = this.contentElement.querySelector('#table-summary');
            if (!container) return;

            const totalBands = bands.length;
            const poiBands = bands.filter(b => b.band_type === 'POI').length;
            const otherBands = bands.filter(b => b.band_type === 'OTHER').length;

            // Calculate total area
            const totalArea = bands.reduce((sum, b) => {
                return sum + (b.densitometry?.corrected_area || 0);
            }, 0);

            // Calculate POI area
            const poiArea = bands
                .filter(b => b.band_type === 'POI')
                .reduce((sum, b) => sum + (b.densitometry?.corrected_area || 0), 0);

            // Calculate purity (POI / (POI + OTHER))
            const otherArea = bands
                .filter(b => b.band_type === 'OTHER')
                .reduce((sum, b) => sum + (b.densitometry?.corrected_area || 0), 0);

            const purity = poiArea + otherArea > 0
                ? (poiArea / (poiArea + otherArea) * 100)
                : null;

            container.innerHTML = `
                <div class="dm-summary-stats">
                    <span class="dm-stat">
                        <span class="dm-stat-value">${totalBands}</span>
                        <span class="dm-stat-label">Bands</span>
                    </span>
                    <span class="dm-stat dm-stat-poi">
                        <span class="dm-stat-value">${poiBands}</span>
                        <span class="dm-stat-label">POI</span>
                    </span>
                    <span class="dm-stat dm-stat-other">
                        <span class="dm-stat-value">${otherBands}</span>
                        <span class="dm-stat-label">Other</span>
                    </span>
                    ${totalArea > 0 ? `
                        <span class="dm-stat">
                            <span class="dm-stat-value">${this._formatArea(totalArea)}</span>
                            <span class="dm-stat-label">Total Area</span>
                        </span>
                    ` : ''}
                    ${purity !== null ? `
                        <span class="dm-stat dm-stat-purity ${purity >= 90 ? 'dm-purity-high' : purity >= 70 ? 'dm-purity-medium' : 'dm-purity-low'}">
                            <span class="dm-stat-value">${purity.toFixed(1)}%</span>
                            <span class="dm-stat-label">Purity</span>
                        </span>
                    ` : ''}
                </div>
            `;
        }

        /**
         * Highlight a row by band ID.
         */
        _highlightRow(bandId) {
            // Remove previous selection
            this.contentElement.querySelectorAll('tr.selected').forEach(row => {
                row.classList.remove('selected');
            });

            // Add selection to new row
            if (bandId) {
                const row = this.contentElement.querySelector(`tr[data-band-id="${bandId}"]`);
                if (row) {
                    row.classList.add('selected');
                    row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
            }
        }

        /**
         * Export current table data to array.
         */
        exportData() {
            let bands = this.state.getAllBands();

            if (this.filterLaneId) {
                bands = bands.filter(b => b.lane_id === this.filterLaneId);
            }

            if (this.filterBandType) {
                bands = bands.filter(b => b.band_type === this.filterBandType);
            }

            return this._sortBands(bands).map(band => ({
                lane_number: band.lane_number,
                band_type: band.band_type,
                detection_source: band.detection_source,
                position_y: band.position_y,
                estimated_mw_kda: band.estimated_mw_kda,
                corrected_area: band.densitometry?.corrected_area,
                relative_percent_lane: band.densitometry?.relative_percent_lane,
                fit_r_squared: band.densitometry?.fit_r_squared,
            }));
        }

        /**
         * Setup ResizeObserver with debouncing.
         */
        _setupResizeObserver() {
            if (this.resizeObserver) {
                this.resizeObserver.disconnect();
            }

            this.resizeObserver = new ResizeObserver(() => {
                if (this.resizeTimeout) {
                    cancelAnimationFrame(this.resizeTimeout);
                }
                this.resizeTimeout = requestAnimationFrame(() => {
                    this._handleResize();
                });
            });

            this.resizeObserver.observe(this.contentElement);
        }

        /**
         * Handle resize - ensure table layout is valid.
         */
        _handleResize() {
            const rect = this.contentElement.getBoundingClientRect();
            // Skip if container has no dimensions (panel hidden/collapsed)
            if (rect.width === 0 || rect.height === 0) return;

            // Table layout is handled by CSS flexbox/grid
            // No need to re-render unless data changes
        }

        /**
         * Cleanup resources.
         */
        destroy() {
            if (this.resizeObserver) {
                this.resizeObserver.disconnect();
                this.resizeObserver = null;
            }
            if (this.resizeTimeout) {
                cancelAnimationFrame(this.resizeTimeout);
                this.resizeTimeout = null;
            }
        }
    }

    // Export
    global.Densitometry = global.Densitometry || {};
    global.Densitometry.ResultsTablePanel = ResultsTablePanel;

})(window);
