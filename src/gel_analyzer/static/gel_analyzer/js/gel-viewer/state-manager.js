/**
 * StateManager - State Management for GelViewer
 *
 * Centralized state management for annotations, pending changes,
 * and localStorage persistence (crash recovery).
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    /**
     * StateManager Class
     * Manages all annotation state and pending changes.
     */
    class StateManager {
        /**
         * Create a StateManager instance.
         * @param {Object} options - Configuration options
         * @param {string} options.analysisId - UUID of the analysis
         * @param {EventBus} options.eventBus - EventBus instance
         */
        constructor(options) {
            this.analysisId = options.analysisId;
            this.eventBus = options.eventBus;

            // Annotations storage
            this.lanes = new Map();
            this.bands = new Map();

            // Selection state
            this.selectedAnnotation = null;

            // Pending changes for batch save (hybrid approach)
            this.pendingChanges = {
                lanes: {
                    created: new Map(),   // tempId -> data
                    updated: new Map(),   // id -> data
                    deleted: new Set(),   // Set of ids
                },
                bands: {
                    created: new Map(),   // tempId -> data
                    updated: new Map(),   // id -> data
                    deleted: new Set(),   // Set of ids
                }
            };

            // Dirty state
            this.isDirty = false;
            this.tempIdCounter = 0;
        }

        // =====================================================================
        // Dirty State Management
        // =====================================================================

        /**
         * Check if there are unsaved changes.
         * @returns {boolean}
         */
        hasUnsavedChanges() {
            return this.isDirty;
        }

        /**
         * Mark the state as dirty (unsaved changes).
         */
        markDirty() {
            if (!this.isDirty) {
                this.isDirty = true;
                this.eventBus.emit(Events.STATE_DIRTY);
                this.saveToLocalStorage();
            }
        }

        /**
         * Mark the state as clean (no unsaved changes).
         */
        markClean() {
            this.isDirty = false;
            this.pendingChanges = {
                lanes: { created: new Map(), updated: new Map(), deleted: new Set() },
                bands: { created: new Map(), updated: new Map(), deleted: new Set() }
            };
            this.eventBus.emit(Events.STATE_CLEAN);
            this.clearLocalStorage();
        }

        /**
         * Generate a temporary ID for new annotations.
         * @returns {string}
         */
        generateTempId() {
            return `temp_${++this.tempIdCounter}_${Date.now()}`;
        }

        // =====================================================================
        // Lane Operations
        // =====================================================================

        /**
         * Get a lane by ID.
         * @param {string|number} id - Lane ID
         * @returns {Object|undefined}
         */
        getLane(id) {
            return this.lanes.get(id);
        }

        /**
         * Get all lanes.
         * @returns {Map}
         */
        getAllLanes() {
            return this.lanes;
        }

        /**
         * Get lanes sorted by X position (left to right).
         * @returns {Array}
         */
        getLanesSortedByPosition() {
            return Array.from(this.lanes.values()).sort((a, b) => a.x - b.x);
        }

        /**
         * Add or update a lane in storage.
         * @param {string|number} id - Lane ID
         * @param {Object} data - Lane data
         */
        setLane(id, data) {
            this.lanes.set(id, data);
        }

        /**
         * Remove a lane from storage.
         * @param {string|number} id - Lane ID
         */
        deleteLane(id) {
            this.lanes.delete(id);
        }

        /**
         * Get the next lane number.
         * @returns {number}
         */
        getNextLaneNumber() {
            return this.lanes.size + 1;
        }

        /**
         * Track a lane creation (pending).
         * @param {string} tempId - Temporary ID
         * @param {Object} data - Lane data
         */
        trackLaneCreation(tempId, data) {
            this.pendingChanges.lanes.created.set(tempId, data);
            this.markDirty();
        }

        /**
         * Track a lane update (pending).
         * @param {string|number} id - Lane ID
         * @param {Object} data - Updated fields
         */
        trackLaneUpdate(id, data) {
            const lane = this.lanes.get(id);
            if (!lane) return;

            if (!lane._isNew) {
                const existing = this.pendingChanges.lanes.updated.get(id) || {};
                this.pendingChanges.lanes.updated.set(id, { ...existing, ...data });
            } else {
                const createData = this.pendingChanges.lanes.created.get(id);
                if (createData) {
                    Object.assign(createData, data);
                }
            }
            this.markDirty();
        }

        /**
         * Track a lane deletion (pending).
         * @param {string|number} id - Lane ID
         */
        trackLaneDeletion(id) {
            const lane = this.lanes.get(id);
            if (!lane) return;

            if (lane._isNew) {
                this.pendingChanges.lanes.created.delete(id);
            } else {
                this.pendingChanges.lanes.deleted.add(id);
                this.pendingChanges.lanes.updated.delete(id);
            }
            this.markDirty();
        }

        /**
         * Calculate lane number based on X position.
         * @param {number} x - X coordinate
         * @returns {number}
         */
        calculateLaneNumber(x) {
            let number = 1;
            for (const [, lane] of this.lanes) {
                if (lane.x < x) number++;
            }
            return number;
        }

        /**
         * Recalculate all lane numbers based on X position.
         * @returns {Array} Array of {id, oldNumber, newNumber} for lanes that changed
         */
        recalculateLaneNumbers() {
            const changes = [];
            const sorted = this.getLanesSortedByPosition();

            sorted.forEach((lane, index) => {
                const newNumber = index + 1;
                if (lane.lane_number !== newNumber) {
                    const oldNumber = lane.lane_number;
                    lane.lane_number = newNumber;
                    changes.push({ id: lane.id, oldNumber, newNumber });
                }
            });

            return changes;
        }

        // =====================================================================
        // Band Operations
        // =====================================================================

        /**
         * Get a band by ID.
         * @param {string} id - Band ID
         * @returns {Object|undefined}
         */
        getBand(id) {
            return this.bands.get(id);
        }

        /**
         * Get all bands.
         * @returns {Map}
         */
        getAllBands() {
            return this.bands;
        }

        /**
         * Add or update a band in storage.
         * @param {string} id - Band ID
         * @param {Object} data - Band data
         */
        setBand(id, data) {
            this.bands.set(id, data);
        }

        /**
         * Remove a band from storage.
         * @param {string} id - Band ID
         */
        deleteBand(id) {
            this.bands.delete(id);
        }

        /**
         * Get all bands belonging to a lane.
         * @param {string|number} laneId - Lane ID
         * @returns {Array} Array of bands for the lane
         */
        getBandsForLane(laneId) {
            const laneBands = [];
            for (const [id, band] of this.bands) {
                const bandLaneId = band._parentLaneId || band.lane_id;
                if (bandLaneId == laneId) {
                    laneBands.push(band);
                }
            }
            // Sort by Y position (top to bottom)
            return laneBands.sort((a, b) => (a.position_y || 0) - (b.position_y || 0));
        }

        /**
         * Track a band creation (pending).
         * @param {string} tempId - Temporary ID
         * @param {Object} data - Band data
         */
        trackBandCreation(tempId, data) {
            this.pendingChanges.bands.created.set(tempId, data);
            this.markDirty();
        }

        /**
         * Track a band update (pending).
         * @param {string} id - Band ID
         * @param {Object} data - Updated fields
         */
        trackBandUpdate(id, data) {
            const band = this.bands.get(id);
            if (!band) return;

            if (!band._isNew) {
                const existing = this.pendingChanges.bands.updated.get(id) || {};
                this.pendingChanges.bands.updated.set(id, { ...existing, ...data });
            } else {
                const createData = this.pendingChanges.bands.created.get(id);
                if (createData) {
                    Object.assign(createData, data);
                }
            }
            this.markDirty();
        }

        /**
         * Track a band deletion (pending).
         * @param {string} id - Band ID
         */
        trackBandDeletion(id) {
            const band = this.bands.get(id);
            if (!band) return;

            if (band._isNew) {
                this.pendingChanges.bands.created.delete(id);
            } else {
                this.pendingChanges.bands.deleted.add(id);
                this.pendingChanges.bands.updated.delete(id);
            }
            this.markDirty();
        }

        /**
         * Replace a temporary band ID with the real server ID.
         * Updates all internal references.
         * @param {string} oldId - Temporary ID (e.g., 'temp_123')
         * @param {string} newId - Real server UUID
         */
        replaceBandId(oldId, newId) {
            const band = this.bands.get(oldId);
            if (!band) return;

            // Update bands map
            this.bands.delete(oldId);
            band.id = newId;
            this.bands.set(newId, band);

            // Update parent lane's bands array
            const laneId = band._parentLaneId || band.lane_id;
            const lane = this.lanes.get(laneId);
            if (lane && lane.bands) {
                const bandInLane = lane.bands.find(b => b.id === oldId);
                if (bandInLane) {
                    bandInLane.id = newId;
                }
            }
        }

        // =====================================================================
        // Selection
        // =====================================================================

        /**
         * Set the selected annotation.
         * @param {string} type - 'lane' or 'band'
         * @param {string|number} id - Annotation ID
         */
        setSelection(type, id) {
            this.selectedAnnotation = { type, id };
            this.eventBus.emit(Events.SELECTION_CHANGED, this.selectedAnnotation);
        }

        /**
         * Clear the selection.
         */
        clearSelection() {
            this.selectedAnnotation = null;
            this.eventBus.emit(Events.SELECTION_CLEARED);
        }

        /**
         * Get the current selection.
         * @returns {Object|null}
         */
        getSelection() {
            return this.selectedAnnotation;
        }

        // =====================================================================
        // Clear All
        // =====================================================================

        /**
         * Clear all lanes and bands from storage.
         */
        clearAll() {
            this.lanes.clear();
            this.bands.clear();
            this.selectedAnnotation = null;
        }

        /**
         * Clear all bands from storage (keeps lanes).
         */
        clearAllBands() {
            this.bands.clear();
            // Clear selection if it was a band
            if (this.selectedAnnotation && this.selectedAnnotation.type === 'band') {
                this.selectedAnnotation = null;
            }
        }

        /**
         * Get total number of lanes.
         * @returns {number} Lane count
         */
        getLaneCount() {
            return this.lanes.size;
        }

        /**
         * Get total number of bands.
         * @returns {number} Band count
         */
        getBandCount() {
            return this.bands.size;
        }

        // =====================================================================
        // LocalStorage Persistence (Crash Recovery)
        // =====================================================================

        /**
         * Save current state to localStorage.
         */
        saveToLocalStorage() {
            try {
                const data = {
                    analysisId: this.analysisId,
                    timestamp: Date.now(),
                    lanes: Array.from(this.lanes.entries()),
                    bands: Array.from(this.bands.entries()),
                    pendingChanges: {
                        lanes: {
                            created: Array.from(this.pendingChanges.lanes.created.entries()),
                            updated: Array.from(this.pendingChanges.lanes.updated.entries()),
                            deleted: Array.from(this.pendingChanges.lanes.deleted),
                        },
                        bands: {
                            created: Array.from(this.pendingChanges.bands.created.entries()),
                            updated: Array.from(this.pendingChanges.bands.updated.entries()),
                            deleted: Array.from(this.pendingChanges.bands.deleted),
                        }
                    }
                };
                localStorage.setItem(`gelViewer_${this.analysisId}`, JSON.stringify(data));
            } catch (e) {
                console.warn('Failed to save to localStorage:', e);
            }
        }

        /**
         * Load state from localStorage (crash recovery).
         * @returns {Object|null} Restored data or null if nothing to restore
         */
        loadFromLocalStorage() {
            try {
                const stored = localStorage.getItem(`gelViewer_${this.analysisId}`);
                if (!stored) return null;

                const data = JSON.parse(stored);

                // Only restore if less than 24 hours old
                if (Date.now() - data.timestamp > 24 * 60 * 60 * 1000) {
                    this.clearLocalStorage();
                    return null;
                }

                // Check if there are pending changes
                const hasCreated = data.pendingChanges.lanes.created.length > 0 ||
                                   data.pendingChanges.bands.created.length > 0;
                const hasUpdated = data.pendingChanges.lanes.updated.length > 0 ||
                                   data.pendingChanges.bands.updated.length > 0;
                const hasDeleted = data.pendingChanges.lanes.deleted.length > 0 ||
                                   data.pendingChanges.bands.deleted.length > 0;

                if (hasCreated || hasUpdated || hasDeleted) {
                    return data;
                }

                return null;

            } catch (e) {
                console.warn('Failed to load from localStorage:', e);
                this.clearLocalStorage();
                return null;
            }
        }

        /**
         * Restore pending changes from localStorage data.
         * @param {Object} data - Data from loadFromLocalStorage
         */
        restoreFromLocalStorage(data) {
            this.pendingChanges = {
                lanes: {
                    created: new Map(data.pendingChanges.lanes.created),
                    updated: new Map(data.pendingChanges.lanes.updated),
                    deleted: new Set(data.pendingChanges.lanes.deleted),
                },
                bands: {
                    created: new Map(data.pendingChanges.bands.created),
                    updated: new Map(data.pendingChanges.bands.updated),
                    deleted: new Set(data.pendingChanges.bands.deleted),
                }
            };

            this.isDirty = true;
            this.eventBus.emit(Events.STATE_DIRTY);
        }

        /**
         * Clear localStorage backup.
         */
        clearLocalStorage() {
            try {
                localStorage.removeItem(`gelViewer_${this.analysisId}`);
            } catch (e) {
                console.warn('Failed to clear localStorage:', e);
            }
        }

        // =====================================================================
        // Pending Changes Access (for saveAll)
        // =====================================================================

        /**
         * Get all pending changes.
         * @returns {Object}
         */
        getPendingChanges() {
            return this.pendingChanges;
        }

        /**
         * Check if there are any pending changes.
         * @returns {boolean}
         */
        hasPendingChanges() {
            return this.pendingChanges.lanes.created.size > 0 ||
                   this.pendingChanges.lanes.updated.size > 0 ||
                   this.pendingChanges.lanes.deleted.size > 0 ||
                   this.pendingChanges.bands.created.size > 0 ||
                   this.pendingChanges.bands.updated.size > 0 ||
                   this.pendingChanges.bands.deleted.size > 0;
        }

        // =====================================================================
        // Display Helpers
        // =====================================================================

        /**
         * Get display name for lane type.
         * @param {string} laneType - Lane type code
         * @returns {string}
         */
        static getLaneTypeDisplay(laneType) {
            const displays = {
                'SAMPLE': 'Sample',
                'LADDER': 'MW Ladder',
                'CONTROL': 'Control',
                'EMPTY': 'Empty'
            };
            return displays[laneType] || laneType;
        }

        /**
         * Get display name for band type.
         * @param {string} bandType - Band type code
         * @returns {string}
         */
        static getBandTypeDisplay(bandType) {
            const displays = {
                'MW_REFERENCE': 'MW Reference',
                'POI': 'Protein of Interest',
                'OTHER': 'Other'
            };
            return displays[bandType] || bandType;
        }

        /**
         * Get display name for protein load type.
         * @param {string} loadType - Load type code
         * @returns {string}
         */
        static getProteinLoadTypeDisplay(loadType) {
            if (!loadType) return '';
            const displays = {
                'TOTAL': 'Total Protein',
                'POI': 'Protein of Interest',
                'HOST_CELL': 'Host Cell Protein',
                'OTHER': 'Other'
            };
            return displays[loadType] || loadType;
        }
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.StateManager = StateManager;

})(window);
