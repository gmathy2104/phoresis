/**
 * APIClient - Server Communication for GelViewer
 *
 * Handles all HTTP requests to the GelAnalyzer API.
 * Pure server communication - no local state management.
 */

(function(global) {
    'use strict';

    /**
     * APIClient Class
     * Manages all server-side CRUD operations.
     */
    class APIClient {
        /**
         * Create an APIClient instance.
         * @param {Object} options - Configuration options
         * @param {string} options.analysisId - UUID of the analysis
         * @param {string} options.csrfToken - CSRF token for API requests
         * @param {EventBus} options.eventBus - EventBus instance for notifications
         */
        constructor(options) {
            this.analysisId = options.analysisId;
            this.imageId = options.imageId;
            this.csrfToken = options.csrfToken;
            this.eventBus = options.eventBus;
        }

        // =====================================================================
        // Load Operations
        // =====================================================================

        /**
         * Load all annotations from the server.
         * @returns {Promise<Object>} Analysis data with lanes and bands
         */
        async loadAnnotations() {
            this.eventBus.emit(GelViewer.Events.DATA_LOADING);

            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/data/`, {
                    headers: { 'Accept': 'application/json' }
                });

                if (!response.ok) {
                    throw new Error('Failed to load annotations');
                }

                const data = await response.json();
                this.eventBus.emit(GelViewer.Events.DATA_LOADED, data);
                return data;

            } catch (error) {
                console.error('Error loading annotations:', error);
                this.eventBus.emit(GelViewer.Events.DATA_ERROR, { error });
                throw error;
            }
        }

        // =====================================================================
        // Lane CRUD Operations
        // =====================================================================

        /**
         * Create a lane on the server.
         * @param {Object} data - Lane data
         * @returns {Promise<number>} Server-assigned lane ID
         */
        async createLane(data) {
            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/lanes/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({
                        // Shape and geometry
                        lane_shape: data.lane_shape || 'RECTANGLE',
                        x: data.x,
                        y: data.y,
                        width: data.width,
                        height: data.height,
                        polygon: data.polygon || null,
                        // Type and sample info
                        lane_type: data.lane_type,
                        sample_name: data.sample_name,
                        notes: data.notes,
                        // Metadata fields
                        is_reduced: data.is_reduced,
                        protein_load_ug: data.protein_load_ug,
                        protein_load_type: data.protein_load_type,
                        process_sample_id: data.process_sample_id,
                        // Detection source (MANUAL or YOLO)
                        detection_source: data.detection_source || 'MANUAL',
                        confidence: data.confidence,
                    }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to create lane');
                }

                const result = await response.json();
                return { id: result.lane.id };

            } catch (error) {
                console.error('Server error creating lane:', error);
                throw error;
            }
        }

        /**
         * Update a lane on the server.
         * @param {number|string} id - Lane ID
         * @param {Object} data - Updated lane data
         */
        async updateLane(id, data) {
            try {
                const response = await fetch(`/api/lanes/${id}/`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(data),
                });

                if (!response.ok) {
                    throw new Error('Failed to update lane');
                }

            } catch (error) {
                console.error('Server error updating lane:', error);
                throw error;
            }
        }

        /**
         * Delete a lane from the server.
         * @param {number|string} id - Lane ID
         */
        async deleteLane(id) {
            try {
                const response = await fetch(`/api/lanes/${id}/`, {
                    method: 'DELETE',
                    headers: { 'X-CSRFToken': this.csrfToken },
                });

                if (!response.ok) {
                    throw new Error('Failed to delete lane');
                }

            } catch (error) {
                console.error('Server error deleting lane:', error);
                throw error;
            }
        }

        /**
         * Create multiple lanes in a single request (bulk creation).
         * Used by YOLO auto-detect to create all accepted lanes at once.
         * @param {Array<Object>} lanes - Array of lane data objects
         * @returns {Promise<Object>} Response with created lanes and count
         */
        async createLanesBulk(lanes) {
            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/lanes/bulk/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({ lanes }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to create lanes');
                }

                return await response.json();

            } catch (error) {
                console.error('Server error bulk creating lanes:', error);
                throw error;
            }
        }

        /**
         * Update multiple lanes in a single request.
         * @param {Array<Object>} lanes - Array of {id, ...fields to update}
         * @returns {Promise<Object>} Response with updated lanes and count
         */
        async updateLanesBulk(lanes) {
            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/lanes/bulk-update/`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({ lanes }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to update lanes');
                }

                return await response.json();

            } catch (error) {
                console.error('Server error bulk updating lanes:', error);
                throw error;
            }
        }

        /**
         * Delete multiple lanes in a single request.
         * @param {Array<number>} laneIds - Array of lane IDs to delete
         * @returns {Promise<Object>} Response with deleted count and remaining lanes
         */
        async deleteLanesBulk(laneIds) {
            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/lanes/bulk-delete/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({ lane_ids: laneIds }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to delete lanes');
                }

                return await response.json();

            } catch (error) {
                console.error('Server error bulk deleting lanes:', error);
                throw error;
            }
        }

        /**
         * Delete ALL lanes for the analysis.
         * @returns {Promise<Object>} Response with deleted count
         */
        async deleteAllLanes() {
            try {
                // Get all lane IDs by loading annotations first
                const data = await this.loadAnnotations();
                const lanes = data.lanes || [];
                if (lanes.length === 0) {
                    return { success: true, deleted_count: 0 };
                }
                const laneIds = lanes.map(l => l.id);
                return await this.deleteLanesBulk(laneIds);
            } catch (error) {
                console.error('Server error deleting all lanes:', error);
                throw error;
            }
        }

        /**
         * Delete ALL bands for the analysis.
         * @returns {Promise<Object>} Response with deleted count
         */
        async deleteAllBands() {
            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/bands/bulk-delete/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({}),  // Empty body = delete all
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to delete bands');
                }

                return await response.json();

            } catch (error) {
                console.error('Server error deleting all bands:', error);
                throw error;
            }
        }

        // =====================================================================
        // Band CRUD Operations
        // =====================================================================

        /**
         * Create a band on the server.
         * @param {number|string} laneId - Parent lane ID
         * @param {Object} data - Band data
         * @returns {Promise<string>} Server-assigned band UUID
         */
        async createBand(laneId, data) {
            try {
                const response = await fetch(`/api/lanes/${laneId}/bands/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({
                        polygon: data.polygon,
                        position_y: data.position_y,
                        band_type: data.band_type,
                        estimated_mw_kda: data.estimated_mw_kda,
                        label: data.label,
                        notes: data.notes,
                    }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to create band');
                }

                const result = await response.json();
                return { id: result.band.id };

            } catch (error) {
                console.error('Server error creating band:', error);
                throw error;
            }
        }

        /**
         * Update a band on the server.
         * @param {string} id - Band ID
         * @param {Object} data - Updated band data
         */
        async updateBand(id, data) {
            try {
                const response = await fetch(`/api/bands/${id}/`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(data),
                });

                if (!response.ok) {
                    throw new Error('Failed to update band');
                }

            } catch (error) {
                console.error('Server error updating band:', error);
                throw error;
            }
        }

        /**
         * Delete a band from the server.
         * @param {string} id - Band ID
         */
        async deleteBand(id) {
            try {
                const response = await fetch(`/api/bands/${id}/`, {
                    method: 'DELETE',
                    headers: { 'X-CSRFToken': this.csrfToken },
                });

                if (!response.ok) {
                    throw new Error('Failed to delete band');
                }

            } catch (error) {
                console.error('Server error deleting band:', error);
                throw error;
            }
        }

        /**
         * Bulk update band polygons after SAM refinement.
         * @param {Array<Object>} updates - Array of {band_id, polygon}
         * @returns {Promise<Object>} Result with updated/failed counts
         */
        async updateBandPolygonsBulk(updates) {
            try {
                const response = await fetch('/api/bands/bulk-update-polygons/', {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({ updates }),
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.error || 'Failed to update band polygons');
                }

                return await response.json();

            } catch (error) {
                console.error('Server error updating band polygons:', error);
                throw error;
            }
        }

        // =====================================================================
        // Sample Search API
        // =====================================================================

        /**
         * Search for process samples.
         * @param {Object} params - Search parameters
         * @param {string} [params.query] - Search query
         * @param {number} [params.drugSubstanceId] - Filter by drug substance
         * @param {number} [params.sheetId] - Filter by process sheet
         * @returns {Promise<Array>} Matching samples
         */
        async searchSamples(params = {}) {
            try {
                const url = new URL('/api/samples/search/', window.location.origin);

                if (params.query) url.searchParams.append('q', params.query);
                if (params.drugSubstanceId) url.searchParams.append('drug_substance', params.drugSubstanceId);
                if (params.sheetId) url.searchParams.append('sheet', params.sheetId);

                const response = await fetch(url.toString(), {
                    headers: { 'Accept': 'application/json' }
                });

                if (!response.ok) {
                    throw new Error('Failed to search samples');
                }

                const data = await response.json();
                return data.samples || [];

            } catch (error) {
                console.error('Error searching samples:', error);
                throw error;
            }
        }

        /**
         * Get filter options for sample search.
         * @returns {Promise<Object>} Filter options (drug substances, sheets)
         */
        async getSampleFilterOptions() {
            try {
                const response = await fetch('/api/samples/filter-options/', {
                    headers: { 'Accept': 'application/json' }
                });

                if (!response.ok) {
                    throw new Error('Failed to get filter options');
                }

                return await response.json();

            } catch (error) {
                console.error('Error getting filter options:', error);
                throw error;
            }
        }

        // =====================================================================
        // YOLO Results API
        // =====================================================================

        /**
         * Save raw YOLO detection results to the analysis.
         * This stores the full detection output before user filtering.
         * @param {Object} results - Detection results
         * @param {Array} results.detections - Array of detection objects
         * @param {string} results.inferred_gel_type - Inferred gel type
         * @returns {Promise<Object>} Save result
         */
        async saveYoloResults(results) {
            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/yolo-results/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({
                        detections: results.detections || [],
                        inferred_gel_type: results.inferred_gel_type || '',
                    }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to save YOLO results');
                }

                return await response.json();

            } catch (error) {
                console.error('Error saving YOLO results:', error);
                throw error;
            }
        }

        // =====================================================================
        // Band Detection API (Auto d1/d2 Derivative)
        // =====================================================================

        /**
         * Get default detection parameters.
         * @returns {Promise<Object>} Default parameters
         */
        async getDetectionParams() {
            try {
                const response = await fetch('/api/detection/params/', {
                    headers: { 'Accept': 'application/json' }
                });

                if (!response.ok) {
                    throw new Error('Failed to get detection parameters');
                }

                return await response.json();

            } catch (error) {
                console.error('Error getting detection params:', error);
                throw error;
            }
        }

        /**
         * Preview band detection for a single lane (no save).
         * @param {number} laneId - Lane ID
         * @param {Object} params - Detection parameters
         * @returns {Promise<Object>} Detection results with bands array
         */
        async previewBandDetection(laneId, params = {}) {
            try {
                const response = await fetch(`/api/lanes/${laneId}/detect-bands/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(params),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to detect bands');
                }

                return await response.json();

            } catch (error) {
                console.error('Error previewing band detection:', error);
                throw error;
            }
        }

        /**
         * Detect and save bands for a single lane.
         * @param {number} laneId - Lane ID
         * @param {Object} params - Detection parameters
         * @returns {Promise<Object>} Detection results with created bands
         */
        async detectAndSaveBands(laneId, params = {}) {
            try {
                const response = await fetch(`/api/lanes/${laneId}/detect-bands/save/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(params),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to save detected bands');
                }

                return await response.json();

            } catch (error) {
                console.error('Error detecting and saving bands:', error);
                throw error;
            }
        }

        /**
         * Start async band detection for multiple lanes (Celery task).
         * @param {Array<number>} laneIds - Array of lane IDs to process
         * @param {Object} params - Detection parameters
         * @returns {Promise<Object>} Task info with task_id for polling
         */
        async detectBandsBulkAsync(laneIds, params = {}) {
            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/detect-bands/async/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({
                        lane_ids: laneIds,
                        params: params,
                        save_results: true,
                    }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to start bulk detection');
                }

                return await response.json();

            } catch (error) {
                console.error('Error starting bulk detection:', error);
                throw error;
            }
        }

        // ---- CV2 Vision Detection ----

        async detectBandsCV2Preview(laneId, params = {}, bgType = null) {
            try {
                const body = { params };
                if (bgType && bgType !== 'auto') body.bg_type = bgType;
                const response = await fetch(`/api/lanes/${laneId}/detect-bands-cv2/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(body),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to preview CV2 band detection');
                }

                return await response.json();

            } catch (error) {
                console.error('Error previewing CV2 band detection:', error);
                throw error;
            }
        }

        async detectBandsCV2Save(laneId, params = {}, deleteExisting = true, bgType = null) {
            try {
                const body = { params, delete_existing: deleteExisting };
                if (bgType && bgType !== 'auto') body.bg_type = bgType;
                const response = await fetch(`/api/lanes/${laneId}/detect-bands-cv2/save/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(body),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to save CV2 detected bands');
                }

                return await response.json();

            } catch (error) {
                console.error('Error saving CV2 detected bands:', error);
                throw error;
            }
        }

        async detectBandsCV2Async(laneIds, params = {}, saveResults = true, bgType = null) {
            try {
                const body = {
                    lane_ids: laneIds,
                    params,
                    save_results: saveResults,
                };
                if (bgType && bgType !== 'auto') body.bg_type = bgType;
                const response = await fetch(`/api/analyses/${this.analysisId}/detect-bands-cv2/async/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(body),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to start async CV2 detection');
                }

                return await response.json();

            } catch (error) {
                console.error('Error starting async CV2 detection:', error);
                throw error;
            }
        }

        async getCV2CalibratedParams() {
            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/detect-bands-cv2/calibrate/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({}),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to get CV2 calibrated params');
                }

                return await response.json();

            } catch (error) {
                console.error('Error getting CV2 calibrated params:', error);
                throw error;
            }
        }

        // ── Hybrid Band Detection ────────────────────────────────────────

        async detectBandsHybridPreview(laneId, params = {}) {
            try {
                const response = await fetch(`/api/lanes/${laneId}/detect-bands-hybrid/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({ params }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || `HTTP ${response.status}`);
                }

                return await response.json();

            } catch (error) {
                console.error('[APIClient] Hybrid preview failed:', error);
                throw error;
            }
        }

        async detectBandsHybridSave(laneId, params = {}, deleteExisting = true) {
            try {
                const response = await fetch(`/api/lanes/${laneId}/detect-bands-hybrid/save/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({ params, delete_existing: deleteExisting }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || `HTTP ${response.status}`);
                }

                return await response.json();

            } catch (error) {
                console.error('[APIClient] Hybrid save failed:', error);
                throw error;
            }
        }

        async detectBandsHybridAsync(laneIds, params = {}, saveResults = true) {
            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/detect-bands-hybrid/async/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({
                        lane_ids: laneIds,
                        params,
                        save_results: saveResults,
                    }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || `HTTP ${response.status}`);
                }

                return await response.json();

            } catch (error) {
                console.error('[APIClient] Hybrid async failed:', error);
                throw error;
            }
        }

        /**
         * Get status of an async task (Celery).
         * @param {string} taskId - Celery task ID
         * @returns {Promise<Object>} Task status and results
         */
        async getTaskStatus(taskId) {
            try {
                const response = await fetch(`/api/tasks/${taskId}/status/`, {
                    headers: { 'Accept': 'application/json' }
                });

                if (!response.ok) {
                    throw new Error('Failed to get task status');
                }

                return await response.json();

            } catch (error) {
                console.error('Error getting task status:', error);
                throw error;
            }
        }

        // =====================================================================
        // MW Calibration API
        // =====================================================================

        /**
         * Get all available ladder templates.
         * @returns {Promise<Object>} Templates grouped by manufacturer
         */
        async getLadderTemplates() {
            try {
                const response = await fetch('/api/ladder-templates/', {
                    headers: { 'Accept': 'application/json' }
                });

                if (!response.ok) {
                    throw new Error('Failed to get ladder templates');
                }

                return await response.json();

            } catch (error) {
                console.error('Error getting ladder templates:', error);
                throw error;
            }
        }

        /**
         * Get the organization's default ladder template.
         * @returns {Promise<Object>} Default template info or {template_id: null}
         */
        async getDefaultLadderTemplate() {
            try {
                const response = await fetch('/api/ladder-templates/default/', {
                    headers: { 'Accept': 'application/json' }
                });

                if (!response.ok) {
                    throw new Error('Failed to get default ladder template');
                }

                return await response.json();

            } catch (error) {
                console.error('Error getting default ladder template:', error);
                throw error;
            }
        }

        /**
         * Get a specific ladder template with band definitions.
         * @param {string} templateId - Template UUID
         * @returns {Promise<Object>} Template with bands
         */
        async getLadderTemplate(templateId) {
            try {
                const response = await fetch(`/api/ladder-templates/${templateId}/`, {
                    headers: { 'Accept': 'application/json' }
                });

                if (!response.ok) {
                    throw new Error('Failed to get ladder template');
                }

                const data = await response.json();
                return data.template;  // Unwrap: API returns {template: {...}}

            } catch (error) {
                console.error('Error getting ladder template:', error);
                throw error;
            }
        }

        /**
         * Match lane bands to a ladder template (preview matching).
         * @param {number} laneId - Lane ID
         * @param {string} templateId - Template UUID
         * @returns {Promise<Object>} Matching result with band assignments
         */
        async matchTemplate(laneId, templateId) {
            try {
                const response = await fetch(`/api/lanes/${laneId}/match-template/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({ template_id: templateId }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to match template');
                }

                return await response.json();

            } catch (error) {
                console.error('Error matching template:', error);
                throw error;
            }
        }

        /**
         * Calibrate a single ladder lane.
         * @param {number} laneId - Ladder lane ID
         * @param {string} templateId - Template UUID
         * @param {string} method - Calibration method (LOG_LINEAR, POLYNOMIAL_2, etc.)
         * @returns {Promise<Object>} Calibration result with coefficients
         */
        async calibrateSingle(laneId, templateId, method = 'LOG_LINEAR') {
            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/calibrate/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({
                        lane_id: laneId,
                        template_id: templateId,
                        method: method,
                    }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to calibrate');
                }

                return await response.json();

            } catch (error) {
                console.error('Error calibrating:', error);
                throw error;
            }
        }

        /**
         * Calibrate all ladder lanes with multi-ladder interpolation.
         * @param {string} templateId - Template UUID
         * @param {string} method - Calibration method
         * @returns {Promise<Object>} Multi-calibration result
         */
        async calibrateMulti(templateId, method = 'LOG_LINEAR') {
            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/calibrate-multi/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({
                        template_id: templateId,
                        method: method,
                    }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to calibrate ladders');
                }

                return await response.json();

            } catch (error) {
                console.error('Error calibrating multi:', error);
                throw error;
            }
        }

        /**
         * Apply single-ladder calibration to all bands.
         * @returns {Promise<Object>} Update statistics
         */
        async applyCalibration() {
            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/apply-calibration/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to apply calibration');
                }

                return await response.json();

            } catch (error) {
                console.error('Error applying calibration:', error);
                throw error;
            }
        }

        /**
         * Apply multi-ladder calibration with position interpolation.
         * @returns {Promise<Object>} Update statistics
         */
        async applyMultiCalibration() {
            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/apply-multi-calibration/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to apply multi-calibration');
                }

                return await response.json();

            } catch (error) {
                console.error('Error applying multi-calibration:', error);
                throw error;
            }
        }

        /**
         * Get current calibration status and data.
         * @returns {Promise<Object>} Calibration info
         */
        async getCalibration() {
            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/calibration/`, {
                    headers: { 'Accept': 'application/json' }
                });

                if (!response.ok) {
                    throw new Error('Failed to get calibration');
                }

                return await response.json();

            } catch (error) {
                console.error('Error getting calibration:', error);
                throw error;
            }
        }

        /**
         * Get multi-ladder calibration status and data.
         * @returns {Promise<Object>} Multi-calibration info
         */
        async getMultiCalibration() {
            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/multi-calibration/`, {
                    headers: { 'Accept': 'application/json' }
                });

                if (!response.ok) {
                    throw new Error('Failed to get multi-calibration');
                }

                return await response.json();

            } catch (error) {
                console.error('Error getting multi-calibration:', error);
                throw error;
            }
        }

        /**
         * Estimate MW for a single band using multi-ladder interpolation.
         * @param {string} bandId - Band UUID
         * @returns {Promise<Object>} MW estimation result
         */
        async estimateBandMW(bandId) {
            try {
                const response = await fetch(`/api/bands/${bandId}/estimate-mw/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to estimate MW');
                }

                return await response.json();

            } catch (error) {
                console.error('Error estimating band MW:', error);
                throw error;
            }
        }

        // =====================================================================
        // UNPLUGGED: Profile Peak Detection API deprecated in favour of Auto (d1/d2) detection
        // =====================================================================

        /**
         * Detect peaks from lane intensity profile.
         * Uses AdvancedPeakDetector for profile-based detection.
         *
         * @param {number} laneId - Lane ID
         * @param {Object} params - Detection parameters
         * @param {number} [params.sensitivity=0.85] - Detection sensitivity (0.5-1.0)
         * @param {number} [params.min_peak_distance=10] - Min distance between peaks (px)
         * @param {number} [params.match_tolerance_px=15] - Tolerance for matching existing bands
         * @param {number} [params.smoothing_window=11] - Smoothing window size
         * @param {boolean} [params.enable_deconvolution=false] - Enable multi-Gaussian fitting
         * @param {boolean} [params.enable_shoulder_detection=true] - Detect shoulder peaks
         * @param {boolean} [params.preview=false] - If true, only preview (no band creation)
         * @returns {Promise<Object>} Detection result with peaks and optional bands_created
         */
        async detectPeaksFromProfile(laneId, params = {}) {
            throw new Error('Profile Peak Detection is unplugged — use Auto (d1/d2) detection instead');
            try {
                const response = await fetch(`/api/lanes/${laneId}/detect-peaks-profile/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(params),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to detect peaks from profile');
                }

                return await response.json();

            } catch (error) {
                console.error('Error detecting peaks from profile:', error);
                throw error;
            }
        }

        /**
         * Start async profile peak detection for multiple lanes.
         *
         * @param {string} analysisId - Analysis UUID
         * @param {Array<number>} laneIds - Array of lane IDs to process
         * @param {Object} params - Detection parameters
         * @returns {Promise<Object>} Object with task_id for status polling
         */
        async detectPeaksProfileAsync(analysisId, laneIds, params = {}) {
            throw new Error('Profile Peak Detection is unplugged — use Auto (d1/d2) detection instead');
            try {
                const response = await fetch(`/api/analyses/${analysisId}/detect-peaks-profile/async/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({
                        lane_ids: laneIds,
                        params: params,
                    }),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to start profile peak detection');
                }

                return await response.json();

            } catch (error) {
                console.error('Error starting async profile peak detection:', error);
                throw error;
            }
        }

        // =====================================================================
        // Lane Profile API (for Electropherogram)
        // =====================================================================

        // =====================================================================
        // Image Crop API
        // =====================================================================

        /**
         * Crop the gel image to a specified region.
         * @param {Object} cropData - Crop coordinates in display-space
         * @param {number} cropData.x - Left edge
         * @param {number} cropData.y - Top edge
         * @param {number} cropData.width - Crop width
         * @param {number} cropData.height - Crop height
         * @returns {Promise<Object>} Result with new width/height
         */
        async cropImage(cropData) {
            try {
                const response = await fetch(`/api/images/${this.imageId}/crop/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(cropData),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to crop image');
                }

                return await response.json();

            } catch (error) {
                console.warn('Crop rejected:', error.message);
                throw error;
            }
        }

        // =====================================================================
        // Band Detection Calibration (Teacher) API
        // =====================================================================

        /**
         * Calibrate band detection parameters from teaching regions.
         * @param {Object} regions - { background, small_band, large_band } region objects
         * @returns {Promise<Object>} { success, derived_params, diagnostics, explanations }
         */
        async calibrateDetection(regions) {
            try {
                const response = await fetch(`/api/analyses/${this.analysisId}/calibrate-detection/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(regions),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to calibrate detection');
                }

                return await response.json();

            } catch (error) {
                console.error('Error calibrating detection:', error);
                throw error;
            }
        }

        // =====================================================================
        // Lane Profile API (for Electropherogram)
        // =====================================================================

        /**
         * Get intensity profile for a lane.
         * Used by ElectropherogramPanel to display the intensity chart.
         *
         * @param {number} laneId - Lane ID
         * @returns {Promise<Object>} Profile data with y_positions, intensities, etc.
         */
        async getLaneProfile(laneId) {
            try {
                const response = await fetch(`/api/lanes/${laneId}/profile/`, {
                    headers: { 'Accept': 'application/json' }
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || 'Failed to get lane profile');
                }

                return await response.json();

            } catch (error) {
                console.error('Error getting lane profile:', error);
                throw error;
            }
        }

        // =====================================================================
        // Cross-Lane Consensus API
        // =====================================================================

        /**
         * Preview cross-lane consensus (dry run, no DB writes).
         * @param {string} analysisId - Analysis UUID
         * @param {Object} params - Consensus parameters
         * @returns {Promise<Object>} Preview result with proposed changes
         */
        async previewCrossLaneConsensus(analysisId, params) {
            const response = await fetch(
                `/analyses/${analysisId}/cross-lane-consensus/`,
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({ params, dry_run: true }),
                }
            );
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.error || `HTTP ${response.status}`);
            }
            return response.json();
        }

        /**
         * Apply cross-lane consensus (persists changes).
         * @param {string} analysisId - Analysis UUID
         * @param {Object} params - Consensus parameters
         * @returns {Promise<Object>} Apply result with run_id for undo
         */
        async applyCrossLaneConsensus(analysisId, params) {
            const response = await fetch(
                `/analyses/${analysisId}/cross-lane-consensus/`,
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({ params, dry_run: false }),
                }
            );
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.error || `HTTP ${response.status}`);
            }
            return response.json();
        }

        /**
         * Undo a previous cross-lane consensus run.
         * @param {string} analysisId - Analysis UUID
         * @param {string} runId - Consensus run ID returned from applyCrossLaneConsensus
         * @returns {Promise<Object>} Undo result
         */
        async undoCrossLaneConsensus(analysisId, runId) {
            const response = await fetch(
                `/analyses/${analysisId}/cross-lane-consensus/?run_id=${encodeURIComponent(runId)}`,
                {
                    method: 'DELETE',
                    headers: { 'X-CSRFToken': this.csrfToken },
                }
            );
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.error || `HTTP ${response.status}`);
            }
            return response.json();
        }
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.APIClient = APIClient;

})(window);
