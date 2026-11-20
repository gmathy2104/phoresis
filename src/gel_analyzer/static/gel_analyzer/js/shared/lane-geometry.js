/**
 * lane-geometry.js -- a lane's shape in the browser: services/lane_geometry/shape.py ported, one rule for every page
 * (spec docs/superpowers/specs/2026-10-10-gel-lane-tilt-design.md §4). Rule 2: a lane is read as its polygon when it
 * is not a RECTANGLE and has at least 3 points, else as its box. Boxes are [x, y, w, h], points [[x, y], ...], in
 * image pixels.
 *
 * Namespace: GelAnalyzer.LaneGeometry
 */
(function (global) {
    'use strict';

    function hasOutline(lane) {
        return !!lane && lane.lane_shape !== 'RECTANGLE' && Array.isArray(lane.polygon) && lane.polygon.length >= 3;
    }

    function boxCorners(x, y, w, h) {
        return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]];
    }

    /** Rule 2 on an editor lane ({lane_shape, polygon, x, y, width, height}). */
    function outline(lane) {
        if (hasOutline(lane)) return lane.polygon.map(p => [Number(p[0]), Number(p[1])]);
        return boxCorners(lane.x, lane.y, lane.width, lane.height);
    }

    /** A page payload's lane: the server's `outline` (Rule 2, computed in Python), else its `bbox` (older payloads). */
    function outlineOfPayload(lane) {
        if (lane && Array.isArray(lane.outline) && lane.outline.length >= 3) return lane.outline;
        const b = (lane && lane.bbox) || {};
        return boxCorners(b.x, b.y, b.width, b.height);
    }

    /** [lo, hi] of the polygon on row y (outer interval if non-convex); null off the polygon (shape.py::span_at). */
    function spanAt(points, y) {
        const xs = [];
        for (let i = 0; i < points.length; i++) {
            const [x0, y0] = points[i];
            const [x1, y1] = points[(i + 1) % points.length];
            if (y0 === y1) {
                if (y === y0) xs.push(x0, x1);
                continue;
            }
            if (Math.min(y0, y1) <= y && y <= Math.max(y0, y1)) xs.push(x0 + (y - y0) * (x1 - x0) / (y1 - y0));
        }
        return xs.length ? [Math.min(...xs), Math.max(...xs)] : null;
    }

    function pointInPolygon(x, y, points) {
        let inside = false;
        for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
            const [xi, yi] = points[i];
            const [xj, yj] = points[j];
            if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) inside = !inside;
        }
        return inside;
    }

    /** [x, y, w, h], floor of the minima and ceil of the maxima (shape.py::outer_bbox, Rule 1). */
    function outerBox(points) {
        const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
        const x0 = Math.floor(Math.min(...xs)), y0 = Math.floor(Math.min(...ys));
        return [x0, y0, Math.ceil(Math.max(...xs)) - x0, Math.ceil(Math.max(...ys)) - y0];
    }

    /** TL, TR, BR, BL by geometry: the two highest are the top, then by x (shape.py::order_corners). */
    function orderCorners(points) {
        const byY = [...points].sort((p, q) => (p[1] - q[1]) || (p[0] - q[0]));
        const top = byY.slice(0, 2).sort((p, q) => p[0] - q[0]);
        const bottom = byY.slice(2).sort((p, q) => p[0] - q[0]);
        return [top[0], top[1], bottom[1], bottom[0]];
    }

    /** Affine per axis from oldBox onto newBox (shape.py::map_polygon_to_box, D12). */
    function mapPolygonToBox(points, oldBox, newBox) {
        const [ox, oy, ow, oh] = oldBox;
        const [nx, ny, nw, nh] = newBox;
        const sx = ow ? nw / ow : 1;
        const sy = oh ? nh / oh : 1;
        return points.map(([x, y]) => [nx + (x - ox) * sx, ny + (y - oy) * sy]);
    }

    /** A 4-point lane's sides extended or cut as lines to yTop / yBottom; TL, TR, BR, BL (shape.py::extend_quad). */
    function extendQuad(points, yTop, yBottom) {
        const [tl, tr, br, bl] = orderCorners(points);
        const at = (a, b, y) => (b[1] === a[1] ? a[0] : a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]));
        return [[at(tl, bl, yTop), yTop], [at(tr, br, yTop), yTop], [at(tr, br, yBottom), yBottom],
            [at(tl, bl, yBottom), yBottom]];
    }

    /** TL, TR, BR, BL of the lane along its axis between two heights (shape.py::quad_from_axis). */
    function quadFromAxis(xRef, yRef, slope, width, yTop, yBottom) {
        const half = width / 2;
        const xTop = xRef + slope * (yTop - yRef);
        const xBottom = xRef + slope * (yBottom - yRef);
        return [[xTop - half, yTop], [xTop + half, yTop], [xBottom + half, yBottom], [xBottom - half, yBottom]];
    }

    /** The outline cut at two rows: a band's shape in its lane (the band model's rule, yolo_bands.py::_build). */
    function slice(points, yTop, yBottom) {
        const top = spanAt(points, yTop);
        const bottom = spanAt(points, yBottom);
        if (!top || !bottom) return null;
        return [[top[0], yTop], [top[1], yTop], [bottom[1], yBottom], [bottom[0], yBottom]];
    }

    /** Clamped to [0, w] x [0, h], then rounded: the last step before any write (spec §3). */
    function clampRound(points, w, h) {
        const c = (v, max) => Math.round(Math.min(Math.max(v, 0), Number.isFinite(max) ? max : Infinity));
        return points.map(([x, y]) => [c(x, w), c(y, h)]);
    }

    /** Four corners on two x and two y values: the outline is its own box (a rectangle, a Straight accept). As
     *  services/report/lane_crop.py::is_upright_box. */
    function isUprightBox(points) {
        return points.length === 4 && new Set(points.map(p => p[0])).size === 2
            && new Set(points.map(p => p[1])).size === 2;
    }

    /** Left end of the outline's top row: where a label goes (a rectangle's (x, y)). */
    function topLeft(points) {
        const y = Math.min(...points.map(p => p[1]));
        return [spanAt(points, y)[0], y];
    }

    /** Middle of the outline's bottom row: where a name under the lane goes. */
    function bottomCentre(points) {
        const y = Math.max(...points.map(p => p[1]));
        const [lo, hi] = spanAt(points, y);
        return [(lo + hi) / 2, y];
    }

    global.GelAnalyzer = global.GelAnalyzer || {};
    global.GelAnalyzer.LaneGeometry = {
        hasOutline, outline, outlineOfPayload, spanAt, pointInPolygon, outerBox, orderCorners, mapPolygonToBox,
        extendQuad, quadFromAxis, slice, clampRound, isUprightBox, topLeft, bottomCentre,
    };
})(typeof window !== 'undefined' ? window : globalThis);
