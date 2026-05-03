/**
 * Gel Overview Panel
 *
 * Displays cropped lane images side-by-side for visual comparison.
 * Normal view: cropped lane strips from each sample's gel image.
 * Magnified view: full gel images side-by-side with lane highlights.
 * Supports drag-and-drop reorder and click selection.
 */

(function(global) {
    'use strict';

    const ComparisonEvents = global.SampleComparison?.Events;
    const DragReorder = global.SampleComparison?.DragReorder;

    /**
     * GelOverviewPanel Class
     */
    class GelOverviewPanel {
        constructor(options) {
            this.container = options.container;
            this.eventBus = options.eventBus;
            this.state = options.state;

            this.contentElement = null;

            // Loaded Image objects keyed by image_url
            this._imageCache = new Map();
            this._pendingLoads = new Set();

            // Band overlay visibility
            this.showBands = true;

            // Per-image adjustments: image_url → { brightness, contrast, invert }
            this._imageAdjustments = new Map();
            this._enhancedUrls = new Set();   // tracks which images have been auto-enhanced
            this._invertAll = false;           // global invert toggle

            this.colors = {
                bandPOI: '#a855f7',
                bandOther: '#22c55e',
                bandRef: '#f97316',
                bandSelected: '#ef4444',
            };

            this._init();
        }

        _init() {
            if (!this.container) return;

            this.contentElement = this.container.querySelector('.dm-panel-content');
            if (!this.contentElement) {
                this.contentElement = this.container;
            }

            // Drag-and-drop reorder
            if (DragReorder) {
                this.laneReorder = new DragReorder({
                    container: null,
                    itemSelector: '.dm-gel-crop-column',
                    dataKey: 'sampleId',
                    onReorder: (newOrder) => {
                        this.state.reorderSamples(newOrder);
                    },
                });
            }

            this._showPlaceholder('Add samples to compare gel lanes');
            this._setupEvents();
            this._setupBandToggle();
            this._setupEnhanceButtons();

            // Re-render on window resize (magnifier open/close triggers this)
            window.addEventListener('resize', () => {
                if (this._resizeTimer) cancelAnimationFrame(this._resizeTimer);
                this._resizeTimer = requestAnimationFrame(() => this._render());
            });
        }

        _showPlaceholder(message) {
            this.contentElement.innerHTML = `
                <div class="dm-placeholder">
                    <i class="bi bi-image"></i>
                    <span>${message}</span>
                </div>
            `;
        }

        /**
         * Detect if the panel is currently in magnified (fullscreen) mode.
         * The PanelMagnifier moves .dm-panel-content into #magnify-content.
         */
        _isMagnified() {
            return !!this.contentElement.closest('#magnify-content');
        }

        _setupBandToggle() {
            const btn = document.getElementById('gel-bands-toggle');
            if (btn) {
                btn.addEventListener('click', () => {
                    this.showBands = !this.showBands;
                    btn.classList.toggle('active', this.showBands);
                    this._render();
                });
            }
        }

        _setupEnhanceButtons() {
            // Auto-enhance button
            const enhanceBtn = document.getElementById('gel-auto-enhance');
            if (enhanceBtn) {
                enhanceBtn.addEventListener('click', () => {
                    const isActive = enhanceBtn.classList.toggle('active');
                    if (isActive) {
                        this._autoEnhanceAll();
                    } else {
                        // Reset all per-image adjustments
                        this._imageAdjustments.clear();
                        this._enhancedUrls.clear();
                        this._render();
                    }
                });
            }

            // Invert toggle button
            const invertBtn = document.getElementById('gel-invert-toggle');
            if (invertBtn) {
                invertBtn.addEventListener('click', () => {
                    this._invertAll = !this._invertAll;
                    invertBtn.classList.toggle('active', this._invertAll);
                    this._render();
                });
            }
        }

        /**
         * Auto-enhance each unique gel image individually by analyzing its histogram.
         */
        _autoEnhanceAll() {
            const samples = this.state.getSamples();
            const urls = new Set();
            for (const s of samples) {
                if (s.image_url && this._imageCache.has(s.image_url)) {
                    urls.add(s.image_url);
                }
            }

            for (const url of urls) {
                if (this._enhancedUrls.has(url)) continue;
                const img = this._imageCache.get(url);
                if (!img) continue;

                const optimal = this._analyzeImage(img);
                this._imageAdjustments.set(url, {
                    brightness: optimal.brightness,
                    contrast: optimal.contrast,
                });
                this._enhancedUrls.add(url);
            }

            this._render();
        }

        /**
         * Analyze a loaded Image to compute optimal brightness/contrast.
         */
        _analyzeImage(img) {
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');

            // Use smaller size for performance
            const maxSize = 500;
            const scale = Math.min(1, maxSize / Math.max(img.naturalWidth || img.width, img.naturalHeight || img.height));
            canvas.width = Math.floor((img.naturalWidth || img.width) * scale);
            canvas.height = Math.floor((img.naturalHeight || img.height) * scale);

            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
            const data = imageData.data;

            // Build grayscale histogram
            const histogram = new Array(256).fill(0);
            const sampleStep = 4;
            for (let i = 0; i < data.length; i += 4 * sampleStep) {
                const gray = Math.round(0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]);
                histogram[gray]++;
            }

            // Analyze histogram: percentiles + mean
            const total = histogram.reduce((a, b) => a + b, 0);
            const p5 = total * 0.05;
            const p95 = total * 0.95;
            let cumulative = 0, minVal = 0, maxVal = 255;

            for (let i = 0; i < 256; i++) {
                cumulative += histogram[i];
                if (cumulative >= p5 && minVal === 0) minVal = i;
                if (cumulative >= p95) { maxVal = i; break; }
            }

            let sum = 0, count = 0;
            for (let i = 0; i < 256; i++) {
                sum += i * histogram[i];
                count += histogram[i];
            }
            const mean = sum / count;

            const range = maxVal - minVal;
            let contrast = 100;
            if (range > 0 && range < 200) {
                contrast = Math.round(Math.min(200, (200 / range) * 100));
            }

            let brightness = 100;
            if (mean < 100) {
                brightness = Math.round(Math.min(180, 100 + (128 - mean) * 0.5));
            } else if (mean > 160) {
                brightness = Math.round(Math.max(60, 100 - (mean - 128) * 0.5));
            }

            brightness = Math.max(50, Math.min(200, brightness));
            contrast = Math.max(80, Math.min(200, contrast));

            return { brightness, contrast };
        }

        /**
         * Apply per-image adjustments (brightness, contrast, invert) to a canvas context.
         * Must be called after drawImage and before drawing overlays.
         */
        _applyImageAdjustments(ctx, imageUrl, width, height) {
            const adj = this._imageAdjustments.get(imageUrl);
            const hasAdj = adj && (adj.brightness !== 100 || adj.contrast !== 100);
            const needsInvert = this._invertAll;

            if (!hasAdj && !needsInvert) return;

            const imageData = ctx.getImageData(0, 0, width, height);
            const d = imageData.data;

            const b = hasAdj ? adj.brightness / 100 : 1;
            const c = hasAdj ? adj.contrast / 100 : 1;
            const factor = (259 * (c * 255 + 255)) / (255 * (259 + 255 - c * 255));
            // Simplified: for contrast as percentage where 100 = no change
            // We use a simpler approach: scale around 128
            const cFactor = c;

            for (let i = 0; i < d.length; i += 4) {
                let r = d[i], g = d[i + 1], bl = d[i + 2];

                // Brightness
                r *= b; g *= b; bl *= b;

                // Contrast (scale around 128)
                r = ((r - 128) * cFactor) + 128;
                g = ((g - 128) * cFactor) + 128;
                bl = ((bl - 128) * cFactor) + 128;

                // Invert
                if (needsInvert) {
                    r = 255 - r;
                    g = 255 - g;
                    bl = 255 - bl;
                }

                d[i]     = Math.max(0, Math.min(255, r));
                d[i + 1] = Math.max(0, Math.min(255, g));
                d[i + 2] = Math.max(0, Math.min(255, bl));
            }

            ctx.putImageData(imageData, 0, 0);
        }

        _setupEvents() {
            this.eventBus.on(ComparisonEvents.DATA_LOADED, () => this._onDataChanged());
            this.eventBus.on(ComparisonEvents.SAMPLE_ADDED, () => this._onDataChanged());
            this.eventBus.on(ComparisonEvents.SAMPLE_REMOVED, () => this._onDataChanged());
            this.eventBus.on(ComparisonEvents.SAMPLE_ORDER_CHANGED, () => this._render());
            this.eventBus.on(ComparisonEvents.SAMPLE_SELECTED, () => this._render());
            this.eventBus.on(ComparisonEvents.BAND_SELECTED, () => this._render());
        }

        // ──────────────────────────────────────────────
        // Image loading
        // ──────────────────────────────────────────────

        _onDataChanged() {
            const samples = this.state.getSamples();
            if (samples.length === 0) {
                this._showPlaceholder('Add samples to compare gel lanes');
                return;
            }

            // Preload any new gel images
            let needsLoad = false;
            for (const s of samples) {
                if (s.image_url && !this._imageCache.has(s.image_url) && !this._pendingLoads.has(s.image_url)) {
                    needsLoad = true;
                    this._loadImage(s.image_url);
                }
            }

            // Render immediately (images will appear as they load)
            this._render();
        }

        _loadImage(url) {
            this._pendingLoads.add(url);

            const img = new Image();
            img.crossOrigin = 'anonymous';
            img.onload = () => {
                this._imageCache.set(url, img);
                this._pendingLoads.delete(url);

                // If auto-enhance is active, analyze newly loaded image
                const enhanceBtn = document.getElementById('gel-auto-enhance');
                if (enhanceBtn && enhanceBtn.classList.contains('active') && !this._enhancedUrls.has(url)) {
                    const optimal = this._analyzeImage(img);
                    this._imageAdjustments.set(url, {
                        brightness: optimal.brightness,
                        contrast: optimal.contrast,
                    });
                    this._enhancedUrls.add(url);
                }

                this._render();
            };
            img.onerror = () => {
                this._pendingLoads.delete(url);
                console.warn('[GelOverviewPanel] Failed to load image:', url);
            };
            img.src = url;
        }

        // ──────────────────────────────────────────────
        // Render: side-by-side cropped lanes
        // ──────────────────────────────────────────────

        _render() {
            const samples = this.state.getSamples();
            if (samples.length === 0) {
                this._showPlaceholder('Add samples to compare gel lanes');
                return;
            }

            // Dispatch to magnified renderer if expanded
            if (this._isMagnified()) {
                // Delay slightly so the magnify modal is fully laid out
                requestAnimationFrame(() => this._renderMagnified(samples));
                return;
            }

            const selectedBandId = this.state.selectedBandId;
            const selectedSampleId = this.state.selectedSampleId;

            // Build grid of crop canvases
            let html = '<div class="dm-gel-crops-grid">';

            samples.forEach((sample) => {
                const isSelected = sample.sampleId === selectedSampleId;
                html += `
                    <div class="dm-gel-crop-column ${isSelected ? 'selected' : ''}"
                         data-sample-id="${sample.sampleId}"
                         style="border-top: 3px solid ${sample.color};">
                        <div class="dm-gel-crop-header" data-sample-id="${sample.sampleId}">
                            ${this._truncate(sample.label, 16) || 'Sample'}
                        </div>
                        <canvas class="dm-gel-crop-canvas"
                                data-sample-id="${sample.sampleId}"></canvas>
                        <div class="dm-gel-crop-footer">
                            L${sample.lane?.lane_number || '?'}
                        </div>
                    </div>
                `;
            });

            html += '</div>';
            this.contentElement.innerHTML = html;

            // Draw each crop canvas
            samples.forEach((sample) => {
                const canvas = this.contentElement.querySelector(
                    `canvas[data-sample-id="${sample.sampleId}"]`
                );
                if (canvas) {
                    this._drawCropCanvas(canvas, sample, selectedBandId);
                }
            });

            // Attach click handlers
            this._attachClickHandlers();

            // Attach drag reorder
            const grid = this.contentElement.querySelector('.dm-gel-crops-grid');
            if (grid && this.laneReorder) {
                this.laneReorder.container = grid;
                this.laneReorder.attach();
            }
        }

        _drawCropCanvas(canvas, sample, selectedBandId) {
            const bbox = sample.lane?.bbox;
            const img = sample.image_url ? this._imageCache.get(sample.image_url) : null;

            // Size canvas to container
            const col = canvas.parentElement;
            const headerH = col.querySelector('.dm-gel-crop-header')?.offsetHeight || 24;
            const footerH = col.querySelector('.dm-gel-crop-footer')?.offsetHeight || 20;
            const availH = col.offsetHeight - headerH - footerH;
            const availW = col.offsetWidth;

            if (availW <= 0 || availH <= 0) return;

            canvas.width = availW;
            canvas.height = Math.max(availH, 80);

            const ctx = canvas.getContext('2d');
            ctx.fillStyle = '#1e1e22';
            ctx.fillRect(0, 0, canvas.width, canvas.height);

            if (!img || !bbox || !bbox.width || !bbox.height) {
                // No image or no bbox — dark placeholder
                ctx.fillStyle = 'rgba(255,255,255,0.3)';
                ctx.font = '11px Inter, system-ui, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(
                    img ? 'No lane geometry' : 'Loading...',
                    canvas.width / 2, canvas.height / 2
                );
                return;
            }

            // Crop parameters with padding
            const padX = Math.max(5, bbox.width * 0.1);
            const padY = Math.max(5, bbox.height * 0.05);
            const sx = Math.max(0, bbox.x - padX);
            const sy = Math.max(0, bbox.y - padY);
            const sw = Math.min(img.width - sx, bbox.width + padX * 2);
            const sh = Math.min(img.height - sy, bbox.height + padY * 2);

            // Draw cropped gel, scaled to fill canvas
            ctx.drawImage(img, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);

            // Apply per-image adjustments (brightness, contrast, invert)
            this._applyImageAdjustments(ctx, sample.image_url, canvas.width, canvas.height);

            // Draw band overlays (if enabled)
            if (sample.bands && this.showBands) {
                const scaleX = canvas.width / sw;
                const scaleY = canvas.height / sh;

                sample.bands.forEach(band => {
                    if (!band.bbox || !band.bbox.width) return;
                    const bb = band.bbox;

                    // Convert band bbox to crop-relative coords
                    const bx = (bb.x - sx) * scaleX;
                    const by = (bb.y - sy) * scaleY;
                    const bw = bb.width * scaleX;
                    const bh = bb.height * scaleY;

                    // Band fill
                    let color;
                    switch (band.band_type) {
                        case 'POI': color = this.colors.bandPOI; break;
                        case 'MW_REFERENCE': color = this.colors.bandRef; break;
                        default: color = this.colors.bandOther;
                    }

                    ctx.fillStyle = color;
                    ctx.globalAlpha = 0.4;
                    ctx.fillRect(bx, by, bw, bh);
                    ctx.globalAlpha = 1.0;

                    // Selected band highlight
                    if (band.id === selectedBandId) {
                        ctx.strokeStyle = this.colors.bandSelected;
                        ctx.lineWidth = 2;
                        ctx.strokeRect(bx, by, bw, bh);
                    }
                });
            }
        }

        _attachClickHandlers() {
            // Click on canvas → detect band or sample
            this.contentElement.querySelectorAll('.dm-gel-crop-canvas').forEach(canvas => {
                canvas.style.cursor = 'pointer';
                canvas.addEventListener('click', (e) => {
                    const sampleId = canvas.dataset.sampleId;
                    const sample = this.state.getSample(sampleId);
                    if (!sample) return;

                    // Try to detect band click
                    const bbox = sample.lane?.bbox;
                    const img = sample.image_url ? this._imageCache.get(sample.image_url) : null;
                    if (bbox && img && sample.bands) {
                        const rect = canvas.getBoundingClientRect();
                        const cx = e.clientX - rect.left;
                        const cy = e.clientY - rect.top;

                        const padX = Math.max(5, bbox.width * 0.1);
                        const padY = Math.max(5, bbox.height * 0.05);
                        const sx = Math.max(0, bbox.x - padX);
                        const sy = Math.max(0, bbox.y - padY);
                        const sw = Math.min(img.width - sx, bbox.width + padX * 2);
                        const sh = Math.min(img.height - sy, bbox.height + padY * 2);
                        const scaleX = canvas.width / sw;
                        const scaleY = canvas.height / sh;

                        for (const band of sample.bands) {
                            if (!band.bbox || !band.bbox.width) continue;
                            const bb = band.bbox;
                            const bx = (bb.x - sx) * scaleX;
                            const by = (bb.y - sy) * scaleY;
                            const bw = bb.width * scaleX;
                            const bh = bb.height * scaleY;

                            if (cx >= bx && cx <= bx + bw && cy >= by && cy <= by + bh) {
                                this.state.selectBand(band.id);
                                return;
                            }
                        }
                    }

                    // Fallback: select sample
                    this.state.selectSample(sampleId);
                });
            });

            // Header click → select sample
            this.contentElement.querySelectorAll('.dm-gel-crop-header').forEach(hdr => {
                hdr.style.cursor = 'pointer';
                hdr.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const sampleId = hdr.dataset.sampleId;
                    if (sampleId) this.state.selectSample(sampleId);
                });
            });
        }

        _truncate(str, max) {
            if (!str) return '';
            return str.length > max ? str.substring(0, max - 1) + '\u2026' : str;
        }

        // ──────────────────────────────────────────────
        // Magnified view: full gel images side by side
        // ──────────────────────────────────────────────

        _renderMagnified(samples) {
            const selectedBandId = this.state.selectedBandId;
            const selectedSampleId = this.state.selectedSampleId;

            // Group samples by image_url to show each unique gel once
            const gelGroups = new Map(); // image_url → [sample, ...]
            for (const s of samples) {
                const url = s.image_url || '__none__';
                if (!gelGroups.has(url)) gelGroups.set(url, []);
                gelGroups.get(url).push(s);
            }

            let html = '<div class="dm-magnified-gels">';

            for (const [url, group] of gelGroups) {
                const hasImage = url !== '__none__' && this._imageCache.has(url);
                const title = group[0].analysis?.name || 'Gel Image';
                const laneLabels = group.map(s => `L${s.lane?.lane_number || '?'}`).join(', ');

                html += `
                    <div class="dm-magnified-gel-card">
                        <div class="dm-magnified-gel-title">
                            ${this._truncate(title, 40)} — ${laneLabels}
                        </div>
                        <div class="dm-magnified-gel-canvas-wrap">
                            <canvas class="dm-magnified-gel-canvas"
                                    data-image-url="${url}"></canvas>
                        </div>
                    </div>
                `;
            }

            html += '</div>';
            this.contentElement.innerHTML = html;

            // Draw full gel canvases
            for (const [url, group] of gelGroups) {
                const canvas = this.contentElement.querySelector(
                    `canvas[data-image-url="${url}"]`
                );
                if (canvas) {
                    this._drawFullGelCanvas(canvas, url, group, selectedBandId, selectedSampleId);
                }
            }
        }

        _drawFullGelCanvas(canvas, imageUrl, samples, selectedBandId, selectedSampleId) {
            const img = this._imageCache.get(imageUrl);

            if (!img) {
                canvas.width = 400;
                canvas.height = 200;
                const ctx = canvas.getContext('2d');
                ctx.fillStyle = '#1e1e22';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.fillStyle = 'rgba(255,255,255,0.3)';
                ctx.font = '14px Inter, system-ui, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText('No gel image available', canvas.width / 2, 100);
                return;
            }

            // Draw at native image resolution; CSS max-width/max-height handles display sizing
            canvas.width = img.width;
            canvas.height = img.height;
            const scale = 1;

            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, img.width, img.height);

            // Apply per-image adjustments (brightness, contrast, invert)
            this._applyImageAdjustments(ctx, imageUrl, canvas.width, canvas.height);

            // Draw lane and band overlays for each sample on this gel
            for (const sample of samples) {
                const isSelectedSample = sample.sampleId === selectedSampleId;
                const bbox = sample.lane?.bbox;
                if (!bbox || !bbox.width) continue;

                // Lane bounding box
                const lx = bbox.x * scale;
                const ly = bbox.y * scale;
                const lw = bbox.width * scale;
                const lh = bbox.height * scale;

                ctx.strokeStyle = sample.color;
                ctx.lineWidth = isSelectedSample ? 3 : 2;
                ctx.setLineDash(isSelectedSample ? [] : [6, 4]);
                ctx.strokeRect(lx, ly, lw, lh);
                ctx.setLineDash([]);

                // Lane label pill
                const label = `L${sample.lane.lane_number}`;
                ctx.font = 'bold 12px Inter, system-ui, sans-serif';
                const lbl_w = ctx.measureText(label).width + 10;
                ctx.fillStyle = sample.color;
                ctx.fillRect(lx, ly - 20, lbl_w, 18);
                ctx.fillStyle = '#fff';
                ctx.fillText(label, lx + 5, ly - 5);

                // Sample name below lane
                ctx.font = '11px Inter, system-ui, sans-serif';
                const sName = this._truncate(sample.label, 22);
                const sNameW = ctx.measureText(sName).width + 8;
                ctx.fillStyle = 'rgba(0,0,0,0.6)';
                ctx.fillRect(lx + (lw - sNameW) / 2, ly + lh + 2, sNameW, 16);
                ctx.fillStyle = '#fff';
                ctx.textAlign = 'center';
                ctx.fillText(sName, lx + lw / 2, ly + lh + 14);
                ctx.textAlign = 'start';

                // Band overlays (if enabled)
                if (sample.bands && this.showBands) {
                    for (const band of sample.bands) {
                        if (!band.bbox || !band.bbox.width) continue;
                        const bb = band.bbox;
                        const bx = bb.x * scale;
                        const by = bb.y * scale;
                        const bw = bb.width * scale;
                        const bh = bb.height * scale;

                        let color;
                        switch (band.band_type) {
                            case 'POI': color = this.colors.bandPOI; break;
                            case 'MW_REFERENCE': color = this.colors.bandRef; break;
                            default: color = this.colors.bandOther;
                        }

                        ctx.fillStyle = color;
                        ctx.globalAlpha = 0.4;
                        ctx.fillRect(bx, by, bw, bh);
                        ctx.globalAlpha = 1.0;

                        if (band.id === selectedBandId) {
                            ctx.strokeStyle = this.colors.bandSelected;
                            ctx.lineWidth = 2;
                            ctx.strokeRect(bx, by, bw, bh);
                        }

                        // MW label for magnified view
                        if (band.estimated_mw_kda) {
                            ctx.font = '10px Inter, system-ui, sans-serif';
                            const mwText = `${band.estimated_mw_kda.toFixed(0)}`;
                            ctx.fillStyle = 'rgba(0,0,0,0.7)';
                            const tw = ctx.measureText(mwText).width + 4;
                            ctx.fillRect(bx + bw + 2, by, tw, 14);
                            ctx.fillStyle = '#fff';
                            ctx.fillText(mwText, bx + bw + 4, by + 11);
                        }
                    }
                }
            }

            // Click handler for magnified canvas
            canvas.style.cursor = 'pointer';
            canvas.onclick = (e) => {
                const rect = canvas.getBoundingClientRect();
                // Convert CSS display coords to native canvas coords
                const cssToNativeX = canvas.width / rect.width;
                const cssToNativeY = canvas.height / rect.height;
                const cx = (e.clientX - rect.left) * cssToNativeX;
                const cy = (e.clientY - rect.top) * cssToNativeY;

                // Check band clicks (coordinates are in native image space)
                for (const sample of samples) {
                    if (!sample.bands) continue;
                    for (const band of sample.bands) {
                        if (!band.bbox || !band.bbox.width) continue;
                        const bb = band.bbox;
                        if (cx >= bb.x && cx <= bb.x + bb.width && cy >= bb.y && cy <= bb.y + bb.height) {
                            this.state.selectBand(band.id);
                            return;
                        }
                    }
                }

                // Check lane clicks
                for (const sample of samples) {
                    const bbox = sample.lane?.bbox;
                    if (!bbox) continue;
                    if (cx >= bbox.x && cx <= bbox.x + bbox.width && cy >= bbox.y && cy <= bbox.y + bbox.height) {
                        this.state.selectSample(sample.sampleId);
                        return;
                    }
                }
            };
        }
    }

    // Export to namespace
    global.SampleComparison = global.SampleComparison || {};
    global.SampleComparison.Panels = global.SampleComparison.Panels || {};
    global.SampleComparison.Panels.GelOverview = GelOverviewPanel;

})(window);
