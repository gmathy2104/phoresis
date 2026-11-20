/**
 * review-panel.js
 *
 * Review of the lanes the lane model found, on the gel itself (Grégory 2026-10-10). The old floating panel was a
 * 260 px card listing five lanes at a time over the gel's right-hand side, and its labels on the gel were SVG text
 * in image pixels, a few screen pixels high at "fit" on a large gel.
 *
 *   - a bar above the gel (`_review_panel.html`, inside `.gv-viewer-wrapper`): how many lanes are kept, the gel
 *     type, the minimum confidence, Reject all / Accept N. While it is open the viewer starts below it and the gel
 *     is fitted again, so no lane is hidden.
 *   - on the gel, every detection outlined in its type's colour (dashed grey once dropped), a tag above it -- the
 *     number it will be saved under, left to right among the kept lanes, and its type -- and its confidence below.
 *     Tags and confidences are HTML laid over the viewer in screen pixels, moved on every pan and zoom.
 *   - click a lane: keep / drop it; click its tag: change its type; Left/Right: move between lanes; Space: keep /
 *     drop the focused one; Ctrl+Enter: accept; Esc: close the type menu, else reject all. While the review is open
 *     it owns the keyboard: the editor's shortcuts are held back, except zoom (+, -, 0).
 *
 * The model runs from a 25 % floor (gel-viewer.js, `_autoDetect`); the slider starts at 50 %, the cut the model
 * used before, so an untouched review keeps exactly what it always kept, and lowering it brings back a lane the
 * model saw between 25 and 50 %. Moving the slider re-applies the threshold to every lane; a click then overrides
 * it for that lane.
 *
 * Straight / Follow the lanes (spec 2026-10-10 §10, opt-in after the bench, §9): the review opens Straight, today's
 * rectangles. On show it posts every detection's box and its own mask slope (the lane worker's fit) to lanes/tilt/;
 * the server answers each lane's axis by the guarded mask slope. *Follow the lanes* becomes clickable once a lane is
 * tilted by 4 px or more and redraws them along their axes. In both modes every lane is drawn AS IT WILL BE SAVED: cut
 * at the common top and bottom of the kept lanes (recomputed on every keep, drop and slider move), clamped to the
 * image, so Accept writes what is on screen and never waits. A reply carries the review's token: one that comes
 * after Accept, Reject or a newer review is dropped (hide() bumps the token and aborts the request).
 *
 * @requires GelViewer.Events
 * @requires SVG.js (the outlines live in the SVG overlay, in image pixels)
 */

(function(global) {
    'use strict';

    const Events = global.GelViewer.Events;

    /** The cut the lane model used before the review had a slider: an untouched review keeps the same lanes. */
    const DEFAULT_THRESHOLD = 50;

    /** The lane types a tag offers, in the properties panel's words. */
    const LANE_TYPES = [
        { value: 'SAMPLE', label: 'Sample', short: 'S' },
        { value: 'LADDER', label: 'MW Ladder', short: 'L' },
        { value: 'CONTROL', label: 'Control', short: 'Ct' },
        { value: 'CALIBRATION', label: 'Calibration Standard', short: 'Ca' },
        { value: 'EMPTY', label: 'Empty', short: 'E' },
        { value: 'DOT', label: 'Dot', short: 'D' },
    ];

    const GEL_TYPE_LABELS = { SDS_PAGE: 'SDS-PAGE', DOT_BLOT: 'Dot Blot' };

    /** Keys the review leaves to the editor: zoom in, zoom out, fit. */
    const PASS_THROUGH_KEYS = new Set(['+', '=', '-', '0']);

    /** A press that moved more than this (screen px) was a pan, not a click on a lane. */
    const CLICK_SLOP = 4;

    /** Tag height in the CSS (`.gv-review-tag`), to keep a tag inside the viewer when a lane starts at its top. */
    const TAG_HEIGHT = 20;

    /** Below this lane width on screen, a tag shows its number alone. */
    const COMPACT_LANE_WIDTH = 34;

    /** The review's fit: the whole gel as large as the viewer allows, a tag's height free above and below. */
    const REVIEW_FIT = { maxScale: 3, fill: 0.97, padX: 12, padY: TAG_HEIGHT + 10 };

    /** The tilt reply's deadline: past it the review stays Straight, the toggle says why. */
    const TILT_TIMEOUT_MS = 10000;

    function typeOf(value) {
        return LANE_TYPES.find(t => t.value === value) || { value, label: value, short: value.charAt(0) };
    }

    /** shape.py's quad_from_axis and outer_bbox (the server's Rule 1), from shared/lane-geometry.js. */
    const { quadFromAxis, outerBox } = global.GelAnalyzer.LaneGeometry;

    /**
     * Top-centre and bottom-centre of an outline, in image pixels: the middle of its two highest and its two lowest
     * corners, so a tilted lane gets its tag above its own top.
     */
    function anchorsOf(points) {
        const byY = [...points].sort((p, q) => p[1] - q[1]);
        const top = byY.slice(0, 2);
        const bottom = byY.slice(-2);
        const xs = points.map(p => p[0]);
        return {
            top: [(top[0][0] + top[1][0]) / 2, Math.min(top[0][1], top[1][1])],
            bottom: [(bottom[0][0] + bottom[1][0]) / 2, Math.max(bottom[0][1], bottom[1][1])],
            width: Math.max(...xs) - Math.min(...xs),
        };
    }

    class ReviewPanel {
        /**
         * @param {Object} options
         * @param {EventBus} options.eventBus
         * @param {StateManager} options.stateManager
         * @param {Object} options.svg - SVG.js root of the overlay
         * @param {Viewport} options.viewport - pan and zoom, to place the tags in screen pixels
         * @param {APIClient} [options.apiClient] - lanes/tilt/; without it the review stays Straight
         * @param {Function} options.onAccept - called with the kept detections (their types and shapes as reviewed)
         */
        constructor(options) {
            this.eventBus = options.eventBus;
            this.stateManager = options.stateManager;
            this.svg = options.svg;
            this.viewport = options.viewport;
            this.apiClient = options.apiClient || null;
            this.onAccept = options.onAccept;

            this.detections = [];
            this.kept = new Set();
            this.threshold = DEFAULT_THRESHOLD;
            this.focus = -1;
            this.inferredGelType = 'UNKNOWN';
            this.isVisible = false;

            // Straight / Follow the lanes
            this.mode = 'straight';
            this.axes = new Map();      // detection index -> {x_ref, slope, width, source}
            this.yRef = 0;
            this.tiltState = 'idle';    // idle | measuring | ready | none | error
            this.tiltMessage = '';
            this._token = 0;
            this._abort = null;
            this._timer = null;
            this._shapes = [];

            this._unsubscribe = [];
            this._pressAt = null;
            this._onKeyDown = this._onKeyDown.bind(this);
            this._onOutsidePress = this._onOutsidePress.bind(this);

            this._setupDOM();
            this._bindEvents();
        }

        // ─── DOM ──────────────────────────────────────────────────────

        _setupDOM() {
            this.panel = document.getElementById('review-panel');
            this.wrapper = this.panel ? this.panel.closest('.gv-viewer-wrapper') : null;
            this.viewer = this.wrapper ? this.wrapper.querySelector('.gv-viewer') : document.querySelector('.gv-viewer');
            this.countEl = document.getElementById('review-count');
            this.gelTypeEl = document.getElementById('review-gel-type');
            this.thresholdInput = document.getElementById('review-threshold');
            this.thresholdValue = document.getElementById('review-threshold-value');
            this.acceptBtn = document.getElementById('review-accept-selected');
            this.acceptLabel = document.getElementById('review-accept-label');
            this.rejectBtn = document.getElementById('review-reject-all');
            this.straightBtn = document.getElementById('review-shape-straight');
            this.followBtn = document.getElementById('review-shape-follow');
            this.crossEl = document.getElementById('review-cross');

            // Tags and confidences: HTML over the viewer, in screen pixels.
            this.tagLayer = document.createElement('div');
            this.tagLayer.className = 'gv-review-tags';
            this.tagLayer.hidden = true;
            if (this.viewer) this.viewer.appendChild(this.tagLayer);

            this.typeMenu = document.createElement('div');
            this.typeMenu.className = 'gv-review-type-menu';
            this.typeMenu.setAttribute('role', 'menu');
            this.typeMenu.hidden = true;
            this.typeMenu.innerHTML = LANE_TYPES.map(t => `
                <button type="button" role="menuitemradio" data-type="${t.value}">
                    <span class="gv-review-swatch t-${t.value.toLowerCase()}"></span>${t.label}
                </button>`).join('');
            this.tagLayer.appendChild(this.typeMenu);
            this._menuFor = -1;

            this.previewGroup = this.svg ? this.svg.group().attr('id', 'detection-previews') : null;
            this._polygons = [];
            this._tags = [];
            this._confs = [];
        }

        _bindEvents() {
            if (this.acceptBtn) this.acceptBtn.addEventListener('click', () => this.acceptSelected());
            if (this.rejectBtn) this.rejectBtn.addEventListener('click', () => this.rejectAll());
            if (this.straightBtn) this.straightBtn.addEventListener('click', () => this.setMode('straight'));
            if (this.followBtn) this.followBtn.addEventListener('click', () => this.setMode('follow'));

            if (this.thresholdInput) {
                this.thresholdInput.addEventListener('input', () => this._setThreshold(Number(this.thresholdInput.value)));
                // Hand Left/Right back to the lanes once the mouse lets go of the slider.
                this.thresholdInput.addEventListener('pointerup', () => this.thresholdInput.blur());
            }

            this.typeMenu.addEventListener('pointerdown', (e) => e.stopPropagation());
            this.typeMenu.addEventListener('click', (e) => {
                const item = e.target.closest('button[data-type]');
                if (!item || this._menuFor < 0) return;
                this._setType(this._menuFor, item.dataset.type);
                this._closeTypeMenu();
            });
        }

        // ─── Show / hide ──────────────────────────────────────────────

        /**
         * @param {Array<Object>} detections - the lane model's, left to right, from its 25 % floor
         * @param {string} inferredGelType
         */
        show(detections, inferredGelType) {
            this.detections = detections.map(d => ({ ...d }));
            this.inferredGelType = inferredGelType || 'UNKNOWN';
            this.threshold = DEFAULT_THRESHOLD;
            if (this.thresholdInput) this.thresholdInput.value = String(DEFAULT_THRESHOLD);
            this.kept = this._keptAt(this.threshold);
            this.focus = -1;
            this.mode = 'straight';
            this.axes = new Map();

            this._computeShapes();
            this._renderPreviews();
            this._renderTags();
            this._refresh();
            this._measureTilt();

            if (this.panel) this.panel.hidden = false;
            if (this.wrapper) this.wrapper.classList.add('gv-reviewing');
            this.tagLayer.hidden = false;
            this.isVisible = true;

            const place = () => this._positionTags();
            this._unsubscribe = [Events.PAN_CHANGED, Events.ZOOM_CHANGED, Events.VIEWPORT_CHANGED]
                .map(event => this.eventBus.on(event, place));
            global.addEventListener('keydown', this._onKeyDown, true);
            document.addEventListener('pointerdown', this._onOutsidePress, true);

            // The viewer now starts below the bar: the gel fills what is left (97 %, not the editor's 90 %), with
            // room for the tags above the lanes and the confidences below (fitToView emits VIEWPORT_CHANGED, which
            // places the tags).
            requestAnimationFrame(() => {
                if (this.viewport) this.viewport.fitToView(REVIEW_FIT);
                else place();
            });

            this.eventBus.emit(Events.REVIEW_SHOWN, {
                count: this.detections.length,
                inferredGelType: this.inferredGelType,
            });
        }

        hide() {
            if (!this.isVisible) return;

            // A tilt reply still on its way belongs to a review that no longer exists.
            this._token += 1;
            this._currentToken = null;
            this._stopTiltRequest();
            this.tiltState = 'idle';

            this._closeTypeMenu();
            this._unsubscribe.forEach(off => off());
            this._unsubscribe = [];
            global.removeEventListener('keydown', this._onKeyDown, true);
            document.removeEventListener('pointerdown', this._onOutsidePress, true);

            if (this.previewGroup) this.previewGroup.clear();
            this._polygons = [];
            this._tags.forEach(el => el.remove());
            this._confs.forEach(el => el.remove());
            this._tags = [];
            this._confs = [];
            this.tagLayer.hidden = true;

            if (this.panel) this.panel.hidden = true;
            if (this.wrapper) this.wrapper.classList.remove('gv-reviewing');
            this.isVisible = false;
            this.detections = [];
            this.kept = new Set();
            this.focus = -1;

            // The viewer has its full height back.
            requestAnimationFrame(() => this.viewport && this.viewport.fitToView());

            this.eventBus.emit(Events.REVIEW_HIDDEN);
        }

        // ─── Actions ──────────────────────────────────────────────────

        /** Accept the kept lanes, with the types the review gave them. */
        acceptSelected() {
            if (this.kept.size === 0) {
                this._showMessage('No lane kept');
                return;
            }
            const accepted = this.getSelectedDetections();
            const gelType = this.inferredGelType;

            if (this.onAccept) this.onAccept(accepted, gelType);
            this.eventBus.emit(Events.REVIEW_ACCEPTED, { count: accepted.length, inferredGelType: gelType });
            this.hide();
        }

        rejectAll() {
            const count = this.detections.length;
            this.hide();
            this.eventBus.emit(Events.REVIEW_REJECTED, { count });
        }

        /** Keep or drop one lane. */
        toggleSelection(index) {
            if (this.kept.has(index)) this.kept.delete(index);
            else this.kept.add(index);
            this._refresh();
        }

        _setThreshold(percent) {
            this.threshold = percent;
            this.kept = this._keptAt(percent);
            this._refresh();
        }

        _keptAt(percent) {
            const kept = new Set();
            this.detections.forEach((d, i) => {
                if (Math.round(d.confidence * 100) >= percent) kept.add(i);
            });
            return kept;
        }

        _setType(index, laneType) {
            const detection = this.detections[index];
            if (!detection || detection.lane_type === laneType) return;
            detection.lane_type = laneType;
            this._refresh();
        }

        _setFocus(index) {
            this.focus = index;
            this._refresh();
        }

        // ─── Straight / Follow the lanes ──────────────────────────────

        /** 'straight' or 'follow'; follow only once the reply came back with a tilted lane. */
        setMode(mode) {
            if (mode === 'follow' && this.tiltState !== 'ready') return;
            if (mode === this.mode) return;
            this.mode = mode;
            this._refresh();
        }

        /** True when the server tilted this lane (its drift over the box reached the app's threshold). */
        _isTilted(index) {
            const axis = this.axes.get(index);
            return !!axis && axis.source !== 'straight' && axis.slope !== 0;
        }

        _stopTiltRequest() {
            if (this._timer) clearTimeout(this._timer);
            this._timer = null;
            if (this._abort) this._abort.abort();
            this._abort = null;
        }

        /** lanes/tilt/ with every detection's box and mask slope; the reply is applied only to this review. */
        async _measureTilt() {
            this._stopTiltRequest();
            const token = String((this._token += 1)) + '-' + Date.now();
            this._currentToken = token;
            if (!this.apiClient || !this.detections.length) {
                this.tiltState = 'error';
                this.tiltMessage = 'The lanes\' tilt cannot be measured here';
                this._refresh();
                return;
            }
            this.tiltState = 'measuring';
            this._refresh();
            const abort = new AbortController();
            this._abort = abort;
            this._timer = setTimeout(() => abort.abort(), TILT_TIMEOUT_MS);
            const body = {
                token,
                boxes: this.detections.map((d, index) => ({
                    index, box: d.bbox, mask_slope: d.mask_slope == null ? null : d.mask_slope,
                })),
            };
            let reply = null, failure = null;
            try {
                reply = await this.apiClient.measureLaneTilt(body, abort.signal);
            } catch (error) {
                failure = error.name === 'AbortError' ? 'No answer within 10 s' : (error.message || 'request failed');
            }
            if (!this.isVisible || this._currentToken !== token) return; // closed, or a newer review
            this._stopTiltRequest();
            if (failure || !reply || reply.token !== token) {
                this.tiltState = 'error';
                this.tiltMessage = `The lanes' tilt could not be measured: ${failure || 'unexpected answer'}`;
                this._refresh();
                return;
            }
            this.yRef = reply.y_ref;
            this.axes = new Map(reply.lanes.map(lane => [lane.index, lane]));
            const tilted = this.detections.some((_, i) => this._isTilted(i));
            this.tiltState = tilted ? 'ready' : 'none';
            this.tiltMessage = tilted ? '' : 'No lane drifts by 4 px or more over its height';
            this._refresh();
        }

        /**
         * Every lane's outline as it will be saved: its box, or (Follow, tilted) its axis -- both cut at the common
         * top and bottom of the kept lanes, clamped to the image and rounded.
         */
        _computeShapes() {
            const kept = this.detections.filter((_, i) => this.kept.has(i));
            const basis = kept.length ? kept : this.detections;
            const top = Math.min(...basis.map(d => d.bbox[1]));
            const bottom = Math.max(...basis.map(d => d.bbox[1] + d.bbox[3]));
            const width = (this.viewport && this.viewport.imageWidth) || Infinity;
            const height = (this.viewport && this.viewport.imageHeight) || Infinity;
            const clamp = (v, max) => Math.round(Math.min(Math.max(v, 0), max));
            this._shapes = this.detections.map((d, index) => {
                const [x, , w] = d.bbox;
                let points;
                if (this.mode === 'follow' && this._isTilted(index)) {
                    const axis = this.axes.get(index);
                    points = quadFromAxis(axis.x_ref, this.yRef, axis.slope, axis.width, top, bottom);
                } else {
                    points = [[x, top], [x + w, top], [x + w, bottom], [x, bottom]];
                }
                return points.map(([px, py]) => [clamp(px, width), clamp(py, height)]);
            });
        }

        /**
         * Kept neighbours that overlap enough to be integrated twice: the densitometry reads the central 50 % of each
         * lane's row (profile_width_percent), so two profiles overlap when the lanes overlap by more than a quarter of
         * their summed widths -- at the top or at the bottom. Dense gels' boxes touch by a few pixels even straight
         * (12dd03b1: up to 10 px): that is not a warning.
         */
        _crossings() {
            const kept = this.detections.map((_, i) => i).filter(i => this.kept.has(i));
            const pairs = [];
            for (let k = 0; k + 1 < kept.length; k++) {
                const a = this._shapes[kept[k]], b = this._shapes[kept[k + 1]];
                const top = a[1][0] - b[0][0] > ((a[1][0] - a[0][0]) + (b[1][0] - b[0][0])) / 4;
                const bottom = a[2][0] - b[3][0] > ((a[2][0] - a[3][0]) + (b[2][0] - b[3][0])) / 4;
                if (top || bottom) pairs.push([kept[k], kept[k + 1]]);
            }
            return pairs;
        }

        // ─── Rendering ────────────────────────────────────────────────

        _renderPreviews() {
            if (!this.previewGroup) return;
            this.previewGroup.clear();
            this._polygons = this.detections.map((detection, index) => {
                const poly = this.previewGroup.polygon(this._shapes[index].map(p => p.join(',')).join(' '))
                    .attr('id', `detection-preview-${index}`)
                    .addClass('gv-detection-preview');

                poly.on('pointerdown', (e) => { this._pressAt = [e.clientX, e.clientY]; });
                poly.on('click', (e) => {
                    if (this._wasPan(e)) return;
                    e.stopPropagation();
                    this.focus = index;
                    this.toggleSelection(index);
                });
                poly.on('mouseenter', () => this._hover(index, true));
                poly.on('mouseleave', () => this._hover(index, false));
                return poly;
            });
        }

        _renderTags() {
            this._tags.forEach(el => el.remove());
            this._confs.forEach(el => el.remove());

            this._tags = this.detections.map((detection, index) => {
                const tag = document.createElement('button');
                tag.type = 'button';
                tag.className = 'gv-review-tag';
                tag.setAttribute('aria-haspopup', 'menu');
                tag.innerHTML = '<span class="gv-review-tag-n"></span><span class="gv-review-tag-t"></span>';
                // A press on a tag is not the start of a pan or of a drawing.
                tag.addEventListener('pointerdown', (e) => e.stopPropagation());
                tag.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.focus = index;
                    this._refresh();
                    this._toggleTypeMenu(index);
                });
                tag.addEventListener('mouseenter', () => this._hover(index, true));
                tag.addEventListener('mouseleave', () => this._hover(index, false));
                this.tagLayer.insertBefore(tag, this.typeMenu);
                return tag;
            });

            this._confs = this.detections.map((detection) => {
                const conf = document.createElement('span');
                const percent = Math.round(detection.confidence * 100);
                conf.className = 'gv-review-conf ' + (percent >= 80 ? 'high' : percent >= 50 ? 'medium' : 'low');
                conf.textContent = `${percent} %`;
                this.tagLayer.insertBefore(conf, this.typeMenu);
                return conf;
            });
        }

        /** Every state-dependent class and text: outlines, tags, numbers, the bar. */
        _refresh() {
            // The outlines as they will be saved: they move with the kept set (common top and bottom) and the mode.
            this._computeShapes();
            this._polygons.forEach((poly, index) => poly.plot(this._shapes[index]));

            // Numbers as they will be saved: left to right among the kept lanes (the detections are sorted by x).
            const numbers = new Map();
            let next = 1;
            this.detections.forEach((_, i) => {
                if (this.kept.has(i)) numbers.set(i, next++);
            });

            this.detections.forEach((detection, index) => {
                const kept = this.kept.has(index);
                const type = typeOf(detection.lane_type || 'SAMPLE');
                const typeClass = `t-${type.value.toLowerCase()}`;
                const percent = Math.round(detection.confidence * 100);

                const poly = this._polygons[index];
                if (poly) {
                    const node = poly.node;
                    node.setAttribute('class', `gv-detection-preview ${typeClass}`);
                    node.classList.toggle('kept', kept);
                    node.classList.toggle('dropped', !kept);
                    node.classList.toggle('focused', index === this.focus);
                }

                const tag = this._tags[index];
                if (tag) {
                    tag.className = `gv-review-tag ${typeClass}`;
                    tag.classList.toggle('dropped', !kept);
                    tag.classList.toggle('focused', index === this.focus);
                    tag.querySelector('.gv-review-tag-n').textContent = kept ? String(numbers.get(index)) : '–';
                    tag.querySelector('.gv-review-tag-t').textContent = type.short;
                    const axis = this.axes.get(index);
                    const tilt = this._isTilted(index)
                        ? ` · tilted ${(Math.atan(axis.slope) * 180 / Math.PI).toFixed(1)}°`
                        : '';
                    tag.title = `${kept ? `Lane ${numbers.get(index)}` : 'Dropped'} · ${type.label} · ${percent} %`
                        + `${tilt} — click to change its type`;
                }
            });

            const total = this.detections.length;
            const n = this.kept.size;
            if (this.countEl) this.countEl.textContent = `${n} of ${total} lane${total !== 1 ? 's' : ''} kept`;
            if (this.gelTypeEl) {
                this.gelTypeEl.textContent = GEL_TYPE_LABELS[this.inferredGelType] || this.inferredGelType;
                this.gelTypeEl.hidden = !this.inferredGelType || this.inferredGelType === 'UNKNOWN';
            }
            if (this.thresholdValue) this.thresholdValue.textContent = `${this.threshold} %`;
            if (this.acceptLabel) this.acceptLabel.textContent = `Accept ${n} lane${n !== 1 ? 's' : ''}`;
            if (this.acceptBtn) this.acceptBtn.disabled = n === 0;

            this._refreshShapeControl(numbers);
            if (this._menuFor >= 0) this._markMenu(this._menuFor);
            this._positionTags();
        }

        /** The Straight / Follow the lanes control and the crossing warning. */
        _refreshShapeControl(numbers) {
            const follow = this.mode === 'follow';
            if (this.straightBtn) this.straightBtn.setAttribute('aria-pressed', String(!follow));
            if (this.followBtn) {
                this.followBtn.setAttribute('aria-pressed', String(follow));
                this.followBtn.disabled = this.tiltState !== 'ready';
                this.followBtn.classList.toggle('measuring', this.tiltState === 'measuring');
                this.followBtn.title = {
                    measuring: 'Measuring the lanes\' tilt…',
                    ready: 'Draw the lanes along their tilt (the lane model\'s mask, checked on the image)',
                    none: this.tiltMessage,
                    error: this.tiltMessage,
                    idle: '',
                }[this.tiltState] || '';
            }
            if (this.crossEl) {
                const pairs = follow ? this._crossings() : [];
                const names = pairs.map(([a, b]) => `${numbers.get(a)}–${numbers.get(b)}`).join(', ');
                this.crossEl.hidden = pairs.length === 0;
                this.crossEl.textContent = pairs.length
                    ? `${pairs.length} overlap${pairs.length > 1 ? 's' : ''}: lanes ${names}`
                    : '';
                this.crossEl.title = pairs.length
                    ? `Lanes ${names} overlap enough for their densitometry to read the same pixels. `
                      + 'Drop one, or go back to Straight.'
                    : '';
            }
        }

        /** Tags above, confidences below, in screen pixels from the viewport's pan and zoom. */
        _positionTags() {
            if (!this.isVisible || !this.viewport || !this.viewer) return;
            const { scale, panX, panY } = this.viewport;
            const height = this.viewer.clientHeight;

            this.detections.forEach((detection, index) => {
                if (!this._shapes[index]) return;
                const a = anchorsOf(this._shapes[index]);
                const tag = this._tags[index];
                const conf = this._confs[index];
                if (tag) {
                    const x = panX + a.top[0] * scale;
                    const y = panY + a.top[1] * scale;
                    tag.style.left = `${x}px`;
                    tag.style.top = `${Math.max(2, y - TAG_HEIGHT - 4)}px`;
                    tag.classList.toggle('compact', a.width * scale < COMPACT_LANE_WIDTH);
                }
                if (conf) {
                    const x = panX + a.bottom[0] * scale;
                    const y = panY + a.bottom[1] * scale;
                    conf.style.left = `${x}px`;
                    conf.style.top = `${Math.min(height - 18, y + 4)}px`;
                }
            });

            if (this._menuFor >= 0) this._placeMenu(this._menuFor);
        }

        _hover(index, on) {
            const poly = this._polygons[index];
            if (poly) poly.node.classList.toggle('hover', on);
            const tag = this._tags[index];
            if (tag) tag.classList.toggle('hover', on);
        }

        // ─── Type menu ────────────────────────────────────────────────

        _toggleTypeMenu(index) {
            if (this._menuFor === index) {
                this._closeTypeMenu();
                return;
            }
            this._menuFor = index;
            this._markMenu(index);
            this.typeMenu.hidden = false;
            this._placeMenu(index);
        }

        _closeTypeMenu() {
            this._menuFor = -1;
            this.typeMenu.hidden = true;
        }

        _markMenu(index) {
            const current = (this.detections[index] || {}).lane_type;
            this.typeMenu.querySelectorAll('button[data-type]').forEach(b => {
                b.setAttribute('aria-checked', String(b.dataset.type === current));
            });
        }

        /** Under the tag, kept inside the viewer. */
        _placeMenu(index) {
            const tag = this._tags[index];
            if (!tag || !this.viewer) return;
            const width = this.typeMenu.offsetWidth || 150;
            const left = Math.min(Math.max(4, tag.offsetLeft - width / 2), this.viewer.clientWidth - width - 4);
            this.typeMenu.style.left = `${left}px`;
            this.typeMenu.style.top = `${tag.offsetTop + TAG_HEIGHT + 4}px`;
        }

        _onOutsidePress(e) {
            if (this._menuFor < 0) return;
            if (this.typeMenu.contains(e.target) || (this._tags[this._menuFor] || {}).contains?.(e.target)) return;
            this._closeTypeMenu();
        }

        // ─── Keyboard ─────────────────────────────────────────────────

        /** Capture phase on window: the review answers first, and holds the editor's shortcuts back. */
        _onKeyDown(e) {
            if (!this.isVisible) return;
            // A dialog opened over the review (a confirm, the sample selector) gets every key; a panel or a menu
            // open with it gets its Esc, the review keeps the rest.
            const layers = global.GelViewer.Layers;
            if (layers && (layers.hasModal() || (e.key === 'Escape' && layers.hasOpen()))) return;
            const target = e.target;
            if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT')) {
                if (e.key === 'Escape') target.blur();
                return;
            }
            if (PASS_THROUGH_KEYS.has(e.key) && !e.ctrlKey && !e.metaKey) return;

            const last = this.detections.length - 1;
            switch (e.key) {
                case 'ArrowRight':
                    this._setFocus(this.focus < 0 ? 0 : Math.min(last, this.focus + 1));
                    break;
                case 'ArrowLeft':
                    this._setFocus(this.focus < 0 ? last : Math.max(0, this.focus - 1));
                    break;
                case ' ':
                case 'Spacebar':
                    if (this.focus >= 0) this.toggleSelection(this.focus);
                    break;
                case 'Enter':
                    if (e.ctrlKey || e.metaKey) this.acceptSelected();
                    else if (this.focus >= 0) this._toggleTypeMenu(this.focus);
                    break;
                case 'Escape':
                    // Esc never decides (owner, 2026-10-12): it closes the type menu; Reject all is a button.
                    if (this._menuFor >= 0) this._closeTypeMenu();
                    break;
                default:
                    // Tab and the browser's own chords (Ctrl+R, F5...) keep working; the editor's letters do not.
                    if (e.key === 'Tab' || e.ctrlKey || e.metaKey || e.altKey || e.key.length > 1) return;
            }
            e.preventDefault();
            e.stopPropagation();
        }

        // ─── Helpers ──────────────────────────────────────────────────

        /** True when the press that ended in this click moved: a pan across the gel, not a click on a lane. */
        _wasPan(e) {
            if (!this._pressAt) return false;
            const [x, y] = this._pressAt;
            this._pressAt = null;
            return Math.abs(e.clientX - x) > CLICK_SLOP || Math.abs(e.clientY - y) > CLICK_SLOP;
        }

        _showMessage(text) {
            if (global.gelViewer && typeof global.gelViewer._showMessage === 'function') {
                global.gelViewer._showMessage(text);
            }
        }

        isOpen() {
            return this.isVisible;
        }

        /** The kept detections, left to right, with the types the review gave them. */
        getSelectedDetections() {
            const follow = this.mode === 'follow';
            return this.detections
                .map((detection, index) => ({ detection, index }))
                .filter(({ index }) => this.kept.has(index))
                .map(({ detection, index }) => {
                    // What is on screen is what is saved: the outline, its outer box, and QUADRILATERAL when tilted.
                    const polygon = this._shapes[index].map(p => [...p]);
                    return {
                        ...detection,
                        polygon,
                        bbox: outerBox(polygon),
                        lane_shape: follow && this._isTilted(index) ? 'QUADRILATERAL' : 'POLYGON',
                    };
                });
        }

        /** Whether the accepted lanes follow their tilt (for the editor's message). */
        followsLanes() {
            return this.mode === 'follow';
        }
    }

    ReviewPanel.DEFAULT_THRESHOLD = DEFAULT_THRESHOLD;

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.ReviewPanel = ReviewPanel;

})(window);
