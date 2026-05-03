/**
 * Core EventBus - Shared Pub/Sub Communication Module
 *
 * A generic event bus for loose coupling between components.
 * Can be used as ES module or via global namespace.
 *
 * Usage (ES Module):
 *   import { EventBus, CoreEvents } from './core/event-bus.js';
 *   const bus = new EventBus();
 *   bus.on(CoreEvents.DATA_LOADED, (data) => console.log(data));
 *
 * Usage (IIFE/Global):
 *   const bus = new GelAnalyzer.Core.EventBus();
 *   bus.on(GelAnalyzer.Core.Events.DATA_LOADED, handler);
 */

(function(global, factory) {
    'use strict';

    // Universal Module Definition (UMD)
    if (typeof module === 'object' && typeof module.exports === 'object') {
        // CommonJS
        module.exports = factory();
    } else if (typeof define === 'function' && define.amd) {
        // AMD
        define(factory);
    } else {
        // Browser globals
        global.GelAnalyzer = global.GelAnalyzer || {};
        global.GelAnalyzer.Core = global.GelAnalyzer.Core || {};
        const exports = factory();
        global.GelAnalyzer.Core.EventBus = exports.EventBus;
        global.GelAnalyzer.Core.Events = exports.CoreEvents;
    }
})(typeof window !== 'undefined' ? window : this, function() {
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
         * @param {Function} callback - Handler function
         */
        off(event, callback) {
            const listeners = this._listeners.get(event);
            if (listeners) listeners.delete(callback);
            const onceListeners = this._onceListeners.get(event);
            if (onceListeners) onceListeners.delete(callback);
        }

        /**
         * Emit an event with optional data.
         * @param {string} event - Event name
         * @param {*} data - Optional data to pass to handlers
         */
        emit(event, data) {
            // Regular listeners
            const listeners = this._listeners.get(event);
            if (listeners) {
                listeners.forEach(callback => {
                    try {
                        callback(data);
                    } catch (e) {
                        console.error(`[EventBus] Error in handler for "${event}":`, e);
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
                        console.error(`[EventBus] Error in once handler for "${event}":`, e);
                    }
                });
                this._onceListeners.set(event, new Set());
            }
        }

        /**
         * Remove all listeners for an event, or all events.
         * @param {string} [event] - Optional event name
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
         * Get listener count for an event.
         * @param {string} event - Event name
         * @returns {number} Number of listeners
         */
        listenerCount(event) {
            const regular = this._listeners.get(event)?.size || 0;
            const once = this._onceListeners.get(event)?.size || 0;
            return regular + once;
        }
    }

    /**
     * Core event name constants.
     * These are shared across all modules using the EventBus.
     */
    const CoreEvents = {
        // Data lifecycle
        DATA_LOADED: 'data:loaded',
        DATA_UPDATED: 'data:updated',
        DATA_ERROR: 'data:error',

        // Selection
        SELECTION_CHANGED: 'selection:changed',
        ITEM_SELECTED: 'item:selected',
        ITEM_DESELECTED: 'item:deselected',

        // UI State
        VIEW_READY: 'view:ready',
        VIEW_RESIZED: 'view:resized',
        VIEW_MODE_CHANGED: 'view:mode:changed',

        // Loading
        LOADING_STARTED: 'loading:started',
        LOADING_COMPLETED: 'loading:completed',
        LOADING_ERROR: 'loading:error',

        // Generic
        ERROR: 'error',
        WARNING: 'warning',
        INFO: 'info',
    };

    // Return exports
    return {
        EventBus,
        CoreEvents,
    };
});
