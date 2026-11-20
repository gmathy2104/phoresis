/**
 * inference-worker.js
 *
 * Web Worker for ONNX Runtime Web inference.
 * Runs in a separate thread to prevent UI blocking during model execution.
 *
 * Communication Protocol:
 * - Main -> Worker: { type: 'LOAD_MODEL' | 'RUN_INFERENCE' | 'CANCEL', payload: {...} }
 * - Worker -> Main: { type: 'MODEL_LOADED' | 'INFERENCE_PROGRESS' | 'INFERENCE_COMPLETE' | 'INFERENCE_ERROR', payload: {...} }
 *
 * @requires ONNX Runtime Web (vendored: js/vendor/onnxruntime/)
 */

// ONNX Runtime Web, vendored (js/vendor/onnxruntime/, no CDN: AGENTS.md §1). Found relative to this worker's
// own URL, so it works whatever prefix the static files are served under.
const ORT_BASE = new URL('../../vendor/onnxruntime/', self.location.href).href;
importScripts(`${ORT_BASE}ort.min.js`);

// The WebAssembly files sit beside ort.min.js.
ort.env.wasm.wasmPaths = ORT_BASE;

// Disable multi-threading to avoid crossOriginIsolated requirement
ort.env.wasm.numThreads = 1;

// Enable verbose logging for debugging
ort.env.debug = true;
ort.env.logLevel = 'verbose';

// Worker state
let session = null;
let isModelLoaded = false;
let isCancelled = false;

/**
 * YOLO model configuration
 */
const CONFIG = {
    INPUT_SIZE: 640,
    NUM_CLASSES: 4,
    NUM_MASK_COEFFS: 32,
    CLASS_NAMES: {
        0: 'marker_lane',
        1: 'sample_lane',
        2: 'smear',
        3: 'dot_lane',
    },
    CLASS_TO_LANE_TYPE: {
        'marker_lane': 'LADDER',
        'sample_lane': 'SAMPLE',
        'smear': 'SAMPLE',
        'dot_lane': 'DOT',
    },
};

/**
 * Send message to main thread.
 * Note: Named sendToMain to avoid conflict with native self.postMessage in Web Worker scope.
 */
function sendToMain(type, payload = {}) {
    self.postMessage({ type, payload });
}

/**
 * Send progress update to main thread.
 */
function reportProgress(stage, progress, message = '') {
    sendToMain('INFERENCE_PROGRESS', { stage, progress, message });
}

/**
 * Handle incoming messages from main thread.
 */
self.onmessage = async function(event) {
    const { type, payload } = event.data;

    switch (type) {
        case 'LOAD_MODEL':
            await loadModel(payload);
            break;

        case 'RUN_INFERENCE':
            await runInference(payload);
            break;

        case 'CANCEL':
            isCancelled = true;
            break;

        default:
            console.warn('InferenceWorker: Unknown message type:', type);
    }
};

/**
 * Load ONNX model into inference session.
 */
async function loadModel({ modelUrl }) {
    try {
        reportProgress('loading', 0, 'Initializing ONNX Runtime...');

        // Set ONNX Runtime execution providers
        // WebAssembly is most compatible, WebGL can be faster but less reliable
        const options = {
            executionProviders: ['wasm'],
            graphOptimizationLevel: 'all',
        };

        reportProgress('loading', 20, 'Fetching model...');

        // Fetch the model file
        const response = await fetch(modelUrl);
        if (!response.ok) {
            throw new Error(`Failed to fetch model: ${response.status} ${response.statusText}`);
        }

        reportProgress('loading', 50, 'Loading model...');

        const modelBuffer = await response.arrayBuffer();
        console.log('InferenceWorker: Model buffer size:', modelBuffer.byteLength, 'bytes');

        // Verify this is an ONNX file (magic bytes: 0x08 for protobuf or ONNX header)
        const headerView = new Uint8Array(modelBuffer.slice(0, 20));
        console.log('InferenceWorker: Model header bytes:', Array.from(headerView).map(b => b.toString(16).padStart(2, '0')).join(' '));

        reportProgress('loading', 70, 'Creating inference session...');

        // Create inference session
        session = await ort.InferenceSession.create(modelBuffer, options);

        isModelLoaded = true;

        reportProgress('loading', 100, 'Model loaded successfully');

        // Report model info
        const inputNames = session.inputNames;
        const outputNames = session.outputNames;

        sendToMain('MODEL_LOADED', {
            success: true,
            inputNames,
            outputNames,
        });

    } catch (error) {
        console.error('InferenceWorker: Error loading model:', error);
        // Handle both Error objects and raw values (ONNX Runtime sometimes throws non-Error)
        const errorMessage = error instanceof Error
            ? error.message
            : (typeof error === 'string' ? error : JSON.stringify(error));
        sendToMain('INFERENCE_ERROR', {
            error: `Failed to load model: ${errorMessage}`,
            stage: 'loading',
        });
    }
}

/**
 * Run inference on image data.
 */
async function runInference({ imageData, metadata, config }) {
    if (!isModelLoaded || !session) {
        sendToMain('INFERENCE_ERROR', {
            error: 'Model not loaded',
            stage: 'inference',
        });
        return;
    }

    isCancelled = false;

    try {
        reportProgress('preprocessing', 0, 'Preparing image...');

        // Image is already preprocessed by main thread
        // imageData is { tensor: Float32Array, width, height }
        const { tensor, width, height } = imageData;

        if (isCancelled) return reportCancelled();

        reportProgress('preprocessing', 100, 'Image prepared');

        // Create input tensor
        reportProgress('inference', 0, 'Running detection...');

        const inputTensor = new ort.Tensor('float32', tensor, [1, 3, height, width]);

        if (isCancelled) return reportCancelled();

        // Run inference
        const feeds = {};
        feeds[session.inputNames[0]] = inputTensor;

        reportProgress('inference', 30, 'Processing...');

        const results = await session.run(feeds);

        if (isCancelled) return reportCancelled();

        reportProgress('inference', 70, 'Extracting results...');

        // Parse output
        const detections = parseOutput(results, {
            confidenceThreshold: config.confidenceThreshold || 0.5,
            nmsThreshold: config.nmsThreshold || 0.45,
            inputSize: CONFIG.INPUT_SIZE,
        });

        if (isCancelled) return reportCancelled();

        reportProgress('postprocessing', 50, 'Scaling coordinates...');

        // Scale detections back to original image coordinates
        const scaledDetections = scaleDetections(detections, metadata);

        reportProgress('postprocessing', 100, 'Complete');

        // Infer gel type
        const inferredGelType = inferGelType(scaledDetections);

        // Send results
        sendToMain('INFERENCE_COMPLETE', {
            detections: scaledDetections,
            inferredGelType,
            metadata: {
                totalDetections: scaledDetections.length,
                byClass: countByClass(scaledDetections),
            },
        });

    } catch (error) {
        console.error('InferenceWorker: Inference error:', error);
        sendToMain('INFERENCE_ERROR', {
            error: `Inference failed: ${error.message}`,
            stage: 'inference',
        });
    }
}

/**
 * Report cancellation.
 */
function reportCancelled() {
    sendToMain('INFERENCE_ERROR', {
        error: 'Inference cancelled',
        stage: 'cancelled',
        cancelled: true,
    });
}

/**
 * Compute bounding rectangle from mask coefficients and prototypes.
 * Returns {x, y, width, height} based on actual mask boundaries.
 *
 * @param {Float32Array} coeffs - 32 mask coefficients from detection
 * @param {Float32Array} protoData - Mask prototype tensor data
 * @param {Array<number>} protoDims - [1, 32, 160, 160]
 * @param {Array<number>} bbox - Original bbox [x, y, w, h] for search region
 * @param {number} inputSize - YOLO input size (640)
 * @returns {{x: number, y: number, width: number, height: number}}
 */
function computeMaskBounds(coeffs, protoData, protoDims, bbox, inputSize) {
    const [_, numProtos, protoH, protoW] = protoDims;  // [1, 32, 160, 160]
    const [bx, by, bw, bh] = bbox;

    // Scale bbox to prototype resolution (640 → 160 = /4)
    const scale = protoW / inputSize;  // 0.25
    const px = Math.max(0, Math.floor(bx * scale) - 2);  // Expand search region slightly
    const py = Math.max(0, Math.floor(by * scale) - 2);
    const px2 = Math.min(protoW, Math.ceil((bx + bw) * scale) + 2);
    const py2 = Math.min(protoH, Math.ceil((by + bh) * scale) + 2);

    // Find mask boundaries
    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;
    const threshold = 0.5;

    for (let y = py; y < py2; y++) {
        for (let x = px; x < px2; x++) {
            // Compute mask value: sum(coeffs[i] * protos[i,y,x])
            let sum = 0;
            for (let p = 0; p < numProtos && p < coeffs.length; p++) {
                const protoIdx = p * protoH * protoW + y * protoW + x;
                sum += coeffs[p] * protoData[protoIdx];
            }
            const maskValue = 1 / (1 + Math.exp(-sum));  // Sigmoid

            if (maskValue > threshold) {
                if (x < minX) minX = x;
                if (x > maxX) maxX = x;
                if (y < minY) minY = y;
                if (y > maxY) maxY = y;
            }
        }
    }

    // Check if we found valid mask pixels
    if (minX === Infinity) {
        // Fallback to original bbox
        return { x: bx, y: by, width: bw, height: bh };
    }

    // Scale back to input resolution (160 → 640 = *4)
    const invScale = inputSize / protoW;  // 4
    return {
        x: Math.round(minX * invScale),
        y: Math.round(minY * invScale),
        width: Math.round((maxX - minX + 1) * invScale),
        height: Math.round((maxY - minY + 1) * invScale),
    };
}

/**
 * Parse YOLO output tensors.
 */
function parseOutput(results, config) {
    const { confidenceThreshold, nmsThreshold, inputSize } = config;

    // Get output tensors
    const outputKeys = Object.keys(results);
    if (outputKeys.length === 0) {
        console.error('No output tensors found');
        return [];
    }

    // YOLOv8 seg typically has two outputs:
    // - output0: detections [1, num_features, num_boxes]
    // - output1: mask protos [1, 32, mask_h, mask_w]
    const detOutput = results['output0'] || results[outputKeys[0]];
    const maskProtos = results['output1'] || results[outputKeys[1]] || null;

    // Extract prototype data for mask computation
    const protoData = maskProtos ? maskProtos.data : null;
    const protoDims = maskProtos ? maskProtos.dims : null;

    const detData = detOutput.data;
    const detDims = detOutput.dims;

    // Determine format and dimensions
    let numBoxes, featuresPerBox, isTransposed;

    if (detDims.length === 3) {
        // [1, features, num_boxes] - transposed format (YOLOv8)
        featuresPerBox = detDims[1];
        numBoxes = detDims[2];
        isTransposed = true;
    } else if (detDims.length === 2) {
        // [num_boxes, features] - standard format
        numBoxes = detDims[0];
        featuresPerBox = detDims[1];
        isTransposed = false;
    } else {
        console.error('Unexpected output dimensions:', detDims);
        return [];
    }

    // Parse features: 4 (xywh) + num_classes + 32 (mask coeffs)
    const numClasses = CONFIG.NUM_CLASSES;
    const numMaskCoeffs = Math.min(CONFIG.NUM_MASK_COEFFS, featuresPerBox - 4 - numClasses);

    const rawDetections = [];

    for (let i = 0; i < numBoxes; i++) {
        let cx, cy, w, h;
        const classScores = [];
        const maskCoeffs = [];

        if (isTransposed) {
            // Transposed: [1, features, boxes]
            cx = detData[0 * numBoxes + i];
            cy = detData[1 * numBoxes + i];
            w = detData[2 * numBoxes + i];
            h = detData[3 * numBoxes + i];

            for (let c = 0; c < numClasses; c++) {
                classScores.push(detData[(4 + c) * numBoxes + i]);
            }

            for (let m = 0; m < numMaskCoeffs; m++) {
                maskCoeffs.push(detData[(4 + numClasses + m) * numBoxes + i]);
            }
        } else {
            // Standard: [boxes, features]
            const offset = i * featuresPerBox;
            cx = detData[offset];
            cy = detData[offset + 1];
            w = detData[offset + 2];
            h = detData[offset + 3];

            for (let c = 0; c < numClasses; c++) {
                classScores.push(detData[offset + 4 + c]);
            }

            for (let m = 0; m < numMaskCoeffs; m++) {
                maskCoeffs.push(detData[offset + 4 + numClasses + m]);
            }
        }

        // Find best class
        let maxScore = 0;
        let classId = 0;
        for (let c = 0; c < classScores.length; c++) {
            if (classScores[c] > maxScore) {
                maxScore = classScores[c];
                classId = c;
            }
        }

        // Skip low confidence
        if (maxScore < confidenceThreshold) continue;

        // Convert center to corner format
        const x = cx - w / 2;
        const y = cy - h / 2;

        // Skip invalid boxes
        if (w <= 0 || h <= 0) continue;

        rawDetections.push({
            class_id: classId,
            class_name: CONFIG.CLASS_NAMES[classId] || 'unknown',
            confidence: maxScore,
            bbox: [x, y, w, h],
            mask_coeffs: maskCoeffs,
            lane_type: CONFIG.CLASS_TO_LANE_TYPE[CONFIG.CLASS_NAMES[classId]] || 'SAMPLE',
        });
    }

    // Apply NMS
    const nmsDetections = applyNMS(rawDetections, nmsThreshold);

    // Apply 20% width shrink to approximate lane boundaries
    // (mask-based bounds were too wide - keeping computeMaskBounds() for future use)
    for (const det of nmsDetections) {
        // The detection's own mask axis, BEFORE the shrink rewrites its box (spec 2026-10-10 §10): the review's
        // "Follow the lanes" tilts the lane by it. scaleDetections turns it into image space.
        det.mask_slope_640 = (protoData && protoDims && det.mask_coeffs && det.mask_coeffs.length)
            ? maskSlope(det.mask_coeffs, protoData, protoDims, det.bbox)
            : null;

        const [x, y, w, h] = det.bbox;

        // Shrink width by 20% (10% from each side)
        const shrinkFactor = 0.20;
        const shrinkAmount = w * shrinkFactor;
        const newX = x + (shrinkAmount / 2);
        const newW = w - shrinkAmount;

        det.bbox = [Math.round(newX), Math.round(y), Math.round(newW), Math.round(h)];

        // Create rectangle polygon from adjusted bounds
        det.polygon = [
            [Math.round(newX), Math.round(y)],
            [Math.round(newX + newW), Math.round(y)],
            [Math.round(newX + newW), Math.round(y + h)],
            [Math.round(newX), Math.round(y + h)],
        ];

        // Clean up mask coefficients
        delete det.mask_coeffs;
    }

    return nmsDetections;
}

/**
 * Slope d(x)/d(y) of the line through a detection's mask row centres, in model-input (640) space; null with fewer
 * than 2 mask rows. tools/proofs/lane_tilt/capture.js::maskAxes VERBATIM -- the fit the lane-tilt bench validated
 * (spec 2026-10-10 §9-§10): the raw box, 3 extra proto columns each side, a pixel in the mask when
 * sum(coeff * proto) > 0 (sigmoid > 0.5), a row's centre = the middle of its first and last mask pixels.
 * Never "simplify" it: the bench's numbers are this fit's.
 */
function maskSlope(coeffs, protoData, protoDims, bbox) {
    const PH = protoDims[2], PW = protoDims[3], NM = coeffs.length;
    const stride = CONFIG.INPUT_SIZE / PW;
    const [bx, by, bw, bh] = bbox;
    const px1 = Math.max(0, Math.floor(bx / stride) - 3), px2 = Math.min(PW - 1, Math.ceil((bx + bw) / stride) + 3);
    const py1 = Math.max(0, Math.floor(by / stride)), py2 = Math.min(PH - 1, Math.ceil((by + bh) / stride));
    const pts = [];
    for (let y = py1; y <= py2; y++) {
        let lo = -1, hi = -1;
        for (let x = px1; x <= px2; x++) {
            let s = 0;
            for (let p = 0; p < NM; p++) s += coeffs[p] * protoData[p * PH * PW + y * PW + x];
            if (s > 0) { if (lo < 0) lo = x; hi = x; }
        }
        if (lo >= 0) pts.push([(y + 0.5) * stride, ((lo + hi) / 2 + 0.5) * stride]);
    }
    const n = pts.length;
    if (n < 2) return null;
    const my = pts.reduce((a, p) => a + p[0], 0) / n, mx = pts.reduce((a, p) => a + p[1], 0) / n;
    const sxy = pts.reduce((a, p) => a + (p[0] - my) * (p[1] - mx), 0);
    const syy = pts.reduce((a, p) => a + (p[0] - my) ** 2, 0);
    return syy > 0 ? sxy / syy : 0;
}

/**
 * Apply Non-Maximum Suppression.
 */
function applyNMS(detections, iouThreshold) {
    if (detections.length === 0) return [];

    // Sort by confidence descending
    const sorted = [...detections].sort((a, b) => b.confidence - a.confidence);

    const kept = [];
    const suppressed = new Set();

    for (let i = 0; i < sorted.length; i++) {
        if (suppressed.has(i)) continue;

        kept.push(sorted[i]);

        for (let j = i + 1; j < sorted.length; j++) {
            if (suppressed.has(j)) continue;

            const iou = calculateIoU(sorted[i].bbox, sorted[j].bbox);
            if (iou > iouThreshold) {
                suppressed.add(j);
            }
        }
    }

    return kept;
}

/**
 * Calculate IoU between two boxes [x, y, w, h].
 */
function calculateIoU(boxA, boxB) {
    const [ax, ay, aw, ah] = boxA;
    const [bx, by, bw, bh] = boxB;

    const x1 = Math.max(ax, bx);
    const y1 = Math.max(ay, by);
    const x2 = Math.min(ax + aw, bx + bw);
    const y2 = Math.min(ay + ah, by + bh);

    const intersection = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
    const union = aw * ah + bw * bh - intersection;

    return union > 0 ? intersection / union : 0;
}

/**
 * Scale detections from YOLO input space to original image space.
 */
function scaleDetections(detections, metadata) {
    const { offsetX, offsetY, scaleX, scaleY, originalWidth, originalHeight } = metadata;

    return detections.map(det => {
        // Scale bbox
        const [x, y, w, h] = det.bbox;
        const scaledX = Math.round((x - offsetX) * scaleX);
        const scaledY = Math.round((y - offsetY) * scaleY);
        const scaledW = Math.round(w * scaleX);
        const scaledH = Math.round(h * scaleY);

        // Clamp to image bounds
        const clampedX = Math.max(0, Math.min(scaledX, originalWidth - 1));
        const clampedY = Math.max(0, Math.min(scaledY, originalHeight - 1));
        const clampedW = Math.min(scaledW, originalWidth - clampedX);
        const clampedH = Math.min(scaledH, originalHeight - clampedY);

        // Scale polygon
        const scaledPolygon = det.polygon.map(([px, py]) => {
            const sx = Math.round((px - offsetX) * scaleX);
            const sy = Math.round((py - offsetY) * scaleY);
            return [
                Math.max(0, Math.min(sx, originalWidth - 1)),
                Math.max(0, Math.min(sy, originalHeight - 1)),
            ];
        });

        // A slope in model-input space becomes one in image space by the two axes' scales (spec 2026-10-10 §10).
        const maskSlopeImage = det.mask_slope_640 == null ? null : det.mask_slope_640 * scaleX / scaleY;
        const { mask_slope_640: _unused, ...rest } = det;

        return {
            ...rest,
            bbox: [clampedX, clampedY, clampedW, clampedH],
            polygon: scaledPolygon,
            mask_slope: maskSlopeImage,
        };
    });
}

/**
 * Infer gel type from detected classes.
 */
function inferGelType(detections) {
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
 * Count detections by class.
 */
function countByClass(detections) {
    const counts = {};
    for (const det of detections) {
        counts[det.class_name] = (counts[det.class_name] || 0) + 1;
    }
    return counts;
}
