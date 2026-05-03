/**
 * Sample Comparison State - Centralized State Management
 *
 * Manages state for comparing multiple ProcessSamples' gel densitometry data.
 * Supports 1-4 samples with their lanes, bands, and profiles.
 */

(function(global) {
    'use strict';

    // Get EventBus from core
    const CoreEventBus = global.GelAnalyzer?.Core?.EventBus;

    /**
     * Event constants for sample comparison.
     */
    const ComparisonEvents = {
        // Sample management
        SAMPLE_ADDED: 'sample:added',
        SAMPLE_REMOVED: 'sample:removed',
        SAMPLE_SELECTED: 'sample:selected',

        // Data events
        DATA_LOADED: 'data:loaded',
        DATA_UPDATED: 'data:updated',
        PROFILE_LOADED: 'profile:loaded',

        // Selection
        BAND_SELECTED: 'band:selected',
        BAND_HOVERED: 'band:hovered',

        // View modes
        POI_ONLY_MODE_CHANGED: 'poi:only:changed',
        SCALE_MODE_CHANGED: 'scale:mode:changed',
        DIGITAL_LANE_MODE_CHANGED: 'digital:lane:mode:changed',
        X_AXIS_MODE_CHANGED: 'x:axis:mode:changed',
        NORMALIZATION_MODE_CHANGED: 'normalization:mode:changed',

        // Chart events
        CHART_READY: 'chart:ready',
        ZOOM_CHANGED: 'zoom:changed',

        // Ordering
        SAMPLE_ORDER_CHANGED: 'sample:order:changed',

        // Settings
        MW_TOLERANCE_CHANGED: 'mw:tolerance:changed',

        // Trace visibility
        TRACE_VISIBILITY_CHANGED: 'trace:visibility:changed',

        // Export
        EXPORT_STARTED: 'export:started',
        EXPORT_COMPLETED: 'export:completed',
    };

    /**
     * Sample colors for visual differentiation.
     */
    const SAMPLE_COLORS = [
        '#2196F3',  // Blue
        '#4CAF50',  // Green
        '#FF9800',  // Orange
        '#9C27B0',  // Purple
    ];

    /**
     * SampleComparisonState Class
     */
    class SampleComparisonState {
        /**
         * @param {EventBus} eventBus - EventBus instance for communication
         */
        constructor(eventBus) {
            this.eventBus = eventBus;

            // Sample data: Map<sampleId, SampleData>
            // SampleData = { sample, lane, bands, profile, color, densitometry }
            this.samples = new Map();

            // Display order: array of sampleId strings
            this.sampleOrder = [];

            // All bands across samples: Map<bandId, BandData>
            this.bands = new Map();

            // Profiles cache: Map<laneId, ProfileData>
            this.profiles = new Map();

            // Selection state
            this.selectedSampleId = null;
            this.selectedBandId = null;

            // View settings
            this.poiOnlyMode = false;  // true = show only POI bands, false = show all bands
            this.scaleMode = 'normalized';  // 'normalized' or 'absolute'
            this.digitalLaneMode = 'bands';  // 'bands' or 'pseudo-gel'

            // MW-aligned electropherogram settings
            this.xAxisMode = 'mw';  // 'mw' (log scale, MW-aligned) or 'position' (pixel Y position)
            this.normalizationMode = 'raw';  // 'raw', 'total', 'max_peak', 'reference'
            this.mwTolerance = 5;  // % tolerance for band matching across samples
            this.referenceBandId = null;  // Band ID for 'reference' normalization

            // Trace visibility: Map<sampleId, boolean>
            this.traceVisibility = new Map();

            // No limit on samples - users can add as many as needed
        }

        // =====================================================================
        // Trace Visibility
        // =====================================================================

        /**
         * Check if a trace is visible.
         * @param {number|string} sampleId - Sample ID
         * @returns {boolean} True if visible (default true if not set)
         */
        isTraceVisible(sampleId) {
            // Default to visible if not explicitly set
            if (!this.traceVisibility.has(sampleId)) {
                return true;
            }
            return this.traceVisibility.get(sampleId);
        }

        /**
         * Set trace visibility for a sample.
         * @param {number|string} sampleId - Sample ID
         * @param {boolean} visible - Whether trace should be visible
         */
        setTraceVisibility(sampleId, visible) {
            this.traceVisibility.set(sampleId, visible);
            this.eventBus.emit(ComparisonEvents.TRACE_VISIBILITY_CHANGED, {
                sampleId,
                visible,
            });
        }

        /**
         * Toggle trace visibility for a sample.
         * @param {number|string} sampleId - Sample ID
         * @returns {boolean} New visibility state
         */
        toggleTraceVisibility(sampleId) {
            const currentVisible = this.isTraceVisible(sampleId);
            const newVisible = !currentVisible;
            this.setTraceVisibility(sampleId, newVisible);
            return newVisible;
        }

        // =====================================================================
        // Sample Management
        // =====================================================================

        /**
         * Add a sample to the comparison.
         * @param {Object} data - Sample data object
         * @param {Object} data.sample - ProcessSample info
         * @param {Object} data.lane - Lane data
         * @param {Array} data.bands - Band array
         * @param {Object} data.profile - Profile data (optional)
         * @param {Object} data.mw_profile - MW-aligned profile data (optional)
         * @param {Object} data.calibration - Calibration data for MW estimation
         * @param {Object} data.lane_geometry - Lane geometry (top, bottom)
         * @param {Object} data.densitometry - Lane densitometry summary
         * @param {string} data.image_url - Gel image URL
         * @param {Object} data.analysis - Analysis info
         * @returns {boolean} True if added successfully
         */
        addSample(data) {
            // Use data.id as the unique identifier - it's always present
            // Format: "lane_{id}" for standalone lanes, "process_sample_{id}" for linked samples
            const sampleId = data.id || (data.sample?.id ? `process_sample_${data.sample.id}` : `lane_${data.lane?.id}`);

            console.log('[SampleComparisonState] addSample called with:', {
                sampleId: sampleId,
                source: data.source,
                label: data.label,
                image_url: data.image_url,
                hasLane: !!data.lane,
                hasBands: !!data.bands,
                hasSample: !!data.sample,
            });

            if (this.samples.has(sampleId)) {
                console.warn('[SampleComparisonState] Sample already exists:', sampleId);
                return false;
            }

            // Assign color based on index
            const colorIndex = this.samples.size;
            const color = SAMPLE_COLORS[colorIndex % SAMPLE_COLORS.length];

            // Store sample data with unique ID and label for display
            const sampleData = {
                sampleId: sampleId,  // Unique identifier (lane_X or process_sample_X)
                source: data.source || 'lane',  // 'lane' or 'process_sample'
                label: data.label || (data.sample?.sample_id || `Lane ${data.lane?.lane_number || data.lane?.id}`),
                sample: data.sample,  // ProcessSample info (may be null for standalone lanes)
                lane: data.lane,
                bands: data.bands || [],
                profile: data.profile || null,
                mw_profile: data.mw_profile || null,  // MW-aligned profile with mw_values
                calibration: data.calibration || null,  // Calibration coefficients
                lane_geometry: data.lane_geometry || null,  // Lane top/bottom for Rf calculation
                densitometry: data.densitometry || null,
                image_url: data.image_url || null,  // Gel image URL
                analysis: data.analysis || null,  // Analysis info
                color: color,
                colorIndex: colorIndex,
            };

            this.samples.set(sampleId, sampleData);
            this.sampleOrder.push(sampleId);

            // Index bands
            if (data.bands) {
                data.bands.forEach(band => {
                    this.bands.set(band.id, {
                        ...band,
                        sampleId: sampleId,
                        sampleColor: color,
                    });
                });
            }

            // Cache profile
            if (data.profile && data.lane) {
                this.profiles.set(data.lane.id, data.profile);
            }

            // Select first sample if none selected
            if (this.selectedSampleId === null) {
                this.selectedSampleId = sampleId;
            }

            this.eventBus.emit(ComparisonEvents.SAMPLE_ADDED, {
                sampleId,
                sampleData,
                totalSamples: this.samples.size,
            });

            return true;
        }

        /**
         * Remove a sample from the comparison.
         * @param {number|string} sampleId - Sample ID to remove
         */
        removeSample(sampleId) {
            const sampleData = this.samples.get(sampleId);
            if (!sampleData) return;

            // Remove associated bands
            if (sampleData.bands) {
                sampleData.bands.forEach(band => {
                    this.bands.delete(band.id);
                });
            }

            // Remove profile
            if (sampleData.lane) {
                this.profiles.delete(sampleData.lane.id);
            }

            this.samples.delete(sampleId);
            this.sampleOrder = this.sampleOrder.filter(id => id !== sampleId);

            // Clear selection if removed sample was selected
            if (this.selectedSampleId === sampleId) {
                this.selectedSampleId = this.samples.size > 0
                    ? this.samples.keys().next().value
                    : null;
            }

            // Reassign colors to remaining samples
            this._reassignColors();

            this.eventBus.emit(ComparisonEvents.SAMPLE_REMOVED, {
                sampleId,
                totalSamples: this.samples.size,
            });
        }

        /**
         * Reassign colors based on display order (sampleOrder).
         * @private
         */
        _reassignColors() {
            this.sampleOrder.forEach((sampleId, index) => {
                const sampleData = this.samples.get(sampleId);
                if (!sampleData) return;

                const newColor = SAMPLE_COLORS[index % SAMPLE_COLORS.length];
                sampleData.color = newColor;
                sampleData.colorIndex = index;

                // Update bands with new color
                if (sampleData.bands) {
                    sampleData.bands.forEach(band => {
                        const bandData = this.bands.get(band.id);
                        if (bandData) {
                            bandData.sampleColor = newColor;
                        }
                    });
                }
            });
        }

        // =====================================================================
        // Selection
        // =====================================================================

        /**
         * Select a sample.
         * @param {number|string} sampleId - Sample ID
         */
        selectSample(sampleId) {
            console.log('[SampleComparisonState] selectSample called with:', sampleId, 'type:', typeof sampleId);
            console.log('[SampleComparisonState] Available sample keys:', Array.from(this.samples.keys()));

            if (!this.samples.has(sampleId)) {
                console.warn('[SampleComparisonState] Sample not found:', sampleId);
                return;
            }

            this.selectedSampleId = sampleId;
            const sampleData = this.samples.get(sampleId);
            console.log('[SampleComparisonState] Emitting SAMPLE_SELECTED, image_url:', sampleData?.image_url);

            this.eventBus.emit(ComparisonEvents.SAMPLE_SELECTED, {
                sampleId,
                sample: sampleData,
            });
        }

        /**
         * Select a band.
         * @param {string} bandId - Band ID
         */
        selectBand(bandId) {
            const band = this.bands.get(bandId);
            this.selectedBandId = bandId;

            // Also select the parent sample and notify panels
            if (band && band.sampleId) {
                this.selectedSampleId = band.sampleId;
                const sampleData = this.samples.get(band.sampleId);
                this.eventBus.emit(ComparisonEvents.SAMPLE_SELECTED, {
                    sampleId: band.sampleId,
                    sample: sampleData,
                });
            }

            this.eventBus.emit(ComparisonEvents.BAND_SELECTED, {
                bandId,
                band,
                sampleId: band?.sampleId,
            });
        }

        /**
         * Clear all selections.
         */
        clearSelection() {
            this.selectedBandId = null;
            this.eventBus.emit(ComparisonEvents.BAND_SELECTED, {
                bandId: null,
                band: null,
            });
        }

        // =====================================================================
        // Data Access
        // =====================================================================

        /**
         * Get all samples as array.
         * @returns {Array} Array of sample data objects
         */
        getSamples() {
            return this.sampleOrder.map(id => this.samples.get(id)).filter(Boolean);
        }

        /**
         * Reorder samples to match the given order.
         * @param {Array<string>} newOrder - Array of sampleId strings in desired order
         */
        reorderSamples(newOrder) {
            // Validate: must contain the same IDs
            const currentIds = new Set(this.sampleOrder);
            const validOrder = newOrder.filter(id => currentIds.has(id));
            if (validOrder.length !== this.sampleOrder.length) {
                console.warn('[SampleComparisonState] reorderSamples: ID mismatch, ignoring');
                return;
            }

            this.sampleOrder = validOrder;
            this._reassignColors();

            this.eventBus.emit(ComparisonEvents.SAMPLE_ORDER_CHANGED, {
                sampleOrder: this.sampleOrder,
            });
        }

        /**
         * Get a specific sample.
         * @param {number|string} sampleId - Sample ID
         * @returns {Object|undefined} Sample data or undefined
         */
        getSample(sampleId) {
            return this.samples.get(sampleId);
        }

        /**
         * Get all bands across all samples.
         * @returns {Array} Array of band objects with sampleId and sampleColor
         */
        getAllBands() {
            return Array.from(this.bands.values());
        }

        /**
         * Get bands for a specific sample.
         * @param {number|string} sampleId - Sample ID
         * @returns {Array} Array of band objects
         */
        getBandsForSample(sampleId) {
            const sampleData = this.samples.get(sampleId);
            return sampleData?.bands || [];
        }

        /**
         * Get bands for a specific lane (for compatibility with densitometry panels).
         * @param {number} laneId - Lane ID
         * @returns {Array} Array of band objects
         */
        getBandsForLane(laneId) {
            for (const sampleData of this.samples.values()) {
                if (sampleData.lane && sampleData.lane.id === laneId) {
                    return sampleData.bands || [];
                }
            }
            return [];
        }

        /**
         * Get lane by ID (for compatibility with densitometry panels).
         * @param {number} laneId - Lane ID
         * @returns {Object|null} Lane object or null
         */
        getLane(laneId) {
            for (const sampleData of this.samples.values()) {
                if (sampleData.lane && sampleData.lane.id === laneId) {
                    return sampleData.lane;
                }
            }
            return null;
        }

        /**
         * Get all profiles for overlay view.
         * @returns {Array} Array of { sampleId, sampleName, profile, mw_profile, calibration, color }
         */
        getAllProfiles() {
            return this.getSamples()
                .filter(s => s.profile)
                .map(s => ({
                    // Use stored sampleId (the unique key) - sample may be null for standalone lanes
                    sampleId: s.sampleId,
                    // Use label for display name - it handles both linked and standalone cases
                    sampleName: s.label || s.sample?.sample_id || `Lane ${s.lane?.lane_number || s.lane?.id}`,
                    laneId: s.lane?.id,
                    profile: s.profile,
                    mw_profile: s.mw_profile,  // MW-aligned profile data
                    calibration: s.calibration,  // Calibration info
                    lane_geometry: s.lane_geometry,  // Lane top/bottom
                    color: s.color,
                }));
        }

        /**
         * Get profile for a lane (for compatibility with densitometry panels).
         * @param {number} laneId - Lane ID
         * @returns {Object|null} Profile data or null
         */
        getProfile(laneId) {
            return this.profiles.get(laneId) || null;
        }

        /**
         * Store profile for a lane.
         * @param {number} laneId - Lane ID
         * @param {Object} profile - Profile data
         */
        setProfile(laneId, profile) {
            this.profiles.set(laneId, profile);

            // Update sample data if found
            for (const sampleData of this.samples.values()) {
                if (sampleData.lane && sampleData.lane.id === laneId) {
                    sampleData.profile = profile;
                    break;
                }
            }

            this.eventBus.emit(ComparisonEvents.PROFILE_LOADED, {
                laneId,
                profile,
            });
        }

        /**
         * Get a specific band.
         * @param {string} bandId - Band ID
         * @returns {Object|undefined} Band data or undefined
         */
        getBand(bandId) {
            return this.bands.get(bandId);
        }

        // =====================================================================
        // View Settings
        // =====================================================================

        /**
         * Set POI-only mode for peak markers.
         * @param {boolean} enabled - True to show only POI bands, false for all bands
         */
        setPoiOnlyMode(enabled) {
            this.poiOnlyMode = enabled;
            this.eventBus.emit(ComparisonEvents.POI_ONLY_MODE_CHANGED, { enabled });
        }

        /**
         * Check if POI-only mode is enabled.
         * @returns {boolean} True if only POI bands should be shown
         */
        isPoiOnlyMode() {
            return this.poiOnlyMode;
        }

        /**
         * Set scale mode.
         * @param {string} mode - 'normalized' or 'absolute'
         */
        setScaleMode(mode) {
            this.scaleMode = mode;
            this.eventBus.emit(ComparisonEvents.SCALE_MODE_CHANGED, { mode });
        }

        /**
         * Set digital lane display mode.
         * @param {string} mode - 'bands' or 'pseudo-gel'
         */
        setDigitalLaneMode(mode) {
            this.digitalLaneMode = mode;
            this.eventBus.emit(ComparisonEvents.DIGITAL_LANE_MODE_CHANGED, { mode });
        }

        /**
         * Set X-axis mode for electropherogram.
         * @param {string} mode - 'mw' (molecular weight, log scale) or 'position' (Y pixel position)
         */
        setXAxisMode(mode) {
            this.xAxisMode = mode;
            this.eventBus.emit(ComparisonEvents.X_AXIS_MODE_CHANGED, { mode });
        }

        /**
         * Set normalization mode for intensity values.
         * @param {string} mode - 'raw', 'total', 'max_peak', or 'reference'
         */
        setNormalizationMode(mode) {
            this.normalizationMode = mode;
            this.eventBus.emit(ComparisonEvents.NORMALIZATION_MODE_CHANGED, { mode });
        }

        /**
         * Set MW tolerance for band matching.
         * @param {number} tolerance - Percentage tolerance (e.g., 5 for 5%)
         */
        setMwTolerance(tolerance) {
            this.mwTolerance = Math.max(1, Math.min(20, tolerance));
            this.eventBus.emit(ComparisonEvents.MW_TOLERANCE_CHANGED, { tolerance: this.mwTolerance });
        }

        /**
         * Set reference band for normalization.
         * @param {string} bandId - Band ID to use as reference
         */
        setReferenceBand(bandId) {
            this.referenceBandId = bandId;
            if (this.normalizationMode === 'reference') {
                this.eventBus.emit(ComparisonEvents.NORMALIZATION_MODE_CHANGED, {
                    mode: 'reference',
                    referenceBandId: bandId,
                });
            }
        }

        // =====================================================================
        // Utilities
        // =====================================================================

        /**
         * Check if more samples can be added.
         * @returns {boolean} Always true - no limit on samples
         */
        canAddMore() {
            return true;
        }

        /**
         * Get summary statistics for comparison.
         * @returns {Object} Summary with counts and ranges
         */
        getSummary() {
            const samples = this.getSamples();

            const purities = samples
                .filter(s => s.densitometry?.poi_percentage != null)
                .map(s => s.densitometry.poi_percentage);

            return {
                sampleCount: samples.length,
                totalBands: this.bands.size,
                poiBandCount: Array.from(this.bands.values())
                    .filter(b => b.band_type === 'POI').length,
                purityRange: purities.length > 0 ? {
                    min: Math.min(...purities),
                    max: Math.max(...purities),
                    avg: purities.reduce((a, b) => a + b, 0) / purities.length,
                } : null,
            };
        }

        /**
         * Clear all data.
         */
        clear() {
            this.samples.clear();
            this.sampleOrder = [];
            this.bands.clear();
            this.profiles.clear();
            this.traceVisibility.clear();
            this.selectedSampleId = null;
            this.selectedBandId = null;
        }
    }

    // Export to namespace
    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.State = SampleComparisonState;
    global.SampleComparison.Events = ComparisonEvents;
    global.SampleComparison.Colors = SAMPLE_COLORS;

})(window);
