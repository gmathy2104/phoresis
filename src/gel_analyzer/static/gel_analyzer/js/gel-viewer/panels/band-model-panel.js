/**
 * band-model-panel.js
 *
 * Band detection with the YOLO band model, after the lane model (Grégory 2026-10-09): lanes first (the wand and
 * the review panel), then this panel finds the bands of the saved lanes.
 *
 *   1. GET band-model/            which model to run, its settings, the gel's window in a scanned page
 *   2. BandModelEngine            the model runs in THIS browser (WebGPU, else the CPU) on the whole gel
 *   3. POST band-model/preview/   the server puts the boxes in the lanes, in the classical detection's shape
 *   4. slider                     filters the preview on the page (the server returned every band from the floor up)
 *   5. POST band-model/save/      the server writes them: auto-detected bands replaced, hand-drawn ones kept
 *
 * Every phase is shown while it runs (download %, checking, preparing, finding bands on GPU/CPU with the elapsed
 * time, placing in lanes, saving), and every refusal with the server's own words.
 *
 * @requires GelViewer.Events
 * @requires GelViewer.DetectionPanelBase
 * @requires GelViewer.BandModelEngine
 * @requires GelViewer.APIClient
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;
    const Base = global.GelViewer.DetectionPanelBase;
    const BandModelEngine = global.GelViewer.BandModelEngine;

    const MB = 1024 * 1024;

    function escapeHtml(text) {
        return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    class BandModelPanel {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus
         * @param {APIClient} options.apiClient
         * @param {StateManager} options.stateManager
         * @param {Object} options.svg - SVG.js root, for the preview
         * @param {string} options.workerUrl - band-model-worker.js URL
         * @param {Function} [options.onDetectionComplete] - called after a save
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.apiClient = options.apiClient;
            this.stateManager = options.stateManager;
            this.svg = options.svg;
            this.onDetectionComplete = options.onDetectionComplete;
            this.engine = BandModelEngine ? new BandModelEngine({ workerUrl: options.workerUrl }) : null;

            this.isVisible = false;
            this.context = null; // GET band-model/
            this.preview = null; // {request, response} of the last detection
            this.busy = false;
            this._previewGroup = null;
            this._timer = null;

            this._setupDOM();
            this._bindEvents();
        }

        // ─── DOM ──────────────────────────────────────────────────────

        _setupDOM() {
            this.backdrop = document.createElement('div');
            this.backdrop.className = 'gv-bm-backdrop';
            this.backdrop.style.display = 'none';
            document.body.appendChild(this.backdrop);

            this.panel = document.createElement('div');
            this.panel.className = 'gv-bm-panel';
            this.panel.style.display = 'none';
            this.panel.setAttribute('role', 'dialog');
            this.panel.setAttribute('aria-label', 'Band detection with the model');
            this.panel.innerHTML = this._buildHTML();
            document.body.appendChild(this.panel);

            if (this.svg) {
                this._previewGroup = this.svg.group().attr('id', 'band-model-previews');
            }

            const q = (selector) => this.panel.querySelector(selector);
            this._modelLine = q('#gv-bm-model');
            this._status = q('#gv-bm-status');
            this._stage = q('#gv-bm-stage');
            this._bar = q('#gv-bm-bar');
            this._barFill = q('#gv-bm-bar-fill');
            this._backendLine = q('#gv-bm-backend');
            this._error = q('#gv-bm-error');
            this._slider = q('#gv-bm-confidence');
            this._sliderValue = q('#gv-bm-confidence-value');
            this._kept = q('#gv-bm-kept');
            this._detectBtn = q('#gv-bm-detect-btn');
            this._clearBtn = q('#gv-bm-clear-btn');
            this._results = q('#gv-bm-results');
            this._footer = q('#gv-bm-footer');
            this._saveBtn = q('#gv-bm-save-btn');
            this._saveReason = q('#gv-bm-save-reason');
        }

        _buildHTML() {
            return `
                <div class="gv-bm-header">
                    <span class="gv-bm-title"><i class="bi bi-bullseye"></i> Band detection (model)</span>
                    <button class="gv-bm-close" aria-label="Close">&times;</button>
                </div>
                <div class="gv-bm-body">
                    <div class="gv-bm-model" id="gv-bm-model">Loading the model's settings…</div>

                    <div class="gv-bm-control">
                        <label class="gv-bm-label" for="gv-bm-confidence">Confidence threshold</label>
                        <div class="gv-bm-slider-row">
                            <input type="range" id="gv-bm-confidence" class="gv-bm-slider"
                                   min="0.05" max="0.9" step="0.05" value="0.25">
                            <span class="gv-bm-slider-value" id="gv-bm-confidence-value">0.25</span>
                        </div>
                        <div class="gv-bm-kept" id="gv-bm-kept"></div>
                    </div>

                    <div class="gv-bm-control">
                        <label class="gv-bm-label">Apply to</label>
                        <div class="gv-bm-radio-group">
                            <label><input type="radio" name="gv-bm-lane-filter" value="all" checked> All lanes</label>
                            <label><input type="radio" name="gv-bm-lane-filter" value="selected"> Selected lane</label>
                            <label><input type="radio" name="gv-bm-lane-filter" value="sample"> Sample lanes only</label>
                            <label><input type="radio" name="gv-bm-lane-filter" value="ladder"> Ladder lanes only</label>
                        </div>
                    </div>

                    <div class="gv-bm-note">
                        Saving replaces the auto-detected bands of these lanes; hand-drawn bands are kept.
                        Ladder lanes get MW reference bands; mark the POI bands yourself.
                    </div>

                    <div class="gv-bm-actions">
                        <button id="gv-bm-detect-btn" class="gv-bm-btn gv-bm-btn-primary">
                            <i class="bi bi-bullseye"></i> Detect bands
                        </button>
                        <button id="gv-bm-clear-btn" class="gv-bm-btn gv-bm-btn-secondary">
                            <i class="bi bi-x-circle"></i> Clear
                        </button>
                    </div>

                    <div class="gv-bm-status" id="gv-bm-status" style="display:none;" aria-live="polite">
                        <div class="gv-bm-stage" id="gv-bm-stage"></div>
                        <div class="gv-bm-bar" id="gv-bm-bar" style="display:none;"><div class="gv-bm-bar-fill" id="gv-bm-bar-fill"></div></div>
                    </div>
                    <div class="gv-bm-backend" id="gv-bm-backend" style="display:none;"></div>
                    <div class="gv-bm-error" id="gv-bm-error" style="display:none;" role="alert"></div>

                    <div class="gv-bm-results" id="gv-bm-results" style="display:none;"></div>
                </div>
                <div class="gv-bm-footer" id="gv-bm-footer" style="display:none;">
                    <button id="gv-bm-save-btn" class="gv-bm-btn gv-bm-btn-success">
                        <i class="bi bi-check-circle"></i> Save all
                    </button>
                    <div class="gv-bm-save-reason" id="gv-bm-save-reason" style="display:none;"></div>
                </div>
            `;
        }

        _bindEvents() {
            this.panel.querySelector('.gv-bm-close').addEventListener('click', () => this.hide());
            // A click on the backdrop closes nothing (owner, 2026-10-13): a stray click lost the preview, or left a
            // detection running with no panel. Esc: GelViewer.Layers (show) closes the panel.
            this._slider.addEventListener('input', () => {
                this._sliderValue.textContent = Number(this._slider.value).toFixed(2);
                this._renderPreview();
            });
            this.panel.querySelectorAll('input[name="gv-bm-lane-filter"]').forEach((radio) => {
                radio.addEventListener('change', () => this._clearPreview());
            });
            this._detectBtn.addEventListener('click', () => this._detect());
            this._clearBtn.addEventListener('click', () => this._clearPreview());
            this._saveBtn.addEventListener('click', () => this._save());
        }

        // ─── Show / hide ──────────────────────────────────────────────

        async show() {
            this.panel.style.display = 'flex';
            this.backdrop.style.display = 'block';
            this.isVisible = true;
            this.panel.setAttribute('tabindex', '-1');
            global.GelViewer.Layers?.open(this.panel, {
                modal: true,
                close: () => this.hide(),
                isOpen: () => this.isVisible,
            });
            this.eventBus.emit(Events.BAND_MODEL_PANEL_SHOWN);
            if (!this.context) {
                await this._loadContext();
            }
        }

        hide() {
            this._clearPreview();
            this.panel.style.display = 'none';
            this.backdrop.style.display = 'none';
            this.isVisible = false;
            global.GelViewer.Layers?.close(this.panel);
            this.eventBus.emit(Events.BAND_MODEL_PANEL_HIDDEN);
        }

        toggle() {
            if (this.isVisible) {
                this.hide();
            } else {
                this.show();
            }
        }

        isOpen() {
            return this.isVisible;
        }

        // ─── Context ──────────────────────────────────────────────────

        async _loadContext() {
            try {
                const context = await this.apiClient.getBandModelContext();
                this.context = context;
                const m = context.model;
                this._modelLine.textContent = `${m.name} · ${m.imgsz} px · ${m.sha256.slice(0, 8)}`;
                this._slider.min = String(m.min_confidence);
                this._slider.value = String(m.confidence);
                this._sliderValue.textContent = Number(m.confidence).toFixed(2);
                return context;
            } catch (error) {
                this._modelLine.textContent = 'Band model unavailable';
                this._showError(error.message);
                return null;
            }
        }

        // ─── Lanes ────────────────────────────────────────────────────

        _targetLanes() {
            const radio = this.panel.querySelector('input[name="gv-bm-lane-filter"]:checked');
            const filter = radio ? radio.value : 'all';
            if (Base && Base.getTargetLanes) {
                return Base.getTargetLanes(filter, this.stateManager);
            }
            const lanes = Array.from(this.stateManager.getAllLanes().values());
            if (filter === 'sample') return lanes.filter((l) => l.lane_type === 'SAMPLE');
            if (filter === 'ladder') return lanes.filter((l) => l.lane_type === 'LADDER');
            return lanes;
        }

        // ─── Detect ───────────────────────────────────────────────────

        async _detect() {
            if (this.busy) return;
            this._clearPreview();
            this._hideError();
            const context = this.context || (await this._loadContext());
            if (!context) return;

            // The server places bands in the SAVED lanes: an unsaved lane, or a lane moved and not saved, would get
            // bands computed in another geometry than the one on screen.
            if (this.stateManager.isDirty) {
                this._showError('Save your changes first (Ctrl+S): bands are placed in the saved lanes.');
                return;
            }
            const lanes = this._targetLanes();
            const laneIds = lanes.map((l) => l.id).filter((id) => Number.isInteger(id));
            if (!laneIds.length) {
                this._showError(
                    lanes.length
                        ? 'Save your lanes first (Ctrl+S): bands are placed in the saved lanes.'
                        : 'No lane to detect in. Detect or draw the lanes first, or change "Apply to".',
                );
                return;
            }
            const image = document.getElementById('gel-image');
            if (!image || !image.complete || !image.naturalWidth) {
                this._showError('The gel image is not loaded yet.');
                return;
            }
            if (image.naturalWidth !== context.image.width || image.naturalHeight !== context.image.height) {
                this._showError(
                    `This page shows a ${image.naturalWidth}x${image.naturalHeight} image, the gel's is `
                    + `${context.image.width}x${context.image.height}. Reload the page.`,
                );
                return;
            }

            this._setBusy(true);
            const m = context.model;
            try {
                const loaded = await this.engine.load({
                    modelUrl: m.url,
                    sha256: m.sha256,
                    backend: this._forcedBackend(),
                    onProgress: (p) => this._onLoadProgress(p),
                });
                this._showBackend(loaded);

                const detection = await this.engine.detect(
                    image,
                    {
                        window: context.image.gel_window,
                        imgsz: m.imgsz,
                        minConfidence: m.min_confidence,
                        iou: m.iou,
                        maxDet: m.max_det,
                    },
                    (p) => this._onDetectProgress(p, loaded.backend),
                );

                this._setStage('Placing the bands in the lanes…');
                const request = {
                    model_sha256: m.sha256,
                    image: { width: context.image.width, height: context.image.height },
                    boxes: detection.boxes,
                    confidence: m.min_confidence,
                    lane_ids: laneIds,
                };
                const response = await this.apiClient.previewBandModel(request);
                // Closed (x, Esc) while the model ran: the answer is dropped, never drawn on a gel with no panel.
                if (!this.isVisible) {
                    this._hideStatus();
                    return;
                }
                this.preview = { request, response, timings: detection.timings, backend: detection.backend };
                this._hideStatus();
                this._renderPreview();
            } catch (error) {
                this._hideStatus();
                this._showError(this._explain(error));
            } finally {
                this._setBusy(false);
            }
        }

        /**
         * 'wasm' forces the CPU path, to check the fallback on a PC that has a graphics card:
         * localStorage.setItem('gelViewer.bandModelBackend', 'wasm') in the console, then reload. 'auto' otherwise.
         */
        _forcedBackend() {
            try {
                return global.localStorage.getItem('gelViewer.bandModelBackend') === 'wasm' ? 'wasm' : 'auto';
            } catch (error) {
                return 'auto';
            }
        }

        _onLoadProgress(p) {
            if (p.stage === 'download') {
                const total = p.total || 0;
                if (total) {
                    const pct = Math.round((100 * p.loaded) / total);
                    this._setStage(`Downloading the band model… ${pct} % (${(p.loaded / MB).toFixed(0)} / ${(total / MB).toFixed(0)} MB, once per browser)`);
                    this._setBar(pct);
                } else {
                    this._setStage(`Downloading the band model… ${(p.loaded / MB).toFixed(0)} MB`);
                }
            } else if (p.stage === 'verify') {
                this._setBar(null);
                this._setStage('Checking the model file…');
            } else if (p.stage === 'session') {
                this._setBar(null);
                this._setStage('Preparing the model…');
            }
        }

        _onDetectProgress(p, backend) {
            this._setBar(null);
            if (p.stage === 'preprocess') {
                this._setStage('Preparing the image…');
            } else if (p.stage === 'inference') {
                const started = Date.now();
                const where = backend === 'webgpu' ? 'on the graphics card' : 'on the processor (usually 15–20 s)';
                const tick = () => this._setStage(`Finding the bands ${where}… ${Math.round((Date.now() - started) / 1000)} s`);
                tick();
                this._stopTimer();
                this._timer = setInterval(tick, 1000);
            } else if (p.stage === 'postprocess') {
                this._stopTimer();
                this._setStage('Reading the model\'s answer…');
            }
        }

        // ─── Preview ──────────────────────────────────────────────────

        _visibleBands() {
            const threshold = Number(this._slider.value);
            if (!this.preview) return [];
            return this.preview.response.lanes.map((lane) => ({
                ...lane,
                bands: lane.bands.filter((b) => b.score >= threshold),
            }));
        }

        _renderPreview() {
            if (this._previewGroup) this._previewGroup.clear();
            if (!this.preview) {
                this._kept.textContent = '';
                return;
            }
            const lanes = this._visibleBands();
            const kept = lanes.reduce((n, l) => n + l.bands.length, 0);
            const proposed = this.preview.response.band_count;
            this._kept.textContent = `${kept} of ${proposed} proposed bands kept`;

            if (this._previewGroup) {
                for (const lane of lanes) {
                    for (const b of lane.bands) {
                        this._previewGroup
                            .rect(b.bbox_width, b.bbox_height)
                            .attr('x', b.bbox_x)
                            .attr('y', b.bbox_y)
                            .addClass('gv-bm-preview-band');
                    }
                }
            }

            const r = this.preview.response;
            let html = '<div class="gv-bm-results-header">Preview — nothing saved yet</div>';
            for (const lane of lanes) {
                const type = lane.band_type === 'MW_REFERENCE' ? ' (MW reference)' : '';
                html += `<div class="gv-bm-result-row">Lane ${escapeHtml(lane.lane_number)} · ${escapeHtml(lane.lane_type)} · `
                    + `${lane.bands.length} band${lane.bands.length === 1 ? '' : 's'}${type}</div>`;
            }
            const notes = [];
            if (r.outside_lanes) notes.push(`${r.outside_lanes} outside any lane`);
            if (r.superposed) notes.push(`${r.superposed} superposed in a lane`);
            if (r.empty) notes.push(`${r.empty} empty`);
            if (notes.length) {
                html += `<div class="gv-bm-result-note">Not placed: ${escapeHtml(notes.join(', '))}.</div>`;
            }
            const t = this.preview.timings || {};
            const where = this.preview.backend === 'webgpu' ? 'graphics card' : 'processor';
            html += `<div class="gv-bm-results-total">Total: ${kept} bands · found in ${((t.inference_ms || 0) / 1000).toFixed(1)} s on the ${where}</div>`;
            this._results.innerHTML = html;
            this._results.style.display = 'block';

            this._footer.style.display = '';
            const reason = this._saveRefusal();
            this._saveBtn.disabled = Boolean(reason) || kept === 0;
            this._saveReason.textContent = reason || (kept === 0 ? 'No band above the threshold.' : '');
            this._saveReason.style.display = this._saveReason.textContent ? '' : 'none';
        }

        _saveRefusal() {
            if (!this.context) return 'The band model is unavailable.';
            if (!this.context.can_write) return 'You need write access to gel analyses to save bands.';
            if (!this.context.editable) return 'This analysis is not editable.';
            return null;
        }

        _clearPreview() {
            this.preview = null;
            if (this._previewGroup) this._previewGroup.clear();
            this._results.style.display = 'none';
            this._results.innerHTML = '';
            this._footer.style.display = 'none';
            this._kept.textContent = '';
        }

        // ─── Save ─────────────────────────────────────────────────────

        async _save() {
            if (this.busy || !this.preview) return;
            this._hideError();
            this._setBusy(true);
            this._setStage('Saving the bands…');
            try {
                const body = { ...this.preview.request, confidence: Number(this._slider.value) };
                const result = await this.apiClient.saveBandModel(body);
                this._hideStatus();
                this._clearPreview();
                this.eventBus.emit(Events.DATA_RELOAD_REQUESTED);
                if (this.onDetectionComplete) this.onDetectionComplete();
                const message = `${result.created_count} bands saved (${result.deleted_count} auto-detected bands replaced). `
                    + 'Run the densitometry of these lanes again.';
                if (global.gaToast) global.gaToast(message, 'success');
                this.hide();
            } catch (error) {
                this._hideStatus();
                this._showError(this._explain(error));
            } finally {
                this._setBusy(false);
            }
        }

        // ─── Status, errors ───────────────────────────────────────────

        _explain(error) {
            if (error && error.status === 409) {
                return `${error.message}`;
            }
            if (error && error.status === 503) {
                return error.message;
            }
            return (error && error.message) || 'Band detection failed.';
        }

        _showBackend(loaded) {
            if (loaded.backend === 'webgpu') {
                this._backendLine.textContent = 'Running on the graphics card (WebGPU).';
                this._backendLine.className = 'gv-bm-backend gv-bm-backend-gpu';
            } else {
                const why = loaded.webgpuError ? ` — no graphics card available: ${loaded.webgpuError}` : '';
                this._backendLine.textContent = `Running on the processor (slower, 15–20 s per gel)${why}.`;
                this._backendLine.className = 'gv-bm-backend gv-bm-backend-cpu';
            }
            this._backendLine.style.display = '';
        }

        _setBusy(busy) {
            this.busy = busy;
            this._detectBtn.disabled = busy;
            this._clearBtn.disabled = busy;
            this._saveBtn.disabled = busy || Boolean(this._saveRefusal());
            this._slider.disabled = busy;
            this._detectBtn.innerHTML = busy
                ? '<i class="bi bi-hourglass-split"></i> Working…'
                : '<i class="bi bi-bullseye"></i> Detect bands';
            if (!busy) this._stopTimer();
        }

        _setStage(text) {
            this._status.style.display = '';
            this._stage.textContent = text;
        }

        _setBar(pct) {
            if (pct == null) {
                this._bar.style.display = 'none';
                return;
            }
            this._bar.style.display = '';
            this._barFill.style.width = `${Math.max(0, Math.min(100, pct))}%`;
        }

        _hideStatus() {
            this._stopTimer();
            this._status.style.display = 'none';
            this._setBar(null);
        }

        _stopTimer() {
            if (this._timer) {
                clearInterval(this._timer);
                this._timer = null;
            }
        }

        _showError(message) {
            this._error.textContent = message;
            this._error.style.display = '';
        }

        _hideError() {
            this._error.style.display = 'none';
            this._error.textContent = '';
        }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.BandModelPanel = BandModelPanel;
})(window);
