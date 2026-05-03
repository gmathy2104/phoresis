/**
 * postprocess.js
 *
 * YOLO segmentation output postprocessing utilities.
 * Handles NMS, mask-to-polygon conversion, and gel type inference.
 *
 * @requires Nothing (vanilla JS)
 */

(function(global) {
    'use strict';

    /**
     * YOLO model class names mapping.
     * These are the classes the gel analysis model was trained on.
     */
    const CLASS_NAMES = {
        0: 'marker_lane',
        1: 'sample_lane',
        2: 'smear',
        3: 'dot_lane',
    };

    /**
     * Map YOLO class names to Lane model types.
     */
    const CLASS_TO_LANE_TYPE = {
        'marker_lane': 'LADDER',
        'sample_lane': 'SAMPLE',
        'smear': 'SAMPLE',      // Smears are typically in sample lanes
        'dot_lane': 'DOT',
    };

    /**
     * Calculate Intersection over Union (IoU) between two bounding boxes.
     * @param {Array} boxA - [x, y, width, height]
     * @param {Array} boxB - [x, y, width, height]
     * @returns {number} IoU value (0-1)
     */
    function calculateIoU(boxA, boxB) {
        const [ax, ay, aw, ah] = boxA;
        const [bx, by, bw, bh] = boxB;

        // Calculate intersection
        const x1 = Math.max(ax, bx);
        const y1 = Math.max(ay, by);
        const x2 = Math.min(ax + aw, bx + bw);
        const y2 = Math.min(ay + ah, by + bh);

        const intersectionWidth = Math.max(0, x2 - x1);
        const intersectionHeight = Math.max(0, y2 - y1);
        const intersectionArea = intersectionWidth * intersectionHeight;

        // Calculate union
        const areaA = aw * ah;
        const areaB = bw * bh;
        const unionArea = areaA + areaB - intersectionArea;

        if (unionArea === 0) return 0;

        return intersectionArea / unionArea;
    }

    /**
     * Non-Maximum Suppression (NMS) to filter overlapping detections.
     * @param {Array<Object>} detections - Array of detection objects
     * @param {number} iouThreshold - IoU threshold for suppression (default: 0.45)
     * @returns {Array<Object>} Filtered detections
     */
    function nms(detections, iouThreshold = 0.45) {
        if (detections.length === 0) return [];

        // Sort by confidence (descending)
        const sorted = [...detections].sort((a, b) => b.confidence - a.confidence);

        const kept = [];
        const suppressed = new Set();

        for (let i = 0; i < sorted.length; i++) {
            if (suppressed.has(i)) continue;

            kept.push(sorted[i]);

            // Suppress overlapping detections
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
     * Convert a binary mask to polygon points using contour tracing.
     * Simplified marching squares algorithm.
     * @param {Uint8Array|Float32Array} mask - Binary mask data
     * @param {number} width - Mask width
     * @param {number} height - Mask height
     * @param {number} threshold - Threshold for binarization (default: 0.5)
     * @returns {Array<Array<number>>} Polygon points [[x1,y1], [x2,y2], ...]
     */
    function maskToPolygon(mask, width, height, threshold = 0.5) {
        // Create binary mask
        const binary = new Uint8Array(width * height);
        for (let i = 0; i < mask.length; i++) {
            binary[i] = mask[i] > threshold ? 1 : 0;
        }

        // Find contour points (simplified approach)
        const contourPoints = [];

        // Scan for edge pixels
        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                const idx = y * width + x;
                if (binary[idx] === 0) continue;

                // Check if this is an edge pixel (has at least one non-mask neighbor)
                const isEdge = (
                    x === 0 || x === width - 1 ||
                    y === 0 || y === height - 1 ||
                    binary[idx - 1] === 0 ||
                    binary[idx + 1] === 0 ||
                    binary[idx - width] === 0 ||
                    binary[idx + width] === 0
                );

                if (isEdge) {
                    contourPoints.push([x, y]);
                }
            }
        }

        if (contourPoints.length < 3) {
            // Fallback to bounding box if no valid contour
            return computeBboxPolygon(binary, width, height);
        }

        // Sort points to form a proper polygon (convex hull approximation)
        return sortPointsConvex(contourPoints);
    }

    /**
     * Compute bounding box polygon from binary mask.
     * @param {Uint8Array} binary - Binary mask
     * @param {number} width - Mask width
     * @param {number} height - Mask height
     * @returns {Array<Array<number>>} Bounding box as polygon
     */
    function computeBboxPolygon(binary, width, height) {
        let minX = width, maxX = 0, minY = height, maxY = 0;

        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                if (binary[y * width + x] === 1) {
                    minX = Math.min(minX, x);
                    maxX = Math.max(maxX, x);
                    minY = Math.min(minY, y);
                    maxY = Math.max(maxY, y);
                }
            }
        }

        if (minX > maxX || minY > maxY) {
            return []; // Empty mask
        }

        return [
            [minX, minY],
            [maxX, minY],
            [maxX, maxY],
            [minX, maxY],
        ];
    }

    /**
     * Sort points to form a convex hull (simplified).
     * Uses centroid-based angle sorting.
     * @param {Array<Array<number>>} points - Unsorted points
     * @returns {Array<Array<number>>} Sorted polygon points
     */
    function sortPointsConvex(points) {
        if (points.length < 3) return points;

        // Calculate centroid
        let cx = 0, cy = 0;
        for (const [x, y] of points) {
            cx += x;
            cy += y;
        }
        cx /= points.length;
        cy /= points.length;

        // Sort by angle from centroid
        return points.sort((a, b) => {
            const angleA = Math.atan2(a[1] - cy, a[0] - cx);
            const angleB = Math.atan2(b[1] - cy, b[0] - cx);
            return angleA - angleB;
        });
    }

    /**
     * Simplify polygon by reducing number of points (Douglas-Peucker algorithm).
     * @param {Array<Array<number>>} polygon - Input polygon
     * @param {number} epsilon - Simplification tolerance (default: 2.0)
     * @returns {Array<Array<number>>} Simplified polygon
     */
    function simplifyPolygon(polygon, epsilon = 2.0) {
        if (polygon.length <= 4) return polygon;

        // Douglas-Peucker algorithm
        function perpendicularDistance(point, lineStart, lineEnd) {
            const [px, py] = point;
            const [x1, y1] = lineStart;
            const [x2, y2] = lineEnd;

            const dx = x2 - x1;
            const dy = y2 - y1;

            if (dx === 0 && dy === 0) {
                return Math.sqrt((px - x1) ** 2 + (py - y1) ** 2);
            }

            const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)));
            const nearestX = x1 + t * dx;
            const nearestY = y1 + t * dy;

            return Math.sqrt((px - nearestX) ** 2 + (py - nearestY) ** 2);
        }

        function douglasPeucker(points, start, end) {
            let maxDist = 0;
            let maxIdx = start;

            for (let i = start + 1; i < end; i++) {
                const dist = perpendicularDistance(points[i], points[start], points[end]);
                if (dist > maxDist) {
                    maxDist = dist;
                    maxIdx = i;
                }
            }

            if (maxDist > epsilon) {
                const left = douglasPeucker(points, start, maxIdx);
                const right = douglasPeucker(points, maxIdx, end);
                return [...left.slice(0, -1), ...right];
            } else {
                return [points[start], points[end]];
            }
        }

        return douglasPeucker(polygon, 0, polygon.length - 1);
    }

    /**
     * Parse YOLO segmentation output tensor.
     * YOLOv8/11 seg outputs have format: [batch, num_detections, 4+num_classes+mask_dim]
     * @param {Object} output - ONNX model output tensors
     * @param {Object} config - Configuration { confidenceThreshold, nmsThreshold, inputSize, maskSize }
     * @returns {Array<Object>} Parsed detections
     */
    function parseYoloSegmentationOutput(output, config) {
        const { confidenceThreshold = 0.5, nmsThreshold = 0.45, inputSize = 640, maskSize = 160 } = config;

        // YOLOv8 seg output structure:
        // - output0: detection output [1, 116, 8400] = [batch, 4+80classes+32mask, num_boxes]
        // - output1: mask protos [1, 32, 160, 160]

        // For our custom model with 4 classes:
        // - output0: [1, 4+4+32, N] = [batch, xywh+classes+mask_coeffs, num_boxes]

        const detOutput = output['output0'] || output['output'] || Object.values(output)[0];
        const maskProtos = output['output1'] || output['masks'] || Object.values(output)[1];

        if (!detOutput) {
            console.error('PostProcess: No detection output found');
            return [];
        }

        const detData = detOutput.data;
        const detShape = detOutput.dims;

        // Determine output format
        // YOLOv8 uses transposed format: [1, features, num_boxes]
        // features = 4 (xywh) + num_classes + 32 (mask coefficients)
        const numClasses = Object.keys(CLASS_NAMES).length; // 4
        const numMaskCoeffs = 32;
        const expectedFeatures = 4 + numClasses + numMaskCoeffs; // 40

        let numBoxes, featuresPerBox;
        if (detShape.length === 3) {
            // [1, features, num_boxes] format
            featuresPerBox = detShape[1];
            numBoxes = detShape[2];
        } else if (detShape.length === 2) {
            // [num_boxes, features] format
            numBoxes = detShape[0];
            featuresPerBox = detShape[1];
        } else {
            console.error('PostProcess: Unexpected output shape', detShape);
            return [];
        }

        const detections = [];

        for (let i = 0; i < numBoxes; i++) {
            // Extract box and class scores
            let cx, cy, w, h;
            const classScores = [];
            const maskCoeffs = [];

            if (detShape.length === 3) {
                // Transposed format [1, features, num_boxes]
                cx = detData[0 * numBoxes + i];
                cy = detData[1 * numBoxes + i];
                w = detData[2 * numBoxes + i];
                h = detData[3 * numBoxes + i];

                for (let c = 0; c < numClasses; c++) {
                    classScores.push(detData[(4 + c) * numBoxes + i]);
                }

                for (let m = 0; m < numMaskCoeffs && (4 + numClasses + m) < featuresPerBox; m++) {
                    maskCoeffs.push(detData[(4 + numClasses + m) * numBoxes + i]);
                }
            } else {
                // Standard format [num_boxes, features]
                const offset = i * featuresPerBox;
                cx = detData[offset];
                cy = detData[offset + 1];
                w = detData[offset + 2];
                h = detData[offset + 3];

                for (let c = 0; c < numClasses; c++) {
                    classScores.push(detData[offset + 4 + c]);
                }

                for (let m = 0; m < numMaskCoeffs && (4 + numClasses + m) < featuresPerBox; m++) {
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

            // Skip low confidence detections
            if (maxScore < confidenceThreshold) continue;

            // Convert center format to corner format
            const x = cx - w / 2;
            const y = cy - h / 2;

            // Skip invalid boxes
            if (w <= 0 || h <= 0 || x < 0 || y < 0 || x + w > inputSize || y + h > inputSize) {
                continue;
            }

            detections.push({
                class_id: classId,
                class_name: CLASS_NAMES[classId] || 'unknown',
                confidence: maxScore,
                bbox: [Math.round(x), Math.round(y), Math.round(w), Math.round(h)],
                mask_coeffs: maskCoeffs,
                lane_type: CLASS_TO_LANE_TYPE[CLASS_NAMES[classId]] || 'SAMPLE',
            });
        }

        // Apply NMS
        const filtered = nms(detections, nmsThreshold);

        // Generate polygons from mask coefficients and protos
        if (maskProtos && filtered.length > 0) {
            const maskData = maskProtos.data;
            const maskShape = maskProtos.dims; // [1, 32, 160, 160]
            const protoH = maskShape[2] || maskSize;
            const protoW = maskShape[3] || maskSize;

            for (const det of filtered) {
                if (det.mask_coeffs.length > 0) {
                    // Compute mask from coefficients and protos
                    const mask = computeMaskFromProtos(det.mask_coeffs, maskData, protoH, protoW, numMaskCoeffs);

                    // Crop mask to bbox
                    const scale = protoW / inputSize;
                    const bx = Math.floor(det.bbox[0] * scale);
                    const by = Math.floor(det.bbox[1] * scale);
                    const bw = Math.ceil(det.bbox[2] * scale);
                    const bh = Math.ceil(det.bbox[3] * scale);

                    // Convert mask to polygon
                    const polygon = maskToPolygon(mask, protoW, protoH, 0.5);

                    // Scale polygon back to input size
                    det.polygon = polygon.map(([px, py]) => [
                        Math.round(px / scale),
                        Math.round(py / scale),
                    ]);

                    // Simplify polygon
                    det.polygon = simplifyPolygon(det.polygon, 3.0);
                }

                // Fallback to bbox polygon if no mask
                if (!det.polygon || det.polygon.length < 3) {
                    const [x, y, w, h] = det.bbox;
                    det.polygon = [
                        [x, y],
                        [x + w, y],
                        [x + w, y + h],
                        [x, y + h],
                    ];
                }

                // Clean up mask coefficients (not needed in final output)
                delete det.mask_coeffs;
            }
        } else {
            // No mask protos - use bbox as polygon
            for (const det of filtered) {
                const [x, y, w, h] = det.bbox;
                det.polygon = [
                    [x, y],
                    [x + w, y],
                    [x + w, y + h],
                    [x, y + h],
                ];
                delete det.mask_coeffs;
            }
        }

        return filtered;
    }

    /**
     * Compute instance mask from mask coefficients and prototypes.
     * @param {Array<number>} coeffs - Mask coefficients
     * @param {Float32Array} protos - Prototype masks [32, H, W]
     * @param {number} height - Prototype height
     * @param {number} width - Prototype width
     * @param {number} numProtos - Number of prototypes (32)
     * @returns {Float32Array} Instance mask
     */
    function computeMaskFromProtos(coeffs, protos, height, width, numProtos = 32) {
        const mask = new Float32Array(height * width);

        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                let sum = 0;
                for (let p = 0; p < numProtos && p < coeffs.length; p++) {
                    const protoIdx = p * height * width + y * width + x;
                    sum += coeffs[p] * protos[protoIdx];
                }
                // Sigmoid activation
                mask[y * width + x] = 1 / (1 + Math.exp(-sum));
            }
        }

        return mask;
    }

    /**
     * Infer gel type from detected lane classes.
     * @param {Array<Object>} detections - Detected lanes
     * @returns {string} Gel type: 'SDS_PAGE', 'DOT_BLOT', or 'UNKNOWN'
     */
    function inferGelType(detections) {
        const classNames = new Set(detections.map(d => d.class_name));

        // Logic from README:
        // - marker_lane + sample_lane -> SDS_PAGE
        // - only dot_lane -> DOT_BLOT
        // - otherwise -> UNKNOWN

        const hasMarker = classNames.has('marker_lane');
        const hasSample = classNames.has('sample_lane');
        const hasDot = classNames.has('dot_lane');

        if (hasMarker && hasSample) {
            return 'SDS_PAGE';
        } else if (hasDot && !hasMarker && !hasSample) {
            return 'DOT_BLOT';
        } else if (hasSample || hasMarker) {
            return 'SDS_PAGE'; // Single marker or sample lane still indicates SDS-PAGE
        }

        return 'UNKNOWN';
    }

    /**
     * Sort detections by X position (left to right) for lane numbering.
     * @param {Array<Object>} detections - Detected lanes
     * @returns {Array<Object>} Sorted detections
     */
    function sortDetectionsByPosition(detections) {
        return [...detections].sort((a, b) => a.bbox[0] - b.bbox[0]);
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.PostProcess = {
        CLASS_NAMES,
        CLASS_TO_LANE_TYPE,
        calculateIoU,
        nms,
        maskToPolygon,
        simplifyPolygon,
        parseYoloSegmentationOutput,
        computeMaskFromProtos,
        inferGelType,
        sortDetectionsByPosition,
    };

})(window);
