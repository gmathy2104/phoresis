/**
 * StateManager - State Management for GelViewer
 *
 * Centralized state management for annotations, pending changes,
 * and localStorage persistence (crash recovery).
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    // The crash backup (localStorage) mirrors pendingChanges: rewritten this long after the last change, kept 24 h.
    const BACKUP_VERSION = 2;
    const BACKUP_DELAY_MS = 500;
    const BACKUP_MAX_AGE_MS = 24 * 60 * 60 * 1000;

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
            this._backupTimer = null;

            // Saved band id -> its lane id, for the bands deleted along with their lane (pendingCount counts the
            // lane alone). Only read for ids in pendingChanges.bands.deleted.
            this._deletedBandLane = new Map();
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
         * Mark the state as dirty (unsaved changes). Every call, not only the first, rewrites the backup.
         */
        markDirty() {
            if (!this.isDirty) {
                this.isDirty = true;
                this.eventBus.emit(Events.STATE_DIRTY);
            }
            this.scheduleBackup();
            this.eventBus.emit(Events.PENDING_CHANGED);
        }

        /**
         * A pending change left pendingChanges outside Save: it reached the server (a band sent at once), or it is
         * forgotten (an unsaved lane or band deleted, an entry a reload made stale). Clean when nothing else waits,
         * else the backup is rewritten without it, or a restore would send it a second time.
         */
        afterImmediateSave() {
            if (this.hasPendingChanges()) {
                this.scheduleBackup();
                this.eventBus.emit(Events.PENDING_CHANGED);
            } else {
                this.markClean();
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
            this._deletedBandLane.clear();
            this.eventBus.emit(Events.STATE_CLEAN);
            this.clearLocalStorage();
            this.eventBus.emit(Events.PENDING_CHANGED);
        }

        /**
         * How many lanes and bands the next Save writes: each one created, edited or deleted counts once, and the
         * saved bands deleted along with their lane are that lane's deletion, not more changes (their lane is off
         * the canvas, its own DELETE pending or already through). What the editor's "N unsaved changes" says.
         * @returns {number}
         */
        pendingCount() {
            const p = this.pendingChanges;
            const lanesHere = new Set(Array.from(this.lanes.keys(), String));
            let count = p.lanes.created.size + p.lanes.updated.size + p.lanes.deleted.size
                + p.bands.created.size + p.bands.updated.size;
            for (const id of p.bands.deleted) {
                const laneId = this._deletedBandLane.get(String(id));
                if (laneId === undefined || lanesHere.has(laneId)) count += 1;
            }
            return count;
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
         * Reads the pending sets, not the lanes map, so the caller may already have removed the lane. The new bands
         * drawn in it go too: a Save creating a band in a lane that is gone fails on every attempt.
         * @param {string|number} id - Lane ID
         */
        trackLaneDeletion(id) {
            const pending = this.pendingChanges;
            for (const [bandId, band] of pending.bands.created) {
                if (String(band._parentLaneId || band.lane_id) === String(id)) {
                    pending.bands.created.delete(bandId);
                }
            }

            if (pending.lanes.created.delete(id) || String(id).startsWith('temp_')) {
                // Never saved: forgetting it is the whole deletion.
                this.afterImmediateSave();
                return;
            }
            pending.lanes.deleted.add(id);
            pending.lanes.updated.delete(id);
            this.markDirty();
        }

        /**
         * A saved lane was deleted on the server at once (GelViewerApp._deleteLane): a pending edit of it would PUT to
         * a lane that is gone, and a new band drawn in it be created in no lane -- the Save would fail on every attempt.
         * @param {string|number} id - Lane ID
         */
        forgetLaneUpdate(id) {
            const pending = this.pendingChanges;
            let forgot = pending.lanes.updated.delete(id);
            for (const [bandId, band] of pending.bands.created) {
                if (String(band._parentLaneId || band.lane_id) === String(id)) {
                    pending.bands.created.delete(bandId);
                    forgot = true;
                }
            }
            if (forgot) this.afterImmediateSave();
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
         * Reads the pending sets, not the bands map, so the caller may already have removed the band: looked up
         * there, an unsaved band deleted first stayed pending and the next Save created it again.
         * @param {string} id - Band ID
         */
        trackBandDeletion(id) {
            const pending = this.pendingChanges;
            if (pending.bands.created.delete(id) || String(id).startsWith('temp_')) {
                // Never saved: forgetting it is the whole deletion.
                this.afterImmediateSave();
                return;
            }
            const band = this.bands.get(id);  // still here when its lane is being deleted (GelViewerApp._deleteLane)
            if (band) this._deletedBandLane.set(String(id), String(band._parentLaneId || band.lane_id));
            pending.bands.deleted.add(id);
            pending.bands.updated.delete(id);
            this.markDirty();
        }

        /**
         * A saved band was deleted on the server at once: a pending edit of it would PUT to a band that is gone, and
         * the Save fail on every attempt.
         * @param {string} id - Band ID
         */
        forgetBandUpdate(id) {
            if (this.pendingChanges.bands.updated.delete(id)) {
                this.afterImmediateSave();
            }
        }

        /**
         * The server created a band outside the batch Save (drawn in a saved lane): the Save must not create it again.
         * @param {string} tempId - The band's temporary ID
         */
        confirmBandCreated(tempId) {
            this.pendingChanges.bands.created.delete(tempId);
            this.afterImmediateSave();
        }

        /**
         * The server saved `sent` for a lane or band outside the batch Save. Forget those fields only: the same
         * pending entry may hold edits still waiting (a resize before an auto-promote, an earlier PUT that failed),
         * and a field edited again since the PUT left (its pending value is no longer the one sent) still waits.
         * @param {'lanes'|'bands'} kind
         * @param {string|number} id - Lane or band ID
         * @param {Object} sent - The fields the PUT carried
         */
        confirmUpdateSaved(kind, id, sent) {
            const updated = this.pendingChanges[kind].updated;
            const edit = updated.get(id);
            if (edit) {
                for (const key of Object.keys(sent)) {
                    if (edit[key] === sent[key]) delete edit[key];
                }
                if (Object.keys(edit).length === 0) updated.delete(id);
            }
            this.afterImmediateSave();
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
         * Rewrite the backup BACKUP_DELAY_MS after the last call (a drag fires a change per mouse move).
         */
        scheduleBackup() {
            clearTimeout(this._backupTimer);
            this._backupTimer = setTimeout(() => this.saveToLocalStorage(), BACKUP_DELAY_MS);
        }

        /**
         * Write the backup now: the pending changes only (what Save would send), or no backup when none is left.
         */
        saveToLocalStorage() {
            clearTimeout(this._backupTimer);
            this._backupTimer = null;
            if (!this.hasPendingChanges()) {
                this.clearLocalStorage();
                return;
            }
            try {
                const p = this.pendingChanges;
                const data = {
                    version: BACKUP_VERSION,
                    analysisId: this.analysisId,
                    timestamp: Date.now(),
                    pendingChanges: {
                        lanes: {
                            created: Array.from(p.lanes.created.entries()),
                            updated: Array.from(p.lanes.updated.entries()),
                            deleted: Array.from(p.lanes.deleted),
                        },
                        bands: {
                            created: Array.from(p.bands.created.entries()),
                            updated: Array.from(p.bands.updated.entries()),
                            deleted: Array.from(p.bands.deleted),
                        }
                    }
                };
                localStorage.setItem(`gelViewer_${this.analysisId}`, JSON.stringify(data));
            } catch (e) {
                console.warn('Failed to save to localStorage:', e);
            }
        }

        /**
         * The backup an earlier visit left (a crash, a tab closed without saving), or null. A backup older than
         * 24 h, or written before this format (version 1 kept only the FIRST change), is dropped.
         * @returns {Object|null} {timestamp, pendingChanges} with arrays in place of the Maps and Sets
         */
        loadFromLocalStorage() {
            try {
                const stored = localStorage.getItem(`gelViewer_${this.analysisId}`);
                if (!stored) return null;

                const data = JSON.parse(stored);
                if (data.version !== BACKUP_VERSION || Date.now() - data.timestamp > BACKUP_MAX_AGE_MS) {
                    this.clearLocalStorage();
                    return null;
                }
                return StateManager.countChanges(data.pendingChanges) > 0 ? data : null;

            } catch (e) {
                console.warn('Failed to load from localStorage:', e);
                this.clearLocalStorage();
                return null;
            }
        }

        /**
         * The part of a backup that still applies to the lanes and bands the server just returned, and the number
         * of changes left out: an edit or a deletion of a lane or band the server no longer has (deleted elsewhere,
         * replaced by a detection rerun), a band whose lane is gone. Ids come back with the live Map keys' type.
         * Call it right after the server's annotations are loaded and before any edit.
         * @param {Object} backup - from loadFromLocalStorage
         * @returns {{changes: Object, dropped: number}} changes has the backup's shape (arrays)
         */
        recoverable(backup) {
            const p = backup.pendingChanges;
            const keyOf = (map) => new Map(Array.from(map.keys(), k => [String(k), k]));
            const laneKey = keyOf(this.lanes);
            const bandKey = keyOf(this.bands);

            const lanesDeleted = p.lanes.deleted.filter(id => laneKey.has(String(id))).map(id => laneKey.get(String(id)));
            const gone = new Set(lanesDeleted.map(String));
            const lanesUpdated = p.lanes.updated
                .filter(([id]) => laneKey.has(String(id)) && !gone.has(String(id)))
                .map(([id, data]) => [laneKey.get(String(id)), data]);
            // A created lane has nothing on the server to be compared with: it comes back as it was drawn.
            const lanesCreated = p.lanes.created;
            const newLanes = new Set(lanesCreated.map(([id]) => String(id)));
            const bandsCreated = [];
            for (const [id, band] of p.bands.created) {
                const laneId = String(band._parentLaneId ?? band.lane_id);
                if (laneKey.has(laneId) && !gone.has(laneId)) {
                    band._parentLaneId = band.lane_id = laneKey.get(laneId);  // a band drawn on a saved lane
                } else if (!newLanes.has(laneId)) {
                    continue;
                }
                bandsCreated.push([id, band]);
            }
            const bandsUpdated = p.bands.updated
                .filter(([id]) => bandKey.has(String(id)))
                .map(([id, data]) => [bandKey.get(String(id)), data]);
            const bandsDeleted = p.bands.deleted.filter(id => bandKey.has(String(id))).map(id => bandKey.get(String(id)));

            const changes = {
                lanes: { created: lanesCreated, updated: lanesUpdated, deleted: lanesDeleted },
                bands: { created: bandsCreated, updated: bandsUpdated, deleted: bandsDeleted },
            };
            return { changes, dropped: StateManager.countChanges(p) - StateManager.countChanges(changes) };
        }

        /**
         * Number of entries in a pendingChanges-shaped object of arrays (a backup's).
         */
        static countChanges(p) {
            return ['lanes', 'bands'].reduce((n, kind) =>
                n + p[kind].created.length + p[kind].updated.length + p[kind].deleted.length, 0);
        }

        /**
         * Clear localStorage backup (and a rewrite still waiting).
         */
        clearLocalStorage() {
            clearTimeout(this._backupTimer);
            this._backupTimer = null;
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

        /**
         * Whether the server's copy of a lane or of its bands is behind the editor's: the lane never saved, deleted
         * here, or its type waiting for Save; one of its bands created, edited or deleted here and not saved (a band
         * POST or PUT still on its way counts: it leaves pendingChanges once answered). A write the server computes
         * from its own copy -- a ladder template's MW values, given to the saved bands in their saved order
         * (LadderTemplateApply) -- waits until this is false. The lane's other fields do not count.
         * @param {string|number} laneId - Lane ID
         * @returns {boolean}
         */
        laneWaitsForSave(laneId) {
            const p = this.pendingChanges;
            const key = String(laneId);
            const same = (id) => String(id) === key;
            if (key.startsWith('temp_')) return true;
            if (Array.from(p.lanes.created.keys()).some(same) || Array.from(p.lanes.deleted).some(same)) return true;
            for (const [id, edit] of p.lanes.updated) {
                if (same(id) && 'lane_type' in edit) return true;
            }
            const inLane = (band) => !!band && same(band._parentLaneId || band.lane_id);
            for (const band of p.bands.created.values()) {
                if (inLane(band)) return true;
            }
            for (const id of p.bands.updated.keys()) {
                if (inLane(this.bands.get(id))) return true;
            }
            for (const id of p.bands.deleted) {
                if (this._deletedBandLane.get(String(id)) === key) return true;
            }
            return false;
        }

        /**
         * Before a reload replaces the lanes and bands with the server's: keep the unsaved changes that still apply
         * (the reload draws them again) and drop the others, so the canvas and the next Save agree. Kept: a lane or
         * band never saved that is still on the canvas (Remove all lanes / bands empty the maps before reloading) and
         * not in the middle of its own POST, a new band only with its lane; an edit or a deletion of a lane or band
         * the server still has. Call it while the maps still hold the canvas.
         * @param {Array} serverLanes - The reloaded lanes, each with its bands
         * @returns {number} How many pending changes were dropped
         */
        keepPendingApplicable(serverLanes) {
            const pending = this.pendingChanges;
            const count = () => [pending.lanes, pending.bands]
                .reduce((n, set) => n + set.created.size + set.updated.size + set.deleted.size, 0);
            const before = count();
            const laneIds = new Set(serverLanes.map(lane => String(lane.id)));
            const bandIds = new Set(serverLanes.flatMap(lane => (lane.bands || []).map(band => String(band.id))));

            for (const id of pending.lanes.created.keys()) {
                if (!this.lanes.has(id)) pending.lanes.created.delete(id);
            }
            for (const id of pending.lanes.updated.keys()) {
                if (!laneIds.has(String(id))) pending.lanes.updated.delete(id);
            }
            for (const id of pending.lanes.deleted) {
                if (!laneIds.has(String(id))) pending.lanes.deleted.delete(id);
            }
            const lanesStaying = new Set([...pending.lanes.created.keys(), ...laneIds].map(String));
            for (const id of pending.lanes.deleted) lanesStaying.delete(String(id));
            for (const [id, band] of pending.bands.created) {
                const laneStays = lanesStaying.has(String(band._parentLaneId || band.lane_id));
                if (!this.bands.has(id) || band._isSaving || !laneStays) pending.bands.created.delete(id);
            }
            for (const id of pending.bands.updated.keys()) {
                if (!bandIds.has(String(id))) pending.bands.updated.delete(id);
            }
            for (const id of pending.bands.deleted) {
                if (!bandIds.has(String(id))) pending.bands.deleted.delete(id);
            }

            const dropped = before - count();
            if (dropped > 0) this.afterImmediateSave();
            return dropped;
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
                'EMPTY': 'Empty',
                'CALIBRATION': 'Calibration Standard',
                'DOT': 'Dot'
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
                'CALIBRATION': 'Calibration Point',
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
