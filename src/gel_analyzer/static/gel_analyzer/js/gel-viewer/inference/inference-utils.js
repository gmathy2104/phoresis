/**
 * inference-utils.js
 *
 * Image preprocessing utilities for YOLO inference.
 * Converts image elements to the format required by ONNX Runtime Web.
 *
 * @requires Nothing (vanilla JS)
 */

(function(global) {
    'use strict';

    /**
     * YOLO model configuration
     */
    const YOLO_CONFIG = {
        INPUT_SIZE: 640,           // YOLO expects 640x640 input
        CHANNELS: 3,               // RGB
        NORMALIZE_MEAN: [0, 0, 0], // YOLO uses 0-1 normalization, no mean subtraction
        NORMALIZE_STD: [1, 1, 1],  // No std normalization
    };

    /**
     * Convert an image element to a canvas.
     * @param {HTMLImageElement} imageElement - The image to convert
     * @returns {HTMLCanvasElement} Canvas with image drawn
     */
    function imageToCanvas(imageElement) {
        const canvas = document.createElement('canvas');
        canvas.width = imageElement.naturalWidth || imageElement.width;
        canvas.height = imageElement.naturalHeight || imageElement.height;

        const ctx = canvas.getContext('2d');
        ctx.drawImage(imageElement, 0, 0);

        return canvas;
    }

    /**
     * Get ImageData from canvas, optionally resizing.
     * @param {HTMLCanvasElement} canvas - Source canvas
     * @param {number} targetWidth - Target width (default: YOLO_CONFIG.INPUT_SIZE)
     * @param {number} targetHeight - Target height (default: YOLO_CONFIG.INPUT_SIZE)
     * @returns {Object} { imageData, scaleX, scaleY, originalWidth, originalHeight }
     */
    function canvasToImageData(canvas, targetWidth = YOLO_CONFIG.INPUT_SIZE, targetHeight = YOLO_CONFIG.INPUT_SIZE) {
        const originalWidth = canvas.width;
        const originalHeight = canvas.height;

        // Create resized canvas
        const resizedCanvas = document.createElement('canvas');
        resizedCanvas.width = targetWidth;
        resizedCanvas.height = targetHeight;

        const ctx = resizedCanvas.getContext('2d');

        // Use high-quality interpolation
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';

        // Calculate letterbox dimensions to maintain aspect ratio
        const scale = Math.min(targetWidth / originalWidth, targetHeight / originalHeight);
        const newWidth = Math.round(originalWidth * scale);
        const newHeight = Math.round(originalHeight * scale);
        const offsetX = Math.round((targetWidth - newWidth) / 2);
        const offsetY = Math.round((targetHeight - newHeight) / 2);

        // Fill with gray background (YOLO letterbox convention)
        ctx.fillStyle = '#808080';
        ctx.fillRect(0, 0, targetWidth, targetHeight);

        // Draw resized image centered
        ctx.drawImage(canvas, offsetX, offsetY, newWidth, newHeight);

        const imageData = ctx.getImageData(0, 0, targetWidth, targetHeight);

        return {
            imageData,
            scaleX: originalWidth / newWidth,
            scaleY: originalHeight / newHeight,
            offsetX,
            offsetY,
            originalWidth,
            originalHeight,
            scaledWidth: newWidth,
            scaledHeight: newHeight,
        };
    }

    /**
     * Convert ImageData to normalized Float32Array.
     * @param {ImageData} imageData - Source image data
     * @returns {Float32Array} Normalized pixel values (0-1)
     */
    function normalizeImageData(imageData) {
        const { data, width, height } = imageData;
        const pixelCount = width * height;
        const normalized = new Float32Array(pixelCount * 3);

        for (let i = 0; i < pixelCount; i++) {
            const srcIdx = i * 4; // RGBA
            // Normalize to 0-1 range
            normalized[i] = data[srcIdx] / 255.0;                    // R
            normalized[pixelCount + i] = data[srcIdx + 1] / 255.0;   // G
            normalized[pixelCount * 2 + i] = data[srcIdx + 2] / 255.0; // B
        }

        return normalized;
    }

    /**
     * Convert ImageData to NCHW format Float32Array for YOLO.
     * NCHW = [batch, channels, height, width]
     * @param {ImageData} imageData - Source image data
     * @returns {Float32Array} NCHW formatted tensor data
     */
    function imageDataToNCHW(imageData) {
        const { data, width, height } = imageData;
        const pixelCount = width * height;

        // YOLO expects NCHW format: [1, 3, height, width]
        const tensor = new Float32Array(1 * 3 * height * width);

        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                const srcIdx = (y * width + x) * 4; // RGBA index
                const dstIdx = y * width + x;       // CHW index (within channel)

                // Channel 0 (R)
                tensor[0 * pixelCount + dstIdx] = data[srcIdx] / 255.0;
                // Channel 1 (G)
                tensor[1 * pixelCount + dstIdx] = data[srcIdx + 1] / 255.0;
                // Channel 2 (B)
                tensor[2 * pixelCount + dstIdx] = data[srcIdx + 2] / 255.0;
            }
        }

        return tensor;
    }

    /**
     * Load an image with CORS enabled.
     * Reloads the image to ensure CORS headers are properly set.
     * @param {string} src - Image URL
     * @returns {Promise<HTMLImageElement>} Loaded image with CORS
     */
    function loadImageWithCORS(src) {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.crossOrigin = 'anonymous';
            img.onload = () => resolve(img);
            img.onerror = (e) => reject(new Error(`Failed to load image with CORS: ${src}`));
            // Add cache-busting query param if same-origin to force reload with CORS
            const url = new URL(src, window.location.origin);
            if (url.origin === window.location.origin) {
                url.searchParams.set('_cors', Date.now());
            }
            img.src = url.toString();
        });
    }

    /**
     * Prepare image element for YOLO inference.
     * Complete preprocessing pipeline.
     * @param {HTMLImageElement} imageElement - The image to process
     * @returns {Promise<Object>} { tensor, metadata }
     */
    async function prepareImageForInference(imageElement) {
        // Step 1: Try to convert to canvas directly
        let canvas;
        try {
            canvas = imageToCanvas(imageElement);
            // Test if canvas is tainted by trying to read one pixel
            const ctx = canvas.getContext('2d');
            ctx.getImageData(0, 0, 1, 1);
        } catch (e) {
            // Canvas is tainted, reload image with CORS
            console.log('InferenceUtils: Canvas tainted, reloading image with CORS...');
            const corsImage = await loadImageWithCORS(imageElement.src);
            canvas = imageToCanvas(corsImage);
        }

        // Step 2: Resize with letterboxing and get ImageData
        const { imageData, scaleX, scaleY, offsetX, offsetY, originalWidth, originalHeight, scaledWidth, scaledHeight } =
            canvasToImageData(canvas, YOLO_CONFIG.INPUT_SIZE, YOLO_CONFIG.INPUT_SIZE);

        // Step 3: Convert to NCHW tensor
        const tensor = imageDataToNCHW(imageData);

        return {
            tensor,
            metadata: {
                inputSize: YOLO_CONFIG.INPUT_SIZE,
                originalWidth,
                originalHeight,
                scaledWidth,
                scaledHeight,
                scaleX,
                scaleY,
                offsetX,
                offsetY,
            },
        };
    }

    /**
     * Scale coordinates from YOLO output (640x640) back to original image.
     * Accounts for letterboxing offset.
     * @param {number} x - X coordinate in YOLO space
     * @param {number} y - Y coordinate in YOLO space
     * @param {Object} metadata - Preprocessing metadata
     * @returns {Object} { x, y } in original image coordinates
     */
    function scaleCoordinatesToOriginal(x, y, metadata) {
        const { offsetX, offsetY, scaleX, scaleY } = metadata;

        // Remove letterbox offset
        const adjustedX = x - offsetX;
        const adjustedY = y - offsetY;

        // Scale back to original dimensions
        return {
            x: Math.round(adjustedX * scaleX),
            y: Math.round(adjustedY * scaleY),
        };
    }

    /**
     * Scale a polygon from YOLO output back to original image coordinates.
     * @param {Array<Array<number>>} polygon - [[x1,y1], [x2,y2], ...]
     * @param {Object} metadata - Preprocessing metadata
     * @returns {Array<Array<number>>} Scaled polygon
     */
    function scalePolygonToOriginal(polygon, metadata) {
        return polygon.map(([x, y]) => {
            const scaled = scaleCoordinatesToOriginal(x, y, metadata);
            return [scaled.x, scaled.y];
        });
    }

    /**
     * Scale a bounding box from YOLO output back to original image coordinates.
     * @param {Object} bbox - { x, y, width, height } in YOLO space
     * @param {Object} metadata - Preprocessing metadata
     * @returns {Object} Scaled bounding box
     */
    function scaleBboxToOriginal(bbox, metadata) {
        const topLeft = scaleCoordinatesToOriginal(bbox.x, bbox.y, metadata);
        const bottomRight = scaleCoordinatesToOriginal(
            bbox.x + bbox.width,
            bbox.y + bbox.height,
            metadata
        );

        return {
            x: topLeft.x,
            y: topLeft.y,
            width: bottomRight.x - topLeft.x,
            height: bottomRight.y - topLeft.y,
        };
    }

    /**
     * Clamp coordinates to image boundaries.
     * @param {number} value - Coordinate value
     * @param {number} min - Minimum value
     * @param {number} max - Maximum value
     * @returns {number} Clamped value
     */
    function clamp(value, min, max) {
        return Math.max(min, Math.min(max, value));
    }

    /**
     * Clamp polygon points to image boundaries.
     * @param {Array<Array<number>>} polygon - Polygon points
     * @param {number} width - Image width
     * @param {number} height - Image height
     * @returns {Array<Array<number>>} Clamped polygon
     */
    function clampPolygon(polygon, width, height) {
        return polygon.map(([x, y]) => [
            clamp(x, 0, width - 1),
            clamp(y, 0, height - 1),
        ]);
    }

    // Export to namespace
    global.GelViewer = global.GelViewer || {};
    global.GelViewer.InferenceUtils = {
        YOLO_CONFIG,
        imageToCanvas,
        canvasToImageData,
        normalizeImageData,
        imageDataToNCHW,
        loadImageWithCORS,
        prepareImageForInference,  // Note: now returns a Promise
        scaleCoordinatesToOriginal,
        scalePolygonToOriginal,
        scaleBboxToOriginal,
        clamp,
        clampPolygon,
    };

})(window);
