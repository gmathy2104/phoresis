/**
 * APIClient - Server Communication for GelViewer
 *
 * Handles all HTTP requests to the GelAnalyzer API.
 * Pure server communication - no local state management.
 */

(function(global) {
    'use strict';

    // Shared helper: extracts a useful error message from a non-OK fetch
    // response. Falls back to status + statusText so a 500 HTML page still
    // shows up as "500 Internal Server Error" in the UI instead of the
    // useless `{}` we used to throw.
    const sharedExtractApiError = (global.PhoresisShared && global.PhoresisShared.extractApiError)
        || (async function fallbackExtract(response, fallback) {
            // Defensive fallback for the unlikely case the shared module
            // didn't load — keep behaviour close to the new helper.
            try {
                const body = await response.json();
                if (body && body.detail) return body.detail;
            } catch (_) { /* ignore */ }
            return fallback || `${response.status} ${response.statusText || ''}`.trim();
        });

    // The legacy views answer a refusal as {"error": "..."} (json_error): that message is the one to show, as
    // ds-hub's client reads it. Anything else (DRF's {"detail"}, field errors, an HTML 500) goes to the shared helper.
    async function extractApiError(response, fallback) {
        try {
            const copy = typeof response.clone === 'function' ? response.clone() : response;
            const body = await copy.json();
            if (body && typeof body.error === 'string' && body.error.trim()) return body.error;
        } catch (_) { /* not JSON: the shared helper says what it can */ }
        return sharedExtractApiError(response, fallback);
    }

    // The writes that change what the server reads of the annotations (lanes, bands, MW, the HCP reference, the
    // image): each announces itself once settled (constructor). Previews, estimates and parameter fits are not here.
    const WRITES = [
        'createLane', 'updateLane', 'patchLaneV1', 'deleteLane', 'createLanesBulk', 'updateLanesBulk',
        'deleteLanesBulk', 'deleteAllLanes', 'deleteAllBands', 'createBand', 'updateBand', 'patchBand', 'deleteBand',
        'splitBand', 'updateBandPolygonsBulk', 'setReadoutReferenceLane', 'applyCalibration', 'applyMultiCalibration',
        'applyLadderTemplate', 'detectAndSaveBands', 'detectBandsCV2Save', 'cropImage',
    ];

    // Signed out, a request never reaches its view: @login_required answers 302 to the login page and fetch follows
    // it -- a PUT is replayed there and answered 200 with the page's HTML, a POST becomes a GET of it, 200 again (a
    // DELETE gets 405). `response.ok` alone took that page for a save: the band PUT resolved, the editor dropped the
    // pending change and said "Band updated" (measured on devlocal, 2026-10-13). Every answer now goes through
    // APIClient._request: the login page (the `next=` redirect_to_login adds, whatever LOGIN_URL is) or a 401 (the DRF
    // endpoints) is a SessionExpiredError, and a success that is not JSON fails too -- every endpoint called here
    // answers JSON. The caller fails as on any refusal, so the change stays pending for the next Save.
    const LOG_IN_AGAIN = 'Log in again in another tab and keep this one open: then Save sends the changes still '
        + 'waiting here.';

    class SessionExpiredError extends Error {
        constructor(message, status) {
            super(message);
            this.name = 'SessionExpiredError';
            this.status = status;
        }
    }

    function isLoginPage(url) {
        try {
            return new URL(url).searchParams.has('next');
        } catch (_) {
            return false;
        }
    }

    function isJson(response) {
        return /json/i.test(response.headers.get('content-type') || '');
    }

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
            this._pageCsrfToken = options.csrfToken;
            this.eventBus = options.eventBus;
            this.signedOut = false;  // SESSION_EXPIRED once, until an answer comes through again (SESSION_RESTORED)

            // Every write announces itself once settled (SERVER_WRITTEN): the editor refreshes what the server reads
            // from the annotations -- a band's role, the checks -- whoever wrote (a form, a panel, the batch Save).
            WRITES.forEach((name) => {
                const write = this[name];
                if (typeof write !== 'function') return;
                this[name] = async (...args) => {
                    try {
                        return await write.apply(this, args);
                    } finally {
                        if (this.eventBus) this.eventBus.emit(GelViewer.Events.SERVER_WRITTEN, { method: name });
                    }
                };
            });
        }

        /**
         * The CSRF token the server holds now. A login rotates it (django.contrib.auth.login), so after logging in
         * again in another tab the token the page was rendered with is refused (403, measured 2026-10-13): read the
         * cookie, as Django's AJAX recipe does, the page's token as the fallback (HttpOnly cookie, CSRF_USE_SESSIONS).
         */
        get csrfToken() {
            const cookies = (global.document && global.document.cookie) || '';
            const match = cookies.match(/(?:^|;\s*)csrftoken=([^;]+)/);
            return match ? decodeURIComponent(match[1]) : this._pageCsrfToken;
        }

        /** fetch, then refuse an answer that is not the endpoint's own (see SessionExpiredError above). */
        async _request(url, init) {
            const response = await fetch(url, init);
            const signedOut = response.status === 401 || (response.redirected && isLoginPage(response.url));
            const notData = response.ok && response.status !== 204 && !isJson(response);
            if (!signedOut && !notData) {
                if (this.signedOut) {
                    this.signedOut = false;
                    if (this.eventBus) this.eventBus.emit(GelViewer.Events.SESSION_RESTORED);
                }
                return response;
            }
            // The caller's own message reads "Save failed: <this>"; the notice (GelViewerApp) says what to do.
            const [message, notice] = signedOut
                ? ['you are signed out (session expired) - log in again',
                    `You are signed out (your session expired): nothing reaches the server. ${LOG_IN_AGAIN}`]
                : [`the server answered a web page, not data (HTTP ${response.status}) - log in again`,
                    `The server answered a web page instead of data, so nothing was taken as saved: your session `
                        + `may have expired. ${LOG_IN_AGAIN}`];
            if (!this.signedOut) {
                this.signedOut = true;
                if (this.eventBus) this.eventBus.emit(GelViewer.Events.SESSION_EXPIRED, { message: notice });
            }
            throw new SessionExpiredError(message, response.status);
        }

        // =====================================================================
        // Load Operations
        // =====================================================================

        /**
         * Load all annotations from the server.
         * @param {Object} [opts]
         * @param {boolean} [opts.quiet=false] - No DATA_LOADING / DATA_LOADED: a refresh of the reading only, the
         *   panels that reload on those events stay as they are.
         * @returns {Promise<Object>} Analysis data with lanes and bands
         */
        async loadAnnotations({ quiet = false } = {}) {
            if (!quiet) this.eventBus.emit(GelViewer.Events.DATA_LOADING);

            try {
                const response = await this._request(`/api/analyses/${this.analysisId}/data/`, {
                    headers: { 'Accept': 'application/json' }
                });

                if (!response.ok) {
                    throw new Error('Failed to load annotations');
                }

                const data = await response.json();
                if (!quiet) this.eventBus.emit(GelViewer.Events.DATA_LOADED, data);
                return data;

            } catch (error) {
                console.error('Error loading annotations:', error);
                if (!quiet) this.eventBus.emit(GelViewer.Events.DATA_ERROR, { error });
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
                const response = await this._request(`/api/analyses/${this.analysisId}/lanes/`, {
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
                        loading_volume_ul: data.loading_volume_ul,
                        protein_load_type: data.protein_load_type,
                        // Detection source (MANUAL or YOLO)
                        detection_source: data.detection_source || 'MANUAL',
                        confidence: data.confidence,
                    }),
                });

                if (!response.ok) {
                    throw new Error(await extractApiError(response, 'Failed to create lane'));
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
         * @param {Object} [options]
         * @param {boolean} [options.force] - Pass ?force=true to purge dependent
         *   CALIBRATION points when downgrading the lane type. The v1 endpoint
         *   returns 409 without it.
         */
        async updateLane(id, data, options = {}) {
            try {
                // Use the v1 PATCH endpoint when ?force is required (lane-type
                // downgrade purge); the legacy PUT endpoint at /api/lanes/<id>/
                // does not understand ?force=true. (Phoresis; ds-hub's own path is patchLaneV1.)
                const useV1 = !!options.force;
                const url = useV1 ? `/api/v1/lanes/${id}/?force=true` : `/api/lanes/${id}/`;
                const response = await this._request(url, {
                    method: useV1 ? 'PATCH' : 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(data),
                });

                if (!response.ok) {
                    if (response.status === 409) {
                        // Custom path: 409 carries structured detail used
                        // by the lane-downgrade-confirm flow, so we keep
                        // the raw response body on the Error.
                        const err = await response.json().catch(() => ({}));
                        const e = new Error(err.detail || 'Lane has dependent calibration points');
                        e.status = 409;
                        e.detail = err;
                        throw e;
                    }
                    throw new Error(await extractApiError(response, 'Failed to update lane'));
                }

            } catch (error) {
                console.error('Server error updating lane:', error);
                throw error;
            }
        }

        /**
         * PATCH a lane via the DRF v1 endpoint (LaneViewSet.partial_update).
         *
         * Specifically wires the CALIBRATION/CONTROL → other downgrade
         * safeguard: the backend returns 409 with `dependent_band_ids` when
         * a downgrade would orphan ProteinQuantCalibrationPoint rows. The
         * caller re-fires with `{force: true}` after explicit confirmation
         * to purge those points and re-tag the affected bands.
         *
         *  - 2xx → { ok: true, lane }
         *  - 409 → { ok: false, conflict: true, dependent_band_ids, detail }
         *  - other → throws
         *
         * @param {number|string} id - Lane ID
         * @param {Object} data - Partial payload (e.g. { lane_type: 'OTHER' })
         * @param {Object} [opts]
         * @param {boolean} [opts.force=false] - Append ?force=true to purge
         * @returns {Promise<Object>}
         */
        async patchLaneV1(id, data, opts = {}) {
            const url = opts.force
                ? `/api/v1/lanes/${id}/?force=true`
                : `/api/v1/lanes/${id}/`;
            const response = await this._request(url, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
                body: JSON.stringify(data),
            });
            if (response.status === 409) {
                const payload = await response.json().catch(() => ({}));
                return {
                    ok: false,
                    conflict: true,
                    dependent_band_ids: payload.dependent_band_ids || [],
                    detail: payload.detail || '',
                };
            }
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.detail || err.error || `HTTP ${response.status}`);
            }
            const lane = await response.json().catch(() => null);
            return { ok: true, lane };
        }

        /**
         * Delete a lane from the server.
         * @param {number|string} id - Lane ID
         */
        async deleteLane(id) {
            try {
                const response = await this._request(`/api/lanes/${id}/`, {
                    method: 'DELETE',
                    headers: { 'X-CSRFToken': this.csrfToken },
                });

                // 404 = already gone (e.g. auto-detect rerun wiped it); desired end state.
                if (!response.ok && response.status !== 404) {
                    throw new Error(await extractApiError(response, 'Failed to delete lane'));
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
                const response = await this._request(`/api/analyses/${this.analysisId}/lanes/bulk/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({ lanes }),
                });

                if (!response.ok) {
                    throw new Error(await extractApiError(response, 'Failed to create lanes'));
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
                const url = `/api/analyses/${this.analysisId}/lanes/bulk-update/`;
                const response = await this._request(url, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({ lanes }),
                });

                if (!response.ok) {
                    throw new Error(await extractApiError(response, 'Failed to update lanes'));
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
                const url = `/api/analyses/${this.analysisId}/lanes/bulk-delete/`;
                const response = await this._request(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({ lane_ids: laneIds }),
                });

                if (!response.ok) {
                    throw new Error(await extractApiError(response, 'Failed to delete lanes'));
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
                const url = `/api/analyses/${this.analysisId}/bands/bulk-delete/`;
                const response = await this._request(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify({}),  // Empty body = delete all
                });

                if (!response.ok) {
                    throw new Error(await extractApiError(response, 'Failed to delete bands'));
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
                const response = await this._request(`/api/lanes/${laneId}/bands/`, {
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
                    throw new Error(await extractApiError(response, 'Failed to create band'));
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
                const response = await this._request(`/api/bands/${id}/`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(data),
                });

                if (!response.ok) {
                    throw new Error(await extractApiError(response, 'Failed to update band'));
                }

            } catch (error) {
                console.error('Server error updating band:', error);
                throw error;
            }
        }

        /**
         * PATCH a band via the DRF v1 endpoint (BandSerializer).
         *
         * Used for nested writes that the legacy /api/bands/<id>/ PUT cannot
         * validate — most importantly, the `quant_point` payload that needs
         * the BandSerializer's _validate_band_quant_point + auto-promote
         * + apply_band_type post-save logic (services/quantification/band_type_change.py).
         *
         * @param {string} id - Band ID
         * @param {Object} data - Partial payload, e.g.
         *   { band_type: 'CALIBRATION', quant_point: { load_amount, load_unit } }
         * @returns {Promise<Object>} updated band
         */
        async patchBand(id, data) {
            const extractApiError = (global.PhoresisShared && global.PhoresisShared.extractApiError);
            const response = await this._request(`/api/v1/bands/${id}/`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
                body: JSON.stringify(data),
            });
            if (!response.ok) {
                const message = extractApiError
                    ? await extractApiError(response, 'Failed to PATCH band')
                    : `HTTP ${response.status}`;
                throw new Error(message);
            }
            return response.json();
        }

        /**
         * Set (laneId) or clear (null) the anti-HCP reference lane of the
         * analysis. Saved at once, not with the batch save: the server stores
         * GelAnalysis.readout_reference_lane and republishes the readouts.
         * 403 for a reader or a non-editable analysis, 400 for a foreign lane.
         *
         * @param {number|null} laneId - Server lane id (never a temp id)
         * @returns {Promise<Object>} { reference_lane_id, reference_lane_number, published }
         */
        async setReadoutReferenceLane(laneId) {
            const response = await this._request(`/api/analyses/${this.analysisId}/readout-reference/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
                body: JSON.stringify({ lane_id: laneId }),
            });
            if (!response.ok) {
                // The endpoint answers {"error": "..."} (json_error); the
                // shared extractor covers anything else (HTML 500, proxy...).
                let message = null;
                try {
                    const body = await response.clone().json();
                    if (body && typeof body.error === 'string' && body.error.trim()) {
                        message = body.error;
                    }
                } catch (_) { /* not JSON: fall through */ }
                if (!message) {
                    const extractApiError = (global.PhoresisShared && global.PhoresisShared.extractApiError);
                    message = extractApiError
                        ? await extractApiError(response, 'Failed to set the HCP reference lane')
                        : `HTTP ${response.status}`;
                }
                throw new Error(message);
            }
            return response.json();
        }

        /**
         * Get the active protein quantification calibration for the analysis.
         * Returns { active: { ... } | null }. Used by PropertiesPanel to lock
         * the load_unit select when an active calibration exists.
         */
        async getActiveQuantification(analysisId) {
            const id = analysisId || this.analysisId;
            const response = await this._request(`/api/v1/analyses/${id}/quantification/`, {
                headers: { 'Accept': 'application/json' },
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            return response.json();
        }

        /**
         * Delete a band from the server.
         * @param {string} id - Band ID
         */
        async deleteBand(id) {
            try {
                const response = await this._request(`/api/bands/${id}/`, {
                    method: 'DELETE',
                    headers: { 'X-CSRFToken': this.csrfToken },
                });

                // 404 = already gone (e.g. auto-detect rerun wiped it); desired end state.
                if (!response.ok && response.status !== 404) {
                    throw new Error(await extractApiError(response, 'Failed to delete band'));
                }

            } catch (error) {
                console.error('Server error deleting band:', error);
                throw error;
            }
        }

        /**
         * Split a band into two halves atomically. Sends both pre-computed
         * upper + lower payloads in a single POST; the backend deletes the
         * original + creates the two new bands inside a transaction and
         * returns the new band objects. Replaces the old DELETE → CREATE →
         * CREATE → reload chain (4 roundtrips) with 1.
         * @param {string} bandId - UUID of the band to split
         * @param {Object} payload - { upper: {...}, lower: {...} }
         * @returns {Promise<Object>} { success, deleted_id, upper, lower }
         */
        async splitBand(bandId, payload) {
            try {
                const response = await this._request(`/api/bands/${bandId}/split/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(payload),
                });

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.error || errorData.detail || 'Failed to split band');
                }

                return await response.json();
            } catch (error) {
                console.error('Server error splitting band:', error);
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
                const response = await this._request('/api/bands/bulk-update-polygons/', {
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
                const response = await this._request(`/api/analyses/${this.analysisId}/yolo-results/`, {
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
        // Band Model API (the YOLO band model the browser runs, after the lane model)
        // =====================================================================

        /**
         * The model to run (URL, sha256, settings), the image size, the gel's window in a scanned page,
         * whether the analysis is editable and whether this user may save.
         * @returns {Promise<Object>}
         */
        async getBandModelContext() {
            return this._bandModelRequest('GET', 'band-model/');
        }

        /**
         * The bands each lane would get from the model's boxes. Writes nothing.
         * @param {Object} body - {model_sha256, image: {width, height}, boxes, confidence, lane_ids}
         * @returns {Promise<Object>}
         */
        async previewBandModel(body) {
            return this._bandModelRequest('POST', 'band-model/preview/', body);
        }

        /**
         * Write the bands: auto-detected bands of these lanes replaced, hand-drawn ones kept.
         * @param {Object} body - the preview's body, with the chosen confidence
         * @returns {Promise<Object>}
         */
        async saveBandModel(body) {
            return this._bandModelRequest('POST', 'band-model/save/', body);
        }

        /**
         * Each detected lane's axis for the review's "Follow the lanes" (the guarded mask slope). Writes nothing.
         * @param {Object} body - {token, boxes: [{index, box: [x, y, w, h], mask_slope}]}
         * @param {AbortSignal} [signal] - the review aborts it on close or after 10 s
         * @returns {Promise<Object>} {token, y_ref, lanes: [{index, x_ref, slope, width, source}]}
         */
        async measureLaneTilt(body, signal) {
            return this._bandModelRequest('POST', 'lanes/tilt/', body, signal);
        }

        /** fetch + JSON; a refusal throws an Error carrying the server's message and the HTTP status. */
        async _bandModelRequest(method, path, body, signal) {
            const response = await this._request(`/api/analyses/${this.analysisId}/${path}`, {
                method,
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
                body: body === undefined ? undefined : JSON.stringify(body),
                signal,
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                const error = new Error(data.error || `HTTP ${response.status}`);
                error.status = response.status;
                throw error;
            }
            return data;
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
                const response = await this._request('/api/detection/params/', {
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
                const response = await this._request(`/api/lanes/${laneId}/detect-bands/`, {
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
                const response = await this._request(`/api/lanes/${laneId}/detect-bands/save/`, {
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
                const url = `/api/analyses/${this.analysisId}/detect-bands/async/`;
                const response = await this._request(url, {
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
                const response = await this._request(`/api/lanes/${laneId}/detect-bands-cv2/`, {
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
                const response = await this._request(`/api/lanes/${laneId}/detect-bands-cv2/save/`, {
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
                const url = `/api/analyses/${this.analysisId}/detect-bands-cv2/async/`;
                const response = await this._request(url, {
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
                const url = `/api/analyses/${this.analysisId}/detect-bands-cv2/calibrate/`;
                const response = await this._request(url, {
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

        /**
         * Get status of an async task (Celery).
         * @param {string} taskId - Celery task ID
         * @returns {Promise<Object>} Task status and results
         */
        async getTaskStatus(taskId) {
            try {
                const response = await this._request(`/api/tasks/${taskId}/status/`, {
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
                const response = await this._request('/api/ladder-templates/', {
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
                const response = await this._request('/api/ladder-templates/default/', {
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
                const response = await this._request(`/api/ladder-templates/${templateId}/`, {
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
         * Fill a LADDER lane's band MW values from a ladder template (LadderTemplateApply, its one caller): the server
         * gives the template's values to the lane's saved bands, top to bottom, and stores the template on the lane.
         * @param {number} laneId - Saved lane ID
         * @param {string} templateId - Template UUID
         * @returns {Promise<Object>} {bands_updated, template_name, warnings (null or strings), bands}
         */
        async applyLadderTemplate(laneId, templateId) {
            const response = await this._request(`/api/lanes/${laneId}/apply-ladder-template/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.csrfToken,
                },
                body: JSON.stringify({ template_id: templateId }),
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || `Failed to apply the template (HTTP ${response.status})`);
            }
            return response.json();
        }

        /**
         * Match lane bands to a ladder template (preview matching).
         * @param {number} laneId - Lane ID
         * @param {string} templateId - Template UUID
         * @returns {Promise<Object>} Matching result with band assignments
         */
        async matchTemplate(laneId, templateId) {
            try {
                const response = await this._request(`/api/lanes/${laneId}/match-template/`, {
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
         * @param {string[]} excludedBandIds - Band UUIDs to drop from the fit
         * @returns {Promise<Object>} Calibration result with coefficients
         */
        async calibrateSingle(laneId, templateId, method = 'LOG_LINEAR', excludedBandIds = []) {
            try {
                // Omit template_id when null — the manual-MW workflow runs
                // calibration without a template (PR #1 of the quantification
                // port made the backend service-layer template arg optional).
                const body = {
                    lane_id: laneId,
                    method: method,
                    excluded_band_ids: excludedBandIds,
                };
                if (templateId != null) {
                    body.template_id = templateId;
                }
                const response = await this._request(`/api/analyses/${this.analysisId}/calibrate/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(body),
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
         * @param {string[]} excludedBandIds - Band UUIDs to drop from the fit (across all ladders)
         * @returns {Promise<Object>} Multi-calibration result
         */
        async calibrateMulti(templateId, method = 'LOG_LINEAR', excludedBandIds = []) {
            try {
                // Omit template_id when null — manual-MW workflow runs
                // multi-ladder calibration without a template (PR #1 of the
                // quantification port).
                const body = {
                    method: method,
                    excluded_band_ids: excludedBandIds,
                };
                if (templateId != null) {
                    body.template_id = templateId;
                }
                const response = await this._request(`/api/analyses/${this.analysisId}/calibrate-multi/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                    body: JSON.stringify(body),
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
                const url = `/api/analyses/${this.analysisId}/apply-calibration/`;
                const response = await this._request(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.csrfToken,
                    },
                });

                if (!response.ok) {
                    throw new Error(await extractApiError(response, 'Failed to apply calibration'));
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
                const url = `/api/analyses/${this.analysisId}/apply-multi-calibration/`;
                const response = await this._request(url, {
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
                const response = await this._request(`/api/analyses/${this.analysisId}/calibration/`, {
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
                const url = `/api/analyses/${this.analysisId}/multi-calibration/`;
                const response = await this._request(url, {
                    headers: { 'Accept': 'application/json' }
                });

                if (!response.ok) {
                    throw new Error(await extractApiError(response, 'Failed to get multi-calibration'));
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
                const response = await this._request(`/api/bands/${bandId}/estimate-mw/`, {
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
                const response = await this._request(`/api/images/${this.imageId}/crop/`, {
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
                const url = `/api/analyses/${this.analysisId}/calibrate-detection/`;
                const response = await this._request(url, {
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
                const response = await this._request(`/api/lanes/${laneId}/profile/`, {
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
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.APIClient = APIClient;

})(window);
