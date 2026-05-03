/**
 * EventBus - PubSub Communication for GelViewer Modules
 *
 * Central event bus for loose coupling between modules.
 * All modules can publish and subscribe to events without
 * direct references to each other.
 */

(function(global) {
    'use strict';

    /**
     * EventBus Class
     * Simple publish/subscribe pattern implementation.
     */
    class EventBus {
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

            // Return unsubscribe function
            return () => this.off(event, callback);
        }

        /**
         * Subscribe to an event once (auto-unsubscribe after first call).
         * @param {string} event - Event name
         * @param {Function} callback - Handler function
         * @returns {Function} Unsubscribe function
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
         * @param {string} event - Event name
         * @param {Function} callback - Handler function to remove
         */
        off(event, callback) {
            const listeners = this._listeners.get(event);
            if (listeners) {
                listeners.delete(callback);
            }
            const onceListeners = this._onceListeners.get(event);
            if (onceListeners) {
                onceListeners.delete(callback);
            }
        }

        /**
         * Emit an event with optional data.
         * @param {string} event - Event name
         * @param {*} data - Data to pass to handlers
         */
        emit(event, data) {
            // Regular listeners
            const listeners = this._listeners.get(event);
            if (listeners) {
                listeners.forEach(callback => {
                    try {
                        callback(data);
                    } catch (e) {
                        console.error(`EventBus: Error in handler for "${event}":`, e);
                    }
                });
            }

            // Once listeners (fire and remove)
            const onceListeners = this._onceListeners.get(event);
            if (onceListeners && onceListeners.size > 0) {
                onceListeners.forEach(callback => {
                    try {
                        callback(data);
                    } catch (e) {
                        console.error(`EventBus: Error in once handler for "${event}":`, e);
                    }
                });
                this._onceListeners.set(event, new Set());
            }
        }

        /**
         * Remove all listeners for an event (or all events).
         * @param {string} [event] - Event name (optional, clears all if omitted)
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

        /**
         * Get the number of listeners for an event.
         * @param {string} event - Event name
         * @returns {number}
         */
        listenerCount(event) {
            const regular = this._listeners.get(event)?.size || 0;
            const once = this._onceListeners.get(event)?.size || 0;
            return regular + once;
        }
    }

    // Event name constants for type safety
    const Events = {
        // Lane events
        LANE_CREATED: 'lane:created',
        LANE_UPDATED: 'lane:updated',
        LANE_DELETED: 'lane:deleted',
        LANE_SELECTED: 'lane:selected',
        LANE_PROPERTY_CHANGED: 'lane:property:changed',
        LANE_DRAW_FINISHED: 'lane:draw:finished',

        // Band events
        BAND_CREATED: 'band:created',
        BAND_UPDATED: 'band:updated',
        BAND_DELETED: 'band:deleted',
        BAND_SELECTED: 'band:selected',
        BAND_SPLIT: 'band:split',
        BAND_DRAW_FINISHED: 'band:draw:finished',
        BAND_PROPERTY_CHANGED: 'band:property:changed',
        BAND_SAVE_COMPLETE: 'band:save:complete',
        BAND_SAVE_FAILED: 'band:save:failed',

        // Selection events
        SELECTION_CHANGED: 'selection:changed',
        SELECTION_CLEARED: 'selection:cleared',

        // Tool events
        TOOL_CHANGED: 'tool:changed',
        LANE_SHAPE_CHANGED: 'lane:shape:changed',

        // State events
        STATE_DIRTY: 'state:dirty',
        STATE_CLEAN: 'state:clean',
        STATE_SAVING: 'state:saving',
        STATE_SAVED: 'state:saved',
        STATE_ERROR: 'state:error',

        // Viewport events
        VIEWPORT_CHANGED: 'viewport:changed',
        ZOOM_CHANGED: 'zoom:changed',
        PAN_CHANGED: 'pan:changed',

        // UI events
        ANNOTATIONS_LIST_UPDATED: 'annotations:list:updated',
        ANNOTATIONS_LOADED: 'annotations:loaded',
        PROPERTIES_PANEL_UPDATED: 'properties:panel:updated',
        TABLE_PANEL_TOGGLED: 'table:panel:toggled',
        TABLE_CELL_CHANGED: 'table:cell:changed',
        CONTEXT_MENU_SHOWN: 'context:menu:shown',
        CONTEXT_MENU_HIDDEN: 'context:menu:hidden',
        CONTEXT_MENU_REQUESTED: 'context:menu:requested',
        MESSAGE_SHOWN: 'message:shown',

        // Save events
        SAVE_REQUESTED: 'save:requested',
        SAVE_COMPLETED: 'save:completed',

        // Data events
        DATA_LOADED: 'data:loaded',
        DATA_LOADING: 'data:loading',
        DATA_ERROR: 'data:error',

        // Image adjustment events
        IMAGE_ADJUSTED: 'image:adjusted',
        IMAGE_RESET: 'image:reset',

        // Inference events (Phase 3 - YOLO detection)
        INFERENCE_STARTED: 'inference:started',
        INFERENCE_PROGRESS: 'inference:progress',
        INFERENCE_COMPLETED: 'inference:completed',
        INFERENCE_ERROR: 'inference:error',

        // Review panel events
        REVIEW_SHOWN: 'review:shown',
        REVIEW_HIDDEN: 'review:hidden',
        REVIEW_ACCEPTED: 'review:accepted',
        REVIEW_REJECTED: 'review:rejected',

        // Band detection events (Phase 3 - Auto detection)
        DETECTION_PANEL_SHOWN: 'detection:panel:shown',
        DETECTION_PANEL_HIDDEN: 'detection:panel:hidden',
        BANDS_DETECTED: 'bands:detected',
        BAND_DETECTION_PREVIEW: 'band:detection:preview',
        BAND_DETECTION_PREVIEW_CLEAR: 'band:detection:preview:clear',
        BAND_DETECTION_STARTED: 'band:detection:started',
        BAND_DETECTION_PROGRESS: 'band:detection:progress',
        BAND_DETECTION_COMPLETED: 'band:detection:completed',
        BAND_DETECTION_ERROR: 'band:detection:error',

        // Profile Peak Detection events
        PROFILE_DETECTION_PANEL_SHOWN: 'profile:detection:panel:shown',
        PROFILE_DETECTION_PANEL_HIDDEN: 'profile:detection:panel:hidden',
        PROFILE_DETECTION_STARTED: 'profile:detection:started',
        PROFILE_DETECTION_COMPLETED: 'profile:detection:completed',
        PROFILE_DETECTION_ERROR: 'profile:detection:error',

        // MW Calibration events (Phase 3 - ladder calibration)
        CALIBRATION_PANEL_SHOWN: 'calibration:panel:shown',
        CALIBRATION_PANEL_HIDDEN: 'calibration:panel:hidden',
        CALIBRATION_TEMPLATE_SELECTED: 'calibration:template:selected',
        CALIBRATION_TEMPLATE_MATCHED: 'calibration:template:matched',
        CALIBRATION_APPLIED: 'calibration:applied',
        CALIBRATION_MULTI_APPLIED: 'calibration:multi:applied',
        MW_UPDATED: 'mw:updated',
        MW_BANDS_UPDATED: 'mw:bands:updated',

        // General data events
        DATA_RELOAD_REQUESTED: 'data:reload:requested',

        // Image crop events
        CROP_REQUESTED: 'image:crop:requested',

        // SAM decoder events (MobileSAM polygon refinement)
        SAM_DECODER_INITIALIZING: 'sam:decoder:initializing',
        SAM_DECODER_READY: 'sam:decoder:ready',
        SAM_EMBEDDINGS_LOADING: 'sam:embeddings:loading',
        SAM_EMBEDDINGS_READY: 'sam:embeddings:ready',
        SAM_EMBEDDINGS_ERROR: 'sam:embeddings:error',
        SAM_POLYGON_REFINED: 'sam:polygon:refined',
        SAM_BATCH_STARTED: 'sam:batch:started',
        SAM_BATCH_PROGRESS: 'sam:batch:progress',
        SAM_BATCH_COMPLETE: 'sam:batch:complete',
        SAM_ERROR: 'sam:error',

        // Threshold events (boundary-centric integration)
        THRESHOLD_CHANGED: 'detection:threshold:changed',

        // Teacher (band detection calibration) events
        TEACHER_PANEL_SHOWN: 'teacher:panel:shown',
        TEACHER_PANEL_HIDDEN: 'teacher:panel:hidden',
        TEACHER_MARK_PROFILE_START: 'teacher:mark:profile:start',
        TEACHER_MARK_PROFILE_RESULT: 'teacher:mark:profile:result',
        TEACHER_PARAMS_APPLIED: 'teacher:params:applied',

        // CV2 Vision Detection
        CV2_DETECTION_PANEL_SHOWN: 'cv2:detection:panel:shown',
        CV2_DETECTION_PANEL_HIDDEN: 'cv2:detection:panel:hidden',
        CV2_DETECTION_PREVIEW: 'cv2:detection:preview',
        CV2_DETECTION_PREVIEW_CLEAR: 'cv2:detection:preview:clear',
        CV2_DETECTION_STARTED: 'cv2:detection:started',
        CV2_DETECTION_PROGRESS: 'cv2:detection:progress',
        CV2_DETECTION_COMPLETED: 'cv2:detection:completed',
        CV2_DETECTION_ERROR: 'cv2:detection:error',

        // Hybrid Detection (blend of CV2 and derivative methods)
        HYBRID_DETECTION_PANEL_SHOWN: 'hybrid:detection:panel:shown',
        HYBRID_DETECTION_PANEL_HIDDEN: 'hybrid:detection:panel:hidden',

        // Cross-Lane Consensus panel
        CROSS_LANE_PANEL_SHOWN: 'cross-lane:panel:shown',
        CROSS_LANE_PANEL_HIDDEN: 'cross-lane:panel:hidden',
    };

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.EventBus = EventBus;
    global.GelViewer.Events = Events;

})(window);
