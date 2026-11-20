/**
 * band-model-engine.js
 *
 * Main-thread side of the YOLO band model: one Web Worker (band-model-worker.js), the model loaded once per page,
 * detect(image) -> the model's boxes in image pixels. No server call here: BandModelPanel asks the server which model
 * to run (band-model/) and what the boxes mean (band-model/preview/, save/).
 *
 * @example
 *   const engine = new GelViewer.BandModelEngine({ workerUrl });
 *   await engine.load({ modelUrl, sha256, onProgress: (p) => ... });   // {backend: 'webgpu'|'wasm', ...}
 *   const { boxes } = await engine.detect(imageElement, { window, imgsz, minConfidence, iou, maxDet }, onProgress);
 */

(function(global) {
    'use strict';

    class BandModelEngine {
        /**
         * @param {Object} options
         * @param {string} options.workerUrl - URL of band-model-worker.js ({% static %}, so hashed in production)
         */
        constructor(options) {
            this.workerUrl = options.workerUrl;
            this.worker = null;
            this.backend = null;
            this.webgpuError = null;
            this._loading = null;
            this._loadedKey = null;
            this._loadCallbacks = null;
            this._pending = new Map();
            this._nextId = 1;
        }

        /**
         * Load the model in the worker (once: a second call with the same model returns the same promise).
         * @param {Object} options - {modelUrl, sha256, backend: 'auto'|'wasm', onProgress}
         * @returns {Promise<{backend: string, webgpuError: ?string, verified: boolean}>}
         */
        load({ modelUrl, sha256, backend = 'auto', onProgress = null }) {
            const key = `${modelUrl}|${sha256}|${backend}`;
            if (this._loading && this._loadedKey === key) {
                return this._loading;
            }
            this.destroy();
            this._loadedKey = key;
            this.worker = new Worker(this.workerUrl);
            this.worker.onmessage = (event) => this._onMessage(event.data || {});
            this.worker.onerror = (event) => this._fail(new Error(event.message || 'The band model worker failed to start'));
            this._loading = new Promise((resolve, reject) => {
                this._loadCallbacks = { resolve, reject, onProgress };
            });
            this._loading.catch(() => {
                // A failed load is never reused: the next call starts again.
                this._loading = null;
                this._loadedKey = null;
            });
            this.worker.postMessage({ type: 'load', modelUrl, sha256, backend });
            return this._loading;
        }

        /**
         * Run the model on an <img> (same-origin: the editor's image proxy) at its natural size.
         * @param {HTMLImageElement} imageElement
         * @param {Object} options - {window: [x, y, w, h] | null, imgsz, minConfidence, iou, maxDet}
         * @param {Function} [onProgress] - called with {stage: 'preprocess'|'inference'|'postprocess'}
         * @returns {Promise<{boxes: number[][], input: number[], backend: string, timings: Object}>}
         */
        detect(imageElement, options, onProgress = null) {
            if (!this.worker || !this._loading) {
                return Promise.reject(new Error('The band model is not loaded'));
            }
            const width = imageElement.naturalWidth;
            const height = imageElement.naturalHeight;
            if (!width || !height) {
                return Promise.reject(new Error('The gel image is not loaded yet'));
            }
            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;
            const ctx = canvas.getContext('2d', { willReadFrequently: true });
            ctx.drawImage(imageElement, 0, 0);
            const pixels = ctx.getImageData(0, 0, width, height);
            const id = this._nextId++;
            const result = new Promise((resolve, reject) => {
                this._pending.set(id, { resolve, reject, onProgress });
            });
            this.worker.postMessage(
                {
                    type: 'detect',
                    id,
                    rgba: pixels.data.buffer,
                    width,
                    height,
                    window: options.window || null,
                    imgsz: options.imgsz,
                    minConfidence: options.minConfidence,
                    iou: options.iou,
                    maxDet: options.maxDet,
                },
                [pixels.data.buffer],
            );
            return result;
        }

        destroy() {
            if (this.worker) {
                this.worker.terminate();
            }
            this.worker = null;
            this._fail(new Error('The band model was unloaded'));
            this._loading = null;
            this._loadedKey = null;
        }

        _onMessage(msg) {
            if (msg.type === 'progress') {
                if (msg.id != null) {
                    const job = this._pending.get(msg.id);
                    if (job && job.onProgress) job.onProgress(msg);
                } else if (this._loadCallbacks && this._loadCallbacks.onProgress) {
                    this._loadCallbacks.onProgress(msg);
                }
            } else if (msg.type === 'loaded') {
                this.backend = msg.backend;
                this.webgpuError = msg.webgpuError || null;
                if (this._loadCallbacks) {
                    this._loadCallbacks.resolve(msg);
                    this._loadCallbacks = null;
                }
            } else if (msg.type === 'detected') {
                const job = this._pending.get(msg.id);
                if (job) {
                    this._pending.delete(msg.id);
                    job.resolve(msg);
                }
            } else if (msg.type === 'error') {
                const error = new Error(msg.message || 'The band model failed');
                if (msg.id != null && this._pending.has(msg.id)) {
                    this._pending.get(msg.id).reject(error);
                    this._pending.delete(msg.id);
                } else {
                    this._fail(error);
                }
            }
        }

        _fail(error) {
            if (this._loadCallbacks) {
                this._loadCallbacks.reject(error);
                this._loadCallbacks = null;
            }
            for (const job of this._pending.values()) {
                job.reject(error);
            }
            this._pending.clear();
        }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.BandModelEngine = BandModelEngine;
})(window);
