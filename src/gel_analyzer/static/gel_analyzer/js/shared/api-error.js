/**
 * Shared helper to extract a useful error message from a non-OK fetch
 * Response.
 *
 * Background: every api-client method used to write a one-off block like
 *
 *     const err = await response.json().catch(() => ({}));
 *     throw new Error(err.detail || JSON.stringify(err) || 'Failed to ...');
 *
 * which collapses to the unhelpful `Error('{}')` whenever the server
 * returns a non-JSON 500 page (Django debug HTML, gateway timeout, etc.).
 * Centralising the extraction here gets us a meaningful `.message` —
 * including the HTTP status and statusText as a last-resort fallback —
 * so the toast that AutoSave shows the user is actually informative.
 */
(function (global) {
    'use strict';

    /**
     * Extract a best-effort error message from a fetch Response.
     *
     * Strategy, first hit wins:
     *   1. JSON body with `.detail` (DRF's standard error format)
     *   2. JSON body with first non-empty field error (DRF validation
     *      errors look like `{"field": ["msg"]}`)
     *   3. Stringified JSON body if it's a non-trivial object
     *   4. `${status} ${statusText}` (covers 500 HTML pages,
     *      "404 Not Found", "504 Gateway Timeout", etc.)
     *   5. The provided fallback message
     *
     * @param {Response} response - non-OK fetch response
     * @param {string} [fallback='Request failed'] - last-resort message
     * @returns {Promise<string>}
     */
    async function extractApiError(response, fallback = 'Request failed') {
        // (1) + (2) + (3): try the body as JSON first
        let body = null;
        try {
            body = await response.json();
        } catch (_) {
            // Non-JSON body (HTML 500 page, empty body, etc.) — fall through
        }

        if (body && typeof body === 'object') {
            if (typeof body.detail === 'string' && body.detail.trim()) {
                return body.detail;
            }
            // DRF validation errors: pick the first field with a message
            for (const key of Object.keys(body)) {
                const value = body[key];
                if (Array.isArray(value) && value.length && typeof value[0] === 'string') {
                    return `${key}: ${value[0]}`;
                }
                if (typeof value === 'string' && value.trim()) {
                    return `${key}: ${value}`;
                }
            }
            // Non-empty object with no recognized shape — stringify it
            const serialized = JSON.stringify(body);
            if (serialized && serialized !== '{}' && serialized !== 'null') {
                return serialized;
            }
        }

        // (4) status + statusText
        if (response.status) {
            const statusText = response.statusText || '';
            return `${response.status}${statusText ? ' ' + statusText : ''}`;
        }

        // (5) absolute fallback
        return fallback;
    }

    global.PhoresisShared = global.PhoresisShared || {};
    global.PhoresisShared.extractApiError = extractApiError;
})(window);
