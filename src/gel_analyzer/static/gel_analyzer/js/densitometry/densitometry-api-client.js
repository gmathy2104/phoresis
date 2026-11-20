/**
 * Densitometry API Client
 *
 * Handles all API communication for the densitometry module.
 */

(function(global) {
    'use strict';

    // Same shared helper used by gel-viewer/api-client.js: extracts a useful
    // message from non-OK fetch responses (DRF detail → field errors → status
    // text → fallback) so toasts/inline errors are actually informative.
    const extractApiError = (global.PhoresisShared && global.PhoresisShared.extractApiError)
        || (async function fallbackExtract(response, fallback) {
            try {
                const body = await response.json();
                if (body && body.detail) return body.detail;
                if (body && body.error) return body.error;
            } catch (_) { /* ignore */ }
            return fallback || `${response.status} ${response.statusText || ''}`.trim();
        });

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
                throw new Error(await extractApiError(response, `HTTP ${response.status}`));
            }

            return response.json();
        }

        /**
         * Fetch variant for endpoints where a 422 carries a meaningful body
         * (domain-level failure, not a transport error). Returns the parsed
         * body on both 2xx AND 422 so callers can branch on `body.success`
         * to render an empty/explanatory state instead of treating 422 as
         * an error. Used by the quantification preview/save endpoints
         * which return `result.to_dict()` with `success: false` and
         * `error_message: ...` when there's nothing to fit yet.
         */
        async _fetchDomain(url, options = {}) {
            const defaultOptions = {
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
            };

            const response = await fetch(url, { ...defaultOptions, ...options });

            if (response.ok || response.status === 422) {
                // Guard against non-JSON bodies (e.g. Django DEBUG=True
                // serves an HTML error page on misconfigured 422 routes;
                // a bare response.json() then throws SyntaxError and the
                // caller can't tell domain failure from transport failure).
                // Synthesize a domain-shaped fallback so the modal's
                // r.success branch still works.
                try {
                    return await response.json();
                } catch (parseErr) {
                    console.warn(
                        `[DensitometryApiClient] Non-JSON ${response.status} body on ${url}:`,
                        parseErr
                    );
                    return {
                        success: false,
                        error_message: `Server returned a non-JSON ${response.status} response. Check the server logs.`,
                    };
                }
            }

            throw new Error(await extractApiError(response, `HTTP ${response.status}`));
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
         * Set (laneId) or clear (null) the anti-HCP reference lane. Same
         * endpoint as the annotation editor's lane menu; the server
         * republishes the readouts. 403 for a reader or a non-editable
         * analysis, 400 for a foreign lane.
         * @returns {Promise<Object>} { reference_lane_id, reference_lane_number, published }
         */
        async setReadoutReferenceLane(laneId) {
            const response = await fetch(`${this.baseUrl}/analyses/${this.analysisId}/readout-reference/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
                body: JSON.stringify({ lane_id: laneId }),
            });
            if (!response.ok) {
                // The endpoint answers {"error": "..."} (json_error): read it
                // first — the shared extractor would print "error: ...".
                let message = null;
                try {
                    const body = await response.clone().json();
                    if (body && typeof body.error === 'string' && body.error.trim()) {
                        message = body.error;
                    }
                } catch (_) { /* not JSON: fall through */ }
                throw new Error(message || await extractApiError(response, `HTTP ${response.status}`));
            }
            return response.json();
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
         * Export the SAVED densitometry to CSV (synchronous, returns download). A refusal -- 409
         * "Run the densitometry first" -- throws with the server's message, which the page shows.
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
                throw new Error(await extractApiError(response, `HTTP ${response.status}`));
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
            // _fetchDomain so a 422 (no points yet / not enough points) comes
            // back as a domain result with success=false instead of throwing
            // — the modal renders the empty state from result.error_message.
            return this._fetchDomain(`${this.baseUrl}/v1/analyses/${id}/quantification/preview/`, {
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
            return this._fetchDomain(`${this.baseUrl}/v1/analyses/${id}/quantification/`, {
                method: 'POST',
                body: JSON.stringify(body || {}),
            });
        }
    }

    // Export
    global.Densitometry = global.Densitometry || {};
    global.Densitometry.ApiClient = DensitometryApiClient;

})(window);
