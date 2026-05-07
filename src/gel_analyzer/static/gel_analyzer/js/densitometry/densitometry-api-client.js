/**
 * Densitometry API Client
 *
 * Handles all API communication for the densitometry module.
 */

(function(global) {
    'use strict';

    /**
     * DensitometryApiClient Class
     */
    class DensitometryApiClient {
        /**
         * @param {Object} options
         * @param {string} options.analysisId
         * @param {string} options.csrfToken
         */
        constructor(options) {
            this.analysisId = options.analysisId;
            this.csrfToken = options.csrfToken;
            this.baseUrl = '/api';
        }

        /**
         * Make a fetch request with standard headers.
         */
        async _fetch(url, options = {}) {
            const defaultOptions = {
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
            };

            const response = await fetch(url, { ...defaultOptions, ...options });

            if (!response.ok) {
                const error = await response.json().catch(() => ({ error: 'Request failed' }));
                throw new Error(error.error || `HTTP ${response.status}`);
            }

            return response.json();
        }

        // =====================================================================
        // Densitometry Analysis
        // =====================================================================

        /**
         * Get existing densitometry results.
         */
        async getDensitometry() {
            return this._fetch(`${this.baseUrl}/analyses/${this.analysisId}/densitometry/`);
        }

        /**
         * Run densitometry analysis (synchronous, preview mode).
         */
        async runDensitometry(params = {}, laneIds = null) {
            const body = { params };
            if (laneIds) body.lane_ids = laneIds;

            return this._fetch(`${this.baseUrl}/analyses/${this.analysisId}/densitometry/run/`, {
                method: 'POST',
                body: JSON.stringify(body),
            });
        }

        /**
         * Start async densitometry analysis (saves to database).
         */
        async runDensitometryAsync(params = {}, laneIds = null) {
            const body = { params };
            if (laneIds) body.lane_ids = laneIds;

            return this._fetch(`${this.baseUrl}/analyses/${this.analysisId}/densitometry/async/`, {
                method: 'POST',
                body: JSON.stringify(body),
            });
        }

        /**
         * Get job status.
         */
        async getJobStatus(jobId) {
            return this._fetch(`${this.baseUrl}/analyses/${this.analysisId}/densitometry/jobs/${jobId}/`);
        }

        /**
         * Poll job until complete.
         */
        async pollJob(jobId, onProgress = null, interval = 1000, maxAttempts = 300) {
            let attempts = 0;

            while (attempts < maxAttempts) {
                const status = await this.getJobStatus(jobId);

                if (onProgress) {
                    onProgress(status);
                }

                if (status.status === 'COMPLETED') {
                    return status;
                }

                if (status.status === 'FAILED') {
                    throw new Error(status.error_message || 'Job failed');
                }

                // Fallback: if Celery says SUCCESS but job status hasn't
                // caught up yet, trust Celery (handles race on mark_completed)
                if (status.celery_status === 'SUCCESS' && status.progress >= 100) {
                    console.warn('[DensitometryApi] Celery SUCCESS but job not COMPLETED — forcing completion');
                    return status;
                }

                await new Promise(resolve => setTimeout(resolve, interval));
                attempts++;
            }

            throw new Error('Job timed out');
        }

        // =====================================================================
        // Lane Data
        // =====================================================================

        /**
         * Get intensity profile for a lane.
         */
        async getLaneProfile(laneId) {
            return this._fetch(`${this.baseUrl}/lanes/${laneId}/profile/`);
        }

        /**
         * Get densitometry summary for a lane.
         */
        async getLaneDensitometry(laneId) {
            return this._fetch(`${this.baseUrl}/lanes/${laneId}/densitometry/`);
        }

        // =====================================================================
        // Band Data
        // =====================================================================

        /**
         * Get densitometry details for a band.
         */
        async getBandDensitometry(bandId) {
            return this._fetch(`${this.baseUrl}/bands/${bandId}/densitometry/`);
        }

        // =====================================================================
        // Export
        // =====================================================================

        /**
         * Export densitometry results to CSV (synchronous, returns download).
         */
        async exportCSV(includeProfile = false) {
            const response = await fetch(
                `${this.baseUrl}/analyses/${this.analysisId}/densitometry/export/`,
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({
                        format: 'csv',
                        include_profile: includeProfile,
                        async: false,
                    }),
                }
            );

            if (!response.ok) {
                const error = await response.json().catch(() => ({ error: 'Export failed' }));
                throw new Error(error.error || `HTTP ${response.status}`);
            }

            // Return blob for download
            return response.blob();
        }

        /**
         * Start async CSV export.
         */
        async exportCSVAsync(includeProfile = false) {
            return this._fetch(`${this.baseUrl}/analyses/${this.analysisId}/densitometry/export/`, {
                method: 'POST',
                body: JSON.stringify({
                    format: 'csv',
                    include_profile: includeProfile,
                    async: true,
                }),
            });
        }

        /**
         * Get export task status.
         */
        async getExportStatus(taskId) {
            return this._fetch(`${this.baseUrl}/analyses/${this.analysisId}/densitometry/export/${taskId}/`);
        }

        // =====================================================================
        // Celery Task Status (generic)
        // =====================================================================

        /**
         * Get Celery task status.
         */
        async getTaskStatus(taskId) {
            return this._fetch(`${this.baseUrl}/tasks/${taskId}/status/`);
        }

        // =====================================================================
        // Peak Detection (Auto-detect from Profile)
        // =====================================================================

        /**
         * Detect peaks in a single lane's intensity profile.
         * @param {number} laneId - Lane ID
         * @param {Object} params - Detection parameters
         * @param {number} matchTolerancePx - Tolerance for matching peaks to bands
         * @returns {Object} Detection result with peaks array
         */
        async detectPeaks(laneId, params = {}, matchTolerancePx = 15) {
            return this._fetch(`${this.baseUrl}/lanes/${laneId}/peaks/detect/`, {
                method: 'POST',
                body: JSON.stringify({
                    params: params,
                    match_tolerance_px: matchTolerancePx,
                }),
            });
        }

        /**
         * Bulk detect peaks and optionally create bands for all lanes.
         * @param {Object} params - Detection parameters
         * @param {number} matchTolerancePx - Tolerance for matching peaks to bands
         * @param {boolean} createBands - Whether to create bands for orphan peaks
         * @param {Array} laneIds - Optional list of lane IDs to process
         * @param {boolean} replaceProfileBands - Whether to delete previous PROFILE bands before creating new ones
         * @returns {Object} Bulk detection result
         */
        async detectAndCreateBands(params = {}, matchTolerancePx = 15, createBands = true, laneIds = null, replaceProfileBands = true) {
            const body = {
                params: params,
                match_tolerance_px: matchTolerancePx,
                create_bands: createBands,
                replace_profile_bands: replaceProfileBands,
            };
            if (laneIds) {
                body.lane_ids = laneIds;
            }

            return this._fetch(`${this.baseUrl}/analyses/${this.analysisId}/peaks/detect-and-create/`, {
                method: 'POST',
                body: JSON.stringify(body),
            });
        }

        /**
         * Create a band from a detected orphan peak.
         * @param {number} laneId - Lane ID
         * @param {number} yPosition - Y position of the peak
         * @param {Object} peakData - Additional peak data (height, width, etc.)
         * @returns {Object} Created band
         */
        async createBandFromPeak(laneId, yPosition, peakData = {}) {
            return this._fetch(`${this.baseUrl}/lanes/${laneId}/bands/`, {
                method: 'POST',
                body: JSON.stringify({
                    position_y: yPosition,
                    position_x: peakData.position_x || null,
                    width: peakData.width || null,
                    height: peakData.height || null,
                    band_type: 'OTHER',  // Default to OTHER, user can change
                    source: 'AUTO_DETECTED',
                }),
            });
        }

        // =====================================================================
        // Protein Quantification (v1 API)
        // =====================================================================
        // The quantification routes live under /api/v1/ (function-based views,
        // see gel_analyzer/api/urls.py). The other endpoints in this client use
        // the unversioned /api/ prefix, so we explicitly prefix /v1 here.

        /**
         * Get the active quantification calibration (or null) for the analysis.
         */
        async getActiveQuantification(analysisId) {
            const id = analysisId || this.analysisId;
            return this._fetch(`${this.baseUrl}/v1/analyses/${id}/quantification/`);
        }

        /**
         * Preview a quantification fit without persisting.
         * @param {string} analysisId
         * @param {Object} body - { method, unit, excluded_band_ids }
         * @returns {Object} fit result (calibration_points, control_points,
         *   sample_projections, r_squared, equation, success, ...)
         */
        async previewQuantification(analysisId, body) {
            const id = analysisId || this.analysisId;
            return this._fetch(`${this.baseUrl}/v1/analyses/${id}/quantification/preview/`, {
                method: 'POST',
                body: JSON.stringify(body || {}),
            });
        }

        /**
         * Save & apply a quantification calibration.
         * @returns {Object} serialized calibration (id, method, unit, ...)
         */
        async saveQuantification(analysisId, body) {
            const id = analysisId || this.analysisId;
            return this._fetch(`${this.baseUrl}/v1/analyses/${id}/quantification/`, {
                method: 'POST',
                body: JSON.stringify(body || {}),
            });
        }
    }

    // Export
    global.Densitometry = global.Densitometry || {};
    global.Densitometry.ApiClient = DensitometryApiClient;

})(window);
