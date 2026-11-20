/**
 * corner-handles.js
 *
 * Corner handles for a 4-point lane (spec docs/superpowers/specs/2026-10-10-gel-lane-tilt-design.md §3, D3): selecting
 * a QUADRILATERAL lane -- or an upright 4-point POLYGON one -- shows a handle on each corner instead of the box. Dragging
 * a corner moves its x freely; its y moves both corners of that edge, so the top and the bottom stay horizontal and the
 * side's slope changes. Corners stay inside the image, each edge keeps MIN_PX of width and the top stays MIN_PX above
 * the bottom, so the sides can never cross.
 *
 * While dragging only the drawing moves; the drop commits ONE lane update (QUADRILATERAL, the corners rounded, the box
 * their outer box -- the server's Rule 1), saved as any lane edit (dirty, Ctrl+S, bulk update). Esc during a drag puts
 * the lane back as it was and commits nothing. The scale and the canvas origin are read on every move, so a zoom or a
 * pan in the middle of a drag keeps the corner under the pointer.
 */
(function(global) {
    'use strict';

    const MIN_PX = 6;

    /** Handle diameter, in screen pixels. */
    const HANDLE_PX = 12;

    class CornerHandles {
        /**
         * @param {Object} opts
         * @param {Object} opts.handlesGroup - SVG.js group above the lanes
         * @param {Object} opts.viewport - getImagePoint(e), getScale()
         * @param {Object} opts.renderer - updateLane(lane)
         * @param {number} opts.imageWidth
         * @param {number} opts.imageHeight
         * @param {Function} opts.onCommit - (laneId, {lane_shape, polygon, x, y, width, height})
         */
        constructor({ handlesGroup, viewport, renderer, imageWidth, imageHeight, onCommit }) {
            this.handlesGroup = handlesGroup;
            this.viewport = viewport;
            this.renderer = renderer;
            this.imageWidth = imageWidth;
            this.imageHeight = imageHeight;
            this.onCommit = onCommit;
            this._lane = null;
            this._corners = null;
            this._handles = [];
            this._drag = null;
        }

        get laneId() {
            return this._lane ? this._lane.id : null;
        }

        /** True for a lane drawn by 4 corners (Rule 2, exactly 4 points). */
        static fits(lane) {
            return GelAnalyzer.LaneGeometry.hasOutline(lane) && lane.polygon.length === 4;
        }

        /**
         * Corners TL, TR, BR, BL after dragging corner `index` to `point`: its x moves freely, its y moves both corners
         * of its edge; clamped to the image; the edge keeps >= MIN_PX of width and the top stays MIN_PX above the
         * bottom, so the sides can never cross.
         */
        static dragCorner(corners, index, point, w, h) {
            const c = corners.map(p => [p[0], p[1]]);
            const partner = [1, 0, 3, 2][index];
            const isTop = index < 2;
            const isLeft = index === 0 || index === 3;
            let x = Math.min(Math.max(point.x, 0), w);
            let y = Math.min(Math.max(point.y, 0), h);
            // Against BOTH corners of the other edge: a Q-drawn lane's edges are rarely horizontal.
            y = isTop ? Math.min(y, Math.min(c[2][1], c[3][1]) - MIN_PX) : Math.max(y, Math.max(c[0][1], c[1][1]) + MIN_PX);
            x = isLeft ? Math.min(x, c[partner][0] - MIN_PX) : Math.max(x, c[partner][0] + MIN_PX);
            c[index] = [Math.min(Math.max(x, 0), w), y];
            c[partner][1] = y;
            return c;
        }

        show(lane) {
            this._cancelDrag();  // a drag cut short by a new selection leaves nothing drawn that was not saved
            this._lane = lane;
            this._corners = GelAnalyzer.LaneGeometry.orderCorners(lane.polygon).map(p => [p[0], p[1]]);
            this._draw();
        }

        hide() {
            this._cancelDrag();
            this.handlesGroup.clear();
            this._handles = [];
            this._lane = null;
            this._corners = null;
        }

        /** Redraw for `lane` if it is the one shown (new scale, new corners); hide when it is gone or no longer
         *  fits. `lane` is the state's lane for the shown id, undefined once deleted. */
        refresh(lane) {
            if (!this._lane) return;
            if (!lane) {
                this.hide();
                return;
            }
            if (lane.id !== this._lane.id) return;
            if (this._drag) return;
            if (CornerHandles.fits(lane)) {
                this.show(lane);
            } else {
                this.hide();
            }
        }

        _draw() {
            this.handlesGroup.clear();
            const scale = this.viewport.getScale();
            const size = HANDLE_PX / (scale > 0 ? scale : 1);  // 0 before the first fit (a hidden viewer)
            this._handles = this._corners.map((p, index) => {
                const handle = this.handlesGroup.circle(size).center(p[0], p[1])
                    .addClass('gv-corner-handle').attr('data-corner', index);
                handle.node.addEventListener('pointerdown', (e) => this._startDrag(e, index));
                // The viewer's tools listen to mousedown: never let a press on a handle reach them.
                handle.node.addEventListener('mousedown', (e) => e.stopPropagation());
                return handle;
            });
        }

        _moveHandles() {
            this._handles.forEach((handle, i) => handle.center(this._corners[i][0], this._corners[i][1]));
        }

        _preview(corners) {
            this.renderer.updateLane({ ...this._lane, polygon: corners });
        }

        _startDrag(e, index) {
            if (e.button !== undefined && e.button !== 0) return;
            e.stopPropagation();
            e.preventDefault();
            const before = this._corners.map(p => [p[0], p[1]]);
            const onMove = (ev) => this._onMove(ev);
            const onUp = (ev) => this._onUp(ev);
            const onKey = (ev) => this._onKey(ev);
            const onCancel = () => this._cancelDrag();  // the system took the pointer: as Esc, nothing committed
            document.addEventListener('pointermove', onMove);
            document.addEventListener('pointerup', onUp);
            document.addEventListener('pointercancel', onCancel);
            window.addEventListener('keydown', onKey, true);
            this._drag = { index, before, moved: false, onMove, onUp, onKey, onCancel };
        }

        _onMove(e) {
            if (!this._drag) return;
            const point = this.viewport.getImagePoint(e);
            this._corners = CornerHandles.dragCorner(this._corners, this._drag.index, point,
                this.imageWidth, this.imageHeight);
            this._drag.moved = true;
            this._preview(this._corners);
            this._moveHandles();
        }

        _onUp() {
            if (!this._drag) return;
            const moved = this._drag.moved;
            this._endDrag();
            if (!moved) return;
            const G = GelAnalyzer.LaneGeometry;
            const polygon = G.clampRound(this._corners, this.imageWidth, this.imageHeight);
            const [x, y, width, height] = G.outerBox(polygon);
            this.onCommit(this._lane.id, { lane_shape: 'QUADRILATERAL', polygon, x, y, width, height });
        }

        _onKey(e) {
            if (!this._drag || e.key !== 'Escape') return;
            e.preventDefault();
            e.stopImmediatePropagation();
            this._cancelDrag();
            this._draw();  // at the current scale: a zoom may have come during the drag
        }

        /** Ends a drag without committing: the lane drawn as the state holds it, the corners back. */
        _cancelDrag() {
            if (!this._drag) return;
            this._corners = this._drag.before;
            this._endDrag();
            this.renderer.updateLane(this._lane);
            this._moveHandles();
        }

        _endDrag() {
            if (!this._drag) return;
            document.removeEventListener('pointermove', this._drag.onMove);
            document.removeEventListener('pointerup', this._drag.onUp);
            document.removeEventListener('pointercancel', this._drag.onCancel);
            window.removeEventListener('keydown', this._drag.onKey, true);
            this._drag = null;
        }
    }

    global.GelViewer = global.GelViewer || {};
    global.GelViewer.CornerHandles = CornerHandles;
})(window);
