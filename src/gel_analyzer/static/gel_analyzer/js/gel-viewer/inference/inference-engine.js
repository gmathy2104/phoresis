/**
 * inference-engine.js
 *
 * Main orchestrator for YOLO inference.
 * Manages Web Worker communication and provides a clean API for the application.
 *
 * @requires GelViewer.InferenceUtils
 * @requires inference-worker.js (Web Worker)
 */

(function(global) {
    'use strict';

    // Import utilities
    const InferenceUtils = global.GelViewer.InferenceUtils;
    const Events = global.GelViewer.Events;

    /**
     * InferenceEngine Class
     *
     * Handles model loading, inference execution, and result handling.
     * Uses a Web Worker for non-blocking inference.
     */
    class InferenceEngine {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus - Event bus for communication
         * @param {string} options.modelUrl - URL to ONNX model file
         * @param {number} options.imageWidth - Original image width
         * @param {number} options.imageHeight - Original image height
         * @param {number} [options.confidenceThreshold=0.5] - Detection confidence threshold
         * @param {number} [options.nmsThreshold=0.45] - NMS IoU threshold
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.modelUrl = options.modelUrl || '/static/gel_analyzer/ml/gel_analysis.onnx';
            this.imageWidth = options.imageWidth;
            this.imageHeight = options.imageHeight;
            this.confidenceThreshold = options.confidenceThreshold || 0.5;
            this.nmsThreshold = options.nmsThreshold || 0.45;

            // Worker state
            this.worker = null;
            this.isModelLoaded = false;
            this.isInferring = false;
            this.isInitializing = false;

            // Promise resolvers for async operations
            this._loadPromise = null;
            this._inferencePromise = null;
            this._loadResolve = null;
            this._loadReject = null;
            this._inferenceResolve = null;
            this._inferenceReject = null;

            // Last results for reference
            this.lastResults = null;
        }

        /**
         * Initialize the inference engine.
         * Creates the Web Worker and loads the model.
         * @returns {Promise<void>}
         */
        async initialize() {
            if (this.isModelLoaded) {
                return; // Already initialized
            }

            if (this.isInitializing) {
                return this._loadPromise; // Wait for existing initialization
            }

            this.isInitializing = true;

            try {
                // Create new promise for initialization
                this._loadPromise = new Promise((resolve, reject) => {
                    this._loadResolve = resolve;
                    this._loadReject = reject;
                });

                // Emit start event
                this.eventBus.emit(Events.INFERENCE_STARTED, { stage: 'initializing' });

                // Create Web Worker
                const workerUrl = this._getWorkerUrl();
                this.worker = new Worker(workerUrl);

                // Setup message handler
                this.worker.onmessage = (event) => this._handleWorkerMessage(event);
                this.worker.onerror = (error) => this._handleWorkerError(error);

                // Send load model command
                this.worker.postMessage({
                    type: 'LOAD_MODEL',
                    payload: { modelUrl: this.modelUrl },
                });

                // Wait for model to load
                await this._loadPromise;

            } catch (error) {
                this.isInitializing = false;
                throw error;
            }
        }

        /**
         * Get the Worker script URL.
         * Uses the same static path structure as other modules.
         * @returns {string}
         */
        _getWorkerUrl() {
            // The worker file is in the same directory
            return '/static/gel_analyzer/js/gel-viewer/inference/inference-worker.js';
        }

        /**
         * Run inference on an image element.
         * @param {HTMLImageElement} imageElement - The image to analyze
         * @returns {Promise<Object>} Detection results
         */
        async runInference(imageElement) {
            if (!this.isModelLoaded) {
                await this.initialize();
            }

            if (this.isInferring) {
                throw new Error('Inference already in progress');
            }

            this.isInferring = true;

            try {
                // Create promise for inference
                this._inferencePromise = new Promise((resolve, reject) => {
                    this._inferenceResolve = resolve;
                    this._inferenceReject = reject;
                });

                // Emit start event
                this.eventBus.emit(Events.INFERENCE_STARTED, { stage: 'preprocessing' });

                // Preprocess image (async to handle CORS if needed)
                console.log('InferenceEngine: Preprocessing image...');
                const { tensor, metadata } = await InferenceUtils.prepareImageForInference(imageElement);
                console.log('InferenceEngine: Image preprocessed', {
                    tensorLength: tensor.length,
                    metadata: metadata
                });

                // Send to worker
                console.log('InferenceEngine: Sending to worker...');
                this.worker.postMessage({
                    type: 'RUN_INFERENCE',
                    payload: {
                        imageData: {
                            tensor,
                            width: InferenceUtils.YOLO_CONFIG.INPUT_SIZE,
                            height: InferenceUtils.YOLO_CONFIG.INPUT_SIZE,
                        },
                        metadata,
                        config: {
                            confidenceThreshold: this.confidenceThreshold,
                            nmsThreshold: this.nmsThreshold,
                        },
                    },
                });

                // Wait for results
                console.log('InferenceEngine: Waiting for worker results...');
                const results = await this._inferencePromise;
                console.log('InferenceEngine: Results received', results);

                this.lastResults = results;
                return results;

            } finally {
                this.isInferring = false;
            }
        }

        /**
         * Cancel ongoing inference.
         */
        cancel() {
            if (this.worker && this.isInferring) {
                this.worker.postMessage({ type: 'CANCEL', payload: {} });

                // Reject pending promise
                if (this._inferenceReject) {
                    this._inferenceReject(new Error('Inference cancelled'));
                    this._inferenceReject = null;
                    this._inferenceResolve = null;
                }

                this.isInferring = false;
            }
        }

        /**
         * Get inferred gel type from detections.
         * @param {Array<Object>} detections - Detection results
         * @returns {string} 'SDS_PAGE', 'DOT_BLOT', or 'UNKNOWN'
         */
        getInferredGelType(detections) {
            const classes = new Set(detections.map(d => d.class_name));

            const hasMarker = classes.has('marker_lane');
            const hasSample = classes.has('sample_lane');
            const hasDot = classes.has('dot_lane');

            if (hasMarker && hasSample) {
                return 'SDS_PAGE';
            } else if (hasDot && !hasMarker && !hasSample) {
                return 'DOT_BLOT';
            } else if (hasSample || hasMarker) {
                return 'SDS_PAGE';
            }

            return 'UNKNOWN';
        }

        /**
         * Sort detections by X position for lane numbering.
         * @param {Array<Object>} detections - Detection results
         * @returns {Array<Object>} Sorted detections
         */
        sortDetectionsByPosition(detections) {
            return [...detections].sort((a, b) => a.bbox[0] - b.bbox[0]);
        }

        /**
         * Handle messages from the Web Worker.
         * @param {MessageEvent} event
         */
        _handleWorkerMessage(event) {
            const { type, payload } = event.data;
            console.log('InferenceEngine: Worker message received:', type, payload);

            switch (type) {
                case 'MODEL_LOADED':
                    this._handleModelLoaded(payload);
                    break;

                case 'INFERENCE_PROGRESS':
                    this._handleInferenceProgress(payload);
                    break;

                case 'INFERENCE_COMPLETE':
                    this._handleInferenceComplete(payload);
                    break;

                case 'INFERENCE_ERROR':
                    this._handleInferenceError(payload);
                    break;

                default:
                    console.warn('InferenceEngine: Unknown message type:', type);
            }
        }

        /**
         * Handle model loaded message.
         */
        _handleModelLoaded(payload) {
            if (payload.success) {
                this.isModelLoaded = true;
                this.isInitializing = false;

                console.log('InferenceEngine: Model loaded', {
                    inputs: payload.inputNames,
                    outputs: payload.outputNames,
                });

                if (this._loadResolve) {
                    this._loadResolve();
                    this._loadResolve = null;
                    this._loadReject = null;
                }
            } else {
                this._handleInferenceError({ error: 'Model load failed', stage: 'loading' });
            }
        }

        /**
         * Handle inference progress message.
         */
        _handleInferenceProgress(payload) {
            const { stage, progress, message } = payload;

            this.eventBus.emit(Events.INFERENCE_PROGRESS, {
                stage,
                progress,
                message,
            });
        }

        /**
         * Handle inference complete message.
         */
        _handleInferenceComplete(payload) {
            const { detections, inferredGelType, metadata } = payload;

            // Sort detections by position
            const sortedDetections = this.sortDetectionsByPosition(detections);

            const results = {
                detections: sortedDetections,
                inferredGelType,
                metadata,
            };

            // Emit completion event
            this.eventBus.emit(Events.INFERENCE_COMPLETED, results);

            // Resolve promise
            if (this._inferenceResolve) {
                this._inferenceResolve(results);
                this._inferenceResolve = null;
                this._inferenceReject = null;
            }
        }

        /**
         * Handle inference error message.
         */
        _handleInferenceError(payload) {
            const { error, stage, cancelled } = payload;

            console.error('InferenceEngine: Error', { error, stage, cancelled });

            // Emit error event
            this.eventBus.emit(Events.INFERENCE_ERROR, {
                error,
                stage,
                cancelled: cancelled || false,
            });

            // Reject pending promises
            if (this._loadReject && (stage === 'loading' || !this.isModelLoaded)) {
                this.isInitializing = false;
                this._loadReject(new Error(error));
                this._loadReject = null;
                this._loadResolve = null;
            }

            if (this._inferenceReject) {
                this._inferenceReject(new Error(error));
                this._inferenceReject = null;
                this._inferenceResolve = null;
            }
        }

        /**
         * Handle Worker errors.
         */
        _handleWorkerError(error) {
            console.error('InferenceEngine: Worker error', error);

            this.eventBus.emit(Events.INFERENCE_ERROR, {
                error: error.message || 'Worker error',
                stage: 'worker',
            });

            // Reject pending promises
            const err = new Error(error.message || 'Worker error');

            if (this._loadReject) {
                this.isInitializing = false;
                this._loadReject(err);
                this._loadReject = null;
                this._loadResolve = null;
            }

            if (this._inferenceReject) {
                this._inferenceReject(err);
                this._inferenceReject = null;
                this._inferenceResolve = null;
            }
        }

        /**
         * Check if the engine is ready for inference.
         * @returns {boolean}
         */
        isReady() {
            return this.isModelLoaded && !this.isInferring;
        }

        /**
         * Get current state.
         * @returns {Object}
         */
        getState() {
            return {
                isModelLoaded: this.isModelLoaded,
                isInferring: this.isInferring,
                isInitializing: this.isInitializing,
                hasResults: this.lastResults !== null,
            };
        }

        /**
         * Update configuration.
         * @param {Object} config
         */
        setConfig(config) {
            if (config.confidenceThreshold !== undefined) {
                this.confidenceThreshold = config.confidenceThreshold;
            }
            if (config.nmsThreshold !== undefined) {
                this.nmsThreshold = config.nmsThreshold;
            }
        }

        /**
         * Clean up resources.
         */
        destroy() {
            this.cancel();

            if (this.worker) {
                this.worker.terminate();
                this.worker = null;
            }

            this.isModelLoaded = false;
            this.isInferring = false;
            this.isInitializing = false;
            this.lastResults = null;
        }
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.InferenceEngine = InferenceEngine;

})(window);
