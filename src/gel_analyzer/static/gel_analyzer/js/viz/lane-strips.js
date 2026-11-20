/**
 * GelAnalyzer.Viz.LaneStrips — the lanes of several samples side by side, each cut from its own gel, on one
 * common kDa axis. Read-only. Spec: docs/superpowers/specs/2026-10-11-sample-comparison-design.md §3. Each strip
 * is fed by one entry of GET /api/samples/<pk>/gels/ (services/sample_gels.py):
 *
 *   var handle = GelAnalyzer.Viz.LaneStrips.mount(el, {
 *     strips: [{ key: '1871', color: '#38bdf8', label: '★ G057', entry: entry }],
 *     kind: 'SDS-PAGE', showProfiles: true, eventBus: bus,
 *   });
 *   handle.update({ showProfiles: false });   // or { strips: [...] }: new colours after a theme switch
 *   handle.destroy();
 *
 * The axis (§3.3) is log10(kDa), top = high MW. A strip's ticks (entry.mw_ticks: the band rows of the ladder
 * nearest its lane) are normalised first (_normalizeTicks); between two kept ticks the lane's image rows map
 * linearly onto the axis, so every ladder band lands on its kDa. The rows above the top tick and below the bottom
 * one keep the strip's mean scale and sit in hatched "above ladder" / "below ladder" bands; when those bands would
 * together take more than the axis's own height (one inconsistent ladder), the outside scale of each strip is
 * capped at one common value, found so that the bands fit in one axis height: a strip whose own scale is below the
 * cap keeps it, so a degenerate ladder compresses its own outside rows and not those of the consistent strips
 * beside it. The axis keeps at least half the plot and no lane row is clipped. A strip with fewer than 2 usable
 * ticks goes to the "No kDa calibration" group, aligned by its lane's top and bottom (§3.6).
 *
 * Drawing (§3.4): one <image> per URL in a <defs>, created once for the mount's life (a URL -> element map: the
 * image proxy answers no-cache, so nothing may re-create it); each segment of a strip (_segments) is a nested
 * <svg> whose viewBox is the segment's rows over the outline's outer box, holding a <use> of that image clipped by
 * the lane's outline -- one clipPath per strip. A lane is read by its outline (Rule 2, gel_analyzer/CLAUDE.md):
 * LaneGeometry.outlineOfPayload / outerBox (shared/lane-geometry.js, loaded first; never modified here).
 * The readouts and the lane / gel links are HTML under the SVG, never inside it. Hovering a strip emits
 * 'sample:highlight' {key} on cfg.eventBus, and the panel follows the same event. Colours are --ga-lst-* custom
 * properties (css/lane-strips.css): .ga-viz-root resets `color` under all: initial. render() redraws everything
 * but the images, on update(), on a change of width and on `dsh:themechange`.
 */
(function (global) {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var Viz = global.GelAnalyzer && global.GelAnalyzer.Viz;
  var LaneGeometry = global.GelAnalyzer && global.GelAnalyzer.LaneGeometry;
  if (!Viz || !Viz.Panel || !Viz.mount || !LaneGeometry) return;

  // The standard ladder values: the only axis labels (§3.3), dropped when two would collide.
  var LADDER = [250, 150, 100, 75, 50, 37, 25, 20, 15, 10];
  var HEAD_H = 26;          // colour bar + label above the strips
  var GUTTER = 38;          // the kDa labels, left of the first strip
  var LABEL_GAP = 11;       // px between two axis labels, at least
  // Text extents for the band names: a 9px band label reaches BAND_UP above its baseline and BAND_DOWN below (css
  // .ga-lst-band-label); an axis label (10px, baseline 3.5 under its tick) reaches TICK_UP above its tick's y and
  // TICK_DOWN below (measured on a 768 px tile: 272-285 around a tick at 277.5); LABEL_CLEAR px at least between a
  // band name and an axis label.
  var BAND_UP = 8.6;
  var BAND_DOWN = 2.7;
  var TICK_UP = 6;
  var TICK_DOWN = 6.5;
  var LABEL_CLEAR = 1;
  var MAX_COL = 72;         // a strip is never wider than this
  var COMPACT_COL = 56;     // narrower: a strip's notes go to the list under the strips
  var NARROW = 480;         // narrower: the profile panel moves under the strips (§3.4)
  var BODY_GAP = 16;        // between the calibrated strips and the uncalibrated group (css: .ga-lst-body gap)
  var SEAM = 0.5;           // output px each segment overlaps its neighbours, against hairline seams (§3.4)
  var UNCAL_COL = 34;       // a strip of the uncalibrated group
  var UNCAL_PROFILE = 34;   // and its own small profile beside it (§3.6)
  var UNCAL_PAD = 13;       // the group's left padding + border, beside the strips (css: .ga-lst-uncal)
  var uid = 0;

  function svgEl(tag, attrs, parent) {
    var node = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (parent) parent.appendChild(node);
    return node;
  }

  // Text through textContent only: every name here comes from the server.
  function htmlEl(tag, className, parent, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    if (parent) parent.appendChild(node);
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function finite(value) {
    return value !== null && value !== undefined && value !== '' && typeof value !== 'boolean' && Number.isFinite(Number(value));
  }

  function clamp(value, lo, hi) {
    return Math.min(Math.max(value, lo), hi);
  }

  function fmt(value, decimals) {
    return Number(value).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  }

  // A molecular weight as part 1's gel tile prints it (sd-gel-tile.js): no decimal from 100 kDa, else one, so a POI
  // mark reads "POI · 50.0 kDa" and the SVG's aria-label "250 to 10.0 kDa".
  function formatKda(value) {
    var v = Number(value);
    return fmt(v, v >= 100 ? 0 : 1);
  }

  // An axis label: a whole number stays an integer ("10", "50", like the standard ladder values), a value between
  // two standard values (the ends of a short ladder's range) takes formatKda's decimal.
  function axisKda(value) {
    var v = Number(value);
    return Math.abs(Math.round(v * 10) / 10 - Math.round(v)) < 1e-9 ? fmt(v, 0) : formatKda(v);
  }

  function pointsAttr(points) {
    return points.map(function (p) { return p[0] + ',' + p[1]; }).join(' ');
  }

  function hasProfile(g) {
    var p = g.entry.profile;
    return !!(p && Array.isArray(p.y) && p.y.length && Array.isArray(p.intensity));
  }

  // §3.6: the uncalibrated strips carry their own small profile when Profiles is on and one of them has a profile;
  // a card is the strip, plus that profile. One rule for the layout (render) and the drawing (_drawUncal).
  function uncalProfiles(options, uncals) {
    return options.showProfiles !== false && uncals.some(hasProfile);
  }

  function uncalCardWidth(withProfiles) {
    return UNCAL_COL + (withProfiles ? 4 + UNCAL_PROFILE : 0);
  }

  /**
   * §3.3 tick normalisation, before any drawing. Ticks on one image row merge (both are dropped when their kDa
   * differ); then the longest SUBSEQUENCE, in row order, where the kDa strictly decreases as the row grows is kept:
   * a tick out of order (a mislabelled band) costs that tick alone, never the run of good ticks around it. Between
   * two equally long subsequences the one spanning the widest kDa range wins, then the one whose first tick has the
   * lowest y, then the first found: the choice depends on the ticks alone.
   * Returns {ticks: [{y, mw_kda}] top to bottom, reason}: reason is null, or why the strip has no usable
   * calibration ("no ladder calibration": under 2 ticks to start with; "ladder ticks out of order": fewer than 2
   * ticks left in order).
   */
  function normalizeTicks(ticks) {
    var valid = (Array.isArray(ticks) ? ticks : []).filter(function (t) {
      return t && finite(t.y) && finite(t.mw_kda) && Number(t.mw_kda) > 0;
    }).map(function (t) {
      return { y: Number(t.y), mw_kda: Number(t.mw_kda) };
    });
    if (valid.length < 2) return { ticks: [], reason: 'no ladder calibration' };
    valid.sort(function (a, b) { return a.y - b.y; });
    var rows = [];
    valid.forEach(function (t) {
      var last = rows[rows.length - 1];
      if (last && Math.round(last.y) === Math.round(t.y)) {
        if (last.mw_kda !== t.mw_kda) last.conflict = true;
        return;
      }
      rows.push({ y: t.y, mw_kda: t.mw_kda, conflict: false });
    });
    var kept = rows.filter(function (t) { return !t.conflict; });
    // len[j], first[j], prev[j]: the best strictly decreasing subsequence ENDING at kept[j] -- its length, the index
    // of its first tick, the tick before kept[j]. With the end fixed, the widest range is the highest first kDa.
    var len = [];
    var first = [];
    var prev = [];
    var better = function (aLen, aFirst, bLen, bFirst) {
      if (aLen !== bLen) return aLen > bLen;
      var a = kept[aFirst];
      var b = kept[bFirst];
      if (a.mw_kda !== b.mw_kda) return a.mw_kda > b.mw_kda;
      return a.y < b.y;
    };
    for (var j = 0; j < kept.length; j++) {
      len[j] = 1;
      first[j] = j;
      prev[j] = -1;
      for (var i = 0; i < j; i++) {
        if (!(kept[i].mw_kda > kept[j].mw_kda)) continue;
        if (better(len[i] + 1, first[i], len[j], first[j])) {
          len[j] = len[i] + 1;
          first[j] = first[i];
          prev[j] = i;
        }
      }
    }
    // The end: the longest, then the widest range (first kDa over last kDa), then the lowest first y, then the first.
    var end = -1;
    for (var k = 0; k < kept.length; k++) {
      if (end < 0 || len[k] > len[end]) {
        end = k;
        continue;
      }
      if (len[k] < len[end]) continue;
      var range = kept[first[k]].mw_kda / kept[k].mw_kda;
      var bestRange = kept[first[end]].mw_kda / kept[end].mw_kda;
      if (range > bestRange || (range === bestRange && kept[first[k]].y < kept[first[end]].y)) end = k;
    }
    if (end < 0 || len[end] < 2) return { ticks: [], reason: 'ladder ticks out of order' };
    var best = [];
    for (var at = end; at >= 0; at = prev[at]) best.unshift({ y: kept[at].y, mw_kda: kept[at].mw_kda });
    return { ticks: best, reason: null };
  }

  /**
   * The rows of a calibrated lane, cut at its kept ticks (§3.4), clamped to the outline's vertical extent
   * (LaneGeometry.outerBox): 'above' (over the top tick), one 'ladder' segment per pair of ticks (ty0/ty1 and
   * kda0/kda1: the pair, unclamped), 'below' (under the bottom tick). Empty segments are left out.
   */
  function segments(ticks, outline) {
    var box = LaneGeometry.outerBox(outline);
    var top = box[1];
    var bottom = box[1] + box[3];
    var out = [];
    if (!(bottom > top) || !ticks || ticks.length < 2) return out;
    var first = ticks[0];
    var last = ticks[ticks.length - 1];
    if (top < first.y) out.push({ kind: 'above', y0: top, y1: Math.min(first.y, bottom) });
    for (var i = 0; i + 1 < ticks.length; i++) {
      var a = ticks[i];
      var b = ticks[i + 1];
      out.push({ kind: 'ladder', y0: Math.max(a.y, top), y1: Math.min(b.y, bottom), ty0: a.y, ty1: b.y, kda0: a.mw_kda, kda1: b.mw_kda });
    }
    if (bottom > last.y) out.push({ kind: 'below', y0: Math.max(last.y, top), y1: bottom });
    return out.filter(function (s) { return s.y1 > s.y0; });
  }

  // One strip: its lane (the entry's own, by lane_id), outline, outer box, normalised ticks and segments.
  // `skip` names why it cannot be drawn: a self lane missing from entry.lanes never throws (§3.4).
  function stripGeometry(strip, index) {
    var entry = (strip && strip.entry) || {};
    var key = String(strip && strip.key != null ? strip.key : index);
    var g = {
      index: index,
      entry: entry,
      key: key,
      label: strip && strip.label != null ? String(strip.label) : key,
      color: (strip && strip.color) || '',
      // The host's own readout under the strip ({text, cls}; the gel comparison's), else readoutOf(entry).
      readout: strip && strip.readout && strip.readout.text != null ? strip.readout : null,
      skip: null,
    };
    var self = null;
    (Array.isArray(entry.lanes) ? entry.lanes : []).forEach(function (lane) {
      if (lane && lane.id === entry.lane_id) self = lane;
    });
    if (!self) {
      g.skip = 'lane not found on its gel';
      return g;
    }
    var points = LaneGeometry.outlineOfPayload(self);
    var usable = Array.isArray(points) && points.length >= 3 && points.every(function (p) {
      return p && finite(p[0]) && finite(p[1]);
    });
    var outline = usable ? points.map(function (p) { return [Number(p[0]), Number(p[1])]; }) : null;
    var box = outline ? LaneGeometry.outerBox(outline) : null;
    if (!box || !(box[2] > 0) || !(box[3] > 0)) {
      g.skip = 'lane outline unusable';
      return g;
    }
    var norm = normalizeTicks(entry.mw_ticks);
    g.outline = outline;
    g.box = box;
    g.top = box[1];
    g.bottom = box[1] + box[3];
    g.ticks = norm.ticks;
    g.reason = norm.reason;
    g.segs = norm.reason ? [{ kind: 'lane', y0: g.top, y1: g.bottom }] : segments(norm.ticks, outline);
    return g;
  }

  /**
   * The common axis over the calibrated strips (§3.3): kTop / kBot = the union of their calibrated ranges, unit(k)
   * = 0 at kTop and 1 at kBot (log10). Each strip gets `mean`, its mean scale in axis units per image row, and
   * `outScale`, the scale of its rows outside the ladder: its mean, or `cap` when that is smaller. above / below =
   * the room the tallest outside part needs beyond the calibrated range, in the same units (§3.3: each band as tall
   * as the tallest strip's outside part). One inconsistent ladder (ticks a few rows apart over a wide kDa range) has
   * a huge mean and would leave the shared axis a few pixels tall (253 -> 12 px measured): when above + below exceed
   * one axis height, `cap` (the largest scale, by bisection, at which they fit exactly) bounds the outside scale of
   * every strip. A strip whose mean is below the cap keeps its own scale out of the ladder (§3.3: each strip keeps
   * its own pixel scale there), so the degenerate ladder compresses its own rows only. Compressed, never clipped:
   * an aggregate above the ladder stays visible.
   */
  function buildAxis(cals) {
    var kTop = -Infinity;
    var kBot = Infinity;
    cals.forEach(function (g) {
      kTop = Math.max(kTop, g.ticks[0].mw_kda);
      kBot = Math.min(kBot, g.ticks[g.ticks.length - 1].mw_kda);
    });
    var lTop = Math.log10(kTop);
    var span = lTop - Math.log10(kBot);
    var unit = function (k) { return (lTop - Math.log10(k)) / span; };
    cals.forEach(function (g) {
      var t0 = g.ticks[0];
      var tn = g.ticks[g.ticks.length - 1];
      g.mean = (unit(tn.mw_kda) - unit(t0.mw_kda)) / (tn.y - t0.y);
    });
    // above / below with each strip's outside rows at its own scale, `cap` at most: non-decreasing in cap; 0 at 0
    // (unit(t0) >= 0 and unit(tn) <= 1: kTop / kBot are the union of the strips' ranges).
    var room = function (cap) {
      var above = 0;
      var below = 0;
      cals.forEach(function (g) {
        var t0 = g.ticks[0];
        var tn = g.ticks[g.ticks.length - 1];
        var scale = Math.min(g.mean, cap);
        above = Math.max(above, Math.max(0, t0.y - g.top) * scale - unit(t0.mw_kda));
        below = Math.max(below, unit(tn.mw_kda) + Math.max(0, g.bottom - tn.y) * scale - 1);
      });
      return { above: above, below: below };
    };
    var widest = cals.reduce(function (m, g) { return Math.max(m, g.mean); }, 0);
    var cap = widest;
    var out = room(cap);
    if (!(out.above + out.below <= 1)) {
      // The largest cap whose bands fit in one axis height, by bisection (room is monotone; 50 halvings of
      // [0, widest mean]).
      var lo = 0;
      var hi = widest;
      for (var n = 0; n < 50; n++) {
        var mid = (lo + hi) / 2;
        var r = room(mid);
        if (r.above + r.below <= 1) lo = mid;
        else hi = mid;
      }
      cap = lo;
      out = room(lo);
    }
    cals.forEach(function (g) { g.outScale = Math.min(g.mean, cap); });
    return { kTop: kTop, kBot: kBot, unit: unit, above: out.above, below: out.below, cap: cap, capped: cap < widest };
  }

  // Image row -> output row of a calibrated strip: piecewise linear between its ticks, its outside scale (its mean,
  // capped when a degenerate ladder would crush the axis: buildAxis) above and below them; null off the lane's rows.
  function calibratedMap(g, Y, Hk) {
    var ticks = g.ticks;
    var t0 = ticks[0];
    var tn = ticks[ticks.length - 1];
    var scale = g.outScale * Hk;
    return function (y) {
      if (!(y >= g.top && y <= g.bottom)) return null;
      if (y <= t0.y) return Y(t0.mw_kda) - (t0.y - y) * scale;
      if (y >= tn.y) return Y(tn.mw_kda) + (y - tn.y) * scale;
      for (var i = 0; i + 1 < ticks.length; i++) {
        var a = ticks[i];
        var b = ticks[i + 1];
        if (y <= b.y) return Y(a.mw_kda) + (y - a.y) * (Y(b.mw_kda) - Y(a.mw_kda)) / (b.y - a.y);
      }
      return null;
    };
  }

  // The standard ladder values inside the range, top to bottom, a label dropped when it would collide with the
  // one above. A range between two standard values (a short ladder) is labelled by its two ends instead.
  function axisLabels(f) {
    var out = [];
    var lastY = -Infinity;
    LADDER.forEach(function (k) {
      if (k > f.kTop * 1.0001 || k < f.kBot * 0.9999) return;
      var y = f.Y(k);
      if (y - lastY < LABEL_GAP) return;
      out.push({ y: y, text: String(k) });
      lastY = y;
    });
    if (!out.length) {
      out.push({ y: f.Y(f.kTop), text: axisKda(f.kTop) });
      if (f.Y(f.kBot) - f.Y(f.kTop) >= LABEL_GAP) out.push({ y: f.Y(f.kBot), text: axisKda(f.kBot) });
    }
    return out;
  }

  // A hatched band of rows with no kDa (§3.3), across x0..x1. Its name goes in the gutter, where the axis labels are:
  // `avoid` = their [top, bottom] extents. Two lines ("above" / "ladder") centred when they fit inside the band clear
  // of every axis label, else the first word on one line (centred, else flush with the band's top, else its bottom),
  // else nothing (the hatching and its tooltip remain).
  function band(svg, f, x0, x1, y0, y1, words, tip, avoid) {
    if (!(y1 - y0 > 0.5)) return;
    if (!(x1 - x0 > 0)) return;   // a very narrow tile: never a rect of negative width
    var group = svgEl('g', { class: 'ga-lst-band' }, svg);
    svgEl('title', {}, group).textContent = tip;
    svgEl('rect', { x: x0, y: y0, width: x1 - x0, height: y1 - y0, class: 'ga-lst-band-bg' }, group);
    var hatch = svgEl('rect', { x: x0, y: y0, width: x1 - x0, height: y1 - y0 }, group);
    hatch.style.fill = 'url(#' + f.hatch + ')';
    var mid = (y0 + y1) / 2;
    var clear = function (top, bottom) {
      return top >= y0 - 1e-6 && bottom <= y1 + 1e-6 && avoid.every(function (e) {
        return bottom + LABEL_CLEAR <= e[0] || top - LABEL_CLEAR >= e[1];
      });
    };
    if (clear(mid - 2 - BAND_UP, mid + 8 + BAND_DOWN)) {
      var text = svgEl('text', { x: GUTTER - 6, y: mid - 2, 'text-anchor': 'end', class: 'ga-lst-band-label' }, group);
      svgEl('tspan', { x: GUTTER - 6 }, text).textContent = words[0];
      svgEl('tspan', { x: GUTTER - 6, dy: 10 }, text).textContent = words[1];
      return;
    }
    // One line: the baselines tried are the band's middle, then the band's top and bottom edges.
    var baselines = [mid + 3, y0 + BAND_UP, y1 - BAND_DOWN];
    for (var i = 0; i < baselines.length; i++) {
      if (!clear(baselines[i] - BAND_UP, baselines[i] + BAND_DOWN)) continue;
      var one = svgEl('text', { x: GUTTER - 6, y: baselines[i], 'text-anchor': 'end', class: 'ga-lst-band-label' }, group);
      one.textContent = words[0];
      return;
    }
  }

  // The gutter (kDa title, labels and ticks) and the out-of-ladder bands across x0..x1.
  function drawFrame(svg, f, x0, x1) {
    var title = svgEl('text', { x: GUTTER - 6, y: HEAD_H - 7, 'text-anchor': 'end', class: 'ga-lst-axis-title' }, svg);
    title.textContent = 'kDa';
    var labels = axisLabels(f);
    var avoid = labels.map(function (label) { return [label.y - TICK_UP, label.y + TICK_DOWN]; });
    band(svg, f, x0, x1, f.plotTop, f.axisTop, ['above', 'ladder'], 'Lane rows above the top ladder band: no kDa', avoid);
    band(svg, f, x0, x1, f.axisBot, f.plotBot, ['below', 'ladder'], 'Lane rows below the bottom ladder band: no kDa', avoid);
    labels.forEach(function (label) {
      svgEl('line', { x1: GUTTER - 4, x2: GUTTER - 1, y1: label.y, y2: label.y, class: 'ga-lst-tick' }, svg);
      var text = svgEl('text', { x: GUTTER - 6, y: label.y + 3.5, 'text-anchor': 'end', class: 'ga-lst-axis' }, svg);
      text.textContent = label.text;
    });
  }

  // The colour bar and the label above a strip.
  function head(parent, g, x, w) {
    var bar = svgEl('rect', { x: x, y: 2, width: w, height: 4, rx: 2, class: 'ga-lst-bar' }, parent);
    bar.style.fill = g.color;
    var text = svgEl('text', { x: x + w / 2, y: 19, 'text-anchor': 'middle', class: 'ga-lst-label' }, parent);
    text.style.fill = g.color;
    var room = Math.max(2, Math.floor(w / 6.2));
    text.textContent = g.label.length > room ? g.label.slice(0, room - 1) + '…' : g.label;
    svgEl('title', {}, text).textContent = g.label;
  }

  // One segment: a nested <svg> whose viewBox is the segment's rows over the outline's outer box, so the viewBox
  // applies the segment's scale and the viewport cuts its rows (§3.4). It overlaps its neighbours by SEAM output
  // px, the same overlap in image rows at the segment's own scale. Never a NaN in a viewBox: such a segment is
  // left out.
  function drawSegment(parent, g, seg, map, x, w, imageId, clipId) {
    var y0 = map(seg.y0);
    var y1 = map(seg.y1);
    if (y0 == null || y1 == null || !(y1 > y0) || !(w > 0)) return;
    var pad = SEAM / ((y1 - y0) / (seg.y1 - seg.y0));
    var viewBox = [g.box[0], seg.y0 - pad, g.box[2], seg.y1 - seg.y0 + 2 * pad];
    var port = [x, y0 - SEAM, w, y1 - y0 + 2 * SEAM];
    if (!viewBox.concat(port).every(Number.isFinite)) return;
    var nested = svgEl('svg', {
      x: port[0], y: port[1], width: port[2], height: port[3], viewBox: viewBox.join(' '), preserveAspectRatio: 'none', class: 'ga-lst-seg',
    }, parent);
    svgEl('use', { href: '#' + imageId, 'clip-path': 'url(#' + clipId + ')' }, nested);
  }

  // A strip's line on the profile panel: y through the strip's own map (out-of-ladder rows included), x the
  // intensity over the profile's maximum within the drawn rows (§3.5). A point off the map, or a gap in y (a
  // polygon lane's profile skips rows), breaks the line.
  function profilePath(profile, map, x0, w) {
    if (!profile || !Array.isArray(profile.y) || !Array.isArray(profile.intensity)) return '';
    var ys = profile.y;
    var vs = profile.intensity;
    var n = Math.min(ys.length, vs.length);
    var max = 0;
    var i;
    for (i = 0; i < n; i++) {
      if (finite(ys[i]) && finite(vs[i]) && map(Number(ys[i])) != null) max = Math.max(max, Number(vs[i]));
    }
    if (!(max > 0)) return '';
    var steps = [];
    for (i = 1; i < n; i++) {
      var step = Math.abs(Number(ys[i]) - Number(ys[i - 1]));
      if (step > 0) steps.push(step);
    }
    steps.sort(function (a, b) { return a - b; });
    var limit = Math.max(1.5, 2.5 * (steps.length ? steps[Math.floor(steps.length / 2)] : 1));
    var d = [];
    var prev = null;
    for (i = 0; i < n; i++) {
      var y = finite(ys[i]) ? Number(ys[i]) : null;
      var out = y != null && finite(vs[i]) ? map(y) : null;
      if (out == null) {
        prev = null;
        continue;
      }
      var x = x0 + clamp(Number(vs[i]) / max, 0, 1) * w;
      d.push((prev != null && Math.abs(y - prev) <= limit ? 'L' : 'M') + x.toFixed(1) + ',' + out.toFixed(1));
      prev = y;
    }
    return d.join(' ');
  }

  // The profile panel: one line per strip in its colour, on the strips' axis (grid lines at the axis labels).
  function drawProfiles(svg, gs, x0, w, f) {
    axisLabels(f).forEach(function (label) {
      svgEl('line', { x1: x0, x2: x0 + w, y1: label.y, y2: label.y, class: 'ga-lst-grid' }, svg);
    });
    svgEl('line', { x1: x0, x2: x0, y1: f.plotTop, y2: f.plotBot, class: 'ga-lst-tick' }, svg);
    var caption = svgEl('text', { x: x0 + w / 2, y: HEAD_H - 7, 'text-anchor': 'middle', class: 'ga-lst-axis-title' }, svg);
    caption.textContent = 'lane profiles';
    gs.forEach(function (g) {
      var d = profilePath(g.entry.profile, g.map, x0 + 1, w - 4);
      if (!d) return;
      var path = svgEl('path', { d: d, class: 'ga-lst-profile', 'data-key': g.key }, svg);
      path.style.stroke = g.color;
    });
  }

  // What the lane reads (§3.4, as in the mockup): its purity, else the state of the readout it feeds.
  function readoutOf(entry) {
    var state = entry.readout && entry.readout.state;
    if (entry.measures_purity && finite(entry.purity)) {
      return { text: fmt(entry.purity, 1) + ' %', cls: state === 'published' ? '' : 'is-muted' };
    }
    if (state === 'published') return { text: 'published', cls: '' };
    if (state === 'pending') return { text: 'pending', cls: 'is-pending' };
    if (state === 'elsewhere') return { text: 'elsewhere', cls: 'is-muted' };
    return { text: entry.measures_purity ? '—' : 'no readout', cls: 'is-muted' };
  }

  // §3.2: the strip drawn is not the one the matrix value comes from (the sample's official row sits on another
  // lane or source). A lane still pending or with no readout has no matrix value to point elsewhere.
  function sourceNote(entry) {
    if (!entry.readout || entry.readout.state !== 'elsewhere') return '';
    var gel = (entry.analysis && entry.analysis.name) || 'its gel';
    return 'matrix value from another source; showing L' + entry.lane_number + ' of ' + gel;
  }

  // Under a strip: the readout, then "L<n> · <gel>", a link to the analysis in Gel Analyzer, then its notes.
  // Compact (a narrow column): the link shows "L<n>" only and the notes go to the list under the strips.
  function foot(parent, g, compact, notes, keyed, extra) {
    var box = htmlEl('div', 'ga-lst-foot', parent);
    if (keyed) box.setAttribute('data-key', g.key);
    var readout = g.readout || readoutOf(g.entry);
    htmlEl('div', 'ga-lst-readout' + (readout.cls ? ' ' + readout.cls : ''), box, readout.text);
    var analysis = g.entry.analysis || {};
    var lane = 'L' + (g.entry.lane_number != null ? g.entry.lane_number : '?');
    var gel = analysis.name || 'gel';
    var link = htmlEl(analysis.url ? 'a' : 'span', 'ga-lst-link', box, compact ? lane : lane + ' · ' + gel);
    if (analysis.url) {
      link.setAttribute('href', analysis.url);
      link.setAttribute('title', lane + ' · ' + gel + ' — open in Gel Analyzer');
    }
    [extra, sourceNote(g.entry)].forEach(function (line) {
      if (!line) return;
      if (compact) notes.push({ key: g.key, text: g.label + ': ' + line, error: false });
      else htmlEl('div', 'ga-lst-foot-note', box, line);
    });
  }

  class LaneStripsPanel extends Viz.Panel {
    init() {
      var c = this.container;
      this._uid = 'ga-lst-' + (++uid);
      this._images = new Map();   // image URL -> {id, node, state}: for the mount's life (the proxy is no-cache)
      this._keys = new Set();
      this._hl = null;
      this._hover = null;
      this._width = -1;
      this._destroyed = false;
      c.setAttribute('role', 'group');
      // Images, clip paths and the hatch live in a 0 x 0 SVG every drawn SVG references (not display:none, which
      // would stop the paint servers from rendering).
      var defs = svgEl('svg', { class: 'ga-lst-defs', width: 0, height: 0, 'aria-hidden': 'true' }, c);
      this._imageDefs = svgEl('defs', {}, defs);
      this._drawDefs = svgEl('defs', {}, defs);
      this._body = htmlEl('div', 'ga-lst-body', c);

      this._on('sample:highlight', (detail) => {
        this._hl = detail && detail.key != null ? String(detail.key) : null;
        this._applyHighlight();
      });
      var hover = (event) => {
        var hit = event.target && event.target.closest ? event.target.closest('[data-key]') : null;
        var key = hit && c.contains(hit) ? hit.getAttribute('data-key') : null;
        if (key === this._hover) return;
        this._hover = key;
        this.eventBus.emit('sample:highlight', { key: key });
      };
      var leave = (event) => {
        if (event.relatedTarget && c.contains(event.relatedTarget)) return;
        if (this._hover === null) return;
        this._hover = null;
        this.eventBus.emit('sample:highlight', { key: null });
      };
      c.addEventListener('mouseover', hover);
      c.addEventListener('focusin', hover);
      c.addEventListener('mouseleave', leave);
      c.addEventListener('focusout', leave);
      this._disposers.push(() => {
        c.removeEventListener('mouseover', hover);
        c.removeEventListener('focusin', hover);
        c.removeEventListener('mouseleave', leave);
        c.removeEventListener('focusout', leave);
      });

      // A width change redraws (a tile drawn while hidden draws when shown); a height change does not.
      var frame = 0;
      this._observe(c, () => {
        if (frame) cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
          frame = 0;
          if (c.clientWidth !== this._width) this.render();
        });
      });
      var themeTimer = 0;
      this._onWindow('dsh:themechange', () => {
        clearTimeout(themeTimer);
        themeTimer = setTimeout(() => { themeTimer = 0; this.render(); }, 0);
      });
      this._disposers.push(() => {
        if (frame) cancelAnimationFrame(frame);
        clearTimeout(themeTimer);
      });
    }

    destroy() {
      this._destroyed = true;
      super.destroy();
    }

    // The <image> of a URL, created once and kept for the mount's life; null without a URL or a known size
    // (lane coordinates are display-file pixels: a photo of unknown size would put the outline beside the lane).
    _imageFor(entry) {
      var image = entry && entry.image;
      if (!image || !image.url || !(Number(image.width) > 0) || !(Number(image.height) > 0)) return null;
      var rec = this._images.get(image.url);
      if (rec) return rec;
      var node = document.createElementNS(NS, 'image');
      rec = { id: this._uid + '-img-' + this._images.size, node: node, state: 'loading' };
      node.addEventListener('load', () => { rec.state = 'loaded'; });
      node.addEventListener('error', () => {
        rec.state = 'failed';
        if (!this._destroyed) this.render();
      });
      [['id', rec.id], ['x', 0], ['y', 0], ['width', Number(image.width)], ['height', Number(image.height)],
        ['preserveAspectRatio', 'none'], ['href', image.url]].forEach(function (pair) { node.setAttribute(pair[0], pair[1]); });
      this._imageDefs.appendChild(node);
      this._images.set(image.url, rec);
      return rec;
    }

    _applyHighlight() {
      var key = this._hl;
      var on = key != null && this._keys.has(key);
      this.container.classList.toggle('has-hl', on);
      var nodes = this.container.querySelectorAll('[data-key]');
      for (var i = 0; i < nodes.length; i++) nodes[i].classList.toggle('is-hl', on && nodes[i].getAttribute('data-key') === key);
    }

    // A strip in its column: slab, the image segments clipped by the outline, the hatch over its rows outside the
    // ladder, its POI marks. The slab says "no image" without a photo (§3.4); the profile is still drawn.
    _drawStrip(parent, g, x, w, map, headW, keyed) {
      var group = svgEl('g', { class: 'ga-lst-strip' }, parent);
      if (keyed) group.setAttribute('data-key', g.key);
      head(group, g, x, headW);
      var y0 = map(g.top);
      var y1 = map(g.bottom);
      if (y0 == null || y1 == null || !(y1 > y0)) return;
      svgEl('rect', { x: x, y: y0, width: w, height: y1 - y0, class: 'ga-lst-slab' }, group);
      var rec = g.image;
      if (!rec || rec.state !== 'loaded') {
        var cx = x + w / 2;
        var cy = (y0 + y1) / 2;
        var note = svgEl('text', { x: cx, y: cy + 3, 'text-anchor': 'middle', transform: 'rotate(-90 ' + cx + ' ' + cy + ')', class: 'ga-lst-slab-note' }, group);
        note.textContent = rec && rec.state === 'loading' ? 'loading…' : 'no image';
      }
      if (rec && rec.state !== 'failed') {
        var clipId = this._uid + '-clip-' + g.index;
        var clip = svgEl('clipPath', { id: clipId, clipPathUnits: 'userSpaceOnUse' }, this._drawDefs);
        svgEl('polygon', { points: pointsAttr(g.outline) }, clip);
        g.segs.forEach(function (seg) { drawSegment(group, g, seg, map, x, w, rec.id, clipId); });
      }
      var hatchId = this._uid + '-hatch';
      g.segs.forEach(function (seg) {
        if (seg.kind !== 'above' && seg.kind !== 'below') return;
        var a = map(seg.y0);
        var b = map(seg.y1);
        if (a == null || b == null || !(b > a)) return;
        var rect = svgEl('rect', { x: x, y: a, width: w, height: b - a, class: 'ga-lst-out' }, group);
        rect.style.fill = 'url(#' + hatchId + ')';
      });
      // A POI band: a thin mark at its own row, through the strip's map, so it sits on the band in the picture;
      // its tooltip gives Gel Analyzer's value (§3.4).
      (Array.isArray(g.entry.bands) ? g.entry.bands : []).forEach(function (bandRow) {
        if (!bandRow || bandRow.band_type !== 'POI' || !finite(bandRow.position_y)) return;
        var y = map(Number(bandRow.position_y));
        if (y == null) return;
        var mark = svgEl('g', { class: 'ga-lst-poi' }, group);
        svgEl('title', {}, mark).textContent = 'POI' + (finite(bandRow.estimated_mw_kda) ? ' · ' + formatKda(bandRow.estimated_mw_kda) + ' kDa' : '');
        svgEl('line', { x1: x - 4, x2: x + 1.5, y1: y, y2: y }, mark);
        svgEl('line', { x1: x + w - 1.5, x2: x + w + 4, y1: y, y2: y }, mark);
        svgEl('line', { x1: x, x2: x + w, y1: y, y2: y, class: 'ga-lst-poi-hit' }, mark);
      });
    }

    // The calibrated strips on the common axis, the profile panel beside them (or under them, narrow), the feet.
    _drawMain(cals, width, Hp, notes) {
      var showProfiles = this.options.showProfiles !== false && cals.some(hasProfile);
      var narrow = width < NARROW;
      var sideProfile = showProfiles && !narrow;
      var n = cals.length;
      var profileW = sideProfile ? clamp(Math.round(width * 0.26), 90, 220) : 0;
      var area = width - GUTTER - 4 - (sideProfile ? profileW + 14 : 0);
      var gap = n > 1 ? clamp(area * 0.03, 6, 12) : 0;
      var colW = Math.max(8, Math.min(MAX_COL, (area - gap * (n - 1)) / n));
      var compact = colW < COMPACT_COL;
      var axis = buildAxis(cals);
      var Hk = Hp / (1 + axis.above + axis.below);
      var axisTop = HEAD_H + axis.above * Hk;
      var Y = function (k) { return axisTop + axis.unit(k) * Hk; };
      var f = {
        plotTop: HEAD_H, plotBot: HEAD_H + Hp, axisTop: axisTop, axisBot: axisTop + Hk, Y: Y,
        kTop: axis.kTop, kBot: axis.kBot, hatch: this._uid + '-hatch',
      };
      var colX = function (i) { return GUTTER + i * (colW + gap); };
      var colsRight = colX(n - 1) + colW;
      var svgH = HEAD_H + Hp + 2;
      var main = htmlEl('div', 'ga-lst-main', this._body);
      main.style.width = width + 'px';
      var svg = svgEl('svg', {
        class: 'ga-lst-svg', width: width, height: svgH, viewBox: '0 0 ' + width + ' ' + svgH, role: 'img',
        'aria-label': 'Lanes aligned on molecular weight, ' + formatKda(axis.kTop) + ' to ' + formatKda(axis.kBot) + ' kDa',
      }, main);
      drawFrame(svg, f, GUTTER, sideProfile ? colsRight + 14 + profileW : colsRight);
      cals.forEach((g, i) => {
        g.map = calibratedMap(g, Y, Hk);
        this._drawStrip(svg, g, colX(i), colW, g.map, colW, true);
      });
      if (sideProfile) drawProfiles(svg, cals, colsRight + 14, profileW, f);
      var feet = htmlEl('div', 'ga-lst-feet', main);
      feet.style.paddingLeft = GUTTER + 'px';
      feet.style.gridTemplateColumns = 'repeat(' + n + ', ' + colW + 'px)';
      feet.style.columnGap = gap + 'px';
      cals.forEach(function (g) { foot(feet, g, compact, notes, true, ''); });
      if (showProfiles && narrow) {
        var below = svgEl('svg', {
          class: 'ga-lst-svg ga-lst-svg--profiles', width: width, height: svgH, viewBox: '0 0 ' + width + ' ' + svgH,
          role: 'img', 'aria-label': 'Lane profiles on the same kDa axis',
        }, main);
        drawFrame(below, f, GUTTER, width - 4);
        drawProfiles(below, cals, GUTTER, width - GUTTER - 4, f);
      }
    }

    // §3.6: each strip from its outline's top to its bottom, scaled to the plot height, its own profile beside it.
    _drawUncal(uncals, width, Hp, stacked, alone, notes) {
      var group = htmlEl('div', 'ga-lst-uncal' + (stacked ? ' is-stacked' : ''), this._body);
      group.style.width = width + 'px';
      htmlEl('div', 'ga-lst-uncal-title', group, 'No kDa calibration — aligned by lane top/bottom');
      if (alone) htmlEl('div', 'ga-lst-uncal-note', group, 'None of these lanes has a usable ladder calibration: there is no kDa axis.');
      var showProfiles = uncalProfiles(this.options, uncals);
      var cardW = uncalCardWidth(showProfiles);
      var compact = cardW < COMPACT_COL;
      var cards = htmlEl('div', 'ga-lst-cards', group);
      var svgH = HEAD_H + Hp + 2;
      uncals.forEach((g) => {
        var card = htmlEl('div', 'ga-lst-card', cards);
        card.setAttribute('data-key', g.key);
        card.style.width = cardW + 'px';
        var svg = svgEl('svg', {
          class: 'ga-lst-svg', width: cardW, height: svgH, viewBox: '0 0 ' + cardW + ' ' + svgH, role: 'img',
          'aria-label': g.label + ': lane without kDa calibration',
        }, card);
        g.map = function (y) {
          return y >= g.top && y <= g.bottom ? HEAD_H + (y - g.top) / (g.bottom - g.top) * Hp : null;
        };
        this._drawStrip(svg, g, 0, UNCAL_COL, g.map, cardW, false);
        if (showProfiles) {
          var x0 = UNCAL_COL + 4;
          svgEl('line', { x1: x0, x2: x0, y1: HEAD_H, y2: HEAD_H + Hp, class: 'ga-lst-tick' }, svg);
          var d = profilePath(g.entry.profile, g.map, x0 + 1, UNCAL_PROFILE - 3);
          if (d) svgEl('path', { d: d, class: 'ga-lst-profile' }, svg).style.stroke = g.color;
        }
        foot(card, g, compact, notes, false, g.reason);
      });
    }

    render() {
      if (this._destroyed) return;
      var c = this.container;
      var width = c.clientWidth;
      var o = this.options;
      var strips = Array.isArray(o.strips) ? o.strips : [];
      this._width = width;
      clear(this._drawDefs);
      clear(this._body);
      this._keys = new Set();
      c.setAttribute('aria-label', 'Gel lanes of ' + strips.length + (strips.length === 1 ? ' sample' : ' samples') +
        (o.kind ? ' · ' + o.kind : '') + ', side by side');
      if (!width || !strips.length) return;   // hidden: drawn when the observer sees a width

      var notes = [];
      var geoms = [];
      strips.forEach((strip, i) => {
        var g = stripGeometry(strip, i);
        if (g.skip) {
          notes.push({ key: g.key, text: g.label + ': ' + g.skip, error: true });
          return;
        }
        g.image = this._imageFor(g.entry);
        if (g.image && g.image.state === 'failed') notes.push({ key: g.key, text: g.label + ': image could not be loaded', error: true });
        this._keys.add(g.key);
        geoms.push(g);
      });
      var cals = geoms.filter(function (g) { return !g.reason; });
      var uncals = geoms.filter(function (g) { return g.reason; });
      if (geoms.length) {
        var pattern = svgEl('pattern', {
          id: this._uid + '-hatch', patternUnits: 'userSpaceOnUse', width: 6, height: 6, patternTransform: 'rotate(45)',
        }, this._drawDefs);
        svgEl('line', { x1: 0, y1: 0, x2: 0, y2: 6, class: 'ga-lst-hatch' }, pattern);
        var cardW = uncalCardWidth(uncalProfiles(o, uncals));
        var groupW = Math.max(170, UNCAL_PAD + uncals.length * cardW + (uncals.length - 1) * 10);
        var side = cals.length && uncals.length && width - groupW - BODY_GAP >= NARROW;
        var mainW = side ? width - groupW - BODY_GAP : width;
        var Hp = mainW >= NARROW ? 300 : 260;
        if (cals.length) this._drawMain(cals, mainW, Hp, notes);
        if (uncals.length) this._drawUncal(uncals, side ? groupW : width, Hp, !side && cals.length > 0, !cals.length, notes);
      }
      if (notes.length) {
        var list = htmlEl('ul', 'ga-lst-notes', this._body);
        notes.forEach(function (note) {
          var item = htmlEl('li', note.error ? 'is-error' : '', list, note.text);
          if (note.key) item.setAttribute('data-key', note.key);
        });
      }
      this._applyHighlight();
    }
  }

  global.GelAnalyzer.Viz.LaneStrips = {
    Panel: LaneStripsPanel,
    // Pure, exposed for browser-side checks with crafted payloads (spec §7.1).
    _normalizeTicks: normalizeTicks,
    _segments: segments,
    _buildAxis: buildAxis,
    _drawFrame: drawFrame,
    _formatKda: formatKda,
    mount: function (containerEl, cfg) {
      cfg = cfg || {};
      var handle = Viz.mount(containerEl, {
        panelDefs: [{ name: 'strips', PanelClass: LaneStripsPanel, containerClass: 'ga-lst' }],
        eventBus: cfg.eventBus,
        options: { strips: cfg.strips || [], kind: cfg.kind || '', showProfiles: cfg.showProfiles !== false },
      });
      // Viz.mount attaches the root after the panels' init(): the width is only measurable now.
      handle.getPanel('strips').render();
      return {
        update: function (opts) {
          var panel = handle.getPanel('strips');
          Object.keys(opts || {}).forEach(function (key) { panel.options[key] = opts[key]; });
          panel.render();
        },
        destroy: function () { handle.destroy(); },
      };
    },
  };
})(window);
