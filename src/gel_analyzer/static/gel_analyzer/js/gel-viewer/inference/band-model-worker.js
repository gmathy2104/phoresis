/**
 * band-model-worker.js
 *
 * Web Worker running the YOLO band model (settings.GEL_ANALYZER_BAND_MODEL) on a gel image.
 *
 * The browser runs the model because the server has no GPU (Grégory 2026-10-09): WebGPU first, WASM (CPU, one
 * thread: the page is not crossOriginIsolated) as the fallback. It only finds BOXES; the server turns them into
 * the bands of each saved lane (api/analyses/<uuid>/band-model/preview/ and save/).
 *
 * Pre- and post-processing reproduce ultralytics 8.3 predict, so the boxes are those ml_annotator's "Run the
 * model" finds on the same image (gel_analyzer/README.md, "Band model"):
 *   - the gel cut out of a scanned page first (the window the server computed), boxes shifted back after;
 *   - rect letterbox: scale min(imgsz/h, imgsz/w), padding to a multiple of 32, centred, grey 114, resized
 *     bit-exactly as cv2.resize(INTER_LINEAR) on 8-bit pixels (see letterbox()); RGB / 255, NCHW;
 *   - candidates: score > min confidence (strict, as ultralytics), best 30 000, greedy NMS suppressing IoU > iou,
 *     the first max_det kept; boxes scaled back as ultralytics' scale_boxes and clipped to the image.
 *
 * Protocol
 *   main -> worker  {type: 'load', modelUrl, sha256, backend: 'auto'|'wasm'}
 *   worker -> main  {type: 'progress', stage: 'download', loaded, total}
 *   worker -> main  {type: 'progress', stage: 'verify'|'session'}
 *   worker -> main  {type: 'loaded', backend: 'webgpu'|'wasm', webgpuError, verified}
 *   main -> worker  {type: 'detect', id, rgba: ArrayBuffer, width, height, window: [x, y, w, h] | null,
 *                    imgsz, minConfidence, iou, maxDet}
 *   worker -> main  {type: 'progress', id, stage: 'preprocess'|'inference'|'postprocess'}
 *   worker -> main  {type: 'detected', id, boxes: [[x1, y1, x2, y2, score], ...], input: [h, w], timings}
 *   worker -> main  {type: 'error', id, stage, message}
 */

// ONNX Runtime Web 1.24.3 (WebGPU + WASM), from the CDN the lane worker already loads its runtime from.
const ORT_VERSION = '1.24.3';
const ORT_BASE = `https://cdn.jsdelivr.net/npm/onnxruntime-web@${ORT_VERSION}/dist/`;
importScripts(`${ORT_BASE}ort.min.js`);
ort.env.wasm.wasmPaths = ORT_BASE;
ort.env.wasm.numThreads = 1;

const STRIDE = 32;
const PAD_VALUE = 114;
const MAX_NMS = 30000;
const FIXED_ONE = 2048; // cv2's INTER_RESIZE_COEF_SCALE

let session = null;
let backend = null;

function post(message) {
    self.postMessage(message);
}

self.onmessage = async (event) => {
    const msg = event.data || {};
    if (msg.type === 'load') {
        await load(msg);
    } else if (msg.type === 'detect') {
        await detect(msg);
    }
};

// ───────────────────────────────────────────────────────────── load

async function load({ modelUrl, sha256, backend: wanted }) {
    try {
        const bytes = await download(modelUrl);
        let verified = false;
        if (sha256 && self.crypto && self.crypto.subtle) {
            post({ type: 'progress', stage: 'verify' });
            const digest = await self.crypto.subtle.digest('SHA-256', bytes);
            const hex = Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('');
            if (hex !== sha256) {
                throw new Error(`the downloaded model has sha256 ${hex.slice(0, 12)}…, the server expects ${sha256.slice(0, 12)}…`);
            }
            verified = true;
        }
        post({ type: 'progress', stage: 'session' });
        let webgpuError = null;
        session = null;
        if (wanted !== 'wasm') {
            if (self.navigator && self.navigator.gpu) {
                try {
                    session = await ort.InferenceSession.create(bytes, {
                        executionProviders: ['webgpu'],
                        graphOptimizationLevel: 'all',
                    });
                    backend = 'webgpu';
                } catch (error) {
                    webgpuError = String((error && error.message) || error);
                }
            } else {
                webgpuError = 'WebGPU is not available in this browser';
            }
        }
        if (!session) {
            session = await ort.InferenceSession.create(bytes, {
                executionProviders: ['wasm'],
                graphOptimizationLevel: 'all',
            });
            backend = 'wasm';
        }
        post({ type: 'loaded', backend, webgpuError, verified });
    } catch (error) {
        post({ type: 'error', stage: 'load', message: String((error && error.message) || error) });
    }
}

async function download(url) {
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`model download failed: ${response.status} ${response.statusText}`);
    }
    const total = Number(response.headers.get('Content-Length')) || 0;
    if (!response.body || !response.body.getReader) {
        const buffer = await response.arrayBuffer();
        post({ type: 'progress', stage: 'download', loaded: buffer.byteLength, total: buffer.byteLength });
        return buffer;
    }
    const reader = response.body.getReader();
    const chunks = [];
    let loaded = 0;
    let lastPost = 0;
    for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        loaded += value.byteLength;
        const now = Date.now();
        if (now - lastPost > 100) {
            post({ type: 'progress', stage: 'download', loaded, total });
            lastPost = now;
        }
    }
    const bytes = new Uint8Array(loaded);
    let offset = 0;
    for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.byteLength;
    }
    post({ type: 'progress', stage: 'download', loaded, total: total || loaded });
    return bytes.buffer;
}

// ───────────────────────────────────────────────────────────── detect

async function detect(msg) {
    const { id } = msg;
    if (!session) {
        post({ type: 'error', id, stage: 'detect', message: 'the model is not loaded' });
        return;
    }
    try {
        const timings = {};
        let t = performance.now();
        post({ type: 'progress', id, stage: 'preprocess' });
        const rgba = new Uint8ClampedArray(msg.rgba);
        const [wx, wy, ww, wh] = msg.window || [0, 0, msg.width, msg.height];
        const prep = letterbox(rgba, msg.width, wx, wy, ww, wh, msg.imgsz);
        timings.preprocess_ms = performance.now() - t;

        t = performance.now();
        post({ type: 'progress', id, stage: 'inference' });
        const feeds = {};
        feeds[session.inputNames[0]] = new ort.Tensor('float32', prep.tensor, [1, 3, prep.inH, prep.inW]);
        const outputs = await session.run(feeds);
        const out0 = outputs[session.outputNames[0]];
        const out1 = outputs[session.outputNames[1]];
        const preds = await out0.getData();
        const dims = out0.dims;
        const numProtos = out1 ? out1.dims[1] : 32;
        timings.inference_ms = performance.now() - t;

        t = performance.now();
        post({ type: 'progress', id, stage: 'postprocess' });
        const boxes = decode(preds, dims, numProtos, msg.minConfidence, msg.iou, msg.maxDet, prep, ww, wh)
            .map(([x1, y1, x2, y2, s]) => [x1 + wx, y1 + wy, x2 + wx, y2 + wy, s]);
        timings.postprocess_ms = performance.now() - t;
        for (const key of Object.keys(outputs)) {
            if (outputs[key].dispose) outputs[key].dispose();
        }
        post({ type: 'detected', id, boxes, input: [prep.inH, prep.inW], backend, timings });
    } catch (error) {
        post({ type: 'error', id, stage: 'detect', message: String((error && error.message) || error) });
    }
}

/** Python's round(): half to even, as ultralytics' int(round(...)). */
function pyRound(x) {
    const r = Math.round(x);
    return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
}

/**
 * ultralytics LetterBox(new_shape=(imgsz, imgsz), auto=True, stride=32, center=True) on the window of the image,
 * then RGB / 255 in NCHW planes. Returns the tensor and the input size.
 */
function letterbox(rgba, fullWidth, wx, wy, w, h, imgsz) {
    const r = Math.min(imgsz / h, imgsz / w);
    const newW = pyRound(w * r);
    const newH = pyRound(h * r);
    let dw = (imgsz - newW) % STRIDE;
    let dh = (imgsz - newH) % STRIDE;
    dw /= 2;
    dh /= 2;
    const top = pyRound(dh - 0.1);
    const bottom = pyRound(dh + 0.1);
    const left = pyRound(dw - 0.1);
    const right = pyRound(dw + 0.1);
    const inH = newH + top + bottom;
    const inW = newW + left + right;
    const plane = inH * inW;
    const tensor = new Float32Array(3 * plane).fill(PAD_VALUE / 255);

    // cv2.resize(INTER_LINEAR) on 8-bit pixels, BIT-EXACT (measured 2026-10-09: 0 pixel of 3 bench gels differs from
    // ultralytics' LetterBox; a float bilinear differed by 1 grey level on 12 % of them, enough to move scores by
    // up to 0.07): coefficients in fixed point x 2048 rounded half to even, the horizontal sums exact, the vertical
    // pass OpenCV's SIMD rounding ((h0 >> 4) * b0 >> 16) + ((h1 >> 4) * b1 >> 16) + 2) >> 2, the vertical weights
    // from the UNCLAMPED fy (rows clamped), the horizontal ones clamped at the edges. Coordinates in float32 as cv2.
    const xs0 = new Int32Array(newW);
    const xs1 = new Int32Array(newW);
    const a0 = new Int32Array(newW);
    const a1 = new Int32Array(newW);
    const scaleX = 1 / (newW / w);
    for (let dx = 0; dx < newW; dx++) {
        let fx = Math.fround((dx + 0.5) * scaleX - 0.5);
        let sx = Math.floor(fx);
        fx = Math.fround(fx - sx);
        if (sx < 0) {
            fx = 0;
            sx = 0;
        }
        if (sx >= w - 1) {
            fx = 0;
            sx = w - 1;
        }
        xs0[dx] = sx;
        xs1[dx] = Math.min(sx + 1, w - 1);
        a0[dx] = pyRound(Math.fround(1 - fx) * FIXED_ONE);
        a1[dx] = pyRound(fx * FIXED_ONE);
    }
    const scaleY = 1 / (newH / h);
    for (let dy = 0; dy < newH; dy++) {
        let fy = Math.fround((dy + 0.5) * scaleY - 0.5);
        const sy = Math.floor(fy);
        fy = Math.fround(fy - sy);
        const b0 = pyRound(Math.fround(1 - fy) * FIXED_ONE);
        const b1 = pyRound(fy * FIXED_ONE);
        const row0 = (wy + Math.min(Math.max(sy, 0), h - 1)) * fullWidth + wx;
        const row1 = (wy + Math.min(Math.max(sy + 1, 0), h - 1)) * fullWidth + wx;
        const out = (dy + top) * inW + left;
        for (let dx = 0; dx < newW; dx++) {
            const p00 = (row0 + xs0[dx]) * 4;
            const p01 = (row0 + xs1[dx]) * 4;
            const p10 = (row1 + xs0[dx]) * 4;
            const p11 = (row1 + xs1[dx]) * 4;
            for (let ch = 0; ch < 3; ch++) {
                const h0 = rgba[p00 + ch] * a0[dx] + rgba[p01 + ch] * a1[dx];
                const h1 = rgba[p10 + ch] * a0[dx] + rgba[p11 + ch] * a1[dx];
                const v = ((((h0 >> 4) * b0) >> 16) + (((h1 >> 4) * b1) >> 16) + 2) >> 2;
                tensor[ch * plane + out + dx] = Math.max(0, Math.min(255, v)) / 255;
            }
        }
    }
    return { tensor, inH, inW, newW, newH };
}

/** output0 [1, 4 + nc + nm, N] -> boxes in window pixels, NMS'd, as ultralytics non_max_suppression + scale_boxes. */
function decode(preds, dims, numProtos, minConfidence, iouThreshold, maxDet, prep, w, h) {
    const rows = dims[1];
    const n = dims[2];
    const nc = rows - 4 - numProtos;
    const candidates = [];
    for (let i = 0; i < n; i++) {
        let score = -Infinity;
        for (let c = 0; c < nc; c++) {
            const s = preds[(4 + c) * n + i];
            if (s > score) score = s;
        }
        if (!(score > minConfidence)) continue;
        const cx = preds[i];
        const cy = preds[n + i];
        const bw = preds[2 * n + i];
        const bh = preds[3 * n + i];
        candidates.push([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2, score]);
    }
    candidates.sort((p, q) => q[4] - p[4]);
    if (candidates.length > MAX_NMS) candidates.length = MAX_NMS;

    const kept = [];
    const suppressed = new Uint8Array(candidates.length);
    for (let i = 0; i < candidates.length && kept.length < maxDet; i++) {
        if (suppressed[i]) continue;
        const a = candidates[i];
        kept.push(a);
        const areaA = (a[2] - a[0]) * (a[3] - a[1]);
        for (let j = i + 1; j < candidates.length; j++) {
            if (suppressed[j]) continue;
            const b = candidates[j];
            const iw = Math.min(a[2], b[2]) - Math.max(a[0], b[0]);
            const ih = Math.min(a[3], b[3]) - Math.max(a[1], b[1]);
            if (iw <= 0 || ih <= 0) continue;
            const inter = iw * ih;
            const union = areaA + (b[2] - b[0]) * (b[3] - b[1]) - inter;
            if (union > 0 && inter / union > iouThreshold) suppressed[j] = 1;
        }
    }

    // scale_boxes: gain and padding recomputed from the shapes, as ultralytics does.
    const gain = Math.min(prep.inH / h, prep.inW / w);
    const padX = pyRound((prep.inW - w * gain) / 2 - 0.1);
    const padY = pyRound((prep.inH - h * gain) / 2 - 0.1);
    const clip = (v, hi) => Math.min(Math.max(v, 0), hi);
    return kept.map(([x1, y1, x2, y2, s]) => [
        clip((x1 - padX) / gain, w),
        clip((y1 - padY) / gain, h),
        clip((x2 - padX) / gain, w),
        clip((y2 - padY) / gain, h),
        s,
    ]);
}
