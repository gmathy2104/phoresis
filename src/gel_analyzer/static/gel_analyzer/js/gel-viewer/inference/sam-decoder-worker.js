/**
 * sam-decoder-worker.js
 *
 * Web Worker for MobileSAM decoder inference.
 * Takes pre-computed image embeddings from the server and bounding box prompts
 * to generate precise segmentation masks for band polygon refinement.
 *
 * Based on: https://github.com/akbartus/MobileSAM-in-the-Browser
 *
 * Communication Protocol:
 * - Main -> Worker:
 *   - INIT: Initialize decoder with model URL
 *   - SET_EMBEDDINGS: Load image embeddings from server
 *   - REFINE_BAND: Generate mask for bounding box
 *   - REFINE_BANDS_BATCH: Process multiple bands
 *
 * - Worker -> Main:
 *   - READY: Decoder initialized
 *   - EMBEDDINGS_SET: Embeddings loaded
 *   - POLYGON_RESULT: Single band polygon result
 *   - BATCH_COMPLETE: Batch processing complete
 *   - ERROR: Error occurred
 *
 * @requires ONNX Runtime Web 1.14.0 (most compatible with MobileSAM)
 */

// Use ONNX Runtime Web 1.14.0 as recommended by MobileSAM-in-the-Browser
// Newer versions have compatibility issues with the decoder
importScripts('https://cdn.jsdelivr.net/npm/onnxruntime-web@1.14.0/dist/ort.min.js');

// Configure ONNX Runtime
ort.env.wasm.wasmPaths = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.14.0/dist/';
ort.env.wasm.numThreads = 1;

// Worker state
let decoderSession = null;
let isInitialized = false;
let imageEmbeddings = null;
let embeddingsShape = null;
let originalSize = null;
let inputSize = null;

/**
 * Send message to main thread.
 */
function sendToMain(type, payload = {}) {
    self.postMessage({ type, payload });
}

/**
 * Handle incoming messages from main thread.
 */
self.onmessage = async function(event) {
    const { type, payload } = event.data;

    try {
        switch (type) {
            case 'INIT':
                await initDecoder(payload);
                break;

            case 'SET_EMBEDDINGS':
                await setEmbeddings(payload);
                break;

            case 'REFINE_BAND':
                await refineBand(payload);
                break;

            case 'REFINE_BANDS_BATCH':
                await refineBandsBatch(payload);
                break;

            default:
                console.warn('SAMDecoderWorker: Unknown message type:', type);
        }
    } catch (error) {
        console.error('SAMDecoderWorker: Error:', error);
        sendToMain('ERROR', {
            error: error.message || String(error),
            type: type,
        });
    }
};

/**
 * Initialize the MobileSAM decoder.
 */
async function initDecoder({ modelUrl, useQuantized = true }) {
    try {
        console.log('SAMDecoderWorker: Initializing decoder...');

        // Default model path if not provided
        if (!modelUrl) {
            const basePath = '/static/gel_analyzer/ml/sam/';
            modelUrl = useQuantized
                ? `${basePath}mobilesam_decoder_quant.onnx`
                : `${basePath}mobilesam_decoder.onnx`;
        }

        console.log('SAMDecoderWorker: Loading model from:', modelUrl);

        // Create session with WASM execution provider
        const options = {
            executionProviders: ['wasm'],
            graphOptimizationLevel: 'all',
        };

        // Fetch and load model
        const response = await fetch(modelUrl);
        if (!response.ok) {
            throw new Error(`Failed to fetch model: ${response.status}`);
        }

        const modelBuffer = await response.arrayBuffer();
        console.log('SAMDecoderWorker: Model size:', modelBuffer.byteLength, 'bytes');

        decoderSession = await ort.InferenceSession.create(modelBuffer, options);
        isInitialized = true;

        console.log('SAMDecoderWorker: Decoder initialized');
        console.log('SAMDecoderWorker: Input names:', decoderSession.inputNames);
        console.log('SAMDecoderWorker: Output names:', decoderSession.outputNames);

        sendToMain('READY', {
            inputNames: decoderSession.inputNames,
            outputNames: decoderSession.outputNames,
            useQuantized: useQuantized,
        });

    } catch (error) {
        console.error('SAMDecoderWorker: Failed to initialize:', error);
        sendToMain('ERROR', {
            error: `Decoder initialization failed: ${error.message}`,
            stage: 'init',
        });
    }
}

/**
 * Set image embeddings from server response.
 */
async function setEmbeddings({ embeddings, embeddingShape, dtype, origSize, inputSz }) {
    try {
        console.log('SAMDecoderWorker: Setting embeddings...');

        // Decode base64 embeddings
        const binaryString = atob(embeddings);
        const bytes = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
            bytes[i] = binaryString.charCodeAt(i);
        }

        // Convert to Float32Array
        const float32Data = new Float32Array(bytes.buffer);
        console.log('SAMDecoderWorker: Embeddings decoded, length:', float32Data.length);

        // Store embeddings and metadata
        imageEmbeddings = float32Data;
        embeddingsShape = embeddingShape;
        originalSize = origSize;
        inputSize = inputSz;

        console.log('SAMDecoderWorker: Embeddings shape:', embeddingsShape);
        console.log('SAMDecoderWorker: Original size:', originalSize);
        console.log('SAMDecoderWorker: Input size:', inputSize);

        sendToMain('EMBEDDINGS_SET', {
            shape: embeddingsShape,
            originalSize: originalSize,
            inputSize: inputSize,
        });

    } catch (error) {
        console.error('SAMDecoderWorker: Failed to set embeddings:', error);
        sendToMain('ERROR', {
            error: `Failed to set embeddings: ${error.message}`,
            stage: 'embeddings',
        });
    }
}

/**
 * Refine a single band polygon using bounding box prompt.
 */
async function refineBand({ bandId, bbox }) {
    if (!isInitialized || !decoderSession) {
        throw new Error('Decoder not initialized');
    }

    if (!imageEmbeddings) {
        throw new Error('Image embeddings not set');
    }

    console.log('SAMDecoderWorker: Refining band:', bandId, 'bbox:', bbox);

    const startTime = performance.now();

    // Run decoder
    const mask = await runDecoder(bbox);

    // Convert mask to polygon
    const polygon = maskToPolygon(mask.data, mask.width, mask.height, bbox);

    const elapsed = performance.now() - startTime;
    console.log('SAMDecoderWorker: Band refined in', elapsed.toFixed(1), 'ms');

    sendToMain('POLYGON_RESULT', {
        bandId: bandId,
        polygon: polygon,
        inferenceTime: elapsed,
    });

    return polygon;
}

/**
 * Refine multiple bands in batch.
 */
async function refineBandsBatch({ bands }) {
    if (!isInitialized || !decoderSession) {
        throw new Error('Decoder not initialized');
    }

    if (!imageEmbeddings) {
        throw new Error('Image embeddings not set');
    }

    console.log('SAMDecoderWorker: Processing batch of', bands.length, 'bands');

    const startTime = performance.now();
    const results = [];

    for (let i = 0; i < bands.length; i++) {
        const { bandId, bbox } = bands[i];

        try {
            // Run decoder for this band
            const mask = await runDecoder(bbox);

            // Convert mask to polygon
            const polygon = maskToPolygon(mask.data, mask.width, mask.height, bbox);

            results.push({
                bandId: bandId,
                polygon: polygon,
                success: true,
            });

        } catch (error) {
            console.error('SAMDecoderWorker: Error processing band:', bandId, error);
            results.push({
                bandId: bandId,
                error: error.message,
                success: false,
            });
        }

        // Report progress
        sendToMain('BATCH_PROGRESS', {
            current: i + 1,
            total: bands.length,
        });
    }

    const elapsed = performance.now() - startTime;
    console.log('SAMDecoderWorker: Batch complete in', elapsed.toFixed(1), 'ms');

    sendToMain('BATCH_COMPLETE', {
        results: results,
        totalTime: elapsed,
        avgTimePerBand: elapsed / bands.length,
    });

    return results;
}

/**
 * Run the decoder with a bounding box prompt.
 * Returns mask data at original image resolution.
 */
async function runDecoder(bbox) {
    // Extract bbox coordinates [x, y, width, height]
    const [bx, by, bw, bh] = bbox;

    // Convert bbox to SAM's point format:
    // For bounding box: use top-left and bottom-right corners
    // Labels: 2 = box top-left, 3 = box bottom-right
    const x1 = bx;
    const y1 = by;
    const x2 = bx + bw;
    const y2 = by + bh;

    // SAM preprocessing: resize to fit longest side = 1024, PRESERVING aspect ratio
    // Then pad to 1024x1024. Both X and Y must use the SAME scale factor!
    // Bug fix: was using different scaleX and scaleY which caused Y offset
    const SAM_INPUT_SIZE = 1024;
    const origH = originalSize[0];
    const origW = originalSize[1];
    const longestSide = Math.max(origH, origW);
    const scale = SAM_INPUT_SIZE / longestSide;  // uniform scale for both axes

    const scaledX1 = x1 * scale;
    const scaledY1 = y1 * scale;
    const scaledX2 = x2 * scale;
    const scaledY2 = y2 * scale;

    console.log(`SAM COORDS: original=(${origW}x${origH}), scale=${scale.toFixed(4)}, ` +
        `bbox=(${x1},${y1})-(${x2},${y2}) → scaled=(${scaledX1.toFixed(1)},${scaledY1.toFixed(1)})-(${scaledX2.toFixed(1)},${scaledY2.toFixed(1)})`);

    // Create input tensors
    // Point coordinates: [1, num_points, 2]
    const pointCoords = new ort.Tensor(
        'float32',
        new Float32Array([scaledX1, scaledY1, scaledX2, scaledY2]),
        [1, 2, 2]
    );

    // Point labels: 2 = box corner 1, 3 = box corner 2
    const pointLabels = new ort.Tensor(
        'float32',
        new Float32Array([2, 3]),
        [1, 2]
    );

    // Mask input (not using prior mask)
    const maskInput = new ort.Tensor(
        'float32',
        new Float32Array(256 * 256).fill(0),
        [1, 1, 256, 256]
    );

    // Has mask input flag (0 = no prior mask)
    const hasMaskInput = new ort.Tensor(
        'float32',
        new Float32Array([0]),
        [1]
    );

    // Original image size [H, W]
    const origImSize = new ort.Tensor(
        'float32',
        new Float32Array([originalSize[0], originalSize[1]]),
        [2]
    );

    // Image embeddings tensor
    const embeddingsTensor = new ort.Tensor(
        'float32',
        imageEmbeddings,
        embeddingsShape
    );

    // Build feeds
    const feeds = {
        'image_embeddings': embeddingsTensor,
        'point_coords': pointCoords,
        'point_labels': pointLabels,
        'mask_input': maskInput,
        'has_mask_input': hasMaskInput,
        'orig_im_size': origImSize,
    };

    // Run inference
    const results = await decoderSession.run(feeds);

    // Get mask output
    // Output is typically "masks" with shape [1, 1, H, W] or [1, 4, H, W]
    const maskTensor = results['masks'] || results[decoderSession.outputNames[0]];
    const maskData = maskTensor.data;
    const maskDims = maskTensor.dims;

    // If multiple masks, take the first (best IoU)
    const maskH = maskDims[2];
    const maskW = maskDims[3];
    const singleMaskSize = maskH * maskW;
    const mask = maskData.slice(0, singleMaskSize);

    return {
        data: mask,
        width: maskW,
        height: maskH,
    };
}

/**
 * Convert binary mask to polygon points.
 * Uses contour tracing to extract the mask boundary.
 */
function maskToPolygon(maskData, width, height, originalBbox) {
    // Apply sigmoid and threshold
    const threshold = 0.5;
    const binary = new Uint8Array(width * height);

    for (let i = 0; i < maskData.length; i++) {
        // Mask data might already be post-sigmoid
        const value = maskData[i] > 20 ? 1 / (1 + Math.exp(-maskData[i])) : maskData[i];
        binary[i] = value > threshold ? 1 : 0;
    }

    // Find contour using marching squares algorithm (simplified)
    const contour = findContour(binary, width, height);

    if (contour.length < 3) {
        // Fallback to bbox rectangle
        const [x, y, w, h] = originalBbox;
        return [
            [x, y],
            [x + w, y],
            [x + w, y + h],
            [x, y + h],
        ];
    }

    // Simplify contour using Ramer-Douglas-Peucker algorithm
    const simplified = simplifyPolygon(contour, 2.0);

    return simplified;
}

/**
 * Find contour in binary mask using simple boundary tracing.
 */
function findContour(binary, width, height) {
    const contour = [];

    // Find starting point (first foreground pixel)
    let startX = -1, startY = -1;
    outer: for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
            if (binary[y * width + x] === 1) {
                startX = x;
                startY = y;
                break outer;
            }
        }
    }

    if (startX === -1) {
        return contour;
    }

    // Moore neighbor tracing
    const dx = [1, 1, 0, -1, -1, -1, 0, 1];
    const dy = [0, 1, 1, 1, 0, -1, -1, -1];

    let x = startX, y = startY;
    let dir = 7;  // Start direction
    let visited = new Set();
    const maxIterations = width * height;
    let iterations = 0;

    do {
        const key = `${x},${y}`;
        if (!visited.has(key)) {
            contour.push([x, y]);
            visited.add(key);
        }

        // Find next boundary pixel
        let found = false;
        for (let i = 0; i < 8; i++) {
            const ndir = (dir + i + 6) % 8;  // Start from dir-2
            const nx = x + dx[ndir];
            const ny = y + dy[ndir];

            if (nx >= 0 && nx < width && ny >= 0 && ny < height) {
                if (binary[ny * width + nx] === 1) {
                    x = nx;
                    y = ny;
                    dir = ndir;
                    found = true;
                    break;
                }
            }
        }

        if (!found) break;

        iterations++;
    } while ((x !== startX || y !== startY) && iterations < maxIterations);

    return contour;
}

/**
 * Simplify polygon using Ramer-Douglas-Peucker algorithm.
 */
function simplifyPolygon(points, epsilon) {
    if (points.length < 3) return points;

    // Find point furthest from line between first and last
    let maxDist = 0;
    let maxIndex = 0;

    const start = points[0];
    const end = points[points.length - 1];

    for (let i = 1; i < points.length - 1; i++) {
        const dist = perpendicularDistance(points[i], start, end);
        if (dist > maxDist) {
            maxDist = dist;
            maxIndex = i;
        }
    }

    // If max distance is greater than epsilon, recursively simplify
    if (maxDist > epsilon) {
        const left = simplifyPolygon(points.slice(0, maxIndex + 1), epsilon);
        const right = simplifyPolygon(points.slice(maxIndex), epsilon);

        // Combine results (remove duplicate middle point)
        return left.slice(0, -1).concat(right);
    }

    // All points within epsilon, return just endpoints
    return [start, end];
}

/**
 * Calculate perpendicular distance from point to line.
 */
function perpendicularDistance(point, lineStart, lineEnd) {
    const [x, y] = point;
    const [x1, y1] = lineStart;
    const [x2, y2] = lineEnd;

    const dx = x2 - x1;
    const dy = y2 - y1;

    if (dx === 0 && dy === 0) {
        // Line is a point
        return Math.sqrt((x - x1) ** 2 + (y - y1) ** 2);
    }

    const t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy);
    const t_clamped = Math.max(0, Math.min(1, t));

    const nearestX = x1 + t_clamped * dx;
    const nearestY = y1 + t_clamped * dy;

    return Math.sqrt((x - nearestX) ** 2 + (y - nearestY) ** 2);
}
