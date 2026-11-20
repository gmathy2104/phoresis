/**
 * Densitometry State Management
 *
 * Centralized state store for the densitometry module.
 * Manages lanes, bands, profiles, and densitometry results.
 */

(function(global) {
    'use strict';

    const Events = global.Densitometry.Events;

    /**
     * DensitometryState Class
     * Manages all state for the densitometry module.
     */
    class DensitometryState {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus
         * @param {string} options.analysisId
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.analysisId = options.analysisId;

            // Data state
            this.lanes = new Map();  // lane_id -> lane data
            this.bands = new Map();  // band_id -> band data
            this.profiles = new Map();  // lane_id -> profile data
            this.results = null;  // Full analysis result

            // Detected peaks state (from auto-detection)
            this.detectedPeaks = new Map();  // lane_id -> array of detected peaks

            // Selection state
            this.selectedLaneId = null;
            this.selectedBandId = null;

            // UI state
            this.isLoading = false;
            this.hasResults = false;

            // Analysis parameters
            this.params = {
                gaussian_fit_enabled: true,
                background_method: 'rolling_ball',
                normalization_method: 'lane_total',
                smoothing_window: 11,
                profile_width_percent: 50.0,
            };

            // Calibration data (analysis-level, shared across lanes)
            this.calibrationData = null;

            // Peak detection parameters
            this.peakDetectionParams = {
                sensitivity: 0.85,
                min_peak_distance: 10,
                match_tolerance_px: 15,
                enable_deconvolution: false,
            };

            // Western readout (spec §4.4). Computed by the server
            // (readout_publisher.lane_readouts, the publisher's own values):
            // this module only stores and displays it.
            this.readoutAssay = null;                // {id, name, readout} | null
            this.readoutReferenceLaneId = null;      // anti-HCP reference lane id | null
            this.readoutReferenceLaneNumber = null;
            this.readouts = [];                      // lane entries; null = the server could not compute them
            this.readoutsLoaded = false;             // false until the first densitometry fetch
            // services/analysis_detail.py::summary_payload, rendered at load then refreshed with the readouts.
            this.pageSummary = options.pageSummary || null;
            this.canWrite = false;
            this.isEditable = false;
        }

        // =====================================================================
        // Western readout
        // =====================================================================

        /**
         * Store the readout block of a densitometry payload (or of the page
         * config) and emit READOUTS_UPDATED. Only the keys present are
         * updated, so a POST response carrying just the reference can be
         * applied before the re-fetch lands.
         */
        setReadouts(payload) {
            if (!payload) return;
            if ('assay' in payload) this.readoutAssay = payload.assay || null;
            if ('readout_reference_lane_id' in payload) {
                this.readoutReferenceLaneId = payload.readout_reference_lane_id ?? null;
            }
            if ('reference_lane_number' in payload) {
                this.readoutReferenceLaneNumber = payload.reference_lane_number ?? null;
            }
            if ('can_write' in payload) this.canWrite = payload.can_write === true;
            if ('is_editable' in payload) this.isEditable = payload.is_editable === true;
            if ('readouts' in payload) {
                this.readouts = payload.readouts;  // null kept: the panel says so
                this.readoutsLoaded = true;
            }
            this.eventBus.emit(Events.READOUTS_UPDATED, {
                assay: this.readoutAssay,
                referenceLaneId: this.readoutReferenceLaneId,
                readouts: this.readouts,
            });
            // The page summary (services/analysis_detail.py::summary_payload) rides on the same GET: every
            // path that refreshes the readouts (a run, a reference change, a quantification save) refreshes it.
            if (payload.page_summary) this.setPageSummary(payload.page_summary);
        }

        /** The summary strip's and the Lanes view's payload (server-built; the page never computes it). */
        setPageSummary(summary) {
            if (!summary) return;
            this.pageSummary = summary;
            this.eventBus.emit(Events.PAGE_SUMMARY_UPDATED, summary);
        }

        /**
         * The anti-HCP reference lane id (a number), or null when there is
         * none or the assay is not an anti-HCP western.
         */
        getHcpReferenceLaneId() {
            if (this.readoutAssay?.readout !== 'HOST_CELL_PROTEINS') return null;
            if (this.readoutReferenceLaneId === null || this.readoutReferenceLaneId === undefined) return null;
            return Number(this.readoutReferenceLaneId);
        }

        // =====================================================================
        // Data Management
        // =====================================================================

        /**
         * Load initial data.
         */
        loadData(data) {
            // Clear existing
            this.lanes.clear();
            this.bands.clear();

            // Load lanes
            if (data.lanes) {
                data.lanes.forEach(lane => {
                    this.lanes.set(lane.id, lane);
                });
            }

            // Load bands
            if (data.bands) {
                data.bands.forEach(band => {
                    this.bands.set(band.id, band);
                });
            }

            this.eventBus.emit(Events.DATA_LOADED, {
                laneCount: this.lanes.size,
                bandCount: this.bands.size,
            });
        }

        /**
         * Load densitometry results.
         */
        loadResults(results) {
            this.results = results;
            this.hasResults = true;

            // A band's western role (services/readouts.py::band_roles) comes with its result; a band the
            // payload no longer carries (never integrated, wiped by an edit) has none.
            this.bands.forEach(band => {
                band.role = null;
            });

            // Update lane data with densitometry
            if (results.lanes) {
                results.lanes.forEach(laneResult => {
                    const lane = this.lanes.get(laneResult.lane_id);
                    if (lane) {
                        lane.densitometry = laneResult;
                    }

                    // Store profile data
                    if (laneResult.profile_data) {
                        this.profiles.set(laneResult.lane_id, laneResult.profile_data);
                    }

                    // Update bands with densitometry results
                    if (laneResult.bands) {
                        laneResult.bands.forEach(bandResult => {
                            const band = this.bands.get(bandResult.band_id);
                            if (band) {
                                band.densitometry = bandResult;
                                band.role = bandResult.role ?? null;
                                // Sync bbox to the band top-level so the
                                // chromatogram render (chromatogram-utils
                                // calculateBandBounds reads band.bbox_y /
                                // band.bbox_height) stays in lock-step with
                                // whatever the densito server just integrated.
                                // Without this, an edit-without-page-reload
                                // leaves the JS bbox stale even though the
                                // server-side integration used the new values.
                                if (bandResult.bbox_y != null) {
                                    band.bbox_y = bandResult.bbox_y;
                                }
                                if (bandResult.bbox_height != null) {
                                    band.bbox_height = bandResult.bbox_height;
                                }
                            }
                        });
                    }
                });
            }

            this.eventBus.emit(Events.DATA_UPDATED, results);
        }

        /**
         * Get lane by ID.
         */
        getLane(laneId) {
            return this.lanes.get(laneId);
        }

        /**
         * Get band by ID.
         */
        getBand(bandId) {
            return this.bands.get(bandId);
        }

        /**
         * Get profile for a lane.
         */
        getProfile(laneId) {
            return this.profiles.get(laneId);
        }

        /**
         * Get bands for a lane.
         */
        getBandsForLane(laneId) {
            return Array.from(this.bands.values())
                .filter(band => band.lane_id === laneId)
                .sort((a, b) => a.position_y - b.position_y);
        }

        /**
         * Get all lanes sorted by lane number.
         */
        getAllLanes() {
            return Array.from(this.lanes.values())
                .sort((a, b) => a.lane_number - b.lane_number);
        }

        /**
         * Get all bands sorted by lane and position.
         */
        getAllBands() {
            return Array.from(this.bands.values())
                .sort((a, b) => {
                    if (a.lane_number !== b.lane_number) {
                        return a.lane_number - b.lane_number;
                    }
                    return a.position_y - b.position_y;
                });
        }

        // =====================================================================
        // Selection Management
        // =====================================================================

        /**
         * Select a lane.
         */
        selectLane(laneId) {
            const previousLaneId = this.selectedLaneId;
            this.selectedLaneId = laneId;

            // Clear band selection if changing lanes
            if (previousLaneId !== laneId) {
                this.selectedBandId = null;
            }

            this.eventBus.emit(Events.LANE_SELECTED, {
                laneId,
                previousLaneId,
                lane: this.getLane(laneId),
            });
        }

        /**
         * Select a band.
         */
        selectBand(bandId) {
            const previousBandId = this.selectedBandId;
            this.selectedBandId = bandId;

            const band = this.getBand(bandId);
            if (band && band.lane_id !== this.selectedLaneId) {
                this.selectLane(band.lane_id);
            }

            this.eventBus.emit(Events.BAND_SELECTED, {
                bandId,
                previousBandId,
                band: this.getBand(bandId),
            });
        }

        /**
         * Clear selection.
         */
        clearSelection() {
            this.selectedLaneId = null;
            this.selectedBandId = null;
            this.eventBus.emit(Events.LANE_SELECTED, { laneId: null });
            this.eventBus.emit(Events.BAND_SELECTED, { bandId: null });
        }

        /**
         * Get selected lane.
         */
        getSelectedLane() {
            return this.selectedLaneId ? this.getLane(this.selectedLaneId) : null;
        }

        /**
         * Get selected band.
         */
        getSelectedBand() {
            return this.selectedBandId ? this.getBand(this.selectedBandId) : null;
        }

        // =====================================================================
        // Parameters
        // =====================================================================

        /**
         * Update analysis parameters.
         */
        setParams(newParams) {
            this.params = { ...this.params, ...newParams };
            this.eventBus.emit(Events.PARAMS_CHANGED, this.params);
        }

        /**
         * Get current parameters.
         */
        getParams() {
            return { ...this.params };
        }

        // =====================================================================
        // Summary Statistics
        // =====================================================================

        /**
         * Get summary statistics for the gel.
         */
        getSummary() {
            if (!this.results) {
                return {
                    laneCount: this.lanes.size,
                    bandCount: this.bands.size,
                    hasResults: false,
                };
            }

            return {
                laneCount: this.lanes.size,
                bandCount: this.bands.size,
                hasResults: true,
                gelTotalArea: this.results.gel_total_area,
                averagePurity: this.results.average_poi_percentage,
                lanesProcessed: this.results.lanes_processed,
                totalBands: this.results.total_bands,
            };
        }

        /**
         * Get POI bands.
         */
        getPOIBands() {
            return Array.from(this.bands.values())
                .filter(band => band.band_type === 'POI');
        }

        // =====================================================================
        // Detected Peaks Management
        // =====================================================================

        /**
         * Store detected peaks for a lane.
         * @param {number} laneId - Lane ID
         * @param {Array} peaks - Array of detected peaks
         */
        setDetectedPeaks(laneId, peaks) {
            const peaksArray = peaks || [];
            this.detectedPeaks.set(laneId, peaksArray);
            this.eventBus.emit(Events.PEAKS_DETECTED, {
                laneId,
                peaks: peaksArray,
                orphanCount: peaksArray.filter(p => p.is_orphan).length,
                matchedCount: peaksArray.filter(p => !p.is_orphan).length,
            });
        }

        /**
         * Get detected peaks for a lane.
         * @param {number} laneId - Lane ID
         * @returns {Array} Array of detected peaks
         */
        getDetectedPeaks(laneId) {
            return this.detectedPeaks.get(laneId) || [];
        }

        /**
         * Get orphan peaks (peaks without matching bands) for a lane.
         * @param {number} laneId - Lane ID
         * @returns {Array} Array of orphan peaks
         */
        getOrphanPeaks(laneId) {
            const peaks = this.detectedPeaks.get(laneId) || [];
            return peaks.filter(p => p.is_orphan);
        }

        /**
         * Clear detected peaks for a lane.
         * @param {number} laneId - Lane ID
         */
        clearDetectedPeaks(laneId) {
            if (laneId) {
                this.detectedPeaks.delete(laneId);
            } else {
                this.detectedPeaks.clear();
            }
        }

        /**
         * Add a band (after creating from peak).
         * @param {Object} band - Band data
         */
        addBand(band) {
            this.bands.set(band.id, band);
            this.eventBus.emit(Events.BANDS_CREATED, { bands: [band] });
        }

        /**
         * Add multiple bands (after bulk creation).
         * @param {Array} bands - Array of band data
         */
        addBands(bands) {
            bands.forEach(band => {
                this.bands.set(band.id, band);
            });
            this.eventBus.emit(Events.BANDS_CREATED, { bands });
        }

        /**
         * Update peak detection parameters.
         * @param {Object} newParams - New detection parameters
         */
        setPeakDetectionParams(newParams) {
            this.peakDetectionParams = { ...this.peakDetectionParams, ...newParams };
        }

        /**
         * Get current peak detection parameters.
         * @returns {Object} Peak detection parameters
         */
        getPeakDetectionParams() {
            return { ...this.peakDetectionParams };
        }
    }

    // Export
    global.Densitometry = global.Densitometry || {};
    global.Densitometry.State = DensitometryState;

})(window);
