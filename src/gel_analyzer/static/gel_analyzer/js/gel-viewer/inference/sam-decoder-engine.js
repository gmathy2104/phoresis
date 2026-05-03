/**
 * sam-decoder-engine.js
 *
 * Main orchestrator for MobileSAM decoder inference.
 * Manages the SAM decoder Web Worker, fetches embeddings from server,
 * and provides API for band polygon refinement.
 *
 * @requires sam-decoder-worker.js (Web Worker)
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    /**
     * SAMDecoderEngine Class
     *
     * Handles MobileSAM decoder initialization, embedding management,
     * and band polygon refinement.
     */
    class SAMDecoderEngine {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus - Event bus for communication
         * @param {string} options.analysisId - Analysis UUID for embedding API
         * @param {boolean} [options.useQuantized=true] - Use quantized model
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.analysisId = options.analysisId;
            this.useQuantized = options.useQuantized !== false;

            // Worker state
            this.worker = null;
            this.isInitialized = false;
            this.isInitializing = false;
            this.hasEmbeddings = false;
            this.isBusy = false;

            // Embedding info
            this.embeddingInfo = null;

            // Promise resolvers
            this._initPromise = null;
            this._initResolve = null;
            this._initReject = null;
            this._embeddingsPromise = null;
            this._embeddingsResolve = null;
            this._embeddingsReject = null;
            this._refinementPromise = null;
            this._refinementResolve = null;
            this._refinementReject = null;
            this._batchPromise = null;
            this._batchResolve = null;
            this._batchReject = null;
        }

        /**
         * Initialize the SAM decoder engine.
         * Creates the Web Worker and loads the decoder model.
         * @returns {Promise<void>}
         */
        async initialize() {
            if (this.isInitialized) {
                return;
            }

            if (this.isInitializing) {
                return this._initPromise;
            }

            this.isInitializing = true;

            try {
                this._initPromise = new Promise((resolve, reject) => {
                    this._initResolve = resolve;
                    this._initReject = reject;
                });

                // Emit event
                this.eventBus.emit(Events.SAM_DECODER_INITIALIZING, {
                    useQuantized: this.useQuantized,
                });

                // Create Web Worker
                const workerUrl = '/static/gel_analyzer/js/gel-viewer/inference/sam-decoder-worker.js';
                this.worker = new Worker(workerUrl);

                // Setup handlers
                this.worker.onmessage = (event) => this._handleWorkerMessage(event);
                this.worker.onerror = (error) => this._handleWorkerError(error);

                // Initialize decoder
                this.worker.postMessage({
                    type: 'INIT',
                    payload: { useQuantized: this.useQuantized },
                });

                await this._initPromise;

            } catch (error) {
                this.isInitializing = false;
                throw error;
            }
        }

        /**
         * Fetch and set image embeddings from server.
         * Uses the SAM embeddings API endpoint.
         * @param {boolean} [forceRefresh=false] - Force regenerate embeddings
         * @returns {Promise<Object>} Embedding info
         */
        async loadEmbeddings(forceRefresh = false) {
            if (!this.isInitialized) {
                await this.initialize();
            }

            if (this.hasEmbeddings && !forceRefresh) {
                return this.embeddingInfo;
            }

            try {
                this._embeddingsPromise = new Promise((resolve, reject) => {
                    this._embeddingsResolve = resolve;
                    this._embeddingsReject = reject;
                });

                // Emit event
                this.eventBus.emit(Events.SAM_EMBEDDINGS_LOADING, {
                    analysisId: this.analysisId,
                    forceRefresh: forceRefresh,
                });

                console.log('SAMDecoderEngine: Fetching embeddings from server...');

                // Fetch embeddings from API
                const url = `/gel-analyzer/api/analyses/${this.analysisId}/sam-embeddings/` +
                    (forceRefresh ? '?force=true' : '');

                const response = await fetch(url, {
                    method: 'GET',
                    headers: {
                        'Accept': 'application/json',
                    },
                });

                if (!response.ok) {
                    throw new Error(`Failed to fetch embeddings: ${response.status}`);
                }

                const data = await response.json();
                console.log('SAMDecoderEngine: Embeddings received from server');

                // Send embeddings to worker
                this.worker.postMessage({
                    type: 'SET_EMBEDDINGS',
                    payload: {
                        embeddings: data.image_embedding,
                        embeddingShape: data.embedding_shape,
                        dtype: data.dtype,
                        origSize: data.original_size,
                        inputSz: data.input_size,
                    },
                });

                const result = await this._embeddingsPromise;
                return result;

            } catch (error) {
                console.error('SAMDecoderEngine: Failed to load embeddings:', error);
                this.eventBus.emit(Events.SAM_EMBEDDINGS_ERROR, { error: error.message });
                throw error;
            }
        }

        /**
         * Refine a single band polygon using SAM decoder.
         * @param {string} bandId - Band identifier
         * @param {Array<number>} bbox - Bounding box [x, y, width, height]
         * @returns {Promise<Array>} Refined polygon points
         */
        async refineBand(bandId, bbox) {
            if (!this.isInitialized) {
                await this.initialize();
            }

            if (!this.hasEmbeddings) {
                await this.loadEmbeddings();
            }

            if (this.isBusy) {
                throw new Error('SAM decoder is busy');
            }

            this.isBusy = true;

            try {
                this._refinementPromise = new Promise((resolve, reject) => {
                    this._refinementResolve = resolve;
                    this._refinementReject = reject;
                });

                console.log('SAMDecoderEngine: Refining band', bandId, bbox);

                // Send refinement request
                this.worker.postMessage({
                    type: 'REFINE_BAND',
                    payload: { bandId, bbox },
                });

                const result = await this._refinementPromise;
                return result;

            } finally {
                this.isBusy = false;
            }
        }

        /**
         * Refine multiple bands in batch.
         * @param {Array<Object>} bands - Array of {bandId, bbox}
         * @returns {Promise<Array>} Array of results
         */
        async refineBandsBatch(bands) {
            if (!this.isInitialized) {
                await this.initialize();
            }

            if (!this.hasEmbeddings) {
                await this.loadEmbeddings();
            }

            if (this.isBusy) {
                throw new Error('SAM decoder is busy');
            }

            this.isBusy = true;

            try {
                this._batchPromise = new Promise((resolve, reject) => {
                    this._batchResolve = resolve;
                    this._batchReject = reject;
                });

                console.log('SAMDecoderEngine: Refining batch of', bands.length, 'bands');

                // Emit start event
                this.eventBus.emit(Events.SAM_BATCH_STARTED, {
                    total: bands.length,
                });

                // Send batch request
                this.worker.postMessage({
                    type: 'REFINE_BANDS_BATCH',
                    payload: { bands },
                });

                const result = await this._batchPromise;
                return result;

            } finally {
                this.isBusy = false;
            }
        }

        /**
         * Handle messages from the Web Worker.
         */
        _handleWorkerMessage(event) {
            const { type, payload } = event.data;
            console.log('SAMDecoderEngine: Worker message:', type);

            switch (type) {
                case 'READY':
                    this._handleReady(payload);
                    break;

                case 'EMBEDDINGS_SET':
                    this._handleEmbeddingsSet(payload);
                    break;

                case 'POLYGON_RESULT':
                    this._handlePolygonResult(payload);
                    break;

                case 'BATCH_PROGRESS':
                    this._handleBatchProgress(payload);
                    break;

                case 'BATCH_COMPLETE':
                    this._handleBatchComplete(payload);
                    break;

                case 'ERROR':
                    this._handleError(payload);
                    break;

                default:
                    console.warn('SAMDecoderEngine: Unknown message type:', type);
            }
        }

        /**
         * Handle decoder ready message.
         */
        _handleReady(payload) {
            this.isInitialized = true;
            this.isInitializing = false;

            console.log('SAMDecoderEngine: Decoder ready', payload);

            this.eventBus.emit(Events.SAM_DECODER_READY, payload);

            if (this._initResolve) {
                this._initResolve();
                this._initResolve = null;
                this._initReject = null;
            }
        }

        /**
         * Handle embeddings set message.
         */
        _handleEmbeddingsSet(payload) {
            this.hasEmbeddings = true;
            this.embeddingInfo = payload;

            console.log('SAMDecoderEngine: Embeddings set', payload);

            this.eventBus.emit(Events.SAM_EMBEDDINGS_READY, payload);

            if (this._embeddingsResolve) {
                this._embeddingsResolve(payload);
                this._embeddingsResolve = null;
                this._embeddingsReject = null;
            }
        }

        /**
         * Handle single polygon result.
         */
        _handlePolygonResult(payload) {
            const { bandId, polygon, inferenceTime } = payload;

            console.log('SAMDecoderEngine: Polygon result for band', bandId, 'in', inferenceTime, 'ms');

            this.eventBus.emit(Events.SAM_POLYGON_REFINED, {
                bandId,
                polygon,
                inferenceTime,
            });

            if (this._refinementResolve) {
                this._refinementResolve(polygon);
                this._refinementResolve = null;
                this._refinementReject = null;
            }
        }

        /**
         * Handle batch progress message.
         */
        _handleBatchProgress(payload) {
            const { current, total } = payload;

            this.eventBus.emit(Events.SAM_BATCH_PROGRESS, {
                current,
                total,
                percent: Math.round((current / total) * 100),
            });
        }

        /**
         * Handle batch complete message.
         */
        _handleBatchComplete(payload) {
            const { results, totalTime, avgTimePerBand } = payload;

            console.log('SAMDecoderEngine: Batch complete', results.length, 'bands in', totalTime, 'ms');

            this.eventBus.emit(Events.SAM_BATCH_COMPLETE, {
                results,
                totalTime,
                avgTimePerBand,
            });

            if (this._batchResolve) {
                this._batchResolve(results);
                this._batchResolve = null;
                this._batchReject = null;
            }
        }

        /**
         * Handle error message.
         */
        _handleError(payload) {
            const { error, stage, type: errorType } = payload;

            console.error('SAMDecoderEngine: Error:', error, stage, errorType);

            this.eventBus.emit(Events.SAM_ERROR, { error, stage });

            // Reject pending promises based on error type
            if (errorType === 'INIT' || !this.isInitialized) {
                this.isInitializing = false;
                if (this._initReject) {
                    this._initReject(new Error(error));
                    this._initReject = null;
                    this._initResolve = null;
                }
            }

            if (this._embeddingsReject) {
                this._embeddingsReject(new Error(error));
                this._embeddingsReject = null;
                this._embeddingsResolve = null;
            }

            if (this._refinementReject) {
                this._refinementReject(new Error(error));
                this._refinementReject = null;
                this._refinementResolve = null;
            }

            if (this._batchReject) {
                this._batchReject(new Error(error));
                this._batchReject = null;
                this._batchResolve = null;
            }

            this.isBusy = false;
        }

        /**
         * Handle worker errors.
         */
        _handleWorkerError(error) {
            console.error('SAMDecoderEngine: Worker error:', error);
            this._handleError({ error: error.message || 'Worker error', stage: 'worker' });
        }

        /**
         * Check if ready for refinement.
         * @returns {boolean}
         */
        isReady() {
            return this.isInitialized && this.hasEmbeddings && !this.isBusy;
        }

        /**
         * Get current state.
         * @returns {Object}
         */
        getState() {
            return {
                isInitialized: this.isInitialized,
                isInitializing: this.isInitializing,
                hasEmbeddings: this.hasEmbeddings,
                isBusy: this.isBusy,
                embeddingInfo: this.embeddingInfo,
            };
        }

        /**
         * Clean up resources.
         */
        destroy() {
            if (this.worker) {
                this.worker.terminate();
                this.worker = null;
            }

            this.isInitialized = false;
            this.isInitializing = false;
            this.hasEmbeddings = false;
            this.isBusy = false;
            this.embeddingInfo = null;
        }
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.SAMDecoderEngine = SAMDecoderEngine;

})(window);
