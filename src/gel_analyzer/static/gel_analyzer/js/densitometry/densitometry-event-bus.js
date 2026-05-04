/**
 * Densitometry EventBus - PubSub Communication for Densitometry Module
 *
 * Central event bus for loose coupling between densitometry panels.
 * Follows the same pattern as GelViewer.EventBus.
 */

(function(global) {
    'use strict';

    /**
     * EventBus Class
     * Simple publish/subscribe pattern implementation.
     */
    class DensitometryEventBus {
        constructor() {
            this._listeners = new Map();
            this._onceListeners = new Map();
        }

        /**
         * Subscribe to an event.
         * @param {string} event - Event name
         * @param {Function} callback - Handler function
         * @returns {Function} Unsubscribe function
         */
        on(event, callback) {
            if (!this._listeners.has(event)) {
                this._listeners.set(event, new Set());
            }
            this._listeners.get(event).add(callback);
            return () => this.off(event, callback);
        }

        /**
         * Subscribe to an event once (auto-unsubscribe after first call).
         */
        once(event, callback) {
            if (!this._onceListeners.has(event)) {
                this._onceListeners.set(event, new Set());
            }
            this._onceListeners.get(event).add(callback);
            return () => {
                const listeners = this._onceListeners.get(event);
                if (listeners) listeners.delete(callback);
            };
        }

        /**
         * Unsubscribe from an event.
         */
        off(event, callback) {
            const listeners = this._listeners.get(event);
            if (listeners) listeners.delete(callback);
            const onceListeners = this._onceListeners.get(event);
            if (onceListeners) onceListeners.delete(callback);
        }

        /**
         * Emit an event with optional data.
         */
        emit(event, data) {
            // Regular listeners
            const listeners = this._listeners.get(event);
            if (listeners) {
                listeners.forEach(callback => {
                    try {
                        callback(data);
                    } catch (e) {
                        console.error(`DensitometryEventBus: Error in handler for "${event}":`, e);
                    }
                });
            }

            // Once listeners
            const onceListeners = this._onceListeners.get(event);
            if (onceListeners && onceListeners.size > 0) {
                onceListeners.forEach(callback => {
                    try {
                        callback(data);
                    } catch (e) {
                        console.error(`DensitometryEventBus: Error in once handler for "${event}":`, e);
                    }
                });
                this._onceListeners.set(event, new Set());
            }
        }

        /**
         * Remove all listeners for an event.
         */
        clear(event) {
            if (event) {
                this._listeners.delete(event);
                this._onceListeners.delete(event);
            } else {
                this._listeners.clear();
                this._onceListeners.clear();
            }
        }
    }

    // Event name constants
    const DensitometryEvents = {
        // Lane events
        LANE_SELECTED: 'lane:selected',
        LANE_HOVERED: 'lane:hovered',

        // Band events
        BAND_SELECTED: 'band:selected',
        BAND_HOVERED: 'band:hovered',
        BAND_TYPE_CHANGED: 'band:type:changed',
        BANDS_CREATED: 'bands:created',  // New bands created from peaks

        // Peak events (on chart)
        PEAK_CLICKED: 'peak:clicked',
        PEAK_HOVERED: 'peak:hovered',

        // Peak detection events (auto-detection from profile)
        PEAKS_DETECTION_STARTED: 'peaks:detection:started',
        PEAKS_DETECTED: 'peaks:detected',
        PEAKS_DETECTION_ERROR: 'peaks:detection:error',
        ORPHAN_PEAK_CLICKED: 'orphan:peak:clicked',

        // Analysis events
        ANALYSIS_STARTED: 'analysis:started',
        ANALYSIS_PROGRESS: 'analysis:progress',
        ANALYSIS_COMPLETED: 'analysis:completed',
        ANALYSIS_ERROR: 'analysis:error',
        ANALYSIS_OPTIONS_SELECTED: 'analysis:options:selected',

        // Data events
        DATA_LOADED: 'data:loaded',
        DATA_UPDATED: 'data:updated',
        PROFILE_LOADED: 'profile:loaded',

        // View events
        ZOOM_CHANGED: 'zoom:changed',
        VIEW_MODE_CHANGED: 'view:mode:changed',

        // Chart events
        CHART_READY: 'chart:ready',
        CHART_UPDATED: 'chart:updated',

        // Image adjustment events
        IMAGE_ADJUSTED: 'image:adjusted',
        IMAGE_RESET: 'image:reset',

        // Export events
        EXPORT_STARTED: 'export:started',
        EXPORT_COMPLETED: 'export:completed',
        EXPORT_ERROR: 'export:error',

        // Table events
        TABLE_ROW_SELECTED: 'table:row:selected',
        TABLE_SORT_CHANGED: 'table:sort:changed',

        // Digital lane events
        DIGITAL_LANE_MODE_CHANGED: 'digital:lane:mode:changed',

        // Settings events
        PARAMS_CHANGED: 'params:changed',
        NORMALIZATION_CHANGED: 'normalization:changed',
    };

    // Export to namespace
    global.Densitometry = global.Densitometry || {};
    global.Densitometry.EventBus = DensitometryEventBus;
    global.Densitometry.Events = DensitometryEvents;

})(window);
